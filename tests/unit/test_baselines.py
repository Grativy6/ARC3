"""Determinism and legality tests for game-agnostic Stage 02 baselines."""

from __future__ import annotations

import pytest

from arc3.adapters import GridFrame, Observation
from arc3.errors import PolicyError
from arc3.policy.baselines import (
    ActionCyclePolicy,
    CoordinateSweepPolicy,
    RandomValidPolicy,
    make_baseline,
)
from arc3.types import ActionName, ActionRequest, Coordinate, GameId, GameStateName


def observation(
    *,
    state: GameStateName = GameStateName.NOT_FINISHED,
    actions: tuple[ActionName, ...] = (
        ActionName.ACTION7,
        ActionName.ACTION6,
        ActionName.ACTION1,
    ),
) -> Observation:
    return Observation(
        game_id=GameId("generic-fixture-v1"),
        frames=(GridFrame.from_rows(((0, 1), (2, 3))),),
        state=state,
        levels_completed=0,
        win_levels=1,
        available_actions=actions,
    )


def test_seeded_random_policy_reproduces_valid_sequence() -> None:
    first = RandomValidPolicy(17)
    second = RandomValidPolicy(17)
    current = observation()

    left = [first.select(current) for _ in range(30)]
    right = [second.select(current) for _ in range(30)]

    assert left == right
    assert all(action.name in current.available_actions for action in left)
    assert all(
        (action.coordinate is not None) is (action.name is ActionName.ACTION6) for action in left
    )
    first.reset()
    assert [first.select(current) for _ in range(30)] == left


def test_cycle_uses_fixed_order_and_valid_action6_coordinate() -> None:
    policy = ActionCyclePolicy()
    current = observation()

    selected = [policy.select(current) for _ in range(5)]

    assert [action.name for action in selected] == [
        ActionName.ACTION1,
        ActionName.ACTION6,
        ActionName.ACTION7,
        ActionName.ACTION1,
        ActionName.ACTION6,
    ]
    assert selected[1].coordinate is not None
    assert (selected[1].coordinate.x, selected[1].coordinate.y) == (32, 32)
    policy.reset()
    assert policy.select(current).name is ActionName.ACTION1


def test_coordinate_sweep_is_coarse_deterministic_and_wraps() -> None:
    policy = CoordinateSweepPolicy()
    current = observation(actions=(ActionName.ACTION6,))

    selected = [policy.select(current) for _ in range(26)]
    coordinates = [action.coordinate for action in selected]

    assert coordinates[:6] == [
        Coordinate(0, 0),
        Coordinate(16, 0),
        Coordinate(32, 0),
        Coordinate(48, 0),
        Coordinate(63, 0),
        Coordinate(0, 16),
    ]
    assert coordinates[25] == coordinates[0]
    assert all(
        action == ActionRequest(ActionName.ACTION6, action.coordinate) for action in selected
    )


def test_terminal_handling_is_safe() -> None:
    for policy in (RandomValidPolicy(1), ActionCyclePolicy(), CoordinateSweepPolicy()):
        assert policy.select(observation(state=GameStateName.GAME_OVER)).name is ActionName.RESET
        assert policy.select(observation(state=GameStateName.NOT_PLAYED)).name is ActionName.RESET
        with pytest.raises(PolicyError, match="complete"):
            policy.select(observation(state=GameStateName.WIN))


def test_unavailable_coordinate_action_and_empty_space_fail() -> None:
    with pytest.raises(PolicyError, match="requires advertised ACTION6"):
        CoordinateSweepPolicy().select(observation(actions=(ActionName.ACTION1,)))
    with pytest.raises(PolicyError, match="no baseline-compatible action"):
        ActionCyclePolicy().select(observation(actions=()))


def test_factory_has_stable_names() -> None:
    assert isinstance(make_baseline("random", seed=3), RandomValidPolicy)
    assert isinstance(make_baseline("cycle"), ActionCyclePolicy)
    assert isinstance(make_baseline("sweep"), CoordinateSweepPolicy)
    with pytest.raises(PolicyError, match="unknown baseline"):
        make_baseline("unknown")
