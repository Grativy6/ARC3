"""Measure ARC3 hot-path profiler overhead on fixed synthetic episodes only.

The harness alternates disabled and enabled trials under one seed and action
budget.  Timing is never supplied to the policy.  Public-game manifests,
assets, adapters, and episodes are outside this tool's input surface.
"""

from __future__ import annotations

import argparse
import os
import platform
import statistics
import subprocess
import sys
import time
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
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
    ControllerPhase,
    ControllerPreset,
    RunContext,
)
from arc3.profiling import HotPathPhase, HotPathProfiler, process_memory_sample
from arc3.types import ActionRequest, EnvironmentMode, GameStateName, JSONValue

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SEED = 25
DEFAULT_REPETITIONS = 7
DEFAULT_ACTIONS = 8
DEFAULT_OUTPUT = ROOT / "artifacts" / "stage02" / "hot-path-overhead.json"
DEFAULT_WORK_ROOT = ROOT / "artifacts" / "stage02" / "hot-path-overhead-work"


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


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
    if completed.returncode != 0:
        return None
    return completed.stdout.strip()


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
        ROOT / "scripts" / "measure_hot_path.py",
        ROOT / "pyproject.toml",
        ROOT / "uv.lock",
    ):
        if path.is_file():
            candidates.append(path)
    entries = [
        {
            "path": path.relative_to(ROOT).as_posix(),
            "sha256": sha256_file(path),
        }
        for path in sorted(set(candidates))
    ]
    worktree_status = _git_value("status", "--porcelain=v1")
    identity: dict[str, object] = {
        "branch": _git_value("branch", "--show-current"),
        "dirty_worktree": worktree_status is None or bool(worktree_status),
        "dirty_worktree_reason": ("git status unavailable" if worktree_status is None else None),
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
        "timer": {
            "cpu": "time.process_time_ns",
            "wall": "time.perf_counter_ns",
        },
    }


def _positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("value must be an integer") from error
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be positive")
    return parsed


def _trial_modes(repetitions: int) -> tuple[bool, ...]:
    """Return strict disabled/enabled alternation with equal sample counts."""

    if isinstance(repetitions, bool) or not isinstance(repetitions, int) or repetitions <= 0:
        raise ValueError("repetitions must be a positive integer")
    return tuple(enabled for _ in range(repetitions) for enabled in (False, True))


def _action_payload(action: ActionRequest) -> dict[str, JSONValue]:
    coordinate = action.coordinate
    return {
        "coordinate": (None if coordinate is None else {"x": coordinate.x, "y": coordinate.y}),
        "name": action.name.value,
    }


def _decision_signature(decision: ActionDecision) -> dict[str, JSONValue]:
    """Capture exact policy outputs while excluding run-specific receipt IDs."""

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
        "scope": "whole-process; peak may include earlier trials in this process",
    }


def _context(
    trial_root: Path,
    *,
    seed: int,
    actions: int,
    trial_index: int,
    profiler_enabled: bool,
    git_commit: str,
) -> RunContext:
    mode = "enabled" if profiler_enabled else "disabled"
    label = f"trial-{trial_index:03d}-{mode}"
    return RunContext(
        run_id=f"stage02-hot-path-{seed}-{label}",
        episode_id=f"stage02-hot-path-episode-{seed}-{label}",
        game_id=SYNTHETIC_GAME_ID,
        trace_root=trial_root / "trace",
        checkpoint_root=trial_root / "checkpoint",
        config=ARC3Config(
            mode=EnvironmentMode.SYNTHETIC,
            seed=seed,
            network_enabled=False,
            profile="build-001-stage02-hot-path-overhead",
            budgets=BudgetConfig(
                max_actions=actions,
                max_resets=max(1, actions),
                max_search_nodes=2_048,
            ),
        ),
        git_commit=git_commit,
        source_kind="build-001-stage02-hot-path-overhead",
        source_version="0.1",
    )


