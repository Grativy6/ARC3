"""Diagnose ARC3 controller throughput with synthetic-only causal interventions.

The primary experiment is a matched 2x2 factorial design.  Every trial uses
the FULL controller mechanisms while varying only Python ``tracemalloc`` and
automatic checkpoint persistence.  Checkpoint suppression is an experimental
diagnostic made with ``dataclasses.replace(..., use_memory=False)``; it is not
treated as a production repair.  Public games, manifests, assets, and adapters
are deliberately outside this tool's input surface.
"""

from __future__ import annotations

import argparse
import cProfile
import os
import platform
import statistics
import subprocess
import sys
import time
import tracemalloc
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from types import CodeType
from typing import cast

from arc3.adapters.synthetic import SYNTHETIC_GAME_ID, SyntheticAdapter
from arc3.config import ARC3Config, BudgetConfig
from arc3.evaluation.artifacts import (
    atomic_write_json,
    canonical_json_bytes,
    seal_object,
    sha256_bytes,
    sha256_file,
)
from arc3.policy import (
    ActionDecision,
    ARC3Controller,
    CandidateAction,
    ControllerPhase,
    ControllerPreset,
    RunContext,
    preset_features,
)
from arc3.profiling import HotPathPhase, HotPathProfiler, process_memory_sample
from arc3.types import ActionRequest, EnvironmentMode, GameStateName, JSONValue

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SEED = 25
DEFAULT_REPETITIONS = 5
DEFAULT_ACTIONS = 8
DEFAULT_OUTPUT = ROOT / "artifacts" / "stage03" / "hot-path-diagnosis.json"
DEFAULT_WORK_ROOT = ROOT / "artifacts" / "stage03" / "hot-path-diagnosis-work"
_MICRO_MIN_ITERATIONS = 20
_CPROFILE_TOP_COUNT = 12


@dataclass(frozen=True, slots=True)
class _FactorSetting:
    tracemalloc_enabled: bool
    automatic_checkpointing_enabled: bool

    @property
    def key(self) -> str:
        tracing = "on" if self.tracemalloc_enabled else "off"
        checkpoints = "on" if self.automatic_checkpointing_enabled else "off"
        return f"tracemalloc={tracing}|automatic_checkpoints={checkpoints}"

    def to_dict(self) -> dict[str, object]:
        return {
            "automatic_checkpointing_enabled": self.automatic_checkpointing_enabled,
            "factor_key": self.key,
            "tracemalloc_enabled": self.tracemalloc_enabled,
        }


_GRAY_FACTOR_ORDER = (
    _FactorSetting(False, False),
    _FactorSetting(True, False),
    _FactorSetting(True, True),
    _FactorSetting(False, True),
)


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("value must be an integer") from error
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be positive")
    return parsed


def _factor_schedule(repetitions: int) -> tuple[tuple[_FactorSetting, ...], ...]:
    """Return rotated Gray-code orders, reversing complete four-blocks.

    Each repetition contains all four cells exactly once and consecutive cells
    change one factor.  Every complete block of four repetitions balances each
    cell across all four order positions; the next block reverses direction.
    """

    if isinstance(repetitions, bool) or not isinstance(repetitions, int) or repetitions <= 0:
        raise ValueError("repetitions must be a positive integer")
    schedules: list[tuple[_FactorSetting, ...]] = []
    for repetition in range(repetitions):
        block = repetition // len(_GRAY_FACTOR_ORDER)
        orientation = _GRAY_FACTOR_ORDER if block % 2 == 0 else tuple(reversed(_GRAY_FACTOR_ORDER))
        offset = repetition % len(orientation)
        schedules.append(orientation[offset:] + orientation[:offset])
    return tuple(schedules)


