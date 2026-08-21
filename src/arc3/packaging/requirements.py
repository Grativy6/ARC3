"""Exact CPython 3.12 Linux runtime requirement identities from ``uv.lock``."""

from __future__ import annotations

import tomllib
from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlparse

from packaging.markers import Marker
from packaging.tags import Tag, compatible_tags, cpython_tags
from packaging.utils import InvalidWheelFilename, canonicalize_name, parse_wheel_filename

from arc3.packaging.models import PackagingError
from arc3.packaging.util import canonical_json_bytes, sha256_bytes, sha256_file
from arc3.types import JSONValue

TARGET_PLATFORM = "CPython 3.12 / Linux x86_64 / manylinux_2_28"
TARGET_PYTHON_VERSION = "312"
TARGET_IMPLEMENTATION = "cp"
TARGET_ABI = "cp312"


def _manylinux_platform_compatibility() -> tuple[str, ...]:
    """Return the PEP 600 compatibility ladder exposed by glibc 2.28.

    ``pip --platform`` treats each supplied platform literally.  A real
    manylinux_2_28 interpreter also accepts older glibc baselines, so a
    cross-platform wheelhouse build must pass the complete ordered ladder.
    The legacy aliases appear immediately after their PEP 600 equivalents,
    matching ``packaging.tags`` on a native x86_64 interpreter.
    """

    platforms: list[str] = []
    aliases = {17: "manylinux2014_x86_64", 12: "manylinux2010_x86_64", 5: "manylinux1_x86_64"}
    for minor in range(28, 4, -1):
        platforms.append(f"manylinux_2_{minor}_x86_64")
        alias = aliases.get(minor)
        if alias is not None:
            platforms.append(alias)
    return tuple(platforms)


TARGET_PIP_PLATFORMS = _manylinux_platform_compatibility()


def pip_target_arguments() -> tuple[str, ...]:
    """Return exact repeatable pip arguments for the declared Linux target."""

    arguments = [
        "--python-version",
        TARGET_PYTHON_VERSION,
        "--implementation",
        TARGET_IMPLEMENTATION,
        "--abi",
        TARGET_ABI,
    ]
    for platform in TARGET_PIP_PLATFORMS:
        arguments.extend(("--platform", platform))
    return tuple(arguments)


def _supported_tags() -> tuple[Tag, ...]:
    python_version = (3, 12)
    return (
        *cpython_tags(
            python_version,
            abis=(TARGET_ABI,),
            platforms=TARGET_PIP_PLATFORMS,
        ),
        *compatible_tags(
            python_version,
            interpreter=f"{TARGET_IMPLEMENTATION}{TARGET_PYTHON_VERSION}",
            platforms=TARGET_PIP_PLATFORMS,
        ),
    )


_TARGET_TAG_RANK = {tag: rank for rank, tag in enumerate(_supported_tags())}

_MARKER_ENVIRONMENT = {
    "implementation_name": "cpython",
    "implementation_version": "3.12.0",
    "os_name": "posix",
    "platform_machine": "x86_64",
    "platform_python_implementation": "CPython",
    "platform_release": "",
    "platform_system": "Linux",
    "platform_version": "",
    "python_full_version": "3.12.0",
    "python_version": "3.12",
    "sys_platform": "linux",
    "extra": "",
}


@dataclass(frozen=True, slots=True)
class LockedWheel:
    """One exact wheel selected for the declared competition platform."""

    name: str
    version: str
    filename: str
    sha256: str
    url: str

    def requirement_line(self) -> str:
        return f"{self.name}=={self.version} --hash={self.sha256}"

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "filename": self.filename,
            "name": self.name,
            "sha256": self.sha256,
            "url": self.url,
            "version": self.version,
        }


def _dependency_names(package: Mapping[str, Any]) -> tuple[str, ...]:
    raw_dependencies = package.get("dependencies", [])
    if not isinstance(raw_dependencies, list):
        raise PackagingError("uv.lock package dependencies must be an array")
    names: list[str] = []
    for raw in raw_dependencies:
        if not isinstance(raw, Mapping):
            raise PackagingError("uv.lock dependency entry must be an object")
        name = raw.get("name")
        marker = raw.get("marker")
        if not isinstance(name, str):
            raise PackagingError("uv.lock dependency entry is missing a name")
        if marker is not None:
            if not isinstance(marker, str):
                raise PackagingError("uv.lock dependency marker must be a string")
            try:
                included = Marker(marker).evaluate(environment=_MARKER_ENVIRONMENT)
            except Exception as error:
                raise PackagingError(
                    f"cannot evaluate uv.lock marker {marker!r}: {error}"
                ) from error
            if not included:
                continue
        names.append(canonicalize_name(name))
    return tuple(sorted(set(names)))


def _runtime_closure(packages: Mapping[str, Mapping[str, Any]]) -> tuple[str, ...]:
    pending: deque[str] = deque(("arc3", "arc-agi"))
    selected: set[str] = set()
    while pending:
        name = canonicalize_name(pending.popleft())
        if name in selected:
            continue
        package = packages.get(name)
        if package is None:
            raise PackagingError(f"uv.lock has no required runtime package {name!r}")
        selected.add(name)
        pending.extend(_dependency_names(package))
    return tuple(sorted(selected))


def _wheel_rank(filename: str) -> int | None:
    try:
        _, _, _, wheel_tags = parse_wheel_filename(filename)
    except InvalidWheelFilename:
        return None
    ranks = [_TARGET_TAG_RANK[tag] for tag in wheel_tags if tag in _TARGET_TAG_RANK]
    return min(ranks) if ranks else None


