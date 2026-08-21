"""Color-connected geometric component measurements."""

from __future__ import annotations

import hashlib
from collections import Counter, deque
from collections.abc import Collection, Iterable
from dataclasses import dataclass
from enum import StrEnum

from arc3.perception.frame import NormalizedGrid


@dataclass(frozen=True, slots=True, order=True)
class GridPoint:
    """Zero-based grid point using x/y coordinates."""

    x: int
    y: int


@dataclass(frozen=True, slots=True, order=True)
class BoundingBox:
    """Inclusive component bounds."""

    left: int
    top: int
    right: int
    bottom: int

    @property
    def width(self) -> int:
        return self.right - self.left + 1

    @property
    def height(self) -> int:
        return self.bottom - self.top + 1

    def contains(self, other: BoundingBox) -> bool:
        return (
            self.left <= other.left
            and self.top <= other.top
            and self.right >= other.right
            and self.bottom >= other.bottom
        )


class ShapeInvariance(StrEnum):
    """Canonicalization allowed when comparing geometric shapes."""

    TRANSLATION = "translation"
    ROTATION = "rotation"
    REFLECTION = "reflection"


@dataclass(frozen=True, slots=True)
class ComponentConfig:
    """Explicit extraction choices; ``None`` asks for measured background candidates."""

    background_candidates: tuple[int, ...] | None = None
    connectivity: int = 4
    inferred_background_count: int = 1

    def __post_init__(self) -> None:
        if self.connectivity not in {4, 8}:
            raise ValueError("connectivity must be 4 or 8")
        if self.inferred_background_count < 1:
            raise ValueError("inferred_background_count must be positive")
        if self.background_candidates is not None:
            if not self.background_candidates:
                raise ValueError("explicit background_candidates must not be empty")
            if len(set(self.background_candidates)) != len(self.background_candidates):
                raise ValueError("background_candidates must not contain duplicates")
            if any(
                isinstance(color, bool) or not 0 <= color <= 15
                for color in self.background_candidates
            ):
                raise ValueError("background candidates must be integers in 0..15")


@dataclass(frozen=True, slots=True)
class Component:
    """An observation-local connected region with geometry-only signatures."""

    component_id: str
    color: int
    cells: tuple[GridPoint, ...]
    bounds: BoundingBox
    centroid: tuple[float, float]
    translation_signature: str
    rotation_signature: str
    reflection_signature: str

    @property
    def area(self) -> int:
        return len(self.cells)

    def signature(self, invariance: ShapeInvariance = ShapeInvariance.TRANSLATION) -> str:
        if invariance is ShapeInvariance.TRANSLATION:
            return self.translation_signature
        if invariance is ShapeInvariance.ROTATION:
            return self.rotation_signature
        return self.reflection_signature


def infer_background_candidates(
    grid: NormalizedGrid,
    *,
    max_candidates: int = 3,
) -> tuple[int, ...]:
    """Rank colors by boundary coverage then global frequency, without semantics."""

    if max_candidates < 1:
        raise ValueError("max_candidates must be positive")
    total = Counter(cell for row in grid.cells for cell in row)
    boundary: Counter[int] = Counter()
    for x in range(grid.width):
        boundary[grid.cells[0][x]] += 1
        if grid.height > 1:
            boundary[grid.cells[-1][x]] += 1
    for y in range(1, grid.height - 1):
        boundary[grid.cells[y][0]] += 1
        if grid.width > 1:
            boundary[grid.cells[y][-1]] += 1
    ranked = sorted(total, key=lambda color: (-boundary[color], -total[color], color))
    return tuple(ranked[:max_candidates])


def _normalize_points(points: Iterable[tuple[int, int]]) -> tuple[tuple[int, int], ...]:
    materialized = tuple(points)
    if not materialized:
        raise ValueError("a component shape must contain at least one point")
    min_x = min(point[0] for point in materialized)
    min_y = min(point[1] for point in materialized)
    return tuple(sorted((x - min_x, y - min_y) for x, y in materialized))


def _rotate(points: Iterable[tuple[int, int]]) -> tuple[tuple[int, int], ...]:
    return _normalize_points((-y, x) for x, y in points)


def _reflect(points: Iterable[tuple[int, int]]) -> tuple[tuple[int, int], ...]:
    return _normalize_points((-x, y) for x, y in points)


