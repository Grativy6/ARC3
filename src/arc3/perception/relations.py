"""Measured spatial relations and repeated geometric structures."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from enum import StrEnum

from arc3.perception.components import Component, ShapeInvariance


class RelationKind(StrEnum):
    """Geometry-only relations between observed components."""

    CONTAINS_BOUNDS = "contains_bounds"
    INSIDE_BOUNDS = "inside_bounds"
    ADJACENT = "adjacent"
    OVERLAPS = "overlaps"


@dataclass(frozen=True, slots=True, order=True)
class ComponentRelation:
    source_id: str
    target_id: str
    kind: RelationKind
    separation: int


@dataclass(frozen=True, slots=True)
class RepetitionGroup:
    signature: str
    component_ids: tuple[str, ...]
    colors: tuple[int, ...]


def _minimum_manhattan(left: Component, right: Component) -> int:
    return min(abs(a.x - b.x) + abs(a.y - b.y) for a in left.cells for b in right.cells)


def component_relations(components: tuple[Component, ...]) -> tuple[ComponentRelation, ...]:
    """Measure pairwise bounding containment, cell overlap, and adjacency."""

    relations: list[ComponentRelation] = []
    for index, left in enumerate(components):
        left_cells = frozenset(left.cells)
        for right in components[index + 1 :]:
            right_cells = frozenset(right.cells)
            separation = _minimum_manhattan(left, right)
            if left_cells & right_cells:
                relations.extend(
                    (
                        ComponentRelation(
                            left.component_id, right.component_id, RelationKind.OVERLAPS, 0
                        ),
                        ComponentRelation(
                            right.component_id, left.component_id, RelationKind.OVERLAPS, 0
                        ),
                    )
                )
            if left.bounds.contains(right.bounds) and left.bounds != right.bounds:
                relations.extend(
                    (
                        ComponentRelation(
                            left.component_id,
                            right.component_id,
                            RelationKind.CONTAINS_BOUNDS,
                            separation,
                        ),
                        ComponentRelation(
                            right.component_id,
                            left.component_id,
                            RelationKind.INSIDE_BOUNDS,
                            separation,
                        ),
                    )
                )
            elif right.bounds.contains(left.bounds) and left.bounds != right.bounds:
                relations.extend(
                    (
                        ComponentRelation(
                            right.component_id,
                            left.component_id,
                            RelationKind.CONTAINS_BOUNDS,
                            separation,
                        ),
                        ComponentRelation(
                            left.component_id,
                            right.component_id,
                            RelationKind.INSIDE_BOUNDS,
                            separation,
                        ),
                    )
                )
            if separation == 1:
                relations.extend(
                    (
                        ComponentRelation(
                            left.component_id, right.component_id, RelationKind.ADJACENT, 1
                        ),
                        ComponentRelation(
                            right.component_id, left.component_id, RelationKind.ADJACENT, 1
                        ),
                    )
                )
    return tuple(sorted(relations))


def find_repetitions(
    components: tuple[Component, ...],
    *,
    invariance: ShapeInvariance = ShapeInvariance.TRANSLATION,
    ignore_color: bool = True,
) -> tuple[RepetitionGroup, ...]:
    """Group repeated shapes while optionally preserving palette distinction."""

    grouped: defaultdict[tuple[str, int | None], list[Component]] = defaultdict(list)
    for component in components:
        grouped[
            (component.signature(invariance), None if ignore_color else component.color)
        ].append(component)
    result = [
        RepetitionGroup(
            signature=key[0],
            component_ids=tuple(component.component_id for component in values),
            colors=tuple(component.color for component in values),
        )
        for key, values in grouped.items()
        if len(values) > 1
    ]
    return tuple(sorted(result, key=lambda group: (group.signature, group.component_ids)))
