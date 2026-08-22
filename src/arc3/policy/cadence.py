"""Deterministic Stage 08 reasoning cadence and bounded derived-value cache.

This module is intentionally independent of the controller and trace writer.  It
selects a reasoning path from typed evidence signals and integer counters only;
elapsed time is telemetry owned by the caller, never a policy input.  Cached
values are explicitly derived computations and cannot carry trace receipts or
authority-bearing fields.
"""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Mapping
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import cast

from arc3.errors import PolicyError, WorldModelError
from arc3.trace.canonical import sha256_json
from arc3.types import ActionName, ActionRequest, Coordinate, JSONValue
from arc3.world_model.model import AlternativeOutcome, EnsemblePrediction
from arc3.world_model.state import Attachment, Cell, SymbolicEntity, SymbolicState

CADENCE_CONFIG_SCHEMA = "arc3.reasoning-cadence-config.v0.1"
CADENCE_STATE_SCHEMA = "arc3.reasoning-cadence-state.v0.1"
CADENCE_SELECTION_SCHEMA = "arc3.reasoning-cadence-selection.v0.1"
CACHE_KEY_SCHEMA = "arc3.reasoning-cache-key.v0.1"
CACHE_VALUE_SCHEMA = "arc3.reasoning-cache-value.v0.1"
CACHE_STATE_SCHEMA = "arc3.reasoning-cache-state.v0.1"


class DeliberationMode(StrEnum):
    """Predeclared Stage 08 controller cadence variants."""

    LEGACY_ALWAYS_DEEP = "LEGACY_ALWAYS_DEEP"
    TWO_SPEED = "TWO_SPEED"


class ReasoningPath(StrEnum):
    """The selected amount of derived reasoning for one observation."""

    FAST = "FAST"
    DEEP = "DEEP"


class DeepTrigger(StrEnum):
    """Closed, priority-ordered reasons that authorize the deep path."""

    STARTUP_UNKNOWN_ACTION = "STARTUP_UNKNOWN_ACTION"
    REOPENING = "REOPENING"
    MEANINGFUL_CONTRADICTION = "MEANINGFUL_CONTRADICTION"
    STRUCTURAL_NOVELTY = "STRUCTURAL_NOVELTY"
    NO_VALID_PLAN = "NO_VALID_PLAN"
    HIGH_GOAL_UNCERTAINTY = "HIGH_GOAL_UNCERTAINTY"
    REPEATED_NO_PROGRESS = "REPEATED_NO_PROGRESS"
    MAX_FAST_STREAK = "MAX_FAST_STREAK"


DEEP_TRIGGER_PRIORITY: tuple[DeepTrigger, ...] = tuple(DeepTrigger)


class DeliberationStatus(StrEnum):
    """Terminal status recorded for a selected reasoning path."""

    COMPLETED = "COMPLETED"
    FALLBACK_USED = "FALLBACK_USED"
    BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"
    FAILED = "FAILED"


class CacheValueKind(StrEnum):
    """Complete-key namespaces; Stage 08 implements only ``PREDICTION`` values."""

    PREDICTION = "PREDICTION"
    GOAL_PROGRESS = "GOAL_PROGRESS"
    REUSABLE_PLAN = "REUSABLE_PLAN"


class CacheInvalidationReason(StrEnum):
    """Predeclared events that invalidate reusable derived computation."""

    PREDICTION_MISMATCH = "PREDICTION_MISMATCH"
    HYPOTHESIS_CONTRADICTION_OR_REOPENING = "HYPOTHESIS_CONTRADICTION_OR_REOPENING"
    MODEL_STATUS_CHANGE = "MODEL_STATUS_CHANGE"
    MECHANICS_EPOCH_CHANGE = "MECHANICS_EPOCH_CHANGE"
    GOAL_REVISION = "GOAL_REVISION"
    ACTION_SPACE_OR_CALIBRATION_CHANGE = "ACTION_SPACE_OR_CALIBRATION_CHANGE"
    LEVEL_TRANSITION_OR_RESET = "LEVEL_TRANSITION_OR_RESET"
    SOURCE_OR_CONFIGURATION_CHANGE = "SOURCE_OR_CONFIGURATION_CHANGE"


