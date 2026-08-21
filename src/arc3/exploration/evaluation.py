"""Synthetic action-semantics identification and baseline comparison helpers."""

from __future__ import annotations

import hashlib
import random
import statistics
from dataclasses import dataclass
from enum import StrEnum

from arc3.types import ActionName, ActionRequest

from .models import EffectKind, ModelAlternative, ModelPrediction
from .policy import discrimination_information


class MechanismStatus(StrEnum):
    """Bounded Stage 07 mechanism result."""

    OBSERVED = "MECHANISM_OBSERVED"
    NOT_OBSERVED = "MECHANISM_NOT_OBSERVED"


@dataclass(frozen=True, slots=True)
class SemanticIdentificationCase:
    """Evaluator-owned hidden alternative for one generic synthetic task."""

    case_id: str
    alternatives: tuple[ModelAlternative, ...]
    actual_index: int
    available_actions: tuple[ActionRequest, ...]

    def __post_init__(self) -> None:
        if not self.case_id:
            raise ValueError("case_id must not be empty")
        if len(self.alternatives) < 2:
            raise ValueError("identification cases need at least two alternatives")
        if not 0 <= self.actual_index < len(self.alternatives):
            raise ValueError("actual_index is outside alternatives")
        if not self.available_actions:
            raise ValueError("available_actions must not be empty")


@dataclass(frozen=True, slots=True)
class ExplorationComparison:
    """Median actions and bounded conclusion against two pinned baselines."""

    episodes: int
    exploration_actions: tuple[int, ...]
    random_actions: tuple[int, ...]
    cycle_actions: tuple[int, ...]
    exploration_median: float
    random_median: float
    cycle_median: float
    status: MechanismStatus

    @property
    def improvement_over_random(self) -> float:
        return self.random_median - self.exploration_median

    @property
    def improvement_over_cycle(self) -> float:
        return self.cycle_median - self.exploration_median


def held_out_semantic_cases(*, seed: int, count: int) -> tuple[SemanticIdentificationCase, ...]:
    """Generate opaque deterministic alternatives with a hidden discriminating action."""

    if isinstance(seed, bool) or not -(2**63) <= seed < 2**63:
        raise ValueError("seed must be a signed 64-bit integer")
    if isinstance(count, bool) or count <= 0:
        raise ValueError("count must be a positive integer")
    actions = tuple(ActionRequest(action) for action in tuple(ActionName)[1:6])
    cases: list[SemanticIdentificationCase] = []
    for ordinal in range(count):
        material = hashlib.sha256(f"arc3.exploration.v1\0{seed}\0{ordinal}".encode()).digest()
        discriminating = actions[int.from_bytes(material[:2], "big") % len(actions)]
        actual = material[2] % 2
        predictions: list[tuple[ModelPrediction, ModelPrediction]] = []
        for action in actions:
            if action == discriminating:
                predictions.append(
                    (
                        ModelPrediction(action, "translated", EffectKind.MOVEMENT),
                        ModelPrediction(action, "toggled", EffectKind.INTERACTION),
                    )
                )
            else:
                predictions.append(
                    (
                        ModelPrediction(action, "shared-no-op", EffectKind.NO_OP),
                        ModelPrediction(action, "shared-no-op", EffectKind.NO_OP),
                    )
                )
        alternatives = (
            ModelAlternative("candidate-a", tuple(pair[0] for pair in predictions)),
            ModelAlternative("candidate-b", tuple(pair[1] for pair in predictions)),
        )
        cases.append(
            SemanticIdentificationCase(
                case_id=f"held-out-semantic-{ordinal:04d}-{material.hex()[:10]}",
                alternatives=alternatives,
                actual_index=actual,
                available_actions=actions,
            )
        )
    return tuple(cases)


def _identify(case: SemanticIdentificationCase, policy: str, *, seed: int) -> int:
    active = case.alternatives
    actual = case.alternatives[case.actual_index]
    rng = random.Random(seed)
    max_actions = len(case.available_actions) * 8
    for ordinal in range(max_actions):
        if len(active) == 1:
            return ordinal
        if policy == "exploration":
            action = max(
                case.available_actions,
                key=lambda candidate: (
                    discrimination_information(candidate, active),
                    candidate.name.value,
                ),
            )
        elif policy == "random":
            action = rng.choice(case.available_actions)
        elif policy == "cycle":
            action = case.available_actions[ordinal % len(case.available_actions)]
        else:
            raise ValueError("policy must be 'exploration', 'random', or 'cycle'")
        observed = actual.prediction_for(action)
        if observed is None:
            raise AssertionError("actual alternative lacks an available-action prediction")
        active = tuple(
            alternative
            for alternative in active
            if (
                (prediction := alternative.prediction_for(action)) is not None
                and prediction.outcome_label == observed.outcome_label
            )
        )
    return max_actions


def compare_exploration_baselines(
    cases: tuple[SemanticIdentificationCase, ...], *, seed: int
) -> ExplorationComparison:
    """Measure semantic-identification action counts against random and cycle."""

    if not cases:
        raise ValueError("at least one held-out case is required")
    exploration = tuple(_identify(case, "exploration", seed=seed) for case in cases)
    random_counts = tuple(
        _identify(case, "random", seed=seed + ordinal + 1) for ordinal, case in enumerate(cases)
    )
    cycle = tuple(_identify(case, "cycle", seed=seed) for case in cases)
    exploration_median = float(statistics.median(exploration))
    random_median = float(statistics.median(random_counts))
    cycle_median = float(statistics.median(cycle))
    observed = exploration_median < min(random_median, cycle_median)
    return ExplorationComparison(
        episodes=len(cases),
        exploration_actions=exploration,
        random_actions=random_counts,
        cycle_actions=cycle,
        exploration_median=exploration_median,
        random_median=random_median,
        cycle_median=cycle_median,
        status=MechanismStatus.OBSERVED if observed else MechanismStatus.NOT_OBSERVED,
    )


__all__ = [
    "ExplorationComparison",
    "MechanismStatus",
    "SemanticIdentificationCase",
    "compare_exploration_baselines",
    "held_out_semantic_cases",
]
