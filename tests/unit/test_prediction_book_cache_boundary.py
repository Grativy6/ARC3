from __future__ import annotations

from arc3.types import ActionName, ActionRequest
from arc3.world_model import (
    AlternativeOutcome,
    EnsemblePrediction,
    PredictionBook,
    SymbolicState,
)


def test_cached_typed_prediction_mints_fresh_current_decision_receipts() -> None:
    action = ActionRequest(ActionName.ACTION1)
    prediction = EnsemblePrediction(
        before_state_id="state:before",
        action=action,
        alternatives=(
            AlternativeOutcome(
                alternative_rank=1,
                after_state=SymbolicState(width=2, height=2, facts=("predicted",)),
                supporting_model_ids=("model:one",),
                prediction_ids=("prediction:one",),
                rank_weight=1,
            ),
        ),
    )
    book = PredictionBook()

    first = book.emit_prediction(
        action_decision_id="decision:first",
        prediction=prediction,
        dependent_plan_ids=("plan:one",),
    )
    second = book.emit_prediction(
        action_decision_id="decision:second",
        prediction=prediction,
        dependent_plan_ids=("plan:one",),
    )

    assert first.prediction == second.prediction == prediction
    assert first.receipt_id != second.receipt_id
    assert first.action_decision_id == "decision:first"
    assert second.action_decision_id == "decision:second"
    assert first.to_dict()["action_decision_id"] != second.to_dict()["action_decision_id"]
