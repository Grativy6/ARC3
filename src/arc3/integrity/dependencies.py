"""Offline-only dependency and license metadata inventory."""

from __future__ import annotations

import hashlib
import importlib.metadata
import os
import platform
import re
import sys
import tomllib
from collections.abc import Mapping
from pathlib import Path
from typing import Any, cast

from arc3.integrity.hashes import canonical_json_bytes, sha256_bytes
from arc3.integrity.models import DependencyRecord
from arc3.licensing import first_party_license_identity, first_party_license_identity_bytes
from arc3.types import JSONValue

_SIMPLE_PLATFORM_MARKER = re.compile(
    r"^\s*(sys_platform|os_name|platform_system)\s*(==|!=)\s*(['\"])([^'\"]+)\3\s*$"
)


def _source_kind(value: object) -> str:
    if not isinstance(value, dict):
        return "unknown"
    source = cast(dict[str, object], value)
    for candidate in ("editable", "registry", "git", "url", "virtual"):
        if candidate in source:
            return candidate
    return "unknown"


def _simple_platform_marker_is_false(marker: str) -> bool | None:
    """Evaluate one conservative, platform-only PEP 508 marker.

    Unknown or compound marker syntax returns ``None`` so callers cannot use an
    incomplete parser to excuse a dependency that may apply to this runtime.
    """

    match = _SIMPLE_PLATFORM_MARKER.fullmatch(marker)
    if match is None:
        return None
    variable, operator, _, expected = match.groups()
    actual = {
        "os_name": os.name,
        "platform_system": platform.system(),
        "sys_platform": sys.platform,
    }[variable]
    applies = actual == expected if operator == "==" else actual != expected
    return not applies


def _platform_excluded_names(document: Mapping[str, Any]) -> frozenset[str]:
    """Return locked names referenced only by provably false platform edges."""

    raw_packages = document.get("package")
    if not isinstance(raw_packages, list):
        return frozenset()
    incoming: dict[str, list[str | None]] = {}
    for raw_package in raw_packages:
        if not isinstance(raw_package, Mapping):
            continue
        dependency_groups: list[object] = [raw_package.get("dependencies", [])]
        for group_name in ("optional-dependencies", "dev-dependencies"):
            raw_groups = raw_package.get(group_name)
            if isinstance(raw_groups, Mapping):
                dependency_groups.extend(raw_groups.values())
        for raw_group in dependency_groups:
            if not isinstance(raw_group, list):
                continue
            for raw_dependency in raw_group:
                if not isinstance(raw_dependency, Mapping):
                    continue
                name = raw_dependency.get("name")
                marker = raw_dependency.get("marker")
                if isinstance(name, str):
                    incoming.setdefault(name, []).append(
                        marker if isinstance(marker, str) else None
                    )
    return frozenset(
        name
        for name, markers in incoming.items()
        if markers
        and all(
            marker is not None and _simple_platform_marker_is_false(marker) is True
            for marker in markers
        )
    )


def _compact_license(value: str) -> tuple[str, str]:
    normalized = " ".join(value.split())
    if len(normalized) <= 160:
        return normalized, "DECLARED"
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()
    return f"license-text-sha256:{digest}", "HASHED_TEXT"


def _installed_metadata(name: str) -> tuple[str | None, str, tuple[str, ...], str | None]:
    try:
        distribution = importlib.metadata.distribution(name)
    except importlib.metadata.PackageNotFoundError:
        return None, "MISSING_DISTRIBUTION", (), None

    metadata = distribution.metadata
    evidence: list[str] = []
    status = "UNKNOWN"
    expression = metadata.get("License-Expression")
    if expression and expression.strip() and expression.strip().upper() != "UNKNOWN":
        evidence.append(f"expression:{expression.strip()}")
        status = "DECLARED"

    declared = metadata.get("License")
    if declared and declared.strip() and declared.strip().upper() != "UNKNOWN":
        compact, declared_status = _compact_license(declared)
        evidence.append(f"license:{compact}")
        if status == "UNKNOWN":
            status = declared_status

    classifiers = sorted(
        item.strip() for item in metadata.get_all("Classifier", []) if item.startswith("License ::")
    )
    if classifiers:
        evidence.extend(f"classifier:{item}" for item in classifiers)
        if status == "UNKNOWN":
            status = "CLASSIFIER"

    metadata_body: dict[str, JSONValue] = {
        "license_evidence": cast(list[JSONValue], evidence),
        "name": metadata.get("Name", name),
        "version": distribution.version,
    }
    return (
        distribution.version,
        status,
        tuple(evidence),
        sha256_bytes(canonical_json_bytes(metadata_body)),
    )


def inventory_locked_dependencies(
    lock_path: Path,
    *,
    include_installed_metadata: bool = True,
    lock_snapshot: bytes | None = None,
    first_party_source_snapshots: Mapping[str, bytes] | None = None,
) -> tuple[DependencyRecord, ...]:
    """Read ``uv.lock`` and enrich entries from local wheel metadata only.

    This function never invokes a package index, installer, or network client.
    """

    lock_text = (
        lock_path.read_text(encoding="utf-8")
        if lock_snapshot is None
        else lock_snapshot.decode("utf-8")
    )
    document = tomllib.loads(lock_text)
    raw_packages = document.get("package")
    if not isinstance(raw_packages, list):
        raise ValueError("uv lock has no package array")

    platform_excluded = _platform_excluded_names(document)
    records: list[DependencyRecord] = []
    for raw_package in raw_packages:
        if not isinstance(raw_package, Mapping):
            raise ValueError("uv lock package entry must be an object")
        package = cast(Mapping[str, Any], raw_package)
        name = package.get("name")
        version = package.get("version")
        if not isinstance(name, str) or not isinstance(version, str):
            raise ValueError("uv lock package entry must have string name and version")
        if name == "arc3":
            if first_party_source_snapshots is None:
                license_status, license_evidence = first_party_license_identity(lock_path.parent)
            else:
                try:
                    license_status, license_evidence = first_party_license_identity_bytes(
                        first_party_source_snapshots["LICENSE"],
                        first_party_source_snapshots["pyproject.toml"],
                    )
                except KeyError as error:
                    raise ValueError(
                        "first-party license snapshot projection is incomplete"
                    ) from error
            records.append(
                DependencyRecord(
                    name=name,
                    locked_version=version,
                    source_kind=_source_kind(package.get("source")),
                    installed_version=version,
                    license_status=license_status,
                    license_evidence=license_evidence,
                    metadata_sha256=None,
                )
            )
            continue
        if include_installed_metadata:
            installed, status, evidence, metadata_hash = _installed_metadata(name)
            if installed is None and name in platform_excluded:
                status = "PLATFORM_EXCLUDED"
        else:
            installed, status, evidence, metadata_hash = None, "NOT_QUERIED", (), None
        records.append(
            DependencyRecord(
                name=name,
                locked_version=version,
                source_kind=_source_kind(package.get("source")),
                installed_version=installed,
                license_status=status,
                license_evidence=evidence,
                metadata_sha256=metadata_hash,
            )
        )
    return tuple(sorted(records))


__all__ = ["inventory_locked_dependencies"]
