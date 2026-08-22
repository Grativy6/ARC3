"""Action semantics and information-efficient generic exploration."""

from .action_registry import (
    ActionEffectCandidate,
    ActionEffectObservation,
    ActionEffectRegistry,
    ActionEffectStatus,
    CanonicalActionEffect,
    CanonicalEffectKind,
    CoordinateRelation,
    action_condition_signature,
    derive_action_effect_observation,
)
from .coordinates import generate_coordinate_candidates
from .effects import classify_effect, movement_displacements, state_features
from .evaluation import (
    ExplorationComparison,
    MechanismStatus,
    SemanticIdentificationCase,
    compare_exploration_baselines,
    held_out_semantic_cases,
)
from .models import (
    CoordinateCandidate,
    CoordinateSource,
    EffectClassification,
    EffectKind,
    ModelAlternative,
    ModelPrediction,
    ProbeContext,
    ProbeOption,
    ProbeUtilityWeights,
    StateFeatures,
)
from .policy import (
    ExplorationPlanner,
    IneffectiveActionMemory,
    RankedProbe,
    discrimination_information,
)
from .statistics import ActionEffectStatistics, EffectEstimate

__all__ = [
    "ActionEffectCandidate",
    "ActionEffectObservation",
    "ActionEffectRegistry",
    "ActionEffectStatistics",
    "ActionEffectStatus",
    "CanonicalActionEffect",
    "CanonicalEffectKind",
    "CoordinateCandidate",
    "CoordinateRelation",
    "CoordinateSource",
    "EffectClassification",
    "EffectEstimate",
    "EffectKind",
    "ExplorationComparison",
    "ExplorationPlanner",
    "IneffectiveActionMemory",
    "MechanismStatus",
    "ModelAlternative",
    "ModelPrediction",
    "ProbeContext",
    "ProbeOption",
    "ProbeUtilityWeights",
    "RankedProbe",
    "SemanticIdentificationCase",
    "StateFeatures",
    "action_condition_signature",
    "classify_effect",
    "compare_exploration_baselines",
    "derive_action_effect_observation",
    "discrimination_information",
    "generate_coordinate_candidates",
    "held_out_semantic_cases",
    "movement_displacements",
    "state_features",
]
