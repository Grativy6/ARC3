"""Validated event envelopes for the ARC3 Trace v0.1 schema."""

from __future__ import annotations

import threading
import time
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Final

from arc3.errors import ARC3ValidationError, TraceIntegrityError
from arc3.types import JSONValue, RationaleCategory, StateScope

from .canonical import (
    normalize_json,
    require_array,
    require_object,
    require_sha256,
    require_string_sequence,
    sha256_json,
)

EVENT_SCHEMA: Final = "arc3.trace.event.v0.1"
CHECKPOINT_SCHEMA: Final = "arc3.checkpoint.v0.1"
SUMMARY_SCHEMA: Final = "arc3.trace.summary.v0.1"
MANIFEST_SCHEMA: Final = "arc3.trace.manifest.v0.1"
MIGRATION_SCHEMA: Final = "arc3.trace.migration.v0.1"

CORE_EVENT_TYPES: Final[frozenset[str]] = frozenset(
    {
        "run.started",
        "run.resumed",
        "run.completed",
        "run.aborted",
        "run.environment_fault",
        "run.checkpoint_written",
        "run.checkpoint_restored",
        "run.checkpoint_rejected",
        "observation.received",
        "observation.normalized",
        "observation.delta_measured",
        "observation.metadata_changed",
        "observation.parse_failed",
        "perception.component_detected",
        "perception.object_correspondence_proposed",
        "perception.object_correspondence_rejected",
        "perception.salience_computed",
        "hypothesis.created",
        "hypothesis.supported",
        "hypothesis.contradicted",
        "hypothesis.narrowed",
        "hypothesis.rejected",
        "hypothesis.reopened",
        "hypothesis.superseded",
        "hypothesis.scope_changed",
        "model.retrodiction_started",
        "model.retrodiction_completed",
        "model.rule_promoted",
        "model.rule_demoted",
        "simulation.plan_evaluated",
        "simulation.prediction_emitted",
        "goal.candidate_created",
        "goal.supported",
        "goal.contradicted",
        "goal.selected_for_planning",
        "goal.reopened",
        "goal.retired",
        "action.candidates_generated",
        "action.selected",
        "action.validated",
        "action.submitted",
        "action.rejected_by_environment",
        "action.fallback_used",
        "consequence.received",
        "consequence.matched_prediction",
        "consequence.mismatched_prediction",
        "consequence.progress_detected",
        "consequence.level_completed",
        "consequence.game_over",
        "evaluation.started",
        "evaluation.game_result",
        "evaluation.scorecard_received",
        "evaluation.completed",
        "evaluation.result_invalidated",
        "migration.completed",
    }
)

ALLOWED_SCOPES: Final[frozenset[str]] = frozenset(
    {item.value for item in StateScope} | {"run", "evaluation"}
)
EVALUATION_SURFACES: Final[frozenset[str]] = frozenset(
    {
        "synthetic",
        "local-public",
        "online-public",
        "Kaggle-public",
        "semi-private",
        "official-private",
    }
)
_FORBIDDEN_REASONING_KEYS: Final[frozenset[str]] = frozenset(
    {"chain_of_thought", "hidden_reasoning", "reasoning_trace", "scratchpad", "thoughts"}
)
_FORBIDDEN_SECRET_KEYS: Final[frozenset[str]] = frozenset(
    {
        "api_key",
        "arc_api_key",
        "authorization",
        "cookie",
        "credentials",
        "kaggle_token",
        "password",
        "secret",
    }
)
_EVENT_COUNTER_LOCK = threading.Lock()
_EVENT_COUNTER = 0


def utc_now() -> str:
    """Return a canonical UTC timestamp with microsecond precision."""

    return datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def new_event_id() -> str:
    """Create a practically sortable, process-unique receipt identifier."""

    global _EVENT_COUNTER
    with _EVENT_COUNTER_LOCK:
        _EVENT_COUNTER += 1
        counter = _EVENT_COUNTER
    return f"E-{time.time_ns():020d}-{counter:08x}-{uuid.uuid4().hex}"


