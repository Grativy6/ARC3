"""Production Build 002 preflight evidence validation and bundle construction.

This module is intentionally launch-free.  It validates already-created package,
profile, integrity, source-identity, and native Linux cold-start evidence, then
constructs hash-bound gate receipts and the runner plan.  It never imports an ARC
gateway, opens a scorecard, calls ``make``, or writes the one-shot launch marker.

The public CLI never enables fixture mode.  The explicit fixture boundary exists
only so CI can exercise bundle construction without claiming a native Linux or
public-game result; fixture gates are rejected by the holdout arming validator.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from arc3.competition_runtime import (
    BUILD_002_COMPETITION_RUNTIME_SCHEMA,
    load_competition_runtime,
)
from arc3.errors import EvaluationError
from arc3.evaluation.artifacts import canonical_json_bytes, sha256_file
from arc3.integrity import IntegrityReceipt
from arc3.licensing import MIT0_LICENSE_SHA256
from arc3.packaging.candidate import validate_candidate_archive
from arc3.packaging.notebook import notebook_embedded_inputs, validate_notebook
from arc3.packaging.runtime_launcher import AGENTS_COMMIT, _validate_framework
from arc3.packaging.submission import validate_submission_parquet
from arc3.packaging.util import write_bytes_atomic
from arc3.types import JSONValue

PREFLIGHT_REQUEST_SCHEMA = "arc3.build-002.preflight-bundle-request.v0.1"
PREFLIGHT_BLOCKER_SCHEMA = "arc3.build-002.preflight-blocked-external.v0.1"
CANDIDATE_VALIDATION_EVIDENCE_SCHEMA = "arc3.build-002.candidate-validation-evidence.v0.1"
DETERMINISM_EVIDENCE_SCHEMA = "arc3.build-002.determinism-and-replay-evidence.v0.1"
GATE_SCHEMA_VERSION = "v0.2"

GATE_EVIDENCE_ROLES = frozenset(
    {
        "build-receipt",
        "candidate-validation",
        "deterministic-replay",
        "first-party-license",
        "integrity-scan",
        "native-linux-cold-start",
        "package-manifest",
        "runtime-profile",
        "source-identity",
    }
)

_REQUEST_FIELDS = frozenset(
    {
        "assets",
        "dependency_lock",
        "framework_root",
        "gateway_host",
        "gateway_port",
        "integrity_receipt",
        "license_file",
        "manifest",
        "native_linux_cold_start_receipt",
        "output_directory",
        "package_directory",
        "production_agent",
        "runtime_config",
        "runtime_profile_receipt",
        "schema",
        "seed",
        "source_identity_receipt",
        "source_preview_receipt",
        "submission_output",
        "third_party_notices",
        "upstream_lock",
    }
)
_HASH = re.compile(r"^sha256:[0-9a-f]{64}$")
_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_ALLOWED_GATEWAY_HOSTS = frozenset({"127.0.0.1", "::1", "gateway", "localhost"})
_COLD_START_SCHEMA = "arc3.build-002-cold-start-command.v0.2"
_PROFILE_SCHEMA = "arc3.stage16.profile.v0.1"
_SOURCE_IDENTITY_SCHEMA = "arc3.build-002.official-source-identities.v0.1"
_PACKAGE_RECEIPT_SCHEMA = "arc3.kaggle-build-receipt.v0.1"
_PACKAGE_MANIFEST_SCHEMA = "arc3.kaggle-package-manifest.v0.1"


@dataclass(frozen=True, slots=True)
class PreflightBundleRequest:
    """Every already-present input needed for a launch-free preflight bundle."""

    root: Path
    seed: int
    manifest: Path
    assets: dict[str, Path]
    framework_root: Path
    production_agent: Path
    gateway_host: str
    gateway_port: int
    submission_output: Path
    package_directory: Path
    integrity_receipt: Path
    runtime_profile_receipt: Path
    native_linux_cold_start_receipt: Path
    source_identity_receipt: Path
    runtime_config: Path
    dependency_lock: Path
    upstream_lock: Path
    source_preview_receipt: Path
    third_party_notices: Path
    license_file: Path
    output_directory: Path


@dataclass(frozen=True, slots=True)
class BundlePaths:
    """Canonical output paths produced without touching the one-shot state root."""

    candidate_validation: Path
    determinism_evidence: Path
    agent_wrapper: Path
    asset_inventory: Path
    gates_directory: Path
    run_plan: Path
    blocker: Path


@dataclass(frozen=True, slots=True)
class BundleResult:
    """Outcome of a launch-free production or fixture preflight construction."""

    status: str
    output_directory: Path
    run_plan: Path | None
    blocker: Path | None
    environment_make_interactions: int
    holdout_authority_consumed: bool

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "blocker": self.blocker.as_posix() if self.blocker is not None else None,
            "environment_make_interactions": self.environment_make_interactions,
            "holdout_authority_consumed": self.holdout_authority_consumed,
            "output_directory": self.output_directory.as_posix(),
            "run_plan": self.run_plan.as_posix() if self.run_plan is not None else None,
            "status": self.status,
        }


def _load_object(path: Path, *, label: str) -> dict[str, Any]:
    try:
        value: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise EvaluationError(f"{label} is not a readable JSON object") from error
    if not isinstance(value, dict):
        raise EvaluationError(f"{label} must contain a JSON object")
    return cast(dict[str, Any], value)


def _sha256_bytes(raw: bytes) -> str:
    return f"sha256:{hashlib.sha256(raw).hexdigest()}"


def _verify_self_hash(document: Mapping[str, Any], *, field: str, label: str) -> None:
    claimed = document.get(field)
    body = {key: value for key, value in document.items() if key != field}
    if not isinstance(claimed, str) or claimed != _sha256_bytes(canonical_json_bytes(body)):
        raise EvaluationError(f"{label} self-hash does not verify")


def _inside(root: Path, path: Path, *, label: str) -> tuple[Path, str]:
    resolved = path.resolve()
    try:
        relative = resolved.relative_to(root.resolve()).as_posix()
    except ValueError as error:
        raise EvaluationError(f"{label} must remain inside the repository") from error
    if not relative or any(part in {"", ".", ".."} for part in relative.split("/")):
        raise EvaluationError(f"{label} is not a canonical repository path")
    return resolved, relative


def _request_path(
    root: Path,
    value: object,
    *,
    label: str,
    require_inside: bool,
) -> Path:
    if not isinstance(value, str) or not value or value.strip() != value:
        raise EvaluationError(f"{label} must be a canonical non-empty path")
    raw = Path(value)
    resolved = (root / raw).resolve() if not raw.is_absolute() else raw.resolve()
    if require_inside:
        _inside(root, resolved, label=label)
    return resolved


def load_preflight_bundle_request(root: Path, path: Path) -> PreflightBundleRequest:
    """Load an exact-field request without performing any environment interaction."""

    resolved_root = root.resolve()
    raw = _load_object(path, label="Build 002 preflight request")
    if set(raw) != _REQUEST_FIELDS or raw.get("schema") != PREFLIGHT_REQUEST_SCHEMA:
        raise EvaluationError("Build 002 preflight request schema or fields are invalid")
    seed = raw.get("seed")
    port = raw.get("gateway_port")
    host = raw.get("gateway_host")
    if isinstance(seed, bool) or not isinstance(seed, int) or not -(2**63) <= seed < 2**63:
        raise EvaluationError("Build 002 preflight seed must be a signed 64-bit integer")
    if not isinstance(port, int) or isinstance(port, bool) or not 1 <= port <= 65535:
        raise EvaluationError("Build 002 gateway port is invalid")
    if not isinstance(host, str) or host not in _ALLOWED_GATEWAY_HOSTS:
        raise EvaluationError("Build 002 gateway host is outside the offline sidecar boundary")
    raw_assets = raw.get("assets")
    if not isinstance(raw_assets, dict) or any(not isinstance(key, str) for key in raw_assets):
        raise EvaluationError("Build 002 asset map must be an object of paths")
    assets = {
        key: _request_path(
            resolved_root,
            value,
            label=f"assets.{key}",
            require_inside=False,
        )
        for key, value in cast(dict[str, object], raw_assets).items()
    }
    return PreflightBundleRequest(
        root=resolved_root,
        seed=seed,
        manifest=_request_path(
            resolved_root, raw["manifest"], label="manifest", require_inside=True
        ),
        assets=assets,
        framework_root=_request_path(
            resolved_root,
            raw["framework_root"],
            label="framework_root",
            require_inside=False,
        ),
        production_agent=_request_path(
            resolved_root,
            raw["production_agent"],
            label="production_agent",
            require_inside=True,
        ),
        gateway_host=host,
        gateway_port=port,
        submission_output=_request_path(
            resolved_root,
            raw["submission_output"],
            label="submission_output",
            require_inside=False,
        ),
        package_directory=_request_path(
            resolved_root,
            raw["package_directory"],
            label="package_directory",
            require_inside=True,
        ),
        integrity_receipt=_request_path(
            resolved_root,
            raw["integrity_receipt"],
            label="integrity_receipt",
            require_inside=True,
        ),
        runtime_profile_receipt=_request_path(
            resolved_root,
            raw["runtime_profile_receipt"],
            label="runtime_profile_receipt",
            require_inside=True,
        ),
        native_linux_cold_start_receipt=_request_path(
            resolved_root,
            raw["native_linux_cold_start_receipt"],
            label="native_linux_cold_start_receipt",
            require_inside=True,
        ),
        source_identity_receipt=_request_path(
            resolved_root,
            raw["source_identity_receipt"],
            label="source_identity_receipt",
            require_inside=True,
        ),
        runtime_config=_request_path(
            resolved_root,
            raw["runtime_config"],
            label="runtime_config",
            require_inside=True,
        ),
        dependency_lock=_request_path(
            resolved_root,
            raw["dependency_lock"],
            label="dependency_lock",
            require_inside=True,
        ),
        upstream_lock=_request_path(
            resolved_root,
            raw["upstream_lock"],
            label="upstream_lock",
            require_inside=True,
        ),
        source_preview_receipt=_request_path(
            resolved_root,
            raw["source_preview_receipt"],
            label="source_preview_receipt",
            require_inside=True,
        ),
        third_party_notices=_request_path(
            resolved_root,
            raw["third_party_notices"],
            label="third_party_notices",
            require_inside=True,
        ),
        license_file=_request_path(
            resolved_root,
            raw["license_file"],
            label="license_file",
            require_inside=True,
        ),
        output_directory=_request_path(
            resolved_root,
            raw["output_directory"],
            label="output_directory",
            require_inside=True,
        ),
    )


def bundle_paths(request: PreflightBundleRequest) -> BundlePaths:
    """Return the deterministic output layout for a request."""

    output = request.output_directory
    return BundlePaths(
        candidate_validation=output / "candidate-validation.json",
        determinism_evidence=output / "determinism-and-replay.json",
        agent_wrapper=output / "agent-wrapper.py",
        asset_inventory=output / "holdout-asset-inventory.json",
        gates_directory=output / "gates",
        run_plan=output / "run-plan.json",
        blocker=output / "blocked-external.json",
    )


def _git(root: Path, *arguments: str) -> str:
    try:
        completed = subprocess.run(
            ("git", "--no-replace-objects", "-C", str(root), *arguments),
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=30,
            env={
                **{key: value for key, value in os.environ.items() if not key.startswith("GIT_")},
                "GIT_NO_REPLACE_OBJECTS": "1",
            },
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise EvaluationError("Build 002 preflight could not resolve Git identity") from error
    return completed.stdout.strip()


def _current_commit(root: Path, *, allow_test_fixtures: bool) -> str:
    commit = _git(root, "rev-parse", "HEAD")
    if _COMMIT.fullmatch(commit) is None:
        raise EvaluationError("Build 002 source commit is not a full lowercase SHA-1")
    if not allow_test_fixtures and _git(root, "status", "--porcelain", "--untracked-files=all"):
        raise EvaluationError("production Build 002 preflight requires a clean worktree")
    return commit


def _require_files(paths: Mapping[str, Path]) -> None:
    missing = sorted(label for label, path in paths.items() if not path.is_file())
    if missing:
        raise FileNotFoundError(
            "required Build 002 preflight inputs are missing: " + ", ".join(missing)
        )


def _package_paths(package_directory: Path) -> dict[str, Path]:
    return {
        "build-receipt": package_directory / "build-receipt.json",
        "candidate": package_directory / "arc3-kaggle-candidate.zip",
        "notebook": package_directory / "arc3-submission.ipynb",
        "package-manifest": package_directory / "package-manifest.json",
        "payload": package_directory / "arc3-first-party.zip",
        "requirements": package_directory / "runtime-requirements-linux-cp312.txt",
        "sandbox-submission": package_directory / "offline-sandbox" / "submission.parquet",
        "sbom": package_directory / "sbom.spdx.json",
        "wheel-manifest": package_directory / "runtime-wheels-linux-cp312.json",
    }


def _validate_package(
    request: PreflightBundleRequest,
    *,
    commit: str,
    allow_test_fixtures: bool,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, JSONValue]]:
    paths = _package_paths(request.package_directory)
    _require_files(paths)
    candidate_validation = validate_candidate_archive(paths["candidate"])
    if candidate_validation.get("status") != "PASS":
        raise EvaluationError("candidate archive validator did not return PASS")
    receipt = _load_object(paths["build-receipt"], label="Kaggle build receipt")
    manifest = _load_object(paths["package-manifest"], label="Kaggle package manifest")
    package_status = receipt.get("status")
    allowed_statuses = (
        {"PACKAGING_PASS", "PACKAGING_PREACCEPTANCE"} if allow_test_fixtures else {"PACKAGING_PASS"}
    )
    if (
        receipt.get("schema") != _PACKAGE_RECEIPT_SCHEMA
        or package_status not in allowed_statuses
        or receipt.get("official_submission_performed") is not False
    ):
        raise EvaluationError("Kaggle build receipt is not valid for this evidence class")
    _verify_self_hash(receipt, field="receipt_sha256", label="Kaggle build receipt")
    if receipt.get("candidate_sha256") != sha256_file(paths["candidate"]):
        raise EvaluationError("Kaggle build receipt candidate identity changed")
    if receipt.get("candidate_validation") != candidate_validation:
        raise EvaluationError("Kaggle build receipt candidate validation changed")
    if receipt.get("notebook_sha256") != sha256_file(paths["notebook"]):
        raise EvaluationError("Kaggle build receipt notebook identity changed")
    if receipt.get("payload_sha256") != sha256_file(paths["payload"]):
        raise EvaluationError("Kaggle build receipt payload identity changed")
    if receipt.get("runtime_requirements_sha256") != sha256_file(paths["requirements"]):
        raise EvaluationError("Kaggle build receipt requirements identity changed")
    if receipt.get("wheel_manifest_sha256") != sha256_file(paths["wheel-manifest"]):
        raise EvaluationError("Kaggle build receipt wheel identity changed")
    if receipt.get("sbom_sha256") != sha256_file(paths["sbom"]):
        raise EvaluationError("Kaggle build receipt SBOM identity changed")

    sandbox = receipt.get("sandbox")
    validation = receipt.get("validation")
    if (
        not isinstance(sandbox, dict)
        or sandbox.get("status") != "PASS"
        or sandbox.get("production_rerun_exercised") is not True
        or sandbox.get("network_attempts") != 0
        or sandbox.get("credentials_present") != []
        or sandbox.get("dependency_install_status") != "PASS"
        or sandbox.get("secret_scan_status") != "PASS"
        or sandbox.get("agent_count") != 1
        or sandbox.get("worker_count") != 1
        or sandbox.get("max_concurrency") != 1
        or sandbox.get("orchestration") != "arc3.sequential-pinned-swarm.v1"
        or not isinstance(validation, dict)
        or validation.get("status") != "PASS"
    ):
        raise EvaluationError("Kaggle offline notebook/sandbox receipt is incomplete")
    submission_validation = validate_submission_parquet(paths["sandbox-submission"])
    submission_hash = sha256_file(paths["sandbox-submission"])
    if (
        sandbox.get("output_sha256") != submission_hash
        or receipt.get("sandbox_output_sha256") != submission_hash
        or validation.get("artifact_sha256") != submission_hash
        or submission_validation.artifact_sha256 != submission_hash
    ):
        raise EvaluationError("sandbox submission identities do not agree")

    notebook = _load_object(paths["notebook"], label="Kaggle notebook")
    validate_notebook(cast(dict[str, JSONValue], notebook))
    embedded = notebook_embedded_inputs(cast(dict[str, JSONValue], notebook))
    if embedded.payload != paths["payload"].read_bytes():
        raise EvaluationError("Kaggle notebook embeds a different first-party payload")
    if embedded.validation_parquet != paths["sandbox-submission"].read_bytes():
        raise EvaluationError("Kaggle notebook embeds a different validation Parquet")

    source = manifest.get("source")
    competition = manifest.get("competition")
    secret_scan = manifest.get("secret_scan")
    if (
        manifest.get("schema") != _PACKAGE_MANIFEST_SCHEMA
        or manifest.get("build_status") != package_status
        or not isinstance(source, dict)
        or source.get("git_commit") != commit
        or source.get("git_dirty") is not (package_status == "PACKAGING_PREACCEPTANCE")
        or not isinstance(competition, dict)
        or competition.get("internet_enabled") is not False
        or competition.get("official_submission_performed") is not False
        or not isinstance(secret_scan, dict)
        or secret_scan.get("status") != "PASS"
        or secret_scan.get("findings") != []
    ):
        raise EvaluationError("Kaggle package manifest source or integrity boundary changed")
    if receipt.get("manifest_sha256") != sha256_file(paths["package-manifest"]):
        raise EvaluationError("Kaggle build receipt manifest identity changed")
    return receipt, manifest, candidate_validation


def _validate_runtime_and_sources(
    request: PreflightBundleRequest,
    *,
    commit: str,
    allow_test_fixtures: bool,
    validate_framework: bool = True,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    runtime = load_competition_runtime(request.runtime_config)
    if runtime.schema != BUILD_002_COMPETITION_RUNTIME_SCHEMA:
        raise EvaluationError("Build 002 runtime schema is not the competition-bounded schema")
    upstream = _load_object(request.upstream_lock, label="upstream lock")
    refresh = upstream.get("build_002_refresh")
    if upstream.get("schema") != "arc3.upstream-lock.v0.1" or not isinstance(refresh, dict):
        raise EvaluationError("upstream lock has no Build 002 source identity overlay")
    heads = refresh.get("public_repository_heads")
    metadata = refresh.get("kaggle_competition_metadata")
    if (
        not isinstance(heads, dict)
        or heads.get("arcprize/ARC-AGI-3-Agents") != AGENTS_COMMIT
        or not isinstance(metadata, dict)
        or metadata.get("competition_id") != runtime.kaggle_competition_id
        or metadata.get("response_sha256") != runtime.kaggle_metadata_response_sha256
        or metadata.get("internet_enabled") is not False
        or metadata.get("required_submission_file") != "submission.parquet"
        or metadata.get("legal_terms_accepted") is not False
        or metadata.get("credentials_used") is not False
    ):
        raise EvaluationError("runtime and upstream official identities disagree")
    if validate_framework:
        try:
            _validate_framework(request.framework_root, allow_test_fixture=allow_test_fixtures)
        except Exception as error:
            raise EvaluationError("pinned Agents framework identity is unavailable") from error

    source_identity = _load_object(
        request.source_identity_receipt, label="Build 002 source-identity receipt"
    )
    if source_identity.get("fixture") is True and not allow_test_fixtures:
        raise EvaluationError("production preflight rejects fixture source-identity evidence")
    if (
        source_identity.get("schema") != _SOURCE_IDENTITY_SCHEMA
        or source_identity.get("status") not in {"PARTIAL", "PASS"}
        or source_identity.get("official_result") is not None
        or source_identity.get("public_holdout_consumed") is not False
    ):
        raise EvaluationError("Build 002 source-identity claim boundary changed")
    project_lock = source_identity.get("project_lock")
    source_repositories = source_identity.get("repositories")
    if (
        not isinstance(project_lock, dict)
        or project_lock.get("sha256") != sha256_file(request.upstream_lock)
        or not isinstance(source_repositories, list)
    ):
        raise EvaluationError("source-identity receipt does not bind the upstream lock")
    source_heads = {
        item.get("name"): item.get("commit")
        for item in source_repositories
        if isinstance(item, dict)
    }
    if any(source_heads.get(name) != value for name, value in heads.items()):
        raise EvaluationError("source-identity receipt repository heads changed")
    blocked = source_identity.get("blocked_external")
    required_private_surfaces = {
        "exact private competition wheel set",
        "exact private gateway",
        "exact private scorer",
        "independently pinned ten-game static asset provenance",
    }
    if not isinstance(blocked, list) or any(not isinstance(item, str) for item in blocked):
        raise EvaluationError("private competition surface inventory is malformed")
    if allow_test_fixtures:
        if source_identity.get("status") != "PARTIAL" or not required_private_surfaces.issubset(
            set(blocked)
        ):
            raise EvaluationError("fixture source boundary is not honestly PARTIAL")
    elif source_identity.get("status") != "PASS" or blocked:
        raise FileNotFoundError(
            "exact private competition wheel, gateway, scorer, and static asset provenance "
            "remain unavailable"
        )
    else:
        attestations = source_identity.get("external_surface_attestations")
        required_attestations = {
            "competition-wheel-set",
            "framework-input",
            "gateway",
            "network-containment",
            "packaged-runner-imports",
            "platform-cold-start",
            "scorer",
        }
        if not isinstance(attestations, dict) or set(attestations) != required_attestations:
            raise FileNotFoundError(
                "exact competition surfaces have no complete official evidence attestations"
            )
        for role, raw_attestation in attestations.items():
            if not isinstance(raw_attestation, dict) or set(raw_attestation) != {
                "authority",
                "byte_length",
                "path",
                "schema",
                "sha256",
                "status",
            }:
                raise EvaluationError(f"external surface attestation is malformed: {role}")
            relative = raw_attestation.get("path")
            if (
                raw_attestation.get("schema") != "arc3.build-002.external-surface-attestation.v0.1"
                or raw_attestation.get("status") != "PASS"
                or raw_attestation.get("authority") != "official-returned-evidence"
                or not isinstance(relative, str)
            ):
                raise EvaluationError(f"external surface attestation is invalid: {role}")
            evidence_path = (request.root / relative).resolve()
            _inside(request.root, evidence_path, label=f"external-surface:{role}")
            if (
                not evidence_path.is_file()
                or raw_attestation.get("byte_length") != evidence_path.stat().st_size
                or raw_attestation.get("sha256") != sha256_file(evidence_path)
            ):
                raise EvaluationError(f"external surface attestation identity changed: {role}")

    try:
        dependency = tomllib.loads(request.dependency_lock.read_text(encoding="utf-8"))
        project = tomllib.loads((request.root / "pyproject.toml").read_text(encoding="utf-8"))
    except (OSError, UnicodeError, tomllib.TOMLDecodeError) as error:
        raise EvaluationError("dependency or project lock metadata is unreadable") from error
    packages = dependency.get("package")
    names = (
        {item.get("name") for item in packages if isinstance(item, dict)}
        if isinstance(packages, list)
        else set()
    )
    project_metadata = project.get("project")
    if (
        dependency.get("version") != 1
        or dependency.get("requires-python") != "==3.12.*"
        or not {"arc3", "arc-agi", "arcengine", "pyarrow"}.issubset(names)
        or not isinstance(project_metadata, dict)
        or project_metadata.get("license") != "MIT-0"
        or project_metadata.get("license-files") != ["LICENSE"]
    ):
        raise EvaluationError("Python, dependency, or first-party license identity changed")
    if sha256_file(request.license_file) != f"sha256:{MIT0_LICENSE_SHA256}":
        raise EvaluationError("first-party MIT-0 license bytes changed")
    try:
        notices = request.third_party_notices.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise EvaluationError("third-party notices are unreadable") from error
    if not all(
        marker in notices
        for marker in (
            "# Third-party notices",
            "Competition runtime distributions",
            "License evidence",
        )
    ):
        raise EvaluationError("third-party notices do not cover the packaged runtime")

    if not allow_test_fixtures and commit != _git(request.root, "rev-parse", "HEAD"):
        raise EvaluationError("source commit changed during preflight validation")
    return runtime.to_dict(), upstream, source_identity


def _validate_integrity(
    path: Path,
    *,
    commit: str,
    candidate: Path,
    allow_test_fixtures: bool,
) -> dict[str, Any]:
    raw = path.read_bytes()
    if allow_test_fixtures:
        receipt = _load_object(path, label="fixture integrity receipt")
        counts = receipt.get("finding_counts")
        checks = receipt.get("checks")
        secret_scan = checks.get("secret_scan") if isinstance(checks, dict) else None
        dependency_inventory = receipt.get("dependency_inventory")
        if (
            receipt.get("schema") != "arc3.build-002.fixture-integrity.v0.1"
            or receipt.get("status") != "PASS"
            or receipt.get("fixture") is not True
            or receipt.get("candidate_sha256") != sha256_file(candidate)
            or receipt.get("source_commit") != commit
            or receipt.get("secret_findings") != 0
            or receipt.get("package_only_passed") is not True
            or not isinstance(counts, dict)
            or counts.get("blocking") != 0
            or not isinstance(secret_scan, dict)
            or secret_scan.get("passed") is not True
            or not isinstance(dependency_inventory, list)
            or not dependency_inventory
        ):
            raise EvaluationError("fixture integrity receipt is not semantically valid")
        _verify_self_hash(receipt, field="receipt_sha256", label="fixture integrity receipt")
        return receipt
    try:
        parsed = IntegrityReceipt.from_bytes(raw)
    except (UnicodeError, ValueError) as error:
        raise EvaluationError(
            "production integrity receipt is not canonical or self-hashed"
        ) from error
    body = dict(parsed.body)
    git = body.get("git")
    counts = body.get("finding_counts")
    checks = body.get("checks")
    source_hashes = body.get("source_hashes")
    if (
        body.get("package_only_passed") is not True
        or body.get("passed") is not False
        or not isinstance(git, dict)
        or git.get("commit") != commit
        or git.get("dirty_worktree") is not False
        or not isinstance(counts, dict)
        or counts.get("blocking") != 0
        or not isinstance(checks, dict)
        or any(
            not isinstance(check := checks.get(name), dict) or check.get("passed") is not True
            for name in ("archive_static", "policy_static", "secret_scan", "source_identity")
        )
        or not isinstance(source_hashes, dict)
        or sha256_file(candidate) not in source_hashes.values()
    ):
        raise EvaluationError("production package-only integrity receipt is incomplete")
    return {**body, "receipt_sha256": parsed.receipt_sha256}


def _validate_cold_start(
    path: Path,
    *,
    package_paths: Mapping[str, Path],
    allow_test_fixtures: bool,
) -> dict[str, Any]:
    receipt = _load_object(path, label="native Linux cold-start receipt")
    if receipt.get("fixture") is True and not allow_test_fixtures:
        raise EvaluationError("production preflight rejects fixture cold-start evidence")
    cold = receipt.get("cold_start")
    if (
        receipt.get("schema") != "arc3.build-002-cold-start-command.v0.2"
        or receipt.get("status") != "PASS"
        or receipt.get("public_environment_interactions") != 0
        or receipt.get("kaggle_accessed") is not False
        or not isinstance(cold, dict)
        or cold.get("schema") != "arc3.linux-cold-start.v0.2"
        or cold.get("status") != "PASS"
        or cold.get("executed") is not True
        or cold.get("validation_level") != "native-linux-cp312-exact-notebook-cold-start"
        or cold.get("target") != "CPython 3.12 / Linux x86_64 / manylinux_2_28"
    ):
        raise EvaluationError("native Linux cold-start evidence is not an executed PASS")
    host = cold.get("host")
    identities = cold.get("identities")
    determinism = cold.get("determinism")
    notebook_entry = cold.get("notebook_entry")
    pip = cold.get("pip")
    output_validation = (
        notebook_entry.get("output_validation") if isinstance(notebook_entry, dict) else None
    )
    if (
        not allow_test_fixtures
        and isinstance(notebook_entry, dict)
        and notebook_entry.get("framework_fixture") is True
    ):
        raise FileNotFoundError(
            "native Linux packaged-entry rehearsal uses a safe framework fixture; "
            "the exact Kaggle competition platform cold start remains unavailable"
        )
    if (
        not isinstance(host, dict)
        or host.get("system") != "Linux"
        or host.get("machine") not in {"x86_64", "amd64"}
        or host.get("implementation") != "CPython"
        or not str(host.get("python", "")).startswith("3.12.")
        or not isinstance(identities, dict)
        or identities.get("package_manifest_sha256")
        != sha256_file(package_paths["package-manifest"])
        or identities.get("payload_sha256") != sha256_file(package_paths["payload"])
        or identities.get("requirements_sha256") != sha256_file(package_paths["requirements"])
        or identities.get("manifest_sha256") != sha256_file(package_paths["wheel-manifest"])
        or identities.get("notebook_sha256") != sha256_file(package_paths["notebook"])
        or not isinstance(determinism, dict)
        or determinism.get("repetitions") != 2
        or determinism.get("startup_projection_repetitions") != 2
        or determinism.get("notebook_entry_repetitions") != 1
        or not isinstance(determinism.get("stable_projection_sha256"), str)
        or _HASH.fullmatch(cast(str, determinism["stable_projection_sha256"])) is None
        or not isinstance(determinism.get("notebook_entry_projection_sha256"), str)
        or _HASH.fullmatch(cast(str, determinism["notebook_entry_projection_sha256"])) is None
        or not isinstance(pip, dict)
        or any(
            pip.get(name) is not True
            for name in ("isolated", "no_deps", "no_index", "require_hashes")
        )
        or not isinstance(notebook_entry, dict)
        or notebook_entry.get("status") != "PASS"
        or notebook_entry.get("executed") is not True
        or notebook_entry.get("repetitions") != 1
        or notebook_entry.get("entrypoint") != "exact-generated-notebook-code-cells"
        or notebook_entry.get("exact_generated_code_cells") != 4
        or notebook_entry.get("exact_production_requirements") is not True
        or notebook_entry.get("host_site_pth_bridge_present") is not False
        or notebook_entry.get("external_site_pth_entries") != []
        or notebook_entry.get("foreign_site_paths") != []
        or notebook_entry.get("kaggle_competition_rerun_branch") is not True
        or notebook_entry.get("runtime_dependency_surface")
        != "exact-embedded-production-requirements"
        or notebook_entry.get("platform_surface") != "safe-loopback-gateway-and-framework-fixture"
        or notebook_entry.get("framework_fixture") is not True
        or notebook_entry.get("network_attempts") != 0
        or notebook_entry.get("network_attempt_scope") != "non-loopback Python socket attempts"
        or not isinstance(notebook_entry.get("target_inventory_sha256"), str)
        or _HASH.fullmatch(cast(str, notebook_entry["target_inventory_sha256"])) is None
        or notebook_entry.get("notebook_sha256") != identities.get("notebook_sha256")
        or notebook_entry.get("payload_sha256") != identities.get("payload_sha256")
        or notebook_entry.get("requirements_sha256") != identities.get("requirements_sha256")
        or not isinstance(notebook_entry.get("peak_memory_bytes"), int)
        or cast(int, notebook_entry["peak_memory_bytes"]) <= 0
        or not isinstance(output_validation, dict)
        or output_validation.get("status") != "PASS"
        or output_validation.get("validation_level") != "pinned-public-schema"
        or output_validation.get("parquet_engine") != "pyarrow==21.0.0"
        or not isinstance(output_validation.get("artifact_sha256"), str)
        or _HASH.fullmatch(cast(str, output_validation["artifact_sha256"])) is None
    ):
        raise EvaluationError("native Linux cold-start identities or isolation checks changed")
    return receipt


def _validate_profile(
    path: Path,
    *,
    commit: str,
    runtime: Mapping[str, JSONValue],
    allow_test_fixtures: bool,
) -> dict[str, Any]:
    profile = _load_object(path, label="competition runtime profile")
    if profile.get("fixture") is True and not allow_test_fixtures:
        raise EvaluationError("production preflight rejects fixture runtime-profile evidence")
    _verify_self_hash(profile, field="receipt_sha256", label="competition runtime profile")
    measured = profile.get("profile")
    source_identity = profile.get("source_identity")
    startup = profile.get("startup")
    if (
        profile.get("schema") != _PROFILE_SCHEMA
        or profile.get("status") != "PASS"
        or profile.get("verified") is not True
        or profile.get("git_commit") != commit
        or profile.get("competition_runtime") != dict(runtime)
        or profile.get("competition_runtime_match") is not True
        or not isinstance(source_identity, dict)
        or source_identity.get("verified") is not True
        or not isinstance(measured, dict)
        or measured.get("verified") is not True
        or measured.get("trace_replay_verified") is not True
        or not isinstance(startup, dict)
        or startup.get("execution_mode") != "COMPETITION_BOUNDED"
    ):
        raise EvaluationError("competition runtime profile is not a frozen verified PASS")
    execution = measured.get("controller_execution")
    required = measured.get("required_predicates")
    budget = measured.get("budget_assessment")
    if (
        not isinstance(execution, dict)
        or execution.get("execution_mode") != "COMPETITION_BOUNDED"
        or not isinstance(required, dict)
        or any(value is not True for value in required.values())
        or not isinstance(budget, dict)
        or any(value is not True for value in budget.values())
    ):
        raise EvaluationError("competition profile execution, replay, or budgets are incomplete")
    return profile


def _candidate_evidence(
    *,
    candidate_validation: Mapping[str, JSONValue],
    build_receipt_path: Path,
    evidence_class: str,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "build_receipt_sha256": sha256_file(build_receipt_path),
        "candidate_sha256": candidate_validation["candidate_sha256"],
        "candidate_validation": dict(candidate_validation),
        "claim_boundary": "offline candidate structure and byte identity only; no gameplay",
        "environment_make_interactions": 0,
        "evidence_class": evidence_class,
        "schema": CANDIDATE_VALIDATION_EVIDENCE_SCHEMA,
        "status": "PASS",
    }
    body["receipt_sha256"] = _sha256_bytes(canonical_json_bytes(body))
    return body


def _determinism_evidence(
    *,
    commit: str,
    cold_start: Mapping[str, Any],
    cold_start_path: Path,
    profile: Mapping[str, Any],
    profile_path: Path,
    runtime: Mapping[str, JSONValue],
    evidence_class: str,
) -> dict[str, Any]:
    cold = cast(dict[str, Any], cold_start["cold_start"])
    determinism = cast(dict[str, Any], cold["determinism"])
    measured = cast(dict[str, Any], profile["profile"])
    execution = cast(dict[str, Any], measured["controller_execution"])
    runtime_policy = cast(dict[str, Any], execution["runtime_policy"])
    checks = {
        "compact_trace_retained": runtime.get("compact_trace_capacity") == 512,
        "deterministic_replay_verified": measured.get("trace_replay_verified") is True,
        "deterministic_startup_verified": (
            determinism.get("repetitions") == 2
            and isinstance(determinism.get("stable_projection_sha256"), str)
        ),
        "sparse_recovery_checkpoint_verified": (
            runtime_policy.get("automatic_per_action_checkpoints") is False
            and runtime_policy.get("sparse_checkpoint_interval_actions")
            == runtime.get("sparse_checkpoint_interval_actions")
        ),
    }
    if any(value is not True for value in checks.values()):
        raise EvaluationError("determinism/replay evidence projection is incomplete")
    body: dict[str, Any] = {
        "checks": checks,
        "claim_boundary": "derived from exact native cold-start and synthetic runtime-profile receipts",
        "cold_start_receipt_sha256": sha256_file(cold_start_path),
        "environment_make_interactions": 0,
        "evidence_class": evidence_class,
        "runtime_profile_receipt_sha256": sha256_file(profile_path),
        "schema": DETERMINISM_EVIDENCE_SCHEMA,
        "source_commit": commit,
        "stable_startup_projection_sha256": determinism["stable_projection_sha256"],
        "status": "PASS",
    }
    body["receipt_sha256"] = _sha256_bytes(canonical_json_bytes(body))
    return body


def _validate_derived_evidence(
    candidate: Mapping[str, Any],
    determinism: Mapping[str, Any],
    *,
    evidence_class: str,
) -> None:
    if (
        candidate.get("schema") != CANDIDATE_VALIDATION_EVIDENCE_SCHEMA
        or candidate.get("status") != "PASS"
        or candidate.get("evidence_class") != evidence_class
        or candidate.get("environment_make_interactions") != 0
    ):
        raise EvaluationError("candidate-validation evidence is invalid")
    _verify_self_hash(candidate, field="receipt_sha256", label="candidate-validation evidence")
    if (
        determinism.get("schema") != DETERMINISM_EVIDENCE_SCHEMA
        or determinism.get("status") != "PASS"
        or determinism.get("evidence_class") != evidence_class
        or determinism.get("environment_make_interactions") != 0
    ):
        raise EvaluationError("determinism/replay evidence is invalid")
    _verify_self_hash(determinism, field="receipt_sha256", label="determinism/replay evidence")


def _derive_gate_checks(
    request: PreflightBundleRequest,
    *,
    evidence_class: str,
    runtime: Mapping[str, JSONValue],
    source_identity: Mapping[str, Any],
    build_receipt: Mapping[str, Any],
    package_manifest: Mapping[str, Any],
    candidate_validation: Mapping[str, JSONValue],
    integrity: Mapping[str, Any],
    cold_start: Mapping[str, Any],
    profile: Mapping[str, Any],
    determinism: Mapping[str, Any],
    artifact_rows: Mapping[str, Mapping[str, JSONValue]],
) -> dict[str, dict[str, bool]]:
    """Project only typed, already-validated predicates into gate receipts."""

    from arc3.evaluation.build002_holdout import _GATE_CHECKS

    sandbox = build_receipt.get("sandbox")
    competition = package_manifest.get("competition")
    payload = package_manifest.get("payload")
    source_repositories = source_identity.get("repositories")
    blocked = source_identity.get("blocked_external")
    integrity_checks = integrity.get("checks")
    finding_counts = integrity.get("finding_counts")
    dependency_inventory = integrity.get("dependency_inventory")
    cold = cold_start.get("cold_start")
    notebook_entry = cold.get("notebook_entry") if isinstance(cold, dict) else None
    cold_pip = cold.get("pip") if isinstance(cold, dict) else None
    deterministic_checks = determinism.get("checks")
    runtime_lock = package_manifest.get("runtime_lock")
    submission = validate_submission_parquet(
        _package_paths(request.package_directory)["sandbox-submission"]
    )
    try:
        notices = request.third_party_notices.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:  # pragma: no cover - validated earlier
        raise EvaluationError("third-party notices became unreadable") from error

    source_boundary = (
        source_identity.get("status") == "PARTIAL" and isinstance(blocked, list) and bool(blocked)
        if evidence_class == "fixture"
        else source_identity.get("status") == "PASS" and blocked == []
    )
    safe_lifecycle = (
        isinstance(sandbox, dict)
        and sandbox.get("status") == "PASS"
        and sandbox.get("framework_fixture") is True
        and sandbox.get("agent_count") == 1
        and sandbox.get("worker_count") == 1
        and sandbox.get("max_concurrency") == 1
        and sandbox.get("orchestration") == "arc3.sequential-pinned-swarm.v1"
        and sandbox.get("production_rerun_exercised") is True
    )
    package_payload_files = payload.get("files") if isinstance(payload, dict) else None
    secret_check = (
        integrity_checks.get("secret_scan") if isinstance(integrity_checks, dict) else None
    )
    artifact_hashes_bound = all(
        isinstance(row.get("sha256"), str)
        and _HASH.fullmatch(cast(str, row["sha256"])) is not None
        and isinstance(row.get("byte_length"), int)
        and cast(int, row["byte_length"]) > 0
        for row in artifact_rows.values()
    )

    values = {
        "competition-lifecycle": {
            "competition_bounded_mode_configured": (
                runtime.get("execution_mode") == "COMPETITION_BOUNDED"
            ),
            "governor_reserve_configured": (
                runtime.get("official_total_runtime_seconds") == 32400
                and runtime.get("reserved_non_game_seconds") == 6000
                and runtime.get("minimum_fallback_seconds") == 5.0
            ),
            "offline_evaluation_configured": (
                isinstance(competition, dict)
                and competition.get("internet_enabled") is False
                and isinstance(sandbox, dict)
                and sandbox.get("network_attempts") == 0
                and sandbox.get("credentials_present") == []
            ),
            "safe_fixture_lifecycle_rehearsal_passed": safe_lifecycle,
        },
        "dependency-and-config-identity": {
            "dependency_lock_verified": (
                artifact_rows["dependency-lock"].get("sha256")
                == sha256_file(request.dependency_lock)
            ),
            "pinned_public_toolkit_identity_verified": (
                isinstance(source_repositories, list)
                and {
                    item.get("name") for item in source_repositories if isinstance(item, dict)
                }.issuperset(
                    {
                        "arcprize/ARC-AGI",
                        "arcprize/ARCEngine",
                        "arcprize/ARC-AGI-3-Agents",
                    }
                )
            ),
            "python_312_compatible": (
                isinstance(runtime_lock, dict)
                and runtime_lock.get("target") == "CPython 3.12 / Linux x86_64 / manylinux_2_28"
            ),
            "runtime_config_verified": (
                artifact_rows["competition-runtime-config"].get("sha256")
                == sha256_file(request.runtime_config)
            ),
        },
        "deterministic-startup-and-replay": {
            key: isinstance(deterministic_checks, dict) and deterministic_checks.get(key) is True
            for key in _GATE_CHECKS["deterministic-startup-and-replay"]
        },
        "frozen-source-config-artifacts": {
            "all_artifact_hashes_verified": artifact_hashes_bound,
            "configuration_identity_verified": (
                artifact_rows["competition-runtime-config"].get("sha256")
                == sha256_file(request.runtime_config)
                and artifact_rows["upstream-lock"].get("sha256")
                == sha256_file(request.upstream_lock)
            ),
            "source_identity_verified": source_boundary,
        },
        "notebook-build-and-offline-entry-point": {
            "deterministic_package_bytes_bound": (
                candidate_validation.get("candidate_sha256")
                == sha256_file(_package_paths(request.package_directory)["candidate"])
            ),
            "notebook_contract_verified": (
                build_receipt.get("notebook_sha256")
                == sha256_file(_package_paths(request.package_directory)["notebook"])
            ),
            "safe_fixture_entry_point_executed": safe_lifecycle,
            "output_structurally_valid": submission.status == "PASS",
        },
        "offline-cold-start": {
            "exact_generated_notebook_cells_executed": (
                isinstance(notebook_entry, dict)
                and notebook_entry.get("entrypoint") == "exact-generated-notebook-code-cells"
                and notebook_entry.get("exact_generated_code_cells") == 4
                and notebook_entry.get("executed") is True
            ),
            "host_site_packages_injected_false": (
                isinstance(notebook_entry, dict)
                and notebook_entry.get("host_site_pth_bridge_present") is False
                and notebook_entry.get("external_site_pth_entries") == []
                and notebook_entry.get("foreign_site_paths") == []
            ),
            "native_linux_packaged_entry_rehearsal": (
                isinstance(cold, dict)
                and cold.get("status") == "PASS"
                and cold.get("executed") is True
                and cold.get("target") == "CPython 3.12 / Linux x86_64 / manylinux_2_28"
            ),
            "network_attempts_zero": (
                isinstance(notebook_entry, dict) and notebook_entry.get("network_attempts") == 0
            ),
            "packaged_dependencies_complete": (
                isinstance(notebook_entry, dict)
                and notebook_entry.get("exact_production_requirements") is True
                and isinstance(cold_pip, dict)
                and all(
                    cold_pip.get(name) is True
                    for name in ("isolated", "no_deps", "no_index", "require_hashes")
                )
            ),
            "runtime_import_inventory_verified": (
                isinstance(notebook_entry, dict)
                and isinstance(notebook_entry.get("target_inventory_sha256"), str)
                and _HASH.fullmatch(cast(str, notebook_entry["target_inventory_sha256"]))
                is not None
            ),
            "safe_fixture_platform_disclosed": (
                isinstance(notebook_entry, dict)
                and notebook_entry.get("framework_fixture") is True
                and notebook_entry.get("platform_surface")
                == "safe-loopback-gateway-and-framework-fixture"
            ),
        },
        "official-source-identity": {
            "available_public_source_hashes_verified": (
                isinstance(source_repositories, list) and bool(source_repositories)
            ),
            "evidence_class_source_boundary_verified": source_boundary,
            "official_result_absent_prelaunch": (
                source_identity.get("official_result") is None
                and source_identity.get("public_holdout_consumed") is False
            ),
        },
        "package-and-license-inventory": {
            "candidate_archive_valid": candidate_validation.get("status") == "PASS",
            "dependency_inventory_present": (
                isinstance(dependency_inventory, list) and bool(dependency_inventory)
            ),
            "license_notices_present": all(
                marker in notices
                for marker in (
                    "# Third-party notices",
                    "Competition runtime distributions",
                    "License evidence",
                )
            ),
            "packaged_runtime_payload_present": (
                isinstance(package_payload_files, list) and bool(package_payload_files)
            ),
        },
        "secret-and-integrity-scan": {
            "blocking_findings_zero": (
                isinstance(finding_counts, dict) and finding_counts.get("blocking") == 0
            ),
            "package_only_integrity_passed": integrity.get("package_only_passed") is True,
            "secret_scan_passed": (
                isinstance(secret_check, dict) and secret_check.get("passed") is True
            ),
        },
        "submission-parquet-structure": {
            "columns_exact": submission.columns == ("row_id", "game_id", "end_of_game", "score"),
            "encoding_readable": submission.status == "PASS",
            "row_ids_unique": submission.status == "PASS",
            "row_types_valid": submission.status == "PASS",
        },
    }
    if set(values) != set(_GATE_CHECKS):
        raise EvaluationError("derived Build 002 gate roles changed")
    for role, checks in values.items():
        if set(checks) != set(_GATE_CHECKS[role]) or any(
            value is not True for value in checks.values()
        ):
            raise EvaluationError(f"derived Build 002 gate evidence is incomplete: {role}")
    return values


def _validate_static_asset_provenance(
    source_identity: Mapping[str, Any],
    games: Sequence[str],
    assets: Mapping[str, Path],
    *,
    allow_test_fixtures: bool,
) -> None:
    """Require independent official identities for every production asset byte."""

    if allow_test_fixtures:
        return
    provenance = source_identity.get("public_holdout_asset_provenance")
    if not isinstance(provenance, dict):
        raise FileNotFoundError(
            "independently pinned ten-game static asset provenance is unavailable"
        )
    source_url = provenance.get("source_url")
    rows = provenance.get("assets")
    if (
        provenance.get("schema") != "arc3.build-002.official-static-asset-provenance.v0.1"
        or provenance.get("status") != "PASS"
        or provenance.get("source_kind") != "official-static-asset-manifest"
        or not isinstance(source_url, str)
        or not source_url.startswith(
            (
                "https://github.com/arcprize/",
                "https://www.kaggle.com/competitions/arc-prize-2026-arc-agi-3/",
            )
        )
        or not isinstance(provenance.get("source_manifest_sha256"), str)
        or _HASH.fullmatch(cast(str, provenance["source_manifest_sha256"])) is None
        or not isinstance(rows, list)
    ):
        raise EvaluationError("official static-asset provenance receipt is malformed")
    by_game: dict[str, Mapping[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict) or set(row) != {
            "byte_length",
            "game_id",
            "game_version",
            "sha256",
        }:
            raise EvaluationError("official static-asset provenance row is malformed")
        game_id = row.get("game_id")
        if not isinstance(game_id, str) or game_id in by_game:
            raise EvaluationError("official static-asset provenance game IDs are invalid")
        by_game[game_id] = row
    if set(by_game) != set(games) or set(assets) != set(games):
        raise EvaluationError("official static-asset provenance game set changed")
    for game_id in games:
        path = assets[game_id]
        row = by_game[game_id]
        if (
            not path.is_file()
            or row.get("sha256") != sha256_file(path)
            or row.get("byte_length") != path.stat().st_size
            or not isinstance(row.get("game_version"), str)
            or not cast(str, row["game_version"])
        ):
            raise EvaluationError(f"official static-asset identity changed: {game_id}")


def _artifact_paths(request: PreflightBundleRequest, paths: BundlePaths) -> dict[str, Path]:
    package = _package_paths(request.package_directory)
    return {
        "agent-wrapper": paths.agent_wrapper,
        "competition-runtime-config": request.runtime_config,
        "dependency-lock": request.dependency_lock,
        "holdout-asset-inventory": paths.asset_inventory,
        "kaggle-notebook": package["notebook"],
        "offline-package-candidate": package["candidate"],
        "source-preview-contamination-receipt": request.source_preview_receipt,
        "submission-parquet": package["sandbox-submission"],
        "third-party-notices": request.third_party_notices,
        "upstream-lock": request.upstream_lock,
    }


def _evidence_paths(request: PreflightBundleRequest, paths: BundlePaths) -> dict[str, Path]:
    package = _package_paths(request.package_directory)
    return {
        "build-receipt": package["build-receipt"],
        "candidate-validation": paths.candidate_validation,
        "deterministic-replay": paths.determinism_evidence,
        "first-party-license": request.license_file,
        "integrity-scan": request.integrity_receipt,
        "native-linux-cold-start": request.native_linux_cold_start_receipt,
        "package-manifest": package["package-manifest"],
        "runtime-profile": request.runtime_profile_receipt,
        "source-identity": request.source_identity_receipt,
    }


def _file_rows(root: Path, paths: Mapping[str, Path]) -> dict[str, dict[str, JSONValue]]:
    rows: dict[str, dict[str, JSONValue]] = {}
    for role, path in sorted(paths.items()):
        resolved, relative = _inside(root, path, label=role)
        if not resolved.is_file():
            raise EvaluationError(f"Build 002 bound file is missing: {role}")
        rows[role] = {
            "byte_length": resolved.stat().st_size,
            "path": relative,
            "sha256": sha256_file(resolved),
        }
    return rows


def _write_json(path: Path, document: Mapping[str, Any]) -> None:
    write_bytes_atomic(path, canonical_json_bytes(dict(document)))


def _write_blocker(
    request: PreflightBundleRequest,
    paths: BundlePaths,
    *,
    commit: str,
    missing_assets: Sequence[str],
    evidence_rows: Mapping[str, Mapping[str, JSONValue]],
) -> BundleResult:
    state_root = request.root / "artifacts" / "build002" / "holdout-one-shot"
    forbidden = (
        state_root / "holdout-consumed.json",
        state_root / "exposure.jsonl",
        state_root / "result.json",
        state_root / "failed-attempt.json",
        state_root / "launch.json",
        state_root / "preflight.json",
        state_root / "run.lock",
    )
    if any(path.exists() for path in forbidden):
        raise EvaluationError("cannot issue a zero-consumption blocker after holdout state exists")
    body: dict[str, Any] = {
        "authority": {
            "authorized_runs_remaining": 1,
            "holdout_authority_consumed": False,
            "rerun_authorized": True,
        },
        "claim_boundary": "required static public assets unavailable; no environment opened",
        "environment_actions": 0,
        "environment_make_interactions": 0,
        "evidence_sha256": {role: row["sha256"] for role, row in sorted(evidence_rows.items())},
        "missing_asset_game_ids": list(sorted(missing_assets)),
        "reason": "exact ten-game static public assets are unavailable locally",
        "schema": PREFLIGHT_BLOCKER_SCHEMA,
        "source_commit": commit,
        "status": "BLOCKED_EXTERNAL",
    }
    body["receipt_sha256"] = _sha256_bytes(canonical_json_bytes(body))
    _write_json(paths.blocker, body)
    return BundleResult(
        status="BLOCKED_EXTERNAL",
        output_directory=request.output_directory,
        run_plan=None,
        blocker=paths.blocker,
        environment_make_interactions=0,
        holdout_authority_consumed=False,
    )


def _run_plan_document(
    request: PreflightBundleRequest,
    *,
    artifact_paths: Mapping[str, Path],
    gate_paths: Mapping[str, Path],
) -> dict[str, Any]:
    from scripts.run_build002_holdout import RUN_PLAN_SCHEMA

    def relative(path: Path, label: str) -> str:
        return _inside(request.root, path, label=label)[1]

    return {
        "artifacts": {
            role: relative(path, f"artifact:{role}")
            for role, path in sorted(artifact_paths.items())
        },
        "assets": {role: str(path.resolve()) for role, path in sorted(request.assets.items())},
        "framework_root": str(request.framework_root.resolve()),
        "gateway_host": request.gateway_host,
        "gateway_port": request.gateway_port,
        "gates": {
            role: relative(path, f"gate:{role}") for role, path in sorted(gate_paths.items())
        },
        "manifest": relative(request.manifest, "manifest"),
        "production_agent": relative(request.production_agent, "production_agent"),
        "schema": RUN_PLAN_SCHEMA,
        "seed": request.seed,
        "submission_output": str(request.submission_output.resolve()),
    }


def validate_production_evidence_rows(
    root: Path,
    evidence_rows: Mapping[str, Mapping[str, JSONValue]],
    artifact_rows: Mapping[str, Mapping[str, JSONValue]],
    *,
    gate_checks: Mapping[str, Mapping[str, JSONValue]],
) -> None:
    """Revalidate v0.2 gate evidence from the holdout arming path.

    The caller has already checked row shapes.  This function independently
    verifies the production-only semantic receipts and their cross-artifact
    identities, so hand-authored PASS booleans cannot arm the run.
    """

    if set(evidence_rows) != GATE_EVIDENCE_ROLES:
        raise EvaluationError("Build 002 gate evidence role set is incomplete")

    def path_for(row: Mapping[str, JSONValue], label: str) -> Path:
        raw = row.get("path")
        if not isinstance(raw, str):
            raise EvaluationError(f"Build 002 evidence path is malformed: {label}")
        path = (root.resolve() / raw).resolve()
        _inside(root, path, label=label)
        if (
            not path.is_file()
            or row.get("sha256") != sha256_file(path)
            or row.get("byte_length") != path.stat().st_size
        ):
            raise EvaluationError(f"Build 002 evidence identity changed: {label}")
        return path

    evidence = {role: path_for(row, role) for role, row in evidence_rows.items()}
    artifacts = {role: path_for(row, role) for role, row in artifact_rows.items()}
    resolved_root = root.resolve()
    commit = _current_commit(resolved_root, allow_test_fixtures=False)
    package_directory = evidence["build-receipt"].parent
    package = _package_paths(package_directory)
    expected_package_bindings = {
        "build-receipt": evidence["build-receipt"],
        "candidate": artifacts["offline-package-candidate"],
        "notebook": artifacts["kaggle-notebook"],
        "package-manifest": evidence["package-manifest"],
        "sandbox-submission": artifacts["submission-parquet"],
    }
    if any(
        package[role].resolve() != path.resolve()
        for role, path in expected_package_bindings.items()
    ):
        raise EvaluationError("Build 002 package evidence is split across different candidates")

    validation_request = PreflightBundleRequest(
        root=resolved_root,
        seed=0,
        manifest=resolved_root / "docs" / "evaluation" / "public-game-partitions.v0.1.json",
        assets={},
        framework_root=resolved_root,
        production_agent=artifacts["agent-wrapper"],
        gateway_host="127.0.0.1",
        gateway_port=1,
        submission_output=resolved_root / "artifacts" / "build002" / "unused-submission.parquet",
        package_directory=package_directory,
        integrity_receipt=evidence["integrity-scan"],
        runtime_profile_receipt=evidence["runtime-profile"],
        native_linux_cold_start_receipt=evidence["native-linux-cold-start"],
        source_identity_receipt=evidence["source-identity"],
        runtime_config=artifacts["competition-runtime-config"],
        dependency_lock=artifacts["dependency-lock"],
        upstream_lock=artifacts["upstream-lock"],
        source_preview_receipt=artifacts["source-preview-contamination-receipt"],
        third_party_notices=artifacts["third-party-notices"],
        license_file=evidence["first-party-license"],
        output_directory=resolved_root / "artifacts" / "build002" / "unused-preflight",
    )
    build_receipt, package_manifest, candidate = _validate_package(
        validation_request,
        commit=commit,
        allow_test_fixtures=False,
    )
    runtime, _, source_identity = _validate_runtime_and_sources(
        validation_request,
        commit=commit,
        allow_test_fixtures=False,
        validate_framework=False,
    )
    integrity = _validate_integrity(
        evidence["integrity-scan"],
        commit=commit,
        candidate=artifacts["offline-package-candidate"],
        allow_test_fixtures=False,
    )
    cold = _validate_cold_start(
        evidence["native-linux-cold-start"],
        package_paths=package,
        allow_test_fixtures=False,
    )
    profile = _validate_profile(
        evidence["runtime-profile"],
        commit=commit,
        runtime=runtime,
        allow_test_fixtures=False,
    )
    candidate_receipt = _load_object(
        evidence["candidate-validation"], label="candidate-validation evidence"
    )
    determinism = _load_object(evidence["deterministic-replay"], label="determinism evidence")
    _validate_derived_evidence(candidate_receipt, determinism, evidence_class="production")
    if candidate_receipt.get("candidate_validation") != candidate:
        raise EvaluationError("candidate-validation evidence differs from fresh validation")
    if candidate_receipt.get("candidate_sha256") != sha256_file(
        artifacts["offline-package-candidate"]
    ):
        raise EvaluationError("candidate-validation evidence binds a different candidate")
    if candidate_receipt.get("build_receipt_sha256") != sha256_file(evidence["build-receipt"]):
        raise EvaluationError("candidate-validation evidence binds a different build receipt")
    if sha256_file(evidence["first-party-license"]) != f"sha256:{MIT0_LICENSE_SHA256}":
        raise EvaluationError("gate evidence binds a non-MIT-0 first-party license")
    cold_body = cast(dict[str, Any], cold["cold_start"])
    profile_body = cast(dict[str, Any], profile["profile"])
    determinism_checks = determinism.get("checks")
    if (
        determinism.get("source_commit") != commit
        or determinism.get("cold_start_receipt_sha256")
        != sha256_file(evidence["native-linux-cold-start"])
        or determinism.get("runtime_profile_receipt_sha256")
        != sha256_file(evidence["runtime-profile"])
        or determinism.get("stable_startup_projection_sha256")
        != cast(dict[str, Any], cold_body["determinism"])["stable_projection_sha256"]
        or not isinstance(determinism_checks, dict)
        or set(determinism_checks)
        != {
            "compact_trace_retained",
            "deterministic_replay_verified",
            "deterministic_startup_verified",
            "sparse_recovery_checkpoint_verified",
        }
        or any(value is not True for value in determinism_checks.values())
        or profile_body.get("trace_replay_verified") is not True
    ):
        raise EvaluationError("gate determinism evidence does not replay to its source receipts")
    expected_gate_checks = _derive_gate_checks(
        validation_request,
        evidence_class="production",
        runtime=runtime,
        source_identity=source_identity,
        build_receipt=build_receipt,
        package_manifest=package_manifest,
        candidate_validation=candidate,
        integrity=integrity,
        cold_start=cold,
        profile=profile,
        determinism=determinism,
        artifact_rows=artifact_rows,
    )
    normalized_gate_checks = {role: dict(checks) for role, checks in sorted(gate_checks.items())}
    if normalized_gate_checks != expected_gate_checks:
        raise EvaluationError("Build 002 gate checks differ from rederived evidence predicates")


def build_preflight_bundle(
    request: PreflightBundleRequest,
    *,
    allow_test_fixtures: bool = False,
) -> BundleResult:
    """Construct a complete launch-free bundle or a zero-consumption blocker."""

    if request.output_directory.exists():
        raise EvaluationError("Build 002 preflight output directory must be fresh")
    request.output_directory.mkdir(parents=True, exist_ok=False)
    paths = bundle_paths(request)
    commit = _current_commit(request.root, allow_test_fixtures=allow_test_fixtures)
    required = {
        "dependency-lock": request.dependency_lock,
        "integrity-receipt": request.integrity_receipt,
        "license": request.license_file,
        "manifest": request.manifest,
        "native-cold-start": request.native_linux_cold_start_receipt,
        "production-agent": request.production_agent,
        "runtime-config": request.runtime_config,
        "runtime-profile": request.runtime_profile_receipt,
        "source-identity": request.source_identity_receipt,
        "source-preview": request.source_preview_receipt,
        "third-party-notices": request.third_party_notices,
        "upstream-lock": request.upstream_lock,
    }
    _require_files(required)
    if not request.package_directory.is_dir():
        raise FileNotFoundError("Build 002 package directory is unavailable")
    if not request.framework_root.is_dir():
        raise FileNotFoundError("pinned Agents framework root is unavailable")
    if request.submission_output.exists():
        raise EvaluationError("holdout submission output must be absent before execution")

    package = _package_paths(request.package_directory)
    build_receipt, package_manifest, candidate_validation = _validate_package(
        request,
        commit=commit,
        allow_test_fixtures=allow_test_fixtures,
    )
    runtime, _, source_identity = _validate_runtime_and_sources(
        request,
        commit=commit,
        allow_test_fixtures=allow_test_fixtures,
    )
    integrity = _validate_integrity(
        request.integrity_receipt,
        commit=commit,
        candidate=package["candidate"],
        allow_test_fixtures=allow_test_fixtures,
    )
    cold = _validate_cold_start(
        request.native_linux_cold_start_receipt,
        package_paths=package,
        allow_test_fixtures=allow_test_fixtures,
    )
    profile = _validate_profile(
        request.runtime_profile_receipt,
        commit=commit,
        runtime=runtime,
        allow_test_fixtures=allow_test_fixtures,
    )
    evidence_class = "fixture" if allow_test_fixtures else "production"
    candidate_evidence = _candidate_evidence(
        candidate_validation=candidate_validation,
        build_receipt_path=package["build-receipt"],
        evidence_class=evidence_class,
    )
    determinism_evidence = _determinism_evidence(
        commit=commit,
        cold_start=cold,
        cold_start_path=request.native_linux_cold_start_receipt,
        profile=profile,
        profile_path=request.runtime_profile_receipt,
        runtime=runtime,
        evidence_class=evidence_class,
    )
    _write_json(paths.candidate_validation, candidate_evidence)
    _write_json(paths.determinism_evidence, determinism_evidence)
    _validate_derived_evidence(
        candidate_evidence,
        determinism_evidence,
        evidence_class=evidence_class,
    )
    evidence_paths = _evidence_paths(request, paths)
    evidence_rows = _file_rows(request.root, evidence_paths)

    from arc3.evaluation.build002_holdout import _exact_holdout_games

    expected_games = _exact_holdout_games(request.manifest)
    unexpected_assets = sorted(set(request.assets).difference(expected_games))
    if unexpected_assets:
        raise EvaluationError("asset request expands the exact ten-game public holdout")
    missing_assets = sorted(
        game_id
        for game_id in expected_games
        if game_id not in request.assets or not request.assets[game_id].is_file()
    )
    if missing_assets:
        return _write_blocker(
            request,
            paths,
            commit=commit,
            missing_assets=missing_assets,
            evidence_rows=evidence_rows,
        )
    _validate_static_asset_provenance(
        source_identity,
        expected_games,
        request.assets,
        allow_test_fixtures=allow_test_fixtures,
    )

    from scripts.run_build002_holdout import _collector_source

    from arc3.evaluation.build002_holdout import (
        _GATE_ARTIFACT_ROLES,
        _GATE_CHECKS,
        _GATE_SCHEMAS,
        create_static_asset_inventory,
    )

    inventory = create_static_asset_inventory(request.manifest, request.assets)
    _write_json(paths.asset_inventory, inventory)
    write_bytes_atomic(paths.agent_wrapper, _collector_source(request.production_agent))
    artifact_paths = _artifact_paths(request, paths)
    artifact_rows = _file_rows(request.root, artifact_paths)
    gate_checks = _derive_gate_checks(
        request,
        evidence_class=evidence_class,
        runtime=runtime,
        source_identity=source_identity,
        build_receipt=build_receipt,
        package_manifest=package_manifest,
        candidate_validation=candidate_validation,
        integrity=integrity,
        cold_start=cold,
        profile=profile,
        determinism=determinism_evidence,
        artifact_rows=artifact_rows,
    )
    gate_paths = {role: paths.gates_directory / f"{role}.json" for role in sorted(_GATE_SCHEMAS)}
    for role, gate_path in gate_paths.items():
        receipt = {
            "artifact_sha256": {
                artifact_role: artifact_rows[artifact_role]["sha256"]
                for artifact_role in sorted(_GATE_ARTIFACT_ROLES[role])
            },
            "checks": {check: gate_checks[role][check] for check in sorted(_GATE_CHECKS[role])},
            "evidence": evidence_rows,
            "evidence_class": evidence_class,
            "schema": _GATE_SCHEMAS[role],
            "status": "PASS",
        }
        _write_json(gate_path, receipt)
    run_plan = _run_plan_document(
        request,
        artifact_paths=artifact_paths,
        gate_paths=gate_paths,
    )
    _write_json(paths.run_plan, run_plan)
    if not allow_test_fixtures:
        if _git(request.root, "status", "--porcelain", "--untracked-files=all"):
            raise EvaluationError(
                "preflight outputs are not ignored; clean freeze cannot be produced"
            )
        validate_production_evidence_rows(
            request.root,
            evidence_rows,
            artifact_rows,
            gate_checks=gate_checks,
        )
    return BundleResult(
        status="READY_NOT_ARMED" if not allow_test_fixtures else "FIXTURE_READY_NOT_ARMABLE",
        output_directory=request.output_directory,
        run_plan=paths.run_plan,
        blocker=None,
        environment_make_interactions=0,
        holdout_authority_consumed=False,
    )


__all__ = [
    "CANDIDATE_VALIDATION_EVIDENCE_SCHEMA",
    "DETERMINISM_EVIDENCE_SCHEMA",
    "GATE_EVIDENCE_ROLES",
    "GATE_SCHEMA_VERSION",
    "PREFLIGHT_BLOCKER_SCHEMA",
    "PREFLIGHT_REQUEST_SCHEMA",
    "BundlePaths",
    "BundleResult",
    "PreflightBundleRequest",
    "build_preflight_bundle",
    "bundle_paths",
    "load_preflight_bundle_request",
    "validate_production_evidence_rows",
]
