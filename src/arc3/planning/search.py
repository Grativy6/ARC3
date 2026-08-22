"""Bounded deterministic BFS, uniform-cost, and A* symbolic search."""

from __future__ import annotations

import heapq
import math
import time
from dataclasses import dataclass

from arc3.errors import PlanningError
from arc3.trace.canonical import sha256_json
from arc3.types import ActionRequest, JSONValue
from arc3.world_model import SymbolicState

from .models import (
    Plan,
    PlanProblem,
    PlanScore,
    PlanScoreWeights,
    PlanStep,
    SearchAlgorithm,
    SearchBudget,
    SearchResult,
    SearchStatus,
)


@dataclass(frozen=True, slots=True)
class _Node:
    state: SymbolicState
    actions: tuple[ActionRequest, ...]
    states: tuple[SymbolicState, ...]
    costs: tuple[float, ...]
    risks: tuple[float, ...]
    information: tuple[float, ...]

    @property
    def depth(self) -> int:
        return len(self.actions)

    @property
    def cost(self) -> float:
        return sum(self.costs)


def search(
    problem: PlanProblem,
    *,
    algorithm: SearchAlgorithm = SearchAlgorithm.A_STAR,
    budget: SearchBudget | None = None,
    score_weights: PlanScoreWeights | None = None,
    enforce_time_budget: bool = True,
) -> SearchResult:
    """Find one bounded plan using stable priorities and action tie-breaks.

    ``enforce_time_budget=False`` retains elapsed time as output telemetry but
    removes it from search termination and therefore from policy semantics.
    Deterministic callers must still supply finite node and depth budgets.
    """

    budget = budget or SearchBudget()
    score_weights = score_weights or PlanScoreWeights()
    started = time.perf_counter()
    root = _Node(problem.initial_state, (), (problem.initial_state,), (), (), ())
    frontier: list[tuple[float, int, tuple[int, ...], str, _Node]] = []
    _push(frontier, root, problem, algorithm)
    best_cost: dict[str, float] = {problem.initial_state.state_id: 0.0}
    expanded = 0
    generated = 0
    maximum_depth = 0
    depth_truncated = False

    while frontier:
        elapsed_ms = (time.perf_counter() - started) * 1_000.0
        if enforce_time_budget and elapsed_ms >= budget.max_time_ms:
            return _result(
                SearchStatus.TIME_BUDGET,
                algorithm,
                None,
                expanded,
                generated,
                maximum_depth,
                elapsed_ms,
                budget,
            )
        if expanded >= budget.max_nodes:
            return _result(
                SearchStatus.NODE_BUDGET,
                algorithm,
                None,
                expanded,
                generated,
                maximum_depth,
                elapsed_ms,
                budget,
            )

        _priority, _depth, _actions, _state_id, node = heapq.heappop(frontier)
        if node.cost > best_cost.get(node.state.state_id, math.inf):
            continue
        expanded += 1
        maximum_depth = max(maximum_depth, node.depth)
        if problem.goal_test(node.state):
            plan = _make_plan(problem, node, algorithm, score_weights)
            return _result(
                SearchStatus.FOUND,
                algorithm,
                plan,
                expanded,
                generated,
                maximum_depth,
                (time.perf_counter() - started) * 1_000.0,
                budget,
            )
        if node.depth >= budget.max_depth:
            depth_truncated = True
            continue

        for action in problem.available_actions:
            prediction = problem.model.predict(node.state, action)
            next_state = prediction.after_state
            transition_cost = problem.action_cost(node.state, action, next_state)
            risk = problem.failure_risk(node.state, action, next_state)
            information = problem.information_value(node.state, action, next_state)
            _validate_metric("action cost", transition_cost, positive=True)
            _validate_metric("failure risk", risk)
            _validate_metric("information value", information)
            generated += 1
            if next_state == node.state:
                continue
            next_cost = node.cost + transition_cost
            if next_cost >= best_cost.get(next_state.state_id, math.inf):
                continue
            best_cost[next_state.state_id] = next_cost
            child = _Node(
                next_state,
                (*node.actions, action),
                (*node.states, next_state),
                (*node.costs, transition_cost),
                (*node.risks, risk),
                (*node.information, information),
            )
            _push(frontier, child, problem, algorithm)

    status = SearchStatus.DEPTH_BUDGET if depth_truncated else SearchStatus.EXHAUSTED
    return _result(
        status,
        algorithm,
        None,
        expanded,
        generated,
        maximum_depth,
        (time.perf_counter() - started) * 1_000.0,
        budget,
    )


