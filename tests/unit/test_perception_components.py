from __future__ import annotations

from arc3.perception.components import (
    ComponentConfig,
    GridPoint,
    ShapeInvariance,
    component_signature,
    extract_components,
    infer_background_candidates,
)
from arc3.perception.frame import normalize_grid
from arc3.perception.relations import RelationKind, component_relations, find_repetitions


def test_per_color_components_and_configurable_background() -> None:
    grid = normalize_grid([[0, 1, 0], [1, 1, 2], [0, 2, 2]])
    components = extract_components(
        grid,
        config=ComponentConfig(background_candidates=(0,), connectivity=4),
    )

    assert [(component.color, component.area) for component in components] == [(1, 3), (2, 3)]
    assert components[0].bounds.width == 2
    assert components[0].bounds.height == 2
    assert infer_background_candidates(grid, max_candidates=1) == (0,)


def test_connectivity_is_explicit() -> None:
    grid = normalize_grid([[1, 0], [0, 1]])
    four = extract_components(
        grid, config=ComponentConfig(background_candidates=(0,), connectivity=4)
    )
    eight = extract_components(
        grid, config=ComponentConfig(background_candidates=(0,), connectivity=8)
    )
    assert len(four) == 2
    assert len(eight) == 1


def test_shape_signatures_have_declared_invariances() -> None:
    shape = (GridPoint(2, 3), GridPoint(2, 4), GridPoint(3, 4))
    translated = (GridPoint(7, 9), GridPoint(7, 10), GridPoint(8, 10))
    rotated = (GridPoint(0, 0), GridPoint(1, 0), GridPoint(0, 1))

    assert component_signature(shape) == component_signature(translated)
    assert component_signature(shape) != component_signature(rotated)
    assert component_signature(shape, invariance=ShapeInvariance.ROTATION) == component_signature(
        rotated, invariance=ShapeInvariance.ROTATION
    )


def test_relations_and_repetition_are_geometric() -> None:
    contained_grid = normalize_grid(
        [[1, 1, 1, 1, 1], [1, 0, 0, 0, 1], [1, 0, 2, 0, 1], [1, 0, 0, 0, 1], [1, 1, 1, 1, 1]]
    )
    contained = extract_components(
        contained_grid, config=ComponentConfig(background_candidates=(0,))
    )
    relations = component_relations(contained)
    assert {relation.kind for relation in relations} == {
        RelationKind.CONTAINS_BOUNDS,
        RelationKind.INSIDE_BOUNDS,
    }

    repeated_grid = normalize_grid([[1, 0, 2, 0, 1]])
    repeated = extract_components(repeated_grid, config=ComponentConfig(background_candidates=(0,)))
    groups = find_repetitions(repeated)
    assert len(groups) == 1
    assert len(groups[0].component_ids) == 3
    assert groups[0].colors == (1, 2, 1)
