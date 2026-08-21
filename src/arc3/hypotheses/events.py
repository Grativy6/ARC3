"""Immutable event vocabulary for the derived hypothesis registry."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

from arc3.errors import HypothesisError
from arc3.types import HypothesisStatus, JSONValue

from .base import (
    EvidenceKind,
    EvidenceReceipt,
    HypothesisFamily,
    HypothesisPrediction,
    HypothesisScope,
    normalize_string_tuple,
    normalize_strings,
    require_int,
    require_non_negative_int,
    require_text,
)
from .families import HypothesisStatement, statement_from_dict

HYPOTHESIS_EVENT_SCHEMA = "arc3.hypothesis.event.v0.1"


class HypothesisEventType(StrEnum):
    """Trace-compatible lifecycle event names."""

    CREATED = "hypothesis.created"
    SUPPORTED = "hypothesis.supported"
    CONTRADICTED = "hypothesis.contradicted"
    NARROWED = "hypothesis.narrowed"
    REJECTED = "hypothesis.rejected"
    REOPENED = "hypothesis.reopened"
    SUPERSEDED = "hypothesis.superseded"
    SCOPE_CHANGED = "hypothesis.scope_changed"


_EXPECTED_STATUS: dict[HypothesisEventType, HypothesisStatus] = {
    HypothesisEventType.CREATED: HypothesisStatus.CANDIDATE,
    HypothesisEventType.SUPPORTED: HypothesisStatus.ACTIVE,
    HypothesisEventType.CONTRADICTED: HypothesisStatus.UNRESOLVED,
    HypothesisEventType.NARROWED: HypothesisStatus.NARROWED,
    HypothesisEventType.REJECTED: HypothesisStatus.REJECTED,
    HypothesisEventType.REOPENED: HypothesisStatus.CANDIDATE,
    HypothesisEventType.SUPERSEDED: HypothesisStatus.SUPERSEDED,
}


@dataclass(frozen=True, slots=True)
class HypothesisEvent:
    """One immutable input to the hypothesis-state fold."""

    event_id: str
    sequence: int
    event_type: HypothesisEventType
    hypothesis_id: str
    occurred_step: int
    status: HypothesisStatus
    previous_status: HypothesisStatus | None = None
    family: HypothesisFamily | None = None
    statement: HypothesisStatement | None = None
    scope: HypothesisScope | None = None
    scope_ref: str | None = None
    created_from_event_ids: tuple[str, ...] = ()
    caused_by_event_ids: tuple[str, ...] = ()
    predictions: tuple[HypothesisPrediction, ...] = ()
    receipt: EvidenceReceipt | None = None
    parent_ids: tuple[str, ...] = ()
    related_hypothesis_id: str | None = None
    conflict_ids: tuple[str, ...] = ()
    compatible_ids: tuple[str, ...] = ()
    invalidated_plan_ids: tuple[str, ...] = ()
    rank_delta: int = 0
    note: str = ""
    schema: str = HYPOTHESIS_EVENT_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != HYPOTHESIS_EVENT_SCHEMA:
            raise HypothesisError(f"unsupported hypothesis event schema: {self.schema!r}")
        require_text(self.event_id, field="hypothesis event_id")
        require_non_negative_int(self.sequence, field="hypothesis event sequence")
        require_text(self.hypothesis_id, field="hypothesis_id")
        require_non_negative_int(self.occurred_step, field="occurred_step")
        require_int(self.rank_delta, field="rank_delta")
        object.__setattr__(
            self,
            "created_from_event_ids",
            normalize_strings(self.created_from_event_ids, field="created_from_event_id"),
        )
        object.__setattr__(
            self,
            "caused_by_event_ids",
            normalize_strings(self.caused_by_event_ids, field="caused_by_event_id"),
        )
        object.__setattr__(
            self, "parent_ids", normalize_strings(self.parent_ids, field="parent_id")
        )
        object.__setattr__(
            self,
            "conflict_ids",
            normalize_strings(self.conflict_ids, field="conflict hypothesis_id"),
        )
        object.__setattr__(
            self,
            "compatible_ids",
            normalize_strings(self.compatible_ids, field="compatible hypothesis_id"),
        )
        object.__setattr__(
            self,
            "invalidated_plan_ids",
            normalize_strings(self.invalidated_plan_ids, field="invalidated plan_id"),
        )
        if set(self.conflict_ids) & set(self.compatible_ids):
            raise HypothesisError(
                "a hypothesis cannot declare the same peer compatible and conflicting"
            )
        prediction_ids = [prediction.prediction_id for prediction in self.predictions]
        if len(set(prediction_ids)) != len(prediction_ids):
            raise HypothesisError("prediction IDs must be unique within a hypothesis")
        if self.scope_ref is not None:
            require_text(self.scope_ref, field="scope_ref")
        if self.related_hypothesis_id is not None:
            require_text(self.related_hypothesis_id, field="related_hypothesis_id")
        if len(self.note) > 512:
            raise HypothesisError("hypothesis event note must not exceed 512 characters")
        self._validate_shape()

    def _validate_shape(self) -> None:
        expected = _EXPECTED_STATUS.get(self.event_type)
        if expected is not None and self.status is not expected:
            raise HypothesisError(
                f"{self.event_type.value} must produce status {expected.value}, not {self.status.value}"
            )
        if self.event_type is HypothesisEventType.CREATED:
            if self.previous_status is not None:
                raise HypothesisError("hypothesis.created cannot have a previous status")
            if self.family is None or self.statement is None or self.scope is None:
                raise HypothesisError("hypothesis.created requires family, statement, and scope")
            if self.statement.family is not self.family:
                raise HypothesisError("statement family does not match hypothesis family")
            if not self.created_from_event_ids:
                raise HypothesisError("hypothesis.created requires a source event ID")
            if self.receipt is not None:
                raise HypothesisError(
                    "hypothesis.created cannot carry an evidence transition receipt"
                )
            return

        if self.previous_status is None:
            raise HypothesisError(f"{self.event_type.value} requires previous_status")
        if self.event_type is HypothesisEventType.SCOPE_CHANGED:
            if self.scope is None:
                raise HypothesisError("hypothesis.scope_changed requires a new scope")
            if self.status is not self.previous_status:
                raise HypothesisError("a scope change cannot silently alter hypothesis status")
        elif self.family is not None or self.statement is not None:
            raise HypothesisError("only hypothesis.created may carry family or statement")

        evidence_types = {
            HypothesisEventType.SUPPORTED: {EvidenceKind.SUPPORT},
            HypothesisEventType.CONTRADICTED: {EvidenceKind.CONTRADICTION},
            HypothesisEventType.NARROWED: {
                EvidenceKind.CONTRADICTION,
                EvidenceKind.RESIDUAL,
            },
            HypothesisEventType.REJECTED: {
                EvidenceKind.CONTRADICTION,
                EvidenceKind.RESIDUAL,
            },
            HypothesisEventType.REOPENED: {
                EvidenceKind.CONTRADICTION,
                EvidenceKind.RESIDUAL,
            },
        }
        allowed_kinds = evidence_types.get(self.event_type)
        if allowed_kinds is not None:
            if self.receipt is None or self.receipt.kind not in allowed_kinds:
                allowed = ", ".join(sorted(kind.value for kind in allowed_kinds))
                raise HypothesisError(f"{self.event_type.value} requires evidence kind: {allowed}")
            if self.caused_by_event_ids != self.receipt.evidence_event_ids:
                raise HypothesisError("caused_by_event_ids must match the evidence receipt sources")
            if self.rank_delta != self.receipt.signed_rank_impact:
                raise HypothesisError("rank_delta must equal the receipt's signed rank impact")
        elif self.receipt is not None:
            raise HypothesisError(f"{self.event_type.value} cannot carry an evidence receipt")

        if (
            self.event_type
            in {
                HypothesisEventType.NARROWED,
                HypothesisEventType.SUPERSEDED,
            }
            and self.related_hypothesis_id is None
        ):
            raise HypothesisError(f"{self.event_type.value} requires a related hypothesis ID")
        if self.event_type is HypothesisEventType.REOPENED and not self.invalidated_plan_ids:
            # An empty signal is valid when no plan depended on the rule.  It is
            # still represented explicitly in serialization.
            object.__setattr__(self, "invalidated_plan_ids", ())

    def to_dict(self) -> dict[str, JSONValue]:
        """Return the complete event for checkpointing and deterministic rebuild."""

        return {
            "schema": self.schema,
            "event_id": self.event_id,
            "sequence": self.sequence,
            "event_type": self.event_type.value,
            "hypothesis_id": self.hypothesis_id,
            "occurred_step": self.occurred_step,
            "status": self.status.value,
            "previous_status": self.previous_status.value if self.previous_status else None,
            "family": self.family.value if self.family else None,
            "statement": self.statement.to_dict() if self.statement else None,
            "scope": self.scope.value if self.scope else None,
            "scope_ref": self.scope_ref,
            "created_from_event_ids": list(self.created_from_event_ids),
            "caused_by_event_ids": list(self.caused_by_event_ids),
            "predictions": [prediction.to_dict() for prediction in self.predictions],
            "receipt": self.receipt.to_dict() if self.receipt else None,
            "parent_ids": list(self.parent_ids),
            "related_hypothesis_id": self.related_hypothesis_id,
            "conflict_ids": list(self.conflict_ids),
            "compatible_ids": list(self.compatible_ids),
            "invalidated_plan_ids": list(self.invalidated_plan_ids),
            "rank_delta": self.rank_delta,
            "weight_kind": "uncalibrated_rank",
            "note": self.note,
        }

    def to_trace_payload(self) -> dict[str, JSONValue]:
        """Return a payload compatible with the immutable trace event vocabulary."""

        payload = self.to_dict()
        payload.pop("schema")
        payload.pop("event_type")
        payload["hypothesis_type"] = self.family.value if self.family else None
        payload["evidence_event_ids"] = list(self.caused_by_event_ids)
        if self.event_type is HypothesisEventType.NARROWED:
            payload["narrowed_to"] = self.related_hypothesis_id
        elif self.event_type is HypothesisEventType.SUPERSEDED:
            payload["superseded_by"] = self.related_hypothesis_id
        elif self.event_type is HypothesisEventType.SCOPE_CHANGED:
            payload["new_scope"] = self.scope.value if self.scope else None
        elif self.event_type is HypothesisEventType.REOPENED:
            payload["new_status"] = self.status.value
            payload["residual"] = self.receipt.summary if self.receipt else None
        return payload

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> HypothesisEvent:
        """Parse a checkpointed event without accepting ambiguous family inference."""

        try:
            event_type = HypothesisEventType(
                require_text(value.get("event_type"), field="hypothesis event_type")
            )
            status = HypothesisStatus(require_text(value.get("status"), field="status"))
        except ValueError as error:
            raise HypothesisError("unsupported hypothesis event type or status") from error

        previous_value = value.get("previous_status")
        try:
            previous = HypothesisStatus(previous_value) if isinstance(previous_value, str) else None
        except ValueError as error:
            raise HypothesisError("unsupported previous hypothesis status") from error

        family_value = value.get("family")
        try:
            family = HypothesisFamily(family_value) if isinstance(family_value, str) else None
        except ValueError as error:
            raise HypothesisError("unsupported hypothesis family") from error
        statement_value = value.get("statement")
        statement: HypothesisStatement | None = None
        if statement_value is not None:
            if family is None or not isinstance(statement_value, Mapping):
                raise HypothesisError("serialized statement requires a family and object value")
            statement = statement_from_dict(family, statement_value)

        scope_value = value.get("scope")
        try:
            scope = HypothesisScope(scope_value) if isinstance(scope_value, str) else None
        except ValueError as error:
            raise HypothesisError("unsupported hypothesis scope") from error
        predictions_value = value.get("predictions", [])
        if not isinstance(predictions_value, list) or not all(
            isinstance(item, Mapping) for item in predictions_value
        ):
            raise HypothesisError("predictions must be an array of objects")
        receipt_value = value.get("receipt")
        if receipt_value is not None and not isinstance(receipt_value, Mapping):
            raise HypothesisError("receipt must be an object or null")

        scope_ref = value.get("scope_ref")
        related = value.get("related_hypothesis_id")
        note = value.get("note", "")
        schema = value.get("schema", HYPOTHESIS_EVENT_SCHEMA)
        if scope_ref is not None and not isinstance(scope_ref, str):
            raise HypothesisError("scope_ref must be a string or null")
        if related is not None and not isinstance(related, str):
            raise HypothesisError("related_hypothesis_id must be a string or null")
        return cls(
            schema=require_text(schema, field="hypothesis event schema"),
            event_id=require_text(value.get("event_id"), field="hypothesis event_id"),
            sequence=require_non_negative_int(value.get("sequence"), field="sequence"),
            event_type=event_type,
            hypothesis_id=require_text(value.get("hypothesis_id"), field="hypothesis_id"),
            occurred_step=require_non_negative_int(
                value.get("occurred_step"), field="occurred_step"
            ),
            status=status,
            previous_status=previous,
            family=family,
            statement=statement,
            scope=scope,
            scope_ref=scope_ref,
            created_from_event_ids=normalize_string_tuple(
                value.get("created_from_event_ids", []), field="created_from_event_ids"
            ),
            caused_by_event_ids=normalize_string_tuple(
                value.get("caused_by_event_ids", []), field="caused_by_event_ids"
            ),
            predictions=tuple(HypothesisPrediction.from_dict(item) for item in predictions_value),
            receipt=EvidenceReceipt.from_dict(receipt_value) if receipt_value else None,
            parent_ids=normalize_string_tuple(value.get("parent_ids", []), field="parent_ids"),
            related_hypothesis_id=related,
            conflict_ids=normalize_string_tuple(
                value.get("conflict_ids", []), field="conflict_ids"
            ),
            compatible_ids=normalize_string_tuple(
                value.get("compatible_ids", []), field="compatible_ids"
            ),
            invalidated_plan_ids=normalize_string_tuple(
                value.get("invalidated_plan_ids", []), field="invalidated_plan_ids"
            ),
            rank_delta=require_int(value.get("rank_delta", 0), field="rank_delta"),
            note=require_text(note, field="note") if note else "",
        )
