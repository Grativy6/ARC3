"""Deterministic, game-agnostic Stage 02 baseline policies."""

from __future__ import annotations

import random

from arc3.adapters import Observation
from arc3.errors import PolicyError
from arc3.types import ActionName, ActionRequest, Coordinate, GameStateName

_ACTION_ORDER = (
    ActionName.ACTION1,
    ActionName.ACTION2,
    ActionName.ACTION3,
    ActionName.ACTION4,
    ActionName.ACTION5,
    ActionName.ACTION6,
    ActionName.ACTION7,
)
_SWEEP_AXIS = (0, 16, 32, 48, 63)
_SWEEP_COORDINATES = tuple(Coordinate(x, y) for y in _SWEEP_AXIS for x in _SWEEP_AXIS)


def _terminal_action(observation: Observation) -> ActionRequest | None:
    if observation.state in {GameStateName.GAME_OVER, GameStateName.NOT_PLAYED}:
        return ActionRequest(ActionName.RESET)
    if observation.state is GameStateName.WIN:
        raise PolicyError("the environment is complete; no baseline action is permitted")
    if observation.state is GameStateName.UNKNOWN:
        raise PolicyError("cannot select a baseline action for an unknown environment state")
    return None


def _ordered_available(observation: Observation) -> tuple[ActionName, ...]:
    advertised = set(observation.available_actions)
    return tuple(action for action in _ACTION_ORDER if action in advertised)


def _require_available(observation: Observation) -> tuple[ActionName, ...]:
    terminal = _terminal_action(observation)
    if terminal is not None:
        return (terminal.name,)
    available = _ordered_available(observation)
    if not available:
        raise PolicyError("the environment advertises no baseline-compatible action")
    return available


class RandomValidPolicy:
    """Seeded random selection restricted to currently advertised actions."""

    def __init__(self, seed: int) -> None:
        if isinstance(seed, bool) or not -(2**63) <= seed < 2**63:
            raise PolicyError("seed must be a signed 64-bit integer")
        self._seed = seed
        self._random = random.Random(seed)

    def reset(self) -> None:
        """Restore the exact initial random stream."""

        self._random.seed(self._seed)

    def select(self, observation: Observation) -> ActionRequest:
        terminal = _terminal_action(observation)
        if terminal is not None:
            return terminal
        available = _require_available(observation)
        name = available[self._random.randrange(len(available))]
        if name is ActionName.ACTION6:
            return ActionRequest(
                name,
                Coordinate(self._random.randrange(64), self._random.randrange(64)),
            )
        return ActionRequest(name)


class ActionCyclePolicy:
    """Cycle through the fixed action vocabulary, skipping unavailable actions."""

    def __init__(self) -> None:
        self._ordinal = 0

    def reset(self) -> None:
        self._ordinal = 0

    def select(self, observation: Observation) -> ActionRequest:
        terminal = _terminal_action(observation)
        if terminal is not None:
            return terminal
        available = _require_available(observation)
        name = available[self._ordinal % len(available)]
        self._ordinal += 1
        if name is ActionName.ACTION6:
            return ActionRequest(name, Coordinate(32, 32))
        return ActionRequest(name)


class CoordinateSweepPolicy:
    """Visit a deterministic coarse screen grid when ACTION6 is advertised."""

    def __init__(self) -> None:
        self._ordinal = 0

    def reset(self) -> None:
        self._ordinal = 0

    def select(self, observation: Observation) -> ActionRequest:
        terminal = _terminal_action(observation)
        if terminal is not None:
            return terminal
        if ActionName.ACTION6 not in observation.available_actions:
            raise PolicyError("coordinate sweep requires advertised ACTION6")
        coordinate = _SWEEP_COORDINATES[self._ordinal % len(_SWEEP_COORDINATES)]
        self._ordinal += 1
        return ActionRequest(ActionName.ACTION6, coordinate)


def make_baseline(
    name: str, *, seed: int = 0
) -> RandomValidPolicy | ActionCyclePolicy | CoordinateSweepPolicy:
    """Construct a baseline by its stable CLI name."""

    normalized = name.strip().lower()
    if normalized == "random":
        return RandomValidPolicy(seed)
    if normalized == "cycle":
        return ActionCyclePolicy()
    if normalized in {"sweep", "coordinate-sweep"}:
        return CoordinateSweepPolicy()
    raise PolicyError(f"unknown baseline {name!r}; expected random, cycle, or sweep")


__all__ = [
    "ActionCyclePolicy",
    "CoordinateSweepPolicy",
    "RandomValidPolicy",
    "make_baseline",
]
