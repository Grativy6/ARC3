"""Held-out synthetic Stage 07 action-semantics mechanism measurement."""

from __future__ import annotations

import pytest

from arc3.exploration import (
    MechanismStatus,
    compare_exploration_baselines,
    held_out_semantic_cases,
)

pytestmark = pytest.mark.integration


def test_information_probe_reduces_median_semantic_identification_actions() -> None:
    cases = held_out_semantic_cases(seed=20260821, count=101)

    result = compare_exploration_baselines(cases, seed=7107)

    assert result.episodes == 101
    assert result.exploration_median == 1.0
    assert result.exploration_median < result.random_median
    assert result.exploration_median < result.cycle_median
    assert result.status is MechanismStatus.OBSERVED


def test_comparison_is_deterministic_for_pinned_seed() -> None:
    cases = held_out_semantic_cases(seed=404, count=25)

    first = compare_exploration_baselines(cases, seed=99)
    second = compare_exploration_baselines(cases, seed=99)

    assert first == second
