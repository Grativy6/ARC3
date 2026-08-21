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
    "ARC3Controller",
    "ActionCyclePolicy",
    "ActionDecision",
    "CandidateAction",
    "ConsequenceReceipt",
    "ControllerCheckpoint",
    "ControllerPhase",
    "ControllerPreset",
    "ControllerSnapshot",
    "CoordinateSweepPolicy",
    "LocalProposal",
    "LocalProposalProvider",
    "ObservationReceipt",
    "Policy",
    "PresetFeatures",
    "ProposalContext",
    "RandomValidPolicy",
    "RunContext",
    "make_baseline",
    "preset_features",
]
