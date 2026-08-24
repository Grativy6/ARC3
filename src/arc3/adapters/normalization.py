"""Pure first-party normalization of upstream-shaped ARC observations."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

import numpy as np

from arc3.adapters import GridFrame, Observation
from arc3.errors import AdapterError
from arc3.types import (
    ActionName,
    ActionRequest,
    GameId,
    GameStateName,
    JSONScalar,
)

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


def normalize_game_state(value: object) -> GameStateName:
    """Copy an upstream state value into the first-party state vocabulary."""

    raw_value = getattr(value, "value", value)
    try:
        return GameStateName(str(raw_value))
    except ValueError:
        return GameStateName.UNKNOWN


def strict_nonnegative_int(value: object, *, field: str) -> int:
    """Validate one exact upstream counter without boolean coercion."""

    if isinstance(value, bool) or not isinstance(value, (int, np.integer)):
        raise AdapterError(f"upstream {field} must be an integer")
    normalized = int(value)
    if normalized < 0:
        raise AdapterError(f"upstream {field} must be non-negative")
    return normalized


def _action_id(value: object) -> int:
    raw_value = getattr(value, "value", value)
    if isinstance(raw_value, bool) or not isinstance(raw_value, (int, np.integer)):
        raise AdapterError("upstream action ID must be an integer")
    return int(raw_value)


def _action_name(value: object) -> ActionName:
    action_id = _action_id(value)
    try:
        return _ACTION_BY_ID[action_id]
    except KeyError as error:
        raise AdapterError(f"unknown upstream action ID {action_id}") from error


def _normalize_returned_action(frame_data: object) -> ActionRequest | None:
    action_input = getattr(frame_data, "action_input", None)
    if action_input is None:
        return None
    name = _action_name(getattr(action_input, "id", None))
    raw_data = getattr(action_input, "data", {})
    if not isinstance(raw_data, Mapping):
        raise AdapterError("upstream action data must be an object")
    if name is not ActionName.ACTION6:
        return ActionRequest(name)
    if set(raw_data) != {"x", "y"}:
        raise AdapterError("upstream ACTION6 response must contain exactly x and y")
    if any(
        isinstance(raw_data[key], bool) or not isinstance(raw_data[key], int) for key in ("x", "y")
    ):
        raise AdapterError("upstream ACTION6 coordinates must be exact integers")
    from arc3.types import Coordinate

    try:
        coordinate = Coordinate(raw_data["x"], raw_data["y"])
    except (TypeError, ValueError) as error:
        raise AdapterError("upstream ACTION6 coordinates are invalid") from error
    return ActionRequest(name, coordinate)


def _normalize_frames(value: object) -> tuple[GridFrame, ...]:
    if value is None:
        return ()
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise AdapterError("upstream frame collection must be a sequence")

    frames: list[GridFrame] = []
    for raw_frame in value:
        array = np.asarray(raw_frame)
        if array.ndim != 2:
            raise AdapterError("each upstream frame must be a two-dimensional grid")
        rows: list[tuple[int, ...]] = []
        for raw_row in array.tolist():
            if not isinstance(raw_row, list):
                raise AdapterError("upstream frame row must be a list")
            row: list[int] = []
            for cell in raw_row:
                if isinstance(cell, bool) or not isinstance(cell, int):
                    raise AdapterError("upstream frame cells must be integers")
                row.append(cell)
            rows.append(tuple(row))
        try:
            frames.append(GridFrame(tuple(rows)))
        except ValueError as error:
            raise AdapterError(f"invalid upstream frame: {error}") from error
    return tuple(frames)


def normalize_frame_data(frame_data: object) -> Observation:
    """Deep-copy one SDK-shaped response into immutable first-party values."""

    raw_game_id = getattr(frame_data, "game_id", None)
    if not isinstance(raw_game_id, str) or not raw_game_id.strip():
        raise AdapterError("upstream observation has no game_id")

    raw_actions = getattr(frame_data, "available_actions", None)
    if isinstance(raw_actions, (str, bytes)) or not isinstance(raw_actions, Sequence):
        raise AdapterError("upstream available_actions must be a sequence")
    available: list[ActionName] = []
    seen: set[ActionName] = set()
    for raw_action in raw_actions:
        action = _action_name(raw_action)
        if action not in seen:
            available.append(action)
            seen.add(action)

    raw_full_reset = getattr(frame_data, "full_reset", False)
    if not isinstance(raw_full_reset, bool):
        raise AdapterError("upstream full_reset must be a boolean")
    state_value = getattr(frame_data, "state", None)
    state = normalize_game_state(state_value)
    metadata: list[tuple[str, JSONScalar]] = [
        ("upstream_type", f"{type(frame_data).__module__}.{type(frame_data).__name__}")
    ]
    if state is GameStateName.UNKNOWN:
        metadata.append(("unknown_state", str(getattr(state_value, "value", state_value))))

    raw_guid = getattr(frame_data, "guid", None)
    if raw_guid is not None and not isinstance(raw_guid, str):
        raise AdapterError("upstream guid must be a string when present")

    return Observation(
        game_id=GameId(raw_game_id),
        frames=_normalize_frames(getattr(frame_data, "frame", None)),
        state=state,
        levels_completed=strict_nonnegative_int(
            getattr(frame_data, "levels_completed", None), field="levels_completed"
        ),
        win_levels=strict_nonnegative_int(
            getattr(frame_data, "win_levels", None), field="win_levels"
        ),
        available_actions=tuple(available),
        full_reset=raw_full_reset,
        returned_action=_normalize_returned_action(frame_data),
        upstream_session_id=raw_guid,
        upstream_metadata=tuple(metadata),
    )


__all__ = ["normalize_frame_data", "normalize_game_state", "strict_nonnegative_int"]
