"""Independent verifier for a finished Stage 17 candidate archive."""

from __future__ import annotations

import io
import json
import re
import stat
import tomllib
import zipfile
from collections.abc import Mapping
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import cast
from urllib.parse import unquote, urlparse

from arc3.licensing import MIT0_LICENSE_SHA256
from arc3.packaging.models import PYTHON_NETWORK_ENFORCEMENT, PackagingError
from arc3.packaging.notebook import (
    notebook_embedded_inputs,
    validate_kernel_metadata,
)
from arc3.packaging.requirements import (
    TARGET_ABI,
    TARGET_IMPLEMENTATION,
    TARGET_PIP_PLATFORMS,
    TARGET_PLATFORM,
    TARGET_PYTHON_VERSION,
)
from arc3.packaging.runtime_launcher import AGENTS_COMMIT, SAFE_FRAMEWORK_FIXTURE_IDENTITY
from arc3.packaging.util import canonical_json_bytes, sha256_bytes, sha256_file
from arc3.types import JSONValue

EXPECTED_CANDIDATE_MEMBERS = (
    "arc3-first-party.zip",
    "arc3-submission.ipynb",
    "kernel-metadata.json",
    "package-manifest.json",
    "runtime-requirements-linux-cp312.txt",
    "runtime-wheels-linux-cp312.json",
    "sbom.spdx.json",
    "submission-schema.v0.1.json",
)
_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
_REQUIREMENTS_HEADER = (
    "# Generated from uv.lock; CPython 3.12 Linux x86_64 only.\n"
    "# Installation must also pass --no-index --no-deps --require-hashes.\n"
)


def _json_object(value: bytes, *, name: str) -> dict[str, JSONValue]:
    try:
        decoded = json.loads(value)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise PackagingError(f"candidate member {name} is not valid JSON: {error}") from error
    if not isinstance(decoded, dict):
        raise PackagingError(f"candidate member {name} must be a JSON object")
    return cast(dict[str, JSONValue], decoded)


def _safe_unique_names(archive: zipfile.ZipFile, *, label: str) -> tuple[str, ...]:
    names = tuple(archive.namelist())
    if len(names) != len(set(names)):
        raise PackagingError(f"{label} contains duplicate member names")
    for info in archive.infolist():
        name = info.orig_filename
        posix = PurePosixPath(name)
        windows = PureWindowsPath(name)
        raw_parts = name.split("/")
        if (
            not name
            or "\x00" in name
            or "\\" in name
            or info.is_dir()
            or posix.is_absolute()
            or windows.is_absolute()
            or bool(windows.drive)
            or any(part in {"", ".", ".."} for part in raw_parts)
            or any(":" in part for part in raw_parts)
        ):
            raise PackagingError(f"{label} contains an unsafe member: {name!r}")
        mode = info.external_attr >> 16
        file_type = stat.S_IFMT(mode)
        if file_type not in {0, stat.S_IFREG} or (
            info.create_system == 0 and bool(info.external_attr & 0x400)
        ):
            raise PackagingError(f"{label} contains a link or special member: {name!r}")
    return names


def _record_map(value: JSONValue, *, name: str) -> dict[str, dict[str, JSONValue]]:
    if not isinstance(value, list):
        raise PackagingError(f"{name} records must be an array")
    records: dict[str, dict[str, JSONValue]] = {}
    for raw in value:
        if not isinstance(raw, dict):
            raise PackagingError(f"{name} record must be an object")
        path = raw.get("path")
        digest = raw.get("sha256")
        size = raw.get("size_bytes")
        if not isinstance(path, str) or not isinstance(digest, str) or not isinstance(size, int):
            raise PackagingError(f"{name} record is incomplete")
        if path in records:
            raise PackagingError(f"{name} contains duplicate path {path!r}")
        records[path] = raw
    return records


