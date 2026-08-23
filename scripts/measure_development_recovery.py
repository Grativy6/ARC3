#!/usr/bin/env python3
"""Preflight or execute the frozen Build 001 Stage 09 development matrix.

The default is a non-playing preflight.  ``--execute`` is required for the
exact 96-cell local-public matrix.  The harness never parses the public
partition manifest as metadata and has no holdout identities.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import signal
import subprocess
import sys
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, TypeGuard, cast

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from arc3.errors import EvaluationError  # noqa: E402
from arc3.evaluation.artifacts import (  # noqa: E402
    canonical_json_bytes,
    load_json,
    seal_object,
    sha256_bytes,
    sha256_file,
    verify_object_hash,
)
from arc3.evaluation.development_recovery import (  # noqa: E402
    AGGREGATE_SCHEMA,
    CELL_RECEIPT_SCHEMA,
    DEVELOPMENT_GAMES,
    EXPECTED_CELL_COUNT,
    FROZEN_BUILD_000_COMMIT,
    FROZEN_BUILD_000_SOURCE_SHA256,
    FROZEN_BUILD_000_TREE,
    FROZEN_BUILD_001_COMMIT,
    FROZEN_BUILD_001_SOURCE_SHA256,
    FROZEN_BUILD_001_TREE,
    MAX_ACTIONS,
    MAX_RESETS,
    OVERALL_ACTIVE_WALL_SECONDS,
    PREDECLARATION_FILE_SHA256,
    PREFLIGHT_SCHEMA,
    PUBLIC_PARTITION_MANIFEST_SHA256,
    STAGE08_EXPOSURE_SHA256,
    STAGE08_RESULT_CORE_HASH,
    STAGE08_RESULT_FILE_SHA256,
    WORKER_SPEC_SCHEMA,
    WORKER_WALL_SECONDS,
    CellStatus,
    DevelopmentCell,
    Outcome,
    Variant,
    aggregate,
    build_matrix,
    matrix_hash,
    validate_predeclaration_bytes,
)
from arc3.evaluation.public import PublicExposureLedger  # noqa: E402
from arc3.integrity import discover_policy_files, scan_policy_files  # noqa: E402

PREDECLARATION = ROOT / "docs/evidence/001-09-development-recovery-predeclaration.json"
DEFAULT_OUTPUT = Path("C:/a/arc3-b001/artifacts/stage09/development-recovery-attempt-01.json")
DEFAULT_WORK_ROOT = Path("C:/a/arc3-b001/artifacts/stage09/development-recovery-work-attempt-01")
DEFAULT_EXPOSURE = Path("C:/a/arc3-b001/artifacts/stage09/public-exposure.jsonl")
DEFAULT_RECORDINGS = Path("C:/a/arc3-b001/recordings/stage09")
DEFAULT_ENVIRONMENTS = Path("C:/a/arc3-s15-6a0f6e5/artifacts/stage15/public-environments")
DEFAULT_BUILD_000_ROOT = Path("C:/a/arc3-stage08-build000-90ecf72")
DEFAULT_BUILD_001_ROOT = Path("C:/a/arc3-stage08-build001-2e78c25")
DEFAULT_STAGE08_RESULT = Path(
    "C:/a/arc3-b001/artifacts/stage08/two-speed-controller-attempt-01.json"
)
DEFAULT_STAGE08_EXPOSURE = Path("C:/a/arc3-b001/artifacts/stage08/public-exposure.jsonl")
PUBLIC_MANIFEST_RELATIVE = Path("docs/evaluation/public-game-partitions.v0.1.json")
WORKER = ROOT / "scripts/_stage09_development_worker.py"
CLAIM_BOUNDARY = "development recovery only; no public-holdout or hidden-game generalization claim"
SEALED_HOLDOUT = {
    "identities_loaded": 0,
    "manifest_loaded_as_metadata": False,
    "public_holdout_gameplay_events": 0,
    "status": "SEALED_UNCONSUMED",
}

INHERITED_EXPOSURES = (
    (
        "build-000",
        Path("C:/a/arc3-s15-6a0f6e5/artifacts/stage15/public-exposure.jsonl"),
        "sha256:cd9af42ed3a5ef9fa0dc201ddb10e32d2bcccee9df729aa0c7d53077c04c9ad4",
    ),
    (
        "stage-03",
        Path("C:/a/arc3-b001/artifacts/stage03/public-exposure.jsonl"),
        "sha256:e02a9fa71206170a6fe2aeefb6935ae25141e2759937657475cead4389bb17aa",
    ),
    (
        "stage-07",
        Path("C:/a/arc3-b001/artifacts/stage07/public-exposure.jsonl"),
        "sha256:4f924df44b11decb392022a927b3296e0248a02edac2c87c53899d374045f0c7",
    ),
)
WINDOWS_NEW_GROUP = int(getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))


def _is_mapping(value: object) -> TypeGuard[Mapping[str, object]]:
    return isinstance(value, Mapping) and all(isinstance(key, str) for key in value)


def _git(root: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root.resolve()), *arguments],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=15.0,
    )
    if result.returncode:
        raise EvaluationError(f"Stage 09 git {' '.join(arguments)} failed")
    return result.stdout.strip()


def _runtime_identity() -> dict[str, object]:
    return {
        "cpu": platform.processor() or platform.machine() or None,
        "cpu_count": os.cpu_count(),
        "executable": Path(sys.executable).resolve().as_posix(),
        "platform": platform.platform(),
        "python": platform.python_version(),
    }


def _source_identity(
    root: Path, *, expected_commit: str, expected_tree: str, expected_source: str
) -> dict[str, object]:
    resolved = root.resolve()
    commit = _git(resolved, "rev-parse", "HEAD")
    tree = _git(resolved, "rev-parse", "HEAD^{tree}")
    branch = _git(resolved, "branch", "--show-current")
    status = _git(resolved, "status", "--porcelain=v1", "--untracked-files=all")
    probe = subprocess.run(
        [
            str(Path(sys.executable).resolve()),
            "-I",
            "-c",
            (
                "import json,sys;from pathlib import Path;"
                "r=Path(sys.argv[1]).resolve();sys.path.insert(0,str(r/'src'));"
                "import arc3;from arc3.evaluation.public import _first_party_source_hash;"
                "print(json.dumps({'arc3':Path(arc3.__file__).resolve().as_posix(),"
                "'source':_first_party_source_hash()},sort_keys=True,separators=(',',':')))"
            ),
            str(resolved),
        ],
        cwd=resolved,
        check=False,
        capture_output=True,
        text=True,
        timeout=30.0,
    )
    projection: dict[str, object] | None = None
    if probe.returncode == 0:
        try:
            value = json.loads(probe.stdout)
            projection = cast(dict[str, object], value) if isinstance(value, dict) else None
        except json.JSONDecodeError:
            projection = None
    expected_arc3 = (resolved / "src/arc3/__init__.py").as_posix()
    predicates = {
        "clean": status == "",
        "commit": commit == expected_commit,
        "detached": branch == "",
        "import_root": projection is not None and projection.get("arc3") == expected_arc3,
        "source_bytes": projection is not None and projection.get("source") == expected_source,
        "tree": tree == expected_tree,
    }
    return {
        "branch": branch,
        "dirty_worktree": bool(status),
        "first_party_source_sha256": projection.get("source") if projection else None,
        "git_commit": commit,
        "git_tree": tree,
        "passed": all(predicates.values()),
        "predicates": predicates,
        "probe_returncode": probe.returncode,
        "probe_stderr_sha256": sha256_bytes(probe.stderr.encode()),
        "root": resolved.as_posix(),
    }


def _source_stable(start: Mapping[str, object], end: Mapping[str, object]) -> bool:
    fields = (
        "branch",
        "dirty_worktree",
        "first_party_source_sha256",
        "git_commit",
        "git_tree",
        "root",
    )
    return bool(
        start.get("passed") is True
        and end.get("passed") is True
        and all(start.get(field) == end.get(field) for field in fields)
    )


def _asset_identity(root: Path, cell: DevelopmentCell) -> dict[str, object]:
    directory = root.resolve() / cell.game.stable_name / cell.game.version
    try:
        directory.relative_to(root.resolve())
    except ValueError as error:
        raise EvaluationError("Stage 09 asset escaped its declared root") from error
    files = (
        tuple(
            (path.relative_to(directory).as_posix(), path.stat().st_size, sha256_file(path))
            for path in sorted(directory.rglob("*"))
            if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc"
        )
        if directory.is_dir()
        else ()
    )
    digest = sha256_bytes(canonical_json_bytes(files)) if files else None
    return {
        "aggregate_sha256": digest,
        "directory": directory.as_posix(),
        "file_count": len(files),
        "files": [
            {"bytes": length, "name": name, "sha256": file_hash}
            for name, length, file_hash in files
        ],
        "game_id": cell.game.game_id,
        "passed": digest == cell.game.asset_sha256,
        "source_semantically_inspected": False,
    }


def _all_assets(root: Path) -> dict[str, object]:
    identities = [_asset_identity(root, cell) for cell in build_matrix()[::8]]
    # Matrix order is two seeds x four variants per game.
    expected_ids = [game.game_id for game in DEVELOPMENT_GAMES]
    if [item["game_id"] for item in identities] != expected_ids:
        raise EvaluationError("Stage 09 development asset order changed")
    return {
        "game_count": len(identities),
        "identities": identities,
        "passed": all(item["passed"] is True for item in identities),
        "source_semantically_inspected": False,
    }


def _development_integrity(root: Path) -> dict[str, object]:
    identifiers = tuple(
        sorted({item for game in DEVELOPMENT_GAMES for item in (game.game_id, game.stable_name)})
    )
    files = discover_policy_files(root.resolve())
    findings = scan_policy_files(root=root.resolve(), files=files, public_identifiers=identifiers)
    rows = [finding.to_dict() for finding in findings]
    return {
        "development_identifier_count": len(identifiers),
        "finding_count": len(rows),
        "findings": rows,
        "holdout_identifiers_loaded": False,
        "passed": not rows,
        "policy_file_count": len(files),
    }


def _stage08_boundary(result_path: Path, exposure_path: Path) -> dict[str, object]:
    result_hash = sha256_file(result_path) if result_path.is_file() else None
    exposure_hash = sha256_file(exposure_path) if exposure_path.is_file() else None
    result: dict[str, object] | None = None
    if result_path.is_file():
        value = load_json(result_path)
        result = cast(dict[str, object], value)
    events = PublicExposureLedger(exposure_path).events()
    game_ids = {game.game_id for game in DEVELOPMENT_GAMES}
    events_valid = len(events) == 1
    for event in events:
        payload = event.get("payload")
        events_valid = bool(
            events_valid
            and isinstance(payload, dict)
            and payload.get("partition") == "development"
            and payload.get("game_id") in game_ids
        )
    predicates = {
        "exposure_hash": exposure_hash == STAGE08_EXPOSURE_SHA256,
        "exposure_is_development_only": events_valid,
        "result_core": result is not None
        and result.get("artifact_core_hash") == STAGE08_RESULT_CORE_HASH,
        "result_hash": result_hash == STAGE08_RESULT_FILE_SHA256,
        "status": result is not None and result.get("status") == "FAILED_INFRASTRUCTURE",
        "unique_attempt_incomplete": result is not None
        and result.get("execution_complete") is False,
    }
    return {
        "exposure_event_count": len(events),
        "exposure_sha256": exposure_hash,
        "passed": all(predicates.values()),
        "predicates": predicates,
        "result_sha256": result_hash,
        "status": result.get("status") if result else None,
    }


def _inherited_exposures() -> dict[str, object]:
    items: list[dict[str, object]] = []
    for label, path, expected in INHERITED_EXPOSURES:
        observed = sha256_file(path) if path.is_file() else None
        items.append(
            {
                "expected_sha256": expected,
                "label": label,
                "path": path.resolve().as_posix(),
                "sha256": observed,
                "verified": observed == expected,
            }
        )
    return {"items": items, "passed": all(item["verified"] is True for item in items)}


def _validate_exposures(path: Path) -> tuple[dict[str, Any], ...]:
    events = PublicExposureLedger(path).events()
    matrix = build_matrix()
    if len(events) > len(matrix):
        raise EvaluationError("Stage 09 exposure count exceeds the frozen matrix")
    for ordinal, event in enumerate(events):
        cell = matrix[ordinal]
        payload = event.get("payload")
        expected = {
            "asset_sha256": cell.game.asset_sha256,
            "cell_id": cell.cell_id,
            "cell_spec_hash": cell.spec_hash,
            "game_id": cell.game.game_id,
            "partition": "development",
            "seed": cell.seed,
            "source_commit": cell.variant.source_commit,
            "variant": cell.variant.value,
        }
        if event.get("event_type") != "stage09.development_episode_started" or payload != expected:
            raise EvaluationError("Stage 09 exposure ledger is not the exact matrix prefix")
    return events


def _official_paths(
    *,
    output: Path,
    work_root: Path,
    exposure: Path,
    recordings: Path,
    environments: Path,
    build_000_root: Path,
    build_001_root: Path,
    stage08_result: Path,
    stage08_exposure: Path,
) -> None:
    supplied = (
        output,
        work_root,
        exposure,
        recordings,
        environments,
        build_000_root,
        build_001_root,
        stage08_result,
        stage08_exposure,
    )
    expected = (
        DEFAULT_OUTPUT,
        DEFAULT_WORK_ROOT,
        DEFAULT_EXPOSURE,
        DEFAULT_RECORDINGS,
        DEFAULT_ENVIRONMENTS,
        DEFAULT_BUILD_000_ROOT,
        DEFAULT_BUILD_001_ROOT,
        DEFAULT_STAGE08_RESULT,
        DEFAULT_STAGE08_EXPOSURE,
    )
    if any(
        left.resolve() != right.resolve() for left, right in zip(supplied, expected, strict=True)
    ):
        raise EvaluationError("official Stage 09 paths differ from the frozen contract")
    mutable = (output.resolve(), work_root.resolve(), exposure.resolve(), recordings.resolve())
    protected = (environments.resolve(), build_000_root.resolve(), build_001_root.resolve())
    for left in mutable:
        for right in protected:
            try:
                left.relative_to(right)
            except ValueError:
                pass
            else:
                raise EvaluationError("Stage 09 mutable and protected roots overlap")


def preflight(
    *,
    output: Path = DEFAULT_OUTPUT,
    work_root: Path = DEFAULT_WORK_ROOT,
    exposure: Path = DEFAULT_EXPOSURE,
    recordings: Path = DEFAULT_RECORDINGS,
    environments: Path = DEFAULT_ENVIRONMENTS,
    build_000_root: Path = DEFAULT_BUILD_000_ROOT,
    build_001_root: Path = DEFAULT_BUILD_001_ROOT,
    stage08_result: Path = DEFAULT_STAGE08_RESULT,
    stage08_exposure: Path = DEFAULT_STAGE08_EXPOSURE,
    enforce_official_paths: bool = True,
) -> dict[str, object]:
    """Validate every boundary without opening an environment."""

    if enforce_official_paths:
        _official_paths(
            output=output,
            work_root=work_root,
            exposure=exposure,
            recordings=recordings,
            environments=environments,
            build_000_root=build_000_root,
            build_001_root=build_001_root,
            stage08_result=stage08_result,
            stage08_exposure=stage08_exposure,
        )
    declaration = validate_predeclaration_bytes(
        PREDECLARATION.read_bytes(), expected_file_sha256=PREDECLARATION_FILE_SHA256
    )
    source_000 = _source_identity(
        build_000_root,
        expected_commit=FROZEN_BUILD_000_COMMIT,
        expected_tree=FROZEN_BUILD_000_TREE,
        expected_source=FROZEN_BUILD_000_SOURCE_SHA256,
    )
    source_001 = _source_identity(
        build_001_root,
        expected_commit=FROZEN_BUILD_001_COMMIT,
        expected_tree=FROZEN_BUILD_001_TREE,
        expected_source=FROZEN_BUILD_001_SOURCE_SHA256,
    )
    assets = _all_assets(environments)
    predecessor = _stage08_boundary(stage08_result, stage08_exposure)
    inherited = _inherited_exposures()
    current_events = _validate_exposures(exposure)
    manifest_hashes = {
        "build_000": sha256_file(build_000_root / PUBLIC_MANIFEST_RELATIVE),
        "build_001": sha256_file(build_001_root / PUBLIC_MANIFEST_RELATIVE),
    }
    integrity = {
        "build_000": _development_integrity(build_000_root),
        "build_001": _development_integrity(build_001_root),
    }
    predicates = {
        "assets": assets["passed"] is True,
        "build_000_integrity": integrity["build_000"]["passed"] is True,
        "build_000_source": source_000["passed"] is True,
        "build_001_integrity": integrity["build_001"]["passed"] is True,
        "build_001_source": source_001["passed"] is True,
        "inherited_exposures": inherited["passed"] is True,
        "manifest_hashes": set(manifest_hashes.values()) == {PUBLIC_PARTITION_MANIFEST_SHA256},
        "matrix": len(build_matrix()) == EXPECTED_CELL_COUNT,
        "predecessor": predecessor["passed"] is True,
        "worker": WORKER.is_file(),
    }
    payload = {
        "schema": PREFLIGHT_SCHEMA,
        "status": "READY_NOT_EXECUTED" if all(predicates.values()) else "FAILED_INFRASTRUCTURE",
        "gameplay_opened": False,
        "holdout": {
            "identities_loaded": 0,
            "manifest_loaded_as_metadata": False,
            "public_holdout_gameplay_events": 0,
            "status": "SEALED_UNCONSUMED" if all(predicates.values()) else "UNVERIFIED",
        },
        "predeclaration_core_hash": declaration["predeclaration_core_hash"],
        "predeclaration_sha256": sha256_file(PREDECLARATION),
        "matrix_hash": matrix_hash(),
        "sources": {"build_000": source_000, "build_001": source_001},
        "assets": assets,
        "stage08_predecessor": predecessor,
        "inherited_exposures": inherited,
        "stage09_exposure_event_count": len(current_events),
        "public_manifest_hashes": manifest_hashes,
        "competition_integrity": integrity,
        "runtime_identity": _runtime_identity(),
        "paths": {
            "build_000_root": build_000_root.resolve().as_posix(),
            "build_001_root": build_001_root.resolve().as_posix(),
            "environments": environments.resolve().as_posix(),
            "exposure": exposure.resolve().as_posix(),
            "output": output.resolve().as_posix(),
            "recordings": recordings.resolve().as_posix(),
            "work_root": work_root.resolve().as_posix(),
        },
        "predicates": predicates,
    }
    return cast(dict[str, object], seal_object(payload, hash_field="preflight_hash"))


def _terminate_tree(process: subprocess.Popen[bytes]) -> dict[str, object]:
    method = "windows-taskkill-tree" if os.name == "nt" else "posix-killpg"
    error: str | None = None
    returncode: int | None = None
    try:
        if os.name == "nt":
            result = subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                check=False,
                capture_output=True,
                timeout=10.0,
            )
            returncode = result.returncode
        else:
            kill_group = getattr(os, "killpg", None)
            if not callable(kill_group):
                raise OSError("process-group termination is unavailable")
            kill_group(process.pid, int(getattr(signal, "SIGKILL", signal.SIGTERM)))
    except (OSError, subprocess.TimeoutExpired) as caught:
        error = f"{type(caught).__name__}: {caught}"
    if process.poll() is None:
        process.kill()
    passed = error is None and (
        (method == "windows-taskkill-tree" and returncode == 0)
        or (method == "posix-killpg" and returncode is None)
    )
    return {
        "attempted": True,
        "error": error,
        "method": method,
        "passed": passed,
        "returncode": returncode,
    }


def _atomic_create(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())


def _supervise(
    command: Sequence[str], *, cwd: Path, streams: Path, timeout_seconds: float
) -> dict[str, object]:
    started = time.perf_counter_ns()
    stdout = b""
    stderr = b""
    timed_out = False
    launch_error: str | None = None
    termination: dict[str, object] | None = None
    returncode: int | None = None
    try:
        options: dict[str, object] = {
            "cwd": cwd,
            "env": {key: value for key, value in os.environ.items() if key.upper() != "PYTHONPATH"},
            "stdin": subprocess.DEVNULL,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
        }
        if os.name == "nt":
            options["creationflags"] = WINDOWS_NEW_GROUP
        else:
            options["start_new_session"] = True
        process = subprocess.Popen(list(command), **cast(dict[str, Any], options))
        try:
            stdout, stderr = process.communicate(timeout=timeout_seconds)
        except subprocess.TimeoutExpired as error:
            timed_out = True
            stdout = bytes(error.stdout or b"")
            stderr = bytes(error.stderr or b"")
            termination = _terminate_tree(process)
            try:
                tail_out, tail_err = process.communicate(timeout=10.0)
                stdout = tail_out if tail_out.startswith(stdout) else stdout + tail_out
                stderr = tail_err if tail_err.startswith(stderr) else stderr + tail_err
            except subprocess.TimeoutExpired:
                if process.poll() is None:
                    process.kill()
                process.wait(timeout=5.0)
        returncode = process.returncode
    except OSError as error:
        launch_error = f"{type(error).__name__}: {error}"
    stdout_path = streams / "stdout.bin"
    stderr_path = streams / "stderr.bin"
    _atomic_create(stdout_path, stdout)
    _atomic_create(stderr_path, stderr)
    return {
        "command": list(command),
        "launch_error": launch_error,
        "returncode": returncode,
        "stderr_bytes": len(stderr),
        "stderr_path": stderr_path.resolve().as_posix(),
        "stderr_sha256": sha256_bytes(stderr),
        "stdout_bytes": len(stdout),
        "stdout_path": stdout_path.resolve().as_posix(),
        "stdout_sha256": sha256_bytes(stdout),
        "timed_out": timed_out,
        "timeout_seconds": timeout_seconds,
        "termination": termination,
        "wall_ns": max(0, time.perf_counter_ns() - started),
    }


def _worker_spec(
    cell: DevelopmentCell,
    *,
    source_root: Path,
    environments: Path,
    recordings: Path,
    cell_root: Path,
    runtime_identity: Mapping[str, object],
) -> dict[str, Any]:
    declaration = {
        "agent": cell.variant.agent,
        "automatic_checkpointing": True,
        "max_actions": MAX_ACTIONS,
        "max_resets": MAX_RESETS,
        "network_mode": "offline-evaluation",
        "profile": "stage15-local-public",
        "python_allocation_tracing": True,
        "seed": cell.seed,
        "timeout_seconds": WORKER_WALL_SECONDS,
    }
    asset = _asset_identity(environments, cell)
    identity: dict[str, object] = {
        "action_budget": MAX_ACTIONS,
        "agent_config": declaration,
        "asset_identities": {cell.game.game_id: asset},
        "budgets": {
            "maximum_actions": MAX_ACTIONS,
            "maximum_resets": MAX_RESETS,
            "maximum_wall_clock_seconds_per_run": WORKER_WALL_SECONDS,
        },
        "config_hash": sha256_bytes(canonical_json_bytes(declaration)),
        "dirty_worktree": False,
        "first_party_source_hash": cell.variant.source_sha256,
        "games": [cell.game.game_id],
        "git_commit": cell.variant.source_commit,
        "hardware": dict(runtime_identity),
        "network_mode": "offline-evaluation",
        "policy_network_mode": "offline",
        "public_partition_manifest_hash": PUBLIC_PARTITION_MANIFEST_SHA256,
        "python_version": platform.python_version(),
        "seeds": [cell.seed],
        "surface": "local-public",
        "upstream_lock_hash": "sha256:67e1d937e213bbcc25783784d04c4fa349b85dc09b94855256916ca6b96e808a",
        "wall_clock_budget_seconds": WORKER_WALL_SECONDS,
    }
    identity["identity_hash"] = sha256_bytes(canonical_json_bytes(identity))
    specification: dict[str, object] = {
        "agent": cell.variant.agent,
        "asset_aggregate_sha256_before": cell.game.asset_sha256,
        "baseline_id": cell.variant.baseline_id,
        "evaluation_id": "build-001-stage09-development-recovery",
        "game_id": cell.game.game_id,
        "identity_hash": identity["identity_hash"],
        "max_actions": MAX_ACTIONS,
        "max_resets": MAX_RESETS,
        "network_mode": "offline-evaluation",
        "partition": "development",
        "run_id": cell.cell_id,
        "seed": cell.seed,
        "stable_name": cell.game.stable_name,
        "surface": "local-public",
        "timeout_seconds": WORKER_WALL_SECONDS,
    }
    if cell.variant is Variant.BUILD_001_FULL:
        specification.update(
            {
                "automatic_checkpointing": True,
                "hot_path_profile": False,
                "python_allocation_tracing": True,
            }
        )
    specification["run_spec_hash"] = sha256_bytes(canonical_json_bytes(specification))
    public_worker_spec = {
        "checkpoint_path": str(cell_root / "checkpoint"),
        "environments_dir": str(environments.resolve()),
        "game_id": cell.game.game_id,
        "git_commit": cell.variant.source_commit,
        "identity": identity,
        "max_actions": MAX_ACTIONS,
        "max_resets": MAX_RESETS,
        "recordings_dir": str(recordings.resolve() / cell.cell_id),
        "run_id": cell.cell_id,
        "seed": cell.seed,
        "specification": specification,
        "timeout_seconds": WORKER_WALL_SECONDS,
        "trace_path": str(cell_root / "trace"),
        "trace_relative": f"cells/{cell.cell_id}/trace",
    }
    outer = {
        "schema": WORKER_SPEC_SCHEMA,
        "cell_id": cell.cell_id,
        "cell_spec_hash": cell.spec_hash,
        "first_party_source_sha256": cell.variant.source_sha256,
        "public_worker_spec": public_worker_spec,
        "source_commit": cell.variant.source_commit,
        "source_root": source_root.resolve().as_posix(),
        "source_tree": cell.variant.source_tree,
    }
    return seal_object(outer, hash_field="worker_spec_hash")


def _raw_result(
    raw_path: Path, cell: DevelopmentCell, spec: Mapping[str, object]
) -> dict[str, object]:
    raw = load_json(raw_path)
    public_spec = cast(dict[str, object], spec["public_worker_spec"])
    specification = cast(dict[str, object], public_spec["specification"])
    identity = cast(dict[str, object], public_spec["identity"])
    if not verify_object_hash(raw, hash_field="receipt_hash"):
        raise EvaluationError("Stage 09 raw worker receipt hash is invalid")
    for field in (
        "evaluation_id",
        "run_id",
        "game_id",
        "baseline_id",
        "agent",
        "seed",
        "partition",
    ):
        if raw.get(field) != specification.get(field):
            raise EvaluationError(f"Stage 09 raw worker {field} changed")
    if raw.get("identity_hash") != identity.get("identity_hash"):
        raise EvaluationError("Stage 09 raw worker identity changed")
    score = raw.get("score")
    metrics = raw.get("metrics")
    asset = raw.get("asset_identity_after")
    if not isinstance(score, dict) or not isinstance(metrics, dict) or not isinstance(asset, dict):
        raise EvaluationError("Stage 09 raw worker evidence is incomplete")
    if asset.get("aggregate_sha256") != cell.game.asset_sha256:
        raise EvaluationError("Stage 09 asset changed during worker execution")
    actions = metrics.get("environment_actions")
    if isinstance(actions, bool) or not isinstance(actions, int) or not 0 <= actions <= MAX_ACTIONS:
        raise EvaluationError("Stage 09 raw action count is invalid")
    return cast(dict[str, object], raw)


def _cell_receipt(
    cell: DevelopmentCell,
    *,
    spec: Mapping[str, object],
    exposure_event: Mapping[str, object],
    supervision: Mapping[str, object],
    raw_path: Path,
    asset_after: Mapping[str, object],
    parent_active_wall_ns: int,
) -> dict[str, object]:
    status = CellStatus.INFRASTRUCTURE_FAILURE
    score_verified = False
    completed = False
    levels = 0
    actions = 0
    raw_hash: str | None = None
    child_cpu: float | None = None
    child_rss: int | None = None
    failure: str | None = None
    if supervision.get("timed_out") is True:
        termination = supervision.get("termination")
        if isinstance(termination, dict) and termination.get("passed") is True:
            status = CellStatus.CONTROLLER_WALL_TIMEOUT
            actions = MAX_ACTIONS
        else:
            failure = "process-tree termination did not verify"
    elif supervision.get("launch_error") is not None:
        failure = "worker process launch failed"
    elif supervision.get("returncode") != 0:
        failure = "worker exited nonzero"
    elif not raw_path.is_file():
        failure = "worker produced no raw receipt"
    else:
        try:
            raw = _raw_result(raw_path, cell, spec)
            raw_hash = cast(str, raw["receipt_hash"])
            score = cast(dict[str, object], raw["score"])
            metrics = cast(dict[str, object], raw["metrics"])
            score_verified = score.get("verified") is True
            completed = score.get("completed") is True
            raw_levels = score.get("levels_completed")
            levels = (
                raw_levels
                if isinstance(raw_levels, int) and not isinstance(raw_levels, bool)
                else 0
            )
            raw_actions = metrics.get("environment_actions")
            actions = (
                raw_actions
                if isinstance(raw_actions, int) and not isinstance(raw_actions, bool)
                else 0
            )
            cpu = metrics.get("total_cpu_seconds")
            child_cpu = (
                float(cpu) if isinstance(cpu, (int, float)) and not isinstance(cpu, bool) else None
            )
            rss = metrics.get("peak_rss_bytes")
            child_rss = rss if isinstance(rss, int) and not isinstance(rss, bool) else None
            if raw.get("status") == "success":
                status = CellStatus.SUCCESS
            else:
                status = CellStatus.INFRASTRUCTURE_FAILURE
                raw_failure = raw.get("failure")
                failure = (
                    f"raw worker failure: {raw_failure}"
                    if isinstance(raw_failure, dict)
                    else "raw worker did not terminate successfully"
                )
        except (EvaluationError, OSError, ValueError) as error:
            failure = f"{type(error).__name__}: {error}"
    if asset_after.get("passed") is not True:
        status = CellStatus.INFRASTRUCTURE_FAILURE
        failure = "development asset identity changed after cell execution"
    payload = {
        "schema": CELL_RECEIPT_SCHEMA,
        "status": status.value,
        "evidence_label": "local-public",
        "cell_id": cell.cell_id,
        "cell_spec_hash": cell.spec_hash,
        "game_id": cell.game.game_id,
        "seed": cell.seed,
        "variant": cell.variant.value,
        "asset_sha256": cell.game.asset_sha256,
        "source_commit": cell.variant.source_commit,
        "exposure_event_hash": exposure_event.get("event_hash"),
        "worker_spec_hash": spec.get("worker_spec_hash"),
        "raw_receipt_hash": raw_hash,
        "raw_receipt_sha256": sha256_file(raw_path) if raw_path.is_file() else None,
        "result": {
            "completed": completed,
            "environment_actions": actions,
            "levels_completed": levels,
            "score_verified": score_verified,
        },
        "resources": {
            "child_cpu_seconds": child_cpu,
            "child_peak_rss_bytes": child_rss,
            "parent_active_wall_ns": parent_active_wall_ns,
            "supervision_wall_ns": supervision.get("wall_ns"),
            "worker_wall_seconds": WORKER_WALL_SECONDS,
        },
        "supervisor": dict(supervision),
        "asset_after": dict(asset_after),
        "failure": failure,
    }
    return cast(dict[str, object], seal_object(payload, hash_field="cell_receipt_hash"))


def _append_exposure(path: Path, cell: DevelopmentCell) -> dict[str, Any]:
    return PublicExposureLedger(path).append(
        "stage09.development_episode_started",
        {
            "asset_sha256": cell.game.asset_sha256,
            "cell_id": cell.cell_id,
            "cell_spec_hash": cell.spec_hash,
            "game_id": cell.game.game_id,
            "partition": "development",
            "seed": cell.seed,
            "source_commit": cell.variant.source_commit,
            "variant": cell.variant.value,
        },
    )


def _resource_summary(
    receipts: Sequence[Mapping[str, object]],
    *,
    runtime_start: Mapping[str, object],
    execution_complete: bool,
) -> dict[str, object]:
    parent_wall_ns = 0
    supervision_wall_ns = 0
    cpu_values: list[float] = []
    rss_values: list[int] = []
    for receipt in receipts:
        resources = receipt.get("resources")
        if not isinstance(resources, dict):
            raise EvaluationError("Stage 09 resource receipt is absent")
        parent = resources.get("parent_active_wall_ns")
        supervised = resources.get("supervision_wall_ns")
        if isinstance(parent, bool) or not isinstance(parent, int) or parent < 0:
            raise EvaluationError("Stage 09 parent active wall is invalid")
        if isinstance(supervised, bool) or not isinstance(supervised, int) or supervised < 0:
            raise EvaluationError("Stage 09 supervision wall is invalid")
        if parent < supervised:
            raise EvaluationError("Stage 09 parent active wall is below supervision wall")
        parent_wall_ns += parent
        supervision_wall_ns += supervised
        cpu = resources.get("child_cpu_seconds")
        rss = resources.get("child_peak_rss_bytes")
        if cpu is not None:
            if isinstance(cpu, bool) or not isinstance(cpu, (int, float)) or float(cpu) < 0:
                raise EvaluationError("Stage 09 child CPU receipt is invalid")
            cpu_values.append(float(cpu))
        if rss is not None:
            if isinstance(rss, bool) or not isinstance(rss, int) or rss < 0:
                raise EvaluationError("Stage 09 child RSS receipt is invalid")
            rss_values.append(rss)
    limit_ns = int(OVERALL_ACTIVE_WALL_SECONDS * 1_000_000_000)
    return {
        "cell_receipt_count": len(receipts),
        "child_cpu_measurement_complete": len(cpu_values) == len(receipts),
        "child_cpu_seconds_observed_sum": sum(cpu_values),
        "child_peak_rss_bytes_max": max(rss_values, default=None),
        "child_peak_rss_measurement_complete": len(rss_values) == len(receipts),
        "cumulative_active_wall_ns": parent_wall_ns,
        "cumulative_worker_supervision_wall_ns": supervision_wall_ns,
        "overall_active_wall_limit_ns": limit_ns,
        "runtime_end": _runtime_identity(),
        "runtime_start": dict(runtime_start),
        "wall_measurement_complete": execution_complete,
        "wall_within_limit": parent_wall_ns <= limit_ns,
    }


def _failure_terminal(
    *,
    output: Path,
    check: Mapping[str, object],
    receipts: Sequence[Mapping[str, object]],
    exposure: Path,
    failed_cell: DevelopmentCell,
    failure_kind: str,
    exposure_event_hash: object,
) -> dict[str, object]:
    runtime_start = check.get("runtime_identity")
    if not isinstance(runtime_start, dict):
        raise EvaluationError("Stage 09 preflight runtime identity is absent")
    payload = {
        "schema": AGGREGATE_SCHEMA,
        "status": "FAILED_INFRASTRUCTURE",
        "evidence_label": "local-public",
        "claim_boundary": CLAIM_BOUNDARY,
        "execution_complete": False,
        "matrix_hash": matrix_hash(),
        "expected_cell_count": EXPECTED_CELL_COUNT,
        "cell_count": len(receipts),
        "cell_receipt_hashes": [receipt.get("cell_receipt_hash") for receipt in receipts],
        "failure": {
            "cell_id": failed_cell.cell_id,
            "cell_ordinal": failed_cell.ordinal,
            "exposure_event_hash": exposure_event_hash,
            "kind": failure_kind,
        },
        "preflight": dict(check),
        "resources": _resource_summary(
            receipts, runtime_start=runtime_start, execution_complete=False
        ),
        "exposure_ledger_sha256": sha256_file(exposure) if exposure.is_file() else None,
        "holdout": dict(SEALED_HOLDOUT),
    }
    final = cast(dict[str, object], seal_object(payload, hash_field="artifact_core_hash"))
    _atomic_create(output, canonical_json_bytes(final))
    return final


def _load_receipt_prefix(work_root: Path, count: int) -> list[dict[str, object]]:
    matrix = build_matrix()
    if not 0 <= count <= len(matrix):
        raise EvaluationError("Stage 09 terminal cell count is invalid")
    receipts: list[dict[str, object]] = []
    for ordinal, cell in enumerate(matrix[:count]):
        path = work_root / "parent-receipts" / f"{ordinal:02d}-{cell.cell_id}.json"
        if not path.is_file():
            raise EvaluationError("Stage 09 terminal artifact references a missing receipt")
        receipt = load_json(path)
        Outcome.from_receipt(receipt, cell)
        receipts.append(cast(dict[str, object], receipt))
    return receipts


def _load_existing_terminal(
    *,
    output: Path,
    work_root: Path,
    exposure: Path,
    check: Mapping[str, object],
) -> dict[str, object] | None:
    if not output.exists():
        return None
    prior = load_json(output)
    if prior.get("schema") != AGGREGATE_SCHEMA or not verify_object_hash(
        prior, hash_field="artifact_core_hash"
    ):
        raise EvaluationError("existing Stage 09 output is not an exact terminal artifact")
    if (
        prior.get("evidence_label") != "local-public"
        or prior.get("claim_boundary") != CLAIM_BOUNDARY
        or prior.get("matrix_hash") != matrix_hash()
        or prior.get("expected_cell_count") != EXPECTED_CELL_COUNT
        or prior.get("holdout") != SEALED_HOLDOUT
    ):
        raise EvaluationError("existing Stage 09 terminal identity changed")
    count = prior.get("cell_count")
    if isinstance(count, bool) or not isinstance(count, int):
        raise EvaluationError("existing Stage 09 terminal cell count is invalid")
    receipts = _load_receipt_prefix(work_root, count)
    if prior.get("cell_receipt_hashes") != [
        receipt.get("cell_receipt_hash") for receipt in receipts
    ]:
        raise EvaluationError("existing Stage 09 terminal receipt projection changed")
    events = _validate_exposures(exposure)
    execution_complete = prior.get("execution_complete")
    runtime_start = check.get("runtime_identity")
    if not isinstance(runtime_start, dict):
        raise EvaluationError("current Stage 09 runtime identity is absent")
    expected_resources = _resource_summary(
        receipts,
        runtime_start=runtime_start,
        execution_complete=execution_complete is True,
    )
    if prior.get("resources") != expected_resources:
        raise EvaluationError("existing Stage 09 resource projection changed")
    embedded_preflight = prior.get("preflight")
    if (
        not isinstance(embedded_preflight, dict)
        or embedded_preflight.get("schema") != PREFLIGHT_SCHEMA
        or embedded_preflight.get("status") != "READY_NOT_EXECUTED"
        or not verify_object_hash(embedded_preflight, hash_field="preflight_hash")
        or embedded_preflight.get("gameplay_opened") is not False
    ):
        raise EvaluationError("existing Stage 09 preflight evidence changed")
    if execution_complete is True:
        if count != EXPECTED_CELL_COUNT or len(events) != EXPECTED_CELL_COUNT:
            raise EvaluationError("existing complete Stage 09 terminal is not matrix-complete")
        integrity = check.get("competition_integrity")
        if not isinstance(integrity, dict) or not all(
            isinstance(value, dict) and value.get("passed") is True for value in integrity.values()
        ):
            raise EvaluationError("existing Stage 09 competition integrity does not verify")
        expected = aggregate(
            receipts,
            evidence_integrity=expected_resources["wall_within_limit"] is True,
            competition_integrity=True,
        )
        for key, value in expected.items():
            if prior.get(key) != value:
                raise EvaluationError("existing complete Stage 09 decision projection changed")
    elif execution_complete is False:
        if prior.get("status") != "FAILED_INFRASTRUCTURE" or len(events) not in {
            count,
            count + 1,
        }:
            raise EvaluationError("existing partial Stage 09 terminal is not fail-closed")
        failure = prior.get("failure")
        if not isinstance(failure, dict) or failure.get("cell_ordinal") != count:
            if not (
                count > 0
                and isinstance(failure, dict)
                and failure.get("cell_ordinal") == count - 1
                and receipts[-1].get("status") == CellStatus.INFRASTRUCTURE_FAILURE.value
            ):
                raise EvaluationError("existing Stage 09 failure boundary changed")
    else:
        raise EvaluationError("existing Stage 09 terminal completion state is invalid")
    return cast(dict[str, object], prior)


def execute(
    *,
    output: Path = DEFAULT_OUTPUT,
    work_root: Path = DEFAULT_WORK_ROOT,
    exposure: Path = DEFAULT_EXPOSURE,
    recordings: Path = DEFAULT_RECORDINGS,
    environments: Path = DEFAULT_ENVIRONMENTS,
    build_000_root: Path = DEFAULT_BUILD_000_ROOT,
    build_001_root: Path = DEFAULT_BUILD_001_ROOT,
    stage08_result: Path = DEFAULT_STAGE08_RESULT,
    stage08_exposure: Path = DEFAULT_STAGE08_EXPOSURE,
) -> dict[str, object]:
    """Execute exactly once; exposed cells are never relaunched."""

    _official_paths(
        output=output,
        work_root=work_root,
        exposure=exposure,
        recordings=recordings,
        environments=environments,
        build_000_root=build_000_root,
        build_001_root=build_001_root,
        stage08_result=stage08_result,
        stage08_exposure=stage08_exposure,
    )
    check = preflight(
        output=output,
        work_root=work_root,
        exposure=exposure,
        recordings=recordings,
        environments=environments,
        build_000_root=build_000_root,
        build_001_root=build_001_root,
        stage08_result=stage08_result,
        stage08_exposure=stage08_exposure,
    )
    if check["status"] != "READY_NOT_EXECUTED":
        raise EvaluationError("Stage 09 execution preflight is not ready")
    existing_terminal = _load_existing_terminal(
        output=output, work_root=work_root, exposure=exposure, check=check
    )
    if existing_terminal is not None:
        return existing_terminal
    work_root.mkdir(parents=True, exist_ok=True)
    recordings.mkdir(parents=True, exist_ok=True)
    events = _validate_exposures(exposure)
    matrix = build_matrix()
    receipt_root = work_root / "parent-receipts"
    existing_receipts: list[dict[str, object]] = []
    cumulative_wall_ns = 0
    for ordinal, cell in enumerate(matrix):
        receipt_path = receipt_root / f"{ordinal:02d}-{cell.cell_id}.json"
        if ordinal < len(events):
            if not receipt_path.is_file():
                return _failure_terminal(
                    output=output,
                    check=check,
                    receipts=existing_receipts,
                    exposure=exposure,
                    failed_cell=cell,
                    failure_kind="exposed-without-terminal-receipt",
                    exposure_event_hash=events[ordinal].get("event_hash"),
                )
            receipt = load_json(receipt_path)
            Outcome.from_receipt(receipt, cell)
            existing_receipts.append(cast(dict[str, object], receipt))
            resources = cast(dict[str, object], receipt["resources"])
            cumulative_wall_ns += cast(int, resources["parent_active_wall_ns"])
            if receipt["status"] == CellStatus.INFRASTRUCTURE_FAILURE.value:
                return _failure_terminal(
                    output=output,
                    check=check,
                    receipts=existing_receipts,
                    exposure=exposure,
                    failed_cell=cell,
                    failure_kind="terminal-cell-infrastructure-failure",
                    exposure_event_hash=events[ordinal].get("event_hash"),
                )
            continue
        remaining_ns = int(OVERALL_ACTIVE_WALL_SECONDS * 1_000_000_000) - cumulative_wall_ns
        if remaining_ns < int(WORKER_WALL_SECONDS * 1_000_000_000):
            return _failure_terminal(
                output=output,
                check=check,
                receipts=existing_receipts,
                exposure=exposure,
                failed_cell=cell,
                failure_kind="overall-active-wall-cannot-admit-next-cell",
                exposure_event_hash=None,
            )
        source_root = build_001_root if cell.variant is Variant.BUILD_001_FULL else build_000_root
        cell_started_ns = time.perf_counter_ns()
        cell_root = work_root / "cells" / f"{ordinal:02d}-{cell.cell_id}"
        spec = _worker_spec(
            cell,
            source_root=source_root,
            environments=environments,
            recordings=recordings,
            cell_root=cell_root,
            runtime_identity=cast(dict[str, object], check["runtime_identity"]),
        )
        spec_path = work_root / "specs" / f"{ordinal:02d}-{cell.cell_id}.json"
        _atomic_create(spec_path, canonical_json_bytes(spec))
        event = _append_exposure(exposure, cell)
        raw_path = cell_root / "raw-worker-result.json"
        streams = work_root / "parent-streams" / f"{ordinal:02d}-{cell.cell_id}"
        command = (
            str(Path(sys.executable).resolve()),
            "-I",
            str(WORKER.resolve()),
            "--spec",
            str(spec_path.resolve()),
            "--result",
            str(raw_path.resolve()),
        )
        supervision = _supervise(
            command,
            cwd=ROOT,
            streams=streams,
            timeout_seconds=WORKER_WALL_SECONDS,
        )
        asset_after = _asset_identity(environments, cell)
        parent_active_wall_ns = max(0, time.perf_counter_ns() - cell_started_ns)
        receipt = _cell_receipt(
            cell,
            spec=spec,
            exposure_event=event,
            supervision=supervision,
            raw_path=raw_path,
            asset_after=asset_after,
            parent_active_wall_ns=parent_active_wall_ns,
        )
        _atomic_create(receipt_path, canonical_json_bytes(receipt))
        existing_receipts.append(receipt)
        cumulative_wall_ns += parent_active_wall_ns
        if receipt["status"] == CellStatus.INFRASTRUCTURE_FAILURE.value:
            return _failure_terminal(
                output=output,
                check=check,
                receipts=existing_receipts,
                exposure=exposure,
                failed_cell=cell,
                failure_kind="terminal-cell-infrastructure-failure",
                exposure_event_hash=event.get("event_hash"),
            )
    end_000 = _source_identity(
        build_000_root,
        expected_commit=FROZEN_BUILD_000_COMMIT,
        expected_tree=FROZEN_BUILD_000_TREE,
        expected_source=FROZEN_BUILD_000_SOURCE_SHA256,
    )
    end_001 = _source_identity(
        build_001_root,
        expected_commit=FROZEN_BUILD_001_COMMIT,
        expected_tree=FROZEN_BUILD_001_TREE,
        expected_source=FROZEN_BUILD_001_SOURCE_SHA256,
    )
    start_sources = cast(dict[str, Mapping[str, object]], check["sources"])
    source_stable = _source_stable(start_sources["build_000"], end_000) and _source_stable(
        start_sources["build_001"], end_001
    )
    asset_end = _all_assets(environments)
    exposures_end = _validate_exposures(exposure)
    evidence_integrity = bool(
        source_stable
        and asset_end["passed"] is True
        and len(exposures_end) == EXPECTED_CELL_COUNT
        and cumulative_wall_ns <= int(OVERALL_ACTIVE_WALL_SECONDS * 1_000_000_000)
    )
    integrity = cast(dict[str, Mapping[str, object]], check["competition_integrity"])
    competition_integrity = all(value.get("passed") is True for value in integrity.values())
    result = aggregate(
        existing_receipts,
        evidence_integrity=evidence_integrity,
        competition_integrity=competition_integrity,
    )
    result.update(
        {
            "preflight": check,
            "execution_complete": True,
            "expected_cell_count": EXPECTED_CELL_COUNT,
            "resources": _resource_summary(
                existing_receipts,
                runtime_start=cast(dict[str, object], check["runtime_identity"]),
                execution_complete=True,
            ),
            "source_end": {"build_000": end_000, "build_001": end_001},
            "source_stable": source_stable,
            "asset_end": asset_end,
            "exposure_ledger_sha256": sha256_file(exposure),
            "holdout": dict(SEALED_HOLDOUT),
        }
    )
    final = cast(dict[str, object], seal_object(result, hash_field="artifact_core_hash"))
    _atomic_create(output, canonical_json_bytes(final))
    return final


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--work-root", type=Path, default=DEFAULT_WORK_ROOT)
    parser.add_argument("--exposure-ledger", type=Path, default=DEFAULT_EXPOSURE)
    parser.add_argument("--recordings-root", type=Path, default=DEFAULT_RECORDINGS)
    parser.add_argument("--environments-dir", type=Path, default=DEFAULT_ENVIRONMENTS)
    parser.add_argument("--build-000-root", type=Path, default=DEFAULT_BUILD_000_ROOT)
    parser.add_argument("--build-001-root", type=Path, default=DEFAULT_BUILD_001_ROOT)
    parser.add_argument("--stage08-result", type=Path, default=DEFAULT_STAGE08_RESULT)
    parser.add_argument("--stage08-exposure", type=Path, default=DEFAULT_STAGE08_EXPOSURE)
    parser.add_argument("--execute", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(list(argv) if argv is not None else None)
    keywords = {
        "output": args.output,
        "work_root": args.work_root,
        "exposure": args.exposure_ledger,
        "recordings": args.recordings_root,
        "environments": args.environments_dir,
        "build_000_root": args.build_000_root,
        "build_001_root": args.build_001_root,
        "stage08_result": args.stage08_result,
        "stage08_exposure": args.stage08_exposure,
    }
    result = execute(**keywords) if args.execute else preflight(**keywords)
    sys.stdout.buffer.write(canonical_json_bytes(result))
    return 0 if result["status"] in {"READY_NOT_EXECUTED", "PASS"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
