"""Unit coverage for discriminating probes, suppression, undo, and fallback."""

from __future__ import annotations

from arc3.exploration import (
    EffectClassification,
    EffectKind,
    ExplorationPlanner,
    ModelAlternative,
    ModelPrediction,
    ProbeContext,
    ProbeOption,
    StateFeatures,
)
from arc3.types import ActionName, ActionRequest, GameStateName


def _state(*, token: str = "phase-a", terminal: bool = False) -> StateFeatures:
    return StateFeatures(
        width=8,
        height=8,
        palette_size=3,
        component_count=2,
        changed_cell_count=0,
        game_state=GameStateName.GAME_OVER if terminal else GameStateName.NOT_FINISHED,
        available_actions=(ActionName.ACTION1, ActionName.ACTION2, ActionName.ACTION7),
        condition_tokens=(token,),
    )


def _alternatives() -> tuple[ModelAlternative, ...]:
    first = ActionRequest(ActionName.ACTION1)
    second = ActionRequest(ActionName.ACTION2)
    return (
        ModelAlternative(
            "a",
            (
                ModelPrediction(first, "same", EffectKind.NO_OP),
                ModelPrediction(second, "north", EffectKind.MOVEMENT),
            ),
        ),
        ModelAlternative(
            "b",
            (
                ModelPrediction(first, "same", EffectKind.NO_OP),
                ModelPrediction(second, "toggle", EffectKind.INTERACTION),
            ),
        ),
    )


def test_planner_prefers_action_that_discriminates_active_alternatives() -> None:
    planner = ExplorationPlanner()
    context = ProbeContext(_state(), actions_used=0, action_budget=20)
    options = (
        ProbeOption(ActionRequest(ActionName.ACTION1), novelty=1.0),
        ProbeOption(ActionRequest(ActionName.ACTION2), novelty=0.1),
    )

    selected = planner.select(options, context=context, alternatives=_alternatives())

    assert selected.action.name is ActionName.ACTION2
    assert selected.information == 1.0


def test_repeated_noop_is_suppressed_but_changed_condition_reopens_probe() -> None:
    planner = ExplorationPlanner(suppression_threshold=2)
    action = ActionRequest(ActionName.ACTION2)
    options = (
        ProbeOption(ActionRequest(ActionName.ACTION1)),
        ProbeOption(action, novelty=1.0),
    )
    original = ProbeContext(_state(token="closed"), actions_used=0, action_budget=20)
    noop = EffectClassification(frozenset({EffectKind.NO_OP}))
    planner.record_outcome(original, action, noop)
    planner.record_outcome(original, action, noop)

    suppressed = planner.select(options, context=original, alternatives=_alternatives())
    changed = ProbeContext(_state(token="open"), actions_used=1, action_budget=20)
    reopened = planner.select(options, context=changed, alternatives=_alternatives())

    assert suppressed.action.name is ActionName.ACTION1
    assert reopened.action.name is ActionName.ACTION2


def test_undo_requires_supported_receipt_and_current_availability() -> None:
    planner = ExplorationPlanner()
    context = ProbeContext(_state(), actions_used=0, action_budget=20)
    undo = ActionRequest(ActionName.ACTION7)
    options = (
        ProbeOption(ActionRequest(ActionName.ACTION1)),
        ProbeOption(undo, progress=1.0, novelty=1.0),
    )

    unsupported = planner.select(options, context=context)
    planner.record_outcome(
        context,
        undo,
        EffectClassification(frozenset({EffectKind.UNDO}), changed_cells=2),
    )
    supported = planner.select(options, context=context)

    assert unsupported.action.name is ActionName.ACTION1
    assert supported.action.name is ActionName.ACTION7


def test_budget_fallback_prefers_progress_and_game_over_forces_reset() -> None:
    planner = ExplorationPlanner()
    near_budget = ProbeContext(_state(), actions_used=9, action_budget=10, fallback_reserve=2)
    options = (
        ProbeOption(ActionRequest(ActionName.ACTION1), progress=0.9, failure_risk=0.1),
        ProbeOption(ActionRequest(ActionName.ACTION2), novelty=1.0),
    )
    fallback = planner.select(options, context=near_budget, alternatives=_alternatives())
    terminal = ProbeContext(_state(terminal=True), actions_used=2, action_budget=10)
    forced = planner.select(options, context=terminal)

    assert fallback.fallback is True
    assert fallback.action.name is ActionName.ACTION1
    assert forced.action.name is ActionName.RESET
