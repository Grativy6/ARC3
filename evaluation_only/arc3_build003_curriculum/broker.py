"""Canonical byte-only observation/action boundary for evaluator workers."""

from __future__ import annotations

import json
import math
import multiprocessing
from collections.abc import Mapping, Sequence
from typing import cast

from arc3.adapters import GridFrame, Observation
from arc3.types import (
    ActionName,
    ActionRequest,
    Coordinate,
    GameId,
    GameStateName,
    JSONScalar,
)

OBSERVATION_SCHEMA = "arc3.build003.worker-observation.v0.1"
ACTION_SCHEMA = "arc3.build003.worker-action.v0.1"
_READY_SCHEMA = "arc3.build003.worker-ready.v0.1"
_ERROR_SCHEMA = "arc3.build003.worker-error.v0.1"
_SUMMARY_SCHEMA = "arc3.build003.worker-summary.v0.1"
_ALLOWED_METADATA = frozenset({"attempt", "step"})
_PRIVILEGED_KEYS = frozenset(
    {
        "family",
        "mechanic",
        "oracle",
        "palette",
        "resource",
        "resource_cap",
        "resource_start",
        "rules",
        "seed",
        "solution",
        "spec",
        "transition_truth",
        "walls",
    }
)


def canonical_bytes(value: object) -> bytes:
    """Encode a JSON value canonically, rejecting NaN and custom objects."""

    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _json_object(payload: bytes) -> dict[str, object]:
    try:
        value = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("worker payload is not valid UTF-8 canonical JSON") from error
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ValueError("worker payload must be a JSON object")
    result = cast(dict[str, object], value)
    if canonical_bytes(result) != payload:
        raise ValueError("worker payload is not canonically encoded")
    return result


def assert_unprivileged_payload(value: object) -> None:
    """Reject evaluator-only names anywhere in a worker-bound object."""

    if isinstance(value, Mapping):
        for key, child in value.items():
            if not isinstance(key, str):
                raise ValueError("worker payload keys must be strings")
            if key.casefold() in _PRIVILEGED_KEYS:
                raise ValueError(f"privileged evaluator field crossed worker boundary: {key}")
            assert_unprivileged_payload(child)
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for child in value:
            assert_unprivileged_payload(child)


def observation_to_bytes(observation: Observation) -> bytes:
    """Serialize exactly the normalized public observation contract."""

    metadata = dict(observation.upstream_metadata)
    unexpected = set(metadata) - _ALLOWED_METADATA
    if unexpected:
        raise ValueError(f"observation contains non-public metadata: {sorted(unexpected)}")
    returned = None
    if observation.returned_action is not None:
        returned = _action_object(observation.returned_action)
    value: dict[str, object] = {
        "available_actions": [action.value for action in observation.available_actions],
        "frames": [[list(row) for row in frame.cells] for frame in observation.frames],
        "full_reset": observation.full_reset,
        "game_id": str(observation.game_id),
        "levels_completed": observation.levels_completed,
        "metadata": [[key, metadata[key]] for key in sorted(metadata)],
        "returned_action": returned,
        "schema": OBSERVATION_SCHEMA,
        "state": observation.state.value,
        "win_levels": observation.win_levels,
    }
    assert_unprivileged_payload(value)
    return canonical_bytes(value)


def _exact_keys(value: Mapping[str, object], expected: set[str], kind: str) -> None:
    if set(value) != expected:
        raise ValueError(f"{kind} fields disagree with the frozen wire schema")


def _integer(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field} must be an integer")
    return value