def _verify_recorded_members(
    archive: zipfile.ZipFile,
    records: dict[str, dict[str, JSONValue]],
    *,
    label: str,
) -> None:
    if set(archive.namelist()) != records.keys():
        raise PackagingError(f"{label} members do not match its manifest records")
    for name, record in records.items():
        content = archive.read(name)
        if record["sha256"] != sha256_bytes(content):
            raise PackagingError(f"{label} member hash mismatch: {name}")
        if record["size_bytes"] != len(content):
            raise PackagingError(f"{label} member size mismatch: {name}")


def _runtime_wheel_identities(
    requirements_bytes: bytes, wheel_manifest_bytes: bytes
) -> tuple[dict[str, str], ...]:
    wheel_manifest = _json_object(wheel_manifest_bytes, name="runtime wheel manifest")
    if (
        wheel_manifest.get("schema") != "arc3.runtime-wheel-manifest.v0.1"
        or wheel_manifest.get("python") != "3.12"
        or wheel_manifest.get("target") != TARGET_PLATFORM
    ):
        raise PackagingError("runtime wheel manifest has an unexpected target or schema")
    if wheel_manifest.get("pip_target") != {
        "abi": TARGET_ABI,
        "exact_wheelhouse_required": True,
        "implementation": TARGET_IMPLEMENTATION,
        "single_platform_simulation_supported": False,
        "platforms": list(TARGET_PIP_PLATFORMS),
        "python_version": TARGET_PYTHON_VERSION,
    }:
        raise PackagingError("runtime wheel manifest has an incomplete pip target")
    if wheel_manifest.get("requirements_sha256") != sha256_bytes(requirements_bytes):
        raise PackagingError("runtime wheel manifest does not identify its requirements")
    manifest_core = dict(wheel_manifest)
    recorded_core_hash = manifest_core.pop("manifest_core_sha256", None)
    manifest_core.pop("requirements_sha256", None)
    if recorded_core_hash != sha256_bytes(canonical_json_bytes(manifest_core)):
        raise PackagingError("runtime wheel manifest core hash does not verify")

    raw_packages = wheel_manifest.get("packages")
    if not isinstance(raw_packages, list) or not raw_packages:
        raise PackagingError("runtime wheel manifest has no package identities")
    identities: list[dict[str, str]] = []
    for raw in raw_packages:
        if not isinstance(raw, dict):
            raise PackagingError("runtime wheel manifest package must be an object")
        fields = {key: raw.get(key) for key in ("filename", "name", "sha256", "url", "version")}
        if not all(isinstance(value, str) and value for value in fields.values()):
            raise PackagingError("runtime wheel identity is incomplete")
        identity = cast(dict[str, str], fields)
        if not _SHA256.fullmatch(identity["sha256"]):
            raise PackagingError("runtime wheel identity has an invalid SHA-256")
        filename = identity["filename"]
        if (
            PurePosixPath(filename).name != filename
            or not filename.endswith(".whl")
            or Path(unquote(urlparse(identity["url"]).path)).name != filename
        ):
            raise PackagingError("runtime wheel identity has an invalid filename or URL")
        identities.append(identity)
    if [item["name"] for item in identities] != sorted(item["name"] for item in identities):
        raise PackagingError("runtime wheel identities are not in canonical name order")
    if len({item["name"] for item in identities}) != len(identities):
        raise PackagingError("runtime wheel manifest contains a duplicate package name")
    expected_requirements = (
        _REQUIREMENTS_HEADER
        + "\n".join(
            f"{item['name']}=={item['version']} --hash={item['sha256']}" for item in identities
        )
        + "\n"
    ).encode("utf-8")
    if requirements_bytes != expected_requirements:
        raise PackagingError("runtime requirements do not exactly match the wheel manifest")
    return tuple(identities)


def _spdx_id(name: str) -> str:
    normalized = "".join(character if character.isalnum() else "-" for character in name)
    return f"SPDXRef-Package-{normalized}"


