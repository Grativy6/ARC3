"""Pure frozen contract for the Build 001 Stage 08 timing comparison.

This module defines identities, typed measurements, canonical receipts, and
decision gates only.  It does not import a controller, enumerate public assets,
or open an environment.  In particular, the sole permitted local-public
identity is encoded directly from the frozen preimplementation declaration.
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import cast

from arc3.errors import EvaluationError
from arc3.trace.canonical import normalize_json, sha256_bytes, sha256_json
from arc3.types import JSONValue

ROOT = Path(__file__).resolve().parents[3]
PREDECLARATION_PATH = ROOT / "docs/evidence/001-08-two-speed-predeclaration.json"
PREDECLARATION_SHA256 = "sha256:3342b6e2635c0606391c9aea02b2fec0cf4c5642a3d38b95768a1b77b4520878"
PUBLIC_PARTITION_MANIFEST_SHA256 = (
    "sha256:682d5891c2aface54803d9bd1173c55ed21e89856e13b8a478fb9276ee963f2f"
)
BUILD_000_PRODUCTION_COMMIT = "90ecf7267d5bb23d751d6f7ce3e8aa75f2f1a130"
BUILD_000_PRODUCTION_TREE = "0cf6e00b2fcc399e7a99a62c20e91bb84d485f13"
BUILD_001_BASELINE_COMMIT = "d0052555e721453746e4c443efea441da2cb4789"

DEVELOPMENT_PARTITION = "development"
DEVELOPMENT_GAME_ID = "ar25-0c556536"
DEVELOPMENT_ASSET_SHA256 = "sha256:e796e615d2e10c93b849f9bf150308fbf84d624725deaf995d7ec2d1c2f86b22"
DEVELOPMENT_SEED = 7
MAX_ACTIONS = 8
MAX_RESETS = 8
WORKER_WALL_SECONDS = 120.0
ENVIRONMENT_MODE = "LOCAL"

REPETITIONS_PER_VARIANT = 5
VARIANTS_PER_REPETITION = 4
EXPECTED_CELL_COUNT = REPETITIONS_PER_VARIANT * VARIANTS_PER_REPETITION
MATERIALITY_MAX_MEDIAN_RATIO = 0.75
NONREGRESSION_MIN_FRACTION = 0.70
MAX_PEAK_RSS_BYTES = 2_147_483_648
MAX_TRACE_BYTES_PER_RUN = 268_435_456
MAX_DECISION_WALL_NS = 2_000_000_000
MEASUREMENT_MATRIX_SHA256 = (
    "sha256:ca507ee6e539e0544647aac792417b276806a848e656f2b7b4f1a368ba6b63a1"
)
MEASUREMENT_PLAN_SHA256 = "sha256:b42326c4de76786982c07a18be2fcd73afe4583bdb11100e9cb6147b6c8e582c"

_PLAN_SCHEMA = "arc3.build-001.stage-08.measurement-plan.v0.1"
_CELL_SCHEMA = "arc3.build-001.stage-08.measurement-cell.v0.1"
_RESULT_SCHEMA = "arc3.build-001.stage-08.cell-result.v0.3"
_GATE_SCHEMA = "arc3.build-001.stage-08.materiality-gate.v0.3"
_SCORE_SCOPE_SUCCESS = "terminal-success-receipts"
_SCORE_SCOPE_RECOVERED_FAILURE = "verified-scorecards-on-failed-receipts"


class MeasurementVariant(StrEnum):
    """The exact Stage 08 comparison variants in frozen base order."""

    FROZEN_BUILD_000_FULL = "FROZEN_BUILD_000_FULL"
    BUILD_001_LEGACY_ALWAYS_DEEP = "BUILD_001_LEGACY_ALWAYS_DEEP"
    BUILD_001_TWO_SPEED = "BUILD_001_TWO_SPEED"
    BUILD_001_TWO_SPEED_NO_PREDICTION_CACHE = "BUILD_001_TWO_SPEED_NO_PREDICTION_CACHE"


VARIANT_ORDER = (
    MeasurementVariant.FROZEN_BUILD_000_FULL,
    MeasurementVariant.BUILD_001_LEGACY_ALWAYS_DEEP,
    MeasurementVariant.BUILD_001_TWO_SPEED,
    MeasurementVariant.BUILD_001_TWO_SPEED_NO_PREDICTION_CACHE,
)


class BoundaryStatus(StrEnum):
    """Whether an action/consequence timing boundary returned normally."""

    NORMAL = "normal"
    FAILED = "failed"
    CENSORED = "censored"


class CellStatus(StrEnum):
    """Terminal worker outcome retained by the Stage 08 harness."""

    SUCCESS = "success"
    FAILURE = "failure"
    TIMEOUT = "timeout"
    INTERRUPTED = "interrupted"
    CRASH = "crash"


class EvidenceAvailability(StrEnum):
    """Whether a terminal cell retains exact typed measurement evidence."""

    EXACT = "exact"
    UNAVAILABLE = "unavailable"


class FailureDomain(StrEnum):
    """Typed Stage 08 terminal-failure ownership used by the aggregate status."""

    MECHANISM = "MECHANISM"
    RESOURCE = "RESOURCE"
    INFRASTRUCTURE = "INFRASTRUCTURE"


class WorkAvailability(StrEnum):
    """Availability of deterministic integer-work telemetry."""

    AVAILABLE = "available"
    UNAVAILABLE_AT_FROZEN_SOURCE = "unavailable-at-frozen-source"


class ReasoningPath(StrEnum):
    """Typed reasoning path projected from immutable cadence receipts."""

    FAST = "FAST"
    DEEP = "DEEP"


class DeepTrigger(StrEnum):
    """The frozen priority-ordered reasons that authorize TWO_SPEED DEEP work."""

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
    """Terminal status of one selected reasoning path."""

    COMPLETED = "COMPLETED"
    FALLBACK_USED = "FALLBACK_USED"
    BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"
    FAILED = "FAILED"


class ReasoningTerminalKind(StrEnum):
    """The exactly-one terminal receipt kind linked to a path selection."""

    DELIBERATION_COMPLETED = "reasoning.deliberation_completed"
    FALLBACK_USED = "reasoning.fallback_used"


@dataclass(frozen=True, slots=True)
class BoundaryCounts:
    """Monotone phase counts for one kind of submitted environment boundary.

    A worker can fail before it has an action identity, after submission, after
    the environment returned, or while the controller acknowledges the return.
    Keeping those phases separate prevents a partial boundary from being
    reported as a completed environment action.
    """

    attempted: int
    submitted: int
    returned: int
    acknowledged: int

    def __post_init__(self) -> None:
        values = (
            ("attempted", self.attempted),
            ("submitted", self.submitted),
            ("returned", self.returned),
            ("acknowledged", self.acknowledged),
        )
        for field_name, value in values:
            _require_nonnegative_int(value, field=f"boundary {field_name} count")
        if not self.attempted >= self.submitted >= self.returned >= self.acknowledged:
            raise EvaluationError(
                "boundary counts must satisfy attempted >= submitted >= returned >= acknowledged"
            )

    @classmethod
    def completed(cls, count: int) -> BoundaryCounts:
        """Construct exact counts for wholly acknowledged boundaries."""

        _require_nonnegative_int(count, field="completed boundary count")
        return cls(attempted=count, submitted=count, returned=count, acknowledged=count)

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "acknowledged": self.acknowledged,
            "attempted": self.attempted,
            "returned": self.returned,
            "submitted": self.submitted,
        }


@dataclass(frozen=True, slots=True)
class DevelopmentIdentity:
    """The one already exposed development identity permitted in Stage 08."""

    partition: str = DEVELOPMENT_PARTITION
    game_id: str = DEVELOPMENT_GAME_ID
    seed: int = DEVELOPMENT_SEED
    max_actions: int = MAX_ACTIONS
    max_resets: int = MAX_RESETS
    worker_wall_seconds: float = WORKER_WALL_SECONDS
    environment_mode: str = ENVIRONMENT_MODE
    network_enabled: bool = False
    acquire_missing: bool = False
    asset_aggregate_sha256: str = DEVELOPMENT_ASSET_SHA256
    public_partition_manifest_sha256: str = PUBLIC_PARTITION_MANIFEST_SHA256

    def __post_init__(self) -> None:
        _require_str(self.partition, field="partition")
        _require_str(self.game_id, field="game_id")
        _require_int(self.seed, field="seed")
        _require_int(self.max_actions, field="max_actions")
        _require_int(self.max_resets, field="max_resets")
        _require_float(self.worker_wall_seconds, field="worker_wall_seconds")
        _require_str(self.environment_mode, field="environment_mode")
        _require_bool(self.network_enabled, field="network_enabled")
        _require_bool(self.acquire_missing, field="acquire_missing")
        _require_str(self.asset_aggregate_sha256, field="asset_aggregate_sha256")
        _require_str(
            self.public_partition_manifest_sha256,
            field="public_partition_manifest_sha256",
        )
        expected = _development_identity_values()
        if self.to_dict() != expected:
            raise EvaluationError("Stage 08 accepts only the exact frozen development identity")

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "acquire_missing": self.acquire_missing,
            "asset_aggregate_sha256": self.asset_aggregate_sha256,
            "environment_mode": self.environment_mode,
            "game_id": self.game_id,
            "max_actions": self.max_actions,
            "max_resets": self.max_resets,
            "network_enabled": self.network_enabled,
            "partition": self.partition,
            "public_partition_manifest_sha256": self.public_partition_manifest_sha256,
            "seed": self.seed,
            "worker_wall_seconds": self.worker_wall_seconds,
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> DevelopmentIdentity:
        """Parse an exact identity without consulting a partition or asset manifest."""

        expected_fields = frozenset(_development_identity_values())
        if frozenset(value) != expected_fields:
            raise EvaluationError("Stage 08 development identity fields are not exact")
        try:
            return cls(
                partition=_require_str(value["partition"], field="partition"),
                game_id=_require_str(value["game_id"], field="game_id"),
                seed=_require_int(value["seed"], field="seed"),
                max_actions=_require_int(value["max_actions"], field="max_actions"),
                max_resets=_require_int(value["max_resets"], field="max_resets"),
                worker_wall_seconds=_require_float(
                    value["worker_wall_seconds"], field="worker_wall_seconds"
                ),
                environment_mode=_require_str(value["environment_mode"], field="environment_mode"),
                network_enabled=_require_bool(value["network_enabled"], field="network_enabled"),
                acquire_missing=_require_bool(value["acquire_missing"], field="acquire_missing"),
                asset_aggregate_sha256=_require_str(
                    value["asset_aggregate_sha256"], field="asset_aggregate_sha256"
                ),
                public_partition_manifest_sha256=_require_str(
                    value["public_partition_manifest_sha256"],
                    field="public_partition_manifest_sha256",
                ),
            )
        except KeyError as error:  # defensive: exact fields were checked above
            raise EvaluationError("Stage 08 development identity is incomplete") from error


def _development_identity_values() -> dict[str, JSONValue]:
    return {
        "acquire_missing": False,
        "asset_aggregate_sha256": DEVELOPMENT_ASSET_SHA256,
        "environment_mode": ENVIRONMENT_MODE,
        "game_id": DEVELOPMENT_GAME_ID,
        "max_actions": MAX_ACTIONS,
        "max_resets": MAX_RESETS,
        "network_enabled": False,
        "partition": DEVELOPMENT_PARTITION,
        "public_partition_manifest_sha256": PUBLIC_PARTITION_MANIFEST_SHA256,
        "seed": DEVELOPMENT_SEED,
        "worker_wall_seconds": WORKER_WALL_SECONDS,
    }


@dataclass(frozen=True, slots=True)
class MeasurementCell:
    """One immutable cell in the exact five-rotation measurement matrix."""

    ordinal: int
    repetition: int
    position: int
    variant: MeasurementVariant
    development: DevelopmentIdentity = field(default_factory=DevelopmentIdentity)

    def __post_init__(self) -> None:
        _require_nonnegative_int(self.ordinal, field="ordinal")
        _require_nonnegative_int(self.repetition, field="repetition")
        _require_nonnegative_int(self.position, field="position")
        if not isinstance(self.variant, MeasurementVariant):
            raise EvaluationError("Stage 08 cell variant must be typed")
        if self.ordinal != self.repetition * VARIANTS_PER_REPETITION + self.position:
            raise EvaluationError("Stage 08 cell ordinal disagrees with repetition and position")
        if not 0 <= self.repetition < REPETITIONS_PER_VARIANT:
            raise EvaluationError("Stage 08 repetition is outside the frozen schedule")
        if not 0 <= self.position < VARIANTS_PER_REPETITION:
            raise EvaluationError("Stage 08 position is outside the frozen schedule")
        expected = VARIANT_ORDER[(self.repetition + self.position) % len(VARIANT_ORDER)]
        if self.variant is not expected:
            raise EvaluationError("Stage 08 variant disagrees with the frozen balanced rotation")

    @property
    def cell_id(self) -> str:
        core: dict[str, JSONValue] = {
            "development_identity": self.development.to_dict(),
            "ordinal": self.ordinal,
            "position": self.position,
            "repetition": self.repetition,
            "variant": self.variant.value,
        }
        digest = sha256_json(core).removeprefix("sha256:")[:16]
        return f"stage08-cell-{self.ordinal:02d}-r{self.repetition}-p{self.position}-{digest}"

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "cell_id": self.cell_id,
            "development_identity": self.development.to_dict(),
            "ordinal": self.ordinal,
            "position": self.position,
            "repetition": self.repetition,
            "schema": _CELL_SCHEMA,
            "variant": self.variant.value,
        }


def build_measurement_matrix(
    development: DevelopmentIdentity | None = None,
) -> tuple[MeasurementCell, ...]:
    """Return the exact A/B/C/D cyclic rotation frozen before measurement."""

    identity = development or DevelopmentIdentity()
    cells = tuple(
        MeasurementCell(
            ordinal=repetition * VARIANTS_PER_REPETITION + position,
            repetition=repetition,
            position=position,
            variant=VARIANT_ORDER[(repetition + position) % len(VARIANT_ORDER)],
            development=identity,
        )
        for repetition in range(REPETITIONS_PER_VARIANT)
        for position in range(VARIANTS_PER_REPETITION)
    )
    if len(cells) != EXPECTED_CELL_COUNT or len({cell.cell_id for cell in cells}) != len(cells):
        raise EvaluationError("Stage 08 matrix identity is not exactly 20 unique cells")
    return cells


def build_measurement_plan() -> dict[str, JSONValue]:
    """Build and canonically self-seal the frozen controller-independent plan."""

    cells = build_measurement_matrix()
    matrix_payload: list[JSONValue] = [cell.to_dict() for cell in cells]
    matrix_hash = sha256_json(matrix_payload)
    if matrix_hash != MEASUREMENT_MATRIX_SHA256:
        raise EvaluationError("Stage 08 canonical measurement matrix changed")
    core: dict[str, JSONValue] = {
        "build_000_production_commit": BUILD_000_PRODUCTION_COMMIT,
        "build_000_production_tree": BUILD_000_PRODUCTION_TREE,
        "build_001_baseline_commit": BUILD_001_BASELINE_COMMIT,
        "development_identity": DevelopmentIdentity().to_dict(),
        "evaluation_matrix": matrix_payload,
        "evaluation_matrix_hash": matrix_hash,
        "expected_cell_count": EXPECTED_CELL_COUNT,
        "materiality": {
            "candidate": MeasurementVariant.BUILD_001_TWO_SPEED.value,
            "comparators": [
                MeasurementVariant.FROZEN_BUILD_000_FULL.value,
                MeasurementVariant.BUILD_001_LEGACY_ALWAYS_DEEP.value,
            ],
            "maximum_median_paired_ratio": MATERIALITY_MAX_MEDIAN_RATIO,
            "minimum_paired_cell_nonregression_fraction": NONREGRESSION_MIN_FRACTION,
            "primary_scope": "normally-returned-action-consequence-boundaries-only",
        },
        "predeclaration_path": PREDECLARATION_PATH.relative_to(ROOT).as_posix(),
        "predeclaration_sha256": PREDECLARATION_SHA256,
        "public_holdout_allowed": False,
        "repetitions_per_variant": REPETITIONS_PER_VARIANT,
        "schema": _PLAN_SCHEMA,
        "variant_order": [variant.value for variant in VARIANT_ORDER],
    }
    plan = seal_canonical_object(core, hash_field="plan_hash")
    if plan["plan_hash"] != MEASUREMENT_PLAN_SHA256:
        raise EvaluationError("Stage 08 canonical measurement plan changed")
    return plan


@dataclass(frozen=True, slots=True)
class WorkMeasurement:
    """Integer work counters, explicitly absent at the frozen Build 000 source."""

    availability: WorkAvailability
    prediction_invocations: int | None
    compilation_invocations: int | None
    retrodicted_transitions: int | None
    simulation_invocations: int | None
    search_expanded_nodes: int | None
    cache_hits: int | None
    cache_misses: int | None
    cache_invalidations: int | None

    def __post_init__(self) -> None:
        if not isinstance(self.availability, WorkAvailability):
            raise EvaluationError("work availability must be typed")
        values = self._values()
        if self.availability is WorkAvailability.UNAVAILABLE_AT_FROZEN_SOURCE:
            if any(value is not None for value in values):
                raise EvaluationError(
                    "unavailable frozen-source work measurements must be null, never zero"
                )
            return
        if any(value is None for value in values):
            raise EvaluationError("available Stage 08 work measurements must be complete")
        for value in values:
            _require_nonnegative_int(value, field="work measurement")

    @classmethod
    def unavailable_at_frozen_source(cls) -> WorkMeasurement:
        return cls(
            availability=WorkAvailability.UNAVAILABLE_AT_FROZEN_SOURCE,
            prediction_invocations=None,
            compilation_invocations=None,
            retrodicted_transitions=None,
            simulation_invocations=None,
            search_expanded_nodes=None,
            cache_hits=None,
            cache_misses=None,
            cache_invalidations=None,
        )

    @classmethod
    def measured(
        cls,
        *,
        prediction_invocations: int = 0,
        compilation_invocations: int = 0,
        retrodicted_transitions: int = 0,
        simulation_invocations: int = 0,
        search_expanded_nodes: int = 0,
        cache_hits: int = 0,
        cache_misses: int = 0,
        cache_invalidations: int = 0,
    ) -> WorkMeasurement:
        return cls(
            availability=WorkAvailability.AVAILABLE,
            prediction_invocations=prediction_invocations,
            compilation_invocations=compilation_invocations,
            retrodicted_transitions=retrodicted_transitions,
            simulation_invocations=simulation_invocations,
            search_expanded_nodes=search_expanded_nodes,
            cache_hits=cache_hits,
            cache_misses=cache_misses,
            cache_invalidations=cache_invalidations,
        )

    def _values(self) -> tuple[int | None, ...]:
        return (
            self.prediction_invocations,
            self.compilation_invocations,
            self.retrodicted_transitions,
            self.simulation_invocations,
            self.search_expanded_nodes,
            self.cache_hits,
            self.cache_misses,
            self.cache_invalidations,
        )

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "availability": self.availability.value,
            "cache_hits": self.cache_hits,
            "cache_invalidations": self.cache_invalidations,
            "cache_misses": self.cache_misses,
            "compilation_invocations": self.compilation_invocations,
            "prediction_invocations": self.prediction_invocations,
            "retrodicted_transitions": self.retrodicted_transitions,
            "search_expanded_nodes": self.search_expanded_nodes,
            "simulation_invocations": self.simulation_invocations,
        }


@dataclass(frozen=True, slots=True)
class DeepTriggerMeasurement:
    """One typed DEEP trigger and its immutable source-event provenance."""

    trigger: DeepTrigger
    source_event_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.trigger, DeepTrigger):
            raise EvaluationError("deep trigger must be typed")
        if not self.source_event_ids:
            raise EvaluationError("deep trigger requires at least one source event")
        if any(not isinstance(event_id, str) or not event_id for event_id in self.source_event_ids):
            raise EvaluationError("deep trigger source IDs must be non-empty strings")
        if self.source_event_ids != tuple(sorted(set(self.source_event_ids))):
            raise EvaluationError("deep trigger source IDs must be unique and sorted")

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "source_event_ids": list(self.source_event_ids),
            "trigger": self.trigger.value,
        }


@dataclass(frozen=True, slots=True)
class ReasoningTerminalMeasurement:
    """Selected-path linkage to exactly one typed terminal reasoning receipt."""

    path_selected_event_id: str
    terminal_event_id: str
    path: ReasoningPath
    kind: ReasoningTerminalKind
    status: DeliberationStatus

    def __post_init__(self) -> None:
        _require_str(self.path_selected_event_id, field="path_selected_event_id")
        _require_str(self.terminal_event_id, field="terminal_event_id")
        if self.path_selected_event_id == self.terminal_event_id:
            raise EvaluationError("reasoning selected and terminal event IDs must differ")
        if not isinstance(self.path, ReasoningPath):
            raise EvaluationError("reasoning terminal path must be typed")
        if not isinstance(self.kind, ReasoningTerminalKind):
            raise EvaluationError("reasoning terminal kind must be typed")
        if not isinstance(self.status, DeliberationStatus):
            raise EvaluationError("reasoning terminal status must be typed")
        fallback = self.kind is ReasoningTerminalKind.FALLBACK_USED
        if fallback != (self.status is DeliberationStatus.FALLBACK_USED):
            raise EvaluationError("reasoning terminal kind and status disagree")

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "kind": self.kind.value,
            "path": self.path.value,
            "path_selected_event_id": self.path_selected_event_id,
            "status": self.status.value,
            "terminal_event_id": self.terminal_event_id,
        }


@dataclass(frozen=True, slots=True)
class ActionMeasurement:
    """One submitted boundary timing and its deterministic work projection.

    ``action_ordinal`` is local to its non-reset or reset collection, while
    ``submission_ordinal`` preserves the exact position in the combined stream
    sent to the environment.
    """

    action_ordinal: int
    submission_ordinal: int
    environment_action_identity: str
    boundary_status: BoundaryStatus
    choose_wall_ns: int | None
    choose_cpu_ns: int | None
    consequence_wall_ns: int | None
    consequence_cpu_ns: int | None
    checkpoint_wall_ns: int | None
    checkpoint_cpu_ns: int | None
    controller_total_wall_ns: int | None
    controller_total_cpu_ns: int | None
    work: WorkMeasurement
    reasoning_path: ReasoningPath | None = None
    deep_triggers: tuple[DeepTriggerMeasurement, ...] = ()
    reasoning_terminal: ReasoningTerminalMeasurement | None = None

    def __post_init__(self) -> None:
        _require_nonnegative_int(self.action_ordinal, field="action_ordinal")
        _require_nonnegative_int(self.submission_ordinal, field="submission_ordinal")
        _require_str(self.environment_action_identity, field="environment_action_identity")
        if not isinstance(self.boundary_status, BoundaryStatus):
            raise EvaluationError("boundary status must be typed")
        timings = self._timings()
        if self.boundary_status is BoundaryStatus.NORMAL and any(
            value is None for value in timings
        ):
            raise EvaluationError("normal Stage 08 boundaries require complete timing values")
        for value in timings:
            if value is not None:
                _require_nonnegative_int(value, field="action timing")
        if self.boundary_status is BoundaryStatus.NORMAL:
            assert self.choose_wall_ns is not None
            assert self.consequence_wall_ns is not None
            assert self.controller_total_wall_ns is not None
            assert self.choose_cpu_ns is not None
            assert self.consequence_cpu_ns is not None
            assert self.controller_total_cpu_ns is not None
            assert self.checkpoint_wall_ns is not None
            assert self.checkpoint_cpu_ns is not None
            expected_wall = self.choose_wall_ns + self.consequence_wall_ns + self.checkpoint_wall_ns
            expected_cpu = self.choose_cpu_ns + self.consequence_cpu_ns + self.checkpoint_cpu_ns
            if self.controller_total_wall_ns != expected_wall:
                raise EvaluationError(
                    "controller wall total must equal choose plus consequence plus checkpoint"
                )
            if self.controller_total_cpu_ns != expected_cpu:
                raise EvaluationError(
                    "controller CPU total must equal choose plus consequence plus checkpoint"
                )
        if self.reasoning_path is not None and not isinstance(self.reasoning_path, ReasoningPath):
            raise EvaluationError("reasoning path must be typed when available")
        if any(not isinstance(trigger, DeepTriggerMeasurement) for trigger in self.deep_triggers):
            raise EvaluationError("deep trigger measurements must be typed")
        ordered = tuple(item.trigger for item in self.deep_triggers)
        expected_order = tuple(trigger for trigger in DEEP_TRIGGER_PRIORITY if trigger in ordered)
        if ordered != expected_order or len(set(ordered)) != len(ordered):
            raise EvaluationError("deep triggers must be unique and priority ordered")
        if self.reasoning_path is ReasoningPath.FAST and self.deep_triggers:
            raise EvaluationError("FAST reasoning cannot carry a DEEP trigger")
        if self.reasoning_terminal is not None and not isinstance(
            self.reasoning_terminal, ReasoningTerminalMeasurement
        ):
            raise EvaluationError("reasoning terminal measurement must be typed")
        if self.reasoning_path is None and (
            self.deep_triggers or self.reasoning_terminal is not None
        ):
            raise EvaluationError("unavailable reasoning telemetry must be wholly null")
        if (
            self.reasoning_terminal is not None
            and self.reasoning_terminal.path is not self.reasoning_path
        ):
            raise EvaluationError("reasoning terminal path disagrees with the selected path")

    @property
    def reasoning_receipt_complete(self) -> bool:
        """Whether selected-path telemetry links to exactly one typed terminal receipt."""

        return self.reasoning_path is not None and self.reasoning_terminal is not None

    def _timings(self) -> tuple[int | None, ...]:
        return (
            self.choose_wall_ns,
            self.choose_cpu_ns,
            self.consequence_wall_ns,
            self.consequence_cpu_ns,
            self.checkpoint_wall_ns,
            self.checkpoint_cpu_ns,
            self.controller_total_wall_ns,
            self.controller_total_cpu_ns,
        )

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "action_ordinal": self.action_ordinal,
            "boundary_status": self.boundary_status.value,
            "checkpoint_cpu_ns": self.checkpoint_cpu_ns,
            "checkpoint_wall_ns": self.checkpoint_wall_ns,
            "choose_cpu_ns": self.choose_cpu_ns,
            "choose_wall_ns": self.choose_wall_ns,
            "consequence_cpu_ns": self.consequence_cpu_ns,
            "consequence_wall_ns": self.consequence_wall_ns,
            "controller_total_cpu_ns": self.controller_total_cpu_ns,
            "controller_total_wall_ns": self.controller_total_wall_ns,
            "deep_trigger_receipts": [item.to_dict() for item in self.deep_triggers],
            "environment_action_identity": self.environment_action_identity,
            "ordered_triggers": [item.trigger.value for item in self.deep_triggers],
            "reasoning_path": None if self.reasoning_path is None else self.reasoning_path.value,
            "reasoning_terminal_receipt": (
                None if self.reasoning_terminal is None else self.reasoning_terminal.to_dict()
            ),
            "submission_ordinal": self.submission_ordinal,
            "work": self.work.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class ScoreMeasurement:
    """Official score evidence, which may be recovered after a failed worker."""

    verified: bool
    score: float | None
    levels_completed: int | None
    completed: bool | None

    def __post_init__(self) -> None:
        if not isinstance(self.verified, bool):
            raise EvaluationError("score verification must be boolean")
        values = (self.score, self.levels_completed, self.completed)
        if not self.verified:
            if any(value is not None for value in values):
                raise EvaluationError("unverified score fields must be null")
            return
        if (
            isinstance(self.score, bool)
            or not isinstance(self.score, (int, float))
            or not math.isfinite(self.score)
            or self.score < 0.0
        ):
            raise EvaluationError("verified score must be a finite non-negative number")
        _require_nonnegative_int(self.levels_completed, field="levels_completed")
        if not isinstance(self.completed, bool):
            raise EvaluationError("verified completed must be boolean")

    @classmethod
    def unverified(cls) -> ScoreMeasurement:
        return cls(verified=False, score=None, levels_completed=None, completed=None)

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "completed": self.completed,
            "levels_completed": self.levels_completed,
            "score": self.score,
            "verified": self.verified,
        }


@dataclass(frozen=True, slots=True)
class CellResult:
    """Typed terminal result for one declared Stage 08 matrix cell."""

    cell: MeasurementCell
    status: CellStatus
    actions: tuple[ActionMeasurement, ...]
    reset_boundaries: tuple[ActionMeasurement, ...]
    score: ScoreMeasurement
    action_counts: BoundaryCounts | None
    reset_counts: BoundaryCounts | None
    evidence_availability: EvidenceAvailability
    peak_rss_bytes: int | None
    memory_measurement_valid: bool
    memory_measurement_source: str | None
    trace_bytes: int | None
    checkpoint_bytes: int | None
    terminal_state: str | None
    controller_faults: int | None
    controller_fault_identities: tuple[str, ...]
    source_identity_valid: bool = True
    receipt_integrity_valid: bool = True
    replay_valid: bool = True
    checkpoint_valid: bool = True
    network_attempt_count: int | None = 0
    holdout_exposure_count: int = 0
    failure_kind: str | None = None
    failure_domain: FailureDomain | None = None
    failure_phase: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.status, CellStatus):
            raise EvaluationError("cell status must be typed")
        if not isinstance(self.evidence_availability, EvidenceAvailability):
            raise EvaluationError("cell evidence availability must be typed")
        boolean_fields = (
            self.source_identity_valid,
            self.receipt_integrity_valid,
            self.replay_valid,
            self.checkpoint_valid,
            self.memory_measurement_valid,
        )
        if any(not isinstance(value, bool) for value in boolean_fields):
            raise EvaluationError("cell integrity fields must be boolean")
        counts = (("holdout_exposure_count", self.holdout_exposure_count),)
        for field_name, value in counts:
            _require_nonnegative_int(value, field=field_name)
        if self.evidence_availability is EvidenceAvailability.EXACT:
            if not isinstance(self.action_counts, BoundaryCounts) or not isinstance(
                self.reset_counts, BoundaryCounts
            ):
                raise EvaluationError("exact cell boundary counts must be typed")
            for optional_field_name, optional_value in (
                ("trace_bytes", self.trace_bytes),
                ("checkpoint_bytes", self.checkpoint_bytes),
                ("controller_faults", self.controller_faults),
                ("network_attempt_count", self.network_attempt_count),
            ):
                _require_nonnegative_int(optional_value, field=optional_field_name)
        elif any(
            value is not None
            for value in (
                self.action_counts,
                self.reset_counts,
                self.trace_bytes,
                self.checkpoint_bytes,
                self.controller_faults,
                self.network_attempt_count,
            )
        ):
            raise EvaluationError("unavailable cell evidence values must be null")
        if self.evidence_availability is EvidenceAvailability.UNAVAILABLE and (
            self.actions or self.reset_boundaries or self.controller_fault_identities
        ):
            raise EvaluationError("unavailable cell evidence cannot carry derived measurements")
        if self.peak_rss_bytes is not None:
            _require_nonnegative_int(self.peak_rss_bytes, field="peak_rss_bytes")
        if self.memory_measurement_source is not None:
            _require_str(self.memory_measurement_source, field="memory_measurement_source")
        if self.memory_measurement_valid and (
            self.peak_rss_bytes is None or self.memory_measurement_source is None
        ):
            raise EvaluationError(
                "valid Stage 08 memory measurement requires RSS and a measurement source"
            )
        if any(
            not isinstance(identity, str) or not identity
            for identity in self.controller_fault_identities
        ):
            raise EvaluationError("controller fault identities must be non-empty strings")
        if len(set(self.controller_fault_identities)) != len(self.controller_fault_identities):
            raise EvaluationError("controller fault identities must be unique")
        if (
            self.evidence_availability is EvidenceAvailability.EXACT
            and self.controller_faults != len(self.controller_fault_identities)
        ):
            raise EvaluationError("controller fault count and identities disagree")
        if self.action_counts is not None and self.action_counts.submitted > MAX_ACTIONS:
            raise EvaluationError("Stage 08 action budget was exceeded")
        if self.reset_counts is not None and self.reset_counts.submitted > MAX_RESETS:
            raise EvaluationError("Stage 08 action or reset budget was exceeded")
        if self.action_counts is not None and self.action_counts.submitted != len(self.actions):
            raise EvaluationError("every submitted non-reset action must retain one measurement")
        if self.reset_counts is not None and self.reset_counts.submitted != len(
            self.reset_boundaries
        ):
            raise EvaluationError("every submitted reset must retain one measurement")
        if tuple(action.action_ordinal for action in self.actions) != tuple(
            range(len(self.actions))
        ):
            raise EvaluationError("non-reset measurements must be contiguous and ordered from zero")
        if tuple(boundary.action_ordinal for boundary in self.reset_boundaries) != tuple(
            range(len(self.reset_boundaries))
        ):
            raise EvaluationError("reset measurements must be contiguous and ordered from zero")
        submitted_positions = sorted(
            boundary.submission_ordinal for boundary in self.submitted_boundaries
        )
        if submitted_positions != list(range(len(self.submitted_boundaries))):
            raise EvaluationError(
                "submitted action and reset positions must be exact, unique, and contiguous"
            )
        if self.status is CellStatus.SUCCESS:
            if any(
                value is not None
                for value in (self.failure_kind, self.failure_domain, self.failure_phase)
            ):
                raise EvaluationError("successful Stage 08 cells cannot carry failure metadata")
            if self.evidence_availability is not EvidenceAvailability.EXACT:
                raise EvaluationError("successful Stage 08 cells require exact evidence")
            if not self.score.verified:
                raise EvaluationError("successful Stage 08 cells require a verified score")
            if self.terminal_state is None:
                raise EvaluationError("successful Stage 08 cells require a terminal state")
            if self.action_counts != BoundaryCounts.completed(len(self.actions)):
                raise EvaluationError(
                    "successful Stage 08 action phase counts must be exactly consistent"
                )
            if self.reset_counts != BoundaryCounts.completed(len(self.reset_boundaries)):
                raise EvaluationError(
                    "successful Stage 08 reset phase counts must be exactly consistent"
                )
        else:
            if not self.failure_kind:
                raise EvaluationError("failed Stage 08 cells require a failure kind")
            if not isinstance(self.failure_domain, FailureDomain):
                raise EvaluationError("failed Stage 08 cells require a typed failure domain")
            if self.failure_phase is None:
                raise EvaluationError("failed Stage 08 cells require a failure phase")
            _require_str(self.failure_phase, field="failure_phase")
        if self.terminal_state is not None:
            _require_str(self.terminal_state, field="terminal_state")
        frozen_source = self.cell.variant is MeasurementVariant.FROZEN_BUILD_000_FULL
        for action in self.submitted_boundaries:
            if frozen_source and (
                action.work.availability is not WorkAvailability.UNAVAILABLE_AT_FROZEN_SOURCE
            ):
                raise EvaluationError("Build 000 integer work must be explicitly unavailable")
            if not frozen_source and action.work.availability is not WorkAvailability.AVAILABLE:
                raise EvaluationError("Build 001 integer work must be measured")
            if frozen_source and (
                action.reasoning_path is not None
                or action.deep_triggers
                or action.reasoning_terminal is not None
            ):
                raise EvaluationError("Build 000 reasoning telemetry must be null")

    @property
    def submitted_boundaries(self) -> tuple[ActionMeasurement, ...]:
        """Return all submitted boundaries in exact environment submission order."""

        return tuple(
            sorted(
                (*self.actions, *self.reset_boundaries),
                key=lambda boundary: boundary.submission_ordinal,
            )
        )

    @property
    def behavior_signature(self) -> tuple[object, ...]:
        """Exact observable outcome used for cross-variant behavior parity."""

        submitted_sequence = tuple(
            sorted(
                (
                    *(
                        (
                            boundary.submission_ordinal,
                            "non-reset",
                            boundary.environment_action_identity,
                        )
                        for boundary in self.actions
                    ),
                    *(
                        (
                            boundary.submission_ordinal,
                            "reset",
                            boundary.environment_action_identity,
                        )
                        for boundary in self.reset_boundaries
                    ),
                )
            )
        )
        return (
            submitted_sequence,
            self.action_counts,
            self.reset_counts,
            self.terminal_state,
            self.score,
            self.controller_faults,
            self.controller_fault_identities,
        )

    @property
    def resources_valid(self) -> bool:
        """Apply the frozen per-cell RSS, trace, and per-decision wall limits."""

        return (
            self.evidence_availability is EvidenceAvailability.EXACT
            and self.memory_measurement_valid
            and self.peak_rss_bytes is not None
            and self.peak_rss_bytes <= MAX_PEAK_RSS_BYTES
            and self.trace_bytes is not None
            and self.trace_bytes <= MAX_TRACE_BYTES_PER_RUN
            and all(
                action.choose_wall_ns is not None and action.choose_wall_ns <= MAX_DECISION_WALL_NS
                for action in self.submitted_boundaries
            )
        )

    @property
    def reasoning_receipts_valid(self) -> bool:
        """Fail closed on unavailable or incomplete Build 001 cadence receipts."""

        frozen_source = self.cell.variant is MeasurementVariant.FROZEN_BUILD_000_FULL
        if frozen_source:
            return all(
                action.reasoning_path is None
                and not action.deep_triggers
                and action.reasoning_terminal is None
                for action in self.submitted_boundaries
            )
        if self.cell.variant is MeasurementVariant.BUILD_001_LEGACY_ALWAYS_DEEP:
            return all(
                action.reasoning_path is ReasoningPath.DEEP and action.reasoning_receipt_complete
                for action in self.submitted_boundaries
            )
        return all(
            action.reasoning_receipt_complete
            and (
                (action.reasoning_path is ReasoningPath.FAST and not action.deep_triggers)
                or (action.reasoning_path is ReasoningPath.DEEP and bool(action.deep_triggers))
            )
            for action in self.submitted_boundaries
        )

    @property
    def integrity_valid(self) -> bool:
        return (
            self.source_identity_valid
            and self.evidence_availability is EvidenceAvailability.EXACT
            and self.receipt_integrity_valid
            and self.replay_valid
            and self.checkpoint_valid
            and self.network_attempt_count == 0
            and self.holdout_exposure_count == 0
        )

    @property
    def result_hash(self) -> str:
        return sha256_json(self.to_dict())

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "action_counts": None if self.action_counts is None else self.action_counts.to_dict(),
            "actions": [action.to_dict() for action in self.actions],
            "cell": self.cell.to_dict(),
            "checkpoint_bytes": self.checkpoint_bytes,
            "checkpoint_valid": self.checkpoint_valid,
            "controller_fault_identities": list(self.controller_fault_identities),
            "controller_faults": self.controller_faults,
            "evidence_availability": self.evidence_availability.value,
            "failure_domain": None if self.failure_domain is None else self.failure_domain.value,
            "failure_kind": self.failure_kind,
            "failure_phase": self.failure_phase,
            "holdout_exposure_count": self.holdout_exposure_count,
            "memory_measurement_source": self.memory_measurement_source,
            "memory_measurement_valid": self.memory_measurement_valid,
            "network_attempt_count": self.network_attempt_count,
            "peak_rss_bytes": self.peak_rss_bytes,
            "receipt_integrity_valid": self.receipt_integrity_valid,
            "replay_valid": self.replay_valid,
            "reset_boundaries": [boundary.to_dict() for boundary in self.reset_boundaries],
            "reset_counts": None if self.reset_counts is None else self.reset_counts.to_dict(),
            "schema": _RESULT_SCHEMA,
            "score": self.score.to_dict(),
            "source_identity_valid": self.source_identity_valid,
            "status": self.status.value,
            "terminal_state": self.terminal_state,
            "trace_bytes": self.trace_bytes,
        }

    def sealed_dict(self) -> dict[str, JSONValue]:
        return seal_canonical_object(self.to_dict(), hash_field="result_hash")


@dataclass(frozen=True, slots=True)
class ScoreMetrics:
    """One disjoint score-evidence scope from B-001-0044."""

    evidence_scope: str
    run_count: int
    score_sum: float
    mean_score: float | None
    levels_completed: int
    completed_runs: int

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "completed_runs": self.completed_runs,
            "evidence_scope": self.evidence_scope,
            "levels_completed": self.levels_completed,
            "mean_score": self.mean_score,
            "run_count": self.run_count,
            "score_sum": self.score_sum,
        }


@dataclass(frozen=True, slots=True)
class VariantScoreAggregate:
    """Successful and recovered-failure scores kept in separate namespaces."""

    variant: MeasurementVariant
    successful_score_metrics: ScoreMetrics
    recovered_failure_score_metrics: ScoreMetrics
    unscored_failure_runs: int

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "recovered_failure_score_metrics": (self.recovered_failure_score_metrics.to_dict()),
            "score_metric_scope": "SUCCESSFUL_RUNS_ONLY",
            "successful_score_metrics": self.successful_score_metrics.to_dict(),
            "unscored_failure_runs": self.unscored_failure_runs,
            "variant": self.variant.value,
        }


def aggregate_score_evidence(
    results: Sequence[CellResult], variant: MeasurementVariant
) -> VariantScoreAggregate:
    """Aggregate success scores while preserving failed-score evidence separately."""

    successful: list[ScoreMeasurement] = []
    recovered: list[ScoreMeasurement] = []
    unscored_failures = 0
    for result in results:
        if result.cell.variant is not variant:
            continue
        if result.status is CellStatus.SUCCESS:
            successful.append(result.score)
        elif result.score.verified:
            recovered.append(result.score)
        else:
            unscored_failures += 1
    return VariantScoreAggregate(
        variant=variant,
        successful_score_metrics=_score_metrics(successful, _SCORE_SCOPE_SUCCESS),
        recovered_failure_score_metrics=_score_metrics(recovered, _SCORE_SCOPE_RECOVERED_FAILURE),
        unscored_failure_runs=unscored_failures,
    )


def _score_metrics(values: Sequence[ScoreMeasurement], evidence_scope: str) -> ScoreMetrics:
    score_sum = sum(cast(float, value.score) for value in values)
    return ScoreMetrics(
        evidence_scope=evidence_scope,
        run_count=len(values),
        score_sum=score_sum,
        mean_score=score_sum / len(values) if values else None,
        levels_completed=sum(cast(int, value.levels_completed) for value in values),
        completed_runs=sum(int(cast(bool, value.completed)) for value in values),
    )


@dataclass(frozen=True, slots=True)
class ComparatorGate:
    """Frozen materiality result for TWO_SPEED against one control."""

    comparator: MeasurementVariant
    expected_cell_pairs: int
    valid_cell_pairs: int
    missing_cell_pairs: int
    failed_cell_pairs: int
    integrity_failed_cell_pairs: int
    paired_action_count: int
    censored_action_pairs: int
    median_paired_wall_ratio: float | None
    median_reduction_fraction: float | None
    nonregressing_cell_count: int
    nonregressing_cell_fraction: float
    material_reduction_passed: bool
    nonregression_passed: bool
    passed: bool

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "censored_action_pairs": self.censored_action_pairs,
            "comparator": self.comparator.value,
            "expected_cell_pairs": self.expected_cell_pairs,
            "failed_cell_pairs": self.failed_cell_pairs,
            "integrity_failed_cell_pairs": self.integrity_failed_cell_pairs,
            "material_reduction_passed": self.material_reduction_passed,
            "median_paired_wall_ratio": self.median_paired_wall_ratio,
            "median_reduction_fraction": self.median_reduction_fraction,
            "missing_cell_pairs": self.missing_cell_pairs,
            "nonregressing_cell_count": self.nonregressing_cell_count,
            "nonregressing_cell_fraction": self.nonregressing_cell_fraction,
            "nonregression_passed": self.nonregression_passed,
            "paired_action_count": self.paired_action_count,
            "passed": self.passed,
            "primary_timing_scope": "normally-returned-non-reset-boundaries-only",
            "reset_boundaries_excluded_from_primary_median": True,
            "valid_cell_pairs": self.valid_cell_pairs,
        }


@dataclass(frozen=True, slots=True)
class Stage08GateResult:
    """Fail-closed timing gate plus disjoint B44 score aggregates."""

    complete_matrix: bool
    result_count: int
    missing_cell_count: int
    terminal_failure_count: int
    censored_action_count: int
    censored_reset_count: int
    integrity_failure_count: int
    behavior_parity_failure_count: int
    resource_failure_count: int
    reasoning_receipt_failure_count: int
    comparisons: tuple[ComparatorGate, ...]
    scores: tuple[VariantScoreAggregate, ...]
    passed: bool

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "behavior_parity_failure_count": self.behavior_parity_failure_count,
            "censored_action_count": self.censored_action_count,
            "censored_reset_count": self.censored_reset_count,
            "comparisons": [comparison.to_dict() for comparison in self.comparisons],
            "complete_matrix": self.complete_matrix,
            "integrity_failure_count": self.integrity_failure_count,
            "missing_cell_count": self.missing_cell_count,
            "passed": self.passed,
            "result_count": self.result_count,
            "resource_failure_count": self.resource_failure_count,
            "reasoning_receipt_failure_count": self.reasoning_receipt_failure_count,
            "schema": _GATE_SCHEMA,
            "score_aggregates": [score.to_dict() for score in self.scores],
            "terminal_failure_count": self.terminal_failure_count,
        }


def evaluate_materiality_gates(results: Sequence[CellResult]) -> Stage08GateResult:
    """Apply paired timing gates while keeping failures and censoring out of medians."""

    expected = build_measurement_matrix()
    expected_by_id = {cell.cell_id: cell for cell in expected}
    by_id: dict[str, CellResult] = {}
    for result in results:
        cell_id = result.cell.cell_id
        if cell_id not in expected_by_id or result.cell != expected_by_id[cell_id]:
            raise EvaluationError("Stage 08 result references an undeclared measurement cell")
        if cell_id in by_id:
            raise EvaluationError("Stage 08 result cells must be unique")
        by_id[cell_id] = result

    missing_cell_count = len(expected_by_id) - len(by_id)
    terminal_failure_count = sum(
        result.status is not CellStatus.SUCCESS for result in by_id.values()
    )
    censored_action_count = sum(
        action.boundary_status is not BoundaryStatus.NORMAL
        for result in by_id.values()
        for action in result.actions
    )
    censored_reset_count = sum(
        boundary.boundary_status is not BoundaryStatus.NORMAL
        for result in by_id.values()
        for boundary in result.reset_boundaries
    )
    integrity_failure_count = sum(not result.integrity_valid for result in by_id.values())
    behavior_parity_failure_count = _behavior_parity_failure_count(expected, by_id)
    resource_failure_count = sum(not result.resources_valid for result in by_id.values())
    reasoning_receipt_failure_count = sum(
        not result.reasoning_receipts_valid for result in by_id.values()
    )
    candidate = MeasurementVariant.BUILD_001_TWO_SPEED
    comparisons = tuple(
        _evaluate_comparator(expected, by_id, candidate, comparator)
        for comparator in (
            MeasurementVariant.FROZEN_BUILD_000_FULL,
            MeasurementVariant.BUILD_001_LEGACY_ALWAYS_DEEP,
        )
    )
    complete_matrix = missing_cell_count == 0 and len(by_id) == EXPECTED_CELL_COUNT
    passed = (
        complete_matrix
        and terminal_failure_count == 0
        and censored_action_count == 0
        and censored_reset_count == 0
        and integrity_failure_count == 0
        and behavior_parity_failure_count == 0
        and resource_failure_count == 0
        and reasoning_receipt_failure_count == 0
        and all(comparison.passed for comparison in comparisons)
    )
    return Stage08GateResult(
        complete_matrix=complete_matrix,
        result_count=len(by_id),
        missing_cell_count=missing_cell_count,
        terminal_failure_count=terminal_failure_count,
        censored_action_count=censored_action_count,
        censored_reset_count=censored_reset_count,
        integrity_failure_count=integrity_failure_count,
        behavior_parity_failure_count=behavior_parity_failure_count,
        resource_failure_count=resource_failure_count,
        reasoning_receipt_failure_count=reasoning_receipt_failure_count,
        comparisons=comparisons,
        scores=tuple(
            aggregate_score_evidence(tuple(by_id.values()), variant) for variant in VARIANT_ORDER
        ),
        passed=passed,
    )


def _behavior_parity_failure_count(
    expected: Sequence[MeasurementCell], results: Mapping[str, CellResult]
) -> int:
    """Count exact behavior mismatches across all paired variants in each repetition."""

    cells_by_key = {(cell.repetition, cell.variant): cell for cell in expected}
    failures = 0
    for repetition in range(REPETITIONS_PER_VARIANT):
        paired: list[CellResult] = []
        for variant in VARIANT_ORDER:
            result = results.get(cells_by_key[(repetition, variant)].cell_id)
            if result is None or result.status is not CellStatus.SUCCESS:
                paired = []
                break
            paired.append(result)
        if not paired:
            continue
        reference = paired[0].behavior_signature
        failures += sum(result.behavior_signature != reference for result in paired[1:])
    return failures


def _evaluate_comparator(
    expected: Sequence[MeasurementCell],
    results: Mapping[str, CellResult],
    candidate: MeasurementVariant,
    comparator: MeasurementVariant,
) -> ComparatorGate:
    cells_by_key = {(cell.repetition, cell.variant): cell for cell in expected}
    action_ratios: list[float] = []
    missing = 0
    failed = 0
    integrity_failed = 0
    censored = 0
    valid_cells = 0
    nonregressing = 0
    for repetition in range(REPETITIONS_PER_VARIANT):
        candidate_cell = cells_by_key[(repetition, candidate)]
        comparator_cell = cells_by_key[(repetition, comparator)]
        candidate_result = results.get(candidate_cell.cell_id)
        comparator_result = results.get(comparator_cell.cell_id)
        if candidate_result is None or comparator_result is None:
            missing += 1
            continue
        if (
            candidate_result.status is not CellStatus.SUCCESS
            or comparator_result.status is not CellStatus.SUCCESS
        ):
            failed += 1
            continue
        if not candidate_result.integrity_valid or not comparator_result.integrity_valid:
            integrity_failed += 1
            continue
        candidate_actions = {action.action_ordinal: action for action in candidate_result.actions}
        comparator_actions = {action.action_ordinal: action for action in comparator_result.actions}
        cell_ratios: list[float] = []
        for action_ordinal in sorted(set(candidate_actions) | set(comparator_actions)):
            candidate_action = candidate_actions.get(action_ordinal)
            comparator_action = comparator_actions.get(action_ordinal)
            if (
                candidate_action is None
                or comparator_action is None
                or candidate_action.boundary_status is not BoundaryStatus.NORMAL
                or comparator_action.boundary_status is not BoundaryStatus.NORMAL
                or comparator_action.controller_total_wall_ns in {None, 0}
                or candidate_action.controller_total_wall_ns is None
            ):
                censored += 1
                continue
            candidate_wall_ns = candidate_action.controller_total_wall_ns
            comparator_wall_ns = comparator_action.controller_total_wall_ns
            assert candidate_wall_ns is not None
            assert comparator_wall_ns is not None and comparator_wall_ns > 0
            ratio = candidate_wall_ns / comparator_wall_ns
            action_ratios.append(ratio)
            cell_ratios.append(ratio)
        if cell_ratios and len(cell_ratios) == len(candidate_actions) == len(comparator_actions):
            valid_cells += 1
            if statistics.median(cell_ratios) <= 1.0:
                nonregressing += 1

    median_ratio = float(statistics.median(action_ratios)) if action_ratios else None
    reduction = None if median_ratio is None else 1.0 - median_ratio
    nonregression_fraction = nonregressing / REPETITIONS_PER_VARIANT
    material_passed = median_ratio is not None and median_ratio <= MATERIALITY_MAX_MEDIAN_RATIO
    nonregression_passed = nonregression_fraction >= NONREGRESSION_MIN_FRACTION
    passed = (
        missing == 0
        and failed == 0
        and integrity_failed == 0
        and censored == 0
        and valid_cells == REPETITIONS_PER_VARIANT
        and material_passed
        and nonregression_passed
    )
    return ComparatorGate(
        comparator=comparator,
        expected_cell_pairs=REPETITIONS_PER_VARIANT,
        valid_cell_pairs=valid_cells,
        missing_cell_pairs=missing,
        failed_cell_pairs=failed,
        integrity_failed_cell_pairs=integrity_failed,
        paired_action_count=len(action_ratios),
        censored_action_pairs=censored,
        median_paired_wall_ratio=median_ratio,
        median_reduction_fraction=reduction,
        nonregressing_cell_count=nonregressing,
        nonregressing_cell_fraction=nonregression_fraction,
        material_reduction_passed=material_passed,
        nonregression_passed=nonregression_passed,
        passed=passed,
    )


def validate_predeclaration_bytes(content: bytes) -> None:
    """Fail closed unless bytes match the frozen preimplementation declaration."""

    if sha256_bytes(content) != PREDECLARATION_SHA256:
        raise EvaluationError("Stage 08 predeclaration hash changed")


def seal_canonical_object(
    value: Mapping[str, JSONValue], *, hash_field: str
) -> dict[str, JSONValue]:
    """Return a canonical self-hashed object using the trace JSON contract."""

    unsigned = {key: item for key, item in value.items() if key != hash_field}
    sealed = dict(unsigned)
    sealed[hash_field] = sha256_json(unsigned)
    return sealed


def verify_canonical_object_hash(value: Mapping[str, JSONValue], *, hash_field: str) -> bool:
    """Verify a canonical object hash without mutating the supplied mapping."""

    expected = value.get(hash_field)
    if not isinstance(expected, str):
        return False
    unsigned = {key: item for key, item in value.items() if key != hash_field}
    try:
        return expected == sha256_json(unsigned)
    except (TypeError, ValueError):
        return False


def canonical_measurement_hash(value: object) -> str:
    """Hash any JSON-compatible Stage 08 projection canonically."""

    normalized = normalize_json(value)
    return sha256_json(normalized)


def _require_nonnegative_int(value: object, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise EvaluationError(f"{field} must be a non-negative integer")
    return value


def _require_int(value: object, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise EvaluationError(f"{field} must be an integer")
    return value


def _require_float(value: object, *, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise EvaluationError(f"{field} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise EvaluationError(f"{field} must be finite")
    return result


def _require_str(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise EvaluationError(f"{field} must be a non-empty string")
    return value


def _require_bool(value: object, *, field: str) -> bool:
    if not isinstance(value, bool):
        raise EvaluationError(f"{field} must be boolean")
    return value


__all__ = [
    "BUILD_000_PRODUCTION_COMMIT",
    "BUILD_000_PRODUCTION_TREE",
    "BUILD_001_BASELINE_COMMIT",
    "DEVELOPMENT_ASSET_SHA256",
    "DEVELOPMENT_GAME_ID",
    "EXPECTED_CELL_COUNT",
    "MATERIALITY_MAX_MEDIAN_RATIO",
    "MAX_DECISION_WALL_NS",
    "MAX_PEAK_RSS_BYTES",
    "MAX_TRACE_BYTES_PER_RUN",
    "MEASUREMENT_MATRIX_SHA256",
    "MEASUREMENT_PLAN_SHA256",
    "NONREGRESSION_MIN_FRACTION",
    "PREDECLARATION_PATH",
    "PREDECLARATION_SHA256",
    "PUBLIC_PARTITION_MANIFEST_SHA256",
    "VARIANT_ORDER",
    "ActionMeasurement",
    "BoundaryCounts",
    "BoundaryStatus",
    "CellResult",
    "CellStatus",
    "ComparatorGate",
    "DeepTrigger",
    "DeepTriggerMeasurement",
    "DeliberationStatus",
    "DevelopmentIdentity",
    "EvidenceAvailability",
    "FailureDomain",
    "MeasurementCell",
    "MeasurementVariant",
    "ReasoningPath",
    "ReasoningTerminalKind",
    "ReasoningTerminalMeasurement",
    "ScoreMeasurement",
    "ScoreMetrics",
    "Stage08GateResult",
    "VariantScoreAggregate",
    "WorkAvailability",
    "WorkMeasurement",
    "aggregate_score_evidence",
    "build_measurement_matrix",
    "build_measurement_plan",
    "canonical_measurement_hash",
    "evaluate_materiality_gates",
    "seal_canonical_object",
    "validate_predeclaration_bytes",
    "verify_canonical_object_hash",
]