def _require_text(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PolicyError(f"{field} must be a non-empty string")
    return value


def _require_non_negative_int(value: object, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise PolicyError(f"{field} must be a non-negative integer")
    return value


def _require_positive_int(value: object, *, field: str) -> int:
    parsed = _require_non_negative_int(value, field=field)
    if parsed < 1:
        raise PolicyError(f"{field} must be a positive integer")
    return parsed


def _require_bool(value: object, *, field: str) -> bool:
    if not isinstance(value, bool):
        raise PolicyError(f"{field} must be a boolean")
    return value


def _require_exact_keys(
    value: Mapping[str, object],
    expected: set[str],
    *,
    field: str,
) -> None:
    actual = set(value)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise PolicyError(f"{field} keys disagree; missing={missing}, extra={extra}")


def _normalize_source_ids(values: tuple[str, ...], *, field: str) -> tuple[str, ...]:
    for value in values:
        _require_text(value, field=field)
    return tuple(sorted(set(values)))


def _parse_string_array(value: object, *, field: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise PolicyError(f"{field} must be an array of strings")
    return _normalize_source_ids(tuple(cast(list[str], value)), field=field)


def _parse_ordered_unique_string_array(value: object, *, field: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise PolicyError(f"{field} must be an array of strings")
    parsed = tuple(cast(list[str], value))
    for item in parsed:
        _require_text(item, field=field)
    if len(set(parsed)) != len(parsed):
        raise PolicyError(f"{field} must not contain duplicates")
    return parsed


@dataclass(frozen=True, slots=True)
class CadenceConfig:
    """Complete deterministic identity of the Stage 08 cadence policy."""

    mode: DeliberationMode = DeliberationMode.TWO_SPEED
    maximum_fast_streak: int = 4
    repeated_no_progress_threshold: int = 2
    prediction_cache_enabled: bool = True
    cache_capacity: int = 256
    schema: str = CADENCE_CONFIG_SCHEMA

    def __post_init__(self) -> None:
        if not isinstance(self.mode, DeliberationMode):
            raise PolicyError("cadence mode must be a DeliberationMode")
        if self.schema != CADENCE_CONFIG_SCHEMA:
            raise PolicyError("cadence config schema is unsupported")
        _require_positive_int(self.maximum_fast_streak, field="maximum_fast_streak")
        _require_positive_int(
            self.repeated_no_progress_threshold,
            field="repeated_no_progress_threshold",
        )
        _require_bool(self.prediction_cache_enabled, field="prediction_cache_enabled")
        _require_positive_int(self.cache_capacity, field="cache_capacity")

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "cache_capacity": self.cache_capacity,
            "maximum_fast_streak": self.maximum_fast_streak,
            "mode": self.mode.value,
            "prediction_cache_enabled": self.prediction_cache_enabled,
            "repeated_no_progress_threshold": self.repeated_no_progress_threshold,
            "schema": self.schema,
        }

    @property
    def configuration_hash(self) -> str:
        return sha256_json(self.to_dict())

    @classmethod
    def from_dict(cls, value: object) -> CadenceConfig:
        if not isinstance(value, Mapping):
            raise PolicyError("cadence config must be an object")
        _require_exact_keys(
            value,
            {
                "cache_capacity",
                "maximum_fast_streak",
                "mode",
                "prediction_cache_enabled",
                "repeated_no_progress_threshold",
                "schema",
            },
            field="cadence config",
        )
        raw_mode = _require_text(value.get("mode"), field="cadence mode")
        try:
            mode = DeliberationMode(raw_mode)
        except ValueError as error:
            raise PolicyError("cadence mode is unsupported") from error
        return cls(
            mode=mode,
            maximum_fast_streak=_require_positive_int(
                value.get("maximum_fast_streak"),
                field="maximum_fast_streak",
            ),
            repeated_no_progress_threshold=_require_positive_int(
                value.get("repeated_no_progress_threshold"),
                field="repeated_no_progress_threshold",
            ),
            prediction_cache_enabled=_require_bool(
                value.get("prediction_cache_enabled"),
                field="prediction_cache_enabled",
            ),
            cache_capacity=_require_positive_int(
                value.get("cache_capacity"), field="cache_capacity"
            ),
            schema=_require_text(value.get("schema"), field="cadence config schema"),
        )


@dataclass(frozen=True, slots=True)
class CadenceSignals:
    """Current typed evidence inputs to cadence selection.

    Trigger fields contain immutable source event IDs.  State-derived triggers
    use ``observation_event_id`` as their source.  No elapsed-time field exists.
    """

    observation_event_id: str
    state_id: str
    mechanics_epoch_id: str
    goal_id: str | None
    goal_revision: int
    plan_id: str | None
    has_valid_plan: bool
    startup_unknown_action_event_ids: tuple[str, ...] = ()
    reopening_event_ids: tuple[str, ...] = ()
    meaningful_contradiction_event_ids: tuple[str, ...] = ()
    structural_novelty_event_ids: tuple[str, ...] = ()
    high_goal_uncertainty_event_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_text(self.observation_event_id, field="observation_event_id")
        _require_text(self.state_id, field="state_id")
        _require_text(self.mechanics_epoch_id, field="mechanics_epoch_id")
        _require_non_negative_int(self.goal_revision, field="goal_revision")
        _require_bool(self.has_valid_plan, field="has_valid_plan")
        if self.goal_id is not None:
            _require_text(self.goal_id, field="goal_id")
        if self.plan_id is not None:
            _require_text(self.plan_id, field="plan_id")
        if self.has_valid_plan and self.plan_id is None:
            raise PolicyError("a valid plan requires plan_id")
        for field in (
            "startup_unknown_action_event_ids",
            "reopening_event_ids",
            "meaningful_contradiction_event_ids",
            "structural_novelty_event_ids",
            "high_goal_uncertainty_event_ids",
        ):
            object.__setattr__(
                self,
                field,
                _normalize_source_ids(
                    cast(tuple[str, ...], getattr(self, field)),
                    field=field,
                ),
            )


@dataclass(frozen=True, slots=True)
class CadenceSelection:
    """Pure path selection, ready to be embedded in an immutable receipt."""

    configuration_hash: str
    path: ReasoningPath
    ordered_triggers: tuple[DeepTrigger, ...]
    trigger_sources: tuple[tuple[DeepTrigger, tuple[str, ...]], ...]
    state_id: str
    mechanics_epoch_id: str
    goal_id: str | None
    goal_revision: int
    plan_id: str | None
    schema: str = CADENCE_SELECTION_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != CADENCE_SELECTION_SCHEMA:
            raise PolicyError("cadence selection schema is unsupported")
        for field, value in (
            ("configuration_hash", self.configuration_hash),
            ("state_id", self.state_id),
            ("mechanics_epoch_id", self.mechanics_epoch_id),
        ):
            _require_text(value, field=field)
        if not isinstance(self.path, ReasoningPath):
            raise PolicyError("reasoning path must be typed")
        _require_non_negative_int(self.goal_revision, field="goal_revision")
        if self.goal_id is not None:
            _require_text(self.goal_id, field="goal_id")
        if self.plan_id is not None:
            _require_text(self.plan_id, field="plan_id")
        expected = tuple(
            trigger for trigger in DEEP_TRIGGER_PRIORITY if trigger in self.ordered_triggers
        )
        if self.ordered_triggers != expected or len(set(self.ordered_triggers)) != len(
            self.ordered_triggers
        ):
            raise PolicyError("deep triggers are not unique and priority ordered")
        if self.path is ReasoningPath.FAST and self.ordered_triggers:
            raise PolicyError("FAST cannot carry a deep trigger")
        source_triggers = tuple(trigger for trigger, _ids in self.trigger_sources)
        if source_triggers != self.ordered_triggers:
            raise PolicyError("trigger source ordering disagrees with selected triggers")
        normalized_sources = tuple(
            (
                trigger,
                _normalize_source_ids(ids, field=f"{trigger.value} source_event_id"),
            )
            for trigger, ids in self.trigger_sources
        )
        if normalized_sources != self.trigger_sources:
            raise PolicyError("trigger source IDs must be unique and sorted")
        if any(not ids for _trigger, ids in self.trigger_sources):
            raise PolicyError("every active deep trigger requires a source event ID")

    @property
    def trigger_source_event_ids(self) -> tuple[str, ...]:
        seen: set[str] = set()
        ordered: list[str] = []
        for _trigger, source_ids in self.trigger_sources:
            for source_id in source_ids:
                if source_id not in seen:
                    seen.add(source_id)
                    ordered.append(source_id)
        return tuple(ordered)

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "configuration_hash": self.configuration_hash,
            "goal_id": self.goal_id,
            "goal_revision": self.goal_revision,
            "mechanics_epoch_id": self.mechanics_epoch_id,
            "ordered_triggers": [item.value for item in self.ordered_triggers],
            "path": self.path.value,
            "plan_id": self.plan_id,
            "schema": self.schema,
            "state_id": self.state_id,
            "trigger_source_event_ids": list(self.trigger_source_event_ids),
            "trigger_sources": [
                {
                    "source_event_ids": list(source_ids),
                    "trigger": trigger.value,
                }
                for trigger, source_ids in self.trigger_sources
            ],
        }

    @property
    def selection_hash(self) -> str:
        return sha256_json(self.to_dict())

    @classmethod
    def from_dict(cls, value: object) -> CadenceSelection:
        if not isinstance(value, Mapping):
            raise PolicyError("cadence selection must be an object")
        _require_exact_keys(
            value,
            {
                "configuration_hash",
                "goal_id",
                "goal_revision",
                "mechanics_epoch_id",
                "ordered_triggers",
                "path",
                "plan_id",
                "schema",
                "state_id",
                "trigger_source_event_ids",
                "trigger_sources",
            },
            field="cadence selection",
        )
        raw_path = _require_text(value.get("path"), field="reasoning path")
        try:
            path = ReasoningPath(raw_path)
        except ValueError as error:
            raise PolicyError("reasoning path is unsupported") from error
        raw_triggers = value.get("ordered_triggers")
        if not isinstance(raw_triggers, list) or not all(
            isinstance(item, str) for item in raw_triggers
        ):
            raise PolicyError("ordered_triggers must be an array of strings")
        try:
            triggers = tuple(DeepTrigger(cast(str, item)) for item in raw_triggers)
        except ValueError as error:
            raise PolicyError("deep trigger is unsupported") from error
        raw_sources = value.get("trigger_sources")
        if not isinstance(raw_sources, list):
            raise PolicyError("trigger_sources must be an array")
        sources: list[tuple[DeepTrigger, tuple[str, ...]]] = []
        for item in raw_sources:
            if not isinstance(item, Mapping):
                raise PolicyError("trigger source must be an object")
            _require_exact_keys(
                item,
                {"source_event_ids", "trigger"},
                field="trigger source",
            )
            raw_trigger = _require_text(item.get("trigger"), field="trigger source trigger")
            try:
                trigger = DeepTrigger(raw_trigger)
            except ValueError as error:
                raise PolicyError("trigger source trigger is unsupported") from error
            sources.append(
                (
                    trigger,
                    _parse_string_array(
                        item.get("source_event_ids"),
                        field="trigger source_event_ids",
                    ),
                )
            )
        goal_id = value.get("goal_id")
        plan_id = value.get("plan_id")
        if goal_id is not None and not isinstance(goal_id, str):
            raise PolicyError("goal_id must be a string or null")
        if plan_id is not None and not isinstance(plan_id, str):
            raise PolicyError("plan_id must be a string or null")
        selection = cls(
            configuration_hash=_require_text(
                value.get("configuration_hash"), field="configuration_hash"
            ),
            path=path,
            ordered_triggers=triggers,
            trigger_sources=tuple(sources),
            state_id=_require_text(value.get("state_id"), field="state_id"),
            mechanics_epoch_id=_require_text(
                value.get("mechanics_epoch_id"), field="mechanics_epoch_id"
            ),
            goal_id=goal_id,
            goal_revision=_require_non_negative_int(
                value.get("goal_revision"), field="goal_revision"
            ),
            plan_id=plan_id,
            schema=_require_text(value.get("schema"), field="cadence selection schema"),
        )
        declared_sources = _parse_ordered_unique_string_array(
            value.get("trigger_source_event_ids"),
            field="trigger_source_event_ids",
        )
        if declared_sources != selection.trigger_source_event_ids:
            raise PolicyError("flattened trigger source IDs disagree with typed trigger sources")
        return selection


@dataclass(frozen=True, slots=True)
class CadenceState:
    """Checkpointable cadence counters and deliberation linkage."""

    configuration_hash: str
    fast_streak: int = 0
    no_progress_streak: int = 0
    last_structural_identity: str | None = None
    last_completed_deliberation_event_id: str | None = None
    last_completed_status: DeliberationStatus | None = None
    pending_selection_hash: str | None = None
    pending_path: ReasoningPath | None = None
    schema: str = CADENCE_STATE_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != CADENCE_STATE_SCHEMA:
            raise PolicyError("cadence state schema is unsupported")
        _require_text(self.configuration_hash, field="cadence configuration_hash")
        _require_non_negative_int(self.fast_streak, field="fast_streak")
        _require_non_negative_int(self.no_progress_streak, field="no_progress_streak")
        for field, value in (
            ("last_structural_identity", self.last_structural_identity),
            (
                "last_completed_deliberation_event_id",
                self.last_completed_deliberation_event_id,
            ),
            ("pending_selection_hash", self.pending_selection_hash),
        ):
            if value is not None:
                _require_text(value, field=field)
        if (self.last_completed_deliberation_event_id is None) != (
            self.last_completed_status is None
        ):
            raise PolicyError("completed deliberation identity and status must appear together")
        if self.last_completed_status is not None and not isinstance(
            self.last_completed_status, DeliberationStatus
        ):
            raise PolicyError("last_completed_status must be typed")
        if (self.pending_selection_hash is None) != (self.pending_path is None):
            raise PolicyError("pending selection hash and path must appear together")
        if self.pending_path is not None and not isinstance(self.pending_path, ReasoningPath):
            raise PolicyError("pending_path must be typed")

    @classmethod
    def initial(cls, config: CadenceConfig) -> CadenceState:
        return cls(configuration_hash=config.configuration_hash)

    @property
    def deliberation_in_progress(self) -> bool:
        return self.pending_selection_hash is not None

    def fold_consequence(
        self,
        *,
        progress_made: bool,
        structural_identity: str,
    ) -> CadenceState:
        """Return counters after the always-on evidence fold."""

        if self.deliberation_in_progress:
            raise PolicyError("cannot fold a consequence during deliberation")
        _require_bool(progress_made, field="progress_made")
        _require_text(structural_identity, field="structural_identity")
        return replace(
            self,
            no_progress_streak=0 if progress_made else self.no_progress_streak + 1,
            last_structural_identity=structural_identity,
        )

    def begin(self, selection: CadenceSelection) -> CadenceState:
        """Mark exactly one selected path as in progress."""

        if self.deliberation_in_progress:
            raise PolicyError("a cadence selection is already in progress")
        if selection.configuration_hash != self.configuration_hash:
            raise PolicyError("cadence selection configuration disagrees with state")
        return replace(
            self,
            pending_selection_hash=selection.selection_hash,
            pending_path=selection.path,
        )

    def complete(
        self,
        selection: CadenceSelection,
        *,
        completed_event_id: str,
        status: DeliberationStatus,
    ) -> CadenceState:
        """Close the selected path and update the deterministic fast streak."""

        _require_text(completed_event_id, field="completed_event_id")
        if not isinstance(status, DeliberationStatus):
            raise PolicyError("deliberation status must be typed")
        if self.pending_selection_hash != selection.selection_hash:
            raise PolicyError("completed cadence selection disagrees with pending selection")
        if self.pending_path is not selection.path:
            raise PolicyError("completed cadence path disagrees with pending path")
        return replace(
            self,
            fast_streak=(self.fast_streak + 1 if selection.path is ReasoningPath.FAST else 0),
            last_completed_deliberation_event_id=completed_event_id,
            last_completed_status=status,
            pending_selection_hash=None,
            pending_path=None,
        )

    def assert_checkpointable(self) -> None:
        """Reject a state that could falsely imply completed deliberation."""

        if self.deliberation_in_progress:
            raise PolicyError("cadence state is mid-deliberation and is not checkpointable")

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "configuration_hash": self.configuration_hash,
            "fast_streak": self.fast_streak,
            "last_completed_deliberation_event_id": self.last_completed_deliberation_event_id,
            "last_completed_status": (
                self.last_completed_status.value if self.last_completed_status is not None else None
            ),
            "last_structural_identity": self.last_structural_identity,
            "no_progress_streak": self.no_progress_streak,
            "pending_path": self.pending_path.value if self.pending_path is not None else None,
            "pending_selection_hash": self.pending_selection_hash,
            "schema": self.schema,
        }

    def to_checkpoint_dict(self) -> dict[str, JSONValue]:
        self.assert_checkpointable()
        return self.to_dict()

    @classmethod
    def from_dict(cls, value: object) -> CadenceState:
        if not isinstance(value, Mapping):
            raise PolicyError("cadence state must be an object")
        _require_exact_keys(
            value,
            {
                "configuration_hash",
                "fast_streak",
                "last_completed_deliberation_event_id",
                "last_completed_status",
                "last_structural_identity",
                "no_progress_streak",
                "pending_path",
                "pending_selection_hash",
                "schema",
            },
            field="cadence state",
        )

        def optional_text(field: str) -> str | None:
            raw = value.get(field)
            if raw is None:
                return None
            return _require_text(raw, field=field)

        raw_status = optional_text("last_completed_status")
        raw_path = optional_text("pending_path")
        try:
            status = None if raw_status is None else DeliberationStatus(raw_status)
            path = None if raw_path is None else ReasoningPath(raw_path)
        except ValueError as error:
            raise PolicyError("cadence state enum is unsupported") from error
        return cls(
            configuration_hash=_require_text(
                value.get("configuration_hash"), field="cadence configuration_hash"
            ),
            fast_streak=_require_non_negative_int(value.get("fast_streak"), field="fast_streak"),
            no_progress_streak=_require_non_negative_int(
                value.get("no_progress_streak"), field="no_progress_streak"
            ),
            last_structural_identity=optional_text("last_structural_identity"),
            last_completed_deliberation_event_id=optional_text(
                "last_completed_deliberation_event_id"
            ),
            last_completed_status=status,
            pending_selection_hash=optional_text("pending_selection_hash"),
            pending_path=path,
            schema=_require_text(value.get("schema"), field="cadence state schema"),
        )

    @classmethod
    def from_checkpoint_dict(cls, value: object) -> CadenceState:
        state = cls.from_dict(value)
        state.assert_checkpointable()
        return state


def select_reasoning_path(
    config: CadenceConfig,
    state: CadenceState,
    signals: CadenceSignals,
) -> CadenceSelection:
    """Select FAST or DEEP using only typed evidence and integer counters."""

    if state.deliberation_in_progress:
        raise PolicyError("cannot select a new path while deliberation is in progress")
    if state.configuration_hash != config.configuration_hash:
        raise PolicyError("cadence state configuration disagrees with runtime")
    source_by_trigger: dict[DeepTrigger, tuple[str, ...]] = {
        DeepTrigger.STARTUP_UNKNOWN_ACTION: signals.startup_unknown_action_event_ids,
        DeepTrigger.REOPENING: signals.reopening_event_ids,
        DeepTrigger.MEANINGFUL_CONTRADICTION: signals.meaningful_contradiction_event_ids,
        DeepTrigger.STRUCTURAL_NOVELTY: signals.structural_novelty_event_ids,
        DeepTrigger.HIGH_GOAL_UNCERTAINTY: signals.high_goal_uncertainty_event_ids,
    }
    if not signals.has_valid_plan:
        source_by_trigger[DeepTrigger.NO_VALID_PLAN] = (signals.observation_event_id,)
    if state.no_progress_streak >= config.repeated_no_progress_threshold:
        source_by_trigger[DeepTrigger.REPEATED_NO_PROGRESS] = (signals.observation_event_id,)
    if state.fast_streak >= config.maximum_fast_streak:
        source_by_trigger[DeepTrigger.MAX_FAST_STREAK] = (signals.observation_event_id,)
    triggers = tuple(trigger for trigger in DEEP_TRIGGER_PRIORITY if source_by_trigger.get(trigger))
    path = (
        ReasoningPath.DEEP
        if config.mode is DeliberationMode.LEGACY_ALWAYS_DEEP or triggers
        else ReasoningPath.FAST
    )
    # The legacy control is deliberately deep without inventing a causal trigger.
    if path is ReasoningPath.DEEP and not triggers:
        return CadenceSelection(
            configuration_hash=config.configuration_hash,
            path=path,
            ordered_triggers=(),
            trigger_sources=(),
            state_id=signals.state_id,
            mechanics_epoch_id=signals.mechanics_epoch_id,
            goal_id=signals.goal_id,
            goal_revision=signals.goal_revision,
            plan_id=signals.plan_id,
        )
    return CadenceSelection(
        configuration_hash=config.configuration_hash,
        path=path,
        ordered_triggers=triggers,
        trigger_sources=tuple((trigger, source_by_trigger[trigger]) for trigger in triggers),
        state_id=signals.state_id,
        mechanics_epoch_id=signals.mechanics_epoch_id,
        goal_id=signals.goal_id,
        goal_revision=signals.goal_revision,
        plan_id=signals.plan_id,
    )


@dataclass(frozen=True, slots=True, order=True)
class ModelCacheIdentity:
    """One ordered model semantic identity and deterministic rank weight."""

    semantic_identity: str
    rank_weight: int

    def __post_init__(self) -> None:
        _require_text(self.semantic_identity, field="model semantic_identity")
        if isinstance(self.rank_weight, bool) or not isinstance(self.rank_weight, int):
            raise PolicyError("model rank_weight must be an integer")

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "rank_weight": self.rank_weight,
            "semantic_identity": self.semantic_identity,
            "weight_kind": "uncalibrated_rank",
        }

    @classmethod
    def from_dict(cls, value: object) -> ModelCacheIdentity:
        if not isinstance(value, Mapping):
            raise PolicyError("model cache identity must be an object")
        _require_exact_keys(
            value,
            {"rank_weight", "semantic_identity", "weight_kind"},
            field="model cache identity",
        )
        if value.get("weight_kind") != "uncalibrated_rank":
            raise PolicyError("model cache rank weight kind is unsupported")
        rank_weight = value.get("rank_weight")
        if isinstance(rank_weight, bool) or not isinstance(rank_weight, int):
            raise PolicyError("model cache rank_weight must be an integer")
        return cls(
            semantic_identity=_require_text(
                value.get("semantic_identity"), field="model semantic_identity"
            ),
            rank_weight=rank_weight,
        )


