from __future__ import annotations

from arc3.perception.components import ComponentConfig, extract_components
from arc3.perception.frame import normalize_grid
from arc3.perception.tracking import (
    ComponentChangeKind,
    detect_global_shift,
    track_components,
)


def _components(rows: list[list[int]]) -> tuple:
    return extract_components(
        normalize_grid(rows), config=ComponentConfig(background_candidates=(0,))
    )


def test_ambiguous_correspondence_retains_all_best_alternatives() -> None:
    before = _components([[0, 0, 0, 1, 0, 0, 0]])
    after = _components([[0, 1, 0, 0, 0, 1, 0]])

    result = track_components(before, after, frame_extent=(7, 1))

    assert result.has_ambiguity
    assert len(result.correspondences) == 1
    correspondence = result.correspondences[0]
    assert correspondence.ambiguous
    assert len(correspondence.alternatives) == 2
    assert correspondence.sole_alternative is None
    assert not result.unmatched_after_ids
    assert not result.changes


def test_structural_changes_are_measured_without_rewriting_correspondence() -> None:
    before = _components([[0, 1, 1, 0, 0]])
    after = _components([[0, 0, 2, 2, 2]])
    result = track_components(before, after, frame_extent=(5, 1), minimum_score=0.4)

    assert len(result.correspondences) == 1
    change = result.changes[0]
    assert set(change.kinds) == {
        ComponentChangeKind.RECOLOR,
        ComponentChangeKind.TRANSLATION,
        ComponentChangeKind.RESIZE,
        ComponentChangeKind.SHAPE_CHANGE,
    }


def test_complete_shared_translation_is_reported_as_global_shift() -> None:
    before = _components([[0, 1, 0, 0, 2, 0, 0]])
    after = _components([[0, 0, 1, 0, 0, 2, 0]])
    result = track_components(before, after, frame_extent=(7, 1), ambiguity_tolerance=0.01)

    shift = detect_global_shift(result)
    assert shift is not None
    assert shift.displacement == (1, 0)
    assert shift.supporting_correspondences == 2


def test_additions_and_removals_remain_explicit() -> None:
    before = _components([[1, 1, 0, 0, 0]])
    after = _components([[0, 0, 0, 2, 0]])
    result = track_components(before, after, frame_extent=(5, 1), minimum_score=0.95)
    assert {change.kinds for change in result.changes} == {
        (ComponentChangeKind.REMOVAL,),
        (ComponentChangeKind.ADDITION,),
    }
