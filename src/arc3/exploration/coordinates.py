"""Bounded, deterministic ACTION6 coordinate candidate generation."""

from __future__ import annotations

import math
from collections.abc import Collection, Sequence

from arc3.perception.components import Component, GridPoint
from arc3.perception.delta import CellChange
from arc3.perception.frame import NormalizedGrid
from arc3.types import Coordinate

from .models import CoordinateCandidate, CoordinateSource


def _bounded_points(
    points: Collection[GridPoint] | Collection[Coordinate], *, width: int, height: int
) -> tuple[Coordinate, ...]:
    return tuple(
        Coordinate(point.x, point.y)
        for point in points
        if 0 <= point.x < width and 0 <= point.y < height
    )


def _boundary_points(width: int, height: int) -> tuple[Coordinate, ...]:
    xs = (0, (width - 1) // 2, width - 1)
    ys = (0, (height - 1) // 2, height - 1)
    return tuple(
        Coordinate(x, y)
        for x, y in (
            (xs[0], ys[0]),
            (xs[2], ys[0]),
            (xs[0], ys[2]),
            (xs[2], ys[2]),
            (xs[1], ys[0]),
            (xs[1], ys[2]),
            (xs[0], ys[1]),
            (xs[2], ys[1]),
        )
    )


def _coarse_unexplored(
    width: int,
    height: int,
    explored: frozenset[Coordinate],
    *,
    target_count: int,
) -> tuple[Coordinate, ...]:
    spacing = max(1, math.ceil(math.sqrt((width * height) / max(1, target_count))))
    offsets = (spacing // 2, 0)
    points: list[Coordinate] = []
    for offset in offsets:
        for y in range(min(height - 1, offset), height, spacing):
            for x in range(min(width - 1, offset), width, spacing):
                point = Coordinate(x, y)
                if point not in explored and point not in points:
                    points.append(point)
    return tuple(points)


def generate_coordinate_candidates(
    grid: NormalizedGrid,
    *,
    components: Sequence[Component] = (),
    changed_cells: Sequence[CellChange] = (),
    empty_slots: Collection[GridPoint] | Collection[Coordinate] = (),
    disagreement_cells: Collection[GridPoint] | Collection[Coordinate] = (),
    explored: Collection[Coordinate] = (),
    max_candidates: int = 24,
) -> tuple[CoordinateCandidate, ...]:
    """Round-robin candidate sources so one large source cannot crowd out the rest."""

    if isinstance(max_candidates, bool) or max_candidates <= 0:
        raise ValueError("max_candidates must be a positive integer")
    width, height = grid.width, grid.height
    explored_set = frozenset(explored)
    source_points: tuple[tuple[CoordinateSource, tuple[Coordinate, ...]], ...] = (
        (
            CoordinateSource.COMPONENT_CENTER,
            tuple(
                Coordinate(
                    min(width - 1, max(0, round(component.centroid[0]))),
                    min(height - 1, max(0, round(component.centroid[1]))),
                )
                for component in components
            ),
        ),
        (
            CoordinateSource.CHANGED_CELL,
            tuple(
                Coordinate(change.x, change.y)
                for change in changed_cells
                if 0 <= change.x < width and 0 <= change.y < height
            ),
        ),
        (
            CoordinateSource.EMPTY_SLOT,
            _bounded_points(empty_slots, width=width, height=height),
        ),
        (CoordinateSource.BOUNDARY, _boundary_points(width, height)),
        (
            CoordinateSource.DISAGREEMENT,
            _bounded_points(disagreement_cells, width=width, height=height),
        ),
        (
            CoordinateSource.COARSE_UNEXPLORED,
            _coarse_unexplored(
                width,
                height,
                explored_set,
                target_count=max_candidates,
            ),
        ),
    )
    merged: dict[Coordinate, list[CoordinateSource]] = {}
    cursors = [0] * len(source_points)
    while len(merged) < max_candidates:
        made_progress = False
        for source_index, (source, points) in enumerate(source_points):
            cursor = cursors[source_index]
            while cursor < len(points) and points[cursor] in explored_set:
                cursor += 1
            cursors[source_index] = cursor
            if cursor >= len(points):
                continue
            point = points[cursor]
            cursors[source_index] += 1
            made_progress = True
            merged.setdefault(point, []).append(source)
            if len(merged) >= max_candidates:
                break
        if not made_progress:
            break

    # Merge support from sources whose duplicate point was beyond the round-robin cutoff.
    for source, points in source_points:
        for point in points:
            if point in merged and source not in merged[point]:
                merged[point].append(source)
    return tuple(
        CoordinateCandidate(coordinate=point, sources=tuple(sources))
        for point, sources in merged.items()
    )


__all__ = ["generate_coordinate_candidates"]
