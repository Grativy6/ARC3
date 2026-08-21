"""Exact cell and metadata differencing without causal interpretation."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

from arc3.perception.frame import NormalizedGrid
from arc3.types import FrameHash, JSONScalar


class CellChangeKind(StrEnum):
    """Observed cell transition relative to configured background values."""

    ADDITION = "addition"
    REMOVAL = "removal"
    RECOLOR = "recolor"
    EXTENT_CHANGE = "extent_change"


@dataclass(frozen=True, slots=True, order=True)
class CellChange:
    """One exact coordinate-level change; ``None`` denotes out of bounds."""

    x: int
    y: int
    before: int | None
    after: int | None
    kind: CellChangeKind


@dataclass(frozen=True, slots=True)
class MetadataChange:
    """One exact scalar metadata transition."""

    field: str
    before_present: bool
    after_present: bool
    before: JSONScalar
    after: JSONScalar


@dataclass(frozen=True, slots=True)
class FrameDelta:
    """Immutable measurement between two normalized grids."""

    before_hash: FrameHash
    after_hash: FrameHash
    width: int
    height: int
    changed_mask: tuple[tuple[bool, ...], ...]
    cell_changes: tuple[CellChange, ...]
    metadata_changes: tuple[MetadataChange, ...] = ()

    @property
    def changed_cell_count(self) -> int:
        return len(self.cell_changes)

    @property
    def apparent_noop(self) -> bool:
        """Whether neither grid content nor supplied metadata changed."""

        return not self.cell_changes and not self.metadata_changes

    def changes_of_kind(self, kind: CellChangeKind) -> tuple[CellChange, ...]:
        return tuple(change for change in self.cell_changes if change.kind is kind)


def _cell(grid: NormalizedGrid, x: int, y: int) -> int | None:
    if y >= grid.height or x >= grid.width:
        return None
    return grid.cells[y][x]


def _classify_change(
    before: int | None,
    after: int | None,
    backgrounds: frozenset[int],
) -> CellChangeKind:
    if before is None:
        return (
            CellChangeKind.ADDITION
            if after is not None and after not in backgrounds
            else CellChangeKind.EXTENT_CHANGE
        )
    if after is None:
        return CellChangeKind.REMOVAL if before not in backgrounds else CellChangeKind.EXTENT_CHANGE
    before_background = before in backgrounds
    after_background = after in backgrounds
    if before_background and not after_background:
        return CellChangeKind.ADDITION
    if not before_background and after_background:
        return CellChangeKind.REMOVAL
    return CellChangeKind.RECOLOR


def measure_delta(
    before: NormalizedGrid,
    after: NormalizedGrid,
    *,
    before_metadata: Mapping[str, JSONScalar] | None = None,
    after_metadata: Mapping[str, JSONScalar] | None = None,
    background_colors: frozenset[int] = frozenset({0}),
) -> FrameDelta:
    """Measure an exact delta, including extent and scalar metadata changes."""

    if any(isinstance(color, bool) or not 0 <= color <= 15 for color in background_colors):
        raise ValueError("background colors must be integers in 0..15")
    width = max(before.width, after.width)
    height = max(before.height, after.height)
    mask_rows: list[tuple[bool, ...]] = []
    changes: list[CellChange] = []
    for y in range(height):
        mask_row: list[bool] = []
        for x in range(width):
            old = _cell(before, x, y)
            new = _cell(after, x, y)
            changed = old != new
            mask_row.append(changed)
            if changed:
                changes.append(
                    CellChange(x, y, old, new, _classify_change(old, new, background_colors))
                )
        mask_rows.append(tuple(mask_row))

    old_metadata = before_metadata or {}
    new_metadata = after_metadata or {}
    metadata_changes = tuple(
        MetadataChange(
            key,
            key in old_metadata,
            key in new_metadata,
            old_metadata.get(key),
            new_metadata.get(key),
        )
        for key in sorted(set(old_metadata) | set(new_metadata))
        if (key in old_metadata) != (key in new_metadata)
        or old_metadata.get(key) != new_metadata.get(key)
    )
    return FrameDelta(
        before_hash=before.digest,
        after_hash=after.digest,
        width=width,
        height=height,
        changed_mask=tuple(mask_rows),
        cell_changes=tuple(changes),
        metadata_changes=metadata_changes,
    )