def _validate_runtime_sbom(
    sbom: dict[str, JSONValue],
    *,
    wheels: tuple[dict[str, str], ...],
    requirements_sha256: str,
    wheel_manifest_sha256: str,
    payload_sha256: str,
) -> None:
    if sbom.get("spdxVersion") != "SPDX-2.3":
        raise PackagingError("candidate SBOM is not SPDX 2.3")
    annotations = sbom.get("annotations")
    linked_identities = (requirements_sha256, wheel_manifest_sha256, payload_sha256)
    if not isinstance(annotations, list) or not any(
        isinstance(item, dict)
        and all(identity in str(item.get("comment", "")) for identity in linked_identities)
        for item in annotations
    ):
        raise PackagingError("candidate SBOM is not linked to the exact runtime artifacts")
    raw_packages = sbom.get("packages")
    if not isinstance(raw_packages, list):
        raise PackagingError("candidate SBOM has no package inventory")
    packages: dict[str, dict[str, JSONValue]] = {}
    for raw in raw_packages:
        if not isinstance(raw, dict) or not isinstance(raw.get("SPDXID"), str):
            raise PackagingError("candidate SBOM package record is incomplete")
        package_id = cast(str, raw["SPDXID"])
        if package_id in packages:
            raise PackagingError(f"candidate SBOM repeats package identity {package_id}")
        packages[package_id] = raw
    first_party = packages.get(_spdx_id("arc3"))
    if (
        first_party is None
        or first_party.get("licenseDeclared") != "MIT-0"
        or first_party.get("licenseConcluded") != "MIT-0"
    ):
        raise PackagingError("first-party ARC3 license must declare MIT-0")
    extracted_licenses = sbom.get("hasExtractedLicensingInfos")
    if not isinstance(extracted_licenses, list) or not any(
        isinstance(item, dict)
        and item.get("licenseId") == "LicenseRef-Matplotlib-3.11.1-Composite"
        and isinstance(item.get("extractedText"), str)
        and bool(cast(str, item["extractedText"]).strip())
        for item in extracted_licenses
    ):
        raise PackagingError("SBOM does not contain Matplotlib's extracted composite license")
    for wheel in wheels:
        package = packages.get(_spdx_id(wheel["name"]))
        expected_checksum = wheel["sha256"].removeprefix("sha256:")
        if (
            package is None
            or package.get("name") != wheel["name"]
            or package.get("versionInfo") != wheel["version"]
            or package.get("downloadLocation") != wheel["url"]
            or package.get("licenseDeclared") in (None, "NOASSERTION")
            or "version-keyed evidence" not in str(package.get("licenseComments", ""))
        ):
            raise PackagingError(f"SBOM runtime identity is incomplete for {wheel['name']}")
        checksums = package.get("checksums")
        if not isinstance(checksums, list) or not any(
            isinstance(checksum, dict)
            and checksum.get("algorithm") == "SHA256"
            and checksum.get("checksumValue") == expected_checksum
            for checksum in checksums
        ):
            raise PackagingError(f"SBOM wheel hash is missing for {wheel['name']}")
    agents = packages.get(_spdx_id("arc-agi-3-agents-platform"))
    if (
        agents is None
        or agents.get("name") != "ARC-AGI-3-Agents"
        or agents.get("versionInfo") != AGENTS_COMMIT
        or agents.get("licenseDeclared") != "MIT"
    ):
        raise PackagingError("SBOM platform Agents component is absent or unpinned")
    build_only_versions = (
        ("pyarrow-build-only", "21.0.0"),
        ("hatchling-build-only", "1.32.0"),
        ("pathspec-build-only", "1.1.1"),
        ("pluggy-build-only", "1.6.0"),
        ("tomlkit-build-only", "0.15.1"),
        ("trove-classifiers-build-only", "2026.6.1.19"),
        ("uv-build-tool", "0.12.5"),
    )
    for name, version in build_only_versions:
        package = packages.get(_spdx_id(name))
        if package is None or package.get("versionInfo") != version:
            raise PackagingError(f"SBOM build-only identity is absent or unpinned: {name}")


def _decode_candidate_members(candidate: zipfile.ZipFile) -> dict[str, bytes]:
    names = _safe_unique_names(candidate, label="candidate archive")
    if names != EXPECTED_CANDIDATE_MEMBERS:
        raise PackagingError(
            "candidate archive members differ from the fixed review-artifact contract"
        )
    return {name: candidate.read(name) for name in names}