def _git_value(*arguments: str) -> str | None:
    try:
        completed: subprocess.CompletedProcess[str] = subprocess.run(
            ("git", *arguments),
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return completed.stdout.strip() if completed.returncode == 0 else None


def _package_version(name: str) -> str:
    try:
        return version(name)
    except PackageNotFoundError:
        return "not-installed"


def _source_identity() -> dict[str, object]:
    candidates: list[Path] = []
    for directory in (ROOT / "src" / "arc3", ROOT / "agent"):
        if directory.is_dir():
            candidates.extend(
                path
                for path in directory.rglob("*.py")
                if path.is_file() and "__pycache__" not in path.parts
            )
    for path in (
        ROOT / "scripts" / "diagnose_hot_path.py",
        ROOT / "pyproject.toml",
        ROOT / "uv.lock",
    ):
        if path.is_file():
            candidates.append(path)
    entries = [
        {"path": path.relative_to(ROOT).as_posix(), "sha256": sha256_file(path)}
        for path in sorted(set(candidates))
    ]
    worktree_status = _git_value("status", "--porcelain=v1")
    identity: dict[str, object] = {
        "branch": _git_value("branch", "--show-current"),
        "dirty_worktree": worktree_status is None or bool(worktree_status),
        "dirty_worktree_reason": "git status unavailable" if worktree_status is None else None,
        "first_party_source_file_count": len(entries),
        "first_party_source_hash": sha256_bytes(canonical_json_bytes(entries)),
        "git_commit": _git_value("rev-parse", "HEAD"),
        "worktree_status_hash": (
            None
            if worktree_status is None
            else sha256_bytes((worktree_status + "\n").encode("utf-8"))
        ),
    }
    return seal_object(identity, hash_field="identity_hash")


def _runtime_identity() -> dict[str, object]:
    memory = process_memory_sample()
    return {
        "logical_cpu_count": os.cpu_count(),
        "machine": platform.machine(),
        "memory_measurement_source": memory.get("measurement_source"),
        "packages": {
            "arc3": _package_version("arc3"),
            "numpy": _package_version("numpy"),
            "pydantic": _package_version("pydantic"),
        },
        "platform": platform.platform(),
        "processor": platform.processor() or None,
        "python": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "timers": {
            "cpu": "time.process_time_ns",
            "python_allocations": "tracemalloc",
            "rss": "host process RSS sampler",
            "wall": "time.perf_counter_ns",
        },
    }


def _action_payload(action: ActionRequest) -> dict[str, JSONValue]:
    coordinate = action.coordinate
    return {
        "coordinate": None if coordinate is None else {"x": coordinate.x, "y": coordinate.y},
        "name": action.name.value,
    }


def _decision_signature(decision: ActionDecision) -> dict[str, JSONValue]:
    """Capture exact policy output while excluding run-specific receipt IDs."""

    return {
        "action": _action_payload(decision.action),
        "active_goal_count": len(decision.active_goal_ids),
        "active_hypothesis_count": len(decision.active_hypothesis_ids),
        "active_world_model_count": len(decision.active_world_model_ids),
        "alternatives": [candidate.to_trace_payload() for candidate in decision.alternatives],
        "prediction_count": len(decision.prediction_ids),
        "rationale_category": decision.rationale_category.value,
        "rationale_summary": decision.rationale_summary,
        "selected_probe_or_plan": decision.selected_probe_or_plan_id is not None,
    }


def _candidate_signature(candidates: tuple[CandidateAction, ...]) -> list[JSONValue]:
    return [candidate.to_trace_payload() for candidate in candidates]


def _tree_metrics(root: Path) -> dict[str, object]:
    files = (
        tuple(sorted(path for path in root.rglob("*") if path.is_file())) if root.exists() else ()
    )
    return {
        "bytes": sum(path.stat().st_size for path in files),
        "file_count": len(files),
    }


def _checkpoint_metrics(root: Path) -> dict[str, object]:
    metrics = _tree_metrics(root)
    immutable = tuple(sorted(root.glob("checkpoint-*.json"))) if root.exists() else ()
    latest = root / "latest.json"
    metrics.update(
        {
            "immutable_checkpoint_bytes": sum(path.stat().st_size for path in immutable),
            "immutable_checkpoint_count": len(immutable),
            "latest_checkpoint_bytes": latest.stat().st_size if latest.is_file() else 0,
            "latest_checkpoint_present": latest.is_file(),
        }
    )
    return metrics


def _trace_metrics(root: Path, *, event_count: int) -> dict[str, object]:
    metrics = _tree_metrics(root)
    blob_root = root / "blobs"
    blob_files = (
        tuple(sorted(path for path in blob_root.rglob("*") if path.is_file()))
        if blob_root.exists()
        else ()
    )
    metrics.update(
        {
            "blob_bytes": sum(path.stat().st_size for path in blob_files),
            "blob_file_count": len(blob_files),
            "event_count": event_count,
        }
    )
    return metrics


def _rss_integer(sample: dict[str, JSONValue], key: str) -> int | None:
    value = sample.get(key)
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    return None


def _rss_report(before: dict[str, JSONValue], after: dict[str, JSONValue]) -> dict[str, object]:
    before_current = _rss_integer(before, "current_rss_bytes")
    after_current = _rss_integer(after, "current_rss_bytes")
    peaks = [
        value
        for value in (
            _rss_integer(before, "peak_rss_bytes"),
            _rss_integer(after, "peak_rss_bytes"),
        )
        if value is not None
    ]
    return {
        "after": after,
        "before": before,
        "current_delta_bytes": (
            None
            if before_current is None or after_current is None
            else after_current - before_current
        ),
        "process_peak_rss_bytes": max(peaks) if peaks else None,
        "scope": "whole-process; peak may include earlier serialized trials",
    }


def _phase_totals(profile: dict[str, JSONValue]) -> dict[str, object]:
    raw_phases = cast(dict[str, JSONValue], profile["phases"])
    totals: dict[str, object] = {}
    for name, raw in sorted(raw_phases.items()):
        phase = cast(dict[str, JSONValue], raw)
        totals[name] = {
            "calls": phase["calls"],
            "exclusive_cpu_ns": phase["exclusive_cpu_ns"],
            "exclusive_wall_ns": phase["exclusive_wall_ns"],
        }
    return totals


def _context(
    trial_root: Path,
    *,
    seed: int,
    actions: int,
    trial_index: int,
    factors: _FactorSetting,
    git_commit: str,
) -> RunContext:
    return RunContext(
        run_id=f"stage03-causal-{seed}-{trial_index:04d}",
        episode_id=f"stage03-causal-episode-{seed}-{trial_index:04d}",
        game_id=SYNTHETIC_GAME_ID,
        trace_root=trial_root / "trace",
        checkpoint_root=trial_root / "checkpoint",
        config=ARC3Config(
            mode=EnvironmentMode.SYNTHETIC,
            seed=seed,
            network_enabled=False,
            profile="build-001-stage03-causal-diagnosis",
            budgets=BudgetConfig(
                max_actions=actions,
                max_resets=max(1, actions),
                max_search_nodes=2_048,
            ),
        ),
        git_commit=git_commit,
        source_kind=f"build-001-stage03-{factors.key}",
        source_version="0.1",
    )


def _execute_controller_trial(
    trial_root: Path,
    *,
    seed: int,
    actions: int,
    trial_index: int,
    repetition: int,
    order_position: int,
    factors: _FactorSetting,
    git_commit: str,
) -> dict[str, object]:
    before_rss = process_memory_sample()
    profiler = HotPathProfiler(enabled=True)
    wall_started_ns = time.perf_counter_ns()
    cpu_started_ns = time.process_time_ns()
    features = preset_features(ControllerPreset.FULL)
    if not factors.automatic_checkpointing_enabled:
        features = replace(features, use_memory=False)

    with profiler.span(HotPathPhase.STARTUP):
        session = SyntheticAdapter(seed=seed, size=8, max_steps=actions).open(
            SYNTHETIC_GAME_ID,
            seed=seed,
        )
        controller = ARC3Controller(
            ControllerPreset.FULL,
            features=features,
            hot_path_profiler=profiler,
        )
        context = _context(
            trial_root,
            seed=seed,
            actions=actions,
            trial_index=trial_index,
            factors=factors,
            git_commit=git_commit,
        )
        controller.reset(context)

    controller.observe(session.observation)
    decisions: list[dict[str, JSONValue]] = []
    while len(decisions) < actions and controller.phase not in {
        ControllerPhase.COMPLETE,
        ControllerPhase.GAME_OVER,
    }:
        decision = controller.choose_action()
        decisions.append(_decision_signature(decision))
        with profiler.span(HotPathPhase.ENVIRONMENT_STEP):
            consequence = session.step(decision.action)
        controller.apply_consequence(consequence)

    before_close_snapshot = controller.snapshot
    final_observation = session.observation
    with profiler.span(HotPathPhase.FINALIZE):
        controller.close()
        scorecard = session.close()

    profile = profiler.summary()
    cpu_elapsed_ns = max(0, time.process_time_ns() - cpu_started_ns)
    wall_elapsed_ns = max(0, time.perf_counter_ns() - wall_started_ns)
    after_rss = process_memory_sample()
    allocation_current: int | None = None
    allocation_peak: int | None = None
    if factors.tracemalloc_enabled:
        allocation_current, allocation_peak = tracemalloc.get_traced_memory()
    trace_event_count = controller.journal.event_count
    outcome_signature: dict[str, object] = {
        "completed": final_observation.state is GameStateName.WIN,
        "controller_action_count": before_close_snapshot.actions_used,
        "controller_fault_count": before_close_snapshot.fault_count,
        "controller_reset_count": before_close_snapshot.resets_used,
        "decision_count": len(decisions),
        "environment_action_count": scorecard.total_actions,
        "environment_reset_count": scorecard.total_resets,
        "final_state": final_observation.state.value,
        "levels_completed": final_observation.levels_completed,
        "score": scorecard.score,
    }
    return {
        "checkpoint_metrics": _checkpoint_metrics(context.checkpoint_root),
        "cpu_ns": cpu_elapsed_ns,
        "decision_signature": decisions,
        "decision_signature_hash": sha256_bytes(canonical_json_bytes(decisions)),
        "factors": factors.to_dict(),
        "hot_path_profile": profile,
        "order_position": order_position,
        "outcome_signature": outcome_signature,
        "outcome_signature_hash": sha256_bytes(canonical_json_bytes(outcome_signature)),
        "phase_totals": _phase_totals(profile),
        "python_allocation_current_bytes": allocation_current,
        "python_allocation_peak_bytes": allocation_peak,
        "repetition": repetition,
        "rss": _rss_report(before_rss, after_rss),
        "seed": seed,
        "trace_metrics": _trace_metrics(context.trace_root, event_count=trace_event_count),
        "trial_index": trial_index,
        "wall_ns": wall_elapsed_ns,
        "wall_ns_per_environment_action": (
            None
            if scorecard.total_actions <= 0
            else round(wall_elapsed_ns / scorecard.total_actions, 9)
        ),
    }


def _run_controller_trial(
    trial_root: Path,
    *,
    seed: int,
    actions: int,
    trial_index: int,
    repetition: int,
    order_position: int,
    factors: _FactorSetting,
    git_commit: str,
) -> dict[str, object]:
    if tracemalloc.is_tracing():
        raise RuntimeError("diagnosis requires exclusive ownership of process tracemalloc state")
    started_tracer = False
    try:
        if factors.tracemalloc_enabled:
            tracemalloc.start()
            started_tracer = True
        return _execute_controller_trial(
            trial_root,
            seed=seed,
            actions=actions,
            trial_index=trial_index,
            repetition=repetition,
            order_position=order_position,
            factors=factors,
            git_commit=git_commit,
        )
    finally:
        if started_tracer and tracemalloc.is_tracing():
            tracemalloc.stop()


def _median(values: list[int | float]) -> float:
    if not values:
        raise ValueError("cannot take the median of an empty sample")
    return float(statistics.median(values))


def _ratio(numerator: float, denominator: float) -> float | None:
    if denominator <= 0.0:
        return None
    return round(numerator / denominator, 12)


def _factorial_metric(trials: list[dict[str, object]], metric: str) -> dict[str, object]:
    cells: dict[tuple[bool, bool], list[float]] = {
        (False, False): [],
        (True, False): [],
        (True, True): [],
        (False, True): [],
    }
    for trial in trials:
        factors = cast(dict[str, object], trial["factors"])
        tracing = cast(bool, factors["tracemalloc_enabled"])
        checkpoints = cast(bool, factors["automatic_checkpointing_enabled"])
        value = trial[metric]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"trial metric {metric!r} is not numeric")
        cells[(tracing, checkpoints)].append(float(value))
    if any(not values for values in cells.values()):
        raise ValueError("factorial comparison requires every 2x2 cell")

    medians = {cell: _median(values) for cell, values in cells.items()}
    off_off = medians[(False, False)]
    trace_on = medians[(True, False)]
    both_on = medians[(True, True)]
    checkpoint_on = medians[(False, True)]
    pooled_trace_off = _median(cells[(False, False)] + cells[(False, True)])
    pooled_trace_on = _median(cells[(True, False)] + cells[(True, True)])
    pooled_checkpoint_off = _median(cells[(False, False)] + cells[(True, False)])
    pooled_checkpoint_on = _median(cells[(False, True)] + cells[(True, True)])
    checkpoint_effect_no_trace = checkpoint_on - off_off
    checkpoint_effect_with_trace = both_on - trace_on
    return {
        "cell_medians": {
            _FactorSetting(tracing, checkpoints).key: medians[(tracing, checkpoints)]
            for tracing, checkpoints in cells
        },
        "checkpoint_effect_by_tracemalloc": {
            "tracemalloc_disabled_delta": checkpoint_effect_no_trace,
            "tracemalloc_disabled_ratio": _ratio(checkpoint_on, off_off),
            "tracemalloc_enabled_delta": checkpoint_effect_with_trace,
            "tracemalloc_enabled_ratio": _ratio(both_on, trace_on),
        },
        "checkpoint_marginal_delta": pooled_checkpoint_on - pooled_checkpoint_off,
        "checkpoint_marginal_ratio": _ratio(pooled_checkpoint_on, pooled_checkpoint_off),
        "interaction": {
            "additive_difference_of_differences": (
                checkpoint_effect_with_trace - checkpoint_effect_no_trace
            ),
            "multiplicative_cross_ratio": (
                None
                if trace_on <= 0.0 or checkpoint_on <= 0.0
                else _ratio(both_on * off_off, trace_on * checkpoint_on)
            ),
        },
        "sample_count_per_cell": {
            _FactorSetting(tracing, checkpoints).key: len(values)
            for (tracing, checkpoints), values in cells.items()
        },
        "tracemalloc_effect_by_checkpoint": {
            "checkpoints_disabled_delta": trace_on - off_off,
            "checkpoints_disabled_ratio": _ratio(trace_on, off_off),
            "checkpoints_enabled_delta": both_on - checkpoint_on,
            "checkpoints_enabled_ratio": _ratio(both_on, checkpoint_on),
        },
        "tracemalloc_marginal_delta": pooled_trace_on - pooled_trace_off,
        "tracemalloc_marginal_ratio": _ratio(pooled_trace_on, pooled_trace_off),
    }


