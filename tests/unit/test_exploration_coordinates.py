"""Unit coverage for bounded ACTION6 coordinate generation."""

from __future__ import annotations

from arc3.adapters import GridFrame
from arc3.exploration import CoordinateSource, generate_coordinate_candidates
from arc3.perception.components import ComponentConfig, GridPoint, extract_components
from arc3.perception.delta import measure_delta
from arc3.types import Coordinate


def test_coordinate_candidates_cover_every_required_generic_source() -> None:
    before = GridFrame.from_rows(
        [
            [0, 0, 0, 0, 0, 0, 0],
            [0, 2, 2, 0, 0, 0, 0],
            [0, 2, 2, 0, 0, 0, 0],
            [0, 0, 0, 0, 0, 0, 0],
            [0, 0, 0, 0, 3, 0, 0],
            [0, 0, 0, 0, 0, 0, 0],
            [0, 0, 0, 0, 0, 0, 0],
        ]
    )
    after = GridFrame.from_rows(
        [
            [0, 0, 0, 0, 0, 0, 0],
            [0, 0, 2, 2, 0, 0, 0],
            [0, 0, 2, 2, 0, 0, 0],
            [0, 0, 0, 0, 0, 0, 0],
            [0, 0, 0, 0, 3, 0, 0],
            [0, 0, 0, 0, 0, 0, 0],
            [0, 0, 0, 0, 0, 0, 0],
        ]
    )
    components = extract_components(after, config=ComponentConfig(background_candidates=(0,)))
    delta = measure_delta(before, after)

    candidates = generate_coordinate_candidates(
        after,
        components=components,
        changed_cells=delta.cell_changes,
        empty_slots=(GridPoint(3, 3),),
        disagreement_cells=(GridPoint(5, 5),),
        explored=(Coordinate(6, 6),),
        max_candidates=18,
    )
    sources = {source for candidate in candidates for source in candidate.sources}

    assert sources == set(CoordinateSource)
    assert len(candidates) <= 18
    assert len({candidate.coordinate for candidate in candidates}) == len(candidates)
    assert Coordinate(6, 6) not in {candidate.coordinate for candidate in candidates}


def test_duplicate_coordinate_retains_multiple_supporting_sources() -> None:
    grid = GridFrame.from_rows([[0, 0, 0], [0, 4, 0], [0, 0, 0]])
    components = extract_components(grid, config=ComponentConfig(background_candidates=(0,)))

    candidates = generate_coordinate_candidates(
        grid,
        components=components,
        disagreement_cells=(GridPoint(1, 1),),
        max_candidates=12,
    )
    center = next(candidate for candidate in candidates if candidate.coordinate == Coordinate(1, 1))

    assert CoordinateSource.COMPONENT_CENTER in center.sources
    assert CoordinateSource.DISAGREEMENT in center.sources
