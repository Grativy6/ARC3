"""Typed goal-acquisition values with explicit evidence and authority boundaries."""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum

from arc3.hypotheses import CandidateGoalStatement, HypothesisScope
from arc3.types import ActionRequest, GameStateName, JSONValue


class GoalKind(StrEnum):
    """Generic goal forms; each remains a falsifiable candidate."""

    EXPLICIT_PROGRESS = "explicit-progress"
    LEVEL_ADVANCE = "level-advance"
    WIN = "win"
    EXIT = "exit"
    MATCHING_SLOT = "matching-slot"
    COMPLETION_PATTERN = "completion-pattern"
    CONTACT = "contact"
    DISCREPANCY_REDUCTION = "discrepancy-reduction"


class GoalRole(StrEnum):
    """Goal roles kept disjoint from intrinsic exploration utility."""

    EXTERNAL_PROGRESS = "external-progress"
    INTERMEDIATE_SUBGOAL = "intermediate-subgoal"
    TERMINAL_HYPOTHESIS = "terminal-hypothesis"


class GoalStatus(StrEnum):
    """Derived lifecycle state for a goal candidate."""

    CANDIDATE = "candidate"
    ACTIVE = "active"
    RETIRED = "retired"


class EvidenceDirection(StrEnum):
    """Whether an immutable receipt supports or contradicts a candidate."""

    SUPPORT = "support"
    CONTRADICTION = "contradiction"


class ProgressSignalKind(StrEnum):
    """Explicit environment metadata transitions, separate from interpretation."""

    SCORE_INCREASE = "score-increase"
    PROGRESS_INCREASE = "progress-increase"
    LEVEL_ADVANCE = "level-advance"
    LEVEL_COMPLETED = "level-completed"
    WIN = "win"
    GAME_OVER = "game-over"


@dataclass(frozen=True, slots=True)
class GoalEvidence:
    """Immutable source-linked evidence used by the goal registry."""

    evidence_id: str
    direction: EvidenceDirection
    source_event_ids: tuple[str, ...]
    observed_step: int
    level_index: int
    summary: str
    rank_impact: int = 1

    def __post_init__(self) -> None:
        if not self.evidence_id.strip():
            raise ValueError("evidence_id must be non-empty")
        sources = tuple(sorted(set(self.source_event_ids)))
        if not sources or any(not item.strip() for item in sources):
            raise ValueError("goal evidence requires non-empty source event IDs")
        if isinstance(self.observed_step, bool) or self.observed_step < 0:
            raise ValueError("observed_step must be a non-negative integer")
        if isinstance(self.level_index, bool) or self.level_index < 0:
            raise ValueError("level_index must be a non-negative integer")
        if not self.summary.strip() or len(self.summary) > 256:
            raise ValueError("evidence summary must contain 1..256 characters")
        if isinstance(self.rank_impact, bool) or self.rank_impact <= 0:
            raise ValueError("rank_impact must be a positive integer")
        object.__setattr__(self, "source_event_ids", sources)

    def to_dict(self) -> dict[str, JSONValue]:
        """Return the complete immutable evidence projection."""

        return {
            "evidence_id": self.evidence_id,
            "direction": self.direction.value,
            "source_event_ids": list(self.source_event_ids),
            "observed_step": self.observed_step,
            "level_index": self.level_index,
            "summary": self.summary,
            "rank_impact": self.rank_impact,
        }


@dataclass(frozen=True, slots=True)
class GoalCandidate:
    """Immutable claim that a structural or external state may be worth pursuing."""

    goal_id: str
    kind: GoalKind
    role: GoalRole
    scope: HypothesisScope
    scope_ref: str
    target_state: str
    source_evidence: tuple[GoalEvidence, ...]
    created_step: int
    initial_rank: int = 1

    def __post_init__(self) -> None:
        if not self.goal_id.strip() or not self.scope_ref.strip() or not self.target_state.strip():
            raise ValueError("goal identity, scope reference, and target state must be non-empty")
        if not self.source_evidence:
            raise ValueError("goal candidates require immutable source evidence")
        if any(e.direction is not EvidenceDirection.SUPPORT for e in self.source_evidence):
            raise ValueError("candidate source evidence must support candidate creation")
        if isinstance(self.created_step, bool) or self.created_step < 0:
            raise ValueError("created_step must be a non-negative integer")
        if isinstance(self.initial_rank, bool):
            raise ValueError("initial_rank must be an integer")
        ids = tuple(item.evidence_id for item in self.source_evidence)
        if len(set(ids)) != len(ids):
            raise ValueError("candidate source evidence IDs must be unique")

    def as_hypothesis_statement(self) -> CandidateGoalStatement:
        """Bridge into the Stage 05 hypothesis vocabulary without promotion."""

        terminal = (self.kind.value,) if self.role is GoalRole.TERMINAL_HYPOTHESIS else ()
        return CandidateGoalStatement(
            objective=self.kind.value,
            target_state=self.target_state,
            progress_indicators=tuple(sorted({e.summary for e in self.source_evidence})),
            terminal_indicators=terminal,
        )

    def to_dict(self) -> dict[str, JSONValue]:
        """Return the complete immutable candidate projection."""

        return {
            "goal_id": self.goal_id,
            "kind": self.kind.value,
            "role": self.role.value,
            "scope": self.scope.value,
            "scope_ref": self.scope_ref,
            "target_state": self.target_state,
            "source_evidence": [evidence.to_dict() for evidence in self.source_evidence],
            "created_step": self.created_step,
            "initial_rank": self.initial_rank,
        }