def _encode_shape(points: tuple[tuple[int, int], ...]) -> str:
    width = max(x for x, _y in points) + 1
    height = max(y for _x, y in points) + 1
    body = ";".join(f"{x},{y}" for x, y in points)
    return f"{width}x{height}:{body}"


def component_signature(
    cells: Collection[GridPoint] | Collection[tuple[int, int]],
    *,
    invariance: ShapeInvariance = ShapeInvariance.TRANSLATION,
) -> str:
    """Return a color-independent canonical shape signature."""

    points = _normalize_points(
        (cell.x, cell.y) if isinstance(cell, GridPoint) else cell for cell in cells
    )
    variants = [points]
    rotated = points
    if invariance in {ShapeInvariance.ROTATION, ShapeInvariance.REFLECTION}:
        for _index in range(3):
            rotated = _rotate(rotated)
            variants.append(rotated)
    if invariance is ShapeInvariance.REFLECTION:
        reflected = _reflect(points)
        variants.append(reflected)
        for _index in range(3):
            reflected = _rotate(reflected)
            variants.append(reflected)
    return min(_encode_shape(variant) for variant in variants)


def _neighbors(
    point: GridPoint, *, width: int, height: int, connectivity: int
) -> Iterable[GridPoint]:
    offsets: tuple[tuple[int, int], ...] = ((-1, 0), (1, 0), (0, -1), (0, 1))
    if connectivity == 8:
        offsets += ((-1, -1), (-1, 1), (1, -1), (1, 1))
    for dx, dy in offsets:
        x = point.x + dx
        y = point.y + dy
        if 0 <= x < width and 0 <= y < height:
            yield GridPoint(x, y)


def _make_component(
    grid: NormalizedGrid,
    *,
    color: int,
    cells: Collection[GridPoint],
) -> Component:
    ordered = tuple(sorted(cells, key=lambda point: (point.y, point.x)))
    bounds = BoundingBox(
        left=min(point.x for point in ordered),
        top=min(point.y for point in ordered),
        right=max(point.x for point in ordered),
        bottom=max(point.y for point in ordered),
    )
    translation = component_signature(ordered)
    identity_material = (
        f"arc3.component.v1\0{grid.digest}\0{color}\0"
        + ";".join(f"{point.x},{point.y}" for point in ordered)
    ).encode()
    component_id = f"cmp:{hashlib.sha256(identity_material).hexdigest()}"
    return Component(
        component_id=component_id,
        color=color,
        cells=ordered,
        bounds=bounds,
        centroid=(
            sum(point.x for point in ordered) / len(ordered),
            sum(point.y for point in ordered) / len(ordered),
        ),
        translation_signature=translation,
        rotation_signature=component_signature(ordered, invariance=ShapeInvariance.ROTATION),
        reflection_signature=component_signature(ordered, invariance=ShapeInvariance.REFLECTION),
    )


def extract_components(
    grid: NormalizedGrid,
    *,
    config: ComponentConfig | None = None,
) -> tuple[Component, ...]:
    """Extract deterministic same-color connected components."""

    chosen = config or ComponentConfig()
    backgrounds = frozenset(
        chosen.background_candidates
        if chosen.background_candidates is not None
        else infer_background_candidates(grid, max_candidates=chosen.inferred_background_count)
    )
    visited: set[GridPoint] = set()
    components: list[Component] = []
    for y, row in enumerate(grid.cells):
        for x, color in enumerate(row):
            start = GridPoint(x, y)
            if color in backgrounds or start in visited:
                continue
            queue = deque([start])
            visited.add(start)
            cells: list[GridPoint] = []
            while queue:
                point = queue.popleft()
                cells.append(point)
                for neighbor in _neighbors(
                    point,
                    width=grid.width,
                    height=grid.height,
                    connectivity=chosen.connectivity,
                ):
                    if neighbor not in visited and grid.cells[neighbor.y][neighbor.x] == color:
                        visited.add(neighbor)
                        queue.append(neighbor)
            components.append(_make_component(grid, color=color, cells=cells))
    return tuple(
        sorted(
            components,
            key=lambda component: (
                component.bounds.top,
                component.bounds.left,
                component.color,
                component.component_id,
            ),
        )
    )
