"""Run Stage 16 controller profiling and robustness checks in fresh processes."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


def _sealed(value: Mapping[str, object]) -> dict[str, object]:
    body = dict(value)
    body["receipt_sha256"] = _sha256_bytes(_canonical_bytes(body))
    return body


def _atomic_write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(_canonical_bytes(value) + b"\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _load_object(path: Path) -> dict[str, Any]:
    loaded: object = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError(f"expected JSON object in {path}")
    return cast(dict[str, Any], loaded)


def _frozen_runtime_defaults() -> dict[str, Any]:
    path = Path(__file__).resolve().parents[1] / "src" / "arc3" / "competition-runtime.v0.1.json"
    raw = _load_object(path)
    claimed = raw.get("configuration_sha256")
    body = {key: value for key, value in raw.items() if key != "configuration_sha256"}
    if claimed != _sha256_bytes(_canonical_bytes(body)):
        raise ValueError("frozen competition runtime configuration hash mismatch")
    return raw


def _git_text(root: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ("git", *arguments),
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=10,
    )
    return completed.stdout.strip()


def _git_source_identity(root: Path, expected_commit: str) -> dict[str, object]:
    """Resolve the exact clean commit/tree that the profile is permitted to measure."""

    try:
        commit = _git_text(root, "rev-parse", "HEAD")
        tree = _git_text(root, "rev-parse", "HEAD^{tree}")
        dirty_output = _git_text(root, "status", "--porcelain=v1", "--untracked-files=all")
    except (OSError, subprocess.SubprocessError) as error:
        raise RuntimeError("unable to resolve frozen Git source identity") from error
    dirty_paths = [line[3:] for line in dirty_output.splitlines() if len(line) > 3]
    verified = bool(commit and tree) and not dirty_paths and commit == expected_commit
    return {
        "actual_commit": commit,
        "clean_worktree": not dirty_paths,
        "dirty_paths": dirty_paths,
        "expected_commit": expected_commit,
        "tree": tree,
        "verified": verified,
    }


def _accelerator_disposition() -> dict[str, object]:
    executable = shutil.which("nvidia-smi")
    availability: dict[str, object] = {
        "nvidia_smi_available": executable is not None,
        "nvidia_smi_query": None,
    }
    if executable is not None:
        try:
            probe = subprocess.run(
                (
                    executable,
                    "--query-gpu=name,driver_version,memory.total",
                    "--format=csv,noheader,nounits",
                ),
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=5,
            )
            availability["nvidia_smi_query"] = (
                probe.stdout.strip().splitlines() if probe.returncode == 0 else []
            )
            availability["probe_exit_code"] = probe.returncode
        except (OSError, subprocess.SubprocessError) as error:
            availability["probe_error"] = type(error).__name__
    return {
        "availability_probe": availability,
        "execution_backend": "cpu",
        "justification": (
            "The production controller is symbolic/CPU-bound and has no accelerator runtime "
            "dependency; no measured GPU mechanism was available to justify a mandatory path."
        ),
        "used": False,
    }


def _failure_receipt(
    *,
    boundary: str,
    git_commit: str | None,
    kind: str,
    message: str | None = None,
    source_identity: Mapping[str, object] | None = None,
    timeout_seconds: float | None = None,
) -> dict[str, object]:
    failure: dict[str, object] = {"boundary": boundary, "kind": kind}
    if message is not None:
        failure["message"] = message[:500]
    if timeout_seconds is not None:
        failure["timeout_seconds"] = timeout_seconds
    return _sealed(
        {
            "claim": "NO_GENERALIZATION_CLAIM",
            "completed_at": _utc_now(),
            "failure": failure,
            "git_commit": git_commit,
            "label": "synthetic",
            "schema": "arc3.stage16.profile.v0.1",
            "source_identity": dict(source_identity) if source_identity is not None else None,
            "status": "FAILED_INFRASTRUCTURE",
            "verified": False,
        }
    )


def _sanitized_environment(repository: Path) -> dict[str, str]:
    blocked_parts = ("API_KEY", "TOKEN", "PASSWORD", "SECRET", "KAGGLE")
    blocked_names = {
        "ARC_API_KEY",
        "ARC3_NETWORK_ENABLED",
        "PYTHONHOME",
        "PYTHONPATH",
        "VIRTUAL_ENV",
    }
    result = {
        key: value
        for key, value in os.environ.items()
        if not any(part in key.upper() for part in blocked_parts)
        and key.upper() not in blocked_names
    }
    result["ARC3_NETWORK_ENABLED"] = "false"
    result["PYTHONHASHSEED"] = "0"
    result["PYTHONNOUSERSITE"] = "1"
    result["PYTHONPATH"] = os.pathsep.join((str(repository / "src"), str(repository)))
    return result


def _worker(config_path: Path) -> int:
    import arc3
    from arc3.competition_runtime import FROZEN_COMPETITION_RUNTIME
    from arc3.integrity import build_integrity_receipt
    from arc3.policy import ControllerPreset
    from arc3.profiling import (
        RuntimeProfileConfig,
        run_fault_matrix,
        run_robustness_suite,
        run_runtime_profile,
    )
    from arc3.profiling.regression import run_stage13_regression

    config = _load_object(config_path)
    repository = Path(str(config["repository"])).resolve()
    work_root = Path(str(config["work_root"])).resolve()
    output = Path(str(config["worker_output"])).resolve()
    git_commit = str(config["git_commit"])
    imported_arc3 = Path(str(arc3.__file__)).resolve()
    expected_arc3_root = (repository / "src" / "arc3").resolve()
    import_identity = {
        "arc3_module": str(imported_arc3),
        "expected_root": str(expected_arc3_root),
        "verified": imported_arc3.is_relative_to(expected_arc3_root),
    }
    if import_identity["verified"] is not True:
        raise RuntimeError("worker imported arc3 outside the clean frozen repository")
    expected_source = config.get("source_identity")
    if not isinstance(expected_source, dict):
        raise ValueError("worker source identity must be an object")
    worker_source_start = _git_source_identity(repository, git_commit)
    if worker_source_start["verified"] is not True or worker_source_start[
        "tree"
    ] != expected_source.get("tree"):
        raise RuntimeError("worker source does not match the clean frozen parent source")
    profile_config = RuntimeProfileConfig(
        seed=int(config["seed"]),
        frame_size=int(config["frame_size"]),
        fixture=str(config["fixture"]),
        component_count=int(config["component_count"]),
        max_actions=int(config["max_actions"]),
        max_resets=int(config["max_resets"]),
        restart_every=int(config["restart_every"]),
        decision_seconds=float(config["decision_seconds"]),
        wall_clock_seconds=float(config["wall_clock_seconds"]),
        memory_megabytes=int(config["memory_megabytes"]),
        max_trace_bytes=int(config["max_trace_bytes"]),
        max_checkpoint_bytes=int(config["max_checkpoint_bytes"]),
        max_coordinate_candidates=int(config["max_coordinate_candidates"]),
        max_search_nodes=int(config["max_search_nodes"]),
        max_search_depth=int(config["max_search_depth"]),
    )
    raw_robustness_seeds = config["robustness_seeds"]
    if not isinstance(raw_robustness_seeds, list) or any(
        isinstance(value, bool) or not isinstance(value, int) for value in raw_robustness_seeds
    ):
        raise ValueError("worker robustness seeds must be an integer array")
    robustness_seeds = tuple(value for value in raw_robustness_seeds if isinstance(value, int))
    runtime = run_runtime_profile(
        work_root / "runtime",
        config=profile_config,
        git_commit=git_commit,
        preset=ControllerPreset.COMPETITION,
    )
    robustness = run_robustness_suite(
        work_root / "robustness",
        seeds=robustness_seeds,
        max_actions=int(config["robustness_actions"]),
        wall_clock_seconds=float(config["robustness_wall_clock_seconds"]),
        git_commit=git_commit,
        preset=ControllerPreset.COMPETITION,
    )
    faults = run_fault_matrix(work_root / "faults", git_commit=git_commit)
    regression: dict[str, object] | None = None
    if bool(config["run_regression"]):
        regression = cast(
            dict[str, object],
            run_stage13_regression(
                repository,
                work_root / "stage13-regression",
                git_commit=git_commit,
            ),
        )
    integrity: dict[str, object] | None = None
    if bool(config["run_integrity"]):
        receipt = build_integrity_receipt(repository)
        integrity = {**receipt.body, "receipt_sha256": receipt.receipt_sha256}
    runtime_passed = runtime["verified"] is True
    robustness_passed = robustness["verified"] is True
    faults_passed = faults["verified"] is True
    integrity_passed = integrity is None or integrity["passed"] is True
    regression_passed = regression is None or regression["verified"] is True
    known_gaps = list(cast(list[object], faults["known_input_gaps"]))
    if regression is None:
        known_gaps.append("Stage 13 regression rerun was explicitly skipped")
    if integrity is None:
        known_gaps.append("static integrity scan was explicitly skipped")
    frozen_budget = FROZEN_COMPETITION_RUNTIME.to_dict()
    competition_envelope = {
        "decision_seconds": profile_config.decision_seconds,
        "max_actions": profile_config.max_actions,
        "max_checkpoint_bytes": profile_config.max_checkpoint_bytes,
        "max_coordinate_candidates": profile_config.max_coordinate_candidates,
        "max_resets": profile_config.max_resets,
        "max_search_depth": profile_config.max_search_depth,
        "max_search_nodes": profile_config.max_search_nodes,
        "max_trace_bytes": profile_config.max_trace_bytes,
        "memory_megabytes": profile_config.memory_megabytes,
        "per_game_wall_clock_seconds": profile_config.wall_clock_seconds,
    }
    expected_envelope = {key: frozen_budget[key] for key in competition_envelope}
    competition_envelope_verified = competition_envelope == expected_envelope
    if not competition_envelope_verified:
        known_gaps.append("runtime profile used a reduced/non-competition measurement envelope")
    if config["outer_timeout_coherent"] is not True:
        known_gaps.append("outer worker timeout is shorter than the declared worst-case envelope")
    mechanism_passed = all(
        (
            runtime_passed,
            robustness_passed,
            faults_passed,
            integrity_passed,
            regression_passed,
        )
    )
    worker_source_end = _git_source_identity(repository, git_commit)
    source_identity = {
        "parent": expected_source,
        "verified": (
            worker_source_start["verified"] is True
            and worker_source_end["verified"] is True
            and worker_source_start["tree"] == worker_source_end["tree"] == expected_source["tree"]
        ),
        "worker_end": worker_source_end,
        "worker_start": worker_source_start,
    }
    if source_identity["verified"] is not True:
        raise RuntimeError("source identity changed while the worker was measuring")
    worker_verified = mechanism_passed and not known_gaps
    body: dict[str, object] = {
        "claim": "NO_GENERALIZATION_CLAIM",
        "completed_at": _utc_now(),
        "competition_runtime": FROZEN_COMPETITION_RUNTIME.to_dict(),
        "competition_runtime_match": competition_envelope_verified,
        "fault_matrix": faults,
        "git_commit": git_commit,
        "first_party_import_identity": import_identity,
        "integrity": integrity,
        "label": "synthetic",
        "network_enforcement": (
            "competition configuration plus static reachability scan; "
            "OS-level socket denial is not claimed"
        ),
        "profile": runtime,
        "regression": regression,
        "robustness": robustness,
        "schema": "arc3.stage16.profile.v0.1",
        "status": (
            "FAILED_MECHANISM" if not mechanism_passed else "PARTIAL" if known_gaps else "PASS"
        ),
        "source_identity": source_identity,
        "worker_timeout": {
            "coherent": config["outer_timeout_coherent"],
            "declared_minimum_seconds": config["declared_minimum_worker_timeout_seconds"],
            "outer_seconds": config["worker_timeout_seconds"],
        },
        "verified": worker_verified,
    }
    _atomic_write(output, _sealed(body))
    return 0 if worker_verified else 1


def _worker_entry(config_path: Path) -> int:
    """Seal an infrastructure receipt even when the inner worker raises."""

    try:
        return _worker(config_path)
    except Exception as error:  # subprocess boundary must retain unexpected failures
        try:
            config = _load_object(config_path)
            output = Path(str(config["worker_output"])).resolve()
            raw_source = config.get("source_identity")
            source_identity = raw_source if isinstance(raw_source, dict) else None
            if not output.exists():
                _atomic_write(
                    output,
                    _failure_receipt(
                        boundary="profile-worker-internal",
                        git_commit=str(config.get("git_commit") or "unavailable-git-identity"),
                        kind=type(error).__name__,
                        message=str(error),
                        source_identity=source_identity,
                    ),
                )
        except (KeyError, OSError, ValueError):
            pass
        sys.stderr.write(f"Stage 16 worker failed: {type(error).__name__}: {error}\n")
        return 2


def _startup_worker(root: Path, git_commit: str) -> int:
    started = time.perf_counter()
    from arc3.adapters.synthetic import SYNTHETIC_GAME_ID, SyntheticAdapter
    from arc3.config import ARC3Config, BudgetConfig
    from arc3.policy import ARC3Controller, ControllerPreset, RunContext
    from arc3.profiling import process_memory_sample
    from arc3.types import EnvironmentMode

    imports_completed = time.perf_counter()
    session = SyntheticAdapter(seed=7, size=8, max_steps=32).open(SYNTHETIC_GAME_ID)
    controller = ARC3Controller(ControllerPreset.COMPETITION)
    context = RunContext(
        run_id="stage16-startup",
        episode_id="stage16-startup-episode",
        game_id=SYNTHETIC_GAME_ID,
        trace_root=root / "trace",
        checkpoint_root=root / "checkpoint",
        config=ARC3Config(
            mode=EnvironmentMode.COMPETITION,
            seed=7,
            network_enabled=False,
            profile="stage16-startup",
            budgets=BudgetConfig(max_actions=4, max_resets=1),
        ),
        git_commit=git_commit,
        source_kind="arc3-stage16-startup",
        source_version="0.1",
    )
    controller.reset(context)
    controller.observe(session.observation)
    ready = time.perf_counter()
    result = {
        "controller_initialize_and_first_observe_seconds": ready - imports_completed,
        "first_party_import_through_ready_seconds": ready - started,
        "memory_at_ready": process_memory_sample(),
        "phase_at_ready": controller.phase.value,
        "trace_events_at_ready": controller.snapshot.trace_events,
    }
    controller.close()
    session.close()
    sys.stdout.buffer.write(_canonical_bytes(result) + b"\n")
    return 0


def _parser() -> argparse.ArgumentParser:
    frozen = _frozen_runtime_defaults()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, default=Path("artifacts/stage16/profile.json"))
    parser.add_argument("--work-root", type=Path)
    parser.add_argument("--frozen-commit")
    parser.add_argument("--seed", type=int, default=25)
    parser.add_argument("--frame-size", type=int, default=32)
    parser.add_argument(
        "--fixture", choices=("component-stress", "navigation"), default="component-stress"
    )
    parser.add_argument("--component-count", type=int, default=64)
    parser.add_argument("--max-actions", type=int, default=int(frozen["max_actions"]))
    parser.add_argument("--max-resets", type=int, default=int(frozen["max_resets"]))
    parser.add_argument("--restart-every", type=int, default=8)
    parser.add_argument("--decision-seconds", type=float, default=float(frozen["decision_seconds"]))
    parser.add_argument(
        "--wall-clock-seconds",
        type=float,
        default=float(frozen["per_game_wall_clock_seconds"]),
    )
    parser.add_argument("--memory-megabytes", type=int, default=int(frozen["memory_megabytes"]))
    parser.add_argument("--max-trace-bytes", type=int, default=int(frozen["max_trace_bytes"]))
    parser.add_argument(
        "--max-checkpoint-bytes",
        type=int,
        default=int(frozen["max_checkpoint_bytes"]),
    )
    parser.add_argument(
        "--max-coordinate-candidates",
        type=int,
        default=int(frozen["max_coordinate_candidates"]),
    )
    parser.add_argument("--max-search-nodes", type=int, default=int(frozen["max_search_nodes"]))
    parser.add_argument("--max-search-depth", type=int, default=int(frozen["max_search_depth"]))
    parser.add_argument("--robustness-seeds", default="7,11")
    parser.add_argument("--robustness-actions", type=int, default=16)
    parser.add_argument("--robustness-wall-clock-seconds", type=float, default=60.0)
    parser.add_argument("--worker-timeout-seconds", type=float, default=1800.0)
    parser.add_argument("--skip-integrity", action="store_true")
    parser.add_argument("--skip-regression", action="store_true")
    parser.add_argument("--worker-config", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--startup-worker-root", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--git-commit", help=argparse.SUPPRESS)
    return parser


def _parse_seeds(value: str) -> list[int]:
    seeds = [int(item.strip()) for item in value.split(",") if item.strip()]
    if not seeds:
        raise ValueError("robustness seeds must not be empty")
    if any(not -(2**63) <= seed < 2**63 for seed in seeds):
        raise ValueError("robustness seeds must be signed 64-bit integers")
    return seeds


def _run_parent(args: argparse.Namespace) -> int:
    repository = args.root.resolve()
    output = args.output if args.output.is_absolute() else repository / args.output
    output = output.resolve()
    if output.exists():
        raise FileExistsError(f"refusing to overwrite existing profile receipt: {output}")
    if not isinstance(args.frozen_commit, str) or not args.frozen_commit:
        _atomic_write(
            output,
            _failure_receipt(
                boundary="source-identity",
                git_commit=None,
                kind="missing-frozen-commit",
            ),
        )
        raise RuntimeError("--frozen-commit is required for a Stage 16 profile")
    try:
        source_identity = _git_source_identity(repository, args.frozen_commit)
    except RuntimeError as error:
        _atomic_write(
            output,
            _failure_receipt(
                boundary="source-identity",
                git_commit=None,
                kind="git-identity-unavailable",
                message=str(error),
            ),
        )
        raise
    git_commit = str(source_identity["actual_commit"])
    if source_identity["verified"] is not True:
        _atomic_write(
            output,
            _failure_receipt(
                boundary="source-identity",
                git_commit=git_commit,
                kind="dirty-or-mismatched-source",
                source_identity=source_identity,
            ),
        )
        raise RuntimeError("Stage 16 profiles require the named clean frozen commit")
    work_root = (
        args.work_root.resolve()
        if args.work_root is not None
        else output.parent / f"stage16-work-{uuid.uuid4().hex}"
    )
    work_root.mkdir(parents=True, exist_ok=False)
    script = Path(__file__).resolve()
    environment = _sanitized_environment(repository)

    startup_command = (
        sys.executable,
        str(script),
        "--startup-worker-root",
        str(work_root / "startup"),
        "--git-commit",
        git_commit,
    )
    startup_started = time.perf_counter()
    try:
        startup = subprocess.run(
            startup_command,
            cwd=repository,
            env=environment,
            check=False,
            capture_output=True,
            timeout=args.worker_timeout_seconds,
        )
    except subprocess.TimeoutExpired as error:
        failure = _failure_receipt(
            boundary="fresh-process-startup",
            git_commit=git_commit,
            kind="worker-timeout",
            source_identity=source_identity,
            timeout_seconds=args.worker_timeout_seconds,
        )
        _atomic_write(output, failure)
        raise RuntimeError("Stage 16 startup probe exceeded its hard subprocess timeout") from error
    startup_process_seconds = time.perf_counter() - startup_started
    if startup.returncode != 0:
        _atomic_write(
            output,
            _failure_receipt(
                boundary="fresh-process-startup",
                git_commit=git_commit,
                kind="nonzero-exit",
                message=startup.stderr.decode("utf-8", errors="replace"),
                source_identity=source_identity,
            ),
        )
        raise RuntimeError(
            "fresh-process startup probe failed: "
            + startup.stderr.decode("utf-8", errors="replace")[:500]
        )
    try:
        startup_payload: object = json.loads(startup.stdout)
    except json.JSONDecodeError as error:
        _atomic_write(
            output,
            _failure_receipt(
                boundary="fresh-process-startup",
                git_commit=git_commit,
                kind="invalid-json-receipt",
                message=str(error),
                source_identity=source_identity,
            ),
        )
        raise RuntimeError("startup probe returned invalid JSON") from error
    if not isinstance(startup_payload, dict):
        _atomic_write(
            output,
            _failure_receipt(
                boundary="fresh-process-startup",
                git_commit=git_commit,
                kind="non-object-receipt",
                source_identity=source_identity,
            ),
        )
        raise RuntimeError("startup probe returned a non-object receipt")
    startup_result = cast(dict[str, object], startup_payload)
    startup_result["fresh_process_launch_through_clean_exit_seconds"] = startup_process_seconds

    worker_output = work_root / "worker-result.json"
    worker_config = work_root / "worker-config.json"
    robustness_seeds = _parse_seeds(args.robustness_seeds)
    regression_worst_case_seconds = 0.0 if args.skip_regression else 8 * 30.0
    from arc3.profiling import RobustnessVariant

    declared_minimum_worker_timeout_seconds = (
        args.wall_clock_seconds
        + len(tuple(RobustnessVariant)) * len(robustness_seeds) * args.robustness_wall_clock_seconds
        + regression_worst_case_seconds
        + 120.0
    )
    outer_timeout_coherent = args.worker_timeout_seconds >= declared_minimum_worker_timeout_seconds
    config = {
        "component_count": args.component_count,
        "decision_seconds": args.decision_seconds,
        "declared_minimum_worker_timeout_seconds": declared_minimum_worker_timeout_seconds,
        "fixture": args.fixture,
        "frame_size": args.frame_size,
        "git_commit": git_commit,
        "max_actions": args.max_actions,
        "max_checkpoint_bytes": args.max_checkpoint_bytes,
        "max_coordinate_candidates": args.max_coordinate_candidates,
        "max_resets": args.max_resets,
        "max_search_depth": args.max_search_depth,
        "max_search_nodes": args.max_search_nodes,
        "max_trace_bytes": args.max_trace_bytes,
        "memory_megabytes": args.memory_megabytes,
        "repository": str(repository),
        "restart_every": args.restart_every,
        "robustness_actions": args.robustness_actions,
        "robustness_seeds": robustness_seeds,
        "robustness_wall_clock_seconds": args.robustness_wall_clock_seconds,
        "run_integrity": not args.skip_integrity,
        "run_regression": not args.skip_regression,
        "seed": args.seed,
        "wall_clock_seconds": args.wall_clock_seconds,
        "outer_timeout_coherent": outer_timeout_coherent,
        "source_identity": source_identity,
        "work_root": str(work_root / "worker"),
        "worker_output": str(worker_output),
        "worker_timeout_seconds": args.worker_timeout_seconds,
    }
    _atomic_write(worker_config, config)
    worker_command = (
        sys.executable,
        str(script),
        "--worker-config",
        str(worker_config),
    )
    worker_started = time.perf_counter()
    try:
        worker = subprocess.run(
            worker_command,
            cwd=repository,
            env=environment,
            check=False,
            capture_output=True,
            timeout=args.worker_timeout_seconds,
        )
    except subprocess.TimeoutExpired as error:
        failure = _failure_receipt(
            boundary="profile-worker",
            git_commit=git_commit,
            kind="worker-timeout",
            source_identity=source_identity,
            timeout_seconds=args.worker_timeout_seconds,
        )
        failure["startup"] = startup_result
        failure = _sealed({key: value for key, value in failure.items() if key != "receipt_sha256"})
        _atomic_write(output, failure)
        raise RuntimeError("Stage 16 worker exceeded its hard subprocess timeout") from error
    worker_process_seconds = time.perf_counter() - worker_started
    if not worker_output.is_file():
        _atomic_write(
            output,
            _failure_receipt(
                boundary="profile-worker",
                git_commit=git_commit,
                kind="missing-worker-receipt",
                message=worker.stderr.decode("utf-8", errors="replace"),
                source_identity=source_identity,
            ),
        )
        raise RuntimeError(
            "Stage 16 worker produced no receipt: "
            + worker.stderr.decode("utf-8", errors="replace")[:500]
        )
    try:
        result = _load_object(worker_output)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        _atomic_write(
            output,
            _failure_receipt(
                boundary="profile-worker",
                git_commit=git_commit,
                kind="invalid-worker-json-receipt",
                message=str(error),
                source_identity=source_identity,
            ),
        )
        raise RuntimeError("Stage 16 worker receipt is invalid JSON") from error
    claimed = result.pop("receipt_sha256", None)
    if claimed != _sha256_bytes(_canonical_bytes(result)):
        _atomic_write(
            output,
            _failure_receipt(
                boundary="profile-worker",
                git_commit=git_commit,
                kind="invalid-worker-receipt-hash",
                source_identity=source_identity,
            ),
        )
        raise RuntimeError("Stage 16 worker receipt hash does not verify")
    result.update(
        {
            "generated_at": _utc_now(),
            "host": {
                "cpu": platform.processor() or platform.machine() or None,
                "cpu_count": os.cpu_count(),
                "platform": platform.platform(),
                "python": platform.python_version(),
            },
            "accelerator": _accelerator_disposition(),
            "launch": {
                "fresh_process": True,
                "sanitized_credentials": True,
                "worker_exit_code": worker.returncode,
                "worker_process_seconds": worker_process_seconds,
                "worker_timeout_seconds": args.worker_timeout_seconds,
            },
            "startup": startup_result,
        }
    )
    sealed = _sealed(result)
    _atomic_write(output, sealed)
    sys.stdout.write(json.dumps(sealed, indent=2, sort_keys=True) + "\n")
    return 0 if worker.returncode == 0 and sealed.get("verified") is True else 1


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(list(argv) if argv is not None else None)
    if args.worker_config is not None:
        return _worker_entry(args.worker_config)
    if args.startup_worker_root is not None:
        return _startup_worker(
            args.startup_worker_root.resolve(),
            args.git_commit or "unavailable-git-identity",
        )
    try:
        return _run_parent(args)
    except (FileExistsError, OSError, RuntimeError, ValueError) as error:
        sys.stderr.write(f"Stage 16 profiling failed: {error}\n")
        return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
