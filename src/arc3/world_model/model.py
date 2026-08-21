"""Deterministic executable candidate and underdetermined ensemble models."""

from __future__ import annotations

from dataclasses import asdict, dataclass

from arc3.errors import WorldModelError
from arc3.trace.canonical import normalize_json, sha256_json
from arc3.types import ActionRequest, JSONValue

from .rules import (
    RuleEffect,
    RulePrimitive,
    conditions_match,
    execute_rules,
    rule_action,
    rule_complexity,
)
from .state import SymbolicState


@dataclass(frozen=True, slots=True)
class ModelPrediction:
    """One candidate model's deterministic outcome and rank-only weight."""

    prediction_id: str
    model_id: str
    before_state_id: str
    action: ActionRequest
    after_state: SymbolicState
    effects: tuple[RuleEffect, ...]
    applied_rule_ids: tuple[str, ...]
    rank_weight: int

    @property
    def after_state_id(self) -> str:
        return self.after_state.state_id


@dataclass(frozen=True, slots=True)
class ModelCandidate:
    """A compatible set of hypothesis-linked executable rules."""

    model_id: str
    hypothesis_ids: tuple[str, ...]
    rules: tuple[RulePrimitive, ...]
    rank_weight: int = 0
    compile_residuals: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.model_id.strip():
            raise WorldModelError("model_id must be non-empty")
        if not self.hypothesis_ids:
            raise WorldModelError("model candidates require at least one source hypothesis")
        if len(set(self.hypothesis_ids)) != len(self.hypothesis_ids):
            raise WorldModelError("source hypothesis IDs must be unique")
        if len({rule.rule_id for rule in self.rules}) != len(self.rules):
            raise WorldModelError("world-model rule IDs must be unique")

    @property
    def complexity(self) -> int:
        return sum(rule_complexity(rule) for rule in self.rules)

    def has_explicit_exclusion(self, state: SymbolicState, action: ActionRequest) -> bool:
        """Whether declared conditions, rather than a mismatch, exclude this transition."""

        action_rules = tuple(rule for rule in self.rules if rule_action(rule) is action.name)
        return bool(action_rules) and all(
            bool(rule.conditions) and not conditions_match(rule.conditions, state)
            for rule in action_rules
        )

    def predict(self, state: SymbolicState, action: ActionRequest) -> ModelPrediction:
        execution = execute_rules(self.rules, state, action)
        identity = sha256_json(
            {
                "model_id": self.model_id,
                "before_state_id": state.state_id,
                "action": _action_dict(action),
                "after_state_id": execution.state.state_id,
            }
        )
        return ModelPrediction(
            prediction_id=f"prediction:{identity.removeprefix('sha256:')[:24]}",
            model_id=self.model_id,
            before_state_id=state.state_id,
            action=action,
            after_state=execution.state,
            effects=execution.effects,
            applied_rule_ids=execution.applied_rule_ids,
            rank_weight=self.rank_weight,
        )


@dataclass(frozen=True, slots=True)
class AlternativeOutcome:
    """One distinct predicted state retained across supporting candidates."""

    alternative_rank: int
    after_state: SymbolicState
    supporting_model_ids: tuple[str, ...]
    prediction_ids: tuple[str, ...]
    rank_weight: int
    weight_kind: str = "uncalibrated_rank"

    @property
    def after_state_id(self) -> str:
        return self.after_state.state_id


@dataclass(frozen=True, slots=True)
class EnsemblePrediction:
    before_state_id: str
    action: ActionRequest
    alternatives: tuple[AlternativeOutcome, ...]

    @property
    def underdetermined(self) -> bool:
        return len(self.alternatives) > 1


@dataclass(frozen=True, slots=True)
class WorldModelEnsemble:
    """A stable set of viable candidates; disagreement remains observable."""

    candidates: tuple[ModelCandidate, ...]

    def __post_init__(self) -> None:
        candidates = tuple(
            sorted(self.candidates, key=lambda item: (-item.rank_weight, item.model_id))
        )
        if not candidates:
            raise WorldModelError("a world-model ensemble cannot be empty")
        if len({item.model_id for item in candidates}) != len(candidates):
            raise WorldModelError("ensemble model IDs must be unique")
        object.__setattr__(self, "candidates", candidates)

    def predict(self, state: SymbolicState, action: ActionRequest) -> EnsemblePrediction:
        predictions = tuple(candidate.predict(state, action) for candidate in self.candidates)
        grouped: dict[str, list[ModelPrediction]] = {}
        for prediction in predictions:
            grouped.setdefault(prediction.after_state_id, []).append(prediction)
        ranked = sorted(
            grouped.values(),
            key=lambda group: (
                -max(item.rank_weight for item in group),
                group[0].after_state_id,
            ),
        )
        alternatives = tuple(
            AlternativeOutcome(
                alternative_rank=index,
                after_state=group[0].after_state,
                supporting_model_ids=tuple(sorted(item.model_id for item in group)),
                prediction_ids=tuple(sorted(item.prediction_id for item in group)),
                rank_weight=max(item.rank_weight for item in group),
            )
            for index, group in enumerate(ranked, start=1)
        )
        return EnsemblePrediction(state.state_id, action, alternatives)

    def without(self, model_ids: tuple[str, ...]) -> WorldModelEnsemble | None:
        retained = tuple(item for item in self.candidates if item.model_id not in set(model_ids))
        return WorldModelEnsemble(retained) if retained else None


def make_model_candidate(
    *,
    hypothesis_ids: tuple[str, ...],
    rules: tuple[RulePrimitive, ...],
    rank_weight: int = 0,
    compile_residuals: tuple[str, ...] = (),
) -> ModelCandidate:
    """Construct a candidate with an identity derived from its complete rule content."""

    normalized_rules: list[JSONValue] = []
    for rule in rules:
        value = normalize_json(asdict(rule))
        normalized_rules.append(value)
    digest = sha256_json(
        {
            "hypothesis_ids": list(sorted(hypothesis_ids)),
            "rules": normalized_rules,
            "compile_residuals": list(sorted(compile_residuals)),
        }
    )
    return ModelCandidate(
        model_id=f"world-model:{digest.removeprefix('sha256:')[:24]}",
        hypothesis_ids=tuple(sorted(hypothesis_ids)),
        rules=tuple(sorted(rules, key=lambda rule: rule.rule_id)),
        rank_weight=rank_weight,
        compile_residuals=tuple(sorted(compile_residuals)),
    )


def _action_dict(action: ActionRequest) -> dict[str, JSONValue]:
    return {
        "name": action.name.value,
        "coordinate": (
            {"x": action.coordinate.x, "y": action.coordinate.y}
            if action.coordinate is not None
            else None
        ),
    }


__all__ = [
    "AlternativeOutcome",
    "EnsemblePrediction",
    "ModelCandidate",
    "ModelPrediction",
    "WorldModelEnsemble",
    "make_model_candidate",
]
