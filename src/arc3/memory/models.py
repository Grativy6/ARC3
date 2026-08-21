"""Typed, source-bounded records for ARC3 persistent memory."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import cast

from arc3.errors import ARC3ValidationError, ReplayError
from arc3.trace import TraceEvent, TraceSummary, summary_from_mapping, validate_summary
from arc3.trace.canonical import canonical_bytes, normalize_json, require_sha256, sha256_json
from arc3.types import JSONValue, StateScope

MEMORY_SCHEMA = "arc3.memory.record.v0.1"
SOURCE_LINK_SCHEMA = "arc3.memory.source-link.v0.1"
MEMORY_SNAPSHOT_SCHEMA = "arc3.memory.snapshot.v0.1"


class MemoryContractError(ARC3ValidationError):
    """A memory value would violate scope, provenance, or budget rules."""


class MemoryKind(StrEnum):
    """The retrieval role of a derived memory record."""

    EVENT = "event"
    ABSTRACT_STATE = "abstract_state"
    CONTRADICTION = "contradiction"
    RULE = "rule"


def _non_empty_text(value: object, *, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise MemoryContractError(f"{field_name} must be a non-empty string")
    return value


def _string_tuple(value: object, *, field_name: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        raise MemoryContractError(f"{field_name} must be an array of non-empty strings")
    return tuple(cast(str, item) for item in value)


def _normalized_tokens(values: Sequence[str], *, field_name: str) -> tuple[str, ...]:
    normalized = tuple(sorted({value.strip().lower() for value in values if value.strip()}))
    if not normalized:
        raise MemoryContractError(f"{field_name} must contain at least one non-empty token")
    return normalized


@dataclass(frozen=True, slots=True)
class AbstractState:
    """Palette- and position-independent state features supplied by perception."""

    features: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "features",
            _normalized_tokens(self.features, field_name="abstract-state features"),
        )

    @property
    def state_hash(self) -> str:
        return sha256_json({"schema": "arc3.memory.abstract-state.v0.1", "features": self.features})

    def similarity(self, other: AbstractState) -> float:
        left = set(self.features)
        right = set(other.features)
        return len(left & right) / len(left | right)

    def to_dict(self) -> dict[str, JSONValue]:
        return {"features": list(self.features), "state_hash": self.state_hash}

    @classmethod
    def from_dict(cls, value: object) -> AbstractState:
        if not isinstance(value, Mapping):
            raise MemoryContractError("abstract_state must be an object")
        state = cls(features=_string_tuple(value.get("features"), field_name="features"))
        declared_hash = value.get("state_hash")
        if declared_hash != state.state_hash:
            raise MemoryContractError("abstract_state hash mismatch")
        return state


@dataclass(frozen=True, slots=True)
class RuleSignature:
    """A game-independent structural signature, never a solution sequence."""

    family: str
    operation: str
    predicates: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "family", _non_empty_text(self.family, field_name="family").lower()
        )
        object.__setattr__(
            self,
            "operation",
            _non_empty_text(self.operation, field_name="operation").lower(),
        )
        normalized = tuple(
            sorted({item.strip().lower() for item in self.predicates if item.strip()})
        )
        object.__setattr__(self, "predicates", normalized)

    @property
    def signature_hash(self) -> str:
        return sha256_json(self.to_dict(include_hash=False))

    def similarity(self, other: RuleSignature) -> float:
        if self.family != other.family:
            return 0.0
        operation_score = 0.6 if self.operation == other.operation else 0.25
        left = set(self.predicates)
        right = set(other.predicates)
        predicate_score = (
            0.4 if not left and not right else 0.4 * len(left & right) / len(left | right)
        )
        return operation_score + predicate_score

    def to_dict(self, *, include_hash: bool = True) -> dict[str, JSONValue]:
        result: dict[str, JSONValue] = {
            "family": self.family,
            "operation": self.operation,
            "predicates": list(self.predicates),
        }
        if include_hash:
            result["signature_hash"] = self.signature_hash
        return result

    @classmethod
    def from_dict(cls, value: object) -> RuleSignature:
        if not isinstance(value, Mapping):
            raise MemoryContractError("rule_signature must be an object")
        signature = cls(
            family=_non_empty_text(value.get("family"), field_name="family"),
            operation=_non_empty_text(value.get("operation"), field_name="operation"),
            predicates=_string_tuple(value.get("predicates", []), field_name="predicates"),
        )
        if value.get("signature_hash") != signature.signature_hash:
            raise MemoryContractError("rule_signature hash mismatch")
        return signature


@dataclass(frozen=True, slots=True)
class SourceLinkedSummary:
    """A Stage 03 summary strengthened with every source event hash."""

    trace_summary: TraceSummary
    source_event_ids: tuple[str, ...]
    source_event_hashes: tuple[str, ...]
    schema: str = SOURCE_LINK_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != SOURCE_LINK_SCHEMA:
            raise MemoryContractError(f"unsupported source-link schema: {self.schema!r}")
        if not self.source_event_ids or len(self.source_event_ids) != len(self.source_event_hashes):
            raise MemoryContractError(
                "source link requires equally sized non-empty event IDs/hashes"
            )
        if self.source_event_ids[0] != self.trace_summary.source_event_start_id:
            raise MemoryContractError("source-link start does not match summary event range")
        if self.source_event_ids[-1] != self.trace_summary.source_event_end_id:
            raise MemoryContractError("source-link end does not match summary event range")
        if len(set(self.source_event_ids)) != len(self.source_event_ids):
            raise MemoryContractError("source-link event IDs must be unique")
        if not self.trace_summary.claims:
            raise MemoryContractError("source-linked summary requires at least one bounded claim")
        if any(not claim.supporting_event_ids for claim in self.trace_summary.claims):
            raise MemoryContractError(
                "every source-linked summary claim requires supporting events"
            )
        for event_hash in self.source_event_hashes:
            try:
                require_sha256(event_hash, field="source_event_hash")
            except ARC3ValidationError as error:
                raise MemoryContractError(str(error)) from error
        referenced = {
            event_id
            for claim in self.trace_summary.claims
            for event_id in (*claim.supporting_event_ids, *claim.contradicting_event_ids)
        }
        if referenced - set(self.source_event_ids):
            raise MemoryContractError("summary claim references an event outside its source link")

    @classmethod
    def from_events(
        cls,
        trace_summary: TraceSummary,
        source_events: Sequence[TraceEvent],
    ) -> SourceLinkedSummary:
        try:
            validate_summary(trace_summary, source_events)
        except ReplayError as error:
            raise MemoryContractError(str(error)) from error
        return cls(
            trace_summary=trace_summary,
            source_event_ids=tuple(event.event_id for event in source_events),
            source_event_hashes=tuple(event.event_hash for event in source_events),
        )

    @property
    def source_hash(self) -> str:
        return sha256_json(
            {
                "event_ids": self.source_event_ids,
                "event_hashes": self.source_event_hashes,
                "chunk_hashes": self.trace_summary.source_chunk_hashes,
            }
        )

    def references_event(self, event_id: str) -> bool:
        return event_id in self.source_event_ids

    def verify_events(self, source_events: Sequence[TraceEvent]) -> None:
        """Rebind a persisted derived summary to verified immutable receipts."""

        try:
            validate_summary(self.trace_summary, source_events)
        except ReplayError as error:
            raise MemoryContractError(str(error)) from error
        observed_ids = tuple(event.event_id for event in source_events)
        observed_hashes = tuple(event.event_hash for event in source_events)
        if observed_ids != self.source_event_ids or observed_hashes != self.source_event_hashes:
            raise MemoryContractError("source-link identities do not match supplied trace events")

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "schema": self.schema,
            "trace_summary": self.trace_summary.to_dict(),
            "source_event_ids": list(self.source_event_ids),
            "source_event_hashes": list(self.source_event_hashes),
            "source_hash": self.source_hash,
        }

    @classmethod
    def from_dict(cls, value: object) -> SourceLinkedSummary:
        if not isinstance(value, Mapping):
            raise MemoryContractError("source_link must be an object")
        raw_summary = value.get("trace_summary")
        if not isinstance(raw_summary, Mapping):
            raise MemoryContractError("source_link trace_summary must be an object")
        try:
            trace_summary = summary_from_mapping(raw_summary)
        except ReplayError as error:
            raise MemoryContractError(str(error)) from error
        link = cls(
            schema=_non_empty_text(value.get("schema"), field_name="source-link schema"),
            trace_summary=trace_summary,
            source_event_ids=_string_tuple(
                value.get("source_event_ids"), field_name="source_event_ids"
            ),
            source_event_hashes=_string_tuple(
                value.get("source_event_hashes"), field_name="source_event_hashes"
            ),
        )
        if value.get("source_hash") != link.source_hash:
            raise MemoryContractError("source-link hash mismatch")
        return link


def _contains_forbidden_lookup_key(value: JSONValue) -> str | None:
    forbidden = {"game_id", "solution", "solution_sequence", "action_sequence"}
    if isinstance(value, dict):
        for key, child in value.items():
            if key.lower() in forbidden:
                return key
            nested = _contains_forbidden_lookup_key(child)
            if nested is not None:
                return nested
    elif isinstance(value, list):
        for child in value:
            nested = _contains_forbidden_lookup_key(child)
            if nested is not None:
                return nested
    return None


@dataclass(frozen=True, slots=True)
class MemoryRecord:
    """One replaceable derived-memory item with explicit authority ceiling."""

    memory_id: str
    kind: MemoryKind
    scope: StateScope
    summary: SourceLinkedSummary
    importance: int = 0
    episode_id: str | None = None
    game_scope_hash: str | None = None
    abstract_state: AbstractState | None = None
    rule_signature: RuleSignature | None = None
    active_contradiction_ids: tuple[str, ...] = ()
    rejected_hypothesis_ids: tuple[str, ...] = ()
    origin_scope_hashes: tuple[str, ...] = ()
    payload: dict[str, JSONValue] = field(default_factory=dict)
    schema: str = MEMORY_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != MEMORY_SCHEMA:
            raise MemoryContractError(f"unsupported memory schema: {self.schema!r}")
        _non_empty_text(self.memory_id, field_name="memory_id")
        try:
            scope = (
                self.scope if isinstance(self.scope, StateScope) else StateScope(str(self.scope))
            )
            kind = self.kind if isinstance(self.kind, MemoryKind) else MemoryKind(str(self.kind))
        except ValueError as error:
            raise MemoryContractError("memory scope or kind is unsupported") from error
        if scope not in {StateScope.EPISODE, StateScope.GAME, StateScope.GENERIC}:
            raise MemoryContractError(
                "memory records may only have episode, game, or generic scope"
            )
        object.__setattr__(self, "scope", scope)
        object.__setattr__(self, "kind", kind)
        if isinstance(self.importance, bool) or not -100 <= self.importance <= 100:
            raise MemoryContractError("importance must be an integer within -100..100")
        if scope is StateScope.EPISODE:
            _non_empty_text(self.episode_id, field_name="episode_id")
            self._validate_scope_hash(self.game_scope_hash, field_name="game_scope_hash")
        elif scope is StateScope.GAME:
            if self.episode_id is not None:
                raise MemoryContractError("game memory cannot retain an episode identifier")
            self._validate_scope_hash(self.game_scope_hash, field_name="game_scope_hash")
        else:
            if self.episode_id is not None or self.game_scope_hash is not None:
                raise MemoryContractError("generic memory cannot retain episode or game scope")
            if self.rule_signature is None:
                raise MemoryContractError("generic memory requires an analogous rule signature")
            distinct_origins = set(self.origin_scope_hashes)
            if len(distinct_origins) < 2:
                raise MemoryContractError(
                    "generic learned memory requires support from at least two opaque game scopes"
                )
        if kind is MemoryKind.ABSTRACT_STATE and self.abstract_state is None:
            raise MemoryContractError("abstract-state memory requires abstract_state")
        if kind is MemoryKind.CONTRADICTION and not self.active_contradiction_ids:
            raise MemoryContractError("contradiction memory requires an active contradiction")
        if kind is MemoryKind.RULE and self.rule_signature is None:
            raise MemoryContractError("rule memory requires rule_signature")
        for scope_hash in self.origin_scope_hashes:
            self._validate_scope_hash(scope_hash, field_name="origin_scope_hash")
        normalized_payload = normalize_json(self.payload)
        if not isinstance(normalized_payload, dict):  # pragma: no cover - static invariant
            raise MemoryContractError("memory payload must be an object")
        forbidden = _contains_forbidden_lookup_key(normalized_payload)
        summary_forbidden = _contains_forbidden_lookup_key(self.summary.to_dict())
        forbidden = forbidden or summary_forbidden
        if forbidden is not None:
            raise MemoryContractError(
                f"memory payload key {forbidden!r} could enable task-specific solution lookup"
            )
        object.__setattr__(self, "payload", normalized_payload)
        object.__setattr__(
            self,
            "active_contradiction_ids",
            tuple(sorted(set(self.active_contradiction_ids))),
        )
        object.__setattr__(
            self,
            "rejected_hypothesis_ids",
            tuple(sorted(set(self.rejected_hypothesis_ids))),
        )
        object.__setattr__(
            self, "origin_scope_hashes", tuple(sorted(set(self.origin_scope_hashes)))
        )

    @staticmethod
    def _validate_scope_hash(value: object, *, field_name: str) -> None:
        try:
            require_sha256(value, field=field_name)
        except ARC3ValidationError as error:
            raise MemoryContractError(str(error)) from error

    @property
    def byte_size(self) -> int:
        return len(canonical_bytes(self.to_dict()))

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "schema": self.schema,
            "memory_id": self.memory_id,
            "kind": self.kind.value,
            "scope": self.scope.value,
            "summary": self.summary.to_dict(),
            "importance": self.importance,
            "episode_id": self.episode_id,
            "game_scope_hash": self.game_scope_hash,
            "abstract_state": self.abstract_state.to_dict() if self.abstract_state else None,
            "rule_signature": self.rule_signature.to_dict() if self.rule_signature else None,
            "active_contradiction_ids": list(self.active_contradiction_ids),
            "rejected_hypothesis_ids": list(self.rejected_hypothesis_ids),
            "origin_scope_hashes": list(self.origin_scope_hashes),
            "payload": self.payload,
        }

    @classmethod
    def from_dict(cls, value: object) -> MemoryRecord:
        if not isinstance(value, Mapping):
            raise MemoryContractError("memory record must be an object")
        raw_summary = value.get("summary")
        raw_abstract = value.get("abstract_state")
        raw_rule = value.get("rule_signature")
        raw_payload = value.get("payload", {})
        if not isinstance(raw_payload, Mapping):
            raise MemoryContractError("memory payload must be an object")
        try:
            scope = StateScope(_non_empty_text(value.get("scope"), field_name="scope"))
            kind = MemoryKind(_non_empty_text(value.get("kind"), field_name="kind"))
        except ValueError as error:
            raise MemoryContractError("memory scope or kind is unsupported") from error
        importance = value.get("importance", 0)
        if isinstance(importance, bool) or not isinstance(importance, int):
            raise MemoryContractError("importance must be an integer")
        return cls(
            schema=_non_empty_text(value.get("schema"), field_name="memory schema"),
            memory_id=_non_empty_text(value.get("memory_id"), field_name="memory_id"),
            kind=kind,
            scope=scope,
            summary=SourceLinkedSummary.from_dict(raw_summary),
            importance=importance,
            episode_id=cast(str | None, value.get("episode_id")),
            game_scope_hash=cast(str | None, value.get("game_scope_hash")),
            abstract_state=(
                AbstractState.from_dict(raw_abstract) if raw_abstract is not None else None
            ),
            rule_signature=RuleSignature.from_dict(raw_rule) if raw_rule is not None else None,
            active_contradiction_ids=_string_tuple(
                value.get("active_contradiction_ids", []), field_name="active_contradiction_ids"
            ),
            rejected_hypothesis_ids=_string_tuple(
                value.get("rejected_hypothesis_ids", []), field_name="rejected_hypothesis_ids"
            ),
            origin_scope_hashes=_string_tuple(
                value.get("origin_scope_hashes", []), field_name="origin_scope_hashes"
            ),
            payload=cast(dict[str, JSONValue], dict(raw_payload)),
        )


@dataclass(frozen=True, slots=True)
class MemoryBudget:
    """Hard limits for all derived memory; raw trace has its own separate budget."""

    max_records: int = 1024
    max_bytes: int = 8 * 1024 * 1024
    max_episode_records: int = 512
    max_game_records: int = 384
    max_generic_records: int = 128
    trace_chunk_events: int = 512
    trace_chunk_bytes: int = 8 * 1024 * 1024

    def __post_init__(self) -> None:
        for field_name in self.__dataclass_fields__:
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise MemoryContractError(f"{field_name} must be a positive integer")

    def to_dict(self) -> dict[str, JSONValue]:
        return {name: cast(int, getattr(self, name)) for name in self.__dataclass_fields__}

    @classmethod
    def from_dict(cls, value: object) -> MemoryBudget:
        if not isinstance(value, Mapping):
            raise MemoryContractError("memory budget must be an object")
        expected = set(cls.__dataclass_fields__)
        if set(value) != expected:
            raise MemoryContractError("memory budget fields do not match the current schema")
        kwargs: dict[str, int] = {}
        for key in expected:
            item = value[key]
            if isinstance(item, bool) or not isinstance(item, int):
                raise MemoryContractError(f"{key} must be an integer")
            kwargs[key] = item
        return cls(**kwargs)


@dataclass(frozen=True, slots=True)
class MemoryAblations:
    """Stage 11 switches used by equal-budget mechanism comparisons."""

    memory_enabled: bool = True
    retain_rejected_hypotheses: bool = True

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "memory_enabled": self.memory_enabled,
            "retain_rejected_hypotheses": self.retain_rejected_hypotheses,
        }

    @classmethod
    def from_dict(cls, value: object) -> MemoryAblations:
        if not isinstance(value, Mapping):
            raise MemoryContractError("memory ablations must be an object")
        enabled = value.get("memory_enabled")
        rejected = value.get("retain_rejected_hypotheses")
        if not isinstance(enabled, bool) or not isinstance(rejected, bool):
            raise MemoryContractError("memory ablation switches must be booleans")
        return cls(memory_enabled=enabled, retain_rejected_hypotheses=rejected)


@dataclass(frozen=True, slots=True)
class MemoryQuery:
    """A structural retrieval request containing no public task identifier."""

    episode_id: str | None = None
    game_scope_hash: str | None = None
    exact_event_id: str | None = None
    abstract_state: AbstractState | None = None
    active_contradiction_ids: tuple[str, ...] = ()
    analogous_rule: RuleSignature | None = None
    current_game_evidence_event_ids: tuple[str, ...] = ()
    limit: int = 8

    def __post_init__(self) -> None:
        if self.game_scope_hash is not None:
            MemoryRecord._validate_scope_hash(self.game_scope_hash, field_name="game_scope_hash")
        if self.episode_id is not None and self.game_scope_hash is None:
            raise MemoryContractError("episode retrieval requires an opaque game scope")
        if isinstance(self.limit, bool) or not 1 <= self.limit <= 256:
            raise MemoryContractError("retrieval limit must be within 1..256")
        if not any(
            (
                self.exact_event_id,
                self.abstract_state,
                self.active_contradiction_ids,
                self.analogous_rule,
            )
        ):
            raise MemoryContractError("memory query needs at least one retrieval key")


@dataclass(frozen=True, slots=True)
class MemoryHit:
    """A ranked hit retaining the complete source-linked record."""

    record: MemoryRecord
    score: int
    matched_by: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class StoreResult:
    retained: bool
    evicted_memory_ids: tuple[str, ...] = ()
    reason: str | None = None