def observation_from_bytes(payload: bytes) -> Observation:
    """Decode the public observation schema in a policy process."""

    value = _json_object(payload)
    assert_unprivileged_payload(value)
    expected = {
        "available_actions",
        "frames",
        "full_reset",
        "game_id",
        "levels_completed",
        "metadata",
        "returned_action",
        "schema",
        "state",
        "win_levels",
    }
    _exact_keys(value, expected, "observation")
    if value["schema"] != OBSERVATION_SCHEMA:
        raise ValueError("worker observation schema mismatch")
    game_id = value["game_id"]
    state = value["state"]
    full_reset = value["full_reset"]
    raw_frames = value["frames"]
    raw_actions = value["available_actions"]
    raw_metadata = value["metadata"]
    if not isinstance(game_id, str) or not game_id:
        raise ValueError("game_id must be a non-empty string")
    if not isinstance(state, str):
        raise ValueError("state must be a string")
    if not isinstance(full_reset, bool):
        raise ValueError("full_reset must be boolean")
    if not isinstance(raw_frames, list) or not raw_frames:
        raise ValueError("frames must be a non-empty list")
    if not isinstance(raw_actions, list) or not all(isinstance(item, str) for item in raw_actions):
        raise ValueError("available_actions must be strings")
    if not isinstance(raw_metadata, list):
        raise ValueError("metadata must be a list")

    frames: list[GridFrame] = []
    for raw_frame in raw_frames:
        if not isinstance(raw_frame, list):
            raise ValueError("each frame must be a list of rows")
        rows: list[list[int]] = []
        for raw_row in raw_frame:
            if not isinstance(raw_row, list):
                raise ValueError("each frame row must be a list")
            rows.append([_integer(cell, "frame cell") for cell in raw_row])
        frames.append(GridFrame.from_rows(rows))

    metadata: list[tuple[str, JSONScalar]] = []
    for item in raw_metadata:
        if not isinstance(item, list) or len(item) != 2 or not isinstance(item[0], str):
            raise ValueError("metadata entries must be key/value pairs")
        key = item[0]
        if key not in _ALLOWED_METADATA:
            raise ValueError("worker observation contains non-public metadata")
        scalar = item[1]
        if not isinstance(scalar, (str, int, float, bool)) and scalar is not None:
            raise ValueError("metadata values must be JSON scalars")
        metadata.append((key, scalar))

    returned_value = value["returned_action"]
    returned = None
    if returned_value is not None:
        if not isinstance(returned_value, dict):
            raise ValueError("returned_action must be an action object or null")
        returned = _action_from_object(cast(dict[str, object], returned_value))
    try:
        actions = tuple(ActionName(cast(str, item)) for item in raw_actions)
        normalized_state = GameStateName(state)
    except ValueError as error:
        raise ValueError("observation contains an unknown action or state") from error
    return Observation(
        game_id=GameId(game_id),
        frames=tuple(frames),
        state=normalized_state,
        levels_completed=_integer(value["levels_completed"], "levels_completed"),
        win_levels=_integer(value["win_levels"], "win_levels"),
        available_actions=actions,
        full_reset=full_reset,
        returned_action=returned,
        upstream_metadata=tuple(metadata),
    )


def _action_object(action: ActionRequest) -> dict[str, object]:
    coordinate = None
    if action.coordinate is not None:
        coordinate = {"x": action.coordinate.x, "y": action.coordinate.y}
    return {"coordinate": coordinate, "name": action.name.value}


def _action_from_object(value: dict[str, object]) -> ActionRequest:
    _exact_keys(value, {"coordinate", "name"}, "action")
    name = value["name"]
    coordinate = value["coordinate"]
    if not isinstance(name, str):
        raise ValueError("action name must be a string")
    normalized_coordinate = None
    if coordinate is not None:
        if not isinstance(coordinate, dict):
            raise ValueError("action coordinate must be an object or null")
        raw_coordinate = cast(dict[str, object], coordinate)
        _exact_keys(raw_coordinate, {"x", "y"}, "coordinate")
        normalized_coordinate = Coordinate(
            _integer(raw_coordinate["x"], "coordinate.x"),
            _integer(raw_coordinate["y"], "coordinate.y"),
        )
    try:
        return ActionRequest(ActionName(name), normalized_coordinate)
    except ValueError as error:
        raise ValueError("worker action is invalid") from error


def action_to_bytes(action: ActionRequest) -> bytes:
    value = {"action": _action_object(action), "schema": ACTION_SCHEMA}
    assert_unprivileged_payload(value)
    return canonical_bytes(value)


def action_from_bytes(payload: bytes) -> ActionRequest:
    value = _json_object(payload)
    assert_unprivileged_payload(value)
    _exact_keys(value, {"action", "schema"}, "action envelope")
    if value["schema"] != ACTION_SCHEMA or not isinstance(value["action"], dict):
        raise ValueError("worker action envelope is invalid")
    return _action_from_object(cast(dict[str, object], value["action"]))


