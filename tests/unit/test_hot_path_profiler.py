"""Unit contracts for low-overhead Build 001 hot-path accounting."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import cast

import pytest

from arc3.profiling import HotPathPhase, HotPathProfiler, NullHotPathProfiler
from arc3.profiling.hot_path import HotPathChangeKind
from arc3.types import JSONValue


class _Clock:
    def __init__(self, *values: int) -> None:
        self._values = iter(values)

    def __call__(self) -> int:
        return next(self._values)


def _raising_clock() -> int:
    raise AssertionError("disabled profiler touched a clock")


def _raising_rss() -> Mapping[str, JSONValue]:
    raise AssertionError("disabled profiler sampled RSS")


def _phase(summary: dict[str, JSONValue], phase: HotPathPhase) -> dict[str, JSONValue]:
    phases = cast(dict[str, JSONValue], summary["phases"])
    return cast(dict[str, JSONValue], phases[phase.value])


def test_phase_vocabulary_is_exact_and_stable() -> None:
    assert tuple(phase.value for phase in HotPathPhase) == (
        "startup",
        "observation_normalization",
        "perception",
        "correspondence",
        "hypothesis_update",
        "world_model_compilation",
        "retrodiction",
        "goal_inference",
        "planning",
        "action_selection",
        "trace_serialization",
        "environment_step",
        "checkpointing",
        "rendering_debug",
        "finalize",
        "controller_orchestration",
        "profiler_telemetry",
        "runtime_remainder",
    )


def test_disabled_profiler_is_a_true_noop_without_clock_or_rss_access() -> None:
    profiler = HotPathProfiler(
        enabled=False,
        wall_clock=_raising_clock,
        cpu_clock=_raising_clock,
        rss_sampler=_raising_rss,
    )
    with profiler.span("planning"):
        profiler.cache(
            "planning",
            True,
            input_key="ignored-while-disabled",
            change_kind="unchanged",
        )
    profiler.boundary("decision", actions=9)
    summary = profiler.summary(total_wall_ns=123)

    assert profiler.enabled is False
    assert summary["schema"] == "arc3.hot-path-profile.v0.2"
    assert summary["enabled"] is False
    assert summary["total_wall_ns"] == 0
    assert summary["boundary_count"] == 0
    assert _phase(summary, HotPathPhase.PLANNING)["calls"] == 0
    assert NullHotPathProfiler().enabled is False


def test_nested_spans_account_inclusive_and_exclusive_time_without_double_count() -> None:
    profiler = HotPathProfiler(
        wall_clock=_Clock(0, 10, 20, 50, 90),
        cpu_clock=_Clock(0, 10, 20, 45, 80, 100),
        rss_sampler=_raising_rss,
    )
    with profiler.span("observation_normalization"):
        with profiler.span(HotPathPhase.PERCEPTION):
            pass
    summary = profiler.summary(total_wall_ns=100)
    normalization = _phase(summary, HotPathPhase.OBSERVATION_NORMALIZATION)
    perception = _phase(summary, HotPathPhase.PERCEPTION)
    remainder = _phase(summary, HotPathPhase.RUNTIME_REMAINDER)

    assert normalization["inclusive_wall_ns"] == 80
    assert normalization["exclusive_wall_ns"] == 50
    assert normalization["inclusive_cpu_ns"] == 70
    assert normalization["exclusive_cpu_ns"] == 45
    assert perception["inclusive_wall_ns"] == 30
    assert perception["exclusive_wall_ns"] == 30
    assert perception["inclusive_cpu_ns"] == 25
    assert perception["exclusive_cpu_ns"] == 25
    assert summary["named_exclusive_wall_ns"] == 80
    assert summary["named_exclusive_cpu_ns"] == 70
    assert summary["attribution_coverage"] == 0.8
    assert remainder["exclusive_wall_ns"] == 20
    assert remainder["exclusive_cpu_ns"] == 30


def test_cache_and_boundary_samples_are_typed_ordered_and_serializable() -> None:
    profiler = HotPathProfiler(
        wall_clock=_Clock(0, 25, 80, 100, 120, 150),
        cpu_clock=_Clock(0, 10, 40, 50, 70, 100, 110),
        rss_sampler=lambda: {
            "current_rss_bytes": 4096,
            "measurement_source": "test-kernel-surface",
            "peak_rss_bytes": 8192,
            "reason": None,
        },
    )
    profiler.cache("perception", True)
    profiler.cache(HotPathPhase.PERCEPTION, False)
    profiler.cache("perception", None)
    with profiler.span("perception"):
        pass
    profiler.boundary("consequence", actions=1)
    summary = profiler.summary(total_wall_ns=150)
    perception = _phase(summary, HotPathPhase.PERCEPTION)
    boundaries = cast(list[JSONValue], summary["boundaries"])
    boundary = cast(dict[str, JSONValue], boundaries[0])

    assert perception["cache_hits"] == 1
    assert perception["cache_misses"] == 1
    assert perception["cache_opportunity_misses"] == 1
    cache_totals = cast(dict[str, JSONValue], summary["cache_totals"])
    assert cache_totals["hits"] == 1
    assert cache_totals["misses"] == 1
    assert cache_totals["opportunity_misses"] == 1
    assert boundary["actions"] == 1
    assert boundary["cpu_elapsed_ns"] == 100
    assert boundary["current_rss_bytes"] == 4096
    assert boundary["kind"] == "consequence"
    assert boundary["peak_rss_bytes"] == 8192
    assert boundary["rss_reason"] is None
    assert boundary["rss_source"] == "test-kernel-surface"
    assert boundary["segment_index"] == 0
    assert boundary["sequence"] == 0
    assert boundary["wall_elapsed_ns"] == 150
    cumulative = cast(dict[str, JSONValue], boundary["phase_cumulative"])
    telemetry = cast(dict[str, JSONValue], cumulative[HotPathPhase.PROFILER_TELEMETRY])
    assert telemetry == {
        "calls": 1,
        "exclusive_cpu_ns": 20,
        "exclusive_wall_ns": 20,
    }
    assert json.loads(json.dumps(summary, allow_nan=False, sort_keys=True)) == summary


def test_invalid_phase_boundary_and_total_values_fail_closed() -> None:
    profiler = HotPathProfiler(
        wall_clock=_Clock(0),
        cpu_clock=_Clock(0),
        rss_sampler=_raising_rss,
    )
    with pytest.raises(ValueError, match="runtime_remainder"):
        with profiler.span("runtime_remainder"):
            pass
    with pytest.raises(ValueError):
        profiler.cache("not-a-phase", True)
    with pytest.raises(ValueError, match="boolean or None"):
        profiler.cache("planning", cast(bool | None, 1))
    with pytest.raises(ValueError, match="non-empty string"):
        profiler.cache("planning", True, input_key="")
    with pytest.raises(ValueError):
        profiler.cache("planning", True, change_kind="not-a-change-kind")
    with pytest.raises(ValueError, match="non-empty"):
        profiler.boundary(" ", actions=0)
    with pytest.raises(ValueError, match="non-negative"):
        profiler.boundary("decision", actions=-1)
    with pytest.raises(ValueError, match="total_wall_ns"):
        profiler.summary(total_wall_ns=-1)


def test_boundary_action_count_cannot_move_backward() -> None:
    profiler = HotPathProfiler(
        wall_clock=_Clock(0, 10, 20, 30),
        cpu_clock=_Clock(0, 5, 10, 15),
        rss_sampler=lambda: {
            "current_rss_bytes": None,
            "measurement_source": "unavailable",
            "peak_rss_bytes": None,
            "reason": "test",
        },
    )
    profiler.boundary("consequence", actions=2)
    with pytest.raises(ValueError, match="cannot decrease"):
        profiler.boundary("decision", actions=1)


def test_reset_and_restore_boundaries_start_explicit_new_segments() -> None:
    profiler = HotPathProfiler(
        rss_sampler=lambda: {
            "current_rss_bytes": 1024,
            "measurement_source": "test",
            "peak_rss_bytes": 2048,
            "reason": None,
        }
    )

    profiler.boundary("reset", actions=0)
    profiler.boundary("decision", actions=2)
    profiler.boundary("reset", actions=0)
    profiler.boundary("decision", actions=1)
    profiler.boundary("restore", actions=0)
    profiler.boundary("decision", actions=3)
    summary = profiler.summary()
    boundaries = cast(list[dict[str, JSONValue]], summary["boundaries"])

    assert [item["segment_index"] for item in boundaries] == [0, 0, 1, 1, 2, 2]
    assert summary["segment_count"] == 3
    assert summary["current_segment_index"] == 2
    assert summary["max_actions_observed"] == 3


def test_rss_sampler_failure_is_recorded_without_escaping_boundary() -> None:
    def raising_sampler() -> Mapping[str, JSONValue]:
        raise RuntimeError("synthetic sampler failure")

    profiler = HotPathProfiler(rss_sampler=raising_sampler)
    profiler.boundary("decision", actions=1)
    summary = profiler.summary()
    boundaries = cast(list[dict[str, JSONValue]], summary["boundaries"])
    boundary = boundaries[0]

    assert boundary["current_rss_bytes"] is None
    assert boundary["peak_rss_bytes"] is None
    assert boundary["rss_source"] == "unavailable"
    assert "rss_sampler_error:RuntimeError" in cast(str, boundary["rss_reason"])
    telemetry = _phase(summary, HotPathPhase.PROFILER_TELEMETRY)
    assert telemetry["calls"] == 1


def test_boundaries_snapshot_cumulative_phase_counts_for_action_deltas() -> None:
    profiler = HotPathProfiler(
        rss_sampler=lambda: {
            "current_rss_bytes": None,
            "measurement_source": "unavailable",
            "peak_rss_bytes": None,
            "reason": "test",
        }
    )

    with profiler.span("planning"):
        pass
    profiler.boundary("decision", actions=1)
    with profiler.span("planning"):
        pass
    profiler.boundary("decision", actions=2)
    boundaries = cast(list[dict[str, JSONValue]], profiler.summary()["boundaries"])
    first = cast(dict[str, JSONValue], boundaries[0]["phase_cumulative"])
    second = cast(dict[str, JSONValue], boundaries[1]["phase_cumulative"])
    first_planning = cast(dict[str, JSONValue], first[HotPathPhase.PLANNING.value])
    second_planning = cast(dict[str, JSONValue], second[HotPathPhase.PLANNING.value])

    assert first_planning["calls"] == 1
    assert second_planning["calls"] == 2
    assert cast(int, second_planning["exclusive_wall_ns"]) >= cast(
        int, first_planning["exclusive_wall_ns"]
    )
    assert cast(int, second_planning["exclusive_cpu_ns"]) >= cast(
        int, first_planning["exclusive_cpu_ns"]
    )
    assert set(first) == {phase.value for phase in HotPathPhase}


def test_cache_inputs_track_repetition_and_change_without_emitting_keys() -> None:
    profiler = HotPathProfiler()
    profiler.cache(
        "perception",
        False,
        input_key="sensitive-frame-key-a",
        change_kind=HotPathChangeKind.INITIAL,
    )
    profiler.cache(
        "perception",
        True,
        input_key="sensitive-frame-key-a",
        change_kind="unchanged",
    )
    profiler.cache(
        "perception",
        None,
        input_key="sensitive-frame-key-b",
        change_kind="local_change",
    )
    summary = profiler.summary()
    perception = _phase(summary, HotPathPhase.PERCEPTION)
    changes = cast(dict[str, JSONValue], perception["change_kind_counts"])

    assert perception["input_observations"] == 3
    assert perception["unique_inputs"] == 2
    assert perception["repeated_inputs"] == 1
    assert changes == {
        "initial": 1,
        "unchanged": 1,
        "local_change": 1,
        "global_change": 0,
        "history_growth": 0,
    }
    rendered = json.dumps(summary, allow_nan=False, sort_keys=True)
    assert "sensitive-frame-key-a" not in rendered
    assert "sensitive-frame-key-b" not in rendered
