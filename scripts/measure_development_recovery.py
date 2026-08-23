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
    environment_cache_stable,
    harness_source_stable,
    matrix_hash,
    prior_authority_stable,
    runtime_environment_stable,
    validate_environment_cache_observation,
    validate_harness_source_binding,
    validate_harness_source_observation,
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
from arc3.integrity import IntegrityReceipt, discover_policy_files, scan_policy_files  # noqa: E402

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
DEFAULT_PRIOR_INTEGRITY_RECEIPT = Path(
    "C:/a/arc3-b001/artifacts/stage09/policy-integrity-2e78c258-full.json"
)
DEFAULT_BUILD_000_INTEGRITY_RECEIPT = Path(
    "C:/a/arc3-b001/artifacts/stage09/policy-integrity-build000-90ecf726-full.json"
)
HOLDOUT_NONCONSUMPTION_RECEIPT = ROOT / "docs/evidence/001-08-two-speed-controller.json"
PRIOR_INTEGRITY_RECEIPT_SHA256 = (
    "sha256:9fd255b3a32549fd09c12247863319e8662805ed43f874b46e52eb3cb675834f"
)
PRIOR_INTEGRITY_SELF_HASH = (
    "sha256:6926149cafda4248a2dc92b042ab6f087888133daf60d7de0b1f1070f6203e9b"
)
BUILD_000_INTEGRITY_RECEIPT_SHA256 = (
    "sha256:b63ea29913a042930b01ace640c283dd0febce3597b637c3d8433fc981579349"
)
BUILD_000_INTEGRITY_SELF_HASH = (
    "sha256:3545f69c786ed8268d2e3948769a976db920f2b2e79851cb6bb5c6e922601643"
)
HOLDOUT_NONCONSUMPTION_RECEIPT_SHA256 = (
    "sha256:0134c9e5b7acea716f790088cb59109eded7857ce83fda004ea1b88be2eb92ac"
)
PUBLIC_MANIFEST_RELATIVE = Path("docs/evaluation/public-game-partitions.v0.1.json")
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
LAUNCH_RECEIPT_SCHEMA = "arc3.build-001.stage-09-process-launch.v0.1"
LAUNCH_AUTHORIZATION_SCHEMA = "arc3.build-001.stage-09-launch-authorization.v0.1"
WORKER_ABORT_SCHEMA = "arc3.build-001.stage-09-worker-abort.v0.1"
SUPERVISION_RECEIPT_SCHEMA = "arc3.build-001.stage-09-supervision.v0.1"
TIMEOUT_TRACE_SCHEMA = "arc3.build-001.stage-09-timeout-trace.v0.1"
ORPHAN_RECEIPT_SCHEMA = "arc3.build-001.stage-09-orphan-termination.v0.2"
PARENT_EVIDENCE_SCHEMA = "arc3.build-001.stage-09-parent-evidence.v0.2"
RUN_CLOCK_SCHEMA = "arc3.build-001.stage-09-run-clock.v0.1"
TERMINAL_FINALIZATION_SCHEMA = "arc3.build-001.stage-09-terminal-finalization.v0.1"
TERMINAL_WRITE_RESERVE_NS = 1_000_000_000
_SDK_IMPORT_PROBE_CACHE: bool | None = None


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
                str(Path(sys.executable).resolve()),
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


