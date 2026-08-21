from __future__ import annotations

from hypothesis import given
from hypothesis import strategies as st

from arc3.adapters import GridFrame
from arc3.goals import (
    EvidenceDirection,
    GoalEvidence,
    held_out_goal_traps,
    measure_structural_goals,
)


@given(
    st.lists(
        st.lists(st.integers(min_value=0, max_value=1), min_size=3, max_size=3),
        min_size=3,
        max_size=3,
    ),
    st.integers(min_value=2, max_value=15),
)
def test_palette_renaming_does_not_change_structural_goal_measurements(
    rows: list[list[int]], replacement: int
) -> None:
    original = GridFrame.from_rows(rows)
    renamed = GridFrame.from_rows(
        [[replacement if value == 1 else 0 for value in row] for row in rows]
    )

    original_features = {
        (item.kind, item.target_state, item.discrepancy, item.satisfied)
        for item in measure_structural_goals(original)
    }
    renamed_features = {
        (item.kind, item.target_state, item.discrepancy, item.satisfied)
        for item in measure_structural_goals(renamed)
    }

    assert original_features == renamed_features


@given(
    st.lists(
        st.text(alphabet=st.characters(categories=("Ll", "Lu", "Nd")), min_size=1),
        min_size=1,
        max_size=8,
    )
)
def test_goal_evidence_source_identity_is_canonical(source_ids: list[str]) -> None:
    evidence = GoalEvidence(
        evidence_id="property-evidence",
        direction=EvidenceDirection.SUPPORT,
        source_event_ids=tuple(source_ids),
        observed_step=0,
        level_index=0,
        summary="canonical source set",
    )

    assert evidence.source_event_ids == tuple(sorted(set(source_ids)))


@given(
    st.integers(min_value=-(2**31), max_value=2**31 - 1),
    st.integers(min_value=1, max_value=20),
    st.integers(min_value=2, max_value=8),
)
def test_delayed_goal_cases_are_deterministic_and_never_alias_trap_actions(
    seed: int, count: int, horizon: int
) -> None:
    first = held_out_goal_traps(seed=seed, count=count, horizon=horizon)
    second = held_out_goal_traps(seed=seed, count=count, horizon=horizon)

    assert first == second
    assert all(
        progress != novelty
        for case in first
        for progress, novelty in zip(case.progress_actions, case.novelty_actions, strict=True)
    )
