from __future__ import annotations

from arc3.adapters import Observation
from arc3.perception.delta import CellChangeKind, measure_delta
from arc3.perception.frame import normalize_grid
from arc3.perception.metadata import observation_metadata
from arc3.types import ActionName, GameId, GameStateName


def test_exact_cell_and_metadata_delta() -> None:
    before = normalize_grid([[0, 0, 0], [0, 1, 1], [0, 0, 2]])
    after = normalize_grid([[0, 3, 0], [0, 1, 0], [0, 4, 5]])

    delta = measure_delta(
        before,
        after,
        before_metadata={"levels": 0, "state": "NOT_FINISHED"},
        after_metadata={"levels": 1, "state": "NOT_FINISHED"},
    )

    assert delta.changed_cell_count == 4
    assert delta.changed_mask == (
        (False, True, False),
        (False, False, True),
        (False, True, True),
    )
    assert [
        (change.x, change.y, change.before, change.after, change.kind)
        for change in delta.cell_changes
    ] == [
        (1, 0, 0, 3, CellChangeKind.ADDITION),
        (2, 1, 1, 0, CellChangeKind.REMOVAL),
        (1, 2, 0, 4, CellChangeKind.ADDITION),
        (2, 2, 2, 5, CellChangeKind.RECOLOR),
    ]
    assert [
        (
            change.field,
            change.before_present,
            change.after_present,
            change.before,
            change.after,
        )
        for change in delta.metadata_changes
    ] == [("levels", True, True, 0, 1)]
    assert not delta.apparent_noop


def test_delta_measures_extent_changes() -> None:
    before = normalize_grid([[0]])
    after = normalize_grid([[0, 1], [0, 0]])
    delta = measure_delta(before, after)

    assert delta.width == 2
    assert delta.height == 2
    assert delta.changed_cell_count == 3
    assert [change.kind for change in delta.cell_changes] == [
        CellChangeKind.ADDITION,
        CellChangeKind.EXTENT_CHANGE,
        CellChangeKind.EXTENT_CHANGE,
    ]


def test_metadata_presence_is_measured_separately_from_null() -> None:
    frame = normalize_grid([[0]])
    delta = measure_delta(frame, frame, before_metadata={"optional": None}, after_metadata={})
    assert len(delta.metadata_changes) == 1
    assert delta.metadata_changes[0].before_present
    assert not delta.metadata_changes[0].after_present


def test_identical_frame_and_metadata_is_apparent_noop() -> None:
    frame = normalize_grid([[1, 2]])
    delta = measure_delta(frame, frame, before_metadata={"score": 1}, after_metadata={"score": 1})
    assert delta.apparent_noop
    assert delta.changed_mask == ((False, False),)


def test_metadata_only_change_is_not_an_apparent_noop() -> None:
    frame = normalize_grid([[1, 2]])
    delta = measure_delta(
        frame,
        frame,
        before_metadata={"state": "NOT_FINISHED"},
        after_metadata={"state": "GAME_OVER"},
    )

    assert delta.changed_cell_count == 0
    assert [change.field for change in delta.metadata_changes] == ["state"]
    assert not delta.apparent_noop


def test_observation_metadata_includes_official_state_and_prevents_shadowing() -> None:
    observation = Observation(
        game_id=GameId("fixture"),
        frames=(normalize_grid([[0]]),),
        state=GameStateName.GAME_OVER,
        levels_completed=2,
        win_levels=3,
        available_actions=(ActionName.RESET,),
        full_reset=True,
        upstream_metadata=(("state", "spoofed"), ("counter", 7)),
    )

    assert observation_metadata(observation) == {
        "state": "GAME_OVER",
        "levels_completed": 2,
        "win_levels": 3,
        "available_actions": "RESET",
        "full_reset": True,
        "upstream.state": "spoofed",
        "counter": 7,
    }