def _action_to_dict(action: ActionRequest) -> dict[str, JSONValue]:
    coordinate = action.coordinate
    return {
        "coordinate": None if coordinate is None else {"x": coordinate.x, "y": coordinate.y},
        "name": action.name.value,
    }


def _action_from_dict(value: object, *, field: str) -> ActionRequest:
    if not isinstance(value, Mapping):
        raise PolicyError(f"{field} must be an object")
    _require_exact_keys(value, {"coordinate", "name"}, field=field)
    raw_name = _require_text(value.get("name"), field=f"{field} name")
    try:
        name = ActionName(raw_name)
    except ValueError as error:
        raise PolicyError(f"{field} name is unsupported") from error
    raw_coordinate = value.get("coordinate")
    coordinate: Coordinate | None
    if raw_coordinate is None:
        coordinate = None
    elif isinstance(raw_coordinate, Mapping):
        _require_exact_keys(raw_coordinate, {"x", "y"}, field=f"{field} coordinate")
        x = raw_coordinate.get("x")
        y = raw_coordinate.get("y")
        if (
            isinstance(x, bool)
            or not isinstance(x, int)
            or isinstance(y, bool)
            or not isinstance(y, int)
        ):
            raise PolicyError(f"{field} coordinate must contain integers")
        try:
            coordinate = Coordinate(x=x, y=y)
        except ValueError as error:
            raise PolicyError(f"{field} coordinate is invalid") from error
    else:
        raise PolicyError(f"{field} coordinate must be an object or null")
    try:
        return ActionRequest(name=name, coordinate=coordinate)
    except ValueError as error:
        raise PolicyError(f"{field} is invalid") from error


