"""Prediction-before-action receipts and mismatch-triggered reopening signals."""

from __future__ import annotations

from dataclasses import dataclass

from arc3.errors import WorldModelError
from arc3.trace.canonical import normalize_json, sha256_json
from arc3.types import ActionRequest, JSONValue

from .model import EnsemblePrediction, WorldModelEnsemble
from .retrodiction import StateResidual, compare_states
from .state import SymbolicState


@dataclass(frozen=True, slots=True)
class PredictionReceipt:
    receipt_id: str
    action_decision_id: str
    before_state_id: str
    action: ActionRequest
    prediction: EnsemblePrediction
    dependent_plan_ids: tuple[str, ...]
    emitted_before_action: bool = True
    weight_kind: str = "uncalibrated_rank"

    def to_dict(self) -> dict[str, JSONValue]:
        payload = normalize_json(
            {
                "schema": "arc3.world-model.prediction-receipt.v0.1",
                "receipt_id": self.receipt_id,
                "action_decision_id": self.action_decision_id,
                "before_state_id": self.before_state_id,
                "action": {
                    "name": self.action.name.value,
                    "coordinate": (
                        [self.action.coordinate.x, self.action.coordinate.y]
                        if self.action.coordinate is not None
                        else None
                    ),
                },
                "alternatives": [
                    {
                        "alternative_rank": alternative.alternative_rank,
                        "after_state_id": alternative.after_state_id,
                        "supporting_model_ids": list(alternative.supporting_model_ids),
                        "prediction_ids": list(alternative.prediction_ids),
                        "rank_weight": alternative.rank_weight,
                        "weight_kind": alternative.weight_kind,
                    }
                    for alternative in self.prediction.alternatives
                ],
                "dependent_plan_ids": list(self.dependent_plan_ids),
                "emitted_before_action": self.emitted_before_action,
                "weight_kind": self.weight_kind,
            }
        )
        assert isinstance(payload, dict)
        return payload


@dataclass(frozen=True, slots=True)
class ModelReopening:
    model_id: str
    previous_status: str
    new_status: str
    caused_by_receipt_id: str
    invalidated_plan_ids: tuple[str, ...]
    residual: StateResidual

    def to_dict(self) -> dict[str, JSONValue]:
        payload = normalize_json(
            {
                "model_id": self.model_id,
                "previous_status": self.previous_status,
                "new_status": self.new_status,
                "caused_by_receipt_id": self.caused_by_receipt_id,
                "invalidated_plan_ids": list(self.invalidated_plan_ids),
                "residual_count": self.residual.count,
                "residual_transition_id": self.residual.transition_id,
            }
        )
        assert isinstance(payload, dict)
        return payload


@dataclass(frozen=True, slots=True)
class ConsequenceAssessment:
    receipt_id: str
    prediction_receipt_id: str
    observed_state_id: str
    matched_prediction_ids: tuple[str, ...]
    mismatched_prediction_ids: tuple[str, ...]
    reopenings: tuple[ModelReopening, ...]

    @property
    def matched_any(self) -> bool:
        return bool(self.matched_prediction_ids)

    def to_dict(self) -> dict[str, JSONValue]:
        payload = normalize_json(
            {
                "schema": "arc3.world-model.consequence-assessment.v0.1",
                "receipt_id": self.receipt_id,
                "prediction_receipt_id": self.prediction_receipt_id,
                "observed_state_id": self.observed_state_id,
                "matched_prediction_ids": list(self.matched_prediction_ids),
                "mismatched_prediction_ids": list(self.mismatched_prediction_ids),
                "reopenings": [item.to_dict() for item in self.reopenings],
            }
        )
        assert isinstance(payload, dict)
        return payload


class PredictionBook:
    """Enforce emission before matching and retain pending prediction identity."""

    def __init__(self) -> None:
        self._pending: dict[str, PredictionReceipt] = {}

    def emit(
        self,
        *,
        action_decision_id: str,
        ensemble: WorldModelEnsemble,
        state: SymbolicState,
        action: ActionRequest,
        dependent_plan_ids: tuple[str, ...] = (),
    ) -> PredictionReceipt:
        prediction = ensemble.predict(state, action)
        content: dict[str, JSONValue] = {
            "action_decision_id": action_decision_id,
            "before_state_id": state.state_id,
            "action": action.name.value,
            "coordinate": (
                [action.coordinate.x, action.coordinate.y]
                if action.coordinate is not None
                else None
            ),
            "prediction_ids": [
                prediction_id
                for alternative in prediction.alternatives
                for prediction_id in alternative.prediction_ids
            ],
            "dependent_plan_ids": list(sorted(dependent_plan_ids)),
        }
        digest = sha256_json(content)
        receipt = PredictionReceipt(
            receipt_id=f"prediction-receipt:{digest.removeprefix('sha256:')[:24]}",
            action_decision_id=action_decision_id,
            before_state_id=state.state_id,
            action=action,
            prediction=prediction,
            dependent_plan_ids=tuple(sorted(set(dependent_plan_ids))),
        )
        if receipt.receipt_id in self._pending:
            raise WorldModelError("duplicate pending prediction receipt")
        self._pending[receipt.receipt_id] = receipt
        return receipt

    def match(self, receipt_id: str, observed: SymbolicState) -> ConsequenceAssessment:
        try:
            receipt = self._pending.pop(receipt_id)
        except KeyError as error:
            raise WorldModelError("consequence requires a pending prediction receipt") from error
        matched: list[str] = []
        mismatched: list[str] = []
        reopenings: list[ModelReopening] = []
        for alternative in receipt.prediction.alternatives:
            if alternative.after_state == observed:
                matched.extend(alternative.prediction_ids)
                continue
            mismatched.extend(alternative.prediction_ids)
            residual = compare_states(receipt.receipt_id, alternative.after_state, observed)
            reopenings.extend(
                ModelReopening(
                    model_id=model_id,
                    previous_status="promoted",
                    new_status="candidate",
                    caused_by_receipt_id=receipt.receipt_id,
                    invalidated_plan_ids=receipt.dependent_plan_ids,
                    residual=residual,
                )
                for model_id in alternative.supporting_model_ids
            )
        content = {
            "prediction_receipt_id": receipt.receipt_id,
            "observed_state_id": observed.state_id,
            "matched": sorted(matched),
            "mismatched": sorted(mismatched),
        }
        digest = sha256_json(content)
        return ConsequenceAssessment(
            receipt_id=f"consequence-assessment:{digest.removeprefix('sha256:')[:24]}",
            prediction_receipt_id=receipt.receipt_id,
            observed_state_id=observed.state_id,
            matched_prediction_ids=tuple(sorted(matched)),
            mismatched_prediction_ids=tuple(sorted(mismatched)),
            reopenings=tuple(sorted(reopenings, key=lambda item: item.model_id)),
        )


__all__ = [
    "ConsequenceAssessment",
    "ModelReopening",
    "PredictionBook",
    "PredictionReceipt",
]
