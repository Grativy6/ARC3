"""First-party compatibility wrapper for the official ARC-AGI-3 Agent API.

The evaluated policy remains generic and offline.  This wrapper deliberately
contains no environment-name branches and uses only a deterministic, local
fallback until the integrated controller is available.
"""

from __future__ import annotations

import os
import random
from enum import StrEnum
from importlib import import_module
from typing import ClassVar

from arc3.config import derive_seed
from arc3.errors import ConfigurationError


class _FallbackGameState(StrEnum):
    NOT_PLAYED = "NOT_PLAYED"
    NOT_FINISHED = "NOT_FINISHED"
    WIN = "WIN"
    GAME_OVER = "GAME_OVER"


class _FallbackGameAction(StrEnum):
    RESET = "RESET"
    ACTION1 = "ACTION1"
    ACTION2 = "ACTION2"
    ACTION3 = "ACTION3"
    ACTION4 = "ACTION4"
    ACTION5 = "ACTION5"
    ACTION6 = "ACTION6"
    ACTION7 = "ACTION7"

    def is_complex(self) -> bool:
        return self is _FallbackGameAction.ACTION6

    def set_data(self, data: dict[str, int]) -> None:
        self.action_data = dict(data)


class _FallbackAgent:
    """Import-only stand-in used when the optional official framework is absent."""

    MAX_ACTIONS: ClassVar[int] = 80

    def __init__(self, *args: object, **kwargs: object) -> None:
        del args
        self.game_id = str(kwargs.get("game_id", "offline"))
        self.agent_name = str(kwargs.get("agent_name", type(self).__name__.lower()))

    @property
    def name(self) -> str:
        return self.agent_name


def _optional_attribute(module_name: str, attribute: str, fallback: object) -> object:
    try:
        module = import_module(module_name)
    except (ImportError, ModuleNotFoundError):
        return fallback
    return getattr(module, attribute, fallback)


_AgentBase = _optional_attribute("agents.agent", "Agent", _FallbackAgent)
GameAction = _optional_attribute("arcengine", "GameAction", _FallbackGameAction)
GameState = _optional_attribute("arcengine", "GameState", _FallbackGameState)


def _enum_name(value: object) -> str:
    name = getattr(value, "name", None)
    if isinstance(name, str):
        return name.upper()
    raw = getattr(value, "value", value)
    return str(raw).upper()


def _enum_member(enum_type: object, name: str) -> object:
    member = getattr(enum_type, name, None)
    if member is None:
        raise RuntimeError(f"official action vocabulary is missing {name}")
    return member


def _parse_root_seed(raw_seed: object) -> int:
    if raw_seed is None:
        raw_seed = os.environ.get("ARC3_SEED", "0")
    try:
        seed = int(str(raw_seed))
    except ValueError as error:
        raise ConfigurationError("ARC3_SEED must be an integer") from error
    if not -(2**63) <= seed < 2**63:
        raise ConfigurationError("ARC3_SEED must be a signed 64-bit integer")
    return seed


class MyAgent(_AgentBase):  # type: ignore[misc,valid-type]
    """Thin deterministic compatibility policy for the pinned framework surface."""

    MAX_ACTIONS = 80

    def __init__(self, *args: object, **kwargs: object) -> None:
        forwarded = dict(kwargs)
        root_seed = _parse_root_seed(forwarded.pop("seed", forwarded.pop("root_seed", None)))
        super().__init__(*args, **forwarded)
        self._rng = random.Random(derive_seed(root_seed, "compatibility-policy"))

    @property
    def name(self) -> str:
        base_name = getattr(super(), "name", type(self).__name__.lower())
        return f"{base_name}.deterministic-v1"

    def is_done(self, frames: list[object], latest_frame: object) -> bool:
        del frames
        return _enum_name(getattr(latest_frame, "state", "UNKNOWN")) == "WIN"

    def choose_action(self, frames: list[object], latest_frame: object) -> object:
        """Choose deterministically from the advertised actions.

        ``RESET`` is mandatory before play and after game over.  No state is
        keyed by environment identity, and no network or hosted inference path
        is reachable here.
        """

        del frames
        state_name = _enum_name(getattr(latest_frame, "state", "NOT_PLAYED"))
        if state_name in {"NOT_PLAYED", "GAME_OVER"}:
            return _enum_member(GameAction, "RESET")

        advertised = getattr(latest_frame, "available_actions", None)
        if advertised:
            raw_candidates = list(advertised)
        else:
            try:
                raw_candidates = list(GameAction)  # type: ignore[call-overload]
            except TypeError:
                raw_candidates = []

        candidates: list[object] = []
        for raw_candidate in raw_candidates:
            candidate = raw_candidate
            if isinstance(raw_candidate, str):
                candidate = getattr(GameAction, raw_candidate.upper(), raw_candidate)
            if _enum_name(candidate) != "RESET":
                candidates.append(candidate)
        candidates.sort(key=_enum_name)

        if not candidates:
            return _enum_member(GameAction, "RESET")
        action = candidates[self._rng.randrange(len(candidates))]
        if _enum_name(action) == "ACTION6":
            setter = getattr(action, "set_data", None)
            if callable(setter):
                setter({"x": self._rng.randrange(64), "y": self._rng.randrange(64)})
        return action


__all__ = ["MyAgent"]
