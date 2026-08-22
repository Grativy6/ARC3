from __future__ import annotations

from importlib import import_module

import pytest

from arc3.planning import (
    PlanProblem,
    SearchAlgorithm,
    SearchBudget,
    SearchStatus,
    search,
)
from arc3.types import ActionName, ActionRequest
from arc3.world_model import Cell, ModelCandidate, MovementRule, SymbolicEntity, SymbolicState


def _line_problem(*, goal_x: int = 4) -> PlanProblem:
    state = SymbolicState(
        6,
        1,
        entities=(SymbolicEntity("mover", "controllable", (Cell(0, 0),)),),
    )
    model = ModelCandidate(
        model_id="line-model",
        hypothesis_ids=("move-map",),
        rules=(
            MovementRule("right", ActionName.ACTION2, 1, 0, entity_id="mover"),
            MovementRule("left", ActionName.ACTION1, -1, 0, entity_id="mover"),
        ),
    )

    def reached(candidate: SymbolicState) -> bool:
        mover = candidate.entity("mover")
        return mover is not None and mover.anchor == Cell(goal_x, 0)

    def heuristic(candidate: SymbolicState) -> float:
        mover = candidate.entity("mover")
        assert mover is not None
        return float(abs(goal_x - mover.anchor.x))

    return PlanProblem(
        problem_id="line-problem",
        initial_state=state,
        model=model,
        goal_id="reach-target",
        goal_revision="evidence-3",
        available_actions=(ActionRequest(ActionName.ACTION2), ActionRequest(ActionName.ACTION1)),
        goal_test=reached,
        heuristic=heuristic,
        failure_risk=lambda _before, action, _after: (
            0.2 if action.name is ActionName.ACTION1 else 0.0
        ),
        information_value=lambda _before, action, _after: (
            0.5 if action.name is ActionName.ACTION2 else 0.0
        ),
    )


def test_planning_all_deterministic_searches_find_shortest_plan() -> None:
    problem = _line_problem()
    for algorithm in SearchAlgorithm:
        result = search(
            problem,
            algorithm=algorithm,
            budget=SearchBudget(max_nodes=32, max_depth=8, max_time_ms=1_000),
        )
        assert result.status is SearchStatus.FOUND
        assert result.plan is not None
        assert [step.action.name for step in result.plan.steps] == [ActionName.ACTION2] * 4
        assert result.plan.score.action_count == 4
        assert result.plan.score.total_information == 2.0
        assert result.plan.score.completion_likelihood == 1.0


def test_planning_tie_break_and_plan_identity_are_deterministic() -> None:
    problem = _line_problem(goal_x=1)
    first = search(problem, algorithm=SearchAlgorithm.BREADTH_FIRST)
    second = search(problem, algorithm=SearchAlgorithm.BREADTH_FIRST)
    assert first.plan is not None and second.plan is not None
    assert first.plan.plan_id == second.plan.plan_id
    assert first.plan.steps == second.plan.steps


def test_planning_reports_node_and_depth_budget_exhaustion() -> None:
    problem = _line_problem(goal_x=5)
    node_limited = search(
        problem,
        budget=SearchBudget(max_nodes=1, max_depth=8, max_time_ms=1_000),
    )
    depth_limited = search(
        problem,
        budget=SearchBudget(max_nodes=32, max_depth=2, max_time_ms=1_000),
    )
    assert node_limited.status is SearchStatus.NODE_BUDGET
    assert depth_limited.status is SearchStatus.DEPTH_BUDGET
    assert node_limited.plan is None
    assert depth_limited.plan is None


def test_deterministic_search_disables_elapsed_time_as_a_termination_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    problem = _line_problem()
    tick = 0

    def advanced_clock() -> float:
        nonlocal tick
        tick += 10
        return float(tick)

    search_module = import_module("arc3.planning.search")
    monkeypatch.setattr(search_module.time, "perf_counter", advanced_clock)
    result = search(
        problem,
        budget=SearchBudget(max_nodes=32, max_depth=8, max_time_ms=1),
        enforce_time_budget=False,
    )

    assert result.status is SearchStatus.FOUND
