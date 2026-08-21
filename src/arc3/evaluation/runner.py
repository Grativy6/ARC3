"""Crash-preserving, process-isolated Stage 13 batch evaluation runner."""

from __future__ import annotations

import hashlib
import json
import math
import multiprocessing
import os
import platform
import shlex
import subprocess
import sys
import time
import tracemalloc
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from arc3.adapters import ScoreSummary
from arc3.adapters.synthetic import SYNTHETIC_GAME_ID, SyntheticAdapter
from arc3.config import ARC3Config, BudgetConfig
from arc3.errors import EvaluationError, TraceError
from arc3.trace import (
    BaselineTraceSink,
    CodeIdentity,
    EventJournal,
    ReplayEngine,
    SourceIdentity,
)
from arc3.types import ActionName, EnvironmentMode, GameStateName

from .artifacts import (
    atomic_write_bytes,
    atomic_write_json,
    atomic_write_text,
    canonical_json_bytes,
    load_json,
    run_receipt_errors,
    seal_object,
    sha256_bytes,
    sha256_file,
    verify_evaluation_artifacts,
    verify_object_hash,
)
from .baselines import baseline_descriptor, make_evaluation_policy
from .models import EvaluationConfig, EvaluationOutcome
from .reports import build_summary, render_markdown
from .thresholds import evaluate_performance_thresholds

if TYPE_CHECKING:
    from arc3.policy import RunContext

