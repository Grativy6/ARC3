"""Preflight or serially execute the frozen Build 001 Stage 10 suites."""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import os
import signal
import subprocess
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from arc3.errors import EvaluationError
from arc3.evaluation.artifacts import (
    atomic_write_json,
    canonical_json_bytes,
    seal_object,
    sha256_file,
    verify_object_hash,
)
from arc3.evaluation.integrity_authority import (
    COMPOSITE_INTEGRITY_SCHEMA,
    authority_callable_origins,
    composite_binding,
    create_composite_integrity_authority,
    validate_composite_integrity_authority,
)
from arc3.evaluation.stage10_regression import (
    PREDECLARATION_PATH,
    PREDECLARATION_SHA256,
    PUBLIC_PARTITION_MANIFEST_SHA256,
    SOURCE_FLOOR_COMMIT,
    SOURCE_FLOOR_TREE,
    STAGE10_CHILD_AUTHORITY_SCHEMA,
    STAGE10_LAUNCH_AUTHORIZATION_SCHEMA,
    STAGE10_PARENT_RECEIPT_SCHEMA,
    STAGE10_PREFLIGHT_SCHEMA,
    STAGE10_PROCESS_CLEANUP_SCHEMA,
    STAGE10_PROCESS_LAUNCH_SCHEMA,
    STAGE10_RESULT_SCHEMA,
    STAGE10_SOCKET_DENIAL_SCHEMA,
    STAGE10_WORKER_ABORT_SCHEMA,
    UV_LOCK_SHA256,
    Stage10Status,
    SuiteDisposition,
    SuiteSpec,
    SuiteValidation,
    build_suite_plan,
    classify_stage,
    suite_plan_hash,
    validate_ablations,
    validate_action,
    validate_checkpoint_replay,
    validate_integrity,
    validate_palette,
    validate_predeclaration_bytes,
    validate_resource_profile,
    validate_rule_change,
    validate_stage13,
    validate_stage13_verification,
)
from arc3.types import JSONValue

