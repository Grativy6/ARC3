"""Integration tests for fast recorded batches and measured baselines."""

from __future__ import annotations

import pytest

from arc3.lab import LabEvaluator, LabPartition, measure_baseline, run_batch
from arc3.policy.baselines import ActionCyclePolicy

pytestmark = pytest.mark.integration


def test_fast_batch_records_every_action_and_frame_deterministically() -> None:
    first = LabEvaluator(
        partition=LabPartition.HELD_OUT_COMBINATIONS,
        root_seed=2026,
        count=24,
    )
    second = LabEvaluator(
        partition=LabPartition.HELD_OUT_COMBINATIONS,
        root_seed=2026,
        count=24,
    )

    left = run_batch(first, lambda _seed: ActionCyclePolicy(), max_actions=32)
    right = run_batch(second, lambda _seed: ActionCyclePolicy(), max_actions=32)

    assert left == right
    assert len(left) == 24
    assert all(len(record.frame_hashes) == len(record.actions) + 1 for record in left)
    assert all(record.actions for record in left)


@pytest.mark.parametrize("partition", tuple(LabPartition))
def test_baseline_helper_emits_bounded_measured_synthetic_result(
    partition: LabPartition,
) -> None:
    first = measure_baseline(
        partition=partition,
        root_seed=20260821,
        episodes=15,
        max_actions=48,
        policy="random",
    )
    second = measure_baseline(
        partition=partition,
        root_seed=20260821,
        episodes=15,
        max_actions=48,
        policy="random",
    )

    assert first == second
    assert first.scorer == "arc3.lab.completion-rate.v1"
    assert first.episodes == 15
    assert first.completed == sum(record.completed for record in first.records)
    assert 0.0 <= first.completion_rate <= 1.0
    assert first.environment_actions <= 15 * 48
    assert first.mean_actions == first.environment_actions / 15


def test_large_oracle_self_test_runs_as_an_in_memory_batch() -> None:
    for partition in LabPartition:
        evaluator = LabEvaluator(partition=partition, root_seed=808, count=30)
        evaluator.assert_solvable()
