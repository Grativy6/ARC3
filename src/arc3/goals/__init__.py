"""Typed, falsifiable ARC3 goal acquisition and selection."""

from .acquisition import GoalAcquirer, GoalAcquisitionResult, GoalTransition
from .evaluation import (
    GoalComparison,
    GoalMechanismStatus,
    GoalTrapCase,
    compare_goal_policy_to_novelty,
    held_out_goal_traps,
)
from .models import (
    ActionGoalEstimate,
    EvidenceDirection,
    GoalCandidate,
    GoalEvidence,
    GoalKind,
    GoalRecord,
    GoalRole,
    GoalSelection,
    GoalStatus,
    IntrinsicExplorationUtility,
    ProgressSignal,
    ProgressSignalKind,
    ProgressSnapshot,
)
from .progress import detect_progress_signals, positive_external_progress, progress_snapshot
from .registry import GoalEventType, GoalLifecycleEvent, GoalRegistry
from .report import render_goal_report, structured_goal_report
from .selection import has_strong_external_progress, select_goal_action
from .structure import (
    StructuralChange,
    StructuralGoalFeature,
    compare_structural_goals,
    measure_structural_goals,
)

__all__ = [
    "ActionGoalEstimate",
    "EvidenceDirection",
    "GoalAcquirer",
    "GoalAcquisitionResult",
    "GoalCandidate",
    "GoalComparison",
    "GoalEventType",
    "GoalEvidence",
    "GoalKind",
    "GoalLifecycleEvent",
    "GoalMechanismStatus",
    "GoalRecord",
    "GoalRegistry",
    "GoalRole",
    "GoalSelection",
    "GoalStatus",
    "GoalTransition",
    "GoalTrapCase",
    "IntrinsicExplorationUtility",
    "ProgressSignal",
    "ProgressSignalKind",
    "ProgressSnapshot",
    "StructuralChange",
    "StructuralGoalFeature",
    "compare_goal_policy_to_novelty",
    "compare_structural_goals",
    "detect_progress_signals",
    "has_strong_external_progress",
    "held_out_goal_traps",
    "measure_structural_goals",
    "positive_external_progress",
    "progress_snapshot",
    "render_goal_report",
    "select_goal_action",
    "structured_goal_report",
]