def _require_text(data: Mapping[str, JSONValue], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value:
        raise ARC3ValidationError(f"{key} must be a non-empty string")
    return value


def _require_int(data: Mapping[str, JSONValue], key: str) -> int:
    value = data.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ARC3ValidationError(f"{key} must be an integer")
    return value


def _parse_timestamp(value: str, *, field_name: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ARC3ValidationError(f"{field_name} must be an ISO-8601 timestamp") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ARC3ValidationError(f"{field_name} must include a timezone")
    return parsed


def _contains_forbidden_reasoning(value: JSONValue) -> str | None:
    if isinstance(value, dict):
        for key, child in value.items():
            if key.lower() in _FORBIDDEN_REASONING_KEYS:
                return key
            nested = _contains_forbidden_reasoning(child)
            if nested is not None:
                return nested
    elif isinstance(value, list):
        for child in value:
            nested = _contains_forbidden_reasoning(child)
            if nested is not None:
                return nested
    return None


def _contains_secret(value: JSONValue) -> str | None:
    if isinstance(value, dict):
        for key, child in value.items():
            if key.lower() in _FORBIDDEN_SECRET_KEYS:
                return key
            nested = _contains_secret(child)
            if nested is not None:
                return nested
    elif isinstance(value, list):
        for child in value:
            nested = _contains_secret(child)
            if nested is not None:
                return nested
    return None


@dataclass(frozen=True, slots=True)
class SourceIdentity:
    """Identity of the component that supplied an event's source evidence."""

    kind: str
    version: str
    details: dict[str, JSONValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.kind or not self.version:
            raise ARC3ValidationError("source kind and version must be non-empty")
        normalized = normalize_json(self.details)
        if not isinstance(normalized, dict):  # pragma: no cover - field is statically a dict
            raise ARC3ValidationError("source details must be an object")
        object.__setattr__(self, "details", normalized)

    def to_dict(self) -> dict[str, JSONValue]:
        return {"kind": self.kind, "version": self.version, **self.details}

    @classmethod
    def from_dict(cls, value: JSONValue) -> SourceIdentity:
        data = require_object(value, field="source")
        kind = _require_text(data, "kind")
        version = _require_text(data, "version")
        return cls(
            kind=kind,
            version=version,
            details={k: v for k, v in data.items() if k not in {"kind", "version"}},
        )


@dataclass(frozen=True, slots=True)
class CodeIdentity:
    """First-party code and configuration identities active at event time."""

    git_commit: str
    config_hash: str
    details: dict[str, JSONValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.git_commit:
            raise ARC3ValidationError("git_commit must be non-empty")
        require_sha256(self.config_hash, field="config_hash")
        normalized = normalize_json(self.details)
        if not isinstance(normalized, dict):  # pragma: no cover - field is statically a dict
            raise ARC3ValidationError("code identity details must be an object")
        object.__setattr__(self, "details", normalized)

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "git_commit": self.git_commit,
            "config_hash": self.config_hash,
            **self.details,
        }

    @classmethod
    def from_dict(cls, value: JSONValue) -> CodeIdentity:
        data = require_object(value, field="code_identity")
        commit = _require_text(data, "git_commit")
        config_hash = _require_text(data, "config_hash")
        return cls(
            git_commit=commit,
            config_hash=config_hash,
            details={k: v for k, v in data.items() if k not in {"git_commit", "config_hash"}},
        )


def _validate_observation_payload(payload: dict[str, JSONValue]) -> None:
    frame_count = _require_int(payload, "frame_count")
    frames = require_array(payload.get("frames"), field="payload.frames")
    if frame_count < 0 or frame_count != len(frames):
        raise ARC3ValidationError("frame_count must equal the number of frame descriptors")
    for raw_frame in frames:
        frame = require_object(raw_frame, field="payload.frames[]")
        require_sha256(_require_text(frame, "blob_hash"), field="frame blob_hash")
        require_sha256(_require_text(frame, "frame_hash"), field="frame_hash")
        width = _require_int(frame, "width")
        height = _require_int(frame, "height")
        if not 1 <= width <= 64 or not 1 <= height <= 64:
            raise ARC3ValidationError("frame dimensions must be within 1..64")
        palette = require_array(frame.get("palette"), field="frame palette")
        if any(
            isinstance(item, bool) or not isinstance(item, int) or not 0 <= item <= 15
            for item in palette
        ):
            raise ARC3ValidationError("frame palette values must be integers within 0..15")
    _require_text(payload, "game_state")
    require_string_sequence(payload.get("available_actions"), field="available_actions")
    require_object(payload.get("upstream_metadata"), field="upstream_metadata")
    score = payload.get("score")
    if score is not None and (isinstance(score, bool) or not isinstance(score, (int, float))):
        raise ARC3ValidationError("observation score must be numeric or null")


def _validate_action_selected_payload(payload: dict[str, JSONValue]) -> None:
    required = {
        "selected_action",
        "candidate_utilities",
        "selected_probe_or_plan_id",
        "active_hypothesis_ids",
        "predicted_outcome_ids",
        "rationale_category",
    }
    missing = sorted(required - set(payload))
    if missing:
        raise ARC3ValidationError(f"action.selected payload missing: {', '.join(missing)}")
    selected_action = require_object(payload["selected_action"], field="selected_action")
    action_name = selected_action.get("name")
    if action_name not in {"RESET", *(f"ACTION{index}" for index in range(1, 8))}:
        raise ARC3ValidationError("selected_action name is not in the official action vocabulary")
    coordinate = selected_action.get("coordinate")
    if action_name == "ACTION6":
        coordinate_object = require_object(coordinate, field="selected_action.coordinate")
        for axis in ("x", "y"):
            axis_value = coordinate_object.get(axis)
            if (
                isinstance(axis_value, bool)
                or not isinstance(axis_value, int)
                or not 0 <= axis_value <= 63
            ):
                raise ARC3ValidationError("ACTION6 coordinates must be integers within 0..63")
    elif coordinate is not None:
        raise ARC3ValidationError("only ACTION6 may carry coordinate data")
    utilities = require_array(payload["candidate_utilities"], field="candidate_utilities")
    if not all(isinstance(item, dict) for item in utilities):
        raise ARC3ValidationError("candidate_utilities entries must be objects")
    plan_id = payload["selected_probe_or_plan_id"]
    if plan_id is not None and not isinstance(plan_id, str):
        raise ARC3ValidationError("selected_probe_or_plan_id must be a string or null")
    require_string_sequence(payload["active_hypothesis_ids"], field="active_hypothesis_ids")
    require_string_sequence(payload["predicted_outcome_ids"], field="predicted_outcome_ids")
    rationale = payload["rationale_category"]
    if not isinstance(rationale, str) or rationale not in {
        item.value for item in RationaleCategory
    }:
        raise ARC3ValidationError("rationale_category must be a typed RationaleCategory value")
    summary = payload.get("rationale_summary")
    if summary is not None and (not isinstance(summary, str) or len(summary) > 512):
        raise ARC3ValidationError("rationale_summary must be a string of at most 512 characters")


def _validate_delta_payload(payload: dict[str, JSONValue]) -> None:
    require_sha256(_require_text(payload, "before_frame_hash"), field="before_frame_hash")
    require_sha256(_require_text(payload, "after_frame_hash"), field="after_frame_hash")
    changed_count = _require_int(payload, "changed_cell_count")
    if changed_count < 0:
        raise ARC3ValidationError("changed_cell_count must be non-negative")
    raw_changes = require_array(payload.get("cell_changes"), field="cell_changes")
    delta_blob_hash = payload.get("delta_blob_hash")
    if delta_blob_hash is not None:
        require_sha256(delta_blob_hash, field="delta_blob_hash")
    elif len(raw_changes) != changed_count:
        raise ARC3ValidationError("cell_changes must account for changed_cell_count")
    for raw_change in raw_changes:
        change = require_object(raw_change, field="cell_changes[]")
        for field_name in ("x", "y", "before", "after"):
            _require_int(change, field_name)
    raw_bbox = payload.get("changed_bbox")
    if raw_bbox is not None:
        bbox = require_array(raw_bbox, field="changed_bbox")
        if len(bbox) != 4 or any(
            isinstance(item, bool) or not isinstance(item, int) for item in bbox
        ):
            raise ARC3ValidationError("changed_bbox must contain four integers or be null")
    require_array(payload.get("component_changes"), field="component_changes")
    require_object(payload.get("metadata_changes"), field="metadata_changes")
    apparent_noop = payload.get("apparent_noop")
    if not isinstance(apparent_noop, bool) or apparent_noop != (changed_count == 0):
        raise ARC3ValidationError("apparent_noop must exactly reflect changed_cell_count == 0")


def _validate_event_payload(event_type: str, payload: dict[str, JSONValue]) -> None:
    secret = _contains_secret(payload)
    if secret is not None:
        raise ARC3ValidationError(f"credential-bearing field {secret!r} is forbidden in receipts")
    forbidden = _contains_forbidden_reasoning(payload)
    if forbidden is not None:
        raise ARC3ValidationError(f"hidden reasoning field {forbidden!r} is forbidden in receipts")
    if event_type == "observation.received":
        _validate_observation_payload(payload)
    elif event_type == "observation.delta_measured":
        _validate_delta_payload(payload)
    elif event_type == "action.selected":
        _validate_action_selected_payload(payload)
    elif event_type.startswith("evaluation."):
        surface = payload.get("result_surface")
        if surface not in EVALUATION_SURFACES:
            raise ARC3ValidationError("evaluation result_surface is not an allowed evidence label")


@dataclass(frozen=True, slots=True)
class TraceEvent:
    """A hash-linked, immutable ARC3 raw event envelope."""

    event_id: str
    run_id: str
    episode_id: str
    game_id: str
    level_index: int
    step_index: int
    event_type: str
    occurred_at: str
    recorded_at: str
    source: SourceIdentity
    scope: str
    payload: dict[str, JSONValue]
    code_identity: CodeIdentity
    previous_event_hash: str | None
    event_hash: str
    schema: str = EVENT_SCHEMA
    extensions: dict[str, JSONValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.schema != EVENT_SCHEMA:
            raise ARC3ValidationError(f"unsupported event schema: {self.schema!r}")
        for field_name, value in {
            "event_id": self.event_id,
            "run_id": self.run_id,
            "episode_id": self.episode_id,
            "game_id": self.game_id,
        }.items():
            if not value:
                raise ARC3ValidationError(f"{field_name} must be non-empty")
        if self.event_type not in CORE_EVENT_TYPES:
            raise ARC3ValidationError(f"unsupported event_type: {self.event_type!r}")
        if isinstance(self.level_index, bool) or self.level_index < 0:
            raise ARC3ValidationError("level_index must be a non-negative integer")
        if isinstance(self.step_index, bool) or self.step_index < 0:
            raise ARC3ValidationError("step_index must be a non-negative integer")
        _parse_timestamp(self.occurred_at, field_name="occurred_at")
        _parse_timestamp(self.recorded_at, field_name="recorded_at")
        if self.scope not in ALLOWED_SCOPES:
            raise ARC3ValidationError(f"unsupported event scope: {self.scope!r}")
        normalized_payload = normalize_json(self.payload)
        if not isinstance(normalized_payload, dict):  # pragma: no cover - static invariant
            raise ARC3ValidationError("payload must be an object")
        object.__setattr__(self, "payload", normalized_payload)
        _validate_event_payload(self.event_type, normalized_payload)
        if self.previous_event_hash is not None:
            require_sha256(self.previous_event_hash, field="previous_event_hash")
        require_sha256(self.event_hash, field="event_hash")
        normalized_extensions = normalize_json(self.extensions)
        if not isinstance(normalized_extensions, dict):  # pragma: no cover - static invariant
            raise ARC3ValidationError("event extensions must be an object")
        known = set(self._base_dict(include_hash=True))
        collisions = sorted(known & set(normalized_extensions))
        if collisions:
            raise ARC3ValidationError(f"event extensions collide with envelope keys: {collisions}")
        object.__setattr__(self, "extensions", normalized_extensions)

    @classmethod
    def create(
        cls,
        *,
        run_id: str,
        episode_id: str,
        game_id: str,
        level_index: int,
        step_index: int,
        event_type: str,
        source: SourceIdentity,
        scope: StateScope | str,
        payload: Mapping[str, object],
        code_identity: CodeIdentity,
        previous_event_hash: str | None,
        event_id: str | None = None,
        occurred_at: str | None = None,
        recorded_at: str | None = None,
    ) -> TraceEvent:
        """Validate an event and compute its content/linkage hash."""

        normalized_payload = normalize_json(payload)
        if not isinstance(normalized_payload, dict):  # pragma: no cover - Mapping invariant
            raise ARC3ValidationError("event payload must be an object")
        raw = cls(
            event_id=event_id or new_event_id(),
            run_id=run_id,
            episode_id=episode_id,
            game_id=game_id,
            level_index=level_index,
            step_index=step_index,
            event_type=event_type,
            occurred_at=occurred_at or utc_now(),
            recorded_at=recorded_at or utc_now(),
            source=source,
            scope=scope.value if isinstance(scope, StateScope) else scope,
            payload=normalized_payload,
            code_identity=code_identity,
            previous_event_hash=previous_event_hash,
            event_hash="sha256:" + "0" * 64,
        )
        return replace(raw, event_hash=raw.computed_hash())

    def _base_dict(self, *, include_hash: bool) -> dict[str, JSONValue]:
        result: dict[str, JSONValue] = {
            "schema": self.schema,
            "event_id": self.event_id,
            "run_id": self.run_id,
            "episode_id": self.episode_id,
            "game_id": self.game_id,
            "level_index": self.level_index,
            "step_index": self.step_index,
            "event_type": self.event_type,
            "occurred_at": self.occurred_at,
            "recorded_at": self.recorded_at,
            "source": self.source.to_dict(),
            "scope": self.scope,
            "payload": self.payload,
            "code_identity": self.code_identity.to_dict(),
            "previous_event_hash": self.previous_event_hash,
        }
        if include_hash:
            result["event_hash"] = self.event_hash
        return result

    def to_dict(self, *, include_hash: bool = True) -> dict[str, JSONValue]:
        """Return the canonicalizable envelope, preserving unknown fields."""

        return {**self._base_dict(include_hash=include_hash), **self.extensions}

    def computed_hash(self) -> str:
        """Compute the event hash over the envelope excluding ``event_hash``."""

        return sha256_json(self.to_dict(include_hash=False))

    def verify_hash(self) -> None:
        """Raise if the serialized receipt no longer matches its hash."""

        computed = self.computed_hash()
        if computed != self.event_hash:
            raise TraceIntegrityError(
                f"event {self.event_id} hash mismatch: stored {self.event_hash}, computed {computed}"
            )

    @classmethod
    def from_dict(cls, value: Mapping[str, object], *, verify_hash: bool = True) -> TraceEvent:
        """Validate a parsed envelope and optionally verify its content hash."""

        normalized = normalize_json(value)
        if not isinstance(normalized, dict):  # pragma: no cover - Mapping invariant
            raise ARC3ValidationError("event envelope must be an object")
        data = normalized
        schema = _require_text(data, "schema")
        event_id = _require_text(data, "event_id")
        previous_value = data.get("previous_event_hash")
        if previous_value is not None and not isinstance(previous_value, str):
            raise ARC3ValidationError("previous_event_hash must be a string or null")
        known_keys = {
            "schema",
            "event_id",
            "run_id",
            "episode_id",
            "game_id",
            "level_index",
            "step_index",
            "event_type",
            "occurred_at",
            "recorded_at",
            "source",
            "scope",
            "payload",
            "code_identity",
            "previous_event_hash",
            "event_hash",
        }
        event = cls(
            schema=schema,
            event_id=event_id,
            run_id=_require_text(data, "run_id"),
            episode_id=_require_text(data, "episode_id"),
            game_id=_require_text(data, "game_id"),
            level_index=_require_int(data, "level_index"),
            step_index=_require_int(data, "step_index"),
            event_type=_require_text(data, "event_type"),
            occurred_at=_require_text(data, "occurred_at"),
            recorded_at=_require_text(data, "recorded_at"),
            source=SourceIdentity.from_dict(data.get("source")),
            scope=_require_text(data, "scope"),
            payload=require_object(data.get("payload"), field="payload"),
            code_identity=CodeIdentity.from_dict(data.get("code_identity")),
            previous_event_hash=previous_value,
            event_hash=_require_text(data, "event_hash"),
            extensions={key: item for key, item in data.items() if key not in known_keys},
        )
        if verify_hash:
            event.verify_hash()
        return event


def verify_event_chain(events: list[TraceEvent], *, expected_previous: str | None = None) -> None:
    """Verify hashes, previous-hash linkage, and globally unique event IDs."""

    previous = expected_previous
    event_ids: set[str] = set()
    for event in events:
        event.verify_hash()
        if event.event_id in event_ids:
            raise TraceIntegrityError(f"duplicate event_id: {event.event_id}")
        if event.previous_event_hash != previous:
            raise TraceIntegrityError(
                f"event {event.event_id} links to {event.previous_event_hash!r}; expected {previous!r}"
            )
        event_ids.add(event.event_id)
        previous = event.event_hash
