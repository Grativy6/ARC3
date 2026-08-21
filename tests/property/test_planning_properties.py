from __future__ import annotations

from hypothesis import given
from hypothesis import strategies as st

from arc3.planning import PlanProblem, SearchAlgorithm, SearchBudget, search
from arc3.types import ActionName, ActionRequest
from arc3.world_model import Cell, ModelCandidate, MovementRule, SymbolicEntity, SymbolicState


@given(goal_x=st.integers(min_value=1, max_value=15))
def test_planning_astar_is_minimal_and_within_declared_budget(goal_x: int) -> None:
    state = SymbolicState(
        16,
        1,
        entities=(SymbolicEntity("mover", "controllable", (Cell(0, 0),)),),
    )
    model = ModelCandidate(
        model_id="property-line-model",
        hypothesis_ids=("generic-direction",),
        rules=(
            MovementRule("left", ActionName.ACTION1, -1, 0, entity_id="mover"),
            MovementRule("right", ActionName.ACTION2, 1, 0, entity_id="mover"),
        ),
    )
    problem = PlanProblem(
        problem_id=f"line-{goal_x}",
        initial_state=state,
        model=model,
        goal_id="reach-coordinate",
        goal_revision="r1",
        available_actions=(ActionRequest(ActionName.ACTION1), ActionRequest(ActionName.ACTION2)),
        goal_test=lambda candidate: candidate.entity("mover").anchor == Cell(goal_x, 0),  # type: ignore[union-attr]
        heuristic=lambda candidate: float(  # type: ignore[union-attr]
            goal_x - candidate.entity("mover").anchor.x
        ),
    )
    budget = SearchBudget(max_nodes=32, max_depth=15, max_time_ms=1_000)
    first = search(problem, algorithm=SearchAlgorithm.A_STAR, budget=budget)
    second = search(problem, algorithm=SearchAlgorithm.A_STAR, budget=budget)
    assert first.plan is not None and second.plan is not None
    assert len(first.plan.steps) == goal_x
    assert first.plan.plan_id == second.plan.plan_id
    assert first.expanded_nodes <= budget.max_nodes
    assert first.maximum_depth_reached <= budget.max_depth
