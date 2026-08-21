"""End-to-end synthetic observation-policy-action-scorecard loop."""

from __future__ import annotations

import pytest

from arc3.adapters.synthetic import SYNTHETIC_GAME_ID, SyntheticAdapter
from arc3.policy.baselines import ActionCyclePolicy
from arc3.types import EvaluationSurface, GameStateName

pytestmark = pytest.mark.integration


def run_loop(seed: int) -> tuple[list[str], list[str], float, int, int]:
    adapter = SyntheticAdapter(seed=seed, size=8, max_steps=5)
    session = adapter.open(SYNTHETIC_GAME_ID)
    policy = ActionCyclePolicy()
    frame_hashes = [str(session.observation.frames[-1].digest)]
    actions: list[str] = []

    for _ in range(16):
        if session.observation.state is GameStateName.WIN:
            break
        action = policy.select(session.observation)
        actions.append(action.name.value)
        result = session.step(action, reasoning={"category": "baseline"})
        frame_hashes.append(str(result.frames[-1].digest))

    scorecard = session.close()
    assert session.close() is scorecard
    return (
        actions,
        frame_hashes,
        scorecard.score,
        scorecard.total_actions,
        scorecard.total_resets,
    )


def test_synthetic_loop_is_deterministic_and_measured() -> None:
    first = run_loop(29)
    second = run_loop(29)

    assert first == second
    actions, frame_hashes, score, action_count, reset_count = first
    assert actions
    assert len(frame_hashes) == len(actions) + 1
    assert score in {0.0, 1.0}
    assert action_count <= len(actions)
    assert reset_count == len(actions) - action_count


def test_synthetic_descriptor_and_scorecard_are_first_party() -> None:
    adapter = SyntheticAdapter(seed=5, size=6, max_steps=3)
    descriptor = adapter.list_games()[0]
    session = adapter.open(str(descriptor.game_id))

    assert descriptor.locally_available is True
    assert descriptor.tags == ("synthetic", "deterministic")
    assert session.observation.state is GameStateName.NOT_FINISHED
    assert session.observation.frames[0].width == 6
    scorecard = session.scorecard()
    assert scorecard.surface is EvaluationSurface.SYNTHETIC
    assert scorecard.verified is True
    assert scorecard.scorer == "arc3.synthetic.v1"
