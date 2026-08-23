#!/usr/bin/env python3
"""Preflight or execute the frozen Build 001 Stage 09 development matrix.

The default is a non-playing preflight.  ``--execute`` is required for the
exact 96-cell local-public matrix.  The harness never parses the public
partition manifest as metadata and has no holdout identities.
"""

from __future__ import annotations

import argparse
import base64
import builtins
import csv
import ctypes
import hashlib
import importlib.metadata
import json
import os
import platform
import re
import signal
import subprocess
import sys
import sysconfig
import time
import uuid
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, TypeGuard, cast

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
_BOOTSTRAP_AUTHORITY = getattr(builtins, "_arc3_stage09_supervisor_bootstrap_authority", None)
if __name__ == "__main__":
    if not isinstance(_BOOTSTRAP_AUTHORITY, dict):
        raise RuntimeError("Stage 09 supervisor requires the stdlib-only bootstrap")
    _bootstrap_unsigned = {
        key: value for key, value in _BOOTSTRAP_AUTHORITY.items() if key != "authority_hash"
    }
    _bootstrap_hash = (
        "sha256:"
        + hashlib.sha256(
            (
                json.dumps(
                    _bootstrap_unsigned,
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=False,
                    allow_nan=False,
                )
                + "\n"
            ).encode()
        ).hexdigest()
    )
    if (
        _BOOTSTRAP_AUTHORITY.get("schema")
        != "arc3.build-001.stage-09-supervisor-bootstrap-authority.v0.1"
        or _BOOTSTRAP_AUTHORITY.get("authority_hash") != _bootstrap_hash
        or _BOOTSTRAP_AUTHORITY.get("socket_audit_denial_installed") is not True
        or not isinstance(_BOOTSTRAP_AUTHORITY.get("runtime_observation_hash"), str)
    ):
        raise RuntimeError("Stage 09 supervisor bootstrap authority changed")
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from arc3.errors import EvaluationError, TraceError  # noqa: E402
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
    CELL_ADMISSION_CHARGE_NS,
    CELL_FINALIZATION_SCHEMA,
    CELL_RECEIPT_SCHEMA,
    DEVELOPMENT_GAMES,
    ENVIRONMENT_CACHE_SCHEMA,
    EXPECTED_CELL_COUNT,
    FROZEN_BUILD_000_COMMIT,
    FROZEN_BUILD_000_SOURCE_SHA256,
    FROZEN_BUILD_000_TREE,
    FROZEN_BUILD_001_COMMIT,
    FROZEN_BUILD_001_SOURCE_SHA256,
    FROZEN_BUILD_001_TREE,
    HARNESS_SOURCE_BINDING_SCHEMA,
    HARNESS_SOURCE_OBSERVATION_SCHEMA,
    HARNESS_SOURCE_PATHS,
    MAX_ACTIONS,
    MAX_RESETS,
    NORMAL_TERMINATION_DEFINITION,
    OVERALL_ACTIVE_WALL_SECONDS,
    PREDECLARATION_AMENDMENT_CORE_HASH,
    PREDECLARATION_AMENDMENT_FILE_SHA256,
    PREDECLARATION_CORE_HASH,
    PREDECLARATION_FILE_SHA256,
    PREFLIGHT_SCHEMA,
    PRIOR_AUTHORITY_SCHEMA,
    PUBLIC_PARTITION_MANIFEST_SHA256,
    RUNTIME_ENVIRONMENT_OBSERVATION_SCHEMA,
    RUNTIME_ENVIRONMENT_SCHEMA,
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
    development_identifier_list_hash,
    environment_cache_stable,
    harness_source_stable,
    matrix_hash,
    prior_authority_stable,
    runtime_environment_stable,
    validate_environment_cache_observation,
    validate_harness_source_binding,
    validate_harness_source_observation,
    validate_predeclaration_amendment_bytes,
    validate_predeclaration_bytes,
    validate_prior_authority_observation,
    validate_runtime_environment_binding,
    validate_runtime_environment_observation,
)
from arc3.evaluation.public import (  # noqa: E402
    PUBLIC_RUN_SCHEMA,
    PublicExposureLedger,
    _trace_receipt,
)
from arc3.evaluation.public_runner import _receipt_valid  # noqa: E402
from arc3.integrity import (  # noqa: E402
    IntegrityReceipt,
    discover_policy_files,
    discover_reachable_policy_files,
    scan_policy_files,
)

PREDECLARATION = ROOT / "docs/evidence/001-09-development-recovery-predeclaration.json"
PREDECLARATION_AMENDMENT = (
    ROOT / "docs/evidence/001-09-development-recovery-predeclaration-amendment-v0.1.json"
)
DEFAULT_OUTPUT = Path("C:/a/arc3-b001/artifacts/stage09/development-recovery-attempt-01.json")
DEFAULT_WORK_ROOT = Path("C:/a/arc3-b001/artifacts/stage09/development-recovery-work-attempt-01")
DEFAULT_EXPOSURE = Path("C:/a/arc3-b001/artifacts/stage09/public-exposure.jsonl")
DEFAULT_RECORDINGS = Path("C:/a/arc3-b001/recordings/stage09")
DEFAULT_ENVIRONMENTS = Path("C:/a/arc3-s15-6a0f6e5/artifacts/stage15/public-environments")
DEFAULT_BUILD_000_ROOT = Path("C:/a/arc3-stage08-build000-90ecf72")
DEFAULT_BUILD_001_ROOT = Path("C:/a/arc3-stage09-build001-d6d4bac")
DEFAULT_STAGE08_RESULT = Path(
    "C:/a/arc3-b001/artifacts/stage08/two-speed-controller-attempt-01.json"
)
DEFAULT_STAGE08_EXPOSURE = Path("C:/a/arc3-b001/artifacts/stage08/public-exposure.jsonl")
DEFAULT_PRIOR_INTEGRITY_RECEIPT = Path(
    "C:/a/arc3-b001/artifacts/stage09/policy-integrity-d6d4bac-package-only.json"
)
DEFAULT_BUILD_000_INTEGRITY_RECEIPT = Path(
    "C:/a/arc3-b001/artifacts/stage09/policy-integrity-build000-90ecf726-full.json"
)
HOLDOUT_NONCONSUMPTION_RECEIPT = ROOT / "docs/evidence/001-08-two-speed-controller.json"
BUILD_001_PACKAGE_INTEGRITY_RECEIPT_SHA256: str | None = (
    "sha256:173c0a6c3aee154df67920227e3b5303c59682186a2254a220e24dd5589269fe"
)
BUILD_001_PACKAGE_INTEGRITY_SELF_HASH: str | None = (
    "sha256:3e29edd69d7999760c53a80de474d701f9124faed73ccc1b9047adbf9a766702"
)
BUILD_001_PACKAGE_INTEGRITY_COMMIT: str | None = "d6d4bac1e33c9837856c08abcee61bcb14afd34e"
BUILD_000_INTEGRITY_RECEIPT_SHA256 = (
    "sha256:b63ea29913a042930b01ace640c283dd0febce3597b637c3d8433fc981579349"
)
BUILD_000_INTEGRITY_SELF_HASH = (
    "sha256:3545f69c786ed8268d2e3948769a976db920f2b2e79851cb6bb5c6e922601643"
)
HOLDOUT_NONCONSUMPTION_RECEIPT_SHA256 = (
    "sha256:0134c9e5b7acea716f790088cb59109eded7857ce83fda004ea1b88be2eb92ac"
)
WORKER = ROOT / "scripts/_stage09_development_worker.py"
CLAIM_BOUNDARY = "development recovery only; no public-holdout or hidden-game generalization claim"
SEALED_HOLDOUT = {
    "identities_loaded": 0,
    "manifest_loaded_as_metadata": False,
    "public_holdout_gameplay_events": 0,
    "status": "SEALED_UNCONSUMED",
}
EXPECTED_INSTALLED_DISTRIBUTIONS = (
    ("annotated-types", "0.8.0"),
    ("arc-agi", "0.9.9"),
    ("arc3", "0.1.0"),
    ("arcengine", "0.9.3"),
    ("blinker", "1.9.0"),
    ("certifi", "2026.7.22"),
    ("cfgv", "3.5.0"),
    ("charset-normalizer", "3.5.1"),
    ("click", "8.4.2"),
    ("colorama", "0.4.6"),
    ("contourpy", "1.3.3"),
    ("coverage", "7.15.4"),
    ("cycler", "0.12.1"),
    ("distlib", "0.4.3"),
    ("filelock", "3.32.3"),
    ("flask", "3.1.3"),
    ("fonttools", "4.63.0"),
    ("hatchling", "1.32.0"),
    ("hypothesis", "6.165.10"),
    ("identify", "2.6.19"),
    ("idna", "3.19"),
    ("iniconfig", "2.3.0"),
    ("itsdangerous", "2.2.0"),
    ("jinja2", "3.1.6"),
    ("kiwisolver", "1.5.0"),
    ("librt", "0.15.0"),
    ("markupsafe", "3.0.3"),
    ("matplotlib", "3.11.1"),
    ("mypy", "1.20.2"),
    ("mypy-extensions", "1.1.0"),
    ("nodeenv", "1.10.0"),
    ("numpy", "2.5.2"),
    ("packaging", "26.3"),
    ("pathspec", "1.1.1"),
    ("pillow", "12.3.0"),
    ("platformdirs", "4.11.3"),
    ("pluggy", "1.6.0"),
    ("pre-commit", "4.6.2"),
    ("pyarrow", "21.0.0"),
    ("pydantic", "2.13.4"),
    ("pydantic-core", "2.46.4"),
    ("pygments", "2.21.0"),
    ("pyparsing", "3.3.2"),
    ("pytest", "8.4.2"),
    ("pytest-cov", "6.3.0"),
    ("python-dateutil", "2.9.0.post0"),
    ("python-discovery", "1.5.2"),
    ("python-dotenv", "1.2.3"),
    ("pyyaml", "6.0.3"),
    ("requests", "2.34.2"),
    ("ruff", "0.16.4"),
    ("six", "1.17.0"),
    ("sortedcontainers", "2.4.0"),
    ("tomlkit", "0.15.1"),
    ("trove-classifiers", "2026.6.1.19"),
    ("types-requests", "2.33.0.20260712"),
    ("typing-extensions", "4.16.0"),
    ("typing-inspection", "0.4.4"),
    ("urllib3", "2.7.0"),
    ("virtualenv", "21.7.4"),
    ("werkzeug", "3.1.8"),
)

EXPECTED_RUNTIME_ENVIRONMENT = seal_object(
    {
        "schema": RUNTIME_ENVIRONMENT_SCHEMA,
        "bootstrap_boundary": {
            "residual": None,
            "supervisor_pre_first_party_runtime_validation": True,
            "worker_pre_first_party_runtime_validation": True,
        },
        "executable": "C:/a/arc3-b001-28c7a00/Scripts/python.exe",
        "executable_sha256": (
            "sha256:99bbec125a2d2ce19b6257324a5a5b70539a64c9fd7b9724c6b65dcba8a6d276"
        ),
        "implementation": "CPython",
        "python_version": "3.12.14",
        "cache_tag": "cpython-312",
        "upstream_lock_sha256": (
            "sha256:67e1d937e213bbcc25783784d04c4fa349b85dc09b94855256916ca6b96e808a"
        ),
        "uv_lock_sha256": (
            "sha256:3bf42dcbe45720f71b7433584f56a5d5982ec1c687c341ad2626222fa5de285b"
        ),
        "distributions": {
            "arc-agi": {
                "file_bytes": 142_986,
                "file_count": 10,
                "files_sha256": (
                    "sha256:486e1e6a08ba8a1feca2bb1633d456a8b5eb7113847a959c8b01aa1e44c0fcaa"
                ),
                "hash_entry_count": 14,
                "installed_files_sha256": (
                    "sha256:e4b4535eed8001cfe63975defbc8e0cafe53381789824b452ee7076d41a0f436"
                ),
                "record_entry_count": 15,
                "record_sha256": (
                    "sha256:342fb4152a43d4c99429917b7bf397e82cd64cc1e41d1006a44515f00fb4f09a"
                ),
                "record_verification_passed": True,
                "verified_hash_entry_count": 14,
                "version": "0.9.9",
            },
            "arcengine": {
                "file_bytes": 100_940,
                "file_count": 10,
                "files_sha256": (
                    "sha256:516dd546cc5913a0f6cb4edc3f85cdd52a7dc1ce4cddaca500c2a1ee3b012205"
                ),
                "hash_entry_count": 14,
                "installed_files_sha256": (
                    "sha256:5a724c77b01f39b6d3e625c804b3712597d722cfb84c785072d124d424b5b41d"
                ),
                "record_entry_count": 15,
                "record_sha256": (
                    "sha256:b1a220337cab27ba934fe0945c8e1250adb1e708eb2f73cdc202d60a9a007970"
                ),
                "record_verification_passed": True,
                "verified_hash_entry_count": 14,
                "version": "0.9.3",
            },
            "numpy": {
                "file_bytes": 41_511_286,
                "file_count": 923,
                "files_sha256": (
                    "sha256:43bf9f821390052fb0cff09389aff380b850dea75585d928c969c089b677c9db"
                ),
                "hash_entry_count": 948,
                "installed_files_sha256": (
                    "sha256:7e5ec0b2eefb84c95b43ffc4ea1527d98236dd893750b53a263efb98937e9dff"
                ),
                "record_entry_count": 949,
                "record_sha256": (
                    "sha256:1a2cb8b62ed5afe896818890b0b0372a192c1838e8af38ce6cd0df122585d097"
                ),
                "record_verification_passed": True,
                "verified_hash_entry_count": 948,
                "version": "2.5.2",
            },
            "pydantic": {
                "file_bytes": 1_772_739,
                "file_count": 107,
                "files_sha256": (
                    "sha256:99bca3dcf2febba7bf4a2ba763b58fdd818d0759a20aaa6398b31e467d6eec62"
                ),
                "hash_entry_count": 112,
                "installed_files_sha256": (
                    "sha256:ac9ac1cfaecfded4111d90585632752a32b730368322d3aa77a3fbb1132071be"
                ),
                "record_entry_count": 113,
                "record_sha256": (
                    "sha256:d0cbe0f34b294885175920bc8f2ece0b3ed6d9874347dc9cfb2caf4931329272"
                ),
                "record_verification_passed": True,
                "verified_hash_entry_count": 112,
                "version": "2.13.4",
            },
            "pydantic-core": {
                "file_bytes": 5_465_429,
                "file_count": 5,
                "files_sha256": (
                    "sha256:4986b84dd3fae3a6bd0cc0f227da0045ccd5af758a25d681258e3fa9878231ad"
                ),
                "hash_entry_count": 11,
                "installed_files_sha256": (
                    "sha256:ae9cf675f865b4f37eab20f4e9bf45233d754344464aa3897d9f456924c43937"
                ),
                "record_entry_count": 12,
                "record_sha256": (
                    "sha256:d4d569852beabeb9a5c6f39985b5b708f7ea4f1b53ddd0c27b819e895dfb5e94"
                ),
                "record_verification_passed": True,
                "verified_hash_entry_count": 11,
                "version": "2.46.4",
            },
        },
        "installed_distribution_inventory": {
            "distribution_count": len(EXPECTED_INSTALLED_DISTRIBUTIONS),
            "hash_entry_count": 6_096,
            "installed_files_sha256": (
                "sha256:cad0b80f2846e6cf152c12e814c0998c100afdb8752a780582b6a0bb57d7002e"
            ),
            "names_and_versions": [
                {"name": name, "version": version}
                for name, version in EXPECTED_INSTALLED_DISTRIBUTIONS
            ],
            "record_verification_passed": True,
            "records_sha256": (
                "sha256:c429b53a091d475d1aa942775652e47cbfdfbc7d6adf2af6afd0ea8f8e0d5d6c"
            ),
            "verified_hash_entry_count": 6_096,
        },
        "critical_versions": {
            "annotated-types": "0.8.0",
            "numpy": "2.5.2",
            "pydantic": "2.13.4",
            "pydantic-core": "2.46.4",
            "typing-extensions": "4.16.0",
            "typing-inspection": "0.4.4",
        },
        "sdk_import_probe": True,
        "sdk_probe_network_denied": True,
        "python_base": {
            "base_executable": (
                "C:/Users/cdpan/AppData/Roaming/uv/python/"
                "cpython-3.12.14-windows-x86_64-none/python.exe"
            ),
            "base_executable_sha256": (
                "sha256:4eb51b7d5963d9e0dc356bd209b1d55360c73db39d8d458ceee084610ca48fd1"
            ),
            "base_prefix": (
                "C:/Users/cdpan/AppData/Roaming/uv/python/cpython-3.12.14-windows-x86_64-none"
            ),
            "dll_file_bytes": 25_147_104,
            "dll_file_count": 41,
            "dll_files_sha256": (
                "sha256:b42d9c67f57f57cf23d9c31f9acef472e2b01ee4ed5752303a073990ae6a0546"
            ),
            "stdlib": {
                "file_bytes": 14_208_400,
                "file_count": 738,
                "files_sha256": (
                    "sha256:638457f60f5ba635b08e006a4be9758b88b7c97f27da818b92ea393c79bbe5f8"
                ),
                "root": (
                    "C:/Users/cdpan/AppData/Roaming/uv/python/"
                    "cpython-3.12.14-windows-x86_64-none/Lib"
                ),
            },
        },
        "scorer": {
            "distribution": "arc-agi",
            "module": "arc_agi/scorecard.py",
            "sha256": ("sha256:1cc830e48008bec60b8a98ae14d3e9312e8408f102a9878bad42744aa9e489b7"),
            "source_version": ("arc-agi==0.9.9 local ScorecardManager; arcengine==0.9.3"),
        },
    },
    hash_field="runtime_binding_hash",
)
EXPECTED_ENVIRONMENT_CACHE = {
    "aggregate_sha256": ("sha256:6f8618674e4f974cca144c94c7a2632dfbe8dddf36b0654e1d0564246932d3b2"),
    "directory_count": 30,
    "entry_count": 60,
    "recursive_bytes": 2_784_922,
    "recursive_file_count": 30,
    "root_file_count": 0,
    "top_level_directory_count": 15,
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
WINDOWS_CREATE_SUSPENDED = 0x00000004
WINDOWS_JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
LAUNCH_RECEIPT_SCHEMA = "arc3.build-001.stage-09-process-launch.v0.1"
LAUNCH_AUTHORIZATION_SCHEMA = "arc3.build-001.stage-09-launch-authorization.v0.1"
WORKER_ABORT_SCHEMA = "arc3.build-001.stage-09-worker-abort.v0.1"
SUPERVISION_RECEIPT_SCHEMA = "arc3.build-001.stage-09-supervision.v0.1"
TIMEOUT_TRACE_SCHEMA = "arc3.build-001.stage-09-timeout-trace.v0.1"
SPAWN_INTENT_SCHEMA = "arc3.build-001.stage-09-spawn-intent.v0.1"
CELL_SEGMENT_SCHEMA = "arc3.build-001.stage-09-active-cell-segment.v0.1"
ORPHAN_RECEIPT_SCHEMA = "arc3.build-001.stage-09-orphan-termination.v0.3"
PARENT_EVIDENCE_SCHEMA = "arc3.build-001.stage-09-parent-evidence.v0.2"
RUN_CLOCK_SCHEMA = "arc3.build-001.stage-09-run-clock.v0.2"
TERMINAL_FINALIZATION_SCHEMA = "arc3.build-001.stage-09-terminal-finalization.v0.3"
TERMINAL_VERIFICATION_SCHEMA = "arc3.build-001.stage-09-terminal-verification.v0.2"
RECOVERED_CELL_FINALIZATION_SCHEMA = "arc3.build-001.stage-09-recovered-cell-finalization.v0.1"
TERMINAL_WRITE_RESERVE_NS = 1_000_000_000
_SDK_IMPORT_PROBE_CACHE: bool | None = None


class _WindowsIoCounters(ctypes.Structure):
    _fields_ = [
        (name, ctypes.c_ulonglong)
        for name in (
            "read_operations",
            "write_operations",
            "other_operations",
            "read_bytes",
            "write_bytes",
            "other_bytes",
        )
    ]


class _WindowsJobBasicLimits(ctypes.Structure):
    _fields_ = [
        ("per_process_user_time", ctypes.c_longlong),
        ("per_job_user_time", ctypes.c_longlong),
        ("limit_flags", ctypes.c_uint32),
        ("minimum_working_set", ctypes.c_size_t),
        ("maximum_working_set", ctypes.c_size_t),
        ("active_process_limit", ctypes.c_uint32),
        ("affinity", ctypes.c_size_t),
        ("priority_class", ctypes.c_uint32),
        ("scheduling_class", ctypes.c_uint32),
    ]


class _WindowsJobExtendedLimits(ctypes.Structure):
    _fields_ = [
        ("basic", _WindowsJobBasicLimits),
        ("io", _WindowsIoCounters),
        ("process_memory_limit", ctypes.c_size_t),
        ("job_memory_limit", ctypes.c_size_t),
        ("peak_process_memory", ctypes.c_size_t),
        ("peak_job_memory", ctypes.c_size_t),
    ]


class _WindowsJobAccounting(ctypes.Structure):
    _fields_ = [
        ("total_user_time", ctypes.c_longlong),
        ("total_kernel_time", ctypes.c_longlong),
        ("period_user_time", ctypes.c_longlong),
        ("period_kernel_time", ctypes.c_longlong),
        ("total_page_faults", ctypes.c_uint32),
        ("total_processes", ctypes.c_uint32),
        ("active_processes", ctypes.c_uint32),
        ("terminated_processes", ctypes.c_uint32),
    ]


def _windows_library(name: str) -> Any:
    """Load one Windows DLL without exposing platform-only ctypes attributes to mypy."""

    loader = getattr(ctypes, "windll", None)
    library = getattr(loader, name, None)
    if os.name != "nt" or library is None:
        raise OSError(f"Windows {name} is unavailable through ctypes")
    return library


def _is_mapping(value: object) -> TypeGuard[Mapping[str, object]]:
    return isinstance(value, Mapping) and all(isinstance(key, str) for key in value)


def _git(root: Path, *arguments: str) -> str:
    environment = {
        key: value for key, value in os.environ.items() if not key.upper().startswith("GIT_")
    }
    environment["GIT_NO_REPLACE_OBJECTS"] = "1"
    result = subprocess.run(
        ["git", "-C", str(root.resolve()), *arguments],
        check=False,
        capture_output=True,
        env=environment,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=15.0,
    )
    if result.returncode:
        raise EvaluationError(f"Stage 09 git {' '.join(arguments)} failed")
    return result.stdout.strip()


def _runtime_identity() -> dict[str, object]:
    gpu: list[dict[str, object]] = []
    try:
        query = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=name,driver_version,memory.total",
                "--format=csv,noheader,nounits",
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=5.0,
        )
        if query.returncode == 0:
            for row in query.stdout.splitlines():
                fields = [field.strip() for field in row.split(",")]
                if len(fields) == 3:
                    try:
                        memory_mib: int | None = int(fields[2])
                    except ValueError:
                        memory_mib = None
                    gpu.append({"driver": fields[1], "memory_mib": memory_mib, "name": fields[0]})
    except (OSError, subprocess.TimeoutExpired):
        pass
    ram_total: int | None = None
    if os.name == "nt":

        class _MemoryStatusEx(ctypes.Structure):
            _fields_ = (
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            )

        memory = _MemoryStatusEx()
        memory.dwLength = ctypes.sizeof(_MemoryStatusEx)
        loader = getattr(ctypes, "windll", None)
        kernel32 = getattr(loader, "kernel32", None)
        global_memory_status = getattr(kernel32, "GlobalMemoryStatusEx", None)
        if callable(global_memory_status) and global_memory_status(ctypes.byref(memory)):
            ram_total = int(memory.ullTotalPhys)
    else:
        try:
            sysconf = getattr(os, "sysconf", None)
            if callable(sysconf):
                ram_total = int(sysconf("SC_PAGE_SIZE") * sysconf("SC_PHYS_PAGES"))
        except (AttributeError, OSError, ValueError):
            pass
    return {
        "cpu": (
            os.environ.get("PROCESSOR_IDENTIFIER")
            or os.environ.get("PROCESSOR_ARCHITECTURE")
            or os.environ.get("HOSTTYPE")
            or None
        ),
        "cpu_count": os.cpu_count(),
        "cpu_physical_count": None,
        "executable": Path(sys.executable).resolve().as_posix(),
        "gpu": gpu,
        "platform": f"{os.name}:{sys.platform}",
        "python": platform.python_version(),
        "ram_total_bytes": ram_total,
    }


def _harness_source_binding(
    *, git_commit: str, git_tree: str, files: Mapping[str, str]
) -> dict[str, object]:
    payload = {
        "schema": HARNESS_SOURCE_BINDING_SCHEMA,
        "git_commit": git_commit,
        "git_tree": git_tree,
        "files": dict(files),
    }
    binding = cast(dict[str, object], seal_object(payload, hash_field="binding_hash"))
    return validate_harness_source_binding(binding)


def _harness_source_identity(expected: Mapping[str, object]) -> dict[str, object]:
    binding = validate_harness_source_binding(expected)
    resolved = ROOT.resolve()
    commit = _git(resolved, "rev-parse", "HEAD")
    tree = _git(resolved, "rev-parse", "HEAD^{tree}")
    branch = _git(resolved, "branch", "--show-current")
    status = _git(resolved, "status", "--porcelain=v1", "--untracked-files=all")
    top_level = Path(_git(resolved, "rev-parse", "--show-toplevel")).resolve()
    observed_files: dict[str, object] = {}
    for relative in HARNESS_SOURCE_PATHS:
        path = resolved / relative
        observed_files[relative] = sha256_file(path) if path.is_file() else None
    predicates = {
        "clean": status == "",
        "commit": commit == binding["git_commit"],
        "detached": branch == "",
        "files": observed_files == binding["files"],
        "root": top_level == resolved,
        "tree": tree == binding["git_tree"],
    }
    return cast(
        dict[str, object],
        seal_object(
            {
                "schema": HARNESS_SOURCE_OBSERVATION_SCHEMA,
                "binding_hash": binding["binding_hash"],
                "branch": branch,
                "dirty_worktree": bool(status),
                "files": observed_files,
                "git_commit": commit,
                "git_tree": tree,
                "passed": all(predicates.values()),
                "predicates": predicates,
                "root": resolved.as_posix(),
            },
            hash_field="observation_hash",
        ),
    )


def _canonical_distribution_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _distribution_record_identity(
    distribution: importlib.metadata.Distribution,
) -> dict[str, object]:
    record_items = [
        item
        for item in distribution.files or ()
        if str(item).replace("\\", "/").endswith(".dist-info/RECORD")
    ]
    if len(record_items) != 1:
        return {
            "hash_entry_count": 0,
            "installed_files_sha256": None,
            "record_entry_count": 0,
            "record_sha256": None,
            "record_verification_passed": False,
            "verified_hash_entry_count": 0,
        }
    record_path = Path(str(distribution.locate_file(record_items[0]))).resolve()
    if not record_path.is_file():
        return {
            "hash_entry_count": 0,
            "installed_files_sha256": None,
            "record_entry_count": 0,
            "record_sha256": None,
            "record_verification_passed": False,
            "verified_hash_entry_count": 0,
        }
    raw = record_path.read_bytes()
    try:
        rows = list(csv.reader(raw.decode("utf-8").splitlines()))
    except (UnicodeDecodeError, csv.Error):
        return {
            "hash_entry_count": 0,
            "installed_files_sha256": None,
            "record_entry_count": 0,
            "record_sha256": None,
            "record_verification_passed": False,
            "verified_hash_entry_count": 0,
        }
    installed_rows: list[tuple[str, int | None, str | None, str]] = []
    verified = 0
    for row in rows:
        if len(row) < 2 or not row[1]:
            continue
        relative, separator, encoded = row[1].partition("=")
        if separator != "=" or relative != "sha256" or not encoded:
            installed_rows.append((row[0], None, None, row[1]))
            continue
        installed = Path(str(distribution.locate_file(row[0]))).resolve()
        if installed.is_file():
            raw_file = installed.read_bytes()
            digest = sha256_bytes(raw_file)
            declared = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)).hex()
            if digest == f"sha256:{declared}":
                verified += 1
            installed_rows.append((row[0].replace("\\", "/"), len(raw_file), digest, row[1]))
        else:
            installed_rows.append((row[0].replace("\\", "/"), None, None, row[1]))
    return {
        "hash_entry_count": len(installed_rows),
        "installed_files_sha256": sha256_bytes(canonical_json_bytes(installed_rows)),
        "record_entry_count": len(rows),
        "record_sha256": sha256_bytes(raw),
        "record_verification_passed": verified == len(installed_rows),
        "verified_hash_entry_count": verified,
    }


def _distribution_file_identity(name: str, package_prefixes: Sequence[str]) -> dict[str, object]:
    try:
        distribution = importlib.metadata.distribution(name)
    except importlib.metadata.PackageNotFoundError:
        return {
            "file_bytes": 0,
            "file_count": 0,
            "files_sha256": None,
            "record_entry_count": 0,
            "record_sha256": None,
            "hash_entry_count": 0,
            "installed_files_sha256": None,
            "record_verification_passed": False,
            "verified_hash_entry_count": 0,
            "version": None,
        }
    rows: list[tuple[str, int, str]] = []
    for item in sorted(distribution.files or (), key=lambda value: str(value).replace("\\", "/")):
        relative = str(item).replace("\\", "/")
        path = Path(str(distribution.locate_file(item))).resolve()
        if (
            any(relative.startswith(prefix) for prefix in package_prefixes)
            and path.is_file()
            and "__pycache__" not in path.parts
            and path.suffix != ".pyc"
        ):
            rows.append((relative, path.stat().st_size, sha256_file(path)))
    return {
        "file_bytes": sum(row[1] for row in rows),
        "file_count": len(rows),
        "files_sha256": sha256_bytes(canonical_json_bytes(rows)),
        **_distribution_record_identity(distribution),
        "version": distribution.version,
    }


