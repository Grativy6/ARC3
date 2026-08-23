"""Preflight or serially execute the frozen Build 001 Stage 10 suites."""

from __future__ import annotations

import argparse
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

from arc3.evaluation.artifacts import (
    atomic_write_json,
    canonical_json_bytes,
    seal_object,
    sha256_file,
    verify_object_hash,
)
from arc3.evaluation.stage10_regression import (
    PREDECLARATION_PATH,
    PREDECLARATION_SHA256,
    PUBLIC_PARTITION_MANIFEST_SHA256,
    SOURCE_FLOOR_COMMIT,
    SOURCE_FLOOR_TREE,
    STAGE10_PARENT_RECEIPT_SCHEMA,
    STAGE10_PREFLIGHT_SCHEMA,
    STAGE10_RESULT_SCHEMA,
    STAGE10_SOCKET_DENIAL_SCHEMA,
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

ROOT = Path(__file__).resolve().parents[1]
_MANIFEST = Path("docs/evaluation/public-game-partitions.v0.1.json")
_LEDGER_SCHEMA = "arc3.build-001.stage-10-invocation.v0.1"
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
arc3 = importlib.util.find_spec("arc3")
stage10 = importlib.util.find_spec("arc3.evaluation.stage10_regression")
print(json.dumps({
    "arc3_origin": str(Path(arc3.origin).resolve()) if arc3 and arc3.origin else None,
    "implementation": platform.python_implementation(),
    "machine": platform.machine(),
    "platform": platform.platform(),
    "python_executable": str(Path(sys.executable).resolve()),
    "python_version": list(sys.version_info[:3]),
    "stage10_origin": str(Path(stage10.origin).resolve()) if stage10 and stage10.origin else None,
    "sys_prefix": str(Path(sys.prefix).resolve()),
}, sort_keys=True, separators=(",", ":")))
"""


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _git(root: Path, *arguments: str, check: bool = True) -> str:
    completed = subprocess.run(
        ("git", *arguments),
        cwd=root,
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
    return (
        subprocess.run(
            ("git", *arguments),
            cwd=root,
            check=False,
            capture_output=True,
            timeout=15,
        ).returncode
        == 0
    )


def _source_identity(source_root: Path, frozen_commit: str) -> dict[str, JSONValue]:
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
        "verified": (
            status == ""
            and commit == frozen_commit
            and floor_is_ancestor
            and floor_tree == SOURCE_FLOOR_TREE
        ),
    }


def _runtime_identity(source_root: Path, python: Path) -> dict[str, object]:
    executable = python.resolve()
    expected_arc3 = (source_root / "src/arc3/__init__.py").resolve()
    expected_stage10 = (source_root / "src/arc3/evaluation/stage10_regression.py").resolve()
    observed: dict[str, object] = {}
    error: str | None = None
    try:
        completed = subprocess.run(
            (str(executable), "-I", "-c", _RUNTIME_PROBE, str((source_root / "src").resolve())),
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
    executable_hash = sha256_file(executable) if executable.is_file() else None
    lock_hash = sha256_file(lock_path) if lock_path.is_file() else None
    version_value = observed.get("python_version")
    python_3_12 = (
        isinstance(version_value, list)
        and len(version_value) == 3
        and version_value[:2] == [3, 12]
        and all(isinstance(item, int) and not isinstance(item, bool) for item in version_value)
    )
    predicates = {
        "arc3_import_origin_exact": observed.get("arc3_origin") == str(expected_arc3),
        "executable_exists": executable.is_file(),
        "executable_reported_exact": observed.get("python_executable") == str(executable),
        "python_3_12": python_3_12,
        "stage10_import_origin_exact": observed.get("stage10_origin") == str(expected_stage10),
        "uv_lock_exact": lock_hash == UV_LOCK_SHA256,
    }
    report: dict[str, object] = {
        "error": error,
        "executable_sha256": executable_hash,
        "observed": observed,
        "predicates": predicates,
        "schema": "arc3.build-001.stage-10-runtime-identity.v0.1",
        "uv_lock_sha256": lock_hash,
        "verified": error is None and all(predicates.values()),
    }
    return seal_object(report, hash_field="runtime_identity_sha256")


def _outside_source(source_root: Path, candidate: Path) -> bool:
    try:
        candidate.resolve().relative_to(source_root.resolve())
    except ValueError:
        return True
    return False


def build_preflight(
    *,
    source_root: Path,
    python: Path,
    attempt_root: Path,
    output: Path,
    frozen_commit: str,
) -> tuple[dict[str, object], tuple[SuiteSpec, ...]]:
    """Validate identities and produce a non-playing plan without writing files."""

    declaration_path = source_root / PREDECLARATION_PATH
    declaration = validate_predeclaration_bytes(declaration_path.read_bytes())
    manifest_path = source_root / _MANIFEST
    identity = _source_identity(source_root, frozen_commit)
    runtime_identity = _runtime_identity(source_root, python)
    plan = build_suite_plan(
        python=python,
        source_root=source_root,
        attempt_root=attempt_root,
        frozen_commit=frozen_commit,
    )
    required_paths = tuple(
        path
        for path in (
            python,
            manifest_path,
            source_root / "uv.lock",
            source_root / "docs/ledger/build-001-run-state.json",
            source_root / "scripts/measure_ablations.py",
            source_root / "scripts/measure_palette_equivariance.py",
            source_root / "scripts/measure_action_equivariance.py",
            source_root / "scripts/measure_rule_change_reopening.py",
            source_root / "scripts/_stage10_checkpoint_worker.py",
            source_root / "scripts/_stage10_offline_child.py",
            source_root / "scripts/profile_competition.py",
            source_root / "scripts/check_competition_integrity.py",
            source_root / "src/arc3/evaluation/holdout_authority.py",
        )
    )
    predicates = {
        "attempt_root_external": _outside_source(source_root, attempt_root),
        "frozen_declaration": declaration.get("status") == "FROZEN_PREMEASUREMENT",
        "manifest_hash_exact": sha256_file(manifest_path) == PUBLIC_PARTITION_MANIFEST_SHA256,
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
            )
        },
        "required_paths_exist": all(path.exists() for path in required_paths),
        "runtime_identity": runtime_identity.get("verified") is True,
        "source_identity": identity.get("verified") is True,
    }
    report: dict[str, object] = {
        "claim": "NO_GENERALIZATION_CLAIM",
        "evidence_label": "synthetic",
        "mode": "NON_PLAYING_PREFLIGHT",
        "plan": [item.to_dict() for item in plan],
        "plan_hash": suite_plan_hash(plan),
        "predeclaration_sha256": PREDECLARATION_SHA256,
        "predicates": predicates,
        "runtime_identity": runtime_identity,
        "schema": STAGE10_PREFLIGHT_SCHEMA,
        "source_identity": identity,
        "status": "PASS" if all(predicates.values()) else "FAILED_INFRASTRUCTURE",
    }
    return seal_object(report, hash_field="preflight_hash"), plan


def _safe_environment(source_root: Path) -> dict[str, str]:
    environment = {
        key: value
        for key, value in os.environ.items()
        if not any(marker in key.upper() for marker in _SENSITIVE_ENV_MARKERS)
    }
    environment.update(
        {
            "ARC3_OFFLINE": "1",
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
    descriptor = os.open(path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
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
    for ordinal, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        value: object = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError(f"invocation ledger row {ordinal} is not an object")
        record = cast(dict[str, object], value)
        if (
            record.get("schema") != _LEDGER_SCHEMA
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


def _new_ledger_record(
    records: Sequence[Mapping[str, object]],
    *,
    suite: SuiteSpec,
    state: str,
    plan_hash: str,
    receipt_hash: str | None = None,
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
    if receipt_hash is not None:
        record["parent_receipt_hash"] = receipt_hash
    return seal_object(record, hash_field="record_hash")


def _ledger_states(
    records: Sequence[Mapping[str, object]],
    *,
    plan_hash: str,
) -> dict[str, tuple[str, str | None]]:
    states: dict[str, tuple[str, str | None]] = {}
    active_suite: str | None = None
    for record in records:
        suite_id = record.get("suite_id")
        state = record.get("state")
        if (
            not isinstance(suite_id, str)
            or state not in {"STARTED", "COMPLETED"}
            or record.get("plan_hash") != plan_hash
        ):
            raise ValueError("invocation ledger disagrees with the frozen plan")
        prior = states.get(suite_id)
        if state == "STARTED":
            if prior is not None or active_suite is not None:
                raise ValueError(f"suite {suite_id} was started more than once")
            states[suite_id] = ("STARTED", None)
            active_suite = suite_id
        else:
            receipt_hash = record.get("parent_receipt_hash")
            if (
                prior != ("STARTED", None)
                or active_suite != suite_id
                or not isinstance(receipt_hash, str)
            ):
                raise ValueError(f"suite {suite_id} completion has no unique start")
            states[suite_id] = ("COMPLETED", receipt_hash)
            active_suite = None
    return states


def _terminate_process_tree(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(
            ("taskkill", "/PID", str(process.pid), "/T", "/F"),
            check=False,
            capture_output=True,
            timeout=15,
        )
    else:
        try:
            kill_process_group = cast(
                Callable[[int, int], None],
                getattr(os, "killpg"),  # noqa: B009 - absent from Windows typeshed
            )
            kill_process_group(process.pid, int(getattr(signal, "SIGKILL", 9)))
        except ProcessLookupError:
            pass


def _run_child(
    suite: SuiteSpec,
    *,
    source_root: Path,
    stdout_path: Path,
    stderr_path: Path,
) -> tuple[int | None, bool, str | None, int]:
    guard_path = suite.network_guard_path
    if (
        stdout_path.exists()
        or stderr_path.exists()
        or (guard_path is not None and guard_path.exists())
    ):
        stdout_path.parent.mkdir(parents=True, exist_ok=True)
        stdout_path.touch(exist_ok=True)
        stderr_path.touch(exist_ok=True)
        return None, False, "raw stream path already exists", 0
    stdout_path.parent.mkdir(parents=True, exist_ok=True)
    if guard_path is not None:
        guard_path.parent.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter_ns()
    creationflags = _WINDOWS_CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
    try:
        with stdout_path.open("xb") as stdout, stderr_path.open("xb") as stderr:
            process = subprocess.Popen(
                suite.command,
                cwd=source_root,
                env=_safe_environment(source_root),
                stdin=subprocess.DEVNULL,
                stdout=stdout,
                stderr=stderr,
                creationflags=creationflags,
                start_new_session=os.name != "nt",
            )
            try:
                returncode = process.wait(timeout=suite.timeout_seconds)
            except subprocess.TimeoutExpired:
                _terminate_process_tree(process)
                process.wait(timeout=30)
                return None, True, None, max(0, time.perf_counter_ns() - started)
    except OSError as error:
        stdout_path.touch(exist_ok=True)
        stderr_path.touch(exist_ok=True)
        return (
            None,
            False,
            f"{type(error).__name__}: {error}",
            max(0, time.perf_counter_ns() - started),
        )
    return returncode, False, None, max(0, time.perf_counter_ns() - started)


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
        value: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        return (f"socket-denial-receipt-unreadable:{type(error).__name__}",), -1
    if not isinstance(value, dict):
        return ("socket-denial-receipt-not-object",), -1
    receipt = cast(dict[str, object], value)
    expected_fields = {
        "attempts",
        "failure_kind",
        "frozen_commit",
        "installed_operations",
        "network_attempt_count",
        "process_id",
        "receipt_sha256",
        "schema",
        "suite_id",
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
    errors: list[str] = []
    predicates = {
        "fields_exact": set(receipt) == expected_fields,
        "hash_valid": verify_object_hash(receipt, hash_field="receipt_sha256"),
        "identity_exact": receipt.get("frozen_commit") == frozen_commit
        and receipt.get("suite_id") == suite.suite_id,
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


def _validate_suite(
    suite: SuiteSpec,
    *,
    attempt_root: Path,
    frozen_commit: str,
    returncode: int | None,
    timed_out: bool,
    launch_error: str | None,
    stdout_path: Path,
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
    return _with_infrastructure_errors(validation, errors)


def _file_receipt(path: Path) -> dict[str, JSONValue]:
    return {
        "byte_length": path.stat().st_size,
        "path": path.resolve().as_posix(),
        "sha256": sha256_file(path),
    }


def _parent_receipt(
    *,
    suite: SuiteSpec,
    plan_hash: str,
    source_identity: Mapping[str, JSONValue],
    runtime_identity: Mapping[str, object],
    returncode: int | None,
    timed_out: bool,
    launch_error: str | None,
    wall_ns: int,
    stdout_path: Path,
    stderr_path: Path,
    validation: SuiteValidation,
) -> dict[str, object]:
    artifact = suite.artifact_path
    report: dict[str, object] = {
        "artifact": _file_receipt(artifact)
        if artifact is not None and artifact.is_file()
        else None,
        "command": list(suite.command),
        "launch_error": launch_error,
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


def _resume_receipt(
    path: Path,
    *,
    suite: SuiteSpec,
    attempt_root: Path,
    plan_hash: str,
    source_identity: Mapping[str, JSONValue],
    runtime_identity: Mapping[str, object],
) -> SuiteValidation:
    value: object = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"parent receipt {suite.suite_id} is not an object")
    receipt = cast(dict[str, object], value)
    if set(receipt) != {
        "artifact",
        "command",
        "launch_error",
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
        or (
            suite.network_guard_path is not None
            and not _verify_file_receipt(receipt.get("network_guard"), suite.network_guard_path)
        )
        or (
            suite.artifact_path is not None
            and not _verify_file_receipt(receipt.get("artifact"), suite.artifact_path)
        )
    ):
        raise ValueError(f"parent receipt {suite.suite_id} failed closed validation")
    returncode = receipt.get("returncode")
    if isinstance(returncode, bool) or (returncode is not None and not isinstance(returncode, int)):
        raise ValueError(f"parent receipt {suite.suite_id} has invalid returncode")
    validation = _validate_suite(
        suite,
        attempt_root=attempt_root,
        frozen_commit=cast(str, source_identity["commit"]),
        returncode=returncode,
        timed_out=receipt.get("timed_out") is True,
        launch_error=(
            cast(str, receipt["launch_error"])
            if isinstance(receipt.get("launch_error"), str)
            else None
        ),
        stdout_path=stdout_path,
    )
    if receipt.get("validation") != validation.to_dict():
        raise ValueError(f"parent receipt {suite.suite_id} validation drifted")
    return validation


def _execute(
    *,
    preflight: Mapping[str, object],
    plan: Sequence[SuiteSpec],
    source_root: Path,
    attempt_root: Path,
    output: Path,
    frozen_commit: str,
) -> Stage10Status:
    if preflight.get("status") != "PASS":
        raise RuntimeError("Stage 10 execution refused a failing non-playing preflight")
    attempt_root.mkdir(parents=True, exist_ok=True)
    (attempt_root / "logs").mkdir(exist_ok=True)
    (attempt_root / "receipts").mkdir(exist_ok=True)
    ledger_path = attempt_root / "invocations.jsonl"
    plan_hash = cast(str, preflight["plan_hash"])
    records = _load_ledger(ledger_path)
    states = _ledger_states(records, plan_hash=plan_hash)
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
    if (
        runtime_start.get("verified") is not True
        or preflight.get("runtime_identity") != runtime_start
    ):
        terminal_infrastructure = "runtime-identity-disagrees-with-preflight"

    for suite in plan:
        if terminal_infrastructure is not None:
            break
        if _runtime_identity(source_root, Path(suite.command[0])) != runtime_start:
            terminal_infrastructure = f"runtime-identity-changed-before-suite:{suite.suite_id}"
            break
        state = states.get(suite.suite_id)
        receipt_path = attempt_root / "receipts" / f"{suite.suite_id}.json"
        if state is not None:
            if state[0] != "COMPLETED":
                terminal_infrastructure = f"interrupted-suite-not-rerun:{suite.suite_id}"
                break
            try:
                validation = _resume_receipt(
                    receipt_path,
                    suite=suite,
                    attempt_root=attempt_root,
                    plan_hash=plan_hash,
                    source_identity=source_start,
                    runtime_identity=runtime_start,
                )
            except (OSError, ValueError, json.JSONDecodeError) as error:
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
            continue

        started_record = _new_ledger_record(
            records,
            suite=suite,
            state="STARTED",
            plan_hash=plan_hash,
        )
        _append_record(ledger_path, started_record)
        records.append(started_record)
        stdout_path = attempt_root / "logs" / f"{suite.suite_id}.stdout"
        stderr_path = attempt_root / "logs" / f"{suite.suite_id}.stderr"
        returncode, timed_out, launch_error, wall_ns = _run_child(
            suite,
            source_root=source_root,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
        )
        validation = _validate_suite(
            suite,
            attempt_root=attempt_root,
            frozen_commit=frozen_commit,
            returncode=returncode,
            timed_out=timed_out,
            launch_error=launch_error,
            stdout_path=stdout_path,
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
        receipt = _parent_receipt(
            suite=suite,
            plan_hash=plan_hash,
            source_identity=source_start,
            runtime_identity=runtime_start,
            returncode=returncode,
            timed_out=timed_out,
            launch_error=launch_error,
            wall_ns=wall_ns,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
            validation=validation,
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
    report: dict[str, object] = {
        "claim": "NO_GENERALIZATION_CLAIM",
        "evidence_label": "synthetic",
        "infrastructure_failure": terminal_infrastructure,
        "invocation_ledger": _file_receipt(ledger_path),
        "plan_hash": plan_hash,
        "predeclaration_sha256": PREDECLARATION_SHA256,
        "schema": STAGE10_RESULT_SCHEMA,
        "runtime_identity_end": runtime_end,
        "runtime_identity_start": runtime_start,
        "source_identity_end": source_end,
        "source_identity_start": source_start,
        "status": status.value,
        "suite_validations": [item.to_dict() for item in validations],
    }
    sealed = seal_object(report, hash_field="artifact_core_hash")
    if output.exists():
        raise RuntimeError(f"refusing to overwrite Stage 10 result {output}")
    atomic_write_json(output, sealed)
    return status


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=ROOT)
    parser.add_argument("--python", type=Path, default=Path(sys.executable))
    parser.add_argument("--attempt-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--frozen-commit")
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
            python=args.python.resolve(),
            attempt_root=args.attempt_root.resolve(),
            output=args.output.resolve(),
            frozen_commit=frozen_commit,
        )
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as error:
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
        )
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as error:
        print(f"Stage 10 supervisor failed: {type(error).__name__}: {error}", file=sys.stderr)
        return 2
    return 0 if status is Stage10Status.PASS else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
