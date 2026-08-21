"""First-party environment boundary types shared by ARC3 adapters."""

from __future__ import annotations

import hashlib
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Protocol

from arc3.errors import EnvironmentStateError, InvalidActionError
from arc3.types import (
    ActionName,
    ActionRequest,
    EvaluationSurface,
    FrameHash,
    GameId,
    GameStateName,
    JSONScalar,
    JSONValue,
)


@dataclass(frozen=True, slots=True)
class GridFrame:
    """Immutable normalized grid plus its canonical content identity."""

    cells: tuple[tuple[int, ...], ...]
    width: int = field(init=False)
    height: int = field(init=False)
    palette: tuple[int, ...] = field(init=False)
    digest: FrameHash = field(init=False)

    def __post_init__(self) -> None:
        normalized = tuple(tuple(row) for row in self.cells)
        if not normalized or not normalized[0]:
            raise ValueError("a grid frame must contain at least one cell")
        width = len(normalized[0])
        if len(normalized) > 64 or width > 64:
            raise ValueError("grid dimensions must not exceed 64 by 64")
        palette: set[int] = set()
        for row in normalized:
            if len(row) != width:
                raise ValueError("grid rows must have equal width")
            for cell in row:
                if isinstance(cell, bool) or not isinstance(cell, int):
                    raise ValueError("grid cells must be integers")
                if not 0 <= cell <= 15:
                    raise ValueError("grid cells must be within the inclusive range 0..15")
                palette.add(cell)

        hasher = hashlib.sha256()
        hasher.update(b"arc3.frame.v1\0")
        hasher.update(len(normalized).to_bytes(2, "big"))
        hasher.update(width.to_bytes(2, "big"))
        hasher.update(bytes(cell for row in normalized for cell in row))

        object.__setattr__(self, "cells", normalized)
        object.__setattr__(self, "width", width)
        object.__setattr__(self, "height", len(normalized))
        object.__setattr__(self, "palette", tuple(sorted(palette)))
        object.__setattr__(self, "digest", FrameHash(f"sha256:{hasher.hexdigest()}"))

    @classmethod
    def from_rows(cls, rows: Sequence[Sequence[int]]) -> GridFrame:
        """Copy a mutable or third-party grid into the immutable boundary type."""

        return cls(tuple(tuple(cell for cell in row) for row in rows))


@dataclass(frozen=True, slots=True)
class EnvironmentDescriptor:
    """Public, non-executable environment metadata safe for core consumers."""

    game_id: GameId
    title: str | None = None
    tags: tuple[str, ...] = ()
    baseline_actions: tuple[int, ...] = ()
    locally_available: bool = False

    def __post_init__(self) -> None:
        if not str(self.game_id).strip():
            raise ValueError("game_id must not be empty")
        if self.title is not None and not isinstance(self.title, str):
            raise ValueError("title must be a string when present")
        if any(not isinstance(tag, str) for tag in self.tags):
            raise ValueError("tags must be strings")
        if any(
            isinstance(value, bool) or not isinstance(value, int) or value < 0
            for value in self.baseline_actions
        ):
            raise ValueError("baseline actions must be non-negative integers")


@dataclass(frozen=True, slots=True)
class Observation:
    """Immutable observation with no official-SDK objects across the boundary."""

    game_id: GameId
    frames: tuple[GridFrame, ...]
    state: GameStateName
    levels_completed: int
    win_levels: int
    available_actions: tuple[ActionName, ...]
    full_reset: bool = False
    returned_action: ActionRequest | None = None
    upstream_session_id: str | None = None
    upstream_metadata: tuple[tuple[str, JSONScalar], ...] = ()

    def __post_init__(self) -> None:
        if not str(self.game_id).strip():
            raise ValueError("game_id must not be empty")
        for name, value in {
            "levels_completed": self.levels_completed,
            "win_levels": self.win_levels,
        }.items():
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")
        if len(set(self.available_actions)) != len(self.available_actions):
            raise ValueError("available actions must not contain duplicates")
        if self.upstream_session_id is not None and not self.upstream_session_id:
            raise ValueError("upstream_session_id must be non-empty when present")


