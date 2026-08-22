"""Policy interfaces and deterministic baseline implementations."""

from __future__ import annotations

from typing import Protocol

from arc3.adapters import Observation
from arc3.types import ActionRequest


class Policy(Protocol):
    """Minimal policy boundary: select one action from one observation."""

    def select(self, observation: Observation) -> ActionRequest:
        """Return one normalized action without touching the environment."""


from arc3.policy.baselines import (  # noqa: E402
    ActionCyclePolicy,
    CoordinateSweepPolicy,
    RandomValidPolicy,
    make_baseline,
)
from arc3.policy.cadence import (  # noqa: E402
    DEEP_TRIGGER_PRIORITY,
    BoundedCanonicalLRU,
    CacheInvalidationReason,
    CacheValueKind,
    CadenceConfig,
    CadenceSelection,
    CadenceSignals,
    CadenceState,
    CanonicalCacheKey,
    DeepTrigger,
    DeliberationMode,
    DeliberationStatus,
    DerivedCacheValue,
    ModelCacheIdentity,
    ReasoningPath,
    select_reasoning_path,
)
from arc3.policy.controller import ARC3Controller  # noqa: E402
from arc3.policy.models import (  # noqa: E402
    ActionDecision,
    CandidateAction,
    ConsequenceReceipt,
    ControllerCheckpoint,
    ControllerPhase,
    ControllerPreset,
    ControllerSnapshot,
    ObservationReceipt,
    PresetFeatures,
    RunContext,
    preset_features,
)
from arc3.policy.proposal import (  # noqa: E402
    LocalProposal,
    LocalProposalProvider,
    ProposalContext,
)

__all__ = [
    "DEEP_TRIGGER_PRIORITY",
    "ARC3Controller",
    "ActionCyclePolicy",
    "ActionDecision",
    "BoundedCanonicalLRU",
    "CacheInvalidationReason",
    "CacheValueKind",
    "CadenceConfig",
    "CadenceSelection",
    "CadenceSignals",
    "CadenceState",
    "CandidateAction",
    "CanonicalCacheKey",
    "ConsequenceReceipt",
    "ControllerCheckpoint",
    "ControllerPhase",
    "ControllerPreset",
    "ControllerSnapshot",
    "CoordinateSweepPolicy",
    "DeepTrigger",
    "DeliberationMode",
    "DeliberationStatus",
    "DerivedCacheValue",
    "LocalProposal",
    "LocalProposalProvider",
    "ModelCacheIdentity",
    "ObservationReceipt",
    "Policy",
    "PresetFeatures",
    "ProposalContext",
    "RandomValidPolicy",
    "ReasoningPath",
    "RunContext",
    "make_baseline",
    "preset_features",
    "select_reasoning_path",
]