def _validate_candidate_members(
    members: Mapping[str, bytes], *, candidate_sha256: str
) -> dict[str, JSONValue]:
    names = tuple(members)
    if names != EXPECTED_CANDIDATE_MEMBERS:
        raise PackagingError("candidate member snapshots differ from the fixed release contract")
    manifest = _json_object(members["package-manifest.json"], name="manifest")
    artifacts = _record_map(manifest.get("artifacts"), name="artifact")
    expected_artifacts = set(EXPECTED_CANDIDATE_MEMBERS) - {"package-manifest.json"}
    if artifacts.keys() != expected_artifacts:
        raise PackagingError("manifest artifact paths do not match candidate members")
    for name, record in artifacts.items():
        content = members[name]
        if record["sha256"] != sha256_bytes(content):
            raise PackagingError(f"candidate member hash mismatch: {name}")
        if record["size_bytes"] != len(content):
            raise PackagingError(f"candidate member size mismatch: {name}")

    source = manifest.get("source")
    build_status = manifest.get("build_status")
    if not isinstance(source, dict) or not isinstance(source.get("git_dirty"), bool):
        raise PackagingError("candidate manifest has no source cleanliness receipt")
    expected_status = "PACKAGING_PREACCEPTANCE" if source["git_dirty"] else "PACKAGING_PASS"
    if build_status != expected_status:
        raise PackagingError("candidate build status does not match source cleanliness")

    runtime_lock = manifest.get("runtime_lock")
    if not isinstance(runtime_lock, dict):
        raise PackagingError("candidate manifest has no exact runtime lock")
    requirements_bytes = members["runtime-requirements-linux-cp312.txt"]
    wheel_manifest_bytes = members["runtime-wheels-linux-cp312.json"]
    if runtime_lock.get("requirements_sha256") != sha256_bytes(requirements_bytes):
        raise PackagingError("runtime requirements hash does not match the manifest")
    if runtime_lock.get("wheel_manifest_sha256") != sha256_bytes(wheel_manifest_bytes):
        raise PackagingError("runtime wheel manifest hash does not match the manifest")
    if runtime_lock.get("target") != TARGET_PLATFORM:
        raise PackagingError("package manifest has an unexpected runtime target")
    wheels = _runtime_wheel_identities(requirements_bytes, wheel_manifest_bytes)

    offline_rehearsal = manifest.get("offline_rehearsal")
    if not isinstance(offline_rehearsal, dict):
        raise PackagingError("candidate manifest has no offline rehearsal receipt")
    sandbox = offline_rehearsal.get("receipt")
    if not isinstance(sandbox, dict) or sandbox.get("status") != "PASS":
        raise PackagingError("candidate sandbox receipt is absent or did not pass")
    if sandbox.get("notebook_sha256") != sha256_bytes(members["arc3-submission.ipynb"]):
        raise PackagingError("sandbox receipt does not identify the candidate notebook")
    if sandbox.get("payload_sha256") != sha256_bytes(members["arc3-first-party.zip"]):
        raise PackagingError("sandbox receipt does not identify the candidate payload")
    if sandbox.get("requirements_sha256") != sha256_bytes(requirements_bytes):
        raise PackagingError("sandbox receipt does not identify production requirements")
    if sandbox.get("secret_scan_status") != "PASS":
        raise PackagingError("sandbox extracted-payload secret rescan did not pass")
    if (
        sandbox.get("production_rerun_exercised") is not True
        or sandbox.get("agent_action_cycle_status") != "PASS"
        or sandbox.get("agent_consequence_state") != "NOT_FINISHED"
        or not isinstance(sandbox.get("agent_cycle_actions"), list)
        or cast(list[object], sandbox["agent_cycle_actions"])[0:1] != ["RESET"]
        or sandbox.get("dependency_install_status") != "PASS"
        or sandbox.get("network_attempts") != 0
        or sandbox.get("network_enforcement") != PYTHON_NETWORK_ENFORCEMENT
        or sandbox.get("credentials_present") != []
        or sandbox.get("framework_commit") != AGENTS_COMMIT
        or sandbox.get("framework_identity") != SAFE_FRAMEWORK_FIXTURE_IDENTITY
        or sandbox.get("framework_fixture") is not True
        or not isinstance(sandbox.get("gateway_connections"), int)
        or cast(int, sandbox["gateway_connections"]) < 2
    ):
        raise PackagingError("sandbox receipt did not exercise the hardened rerun path")
    limitations = sandbox.get("limitations")
    if (
        not isinstance(limitations, list)
        or len(limitations) < 4
        or not any(
            isinstance(item, str) and "OS-level network containment is absent" in item
            for item in limitations
        )
    ):
        raise PackagingError("sandbox receipt does not preserve its external limitations")
    secret_scan = manifest.get("secret_scan")
    if (
        not isinstance(secret_scan, dict)
        or secret_scan.get("status") != "PASS"
        or secret_scan.get("findings") != []
        or secret_scan.get("scopes")
        != ["payload-before-archive", "candidate-members-before-archive"]
    ):
        raise PackagingError("candidate manifest has no complete secret-rescan receipt")

    notebook = _json_object(members["arc3-submission.ipynb"], name="notebook")
    metadata = _json_object(members["kernel-metadata.json"], name="metadata")
    embedded = notebook_embedded_inputs(notebook)
    if embedded.payload != members["arc3-first-party.zip"]:
        raise PackagingError("notebook embedded payload differs from the candidate payload")
    if embedded.requirements != requirements_bytes:
        raise PackagingError("notebook embedded requirements differ from the runtime lock")
    if embedded.source_commit != source.get("git_commit"):
        raise PackagingError("notebook embedded source commit differs from the manifest")
    validate_kernel_metadata(metadata)
    sbom = _json_object(members["sbom.spdx.json"], name="SBOM")
    _validate_runtime_sbom(
        sbom,
        wheels=wheels,
        requirements_sha256=cast(str, runtime_lock["requirements_sha256"]),
        wheel_manifest_sha256=cast(str, runtime_lock["wheel_manifest_sha256"]),
        payload_sha256=sha256_bytes(members["arc3-first-party.zip"]),
    )
    schema = _json_object(members["submission-schema.v0.1.json"], name="submission schema")
    if schema.get("required") != ["row_id", "game_id", "end_of_game", "score"]:
        raise PackagingError("candidate submission schema has unexpected required fields")

    try:
        with zipfile.ZipFile(io.BytesIO(members["arc3-first-party.zip"])) as payload:
            payload_names = _safe_unique_names(payload, label="first-party payload")
            required_runtime_members = {
                "LICENSE",
                "THIRD_PARTY_NOTICES.md",
                "src/arc3/competition-runtime.v0.1.json",
                "src/arc3/competition-runtime.v0.2.json",
                "src/arc3/competition/__init__.py",
                "src/arc3/competition/governor.py",
                "src/arc3/competition_runtime.py",
            }
            if not required_runtime_members.issubset(payload_names):
                raise PackagingError(
                    "first-party payload omits the frozen competition runtime declaration"
                )
            if sha256_bytes(payload.read("LICENSE")) != f"sha256:{MIT0_LICENSE_SHA256}":
                raise PackagingError("payload LICENSE does not match owner-approved MIT-0")
            payload_manifest = manifest.get("payload")
            if not isinstance(payload_manifest, dict):
                raise PackagingError("manifest payload record is missing")
            records = _record_map(payload_manifest.get("files"), name="payload")
            _verify_recorded_members(payload, records, label="first-party payload")
            source_identity = payload_manifest.get("source_identity")
            expected_exact = source["git_dirty"] is False
            record_projection = [records[name] for name in sorted(records)]
            record_document = cast(dict[str, JSONValue], {"files": record_projection})
            if (
                not isinstance(source_identity, dict)
                or source_identity.get("exact_git_commit_bound") is not expected_exact
                or source_identity.get("git_commit") != source.get("git_commit")
                or source_identity.get("member_count") != len(records)
                or source_identity.get("member_records_sha256")
                != sha256_bytes(canonical_json_bytes(record_document))
                or source_identity.get("mode")
                != ("git-blob-exact" if expected_exact else "live-worktree-preacceptance")
            ):
                raise PackagingError(
                    "first-party payload lacks an exact source-member identity projection"
                )
            wheel_manifest = _json_object(wheel_manifest_bytes, name="runtime wheel manifest")
            if wheel_manifest.get("uv_lock_sha256") != sha256_bytes(payload.read("uv.lock")):
                raise PackagingError("runtime wheel manifest does not identify payload uv.lock")
            try:
                project = tomllib.loads(payload.read("pyproject.toml").decode("utf-8"))
            except (UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
                raise PackagingError(f"payload pyproject.toml is invalid: {error}") from error
            build_system = project.get("build-system")
            project_metadata = project.get("project")
            tool = project.get("tool")
            uv = tool.get("uv") if isinstance(tool, dict) else None
            if (
                not isinstance(build_system, dict)
                or build_system.get("requires") != ["hatchling==1.32.0"]
                or not isinstance(project_metadata, dict)
                or project_metadata.get("license") != "MIT-0"
                or project_metadata.get("license-files") != ["LICENSE"]
                or not isinstance(uv, dict)
                or uv.get("required-version") != "==0.12.5"
            ):
                raise PackagingError(
                    "payload build-system, license, or uv version is not exactly pinned"
                )
    except (OSError, zipfile.BadZipFile, KeyError) as error:
        raise PackagingError(f"candidate payload cannot be decoded: {error}") from error

    return {
        "candidate_sha256": candidate_sha256,
        "member_count": len(names),
        "payload_member_count": len(payload_names),
        "schema": "arc3.kaggle-candidate-validation.v0.1",
        "status": "PASS",
    }


def inspect_candidate_archive_snapshot(
    snapshot: bytes,
) -> tuple[dict[str, JSONValue], dict[str, bytes]]:
    """Decode and validate one already resource-bounded immutable candidate snapshot."""

    members = decode_candidate_archive_snapshot(snapshot)
    return validate_candidate_member_snapshots(snapshot, members), members


def decode_candidate_archive_snapshot(snapshot: bytes) -> dict[str, bytes]:
    """Decode fixed candidate members once from an immutable bounded snapshot."""

    try:
        with zipfile.ZipFile(io.BytesIO(snapshot)) as candidate:
            return _decode_candidate_members(candidate)
    except (OSError, zipfile.BadZipFile, KeyError) as error:
        raise PackagingError(f"candidate archive cannot be decoded: {error}") from error


def validate_candidate_member_snapshots(
    snapshot: bytes,
    members: Mapping[str, bytes],
) -> dict[str, JSONValue]:
    """Validate decoded member snapshots while retaining their outer-archive identity."""

    return _validate_candidate_members(members, candidate_sha256=sha256_bytes(snapshot))


def validate_candidate_archive(path: Path | bytes) -> dict[str, JSONValue]:
    """Verify a candidate path or an already bounded immutable byte snapshot."""

    if isinstance(path, bytes):
        return inspect_candidate_archive_snapshot(path)[0]
    if not path.is_file():
        raise PackagingError(f"candidate archive does not exist: {path}")
    candidate_sha256 = sha256_file(path)
    try:
        with zipfile.ZipFile(path) as candidate:
            members = _decode_candidate_members(candidate)
    except (OSError, zipfile.BadZipFile, KeyError) as error:
        raise PackagingError(f"candidate archive cannot be decoded: {error}") from error
    return _validate_candidate_members(members, candidate_sha256=candidate_sha256)


__all__ = [
    "EXPECTED_CANDIDATE_MEMBERS",
    "decode_candidate_archive_snapshot",
    "inspect_candidate_archive_snapshot",
    "validate_candidate_archive",
    "validate_candidate_member_snapshots",
]