def _symbolic_state_from_dict(value: Mapping[str, object]) -> SymbolicState:
    """Rebuild one exact canonical symbolic-state prediction projection."""

    _require_exact_keys(
        value,
        {
            "attachments",
            "counters",
            "entities",
            "facts",
            "height",
            "selected_id",
            "toggles",
            "width",
        },
        field="prediction symbolic state",
    )
    width = _require_positive_int(value.get("width"), field="prediction state width")
    height = _require_positive_int(value.get("height"), field="prediction state height")
    raw_entities = value.get("entities")
    raw_facts = value.get("facts")
    raw_counters = value.get("counters")
    raw_toggles = value.get("toggles")
    raw_attachments = value.get("attachments")
    if (
        not isinstance(raw_entities, list)
        or not isinstance(raw_facts, list)
        or not all(isinstance(item, str) for item in raw_facts)
        or not isinstance(raw_counters, list)
        or not isinstance(raw_toggles, list)
        or not isinstance(raw_attachments, list)
    ):
        raise PolicyError("prediction symbolic state collections are malformed")

    entities: list[SymbolicEntity] = []
    for raw_entity in raw_entities:
        if not isinstance(raw_entity, Mapping):
            raise PolicyError("prediction symbolic entity must be an object")
        _require_exact_keys(
            raw_entity,
            {"attributes", "cells", "color", "entity_id", "kind"},
            field="prediction symbolic entity",
        )
        raw_cells = raw_entity.get("cells")
        raw_attributes = raw_entity.get("attributes")
        if not isinstance(raw_cells, list) or not isinstance(raw_attributes, list):
            raise PolicyError("prediction symbolic entity collections are malformed")
        cells: list[Cell] = []
        for raw_cell in raw_cells:
            if not isinstance(raw_cell, list) or len(raw_cell) != 2:
                raise PolicyError("prediction symbolic cell is malformed")
            x, y = raw_cell
            if (
                isinstance(x, bool)
                or not isinstance(x, int)
                or isinstance(y, bool)
                or not isinstance(y, int)
            ):
                raise PolicyError("prediction symbolic cell coordinates must be integers")
            cells.append(Cell(x=x, y=y))
        attributes: list[tuple[str, str]] = []
        for raw_attribute in raw_attributes:
            if (
                not isinstance(raw_attribute, list)
                or len(raw_attribute) != 2
                or not all(isinstance(item, str) for item in raw_attribute)
            ):
                raise PolicyError("prediction symbolic entity attribute is malformed")
            attributes.append((cast(str, raw_attribute[0]), cast(str, raw_attribute[1])))
        color = raw_entity.get("color")
        if color is not None and (isinstance(color, bool) or not isinstance(color, int)):
            raise PolicyError("prediction symbolic entity color must be an integer or null")
        try:
            entities.append(
                SymbolicEntity(
                    entity_id=_require_text(
                        raw_entity.get("entity_id"),
                        field="prediction symbolic entity_id",
                    ),
                    kind=_require_text(
                        raw_entity.get("kind"),
                        field="prediction symbolic entity kind",
                    ),
                    cells=tuple(cells),
                    color=color,
                    attributes=tuple(attributes),
                )
            )
        except WorldModelError as error:
            raise PolicyError("prediction symbolic entity is invalid") from error

    counters: list[tuple[str, int]] = []
    for raw_counter in raw_counters:
        if (
            not isinstance(raw_counter, list)
            or len(raw_counter) != 2
            or not isinstance(raw_counter[0], str)
            or isinstance(raw_counter[1], bool)
            or not isinstance(raw_counter[1], int)
        ):
            raise PolicyError("prediction symbolic counter is malformed")
        counters.append((raw_counter[0], raw_counter[1]))
    toggles: list[tuple[str, str]] = []
    for raw_toggle in raw_toggles:
        if (
            not isinstance(raw_toggle, list)
            or len(raw_toggle) != 2
            or not isinstance(raw_toggle[0], str)
            or not isinstance(raw_toggle[1], str)
        ):
            raise PolicyError("prediction symbolic toggle is malformed")
        toggles.append((raw_toggle[0], raw_toggle[1]))
    attachments: list[Attachment] = []
    for raw_attachment in raw_attachments:
        if not isinstance(raw_attachment, Mapping):
            raise PolicyError("prediction symbolic attachment must be an object")
        _require_exact_keys(
            raw_attachment,
            {"child_id", "dx", "dy", "parent_id"},
            field="prediction symbolic attachment",
        )
        child_id = raw_attachment.get("child_id")
        parent_id = raw_attachment.get("parent_id")
        dx = raw_attachment.get("dx")
        dy = raw_attachment.get("dy")
        if (
            not isinstance(child_id, str)
            or not isinstance(parent_id, str)
            or isinstance(dx, bool)
            or not isinstance(dx, int)
            or isinstance(dy, bool)
            or not isinstance(dy, int)
        ):
            raise PolicyError("prediction symbolic attachment fields are malformed")
        attachments.append(Attachment(child_id=child_id, parent_id=parent_id, dx=dx, dy=dy))
    selected_id = value.get("selected_id")
    if selected_id is not None and not isinstance(selected_id, str):
        raise PolicyError("prediction symbolic selected_id must be a string or null")
    try:
        state = SymbolicState(
            width=width,
            height=height,
            entities=tuple(entities),
            facts=tuple(cast(list[str], raw_facts)),
            counters=tuple(counters),
            toggles=tuple(toggles),
            selected_id=selected_id,
            attachments=tuple(attachments),
        )
    except WorldModelError as error:
        raise PolicyError("prediction symbolic state is invalid") from error
    if state.to_dict() != value:
        raise PolicyError("prediction symbolic state is not canonical")
    return state