@dataclass(frozen=True, slots=True)
class ScoreRunSummary:
    """Credential-free score summary for one environment run."""

    game_id: GameId
    score: float
    levels_completed: int
    actions: int
    resets: int
    state: GameStateName
    completed: bool
    level_scores: tuple[float, ...] = ()
    level_actions: tuple[int, ...] = ()
    level_baseline_actions: tuple[int, ...] = ()

    def __post_init__(self) -> None:
        if not math.isfinite(self.score):
            raise ValueError("run score must be finite")
        for name, value in {
            "levels_completed": self.levels_completed,
            "actions": self.actions,
            "resets": self.resets,
        }.items():
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")


@dataclass(frozen=True, slots=True)
class ScoreSummary:
    """Measured scorecard without API keys, cookies, or mutable SDK models."""

    surface: EvaluationSurface
    verified: bool
    scorer: str
    score: float
    runs: tuple[ScoreRunSummary, ...]

    def __post_init__(self) -> None:
        if not self.scorer.strip():
            raise ValueError("scorer identity must not be empty")
        if not math.isfinite(self.score):
            raise ValueError("score must be finite")

    @property
    def total_actions(self) -> int:
        """Return the summed environment actions without counting resets."""

        return sum(run.actions for run in self.runs)

    @property
    def total_resets(self) -> int:
        """Return the summed reset count."""

        return sum(run.resets for run in self.runs)


class EnvironmentSession(Protocol):
    """Minimal normalized session used by policies and controllers."""

    @property
    def observation(self) -> Observation:
        """Return the latest immutable observation."""

    def step(
        self,
        action: ActionRequest,
        *,
        reasoning: Mapping[str, JSONValue] | None = None,
    ) -> Observation:
        """Validate and submit exactly one environment action."""

    def reset(self) -> Observation:
        """Explicitly reset the environment."""

    def scorecard(self) -> ScoreSummary | None:
        """Return the current measured scorecard when available."""

    def close(self) -> ScoreSummary | None:
        """Close the session and return its final scorecard when available."""


class EnvironmentAdapter(Protocol):
    """Discovery and session-construction boundary."""

    def list_games(self) -> tuple[EnvironmentDescriptor, ...]:
        """Return deterministic, copied environment descriptors."""

    def open(self, game_id: str, *, seed: int | None = None) -> EnvironmentSession:
        """Open an environment and expose its constructor-produced observation."""


def validate_action_request(observation: Observation, action: ActionRequest) -> None:
    """Enforce ARC3 action legality before any backend call."""

    if action.coordinate is not None and (
        isinstance(action.coordinate.x, bool)
        or isinstance(action.coordinate.y, bool)
        or not isinstance(action.coordinate.x, int)
        or not isinstance(action.coordinate.y, int)
    ):
        raise InvalidActionError("ACTION6 coordinates must be exact integers")
    if observation.state is GameStateName.WIN:
        raise EnvironmentStateError("the completed environment is terminal; close the session")
    if observation.state is GameStateName.UNKNOWN:
        raise EnvironmentStateError("cannot act while the environment state is unknown")
    if observation.state is GameStateName.GAME_OVER:
        if action.name is not ActionName.RESET:
            raise InvalidActionError("GAME_OVER permits only RESET")
        return
    if observation.state is GameStateName.NOT_PLAYED:
        if action.name is not ActionName.RESET:
            raise InvalidActionError("NOT_PLAYED requires RESET")
        return
    if action.name is ActionName.RESET:
        return
    if action.name not in observation.available_actions:
        advertised = ", ".join(item.value for item in observation.available_actions) or "none"
        raise InvalidActionError(
            f"{action.name.value} is not currently advertised; available actions: {advertised}"
        )


__all__ = [
    "EnvironmentAdapter",
    "EnvironmentDescriptor",
    "EnvironmentSession",
    "GridFrame",
    "Observation",
    "ScoreRunSummary",
    "ScoreSummary",
    "validate_action_request",
]