class PolicyProcess:
    """Spawn a learner with no evaluator state or Python object references."""

    def __init__(
        self,
        *,
        variant: str = "BLA_CLEF_FULL",
        timeout_seconds: float = 10.0,
    ) -> None:
        if (
            isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, (int, float))
            or not math.isfinite(timeout_seconds)
            or timeout_seconds <= 0
        ):
            raise ValueError("timeout_seconds must be finite and positive")
        from .policy_worker import worker_main

        context = multiprocessing.get_context("spawn")
        parent, child = context.Pipe(duplex=True)
        process = context.Process(
            target=worker_main,
            args=(child, variant),
            name="arc3-build003-policy-worker",
            daemon=True,
        )
        process.start()
        child.close()
        self._connection = parent
        self._process = process
        self._timeout_seconds = timeout_seconds
        try:
            ready = self._receive_object()
        except Exception:
            self.close()
            raise
        if ready.get("schema") != _READY_SCHEMA:
            self.close()
            raise RuntimeError("policy worker did not return a ready receipt")
        raw_modules = ready.get("modules")
        raw_blocked = ready.get("blocked_imports")
        if not isinstance(raw_modules, list) or not all(
            isinstance(module, str) for module in raw_modules
        ):
            self.close()
            raise RuntimeError("policy worker returned an invalid module inventory")
        if not isinstance(raw_blocked, list) or not all(
            isinstance(module, str) for module in raw_blocked
        ):
            self.close()
            raise RuntimeError("policy worker returned an invalid import-denial receipt")
        self.loaded_modules = tuple(cast(list[str], raw_modules))
        self.blocked_privileged_imports = tuple(cast(list[str], raw_blocked))
        returned_variant = ready.get("variant")
        if returned_variant != variant:
            self.close()
            raise RuntimeError("policy worker variant identity mismatch")
        self.variant = variant

    @property
    def process_id(self) -> int | None:
        return self._process.pid

    def _receive_object(self) -> dict[str, object]:
        if not self._connection.poll(self._timeout_seconds):
            raise TimeoutError("policy worker exceeded its response timeout")
        value = _json_object(self._connection.recv_bytes())
        if value.get("schema") == _ERROR_SCHEMA:
            raise RuntimeError(f"policy worker failed: {value.get('message', 'unknown error')}")
        return value

    def request_action(self, observation: Observation) -> ActionRequest:
        if not self._process.is_alive():
            raise RuntimeError("policy worker is not alive")
        self._connection.send_bytes(observation_to_bytes(observation))
        if not self._connection.poll(self._timeout_seconds):
            raise TimeoutError("policy worker exceeded its action timeout")
        return action_from_bytes(self._connection.recv_bytes())

    def finalize(self, observation: Observation) -> dict[str, object]:
        """Deliver the last consequence and return observation-only telemetry."""

        if not self._process.is_alive():
            raise RuntimeError("policy worker is not alive")
        observation_value = _json_object(observation_to_bytes(observation))
        self._connection.send_bytes(
            canonical_bytes({"command": "finalize", "observation": observation_value})
        )
        summary = self._receive_object()
        if summary.get("schema") != _SUMMARY_SCHEMA:
            raise RuntimeError("policy worker returned an invalid summary receipt")
        return summary

    def close(self) -> None:
        if not hasattr(self, "_connection"):
            return
        if self._process.is_alive():
            try:
                self._connection.send_bytes(canonical_bytes({"command": "close"}))
                self._process.join(timeout=self._timeout_seconds)
            except (BrokenPipeError, EOFError, OSError):
                pass
        if self._process.is_alive():
            self._process.terminate()
            self._process.join(timeout=self._timeout_seconds)
        self._connection.close()

    def __enter__(self) -> PolicyProcess:
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()


__all__ = [
    "ACTION_SCHEMA",
    "OBSERVATION_SCHEMA",
    "_SUMMARY_SCHEMA",
    "PolicyProcess",
    "action_from_bytes",
    "action_to_bytes",
    "assert_unprivileged_payload",
    "canonical_bytes",
    "observation_from_bytes",
    "observation_to_bytes",
]
