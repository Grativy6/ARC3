"""Immutable frame normalization at the perception boundary."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from arc3.adapters import GridFrame
from arc3.types import ActionName, FrameHash, GameStateName, JSONScalar

# The adapter boundary already owns the canonical grid encoding. Reusing it here
# keeps a single hash identity from receipt through derived perception.
NormalizedGrid = GridFrame


def normalize_grid(rows: Sequence[Sequence[int]]) -> NormalizedGrid:
    """Copy rows into the canonical immutable grid and compute its stable hash."""

    return GridFrame.from_rows(rows)


@dataclass(frozen=True, slots=True)
class NormalizedFrame:
    """A grid and source metadata with no inferred meaning."""

    grid: NormalizedGrid
    source_index: int
    game_state: GameStateName = GameStateName.UNKNOWN
    score: float | None = None
    available_actions: tuple[ActionName, ...] = ()
    timestamp_ns: int | None = None
    parent_frame_hash: FrameHash | None = None
    metadata: tuple[tuple[str, JSONScalar], ...] = ()

    def __post_init__(self) -> None:
        if isinstance(self.source_index, bool) or self.source_index < 0:
            raise ValueError("source_index must be a non-negative integer")
        if self.timestamp_ns is not None and (
            isinstance(self.timestamp_ns, bool) or self.timestamp_ns < 0
        ):
            raise ValueError("timestamp_ns must be a non-negative integer when present")
        if self.score is not None and not math.isfinite(self.score):
            raise ValueError("score must be finite when present")
        if len(set(self.available_actions)) != len(self.available_actions):
            raise ValueError("available_actions must not contain duplicates")
        if self.parent_frame_hash is not None and not str(self.parent_frame_hash).startswith(
            "sha256:"
        ):
            raise ValueError("parent_frame_hash must use the sha256 namespace")
        keys = tuple(key for key, _value in self.metadata)
        if any(not key for key in keys) or len(set(keys)) != len(keys):
            raise ValueError("metadata keys must be unique and non-empty")
        object.__setattr__(self, "metadata", tuple(sorted(self.metadata)))

    @property
    def content_hash(self) -> FrameHash:
        """Return the canonical grid content hash."""

        return self.grid.digest

    @classmethod
    def from_rows(
        cls,
        rows: Sequence[Sequence[int]],
        *,
        source_index: int,
        game_state: GameStateName = GameStateName.UNKNOWN,
        score: float | None = None,
        available_actions: Sequence[ActionName] = (),
        timestamp_ns: int | None = None,
        parent_frame_hash: FrameHash | None = None,
        metadata: Mapping[str, JSONScalar] | None = None,
    ) -> NormalizedFrame:
        """Normalize mutable input without retaining references to it."""

        return cls(
            grid=normalize_grid(rows),
            source_index=source_index,
            game_state=game_state,
            score=score,
            available_actions=tuple(available_actions),
            timestamp_ns=timestamp_ns,
            parent_frame_hash=parent_frame_hash,
            metadata=tuple((metadata or {}).items()),
        )
