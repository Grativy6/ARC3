"""Property tests for exploration bounds and weak-prior override."""

from __future__ import annotations

from hypothesis import given
from hypothesis import strategies as st

from arc3.adapters import GridFrame
from arc3.exploration import generate_coordinate_candidates
from arc3.perception.components import GridPoint
from arc3.types import Coordinate


@given(
    width=st.integers(min_value=1, max_value=64),
    height=st.integers(min_value=1, max_value=64),
    limit=st.integers(min_value=1, max_value=40),
    seed_points=st.lists(
        st.tuples(st.integers(min_value=0, max_value=63), st.integers(min_value=0, max_value=63)),
        max_size=30,
    ),
)
def test_coordinate_generation_is_deterministic_unique_and_bounded(
    width: int, height: int, limit: int, seed_points: list[tuple[int, int]]
) -> None:
    grid = GridFrame.from_rows([[0] * width for _ in range(height)])
    in_bounds = tuple(GridPoint(x, y) for x, y in seed_points if x < width and y < height)

    first = generate_coordinate_candidates(grid, disagreement_cells=in_bounds, max_candidates=limit)
    second = generate_coordinate_candidates(
        grid, disagreement_cells=in_bounds, max_candidates=limit
    )

    assert first == second
    assert len(first) <= limit
    coordinates = tuple(candidate.coordinate for candidate in first)
    assert len(coordinates) == len(set(coordinates))
    assert all(
        Coordinate(point.x, point.y) == point and 0 <= point.x < width and 0 <= point.y < height
        for point in coordinates
    )
