from __future__ import annotations

from arc3.goals import (
    GoalMechanismStatus,
    compare_goal_policy_to_novelty,
    held_out_goal_traps,
)


def test_goal_policy_beats_novelty_only_on_delayed_proxy_goal_tasks() -> None:
    cases = held_out_goal_traps(seed=20260821, count=64, horizon=5)

    result = compare_goal_policy_to_novelty(cases)

    assert result.surface == "synthetic"
    assert result.scorer == "arc3.goals.delayed-proxy-completion.v1"
    assert result.episodes == 64
    assert result.action_budget_per_episode == 5
    assert result.goal_completions == 64
    assert result.novelty_completions == 0
    assert result.goal_actions == result.novelty_actions == 320
    assert result.completion_rate_difference == 1.0
    assert result.status is GoalMechanismStatus.OBSERVED


def test_goal_trap_generation_and_comparison_are_deterministic() -> None:
    first_cases = held_out_goal_traps(seed=71, count=24)
    second_cases = held_out_goal_traps(seed=71, count=24)

    assert first_cases == second_cases
    assert compare_goal_policy_to_novelty(first_cases) == compare_goal_policy_to_novelty(
        second_cases
    )
