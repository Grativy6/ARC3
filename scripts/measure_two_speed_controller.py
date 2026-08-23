#!/usr/bin/env python3
"""Orchestrate the frozen Build 001 Stage 08 two-speed measurement.

The default command is a non-playing preflight.  ``--execute`` is required to
start the exact twenty-cell local-public development comparison.  The runner
never loads the public partition manifest as gameplay metadata, never selects a
holdout identity, and never asks the adapter to acquire an asset.
"""

from __future__ import annotations

import argparse
import importlib
import importlib.metadata
import json
import os
import platform
import signal
import subprocess
import sys
import time
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import replace
from pathlib import Path
from typing import TypeGuard, cast

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from arc3.adapters import arc_agi as arc_agi_adapter  # noqa: E402
from arc3.adapters.arc_agi import ARC_AGI_VERSION, ARCENGINE_VERSION  # noqa: E402
from arc3.errors import EvaluationError  # noqa: E402
from arc3.evaluation.public import PublicExposureLedger  # noqa: E402
from arc3.evaluation.two_speed_measurement import (  # noqa: E402
    BUILD_000_PRODUCTION_COMMIT,
    BUILD_000_PRODUCTION_TREE,
    BUILD_001_BASELINE_COMMIT,
    DEVELOPMENT_ASSET_SHA256,
    DEVELOPMENT_GAME_ID,
    EXPECTED_CELL_COUNT,
    MAX_DECISION_WALL_NS,
    MAX_PEAK_RSS_BYTES,
    MAX_TRACE_BYTES_PER_RUN,
    MEASUREMENT_MATRIX_SHA256,
    MEASUREMENT_PLAN_SHA256,
    PREDECLARATION_PATH,
    PREDECLARATION_SHA256,
    PUBLIC_PARTITION_MANIFEST_SHA256,
    ActionMeasurement,
    BoundaryCounts,
    BoundaryStatus,
    CellResult,
    CellStatus,
    DeepTrigger,
    DeepTriggerMeasurement,
    DeliberationStatus,
    EvidenceAvailability,
    FailureDomain,
    MeasurementCell,
    MeasurementVariant,
    ReasoningPath,
    ReasoningTerminalKind,
    ReasoningTerminalMeasurement,
    ScoreMeasurement,
    WorkAvailability,
    WorkMeasurement,
    build_measurement_matrix,
    build_measurement_plan,
    evaluate_materiality_gates,
    seal_canonical_object,
    validate_predeclaration_bytes,
    verify_canonical_object_hash,
)
from arc3.trace.canonical import normalize_json, sha256_bytes, sha256_json  # noqa: E402
from arc3.types import JSONValue  # noqa: E402

DEFAULT_OUTPUT = Path("C:/a/arc3-b001/artifacts/stage08/two-speed-controller-attempt-01.json")
DEFAULT_WORK_ROOT = Path("C:/a/arc3-b001/artifacts/stage08/two-speed-work-attempt-01")
DEFAULT_EXPOSURE_LEDGER = Path("C:/a/arc3-b001/artifacts/stage08/public-exposure.jsonl")
DEFAULT_RECORDINGS_ROOT = Path("C:/a/arc3-b001/recordings/stage08")
DEFAULT_ENVIRONMENTS_DIR = Path("C:/a/arc3-s15-6a0f6e5/artifacts/stage15/public-environments")
DEFAULT_BUILD_000_ROOT = Path("C:/a/arc3-stage08-build000-90ecf72")
DEFAULT_BUILD_001_ROOT = ROOT

