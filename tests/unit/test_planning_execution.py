from __future__ import annotations

import pytest

from arc3.errors import PlanningError
from arc3.planning import (
    ActionEmission,
    PlanExecutor,
    PlanProblem,
    RecoveryMode,
    RecoveryPolicy,
    SearchAlgorithm,
    search,
)
from arc3.types import ActionName, ActionRequest, GameStateName
from arc3.world_model import Cell, ModelCandidate, MovementRule, SymbolicEntity, SymbolicState


def _plan() -> tuple[PlanProblem, object]:
    state = SymbolicState(
        4,
        1,
        entities=(SymbolicEntity("mover", "controllable", (Cell(0, 0),)),),
    )
    model = ModelCandidate(
        model_id="execution-model",
        hypothesis_ids=("movement",),
        rules=(MovementRule("right", ActionName.ACTION1, 1, 0, entity_id="mover"),),
    )
    problem = PlanProblem(
        problem_id="execution-problem",
        initial_state=state,
        model=model,
        goal_id="exit",
        goal_revision="r1",
        available_actions=(ActionRequest(ActionName.ACTION1),),
        goal_test=lambda candidate: candidate.entity("mover").anchor == Cell(2, 0),  # type: ignore[union-attr]
    )
    result = search(
        problem,
        algorithm=SearchAlgorithm.BREADTH_FIRST,
        enforce_time_budget=False,
    )
    assert result.plan is not None
    return problem, result.plan


def test_planning_executor_requires_consequence_before_next_action() -> None:
    problem, plan = _plan()
    executor = PlanExecutor()
    executor.load(plan)  # type: ignore[arg-type]
    first = executor.next_action(
        problem.initial_state,
        model_id=problem.model_id,
        goal_id=problem.goal_id,
        goal_revision=problem.goal_revision,
    )
    assert isinstance(first, ActionEmission)
    with pytest.raises(PlanningError, match="consequence"):
        executor.next_action(
            problem.initial_state,
            model_id=problem.model_id,
            goal_id=problem.goal_id,
            goal_revision=problem.goal_revision,
        )
    predicted = plan.steps[0].predicted_state  # type: ignore[union-attr]
    assessment = executor.apply_consequence(predicted)
    assert assessment.matched
    assert assessment.recovery is None


def test_planning_failed_prediction_emits_recovery_not_blind_continuation() -> None:
    problem, plan = _plan()
    executor = PlanExecutor()
    executor.load(plan)  # type: ignore[arg-type]
    emission = executor.next_action(
        problem.initial_state,
        model_id=problem.model_id,
        goal_id=problem.goal_id,
        goal_revision=problem.goal_revision,
    )
    assert isinstance(emission, ActionEmission)
    assessment = executor.apply_consequence(problem.initial_state, same_model_viable=True)
    assert not assessment.matched
    assert assessment.recovery is not None
    assert assessment.recovery.mode is RecoveryMode.REPLAN_SAME_MODEL
    assert assessment.recovery.to_trace_payload()["invalidated_plan_id"] == plan.plan_id  # type: ignore[union-attr]
    assert executor.plan is None


def test_planning_recovery_modes_cover_probe_undo_reopen_and_reset() -> None:
    problem, plan = _plan()
    probe = ActionRequest(ActionName.ACTION3)
    restore = ActionRequest(ActionName.ACTION5)
    scenarios = (
        ({"restore_action": restore}, RecoveryMode.SUPPORTED_UNDO, ActionName.ACTION5),
        (
            {"models_disagree": True, "discriminating_probe": probe},
            RecoveryMode.DISCRIMINATING_PROBE,
            ActionName.ACTION3,
        ),
        ({"same_model_viable": False}, RecoveryMode.REOPEN_MODEL, None),
    )
    for kwargs, expected, action_name in scenarios:
        executor = PlanExecutor()
        executor.load(plan)  # type: ignore[arg-type]
        executor.next_action(
            problem.initial_state,
            model_id=problem.model_id,
            goal_id=problem.goal_id,
            goal_revision=problem.goal_revision,
        )
        assessment = executor.apply_consequence(problem.initial_state, **kwargs)
        assert assessment.recovery is not None
        assert assessment.recovery.mode is expected
        assert (
            assessment.recovery.next_action.name
            if assessment.recovery.next_action is not None
            else None
        ) is action_name

    executor = PlanExecutor()
    executor.load(plan)  # type: ignore[arg-type]
    reset = executor.next_action(
        problem.initial_state,
        model_id=problem.model_id,
        goal_id=problem.goal_id,
        goal_revision=problem.goal_revision,
        game_state=GameStateName.GAME_OVER,
    )
    assert reset is not None
    assert reset.mode is RecoveryMode.MANDATORY_RESET  # type: ignore[union-attr]
    assert reset.next_action == ActionRequest(ActionName.RESET)  # type: ignore[union-attr]


def test_planning_invalidates_model_or_goal_identity_change() -> None:
    problem, plan = _plan()
    executor = PlanExecutor()
    executor.load(plan)  # type: ignore[arg-type]
    decision = executor.next_action(
        problem.initial_state,
        model_id="replacement-model",
        goal_id=problem.goal_id,
        goal_revision=problem.goal_revision,
    )
    assert decision is not None
    assert decision.mode is RecoveryMode.REOPEN_MODEL  # type: ignore[union-attr]


def test_planning_no_recovery_ablation_stops_without_blind_continuation() -> None:
    problem, plan = _plan()
    executor = PlanExecutor(recovery_policy=RecoveryPolicy(enabled=False))
    executor.load(plan)  # type: ignore[arg-type]
    executor.next_action(
        problem.initial_state,
        model_id=problem.model_id,
        goal_id=problem.goal_id,
        goal_revision=problem.goal_revision,
    )
    assessment = executor.apply_consequence(problem.initial_state)
    assert assessment.recovery is not None
    assert assessment.recovery.mode is RecoveryMode.STOP_NO_RECOVERY
    assert assessment.recovery.next_action is None
