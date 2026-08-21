"""Generic structural goal proposals derived from geometry, never game identity."""

from __future__ import annotations

from collections import Counter, deque
from dataclasses import dataclass

from arc3.adapters import GridFrame
from arc3.perception import ComponentConfig, GridPoint, component_signature, extract_components

from .models import GoalKind


@dataclass(frozen=True, slots=True, order=True)
class StructuralGoalFeature:
    """One measured structural affordance or discrepancy."""

    kind: GoalKind
    target_state: str
    discrepancy: int | None
    satisfied: bool
    measurement: str


@dataclass(frozen=True, slots=True)
class StructuralChange:
    """Comparison of one structural feature across a preserved transition."""

    before: StructuralGoalFeature
    after: StructuralGoalFeature
    improved: bool
    contradicted: bool


def _background(grid: GridFrame) -> int:
    counts = Counter(cell for row in grid.cells for cell in row)
    return min(counts, key=lambda color: (-counts[color], color))


def _enclosed_regions(grid: GridFrame, background: int) -> tuple[tuple[GridPoint, ...], ...]:
    unseen = {
        GridPoint(x, y)
        for y, row in enumerate(grid.cells)
        for x, cell in enumerate(row)
        if cell == background
    }
    enclosed: list[tuple[GridPoint, ...]] = []
    while unseen:
        start = min(unseen, key=lambda point: (point.y, point.x))
        queue = deque((start,))
        unseen.remove(start)
        region: list[GridPoint] = []
        touches_boundary = False
        while queue:
            point = queue.popleft()
            region.append(point)
            touches_boundary |= point.x in {0, grid.width - 1} or point.y in {0, grid.height - 1}
            for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                neighbor = GridPoint(point.x + dx, point.y + dy)
                if neighbor in unseen:
                    unseen.remove(neighbor)
                    queue.append(neighbor)
        if not touches_boundary:
            enclosed.append(tuple(sorted(region, key=lambda point: (point.y, point.x))))
    return tuple(enclosed)


def _repeated_pattern_discrepancy(grid: GridFrame) -> int | None:
    row_counts = Counter(grid.cells)
    dominant_row, count = min(row_counts.items(), key=lambda item: (-item[1], item[0]))
    row_discrepancy = sum(
        sum(left != right for left, right in zip(row, dominant_row, strict=True))
        for row in grid.cells
    )
    columns = tuple(tuple(grid.cells[y][x] for y in range(grid.height)) for x in range(grid.width))
    column_counts = Counter(columns)
    dominant_column, column_count = min(column_counts.items(), key=lambda item: (-item[1], item[0]))
    column_discrepancy = sum(
        sum(left != right for left, right in zip(column, dominant_column, strict=True))
        for column in columns
    )
    candidates: list[int] = []
    if count >= 2:
        candidates.append(row_discrepancy)
    if column_count >= 2:
        candidates.append(column_discrepancy)
    return min(candidates) if candidates else None


def _component_gap(left_cells: tuple[GridPoint, ...], right_cells: tuple[GridPoint, ...]) -> int:
    return min(
        abs(left.x - right.x) + abs(left.y - right.y) - 1
        for left in left_cells
        for right in right_cells
    )


def measure_structural_goals(grid: GridFrame) -> tuple[StructuralGoalFeature, ...]:
    """Propose exits, slots, patterns, contact, and discrepancy candidates."""

    background = _background(grid)
    components = extract_components(
        grid,
        config=ComponentConfig(background_candidates=(background,)),
    )
    features: list[StructuralGoalFeature] = []

    for component in components:
        if (
            component.bounds.left == 0
            or component.bounds.top == 0
            or component.bounds.right == grid.width - 1
            or component.bounds.bottom == grid.height - 1
        ):
            features.append(
                StructuralGoalFeature(
                    kind=GoalKind.EXIT,
                    target_state=f"contact-boundary-feature:{component.translation_signature}",
                    discrepancy=None,
                    satisfied=False,
                    measurement="boundary component measured",
                )
            )

    enclosed = _enclosed_regions(grid, background)
    if enclosed:
        signatures = tuple(sorted(component_signature(region) for region in enclosed))
        features.append(
            StructuralGoalFeature(
                kind=GoalKind.MATCHING_SLOT,
                target_state="fill-enclosed-slots:" + ",".join(signatures),
                discrepancy=len(enclosed),
                satisfied=False,
                measurement=f"{len(enclosed)} enclosed background region(s)",
            )
        )

    pattern_discrepancy = _repeated_pattern_discrepancy(grid)
    if pattern_discrepancy is not None:
        features.append(
            StructuralGoalFeature(
                kind=GoalKind.COMPLETION_PATTERN,
                target_state="complete-repeated-row-or-column-pattern",
                discrepancy=pattern_discrepancy,
                satisfied=pattern_discrepancy == 0,
                measurement=f"repeated-pattern discrepancy={pattern_discrepancy}",
            )
        )

    for index, left in enumerate(components):
        for right in components[index + 1 :]:
            gap = _component_gap(left.cells, right.cells)
            if 0 <= gap <= 4:
                pair_signatures = sorted((left.translation_signature, right.translation_signature))
                features.append(
                    StructuralGoalFeature(
                        kind=GoalKind.CONTACT,
                        target_state=(f"contact-shapes:{pair_signatures[0]}:{pair_signatures[1]}"),
                        discrepancy=gap,
                        satisfied=gap == 0,
                        measurement=f"component gap={gap}",
                    )
                )

    cell_counts = Counter(cell for row in grid.cells for cell in row)
    modal_count = max(cell_counts.values())
    discrepancy = grid.width * grid.height - modal_count
    features.append(
        StructuralGoalFeature(
            kind=GoalKind.DISCREPANCY_REDUCTION,
            target_state="reduce-modal-cell-discrepancy",
            discrepancy=discrepancy,
            satisfied=discrepancy == 0,
            measurement=f"modal-cell discrepancy={discrepancy}",
        )
    )
    return tuple(sorted(set(features)))


def compare_structural_goals(
    before: tuple[StructuralGoalFeature, ...],
    after: tuple[StructuralGoalFeature, ...],
) -> tuple[StructuralChange, ...]:
    """Compare compatible features; absence never silently counts as completion."""

    old = {(feature.kind, feature.target_state): feature for feature in before}
    changes: list[StructuralChange] = []
    for current in after:
        prior = old.get((current.kind, current.target_state))
        if prior is None:
            continue
        improved = (
            prior.discrepancy is not None
            and current.discrepancy is not None
            and current.discrepancy < prior.discrepancy
        )
        contradicted = (
            prior.discrepancy is not None
            and current.discrepancy is not None
            and current.discrepancy > prior.discrepancy
        )
        changes.append(StructuralChange(prior, current, improved, contradicted))
    return tuple(changes)


__all__ = [
    "StructuralChange",
    "StructuralGoalFeature",
    "compare_structural_goals",
    "measure_structural_goals",
]