def _run_trial(
    work_root: Path,
    *,
    seed: int,
    actions: int,
    trial_index: int,
    repetition: int,
    profiler_enabled: bool,
    git_commit: str,
) -> dict[str, object]:
    mode = "enabled" if profiler_enabled else "disabled"
    trial_root = work_root / f"trial-{trial_index:03d}-{mode}"
    before_rss = process_memory_sample()
    wall_started_ns = time.perf_counter_ns()
    cpu_started_ns = time.process_time_ns()
    profiler = HotPathProfiler(enabled=profiler_enabled)

    with profiler.span(HotPathPhase.STARTUP):
        session = SyntheticAdapter(seed=seed, size=8, max_steps=actions).open(
            SYNTHETIC_GAME_ID,
            seed=seed,
        )
        controller = ARC3Controller(ControllerPreset.FULL, hot_path_profiler=profiler)
        context = _context(
            trial_root,
            seed=seed,
            actions=actions,
            trial_index=trial_index,
            profiler_enabled=profiler_enabled,
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

    snapshot = controller.snapshot
    final_state = session.observation.state
    with profiler.span(HotPathPhase.FINALIZE):
        controller.close()
        scorecard = session.close()

    cpu_elapsed_ns = max(0, time.process_time_ns() - cpu_started_ns)
    wall_elapsed_ns = max(0, time.perf_counter_ns() - wall_started_ns)
    # The profile denominator starts at profiler construction. The external
    # trial timer remains the overhead comparator but includes harness setup.
    phase_summary = profiler.summary()
    after_rss = process_memory_sample()
    signature_hash = sha256_bytes(canonical_json_bytes(decisions))
    return {
        "completed": final_state is GameStateName.WIN,
        "controller_action_count": snapshot.actions_used,
        "controller_fault_count": snapshot.fault_count,
        "controller_reset_count": snapshot.resets_used,
        "cpu_ns": cpu_elapsed_ns,
        "decision_count": len(decisions),
        "decision_signature": decisions,
        "decision_signature_hash": signature_hash,
        "environment_action_count": scorecard.total_actions,
        "final_state": final_state.value,
        "phase_summary": phase_summary,
        "profiler_enabled": profiler_enabled,
        "repetition": repetition,
        "rss": _rss_report(before_rss, after_rss),
        "score": scorecard.score,
        "seed": seed,
        "trial_index": trial_index,
        "wall_ns": wall_elapsed_ns,
    }


def _median(values: list[int]) -> float:
    return float(statistics.median(values))


def _ratio(numerator: float, denominator: float) -> float | None:
    if denominator <= 0.0:
        return None
    return round(numerator / denominator, 12)


def measure_hot_path_overhead(
    *,
    seed: int,
    repetitions: int,
    actions: int,
    work_root: Path,
) -> dict[str, object]:
    """Run paired synthetic trials and return one self-hashed evidence object."""

    if isinstance(seed, bool) or not isinstance(seed, int) or not -(2**63) <= seed < 2**63:
        raise ValueError("seed must be a signed 64-bit integer")
    if isinstance(actions, bool) or not isinstance(actions, int) or actions <= 0:
        raise ValueError("actions must be a positive integer")
    modes = _trial_modes(repetitions)
    if work_root.exists():
        if not work_root.is_dir():
            raise ValueError(f"work root is not a directory: {work_root}")
        if any(work_root.iterdir()):
            raise ValueError(f"work root already contains data: {work_root}")
    work_root.mkdir(parents=True, exist_ok=True)

    started_at = _utc_now()
    source_identity = _source_identity()
    git_commit_value = source_identity.get("git_commit")
    git_commit = (
        git_commit_value
        if isinstance(git_commit_value, str) and git_commit_value
        else "unavailable-git-identity"
    )
    trials = [
        _run_trial(
            work_root,
            seed=seed,
            actions=actions,
            trial_index=index,
            repetition=index // 2,
            profiler_enabled=enabled,
            git_commit=git_commit,
        )
        for index, enabled in enumerate(modes)
    ]
    disabled = [trial for trial in trials if trial["profiler_enabled"] is False]
    enabled = [trial for trial in trials if trial["profiler_enabled"] is True]
    disabled_wall = _median([cast(int, trial["wall_ns"]) for trial in disabled])
    enabled_wall = _median([cast(int, trial["wall_ns"]) for trial in enabled])
    disabled_cpu = _median([cast(int, trial["cpu_ns"]) for trial in disabled])
    enabled_cpu = _median([cast(int, trial["cpu_ns"]) for trial in enabled])
    reference_signature = trials[0]["decision_signature"]
    signatures_match = all(trial["decision_signature"] == reference_signature for trial in trials)
    reference_outcome = (
        trials[0]["completed"],
        trials[0]["controller_action_count"],
        trials[0]["controller_reset_count"],
        trials[0]["decision_count"],
        trials[0]["environment_action_count"],
        trials[0]["final_state"],
        trials[0]["score"],
    )
    outcomes_match = all(
        (
            trial["completed"],
            trial["controller_action_count"],
            trial["controller_reset_count"],
            trial["decision_count"],
            trial["environment_action_count"],
            trial["final_state"],
            trial["score"],
        )
        == reference_outcome
        for trial in trials
    )
    wall_ratio = _ratio(enabled_wall, disabled_wall)
    cpu_ratio = _ratio(enabled_cpu, disabled_cpu)
    comparison: dict[str, object] = {
        "disabled_median_cpu_ns": disabled_cpu,
        "disabled_median_wall_ns": disabled_wall,
        "enabled_median_cpu_ns": enabled_cpu,
        "enabled_median_wall_ns": enabled_wall,
        "exact_action_decision_signatures_match": signatures_match,
        "exact_outcomes_match": outcomes_match,
        "median_cpu_overhead_ratio": cpu_ratio,
        "median_wall_overhead_percent": (
            None if wall_ratio is None else round((wall_ratio - 1.0) * 100.0, 9)
        ),
        "median_wall_overhead_ratio": wall_ratio,
        "reference_decision_signature_hash": trials[0]["decision_signature_hash"],
    }
    report: dict[str, object] = {
        "completed_at": _utc_now(),
        "comparison": comparison,
        "configuration": {
            "action_budget": actions,
            "game_id": SYNTHETIC_GAME_ID,
            "grid_size": 8,
            "max_steps": actions,
            "network_enabled": False,
            "preset": ControllerPreset.FULL.value,
            "repetitions_per_mode": repetitions,
            "seed": seed,
            "total_trials": len(trials),
            "trial_order": ["enabled" if item else "disabled" for item in modes],
        },
        "evidence_label": "synthetic",
        "limitations": [
            "This measures one fixed synthetic episode and makes no public-game or generalization claim.",
            "Whole-process peak RSS may include earlier trials in the same process.",
            "Wall/CPU observations vary by host load; seeded policy decisions are the deterministic control.",
            "No public-game or holdout manifest, asset, adapter, or episode is accessed.",
        ],
        "runtime": _runtime_identity(),
        "schema": "arc3.hot-path-overhead.v0.1",
        "source_identity": source_identity,
        "started_at": started_at,
        "status": "PASS" if signatures_match and outcomes_match else "FAILED_MECHANISM",
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
    report = measure_hot_path_overhead(
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