_TERMINAL_EVALUATION_STATUSES = {"PASS", "PARTIAL", "FAILED_INFRASTRUCTURE"}
_SOURCE_SUFFIXES = {".json", ".py", ".toml", ".yaml", ".yml"}


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _repository_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _git_value(*arguments: str) -> str | None:
    try:
        completed = subprocess.run(
            ("git", *arguments),
            cwd=_repository_root(),
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    value = completed.stdout.strip()
    return value or None


def _hardware() -> dict[str, object]:
    ram_gb: float | None = None
    ram_reason: str | None = None
    try:
        if sys.platform == "win32":
            import ctypes

            class MemoryStatus(ctypes.Structure):
                _fields_ = [
                    ("length", ctypes.c_ulong),
                    ("memory_load", ctypes.c_ulong),
                    ("total_physical", ctypes.c_ulonglong),
                    ("available_physical", ctypes.c_ulonglong),
                    ("total_page_file", ctypes.c_ulonglong),
                    ("available_page_file", ctypes.c_ulonglong),
                    ("total_virtual", ctypes.c_ulonglong),
                    ("available_virtual", ctypes.c_ulonglong),
                    ("available_extended_virtual", ctypes.c_ulonglong),
                ]

            status = MemoryStatus()
            status.length = ctypes.sizeof(status)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
                ram_gb = round(status.total_physical / (1024**3), 3)
            else:
                ram_reason = "GlobalMemoryStatusEx returned failure"
        elif hasattr(os, "sysconf"):
            ram_gb = round(
                int(os.sysconf("SC_PHYS_PAGES")) * int(os.sysconf("SC_PAGE_SIZE")) / (1024**3),
                3,
            )
        else:
            ram_reason = "no portable physical-memory query is available"
    except (AttributeError, OSError, ValueError):
        ram_reason = "physical memory query failed"
    return {
        "cpu": platform.processor() or platform.machine() or None,
        "cpu_count": os.cpu_count(),
        "gpu": None,
        "gpu_reason": "GPU is not required or queried by the symbolic synthetic harness",
        "ram_gb": ram_gb,
        "ram_reason": ram_reason,
    }


def _first_party_source_hash() -> str:
    root = _repository_root()
    candidates: list[Path] = []
    for directory in (root / "src" / "arc3", root / "agent"):
        if directory.is_dir():
            candidates.extend(
                path
                for path in directory.rglob("*")
                if path.is_file()
                and path.suffix.lower() in _SOURCE_SUFFIXES
                and "__pycache__" not in path.parts
            )
    for relative in ("pyproject.toml", "uv.lock"):
        path = root / relative
        if path.is_file():
            candidates.append(path)
    entries = [
        {
            "path": path.relative_to(root).as_posix(),
            "sha256": sha256_file(path),
        }
        for path in sorted(set(candidates))
    ]
    return sha256_bytes(canonical_json_bytes(entries))


def _identity(config: EvaluationConfig) -> dict[str, object]:
    root = _repository_root()
    lock = root / "upstream.lock.json"
    partition_manifest = root / "docs" / "evaluation" / "public-game-partitions.v0.1.json"
    threshold_file = Path(__file__).with_name("performance-thresholds.v0.1.json")
    dirty_output = _git_value("status", "--porcelain")
    declaration = config.declaration()
    identity: dict[str, object] = {
        "git_commit": _git_value("rev-parse", "HEAD"),
        "dirty_worktree": dirty_output is None or bool(dirty_output),
        "dirty_worktree_reason": "git status unavailable" if dirty_output is None else None,
        "first_party_source_hash": _first_party_source_hash(),
        "upstream_lock_hash": sha256_file(lock) if lock.is_file() else None,
        "upstream_lock_reason": None if lock.is_file() else "upstream.lock.json is missing",
        "public_partition_manifest_hash": (
            sha256_file(partition_manifest) if partition_manifest.is_file() else None
        ),
        "public_partition_manifest_note": (
            "identity only; public game entries were not opened by this synthetic run"
        ),
        "performance_threshold_hash": sha256_file(threshold_file),
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "hardware": _hardware(),
        "agent_config": declaration,
        "config_hash": sha256_bytes(canonical_json_bytes(declaration)),
        "games": [SYNTHETIC_GAME_ID],
        "seeds": list(config.seeds),
        "action_budget": config.max_actions,
        "wall_clock_budget_seconds": config.timeout_seconds,
        "budgets": {
            "maximum_actions": config.max_actions,
            "maximum_resets": config.max_resets,
            "maximum_decision_latency_seconds": None,
            "maximum_wall_clock_seconds": config.timeout_seconds,
            "maximum_ram_bytes": None,
            "maximum_generated_coordinate_candidates": None,
            "maximum_search_nodes": None,
            "maximum_search_depth": None,
            "maximum_trace_bytes": None,
            "unspecified_reason": (
                "policy-specific internal budgets remain in its recorded controller configuration"
            ),
        },
        "network_mode": "offline",
    }
    identity["identity_hash"] = sha256_bytes(canonical_json_bytes(identity))
    return identity


def _percentile(values: list[float], quantile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, math.ceil(quantile * len(ordered)) - 1)
    return ordered[index]


def _empty_score() -> dict[str, object]:
    return {
        "scorer": None,
        "verified": False,
        "score": 0.0,
        "total_score": 0.0,
        "game_score": None,
        "official_rhae": None,
        "official_rhae_reason": "no scorecard was returned",
        "human_baselines_available": False,
        "levels_completed": 0,
        "completed": False,
        "level_scores": [],
        "level_actions": [],
        "level_human_baseline_actions": [],
    }


def _empty_metrics() -> dict[str, object]:
    return {
        "environment_actions": 0,
        "resets": 0,
        "game_over_events": 0,
        "time_to_first_progress_seconds": None,
        "actions_to_first_completed_level": None,
        "repeated_no_op_rate": 0.0,
        "invalid_action_rate": 0.0,
        "coordinate_action_hit_rate": None,
        "unique_state_count": 0,
        "state_revisitation_rate": 0.0,
        "prediction_accuracy_by_horizon": None,
        "transitions_explained_fraction": None,
        "hypothesis_creation_count": None,
        "hypothesis_rejection_count": None,
        "hypothesis_reopening_count": None,
        "average_hypotheses_retained": None,
        "retrodiction_contradiction_rate": None,
        "planner_success_rate": None,
        "replans_caused_by_mismatch": None,
        "trace_bytes_per_action": None,
        "peak_ram_bytes": None,
        "peak_ram_measurement": "Python tracemalloc allocation peak",
        "decision_latency_seconds": {"p50": None, "p95": None, "p99": None},
        "total_wall_clock_seconds": 0.0,
        "unsupported_metric_reasons": {
            "prediction_accuracy_by_horizon": "trace has no calibrated horizon labels",
            "transitions_explained_fraction": "selected policy may emit no active world model",
            "average_hypotheses_retained": "trace events do not encode a per-step retained count",
            "planner_success_rate": "plan evaluation events do not yet encode a calibrated denominator",
        },
    }


def _score_payload(scorecard: ScoreSummary) -> dict[str, object]:
    score_run = scorecard.runs[0] if scorecard.runs else None
    baseline_actions = list(score_run.level_baseline_actions) if score_run else []
    return {
        "scorer": scorecard.scorer,
        "verified": scorecard.verified,
        "score": scorecard.score,
        "total_score": scorecard.score,
        "game_score": score_run.score if score_run else None,
        "official_rhae": None,
        "official_rhae_reason": (
            "normalized scorecard preserves level scores and baselines but does not identify "
            "whether a value is raw, capped, or weighted RHAE"
            if baseline_actions
            else "adapter supplied no human action baselines"
        ),
        "human_baselines_available": bool(baseline_actions),
        "levels_completed": score_run.levels_completed if score_run else 0,
        "completed": score_run.completed if score_run else False,
        "level_scores": list(score_run.level_scores) if score_run else [],
        "level_actions": list(score_run.level_actions) if score_run else [],
        "level_human_baseline_actions": baseline_actions,
    }


def _run_id(agent: str, seed: int) -> str:
    safe_seed = str(seed).replace("-", "neg")
    return f"{baseline_descriptor(agent).baseline_id}-{agent}-seed-{safe_seed}"


def _storage_key(run_id: str) -> str:
    return hashlib.sha256(run_id.encode("utf-8")).hexdigest()[:16]


def _runtime_path(path: Path) -> Path:
    """Use Windows' extended path form for deeply nested content-addressed blobs."""

    resolved = path.resolve()
    if os.name == "nt":
        value = str(resolved)
        if not value.startswith("\\\\?\\"):
            return Path(f"\\\\?\\{value}")
    return resolved


def _run_specification(
    evaluation_id: str,
    agent: str,
    seed: int,
    config: EvaluationConfig,
    identity: dict[str, object],
) -> dict[str, object]:
    specification: dict[str, object] = {
        "evaluation_id": evaluation_id,
        "run_id": _run_id(agent, seed),
        "baseline_id": baseline_descriptor(agent).baseline_id,
        "agent": agent,
        "seed": seed,
        "max_actions": config.max_actions,
        "max_resets": config.max_resets,
        "timeout_seconds": config.timeout_seconds,
        "identity_hash": identity["identity_hash"],
    }
    specification["run_spec_hash"] = sha256_bytes(canonical_json_bytes(specification))
    return specification


def _failure_result(
    *,
    specification: dict[str, object],
    identity: dict[str, object],
    started_at: str,
    completed_at: str,
    status: str,
    kind: str,
    message: str,
    trace: dict[str, object] | None = None,
    metrics: dict[str, object] | None = None,
) -> dict[str, Any]:
    result_metrics = metrics or _empty_metrics()
    if trace is not None:
        result_metrics["environment_actions"] = trace["environment_action_count"]
        result_metrics["resets"] = trace["reset_count"]
        action_count = cast(int, trace["consequence_count"])
        result_metrics["trace_bytes_per_action"] = (
            cast(int, trace["byte_length"]) / action_count if action_count else None
        )
    result: dict[str, Any] = {
        "schema": "arc3.evaluation.run.v0.1",
        "evaluation_id": specification["evaluation_id"],
        "run_id": specification["run_id"],
        "baseline_id": specification["baseline_id"],
        "agent": specification["agent"],
        "seed": specification["seed"],
        "run_spec_hash": specification["run_spec_hash"],
        "surface": "synthetic",
        "partition": "smoke",
        "status": status,
        "started_at": started_at,
        "completed_at": completed_at,
        "identity": identity,
        "score": _empty_score(),
        "metrics": result_metrics,
        "trace": trace,
        "failure": {"kind": kind, "message": message},
    }
    return seal_object(result, hash_field="receipt_hash")


def _trace_receipt(trace_path: Path, *, run_id: str, relative_path: str) -> dict[str, object]:
    active_path = trace_path / "active.jsonl"
    preserved_recovery: dict[str, object] | None = None
    if active_path.is_file():
        active_bytes = active_path.read_bytes()
        if active_bytes and not active_bytes.endswith(b"\n"):
            source_hash = sha256_bytes(active_bytes)
            recovery_relative = (
                f"recovery/active-pre-recovery-{source_hash.removeprefix('sha256:')}.bin"
            )
            atomic_write_bytes(trace_path / recovery_relative, active_bytes)
            preserved_recovery = {
                "path": recovery_relative,
                "sha256": source_hash,
                "original_byte_length": len(active_bytes),
            }
    journal = EventJournal(trace_path, run_id=run_id, fsync_on_flush=False)
    try:
        if journal.active_path.is_file() and journal.active_path.stat().st_size:
            journal.seal()
        replay = ReplayEngine(journal)
        events = replay.verify_integrity(verify_blobs=True)
        frames = replay.replay_frames()
        counts: dict[str, int] = {}
        environment_actions = 0
        resets = 0
        for event in events:
            counts[event.event_type] = counts.get(event.event_type, 0) + 1
            if event.event_type == "consequence.received":
                action = event.payload.get("action")
                name = action.get("name") if isinstance(action, dict) else None
                if name == ActionName.RESET.value:
                    resets += 1
                else:
                    environment_actions += 1
        receipt = {
            "schema": "arc3.evaluation.trace-receipt.v0.1",
            "path": relative_path,
            "run_id": run_id,
            "event_count": len(events),
            "submitted_action_count": counts.get("action.submitted", 0),
            "consequence_count": counts.get("consequence.received", 0),
            "environment_action_count": environment_actions,
            "reset_count": resets,
            "replayed_frame_count": len(frames),
            "trace_manifest_hash": journal.manifest.manifest_hash,
            "tail_event_hash": events[-1].event_hash if events else None,
            "event_type_counts": counts,
            "replay_verified": True,
            "recovery": (
                {
                    **preserved_recovery,
                    "recovered_byte_length": journal.recovery_receipt.recovered_byte_length,
                    "discarded_byte_length": journal.recovery_receipt.discarded_byte_length,
                }
                if preserved_recovery is not None
                else None
            ),
        }
    finally:
        journal.close()
    receipt["byte_length"] = sum(
        path.stat().st_size for path in trace_path.rglob("*") if path.is_file()
    )
    return receipt


def _full_run_context(spec: dict[str, Any]) -> RunContext:
    from arc3.policy import RunContext

    timeout = float(spec["timeout_seconds"])
    specification = spec["specification"]
    if not isinstance(specification, dict):
        raise EvaluationError("worker run specification is invalid")
    budgets = BudgetConfig(
        max_actions=int(specification["max_actions"]),
        max_resets=int(specification["max_resets"]),
        decision_seconds=max(0.001, min(5.0, timeout)),
        wall_clock_seconds=timeout,
    )
    config = ARC3Config.for_mode(
        EnvironmentMode.SYNTHETIC,
        seed=int(specification["seed"]),
        network_enabled=False,
        profile="stage13-full-evaluation",
        budgets=budgets,
    )
    identity = spec["identity"]
    git_commit = identity.get("git_commit") if isinstance(identity, dict) else None
    return RunContext(
        run_id=str(specification["run_id"]),
        episode_id=f"episode:{specification['run_id']}",
        game_id=SYNTHETIC_GAME_ID,
        trace_root=Path(str(spec["trace_path"])),
        checkpoint_root=Path(str(spec["checkpoint_path"])),
        config=config,
        git_commit=str(git_commit or "unavailable-git-identity"),
        source_kind="arc3-stage13-evaluation",
        source_version="0.1",
    )


def _apply_trace_metrics(metrics: dict[str, object], trace: dict[str, object]) -> None:
    counts_value = trace.get("event_type_counts")
    counts = counts_value if isinstance(counts_value, dict) else {}
    metrics["hypothesis_creation_count"] = int(counts.get("hypothesis.created", 0))
    metrics["hypothesis_rejection_count"] = int(counts.get("hypothesis.rejected", 0))
    metrics["hypothesis_reopening_count"] = int(counts.get("hypothesis.reopened", 0))
    mismatches = int(counts.get("consequence.mismatched_prediction", 0))
    matches = int(counts.get("consequence.matched_prediction", 0))
    prediction_total = matches + mismatches
    metrics["transitions_explained_fraction"] = (
        matches / prediction_total if prediction_total else None
    )
    metrics["retrodiction_contradiction_rate"] = (
        mismatches / prediction_total if prediction_total else None
    )
    metrics["replans_caused_by_mismatch"] = mismatches
    consequence_count = cast(int, trace["consequence_count"])
    metrics["trace_bytes_per_action"] = (
        cast(int, trace["byte_length"]) / consequence_count if consequence_count else None
    )


def _worker(spec: dict[str, Any], receipt_path: str) -> None:
    started_at = _utc_now()
    started = time.perf_counter()
    tracemalloc.start()
    identity = dict(spec["identity"])
    specification = dict(spec["specification"])
    run_id = str(specification["run_id"])
    agent = str(specification["agent"])
    seed = int(specification["seed"])
    trace_path = Path(str(spec["trace_path"]))
    trace_relative = str(spec["trace_relative"])
    session = SyntheticAdapter(seed=seed).open(SYNTHETIC_GAME_ID, seed=seed)
    policy = make_evaluation_policy(
        agent,
        seed=seed,
        run_context=_full_run_context(spec) if agent == "full" else None,
    )
    baseline_journal: EventJournal | None = None
    sink: BaselineTraceSink | None = None
    if not policy.manages_trace:
        baseline_journal = EventJournal(trace_path, run_id=run_id)
        sink = BaselineTraceSink(
            journal=baseline_journal,
            episode_id=f"episode:{run_id}",
            source=SourceIdentity(
                "synthetic_environment",
                "arc3.synthetic.v1",
                {"baseline_id": specification["baseline_id"]},
            ),
            code_identity=CodeIdentity(
                str(identity.get("git_commit") or "unavailable-git-identity"),
                str(identity["config_hash"]),
                {"first_party_source_hash": identity["first_party_source_hash"]},
            ),
        )
    observation = session.observation
    state_visits = [f"{observation.state.value}:{observation.frames[-1].digest}"]
    no_op_keys: set[tuple[str, str]] = set()
    repeated_no_ops = 0
    invalid_actions = 0
    coordinate_actions = 0
    coordinate_hits = 0
    resets = 0
    game_over_events = 0
    environment_actions = 0
    first_progress: float | None = None
    actions_first_completed: int | None = None
    latencies: list[float] = []
    scorecard: ScoreSummary | None = None
    caught: Exception | None = None
    trace: dict[str, object] | None = None
    if sink is not None:
        sink.record_observation(observation)
    try:
        while environment_actions < int(specification["max_actions"]):
            if observation.state is GameStateName.WIN:
                break
            if sink is not None:
                sink.record_candidates(observation)
            decision_started = time.perf_counter()
            action = policy.select(observation)
            latencies.append(time.perf_counter() - decision_started)
            if sink is not None:
                sink.record_selected(observation, action)
            if action.name is ActionName.RESET and resets >= int(specification["max_resets"]):
                break
            before = observation
            if sink is not None:
                sink.record_submitted(before, action)
            try:
                observation = session.step(
                    action,
                    reasoning={
                        "category": "stage13-evaluation",
                        "summary": "typed policy selection recorded in immutable trace",
                    },
                )
            except Exception:
                invalid_actions += 1
                raise
            policy.accept_consequence(observation)
            if sink is not None:
                sink.record_consequence(before, action, observation)
                sink.record_observation(observation)
            if action.name is ActionName.RESET:
                resets += 1
            else:
                environment_actions += 1
            before_hash = str(before.frames[-1].digest)
            after_hash = str(observation.frames[-1].digest)
            changed = (
                before_hash != after_hash or observation.levels_completed > before.levels_completed
            )
            if not changed and action.name is not ActionName.RESET:
                key = (before_hash, repr(action))
                if key in no_op_keys:
                    repeated_no_ops += 1
                no_op_keys.add(key)
            if action.name is ActionName.ACTION6:
                coordinate_actions += 1
                coordinate_hits += int(changed)
            if observation.state is GameStateName.GAME_OVER:
                game_over_events += 1
            if observation.levels_completed > before.levels_completed and first_progress is None:
                first_progress = time.perf_counter() - started
                actions_first_completed = environment_actions
            state_visits.append(f"{observation.state.value}:{after_hash}")
        scorecard = session.close()
    except Exception as error:
        caught = error
    finally:
        try:
            policy.close()
        except Exception as error:
            caught = caught or error
        if baseline_journal is not None:
            try:
                baseline_journal.close()
            except Exception as error:
                caught = caught or error
        try:
            if trace_path.is_dir():
                trace = _trace_receipt(trace_path, run_id=run_id, relative_path=trace_relative)
        except (OSError, TraceError, ValueError) as error:
            caught = caught or error
        _current, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
    duration = time.perf_counter() - started
    metrics = _empty_metrics()
    unique_states = len(set(state_visits))
    metrics.update(
        {
            "environment_actions": environment_actions,
            "resets": resets,
            "game_over_events": game_over_events,
            "time_to_first_progress_seconds": first_progress,
            "actions_to_first_completed_level": actions_first_completed,
            "repeated_no_op_rate": repeated_no_ops / environment_actions
            if environment_actions
            else 0.0,
            "invalid_action_rate": invalid_actions / max(1, environment_actions + invalid_actions),
            "coordinate_action_hit_rate": coordinate_hits / coordinate_actions
            if coordinate_actions
            else None,
            "unique_state_count": unique_states,
            "state_revisitation_rate": (len(state_visits) - unique_states) / len(state_visits),
            "peak_ram_bytes": peak,
            "decision_latency_seconds": {
                "p50": _percentile(latencies, 0.50),
                "p95": _percentile(latencies, 0.95),
                "p99": _percentile(latencies, 0.99),
            },
            "total_wall_clock_seconds": duration,
        }
    )
    if trace is not None:
        _apply_trace_metrics(metrics, trace)
    if caught is not None or scorecard is None:
        result = _failure_result(
            specification=specification,
            identity=identity,
            started_at=started_at,
            completed_at=_utc_now(),
            status="failure",
            kind=type(caught).__name__ if caught is not None else "missing_scorecard",
            message=(str(caught)[:500] if caught is not None else "session returned no scorecard"),
            trace=trace,
            metrics=metrics,
        )
    else:
        result = seal_object(
            {
                "schema": "arc3.evaluation.run.v0.1",
                "evaluation_id": specification["evaluation_id"],
                "run_id": run_id,
                "baseline_id": specification["baseline_id"],
                "agent": agent,
                "seed": seed,
                "run_spec_hash": specification["run_spec_hash"],
                "surface": "synthetic",
                "partition": "smoke",
                "status": "success",
                "started_at": started_at,
                "completed_at": _utc_now(),
                "identity": identity,
                "score": _score_payload(scorecard),
                "metrics": metrics,
                "trace": trace,
                "failure": None,
            },
            hash_field="receipt_hash",
        )
    atomic_write_json(Path(receipt_path), result)


def _evaluation_id(config: EvaluationConfig, started_at: str) -> str:
    if config.evaluation_id is not None:
        return config.evaluation_id
    digest = hashlib.sha256(canonical_json_bytes(config.declaration())).hexdigest()[:12]
    compact_time = "".join(character for character in started_at if character.isalnum())
    return f"eval-{compact_time}-{digest}"


def _receipt_matches(
    directory: Path,
    receipt: dict[str, Any],
    specification: dict[str, object],
    identity: dict[str, object],
    *,
    verify_trace: bool = True,
) -> bool:
    return not run_receipt_errors(
        directory,
        receipt,
        specification,
        identity,
        verify_trace=verify_trace,
    )


def _preserve_invalid_receipt(receipt_path: Path, failures_directory: Path) -> None:
    destination = failures_directory / (
        f"{receipt_path.stem}.invalid-{uuid.uuid4().hex}{receipt_path.suffix}"
    )
    receipt_path.replace(destination)


def _preserve_invalid_attempt_directory(
    path: Path,
    failures_directory: Path,
    *,
    category: str,
    storage_key: str,
) -> None:
    """Move prior mutable attempt state aside before rerunning a rejected receipt."""

    if not path.exists():
        return
    destination_root = failures_directory / category
    destination_root.mkdir(parents=True, exist_ok=True)
    destination = destination_root / f"{storage_key}.invalid-{uuid.uuid4().hex}"
    path.replace(destination)


def _collect_receipts(
    runs_directory: Path,
    specifications: list[dict[str, object]],
    identity: dict[str, object],
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for specification in specifications:
        path = runs_directory / f"{specification['run_id']}.json"
        receipt = load_json(path)
        if not _receipt_matches(
            runs_directory.parent,
            receipt,
            specification,
            identity,
            verify_trace=False,
        ):
            raise EvaluationError(f"run receipt failed final validation: {specification['run_id']}")
        results.append(receipt)
    return sorted(results, key=lambda result: str(result["run_id"]))


def _shell_command(argv: list[str]) -> str:
    if os.name == "nt":
        return subprocess.list2cmdline(argv)
    return shlex.join(argv)


def _reproduction_argv(config: EvaluationConfig) -> list[str]:
    return [
        sys.executable,
        "-m",
        "arc3",
        "evaluate",
        "--partition",
        config.partition,
        "--agents",
        ",".join(config.agents),
        "--seeds",
        ",".join(str(seed) for seed in config.seeds),
        "--max-actions",
        str(config.max_actions),
        "--max-resets",
        str(config.max_resets),
        "--timeout-seconds",
        str(config.timeout_seconds),
        "--output-root",
        str(config.output_root.resolve()),
    ]


def _terminal_outcome(
    directory: Path,
    manifest: dict[str, Any],
    identity: dict[str, object],
) -> EvaluationOutcome:
    verification = verify_evaluation_artifacts(directory)
    if not verification["verified"]:
        raw_errors = verification.get("errors")
        error_items = raw_errors if isinstance(raw_errors, list) else [raw_errors]
        errors = "; ".join(str(item) for item in error_items)
        raise EvaluationError(f"refusing to reopen a tampered terminal evaluation: {errors}")
    if manifest.get("identity_hash") != identity.get("identity_hash"):
        raise EvaluationError(
            "evaluation_id belongs to a different code/config/runtime identity; use a new ID"
        )
    summary = load_json(directory / "summary.json")
    return EvaluationOutcome(
        str(manifest["evaluation_id"]),
        directory.resolve(),
        str(manifest["status"]),
        summary,
    )


def run_evaluation(config: EvaluationConfig) -> EvaluationOutcome:
    """Execute or integrity-check a process-isolated synthetic evaluation."""

    for agent in config.agents:
        baseline_descriptor(agent)
    started_at = _utc_now()
    evaluation_id = _evaluation_id(config, started_at)
    directory = config.output_root / evaluation_id
    runs_directory = directory / "runs"
    failures_directory = directory / "failures"
    traces_directory = directory / "t"
    checkpoints_directory = directory / "c"
    identity = _identity(config)
    specifications = [
        _run_specification(evaluation_id, agent, seed, config, identity)
        for agent in config.agents
        for seed in config.seeds
    ]
    expected_run_ids = {str(item["run_id"]) for item in specifications}
    manifest_path = directory / "manifest.json"
    if manifest_path.exists():
        previous = load_json(manifest_path)
        if not verify_object_hash(previous, hash_field="manifest_hash"):
            raise EvaluationError("evaluation manifest self-hash mismatch")
        if previous.get("status") in _TERMINAL_EVALUATION_STATUSES:
            return _terminal_outcome(directory, previous, identity)
        if previous.get("status") != "IN_PROGRESS":
            raise EvaluationError("evaluation manifest status is neither resumable nor terminal")
        if previous.get("identity_hash") != identity["identity_hash"]:
            raise EvaluationError("cannot resume an evaluation under a different identity")
        if previous.get("expected_runs") != specifications:
            raise EvaluationError("cannot resume an evaluation with a different run declaration")
        original_started = previous.get("started_at")
        if isinstance(original_started, str):
            started_at = original_started
    elif directory.exists() and any(directory.iterdir()):
        raise EvaluationError("evaluation directory has artifacts but no sealed manifest")
    runs_directory.mkdir(parents=True, exist_ok=True)
    failures_directory.mkdir(parents=True, exist_ok=True)
    traces_directory.mkdir(parents=True, exist_ok=True)
    checkpoints_directory.mkdir(parents=True, exist_ok=True)
    unexpected = {
        path.stem for path in runs_directory.glob("*.json") if path.stem not in expected_run_ids
    }
    if unexpected:
        raise EvaluationError(f"evaluation contains undeclared run receipts: {sorted(unexpected)}")
    required_artifacts = sorted(
        {
            "results.jsonl",
            "summary.json",
            "report.md",
            "reproduce.json",
            "reproduce.txt",
            *(f"runs/{run_id}.json" for run_id in expected_run_ids),
        }
    )
    manifest: dict[str, Any] = {
        "schema": "arc3.evaluation.manifest.v0.1",
        "evaluation_id": evaluation_id,
        "status": "IN_PROGRESS",
        "surface": "synthetic",
        "verified": True,
        "verified_meaning": "first-party deterministic synthetic adapter",
        "scorer_source_version": "adapter ScoreSummary; arc3.synthetic.v1",
        "human_baselines_available": False,
        "public_game_derived_memory_or_tuning": False,
        "aggregate": True,
        "partition": config.partition,
        **identity,
        "started_at": started_at,
        "completed_at": None,
        "expected_runs": specifications,
        "required_artifacts": required_artifacts,
        "artifact_hashes": {},
        "process_isolation": "multiprocessing-spawn",
        "resume_policy": (
            "terminal evaluations are immutable; in-progress receipts are reused only after "
            "self-hash, run declaration, and full identity validation"
        ),
    }
    atomic_write_json(manifest_path, seal_object(manifest, hash_field="manifest_hash"))
    context = multiprocessing.get_context("spawn")
    for specification in specifications:
        run_id = str(specification["run_id"])
        agent = str(specification["agent"])
        storage_key = _storage_key(run_id)
        trace_path = traces_directory / storage_key
        checkpoint_path = checkpoints_directory / storage_key
        receipt_path = runs_directory / f"{run_id}.json"
        failure_path = failures_directory / f"{run_id}.json"
        if receipt_path.is_file():
            try:
                existing = load_json(receipt_path)
            except (OSError, EvaluationError, json.JSONDecodeError):
                _preserve_invalid_receipt(receipt_path, failures_directory)
            else:
                if _receipt_matches(directory, existing, specification, identity):
                    if existing.get("status") == "success":
                        if failure_path.exists():
                            _preserve_invalid_receipt(failure_path, failures_directory)
                    else:
                        retained: dict[str, Any] | None = None
                        if failure_path.is_file():
                            try:
                                retained = load_json(failure_path)
                            except (OSError, EvaluationError, json.JSONDecodeError):
                                _preserve_invalid_receipt(failure_path, failures_directory)
                        if retained != existing:
                            if failure_path.exists():
                                _preserve_invalid_receipt(failure_path, failures_directory)
                            atomic_write_json(failure_path, existing)
                    continue
                _preserve_invalid_receipt(receipt_path, failures_directory)
        if failure_path.exists():
            _preserve_invalid_receipt(failure_path, failures_directory)
        _preserve_invalid_attempt_directory(
            trace_path,
            failures_directory,
            category="traces",
            storage_key=storage_key,
        )
        _preserve_invalid_attempt_directory(
            checkpoint_path,
            failures_directory,
            category="checkpoints",
            storage_key=storage_key,
        )
        descriptor = baseline_descriptor(agent)
        if descriptor.status != "supported":
            moment = _utc_now()
            result = _failure_result(
                specification=specification,
                identity=identity,
                started_at=moment,
                completed_at=moment,
                status="unsupported",
                kind="unsupported_baseline",
                message=descriptor.limitation or "baseline is not implemented",
            )
            atomic_write_json(receipt_path, result)
            atomic_write_json(failures_directory / f"{run_id}.json", result)
            continue
        trace_relative = f"t/{storage_key}"
        spec = {
            "identity": identity,
            "specification": specification,
            "trace_path": str(_runtime_path(trace_path)),
            "trace_relative": trace_relative,
            "checkpoint_path": str(_runtime_path(checkpoint_path)),
            "timeout_seconds": config.timeout_seconds,
        }
        launched_at = _utc_now()
        launched_timer = time.perf_counter()
        process = context.Process(target=_worker, args=(spec, str(receipt_path)))
        try:
            process.start()
        except (OSError, RuntimeError) as error:
            metrics = _empty_metrics()
            metrics["total_wall_clock_seconds"] = time.perf_counter() - launched_timer
            result = _failure_result(
                specification=specification,
                identity=identity,
                started_at=launched_at,
                completed_at=_utc_now(),
                status="failure",
                kind="process_start_failed",
                message=f"{type(error).__name__}: {error}"[:500],
                metrics=metrics,
            )
            atomic_write_json(receipt_path, result)
            atomic_write_json(failures_directory / f"{run_id}.json", result)
            continue
        process.join(config.timeout_seconds)
        forced_status: tuple[str, str, str] | None = None
        if process.is_alive():
            process.terminate()
            process.join(5)
            if process.is_alive():
                process.kill()
                process.join(5)
            forced_status = (
                "timeout",
                "wall_clock_timeout",
                f"worker exceeded {config.timeout_seconds} seconds",
            )
        elif process.exitcode != 0:
            forced_status = (
                "crash",
                "abnormal_process_exit",
                f"isolated worker exited with code {process.exitcode}",
            )
        elif not receipt_path.is_file():
            forced_status = (
                "failure",
                "missing_worker_receipt",
                "isolated worker exited successfully without a terminal receipt",
            )
        if forced_status is not None:
            if receipt_path.is_file():
                _preserve_invalid_receipt(receipt_path, failures_directory)
            trace: dict[str, object] | None = None
            trace_path = _runtime_path(directory / trace_relative)
            try:
                if trace_path.is_dir():
                    trace = _trace_receipt(
                        trace_path,
                        run_id=run_id,
                        relative_path=trace_relative,
                    )
            except (OSError, TraceError, ValueError):
                trace = None
            status, kind, message = forced_status
            metrics = _empty_metrics()
            metrics["total_wall_clock_seconds"] = time.perf_counter() - launched_timer
            result = _failure_result(
                specification=specification,
                identity=identity,
                started_at=launched_at,
                completed_at=_utc_now(),
                status=status,
                kind=kind,
                message=message,
                trace=trace,
                metrics=metrics,
            )
            atomic_write_json(receipt_path, result)
            atomic_write_json(failures_directory / f"{run_id}.json", result)
            continue
        try:
            result = load_json(receipt_path)
        except (OSError, EvaluationError, json.JSONDecodeError) as error:
            _preserve_invalid_receipt(receipt_path, failures_directory)
            metrics = _empty_metrics()
            metrics["total_wall_clock_seconds"] = time.perf_counter() - launched_timer
            result = _failure_result(
                specification=specification,
                identity=identity,
                started_at=launched_at,
                completed_at=_utc_now(),
                status="failure",
                kind="invalid_worker_receipt",
                message=f"{type(error).__name__}: {error}"[:500],
                metrics=metrics,
            )
            atomic_write_json(receipt_path, result)
        if not _receipt_matches(directory, result, specification, identity):
            _preserve_invalid_receipt(receipt_path, failures_directory)
            metrics = _empty_metrics()
            metrics["total_wall_clock_seconds"] = time.perf_counter() - launched_timer
            result = _failure_result(
                specification=specification,
                identity=identity,
                started_at=launched_at,
                completed_at=_utc_now(),
                status="failure",
                kind="worker_receipt_identity_mismatch",
                message="worker receipt failed its self-hash or declared run identity",
                metrics=metrics,
            )
            atomic_write_json(receipt_path, result)
        if result.get("status") != "success":
            atomic_write_json(failures_directory / f"{run_id}.json", result)
    results = _collect_receipts(runs_directory, specifications, identity)
    results_path = directory / "results.jsonl"
    atomic_write_bytes(results_path, b"".join(canonical_json_bytes(result) for result in results))
    summary = build_summary(evaluation_id, results)
    regression = evaluate_performance_thresholds(results, declaration=config.declaration())
    summary["performance_regression"] = regression
    if regression["status"] == "FAIL":
        summary["status"] = "FAILED_INFRASTRUCTURE"
    summary_path = directory / "summary.json"
    atomic_write_json(summary_path, summary)
    argv = _reproduction_argv(config)
    reproduce_json_path = directory / "reproduce.json"
    atomic_write_json(
        reproduce_json_path,
        {
            "schema": "arc3.evaluation.reproduction.v0.1",
            "argv": argv,
            "working_directory": str(_repository_root()),
            "note": "evaluation_id is intentionally omitted so reproduction creates new evidence",
        },
    )
    reproduce_path = directory / "reproduce.txt"
    atomic_write_text(reproduce_path, _shell_command(argv) + "\n")
    completed_at = _utc_now()
    manifest.update(
        {
            "status": summary["status"],
            "completed_at": completed_at,
        }
    )
    pre_report_paths = [
        path
        for path in directory.rglob("*")
        if path.is_file()
        and path.relative_to(directory).as_posix() != "manifest.json"
        and path.relative_to(directory).as_posix() != "report.md"
    ]
    manifest["artifact_hashes"] = {
        path.relative_to(directory).as_posix(): sha256_file(path) for path in pre_report_paths
    }
    report_path = directory / "report.md"
    atomic_write_text(report_path, render_markdown(manifest, summary, results))
    artifact_paths = [
        path
        for path in directory.rglob("*")
        if path.is_file() and path.relative_to(directory).as_posix() != "manifest.json"
    ]
    manifest["artifact_hashes"] = {
        path.relative_to(directory).as_posix(): sha256_file(path) for path in artifact_paths
    }
    sealed_manifest = seal_object(manifest, hash_field="manifest_hash")
    atomic_write_json(manifest_path, sealed_manifest)
    verification = verify_evaluation_artifacts(directory)
    if not verification["verified"]:
        raw_errors = verification.get("errors")
        error_items = raw_errors if isinstance(raw_errors, list) else [raw_errors]
        errors = "; ".join(str(item) for item in error_items)
        raise EvaluationError(f"new evaluation failed final artifact verification: {errors}")
    return EvaluationOutcome(evaluation_id, directory.resolve(), str(summary["status"]), summary)


__all__ = ["run_evaluation"]