PUBLIC_PARTITION_PATH = ROOT / "docs/evaluation/public-game-partitions.v0.1.json"
STAGE07_ACCEPTANCE_PATH = ROOT / "docs/evidence/001-07-retrodiction-decision.json"
EXPECTED_BRANCH = "build/001-local-public-recovery"
WORKER_WALL_SECONDS = 120.0
OVERALL_WALL_SECONDS = 2700.0
WINDOWS_CREATE_NEW_PROCESS_GROUP = int(getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
WORKER_SPEC_SCHEMA = "arc3.build-001.stage-08-worker-spec.v0.3"
WORKER_RESULT_SCHEMA = "arc3.build-001.stage-08-worker-result.v0.3"
PARENT_RECEIPT_SCHEMA = "arc3.build-001.stage-08-parent-cell-receipt.v0.3"
AGGREGATE_SCHEMA = "arc3.build-001.stage-08-two-speed-controller.v0.2"
PREFLIGHT_SCHEMA = "arc3.build-001.stage-08-preflight.v0.2"

_BUILD_000_EXPOSURE = (
    Path("C:/a/arc3-s15-6a0f6e5/artifacts/stage15/public-exposure.jsonl"),
    "sha256:cd9af42ed3a5ef9fa0dc201ddb10e32d2bcccee9df729aa0c7d53077c04c9ad4",
)
_STAGE03_EXPOSURE = (
    Path("C:/a/arc3-b001/artifacts/stage03/public-exposure.jsonl"),
    "sha256:e02a9fa71206170a6fe2aeefb6935ae25141e2759937657475cead4389bb17aa",
)
_STAGE07_EXPOSURE = (
    Path("C:/a/arc3-b001/artifacts/stage07/public-exposure.jsonl"),
    "sha256:4f924df44b11decb392022a927b3296e0248a02edac2c87c53899d374045f0c7",
)
_INHERITED_EXPOSURES = (
    ("build-000", *_BUILD_000_EXPOSURE),
    ("stage-03", *_STAGE03_EXPOSURE),
    ("stage-07", *_STAGE07_EXPOSURE),
)

_WORKER_RESULT_FIELDS = frozenset(
    {
        "action_sequence",
        "action_counts",
        "actions",
        "attempted_boundaries",
        "asset_after",
        "asset_before",
        "cadence",
        "cell_id",
        "cell",
        "checkpoint",
        "checkpoint_bytes",
        "completed_at",
        "configuration",
        "controller_fault_count",
        "controller_fault_identities",
        "counts",
        "development_identity",
        "environment_actions",
        "evidence_label",
        "failure",
        "failure_domain",
        "failure_phase",
        "final_observation",
        "memory",
        "network_attempt_count",
        "network_guard",
        "peak_rss_bytes",
        "primary_timing_scope",
        "receipt_integrity_valid",
        "recordings",
        "reset_boundaries",
        "reset_counts",
        "resets",
        "resources_valid",
        "returned_consequences",
        "runtime_environment",
        "runtime_identity",
        "schema",
        "score",
        "source_identity",
        "spec_hash",
        "status",
        "submitted_action_identities",
        "submitted_boundaries",
        "total_cpu_ns",
        "total_wall_ns",
        "trace",
        "validation_failures",
        "variant",
        "worker_result_hash",
    }
)
_PARENT_RECEIPT_FIELDS = frozenset(
    {
        "cell",
        "cell_id",
        "classification",
        "completed_at",
        "parent_receipt_hash",
        "raw_worker_result_path",
        "raw_worker_result_sha256",
        "recovered_after_orchestrator_interruption",
        "schema",
        "spec_hash",
        "surviving_cell_artifacts",
        "surviving_recording_artifacts",
        "supervisor",
        "supervisor_stream_artifacts",
    }
)
_SUPERVISOR_FIELDS = frozenset(
    {
        "command",
        "launch_error",
        "returncode",
        "stderr_bytes",
        "stderr_path",
        "stderr_sha256",
        "stdout_bytes",
        "stdout_path",
        "stdout_sha256",
        "timed_out",
        "timeout_seconds",
        "termination",
        "wall_ns",
    }
)
_TERMINATION_FIELDS = frozenset(
    {
        "attempted",
        "direct_fallback_used",
        "error",
        "method",
        "returncode",
        "stderr_bytes",
        "stderr_sha256",
        "stdout_bytes",
        "stdout_sha256",
    }
)


def _is_mapping(value: object) -> TypeGuard[Mapping[str, object]]:
    return isinstance(value, Mapping)


def _is_nonnegative_int(value: object) -> TypeGuard[int]:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _is_sha256(value: object) -> TypeGuard[str]:
    return (
        isinstance(value, str)
        and value.startswith("sha256:")
        and len(value) == 71
        and all(character in "0123456789abcdef" for character in value[7:])
    )


def _required_mapping(value: object, field: str) -> Mapping[str, object]:
    if not _is_mapping(value):
        raise EvaluationError(f"Stage 08 {field} must be an object")
    return value


def _required_list(value: object, field: str) -> list[object]:
    if not isinstance(value, list):
        raise EvaluationError(f"Stage 08 {field} must be an array")
    return value


def _required_string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise EvaluationError(f"Stage 08 {field} must be a non-empty string")
    return value


def _required_nonnegative_int(value: object, field: str) -> int:
    if not _is_nonnegative_int(value):
        raise EvaluationError(f"Stage 08 {field} must be a non-negative integer")
    return value


def _optional_nonnegative_int(value: object, field: str) -> int | None:
    if value is None:
        return None
    return _required_nonnegative_int(value, field)


def _sha256_file(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def _load_object(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise EvaluationError(f"Stage 08 JSON is unreadable: {path}") from error
    if not isinstance(value, dict):
        raise EvaluationError(f"Stage 08 JSON must contain an object: {path}")
    return cast(dict[str, object], value)


def _json_file_bytes(value: object) -> bytes:
    return (
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def _atomic_write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("xb") as stream:
            stream.write(_json_file_bytes(value))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _atomic_create_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(_json_file_bytes(value))
        stream.flush()
        os.fsync(stream.fileno())


def _atomic_create_bytes(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())


def _artifact_inventory(root: Path) -> dict[str, object]:
    files = (
        tuple(
            {
                "bytes": path.stat().st_size,
                "path": path.relative_to(root).as_posix(),
                "sha256": _sha256_file(path),
            }
            for path in sorted(root.rglob("*"))
            if path.is_file()
        )
        if root.is_dir()
        else ()
    )
    return {
        "aggregate_sha256": sha256_json(normalize_json(files)),
        "file_count": len(files),
        "files": list(files),
        "root": root.resolve().as_posix(),
    }


def _git(root: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(root), *arguments],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if completed.returncode != 0:
        raise EvaluationError(
            f"Stage 08 git {' '.join(arguments)} failed at {root}: {completed.stderr[:300]}"
        )
    return completed.stdout.strip()


def _git_success(root: Path, *arguments: str) -> bool:
    return (
        subprocess.run(
            ["git", "-C", str(root), *arguments],
            check=False,
            capture_output=True,
        ).returncode
        == 0
    )


def _source_identity(root: Path, *, current: bool) -> dict[str, object]:
    resolved = root.resolve()
    commit = _git(resolved, "rev-parse", "HEAD")
    tree = _git(resolved, "rev-parse", "HEAD^{tree}")
    status = _git(resolved, "status", "--porcelain=v1", "--untracked-files=all")
    branch = _git(resolved, "branch", "--show-current")
    baseline_ancestor = (
        _git_success(resolved, "merge-base", "--is-ancestor", BUILD_001_BASELINE_COMMIT, "HEAD")
        if current
        else None
    )
    predicates = {
        "branch": branch in {"", EXPECTED_BRANCH} if current else branch == "",
        "clean": status == "",
        "commit": commit != BUILD_000_PRODUCTION_COMMIT
        if current
        else commit == BUILD_000_PRODUCTION_COMMIT,
        "tree": tree != BUILD_000_PRODUCTION_TREE if current else tree == BUILD_000_PRODUCTION_TREE,
        "baseline_ancestor": baseline_ancestor is True if current else True,
    }
    return {
        "baseline_ancestor": baseline_ancestor,
        "branch": branch,
        "dirty_worktree": bool(status),
        "git_commit": commit,
        "git_tree": tree,
        "passed": all(predicates.values()),
        "predicates": predicates,
        "root": resolved.as_posix(),
        "status_porcelain": status,
    }


def _source_stable(start: Mapping[str, object], end: Mapping[str, object]) -> bool:
    fields = ("branch", "dirty_worktree", "git_commit", "git_tree", "baseline_ancestor", "root")
    return (
        start.get("passed") is True
        and end.get("passed") is True
        and all(start.get(field) == end.get(field) for field in fields)
    )


def _development_asset_identity(environments_dir: Path) -> dict[str, object]:
    directory = environments_dir.resolve() / "ar25" / "0c556536"
    metadata = directory / "metadata.json"
    if not metadata.is_file():
        return {
            "aggregate_sha256": None,
            "directory": directory.as_posix(),
            "file_count": 0,
            "passed": False,
            "source_semantically_inspected": False,
        }
    files = tuple(
        (
            path.relative_to(directory).as_posix(),
            path.stat().st_size,
            _sha256_file(path),
        )
        for path in sorted(directory.rglob("*"))
        if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc"
    )
    aggregate = sha256_bytes(_json_file_bytes(files))
    return {
        "aggregate_sha256": aggregate,
        "directory": directory.as_posix(),
        "file_count": len(files),
        "files": [{"bytes": size, "name": name, "sha256": digest} for name, size, digest in files],
        "game_id": DEVELOPMENT_GAME_ID,
        "passed": aggregate == DEVELOPMENT_ASSET_SHA256,
        "source_semantically_inspected": False,
    }


def _validate_stage08_exposures(path: Path) -> tuple[dict[str, object], ...]:
    events = PublicExposureLedger(path).events()
    matrix = build_measurement_matrix()
    expected_cells = {cell.cell_id: cell for cell in matrix}
    seen: set[str] = set()
    observed_order: list[str] = []
    for event in events:
        payload = _required_mapping(event.get("payload"), "exposure payload")
        cell_id = _required_string(payload.get("cell_id"), "exposure cell_id")
        exact = {
            "cell_id",
            "game_id",
            "partition",
            "seed",
            "spec_hash",
            "variant",
        }
        if (
            event.get("event_type") != "stage08.development_episode_started"
            or set(payload) != exact
            or cell_id not in expected_cells
            or cell_id in seen
            or payload.get("game_id") != DEVELOPMENT_GAME_ID
            or payload.get("partition") != "development"
            or payload.get("seed") != 7
            or payload.get("variant") != expected_cells[cell_id].variant.value
            or not isinstance(payload.get("spec_hash"), str)
            or not cast(str, payload.get("spec_hash"))
        ):
            raise EvaluationError("Stage 08 exposure ledger contains an undeclared boundary")
        seen.add(cell_id)
        observed_order.append(cell_id)
    expected_prefix = [cell.cell_id for cell in matrix[: len(observed_order)]]
    if observed_order != expected_prefix:
        raise EvaluationError("Stage 08 exposure ledger is not the frozen contiguous prefix")
    return tuple(cast(dict[str, object], event) for event in events)


def _holdout_integrity(exposure_ledger: Path) -> dict[str, object]:
    manifest_hash = _sha256_file(PUBLIC_PARTITION_PATH) if PUBLIC_PARTITION_PATH.is_file() else None
    inherited: list[dict[str, object]] = []
    for label, path, expected in _INHERITED_EXPOSURES:
        actual = _sha256_file(path) if path.is_file() else None
        inherited.append(
            {
                "expected_sha256": expected,
                "label": label,
                "path": path.resolve().as_posix(),
                "sha256": actual,
                "verified": actual == expected,
            }
        )
    predecessor = _load_object(STAGE07_ACCEPTANCE_PATH)
    holdout = _required_mapping(predecessor.get("holdout"), "Stage 07 holdout receipt")
    predecessor_valid = (
        predecessor.get("status") == "FAILED_INFRASTRUCTURE"
        and holdout.get("status") == "SEALED_UNCONSUMED"
        and holdout.get("public_holdout_gameplay_events") == 0
        and holdout.get("locally_acquired_holdout_assets") == 0
        and holdout.get("development_exposure_ledger_sha256") == _STAGE07_EXPOSURE[1]
    )
    current_events = _validate_stage08_exposures(exposure_ledger)
    predicates = {
        "frozen_manifest_bytes": manifest_hash == PUBLIC_PARTITION_MANIFEST_SHA256,
        "inherited_exposure_receipts": all(item["verified"] is True for item in inherited),
        "predecessor_sealed_receipt": predecessor_valid,
        "stage08_development_only": len(current_events) <= EXPECTED_CELL_COUNT,
    }
    return {
        "exposure_event_count": len(current_events),
        "inherited_exposure_ledgers": inherited,
        "manifest_loaded_as_gameplay_metadata": False,
        "manifest_sha256": manifest_hash,
        "passed": all(predicates.values()),
        "predicates": predicates,
        "public_holdout_game_ids_selected": 0,
        "public_holdout_gameplay_events": 0,
        "status": "SEALED_UNCONSUMED" if all(predicates.values()) else "VIOLATED",
    }


def _require_official_paths(
    *,
    output: Path,
    work_root: Path,
    exposure_ledger: Path,
    recordings_root: Path,
    environments_dir: Path,
    build_000_root: Path,
    build_001_root: Path,
) -> None:
    supplied = {
        "build_000_root": build_000_root,
        "environments_dir": environments_dir,
        "exposure_ledger": exposure_ledger,
        "output": output,
        "recordings_root": recordings_root,
        "work_root": work_root,
    }
    expected = {
        "build_000_root": DEFAULT_BUILD_000_ROOT,
        "environments_dir": DEFAULT_ENVIRONMENTS_DIR,
        "exposure_ledger": DEFAULT_EXPOSURE_LEDGER,
        "output": DEFAULT_OUTPUT,
        "recordings_root": DEFAULT_RECORDINGS_ROOT,
        "work_root": DEFAULT_WORK_ROOT,
    }
    mismatches = {
        key: {
            "expected": expected[key].resolve().as_posix(),
            "supplied": value.resolve().as_posix(),
        }
        for key, value in supplied.items()
        if value.resolve() != expected[key].resolve()
    }
    if mismatches:
        raise EvaluationError(
            f"official Stage 08 paths differ from the frozen contract: {mismatches}"
        )
    measured_root = build_001_root.resolve()
    if measured_root != ROOT.resolve():
        raise EvaluationError(
            "Stage 08 parent must execute from the exact measured Build 001 source root"
        )
    for protected in (
        work_root.resolve(),
        recordings_root.resolve(),
        environments_dir.resolve(),
        build_000_root.resolve(),
    ):
        overlaps = False
        try:
            measured_root.relative_to(protected)
            overlaps = True
        except ValueError:
            pass
        try:
            protected.relative_to(measured_root)
            overlaps = True
        except ValueError:
            pass
        if overlaps:
            raise EvaluationError("Stage 08 Build 001 source root overlaps another declared root")


def _runtime_identity() -> dict[str, object]:
    return {
        "cpu": platform.processor() or platform.machine() or None,
        "cpu_count": os.cpu_count(),
        "executable": str(Path(sys.executable).resolve()),
        "platform": platform.platform(),
        "python": platform.python_version(),
    }


_SOURCE_IMPORT_PROBE = r"""
import importlib.metadata
import json
from pathlib import Path
import sys

root = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(root / "src"))
import arc3
import arc3.adapters.arc_agi as adapter
import arc3.config as config
import arc3.policy as policy

adapter._load_sdk_bindings()
payload = {
    "arc3": Path(arc3.__file__).resolve().as_posix(),
    "adapter": Path(adapter.__file__).resolve().as_posix(),
    "config": Path(config.__file__).resolve().as_posix(),
    "policy": Path(policy.__file__).resolve().as_posix(),
    "packages": {
        "arc-agi": importlib.metadata.version("arc-agi"),
        "arcengine": importlib.metadata.version("arcengine"),
    },
}
sys.stdout.write(json.dumps(payload, sort_keys=True, separators=(",", ":")))
"""


def _source_import_probe(source_root: Path, *, label: str) -> dict[str, object]:
    """Import policy/config/adapter bindings from one exact clean source root."""

    resolved = source_root.resolve()
    command = (
        str(Path(sys.executable).resolve()),
        "-I",
        "-c",
        _SOURCE_IMPORT_PROBE,
        str(resolved),
    )
    started = time.perf_counter_ns()
    timed_out = False
    try:
        completed = subprocess.run(
            list(command),
            cwd=resolved,
            env=_worker_environment(),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            timeout=30.0,
            check=False,
        )
        returncode: int | None = completed.returncode
        stdout = completed.stdout
        stderr = completed.stderr
    except subprocess.TimeoutExpired as error:
        timed_out = True
        returncode = None
        stdout = bytes(error.stdout or b"")
        stderr = bytes(error.stderr or b"")
    projection: dict[str, object] | None = None
    parse_error: str | None = None
    if not timed_out and returncode == 0:
        try:
            decoded = json.loads(stdout.decode("utf-8"))
            if not isinstance(decoded, dict):
                raise ValueError("probe output is not an object")
            projection = cast(dict[str, object], decoded)
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
            parse_error = f"{type(error).__name__}: {error}"
    expected_modules = {
        "arc3": (resolved / "src/arc3/__init__.py").as_posix(),
        "adapter": (resolved / "src/arc3/adapters/arc_agi.py").as_posix(),
        "config": (resolved / "src/arc3/config.py").as_posix(),
        "policy": (resolved / "src/arc3/policy/__init__.py").as_posix(),
    }
    modules_match = projection is not None and all(
        projection.get(name) == expected for name, expected in expected_modules.items()
    )
    packages_match = projection is not None and projection.get("packages") == {
        "arc-agi": ARC_AGI_VERSION,
        "arcengine": ARCENGINE_VERSION,
    }
    passed = (
        not timed_out
        and returncode == 0
        and parse_error is None
        and modules_match
        and packages_match
    )
    return {
        "command": list(command),
        "expected_modules": expected_modules,
        "label": label,
        "modules_match": modules_match,
        "packages_match": packages_match,
        "parse_error": parse_error,
        "passed": passed,
        "projection": projection,
        "returncode": returncode,
        "source_root": resolved.as_posix(),
        "stderr_bytes": len(stderr),
        "stderr_sha256": sha256_bytes(stderr),
        "stdout_bytes": len(stdout),
        "stdout_sha256": sha256_bytes(stdout),
        "timed_out": timed_out,
        "wall_ns": max(0, time.perf_counter_ns() - started),
    }


def _official_runtime_preflight(
    *,
    build_000_root: Path = DEFAULT_BUILD_000_ROOT,
    build_001_root: Path = DEFAULT_BUILD_001_ROOT,
) -> dict[str, object]:
    """Import and bind the exact pinned SDK before any exposure is allowed."""

    packages: dict[str, str | None] = {}
    failures: list[str] = []
    for distribution, expected in (
        ("arc-agi", ARC_AGI_VERSION),
        ("arcengine", ARCENGINE_VERSION),
    ):
        try:
            observed = importlib.metadata.version(distribution)
        except importlib.metadata.PackageNotFoundError as error:
            observed = None
            failures.append(f"{distribution}:{type(error).__name__}")
        packages[distribution] = observed
        if observed is not None and observed != expected:
            failures.append(f"{distribution}:expected={expected}:observed={observed}")
    for module_name in ("arc_agi", "arcengine"):
        try:
            importlib.import_module(module_name)
        except (ImportError, ModuleNotFoundError) as error:
            failures.append(f"{module_name}:{type(error).__name__}:{error}")
    try:
        arc_agi_adapter._load_sdk_bindings()
    except Exception as error:
        failures.append(f"adapter-bindings:{type(error).__name__}:{error}")
    source_probes = {
        "build_000": _source_import_probe(build_000_root, label="build-000"),
        "build_001": _source_import_probe(build_001_root, label="build-001"),
    }
    for source_label, probe in source_probes.items():
        if probe.get("passed") is not True:
            failures.append(f"{source_label}-source-import-probe:failed")
    return {
        "adapter_bindings_valid": not failures,
        "expected_packages": {
            "arc-agi": ARC_AGI_VERSION,
            "arcengine": ARCENGINE_VERSION,
        },
        "failures": failures,
        "observed_packages": packages,
        "passed": not failures,
        "source_import_probes": source_probes,
    }


def preflight(
    *,
    output: Path = DEFAULT_OUTPUT,
    work_root: Path = DEFAULT_WORK_ROOT,
    exposure_ledger: Path = DEFAULT_EXPOSURE_LEDGER,
    recordings_root: Path = DEFAULT_RECORDINGS_ROOT,
    environments_dir: Path = DEFAULT_ENVIRONMENTS_DIR,
    build_000_root: Path = DEFAULT_BUILD_000_ROOT,
    build_001_root: Path = DEFAULT_BUILD_001_ROOT,
) -> dict[str, object]:
    """Validate all identities without opening a public environment."""

    _require_official_paths(
        output=output,
        work_root=work_root,
        exposure_ledger=exposure_ledger,
        recordings_root=recordings_root,
        environments_dir=environments_dir,
        build_000_root=build_000_root,
        build_001_root=build_001_root,
    )
    predeclaration_bytes = PREDECLARATION_PATH.read_bytes()
    validate_predeclaration_bytes(predeclaration_bytes)
    plan = build_measurement_plan()
    current_source = _source_identity(build_001_root, current=True)
    build_000_source = _source_identity(build_000_root, current=False)
    asset = _development_asset_identity(environments_dir)
    holdout = _holdout_integrity(exposure_ledger)
    official_runtime = _official_runtime_preflight(
        build_000_root=build_000_root,
        build_001_root=build_001_root,
    )
    measured_worker = build_001_root.resolve() / "scripts/_stage08_two_speed_worker.py"
    measured_harness = build_001_root.resolve() / "scripts/measure_two_speed_controller.py"
    measured_contract = build_001_root.resolve() / "src/arc3/evaluation/two_speed_measurement.py"
    executing_contract = ROOT / "src/arc3/evaluation/two_speed_measurement.py"
    worker_available = measured_worker.is_file()
    harness_available = measured_harness.is_file()
    contract_available = measured_contract.is_file()
    executing_harness = Path(__file__).resolve()
    harness_identity_matches = harness_available and _sha256_file(measured_harness) == _sha256_file(
        executing_harness
    )
    contract_identity_matches = contract_available and _sha256_file(
        measured_contract
    ) == _sha256_file(executing_contract)
    paths = {
        "build_000_root": build_000_root.resolve().as_posix(),
        "build_001_root": build_001_root.resolve().as_posix(),
        "environments_dir": environments_dir.resolve().as_posix(),
        "exposure_ledger": exposure_ledger.resolve().as_posix(),
        "output": output.resolve().as_posix(),
        "recordings_root": recordings_root.resolve().as_posix(),
        "work_root": work_root.resolve().as_posix(),
    }
    predicates = {
        "build_000_source": build_000_source["passed"] is True,
        "current_source": current_source["passed"] is True,
        "development_asset": asset["passed"] is True,
        "contract_identity": contract_identity_matches,
        "holdout_sealed": holdout["passed"] is True,
        "harness_identity": harness_identity_matches,
        "matrix_exact": len(build_measurement_matrix()) == EXPECTED_CELL_COUNT,
        "official_runtime": official_runtime["passed"] is True,
        "plan_hash": plan.get("plan_hash") == MEASUREMENT_PLAN_SHA256,
        "predeclaration_hash": _sha256_file(PREDECLARATION_PATH) == PREDECLARATION_SHA256,
        "worker_available": worker_available,
    }
    return cast(
        dict[str, object],
        seal_canonical_object(
            cast(
                dict[str, JSONValue],
                normalize_json(
                    {
                        "build_000_source": build_000_source,
                        "current_source": current_source,
                        "development_asset": asset,
                        "contract_identity": {
                            "executing_path": executing_contract.as_posix(),
                            "executing_sha256": _sha256_file(executing_contract),
                            "measured_path": measured_contract.as_posix(),
                            "measured_sha256": (
                                _sha256_file(measured_contract) if contract_available else None
                            ),
                            "passed": contract_identity_matches,
                        },
                        "execution_started": False,
                        "holdout": holdout,
                        "harness_identity": {
                            "executing_path": executing_harness.as_posix(),
                            "executing_sha256": _sha256_file(executing_harness),
                            "measured_path": measured_harness.as_posix(),
                            "measured_sha256": (
                                _sha256_file(measured_harness) if harness_available else None
                            ),
                            "passed": harness_identity_matches,
                        },
                        "matrix_hash": MEASUREMENT_MATRIX_SHA256,
                        "official_runtime": official_runtime,
                        "overall_wall_seconds": OVERALL_WALL_SECONDS,
                        "paths": paths,
                        "plan": plan,
                        "predicates": predicates,
                        "runtime_identity": _runtime_identity(),
                        "schema": PREFLIGHT_SCHEMA,
                        "status": "READY_NOT_EXECUTED" if all(predicates.values()) else "NOT_READY",
                        "worker_path": measured_worker.as_posix(),
                        "worker_sha256": _sha256_file(measured_worker)
                        if worker_available
                        else None,
                        "worker_wall_seconds": WORKER_WALL_SECONDS,
                    }
                ),
            ),
            hash_field="preflight_hash",
        ),
    )


def _cell_root(work_root: Path, cell: MeasurementCell) -> Path:
    return work_root.resolve() / "cells" / f"{cell.ordinal:02d}-{cell.cell_id}"


def _spec_path(work_root: Path, cell: MeasurementCell) -> Path:
    return work_root.resolve() / "specs" / f"{cell.ordinal:02d}-{cell.cell_id}.json"


def _parent_receipt_path(work_root: Path, cell: MeasurementCell) -> Path:
    return work_root.resolve() / "parent-receipts" / f"{cell.ordinal:02d}-{cell.cell_id}.json"


def _recordings_dir(recordings_root: Path, cell: MeasurementCell) -> Path:
    return recordings_root.resolve() / "cells" / f"{cell.ordinal:02d}-{cell.cell_id}"


def build_worker_spec(
    cell: MeasurementCell,
    *,
    work_root: Path,
    recordings_root: Path,
    environments_dir: Path,
    current_source: Mapping[str, object],
    build_000_source: Mapping[str, object],
) -> dict[str, object]:
    """Build the exact self-hashed spec consumed by the isolated worker."""

    source = (
        build_000_source
        if cell.variant is MeasurementVariant.FROZEN_BUILD_000_FULL
        else current_source
    )
    source_root = _required_string(source.get("root"), "source root")
    source_commit = _required_string(source.get("git_commit"), "source commit")
    source_tree = _required_string(source.get("git_tree"), "source tree")
    root = _cell_root(work_root, cell)
    core: dict[str, JSONValue] = {
        "cell": cell.to_dict(),
        "cell_id": cell.cell_id,
        "cell_root": root.as_posix(),
        "checkpoint_root": (root / "checkpoint").as_posix(),
        "development_identity": cell.development.to_dict(),
        "environments_dir": environments_dir.resolve().as_posix(),
        "measurement_matrix_sha256": MEASUREMENT_MATRIX_SHA256,
        "measurement_plan_sha256": MEASUREMENT_PLAN_SHA256,
        "predeclaration_sha256": PREDECLARATION_SHA256,
        "recordings_dir": _recordings_dir(recordings_root, cell).as_posix(),
        "recordings_root": recordings_root.resolve().as_posix(),
        "schema": WORKER_SPEC_SCHEMA,
        "source_commit": source_commit,
        "source_root": Path(source_root).resolve().as_posix(),
        "source_tree": source_tree,
        "trace_root": (root / "trace").as_posix(),
        "variant": cell.variant.value,
    }
    return cast(dict[str, object], seal_canonical_object(core, hash_field="spec_hash"))


def _write_or_validate_spec(path: Path, spec: Mapping[str, object]) -> None:
    if path.exists():
        if _load_object(path) != dict(spec):
            raise EvaluationError("existing Stage 08 worker spec differs from the frozen cell")
        return
    _atomic_create_json(path, spec)


def _worker_environment(environ: Mapping[str, str] | None = None) -> dict[str, str]:
    source = os.environ if environ is None else environ
    allowed = {
        "COMSPEC",
        "LD_LIBRARY_PATH",
        "NUMBER_OF_PROCESSORS",
        "PATH",
        "PATHEXT",
        "SYSTEMDRIVE",
        "SYSTEMROOT",
        "TEMP",
        "TMP",
        "VIRTUAL_ENV",
        "WINDIR",
    }
    result = {key: value for key, value in source.items() if key.upper() in allowed}
    result.update(
        {
            "ALL_PROXY": "",
            "HTTP_PROXY": "",
            "HTTPS_PROXY": "",
            "NO_PROXY": "*",
            "PIP_NO_INDEX": "1",
            "PYTHONHASHSEED": "0",
            "PYTHONNOUSERSITE": "1",
            "UV_OFFLINE": "1",
        }
    )
    return result


def _append_exposure(
    exposure_ledger: Path,
    *,
    cell: MeasurementCell,
    spec_hash: str,
) -> dict[str, object]:
    event = PublicExposureLedger(exposure_ledger).append(
        "stage08.development_episode_started",
        {
            "cell_id": cell.cell_id,
            "game_id": DEVELOPMENT_GAME_ID,
            "partition": "development",
            "seed": cell.development.seed,
            "spec_hash": spec_hash,
            "variant": cell.variant.value,
        },
    )
    return cast(dict[str, object], event)


def _terminate_process_tree(process: subprocess.Popen[bytes]) -> dict[str, object]:
    """Terminate the isolated worker process group and record the exact attempt."""

    method = "windows-taskkill-tree" if os.name == "nt" else "posix-killpg"
    stdout = b""
    stderr = b""
    returncode: int | None = None
    error_message: str | None = None
    try:
        if os.name == "nt":
            completed = subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                check=False,
                capture_output=True,
                timeout=10.0,
            )
            returncode = completed.returncode
            stdout = completed.stdout
            stderr = completed.stderr
        else:
            kill_process_group = getattr(os, "killpg", None)
            sigkill = getattr(signal, "SIGKILL", None)
            if not callable(kill_process_group) or not isinstance(sigkill, int):
                raise OSError("POSIX process-group termination is unavailable")
            kill_process_group(process.pid, sigkill)
    except (OSError, subprocess.TimeoutExpired) as error:
        error_message = f"{type(error).__name__}: {error}"
    direct_fallback = process.poll() is None
    if direct_fallback:
        process.kill()
    return {
        "attempted": True,
        "direct_fallback_used": direct_fallback,
        "error": error_message,
        "method": method,
        "returncode": returncode,
        "stderr_bytes": len(stderr),
        "stderr_sha256": sha256_bytes(stderr),
        "stdout_bytes": len(stdout),
        "stdout_sha256": sha256_bytes(stdout),
    }


def _process_tree_termination_succeeded(value: object) -> bool:
    """Return whether the platform tree-kill itself completed successfully."""

    if not _is_mapping(value) or value.get("attempted") is not True:
        return False
    if value.get("error") is not None:
        return False
    method = value.get("method")
    returncode = value.get("returncode")
    if method == "windows-taskkill-tree":
        return returncode == 0 and not isinstance(returncode, bool)
    if method == "posix-killpg":
        return returncode is None
    return False


def _supervise_worker(
    command: Sequence[str],
    *,
    environment: Mapping[str, str],
    streams_root: Path,
    timeout_seconds: float = WORKER_WALL_SECONDS,
) -> dict[str, object]:
    """Run one worker, forcibly terminate on timeout, and hash captured streams."""

    started = time.perf_counter_ns()
    timed_out = False
    launch_error: str | None = None
    returncode: int | None = None
    stdout = b""
    stderr = b""
    termination: dict[str, object] | None = None
    process: subprocess.Popen[bytes] | None = None
    try:
        if os.name == "nt":
            process = subprocess.Popen(
                list(command),
                cwd=ROOT,
                env=dict(environment),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                creationflags=WINDOWS_CREATE_NEW_PROCESS_GROUP,
            )
        else:
            process = subprocess.Popen(
                list(command),
                cwd=ROOT,
                env=dict(environment),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=True,
            )
        try:
            stdout, stderr = process.communicate(timeout=timeout_seconds)
        except subprocess.TimeoutExpired as error:
            timed_out = True
            stdout = bytes(error.stdout or b"")
            stderr = bytes(error.stderr or b"")
            termination = _terminate_process_tree(process)
            try:
                tail_out, tail_err = process.communicate(timeout=10.0)
            except subprocess.TimeoutExpired as tail_error:
                tail_out = bytes(tail_error.stdout or b"")
                tail_err = bytes(tail_error.stderr or b"")
                prior_error = termination.get("error")
                suffix = "PostTerminationCommunicateTimeout: worker pipes remained open"
                termination["error"] = f"{prior_error}; {suffix}" if prior_error else suffix
                if process.poll() is None:
                    process.kill()
                try:
                    process.wait(timeout=5.0)
                except (OSError, subprocess.TimeoutExpired):
                    pass
                for stream in (process.stdout, process.stderr):
                    if stream is not None:
                        stream.close()
            stdout = tail_out if tail_out.startswith(stdout) else stdout + tail_out
            stderr = tail_err if tail_err.startswith(stderr) else stderr + tail_err
        returncode = process.returncode
    except OSError as error:
        launch_error = f"{type(error).__name__}: {error}"
    stdout_path = streams_root.resolve() / "stdout.bin"
    stderr_path = streams_root.resolve() / "stderr.bin"
    _atomic_create_bytes(stdout_path, stdout)
    _atomic_create_bytes(stderr_path, stderr)
    return {
        "command": list(command),
        "launch_error": launch_error,
        "returncode": returncode,
        "stderr_bytes": len(stderr),
        "stderr_path": stderr_path.as_posix(),
        "stderr_sha256": sha256_bytes(stderr),
        "stdout_bytes": len(stdout),
        "stdout_path": stdout_path.as_posix(),
        "stdout_sha256": sha256_bytes(stdout),
        "timed_out": timed_out,
        "timeout_seconds": timeout_seconds,
        "termination": termination,
        "wall_ns": max(0, time.perf_counter_ns() - started),
    }


def _remaining_worker_timeout(elapsed_ns: int) -> float:
    if not _is_nonnegative_int(elapsed_ns):
        raise EvaluationError("Stage 08 elapsed wall must be a non-negative integer")
    remaining = (int(OVERALL_WALL_SECONDS * 1_000_000_000) - elapsed_ns) / 1_000_000_000
    return min(WORKER_WALL_SECONDS, max(0.0, remaining))


def _wall_resource_receipt(observed_lower_bound_ns: int, *, complete: bool) -> dict[str, object]:
    if not _is_nonnegative_int(observed_lower_bound_ns) or not isinstance(complete, bool):
        raise EvaluationError("Stage 08 wall accounting inputs are invalid")
    limit = int(OVERALL_WALL_SECONDS * 1_000_000_000)
    return {
        "cumulative_active_wall_ns": observed_lower_bound_ns if complete else None,
        "observed_lower_bound_active_wall_ns": observed_lower_bound_ns,
        "overall_wall_limit_ns": limit,
        "wall_measurement_complete": complete,
        "wall_within_limit": complete and observed_lower_bound_ns <= limit,
    }


def _parse_work(value: object) -> WorkMeasurement:
    raw = _required_mapping(value, "work measurement")
    expected = {
        "availability",
        "cache_hits",
        "cache_invalidations",
        "cache_misses",
        "compilation_invocations",
        "prediction_invocations",
        "retrodicted_transitions",
        "search_expanded_nodes",
        "simulation_invocations",
    }
    if set(raw) != expected:
        raise EvaluationError("Stage 08 work measurement fields are not exact")
    availability = WorkAvailability(_required_string(raw.get("availability"), "work availability"))
    if availability is WorkAvailability.UNAVAILABLE_AT_FROZEN_SOURCE:
        if any(raw.get(key) is not None for key in expected - {"availability"}):
            raise EvaluationError("unavailable Stage 08 work values must be null")
        return WorkMeasurement.unavailable_at_frozen_source()
    return WorkMeasurement.measured(
        prediction_invocations=_required_nonnegative_int(
            raw.get("prediction_invocations"), "prediction invocations"
        ),
        compilation_invocations=_required_nonnegative_int(
            raw.get("compilation_invocations"), "compilation invocations"
        ),
        retrodicted_transitions=_required_nonnegative_int(
            raw.get("retrodicted_transitions"), "retrodicted transitions"
        ),
        simulation_invocations=_required_nonnegative_int(
            raw.get("simulation_invocations"), "simulation invocations"
        ),
        search_expanded_nodes=_required_nonnegative_int(
            raw.get("search_expanded_nodes"), "search expanded nodes"
        ),
        cache_hits=_required_nonnegative_int(raw.get("cache_hits"), "cache hits"),
        cache_misses=_required_nonnegative_int(raw.get("cache_misses"), "cache misses"),
        cache_invalidations=_required_nonnegative_int(
            raw.get("cache_invalidations"), "cache invalidations"
        ),
    )


def _parse_reasoning_terminal(value: object) -> ReasoningTerminalMeasurement | None:
    if value is None:
        return None
    raw = _required_mapping(value, "reasoning terminal")
    expected = {"kind", "path", "path_selected_event_id", "status", "terminal_event_id"}
    if set(raw) != expected:
        raise EvaluationError("Stage 08 reasoning terminal fields are not exact")
    return ReasoningTerminalMeasurement(
        path_selected_event_id=_required_string(
            raw.get("path_selected_event_id"), "reasoning selected event"
        ),
        terminal_event_id=_required_string(
            raw.get("terminal_event_id"), "reasoning terminal event"
        ),
        path=ReasoningPath(_required_string(raw.get("path"), "reasoning terminal path")),
        kind=ReasoningTerminalKind(_required_string(raw.get("kind"), "reasoning terminal kind")),
        status=DeliberationStatus(_required_string(raw.get("status"), "reasoning terminal status")),
    )


def _parse_action(
    value: object,
    *,
    action_ordinal: int,
    submission_ordinal: int,
) -> ActionMeasurement:
    raw = _required_mapping(value, "submitted boundary")
    if (
        raw.get("action_ordinal") != action_ordinal
        or raw.get("submission_ordinal") != submission_ordinal
    ):
        raise EvaluationError("Stage 08 worker boundary ordinals changed")
    identity = _required_string(raw.get("environment_action_identity"), "action identity")
    action = _required_mapping(raw.get("action"), "raw action")
    if identity != sha256_json(normalize_json(action)):
        raise EvaluationError("Stage 08 environment action identity is invalid")
    status = BoundaryStatus(_required_string(raw.get("boundary_status"), "boundary status"))
    raw_triggers = _required_list(raw.get("deep_trigger_receipts"), "deep trigger receipts")
    triggers: list[DeepTriggerMeasurement] = []
    for item in raw_triggers:
        trigger = _required_mapping(item, "deep trigger receipt")
        if set(trigger) != {"source_event_ids", "trigger"}:
            raise EvaluationError("Stage 08 deep trigger fields are not exact")
        source_ids = _required_list(trigger.get("source_event_ids"), "deep trigger sources")
        triggers.append(
            DeepTriggerMeasurement(
                trigger=DeepTrigger(
                    _required_string(trigger.get("trigger"), "deep trigger identity")
                ),
                source_event_ids=tuple(
                    _required_string(source_id, "deep trigger source") for source_id in source_ids
                ),
            )
        )
    ordered = _required_list(raw.get("ordered_triggers"), "ordered triggers")
    if ordered != [item.trigger.value for item in triggers]:
        raise EvaluationError("Stage 08 ordered trigger projection disagrees")
    raw_path = raw.get("reasoning_path")
    reasoning_path = None if raw_path is None else ReasoningPath(_required_string(raw_path, "path"))
    return ActionMeasurement(
        action_ordinal=action_ordinal,
        submission_ordinal=submission_ordinal,
        environment_action_identity=identity,
        boundary_status=status,
        choose_wall_ns=_optional_nonnegative_int(raw.get("choose_wall_ns"), "choose wall"),
        choose_cpu_ns=_optional_nonnegative_int(raw.get("choose_cpu_ns"), "choose CPU"),
        consequence_wall_ns=_optional_nonnegative_int(
            raw.get("consequence_wall_ns"), "consequence wall"
        ),
        consequence_cpu_ns=_optional_nonnegative_int(
            raw.get("consequence_cpu_ns"), "consequence CPU"
        ),
        checkpoint_wall_ns=_optional_nonnegative_int(
            raw.get("checkpoint_wall_ns"), "checkpoint wall"
        ),
        checkpoint_cpu_ns=_optional_nonnegative_int(raw.get("checkpoint_cpu_ns"), "checkpoint CPU"),
        controller_total_wall_ns=_optional_nonnegative_int(
            raw.get("controller_total_wall_ns"), "controller total wall"
        ),
        controller_total_cpu_ns=_optional_nonnegative_int(
            raw.get("controller_total_cpu_ns"), "controller total CPU"
        ),
        work=_parse_work(raw.get("work")),
        reasoning_path=reasoning_path,
        deep_triggers=tuple(triggers),
        reasoning_terminal=_parse_reasoning_terminal(raw.get("reasoning_terminal_receipt")),
    )


def _parse_score(value: object) -> ScoreMeasurement:
    raw = _required_mapping(value, "score")
    verified = raw.get("verified")
    if not isinstance(verified, bool):
        raise EvaluationError("Stage 08 score verification is not boolean")
    if not verified:
        if set(raw) != {"completed", "levels_completed", "score", "verified"}:
            raise EvaluationError("Stage 08 unverified score fields are not exact")
        if any(raw.get(field) is not None for field in ("score", "levels_completed", "completed")):
            raise EvaluationError("Stage 08 unverified score contains claimed values")
        return ScoreMeasurement.unverified()
    expected_verified_fields = {
        "completed",
        "levels_completed",
        "official_run_actions",
        "official_run_levels_completed",
        "official_run_resets",
        "official_run_state",
        "score",
        "scorer",
        "verified",
    }
    if set(raw) != expected_verified_fields:
        raise EvaluationError("Stage 08 verified score fields are not exact")
    score = raw.get("score")
    completed = raw.get("completed")
    levels = raw.get("levels_completed")
    if isinstance(score, bool) or not isinstance(score, (int, float)):
        raise EvaluationError("Stage 08 verified score is not numeric")
    if not isinstance(completed, bool):
        raise EvaluationError("Stage 08 verified completion is not boolean")
    return ScoreMeasurement(
        verified=True,
        score=float(score),
        levels_completed=_required_nonnegative_int(levels, "levels completed"),
        completed=completed,
    )


def _parse_boundary_counts(
    value: object,
    *,
    field: str,
    boundaries: Sequence[Mapping[str, object]],
    attempted_boundaries: Sequence[Mapping[str, object]],
) -> BoundaryCounts:
    raw = _required_mapping(value, field)
    if set(raw) != {"attempted", "submitted", "returned", "acknowledged"}:
        raise EvaluationError(f"Stage 08 {field} fields are not exact")
    counts = BoundaryCounts(
        attempted=_required_nonnegative_int(raw.get("attempted"), f"{field} attempted"),
        submitted=_required_nonnegative_int(raw.get("submitted"), f"{field} submitted"),
        returned=_required_nonnegative_int(raw.get("returned"), f"{field} returned"),
        acknowledged=_required_nonnegative_int(raw.get("acknowledged"), f"{field} acknowledged"),
    )
    expected = BoundaryCounts(
        attempted=len(attempted_boundaries),
        submitted=len(boundaries),
        returned=sum(boundary.get("consequence_returned") is True for boundary in boundaries),
        acknowledged=sum(
            boundary.get("acknowledged_by_controller") is True for boundary in boundaries
        ),
    )
    if counts != expected:
        raise EvaluationError(f"Stage 08 {field} disagrees with immutable boundaries")
    return counts


def _expected_configuration(variant: MeasurementVariant) -> dict[str, object]:
    controller = {
        "artifact_root": "artifacts",
        "budgets": {
            "decision_seconds": 2.0,
            "max_actions": 8,
            "max_coordinate_candidates": 128,
            "max_resets": 8,
            "max_search_depth": 32,
            "max_search_nodes": 10_000,
            "max_trace_bytes": 268_435_456,
            "memory_megabytes": 2048,
            "wall_clock_seconds": 120.0,
        },
        "log_level": "INFO",
        "mode": "local",
        "network_enabled": False,
        "profile": "stage08-two-speed-local-public",
        "schema": "arc3.config.v0.1",
        "seed": 7,
        "trace_root": "recordings",
    }
    cadence: dict[str, object] | None = None
    if variant is not MeasurementVariant.FROZEN_BUILD_000_FULL:
        cadence_config = {
            "cache_capacity": 256,
            "maximum_fast_streak": 4,
            "mode": (
                "LEGACY_ALWAYS_DEEP"
                if variant is MeasurementVariant.BUILD_001_LEGACY_ALWAYS_DEEP
                else "TWO_SPEED"
            ),
            "prediction_cache_enabled": (
                variant is not MeasurementVariant.BUILD_001_TWO_SPEED_NO_PREDICTION_CACHE
            ),
            "repeated_no_progress_threshold": 2,
            "schema": "arc3.reasoning-cadence-config.v0.1",
        }
        cadence = {
            "config": cadence_config,
            "configuration_hash": sha256_json(normalize_json(cadence_config)),
        }
    return {
        "cadence": cadence,
        "controller": {
            "config": controller,
            "config_hash": sha256_json(normalize_json(controller)),
        },
        "controller_preset": "full",
        "variant": variant.value,
    }


def _expected_worker_failure_domain(*, phase: str, kind: str) -> FailureDomain:
    """Mirror the sealed worker's deterministic failure-domain authority."""

    if phase == "resources":
        return FailureDomain.RESOURCE
    if kind in {
        "DependencyUnavailableError",
        "ImportError",
        "ModuleNotFoundError",
        "PackageNotFoundError",
    }:
        return FailureDomain.INFRASTRUCTURE
    if phase.startswith("controller-") or phase in {"network", "worker-reset-budget"}:
        return FailureDomain.MECHANISM
    return FailureDomain.INFRASTRUCTURE


def _worker_result_errors(
    raw: Mapping[str, object],
    *,
    cell: MeasurementCell,
    spec: Mapping[str, object],
    supervisor: Mapping[str, object] | None,
) -> list[str]:
    errors: list[str] = []
    if set(raw) != _WORKER_RESULT_FIELDS:
        errors.append("worker result fields are not exact")
    if raw.get("schema") != WORKER_RESULT_SCHEMA:
        errors.append("worker result schema changed")
    if not verify_canonical_object_hash(
        cast(Mapping[str, JSONValue], raw), hash_field="worker_result_hash"
    ):
        errors.append("worker result self-hash is invalid")
    for field, expected in {
        "cell": cell.to_dict(),
        "cell_id": cell.cell_id,
        "development_identity": cell.development.to_dict(),
        "evidence_label": "local-public",
        "spec_hash": spec.get("spec_hash"),
        "variant": cell.variant.value,
    }.items():
        if raw.get(field) != expected:
            errors.append(f"worker result {field} changed")
    if raw.get("status") not in {"success", "failure"}:
        errors.append("worker result status is not terminal")
    failure_domain = raw.get("failure_domain")
    failure_phase = raw.get("failure_phase")
    if raw.get("status") == "success":
        if (
            failure_domain is not None
            or failure_phase is not None
            or raw.get("failure") is not None
        ):
            errors.append("successful worker carries failure metadata")
    elif (
        failure_domain not in {domain.value for domain in FailureDomain}
        or not isinstance(failure_phase, str)
        or not failure_phase
    ):
        errors.append("failed worker lacks a typed failure domain or phase")
    else:
        failure = raw.get("failure")
        failure_kind = failure.get("kind") if _is_mapping(failure) else None
        if not isinstance(failure_kind, str) or not failure_kind:
            errors.append("failed worker lacks a typed failure kind")
        elif (
            failure_domain
            != _expected_worker_failure_domain(
                phase=failure_phase,
                kind=failure_kind,
            ).value
        ):
            errors.append("worker failure domain disagrees with its phase and kind")
    if raw.get("configuration") != _expected_configuration(cell.variant):
        errors.append("worker controller/cadence configuration changed")
    source = raw.get("source_identity")
    if not _is_mapping(source) or source.get("exact_identity_stable") is not True:
        errors.append("worker source identity is not stable")
    else:
        for endpoint in ("start", "end"):
            identity = source.get(endpoint)
            if (
                not _is_mapping(identity)
                or identity.get("git_commit") != spec.get("source_commit")
                or identity.get("git_tree") != spec.get("source_tree")
                or identity.get("dirty_worktree") is not False
                or identity.get("source_root")
                != Path(_required_string(spec.get("source_root"), "spec source root"))
                .resolve()
                .as_posix()
            ):
                errors.append(f"worker source {endpoint} identity changed")
    for field in ("asset_before", "asset_after"):
        asset = raw.get(field)
        if (
            not _is_mapping(asset)
            or asset.get("passed") is not True
            or asset.get("aggregate_sha256") != DEVELOPMENT_ASSET_SHA256
            or asset.get("source_semantically_inspected") is not False
        ):
            errors.append(f"worker {field} identity changed")
    if raw.get("asset_before") != raw.get("asset_after"):
        errors.append("worker development asset changed during execution")
    if raw.get("network_attempt_count") != 0:
        errors.append("worker attempted network access")
    runtime_environment = raw.get("runtime_environment")
    exact_environment = {
        "ALL_PROXY": "",
        "HTTP_PROXY": "",
        "HTTPS_PROXY": "",
        "NO_PROXY": "*",
        "PIP_NO_INDEX": "1",
        "PYTHONHASHSEED": "0",
        "PYTHONNOUSERSITE": "1",
        "UV_OFFLINE": "1",
    }
    if (
        not _is_mapping(runtime_environment)
        or runtime_environment.get("passed") is not True
        or runtime_environment.get("expected") != exact_environment
        or runtime_environment.get("observed") != exact_environment
    ):
        errors.append("worker deterministic runtime environment changed")
    submitted = raw.get("submitted_boundaries")
    attempted = raw.get("attempted_boundaries")
    if not isinstance(attempted, list) or any(not _is_mapping(item) for item in attempted):
        errors.append("worker attempted boundary stream is unavailable")
    if not isinstance(submitted, list):
        errors.append("worker submitted boundary stream is unavailable")
    else:
        returned_consequences = raw.get("returned_consequences")
        if not isinstance(returned_consequences, list) or any(
            not _is_mapping(item) for item in returned_consequences
        ):
            errors.append("worker returned consequence stream is unavailable")
        identities = [
            item.get("environment_action_identity") if _is_mapping(item) else None
            for item in submitted
        ]
        if raw.get("submitted_action_identities") != identities:
            errors.append("worker submitted identity stream changed")
        action_sequence = [item.get("action") if _is_mapping(item) else None for item in submitted]
        if raw.get("action_sequence") != action_sequence:
            errors.append("worker submitted action stream changed")
        expected_returned: list[object] = []
        for item in submitted:
            if not _is_mapping(item):
                errors.append("worker submitted boundary is not an object")
                continue
            consequence_returned = item.get("consequence_returned")
            consequence = item.get("consequence")
            if consequence_returned is True:
                if not _is_mapping(consequence):
                    errors.append("returned boundary lacks its exact consequence payload")
                else:
                    expected_observation_fields = {
                        "available_actions",
                        "frame_digest",
                        "full_reset",
                        "game_id",
                        "levels_completed",
                        "returned_action",
                        "state",
                        "win_levels",
                    }
                    if (
                        set(consequence) != expected_observation_fields
                        or consequence.get("game_id") != DEVELOPMENT_GAME_ID
                        or not _is_nonnegative_int(consequence.get("levels_completed"))
                        or not _is_nonnegative_int(consequence.get("win_levels"))
                        or not isinstance(consequence.get("full_reset"), bool)
                    ):
                        errors.append("returned boundary consequence fields changed")
                    for identity_field in (
                        "consequence_event_hash",
                        "consequence_event_id",
                        "consequence_observation_event_hash",
                        "consequence_observation_event_id",
                        "trace_consequence_event_id",
                        "trace_consequence_observation_event_id",
                    ):
                        if not isinstance(item.get(identity_field), str) or not item.get(
                            identity_field
                        ):
                            errors.append(f"returned boundary lacks {identity_field}")
                    if item.get("trace_consequence_event_id") != item.get(
                        "consequence_event_id"
                    ) or item.get("trace_consequence_observation_event_id") != item.get(
                        "consequence_observation_event_id"
                    ):
                        errors.append("returned boundary trace consequence linkage changed")
                    expected_returned.append(dict(consequence))
            elif consequence is not None:
                errors.append("non-returned boundary carries a consequence payload")
        if returned_consequences != expected_returned:
            errors.append("worker returned consequence payload/order changed")
        final_observation = raw.get("final_observation")
        if expected_returned and final_observation != expected_returned[-1]:
            errors.append("worker final observation is not the last returned consequence")
        projected_actions = [
            item for item in submitted if _is_mapping(item) and item.get("is_reset") is False
        ]
        projected_resets = [
            item for item in submitted if _is_mapping(item) and item.get("is_reset") is True
        ]
        if (
            raw.get("actions") != projected_actions
            or raw.get("reset_boundaries") != projected_resets
        ):
            errors.append("worker reset/non-reset partition changed")
        if isinstance(attempted, list):
            attempted_actions = [
                item for item in attempted if _is_mapping(item) and item.get("is_reset") is False
            ]
            attempted_resets = [
                item for item in attempted if _is_mapping(item) and item.get("is_reset") is True
            ]
            try:
                action_counts = _parse_boundary_counts(
                    raw.get("action_counts"),
                    field="action counts",
                    boundaries=projected_actions,
                    attempted_boundaries=attempted_actions,
                )
                reset_counts = _parse_boundary_counts(
                    raw.get("reset_counts"),
                    field="reset counts",
                    boundaries=projected_resets,
                    attempted_boundaries=attempted_resets,
                )
                if raw.get("environment_actions") != action_counts.submitted:
                    errors.append("worker environment action count changed")
                if raw.get("resets") != reset_counts.submitted:
                    errors.append("worker reset count changed")
            except EvaluationError as error:
                errors.append(str(error))
    counts = raw.get("counts")
    if not _is_mapping(counts):
        errors.append("worker raw phase counts are unavailable")
    elif isinstance(submitted, list):
        if counts.get("adapter_submissions") != len(submitted):
            errors.append("worker submitted boundary count changed")
        returned = sum(
            item.get("consequence_returned") is True for item in submitted if _is_mapping(item)
        )
        acknowledged = sum(
            item.get("acknowledged_by_controller") is True
            for item in submitted
            if _is_mapping(item)
        )
        if (
            counts.get("returned_consequences") != returned
            or counts.get("acknowledged_consequences") != acknowledged
        ):
            errors.append("worker return/acknowledgment counts changed")
        decision_attempts = counts.get("decision_attempts")
        classified_attempts = counts.get("classified_attempts")
        unclassified_attempts = counts.get("unclassified_attempts")
        if (
            not _is_nonnegative_int(decision_attempts)
            or not _is_nonnegative_int(classified_attempts)
            or not _is_nonnegative_int(unclassified_attempts)
            or classified_attempts + unclassified_attempts != decision_attempts
            or (isinstance(attempted, list) and classified_attempts != len(attempted))
        ):
            errors.append("worker attempted-decision accounting changed")
    raw_fault_ids = raw.get("controller_fault_identities")
    if (
        not isinstance(raw_fault_ids, list)
        or any(not isinstance(item, str) or not item for item in raw_fault_ids)
        or len(set(raw_fault_ids)) != len(raw_fault_ids)
        or raw.get("controller_fault_count") != len(raw_fault_ids)
    ):
        errors.append("worker controller fault identities changed")
    memory = raw.get("memory")
    peak_rss = raw.get("peak_rss_bytes")
    memory_valid = False
    if not _is_mapping(memory):
        errors.append("worker memory receipt is unavailable")
    else:
        source = memory.get("source")
        sources = memory.get("sources")
        sample_count = memory.get("sample_count")
        invalid_count = memory.get("invalid_sample_count")
        memory_valid = (
            memory.get("measurement_valid") is True
            and _is_nonnegative_int(peak_rss)
            and peak_rss == memory.get("peak_rss_bytes")
            and _is_nonnegative_int(sample_count)
            and sample_count > 0
            and invalid_count == 0
            and isinstance(source, str)
            and bool(source)
            and sources == [source]
        )
        if memory.get("measurement_valid") is not memory_valid:
            errors.append("worker RSS measurement validity changed")
        if peak_rss != memory.get("peak_rss_bytes"):
            errors.append("worker top-level and nested peak RSS disagree")
    score = raw.get("score")
    final_observation = raw.get("final_observation")
    if _is_mapping(score) and score.get("verified") is True:
        if (
            score.get("official_run_actions") != raw.get("environment_actions")
            or score.get("official_run_resets") != raw.get("resets")
            or not _is_mapping(final_observation)
            or score.get("official_run_state") != final_observation.get("state")
            or score.get("official_run_levels_completed")
            != final_observation.get("levels_completed")
            or score.get("levels_completed") != final_observation.get("levels_completed")
        ):
            errors.append("worker verified score disagrees with its execution")
    elif raw.get("status") == "success":
        errors.append("successful worker lacks a verified score")
    if raw.get("status") == "success":
        checkpoint = raw.get("checkpoint")
        trace = raw.get("trace")
        recordings = raw.get("recordings")
        if not _is_mapping(checkpoint) or checkpoint.get("restore_valid") is not True:
            errors.append("successful worker checkpoint did not restore")
        if not _is_mapping(trace) or trace.get("replay_verified") is not True:
            errors.append("successful worker trace did not replay")
        recording_count = recordings.get("file_count") if _is_mapping(recordings) else None
        if not _is_nonnegative_int(recording_count) or recording_count == 0:
            errors.append("successful worker recording is unavailable")
    recordings = raw.get("recordings")
    recordings_dir = Path(_required_string(spec.get("recordings_dir"), "recordings dir"))
    expected_recordings = _artifact_inventory(recordings_dir)
    expected_recordings["path"] = expected_recordings.pop("root")
    if recordings != expected_recordings:
        errors.append("worker external recording identity changed")
    trace = raw.get("trace")
    if (
        not _is_mapping(trace)
        or trace.get("path")
        != Path(_required_string(spec.get("trace_root"), "trace root")).resolve().as_posix()
    ):
        errors.append("worker immutable trace path changed")
    checkpoint = raw.get("checkpoint")
    if _is_mapping(checkpoint) and checkpoint.get("restore_valid") is True:
        checkpoint_path_value = checkpoint.get("path")
        try:
            checkpoint_path = Path(_required_string(checkpoint_path_value, "checkpoint path"))
            checkpoint_path.resolve().relative_to(
                Path(_required_string(spec.get("checkpoint_root"), "checkpoint root")).resolve()
            )
        except (EvaluationError, ValueError):
            errors.append("worker checkpoint path escaped its sealed root")
    trace_bytes = trace.get("byte_length") if _is_mapping(trace) else None
    total_wall_ns = raw.get("total_wall_ns")
    decision_timings_valid = isinstance(submitted, list) and all(
        _is_mapping(item)
        and _is_nonnegative_int(item.get("choose_wall_ns"))
        and cast(int, item["choose_wall_ns"]) <= MAX_DECISION_WALL_NS
        for item in submitted
    )
    recomputed_resources_valid = (
        memory_valid
        and _is_nonnegative_int(peak_rss)
        and peak_rss <= MAX_PEAK_RSS_BYTES
        and _is_nonnegative_int(trace_bytes)
        and trace_bytes <= MAX_TRACE_BYTES_PER_RUN
        and decision_timings_valid
        and _is_nonnegative_int(total_wall_ns)
        and total_wall_ns <= int(WORKER_WALL_SECONDS * 1_000_000_000)
    )
    if raw.get("resources_valid") is not recomputed_resources_valid:
        errors.append("worker resource validity does not match recomputed evidence")
    if supervisor is not None and supervisor.get("timed_out") is not True:
        returncode = supervisor.get("returncode")
        if raw.get("status") == "success" and returncode not in {0, None}:
            errors.append("successful worker has a nonzero supervisor return code")
        if raw.get("status") == "failure" and returncode not in {1, None}:
            errors.append("failed worker has an unexpected supervisor return code")
    return errors


def _project_worker_result(
    raw: Mapping[str, object],
    *,
    cell: MeasurementCell,
    spec: Mapping[str, object],
    supervisor: Mapping[str, object] | None = None,
    holdout_exposure_count: int = 0,
) -> CellResult:
    """Fail closed while projecting an exact raw worker receipt to v0.3."""

    errors = _worker_result_errors(raw, cell=cell, spec=spec, supervisor=supervisor)
    if errors:
        raise EvaluationError("; ".join(errors))
    submitted_raw = _required_list(raw.get("submitted_boundaries"), "submitted boundaries")
    actions: list[ActionMeasurement] = []
    resets: list[ActionMeasurement] = []
    action_raw: list[Mapping[str, object]] = []
    reset_raw: list[Mapping[str, object]] = []
    attempted_raw = _required_list(raw.get("attempted_boundaries"), "attempted boundaries")
    attempted_actions = [
        _required_mapping(item, "attempted boundary")
        for item in attempted_raw
        if _required_mapping(item, "attempted boundary").get("is_reset") is False
    ]
    attempted_resets = [
        _required_mapping(item, "attempted boundary")
        for item in attempted_raw
        if _required_mapping(item, "attempted boundary").get("is_reset") is True
    ]
    for submission_ordinal, item in enumerate(submitted_raw):
        boundary = _required_mapping(item, "submitted boundary")
        if boundary.get("action_chain_valid") is not True:
            raise EvaluationError("Stage 08 submitted boundary action chain is invalid")
        is_reset = boundary.get("is_reset")
        if not isinstance(is_reset, bool):
            raise EvaluationError("Stage 08 submitted boundary reset kind is unavailable")
        collection = resets if is_reset else actions
        raw_collection = reset_raw if is_reset else action_raw
        collection.append(
            _parse_action(
                boundary,
                action_ordinal=len(collection),
                submission_ordinal=submission_ordinal,
            )
        )
        raw_collection.append(boundary)
    memory = _required_mapping(raw.get("memory"), "memory receipt")
    memory_valid = memory.get("measurement_valid") is True
    raw_memory_source = memory.get("source")
    memory_source: str | None = raw_memory_source if isinstance(raw_memory_source, str) else None
    peak_rss = _optional_nonnegative_int(raw.get("peak_rss_bytes"), "peak RSS")
    trace = _required_mapping(raw.get("trace"), "trace receipt")
    checkpoint = _required_mapping(raw.get("checkpoint"), "checkpoint receipt")
    final_observation = raw.get("final_observation")
    raw_terminal_state = final_observation.get("state") if _is_mapping(final_observation) else None
    terminal_state: str | None = raw_terminal_state if isinstance(raw_terminal_state, str) else None
    raw_fault_ids = _required_list(raw.get("controller_fault_identities"), "fault identities")
    fault_ids = tuple(_required_string(value, "fault identity") for value in raw_fault_ids)
    failure = raw.get("failure")
    failure_kind = None
    failure_domain = None
    failure_phase = None
    if raw.get("status") != "success":
        failure_map = _required_mapping(failure, "worker failure")
        failure_kind = _required_string(failure_map.get("kind"), "worker failure kind")
        failure_domain = FailureDomain(
            _required_string(raw.get("failure_domain"), "worker failure domain")
        )
        failure_phase = _required_string(raw.get("failure_phase"), "worker failure phase")
    return CellResult(
        cell=cell,
        status=CellStatus.SUCCESS if raw.get("status") == "success" else CellStatus.FAILURE,
        actions=tuple(actions),
        reset_boundaries=tuple(resets),
        score=_parse_score(raw.get("score")),
        action_counts=_parse_boundary_counts(
            raw.get("action_counts"),
            field="action counts",
            boundaries=action_raw,
            attempted_boundaries=attempted_actions,
        ),
        reset_counts=_parse_boundary_counts(
            raw.get("reset_counts"),
            field="reset counts",
            boundaries=reset_raw,
            attempted_boundaries=attempted_resets,
        ),
        evidence_availability=EvidenceAvailability.EXACT,
        peak_rss_bytes=peak_rss,
        memory_measurement_valid=memory_valid,
        memory_measurement_source=memory_source,
        trace_bytes=_required_nonnegative_int(trace.get("byte_length"), "trace bytes"),
        checkpoint_bytes=_required_nonnegative_int(raw.get("checkpoint_bytes"), "checkpoint bytes"),
        terminal_state=terminal_state,
        controller_faults=_required_nonnegative_int(
            raw.get("controller_fault_count"), "controller fault count"
        ),
        controller_fault_identities=fault_ids,
        source_identity_valid=True,
        receipt_integrity_valid=raw.get("receipt_integrity_valid") is True,
        replay_valid=trace.get("replay_verified") is True,
        checkpoint_valid=checkpoint.get("restore_valid") is True,
        network_attempt_count=_required_nonnegative_int(
            raw.get("network_attempt_count"), "network attempt count"
        ),
        holdout_exposure_count=holdout_exposure_count,
        failure_kind=failure_kind,
        failure_domain=failure_domain,
        failure_phase=failure_phase,
    )


def _synthetic_failure_result(
    cell: MeasurementCell,
    *,
    status: CellStatus,
    failure_kind: str,
    failure_phase: str,
    failure_domain: FailureDomain = FailureDomain.INFRASTRUCTURE,
    holdout_exposure_count: int = 0,
) -> CellResult:
    return CellResult(
        cell=cell,
        status=status,
        actions=(),
        reset_boundaries=(),
        score=ScoreMeasurement.unverified(),
        action_counts=None,
        reset_counts=None,
        evidence_availability=EvidenceAvailability.UNAVAILABLE,
        peak_rss_bytes=None,
        memory_measurement_valid=False,
        memory_measurement_source=None,
        trace_bytes=None,
        checkpoint_bytes=None,
        terminal_state=None,
        controller_faults=None,
        controller_fault_identities=(),
        source_identity_valid=False,
        receipt_integrity_valid=False,
        replay_valid=False,
        checkpoint_valid=False,
        network_attempt_count=None,
        holdout_exposure_count=holdout_exposure_count,
        failure_kind=failure_kind,
        failure_domain=failure_domain,
        failure_phase=failure_phase,
    )


def _seal_parent_receipt(payload: Mapping[str, object]) -> dict[str, object]:
    normalized = cast(dict[str, JSONValue], normalize_json(dict(payload)))
    return cast(
        dict[str, object], seal_canonical_object(normalized, hash_field="parent_receipt_hash")
    )


def _validate_parent_receipt(
    receipt: Mapping[str, object],
    *,
    cell: MeasurementCell,
    spec: Mapping[str, object],
    raw_path: Path,
) -> None:
    if set(receipt) != _PARENT_RECEIPT_FIELDS:
        raise EvaluationError("Stage 08 parent cell receipt fields are not exact")
    if receipt.get("schema") != PARENT_RECEIPT_SCHEMA or not verify_canonical_object_hash(
        cast(Mapping[str, JSONValue], receipt), hash_field="parent_receipt_hash"
    ):
        raise EvaluationError("Stage 08 parent cell receipt is invalid")
    if (
        receipt.get("cell") != cell.to_dict()
        or receipt.get("cell_id") != cell.cell_id
        or receipt.get("spec_hash") != spec.get("spec_hash")
        or receipt.get("raw_worker_result_path") != raw_path.resolve().as_posix()
    ):
        raise EvaluationError("Stage 08 parent cell receipt identity changed")
    recovered = receipt.get("recovered_after_orchestrator_interruption")
    if not isinstance(recovered, bool):
        raise EvaluationError("Stage 08 parent receipt recovery flag is not boolean")
    supervisor = receipt.get("supervisor")
    raw_hash = receipt.get("raw_worker_result_sha256")
    if raw_hash is not None and not _is_sha256(raw_hash):
        raise EvaluationError("Stage 08 parent raw worker hash is invalid")
    if supervisor is None:
        if not recovered:
            raise EvaluationError("unsupervised Stage 08 receipt must be an interruption recovery")
        expected_classification = "interrupted"
    elif _is_mapping(supervisor):
        if recovered:
            raise EvaluationError("supervised Stage 08 receipt cannot be marked recovered")
        if set(supervisor) != _SUPERVISOR_FIELDS:
            raise EvaluationError("Stage 08 supervisor receipt fields are not exact")
        command = supervisor.get("command")
        timed_out = supervisor.get("timed_out")
        launch_error = supervisor.get("launch_error")
        returncode = supervisor.get("returncode")
        timeout_seconds = supervisor.get("timeout_seconds")
        if (
            not isinstance(command, list)
            or not command
            or any(not isinstance(part, str) or not part for part in command)
            or not isinstance(timed_out, bool)
            or (launch_error is not None and not isinstance(launch_error, str))
            or (
                returncode is not None
                and (not isinstance(returncode, int) or isinstance(returncode, bool))
            )
            or not isinstance(timeout_seconds, (int, float))
            or isinstance(timeout_seconds, bool)
            or not 0.0 < float(timeout_seconds) <= WORKER_WALL_SECONDS
            or not _is_nonnegative_int(supervisor.get("wall_ns"))
        ):
            raise EvaluationError("Stage 08 supervisor outcome fields are invalid")
        for stream in ("stdout", "stderr"):
            if (
                not _is_nonnegative_int(supervisor.get(f"{stream}_bytes"))
                or not isinstance(supervisor.get(f"{stream}_path"), str)
                or not cast(str, supervisor.get(f"{stream}_path"))
                or not _is_sha256(supervisor.get(f"{stream}_sha256"))
            ):
                raise EvaluationError("Stage 08 supervisor stream receipt is invalid")
        if raw_hash is not None:
            if timed_out or launch_error is not None or returncode is None:
                raise EvaluationError(
                    "Stage 08 terminal raw result conflicts with its supervisor outcome"
                )
            expected_classification = "worker-result"
        elif timed_out:
            if launch_error is not None or returncode is None:
                raise EvaluationError("Stage 08 timeout supervisor outcome is inconsistent")
            expected_classification = None
        elif launch_error is not None:
            if returncode is not None:
                raise EvaluationError("Stage 08 launch-error supervisor outcome is inconsistent")
            expected_classification = "launch-error"
        else:
            if returncode is None:
                raise EvaluationError("Stage 08 missing-result supervisor outcome is inconsistent")
            expected_classification = "missing-result"
        termination = supervisor.get("termination")
        if timed_out:
            if not _is_mapping(termination) or set(termination) != _TERMINATION_FIELDS:
                raise EvaluationError("Stage 08 timeout lacks exact process-tree termination")
            termination_returncode = termination.get("returncode")
            if (
                termination.get("attempted") is not True
                or termination.get("method") not in {"windows-taskkill-tree", "posix-killpg"}
                or not isinstance(termination.get("direct_fallback_used"), bool)
                or (
                    termination.get("error") is not None
                    and not isinstance(termination.get("error"), str)
                )
                or (
                    termination_returncode is not None
                    and (
                        not isinstance(termination_returncode, int)
                        or isinstance(termination_returncode, bool)
                    )
                )
                or any(
                    not _is_nonnegative_int(termination.get(f"{stream}_bytes"))
                    or not _is_sha256(termination.get(f"{stream}_sha256"))
                    for stream in ("stdout", "stderr")
                )
            ):
                raise EvaluationError("Stage 08 process-tree termination receipt is invalid")
            expected_classification = (
                "timeout"
                if _process_tree_termination_succeeded(termination)
                else "termination-failure"
            )
        elif termination is not None:
            raise EvaluationError("Stage 08 non-timeout cannot carry termination evidence")
    else:
        raise EvaluationError("Stage 08 parent supervisor must be an object or null")
    if receipt.get("classification") != expected_classification:
        raise EvaluationError("Stage 08 parent receipt classification was not recomputed exactly")


def _result_from_receipt(
    *,
    cell: MeasurementCell,
    spec: Mapping[str, object],
    receipt: Mapping[str, object],
    cell_root: Path,
    streams_root: Path,
    holdout_exposure_count: int,
    exposure_spec_hash: str | None,
) -> tuple[CellResult, list[str], dict[str, object] | None]:
    exposure_error = (
        []
        if exposure_spec_hash == spec.get("spec_hash")
        else ["matching development exposure event is missing or changed"]
    )
    raw_path = cell_root / "worker-result.json"
    parent_receipt_valid = True
    try:
        _validate_parent_receipt(receipt, cell=cell, spec=spec, raw_path=raw_path)
    except EvaluationError as error:
        exposure_error.append(str(error))
        parent_receipt_valid = False
    classification = receipt.get("classification") if parent_receipt_valid else "invalid-receipt"
    raw: dict[str, object] | None = None
    errors: list[str] = list(exposure_error)
    declared_cell_inventory = receipt.get("surviving_cell_artifacts")
    if declared_cell_inventory != _artifact_inventory(cell_root):
        errors.append("surviving worker artifact inventory changed")
    if receipt.get("supervisor_stream_artifacts") != _artifact_inventory(streams_root):
        errors.append("supervisor stream artifact inventory changed")
    recordings_dir = Path(_required_string(spec.get("recordings_dir"), "recordings dir"))
    if receipt.get("surviving_recording_artifacts") != _artifact_inventory(recordings_dir):
        errors.append("surviving external recording artifact inventory changed")
    supervisor_value = receipt.get("supervisor")
    if _is_mapping(supervisor_value):
        for stream in ("stdout", "stderr"):
            stream_path_value = supervisor_value.get(f"{stream}_path")
            if not isinstance(stream_path_value, str):
                errors.append(f"supervisor {stream} path is unavailable")
                continue
            stream_path = Path(stream_path_value).resolve()
            if (
                stream_path.parent != streams_root.resolve()
                or not stream_path.is_file()
                or supervisor_value.get(f"{stream}_sha256") != _sha256_file(stream_path)
                or supervisor_value.get(f"{stream}_bytes") != stream_path.stat().st_size
            ):
                errors.append(f"supervisor {stream} bytes changed")
    if raw_path.is_file():
        raw = _load_object(raw_path)
        if receipt.get("raw_worker_result_sha256") != _sha256_file(raw_path):
            errors.append("raw worker result file hash changed")
    elif receipt.get("raw_worker_result_sha256") is not None:
        errors.append("raw worker result is missing")
    if classification == "timeout":
        return (
            _synthetic_failure_result(
                cell,
                status=CellStatus.TIMEOUT,
                failure_kind="WorkerTimeout",
                failure_phase="supervisor-timeout",
                failure_domain=FailureDomain.RESOURCE,
                holdout_exposure_count=holdout_exposure_count,
            ),
            errors,
            raw,
        )
    if classification in {
        "interrupted",
        "launch-error",
        "missing-result",
        "termination-failure",
    }:
        return (
            _synthetic_failure_result(
                cell,
                status=(
                    CellStatus.INTERRUPTED if classification == "interrupted" else CellStatus.CRASH
                ),
                failure_kind=str(classification),
                failure_phase=f"supervisor-{classification}",
                holdout_exposure_count=holdout_exposure_count,
            ),
            errors,
            raw,
        )
    if raw is None:
        errors.append("raw worker result is unavailable")
    if not errors and raw is not None:
        supervisor = receipt.get("supervisor")
        try:
            result = _project_worker_result(
                raw,
                cell=cell,
                spec=spec,
                supervisor=(supervisor if _is_mapping(supervisor) else None),
                holdout_exposure_count=holdout_exposure_count,
            )
            return result, [], raw
        except (EvaluationError, ValueError) as error:
            errors.append(f"{type(error).__name__}: {error}")
    return (
        _synthetic_failure_result(
            cell,
            status=CellStatus.CRASH,
            failure_kind="WorkerResultValidationError",
            failure_phase="parent-worker-result-validation",
            holdout_exposure_count=holdout_exposure_count,
        ),
        errors,
        raw,
    )


def _make_parent_receipt(
    *,
    cell: MeasurementCell,
    spec: Mapping[str, object],
    supervisor: Mapping[str, object],
    raw_path: Path,
    streams_root: Path,
) -> dict[str, object]:
    raw_hash = _sha256_file(raw_path) if raw_path.is_file() else None
    if raw_hash is not None:
        classification = "worker-result"
    elif supervisor.get("timed_out") is True:
        classification = (
            "timeout"
            if _process_tree_termination_succeeded(supervisor.get("termination"))
            else "termination-failure"
        )
    elif supervisor.get("launch_error") is not None:
        classification = "launch-error"
    else:
        classification = "missing-result"
    return _seal_parent_receipt(
        {
            "cell": cell.to_dict(),
            "cell_id": cell.cell_id,
            "classification": classification,
            "completed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "raw_worker_result_path": raw_path.resolve().as_posix(),
            "raw_worker_result_sha256": raw_hash,
            "recovered_after_orchestrator_interruption": False,
            "schema": PARENT_RECEIPT_SCHEMA,
            "spec_hash": spec.get("spec_hash"),
            "surviving_cell_artifacts": _artifact_inventory(raw_path.parent),
            "surviving_recording_artifacts": _artifact_inventory(
                Path(_required_string(spec.get("recordings_dir"), "recordings dir"))
            ),
            "supervisor": supervisor,
            "supervisor_stream_artifacts": _artifact_inventory(streams_root),
        }
    )


def _interrupted_parent_receipt(
    *,
    cell: MeasurementCell,
    spec: Mapping[str, object],
    raw_path: Path,
    streams_root: Path,
) -> dict[str, object]:
    return _seal_parent_receipt(
        {
            "cell": cell.to_dict(),
            "cell_id": cell.cell_id,
            "classification": "interrupted",
            "completed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "raw_worker_result_path": raw_path.resolve().as_posix(),
            "raw_worker_result_sha256": (_sha256_file(raw_path) if raw_path.is_file() else None),
            "recovered_after_orchestrator_interruption": True,
            "schema": PARENT_RECEIPT_SCHEMA,
            "spec_hash": spec.get("spec_hash"),
            "surviving_cell_artifacts": _artifact_inventory(raw_path.parent),
            "surviving_recording_artifacts": _artifact_inventory(
                Path(_required_string(spec.get("recordings_dir"), "recordings dir"))
            ),
            "supervisor": None,
            "supervisor_stream_artifacts": _artifact_inventory(streams_root),
        }
    )


def _existing_exposure_cells(exposure_ledger: Path) -> dict[str, str]:
    events = _validate_stage08_exposures(exposure_ledger)
    return {
        cast(str, cast(Mapping[str, object], event["payload"])["cell_id"]): cast(
            str, cast(Mapping[str, object], event["payload"])["spec_hash"]
        )
        for event in events
    }


def _surviving_receipt_preflight_errors(
    *,
    matrix: Sequence[MeasurementCell],
    specs_by_id: Mapping[str, Mapping[str, object]],
    exposure_cells: Mapping[str, str],
    work_root: Path,
) -> list[str]:
    """Read every surviving parent receipt before any fresh worker can launch."""

    errors: list[str] = []
    receipt_root = work_root.resolve() / "parent-receipts"
    expected_paths = {_parent_receipt_path(work_root, cell).resolve(): cell for cell in matrix}
    observed_paths = (
        tuple(path.resolve() for path in sorted(receipt_root.rglob("*")) if path.is_file())
        if receipt_root.is_dir()
        else ()
    )
    for path in observed_paths:
        cell = expected_paths.get(path)
        if cell is None:
            errors.append(f"unexpected surviving parent receipt: {path.as_posix()}")
            continue
        if cell.cell_id not in exposure_cells:
            errors.append(f"unexposed cell has a surviving parent receipt: {cell.cell_id}")
            continue
        spec = specs_by_id[cell.cell_id]
        spec_path = _spec_path(work_root, cell)
        if not spec_path.is_file():
            errors.append(f"surviving receipt lacks its sealed worker spec: {cell.cell_id}")
            continue
        try:
            if _load_object(spec_path) != dict(spec):
                errors.append(f"surviving receipt worker spec changed: {cell.cell_id}")
                continue
            receipt = _load_object(path)
            _result, receipt_errors, _raw = _result_from_receipt(
                cell=cell,
                spec=spec,
                receipt=receipt,
                cell_root=_cell_root(work_root, cell),
                streams_root=(
                    work_root.resolve() / "parent-streams" / f"{cell.ordinal:02d}-{cell.cell_id}"
                ),
                holdout_exposure_count=0,
                exposure_spec_hash=exposure_cells.get(cell.cell_id),
            )
        except (EvaluationError, ValueError) as error:
            errors.append(
                f"surviving receipt validation failed for {cell.cell_id}: "
                f"{type(error).__name__}: {error}"
            )
            continue
        errors.extend(f"{cell.cell_id}: {error}" for error in receipt_errors)
    return errors


def _load_existing_aggregate(output: Path) -> dict[str, object] | None:
    if not output.exists():
        return None
    aggregate = _load_object(output)
    if aggregate.get("schema") != AGGREGATE_SCHEMA or not verify_canonical_object_hash(
        cast(Mapping[str, JSONValue], aggregate), hash_field="artifact_core_hash"
    ):
        raise EvaluationError("existing Stage 08 aggregate is invalid and cannot be resumed")
    return aggregate


def _aggregate_payload(
    *,
    command_history: Sequence[Sequence[str]],
    current_start: Mapping[str, object],
    build_000_start: Mapping[str, object],
    asset_start: Mapping[str, object],
    holdout_start: Mapping[str, object],
    preflight_receipt: Mapping[str, object],
    output: Path,
    work_root: Path,
    exposure_ledger: Path,
    recordings_root: Path,
    environments_dir: Path,
    build_000_root: Path,
    build_001_root: Path,
    results: Sequence[CellResult],
    records: Sequence[Mapping[str, object]],
    projection_failures: Sequence[Mapping[str, object]],
    base_wall_ns: int,
    invocation_started_ns: int | None,
    wall_measurement_complete: bool,
    final: bool,
) -> dict[str, object]:
    current_end = _source_identity(build_001_root, current=True)
    build_000_end = _source_identity(build_000_root, current=False)
    asset_end = _development_asset_identity(environments_dir)
    holdout_end = _holdout_integrity(exposure_ledger)
    source_valid = _source_stable(current_start, current_end) and _source_stable(
        build_000_start, build_000_end
    )
    asset_valid = asset_start == asset_end and asset_end.get("passed") is True
    holdout_valid = holdout_start.get("passed") is True and holdout_end.get("passed") is True
    adjusted = tuple(
        replace(
            result,
            source_identity_valid=result.source_identity_valid and source_valid,
            holdout_exposure_count=(0 if holdout_valid else 1),
        )
        for result in results
    )
    gate = evaluate_materiality_gates(adjusted)
    invocation_wall_ns = (
        0
        if invocation_started_ns is None
        else max(0, time.perf_counter_ns() - invocation_started_ns)
    )
    cumulative_wall_ns = base_wall_ns + invocation_wall_ns
    matrix_complete = len(adjusted) == EXPECTED_CELL_COUNT
    infrastructure_classifications = {"interrupted", "launch-error", "missing-result"}
    infrastructure_failure = (
        bool(projection_failures)
        or any(result.failure_domain is FailureDomain.INFRASTRUCTURE for result in adjusted)
        or any(
            _is_mapping(record.get("parent_receipt"))
            and cast(Mapping[str, object], record["parent_receipt"]).get("classification")
            in infrastructure_classifications
            for record in records
        )
        or not wall_measurement_complete
        or not (source_valid and asset_valid and holdout_valid)
    )
    if not final:
        status = "IN_PROGRESS"
    elif (
        gate.passed
        and not infrastructure_failure
        and cumulative_wall_ns <= int(OVERALL_WALL_SECONDS * 1_000_000_000)
    ):
        status = "PASS"
    elif infrastructure_failure:
        status = "FAILED_INFRASTRUCTURE"
    elif matrix_complete:
        status = "FAILED_MECHANISM"
    else:
        status = "PARTIAL"
    payload = cast(
        dict[str, JSONValue],
        normalize_json(
            {
                "asset_end": asset_end,
                "asset_start": asset_start,
                "build_000_source_end": build_000_end,
                "build_000_source_start": build_000_start,
                "cell_records": list(records),
                "commands": [list(command) for command in command_history],
                "completed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "configuration": {
                    "execution": "serial",
                    "expected_cell_count": EXPECTED_CELL_COUNT,
                    "network_enabled": False,
                    "overall_wall_seconds": OVERALL_WALL_SECONDS,
                    "worker_wall_seconds": WORKER_WALL_SECONDS,
                },
                "current_source_end": current_end,
                "current_source_start": current_start,
                "evidence_label": "local-public",
                "execution_complete": matrix_complete and wall_measurement_complete,
                "gate": gate.to_dict(),
                "holdout_end": holdout_end,
                "holdout_start": holdout_start,
                "matrix": [cell.to_dict() for cell in build_measurement_matrix()],
                "matrix_hash": MEASUREMENT_MATRIX_SHA256,
                "paths": {
                    "build_000_root": build_000_root.resolve().as_posix(),
                    "build_001_root": build_001_root.resolve().as_posix(),
                    "environments_dir": environments_dir.resolve().as_posix(),
                    "exposure_ledger": exposure_ledger.resolve().as_posix(),
                    "output": output.resolve().as_posix(),
                    "recordings_root": recordings_root.resolve().as_posix(),
                    "work_root": work_root.resolve().as_posix(),
                },
                "plan": build_measurement_plan(),
                "preflight": dict(preflight_receipt),
                "projection_failures": list(projection_failures),
                "resources": _wall_resource_receipt(
                    cumulative_wall_ns, complete=wall_measurement_complete
                ),
                "runtime_identity": _runtime_identity(),
                "schema": AGGREGATE_SCHEMA,
                "source_and_external_integrity": {
                    "asset_stable": asset_valid,
                    "holdout_sealed": holdout_valid,
                    "source_stable": source_valid,
                },
                "status": status,
                "typed_results": [result.sealed_dict() for result in adjusted],
            }
        ),
    )
    return cast(dict[str, object], seal_canonical_object(payload, hash_field="artifact_core_hash"))


def measure_two_speed_controller(
    *,
    output: Path,
    work_root: Path,
    exposure_ledger: Path,
    recordings_root: Path,
    environments_dir: Path,
    build_000_root: Path,
    build_001_root: Path,
    command: Sequence[str],
) -> dict[str, object]:
    """Run or resume the exact serial twenty-cell Stage 08 attempt."""

    check = preflight(
        output=output,
        work_root=work_root,
        exposure_ledger=exposure_ledger,
        recordings_root=recordings_root,
        environments_dir=environments_dir,
        build_000_root=build_000_root,
        build_001_root=build_001_root,
    )
    if check.get("status") != "READY_NOT_EXECUTED":
        raise EvaluationError("official Stage 08 execution preflight is not ready")
    existing_aggregate = _load_existing_aggregate(output)
    matrix = build_measurement_matrix()
    base_wall_ns = 0
    wall_measurement_complete = True
    no_new_launches = False
    prior_records_by_id: dict[str, Mapping[str, object]] = {}
    command_history: list[list[str]] = []
    if existing_aggregate is not None:
        prior_current = _required_mapping(
            existing_aggregate.get("current_source_start"), "prior current source"
        )
        prior_build_000 = _required_mapping(
            existing_aggregate.get("build_000_source_start"), "prior Build 000 source"
        )
        if (
            prior_current.get("git_commit")
            != _required_mapping(check["current_source"], "current source").get("git_commit")
            or prior_build_000.get("git_commit") != BUILD_000_PRODUCTION_COMMIT
            or existing_aggregate.get("matrix_hash") != MEASUREMENT_MATRIX_SHA256
        ):
            raise EvaluationError("Stage 08 resume source or matrix identity changed")
        resources = _required_mapping(existing_aggregate.get("resources"), "prior resources")
        prior_wall_complete = resources.get("wall_measurement_complete")
        if prior_wall_complete is True:
            base_wall_ns = _required_nonnegative_int(
                resources.get("cumulative_active_wall_ns"), "prior active wall"
            )
        else:
            base_wall_ns = _required_nonnegative_int(
                resources.get("observed_lower_bound_active_wall_ns"),
                "prior observed lower-bound wall",
            )
            wall_measurement_complete = False
            no_new_launches = True
        prior_records = _required_list(existing_aggregate.get("cell_records"), "prior records")
        if len(prior_records) > len(matrix):
            raise EvaluationError("Stage 08 prior aggregate has too many cell records")
        for ordinal, record_value in enumerate(prior_records):
            record = _required_mapping(record_value, f"prior record {ordinal}")
            cell_id = _required_string(record.get("cell_id"), f"prior record {ordinal} cell id")
            if cell_id != matrix[ordinal].cell_id or cell_id in prior_records_by_id:
                raise EvaluationError("Stage 08 prior aggregate cell order is invalid")
            prior_records_by_id[cell_id] = record
        prior_commands = _required_list(existing_aggregate.get("commands"), "prior commands")
        for ordinal, raw_command in enumerate(prior_commands):
            if not isinstance(raw_command, list) or any(
                not isinstance(part, str) or not part for part in raw_command
            ):
                raise EvaluationError(f"Stage 08 prior command {ordinal} is invalid")
            command_history.append(cast(list[str], raw_command))
        if existing_aggregate.get("execution_complete") is True:
            no_new_launches = True
    command_history.append(list(command))
    current_start = cast(Mapping[str, object], check["current_source"])
    build_000_start = cast(Mapping[str, object], check["build_000_source"])
    asset_start = cast(Mapping[str, object], check["development_asset"])
    holdout_start = cast(Mapping[str, object], check["holdout"])
    work_root.mkdir(parents=True, exist_ok=True)
    invocation_started: int | None = None
    results: list[CellResult] = []
    records: list[dict[str, object]] = []
    projection_failures: list[dict[str, object]] = []
    exposure_cells = _existing_exposure_cells(exposure_ledger)
    specs_by_id = {
        cell.cell_id: build_worker_spec(
            cell,
            work_root=work_root,
            recordings_root=recordings_root,
            environments_dir=environments_dir,
            current_source=current_start,
            build_000_source=build_000_start,
        )
        for cell in matrix
    }
    surviving_receipt_errors = _surviving_receipt_preflight_errors(
        matrix=matrix,
        specs_by_id=specs_by_id,
        exposure_cells=exposure_cells,
        work_root=work_root,
    )
    if surviving_receipt_errors:
        projection_failures.append({"cell_id": None, "errors": surviving_receipt_errors})
        no_new_launches = True
    exposed_without_receipt = any(
        not _parent_receipt_path(work_root, cell).is_file()
        for cell in matrix
        if cell.cell_id in exposure_cells
    )
    unaccounted_receipt = any(
        _parent_receipt_path(work_root, cell).is_file() and cell.cell_id not in prior_records_by_id
        for cell in matrix
        if cell.cell_id in exposure_cells
    )
    if exposed_without_receipt or unaccounted_receipt:
        wall_measurement_complete = False
        no_new_launches = True
    stopped_for_overall_wall = False

    for cell in matrix:
        spec = specs_by_id[cell.cell_id]
        spec_path = _spec_path(work_root, cell)
        cell_root = _cell_root(work_root, cell)
        raw_path = cell_root / "worker-result.json"
        streams_root = work_root.resolve() / "parent-streams" / f"{cell.ordinal:02d}-{cell.cell_id}"
        receipt_path = _parent_receipt_path(work_root, cell)
        prior_record = prior_records_by_id.get(cell.cell_id)
        preprojection_errors: list[str] = []
        launched = False
        if receipt_path.is_file():
            receipt = _load_object(receipt_path)
            if prior_record is None:
                # The supervisor receipt survived, but no atomic aggregate ever
                # accounted for the interval in which it was produced.  Its raw
                # result remains independently verifiable, while cumulative wall
                # time is now only a lower bound.
                wall_measurement_complete = False
                no_new_launches = True
        elif cell.cell_id in exposure_cells:
            receipt = _interrupted_parent_receipt(
                cell=cell,
                spec=spec,
                raw_path=raw_path,
                streams_root=streams_root,
            )
            # The aggregate itself seals this recovered classification.  Resume
            # validation does not mutate the surviving cell/recording evidence.
            wall_measurement_complete = False
            no_new_launches = True
        elif prior_record is not None:
            embedded_receipt = prior_record.get("parent_receipt")
            if _is_mapping(embedded_receipt):
                receipt = dict(embedded_receipt)
                preprojection_errors.append("persisted parent receipt artifact is missing")
            else:
                preprojection_errors.append("prior cell record has no recoverable parent receipt")
                continue
            no_new_launches = True
        elif no_new_launches:
            continue
        else:
            elapsed = base_wall_ns + (
                0
                if invocation_started is None
                else max(0, time.perf_counter_ns() - invocation_started)
            )
            if elapsed >= int(OVERALL_WALL_SECONDS * 1_000_000_000):
                stopped_for_overall_wall = True
                no_new_launches = True
                continue
            _write_or_validate_spec(spec_path, spec)
            invocation_started = invocation_started or time.perf_counter_ns()
            spec_hash = _required_string(spec.get("spec_hash"), "worker spec hash")
            _append_exposure(exposure_ledger, cell=cell, spec_hash=spec_hash)
            exposure_cells[cell.cell_id] = spec_hash
            worker_command = (
                str(Path(sys.executable).resolve()),
                str(build_001_root.resolve() / "scripts/_stage08_two_speed_worker.py"),
                "--spec",
                str(spec_path.resolve()),
                "--output",
                str(raw_path.resolve()),
            )
            supervisor = _supervise_worker(
                worker_command,
                environment=_worker_environment(),
                streams_root=streams_root,
                timeout_seconds=_remaining_worker_timeout(
                    base_wall_ns + max(0, time.perf_counter_ns() - invocation_started)
                ),
            )
            receipt = _make_parent_receipt(
                cell=cell,
                spec=spec,
                supervisor=supervisor,
                raw_path=raw_path,
                streams_root=streams_root,
            )
            _atomic_create_json(receipt_path, receipt)
            launched = True
        if not launched:
            if not spec_path.is_file():
                preprojection_errors.append("sealed worker spec artifact is missing")
            elif _load_object(spec_path) != spec:
                preprojection_errors.append("sealed worker spec artifact changed")
        result, errors, raw = _result_from_receipt(
            cell=cell,
            spec=spec,
            receipt=receipt,
            cell_root=cell_root,
            streams_root=streams_root,
            holdout_exposure_count=0,
            exposure_spec_hash=exposure_cells.get(cell.cell_id),
        )
        errors = [*preprojection_errors, *errors]
        parent_receipt_file_sha = _sha256_file(receipt_path) if receipt_path.is_file() else None
        if prior_record is not None:
            if prior_record.get("parent_receipt") != receipt:
                errors.append("prior aggregate parent receipt projection changed")
            if prior_record.get("parent_receipt_sha256") != parent_receipt_file_sha:
                errors.append("prior aggregate parent receipt file hash changed")
            if prior_record.get("raw_worker_result_hash") != (
                None if raw is None else raw.get("worker_result_hash")
            ):
                errors.append("prior aggregate raw worker result identity changed")
            if prior_record.get("typed_result_hash") != result.result_hash:
                errors.append("prior aggregate typed result identity changed")
        results.append(result)
        record = {
            "cell_id": cell.cell_id,
            "parent_receipt": receipt,
            "parent_receipt_path": (
                receipt_path.resolve().as_posix() if receipt_path.is_file() else None
            ),
            "parent_receipt_sha256": parent_receipt_file_sha,
            "raw_worker_result_hash": None if raw is None else raw.get("worker_result_hash"),
            "typed_result_hash": result.result_hash,
        }
        records.append(record)
        if errors:
            projection_failures.append({"cell_id": cell.cell_id, "errors": errors})
        if errors or result.failure_domain is FailureDomain.INFRASTRUCTURE:
            no_new_launches = True
        interim = _aggregate_payload(
            command_history=command_history,
            current_start=current_start,
            build_000_start=build_000_start,
            asset_start=asset_start,
            holdout_start=holdout_start,
            preflight_receipt=check,
            output=output,
            work_root=work_root,
            exposure_ledger=exposure_ledger,
            recordings_root=recordings_root,
            environments_dir=environments_dir,
            build_000_root=build_000_root,
            build_001_root=build_001_root,
            results=results,
            records=records,
            projection_failures=projection_failures,
            base_wall_ns=base_wall_ns,
            invocation_started_ns=invocation_started,
            wall_measurement_complete=wall_measurement_complete,
            final=False,
        )
        interim_integrity = interim.get("source_and_external_integrity")
        if not _is_mapping(interim_integrity) or any(
            interim_integrity.get(field) is not True
            for field in ("asset_stable", "holdout_sealed", "source_stable")
        ):
            no_new_launches = True
        # Revalidation of already-aggregated cells must not replace the durable
        # aggregate with a shorter prefix if this resume invocation is itself
        # interrupted.  The first newly handled cell contains the full verified
        # prefix and is safe to publish atomically.
        if launched:
            _atomic_write_json(output, interim)

    if stopped_for_overall_wall:
        projection_failures.append(
            {
                "cell_id": None,
                "errors": ["Stage 08 overall 2700-second active wall ceiling reached"],
            }
        )
    final = _aggregate_payload(
        command_history=command_history,
        current_start=current_start,
        build_000_start=build_000_start,
        asset_start=asset_start,
        holdout_start=holdout_start,
        preflight_receipt=check,
        output=output,
        work_root=work_root,
        exposure_ledger=exposure_ledger,
        recordings_root=recordings_root,
        environments_dir=environments_dir,
        build_000_root=build_000_root,
        build_001_root=build_001_root,
        results=results,
        records=records,
        projection_failures=projection_failures,
        base_wall_ns=base_wall_ns,
        invocation_started_ns=invocation_started,
        wall_measurement_complete=wall_measurement_complete,
        final=True,
    )
    _atomic_write_json(output, final)
    return final


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--work-root", type=Path, default=DEFAULT_WORK_ROOT)
    parser.add_argument("--exposure-ledger", type=Path, default=DEFAULT_EXPOSURE_LEDGER)
    parser.add_argument("--recordings-root", type=Path, default=DEFAULT_RECORDINGS_ROOT)
    parser.add_argument("--environments-dir", type=Path, default=DEFAULT_ENVIRONMENTS_DIR)
    parser.add_argument("--build-000-root", type=Path, default=DEFAULT_BUILD_000_ROOT)
    parser.add_argument("--build-001-root", type=Path, default=DEFAULT_BUILD_001_ROOT)
    parser.add_argument("--execute", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(list(argv) if argv is not None else None)
    if not args.execute:
        check = preflight(
            output=args.output,
            work_root=args.work_root,
            exposure_ledger=args.exposure_ledger,
            recordings_root=args.recordings_root,
            environments_dir=args.environments_dir,
            build_000_root=args.build_000_root,
            build_001_root=args.build_001_root,
        )
        sys.stdout.buffer.write(_json_file_bytes(check))
        return 0 if check["status"] == "READY_NOT_EXECUTED" else 1
    command = (
        str(Path(sys.executable).resolve()),
        str(Path(__file__).resolve()),
        "--execute",
        "--output",
        str(args.output.resolve()),
        "--work-root",
        str(args.work_root.resolve()),
        "--exposure-ledger",
        str(args.exposure_ledger.resolve()),
        "--recordings-root",
        str(args.recordings_root.resolve()),
        "--environments-dir",
        str(args.environments_dir.resolve()),
        "--build-000-root",
        str(args.build_000_root.resolve()),
        "--build-001-root",
        str(args.build_001_root.resolve()),
    )
    result = measure_two_speed_controller(
        output=args.output,
        work_root=args.work_root,
        exposure_ledger=args.exposure_ledger,
        recordings_root=args.recordings_root,
        environments_dir=args.environments_dir,
        build_000_root=args.build_000_root,
        build_001_root=args.build_001_root,
        command=command,
    )
    sys.stdout.buffer.write(
        _json_file_bytes(
            {
                "artifact_core_hash": result["artifact_core_hash"],
                "execution_complete": result["execution_complete"],
                "output": args.output.resolve().as_posix(),
                "status": result["status"],
            }
        )
    )
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