def _installed_distribution_inventory() -> dict[str, object]:
    names_and_versions: list[dict[str, str]] = []
    records: list[tuple[str, str, int, str | None, int, int, str | None, bool]] = []
    for distribution in importlib.metadata.distributions():
        raw_name = distribution.metadata.get("Name")
        if not isinstance(raw_name, str) or not raw_name:
            continue
        name = _canonical_distribution_name(raw_name)
        version = distribution.version
        record = _distribution_record_identity(distribution)
        names_and_versions.append({"name": name, "version": version})
        records.append(
            (
                name,
                version,
                cast(int, record["record_entry_count"]),
                cast(str | None, record["record_sha256"]),
                cast(int, record["hash_entry_count"]),
                cast(int, record["verified_hash_entry_count"]),
                cast(str | None, record["installed_files_sha256"]),
                cast(bool, record["record_verification_passed"]),
            )
        )
    names_and_versions.sort(key=lambda item: (item["name"], item["version"]))
    records.sort()
    if len({item["name"] for item in names_and_versions}) != len(names_and_versions):
        raise EvaluationError("Stage 09 installed distribution inventory contains duplicates")
    return {
        "distribution_count": len(names_and_versions),
        "hash_entry_count": sum(item[4] for item in records),
        "installed_files_sha256": sha256_bytes(canonical_json_bytes(records)),
        "names_and_versions": names_and_versions,
        "record_verification_passed": all(item[7] for item in records),
        "records_sha256": sha256_bytes(canonical_json_bytes([item[:4] for item in records])),
        "verified_hash_entry_count": sum(item[5] for item in records),
    }


def _tree_identity(root: Path, *, exclude_site_packages: bool = False) -> dict[str, object]:
    rows: list[tuple[str, int, str]] = []
    if root.is_dir():
        for path in sorted(root.rglob("*")):
            relative_path = path.relative_to(root)
            if (
                not path.is_file()
                or "__pycache__" in relative_path.parts
                or path.suffix == ".pyc"
                or (
                    exclude_site_packages
                    and any(
                        part in {"site-packages", "dist-packages"} for part in relative_path.parts
                    )
                )
            ):
                continue
            relative = relative_path.as_posix()
            rows.append((relative, path.stat().st_size, sha256_file(path)))
    return {
        "file_bytes": sum(row[1] for row in rows),
        "file_count": len(rows),
        "files_sha256": sha256_bytes(canonical_json_bytes(rows)),
        "root": root.resolve().as_posix(),
    }


def _python_base_identity() -> dict[str, object]:
    base_prefix = Path(sys.base_prefix).resolve()
    stdlib_root = Path(sysconfig.get_path("stdlib")).resolve()
    base_executable = Path(getattr(sys, "_base_executable", sys.executable)).resolve()
    dll_rows: list[tuple[str, int, str]] = []
    dll_roots = [base_prefix / "DLLs"]
    for path in sorted(base_prefix.glob("*.dll")):
        if path.is_file():
            dll_rows.append((path.name, path.stat().st_size, sha256_file(path)))
    dll_root = dll_roots[0]
    if dll_root.is_dir():
        for path in sorted(dll_root.rglob("*")):
            if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc":
                relative = f"DLLs/{path.relative_to(dll_root).as_posix()}"
                dll_rows.append((relative, path.stat().st_size, sha256_file(path)))
    return {
        "base_executable": base_executable.as_posix(),
        "base_executable_sha256": sha256_file(base_executable),
        "base_prefix": base_prefix.as_posix(),
        "dll_file_bytes": sum(row[1] for row in dll_rows),
        "dll_file_count": len(dll_rows),
        "dll_files_sha256": sha256_bytes(canonical_json_bytes(dll_rows)),
        "stdlib": _tree_identity(stdlib_root, exclude_site_packages=True),
    }


def _runtime_environment_identity(
    expected: Mapping[str, object] = EXPECTED_RUNTIME_ENVIRONMENT,
) -> dict[str, object]:
    binding = validate_runtime_environment_binding(expected)
    distributions = {
        "arc-agi": _distribution_file_identity("arc-agi", ("arc_agi/",)),
        "arcengine": _distribution_file_identity("arcengine", ("arcengine/",)),
        "numpy": _distribution_file_identity("numpy", ("numpy/", "numpy.libs/")),
        "pydantic": _distribution_file_identity("pydantic", ("pydantic/",)),
        "pydantic-core": _distribution_file_identity("pydantic-core", ("pydantic_core/",)),
    }
    critical_versions: dict[str, str | None] = {}
    for name in cast(dict[str, str], binding["critical_versions"]):
        try:
            critical_versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            critical_versions[name] = None
    try:
        scorecard_distribution = importlib.metadata.distribution("arc-agi")
        scorecard = Path(str(scorecard_distribution.locate_file("arc_agi/scorecard.py"))).resolve()
        scorer_sha256 = sha256_file(scorecard) if scorecard.is_file() else None
    except importlib.metadata.PackageNotFoundError:
        scorer_sha256 = None
    static_actual = {
        "bootstrap_boundary": {
            "residual": None,
            "supervisor_pre_first_party_runtime_validation": True,
            "worker_pre_first_party_runtime_validation": True,
        },
        "cache_tag": sys.implementation.cache_tag,
        "critical_versions": critical_versions,
        "distributions": distributions,
        "installed_distribution_inventory": _installed_distribution_inventory(),
        "executable": Path(sys.executable).resolve().as_posix(),
        "executable_sha256": sha256_file(Path(sys.executable).resolve()),
        "implementation": platform.python_implementation(),
        "python_version": platform.python_version(),
        "python_base": _python_base_identity(),
        "sdk_probe_network_denied": True,
        "scorer": {
            "distribution": "arc-agi",
            "module": "arc_agi/scorecard.py",
            "sha256": scorer_sha256,
            "source_version": (
                f"arc-agi=={distributions['arc-agi']['version']} local ScorecardManager; "
                f"arcengine=={distributions['arcengine']['version']}"
            ),
        },
        "upstream_lock_sha256": sha256_file(ROOT / "upstream.lock.json"),
        "uv_lock_sha256": sha256_file(ROOT / "uv.lock"),
    }
    static_expected = {
        key: value
        for key, value in binding.items()
        if key not in {"runtime_binding_hash", "schema", "sdk_import_probe"}
    }
    static_pass = static_actual == static_expected
    global _SDK_IMPORT_PROBE_CACHE
    if static_pass and _SDK_IMPORT_PROBE_CACHE is None:
        probe = subprocess.run(
            [
                _lexical_python_launcher(),
                "-I",
                "-c",
                (
                    "import sys;from pathlib import Path;"
                    'exec("def _deny(event,args):\\n '
                    "   if event.startswith('socket.'): raise RuntimeError('network denied')\");"
                    "sys.addaudithook(_deny);"
                    "r=Path(sys.argv[1]).resolve();sys.path.insert(0,str(r/'src'));"
                    "from arc3.adapters.arc_agi import _load_sdk_bindings;"
                    "_load_sdk_bindings();print('PASS')"
                ),
                str(ROOT.resolve()),
            ],
            cwd=ROOT.resolve(),
            check=False,
            capture_output=True,
            timeout=30.0,
        )
        _SDK_IMPORT_PROBE_CACHE = probe.returncode == 0 and probe.stdout.strip() == b"PASS"
    actual = {
        **static_actual,
        "sdk_import_probe": _SDK_IMPORT_PROBE_CACHE if static_pass else False,
    }
    predicates = {key: actual[key] == binding[key] for key in actual}
    return cast(
        dict[str, object],
        seal_object(
            {
                "schema": RUNTIME_ENVIRONMENT_OBSERVATION_SCHEMA,
                "actual": actual,
                "binding_hash": binding["runtime_binding_hash"],
                "passed": all(predicates.values()),
                "predicates": predicates,
            },
            hash_field="observation_hash",
        ),
    )


def _integrity_authority(
    path: Path, *, expected_file_hash: str, expected_self_hash: str, expected_commit: str
) -> tuple[dict[str, object], dict[str, bool]]:
    file_hash = sha256_file(path) if path.is_file() else None
    receipt = load_json(path) if path.is_file() else {}
    canonical_self_hash = False
    if path.is_file():
        try:
            canonical_self_hash = (
                IntegrityReceipt.from_bytes(path.read_bytes()).receipt_sha256 == expected_self_hash
            )
        except (TypeError, UnicodeDecodeError, ValueError):
            canonical_self_hash = False
    checks = receipt.get("checks")
    finding_counts = receipt.get("finding_counts")
    checks_pass = bool(
        isinstance(checks, dict)
        and all(
            isinstance(checks.get(name), dict)
            and cast(dict[str, object], checks[name]).get("passed") is True
            for name in (
                "archive_static",
                "policy_static",
                "secret_scan",
                "source_identity",
                "supply_chain",
            )
        )
    )
    predicates = {
        "checks": checks_pass,
        "clean_source": isinstance(receipt.get("git"), dict)
        and cast(dict[str, object], receipt["git"]).get("commit") == expected_commit
        and cast(dict[str, object], receipt["git"]).get("dirty_worktree") is False,
        "file_hash": file_hash == expected_file_hash,
        "findings": isinstance(finding_counts, dict)
        and finding_counts.get("blocking") == 0
        and finding_counts.get("warnings") == 0
        and finding_counts.get("total") == 0,
        "manifest_hash": isinstance(receipt.get("inputs"), dict)
        and cast(dict[str, object], receipt["inputs"]).get("manifest_sha256")
        == PUBLIC_PARTITION_MANIFEST_SHA256,
        "passed": receipt.get("passed") is True,
        "self_hash": receipt.get("receipt_sha256") == expected_self_hash and canonical_self_hash,
    }
    projection = {
        "file_sha256": file_hash,
        "git_commit": cast(dict[str, object], receipt.get("git", {})).get("commit"),
        "path": path.resolve().as_posix(),
        "receipt_sha256": receipt.get("receipt_sha256"),
    }
    return projection, predicates


_PACKAGE_ONLY_PREFIXES = (".github/", "agent/", "scripts/", "src/", "tests/")
_PACKAGE_ONLY_ROOT_FILES = frozenset(
    {
        ".env.example",
        ".gitattributes",
        ".gitignore",
        "AGENTS.md",
        "LICENSE",
        "README.md",
        "THIRD_PARTY_NOTICES.md",
        "pyproject.toml",
        "upstream.lock.json",
        "uv.lock",
    }
)
_PRODUCTION_POLICY_ENTRY_POINTS = ("agent/my_agent.py",)


def _package_only_candidate_files(root: Path) -> tuple[Path, ...]:
    """Recompute the protected-surface-free tracked candidate set."""

    resolved = root.resolve()
    environment = {
        key: value for key, value in os.environ.items() if not key.upper().startswith("GIT_")
    }
    environment["GIT_NO_REPLACE_OBJECTS"] = "1"
    completed = subprocess.run(
        ("git", "-C", str(resolved), "ls-tree", "-r", "--name-only", "-z", "HEAD"),
        check=False,
        capture_output=True,
        env=environment,
        timeout=30.0,
    )
    if completed.returncode != 0:
        raise EvaluationError("Stage 09 package integrity cannot read the exact Git tree")
    try:
        names = tuple(name.decode("utf-8") for name in completed.stdout.split(b"\0") if name)
    except UnicodeDecodeError as error:
        raise EvaluationError("Stage 09 package integrity found a non-UTF-8 path") from error
    selected: list[Path] = []
    for name in names:
        normalized = Path(name).as_posix()
        if normalized in _PACKAGE_ONLY_ROOT_FILES or normalized.startswith(_PACKAGE_ONLY_PREFIXES):
            lexical = resolved / normalized
            if lexical.is_symlink():
                raise EvaluationError("Stage 09 package candidate is a symlink")
            candidate = lexical.resolve()
            try:
                candidate.relative_to(resolved)
            except ValueError as error:
                raise EvaluationError(
                    "Stage 09 package candidate escaped its source root"
                ) from error
            if not candidate.is_file() or candidate.is_symlink():
                raise EvaluationError("Stage 09 package candidate is not a regular file")
            selected.append(candidate)
    if not selected:
        raise EvaluationError("Stage 09 package integrity found no candidate files")
    return tuple(selected)


def _package_integrity_authority(
    path: Path,
    *,
    source_root: Path,
    expected_file_hash: str | None,
    expected_self_hash: str | None,
    expected_commit: str | None,
) -> tuple[dict[str, object], dict[str, bool]]:
    """Validate a package-only receipt without loading public identifiers."""

    file_hash = sha256_file(path) if path.is_file() else None
    receipt = load_json(path) if path.is_file() else {}
    canonical_self_hash = False
    if path.is_file() and expected_self_hash is not None:
        try:
            canonical_self_hash = (
                IntegrityReceipt.from_bytes(path.read_bytes()).receipt_sha256 == expected_self_hash
            )
        except (TypeError, UnicodeDecodeError, ValueError):
            canonical_self_hash = False
    checks = receipt.get("checks")
    finding_counts = receipt.get("finding_counts")
    inputs = receipt.get("inputs")
    assurance = receipt.get("assurance_scope")
    license_summary = receipt.get("license_summary")
    coverage = receipt.get("production_policy_static_coverage")
    reachable_hashes = receipt.get("reachable_policy_source_hashes")
    source_hashes = receipt.get("source_hashes")
    checks_pass = bool(
        isinstance(checks, dict)
        and all(
            isinstance(checks.get(name), dict)
            and cast(dict[str, object], checks[name]).get("passed") is True
            for name in (
                "archive_static",
                "policy_static",
                "secret_scan",
                "source_identity",
                "supply_chain",
            )
        )
    )
    declared_coverage_pass = bool(
        isinstance(coverage, dict)
        and coverage.get("algorithm") == "static-first-party-import-closure-v0.1"
        and isinstance(coverage.get("entry_points"), list)
        and coverage.get("entry_points") == coverage.get("entry_points_reached")
        and len(cast(list[object], coverage["entry_points"])) > 0
        and coverage.get("limitations")
        == (
            "Static first-party import reachability does not prove runtime dynamic-import "
            "or native-extension containment."
        )
        and coverage.get("policy_scan_covers_reachable_paths") is True
        and isinstance(coverage.get("reachable_file_count"), int)
        and not isinstance(coverage.get("reachable_file_count"), bool)
        and cast(int, coverage["reachable_file_count"]) > 0
        and coverage.get("reachable_paths_hashed") is True
        and coverage.get("status") == "PASS"
        and isinstance(reachable_hashes, dict)
        and len(reachable_hashes) == coverage.get("reachable_file_count")
        and all(
            isinstance(name, str)
            and isinstance(digest, str)
            and re.fullmatch(r"sha256:[0-9a-f]{64}", digest) is not None
            for name, digest in reachable_hashes.items()
        )
    )
    candidate_set_passed = False
    reachable_recomputed = False
    live_source_hashes_match = False
    candidate_count: int | None = None
    if isinstance(inputs, dict):
        declared_candidates = inputs.get("candidate_paths")
        declared_reachable = inputs.get("reachable_policy_paths")
        try:
            candidates = _package_only_candidate_files(source_root)
            candidate_labels = [
                candidate.relative_to(source_root.resolve()).as_posix() for candidate in candidates
            ]
            candidate_count = len(candidate_labels)
            candidate_set_passed = declared_candidates == candidate_labels
            reachable_files = discover_reachable_policy_files(
                source_root.resolve(),
                candidate_files=candidates,
                entry_points=_PRODUCTION_POLICY_ENTRY_POINTS,
            )
            reachable_labels = [
                item.relative_to(source_root.resolve()).as_posix() for item in reachable_files
            ]
            reachable_recomputed = declared_reachable == reachable_labels
            recomputed_hashes: dict[str, str] = {}
            for relative in reachable_labels:
                lexical = source_root.resolve() / relative
                if lexical.is_symlink():
                    raise EvaluationError("Stage 09 reachable policy source is a symlink")
                resolved = lexical.resolve()
                resolved.relative_to(source_root.resolve())
                if not resolved.is_file() or resolved.is_symlink():
                    raise EvaluationError("Stage 09 reachable policy source is not a regular file")
                recomputed_hashes[relative] = sha256_file(resolved)
            policy_files = discover_policy_files(
                source_root.resolve(),
                candidate_files=candidates,
                entry_points=_PRODUCTION_POLICY_ENTRY_POINTS,
            )
            policy_labels = {
                item.relative_to(source_root.resolve()).as_posix() for item in policy_files
            }
            live_source_hashes_match = bool(
                reachable_labels
                and isinstance(reachable_hashes, dict)
                and recomputed_hashes == reachable_hashes
                and isinstance(source_hashes, dict)
                and all(source_hashes.get(key) == value for key, value in recomputed_hashes.items())
                and all(label in policy_labels for label in reachable_labels)
            )
        except (EvaluationError, OSError, ValueError):
            candidate_set_passed = False
            reachable_recomputed = False
            live_source_hashes_match = False
    coverage_pass = bool(
        declared_coverage_pass
        and isinstance(inputs, dict)
        and inputs.get("entry_points") == list(_PRODUCTION_POLICY_ENTRY_POINTS)
        and candidate_set_passed
        and reachable_recomputed
        and live_source_hashes_match
    )
    license_pass = bool(
        isinstance(license_summary, dict)
        and license_summary.get("first_party_license_status") == "MIT-0"
        and license_summary.get("status") == "PASS"
        and license_summary.get("unknown_or_missing_metadata_count") == 0
        and license_summary.get("installed_version_mismatch_count") == 0
        and license_summary.get("not_evaluated_count") == 0
    )
    package_scope_pass = bool(
        receipt.get("integrity_scope") == "package-only-no-public-identifiers"
        and receipt.get("full_competition_integrity_status") == "NOT_EVALUATED_PUBLIC_IDENTIFIERS"
        and receipt.get("package_only_passed") is True
        and receipt.get("passed") is False
        and isinstance(inputs, dict)
        and inputs.get("manifest") is None
        and inputs.get("manifest_sha256") is None
        and inputs.get("run_state") is None
        and inputs.get("public_identifier_count") == 0
        and inputs.get("public_identifier_mode") == "disabled-package-only"
        and isinstance(assurance, dict)
        and assurance.get("public_identifier_scan")
        == "NOT_EVALUATED_PACKAGE_ONLY_NO_SEMANTIC_MANIFEST_ACCESS"
    )
    git = receipt.get("git")
    predicates = {
        "canonical_self_hash": canonical_self_hash,
        "checks": checks_pass,
        "clean_source": isinstance(git, dict)
        and git.get("commit") == expected_commit
        and git.get("dirty_worktree") is False,
        "complete_reachable_coverage": coverage_pass,
        "candidate_set": candidate_set_passed,
        "expected_commit_pinned": isinstance(expected_commit, str)
        and re.fullmatch(r"[0-9a-f]{40}", expected_commit) is not None,
        "file_hash": expected_file_hash is not None and file_hash == expected_file_hash,
        "findings": isinstance(finding_counts, dict)
        and finding_counts.get("blocking") == 0
        and finding_counts.get("warnings") == 0
        and finding_counts.get("total") == 0,
        "license_inventory": license_pass,
        "package_scope": package_scope_pass,
        "receipt_schema": receipt.get("schema") == "arc3.integrity.receipt.v0.2",
        "self_hash": expected_self_hash is not None
        and receipt.get("receipt_sha256") == expected_self_hash,
    }
    reachable_hash = (
        sha256_bytes(canonical_json_bytes(reachable_hashes))
        if isinstance(reachable_hashes, dict)
        else None
    )
    entry_points = coverage.get("entry_points") if isinstance(coverage, dict) else None
    reached = coverage.get("entry_points_reached") if isinstance(coverage, dict) else None
    projection = {
        "assurance_limitation": coverage.get("limitations") if isinstance(coverage, dict) else None,
        "candidate_file_count": candidate_count,
        "candidate_set_recomputed": candidate_set_passed,
        "entry_point_count": len(entry_points) if isinstance(entry_points, list) else None,
        "entry_points_reached": len(reached) if isinstance(reached, list) else None,
        "file_sha256": file_hash,
        "full_competition_integrity_status": receipt.get("full_competition_integrity_status"),
        "git_commit": git.get("commit") if isinstance(git, dict) else None,
        "integrity_scope": receipt.get("integrity_scope"),
        "license_inventory_passed": license_pass,
        "live_source_hashes_match": live_source_hashes_match,
        "package_only_passed": receipt.get("package_only_passed") is True,
        "path": path.resolve().as_posix(),
        "policy_scan_covers_reachable_paths": coverage.get("policy_scan_covers_reachable_paths")
        if isinstance(coverage, dict)
        else None,
        "public_identifier_mode": inputs.get("public_identifier_mode")
        if isinstance(inputs, dict)
        else None,
        "public_identifier_scan": assurance.get("public_identifier_scan")
        if isinstance(assurance, dict)
        else None,
        "reachable_file_count": coverage.get("reachable_file_count")
        if isinstance(coverage, dict)
        else None,
        "reachable_paths_hashed": coverage.get("reachable_paths_hashed")
        if isinstance(coverage, dict)
        else None,
        "reachable_paths_recomputed": reachable_recomputed,
        "reachable_source_hashes_sha256": reachable_hash,
        "receipt_sha256": receipt.get("receipt_sha256"),
        "status": "PASS" if all(predicates.values()) else "FAIL",
    }
    return projection, predicates


def _prior_authority(
    integrity_receipt: Path = DEFAULT_PRIOR_INTEGRITY_RECEIPT,
    build_000_integrity_receipt: Path = DEFAULT_BUILD_000_INTEGRITY_RECEIPT,
    holdout_receipt: Path = HOLDOUT_NONCONSUMPTION_RECEIPT,
    *,
    build_000_root: Path = DEFAULT_BUILD_000_ROOT,
    build_001_root: Path = DEFAULT_BUILD_001_ROOT,
    expected_build_001_file_hash: str | None = None,
    expected_build_001_self_hash: str | None = None,
    expected_build_001_commit: str | None = None,
) -> dict[str, object]:
    expected_build_001_file_hash = (
        BUILD_001_PACKAGE_INTEGRITY_RECEIPT_SHA256
        if expected_build_001_file_hash is None
        else expected_build_001_file_hash
    )
    expected_build_001_self_hash = (
        BUILD_001_PACKAGE_INTEGRITY_SELF_HASH
        if expected_build_001_self_hash is None
        else expected_build_001_self_hash
    )
    expected_build_001_commit = (
        BUILD_001_PACKAGE_INTEGRITY_COMMIT
        if expected_build_001_commit is None
        else expected_build_001_commit
    )
    integrity_001, integrity_001_predicates = _package_integrity_authority(
        integrity_receipt,
        source_root=build_001_root,
        expected_file_hash=expected_build_001_file_hash,
        expected_self_hash=expected_build_001_self_hash,
        expected_commit=expected_build_001_commit,
    )
    integrity_000, integrity_000_predicates = _integrity_authority(
        build_000_integrity_receipt,
        expected_file_hash=BUILD_000_INTEGRITY_RECEIPT_SHA256,
        expected_self_hash=BUILD_000_INTEGRITY_SELF_HASH,
        expected_commit=FROZEN_BUILD_000_COMMIT,
    )
    development_000 = _development_integrity(build_000_root)
    development_001 = _development_integrity(build_001_root)
    development_identity = {
        "build_000": development_000,
        "build_001": development_001,
        "development_identity_count": len(DEVELOPMENT_GAMES),
        "identifier_list_hash": development_identifier_list_hash(),
        "identifier_string_count": len(DEVELOPMENT_GAMES) * 2,
        "identity_values_disclosed": False,
        "limitations": (
            "Direct static scan only; dynamic-import and native-extension behavior is not proven."
        ),
        "scope": "frozen-exposed-development-game-id-and-stable-name-pairs",
    }
    holdout_hash = sha256_file(holdout_receipt) if holdout_receipt.is_file() else None
    holdout = load_json(holdout_receipt) if holdout_receipt.is_file() else {}
    holdout_projection = holdout.get("integrity")
    predicates = {
        "build_000_development_scan": development_000["passed"] is True,
        "build_000_full_integrity": all(integrity_000_predicates.values()),
        "build_001_development_scan": development_001["passed"] is True,
        "build_001_package_integrity": all(integrity_001_predicates.values()),
        "development_identity": development_identity["development_identity_count"]
        == len(DEVELOPMENT_GAMES)
        and development_identity["identifier_list_hash"] == development_identifier_list_hash(),
        "holdout_file_hash": holdout_hash == HOLDOUT_NONCONSUMPTION_RECEIPT_SHA256,
        "holdout_manifest_hash": isinstance(holdout_projection, dict)
        and holdout_projection.get("holdout_manifest_sha256") == PUBLIC_PARTITION_MANIFEST_SHA256,
        "holdout_nonconsumption": isinstance(holdout_projection, dict)
        and holdout_projection.get("holdout_sealed") is True
        and holdout_projection.get("public_holdout_game_ids_selected") == 0
        and holdout_projection.get("public_holdout_gameplay_events") == 0
        and holdout_projection.get("holdout_manifest_loaded_as_gameplay_metadata") is False,
    }
    authority = cast(
        dict[str, object],
        seal_object(
            {
                "schema": PRIOR_AUTHORITY_SCHEMA,
                "assurance_scope": {
                    "build_000": "historic-full-public-integrity-receipt",
                    "build_001": "package-only-plus-frozen-development-identifiers",
                    "limitations": (
                        "Static-only composite; runtime dynamic-import and native-extension "
                        "containment are not proven."
                    ),
                },
                "full_public_integrity_status": ("NOT_EVALUATED_BUILD_001_PUBLIC_IDENTIFIERS"),
                "holdout": {
                    "file_sha256": holdout_hash,
                    "identities_loaded": 0,
                    "manifest_loaded_as_metadata": False,
                    "path": holdout_receipt.resolve().as_posix(),
                    "pinned_manifest_sha256": PUBLIC_PARTITION_MANIFEST_SHA256,
                    "public_holdout_gameplay_events": 0,
                    "receipt_confirms_manifest_sha256": (
                        holdout_projection.get("holdout_manifest_sha256")
                        if isinstance(holdout_projection, dict)
                        else None
                    ),
                    "status": "SEALED_UNCONSUMED"
                    if predicates["holdout_nonconsumption"]
                    else "UNVERIFIED",
                },
                "integrity": {
                    "build_000_full": integrity_000,
                    "build_001_package_only": integrity_001,
                    "development_scans": development_identity,
                },
                "passed": all(predicates.values()),
                "predicates": predicates,
            },
            hash_field="authority_hash",
        ),
    )
    return validate_prior_authority_observation(authority)


def _prior_authority_stable(before: Mapping[str, object], after: Mapping[str, object]) -> bool:
    return prior_authority_stable(before, after)


def _environment_cache_identity(root: Path) -> dict[str, object]:
    resolved = root.resolve()
    rows: list[tuple[str, str, int, str | None]] = []
    directory_count = 0
    file_count = 0
    file_bytes = 0
    symlink_count = 0
    if resolved.is_dir():
        for path in sorted(resolved.rglob("*")):
            relative = path.relative_to(resolved).as_posix()
            if path.is_symlink():
                symlink_count += 1
                rows.append(("symlink", relative, 0, None))
            elif path.is_dir():
                directory_count += 1
                rows.append(("directory", relative, 0, None))
            elif path.is_file():
                length = path.stat().st_size
                file_count += 1
                file_bytes += length
                rows.append(("file", relative, length, sha256_file(path)))
    actual = {
        "aggregate_sha256": sha256_bytes(canonical_json_bytes(rows)),
        "directory_count": directory_count,
        "entry_count": len(rows),
        "recursive_bytes": file_bytes,
        "recursive_file_count": file_count,
        "root_file_count": (
            sum(path.is_file() for path in resolved.iterdir()) if resolved.is_dir() else 0
        ),
        "top_level_directory_count": (
            sum(path.is_dir() for path in resolved.iterdir()) if resolved.is_dir() else 0
        ),
    }
    predicates = {
        **{key: actual[key] == value for key, value in EXPECTED_ENVIRONMENT_CACHE.items()},
        "root_present": resolved.is_dir(),
        "symlinks_absent": symlink_count == 0,
    }
    cache = cast(
        dict[str, object],
        seal_object(
            {
                "schema": ENVIRONMENT_CACHE_SCHEMA,
                "actual": actual,
                "expected": EXPECTED_ENVIRONMENT_CACHE,
                "holdout_identities_loaded": 0,
                "passed": all(predicates.values()),
                "predicates": predicates,
                "root": resolved.as_posix(),
            },
            hash_field="cache_identity_hash",
        ),
    )
    return validate_environment_cache_observation(cache)


def _environment_cache_stable(before: Mapping[str, object], after: Mapping[str, object]) -> bool:
    return environment_cache_stable(before, after)


def _observe_execution_boundaries(
    *,
    harness_source_expected: Mapping[str, object],
    environments: Path,
    build_000_root: Path,
    build_001_root: Path,
    prior_integrity_receipt: Path,
    build_000_integrity_receipt: Path,
    short_circuit_on_harness_failure: bool = True,
) -> tuple[
    dict[str, object],
    dict[str, object] | None,
    dict[str, object] | None,
    dict[str, object] | None,
]:
    harness = _harness_source_identity(harness_source_expected)
    if harness.get("passed") is not True and short_circuit_on_harness_failure:
        return harness, None, None, None
    runtime = _runtime_environment_identity()
    authority = _prior_authority(
        prior_integrity_receipt,
        build_000_integrity_receipt,
        HOLDOUT_NONCONSUMPTION_RECEIPT,
        build_000_root=build_000_root,
        build_001_root=build_001_root,
    )
    cache = _environment_cache_identity(environments)
    return harness, runtime, authority, cache


def _execution_boundaries_ready(
    observations: tuple[
        Mapping[str, object],
        Mapping[str, object] | None,
        Mapping[str, object] | None,
        Mapping[str, object] | None,
    ],
) -> bool:
    return all(item is not None and item.get("passed") is True for item in observations)


