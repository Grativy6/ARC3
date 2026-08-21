"""Typed values for action-semantics learning and bounded exploration."""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from enum import StrEnum

from arc3.types import ActionName, ActionRequest, Coordinate, GameStateName


class EffectKind(StrEnum):
    """Generic observable action-effect classes, not causal conclusions."""

    NO_OP = "no-op"
    MOVEMENT = "movement"
    SELECTION = "selection"
    INTERACTION = "interaction"
    UNDO = "undo"
    TERMINAL = "terminal"
    METADATA_ONLY = "metadata-only"


@dataclass(frozen=True, slots=True)
class StateFeatures:
    """Generic, observation-derived conditioning features for action evidence."""

    width: int
    height: int
    palette_size: int
    component_count: int
    changed_cell_count: int
    game_state: GameStateName
    available_actions: tuple[ActionName, ...]
    condition_tokens: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name, value in (
            ("width", self.width),
            ("height", self.height),
            ("palette_size", self.palette_size),
            ("component_count", self.component_count),
            ("changed_cell_count", self.changed_cell_count),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")
        if len(set(self.available_actions)) != len(self.available_actions):
            raise ValueError("available_actions must not contain duplicates")
        if any(not token for token in self.condition_tokens):
            raise ValueError("condition tokens must be non-empty")
        object.__setattr__(self, "available_actions", tuple(sorted(self.available_actions)))
        object.__setattr__(self, "condition_tokens", tuple(sorted(set(self.condition_tokens))))

    @property
    def signature(self) -> str:
        """Return a stable, game-identity-free conditioning key."""

        material = repr(
            (
                self.width,
                self.height,
                self.palette_size,
                self.component_count,
                self.changed_cell_count,
                self.game_state.value,
                tuple(action.value for action in self.available_actions),
                self.condition_tokens,
            )
        ).encode()
        return f"state:{hashlib.sha256(material).hexdigest()}"


@dataclass(frozen=True, slots=True)
class EffectClassification:
    """Measured effect labels with optional observed translation."""

    kinds: frozenset[EffectKind]
    displacement: tuple[int, int] | None = None
    changed_cells: int = 0
    metadata_fields: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.kinds:
            raise ValueError("an effect classification needs at least one kind")
        if isinstance(self.changed_cells, bool) or self.changed_cells < 0:
            raise ValueError("changed_cells must be a non-negative integer")
        if self.displacement is not None and self.displacement == (0, 0):
            raise ValueError("movement displacement must be non-zero")
        object.__setattr__(self, "metadata_fields", tuple(sorted(set(self.metadata_fields))))

    @property
    def primary(self) -> EffectKind:
        """Return the most consequential label under a stable precedence."""

        precedence = (
            EffectKind.TERMINAL,
            EffectKind.UNDO,
            EffectKind.SELECTION,
            EffectKind.MOVEMENT,
            EffectKind.INTERACTION,
            EffectKind.METADATA_ONLY,
            EffectKind.NO_OP,
        )
        return next(kind for kind in precedence if kind in self.kinds)


@dataclass(frozen=True, slots=True)
class ModelPrediction:
    """One model's concise predicted outcome for a candidate action."""

    action: ActionRequest
    outcome_label: str
    effect: EffectKind

    def __post_init__(self) -> None:
        if not self.outcome_label.strip():
            raise ValueError("outcome_label must not be empty")


@dataclass(frozen=True, slots=True)
class ModelAlternative:
    """An active alternative used only for pre-action discrimination."""

    identifier: str
    predictions: tuple[ModelPrediction, ...]
    weight: float = 1.0

    def __post_init__(self) -> None:
        if not self.identifier.strip():
            raise ValueError("alternative identifier must not be empty")
        if not math.isfinite(self.weight) or self.weight <= 0:
            raise ValueError("alternative weight must be finite and positive")
        actions = tuple(prediction.action for prediction in self.predictions)
        if len(set(actions)) != len(actions):
            raise ValueError("an alternative may predict each action at most once")

    def prediction_for(self, action: ActionRequest) -> ModelPrediction | None:
        return next(
            (prediction for prediction in self.predictions if prediction.action == action),
            None,
        )


class CoordinateSource(StrEnum):
    """Observation-derived origins for bounded ACTION6 candidates."""

    COMPONENT_CENTER = "component-center"
    CHANGED_CELL = "changed-cell"
    EMPTY_SLOT = "empty-slot"
    BOUNDARY = "boundary"
    DISAGREEMENT = "disagreement"
    COARSE_UNEXPLORED = "coarse-unexplored"


@dataclass(frozen=True, slots=True)
class CoordinateCandidate:
    """A deduplicated coordinate with every supporting source retained."""

    coordinate: Coordinate
    sources: tuple[CoordinateSource, ...]

    def __post_init__(self) -> None:
        if not self.sources:
            raise ValueError("coordinate candidate needs at least one source")
        object.__setattr__(self, "sources", tuple(dict.fromkeys(self.sources)))


@dataclass(frozen=True, slots=True)
class ProbeOption:
    """Bounded utility inputs for one available action."""

    action: ActionRequest
    progress: float = 0.0
    reversibility: float = 0.0
    novelty: float = 0.0
    failure_risk: float = 0.0

    def __post_init__(self) -> None:
        for name, value in (
            ("progress", self.progress),
            ("reversibility", self.reversibility),
            ("novelty", self.novelty),
            ("failure_risk", self.failure_risk),
        ):
            if not math.isfinite(value) or not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be finite and within 0..1")


@dataclass(frozen=True, slots=True)
class ProbeUtilityWeights:
    """Configurable coefficients for information-efficient action choice."""

    information: float = 2.0
    progress: float = 1.25
    reversibility: float = 0.5
    novelty: float = 0.5
    failure_risk: float = 2.0
    repetition: float = 1.5
    budget_pressure: float = 1.0

    def __post_init__(self) -> None:
        if any(
            not math.isfinite(value) or value < 0
            for value in (
                self.information,
                self.progress,
                self.reversibility,
                self.novelty,
                self.failure_risk,
                self.repetition,
                self.budget_pressure,
            )
        ):
            raise ValueError("probe utility weights must be finite and non-negative")


@dataclass(frozen=True, slots=True)
class ProbeContext:
    """Action-budget and state context used by probe selection."""

    state: StateFeatures
    actions_used: int
    action_budget: int
    fallback_reserve: int = 2

    def __post_init__(self) -> None:
        if isinstance(self.actions_used, bool) or self.actions_used < 0:
            raise ValueError("actions_used must be a non-negative integer")
        if isinstance(self.action_budget, bool) or self.action_budget <= 0:
            raise ValueError("action_budget must be a positive integer")
        if self.actions_used > self.action_budget:
            raise ValueError("actions_used must not exceed action_budget")
        if isinstance(self.fallback_reserve, bool) or self.fallback_reserve < 0:
            raise ValueError("fallback_reserve must be non-negative")

    @property
    def remaining(self) -> int:
        return self.action_budget - self.actions_used

    @property
    def pressure(self) -> float:
        return self.actions_used / self.action_budget

    @property
    def use_fallback(self) -> bool:
        return self.remaining <= self.fallback_reserve


__all__ = [
    "CoordinateCandidate",
    "CoordinateSource",
    "EffectClassification",
    "EffectKind",
    "ModelAlternative",
    "ModelPrediction",
    "ProbeContext",
    "ProbeOption",
    "ProbeUtilityWeights",
    "StateFeatures",
]