_LEDGER_SCHEMA = "arc3.build-001.stage-10-invocation.v0.1"
_INTEGRITY_INPUTS_SCHEMA = "arc3.build-001.stage-10-integrity-authority-inputs.v0.1"
_PREAUTH_FAILURE_SCHEMA = "arc3.build-001.stage-10-preauthorization-failure.v0.1"
_WINDOWS_CREATE_NEW_PROCESS_GROUP = int(getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
_SENSITIVE_ENV_MARKERS = (
    "API_KEY",
    "AUTH",
    "COOKIE",
    "CREDENTIAL",
    "PASSWORD",
    "SECRET",
    "TOKEN",
)
_RUNTIME_PROBE = """
import importlib.util
import json
import os
import platform
import sys
from pathlib import Path

source = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(source))
from arc3.evaluation.integrity_authority import runtime_surface_identity
arc3 = importlib.util.find_spec("arc3")
stage10 = importlib.util.find_spec("arc3.evaluation.stage10_regression")
runtime_surface = runtime_surface_identity(source.parent)
print(json.dumps({
    "arc3_origin": str(Path(arc3.origin).resolve()) if arc3 and arc3.origin else None,
    "implementation": platform.python_implementation(),
    "machine": platform.machine(),
    "platform": platform.platform(),
    "python_executable_lexical": os.path.abspath(sys.executable),
    "python_executable_resolved": str(Path(sys.executable).resolve()),
    "python_version": list(sys.version_info[:3]),
    "stage10_origin": str(Path(stage10.origin).resolve()) if stage10 and stage10.origin else None,
    "sys_base_prefix_lexical": os.path.abspath(sys.base_prefix),
    "sys_prefix_lexical": os.path.abspath(sys.prefix),
    "sys_prefix_resolved": str(Path(sys.prefix).resolve()),
    "runtime_surface": runtime_surface,
}, sort_keys=True, separators=(",", ":")))
"""
_REQUIRED_SUPERVISOR_MODULE_PATHS = {
    "arc3": Path("src/arc3/__init__.py"),
    "arc3.errors": Path("src/arc3/errors.py"),
    "arc3.evaluation": Path("src/arc3/evaluation/__init__.py"),
    "arc3.evaluation.artifacts": Path("src/arc3/evaluation/artifacts.py"),
    "arc3.evaluation.integrity_authority": Path("src/arc3/evaluation/integrity_authority.py"),
    "arc3.evaluation.stage10_regression": Path("src/arc3/evaluation/stage10_regression.py"),
    "arc3.integrity": Path("src/arc3/integrity/__init__.py"),
    "arc3.integrity.models": Path("src/arc3/integrity/models.py"),
    "arc3.integrity.scanner": Path("src/arc3/integrity/scanner.py"),
    "arc3.types": Path("src/arc3/types.py"),
}


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _git(root: Path, *arguments: str, check: bool = True) -> str:
    environment = {
        key: value for key, value in os.environ.items() if not key.upper().startswith("GIT_")
    }
    environment["GIT_NO_REPLACE_OBJECTS"] = "1"
    completed = subprocess.run(
        ("git", *arguments),
        cwd=root,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=15,
    )
    if check and completed.returncode != 0:
        raise RuntimeError(f"git {' '.join(arguments)} failed: {completed.stderr[:300]}")
    return completed.stdout.strip() if completed.returncode == 0 else ""


def _git_success(root: Path, *arguments: str) -> bool:
    environment = {
        key: value for key, value in os.environ.items() if not key.upper().startswith("GIT_")
    }
    environment["GIT_NO_REPLACE_OBJECTS"] = "1"
    return (
        subprocess.run(
            ("git", *arguments),
            cwd=root,
            env=environment,
            check=False,
            capture_output=True,
            timeout=15,
        ).returncode
        == 0
    )


def _supervisor_import_identity(source_root: Path) -> dict[str, object]:
    """Bind every loaded first-party module used by the Stage 10 supervisor."""

    root = source_root.resolve()
    preload_exact = True
    for module_name, relative in (
        ("scripts.check_competition_integrity", "scripts/check_competition_integrity.py"),
        ("scripts.measure_development_recovery", "scripts/measure_development_recovery.py"),
    ):
        try:
            module = importlib.import_module(module_name)
        except (ImportError, OSError, RuntimeError, ValueError):
            preload_exact = False
            continue
        origin = getattr(module, "__file__", None)
        if not isinstance(origin, str) or Path(origin).resolve() != (root / relative).resolve():
            preload_exact = False
    expected_script = (root / "scripts/measure_stage10_regression.py").resolve()
    expected_source = (root / "src").resolve()
    modules: dict[str, dict[str, str]] = {}
    origins_exact = Path(__file__).resolve() == expected_script and preload_exact
    for name, module in sorted(sys.modules.items()):
        if name != "arc3" and not name.startswith("arc3."):
            continue
        origin_value = getattr(module, "__file__", None)
        if not isinstance(origin_value, str):
            origins_exact = False
            continue
        origin = Path(origin_value).resolve()
        try:
            relative = origin.relative_to(root).as_posix()
            origin.relative_to(expected_source)
        except ValueError:
            origins_exact = False
            continue
        if not origin.is_file():
            origins_exact = False
            continue
        modules[name] = {"path": relative, "sha256": sha256_file(origin)}
    required_exact = all(
        name in modules and modules[name]["path"] == relative.as_posix()
        for name, relative in _REQUIRED_SUPERVISOR_MODULE_PATHS.items()
    )
    callable_origins: dict[str, str] = {}
    callable_origins_exact = True
    expected_callables = {
        "atomic_write_json": (atomic_write_json, "src/arc3/evaluation/artifacts.py"),
        "authority_callable_origins": (
            authority_callable_origins,
            "src/arc3/evaluation/integrity_authority.py",
        ),
        "build_suite_plan": (
            build_suite_plan,
            "src/arc3/evaluation/stage10_regression.py",
        ),
        "canonical_json_bytes": (
            canonical_json_bytes,
            "src/arc3/evaluation/artifacts.py",
        ),
        "composite_binding": (
            composite_binding,
            "src/arc3/evaluation/integrity_authority.py",
        ),
        "create_composite_integrity_authority": (
            create_composite_integrity_authority,
            "src/arc3/evaluation/integrity_authority.py",
        ),
        "seal_object": (seal_object, "src/arc3/evaluation/artifacts.py"),
        "validate_composite_integrity_authority": (
            validate_composite_integrity_authority,
            "src/arc3/evaluation/integrity_authority.py",
        ),
        "validate_integrity": (
            validate_integrity,
            "src/arc3/evaluation/stage10_regression.py",
        ),
        "validate_predeclaration_bytes": (
            validate_predeclaration_bytes,
            "src/arc3/evaluation/stage10_regression.py",
        ),
        "verify_object_hash": (
            verify_object_hash,
            "src/arc3/evaluation/artifacts.py",
        ),
    }
    for name, (function, relative) in expected_callables.items():
        code = getattr(function, "__code__", None)
        expected_path = (root / relative).resolve()
        if code is None or Path(code.co_filename).resolve() != expected_path:
            callable_origins_exact = False
            continue
        callable_origins[name] = relative
    try:
        nested_callable_origins = authority_callable_origins(root)
    except EvaluationError:
        callable_origins_exact = False
        nested_callable_origins = {}
    report: dict[str, object] = {
        "loaded_arc3_modules": modules,
        "authority_callable_origins": nested_callable_origins,
        "callable_origins": callable_origins,
        "callable_origins_exact": callable_origins_exact,
        "required_modules_exact": required_exact,
        "schema": "arc3.build-001.stage-10-supervisor-import-identity.v0.1",
        "script": {
            "path": (
                Path(__file__).resolve().relative_to(root).as_posix()
                if Path(__file__).resolve() == expected_script
                else Path(__file__).resolve().as_posix()
            ),
            "sha256": sha256_file(Path(__file__).resolve()),
        },
        "source_root": root.as_posix(),
        "verified": origins_exact and required_exact and callable_origins_exact,
    }
    return seal_object(report, hash_field="supervisor_import_identity_sha256")


def _require_supervisor_import_origin(source_root: Path) -> dict[str, object]:
    identity = _supervisor_import_identity(source_root)
    if identity.get("verified") is not True:
        raise ValueError("Stage 10 supervisor import closure is not the execution source root")
    return identity


def _source_identity(source_root: Path, frozen_commit: str) -> dict[str, JSONValue]:
    root = source_root.resolve()
    top_level = Path(_git(root, "rev-parse", "--show-toplevel")).resolve()
    commit = _git(source_root, "rev-parse", "HEAD")
    tree = _git(source_root, "rev-parse", "HEAD^{tree}")
    status = _git(source_root, "status", "--porcelain=v1", "--untracked-files=all")
    floor_tree = _git(source_root, "show", "-s", "--format=%T", SOURCE_FLOOR_COMMIT)
    floor_is_ancestor = _git_success(
        source_root,
        "merge-base",
        "--is-ancestor",
        SOURCE_FLOOR_COMMIT,
        commit,
    )
    return {
        "clean_worktree": status == "",
        "commit": commit,
        "exact_frozen_commit": commit == frozen_commit,
        "floor_commit": SOURCE_FLOOR_COMMIT,
        "floor_is_ancestor": floor_is_ancestor,
        "floor_tree": floor_tree,
        "floor_tree_exact": floor_tree == SOURCE_FLOOR_TREE,
        "tree": tree,
        "git_top_level_exact": top_level == root,
        "verified": (
            status == ""
            and commit == frozen_commit
            and floor_is_ancestor
            and floor_tree == SOURCE_FLOOR_TREE
            and top_level == root
        ),
    }


def _runtime_identity(source_root: Path, python: Path) -> dict[str, object]:
    launcher = Path(os.path.abspath(python))
    resolved_executable = launcher.resolve()
    expected_arc3 = (source_root / "src/arc3/__init__.py").resolve()
    expected_stage10 = (source_root / "src/arc3/evaluation/stage10_regression.py").resolve()
    observed: dict[str, object] = {}
    error: str | None = None
    try:
        completed = subprocess.run(
            (str(launcher), "-I", "-c", _RUNTIME_PROBE, str((source_root / "src").resolve())),
            cwd=source_root,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
        if completed.returncode != 0:
            raise RuntimeError(
                f"runtime probe exited {completed.returncode}: {completed.stderr[:200]}"
            )
        value: object = json.loads(completed.stdout)
        if not isinstance(value, dict):
            raise ValueError("runtime probe did not return an object")
        observed = cast(dict[str, object], value)
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as caught:
        error = f"{type(caught).__name__}:{caught}"
    lock_path = source_root / "uv.lock"
    launcher_hash = sha256_file(launcher) if launcher.is_file() else None
    resolved_executable_hash = (
        sha256_file(resolved_executable) if resolved_executable.is_file() else None
    )
    lock_hash = sha256_file(lock_path) if lock_path.is_file() else None
    version_value = observed.get("python_version")
    runtime_surface = observed.get("runtime_surface")
    python_3_12 = (
        isinstance(version_value, list)
        and len(version_value) == 3
        and version_value[:2] == [3, 12]
        and all(isinstance(item, int) and not isinstance(item, bool) for item in version_value)
    )
    predicates = {
        "arc3_import_origin_exact": observed.get("arc3_origin") == str(expected_arc3),
        "launcher_exists": launcher.is_file(),
        "launcher_reported_lexically": observed.get("python_executable_lexical") == str(launcher),
        "resolved_executable_exact": observed.get("python_executable_resolved")
        == str(resolved_executable),
        "venv_prefix_lexical": observed.get("sys_prefix_lexical") == str(launcher.parent.parent),
        "python_3_12": python_3_12,
        "stage10_import_origin_exact": observed.get("stage10_origin") == str(expected_stage10),
        "runtime_surface_verified": isinstance(runtime_surface, Mapping)
        and runtime_surface.get("verified") is True
        and verify_object_hash(dict(runtime_surface), hash_field="runtime_surface_sha256"),
        "uv_lock_exact": lock_hash == UV_LOCK_SHA256,
    }
    report: dict[str, object] = {
        "error": error,
        "launcher_is_symlink": launcher.is_symlink(),
        "launcher_link_target": os.readlink(launcher) if launcher.is_symlink() else None,
        "launcher_path": str(launcher),
        "launcher_sha256": launcher_hash,
        "observed": observed,
        "predicates": predicates,
        "resolved_executable_path": str(resolved_executable),
        "resolved_executable_sha256": resolved_executable_hash,
        "schema": "arc3.build-001.stage-10-runtime-identity.v0.1",
        "uv_lock_sha256": lock_hash,
        "verified": error is None and all(predicates.values()),
    }
    return seal_object(report, hash_field="runtime_identity_sha256")


def _load_integrity_inputs(path: Path) -> dict[str, object]:
    raw = path.resolve().read_bytes()
    value: object = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("Stage 10 integrity authority inputs are not an object")
    document = cast(dict[str, object], value)
    expected_fields = {
        "authority_inputs_hash",
        "build_000_source_commit",
        "build_000_source_root",
        "build_000_source_tree",
        "development_predeclaration_core_hash",
        "development_predeclaration_file_sha256",
        "development_predeclaration_path",
        "development_identifier_list_sha256",
        "holdout_nonconsumption_path",
        "holdout_nonconsumption_sha256",
        "schema",
        "stage09_verification_file_sha256",
        "stage09_verification_hash",
        "stage09_verification_path",
    }
    sha_fields = {
        "development_identifier_list_sha256",
        "development_predeclaration_core_hash",
        "development_predeclaration_file_sha256",
        "holdout_nonconsumption_sha256",
        "stage09_verification_file_sha256",
        "stage09_verification_hash",
    }
    git_fields = {"build_000_source_commit", "build_000_source_tree"}
    if (
        set(document) != expected_fields
        or canonical_json_bytes(document) != raw
        or document.get("schema") != _INTEGRITY_INPUTS_SCHEMA
        or not verify_object_hash(document, hash_field="authority_inputs_hash")
        or not all(
            isinstance(document.get(name), str)
            and cast(str, document[name]).startswith("sha256:")
            and len(cast(str, document[name])) == 71
            and all(character in "0123456789abcdef" for character in cast(str, document[name])[7:])
            for name in sha_fields
        )
        or not all(
            isinstance(document.get(name), str)
            and len(cast(str, document[name])) == 40
            and all(character in "0123456789abcdef" for character in cast(str, document[name]))
            for name in git_fields
        )
        or not all(
            isinstance(document.get(name), str)
            for name in (
                "build_000_source_root",
                "development_predeclaration_path",
                "holdout_nonconsumption_path",
                "stage09_verification_path",
            )
        )
        or not all(
            Path(cast(str, document[name])).is_absolute()
            for name in (
                "build_000_source_root",
                "development_predeclaration_path",
                "holdout_nonconsumption_path",
                "stage09_verification_path",
            )
        )
    ):
        raise ValueError("Stage 10 integrity authority inputs failed exact validation")
    return document


def _integrity_inputs_summary(path: Path) -> dict[str, JSONValue]:
    document = _load_integrity_inputs(path)
    return {
        "authority_inputs_hash": cast(str, document["authority_inputs_hash"]),
        "file_sha256": sha256_file(path.resolve()),
        "path": path.resolve().as_posix(),
        "schema": _INTEGRITY_INPUTS_SCHEMA,
    }


def _outside_source(source_root: Path, candidate: Path) -> bool:
    try:
        candidate.resolve().relative_to(source_root.resolve())
    except ValueError:
        return True
    return False


def _integrity_input_locations_clear(source_root: Path, document: Mapping[str, object]) -> bool:
    return all(
        _outside_source(source_root, Path(cast(str, document[name])))
        for name in (
            "build_000_source_root",
            "development_predeclaration_path",
            "holdout_nonconsumption_path",
            "stage09_verification_path",
        )
    )


def build_preflight(
    *,
    source_root: Path,
    python: Path,
    attempt_root: Path,
    output: Path,
    frozen_commit: str,
    integrity_inputs_path: Path,
) -> tuple[dict[str, object], tuple[SuiteSpec, ...]]:
    """Validate identities and produce a non-playing plan without writing files."""

    _require_supervisor_import_origin(source_root)
    declaration_path = source_root / PREDECLARATION_PATH
    declaration = validate_predeclaration_bytes(declaration_path.read_bytes())
    identity = _source_identity(source_root, frozen_commit)
    runtime_identity = _runtime_identity(source_root, python)
    try:
        integrity_document = _load_integrity_inputs(integrity_inputs_path)
        integrity_inputs = _integrity_inputs_summary(integrity_inputs_path)
        integrity_inputs_valid = _outside_source(
            source_root, integrity_inputs_path
        ) and _integrity_input_locations_clear(source_root, integrity_document)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        integrity_inputs = {
            "error_kind": type(error).__name__,
            "verified": False,
        }
        integrity_inputs_valid = False
    plan = build_suite_plan(
        python=python,
        source_root=source_root,
        attempt_root=attempt_root,
        frozen_commit=frozen_commit,
        prior_integrity_path=None,
        integrity_inputs_hash=cast(
            str,
            integrity_inputs.get("authority_inputs_hash", "sha256:" + "0" * 64),
        ),
    )
    frozen_inputs = declaration.get("frozen_inputs")
    required_paths = tuple(
        path
        for path in (
            python,
            integrity_inputs_path,
            source_root / "uv.lock",
            source_root / "docs/ledger/build-001-run-state.json",
            source_root / "scripts/measure_ablations.py",
            source_root / "scripts/measure_palette_equivariance.py",
            source_root / "scripts/measure_action_equivariance.py",
            source_root / "scripts/measure_rule_change_reopening.py",
            source_root / "scripts/measure_development_recovery.py",
            source_root / "scripts/_stage10_checkpoint_worker.py",
            source_root / "scripts/_stage10_offline_child.py",
            source_root / "scripts/profile_competition.py",
            source_root / "scripts/check_competition_integrity.py",
            source_root / "src/arc3/evaluation/holdout_authority.py",
            source_root / "src/arc3/evaluation/development_recovery.py",
            source_root / "src/arc3/evaluation/integrity_authority.py",
            source_root / "src/arc3/integrity/scanner.py",
        )
    )
    predicates = {
        "attempt_root_external": _outside_source(source_root, attempt_root),
        "frozen_declaration": declaration.get("status") == "FROZEN_PREMEASUREMENT",
        "manifest_hash_exact": isinstance(frozen_inputs, Mapping)
        and frozen_inputs.get("public_partition_manifest_sha256")
        == PUBLIC_PARTITION_MANIFEST_SHA256,
        "output_external": _outside_source(source_root, output),
        "output_has_no_suite_collision": output.resolve()
        not in {
            path.resolve()
            for path in (
                attempt_root / "invocations.jsonl",
                *(item.artifact_path for item in plan if item.artifact_path is not None),
                *(
                    attempt_root / "logs" / f"{item.suite_id}.{suffix}"
                    for item in plan
                    for suffix in ("stdout", "stderr")
                ),
                *(attempt_root / "receipts" / f"{item.suite_id}.json" for item in plan),
                *(item.network_guard_path for item in plan if item.network_guard_path is not None),
                *(item.authority_path for item in plan if item.authority_path is not None),
                *(item.launch_path for item in plan if item.launch_path is not None),
                *(item.authorization_path for item in plan if item.authorization_path is not None),
                *(item.abort_path for item in plan if item.abort_path is not None),
                *(item.cleanup_path for item in plan if item.cleanup_path is not None),
                *(
                    item.integrity_composite_path
                    for item in plan
                    if item.integrity_composite_path is not None
                ),
            )
        },
        "required_paths_exist": all(path.exists() for path in required_paths),
        "current_integrity_inputs_exact": integrity_inputs_valid,
        "runtime_identity": runtime_identity.get("verified") is True,
        "source_identity": identity.get("verified") is True,
    }
    supervisor_identity = _require_supervisor_import_origin(source_root)
    report: dict[str, object] = {
        "claim": "NO_GENERALIZATION_CLAIM",
        "evidence_label": "synthetic",
        "mode": "NON_PLAYING_PREFLIGHT",
        "plan": [item.to_dict() for item in plan],
        "plan_hash": suite_plan_hash(plan),
        "predeclaration_sha256": PREDECLARATION_SHA256,
        "current_integrity_authority_inputs": integrity_inputs,
        "predicates": predicates,
        "runtime_identity": runtime_identity,
        "schema": STAGE10_PREFLIGHT_SCHEMA,
        "source_identity": identity,
        "supervisor_import_identity": supervisor_identity,
        "status": "PASS" if all(predicates.values()) else "FAILED_INFRASTRUCTURE",
    }
    return seal_object(report, hash_field="preflight_hash"), plan


def _safe_environment(source_root: Path) -> dict[str, str]:
    environment = {
        key: value
        for key, value in os.environ.items()
        if not any(marker in key.upper() for marker in _SENSITIVE_ENV_MARKERS)
        and not key.upper().startswith("GIT_")
    }
    environment.update(
        {
            "ARC3_OFFLINE": "1",
            "GIT_NO_REPLACE_OBJECTS": "1",
            "HF_HUB_OFFLINE": "1",
            "NO_PROXY": "*",
            "PYTHONNOUSERSITE": "1",
            "PYTHONPATH": str((source_root / "src").resolve()),
            "TRANSFORMERS_OFFLINE": "1",
        }
    )
    return environment


def _append_record(path: Path, record: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = canonical_json_bytes(dict(record))
    descriptor = os.open(
        path,
        os.O_APPEND | os.O_CREAT | os.O_WRONLY | getattr(os, "O_BINARY", 0),
        0o600,
    )
    try:
        os.write(descriptor, raw)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _load_ledger(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        return []
    records: list[dict[str, object]] = []
    previous: str | None = None
    raw = path.read_bytes()
    if raw and not raw.endswith(b"\n"):
        raise ValueError("invocation ledger is not canonical JSONL")
    for ordinal, line in enumerate(raw.splitlines(keepends=True), start=1):
        value: object = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError(f"invocation ledger row {ordinal} is not an object")
        record = cast(dict[str, object], value)
        if (
            canonical_json_bytes(record) != line
            or record.get("schema") != _LEDGER_SCHEMA
            or record.get("sequence") != ordinal
            or record.get("previous_record_hash") != previous
            or not verify_object_hash(record, hash_field="record_hash")
        ):
            raise ValueError(f"invocation ledger row {ordinal} failed integrity")
        previous_value = record.get("record_hash")
        if not isinstance(previous_value, str):
            raise ValueError(f"invocation ledger row {ordinal} has no record hash")
        previous = previous_value
        records.append(record)
    return records


def _process_creation_token(pid: int) -> str | None:
    """Return a restart-comparable operating-system process identity."""

    if isinstance(pid, bool) or pid <= 0:
        return None
    if os.name == "nt":
        try:
            probe = subprocess.run(
                (
                    "powershell.exe",
                    "-NoProfile",
                    "-NonInteractive",
                    "-Command",
                    (
                        "$p=Get-CimInstance Win32_Process -Filter 'ProcessId = "
                        f"{pid}';if($null -ne $p){{$p.CreationDate.ToUniversalTime().Ticks}}"
                    ),
                ),
                check=False,
                capture_output=True,
                text=True,
                timeout=5.0,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        value = probe.stdout.strip()
        return f"windows-cim:{value}" if probe.returncode == 0 and value.isdigit() else None
    stat_path = Path(f"/proc/{pid}/stat")
    command_path = Path(f"/proc/{pid}/cmdline")
    if stat_path.is_file() and command_path.is_file():
        try:
            stat = stat_path.read_text(encoding="utf-8")
            suffix = stat[stat.rfind(")") + 2 :].split()
            start_ticks = suffix[19]
            command_hash = sha256_file(command_path)
        except (OSError, IndexError):
            return None
        return f"linux-proc:{start_ticks}:{command_hash}"
    return None


def _suite_spec_sha256(suite: SuiteSpec) -> str:
    return "sha256:" + hashlib.sha256(canonical_json_bytes(suite.to_dict())).hexdigest()


def _load_canonical_sealed(
    path: Path,
    *,
    schema: str,
    hash_field: str,
    label: str,
) -> dict[str, object]:
    raw = path.resolve().read_bytes()
    value: object = json.loads(raw)
    if (
        not isinstance(value, dict)
        or canonical_json_bytes(value) != raw
        or value.get("schema") != schema
        or not verify_object_hash(value, hash_field=hash_field)
    ):
        raise ValueError(f"Stage 10 {label} bytes/hash/schema changed")
    return cast(dict[str, object], value)


def _validate_launch_receipt(
    suite: SuiteSpec,
    *,
    source_root: Path,
) -> dict[str, object]:
    if (
        suite.launch_path is None
        or suite.authorization_path is None
        or suite.abort_path is None
        or suite.launch_token is None
        or suite.network_guard_path is None
    ):
        raise ValueError("Stage 10 suite has no exact launch-handshake paths")
    launch = _load_canonical_sealed(
        suite.launch_path,
        schema=STAGE10_PROCESS_LAUNCH_SCHEMA,
        hash_field="launch_receipt_hash",
        label="process launch receipt",
    )
    expected = {
        "abort_path": suite.abort_path.resolve().as_posix(),
        "authorization_path": suite.authorization_path.resolve().as_posix(),
        "authority_path": (
            suite.authority_path.resolve().as_posix() if suite.authority_path is not None else None
        ),
        "command": list(suite.command),
        "command_sha256": "sha256:"
        + hashlib.sha256(canonical_json_bytes(list(suite.command))).hexdigest(),
        "cwd": source_root.resolve().as_posix(),
        "frozen_commit": next(
            (
                suite.command[index + 1]
                for index, value in enumerate(suite.command[:-1])
                if value == "--frozen-commit"
            ),
            None,
        ),
        "launch_token": suite.launch_token,
        "network_receipt_path": suite.network_guard_path.resolve().as_posix(),
        "socket_denial_installed": True,
        "suite_id": suite.suite_id,
        "target_imported": False,
    }
    if any(launch.get(name) != value for name, value in expected.items()):
        raise ValueError("Stage 10 process launch binding changed")
    expected_fields = {
        *expected,
        "launch_receipt_hash",
        "parent_pid",
        "pid",
        "process_creation_token",
        "schema",
        "target_kind",
        "target_sha256",
    }
    if set(launch) != expected_fields:
        raise ValueError("Stage 10 process launch fields changed")
    for name in ("parent_pid", "pid"):
        value = launch.get(name)
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError(f"Stage 10 process launch {name} is invalid")
    if not isinstance(launch.get("process_creation_token"), str):
        raise ValueError("Stage 10 process launch creation token is invalid")
    return launch


def _authorization_payload(
    suite: SuiteSpec,
    *,
    launch: Mapping[str, object],
    plan_hash: str,
    source_root: Path,
    source_identity: Mapping[str, JSONValue],
    runtime_identity: Mapping[str, object],
    supervisor_import_identity: Mapping[str, object],
    containment: Mapping[str, object],
) -> dict[str, object]:
    if (
        suite.launch_path is None
        or suite.abort_path is None
        or suite.network_guard_path is None
        or suite.launch_token is None
        or suite.integrity_inputs_hash is None
    ):
        raise ValueError("Stage 10 suite has no authorization paths")
    observed = runtime_identity.get("observed")
    runtime_surface = observed.get("runtime_surface") if isinstance(observed, Mapping) else None
    if not isinstance(runtime_surface, Mapping):
        raise ValueError("Stage 10 runtime surface is absent from launch authorization")
    payload = {
        "abort_path": suite.abort_path.resolve().as_posix(),
        "command_sha256": launch.get("command_sha256"),
        "containment": dict(containment),
        "frozen_commit": source_identity.get("commit"),
        "integrity_inputs_hash": suite.integrity_inputs_hash,
        "launch_receipt_hash": launch.get("launch_receipt_hash"),
        "launch_receipt_sha256": sha256_file(suite.launch_path),
        "launch_token": suite.launch_token,
        "network_receipt_path": suite.network_guard_path.resolve().as_posix(),
        "pid": launch.get("pid"),
        "plan_hash": plan_hash,
        "process_creation_token": launch.get("process_creation_token"),
        "runtime_identity_sha256": runtime_identity.get("runtime_identity_sha256"),
        "runtime_surface": dict(runtime_surface),
        "schema": STAGE10_LAUNCH_AUTHORIZATION_SCHEMA,
        "source_commit": source_identity.get("commit"),
        "source_root": source_root.resolve().as_posix(),
        "source_tree": source_identity.get("tree"),
        "suite_id": suite.suite_id,
        "suite_spec_sha256": _suite_spec_sha256(suite),
        "supervisor_import_identity_sha256": supervisor_import_identity.get(
            "supervisor_import_identity_sha256"
        ),
        "target_import_authorized": True,
    }
    return seal_object(payload, hash_field="authorization_hash")


def _validate_authorization_receipt(
    suite: SuiteSpec,
    *,
    expected: Mapping[str, object],
) -> dict[str, object]:
    if suite.authorization_path is None:
        raise ValueError("Stage 10 suite has no launch authorization path")
    authorization = _load_canonical_sealed(
        suite.authorization_path,
        schema=STAGE10_LAUNCH_AUTHORIZATION_SCHEMA,
        hash_field="authorization_hash",
        label="launch authorization",
    )
    if authorization != dict(expected):
        raise ValueError("Stage 10 launch authorization changed")
    return authorization


def _new_ledger_record(
    records: Sequence[Mapping[str, object]],
    *,
    suite: SuiteSpec,
    state: str,
    plan_hash: str,
    receipt_hash: str | None = None,
    launch: Mapping[str, object] | None = None,
    authorization: Mapping[str, object] | None = None,
) -> dict[str, object]:
    previous = records[-1].get("record_hash") if records else None
    record: dict[str, object] = {
        "command": list(suite.command),
        "plan_hash": plan_hash,
        "previous_record_hash": previous,
        "schema": _LEDGER_SCHEMA,
        "sequence": len(records) + 1,
        "state": state,
        "suite_id": suite.suite_id,
        "timestamp": _utc_now(),
    }
    if state == "STARTED":
        if launch is None or authorization is None:
            raise ValueError("Stage 10 STARTED record requires exact launch authorization")
        record.update(
            {
                "authorization_hash": authorization.get("authorization_hash"),
                "authorization_sha256": "sha256:"
                + hashlib.sha256(canonical_json_bytes(dict(authorization))).hexdigest(),
                "containment": authorization.get("containment"),
                "launch_receipt_hash": launch.get("launch_receipt_hash"),
                "launch_receipt_sha256": "sha256:"
                + hashlib.sha256(canonical_json_bytes(dict(launch))).hexdigest(),
                "launch_token": launch.get("launch_token"),
                "pid": launch.get("pid"),
                "process_creation_token": launch.get("process_creation_token"),
            }
        )
    if state == "COMPLETED" and receipt_hash is not None:
        record["parent_receipt_hash"] = receipt_hash
    return seal_object(record, hash_field="record_hash")


def _ledger_states(
    records: Sequence[Mapping[str, object]],
    *,
    plan_hash: str,
    plan: Sequence[SuiteSpec],
) -> dict[str, tuple[str, str | None, dict[str, object]]]:
    states: dict[str, tuple[str, str | None, dict[str, object]]] = {}
    active_suite: str | None = None
    specifications = {suite.suite_id: suite for suite in plan}
    for record in records:
        suite_id = record.get("suite_id")
        state = record.get("state")
        expected_fields = {
            "command",
            "plan_hash",
            "previous_record_hash",
            "record_hash",
            "schema",
            "sequence",
            "state",
            "suite_id",
            "timestamp",
        }
        if state == "STARTED":
            expected_fields.update(
                {
                    "authorization_hash",
                    "authorization_sha256",
                    "containment",
                    "launch_receipt_hash",
                    "launch_receipt_sha256",
                    "launch_token",
                    "pid",
                    "process_creation_token",
                }
            )
        elif state == "COMPLETED":
            expected_fields.add("parent_receipt_hash")
        if (
            not isinstance(suite_id, str)
            or state not in {"STARTED", "COMPLETED"}
            or record.get("plan_hash") != plan_hash
            or set(record) != expected_fields
            or suite_id not in specifications
            or record.get("command") != list(specifications[suite_id].command)
            or not isinstance(record.get("timestamp"), str)
        ):
            raise ValueError("invocation ledger disagrees with the frozen plan")
        prior = states.get(suite_id)
        if state == "STARTED":
            if (
                prior is not None
                or active_suite is not None
                or not all(
                    isinstance(record.get(name), str)
                    for name in (
                        "authorization_hash",
                        "authorization_sha256",
                        "launch_receipt_hash",
                        "launch_receipt_sha256",
                        "launch_token",
                        "process_creation_token",
                    )
                )
                or isinstance(record.get("pid"), bool)
                or not isinstance(record.get("pid"), int)
                or cast(int, record.get("pid")) <= 0
                or not isinstance(record.get("containment"), Mapping)
            ):
                raise ValueError(f"suite {suite_id} was started more than once")
            states[suite_id] = ("STARTED", None, dict(record))
            active_suite = suite_id
        else:
            receipt_hash = record.get("parent_receipt_hash")
            if (
                prior is None
                or prior[0] != "STARTED"
                or prior[1] is not None
                or active_suite != suite_id
                or not isinstance(receipt_hash, str)
            ):
                raise ValueError(f"suite {suite_id} completion has no unique start")
            states[suite_id] = ("COMPLETED", receipt_hash, prior[2])
            active_suite = None
    return states


def _atomic_create_json(path: Path, value: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(canonical_json_bytes(dict(value)))
        stream.flush()
        os.fsync(stream.fileno())


def _assign_windows_kill_job(process: subprocess.Popen[bytes]) -> int:
    """Contain the child tree in a kill-on-close Windows Job Object."""

    import ctypes
    from ctypes import wintypes

    class _BasicLimit(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_int64),
            ("PerJobUserTimeLimit", ctypes.c_int64),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class _IoCounters(ctypes.Structure):
        _fields_ = [
            ("ReadOperationCount", ctypes.c_uint64),
            ("WriteOperationCount", ctypes.c_uint64),
            ("OtherOperationCount", ctypes.c_uint64),
            ("ReadTransferCount", ctypes.c_uint64),
            ("WriteTransferCount", ctypes.c_uint64),
            ("OtherTransferCount", ctypes.c_uint64),
        ]

    class _ExtendedLimit(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", _BasicLimit),
            ("IoInfo", _IoCounters),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    win_dll = getattr(ctypes, "WinDLL", None)
    get_last_error = getattr(ctypes, "get_last_error", None)
    if not callable(win_dll) or not callable(get_last_error):
        raise OSError("Windows kernel32 is unavailable through ctypes")
    kernel32 = win_dll("kernel32", use_last_error=True)
    create_job = kernel32.CreateJobObjectW
    create_job.argtypes = (ctypes.c_void_p, wintypes.LPCWSTR)
    create_job.restype = wintypes.HANDLE
    set_job = kernel32.SetInformationJobObject
    set_job.argtypes = (
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
    )
    set_job.restype = wintypes.BOOL
    assign = kernel32.AssignProcessToJobObject
    assign.argtypes = (wintypes.HANDLE, wintypes.HANDLE)
    assign.restype = wintypes.BOOL
    close = kernel32.CloseHandle
    close.argtypes = (wintypes.HANDLE,)
    close.restype = wintypes.BOOL
    handle = create_job(None, None)
    if not handle:
        raise OSError(int(get_last_error()), "CreateJobObjectW failed")
    try:
        limits = _ExtendedLimit()
        limits.BasicLimitInformation.LimitFlags = 0x00002000
        if not set_job(handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
            raise OSError(int(get_last_error()), "SetInformationJobObject failed")
        process_handle_value = getattr(process, "_handle", None)
        if not isinstance(process_handle_value, int) or process_handle_value <= 0:
            raise OSError("Popen has no Windows process handle")
        if not assign(handle, wintypes.HANDLE(process_handle_value)):
            raise OSError(int(get_last_error()), "AssignProcessToJobObject failed")
        return int(handle)
    except BaseException:
        close(handle)
        raise


def _close_windows_handle(handle: int) -> None:
    import ctypes
    from ctypes import wintypes

    win_dll = getattr(ctypes, "WinDLL", None)
    get_last_error = getattr(ctypes, "get_last_error", None)
    if not callable(win_dll) or not callable(get_last_error):
        raise OSError("Windows kernel32 is unavailable through ctypes")
    close = win_dll("kernel32", use_last_error=True).CloseHandle
    close.argtypes = (wintypes.HANDLE,)
    close.restype = wintypes.BOOL
    if not close(wintypes.HANDLE(handle)):
        raise OSError(int(get_last_error()), "CloseHandle failed")


def _posix_group_members(process_group_id: int) -> tuple[int, ...]:
    proc = Path("/proc")
    if os.name == "nt" or not proc.is_dir():
        return ()
    members: list[int] = []
    try:
        entries = tuple(proc.iterdir())
    except OSError as error:
        raise OSError("process-group enumeration failed") from error
    for entry in entries:
        if not entry.name.isdigit():
            continue
        try:
            stat = (entry / "stat").read_text(encoding="utf-8")
            suffix = stat[stat.rfind(")") + 2 :].split()
            group_id = int(suffix[2])
        except (OSError, IndexError, ValueError):
            continue
        if group_id == process_group_id:
            members.append(int(entry.name))
    return tuple(sorted(members))


def _wait_process_token_change(pid: int, expected: str, *, seconds: float = 5.0) -> str | None:
    deadline = time.monotonic() + seconds
    observed = _process_creation_token(pid)
    while observed == expected and time.monotonic() < deadline:
        time.sleep(0.02)
        observed = _process_creation_token(pid)
    return observed


def _wait_posix_group_empty(process_group_id: int, *, seconds: float = 5.0) -> tuple[int, ...]:
    members = _posix_group_members(process_group_id)
    deadline = time.monotonic() + seconds
    while members and time.monotonic() < deadline:
        time.sleep(0.02)
        members = _posix_group_members(process_group_id)
    return members


def _cleanup_unidentified_spawn(
    *,
    suite: SuiteSpec,
    process: subprocess.Popen[bytes],
    containment: Mapping[str, object],
    reason: str,
    windows_job_handle: int | None,
) -> dict[str, object]:
    """Terminate a pre-authorization spawn whose OS creation token is unavailable."""

    pid = process.pid
    group_before = _posix_group_members(pid)
    attempted = False
    method: str | None = None
    error: str | None = None
    if os.name == "nt":
        attempted = True
        method = (
            "windows-job-unidentified-preauthorization"
            if windows_job_handle is not None
            else "windows-popen-handle-unidentified-preauthorization"
        )
        try:
            if windows_job_handle is not None:
                _close_windows_handle(windows_job_handle)
            else:
                process.kill()
        except OSError as caught:
            error = f"{type(caught).__name__}: {caught}"
    else:
        attempted = process.poll() is None or bool(group_before)
        method = "posix-killpg-unidentified-preauthorization" if attempted else None
        if attempted:
            try:
                kill_process_group = cast(
                    Callable[[int, int], None],
                    getattr(os, "killpg"),  # noqa: B009 - absent from Windows typeshed
                )
                kill_process_group(pid, int(getattr(signal, "SIGKILL", 9)))
            except ProcessLookupError:
                pass
            except OSError as caught:
                error = f"{type(caught).__name__}: {caught}"
    try:
        process.wait(timeout=30)
    except (OSError, subprocess.TimeoutExpired) as caught:
        error = f"{type(caught).__name__}: {caught}"
    group_after = _wait_posix_group_empty(pid) if os.name != "nt" else ()
    live_after = _process_creation_token(pid)
    if error is not None or process.poll() is None or group_after:
        raise ValueError("Stage 10 unidentified spawn cleanup could not prove zero survivors")
    cleanup = seal_object(
        {
            "authorization_hash": None,
            "authorization_sha256": None,
            "containment": dict(containment),
            "error": None,
            "group_members_after": list(group_after),
            "group_members_before": list(group_before),
            "launch_receipt_hash": None,
            "launch_receipt_sha256": (
                sha256_file(suite.launch_path)
                if suite.launch_path is not None and suite.launch_path.is_file()
                else None
            ),
            "launch_token": suite.launch_token,
            "live_process_token_after": live_after,
            "live_process_token_before": None,
            "method": method,
            "passed": True,
            "pid": pid,
            "pid_reused_original_not_running": live_after is not None,
            "process_creation_token": None,
            "reason": reason,
            "returncode": process.returncode,
            "schema": STAGE10_PROCESS_CLEANUP_SCHEMA,
            "suite_id": suite.suite_id,
            "termination_attempted": attempted,
        },
        hash_field="cleanup_receipt_hash",
    )
    if suite.cleanup_path is None:
        raise ValueError("Stage 10 suite has no cleanup receipt path")
    _atomic_create_json(suite.cleanup_path, cleanup)
    return cleanup


def _cleanup_process_tree(
    *,
    suite: SuiteSpec,
    launch: Mapping[str, object],
    authorization: Mapping[str, object] | None,
    containment: Mapping[str, object],
    reason: str,
    windows_job_handle: int | None,
    allow_group_without_live_root: bool,
) -> dict[str, object]:
    pid = launch.get("pid")
    stored_token = launch.get("process_creation_token")
    if (
        isinstance(pid, bool)
        or not isinstance(pid, int)
        or pid <= 0
        or not isinstance(stored_token, str)
    ):
        raise ValueError("Stage 10 cleanup has no exact process identity")
    live_before = _process_creation_token(pid)
    group_before = _posix_group_members(pid)
    attempted = False
    method: str | None = None
    returncode: int | None = None
    error: str | None = None
    if os.name == "nt" and windows_job_handle is not None:
        attempted = True
        method = "windows-job-kill-on-close"
        try:
            _close_windows_handle(windows_job_handle)
        except OSError as caught:
            error = f"{type(caught).__name__}: {caught}"
    elif live_before == stored_token:
        attempted = True
        if os.name == "nt":
            method = "windows-taskkill-exact-tree"
            try:
                result = subprocess.run(
                    ("taskkill", "/PID", str(pid), "/T", "/F"),
                    check=False,
                    capture_output=True,
                    timeout=15.0,
                )
                returncode = result.returncode
            except (OSError, subprocess.TimeoutExpired) as caught:
                error = f"{type(caught).__name__}: {caught}"
        else:
            method = "posix-killpg-exact-leader"
            try:
                kill_process_group = cast(
                    Callable[[int, int], None],
                    getattr(os, "killpg"),  # noqa: B009 - absent from Windows typeshed
                )
                kill_process_group(pid, int(getattr(signal, "SIGKILL", 9)))
            except ProcessLookupError:
                pass
            except OSError as caught:
                error = f"{type(caught).__name__}: {caught}"
    elif os.name != "nt" and live_before is None and group_before and allow_group_without_live_root:
        attempted = True
        method = "posix-killpg-same-supervision-window"
        try:
            kill_process_group = cast(
                Callable[[int, int], None],
                getattr(os, "killpg"),  # noqa: B009 - absent from Windows typeshed
            )
            kill_process_group(pid, int(getattr(signal, "SIGKILL", 9)))
        except ProcessLookupError:
            pass
        except OSError as caught:
            error = f"{type(caught).__name__}: {caught}"
    live_after = _wait_process_token_change(pid, stored_token)
    group_after = _wait_posix_group_empty(pid) if os.name != "nt" else ()
    pid_reused = live_before is not None and live_before != stored_token
    passed = bool(
        error is None
        and live_after != stored_token
        and (os.name == "nt" or not group_after or pid_reused)
    )
    if not passed:
        raise ValueError("Stage 10 process-tree cleanup could not prove zero survivors")
    cleanup = seal_object(
        {
            "authorization_hash": (
                authorization.get("authorization_hash") if authorization is not None else None
            ),
            "authorization_sha256": (
                "sha256:" + hashlib.sha256(canonical_json_bytes(dict(authorization))).hexdigest()
                if authorization is not None
                else None
            ),
            "containment": dict(containment),
            "error": error,
            "group_members_after": list(group_after),
            "group_members_before": list(group_before),
            "launch_receipt_hash": launch.get("launch_receipt_hash"),
            "launch_receipt_sha256": (
                sha256_file(suite.launch_path)
                if suite.launch_path is not None and suite.launch_path.is_file()
                else None
            ),
            "launch_token": launch.get("launch_token"),
            "live_process_token_after": live_after,
            "live_process_token_before": live_before,
            "method": method,
            "passed": True,
            "pid": pid,
            "pid_reused_original_not_running": pid_reused,
            "process_creation_token": stored_token,
            "reason": reason,
            "returncode": returncode,
            "schema": STAGE10_PROCESS_CLEANUP_SCHEMA,
            "suite_id": suite.suite_id,
            "termination_attempted": attempted,
        },
        hash_field="cleanup_receipt_hash",
    )
    if suite.cleanup_path is None:
        raise ValueError("Stage 10 suite has no cleanup receipt path")
    _atomic_create_json(suite.cleanup_path, cleanup)
    return cleanup


def _validate_cleanup_receipt(
    suite: SuiteSpec,
    *,
    launch: Mapping[str, object],
    authorization: Mapping[str, object] | None,
) -> dict[str, object]:
    if suite.cleanup_path is None:
        raise ValueError("Stage 10 suite has no cleanup receipt path")
    cleanup = _load_canonical_sealed(
        suite.cleanup_path,
        schema=STAGE10_PROCESS_CLEANUP_SCHEMA,
        hash_field="cleanup_receipt_hash",
        label="process cleanup receipt",
    )
    expected_fields = {
        "authorization_hash",
        "authorization_sha256",
        "cleanup_receipt_hash",
        "containment",
        "error",
        "group_members_after",
        "group_members_before",
        "launch_receipt_hash",
        "launch_receipt_sha256",
        "launch_token",
        "live_process_token_after",
        "live_process_token_before",
        "method",
        "passed",
        "pid",
        "pid_reused_original_not_running",
        "process_creation_token",
        "reason",
        "returncode",
        "schema",
        "suite_id",
        "termination_attempted",
    }
    pid = launch.get("pid")
    token = launch.get("process_creation_token")
    expected_authorization_hash = (
        authorization.get("authorization_hash") if authorization is not None else None
    )
    expected_authorization_sha256 = (
        "sha256:" + hashlib.sha256(canonical_json_bytes(dict(authorization))).hexdigest()
        if authorization is not None
        else None
    )
    live_now = _process_creation_token(pid) if isinstance(pid, int) else None
    if (
        set(cleanup) != expected_fields
        or cleanup.get("passed") is not True
        or cleanup.get("suite_id") != suite.suite_id
        or cleanup.get("pid") != pid
        or cleanup.get("process_creation_token") != token
        or cleanup.get("launch_token") != launch.get("launch_token")
        or cleanup.get("launch_receipt_hash") != launch.get("launch_receipt_hash")
        or cleanup.get("launch_receipt_sha256")
        != (sha256_file(suite.launch_path) if suite.launch_path is not None else None)
        or cleanup.get("authorization_hash") != expected_authorization_hash
        or cleanup.get("authorization_sha256") != expected_authorization_sha256
        or (
            authorization is not None
            and cleanup.get("containment") != authorization.get("containment")
        )
        or cleanup.get("error") is not None
        or not isinstance(cleanup.get("termination_attempted"), bool)
        or not isinstance(cleanup.get("pid_reused_original_not_running"), bool)
        or not isinstance(cleanup.get("group_members_before"), list)
        or not isinstance(cleanup.get("group_members_after"), list)
        or cleanup.get("live_process_token_after") == token
        or live_now == token
    ):
        raise ValueError("Stage 10 process cleanup receipt failed live validation")
    if os.name != "nt" and _posix_group_members(cast(int, pid)):
        raise ValueError("Stage 10 process group has live survivors after cleanup")
    return cleanup


def _validate_worker_abort(
    suite: SuiteSpec,
    *,
    launch: Mapping[str, object],
) -> dict[str, object]:
    if suite.abort_path is None:
        raise ValueError("Stage 10 suite has no worker abort path")
    abort = _load_canonical_sealed(
        suite.abort_path,
        schema=STAGE10_WORKER_ABORT_SCHEMA,
        hash_field="worker_abort_hash",
        label="worker abort receipt",
    )
    if set(abort) != {
        "authorization_path",
        "launch_receipt_hash",
        "launch_receipt_path",
        "launch_token",
        "pid",
        "process_creation_token",
        "reason",
        "schema",
        "socket_denial_installed",
        "suite_id",
        "target_imported",
        "worker_abort_hash",
    } or any(
        abort.get(name) != value
        for name, value in {
            "authorization_path": (
                suite.authorization_path.resolve().as_posix()
                if suite.authorization_path is not None
                else None
            ),
            "launch_receipt_hash": launch.get("launch_receipt_hash"),
            "launch_receipt_path": (
                suite.launch_path.resolve().as_posix() if suite.launch_path is not None else None
            ),
            "launch_token": launch.get("launch_token"),
            "pid": launch.get("pid"),
            "process_creation_token": launch.get("process_creation_token"),
            "reason": "launch-authorization-unavailable-or-invalid",
            "socket_denial_installed": True,
            "suite_id": suite.suite_id,
            "target_imported": False,
        }.items()
    ):
        raise ValueError("Stage 10 worker abort receipt changed")
    return abort


def _recover_interrupted_suite(
    suite: SuiteSpec,
    *,
    started_record: Mapping[str, object] | None,
    source_root: Path,
    plan_hash: str,
    source_identity: Mapping[str, JSONValue],
    runtime_identity: Mapping[str, object],
    supervisor_import_identity: Mapping[str, object],
) -> dict[str, object]:
    """Prove an interrupted child tree is gone without ever rerunning it."""

    launch = _validate_launch_receipt(suite, source_root=source_root)
    pid = launch.get("pid")
    if started_record is not None:
        for name in (
            "launch_receipt_hash",
            "launch_token",
            "pid",
            "process_creation_token",
        ):
            if started_record.get(name) != launch.get(name):
                raise ValueError("Stage 10 interrupted STARTED launch identity changed")
        if suite.launch_path is None or started_record.get("launch_receipt_sha256") != sha256_file(
            suite.launch_path
        ):
            raise ValueError("Stage 10 interrupted launch receipt bytes changed")
        containment_raw = started_record.get("containment")
    else:
        containment_raw = {
            "job_assigned_before_authorization": True if os.name == "nt" else None,
            "kill_on_parent_exit": os.name == "nt",
            "kind": ("windows-job-kill-on-close" if os.name == "nt" else "posix-process-group"),
            "process_group_id": None if os.name == "nt" else pid,
        }
    if not isinstance(containment_raw, Mapping):
        raise ValueError("Stage 10 interrupted containment authority changed")
    containment = dict(containment_raw)
    authorization: dict[str, object] | None = None
    if suite.authorization_path is not None and suite.authorization_path.is_file():
        expected_authorization = _authorization_payload(
            suite,
            launch=launch,
            plan_hash=plan_hash,
            source_root=source_root,
            source_identity=source_identity,
            runtime_identity=runtime_identity,
            supervisor_import_identity=supervisor_import_identity,
            containment=containment,
        )
        authorization = _validate_authorization_receipt(
            suite,
            expected=expected_authorization,
        )
        if started_record is None:
            raise ValueError("Stage 10 authorization exists without a STARTED ledger record")
        if started_record.get("authorization_hash") != authorization.get(
            "authorization_hash"
        ) or started_record.get("authorization_sha256") != sha256_file(suite.authorization_path):
            raise ValueError("Stage 10 interrupted authorization bytes changed")
    elif started_record is not None:
        expected_authorization = _authorization_payload(
            suite,
            launch=launch,
            plan_hash=plan_hash,
            source_root=source_root,
            source_identity=source_identity,
            runtime_identity=runtime_identity,
            supervisor_import_identity=supervisor_import_identity,
            containment=containment,
        )
        expected_hash = expected_authorization.get("authorization_hash")
        expected_file_hash = (
            "sha256:" + hashlib.sha256(canonical_json_bytes(expected_authorization)).hexdigest()
        )
        if (
            started_record.get("authorization_hash") != expected_hash
            or started_record.get("authorization_sha256") != expected_file_hash
        ):
            raise ValueError("Stage 10 missing interrupted authorization was rebound")
    if suite.abort_path is not None and suite.abort_path.is_file():
        if authorization is not None:
            raise ValueError("Stage 10 worker abort exists after target authorization")
        _validate_worker_abort(suite, launch=launch)
    if suite.cleanup_path is None:
        raise ValueError("Stage 10 interrupted suite has no cleanup receipt path")
    if not suite.cleanup_path.exists():
        _cleanup_process_tree(
            suite=suite,
            launch=launch,
            authorization=authorization,
            containment=containment,
            reason="interrupted-resume",
            windows_job_handle=None,
            allow_group_without_live_root=False,
        )
    return _validate_cleanup_receipt(
        suite,
        launch=launch,
        authorization=authorization,
    )


def _run_child(
    suite: SuiteSpec,
    *,
    source_root: Path,
    stdout_path: Path,
    stderr_path: Path,
    ledger_path: Path,
    records: list[dict[str, object]],
    plan_hash: str,
    source_identity: Mapping[str, JSONValue],
    runtime_identity: Mapping[str, object],
    supervisor_import_identity: Mapping[str, object],
    expected_authority: Mapping[str, object] | None = None,
) -> tuple[int | None, bool, str | None, int, bool]:
    guard_path = suite.network_guard_path
    if (
        stdout_path.exists()
        or stderr_path.exists()
        or (guard_path is not None and guard_path.exists())
        or any(
            path is not None and path.exists()
            for path in (
                suite.launch_path,
                suite.authorization_path,
                suite.abort_path,
                suite.cleanup_path,
            )
        )
    ):
        stdout_path.parent.mkdir(parents=True, exist_ok=True)
        stdout_path.touch(exist_ok=True)
        stderr_path.touch(exist_ok=True)
        return None, False, "raw/process receipt path already exists", 0, False
    stdout_path.parent.mkdir(parents=True, exist_ok=True)
    if guard_path is not None:
        guard_path.parent.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter_ns()
    creationflags = _WINDOWS_CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
    environment = _safe_environment(source_root)
    environment["ARC3_STAGE10_LEXICAL_LAUNCHER"] = suite.command[0]
    if expected_authority is not None:
        parent_hash = expected_authority.get("integrity_parent_receipt_sha256")
        authority_hash = expected_authority.get("authority_sha256")
        if not isinstance(parent_hash, str) or not isinstance(authority_hash, str):
            return None, False, "expected child authority is malformed", 0, False
        environment.update(
            {
                "ARC3_STAGE10_EXPECTED_AUTHORITY_FILE_SHA256": (
                    "sha256:"
                    + hashlib.sha256(canonical_json_bytes(dict(expected_authority))).hexdigest()
                ),
                "ARC3_STAGE10_EXPECTED_AUTHORITY_SHA256": authority_hash,
                "ARC3_STAGE10_EXPECTED_PARENT_RECEIPT_SHA256": parent_hash,
            }
        )
    process: subprocess.Popen[bytes] | None = None
    windows_job_handle: int | None = None
    launch: dict[str, object] | None = None
    authorization: dict[str, object] | None = None
    containment: dict[str, object] | None = None
    started_record_written = False
    try:
        with stdout_path.open("xb") as stdout, stderr_path.open("xb") as stderr:
            process = subprocess.Popen(
                suite.command,
                cwd=source_root,
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=stdout,
                stderr=stderr,
                creationflags=creationflags,
                start_new_session=os.name != "nt",
            )
            launch = {
                "launch_receipt_hash": None,
                "launch_token": suite.launch_token,
                "pid": process.pid,
                "process_creation_token": None,
            }
            if os.name == "nt":
                containment = {
                    "job_assigned_before_authorization": False,
                    "kill_on_parent_exit": False,
                    "kind": "windows-popen-handle-preauthorization",
                    "process_group_id": None,
                }
                windows_job_handle = _assign_windows_kill_job(process)
                containment = {
                    "job_assigned_before_authorization": True,
                    "kill_on_parent_exit": True,
                    "kind": "windows-job-kill-on-close",
                    "process_group_id": None,
                }
            else:
                containment = {
                    "job_assigned_before_authorization": None,
                    "kill_on_parent_exit": False,
                    "kind": "posix-process-group",
                    "process_group_id": process.pid,
                }
            token_deadline = time.monotonic() + 1.0
            spawn_token = _process_creation_token(process.pid)
            while (
                spawn_token is None and process.poll() is None and time.monotonic() < token_deadline
            ):
                time.sleep(0.02)
                spawn_token = _process_creation_token(process.pid)
            if spawn_token is None:
                raise ValueError("Stage 10 spawned process creation identity is unavailable")
            # Parent-observed provisional identity ensures even a worker that
            # never emits its launch receipt can be terminated and evidenced.
            launch["process_creation_token"] = spawn_token
            if suite.launch_path is None:
                raise ValueError("Stage 10 suite has no launch receipt path")
            deadline = time.monotonic() + 10.0
            while not suite.launch_path.is_file() and time.monotonic() < deadline:
                if process.poll() is not None:
                    break
                time.sleep(0.02)
            launch = _validate_launch_receipt(suite, source_root=source_root)
            live_token = _process_creation_token(process.pid)
            if (
                launch.get("pid") != process.pid
                or live_token is None
                or launch.get("process_creation_token") != live_token
            ):
                raise ValueError("Stage 10 live launch identity changed before authorization")
            authorization = _authorization_payload(
                suite,
                launch=launch,
                plan_hash=plan_hash,
                source_root=source_root,
                source_identity=source_identity,
                runtime_identity=runtime_identity,
                supervisor_import_identity=supervisor_import_identity,
                containment=containment,
            )
            started_record = _new_ledger_record(
                records,
                suite=suite,
                state="STARTED",
                plan_hash=plan_hash,
                launch=launch,
                authorization=authorization,
            )
            _append_record(ledger_path, started_record)
            records.append(started_record)
            started_record_written = True
            if suite.authorization_path is None:
                raise ValueError("Stage 10 suite has no authorization receipt path")
            _atomic_create_json(suite.authorization_path, authorization)
            try:
                returncode = process.wait(timeout=suite.timeout_seconds)
            except subprocess.TimeoutExpired:
                assert launch is not None
                assert containment is not None
                _cleanup_process_tree(
                    suite=suite,
                    launch=launch,
                    authorization=authorization,
                    containment=containment,
                    reason="timeout",
                    windows_job_handle=windows_job_handle,
                    allow_group_without_live_root=True,
                )
                windows_job_handle = None
                process.wait(timeout=30)
                return (
                    None,
                    True,
                    None,
                    max(0, time.perf_counter_ns() - started),
                    started_record_written,
                )
            assert launch is not None
            assert containment is not None
            _cleanup_process_tree(
                suite=suite,
                launch=launch,
                authorization=authorization,
                containment=containment,
                reason="normal-exit",
                windows_job_handle=windows_job_handle,
                allow_group_without_live_root=True,
            )
            windows_job_handle = None
    except (OSError, ValueError) as error:
        launch_error = f"{type(error).__name__}: {error}"
        if process is not None and launch is not None and containment is not None:
            try:
                reason = f"child-failed-before-authorized-start:{suite.suite_id}:{launch_error}"
                if isinstance(launch.get("process_creation_token"), str):
                    _cleanup_process_tree(
                        suite=suite,
                        launch=launch,
                        authorization=authorization,
                        containment=containment,
                        reason=reason,
                        windows_job_handle=windows_job_handle,
                        allow_group_without_live_root=True,
                    )
                else:
                    _cleanup_unidentified_spawn(
                        suite=suite,
                        process=process,
                        containment=containment,
                        reason=reason,
                        windows_job_handle=windows_job_handle,
                    )
                windows_job_handle = None
            except (OSError, ValueError):
                if windows_job_handle is not None:
                    try:
                        _close_windows_handle(windows_job_handle)
                    except OSError:
                        pass
                    windows_job_handle = None
                raise
        stdout_path.touch(exist_ok=True)
        stderr_path.touch(exist_ok=True)
        return (
            None,
            False,
            launch_error,
            max(0, time.perf_counter_ns() - started),
            started_record_written,
        )
    finally:
        if windows_job_handle is not None:
            _close_windows_handle(windows_job_handle)
    return (
        returncode,
        False,
        None,
        max(0, time.perf_counter_ns() - started),
        started_record_written,
    )


def _with_infrastructure_errors(
    validation: SuiteValidation,
    errors: Sequence[str],
) -> SuiteValidation:
    if not errors:
        return validation
    return SuiteValidation(
        suite_id=validation.suite_id,
        disposition=SuiteDisposition.FAILED_INFRASTRUCTURE,
        predicates=dict(validation.predicates),
        measurements=dict(validation.measurements),
        errors=(*validation.errors, *errors),
    )


def _artifact_status(path: Path | None) -> str:
    if path is None or not path.is_file():
        return ""
    try:
        value: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    return str(value.get("status", "")) if isinstance(value, dict) else ""


def _network_guard_validation(
    suite: SuiteSpec,
    *,
    frozen_commit: str,
    returncode: int | None,
) -> tuple[tuple[str, ...], int]:
    path = suite.network_guard_path
    if path is None or not path.is_file():
        return ("socket-denial-receipt-missing",), -1
    try:
        raw = path.read_bytes()
        value: object = json.loads(raw)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        return (f"socket-denial-receipt-unreadable:{type(error).__name__}",), -1
    if not isinstance(value, dict):
        return ("socket-denial-receipt-not-object",), -1
    receipt = cast(dict[str, object], value)
    expected_fields = {
        "attempts",
        "authority",
        "failure_kind",
        "frozen_commit",
        "installed_operations",
        "launch_authorization",
        "network_attempt_count",
        "process_id",
        "receipt_sha256",
        "schema",
        "suite_id",
        "target_argv_sha256",
        "target_exit_code",
        "target_kind",
        "target_sha256",
    }
    attempts_raw = receipt.get("attempts")
    attempts = attempts_raw if isinstance(attempts_raw, Mapping) else {}
    counts_typed = set(attempts) == {
        "connect",
        "connect_ex",
        "create_connection",
        "getaddrinfo",
        "send",
        "sendall",
        "sendto",
    } and all(
        isinstance(item, int) and not isinstance(item, bool) and item >= 0
        for item in attempts.values()
    )
    measured_attempts = sum(cast(int, item) for item in attempts.values()) if counts_typed else -1
    expected_target_kind: str | None = None
    expected_target_sha256: str | None = None
    expected_target_argv_sha256: str | None = None
    command = list(suite.command)
    selectors = [selector for selector in ("--module", "--script") if selector in command]
    if len(selectors) == 1:
        selector = selectors[0]
        selector_index = command.index(selector)
        if selector_index + 1 < len(command):
            target_value = command[selector_index + 1]
            if selector == "--script":
                target_value = str(Path(target_value).resolve())
            target_arguments = command[selector_index + 2 :]
            if target_arguments[:1] == ["--"]:
                target_arguments = target_arguments[1:]
            expected_target_kind = "module" if selector == "--module" else "script"
            expected_target_sha256 = (
                "sha256:" + hashlib.sha256(target_value.encode("utf-8")).hexdigest()
            )
            expected_target_argv_sha256 = (
                "sha256:"
                + hashlib.sha256(
                    canonical_json_bytes([target_value, *target_arguments])
                ).hexdigest()
            )
    errors: list[str] = []
    launch_pid: object = None
    if suite.launch_path is not None and suite.launch_path.is_file():
        try:
            launch_value: object = json.loads(suite.launch_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            launch_value = None
        if isinstance(launch_value, Mapping):
            launch_pid = launch_value.get("pid")
    expected_authority: object = None
    expected_launch_authorization: object = None
    if suite.authority_path is not None and suite.authority_path.is_file():
        try:
            authority_value: object = json.loads(suite.authority_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            authority_value = None
        if isinstance(authority_value, Mapping):
            expected_authority = {
                "authority_sha256": authority_value.get("authority_sha256"),
                "file_sha256": sha256_file(suite.authority_path),
                "integrity_inputs_hash": authority_value.get("integrity_inputs_hash"),
                "integrity_composition": authority_value.get("integrity_composition"),
                "integrity_parent_receipt_sha256": authority_value.get(
                    "integrity_parent_receipt_sha256"
                ),
                "profile": authority_value.get("profile"),
            }
    if suite.authorization_path is not None and suite.authorization_path.is_file():
        try:
            authorization_value: object = json.loads(
                suite.authorization_path.read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError):
            authorization_value = None
        if isinstance(authorization_value, Mapping):
            expected_launch_authorization = {
                "authorization_hash": authorization_value.get("authorization_hash"),
                "integrity_inputs_hash": authorization_value.get("integrity_inputs_hash"),
                "launch_receipt_hash": authorization_value.get("launch_receipt_hash"),
                "plan_hash": authorization_value.get("plan_hash"),
                "runtime_identity_sha256": authorization_value.get("runtime_identity_sha256"),
                "suite_spec_sha256": authorization_value.get("suite_spec_sha256"),
                "supervisor_import_identity_sha256": authorization_value.get(
                    "supervisor_import_identity_sha256"
                ),
            }
    predicates = {
        "authority_exact": receipt.get("authority") == expected_authority,
        "canonical_bytes": canonical_json_bytes(receipt) == raw,
        "fields_exact": set(receipt) == expected_fields,
        "hash_valid": verify_object_hash(receipt, hash_field="receipt_sha256"),
        "identity_exact": receipt.get("frozen_commit") == frozen_commit
        and receipt.get("suite_id") == suite.suite_id,
        "launch_authorization_exact": receipt.get("launch_authorization")
        == expected_launch_authorization,
        "operations_exact": counts_typed
        and receipt.get("installed_operations")
        == [
            "create_connection",
            "getaddrinfo",
            "connect",
            "connect_ex",
            "send",
            "sendall",
            "sendto",
        ],
        "returncode_bound": receipt.get("target_exit_code") == returncode,
        "schema": receipt.get("schema") == STAGE10_SOCKET_DENIAL_SCHEMA,
        "supervision_fields_typed": isinstance(receipt.get("process_id"), int)
        and not isinstance(receipt.get("process_id"), bool)
        and cast(int, receipt.get("process_id")) > 0
        and receipt.get("process_id") == launch_pid
        and (receipt.get("failure_kind") is None or isinstance(receipt.get("failure_kind"), str)),
        "target_exact": receipt.get("target_kind") == expected_target_kind
        and receipt.get("target_sha256") == expected_target_sha256
        and receipt.get("target_argv_sha256") == expected_target_argv_sha256,
        "total_exact": receipt.get("network_attempt_count") == measured_attempts,
    }
    errors.extend(
        f"socket-denial-predicate-failed:{name}"
        for name, passed in predicates.items()
        if not passed
    )
    return tuple(errors), measured_attempts


def _with_network_guard(
    validation: SuiteValidation,
    *,
    structural_errors: Sequence[str],
    network_attempts: int,
) -> SuiteValidation:
    predicates = {
        **validation.predicates,
        "socket_denial_receipt_valid": not structural_errors,
        "socket_network_attempts_zero": network_attempts == 0,
    }
    errors = (*validation.errors, *structural_errors)
    if errors:
        disposition = SuiteDisposition.FAILED_INFRASTRUCTURE
    elif network_attempts != 0:
        disposition = SuiteDisposition.FAILED_MECHANISM
    else:
        disposition = validation.disposition
    return SuiteValidation(
        suite_id=validation.suite_id,
        disposition=disposition,
        predicates=predicates,
        measurements={**validation.measurements, "socket_network_attempts": network_attempts},
        errors=errors,
    )


def _with_integrity_continuity(
    validation: SuiteValidation,
    *,
    source_root: Path,
    integrity_inputs_path: Path,
    expected_integrity_inputs_hash: str | None,
) -> SuiteValidation:
    errors = list(validation.errors)
    summary: dict[str, JSONValue] = {}
    try:
        summary = _integrity_inputs_summary(integrity_inputs_path)
        document = _load_integrity_inputs(integrity_inputs_path)
        if not _outside_source(
            source_root, integrity_inputs_path
        ) or not _integrity_input_locations_clear(source_root, document):
            raise ValueError("integrity authority inputs must remain outside execution source")
        if (
            expected_integrity_inputs_hash is None
            or summary.get("authority_inputs_hash") != expected_integrity_inputs_hash
        ):
            raise ValueError("integrity authority inputs changed after frozen preflight")
        continuity = True
    except (OSError, ValueError, json.JSONDecodeError) as error:
        continuity = False
        errors.append(f"integrity-inputs-invalid:{type(error).__name__}:{error}")
    return SuiteValidation(
        suite_id=validation.suite_id,
        disposition=(
            validation.disposition if continuity else SuiteDisposition.FAILED_INFRASTRUCTURE
        ),
        predicates={
            **validation.predicates,
            "current_integrity_inputs_exact": continuity,
        },
        measurements={
            **validation.measurements,
            "integrity_inputs_hash": summary.get("authority_inputs_hash"),
            "integrity_inputs_file_sha256": summary.get("file_sha256"),
            "integrity_inputs_schema": summary.get("schema"),
        },
        errors=tuple(errors),
    )


def _with_composite_integrity_authority(
    validation: SuiteValidation,
    *,
    source_root: Path,
    package_path: Path,
    integrity_inputs_path: Path,
    composite_path: Path | None,
    runtime_identity: Mapping[str, object],
    create_if_missing: bool,
) -> SuiteValidation:
    """Create or reconstruct the full composite authority after scoped PASS."""

    if validation.disposition is SuiteDisposition.FAILED_MECHANISM:
        return SuiteValidation(
            suite_id=validation.suite_id,
            disposition=validation.disposition,
            predicates={
                **validation.predicates,
                "composite_integrity_authority": False,
            },
            measurements=dict(validation.measurements),
            errors=validation.errors,
        )
    errors = list(validation.errors)
    binding: dict[str, JSONValue] = {}
    passed = False
    try:
        if validation.disposition is not SuiteDisposition.PASS:
            raise ValueError("package-only suite is structurally invalid")
        if composite_path is None:
            raise ValueError("competition-integrity composite output is undeclared")
        inputs = _load_integrity_inputs(integrity_inputs_path)
        observed = runtime_identity.get("observed")
        runtime_surface = observed.get("runtime_surface") if isinstance(observed, Mapping) else None
        if not isinstance(runtime_surface, Mapping):
            raise ValueError("Stage 10 preflight has no runtime-surface authority")
        document = create_composite_integrity_authority(
            source_root=source_root,
            package_only_path=package_path,
            build_000_root=Path(cast(str, inputs["build_000_source_root"])),
            expected_build_000_commit=cast(str, inputs["build_000_source_commit"]),
            expected_build_000_tree=cast(str, inputs["build_000_source_tree"]),
            expected_development_identifier_sha256=cast(
                str, inputs["development_identifier_list_sha256"]
            ),
            development_predeclaration_path=Path(
                cast(str, inputs["development_predeclaration_path"])
            ),
            expected_development_predeclaration_file_sha256=cast(
                str, inputs["development_predeclaration_file_sha256"]
            ),
            expected_development_predeclaration_core_hash=cast(
                str, inputs["development_predeclaration_core_hash"]
            ),
            holdout_nonconsumption_path=Path(cast(str, inputs["holdout_nonconsumption_path"])),
            expected_holdout_nonconsumption_sha256=cast(
                str, inputs["holdout_nonconsumption_sha256"]
            ),
            stage09_verification_path=Path(cast(str, inputs["stage09_verification_path"])),
            expected_stage09_verification_file_sha256=cast(
                str, inputs["stage09_verification_file_sha256"]
            ),
            expected_stage09_verification_hash=cast(str, inputs["stage09_verification_hash"]),
            expected_runtime_surface=runtime_surface,
        )
        if composite_path.exists():
            if create_if_missing:
                raise ValueError("fresh composite integrity output already exists")
        elif create_if_missing:
            atomic_write_json(composite_path, document)
        else:
            raise ValueError("composite integrity output is missing during reconstruction")
        expected_binding = composite_binding(document, path=composite_path)
        validated = validate_composite_integrity_authority(
            composite_path,
            expected_file_sha256=cast(str, expected_binding["file_sha256"]),
            expected_core_hash=cast(str, expected_binding["artifact_core_hash"]),
            source_root=source_root,
        )
        if validated != document:
            raise ValueError("composite integrity live reconstruction changed")
        binding = {
            "composite_integrity_core_hash": expected_binding["artifact_core_hash"],
            "composite_integrity_file_sha256": expected_binding["file_sha256"],
            "composite_integrity_schema": expected_binding["schema"],
        }
        passed = True
    except (OSError, ValueError, EvaluationError, json.JSONDecodeError) as error:
        errors.append(f"composite-integrity-invalid:{type(error).__name__}:{error}")
    return SuiteValidation(
        suite_id=validation.suite_id,
        disposition=(validation.disposition if passed else SuiteDisposition.FAILED_INFRASTRUCTURE),
        predicates={**validation.predicates, "composite_integrity_authority": passed},
        measurements={**validation.measurements, **binding},
        errors=tuple(errors),
    )


def _validate_suite(
    suite: SuiteSpec,
    *,
    attempt_root: Path,
    source_root: Path,
    frozen_commit: str,
    returncode: int | None,
    timed_out: bool,
    launch_error: str | None,
    stdout_path: Path,
    runtime_identity: Mapping[str, object],
    integrity_inputs_path: Path,
    create_composite: bool = False,
) -> SuiteValidation:
    artifact = suite.artifact_path
    if suite.suite_id == "stage13-evaluate":
        assert artifact is not None
        validation = validate_stage13(artifact.parent, frozen_commit=frozen_commit)
    elif suite.suite_id == "stage13-verify":
        validation = validate_stage13_verification(
            stdout_path.read_bytes() if stdout_path.is_file() else b"",
            returncode,
        )
    elif suite.suite_id == "stage14-ablations":
        assert artifact is not None
        validation = validate_ablations(artifact, frozen_commit=frozen_commit)
    elif suite.suite_id == "palette-equivariance":
        assert artifact is not None
        validation = validate_palette(artifact, frozen_commit=frozen_commit)
    elif suite.suite_id == "action-equivariance":
        assert artifact is not None
        validation = validate_action(artifact, frozen_commit=frozen_commit)
    elif suite.suite_id == "rule-change":
        assert artifact is not None
        validation = validate_rule_change(
            artifact,
            frozen_commit=frozen_commit,
            returncode=returncode,
        )
    elif suite.suite_id == "checkpoint-replay":
        assert artifact is not None
        validation = validate_checkpoint_replay(artifact, frozen_commit=frozen_commit)
    elif suite.suite_id == "resource-profile":
        assert artifact is not None
        validation = validate_resource_profile(
            artifact,
            frozen_commit=frozen_commit,
            returncode=returncode,
        )
    elif suite.suite_id == "competition-integrity":
        assert artifact is not None
        validation = validate_integrity(artifact, frozen_commit=frozen_commit)
        validation = _with_integrity_continuity(
            validation,
            source_root=source_root,
            integrity_inputs_path=integrity_inputs_path,
            expected_integrity_inputs_hash=suite.integrity_inputs_hash,
        )
    else:  # pragma: no cover - the plan constructor is closed
        raise ValueError(f"unknown Stage 10 suite {suite.suite_id}")

    guard_errors, network_attempts = _network_guard_validation(
        suite,
        frozen_commit=frozen_commit,
        returncode=returncode,
    )
    validation = _with_network_guard(
        validation,
        structural_errors=guard_errors,
        network_attempts=network_attempts,
    )

    errors: list[str] = []
    if timed_out:
        errors.append("child-timeout")
    if launch_error is not None:
        errors.append(f"child-launch-error:{launch_error}")
    if returncode not in suite.allowed_returncodes:
        errors.append(f"child-returncode-not-allowed:{returncode}")
    if artifact is not None and not artifact.is_file():
        errors.append("child-artifact-missing")
    status = _artifact_status(artifact)
    if status == "FAILED_INFRASTRUCTURE":
        errors.append("child-reported-failed-infrastructure")
    if returncode == 0 and status and status not in {"PASS"}:
        errors.append(f"child-exit-status-disagreement:{status}")
    if returncode == 1 and status == "PASS":
        errors.append("child-exit-status-disagreement:PASS")
    del attempt_root
    validation = _with_infrastructure_errors(validation, errors)
    if suite.suite_id == "competition-integrity":
        assert artifact is not None
        validation = _with_composite_integrity_authority(
            validation,
            source_root=source_root,
            package_path=artifact,
            integrity_inputs_path=integrity_inputs_path,
            composite_path=suite.integrity_composite_path,
            runtime_identity=runtime_identity,
            create_if_missing=create_composite,
        )
    return validation


def _file_receipt(path: Path) -> dict[str, JSONValue]:
    return {
        "byte_length": path.stat().st_size,
        "path": path.resolve().as_posix(),
        "sha256": sha256_file(path),
    }


def _ensure_child_authority(
    path: Path,
    *,
    integrity_parent_receipt: Path,
    plan: Sequence[SuiteSpec],
    plan_hash: str,
    source_root: Path,
    source_identity: Mapping[str, JSONValue],
    runtime_identity: Mapping[str, object],
    supervisor_import_identity: Mapping[str, object],
    integrity_inputs_path: Path,
    create_if_missing: bool = True,
) -> dict[str, object]:
    """Create or exactly reconstruct the no-semantic child authorization."""

    parent_raw = integrity_parent_receipt.read_bytes()
    parent_value: object = json.loads(parent_raw)
    if not isinstance(parent_value, dict):
        raise ValueError("integrity parent receipt is not an object")
    parent = cast(dict[str, object], parent_value)
    validation = parent.get("validation")
    predicates = validation.get("predicates") if isinstance(validation, Mapping) else None
    measurements = validation.get("measurements") if isinstance(validation, Mapping) else None
    parent_hash = parent.get("receipt_sha256")
    composite_receipt = parent.get("integrity_composite")
    integrity_inputs_receipt = parent.get("integrity_authority_inputs")
    runtime_observed = runtime_identity.get("observed")
    runtime_surface = (
        runtime_observed.get("runtime_surface") if isinstance(runtime_observed, Mapping) else None
    )
    composite_path = next(
        (
            suite.integrity_composite_path
            for suite in plan
            if suite.suite_id == "competition-integrity"
        ),
        None,
    )
    planned_integrity_inputs_hash = next(
        (
            suite.integrity_inputs_hash
            for suite in plan
            if suite.suite_id == "competition-integrity"
        ),
        None,
    )
    current_integrity_inputs = _integrity_inputs_summary(integrity_inputs_path)
    if (
        parent.get("schema") != STAGE10_PARENT_RECEIPT_SCHEMA
        or parent.get("suite_id") != "competition-integrity"
        or canonical_json_bytes(parent) != parent_raw
        or not verify_object_hash(parent, hash_field="receipt_sha256")
        or not isinstance(parent_hash, str)
        or not isinstance(validation, Mapping)
        or validation.get("artifact_valid") is not True
        or not isinstance(predicates, Mapping)
        or predicates.get("current_integrity_inputs_exact") is not True
        or predicates.get("package_only_scope_exact") is not True
        or predicates.get("package_only_inputs") is not True
        or predicates.get("composite_integrity_authority") is not True
        or not isinstance(measurements, Mapping)
        or not _verify_file_receipt(integrity_inputs_receipt, integrity_inputs_path)
        or measurements.get("integrity_inputs_file_sha256")
        != cast(Mapping[str, object], integrity_inputs_receipt).get("sha256")
        or not isinstance(measurements.get("integrity_inputs_hash"), str)
        or planned_integrity_inputs_hash is None
        or current_integrity_inputs.get("authority_inputs_hash") != planned_integrity_inputs_hash
        or measurements.get("integrity_inputs_hash") != planned_integrity_inputs_hash
        or measurements.get("integrity_inputs_schema") != _INTEGRITY_INPUTS_SCHEMA
        or measurements.get("composite_integrity_schema") != COMPOSITE_INTEGRITY_SCHEMA
        or composite_path is None
        or not _verify_file_receipt(composite_receipt, composite_path)
        or measurements.get("composite_integrity_file_sha256")
        != cast(Mapping[str, object], composite_receipt).get("sha256")
        or measurements.get("composite_integrity_core_hash") is None
        or not isinstance(runtime_surface, Mapping)
        or runtime_surface.get("verified") is not True
        or supervisor_import_identity.get("verified") is not True
        or not isinstance(supervisor_import_identity.get("supervisor_import_identity_sha256"), str)
    ):
        raise ValueError("integrity parent receipt cannot authorize later children")
    assert composite_path is not None
    assert isinstance(composite_receipt, Mapping)
    assert isinstance(integrity_inputs_receipt, Mapping)
    assert isinstance(runtime_surface, Mapping)
    validate_composite_integrity_authority(
        composite_path,
        expected_file_sha256=cast(str, composite_receipt["sha256"]),
        expected_core_hash=cast(str, measurements["composite_integrity_core_hash"]),
        source_root=source_root,
    )
    payload: dict[str, object] = {
        "authorized_suites": [
            suite.suite_id for suite in plan if suite.suite_id != "competition-integrity"
        ],
        "frozen_commit": source_identity.get("commit"),
        "integrity_parent_receipt_sha256": parent_hash,
        "integrity_inputs_hash": measurements.get("integrity_inputs_hash"),
        "integrity_composition": {
            "composite_integrity_core_hash": measurements.get("composite_integrity_core_hash"),
            "composite_integrity_file_sha256": measurements.get("composite_integrity_file_sha256"),
            "composite_integrity_schema": measurements.get("composite_integrity_schema"),
            "integrity_inputs_file_sha256": measurements.get("integrity_inputs_file_sha256"),
            "integrity_inputs_hash": measurements.get("integrity_inputs_hash"),
            "integrity_inputs_schema": measurements.get("integrity_inputs_schema"),
            "assurance_limitation": (
                "Package and development scans are static; dynamic-import and native-extension "
                "containment are not proven; Build 001 public identifiers were not fully evaluated."
            ),
            "full_public_integrity_status": "NOT_EVALUATED_BUILD_001_PUBLIC_IDENTIFIERS",
            "static_authority_claim": "BOUNDED_STATIC_COMPETITION_INTEGRITY_WITH_OPAQUE_HOLDOUT",
            "semantic_holdout_identifier_scan": "NOT_EVALUATED_SEALED_HOLDOUT_IDENTIFIERS",
            "dynamic_or_native_containment": "NOT_PROVEN_BY_STATIC_IMPORT_REACHABILITY",
        },
        "plan_hash": plan_hash,
        "predeclaration_sha256": PREDECLARATION_SHA256,
        "profile": {
            "authorized_surface": "synthetic-no-semantic-public-manifest",
            "public_identifier_values_available": 0,
            "public_manifest_paths_available": 0,
            "semantic_public_manifest_access": False,
        },
        "runtime_identity_sha256": runtime_identity.get("runtime_identity_sha256"),
        "runtime_surface": dict(runtime_surface),
        "schema": STAGE10_CHILD_AUTHORITY_SCHEMA,
        "source_commit": source_identity.get("commit"),
        "source_tree": source_identity.get("tree"),
        "supervisor_import_identity_sha256": supervisor_import_identity.get(
            "supervisor_import_identity_sha256"
        ),
    }
    authority = seal_object(payload, hash_field="authority_sha256")
    if path.exists():
        raw = path.read_bytes()
        observed: object = json.loads(raw)
        if (
            not isinstance(observed, dict)
            or canonical_json_bytes(observed) != raw
            or observed != authority
        ):
            raise ValueError("Stage 10 child authority changed during resume")
    elif create_if_missing:
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(path, authority)
    else:
        raise ValueError("Stage 10 child authority is missing during reconstruction")
    return authority


def _parent_receipt(
    *,
    suite: SuiteSpec,
    plan_hash: str,
    source_identity: Mapping[str, JSONValue],
    runtime_identity: Mapping[str, object],
    supervisor_import_identity: Mapping[str, object],
    returncode: int | None,
    timed_out: bool,
    launch_error: str | None,
    wall_ns: int,
    stdout_path: Path,
    stderr_path: Path,
    validation: SuiteValidation,
    integrity_inputs_path: Path,
) -> dict[str, object]:
    artifact = suite.artifact_path
    report: dict[str, object] = {
        "abort": (
            _file_receipt(suite.abort_path)
            if suite.abort_path is not None and suite.abort_path.is_file()
            else None
        ),
        "artifact": _file_receipt(artifact)
        if artifact is not None and artifact.is_file()
        else None,
        "authority": (
            _file_receipt(suite.authority_path)
            if suite.authority_path is not None and suite.authority_path.is_file()
            else None
        ),
        "command": list(suite.command),
        "cleanup": (
            _file_receipt(suite.cleanup_path)
            if suite.cleanup_path is not None and suite.cleanup_path.is_file()
            else None
        ),
        "integrity_composite": (
            _file_receipt(suite.integrity_composite_path)
            if suite.integrity_composite_path is not None
            and suite.integrity_composite_path.is_file()
            else None
        ),
        "integrity_authority_inputs": _file_receipt(integrity_inputs_path),
        "launch_error": launch_error,
        "launch_authorization": (
            _file_receipt(suite.authorization_path)
            if suite.authorization_path is not None and suite.authorization_path.is_file()
            else None
        ),
        "launch_receipt": (
            _file_receipt(suite.launch_path)
            if suite.launch_path is not None and suite.launch_path.is_file()
            else None
        ),
        "network_guard": (
            _file_receipt(suite.network_guard_path)
            if suite.network_guard_path is not None and suite.network_guard_path.is_file()
            else None
        ),
        "plan_hash": plan_hash,
        "predeclaration_sha256": PREDECLARATION_SHA256,
        "returncode": returncode,
        "runtime_identity": dict(runtime_identity),
        "schema": STAGE10_PARENT_RECEIPT_SCHEMA,
        "source_identity": dict(source_identity),
        "supervisor_import_identity": dict(supervisor_import_identity),
        "stderr": _file_receipt(stderr_path),
        "stdout": _file_receipt(stdout_path),
        "suite_id": suite.suite_id,
        "timed_out": timed_out,
        "validation": validation.to_dict(),
        "wall_ns": wall_ns,
    }
    return seal_object(report, hash_field="receipt_sha256")


def _verify_file_receipt(raw: object, expected: Path) -> bool:
    if not isinstance(raw, Mapping) or not expected.is_file():
        return False
    return (
        raw.get("path") == expected.resolve().as_posix()
        and raw.get("byte_length") == expected.stat().st_size
        and raw.get("sha256") == sha256_file(expected)
    )


def _preauthorization_failure(
    suite: SuiteSpec,
    *,
    stdout_path: Path,
    stderr_path: Path,
    launch_error: str,
) -> dict[str, object]:
    if suite.cleanup_path is None or not suite.cleanup_path.is_file():
        raise ValueError("preauthorization failure has no cleanup proof")
    if suite.authorization_path is not None and suite.authorization_path.exists():
        raise ValueError("preauthorization failure cannot have launch authorization")
    cleanup = _load_canonical_sealed(
        suite.cleanup_path,
        schema=STAGE10_PROCESS_CLEANUP_SCHEMA,
        hash_field="cleanup_receipt_hash",
        label="preauthorization cleanup",
    )
    expected_reason = f"child-failed-before-authorized-start:{suite.suite_id}:{launch_error}"
    pid = cleanup.get("pid")
    token = cleanup.get("process_creation_token")
    tokenless_cleanup = token is None and cleanup.get("method") in {
        None,
        "posix-killpg-unidentified-preauthorization",
        "windows-job-unidentified-preauthorization",
        "windows-popen-handle-unidentified-preauthorization",
    }
    if (
        cleanup.get("passed") is not True
        or cleanup.get("suite_id") != suite.suite_id
        or cleanup.get("reason") != expected_reason
        or cleanup.get("authorization_hash") is not None
        or cleanup.get("authorization_sha256") is not None
        or cleanup.get("error") is not None
        or isinstance(pid, bool)
        or not isinstance(pid, int)
        or (not isinstance(token, str) and not tokenless_cleanup)
        or (isinstance(token, str) and _process_creation_token(pid) == token)
        or (tokenless_cleanup and cleanup.get("live_process_token_before") is not None)
        or (tokenless_cleanup and cleanup.get("group_members_after") != [])
        or (os.name != "nt" and _posix_group_members(pid))
    ):
        raise ValueError("preauthorization cleanup cannot prove the child tree is gone")
    payload: dict[str, object] = {
        "abort": (
            _file_receipt(suite.abort_path)
            if suite.abort_path is not None and suite.abort_path.is_file()
            else None
        ),
        "cleanup": _file_receipt(suite.cleanup_path),
        "launch_error": launch_error,
        "launch_receipt": (
            _file_receipt(suite.launch_path)
            if suite.launch_path is not None and suite.launch_path.is_file()
            else None
        ),
        "schema": _PREAUTH_FAILURE_SCHEMA,
        "stderr": _file_receipt(stderr_path),
        "stdout": _file_receipt(stdout_path),
        "suite_id": suite.suite_id,
        "target_import_authorized": False,
    }
    return seal_object(payload, hash_field="failure_hash")


def _validate_preauthorization_failure(
    value: object,
    *,
    suite: SuiteSpec,
    attempt_root: Path,
) -> tuple[dict[str, object], str]:
    if not isinstance(value, Mapping):
        raise ValueError("terminal preauthorization failure is absent")
    failure = dict(value)
    expected_fields = {
        "abort",
        "cleanup",
        "failure_hash",
        "launch_error",
        "launch_receipt",
        "schema",
        "stderr",
        "stdout",
        "suite_id",
        "target_import_authorized",
    }
    launch_error = failure.get("launch_error")
    if (
        set(failure) != expected_fields
        or failure.get("schema") != _PREAUTH_FAILURE_SCHEMA
        or failure.get("suite_id") != suite.suite_id
        or failure.get("target_import_authorized") is not False
        or not isinstance(launch_error, str)
        or not verify_object_hash(failure, hash_field="failure_hash")
    ):
        raise ValueError("terminal preauthorization failure changed")
    expected = _preauthorization_failure(
        suite,
        stdout_path=attempt_root / "logs" / f"{suite.suite_id}.stdout",
        stderr_path=attempt_root / "logs" / f"{suite.suite_id}.stderr",
        launch_error=launch_error,
    )
    if failure != expected:
        raise ValueError("terminal preauthorization failure does not match live evidence")
    return failure, f"child-failed-before-authorized-start:{suite.suite_id}:{launch_error}"


def _resume_receipt(
    path: Path,
    *,
    suite: SuiteSpec,
    attempt_root: Path,
    source_root: Path,
    plan_hash: str,
    source_identity: Mapping[str, JSONValue],
    runtime_identity: Mapping[str, object],
    supervisor_import_identity: Mapping[str, object],
    integrity_inputs_path: Path,
) -> SuiteValidation:
    raw = path.read_bytes()
    value: object = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError(f"parent receipt {suite.suite_id} is not an object")
    receipt = cast(dict[str, object], value)
    if set(receipt) != {
        "abort",
        "artifact",
        "authority",
        "command",
        "cleanup",
        "integrity_composite",
        "integrity_authority_inputs",
        "launch_error",
        "launch_authorization",
        "launch_receipt",
        "network_guard",
        "plan_hash",
        "predeclaration_sha256",
        "receipt_sha256",
        "returncode",
        "runtime_identity",
        "schema",
        "source_identity",
        "stderr",
        "stdout",
        "suite_id",
        "supervisor_import_identity",
        "timed_out",
        "validation",
        "wall_ns",
    }:
        raise ValueError(f"parent receipt {suite.suite_id} fields are not exact")
    stdout_path = attempt_root / "logs" / f"{suite.suite_id}.stdout"
    stderr_path = attempt_root / "logs" / f"{suite.suite_id}.stderr"
    if (
        receipt.get("schema") != STAGE10_PARENT_RECEIPT_SCHEMA
        or receipt.get("suite_id") != suite.suite_id
        or receipt.get("command") != list(suite.command)
        or receipt.get("plan_hash") != plan_hash
        or receipt.get("predeclaration_sha256") != PREDECLARATION_SHA256
        or receipt.get("source_identity") != dict(source_identity)
        or receipt.get("runtime_identity") != dict(runtime_identity)
        or receipt.get("supervisor_import_identity") != dict(supervisor_import_identity)
        or canonical_json_bytes(receipt) != raw
        or not isinstance(receipt.get("timed_out"), bool)
        or (
            receipt.get("launch_error") is not None
            and not isinstance(receipt.get("launch_error"), str)
        )
        or isinstance(receipt.get("wall_ns"), bool)
        or not isinstance(receipt.get("wall_ns"), int)
        or cast(int, receipt.get("wall_ns")) < 0
        or not verify_object_hash(receipt, hash_field="receipt_sha256")
        or not _verify_file_receipt(receipt.get("stdout"), stdout_path)
        or not _verify_file_receipt(receipt.get("stderr"), stderr_path)
        or not _verify_file_receipt(
            receipt.get("integrity_authority_inputs"), integrity_inputs_path
        )
        or (
            suite.launch_path is not None
            and not _verify_file_receipt(receipt.get("launch_receipt"), suite.launch_path)
        )
        or (suite.launch_path is None and receipt.get("launch_receipt") is not None)
        or (
            suite.authorization_path is not None
            and not _verify_file_receipt(
                receipt.get("launch_authorization"), suite.authorization_path
            )
        )
        or (suite.authorization_path is None and receipt.get("launch_authorization") is not None)
        or (
            suite.cleanup_path is not None
            and not _verify_file_receipt(receipt.get("cleanup"), suite.cleanup_path)
        )
        or (suite.cleanup_path is None and receipt.get("cleanup") is not None)
        or (
            suite.abort_path is not None
            and suite.abort_path.exists()
            and not _verify_file_receipt(receipt.get("abort"), suite.abort_path)
        )
        or (
            (suite.abort_path is None or not suite.abort_path.exists())
            and receipt.get("abort") is not None
        )
        or (
            suite.authority_path is not None
            and not _verify_file_receipt(receipt.get("authority"), suite.authority_path)
        )
        or (suite.authority_path is None and receipt.get("authority") is not None)
        or (
            suite.network_guard_path is not None
            and not _verify_file_receipt(receipt.get("network_guard"), suite.network_guard_path)
        )
        or (suite.network_guard_path is None and receipt.get("network_guard") is not None)
        or (
            suite.artifact_path is not None
            and not _verify_file_receipt(receipt.get("artifact"), suite.artifact_path)
        )
        or (suite.artifact_path is None and receipt.get("artifact") is not None)
        or (
            suite.integrity_composite_path is not None
            and not _verify_file_receipt(
                receipt.get("integrity_composite"), suite.integrity_composite_path
            )
        )
        or (
            suite.integrity_composite_path is None
            and receipt.get("integrity_composite") is not None
        )
    ):
        raise ValueError(f"parent receipt {suite.suite_id} failed closed validation")
    returncode = receipt.get("returncode")
    if isinstance(returncode, bool) or (returncode is not None and not isinstance(returncode, int)):
        raise ValueError(f"parent receipt {suite.suite_id} has invalid returncode")
    launch = _validate_launch_receipt(suite, source_root=source_root)
    if suite.authorization_path is None:
        raise ValueError(f"parent receipt {suite.suite_id} has no authorization path")
    authorization_preview = _load_canonical_sealed(
        suite.authorization_path,
        schema=STAGE10_LAUNCH_AUTHORIZATION_SCHEMA,
        hash_field="authorization_hash",
        label="launch authorization",
    )
    containment = authorization_preview.get("containment")
    if not isinstance(containment, Mapping):
        raise ValueError(f"parent receipt {suite.suite_id} has invalid containment")
    expected_authorization = _authorization_payload(
        suite,
        launch=launch,
        plan_hash=plan_hash,
        source_root=source_root,
        source_identity=source_identity,
        runtime_identity=runtime_identity,
        supervisor_import_identity=supervisor_import_identity,
        containment=containment,
    )
    authorization = _validate_authorization_receipt(
        suite,
        expected=expected_authorization,
    )
    _validate_cleanup_receipt(
        suite,
        launch=launch,
        authorization=authorization,
    )
    validation = _validate_suite(
        suite,
        attempt_root=attempt_root,
        source_root=source_root,
        frozen_commit=cast(str, source_identity["commit"]),
        returncode=returncode,
        timed_out=receipt.get("timed_out") is True,
        launch_error=(
            cast(str, receipt["launch_error"])
            if isinstance(receipt.get("launch_error"), str)
            else None
        ),
        stdout_path=stdout_path,
        runtime_identity=runtime_identity,
        integrity_inputs_path=integrity_inputs_path,
    )
    if receipt.get("validation") != validation.to_dict():
        raise ValueError(f"parent receipt {suite.suite_id} validation drifted")
    return validation


def _resume_terminal_result(
    output: Path,
    *,
    preflight: Mapping[str, object],
    plan: Sequence[SuiteSpec],
    source_root: Path,
    attempt_root: Path,
    frozen_commit: str,
    integrity_inputs_path: Path,
) -> Stage10Status:
    """Validate an existing terminal graph without ever launching another child."""

    supervisor_now = _require_supervisor_import_origin(source_root)
    if preflight.get("supervisor_import_identity") != supervisor_now:
        raise ValueError("Stage 10 supervisor import identity disagrees with preflight")
    raw = output.read_bytes()
    value: object = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("existing Stage 10 result is not an object")
    result = cast(dict[str, object], value)
    expected_fields = {
        "artifact_core_hash",
        "claim",
        "evidence_label",
        "infrastructure_failure",
        "integrity_authority_inputs",
        "invocation_ledger",
        "plan_hash",
        "predeclaration_sha256",
        "preauthorization_failure",
        "process_cleanup_receipts",
        "runtime_identity_end",
        "runtime_identity_start",
        "schema",
        "source_identity_end",
        "source_identity_start",
        "status",
        "supervisor_import_identity_end",
        "supervisor_import_identity_start",
        "suite_validations",
    }
    if (
        set(result) != expected_fields
        or canonical_json_bytes(result) != raw
        or result.get("schema") != STAGE10_RESULT_SCHEMA
        or result.get("claim") != "NO_GENERALIZATION_CLAIM"
        or result.get("evidence_label") != "synthetic"
        or result.get("predeclaration_sha256") != PREDECLARATION_SHA256
        or result.get("plan_hash") != preflight.get("plan_hash")
        or not verify_object_hash(result, hash_field="artifact_core_hash")
        or not _verify_file_receipt(result.get("integrity_authority_inputs"), integrity_inputs_path)
    ):
        raise ValueError("existing Stage 10 result failed exact structural validation")
    source_now = _source_identity(source_root, frozen_commit)
    runtime_now = _runtime_identity(source_root, Path(plan[0].command[0])) if plan else {}
    if (
        source_now.get("verified") is not True
        or source_now != preflight.get("source_identity")
        or result.get("source_identity_start") != source_now
        or result.get("source_identity_end") != source_now
        or runtime_now.get("verified") is not True
        or runtime_now != preflight.get("runtime_identity")
        or result.get("runtime_identity_start") != runtime_now
        or result.get("runtime_identity_end") != runtime_now
        or result.get("supervisor_import_identity_start") != supervisor_now
        or result.get("supervisor_import_identity_end") != supervisor_now
    ):
        raise ValueError("existing Stage 10 result source/runtime identity drifted")
    ledger_path = attempt_root / "invocations.jsonl"
    if not _verify_file_receipt(result.get("invocation_ledger"), ledger_path):
        raise ValueError("existing Stage 10 result invocation ledger changed")
    plan_hash = cast(str, preflight["plan_hash"])
    records = _load_ledger(ledger_path)
    states = _ledger_states(records, plan_hash=plan_hash, plan=plan)
    started_ids = [
        cast(str, record["suite_id"]) for record in records if record.get("state") == "STARTED"
    ]
    plan_ids = [suite.suite_id for suite in plan]
    if started_ids != plan_ids[: len(started_ids)]:
        raise ValueError("existing Stage 10 ledger is not an exact plan prefix")
    validations: list[SuiteValidation] = []
    infrastructure_failure: str | None = None
    preauthorization_failure: dict[str, object] | None = None
    mechanism_terminal = False
    consumed_states = 0
    if not states and result.get("preauthorization_failure") is not None:
        if not plan:
            raise ValueError("preauthorization failure has no frozen suite")
        preauthorization_failure, infrastructure_failure = _validate_preauthorization_failure(
            result.get("preauthorization_failure"),
            suite=plan[0],
            attempt_root=attempt_root,
        )
    for index, suite in enumerate(plan):
        state = states.get(suite.suite_id)
        if state is None:
            break
        consumed_states += 1
        if state[0] == "STARTED":
            _recover_interrupted_suite(
                suite,
                started_record=state[2],
                source_root=source_root,
                plan_hash=plan_hash,
                source_identity=source_now,
                runtime_identity=runtime_now,
                supervisor_import_identity=supervisor_now,
            )
            infrastructure_failure = f"interrupted-suite-not-rerun:{suite.suite_id}"
            break
        if suite.authority_path is not None:
            _ensure_child_authority(
                suite.authority_path,
                integrity_parent_receipt=(attempt_root / "receipts" / "competition-integrity.json"),
                plan=plan,
                plan_hash=plan_hash,
                source_root=source_root,
                source_identity=source_now,
                runtime_identity=runtime_now,
                supervisor_import_identity=supervisor_now,
                integrity_inputs_path=integrity_inputs_path,
                create_if_missing=False,
            )
        receipt_path = attempt_root / "receipts" / f"{suite.suite_id}.json"
        validation = _resume_receipt(
            receipt_path,
            suite=suite,
            attempt_root=attempt_root,
            source_root=source_root,
            plan_hash=plan_hash,
            source_identity=source_now,
            runtime_identity=runtime_now,
            supervisor_import_identity=supervisor_now,
            integrity_inputs_path=integrity_inputs_path,
        )
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        if not isinstance(receipt, dict) or receipt.get("receipt_sha256") != state[1]:
            raise ValueError(f"existing Stage 10 receipt hash changed: {suite.suite_id}")
        validations.append(validation)
        if validation.disposition is SuiteDisposition.FAILED_INFRASTRUCTURE:
            infrastructure_failure = f"suite-failed-infrastructure:{suite.suite_id}"
            break
        if (
            suite.suite_id == "competition-integrity"
            and validation.disposition is SuiteDisposition.FAILED_MECHANISM
        ):
            mechanism_terminal = True
            break
        if index + 1 == len(plan):
            consumed_states = len(plan)
    if set(states) != set(plan_ids[:consumed_states]):
        raise ValueError("existing Stage 10 ledger continues past its terminal state")
    if mechanism_terminal:
        expected_status = Stage10Status.FAILED_MECHANISM
    elif len(validations) == len(plan):
        expected_status = classify_stage(validations)
    else:
        expected_status = Stage10Status.FAILED_INFRASTRUCTURE
        if infrastructure_failure is None:
            raise ValueError("existing Stage 10 terminal reason cannot be reconstructed")
    if expected_status is not Stage10Status.FAILED_INFRASTRUCTURE:
        infrastructure_failure = None
    reconstructed = seal_object(
        {
            "claim": "NO_GENERALIZATION_CLAIM",
            "evidence_label": "synthetic",
            "infrastructure_failure": infrastructure_failure,
            "integrity_authority_inputs": _file_receipt(integrity_inputs_path),
            "invocation_ledger": _file_receipt(ledger_path),
            "plan_hash": plan_hash,
            "predeclaration_sha256": PREDECLARATION_SHA256,
            "preauthorization_failure": preauthorization_failure,
            "process_cleanup_receipts": [
                _file_receipt(suite.cleanup_path)
                for suite in plan
                if suite.cleanup_path is not None and suite.cleanup_path.is_file()
            ],
            "runtime_identity_end": runtime_now,
            "runtime_identity_start": runtime_now,
            "schema": STAGE10_RESULT_SCHEMA,
            "source_identity_end": source_now,
            "source_identity_start": source_now,
            "status": expected_status.value,
            "supervisor_import_identity_end": supervisor_now,
            "supervisor_import_identity_start": supervisor_now,
            "suite_validations": [item.to_dict() for item in validations],
        },
        hash_field="artifact_core_hash",
    )
    if canonical_json_bytes(reconstructed) != raw:
        raise ValueError("existing Stage 10 terminal bytes differ from reconstructed evidence")
    return expected_status


def _execute(
    *,
    preflight: Mapping[str, object],
    plan: Sequence[SuiteSpec],
    source_root: Path,
    attempt_root: Path,
    output: Path,
    frozen_commit: str,
    integrity_inputs_path: Path,
) -> Stage10Status:
    supervisor_start = _require_supervisor_import_origin(source_root)
    if preflight.get("supervisor_import_identity") != supervisor_start:
        raise RuntimeError("Stage 10 supervisor import identity disagrees with preflight")
    if preflight.get("status") != "PASS":
        raise RuntimeError("Stage 10 execution refused a failing non-playing preflight")
    if output.exists():
        return _resume_terminal_result(
            output,
            preflight=preflight,
            plan=plan,
            source_root=source_root,
            attempt_root=attempt_root,
            frozen_commit=frozen_commit,
            integrity_inputs_path=integrity_inputs_path,
        )
    attempt_root.mkdir(parents=True, exist_ok=True)
    (attempt_root / "logs").mkdir(exist_ok=True)
    (attempt_root / "receipts").mkdir(exist_ok=True)
    ledger_path = attempt_root / "invocations.jsonl"
    if not ledger_path.exists():
        with ledger_path.open("xb") as ledger:
            ledger.flush()
            os.fsync(ledger.fileno())
    plan_hash = cast(str, preflight["plan_hash"])
    records = _load_ledger(ledger_path)
    states = _ledger_states(records, plan_hash=plan_hash, plan=plan)
    plan_ids = [item.suite_id for item in plan]
    started_ids = [
        cast(str, record["suite_id"]) for record in records if record.get("state") == "STARTED"
    ]
    if started_ids != plan_ids[: len(started_ids)]:
        raise ValueError("invocation ledger is not an exact serial plan prefix")
    source_start = _source_identity(source_root, frozen_commit)
    runtime_start = _runtime_identity(source_root, Path(plan[0].command[0])) if plan else {}
    validations: list[SuiteValidation] = []
    terminal_infrastructure: str | None = None
    preauthorization_failure: dict[str, object] | None = None
    if source_start.get("verified") is not True or preflight.get("source_identity") != source_start:
        terminal_infrastructure = "source-identity-disagrees-with-preflight"
    elif (
        runtime_start.get("verified") is not True
        or preflight.get("runtime_identity") != runtime_start
    ):
        terminal_infrastructure = "runtime-identity-disagrees-with-preflight"

    for suite in plan:
        if terminal_infrastructure is not None:
            break
        if _supervisor_import_identity(source_root) != supervisor_start:
            terminal_infrastructure = f"supervisor-import-changed-before-suite:{suite.suite_id}"
            break
        expected_child_authority: Mapping[str, object] | None = None
        if suite.authority_path is not None:
            try:
                expected_child_authority = _ensure_child_authority(
                    suite.authority_path,
                    integrity_parent_receipt=(
                        attempt_root / "receipts" / "competition-integrity.json"
                    ),
                    plan=plan,
                    plan_hash=plan_hash,
                    source_root=source_root,
                    source_identity=source_start,
                    runtime_identity=runtime_start,
                    supervisor_import_identity=supervisor_start,
                    integrity_inputs_path=integrity_inputs_path,
                )
            except (OSError, ValueError, EvaluationError, json.JSONDecodeError) as error:
                terminal_infrastructure = (
                    f"child-authority-invalid:{suite.suite_id}:{type(error).__name__}:{error}"
                )
                break
        if _source_identity(source_root, frozen_commit) != source_start:
            terminal_infrastructure = f"source-identity-changed-before-suite:{suite.suite_id}"
            break
        if _runtime_identity(source_root, Path(suite.command[0])) != runtime_start:
            terminal_infrastructure = f"runtime-identity-changed-before-suite:{suite.suite_id}"
            break
        state = states.get(suite.suite_id)
        receipt_path = attempt_root / "receipts" / f"{suite.suite_id}.json"
        if state is not None:
            if state[0] != "COMPLETED":
                _recover_interrupted_suite(
                    suite,
                    started_record=state[2],
                    source_root=source_root,
                    plan_hash=plan_hash,
                    source_identity=source_start,
                    runtime_identity=runtime_start,
                    supervisor_import_identity=supervisor_start,
                )
                terminal_infrastructure = f"interrupted-suite-not-rerun:{suite.suite_id}"
                break
            try:
                validation = _resume_receipt(
                    receipt_path,
                    suite=suite,
                    attempt_root=attempt_root,
                    source_root=source_root,
                    plan_hash=plan_hash,
                    source_identity=source_start,
                    runtime_identity=runtime_start,
                    supervisor_import_identity=supervisor_start,
                    integrity_inputs_path=integrity_inputs_path,
                )
            except (OSError, ValueError, EvaluationError, json.JSONDecodeError) as error:
                terminal_infrastructure = (
                    f"resume-validation-failed:{suite.suite_id}:{type(error).__name__}:{error}"
                )
                break
            expected_hash = state[1]
            actual_hash = json.loads(receipt_path.read_text(encoding="utf-8")).get("receipt_sha256")
            if actual_hash != expected_hash:
                terminal_infrastructure = f"ledger-receipt-hash-mismatch:{suite.suite_id}"
                break
            validations.append(validation)
            if validation.disposition is SuiteDisposition.FAILED_INFRASTRUCTURE:
                terminal_infrastructure = f"suite-failed-infrastructure:{suite.suite_id}"
                break
            if (
                suite.suite_id == "competition-integrity"
                and validation.disposition is SuiteDisposition.FAILED_MECHANISM
            ):
                break
            continue

        stdout_path = attempt_root / "logs" / f"{suite.suite_id}.stdout"
        stderr_path = attempt_root / "logs" / f"{suite.suite_id}.stderr"
        returncode, timed_out, launch_error, wall_ns, started = _run_child(
            suite,
            source_root=source_root,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
            ledger_path=ledger_path,
            records=records,
            plan_hash=plan_hash,
            source_identity=source_start,
            runtime_identity=runtime_start,
            supervisor_import_identity=supervisor_start,
            expected_authority=expected_child_authority,
        )
        if not started:
            if not isinstance(launch_error, str):
                raise RuntimeError("preauthorization child failure has no exact reason")
            preauthorization_failure = _preauthorization_failure(
                suite,
                stdout_path=stdout_path,
                stderr_path=stderr_path,
                launch_error=launch_error,
            )
            terminal_infrastructure = _validate_preauthorization_failure(
                preauthorization_failure,
                suite=suite,
                attempt_root=attempt_root,
            )[1]
            break
        validation = _validate_suite(
            suite,
            attempt_root=attempt_root,
            source_root=source_root,
            frozen_commit=frozen_commit,
            returncode=returncode,
            timed_out=timed_out,
            launch_error=launch_error,
            stdout_path=stdout_path,
            runtime_identity=runtime_start,
            integrity_inputs_path=integrity_inputs_path,
            create_composite=True,
        )
        source_after = _source_identity(source_root, frozen_commit)
        runtime_after = _runtime_identity(source_root, Path(suite.command[0]))
        if source_after != source_start:
            validation = _with_infrastructure_errors(
                validation,
                ("source-identity-changed-during-suite",),
            )
        if runtime_after != runtime_start:
            validation = _with_infrastructure_errors(
                validation,
                ("runtime-identity-changed-during-suite",),
            )
        if _supervisor_import_identity(source_root) != supervisor_start:
            validation = _with_infrastructure_errors(
                validation,
                ("supervisor-import-changed-during-suite",),
            )
        receipt = _parent_receipt(
            suite=suite,
            plan_hash=plan_hash,
            source_identity=source_start,
            runtime_identity=runtime_start,
            supervisor_import_identity=supervisor_start,
            returncode=returncode,
            timed_out=timed_out,
            launch_error=launch_error,
            wall_ns=wall_ns,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
            validation=validation,
            integrity_inputs_path=integrity_inputs_path,
        )
        if receipt_path.exists():
            raise RuntimeError(f"refusing to overwrite parent receipt {receipt_path}")
        atomic_write_json(receipt_path, receipt)
        receipt_hash = receipt.get("receipt_sha256")
        if not isinstance(receipt_hash, str):
            raise RuntimeError("sealed parent receipt has no hash")
        completed_record = _new_ledger_record(
            records,
            suite=suite,
            state="COMPLETED",
            plan_hash=plan_hash,
            receipt_hash=receipt_hash,
        )
        _append_record(ledger_path, completed_record)
        records.append(completed_record)
        validations.append(validation)
        if validation.disposition is SuiteDisposition.FAILED_INFRASTRUCTURE:
            terminal_infrastructure = f"suite-failed-infrastructure:{suite.suite_id}"
            break
        if (
            suite.suite_id == "competition-integrity"
            and validation.disposition is SuiteDisposition.FAILED_MECHANISM
        ):
            break

    status = classify_stage(validations)
    if terminal_infrastructure is not None:
        status = Stage10Status.FAILED_INFRASTRUCTURE
    source_end = _source_identity(source_root, frozen_commit)
    runtime_end = _runtime_identity(source_root, Path(plan[0].command[0])) if plan else {}
    if source_end != source_start:
        status = Stage10Status.FAILED_INFRASTRUCTURE
        terminal_infrastructure = "source-identity-changed-during-stage"
    if runtime_end != runtime_start:
        status = Stage10Status.FAILED_INFRASTRUCTURE
        terminal_infrastructure = "runtime-identity-changed-during-stage"
    supervisor_end = _supervisor_import_identity(source_root)
    if supervisor_end != supervisor_start:
        status = Stage10Status.FAILED_INFRASTRUCTURE
        terminal_infrastructure = "supervisor-import-changed-during-stage"
    report: dict[str, object] = {
        "claim": "NO_GENERALIZATION_CLAIM",
        "evidence_label": "synthetic",
        "infrastructure_failure": terminal_infrastructure,
        "integrity_authority_inputs": _file_receipt(integrity_inputs_path),
        "invocation_ledger": _file_receipt(ledger_path),
        "process_cleanup_receipts": [
            _file_receipt(suite.cleanup_path)
            for suite in plan
            if suite.cleanup_path is not None and suite.cleanup_path.is_file()
        ],
        "plan_hash": plan_hash,
        "predeclaration_sha256": PREDECLARATION_SHA256,
        "preauthorization_failure": preauthorization_failure,
        "schema": STAGE10_RESULT_SCHEMA,
        "runtime_identity_end": runtime_end,
        "runtime_identity_start": runtime_start,
        "source_identity_end": source_end,
        "source_identity_start": source_start,
        "status": status.value,
        "supervisor_import_identity_end": supervisor_end,
        "supervisor_import_identity_start": supervisor_start,
        "suite_validations": [item.to_dict() for item in validations],
    }
    sealed = seal_object(report, hash_field="artifact_core_hash")
    if output.exists():
        raise RuntimeError(f"refusing to overwrite Stage 10 result {output}")
    atomic_write_json(output, sealed)
    return status


def verify_terminal_evidence(
    *,
    source_root: Path,
    attempt_root: Path,
    output: Path,
    frozen_commit: str,
) -> bool:
    """Reconstruct a terminal Stage 10 graph without launching any child."""

    try:
        _require_supervisor_import_origin(source_root)
    except ValueError:
        return False
    if not output.resolve().is_file():
        return False
    first_receipt = attempt_root.resolve() / "receipts" / "competition-integrity.json"
    try:
        first_raw = first_receipt.read_bytes()
        first_value: object = json.loads(first_raw)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return False
    if (
        not isinstance(first_value, dict)
        or canonical_json_bytes(first_value) != first_raw
        or not isinstance(first_value.get("command"), list)
        or not first_value["command"]
        or not isinstance(first_value["command"][0], str)
        or not isinstance(first_value.get("integrity_authority_inputs"), Mapping)
        or not isinstance(
            cast(Mapping[str, object], first_value["integrity_authority_inputs"]).get("path"),
            str,
        )
    ):
        return False
    recorded_python = Path(os.path.abspath(first_value["command"][0]))
    integrity_inputs_path = Path(
        cast(
            str,
            cast(Mapping[str, object], first_value["integrity_authority_inputs"])["path"],
        )
    )
    if not _verify_file_receipt(first_value["integrity_authority_inputs"], integrity_inputs_path):
        return False
    preflight, plan = build_preflight(
        source_root=source_root.resolve(),
        python=recorded_python,
        attempt_root=attempt_root.resolve(),
        output=output.resolve(),
        frozen_commit=frozen_commit,
        integrity_inputs_path=integrity_inputs_path,
    )
    if preflight.get("status") != "PASS":
        return False
    return (
        _resume_terminal_result(
            output.resolve(),
            preflight=preflight,
            plan=plan,
            source_root=source_root.resolve(),
            attempt_root=attempt_root.resolve(),
            frozen_commit=frozen_commit,
            integrity_inputs_path=integrity_inputs_path,
        )
        is Stage10Status.PASS
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--python", type=Path, default=Path(sys.executable))
    parser.add_argument("--attempt-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--frozen-commit")
    parser.add_argument(
        "--integrity-authority-inputs",
        type=Path,
        required=True,
        help="external sealed opaque-holdout integrity-authority inputs",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="execute the frozen serial suite; omitted means non-playing preflight only",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(list(argv) if argv is not None else None)
    source_root = args.source_root.resolve()
    frozen_commit = args.frozen_commit or _git(source_root, "rev-parse", "HEAD")
    if (
        not isinstance(frozen_commit, str)
        or len(frozen_commit) != 40
        or any(character not in "0123456789abcdef" for character in frozen_commit)
    ):
        print("Stage 10 requires an exact lowercase 40-hex frozen commit", file=sys.stderr)
        return 2
    if args.execute and args.frozen_commit is None:
        print("--execute requires an explicit --frozen-commit", file=sys.stderr)
        return 2
    try:
        preflight, plan = build_preflight(
            source_root=source_root,
            python=Path(os.path.abspath(args.python)),
            attempt_root=args.attempt_root.resolve(),
            output=args.output.resolve(),
            frozen_commit=frozen_commit,
            integrity_inputs_path=args.integrity_authority_inputs.resolve(),
        )
    except (OSError, RuntimeError, ValueError, EvaluationError, json.JSONDecodeError) as error:
        print(f"Stage 10 preflight failed: {type(error).__name__}: {error}", file=sys.stderr)
        return 2
    if not args.execute:
        sys.stdout.buffer.write(canonical_json_bytes(preflight))
        return 0 if preflight.get("status") == "PASS" else 2
    try:
        status = _execute(
            preflight=preflight,
            plan=plan,
            source_root=source_root,
            attempt_root=args.attempt_root.resolve(),
            output=args.output.resolve(),
            frozen_commit=frozen_commit,
            integrity_inputs_path=args.integrity_authority_inputs.resolve(),
        )
    except (OSError, RuntimeError, ValueError, EvaluationError, json.JSONDecodeError) as error:
        print(f"Stage 10 supervisor failed: {type(error).__name__}: {error}", file=sys.stderr)
        return 2
    return 0 if status is Stage10Status.PASS else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
