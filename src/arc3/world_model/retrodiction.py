"""Full-history retrodiction gate and explicit world-model scoring."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from arc3.trace.canonical import sha256_json
from arc3.types import ActionRequest

from .model import ModelCandidate, WorldModelEnsemble
from .state import SymbolicState


class PromotionStatus(StrEnum):
    PROMOTED = "promoted"
    REJECTED = "rejected"
    UNGATED_ABLATION = "ungated_ablation"


@dataclass(frozen=True, slots=True)
class PreservedTransition:
    """An immutable-reference transition used for retrospective falsification."""

    transition_id: str
    before: SymbolicState
    action: ActionRequest
    after: SymbolicState
    source_event_ids: tuple[str, ...]
    compatible_model_ids: tuple[str, ...] = ()

    def is_compatible_with(self, model_id: str) -> bool:
        return not self.compatible_model_ids or model_id in self.compatible_model_ids


@dataclass(frozen=True, slots=True)
class StateResidual:
    transition_id: str
    missing_entities: tuple[str, ...]
    unexpected_entities: tuple[str, ...]
    changed_entities: tuple[str, ...]
    missing_facts: tuple[str, ...]
    unexpected_facts: tuple[str, ...]
    changed_counters: tuple[str, ...]
    changed_toggles: tuple[str, ...]
    selection_mismatch: bool
    attachment_mismatch: bool

    @property
    def count(self) -> int:
        return sum(
            (
                len(self.missing_entities),
                len(self.unexpected_entities),
                len(self.changed_entities),
                len(self.missing_facts),
                len(self.unexpected_facts),
                len(self.changed_counters),
                len(self.changed_toggles),
                int(self.selection_mismatch),
                int(self.attachment_mismatch),
            )
        )


@dataclass(frozen=True, slots=True)
class ModelScore:
    fit: float
    complexity: int
    contradictions: int
    residual_coverage: float
    rank_weight: int
    total: float
    weight_kind: str = "uncalibrated_rank"


@dataclass(frozen=True, slots=True)
class RetrodictionArtifact:
    """Complete gate receipt; no promoted state exists without one."""

    artifact_id: str
    model_id: str
    retrodiction_enabled: bool
    compatible_transition_ids: tuple[str, ...]
    tested_transition_ids: tuple[str, ...]
    explicitly_excluded_transition_ids: tuple[str, ...]
    matched_transition_ids: tuple[str, ...]
    contradiction_transition_ids: tuple[str, ...]
    residuals: tuple[StateResidual, ...]
    score: ModelScore
    status: PromotionStatus
    complete: bool

    @property
    def promotable(self) -> bool:
        return self.status is PromotionStatus.PROMOTED


def retrodict(
    model: ModelCandidate,
    transitions: tuple[PreservedTransition, ...],
    *,
    enabled: bool = True,
) -> RetrodictionArtifact:
    """Evaluate every compatible transition or record its explicit condition exclusion."""

    compatible = tuple(item for item in transitions if item.is_compatible_with(model.model_id))
    tested: list[str] = []
    excluded: list[str] = []
    matched: list[str] = []
    contradicted: list[str] = []
    residuals: list[StateResidual] = []
    if enabled:
        for transition in compatible:
            if model.has_explicit_exclusion(transition.before, transition.action):
                excluded.append(transition.transition_id)
                continue
            tested.append(transition.transition_id)
            prediction = model.predict(transition.before, transition.action)
            if prediction.after_state == transition.after:
                matched.append(transition.transition_id)
            else:
                contradicted.append(transition.transition_id)
                residuals.append(
                    compare_states(
                        transition.transition_id,
                        prediction.after_state,
                        transition.after,
                    )
                )
    fit = len(matched) / len(tested) if tested else 0.0
    observed_residual_mass = sum(max(residual.count, 1) for residual in residuals)
    residual_coverage = (
        len(matched) / (len(matched) + observed_residual_mass)
        if matched or observed_residual_mass
        else 0.0
    )
    score = ModelScore(
        fit=fit,
        complexity=model.complexity,
        contradictions=len(contradicted),
        residual_coverage=residual_coverage,
        rank_weight=model.rank_weight,
        total=round(
            100.0 * fit
            + 20.0 * residual_coverage
            + float(model.rank_weight)
            - float(model.complexity)
            - 100.0 * len(contradicted),
            9,
        ),
    )
    complete = len(tested) + len(excluded) == len(compatible)
    if not enabled:
        status = PromotionStatus.UNGATED_ABLATION
    elif complete and tested and not contradicted:
        status = PromotionStatus.PROMOTED
    else:
        status = PromotionStatus.REJECTED
    content = {
        "model_id": model.model_id,
        "enabled": enabled,
        "compatible": [item.transition_id for item in compatible],
        "tested": tested,
        "excluded": excluded,
        "matched": matched,
        "contradicted": contradicted,
        "status": status.value,
    }
    digest = sha256_json(content)
    return RetrodictionArtifact(
        artifact_id=f"retrodiction:{digest.removeprefix('sha256:')[:24]}",
        model_id=model.model_id,
        retrodiction_enabled=enabled,
        compatible_transition_ids=tuple(item.transition_id for item in compatible),
        tested_transition_ids=tuple(tested),
        explicitly_excluded_transition_ids=tuple(excluded),
        matched_transition_ids=tuple(matched),
        contradiction_transition_ids=tuple(contradicted),
        residuals=tuple(residuals),
        score=score,
        status=status,
        complete=complete,
    )


def gated_ensemble(
    candidates: tuple[ModelCandidate, ...],
    artifacts: tuple[RetrodictionArtifact, ...],
    *,
    allow_ungated_ablation: bool = False,
) -> WorldModelEnsemble:
    """Build an ensemble only from candidates with matching gate artifacts."""

    artifacts_by_model = {artifact.model_id: artifact for artifact in artifacts}
    accepted = []
    for candidate in candidates:
        artifact = artifacts_by_model.get(candidate.model_id)
        if artifact is None:
            continue
        if artifact.promotable or (
            allow_ungated_ablation and artifact.status is PromotionStatus.UNGATED_ABLATION
        ):
            accepted.append(candidate)
    return WorldModelEnsemble(tuple(accepted))


def compare_states(
    transition_id: str, predicted: SymbolicState, observed: SymbolicState
) -> StateResidual:
    predicted_entities = {item.entity_id: item for item in predicted.entities}
    observed_entities = {item.entity_id: item for item in observed.entities}
    common = set(predicted_entities) & set(observed_entities)
    return StateResidual(
        transition_id=transition_id,
        missing_entities=tuple(sorted(set(observed_entities) - set(predicted_entities))),
        unexpected_entities=tuple(sorted(set(predicted_entities) - set(observed_entities))),
        changed_entities=tuple(
            sorted(key for key in common if predicted_entities[key] != observed_entities[key])
        ),
        missing_facts=tuple(sorted(set(observed.facts) - set(predicted.facts))),
        unexpected_facts=tuple(sorted(set(predicted.facts) - set(observed.facts))),
        changed_counters=tuple(
            sorted(
                key
                for key in set(dict(predicted.counters)) | set(dict(observed.counters))
                if dict(predicted.counters).get(key) != dict(observed.counters).get(key)
            )
        ),
        changed_toggles=tuple(
            sorted(
                key
                for key in set(dict(predicted.toggles)) | set(dict(observed.toggles))
                if dict(predicted.toggles).get(key) != dict(observed.toggles).get(key)
            )
        ),
        selection_mismatch=predicted.selected_id != observed.selected_id,
        attachment_mismatch=predicted.attachments != observed.attachments,
    )


__all__ = [
    "ModelScore",
    "PreservedTransition",
    "PromotionStatus",
    "RetrodictionArtifact",
    "StateResidual",
    "compare_states",
    "gated_ensemble",
    "retrodict",
]
