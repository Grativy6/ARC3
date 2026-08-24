"""Acquire and verify the exact Linux wheelhouse, then prove an offline cold start.

The acquisition phase is intentionally separate from execution.  A Windows
host can download and hash-check Linux wheels, but it can never emit a Linux
cold-start ``PASS`` receipt.  The execution phase only runs on native CPython
3.12 Linux x86_64 and installs into a fresh virtual environment with pip's
index, dependency resolution, configuration, cache, and user site disabled.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import zipfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import BinaryIO, cast
from urllib.parse import unquote, urlparse
from urllib.request import Request, urlopen

from packaging.utils import canonicalize_name

from arc3.packaging.models import PackagingError
from arc3.packaging.requirements import (
    TARGET_ABI,
    TARGET_IMPLEMENTATION,
    TARGET_PIP_PLATFORMS,
    TARGET_PLATFORM,
    TARGET_PYTHON_VERSION,
    LockedWheel,
    verify_runtime_wheelhouse,
)
from arc3.packaging.util import canonical_json_bytes, sha256_bytes, sha256_file
from arc3.types import JSONValue

_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_ALLOWED_WHEEL_HOST = "files.pythonhosted.org"
_REQUIREMENTS_HEADER = (
    "# Generated from uv.lock; CPython 3.12 Linux x86_64 only.\n"
    "# Installation must also pass --no-index --no-deps --require-hashes.\n"
)
_DEFAULT_MAX_WHEEL_BYTES = 512 * 1024 * 1024
_DEFAULT_MAX_TOTAL_BYTES = 2 * 1024 * 1024 * 1024
_DEFAULT_MEMORY_LIMIT_BYTES = 2 * 1024 * 1024 * 1024
_DEFAULT_CPU_LIMIT_SECONDS = 240
_DEFAULT_WALL_TIMEOUT_SECONDS = 300.0
_MAX_PAYLOAD_UNCOMPRESSED_BYTES = 1024 * 1024 * 1024
_DISTRIBUTION_IMPORTS = {
    "annotated-types": "annotated_types",
    "arc-agi": "arc_agi",
    "arcengine": "arcengine",
    "blinker": "blinker",
    "certifi": "certifi",
    "charset-normalizer": "charset_normalizer",
    "click": "click",
    "contourpy": "contourpy",
    "cycler": "cycler",
    "flask": "flask",
    "fonttools": "fontTools",
    "idna": "idna",
    "itsdangerous": "itsdangerous",
    "jinja2": "jinja2",
    "kiwisolver": "kiwisolver",
    "markupsafe": "markupsafe",
    "matplotlib": "matplotlib",
    "numpy": "numpy",
    "packaging": "packaging",
    "pillow": "PIL",
    "pydantic": "pydantic",
    "pydantic-core": "pydantic_core",
    "pyparsing": "pyparsing",
    "python-dateutil": "dateutil",
    "python-dotenv": "dotenv",
    "requests": "requests",
    "six": "six",
    "typing-extensions": "typing_extensions",
    "typing-inspection": "typing_inspection",
    "urllib3": "urllib3",
    "werkzeug": "werkzeug",
}


@dataclass(frozen=True, slots=True)
class WheelhouseAcquisitionReceipt:
    """Receipt for the online, hash-verified acquisition phase."""

    manifest_sha256: str
    requirements_sha256: str
    package_count: int
    total_bytes: int
    max_wheel_bytes: int
    max_total_bytes: int
    source_host: str
    wheelhouse: str
    files: tuple[dict[str, JSONValue], ...]

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "files": list(self.files),
            "limits": {
                "max_total_bytes": self.max_total_bytes,
                "max_wheel_bytes": self.max_wheel_bytes,
            },
            "manifest_sha256": self.manifest_sha256,
            "package_count": self.package_count,
            "requirements_sha256": self.requirements_sha256,
            "schema": "arc3.linux-wheelhouse-acquisition.v0.1",
            "source_host": self.source_host,
            "status": "PASS",
            "target": TARGET_PLATFORM,
            "total_bytes": self.total_bytes,
            "wheelhouse": self.wheelhouse,
        }


@dataclass(frozen=True, slots=True)
class LinuxColdStartReceipt:
    """Native-host result for one exact no-index cold-start attempt."""

    status: str
    executed: bool
    validation_level: str
    observed_system: str
    observed_machine: str
    observed_implementation: str
    observed_python: str
    executable: str
    glibc: str
    package_manifest_sha256: str
    manifest_sha256: str
    requirements_sha256: str
    payload_sha256: str
    wheelhouse_package_count: int
    wall_seconds: float
    peak_memory_bytes: int | None
    memory_limit_bytes: int
    cpu_limit_seconds: int
    wall_timeout_seconds: float
    deterministic_repetitions: int
    stable_projection_sha256: str | None
    pip_version: str | None
    limitations: tuple[str, ...]

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "determinism": {
                "repetitions": self.deterministic_repetitions,
                "stable_projection_sha256": self.stable_projection_sha256,
            },
            "executed": self.executed,
            "host": {
                "executable": self.executable,
                "glibc": self.glibc,
                "implementation": self.observed_implementation,
                "machine": self.observed_machine,
                "python": self.observed_python,
                "system": self.observed_system,
            },
            "identities": {
                "manifest_sha256": self.manifest_sha256,
                "package_manifest_sha256": self.package_manifest_sha256,
                "payload_sha256": self.payload_sha256,
                "requirements_sha256": self.requirements_sha256,
            },
            "limitations": list(self.limitations),
            "limits": {
                "cpu_seconds": self.cpu_limit_seconds,
                "memory_bytes": self.memory_limit_bytes,
                "wall_seconds": self.wall_timeout_seconds,
            },
            "measurements": {
                "peak_memory_bytes": self.peak_memory_bytes,
                "wall_seconds": self.wall_seconds,
            },
            "pip": {
                "isolated": self.executed,
                "no_deps": self.executed,
                "no_index": self.executed,
                "require_hashes": self.executed,
                "version": self.pip_version,
            },
            "schema": "arc3.linux-cold-start.v0.1",
            "status": self.status,
            "target": TARGET_PLATFORM,
            "validation_level": self.validation_level,
            "wheelhouse_package_count": self.wheelhouse_package_count,
        }


def _json_object(path: Path, *, label: str) -> dict[str, JSONValue]:
    try:
        decoded: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise PackagingError(f"cannot read {label}: {error}") from error
    if not isinstance(decoded, dict):
        raise PackagingError(f"{label} must be a JSON object")
    return cast(dict[str, JSONValue], decoded)


def _validate_wheel_url(url: str, filename: str) -> None:
    parsed = urlparse(url)
    if (
        parsed.scheme != "https"
        or parsed.hostname != _ALLOWED_WHEEL_HOST
        or parsed.port is not None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or Path(unquote(parsed.path)).name != filename
    ):
        raise PackagingError(f"runtime wheel URL is outside the pinned PyPI file boundary: {url}")


def load_runtime_wheel_manifest(
    manifest_path: Path, requirements_path: Path
) -> tuple[LockedWheel, ...]:
    """Load a manifest only when its target, self-hash, and requirements agree."""

    manifest_path = manifest_path.resolve()
    requirements_path = requirements_path.resolve()
    manifest = _json_object(manifest_path, label="runtime wheel manifest")
    requirements = requirements_path.read_bytes()
    expected_target = {
        "abi": TARGET_ABI,
        "exact_wheelhouse_required": True,
        "implementation": TARGET_IMPLEMENTATION,
        "single_platform_simulation_supported": False,
        "platforms": list(TARGET_PIP_PLATFORMS),
        "python_version": TARGET_PYTHON_VERSION,
    }
    if (
        manifest.get("schema") != "arc3.runtime-wheel-manifest.v0.1"
        or manifest.get("target") != TARGET_PLATFORM
        or manifest.get("python") != "3.12"
        or manifest.get("pip_target") != expected_target
    ):
        raise PackagingError("runtime wheel manifest target or schema is not exact")
    if manifest.get("requirements_sha256") != sha256_bytes(requirements):
        raise PackagingError("runtime wheel manifest does not match its requirements")
    core = dict(manifest)
    recorded_core_hash = core.pop("manifest_core_sha256", None)
    core.pop("requirements_sha256", None)
    if recorded_core_hash != sha256_bytes(canonical_json_bytes(core)):
        raise PackagingError("runtime wheel manifest core hash does not verify")

    packages = manifest.get("packages")
    if not isinstance(packages, list) or not packages:
        raise PackagingError("runtime wheel manifest has no packages")
    wheels: list[LockedWheel] = []
    for raw in packages:
        if not isinstance(raw, dict):
            raise PackagingError("runtime wheel manifest package must be an object")
        name = raw.get("name")
        version = raw.get("version")
        filename = raw.get("filename")
        digest = raw.get("sha256")
        url = raw.get("url")
        if not all(
            isinstance(value, str) and value for value in (name, version, filename, digest, url)
        ):
            raise PackagingError("runtime wheel manifest package is incomplete")
        name = cast(str, name)
        version = cast(str, version)
        filename = cast(str, filename)
        digest = cast(str, digest)
        url = cast(str, url)
        if canonicalize_name(name) != name:
            raise PackagingError(f"runtime package name is not canonical: {name}")
        if PurePosixPath(filename).name != filename or not filename.endswith(".whl"):
            raise PackagingError(f"runtime wheel filename is unsafe: {filename}")
        if _SHA256.fullmatch(digest) is None:
            raise PackagingError(f"runtime wheel hash is malformed: {filename}")
        _validate_wheel_url(url, filename)
        wheels.append(LockedWheel(name, version, filename, digest, url))

    ordered = tuple(wheels)
    if tuple(wheel.name for wheel in ordered) != tuple(sorted(wheel.name for wheel in ordered)):
        raise PackagingError("runtime wheel manifest packages are not canonically ordered")
    if len({wheel.name for wheel in ordered}) != len(ordered):
        raise PackagingError("runtime wheel manifest repeats a package")
    if len({wheel.filename for wheel in ordered}) != len(ordered):
        raise PackagingError("runtime wheel manifest repeats a filename")
    expected_requirements = (
        _REQUIREMENTS_HEADER + "\n".join(wheel.requirement_line() for wheel in ordered) + "\n"
    ).encode("utf-8")
    if requirements != expected_requirements:
        raise PackagingError("runtime requirements do not exactly match the wheel manifest")
    return ordered


def _response_url(response: BinaryIO, fallback: str) -> str:
    getter = getattr(response, "geturl", None)
    value = getter() if callable(getter) else fallback
    if not isinstance(value, str):
        raise PackagingError("wheel download returned an invalid effective URL")
    return value


def _response_header(response: BinaryIO, name: str) -> str | None:
    headers = getattr(response, "headers", None)
    getter = getattr(headers, "get", None)
    value = getter(name) if callable(getter) else None
    return value if isinstance(value, str) else None


def acquire_runtime_wheelhouse(
    manifest_path: Path,
    requirements_path: Path,
    destination: Path,
    *,
    timeout_seconds: float = 60.0,
    max_wheel_bytes: int = _DEFAULT_MAX_WHEEL_BYTES,
    max_total_bytes: int = _DEFAULT_MAX_TOTAL_BYTES,
) -> WheelhouseAcquisitionReceipt:
    """Download only manifest URLs into a fresh, exact wheelhouse."""

    if timeout_seconds <= 0 or max_wheel_bytes <= 0 or max_total_bytes <= 0:
        raise PackagingError("wheelhouse acquisition limits must be positive")
    wheels = load_runtime_wheel_manifest(manifest_path, requirements_path)
    destination = destination.resolve()
    if destination.exists():
        raise PackagingError(f"wheelhouse destination must be fresh: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".arc3-wheelhouse-", dir=destination.parent))
    total_bytes = 0
    records: list[dict[str, JSONValue]] = []
    try:
        for wheel in wheels:
            request = Request(
                wheel.url,
                headers={"User-Agent": "ARC3-Build002-wheelhouse/1"},
                method="GET",
            )
            path = staging / wheel.filename
            digest = hashlib.sha256()
            size = 0
            with cast(BinaryIO, urlopen(request, timeout=timeout_seconds)) as response:
                effective_url = _response_url(response, wheel.url)
                _validate_wheel_url(effective_url, wheel.filename)
                raw_length = _response_header(response, "Content-Length")
                if raw_length is not None:
                    try:
                        content_length = int(raw_length)
                    except ValueError as error:
                        raise PackagingError(
                            f"wheel server returned invalid Content-Length for {wheel.filename}"
                        ) from error
                    if content_length < 0 or content_length > max_wheel_bytes:
                        raise PackagingError(f"wheel exceeds acquisition limit: {wheel.filename}")
                    if total_bytes + content_length > max_total_bytes:
                        raise PackagingError("wheelhouse exceeds aggregate acquisition limit")
                with path.open("xb") as output:
                    while chunk := response.read(1024 * 1024):
                        size += len(chunk)
                        total_bytes += len(chunk)
                        if size > max_wheel_bytes:
                            raise PackagingError(
                                f"wheel exceeds acquisition limit: {wheel.filename}"
                            )
                        if total_bytes > max_total_bytes:
                            raise PackagingError("wheelhouse exceeds aggregate acquisition limit")
                        digest.update(chunk)
                        output.write(chunk)
            actual = f"sha256:{digest.hexdigest()}"
            if actual != wheel.sha256:
                raise PackagingError(f"downloaded wheel hash mismatch: {wheel.filename}")
            records.append(
                {
                    "filename": wheel.filename,
                    "sha256": actual,
                    "size_bytes": size,
                    "url": wheel.url,
                }
            )
        verify_runtime_wheelhouse(wheels, staging)
        staging.rename(destination)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return WheelhouseAcquisitionReceipt(
        manifest_sha256=sha256_file(manifest_path),
        requirements_sha256=sha256_file(requirements_path),
        package_count=len(wheels),
        total_bytes=total_bytes,
        max_wheel_bytes=max_wheel_bytes,
        max_total_bytes=max_total_bytes,
        source_host=_ALLOWED_WHEEL_HOST,
        wheelhouse=str(destination),
        files=tuple(records),
    )


def _host_identity() -> tuple[str, str, str, str, str]:
    libc_name, libc_version = platform.libc_ver()
    glibc = f"{libc_name}-{libc_version}" if libc_name or libc_version else "unknown"
    return (
        platform.system(),
        platform.machine(),
        platform.python_implementation(),
        platform.python_version(),
        glibc,
    )


def _is_exact_linux_host(identity: tuple[str, str, str, str, str]) -> bool:
    system, machine, implementation, version, _glibc = identity
    try:
        major, minor, *_rest = (int(part) for part in version.split("."))
    except ValueError:
        return False
    return (
        system == "Linux"
        and machine.lower() in {"x86_64", "amd64"}
        and implementation == "CPython"
        and (major, minor) == (3, 12)
    )


def _safe_payload_names(archive: zipfile.ZipFile) -> tuple[str, ...]:
    names: list[str] = []
    total_size = 0
    for info in archive.infolist():
        name = info.orig_filename
        posix = PurePosixPath(name)
        windows = PureWindowsPath(name)
        if (
            not name
            or "\x00" in name
            or "\\" in name
            or info.is_dir()
            or posix.is_absolute()
            or windows.is_absolute()
            or bool(windows.drive)
            or any(part in {"", ".", ".."} for part in name.split("/"))
            or any(":" in part for part in name.split("/"))
        ):
            raise PackagingError(f"payload contains an unsafe member: {name!r}")
        mode = info.external_attr >> 16
        file_type = stat.S_IFMT(mode)
        if file_type not in {0, stat.S_IFREG} or (
            info.create_system == 0 and bool(info.external_attr & 0x400)
        ):
            raise PackagingError(f"payload contains a link or special member: {name!r}")
        total_size += info.file_size
        if info.file_size < 0 or total_size > _MAX_PAYLOAD_UNCOMPRESSED_BYTES:
            raise PackagingError("payload exceeds the cold-start extraction limit")
        names.append(name)
    if len(names) != len(set(names)):
        raise PackagingError("payload contains duplicate members")
    required = {"agent/my_agent.py", "src/arc3/__init__.py"}
    if not required.issubset(names):
        raise PackagingError("payload is missing the agent or arc3 package")
    return tuple(names)


def _validate_package_binding(
    package_manifest_path: Path,
    *,
    source_commit: str,
    payload_sha256: str,
    wheel_manifest_sha256: str,
    requirements_sha256: str,
) -> str:
    manifest = _json_object(package_manifest_path, label="package manifest")
    source = manifest.get("source")
    payload = manifest.get("payload")
    runtime_lock = manifest.get("runtime_lock")
    if (
        manifest.get("schema") != "arc3.kaggle-package-manifest.v0.1"
        or manifest.get("build_status") != "PACKAGING_PASS"
        or not isinstance(source, dict)
        or source.get("git_commit") != source_commit
        or source.get("git_dirty") is not False
        or not isinstance(payload, dict)
        or payload.get("sha256") != payload_sha256
        or not isinstance(runtime_lock, dict)
        or runtime_lock.get("wheel_manifest_sha256") != wheel_manifest_sha256
        or runtime_lock.get("requirements_sha256") != requirements_sha256
        or runtime_lock.get("target") != TARGET_PLATFORM
    ):
        raise PackagingError("package manifest does not bind the exact cold-start inputs")
    source_identity = payload.get("source_identity")
    if (
        not isinstance(source_identity, dict)
        or source_identity.get("exact_git_commit_bound") is not True
        or source_identity.get("git_commit") != source_commit
        or source_identity.get("mode") != "git-blob-exact"
    ):
        raise PackagingError("package payload is not bound to an exact clean Git commit")
    return sha256_file(package_manifest_path)


_PROBE_SOURCE = r"""from __future__ import annotations
import hashlib
import importlib
import importlib.metadata
import json
import os
import resource
import site
import socket
import sys
from pathlib import Path

