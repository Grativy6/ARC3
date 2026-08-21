"""Event-preserving goal lifecycle with retirement and explicit reopening."""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum

from arc3.types import JSONValue

from .models import (
    EvidenceDirection,
    GoalCandidate,
    GoalEvidence,
    GoalKind,
    GoalRecord,
    GoalStatus,
)


class GoalEventType(StrEnum):
    """Trace-compatible lifecycle transitions for goal candidates."""

    CREATED = "goal.candidate_created"
    SUPPORTED = "goal.supported"
    CONTRADICTED = "goal.contradicted"
    SELECTED = "goal.selected_for_planning"
    REOPENED = "goal.reopened"
    RETIRED = "goal.retired"


@dataclass(frozen=True, slots=True)
class GoalLifecycleEvent:
    """One immutable lifecycle fact suitable for a trace payload."""

    event_id: str
    sequence: int
    event_type: GoalEventType
    goal_id: str
    source_event_ids: tuple[str, ...]
    previous_status: GoalStatus | None
    new_status: GoalStatus
    rank_after: int
    summary: str

    def to_trace_payload(self) -> dict[str, JSONValue]:
        return {
            "goal_id": self.goal_id,
            "goal_event_id": self.event_id,
            "sequence": self.sequence,
            "source_event_ids": list(self.source_event_ids),
            "previous_status": self.previous_status.value if self.previous_status else None,
            "new_status": self.new_status.value,
            "rank_after": self.rank_after,
            "weight_kind": "uncalibrated_rank",
            "summary": self.summary,
        }


