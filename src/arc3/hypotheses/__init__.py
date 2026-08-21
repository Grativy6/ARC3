"""Typed, event-sourced, falsification-aware hypothesis APIs."""

from .actions import (
    ActionSemanticsStatement,
    CoordinateActionTargetStatement,
    InteractionToggleStatement,
)
from .base import (
    Compatibility,
    EvidenceKind,
    EvidenceReceipt,
    HypothesisFamily,
    HypothesisPrediction,
    HypothesisScope,
)
from .events import HYPOTHESIS_EVENT_SCHEMA, HypothesisEvent, HypothesisEventType
from .families import HypothesisStatement, statement_from_dict
from .goals import CandidateGoalStatement
from .objects import CollisionTraversabilityStatement, ControllableObjectStatement
from .registry import (
    HypothesisRecord,
    HypothesisRegistry,
    PlanInvalidationSignal,
    ScopeRevision,
)
from .report import render_hypothesis_report, structured_hypothesis_report
from .transitions import (
    LevelInvariantStatement,
    ProgressTerminalStatement,
    StateTransitionStatement,
)

__all__ = [
    "HYPOTHESIS_EVENT_SCHEMA",
    "ActionSemanticsStatement",
    "CandidateGoalStatement",
    "CollisionTraversabilityStatement",
    "Compatibility",
    "ControllableObjectStatement",
    "CoordinateActionTargetStatement",
    "EvidenceKind",
    "EvidenceReceipt",
    "HypothesisEvent",
    "HypothesisEventType",
    "HypothesisFamily",
    "HypothesisPrediction",
    "HypothesisRecord",
    "HypothesisRegistry",
    "HypothesisScope",
    "HypothesisStatement",
    "InteractionToggleStatement",
    "LevelInvariantStatement",
    "PlanInvalidationSignal",
    "ProgressTerminalStatement",
    "ScopeRevision",
    "StateTransitionStatement",
    "render_hypothesis_report",
    "statement_from_dict",
    "structured_hypothesis_report",
]