payload_root = Path(sys.argv[1]).resolve()
working_root = Path(sys.argv[2]).resolve()
packages = json.loads(sys.argv[3])
memory_limit = int(sys.argv[4])
cpu_limit = int(sys.argv[5])
source_commit = sys.argv[6]
import_targets = json.loads(sys.argv[7])
resource.setrlimit(resource.RLIMIT_AS, (memory_limit, memory_limit))
resource.setrlimit(resource.RLIMIT_CPU, (cpu_limit, cpu_limit))
network_attempts = []
def guard(event, _args):
    if event.startswith("socket."):
        network_attempts.append(event)
        raise PermissionError("cold-start probe forbids network access")
sys.addaudithook(guard)

if sys.flags.isolated != 1 or site.ENABLE_USER_SITE is not False:
    raise RuntimeError("probe interpreter is not isolated from the user site")
if sys.prefix == sys.base_prefix:
    raise RuntimeError("probe interpreter is not running in a virtual environment")
site_roots = [Path(item).resolve() for item in site.getsitepackages()]
if not site_roots or any(not item.is_relative_to(Path(sys.prefix).resolve()) for item in site_roots):
    raise RuntimeError("probe site-packages escape the fresh virtual environment")

installed = {name: importlib.metadata.version(name) for name in sorted(packages)}
if installed != packages:
    raise RuntimeError("installed distribution versions differ from the wheel manifest")