def _factorial_metrics(trials: list[dict[str, object]]) -> dict[str, object]:
    return {
        metric: _factorial_metric(trials, metric)
        for metric in ("wall_ns", "cpu_ns", "wall_ns_per_environment_action")
    }


def _controller_read_only_signature(controller: ARC3Controller) -> dict[str, object]:
    snapshot = controller.snapshot
    pending = snapshot.pending_action
    statistics = controller._exploration.statistics
    exploration_state_hash = sha256_bytes(
        repr(
            (
                dict(statistics._counts),
                dict(statistics._observations),
                statistics._undo_successes,
                dict(controller._exploration.ineffective._counts),
            )
        ).encode("utf-8")
    )
    action_counts = tuple(
        sorted(
            (
                action.name.value,
                None if action.coordinate is None else (action.coordinate.x, action.coordinate.y),
                count,
            )
            for action, count in controller._action_counts.items()
        )
    )
    return {
        "action_counts": action_counts,
        "event_count": controller.journal.event_count,
        "exploration_state_hash": exploration_state_hash,
        "explored_coordinates": sorted(
            (coordinate.x, coordinate.y) for coordinate in controller._explored_coordinates
        ),
        "journal_tail_hash": controller.journal.tail_hash,
        "pending_action": None if pending is None else _action_payload(pending),
        "rng_state_hash": sha256_bytes(repr(controller._rng.getstate()).encode("utf-8")),
        "snapshot": {
            "actions_used": snapshot.actions_used,
            "active_goal_ids": list(snapshot.active_goal_ids),
            "active_hypothesis_ids": list(snapshot.active_hypothesis_ids),
            "active_world_model_ids": list(snapshot.active_world_model_ids),
            "fault_count": snapshot.fault_count,
            "level_index": snapshot.level_index,
            "phase": snapshot.phase.value,
            "resets_used": snapshot.resets_used,
            "step_index": snapshot.step_index,
            "trace_events": snapshot.trace_events,
        },
    }