def _validate_metric(name: str, value: float, *, positive: bool = False) -> None:
    lower_bound = value <= 0 if positive else value < 0
    if not math.isfinite(value) or lower_bound:
        qualifier = "positive" if positive else "non-negative"
        raise PlanningError(f"{name} must be finite and {qualifier}")


def _push(
    frontier: list[tuple[float, int, tuple[int, ...], str, _Node]],
    node: _Node,
    problem: PlanProblem,
    algorithm: SearchAlgorithm,
) -> None:
    if algorithm is SearchAlgorithm.BREADTH_FIRST:
        priority = float(node.depth)
    elif algorithm is SearchAlgorithm.UNIFORM_COST:
        priority = node.cost
    else:
        heuristic = problem.heuristic(node.state)
        _validate_metric("heuristic", heuristic)
        priority = node.cost + heuristic
    semantic_rank = {action: index for index, action in enumerate(problem.available_actions)}
    action_path = tuple(semantic_rank[action] for action in node.actions)
    heapq.heappush(frontier, (priority, node.depth, action_path, node.state.state_id, node))


def _make_plan(
    problem: PlanProblem,
    node: _Node,
    algorithm: SearchAlgorithm,
    weights: PlanScoreWeights,
) -> Plan:
    steps = tuple(
        PlanStep(
            index=index,
            action=action,
            before_state_id=node.states[index].state_id,
            predicted_state=node.states[index + 1],
            cost=node.costs[index],
            failure_risk=node.risks[index],
            information_value=node.information[index],
        )
        for index, action in enumerate(node.actions)
    )
    total_risk = sum(node.risks)
    total_information = sum(node.information)
    utility = (
        weights.completion * problem.completion_likelihood
        - weights.action_count * len(steps)
        - weights.risk * total_risk
        + weights.information * total_information
    )
    score = PlanScore(
        completion_likelihood=problem.completion_likelihood,
        action_count=len(steps),
        total_cost=node.cost,
        total_risk=total_risk,
        total_information=total_information,
        utility=utility,
    )
    identity: dict[str, JSONValue] = {
        "problem_id": problem.problem_id,
        "model_id": problem.model_id,
        "goal_id": problem.goal_id,
        "goal_revision": problem.goal_revision,
        "algorithm": algorithm.value,
        "initial_state_id": problem.initial_state.state_id,
        "actions": [
            {
                "name": action.name.value,
                "coordinate": (
                    [action.coordinate.x, action.coordinate.y]
                    if action.coordinate is not None
                    else None
                ),
            }
            for action in node.actions
        ],
    }
    digest = sha256_json(identity).removeprefix("sha256:")[:24]
    return Plan(
        plan_id=f"plan:{digest}",
        problem_id=problem.problem_id,
        model_id=problem.model_id,
        goal_id=problem.goal_id,
        goal_revision=problem.goal_revision,
        algorithm=algorithm,
        initial_state_id=problem.initial_state.state_id,
        final_state_id=node.state.state_id,
        steps=steps,
        score=score,
    )


def _result(
    status: SearchStatus,
    algorithm: SearchAlgorithm,
    plan: Plan | None,
    expanded: int,
    generated: int,
    maximum_depth: int,
    elapsed_ms: float,
    budget: SearchBudget,
) -> SearchResult:
    return SearchResult(
        status,
        algorithm,
        plan,
        expanded,
        generated,
        maximum_depth,
        elapsed_ms,
        budget,
    )


__all__ = ["search"]