sys.path.insert(0, str(payload_root / "src"))
sys.path.insert(0, str(payload_root))
os.environ["ARC3_EXECUTION_MODE"] = "COMPETITION_BOUNDED"
os.environ["ARC3_GIT_COMMIT"] = source_commit
os.environ["ARC3_MODE"] = "competition"
os.environ["ARC3_NETWORK_ENABLED"] = "false"
os.environ["ARC3_SEED"] = "0"
os.environ["ARC3_WORKING_DIR"] = str(working_root)
os.environ["MPLBACKEND"] = "Agg"
os.environ["MPLCONFIGDIR"] = str(working_root / "matplotlib")
if sorted(import_targets) != sorted(packages):
    raise RuntimeError("runtime distribution import map is incomplete")
imported_runtime = {}
for distribution in sorted(packages):
    module_name = import_targets[distribution]
    module = importlib.import_module(module_name)
    origin = getattr(module, "__file__", None)
    imported_runtime[distribution] = {
        "module": module_name,
        "origin": str(Path(origin).resolve()) if isinstance(origin, str) else None,
    }
arc3 = importlib.import_module("arc3")
arc_agi = importlib.import_module("arc_agi")
arcengine = importlib.import_module("arcengine")
wrapper = importlib.import_module("agent.my_agent")