@dataclass(frozen=True, slots=True)
class CanonicalCacheKey:
    """Collision-safe complete key for reusable derived computation."""

    source_identity: str
    configuration_identity: str
    symbolic_state_id: str
    action: ActionRequest
    ordered_models: tuple[ModelCacheIdentity, ...]
    mechanics_epoch_id: str
    action_registry_identity: str
    value_kind: CacheValueKind = CacheValueKind.PREDICTION
    schema: str = CACHE_KEY_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != CACHE_KEY_SCHEMA:
            raise PolicyError("reasoning cache key schema is unsupported")
        for field, value in (
            ("source_identity", self.source_identity),
            ("configuration_identity", self.configuration_identity),
            ("symbolic_state_id", self.symbolic_state_id),
            ("mechanics_epoch_id", self.mechanics_epoch_id),
            ("action_registry_identity", self.action_registry_identity),
        ):
            _require_text(value, field=field)
        if not isinstance(self.action, ActionRequest):
            raise PolicyError("cache action must be an ActionRequest")
        if not isinstance(self.value_kind, CacheValueKind):
            raise PolicyError("cache value namespace must be typed")
        if not all(isinstance(item, ModelCacheIdentity) for item in self.ordered_models):
            raise PolicyError("ordered_models must contain typed identities")
        semantic_ids = [item.semantic_identity for item in self.ordered_models]
        if len(set(semantic_ids)) != len(semantic_ids):
            raise PolicyError("ordered model semantic identities must be unique")

    def to_dict(self) -> dict[str, JSONValue]:
        coordinate = self.action.coordinate
        return {
            "action": {
                "coordinate": (
                    None if coordinate is None else {"x": coordinate.x, "y": coordinate.y}
                ),
                "name": self.action.name.value,
            },
            "action_registry_identity": self.action_registry_identity,
            "configuration_identity": self.configuration_identity,
            "mechanics_epoch_id": self.mechanics_epoch_id,
            "ordered_models": [item.to_dict() for item in self.ordered_models],
            "schema": self.schema,
            "source_identity": self.source_identity,
            "symbolic_state_id": self.symbolic_state_id,
            "value_kind": self.value_kind.value,
        }

    @property
    def key_hash(self) -> str:
        return _cache_key_hash(self.to_dict())

    @classmethod
    def from_dict(cls, value: object) -> CanonicalCacheKey:
        if not isinstance(value, Mapping):
            raise PolicyError("reasoning cache key must be an object")
        _require_exact_keys(
            value,
            {
                "action",
                "action_registry_identity",
                "configuration_identity",
                "mechanics_epoch_id",
                "ordered_models",
                "schema",
                "source_identity",
                "symbolic_state_id",
                "value_kind",
            },
            field="reasoning cache key",
        )
        raw_action = value.get("action")
        if not isinstance(raw_action, Mapping):
            raise PolicyError("reasoning cache action must be an object")
        _require_exact_keys(raw_action, {"coordinate", "name"}, field="reasoning cache action")
        raw_name = _require_text(raw_action.get("name"), field="reasoning cache action name")
        try:
            name = ActionName(raw_name)
        except ValueError as error:
            raise PolicyError("reasoning cache action name is unsupported") from error
        raw_coordinate = raw_action.get("coordinate")
        coordinate: Coordinate | None
        if raw_coordinate is None:
            coordinate = None
        elif isinstance(raw_coordinate, Mapping):
            _require_exact_keys(raw_coordinate, {"x", "y"}, field="reasoning cache coordinate")
            x = raw_coordinate.get("x")
            y = raw_coordinate.get("y")
            if (
                isinstance(x, bool)
                or not isinstance(x, int)
                or isinstance(y, bool)
                or not isinstance(y, int)
            ):
                raise PolicyError("reasoning cache coordinate must contain integers")
            try:
                coordinate = Coordinate(x=x, y=y)
            except ValueError as error:
                raise PolicyError("reasoning cache coordinate is invalid") from error
        else:
            raise PolicyError("reasoning cache coordinate must be an object or null")
        try:
            action = ActionRequest(name=name, coordinate=coordinate)
        except ValueError as error:
            raise PolicyError("reasoning cache action is invalid") from error
        raw_models = value.get("ordered_models")
        if not isinstance(raw_models, list):
            raise PolicyError("ordered_models must be an array")
        raw_value_kind = _require_text(value.get("value_kind"), field="cache value namespace")
        try:
            value_kind = CacheValueKind(raw_value_kind)
        except ValueError as error:
            raise PolicyError("cache value namespace is unsupported") from error
        return cls(
            source_identity=_require_text(value.get("source_identity"), field="source_identity"),
            configuration_identity=_require_text(
                value.get("configuration_identity"), field="configuration_identity"
            ),
            symbolic_state_id=_require_text(
                value.get("symbolic_state_id"), field="symbolic_state_id"
            ),
            action=action,
            ordered_models=tuple(ModelCacheIdentity.from_dict(item) for item in raw_models),
            mechanics_epoch_id=_require_text(
                value.get("mechanics_epoch_id"), field="mechanics_epoch_id"
            ),
            action_registry_identity=_require_text(
                value.get("action_registry_identity"), field="action_registry_identity"
            ),
            value_kind=value_kind,
            schema=_require_text(value.get("schema"), field="reasoning cache key schema"),
        )