def _preflight_boundary_snapshot(
    check: Mapping[str, object],
) -> tuple[
    dict[str, object],
    dict[str, object],
    dict[str, object],
    dict[str, object],
    dict[str, object],
    dict[str, object],
]:
    """Recover the exact externally bound identities used to reconstruct a cell."""

    raw_harness = check.get("harness_source")
    raw_runtime = check.get("runtime_environment")
    raw_authority = check.get("prior_authority")
    raw_cache = check.get("environment_cache")
    if not all(isinstance(item, dict) for item in (raw_harness, raw_runtime, raw_cache)):
        raise EvaluationError("Stage 09 preflight execution identity is absent")
    harness = cast(dict[str, object], raw_harness)
    runtime = cast(dict[str, object], raw_runtime)
    cache = cast(dict[str, object], raw_cache)
    expected_harness = harness.get("expected")
    harness_start = harness.get("start")
    expected_runtime = runtime.get("expected")
    runtime_start = runtime.get("start")
    cache_start = cache.get("start")
    if not all(
        isinstance(item, dict)
        for item in (
            expected_harness,
            harness_start,
            expected_runtime,
            runtime_start,
            raw_authority,
            cache_start,
        )
    ):
        raise EvaluationError("Stage 09 preflight execution identity is malformed")
    typed_harness = validate_harness_source_binding(cast(dict[str, object], expected_harness))
    typed_harness_start = validate_harness_source_observation(
        cast(dict[str, object], harness_start), expected=typed_harness
    )
    typed_runtime = validate_runtime_environment_binding(cast(dict[str, object], expected_runtime))
    typed_runtime_start = validate_runtime_environment_observation(
        cast(dict[str, object], runtime_start), expected=typed_runtime
    )
    typed_authority = validate_prior_authority_observation(cast(dict[str, object], raw_authority))
    typed_cache = validate_environment_cache_observation(cast(dict[str, object], cache_start))
    if any(
        item.get("passed") is not True
        for item in (
            typed_harness_start,
            typed_runtime_start,
            typed_authority,
            typed_cache,
        )
    ):
        raise EvaluationError("Stage 09 preflight execution identity does not pass")
    return (
        typed_harness,
        typed_harness_start,
        typed_runtime,
        typed_runtime_start,
        typed_authority,
        typed_cache,
    )


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
            _lexical_python_launcher(),
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
        "finding_count": len(rows),
        "findings": rows,
        "passed": bool(files) and not rows,
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
    prior_integrity_receipt: Path,
    build_000_integrity_receipt: Path,
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
        prior_integrity_receipt,
        build_000_integrity_receipt,
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
        DEFAULT_PRIOR_INTEGRITY_RECEIPT,
        DEFAULT_BUILD_000_INTEGRITY_RECEIPT,
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


def _predeclaration_authority(*, live_validated: bool = True) -> dict[str, object]:
    if live_validated:
        declaration = validate_predeclaration_bytes(
            PREDECLARATION.read_bytes(), expected_file_sha256=PREDECLARATION_FILE_SHA256
        )
        amendment = validate_predeclaration_amendment_bytes(
            PREDECLARATION_AMENDMENT.read_bytes(),
            original=declaration,
            expected_file_sha256=PREDECLARATION_AMENDMENT_FILE_SHA256,
        )
        original_hash = sha256_file(PREDECLARATION)
        amendment_hash = sha256_file(PREDECLARATION_AMENDMENT)
    else:
        declaration = {"predeclaration_core_hash": PREDECLARATION_CORE_HASH}
        amendment = {
            "amendment_core_hash": PREDECLARATION_AMENDMENT_CORE_HASH,
            "result_state": "READY_NOT_EXECUTED",
        }
        original_hash = PREDECLARATION_FILE_SHA256
        amendment_hash = PREDECLARATION_AMENDMENT_FILE_SHA256
    return {
        "original": {
            "path": PREDECLARATION.resolve().as_posix(),
            "file_sha256": original_hash,
            "core_hash": declaration["predeclaration_core_hash"],
            "preserved_unchanged": True,
        },
        "amendment": {
            "path": PREDECLARATION_AMENDMENT.resolve().as_posix(),
            "file_sha256": amendment_hash,
            "core_hash": amendment["amendment_core_hash"],
            "result_state": amendment["result_state"],
        },
        "effective_build_001_commit": FROZEN_BUILD_001_COMMIT,
        "effective_build_001_tree": FROZEN_BUILD_001_TREE,
        "effective_build_001_source_sha256": FROZEN_BUILD_001_SOURCE_SHA256,
        "effective_matrix_hash": matrix_hash(),
        "live_validated": live_validated,
    }


