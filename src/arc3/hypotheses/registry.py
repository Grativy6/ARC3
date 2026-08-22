"""Deterministic event-sourced hypothesis registry and compatibility logic."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from typing import cast

from arc3.errors import HypothesisError
from arc3.trace.canonical import canonical_json, normalize_json
from arc3.types import HypothesisStatus, JSONValue

from .base import (
    Compatibility,
    EvidenceKind,
    EvidenceReceipt,
    HypothesisFamily,
    HypothesisPrediction,
    HypothesisScope,
    normalize_strings,
    require_text,
)
from .events import HypothesisEvent, HypothesisEventType
from .families import HypothesisStatement


@dataclass(frozen=True, slots=True)
class ScopeRevision:
    """One retained scope change in a hypothesis lineage."""

    event_id: str
    previous_scope: HypothesisScope | None
    previous_scope_ref: str | None
    new_scope: HypothesisScope
    new_scope_ref: str | None

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "event_id": self.event_id,
            "previous_scope": self.previous_scope.value if self.previous_scope else None,
            "previous_scope_ref": self.previous_scope_ref,
            "new_scope": self.new_scope.value,
            "new_scope_ref": self.new_scope_ref,
        }


@dataclass(frozen=True, slots=True)
class PlanInvalidationSignal:
    """Explicit downstream signal emitted when a hypothesis is reopened."""

    event_id: str
    hypothesis_id: str
    plan_ids: tuple[str, ...]
    reason_receipt_id: str

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "event_id": self.event_id,
            "hypothesis_id": self.hypothesis_id,
            "plan_ids": list(self.plan_ids),
            "reason_receipt_id": self.reason_receipt_id,
        }


@dataclass(frozen=True, slots=True)
class HypothesisRecord:
    """Current replaceable view derived from immutable hypothesis events."""

    hypothesis_id: str
    family: HypothesisFamily
    statement: HypothesisStatement
    scope: HypothesisScope
    scope_ref: str | None
    status: HypothesisStatus
    rank_weight: int
    created_event_id: str
    created_sequence: int
    created_from_event_ids: tuple[str, ...]
    predictions: tuple[HypothesisPrediction, ...]
    support_receipts: tuple[EvidenceReceipt, ...]
    contradiction_receipts: tuple[EvidenceReceipt, ...]
    residual_receipts: tuple[EvidenceReceipt, ...]
    parent_ids: tuple[str, ...]
    narrowed_to_ids: tuple[str, ...]
    superseded_by: str | None
    scope_history: tuple[ScopeRevision, ...]
    last_tested_step: int | None
    conflict_ids: tuple[str, ...]
    compatible_ids: tuple[str, ...]
    version: int
    event_ids: tuple[str, ...]

    @property
    def support_event_ids(self) -> tuple[str, ...]:
        """All immutable event IDs supporting the claim."""

        return _receipt_source_ids(self.support_receipts)

    @property
    def contradiction_event_ids(self) -> tuple[str, ...]:
        """All immutable event IDs contradicting the claim."""

        return _receipt_source_ids(self.contradiction_receipts)

    @property
    def residual_event_ids(self) -> tuple[str, ...]:
        """All source IDs for unexplained residuals."""

        return _receipt_source_ids(self.residual_receipts)

    @property
    def is_ensemble_eligible(self) -> bool:
        """Whether the current status can contribute to a live model ensemble."""

        return self.status in {
            HypothesisStatus.CANDIDATE,
            HypothesisStatus.ACTIVE,
            HypothesisStatus.UNRESOLVED,
        }

    def to_dict(self) -> dict[str, JSONValue]:
        """Return the serializable current view without hiding counterevidence."""

        return {
            "hypothesis_id": self.hypothesis_id,
            "hypothesis_type": self.family.value,
            "statement": self.statement.to_dict(),
            "scope": self.scope.value,
            "scope_ref": self.scope_ref,
            "status": self.status.value,
            "rank_weight": self.rank_weight,
            "weight_kind": "uncalibrated_rank",
            "created_event_id": self.created_event_id,
            "created_sequence": self.created_sequence,
            "created_from_event_ids": list(self.created_from_event_ids),
            "predictions": [prediction.to_dict() for prediction in self.predictions],
            "support_receipts": [receipt.to_dict() for receipt in self.support_receipts],
            "contradiction_receipts": [
                receipt.to_dict() for receipt in self.contradiction_receipts
            ],
            "residual_receipts": [receipt.to_dict() for receipt in self.residual_receipts],
            "support_event_ids": list(self.support_event_ids),
            "contradiction_event_ids": list(self.contradiction_event_ids),
            "residual_event_ids": list(self.residual_event_ids),
            "parent_ids": list(self.parent_ids),
            "narrowed_to_ids": list(self.narrowed_to_ids),
            "superseded_by": self.superseded_by,
            "scope_history": [revision.to_dict() for revision in self.scope_history],
            "last_tested_step": self.last_tested_step,
            "conflict_ids": list(self.conflict_ids),
            "compatible_ids": list(self.compatible_ids),
            "version": self.version,
            "event_ids": list(self.event_ids),
        }


def _receipt_source_ids(receipts: tuple[EvidenceReceipt, ...]) -> tuple[str, ...]:
    return tuple(
        sorted({event_id for receipt in receipts for event_id in receipt.evidence_event_ids})
    )


_ALLOWED_PREVIOUS: dict[HypothesisEventType, frozenset[HypothesisStatus]] = {
    HypothesisEventType.SUPPORTED: frozenset(
        {
            HypothesisStatus.CANDIDATE,
            HypothesisStatus.ACTIVE,
            HypothesisStatus.UNRESOLVED,
        }
    ),
    HypothesisEventType.CONTRADICTED: frozenset(
        {
            HypothesisStatus.CANDIDATE,
            HypothesisStatus.ACTIVE,
            HypothesisStatus.UNRESOLVED,
        }
    ),
    HypothesisEventType.NARROWED: frozenset(
        {
            HypothesisStatus.CANDIDATE,
            HypothesisStatus.ACTIVE,
            HypothesisStatus.UNRESOLVED,
        }
    ),
    HypothesisEventType.REJECTED: frozenset(
        {
            HypothesisStatus.CANDIDATE,
            HypothesisStatus.ACTIVE,
            HypothesisStatus.UNRESOLVED,
            HypothesisStatus.NARROWED,
        }
    ),
    HypothesisEventType.REOPENED: frozenset(
        {
            HypothesisStatus.ACTIVE,
            HypothesisStatus.UNRESOLVED,
            HypothesisStatus.NARROWED,
            HypothesisStatus.REJECTED,
            HypothesisStatus.SUPERSEDED,
        }
    ),
    HypothesisEventType.SUPERSEDED: frozenset(
        {
            HypothesisStatus.CANDIDATE,
            HypothesisStatus.ACTIVE,
            HypothesisStatus.UNRESOLVED,
            HypothesisStatus.NARROWED,
        }
    ),
    HypothesisEventType.SCOPE_CHANGED: frozenset(HypothesisStatus),
}


class HypothesisRegistry:
    """Fold immutable events into revisable typed hypothesis records."""

    def __init__(self, events: Iterable[HypothesisEvent] = ()) -> None:
        self._events: list[HypothesisEvent] = []
        self._records: dict[str, HypothesisRecord] = {}
        self._event_ids: set[str] = set()
        self._receipt_ids: set[str] = set()
        self._dependent_plans: dict[str, set[str]] = {}
        self._invalidations: list[PlanInvalidationSignal] = []
        for event in events:
            self.apply(event)

    @property
    def events(self) -> tuple[HypothesisEvent, ...]:
        """Return the immutable event history in accepted order."""

        return tuple(self._events)

    @property
    def invalidations(self) -> tuple[PlanInvalidationSignal, ...]:
        """Return all retained dependent-plan invalidation signals."""

        return tuple(self._invalidations)

    def __len__(self) -> int:
        return len(self._records)

    def get(self, hypothesis_id: str) -> HypothesisRecord:
        """Retrieve any record, including rejected and superseded history."""

        try:
            return self._records[hypothesis_id]
        except KeyError as error:
            raise HypothesisError(f"unknown hypothesis: {hypothesis_id}") from error

    def find(self, hypothesis_id: str) -> HypothesisRecord | None:
        """Return a record if known, without filtering historical statuses."""

        return self._records.get(hypothesis_id)

    def all(self) -> tuple[HypothesisRecord, ...]:
        """Return all records in stable identifier order."""

        return tuple(self._records[key] for key in sorted(self._records))

    def rejected(self) -> tuple[HypothesisRecord, ...]:
        """Return rejected records without deleting or hiding them."""

        return tuple(record for record in self.all() if record.status is HypothesisStatus.REJECTED)

    def ever_rejected(self) -> tuple[HypothesisRecord, ...]:
        """Return records with a retained rejection event, even after reopening."""

        rejected_ids = {
            event.hypothesis_id
            for event in self._events
            if event.event_type is HypothesisEventType.REJECTED
        }
        return tuple(self._records[key] for key in sorted(rejected_ids))

    def create(
        self,
        *,
        statement: HypothesisStatement,
        scope: HypothesisScope,
        created_from_event_ids: Iterable[str],
        occurred_step: int,
        hypothesis_id: str | None = None,
        event_id: str | None = None,
        scope_ref: str | None = None,
        predictions: Iterable[HypothesisPrediction] = (),
        parent_ids: Iterable[str] = (),
        conflict_ids: Iterable[str] = (),
        compatible_ids: Iterable[str] = (),
        initial_rank_weight: int = 0,
        note: str = "",
    ) -> HypothesisRecord:
        """Create a candidate from explicit source evidence pointers."""

        normalized_parents = normalize_strings(parent_ids, field="parent_id")
        for parent_id in normalized_parents:
            self.get(parent_id)
        identifier = hypothesis_id or self._next_hypothesis_id(statement.family)
        if identifier in self._records:
            raise HypothesisError(f"duplicate hypothesis_id: {identifier}")
        event = HypothesisEvent(
            event_id=event_id or self._next_event_id(),
            sequence=len(self._events),
            event_type=HypothesisEventType.CREATED,
            hypothesis_id=identifier,
            occurred_step=occurred_step,
            status=HypothesisStatus.CANDIDATE,
            family=statement.family,
            statement=statement,
            scope=scope,
            scope_ref=scope_ref,
            created_from_event_ids=tuple(created_from_event_ids),
            predictions=tuple(predictions),
            parent_ids=normalized_parents,
            conflict_ids=tuple(conflict_ids),
            compatible_ids=tuple(compatible_ids),
            rank_delta=initial_rank_weight,
            note=note,
        )
        self.apply(event)
        return self.get(identifier)

    def support(
        self,
        hypothesis_id: str,
        receipt: EvidenceReceipt,
        *,
        event_id: str | None = None,
        note: str = "",
    ) -> HypothesisRecord:
        """Append support and promote a live candidate to active status."""

        return self._evidence_transition(
            hypothesis_id,
            receipt,
            event_type=HypothesisEventType.SUPPORTED,
            status=HypothesisStatus.ACTIVE,
            event_id=event_id,
            note=note,
        )

    def contradict(
        self,
        hypothesis_id: str,
        receipt: EvidenceReceipt,
        *,
        event_id: str | None = None,
        note: str = "",
    ) -> HypothesisRecord:
        """Append counterevidence and mark the claim unresolved."""

        return self._evidence_transition(
            hypothesis_id,
            receipt,
            event_type=HypothesisEventType.CONTRADICTED,
            status=HypothesisStatus.UNRESOLVED,
            event_id=event_id,
            note=note,
        )

    def narrow(
        self,
        hypothesis_id: str,
        *,
        statement: HypothesisStatement,
        receipt: EvidenceReceipt,
        occurred_step: int,
        scope: HypothesisScope | None = None,
        scope_ref: str | None = None,
        new_hypothesis_id: str | None = None,
        narrowed_event_id: str | None = None,
        created_event_id: str | None = None,
        predictions: Iterable[HypothesisPrediction] | None = None,
        note: str = "",
    ) -> HypothesisRecord:
        """Retain the broad claim and create a lineage-linked narrower form."""

        parent = self.get(hypothesis_id)
        if parent.status not in _ALLOWED_PREVIOUS[HypothesisEventType.NARROWED]:
            raise HypothesisError(f"cannot narrow hypothesis in {parent.status.value} status")
        if statement.family is not parent.family:
            raise HypothesisError("a narrowed form must retain the parent hypothesis family")
        child_id = new_hypothesis_id or self._next_hypothesis_id(statement.family)
        if child_id in self._records:
            raise HypothesisError(f"duplicate hypothesis_id: {child_id}")
        normalized_scope = scope or parent.scope
        normalized_ref = scope_ref if scope_ref is not None else parent.scope_ref
        child = self.create(
            statement=statement,
            scope=normalized_scope,
            scope_ref=normalized_ref,
            created_from_event_ids=receipt.evidence_event_ids,
            occurred_step=occurred_step,
            hypothesis_id=child_id,
            event_id=created_event_id,
            predictions=parent.predictions if predictions is None else predictions,
            parent_ids=(parent.hypothesis_id,),
            initial_rank_weight=parent.rank_weight,
            note=f"narrowed from {parent.hypothesis_id}",
        )
        narrowed_event = self._transition_event(
            parent,
            event_type=HypothesisEventType.NARROWED,
            status=HypothesisStatus.NARROWED,
            receipt=receipt,
            event_id=narrowed_event_id,
            related_hypothesis_id=child_id,
            note=note,
        )
        self.apply(narrowed_event)
        return child

    def reject(
        self,
        hypothesis_id: str,
        receipt: EvidenceReceipt,
        *,
        event_id: str | None = None,
        note: str = "",
    ) -> HypothesisRecord:
        """Reject a claim while retaining it and every evidence pointer."""

        return self._evidence_transition(
            hypothesis_id,
            receipt,
            event_type=HypothesisEventType.REJECTED,
            status=HypothesisStatus.REJECTED,
            event_id=event_id,
            note=note,
        )

    def reopen(
        self,
        hypothesis_id: str,
        receipt: EvidenceReceipt,
        *,
        invalidated_plan_ids: Iterable[str] = (),
        event_id: str | None = None,
        note: str = "",
    ) -> PlanInvalidationSignal:
        """Reopen a prior claim and emit deterministic dependent-plan invalidation."""

        record = self.get(hypothesis_id)
        plans = normalize_strings(
            (*self._dependent_plans.get(hypothesis_id, set()), *invalidated_plan_ids),
            field="invalidated plan_id",
        )
        event = self._transition_event(
            record,
            event_type=HypothesisEventType.REOPENED,
            status=HypothesisStatus.CANDIDATE,
            receipt=receipt,
            event_id=event_id,
            invalidated_plan_ids=plans,
            note=note,
        )
        self.apply(event)
        self._dependent_plans[hypothesis_id] = set()
        return self._invalidations[-1]

    def supersede(
        self,
        hypothesis_id: str,
        superseding_hypothesis_id: str,
        *,
        occurred_step: int,
        caused_by_event_ids: Iterable[str] = (),
        event_id: str | None = None,
        note: str = "",
    ) -> HypothesisRecord:
        """Mark a record superseded by another retained record."""

        record = self.get(hypothesis_id)
        self.get(superseding_hypothesis_id)
        event = self._transition_event(
            record,
            event_type=HypothesisEventType.SUPERSEDED,
            status=HypothesisStatus.SUPERSEDED,
            occurred_step=occurred_step,
            caused_by_event_ids=tuple(caused_by_event_ids),
            event_id=event_id,
            related_hypothesis_id=superseding_hypothesis_id,
            note=note,
        )
        self.apply(event)
        return self.get(hypothesis_id)

    def change_scope(
        self,
        hypothesis_id: str,
        new_scope: HypothesisScope,
        *,
        occurred_step: int,
        new_scope_ref: str | None = None,
        caused_by_event_ids: Iterable[str] = (),
        event_id: str | None = None,
        note: str = "",
    ) -> HypothesisRecord:
        """Append a scope revision without rewriting the original claim."""

        record = self.get(hypothesis_id)
        event = self._transition_event(
            record,
            event_type=HypothesisEventType.SCOPE_CHANGED,
            status=record.status,
            occurred_step=occurred_step,
            caused_by_event_ids=tuple(caused_by_event_ids),
            event_id=event_id,
            scope=new_scope,
            scope_ref=new_scope_ref,
            note=note,
        )
        self.apply(event)
        return self.get(hypothesis_id)

    def register_dependent_plan(self, plan_id: str, hypothesis_ids: Iterable[str]) -> None:
        """Register plan dependencies for a later reopening signal."""

        identifier = require_text(plan_id, field="plan_id")
        normalized = normalize_strings(hypothesis_ids, field="hypothesis_id")
        if not normalized:
            raise HypothesisError("a dependent plan requires at least one hypothesis")
        for hypothesis_id in normalized:
            record = self.get(hypothesis_id)
            if not record.is_ensemble_eligible:
                raise HypothesisError(
                    f"plan cannot depend on {hypothesis_id} in {record.status.value} status"
                )
            self._dependent_plans.setdefault(hypothesis_id, set()).add(identifier)

    def dependent_plan_ids(self, hypothesis_id: str) -> tuple[str, ...]:
        """Return current dependent plan IDs in deterministic order."""

        self.get(hypothesis_id)
        return tuple(sorted(self._dependent_plans.get(hypothesis_id, set())))

    def apply(self, event: HypothesisEvent) -> None:
        """Validate and append one event, then update its replaceable derived view."""

        if event.sequence != len(self._events):
            raise HypothesisError(
                f"hypothesis event sequence {event.sequence} does not follow {len(self._events) - 1}"
            )
        if event.event_id in self._event_ids:
            raise HypothesisError(f"duplicate hypothesis event_id: {event.event_id}")
        if event.receipt is not None and event.receipt.receipt_id in self._receipt_ids:
            raise HypothesisError(f"duplicate evidence receipt_id: {event.receipt.receipt_id}")
        updated, invalidation = self._reduce(event)
        self._events.append(event)
        self._event_ids.add(event.event_id)
        if event.receipt is not None:
            self._receipt_ids.add(event.receipt.receipt_id)
        self._records[event.hypothesis_id] = updated
        if invalidation is not None:
            self._invalidations.append(invalidation)

    def _reduce(
        self, event: HypothesisEvent
    ) -> tuple[HypothesisRecord, PlanInvalidationSignal | None]:
        if event.event_type is HypothesisEventType.CREATED:
            if event.hypothesis_id in self._records:
                raise HypothesisError(f"duplicate hypothesis_id: {event.hypothesis_id}")
            assert event.family is not None
            assert event.statement is not None
            assert event.scope is not None
            for parent_id in event.parent_ids:
                self.get(parent_id)
            record = HypothesisRecord(
                hypothesis_id=event.hypothesis_id,
                family=event.family,
                statement=event.statement,
                scope=event.scope,
                scope_ref=event.scope_ref,
                status=event.status,
                rank_weight=event.rank_delta,
                created_event_id=event.event_id,
                created_sequence=event.sequence,
                created_from_event_ids=event.created_from_event_ids,
                predictions=event.predictions,
                support_receipts=(),
                contradiction_receipts=(),
                residual_receipts=(),
                parent_ids=event.parent_ids,
                narrowed_to_ids=(),
                superseded_by=None,
                scope_history=(
                    ScopeRevision(event.event_id, None, None, event.scope, event.scope_ref),
                ),
                last_tested_step=None,
                conflict_ids=event.conflict_ids,
                compatible_ids=event.compatible_ids,
                version=1,
                event_ids=(event.event_id,),
            )
            return record, None

        record = self.get(event.hypothesis_id)
        if event.previous_status is not record.status:
            raise HypothesisError(
                f"stale transition for {record.hypothesis_id}: event expected "
                f"{event.previous_status}, current status is {record.status.value}"
            )
        allowed = _ALLOWED_PREVIOUS[event.event_type]
        if record.status not in allowed:
            raise HypothesisError(
                f"cannot apply {event.event_type.value} to {record.status.value} hypothesis"
            )

        support = record.support_receipts
        contradictions = record.contradiction_receipts
        residuals = record.residual_receipts
        if event.receipt is not None:
            if event.receipt.kind is EvidenceKind.SUPPORT:
                support = (*support, event.receipt)
            elif event.receipt.kind is EvidenceKind.CONTRADICTION:
                contradictions = (*contradictions, event.receipt)
            else:
                residuals = (*residuals, event.receipt)

        narrowed_to = record.narrowed_to_ids
        superseded_by = record.superseded_by
        scope = record.scope
        scope_ref = record.scope_ref
        scope_history = record.scope_history
        if event.event_type is HypothesisEventType.NARROWED:
            assert event.related_hypothesis_id is not None
            narrowed_record = self.get(event.related_hypothesis_id)
            if record.hypothesis_id not in narrowed_record.parent_ids:
                raise HypothesisError("narrowed form must identify the source hypothesis as parent")
            narrowed_to = tuple(sorted({*narrowed_to, event.related_hypothesis_id}))
        elif event.event_type is HypothesisEventType.SUPERSEDED:
            assert event.related_hypothesis_id is not None
            self.get(event.related_hypothesis_id)
            superseded_by = event.related_hypothesis_id
        elif event.event_type is HypothesisEventType.SCOPE_CHANGED:
            assert event.scope is not None
            scope_history = (
                *scope_history,
                ScopeRevision(
                    event.event_id,
                    record.scope,
                    record.scope_ref,
                    event.scope,
                    event.scope_ref,
                ),
            )
            scope = event.scope
            scope_ref = event.scope_ref

        invalidation: PlanInvalidationSignal | None = None
        if event.event_type is HypothesisEventType.REOPENED:
            assert event.receipt is not None
            invalidation = PlanInvalidationSignal(
                event_id=event.event_id,
                hypothesis_id=event.hypothesis_id,
                plan_ids=event.invalidated_plan_ids,
                reason_receipt_id=event.receipt.receipt_id,
            )

        updated = replace(
            record,
            status=event.status,
            rank_weight=record.rank_weight + event.rank_delta,
            support_receipts=support,
            contradiction_receipts=contradictions,
            residual_receipts=residuals,
            narrowed_to_ids=narrowed_to,
            superseded_by=superseded_by,
            scope=scope,
            scope_ref=scope_ref,
            scope_history=scope_history,
            last_tested_step=(
                event.receipt.observed_step
                if event.receipt is not None
                else record.last_tested_step
            ),
            version=record.version + 1,
            event_ids=(*record.event_ids, event.event_id),
        )
        return updated, invalidation

    def _evidence_transition(
        self,
        hypothesis_id: str,
        receipt: EvidenceReceipt,
        *,
        event_type: HypothesisEventType,
        status: HypothesisStatus,
        event_id: str | None,
        note: str,
    ) -> HypothesisRecord:
        record = self.get(hypothesis_id)
        event = self._transition_event(
            record,
            event_type=event_type,
            status=status,
            receipt=receipt,
            event_id=event_id,
            note=note,
        )
        self.apply(event)
        return self.get(hypothesis_id)

    def _transition_event(
        self,
        record: HypothesisRecord,
        *,
        event_type: HypothesisEventType,
        status: HypothesisStatus,
        receipt: EvidenceReceipt | None = None,
        occurred_step: int | None = None,
        caused_by_event_ids: tuple[str, ...] = (),
        event_id: str | None = None,
        related_hypothesis_id: str | None = None,
        invalidated_plan_ids: tuple[str, ...] = (),
        scope: HypothesisScope | None = None,
        scope_ref: str | None = None,
        note: str = "",
    ) -> HypothesisEvent:
        event_sources = receipt.evidence_event_ids if receipt is not None else caused_by_event_ids
        step = receipt.observed_step if receipt is not None else occurred_step
        if step is None:
            raise HypothesisError("hypothesis transition requires an occurred step")
        return HypothesisEvent(
            event_id=event_id or self._next_event_id(),
            sequence=len(self._events),
            event_type=event_type,
            hypothesis_id=record.hypothesis_id,
            occurred_step=step,
            status=status,
            previous_status=record.status,
            scope=scope,
            scope_ref=scope_ref,
            caused_by_event_ids=event_sources,
            receipt=receipt,
            related_hypothesis_id=related_hypothesis_id,
            invalidated_plan_ids=invalidated_plan_ids,
            rank_delta=receipt.signed_rank_impact if receipt is not None else 0,
            note=note,
        )

    def history(
        self, hypothesis_id: str, *, include_lineage: bool = False
    ) -> tuple[HypothesisEvent, ...]:
        """Return ordered history for one record or its connected lineage."""

        identifiers = (
            {record.hypothesis_id for record in self.lineage(hypothesis_id)}
            if include_lineage
            else {self.get(hypothesis_id).hypothesis_id}
        )
        return tuple(event for event in self._events if event.hypothesis_id in identifiers)

    def lineage(self, hypothesis_id: str) -> tuple[HypothesisRecord, ...]:
        """Return all parent, narrowed, and superseding records in a stable closure."""

        pending = [self.get(hypothesis_id).hypothesis_id]
        visited: set[str] = set()
        while pending:
            identifier = pending.pop()
            if identifier in visited:
                continue
            visited.add(identifier)
            record = self.get(identifier)
            related = [*record.parent_ids, *record.narrowed_to_ids]
            if record.superseded_by is not None:
                related.append(record.superseded_by)
            pending.extend(item for item in related if item not in visited)
        return tuple(sorted((self.get(item) for item in visited), key=_lineage_key))

    def ranking_key(self, record: HypothesisRecord) -> tuple[int, int, int, int, int, int, str]:
        """Return a documented deterministic key containing no probability claim."""

        status_priority = {
            HypothesisStatus.ACTIVE: 5,
            HypothesisStatus.CANDIDATE: 4,
            HypothesisStatus.UNRESOLVED: 3,
            HypothesisStatus.NARROWED: 2,
            HypothesisStatus.REJECTED: 1,
            HypothesisStatus.SUPERSEDED: 0,
        }[record.status]
        support = sum(receipt.rank_impact for receipt in record.support_receipts)
        counter = sum(receipt.rank_impact for receipt in record.contradiction_receipts)
        residual = sum(receipt.rank_impact for receipt in record.residual_receipts)
        return (
            -record.rank_weight,
            -status_priority,
            -support,
            counter,
            residual,
            record.created_sequence,
            record.hypothesis_id,
        )

    def ranked(
        self,
        *,
        family: HypothesisFamily | None = None,
        statuses: Iterable[HypothesisStatus] | None = None,
        include_rejected: bool = False,
    ) -> tuple[HypothesisRecord, ...]:
        """Rank records deterministically using uncalibrated integer weights."""

        allowed = set(statuses) if statuses is not None else None
        candidates = [
            record
            for record in self._records.values()
            if (family is None or record.family is family)
            and (allowed is None or record.status in allowed)
            and (include_rejected or record.status is not HypothesisStatus.REJECTED)
        ]
        return tuple(sorted(candidates, key=self.ranking_key))

    def compatibility(self, left_id: str, right_id: str) -> Compatibility:
        """Check explicit and structural compatibility symmetrically."""

        left = self.get(left_id)
        right = self.get(right_id)
        if left.hypothesis_id == right.hypothesis_id:
            return Compatibility.REDUNDANT
        if right.hypothesis_id in left.conflict_ids or left.hypothesis_id in right.conflict_ids:
            return Compatibility.INCOMPATIBLE
        if right.hypothesis_id in left.compatible_ids or left.hypothesis_id in right.compatible_ids:
            return Compatibility.COMPATIBLE
        if (
            left.family is right.family
            and left.statement.to_dict() == right.statement.to_dict()
            and left.scope is right.scope
            and left.scope_ref == right.scope_ref
        ):
            return Compatibility.REDUNDANT
        if (
            left.family is right.family
            and left.statement.conflict_domain() == right.statement.conflict_domain()
            and _scope_overlap(left, right)
        ):
            return Compatibility.INCOMPATIBLE
        return Compatibility.COMPATIBLE

    def resolve_conflict(self, hypothesis_ids: Iterable[str]) -> HypothesisRecord:
        """Select the stable highest-ranked eligible member without mutating history."""

        identifiers = normalize_strings(hypothesis_ids, field="hypothesis_id")
        candidates = [self.get(identifier) for identifier in identifiers]
        eligible = [record for record in candidates if record.is_ensemble_eligible]
        if not eligible:
            raise HypothesisError("conflict resolution requires an eligible hypothesis")
        return min(eligible, key=self.ranking_key)

    def compatible_ensemble(
        self, hypothesis_ids: Iterable[str] | None = None
    ) -> tuple[HypothesisRecord, ...]:
        """Greedily form a stable compatible ensemble from ranked live records."""

        if hypothesis_ids is None:
            pool = [record for record in self._records.values() if record.is_ensemble_eligible]
        else:
            identifiers = normalize_strings(hypothesis_ids, field="hypothesis_id")
            pool = [self.get(identifier) for identifier in identifiers]
            pool = [record for record in pool if record.is_ensemble_eligible]
        selected: list[HypothesisRecord] = []
        for candidate in sorted(pool, key=self.ranking_key):
            relations = [
                self.compatibility(candidate.hypothesis_id, existing.hypothesis_id)
                for existing in selected
            ]
            if all(relation is Compatibility.COMPATIBLE for relation in relations):
                selected.append(candidate)
        return tuple(selected)

    def to_dict(self) -> dict[str, JSONValue]:
        """Serialize events, current views, plan dependencies, and invalidations."""

        return {
            "schema": "arc3.hypothesis.registry.v0.1",
            "events": [event.to_dict() for event in self._events],
            "records": {key: record.to_dict() for key, record in sorted(self._records.items())},
            "dependent_plans": {
                key: cast(list[JSONValue], sorted(value))
                for key, value in sorted(self._dependent_plans.items())
                if value
            },
            "invalidations": [signal.to_dict() for signal in self._invalidations],
        }

    def canonical_snapshot(self) -> str:
        """Return a deterministic checkpoint/report representation."""

        return canonical_json(self.to_dict())

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> HypothesisRegistry:
        """Restore by replaying events; serialized records are never trusted as authority."""

        if value.get("schema") != "arc3.hypothesis.registry.v0.1":
            raise HypothesisError("unsupported hypothesis registry schema")
        events_value = value.get("events")
        if not isinstance(events_value, list) or not all(
            isinstance(item, Mapping) for item in events_value
        ):
            raise HypothesisError("hypothesis registry events must be an array of objects")
        registry = cls(HypothesisEvent.from_dict(item) for item in events_value)
        dependencies = value.get("dependent_plans", {})
        if not isinstance(dependencies, Mapping):
            raise HypothesisError("dependent_plans must be an object")
        for hypothesis_id, plan_ids in dependencies.items():
            if not isinstance(hypothesis_id, str) or not isinstance(plan_ids, list):
                raise HypothesisError("dependent plan entries must map strings to arrays")
            registry.get(hypothesis_id)
            for plan_id in plan_ids:
                if not isinstance(plan_id, str):
                    raise HypothesisError("dependent plan IDs must be strings")
                registry._dependent_plans.setdefault(hypothesis_id, set()).add(
                    require_text(plan_id, field="plan_id")
                )
        replayed = registry.to_dict()
        for field in ("records", "dependent_plans", "invalidations"):
            supplied = value.get(field)
            if normalize_json(supplied) != replayed[field]:
                raise HypothesisError(
                    f"serialized hypothesis {field} disagrees with replayed events"
                )
        return registry

    def _next_event_id(self) -> str:
        ordinal = len(self._events) + 1
        while True:
            candidate = f"HE-{ordinal:08d}"
            if candidate not in self._event_ids:
                return candidate
            ordinal += 1

    def _next_hypothesis_id(self, family: HypothesisFamily) -> str:
        prefix = family.value.upper().replace("_", "-")
        ordinal = 1
        while True:
            candidate = f"H-{prefix}-{ordinal:04d}"
            if candidate not in self._records:
                return candidate
            ordinal += 1


def _scope_overlap(left: HypothesisRecord, right: HypothesisRecord) -> bool:
    if left.scope is HypothesisScope.GENERIC or right.scope is HypothesisScope.GENERIC:
        return True
    if left.scope_ref is None or right.scope_ref is None:
        return True
    if left.scope is right.scope:
        return left.scope_ref == right.scope_ref
    return left.scope_ref.startswith(f"{right.scope_ref}/") or right.scope_ref.startswith(
        f"{left.scope_ref}/"
    )


def _lineage_key(record: HypothesisRecord) -> tuple[int, str]:
    return (record.created_sequence, record.hypothesis_id)