@dataclass(frozen=True, slots=True)
class DerivedCacheValue:
    """Exact immutable projection of one pure world-model prediction.

    Stage 08 measures only prediction caching.  Retaining the typed prediction
    rather than an open JSON payload keeps receipts, environment consequences,
    hypothesis status, and permission outside the cache boundary by
    construction.  ``payload`` and ``to_dict`` always allocate fresh JSON
    containers, so callers cannot mutate live cache state through serialization.
    """

    prediction: EnsemblePrediction
    kind: CacheValueKind = CacheValueKind.PREDICTION
    schema: str = CACHE_VALUE_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != CACHE_VALUE_SCHEMA:
            raise PolicyError("reasoning cache value schema is unsupported")
        if self.kind is not CacheValueKind.PREDICTION:
            raise PolicyError("Stage 08 cache values must be prediction projections")
        if not isinstance(self.prediction, EnsemblePrediction):
            raise PolicyError("prediction cache value must contain an EnsemblePrediction")
        _require_text(self.prediction.before_state_id, field="prediction before_state_id")
        if not isinstance(self.prediction.action, ActionRequest):
            raise PolicyError("prediction cache action must be an ActionRequest")
        if not isinstance(self.prediction.alternatives, tuple) or not self.prediction.alternatives:
            raise PolicyError("prediction cache requires a non-empty alternatives tuple")
        expected_ranks = tuple(range(1, len(self.prediction.alternatives) + 1))
        actual_ranks: list[int] = []
        for alternative in self.prediction.alternatives:
            if not isinstance(alternative, AlternativeOutcome):
                raise PolicyError("prediction cache alternatives must be typed")
            actual_ranks.append(
                _require_positive_int(
                    alternative.alternative_rank,
                    field="prediction alternative_rank",
                )
            )
            if not isinstance(alternative.after_state, SymbolicState):
                raise PolicyError("prediction alternative state must be symbolic")
            if (
                not isinstance(alternative.supporting_model_ids, tuple)
                or not alternative.supporting_model_ids
                or tuple(sorted(set(alternative.supporting_model_ids)))
                != alternative.supporting_model_ids
            ):
                raise PolicyError(
                    "prediction supporting model IDs must be a non-empty sorted unique tuple"
                )
            if (
                not isinstance(alternative.prediction_ids, tuple)
                or not alternative.prediction_ids
                or tuple(sorted(set(alternative.prediction_ids))) != alternative.prediction_ids
            ):
                raise PolicyError("prediction IDs must be a non-empty sorted unique tuple")
            for identifier in (*alternative.supporting_model_ids, *alternative.prediction_ids):
                _require_text(identifier, field="prediction semantic identity")
            if isinstance(alternative.rank_weight, bool) or not isinstance(
                alternative.rank_weight, int
            ):
                raise PolicyError("prediction rank_weight must be an integer")
            if alternative.weight_kind != "uncalibrated_rank":
                raise PolicyError("prediction weight kind is unsupported")
        if tuple(actual_ranks) != expected_ranks:
            raise PolicyError("prediction alternatives must have contiguous rank order")

    @property
    def payload(self) -> dict[str, JSONValue]:
        """Return a detached canonical JSON projection of the prediction."""

        return {
            "action": _action_to_dict(self.prediction.action),
            "alternatives": [
                {
                    "after_state": alternative.after_state.to_dict(),
                    "after_state_id": alternative.after_state_id,
                    "alternative_rank": alternative.alternative_rank,
                    "prediction_ids": list(alternative.prediction_ids),
                    "rank_weight": alternative.rank_weight,
                    "supporting_model_ids": list(alternative.supporting_model_ids),
                    "weight_kind": alternative.weight_kind,
                }
                for alternative in self.prediction.alternatives
            ],
            "before_state_id": self.prediction.before_state_id,
        }

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "kind": self.kind.value,
            "payload": self.payload,
            "schema": self.schema,
        }

    @property
    def value_hash(self) -> str:
        return sha256_json(self.to_dict())

    @classmethod
    def from_dict(cls, value: object) -> DerivedCacheValue:
        if not isinstance(value, Mapping):
            raise PolicyError("reasoning cache value must be an object")
        _require_exact_keys(value, {"kind", "payload", "schema"}, field="reasoning cache value")
        raw_kind = _require_text(value.get("kind"), field="reasoning cache value kind")
        try:
            kind = CacheValueKind(raw_kind)
        except ValueError as error:
            raise PolicyError("reasoning cache value kind is unsupported") from error
        if kind is not CacheValueKind.PREDICTION:
            raise PolicyError("Stage 08 cache values must be prediction projections")
        raw_payload = value.get("payload")
        if not isinstance(raw_payload, Mapping):
            raise PolicyError("reasoning cache payload must be an object")
        _require_exact_keys(
            raw_payload,
            {"action", "alternatives", "before_state_id"},
            field="prediction cache payload",
        )
        raw_alternatives = raw_payload.get("alternatives")
        if not isinstance(raw_alternatives, list) or not raw_alternatives:
            raise PolicyError("prediction cache alternatives must be a non-empty array")
        alternatives: list[AlternativeOutcome] = []
        for raw_alternative in raw_alternatives:
            if not isinstance(raw_alternative, Mapping):
                raise PolicyError("prediction cache alternative must be an object")
            _require_exact_keys(
                raw_alternative,
                {
                    "after_state",
                    "after_state_id",
                    "alternative_rank",
                    "prediction_ids",
                    "rank_weight",
                    "supporting_model_ids",
                    "weight_kind",
                },
                field="prediction cache alternative",
            )
            raw_state = raw_alternative.get("after_state")
            if not isinstance(raw_state, Mapping):
                raise PolicyError("prediction cache after_state must be an object")
            after_state = _symbolic_state_from_dict(raw_state)
            if raw_alternative.get("after_state_id") != after_state.state_id:
                raise PolicyError("prediction cache after_state identity disagrees with content")
            rank_weight = raw_alternative.get("rank_weight")
            if isinstance(rank_weight, bool) or not isinstance(rank_weight, int):
                raise PolicyError("prediction cache rank_weight must be an integer")
            alternatives.append(
                AlternativeOutcome(
                    alternative_rank=_require_positive_int(
                        raw_alternative.get("alternative_rank"),
                        field="prediction alternative_rank",
                    ),
                    after_state=after_state,
                    supporting_model_ids=_parse_ordered_unique_string_array(
                        raw_alternative.get("supporting_model_ids"),
                        field="prediction supporting_model_ids",
                    ),
                    prediction_ids=_parse_ordered_unique_string_array(
                        raw_alternative.get("prediction_ids"),
                        field="prediction prediction_ids",
                    ),
                    rank_weight=rank_weight,
                    weight_kind=_require_text(
                        raw_alternative.get("weight_kind"),
                        field="prediction weight_kind",
                    ),
                )
            )
        return cls(
            prediction=EnsemblePrediction(
                before_state_id=_require_text(
                    raw_payload.get("before_state_id"),
                    field="prediction before_state_id",
                ),
                action=_action_from_dict(
                    raw_payload.get("action"),
                    field="prediction cache action",
                ),
                alternatives=tuple(alternatives),
            ),
            kind=kind,
            schema=_require_text(value.get("schema"), field="reasoning cache value schema"),
        )