def module_record(module):
    origin = Path(module.__file__).resolve()
    return {"origin": str(origin), "sha256": "sha256:" + hashlib.sha256(origin.read_bytes()).hexdigest()}
if not Path(arc3.__file__).resolve().is_relative_to(payload_root):
    raise RuntimeError("arc3 imported outside the packaged payload")
if not Path(wrapper.__file__).resolve().is_relative_to(payload_root):
    raise RuntimeError("MyAgent imported outside the packaged payload")
if not Path(arc_agi.__file__).resolve().is_relative_to(Path(sys.prefix).resolve()):
    raise RuntimeError("arc_agi imported outside the fresh environment")
if not Path(arcengine.__file__).resolve().is_relative_to(Path(sys.prefix).resolve()):
    raise RuntimeError("arcengine imported outside the fresh environment")

agent_type = wrapper.MyAgent
agent_type.configure_tournament(("cold-start-environment",), working_root)
agent = agent_type(game_id="cold-start-environment", agent_name="myagent", seed=0)
name = agent.name
final = agent_type.finalize_tournament()
if network_attempts:
    raise RuntimeError("cold-start probe attempted network access")
peak_bytes = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024
projection = {
    "agent_name": name,
    "arc3": module_record(arc3),
    "arc_agi": module_record(arc_agi),
    "arcengine": module_record(arcengine),
    "installed": installed,
    "imported_runtime": imported_runtime,
    "network_attempts": 0,
    "source_commit": source_commit,
    "source_runtime_config_sha256": wrapper.FROZEN_COMPETITION_RUNTIME.config_sha256,
    "tournament_finalized_environments": final.get("finalized_environments"),
    "tournament_outcome": final.get("outcome"),
    "tournament_total_actions": final.get("total_actions_authorized"),
}
print(json.dumps({"peak_memory_bytes": peak_bytes, "projection": projection}, allow_nan=False, separators=(",", ":"), sort_keys=True))
"""


def _extract_payload(payload_archive: Path, destination: Path) -> None:
    with zipfile.ZipFile(payload_archive) as archive:
        names = _safe_payload_names(archive)
        for name in names:
            target = destination / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.read(name))


def _minimal_subprocess_environment(working_root: Path) -> dict[str, str]:
    environment = {
        "HOME": str(working_root),
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "MKL_NUM_THREADS": "1",
        "NUMEXPR_NUM_THREADS": "1",
        "OMP_NUM_THREADS": "1",
        "OPENBLAS_NUM_THREADS": "1",
        "PATH": os.environ.get("PATH", ""),
        "PIP_CONFIG_FILE": os.devnull,
        "PIP_DISABLE_PIP_VERSION_CHECK": "1",
        "PIP_NO_CACHE_DIR": "1",
        "PIP_NO_INDEX": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONHASHSEED": "0",
        "PYTHONNOUSERSITE": "1",
        "TMPDIR": str(working_root / "tmp"),
    }
    return environment


def _run_checked(
    command: Sequence[str],
    *,
    environment: Mapping[str, str],
    timeout_seconds: float,
    label: str,
) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        list(command),
        check=False,
        capture_output=True,
        env=dict(environment),
        text=True,
        timeout=timeout_seconds,
    )
    if completed.returncode != 0:
        stderr_digest = sha256_bytes(completed.stderr.encode("utf-8", errors="replace"))
        stdout_digest = sha256_bytes(completed.stdout.encode("utf-8", errors="replace"))
        # The child receives a deliberately minimal environment with no repository or
        # CI credentials.  Preserve a bounded tail so Linux-only import failures can
        # be repaired from a receipt instead of reducing the evidence to a hash.
        stderr_tail = completed.stderr[-4096:].replace("\x00", "\\0")
        raise PackagingError(
            f"{label} failed with exit {completed.returncode}; "
            f"stdout_sha256={stdout_digest}; stderr_sha256={stderr_digest}; "
            f"stderr_tail={stderr_tail!r}"
        )
    return completed


def run_linux_cold_start(
    manifest_path: Path,
    requirements_path: Path,
    wheelhouse: Path,
    payload_archive: Path,
    package_manifest_path: Path,
    *,
    source_commit: str,
    wall_timeout_seconds: float = _DEFAULT_WALL_TIMEOUT_SECONDS,
    memory_limit_bytes: int = _DEFAULT_MEMORY_LIMIT_BYTES,
    cpu_limit_seconds: int = _DEFAULT_CPU_LIMIT_SECONDS,
    deterministic_repetitions: int = 2,
) -> LinuxColdStartReceipt:
    """Install and start twice in one fresh native-Linux CPython 3.12 venv."""

    if _COMMIT.fullmatch(source_commit) is None:
        raise PackagingError("cold-start source commit must be a full lowercase Git SHA")
    if (
        wall_timeout_seconds <= 0
        or memory_limit_bytes <= 0
        or cpu_limit_seconds <= 0
        or deterministic_repetitions < 2
    ):
        raise PackagingError("cold-start limits and repetitions are invalid")
    wheels = load_runtime_wheel_manifest(manifest_path, requirements_path)
    missing_import_targets = sorted(
        wheel.name for wheel in wheels if wheel.name not in _DISTRIBUTION_IMPORTS
    )
    if missing_import_targets:
        raise PackagingError(
            "runtime distributions lack explicit cold-start import targets: "
            + ", ".join(missing_import_targets)
        )
    verification = verify_runtime_wheelhouse(wheels, wheelhouse.resolve())
    package_count = verification.get("package_count")
    if not isinstance(package_count, int):
        raise PackagingError("wheelhouse verification omitted its package count")
    payload_archive = payload_archive.resolve()
    try:
        with zipfile.ZipFile(payload_archive) as archive:
            _safe_payload_names(archive)
    except (OSError, zipfile.BadZipFile) as error:
        raise PackagingError(f"cannot validate first-party payload: {error}") from error
    manifest_sha256 = sha256_file(manifest_path)
    requirements_sha256 = sha256_file(requirements_path)
    payload_sha256 = sha256_file(payload_archive)
    package_manifest_sha256 = _validate_package_binding(
        package_manifest_path.resolve(),
        source_commit=source_commit,
        payload_sha256=payload_sha256,
        wheel_manifest_sha256=manifest_sha256,
        requirements_sha256=requirements_sha256,
    )
    system, machine, implementation, version, glibc = _host_identity()
    if not _is_exact_linux_host((system, machine, implementation, version, glibc)):
        return LinuxColdStartReceipt(
            status="BLOCKED_PLATFORM",
            executed=False,
            validation_level="wheelhouse-hash-only; native Linux cold start not executed",
            observed_system=system,
            observed_machine=machine,
            observed_implementation=implementation,
            observed_python=version,
            executable=sys.executable,
            glibc=glibc,
            package_manifest_sha256=package_manifest_sha256,
            manifest_sha256=manifest_sha256,
            requirements_sha256=requirements_sha256,
            payload_sha256=payload_sha256,
            wheelhouse_package_count=package_count,
            wall_seconds=0.0,
            peak_memory_bytes=None,
            memory_limit_bytes=memory_limit_bytes,
            cpu_limit_seconds=cpu_limit_seconds,
            wall_timeout_seconds=wall_timeout_seconds,
            deterministic_repetitions=0,
            stable_projection_sha256=None,
            pip_version=None,
            limitations=(
                "Native CPython 3.12 Linux x86_64 execution is required for PASS.",
                "This host performed no cross-platform simulation and makes no Linux startup claim.",
            ),
        )

    started = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix="arc3-linux-cold-start-") as temporary:
        root = Path(temporary).resolve()
        venv = root / "venv"
        payload_root = root / "payload"
        payload_root.mkdir()
        (root / "tmp").mkdir()
        environment = _minimal_subprocess_environment(root)
        _run_checked(
            [sys.executable, "-I", "-E", "-s", "-m", "venv", str(venv)],
            environment=environment,
            timeout_seconds=wall_timeout_seconds,
            label="isolated virtual-environment creation",
        )
        python = venv / "bin" / "python"
        if not python.is_file():
            raise PackagingError("fresh Linux virtual environment has no bin/python")
        pip_version_process = _run_checked(
            [str(python), "-I", "-E", "-s", "-m", "pip", "--version"],
            environment=environment,
            timeout_seconds=wall_timeout_seconds,
            label="isolated pip inspection",
        )
        pip_version = pip_version_process.stdout.strip()
        install_command = [
            str(python),
            "-I",
            "-E",
            "-s",
            "-m",
            "pip",
            "--isolated",
            "install",
            "--disable-pip-version-check",
            "--no-cache-dir",
            "--no-index",
            "--no-deps",
            "--require-hashes",
            "--only-binary=:all:",
            "--no-compile",
            "--find-links",
            str(wheelhouse.resolve()),
            "-r",
            str(requirements_path.resolve()),
        ]
        _run_checked(
            install_command,
            environment=environment,
            timeout_seconds=wall_timeout_seconds,
            label="offline no-index dependency installation",
        )
        _extract_payload(payload_archive, payload_root)
        expected_packages = json.dumps(
            {wheel.name: wheel.version for wheel in wheels},
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        projections: list[dict[str, JSONValue]] = []
        peaks: list[int] = []
        for ordinal in range(deterministic_repetitions):
            run_root = root / f"run-{ordinal}"
            run_root.mkdir()
            completed = _run_checked(
                [
                    str(python),
                    "-I",
                    "-E",
                    "-s",
                    "-c",
                    _PROBE_SOURCE,
                    str(payload_root),
                    str(run_root),
                    expected_packages,
                    str(memory_limit_bytes),
                    str(cpu_limit_seconds),
                    source_commit,
                    json.dumps(_DISTRIBUTION_IMPORTS, separators=(",", ":"), sort_keys=True),
                ],
                environment=environment,
                timeout_seconds=wall_timeout_seconds,
                label=f"isolated startup probe {ordinal + 1}",
            )
            try:
                result: object = json.loads(completed.stdout)
            except json.JSONDecodeError as error:
                raise PackagingError("cold-start probe did not return JSON") from error
            if not isinstance(result, dict):
                raise PackagingError("cold-start probe receipt is not an object")
            projection = result.get("projection")
            peak = result.get("peak_memory_bytes")
            if not isinstance(projection, dict) or not isinstance(peak, int) or peak <= 0:
                raise PackagingError("cold-start probe receipt is incomplete")
            projections.append(cast(dict[str, JSONValue], projection))
            peaks.append(peak)
        projection_bytes = tuple(canonical_json_bytes(item) for item in projections)
        if len(set(projection_bytes)) != 1:
            raise PackagingError("cold-start stable projection changed between repetitions")
        stable_projection_sha256 = sha256_bytes(projection_bytes[0])

    return LinuxColdStartReceipt(
        status="PASS",
        executed=True,
        validation_level="native-linux-cp312-no-index-cold-start",
        observed_system=system,
        observed_machine=machine,
        observed_implementation=implementation,
        observed_python=version,
        executable=sys.executable,
        glibc=glibc,
        package_manifest_sha256=package_manifest_sha256,
        manifest_sha256=manifest_sha256,
        requirements_sha256=requirements_sha256,
        payload_sha256=payload_sha256,
        wheelhouse_package_count=package_count,
        wall_seconds=time.perf_counter() - started,
        peak_memory_bytes=max(peaks),
        memory_limit_bytes=memory_limit_bytes,
        cpu_limit_seconds=cpu_limit_seconds,
        wall_timeout_seconds=wall_timeout_seconds,
        deterministic_repetitions=deterministic_repetitions,
        stable_projection_sha256=stable_projection_sha256,
        pip_version=pip_version,
        limitations=(
            "Python audit hooks observe Python socket operations, not arbitrary native syscalls.",
            "This receipt validates local-public packaging compatibility, not Kaggle execution.",
        ),
    )


__all__ = [
    "LinuxColdStartReceipt",
    "WheelhouseAcquisitionReceipt",
    "acquire_runtime_wheelhouse",
    "load_runtime_wheel_manifest",
    "run_linux_cold_start",
]