class GoalRegistry:
    """Derived registry retaining every candidate, contradiction, and reopening event."""

    def __init__(self, *, retirement_threshold: int = 2) -> None:
        if isinstance(retirement_threshold, bool) or retirement_threshold <= 0:
            raise ValueError("retirement_threshold must be a positive integer")
        self._retirement_threshold = retirement_threshold
        self._records: dict[str, GoalRecord] = {}
        self._events: list[GoalLifecycleEvent] = []

    @property
    def events(self) -> tuple[GoalLifecycleEvent, ...]:
        return tuple(self._events)

    def records(self, *, include_retired: bool = True) -> tuple[GoalRecord, ...]:
        records = tuple(self._records.values())
        if not include_retired:
            records = tuple(record for record in records if record.status is not GoalStatus.RETIRED)
        return tuple(sorted(records, key=lambda record: record.candidate.goal_id))

    def get(self, goal_id: str) -> GoalRecord:
        try:
            return self._records[goal_id]
        except KeyError as error:
            raise KeyError(f"unknown goal candidate: {goal_id}") from error

    def matching(self, kind: GoalKind, target_state: str) -> tuple[GoalRecord, ...]:
        return tuple(
            record
            for record in self.records()
            if record.candidate.kind is kind and record.candidate.target_state == target_state
        )

    def _append(
        self,
        event_type: GoalEventType,
        record: GoalRecord,
        *,
        source_event_ids: tuple[str, ...],
        previous_status: GoalStatus | None,
        summary: str,
    ) -> None:
        sequence = len(self._events)
        self._events.append(
            GoalLifecycleEvent(
                event_id=f"goal-event-{sequence:08d}",
                sequence=sequence,
                event_type=event_type,
                goal_id=record.candidate.goal_id,
                source_event_ids=tuple(sorted(set(source_event_ids))),
                previous_status=previous_status,
                new_status=record.status,
                rank_after=record.rank,
                summary=summary,
            )
        )

    def register(self, candidate: GoalCandidate) -> GoalRecord:
        """Register once; later observations become support instead of rewriting creation."""

        existing = self._records.get(candidate.goal_id)
        if existing is not None:
            if (
                existing.candidate.kind is not candidate.kind
                or existing.candidate.target_state != candidate.target_state
                or existing.candidate.scope_ref != candidate.scope_ref
            ):
                raise ValueError("goal ID collision with a different candidate")
            record = existing
            for evidence in candidate.source_evidence:
                if evidence.evidence_id not in {item.evidence_id for item in record.evidence}:
                    record = self.support(candidate.goal_id, evidence)
            return record
        support_levels = tuple(sorted({item.level_index for item in candidate.source_evidence}))
        record = GoalRecord(
            candidate=candidate,
            status=GoalStatus.CANDIDATE,
            evidence=candidate.source_evidence,
            rank=candidate.initial_rank,
            support_levels=support_levels,
        )
        self._records[candidate.goal_id] = record
        self._append(
            GoalEventType.CREATED,
            record,
            source_event_ids=record.source_event_ids,
            previous_status=None,
            summary="candidate created from source-linked evidence",
        )
        return record

    def _new_evidence(self, record: GoalRecord, evidence: GoalEvidence) -> bool:
        return evidence.evidence_id not in {item.evidence_id for item in record.evidence}

    def support(self, goal_id: str, evidence: GoalEvidence) -> GoalRecord:
        if evidence.direction is not EvidenceDirection.SUPPORT:
            raise ValueError("support requires supporting evidence")
        record = self.get(goal_id)
        if not self._new_evidence(record, evidence):
            return record
        if record.status is GoalStatus.RETIRED:
            return self.reopen(goal_id, evidence)
        updated = replace(
            record,
            status=GoalStatus.ACTIVE,
            evidence=(*record.evidence, evidence),
            rank=record.rank + evidence.rank_impact,
            support_levels=tuple(sorted(set((*record.support_levels, evidence.level_index)))),
        )
        self._records[goal_id] = updated
        self._append(
            GoalEventType.SUPPORTED,
            updated,
            source_event_ids=evidence.source_event_ids,
            previous_status=record.status,
            summary=evidence.summary,
        )
        return updated

    def contradict(self, goal_id: str, evidence: GoalEvidence) -> GoalRecord:
        if evidence.direction is not EvidenceDirection.CONTRADICTION:
            raise ValueError("contradiction requires contradicting evidence")
        record = self.get(goal_id)
        if not self._new_evidence(record, evidence):
            return record
        count = record.contradiction_count + 1
        status = GoalStatus.RETIRED if count >= self._retirement_threshold else GoalStatus.CANDIDATE
        updated = replace(
            record,
            status=status,
            evidence=(*record.evidence, evidence),
            rank=max(0, record.rank - evidence.rank_impact),
            contradiction_count=count,
        )
        self._records[goal_id] = updated
        event_type = (
            GoalEventType.RETIRED if status is GoalStatus.RETIRED else GoalEventType.CONTRADICTED
        )
        self._append(
            event_type,
            updated,
            source_event_ids=evidence.source_event_ids,
            previous_status=record.status,
            summary=evidence.summary,
        )
        return updated

    def reopen(self, goal_id: str, evidence: GoalEvidence) -> GoalRecord:
        if evidence.direction is not EvidenceDirection.SUPPORT:
            raise ValueError("reopening requires new supporting evidence")
        record = self.get(goal_id)
        if record.status is not GoalStatus.RETIRED:
            return self.support(goal_id, evidence)
        if not self._new_evidence(record, evidence):
            return record
        updated = replace(
            record,
            status=GoalStatus.ACTIVE,
            evidence=(*record.evidence, evidence),
            rank=record.rank + evidence.rank_impact,
            support_levels=tuple(sorted(set((*record.support_levels, evidence.level_index)))),
            reopen_count=record.reopen_count + 1,
        )
        self._records[goal_id] = updated
        self._append(
            GoalEventType.REOPENED,
            updated,
            source_event_ids=evidence.source_event_ids,
            previous_status=record.status,
            summary=evidence.summary,
        )
        return updated

    def retire(
        self,
        goal_id: str,
        *,
        source_event_ids: tuple[str, ...],
        summary: str,
    ) -> GoalRecord:
        """Close a bounded goal scope without manufacturing contradictory evidence."""

        sources = tuple(sorted(set(source_event_ids)))
        if not sources or any(not item.strip() for item in sources):
            raise ValueError("goal retirement requires source event IDs")
        if not summary.strip() or len(summary) > 256:
            raise ValueError("goal retirement summary must contain 1..256 characters")
        record = self.get(goal_id)
        if record.status is GoalStatus.RETIRED:
            return record
        updated = replace(record, status=GoalStatus.RETIRED)
        self._records[goal_id] = updated
        self._append(
            GoalEventType.RETIRED,
            updated,
            source_event_ids=sources,
            previous_status=record.status,
            summary=summary,
        )
        return updated

    def selected(self, goal_id: str) -> GoalLifecycleEvent:
        record = self.get(goal_id)
        if record.status is GoalStatus.RETIRED:
            raise ValueError("a retired goal cannot be selected")
        self._append(
            GoalEventType.SELECTED,
            record,
            source_event_ids=record.source_event_ids,
            previous_status=record.status,
            summary="candidate selected for planning",
        )
        return self._events[-1]


__all__ = ["GoalEventType", "GoalLifecycleEvent", "GoalRegistry"]