@dataclass(frozen=True, slots=True)
class _CacheEntry:
    key: CanonicalCacheKey
    value: DerivedCacheValue

    def __post_init__(self) -> None:
        if self.key.value_kind is not self.value.kind:
            raise PolicyError("reasoning cache key namespace disagrees with value kind")
        if self.value.prediction.before_state_id != self.key.symbolic_state_id:
            raise PolicyError("cached prediction before_state_id disagrees with complete key")
        if self.value.prediction.action != self.key.action:
            raise PolicyError("cached prediction action disagrees with complete key")

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "key": self.key.to_dict(),
            "key_hash": self.key.key_hash,
            "value": self.value.to_dict(),
            "value_hash": self.value.value_hash,
        }

    @classmethod
    def from_dict(cls, value: object) -> _CacheEntry:
        if not isinstance(value, Mapping):
            raise PolicyError("reasoning cache entry must be an object")
        _require_exact_keys(
            value,
            {"key", "key_hash", "value", "value_hash"},
            field="reasoning cache entry",
        )
        key = CanonicalCacheKey.from_dict(value.get("key"))
        cached_value = DerivedCacheValue.from_dict(value.get("value"))
        if value.get("key_hash") != key.key_hash:
            raise PolicyError("reasoning cache entry key hash disagrees with complete key")
        if value.get("value_hash") != cached_value.value_hash:
            raise PolicyError("reasoning cache entry value hash disagrees with content")
        return cls(key=key, value=cached_value)


def _cache_key_hash(value: object) -> str:
    """Indirection retained so collision handling can be exercised in tests."""

    return sha256_json(value)


