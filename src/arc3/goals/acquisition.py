"""Goal acquisition from explicit metadata and generic structural transitions."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from arc3.adapters import Observation
from arc3.hypotheses import HypothesisScope

from .models import (
    EvidenceDirection,
    GoalCandidate,
    GoalEvidence,
    GoalKind,
    GoalRecord,
    GoalRole,
    ProgressSignal,
    ProgressSignalKind,
)
from .progress import detect_progress_signals, positive_external_progress, progress_snapshot
from .registry import GoalRegistry
from .structure import (
    StructuralChange,
    StructuralGoalFeature,
    compare_structural_goals,
    measure_structural_goals,
)


@dataclass(frozen=True, slots=True)
class GoalTransition:
    """Two observations plus immutable event sources and explicit scope references."""

    before: Observation
    after: Observation
    before_event_ids: tuple[str, ...]
    after_event_ids: tuple[str, ...]
    step: int
    level_scope_ref: str
    game_scope_ref: str

    def __post_init__(self) -> None:
        if not self.before.frames or not self.after.frames:
            raise ValueError("goal transitions require before and after frames")
        if isinstance(self.step, bool) or self.step < 0:
            raise ValueError("step must be a non-negative integer")
        if not self.before_event_ids or not self.after_event_ids:
            raise ValueError("goal transitions require before and after event IDs")
        if not self.level_scope_ref.strip() or not self.game_scope_ref.strip():
            raise ValueError("goal transition scope references must be non-empty")


@dataclass(frozen=True, slots=True)
class GoalAcquisitionResult:
    """Derived outputs from one transition; raw observations remain untouched."""

    progress_signals: tuple[ProgressSignal, ...]
    structural_changes: tuple[StructuralChange, ...]
    touched_goal_ids: tuple[str, ...]
    active_records: tuple[GoalRecord, ...]


def _stable_id(prefix: str, *parts: str) -> str:
    material = "\0".join((prefix, *parts)).encode()
    return f"{prefix}:{hashlib.sha256(material).hexdigest()}"


def _candidate_id(scope_ref: str, kind: GoalKind, target_state: str) -> str:
    return _stable_id("goal", scope_ref, kind.value, target_state)


def _structural_role(kind: GoalKind) -> GoalRole:
    if kind in {GoalKind.EXIT, GoalKind.COMPLETION_PATTERN}:
        return GoalRole.TERMINAL_HYPOTHESIS
    return GoalRole.INTERMEDIATE_SUBGOAL


class GoalAcquirer:
    """Accumulate falsifiable goal candidates without treating novelty as a goal."""

    def __init__(self, registry: GoalRegistry | None = None) -> None:
        self.registry = registry or GoalRegistry()

    def _structural_evidence(
        self,
        feature: StructuralGoalFeature,
        transition: GoalTransition,
    ) -> GoalEvidence:
        sources = tuple(sorted(set(transition.after_event_ids)))
        return GoalEvidence(
            evidence_id=_stable_id(
                "gev",
                "structural-proposal",
                feature.kind.value,
                feature.target_state,
                *sources,
            ),
            direction=EvidenceDirection.SUPPORT,
            source_event_ids=sources,
            observed_step=transition.step,
            level_index=transition.after.levels_completed,
            summary=f"structural proposal: {feature.measurement}",
            rank_impact=1,
        )

    def _register_structural(
        self,
        feature: StructuralGoalFeature,
        transition: GoalTransition,
    ) -> GoalRecord:
        evidence = self._structural_evidence(feature, transition)
        return self.registry.register(
            GoalCandidate(
                goal_id=_candidate_id(
                    transition.level_scope_ref,
                    feature.kind,
                    feature.target_state,
                ),
                kind=feature.kind,
                role=_structural_role(feature.kind),
                scope=HypothesisScope.LEVEL,
                scope_ref=transition.level_scope_ref,
                target_state=feature.target_state,
                source_evidence=(evidence,),
                created_step=transition.step,
            )
        )

    def _register_explicit(
        self, signal: ProgressSignal, transition: GoalTransition
    ) -> GoalRecord | None:
        if signal.evidence.direction is EvidenceDirection.CONTRADICTION:
            return None
        if signal.kind in {
            ProgressSignalKind.SCORE_INCREASE,
            ProgressSignalKind.PROGRESS_INCREASE,
        }:
            kind = GoalKind.EXPLICIT_PROGRESS
            role = GoalRole.EXTERNAL_PROGRESS
            target = f"continue-{signal.kind.value}"
            scope = HypothesisScope.LEVEL
            scope_ref = transition.level_scope_ref
        elif signal.kind in {
            ProgressSignalKind.LEVEL_ADVANCE,
            ProgressSignalKind.LEVEL_COMPLETED,
        }:
            kind = GoalKind.LEVEL_ADVANCE
            role = GoalRole.TERMINAL_HYPOTHESIS
            target = "advance-level"
            scope = HypothesisScope.GAME
            scope_ref = transition.game_scope_ref
        elif signal.kind is ProgressSignalKind.WIN:
            kind = GoalKind.WIN
            role = GoalRole.TERMINAL_HYPOTHESIS
            target = "reach-win-state"
            scope = HypothesisScope.GAME
            scope_ref = transition.game_scope_ref
        else:
            return None
        return self.registry.register(
            GoalCandidate(
                goal_id=_candidate_id(scope_ref, kind, target),
                kind=kind,
                role=role,
                scope=scope,
                scope_ref=scope_ref,
                target_state=target,
                source_evidence=(signal.evidence,),
                created_step=transition.step,
                initial_rank=signal.evidence.rank_impact,
            )
        )

    def _correlated_evidence(
        self,
        feature: StructuralGoalFeature,
        transition: GoalTransition,
        signals: tuple[ProgressSignal, ...],
    ) -> GoalEvidence:
        sources = tuple(
            sorted(
                {
                    source
                    for signal in signals
                    if signal.evidence.direction is EvidenceDirection.SUPPORT
                    for source in signal.evidence.source_event_ids
                }
                | set(transition.before_event_ids)
                | set(transition.after_event_ids)
            )
        )
        labels = ",".join(
            signal.kind.value
            for signal in signals
            if signal.evidence.direction is EvidenceDirection.SUPPORT
        )
        return GoalEvidence(
            evidence_id=_stable_id(
                "gev", "progress-correlation", feature.kind.value, feature.target_state, *sources
            ),
            direction=EvidenceDirection.SUPPORT,
            source_event_ids=sources,
            observed_step=transition.step,
            level_index=transition.after.levels_completed,
            summary=f"structural improvement coincided with explicit progress: {labels}",
            rank_impact=3,
        )

    def _cross_level_candidate(
        self,
        record: GoalRecord,
        transition: GoalTransition,
    ) -> GoalRecord | None:
        related = self.registry.matching(
            record.candidate.kind,
            record.candidate.target_state,
        )
        level_records = tuple(
            item
            for item in related
            if item.candidate.scope is HypothesisScope.LEVEL and item.status.value == "active"
        )
        levels = {item.candidate.scope_ref for item in level_records}
        if len(levels) < 2:
            return None
        sources = tuple(
            sorted({source for item in level_records for source in item.source_event_ids})
        )
        evidence = GoalEvidence(
            evidence_id=_stable_id(
                "gev",
                "cross-level",
                record.candidate.kind.value,
                record.candidate.target_state,
                *sources,
            ),
            direction=EvidenceDirection.SUPPORT,
            source_event_ids=sources,
            observed_step=transition.step,
            level_index=transition.after.levels_completed,
            summary=f"same structural progress relation observed across {len(levels)} levels",
            rank_impact=len(levels),
        )
        return self.registry.register(
            GoalCandidate(
                goal_id=_candidate_id(
                    transition.game_scope_ref,
                    record.candidate.kind,
                    record.candidate.target_state,
                ),
                kind=record.candidate.kind,
                role=record.candidate.role,
                scope=HypothesisScope.GAME,
                scope_ref=transition.game_scope_ref,
                target_state=record.candidate.target_state,
                source_evidence=(evidence,),
                created_step=transition.step,
                initial_rank=evidence.rank_impact,
            )
        )

    def observe_transition(self, transition: GoalTransition) -> GoalAcquisitionResult:
        """Compare a transition with prior structure and update derived candidates."""

        before_snapshot = progress_snapshot(
            transition.before,
            step=max(0, transition.step - 1),
            source_event_ids=transition.before_event_ids,
        )
        after_snapshot = progress_snapshot(
            transition.after,
            step=transition.step,
            source_event_ids=transition.after_event_ids,
        )
        signals = detect_progress_signals(before_snapshot, after_snapshot)
        before_features = measure_structural_goals(transition.before.frames[-1])
        after_features = measure_structural_goals(transition.after.frames[-1])
        changes = compare_structural_goals(before_features, after_features)
        touched: set[str] = set()

        for signal in signals:
            record = self._register_explicit(signal, transition)
            if record is not None:
                touched.add(record.candidate.goal_id)

        structural_records: dict[tuple[GoalKind, str], GoalRecord] = {}
        for feature in after_features:
            record = self._register_structural(feature, transition)
            structural_records[(feature.kind, feature.target_state)] = record
            touched.add(record.candidate.goal_id)

        if positive_external_progress(signals):
            for change in changes:
                if not change.improved:
                    continue
                key = (change.after.kind, change.after.target_state)
                record = structural_records.get(key)
                if record is None:
                    record = self._register_structural(change.after, transition)
                evidence = self._correlated_evidence(change.after, transition, signals)
                record = self.registry.support(record.candidate.goal_id, evidence)
                touched.add(record.candidate.goal_id)
                promoted = self._cross_level_candidate(record, transition)
                if promoted is not None:
                    touched.add(promoted.candidate.goal_id)

        return GoalAcquisitionResult(
            progress_signals=signals,
            structural_changes=changes,
            touched_goal_ids=tuple(sorted(touched)),
            active_records=self.registry.records(include_retired=False),
        )

    def record_goal_test(
        self,
        goal_id: str,
        transition: GoalTransition,
        *,
        target_condition_reached: bool,
    ) -> GoalRecord:
        """Support or contradict a tested goal without rewriting the prior candidate."""

        before = progress_snapshot(
            transition.before,
            step=max(0, transition.step - 1),
            source_event_ids=transition.before_event_ids,
        )
        after = progress_snapshot(
            transition.after,
            step=transition.step,
            source_event_ids=transition.after_event_ids,
        )
        signals = detect_progress_signals(before, after)
        sources = tuple(sorted(set(transition.before_event_ids + transition.after_event_ids)))
        if target_condition_reached and positive_external_progress(signals):
            evidence = GoalEvidence(
                evidence_id=_stable_id("gev", "goal-test-support", goal_id, *sources),
                direction=EvidenceDirection.SUPPORT,
                source_event_ids=sources,
                observed_step=transition.step,
                level_index=after.level_index,
                summary="tested target condition coincided with explicit progress",
                rank_impact=3,
            )
            return self.registry.support(goal_id, evidence)
        evidence = GoalEvidence(
            evidence_id=_stable_id("gev", "goal-test-contradiction", goal_id, *sources),
            direction=EvidenceDirection.CONTRADICTION,
            source_event_ids=sources,
            observed_step=transition.step,
            level_index=after.level_index,
            summary=(
                "tested target condition produced no explicit progress"
                if target_condition_reached
                else "tested transition moved away from the target condition"
            ),
            rank_impact=2,
        )
        return self.registry.contradict(goal_id, evidence)


__all__ = ["GoalAcquirer", "GoalAcquisitionResult", "GoalTransition"]
