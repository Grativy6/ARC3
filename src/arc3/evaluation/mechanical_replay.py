"""Read-only mechanical-policy replay over immutable official evidence.

This module deliberately has no environment or SDK dependency.  It parses the
JSONL representation already written by the pinned official recorder into the
first-party immutable observation boundary, or reconstructs that same boundary
from a sealed first-party trace without rewriting an incomplete SDK recording.
It replays observed consequences through the production mechanical policy and
selects one *unsubmitted* next action.  Selection is cancelled before return,
so replay cannot manufacture an environment receipt or learner update for an
action that never crossed the environment boundary.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
from collections import Counter
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any, cast

from arc3.adapters import GridFrame, Observation
from arc3.errors import EvaluationError, TraceError
from arc3.evaluation.artifacts import canonical_json_bytes, sha256_bytes
from arc3.integrity import read_bounded_regular_snapshot
from arc3.mechanics.visual_causal import VisualCausalPolicy
from arc3.trace import EventJournal, ReplayEngine, TraceEvent
from arc3.types import (
    ActionName,
    ActionRequest,
    Coordinate,
    GameId,
    GameStateName,
    JSONScalar,
    JSONValue,
)

MAX_RECORDING_BYTES = 64 * 1024 * 1024
MAX_RECORDING_ROWS = 10_000
MAX_RECORDING_LINE_BYTES = 2 * 1024 * 1024
MAX_TRACE_BYTES = 128 * 1024 * 1024
MAX_TRACE_EVENTS = 60_002
MAX_TRACE_SUBMISSIONS = 10_000

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
        "hierarchy_residual_linked_relation_rejected_count",
        "hierarchy_external_residual_linked_relation_rejected_count",
        "hierarchy_raw_matching_composite_relation_rejected_count",
        "hierarchy_preterminal_retry_count",
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


def _normalized_trace_sha256(value: str, *, field: str) -> str:
    normalized = value.lower()
    if not normalized.startswith("sha256:"):
        normalized = f"sha256:{normalized}"
    digest = normalized.removeprefix("sha256:")
    if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
        raise MechanicalReplayError(f"{field} is not a full SHA-256 digest")
    return normalized


def _sealed_trace_projection(path: Path) -> tuple[dict[str, str], int]:
    try:
        entries = tuple(path.rglob("*"))
    except OSError as error:
        raise MechanicalReplayError(f"sealed trace inventory is unreadable: {error}") from error
    if any(entry.is_symlink() or entry.is_junction() for entry in entries):
        raise MechanicalReplayError("sealed trace contains an aliased entry")
    projection: dict[str, str] = {}
    byte_length = 0
    for entry in sorted(entries):
        if entry.is_dir():
            continue
        if not entry.is_file():
            raise MechanicalReplayError("sealed trace contains a non-regular entry")
        relative = entry.relative_to(path).as_posix()
        try:
            snapshot = read_bounded_regular_snapshot(
                root=path,
                path=entry,
                max_bytes=MAX_TRACE_BYTES,
                path_label=relative,
            )
        except (OSError, ValueError) as error:
            raise MechanicalReplayError(
                f"sealed trace file {relative} is unreadable: {error}"
            ) from error
        byte_length += len(snapshot)
        if byte_length > MAX_TRACE_BYTES:
            raise MechanicalReplayError("sealed trace byte length is outside the replay bound")
        projection[relative] = sha256_bytes(snapshot)
    if not projection or byte_length <= 0:
        raise MechanicalReplayError("sealed trace byte length is outside the replay bound")
    return projection, byte_length


def _close_trace_copy(
    journal: EventJournal | None,
    temporary: tempfile.TemporaryDirectory[str],
) -> None:
    try:
        if journal is not None:
            journal.close()
    finally:
        temporary.cleanup()


def _validate_compressed_copy_paths(path: Path, manifest_snapshot: bytes) -> None:
    try:
        raw_manifest = json.loads(manifest_snapshot)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise MechanicalReplayError(f"sealed trace manifest is invalid JSON: {error}") from error
    if not isinstance(raw_manifest, dict):
        raise MechanicalReplayError("sealed trace manifest must be an object")
    chunks = raw_manifest.get("chunks")
    if not isinstance(chunks, list):
        raise MechanicalReplayError("sealed trace manifest chunks must be an array")
    for index, raw_chunk in enumerate(chunks):
        if not isinstance(raw_chunk, dict):
            raise MechanicalReplayError(f"sealed trace manifest chunk {index} is not an object")
        value = raw_chunk.get("compressed_copy_path")
        if value is None:
            continue
        if not isinstance(value, str):
            raise MechanicalReplayError(
                f"sealed trace manifest chunk {index} compressed_copy_path is invalid"
            )
        relative = PurePosixPath(value)
        if (
            not value
            or relative.is_absolute()
            or "\\" in value
            or any(part in {"", ".", ".."} for part in relative.parts)
        ):
            raise MechanicalReplayError(
                f"sealed trace manifest chunk {index} compressed_copy_path is unsafe"
            )
        candidate = path.joinpath(*relative.parts)
        if not candidate.is_file() or candidate.is_symlink() or candidate.is_junction():
            raise MechanicalReplayError(
                f"sealed trace manifest chunk {index} compressed copy is not a regular file"
            )
        try:
            resolved = candidate.resolve(strict=True)
            resolved.relative_to(path)
        except (OSError, ValueError) as error:
            raise MechanicalReplayError(
                f"sealed trace manifest chunk {index} compressed_copy_path escapes its root"
            ) from error


def _trace_nonnegative_int(value: object, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise MechanicalReplayError(f"sealed trace field {field} must be a non-negative integer")
    return value


def _trace_action(value: object, *, field: str) -> ActionRequest:
    if not isinstance(value, dict) or set(value) != {"coordinate", "name"}:
        raise MechanicalReplayError(
            f"sealed trace field {field} must contain exactly coordinate and name"
        )
    raw_name = value.get("name")
    if not isinstance(raw_name, str) or raw_name not in _ACTION_BY_NAME:
        raise MechanicalReplayError(f"sealed trace field {field} has an unknown action name")
    name = _ACTION_BY_NAME[raw_name]
    raw_coordinate = value.get("coordinate")
    if name is not ActionName.ACTION6:
        if raw_coordinate is not None:
            raise MechanicalReplayError(
                f"sealed trace field {field} gives a coordinate to a non-coordinate action"
            )
        return ActionRequest(name)
    if not isinstance(raw_coordinate, dict) or set(raw_coordinate) != {"x", "y"}:
        raise MechanicalReplayError(
            f"sealed trace field {field} ACTION6 coordinate must contain exactly x and y"
        )
    x = raw_coordinate.get("x")
    y = raw_coordinate.get("y")
    if (
        isinstance(x, bool)
        or not isinstance(x, int)
        or isinstance(y, bool)
        or not isinstance(y, int)
    ):
        raise MechanicalReplayError(
            f"sealed trace field {field} ACTION6 coordinate must contain exact integers"
        )
    try:
        return ActionRequest(name, Coordinate(x, y))
    except ValueError as error:
        raise MechanicalReplayError(
            f"sealed trace field {field} ACTION6 coordinate is invalid: {error}"
        ) from error


def _trace_action_dict(action: ActionRequest) -> dict[str, JSONValue]:
    coordinate: dict[str, JSONValue] | None = None
    if action.coordinate is not None:
        coordinate = {"x": action.coordinate.x, "y": action.coordinate.y}
    return {"coordinate": coordinate, "name": action.name.value}


def _trace_observation(
    replay: ReplayEngine,
    event: TraceEvent,
    *,
    returned_action: ActionRequest | None,
) -> Observation:
    payload = event.payload
    raw_frames = payload.get("frames")
    if not isinstance(raw_frames, list) or not raw_frames:
        raise MechanicalReplayError(
            f"sealed observation {event.event_id} has no replayable frame descriptors"
        )
    frames: list[GridFrame] = []
    for frame_index, raw_descriptor in enumerate(raw_frames):
        if not isinstance(raw_descriptor, dict):
            raise MechanicalReplayError(
                f"sealed observation {event.event_id} frame {frame_index} is not an object"
            )
        blob_hash = raw_descriptor.get("blob_hash")
        if not isinstance(blob_hash, str):
            raise MechanicalReplayError(
                f"sealed observation {event.event_id} frame {frame_index} has no blob hash"
            )
        try:
            frame = GridFrame(replay.blobs.get_frame(blob_hash))
        except (OSError, TraceError, ValueError) as error:
            raise MechanicalReplayError(
                f"sealed observation {event.event_id} frame {frame_index} is unavailable: "
                f"{type(error).__name__}: {error}"
            ) from error
        if (
            raw_descriptor.get("width") != frame.width
            or raw_descriptor.get("height") != frame.height
            or raw_descriptor.get("palette") != list(frame.palette)
        ):
            raise MechanicalReplayError(
                f"sealed observation {event.event_id} frame {frame_index} descriptor disagrees "
                "with its blob"
            )
        frames.append(frame)

    raw_state = payload.get("game_state")
    if not isinstance(raw_state, str):
        raise MechanicalReplayError(f"sealed observation {event.event_id} state is invalid")
    try:
        state = GameStateName(raw_state)
    except ValueError as error:
        raise MechanicalReplayError(
            f"sealed observation {event.event_id} state is unknown"
        ) from error

    raw_actions = payload.get("available_actions")
    if not isinstance(raw_actions, list):
        raise MechanicalReplayError(
            f"sealed observation {event.event_id} available actions are invalid"
        )
    available: list[ActionName] = []
    for raw_action in raw_actions:
        if not isinstance(raw_action, str) or raw_action not in _ACTION_BY_NAME:
            raise MechanicalReplayError(
                f"sealed observation {event.event_id} has an unknown available action"
            )
        action = _ACTION_BY_NAME[raw_action]
        if action in available:
            raise MechanicalReplayError(
                f"sealed observation {event.event_id} repeats an available action"
            )
        available.append(action)

    raw_metadata = payload.get("upstream_metadata")
    if not isinstance(raw_metadata, dict):
        raise MechanicalReplayError(
            f"sealed observation {event.event_id} upstream metadata is invalid"
        )
    levels_completed = _trace_nonnegative_int(
        raw_metadata.get("levels_completed"),
        field=f"observation {event.event_id} levels_completed",
    )
    win_levels = _trace_nonnegative_int(
        raw_metadata.get("win_levels"),
        field=f"observation {event.event_id} win_levels",
    )
    full_reset = raw_metadata.get("full_reset")
    if not isinstance(full_reset, bool):
        raise MechanicalReplayError(
            f"sealed observation {event.event_id} full_reset must be boolean"
        )
    upstream_metadata: list[tuple[str, JSONScalar]] = []
    for key, value in sorted(raw_metadata.items()):
        if key in {"full_reset", "levels_completed", "win_levels"}:
            continue
        if value is None or isinstance(value, (bool, int, float, str)):
            upstream_metadata.append((key, value))
        else:
            raise MechanicalReplayError(
                f"sealed observation {event.event_id} metadata field {key!r} is not scalar"
            )
    upstream_session_id = payload.get("upstream_session_id")
    if upstream_session_id is not None and (
        not isinstance(upstream_session_id, str) or not upstream_session_id
    ):
        raise MechanicalReplayError(
            f"sealed observation {event.event_id} session identity is invalid"
        )
    return Observation(
        game_id=GameId(event.game_id),
        frames=tuple(frames),
        state=state,
        levels_completed=levels_completed,
        win_levels=win_levels,
        available_actions=tuple(available),
        full_reset=full_reset,
        returned_action=returned_action,
        upstream_session_id=upstream_session_id,
        upstream_metadata=tuple(upstream_metadata),
    )


def _expected_trace_candidates(observation: Observation) -> list[dict[str, JSONValue]]:
    if observation.state in {GameStateName.GAME_OVER, GameStateName.NOT_PLAYED}:
        return [{"action": ActionName.RESET.value, "source": "mandatory_lifecycle"}]
    return [
        {"action": action.value, "source": "advertised"} for action in observation.available_actions
    ]


def _validate_trace_candidates(event: TraceEvent, observation: Observation) -> None:
    if event.payload.get("candidates") != _expected_trace_candidates(observation):
        raise MechanicalReplayError(
            f"sealed candidate event at step {event.step_index} disagrees with the observation"
        )


def _validate_trace_event_position(
    event: TraceEvent,
    *,
    episode_id: str,
    level_index: int,
    step_index: int,
) -> None:
    if (
        event.episode_id != episode_id
        or event.level_index != level_index
        or event.step_index != step_index
    ):
        raise MechanicalReplayError(
            f"sealed event {event.event_id} has inconsistent episode/level/step identity"
        )


def _stage_and_cancel_candidate(
    policy: VisualCausalPolicy,
    observation: Observation,
) -> tuple[
    dict[str, JSONValue],
    dict[str, JSONValue],
    dict[str, JSONValue],
    str,
]:
    receipts_before_candidate = len(policy.receipts)
    learner = policy.mechanical_learner
    if learner is None or learner.pending:
        raise MechanicalReplayError("mechanical learner is not quiescent before next selection")
    candidate = policy.select(observation)
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
        raise MechanicalReplayError("unsubmitted candidate cancellation did not restore quiescence")
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
    return candidate_payload, cancellation_payload, family_payload, selected_snapshot_hash


def replay_unfinished_mechanical_trace(
    trace_path: Path,
    *,
    expected_run_id: str,
    expected_game_id: str,
    expected_git_commit: str,
    expected_trace_manifest_hash: str,
    expected_tail_event_hash: str,
    expected_event_count: int,
    expected_submission_count: int,
    expected_final_state: GameStateName,
    expected_levels_completed: int,
    expected_win_levels: int,
    max_coordinate_candidates: int = 8,
) -> dict[str, JSONValue]:
    """Replay one complete sealed trace without repairing its SDK recording.

    The immutable trace must contain exactly one initial observation, one
    six-event cycle for each submitted action, and one final candidate event.
    The initial SDK ``returned_action`` is not represented by the trace schema
    and is therefore kept explicitly unavailable rather than invented.
    """

    if not expected_run_id.strip() or not expected_game_id.strip():
        raise MechanicalReplayError("expected trace run_id and game_id must be non-empty")
    if not expected_git_commit.strip():
        raise MechanicalReplayError("expected trace Git commit must be non-empty")
    if expected_final_state is not GameStateName.NOT_FINISHED:
        raise MechanicalReplayError("next-action trace replay requires final NOT_FINISHED")
    if (
        isinstance(expected_event_count, bool)
        or not isinstance(expected_event_count, int)
        or not 2 <= expected_event_count <= MAX_TRACE_EVENTS
    ):
        raise MechanicalReplayError("expected trace event count is outside the replay bound")
    if (
        isinstance(expected_submission_count, bool)
        or not isinstance(expected_submission_count, int)
        or not 1 <= expected_submission_count <= MAX_TRACE_SUBMISSIONS
    ):
        raise MechanicalReplayError("expected trace submission count is outside the replay bound")
    complete_event_count = 2 + (6 * expected_submission_count)
    if expected_event_count != complete_event_count:
        raise MechanicalReplayError(
            "expected trace event count does not describe complete six-event action cycles"
        )
    if expected_levels_completed < 0 or expected_win_levels < 0:
        raise MechanicalReplayError("expected final counters must be non-negative")
    if max_coordinate_candidates <= 0 or max_coordinate_candidates > 64:
        raise MechanicalReplayError("max coordinate candidates must be within 1..64")
    named_manifest_hash = _normalized_trace_sha256(
        expected_trace_manifest_hash,
        field="expected trace manifest hash",
    )
    named_tail_hash = _normalized_trace_sha256(
        expected_tail_event_hash,
        field="expected trace tail event hash",
    )

    try:
        supplied_path = trace_path.absolute()
    except OSError as error:
        raise MechanicalReplayError(f"sealed trace root is unavailable: {error}") from error
    if any(
        candidate.exists() and (candidate.is_symlink() or candidate.is_junction())
        for candidate in (supplied_path, *supplied_path.parents)
    ):
        raise MechanicalReplayError("sealed trace root must not cross an aliased path")
    try:
        path = supplied_path.resolve(strict=True)
    except OSError as error:
        raise MechanicalReplayError(f"sealed trace root is unavailable: {error}") from error
    if not path.is_dir():
        raise MechanicalReplayError("sealed trace root must be a direct regular directory")
    manifest_path = path / "manifest.json"
    active_path = path / "active.jsonl"
    for required in (manifest_path, active_path):
        if not required.is_file() or required.is_symlink() or required.is_junction():
            raise MechanicalReplayError(
                f"sealed trace required file {required.name} is unavailable or aliased"
            )
    blobs_path = path / "blobs"
    if not blobs_path.is_dir() or blobs_path.is_symlink() or blobs_path.is_junction():
        raise MechanicalReplayError("sealed trace blobs directory is unavailable or aliased")
    try:
        manifest_snapshot = read_bounded_regular_snapshot(
            root=path,
            path=manifest_path,
            max_bytes=MAX_TRACE_BYTES,
            path_label="manifest.json",
        )
        active_snapshot = read_bounded_regular_snapshot(
            root=path,
            path=active_path,
            max_bytes=1,
            path_label="active.jsonl",
        )
    except (OSError, ValueError) as error:
        raise MechanicalReplayError(
            f"sealed trace active journal is unreadable: {error}"
        ) from error
    if active_snapshot:
        raise MechanicalReplayError("sealed trace contains unsealed active events")
    _validate_compressed_copy_paths(path, manifest_snapshot)
    trace_projection, trace_byte_length = _sealed_trace_projection(path)
    trace_projection_hash = sha256_bytes(canonical_json_bytes(trace_projection))

    temporary = tempfile.TemporaryDirectory(prefix="arc3-mechanical-trace-replay-")
    copied_path = Path(temporary.name) / "trace"
    journal: EventJournal | None = None
    try:
        shutil.copytree(path, copied_path)
        copied_projection, copied_byte_length = _sealed_trace_projection(copied_path)
        source_projection_after_copy, source_byte_length_after_copy = _sealed_trace_projection(path)
        if (
            copied_projection != trace_projection
            or copied_byte_length != trace_byte_length
            or source_projection_after_copy != trace_projection
            or source_byte_length_after_copy != trace_byte_length
        ):
            raise MechanicalReplayError("sealed trace changed while its immutable copy was made")
        try:
            copied_manifest_snapshot = read_bounded_regular_snapshot(
                root=copied_path,
                path=copied_path / "manifest.json",
                max_bytes=MAX_TRACE_BYTES,
                path_label="manifest.json",
            )
        except (OSError, ValueError) as error:
            raise MechanicalReplayError(
                f"copied sealed trace manifest is unreadable: {error}"
            ) from error
        _validate_compressed_copy_paths(copied_path, copied_manifest_snapshot)
        if copied_manifest_snapshot != manifest_snapshot:
            raise MechanicalReplayError(
                "copied sealed trace manifest changed after projection validation"
            )
        journal = EventJournal(copied_path, run_id=expected_run_id, fsync_on_flush=False)
        replay = ReplayEngine(journal)
        events = replay.verify_integrity(verify_blobs=True)
        replayed_frames = replay.replay_frames()
        manifest_hash = journal.manifest.manifest_hash
    except MechanicalReplayError:
        _close_trace_copy(journal, temporary)
        raise
    except (OSError, TraceError, ValueError) as error:
        _close_trace_copy(journal, temporary)
        raise MechanicalReplayError(
            f"sealed trace integrity verification failed: {type(error).__name__}: {error}"
        ) from error
    except BaseException:
        _close_trace_copy(journal, temporary)
        raise

    try:
        policy = VisualCausalPolicy(max_coordinate_candidates=max_coordinate_candidates)
    except BaseException:
        _close_trace_copy(journal, temporary)
        raise
    state_counts: Counter[str] = Counter()
    action_counts: Counter[str] = Counter()
    reset_count = 0
    matched = 0
    regenerated_receipts = 0
    current: Observation | None = None
    try:
        if len(events) != expected_event_count:
            raise MechanicalReplayError(
                f"sealed trace event count {len(events)} != expected {expected_event_count}"
            )
        if manifest_hash != named_manifest_hash:
            raise MechanicalReplayError(
                f"sealed trace manifest hash {manifest_hash} != expected {named_manifest_hash}"
            )
        tail_hash = events[-1].event_hash if events else None
        if tail_hash != named_tail_hash:
            raise MechanicalReplayError(
                f"sealed trace tail hash {tail_hash} != expected {named_tail_hash}"
            )
        if any(event.run_id != expected_run_id for event in events):
            raise MechanicalReplayError("sealed trace contains a different run identity")
        if any(event.game_id != expected_game_id for event in events):
            raise MechanicalReplayError("sealed trace contains a different game identity")
        if any(event.code_identity.git_commit != expected_git_commit for event in events):
            raise MechanicalReplayError("sealed trace contains a different generator commit")
        episode_ids = {event.episode_id for event in events}
        if len(episode_ids) != 1:
            raise MechanicalReplayError("sealed trace spans more than one episode identity")
        episode_id = next(iter(episode_ids))

        initial = events[0]
        if initial.event_type != "observation.received":
            raise MechanicalReplayError("sealed trace does not start with its initial observation")
        current = _trace_observation(replay, initial, returned_action=None)
        _validate_trace_event_position(
            initial,
            episode_id=episode_id,
            level_index=current.levels_completed,
            step_index=0,
        )
        if not current.full_reset:
            raise MechanicalReplayError("sealed initial observation is not marked full_reset")
        if current.state is GameStateName.WIN:
            raise MechanicalReplayError(
                "sealed unfinished replay contains authoritative WIN at its initial boundary"
            )
        if current.levels_completed > current.win_levels:
            raise MechanicalReplayError("sealed initial observation exceeds win_levels")
        upstream_session_id = current.upstream_session_id

        cursor = 1
        for submission_index in range(expected_submission_count):
            cycle = events[cursor : cursor + 6]
            expected_types = (
                "action.candidates_generated",
                "action.selected",
                "action.submitted",
                "consequence.received",
                "observation.received",
                "mechanics.action_receipt",
            )
            if len(cycle) != 6 or tuple(event.event_type for event in cycle) != expected_types:
                raise MechanicalReplayError(
                    f"sealed trace action cycle {submission_index + 1} is incomplete or reordered"
                )
            candidates, selected_event, submitted, consequence, observed, mechanical = cycle
            for event in (candidates, selected_event, submitted, consequence, mechanical):
                _validate_trace_event_position(
                    event,
                    episode_id=episode_id,
                    level_index=current.levels_completed,
                    step_index=submission_index,
                )
            _validate_trace_candidates(candidates, current)

            recorded_action = _trace_action(
                selected_event.payload.get("selected_action"),
                field=f"action.selected step {submission_index}",
            )
            selected = policy.select(current)
            if selected != recorded_action:
                raise MechanicalReplayError(
                    f"policy divergence at sealed submission {submission_index + 1}: "
                    f"selected {_action_dict(selected)!r}, trace "
                    f"{_action_dict(recorded_action)!r}"
                )
            selected_payload = _trace_action_dict(recorded_action)
            if (
                submitted.payload.get("selected_event_id") != selected_event.event_id
                or submitted.payload.get("action") != selected_payload
                or consequence.payload.get("action") != selected_payload
            ):
                raise MechanicalReplayError(
                    f"sealed action linkage disagrees at submission {submission_index + 1}"
                )
            if consequence.payload.get("before_state") != current.state.value:
                raise MechanicalReplayError(
                    f"sealed consequence before-state disagrees at submission {submission_index + 1}"
                )

            after = _trace_observation(replay, observed, returned_action=recorded_action)
            if after.state is GameStateName.WIN:
                raise MechanicalReplayError(
                    f"sealed unfinished replay contains authoritative WIN at submission "
                    f"{submission_index + 1}"
                )
            _validate_trace_event_position(
                observed,
                episode_id=episode_id,
                level_index=after.levels_completed,
                step_index=submission_index + 1,
            )
            if (
                consequence.payload.get("returned_frames") != observed.payload.get("frames")
                or consequence.payload.get("after_state") != after.state.value
                or consequence.payload.get("levels_completed") != after.levels_completed
            ):
                raise MechanicalReplayError(
                    f"sealed consequence/observation linkage disagrees at submission "
                    f"{submission_index + 1}"
                )
            if after.full_reset:
                raise MechanicalReplayError(
                    f"sealed consequence {submission_index + 1} unexpectedly repeats full_reset"
                )
            if after.win_levels != current.win_levels:
                raise MechanicalReplayError(
                    f"sealed consequence {submission_index + 1} changes win_levels"
                )
            if after.levels_completed < current.levels_completed:
                raise MechanicalReplayError(
                    f"sealed consequence {submission_index + 1} regresses levels_completed"
                )
            if after.levels_completed > after.win_levels:
                raise MechanicalReplayError(
                    f"sealed consequence {submission_index + 1} exceeds win_levels"
                )
            if after.upstream_session_id != upstream_session_id:
                raise MechanicalReplayError(
                    f"sealed consequence {submission_index + 1} changes session identity"
                )
            if recorded_action.name is ActionName.RESET:
                if current.state not in {GameStateName.GAME_OVER, GameStateName.NOT_PLAYED}:
                    raise MechanicalReplayError(
                        f"sealed RESET {submission_index + 1} lacks a lifecycle boundary"
                    )
                if (
                    after.state is not GameStateName.NOT_FINISHED
                    or after.levels_completed != current.levels_completed
                ):
                    raise MechanicalReplayError(
                        f"sealed RESET {submission_index + 1} does not preserve level recovery"
                    )
                reset_count += 1
            elif current.state in {GameStateName.GAME_OVER, GameStateName.NOT_PLAYED}:
                raise MechanicalReplayError(
                    f"sealed submission {submission_index + 1} bypasses mandatory RESET"
                )
            elif recorded_action.name not in current.available_actions:
                raise MechanicalReplayError(
                    f"sealed submission {submission_index + 1} was not advertised"
                )

            if mechanical.payload.get("source_consequence_event_id") != consequence.event_id:
                raise MechanicalReplayError(
                    f"sealed mechanics receipt {submission_index + 1} links to the wrong consequence"
                )
            trace_receipt = mechanical.payload.get("receipt")
            if not isinstance(trace_receipt, dict):
                raise MechanicalReplayError(
                    f"sealed mechanics receipt {submission_index + 1} is malformed"
                )
            policy.accept_consequence(after)
            durable = policy.drain_durable_receipts()
            if len(durable) != 1 or durable[0] != trace_receipt:
                raise MechanicalReplayError(
                    f"regenerated mechanics receipt disagrees at submission {submission_index + 1}"
                )
            regenerated_receipts += 1
            matched += 1
            action_counts[recorded_action.name.value] += 1
            state_counts[after.state.value] += 1
            current = after
            cursor += 6

        terminal_candidates = events[cursor:]
        if len(terminal_candidates) != 1 or terminal_candidates[0].event_type != (
            "action.candidates_generated"
        ):
            raise MechanicalReplayError(
                "sealed trace does not end with exactly one unsubmitted candidate event"
            )
        _validate_trace_event_position(
            terminal_candidates[0],
            episode_id=episode_id,
            level_index=current.levels_completed,
            step_index=expected_submission_count,
        )
        _validate_trace_candidates(terminal_candidates[0], current)
        if (
            current.state is not expected_final_state
            or current.levels_completed != expected_levels_completed
            or current.win_levels != expected_win_levels
        ):
            raise MechanicalReplayError(
                "sealed trace final observation disagrees with the named evidence boundary"
            )
        if (
            matched != expected_submission_count
            or regenerated_receipts != expected_submission_count
            or len(policy.receipts) != expected_submission_count
        ):
            raise MechanicalReplayError("sealed trace replay receipt cardinality is inconsistent")

        candidate, cancellation, family, snapshot_hash = _stage_and_cancel_candidate(
            policy,
            current,
        )
        final_projection, final_byte_length = _sealed_trace_projection(path)
        if final_projection != trace_projection or final_byte_length != trace_byte_length:
            raise MechanicalReplayError("sealed trace changed during read-only replay")
        return {
            "boundaries": {
                "completion_claimed": False,
                "environment_actions_issued": False,
                "game_source_inspected": False,
                "holdout_accessed": False,
                "initial_returned_action_represented": False,
                "initial_returned_action_reconstructed": False,
                "recording_rewritten": False,
                "session_or_adapter_constructed": False,
                "trace_root_modified": False,
            },
            "candidate_next_submission": candidate,
            "cancellation_verification": cancellation,
            "evidence_completeness": {
                "official_recording_evaluated": False,
                "receipt_complete": False,
                "recording_verified": False,
                "run_evidence_complete": False,
                "trace_replay_does_not_repair_sdk_recording": True,
            },
            "family_state_after_candidate_selection": family,
            "final_recorded_observation": _observation_dict(current),
            "method": {
                "consequence_order": (
                    "select(observation[n]); compare selected/submitted/consequence; "
                    "accept(observation[n+1]); compare regenerated durable receipt"
                ),
                "environment_boundary": "none",
                "final_selection": "selected once, captured, cancelled as unsubmitted",
                "initial_returned_action": "unavailable in trace schema; retained as None",
                "policy": "arc3.mechanics.visual_causal.VisualCausalPolicy",
                "trace_parser": "EventJournal plus ReplayEngine over sealed first-party blobs",
            },
            "replay_result": {
                "accepted_consequence_count": matched,
                "action_counts": {name: action_counts[name] for name in sorted(action_counts)},
                "candidate_cancelled": True,
                "candidate_cancellation_verified": True,
                "candidate_selection_snapshot_sha256": snapshot_hash,
                "matched_regenerated_mechanics_receipt_count": regenerated_receipts,
                "matched_submission_count": matched,
                "matched_through_submission": matched,
                "mismatch": None,
                "policy_receipt_count": len(policy.receipts),
                "reset_count": reset_count,
                "state_counts": {name: state_counts[name] for name in sorted(state_counts)},
                "status": "PASS_SEALED_TRACE_REPLAY",
            },
            "trace": {
                "active_byte_length": 0,
                "byte_length": trace_byte_length,
                "event_count": len(events),
                "game_id": expected_game_id,
                "manifest_hash": manifest_hash,
                "path": str(path),
                "projection_file_count": len(trace_projection),
                "projection_sha256": trace_projection_hash,
                "replayed_from_immutable_copy": True,
                "replayed_frame_count": len(replayed_frames),
                "run_id": expected_run_id,
                "submission_count": expected_submission_count,
                "tail_event_hash": named_tail_hash,
            },
        }
    except Exception:
        try:
            policy.cancel_unsubmitted_action()
            policy.close()
        except Exception:
            pass
        raise
    finally:
        _close_trace_copy(journal, temporary)


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
    "MAX_TRACE_BYTES",
    "MAX_TRACE_EVENTS",
    "MAX_TRACE_SUBMISSIONS",
    "MechanicalReplayError",
    "replay_unfinished_mechanical_recording",
    "replay_unfinished_mechanical_trace",
]