def preflight(
    *,
    harness_source_expected: Mapping[str, object],
    output: Path = DEFAULT_OUTPUT,
    work_root: Path = DEFAULT_WORK_ROOT,
    exposure: Path = DEFAULT_EXPOSURE,
    recordings: Path = DEFAULT_RECORDINGS,
    environments: Path = DEFAULT_ENVIRONMENTS,
    build_000_root: Path = DEFAULT_BUILD_000_ROOT,
    build_001_root: Path = DEFAULT_BUILD_001_ROOT,
    stage08_result: Path = DEFAULT_STAGE08_RESULT,
    stage08_exposure: Path = DEFAULT_STAGE08_EXPOSURE,
    prior_integrity_receipt: Path = DEFAULT_PRIOR_INTEGRITY_RECEIPT,
    build_000_integrity_receipt: Path = DEFAULT_BUILD_000_INTEGRITY_RECEIPT,
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
            prior_integrity_receipt=prior_integrity_receipt,
            build_000_integrity_receipt=build_000_integrity_receipt,
        )
    expected_harness = validate_harness_source_binding(harness_source_expected)
    harness_start = _harness_source_identity(expected_harness)
    if harness_start["passed"] is not True:
        return cast(
            dict[str, object],
            seal_object(
                {
                    "schema": PREFLIGHT_SCHEMA,
                    "status": "FAILED_INFRASTRUCTURE",
                    "gameplay_opened": False,
                    "holdout": {
                        "identities_loaded": 0,
                        "manifest_loaded_as_metadata": False,
                        "public_holdout_gameplay_events": 0,
                        "status": "UNVERIFIED",
                    },
                    "harness_source": {
                        "expected": expected_harness,
                        "start": harness_start,
                    },
                    "runtime_environment": {
                        "expected": EXPECTED_RUNTIME_ENVIRONMENT,
                        "start": None,
                        "status": "NOT_EVALUATED_HARNESS_SOURCE_FAILED",
                    },
                    "prior_authority": None,
                    "environment_cache": None,
                    "runtime_identity": _runtime_identity(),
                    "predeclaration_authority": _predeclaration_authority(live_validated=False),
                    "predicates": {"harness_source": False},
                },
                hash_field="preflight_hash",
            ),
        )
    declaration = validate_predeclaration_bytes(
        PREDECLARATION.read_bytes(), expected_file_sha256=PREDECLARATION_FILE_SHA256
    )
    amendment = validate_predeclaration_amendment_bytes(
        PREDECLARATION_AMENDMENT.read_bytes(),
        original=declaration,
        expected_file_sha256=PREDECLARATION_AMENDMENT_FILE_SHA256,
    )
    predeclaration_authority = _predeclaration_authority()
    runtime_start = _runtime_environment_identity()
    authority_start = _prior_authority(
        prior_integrity_receipt,
        build_000_integrity_receipt,
        HOLDOUT_NONCONSUMPTION_RECEIPT,
        build_000_root=build_000_root,
        build_001_root=build_001_root,
    )
    cache_start = _environment_cache_identity(environments)
    identity_predicates = {
        "environment_cache": cache_start["passed"] is True,
        "harness_source": harness_start["passed"] is True,
        "prior_authority": authority_start["passed"] is True,
        "runtime_environment": runtime_start["passed"] is True,
    }
    if not all(identity_predicates.values()):
        return cast(
            dict[str, object],
            seal_object(
                {
                    "schema": PREFLIGHT_SCHEMA,
                    "status": "FAILED_INFRASTRUCTURE",
                    "gameplay_opened": False,
                    "holdout": {
                        "identities_loaded": 0,
                        "manifest_loaded_as_metadata": False,
                        "public_holdout_gameplay_events": 0,
                        "status": "UNVERIFIED",
                    },
                    "harness_source": {
                        "expected": expected_harness,
                        "start": harness_start,
                    },
                    "runtime_environment": {
                        "expected": EXPECTED_RUNTIME_ENVIRONMENT,
                        "start": runtime_start,
                    },
                    "prior_authority": authority_start,
                    "environment_cache": {"start": cache_start},
                    "runtime_identity": _runtime_identity(),
                    "predeclaration_authority": predeclaration_authority,
                    "predicates": identity_predicates,
                },
                hash_field="preflight_hash",
            ),
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
    authority_integrity = cast(dict[str, object], authority_start["integrity"])
    development_scans = cast(dict[str, object], authority_integrity["development_scans"])
    authority_predicates = cast(dict[str, object], authority_start["predicates"])
    integrity = {
        "build_000_development": cast(dict[str, object], development_scans["build_000"]),
        "build_001_development": cast(dict[str, object], development_scans["build_001"]),
        "build_001_package_only": {
            "passed": authority_predicates["build_001_package_integrity"] is True,
            "status": cast(dict[str, object], authority_integrity["build_001_package_only"])[
                "status"
            ],
        },
    }
    manifest_identity = {
        "pinned_sha256": PUBLIC_PARTITION_MANIFEST_SHA256,
        "semantic_access": False,
        "verified_by_prior_authority": authority_predicates["holdout_manifest_hash"] is True,
    }
    predicates = {
        "assets": assets["passed"] is True,
        "build_000_integrity": integrity["build_000_development"]["passed"] is True,
        "build_000_source": source_000["passed"] is True,
        "build_001_integrity": all(
            item["passed"] is True
            for item in (
                integrity["build_001_development"],
                integrity["build_001_package_only"],
            )
        ),
        "build_001_source": source_001["passed"] is True,
        "inherited_exposures": inherited["passed"] is True,
        "manifest_identity": manifest_identity["verified_by_prior_authority"] is True,
        "matrix": len(build_matrix()) == EXPECTED_CELL_COUNT,
        "predecessor": predecessor["passed"] is True,
        "worker": WORKER.is_file(),
        **identity_predicates,
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
        "predeclaration_amendment_core_hash": amendment["amendment_core_hash"],
        "predeclaration_amendment_sha256": sha256_file(PREDECLARATION_AMENDMENT),
        "predeclaration_authority": predeclaration_authority,
        "matrix_hash": matrix_hash(),
        "sources": {"build_000": source_000, "build_001": source_001},
        "assets": assets,
        "stage08_predecessor": predecessor,
        "inherited_exposures": inherited,
        "stage09_exposure_event_count": len(current_events),
        "public_manifest_identity": manifest_identity,
        "competition_integrity": integrity,
        "runtime_identity": _runtime_identity(),
        "harness_source": {"expected": expected_harness, "start": harness_start},
        "runtime_environment": {
            "expected": EXPECTED_RUNTIME_ENVIRONMENT,
            "start": runtime_start,
        },
        "prior_authority": authority_start,
        "environment_cache": {"start": cache_start},
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


def _windows_job_for_suspended_process(process: subprocess.Popen[bytes]) -> int:
    if os.name != "nt":
        raise OSError("Windows Job Objects are unavailable")
    kernel32 = _windows_library("kernel32")
    kernel32.CreateJobObjectW.restype = ctypes.c_void_p
    job = kernel32.CreateJobObjectW(None, None)
    if not job:
        raise OSError("CreateJobObjectW failed")
    handle = int(job)
    try:
        limits = _WindowsJobExtendedLimits()
        limits.basic.limit_flags = WINDOWS_JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not kernel32.SetInformationJobObject(
            ctypes.c_void_p(handle),
            9,
            ctypes.byref(limits),
            ctypes.sizeof(limits),
        ):
            raise OSError("SetInformationJobObject failed")
        process_handle = ctypes.c_void_p(int(cast(Any, process)._handle))
        if not kernel32.AssignProcessToJobObject(ctypes.c_void_p(handle), process_handle):
            raise OSError("AssignProcessToJobObject failed")
        ntdll = _windows_library("ntdll")
        status = int(ntdll.NtResumeProcess(process_handle))
        if status != 0:
            raise OSError(f"NtResumeProcess failed with NTSTATUS {status:#x}")
    except OSError as error:
        try:
            _close_windows_handle(handle)
        except OSError as close_error:
            raise OSError(f"{error}; {close_error}") from error
        raise
    return handle


def _windows_job_active_processes(handle: int) -> int:
    accounting = _WindowsJobAccounting()
    if not _windows_library("kernel32").QueryInformationJobObject(
        ctypes.c_void_p(handle),
        1,
        ctypes.byref(accounting),
        ctypes.sizeof(accounting),
        None,
    ):
        raise OSError("QueryInformationJobObject failed")
    return int(accounting.active_processes)


def _wait_for_windows_job_empty(
    handle: int, *, timeout_seconds: float = 5.0
) -> tuple[int | None, str | None]:
    deadline = time.perf_counter() + timeout_seconds
    while True:
        try:
            active = _windows_job_active_processes(handle)
        except OSError as error:
            return None, f"{type(error).__name__}: {error}"
        if active == 0 or time.perf_counter() >= deadline:
            return active, None
        time.sleep(0.05)


def _checked_windows_close_handle(close_handle: Any, handle: int) -> None:
    """Close one pointer-width HANDLE and reject a failed kernel transition."""

    close_handle.argtypes = [ctypes.c_void_p]
    close_handle.restype = ctypes.c_int
    if not close_handle(ctypes.c_void_p(handle)):
        raise OSError("CloseHandle failed")


def _close_windows_handle(handle: int) -> None:
    if os.name != "nt":
        raise OSError("Windows HANDLE close is unavailable")
    _checked_windows_close_handle(_windows_library("kernel32").CloseHandle, handle)


def _cleanup_assigned_containment(
    process: subprocess.Popen[bytes] | None,
    *,
    windows_job_handle: int | None,
) -> dict[str, object]:
    """Drain and verify the whole assigned process container after root exit."""

    if os.name == "nt":
        if windows_job_handle is None:
            return {
                "active_processes_after": None,
                "active_processes_before": None,
                "assigned_before_resume": False,
                "authority": "windows-job-object",
                "close_attempted": False,
                "close_error": None,
                "close_succeeded": None,
                "error": "job assignment unavailable",
                "limitation": None,
                "members_after": None,
                "members_before": None,
                "observation_error_before": "job assignment unavailable",
                "passed": False,
                "termination_attempted": False,
                "termination_error": None,
                "termination_succeeded": None,
                "verification_error": "job assignment unavailable",
            }
        active_before, observation_error = _wait_for_windows_job_empty(
            windows_job_handle, timeout_seconds=0.0
        )
        termination_attempted = active_before is None or active_before > 0
        termination_error: str | None = None
        termination_succeeded: bool | None = None
        if termination_attempted:
            try:
                succeeded = bool(
                    _windows_library("kernel32").TerminateJobObject(
                        ctypes.c_void_p(windows_job_handle), 1
                    )
                )
                if not succeeded:
                    raise OSError("TerminateJobObject failed")
                termination_succeeded = True
            except OSError as error:
                termination_error = f"{type(error).__name__}: {error}"
                termination_succeeded = False
        active_after, verification_error = _wait_for_windows_job_empty(windows_job_handle)
        errors = tuple(
            item
            for item in (observation_error, termination_error, verification_error)
            if item is not None
        )
        passed = (
            active_after == 0
            and not errors
            and (not termination_attempted or termination_succeeded is True)
        )
        return {
            "active_processes_after": active_after,
            "active_processes_before": active_before,
            "assigned_before_resume": True,
            "authority": "windows-job-object-assigned-before-resume",
            "close_attempted": False,
            "close_error": None,
            "close_succeeded": None,
            "error": "; ".join(errors) if errors else None,
            "limitation": None,
            "members_after": None,
            "members_before": None,
            "observation_error_before": observation_error,
            "passed": passed,
            "termination_attempted": termination_attempted,
            "termination_error": termination_error,
            "termination_succeeded": termination_succeeded,
            "verification_error": verification_error,
        }

    if process is None:
        return {
            "active_processes_after": None,
            "active_processes_before": None,
            "assigned_before_resume": False,
            "authority": "posix-new-session-process-group",
            "close_attempted": False,
            "close_error": None,
            "close_succeeded": None,
            "error": "process-group assignment unavailable",
            "limitation": "setsid-or-double-fork escape is not OS-contained",
            "members_after": None,
            "members_before": None,
            "observation_error_before": "process-group assignment unavailable",
            "passed": False,
            "termination_attempted": False,
            "termination_error": None,
            "termination_succeeded": None,
            "verification_error": "process-group assignment unavailable",
        }
    members_before, observation_error = _wait_for_process_group_exit(
        process.pid, timeout_seconds=0.0
    )
    termination_attempted = bool(members_before) or observation_error is not None
    termination_error = None
    termination_succeeded = None
    if termination_attempted:
        try:
            kill_group = getattr(os, "killpg", None)
            if not callable(kill_group):
                raise OSError("process-group termination is unavailable")
            kill_group(process.pid, int(getattr(signal, "SIGKILL", signal.SIGTERM)))
            termination_succeeded = True
        except ProcessLookupError:
            # A member may exit after the observation.  Only the fresh empty
            # group observation below can turn that race into authority.
            termination_succeeded = True
        except OSError as error:
            termination_error = f"{type(error).__name__}: {error}"
            termination_succeeded = False
    members_after, verification_error = _wait_for_process_group_exit(process.pid)
    errors = tuple(
        item
        for item in (observation_error, termination_error, verification_error)
        if item is not None
    )
    passed = (
        not members_after
        and not errors
        and (not termination_attempted or termination_succeeded is True)
    )
    return {
        "active_processes_after": len(members_after),
        "active_processes_before": len(members_before),
        "assigned_before_resume": True,
        "authority": "posix-new-session-process-group",
        "close_attempted": False,
        "close_error": None,
        "close_succeeded": None,
        "error": "; ".join(errors) if errors else None,
        "limitation": "setsid-or-double-fork escape is not OS-contained",
        "members_after": members_after,
        "members_before": members_before,
        "observation_error_before": observation_error,
        "passed": passed,
        "termination_attempted": termination_attempted,
        "termination_error": termination_error,
        "termination_succeeded": termination_succeeded,
        "verification_error": verification_error,
    }


def _terminate_tree(
    process: subprocess.Popen[bytes],
    *,
    expected_root_token: str | None = None,
    windows_job_handle: int | None = None,
) -> dict[str, object]:
    method = "windows-taskkill-tree" if os.name == "nt" else "posix-killpg"
    tree_before, enumeration_error = _process_tree_snapshot(
        process.pid,
        expected_root_token=expected_root_token,
    )
    error: str | None = None
    returncode: int | None = None
    try:
        if os.name == "nt" and windows_job_handle is not None:
            if not _windows_library("kernel32").TerminateJobObject(
                ctypes.c_void_p(windows_job_handle), 1
            ):
                raise OSError("TerminateJobObject failed")
            method = "windows-kill-on-close-job-object"
            returncode = 0
        elif enumeration_error is not None:
            # A PID-targeted tree command is unsafe when the exact root identity
            # could not be enumerated.  The Popen handle still permits a narrow
            # root-only kill, but the receipt must remain failed closed.
            process.kill()
            method = "root-handle-kill-after-tree-enumeration-failure"
        elif os.name == "nt":
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
        try:
            process.kill()
        except OSError as caught:
            fallback_error = f"{type(caught).__name__}: {caught}"
            error = fallback_error if error is None else f"{error}; {fallback_error}"
    try:
        process.wait(timeout=5.0)
    except (OSError, subprocess.TimeoutExpired) as caught:
        wait_error = f"{type(caught).__name__}: {caught}"
        error = wait_error if error is None else f"{error}; {wait_error}"
    if os.name == "nt" and windows_job_handle is not None:
        active_after, verification_error = _wait_for_windows_job_empty(windows_job_handle)
        tree_live_after: list[dict[str, object]] = []
        tree_verified_empty = active_after == 0 and verification_error is None
        containment_authority = "windows-job-object-assigned-before-resume"
        containment_limit = None
    elif os.name != "nt":
        tree_live_after, verification_error = _wait_for_process_group_exit(process.pid)
        active_after = len(tree_live_after)
        tree_verified_empty = verification_error is None and not tree_live_after
        containment_authority = "posix-new-session-process-group"
        containment_limit = "setsid-or-double-fork escape is not OS-contained"
    else:
        tree_live_after, verification_error = _wait_for_process_tree_exit(tree_before)
        active_after = len(tree_live_after)
        tree_verified_empty = (
            enumeration_error is None and verification_error is None and not tree_live_after
        )
        containment_authority = "suspended-root-or-best-effort-tree"
        containment_limit = "not authoritative for a resumed uncontained process tree"
    return {
        "attempted": True,
        "command_succeeded": (
            (
                method in {"windows-taskkill-tree", "windows-kill-on-close-job-object"}
                and returncode == 0
            )
            or (method == "posix-killpg" and returncode is None and error is None)
        ),
        "error": error,
        "containment_active_processes_after": active_after,
        "containment_authority": containment_authority,
        "containment_limit": containment_limit,
        "method": method,
        "passed": tree_verified_empty,
        "process_tree_before": tree_before,
        "process_tree_enumeration_error": enumeration_error,
        "process_tree_live_after": tree_live_after,
        "process_tree_verification_error": verification_error,
        "process_tree_verified_empty": tree_verified_empty,
        "root_pid": process.pid,
        "root_process_creation_token": expected_root_token,
        "returncode": returncode,
    }


def _atomic_create(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())


def _atomic_create_or_verify(path: Path, content: bytes, *, label: str) -> None:
    """Create immutable bytes, accepting an exact pre-exposure crash remnant."""

    try:
        _atomic_create(path, content)
    except FileExistsError:
        if not path.is_file() or path.read_bytes() != content:
            raise EvaluationError(f"existing Stage 09 {label} bytes changed") from None


def _boot_identity() -> str:
    if os.name == "nt":
        try:
            result = subprocess.run(
                [
                    "powershell.exe",
                    "-NoProfile",
                    "-NonInteractive",
                    "-Command",
                    (
                        "(Get-CimInstance Win32_OperatingSystem)."
                        "LastBootUpTime.ToUniversalTime().Ticks"
                    ),
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=10.0,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise EvaluationError("Stage 09 boot identity is unavailable") from error
        value = result.stdout.strip()
        if result.returncode or not value.isdigit():
            raise EvaluationError("Stage 09 boot identity is unavailable")
        return f"windows-cim:{value}"
    boot_id = Path("/proc/sys/kernel/random/boot_id")
    try:
        value = boot_id.read_text(encoding="ascii").strip()
    except (OSError, UnicodeDecodeError) as error:
        raise EvaluationError("Stage 09 boot identity is unavailable") from error
    if not value:
        raise EvaluationError("Stage 09 boot identity is unavailable")
    return f"linux-boot-id:{value}"


def _run_clock(
    work_root: Path,
    *,
    harness_binding_hash: object,
    create_missing: bool = True,
) -> dict[str, object]:
    path = work_root.resolve() / "run-clock.json"
    if path.is_file():
        receipt = _load_canonical_sealed(
            path,
            schema=RUN_CLOCK_SCHEMA,
            hash_field="run_clock_hash",
            label="run monotonic clock",
        )
        if (
            receipt.get("accounting") != "sealed-per-cell-active-segments"
            or receipt.get("clock") != "time.perf_counter_ns-per-active-segment"
            or receipt.get("harness_binding_hash") != harness_binding_hash
            or receipt.get("interruption_downtime_excluded") is not True
            or receipt.get("overall_active_wall_limit_ns")
            != int(OVERALL_ACTIVE_WALL_SECONDS * 1_000_000_000)
            or receipt.get("open_segment_conservative_charge_ns") != CELL_ADMISSION_CHARGE_NS
            or receipt.get("reboot_stable") is not True
            or receipt.get("terminal_write_reserve_ns") != TERMINAL_WRITE_RESERVE_NS
        ):
            raise EvaluationError("Stage 09 active-wall accounting identity changed")
        return cast(dict[str, object], receipt)
    if not create_missing:
        raise EvaluationError("Stage 09 run clock receipt is absent")
    payload = {
        "schema": RUN_CLOCK_SCHEMA,
        "accounting": "sealed-per-cell-active-segments",
        "clock": "time.perf_counter_ns-per-active-segment",
        "harness_binding_hash": harness_binding_hash,
        "interruption_downtime_excluded": True,
        "open_segment_conservative_charge_ns": CELL_ADMISSION_CHARGE_NS,
        "overall_active_wall_limit_ns": int(OVERALL_ACTIVE_WALL_SECONDS * 1_000_000_000),
        "reboot_stable": True,
        "terminal_write_reserve_ns": TERMINAL_WRITE_RESERVE_NS,
    }
    receipt = cast(dict[str, object], seal_object(payload, hash_field="run_clock_hash"))
    _atomic_create(path, canonical_json_bytes(receipt))
    return receipt


def _attach_run_clock(
    check: Mapping[str, object],
    *,
    work_root: Path,
    harness_binding_hash: object,
    create_missing: bool = True,
) -> dict[str, object]:
    clock = _run_clock(
        work_root,
        harness_binding_hash=harness_binding_hash,
        create_missing=create_missing,
    )
    payload = dict(check)
    payload.pop("preflight_hash", None)
    payload["run_clock"] = {
        "path": (work_root.resolve() / "run-clock.json").as_posix(),
        "receipt": clock,
        "sha256": sha256_file(work_root.resolve() / "run-clock.json"),
    }
    return cast(dict[str, object], seal_object(payload, hash_field="preflight_hash"))


def _clock_from_check(check: Mapping[str, object]) -> tuple[dict[str, object], Path]:
    projection = check.get("run_clock")
    if not isinstance(projection, dict) or set(projection) != {"path", "receipt", "sha256"}:
        raise EvaluationError("Stage 09 preflight run clock is absent")
    path_value = projection.get("path")
    receipt = projection.get("receipt")
    if not isinstance(path_value, str) or not isinstance(receipt, dict):
        raise EvaluationError("Stage 09 preflight run clock is malformed")
    path = Path(path_value)
    live = _load_canonical_sealed(
        path,
        schema=RUN_CLOCK_SCHEMA,
        hash_field="run_clock_hash",
        label="run monotonic clock",
    )
    if receipt != live or projection.get("sha256") != sha256_file(path):
        raise EvaluationError("Stage 09 preflight run clock changed")
    return cast(dict[str, object], live), path


def _cell_segment_payload(
    *,
    cell: DevelopmentCell,
    check: Mapping[str, object],
    boot_identity: str,
    started_perf_counter_ns: int,
) -> dict[str, object]:
    if (
        not isinstance(boot_identity, str)
        or not boot_identity
        or isinstance(started_perf_counter_ns, bool)
        or not isinstance(started_perf_counter_ns, int)
        or started_perf_counter_ns < 0
    ):
        raise EvaluationError("Stage 09 active cell-segment clock is invalid")
    clock, clock_path = _clock_from_check(check)
    payload = {
        "schema": CELL_SEGMENT_SCHEMA,
        "admission_charge_ns": CELL_ADMISSION_CHARGE_NS,
        "boot_identity": boot_identity,
        "cell_id": cell.cell_id,
        "cell_ordinal": cell.ordinal,
        "cell_spec_hash": cell.spec_hash,
        "interruption_recovery": "full-admission-charge-and-failed-infrastructure",
        "run_clock_hash": clock.get("run_clock_hash"),
        "run_clock_sha256": sha256_file(clock_path),
        "segment_started_perf_counter_ns": started_perf_counter_ns,
        "state": "OPEN",
    }
    return cast(dict[str, object], seal_object(payload, hash_field="cell_segment_hash"))


def _load_cell_segment(
    *,
    cell: DevelopmentCell,
    paths: Mapping[str, Path],
    check: Mapping[str, object],
) -> dict[str, object]:
    persisted = _load_canonical_sealed(
        paths["cell_segment"],
        schema=CELL_SEGMENT_SCHEMA,
        hash_field="cell_segment_hash",
        label="active cell segment",
    )
    boot = persisted.get("boot_identity")
    started = persisted.get("segment_started_perf_counter_ns")
    if not isinstance(boot, str) or isinstance(started, bool) or not isinstance(started, int):
        raise EvaluationError("Stage 09 active cell segment is malformed")
    expected = _cell_segment_payload(
        cell=cell,
        check=check,
        boot_identity=boot,
        started_perf_counter_ns=started,
    )
    if persisted != expected:
        raise EvaluationError("Stage 09 active cell segment does not reconstruct exactly")
    return cast(dict[str, object], persisted)


def _open_cell_segment(
    *,
    cell: DevelopmentCell,
    paths: Mapping[str, Path],
    check: Mapping[str, object],
) -> tuple[dict[str, object], int]:
    started = time.perf_counter_ns()
    if paths["cell_segment"].exists():
        raise EvaluationError("Stage 09 cell segment was already opened")
    segment = _cell_segment_payload(
        cell=cell,
        check=check,
        boot_identity=_boot_identity(),
        started_perf_counter_ns=started,
    )
    _atomic_create(paths["cell_segment"], canonical_json_bytes(segment))
    return segment, started


def _terminal_active_base_ns(value: Mapping[str, object]) -> int:
    resources = value.get("resources")
    active = (
        resources.get("cumulative_active_accounted_wall_ns")
        if isinstance(resources, dict)
        else None
    )
    if isinstance(active, bool) or not isinstance(active, int) or active < 0:
        raise EvaluationError("Stage 09 terminal active-wall resource projection is invalid")
    return active


def _bind_terminal_clock(
    value: Mapping[str, object],
    *,
    check: Mapping[str, object],
    active_before_output_ns: int,
) -> dict[str, object]:
    if (
        isinstance(active_before_output_ns, bool)
        or not isinstance(active_before_output_ns, int)
        or active_before_output_ns < 0
    ):
        raise EvaluationError("Stage 09 terminal pre-write wall is invalid")
    clock, clock_path = _clock_from_check(check)
    limit = int(OVERALL_ACTIVE_WALL_SECONDS * 1_000_000_000)
    payload = dict(value)
    payload.pop("artifact_core_hash", None)
    payload["run_clock"] = {
        "path": clock_path.resolve().as_posix(),
        "run_clock_hash": clock.get("run_clock_hash"),
        "sha256": sha256_file(clock_path),
    }
    payload["run_active_wall"] = {
        "accounting": "sealed-per-cell-active-segments",
        "active_before_output_ns": active_before_output_ns,
        "interruption_downtime_excluded": True,
        "overall_active_wall_limit_ns": limit,
        "terminal_write_reserve_ns": TERMINAL_WRITE_RESERVE_NS,
        "within_prewrite_reserve": active_before_output_ns <= limit - TERMINAL_WRITE_RESERVE_NS,
    }
    return cast(dict[str, object], seal_object(payload, hash_field="artifact_core_hash"))


def _terminal_finalization_path(output: Path) -> Path:
    return Path(f"{output.resolve()}.finalization.json")


def _terminal_evidence_authority(check: Mapping[str, object]) -> dict[str, object]:
    predeclaration = check.get("predeclaration_authority")
    if not isinstance(predeclaration, dict) or predeclaration != _predeclaration_authority():
        raise EvaluationError("Stage 09 terminal predeclaration authority changed")
    prior_value = check.get("prior_authority")
    if not isinstance(prior_value, dict):
        raise EvaluationError("Stage 09 terminal prior authority is absent")
    prior = validate_prior_authority_observation(prior_value)
    if prior.get("passed") is not True:
        raise EvaluationError("Stage 09 terminal prior authority does not pass")
    integrity = prior.get("integrity")
    if not isinstance(integrity, dict):
        raise EvaluationError("Stage 09 terminal integrity projection is absent")
    package = integrity.get("build_001_package_only")
    scans = integrity.get("development_scans")
    holdout = prior.get("holdout")
    if (
        not isinstance(package, dict)
        or not isinstance(scans, dict)
        or not isinstance(holdout, dict)
    ):
        raise EvaluationError("Stage 09 terminal composite authority is malformed")
    build_000_scan = scans.get("build_000")
    build_001_scan = scans.get("build_001")
    if not isinstance(build_000_scan, dict) or not isinstance(build_001_scan, dict):
        raise EvaluationError("Stage 09 terminal development scans are absent")
    projection = {
        "predeclaration": predeclaration,
        "prior_authority_hash": prior["authority_hash"],
        "full_public_integrity_status": prior["full_public_integrity_status"],
        "build_001_package_only": {
            "file_sha256": package["file_sha256"],
            "receipt_sha256": package["receipt_sha256"],
            "git_commit": package["git_commit"],
            "status": package["status"],
            "package_only_passed": package["package_only_passed"],
            "candidate_set_recomputed": package["candidate_set_recomputed"],
            "reachable_paths_recomputed": package["reachable_paths_recomputed"],
            "live_source_hashes_match": package["live_source_hashes_match"],
            "policy_scan_covers_reachable_paths": package["policy_scan_covers_reachable_paths"],
        },
        "development_scans": {
            "identifier_list_hash": scans["identifier_list_hash"],
            "development_identity_count": scans["development_identity_count"],
            "identifier_string_count": scans["identifier_string_count"],
            "identity_values_disclosed": scans["identity_values_disclosed"],
            "build_000_finding_count": build_000_scan["finding_count"],
            "build_001_finding_count": build_001_scan["finding_count"],
            "build_000_passed": build_000_scan["passed"],
            "build_001_passed": build_001_scan["passed"],
        },
        "holdout": {
            "file_sha256": holdout["file_sha256"],
            "pinned_manifest_sha256": holdout["pinned_manifest_sha256"],
            "identities_loaded": holdout["identities_loaded"],
            "manifest_loaded_as_metadata": holdout["manifest_loaded_as_metadata"],
            "public_holdout_gameplay_events": holdout["public_holdout_gameplay_events"],
            "status": holdout["status"],
        },
        "assurance_limitation": (
            "Package and development scans are static; dynamic-import and native-extension "
            "containment are not proven; Build 001 public identifiers were not fully evaluated."
        ),
    }
    package_projection = cast(dict[str, object], projection["build_001_package_only"])
    scans_projection = cast(dict[str, object], projection["development_scans"])
    holdout_projection = cast(dict[str, object], projection["holdout"])
    if (
        package_projection
        != {
            "file_sha256": BUILD_001_PACKAGE_INTEGRITY_RECEIPT_SHA256,
            "receipt_sha256": BUILD_001_PACKAGE_INTEGRITY_SELF_HASH,
            "git_commit": FROZEN_BUILD_001_COMMIT,
            "status": "PASS",
            "package_only_passed": True,
            "candidate_set_recomputed": True,
            "reachable_paths_recomputed": True,
            "live_source_hashes_match": True,
            "policy_scan_covers_reachable_paths": True,
        }
        or scans_projection["identifier_list_hash"] != development_identifier_list_hash()
        or scans_projection["development_identity_count"] != len(DEVELOPMENT_GAMES)
        or scans_projection["identifier_string_count"] != len(DEVELOPMENT_GAMES) * 2
        or scans_projection["identity_values_disclosed"] is not False
        or scans_projection["build_000_finding_count"] != 0
        or scans_projection["build_001_finding_count"] != 0
        or scans_projection["build_000_passed"] is not True
        or scans_projection["build_001_passed"] is not True
        or holdout_projection["file_sha256"] != HOLDOUT_NONCONSUMPTION_RECEIPT_SHA256
        or holdout_projection["pinned_manifest_sha256"] != PUBLIC_PARTITION_MANIFEST_SHA256
        or holdout_projection["identities_loaded"] != 0
        or holdout_projection["manifest_loaded_as_metadata"] is not False
        or holdout_projection["public_holdout_gameplay_events"] != 0
        or holdout_projection["status"] != "SEALED_UNCONSUMED"
    ):
        raise EvaluationError("Stage 09 terminal composite authority changed")
    return projection


def _terminal_finalization_payload(
    *,
    output: Path,
    terminal: Mapping[str, object],
    check: Mapping[str, object],
    active_after_output_ns: int,
    recovery_kind: str | None,
) -> dict[str, object]:
    wall = terminal.get("run_active_wall")
    if not isinstance(wall, dict):
        raise EvaluationError("Stage 09 terminal pre-write wall is absent")
    before = wall.get("active_before_output_ns")
    if (
        isinstance(active_after_output_ns, bool)
        or not isinstance(active_after_output_ns, int)
        or not isinstance(before, int)
        or isinstance(before, bool)
        or active_after_output_ns < before
        or recovery_kind
        not in {None, "terminal-output-durable-finalization-missing-after-interruption"}
    ):
        raise EvaluationError("Stage 09 terminal finalization wall is invalid")
    clock, clock_path = _clock_from_check(check)
    limit = int(OVERALL_ACTIVE_WALL_SECONDS * 1_000_000_000)
    payload = {
        "schema": TERMINAL_FINALIZATION_SCHEMA,
        "evidence_authority": _terminal_evidence_authority(check),
        "active_after_durable_output_ns": active_after_output_ns,
        "artifact_core_hash": terminal.get("artifact_core_hash"),
        "interruption_downtime_excluded": True,
        "measurement_scope": "sealed-cell-segments-plus-current-terminal-write-segment",
        "recovery_kind": recovery_kind,
        "timing_measurement_available": recovery_kind is None,
        "terminal_authority_passed": (recovery_kind is None and active_after_output_ns <= limit),
        "output_path": output.resolve().as_posix(),
        "output_sha256": sha256_file(output),
        "overall_active_wall_limit_ns": limit,
        "run_clock_hash": clock.get("run_clock_hash"),
        "run_clock_sha256": sha256_file(clock_path),
        "within_overall_active_wall": active_after_output_ns <= limit,
    }
    return cast(dict[str, object], seal_object(payload, hash_field="terminal_finalization_hash"))


def _write_terminal(
    output: Path, value: Mapping[str, object], *, check: Mapping[str, object]
) -> dict[str, object]:
    segment_started_ns = time.perf_counter_ns()
    active_base_ns = _terminal_active_base_ns(value)
    active_before_output_ns = active_base_ns + max(0, time.perf_counter_ns() - segment_started_ns)
    terminal = _bind_terminal_clock(
        value,
        check=check,
        active_before_output_ns=active_before_output_ns,
    )
    if (
        terminal.get("status") != "FAILED_INFRASTRUCTURE"
        and cast(dict[str, object], terminal["run_active_wall"]).get("within_prewrite_reserve")
        is not True
    ):
        raise EvaluationError("Stage 09 terminal cannot be admitted within its wall reserve")
    _atomic_create(output, canonical_json_bytes(terminal))
    active_after_output_ns = active_base_ns + max(0, time.perf_counter_ns() - segment_started_ns)
    finalization = _terminal_finalization_payload(
        output=output,
        terminal=terminal,
        check=check,
        active_after_output_ns=active_after_output_ns,
        recovery_kind=None,
    )
    _atomic_create(_terminal_finalization_path(output), canonical_json_bytes(finalization))
    if (
        terminal.get("status") != "FAILED_INFRASTRUCTURE"
        and finalization.get("within_overall_active_wall") is not True
    ):
        raise EvaluationError("Stage 09 terminal crossed the overall active-wall boundary")
    return terminal


def _validate_terminal_finalization(
    output: Path,
    terminal: Mapping[str, object],
    *,
    check: Mapping[str, object],
    recover_missing: bool = True,
) -> dict[str, object]:
    path = _terminal_finalization_path(output)
    if not path.exists():
        if not recover_missing:
            raise EvaluationError("Stage 09 terminal finalization receipt is absent")
        wall = terminal.get("run_active_wall")
        before = wall.get("active_before_output_ns") if isinstance(wall, dict) else None
        if isinstance(before, bool) or not isinstance(before, int) or before < 0:
            raise EvaluationError("Stage 09 terminal recovery wall is invalid")
        recovery = _terminal_finalization_payload(
            output=output,
            terminal=terminal,
            check=check,
            active_after_output_ns=before + CELL_ADMISSION_CHARGE_NS,
            recovery_kind="terminal-output-durable-finalization-missing-after-interruption",
        )
        _atomic_create(path, canonical_json_bytes(recovery))
    persisted = _load_canonical_sealed(
        path,
        schema=TERMINAL_FINALIZATION_SCHEMA,
        hash_field="terminal_finalization_hash",
        label="terminal finalization receipt",
    )
    active = persisted.get("active_after_durable_output_ns")
    recovery_kind = persisted.get("recovery_kind")
    if (
        isinstance(active, bool)
        or not isinstance(active, int)
        or active < 0
        or recovery_kind
        not in {None, "terminal-output-durable-finalization-missing-after-interruption"}
        or persisted.get("timing_measurement_available") is not (recovery_kind is None)
        or persisted.get("terminal_authority_passed")
        is not (
            recovery_kind is None and active <= int(OVERALL_ACTIVE_WALL_SECONDS * 1_000_000_000)
        )
    ):
        raise EvaluationError("Stage 09 terminal finalization active wall changed")
    expected = _terminal_finalization_payload(
        output=output,
        terminal=terminal,
        check=check,
        active_after_output_ns=active,
        recovery_kind=cast(str | None, recovery_kind),
    )
    if persisted != expected:
        raise EvaluationError("Stage 09 terminal finalization does not reconstruct exactly")
    if (
        terminal.get("status") != "FAILED_INFRASTRUCTURE"
        and persisted.get("terminal_authority_passed") is not True
    ):
        raise EvaluationError("Stage 09 claimed terminal exceeded the overall active wall")
    return persisted


def _cell_paths(work_root: Path, cell: DevelopmentCell) -> dict[str, Path]:
    prefix = f"{cell.ordinal:02d}-{cell.cell_id}"
    cell_root = work_root.resolve() / "cells" / prefix
    return {
        "abort": work_root.resolve() / "worker-aborts" / f"{prefix}.json",
        "authorization": work_root.resolve() / "launch-authorizations" / f"{prefix}.json",
        "cell_root": cell_root,
        "cell_segment": work_root.resolve() / "active-cell-segments" / f"{prefix}.json",
        "launch": work_root.resolve() / "process-launches" / f"{prefix}.json",
        "orphan": work_root.resolve() / "orphan-terminations" / f"{prefix}.json",
        "parent_evidence": work_root.resolve() / "parent-evidence" / f"{prefix}.json",
        "finalization": work_root.resolve() / "cell-finalizations" / f"{prefix}.json",
        "raw": cell_root / "raw-worker-result.json",
        "receipt": work_root.resolve() / "parent-receipts" / f"{prefix}.json",
        "spec": work_root.resolve() / "specs" / f"{prefix}.json",
        "spawn_intent": work_root.resolve() / "spawn-intents" / f"{prefix}.json",
        "stderr": work_root.resolve() / "parent-streams" / prefix / "stderr.bin",
        "stdout": work_root.resolve() / "parent-streams" / prefix / "stdout.bin",
        "supervision": work_root.resolve() / "supervision-receipts" / f"{prefix}.json",
    }


def _assert_unexposed_cell_clean(
    *, paths: Mapping[str, Path], recordings: Path, cell: DevelopmentCell
) -> None:
    evidence_paths = (
        paths["abort"],
        paths["authorization"],
        paths["cell_root"],
        paths["finalization"],
        paths["launch"],
        paths["orphan"],
        paths["parent_evidence"],
        paths["receipt"],
        paths["stderr"].parent,
        paths["supervision"],
        recordings.resolve() / cell.cell_id,
    )
    if any(path.exists() for path in evidence_paths):
        raise EvaluationError("unexposed Stage 09 cell already has execution evidence")


def _lexical_python_launcher() -> str:
    """Keep a venv launcher symlink lexical while runtime identity binds its target."""

    return os.path.abspath(sys.executable)


def _worker_command(
    spec_path: Path,
    raw_path: Path,
    *,
    launch_path: Path,
    authorization_path: Path,
    abort_path: Path,
    launch_token: str,
) -> tuple[str, ...]:
    return (
        _lexical_python_launcher(),
        "-I",
        str(WORKER.resolve()),
        "--spec",
        str(spec_path.resolve()),
        "--result",
        str(raw_path.resolve()),
        "--launch-receipt",
        str(launch_path.resolve()),
        "--authorization",
        str(authorization_path.resolve()),
        "--abort-receipt",
        str(abort_path.resolve()),
        "--launch-token",
        launch_token,
    )


def _spawn_intent_payload(
    *,
    cell: DevelopmentCell,
    paths: Mapping[str, Path],
    spec: Mapping[str, object],
    launch_token: str,
) -> dict[str, object]:
    if not re.fullmatch(r"[0-9a-f]{32}", launch_token):
        raise EvaluationError("Stage 09 spawn-intent launch token is invalid")
    command = _worker_command(
        paths["spec"],
        paths["raw"],
        launch_path=paths["launch"],
        authorization_path=paths["authorization"],
        abort_path=paths["abort"],
        launch_token=launch_token,
    )
    payload = {
        "schema": SPAWN_INTENT_SCHEMA,
        "cell_id": cell.cell_id,
        "cell_spec_hash": cell.spec_hash,
        "command": list(command),
        "command_sha256": sha256_bytes(canonical_json_bytes(list(command))),
        "environment_open_authority": "exact-launch-and-authorization-receipts-required",
        "launch_token": launch_token,
        "spec_sha256": sha256_file(paths["spec"]),
    }
    return cast(dict[str, object], seal_object(payload, hash_field="spawn_intent_hash"))


def _prepare_spawn_intent(
    *,
    cell: DevelopmentCell,
    paths: Mapping[str, Path],
    spec: Mapping[str, object],
) -> dict[str, object]:
    path = paths["spawn_intent"]
    if path.is_file():
        existing = _load_canonical_sealed(
            path,
            schema=SPAWN_INTENT_SCHEMA,
            hash_field="spawn_intent_hash",
            label="spawn intent",
        )
        launch_token = existing.get("launch_token")
        if not isinstance(launch_token, str):
            raise EvaluationError("Stage 09 spawn-intent launch token is absent")
        expected = _spawn_intent_payload(
            cell=cell,
            paths=paths,
            spec=spec,
            launch_token=launch_token,
        )
        if existing != expected:
            raise EvaluationError("Stage 09 spawn intent does not reconstruct exactly")
        return cast(dict[str, object], existing)
    intent = _spawn_intent_payload(
        cell=cell,
        paths=paths,
        spec=spec,
        launch_token=uuid.uuid4().hex,
    )
    _atomic_create(path, canonical_json_bytes(intent))
    return intent


def _validate_spawn_intent(
    *,
    cell: DevelopmentCell,
    paths: Mapping[str, Path],
    spec: Mapping[str, object],
) -> dict[str, object]:
    if not paths["spawn_intent"].is_file():
        raise EvaluationError("Stage 09 exposed cell spawn intent is absent")
    return _prepare_spawn_intent(cell=cell, paths=paths, spec=spec)


def _recorded_launch_token(command: object) -> str:
    if not isinstance(command, list) or len(command) < 2:
        raise EvaluationError("Stage 09 recorded worker command is invalid")
    try:
        index = command.index("--launch-token")
    except ValueError as error:
        raise EvaluationError("Stage 09 recorded worker command lacks a launch token") from error
    if (
        index != len(command) - 2
        or not isinstance(command[index + 1], str)
        or not command[index + 1]
    ):
        raise EvaluationError("Stage 09 recorded worker launch token is invalid")
    return cast(str, command[index + 1])


def _process_creation_token(pid: int) -> str | None:
    """Return a restart-comparable OS process creation identity when available."""

    if isinstance(pid, bool) or pid <= 0:
        return None
    if os.name == "nt":
        try:
            probe = subprocess.run(
                [
                    "powershell.exe",
                    "-NoProfile",
                    "-NonInteractive",
                    "-Command",
                    (
                        "$p=Get-CimInstance Win32_Process -Filter 'ProcessId = "
                        f"{pid}';if($null -ne $p){{$p.CreationDate.ToUniversalTime().Ticks}}"
                    ),
                ],
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
            # The comm field may contain spaces and parentheses; the fields after
            # its final ')' begin at field three.  Start time is field 22.
            suffix = stat[stat.rfind(")") + 2 :].split()
            start_ticks = suffix[19]
            command_hash = sha256_bytes(command_path.read_bytes())
        except (OSError, IndexError):
            return None
        return f"linux-proc:{start_ticks}:{command_hash}"
    return None


def _parse_windows_process_table_rows(rows: Sequence[object]) -> dict[int, dict[str, object]]:
    table: dict[int, dict[str, object]] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise EvaluationError("Stage 09 process-table row is malformed")
        pid = row.get("pid")
        parent_pid = row.get("parent_pid")
        command_line = row.get("command_line")
        token = row.get("process_creation_token")
        # Win32_Process includes the System Idle Process (PID 0), which is
        # not an addressable process and cannot be part of a launched tree.
        if pid == 0:
            continue
        if (
            isinstance(pid, bool)
            or not isinstance(pid, int)
            or pid <= 0
            or isinstance(parent_pid, bool)
            or not isinstance(parent_pid, int)
            or parent_pid < 0
            or not isinstance(command_line, str)
            or not isinstance(token, str)
            or not token.startswith("windows-cim:")
            or not token.removeprefix("windows-cim:").isdigit()
            or pid in table
        ):
            raise EvaluationError("Stage 09 process-table row is malformed")
        table[pid] = {
            "command_line": command_line,
            "parent_pid": parent_pid,
            "process_creation_token": token,
        }
    return table


def _process_table() -> dict[int, dict[str, object]]:
    """Enumerate exact process identities for tree-termination verification."""

    if os.name == "nt":
        command = (
            "$ErrorActionPreference='Stop';"
            "@(Get-CimInstance Win32_Process|ForEach-Object {"
            "[pscustomobject]@{pid=[int]$_.ProcessId;"
            "parent_pid=[int]$_.ParentProcessId;"
            "command_line=[string]$_.CommandLine;"
            "process_creation_token=('windows-cim:' + "
            "$_.CreationDate.ToUniversalTime().Ticks)}})|"
            "ConvertTo-Json -Compress"
        )
        try:
            probe = subprocess.run(
                [
                    "powershell.exe",
                    "-NoProfile",
                    "-NonInteractive",
                    "-Command",
                    command,
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=10.0,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise EvaluationError("Stage 09 process-table enumeration failed") from error
        if probe.returncode != 0 or not probe.stdout.strip():
            raise EvaluationError("Stage 09 process-table enumeration failed")
        try:
            decoded = json.loads(probe.stdout)
        except json.JSONDecodeError as error:
            raise EvaluationError("Stage 09 process-table enumeration is malformed") from error
        rows = decoded if isinstance(decoded, list) else [decoded]
        table = _parse_windows_process_table_rows(rows)
        if not table:
            raise EvaluationError("Stage 09 process-table enumeration is empty")
        return table

    proc_root = Path("/proc")
    if not proc_root.is_dir():
        raise EvaluationError("Stage 09 /proc process-table authority is unavailable")
    table = {}
    try:
        entries = tuple(proc_root.iterdir())
    except OSError as error:
        raise EvaluationError("Stage 09 process-table enumeration failed") from error
    for entry in entries:
        if not entry.name.isdigit():
            continue
        pid = int(entry.name)
        stat_path = entry / "stat"
        command_path = entry / "cmdline"
        try:
            stat = stat_path.read_text(encoding="utf-8")
            suffix = stat[stat.rfind(")") + 2 :].split()
            parent_pid = int(suffix[1])
            process_group_id = int(suffix[2])
            start_ticks = suffix[19]
            command_hash = sha256_bytes(command_path.read_bytes())
            command_line = command_path.read_bytes().decode("utf-8", errors="replace")
        except (OSError, IndexError, ValueError):
            # Processes may disappear during enumeration.  A surviving target
            # is still required below, and post-kill verification re-enumerates.
            continue
        table[pid] = {
            "command_line": command_line,
            "parent_pid": parent_pid,
            "process_creation_token": f"linux-proc:{start_ticks}:{command_hash}",
            "process_group_id": process_group_id,
        }
    if not table:
        raise EvaluationError("Stage 09 process-table enumeration is empty")
    return table


def _process_tree_snapshot(
    root_pid: int, *, expected_root_token: str | None
) -> tuple[list[dict[str, object]], str | None]:
    """Capture the exact root and every currently enumerated descendant."""

    try:
        table = _process_table()
    except EvaluationError as error:
        return [], str(error)
    root = table.get(root_pid)
    if root is None:
        return [], "Stage 09 process-tree root is absent during termination"
    root_token = root.get("process_creation_token")
    if expected_root_token is not None and root_token != expected_root_token:
        return [], "Stage 09 process-tree root creation identity changed"

    member_pids = {root_pid}
    changed = True
    while changed:
        changed = False
        for pid, row in table.items():
            if pid not in member_pids and row.get("parent_pid") in member_pids:
                member_pids.add(pid)
                changed = True
    if os.name != "nt":
        root_group = root.get("process_group_id")
        if isinstance(root_group, int):
            member_pids.update(
                pid for pid, row in table.items() if row.get("process_group_id") == root_group
            )
    snapshot = [
        {
            "parent_pid": table[pid]["parent_pid"],
            "pid": pid,
            "process_creation_token": table[pid]["process_creation_token"],
        }
        for pid in sorted(member_pids)
    ]
    return snapshot, None


def _spawn_intent_processes(
    launch_token: str,
) -> tuple[list[dict[str, object]], str | None]:
    """Find live processes carrying one unguessable, durable spawn token."""

    if not re.fullmatch(r"[0-9a-f]{32}", launch_token):
        return [], "Stage 09 spawn-intent process token is invalid"
    try:
        table = _process_table()
    except EvaluationError as error:
        return [], str(error)
    matches = [
        {
            "parent_pid": row["parent_pid"],
            "pid": pid,
            "process_creation_token": row["process_creation_token"],
        }
        for pid, row in table.items()
        if launch_token in cast(str, row.get("command_line", ""))
    ]
    matches.sort(key=lambda item: cast(int, item["pid"]))
    return matches, None


def _exact_live_processes(
    snapshot: Sequence[Mapping[str, object]],
) -> tuple[list[dict[str, object]], str | None]:
    try:
        table = _process_table()
    except EvaluationError as error:
        return [dict(item) for item in snapshot], str(error)
    live = [
        dict(item)
        for item in snapshot
        if isinstance(item.get("pid"), int)
        and table.get(cast(int, item["pid"]), {}).get("process_creation_token")
        == item.get("process_creation_token")
    ]
    return live, None


def _wait_for_process_tree_exit(
    snapshot: Sequence[Mapping[str, object]], *, timeout_seconds: float = 5.0
) -> tuple[list[dict[str, object]], str | None]:
    if not snapshot:
        return [], "Stage 09 process-tree snapshot is empty"
    deadline = time.perf_counter() + timeout_seconds
    while True:
        live, error = _exact_live_processes(snapshot)
        if error is not None or not live or time.perf_counter() >= deadline:
            return live, error
        time.sleep(0.05)


def _wait_for_process_group_exit(
    process_group_id: int, *, timeout_seconds: float = 5.0
) -> tuple[list[dict[str, object]], str | None]:
    deadline = time.perf_counter() + timeout_seconds
    while True:
        try:
            table = _process_table()
        except EvaluationError as error:
            return [], str(error)
        live = [
            {
                "parent_pid": row["parent_pid"],
                "pid": pid,
                "process_creation_token": row["process_creation_token"],
            }
            for pid, row in table.items()
            if row.get("process_group_id") == process_group_id
        ]
        live.sort(key=lambda item: cast(int, item["pid"]))
        if not live or time.perf_counter() >= deadline:
            return live, None
        time.sleep(0.05)


def _validate_tree_termination_receipt(
    value: Mapping[str, object],
    *,
    expected_root_pid: int,
    expected_root_token: str,
    require_target_match: bool,
) -> None:
    tree_before = value.get("process_tree_before")
    tree_after = value.get("process_tree_live_after")
    if not isinstance(tree_before, list) or not isinstance(tree_after, list):
        raise EvaluationError("Stage 09 process-tree termination evidence is absent")
    validated: dict[int, tuple[int, str]] = {}
    for item in tree_before:
        if not isinstance(item, dict) or set(item) != {
            "parent_pid",
            "pid",
            "process_creation_token",
        }:
            raise EvaluationError("Stage 09 process-tree snapshot is malformed")
        pid = item.get("pid")
        parent_pid = item.get("parent_pid")
        token = item.get("process_creation_token")
        if (
            isinstance(pid, bool)
            or not isinstance(pid, int)
            or pid <= 0
            or isinstance(parent_pid, bool)
            or not isinstance(parent_pid, int)
            or parent_pid < 0
            or not isinstance(token, str)
            or not token
            or pid in validated
        ):
            raise EvaluationError("Stage 09 process-tree snapshot is malformed")
        validated[pid] = (parent_pid, token)
    authority = value.get("containment_authority")
    if authority == "posix-new-session-process-group":
        if validated.get(expected_root_pid, (None, None))[1] != expected_root_token:
            raise EvaluationError("Stage 09 process-tree root identity changed")
        if any(
            pid != expected_root_pid and parent not in validated
            for pid, (parent, _token) in validated.items()
        ):
            raise EvaluationError("Stage 09 process-tree ancestry changed")
    elif authority != "windows-job-object-assigned-before-resume":
        raise EvaluationError("Stage 09 process containment authority changed")
    if (
        tree_after
        or value.get("containment_active_processes_after") != 0
        or (
            authority == "posix-new-session-process-group"
            and value.get("process_tree_enumeration_error") is not None
        )
        or value.get("process_tree_verification_error") is not None
        or value.get("process_tree_verified_empty") is not True
        or value.get("passed") is not True
        or value.get("root_pid") != expected_root_pid
        or value.get("root_process_creation_token") != expected_root_token
        or not isinstance(value.get("command_succeeded"), bool)
        or (require_target_match and value.get("target_token_matched") is not True)
    ):
        raise EvaluationError("Stage 09 process-tree termination did not verify empty")


def _launch_payload(
    *,
    process: subprocess.Popen[bytes],
    command: Sequence[str],
    cwd: Path,
    context: Mapping[str, object],
) -> dict[str, object]:
    pid = process.pid
    creation_token = _process_creation_token(pid)
    if creation_token is None:
        raise EvaluationError("Stage 09 process creation identity is unavailable")
    payload = {
        "schema": LAUNCH_RECEIPT_SCHEMA,
        "cell_id": context.get("cell_id"),
        "cell_spec_hash": context.get("cell_spec_hash"),
        "command": list(command),
        "command_sha256": sha256_bytes(canonical_json_bytes(list(command))),
        "cwd": cwd.resolve().as_posix(),
        "exposure_event_hash": context.get("exposure_event_hash"),
        "launch_token": context.get("launch_token"),
        "authorization_path": context.get("authorization_path"),
        "launched_at_unix_ns": time.time_ns(),
        "parent_pid": os.getpid(),
        "pid": pid,
        "process_creation_token": creation_token,
        "raw_path": context.get("raw_path"),
        "stderr_path": context.get("stderr_path"),
        "stdout_path": context.get("stdout_path"),
        "worker_spec_hash": context.get("worker_spec_hash"),
        "worker_spec_sha256": context.get("worker_spec_sha256"),
    }
    return cast(dict[str, object], seal_object(payload, hash_field="launch_receipt_hash"))


def _authorization_payload(
    *,
    launch: Mapping[str, object],
    command: Sequence[str],
    context: Mapping[str, object],
) -> dict[str, object]:
    payload = {
        "schema": LAUNCH_AUTHORIZATION_SCHEMA,
        "abort_path": context.get("abort_path"),
        "cell_id": context.get("cell_id"),
        "cell_spec_hash": context.get("cell_spec_hash"),
        "command": list(command),
        "command_sha256": sha256_bytes(canonical_json_bytes(list(command))),
        "exposure_event_hash": context.get("exposure_event_hash"),
        "launch_receipt_hash": launch.get("launch_receipt_hash"),
        "launch_token": context.get("launch_token"),
        "pid": launch.get("pid"),
        "process_creation_token": launch.get("process_creation_token"),
        "raw_path": context.get("raw_path"),
        "worker_spec_hash": context.get("worker_spec_hash"),
        "worker_spec_sha256": context.get("worker_spec_sha256"),
    }
    return cast(dict[str, object], seal_object(payload, hash_field="authorization_hash"))


def _supervise(
    command: Sequence[str],
    *,
    cwd: Path,
    streams: Path,
    timeout_seconds: float,
    launch_receipt_path: Path | None = None,
    authorization_path: Path | None = None,
    supervision_receipt_path: Path | None = None,
    launch_context: Mapping[str, object] | None = None,
) -> dict[str, object]:
    started = time.perf_counter_ns()
    stdout = b""
    stderr = b""
    timed_out = False
    launch_error: str | None = None
    termination: dict[str, object] | None = None
    returncode: int | None = None
    launch_receipt_hash: str | None = None
    authorization_hash: str | None = None
    process_creation_token: str | None = None
    process: subprocess.Popen[bytes] | None = None
    windows_job_handle: int | None = None
    try:
        options: dict[str, object] = {
            "cwd": cwd,
            "env": {
                key: value
                for key, value in os.environ.items()
                if key.upper() != "PYTHONPATH" and not key.upper().startswith("GIT_")
            },
            "stdin": subprocess.DEVNULL,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
        }
        if os.name == "nt":
            options["creationflags"] = WINDOWS_NEW_GROUP | WINDOWS_CREATE_SUSPENDED
        else:
            options["start_new_session"] = True
        process = subprocess.Popen(list(command), **cast(dict[str, Any], options))
        if os.name == "nt":
            windows_job_handle = _windows_job_for_suspended_process(process)
        if launch_receipt_path is not None:
            if launch_context is None:
                raise EvaluationError("Stage 09 launch context is absent")
            launch = _launch_payload(
                process=process,
                command=command,
                cwd=cwd,
                context=launch_context,
            )
            _atomic_create(launch_receipt_path, canonical_json_bytes(launch))
            launch_receipt_hash = cast(str, launch["launch_receipt_hash"])
            process_creation_token = cast(str, launch["process_creation_token"])
            if authorization_path is None:
                raise EvaluationError("Stage 09 launch authorization path is absent")
            authorization = _authorization_payload(
                launch=launch,
                command=command,
                context=launch_context,
            )
            _atomic_create(authorization_path, canonical_json_bytes(authorization))
            authorization_hash = cast(str, authorization["authorization_hash"])
        try:
            stdout, stderr = process.communicate(timeout=timeout_seconds)
        except subprocess.TimeoutExpired as error:
            timed_out = True
            stdout = bytes(error.stdout or b"")
            stderr = bytes(error.stderr or b"")
            termination = _terminate_tree(
                process,
                expected_root_token=process_creation_token,
                windows_job_handle=windows_job_handle,
            )
            try:
                tail_out, tail_err = process.communicate(timeout=10.0)
                stdout = tail_out if tail_out.startswith(stdout) else stdout + tail_out
                stderr = tail_err if tail_err.startswith(stderr) else stderr + tail_err
            except subprocess.TimeoutExpired:
                if process.poll() is None:
                    process.kill()
                process.wait(timeout=5.0)
        returncode = process.returncode
    except (EvaluationError, OSError) as error:
        launch_error = f"{type(error).__name__}: {error}"
        if process is not None and process.poll() is None:
            termination = _terminate_tree(
                process,
                expected_root_token=process_creation_token,
                windows_job_handle=windows_job_handle,
            )
            try:
                tail_out, tail_err = process.communicate(timeout=10.0)
                stdout += tail_out
                stderr += tail_err
            except (OSError, subprocess.TimeoutExpired):
                pass
            returncode = process.returncode
    cleanup = _cleanup_assigned_containment(
        process,
        windows_job_handle=windows_job_handle,
    )
    if windows_job_handle is not None:
        cleanup["close_attempted"] = True
        try:
            _close_windows_handle(windows_job_handle)
            cleanup["close_succeeded"] = True
        except OSError as error:
            close_error = f"{type(error).__name__}: {error}"
            cleanup["close_error"] = close_error
            cleanup["close_succeeded"] = False
            prior_error = cleanup.get("error")
            cleanup["error"] = (
                close_error if prior_error is None else f"{prior_error}; {close_error}"
            )
            cleanup["passed"] = False
    containment = {
        "active_processes_after": cleanup["active_processes_after"],
        "assigned_before_resume": cleanup["assigned_before_resume"],
        "authority": cleanup["authority"],
        "error": cleanup["error"],
        "limitation": cleanup["limitation"],
        "passed": cleanup["passed"],
    }
    stdout_path = streams / "stdout.bin"
    stderr_path = streams / "stderr.bin"
    _atomic_create(stdout_path, stdout)
    _atomic_create(stderr_path, stderr)
    payload = {
        "schema": SUPERVISION_RECEIPT_SCHEMA,
        "authorization_hash": authorization_hash,
        "command": list(command),
        "cleanup": cleanup,
        "containment": containment,
        "launch_receipt_hash": launch_receipt_hash,
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
    result = cast(dict[str, object], seal_object(payload, hash_field="supervision_receipt_hash"))
    if supervision_receipt_path is not None:
        _atomic_create(supervision_receipt_path, canonical_json_bytes(result))
    return result


def _worker_spec(
    cell: DevelopmentCell,
    *,
    source_root: Path,
    environments: Path,
    recordings: Path,
    cell_root: Path,
    runtime_identity: Mapping[str, object],
    harness_source_expected: Mapping[str, object],
    harness_source_before: Mapping[str, object],
    runtime_environment_expected: Mapping[str, object],
    runtime_environment_before: Mapping[str, object],
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
        "harness_root": ROOT.resolve().as_posix(),
        "harness_source_expected": dict(harness_source_expected),
        "harness_source_before": dict(harness_source_before),
        "public_worker_spec": public_worker_spec,
        "runtime_environment_expected": dict(runtime_environment_expected),
        "runtime_environment_before": dict(runtime_environment_before),
        "source_commit": cell.variant.source_commit,
        "source_root": source_root.resolve().as_posix(),
        "source_tree": cell.variant.source_tree,
    }
    return seal_object(outer, hash_field="worker_spec_hash")


def _raw_result(
    raw_path: Path,
    cell: DevelopmentCell,
    spec: Mapping[str, object],
    *,
    asset_after: Mapping[str, object] | None = None,
) -> dict[str, object]:
    raw = _load_canonical_sealed(
        raw_path,
        schema=PUBLIC_RUN_SCHEMA,
        hash_field="receipt_hash",
        label="raw public worker receipt",
    )
    public_spec = cast(dict[str, object], spec["public_worker_spec"])
    specification = cast(dict[str, object], public_spec["specification"])
    identity = cast(dict[str, object], public_spec["identity"])
    if not _receipt_valid(raw, specification, identity.get("identity_hash")):
        raise EvaluationError("Stage 09 raw public worker receipt validation failed")
    score = raw.get("score")
    metrics = raw.get("metrics")
    asset = raw.get("asset_identity_after")
    if not isinstance(score, dict) or not isinstance(metrics, dict) or not isinstance(asset, dict):
        raise EvaluationError("Stage 09 raw worker evidence is incomplete")
    if asset.get("aggregate_sha256") != cell.game.asset_sha256:
        raise EvaluationError("Stage 09 asset changed during worker execution")
    if asset_after is not None and asset != asset_after:
        raise EvaluationError("Stage 09 raw worker asset receipt changed")
    actions = metrics.get("environment_actions")
    if isinstance(actions, bool) or not isinstance(actions, int) or not 0 <= actions <= MAX_ACTIONS:
        raise EvaluationError("Stage 09 raw action count is invalid")
    resets = metrics.get("resets")
    if isinstance(resets, bool) or not isinstance(resets, int) or not 0 <= resets <= MAX_RESETS:
        raise EvaluationError("Stage 09 raw reset count is invalid")
    live_trace = _verified_live_trace(cell, spec)
    if raw.get("trace") != live_trace:
        raise EvaluationError("Stage 09 raw trace receipt changed from exact live replay")
    if (
        live_trace.get("environment_action_count") != actions
        or live_trace.get("reset_count") != resets
    ):
        raise EvaluationError("Stage 09 raw action/reset metrics disagree with live trace")
    if score.get("verified") is True and (
        score.get("official_run_actions") != actions or score.get("official_run_resets") != resets
    ):
        raise EvaluationError("Stage 09 verified score action/reset counts disagree with trace")
    if raw.get("status") not in {"success", "failure"}:
        raise EvaluationError("Stage 09 raw worker termination is not a frozen normal result")
    return cast(dict[str, object], raw)


def _verified_live_trace(cell: DevelopmentCell, spec: Mapping[str, object]) -> dict[str, object]:
    public = spec.get("public_worker_spec")
    if not isinstance(public, dict):
        raise EvaluationError("Stage 09 public worker trace specification is absent")
    trace_path_value = public.get("trace_path")
    run_id = public.get("run_id")
    trace_relative = public.get("trace_relative")
    if not all(
        isinstance(value, str) and value for value in (trace_path_value, run_id, trace_relative)
    ):
        raise EvaluationError("Stage 09 public worker trace identity is invalid")
    trace_path = Path(cast(str, trace_path_value))
    if not trace_path.is_dir():
        raise EvaluationError("Stage 09 public worker trace is absent")
    try:
        trace = _trace_receipt(
            trace_path,
            run_id=cast(str, run_id),
            relative_path=cast(str, trace_relative),
        )
    except (OSError, TraceError, ValueError) as error:
        raise EvaluationError("Stage 09 public worker trace replay failed") from error
    counts = trace.get("event_type_counts")
    integers = {
        "consequence_count": trace.get("consequence_count"),
        "environment_action_count": trace.get("environment_action_count"),
        "event_count": trace.get("event_count"),
        "reset_count": trace.get("reset_count"),
        "submitted_action_count": trace.get("submitted_action_count"),
    }
    if (
        not isinstance(counts, dict)
        or trace.get("replay_verified") is not True
        or trace.get("run_id") != run_id
        or trace.get("path") != trace_relative
        or any(
            isinstance(value, bool) or not isinstance(value, int) or value < 0
            for value in integers.values()
        )
        or any(
            isinstance(value, bool) or not isinstance(value, int) or value < 0
            for value in counts.values()
        )
    ):
        raise EvaluationError("Stage 09 live trace receipt is malformed")
    consequences = cast(int, integers["consequence_count"])
    environment_actions = cast(int, integers["environment_action_count"])
    resets = cast(int, integers["reset_count"])
    submitted = cast(int, integers["submitted_action_count"])
    event_count = cast(int, integers["event_count"])
    if (
        environment_actions > MAX_ACTIONS
        or resets > MAX_RESETS
        or environment_actions + resets != consequences
        or submitted not in {consequences, consequences + 1}
        or sum(cast(int, value) for value in counts.values()) != event_count
        or int(counts.get("observation.received", 0)) < 1
        or (cell.variant.agent == "full" and int(counts.get("run.started", 0)) != 1)
    ):
        raise EvaluationError("Stage 09 live trace receipt violates frozen action semantics")
    return trace


def _timeout_trace_evidence(
    cell: DevelopmentCell, spec: Mapping[str, object]
) -> dict[str, object] | None:
    public = spec.get("public_worker_spec")
    if not isinstance(public, dict):
        return None
    try:
        trace = _verified_live_trace(cell, spec)
    except EvaluationError:
        return None
    run_id = public.get("run_id")
    trace_relative = public.get("trace_relative")
    counts = trace.get("event_type_counts")
    submitted = trace.get("submitted_action_count")
    consequences = trace.get("consequence_count")
    environment_actions = trace.get("environment_action_count")
    resets = trace.get("reset_count")
    event_count = trace.get("event_count")
    if (
        not isinstance(counts, dict)
        or trace.get("replay_verified") is not True
        or trace.get("run_id") != run_id
        or trace.get("path") != trace_relative
        or any(
            isinstance(value, bool) or not isinstance(value, int) or value < 0
            for value in (submitted, consequences, environment_actions, resets, event_count)
        )
    ):
        return None
    assert isinstance(submitted, int)
    assert isinstance(consequences, int)
    assert isinstance(environment_actions, int)
    assert isinstance(resets, int)
    assert isinstance(event_count, int)
    if (
        environment_actions + resets != consequences
        or submitted not in {consequences, consequences + 1}
        or sum(
            value
            for value in counts.values()
            if isinstance(value, int) and not isinstance(value, bool)
        )
        != event_count
        or int(counts.get("observation.received", 0)) < 1
    ):
        return None
    controller_started = int(counts.get("run.started", 0)) == 1
    if cell.variant.agent == "full" and not controller_started:
        return None
    payload = {
        "schema": TIMEOUT_TRACE_SCHEMA,
        "cell_id": cell.cell_id,
        "controller_started": controller_started,
        "observation_received": True,
        "run_id": run_id,
        "trace": trace,
    }
    return cast(dict[str, object], seal_object(payload, hash_field="timeout_trace_hash"))


def _parent_evidence(
    cell: DevelopmentCell,
    *,
    paths: Mapping[str, Path],
    spec: Mapping[str, object],
    exposure_event: Mapping[str, object],
    supervision: Mapping[str, object],
    asset_after: Mapping[str, object],
    pre_receipt_active_wall_ns: int,
    harness_source_expected: Mapping[str, object],
    harness_source_before: Mapping[str, object],
    harness_source_after: Mapping[str, object],
    runtime_environment_expected: Mapping[str, object],
    runtime_environment_before: Mapping[str, object],
    runtime_environment_after: Mapping[str, object],
    prior_authority_before: Mapping[str, object],
    prior_authority_after: Mapping[str, object],
    environment_cache_before: Mapping[str, object],
    environment_cache_after: Mapping[str, object],
) -> dict[str, object]:
    payload = {
        "schema": PARENT_EVIDENCE_SCHEMA,
        "cell_id": cell.cell_id,
        "cell_spec_hash": cell.spec_hash,
        "exposure_event_hash": exposure_event.get("event_hash"),
        "worker_spec_hash": spec.get("worker_spec_hash"),
        "worker_spec_sha256": sha256_file(paths["spec"]),
        "launch_receipt_hash": supervision.get("launch_receipt_hash"),
        "launch_receipt_sha256": (
            sha256_file(paths["launch"]) if paths["launch"].is_file() else None
        ),
        "authorization_hash": supervision.get("authorization_hash"),
        "authorization_sha256": (
            sha256_file(paths["authorization"]) if paths["authorization"].is_file() else None
        ),
        "supervision_receipt_hash": supervision.get("supervision_receipt_hash"),
        "supervision_receipt_sha256": sha256_file(paths["supervision"]),
        "raw_receipt_sha256": sha256_file(paths["raw"]) if paths["raw"].is_file() else None,
        "asset_after": dict(asset_after),
        "execution_observations": {
            "environment_cache_after": dict(environment_cache_after),
            "environment_cache_before": dict(environment_cache_before),
            "harness_source_after": dict(harness_source_after),
            "harness_source_before": dict(harness_source_before),
            "harness_source_expected": dict(harness_source_expected),
            "prior_authority_after": dict(prior_authority_after),
            "prior_authority_before": dict(prior_authority_before),
            "runtime_environment_after": dict(runtime_environment_after),
            "runtime_environment_before": dict(runtime_environment_before),
            "runtime_environment_expected": dict(runtime_environment_expected),
        },
        "pre_receipt_active_wall_ns": pre_receipt_active_wall_ns,
        "supervision_wall_ns": supervision.get("wall_ns"),
        "worker_wall_seconds": WORKER_WALL_SECONDS,
    }
    return cast(dict[str, object], seal_object(payload, hash_field="parent_evidence_hash"))


def _worker_boundary(
    supervision: Mapping[str, object],
    spec: Mapping[str, object],
    *,
    raw_receipt_hash: str,
    harness_after: Mapping[str, object],
    runtime_after: Mapping[str, object],
) -> dict[str, object]:
    stdout_path = supervision.get("stdout_path")
    if not isinstance(stdout_path, str) or not Path(stdout_path).is_file():
        raise EvaluationError("Stage 09 worker boundary stdout is absent")
    try:
        value = json.loads(Path(stdout_path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise EvaluationError("Stage 09 worker boundary stdout is invalid") from error
    if not isinstance(value, dict):
        raise EvaluationError("Stage 09 worker boundary receipt must be an object")
    expected_harness = cast(dict[str, object], spec["harness_source_expected"])
    harness_before = cast(dict[str, object], spec["harness_source_before"])
    expected_runtime = cast(dict[str, object], spec["runtime_environment_expected"])
    runtime_before = cast(dict[str, object], spec["runtime_environment_before"])
    expected = {
        "cell_id": spec["cell_id"],
        "harness_binding_hash": expected_harness["binding_hash"],
        "harness_source_before_hash": harness_before["observation_hash"],
        "harness_source_after_hash": harness_after["observation_hash"],
        "raw_receipt_hash": raw_receipt_hash,
        "runtime_binding_hash": expected_runtime["runtime_binding_hash"],
        "runtime_environment_before_hash": runtime_before["observation_hash"],
        "runtime_environment_after_hash": runtime_after["observation_hash"],
    }
    if any(value.get(key) != item for key, item in expected.items()):
        raise EvaluationError("Stage 09 worker source/runtime boundary changed")
    if value.get("status") not in {"success", "failure"}:
        raise EvaluationError("Stage 09 worker boundary status is invalid")
    return cast(dict[str, object], value)


def _cell_receipt(
    cell: DevelopmentCell,
    *,
    spec: Mapping[str, object],
    exposure_event: Mapping[str, object],
    supervision: Mapping[str, object],
    raw_path: Path,
    asset_after: Mapping[str, object],
    pre_receipt_active_wall_ns: int,
    spec_path: Path | None = None,
    launch_receipt_path: Path | None = None,
    authorization_path: Path | None = None,
    supervision_receipt_path: Path | None = None,
    parent_evidence_path: Path | None = None,
    harness_source_expected: Mapping[str, object],
    harness_source_before: Mapping[str, object],
    harness_source_after: Mapping[str, object],
    runtime_environment_expected: Mapping[str, object],
    runtime_environment_before: Mapping[str, object],
    runtime_environment_after: Mapping[str, object],
    prior_authority_before: Mapping[str, object],
    prior_authority_after: Mapping[str, object],
    environment_cache_before: Mapping[str, object],
    environment_cache_after: Mapping[str, object],
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
    timeout_trace: dict[str, object] | None = None
    raw: dict[str, object] | None = None
    worker_boundary: dict[str, object] | None = None
    harness_stable = harness_source_stable(
        harness_source_before,
        harness_source_after,
        expected=harness_source_expected,
    )
    runtime_stable = runtime_environment_stable(
        runtime_environment_before,
        runtime_environment_after,
        expected=runtime_environment_expected,
    )
    authority_stable = _prior_authority_stable(prior_authority_before, prior_authority_after)
    cache_stable = _environment_cache_stable(environment_cache_before, environment_cache_after)
    containment = supervision.get("containment")
    containment_stable = not isinstance(containment, dict) or containment.get("passed") is True
    raw_available = raw_path.is_file()
    successful_wrapper = (
        supervision.get("launch_error") is None
        and supervision.get("returncode") == 0
        and supervision.get("timed_out") is False
    )
    raw_validation_failure: str | None = None
    if raw_available:
        try:
            raw = _raw_result(raw_path, cell, spec, asset_after=asset_after)
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
        except (EvaluationError, OSError, ValueError) as error:
            raw_validation_failure = f"{type(error).__name__}: {error}"
            failure = raw_validation_failure
    if successful_wrapper:
        if raw is None:
            failure = raw_validation_failure or "worker produced no valid raw receipt"
        else:
            try:
                worker_boundary = _worker_boundary(
                    supervision,
                    spec,
                    raw_receipt_hash=cast(str, raw_hash),
                    harness_after=harness_source_after,
                    runtime_after=runtime_environment_after,
                )
                if raw.get("status") == "success" and score_verified:
                    status = CellStatus.SUCCESS
                elif raw.get("status") == "success":
                    failure = "raw worker success lacks a verified official score"
                else:
                    untyped_failure = raw.get("failure")
                    failure = (
                        f"raw worker failure: {untyped_failure}"
                        if isinstance(untyped_failure, dict)
                        else "raw worker did not terminate successfully"
                    )
            except (EvaluationError, OSError, ValueError) as error:
                failure = f"{type(error).__name__}: {error}"
    elif supervision.get("timed_out") is True:
        termination = supervision.get("termination")
        wall_ns = supervision.get("wall_ns")
        timeout_trace = _timeout_trace_evidence(cell, spec)
        timeout_elapsed = (
            isinstance(wall_ns, int)
            and not isinstance(wall_ns, bool)
            and wall_ns >= int(WORKER_WALL_SECONDS * 1_000_000_000)
        )
        if (
            isinstance(termination, dict)
            and termination.get("passed") is True
            and timeout_elapsed
            and timeout_trace is not None
            and (not raw_available or raw is not None)
        ):
            status = CellStatus.CONTROLLER_WALL_TIMEOUT
        else:
            failure = raw_validation_failure or (
                "controller timeout lacks verified start, trace, wall, or tree termination"
            )
    elif supervision.get("launch_error") is not None:
        failure = raw_validation_failure or "worker process launch failed"
    elif supervision.get("returncode") != 0:
        failure = raw_validation_failure or "worker exited nonzero"
    elif not raw_available:
        failure = "worker produced no raw receipt"
    if asset_after.get("passed") is not True:
        status = CellStatus.INFRASTRUCTURE_FAILURE
        failure = "development asset identity changed after cell execution"
    if not harness_stable:
        status = CellStatus.INFRASTRUCTURE_FAILURE
        failure = "Stage 09 harness source changed during cell execution"
    if not runtime_stable:
        status = CellStatus.INFRASTRUCTURE_FAILURE
        failure = "Stage 09 runtime environment changed during cell execution"
    if not authority_stable:
        status = CellStatus.INFRASTRUCTURE_FAILURE
        failure = "Stage 09 prior authority changed during cell execution"
    if not cache_stable:
        status = CellStatus.INFRASTRUCTURE_FAILURE
        failure = "Stage 09 opaque public cache changed during cell execution"
    if not containment_stable:
        status = CellStatus.INFRASTRUCTURE_FAILURE
        failure = "Stage 09 process containment did not verify empty"
    recovered_failure_result: dict[str, object] | None = None
    if status is not CellStatus.SUCCESS:
        if raw is not None:
            recovered_failure_result = {
                "claim_status": "non-claim",
                "completed": completed if score_verified else False,
                "environment_actions": actions,
                "levels_completed": levels if score_verified else 0,
                "score_verified": score_verified,
                "source": "raw-nondecisive-result",
            }
        elif timeout_trace is not None:
            timeout_receipt = cast(dict[str, object], timeout_trace["trace"])
            recovered_failure_result = {
                "claim_status": "non-claim",
                "completed": False,
                "environment_actions": timeout_receipt["environment_action_count"],
                "levels_completed": 0,
                "score_verified": False,
                "source": "verified-timeout-trace",
            }
        score_verified = False
        completed = False
        levels = 0
        actions = 0
    payload = {
        "schema": CELL_RECEIPT_SCHEMA,
        "status": status.value,
        "normal_termination_definition": NORMAL_TERMINATION_DEFINITION,
        "mechanism_provenance": None,
        "evidence_label": "local-public",
        "cell_id": cell.cell_id,
        "cell_spec_hash": cell.spec_hash,
        "game_id": cell.game.game_id,
        "seed": cell.seed,
        "variant": cell.variant.value,
        "asset_sha256": cell.game.asset_sha256,
        "source_commit": cell.variant.source_commit,
        "harness_source": {
            "expected": dict(harness_source_expected),
            "before": dict(harness_source_before),
            "after": dict(harness_source_after),
            "stable": harness_stable,
        },
        "runtime_environment": {
            "expected": dict(runtime_environment_expected),
            "before": dict(runtime_environment_before),
            "after": dict(runtime_environment_after),
            "stable": runtime_stable,
        },
        "prior_authority": {
            "before": dict(prior_authority_before),
            "after": dict(prior_authority_after),
            "stable": authority_stable,
        },
        "environment_cache": {
            "before": dict(environment_cache_before),
            "after": dict(environment_cache_after),
            "stable": cache_stable,
        },
        "exposure_event_hash": exposure_event.get("event_hash"),
        "worker_spec_hash": spec.get("worker_spec_hash"),
        "worker_spec_sha256": sha256_file(spec_path) if spec_path is not None else None,
        "launch_receipt_hash": supervision.get("launch_receipt_hash"),
        "launch_receipt_sha256": (
            sha256_file(launch_receipt_path)
            if launch_receipt_path is not None and launch_receipt_path.is_file()
            else None
        ),
        "authorization_hash": supervision.get("authorization_hash"),
        "authorization_sha256": (
            sha256_file(authorization_path)
            if authorization_path is not None and authorization_path.is_file()
            else None
        ),
        "supervision_receipt_hash": supervision.get("supervision_receipt_hash"),
        "supervision_receipt_sha256": (
            sha256_file(supervision_receipt_path)
            if supervision_receipt_path is not None and supervision_receipt_path.is_file()
            else None
        ),
        "parent_evidence_hash": (
            load_json(parent_evidence_path).get("parent_evidence_hash")
            if parent_evidence_path is not None and parent_evidence_path.is_file()
            else None
        ),
        "parent_evidence_sha256": (
            sha256_file(parent_evidence_path)
            if parent_evidence_path is not None and parent_evidence_path.is_file()
            else None
        ),
        "raw_receipt_hash": raw_hash,
        "raw_receipt_sha256": sha256_file(raw_path) if raw_path.is_file() else None,
        "result": {
            "completed": completed,
            "environment_actions": actions,
            "levels_completed": levels,
            "score_verified": score_verified,
        },
        "recovered_failure_result": recovered_failure_result,
        "resources": {
            "child_cpu_seconds": child_cpu,
            "child_peak_rss_bytes": child_rss,
            "pre_receipt_active_wall_ns": pre_receipt_active_wall_ns,
            "supervision_wall_ns": supervision.get("wall_ns"),
            "worker_wall_seconds": WORKER_WALL_SECONDS,
        },
        "supervisor": dict(supervision),
        "timeout_trace": timeout_trace,
        "worker_boundary": worker_boundary,
        "asset_after": dict(asset_after),
        "failure": failure,
    }
    return cast(dict[str, object], seal_object(payload, hash_field="cell_receipt_hash"))


def _cell_finalization(
    cell: DevelopmentCell,
    *,
    paths: Mapping[str, Path],
    receipt: Mapping[str, object],
    parent_evidence: Mapping[str, object],
    cell_segment: Mapping[str, object],
    measured_active_wall_ns: int,
) -> dict[str, object]:
    if (
        isinstance(measured_active_wall_ns, bool)
        or not isinstance(measured_active_wall_ns, int)
        or measured_active_wall_ns < 0
    ):
        raise EvaluationError("Stage 09 measured cell wall is invalid")
    payload = {
        "schema": CELL_FINALIZATION_SCHEMA,
        "admission_charge_ns": CELL_ADMISSION_CHARGE_NS,
        "budget_accounting": "fixed-full-cell-admission-charge",
        "cell_id": cell.cell_id,
        "cell_spec_hash": cell.spec_hash,
        "cell_receipt_hash": receipt.get("cell_receipt_hash"),
        "cell_receipt_sha256": sha256_file(paths["receipt"]),
        "cell_segment_hash": cell_segment.get("cell_segment_hash"),
        "cell_segment_sha256": sha256_file(paths["cell_segment"]),
        "measurement_scope": "cell-preparation-start-through-durable-cell-receipt",
        "measured_active_wall_ns": measured_active_wall_ns,
        "normal_termination_definition": NORMAL_TERMINATION_DEFINITION,
        "parent_evidence_hash": parent_evidence.get("parent_evidence_hash"),
        "parent_evidence_sha256": sha256_file(paths["parent_evidence"]),
        "within_admission_charge": measured_active_wall_ns <= CELL_ADMISSION_CHARGE_NS,
    }
    return cast(dict[str, object], seal_object(payload, hash_field="finalization_hash"))


def _recovered_cell_finalization(
    cell: DevelopmentCell,
    *,
    paths: Mapping[str, Path],
    receipt: Mapping[str, object],
    parent_evidence: Mapping[str, object],
    cell_segment: Mapping[str, object],
) -> dict[str, object]:
    resources = receipt.get("resources")
    pre_receipt_wall = (
        resources.get("pre_receipt_active_wall_ns") if isinstance(resources, dict) else None
    )
    if (
        isinstance(pre_receipt_wall, bool)
        or not isinstance(pre_receipt_wall, int)
        or pre_receipt_wall < 0
    ):
        raise EvaluationError("Stage 09 recovered finalization lacks its parent wall")
    payload = {
        "schema": RECOVERED_CELL_FINALIZATION_SCHEMA,
        "admission_charge_ns": CELL_ADMISSION_CHARGE_NS,
        "budget_accounting": "fixed-full-cell-admission-charge",
        "cell_id": cell.cell_id,
        "cell_spec_hash": cell.spec_hash,
        "cell_receipt_hash": receipt.get("cell_receipt_hash"),
        "cell_receipt_sha256": sha256_file(paths["receipt"]),
        "cell_segment_hash": cell_segment.get("cell_segment_hash"),
        "cell_segment_sha256": sha256_file(paths["cell_segment"]),
        "conservative_accounted_active_wall_ns": max(pre_receipt_wall, CELL_ADMISSION_CHARGE_NS),
        "measurement_scope": "durable-receipt-present-finalization-missing-after-interruption",
        "measured_active_wall_ns": None,
        "normal_termination_definition": NORMAL_TERMINATION_DEFINITION,
        "parent_evidence_hash": parent_evidence.get("parent_evidence_hash"),
        "parent_evidence_sha256": sha256_file(paths["parent_evidence"]),
        "recovery_kind": "durable-cell-receipt-without-finalization",
        "timing_measurement_available": False,
        "within_admission_charge": False,
    }
    return cast(dict[str, object], seal_object(payload, hash_field="finalization_hash"))


def _reconstruct_cell_finalization(
    *,
    paths: Mapping[str, Path],
    cell: DevelopmentCell,
    receipt: Mapping[str, object],
    parent_evidence: Mapping[str, object],
    check: Mapping[str, object],
) -> dict[str, object]:
    if not paths["finalization"].is_file():
        raise EvaluationError("Stage 09 cell finalization receipt is absent")
    cell_segment = _load_cell_segment(cell=cell, paths=paths, check=check)
    schema = load_json(paths["finalization"]).get("schema")
    if schema == RECOVERED_CELL_FINALIZATION_SCHEMA:
        persisted = _load_canonical_sealed(
            paths["finalization"],
            schema=RECOVERED_CELL_FINALIZATION_SCHEMA,
            hash_field="finalization_hash",
            label="recovered cell finalization receipt",
        )
        expected = _recovered_cell_finalization(
            cell,
            paths=paths,
            receipt=receipt,
            parent_evidence=parent_evidence,
            cell_segment=cell_segment,
        )
        if persisted != expected:
            raise EvaluationError(
                "Stage 09 recovered cell finalization does not reconstruct exactly"
            )
        return persisted
    persisted = _load_canonical_sealed(
        paths["finalization"],
        schema=CELL_FINALIZATION_SCHEMA,
        hash_field="finalization_hash",
        label="cell finalization receipt",
    )
    measured = persisted.get("measured_active_wall_ns")
    if isinstance(measured, bool) or not isinstance(measured, int) or measured < 0:
        raise EvaluationError("Stage 09 cell finalization wall changed")
    expected = _cell_finalization(
        cell,
        paths=paths,
        receipt=receipt,
        parent_evidence=parent_evidence,
        cell_segment=cell_segment,
        measured_active_wall_ns=measured,
    )
    if persisted != expected:
        raise EvaluationError("Stage 09 cell finalization does not reconstruct exactly")
    return persisted


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


def _load_canonical_sealed(
    path: Path, *, schema: str, hash_field: str, label: str
) -> dict[str, Any]:
    if not path.is_file():
        raise EvaluationError(f"Stage 09 {label} is absent")
    raw_bytes = path.read_bytes()
    value = load_json(path)
    if (
        value.get("schema") != schema
        or not verify_object_hash(value, hash_field=hash_field)
        or canonical_json_bytes(value) != raw_bytes
    ):
        raise EvaluationError(f"Stage 09 {label} bytes/hash/schema changed")
    return value


def _validate_launch_receipt(
    path: Path,
    *,
    cell: DevelopmentCell,
    command: Sequence[str],
    spec: Mapping[str, object],
    spec_path: Path,
    exposure_event: Mapping[str, object],
    paths: Mapping[str, Path],
) -> dict[str, object]:
    launch = _load_canonical_sealed(
        path,
        schema=LAUNCH_RECEIPT_SCHEMA,
        hash_field="launch_receipt_hash",
        label="process launch receipt",
    )
    expected = {
        "cell_id": cell.cell_id,
        "cell_spec_hash": cell.spec_hash,
        "command": list(command),
        "command_sha256": sha256_bytes(canonical_json_bytes(list(command))),
        "cwd": ROOT.resolve().as_posix(),
        "authorization_path": paths["authorization"].resolve().as_posix(),
        "exposure_event_hash": exposure_event.get("event_hash"),
        "raw_path": paths["raw"].resolve().as_posix(),
        "stderr_path": paths["stderr"].resolve().as_posix(),
        "stdout_path": paths["stdout"].resolve().as_posix(),
        "worker_spec_hash": spec.get("worker_spec_hash"),
        "worker_spec_sha256": sha256_file(spec_path),
    }
    if any(launch.get(key) != value for key, value in expected.items()):
        raise EvaluationError("Stage 09 process launch binding changed")
    for field in ("launched_at_unix_ns", "parent_pid", "pid"):
        value = launch.get(field)
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise EvaluationError(f"Stage 09 process launch {field} is invalid")
    token = launch.get("process_creation_token")
    launch_token = launch.get("launch_token")
    if (
        not isinstance(token, str)
        or not token
        or not isinstance(launch_token, str)
        or not launch_token
    ):
        raise EvaluationError("Stage 09 process launch identity is invalid")
    return cast(dict[str, object], launch)


def _validate_authorization_receipt(
    path: Path,
    *,
    cell: DevelopmentCell,
    command: Sequence[str],
    spec: Mapping[str, object],
    spec_path: Path,
    exposure_event: Mapping[str, object],
    paths: Mapping[str, Path],
    launch: Mapping[str, object],
) -> dict[str, object]:
    authorization = _load_canonical_sealed(
        path,
        schema=LAUNCH_AUTHORIZATION_SCHEMA,
        hash_field="authorization_hash",
        label="worker launch authorization",
    )
    expected = {
        "abort_path": paths["abort"].resolve().as_posix(),
        "cell_id": cell.cell_id,
        "cell_spec_hash": cell.spec_hash,
        "command": list(command),
        "command_sha256": sha256_bytes(canonical_json_bytes(list(command))),
        "exposure_event_hash": exposure_event.get("event_hash"),
        "launch_receipt_hash": launch.get("launch_receipt_hash"),
        "launch_token": launch.get("launch_token"),
        "pid": launch.get("pid"),
        "process_creation_token": launch.get("process_creation_token"),
        "raw_path": paths["raw"].resolve().as_posix(),
        "worker_spec_hash": spec.get("worker_spec_hash"),
        "worker_spec_sha256": sha256_file(spec_path),
    }
    if any(authorization.get(key) != value for key, value in expected.items()):
        raise EvaluationError("Stage 09 worker launch authorization changed")
    return cast(dict[str, object], authorization)


def _validate_cleanup_receipt(cleanup: object, containment: object) -> None:
    if not isinstance(cleanup, dict) or set(cleanup) != {
        "active_processes_after",
        "active_processes_before",
        "assigned_before_resume",
        "authority",
        "close_attempted",
        "close_error",
        "close_succeeded",
        "error",
        "limitation",
        "members_after",
        "members_before",
        "observation_error_before",
        "passed",
        "termination_attempted",
        "termination_error",
        "termination_succeeded",
        "verification_error",
    }:
        raise EvaluationError("Stage 09 process cleanup receipt is malformed")
    if not isinstance(containment, dict) or set(containment) != {
        "active_processes_after",
        "assigned_before_resume",
        "authority",
        "error",
        "limitation",
        "passed",
    }:
        raise EvaluationError("Stage 09 process containment receipt is malformed")
    active_before = cleanup.get("active_processes_before")
    active_after = cleanup.get("active_processes_after")
    attempted = cleanup.get("termination_attempted")
    succeeded = cleanup.get("termination_succeeded")
    if (
        isinstance(active_before, bool)
        or not isinstance(active_before, int)
        or active_before < 0
        or active_after != 0
        or cleanup.get("assigned_before_resume") is not True
        or cleanup.get("close_error") is not None
        or cleanup.get("error") is not None
        or cleanup.get("observation_error_before") is not None
        or cleanup.get("termination_error") is not None
        or cleanup.get("verification_error") is not None
        or cleanup.get("passed") is not True
        or not isinstance(attempted, bool)
        or attempted != (active_before > 0)
        or succeeded != (True if attempted else None)
    ):
        raise EvaluationError("Stage 09 process cleanup did not verify empty")
    authority = cleanup.get("authority")
    members_before = cleanup.get("members_before")
    members_after = cleanup.get("members_after")
    if authority == "windows-job-object-assigned-before-resume":
        if (
            cleanup.get("close_attempted") is not True
            or cleanup.get("close_succeeded") is not True
            or cleanup.get("limitation") is not None
            or members_before is not None
            or members_after is not None
        ):
            raise EvaluationError("Stage 09 Windows Job cleanup receipt changed")
    elif authority == "posix-new-session-process-group":
        if (
            cleanup.get("close_attempted") is not False
            or cleanup.get("close_succeeded") is not None
            or cleanup.get("limitation") != "setsid-or-double-fork escape is not OS-contained"
            or not isinstance(members_before, list)
            or not isinstance(members_after, list)
            or members_after
            or len(members_before) != active_before
        ):
            raise EvaluationError("Stage 09 POSIX group cleanup receipt changed")
        member_pids: set[int] = set()
        for member in members_before:
            if not isinstance(member, dict) or set(member) != {
                "parent_pid",
                "pid",
                "process_creation_token",
            }:
                raise EvaluationError("Stage 09 POSIX group member receipt is malformed")
            pid = member.get("pid")
            parent_pid = member.get("parent_pid")
            token = member.get("process_creation_token")
            if (
                isinstance(pid, bool)
                or not isinstance(pid, int)
                or pid <= 0
                or pid in member_pids
                or isinstance(parent_pid, bool)
                or not isinstance(parent_pid, int)
                or parent_pid < 0
                or not isinstance(token, str)
                or not token
            ):
                raise EvaluationError("Stage 09 POSIX group member receipt is malformed")
            member_pids.add(pid)
    else:
        raise EvaluationError("Stage 09 process cleanup authority changed")
    expected_containment = {
        "active_processes_after": cleanup["active_processes_after"],
        "assigned_before_resume": cleanup["assigned_before_resume"],
        "authority": cleanup["authority"],
        "error": cleanup["error"],
        "limitation": cleanup["limitation"],
        "passed": cleanup["passed"],
    }
    if containment != expected_containment:
        raise EvaluationError("Stage 09 process containment projection changed")


def _validate_supervision_receipt(
    path: Path,
    *,
    command: Sequence[str],
    paths: Mapping[str, Path],
    launch: Mapping[str, object] | None,
    authorization: Mapping[str, object] | None,
) -> dict[str, object]:
    supervision = _load_canonical_sealed(
        path,
        schema=SUPERVISION_RECEIPT_SCHEMA,
        hash_field="supervision_receipt_hash",
        label="supervision receipt",
    )
    if (
        supervision.get("command") != list(command)
        or supervision.get("timeout_seconds") != WORKER_WALL_SECONDS
        or supervision.get("stdout_path") != paths["stdout"].resolve().as_posix()
        or supervision.get("stderr_path") != paths["stderr"].resolve().as_posix()
    ):
        raise EvaluationError("Stage 09 supervision invocation changed")
    for name in ("stdout", "stderr"):
        stream_path = paths[name]
        if not stream_path.is_file():
            raise EvaluationError(f"Stage 09 {name} stream is absent")
        content = stream_path.read_bytes()
        if supervision.get(f"{name}_bytes") != len(content) or supervision.get(
            f"{name}_sha256"
        ) != sha256_bytes(content):
            raise EvaluationError(f"Stage 09 {name} stream receipt changed")
    wall_ns = supervision.get("wall_ns")
    if isinstance(wall_ns, bool) or not isinstance(wall_ns, int) or wall_ns < 0:
        raise EvaluationError("Stage 09 supervision wall receipt is invalid")
    timed_out = supervision.get("timed_out")
    launch_error = supervision.get("launch_error")
    returncode = supervision.get("returncode")
    termination = supervision.get("termination")
    containment = supervision.get("containment")
    _validate_cleanup_receipt(supervision.get("cleanup"), containment)
    if not isinstance(timed_out, bool):
        raise EvaluationError("Stage 09 timeout receipt is invalid")
    if launch_error is not None and (not isinstance(launch_error, str) or not launch_error):
        raise EvaluationError("Stage 09 launch error receipt is invalid")
    if returncode is not None and (isinstance(returncode, bool) or not isinstance(returncode, int)):
        raise EvaluationError("Stage 09 process return code is invalid")
    if launch_error is None:
        if (
            launch is None
            or authorization is None
            or supervision.get("launch_receipt_hash") != launch.get("launch_receipt_hash")
            or supervision.get("authorization_hash") != authorization.get("authorization_hash")
        ):
            raise EvaluationError("Stage 09 supervision lacks its exact launch receipt")
        if returncode is None:
            raise EvaluationError("Stage 09 launched process lacks a return code")
    elif launch is None:
        if (
            supervision.get("launch_receipt_hash") is not None
            or supervision.get("authorization_hash") is not None
        ):
            raise EvaluationError("Stage 09 launch-error receipt claims an absent process launch")
    elif supervision.get("launch_receipt_hash") != launch.get(
        "launch_receipt_hash"
    ) or supervision.get("authorization_hash") != (
        authorization.get("authorization_hash") if authorization is not None else None
    ):
        raise EvaluationError("Stage 09 launch-error process evidence changed")
    if timed_out:
        if launch_error is not None or not isinstance(termination, dict):
            raise EvaluationError("Stage 09 timeout supervision semantics changed")
        launch_pid = launch.get("pid") if isinstance(launch, dict) else None
        launch_token = launch.get("process_creation_token") if isinstance(launch, dict) else None
        if (
            isinstance(launch_pid, bool)
            or not isinstance(launch_pid, int)
            or not isinstance(launch_token, str)
        ):
            raise EvaluationError("Stage 09 timeout launch identity is absent")
        _validate_tree_termination_receipt(
            termination,
            expected_root_pid=launch_pid,
            expected_root_token=launch_token,
            require_target_match=False,
        )
    elif launch_error is None and termination is not None:
        raise EvaluationError("Stage 09 non-timeout process has a termination receipt")
    return cast(dict[str, object], supervision)


def _reconstruct_cell_receipt(
    *,
    work_root: Path,
    recordings: Path,
    environments: Path,
    build_000_root: Path,
    build_001_root: Path,
    runtime_identity: Mapping[str, object],
    check: Mapping[str, object],
    cell: DevelopmentCell,
    exposure_event: Mapping[str, object],
) -> dict[str, object]:
    paths = _cell_paths(work_root, cell)
    persisted = _load_canonical_sealed(
        paths["receipt"],
        schema=CELL_RECEIPT_SCHEMA,
        hash_field="cell_receipt_hash",
        label="parent cell receipt",
    )
    (
        harness_expected,
        harness_observation,
        runtime_expected,
        runtime_observation,
        authority_observation,
        cache_observation,
    ) = _preflight_boundary_snapshot(check)
    harness_section = persisted.get("harness_source")
    runtime_section = persisted.get("runtime_environment")
    authority_section = persisted.get("prior_authority")
    cache_section = persisted.get("environment_cache")
    if not all(
        isinstance(section, dict)
        for section in (harness_section, runtime_section, authority_section, cache_section)
    ):
        raise EvaluationError("Stage 09 persisted execution observations are absent")
    persisted_harness = cast(dict[str, object], harness_section)
    persisted_runtime = cast(dict[str, object], runtime_section)
    persisted_authority = cast(dict[str, object], authority_section)
    persisted_cache = cast(dict[str, object], cache_section)
    if (
        persisted_harness.get("expected") != harness_expected
        or persisted_harness.get("before") != harness_observation
        or persisted_runtime.get("expected") != runtime_expected
        or persisted_runtime.get("before") != runtime_observation
        or persisted_authority.get("before") != authority_observation
        or persisted_cache.get("before") != cache_observation
    ):
        raise EvaluationError("Stage 09 persisted before-boundary observations changed")
    harness_after = persisted_harness.get("after")
    runtime_after = persisted_runtime.get("after")
    authority_after = persisted_authority.get("after")
    cache_after = persisted_cache.get("after")
    if not all(
        isinstance(observation, dict)
        for observation in (harness_after, runtime_after, authority_after, cache_after)
    ):
        raise EvaluationError("Stage 09 persisted after-boundary observations are absent")
    validate_harness_source_observation(
        cast(dict[str, object], harness_after), expected=harness_expected
    )
    validate_runtime_environment_observation(
        cast(dict[str, object], runtime_after), expected=runtime_expected
    )
    validate_prior_authority_observation(cast(dict[str, object], authority_after))
    validate_environment_cache_observation(cast(dict[str, object], cache_after))
    source_root = build_001_root if cell.variant is Variant.BUILD_001_FULL else build_000_root
    expected_spec = _worker_spec(
        cell,
        source_root=source_root,
        environments=environments,
        recordings=recordings,
        cell_root=paths["cell_root"],
        runtime_identity=runtime_identity,
        harness_source_expected=harness_expected,
        harness_source_before=harness_observation,
        runtime_environment_expected=runtime_expected,
        runtime_environment_before=runtime_observation,
    )
    expected_spec_bytes = canonical_json_bytes(expected_spec)
    if not paths["spec"].is_file() or paths["spec"].read_bytes() != expected_spec_bytes:
        raise EvaluationError("Stage 09 persisted worker specification changed")
    spec = load_json(paths["spec"])
    if spec != expected_spec:
        raise EvaluationError("Stage 09 worker specification does not reconstruct exactly")
    supervision_preview = _load_canonical_sealed(
        paths["supervision"],
        schema=SUPERVISION_RECEIPT_SCHEMA,
        hash_field="supervision_receipt_hash",
        label="supervision receipt",
    )
    launch_token = _recorded_launch_token(supervision_preview.get("command"))
    command = _worker_command(
        paths["spec"],
        paths["raw"],
        launch_path=paths["launch"],
        authorization_path=paths["authorization"],
        abort_path=paths["abort"],
        launch_token=launch_token,
    )
    launch: dict[str, object] | None = None
    authorization: dict[str, object] | None = None
    if paths["launch"].is_file():
        launch = _validate_launch_receipt(
            paths["launch"],
            cell=cell,
            command=command,
            spec=spec,
            spec_path=paths["spec"],
            exposure_event=exposure_event,
            paths=paths,
        )
        if paths["authorization"].is_file():
            authorization = _validate_authorization_receipt(
                paths["authorization"],
                cell=cell,
                command=command,
                spec=spec,
                spec_path=paths["spec"],
                exposure_event=exposure_event,
                paths=paths,
                launch=launch,
            )
    supervision = _validate_supervision_receipt(
        paths["supervision"],
        command=command,
        paths=paths,
        launch=launch,
        authorization=authorization,
    )
    asset_after = _asset_identity(environments, cell)
    parent_evidence = _load_canonical_sealed(
        paths["parent_evidence"],
        schema=PARENT_EVIDENCE_SCHEMA,
        hash_field="parent_evidence_hash",
        label="parent resource evidence",
    )
    parent_wall = parent_evidence.get("pre_receipt_active_wall_ns")
    supervision_wall = supervision.get("wall_ns")
    if (
        isinstance(parent_wall, bool)
        or not isinstance(parent_wall, int)
        or parent_wall < 0
        or not isinstance(supervision_wall, int)
        or parent_wall < supervision_wall
    ):
        raise EvaluationError("Stage 09 pre-receipt/supervision wall semantics changed")
    expected_parent_evidence = _parent_evidence(
        cell,
        paths=paths,
        spec=spec,
        exposure_event=exposure_event,
        supervision=supervision,
        asset_after=asset_after,
        pre_receipt_active_wall_ns=parent_wall,
        harness_source_expected=harness_expected,
        harness_source_before=harness_observation,
        harness_source_after=cast(dict[str, object], harness_after),
        runtime_environment_expected=runtime_expected,
        runtime_environment_before=runtime_observation,
        runtime_environment_after=cast(dict[str, object], runtime_after),
        prior_authority_before=authority_observation,
        prior_authority_after=cast(dict[str, object], authority_after),
        environment_cache_before=cache_observation,
        environment_cache_after=cast(dict[str, object], cache_after),
    )
    if parent_evidence != expected_parent_evidence:
        raise EvaluationError("Stage 09 parent resource evidence does not reconstruct exactly")
    reconstructed = _cell_receipt(
        cell,
        spec=spec,
        exposure_event=exposure_event,
        supervision=supervision,
        raw_path=paths["raw"],
        asset_after=asset_after,
        pre_receipt_active_wall_ns=parent_wall,
        spec_path=paths["spec"],
        launch_receipt_path=paths["launch"],
        authorization_path=paths["authorization"],
        supervision_receipt_path=paths["supervision"],
        parent_evidence_path=paths["parent_evidence"],
        harness_source_expected=harness_expected,
        harness_source_before=harness_observation,
        harness_source_after=cast(dict[str, object], harness_after),
        runtime_environment_expected=runtime_expected,
        runtime_environment_before=runtime_observation,
        runtime_environment_after=cast(dict[str, object], runtime_after),
        prior_authority_before=authority_observation,
        prior_authority_after=cast(dict[str, object], authority_after),
        environment_cache_before=cache_observation,
        environment_cache_after=cast(dict[str, object], cache_after),
    )
    if reconstructed != persisted:
        raise EvaluationError("Stage 09 parent cell receipt does not reconstruct exactly")
    Outcome.from_receipt(reconstructed, cell)
    return reconstructed


def _terminate_orphan_exact(pid: int, expected_token: str) -> dict[str, object]:
    live_before = _process_creation_token(pid)
    if live_before != expected_token:
        return {
            "attempted": False,
            "command_succeeded": False,
            "error": None,
            "live_process_token_after": live_before,
            "live_process_token_before": live_before,
            "method": None,
            "passed": live_before != expected_token,
            "process_tree_before": [],
            "process_tree_enumeration_error": None,
            "process_tree_live_after": [],
            "process_tree_verification_error": None,
            "process_tree_verified_empty": live_before != expected_token,
            "root_pid": pid,
            "root_process_creation_token": expected_token,
            "returncode": None,
            "target_token_matched": False,
        }
    method = "windows-taskkill-tree" if os.name == "nt" else "posix-killpg"
    tree_before, enumeration_error = _process_tree_snapshot(
        pid,
        expected_root_token=expected_token,
    )
    error: str | None = None
    returncode: int | None = None
    try:
        if enumeration_error is not None:
            method = "none-after-tree-enumeration-failure"
        elif os.name == "nt":
            result = subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                check=False,
                capture_output=True,
                timeout=10.0,
            )
            returncode = result.returncode
        else:
            kill_group = getattr(os, "killpg", None)
            if not callable(kill_group):
                raise OSError("process-group termination is unavailable")
            kill_group(pid, int(getattr(signal, "SIGKILL", signal.SIGTERM)))
    except (OSError, subprocess.TimeoutExpired) as caught:
        error = f"{type(caught).__name__}: {caught}"
    if os.name == "nt":
        tree_live_after, verification_error = _wait_for_process_tree_exit(tree_before)
        active_after = len(tree_live_after)
        tree_verified_empty = False
        containment_authority = "uncontained-windows-orphan-tree"
        containment_limit = "pre-kill snapshot cannot exclude a spawn-or-reparent race"
    else:
        tree_live_after, verification_error = _wait_for_process_group_exit(pid)
        active_after = len(tree_live_after)
        tree_verified_empty = verification_error is None and not tree_live_after
        containment_authority = "posix-new-session-process-group"
        containment_limit = "setsid-or-double-fork escape is not OS-contained"
    live_after = _process_creation_token(pid)
    return {
        "attempted": True,
        "command_succeeded": (
            (method == "windows-taskkill-tree" and returncode == 0)
            or (method == "posix-killpg" and returncode is None and error is None)
        ),
        "containment_active_processes_after": active_after,
        "containment_authority": containment_authority,
        "containment_limit": containment_limit,
        "error": error,
        "live_process_token_after": live_after,
        "live_process_token_before": live_before,
        "method": method,
        "passed": tree_verified_empty,
        "process_tree_before": tree_before,
        "process_tree_enumeration_error": enumeration_error,
        "process_tree_live_after": tree_live_after,
        "process_tree_verification_error": verification_error,
        "process_tree_verified_empty": tree_verified_empty,
        "root_pid": pid,
        "root_process_creation_token": expected_token,
        "returncode": returncode,
        "target_token_matched": True,
    }


def _validate_orphan_semantics(value: Mapping[str, object]) -> dict[str, object]:
    receipt = dict(value)
    required = {
        "abort_receipt_hash",
        "abort_receipt_sha256",
        "authorization_hash",
        "authorization_sha256",
        "cell_id",
        "cell_spec_hash",
        "cleanup_claimed",
        "exposure_event_hash",
        "launch_receipt_hash",
        "launch_receipt_sha256",
        "launch_token",
        "live_process_token_after",
        "live_process_token_before",
        "orphan_receipt_hash",
        "passed",
        "pid",
        "process_creation_token",
        "process_enumeration",
        "schema",
        "spawn_intent_hash",
        "spawn_intent_sha256",
        "state",
        "termination",
    }
    if set(receipt) != required or receipt.get("passed") is not True:
        raise EvaluationError("Stage 09 orphan termination fields changed")
    state = receipt.get("state")
    before = receipt.get("live_process_token_before")
    after = receipt.get("live_process_token_after")
    stored = receipt.get("process_creation_token")
    termination = receipt.get("termination")
    launch_hash = receipt.get("launch_receipt_hash")
    intent_hash = receipt.get("spawn_intent_hash")
    if not isinstance(intent_hash, str) or not isinstance(receipt.get("spawn_intent_sha256"), str):
        raise EvaluationError("Stage 09 orphan spawn intent is absent")
    if state == "pre-environment-handshake-aborted":
        if any(
            item is not None
            for item in (
                launch_hash,
                receipt.get("authorization_hash"),
                termination,
            )
        ) or not all(
            isinstance(receipt.get(field), str)
            for field in ("abort_receipt_hash", "abort_receipt_sha256")
        ):
            raise EvaluationError("Stage 09 pre-environment orphan evidence changed")
        enumeration = receipt.get("process_enumeration")
        if (
            receipt.get("cleanup_claimed") is not False
            or receipt.get("pid") is not None
            or stored is not None
            or before is not None
            or after is not None
            or not isinstance(enumeration, dict)
            or enumeration.get("error") is not None
            or enumeration.get("matching_processes") != []
            or enumeration.get("verified_empty") is not True
        ):
            raise EvaluationError("Stage 09 pre-environment process proof changed")
    elif state == "unreceipted-launch-not-running":
        enumeration = receipt.get("process_enumeration")
        if (
            launch_hash is not None
            or receipt.get("authorization_hash") is not None
            or receipt.get("abort_receipt_hash") is not None
            or receipt.get("cleanup_claimed") is not False
            or receipt.get("pid") is not None
            or stored is not None
            or before is not None
            or after is not None
            or termination is not None
            or not isinstance(enumeration, dict)
            or enumeration.get("error") is not None
            or enumeration.get("matching_processes") != []
            or enumeration.get("verified_empty") is not True
        ):
            raise EvaluationError("Stage 09 unreceipted non-running proof changed")
    elif state == "not-running":
        if (
            not isinstance(launch_hash, str)
            or before is not None
            or after is not None
            or receipt.get("cleanup_claimed") is not False
            or receipt.get("process_enumeration") is not None
        ):
            raise EvaluationError("Stage 09 non-running orphan evidence changed")
        if termination is not None:
            raise EvaluationError("Stage 09 non-running orphan claims termination")
    elif state == "pid-reused-original-not-running":
        if (
            not isinstance(launch_hash, str)
            or not isinstance(before, str)
            or before == stored
            or after != before
            or termination is not None
            or receipt.get("cleanup_claimed") is not False
            or receipt.get("process_enumeration") is not None
        ):
            raise EvaluationError("Stage 09 PID-reuse orphan evidence changed")
    elif state == "terminated":
        if (
            not isinstance(termination, dict)
            or termination.get("attempted") is not True
            or termination.get("target_token_matched") is not True
            or termination.get("passed") is not True
            or termination.get("live_process_token_before") != stored
            or termination.get("live_process_token_after") != after
            or before != stored
            or after == stored
            or receipt.get("cleanup_claimed") is not True
            or receipt.get("process_enumeration") is not None
        ):
            raise EvaluationError("Stage 09 terminated orphan evidence changed")
        if not isinstance(receipt.get("pid"), int) or not isinstance(stored, str):
            raise EvaluationError("Stage 09 terminated orphan identity changed")
        _validate_tree_termination_receipt(
            termination,
            expected_root_pid=cast(int, receipt["pid"]),
            expected_root_token=stored,
            require_target_match=True,
        )
    elif state == "unreceipted-launch-terminated":
        enumeration = receipt.get("process_enumeration")
        if (
            launch_hash is not None
            or receipt.get("authorization_hash") is not None
            or receipt.get("cleanup_claimed") is not True
            or not isinstance(enumeration, dict)
            or enumeration.get("error") is not None
            or not isinstance(enumeration.get("matching_processes"), list)
            or len(cast(list[object], enumeration["matching_processes"])) != 1
            or not isinstance(termination, dict)
            or not isinstance(receipt.get("pid"), int)
            or not isinstance(stored, str)
            or before != stored
            or after == stored
        ):
            raise EvaluationError("Stage 09 unreceipted termination evidence changed")
        _validate_tree_termination_receipt(
            termination,
            expected_root_pid=cast(int, receipt["pid"]),
            expected_root_token=stored,
            require_target_match=True,
        )
    else:
        raise EvaluationError("Stage 09 orphan termination state changed")
    return receipt


def _seal_orphan_boundary(
    *,
    work_root: Path,
    recordings: Path,
    environments: Path,
    build_000_root: Path,
    build_001_root: Path,
    runtime_identity: Mapping[str, object],
    check: Mapping[str, object],
    cell: DevelopmentCell,
    exposure_event: Mapping[str, object],
) -> dict[str, object]:
    paths = _cell_paths(work_root, cell)
    (
        harness_expected,
        harness_observation,
        runtime_expected,
        runtime_observation,
        _authority_observation,
        _cache_observation,
    ) = _preflight_boundary_snapshot(check)
    source_root = build_001_root if cell.variant is Variant.BUILD_001_FULL else build_000_root
    expected_spec = _worker_spec(
        cell,
        source_root=source_root,
        environments=environments,
        recordings=recordings,
        cell_root=paths["cell_root"],
        runtime_identity=runtime_identity,
        harness_source_expected=harness_expected,
        harness_source_before=harness_observation,
        runtime_environment_expected=runtime_expected,
        runtime_environment_before=runtime_observation,
    )
    if not paths["spec"].is_file() or paths["spec"].read_bytes() != canonical_json_bytes(
        expected_spec
    ):
        raise EvaluationError("Stage 09 orphan worker specification changed")
    spawn_intent = _validate_spawn_intent(
        cell=cell,
        paths=paths,
        spec=expected_spec,
    )
    intent_launch_token = cast(str, spawn_intent["launch_token"])
    launch: dict[str, object] | None = None
    authorization: dict[str, object] | None = None
    if paths["launch"].is_file():
        launch_preview = _load_canonical_sealed(
            paths["launch"],
            schema=LAUNCH_RECEIPT_SCHEMA,
            hash_field="launch_receipt_hash",
            label="process launch receipt",
        )
        launch_token = launch_preview.get("launch_token")
        if launch_token != intent_launch_token:
            raise EvaluationError("Stage 09 orphan launch token is invalid")
        command = _worker_command(
            paths["spec"],
            paths["raw"],
            launch_path=paths["launch"],
            authorization_path=paths["authorization"],
            abort_path=paths["abort"],
            launch_token=launch_token,
        )
        launch = _validate_launch_receipt(
            paths["launch"],
            cell=cell,
            command=command,
            spec=expected_spec,
            spec_path=paths["spec"],
            exposure_event=exposure_event,
            paths=paths,
        )
        if paths["authorization"].is_file():
            authorization = _validate_authorization_receipt(
                paths["authorization"],
                cell=cell,
                command=command,
                spec=expected_spec,
                spec_path=paths["spec"],
                exposure_event=exposure_event,
                paths=paths,
                launch=launch,
            )
    stored_token = launch.get("process_creation_token") if launch is not None else None
    pid_value = launch.get("pid") if launch is not None else None
    live_token = _process_creation_token(pid_value) if isinstance(pid_value, int) else None
    termination: dict[str, object] | None = None
    abort: dict[str, object] | None = None
    process_enumeration: dict[str, object] | None = None
    cleanup_claimed = False
    if launch is None:
        if paths["abort"].is_file():
            abort = _load_canonical_sealed(
                paths["abort"],
                schema=WORKER_ABORT_SCHEMA,
                hash_field="worker_abort_hash",
                label="pre-environment worker abort receipt",
            )
            if (
                abort.get("cell_id") != cell.cell_id
                or abort.get("environment_opened") is not False
                or abort.get("launch_receipt_path") != paths["launch"].resolve().as_posix()
                or abort.get("authorization_path") != paths["authorization"].resolve().as_posix()
                or abort.get("reason") != "launch-authorization-unavailable-or-invalid"
                or isinstance(abort.get("pid"), bool)
                or not isinstance(abort.get("pid"), int)
                or cast(int, abort.get("pid")) <= 0
                or not isinstance(abort.get("launch_token"), str)
                or abort.get("launch_token") != intent_launch_token
            ):
                raise EvaluationError("Stage 09 worker abort receipt changed")
        matches, enumeration_error = _spawn_intent_processes(intent_launch_token)
        process_enumeration = {
            "error": enumeration_error,
            "matching_processes": matches,
            "verified_empty": enumeration_error is None and not matches,
        }
        if enumeration_error is not None or len(matches) > 1:
            raise EvaluationError("Stage 09 unreceipted spawn process authority is ambiguous")
        if matches:
            match = matches[0]
            pid_value = cast(int, match["pid"])
            stored_token = cast(str, match["process_creation_token"])
            live_token = stored_token
            termination = _terminate_orphan_exact(pid_value, stored_token)
            if termination.get("passed") is not True:
                raise EvaluationError("Stage 09 unreceipted spawn process tree did not terminate")
            state = "unreceipted-launch-terminated"
            passed = True
            cleanup_claimed = True
        elif abort is not None:
            state = "pre-environment-handshake-aborted"
            passed = True
        else:
            state = "unreceipted-launch-not-running"
            passed = True
    elif live_token is None:
        state = "not-running"
        passed = True
    elif live_token != stored_token:
        state = "pid-reused-original-not-running"
        passed = True
    else:
        termination = _terminate_orphan_exact(cast(int, pid_value), stored_token)
        remaining = termination.get("live_process_token_after")
        if remaining == stored_token:
            raise EvaluationError(
                "Stage 09 exact authorized orphan remains live; terminal sealing is forbidden"
            )
        state = "terminated"
        passed = termination.get("passed") is True
        cleanup_claimed = True
    payload = {
        "schema": ORPHAN_RECEIPT_SCHEMA,
        "cell_id": cell.cell_id,
        "cell_spec_hash": cell.spec_hash,
        "cleanup_claimed": cleanup_claimed,
        "exposure_event_hash": exposure_event.get("event_hash"),
        "abort_receipt_hash": abort.get("worker_abort_hash") if abort is not None else None,
        "abort_receipt_sha256": sha256_file(paths["abort"]) if abort is not None else None,
        "launch_receipt_hash": launch.get("launch_receipt_hash") if launch is not None else None,
        "launch_receipt_sha256": sha256_file(paths["launch"]) if launch is not None else None,
        "authorization_hash": (
            authorization.get("authorization_hash") if authorization is not None else None
        ),
        "authorization_sha256": (
            sha256_file(paths["authorization"]) if authorization is not None else None
        ),
        "launch_token": intent_launch_token,
        "pid": pid_value,
        "process_creation_token": stored_token,
        "process_enumeration": process_enumeration,
        "live_process_token_before": live_token,
        "live_process_token_after": (
            termination.get("live_process_token_after") if termination is not None else live_token
        ),
        "passed": passed,
        "state": state,
        "spawn_intent_hash": spawn_intent.get("spawn_intent_hash"),
        "spawn_intent_sha256": sha256_file(paths["spawn_intent"]),
        "termination": termination,
    }
    sealed = cast(dict[str, object], seal_object(payload, hash_field="orphan_receipt_hash"))
    if paths["orphan"].is_file():
        existing = _validate_orphan_semantics(
            _load_canonical_sealed(
                paths["orphan"],
                schema=ORPHAN_RECEIPT_SCHEMA,
                hash_field="orphan_receipt_hash",
                label="orphan termination receipt",
            )
        )
        # Historic process observations are immutable; reconstruct every static
        # identity and state semantic, then separately prove the exact token is
        # not live now.  A matching live token is retried above before reuse.
        static_fields = (
            "abort_receipt_hash",
            "abort_receipt_sha256",
            "authorization_hash",
            "authorization_sha256",
            "cell_id",
            "cell_spec_hash",
            "exposure_event_hash",
            "launch_receipt_hash",
            "launch_receipt_sha256",
            "launch_token",
            "pid",
            "process_creation_token",
            "schema",
            "spawn_intent_hash",
            "spawn_intent_sha256",
        )
        if any(existing.get(field) != sealed.get(field) for field in static_fields):
            raise EvaluationError("Stage 09 orphan termination identity changed")
        if existing.get("passed") is not True or existing.get("state") not in {
            "not-running",
            "pid-reused-original-not-running",
            "pre-environment-handshake-aborted",
            "terminated",
            "unreceipted-launch-not-running",
            "unreceipted-launch-terminated",
        }:
            raise EvaluationError("Stage 09 orphan termination semantics changed")
        if isinstance(pid_value, int) and isinstance(stored_token, str):
            current = _process_creation_token(pid_value)
            if current == stored_token:
                retried = _terminate_orphan_exact(pid_value, stored_token)
                if retried.get("live_process_token_after") == stored_token:
                    raise EvaluationError("Stage 09 exact authorized orphan remains live on resume")
        return existing
    sealed = _validate_orphan_semantics(sealed)
    _atomic_create(paths["orphan"], canonical_json_bytes(sealed))
    return sealed


def _resource_summary(
    receipts: Sequence[Mapping[str, object]],
    finalizations: Sequence[Mapping[str, object]],
    *,
    runtime_start: Mapping[str, object],
    execution_complete: bool,
    open_segment_charge_ns: int = 0,
) -> dict[str, object]:
    if len(receipts) != len(finalizations):
        raise EvaluationError("Stage 09 receipt/finalization prefix lengths differ")
    if (
        isinstance(open_segment_charge_ns, bool)
        or not isinstance(open_segment_charge_ns, int)
        or open_segment_charge_ns not in {0, CELL_ADMISSION_CHARGE_NS}
    ):
        raise EvaluationError("Stage 09 open active-segment charge is invalid")
    pre_receipt_wall_ns = 0
    measured_wall_ns = 0
    recovery_accounted_wall_ns = 0
    recovery_count = 0
    admission_charges_ns = 0
    supervision_wall_ns = 0
    cpu_values: list[float] = []
    rss_values: list[int] = []
    for receipt, finalization in zip(receipts, finalizations, strict=True):
        resources = receipt.get("resources")
        if not isinstance(resources, dict):
            raise EvaluationError("Stage 09 resource receipt is absent")
        parent = resources.get("pre_receipt_active_wall_ns")
        supervised = resources.get("supervision_wall_ns")
        if isinstance(parent, bool) or not isinstance(parent, int) or parent < 0:
            raise EvaluationError("Stage 09 pre-receipt active wall is invalid")
        if isinstance(supervised, bool) or not isinstance(supervised, int) or supervised < 0:
            raise EvaluationError("Stage 09 supervision wall is invalid")
        if parent < supervised:
            raise EvaluationError("Stage 09 pre-receipt wall is below supervision wall")
        if resources.get("worker_wall_seconds") != WORKER_WALL_SECONDS:
            raise EvaluationError("Stage 09 worker wall limit receipt changed")
        charge = finalization.get("admission_charge_ns")
        if finalization.get("schema") == RECOVERED_CELL_FINALIZATION_SCHEMA:
            accounted = finalization.get("conservative_accounted_active_wall_ns")
            if (
                finalization.get("recovery_kind") != "durable-cell-receipt-without-finalization"
                or finalization.get("measurement_scope")
                != "durable-receipt-present-finalization-missing-after-interruption"
                or finalization.get("measured_active_wall_ns") is not None
                or finalization.get("timing_measurement_available") is not False
                or finalization.get("within_admission_charge") is not False
                or isinstance(accounted, bool)
                or not isinstance(accounted, int)
                or accounted != max(parent, CELL_ADMISSION_CHARGE_NS)
                or charge != CELL_ADMISSION_CHARGE_NS
                or finalization.get("budget_accounting") != "fixed-full-cell-admission-charge"
                or finalization.get("normal_termination_definition")
                != NORMAL_TERMINATION_DEFINITION
            ):
                raise EvaluationError("Stage 09 recovered cell finalization timing changed")
            recovery_accounted_wall_ns += accounted
            recovery_count += 1
        else:
            measured = finalization.get("measured_active_wall_ns")
            if (
                isinstance(measured, bool)
                or not isinstance(measured, int)
                or measured < parent
                or charge != CELL_ADMISSION_CHARGE_NS
                or finalization.get("budget_accounting") != "fixed-full-cell-admission-charge"
                or finalization.get("normal_termination_definition")
                != NORMAL_TERMINATION_DEFINITION
                or finalization.get("within_admission_charge")
                is not (measured <= CELL_ADMISSION_CHARGE_NS)
            ):
                raise EvaluationError("Stage 09 cell finalization timing changed")
            measured_wall_ns += measured
        pre_receipt_wall_ns += parent
        admission_charges_ns += CELL_ADMISSION_CHARGE_NS
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
        "admission_accounting": "fixed-full-cell-admission-charge",
        "cell_admission_charge_ns": CELL_ADMISSION_CHARGE_NS,
        "cumulative_admission_charge_ns": admission_charges_ns,
        "cumulative_active_accounted_wall_ns": (
            measured_wall_ns + recovery_accounted_wall_ns + open_segment_charge_ns
        ),
        "cumulative_measured_active_wall_ns": measured_wall_ns,
        "cumulative_recovery_accounted_active_wall_ns": recovery_accounted_wall_ns,
        "cumulative_pre_receipt_active_wall_ns": pre_receipt_wall_ns,
        "cumulative_worker_supervision_wall_ns": supervision_wall_ns,
        "overall_active_wall_limit_ns": limit_ns,
        "open_segment_conservative_charge_ns": open_segment_charge_ns,
        "recovered_cell_finalization_count": recovery_count,
        "runtime_end": _runtime_identity(),
        "runtime_start": dict(runtime_start),
        "wall_measurement_complete": execution_complete,
        "wall_within_limit": (
            measured_wall_ns + recovery_accounted_wall_ns + open_segment_charge_ns <= limit_ns
        ),
    }


def _execution_boundaries(
    check: Mapping[str, object],
    *,
    harness_end: Mapping[str, object] | None,
    runtime_end: Mapping[str, object] | None,
    authority_end: Mapping[str, object] | None,
    cache_end: Mapping[str, object] | None,
) -> dict[str, object]:
    raw_harness = check.get("harness_source")
    harness = raw_harness if isinstance(raw_harness, dict) else {}
    raw_runtime = check.get("runtime_environment")
    runtime = raw_runtime if isinstance(raw_runtime, dict) else {}
    raw_cache = check.get("environment_cache")
    cache = raw_cache if isinstance(raw_cache, dict) else {}
    expected_harness = harness.get("expected")
    harness_start = harness.get("start")
    expected_runtime = runtime.get("expected")
    runtime_start = runtime.get("start")
    authority_start = check.get("prior_authority")
    cache_start = cache.get("start")
    harness_stable = bool(
        isinstance(expected_harness, dict)
        and isinstance(harness_start, dict)
        and harness_end is not None
        and harness_source_stable(
            harness_start,
            harness_end,
            expected=expected_harness,
        )
    )
    runtime_stable = bool(
        isinstance(expected_runtime, dict)
        and isinstance(runtime_start, dict)
        and runtime_end is not None
        and runtime_environment_stable(
            runtime_start,
            runtime_end,
            expected=expected_runtime,
        )
    )
    authority_stable = bool(
        isinstance(authority_start, dict)
        and authority_end is not None
        and _prior_authority_stable(authority_start, authority_end)
    )
    cache_stable = bool(
        isinstance(cache_start, dict)
        and cache_end is not None
        and _environment_cache_stable(cache_start, cache_end)
    )
    return {
        "harness_source": {
            "expected": expected_harness,
            "start": harness_start,
            "end": dict(harness_end) if harness_end is not None else None,
            "stable": harness_stable,
        },
        "runtime_environment": {
            "expected": expected_runtime,
            "start": runtime_start,
            "end": dict(runtime_end) if runtime_end is not None else None,
            "stable": runtime_stable,
        },
        "prior_authority": {
            "start": authority_start,
            "end": dict(authority_end) if authority_end is not None else None,
            "stable": authority_stable,
        },
        "environment_cache": {
            "start": cache_start,
            "end": dict(cache_end) if cache_end is not None else None,
            "stable": cache_stable,
        },
        "passed": harness_stable and runtime_stable and authority_stable and cache_stable,
    }


def _receipt_after_boundaries(
    receipt: Mapping[str, object],
) -> tuple[
    dict[str, object],
    dict[str, object],
    dict[str, object],
    dict[str, object],
]:
    observations: list[dict[str, object]] = []
    for section_name in (
        "harness_source",
        "runtime_environment",
        "prior_authority",
        "environment_cache",
    ):
        section = receipt.get(section_name)
        after = section.get("after") if isinstance(section, dict) else None
        if not isinstance(after, dict):
            raise EvaluationError("Stage 09 cell after-boundary projection is absent")
        observations.append(cast(dict[str, object], after))
    return observations[0], observations[1], observations[2], observations[3]


def _failure_terminal(
    *,
    output: Path,
    check: Mapping[str, object],
    receipts: Sequence[Mapping[str, object]],
    finalizations: Sequence[Mapping[str, object]],
    exposure: Path,
    failed_cell: DevelopmentCell,
    failure_kind: str,
    exposure_event_hash: object,
    orphan_process: Mapping[str, object] | None = None,
    harness_end: Mapping[str, object] | None = None,
    runtime_end: Mapping[str, object] | None = None,
    authority_end: Mapping[str, object] | None = None,
    cache_end: Mapping[str, object] | None = None,
) -> dict[str, object]:
    final = _failure_terminal_value(
        check=check,
        receipts=receipts,
        finalizations=finalizations,
        exposure=exposure,
        failed_cell=failed_cell,
        failure_kind=failure_kind,
        exposure_event_hash=exposure_event_hash,
        orphan_process=orphan_process,
        harness_end=harness_end,
        runtime_end=runtime_end,
        authority_end=authority_end,
        cache_end=cache_end,
    )
    return _write_terminal(output, final, check=check)


def _failure_terminal_value(
    *,
    check: Mapping[str, object],
    receipts: Sequence[Mapping[str, object]],
    finalizations: Sequence[Mapping[str, object]],
    exposure: Path,
    failed_cell: DevelopmentCell,
    failure_kind: str,
    exposure_event_hash: object,
    orphan_process: Mapping[str, object] | None = None,
    harness_end: Mapping[str, object] | None = None,
    runtime_end: Mapping[str, object] | None = None,
    authority_end: Mapping[str, object] | None = None,
    cache_end: Mapping[str, object] | None = None,
) -> dict[str, object]:
    runtime_start = check.get("runtime_identity")
    if not isinstance(runtime_start, dict):
        raise EvaluationError("Stage 09 preflight runtime identity is absent")
    open_segment_charge_ns = (
        CELL_ADMISSION_CHARGE_NS
        if failure_kind
        in {
            "exposed-without-terminal-receipt",
            "open-cell-segment-without-finalization",
            "pre-cell-source-runtime-authority-boundary-failed",
        }
        else 0
    )
    payload = {
        "schema": AGGREGATE_SCHEMA,
        "status": "FAILED_INFRASTRUCTURE",
        "evidence_label": "local-public",
        "claim_boundary": CLAIM_BOUNDARY,
        "normal_termination_definition": NORMAL_TERMINATION_DEFINITION,
        "execution_complete": False,
        "matrix_hash": matrix_hash(),
        "expected_cell_count": EXPECTED_CELL_COUNT,
        "cell_count": len(receipts),
        "cell_receipt_hashes": [receipt.get("cell_receipt_hash") for receipt in receipts],
        "cell_finalization_hashes": [
            finalization.get("finalization_hash") for finalization in finalizations
        ],
        "failure": {
            "cell_id": failed_cell.cell_id,
            "cell_ordinal": failed_cell.ordinal,
            "exposure_event_hash": exposure_event_hash,
            "kind": failure_kind,
        },
        "orphan_process": dict(orphan_process) if orphan_process is not None else None,
        "preflight": dict(check),
        "execution_boundaries": _execution_boundaries(
            check,
            harness_end=harness_end,
            runtime_end=runtime_end,
            authority_end=authority_end,
            cache_end=cache_end,
        ),
        "resources": _resource_summary(
            receipts,
            finalizations,
            runtime_start=runtime_start,
            execution_complete=False,
            open_segment_charge_ns=open_segment_charge_ns,
        ),
        "exposure_ledger_sha256": sha256_file(exposure) if exposure.is_file() else None,
        "holdout": dict(SEALED_HOLDOUT),
    }
    return cast(dict[str, object], seal_object(payload, hash_field="artifact_core_hash"))


def _load_receipt_prefix(
    *,
    work_root: Path,
    count: int,
    recordings: Path,
    environments: Path,
    build_000_root: Path,
    build_001_root: Path,
    runtime_identity: Mapping[str, object],
    check: Mapping[str, object],
    exposure_events: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    matrix = build_matrix()
    if not 0 <= count <= len(matrix):
        raise EvaluationError("Stage 09 terminal cell count is invalid")
    if len(exposure_events) < count:
        raise EvaluationError("Stage 09 receipt prefix exceeds its exposure prefix")
    receipts: list[dict[str, object]] = []
    for ordinal, cell in enumerate(matrix[:count]):
        receipts.append(
            _reconstruct_cell_receipt(
                work_root=work_root,
                recordings=recordings,
                environments=environments,
                build_000_root=build_000_root,
                build_001_root=build_001_root,
                runtime_identity=runtime_identity,
                check=check,
                cell=cell,
                exposure_event=exposure_events[ordinal],
            )
        )
    return receipts


def _load_finalization_prefix(
    *,
    work_root: Path,
    receipts: Sequence[Mapping[str, object]],
    check: Mapping[str, object],
    recover_missing: bool = False,
) -> list[dict[str, object]]:
    matrix = build_matrix()
    if len(receipts) > len(matrix):
        raise EvaluationError("Stage 09 finalization prefix exceeds the matrix")
    finalizations: list[dict[str, object]] = []
    for cell, receipt in zip(matrix, receipts, strict=False):
        paths = _cell_paths(work_root, cell)
        parent_evidence = _load_canonical_sealed(
            paths["parent_evidence"],
            schema=PARENT_EVIDENCE_SCHEMA,
            hash_field="parent_evidence_hash",
            label="parent resource evidence",
        )
        cell_segment = _load_cell_segment(cell=cell, paths=paths, check=check)
        if recover_missing and not paths["finalization"].exists():
            recovered = _recovered_cell_finalization(
                cell,
                paths=paths,
                receipt=receipt,
                parent_evidence=parent_evidence,
                cell_segment=cell_segment,
            )
            _atomic_create(paths["finalization"], canonical_json_bytes(recovered))
        finalizations.append(
            _reconstruct_cell_finalization(
                paths=paths,
                cell=cell,
                receipt=receipt,
                parent_evidence=parent_evidence,
                check=check,
            )
        )
    return finalizations


def _load_existing_terminal(
    *,
    output: Path,
    work_root: Path,
    exposure: Path,
    check: Mapping[str, object],
    recordings: Path = DEFAULT_RECORDINGS,
    environments: Path = DEFAULT_ENVIRONMENTS,
    build_000_root: Path = DEFAULT_BUILD_000_ROOT,
    build_001_root: Path = DEFAULT_BUILD_001_ROOT,
    allow_recovery: bool = True,
) -> dict[str, object] | None:
    if not output.exists():
        return None
    prior = _load_canonical_sealed(
        output,
        schema=AGGREGATE_SCHEMA,
        hash_field="artifact_core_hash",
        label="terminal output",
    )
    prior_wall = prior.get("run_active_wall")
    if not isinstance(prior_wall, dict):
        raise EvaluationError("existing Stage 09 terminal run wall is absent")
    prior_active_wall = prior_wall.get("active_before_output_ns")
    if isinstance(prior_active_wall, bool) or not isinstance(prior_active_wall, int):
        raise EvaluationError("existing Stage 09 terminal run wall is invalid")
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
    events = _validate_exposures(exposure)
    embedded_preflight = prior.get("preflight")
    if (
        not isinstance(embedded_preflight, dict)
        or embedded_preflight.get("schema") != PREFLIGHT_SCHEMA
        or embedded_preflight.get("status") != "READY_NOT_EXECUTED"
        or not verify_object_hash(embedded_preflight, hash_field="preflight_hash")
        or embedded_preflight.get("gameplay_opened") is not False
    ):
        raise EvaluationError("existing Stage 09 preflight evidence changed")
    embedded_exposure_count = embedded_preflight.get("stage09_exposure_event_count")
    if (
        isinstance(embedded_exposure_count, bool)
        or not isinstance(embedded_exposure_count, int)
        or not 0 <= embedded_exposure_count <= len(events)
    ):
        raise EvaluationError("existing Stage 09 preflight exposure boundary changed")
    expected_preflight = dict(check)
    expected_preflight.pop("preflight_hash", None)
    expected_preflight["stage09_exposure_event_count"] = embedded_exposure_count
    expected_preflight = seal_object(expected_preflight, hash_field="preflight_hash")
    if embedded_preflight != expected_preflight:
        raise EvaluationError("existing Stage 09 preflight does not reconstruct from live evidence")
    runtime_start = embedded_preflight.get("runtime_identity")
    if not isinstance(runtime_start, dict):
        raise EvaluationError("embedded Stage 09 runtime identity is absent")
    receipts = _load_receipt_prefix(
        work_root=work_root,
        count=count,
        recordings=recordings,
        environments=environments,
        build_000_root=build_000_root,
        build_001_root=build_001_root,
        runtime_identity=runtime_start,
        check=check,
        exposure_events=events,
    )
    finalizations = _load_finalization_prefix(
        work_root=work_root,
        receipts=receipts,
        check=check,
    )
    if prior.get("cell_receipt_hashes") != [
        receipt.get("cell_receipt_hash") for receipt in receipts
    ]:
        raise EvaluationError("existing Stage 09 terminal receipt projection changed")
    if prior.get("cell_finalization_hashes") != [
        finalization.get("finalization_hash") for finalization in finalizations
    ]:
        raise EvaluationError("existing Stage 09 terminal finalization projection changed")
    execution_complete = prior.get("execution_complete")
    if not allow_recovery and execution_complete is not True:
        raise EvaluationError("Stage 09 read-only verifier requires complete execution")
    prior_failure = prior.get("failure")
    prior_failure_kind = prior_failure.get("kind") if isinstance(prior_failure, dict) else None
    open_segment_charge_ns = (
        CELL_ADMISSION_CHARGE_NS
        if execution_complete is False
        and prior_failure_kind
        in {
            "exposed-without-terminal-receipt",
            "open-cell-segment-without-finalization",
            "pre-cell-source-runtime-authority-boundary-failed",
        }
        else 0
    )
    expected_resources = _resource_summary(
        receipts,
        finalizations,
        runtime_start=runtime_start,
        execution_complete=execution_complete is True,
        open_segment_charge_ns=open_segment_charge_ns,
    )
    if prior.get("resources") != expected_resources:
        raise EvaluationError("existing Stage 09 resource projection changed")
    live_exposure_sha256 = sha256_file(exposure) if exposure.is_file() else None
    if prior.get("exposure_ledger_sha256") != live_exposure_sha256:
        raise EvaluationError("existing Stage 09 exposure file projection changed")
    if execution_complete is True:
        if count != EXPECTED_CELL_COUNT or len(events) != EXPECTED_CELL_COUNT:
            raise EvaluationError("existing complete Stage 09 terminal is not matrix-complete")
        integrity = check.get("competition_integrity")
        if not isinstance(integrity, dict) or not all(
            isinstance(value, dict) and value.get("passed") is True for value in integrity.values()
        ):
            raise EvaluationError("existing Stage 09 competition integrity does not verify")
        live_sources = check.get("sources")
        start_sources = embedded_preflight.get("sources")
        if not isinstance(live_sources, dict) or not isinstance(start_sources, dict):
            raise EvaluationError("existing Stage 09 source boundary is absent")
        source_000 = live_sources.get("build_000")
        source_001 = live_sources.get("build_001")
        start_000 = start_sources.get("build_000")
        start_001 = start_sources.get("build_001")
        if not all(
            isinstance(value, dict) for value in (source_000, source_001, start_000, start_001)
        ):
            raise EvaluationError("existing Stage 09 source boundary is malformed")
        source_stable = _source_stable(
            cast(dict[str, object], start_000), cast(dict[str, object], source_000)
        ) and _source_stable(
            cast(dict[str, object], start_001), cast(dict[str, object], source_001)
        )
        asset_end = check.get("assets")
        if not isinstance(asset_end, dict) or asset_end.get("passed") is not True:
            raise EvaluationError("existing Stage 09 live asset boundary does not verify")
        (
            _harness_expected,
            harness_end,
            _runtime_expected,
            runtime_end,
            authority_end,
            cache_end,
        ) = _preflight_boundary_snapshot(check)
        execution_boundaries = _execution_boundaries(
            embedded_preflight,
            harness_end=harness_end,
            runtime_end=runtime_end,
            authority_end=authority_end,
            cache_end=cache_end,
        )
        evidence_integrity = bool(
            source_stable
            and execution_boundaries["passed"] is True
            and asset_end["passed"] is True
            and len(events) == EXPECTED_CELL_COUNT
            and expected_resources["wall_within_limit"] is True
        )
        expected = aggregate(
            receipts,
            evidence_integrity=evidence_integrity,
            competition_integrity=True,
        )
        expected.update(
            {
                "preflight": embedded_preflight,
                "execution_complete": True,
                "expected_cell_count": EXPECTED_CELL_COUNT,
                "cell_finalization_hashes": [
                    item.get("finalization_hash") for item in finalizations
                ],
                "execution_boundaries": execution_boundaries,
                "resources": expected_resources,
                "source_end": {
                    "build_000": source_000,
                    "build_001": source_001,
                },
                "source_stable": source_stable,
                "asset_end": asset_end,
                "exposure_ledger_sha256": sha256_file(exposure),
                "holdout": dict(SEALED_HOLDOUT),
            }
        )
        expected_terminal = _bind_terminal_clock(
            seal_object(expected, hash_field="artifact_core_hash"),
            check=embedded_preflight,
            active_before_output_ns=prior_active_wall,
        )
        if prior != expected_terminal:
            raise EvaluationError(
                "existing complete Stage 09 terminal does not reconstruct exactly"
            )
    elif execution_complete is False:
        if (
            prior.get("status") != "FAILED_INFRASTRUCTURE"
            or prior.get("normal_termination_definition") != NORMAL_TERMINATION_DEFINITION
            or len(events) not in {count, count + 1}
            or count >= EXPECTED_CELL_COUNT
        ):
            raise EvaluationError("existing partial Stage 09 terminal is not fail-closed")
        embedded_boundaries = prior.get("execution_boundaries")
        if not isinstance(embedded_boundaries, dict):
            raise EvaluationError("existing Stage 09 failure boundaries are absent")

        def _terminal_end(section: str) -> dict[str, object] | None:
            raw_section = embedded_boundaries.get(section)
            if not isinstance(raw_section, dict):
                raise EvaluationError("existing Stage 09 failure boundary section changed")
            end = raw_section.get("end")
            if end is not None and not isinstance(end, dict):
                raise EvaluationError("existing Stage 09 failure boundary endpoint changed")
            return cast(dict[str, object] | None, end)

        partial_harness_end = _terminal_end("harness_source")
        partial_runtime_end = _terminal_end("runtime_environment")
        partial_authority_end = _terminal_end("prior_authority")
        partial_cache_end = _terminal_end("environment_cache")
        if partial_harness_end is not None:
            expected_harness = cast(
                dict[str, object],
                cast(dict[str, object], embedded_preflight["harness_source"])["expected"],
            )
            validate_harness_source_observation(partial_harness_end, expected=expected_harness)
        if partial_runtime_end is not None:
            expected_runtime = cast(
                dict[str, object],
                cast(dict[str, object], embedded_preflight["runtime_environment"])["expected"],
            )
            validate_runtime_environment_observation(partial_runtime_end, expected=expected_runtime)
        if partial_authority_end is not None:
            validate_prior_authority_observation(partial_authority_end)
        if partial_cache_end is not None:
            validate_environment_cache_observation(partial_cache_end)
        reconstructed_boundaries = _execution_boundaries(
            embedded_preflight,
            harness_end=partial_harness_end,
            runtime_end=partial_runtime_end,
            authority_end=partial_authority_end,
            cache_end=partial_cache_end,
        )
        if embedded_boundaries != reconstructed_boundaries:
            raise EvaluationError("existing Stage 09 failure boundaries do not reconstruct")

        matrix = build_matrix()
        orphan: dict[str, object] | None = None
        if (
            count > 0
            and finalizations[-1].get("recovery_kind")
            == "durable-cell-receipt-without-finalization"
        ):
            failed_cell = matrix[count - 1]
            failure_kind = "durable-cell-receipt-without-finalization"
            expected_exposure_hash = events[count - 1].get("event_hash")
        elif count > 0 and finalizations[-1].get("within_admission_charge") is not True:
            failed_cell = matrix[count - 1]
            failure_kind = "cell-finalization-exceeded-admission-charge"
            expected_exposure_hash = events[count - 1].get("event_hash")
        elif count > 0 and receipts[-1].get("status") == CellStatus.INFRASTRUCTURE_FAILURE.value:
            failed_cell = matrix[count - 1]
            failure_kind = "terminal-cell-infrastructure-failure"
            expected_exposure_hash = events[count - 1].get("event_hash")
        elif len(events) == count + 1:
            failed_cell = matrix[count]
            failure_kind = "exposed-without-terminal-receipt"
            expected_exposure_hash = events[count].get("event_hash")
            orphan = _seal_orphan_boundary(
                work_root=work_root,
                recordings=recordings,
                environments=environments,
                build_000_root=build_000_root,
                build_001_root=build_001_root,
                runtime_identity=runtime_start,
                check=check,
                cell=failed_cell,
                exposure_event=events[count],
            )
        else:
            failed_cell = matrix[count]
            expected_exposure_hash = None
            used = count * CELL_ADMISSION_CHARGE_NS
            limit = int(OVERALL_ACTIVE_WALL_SECONDS * 1_000_000_000)
            failed_paths = _cell_paths(work_root, failed_cell)
            if failed_paths["cell_segment"].exists():
                _load_cell_segment(cell=failed_cell, paths=failed_paths, check=check)
                failure_kind = "open-cell-segment-without-finalization"
            elif limit - used < CELL_ADMISSION_CHARGE_NS:
                failure_kind = "overall-active-wall-cannot-admit-next-cell"
            elif reconstructed_boundaries.get("passed") is False:
                failure_kind = "pre-cell-source-runtime-authority-boundary-failed"
            else:
                raise EvaluationError("existing Stage 09 failure cause is not reconstructible")
        expected_terminal = _bind_terminal_clock(
            _failure_terminal_value(
                check=embedded_preflight,
                receipts=receipts,
                finalizations=finalizations,
                exposure=exposure,
                failed_cell=failed_cell,
                failure_kind=failure_kind,
                exposure_event_hash=expected_exposure_hash,
                orphan_process=orphan,
                harness_end=partial_harness_end,
                runtime_end=partial_runtime_end,
                authority_end=partial_authority_end,
                cache_end=partial_cache_end,
            ),
            check=embedded_preflight,
            active_before_output_ns=prior_active_wall,
        )
        if prior != expected_terminal:
            raise EvaluationError("existing partial Stage 09 terminal does not reconstruct exactly")
    else:
        raise EvaluationError("existing Stage 09 terminal completion state is invalid")
    _validate_terminal_finalization(
        output,
        prior,
        check=embedded_preflight,
        recover_missing=allow_recovery,
    )
    return cast(dict[str, object], prior)


def verify_complete_terminal(
    *,
    source_root: Path,
    attempt_root: Path,
    output: Path,
    exposure: Path,
    expected_output_sha256: str,
    expected_artifact_core_hash: str,
    expected_terminal_finalization_sha256: str,
    expected_terminal_finalization_hash: str,
    recordings: Path = DEFAULT_RECORDINGS,
    environments: Path = DEFAULT_ENVIRONMENTS,
    build_000_root: Path = DEFAULT_BUILD_000_ROOT,
    build_001_root: Path = DEFAULT_BUILD_001_ROOT,
    stage08_result: Path = DEFAULT_STAGE08_RESULT,
    stage08_exposure: Path = DEFAULT_STAGE08_EXPOSURE,
    prior_integrity_receipt: Path = DEFAULT_PRIOR_INTEGRITY_RECEIPT,
    build_000_integrity_receipt: Path = DEFAULT_BUILD_000_INTEGRITY_RECEIPT,
) -> dict[str, object]:
    """Authenticate one complete terminal graph without opening gameplay.

    ``passed`` means evidence authority, not mechanism success.  The returned
    ``status`` remains ``PASS`` or ``FAILED_MECHANISM`` so Stage 11 can require
    the former while Stage 10 can still consume an honest completed failure.
    """

    if source_root.resolve() != ROOT.resolve():
        raise EvaluationError("Stage 09 verifier source root differs from its imported authority")
    if not output.is_file() or sha256_file(output) != expected_output_sha256:
        raise EvaluationError("Stage 09 verifier output file hash changed")
    candidate = _load_canonical_sealed(
        output,
        schema=AGGREGATE_SCHEMA,
        hash_field="artifact_core_hash",
        label="terminal output",
    )
    if candidate.get("artifact_core_hash") != expected_artifact_core_hash:
        raise EvaluationError("Stage 09 verifier terminal core hash changed")
    embedded_preflight = candidate.get("preflight")
    harness_source = (
        embedded_preflight.get("harness_source") if isinstance(embedded_preflight, dict) else None
    )
    harness_source_expected = (
        harness_source.get("expected") if isinstance(harness_source, dict) else None
    )
    if not isinstance(harness_source_expected, dict):
        raise EvaluationError("Stage 09 verifier harness authority is absent")
    check = preflight(
        harness_source_expected=cast(dict[str, object], harness_source_expected),
        output=output,
        work_root=attempt_root,
        exposure=exposure,
        recordings=recordings,
        environments=environments,
        build_000_root=build_000_root,
        build_001_root=build_001_root,
        stage08_result=stage08_result,
        stage08_exposure=stage08_exposure,
        prior_integrity_receipt=prior_integrity_receipt,
        build_000_integrity_receipt=build_000_integrity_receipt,
        enforce_official_paths=False,
    )
    if check.get("status") != "READY_NOT_EXECUTED":
        raise EvaluationError("Stage 09 verifier live preflight is not ready")
    live_harness = check.get("harness_source")
    live_expected = live_harness.get("expected") if isinstance(live_harness, dict) else None
    binding_hash = live_expected.get("binding_hash") if isinstance(live_expected, dict) else None
    check = _attach_run_clock(
        check,
        work_root=attempt_root,
        harness_binding_hash=binding_hash,
        create_missing=False,
    )
    terminal = _load_existing_terminal(
        output=output,
        work_root=attempt_root,
        exposure=exposure,
        check=check,
        recordings=recordings,
        environments=environments,
        build_000_root=build_000_root,
        build_001_root=build_001_root,
        allow_recovery=False,
    )
    if terminal is None:
        raise EvaluationError("Stage 09 verifier terminal output is absent")
    gate = terminal.get("gate")
    if (
        terminal.get("status") not in {"PASS", "FAILED_MECHANISM"}
        or terminal.get("execution_complete") is not True
        or not isinstance(gate, dict)
        or gate.get("all_evidence_verifies") is not True
        or gate.get("competition_integrity") is not True
        or terminal.get("source_stable") is not True
        or terminal.get("cell_count") != EXPECTED_CELL_COUNT
    ):
        raise EvaluationError("Stage 09 verifier terminal is not evidence-complete")
    finalization_path = _terminal_finalization_path(output)
    if (
        not finalization_path.is_file()
        or sha256_file(finalization_path) != expected_terminal_finalization_sha256
    ):
        raise EvaluationError("Stage 09 verifier terminal finalization file hash changed")
    finalization = _load_canonical_sealed(
        finalization_path,
        schema=TERMINAL_FINALIZATION_SCHEMA,
        hash_field="terminal_finalization_hash",
        label="terminal finalization receipt",
    )
    evidence_authority = _terminal_evidence_authority(check)
    if (
        finalization.get("terminal_finalization_hash") != expected_terminal_finalization_hash
        or finalization.get("within_overall_active_wall") is not True
        or finalization.get("terminal_authority_passed") is not True
        or finalization.get("recovery_kind") is not None
        or finalization.get("timing_measurement_available") is not True
        or finalization.get("artifact_core_hash") != terminal.get("artifact_core_hash")
        or finalization.get("output_sha256") != expected_output_sha256
        or finalization.get("evidence_authority") != evidence_authority
        or sha256_file(output) != expected_output_sha256
    ):
        raise EvaluationError("Stage 09 verifier terminal finalization authority changed")
    return cast(
        dict[str, object],
        seal_object(
            {
                "schema": TERMINAL_VERIFICATION_SCHEMA,
                "passed": True,
                "source_root": source_root.resolve().as_posix(),
                "attempt_root": attempt_root.resolve().as_posix(),
                "output": {
                    "path": output.resolve().as_posix(),
                    "sha256": expected_output_sha256,
                    "artifact_core_hash": terminal["artifact_core_hash"],
                },
                "exposure": {
                    "path": exposure.resolve().as_posix(),
                    "sha256": terminal["exposure_ledger_sha256"],
                },
                "terminal_finalization": {
                    "path": finalization_path.resolve().as_posix(),
                    "sha256": expected_terminal_finalization_sha256,
                    "terminal_finalization_hash": finalization["terminal_finalization_hash"],
                },
                "work_authority": {
                    "cell_count": terminal["cell_count"],
                    "cell_receipt_hashes": terminal["cell_receipt_hashes"],
                    "cell_finalization_hashes": terminal["cell_finalization_hashes"],
                    "matrix_hash": terminal["matrix_hash"],
                },
                "status": terminal["status"],
                "execution_complete": terminal["execution_complete"],
                "evidence_integrity": gate["all_evidence_verifies"],
                "competition_integrity": gate["competition_integrity"],
                "prior_authority": evidence_authority,
                "source_end": terminal["source_end"],
                "source_stable": terminal["source_stable"],
                "gate": terminal["gate"],
            },
            hash_field="verification_hash",
        ),
    )


def execute(
    *,
    harness_source_expected: Mapping[str, object],
    output: Path = DEFAULT_OUTPUT,
    work_root: Path = DEFAULT_WORK_ROOT,
    exposure: Path = DEFAULT_EXPOSURE,
    recordings: Path = DEFAULT_RECORDINGS,
    environments: Path = DEFAULT_ENVIRONMENTS,
    build_000_root: Path = DEFAULT_BUILD_000_ROOT,
    build_001_root: Path = DEFAULT_BUILD_001_ROOT,
    stage08_result: Path = DEFAULT_STAGE08_RESULT,
    stage08_exposure: Path = DEFAULT_STAGE08_EXPOSURE,
    prior_integrity_receipt: Path = DEFAULT_PRIOR_INTEGRITY_RECEIPT,
    build_000_integrity_receipt: Path = DEFAULT_BUILD_000_INTEGRITY_RECEIPT,
) -> dict[str, object]:
    """Execute exactly once; exposed cells are never relaunched."""

    if (
        not isinstance(_BOOTSTRAP_AUTHORITY, dict)
        or _BOOTSTRAP_AUTHORITY.get("files")
        != cast(dict[str, object], harness_source_expected).get("files")
        or _BOOTSTRAP_AUTHORITY.get("git_commit")
        != cast(dict[str, object], harness_source_expected).get("git_commit")
        or _BOOTSTRAP_AUTHORITY.get("git_tree")
        != cast(dict[str, object], harness_source_expected).get("git_tree")
        or _BOOTSTRAP_AUTHORITY.get("runtime_binding_hash")
        != EXPECTED_RUNTIME_ENVIRONMENT.get("runtime_binding_hash")
        or _BOOTSTRAP_AUTHORITY.get("socket_audit_denial_installed") is not True
    ):
        raise EvaluationError(
            "Stage 09 execution requires the exact stdlib-only bootstrap authority"
        )

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
        prior_integrity_receipt=prior_integrity_receipt,
        build_000_integrity_receipt=build_000_integrity_receipt,
    )
    check = preflight(
        harness_source_expected=harness_source_expected,
        output=output,
        work_root=work_root,
        exposure=exposure,
        recordings=recordings,
        environments=environments,
        build_000_root=build_000_root,
        build_001_root=build_001_root,
        stage08_result=stage08_result,
        stage08_exposure=stage08_exposure,
        prior_integrity_receipt=prior_integrity_receipt,
        build_000_integrity_receipt=build_000_integrity_receipt,
    )
    if check["status"] != "READY_NOT_EXECUTED":
        raise EvaluationError("Stage 09 execution preflight is not ready")
    harness_binding = cast(dict[str, object], check["harness_source"])["expected"]
    if not isinstance(harness_binding, dict):
        raise EvaluationError("Stage 09 preflight harness binding is absent")
    check = _attach_run_clock(
        check,
        work_root=work_root,
        harness_binding_hash=harness_binding.get("binding_hash"),
    )
    existing_terminal = _load_existing_terminal(
        output=output,
        work_root=work_root,
        exposure=exposure,
        check=check,
        recordings=recordings,
        environments=environments,
        build_000_root=build_000_root,
        build_001_root=build_001_root,
    )
    if existing_terminal is not None:
        return existing_terminal
    work_root.mkdir(parents=True, exist_ok=True)
    recordings.mkdir(parents=True, exist_ok=True)
    events = _validate_exposures(exposure)
    matrix = build_matrix()
    existing_receipts: list[dict[str, object]] = []
    existing_finalizations: list[dict[str, object]] = []
    for ordinal, cell in enumerate(matrix):
        paths = _cell_paths(work_root, cell)
        receipt_path = paths["receipt"]
        if ordinal < len(events):
            if not receipt_path.is_file():
                orphan = _seal_orphan_boundary(
                    work_root=work_root,
                    recordings=recordings,
                    environments=environments,
                    build_000_root=build_000_root,
                    build_001_root=build_001_root,
                    runtime_identity=cast(dict[str, object], check["runtime_identity"]),
                    check=check,
                    cell=cell,
                    exposure_event=events[ordinal],
                )
                return _failure_terminal(
                    output=output,
                    check=check,
                    receipts=existing_receipts,
                    finalizations=existing_finalizations,
                    exposure=exposure,
                    failed_cell=cell,
                    failure_kind="exposed-without-terminal-receipt",
                    exposure_event_hash=events[ordinal].get("event_hash"),
                    orphan_process=orphan,
                )
            receipt = _reconstruct_cell_receipt(
                work_root=work_root,
                recordings=recordings,
                environments=environments,
                build_000_root=build_000_root,
                build_001_root=build_001_root,
                runtime_identity=cast(dict[str, object], check["runtime_identity"]),
                check=check,
                cell=cell,
                exposure_event=events[ordinal],
            )
            existing_receipts.append(receipt)
            finalization = _load_finalization_prefix(
                work_root=work_root,
                receipts=existing_receipts,
                check=check,
                recover_missing=True,
            )[-1]
            existing_finalizations.append(finalization)
            receipt_ends = _receipt_after_boundaries(receipt)
            if finalization.get("recovery_kind") == "durable-cell-receipt-without-finalization":
                return _failure_terminal(
                    output=output,
                    check=check,
                    receipts=existing_receipts,
                    finalizations=existing_finalizations,
                    exposure=exposure,
                    failed_cell=cell,
                    failure_kind="durable-cell-receipt-without-finalization",
                    exposure_event_hash=events[ordinal].get("event_hash"),
                    harness_end=receipt_ends[0],
                    runtime_end=receipt_ends[1],
                    authority_end=receipt_ends[2],
                    cache_end=receipt_ends[3],
                )
            if finalization.get("within_admission_charge") is not True:
                return _failure_terminal(
                    output=output,
                    check=check,
                    receipts=existing_receipts,
                    finalizations=existing_finalizations,
                    exposure=exposure,
                    failed_cell=cell,
                    failure_kind="cell-finalization-exceeded-admission-charge",
                    exposure_event_hash=events[ordinal].get("event_hash"),
                    harness_end=receipt_ends[0],
                    runtime_end=receipt_ends[1],
                    authority_end=receipt_ends[2],
                    cache_end=receipt_ends[3],
                )
            if receipt["status"] == CellStatus.INFRASTRUCTURE_FAILURE.value:
                return _failure_terminal(
                    output=output,
                    check=check,
                    receipts=existing_receipts,
                    finalizations=existing_finalizations,
                    exposure=exposure,
                    failed_cell=cell,
                    failure_kind="terminal-cell-infrastructure-failure",
                    exposure_event_hash=events[ordinal].get("event_hash"),
                    harness_end=receipt_ends[0],
                    runtime_end=receipt_ends[1],
                    authority_end=receipt_ends[2],
                    cache_end=receipt_ends[3],
                )
            continue
        if paths["cell_segment"].exists():
            _load_cell_segment(cell=cell, paths=paths, check=check)
            return _failure_terminal(
                output=output,
                check=check,
                receipts=existing_receipts,
                finalizations=existing_finalizations,
                exposure=exposure,
                failed_cell=cell,
                failure_kind="open-cell-segment-without-finalization",
                exposure_event_hash=None,
            )
        used_admission_ns = len(existing_finalizations) * CELL_ADMISSION_CHARGE_NS
        remaining_ns = int(OVERALL_ACTIVE_WALL_SECONDS * 1_000_000_000) - used_admission_ns
        if remaining_ns < CELL_ADMISSION_CHARGE_NS:
            return _failure_terminal(
                output=output,
                check=check,
                receipts=existing_receipts,
                finalizations=existing_finalizations,
                exposure=exposure,
                failed_cell=cell,
                failure_kind="overall-active-wall-cannot-admit-next-cell",
                exposure_event_hash=None,
            )
        cell_segment, cell_started_ns = _open_cell_segment(
            cell=cell,
            paths=paths,
            check=check,
        )
        boundary_before = _observe_execution_boundaries(
            harness_source_expected=harness_source_expected,
            environments=environments,
            build_000_root=build_000_root,
            build_001_root=build_001_root,
            prior_integrity_receipt=prior_integrity_receipt,
            build_000_integrity_receipt=build_000_integrity_receipt,
        )
        if not _execution_boundaries_ready(boundary_before):
            return _failure_terminal(
                output=output,
                check=check,
                receipts=existing_receipts,
                finalizations=existing_finalizations,
                exposure=exposure,
                failed_cell=cell,
                failure_kind="pre-cell-source-runtime-authority-boundary-failed",
                exposure_event_hash=None,
                harness_end=boundary_before[0],
                runtime_end=boundary_before[1],
                authority_end=boundary_before[2],
                cache_end=boundary_before[3],
            )
        harness_before = boundary_before[0]
        runtime_before = cast(dict[str, object], boundary_before[1])
        authority_before = cast(dict[str, object], boundary_before[2])
        cache_before = cast(dict[str, object], boundary_before[3])
        source_root = build_001_root if cell.variant is Variant.BUILD_001_FULL else build_000_root
        cell_root = paths["cell_root"]
        spec = _worker_spec(
            cell,
            source_root=source_root,
            environments=environments,
            recordings=recordings,
            cell_root=cell_root,
            runtime_identity=cast(dict[str, object], check["runtime_identity"]),
            harness_source_expected=harness_source_expected,
            harness_source_before=harness_before,
            runtime_environment_expected=EXPECTED_RUNTIME_ENVIRONMENT,
            runtime_environment_before=runtime_before,
        )
        spec_path = paths["spec"]
        _atomic_create_or_verify(
            spec_path, canonical_json_bytes(spec), label="unexposed worker specification"
        )
        _assert_unexposed_cell_clean(paths=paths, recordings=recordings, cell=cell)
        spawn_intent = _prepare_spawn_intent(cell=cell, paths=paths, spec=spec)
        launch_token = cast(str, spawn_intent["launch_token"])
        event = _append_exposure(exposure, cell)
        raw_path = paths["raw"]
        streams = paths["stdout"].parent
        command = _worker_command(
            spec_path,
            raw_path,
            launch_path=paths["launch"],
            authorization_path=paths["authorization"],
            abort_path=paths["abort"],
            launch_token=launch_token,
        )
        if list(command) != spawn_intent.get("command"):
            raise EvaluationError("Stage 09 spawn-intent command changed before launch")
        supervision = _supervise(
            command,
            cwd=ROOT,
            streams=streams,
            timeout_seconds=WORKER_WALL_SECONDS,
            launch_receipt_path=paths["launch"],
            authorization_path=paths["authorization"],
            supervision_receipt_path=paths["supervision"],
            launch_context={
                "cell_id": cell.cell_id,
                "cell_spec_hash": cell.spec_hash,
                "exposure_event_hash": event.get("event_hash"),
                "launch_token": launch_token,
                "authorization_path": paths["authorization"].resolve().as_posix(),
                "abort_path": paths["abort"].resolve().as_posix(),
                "raw_path": raw_path.resolve().as_posix(),
                "stderr_path": paths["stderr"].resolve().as_posix(),
                "stdout_path": paths["stdout"].resolve().as_posix(),
                "worker_spec_hash": spec.get("worker_spec_hash"),
                "worker_spec_sha256": sha256_file(spec_path),
            },
        )
        boundary_after = _observe_execution_boundaries(
            harness_source_expected=harness_source_expected,
            environments=environments,
            build_000_root=build_000_root,
            build_001_root=build_001_root,
            prior_integrity_receipt=prior_integrity_receipt,
            build_000_integrity_receipt=build_000_integrity_receipt,
            short_circuit_on_harness_failure=False,
        )
        harness_after = boundary_after[0]
        runtime_after = cast(dict[str, object], boundary_after[1])
        authority_after = cast(dict[str, object], boundary_after[2])
        cache_after = cast(dict[str, object], boundary_after[3])
        asset_after = _asset_identity(environments, cell)
        pre_receipt_active_wall_ns = max(0, time.perf_counter_ns() - cell_started_ns)
        parent_evidence = _parent_evidence(
            cell,
            paths=paths,
            spec=spec,
            exposure_event=event,
            supervision=supervision,
            asset_after=asset_after,
            pre_receipt_active_wall_ns=pre_receipt_active_wall_ns,
            harness_source_expected=harness_source_expected,
            harness_source_before=harness_before,
            harness_source_after=harness_after,
            runtime_environment_expected=EXPECTED_RUNTIME_ENVIRONMENT,
            runtime_environment_before=runtime_before,
            runtime_environment_after=runtime_after,
            prior_authority_before=authority_before,
            prior_authority_after=authority_after,
            environment_cache_before=cache_before,
            environment_cache_after=cache_after,
        )
        _atomic_create(paths["parent_evidence"], canonical_json_bytes(parent_evidence))
        receipt = _cell_receipt(
            cell,
            spec=spec,
            exposure_event=event,
            supervision=supervision,
            raw_path=raw_path,
            asset_after=asset_after,
            pre_receipt_active_wall_ns=pre_receipt_active_wall_ns,
            spec_path=spec_path,
            launch_receipt_path=paths["launch"],
            authorization_path=paths["authorization"],
            supervision_receipt_path=paths["supervision"],
            parent_evidence_path=paths["parent_evidence"],
            harness_source_expected=harness_source_expected,
            harness_source_before=harness_before,
            harness_source_after=harness_after,
            runtime_environment_expected=EXPECTED_RUNTIME_ENVIRONMENT,
            runtime_environment_before=runtime_before,
            runtime_environment_after=runtime_after,
            prior_authority_before=authority_before,
            prior_authority_after=authority_after,
            environment_cache_before=cache_before,
            environment_cache_after=cache_after,
        )
        _atomic_create(receipt_path, canonical_json_bytes(receipt))
        finalization = _cell_finalization(
            cell,
            paths=paths,
            receipt=receipt,
            parent_evidence=parent_evidence,
            cell_segment=cell_segment,
            measured_active_wall_ns=max(0, time.perf_counter_ns() - cell_started_ns),
        )
        _atomic_create(paths["finalization"], canonical_json_bytes(finalization))
        receipt = _reconstruct_cell_receipt(
            work_root=work_root,
            recordings=recordings,
            environments=environments,
            build_000_root=build_000_root,
            build_001_root=build_001_root,
            runtime_identity=cast(dict[str, object], check["runtime_identity"]),
            check=check,
            cell=cell,
            exposure_event=event,
        )
        existing_receipts.append(receipt)
        finalization = _load_finalization_prefix(
            work_root=work_root,
            receipts=existing_receipts,
            check=check,
        )[-1]
        existing_finalizations.append(finalization)
        if finalization.get("within_admission_charge") is not True:
            return _failure_terminal(
                output=output,
                check=check,
                receipts=existing_receipts,
                finalizations=existing_finalizations,
                exposure=exposure,
                failed_cell=cell,
                failure_kind="cell-finalization-exceeded-admission-charge",
                exposure_event_hash=event.get("event_hash"),
                harness_end=harness_after,
                runtime_end=runtime_after,
                authority_end=authority_after,
                cache_end=cache_after,
            )
        if receipt["status"] == CellStatus.INFRASTRUCTURE_FAILURE.value:
            return _failure_terminal(
                output=output,
                check=check,
                receipts=existing_receipts,
                finalizations=existing_finalizations,
                exposure=exposure,
                failed_cell=cell,
                failure_kind="terminal-cell-infrastructure-failure",
                exposure_event_hash=event.get("event_hash"),
                harness_end=harness_after,
                runtime_end=runtime_after,
                authority_end=authority_after,
                cache_end=cache_after,
            )
    boundary_end = _observe_execution_boundaries(
        harness_source_expected=harness_source_expected,
        environments=environments,
        build_000_root=build_000_root,
        build_001_root=build_001_root,
        prior_integrity_receipt=prior_integrity_receipt,
        build_000_integrity_receipt=build_000_integrity_receipt,
        short_circuit_on_harness_failure=False,
    )
    execution_boundaries = _execution_boundaries(
        check,
        harness_end=boundary_end[0],
        runtime_end=boundary_end[1],
        authority_end=boundary_end[2],
        cache_end=boundary_end[3],
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
    overall_limit_ns = int(OVERALL_ACTIVE_WALL_SECONDS * 1_000_000_000)
    resources = _resource_summary(
        existing_receipts,
        existing_finalizations,
        runtime_start=cast(dict[str, object], check["runtime_identity"]),
        execution_complete=True,
    )
    active_before_terminal_ns = cast(int, resources["cumulative_active_accounted_wall_ns"])
    evidence_integrity = bool(
        source_stable
        and execution_boundaries["passed"] is True
        and asset_end["passed"] is True
        and len(exposures_end) == EXPECTED_CELL_COUNT
        and len(existing_finalizations) * CELL_ADMISSION_CHARGE_NS <= overall_limit_ns
        and active_before_terminal_ns <= overall_limit_ns - TERMINAL_WRITE_RESERVE_NS
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
            "cell_finalization_hashes": [
                item.get("finalization_hash") for item in existing_finalizations
            ],
            "execution_boundaries": execution_boundaries,
            "resources": resources,
            "source_end": {"build_000": end_000, "build_001": end_001},
            "source_stable": source_stable,
            "asset_end": asset_end,
            "exposure_ledger_sha256": sha256_file(exposure),
            "holdout": dict(SEALED_HOLDOUT),
        }
    )
    final = cast(dict[str, object], seal_object(result, hash_field="artifact_core_hash"))
    return _write_terminal(output, final, check=check)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-harness-commit", required=True)
    parser.add_argument("--expected-harness-tree", required=True)
    parser.add_argument("--expected-bootstrap-sha256", required=True)
    parser.add_argument("--expected-supervisor-sha256", required=True)
    parser.add_argument("--expected-worker-sha256", required=True)
    parser.add_argument("--expected-protocol-sha256", required=True)
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
    expected_harness_files = {
        "scripts/measure_development_recovery.py": args.expected_supervisor_sha256,
        "scripts/_stage09_supervisor_bootstrap.py": args.expected_bootstrap_sha256,
        "scripts/_stage09_development_worker.py": args.expected_worker_sha256,
        "src/arc3/evaluation/development_recovery.py": args.expected_protocol_sha256,
    }
    if __name__ == "__main__" and (
        not isinstance(_BOOTSTRAP_AUTHORITY, dict)
        or _BOOTSTRAP_AUTHORITY.get("files") != expected_harness_files
        or _BOOTSTRAP_AUTHORITY.get("git_commit") != args.expected_harness_commit
        or _BOOTSTRAP_AUTHORITY.get("git_tree") != args.expected_harness_tree
        or _BOOTSTRAP_AUTHORITY.get("runtime_binding_hash")
        != EXPECTED_RUNTIME_ENVIRONMENT["runtime_binding_hash"]
        or _BOOTSTRAP_AUTHORITY.get("runtime_binding_file_sha256")
        != sha256_file(ROOT / "docs/evidence/001-09-runtime-binding.json")
    ):
        raise EvaluationError("Stage 09 supervisor bootstrap authority does not bind this launch")
    harness_source_expected = _harness_source_binding(
        git_commit=args.expected_harness_commit,
        git_tree=args.expected_harness_tree,
        files=expected_harness_files,
    )
    keywords = {
        "harness_source_expected": harness_source_expected,
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
