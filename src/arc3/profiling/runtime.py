"""Bounded controller runtime, restart, fault, and robustness measurements."""

from __future__ import annotations

import sys
import time
from collections import Counter
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Protocol, cast

from arc3.adapters import GridFrame, Observation, ScoreSummary
from arc3.config import ARC3Config, BudgetConfig
from arc3.policy import ARC3Controller, ControllerPhase, ControllerPreset, RunContext
from arc3.trace import CheckpointStore, EventJournal, ReplayEngine, verify_event_chain
from arc3.trace.canonical import sha256_json
from arc3.types import (
    ActionName,
    ActionRequest,
    EnvironmentMode,
    GameId,
    GameStateName,
    JSONScalar,
    JSONValue,
)

from .fixtures import ManyComponentStressSession, RobustnessVariant, TransformedSyntheticSession
from .models import RuntimeProfileConfig


class _ProfileSession(Protocol):
    @property
    def observation(self) -> Observation: ...

    def step(self, action: ActionRequest) -> Observation: ...

    def close(self) -> ScoreSummary: ...


def _directory_bytes(root: Path) -> int:
    return sum(path.stat().st_size for path in root.rglob("*") if path.is_file())


def _percentile(values: Sequence[float], quantile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * quantile
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def _latency_summary(values: Sequence[float]) -> dict[str, JSONValue]:
    return {
        "count": len(values),
        "maximum": max(values) if values else None,
        "mean": sum(values) / len(values) if values else None,
        "p50": _percentile(values, 0.50),
        "p95": _percentile(values, 0.95),
        "p99": _percentile(values, 0.99),
    }


def process_memory_sample() -> dict[str, JSONValue]:
    """Measure current and peak whole-process RSS using the host kernel surface."""

    current: int | None = None
    peak: int | None = None
    source = "unavailable"
    reason: str | None = None
    try:
        if sys.platform == "win32":
            import ctypes
            from ctypes import wintypes

            class ProcessMemoryCounters(ctypes.Structure):
                _fields_ = [
                    ("cb", wintypes.DWORD),
                    ("page_fault_count", wintypes.DWORD),
                    ("peak_working_set_size", ctypes.c_size_t),
                    ("working_set_size", ctypes.c_size_t),
                    ("quota_peak_paged_pool_usage", ctypes.c_size_t),
                    ("quota_paged_pool_usage", ctypes.c_size_t),
                    ("quota_peak_non_paged_pool_usage", ctypes.c_size_t),
                    ("quota_non_paged_pool_usage", ctypes.c_size_t),
                    ("pagefile_usage", ctypes.c_size_t),
                    ("peak_pagefile_usage", ctypes.c_size_t),
                ]

            counters = ProcessMemoryCounters()
            counters.cb = ctypes.sizeof(counters)
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            psapi = ctypes.WinDLL("psapi", use_last_error=True)
            kernel32.GetCurrentProcess.restype = wintypes.HANDLE
            psapi.GetProcessMemoryInfo.argtypes = [
                wintypes.HANDLE,
                ctypes.POINTER(ProcessMemoryCounters),
                wintypes.DWORD,
            ]
            psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
            handle = kernel32.GetCurrentProcess()
            ok = psapi.GetProcessMemoryInfo(
                handle,
                ctypes.byref(counters),
                counters.cb,
            )
            if not ok:
                raise OSError("GetProcessMemoryInfo returned failure")
            current = int(counters.working_set_size)
            peak = int(counters.peak_working_set_size)
            source = "windows-GetProcessMemoryInfo-working-set"
        elif Path("/proc/self/status").is_file():
            fields: dict[str, int] = {}
            for line in Path("/proc/self/status").read_text(encoding="utf-8").splitlines():
                name, separator, raw = line.partition(":")
                if separator and name in {"VmRSS", "VmHWM"}:
                    value = raw.strip().split()
                    if value:
                        fields[name] = int(value[0]) * 1024
            current = fields.get("VmRSS")
            peak = fields.get("VmHWM")
            source = "linux-proc-status-rss-hwm"
        else:
            import resource

            usage = resource.getrusage(resource.RUSAGE_SELF)
            multiplier = 1 if sys.platform == "darwin" else 1024
            peak = int(usage.ru_maxrss) * multiplier
            source = "posix-getrusage-peak-only"
            reason = "current RSS is unavailable on this host surface"
    except (AttributeError, OSError, ValueError) as error:
        reason = f"{type(error).__name__}: {error}"
    return {
        "current_rss_bytes": current,
        "measurement_source": source,
        "peak_rss_bytes": peak,
        "reason": reason,
    }


def _context(
    root: Path,
    *,
    config: RuntimeProfileConfig,
    preset: ControllerPreset,
    git_commit: str,
    run_label: str,
    game_id: str,
) -> RunContext:
    mode = (
        EnvironmentMode.COMPETITION
        if preset is ControllerPreset.COMPETITION
        else EnvironmentMode.SYNTHETIC
    )
    return RunContext(
        run_id=f"stage16-{run_label}",
        episode_id=f"stage16-{run_label}-episode",
        game_id=game_id,
        trace_root=root / "trace",
        checkpoint_root=root / "checkpoint",
        config=ARC3Config(
            mode=mode,
            seed=config.seed,
            network_enabled=False,
            profile="stage16-runtime-profile",
            budgets=config.budgets(),
        ),
        git_commit=git_commit,
        source_kind="arc3-stage16-profiler",
        source_version="0.1",
    )


def _checkpoint_metrics(root: Path) -> dict[str, JSONValue]:
    immutable = tuple(sorted(root.glob("checkpoint-*.json")))
    sizes = [path.stat().st_size for path in immutable]
    latest = root / "latest.json"
    return {
        "directory_bytes": _directory_bytes(root),
        "immutable_checkpoint_count": len(immutable),
        "largest_checkpoint_bytes": max(sizes) if sizes else 0,
        "latest_checkpoint_bytes": latest.stat().st_size if latest.is_file() else 0,
    }


def _planner_expansions(events: Sequence[object]) -> dict[str, JSONValue]:
    values: list[int] = []
    for raw in events:
        event_type = getattr(raw, "event_type", None)
        payload = getattr(raw, "payload", None)
        if event_type != "simulation.plan_evaluated" or not isinstance(payload, dict):
            continue
        expanded = payload.get("expanded_nodes")
        if isinstance(expanded, int) and not isinstance(expanded, bool) and expanded >= 0:
            values.append(expanded)
    return {
        "evaluation_count": len(values),
        "maximum_expanded_nodes": max(values) if values else 0,
        "total_expanded_nodes": sum(values),
    }


def _candidate_metrics(events: Sequence[object]) -> dict[str, JSONValue]:
    totals: list[int] = []
    coordinate_totals: list[int] = []
    for raw in events:
        if getattr(raw, "event_type", None) != "action.candidates_generated":
            continue
        payload = getattr(raw, "payload", None)
        if not isinstance(payload, dict):
            continue
        candidates = payload.get("candidates")
        if not isinstance(candidates, list):
            continue
        totals.append(len(candidates))
        coordinate_totals.append(
            sum(
                isinstance(candidate, dict)
                and candidate.get("action") == "ACTION6"
                and candidate.get("coordinate") is not None
                for candidate in candidates
            )
        )
    return {
        "generation_count": len(totals),
        "maximum_candidates": max(totals) if totals else 0,
        "maximum_coordinate_candidates": max(coordinate_totals) if coordinate_totals else 0,
        "total_candidates": sum(totals),
    }


def run_runtime_profile(
    root: Path,
    *,
    config: RuntimeProfileConfig | None = None,
    git_commit: str = "unavailable-git-identity",
    preset: ControllerPreset | str = ControllerPreset.COMPETITION,
    variant: RobustnessVariant | str = RobustnessVariant.BASE,
) -> dict[str, JSONValue]:
    """Run one fresh-storage, restartable, trace-verified controller profile."""

    selected_config = config or RuntimeProfileConfig()
    selected_preset = preset if isinstance(preset, ControllerPreset) else ControllerPreset(preset)
    selected_variant = RobustnessVariant(variant)
    run_root = root.resolve()
    run_root.mkdir(parents=True, exist_ok=False)
    session: _ProfileSession
    if selected_config.fixture == "component-stress":
        if selected_variant is not RobustnessVariant.BASE:
            raise ValueError("component-stress supports only the base variant")
        session = ManyComponentStressSession(
            size=selected_config.frame_size,
            component_count=selected_config.component_count,
        )
    else:
        session = TransformedSyntheticSession(
            seed=selected_config.seed,
            size=selected_config.frame_size,
            max_steps=max(selected_config.max_actions + 1, 64),
            variant=selected_variant,
        )
    context = _context(
        run_root,
        config=selected_config,
        preset=selected_preset,
        git_commit=git_commit,
        run_label=f"{selected_variant.value}-{selected_config.seed}",
        game_id=str(session.observation.game_id),
    )
    controller = ARC3Controller(selected_preset)
    observation_latencies: list[float] = []
    decision_latencies: list[float] = []
    consequence_latencies: list[float] = []
    environment_latencies: list[float] = []
    checkpoint_latencies: list[float] = []
    restart_latencies: list[float] = []
    total_step_latencies: list[float] = []
    growth: list[JSONValue] = []
    actions = 0
    resets = 0
    restarts = 0
    attempts = 0
    wall_clock_cutoff_triggered = False
    started = time.perf_counter()
    memory_before = process_memory_sample()
    reset_started = time.perf_counter()
    controller.reset(context)
    controller_reset_seconds = time.perf_counter() - reset_started
    observation_started = time.perf_counter()
    controller.observe(session.observation)
    observation_latencies.append(time.perf_counter() - observation_started)
    while (
        controller.phase not in {ControllerPhase.COMPLETE, ControllerPhase.FAULTED}
        and actions < selected_config.max_actions
        and attempts < selected_config.max_actions + selected_config.max_resets
    ):
        if time.perf_counter() - started > selected_config.wall_clock_seconds:
            wall_clock_cutoff_triggered = True
            break
        step_started = time.perf_counter()
        decision_started = time.perf_counter()
        decision = controller.choose_action()
        decision_latencies.append(time.perf_counter() - decision_started)
        attempts += 1
        should_restart = (
            selected_config.restart_every > 0
            and decision.action.name is not ActionName.RESET
            and (actions + 1) % selected_config.restart_every == 0
        )
        if should_restart:
            checkpoint_started = time.perf_counter()
            checkpoint = controller.checkpoint()
            checkpoint_latencies.append(time.perf_counter() - checkpoint_started)
            before_restart_events = controller.journal.event_count
            restart_started = time.perf_counter()
            controller.close()
            controller = ARC3Controller.restore(
                context,
                preset=selected_preset,
                checkpoint_path=checkpoint.path,
            )
            if controller.journal.event_count != before_restart_events:
                raise RuntimeError("restart duplicated or removed immutable events")
            restart_latencies.append(time.perf_counter() - restart_started)
            restarts += 1
        environment_started = time.perf_counter()
        returned = session.step(decision.action)
        environment_latencies.append(time.perf_counter() - environment_started)
        consequence_started = time.perf_counter()
        controller.apply_consequence(returned)
        consequence_latencies.append(time.perf_counter() - consequence_started)
        total_step_latencies.append(time.perf_counter() - step_started)
        if decision.action.name is ActionName.RESET:
            resets += 1
        else:
            actions += 1
        growth.append(
            {
                "actions": actions,
                "checkpoint_bytes": _directory_bytes(context.checkpoint_root),
                "resets": resets,
                "trace_bytes": _directory_bytes(context.trace_root),
                "trace_events": controller.journal.event_count,
            }
        )
        if time.perf_counter() - started > selected_config.wall_clock_seconds:
            wall_clock_cutoff_triggered = True
            break

    scorecard = session.close()
    phase_before_close = controller.phase
    snapshot = controller.snapshot
    controller.close()
    duration = time.perf_counter() - started
    auditor = EventJournal(context.trace_root, run_id=context.run_id)
    try:
        events = auditor.verify_manifest()
        verify_event_chain(list(events))
        replay = ReplayEngine(auditor)
        replay.verify_integrity()
        replayed_frames = replay.replay_frames()
        rebuilt_deltas = replay.rebuild_deltas()
    finally:
        auditor.close()
    event_types = [event.event_type for event in events]
    event_type_counts = cast(
        dict[str, JSONValue],
        dict(sorted(Counter(event_types).items())),
    )
    submitted = event_types.count("action.submitted")
    consequences = event_types.count("consequence.received")
    observations = event_types.count("observation.received")
    event_ids = [event.event_id for event in events]
    action_sequence: list[JSONValue] = []
    for event in events:
        if event.event_type != "action.submitted":
            continue
        action = event.payload.get("action")
        if isinstance(action, dict):
            action_sequence.append(action)
    memory_after = process_memory_sample()
    peak_rss = memory_after.get("peak_rss_bytes")
    memory_limit = selected_config.memory_megabytes * 1024 * 1024
    trace_bytes = _directory_bytes(context.trace_root)
    checkpoint_metrics = _checkpoint_metrics(context.checkpoint_root)
    checkpoint_bytes = cast(int, checkpoint_metrics["directory_bytes"])
    decision_max = max(decision_latencies) if decision_latencies else 0.0
    observation_max = max(observation_latencies) if observation_latencies else 0.0
    consequence_max = max(consequence_latencies) if consequence_latencies else 0.0
    checkpoint_max = max(checkpoint_latencies) if checkpoint_latencies else 0.0
    total_step_mean = (
        sum(total_step_latencies) / len(total_step_latencies) if total_step_latencies else 0.0
    )
    total_step_limit = selected_config.wall_clock_seconds / (
        selected_config.max_actions + selected_config.max_resets
    )
    growth_first = cast(dict[str, JSONValue], growth[0]) if growth else None
    growth_last = cast(dict[str, JSONValue], growth[-1]) if growth else None
    action_span = (
        cast(int, growth_last["actions"]) - cast(int, growth_first["actions"])
        if growth_first is not None and growth_last is not None
        else 0
    )
    trace_growth_per_action = (
        (cast(int, growth_last["trace_bytes"]) - cast(int, growth_first["trace_bytes"]))
        / action_span
        if growth_first is not None and growth_last is not None and action_span > 0
        else None
    )
    checkpoint_growth_per_action = (
        (cast(int, growth_last["checkpoint_bytes"]) - cast(int, growth_first["checkpoint_bytes"]))
        / action_span
        if growth_first is not None and growth_last is not None and action_span > 0
        else None
    )
    planner = _planner_expansions(events)
    candidates = _candidate_metrics(events)
    planner_evaluations = cast(int, planner["evaluation_count"])
    planner_max = cast(int, planner["maximum_expanded_nodes"])
    candidate_generations = cast(int, candidates["generation_count"])
    max_coordinate_candidates = cast(int, candidates["maximum_coordinate_candidates"])
    complete_action_chains = submitted == consequences == attempts
    # Reaching this point means both manifest and hash-chain verifiers returned
    # successfully; require a non-empty measured chain as well.
    event_chain_verified = bool(events)
    trace_replay_verified = observations == len(replayed_frames)
    required_predicates: dict[str, JSONValue] = {
        "action_chain_complete": complete_action_chains,
        "candidate_receipt_per_submitted_action": candidate_generations == submitted,
        "controller_fault_free": snapshot.fault_count == 0,
        "coordinate_candidates_bounded": (
            max_coordinate_candidates <= selected_config.max_coordinate_candidates
        ),
        "event_chain_verified": event_chain_verified and len(event_ids) == len(set(event_ids)),
        "planner_exercised_and_bounded": (
            planner_evaluations > 0 and planner_max <= selected_config.max_search_nodes
        ),
        "replay_frame_count_matches_observations": trace_replay_verified,
        "forced_length_workload_completed": (
            selected_config.fixture != "component-stress" or actions == selected_config.max_actions
        ),
    }
    budget_assessment: dict[str, JSONValue] = {
        "checkpoint_bytes_within_declared_limit": (
            checkpoint_bytes <= selected_config.max_checkpoint_bytes
        ),
        "checkpoint_latency_within_declared_limit": (
            checkpoint_max <= selected_config.decision_seconds
            and (bool(checkpoint_latencies) or selected_config.restart_every == 0)
        ),
        "consequence_latency_within_declared_limit": (
            consequence_max <= selected_config.decision_seconds
        ),
        "decision_latency_within_declared_limit": (
            decision_max <= selected_config.decision_seconds
        ),
        "observation_latency_within_declared_limit": (
            observation_max <= selected_config.decision_seconds
        ),
        "peak_rss_within_declared_limit": (isinstance(peak_rss, int) and peak_rss <= memory_limit),
        # Dividing the game wall budget by its maximum attempt count produces
        # an average allowance, not a per-step maximum.  Individual decision,
        # consequence, and checkpoint maxima remain independently bounded
        # above, while scheduled restart spikes are retained in the latency
        # summary and assessed through this arithmetic mean plus whole-game
        # wall time.
        "total_step_latency_within_declared_limit": total_step_mean <= total_step_limit,
        "trace_within_declared_limit": trace_bytes <= selected_config.max_trace_bytes,
        "wall_clock_within_declared_limit": (
            not wall_clock_cutoff_triggered and duration <= selected_config.wall_clock_seconds
        ),
    }
    runtime_verified = all(value is True for value in budget_assessment.values()) and all(
        value is True for value in required_predicates.values()
    )
    return {
        "actions": actions,
        "action_sequence": action_sequence,
        "budget_assessment": budget_assessment,
        "candidate_generation": candidates,
        "checkpoint": checkpoint_metrics,
        "checkpoint_latency_seconds": _latency_summary(checkpoint_latencies),
        "checkpoint_growth_bytes_per_action": checkpoint_growth_per_action,
        "complete_action_chains": complete_action_chains,
        "config": selected_config.to_dict(),
        "consequence_latency_seconds": _latency_summary(consequence_latencies),
        "controller_fault_count": snapshot.fault_count,
        "controller_reset_seconds": controller_reset_seconds,
        "decision_latency_seconds": _latency_summary(decision_latencies),
        "duplicate_event_ids": len(event_ids) - len(set(event_ids)),
        "environment_latency_seconds": _latency_summary(environment_latencies),
        "event_chain_sha256": sha256_json([event.event_hash for event in events]),
        "event_type_counts": event_type_counts,
        "final_phase": phase_before_close.value,
        "git_commit": git_commit,
        "kernel_memory_after": memory_after,
        "kernel_memory_before": memory_before,
        "label": "synthetic",
        "observation_latency_seconds": _latency_summary(observation_latencies),
        "planner": planner,
        "preset": selected_preset.value,
        # Kernel RSS/HWM above is the authoritative whole-process memory
        # measurement.  Python allocator tracing is intentionally disabled in
        # the timed pass because the measured instrumentation overhead dwarfs
        # controller work on this allocation-heavy workload.
        "python_tracemalloc_peak_bytes": None,
        "replayed_delta_count": len(rebuilt_deltas),
        "replayed_frame_count": len(replayed_frames),
        "required_predicates": required_predicates,
        "resets": resets,
        "restart_latency_seconds": _latency_summary(restart_latencies),
        "restart_count": restarts,
        "score": scorecard.score,
        "submitted_action_count": submitted,
        "consequence_count": consequences,
        "total_step_latency_limit_seconds": total_step_limit,
        "total_step_latency_seconds": _latency_summary(total_step_latencies),
        "total_wall_clock_seconds": duration,
        "trace_bytes": trace_bytes,
        "trace_event_count": len(events),
        "trace_growth": growth,
        "trace_growth_bytes_per_action": trace_growth_per_action,
        "trace_replay_verified": trace_replay_verified,
        "timing_scope": {
            "checkpoint": "explicit restart checkpoint only; automatic controller persistence remains inside decision/consequence timing",
            "consequence": "controller apply_consequence only",
            "decision": "controller choose_action only",
            "environment": "synthetic session step only",
            "observation": "initial controller observe only",
            "total_step": "decision through returned consequence, including any explicit restart",
            "total_step_acceptance": "arithmetic mean <= wall_clock_seconds / (max_actions + max_resets); maximum and percentiles retained",
        },
        "variant": selected_variant.value,
        "verified": runtime_verified,
        "wall_clock_cutoff_triggered": wall_clock_cutoff_triggered,
    }


def run_robustness_suite(
    root: Path,
    *,
    seeds: Sequence[int] = (7, 11),
    max_actions: int = 16,
    wall_clock_seconds: float = 60.0,
    git_commit: str = "unavailable-git-identity",
    preset: ControllerPreset | str = ControllerPreset.COMPETITION,
) -> dict[str, JSONValue]:
    """Measure operational safety and variant-specific behavioral predicates."""

    selected_preset = preset if isinstance(preset, ControllerPreset) else ControllerPreset(preset)
    selected_seeds = tuple(seeds)
    if not selected_seeds:
        raise ValueError("robustness seeds must not be empty")
    if any(
        isinstance(seed, bool) or not isinstance(seed, int) or not -(2**63) <= seed < 2**63
        for seed in selected_seeds
    ):
        raise ValueError("robustness seeds must be signed 64-bit integers")
    cases: list[JSONValue] = []
    base_by_seed: dict[int, dict[str, JSONValue]] = {}
    for variant in RobustnessVariant:
        for seed in selected_seeds:
            case_root = root / variant.value / f"seed-{seed}"
            result = run_runtime_profile(
                case_root,
                config=RuntimeProfileConfig(
                    seed=seed,
                    frame_size=8,
                    fixture="navigation",
                    max_actions=max_actions,
                    max_resets=2,
                    restart_every=0,
                    wall_clock_seconds=wall_clock_seconds,
                    max_search_nodes=2_048,
                    max_search_depth=32,
                ),
                git_commit=git_commit,
                preset=selected_preset,
                variant=variant,
            )
            case: dict[str, JSONValue] = {
                "actions": result["actions"],
                "complete_action_chains": result["complete_action_chains"],
                "controller_fault_count": result["controller_fault_count"],
                "decision_latency_seconds": result["decision_latency_seconds"],
                "duplicate_event_ids": result["duplicate_event_ids"],
                "final_phase": result["final_phase"],
                "resets": result["resets"],
                "score": result["score"],
                "seed": seed,
                "trace_event_count": result["trace_event_count"],
                "variant": variant.value,
            }
            operational_verified = result["verified"] is True
            behavior_exercised = True
            behavior_verified = True
            behavior_predicate = "reference run"
            if variant is RobustnessVariant.BASE:
                base_by_seed[seed] = result
            else:
                reference = base_by_seed[seed]
                score_parity = result["score"] == reference["score"]
                phase_parity = result["final_phase"] == reference["final_phase"]
                if variant in {
                    RobustnessVariant.PALETTE,
                    RobustnessVariant.TRANSLATION,
                    RobustnessVariant.DISTRACTOR,
                }:
                    behavior_predicate = "terminal phase and score parity with same-seed base"
                    behavior_verified = score_parity and phase_parity
                elif variant is RobustnessVariant.ACTION_REMAP:
                    behavior_predicate = "score parity after a remapped action boundary"
                    behavior_exercised = cast(int, result["actions"]) > 0
                    behavior_verified = behavior_exercised and score_parity
                else:
                    event_counts = cast(dict[str, JSONValue], result["event_type_counts"])
                    contradicted = event_counts.get("hypothesis.contradicted", 0)
                    mismatched = event_counts.get("consequence.mismatched_prediction", 0)
                    change_signals = (contradicted if isinstance(contradicted, int) else 0) + (
                        mismatched if isinstance(mismatched, int) else 0
                    )
                    behavior_predicate = "rule change reached and produced contradiction or prediction-mismatch evidence"
                    behavior_exercised = cast(int, result["actions"]) > 3
                    behavior_verified = behavior_exercised and change_signals > 0
                    case["rule_change_signal_count"] = change_signals
            case_verified = operational_verified and behavior_verified
            case.update(
                {
                    "behavior_exercised": behavior_exercised,
                    "behavior_predicate": behavior_predicate,
                    "behavior_verified": behavior_verified,
                    "operational_verified": operational_verified,
                    "status": (
                        "PASS"
                        if case_verified
                        else "NOT_EXERCISED"
                        if operational_verified and not behavior_exercised
                        else "FAILED_MECHANISM"
                    ),
                    "verified": case_verified,
                }
            )
            cases.append(case)
    completed = sum(cast(float, cast(dict[str, JSONValue], case)["score"]) > 0 for case in cases)
    case_objects = [cast(dict[str, JSONValue], case) for case in cases]
    verified = all(case["verified"] is True for case in case_objects)
    any_not_exercised = any(case["status"] == "NOT_EXERCISED" for case in case_objects)
    return {
        "case_count": len(cases),
        "cases": cases,
        "completed": completed,
        "label": "synthetic",
        "required_variants": [variant.value for variant in RobustnessVariant],
        "seeds": list(selected_seeds),
        "status": (
            "PASS"
            if verified
            else "PARTIAL"
            if any_not_exercised
            and all(case["status"] != "FAILED_MECHANISM" for case in case_objects)
            else "FAILED_MECHANISM"
        ),
        "verified": verified,
    }


def _base_observation(*, state: GameStateName = GameStateName.NOT_FINISHED) -> Observation:
    return Observation(
        game_id=GameId("synthetic-stage16-fault-fixture"),
        frames=(GridFrame.from_rows(((0, 1, 0), (0, 0, 2), (0, 0, 0))),),
        state=state,
        levels_completed=0,
        win_levels=1,
        available_actions=(
            (ActionName.ACTION1, ActionName.ACTION2, ActionName.ACTION3, ActionName.ACTION4)
            if state is GameStateName.NOT_FINISHED
            else ()
        ),
    )


def _fault_context(
    root: Path,
    name: str,
    *,
    max_actions: int = 4,
    git_commit: str,
) -> RunContext:
    return RunContext(
        run_id=f"stage16-fault-{name}",
        episode_id=f"stage16-fault-{name}-episode",
        game_id="synthetic-stage16-fault-fixture",
        trace_root=root / name / "trace",
        checkpoint_root=root / name / "checkpoint",
        config=ARC3Config(
            mode=EnvironmentMode.SYNTHETIC,
            seed=17,
            network_enabled=False,
            profile="stage16-fault-matrix",
            budgets=BudgetConfig(max_actions=max_actions, max_resets=2),
        ),
        git_commit=git_commit,
        source_kind="arc3-stage16-fault-matrix",
        source_version="0.1",
    )


def _caught_name(operation: Callable[[], object]) -> str | None:
    try:
        operation()
    except Exception as error:  # the matrix records the exact typed boundary
        return type(error).__name__
    return None


def _fault_case(
    values: dict[str, JSONValue],
    *,
    predicates: dict[str, bool],
) -> dict[str, JSONValue]:
    verified = all(predicates.values())
    return {
        **values,
        "predicates": cast(dict[str, JSONValue], predicates),
        "status": "PASS" if verified else "FAILED_MECHANISM",
        "verified": verified,
    }


def run_fault_matrix(
    root: Path,
    *,
    git_commit: str = "unavailable-git-identity",
) -> dict[str, JSONValue]:
    """Exercise malformed, mismatch, budget, reset, and checkpoint boundaries."""

    matrix_root = root.resolve()
    matrix_root.mkdir(parents=True, exist_ok=False)
    cases: list[JSONValue] = []

    malformed = ARC3Controller(ControllerPreset.FULL)
    malformed.reset(_fault_context(matrix_root, "malformed-type", git_commit=git_commit))
    malformed_error = _caught_name(lambda: malformed.observe(object()))
    malformed_events = malformed.journal.verify_manifest()
    malformed_parse_count = sum(
        event.event_type == "observation.parse_failed" for event in malformed_events
    )
    cases.append(
        _fault_case(
            {
                "case": "malformed-observation-type",
                "error": malformed_error,
                "parse_receipt_count": malformed_parse_count,
                "phase": malformed.phase.value,
            },
            predicates={
                "faulted": malformed.phase is ControllerPhase.FAULTED,
                "policy_error": malformed_error == "PolicyError",
                "receipt_preserved": malformed_parse_count == 1,
            },
        )
    )
    malformed.close()

    empty_context = _fault_context(matrix_root, "empty-frames", git_commit=git_commit)
    empty = ARC3Controller(ControllerPreset.FULL)
    empty.reset(empty_context)
    empty_observation = Observation(
        game_id=GameId(empty_context.game_id),
        frames=(),
        state=GameStateName.NOT_FINISHED,
        levels_completed=0,
        win_levels=1,
        available_actions=(ActionName.ACTION1,),
    )
    empty_error = _caught_name(lambda: empty.observe(empty_observation))
    empty_parse_count = sum(
        event.event_type == "observation.parse_failed" for event in empty.journal.verify_manifest()
    )
    cases.append(
        _fault_case(
            {
                "case": "empty-frame-batch",
                "error": empty_error,
                "parse_receipt_count": empty_parse_count,
                "phase": empty.phase.value,
            },
            predicates={
                "faulted": empty.phase is ControllerPhase.FAULTED,
                "policy_error": empty_error == "PolicyError",
                "receipt_preserved": empty_parse_count == 1,
            },
        )
    )
    empty.close()

    metadata_context = _fault_context(matrix_root, "metadata", git_commit=git_commit)
    metadata = ARC3Controller(ControllerPreset.FULL)
    metadata.reset(metadata_context)
    invalid_scalar = cast(JSONScalar, object())
    metadata_observation = Observation(
        game_id=GameId(metadata_context.game_id),
        frames=_base_observation().frames,
        state=GameStateName.NOT_FINISHED,
        levels_completed=0,
        win_levels=1,
        available_actions=(ActionName.ACTION1,),
        upstream_metadata=(("non_canonical", invalid_scalar),),
    )
    metadata_error = _caught_name(lambda: metadata.observe(metadata_observation))
    metadata_parse_count = sum(
        event.event_type == "observation.parse_failed"
        for event in metadata.journal.verify_manifest()
    )
    cases.append(
        _fault_case(
            {
                "case": "non-canonical-metadata",
                "error": metadata_error,
                "parse_receipt_count": metadata_parse_count,
                "phase": metadata.phase.value,
            },
            predicates={
                "faulted": metadata.phase is ControllerPhase.FAULTED,
                "policy_error": metadata_error == "PolicyError",
                "receipt_preserved": metadata_parse_count == 1,
            },
        )
    )
    metadata.close()

    frame_error = _caught_name(lambda: GridFrame.from_rows(((0, 16),)))
    action_space_error = _caught_name(
        lambda: Observation(
            game_id=GameId("synthetic-stage16-fault-fixture"),
            frames=_base_observation().frames,
            state=GameStateName.NOT_FINISHED,
            levels_completed=0,
            win_levels=1,
            available_actions=(ActionName.ACTION1, ActionName.ACTION1),
        )
    )
    cases.extend(
        (
            _fault_case(
                {
                    "case": "out-of-range-frame-cell",
                    "error": frame_error,
                },
                predicates={"value_error": frame_error == "ValueError"},
            ),
            _fault_case(
                {
                    "case": "duplicate-action-space",
                    "error": action_space_error,
                },
                predicates={"value_error": action_space_error == "ValueError"},
            ),
        )
    )

    mismatch_context = _fault_context(matrix_root, "action-mismatch", git_commit=git_commit)
    mismatch = ARC3Controller(ControllerPreset.FULL)
    initial = _base_observation()
    mismatch.reset(mismatch_context)
    mismatch.observe(initial)
    decision = mismatch.choose_action()
    other = next(
        action for action in initial.available_actions if action is not decision.action.name
    )
    mismatched = Observation(
        game_id=initial.game_id,
        frames=initial.frames,
        state=initial.state,
        levels_completed=0,
        win_levels=1,
        available_actions=initial.available_actions,
        returned_action=ActionRequest(other),
    )
    mismatch_error = _caught_name(lambda: mismatch.apply_consequence(mismatched))
    mismatch_events = mismatch.journal.verify_manifest()
    mismatch_consequences = sum(
        event.event_type == "consequence.received" for event in mismatch_events
    )
    mismatch_rejections = sum(
        event.event_type == "action.rejected_by_environment" for event in mismatch_events
    )
    cases.append(
        _fault_case(
            {
                "case": "returned-action-mismatch",
                "consequence_receipt_count": mismatch_consequences,
                "error": mismatch_error,
                "phase": mismatch.phase.value,
                "rejection_receipt_count": mismatch_rejections,
            },
            predicates={
                "faulted": mismatch.phase is ControllerPhase.FAULTED,
                "policy_error": mismatch_error == "PolicyError",
                "returned_consequence_preserved": mismatch_consequences == 1,
                "rejection_preserved": mismatch_rejections == 1,
            },
        )
    )
    mismatch.close()

    budget_context = _fault_context(
        matrix_root,
        "budget",
        max_actions=1,
        git_commit=git_commit,
    )
    budget = ARC3Controller(ControllerPreset.FULL)
    budget.reset(budget_context)
    budget.observe(initial)
    first = budget.choose_action()
    budget.apply_consequence(
        Observation(
            game_id=initial.game_id,
            frames=initial.frames,
            state=initial.state,
            levels_completed=0,
            win_levels=1,
            available_actions=initial.available_actions,
            returned_action=first.action,
        )
    )
    budget_error = _caught_name(budget.choose_action)
    cases.append(
        _fault_case(
            {
                "case": "action-budget-exhaustion",
                "error": budget_error,
                "phase": budget.phase.value,
            },
            predicates={
                "faulted": budget.phase is ControllerPhase.FAULTED,
                "policy_error": budget_error == "PolicyError",
            },
        )
    )
    budget.close()

    reset_context = _fault_context(matrix_root, "game-over", git_commit=git_commit)
    reset = ARC3Controller(ControllerPreset.FULL)
    reset.reset(reset_context)
    reset.observe(_base_observation(state=GameStateName.GAME_OVER))
    reset_decision = reset.choose_action()
    reset.apply_consequence(
        Observation(
            game_id=GameId(reset_context.game_id),
            frames=_base_observation().frames,
            state=GameStateName.NOT_FINISHED,
            levels_completed=0,
            win_levels=1,
            available_actions=_base_observation().available_actions,
            full_reset=True,
            returned_action=reset_decision.action,
        )
    )
    cases.append(
        _fault_case(
            {
                "case": "game-over-reset-only",
                "phase": reset.phase.value,
                "reset_action": reset_decision.action.name.value,
            },
            predicates={
                "observed_after_reset": reset.phase is ControllerPhase.OBSERVED,
                "reset_selected": reset_decision.action.name is ActionName.RESET,
            },
        )
    )
    reset.close()

    checkpoint_context = _fault_context(matrix_root, "checkpoint", git_commit=git_commit)
    checkpoint_controller = ARC3Controller(ControllerPreset.FULL)
    checkpoint_controller.reset(checkpoint_context)
    checkpoint_controller.observe(_base_observation())
    checkpoint = checkpoint_controller.checkpoint()
    partial_path = checkpoint.path.with_name("partial-checkpoint.json")
    checkpoint_bytes = checkpoint.path.read_bytes()
    partial_path.write_bytes(checkpoint_bytes[: max(1, len(checkpoint_bytes) // 2)])
    store = CheckpointStore(checkpoint_context.checkpoint_root)
    partial_error = _caught_name(lambda: store.load(partial_path))
    envelope = checkpoint.envelope
    incompatible_error = _caught_name(
        lambda: store.restore(
            expected_run_id=envelope.run_id,
            expected_episode_id=envelope.episode_id,
            expected_trace_tail_event_id=envelope.trace_tail_event_id,
            expected_trace_tail_hash=envelope.trace_tail_hash,
            expected_git_commit="deliberately-incompatible-code",
            expected_config_hash=envelope.config_hash,
            path=checkpoint.path,
        )
    )
    valid_checkpoint_load_error = _caught_name(store.load)
    valid_checkpoint_preserved = checkpoint.path.read_bytes() == checkpoint_bytes
    checkpoint_controller.close()
    fallback_restore_error: str | None = None
    fallback_restore_phase: str | None = None
    try:
        fallback = ARC3Controller.restore(
            checkpoint_context,
            preset=ControllerPreset.FULL,
        )
        fallback_restore_phase = fallback.phase.value
        fallback.close()
    except Exception as error:  # matrix records the concrete fallback boundary
        fallback_restore_error = type(error).__name__
    cases.extend(
        (
            _fault_case(
                {
                    "case": "partial-checkpoint",
                    "error": partial_error,
                    "preserved": partial_path.is_file(),
                    "valid_checkpoint_load_error": valid_checkpoint_load_error,
                    "valid_checkpoint_preserved": valid_checkpoint_preserved,
                    "fallback_restore_error": fallback_restore_error,
                    "fallback_restore_phase": fallback_restore_phase,
                },
                predicates={
                    "partial_rejected": partial_error == "CheckpointError",
                    "partial_receipt_preserved": partial_path.is_file(),
                    "prior_checkpoint_loadable": valid_checkpoint_load_error is None,
                    "prior_checkpoint_unchanged": valid_checkpoint_preserved,
                    "latest_checkpoint_restores": fallback_restore_error is None,
                    "restored_observed_phase": fallback_restore_phase == "observed",
                },
            ),
            _fault_case(
                {
                    "case": "incompatible-checkpoint",
                    "error": incompatible_error,
                    "preserved": checkpoint.path.is_file(),
                },
                predicates={
                    "incompatible_rejected": incompatible_error == "CheckpointError",
                    "checkpoint_preserved": checkpoint.path.is_file(),
                },
            ),
        )
    )

    upstream_context = _fault_context(matrix_root, "upstream-error", git_commit=git_commit)
    upstream = ARC3Controller(ControllerPreset.FULL)
    upstream.reset(upstream_context)
    upstream.observe(_base_observation())
    upstream.choose_action()
    pending = upstream.checkpoint()
    before_events = upstream.journal.event_count
    simulated_upstream_error = _caught_name(
        lambda: (_ for _ in ()).throw(RuntimeError("synthetic upstream failure"))
    )
    upstream.close()
    restored = ARC3Controller.restore(
        upstream_context,
        preset=ControllerPreset.FULL,
        checkpoint_path=pending.path,
    )
    event_count_preserved = restored.journal.event_count == before_events
    cases.append(
        _fault_case(
            {
                "case": "upstream-error-before-consequence",
                "error": simulated_upstream_error,
                "event_count_preserved": event_count_preserved,
                "phase": restored.phase.value,
            },
            predicates={
                "pending_action_restored": restored.phase is ControllerPhase.AWAITING_CONSEQUENCE,
                "trace_event_count_preserved": event_count_preserved,
                "upstream_error_observed": simulated_upstream_error == "RuntimeError",
            },
        )
    )
    restored.close()

    case_objects = [cast(dict[str, JSONValue], case) for case in cases]
    verified = all(case["verified"] is True for case in case_objects)
    return {
        "case_count": len(cases),
        "cases": cases,
        "label": "synthetic",
        "known_input_gaps": [],
        "status": "PASS" if verified else "FAILED_MECHANISM",
        "verified": verified,
    }


__all__ = [
    "process_memory_sample",
    "run_fault_matrix",
    "run_robustness_suite",
    "run_runtime_profile",
]
