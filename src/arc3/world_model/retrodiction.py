"""Retrodiction gates, bounded experimental modes, and exact cache receipts."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import cast

from arc3.errors import WorldModelError
from arc3.trace.canonical import canonical_bytes, normalize_json, sha256_json
from arc3.types import ActionRequest, JSONValue

from .model import ModelCandidate, WorldModelEnsemble
from .state import SymbolicState


class PromotionStatus(StrEnum):
    PROMOTED = "promoted"
    REJECTED = "rejected"
    UNGATED_ABLATION = "ungated_ablation"


class RetrodictionMode(StrEnum):
    """Predeclared Stage 07 history-evaluation modes."""

    FULL = "FULL"
    NONE = "NONE"
    RECENT_WINDOW_8 = "RECENT_WINDOW_8"
    EVENT_TRIGGERED = "EVENT_TRIGGERED"
    CACHED_INCREMENTAL = "CACHED_INCREMENTAL"


class RetrodictionReason(StrEnum):
    """Trace-safe reason for the selected evaluation scope."""

    FULL = "full"
    DISABLED = "disabled"
    RECENT_WINDOW = "recent-window"
    FIRST_USE = "first-use"
    EXACT_CACHE_HIT = "exact-cache-hit"
    PREFIX_EXTENSION = "prefix-extension"
    NON_PREFIX = "non-prefix"
    INVALIDATED = "invalidated"
    EVENT_RECEIPT_REUSE = "event-receipt-reuse"
    EVENT_FULL_AUDIT = "event-full-audit"


class TransitionOutcomeKind(StrEnum):
    """One deterministic transition-level retrodiction outcome."""

    MATCHED = "matched"
    CONTRADICTED = "contradicted"
    EXCLUDED = "excluded"


RETRODICTION_CACHE_SCHEMA = "arc3.retrodiction-cache.v0.1"
DEFAULT_PROJECTION_VERSION = "arc3.candidate-retrodiction.v0.1"
EVENT_REUSE_MATCH_SCOPES = frozenset({"whole-symbolic-state", "controlled-entity-projection"})


def _require_text(value: str, *, field: str) -> str:
    if not value.strip():
        raise WorldModelError(f"{field} must be non-empty")
    return value


@dataclass(frozen=True, slots=True)
class RetrodictionConfig:
    """Complete runtime identity for one retrodiction policy."""

    mode: RetrodictionMode = RetrodictionMode.FULL
    window: int = 8
    capacity: int = 64
    projection_version: str = DEFAULT_PROJECTION_VERSION

    def __post_init__(self) -> None:
        if isinstance(self.window, bool) or self.window < 1:
            raise WorldModelError("retrodiction window must be a positive integer")
        if isinstance(self.capacity, bool) or self.capacity < 1:
            raise WorldModelError("retrodiction cache capacity must be a positive integer")
        _require_text(self.projection_version, field="projection_version")

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "capacity": self.capacity,
            "mode": self.mode.value,
            "projection_version": self.projection_version,
            "window": self.window,
        }

    @property
    def configuration_hash(self) -> str:
        """Hash the complete global retrodiction configuration."""

        return sha256_json(self.to_dict())

    @classmethod
    def from_dict(cls, value: object) -> RetrodictionConfig:
        if not isinstance(value, Mapping):
            raise WorldModelError("retrodiction config must be an object")
        mode = value.get("mode")
        window = value.get("window")
        capacity = value.get("capacity")
        projection_version = value.get("projection_version")
        if (
            not isinstance(mode, str)
            or isinstance(window, bool)
            or not isinstance(window, int)
            or isinstance(capacity, bool)
            or not isinstance(capacity, int)
            or not isinstance(projection_version, str)
        ):
            raise WorldModelError("retrodiction config fields are malformed")
        try:
            parsed_mode = RetrodictionMode(mode)
        except ValueError as error:
            raise WorldModelError("retrodiction mode is unsupported") from error
        return cls(parsed_mode, window, capacity, projection_version)


@dataclass(frozen=True, slots=True, order=True)
class RetrodictionOmission:
    """One explicit transition omission and its bounded reason."""

    transition_id: str
    reason: str

    def __post_init__(self) -> None:
        _require_text(self.transition_id, field="omitted transition_id")
        _require_text(self.reason, field="omission reason")

    def to_dict(self) -> dict[str, JSONValue]:
        return {"reason": self.reason, "transition_id": self.transition_id}

    @classmethod
    def from_dict(cls, value: object) -> RetrodictionOmission:
        if not isinstance(value, Mapping):
            raise WorldModelError("retrodiction omission must be an object")
        transition_id = value.get("transition_id")
        reason = value.get("reason")
        if not isinstance(transition_id, str) or not isinstance(reason, str):
            raise WorldModelError("retrodiction omission fields are malformed")
        return cls(transition_id, reason)


@dataclass(frozen=True, slots=True)
class MatchedPredictionEvidence:
    """Immutable source identities permitting one event-triggered suffix reuse."""

    transition_id: str
    model_id: str
    prediction_event_id: str
    prediction_receipt_id: str
    consequence_event_id: str
    assessment_receipt_id: str
    matched: bool
    match_scope: str
    source_ordered: bool = True

    def __post_init__(self) -> None:
        for field, value in (
            ("transition_id", self.transition_id),
            ("model_id", self.model_id),
            ("prediction_event_id", self.prediction_event_id),
            ("prediction_receipt_id", self.prediction_receipt_id),
            ("consequence_event_id", self.consequence_event_id),
            ("assessment_receipt_id", self.assessment_receipt_id),
            ("match_scope", self.match_scope),
        ):
            _require_text(value, field=field)

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "assessment_receipt_id": self.assessment_receipt_id,
            "consequence_event_id": self.consequence_event_id,
            "match_scope": self.match_scope,
            "matched": self.matched,
            "model_id": self.model_id,
            "prediction_event_id": self.prediction_event_id,
            "prediction_receipt_id": self.prediction_receipt_id,
            "source_ordered": self.source_ordered,
            "transition_id": self.transition_id,
        }


@dataclass(frozen=True, slots=True)
class PreservedTransition:
    """An immutable-reference transition used for retrospective falsification."""

    transition_id: str
    before: SymbolicState
    action: ActionRequest
    after: SymbolicState
    source_event_ids: tuple[str, ...]
    compatible_model_ids: tuple[str, ...] = ()

    def is_compatible_with(self, model_id: str) -> bool:
        return not self.compatible_model_ids or model_id in self.compatible_model_ids


@dataclass(frozen=True, slots=True)
class StateResidual:
    transition_id: str
    missing_entities: tuple[str, ...]
    unexpected_entities: tuple[str, ...]
    changed_entities: tuple[str, ...]
    missing_facts: tuple[str, ...]
    unexpected_facts: tuple[str, ...]
    changed_counters: tuple[str, ...]
    changed_toggles: tuple[str, ...]
    selection_mismatch: bool
    attachment_mismatch: bool

    @property
    def count(self) -> int:
        return sum(
            (
                len(self.missing_entities),
                len(self.unexpected_entities),
                len(self.changed_entities),
                len(self.missing_facts),
                len(self.unexpected_facts),
                len(self.changed_counters),
                len(self.changed_toggles),
                int(self.selection_mismatch),
                int(self.attachment_mismatch),
            )
        )


@dataclass(frozen=True, slots=True)
class ModelScore:
    fit: float
    complexity: int
    contradictions: int
    residual_coverage: float
    rank_weight: int
    total: float
    weight_kind: str = "uncalibrated_rank"


@dataclass(frozen=True, slots=True)
class RetrodictionArtifact:
    """Complete gate receipt; no promoted state exists without one."""

    artifact_id: str
    model_id: str
    retrodiction_enabled: bool
    compatible_transition_ids: tuple[str, ...]
    tested_transition_ids: tuple[str, ...]
    explicitly_excluded_transition_ids: tuple[str, ...]
    matched_transition_ids: tuple[str, ...]
    contradiction_transition_ids: tuple[str, ...]
    residuals: tuple[StateResidual, ...]
    score: ModelScore
    status: PromotionStatus
    complete: bool

    @property
    def promotable(self) -> bool:
        return self.status is PromotionStatus.PROMOTED


@dataclass(frozen=True, slots=True)
class TransitionOutcome:
    """Foldable result for one compatible transition."""

    transition_id: str
    kind: TransitionOutcomeKind
    residual: StateResidual | None = None

    def __post_init__(self) -> None:
        _require_text(self.transition_id, field="outcome transition_id")
        if (self.kind is TransitionOutcomeKind.CONTRADICTED) != (self.residual is not None):
            raise WorldModelError("only contradicted outcomes carry a residual")
        if self.residual is not None and self.residual.transition_id != self.transition_id:
            raise WorldModelError("retrodiction outcome residual identity disagrees")

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "kind": self.kind.value,
            "residual": _residual_to_dict(self.residual) if self.residual is not None else None,
            "transition_id": self.transition_id,
        }

    @classmethod
    def from_dict(cls, value: object) -> TransitionOutcome:
        if not isinstance(value, Mapping):
            raise WorldModelError("retrodiction outcome must be an object")
        transition_id = value.get("transition_id")
        kind = value.get("kind")
        if not isinstance(transition_id, str) or not isinstance(kind, str):
            raise WorldModelError("retrodiction outcome fields are malformed")
        try:
            parsed_kind = TransitionOutcomeKind(kind)
        except ValueError as error:
            raise WorldModelError("retrodiction outcome kind is unsupported") from error
        residual_value = value.get("residual")
        residual = None if residual_value is None else _residual_from_dict(residual_value)
        return cls(transition_id, parsed_kind, residual)


@dataclass(frozen=True, slots=True)
class RetrodictionCacheEntry:
    """One exact, receipt-linked prefix fold retained by deterministic LRU."""

    cache_key: str
    namespace_key: str
    configuration_hash: str
    model_id: str
    model_semantic_fingerprint: str
    mechanics_epoch_id: str
    projection_version: str
    history_key: str
    exclusion_identity: str
    resolved_noise_transition_ids: tuple[str, ...]
    omissions: tuple[RetrodictionOmission, ...]
    prefix_length: int
    prefix_hash: str
    transition_witnesses: tuple[bytes, ...]
    outcomes: tuple[TransitionOutcome, ...]
    materialized_artifact_id: str
    source_receipt_event_id: str
    access_ordinal: int

    def __post_init__(self) -> None:
        for field, value in (
            ("cache_key", self.cache_key),
            ("namespace_key", self.namespace_key),
            ("configuration_hash", self.configuration_hash),
            ("model_id", self.model_id),
            ("model_semantic_fingerprint", self.model_semantic_fingerprint),
            ("mechanics_epoch_id", self.mechanics_epoch_id),
            ("projection_version", self.projection_version),
            ("history_key", self.history_key),
            ("exclusion_identity", self.exclusion_identity),
            ("prefix_hash", self.prefix_hash),
            ("materialized_artifact_id", self.materialized_artifact_id),
            ("source_receipt_event_id", self.source_receipt_event_id),
        ):
            _require_text(value, field=field)
        if isinstance(self.prefix_length, bool) or self.prefix_length < 0:
            raise WorldModelError("cache prefix_length must be a non-negative integer")
        if isinstance(self.access_ordinal, bool) or self.access_ordinal < 1:
            raise WorldModelError("cache access_ordinal must be a positive integer")
        if self.prefix_length != len(self.transition_witnesses):
            raise WorldModelError("cache prefix length disagrees with witnesses")
        if self.prefix_length != len(self.outcomes):
            raise WorldModelError("cache prefix length disagrees with outcomes")
        if any(not isinstance(item, bytes) for item in self.transition_witnesses):
            raise WorldModelError("cache transition witnesses must be bytes")
        if len(set(self.resolved_noise_transition_ids)) != len(
            self.resolved_noise_transition_ids
        ) or any(
            not isinstance(item, str) or not item.strip()
            for item in self.resolved_noise_transition_ids
        ):
            raise WorldModelError("cache resolved-noise identities are malformed")
        if not all(isinstance(item, RetrodictionOmission) for item in self.omissions):
            raise WorldModelError("cache omissions must be typed retrodiction omissions")
        omission_ids = [item.transition_id for item in self.omissions]
        if len(set(omission_ids)) != len(omission_ids):
            raise WorldModelError("cache omission identities must be unique")
        expected_exclusion = _exclusion_identity_from_parts(
            self.omissions,
            self.resolved_noise_transition_ids,
        )
        if self.exclusion_identity != expected_exclusion:
            raise WorldModelError("cache exclusion identity disagrees with typed identities")
        expected_prefix = _prefix_hash(self.transition_witnesses)
        if self.prefix_hash != expected_prefix:
            raise WorldModelError("cache prefix hash disagrees with exact witnesses")

    def validate_against(
        self,
        *,
        config: RetrodictionConfig,
        request: RetrodictionRequest,
        materialized_artifact_id: str,
        source_receipt_event_id: str,
    ) -> None:
        """Rebuild and compare every entry identity against trace-derived inputs."""

        semantic = model_semantic_fingerprint(request.model)
        witnesses = tuple(transition_witness(item) for item in request.transitions)
        exclusion = _exclusion_identity(request)
        history = _history_key(witnesses, exclusion_identity=exclusion)
        namespace = _namespace_key(config, request, semantic_fingerprint=semantic)
        expected = (
            ("configuration hash", self.configuration_hash, config.configuration_hash),
            ("model ID", self.model_id, request.model.model_id),
            ("model semantic fingerprint", self.model_semantic_fingerprint, semantic),
            ("mechanics epoch", self.mechanics_epoch_id, request.mechanics_epoch_id),
            ("projection version", self.projection_version, config.projection_version),
            ("exclusion identity", self.exclusion_identity, exclusion),
            ("history key", self.history_key, history),
            ("namespace", self.namespace_key, namespace),
            ("cache key", self.cache_key, _cache_key(namespace, history)),
            ("artifact identity", self.materialized_artifact_id, materialized_artifact_id),
            ("source receipt", self.source_receipt_event_id, source_receipt_event_id),
        )
        for field, actual, required in expected:
            if actual != required:
                raise WorldModelError(f"cache {field} disagrees with restore evidence")
        if self.resolved_noise_transition_ids != request.resolved_noise_transition_ids:
            raise WorldModelError("cache resolved-noise order disagrees with restore evidence")
        if self.omissions != request.omissions:
            raise WorldModelError("cache omission order disagrees with restore evidence")
        if self.prefix_length != len(request.transitions) or self.transition_witnesses != witnesses:
            raise WorldModelError("cache transition vector disagrees with restore evidence")
        reconstructed_outcomes = _evaluate_outcomes(
            request.model,
            request.transitions,
        )
        if self.outcomes != reconstructed_outcomes:
            raise WorldModelError("cache outcomes disagree with reconstructed transition evidence")
        artifact = _materialize_artifact(
            request.model,
            request.transitions,
            reconstructed_outcomes,
            enabled=True,
        )
        if artifact.artifact_id != materialized_artifact_id:
            raise WorldModelError("cache outcome fold disagrees with completion artifact")

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "access_ordinal": self.access_ordinal,
            "cache_key": self.cache_key,
            "configuration_hash": self.configuration_hash,
            "exclusion_identity": self.exclusion_identity,
            "history_key": self.history_key,
            "materialized_artifact_id": self.materialized_artifact_id,
            "mechanics_epoch_id": self.mechanics_epoch_id,
            "model_id": self.model_id,
            "model_semantic_fingerprint": self.model_semantic_fingerprint,
            "namespace_key": self.namespace_key,
            "omissions": [item.to_dict() for item in self.omissions],
            "outcomes": [item.to_dict() for item in self.outcomes],
            "prefix_hash": self.prefix_hash,
            "prefix_length": self.prefix_length,
            "projection_version": self.projection_version,
            "resolved_noise_transition_ids": list(self.resolved_noise_transition_ids),
            "source_receipt_event_id": self.source_receipt_event_id,
            "transition_witnesses_hex": [item.hex() for item in self.transition_witnesses],
        }

    @classmethod
    def from_dict(cls, value: object) -> RetrodictionCacheEntry:
        if not isinstance(value, Mapping):
            raise WorldModelError("retrodiction cache entry must be an object")
        string_fields = (
            "cache_key",
            "namespace_key",
            "configuration_hash",
            "model_id",
            "model_semantic_fingerprint",
            "mechanics_epoch_id",
            "projection_version",
            "history_key",
            "exclusion_identity",
            "prefix_hash",
            "materialized_artifact_id",
            "source_receipt_event_id",
        )
        strings: dict[str, str] = {}
        for field in string_fields:
            item = value.get(field)
            if not isinstance(item, str):
                raise WorldModelError(f"cache {field} must be a string")
            strings[field] = item
        prefix_length = value.get("prefix_length")
        access_ordinal = value.get("access_ordinal")
        raw_witnesses = value.get("transition_witnesses_hex")
        raw_outcomes = value.get("outcomes")
        raw_resolved_noise = value.get("resolved_noise_transition_ids")
        raw_omissions = value.get("omissions")
        if (
            isinstance(prefix_length, bool)
            or not isinstance(prefix_length, int)
            or isinstance(access_ordinal, bool)
            or not isinstance(access_ordinal, int)
            or not isinstance(raw_witnesses, list)
            or not all(isinstance(item, str) for item in raw_witnesses)
            or not isinstance(raw_outcomes, list)
            or not isinstance(raw_resolved_noise, list)
            or not all(isinstance(item, str) for item in raw_resolved_noise)
            or not isinstance(raw_omissions, list)
        ):
            raise WorldModelError("retrodiction cache entry fields are malformed")
        try:
            witnesses = tuple(bytes.fromhex(cast(str, item)) for item in raw_witnesses)
        except ValueError as error:
            raise WorldModelError("cache transition witness is not hexadecimal") from error
        outcomes = tuple(TransitionOutcome.from_dict(item) for item in raw_outcomes)
        omissions = tuple(RetrodictionOmission.from_dict(item) for item in raw_omissions)
        return cls(
            cache_key=strings["cache_key"],
            namespace_key=strings["namespace_key"],
            configuration_hash=strings["configuration_hash"],
            model_id=strings["model_id"],
            model_semantic_fingerprint=strings["model_semantic_fingerprint"],
            mechanics_epoch_id=strings["mechanics_epoch_id"],
            projection_version=strings["projection_version"],
            history_key=strings["history_key"],
            exclusion_identity=strings["exclusion_identity"],
            resolved_noise_transition_ids=tuple(cast(str, item) for item in raw_resolved_noise),
            omissions=omissions,
            prefix_length=prefix_length,
            prefix_hash=strings["prefix_hash"],
            transition_witnesses=witnesses,
            outcomes=outcomes,
            materialized_artifact_id=strings["materialized_artifact_id"],
            source_receipt_event_id=strings["source_receipt_event_id"],
            access_ordinal=access_ordinal,
        )


@dataclass(frozen=True, slots=True)
class RetrodictionRuntimeState:
    """Checkpointable derived runtime state; raw trace remains authoritative."""

    config: RetrodictionConfig
    access_ordinal: int = 0
    trigger_generations: tuple[tuple[str, int], ...] = ()
    cache_entries: tuple[RetrodictionCacheEntry, ...] = ()
    schema: str = RETRODICTION_CACHE_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != RETRODICTION_CACHE_SCHEMA:
            raise WorldModelError("retrodiction runtime schema is unsupported")
        if isinstance(self.access_ordinal, bool) or self.access_ordinal < 0:
            raise WorldModelError("retrodiction access ordinal must be non-negative")
        namespaces = [item[0] for item in self.trigger_generations]
        if len(set(namespaces)) != len(namespaces):
            raise WorldModelError("retrodiction trigger namespaces must be unique")
        if any(
            not key.strip() or isinstance(value, bool) or value < 0
            for key, value in self.trigger_generations
        ):
            raise WorldModelError("retrodiction trigger generation is malformed")
        cache_keys = [item.cache_key for item in self.cache_entries]
        if len(set(cache_keys)) != len(cache_keys):
            raise WorldModelError("retrodiction cache keys must be unique")
        access_ordinals = [item.access_ordinal for item in self.cache_entries]
        if len(set(access_ordinals)) != len(access_ordinals):
            raise WorldModelError("retrodiction cache access ordinals must be unique")
        if len(cache_keys) > self.config.capacity:
            raise WorldModelError("retrodiction cache exceeds configured capacity")
        if any(item.access_ordinal > self.access_ordinal for item in self.cache_entries):
            raise WorldModelError("cache entry access ordinal exceeds runtime ordinal")
        object.__setattr__(self, "trigger_generations", tuple(sorted(self.trigger_generations)))
        object.__setattr__(
            self,
            "cache_entries",
            tuple(sorted(self.cache_entries, key=lambda item: item.cache_key)),
        )

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "access_ordinal": self.access_ordinal,
            "cache_entries": [item.to_dict() for item in self.cache_entries],
            "config": self.config.to_dict(),
            "configuration_hash": self.config.configuration_hash,
            "schema": self.schema,
            "trigger_generations": [
                {"generation": generation, "namespace_key": namespace}
                for namespace, generation in self.trigger_generations
            ],
        }

    @classmethod
    def from_dict(cls, value: object) -> RetrodictionRuntimeState:
        if not isinstance(value, Mapping):
            raise WorldModelError("retrodiction runtime state must be an object")
        schema = value.get("schema")
        configuration_hash = value.get("configuration_hash")
        access_ordinal = value.get("access_ordinal")
        raw_generations = value.get("trigger_generations")
        raw_entries = value.get("cache_entries")
        if (
            not isinstance(schema, str)
            or not isinstance(configuration_hash, str)
            or isinstance(access_ordinal, bool)
            or not isinstance(access_ordinal, int)
            or not isinstance(raw_generations, list)
            or not isinstance(raw_entries, list)
        ):
            raise WorldModelError("retrodiction runtime state fields are malformed")
        generations: list[tuple[str, int]] = []
        for item in raw_generations:
            if not isinstance(item, Mapping):
                raise WorldModelError("retrodiction trigger generation must be an object")
            namespace = item.get("namespace_key")
            generation = item.get("generation")
            if (
                not isinstance(namespace, str)
                or isinstance(generation, bool)
                or not isinstance(generation, int)
            ):
                raise WorldModelError("retrodiction trigger generation fields are malformed")
            generations.append((namespace, generation))
        config = RetrodictionConfig.from_dict(value.get("config"))
        if configuration_hash != config.configuration_hash:
            raise WorldModelError("retrodiction configuration hash disagrees with config")
        return cls(
            config=config,
            access_ordinal=access_ordinal,
            trigger_generations=tuple(generations),
            cache_entries=tuple(RetrodictionCacheEntry.from_dict(item) for item in raw_entries),
            schema=schema,
        )


@dataclass(frozen=True, slots=True)
class RetrodictionRequest:
    """One candidate-specific, already partitioned and projected history request."""

    model: ModelCandidate
    transitions: tuple[PreservedTransition, ...]
    mechanics_epoch_id: str
    omissions: tuple[RetrodictionOmission, ...] = ()
    resolved_noise_transition_ids: tuple[str, ...] = ()
    force_full_source_event_ids: tuple[str, ...] = ()
    matched_evidence: tuple[MatchedPredictionEvidence, ...] = ()

    def __post_init__(self) -> None:
        _require_text(self.mechanics_epoch_id, field="mechanics_epoch_id")
        transition_ids = [item.transition_id for item in self.transitions]
        if len(set(transition_ids)) != len(transition_ids):
            raise WorldModelError("retrodiction request transitions must be unique")
        omitted_ids = [item.transition_id for item in self.omissions]
        if len(set(omitted_ids)) != len(omitted_ids):
            raise WorldModelError("retrodiction request omissions must be unique")
        if set(transition_ids) & set(omitted_ids):
            raise WorldModelError("a transition cannot be both eligible and omitted")
        if len(set(self.resolved_noise_transition_ids)) != len(self.resolved_noise_transition_ids):
            raise WorldModelError("resolved-noise transition IDs must be unique")
        if len(set(self.force_full_source_event_ids)) != len(self.force_full_source_event_ids):
            raise WorldModelError("force-full source event IDs must be unique")
        if any(not item.strip() for item in self.resolved_noise_transition_ids):
            raise WorldModelError("resolved-noise transition IDs must be non-empty")
        if any(not item.strip() for item in self.force_full_source_event_ids):
            raise WorldModelError("force-full source event IDs must be non-empty")
        evidence_ids = [item.transition_id for item in self.matched_evidence]
        if len(set(evidence_ids)) != len(evidence_ids):
            raise WorldModelError("matched prediction evidence must be transition-unique")


@dataclass(frozen=True, slots=True)
class RetrodictionPlan:
    """Pure scope decision made before the started trace receipt is appended."""

    request: RetrodictionRequest
    mode: RetrodictionMode
    reason: RetrodictionReason
    configuration_hash: str
    model_semantic_fingerprint: str
    namespace_key: str
    exclusion_identity: str
    full_history_hash: str
    full_transition_witnesses: tuple[bytes, ...]
    selected_history_hash: str
    selected_transitions: tuple[PreservedTransition, ...]
    selected_transition_witnesses: tuple[bytes, ...]
    omitted: tuple[RetrodictionOmission, ...]
    cache_key: str
    cache_hit: bool
    prefix_count: int
    suffix_count: int
    authorizing_matched_prediction_evidence: tuple[MatchedPredictionEvidence, ...]
    prior_entry: RetrodictionCacheEntry | None
    generation: int
    complete_scope: bool
    full_audit: bool
    state_access_ordinal: int

    def __post_init__(self) -> None:
        evidence = self.authorizing_matched_prediction_evidence
        if self.reason is not RetrodictionReason.EVENT_RECEIPT_REUSE:
            if evidence:
                raise WorldModelError(
                    "only event-receipt reuse may carry authorizing matched evidence"
                )
            return
        if self.mode is not RetrodictionMode.EVENT_TRIGGERED:
            raise WorldModelError("event-receipt reuse requires EVENT_TRIGGERED mode")
        if self.full_audit or not self.cache_hit or self.prior_entry is None:
            raise WorldModelError("event-receipt reuse requires a reusable cache prefix")
        expected_suffix = self.request.transitions[self.prefix_count :]
        if self.suffix_count != len(expected_suffix) or len(evidence) != len(expected_suffix):
            raise WorldModelError("authorizing evidence must cover the exact reused suffix")
        for transition, item in zip(expected_suffix, evidence, strict=True):
            if (
                item.transition_id != transition.transition_id
                or item.model_id != self.request.model.model_id
                or not item.matched
                or not item.source_ordered
                or item.match_scope not in EVENT_REUSE_MATCH_SCOPES
            ):
                raise WorldModelError(
                    "authorizing evidence must be ordered and bound to the reused suffix"
                )

    @property
    def prior_artifact_id(self) -> str | None:
        return self.prior_entry.materialized_artifact_id if self.prior_entry is not None else None

    @property
    def prior_source_receipt_event_id(self) -> str | None:
        return self.prior_entry.source_receipt_event_id if self.prior_entry is not None else None

    def to_trace_payload(self) -> dict[str, JSONValue]:
        return {
            "authorizing_matched_prediction_evidence": [
                item.to_dict() for item in self.authorizing_matched_prediction_evidence
            ],
            "cache_hit": self.cache_hit,
            "cache_key": self.cache_key,
            "complete_scope": self.complete_scope,
            "force_full_source_event_ids": list(self.request.force_full_source_event_ids),
            "full_audit": self.full_audit,
            "full_eligible_history_count": len(self.request.transitions),
            "full_eligible_history_hash": self.full_history_hash,
            "generation": self.generation,
            "mechanics_epoch_id": self.request.mechanics_epoch_id,
            "mode": self.mode.value,
            "model_id": self.request.model.model_id,
            "model_semantic_fingerprint": self.model_semantic_fingerprint,
            "omissions": [item.to_dict() for item in self.omitted],
            "prefix_count": self.prefix_count,
            "prior_artifact_id": self.prior_artifact_id,
            "prior_source_receipt_event_id": self.prior_source_receipt_event_id,
            "reason": self.reason.value,
            "resolved_noise_transition_ids": list(self.request.resolved_noise_transition_ids),
            "retrodiction_configuration_hash": self.configuration_hash,
            "selected_history_count": len(self.selected_transitions),
            "selected_history_hash": self.selected_history_hash,
            "selected_transition_ids": [item.transition_id for item in self.selected_transitions],
            "suffix_count": self.suffix_count,
        }


@dataclass(frozen=True, slots=True)
class RetrodictionEvaluation:
    """Executed result awaiting a durable completion receipt and runtime commit."""

    plan: RetrodictionPlan
    artifact: RetrodictionArtifact
    outcomes: tuple[TransitionOutcome, ...]
    reused: bool
    evicted_cache_keys: tuple[str, ...] = ()

    @property
    def prior_artifact_id(self) -> str | None:
        return self.plan.prior_artifact_id

    @property
    def prior_source_receipt_event_id(self) -> str | None:
        return self.plan.prior_source_receipt_event_id

    def to_trace_payload(self) -> dict[str, JSONValue]:
        return {
            **self.plan.to_trace_payload(),
            "artifact_id": self.artifact.artifact_id,
            "compatible_transition_ids": list(self.artifact.compatible_transition_ids),
            "contradiction_transition_ids": list(self.artifact.contradiction_transition_ids),
            "evicted_cache_keys": list(self.evicted_cache_keys),
            "explicitly_excluded_transition_ids": list(
                self.artifact.explicitly_excluded_transition_ids
            ),
            "matched_transition_ids": list(self.artifact.matched_transition_ids),
            "result_complete": self.artifact.complete,
            "reused": self.reused,
            "score": self.artifact.score.total,
            "status": self.artifact.status.value,
            "tested_transition_ids": list(self.artifact.tested_transition_ids),
            "weight_kind": self.artifact.score.weight_kind,
        }


def model_semantic_fingerprint(model: ModelCandidate) -> str:
    """Hash every field capable of changing evaluation or candidate ordering."""

    rules = [normalize_json(asdict(rule)) for rule in model.rules]
    return sha256_json(
        {
            "compile_residuals": list(model.compile_residuals),
            "hypothesis_ids": list(model.hypothesis_ids),
            "model_id": model.model_id,
            "rank_weight": model.rank_weight,
            "rules": rules,
        }
    )


def transition_witness(transition: PreservedTransition) -> bytes:
    """Return the exact canonical projected transition prefix witness."""

    coordinate = transition.action.coordinate
    return canonical_bytes(
        {
            "action": {
                "coordinate": (
                    {"x": coordinate.x, "y": coordinate.y} if coordinate is not None else None
                ),
                "name": transition.action.name.value,
            },
            "after_state_id": transition.after.state_id,
            "before_state_id": transition.before.state_id,
            "compatible_model_ids": list(transition.compatible_model_ids),
            "source_event_ids": list(transition.source_event_ids),
            "transition_id": transition.transition_id,
        }
    )


def _prefix_hash(witnesses: tuple[bytes, ...]) -> str:
    return sha256_json([item.hex() for item in witnesses])


def _exclusion_identity_from_parts(
    omissions: tuple[RetrodictionOmission, ...],
    resolved_noise_transition_ids: tuple[str, ...],
) -> str:
    return sha256_json(
        {
            "omissions": [item.to_dict() for item in omissions],
            "resolved_noise_transition_ids": list(resolved_noise_transition_ids),
        }
    )


def _exclusion_identity(request: RetrodictionRequest) -> str:
    return _exclusion_identity_from_parts(
        request.omissions,
        request.resolved_noise_transition_ids,
    )


def _history_key(
    witnesses: tuple[bytes, ...],
    *,
    exclusion_identity: str,
) -> str:
    return sha256_json(
        {
            "exclusion_identity": exclusion_identity,
            "transition_witnesses_hex": [item.hex() for item in witnesses],
        }
    )


def _namespace_key_from_parts(
    config: RetrodictionConfig,
    *,
    model_id: str,
    semantic_fingerprint: str,
    mechanics_epoch_id: str,
    projection_version: str,
) -> str:
    return sha256_json(
        {
            "global_retrodiction_configuration_hash": config.configuration_hash,
            "mechanics_epoch_id": mechanics_epoch_id,
            "mode": config.mode.value,
            "model_id": model_id,
            "model_semantic_fingerprint": semantic_fingerprint,
            "projection_version": projection_version,
            "window": config.window,
        }
    )


def _namespace_key(
    config: RetrodictionConfig,
    request: RetrodictionRequest,
    *,
    semantic_fingerprint: str,
) -> str:
    return _namespace_key_from_parts(
        config,
        model_id=request.model.model_id,
        semantic_fingerprint=semantic_fingerprint,
        mechanics_epoch_id=request.mechanics_epoch_id,
        projection_version=config.projection_version,
    )


def _cache_key(namespace_key: str, history_key: str) -> str:
    return sha256_json({"history_key": history_key, "namespace_key": namespace_key})


class RetrodictionRuntime:
    """Deterministic bounded runtime; cache affects cost but never FULL semantics."""

    def __init__(
        self,
        config: RetrodictionConfig | None = None,
        *,
        state: RetrodictionRuntimeState | None = None,
    ) -> None:
        config = RetrodictionConfig() if config is None else config
        if state is not None and state.config != config:
            raise WorldModelError("retrodiction runtime state/config mismatch")
        self._state = state or RetrodictionRuntimeState(config)
        self._validate_state()

    @property
    def config(self) -> RetrodictionConfig:
        return self._state.config

    @property
    def state(self) -> RetrodictionRuntimeState:
        return self._state

    def to_dict(self) -> dict[str, JSONValue]:
        return self._state.to_dict()

    @classmethod
    def from_dict(
        cls,
        value: object,
        *,
        expected_config: RetrodictionConfig,
    ) -> RetrodictionRuntime:
        state = RetrodictionRuntimeState.from_dict(value)
        if state.config != expected_config:
            raise WorldModelError("checkpoint retrodiction config does not match controller")
        return cls(expected_config, state=state)

    def plan(self, request: RetrodictionRequest) -> RetrodictionPlan:
        """Choose one exact scope without mutating checkpointable state."""

        semantic = model_semantic_fingerprint(request.model)
        namespace = _namespace_key(self.config, request, semantic_fingerprint=semantic)
        exclusion = _exclusion_identity(request)
        witnesses = tuple(transition_witness(item) for item in request.transitions)
        full_history = _history_key(witnesses, exclusion_identity=exclusion)
        current_cache_key = _cache_key(namespace, full_history)
        generation = dict(self._state.trigger_generations).get(namespace, 0)
        namespace_entries = tuple(
            item for item in self._state.cache_entries if item.namespace_key == namespace
        )
        exact = next(
            (
                item
                for item in namespace_entries
                if item.exclusion_identity == exclusion
                and item.transition_witnesses == witnesses
                and item.history_key == full_history
            ),
            None,
        )
        prefixes = tuple(
            item
            for item in namespace_entries
            if item.exclusion_identity == exclusion
            and item.prefix_length < len(witnesses)
            and item.transition_witnesses == witnesses[: item.prefix_length]
            and item.prefix_hash == _prefix_hash(witnesses[: item.prefix_length])
        )
        prefix = max(prefixes, key=lambda item: (item.prefix_length, item.cache_key), default=None)

        mode = self.config.mode
        selected = request.transitions
        selected_witnesses = witnesses
        prior: RetrodictionCacheEntry | None = None
        cache_hit = False
        prefix_count = 0
        suffix_count = len(request.transitions)
        complete_scope = True
        full_audit = True
        reason = RetrodictionReason.FULL
        omitted = request.omissions
        authorizing_evidence: tuple[MatchedPredictionEvidence, ...] = ()

        invalidated = bool(request.force_full_source_event_ids)
        if mode is RetrodictionMode.NONE:
            selected = ()
            selected_witnesses = ()
            suffix_count = 0
            complete_scope = False
            full_audit = False
            reason = RetrodictionReason.DISABLED
        elif mode is RetrodictionMode.RECENT_WINDOW_8:
            selected = request.transitions[-self.config.window :]
            selected_witnesses = witnesses[-self.config.window :]
            bounded = request.transitions[: max(0, len(request.transitions) - self.config.window)]
            omitted = (
                *request.omissions,
                *(
                    RetrodictionOmission(
                        item.transition_id,
                        f"recent-window-{self.config.window}",
                    )
                    for item in bounded
                ),
            )
            suffix_count = len(selected)
            complete_scope = False
            full_audit = False
            reason = RetrodictionReason.RECENT_WINDOW
        elif mode is RetrodictionMode.CACHED_INCREMENTAL:
            if invalidated:
                reason = RetrodictionReason.INVALIDATED
            elif exact is not None:
                prior = exact
                cache_hit = True
                prefix_count = exact.prefix_length
                suffix_count = 0
                full_audit = False
                reason = RetrodictionReason.EXACT_CACHE_HIT
            elif prefix is not None:
                prior = prefix
                cache_hit = True
                prefix_count = prefix.prefix_length
                suffix_count = len(request.transitions) - prefix.prefix_length
                full_audit = False
                reason = RetrodictionReason.PREFIX_EXTENSION
            elif namespace_entries:
                reason = RetrodictionReason.NON_PREFIX
            else:
                reason = RetrodictionReason.FIRST_USE
        elif mode is RetrodictionMode.EVENT_TRIGGERED:
            if invalidated:
                reason = RetrodictionReason.EVENT_FULL_AUDIT
            elif exact is not None:
                prior = exact
                cache_hit = True
                prefix_count = exact.prefix_length
                suffix_count = 0
                full_audit = False
                reason = RetrodictionReason.EXACT_CACHE_HIT
            elif prefix is not None:
                suffix_evidence = self._authorizing_event_evidence_for_suffix(request, prefix)
                if suffix_evidence is not None:
                    prior = prefix
                    cache_hit = True
                    prefix_count = prefix.prefix_length
                    suffix_count = len(request.transitions) - prefix.prefix_length
                    full_audit = False
                    reason = RetrodictionReason.EVENT_RECEIPT_REUSE
                    authorizing_evidence = suffix_evidence
                else:
                    reason = RetrodictionReason.EVENT_FULL_AUDIT
            elif namespace_entries:
                reason = RetrodictionReason.EVENT_FULL_AUDIT
            else:
                reason = RetrodictionReason.FIRST_USE

        if full_audit:
            generation += 1
        selected_history = _history_key(
            selected_witnesses,
            exclusion_identity=exclusion,
        )
        return RetrodictionPlan(
            request=request,
            mode=mode,
            reason=reason,
            configuration_hash=self.config.configuration_hash,
            model_semantic_fingerprint=semantic,
            namespace_key=namespace,
            exclusion_identity=exclusion,
            full_history_hash=full_history,
            full_transition_witnesses=witnesses,
            selected_history_hash=selected_history,
            selected_transitions=selected,
            selected_transition_witnesses=selected_witnesses,
            omitted=tuple(omitted),
            cache_key=current_cache_key,
            cache_hit=cache_hit,
            prefix_count=prefix_count,
            suffix_count=suffix_count,
            authorizing_matched_prediction_evidence=authorizing_evidence,
            prior_entry=prior,
            generation=generation,
            complete_scope=complete_scope,
            full_audit=full_audit,
            state_access_ordinal=self._state.access_ordinal,
        )

    def execute(self, plan: RetrodictionPlan) -> RetrodictionEvaluation:
        """Execute a prepared plan without committing derived cache state."""

        if plan.state_access_ordinal != self._state.access_ordinal:
            raise WorldModelError("retrodiction plan is stale")
        if plan.mode is not self.config.mode:
            raise WorldModelError("retrodiction plan mode disagrees with runtime")
        if plan.configuration_hash != self.config.configuration_hash:
            raise WorldModelError("retrodiction plan configuration disagrees with runtime")
        model = plan.request.model
        reused = False
        if plan.mode is RetrodictionMode.NONE:
            outcomes: tuple[TransitionOutcome, ...] = ()
            artifact = _materialize_artifact(
                model,
                plan.request.transitions,
                outcomes,
                enabled=False,
            )
        elif plan.mode is RetrodictionMode.RECENT_WINDOW_8:
            outcomes = _evaluate_outcomes(model, plan.selected_transitions)
            artifact = _materialize_artifact(
                model,
                plan.selected_transitions,
                outcomes,
                enabled=True,
            )
        elif plan.prior_entry is not None and not plan.full_audit:
            prior = plan.prior_entry
            suffix = plan.request.transitions[prior.prefix_length :]
            suffix_outcomes = _evaluate_outcomes(model, suffix)
            outcomes = (*prior.outcomes, *suffix_outcomes)
            artifact = _materialize_artifact(
                model,
                plan.request.transitions,
                tuple(outcomes),
                enabled=True,
            )
            if not suffix and artifact.artifact_id != prior.materialized_artifact_id:
                raise WorldModelError("cached artifact identity does not rematerialize exactly")
            reused = True
        else:
            outcomes = _evaluate_outcomes(model, plan.request.transitions)
            artifact = _materialize_artifact(
                model,
                plan.request.transitions,
                outcomes,
                enabled=True,
            )

        evicted: tuple[str, ...] = ()
        if plan.mode in {
            RetrodictionMode.EVENT_TRIGGERED,
            RetrodictionMode.CACHED_INCREMENTAL,
        }:
            retained = [
                item for item in self._state.cache_entries if item.cache_key != plan.cache_key
            ]
            overflow = max(0, len(retained) + 1 - self.config.capacity)
            victims = sorted(retained, key=lambda item: (item.access_ordinal, item.cache_key))[
                :overflow
            ]
            evicted = tuple(item.cache_key for item in victims)
        return RetrodictionEvaluation(plan, artifact, tuple(outcomes), reused, evicted)

    def commit(
        self,
        evaluation: RetrodictionEvaluation,
        *,
        source_receipt_event_id: str,
    ) -> None:
        """Commit cost state only after its immutable completion receipt exists."""

        _require_text(source_receipt_event_id, field="source_receipt_event_id")
        plan = evaluation.plan
        if plan.state_access_ordinal != self._state.access_ordinal:
            raise WorldModelError("retrodiction evaluation commit is stale")
        next_ordinal = self._state.access_ordinal + 1
        generations = dict(self._state.trigger_generations)
        generations[plan.namespace_key] = plan.generation
        entries = {
            item.cache_key: item
            for item in self._state.cache_entries
            if item.cache_key not in set(evaluation.evicted_cache_keys)
        }
        if plan.mode in {
            RetrodictionMode.EVENT_TRIGGERED,
            RetrodictionMode.CACHED_INCREMENTAL,
        }:
            entry = RetrodictionCacheEntry(
                cache_key=plan.cache_key,
                namespace_key=plan.namespace_key,
                configuration_hash=plan.configuration_hash,
                model_id=plan.request.model.model_id,
                model_semantic_fingerprint=plan.model_semantic_fingerprint,
                mechanics_epoch_id=plan.request.mechanics_epoch_id,
                projection_version=self.config.projection_version,
                history_key=plan.full_history_hash,
                exclusion_identity=plan.exclusion_identity,
                resolved_noise_transition_ids=plan.request.resolved_noise_transition_ids,
                omissions=plan.request.omissions,
                prefix_length=len(plan.request.transitions),
                prefix_hash=_prefix_hash(plan.full_transition_witnesses),
                transition_witnesses=plan.full_transition_witnesses,
                outcomes=evaluation.outcomes,
                materialized_artifact_id=evaluation.artifact.artifact_id,
                source_receipt_event_id=source_receipt_event_id,
                access_ordinal=next_ordinal,
            )
            entries[entry.cache_key] = entry
        self._state = RetrodictionRuntimeState(
            config=self.config,
            access_ordinal=next_ordinal,
            trigger_generations=tuple(generations.items()),
            cache_entries=tuple(entries.values()),
        )
        self._validate_state()

    def _authorizing_event_evidence_for_suffix(
        self,
        request: RetrodictionRequest,
        prefix: RetrodictionCacheEntry,
    ) -> tuple[MatchedPredictionEvidence, ...] | None:
        evidence = {item.transition_id: item for item in request.matched_evidence}
        suffix = request.transitions[prefix.prefix_length :]
        authorizing: list[MatchedPredictionEvidence] = []
        for transition in suffix:
            item = evidence.get(transition.transition_id)
            if (
                item is None
                or item.model_id != request.model.model_id
                or not item.matched
                or not item.source_ordered
                or item.match_scope not in EVENT_REUSE_MATCH_SCOPES
            ):
                return None
            authorizing.append(item)
        return tuple(authorizing)

    def _validate_state(self) -> None:
        for entry in self._state.cache_entries:
            if entry.configuration_hash != self.config.configuration_hash:
                raise WorldModelError("cache configuration hash disagrees with runtime")
            if entry.projection_version != self.config.projection_version:
                raise WorldModelError("cache projection version disagrees with runtime")
            expected_namespace = _namespace_key_from_parts(
                self.config,
                model_id=entry.model_id,
                semantic_fingerprint=entry.model_semantic_fingerprint,
                mechanics_epoch_id=entry.mechanics_epoch_id,
                projection_version=entry.projection_version,
            )
            if entry.namespace_key != expected_namespace:
                raise WorldModelError("cache namespace disagrees with typed identities")
            expected_history = _history_key(
                entry.transition_witnesses,
                exclusion_identity=entry.exclusion_identity,
            )
            if entry.history_key != expected_history:
                raise WorldModelError("cache history key disagrees with exact witnesses")
            if entry.cache_key != _cache_key(entry.namespace_key, entry.history_key):
                raise WorldModelError("cache key disagrees with namespace/history identity")


def _residual_to_dict(residual: StateResidual) -> dict[str, JSONValue]:
    return {
        "attachment_mismatch": residual.attachment_mismatch,
        "changed_counters": list(residual.changed_counters),
        "changed_entities": list(residual.changed_entities),
        "changed_toggles": list(residual.changed_toggles),
        "missing_entities": list(residual.missing_entities),
        "missing_facts": list(residual.missing_facts),
        "selection_mismatch": residual.selection_mismatch,
        "transition_id": residual.transition_id,
        "unexpected_entities": list(residual.unexpected_entities),
        "unexpected_facts": list(residual.unexpected_facts),
    }


def _residual_from_dict(value: object) -> StateResidual:
    if not isinstance(value, Mapping):
        raise WorldModelError("retrodiction residual must be an object")

    def strings(field: str) -> tuple[str, ...]:
        raw = value.get(field)
        if not isinstance(raw, list) or not all(isinstance(item, str) for item in raw):
            raise WorldModelError(f"retrodiction residual {field} is malformed")
        return tuple(cast(list[str], raw))

    transition_id = value.get("transition_id")
    selection_mismatch = value.get("selection_mismatch")
    attachment_mismatch = value.get("attachment_mismatch")
    if (
        not isinstance(transition_id, str)
        or not isinstance(selection_mismatch, bool)
        or not isinstance(attachment_mismatch, bool)
    ):
        raise WorldModelError("retrodiction residual scalar fields are malformed")
    return StateResidual(
        transition_id=transition_id,
        missing_entities=strings("missing_entities"),
        unexpected_entities=strings("unexpected_entities"),
        changed_entities=strings("changed_entities"),
        missing_facts=strings("missing_facts"),
        unexpected_facts=strings("unexpected_facts"),
        changed_counters=strings("changed_counters"),
        changed_toggles=strings("changed_toggles"),
        selection_mismatch=selection_mismatch,
        attachment_mismatch=attachment_mismatch,
    )


def _evaluate_outcomes(
    model: ModelCandidate,
    transitions: tuple[PreservedTransition, ...],
) -> tuple[TransitionOutcome, ...]:
    outcomes: list[TransitionOutcome] = []
    for transition in transitions:
        if model.has_explicit_exclusion(transition.before, transition.action):
            outcomes.append(
                TransitionOutcome(transition.transition_id, TransitionOutcomeKind.EXCLUDED)
            )
            continue
        prediction = model.predict(transition.before, transition.action)
        if prediction.after_state == transition.after:
            outcomes.append(
                TransitionOutcome(transition.transition_id, TransitionOutcomeKind.MATCHED)
            )
        else:
            outcomes.append(
                TransitionOutcome(
                    transition.transition_id,
                    TransitionOutcomeKind.CONTRADICTED,
                    compare_states(
                        transition.transition_id,
                        prediction.after_state,
                        transition.after,
                    ),
                )
            )
    return tuple(outcomes)


def _materialize_artifact(
    model: ModelCandidate,
    transitions: tuple[PreservedTransition, ...],
    outcomes: tuple[TransitionOutcome, ...],
    *,
    enabled: bool,
) -> RetrodictionArtifact:
    compatible_ids = tuple(item.transition_id for item in transitions)
    outcome_ids = tuple(item.transition_id for item in outcomes)
    if enabled and outcome_ids != compatible_ids:
        raise WorldModelError("retrodiction outcomes do not cover the exact compatible history")
    if not enabled and outcomes:
        raise WorldModelError("disabled retrodiction cannot contain evaluated outcomes")
    tested = [
        item.transition_id for item in outcomes if item.kind is not TransitionOutcomeKind.EXCLUDED
    ]
    excluded = [
        item.transition_id for item in outcomes if item.kind is TransitionOutcomeKind.EXCLUDED
    ]
    matched = [
        item.transition_id for item in outcomes if item.kind is TransitionOutcomeKind.MATCHED
    ]
    contradicted = [
        item.transition_id for item in outcomes if item.kind is TransitionOutcomeKind.CONTRADICTED
    ]
    residuals = [item.residual for item in outcomes if item.residual is not None]
    fit = len(matched) / len(tested) if tested else 0.0
    observed_residual_mass = sum(max(residual.count, 1) for residual in residuals)
    residual_coverage = (
        len(matched) / (len(matched) + observed_residual_mass)
        if matched or observed_residual_mass
        else 0.0
    )
    score = ModelScore(
        fit=fit,
        complexity=model.complexity,
        contradictions=len(contradicted),
        residual_coverage=residual_coverage,
        rank_weight=model.rank_weight,
        total=round(
            100.0 * fit
            + 20.0 * residual_coverage
            + float(model.rank_weight)
            - float(model.complexity)
            - 100.0 * len(contradicted),
            9,
        ),
    )
    complete = len(tested) + len(excluded) == len(compatible_ids)
    if not enabled:
        status = PromotionStatus.UNGATED_ABLATION
    elif complete and tested and not contradicted:
        status = PromotionStatus.PROMOTED
    else:
        status = PromotionStatus.REJECTED
    content = {
        "model_id": model.model_id,
        "enabled": enabled,
        "compatible": list(compatible_ids),
        "tested": tested,
        "excluded": excluded,
        "matched": matched,
        "contradicted": contradicted,
        "status": status.value,
    }
    digest = sha256_json(content)
    return RetrodictionArtifact(
        artifact_id=f"retrodiction:{digest.removeprefix('sha256:')[:24]}",
        model_id=model.model_id,
        retrodiction_enabled=enabled,
        compatible_transition_ids=compatible_ids,
        tested_transition_ids=tuple(tested),
        explicitly_excluded_transition_ids=tuple(excluded),
        matched_transition_ids=tuple(matched),
        contradiction_transition_ids=tuple(contradicted),
        residuals=tuple(residuals),
        score=score,
        status=status,
        complete=complete,
    )


def retrodict(
    model: ModelCandidate,
    transitions: tuple[PreservedTransition, ...],
    *,
    enabled: bool = True,
) -> RetrodictionArtifact:
    """Evaluate every compatible transition or record its explicit condition exclusion."""

    compatible = tuple(item for item in transitions if item.is_compatible_with(model.model_id))
    outcomes = _evaluate_outcomes(model, compatible) if enabled else ()
    return _materialize_artifact(model, compatible, outcomes, enabled=enabled)


def gated_ensemble(
    candidates: tuple[ModelCandidate, ...],
    artifacts: tuple[RetrodictionArtifact, ...],
    *,
    allow_ungated_ablation: bool = False,
) -> WorldModelEnsemble:
    """Build an ensemble only from candidates with matching gate artifacts."""

    artifacts_by_model = {artifact.model_id: artifact for artifact in artifacts}
    accepted = []
    for candidate in candidates:
        artifact = artifacts_by_model.get(candidate.model_id)
        if artifact is None:
            continue
        if artifact.promotable or (
            allow_ungated_ablation and artifact.status is PromotionStatus.UNGATED_ABLATION
        ):
            accepted.append(candidate)
    return WorldModelEnsemble(tuple(accepted))


def compare_states(
    transition_id: str, predicted: SymbolicState, observed: SymbolicState
) -> StateResidual:
    predicted_entities = {item.entity_id: item for item in predicted.entities}
    observed_entities = {item.entity_id: item for item in observed.entities}
    common = set(predicted_entities) & set(observed_entities)
    return StateResidual(
        transition_id=transition_id,
        missing_entities=tuple(sorted(set(observed_entities) - set(predicted_entities))),
        unexpected_entities=tuple(sorted(set(predicted_entities) - set(observed_entities))),
        changed_entities=tuple(
            sorted(key for key in common if predicted_entities[key] != observed_entities[key])
        ),
        missing_facts=tuple(sorted(set(observed.facts) - set(predicted.facts))),
        unexpected_facts=tuple(sorted(set(predicted.facts) - set(observed.facts))),
        changed_counters=tuple(
            sorted(
                key
                for key in set(dict(predicted.counters)) | set(dict(observed.counters))
                if dict(predicted.counters).get(key) != dict(observed.counters).get(key)
            )
        ),
        changed_toggles=tuple(
            sorted(
                key
                for key in set(dict(predicted.toggles)) | set(dict(observed.toggles))
                if dict(predicted.toggles).get(key) != dict(observed.toggles).get(key)
            )
        ),
        selection_mismatch=predicted.selected_id != observed.selected_id,
        attachment_mismatch=predicted.attachments != observed.attachments,
    )


__all__ = [
    "MatchedPredictionEvidence",
    "ModelScore",
    "PreservedTransition",
    "PromotionStatus",
    "RetrodictionArtifact",
    "RetrodictionCacheEntry",
    "RetrodictionConfig",
    "RetrodictionEvaluation",
    "RetrodictionMode",
    "RetrodictionOmission",
    "RetrodictionPlan",
    "RetrodictionReason",
    "RetrodictionRequest",
    "RetrodictionRuntime",
    "RetrodictionRuntimeState",
    "StateResidual",
    "TransitionOutcome",
    "TransitionOutcomeKind",
    "compare_states",
    "gated_ensemble",
    "model_semantic_fingerprint",
    "retrodict",
    "transition_witness",
]
