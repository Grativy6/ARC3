"""Evaluator-only oracle used to reject unsolvable generated curricula."""

from __future__ import annotations

import hashlib
import json
from collections import deque

from arc3.types import ActionName, ActionRequest, GameStateName

from .engine import AVAILABLE_ACTIONS, CurriculumSession, advance_level, initial_level_state
from .models import (
    CurriculumSpec,
    LevelOraclePlan,
    LevelSpec,
    LevelState,
    SequenceOracleReceipt,
)


def _search_key(state: LevelState) -> tuple[object, ...]:
    # BFS first reaches a state at its minimum step count, so steps may be omitted.
    # Animation is observational but mechanically harmless and may also be omitted.
    return (
        state.player,
        state.resource,
        state.pushable,
        state.consumed_one_shot,
        state.gate_open,
        state.delayed_remaining,
        state.terminal,
    )


def shortest_level_plan(spec: LevelSpec, *, max_states: int = 50_000) -> LevelOraclePlan:
    """Find a shortest winning action sequence using privileged evaluator state."""

    if max_states <= 0:
        raise ValueError("max_states must be positive")
    initial = initial_level_state(spec)
    frontier: deque[tuple[LevelState, tuple[ActionRequest, ...]]] = deque([(initial, ())])
    seen = {_search_key(initial)}
    explored = 0
    while frontier:
        state, prefix = frontier.popleft()
        explored += 1
        if explored > max_states:
            raise RuntimeError(f"oracle state bound exceeded for {spec.family.value}")
        for name in AVAILABLE_ACTIONS:
            action = ActionRequest(name)
            candidate, _ = advance_level(spec, state, action)
            actions = (*prefix, action)
            if candidate.terminal is GameStateName.WIN:
                return LevelOraclePlan(
                    family=spec.family,
                    actions=actions,
                    explored_states=explored,
                )
            if candidate.terminal is GameStateName.GAME_OVER:
                continue
            key = _search_key(candidate)
            if key not in seen:
                seen.add(key)
                frontier.append((candidate, actions))
    raise RuntimeError(f"generated level is not oracle-solvable: {spec.family.value}")


def validate_curriculum(spec: CurriculumSpec) -> SequenceOracleReceipt:
    """Solve and replay all ten levels, requiring official-style final WIN semantics."""

    plans = tuple(shortest_level_plan(level) for level in spec.levels)
    session = CurriculumSession(spec)
    action_names: list[str] = []
    for level_index, plan in enumerate(plans):
        for action in plan.actions:
            observation = session.step(action)
            action_names.append(action.name.value)
        expected = (
            GameStateName.WIN if level_index + 1 == len(plans) else GameStateName.NOT_FINISHED
        )
        if observation.state is not expected:
            raise AssertionError(
                f"level {level_index + 1} ended {observation.state.value}, expected {expected.value}"
            )
        if observation.levels_completed != level_index + 1:
            raise AssertionError("level completion counter did not advance exactly once")
    digest_payload = json.dumps(action_names, separators=(",", ":")).encode()
    return SequenceOracleReceipt(
        case_id=spec.case.case_id,
        seed=spec.case.seed,
        plans=plans,
        environment_actions=len(action_names),
        final_state=session.observation.state,
        levels_completed=session.observation.levels_completed,
        win_levels=session.observation.win_levels,
        action_digest=f"sha256:{hashlib.sha256(digest_payload).hexdigest()}",
    )


def force_game_over_then_reset(spec: CurriculumSpec) -> tuple[GameStateName, GameStateName]:
    """Exercise the failure/recovery lifecycle without claiming task success."""

    session = CurriculumSession(spec)
    while session.observation.state is GameStateName.NOT_FINISHED:
        observation = session.step(ActionRequest(ActionName.ACTION5))
    failed = observation.state
    reset = session.step(ActionRequest(ActionName.RESET)).state
    return failed, reset


__all__ = ["force_game_over_then_reset", "shortest_level_plan", "validate_curriculum"]