def _prior_authority(
    integrity_receipt: Path = DEFAULT_PRIOR_INTEGRITY_RECEIPT,
    build_000_integrity_receipt: Path = DEFAULT_BUILD_000_INTEGRITY_RECEIPT,
    holdout_receipt: Path = HOLDOUT_NONCONSUMPTION_RECEIPT,
) -> dict[str, object]:
    integrity_001, integrity_001_predicates = _integrity_authority(
        integrity_receipt,
        expected_file_hash=PRIOR_INTEGRITY_RECEIPT_SHA256,
        expected_self_hash=PRIOR_INTEGRITY_SELF_HASH,
        expected_commit=FROZEN_BUILD_001_COMMIT,
    )
    integrity_000, integrity_000_predicates = _integrity_authority(
        build_000_integrity_receipt,
        expected_file_hash=BUILD_000_INTEGRITY_RECEIPT_SHA256,
        expected_self_hash=BUILD_000_INTEGRITY_SELF_HASH,
        expected_commit=FROZEN_BUILD_000_COMMIT,
    )
    holdout_hash = sha256_file(holdout_receipt) if holdout_receipt.is_file() else None
    holdout = load_json(holdout_receipt) if holdout_receipt.is_file() else {}
    holdout_projection = holdout.get("integrity")
    predicates = {
        "build_000_integrity": all(integrity_000_predicates.values()),
        "build_001_integrity": all(integrity_001_predicates.values()),
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
                "holdout": {
                    "file_sha256": holdout_hash,
                    "identities_loaded": 0,
                    "manifest_loaded_as_metadata": False,
                    "path": holdout_receipt.resolve().as_posix(),
                    "status": "SEALED_UNCONSUMED"
                    if predicates["holdout_nonconsumption"]
                    else "UNVERIFIED",
                },
                "integrity": {
                    "build_000": integrity_000,
                    "build_001": integrity_001,
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
                    "predicates": {"harness_source": False},
                },
                hash_field="preflight_hash",
            ),
        )
    runtime_start = _runtime_environment_identity()
    authority_start = _prior_authority(
        prior_integrity_receipt,
        build_000_integrity_receipt,
        HOLDOUT_NONCONSUMPTION_RECEIPT,
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
                    "predicates": identity_predicates,
                },
                hash_field="preflight_hash",
            ),
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
        "matrix_hash": matrix_hash(),
        "sources": {"build_000": source_000, "build_001": source_001},
        "assets": assets,
        "stage08_predecessor": predecessor,
        "inherited_exposures": inherited,
        "stage09_exposure_event_count": len(current_events),
        "public_manifest_hashes": manifest_hashes,
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


def _run_clock(work_root: Path, *, harness_binding_hash: object) -> dict[str, object]:
    path = work_root.resolve() / "run-clock.json"
    boot = _boot_identity()
    now = time.perf_counter_ns()
    if path.is_file():
        receipt = _load_canonical_sealed(
            path,
            schema=RUN_CLOCK_SCHEMA,
            hash_field="run_clock_hash",
            label="run monotonic clock",
        )
        started = receipt.get("started_monotonic_ns")
        if (
            receipt.get("boot_identity") != boot
            or receipt.get("clock") != "time.perf_counter_ns"
            or receipt.get("harness_binding_hash") != harness_binding_hash
            or receipt.get("overall_active_wall_limit_ns")
            != int(OVERALL_ACTIVE_WALL_SECONDS * 1_000_000_000)
            or receipt.get("terminal_write_reserve_ns") != TERMINAL_WRITE_RESERVE_NS
            or isinstance(started, bool)
            or not isinstance(started, int)
            or started < 0
            or now < started
        ):
            raise EvaluationError("Stage 09 run monotonic clock identity changed")
        return cast(dict[str, object], receipt)
    payload = {
        "schema": RUN_CLOCK_SCHEMA,
        "boot_identity": boot,
        "clock": "time.perf_counter_ns",
        "harness_binding_hash": harness_binding_hash,
        "overall_active_wall_limit_ns": int(OVERALL_ACTIVE_WALL_SECONDS * 1_000_000_000),
        "started_monotonic_ns": now,
        "terminal_write_reserve_ns": TERMINAL_WRITE_RESERVE_NS,
    }
    receipt = cast(dict[str, object], seal_object(payload, hash_field="run_clock_hash"))
    _atomic_create(path, canonical_json_bytes(receipt))
    return receipt


def _attach_run_clock(
    check: Mapping[str, object], *, work_root: Path, harness_binding_hash: object
) -> dict[str, object]:
    clock = _run_clock(work_root, harness_binding_hash=harness_binding_hash)
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


