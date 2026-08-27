"""Run sealed Build 000 or package-only Build 001 clean-clone checks.

The verifier is intentionally a repository-side orchestrator. A caller creates a
fresh clone, follows the documented bootstrap, and then invokes this script with
the literal candidate commit. The script does not clone, install, authenticate,
accept terms, upload, submit, or mutate tracked repository files.
"""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import importlib.util
import io
import json
import os
import platform
import re
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import zipfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from arc3.evaluation.artifacts import canonical_json_bytes as evaluation_canonical_json_bytes
from arc3.integrity import read_bounded_regular_snapshot, scan_archive_files
from arc3.integrity.scanner import (
    DEFAULT_MAX_ARCHIVE_BYTES,
    DEFAULT_MAX_ARCHIVE_CENTRAL_DIRECTORY_BYTES,
    DEFAULT_MAX_ARCHIVE_DEPTH,
    DEFAULT_MAX_ARCHIVE_EXPANDED_BYTES,
    DEFAULT_MAX_ARCHIVE_MEMBER_BYTES,
    DEFAULT_MAX_ARCHIVE_MEMBERS,
    DEFAULT_MAX_CANDIDATE_BYTES,
)
from arc3.packaging.builder import collect_git_payload
from arc3.packaging.candidate import (
    decode_candidate_archive_snapshot,
    validate_candidate_member_snapshots,
)
from arc3.packaging.notebook import notebook_embedded_inputs
from arc3.packaging.util import (
    canonical_json_bytes as package_canonical_json_bytes,
)
from arc3.packaging.util import (
    deterministic_zip_bytes,
)
from scripts.package_only_pytest import (
    BUILD001_BOUNDARY_EXCLUSIONS,
    ORDINARY_CI_FULL_SUITE_COMMAND,
    build001_test_selection,
)
from scripts.package_only_pytest import (
    CLAIM_SCOPE as PACKAGE_ONLY_TEST_CLAIM_SCOPE,
)
from scripts.package_only_pytest import (
    SCHEMA as PACKAGE_ONLY_PYTEST_SCHEMA,
)

SCHEMA = "arc3.release-candidate-verification.v0.1"
PLAN_SCHEMA = "arc3.release-candidate-plan.v0.1"
EXPECTATION_SCHEMA = "arc3.release-benchmark-expectation.v0.1"
RECEIPT_HASH_FIELD = "receipt_sha256"
EXPECTATION_HASH_FIELD = "expectation_sha256"
REPOSITORY = Path(__file__).resolve().parents[1]
DEFAULT_EXPECTATION = Path(__file__).with_name("release_candidate_benchmark.v0.1.json")
BUILD000_PROFILE = "build000-release"
BUILD001_PACKAGE_ONLY_PROFILE = "build001-package-only"
VERIFICATION_PROFILES = (BUILD000_PROFILE, BUILD001_PACKAGE_ONLY_PROFILE)

