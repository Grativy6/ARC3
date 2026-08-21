from __future__ import annotations

from arc3.types import ActionName, ActionRequest
from arc3.world_model import (
    Cell,
    MovementRule,
    PredictionBook,
    PreservedTransition,
    SymbolicEntity,
    SymbolicState,
    gated_ensemble,
    make_model_candidate,
    retrodict,
)
from arc3.world_model.benchmark import measure_retrodiction_comparison


def state(x: int, *, target: int = 6) -> SymbolicState:
    facts = ("goal",) if x == target else ()
    return SymbolicState(
        8,
        3,
        (
            SymbolicEntity("piece", "mover", (Cell(x, 1),), color=2),
            SymbolicEntity("target", "target", (Cell(target, 1),), color=7),
        ),
        facts=facts,
    )


def transition(identifier: str, before_x: int, after_x: int) -> PreservedTransition:
    return PreservedTransition(
        identifier,
        state(before_x),
        ActionRequest(ActionName.ACTION1),
        state(after_x),
        (f"event:{identifier}:before", f"event:{identifier}:after"),
    )


def test_retrodiction_materially_improves_held_out_directional_combination() -> None:
    """Synthetic label: one completion versus zero under the retrodiction-off ablation."""

    result = measure_retrodiction_comparison()

    assert (result.gated_completed, result.gated_actions) == (4, 16)
    assert (result.ungated_completed, result.ungated_actions) == (0, 16)
    assert len(result.gated_model_ids) == 1
    assert len(result.ungated_model_ids) == 2


def test_prediction_receipt_precedes_action_and_mismatch_reopens_models_and_plans() -> None:
    model = make_model_candidate(
        hypothesis_ids=("H-RIGHT",),
        rules=(MovementRule("R-RIGHT", ActionName.ACTION1, 1, 0, entity_id="piece"),),
    )
    artifact = retrodict(model, (transition("T", 1, 2),))
    ensemble = gated_ensemble((model,), (artifact,))
    book = PredictionBook()
    receipt = book.emit(
        action_decision_id="A-1",
        ensemble=ensemble,
        state=state(3),
        action=ActionRequest(ActionName.ACTION1),
        dependent_plan_ids=("PLAN-2", "PLAN-1"),
    )

    mismatch = book.match(receipt.receipt_id, state(3))

    assert receipt.emitted_before_action
    assert receipt.to_dict()["schema"] == "arc3.world-model.prediction-receipt.v0.1"
    assert not mismatch.matched_any
    assert mismatch.mismatched_prediction_ids
    assert mismatch.reopenings[0].model_id == model.model_id
    assert mismatch.reopenings[0].new_status == "candidate"
    assert mismatch.reopenings[0].invalidated_plan_ids == ("PLAN-1", "PLAN-2")
    assert mismatch.reopenings[0].residual.changed_entities == ("piece",)
    assert mismatch.to_dict()["schema"] == "arc3.world-model.consequence-assessment.v0.1"