def _run_elapsed_ns(check: Mapping[str, object]) -> int:
    clock, _path = _clock_from_check(check)
    if clock.get("boot_identity") != _boot_identity():
        raise EvaluationError("Stage 09 run clock crossed a boot boundary")
    started = clock.get("started_monotonic_ns")
    if isinstance(started, bool) or not isinstance(started, int):
        raise EvaluationError("Stage 09 run clock start is invalid")
    elapsed = time.perf_counter_ns() - started
    if elapsed < 0:
        raise EvaluationError("Stage 09 run monotonic clock moved backwards")
    return elapsed


def _bind_terminal_clock(
    value: Mapping[str, object],
    *,
    check: Mapping[str, object],
    elapsed_before_output_ns: int,
) -> dict[str, object]:
    if (
        isinstance(elapsed_before_output_ns, bool)
        or not isinstance(elapsed_before_output_ns, int)
        or elapsed_before_output_ns < 0
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
        "clock": "time.perf_counter_ns",
        "elapsed_before_output_ns": elapsed_before_output_ns,
        "overall_active_wall_limit_ns": limit,
        "terminal_write_reserve_ns": TERMINAL_WRITE_RESERVE_NS,
        "within_prewrite_reserve": elapsed_before_output_ns <= limit - TERMINAL_WRITE_RESERVE_NS,
    }
    return cast(dict[str, object], seal_object(payload, hash_field="artifact_core_hash"))


def _terminal_finalization_path(output: Path) -> Path:
    return Path(f"{output.resolve()}.finalization.json")


def _terminal_finalization_payload(
    *,
    output: Path,
    terminal: Mapping[str, object],
    check: Mapping[str, object],
    elapsed_after_output_ns: int,
) -> dict[str, object]:
    wall = terminal.get("run_active_wall")
    if not isinstance(wall, dict):
        raise EvaluationError("Stage 09 terminal pre-write wall is absent")
    before = wall.get("elapsed_before_output_ns")
    if (
        isinstance(elapsed_after_output_ns, bool)
        or not isinstance(elapsed_after_output_ns, int)
        or not isinstance(before, int)
        or isinstance(before, bool)
        or elapsed_after_output_ns < before
    ):
        raise EvaluationError("Stage 09 terminal finalization wall is invalid")
    clock, clock_path = _clock_from_check(check)
    limit = int(OVERALL_ACTIVE_WALL_SECONDS * 1_000_000_000)
    payload = {
        "schema": TERMINAL_FINALIZATION_SCHEMA,
        "artifact_core_hash": terminal.get("artifact_core_hash"),
        "elapsed_after_durable_output_ns": elapsed_after_output_ns,
        "measurement_scope": "run-clock-start-through-durable-terminal-output",
        "output_path": output.resolve().as_posix(),
        "output_sha256": sha256_file(output),
        "overall_active_wall_limit_ns": limit,
        "run_clock_hash": clock.get("run_clock_hash"),
        "run_clock_sha256": sha256_file(clock_path),
        "within_overall_active_wall": elapsed_after_output_ns <= limit,
    }
    return cast(dict[str, object], seal_object(payload, hash_field="terminal_finalization_hash"))


def _write_terminal(
    output: Path, value: Mapping[str, object], *, check: Mapping[str, object]
) -> dict[str, object]:
    before = _run_elapsed_ns(check)
    terminal = _bind_terminal_clock(value, check=check, elapsed_before_output_ns=before)
    if (
        terminal.get("status") != "FAILED_INFRASTRUCTURE"
        and cast(dict[str, object], terminal["run_active_wall"]).get("within_prewrite_reserve")
        is not True
    ):
        raise EvaluationError("Stage 09 terminal cannot be admitted within its wall reserve")
    _atomic_create(output, canonical_json_bytes(terminal))
    after = _run_elapsed_ns(check)
    finalization = _terminal_finalization_payload(
        output=output,
        terminal=terminal,
        check=check,
        elapsed_after_output_ns=after,
    )
    _atomic_create(_terminal_finalization_path(output), canonical_json_bytes(finalization))
    if (
        terminal.get("status") != "FAILED_INFRASTRUCTURE"
        and finalization.get("within_overall_active_wall") is not True
    ):
        raise EvaluationError("Stage 09 terminal crossed the overall active-wall boundary")
    return terminal


