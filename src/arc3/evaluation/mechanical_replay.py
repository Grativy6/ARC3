"""Read-only mechanical-policy replay over immutable official recordings.

This module deliberately has no environment or SDK dependency.  It parses the
JSONL representation already written by the pinned official recorder into the
first-party immutable observation boundary, replays recorded consequences
through the production mechanical policy, and selects one *unsubmitted* next
action.  Selection is cancelled before return, so replay cannot manufacture an
environment receipt or learner update for an action that never crossed the
environment boundary.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any, cast

from arc3.adapters import GridFrame, Observation
from arc3.errors import EvaluationError
from arc3.evaluation.artifacts import canonical_json_bytes, sha256_bytes
from arc3.integrity import read_bounded_regular_snapshot
from arc3.mechanics.visual_causal import VisualCausalPolicy
from arc3.types import (
    ActionName,
    ActionRequest,
    Coordinate,
    GameId,
    GameStateName,
    JSONValue,
)

MAX_RECORDING_BYTES = 64 * 1024 * 1024
MAX_RECORDING_ROWS = 10_000
MAX_RECORDING_LINE_BYTES = 2 * 1024 * 1024

_ACTION_BY_ID: dict[int, ActionName] = {
    0: ActionName.RESET,
    1: ActionName.ACTION1,
    2: ActionName.ACTION2,
    3: ActionName.ACTION3,
    4: ActionName.ACTION4,
    5: ActionName.ACTION5,
    6: ActionName.ACTION6,
    7: ActionName.ACTION7,
}
_ACTION_BY_NAME = {action.value: action for action in ActionName}
_TOP_LEVEL_KEYS = {"data", "timestamp"}
_DATA_KEYS = {
    "action_input",
    "available_actions",
    "frame",
    "full_reset",
    "game_id",
    "guid",
    "levels_completed",
    "state",
    "win_levels",
}
_ACTION_KEYS = {"data", "id", "reasoning"}


class MechanicalReplayError(EvaluationError):
    """The immutable recording cannot support an exact mechanical replay."""


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise MechanicalReplayError(f"recording JSON contains duplicate key {key!r}")
        result[key] = value
    return result


def _reject_nonfinite(value: str) -> None:
    raise MechanicalReplayError(f"recording JSON contains non-finite number {value}")


def _exact_nonnegative_int(value: object, *, field: str, line_number: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise MechanicalReplayError(
            f"recording line {line_number} field {field} must be a non-negative integer"
        )
    return value


def _parse_frame_rows(value: object, *, line_number: int, frame_index: int) -> GridFrame:
    if not isinstance(value, list) or not value:
        raise MechanicalReplayError(
            f"recording line {line_number} frame {frame_index} must contain rows"
        )
    rows: list[tuple[int, ...]] = []
    for row_index, raw_row in enumerate(value):
        if not isinstance(raw_row, list) or not raw_row:
            raise MechanicalReplayError(
                f"recording line {line_number} frame {frame_index} row {row_index} "
                "must use the pinned recorder's non-empty integer-list encoding"
            )
        if any(isinstance(cell, bool) or not isinstance(cell, int) for cell in raw_row):
            raise MechanicalReplayError(
                f"recording line {line_number} frame {frame_index} row {row_index} "
                "contains a non-integer cell"
            )
        rows.append(tuple(raw_row))
    try:
        return GridFrame(tuple(rows))
    except ValueError as error:
        raise MechanicalReplayError(
            f"recording line {line_number} frame {frame_index} is invalid: {error}"
        ) from error


def _parse_action(value: object, *, line_number: int) -> ActionRequest:
    if not isinstance(value, dict) or set(value) != _ACTION_KEYS:
        raise MechanicalReplayError(
            f"recording line {line_number} action_input must contain exactly "
            f"{sorted(_ACTION_KEYS)!r}"
        )
    raw_name = value.get("id")
    if not isinstance(raw_name, str) or raw_name not in _ACTION_BY_NAME:
        raise MechanicalReplayError(f"recording line {line_number} has an unknown action ID")
    reasoning = value.get("reasoning")
    if reasoning is not None and not isinstance(reasoning, dict):
        raise MechanicalReplayError(
            f"recording line {line_number} action reasoning must be an object or null"
        )
    action = _ACTION_BY_NAME[raw_name]
    raw_data = value.get("data")
    if not isinstance(raw_data, dict):
        raise MechanicalReplayError(f"recording line {line_number} action data must be an object")
    if action is not ActionName.ACTION6:
        if raw_data:
            raise MechanicalReplayError(
                f"recording line {line_number} non-coordinate action carries data"
            )
        return ActionRequest(action)
    if set(raw_data) != {"x", "y"}:
        raise MechanicalReplayError(
            f"recording line {line_number} ACTION6 must contain exactly x and y"
        )
    x = raw_data.get("x")
    y = raw_data.get("y")
    if (
        isinstance(x, bool)
        or not isinstance(x, int)
        or isinstance(y, bool)
        or not isinstance(y, int)
    ):
        raise MechanicalReplayError(
            f"recording line {line_number} ACTION6 coordinates must be exact integers"
        )
    try:
        coordinate = Coordinate(x, y)
    except ValueError as error:
        raise MechanicalReplayError(
            f"recording line {line_number} ACTION6 coordinate is invalid: {error}"
        ) from error
    return ActionRequest(action, coordinate)


def _parse_observation(
    raw_line: bytes,
    *,
    line_number: int,
    expected_game_id: str,
    expected_guid: str | None,
) -> tuple[Observation, str, str]:
    if not raw_line.endswith(b"\n"):
        raise MechanicalReplayError(f"recording line {line_number} is not newline terminated")
    encoded = raw_line[:-1]
    if encoded.endswith(b"\r"):
        encoded = encoded[:-1]
    if not encoded:
        raise MechanicalReplayError(f"recording line {line_number} is blank")
    try:
        text = encoded.decode("utf-8", errors="strict")
        raw_value: object = json.loads(
            text,
            object_pairs_hook=_strict_object,
            parse_constant=_reject_nonfinite,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise MechanicalReplayError(
            f"recording line {line_number} is not strict UTF-8 JSON"
        ) from error
    if not isinstance(raw_value, dict) or set(raw_value) != _TOP_LEVEL_KEYS:
        raise MechanicalReplayError(
            f"recording line {line_number} must contain exactly data and timestamp"
        )
    timestamp = raw_value.get("timestamp")
    data_value = raw_value.get("data")
    if not isinstance(timestamp, str) or not timestamp:
        raise MechanicalReplayError(
            f"recording line {line_number} timestamp must be a non-empty string"
        )
    if not isinstance(data_value, dict) or set(data_value) != _DATA_KEYS:
        raise MechanicalReplayError(f"recording line {line_number} has an unexpected data schema")
    data = cast(dict[str, object], data_value)
    game_id = data.get("game_id")
    guid = data.get("guid")
    state = data.get("state")
    full_reset = data.get("full_reset")
    if game_id != expected_game_id:
        raise MechanicalReplayError(
            f"recording line {line_number} game_id does not match the named target"
        )
    if not isinstance(guid, str) or not guid:
        raise MechanicalReplayError(f"recording line {line_number} guid is invalid")
    if expected_guid is not None and guid != expected_guid:
        raise MechanicalReplayError(f"recording line {line_number} changed guid")
    if not isinstance(state, str):
        raise MechanicalReplayError(f"recording line {line_number} state is not a string")
    try:
        normalized_state = GameStateName(state)
    except ValueError as error:
        raise MechanicalReplayError(
            f"recording line {line_number} has an unknown official state"
        ) from error
    if not isinstance(full_reset, bool):
        raise MechanicalReplayError(f"recording line {line_number} full_reset must be a boolean")

    raw_available = data.get("available_actions")
    if not isinstance(raw_available, list):
        raise MechanicalReplayError(
            f"recording line {line_number} available_actions must be a list"
        )
    available: list[ActionName] = []
    seen: set[ActionName] = set()
    for raw_action_id in raw_available:
        if (
            isinstance(raw_action_id, bool)
            or not isinstance(raw_action_id, int)
            or raw_action_id not in _ACTION_BY_ID
        ):
            raise MechanicalReplayError(
                f"recording line {line_number} has an invalid available action"
            )
        action_name = _ACTION_BY_ID[raw_action_id]
        if action_name in seen:
            raise MechanicalReplayError(f"recording line {line_number} repeats an available action")
        available.append(action_name)
        seen.add(action_name)

    raw_frames = data.get("frame")
    if not isinstance(raw_frames, list) or not raw_frames:
        raise MechanicalReplayError(f"recording line {line_number} has no frame")
    frames = tuple(
        _parse_frame_rows(frame, line_number=line_number, frame_index=index)
        for index, frame in enumerate(raw_frames)
    )
    action = _parse_action(data.get("action_input"), line_number=line_number)
    observation = Observation(
        game_id=GameId(expected_game_id),
        frames=frames,
        state=normalized_state,
        levels_completed=_exact_nonnegative_int(
            data.get("levels_completed"), field="levels_completed", line_number=line_number
        ),
        win_levels=_exact_nonnegative_int(
            data.get("win_levels"), field="win_levels", line_number=line_number
        ),
        available_actions=tuple(available),
        full_reset=full_reset,
        returned_action=action,
        upstream_session_id=guid,
        upstream_metadata=(("upstream_type", "arcengine.enums.FrameData"),),
    )
    return observation, guid, timestamp


def _action_dict(action: ActionRequest) -> dict[str, JSONValue]:
    coordinate: JSONValue = None
    if action.coordinate is not None:
        coordinate = [action.coordinate.x, action.coordinate.y]
    return {"coordinate": coordinate, "name": action.name.value}


def _observation_dict(observation: Observation) -> dict[str, JSONValue]:
    return {
        "available_actions": [action.value for action in observation.available_actions],
        "frame_count": len(observation.frames),
        "frame_sha256": str(observation.frames[-1].digest),
        "full_reset": observation.full_reset,
        "levels_completed": observation.levels_completed,
        "state": observation.state.value,
        "win_levels": observation.win_levels,
    }


def _family_state(snapshot: Mapping[str, JSONValue]) -> dict[str, JSONValue]:
    keys = (
        "child_isolation_distinct_strata_count",
        "child_isolation_hypothesis_rejected_count",
        "child_isolation_relation_rejected_count",
        "child_isolation_remaining_strata_count",
        "hierarchy_equal_relation_rejected_count",
        "hierarchy_bridge_relation_rejected_count",
        "hierarchy_lineage_lost",
        "hierarchy_relation_key",
        "hierarchy_search_deferred_count",
        "hierarchy_search_residual",
        "hierarchy_signature",
        "hierarchy_support_weights",
        "hierarchy_supports",
        "hierarchy_visible_node_relation_rejected_count",
        "hierarchy_weighted_relation_rejected_count",
        "pending_plan_actions",
        "receipt_count",
    )
    return {key: snapshot.get(key) for key in keys}


def _normalized_expected_sha256(value: str) -> str:
    normalized = value.lower()
    if normalized.startswith("sha256:"):
        normalized = normalized.removeprefix("sha256:")
    if len(normalized) != 64 or any(
        character not in "0123456789abcdef" for character in normalized
    ):
        raise MechanicalReplayError("expected recording SHA-256 is not a full hexadecimal digest")
    return normalized


def replay_unfinished_mechanical_recording(
    recording_path: Path,
    *,
    expected_game_id: str,
    expected_recording_sha256: str,
    expected_byte_length: int,
    expected_row_count: int,
    expected_final_state: GameStateName,
    expected_levels_completed: int,
    expected_win_levels: int,
    max_coordinate_candidates: int = 8,
) -> dict[str, JSONValue]:
    """Replay a pinned recording and return a bounded, non-environment receipt payload."""

    if not expected_game_id.strip():
        raise MechanicalReplayError("expected game_id must be non-empty")
    if expected_final_state is not GameStateName.NOT_FINISHED:
        raise MechanicalReplayError("next-action replay requires expected final state NOT_FINISHED")
    if expected_row_count < 2 or expected_row_count > MAX_RECORDING_ROWS:
        raise MechanicalReplayError("expected row count is outside the replay bound")
    if expected_byte_length <= 0 or expected_byte_length > MAX_RECORDING_BYTES:
        raise MechanicalReplayError("expected byte length is outside the replay bound")
    if expected_levels_completed < 0 or expected_win_levels < 0:
        raise MechanicalReplayError("expected final counters must be non-negative")
    if max_coordinate_candidates <= 0 or max_coordinate_candidates > 64:
        raise MechanicalReplayError("max coordinate candidates must be within 1..64")
    expected_digest = _normalized_expected_sha256(expected_recording_sha256)
    try:
        path = recording_path.resolve(strict=True)
        snapshot = read_bounded_regular_snapshot(
            root=path.parent,
            path=recording_path,
            max_bytes=MAX_RECORDING_BYTES,
            path_label=path.name,
        )
    except (OSError, ValueError) as error:
        raise MechanicalReplayError(f"recording snapshot is unavailable: {error}") from error
    if len(snapshot) != expected_byte_length:
        raise MechanicalReplayError(
            f"recording byte length {len(snapshot)} != expected {expected_byte_length}"
        )
    actual_digest = hashlib.sha256(snapshot).hexdigest()
    if actual_digest != expected_digest:
        raise MechanicalReplayError(
            f"recording SHA-256 {actual_digest} != expected {expected_digest}"
        )
    raw_lines = snapshot.splitlines(keepends=True)
    if len(raw_lines) != expected_row_count:
        raise MechanicalReplayError(
            f"recording row count {len(raw_lines)} != expected {expected_row_count}"
        )

    policy = VisualCausalPolicy(max_coordinate_candidates=max_coordinate_candidates)
    state_counts: Counter[str] = Counter()
    action_counts: Counter[str] = Counter()
    current: Observation | None = None
    guid: str | None = None
    first_timestamp: str | None = None
    final_timestamp: str | None = None
    previous_timestamp: datetime | None = None
    matched = 0
    row_count = 0
    try:
        for row_count, raw_line in enumerate(raw_lines, start=1):
            if len(raw_line) > MAX_RECORDING_LINE_BYTES:
                raise MechanicalReplayError(f"recording line {row_count} exceeds the byte bound")
            observation, observed_guid, timestamp = _parse_observation(
                raw_line,
                line_number=row_count,
                expected_game_id=expected_game_id,
                expected_guid=guid,
            )
            try:
                parsed_timestamp = datetime.fromisoformat(timestamp)
            except ValueError as error:
                raise MechanicalReplayError(
                    f"recording line {row_count} timestamp is not ISO-8601"
                ) from error
            if parsed_timestamp.tzinfo is None:
                raise MechanicalReplayError(
                    f"recording line {row_count} timestamp has no UTC offset"
                )
            if previous_timestamp is not None and parsed_timestamp <= previous_timestamp:
                raise MechanicalReplayError(
                    f"recording line {row_count} timestamp is not strictly increasing"
                )
            previous_timestamp = parsed_timestamp
            if guid is None:
                guid = observed_guid
                first_timestamp = timestamp
                if observation.returned_action != ActionRequest(ActionName.RESET):
                    raise MechanicalReplayError(
                        "recording first row is not the official RESET return"
                    )
                if not observation.full_reset:
                    raise MechanicalReplayError(
                        "recording first RESET return is not marked full_reset"
                    )
                if observation.levels_completed > observation.win_levels:
                    raise MechanicalReplayError(
                        "recording first row has levels_completed above win_levels"
                    )
                current = observation
                final_timestamp = timestamp
                continue
            if current is None:
                raise AssertionError("replay current observation was not initialized")
            if observation.full_reset:
                raise MechanicalReplayError(
                    f"recording line {row_count} unexpectedly repeats full_reset"
                )
            if observation.win_levels != current.win_levels:
                raise MechanicalReplayError(f"recording line {row_count} changed win_levels")
            if observation.levels_completed < current.levels_completed:
                raise MechanicalReplayError(
                    f"recording line {row_count} regressed levels_completed"
                )
            if observation.levels_completed > observation.win_levels:
                raise MechanicalReplayError(f"recording line {row_count} exceeds win_levels")
            selected = policy.select(current)
            if observation.returned_action != selected:
                raise MechanicalReplayError(
                    f"policy divergence at recorded submission {row_count - 1}: "
                    f"selected {_action_dict(selected)!r}, recorded "
                    f"{_action_dict(cast(ActionRequest, observation.returned_action))!r}"
                )
            policy.accept_consequence(observation)
            matched += 1
            action_counts[selected.name.value] += 1
            state_counts[observation.state.value] += 1
            current = observation
            final_timestamp = timestamp
        if current is None or guid is None or first_timestamp is None or final_timestamp is None:
            raise MechanicalReplayError("recording contains no observations")
        if current.state is not expected_final_state:
            raise MechanicalReplayError(
                f"final state {current.state.value} != expected {expected_final_state.value}"
            )
        if current.levels_completed != expected_levels_completed:
            raise MechanicalReplayError(
                "final levels_completed does not match the named evidence boundary"
            )
        if current.win_levels != expected_win_levels:
            raise MechanicalReplayError(
                "final win_levels does not match the named evidence boundary"
            )
        if matched != expected_row_count - 1 or len(policy.receipts) != matched:
            raise MechanicalReplayError("replay receipt cardinality is inconsistent")

        receipts_before_candidate = len(policy.receipts)
        learner = policy.mechanical_learner
        if learner is None or learner.pending:
            raise MechanicalReplayError("mechanical learner is not quiescent before next selection")
        candidate = policy.select(current)
        selected_snapshot = policy.snapshot()
        pending = selected_snapshot.get("pending_action")
        if not isinstance(pending, dict) or pending != _action_dict(candidate):
            raise MechanicalReplayError("selected candidate and policy pending action disagree")
        candidate_prediction_id = selected_snapshot.get("pending_prediction_id")
        if not isinstance(candidate_prediction_id, str) or not candidate_prediction_id:
            raise MechanicalReplayError("selected candidate has no pending prediction identity")
        if len(learner.pending) != 1:
            raise MechanicalReplayError("selected candidate did not stage exactly one prediction")
        candidate_payload: dict[str, JSONValue] = {
            "action": _action_dict(candidate),
            "pending_plan_actions_after_selection": selected_snapshot.get("pending_plan_actions"),
            "plan_signature": selected_snapshot.get("hierarchy_signature"),
            "prediction_id": candidate_prediction_id,
            "submitted": False,
            "support_weights": selected_snapshot.get("hierarchy_support_weights"),
            "supports": selected_snapshot.get("hierarchy_supports"),
        }
        family_payload = _family_state(selected_snapshot)
        selected_snapshot_hash = sha256_bytes(canonical_json_bytes(selected_snapshot))

        policy.cancel_unsubmitted_action()
        cancelled_snapshot = policy.snapshot()
        cancellation_verified = bool(
            cancelled_snapshot.get("pending_action") is None
            and cancelled_snapshot.get("pending_prediction_id") is None
            and len(policy.receipts) == receipts_before_candidate
            and not learner.pending
        )
        if not cancellation_verified:
            raise MechanicalReplayError(
                "unsubmitted candidate cancellation did not restore quiescence"
            )
        policy.close()
        cancellation_payload: dict[str, JSONValue] = {
            "close_status": "PASS",
            "learner_pending_after": len(learner.pending),
            "pending_action_after": cancelled_snapshot.get("pending_action"),
            "pending_action_before": selected_snapshot.get("pending_action"),
            "pending_prediction_after": cancelled_snapshot.get("pending_prediction_id"),
            "pending_prediction_before": candidate_prediction_id,
            "performed": True,
            "policy_receipt_count_after": len(policy.receipts),
            "policy_receipt_count_before": receipts_before_candidate,
            "verified": cancellation_verified,
        }

        return {
            "boundaries": {
                "completion_claimed": False,
                "environment_actions_issued": False,
                "game_source_inspected": False,
                "holdout_accessed": False,
                "session_or_adapter_constructed": False,
            },
            "candidate_next_submission": candidate_payload,
            "cancellation_verification": cancellation_payload,
            "family_state_after_candidate_selection": family_payload,
            "final_recorded_observation": _observation_dict(current),
            "method": {
                "consequence_order": "select(row[n-1]); compare row[n].action_input; accept(row[n])",
                "environment_boundary": "none",
                "final_selection": "selected once, captured, cancelled as unsubmitted",
                "policy": "arc3.mechanics.visual_causal.VisualCausalPolicy",
                "recording_parser": "strict first-party pinned-recorder JSONL parser",
            },
            "recording": {
                "byte_length": len(snapshot),
                "first_timestamp": first_timestamp,
                "guid": guid,
                "last_timestamp": final_timestamp,
                "path": str(path),
                "row_count": row_count,
                "sha256": f"sha256:{actual_digest}",
            },
            "replay_result": {
                "accepted_consequence_count": matched,
                "action_counts": {name: action_counts[name] for name in sorted(action_counts)},
                "candidate_selection_snapshot_sha256": selected_snapshot_hash,
                "candidate_cancelled": True,
                "candidate_cancellation_verified": cancellation_verified,
                "matched_submission_count": matched,
                "matched_through_submission": matched,
                "mismatch": None,
                "policy_receipt_count": len(policy.receipts),
                "state_counts": {name: state_counts[name] for name in sorted(state_counts)},
                "status": "PASS_RECORDED_FRAME_REPLAY",
            },
        }
    except Exception:
        try:
            policy.cancel_unsubmitted_action()
            policy.close()
        except Exception:
            pass
        raise


__all__ = [
    "MAX_RECORDING_BYTES",
    "MAX_RECORDING_LINE_BYTES",
    "MAX_RECORDING_ROWS",
    "MechanicalReplayError",
    "replay_unfinished_mechanical_recording",
]