class BoundedCanonicalLRU:
    """Deterministic LRU retaining complete keys and non-authoritative values."""

    def __init__(self, capacity: int = 256) -> None:
        self.capacity = _require_positive_int(capacity, field="reasoning cache capacity")
        self._entries: OrderedDict[str, _CacheEntry] = OrderedDict()
        self.hits = 0
        self.misses = 0
        self.evictions = 0
        self.invalidation_counts: dict[CacheInvalidationReason, int] = {
            reason: 0 for reason in CacheInvalidationReason
        }

    def __len__(self) -> int:
        return len(self._entries)

    def get(self, key: CanonicalCacheKey) -> DerivedCacheValue | None:
        """Return an exact-key hit and update checkpointed access order."""

        if not isinstance(key, CanonicalCacheKey):
            raise PolicyError("reasoning cache lookup requires a canonical key")
        digest = key.key_hash
        entry = self._entries.get(digest)
        if entry is None or entry.key != key:
            # A digest match alone is never sufficient for reuse.
            self.misses += 1
            return None
        self.hits += 1
        self._entries.move_to_end(digest)
        return entry.value

    def put(self, key: CanonicalCacheKey, value: DerivedCacheValue) -> tuple[str, ...]:
        """Insert or refresh a value and return evicted complete-key hashes."""

        if not isinstance(key, CanonicalCacheKey) or not isinstance(value, DerivedCacheValue):
            raise PolicyError("reasoning cache insertion requires typed key and value")
        digest = key.key_hash
        existing = self._entries.get(digest)
        if existing is not None and existing.key != key:
            raise PolicyError("reasoning cache digest collision between unequal complete keys")
        self._entries[digest] = _CacheEntry(key=key, value=value)
        self._entries.move_to_end(digest)
        evicted: list[str] = []
        while len(self._entries) > self.capacity:
            evicted_digest, _entry = self._entries.popitem(last=False)
            evicted.append(evicted_digest)
            self.evictions += 1
        return tuple(evicted)

    def invalidate(self, reason: CacheInvalidationReason) -> int:
        """Invalidate every cached derivation for one typed causal reason."""

        if not isinstance(reason, CacheInvalidationReason):
            raise PolicyError("reasoning cache invalidation reason must be typed")
        removed = len(self._entries)
        self._entries.clear()
        self.invalidation_counts[reason] += 1
        return removed

    @property
    def projection_hash(self) -> str:
        """Hash only content and access order that may affect performed work."""

        return sha256_json(
            {
                "capacity": self.capacity,
                "entries_lru_to_mru": [entry.to_dict() for entry in self._entries.values()],
                "schema": CACHE_STATE_SCHEMA,
            }
        )

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "capacity": self.capacity,
            "entries_lru_to_mru": [entry.to_dict() for entry in self._entries.values()],
            "evictions": self.evictions,
            "hits": self.hits,
            "invalidation_counts": [
                {"count": self.invalidation_counts[reason], "reason": reason.value}
                for reason in CacheInvalidationReason
            ],
            "misses": self.misses,
            "projection_hash": self.projection_hash,
            "schema": CACHE_STATE_SCHEMA,
        }

    @classmethod
    def from_dict(
        cls,
        value: object,
        *,
        expected_capacity: int | None = None,
    ) -> BoundedCanonicalLRU:
        if not isinstance(value, Mapping):
            raise PolicyError("reasoning cache state must be an object")
        _require_exact_keys(
            value,
            {
                "capacity",
                "entries_lru_to_mru",
                "evictions",
                "hits",
                "invalidation_counts",
                "misses",
                "projection_hash",
                "schema",
            },
            field="reasoning cache state",
        )
        if value.get("schema") != CACHE_STATE_SCHEMA:
            raise PolicyError("reasoning cache state schema is unsupported")
        capacity = _require_positive_int(value.get("capacity"), field="reasoning cache capacity")
        if expected_capacity is not None:
            expected = _require_positive_int(
                expected_capacity,
                field="expected reasoning cache capacity",
            )
            if capacity != expected:
                raise PolicyError("reasoning cache capacity disagrees with runtime")
        cache = cls(capacity)
        raw_entries = value.get("entries_lru_to_mru")
        if not isinstance(raw_entries, list):
            raise PolicyError("reasoning cache entries must be an array")
        if len(raw_entries) > cache.capacity:
            raise PolicyError("reasoning cache state exceeds capacity")
        for raw_entry in raw_entries:
            entry = _CacheEntry.from_dict(raw_entry)
            digest = entry.key.key_hash
            if digest in cache._entries:
                raise PolicyError("reasoning cache state contains duplicate key hashes")
            cache._entries[digest] = entry
        cache.hits = _require_non_negative_int(value.get("hits"), field="reasoning cache hits")
        cache.misses = _require_non_negative_int(
            value.get("misses"), field="reasoning cache misses"
        )
        cache.evictions = _require_non_negative_int(
            value.get("evictions"), field="reasoning cache evictions"
        )
        raw_invalidations = value.get("invalidation_counts")
        if not isinstance(raw_invalidations, list):
            raise PolicyError("reasoning cache invalidation counts must be an array")
        parsed_counts: dict[CacheInvalidationReason, int] = {}
        for raw_count in raw_invalidations:
            if not isinstance(raw_count, Mapping):
                raise PolicyError("reasoning cache invalidation count must be an object")
            _require_exact_keys(
                raw_count,
                {"count", "reason"},
                field="reasoning cache invalidation count",
            )
            raw_reason = _require_text(raw_count.get("reason"), field="cache invalidation reason")
            try:
                reason = CacheInvalidationReason(raw_reason)
            except ValueError as error:
                raise PolicyError("cache invalidation reason is unsupported") from error
            if reason in parsed_counts:
                raise PolicyError("cache invalidation reason is duplicated")
            parsed_counts[reason] = _require_non_negative_int(
                raw_count.get("count"), field="cache invalidation count"
            )
        if set(parsed_counts) != set(CacheInvalidationReason):
            raise PolicyError("cache invalidation counts do not cover the closed reason set")
        cache.invalidation_counts = parsed_counts
        if value.get("projection_hash") != cache.projection_hash:
            raise PolicyError("reasoning cache projection hash disagrees with state")
        return cache


__all__ = [
    "CACHE_KEY_SCHEMA",
    "CACHE_STATE_SCHEMA",
    "CACHE_VALUE_SCHEMA",
    "CADENCE_CONFIG_SCHEMA",
    "CADENCE_SELECTION_SCHEMA",
    "CADENCE_STATE_SCHEMA",
    "DEEP_TRIGGER_PRIORITY",
    "BoundedCanonicalLRU",
    "CacheInvalidationReason",
    "CacheValueKind",
    "CadenceConfig",
    "CadenceSelection",
    "CadenceSignals",
    "CadenceState",
    "CanonicalCacheKey",
    "DeepTrigger",
    "DeliberationMode",
    "DeliberationStatus",
    "DerivedCacheValue",
    "ModelCacheIdentity",
    "ReasoningPath",
    "select_reasoning_path",
]
