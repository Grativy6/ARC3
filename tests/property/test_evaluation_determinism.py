"""Property tests for deterministic Stage 13 intermediate baselines."""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from arc3.adapters.synthetic import SYNTHETIC_GAME_ID, SyntheticAdapter
from arc3.evaluation.baselines import make_evaluation_policy


def _sequence(agent: str, seed: int) -> tuple[object, ...]:
    session = SyntheticAdapter(seed=seed).open(SYNTHETIC_GAME_ID, seed=seed)
    policy = make_evaluation_policy(agent, seed=seed)
    actions: list[object] = []
    for _ in range(12):
        if session.observation.state.value == "WIN":
            break
        action = policy.select(session.observation)
        actions.append(action)
        session.step(action)
    return tuple(actions)


@settings(max_examples=20, deadline=None)
@given(seed=st.integers(min_value=-(2**31), max_value=2**31 - 1))
def test_intermediate_policy_action_stream_is_deterministic(seed: int) -> None:
    for agent in ("novelty", "trace"):
        assert _sequence(agent, seed) == _sequence(agent, seed)