def _validate_terminal_finalization(
    output: Path, terminal: Mapping[str, object], *, check: Mapping[str, object]
) -> dict[str, object]:
    path = _terminal_finalization_path(output)
    if not path.exists():
        recovery = _terminal_finalization_payload(
            output=output,
            terminal=terminal,
            check=check,
            elapsed_after_output_ns=_run_elapsed_ns(check),
        )
        _atomic_create(path, canonical_json_bytes(recovery))
    persisted = _load_canonical_sealed(
        path,
        schema=TERMINAL_FINALIZATION_SCHEMA,
        hash_field="terminal_finalization_hash",
        label="terminal finalization receipt",
    )
    elapsed = persisted.get("elapsed_after_durable_output_ns")
    if isinstance(elapsed, bool) or not isinstance(elapsed, int) or elapsed < 0:
        raise EvaluationError("Stage 09 terminal finalization elapsed wall changed")
    expected = _terminal_finalization_payload(
        output=output,
        terminal=terminal,
        check=check,
        elapsed_after_output_ns=elapsed,
    )
    if persisted != expected:
        raise EvaluationError("Stage 09 terminal finalization does not reconstruct exactly")
    if (
        terminal.get("status") != "FAILED_INFRASTRUCTURE"
        and persisted.get("within_overall_active_wall") is not True
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
        "launch": work_root.resolve() / "process-launches" / f"{prefix}.json",
        "orphan": work_root.resolve() / "orphan-terminations" / f"{prefix}.json",
        "parent_evidence": work_root.resolve() / "parent-evidence" / f"{prefix}.json",
        "finalization": work_root.resolve() / "cell-finalizations" / f"{prefix}.json",
        "raw": cell_root / "raw-worker-result.json",
        "receipt": work_root.resolve() / "parent-receipts" / f"{prefix}.json",
        "spec": work_root.resolve() / "specs" / f"{prefix}.json",
        "stderr": work_root.resolve() / "parent-streams" / prefix / "stderr.bin",
        "stdout": work_root.resolve() / "parent-streams" / prefix / "stdout.bin",
        "supervision": work_root.resolve() / "supervision-receipts" / f"{prefix}.json",
    }


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
        str(Path(sys.executable).resolve()),
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
    process: subprocess.Popen[bytes] | None = None
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
    except (EvaluationError, OSError) as error:
        launch_error = f"{type(error).__name__}: {error}"
        if process is not None and process.poll() is None:
            termination = _terminate_tree(process)
            try:
                tail_out, tail_err = process.communicate(timeout=10.0)
                stdout += tail_out
                stderr += tail_err
            except (OSError, subprocess.TimeoutExpired):
                pass
            returncode = process.returncode
    stdout_path = streams / "stdout.bin"
    stderr_path = streams / "stderr.bin"
    _atomic_create(stdout_path, stdout)
    _atomic_create(stderr_path, stderr)
    payload = {
        "schema": SUPERVISION_RECEIPT_SCHEMA,
        "authorization_hash": authorization_hash,
        "command": list(command),
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
        "measurement_scope": "cell-preparation-start-through-durable-cell-receipt",
        "measured_active_wall_ns": measured_active_wall_ns,
        "normal_termination_definition": NORMAL_TERMINATION_DEFINITION,
        "parent_evidence_hash": parent_evidence.get("parent_evidence_hash"),
        "parent_evidence_sha256": sha256_file(paths["parent_evidence"]),
        "within_admission_charge": measured_active_wall_ns <= CELL_ADMISSION_CHARGE_NS,
    }
    return cast(dict[str, object], seal_object(payload, hash_field="finalization_hash"))


