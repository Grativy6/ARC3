"""Integration contracts proving hot-path diagnostics do not steer policy."""

from __future__ import annotations

from dataclasses import dataclass
from itertools import count
from pathlib import Path
from typing import cast

import pytest

import arc3.trace.schema as trace_schema
from arc3.adapters.synthetic import SYNTHETIC_GAME_ID, SyntheticAdapter
from arc3.config import ARC3Config, BudgetConfig
from arc3.policy import (
    ActionDecision,
    ARC3Controller,
    ControllerPhase,
    ControllerPreset,
    ControllerSnapshot,
    RunContext,
)
from arc3.profiling import HotPathPhase, HotPathProfiler
from arc3.types import EnvironmentMode, JSONValue


@dataclass(frozen=True, slots=True)
class _RunResult:
    decisions: tuple[ActionDecision, ...]
    snapshots: tuple[ControllerSnapshot, ...]
    profile: dict[str, JSONValue] | None


def _freeze_trace_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    """Give separate runs identical valid receipt identities and timestamps."""

    event_numbers = count(1)
    monkeypatch.setattr(
        trace_schema,
        "new_event_id",
        lambda: f"E-hot-path-profile-{next(event_numbers):08d}",
    )
    monkeypatch.setattr(
        trace_schema,
        "utc_now",
        lambda: "2026-08-21T00:00:00.000000Z",
    )


def _context(tmp_path: Path, label: str) -> RunContext:
    return RunContext(
        run_id="run-hot-path-profile",
        episode_id="episode-hot-path-profile",
        game_id=SYNTHETIC_GAME_ID,
        trace_root=tmp_path / label / "trace",
        checkpoint_root=tmp_path / label / "checkpoint",
        config=ARC3Config(
            mode=EnvironmentMode.SYNTHETIC,
            seed=7,
            profile="hot-path-profile-integration",
            budgets=BudgetConfig(max_actions=8, max_search_nodes=2_048),
        ),
        git_commit="hot-path-profile-integration",
    )


def _profile_phase(profile: dict[str, JSONValue], phase: HotPathPhase) -> dict[str, JSONValue]:
    phases = cast(dict[str, JSONValue], profile["phases"])
    return cast(dict[str, JSONValue], phases[phase.value])


def _run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    label: str,
    profiler: HotPathProfiler | None,
) -> _RunResult:
    _freeze_trace_identity(monkeypatch)
    session = SyntheticAdapter(seed=7, size=8, max_steps=16).open(SYNTHETIC_GAME_ID)
    controller = ARC3Controller(ControllerPreset.FULL, hot_path_profiler=profiler)
    controller.reset(_context(tmp_path, label))
    controller.observe(session.observation)

    decisions: list[ActionDecision] = []
    snapshots = [controller.snapshot]
    while controller.phase not in {ControllerPhase.COMPLETE, ControllerPhase.GAME_OVER}:
        decision = controller.choose_action()
        decisions.append(decision)
        snapshots.append(controller.snapshot)
        if profiler is None:
            consequence = session.step(decision.action)
        else:
            with profiler.span(HotPathPhase.ENVIRONMENT_STEP):
                consequence = session.step(decision.action)
        controller.apply_consequence(consequence)
        snapshots.append(controller.snapshot)
        if len(decisions) >= 8:
            break

    session.close()
    controller.close()
    snapshots.append(controller.snapshot)
    profile = profiler.summary() if profiler is not None else None
    return _RunResult(tuple(decisions), tuple(snapshots), profile)


@pytest.mark.integration
def test_profiler_enabled_disabled_and_absent_preserve_exact_policy_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    absent = _run(tmp_path, monkeypatch, label="absent", profiler=None)
    disabled_profiler = HotPathProfiler(enabled=False)
    disabled = _run(
        tmp_path,
        monkeypatch,
        label="disabled",
        profiler=disabled_profiler,
    )
    enabled_profiler = HotPathProfiler(
        rss_sampler=lambda: {
            "current_rss_bytes": 4096,
            "measurement_source": "deterministic-test-sample",
            "peak_rss_bytes": 8192,
            "reason": None,
        }
    )
    enabled = _run(
        tmp_path,
        monkeypatch,
        label="enabled",
        profiler=enabled_profiler,
    )

    assert absent.decisions
    assert absent.decisions == disabled.decisions == enabled.decisions
    assert absent.snapshots == disabled.snapshots == enabled.snapshots
    assert absent.profile is None
    assert disabled.profile is not None
    assert disabled.profile["enabled"] is False
    assert disabled.profile["boundary_count"] == 0


@pytest.mark.integration
def test_enabled_profiler_exposes_phases_boundaries_and_cache_opportunities(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    profiler = HotPathProfiler(
        rss_sampler=lambda: {
            "current_rss_bytes": 4096,
            "measurement_source": "deterministic-test-sample",
            "peak_rss_bytes": 8192,
            "reason": None,
        }
    )
    result = _run(tmp_path, monkeypatch, label="telemetry", profiler=profiler)
    assert result.profile is not None
    profile = result.profile

    assert profile["schema"] == "arc3.hot-path-profile.v0.2"
    assert profile["enabled"] is True
    assert profile["active_span_count"] == 0
    assert profile["max_actions_observed"] == result.snapshots[-1].actions_used
    for phase in (
        HotPathPhase.STARTUP,
        HotPathPhase.PERCEPTION,
        HotPathPhase.ACTION_SELECTION,
        HotPathPhase.TRACE_SERIALIZATION,
        HotPathPhase.ENVIRONMENT_STEP,
        HotPathPhase.CONTROLLER_ORCHESTRATION,
        HotPathPhase.FINALIZE,
    ):
        assert cast(int, _profile_phase(profile, phase)["calls"]) > 0

    boundaries = cast(list[dict[str, JSONValue]], profile["boundaries"])
    assert cast(int, profile["boundary_count"]) == len(boundaries)
    assert [boundary["sequence"] for boundary in boundaries] == list(range(len(boundaries)))
    assert {
        "reset",
        "observe",
        "choose_action",
        "apply_consequence",
    }.issubset({cast(str, boundary["kind"]) for boundary in boundaries})
    actions = [cast(int, boundary["actions"]) for boundary in boundaries]
    assert actions == sorted(actions)
    assert all("phase_cumulative" in boundary for boundary in boundaries)

    cache_totals = cast(dict[str, JSONValue], profile["cache_totals"])
    assert cast(int, cache_totals["opportunity_misses"]) > 0
    assert cast(int, cache_totals["input_observations"]) > 0