@dataclass(frozen=True, slots=True)
class GoalRecord:
    """Current replaceable view over an immutable candidate and evidence history."""

    candidate: GoalCandidate
    status: GoalStatus
    evidence: tuple[GoalEvidence, ...]
    rank: int
    support_levels: tuple[int, ...]
    contradiction_count: int = 0
    reopen_count: int = 0

    @property
    def source_event_ids(self) -> tuple[str, ...]:
        return tuple(sorted({source for item in self.evidence for source in item.source_event_ids}))

    @property
    def external_progress_supported(self) -> bool:
        return (
            self.candidate.role is GoalRole.EXTERNAL_PROGRESS
            and self.status is GoalStatus.ACTIVE
            and self.rank >= 3
        )

    def to_dict(self) -> dict[str, JSONValue]:
        """Return the exact revisable view over immutable goal evidence."""

        return {
            "goal_id": self.candidate.goal_id,
            "kind": self.candidate.kind.value,
            "status": self.status.value,
            "rank": self.rank,
            "candidate": self.candidate.to_dict(),
            "evidence": [evidence.to_dict() for evidence in self.evidence],
            "support_levels": list(self.support_levels),
            "contradiction_count": self.contradiction_count,
            "reopen_count": self.reopen_count,
        }


@dataclass(frozen=True, slots=True)
class IntrinsicExplorationUtility:
    """Intrinsic probe value; deliberately not a goal candidate."""

    novelty: float
    information_gain: float
    reversibility: float = 0.0

    def __post_init__(self) -> None:
        for name, value in (
            ("novelty", self.novelty),
            ("information_gain", self.information_gain),
            ("reversibility", self.reversibility),
        ):
            if not math.isfinite(value) or not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be finite and within 0..1")


@dataclass(frozen=True, slots=True)
class ActionGoalEstimate:
    """Pre-action model estimate; desirability and reachability stay separate."""

    action: ActionRequest
    goal_id: str | None
    goal_advance_rank: int
    reachability_rank: int
    exploration: IntrinsicExplorationUtility
    failure_risk_rank: int = 0

    def __post_init__(self) -> None:
        if self.goal_id is not None and not self.goal_id.strip():
            raise ValueError("goal_id must be non-empty when present")
        for name, value in (
            ("goal_advance_rank", self.goal_advance_rank),
            ("reachability_rank", self.reachability_rank),
            ("failure_risk_rank", self.failure_risk_rank),
        ):
            if isinstance(value, bool) or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")


@dataclass(frozen=True, slots=True)
class GoalSelection:
    """Concise goal/action selection receipt, not an action authorization."""

    goal_id: str | None
    action: ActionRequest | None
    desirability_rank: int
    reachability_rank: int
    exploration_utility: float
    novelty_suppressed: bool
    rationale: str


@dataclass(frozen=True, slots=True)
class ProgressSnapshot:
    """Exact progress-bearing observation fields at one step."""

    step: int
    level_index: int
    state: GameStateName
    levels_completed: int
    win_levels: int
    score: float | None
    progress: float | None
    source_event_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        for name, value in (
            ("step", self.step),
            ("level_index", self.level_index),
            ("levels_completed", self.levels_completed),
            ("win_levels", self.win_levels),
        ):
            if isinstance(value, bool) or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")
        for name, numeric_value in (("score", self.score), ("progress", self.progress)):
            if numeric_value is not None and not math.isfinite(numeric_value):
                raise ValueError(f"{name} must be finite when present")
        sources = tuple(sorted(set(self.source_event_ids)))
        if not sources or any(not item.strip() for item in sources):
            raise ValueError("progress snapshots require source event IDs")
        object.__setattr__(self, "source_event_ids", sources)


@dataclass(frozen=True, slots=True)
class ProgressSignal:
    """Measured explicit metadata transition; no structural goal is inferred here."""

    kind: ProgressSignalKind
    before: float | int | str | None
    after: float | int | str | None
    magnitude: float
    terminal: bool
    evidence: GoalEvidence

    def __post_init__(self) -> None:
        if not math.isfinite(self.magnitude) or self.magnitude < 0:
            raise ValueError("progress signal magnitude must be finite and non-negative")


__all__ = [
    "ActionGoalEstimate",
    "EvidenceDirection",
    "GoalCandidate",
    "GoalEvidence",
    "GoalKind",
    "GoalRecord",
    "GoalRole",
    "GoalSelection",
    "GoalStatus",
    "IntrinsicExplorationUtility",
    "ProgressSignal",
    "ProgressSignalKind",
    "ProgressSnapshot",
]
