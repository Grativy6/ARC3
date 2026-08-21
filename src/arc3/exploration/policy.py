"""Information-efficient generic probe ranking and repetition suppression."""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass

from arc3.types import ActionName, ActionRequest, GameStateName

from .models import (
    EffectClassification,
    EffectKind,
    ModelAlternative,
    ProbeContext,
    ProbeOption,
    ProbeUtilityWeights,
)
from .statistics import ActionEffectStatistics


def discrimination_information(
    action: ActionRequest, alternatives: tuple[ModelAlternative, ...]
) -> float:
    """Return normalized weighted entropy of predicted outcomes in 0..1."""

    labels: defaultdict[str, float] = defaultdict(float)
    total = 0.0
    for alternative in alternatives:
        prediction = alternative.prediction_for(action)
        if prediction is None:
            continue
        labels[prediction.outcome_label] += alternative.weight
        total += alternative.weight
    if total <= 0 or len(labels) <= 1:
        return 0.0
    entropy = -sum((weight / total) * math.log2(weight / total) for weight in labels.values())
    return entropy / math.log2(len(labels))


@dataclass(frozen=True, slots=True)
class RankedProbe:
    """A selected option with concise, trace-safe utility terms."""

    action: ActionRequest
    utility: float
    information: float
    repetition_count: int
    fallback: bool


class IneffectiveActionMemory:
    """Condition-indexed no-op counts; a changed condition gets a fresh key."""

    def __init__(self, *, suppression_threshold: int = 2) -> None:
        if isinstance(suppression_threshold, bool) or suppression_threshold <= 0:
            raise ValueError("suppression_threshold must be a positive integer")
        self._threshold = suppression_threshold
        self._counts: defaultdict[tuple[str, ActionRequest], int] = defaultdict(int)

    def record(
        self,
        state_signature: str,
        action: ActionRequest,
        effect: EffectClassification,
    ) -> None:
        key = (state_signature, action)
        if effect.kinds == frozenset({EffectKind.NO_OP}):
            self._counts[key] += 1
        else:
            self._counts.pop(key, None)

    def count(self, state_signature: str, action: ActionRequest) -> int:
        return self._counts.get((state_signature, action), 0)

    def suppressed(self, state_signature: str, action: ActionRequest) -> bool:
        return self.count(state_signature, action) >= self._threshold


class ExplorationPlanner:
    """Rank legal probes using evidence, alternatives, risk, and budget."""

    def __init__(
        self,
        *,
        statistics: ActionEffectStatistics | None = None,
        weights: ProbeUtilityWeights | None = None,
        suppression_threshold: int = 2,
    ) -> None:
        self.statistics = statistics or ActionEffectStatistics()
        self.weights = weights or ProbeUtilityWeights()
        self.ineffective = IneffectiveActionMemory(suppression_threshold=suppression_threshold)

    def record_outcome(
        self,
        context: ProbeContext,
        action: ActionRequest,
        effect: EffectClassification,
    ) -> None:
        self.statistics.observe(context.state, action, effect)
        self.ineffective.record(context.state.signature, action, effect)

    def _eligible(self, option: ProbeOption, context: ProbeContext) -> bool:
        action = option.action
        if context.state.game_state is GameStateName.GAME_OVER:
            return action.name is ActionName.RESET
        if action.name is ActionName.RESET:
            return True
        if action.name not in context.state.available_actions:
            return False
        if action.name is ActionName.ACTION7 and not self.statistics.supported_undo:
            return False
        return not self.ineffective.suppressed(context.state.signature, action)

    def _utility(
        self,
        option: ProbeOption,
        context: ProbeContext,
        alternatives: tuple[ModelAlternative, ...],
    ) -> tuple[float, float, int]:
        information = discrimination_information(option.action, alternatives)
        repetitions = self.ineffective.count(context.state.signature, option.action)
        budget_cost = context.pressure * (1.0 - option.progress) * (1.0 - option.reversibility)
        utility = (
            self.weights.information * information
            + self.weights.progress * option.progress
            + self.weights.reversibility * option.reversibility
            + self.weights.novelty * option.novelty
            - self.weights.failure_risk * option.failure_risk
            - self.weights.repetition * repetitions
            - self.weights.budget_pressure * budget_cost
        )
        return utility, information, repetitions

    def select(
        self,
        options: tuple[ProbeOption, ...],
        *,
        context: ProbeContext,
        alternatives: tuple[ModelAlternative, ...] = (),
    ) -> RankedProbe:
        """Select one legal probe, switching to a progress/risk fallback near budget."""

        if context.state.game_state is GameStateName.GAME_OVER:
            reset = next(
                (option for option in options if option.action.name is ActionName.RESET),
                ProbeOption(ActionRequest(ActionName.RESET), reversibility=1.0),
            )
            utility, information, repetitions = self._utility(reset, context, alternatives)
            return RankedProbe(reset.action, utility, information, repetitions, True)

        eligible = tuple(option for option in options if self._eligible(option, context))
        if not eligible:
            # Suppression is advisory: retain a deterministic least-repeated escape hatch.
            eligible = tuple(
                option
                for option in options
                if (
                    option.action.name is ActionName.RESET
                    or option.action.name in context.state.available_actions
                )
                and not (
                    option.action.name is ActionName.ACTION7 and not self.statistics.supported_undo
                )
            )
        if not eligible:
            raise ValueError("no legal exploration option is available")

        if context.use_fallback:
            selected = max(
                eligible,
                key=lambda option: (
                    option.progress - option.failure_risk,
                    option.reversibility,
                    -self.ineffective.count(context.state.signature, option.action),
                    option.action.name.value,
                    repr(option.action.coordinate),
                ),
            )
            utility, information, repetitions = self._utility(selected, context, alternatives)
            return RankedProbe(selected.action, utility, information, repetitions, True)

        ranked = tuple(
            (self._utility(option, context, alternatives), option) for option in eligible
        )
        (utility, information, repetitions), selected = max(
            ranked,
            key=lambda item: (
                item[0][0],
                item[0][1],
                item[1].progress,
                item[1].action.name.value,
                repr(item[1].action.coordinate),
            ),
        )
        return RankedProbe(selected.action, utility, information, repetitions, False)


__all__ = [
    "ExplorationPlanner",
    "IneffectiveActionMemory",
    "RankedProbe",
    "discrimination_information",
]
