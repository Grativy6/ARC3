from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from arc3.perception.frame import NormalizedFrame, normalize_grid
from arc3.types import ActionName, GameStateName


def test_normalization_copies_input_and_has_stable_content_hash() -> None:
    source = [[0, 1], [2, 3]]
    first = normalize_grid(source)
    source[0][0] = 9
    second = normalize_grid(((0, 1), (2, 3)))

    assert first.cells == ((0, 1), (2, 3))
    assert first.digest == second.digest
    assert str(first.digest).startswith("sha256:")
    assert len(str(first.digest)) == 71


def test_normalized_frame_retains_measurements_without_inference() -> None:
    frame = NormalizedFrame.from_rows(
        [[0, 1]],
        source_index=2,
        game_state=GameStateName.NOT_FINISHED,
        score=0.25,
        available_actions=[ActionName.ACTION1, ActionName.ACTION6],
        timestamp_ns=123,
        metadata={"z": 2, "a": 1},
    )

    assert frame.content_hash == frame.grid.digest
    assert frame.metadata == (("a", 1), ("z", 2))
    with pytest.raises(FrozenInstanceError):
        frame.source_index = 3  # type: ignore[misc]


@pytest.mark.parametrize(
    "rows",
    [[], [[]], [[0], [0, 1]], [[-1]], [[16]], [[True]]],
)
def test_normalize_grid_rejects_invalid_grids(rows: list[list[int]]) -> None:
    with pytest.raises(ValueError):
        normalize_grid(rows)


def test_normalized_frame_validates_source_metadata() -> None:
    grid = normalize_grid([[0]])
    with pytest.raises(ValueError, match="source_index"):
        NormalizedFrame(grid=grid, source_index=-1)
    with pytest.raises(ValueError, match="duplicates"):
        NormalizedFrame(
            grid=grid,
            source_index=0,
            available_actions=(ActionName.ACTION1, ActionName.ACTION1),
        )
