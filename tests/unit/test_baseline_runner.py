"""Bounded episode-runner tests."""

from __future__ import annotations

import pytest

from arc3.adapters.synthetic import SYNTHETIC_GAME_ID, SyntheticAdapter
from arc3.baseline_runner import StopReason, run_baseline_episode
from arc3.policy.baselines import ActionCyclePolicy, RandomValidPolicy
from arc3.types import GameStateName


def test_runner_records_action_receipts_and_stops_at_budget() -> None:
    session = SyntheticAdapter(seed=1, max_steps=64).open(SYNTHETIC_GAME_ID)

    result = run_baseline_episode(
        session,
        RandomValidPolicy(1),
        max_actions=3,
        max_resets=2,
    )

    assert result.stop_reason in {StopReason.WIN, StopReason.ACTION_BUDGET}
    assert result.environment_actions <= 3
    assert len(result.receipts) == result.environment_actions + result.resets
    assert all(receipt.before_frames and receipt.after_frames for receipt in result.receipts)


def test_runner_enforces_reset_budget_after_game_over() -> None:
    session = SyntheticAdapter(seed=1, max_steps=1).open(SYNTHETIC_GAME_ID)

    result = run_baseline_episode(
        session,
        ActionCyclePolicy(),
        max_actions=5,
        max_resets=1,
    )

    assert result.stop_reason is StopReason.RESET_BUDGET
    assert result.environment_actions == 2
    assert result.resets == 1
    assert result.final_observation.state is GameStateName.GAME_OVER


@pytest.mark.parametrize(("max_actions", "max_resets"), [(0, 1), (1, 0), (True, 1)])
def test_runner_rejects_invalid_budgets(max_actions: int, max_resets: int) -> None:
    session = SyntheticAdapter().open(SYNTHETIC_GAME_ID)

    with pytest.raises(ValueError, match="positive integer"):
        run_baseline_episode(
            session,
            ActionCyclePolicy(),
            max_actions=max_actions,
            max_resets=max_resets,
        )