_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_SAFE_CHECK_ID = re.compile(r"^[a-z0-9][a-z0-9-]*$")
_SENSITIVE_ENV_FRAGMENTS = (
    "API_KEY",
    "AUTH",
    "CREDENTIAL",
    "KAGGLE",
    "PASSWORD",
    "SECRET",
    "TOKEN",
)
_PASSTHROUGH_ENVIRONMENT = frozenset(
    {
        "COMSPEC",
        "LANG",
        "LC_ALL",
        "PATH",
        "PATHEXT",
        "SYSTEMDRIVE",
        "SYSTEMROOT",
        "WINDIR",
    }
)
_SECRET_PATTERNS = (
    re.compile(rb"-----BEGIN (?:RSA |EC |DSA |OPENSSH |PGP )?PRIVATE KEY-----"),
    re.compile(rb"(?i)\b(?:sk-[a-z0-9_-]{16,}|gh[oprsu]_[a-z0-9]{16,})\b"),
    re.compile(rb"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(rb"\bAIza[0-9A-Za-z_-]{30,}\b"),
    re.compile(rb"\beyJ[A-Za-z0-9_-]{12,}\.[A-Za-z0-9_-]{12,}\.[A-Za-z0-9_-]{12,}\b"),
    re.compile(
        rb"(?i)\b(?:api[_-]?key|authorization|credential|password|secret|token)"
        rb"\s*[:=]\s*['\"]?[^\s'\"]{8,}"
    ),
)
_TRANSIENT_OUTPUT_PREFIXES = ("cache/", "coverage/", "home/", "hypothesis/", "tmp/")
_RECEIPT_WRAPPERS = frozenset(
    {"release-verification-evidence.json", "release-verification-receipt.json"}
)
_INTERNAL_CHECKS = (
    "benchmark-basis-validation",
    "benchmark-semantic-reproduction",
    "generated-log-secret-scan",
    "interpreter-source-identity",
    "offline-package-determinism",
    "integrity-receipt-validation",
    "official-availability",
    "repository-clean-after",
    "sealed-artifact-set",
)
_PACKAGE_ONLY_INTERNAL_CHECKS = (
    "generated-log-secret-scan",
    "integrity-receipt-validation",
    "interpreter-source-identity",
    "offline-package-determinism",
    "package-test-guard-validation",
    "package-runtime-metrics",
    "private-kaggle-surfaces",
    "repository-clean-after",
    "sealed-artifact-set",
    "source-lock-identity",
)
_PACKAGE_ONLY_FORBIDDEN_PLAN_FRAGMENTS = (
    "docs/evaluation/",
    "evaluate_public.py",
    "official-environments",
    "official-inventory",
    "official-smoke",
    "public-game-partitions",
    "scripts/evaluate_public",
    "scripts.evaluate_public",
)
_PRODUCTION_POLICY_ENTRY_POINTS = ("agent/my_agent.py",)


def canonical_json_bytes(value: object) -> bytes:
    """Encode a JSON value deterministically, rejecting non-finite floats."""

    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    """Return the repository's qualified SHA-256 spelling."""

    return f"sha256:{hashlib.sha256(value).hexdigest()}"


def sha256_file(path: Path) -> str:
    """Hash one regular file without following a replacement during the read."""

    if not path.is_file() or path.is_symlink():
        raise ValueError(f"artifact must be a regular non-symlink file: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def write_bytes_atomic(path: Path, content: bytes) -> None:
    """Write one evidence file atomically on the destination filesystem."""

    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _json_object_bytes(raw: bytes, *, label: str) -> dict[str, Any]:
    try:
        loaded: object = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"cannot decode JSON object {label}: {error}") from error
    if not isinstance(loaded, dict):
        raise ValueError(f"JSON artifact must contain an object: {label}")
    return cast(dict[str, Any], loaded)


def _json_object(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_bytes()
    except OSError as error:
        raise ValueError(f"cannot read JSON object {path}: {error}") from error
    return _json_object_bytes(raw, label=str(path))


def _verified_self_hashed_bytes(
    raw: bytes,
    *,
    label: str,
    hash_field: str,
) -> dict[str, Any]:
    document = _json_object_bytes(raw, label=label)
    claimed = document.pop(hash_field, None)
    if not isinstance(claimed, str):
        raise ValueError(f"{label} has no string {hash_field}")
    actual = sha256_bytes(canonical_json_bytes(document))
    if claimed != actual:
        raise ValueError(f"{label} {hash_field} mismatch: expected {claimed}, computed {actual}")
    return document


def _verified_self_hashed_object(path: Path, *, hash_field: str) -> dict[str, Any]:
    return _verified_self_hashed_bytes(
        path.read_bytes(),
        label=str(path),
        hash_field=hash_field,
    )


def _package_receipt_bytes(body: Mapping[str, Any]) -> bytes:
    """Encode a Stage 17 package receipt with its producer's LF-terminated contract."""

    document = dict(body)
    document[RECEIPT_HASH_FIELD] = sha256_bytes(package_canonical_json_bytes(body))
    return package_canonical_json_bytes(document)


def _verified_package_receipt_bytes(raw: bytes, *, label: str) -> dict[str, Any]:
    """Verify one immutable Stage 17 receipt snapshot."""

    document = _json_object_bytes(raw, label=label)
    claimed = document.pop(RECEIPT_HASH_FIELD, None)
    if not isinstance(claimed, str):
        raise ValueError(f"{label} has no string {RECEIPT_HASH_FIELD}")
    actual = sha256_bytes(package_canonical_json_bytes(document))
    if claimed != actual:
        raise ValueError(
            f"{label} {RECEIPT_HASH_FIELD} mismatch: expected {claimed}, computed {actual}"
        )
    if _package_receipt_bytes(document) != raw:
        raise ValueError(f"package receipt is not canonical JSON: {label}")
    return document


def load_benchmark_expectation(path: Path) -> dict[str, Any]:
    """Load and self-verify the frozen semantic benchmark expectation."""

    document = _verified_self_hashed_object(path, hash_field=EXPECTATION_HASH_FIELD)
    if document.get("schema") != EXPECTATION_SCHEMA:
        raise ValueError(f"unsupported benchmark expectation schema in {path}")
    configuration = document.get("configuration")
    projection = document.get("expected_projection")
    if not isinstance(configuration, dict) or not isinstance(projection, dict):
        raise ValueError("benchmark expectation must contain configuration and projection objects")
    return document


@dataclass(frozen=True, slots=True)
class CommandSpec:
    """One exact process declaration in the release verification plan."""

    check_id: str
    category: str
    argv: tuple[str, ...]
    timeout_seconds: float
    required: bool = True
    dependencies: tuple[str, ...] = ()
    failure_status: str = "FAILED_MECHANISM"
    nondeterminism: tuple[str, ...] = ()
    measure_peak_rss: bool = False

    def __post_init__(self) -> None:
        if not _SAFE_CHECK_ID.fullmatch(self.check_id):
            raise ValueError(f"invalid check id: {self.check_id!r}")
        if not self.argv or not all(self.argv):
            raise ValueError(f"check {self.check_id} has an empty command")
        if self.timeout_seconds <= 0:
            raise ValueError(f"check {self.check_id} has a non-positive timeout")
        if self.failure_status not in {"FAILED_MECHANISM", "FAILED_INFRASTRUCTURE"}:
            raise ValueError(f"check {self.check_id} has an invalid failure status")

    def to_dict(self) -> dict[str, object]:
        document: dict[str, object] = {
            "argv": list(self.argv),
            "category": self.category,
            "dependencies": list(self.dependencies),
            "failure_status": self.failure_status,
            "id": self.check_id,
            "nondeterminism": list(self.nondeterminism),
            "required": self.required,
            "timeout_seconds": self.timeout_seconds,
        }
        if self.measure_peak_rss:
            document["measure_peak_rss"] = True
        return document


@dataclass(frozen=True, slots=True)
class CheckResult:
    """One process or internal verification result."""

    check_id: str
    category: str
    kind: str
    required: bool
    status: str
    started_at: str | None
    completed_at: str | None
    duration_seconds: float | None
    argv: tuple[str, ...]
    exit_code: int | None
    stdout_log: str | None
    stdout_sha256: str | None
    stderr_log: str | None
    stderr_sha256: str | None
    reason: str | None
    details: Mapping[str, object]

    def to_dict(self) -> dict[str, object]:
        return {
            "argv": list(self.argv),
            "category": self.category,
            "completed_at": self.completed_at,
            "details": dict(self.details),
            "duration_seconds": self.duration_seconds,
            "exit_code": self.exit_code,
            "id": self.check_id,
            "kind": self.kind,
            "reason": self.reason,
            "required": self.required,
            "started_at": self.started_at,
            "status": self.status,
            "stderr_log": self.stderr_log,
            "stderr_sha256": self.stderr_sha256,
            "stdout_log": self.stdout_log,
            "stdout_sha256": self.stdout_sha256,
        }


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _path_for_receipt(path: Path, base: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(base.resolve()).as_posix()
    except ValueError:
        return str(resolved)


def _display_command(argv: Sequence[str]) -> str:
    if os.name == "nt":
        return subprocess.list2cmdline(list(argv))
    return shlex.join(argv)


def _sensitive_environment_values() -> tuple[bytes, ...]:
    values = {
        value.encode("utf-8", errors="ignore")
        for name, value in os.environ.items()
        if any(fragment in name.upper() for fragment in _SENSITIVE_ENV_FRAGMENTS)
        and len(value) >= 8
    }
    return tuple(sorted(values, key=len, reverse=True))


def _redact_generated_log(content: bytes) -> tuple[bytes, int]:
    """Remove inherited credential values and recognizable token assignments before writing."""

    redacted = content
    replacements = 0
    for value in _sensitive_environment_values():
        count = redacted.count(value)
        if count:
            redacted = redacted.replace(value, b"[REDACTED_ENV_VALUE]")
            replacements += count
    for pattern in _SECRET_PATTERNS:
        redacted, count = pattern.subn(b"[REDACTED_SECRET_PATTERN]", redacted)
        replacements += count
    return redacted, replacements


def _sanitized_environment(transient_root: Path, check_id: str) -> tuple[dict[str, str], int]:
    environment = {
        name: value
        for name, value in os.environ.items()
        if name.upper() in _PASSTHROUGH_ENVIRONMENT
    }
    removed = len(os.environ) - len(environment)
    temporary = transient_root / "tmp" / check_id
    coverage = transient_root / "coverage"
    hypothesis = transient_root / "hypothesis" / check_id
    mypy_cache = transient_root / "cache" / "mypy" / check_id
    ruff_cache = transient_root / "cache" / "ruff" / check_id
    isolated_home = transient_root / "home" / check_id
    uv_cache = transient_root / "cache" / "uv" / check_id
    for directory in (
        temporary,
        coverage,
        hypothesis,
        mypy_cache,
        ruff_cache,
        isolated_home,
        uv_cache,
    ):
        directory.mkdir(parents=True, exist_ok=True)
    environment.update(
        {
            "COVERAGE_FILE": str(coverage / f".{check_id}.coverage"),
            "HYPOTHESIS_STORAGE_DIRECTORY": str(hypothesis),
            "MYPY_CACHE_DIR": str(mypy_cache),
            "NO_PROXY": "*",
            "PIP_NO_INDEX": "1",
            "PYTHONHASHSEED": "0",
            "PYTHONNOUSERSITE": "1",
            "RUFF_CACHE_DIR": str(ruff_cache),
            "HOME": str(isolated_home),
            "TEMP": str(temporary),
            "TMP": str(temporary),
            "USERPROFILE": str(isolated_home),
            "UV_CACHE_DIR": str(uv_cache),
            "UV_OFFLINE": "1",
            "XDG_CACHE_HOME": str(transient_root / "cache" / "xdg" / check_id),
        }
    )
    return environment, removed


def _blocked_result(spec: CommandSpec, reason: str, *, status: str) -> CheckResult:
    return CheckResult(
        check_id=spec.check_id,
        category=spec.category,
        kind="command",
        required=spec.required,
        status=status,
        started_at=None,
        completed_at=None,
        duration_seconds=None,
        argv=spec.argv,
        exit_code=None,
        stdout_log=None,
        stdout_sha256=None,
        stderr_log=None,
        stderr_sha256=None,
        reason=reason,
        details={"command": _display_command(spec.argv)},
    )


class _ProcessMemoryCounters(ctypes.Structure):
    _fields_ = [
        ("cb", ctypes.c_uint32),
        ("PageFaultCount", ctypes.c_uint32),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t),
        ("PeakPagefileUsage", ctypes.c_size_t),
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


class _JobObjectBasicLimitInformation(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_int64),
        ("PerJobUserTimeLimit", ctypes.c_int64),
        ("LimitFlags", ctypes.c_uint32),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", ctypes.c_uint32),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", ctypes.c_uint32),
        ("SchedulingClass", ctypes.c_uint32),
    ]


class _JobObjectExtendedLimitInformation(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", _JobObjectBasicLimitInformation),
        ("IoInfo", _IoCounters),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


class _ThreadEntry32(ctypes.Structure):
    _fields_ = [
        ("dwSize", ctypes.c_uint32),
        ("cntUsage", ctypes.c_uint32),
        ("th32ThreadID", ctypes.c_uint32),
        ("th32OwnerProcessID", ctypes.c_uint32),
        ("tpBasePri", ctypes.c_long),
        ("tpDeltaPri", ctypes.c_long),
        ("dwFlags", ctypes.c_uint32),
    ]


def _windows_kernel32() -> Any:
    windll = getattr(ctypes, "windll", None)
    if windll is None:
        raise OSError("Windows kernel32 is unavailable through ctypes")
    return windll.kernel32


def _close_windows_handle(handle: int, *, context: str) -> None:
    """Close one full-width Windows HANDLE and fail if the kernel rejects it."""

    close_handle = _windows_kernel32().CloseHandle
    close_handle.argtypes = (ctypes.c_void_p,)
    close_handle.restype = ctypes.c_int
    if not close_handle(ctypes.c_void_p(handle)):
        raise OSError(f"{context}: CloseHandle failed")


def _resume_suspended_windows_process(pid: int) -> None:
    """Resume every initial thread after the suspended process joins its kill job."""

    kernel32 = _windows_kernel32()
    create_snapshot = kernel32.CreateToolhelp32Snapshot
    create_snapshot.argtypes = (ctypes.c_uint32, ctypes.c_uint32)
    create_snapshot.restype = ctypes.c_void_p
    snapshot = create_snapshot(0x00000004, 0)  # TH32CS_SNAPTHREAD
    invalid_handle = ctypes.c_void_p(-1).value
    if not snapshot or snapshot == invalid_handle:
        raise OSError("CreateToolhelp32Snapshot(threads) failed")
    entry = _ThreadEntry32()
    entry.dwSize = ctypes.sizeof(entry)
    first = kernel32.Thread32First
    first.argtypes = (ctypes.c_void_p, ctypes.POINTER(_ThreadEntry32))
    first.restype = ctypes.c_int
    next_entry = kernel32.Thread32Next
    next_entry.argtypes = (ctypes.c_void_p, ctypes.POINTER(_ThreadEntry32))
    next_entry.restype = ctypes.c_int
    thread_ids: list[int] = []
    try:
        more = bool(first(snapshot, ctypes.byref(entry)))
        while more:
            if int(entry.th32OwnerProcessID) == pid:
                thread_ids.append(int(entry.th32ThreadID))
            more = bool(next_entry(snapshot, ctypes.byref(entry)))
    finally:
        _close_windows_handle(int(snapshot), context="thread snapshot")
    if not thread_ids:
        raise OSError("suspended Windows process has no enumerable initial thread")
    open_thread = kernel32.OpenThread
    open_thread.argtypes = (ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32)
    open_thread.restype = ctypes.c_void_p
    resume_thread = kernel32.ResumeThread
    resume_thread.argtypes = (ctypes.c_void_p,)
    resume_thread.restype = ctypes.c_uint32
    for thread_id in thread_ids:
        thread = open_thread(0x0002, False, thread_id)  # THREAD_SUSPEND_RESUME
        if not thread:
            raise OSError("OpenThread(THREAD_SUSPEND_RESUME) failed")
        try:
            if resume_thread(thread) == 0xFFFFFFFF:
                raise OSError("ResumeThread failed")
        finally:
            _close_windows_handle(int(thread), context="suspended process thread")


@dataclass(slots=True)
class _WindowsKillJob:
    """A fail-closed Windows job whose close/termination covers descendants."""

    handle: int
    closed: bool = False
    accounting_error: str | None = None
    close_error: str | None = None

    @classmethod
    def create(cls) -> _WindowsKillJob:
        windll = getattr(ctypes, "windll", None)
        if windll is None:
            raise OSError("Windows job objects are unavailable through ctypes")
        kernel32 = windll.kernel32
        create_job = kernel32.CreateJobObjectW
        create_job.argtypes = (ctypes.c_void_p, ctypes.c_wchar_p)
        create_job.restype = ctypes.c_void_p
        handle = create_job(None, None)
        if not handle:
            raise OSError("CreateJobObjectW failed")
        information = _JobObjectExtendedLimitInformation()
        information.BasicLimitInformation.LimitFlags = 0x00002000  # KILL_ON_JOB_CLOSE
        set_information = kernel32.SetInformationJobObject
        set_information.argtypes = (
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.c_void_p,
            ctypes.c_uint32,
        )
        set_information.restype = ctypes.c_int
        if not set_information(
            handle,
            9,  # JobObjectExtendedLimitInformation
            ctypes.byref(information),
            ctypes.sizeof(information),
        ):
            try:
                _close_windows_handle(int(handle), context="unconfigured Windows job")
            except OSError as close_error:
                raise OSError(
                    f"SetInformationJobObject(KILL_ON_JOB_CLOSE) failed; {close_error}"
                ) from close_error
            raise OSError("SetInformationJobObject(KILL_ON_JOB_CLOSE) failed")
        return cls(int(handle))

    def assign(self, process: subprocess.Popen[bytes]) -> None:
        process_handle = getattr(process, "_handle", None)
        if not isinstance(process_handle, int):
            raise OSError("spawned Windows process has no assignable native handle")
        assign = _windows_kernel32().AssignProcessToJobObject
        assign.argtypes = (ctypes.c_void_p, ctypes.c_void_p)
        assign.restype = ctypes.c_int
        if not assign(self.handle, process_handle):
            raise OSError("AssignProcessToJobObject failed")

    def process_ids(self) -> tuple[int, ...]:
        capacity = 16_384
        pointer_size = ctypes.sizeof(ctypes.c_size_t)
        buffer = ctypes.create_string_buffer(8 + capacity * pointer_size)
        returned = ctypes.c_uint32()
        query = _windows_kernel32().QueryInformationJobObject
        query.argtypes = (
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.POINTER(ctypes.c_uint32),
        )
        query.restype = ctypes.c_int
        if not query(
            self.handle,
            3,  # JobObjectBasicProcessIdList
            buffer,
            len(buffer),
            ctypes.byref(returned),
        ):
            self.accounting_error = "QueryInformationJobObject process-list accounting failed"
            return ()
        assigned = ctypes.c_uint32.from_buffer(buffer, 0).value
        count = ctypes.c_uint32.from_buffer(buffer, 4).value
        if assigned > capacity or count > capacity:
            self.accounting_error = "Windows job process-list accounting exceeded capacity"
            return ()
        identifiers = (ctypes.c_size_t * count).from_buffer(buffer, 8)
        return tuple(sorted({int(identifier) for identifier in identifiers if identifier}))

    def terminate(self) -> bool:
        terminate = _windows_kernel32().TerminateJobObject
        terminate.argtypes = (ctypes.c_void_p, ctypes.c_uint32)
        terminate.restype = ctypes.c_int
        return bool(terminate(self.handle, 1))

    def close(self) -> bool:
        if self.closed:
            return True
        try:
            _close_windows_handle(self.handle, context="Windows kill job")
        except OSError as error:
            self.close_error = str(error)
            return False
        self.closed = True
        self.close_error = None
        return True


def _linux_process_group_ids(process_group: int) -> tuple[int, ...]:
    identifiers: list[int] = []
    try:
        candidates = tuple(Path("/proc").iterdir())
    except OSError:
        return ()
    for candidate in candidates:
        if not candidate.name.isdigit():
            continue
        try:
            raw = (candidate / "stat").read_text(encoding="ascii")
            _prefix, separator, suffix = raw.rpartition(")")
            fields = suffix.strip().split() if separator else ()
            if len(fields) >= 3 and int(fields[2]) == process_group:
                identifiers.append(int(candidate.name))
        except (OSError, UnicodeDecodeError, ValueError):
            continue
    return tuple(sorted(set(identifiers)))


def _sample_process_rss(pid: int) -> tuple[int | None, str]:
    """Sample one process's current resident set using standard-library surfaces."""

    current_platform = platform.system().lower()
    if current_platform == "windows":
        windll = getattr(ctypes, "windll", None)
        if windll is None:
            return None, "windows-ctypes-unavailable"
        process_query_information = 0x0400
        process_vm_read = 0x0010
        open_process = windll.kernel32.OpenProcess
        open_process.argtypes = (ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32)
        open_process.restype = ctypes.c_void_p
        get_process_memory_info = windll.psapi.GetProcessMemoryInfo
        get_process_memory_info.argtypes = (
            ctypes.c_void_p,
            ctypes.POINTER(_ProcessMemoryCounters),
            ctypes.c_uint32,
        )
        get_process_memory_info.restype = ctypes.c_int
        handle = open_process(
            process_query_information | process_vm_read,
            False,
            pid,
        )
        if not handle:
            return None, "windows-process-unavailable"
        counters = _ProcessMemoryCounters()
        counters.cb = ctypes.sizeof(counters)
        try:
            success = get_process_memory_info(
                handle,
                ctypes.byref(counters),
                counters.cb,
            )
            if not success:
                return None, "windows-get-process-memory-info-failed"
            return int(counters.WorkingSetSize), "windows-working-set"
        finally:
            _close_windows_handle(int(handle), context="RSS process query")
    if current_platform == "linux":
        try:
            fields: dict[str, int] = {}
            for line in Path(f"/proc/{pid}/status").read_text(encoding="ascii").splitlines():
                name, separator, value = line.partition(":")
                if separator and name == "VmRSS":
                    fields[name] = int(value.strip().split()[0]) * 1024
            if "VmRSS" in fields:
                return fields["VmRSS"], "linux-proc-vmrss"
        except (OSError, UnicodeDecodeError, ValueError):
            pass
        return None, "linux-proc-unavailable"
    return None, "unsupported-platform"


@dataclass(slots=True)
class _ProcessTreeSupervisor:
    """Supervise one isolated process tree for aggregate RSS and bounded teardown."""

    process: subprocess.Popen[bytes]
    supervision_source: str
    windows_job: _WindowsKillJob | None = None
    termination_attempted: bool = False
    termination_succeeded: bool | None = None
    close_succeeded: bool | None = None
    max_observed_process_count: int = 0

    @classmethod
    def start(
        cls,
        argv: Sequence[str],
        *,
        cwd: Path,
        env: Mapping[str, str],
    ) -> _ProcessTreeSupervisor:
        current_platform = platform.system().lower()
        if current_platform == "windows":
            job = _WindowsKillJob.create()
            try:
                process = subprocess.Popen(
                    list(argv),
                    cwd=cwd,
                    env=dict(env),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    creationflags=(
                        getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
                        | 0x00000004  # CREATE_SUSPENDED
                    ),
                )
                try:
                    job.assign(process)
                    _resume_suspended_windows_process(process.pid)
                except OSError as start_error:
                    job.terminate()
                    direct_termination_error: str | None = None
                    try:
                        process.kill()
                        process.wait(timeout=5.0)
                    except (OSError, subprocess.TimeoutExpired) as cleanup_error:
                        direct_termination_error = (
                            f"{type(cleanup_error).__name__}: {cleanup_error}"
                        )
                    finally:
                        for stream in (process.stdout, process.stderr):
                            if stream is not None:
                                stream.close()
                    detail = "suspended child terminated through the Popen handle"
                    if direct_termination_error is not None:
                        detail = (
                            "suspended child Popen termination could not be verified: "
                            f"{direct_termination_error}"
                        )
                    raise OSError(f"{start_error}; {detail}") from start_error
            except BaseException as start_error:
                if not job.close():
                    raise OSError(
                        f"{start_error}; {job.close_error or 'Windows job handle close failed'}"
                    ) from start_error
                raise
            return cls(process, "windows-job-object-kill-on-close", windows_job=job)
        process = subprocess.Popen(
            list(argv),
            cwd=cwd,
            env=dict(env),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
        return cls(process, "posix-new-session-process-group")

    def process_ids(self) -> tuple[int, ...]:
        if self.windows_job is not None:
            return self.windows_job.process_ids()
        if platform.system().lower() == "linux":
            return _linux_process_group_ids(self.process.pid)
        return (self.process.pid,) if self.process.poll() is None else ()

    def sample_tree_rss(self) -> tuple[int | None, str]:
        identifiers = self.process_ids()
        self.max_observed_process_count = max(self.max_observed_process_count, len(identifiers))
        samples = tuple(_sample_process_rss(pid) for pid in identifiers)
        resident = tuple(value for value, _source in samples if value is not None)
        if not resident:
            source = samples[0][1] if samples else "process-tree-unavailable"
            return None, source
        if self.windows_job is not None:
            return sum(resident), "windows-job-process-list-working-set-sum"
        if platform.system().lower() == "linux":
            return sum(resident), "linux-proc-process-group-vmrss-sum"
        return sum(resident), "direct-process-current-rss-fallback"

    def terminate_tree(self) -> tuple[bool, tuple[int, ...]]:
        self.termination_attempted = True
        if self.windows_job is not None:
            attempted = self.windows_job.terminate()
        else:
            try:
                kill_process_group = getattr(os, "killpg", None)
                kill_signal = getattr(signal, "SIGKILL", signal.SIGTERM)
                if not callable(kill_process_group):
                    raise OSError("POSIX process-group termination is unavailable")
                kill_process_group(self.process.pid, kill_signal)
                attempted = True
            except ProcessLookupError:
                attempted = True
            except OSError:
                attempted = False
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.kill()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass
        deadline = time.monotonic() + 5.0
        remaining = self.process_ids()
        accounting_failed = (
            self.windows_job is not None and self.windows_job.accounting_error is not None
        )
        while remaining and not accounting_failed and time.monotonic() < deadline:
            time.sleep(0.01)
            remaining = self.process_ids()
            accounting_failed = (
                self.windows_job is not None and self.windows_job.accounting_error is not None
            )
        self.termination_succeeded = attempted and not remaining and not accounting_failed
        return self.termination_succeeded, remaining

    def close(self) -> bool:
        if self.windows_job is not None:
            self.close_succeeded = self.windows_job.close()
            return self.close_succeeded
        self.close_succeeded = True
        return True


def _bounded_communicate_after_termination(
    process: subprocess.Popen[bytes], *, timeout_seconds: float = 1.0
) -> tuple[bytes, bytes, bool]:
    """Drain a terminated process without trusting escaped pipe owners to exit."""

    try:
        stdout, stderr = process.communicate(timeout=timeout_seconds)
        return stdout, stderr, True
    except subprocess.TimeoutExpired as error:
        stdout = error.stdout if isinstance(error.stdout, bytes) else b""
        stderr = error.stderr if isinstance(error.stderr, bytes) else b""
        for stream in (process.stdout, process.stderr):
            if stream is not None:
                stream.close()
        return stdout, stderr, False


def run_command(
    spec: CommandSpec,
    *,
    repository: Path,
    output_root: Path,
    transient_root: Path,
    prior: Mapping[str, CheckResult],
) -> CheckResult:
    """Run one command without a shell and seal both byte streams."""

    failed_dependencies = [
        dependency
        for dependency in spec.dependencies
        if dependency not in prior or prior[dependency].status != "PASS"
    ]
    if failed_dependencies:
        return _blocked_result(
            spec,
            f"dependency checks did not pass: {', '.join(failed_dependencies)}",
            status=spec.failure_status,
        )

    environment, removed_sensitive_variables = _sanitized_environment(transient_root, spec.check_id)
    log_root = output_root / "logs"
    stdout_path = log_root / f"{spec.check_id}.stdout.log"
    stderr_path = log_root / f"{spec.check_id}.stderr.log"
    started_at = _utc_now()
    started = time.perf_counter()
    return_code: int | None = None
    stdout = b""
    stderr = b""
    peak_rss_bytes: int | None = None
    rss_measurement_source = "process-not-started"
    supervisor: _ProcessTreeSupervisor | None = None
    process_tree_remaining_pids: tuple[int, ...] = ()
    process_tree_pipe_drain_succeeded: bool | None = None
    timeout_triggered = False
    status = spec.failure_status
    reason: str | None = None
    try:
        supervisor = _ProcessTreeSupervisor.start(
            spec.argv,
            cwd=repository,
            env=environment,
        )
        process = supervisor.process
        deadline = time.monotonic() + spec.timeout_seconds
        while True:
            if spec.measure_peak_rss:
                sampled_rss, sampled_source = supervisor.sample_tree_rss()
                if sampled_rss is not None:
                    peak_rss_bytes = max(peak_rss_bytes or 0, sampled_rss)
                    rss_measurement_source = sampled_source
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                timeout_triggered = True
                _terminated, process_tree_remaining_pids = supervisor.terminate_tree()
                stdout, stderr, process_tree_pipe_drain_succeeded = (
                    _bounded_communicate_after_termination(process)
                )
                return_code = process.returncode
                status = "FAILED_INFRASTRUCTURE"
                reason = f"command exceeded {spec.timeout_seconds} seconds"
                break
            try:
                stdout, stderr = process.communicate(timeout=min(0.05, remaining))
            except subprocess.TimeoutExpired:
                continue
            process_tree_pipe_drain_succeeded = True
            return_code = process.returncode
            if return_code == 0:
                status = "PASS"
            else:
                reason = f"command returned exit code {return_code}"
            _terminated, process_tree_remaining_pids = supervisor.terminate_tree()
            break
    except subprocess.TimeoutExpired as error:
        timeout_triggered = True
        status = "FAILED_INFRASTRUCTURE"
        reason = f"command exceeded {spec.timeout_seconds} seconds"
        stdout = error.stdout or b""
        stderr = error.stderr or b""
        process_tree_pipe_drain_succeeded = False
    except OSError as error:
        status = "FAILED_INFRASTRUCTURE"
        reason = f"command could not start: {type(error).__name__}: {error}"
        stderr = reason.encode("utf-8", errors="replace")
    finally:
        if supervisor is not None:
            if supervisor.termination_attempted is False:
                _terminated, process_tree_remaining_pids = supervisor.terminate_tree()
            supervisor.close()
    if (
        spec.measure_peak_rss
        and status == "PASS"
        and (
            peak_rss_bytes is None
            or (
                supervisor is not None
                and supervisor.windows_job is not None
                and supervisor.windows_job.accounting_error is not None
            )
        )
    ):
        status = "FAILED_INFRASTRUCTURE"
        reason = (
            supervisor.windows_job.accounting_error
            if supervisor is not None
            and supervisor.windows_job is not None
            and supervisor.windows_job.accounting_error is not None
            else "aggregate process-tree RSS accounting was unavailable"
        )
    if (
        spec.required
        and supervisor is not None
        and (
            supervisor.termination_succeeded is not True
            or bool(process_tree_remaining_pids)
            or process_tree_pipe_drain_succeeded is not True
            or (supervisor.windows_job is not None and supervisor.close_succeeded is not True)
        )
    ):
        status = "FAILED_INFRASTRUCTURE"
        cleanup_reason = "required command process-tree cleanup did not complete"
        reason = cleanup_reason if reason is None else f"{reason}; {cleanup_reason}"
    completed_at = _utc_now()
    duration = time.perf_counter() - started
    stdout, stdout_redactions = _redact_generated_log(stdout)
    stderr, stderr_redactions = _redact_generated_log(stderr)
    write_bytes_atomic(stdout_path, stdout)
    write_bytes_atomic(stderr_path, stderr)
    details: dict[str, object] = {
        "command": _display_command(spec.argv),
        "environment_policy": "strict allowlist plus isolated writable homes and caches",
        "generated_log_redactions": stdout_redactions + stderr_redactions,
        "nondeterminism": list(spec.nondeterminism),
        "non_allowlisted_environment_variables_removed": removed_sensitive_variables,
        "process_tree_cleanup_attempted": (
            supervisor.termination_attempted if supervisor is not None else False
        ),
        "process_tree_cleanup_succeeded": (
            supervisor.termination_succeeded if supervisor is not None else False
        ),
        "process_tree_remaining_pid_count": len(process_tree_remaining_pids),
        "process_tree_pipe_drain_succeeded": process_tree_pipe_drain_succeeded,
        "process_tree_supervision_source": (
            supervisor.supervision_source if supervisor is not None else "process-not-started"
        ),
        "process_tree_windows_job_handle_closed": (
            supervisor.windows_job.closed
            if supervisor is not None and supervisor.windows_job is not None
            else None
        ),
        "process_tree_windows_job_handle_close_succeeded": (
            supervisor.close_succeeded
            if supervisor is not None and supervisor.windows_job is not None
            else None
        ),
        "process_tree_windows_job_close_kill_is_fallback_not_verification": (
            supervisor is not None and supervisor.windows_job is not None
        ),
        "process_tree_windows_launch_suspended_before_assignment": (
            supervisor is not None and supervisor.windows_job is not None
        ),
        "process_tree_supervision_scope": (
            "Windows kill-on-close job covers assigned descendants"
            if supervisor is not None and supervisor.windows_job is not None
            else (
                "POSIX inherited process group; deliberate setsid/double-fork escape is not "
                "contained"
                if supervisor is not None
                else "process-not-started"
            )
        ),
        "timeout_triggered": timeout_triggered,
    }
    if spec.measure_peak_rss:
        details.update(
            {
                "peak_rss_bytes": peak_rss_bytes,
                "rss_measurement_scope": (
                    "sampled aggregate resident bytes across the supervised process tree; "
                    "this is measurement, not a hard memory limit"
                ),
                "rss_measurement_source": rss_measurement_source,
                "rss_sampling_limitations": (
                    "sampled current resident bytes can miss descendants that start and exit "
                    "between samples"
                ),
                "rss_sampling_max_observed_process_count": (
                    supervisor.max_observed_process_count if supervisor is not None else 0
                ),
            }
        )
    return CheckResult(
        check_id=spec.check_id,
        category=spec.category,
        kind="command",
        required=spec.required,
        status=status,
        started_at=started_at,
        completed_at=completed_at,
        duration_seconds=duration,
        argv=spec.argv,
        exit_code=return_code,
        stdout_log=_path_for_receipt(stdout_path, output_root),
        stdout_sha256=sha256_bytes(stdout),
        stderr_log=_path_for_receipt(stderr_path, output_root),
        stderr_sha256=sha256_bytes(stderr),
        reason=reason,
        details=details,
    )


def internal_result(
    check_id: str,
    category: str,
    *,
    status: str,
    reason: str | None = None,
    details: Mapping[str, object] | None = None,
    required: bool = True,
) -> CheckResult:
    """Create a typed result for a deterministic in-process comparison."""

    if not _SAFE_CHECK_ID.fullmatch(check_id):
        raise ValueError(f"invalid check id: {check_id!r}")
    moment = _utc_now()
    return CheckResult(
        check_id=check_id,
        category=category,
        kind="internal",
        required=required,
        status=status,
        started_at=moment,
        completed_at=moment,
        duration_seconds=0.0,
        argv=(),
        exit_code=None,
        stdout_log=None,
        stdout_sha256=None,
        stderr_log=None,
        stderr_sha256=None,
        reason=reason,
        details=details or {},
    )


def _git_environment() -> dict[str, str]:
    environment = {
        key: value for key, value in os.environ.items() if not key.upper().startswith("GIT_")
    }
    environment["GIT_NO_REPLACE_OBJECTS"] = "1"
    return environment


def _git_result(repository: Path, *arguments: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        (
            "git",
            "--no-replace-objects",
            "-C",
            str(repository.resolve()),
            *arguments,
        ),
        check=False,
        capture_output=True,
        env=_git_environment(),
        timeout=30,
    )


def _git(repository: Path, *arguments: str) -> str:
    completed = _git_result(repository, *arguments)
    if completed.returncode != 0:
        stderr = completed.stderr.decode("utf-8", errors="replace").strip()
        raise ValueError(
            f"git {' '.join(arguments)} failed with exit {completed.returncode}: {stderr}"
        )
    return completed.stdout.decode("utf-8", errors="strict").strip()


def _git_bytes(repository: Path, *arguments: str) -> bytes:
    completed = _git_result(repository, *arguments)
    if completed.returncode != 0:
        stderr = completed.stderr.decode("utf-8", errors="replace").strip()
        raise ValueError(
            f"git {' '.join(arguments)} failed with exit {completed.returncode}: {stderr}"
        )
    return completed.stdout


def repository_identity(repository: Path, expected_commit: str) -> dict[str, object]:
    """Require the literal clean candidate commit before running any checks."""

    if not _COMMIT.fullmatch(expected_commit):
        raise ValueError("--expected-commit must be a lowercase full 40-character SHA")
    repository = repository.resolve()
    top_level = Path(_git(repository, "rev-parse", "--show-toplevel")).resolve()
    if top_level != repository:
        raise ValueError(f"--root is not the Git top level: {repository} != {top_level}")
    actual_commit = _git(repository, "rev-parse", "HEAD")
    if actual_commit != expected_commit:
        raise ValueError(
            f"candidate commit mismatch: expected {expected_commit}, found {actual_commit}"
        )
    status = _git(repository, "status", "--porcelain=v1", "--untracked-files=normal")
    if status:
        raise ValueError(
            "candidate worktree is not clean; status bytes "
            f"{sha256_bytes(status.encode('utf-8'))} contain {len(status.splitlines())} entries"
        )
    index_projection = _git_bytes(repository, "ls-files", "-v", "-z")
    index_records = tuple(record for record in index_projection.split(b"\0") if record)
    if any(len(record) < 3 or record[1:2] != b" " for record in index_records):
        raise ValueError("Git returned malformed tracked-index tag evidence")
    nonstandard_index_paths = []
    index_paths: list[bytes] = []
    for record in index_records:
        index_paths.append(record[2:])
        if record[:1] == b"H":
            continue
        try:
            relative = record[2:].decode("utf-8", errors="strict")
            tag = record[:1].decode("ascii", errors="strict")
        except UnicodeDecodeError as error:
            raise ValueError("Git index contains a non-portable path or tag") from error
        nonstandard_index_paths.append(f"{tag}:{relative}")
    if nonstandard_index_paths:
        raise ValueError(
            "candidate index has non-H entries that can conceal worktree bytes: "
            + ", ".join(nonstandard_index_paths[:10])
        )
    tree_projection = _git_bytes(repository, "ls-tree", "-r", "-z", expected_commit)
    tree_entries: dict[bytes, tuple[bytes, bytes]] = {}
    for record in (record for record in tree_projection.split(b"\0") if record):
        metadata, separator, raw_path = record.partition(b"\t")
        fields = metadata.split(b" ")
        if separator != b"\t" or len(fields) != 3:
            raise ValueError("Git returned malformed expected-tree stage evidence")
        mode, object_type, object_id = fields
        if object_type != b"blob" or raw_path in tree_entries:
            raise ValueError("expected Git tree has a non-blob or duplicate path")
        tree_entries[raw_path] = (mode, object_id)
    stage_projection = _git_bytes(repository, "ls-files", "--stage", "-z")
    stage_entries: dict[bytes, tuple[bytes, bytes]] = {}
    for record in (record for record in stage_projection.split(b"\0") if record):
        metadata, separator, raw_path = record.partition(b"\t")
        fields = metadata.split(b" ")
        if separator != b"\t" or len(fields) != 3:
            raise ValueError("Git returned malformed index-stage evidence")
        mode, object_id, stage = fields
        if stage != b"0" or raw_path in stage_entries:
            raise ValueError("candidate index contains a non-stage-0 or duplicate path")
        stage_entries[raw_path] = (mode, object_id)
    if len(index_paths) != len(set(index_paths)) or set(index_paths) != set(tree_entries):
        raise ValueError("candidate index membership differs from the expected Git tree")
    if stage_entries != tree_entries:
        raise ValueError("candidate index stage projection differs from the expected Git tree")
    return {
        "clean": True,
        "git_commit": actual_commit,
        "git_index_entry_count": len(index_records),
        "git_index_stage_sha256": sha256_bytes(stage_projection),
        "git_index_tags_sha256": sha256_bytes(index_projection),
        "git_status_sha256": sha256_bytes(status.encode("utf-8")),
        "git_tree_projection_sha256": sha256_bytes(tree_projection),
        "repository": "Grativy6/ARC3",
    }


def source_lock_identity(repository: Path, expected_commit: str) -> dict[str, object]:
    """Bind package-relevant source trees and lock/notices bytes to the candidate commit."""

    repository = repository.resolve()
    if _git(repository, "rev-parse", "HEAD") != expected_commit:
        raise ValueError("source/lock identity is not running at the expected commit")
    subtrees: dict[str, str] = {}
    for relative in ("agent", "scripts", "src"):
        subtrees[relative] = _git(repository, "rev-parse", f"{expected_commit}:{relative}")
    files: dict[str, str] = {}
    for relative in (
        "LICENSE",
        "THIRD_PARTY_NOTICES.md",
        "pyproject.toml",
        "upstream.lock.json",
        "uv.lock",
    ):
        blob = _git_bytes(repository, "show", f"{expected_commit}:{relative}")
        live = read_bounded_regular_snapshot(
            root=repository,
            path=repository / relative,
            max_bytes=DEFAULT_MAX_CANDIDATE_BYTES,
            path_label=relative,
        )
        if live != blob:
            raise ValueError(f"live source/lock bytes differ from expected Git blob: {relative}")
        files[relative] = sha256_bytes(blob)
    identity: dict[str, object] = {
        "files": files,
        "git_commit": expected_commit,
        "git_tree": _git(repository, "rev-parse", f"{expected_commit}^{{tree}}"),
        "subtree_git_objects": subtrees,
    }
    identity["identity_sha256"] = sha256_bytes(canonical_json_bytes(identity))
    return identity


def prepare_fresh_output_root(repository: Path, output_root: Path) -> None:
    """Create a new ignored/out-of-tree evidence root and refuse every reused path."""

    repository = repository.resolve()
    output_root = output_root.resolve()
    if output_root == repository:
        raise ValueError("--output-root cannot be the repository root")
    if output_root.exists():
        raise ValueError(f"--output-root must not already exist: {output_root}")
    if repository in output_root.parents:
        relative = output_root.relative_to(repository).as_posix()
        ignored = _git_result(repository, "check-ignore", "--quiet", "--", relative)
        if ignored.returncode != 0:
            raise ValueError("an in-repository --output-root must be covered by .gitignore")
    output_root.mkdir(parents=True, exist_ok=False)


def prepare_fresh_transient_root(repository: Path, output_root: Path, transient_root: Path) -> None:
    """Create fresh unsealed state outside both the clone and evidence tree."""

    repository = repository.resolve()
    output_root = output_root.resolve()
    transient_root = transient_root.resolve()
    if transient_root.exists():
        raise ValueError(f"--transient-root must not already exist: {transient_root}")
    if (
        transient_root == repository
        or repository in transient_root.parents
        or transient_root in repository.parents
    ):
        raise ValueError("--transient-root must be strictly outside the repository")
    if (
        transient_root == output_root
        or output_root in transient_root.parents
        or transient_root in output_root.parents
    ):
        raise ValueError("--transient-root must not overlap --output-root")
    transient_root.mkdir(parents=True, exist_ok=False)


_INTERPRETER_ORIGIN_PROBE_PROGRAM = (
    "import json,sys\n"
    "from pathlib import Path\n"
    "source_root=Path(sys.argv[1])\n"
    "if not source_root.is_absolute():\n"
    "    raise RuntimeError('candidate source root must be absolute')\n"
    "source_root=source_root.resolve(strict=True)\n"
    "def deny_network(event,args):\n"
    "    if event.startswith('socket.'):\n"
    "        raise PermissionError('network disabled during interpreter origin probe')\n"
    "sys.addaudithook(deny_network)\n"
    "sys.path.insert(0,str(source_root))\n"
    "import arc3\n"
    "print(json.dumps({'executable':sys.executable,'prefix':sys.prefix,"
    "'source_root':str(source_root),'arc3_origin':arc3.__file__},sort_keys=True))\n"
)


def _interpreter_origin_probe_argv(executable: Path, source_root: Path) -> tuple[str, ...]:
    return (
        str(executable),
        "-I",
        "-c",
        _INTERPRETER_ORIGIN_PROBE_PROGRAM,
        str(source_root),
    )


def _lexical_absolute_path(path: str | Path) -> Path:
    """Make a path absolute without resolving a virtual-environment launcher symlink."""

    return Path(os.path.abspath(path))


def _interpreter_origin_mismatches(
    *,
    expected: Mapping[str, Path],
    observed: Mapping[str, Path],
) -> tuple[str, ...]:
    """Return path-free component names for safe CI mismatch diagnostics."""

    return tuple(
        name
        for name in ("executable_target", "prefix", "source_root", "arc3_origin")
        if observed.get(name) != expected.get(name)
    )


def interpreter_source_identity(repository: Path, transient_root: Path) -> dict[str, object]:
    """Prove the verifier and its isolated subprocess import ARC3 from this clone."""

    repository = repository.resolve()
    expected_prefix = (repository / ".venv").resolve()
    executable = _lexical_absolute_path(sys.executable)
    executable_target = executable.resolve(strict=True)
    prefix = Path(sys.prefix).resolve()
    if prefix != expected_prefix:
        raise ValueError("release verifier clone-local component mismatch: prefix")
    try:
        executable.relative_to(expected_prefix)
    except ValueError as error:
        raise ValueError(
            "release verifier executable is not under the clone-local .venv"
        ) from error
    expected_origin = (repository / "src" / "arc3" / "__init__.py").resolve()
    spec = importlib.util.find_spec("arc3")
    if spec is None or spec.origin is None:
        raise ValueError("arc3 is not importable from the release interpreter")
    in_process_origin = Path(spec.origin).resolve()
    if in_process_origin != expected_origin:
        raise ValueError(f"arc3 import origin is outside the candidate source: {in_process_origin}")
    environment, removed = _sanitized_environment(transient_root, "interpreter-origin")
    source_root = (repository / "src").resolve()
    probe = subprocess.run(
        _interpreter_origin_probe_argv(executable, source_root),
        cwd=repository,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if probe.returncode != 0:
        _stderr, _ = _redact_generated_log(probe.stderr.encode("utf-8", errors="replace"))
        raise ValueError(
            "isolated interpreter origin probe failed: "
            + _stderr.decode("utf-8", errors="replace").strip()
        )
    try:
        payload = _required_mapping(json.loads(probe.stdout), name="interpreter origin probe")
    except json.JSONDecodeError as error:
        raise ValueError(f"interpreter origin probe did not return JSON: {error}") from error
    probed_executable = _lexical_absolute_path(str(payload.get("executable")))
    try:
        probed_executable.relative_to(expected_prefix)
    except ValueError as error:
        raise ValueError(
            "isolated interpreter executable is not under the clone-local .venv"
        ) from error
    probed_executable_target = probed_executable.resolve(strict=True)
    probed_prefix = Path(str(payload.get("prefix"))).resolve()
    probed_source_root = Path(str(payload.get("source_root"))).resolve()
    probed_origin = Path(str(payload.get("arc3_origin"))).resolve()
    mismatches = _interpreter_origin_mismatches(
        expected={
            "executable_target": executable_target,
            "prefix": expected_prefix,
            "source_root": source_root,
            "arc3_origin": expected_origin,
        },
        observed={
            "executable_target": probed_executable_target,
            "prefix": probed_prefix,
            "source_root": probed_source_root,
            "arc3_origin": probed_origin,
        },
    )
    if mismatches:
        raise ValueError(
            "isolated interpreter origin disagrees with the candidate runtime components: "
            + ", ".join(mismatches)
        )
    return {
        "arc3_origin": expected_origin.relative_to(repository).as_posix(),
        "arc3_origin_sha256": sha256_file(expected_origin),
        "clone_local_virtual_environment": True,
        "isolated_probe": True,
        "isolated_probe_source_root": source_root.relative_to(repository).as_posix(),
        "network_denied_during_probe": True,
        "non_allowlisted_environment_variables_removed": removed,
        "python_executable": _path_for_receipt(executable, repository),
        "python_executable_sha256": sha256_file(executable_target),
        "python_executable_venv_launcher_preserved": True,
        "python_prefix": _path_for_receipt(expected_prefix, repository),
    }


def _probe_command(argv: Sequence[str], *, environment: Mapping[str, str] | None = None) -> bool:
    try:
        completed = subprocess.run(
            list(argv),
            check=False,
            capture_output=True,
            env=None if environment is None else dict(environment),
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return completed.returncode == 0


def _python_command_candidates() -> tuple[tuple[str, ...], ...]:
    """Return installed interpreter commands that may own a uv entry point."""

    candidates: list[tuple[str, ...]] = [(sys.executable,)]
    python_launcher = shutil.which("py")
    if python_launcher:
        candidates.extend(
            (
                (python_launcher, "-3.13"),
                (python_launcher, "-3.12"),
                (python_launcher, "-3"),
            )
        )
    for name in ("python3", "python"):
        candidate = shutil.which(name)
        if candidate:
            candidates.append((candidate,))
    return tuple(dict.fromkeys(candidates))


def _installed_uv_entrypoints(python_command: Sequence[str]) -> tuple[tuple[str, ...], ...]:
    """Locate pip-created uv executables without importing uv in the release child."""

    discovery = (
        "import json,os,sysconfig;"
        "from pathlib import Path;"
        "name='uv.exe' if os.name=='nt' else 'uv';"
        "user_scheme=sysconfig.get_preferred_scheme('user');"
        "paths=(Path(sysconfig.get_path('scripts'))/name,"
        "Path(sysconfig.get_path('scripts',scheme=user_scheme))/name);"
        "print(json.dumps([str(path.resolve()) for path in paths if path.is_file()]))"
    )
    try:
        completed = subprocess.run(
            (*python_command, "-c", discovery),
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ()
    if completed.returncode != 0:
        return ()
    try:
        loaded: object = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return ()
    if not isinstance(loaded, list) or not all(isinstance(item, str) for item in loaded):
        return ()
    return tuple((item,) for item in cast(list[str], loaded))


def discover_uv_command(
    *, uv_executable: Path | None = None, uv_python: Path | None = None
) -> tuple[str, ...]:
    """Find an installed uv command that survives the release environment policy."""

    if uv_executable is not None and uv_python is not None:
        raise ValueError("--uv-executable and --uv-python are mutually exclusive")
    candidates: list[tuple[str, ...]] = []
    if uv_executable is not None:
        candidates.append((str(uv_executable.resolve()),))
    elif uv_python is not None:
        candidates.append((str(uv_python.resolve()), "-m", "uv"))
    else:
        executable = shutil.which("uv")
        if executable:
            candidates.append((executable,))
        python_commands = _python_command_candidates()
        for python_command in python_commands:
            candidates.extend(_installed_uv_entrypoints(python_command))
        candidates.extend((*python_command, "-m", "uv") for python_command in python_commands)

    unique_candidates = tuple(dict.fromkeys(candidates))
    with tempfile.TemporaryDirectory(prefix="arc3-uv-discovery-") as temporary:
        environment, _removed = _sanitized_environment(Path(temporary), "uv-probe")
        command = next(
            (
                candidate
                for candidate in unique_candidates
                if _probe_command((*candidate, "--version"), environment=environment)
            ),
            (),
        )
    if not command:
        if uv_executable is not None or uv_python is not None:
            configured = unique_candidates[0] if unique_candidates else ()
            raise ValueError(
                "configured uv command is not executable under the sanitized release "
                f"environment: {_display_command(configured)}"
            )
        raise ValueError(
            "the pinned uv bootstrap executable is unavailable under the sanitized release "
            "environment; pass --uv-executable"
        )
    return command


def _expectation_configuration(expectation: Mapping[str, Any]) -> dict[str, Any]:
    raw = expectation.get("configuration")
    if not isinstance(raw, dict):
        raise ValueError("benchmark expectation configuration is missing")
    configuration = cast(dict[str, Any], raw)
    agents = configuration.get("agents")
    seeds = configuration.get("seeds")
    if not isinstance(agents, list) or not all(isinstance(item, str) for item in agents):
        raise ValueError("benchmark configuration field 'agents' has the wrong type")
    if not isinstance(seeds, list) or not all(isinstance(item, int) for item in seeds):
        raise ValueError("benchmark configuration field 'seeds' has the wrong type")
    for key in ("max_actions", "max_resets"):
        value = configuration.get(key)
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"benchmark configuration field {key!r} has the wrong type")
    if not isinstance(configuration.get("partition"), str):
        raise ValueError("benchmark configuration field 'partition' has the wrong type")
    timeout = configuration.get("timeout_seconds")
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)):
        raise ValueError("benchmark configuration field 'timeout_seconds' has the wrong type")
    return configuration


def _build_package_only_plan(
    *,
    repository: Path,
    output_root: Path,
    transient_root: Path,
    uv_command: tuple[str, ...],
) -> tuple[CommandSpec, ...]:
    """Declare Build 001 packaging checks with no public-evaluation reachability."""

    python = sys.executable
    package_a = output_root / "package-a"
    package_b = output_root / "package-b"
    lock_dependencies = ("dependency-sync", "dependency-lock")
    test_argv: list[str] = [
        python,
        "-m",
        "scripts.package_only_pytest",
        "--root",
        str(repository),
        "--guard-log",
        str(transient_root / "package-only-test-guard-attempts.jsonl"),
        "--receipt",
        str(output_root / "package-only-test-guard.json"),
        "--allow-root",
        str(transient_root),
        "--allow-root",
        str(output_root),
        "--select-in-process-tests",
        "--build001-boundary-policy",
        "--expected-commit",
        "{CANDIDATE_COMMIT}",
        "--",
        "-q",
        "--basetemp",
        str(transient_root / "tmp" / "pytest-package-safe"),
    ]
    specs = (
        CommandSpec(
            "dependency-sync",
            "dependency-lock",
            (
                *uv_command,
                "sync",
                "--frozen",
                "--all-extras",
                "--dev",
                "--python",
                "3.12.14",
                "--link-mode",
                "copy",
                "--offline",
            ),
            900.0,
            failure_status="FAILED_INFRASTRUCTURE",
        ),
        CommandSpec(
            "dependency-lock",
            "dependency-lock",
            (*uv_command, "lock", "--check", "--offline"),
            120.0,
            dependencies=("dependency-sync",),
            failure_status="FAILED_INFRASTRUCTURE",
        ),
        CommandSpec(
            "ruff-lint",
            "quality",
            (python, "-m", "ruff", "check", "--no-cache", "."),
            300.0,
            dependencies=lock_dependencies,
        ),
        CommandSpec(
            "ruff-format",
            "quality",
            (python, "-m", "ruff", "format", "--check", "--no-cache", "."),
            300.0,
            dependencies=lock_dependencies,
        ),
        CommandSpec(
            "mypy-strict",
            "quality",
            (
                python,
                "-m",
                "mypy",
                "--strict",
                "--cache-dir",
                str(transient_root / "cache" / "mypy" / "package-only"),
                "src",
                "agent",
                "scripts",
            ),
            900.0,
            dependencies=lock_dependencies,
        ),
        CommandSpec(
            "package-safe-test-suite",
            "tests",
            tuple(test_argv),
            3000.0,
            dependencies=lock_dependencies,
            nondeterminism=("test durations and coverage percentages may vary by host",),
        ),
        CommandSpec(
            "doctor",
            "runtime",
            (python, "-m", "arc3", "doctor", "--json"),
            120.0,
            dependencies=lock_dependencies,
        ),
        CommandSpec(
            "offline-package-a",
            "offline-package",
            (
                python,
                "-m",
                "scripts.prepare_kaggle_submission",
                "--output",
                str(package_a),
                "--sandbox-timeout",
                "120",
            ),
            900.0,
            dependencies=lock_dependencies,
            measure_peak_rss=True,
        ),
        CommandSpec(
            "offline-package-b",
            "offline-package",
            (
                python,
                "-m",
                "scripts.prepare_kaggle_submission",
                "--output",
                str(package_b),
                "--sandbox-timeout",
                "120",
            ),
            900.0,
            dependencies=lock_dependencies,
            measure_peak_rss=True,
        ),
        CommandSpec(
            "offline-package-startup",
            "offline-package",
            (
                python,
                "-I",
                str(repository / "scripts" / "package_startup_probe.py"),
                "--package-root",
                str(package_a),
                "--expected-commit",
                "{CANDIDATE_COMMIT}",
            ),
            180.0,
            dependencies=("offline-package-a",),
            measure_peak_rss=True,
        ),
        CommandSpec(
            "package-integrity",
            "integrity",
            (
                python,
                "-m",
                "scripts.check_competition_integrity",
                "--root",
                str(repository),
                "--package-only",
                "--expected-commit",
                "{CANDIDATE_COMMIT}",
                "--archive",
                str(package_a / "arc3-kaggle-candidate.zip"),
                "--output",
                str(output_root / "integrity-receipt.json"),
            ),
            900.0,
            dependencies=(*lock_dependencies, "offline-package-a"),
            nondeterminism=(
                "installed distribution metadata may differ by platform while lock identity stays fixed",
            ),
        ),
    )
    _validate_package_only_plan(
        specs,
        repository=repository,
        output_root=output_root,
    )
    return specs


def _single_option_value(argv: Sequence[str], option: str) -> str:
    positions = tuple(index for index, value in enumerate(argv) if value == option)
    if len(positions) != 1 or positions[0] + 1 >= len(argv):
        raise ValueError(f"package-only integrity plan requires exactly one {option} value")
    return argv[positions[0] + 1]


def _validate_package_only_plan(
    specs: Sequence[CommandSpec],
    *,
    repository: Path | None = None,
    output_root: Path | None = None,
) -> None:
    """Fail closed unless the plan contains the exact static production-policy gate."""

    rendered = canonical_json_bytes([spec.to_dict() for spec in specs]).decode("utf-8").lower()
    normalized = rendered.replace("\\", "/")
    forbidden = [
        fragment for fragment in _PACKAGE_ONLY_FORBIDDEN_PLAN_FRAGMENTS if fragment in normalized
    ]
    if forbidden:
        raise ValueError(
            "package-only plan crossed the semantic public boundary: " + ", ".join(forbidden)
        )
    forbidden_arguments = {"--environments-dir", "--manifest", "--run-state"}
    for spec in specs:
        if forbidden_arguments & set(spec.argv):
            raise ValueError(f"package-only check {spec.check_id} has a forbidden argument")
    for spec in specs:
        executable = Path(spec.argv[0]).name.lower() if spec.argv else ""
        invokes_direct_pytest = executable in {"pytest", "pytest.exe"} or (
            len(spec.argv) >= 3 and spec.argv[1:3] == ("-m", "pytest")
        )
        if invokes_direct_pytest:
            raise ValueError(
                "package-only plan forbids direct pytest commands outside the guarded runner"
            )
    integrity_specs = tuple(spec for spec in specs if spec.check_id == "package-integrity")
    if len(integrity_specs) != 1:
        raise ValueError("package-only plan requires exactly one package-integrity check")
    integrity = integrity_specs[0]
    if integrity.argv[:3] != (
        sys.executable,
        "-m",
        "scripts.check_competition_integrity",
    ):
        raise ValueError(
            "package-only package-integrity check must execute the production static scanner"
        )
    if integrity.argv.count("--package-only") != 1:
        raise ValueError("package-only package-integrity check must select package-only mode once")
    integrity_commit = integrity.argv[7] if len(integrity.argv) > 7 else ""
    if (
        len(integrity.argv) != 12
        or integrity.argv[3] != "--root"
        or integrity.argv[5] != "--package-only"
        or integrity.argv[6] != "--expected-commit"
        or (
            integrity_commit != "{CANDIDATE_COMMIT}" and _COMMIT.fullmatch(integrity_commit) is None
        )
        or integrity.argv[8] != "--archive"
        or integrity.argv[10] != "--output"
    ):
        raise ValueError("package-only package-integrity argv shape is not the frozen static gate")
    if integrity.required is not True or integrity.dependencies != (
        "dependency-sync",
        "dependency-lock",
        "offline-package-a",
    ):
        raise ValueError("package-only package-integrity dependency boundary is incomplete")
    root_value = _single_option_value(integrity.argv, "--root")
    archive_value = _single_option_value(integrity.argv, "--archive")
    output_value = _single_option_value(integrity.argv, "--output")
    if repository is not None and Path(root_value).resolve() != repository.resolve():
        raise ValueError("package-only integrity root is not the exact candidate repository")
    if output_root is not None:
        expected_archive = (output_root / "package-a" / "arc3-kaggle-candidate.zip").resolve()
        expected_output = (output_root / "integrity-receipt.json").resolve()
        if Path(archive_value).resolve() != expected_archive:
            raise ValueError("package-only integrity archive is not package A")
        if Path(output_value).resolve() != expected_output:
            raise ValueError("package-only integrity receipt leaves the sealed output root")
    test_specs = tuple(spec for spec in specs if spec.check_id == "package-safe-test-suite")
    if len(test_specs) != 1:
        raise ValueError("package-only plan requires exactly one guarded test-suite check")
    guarded_tests = test_specs[0]
    if guarded_tests.argv[:3] != (
        sys.executable,
        "-m",
        "scripts.package_only_pytest",
    ):
        raise ValueError("package-only tests must execute the guarded in-process runner")
    if (
        guarded_tests.argv.count("--select-in-process-tests") != 1
        or guarded_tests.argv.count("--build001-boundary-policy") != 1
        or guarded_tests.argv.count("--expected-commit") != 1
        or "--ignore" in guarded_tests.argv
        or any(argument.startswith("--ignore=") for argument in guarded_tests.argv)
        or guarded_tests.required is not True
        or guarded_tests.dependencies != ("dependency-sync", "dependency-lock")
    ):
        raise ValueError("package-only guarded test selection policy is incomplete")
    separator = tuple(index for index, value in enumerate(guarded_tests.argv) if value == "--")
    pytest_tail = guarded_tests.argv[separator[0] + 1 :] if len(separator) == 1 else ()
    if (
        len(separator) != 1
        or len(pytest_tail) != 3
        or pytest_tail[:2] != ("-q", "--basetemp")
        or not pytest_tail[2]
    ):
        raise ValueError("package-only guarded pytest arguments are not the frozen exact shape")
    test_root = _single_option_value(guarded_tests.argv, "--root")
    test_receipt = _single_option_value(guarded_tests.argv, "--receipt")
    test_commit = _single_option_value(guarded_tests.argv, "--expected-commit")
    if test_commit != "{CANDIDATE_COMMIT}" and _COMMIT.fullmatch(test_commit) is None:
        raise ValueError("package-only guarded tests do not bind a literal candidate commit")
    if test_commit != integrity_commit:
        raise ValueError("package-only guarded tests and integrity scan bind different commits")
    if repository is not None:
        if Path(test_root).resolve() != repository.resolve():
            raise ValueError("package-only guarded tests do not target the exact repository")
        build001_test_selection(repository)
    if (
        output_root is not None
        and Path(test_receipt).resolve() != (output_root / "package-only-test-guard.json").resolve()
    ):
        raise ValueError("package-only guarded test receipt leaves the sealed output root")


def build_plan(
    *,
    repository: Path,
    output_root: Path,
    transient_root: Path,
    expectation: Mapping[str, Any] | None,
    uv_command: tuple[str, ...],
    official_environments: Path | None,
    profile: str = BUILD000_PROFILE,
) -> tuple[CommandSpec, ...]:
    """Declare every command for the selected release-verification profile."""

    repository = repository.resolve()
    output_root = output_root.resolve()
    transient_root = transient_root.resolve()
    if profile == BUILD001_PACKAGE_ONLY_PROFILE:
        return _build_package_only_plan(
            repository=repository,
            output_root=output_root,
            transient_root=transient_root,
            uv_command=uv_command,
        )
    if profile != BUILD000_PROFILE:
        raise ValueError(f"unsupported release-verification profile: {profile}")
    if expectation is None or official_environments is None:
        raise ValueError("Build 000 release verification requires benchmark and official inputs")
    official_environments = official_environments.resolve()
    python = sys.executable
    configuration = _expectation_configuration(expectation)
    agents = ",".join(cast(list[str], configuration["agents"]))
    seeds = ",".join(str(value) for value in cast(list[int], configuration["seeds"]))
    evaluation_root = output_root / "evaluations"
    evaluation_id = "stage18-benchmark-reproduction"
    package_a = output_root / "package-a"
    package_b = output_root / "package-b"
    official_root = output_root / "official-evaluations"
    official_id = "stage18-official-smoke"
    manifest_sha256 = expectation.get("public_partition_manifest_sha256")
    if not isinstance(manifest_sha256, str):
        raise ValueError("benchmark expectation has no public partition manifest identity")
    return (
        CommandSpec(
            "dependency-lock",
            "dependency-lock",
            (*uv_command, "lock", "--check", "--offline"),
            120.0,
            failure_status="FAILED_INFRASTRUCTURE",
        ),
        CommandSpec(
            "ruff-lint",
            "quality",
            (python, "-m", "ruff", "check", "--no-cache", "."),
            300.0,
        ),
        CommandSpec(
            "ruff-format",
            "quality",
            (python, "-m", "ruff", "format", "--check", "--no-cache", "."),
            300.0,
        ),
        CommandSpec(
            "mypy-strict",
            "quality",
            (
                python,
                "-m",
                "mypy",
                "--strict",
                "--cache-dir",
                str(transient_root / "cache" / "mypy" / "full"),
                "src",
                "agent",
                "scripts",
            ),
            900.0,
        ),
        CommandSpec(
            "full-test-suite",
            "tests",
            (
                python,
                "-m",
                "pytest",
                "-q",
                "--basetemp",
                str(transient_root / "tmp" / "pytest-full"),
            ),
            2400.0,
            nondeterminism=("test durations and coverage percentages may vary by host",),
        ),
        CommandSpec(
            "trace-replay-tamper",
            "trace-replay",
            (
                python,
                "-m",
                "pytest",
                "-q",
                "--no-cov",
                "--basetemp",
                str(transient_root / "tmp" / "pytest-replay"),
                "tests/replay",
                "tests/property/test_trace_properties.py",
            ),
            900.0,
        ),
        CommandSpec(
            "synthetic-benchmark",
            "synthetic",
            (
                python,
                "-m",
                "arc3",
                "evaluate",
                "--partition",
                str(configuration["partition"]),
                "--agents",
                agents,
                "--seeds",
                seeds,
                "--max-actions",
                str(configuration["max_actions"]),
                "--max-resets",
                str(configuration["max_resets"]),
                "--timeout-seconds",
                str(configuration["timeout_seconds"]),
                "--output-root",
                str(evaluation_root),
                "--evaluation-id",
                evaluation_id,
            ),
            900.0,
            nondeterminism=(
                "timestamps, runtime metrics, source identity, and sealed artifact hashes change",
                "the separately compared completion/action/score projection must remain exact",
            ),
        ),
        CommandSpec(
            "synthetic-artifact-verification",
            "synthetic",
            (
                python,
                "-m",
                "arc3",
                "verify-artifacts",
                "--evaluation",
                evaluation_id,
                "--output-root",
                str(evaluation_root),
            ),
            300.0,
            dependencies=("synthetic-benchmark",),
        ),
        CommandSpec(
            "offline-package-a",
            "offline-package",
            (
                python,
                "-m",
                "scripts.prepare_kaggle_submission",
                "--output",
                str(package_a),
                "--sandbox-timeout",
                "120",
            ),
            900.0,
        ),
        CommandSpec(
            "offline-package-b",
            "offline-package",
            (
                python,
                "-m",
                "scripts.prepare_kaggle_submission",
                "--output",
                str(package_b),
                "--sandbox-timeout",
                "120",
            ),
            900.0,
        ),
        CommandSpec(
            "competition-integrity",
            "integrity",
            (
                python,
                "-m",
                "scripts.check_competition_integrity",
                "--root",
                str(repository),
                "--expected-manifest-sha256",
                manifest_sha256,
                "--archive",
                str(package_a / "arc3-kaggle-candidate.zip"),
                "--output",
                str(output_root / "integrity-receipt.json"),
            ),
            900.0,
            dependencies=("offline-package-a",),
            nondeterminism=(
                "installed distribution metadata may differ by platform while lock identity stays fixed",
            ),
        ),
        CommandSpec(
            "official-inventory",
            "official-smoke",
            (
                python,
                "-m",
                "scripts.evaluate_public",
                "--partition",
                "smoke",
                "--manifest",
                str(repository / "docs/evaluation/public-game-partitions.v0.1.json"),
                "--environments-dir",
                str(official_environments),
                "--recordings-dir",
                str(output_root / "official-recordings"),
                "--inventory-only",
            ),
            180.0,
            failure_status="FAILED_INFRASTRUCTURE",
        ),
        CommandSpec(
            "official-smoke",
            "official-smoke",
            (
                python,
                "-m",
                "scripts.evaluate_public",
                "--partition",
                "smoke",
                "--agents",
                "random,cycle,full",
                "--seeds",
                "7,11",
                "--max-actions",
                "80",
                "--max-resets",
                "8",
                "--timeout-seconds",
                "120",
                "--frozen-commit",
                "{CANDIDATE_COMMIT}",
                "--manifest",
                str(repository / "docs/evaluation/public-game-partitions.v0.1.json"),
                "--environments-dir",
                str(official_environments),
                "--recordings-dir",
                str(output_root / "official-recordings"),
                "--output-root",
                str(official_root),
                "--exposure-ledger",
                str(output_root / "official-exposure.jsonl"),
                "--evaluation-id",
                official_id,
                "--milestone-id",
                "build-000-stage18-release-candidate",
            ),
            3000.0,
            required=False,
            dependencies=("official-inventory",),
        ),
        CommandSpec(
            "official-artifact-verification",
            "official-smoke",
            (
                python,
                "-m",
                "scripts.evaluate_public",
                "--verify",
                str(official_root / official_id),
            ),
            300.0,
            required=False,
            dependencies=("official-inventory",),
        ),
    )


def _replace_candidate_commit(spec: CommandSpec, commit: str) -> CommandSpec:
    return CommandSpec(
        check_id=spec.check_id,
        category=spec.category,
        argv=tuple(commit if item == "{CANDIDATE_COMMIT}" else item for item in spec.argv),
        timeout_seconds=spec.timeout_seconds,
        required=spec.required,
        dependencies=spec.dependencies,
        failure_status=spec.failure_status,
        nondeterminism=spec.nondeterminism,
        measure_peak_rss=spec.measure_peak_rss,
    )


def _required_mapping(value: object, *, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be an object")
    return cast(dict[str, Any], value)


def evaluation_projection(directory: Path) -> dict[str, object]:
    """Extract only deterministic score/action semantics from an evaluation."""

    manifest = _json_object(directory / "manifest.json")
    summary = _json_object(directory / "summary.json")
    agent_config = _required_mapping(manifest.get("agent_config"), name="agent_config")
    runs: list[dict[str, object]] = []
    try:
        lines = (directory / "results.jsonl").read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as error:
        raise ValueError(f"cannot read evaluation results: {error}") from error
    for line_number, line in enumerate(lines, start=1):
        if not line:
            continue
        try:
            raw: object = json.loads(line)
        except json.JSONDecodeError as error:
            raise ValueError(f"results line {line_number} is invalid JSON: {error}") from error
        result = _required_mapping(raw, name=f"results line {line_number}")
        score = _required_mapping(result.get("score"), name=f"results line {line_number} score")
        metrics = _required_mapping(
            result.get("metrics"), name=f"results line {line_number} metrics"
        )
        runs.append(
            {
                "actions": metrics.get("environment_actions"),
                "agent": result.get("agent"),
                "baseline_id": result.get("baseline_id"),
                "completed": score.get("completed"),
                "levels_completed": score.get("levels_completed"),
                "score": score.get("score"),
                "seed": result.get("seed"),
                "status": result.get("status"),
            }
        )
    runs.sort(key=lambda item: (str(item["baseline_id"]), int(cast(int, item["seed"]))))
    return {
        "configuration": {
            "agents": agent_config.get("agents"),
            "max_actions": agent_config.get("max_actions"),
            "max_resets": agent_config.get("max_resets"),
            "network_mode": agent_config.get("network_mode"),
            "partition": agent_config.get("partition"),
            "seeds": agent_config.get("seeds"),
            "surface": agent_config.get("surface"),
            "timeout_seconds": agent_config.get("timeout_seconds"),
        },
        "runs": runs,
        "summary": {
            "failure_count": summary.get("failure_count"),
            "result_count": summary.get("result_count"),
            "status": summary.get("status"),
            "successful_policy_count": summary.get("successful_policy_count"),
            "surface": summary.get("surface"),
        },
    }


def _stage_evidence_projection(evidence: Mapping[str, Any]) -> dict[str, object]:
    controlled = _required_mapping(
        evidence.get("controlled_comparison"), name="benchmark evidence controlled comparison"
    )
    runtime = _required_mapping(evidence.get("runtime"), name="benchmark evidence runtime")
    raw_policies = controlled.get("policies")
    if not isinstance(raw_policies, list):
        raise ValueError("benchmark evidence policies must be a list")
    runs: list[dict[str, object]] = []
    agents: list[str] = []
    for raw_policy in raw_policies:
        policy = _required_mapping(raw_policy, name="benchmark evidence policy")
        agent = policy.get("agent")
        baseline_id = policy.get("baseline_id")
        per_seed = policy.get("per_seed")
        if not isinstance(agent, str) or not isinstance(baseline_id, str):
            raise ValueError("benchmark evidence policy identity is invalid")
        if not isinstance(per_seed, list):
            raise ValueError("benchmark evidence per-seed records must be a list")
        agents.append(agent)
        for raw_seed in per_seed:
            seed = _required_mapping(raw_seed, name="benchmark evidence seed result")
            completed = seed.get("completed")
            if not isinstance(completed, int) or isinstance(completed, bool):
                raise ValueError("benchmark evidence completion count is invalid")
            runs.append(
                {
                    "actions": seed.get("actions"),
                    "agent": agent,
                    "baseline_id": baseline_id,
                    "completed": completed == 1,
                    "levels_completed": completed,
                    "score": seed.get("score"),
                    "seed": seed.get("seed"),
                    "status": "success",
                }
            )
    runs.sort(key=lambda item: (str(item["baseline_id"]), int(cast(int, item["seed"]))))
    return {
        "configuration": {
            "agents": agents,
            "max_actions": controlled.get("action_budget_per_run"),
            "max_resets": controlled.get("reset_budget_per_run"),
            "network_mode": runtime.get("network_mode"),
            "partition": controlled.get("partition"),
            "seeds": controlled.get("seeds"),
            "surface": controlled.get("surface"),
            "timeout_seconds": controlled.get("wall_clock_budget_seconds"),
        },
        "runs": runs,
        "summary": {
            "failure_count": controlled.get("failure_count"),
            "result_count": controlled.get("result_count"),
            "status": evidence.get("status"),
            "successful_policy_count": controlled.get("successful_policy_count"),
            "surface": controlled.get("surface"),
        },
    }


def benchmark_basis_identity(
    expectation: Mapping[str, Any], repository: Path, candidate_commit: str
) -> dict[str, object]:
    """Bind the frozen expectation to committed measured evidence and ancestry."""

    repository = repository.resolve()
    basis = _required_mapping(expectation.get("basis"), name="benchmark expectation basis")
    evidence_relative = basis.get("evidence")
    evidence_sha256 = basis.get("evidence_sha256")
    evidence_commit = basis.get("evidence_commit")
    measured_commit = basis.get("measured_commit")
    measured_configuration_hash = basis.get("measured_configuration_hash")
    measured_manifest_sha256 = basis.get("measured_manifest_sha256")
    measured_projection_sha256 = basis.get("measured_projection_sha256")
    required_strings = {
        "evidence": evidence_relative,
        "evidence_sha256": evidence_sha256,
        "evidence_commit": evidence_commit,
        "measured_commit": measured_commit,
        "measured_configuration_hash": measured_configuration_hash,
        "measured_manifest_sha256": measured_manifest_sha256,
        "measured_projection_sha256": measured_projection_sha256,
    }
    if not all(isinstance(value, str) and value for value in required_strings.values()):
        raise ValueError("benchmark expectation basis is incomplete")
    assert isinstance(evidence_relative, str)
    assert isinstance(evidence_sha256, str)
    assert isinstance(evidence_commit, str)
    assert isinstance(measured_commit, str)
    assert isinstance(measured_configuration_hash, str)
    assert isinstance(measured_manifest_sha256, str)
    assert isinstance(measured_projection_sha256, str)
    if not _COMMIT.fullmatch(evidence_commit) or not _COMMIT.fullmatch(measured_commit):
        raise ValueError("benchmark evidence commits must be full lowercase SHAs")
    evidence_path = (repository / evidence_relative).resolve()
    try:
        evidence_path.relative_to(repository)
    except ValueError as error:
        raise ValueError("benchmark evidence path escapes the repository") from error
    if sha256_file(evidence_path) != evidence_sha256:
        raise ValueError("benchmark evidence file hash does not match the expectation")
    evidence = _json_object(evidence_path)
    if evidence.get("measured_repository_commit") != measured_commit:
        raise ValueError("benchmark evidence measured commit disagrees with the expectation")
    if evidence.get("status") != "PASS" or evidence.get("label") != "synthetic":
        raise ValueError("benchmark evidence is not a passing synthetic receipt")
    identity = _required_mapping(evidence.get("identity"), name="benchmark evidence identity")
    if identity.get("git_commit") != measured_commit:
        raise ValueError("benchmark evidence identity commit is inconsistent")
    if identity.get("configuration_hash") != measured_configuration_hash:
        raise ValueError("benchmark evidence configuration hash is inconsistent")
    controlled = _required_mapping(
        evidence.get("controlled_comparison"), name="benchmark controlled comparison"
    )
    sealed = _required_mapping(
        controlled.get("sealed_artifacts"), name="benchmark sealed artifacts"
    )
    if (
        sealed.get("manifest_sha256") != measured_manifest_sha256
        or sealed.get("verified") is not True
    ):
        raise ValueError("benchmark measured manifest is not the frozen verified artifact")
    expected_projection = expectation.get("expected_projection")
    if not isinstance(expected_projection, dict):
        raise ValueError("benchmark expectation has no expected projection")
    evidence_projection = _stage_evidence_projection(evidence)
    projection_sha256 = sha256_bytes(canonical_json_bytes(evidence_projection))
    if projection_sha256 != measured_projection_sha256:
        raise ValueError("benchmark evidence projection hash changed")
    if canonical_json_bytes(evidence_projection) != canonical_json_bytes(expected_projection):
        raise ValueError("benchmark evidence semantics disagree with the frozen projection")
    for older, newer, label in (
        (measured_commit, evidence_commit, "measured commit to evidence commit"),
        (evidence_commit, candidate_commit, "evidence commit to candidate commit"),
        (measured_commit, candidate_commit, "measured commit to candidate commit"),
    ):
        if not _COMMIT.fullmatch(newer):
            raise ValueError(f"{label} uses an invalid commit")
        ancestor = _git_result(repository, "merge-base", "--is-ancestor", older, newer)
        if ancestor.returncode != 0:
            raise ValueError(f"benchmark ancestry check failed: {label}")
    committed = _git_result(repository, "show", f"{evidence_commit}:{evidence_relative}")
    if committed.returncode != 0 or sha256_bytes(committed.stdout) != evidence_sha256:
        raise ValueError("benchmark evidence commit does not contain the frozen evidence bytes")
    return {
        "configuration_hash": measured_configuration_hash,
        "evidence_commit": evidence_commit,
        "evidence_path": evidence_relative,
        "evidence_sha256": evidence_sha256,
        "measured_commit": measured_commit,
        "measured_commit_is_ancestor": True,
        "measured_manifest_sha256": measured_manifest_sha256,
        "measured_projection_sha256": measured_projection_sha256,
    }


def compare_benchmark(
    expectation: Mapping[str, Any], evaluation_directory: Path
) -> tuple[bool, dict[str, object]]:
    """Compare exact deterministic semantics and explain excluded byte drift."""

    expected = expectation.get("expected_projection")
    if not isinstance(expected, dict):
        raise ValueError("benchmark expectation has no expected_projection object")
    actual = evaluation_projection(evaluation_directory)
    expected_bytes = canonical_json_bytes(expected)
    actual_bytes = canonical_json_bytes(actual)
    permitted = expectation.get("permitted_nondeterminism")
    if not isinstance(permitted, list) or not all(isinstance(item, str) for item in permitted):
        raise ValueError("benchmark expectation has invalid permitted_nondeterminism")
    return expected_bytes == actual_bytes, {
        "actual_projection": actual,
        "actual_projection_sha256": sha256_bytes(actual_bytes),
        "expected_projection_sha256": sha256_bytes(expected_bytes),
        "permitted_nondeterminism": cast(list[str], permitted),
        "semantic_projection_equal": expected_bytes == actual_bytes,
    }


_PACKAGE_FIELDS = (
    "candidate_sha256",
    "manifest_sha256",
    "notebook_sha256",
    "payload_sha256",
    "runtime_requirements_sha256",
    "sbom_sha256",
    "wheel_manifest_sha256",
)

_PACKAGE_FILE_FIELDS = {
    "candidate_sha256": "arc3-kaggle-candidate.zip",
    "manifest_sha256": "package-manifest.json",
    "notebook_sha256": "arc3-submission.ipynb",
    "payload_sha256": "arc3-first-party.zip",
    "runtime_requirements_sha256": "runtime-requirements-linux-cp312.txt",
    "sbom_sha256": "sbom.spdx.json",
    "wheel_manifest_sha256": "runtime-wheels-linux-cp312.json",
}
_CANDIDATE_MEMBERS = frozenset(
    {
        "arc3-first-party.zip",
        "arc3-submission.ipynb",
        "kernel-metadata.json",
        "package-manifest.json",
        "runtime-requirements-linux-cp312.txt",
        "runtime-wheels-linux-cp312.json",
        "sbom.spdx.json",
        "submission-schema.v0.1.json",
    }
)


@dataclass(frozen=True, slots=True)
class _BoundedPackageArchives:
    """Immutable snapshots accepted by the bounded recursive archive scanner."""

    records: tuple[tuple[Path, str, bytes], ...]

    def hash_for(self, path: Path) -> str:
        resolved = path.resolve()
        for candidate, digest, _snapshot in self.records:
            if candidate == resolved:
                return digest
        raise ValueError(f"bounded archive set omits {resolved.name}")

    def snapshot_for(self, path: Path) -> bytes:
        resolved = path.resolve()
        for candidate, _digest, snapshot in self.records:
            if candidate == resolved:
                return snapshot
        raise ValueError(f"bounded archive set omits {resolved.name}")


def _bounded_package_archive_preflight(
    package_roots: Sequence[Path],
    *,
    max_archive_bytes: int = DEFAULT_MAX_ARCHIVE_BYTES,
    max_member_bytes: int = DEFAULT_MAX_ARCHIVE_MEMBER_BYTES,
    max_members: int = DEFAULT_MAX_ARCHIVE_MEMBERS,
    max_expanded_bytes: int = DEFAULT_MAX_ARCHIVE_EXPANDED_BYTES,
    max_central_directory_bytes: int = DEFAULT_MAX_ARCHIVE_CENTRAL_DIRECTORY_BYTES,
    max_depth: int = DEFAULT_MAX_ARCHIVE_DEPTH,
) -> _BoundedPackageArchives:
    """Bound both candidate builds and payloads before any unbounded ZIP consumer."""

    roots = tuple(root.resolve() for root in package_roots)
    if not roots or len(set(roots)) != len(roots):
        raise ValueError("package archive preflight requires distinct package roots")
    common_root = Path(os.path.commonpath([str(root.parent) for root in roots])).resolve()
    archives = tuple(
        artifact
        for root in roots
        for artifact in (
            root / "arc3-kaggle-candidate.zip",
            root / "arc3-first-party.zip",
        )
    )
    scanned_hashes: dict[str, str] = {}
    scanned_snapshots: dict[str, bytes] = {}
    findings = scan_archive_files(
        root=common_root,
        archives=archives,
        public_identifiers=(),
        max_archive_bytes=max_archive_bytes,
        max_member_bytes=max_member_bytes,
        max_members=max_members,
        max_expanded_bytes=max_expanded_bytes,
        max_central_directory_bytes=max_central_directory_bytes,
        max_depth=max_depth,
        scanned_hashes=scanned_hashes,
        scanned_snapshots=scanned_snapshots,
    )
    if findings:
        summary = ", ".join(f"{finding.path}:{finding.rule_id}" for finding in findings[:8])
        raise ValueError(f"bounded package archive preflight failed: {summary}")
    records: list[tuple[Path, str, bytes]] = []
    for archive in archives:
        label = archive.relative_to(common_root).as_posix()
        digest = scanned_hashes.get(label)
        snapshot = scanned_snapshots.get(label)
        if digest is None or snapshot is None or sha256_bytes(snapshot) != digest:
            raise ValueError("bounded package archive preflight omitted an artifact snapshot")
        records.append((archive.resolve(), digest, snapshot))
    return _BoundedPackageArchives(records=tuple(records))


def _manifest_artifact_hashes(manifest: Mapping[str, Any]) -> dict[str, tuple[str, int]]:
    records = manifest.get("artifacts")
    if not isinstance(records, list):
        raise ValueError("package manifest has no artifact records")
    result: dict[str, tuple[str, int]] = {}
    for raw in records:
        record = _required_mapping(raw, name="package manifest artifact")
        path = record.get("path")
        digest = record.get("sha256")
        size = record.get("size_bytes")
        if (
            not isinstance(path, str)
            or path in result
            or path not in _CANDIDATE_MEMBERS - {"package-manifest.json"}
            or not isinstance(digest, str)
            or not re.fullmatch(r"sha256:[0-9a-f]{64}", digest)
            or isinstance(size, bool)
            or not isinstance(size, int)
            or size < 0
        ):
            raise ValueError("package manifest artifact record is invalid")
        result[path] = (digest, size)
    if set(result) != _CANDIDATE_MEMBERS - {"package-manifest.json"}:
        raise ValueError("package manifest artifact set is incomplete")
    return result


def _validate_package_formats(
    candidate_members: Mapping[str, bytes],
    *,
    payload_snapshot: bytes,
    sandbox_output_snapshot: bytes,
    validate_executable_notebook: bool,
) -> dict[str, object]:
    parsed_json: dict[str, dict[str, Any]] = {}
    for name in (
        "arc3-submission.ipynb",
        "kernel-metadata.json",
        "package-manifest.json",
        "runtime-wheels-linux-cp312.json",
        "sbom.spdx.json",
        "submission-schema.v0.1.json",
    ):
        parsed_json[name] = _json_object_bytes(candidate_members[name], label=f"candidate!/{name}")
    try:
        requirements = candidate_members["runtime-requirements-linux-cp312.txt"].decode("utf-8")
    except UnicodeDecodeError as error:
        raise ValueError("runtime requirements are not valid UTF-8") from error
    lines = [line for line in requirements.splitlines() if line and not line.startswith("#")]
    if not lines or any("--hash=sha256:" not in line for line in lines):
        raise ValueError("runtime requirements are not an exact hash-locked declaration")
    try:
        with zipfile.ZipFile(io.BytesIO(payload_snapshot)) as payload:
            names = [info.filename for info in payload.infolist()]
            if (
                len(names) != len(set(names))
                or not {"agent/my_agent.py", "src/arc3/__init__.py"} <= set(names)
                or any(
                    info.is_dir()
                    or info.filename.startswith("/")
                    or ".." in Path(info.filename).parts
                    for info in payload.infolist()
                )
            ):
                raise ValueError("first-party payload member set is unsafe or incomplete")
    except (OSError, zipfile.BadZipFile) as error:
        raise ValueError(f"first-party payload cannot be independently decoded: {error}") from error
    notebook_projection: dict[str, object] = {"status": "NOT_EVALUATED_FIXTURE_PROJECTION"}
    if validate_executable_notebook:
        embedded = notebook_embedded_inputs(parsed_json["arc3-submission.ipynb"])
        if embedded.payload != payload_snapshot:
            raise ValueError("notebook embedded payload differs from the bounded package payload")
        if embedded.requirements != candidate_members["runtime-requirements-linux-cp312.txt"]:
            raise ValueError("notebook embedded requirements differ from the bounded runtime lock")
        manifest = parsed_json["package-manifest.json"]
        source = _required_mapping(manifest.get("source"), name="package manifest source")
        if embedded.source_commit != source.get("git_commit"):
            raise ValueError("notebook embedded source commit differs from the package manifest")
        if embedded.validation_parquet != sandbox_output_snapshot:
            raise ValueError(
                "notebook embedded validation output differs from the sandbox artifact"
            )
        notebook_projection = {
            "payload_sha256": sha256_bytes(embedded.payload),
            "requirements_sha256": sha256_bytes(embedded.requirements),
            "source_commit": embedded.source_commit,
            "status": "PASS",
            "validation_parquet_sha256": sha256_bytes(embedded.validation_parquet),
        }
    return {
        "candidate_member_count": len(_CANDIDATE_MEMBERS),
        "notebook_embedded_inputs": notebook_projection,
        "payload_member_count": len(names),
        "runtime_requirement_count": len(lines),
    }


def _package_runtime_format_metrics(
    *,
    candidate_snapshot: bytes,
    payload_snapshot: bytes,
    candidate_members: Mapping[str, bytes],
) -> dict[str, object]:
    wheel_manifest = _json_object_bytes(
        candidate_members["runtime-wheels-linux-cp312.json"],
        label="candidate!/runtime-wheels-linux-cp312.json",
    )
    raw_packages = wheel_manifest.get("packages")
    if not isinstance(raw_packages, list) or not raw_packages:
        raise ValueError("runtime wheel manifest has no package records")
    wheel_names: list[str] = []
    for raw_package in raw_packages:
        package = _required_mapping(raw_package, name="runtime wheel package")
        package_name = package.get("name")
        if not isinstance(package_name, str) or not package_name or package_name in wheel_names:
            raise ValueError("runtime wheel manifest has an invalid package identity")
        wheel_names.append(package_name)
    return {
        "archive_size_bytes": len(candidate_snapshot),
        "payload_size_bytes": len(payload_snapshot),
        "runtime_wheel_count": len(wheel_names),
        "runtime_wheel_names_sha256": sha256_bytes(canonical_json_bytes(sorted(wheel_names))),
    }


def package_projection(
    receipt_path: Path,
    *,
    expected_commit: str | None = None,
    include_runtime_metrics: bool = False,
    repository: Path | None = None,
    bounded_archives: _BoundedPackageArchives | None = None,
) -> dict[str, object]:
    """Validate and project one package receipt to deterministic artifact identities."""

    package_root = receipt_path.resolve().parent
    candidate_path = package_root / "arc3-kaggle-candidate.zip"
    payload_path = package_root / "arc3-first-party.zip"
    preflight = (
        _bounded_package_archive_preflight((package_root,))
        if bounded_archives is None
        else bounded_archives
    )
    candidate_snapshot = preflight.snapshot_for(candidate_path)
    payload_snapshot = preflight.snapshot_for(payload_path)
    current_archives = _bounded_package_archive_preflight((package_root,))
    if current_archives.hash_for(candidate_path) != preflight.hash_for(
        candidate_path
    ) or current_archives.hash_for(payload_path) != preflight.hash_for(payload_path):
        raise ValueError("bounded archive paths changed after their immutable snapshots were read")
    candidate_members = decode_candidate_archive_snapshot(candidate_snapshot)
    if candidate_members["arc3-first-party.zip"] != payload_snapshot:
        raise ValueError("candidate payload differs from the bounded top-level payload snapshot")
    top_level_snapshots: dict[str, bytes] = {}
    for relative in sorted(_CANDIDATE_MEMBERS):
        if relative == "arc3-first-party.zip":
            raw = payload_snapshot
        else:
            raw = read_bounded_regular_snapshot(
                root=package_root,
                path=package_root / relative,
                max_bytes=DEFAULT_MAX_ARCHIVE_MEMBER_BYTES,
                path_label=relative,
            )
        if raw != candidate_members[relative]:
            raise ValueError(f"candidate member differs from top-level package file: {relative}")
        top_level_snapshots[relative] = raw
    receipt_raw = read_bounded_regular_snapshot(
        root=package_root,
        path=receipt_path,
        max_bytes=DEFAULT_MAX_CANDIDATE_BYTES,
        path_label=receipt_path.name,
    )
    receipt = _verified_package_receipt_bytes(receipt_raw, label=str(receipt_path))
    if receipt.get("schema") != "arc3.kaggle-build-receipt.v0.1":
        raise ValueError(f"unsupported package receipt schema: {receipt_path}")
    if receipt.get("status") != "PACKAGING_PASS":
        raise ValueError(f"package receipt does not claim PACKAGING_PASS: {receipt_path}")
    if receipt.get("official_submission_performed") is not False:
        raise ValueError(f"package receipt has an invalid submission boundary: {receipt_path}")
    actual_hashes: dict[str, str] = {}
    for field, relative in _PACKAGE_FILE_FIELDS.items():
        claimed = receipt.get(field)
        if not isinstance(claimed, str):
            raise ValueError(f"package receipt is missing {field}: {receipt_path}")
        if relative == "arc3-kaggle-candidate.zip":
            actual = preflight.hash_for(candidate_path)
        elif relative == "arc3-first-party.zip":
            actual = preflight.hash_for(payload_path)
        else:
            actual = sha256_bytes(top_level_snapshots[relative])
        if claimed != actual:
            raise ValueError(f"package artifact {relative} disagrees with {field}")
        actual_hashes[field] = actual
    sandbox = _required_mapping(receipt.get("sandbox"), name="package sandbox")
    validation = _required_mapping(receipt.get("validation"), name="package validation")
    candidate_validation = _required_mapping(
        receipt.get("candidate_validation"), name="package candidate validation"
    )
    if candidate_validation.get("status") != "PASS":
        raise ValueError("package candidate validation did not pass")
    if candidate_validation.get("candidate_sha256") != actual_hashes["candidate_sha256"]:
        raise ValueError("package candidate validation is not linked to the candidate bytes")
    payload_git_projection_sha256: str | None = None
    if repository is not None:
        if expected_commit is None:
            raise ValueError("Git-bound package projection requires an expected commit")
        recomputed_validation = validate_candidate_member_snapshots(
            candidate_snapshot,
            candidate_members,
        )
        if candidate_validation != recomputed_validation:
            raise ValueError("package candidate validation was not independently reproducible")
        expected_members, expected_records, expected_source = collect_git_payload(
            repository,
            expected_commit,
        )
        expected_payload = deterministic_zip_bytes(expected_members)
        if sha256_bytes(expected_payload) != actual_hashes["payload_sha256"]:
            raise ValueError("first-party payload bytes do not derive from the expected Git commit")
        manifest_for_source = _json_object_bytes(
            candidate_members["package-manifest.json"],
            label="candidate!/package-manifest.json",
        )
        payload_for_source = _required_mapping(
            manifest_for_source.get("payload"), name="package manifest payload"
        )
        if (
            payload_for_source.get("files") != [record.to_dict() for record in expected_records]
            or payload_for_source.get("source_identity") != expected_source
        ):
            raise ValueError("first-party payload projection differs from the expected Git tree")
        payload_git_projection_sha256 = sha256_bytes(
            canonical_json_bytes(
                {
                    "files": payload_for_source.get("files"),
                    "source_identity": payload_for_source.get("source_identity"),
                }
            )
        )
    if sandbox.get("status") != "PASS" or validation.get("status") != "PASS":
        raise ValueError("package sandbox or schema validation did not pass")
    sandbox_sha256 = sha256_bytes(package_canonical_json_bytes(sandbox))
    if receipt.get("sandbox_receipt_sha256") != sandbox_sha256:
        raise ValueError("package sandbox receipt hash is not linked to the receipt")
    sandbox_output = package_root / "offline-sandbox" / "submission.parquet"
    sandbox_output_snapshot = read_bounded_regular_snapshot(
        root=package_root,
        path=sandbox_output,
        max_bytes=DEFAULT_MAX_CANDIDATE_BYTES,
        path_label="offline-sandbox/submission.parquet",
    )
    actual_output_sha256 = sha256_bytes(sandbox_output_snapshot)
    if not (
        receipt.get("sandbox_output_sha256")
        == sandbox.get("output_sha256")
        == validation.get("artifact_sha256")
        == actual_output_sha256
    ):
        raise ValueError("package sandbox output identities do not agree")
    if sandbox.get("notebook_sha256") != actual_hashes["notebook_sha256"]:
        raise ValueError("package sandbox is not linked to the notebook")
    if sandbox.get("payload_sha256") != actual_hashes["payload_sha256"]:
        raise ValueError("package sandbox is not linked to the first-party payload")
    if sandbox.get("requirements_sha256") != actual_hashes["runtime_requirements_sha256"]:
        raise ValueError("package sandbox is not linked to the runtime requirements")
    if sandbox.get("secret_scan_status") != "PASS":
        raise ValueError("package sandbox secret rescan did not pass")
    if sandbox.get("network_attempts") != 0 or sandbox.get("credentials_present") != []:
        raise ValueError("package sandbox crossed the offline or credential boundary")
    manifest = _json_object_bytes(
        candidate_members["package-manifest.json"],
        label="candidate!/package-manifest.json",
    )
    source = _required_mapping(manifest.get("source"), name="package manifest source")
    if manifest.get("build_status") != "PACKAGING_PASS" or source.get("git_dirty") is not False:
        raise ValueError("package manifest does not bind PACKAGING_PASS to a clean source")
    if expected_commit is not None and source.get("git_commit") != expected_commit:
        raise ValueError("package manifest source commit differs from the release candidate")
    runtime_lock = _required_mapping(
        manifest.get("runtime_lock"), name="package manifest runtime lock"
    )
    if (
        runtime_lock.get("requirements_sha256") != actual_hashes["runtime_requirements_sha256"]
        or runtime_lock.get("wheel_manifest_sha256") != actual_hashes["wheel_manifest_sha256"]
    ):
        raise ValueError("package manifest is not linked to the runtime lock files")
    secret_scan = _required_mapping(manifest.get("secret_scan"), name="package secret scan")
    if secret_scan.get("status") != "PASS" or secret_scan.get("findings") != []:
        raise ValueError("package manifest secret scan did not pass cleanly")
    manifest_records = _manifest_artifact_hashes(manifest)
    format_validation = _validate_package_formats(
        candidate_members,
        payload_snapshot=payload_snapshot,
        sandbox_output_snapshot=sandbox_output_snapshot,
        validate_executable_notebook=repository is not None,
    )
    for relative in sorted(_CANDIDATE_MEMBERS):
        actual = sha256_bytes(candidate_members[relative])
        if relative != "package-manifest.json":
            recorded_digest, recorded_size = manifest_records[relative]
            if recorded_digest != actual or recorded_size != len(candidate_members[relative]):
                raise ValueError(f"package manifest artifact identity changed: {relative}")
    if not (
        sandbox.get("dependency_install_status") == "PASS"
        and sandbox.get("production_rerun_exercised") is True
        and sandbox.get("framework_fixture") is True
        and sandbox.get("imported_arc3_path") == "arc3_submission/src/arc3/__init__.py"
        and sandbox.get("gateway_connections") in range(2, 2**31)
    ):
        raise ValueError("package sandbox receipt is not linked to the production rerun path")
    projection: dict[str, object] = {field: actual_hashes[field] for field in _PACKAGE_FIELDS}
    projection.update(
        {
            "bounded_archive_preflight": {
                "candidate_sha256": preflight.hash_for(candidate_path),
                "max_archive_bytes_cumulative": DEFAULT_MAX_ARCHIVE_BYTES,
                "max_central_directory_bytes_cumulative": (
                    DEFAULT_MAX_ARCHIVE_CENTRAL_DIRECTORY_BYTES
                ),
                "max_depth": DEFAULT_MAX_ARCHIVE_DEPTH,
                "max_expanded_bytes_cumulative": DEFAULT_MAX_ARCHIVE_EXPANDED_BYTES,
                "max_member_bytes": DEFAULT_MAX_ARCHIVE_MEMBER_BYTES,
                "max_members_cumulative": DEFAULT_MAX_ARCHIVE_MEMBERS,
                "payload_sha256": preflight.hash_for(payload_path),
                "status": "PASS",
            },
            "build_receipt_sha256": sha256_bytes(receipt_raw),
            "candidate_member_sha256": {
                relative: sha256_bytes(candidate_members[relative])
                for relative in sorted(candidate_members)
            },
            "sandbox_output_sha256": actual_output_sha256,
            "sandbox_receipt_sha256": sandbox_sha256,
            "status": "PACKAGING_PASS",
            "validation_artifact_sha256": actual_output_sha256,
            "validated_formats": format_validation,
        }
    )
    if payload_git_projection_sha256 is not None:
        projection["payload_git_projection_sha256"] = payload_git_projection_sha256
    if include_runtime_metrics:
        projection.update(
            _package_runtime_format_metrics(
                candidate_snapshot=candidate_snapshot,
                payload_snapshot=payload_snapshot,
                candidate_members=candidate_members,
            )
        )
    return projection


def compare_packages(
    first: Path,
    second: Path,
    *,
    expected_commit: str | None = None,
    include_runtime_metrics: bool = False,
    repository: Path | None = None,
) -> tuple[bool, dict[str, object]]:
    """Require two fresh offline builds to produce byte-identical identities."""

    first_root = first.resolve().parent
    second_root = second.resolve().parent
    bounded_archives = _bounded_package_archive_preflight((first_root, second_root))
    first_projection = package_projection(
        first,
        expected_commit=expected_commit,
        include_runtime_metrics=include_runtime_metrics,
        repository=repository,
        bounded_archives=bounded_archives,
    )
    second_projection = package_projection(
        second,
        expected_commit=expected_commit,
        include_runtime_metrics=include_runtime_metrics,
        repository=repository,
        bounded_archives=bounded_archives,
    )
    first_bytes = canonical_json_bytes(first_projection)
    second_bytes = canonical_json_bytes(second_projection)
    return first_bytes == second_bytes, {
        "first": first_projection,
        "first_projection_sha256": sha256_bytes(first_bytes),
        "second": second_projection,
        "second_projection_sha256": sha256_bytes(second_bytes),
        "projections_equal": first_bytes == second_bytes,
    }


def _last_json_log_bytes(raw: bytes, *, label: str) -> dict[str, Any]:
    try:
        lines = [line for line in raw.decode("utf-8").splitlines() if line]
    except UnicodeDecodeError as error:
        raise ValueError(f"cannot decode command JSON log {label}: {error}") from error
    if not lines:
        raise ValueError(f"command JSON log is empty: {label}")
    try:
        loaded: object = json.loads(lines[-1])
    except json.JSONDecodeError as error:
        raise ValueError(f"last command output line is not JSON: {error}") from error
    return _required_mapping(loaded, name="command JSON output")


def _last_json_log(path: Path) -> dict[str, Any]:
    raw = read_bounded_regular_snapshot(
        root=path.resolve().parent,
        path=path,
        max_bytes=DEFAULT_MAX_CANDIDATE_BYTES,
        path_label=path.name,
    )
    return _last_json_log_bytes(raw, label=str(path))


def official_smoke_available(
    inventory: Mapping[str, Any], manifest_path: Path
) -> tuple[bool, dict[str, object]]:
    """Decide availability from identities only, without parsing game source."""

    manifest = _json_object(manifest_path)
    games = manifest.get("games")
    assignment = manifest.get("assignment")
    local_assets = inventory.get("local_assets")
    if (
        manifest.get("schema") != "arc3.public-game-partitions.v0.1"
        or not isinstance(assignment, dict)
        or not isinstance(assignment.get("salt"), str)
        or not assignment["salt"]
        or not isinstance(games, list)
        or not isinstance(local_assets, dict)
    ):
        raise ValueError("public manifest or inventory has the wrong shape")
    salt = cast(str, assignment["salt"])
    if inventory.get("schema") != "arc3.public-inventory.v0.1":
        raise ValueError("official inventory schema is unsupported")
    manifest_sha256 = sha256_file(manifest_path)
    if inventory.get("manifest_sha256") != manifest_sha256:
        raise ValueError("official inventory is not bound to the frozen partition manifest")
    if inventory.get("gameplay_opened") is not False:
        raise ValueError("official inventory crossed the metadata-only gameplay boundary")
    if inventory.get("online_metadata_revalidation") is not None:
        raise ValueError("release inventory unexpectedly performed online metadata revalidation")
    all_ids: set[str] = set()
    partition_ids: dict[str, set[str]] = {
        "development": set(),
        "public-holdout": set(),
        "smoke": set(),
    }
    for raw in games:
        entry = _required_mapping(raw, name="public game entry")
        game_id = entry.get("game_id")
        partition = entry.get("partition")
        stable_name = entry.get("stable_name")
        assignment_hash = entry.get("assignment_hash")
        if (
            not isinstance(game_id, str)
            or not re.fullmatch(r"[a-z0-9]+-[0-9a-f]{8}", game_id)
            or not isinstance(stable_name, str)
            or not game_id.startswith(f"{stable_name}-")
            or partition not in partition_ids
            or not isinstance(assignment_hash, str)
            or not re.fullmatch(r"[0-9a-f]{64}", assignment_hash)
            or assignment_hash != hashlib.sha256(f"{salt}\0{stable_name}".encode()).hexdigest()
        ):
            raise ValueError("public partition manifest has an invalid game identity")
        if game_id in all_ids:
            raise ValueError(f"public partition manifest repeats game ID {game_id}")
        all_ids.add(game_id)
        partition_ids[cast(str, partition)].add(game_id)
    counts = inventory.get("partition_counts")
    if not isinstance(counts, dict) or counts != {
        partition: len(partition_ids[partition]) for partition in partition_ids
    }:
        raise ValueError("official inventory partition counts disagree with the manifest")
    local_ids = {str(value) for value in local_assets}
    if not local_ids <= all_ids:
        raise ValueError("official inventory contains game IDs outside the frozen manifest")
    asset_hashes: dict[str, str] = {}
    for game_id, raw_asset in local_assets.items():
        asset = _required_mapping(raw_asset, name=f"official asset {game_id}")
        files = asset.get("files")
        if (
            asset.get("game_id") != game_id
            or asset.get("source_semantically_inspected") is not False
            or not isinstance(files, list)
            or not files
        ):
            raise ValueError(f"official asset identity is invalid for {game_id}")
        normalized_files: list[tuple[str, int, str]] = []
        names: set[str] = set()
        for raw_file in files:
            file = _required_mapping(raw_file, name=f"official asset file {game_id}")
            name = file.get("name")
            length = file.get("bytes")
            digest = file.get("sha256")
            if (
                not isinstance(name, str)
                or not name
                or name.startswith("/")
                or ".." in Path(name).parts
                or name in names
                or isinstance(length, bool)
                or not isinstance(length, int)
                or length < 0
                or not isinstance(digest, str)
                or not re.fullmatch(r"sha256:[0-9a-f]{64}", digest)
            ):
                raise ValueError(f"official asset file identity is invalid for {game_id}")
            names.add(name)
            normalized_files.append((name, length, digest))
        normalized_files.sort()
        aggregate = sha256_bytes(evaluation_canonical_json_bytes(normalized_files))
        if asset.get("aggregate_sha256") != aggregate:
            raise ValueError(f"official asset aggregate identity changed for {game_id}")
        asset_hashes[str(game_id)] = aggregate
    smoke_ids = partition_ids["smoke"]
    available = smoke_ids & local_ids
    missing = smoke_ids - local_ids
    return not missing and bool(smoke_ids), {
        "available_count": len(available),
        "available_game_ids": sorted(available),
        "availability_basis": "metadata and content identities only; game source not inspected",
        "game_asset_sha256": {game_id: asset_hashes[game_id] for game_id in sorted(available)},
        "gameplay_opened_by_inventory": inventory.get("gameplay_opened"),
        "manifest_sha256": manifest_sha256,
        "missing_count": len(missing),
        "missing_game_ids": sorted(missing),
        "required_count": len(smoke_ids),
        "required_game_ids": sorted(smoke_ids),
    }


def scan_generated_logs(
    output_root: Path, results: Sequence[CheckResult]
) -> tuple[bool, dict[str, object]]:
    """Verify only redacted streams were persisted and report any emission boundary crossing."""

    log_root = output_root / "logs"
    residual_findings: list[dict[str, object]] = []
    log_hashes: dict[str, str] = {}
    for path in sorted(log_root.glob("*.log")):
        if path.is_symlink() or not path.is_file():
            residual_findings.append({"file": path.name, "reason": "non-regular log"})
            continue
        try:
            content = read_bounded_regular_snapshot(
                root=output_root,
                path=path,
                max_bytes=DEFAULT_MAX_CANDIDATE_BYTES,
                path_label=path.relative_to(output_root).as_posix(),
            )
        except ValueError as error:
            residual_findings.append({"file": path.name, "reason": str(error)})
            continue
        labels = [
            f"pattern-{index}"
            for index, pattern in enumerate(_SECRET_PATTERNS, start=1)
            if pattern.search(content)
        ]
        if labels:
            residual_findings.append({"file": path.name, "patterns": labels})
        log_hashes[path.name] = sha256_bytes(content)
    redaction_count = 0
    for result in results:
        count = result.details.get("generated_log_redactions", 0)
        if isinstance(count, int) and not isinstance(count, bool):
            redaction_count += count
    passed = not residual_findings and redaction_count == 0
    return passed, {
        "log_count": len(log_hashes),
        "log_hashes": log_hashes,
        "persisted_streams": "redacted stdout/stderr only; pre-redaction bytes are never written",
        "redaction_count": redaction_count,
        "residual_finding_count": len(residual_findings),
        "residual_findings": residual_findings,
    }


def _package_only_expected_artifact_files(specs: Sequence[CommandSpec]) -> frozenset[str]:
    package_files = {
        *_CANDIDATE_MEMBERS,
        "arc3-kaggle-candidate.zip",
        "build-receipt.json",
        "offline-sandbox/submission.parquet",
    }
    return frozenset(
        {
            "integrity-receipt.json",
            "package-only-test-guard.json",
            *(f"logs/{spec.check_id}.stdout.log" for spec in specs),
            *(f"logs/{spec.check_id}.stderr.log" for spec in specs),
            *(f"package-a/{relative}" for relative in package_files),
            *(f"package-b/{relative}" for relative in package_files),
        }
    )


def _complete_artifact_set(
    output_root: Path,
    *,
    sealed: bool,
    expected_files: frozenset[str] | None = None,
    scan_all_sealed_bytes_for_secrets: bool = False,
) -> dict[str, object]:
    """Hash the complete non-transient output set, excluding self-referential wrappers."""

    files: dict[str, str] = {}
    total_bytes = 0
    secret_findings: list[dict[str, object]] = []
    for path in sorted(output_root.rglob("*")):
        relative = path.relative_to(output_root).as_posix()
        if relative in _RECEIPT_WRAPPERS:
            continue
        if path.is_symlink():
            raise ValueError(f"release artifact set contains a symlink: {relative}")
        if relative.startswith(_TRANSIENT_OUTPUT_PREFIXES):
            if expected_files is not None and not path.is_dir():
                raise ValueError(
                    f"package-only output contains an unsealed transient-prefix file: {relative}"
                )
            continue
        if path.is_dir():
            continue
        if not path.is_file():
            raise ValueError(f"release artifact set contains a non-regular node: {relative}")
        raw = read_bounded_regular_snapshot(
            root=output_root,
            path=path,
            max_bytes=DEFAULT_MAX_ARCHIVE_BYTES,
            path_label=relative,
        )
        files[relative] = sha256_bytes(raw)
        total_bytes += len(raw)
        if scan_all_sealed_bytes_for_secrets:
            patterns = [
                f"pattern-{index}"
                for index, pattern in enumerate(_SECRET_PATTERNS, start=1)
                if pattern.search(raw)
            ]
            if patterns:
                secret_findings.append({"file": relative, "patterns": patterns})
    if expected_files is not None and set(files) != set(expected_files):
        missing = sorted(set(expected_files).difference(files))
        extra = sorted(set(files).difference(expected_files))
        raise ValueError(
            "package-only output membership differs from the exact artifact contract; "
            f"missing={missing[:8]}, extra={extra[:8]}"
        )
    if secret_findings:
        raise ValueError("release artifact set contains a secret-pattern finding")
    if sealed and not files:
        raise ValueError("a passing release verification cannot seal an empty artifact set")
    return {
        "all_sealed_raw_bytes_secret_scanned": scan_all_sealed_bytes_for_secrets,
        "complete": sealed,
        "excluded_prefixes": list(_TRANSIENT_OUTPUT_PREFIXES),
        "excluded_wrappers": sorted(_RECEIPT_WRAPPERS),
        "expected_allowlist_enforced": expected_files is not None,
        "file_count": len(files),
        "files": files,
        "secret_finding_count": len(secret_findings),
        "set_sha256": sha256_bytes(canonical_json_bytes(files)),
        "total_bytes": total_bytes,
    }


def _validate_package_only_seal_links(
    sealed_artifact_set: Mapping[str, object],
    *,
    package_details: Mapping[str, object],
    guard_details: Mapping[str, object],
    integrity_details: Mapping[str, object],
    log_details: Mapping[str, object],
    results: Sequence[CheckResult],
    startup_log_sha256: str | None,
) -> dict[str, object]:
    """Cross-bind every allowlisted Build 001 output to its validating snapshot."""

    expected: dict[str, str] = {}
    for projection_name, package_directory in (
        ("first", "package-a"),
        ("second", "package-b"),
    ):
        projection = _required_mapping(
            package_details.get(projection_name),
            name=f"{projection_name} package projection",
        )
        member_hashes = _required_mapping(
            projection.get("candidate_member_sha256"),
            name=f"{projection_name} candidate member hashes",
        )
        if set(member_hashes) != set(_CANDIDATE_MEMBERS) or not all(
            isinstance(value, str) for value in member_hashes.values()
        ):
            raise ValueError("package projection has an incomplete candidate-member hash set")
        candidate_sha256 = projection.get("candidate_sha256")
        receipt_sha256 = projection.get("build_receipt_sha256")
        sandbox_sha256 = projection.get("sandbox_output_sha256")
        if not all(
            isinstance(value, str) for value in (candidate_sha256, receipt_sha256, sandbox_sha256)
        ):
            raise ValueError("package projection has incomplete top-level artifact hashes")
        expected[f"{package_directory}/arc3-kaggle-candidate.zip"] = cast(str, candidate_sha256)
        expected[f"{package_directory}/build-receipt.json"] = cast(str, receipt_sha256)
        expected[f"{package_directory}/offline-sandbox/submission.parquet"] = cast(
            str, sandbox_sha256
        )
        expected.update(
            {
                f"{package_directory}/{relative}": cast(str, digest)
                for relative, digest in member_hashes.items()
            }
        )

    guard_sha256 = guard_details.get("artifact_sha256")
    integrity_sha256 = integrity_details.get("artifact_sha256")
    if not isinstance(guard_sha256, str) or not isinstance(integrity_sha256, str):
        raise ValueError("guard or integrity validation omitted its immutable artifact hash")
    expected["package-only-test-guard.json"] = guard_sha256
    expected["integrity-receipt.json"] = integrity_sha256
    log_hashes = _required_mapping(log_details.get("log_hashes"), name="generated log hashes")
    if not all(
        isinstance(name, str) and isinstance(digest, str) for name, digest in log_hashes.items()
    ):
        raise ValueError("generated log hash projection is invalid")
    expected.update({f"logs/{name}": cast(str, digest) for name, digest in log_hashes.items()})
    if "offline-package-startup.stdout.log" in log_hashes and (
        startup_log_sha256 is None
        or log_hashes.get("offline-package-startup.stdout.log") != startup_log_sha256
    ):
        raise ValueError("startup semantic snapshot differs from the sealed generated log")
    command_results = tuple(result for result in results if result.kind == "command")
    expected_log_paths: set[str] = set()
    for result in command_results:
        expected_stdout = f"logs/{result.check_id}.stdout.log"
        expected_stderr = f"logs/{result.check_id}.stderr.log"
        if (
            result.stdout_log != expected_stdout
            or result.stderr_log != expected_stderr
            or result.stdout_sha256 != log_hashes.get(Path(expected_stdout).name)
            or result.stderr_sha256 != log_hashes.get(Path(expected_stderr).name)
        ):
            raise ValueError("command result log hashes differ from the sealed log snapshots")
        expected_log_paths.update({expected_stdout, expected_stderr})
    if expected_log_paths != {f"logs/{name}" for name in log_hashes}:
        raise ValueError("command results do not cover the exact sealed log set")

    sealed_files = _required_mapping(
        sealed_artifact_set.get("files"), name="sealed package-only artifact hashes"
    )
    if expected != sealed_files:
        raise ValueError("sealed package-only hashes differ from validated immutable snapshots")
    return {
        "linked_file_count": len(expected),
        "linked_files_sha256": sha256_bytes(canonical_json_bytes(expected)),
        "status": "PASS",
    }


def verify_sealed_artifact_set(document: Mapping[str, Any], output_root: Path) -> None:
    """Rehash every declared release artifact and reject missing, extra, or changed files."""

    sealed = _required_mapping(
        document.get("sealed_artifact_set"), name="release sealed artifact set"
    )
    must_be_complete = document.get("status") == "PASS" or (
        document.get("profile") == BUILD001_PACKAGE_ONLY_PROFILE
        and document.get("status") == "BLOCKED_EXTERNAL"
    )
    if must_be_complete and sealed.get("complete") is not True:
        raise ValueError("completed release receipt does not seal a complete artifact set")
    expected_files = sealed.get("files")
    if not isinstance(expected_files, dict) or not all(
        isinstance(name, str) and isinstance(digest, str) for name, digest in expected_files.items()
    ):
        raise ValueError("release sealed artifact file map is invalid")
    expected_allowlist_enforced = sealed.get("expected_allowlist_enforced") is True
    expected_files = (
        frozenset(cast(dict[str, str], expected_files)) if expected_allowlist_enforced else None
    )
    actual = _complete_artifact_set(
        output_root,
        sealed=must_be_complete,
        expected_files=expected_files,
        scan_all_sealed_bytes_for_secrets=(
            sealed.get("all_sealed_raw_bytes_secret_scanned") is True
        ),
    )
    for field in (
        "all_sealed_raw_bytes_secret_scanned",
        "complete",
        "excluded_prefixes",
        "excluded_wrappers",
        "expected_allowlist_enforced",
        "file_count",
        "files",
        "secret_finding_count",
        "set_sha256",
        "total_bytes",
    ):
        if sealed.get(field) != actual.get(field):
            raise ValueError(f"release sealed artifact set {field} mismatch")


def _curated_evidence_bytes(body: Mapping[str, object], raw_receipt_sha256: str) -> bytes:
    checks = body.get("checks")
    check_statuses: dict[str, object] = {}
    if isinstance(checks, list):
        for raw in checks:
            if isinstance(raw, dict) and isinstance(raw.get("id"), str):
                check_statuses[cast(str, raw["id"])] = raw.get("status")
    identity = body.get("identity")
    candidate_commit = identity.get("git_commit") if isinstance(identity, dict) else None
    document: dict[str, object] = {
        "absolute_paths_included": False,
        "candidate_commit": candidate_commit,
        "check_statuses": check_statuses,
        "claim": body.get("claim"),
        "human_gates": body.get("human_gates"),
        "raw_receipt_sha256": raw_receipt_sha256,
        "result_labels": body.get("result_labels"),
        "schema": "arc3.release-candidate-curated-evidence.v0.1",
        "sealed_artifact_set": body.get("sealed_artifact_set"),
        "status": body.get("status"),
        "verification_boundary": body.get("verification_boundary"),
    }
    if body.get("profile") == BUILD001_PACKAGE_ONLY_PROFILE:
        document["measurements"] = body.get("measurements")
        document["profile"] = body.get("profile")
    document["evidence_sha256"] = sha256_bytes(canonical_json_bytes(document))
    return canonical_json_bytes(document)


def _plan_document(
    specs: Sequence[CommandSpec], *, profile: str = BUILD000_PROFILE
) -> dict[str, object]:
    internal_checks = (
        _PACKAGE_ONLY_INTERNAL_CHECKS
        if profile == BUILD001_PACKAGE_ONLY_PROFILE
        else _INTERNAL_CHECKS
    )
    body: dict[str, object] = {
        "checks": [spec.to_dict() for spec in specs],
        "internal_checks": list(internal_checks),
        "schema": PLAN_SCHEMA,
    }
    if profile != BUILD000_PROFILE:
        body["profile"] = profile
    body["plan_sha256"] = sha256_bytes(canonical_json_bytes(body))
    return body


def _overall_status(results: Sequence[CheckResult], *, blocked_is_complete: bool = False) -> str:
    required = [result for result in results if result.required]
    if any(result.status == "FAILED_INFRASTRUCTURE" for result in required):
        return "FAILED_INFRASTRUCTURE"
    if any(result.status != "PASS" for result in required):
        if blocked_is_complete and all(
            result.status in {"BLOCKED_EXTERNAL", "PASS"} for result in required
        ):
            return "BLOCKED_EXTERNAL"
        return "FAILED_MECHANISM"
    return "PASS"


def _receipt_bytes(body: Mapping[str, object]) -> bytes:
    document = dict(body)
    document[RECEIPT_HASH_FIELD] = sha256_bytes(canonical_json_bytes(body))
    return canonical_json_bytes(document)


def _runtime_identity() -> dict[str, object]:
    return {
        "gpu": None,
        "gpu_reason": "the symbolic release verifier neither requires nor queries a GPU",
        "logical_cpu_count": os.cpu_count(),
        "machine": platform.machine() or None,
        "operating_system": platform.platform(),
        "processor": platform.processor() or platform.machine() or None,
        "python_executable": sys.executable,
        "python_version": platform.python_version(),
        "ram_gb": None,
        "ram_reason": "Stage 16 carries measured whole-process memory; this verifier does not infer it",
    }


def verify_release_receipt(path: Path, *, expected_raw: bytes | None = None) -> dict[str, Any]:
    """Parse, self-hash, and require canonical bytes for a release receipt."""

    raw = read_bounded_regular_snapshot(
        root=path.resolve().parent,
        path=path,
        max_bytes=DEFAULT_MAX_CANDIDATE_BYTES,
        path_label=path.name,
    )
    if expected_raw is not None and raw != expected_raw:
        raise ValueError("release verification receipt differs from its exact written bytes")
    document = _verified_self_hashed_bytes(
        raw,
        label=str(path),
        hash_field=RECEIPT_HASH_FIELD,
    )
    if document.get("schema") != SCHEMA:
        raise ValueError("unsupported release verification receipt schema")
    if _receipt_bytes(document) != raw:
        raise ValueError("release verification receipt is not canonical JSON")
    verify_sealed_artifact_set(document, path.resolve().parent)
    return document


def _validate_package_only_integrity(
    path: Path,
    *,
    expected_commit: str,
    expected_archive_sha256: str,
    repository: Path,
) -> tuple[bool, dict[str, object]]:
    raw = read_bounded_regular_snapshot(
        root=path.resolve().parent,
        path=path,
        max_bytes=DEFAULT_MAX_CANDIDATE_BYTES,
        path_label=path.name,
    )
    integrity = _verified_self_hashed_bytes(
        raw,
        label=str(path),
        hash_field=RECEIPT_HASH_FIELD,
    )
    inputs = _required_mapping(integrity.get("inputs"), name="package integrity inputs")
    checks = _required_mapping(integrity.get("checks"), name="package integrity checks")
    assurance = _required_mapping(
        integrity.get("assurance_scope"), name="package integrity assurance scope"
    )
    license_summary = _required_mapping(
        integrity.get("license_summary"), name="package integrity license summary"
    )
    git_identity = _required_mapping(integrity.get("git"), name="package integrity Git identity")
    coverage = _required_mapping(
        integrity.get("production_policy_static_coverage"),
        name="production policy static coverage",
    )
    source_hashes = _required_mapping(
        integrity.get("source_hashes"), name="package integrity source hashes"
    )
    check_passed = all(
        isinstance(checks.get(name), dict) and checks[name].get("passed") is True
        for name in (
            "archive_static",
            "policy_static",
            "secret_scan",
            "source_identity",
            "supply_chain",
        )
    )
    public_boundary = (
        inputs.get("manifest") is None
        and inputs.get("run_state") is None
        and inputs.get("public_identifier_count") == 0
        and inputs.get("public_identifier_mode") == "disabled-package-only"
        and assurance.get("public_identifier_scan")
        == "NOT_EVALUATED_PACKAGE_ONLY_NO_SEMANTIC_MANIFEST_ACCESS"
    )
    license_passed = (
        license_summary.get("first_party_license_status") == "MIT-0"
        and license_summary.get("status") == "PASS"
        and license_summary.get("unknown_or_missing_metadata_count") == 0
        and license_summary.get("installed_version_mismatch_count") == 0
        and license_summary.get("not_evaluated_count") == 0
    )
    reachable_paths = inputs.get("reachable_policy_paths")
    reachable_hashes = integrity.get("reachable_policy_source_hashes")
    declared_candidate_paths = inputs.get("candidate_paths")
    declared_continuity = (
        isinstance(reachable_paths, list)
        and bool(reachable_paths)
        and all(isinstance(item, str) for item in reachable_paths)
        and reachable_paths == sorted(set(reachable_paths))
        and isinstance(reachable_hashes, dict)
        and set(reachable_hashes) == set(reachable_paths)
        and all(
            isinstance(value, str) and re.fullmatch(r"sha256:[0-9a-f]{64}", value)
            for value in reachable_hashes.values()
        )
    )
    candidate_set_passed = False
    recomputed_reachable_paths: list[str] = []
    exact_candidate_snapshots: dict[str, bytes] = {}
    if isinstance(declared_candidate_paths, list) and all(
        isinstance(item, str) for item in declared_candidate_paths
    ):
        from arc3.integrity import discover_reachable_policy_files
        from scripts.check_competition_integrity import package_only_candidate_files

        try:
            independent_candidates = package_only_candidate_files(
                repository,
                expected_commit,
                candidate_snapshots=exact_candidate_snapshots,
            )
            independent_candidate_labels = [
                path.relative_to(repository).as_posix() for path in independent_candidates
            ]
            candidate_set_passed = declared_candidate_paths == independent_candidate_labels
            recomputed_reachable_paths = [
                path.relative_to(repository).as_posix()
                for path in discover_reachable_policy_files(
                    repository,
                    candidate_files=independent_candidates,
                    entry_points=_PRODUCTION_POLICY_ENTRY_POINTS,
                    candidate_snapshots=exact_candidate_snapshots,
                )
            ]
        except (OSError, ValueError):
            candidate_set_passed = False
            recomputed_reachable_paths = []
            exact_candidate_snapshots = {}
    recomputed_hashes: dict[str, str] = {}
    if declared_continuity:
        assert isinstance(reachable_paths, list)
        try:
            recomputed_hashes = {
                relative: sha256_bytes(exact_candidate_snapshots[relative])
                for relative in cast(list[str], reachable_paths)
            }
        except KeyError:
            recomputed_hashes = {}
    expected_snapshot_identity = sha256_bytes(
        canonical_json_bytes(
            {label: sha256_bytes(raw) for label, raw in sorted(exact_candidate_snapshots.items())}
        )
    )
    source_snapshot_passed = (
        bool(exact_candidate_snapshots)
        and inputs.get("candidate_snapshot_file_count") == len(exact_candidate_snapshots)
        and inputs.get("candidate_snapshot_total_bytes")
        == sum(len(raw) for raw in exact_candidate_snapshots.values())
        and inputs.get("candidate_snapshot_sha256") == expected_snapshot_identity
    )
    coverage_passed = (
        declared_continuity
        and isinstance(reachable_paths, list)
        and isinstance(reachable_hashes, dict)
        and inputs.get("entry_points") == list(_PRODUCTION_POLICY_ENTRY_POINTS)
        and all(entry in reachable_paths for entry in _PRODUCTION_POLICY_ENTRY_POINTS)
        and candidate_set_passed
        and source_snapshot_passed
        and reachable_paths == recomputed_reachable_paths
        and coverage
        == {
            "algorithm": "static-first-party-import-closure-v0.1",
            "entry_points": list(_PRODUCTION_POLICY_ENTRY_POINTS),
            "entry_points_reached": list(_PRODUCTION_POLICY_ENTRY_POINTS),
            "limitations": (
                "Static first-party import reachability does not prove runtime dynamic-import "
                "or native-extension containment."
            ),
            "policy_scan_covers_reachable_paths": True,
            "reachable_file_count": len(reachable_paths),
            "reachable_paths_hashed": True,
            "status": "PASS",
        }
        and recomputed_hashes == reachable_hashes
        and all(source_hashes.get(key) == value for key, value in recomputed_hashes.items())
    )
    continuity_passed = declared_continuity and coverage_passed
    source_identity_passed = (
        git_identity.get("commit") == expected_commit
        and git_identity.get("dirty_worktree") is False
    )
    archive_label = "@supplied-archive/0000/arc3-kaggle-candidate.zip"
    archive_identity_passed = (
        inputs.get("archive_count") == 1
        and inputs.get("archive_paths") == [archive_label]
        and source_hashes.get(archive_label) == expected_archive_sha256
    )
    passed = (
        integrity.get("passed") is False
        and integrity.get("package_only_passed") is True
        and integrity.get("integrity_scope") == "package-only-no-public-identifiers"
        and integrity.get("full_competition_integrity_status") == "NOT_EVALUATED_PUBLIC_IDENTIFIERS"
        and integrity.get("finding_counts") == {"blocking": 0, "total": 0, "warnings": 0}
        and check_passed
        and public_boundary
        and license_passed
        and continuity_passed
        and source_identity_passed
        and archive_identity_passed
    )
    details: dict[str, object] = {
        "artifact_sha256": sha256_bytes(raw),
        "archive_identity_passed": archive_identity_passed,
        "archive_sha256": source_hashes.get(archive_label),
        "checks_passed": check_passed,
        "candidate_set_passed": candidate_set_passed,
        "finding_counts": cast(object, integrity.get("finding_counts")),
        "first_party_license_status": cast(
            object, license_summary.get("first_party_license_status")
        ),
        "license_inventory_passed": license_passed,
        "package_only_passed": integrity.get("package_only_passed") is True,
        "passed": passed,
        "policy_continuity_passed": continuity_passed,
        "production_policy_static_coverage": cast(object, coverage),
        "public_semantic_boundary_passed": public_boundary,
        "reachable_policy_source_hashes": cast(object, reachable_hashes),
        "recomputed_reachable_policy_paths": recomputed_reachable_paths,
        "schema": cast(object, integrity.get("schema")),
        "source_identity_passed": source_identity_passed,
        "source_snapshot_passed": source_snapshot_passed,
    }
    for key in ("LICENSE", "THIRD_PARTY_NOTICES.md", "pyproject.toml", "uv.lock"):
        value = source_hashes.get(key)
        if isinstance(value, str):
            details[f"source_hash:{key}"] = value
    return passed, details


def _validate_package_test_guard(
    path: Path,
    *,
    repository: Path,
    expected_commit: str,
) -> dict[str, object]:
    raw = read_bounded_regular_snapshot(
        root=path.resolve().parent,
        path=path,
        max_bytes=DEFAULT_MAX_CANDIDATE_BYTES,
        path_label=path.name,
    )
    guard = _verified_self_hashed_bytes(
        raw,
        label=str(path),
        hash_field=RECEIPT_HASH_FIELD,
    )
    expected_selection = build001_test_selection(
        repository,
        expected_commit=expected_commit,
    ).to_dict()
    exact_selection = all(
        guard.get(field) == expected_selection[field]
        for field in (
            "all_test_file_count",
            "all_test_files",
            "all_test_files_sha256",
            "boundary_exclusion_reasons",
            "excluded_boundary_tests",
            "excluded_process_capable_tests",
            "selected_test_file_count",
            "selected_test_files",
            "selected_test_files_sha256",
            "source_closure_exact_git_commit_bound",
            "source_closure_file_count",
            "source_closure_files",
            "source_closure_records",
            "source_closure_sha256",
            "source_commit",
            "source_index_stage_records",
            "source_index_stage_sha256",
            "source_index_tags",
            "source_index_tags_sha256",
        )
    )
    expected_kernel_paths = ["/proc/self/status"] if sys.platform.startswith("linux") else []
    workflow_relative = ".github/workflows/ci.yml"
    workflow_blob = _git_bytes(repository, "show", f"{expected_commit}:{workflow_relative}")
    workflow_snapshot = read_bounded_regular_snapshot(
        root=repository,
        path=repository / workflow_relative,
        max_bytes=DEFAULT_MAX_CANDIDATE_BYTES,
        path_label=workflow_relative,
    )
    if workflow_snapshot != workflow_blob:
        raise ValueError("ordinary CI workflow bytes differ from the expected Git blob")
    try:
        workflow = workflow_snapshot.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ValueError("ordinary CI workflow is not UTF-8") from error
    ordinary_ci_retains_full_suite = (
        f"run: {ORDINARY_CI_FULL_SUITE_COMMAND}" in workflow
        and "scripts.package_only_pytest" not in workflow
        and "--ignore" not in workflow
    )
    collected_files = guard.get("collected_test_files")
    selected_files = expected_selection["selected_test_files"]
    if (
        guard.get("schema") != PACKAGE_ONLY_PYTEST_SCHEMA
        or guard.get("status") != "PASS"
        or guard.get("attempt_count") != 0
        or guard.get("attempts") != []
        or guard.get("attempt_log_sha256") != sha256_bytes(b"")
        or guard.get("pytest_exit_code") != 0
        or guard.get("runner_failure") is not None
        or guard.get("canonical_paths") is not True
        or guard.get("allow_root_ancestor_directory_metadata_allowed") is not True
        or guard.get("child_processes_denied") is not True
        or guard.get("claim_scope") != PACKAGE_ONLY_TEST_CLAIM_SCOPE
        or guard.get("external_paths_default_denied") is not True
        or guard.get("framework_writable_state") != "isolated-under-allowed-guard-parent"
        or not isinstance(guard.get("sys_path_entries_outside_allowed_roots_removed"), int)
        or cast(int, guard["sys_path_entries_outside_allowed_roots_removed"]) < 0
        or guard.get("pytest_rootdir_forced") is not True
        or guard.get("selection_policy")
        != "exact-git-blob-execution-closure-v0.4-plus-runtime-boundary-denial"
        or guard.get("source_projection_matches_after_tests") is not True
        or guard.get("source_closure_exact_git_commit_bound") is not True
        or guard.get("source_commit") != expected_commit
        or guard.get("collection_matches_selected_files") is not True
        or collected_files != selected_files
        or not isinstance(guard.get("collected_test_count"), int)
        or cast(int, guard["collected_test_count"]) <= 0
        or not exact_selection
        or guard.get("kernel_telemetry_paths") != expected_kernel_paths
        or guard.get("kernel_telemetry_read_only") is not True
        or not isinstance(guard.get("kernel_telemetry_read_count"), int)
        or cast(int, guard["kernel_telemetry_read_count"]) < 0
        or guard.get("ordinary_ci_full_suite_command") != ORDINARY_CI_FULL_SUITE_COMMAND
        or not ordinary_ci_retains_full_suite
        or guard.get("protected_directories") != ["artifacts", "docs/evaluation"]
        or guard.get("protected_files")
        != [
            "docs/ledger/build-001-run-state.json",
            "docs/ledger/run-state.json",
            "guard-attempt-log",
            "guard-receipt",
        ]
    ):
        raise ValueError("package-only pytest guard did not prove its exact test/path boundary")
    return {
        "artifact_sha256": sha256_bytes(raw),
        "all_test_file_count": cast(object, guard.get("all_test_file_count")),
        "all_test_files_sha256": cast(object, guard.get("all_test_files_sha256")),
        "attempt_count": 0,
        "attempt_log_sha256": cast(object, guard.get("attempt_log_sha256")),
        "boundary_exclusion_count": len(BUILD001_BOUNDARY_EXCLUSIONS),
        "canonical_paths": True,
        "child_processes_denied": True,
        "claim_scope": cast(object, guard.get("claim_scope")),
        "collected_test_count": cast(object, guard.get("collected_test_count")),
        "excluded_process_capable_test_count": len(
            cast(list[object], guard["excluded_process_capable_tests"])
        ),
        "external_paths_default_denied": True,
        "kernel_telemetry_paths": expected_kernel_paths,
        "kernel_telemetry_read_count": cast(object, guard.get("kernel_telemetry_read_count")),
        "ordinary_ci_retains_full_suite": True,
        "schema": cast(object, guard.get("schema")),
        "selected_test_file_count": cast(object, guard.get("selected_test_file_count")),
        "selected_test_files_sha256": cast(object, guard.get("selected_test_files_sha256")),
        "source_closure_file_count": cast(object, guard.get("source_closure_file_count")),
        "source_closure_sha256": cast(object, guard.get("source_closure_sha256")),
        "source_commit": expected_commit,
        "source_index_stage_sha256": cast(object, guard.get("source_index_stage_sha256")),
        "source_index_tags_sha256": cast(object, guard.get("source_index_tags_sha256")),
        "source_projection_matches_after_tests": True,
        "status": cast(object, guard.get("status")),
    }


def _package_runtime_measurements(
    *,
    results: Sequence[CheckResult],
    package_details: Mapping[str, object],
    startup: Mapping[str, Any],
) -> tuple[bool, dict[str, object]]:
    by_id = {result.check_id: result for result in results}
    first = _required_mapping(package_details.get("first"), name="first package projection")
    second = _required_mapping(package_details.get("second"), name="second package projection")
    command_wall_seconds = {
        result.check_id: result.duration_seconds
        for result in results
        if result.kind == "command" and result.duration_seconds is not None
    }
    command_peak_rss_bytes = {
        result.check_id: result.details.get("peak_rss_bytes")
        for result in results
        if result.kind == "command"
    }
    measured_ids = ("offline-package-a", "offline-package-b", "offline-package-startup")
    rss_available = all(
        isinstance(command_peak_rss_bytes.get(check_id), int)
        and not isinstance(command_peak_rss_bytes.get(check_id), bool)
        and cast(int, command_peak_rss_bytes[check_id]) > 0
        for check_id in measured_ids
    )
    rss_tree_scoped = all(
        check_id in by_id
        and by_id[check_id].details.get("rss_measurement_scope")
        == (
            "sampled aggregate resident bytes across the supervised process tree; "
            "this is measurement, not a hard memory limit"
        )
        and by_id[check_id].details.get("process_tree_cleanup_succeeded") is True
        and isinstance(by_id[check_id].details.get("rss_sampling_max_observed_process_count"), int)
        and cast(int, by_id[check_id].details["rss_sampling_max_observed_process_count"]) >= 1
        for check_id in measured_ids
    )
    startup_passed = (
        startup.get("schema") == "arc3.package-startup-probe.v0.2"
        and startup.get("status") == "PASS"
        and startup.get("network_attempts") == 0
        and startup.get("network_attempt_events") == []
        and startup.get("network_enforcement") == "python-audit-hook-socket-events"
        and startup.get("process_launch_attempts") == 0
        and startup.get("process_launch_attempt_events") == []
        and startup.get("process_launch_enforcement") == "python-audit-hook-process-events"
        and startup.get("payload_sha256") == first.get("payload_sha256")
        and all(
            isinstance(startup.get(field), (int, float))
            and not isinstance(startup.get(field), bool)
            and cast(float, startup[field]) >= 0
            for field in ("import_seconds", "instantiate_seconds", "total_seconds")
        )
    )
    package_values_equal = all(
        first.get(field) == second.get(field)
        for field in ("archive_size_bytes", "runtime_wheel_count", "candidate_sha256")
    )
    required_commands_passed = all(
        check_id in by_id and by_id[check_id].status == "PASS" for check_id in measured_ids
    )
    passed = (
        rss_available
        and rss_tree_scoped
        and startup_passed
        and package_values_equal
        and required_commands_passed
    )
    return passed, {
        "archive_size_bytes": first.get("archive_size_bytes"),
        "command_peak_rss_bytes": command_peak_rss_bytes,
        "command_wall_seconds": command_wall_seconds,
        "package_build_peak_rss_bytes": {
            check_id: command_peak_rss_bytes.get(check_id)
            for check_id in ("offline-package-a", "offline-package-b")
        },
        "package_build_wall_seconds": {
            check_id: command_wall_seconds.get(check_id)
            for check_id in ("offline-package-a", "offline-package-b")
        },
        "package_values_equal": package_values_equal,
        "rss_available": rss_available,
        "rss_scope": (
            "sampled aggregate resident bytes across supervised process trees; measurement only, "
            "not a hard memory limit"
        ),
        "rss_tree_scoped": rss_tree_scoped,
        "runtime_wheel_count": first.get("runtime_wheel_count"),
        "startup": dict(startup),
        "startup_passed": startup_passed,
    }


def _private_kaggle_surface_boundary() -> tuple[dict[str, object], str]:
    """Describe unprovided private inputs without asserting their host availability."""

    details: dict[str, object] = {
        "access_attempted": False,
        "availability_assessment": "NOT_ASSESSED",
        "compatibility_status": "NOT_VERIFIED",
        "exact_private_gateway": "NOT_PROVIDED_TO_VERIFIER",
        "exact_private_platform_agents_input": "NOT_PROVIDED_TO_VERIFIER",
        "exact_private_scorer": "NOT_PROVIDED_TO_VERIFIER",
        "exact_private_wheel_inventory": "NOT_PROVIDED_TO_VERIFIER",
        "official_submission_performed": False,
        "status": "BLOCKED_EXTERNAL",
    }
    reason = (
        "exact private Kaggle wheels, platform Agents input, gateway, and scorer were not "
        "provided to this verifier; availability was not assessed, and local gateway-shaped "
        "fixtures cannot establish private compatibility"
    )
    return details, reason


def _run_package_only_verification(
    *,
    repository: Path,
    output_root: Path,
    transient_root: Path,
    expected_commit: str,
    uv_command: tuple[str, ...],
) -> dict[str, object]:
    """Run only Build 001 offline packaging surfaces and preserve the external block."""

    started_at = _utc_now()
    identity = repository_identity(repository, expected_commit)
    prepare_fresh_output_root(repository, output_root)
    prepare_fresh_transient_root(repository, output_root, transient_root)
    interpreter_identity = interpreter_source_identity(repository, transient_root)
    identity["interpreter"] = interpreter_identity
    source_identity = source_lock_identity(repository, expected_commit)
    raw_specs = build_plan(
        repository=repository,
        output_root=output_root,
        transient_root=transient_root,
        expectation=None,
        uv_command=uv_command,
        official_environments=None,
        profile=BUILD001_PACKAGE_ONLY_PROFILE,
    )
    specs = tuple(_replace_candidate_commit(spec, expected_commit) for spec in raw_specs)
    _validate_package_only_plan(
        specs,
        repository=repository,
        output_root=output_root,
    )
    results: list[CheckResult] = [
        internal_result(
            "interpreter-source-identity",
            "source-identity",
            status="PASS",
            details=interpreter_identity,
        ),
        internal_result(
            "source-lock-identity",
            "source-identity",
            status="PASS",
            details=source_identity,
        ),
    ]
    prior: dict[str, CheckResult] = {result.check_id: result for result in results}
    for spec in specs:
        result = run_command(
            spec,
            repository=repository,
            output_root=output_root,
            transient_root=transient_root,
            prior=prior,
        )
        results.append(result)
        prior[result.check_id] = result

    guard_details: dict[str, object] = {}
    if prior["package-safe-test-suite"].status == "PASS":
        try:
            guard_details = _validate_package_test_guard(
                output_root / "package-only-test-guard.json",
                repository=repository,
                expected_commit=expected_commit,
            )
            guard_result = internal_result(
                "package-test-guard-validation",
                "tests",
                status="PASS",
                details=guard_details,
            )
        except (OSError, ValueError) as error:
            guard_result = internal_result(
                "package-test-guard-validation",
                "tests",
                status="FAILED_INFRASTRUCTURE",
                reason=f"package-only pytest guard validation failed: {error}",
            )
    else:
        guard_result = internal_result(
            "package-test-guard-validation",
            "tests",
            status="FAILED_MECHANISM",
            reason="package-safe test command did not pass",
        )
    results.append(guard_result)
    prior[guard_result.check_id] = guard_result

    package_details: dict[str, object] = {}
    if prior["offline-package-a"].status == "PASS" and prior["offline-package-b"].status == "PASS":
        try:
            equal, package_details = compare_packages(
                output_root / "package-a" / "build-receipt.json",
                output_root / "package-b" / "build-receipt.json",
                expected_commit=expected_commit,
                include_runtime_metrics=True,
                repository=repository,
            )
            package_result = internal_result(
                "offline-package-determinism",
                "offline-package",
                status="PASS" if equal else "FAILED_MECHANISM",
                reason=None if equal else "two fresh package builds have different identities",
                details=package_details,
            )
        except (OSError, ValueError) as error:
            package_result = internal_result(
                "offline-package-determinism",
                "offline-package",
                status="FAILED_INFRASTRUCTURE",
                reason=f"package receipt comparison failed: {error}",
            )
    else:
        package_result = internal_result(
            "offline-package-determinism",
            "offline-package",
            status="FAILED_MECHANISM",
            reason="one or both offline package builds failed",
        )
    results.append(package_result)
    prior[package_result.check_id] = package_result

    integrity_details: dict[str, object] = {}
    verified_license_status: str | None = None
    verified_license_sha256: str | None = None
    if prior["package-integrity"].status == "PASS":
        try:
            first_projection = _required_mapping(
                package_details.get("first"), name="first package projection"
            )
            expected_archive_sha256 = first_projection.get("candidate_sha256")
            if not isinstance(expected_archive_sha256, str):
                raise ValueError("first package projection has no candidate SHA-256")
            integrity_passed, integrity_details = _validate_package_only_integrity(
                output_root / "integrity-receipt.json",
                expected_commit=expected_commit,
                expected_archive_sha256=expected_archive_sha256,
                repository=repository,
            )
            raw_status = integrity_details.get("first_party_license_status")
            if isinstance(raw_status, str):
                verified_license_status = raw_status
            raw_hash = integrity_details.get("source_hash:LICENSE")
            if isinstance(raw_hash, str):
                verified_license_sha256 = raw_hash
            integrity_result = internal_result(
                "integrity-receipt-validation",
                "integrity",
                status="PASS" if integrity_passed else "FAILED_MECHANISM",
                reason=None if integrity_passed else "package-only integrity receipt did not pass",
                details=integrity_details,
            )
        except (OSError, ValueError) as error:
            integrity_result = internal_result(
                "integrity-receipt-validation",
                "integrity",
                status="FAILED_INFRASTRUCTURE",
                reason=f"package-only integrity receipt validation failed: {error}",
            )
    else:
        integrity_result = internal_result(
            "integrity-receipt-validation",
            "integrity",
            status="FAILED_MECHANISM",
            reason="package-only integrity command did not pass",
        )
    results.append(integrity_result)
    prior[integrity_result.check_id] = integrity_result

    startup: dict[str, Any] = {}
    startup_log_sha256: str | None = None
    if prior["offline-package-startup"].status == "PASS":
        try:
            startup_log_path = output_root / "logs" / "offline-package-startup.stdout.log"
            startup_log_snapshot = read_bounded_regular_snapshot(
                root=output_root,
                path=startup_log_path,
                max_bytes=DEFAULT_MAX_CANDIDATE_BYTES,
                path_label="logs/offline-package-startup.stdout.log",
            )
            startup_log_sha256 = sha256_bytes(startup_log_snapshot)
            startup = _last_json_log_bytes(
                startup_log_snapshot,
                label=str(startup_log_path),
            )
        except (OSError, ValueError) as error:
            startup = {"interpretation_error": str(error)}
    if package_result.status == "PASS" and prior["offline-package-startup"].status == "PASS":
        try:
            metrics_passed, measurements = _package_runtime_measurements(
                results=results,
                package_details=package_details,
                startup=startup,
            )
            metrics_result = internal_result(
                "package-runtime-metrics",
                "offline-package",
                status="PASS" if metrics_passed else "FAILED_INFRASTRUCTURE",
                reason=None
                if metrics_passed
                else "required package runtime metrics are incomplete",
                details=measurements,
            )
        except ValueError as error:
            measurements = {"interpretation_error": str(error)}
            metrics_result = internal_result(
                "package-runtime-metrics",
                "offline-package",
                status="FAILED_INFRASTRUCTURE",
                reason=f"package runtime metric validation failed: {error}",
                details=measurements,
            )
    else:
        measurements = {}
        metrics_result = internal_result(
            "package-runtime-metrics",
            "offline-package",
            status="FAILED_MECHANISM",
            reason="package determinism or startup command did not pass",
        )
    results.append(metrics_result)
    prior[metrics_result.check_id] = metrics_result

    private_surfaces, private_reason = _private_kaggle_surface_boundary()
    private_result = internal_result(
        "private-kaggle-surfaces",
        "external-boundary",
        status="BLOCKED_EXTERNAL",
        reason=private_reason,
        details=private_surfaces,
    )
    results.append(private_result)
    prior[private_result.check_id] = private_result

    try:
        final_identity = repository_identity(repository, expected_commit)
        final_clean = internal_result(
            "repository-clean-after",
            "source-identity",
            status="PASS",
            details=final_identity,
        )
    except ValueError as error:
        final_clean = internal_result(
            "repository-clean-after",
            "source-identity",
            status="FAILED_INFRASTRUCTURE",
            reason=str(error),
        )
    results.append(final_clean)
    logs_passed, log_details = scan_generated_logs(output_root, results)
    log_scan = internal_result(
        "generated-log-secret-scan",
        "secret-scan",
        status="PASS" if logs_passed else "FAILED_MECHANISM",
        reason=None if logs_passed else "generated output retained or redacted a secret value",
        details=log_details,
    )
    results.append(log_scan)

    status = _overall_status(results, blocked_is_complete=True)
    exact_expected_files = (
        _package_only_expected_artifact_files(specs)
        if status in {"BLOCKED_EXTERNAL", "PASS"}
        else None
    )
    sealed_artifact_set = _complete_artifact_set(
        output_root,
        sealed=status in {"BLOCKED_EXTERNAL", "PASS"},
        expected_files=exact_expected_files,
        scan_all_sealed_bytes_for_secrets=exact_expected_files is not None,
    )
    seal_links = (
        _validate_package_only_seal_links(
            sealed_artifact_set,
            package_details=package_details,
            guard_details=guard_details,
            integrity_details=integrity_details,
            log_details=log_details,
            results=results,
            startup_log_sha256=startup_log_sha256,
        )
        if exact_expected_files is not None
        else {"status": "NOT_APPLICABLE_FAILED_RUN"}
    )
    seal_result = internal_result(
        "sealed-artifact-set",
        "artifacts",
        status="PASS",
        details={
            "complete": sealed_artifact_set["complete"],
            "file_count": sealed_artifact_set["file_count"],
            "set_sha256": sealed_artifact_set["set_sha256"],
            "snapshot_links": seal_links,
            "total_bytes": sealed_artifact_set["total_bytes"],
        },
    )
    results.append(seal_result)
    body: dict[str, object] = {
        "artifact_hashes": sealed_artifact_set["files"],
        "checks": [result.to_dict() for result in results],
        "claim": "NO_GENERALIZATION_CLAIM",
        "completed_at": _utc_now(),
        "human_gates": {
            "license_granted": verified_license_status == "MIT-0",
            "license_expression": verified_license_status,
            "license_sha256": verified_license_sha256,
            "official_submission_performed": False,
            "terms_accepted_by_verifier": False,
        },
        "identity": identity,
        "measurements": measurements,
        "output_root": str(output_root),
        "plan": _plan_document(specs, profile=BUILD001_PACKAGE_ONLY_PROFILE),
        "private_kaggle_surfaces": private_surfaces,
        "profile": BUILD001_PACKAGE_ONLY_PROFILE,
        "result_labels": ["synthetic"],
        "runtime": _runtime_identity(),
        "schema": SCHEMA,
        "sealed_artifact_set": sealed_artifact_set,
        "started_at": started_at,
        "status": status,
        "transient_root": {
            "path": str(transient_root),
            "role": "unsealed isolated temporary, cache, home, and test state",
            "sealed": False,
        },
        "verification_boundary": {
            "command_environment": (
                "strict host-variable allowlist; isolated out-of-tree HOME, USERPROFILE, "
                "temporary, and caches"
            ),
            "dependency_resolution": "locked uv sync and lock check both run offline",
            "game_source_inspected": False,
            "official_inventory_planned": False,
            "public_manifest_semantically_accessed": False,
            "public_or_holdout_gameplay_attempted": False,
            "sandbox": "offline gateway-shaped fixture only",
        },
    }
    receipt_path = output_root / "release-verification-receipt.json"
    receipt_raw = _receipt_bytes(body)
    write_bytes_atomic(receipt_path, receipt_raw)
    verify_release_receipt(receipt_path, expected_raw=receipt_raw)
    curated_path = output_root / "release-verification-evidence.json"
    curated_raw = _curated_evidence_bytes(body, sha256_bytes(receipt_raw))
    write_bytes_atomic(curated_path, curated_raw)
    verify_release_receipt(receipt_path, expected_raw=receipt_raw)
    return body


def run_release_verification(
    *,
    repository: Path,
    output_root: Path,
    transient_root: Path,
    expected_commit: str,
    expectation_path: Path,
    uv_command: tuple[str, ...],
    official_environments: Path | None,
    profile: str = BUILD000_PROFILE,
) -> dict[str, object]:
    """Run every achievable Stage 18 check and write one sealed receipt."""

    repository = repository.resolve()
    output_root = output_root.resolve()
    transient_root = transient_root.resolve()
    if profile == BUILD001_PACKAGE_ONLY_PROFILE:
        return _run_package_only_verification(
            repository=repository,
            output_root=output_root,
            transient_root=transient_root,
            expected_commit=expected_commit,
            uv_command=uv_command,
        )
    if profile != BUILD000_PROFILE:
        raise ValueError(f"unsupported release-verification profile: {profile}")
    expectation_path = expectation_path.resolve()
    started_at = _utc_now()
    identity = repository_identity(repository, expected_commit)
    prepare_fresh_output_root(repository, output_root)
    prepare_fresh_transient_root(repository, output_root, transient_root)
    interpreter_identity = interpreter_source_identity(repository, transient_root)
    identity["interpreter"] = interpreter_identity
    expectation = load_benchmark_expectation(expectation_path)
    benchmark_basis = benchmark_basis_identity(expectation, repository, expected_commit)
    raw_specs = build_plan(
        repository=repository,
        output_root=output_root,
        transient_root=transient_root,
        expectation=expectation,
        uv_command=uv_command,
        official_environments=official_environments,
    )
    specs = tuple(_replace_candidate_commit(spec, expected_commit) for spec in raw_specs)
    by_id = {spec.check_id: spec for spec in specs}
    results: list[CheckResult] = [
        internal_result(
            "interpreter-source-identity",
            "source-identity",
            status="PASS",
            details=interpreter_identity,
        ),
        internal_result(
            "benchmark-basis-validation",
            "synthetic",
            status="PASS",
            details=benchmark_basis,
        ),
    ]
    prior: dict[str, CheckResult] = {result.check_id: result for result in results}

    core_ids = (
        "dependency-lock",
        "ruff-lint",
        "ruff-format",
        "mypy-strict",
        "full-test-suite",
        "trace-replay-tamper",
        "synthetic-benchmark",
        "synthetic-artifact-verification",
        "offline-package-a",
        "offline-package-b",
        "competition-integrity",
        "official-inventory",
    )
    for check_id in core_ids:
        result = run_command(
            by_id[check_id],
            repository=repository,
            output_root=output_root,
            transient_root=transient_root,
            prior=prior,
        )
        results.append(result)
        prior[check_id] = result

    evaluation_directory = output_root / "evaluations" / "stage18-benchmark-reproduction"
    if prior["synthetic-artifact-verification"].status == "PASS":
        try:
            equal, details = compare_benchmark(expectation, evaluation_directory)
            benchmark_result = internal_result(
                "benchmark-semantic-reproduction",
                "synthetic",
                status="PASS" if equal else "FAILED_MECHANISM",
                reason=None if equal else "deterministic benchmark projection changed",
                details=details,
            )
        except (OSError, ValueError) as error:
            benchmark_result = internal_result(
                "benchmark-semantic-reproduction",
                "synthetic",
                status="FAILED_INFRASTRUCTURE",
                reason=f"benchmark comparison failed: {error}",
            )
    else:
        benchmark_result = internal_result(
            "benchmark-semantic-reproduction",
            "synthetic",
            status="FAILED_MECHANISM",
            reason="synthetic artifact verification did not pass",
        )
    results.append(benchmark_result)
    prior[benchmark_result.check_id] = benchmark_result

    if prior["offline-package-a"].status == "PASS" and prior["offline-package-b"].status == "PASS":
        try:
            equal, details = compare_packages(
                output_root / "package-a" / "build-receipt.json",
                output_root / "package-b" / "build-receipt.json",
                expected_commit=expected_commit,
                repository=repository,
            )
            package_result = internal_result(
                "offline-package-determinism",
                "offline-package",
                status="PASS" if equal else "FAILED_MECHANISM",
                reason=None if equal else "two fresh package builds have different identities",
                details=details,
            )
        except (OSError, ValueError) as error:
            package_result = internal_result(
                "offline-package-determinism",
                "offline-package",
                status="FAILED_INFRASTRUCTURE",
                reason=f"package receipt comparison failed: {error}",
            )
    else:
        package_result = internal_result(
            "offline-package-determinism",
            "offline-package",
            status="FAILED_MECHANISM",
            reason="one or both offline package builds failed",
        )
    results.append(package_result)
    prior[package_result.check_id] = package_result

    verified_license_status: str | None = None
    verified_license_sha256: str | None = None
    if prior["competition-integrity"].status == "PASS":
        try:
            integrity = _verified_self_hashed_object(
                output_root / "integrity-receipt.json", hash_field=RECEIPT_HASH_FIELD
            )
            integrity_passed = integrity.get("passed") is True
            license_summary = integrity.get("license_summary")
            if isinstance(license_summary, dict):
                raw_license_status = license_summary.get("first_party_license_status")
                if isinstance(raw_license_status, str):
                    verified_license_status = raw_license_status
            source_hashes = integrity.get("source_hashes")
            if isinstance(source_hashes, dict):
                raw_license_sha256 = source_hashes.get("LICENSE")
                if isinstance(raw_license_sha256, str):
                    verified_license_sha256 = raw_license_sha256
            integrity_result = internal_result(
                "integrity-receipt-validation",
                "integrity",
                status="PASS" if integrity_passed else "FAILED_MECHANISM",
                reason=None if integrity_passed else "integrity receipt did not pass",
                details={
                    "finding_count": integrity.get("finding_count"),
                    "first_party_license_status": verified_license_status,
                    "first_party_license_sha256": verified_license_sha256,
                    "passed": integrity.get("passed"),
                    "schema": integrity.get("schema"),
                },
            )
        except (OSError, ValueError) as error:
            integrity_result = internal_result(
                "integrity-receipt-validation",
                "integrity",
                status="FAILED_INFRASTRUCTURE",
                reason=f"integrity receipt validation failed: {error}",
            )
    else:
        integrity_result = internal_result(
            "integrity-receipt-validation",
            "integrity",
            status="FAILED_MECHANISM",
            reason="competition integrity command did not pass",
        )
    results.append(integrity_result)
    prior[integrity_result.check_id] = integrity_result

    official_available = False
    official_details: dict[str, object] = {}
    availability_error: str | None = None
    if prior["official-inventory"].status == "PASS":
        try:
            inventory_log = output_root / "logs" / "official-inventory.stdout.log"
            inventory = _last_json_log(inventory_log)
            official_available, official_details = official_smoke_available(
                inventory,
                repository / "docs/evaluation/public-game-partitions.v0.1.json",
            )
        except (OSError, ValueError) as error:
            availability_error = str(error)
            official_details = {"inventory_interpretation_error": str(error)}
    else:
        availability_error = "official inventory command did not pass"
    availability_result = internal_result(
        "official-availability",
        "official-smoke",
        status="PASS" if availability_error is None else "FAILED_INFRASTRUCTURE",
        reason=availability_error,
        details=official_details,
    )
    results.append(availability_result)
    prior[availability_result.check_id] = availability_result
    if official_available:
        official_result = run_command(
            replace(by_id["official-smoke"], required=True),
            repository=repository,
            output_root=output_root,
            transient_root=transient_root,
            prior=prior,
        )
        results.append(official_result)
        prior[official_result.check_id] = official_result
        official_verify = run_command(
            replace(by_id["official-artifact-verification"], required=True),
            repository=repository,
            output_root=output_root,
            transient_root=transient_root,
            prior=prior,
        )
        results.append(official_verify)
        prior[official_verify.check_id] = official_verify
    else:
        reason = (
            "the frozen official smoke assets are not all present; no acquisition or gameplay "
            "was attempted"
            if prior["official-inventory"].status == "PASS"
            else "official inventory failed before local availability could be established"
        )
        for check_id in ("official-smoke", "official-artifact-verification"):
            blocked = _blocked_result(by_id[check_id], reason, status="BLOCKED_EXTERNAL")
            blocked = replace(blocked, details={**blocked.details, **official_details})
            results.append(blocked)
            prior[check_id] = blocked

    try:
        final_identity = repository_identity(repository, expected_commit)
        final_clean = internal_result(
            "repository-clean-after",
            "source-identity",
            status="PASS",
            details=final_identity,
        )
    except ValueError as error:
        final_clean = internal_result(
            "repository-clean-after",
            "source-identity",
            status="FAILED_INFRASTRUCTURE",
            reason=str(error),
        )
    results.append(final_clean)

    logs_passed, log_details = scan_generated_logs(output_root, results)
    log_scan = internal_result(
        "generated-log-secret-scan",
        "secret-scan",
        status="PASS" if logs_passed else "FAILED_MECHANISM",
        reason=None
        if logs_passed
        else "generated output required redaction or retained a secret pattern",
        details=log_details,
    )
    results.append(log_scan)

    result_labels = ["synthetic"]
    if official_available:
        result_labels.append("local-public")
    plan = _plan_document(specs)
    completed_at = _utc_now()
    status = _overall_status(results)
    sealed_artifact_set = _complete_artifact_set(output_root, sealed=status == "PASS")
    seal_result = internal_result(
        "sealed-artifact-set",
        "artifacts",
        status="PASS",
        details={
            "complete": sealed_artifact_set["complete"],
            "file_count": sealed_artifact_set["file_count"],
            "set_sha256": sealed_artifact_set["set_sha256"],
            "total_bytes": sealed_artifact_set["total_bytes"],
        },
    )
    results.append(seal_result)
    body: dict[str, object] = {
        "artifact_hashes": sealed_artifact_set["files"],
        "checks": [result.to_dict() for result in results],
        "claim": "NO_GENERALIZATION_CLAIM",
        "completed_at": completed_at,
        "human_gates": {
            "license_granted": verified_license_status == "MIT-0",
            "license_expression": verified_license_status,
            "license_sha256": verified_license_sha256,
            "official_submission_performed": False,
            "terms_accepted_by_verifier": False,
        },
        "identity": identity,
        "official_smoke": {
            "availability": official_details,
            "available": official_available,
            "surface": "local-public" if official_available else None,
            "status": prior["official-smoke"].status,
        },
        "output_root": str(output_root),
        "transient_root": {
            "path": str(transient_root),
            "role": "unsealed isolated temporary, cache, home, and test state",
            "sealed": False,
        },
        "plan": plan,
        "result_labels": result_labels,
        "runtime": _runtime_identity(),
        "schema": SCHEMA,
        "sealed_artifact_set": sealed_artifact_set,
        "started_at": started_at,
        "status": status,
        "verification_boundary": {
            "command_environment": (
                "strict host-variable allowlist; isolated out-of-tree HOME, USERPROFILE, "
                "temporary, and caches"
            ),
            "dependency_resolution": "uv lock check uses offline mode",
            "game_source_inspected": False,
            "generated_logs": (
                "credential values and token-like assignments are redacted before persistence; "
                "any redaction fails the required generated-log scan"
            ),
            "network_claim": (
                "No hosted inference is used. The package rehearsal blocks Python sockets. "
                "The verifier does not claim operating-system-level egress denial."
            ),
        },
    }
    receipt_path = output_root / "release-verification-receipt.json"
    receipt_raw = _receipt_bytes(body)
    write_bytes_atomic(receipt_path, receipt_raw)
    verify_release_receipt(receipt_path, expected_raw=receipt_raw)
    curated_path = output_root / "release-verification-evidence.json"
    curated_raw = _curated_evidence_bytes(body, sha256_bytes(receipt_raw))
    write_bytes_atomic(
        curated_path,
        curated_raw,
    )
    verify_release_receipt(receipt_path, expected_raw=receipt_raw)
    return body


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--profile",
        choices=VERIFICATION_PROFILES,
        default=BUILD000_PROFILE,
        help=(
            "Build 000 retains its historical release path; Build 001 package-only forbids "
            "official inventory, public manifests, and gameplay"
        ),
    )
    parser.add_argument("--root", type=Path, default=REPOSITORY)
    parser.add_argument("--output-root", type=Path, default=Path("artifacts/stage18/rc"))
    parser.add_argument(
        "--transient-root",
        type=Path,
        help=(
            "fresh absolute out-of-tree directory for unsealed temporary and cache state; "
            "defaults to a commit-named sibling of the clone"
        ),
    )
    parser.add_argument("--expected-commit", required=True)
    parser.add_argument("--expectation", type=Path, default=DEFAULT_EXPECTATION)
    uv_group = parser.add_mutually_exclusive_group()
    uv_group.add_argument("--uv-executable", type=Path)
    uv_group.add_argument("--uv-python", type=Path)
    parser.add_argument(
        "--official-environments-dir",
        type=Path,
        default=Path("artifacts/stage15/public-environments"),
    )
    parser.add_argument(
        "--plan-only",
        action="store_true",
        help="print the fully rendered deterministic command plan without running it",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    repository = args.root.resolve()
    output_root = (
        args.output_root if args.output_root.is_absolute() else repository / args.output_root
    ).resolve()
    transient_root = (
        args.transient_root.resolve()
        if args.transient_root is not None
        else repository.parent
        / (
            f".arc3-stage13-package-{args.expected_commit[:12]}-transient"
            if args.profile == BUILD001_PACKAGE_ONLY_PROFILE
            else f".arc3-stage18-{args.expected_commit[:12]}-transient"
        )
    ).resolve()
    expectation_path = (
        args.expectation if args.expectation.is_absolute() else repository / args.expectation
    ).resolve()
    official_environments = (
        None
        if args.profile == BUILD001_PACKAGE_ONLY_PROFILE
        else (
            args.official_environments_dir
            if args.official_environments_dir.is_absolute()
            else repository / args.official_environments_dir
        ).resolve()
    )
    try:
        if not _COMMIT.fullmatch(args.expected_commit):
            raise ValueError("--expected-commit must be a lowercase full 40-character SHA")
        expectation = (
            None
            if args.profile == BUILD001_PACKAGE_ONLY_PROFILE
            else load_benchmark_expectation(expectation_path)
        )
        uv_command = discover_uv_command(
            uv_executable=args.uv_executable,
            uv_python=args.uv_python,
        )
        specs = tuple(
            _replace_candidate_commit(spec, args.expected_commit)
            for spec in build_plan(
                repository=repository,
                output_root=output_root,
                transient_root=transient_root,
                expectation=expectation,
                uv_command=uv_command,
                official_environments=official_environments,
                profile=args.profile,
            )
        )
        if args.plan_only:
            print(
                json.dumps(
                    _plan_document(specs, profile=args.profile),
                    indent=2,
                    sort_keys=True,
                )
            )
            return 0
        body = run_release_verification(
            repository=repository,
            output_root=output_root,
            transient_root=transient_root,
            expected_commit=args.expected_commit,
            expectation_path=expectation_path,
            uv_command=uv_command,
            official_environments=official_environments,
            profile=args.profile,
        )
    except (OSError, ValueError) as error:
        print(f"release verification refused: {error}", file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "receipt": str(output_root / "release-verification-receipt.json"),
                "schema": SCHEMA,
                "status": body["status"],
            },
            sort_keys=True,
        )
    )
    return 0 if body["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