def _profile_function_name(filename: str, line: int, function: str) -> str:
    if filename.startswith("{"):
        normalized = filename
    else:
        path = Path(filename)
        try:
            normalized = path.resolve().relative_to(ROOT).as_posix()
        except (OSError, ValueError):
            normalized = path.name
    return f"{normalized}:{line}:{function}"


def _cprofile_rows(profile: cProfile.Profile) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for entry in profile.getstats():
        code = entry.code
        function = (
            _profile_function_name(code.co_filename, code.co_firstlineno, code.co_name)
            if isinstance(code, CodeType)
            else str(code)
        )
        rows.append(
            {
                "cumulative_seconds": entry.totaltime,
                "function": function,
                "primitive_calls": entry.callcount - entry.reccallcount,
                "self_seconds": entry.inlinetime,
                "total_calls": entry.callcount,
            }
        )
    return sorted(
        rows,
        key=lambda row: (
            -cast(float, row["cumulative_seconds"]),
            cast(str, row["function"]),
        ),
    )


def _micro_fixture_seed(seed: int, *, size: int = 8) -> int:
    """Select the first derived seed whose endpoints cannot meet in one step."""

    for offset in range(256):
        unsigned = (seed % (2**64) + offset) % (2**64)
        candidate = unsigned if unsigned < 2**63 else unsigned - 2**64
        start = (unsigned % size, (unsigned // size) % size)
        target = ((unsigned * 3 + 1) % size, (unsigned * 5 + 2) % size)
        if target == start:
            target = ((target[0] + 1) % size, target[1])
        distance = abs(start[0] - target[0]) + abs(start[1] - target[1])
        if distance >= 3:
            return candidate
    raise RuntimeError("could not derive a nonterminal one-step synthetic microbenchmark seed")


def _micro_context(root: Path, *, seed: int, repetition: int, tracing: bool) -> RunContext:
    label = f"micro-{repetition:03d}-{'trace' if tracing else 'plain'}"
    return RunContext(
        run_id=f"stage03-{label}",
        episode_id=f"stage03-{label}-episode",
        game_id=SYNTHETIC_GAME_ID,
        trace_root=root / "trace",
        checkpoint_root=root / "checkpoint",
        config=ARC3Config(
            mode=EnvironmentMode.SYNTHETIC,
            seed=seed,
            network_enabled=False,
            profile="build-001-stage03-action-selection-microbenchmark",
            budgets=BudgetConfig(max_actions=64, max_resets=8, max_search_nodes=2_048),
        ),
        git_commit=_git_value("rev-parse", "HEAD") or "unavailable-git-identity",
        source_kind="build-001-stage03-read-only-candidate-generation",
        source_version="0.1",
    )


def _run_action_selection_micro_trial(
    root: Path,
    *,
    seed: int,
    repetition: int,
    tracing: bool,
    iterations: int,
) -> dict[str, object]:
    if tracemalloc.is_tracing():
        raise RuntimeError("microbenchmark requires exclusive process tracemalloc state")
    fixture_seed = _micro_fixture_seed(seed)
    features = replace(preset_features(ControllerPreset.FULL), use_memory=False)
    session = SyntheticAdapter(seed=fixture_seed, size=8, max_steps=64).open(SYNTHETIC_GAME_ID)
    controller = ARC3Controller(ControllerPreset.FULL, features=features)
    controller.reset(
        _micro_context(root, seed=fixture_seed, repetition=repetition, tracing=tracing)
    )
    controller.observe(session.observation)
    setup_decision = controller.choose_action()
    setup_consequence = session.step(setup_decision.action)
    controller.apply_consequence(setup_consequence)
    setup_snapshot = controller.snapshot
    if controller.phase is not ControllerPhase.OBSERVED:
        raise RuntimeError("microbenchmark setup did not reach a nonterminal observed state")
    if not setup_snapshot.active_world_model_ids:
        raise RuntimeError("microbenchmark setup did not compile an active world-model ensemble")
    observation = controller._latest_observation
    view = controller._latest_view
    if observation is None or view is None:
        raise RuntimeError("synthetic controller did not produce a perception view")
    # ActionEffectStatistics intentionally materializes absent defaultdict
    # keys during its first estimate.  Keep that one setup call outside both
    # the measured region and the invariant boundary.  Every timed/profiled
    # call below then runs on the same already-materialized policy state.
    reference = _candidate_signature(controller._candidate_actions(observation, view))
    state_before = _controller_read_only_signature(controller)
    started_tracer = False
    try:
        if tracing:
            tracemalloc.start()
            started_tracer = True
        wall_started_ns = time.perf_counter_ns()
        cpu_started_ns = time.process_time_ns()
        timed_outputs = [
            _candidate_signature(controller._candidate_actions(observation, view))
            for _ in range(iterations)
        ]
        timing_cpu_ns = max(0, time.process_time_ns() - cpu_started_ns)
        timing_wall_ns = max(0, time.perf_counter_ns() - wall_started_ns)

        profiler = cProfile.Profile()
        profiler.enable()
        profiled_outputs = [
            _candidate_signature(controller._candidate_actions(observation, view))
            for _ in range(iterations)
        ]
        profiler.disable()
        allocation_current: int | None = None
        allocation_peak: int | None = None
        if tracing:
            allocation_current, allocation_peak = tracemalloc.get_traced_memory()
    finally:
        if started_tracer and tracemalloc.is_tracing():
            tracemalloc.stop()

    state_after = _controller_read_only_signature(controller)
    profile_rows = _cprofile_rows(profiler)
    prediction_rows = [
        row for row in profile_rows if "predict" in cast(str, row["function"]).casefold()
    ]
    state_identity_rows = [
        row for row in profile_rows if "state_id" in cast(str, row["function"]).casefold()
    ]
    controller.close()
    session.close()
    outputs_unchanged = all(output == reference for output in (*timed_outputs, *profiled_outputs))
    return {
        "automatic_checkpointing_enabled": False,
        "candidate_signature": reference,
        "candidate_signature_hash": sha256_bytes(canonical_json_bytes(reference)),
        "cprofile_iterations": iterations,
        "cprofile_prediction_rows": prediction_rows,
        "cprofile_state_identity_rows": state_identity_rows,
        "cprofile_top_by_cumulative_time": profile_rows[:_CPROFILE_TOP_COUNT],
        "experimental_boundary": (
            "read-only calls to private candidate generation; choose_action is not bypassed in "
            "any production or episode trial"
        ),
        "iterations": iterations,
        "method": "ARC3Controller._candidate_actions on one unchanged observed synthetic state",
        "outputs_unchanged": outputs_unchanged,
        "policy_state_unchanged": state_before == state_after,
        "python_allocation_current_bytes": allocation_current,
        "python_allocation_peak_bytes": allocation_peak,
        "repetition": repetition,
        "requested_seed": seed,
        "setup_action": _action_payload(setup_decision.action),
        "setup_actions": setup_snapshot.actions_used,
        "setup_active_goal_count": len(setup_snapshot.active_goal_ids),
        "setup_active_hypothesis_count": len(setup_snapshot.active_hypothesis_ids),
        "setup_active_world_model_count": len(setup_snapshot.active_world_model_ids),
        "setup_candidate_count": len(reference),
        "setup_consequence_state": setup_consequence.state.value,
        "setup_fixture_seed": fixture_seed,
        "setup_prediction_count": len(setup_decision.prediction_ids),
        "timing_cpu_ns": timing_cpu_ns,
        "timing_wall_ns": timing_wall_ns,
        "timing_wall_ns_per_call": round(timing_wall_ns / iterations, 9),
        "tracemalloc_enabled": tracing,
        "untimed_lazy_index_warmup_calls": 1,
    }


def _action_selection_microbenchmark(
    root: Path,
    *,
    seed: int,
    repetitions: int,
    actions: int,
) -> dict[str, object]:
    iterations = max(_MICRO_MIN_ITERATIONS, actions * 4)
    trials: list[dict[str, object]] = []
    for repetition in range(repetitions):
        order = (False, True) if repetition % 2 == 0 else (True, False)
        for tracing in order:
            trials.append(
                _run_action_selection_micro_trial(
                    root / f"trial-{len(trials):04d}",
                    seed=seed,
                    repetition=repetition,
                    tracing=tracing,
                    iterations=iterations,
                )
            )
    disabled = [trial for trial in trials if trial["tracemalloc_enabled"] is False]
    enabled = [trial for trial in trials if trial["tracemalloc_enabled"] is True]
    disabled_wall = _median([cast(int, trial["timing_wall_ns_per_call"]) for trial in disabled])
    enabled_wall = _median([cast(int, trial["timing_wall_ns_per_call"]) for trial in enabled])
    signatures_match = len({cast(str, trial["candidate_signature_hash"]) for trial in trials}) == 1
    state_unchanged = all(trial["policy_state_unchanged"] is True for trial in trials)
    outputs_unchanged = all(trial["outputs_unchanged"] is True for trial in trials)
    active_ensemble_sampled = all(
        cast(int, trial["setup_active_world_model_count"]) > 0 for trial in trials
    )
    diagnostic_rows_present = all(
        bool(trial["cprofile_prediction_rows"]) and bool(trial["cprofile_state_identity_rows"])
        for trial in trials
    )
    return {
        "comparison": {
            "active_ensemble_sampled_every_trial": active_ensemble_sampled,
            "prediction_and_state_identity_rows_present_every_trial": diagnostic_rows_present,
            "disabled_median_wall_ns_per_call": disabled_wall,
            "enabled_median_wall_ns_per_call": enabled_wall,
            "exact_candidate_signatures_match": signatures_match,
            "method_outputs_unchanged": outputs_unchanged,
            "policy_state_unchanged": state_unchanged,
            "tracemalloc_delta_wall_ns_per_call": enabled_wall - disabled_wall,
            "tracemalloc_ratio_wall_ns_per_call": _ratio(enabled_wall, disabled_wall),
        },
        "interpretation_boundary": (
            "isolated diagnostic only; it measures read-only candidate generation and does not "
            "authorize bypassing choose_action, receipts, validation, or checkpointing"
        ),
        "iterations_per_timing_pass": iterations,
        "schema": "arc3.hot-path-action-selection-microbenchmark.v0.1",
        "status": (
            "PASS"
            if signatures_match
            and state_unchanged
            and outputs_unchanged
            and active_ensemble_sampled
            and diagnostic_rows_present
            else "FAILED_MECHANISM"
        ),
        "trials": trials,
    }


def diagnose_hot_path(
    *,
    seed: int,
    repetitions: int,
    actions: int,
    work_root: Path,
) -> dict[str, object]:
    """Run the synthetic factorial and return a canonical self-hashed report."""

    if isinstance(seed, bool) or not isinstance(seed, int) or not -(2**63) <= seed < 2**63:
        raise ValueError("seed must be a signed 64-bit integer")
    if isinstance(actions, bool) or not isinstance(actions, int) or actions <= 0:
        raise ValueError("actions must be a positive integer")
    schedule = _factor_schedule(repetitions)
    if work_root.exists():
        if not work_root.is_dir():
            raise ValueError(f"work root is not a directory: {work_root}")
        if any(work_root.iterdir()):
            raise ValueError(f"work root already contains data: {work_root}")
    work_root.mkdir(parents=True, exist_ok=True)

    started_at = _utc_now()
    source_identity = _source_identity()
    git_value = source_identity.get("git_commit")
    git_commit = (
        git_value if isinstance(git_value, str) and git_value else "unavailable-git-identity"
    )
    trials: list[dict[str, object]] = []
    for repetition, order in enumerate(schedule):
        for order_position, factors in enumerate(order):
            trial_index = len(trials)
            trials.append(
                _run_controller_trial(
                    work_root / "factorial" / f"trial-{trial_index:04d}",
                    seed=seed,
                    actions=actions,
                    trial_index=trial_index,
                    repetition=repetition,
                    order_position=order_position,
                    factors=factors,
                    git_commit=git_commit,
                )
            )

    reference_decisions = trials[0]["decision_signature"]
    reference_outcome = trials[0]["outcome_signature"]
    decisions_match = all(trial["decision_signature"] == reference_decisions for trial in trials)
    outcomes_match = all(trial["outcome_signature"] == reference_outcome for trial in trials)
    profiles_enabled = all(
        cast(dict[str, JSONValue], trial["hot_path_profile"])["enabled"] is True for trial in trials
    )
    microbenchmark = _action_selection_microbenchmark(
        work_root / "action-selection-microbenchmark",
        seed=seed,
        repetitions=repetitions,
        actions=actions,
    )
    status = (
        "PASS"
        if decisions_match
        and outcomes_match
        and profiles_enabled
        and microbenchmark["status"] == "PASS"
        else "FAILED_MECHANISM"
    )
    report: dict[str, object] = {
        "completed_at": _utc_now(),
        "configuration": {
            "action_budget": actions,
            "automatic_checkpointing_intervention": (
                "replace(preset_features(ControllerPreset.FULL), use_memory=False)"
            ),
            "factor_order": [
                [setting.to_dict() for setting in repetition_order] for repetition_order in schedule
            ],
            "game_id": SYNTHETIC_GAME_ID,
            "grid_size": 8,
            "hot_path_profile_enabled_every_trial": True,
            "max_steps": actions,
            "network_enabled": False,
            "preset": ControllerPreset.FULL.value,
            "repetitions_per_factor_cell": repetitions,
            "seed": seed,
            "total_factorial_trials": len(trials),
        },
        "controls": {
            "exact_action_decision_signatures_match": decisions_match,
            "exact_environment_outcomes_match": outcomes_match,
            "hot_path_profile_enabled_every_trial": profiles_enabled,
            "reference_decision_signature_hash": trials[0]["decision_signature_hash"],
            "reference_outcome_signature_hash": trials[0]["outcome_signature_hash"],
        },
        "evidence_label": "synthetic",
        "factorial_effects": _factorial_metrics(trials),
        "limitations": [
            "This is synthetic causal diagnosis and makes no public-game or generalization claim.",
            "Process tracemalloc is global, so all trials are serialized and require exclusive tracer ownership.",
            "Disabling use_memory is an experimental automatic-checkpoint intervention, not a production recommendation.",
            "Whole-process peak RSS can include earlier trials; current RSS deltas and Python allocation peaks are also retained.",
            "The action-selection microbenchmark calls a read-only private method only after asserting policy-state identity.",
            "Wall and CPU timing vary with host load; exact seeded decisions and outcomes are deterministic controls.",
            "No public-game or holdout manifest, asset, adapter, source, or episode is accessed.",
        ],
        "microbenchmark": microbenchmark,
        "runtime": _runtime_identity(),
        "schema": "arc3.hot-path-causal-diagnosis.v0.1",
        "source_identity": source_identity,
        "started_at": started_at,
        "status": status,
        "trials": trials,
        "work_root": str(work_root.resolve()),
    }
    return seal_object(report, hash_field="artifact_core_hash")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--repetitions", type=_positive_int, default=DEFAULT_REPETITIONS)
    parser.add_argument("--actions", type=_positive_int, default=DEFAULT_ACTIONS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--work-root", type=Path, default=DEFAULT_WORK_ROOT)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    report = diagnose_hot_path(
        seed=args.seed,
        repetitions=args.repetitions,
        actions=args.actions,
        work_root=args.work_root,
    )
    atomic_write_json(args.output, report)
    sys.stdout.write(canonical_json_bytes(report).decode("utf-8"))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
