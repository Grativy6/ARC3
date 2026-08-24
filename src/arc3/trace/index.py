"""Disposable deterministic indices rebuilt solely from immutable events."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field

from arc3.errors import TraceIntegrityError
from arc3.types import JSONValue

from .authority import authoritative_events
from .canonical import canonical_json
from .schema import TraceEvent


@dataclass(frozen=True, slots=True)
class HypothesisLineage:
    """Rebuildable lifecycle view that never discards rejected candidates."""

    hypothesis_id: str
    status: str
    event_ids: tuple[str, ...]
    support_event_ids: tuple[str, ...]
    contradiction_event_ids: tuple[str, ...]
    parent_ids: tuple[str, ...]
    superseded_by: str | None
    scope: str | None

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "hypothesis_id": self.hypothesis_id,
            "status": self.status,
            "event_ids": list(self.event_ids),
            "support_event_ids": list(self.support_event_ids),
            "contradiction_event_ids": list(self.contradiction_event_ids),
            "parent_ids": list(self.parent_ids),
            "superseded_by": self.superseded_by,
            "scope": self.scope,
        }


@dataclass(slots=True)
class _MutableHypothesis:
    hypothesis_id: str
    status: str = "candidate"
    event_ids: list[str] = field(default_factory=list)
    support_event_ids: list[str] = field(default_factory=list)
    contradiction_event_ids: list[str] = field(default_factory=list)
    parent_ids: list[str] = field(default_factory=list)
    superseded_by: str | None = None
    scope: str | None = None

    def freeze(self) -> HypothesisLineage:
        return HypothesisLineage(
            hypothesis_id=self.hypothesis_id,
            status=self.status,
            event_ids=tuple(self.event_ids),
            support_event_ids=tuple(self.support_event_ids),
            contradiction_event_ids=tuple(self.contradiction_event_ids),
            parent_ids=tuple(self.parent_ids),
            superseded_by=self.superseded_by,
            scope=self.scope,
        )


@dataclass(frozen=True, slots=True)
class DerivedIndex:
    """A canonical event lookup/index snapshot with no independent authority."""

    event_order: tuple[str, ...]
    event_offsets: dict[str, int]
    events_by_type: dict[str, tuple[str, ...]]
    events_by_step: dict[str, tuple[str, ...]]
    frame_events: dict[str, tuple[str, ...]]
    hypotheses: dict[str, HypothesisLineage]

    def hypothesis(self, hypothesis_id: str) -> HypothesisLineage | None:
        """Return any candidate including rejected or superseded records."""

        return self.hypotheses.get(hypothesis_id)

    def rejected_hypotheses(self) -> tuple[HypothesisLineage, ...]:
        """Return rejected records in stable identifier order."""

        return tuple(
            self.hypotheses[key]
            for key in sorted(self.hypotheses)
            if self.hypotheses[key].status == "rejected"
        )

    def to_dict(self) -> dict[str, JSONValue]:
        """Return a deterministic, serializable derived view."""

        return {
            "event_order": list(self.event_order),
            "event_offsets": dict(sorted(self.event_offsets.items())),
            "events_by_type": {
                key: list(value) for key, value in sorted(self.events_by_type.items())
            },
            "events_by_step": {
                key: list(value) for key, value in sorted(self.events_by_step.items())
            },
            "frame_events": {key: list(value) for key, value in sorted(self.frame_events.items())},
            "hypotheses": {key: value.to_dict() for key, value in sorted(self.hypotheses.items())},
        }

    def canonical_snapshot(self) -> str:
        """Serialize for reproducibility comparison or disposable persistence."""

        return canonical_json(self.to_dict())


def _string_list(value: JSONValue | None, *, field_name: str, event_id: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise TraceIntegrityError(f"{event_id} {field_name} must contain only strings")
    return [item for item in value if isinstance(item, str)]


def _update_hypothesis(
    registry: dict[str, _MutableHypothesis],
    event: TraceEvent,
) -> None:
    raw_id = event.payload.get("hypothesis_id")
    if not isinstance(raw_id, str) or not raw_id:
        raise TraceIntegrityError(f"{event.event_type} event lacks a hypothesis_id")
    record = registry.setdefault(raw_id, _MutableHypothesis(raw_id))
    record.event_ids.append(event.event_id)
    if event.event_type == "hypothesis.created":
        status = event.payload.get("status", "candidate")
        if not isinstance(status, str):
            raise TraceIntegrityError("hypothesis created status must be a string")
        record.status = status
        record.parent_ids = _string_list(
            event.payload.get("parent_ids"), field_name="parent_ids", event_id=event.event_id
        )
        raw_scope = event.payload.get("scope", event.scope)
        if raw_scope is not None and not isinstance(raw_scope, str):
            raise TraceIntegrityError("hypothesis scope must be a string or null")
        record.scope = raw_scope
    elif event.event_type == "hypothesis.supported":
        record.status = "active"
        record.support_event_ids.extend(
            _string_list(
                event.payload.get("evidence_event_ids"),
                field_name="evidence_event_ids",
                event_id=event.event_id,
            )
            or [event.event_id]
        )
    elif event.event_type == "hypothesis.contradicted":
        record.contradiction_event_ids.extend(
            _string_list(
                event.payload.get("evidence_event_ids"),
                field_name="evidence_event_ids",
                event_id=event.event_id,
            )
            or [event.event_id]
        )
    elif event.event_type == "hypothesis.narrowed":
        record.status = "narrowed"
    elif event.event_type == "hypothesis.rejected":
        record.status = "rejected"
    elif event.event_type == "hypothesis.reopened":
        status = event.payload.get("new_status", "candidate")
        if not isinstance(status, str):
            raise TraceIntegrityError("hypothesis reopened new_status must be a string")
        record.status = status
        record.contradiction_event_ids.extend(
            _string_list(
                event.payload.get("caused_by_event_ids"),
                field_name="caused_by_event_ids",
                event_id=event.event_id,
            )
        )
    elif event.event_type == "hypothesis.superseded":
        record.status = "superseded"
        superseded_by = event.payload.get("superseded_by")
        if not isinstance(superseded_by, str) or not superseded_by:
            raise TraceIntegrityError("hypothesis.superseded lacks superseded_by")
        record.superseded_by = superseded_by
    elif event.event_type == "hypothesis.scope_changed":
        scope = event.payload.get("new_scope")
        if not isinstance(scope, str) or not scope:
            raise TraceIntegrityError("hypothesis.scope_changed lacks new_scope")
        record.scope = scope


def rebuild_index(events: Iterable[TraceEvent]) -> DerivedIndex:
    """Deterministically derive all lookup state from ordered raw events."""

    event_order: list[str] = []
    event_offsets: dict[str, int] = {}
    by_type: defaultdict[str, list[str]] = defaultdict(list)
    by_step: defaultdict[str, list[str]] = defaultdict(list)
    frame_events: defaultdict[str, list[str]] = defaultdict(list)
    hypothesis_registry: dict[str, _MutableHypothesis] = {}

    for offset, event in enumerate(authoritative_events(tuple(events))):
        if event.event_id in event_offsets:
            raise TraceIntegrityError(
                f"duplicate event_id while rebuilding index: {event.event_id}"
            )
        event_order.append(event.event_id)
        event_offsets[event.event_id] = offset
        by_type[event.event_type].append(event.event_id)
        step_key = f"{event.run_id}/{event.episode_id}/{event.level_index}/{event.step_index}"
        by_step[step_key].append(event.event_id)
        if event.event_type.startswith("observation."):
            raw_frames = event.payload.get("frames", [])
            if isinstance(raw_frames, list):
                for raw_frame in raw_frames:
                    if isinstance(raw_frame, dict):
                        frame_hash = raw_frame.get("frame_hash")
                        if isinstance(frame_hash, str):
                            frame_events[frame_hash].append(event.event_id)
        if event.event_type.startswith("hypothesis."):
            _update_hypothesis(hypothesis_registry, event)

    return DerivedIndex(
        event_order=tuple(event_order),
        event_offsets=event_offsets,
        events_by_type={key: tuple(value) for key, value in sorted(by_type.items())},
        events_by_step={key: tuple(value) for key, value in sorted(by_step.items())},
        frame_events={key: tuple(value) for key, value in sorted(frame_events.items())},
        hypotheses={key: value.freeze() for key, value in sorted(hypothesis_registry.items())},
    )


# Readable downstream alias.
build_index = rebuild_index