def _reconstruct_cell_finalization(
    *,
    paths: Mapping[str, Path],
    cell: DevelopmentCell,
    receipt: Mapping[str, object],
    parent_evidence: Mapping[str, object],
) -> dict[str, object]:
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
            "error": None,
            "live_process_token_after": live_before,
            "live_process_token_before": live_before,
            "method": None,
            "passed": live_before != expected_token,
            "returncode": None,
            "target_token_matched": False,
        }
    method = "windows-taskkill-tree" if os.name == "nt" else "posix-killpg"
    error: str | None = None
    returncode: int | None = None
    try:
        if os.name == "nt":
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
    live_after = _process_creation_token(pid)
    return {
        "attempted": True,
        "error": error,
        "live_process_token_after": live_after,
        "live_process_token_before": live_before,
        "method": method,
        "passed": live_after != expected_token,
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
        "schema",
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
    if state == "pre-environment-handshake-aborted":
        if any(
            item is not None
            for item in (
                launch_hash,
                receipt.get("authorization_hash"),
                receipt.get("pid"),
                stored,
                before,
                after,
                termination,
            )
        ) or not all(
            isinstance(receipt.get(field), str)
            for field in ("abort_receipt_hash", "abort_receipt_sha256")
        ):
            raise EvaluationError("Stage 09 pre-environment orphan evidence changed")
    elif state == "not-running":
        if not isinstance(launch_hash, str) or before is not None or after is not None:
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
        ):
            raise EvaluationError("Stage 09 terminated orphan evidence changed")
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
        if not isinstance(launch_token, str) or not launch_token:
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
                or not abort.get("launch_token")
            ):
                raise EvaluationError("Stage 09 worker abort receipt changed")
            state = "pre-environment-handshake-aborted"
            passed = True
        else:
            raise EvaluationError(
                "Stage 09 exposed cell has neither a launch nor a sealed pre-environment abort"
            )
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
    payload = {
        "schema": ORPHAN_RECEIPT_SCHEMA,
        "cell_id": cell.cell_id,
        "cell_spec_hash": cell.spec_hash,
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
        "launch_token": launch.get("launch_token") if launch is not None else None,
        "pid": pid_value,
        "process_creation_token": stored_token,
        "live_process_token_before": live_token,
        "live_process_token_after": (
            termination.get("live_process_token_after") if termination is not None else live_token
        ),
        "passed": passed,
        "state": state,
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
        )
        if any(existing.get(field) != sealed.get(field) for field in static_fields):
            raise EvaluationError("Stage 09 orphan termination identity changed")
        if existing.get("passed") is not True or existing.get("state") not in {
            "not-running",
            "pid-reused-original-not-running",
            "pre-environment-handshake-aborted",
            "terminated",
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
) -> dict[str, object]:
    if len(receipts) != len(finalizations):
        raise EvaluationError("Stage 09 receipt/finalization prefix lengths differ")
    pre_receipt_wall_ns = 0
    measured_wall_ns = 0
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
        measured = finalization.get("measured_active_wall_ns")
        charge = finalization.get("admission_charge_ns")
        if (
            isinstance(measured, bool)
            or not isinstance(measured, int)
            or measured < parent
            or charge != CELL_ADMISSION_CHARGE_NS
            or finalization.get("budget_accounting") != "fixed-full-cell-admission-charge"
            or finalization.get("normal_termination_definition") != NORMAL_TERMINATION_DEFINITION
            or finalization.get("within_admission_charge")
            is not (measured <= CELL_ADMISSION_CHARGE_NS)
        ):
            raise EvaluationError("Stage 09 cell finalization timing changed")
        pre_receipt_wall_ns += parent
        measured_wall_ns += measured
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
        "cumulative_measured_active_wall_ns": measured_wall_ns,
        "cumulative_pre_receipt_active_wall_ns": pre_receipt_wall_ns,
        "cumulative_worker_supervision_wall_ns": supervision_wall_ns,
        "overall_active_wall_limit_ns": limit_ns,
        "runtime_end": _runtime_identity(),
        "runtime_start": dict(runtime_start),
        "wall_measurement_complete": execution_complete,
        "wall_within_limit": admission_charges_ns <= limit_ns,
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
        finalizations.append(
            _reconstruct_cell_finalization(
                paths=paths,
                cell=cell,
                receipt=receipt,
                parent_evidence=parent_evidence,
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
    prior_elapsed = prior_wall.get("elapsed_before_output_ns")
    if isinstance(prior_elapsed, bool) or not isinstance(prior_elapsed, int):
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
    finalizations = _load_finalization_prefix(work_root=work_root, receipts=receipts)
    if prior.get("cell_receipt_hashes") != [
        receipt.get("cell_receipt_hash") for receipt in receipts
    ]:
        raise EvaluationError("existing Stage 09 terminal receipt projection changed")
    if prior.get("cell_finalization_hashes") != [
        finalization.get("finalization_hash") for finalization in finalizations
    ]:
        raise EvaluationError("existing Stage 09 terminal finalization projection changed")
    execution_complete = prior.get("execution_complete")
    expected_resources = _resource_summary(
        receipts,
        finalizations,
        runtime_start=runtime_start,
        execution_complete=execution_complete is True,
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
            elapsed_before_output_ns=prior_elapsed,
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
        if count > 0 and finalizations[-1].get("within_admission_charge") is not True:
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
            if limit - used < CELL_ADMISSION_CHARGE_NS:
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
            elapsed_before_output_ns=prior_elapsed,
        )
        if prior != expected_terminal:
            raise EvaluationError("existing partial Stage 09 terminal does not reconstruct exactly")
    else:
        raise EvaluationError("existing Stage 09 terminal completion state is invalid")
    _validate_terminal_finalization(output, prior, check=embedded_preflight)
    return cast(dict[str, object], prior)


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
                work_root=work_root, receipts=existing_receipts
            )[-1]
            existing_finalizations.append(finalization)
            receipt_ends = _receipt_after_boundaries(receipt)
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
        cell_started_ns = time.perf_counter_ns()
        boundary_before = _observe_execution_boundaries(
            harness_source_expected=harness_source_expected,
            environments=environments,
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
        for path in (
            paths["abort"],
            paths["authorization"],
            paths["finalization"],
            paths["launch"],
            paths["parent_evidence"],
            paths["raw"],
            paths["receipt"],
            paths["stderr"],
            paths["stdout"],
            paths["supervision"],
        ):
            if path.exists():
                raise EvaluationError("unexposed Stage 09 cell already has execution evidence")
        event = _append_exposure(exposure, cell)
        raw_path = paths["raw"]
        streams = paths["stdout"].parent
        launch_token = uuid.uuid4().hex
        command = _worker_command(
            spec_path,
            raw_path,
            launch_path=paths["launch"],
            authorization_path=paths["authorization"],
            abort_path=paths["abort"],
            launch_token=launch_token,
        )
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
        finalization = _load_finalization_prefix(work_root=work_root, receipts=existing_receipts)[
            -1
        ]
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
    elapsed_before_terminal_ns = _run_elapsed_ns(check)
    overall_limit_ns = int(OVERALL_ACTIVE_WALL_SECONDS * 1_000_000_000)
    evidence_integrity = bool(
        source_stable
        and execution_boundaries["passed"] is True
        and asset_end["passed"] is True
        and len(exposures_end) == EXPECTED_CELL_COUNT
        and len(existing_finalizations) * CELL_ADMISSION_CHARGE_NS <= overall_limit_ns
        and elapsed_before_terminal_ns <= overall_limit_ns - TERMINAL_WRITE_RESERVE_NS
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
            "resources": _resource_summary(
                existing_receipts,
                existing_finalizations,
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
