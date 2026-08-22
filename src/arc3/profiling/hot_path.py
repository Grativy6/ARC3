"""Low-overhead phase accounting for the ARC3 controller hot path.

Timing is derived diagnostic state.  It is deliberately kept outside policy
receipts so enabling this profiler cannot become an input to action selection.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import StrEnum

from arc3.types import JSONValue


class HotPathPhase(StrEnum):
    """Stable, exhaustive names used by Build 001 hot-path evidence."""

    STARTUP = "startup"
    OBSERVATION_NORMALIZATION = "observation_normalization"
    PERCEPTION = "perception"
    CORRESPONDENCE = "correspondence"
    HYPOTHESIS_UPDATE = "hypothesis_update"
    WORLD_MODEL_COMPILATION = "world_model_compilation"
    RETRODICTION = "retrodiction"
    GOAL_INFERENCE = "goal_inference"
    PLANNING = "planning"
    ACTION_SELECTION = "action_selection"
    TRACE_SERIALIZATION = "trace_serialization"
    ENVIRONMENT_STEP = "environment_step"
    CHECKPOINTING = "checkpointing"
    RENDERING_DEBUG = "rendering_debug"
    FINALIZE = "finalize"
    CONTROLLER_ORCHESTRATION = "controller_orchestration"
    PROFILER_TELEMETRY = "profiler_telemetry"
    RUNTIME_REMAINDER = "runtime_remainder"


class HotPathChangeKind(StrEnum):
    """Stable structural categories for repeated-computation accounting."""

    INITIAL = "initial"
    UNCHANGED = "unchanged"
    LOCAL_CHANGE = "local_change"
    GLOBAL_CHANGE = "global_change"
    HISTORY_GROWTH = "history_growth"


@dataclass(slots=True)
class _PhaseAggregate:
    calls: int = 0
    inclusive_wall_ns: int = 0
    exclusive_wall_ns: int = 0
    inclusive_cpu_ns: int = 0
    exclusive_cpu_ns: int = 0
    cache_hits: int = 0
    cache_misses: int = 0
    cache_opportunity_misses: int = 0
    input_observations: int = 0
    unique_inputs: int = 0
    repeated_inputs: int = 0
    change_kind_counts: dict[HotPathChangeKind, int] = field(
        default_factory=lambda: {kind: 0 for kind in HotPathChangeKind}
    )


@dataclass(slots=True)
class _ActiveSpan:
    phase: HotPathPhase
    wall_started_ns: int
    cpu_started_ns: int
    child_wall_ns: int = 0
    child_cpu_ns: int = 0


@dataclass(frozen=True, slots=True)
class _BoundarySample:
    sequence: int
    kind: str
    segment_index: int
    actions: int
    wall_elapsed_ns: int
    cpu_elapsed_ns: int
    current_rss_bytes: int | None
    peak_rss_bytes: int | None
    rss_source: str
    rss_reason: str | None
    phase_cumulative: dict[str, JSONValue]

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "actions": self.actions,
            "cpu_elapsed_ns": self.cpu_elapsed_ns,
            "current_rss_bytes": self.current_rss_bytes,
            "kind": self.kind,
            "peak_rss_bytes": self.peak_rss_bytes,
            "phase_cumulative": self.phase_cumulative,
            "rss_reason": self.rss_reason,
            "rss_source": self.rss_source,
            "segment_index": self.segment_index,
            "sequence": self.sequence,
            "wall_elapsed_ns": self.wall_elapsed_ns,
        }


Clock = Callable[[], int]
RSSSampler = Callable[[], Mapping[str, JSONValue]]


def _default_rss_sampler() -> Mapping[str, JSONValue]:
    # Imported lazily so controller code can type against a local protocol and
    # never create a profiling-package import cycle.
    from .runtime import process_memory_sample

    return process_memory_sample()


def _optional_non_negative_int(value: JSONValue | None) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    return None


def _phase_payload(aggregate: _PhaseAggregate) -> dict[str, JSONValue]:
    return {
        "cache_hits": aggregate.cache_hits,
        "cache_misses": aggregate.cache_misses,
        "cache_opportunity_misses": aggregate.cache_opportunity_misses,
        "calls": aggregate.calls,
        "exclusive_cpu_ns": aggregate.exclusive_cpu_ns,
        "exclusive_wall_ns": aggregate.exclusive_wall_ns,
        "input_observations": aggregate.input_observations,
        "inclusive_cpu_ns": aggregate.inclusive_cpu_ns,
        "inclusive_wall_ns": aggregate.inclusive_wall_ns,
        "repeated_inputs": aggregate.repeated_inputs,
        "unique_inputs": aggregate.unique_inputs,
        "change_kind_counts": {
            kind.value: aggregate.change_kind_counts[kind] for kind in HotPathChangeKind
        },
    }


def _cumulative_phase_payload(aggregate: _PhaseAggregate) -> dict[str, JSONValue]:
    return {
        "calls": aggregate.calls,
        "exclusive_cpu_ns": aggregate.exclusive_cpu_ns,
        "exclusive_wall_ns": aggregate.exclusive_wall_ns,
    }


class HotPathProfiler:
    """Collect deterministic aggregate structure with optional runtime timing.

    The profiler is single-threaded by design, matching one ARC3 controller
    worker.  Nested spans use child subtraction so summed exclusive phase time
    does not double count inner work.
    """

    def __init__(
        self,
        enabled: bool = True,
        *,
        wall_clock: Clock = time.perf_counter_ns,
        cpu_clock: Clock = time.process_time_ns,
        rss_sampler: RSSSampler = _default_rss_sampler,
    ) -> None:
        self._enabled = enabled
        self._wall_clock = wall_clock
        self._cpu_clock = cpu_clock
        self._rss_sampler = rss_sampler
        self._aggregates = {phase: _PhaseAggregate() for phase in HotPathPhase}
        self._seen_inputs: dict[HotPathPhase, set[tuple[int, str]]] = {
            phase: set() for phase in HotPathPhase
        }
        self._stack: list[_ActiveSpan] = []
        self._boundaries: list[_BoundarySample] = []
        self._last_boundary_actions = 0
        self._max_actions_observed = 0
        self._segment_index = 0
        # A disabled profiler is a true no-op: constructing it reads no clock.
        self._wall_started_ns = wall_clock() if enabled else 0
        self._cpu_started_ns = cpu_clock() if enabled else 0

    @property
    def enabled(self) -> bool:
        """Whether timing, cache, and boundary observations are collected."""

        return self._enabled

    @staticmethod
    def _phase(value: HotPathPhase | str) -> HotPathPhase:
        phase = value if isinstance(value, HotPathPhase) else HotPathPhase(value)
        if phase is HotPathPhase.RUNTIME_REMAINDER:
            raise ValueError("runtime_remainder is derived and cannot be timed directly")
        return phase

    @staticmethod
    def _change_kind(value: HotPathChangeKind | str) -> HotPathChangeKind:
        return value if isinstance(value, HotPathChangeKind) else HotPathChangeKind(value)

    @staticmethod
    def _named_phases() -> tuple[HotPathPhase, ...]:
        return tuple(phase for phase in HotPathPhase if phase is not HotPathPhase.RUNTIME_REMAINDER)

    def _phase_cumulative(
        self,
        *,
        total_wall_ns: int,
        total_cpu_ns: int,
    ) -> dict[str, JSONValue]:
        named_phases = self._named_phases()
        named_wall = sum(self._aggregates[phase].exclusive_wall_ns for phase in named_phases)
        named_cpu = sum(self._aggregates[phase].exclusive_cpu_ns for phase in named_phases)
        payload: dict[str, JSONValue] = {
            phase.value: _cumulative_phase_payload(self._aggregates[phase])
            for phase in named_phases
        }
        remainder_wall = max(0, total_wall_ns - named_wall)
        remainder_cpu = max(0, total_cpu_ns - named_cpu)
        payload[HotPathPhase.RUNTIME_REMAINDER.value] = _cumulative_phase_payload(
            _PhaseAggregate(
                calls=int(remainder_wall > 0 or remainder_cpu > 0),
                inclusive_wall_ns=remainder_wall,
                exclusive_wall_ns=remainder_wall,
                inclusive_cpu_ns=remainder_cpu,
                exclusive_cpu_ns=remainder_cpu,
            )
        )
        return payload

    @contextmanager
    def span(self, phase: HotPathPhase | str) -> Iterator[None]:
        """Measure one possibly nested phase, or yield immediately when disabled."""

        if not self._enabled:
            yield
            return
        parsed = self._phase(phase)
        active = _ActiveSpan(
            phase=parsed,
            wall_started_ns=self._wall_clock(),
            cpu_started_ns=self._cpu_clock(),
        )
        self._stack.append(active)
        try:
            yield
        finally:
            cpu_elapsed = max(0, self._cpu_clock() - active.cpu_started_ns)
            wall_elapsed = max(0, self._wall_clock() - active.wall_started_ns)
            popped = self._stack.pop()
            if popped is not active:
                raise RuntimeError("hot-path spans exited out of nesting order")
            exclusive_wall = max(0, wall_elapsed - active.child_wall_ns)
            exclusive_cpu = max(0, cpu_elapsed - active.child_cpu_ns)
            aggregate = self._aggregates[parsed]
            aggregate.calls += 1
            aggregate.inclusive_wall_ns += wall_elapsed
            aggregate.exclusive_wall_ns += exclusive_wall
            aggregate.inclusive_cpu_ns += cpu_elapsed
            aggregate.exclusive_cpu_ns += exclusive_cpu
            if self._stack:
                parent = self._stack[-1]
                parent.child_wall_ns += wall_elapsed
                parent.child_cpu_ns += cpu_elapsed

    def cache(
        self,
        phase: HotPathPhase | str,
        hit: bool | None,
        *,
        input_key: str | None = None,
        change_kind: HotPathChangeKind | str | None = None,
    ) -> None:
        """Record cache use and privacy-preserving repeated-input structure.

        Input keys are retained only in-memory for equality checks and are never
        included in a profile payload.
        """

        if not self._enabled:
            return
        parsed_phase = self._phase(phase)
        if hit is not None and not isinstance(hit, bool):
            raise ValueError("cache hit must be boolean or None")
        if input_key is not None and (not isinstance(input_key, str) or not input_key):
            raise ValueError("cache input_key must be a non-empty string or None")
        parsed_change = self._change_kind(change_kind) if change_kind is not None else None
        aggregate = self._aggregates[parsed_phase]
        if hit is True:
            aggregate.cache_hits += 1
        elif hit is False:
            aggregate.cache_misses += 1
        else:
            aggregate.cache_opportunity_misses += 1
        if input_key is not None:
            aggregate.input_observations += 1
            segmented_key = (self._segment_index, input_key)
            seen = self._seen_inputs[parsed_phase]
            if segmented_key in seen:
                aggregate.repeated_inputs += 1
            else:
                seen.add(segmented_key)
                aggregate.unique_inputs += 1
        if parsed_change is not None:
            aggregate.change_kind_counts[parsed_change] += 1

    def boundary(self, kind: str, *, actions: int) -> None:
        """Sample action count and whole-process RSS at a controller boundary."""

        if not self._enabled:
            return
        if not isinstance(kind, str) or not kind.strip():
            raise ValueError("boundary kind must be a non-empty string")
        if isinstance(actions, bool) or not isinstance(actions, int) or actions < 0:
            raise ValueError("boundary actions must be a non-negative integer")
        normalized_kind = kind.strip()
        begins_segment = normalized_kind in {"reset", "restore"}
        if self._boundaries and begins_segment:
            self._segment_index += 1
        elif actions < self._last_boundary_actions:
            raise ValueError("boundary action count cannot decrease")
        try:
            with self.span(HotPathPhase.PROFILER_TELEMETRY):
                memory = self._rss_sampler()
                if not isinstance(memory, Mapping):
                    raise TypeError("RSS sampler returned a non-mapping value")
                reason_value = memory.get("reason")
                reason = reason_value if isinstance(reason_value, str) else None
                source_value = memory.get("measurement_source")
                source = source_value if isinstance(source_value, str) else "unavailable"
                current_rss = _optional_non_negative_int(memory.get("current_rss_bytes"))
                peak_rss = _optional_non_negative_int(memory.get("peak_rss_bytes"))
        except Exception as error:
            current_rss = None
            peak_rss = None
            source = "unavailable"
            reason = f"rss_sampler_error:{type(error).__name__}"
        wall_elapsed = max(0, self._wall_clock() - self._wall_started_ns)
        cpu_elapsed = max(0, self._cpu_clock() - self._cpu_started_ns)
        self._boundaries.append(
            _BoundarySample(
                sequence=len(self._boundaries),
                kind=normalized_kind,
                segment_index=self._segment_index,
                actions=actions,
                wall_elapsed_ns=wall_elapsed,
                cpu_elapsed_ns=cpu_elapsed,
                current_rss_bytes=current_rss,
                peak_rss_bytes=peak_rss,
                rss_source=source,
                rss_reason=reason,
                phase_cumulative=self._phase_cumulative(
                    total_wall_ns=wall_elapsed,
                    total_cpu_ns=cpu_elapsed,
                ),
            )
        )
        self._last_boundary_actions = actions
        self._max_actions_observed = max(self._max_actions_observed, actions)

    def summary(self, total_wall_ns: int | None = None) -> dict[str, JSONValue]:
        """Return a stable JSON-compatible view with exclusive-time coverage."""

        if total_wall_ns is not None and (
            isinstance(total_wall_ns, bool)
            or not isinstance(total_wall_ns, int)
            or total_wall_ns < 0
        ):
            raise ValueError("total_wall_ns must be a non-negative integer or None")
        if not self._enabled:
            return {
                "active_span_count": 0,
                "attribution_coverage": 0.0,
                "boundaries": [],
                "boundary_count": 0,
                "cache_totals": {
                    "change_kind_counts": {kind.value: 0 for kind in HotPathChangeKind},
                    "hits": 0,
                    "input_observations": 0,
                    "misses": 0,
                    "opportunity_misses": 0,
                    "repeated_inputs": 0,
                    "unique_inputs": 0,
                },
                "current_segment_index": None,
                "enabled": False,
                "max_actions_observed": 0,
                "named_exclusive_cpu_ns": 0,
                "named_exclusive_wall_ns": 0,
                "over_attributed_wall_ns": 0,
                "phases": {
                    phase.value: _phase_payload(_PhaseAggregate()) for phase in HotPathPhase
                },
                "schema": "arc3.hot-path-profile.v0.2",
                "segment_count": 0,
                "total_cpu_ns": 0,
                "total_wall_ns": 0,
                "units": {"cpu": "nanoseconds", "memory": "bytes", "wall": "nanoseconds"},
            }
        measured_total_wall = (
            max(0, self._wall_clock() - self._wall_started_ns)
            if total_wall_ns is None
            else total_wall_ns
        )
        measured_total_cpu = max(0, self._cpu_clock() - self._cpu_started_ns)
        named_phases = self._named_phases()
        named_wall = sum(self._aggregates[phase].exclusive_wall_ns for phase in named_phases)
        named_cpu = sum(self._aggregates[phase].exclusive_cpu_ns for phase in named_phases)
        remainder_wall = max(0, measured_total_wall - named_wall)
        remainder_cpu = max(0, measured_total_cpu - named_cpu)
        over_attributed_wall = max(0, named_wall - measured_total_wall)
        if measured_total_wall == 0:
            coverage = 1.0 if named_wall == 0 else 0.0
        else:
            coverage = round(min(1.0, named_wall / measured_total_wall), 12)
        phases: dict[str, JSONValue] = {
            phase.value: _phase_payload(self._aggregates[phase]) for phase in named_phases
        }
        phases[HotPathPhase.RUNTIME_REMAINDER.value] = _phase_payload(
            _PhaseAggregate(
                calls=int(remainder_wall > 0 or remainder_cpu > 0),
                inclusive_wall_ns=remainder_wall,
                exclusive_wall_ns=remainder_wall,
                inclusive_cpu_ns=remainder_cpu,
                exclusive_cpu_ns=remainder_cpu,
            )
        )
        cache_hits = sum(self._aggregates[phase].cache_hits for phase in named_phases)
        cache_misses = sum(self._aggregates[phase].cache_misses for phase in named_phases)
        opportunity_misses = sum(
            self._aggregates[phase].cache_opportunity_misses for phase in named_phases
        )
        input_observations = sum(
            self._aggregates[phase].input_observations for phase in named_phases
        )
        unique_inputs = sum(self._aggregates[phase].unique_inputs for phase in named_phases)
        repeated_inputs = sum(self._aggregates[phase].repeated_inputs for phase in named_phases)
        change_kind_counts: dict[str, JSONValue] = {
            kind.value: sum(
                self._aggregates[phase].change_kind_counts[kind] for phase in named_phases
            )
            for kind in HotPathChangeKind
        }
        return {
            "active_span_count": len(self._stack),
            "attribution_coverage": coverage,
            "boundaries": [sample.to_dict() for sample in self._boundaries],
            "boundary_count": len(self._boundaries),
            "cache_totals": {
                "change_kind_counts": change_kind_counts,
                "hits": cache_hits,
                "input_observations": input_observations,
                "misses": cache_misses,
                "opportunity_misses": opportunity_misses,
                "repeated_inputs": repeated_inputs,
                "unique_inputs": unique_inputs,
            },
            "current_segment_index": self._segment_index if self._boundaries else None,
            "enabled": True,
            "max_actions_observed": self._max_actions_observed,
            "named_exclusive_cpu_ns": named_cpu,
            "named_exclusive_wall_ns": named_wall,
            "over_attributed_wall_ns": over_attributed_wall,
            "phases": phases,
            "schema": "arc3.hot-path-profile.v0.2",
            "segment_count": self._segment_index + 1 if self._boundaries else 0,
            "total_cpu_ns": measured_total_cpu,
            "total_wall_ns": measured_total_wall,
            "units": {"cpu": "nanoseconds", "memory": "bytes", "wall": "nanoseconds"},
        }


class NullHotPathProfiler(HotPathProfiler):
    """Explicit reusable profiler whose operations perform no measurements."""

    def __init__(self) -> None:
        super().__init__(enabled=False)


NULL_HOT_PATH_PROFILER = NullHotPathProfiler()


__all__ = [
    "NULL_HOT_PATH_PROFILER",
    "HotPathChangeKind",
    "HotPathPhase",
    "HotPathProfiler",
    "NullHotPathProfiler",
]
