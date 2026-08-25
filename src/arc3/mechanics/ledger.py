"""Bounded hash-linked event ledger for versioned mechanics."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Self, cast

from arc3.trace.canonical import (
    canonical_bytes,
    canonical_json,
    is_sha256,
    normalize_json,
    parse_json_bytes,
    sha256_json,
)
from arc3.types import ActionName, JSONValue

from .models import (
    CHANNEL_ORDER,
    ChannelEvidenceSummary,
    CompositionMode,
    ConfirmationMode,
    ConsequenceChannel,
    ConsequenceVector,
    EvidenceProvenance,
    MechanicContext,
    MechanicEvidence,
    MechanicEvidenceKind,
    MechanicLedgerBudget,
    MechanicRef,
    MechanicScope,
    MechanicsError,
    MechanicStatus,
    MechanicVersion,
    MechanicView,
    ScopeCeiling,
    SupportDimension,
)

LEDGER_SCHEMA = "arc3.mechanics.ledger.v0.1"
COMPACT_LEDGER_SCHEMA = "arc3.mechanics.ledger.compact.v0.1"
EVENT_SCHEMA = "arc3.mechanics.event.v0.1"


class MechanicEventType(StrEnum):
    VERSION_DECLARED = "mechanic.version_declared"
    EVIDENCE_RECORDED = "mechanic.evidence_recorded"
    STATUS_CHANGED = "mechanic.status_changed"


@dataclass(frozen=True, slots=True)
class MechanicLedgerEvent:
    """One immutable, hash-linked input to the mechanic projection."""

    event_id: str
    sequence: int
    event_type: MechanicEventType
    ref: MechanicRef
    occurred_step: int
    previous_event_hash: str | None
    version: MechanicVersion | None = None
    evidence: MechanicEvidence | None = None
    previous_status: MechanicStatus | None = None
    status: MechanicStatus | None = None
    caused_by_event_ids: tuple[str, ...] = ()
    superseded_by: MechanicRef | None = None
    note: str = ""
    event_hash: str = ""
    schema: str = EVENT_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != EVENT_SCHEMA:
            raise MechanicsError(f"unsupported mechanic event schema: {self.schema!r}")
        _text(self.event_id, field="mechanic event_id")
        _non_negative(self.sequence, field="mechanic event sequence")
        _non_negative(self.occurred_step, field="mechanic event step")
        if self.previous_event_hash is not None and not is_sha256(self.previous_event_hash):
            raise MechanicsError("previous_event_hash must be a tagged SHA-256 digest")
        object.__setattr__(self, "caused_by_event_ids", _strings(self.caused_by_event_ids))
        if len(self.note) > 512:
            raise MechanicsError("mechanic event note must not exceed 512 characters")
        self._validate_shape()
        expected = sha256_json(self._hash_payload())
        if self.event_hash and self.event_hash != expected:
            raise MechanicsError("mechanic event hash does not match canonical content")
        object.__setattr__(self, "event_hash", expected)

    def _validate_shape(self) -> None:
        if self.event_type is MechanicEventType.VERSION_DECLARED:
            if self.version is None or self.version.ref != self.ref:
                raise MechanicsError("version-declared events require their referenced version")
            if self.status is not MechanicStatus.PROVISIONAL or self.previous_status is not None:
                raise MechanicsError("new mechanic versions must begin provisional")
            if self.evidence is not None:
                raise MechanicsError("version-declared events cannot carry evidence")
            if self.caused_by_event_ids != self.version.created_from_event_ids:
                raise MechanicsError("version event causes must equal semantic source event IDs")
            return
        if self.version is not None:
            raise MechanicsError("only version-declared events may carry mechanic semantics")
        if self.event_type is MechanicEventType.EVIDENCE_RECORDED:
            if self.evidence is None:
                raise MechanicsError("evidence-recorded events require evidence")
            if self.status is not None or self.previous_status is not None:
                raise MechanicsError("evidence events cannot silently change status")
            if self.caused_by_event_ids != self.evidence.source_event_ids:
                raise MechanicsError("evidence event causes must equal its source event IDs")
            return
        if self.evidence is not None:
            raise MechanicsError("status events cannot carry evidence")
        if self.previous_status is None or self.status is None:
            raise MechanicsError("status-changed events require old and new statuses")
        if self.previous_status is self.status:
            raise MechanicsError("status-changed events must change status")
        if not self.caused_by_event_ids:
            raise MechanicsError("status-changed events require a source cause")
        if (
            self.superseded_by is not None
            and self.status is not MechanicStatus.REJECTED_OR_SUPERSEDED
        ):
            raise MechanicsError("superseded_by requires rejected-or-superseded status")

    def _hash_payload(self) -> dict[str, JSONValue]:
        return {
            "schema": self.schema,
            "event_id": self.event_id,
            "sequence": self.sequence,
            "event_type": self.event_type.value,
            "ref": self.ref.to_dict(),
            "occurred_step": self.occurred_step,
            "previous_event_hash": self.previous_event_hash,
            "version": self.version.to_dict() if self.version else None,
            "evidence": self.evidence.to_dict() if self.evidence else None,
            "previous_status": self.previous_status.value if self.previous_status else None,
            "status": self.status.value if self.status else None,
            "caused_by_event_ids": list(self.caused_by_event_ids),
            "superseded_by": self.superseded_by.to_dict() if self.superseded_by else None,
            "note": self.note,
        }

    def to_dict(self) -> dict[str, JSONValue]:
        return {**self._hash_payload(), "event_hash": self.event_hash}

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> Self:
        ref = _mapping(value.get("ref"), field="mechanic event ref")
        version_value = value.get("version")
        evidence_value = value.get("evidence")
        superseded_value = value.get("superseded_by")
        previous_status = value.get("previous_status")
        status = value.get("status")
        previous_hash = value.get("previous_event_hash")
        return cls(
            schema=_text(value.get("schema"), field="mechanic event schema"),
            event_id=_text(value.get("event_id"), field="mechanic event_id"),
            sequence=_integer(value.get("sequence"), field="mechanic event sequence"),
            event_type=_event_type(value.get("event_type")),
            ref=MechanicRef.from_dict(ref),
            occurred_step=_integer(value.get("occurred_step"), field="mechanic event step"),
            previous_event_hash=(
                None if previous_hash is None else _text(previous_hash, field="previous_event_hash")
            ),
            version=(
                None
                if version_value is None
                else MechanicVersion.from_dict(_mapping(version_value, field="mechanic version"))
            ),
            evidence=(
                None
                if evidence_value is None
                else MechanicEvidence.from_dict(_mapping(evidence_value, field="mechanic evidence"))
            ),
            previous_status=(None if previous_status is None else _status(previous_status)),
            status=None if status is None else _status(status),
            caused_by_event_ids=_string_array(
                value.get("caused_by_event_ids", []), field="caused_by_event_ids"
            ),
            superseded_by=(
                None
                if superseded_value is None
                else MechanicRef.from_dict(_mapping(superseded_value, field="superseded_by"))
            ),
            note=_string(value.get("note", ""), field="mechanic event note"),
            event_hash=_text(value.get("event_hash"), field="mechanic event_hash"),
        )


_ALLOWED_STATUS_TRANSITIONS: dict[MechanicStatus, frozenset[MechanicStatus]] = {
    MechanicStatus.PROVISIONAL: frozenset(
        {
            MechanicStatus.SUPPORTED,
            MechanicStatus.STABLE_WITHIN_SCOPE,
            MechanicStatus.STRESSED,
            MechanicStatus.REOPENED,
            MechanicStatus.REJECTED_OR_SUPERSEDED,
        }
    ),
    MechanicStatus.SUPPORTED: frozenset(
        {
            MechanicStatus.STABLE_WITHIN_SCOPE,
            MechanicStatus.STRESSED,
            MechanicStatus.REOPENED,
            MechanicStatus.REJECTED_OR_SUPERSEDED,
        }
    ),
    MechanicStatus.STABLE_WITHIN_SCOPE: frozenset(
        {
            MechanicStatus.STRESSED,
            MechanicStatus.REOPENED,
            MechanicStatus.REJECTED_OR_SUPERSEDED,
        }
    ),
    MechanicStatus.STRESSED: frozenset(
        {
            MechanicStatus.SUPPORTED,
            MechanicStatus.RECURRING_UNRESOLVED,
            MechanicStatus.REOPENED,
            MechanicStatus.REJECTED_OR_SUPERSEDED,
        }
    ),
    MechanicStatus.RECURRING_UNRESOLVED: frozenset(
        {MechanicStatus.REOPENED, MechanicStatus.REJECTED_OR_SUPERSEDED}
    ),
    MechanicStatus.REOPENED: frozenset(
        {
            MechanicStatus.PROVISIONAL,
            MechanicStatus.SUPPORTED,
            MechanicStatus.STABLE_WITHIN_SCOPE,
            MechanicStatus.STRESSED,
            MechanicStatus.RECURRING_UNRESOLVED,
            MechanicStatus.REJECTED_OR_SUPERSEDED,
        }
    ),
    MechanicStatus.REJECTED_OR_SUPERSEDED: frozenset(),
}


class MechanicLedger:
    """Rebuildable mechanic state with strict competition bounds."""

    def __init__(
        self,
        *,
        game_scope: str,
        budget: MechanicLedgerBudget | None = None,
        events: Iterable[MechanicLedgerEvent] = (),
    ) -> None:
        self.game_scope = _text(game_scope, field="ledger game_scope")
        self.budget = budget or MechanicLedgerBudget()
        self._events: list[MechanicLedgerEvent] = []
        self._event_ids: set[str] = set()
        self._evidence_ids: dict[str, tuple[MechanicRef, MechanicEvidence]] = {}
        self._versions: dict[MechanicRef, MechanicVersion] = {}
        self._current: dict[str, MechanicRef] = {}
        self._statuses: dict[MechanicRef, MechanicStatus] = {}
        self._evidence: dict[MechanicRef, list[MechanicEvidence]] = {}
        self._event_ids_by_ref: dict[MechanicRef, list[str]] = {}
        self._superseded_by: dict[MechanicRef, MechanicRef] = {}
        self._view_cache: dict[MechanicRef, MechanicView] = {}
        for event in events:
            self.apply(event)

    @property
    def events(self) -> tuple[MechanicLedgerEvent, ...]:
        return tuple(self._events)

    @property
    def tail_hash(self) -> str | None:
        return self._events[-1].event_hash if self._events else None

    def get(self, ref: MechanicRef) -> MechanicView:
        cached = self._view_cache.get(ref)
        if cached is not None:
            return cached
        try:
            version = self._versions[ref]
        except KeyError as error:
            raise MechanicsError(
                f"unknown mechanic version: {ref.mechanic_id}@{ref.version}"
            ) from error
        view = MechanicView(
            version=version,
            status=self._statuses[ref],
            evidence_receipt_ids=tuple(item.receipt_id for item in self._evidence[ref]),
            channel_evidence=self._channel_summaries(ref),
            event_ids=tuple(self._event_ids_by_ref[ref]),
            superseded_by=self._superseded_by.get(ref),
        )
        self._view_cache[ref] = view
        return view

    def current_ref(self, mechanic_id: str) -> MechanicRef:
        try:
            return self._current[mechanic_id]
        except KeyError as error:
            raise MechanicsError(f"unknown mechanic_id: {mechanic_id}") from error

    def current(self, mechanic_id: str) -> MechanicView:
        return self.get(self.current_ref(mechanic_id))

    def records(self, *, current_only: bool = False) -> tuple[MechanicView, ...]:
        refs = self._current.values() if current_only else self._versions.keys()
        return tuple(self.get(ref) for ref in sorted(refs))

    def active(self) -> tuple[MechanicView, ...]:
        return tuple(item for item in self.records(current_only=True) if item.is_live)

    def applicable(self, action: ActionName, context: MechanicContext) -> tuple[MechanicView, ...]:
        if context.game_scope != self.game_scope:
            raise MechanicsError("mechanic context belongs to a different opaque game scope")
        selected = [
            item
            for item in self.active()
            if item.is_prediction_eligible
            and item.version.action is action
            and item.version.scope.matches(context)
        ]
        return tuple(
            sorted(
                selected,
                key=lambda item: (
                    -item.version.specificity,
                    item.ref.mechanic_id,
                    item.ref.version,
                ),
            )
        )

    def quarantined_for(self, context: MechanicContext) -> tuple[MechanicView, ...]:
        """Return prior-level/layout mechanics retained but inapplicable here."""

        if context.game_scope != self.game_scope:
            raise MechanicsError("mechanic context belongs to a different opaque game scope")
        return tuple(
            item
            for item in self.active()
            if item.version.scope.ceiling is ScopeCeiling.LEVEL
            and item.version.scope.game_scope == context.game_scope
            and item.version.scope.level_scope != context.level_scope
        )

    def open(
        self,
        *,
        action: ActionName,
        scope: MechanicScope,
        consequence: ConsequenceVector,
        composition_mode: CompositionMode,
        created_step: int,
        created_from_event_ids: Iterable[str],
        provenance: EvidenceProvenance,
        mechanic_id: str | None = None,
        priority: int = 0,
        note: str = "",
    ) -> MechanicView:
        identifier = mechanic_id or self._next_mechanic_id()
        ref = MechanicRef(identifier, 1)
        version = MechanicVersion(
            ref=ref,
            action=action,
            scope=scope,
            consequence=consequence,
            composition_mode=composition_mode,
            created_step=created_step,
            created_from_event_ids=tuple(created_from_event_ids),
            provenance=provenance,
            priority=priority,
            note=note,
        )
        self.declare(version)
        return self.get(ref)

    def declare(self, version: MechanicVersion) -> MechanicView:
        self._preflight_version(version)
        self._require_event_capacity(1)
        event = self._new_event(
            event_type=MechanicEventType.VERSION_DECLARED,
            ref=version.ref,
            occurred_step=version.created_step,
            version=version,
            status=MechanicStatus.PROVISIONAL,
            caused_by_event_ids=version.created_from_event_ids,
            note=version.note,
        )
        self.apply(event)
        return self.get(version.ref)

    def revise(
        self,
        ref: MechanicRef,
        *,
        created_step: int,
        created_from_event_ids: Iterable[str],
        consequence: ConsequenceVector | None = None,
        scope: MechanicScope | None = None,
        composition_mode: CompositionMode | None = None,
        provenance: EvidenceProvenance = EvidenceProvenance.DERIVED_THIS_GAME,
        priority: int | None = None,
        note: str = "",
    ) -> MechanicView:
        current = self.get(ref)
        if self._current.get(ref.mechanic_id) != ref or not current.is_live:
            raise MechanicsError("only the current live mechanic version may be revised")
        new_ref = MechanicRef(ref.mechanic_id, ref.version + 1)
        version = MechanicVersion(
            ref=new_ref,
            action=current.version.action,
            scope=scope or current.version.scope,
            consequence=consequence or current.version.consequence,
            composition_mode=composition_mode or current.version.composition_mode,
            created_step=created_step,
            created_from_event_ids=tuple(created_from_event_ids),
            provenance=provenance,
            parent_ref=ref,
            priority=current.version.priority if priority is None else priority,
            note=note,
        )
        self._preflight_version(version)
        if len(self._versions) >= self.budget.max_versions:
            raise MechanicsError("mechanic semantic-version bound reached")
        self._require_event_capacity(2)
        self.transition_status(
            ref,
            MechanicStatus.REJECTED_OR_SUPERSEDED,
            occurred_step=created_step,
            caused_by_event_ids=version.created_from_event_ids,
            superseded_by=new_ref,
            note="superseded by semantic revision",
            _capacity_checked=True,
        )
        self.declare(version)
        return self.get(new_ref)

    def record_evidence(self, ref: MechanicRef, evidence: MechanicEvidence) -> MechanicView:
        view = self.get(ref)
        if not view.is_live or self._current.get(ref.mechanic_id) != ref:
            raise MechanicsError("evidence may be recorded only against a current live version")
        duplicate = self._evidence_ids.get(evidence.receipt_id)
        if duplicate is not None:
            if duplicate == (ref, evidence):
                return self.get(ref)
            raise MechanicsError(f"duplicate mechanic evidence receipt_id: {evidence.receipt_id}")
        if evidence.kind is MechanicEvidenceKind.SUPPORT:
            unsupported = set(evidence.channels) - set(view.version.consequence.known_channels)
            if unsupported:
                names = ", ".join(
                    channel.value for channel in sorted(unsupported, key=CHANNEL_ORDER.index)
                )
                raise MechanicsError(f"support evidence targets unknown mechanic channels: {names}")
        target = self._status_after_evidence(ref, evidence)
        status_change = target is not view.status
        self._require_event_capacity(2 if status_change else 1)
        event = self._new_event(
            event_type=MechanicEventType.EVIDENCE_RECORDED,
            ref=ref,
            occurred_step=evidence.observed_step,
            evidence=evidence,
            caused_by_event_ids=evidence.source_event_ids,
        )
        self.apply(event)
        if status_change:
            self.transition_status(
                ref,
                target,
                occurred_step=evidence.observed_step,
                caused_by_event_ids=evidence.source_event_ids,
                note=f"status derived from {evidence.kind.value} evidence",
                _capacity_checked=True,
            )
        return self.get(ref)

    def confirm_passively(
        self,
        ref: MechanicRef,
        *,
        channels: Iterable[ConsequenceChannel],
        source_event_ids: Iterable[str],
        context_key: str,
        observed_step: int,
        receipt_id: str,
        dimensions: Iterable[SupportDimension] = (
            SupportDimension.OCCURRENCE,
            SupportDimension.MAGNITUDE,
        ),
    ) -> MechanicView:
        return self.record_evidence(
            ref,
            MechanicEvidence(
                receipt_id=receipt_id,
                kind=MechanicEvidenceKind.SUPPORT,
                confirmation_mode=ConfirmationMode.PASSIVE,
                provenance=EvidenceProvenance.OBSERVED_THIS_GAME,
                source_event_ids=tuple(source_event_ids),
                channels=tuple(channels),
                context_key=context_key,
                observed_step=observed_step,
                support_dimensions=tuple(dimensions),
                summary="passive consequence confirmation",
            ),
        )

    def confirm_transfer(
        self,
        ref: MechanicRef,
        *,
        channels: Iterable[ConsequenceChannel],
        source_event_ids: Iterable[str],
        context_key: str,
        observed_step: int,
        receipt_id: str,
    ) -> MechanicView:
        return self.record_evidence(
            ref,
            MechanicEvidence(
                receipt_id=receipt_id,
                kind=MechanicEvidenceKind.SUPPORT,
                confirmation_mode=ConfirmationMode.TRANSFER,
                provenance=EvidenceProvenance.OBSERVED_THIS_GAME,
                source_event_ids=tuple(source_event_ids),
                channels=tuple(channels),
                context_key=context_key,
                observed_step=observed_step,
                support_dimensions=(SupportDimension.OCCURRENCE, SupportDimension.MAGNITUDE),
                summary="cross-level transfer confirmation",
            ),
        )

    def reopen(
        self,
        ref: MechanicRef,
        *,
        occurred_step: int,
        caused_by_event_ids: Iterable[str],
        note: str = "",
    ) -> MechanicView:
        return self.transition_status(
            ref,
            MechanicStatus.REOPENED,
            occurred_step=occurred_step,
            caused_by_event_ids=caused_by_event_ids,
            note=note,
        )

    def reject(
        self,
        ref: MechanicRef,
        *,
        occurred_step: int,
        caused_by_event_ids: Iterable[str],
        note: str = "",
    ) -> MechanicView:
        return self.transition_status(
            ref,
            MechanicStatus.REJECTED_OR_SUPERSEDED,
            occurred_step=occurred_step,
            caused_by_event_ids=caused_by_event_ids,
            note=note,
        )

    def transition_status(
        self,
        ref: MechanicRef,
        status: MechanicStatus,
        *,
        occurred_step: int,
        caused_by_event_ids: Iterable[str],
        superseded_by: MechanicRef | None = None,
        note: str = "",
        _capacity_checked: bool = False,
    ) -> MechanicView:
        current = self.get(ref).status
        if status not in _ALLOWED_STATUS_TRANSITIONS[current]:
            raise MechanicsError(
                f"cannot change mechanic status from {current.value} to {status.value}"
            )
        if not _capacity_checked:
            self._require_event_capacity(1)
        event = self._new_event(
            event_type=MechanicEventType.STATUS_CHANGED,
            ref=ref,
            occurred_step=occurred_step,
            previous_status=current,
            status=status,
            caused_by_event_ids=tuple(caused_by_event_ids),
            superseded_by=superseded_by,
            note=note,
        )
        self.apply(event)
        return self.get(ref)

    def apply(self, event: MechanicLedgerEvent) -> None:
        """Validate and append one event, then update replaceable indices."""

        if len(self._events) >= self.budget.max_events:
            raise MechanicsError("mechanic ledger event bound reached")
        if event.sequence != len(self._events):
            raise MechanicsError("mechanic event sequence is not contiguous")
        expected_previous = self.tail_hash
        if event.previous_event_hash != expected_previous:
            raise MechanicsError("mechanic event previous hash does not match the ledger tail")
        if event.event_id in self._event_ids:
            raise MechanicsError(f"duplicate mechanic event_id: {event.event_id}")
        if event.event_type is MechanicEventType.VERSION_DECLARED:
            assert event.version is not None
            self._apply_version(event.version)
        elif event.event_type is MechanicEventType.EVIDENCE_RECORDED:
            assert event.evidence is not None
            self._apply_evidence(event.ref, event.evidence)
        else:
            assert event.previous_status is not None
            assert event.status is not None
            self._apply_status(event)
        self._events.append(event)
        self._event_ids.add(event.event_id)
        self._event_ids_by_ref[event.ref].append(event.event_id)
        # Views are immutable projections.  Invalidate only the mechanic touched
        # by this accepted event after every backing index, including event IDs,
        # has been updated.
        self._view_cache.pop(event.ref, None)

    def _apply_version(self, version: MechanicVersion) -> None:
        self._preflight_version(version)
        if len(self._versions) >= self.budget.max_versions:
            raise MechanicsError("mechanic semantic-version bound reached")
        self._versions[version.ref] = version
        self._current[version.ref.mechanic_id] = version.ref
        self._statuses[version.ref] = MechanicStatus.PROVISIONAL
        self._evidence[version.ref] = []
        self._event_ids_by_ref[version.ref] = []

    def _apply_evidence(self, ref: MechanicRef, evidence: MechanicEvidence) -> None:
        view = self.get(ref)
        if not view.is_live or self._current.get(ref.mechanic_id) != ref:
            raise MechanicsError("evidence event targets a non-current mechanic version")
        duplicate = self._evidence_ids.get(evidence.receipt_id)
        if duplicate is not None:
            raise MechanicsError(f"duplicate mechanic evidence receipt_id: {evidence.receipt_id}")
        if evidence.kind is MechanicEvidenceKind.SUPPORT and (
            set(evidence.channels) - set(view.version.consequence.known_channels)
        ):
            raise MechanicsError("support evidence targets an unknown consequence channel")
        self._evidence[ref].append(evidence)
        self._evidence_ids[evidence.receipt_id] = (ref, evidence)

    def _apply_status(self, event: MechanicLedgerEvent) -> None:
        current = self.get(event.ref).status
        assert event.previous_status is not None
        assert event.status is not None
        if current is not event.previous_status:
            raise MechanicsError("stale mechanic status transition")
        if event.status not in _ALLOWED_STATUS_TRANSITIONS[current]:
            raise MechanicsError(
                f"cannot change mechanic status from {current.value} to {event.status.value}"
            )
        self._statuses[event.ref] = event.status
        if event.superseded_by is not None:
            if event.superseded_by.mechanic_id != event.ref.mechanic_id:
                raise MechanicsError("superseding mechanic must retain mechanic_id")
            if event.superseded_by.version != event.ref.version + 1:
                raise MechanicsError("superseding mechanic version must be the immediate successor")
            self._superseded_by[event.ref] = event.superseded_by

    def _preflight_version(self, version: MechanicVersion) -> None:
        if version.ref in self._versions:
            raise MechanicsError(
                f"duplicate mechanic version: {version.ref.mechanic_id}@{version.ref.version}"
            )
        if version.scope.ceiling is not ScopeCeiling.GENERIC:
            if version.scope.game_scope != self.game_scope:
                raise MechanicsError("mechanic scope belongs to a different opaque game")
        parent = version.parent_ref
        if parent is None:
            if version.ref.version != 1:
                raise MechanicsError("initial mechanic version must be version 1")
            if version.ref.mechanic_id in self._current:
                raise MechanicsError("an existing mechanic_id requires a revision parent")
            if len(self.active()) >= self.budget.max_active_mechanics:
                raise MechanicsError("active mechanic bound reached")
            return
        if parent not in self._versions:
            raise MechanicsError("mechanic revision parent is unknown")
        if self._current.get(parent.mechanic_id) != parent:
            raise MechanicsError("mechanic revision parent is not current")
        if version.ref.version != parent.version + 1:
            raise MechanicsError("mechanic revisions must increment the version by one")

    def _status_after_evidence(
        self, ref: MechanicRef, evidence: MechanicEvidence
    ) -> MechanicStatus:
        current = self.get(ref).status
        all_evidence = (*self._evidence[ref], evidence)
        if evidence.kind is not MechanicEvidenceKind.SUPPORT:
            contexts = {
                item.context_key
                for item in all_evidence
                if item.kind is not MechanicEvidenceKind.SUPPORT
            }
            if current is MechanicStatus.RECURRING_UNRESOLVED:
                return current
            if current is MechanicStatus.STRESSED and len(contexts) >= 2:
                return MechanicStatus.RECURRING_UNRESOLVED
            return MechanicStatus.STRESSED
        if current in {
            MechanicStatus.STRESSED,
            MechanicStatus.RECURRING_UNRESOLVED,
        }:
            return current
        known = self._versions[ref].consequence.known_channels
        occurrence: list[int] = []
        magnitude: list[int] = []
        modes: set[ConfirmationMode] = set()
        for channel in known:
            channel_support = [
                item
                for item in all_evidence
                if item.kind is MechanicEvidenceKind.SUPPORT and channel in item.channels
            ]
            occurrence.append(
                len(
                    {
                        item.context_key
                        for item in channel_support
                        if SupportDimension.OCCURRENCE in item.support_dimensions
                    }
                )
            )
            magnitude.append(
                len(
                    {
                        item.context_key
                        for item in channel_support
                        if SupportDimension.MAGNITUDE in item.support_dimensions
                    }
                )
            )
            modes.update(item.confirmation_mode for item in channel_support)
        if (
            occurrence
            and min(occurrence) >= 3
            and min(magnitude) >= 3
            and modes & {ConfirmationMode.PASSIVE, ConfirmationMode.TRANSFER}
        ):
            return MechanicStatus.STABLE_WITHIN_SCOPE
        if occurrence and min(occurrence) >= 2 and min(magnitude) >= 2:
            return MechanicStatus.SUPPORTED
        return current

    def _channel_summaries(self, ref: MechanicRef) -> tuple[ChannelEvidenceSummary, ...]:
        evidence = self._evidence[ref]
        summaries: list[ChannelEvidenceSummary] = []
        limit = self.budget.max_contexts_per_channel
        for channel in CHANNEL_ORDER:
            support = [
                item
                for item in evidence
                if item.kind is MechanicEvidenceKind.SUPPORT and channel in item.channels
            ]
            occurrence = {
                item.context_key
                for item in support
                if SupportDimension.OCCURRENCE in item.support_dimensions
            }
            magnitude = {
                item.context_key
                for item in support
                if SupportDimension.MAGNITUDE in item.support_dimensions
            }
            deliberate = {
                item.context_key
                for item in support
                if item.confirmation_mode is ConfirmationMode.DELIBERATE
            }
            passive = {
                item.context_key
                for item in support
                if item.confirmation_mode is ConfirmationMode.PASSIVE
            }
            transfer = {
                item.context_key
                for item in support
                if item.confirmation_mode is ConfirmationMode.TRANSFER
            }
            contradictions = {
                item.context_key
                for item in evidence
                if item.kind is MechanicEvidenceKind.CONTRADICTION and channel in item.channels
            }
            residuals = {
                item.context_key
                for item in evidence
                if item.kind is MechanicEvidenceKind.RESIDUAL and channel in item.channels
            }
            all_contexts = deliberate | passive | transfer | contradictions | residuals
            summaries.append(
                ChannelEvidenceSummary(
                    channel=channel,
                    occurrence_support_count=len(occurrence),
                    magnitude_support_count=len(magnitude),
                    contradiction_count=len(contradictions),
                    residual_count=len(residuals),
                    deliberate_contexts=tuple(sorted(deliberate)[:limit]),
                    passive_contexts=tuple(sorted(passive)[:limit]),
                    transfer_contexts=tuple(sorted(transfer)[:limit]),
                    contradiction_contexts=tuple(sorted(contradictions | residuals)[:limit]),
                    contexts_truncated=len(all_contexts) > limit,
                )
            )
        return tuple(summaries)

    def _new_event(
        self,
        *,
        event_type: MechanicEventType,
        ref: MechanicRef,
        occurred_step: int,
        version: MechanicVersion | None = None,
        evidence: MechanicEvidence | None = None,
        previous_status: MechanicStatus | None = None,
        status: MechanicStatus | None = None,
        caused_by_event_ids: tuple[str, ...] = (),
        superseded_by: MechanicRef | None = None,
        note: str = "",
    ) -> MechanicLedgerEvent:
        sequence = len(self._events)
        return MechanicLedgerEvent(
            event_id=self._next_event_id(),
            sequence=sequence,
            event_type=event_type,
            ref=ref,
            occurred_step=occurred_step,
            previous_event_hash=self.tail_hash,
            version=version,
            evidence=evidence,
            previous_status=previous_status,
            status=status,
            caused_by_event_ids=caused_by_event_ids,
            superseded_by=superseded_by,
            note=note,
        )

    def _next_mechanic_id(self) -> str:
        ordinal = len(self._current) + 1
        while True:
            candidate = f"M-{ordinal:04d}"
            if candidate not in self._current:
                return candidate
            ordinal += 1

    def _next_event_id(self) -> str:
        ordinal = len(self._events) + 1
        while True:
            candidate = f"mechanic-event:{ordinal:08d}"
            if candidate not in self._event_ids:
                return candidate
            ordinal += 1

    def _require_event_capacity(self, count: int) -> None:
        if len(self._events) + count > self.budget.max_events:
            raise MechanicsError("mechanic ledger event bound would be exceeded")

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "schema": LEDGER_SCHEMA,
            "game_scope": self.game_scope,
            "budget": self.budget.to_dict(),
            "events": [event.to_dict() for event in self._events],
            "records": [item.to_dict() for item in self.records()],
            "tail_hash": self.tail_hash,
        }

    def compact_dict(self) -> dict[str, JSONValue]:
        """Return the smallest authoritative snapshot; views rebuild on restore."""

        return {
            "schema": COMPACT_LEDGER_SCHEMA,
            "game_scope": self.game_scope,
            "budget": self.budget.to_dict(),
            "events": [event.to_dict() for event in self._events],
            "tail_hash": self.tail_hash,
        }

    def canonical_snapshot(self, *, compact: bool = True) -> str:
        return canonical_json(self.compact_dict() if compact else self.to_dict())

    def compact_bytes(self) -> bytes:
        return canonical_bytes(self.compact_dict())

    @classmethod
    def from_compact_bytes(cls, data: bytes, *, expected_game_scope: str) -> Self:
        parsed = parse_json_bytes(data)
        if not isinstance(parsed, dict):
            raise MechanicsError("compact mechanic ledger must be a JSON object")
        return cls.from_dict(
            cast(Mapping[str, object], parsed), expected_game_scope=expected_game_scope
        )

    @classmethod
    def from_dict(cls, value: Mapping[str, object], *, expected_game_scope: str) -> Self:
        schema = value.get("schema")
        if schema not in {LEDGER_SCHEMA, COMPACT_LEDGER_SCHEMA}:
            raise MechanicsError("unsupported mechanic ledger schema")
        game_scope = _text(value.get("game_scope"), field="ledger game_scope")
        if game_scope != _text(expected_game_scope, field="expected game_scope"):
            raise MechanicsError("mechanic ledger belongs to a different opaque game scope")
        budget = MechanicLedgerBudget.from_dict(
            _mapping(value.get("budget"), field="mechanic ledger budget")
        )
        raw_events = value.get("events")
        if not isinstance(raw_events, list) or not all(
            isinstance(item, Mapping) for item in raw_events
        ):
            raise MechanicsError("mechanic ledger events must be an array of objects")
        if len(raw_events) > budget.max_events:
            raise MechanicsError("serialized mechanic ledger exceeds its event bound")
        ledger = cls(
            game_scope=game_scope,
            budget=budget,
            events=(MechanicLedgerEvent.from_dict(item) for item in raw_events),
        )
        if value.get("tail_hash") != ledger.tail_hash:
            raise MechanicsError("serialized mechanic ledger tail hash is invalid")
        if schema == LEDGER_SCHEMA:
            supplied = normalize_json(value.get("records"))
            replayed = normalize_json([item.to_dict() for item in ledger.records()])
            if supplied != replayed:
                raise MechanicsError("serialized mechanic views disagree with replayed events")
        return ledger


def _event_type(value: object) -> MechanicEventType:
    if not isinstance(value, str):
        raise MechanicsError("mechanic event type must be a string")
    try:
        return MechanicEventType(value)
    except ValueError as error:
        raise MechanicsError(f"unsupported mechanic event type: {value!r}") from error


def _status(value: object) -> MechanicStatus:
    if not isinstance(value, str):
        raise MechanicsError("mechanic status must be a string")
    try:
        return MechanicStatus(value)
    except ValueError as error:
        raise MechanicsError(f"unsupported mechanic status: {value!r}") from error


def _mapping(value: object, *, field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or not all(isinstance(key, str) for key in value):
        raise MechanicsError(f"{field} must be an object")
    return value


def _text(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise MechanicsError(f"{field} must be a non-empty string")
    return value


def _string(value: object, *, field: str) -> str:
    if not isinstance(value, str):
        raise MechanicsError(f"{field} must be a string")
    return value


def _integer(value: object, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise MechanicsError(f"{field} must be an integer")
    return value


def _non_negative(value: object, *, field: str) -> int:
    result = _integer(value, field=field)
    if result < 0:
        raise MechanicsError(f"{field} must be non-negative")
    return result


def _strings(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(sorted({_text(value, field="event source ID") for value in values}))


def _string_array(value: object, *, field: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise MechanicsError(f"{field} must be an array")
    return _strings(_text(item, field=field) for item in value)


__all__ = [
    "COMPACT_LEDGER_SCHEMA",
    "EVENT_SCHEMA",
    "LEDGER_SCHEMA",
    "MechanicEventType",
    "MechanicLedger",
    "MechanicLedgerEvent",
]
