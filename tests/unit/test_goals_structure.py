from __future__ import annotations

from arc3.adapters import GridFrame
from arc3.goals import (
    GoalKind,
    compare_structural_goals,
    measure_structural_goals,
)


def test_structural_detector_proposes_exit_slot_contact_and_discrepancy_candidates() -> None:
    grid = GridFrame.from_rows(
        (
            (1, 1, 1, 0, 2),
            (1, 0, 1, 0, 0),
            (1, 1, 1, 0, 3),
            (0, 0, 0, 0, 0),
        )
    )

    features = measure_structural_goals(grid)
    kinds = {feature.kind for feature in features}

    assert GoalKind.EXIT in kinds
    assert GoalKind.MATCHING_SLOT in kinds
    assert GoalKind.CONTACT in kinds
    assert GoalKind.DISCREPANCY_REDUCTION in kinds


def test_repeated_pattern_completion_is_compared_as_a_measured_discrepancy() -> None:
    before = GridFrame.from_rows(((1, 1, 1), (1, 1, 1), (1, 0, 1)))
    after = GridFrame.from_rows(((1, 1, 1), (1, 1, 1), (1, 1, 1)))

    changes = compare_structural_goals(
        measure_structural_goals(before),
        measure_structural_goals(after),
    )

    completion = next(
        change for change in changes if change.after.kind is GoalKind.COMPLETION_PATTERN
    )
    assert completion.before.discrepancy == 1
    assert completion.after.discrepancy == 0
    assert completion.improved is True
    assert completion.after.satisfied is True


def test_palette_permutation_preserves_generic_structural_kinds_and_discrepancies() -> None:
    first = GridFrame.from_rows(((1, 1, 1), (1, 1, 1), (1, 0, 1)))
    permuted = GridFrame.from_rows(((7, 7, 7), (7, 7, 7), (7, 4, 7)))

    first_features = {
        (feature.kind, feature.target_state, feature.discrepancy)
        for feature in measure_structural_goals(first)
        if feature.kind in {GoalKind.COMPLETION_PATTERN, GoalKind.DISCREPANCY_REDUCTION}
    }
    permuted_features = {
        (feature.kind, feature.target_state, feature.discrepancy)
        for feature in measure_structural_goals(permuted)
        if feature.kind in {GoalKind.COMPLETION_PATTERN, GoalKind.DISCREPANCY_REDUCTION}
    }

    assert first_features == permuted_features
