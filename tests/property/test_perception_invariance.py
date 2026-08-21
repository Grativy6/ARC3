from __future__ import annotations

from hypothesis import given
from hypothesis import strategies as st

from arc3.perception.components import (
    ComponentConfig,
    GridPoint,
    ShapeInvariance,
    component_signature,
    extract_components,
)
from arc3.perception.frame import normalize_grid


@given(
    st.lists(
        st.tuples(st.integers(0, 5), st.integers(0, 5)),
        min_size=1,
        max_size=12,
        unique=True,
    ),
    st.integers(-20, 20),
    st.integers(-20, 20),
)
def test_translation_signature_is_position_invariant(
    cells: list[tuple[int, int]], dx: int, dy: int
) -> None:
    original = tuple(GridPoint(x, y) for x, y in cells)
    translated = tuple(GridPoint(x + dx, y + dy) for x, y in cells)
    assert component_signature(original) == component_signature(translated)


@given(
    st.lists(
        st.tuples(st.integers(0, 5), st.integers(0, 5)),
        min_size=1,
        max_size=12,
        unique=True,
    )
)
def test_rotation_signature_is_quarter_turn_invariant(cells: list[tuple[int, int]]) -> None:
    original = tuple(GridPoint(x, y) for x, y in cells)
    rotated = tuple(GridPoint(-y, x) for x, y in cells)
    assert component_signature(
        original, invariance=ShapeInvariance.ROTATION
    ) == component_signature(rotated, invariance=ShapeInvariance.ROTATION)


@given(
    st.integers(1, 15),
    st.integers(1, 15),
    st.integers(0, 3),
    st.integers(0, 3),
)
def test_palette_and_position_permutations_preserve_structure(
    first_color: int, second_color: int, dx: int, dy: int
) -> None:
    shifted_color = second_color if second_color != first_color else (second_color % 15) + 1
    first_rows = [[0] * 8 for _index in range(8)]
    second_rows = [[0] * 12 for _index in range(12)]
    for x, y in ((1, 1), (2, 1), (1, 2)):
        first_rows[y][x] = first_color
        second_rows[y + dy + 2][x + dx + 2] = shifted_color
    first = extract_components(
        normalize_grid(first_rows), config=ComponentConfig(background_candidates=(0,))
    )
    second = extract_components(
        normalize_grid(second_rows), config=ComponentConfig(background_candidates=(0,))
    )
    assert len(first) == len(second) == 1
    assert first[0].translation_signature == second[0].translation_signature
    assert first[0].color != second[0].color or first_color == shifted_color


@given(st.permutations(tuple(range(16))))
def test_full_palette_permutation_preserves_inferred_geometry(
    permutation: list[int],
) -> None:
    source_rows = (
        (0, 0, 0, 0, 0),
        (0, 1, 1, 0, 0),
        (0, 1, 0, 0, 2),
        (0, 0, 0, 0, 2),
        (0, 0, 0, 0, 0),
    )
    permuted_rows = tuple(tuple(permutation[cell] for cell in row) for row in source_rows)
    source = extract_components(normalize_grid(source_rows))
    permuted = extract_components(normalize_grid(permuted_rows))

    assert sorted(component.translation_signature for component in source) == sorted(
        component.translation_signature for component in permuted
    )
