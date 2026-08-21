"""Property tests for deterministic generation and evaluator solvability."""

from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from arc3.lab import LabEvaluator, LabPartition

pytestmark = pytest.mark.property


@settings(max_examples=12, deadline=None)
@given(
    root_seed=st.integers(min_value=-(2**63), max_value=2**63 - 1),
    partition=st.sampled_from(tuple(LabPartition)),
)
def test_same_seed_produces_identical_cases_frames_and_oracles(
    root_seed: int, partition: LabPartition
) -> None:
    first = LabEvaluator(partition=partition, root_seed=root_seed, count=6)
    second = LabEvaluator(partition=partition, root_seed=root_seed, count=6)

    assert first.cases() == second.cases()
    for left_case, right_case in zip(first.cases(), second.cases(), strict=True):
        left = first.open(left_case)
        right = second.open(right_case)
        assert left.truth == right.truth
        assert left.session.observation == right.session.observation
        for left_action, right_action in zip(
            left.truth.oracle_plan, right.truth.oracle_plan, strict=True
        ):
            assert left_action == right_action
            assert left.take(left_action) == right.take(right_action)


@settings(max_examples=8, deadline=None)
@given(root_seed=st.integers(min_value=-100_000, max_value=100_000))
def test_generated_catalogs_are_solvable_and_leakage_free(root_seed: int) -> None:
    for partition in LabPartition:
        evaluator = LabEvaluator(partition=partition, root_seed=root_seed, count=6)
        evaluator.assert_no_observation_leakage()
        evaluator.assert_solvable()