def _select_wheel(package: Mapping[str, Any]) -> tuple[str, str, str]:
    raw_wheels = package.get("wheels")
    if not isinstance(raw_wheels, list):
        raise PackagingError("runtime package has no locked wheel array")
    candidates: list[tuple[int, str, str, str]] = []
    for raw in raw_wheels:
        if not isinstance(raw, Mapping):
            raise PackagingError("uv.lock wheel record must be an object")
        url = raw.get("url")
        digest = raw.get("hash")
        if not isinstance(url, str) or not isinstance(digest, str):
            raise PackagingError("uv.lock wheel record is incomplete")
        filename = Path(urlparse(url).path).name
        rank = _wheel_rank(filename)
        if rank is not None and digest.startswith("sha256:"):
            candidates.append((rank, filename, digest, url))
    if not candidates:
        raise PackagingError(f"no compatible locked wheel for {TARGET_PLATFORM}")
    _, filename, digest, url = min(candidates, key=lambda candidate: candidate[:2])
    return filename, digest, url


def build_linux_runtime_requirements(
    lock_path: Path,
) -> tuple[bytes, dict[str, JSONValue], tuple[LockedWheel, ...]]:
    """Return a hash-locked requirements file and its platform wheel manifest."""

    try:
        parsed = tomllib.loads(lock_path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise PackagingError(f"cannot parse uv.lock: {error}") from error
    raw_packages = parsed.get("package")
    if not isinstance(raw_packages, list):
        raise PackagingError("uv.lock has no package array")
    by_name: dict[str, Mapping[str, Any]] = {}
    for raw in raw_packages:
        if not isinstance(raw, Mapping):
            raise PackagingError("uv.lock package entry must be an object")
        package = cast(Mapping[str, Any], raw)
        raw_name = package.get("name")
        if not isinstance(raw_name, str):
            raise PackagingError("uv.lock package entry is missing its name")
        by_name[canonicalize_name(raw_name)] = package

    wheels: list[LockedWheel] = []
    for name in _runtime_closure(by_name):
        if name == "arc3":
            continue
        package = by_name[name]
        version = package.get("version")
        if not isinstance(version, str):
            raise PackagingError(f"runtime package {name!r} has no exact version")
        filename, digest, url = _select_wheel(package)
        wheels.append(LockedWheel(name, version, filename, digest, url))

    ordered = tuple(sorted(wheels, key=lambda wheel: wheel.name))
    requirements = (
        "# Generated from uv.lock; CPython 3.12 Linux x86_64 only.\n"
        "# Installation must also pass --no-index --no-deps --require-hashes.\n"
        + "\n".join(wheel.requirement_line() for wheel in ordered)
        + "\n"
    ).encode("utf-8")
    manifest_core: dict[str, JSONValue] = {
        "packages": [wheel.to_dict() for wheel in ordered],
        "pip_target": {
            "abi": TARGET_ABI,
            "exact_wheelhouse_required": True,
            "implementation": TARGET_IMPLEMENTATION,
            "single_platform_simulation_supported": False,
            "platforms": list(TARGET_PIP_PLATFORMS),
            "python_version": TARGET_PYTHON_VERSION,
        },
        "python": "3.12",
        "schema": "arc3.runtime-wheel-manifest.v0.1",
        "target": TARGET_PLATFORM,
        "uv_lock_sha256": sha256_bytes(lock_path.read_bytes()),
    }
    manifest = dict(manifest_core)
    manifest["requirements_sha256"] = sha256_bytes(requirements)
    manifest["manifest_core_sha256"] = sha256_bytes(canonical_json_bytes(manifest_core))
    return requirements, manifest, ordered


def verify_runtime_wheelhouse(
    wheels: tuple[LockedWheel, ...], wheelhouse: Path
) -> dict[str, JSONValue]:
    """Verify an exact one-wheel-per-distribution offline wheelhouse.

    Rejecting extras matters: pip may prefer an unrecorded wheel carrying a
    different hash (for example FontTools' universal wheel when an incomplete
    single-platform cross-target is used).
    """

    if not wheelhouse.is_dir():
        raise PackagingError(f"runtime wheelhouse does not exist: {wheelhouse}")
    expected = {wheel.filename: wheel for wheel in wheels}
    if len(expected) != len(wheels):
        raise PackagingError("runtime wheel selection contains duplicate filenames")
    actual = {path.name: path for path in wheelhouse.glob("*.whl") if path.is_file()}
    if actual.keys() != expected.keys():
        missing = sorted(expected.keys() - actual.keys())
        unexpected = sorted(actual.keys() - expected.keys())
        raise PackagingError(
            f"runtime wheelhouse inventory mismatch: missing={missing!r}; unexpected={unexpected!r}"
        )
    records: list[JSONValue] = []
    for filename, wheel in sorted(expected.items()):
        path = actual[filename]
        actual_sha256 = sha256_file(path)
        if actual_sha256 != wheel.sha256:
            raise PackagingError(f"runtime wheel hash mismatch for {filename}")
        records.append(
            {
                "filename": filename,
                "sha256": actual_sha256,
                "size_bytes": path.stat().st_size,
            }
        )
    return {
        "files": records,
        "package_count": len(records),
        "schema": "arc3.runtime-wheelhouse-verification.v0.1",
        "status": "PASS",
    }


__all__ = [
    "TARGET_ABI",
    "TARGET_IMPLEMENTATION",
    "TARGET_PIP_PLATFORMS",
    "TARGET_PLATFORM",
    "TARGET_PYTHON_VERSION",
    "LockedWheel",
    "build_linux_runtime_requirements",
    "pip_target_arguments",
    "verify_runtime_wheelhouse",
]
