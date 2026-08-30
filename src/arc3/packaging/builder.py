"""Build a deterministic, credential-free offline Kaggle package candidate."""

from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import cast

from arc3.packaging.candidate import validate_candidate_archive
from arc3.packaging.models import BuildResult, FileRecord, PackagingError
from arc3.packaging.notebook import (
    build_kernel_metadata,
    build_notebook,
    validate_kernel_metadata,
    validate_notebook,
)
from arc3.packaging.requirements import build_linux_runtime_requirements
from arc3.packaging.sandbox import run_offline_sandbox
from arc3.packaging.sbom import build_spdx_sbom
from arc3.packaging.submission import validate_submission_parquet, write_validation_submission
from arc3.packaging.util import (
    canonical_json_bytes,
    deterministic_zip_bytes,
    sha256_bytes,
    sha256_file,
    write_bytes_atomic,
)
from arc3.types import JSONValue

_METADATA_FILES = (
    "LICENSE",
    "THIRD_PARTY_NOTICES.md",
    "pyproject.toml",
    "upstream.lock.json",
    "uv.lock",
)
_SOURCE_SUFFIXES = {".json", ".py"}
_RUNTIME_TOP_LEVEL = {
    "__init__.py",
    "adapters",
    "baseline_runner.py",
    "competition",
    "competition-runtime.v0.1.json",
    "competition-runtime.v0.2.json",
    "competition_runtime.py",
    "config.py",
    "errors.py",
    "exploration",
    "goals",
    "hypotheses",
    "memory",
    "mechanics",
    "packaging",
    "perception",
    "planning",
    "policy",
    "trace",
    "types.py",
    "world_model",
}
_BUILD_ONLY_PACKAGING_MODULES = {
    "builder.py",
    "candidate.py",
    "cold_start.py",
    "notebook.py",
    "sandbox.py",
    "sbom.py",
    "submission.py",
    "requirements.py",
    "util.py",
}
_SECRET_PATTERNS = (
    re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |PGP )?PRIVATE KEY-----"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b"),
    re.compile(r"\bKGAT_[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\bsk-(?:(?:proj|ant|svcacct)-)?[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\bAIza[0-9A-Za-z_-]{30,}\b"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{12,}\.[A-Za-z0-9_-]{12,}\.[A-Za-z0-9_-]{12,}\b"),
    re.compile(
        r"(?i)\b(?:api[_-]?key|access[_-]?token|client[_-]?secret|password)\b"
        r"\s*[:=]\s*[\"']?[A-Za-z0-9_./+=:-]{20,}[\"']?"
    ),
)
_OWNER_USERNAME = re.compile(r"^[A-Za-z0-9_-]+$")
_COMMIT = re.compile(r"^[0-9a-f]{40}$")


def _role(path: str) -> str:
    if path == "agent/my_agent.py":
        return "competition-agent-adapter"
    if path.startswith("src/arc3/packaging/"):
        return "first-party-packaging-runtime"
    if path.startswith("src/arc3/"):
        return "first-party-policy-runtime"
    return "build-and-provenance-metadata"


def _payload_path_selected(relative: str) -> bool:
    if relative in {*_METADATA_FILES, "agent/my_agent.py"}:
        return True
    path = PurePosixPath(relative)
    parts = path.parts
    if (
        len(parts) < 3
        or parts[:2] != ("src", "arc3")
        or path.suffix not in _SOURCE_SUFFIXES
        or "__pycache__" in parts
        or parts[2] not in _RUNTIME_TOP_LEVEL
    ):
        return False
    return not (
        len(parts) == 4 and parts[2] == "packaging" and parts[3] in _BUILD_ONLY_PACKAGING_MODULES
    )


def _git_bytes(repository: Path, *arguments: str) -> bytes:
    environment = {
        key: value for key, value in os.environ.items() if not key.upper().startswith("GIT_")
    }
    environment["GIT_NO_REPLACE_OBJECTS"] = "1"
    completed = subprocess.run(
        ["git", "--no-replace-objects", "-C", str(repository.resolve()), *arguments],
        check=False,
        capture_output=True,
        env=environment,
    )
    if completed.returncode != 0:
        stderr = completed.stderr.decode("utf-8", errors="replace").strip()
        raise PackagingError(
            f"git {' '.join(arguments)} failed with exit {completed.returncode}: {stderr}"
        )
    return completed.stdout


def _git_payload_members(repository: Path, source_commit: str) -> dict[str, bytes]:
    """Read the exact selected payload bytes from one Git tree, not the worktree."""

    raw_tree = _git_bytes(repository, "ls-tree", "-r", "-z", source_commit)
    selected: dict[str, tuple[str, str]] = {}
    for raw_entry in raw_tree.split(b"\0"):
        if not raw_entry:
            continue
        metadata, separator, raw_path = raw_entry.partition(b"\t")
        fields = metadata.split()
        if not separator or len(fields) != 3:
            raise PackagingError("git returned a malformed tree entry")
        try:
            relative = raw_path.decode("utf-8", errors="strict")
            mode, object_type, object_id = (field.decode("ascii") for field in fields)
        except UnicodeDecodeError as error:
            raise PackagingError("package source tree contains a non-portable path") from error
        if not _payload_path_selected(relative):
            continue
        if object_type != "blob" or mode not in {"100644", "100755"}:
            raise PackagingError(f"package source is not a regular Git blob: {relative}")
        if relative in selected:
            raise PackagingError(f"duplicate package source path in Git tree: {relative}")
        selected[relative] = (object_id, mode)
    missing_metadata = sorted({*_METADATA_FILES, "agent/my_agent.py"}.difference(selected))
    if missing_metadata:
        raise PackagingError(
            "Git tree omits required package inputs: " + ", ".join(missing_metadata)
        )
    return {
        relative: _git_bytes(repository, "cat-file", "blob", object_id)
        for relative, (object_id, _mode) in sorted(selected.items())
    }


def _live_payload_members(repository: Path) -> dict[str, bytes]:
    source_root = repository / "src" / "arc3"
    agent_path = repository / "agent" / "my_agent.py"
    if not source_root.is_dir() or not agent_path.is_file():
        raise PackagingError("repository is missing src/arc3 or agent/my_agent.py")
    paths = [
        path
        for path in source_root.rglob("*")
        if path.is_file()
        and path.suffix in _SOURCE_SUFFIXES
        and "__pycache__" not in path.parts
        and path.relative_to(source_root).parts[0] in _RUNTIME_TOP_LEVEL
        and not (
            path.parent == source_root / "packaging" and path.name in _BUILD_ONLY_PACKAGING_MODULES
        )
    ]
    paths.append(agent_path)
    for relative in _METADATA_FILES:
        path = repository / relative
        if not path.is_file():
            raise PackagingError(f"required package metadata is missing: {relative}")
        paths.append(path)

    members: dict[str, bytes] = {}
    for path in sorted(paths, key=lambda candidate: candidate.relative_to(repository).as_posix()):
        if path.is_symlink():
            raise PackagingError(f"symbolic links are not permitted in the package: {path}")
        relative = path.relative_to(repository).as_posix()
        members[relative] = path.read_bytes()
    return members


def _collect_payload(
    repository: Path,
    *,
    source_commit: str,
    exact_commit: bool,
) -> tuple[dict[str, bytes], tuple[FileRecord, ...], dict[str, JSONValue]]:
    members = (
        _git_payload_members(repository, source_commit)
        if exact_commit
        else _live_payload_members(repository)
    )
    records: list[FileRecord] = []
    for relative, content in sorted(members.items()):
        records.append(
            FileRecord(
                path=relative,
                sha256=sha256_bytes(content),
                size_bytes=len(content),
                role=_role(relative),
            )
        )
    required_runtime_members = {
        "src/arc3/competition-runtime.v0.1.json",
        "src/arc3/competition-runtime.v0.2.json",
        "src/arc3/competition/__init__.py",
        "src/arc3/competition/governor.py",
        "src/arc3/competition_runtime.py",
    }
    missing_runtime_members = required_runtime_members.difference(members)
    if missing_runtime_members:
        raise PackagingError(
            "competition runtime payload is incomplete: "
            + ", ".join(sorted(missing_runtime_members))
        )
    record_projection = [record.to_dict() for record in records]
    record_document = cast(dict[str, JSONValue], {"files": record_projection})
    source_identity: dict[str, JSONValue] = {
        "exact_git_commit_bound": exact_commit,
        "git_commit": source_commit,
        "member_count": len(records),
        "member_records_sha256": sha256_bytes(canonical_json_bytes(record_document)),
        "mode": "git-blob-exact" if exact_commit else "live-worktree-preacceptance",
    }
    return members, tuple(records), source_identity


def collect_git_payload(
    repository: Path,
    source_commit: str,
) -> tuple[dict[str, bytes], tuple[FileRecord, ...], dict[str, JSONValue]]:
    """Project the exact competition payload from one immutable Git commit."""

    resolved = repository.resolve()
    if _COMMIT.fullmatch(source_commit) is None:
        raise PackagingError("payload source commit must be a full lowercase Git SHA")
    if Path(_git_command(resolved, "rev-parse", "--show-toplevel")).resolve() != resolved:
        raise PackagingError("payload source is not the exact Git top level")
    literal_commit = _git_command(
        resolved,
        "rev-parse",
        "--verify",
        f"{source_commit}^{{commit}}",
    )
    if literal_commit != source_commit:
        raise PackagingError("payload source commit did not resolve literally")
    return _collect_payload(
        resolved,
        source_commit=source_commit,
        exact_commit=True,
    )


def scan_payload_for_secrets(members: dict[str, bytes]) -> tuple[str, ...]:
    findings: list[str] = []
    forbidden_names = {".env", "kaggle.json", "credentials.json"}
    forbidden_suffixes = {".key", ".p12", ".pem", ".pfx"}
    for path, content in sorted(members.items()):
        name = Path(path).name.lower()
        if name in forbidden_names or Path(name).suffix in forbidden_suffixes:
            findings.append(f"forbidden credential-bearing filename: {path}")
            continue
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError:
            continue
        for pattern in _SECRET_PATTERNS:
            if pattern.search(text):
                findings.append(f"high-confidence secret pattern in {path}")
                break
    return tuple(findings)


def _git_command(repository: Path, *arguments: str) -> str:
    environment = {
        key: value for key, value in os.environ.items() if not key.upper().startswith("GIT_")
    }
    environment["GIT_NO_REPLACE_OBJECTS"] = "1"
    completed = subprocess.run(
        ["git", "--no-replace-objects", "-C", str(repository.resolve()), *arguments],
        check=False,
        capture_output=True,
        env=environment,
        text=True,
    )
    if completed.returncode != 0:
        raise PackagingError(
            f"git {' '.join(arguments)} failed with exit {completed.returncode}: "
            f"{completed.stderr.strip()}"
        )
    return completed.stdout.strip()


def _source_timestamp(repository: Path, source_commit: str) -> str:
    raw = _git_command(repository, "show", "-s", "--format=%cI", source_commit)
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError as error:
        raise PackagingError(f"git returned an invalid commit timestamp: {raw!r}") from error
    return parsed.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _upstream_summary(raw_bytes: bytes) -> list[JSONValue]:
    try:
        raw = json.loads(raw_bytes)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise PackagingError(f"cannot read upstream.lock.json: {error}") from error
    if not isinstance(raw, dict) or not isinstance(raw.get("repositories"), list):
        raise PackagingError("upstream.lock.json has no repository array")
    result: list[JSONValue] = []
    for item in raw["repositories"]:
        if not isinstance(item, dict):
            raise PackagingError("upstream repository lock entry must be an object")
        name = item.get("name")
        commit = item.get("commit")
        license_id = item.get("license")
        if not all(isinstance(value, str) for value in (name, commit, license_id)):
            raise PackagingError("upstream repository lock entry is incomplete")
        result.append(
            {
                "commit": cast(str, commit),
                "license": cast(str, license_id),
                "name": cast(str, name),
            }
        )
    return result


def _write_json(path: Path, document: dict[str, JSONValue]) -> bytes:
    encoded = canonical_json_bytes(document)
    write_bytes_atomic(path, encoded)
    return encoded


def build_kaggle_candidate(
    repository: Path,
    output_directory: Path,
    *,
    owner_username: str = "OWNER_USERNAME",
    sandbox_timeout_seconds: float = 120.0,
    allow_dirty_preacceptance: bool = False,
) -> BuildResult:
    """Build, sandbox, and validate a deterministic offline submission candidate."""

    repository = repository.resolve()
    output_directory = output_directory.resolve()
    if not _OWNER_USERNAME.fullmatch(owner_username):
        raise PackagingError("owner_username may contain only letters, digits, underscore, or dash")
    if sandbox_timeout_seconds <= 0:
        raise PackagingError("sandbox timeout must be positive")
    if output_directory.exists():
        raise PackagingError(
            f"output directory must be fresh and must not already exist: {output_directory}"
        )

    top_level = Path(_git_command(repository, "rev-parse", "--show-toplevel")).resolve()
    if top_level != repository:
        raise PackagingError(f"repository is not the exact Git top level: {repository}")

    source_commit = _git_command(repository, "rev-parse", "HEAD")
    source_dirty = bool(_git_command(repository, "status", "--short", "--untracked-files=normal"))
    if source_dirty and not allow_dirty_preacceptance:
        raise PackagingError(
            "refusing to claim PACKAGING_PASS from a dirty source tree; commit the candidate "
            "or pass allow_dirty_preacceptance for an explicitly non-final rehearsal"
        )
    build_status = "PACKAGING_PREACCEPTANCE" if source_dirty else "PACKAGING_PASS"
    source_timestamp = _source_timestamp(repository, source_commit)
    payload_members, payload_records, payload_source_identity = _collect_payload(
        repository,
        source_commit=source_commit,
        exact_commit=not source_dirty,
    )
    secret_findings = scan_payload_for_secrets(payload_members)
    if secret_findings:
        raise PackagingError("package secret scan failed: " + "; ".join(secret_findings))
    payload_bytes = deterministic_zip_bytes(payload_members)
    payload_sha256 = sha256_bytes(payload_bytes)
    lock_bytes = payload_members["uv.lock"]
    schema_bytes = payload_members["src/arc3/packaging/submission-schema.v0.1.json"]
    upstream_summary = _upstream_summary(payload_members["upstream.lock.json"])
    with tempfile.TemporaryDirectory(prefix="arc3-source-inputs-") as source_inputs:
        lock_snapshot = Path(source_inputs) / "uv.lock"
        write_bytes_atomic(lock_snapshot, lock_bytes)
        runtime_requirements, wheel_manifest_document, runtime_wheels = (
            build_linux_runtime_requirements(lock_snapshot)
        )
        sbom_document = build_spdx_sbom(
            lock_snapshot,
            runtime_wheels=runtime_wheels,
            payload_sha256=payload_sha256,
            requirements_sha256=sha256_bytes(runtime_requirements),
            wheel_manifest_sha256=sha256_bytes(canonical_json_bytes(wheel_manifest_document)),
            source_commit=source_commit,
            source_timestamp=source_timestamp,
        )
    runtime_requirements_sha256 = sha256_bytes(runtime_requirements)
    wheel_manifest_bytes = canonical_json_bytes(wheel_manifest_document)
    wheel_manifest_sha256 = sha256_bytes(wheel_manifest_bytes)

    try:
        output_directory.mkdir(parents=True, exist_ok=False)
    except FileExistsError as error:
        raise PackagingError(
            "output directory appeared during the build; refusing to mix artifacts"
        ) from error
    payload_path = output_directory / "arc3-first-party.zip"
    notebook_path = output_directory / "arc3-submission.ipynb"
    metadata_path = output_directory / "kernel-metadata.json"
    manifest_path = output_directory / "package-manifest.json"
    sbom_path = output_directory / "sbom.spdx.json"
    schema_path = output_directory / "submission-schema.v0.1.json"
    requirements_path = output_directory / "runtime-requirements-linux-cp312.txt"
    wheel_manifest_path = output_directory / "runtime-wheels-linux-cp312.json"
    candidate_path = output_directory / "arc3-kaggle-candidate.zip"
    receipt_path = output_directory / "build-receipt.json"
    sandbox_submission = output_directory / "offline-sandbox" / "submission.parquet"
    write_bytes_atomic(payload_path, payload_bytes)
    write_bytes_atomic(requirements_path, runtime_requirements)
    write_bytes_atomic(wheel_manifest_path, wheel_manifest_bytes)

    with tempfile.TemporaryDirectory(prefix="arc3-parquet-build-") as temporary:
        validation_source = Path(temporary) / "submission.parquet"
        write_validation_submission(validation_source)
        validation_parquet = validation_source.read_bytes()

    notebook_document = build_notebook(
        payload=payload_bytes,
        payload_sha256=payload_sha256,
        runtime_requirements=runtime_requirements,
        requirements_sha256=runtime_requirements_sha256,
        validation_parquet=validation_parquet,
        source_commit=source_commit,
    )
    validate_notebook(notebook_document)
    notebook_bytes = _write_json(notebook_path, notebook_document)
    metadata_document = build_kernel_metadata(owner_username=owner_username)
    validate_kernel_metadata(metadata_document)
    metadata_bytes = _write_json(metadata_path, metadata_document)

    try:
        schema_document = json.loads(schema_bytes)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise PackagingError(f"submission schema is invalid JSON: {error}") from error
    if not isinstance(schema_document, dict):
        raise PackagingError("submission schema must be a JSON object")
    write_bytes_atomic(schema_path, schema_bytes)

    sbom_bytes = _write_json(sbom_path, sbom_document)
    artifact_records = (
        FileRecord(
            path=payload_path.name,
            sha256=payload_sha256,
            size_bytes=len(payload_bytes),
            role="embedded-first-party-payload",
        ),
        FileRecord(
            path=notebook_path.name,
            sha256=sha256_bytes(notebook_bytes),
            size_bytes=len(notebook_bytes),
            role="kaggle-code-artifact",
        ),
        FileRecord(
            path=metadata_path.name,
            sha256=sha256_bytes(metadata_bytes),
            size_bytes=len(metadata_bytes),
            role="kaggle-kernel-metadata",
        ),
        FileRecord(
            path=sbom_path.name,
            sha256=sha256_bytes(sbom_bytes),
            size_bytes=len(sbom_bytes),
            role="runtime-software-bill-of-materials",
        ),
        FileRecord(
            path=requirements_path.name,
            sha256=runtime_requirements_sha256,
            size_bytes=len(runtime_requirements),
            role="exact-linux-cpython312-runtime-requirements",
        ),
        FileRecord(
            path=wheel_manifest_path.name,
            sha256=wheel_manifest_sha256,
            size_bytes=len(wheel_manifest_bytes),
            role="exact-linux-cpython312-wheel-identities",
        ),
        FileRecord(
            path=schema_path.name,
            sha256=sha256_bytes(schema_bytes),
            size_bytes=len(schema_bytes),
            role="pinned-public-submission-contract",
        ),
    )
    sandbox_receipt = run_offline_sandbox(
        notebook_path,
        sandbox_submission,
        payload_sha256=payload_sha256,
        requirements_sha256=runtime_requirements_sha256,
        timeout_seconds=sandbox_timeout_seconds,
    )
    validation_receipt = validate_submission_parquet(sandbox_submission)
    if sandbox_receipt.output_sha256 != validation_receipt.artifact_sha256:
        raise PackagingError("sandbox and schema validators disagree on output artifact identity")

    manifest_document: dict[str, JSONValue] = {
        "artifacts": [record.to_dict() for record in artifact_records],
        "competition": {
            "accelerator": "cpu",
            "credential_requirement": "none; public local-gateway sentinel only",
            "framework_operation_mode": "online transport to Kaggle-local gateway only",
            "hosted_inference": False,
            "internet_enabled": False,
            "official_submission_performed": False,
            "submission_type": "notebook",
        },
        "evidence_label": "synthetic",
        "human_gates": [
            "accept Kaggle or ARC Prize terms",
            "alter or replace the owner-approved first-party license",
            "upload or submit the candidate",
        ],
        "offline_rehearsal": {
            "competition_gateway_available": False,
            "dependency_install": "no-index, no-deps, require-hashes through rerun branch",
            "receipt": sandbox_receipt.to_dict(),
            "scope": (
                "safe wheel/framework/gateway fixtures; exact Linux lock statically linked; "
                "private Kaggle sidecar unavailable"
            ),
        },
        "payload": {
            "archive": payload_path.name,
            "files": [record.to_dict() for record in payload_records],
            "sha256": payload_sha256,
            "size_bytes": len(payload_bytes),
            "source_identity": payload_source_identity,
        },
        "schema": "arc3.kaggle-package-manifest.v0.1",
        "secret_scan": {
            "findings": [],
            "scopes": ["payload-before-archive", "candidate-members-before-archive"],
            "status": "PASS",
        },
        "source": {
            "git_commit": source_commit,
            "git_commit_timestamp": source_timestamp,
            "git_dirty": source_dirty,
            "repository": "https://github.com/Grativy6/ARC3",
        },
        "submission_contract": {
            "columns": list(("row_id", "game_id", "end_of_game", "score")),
            "official_gateway_authoritative": True,
            "public_source": (
                "arcprize/ARC-AGI-3-Kaggle-Starter@eeb1535404f321d280a8f9194bbc1d7aca5f05fc"
            ),
        },
        "upstreams": upstream_summary,
        "build_status": build_status,
        "runtime_lock": {
            "requirements": requirements_path.name,
            "requirements_sha256": runtime_requirements_sha256,
            "target": "CPython 3.12 / Linux x86_64 / manylinux_2_28",
            "wheel_manifest": wheel_manifest_path.name,
            "wheel_manifest_sha256": wheel_manifest_sha256,
        },
    }
    manifest_bytes = _write_json(manifest_path, manifest_document)

    candidate_members = {
        payload_path.name: payload_bytes,
        notebook_path.name: notebook_bytes,
        metadata_path.name: metadata_bytes,
        manifest_path.name: manifest_bytes,
        sbom_path.name: sbom_bytes,
        requirements_path.name: runtime_requirements,
        schema_path.name: schema_bytes,
        wheel_manifest_path.name: wheel_manifest_bytes,
    }
    candidate_secret_findings = scan_payload_for_secrets(candidate_members)
    if candidate_secret_findings:
        raise PackagingError(
            "final candidate secret rescan failed: " + "; ".join(candidate_secret_findings)
        )
    candidate_bytes = deterministic_zip_bytes(candidate_members)
    write_bytes_atomic(candidate_path, candidate_bytes)
    candidate_validation = validate_candidate_archive(candidate_path)

    sandbox_receipt_sha256 = sha256_bytes(canonical_json_bytes(sandbox_receipt.to_dict()))
    receipt_core: dict[str, JSONValue] = {
        "candidate_sha256": sha256_bytes(candidate_bytes),
        "candidate_validation": candidate_validation,
        "evidence_label": "synthetic",
        "manifest_sha256": sha256_bytes(manifest_bytes),
        "notebook_sha256": sha256_bytes(notebook_bytes),
        "official_submission_performed": False,
        "payload_sha256": payload_sha256,
        "runtime_requirements_sha256": runtime_requirements_sha256,
        "sandbox": sandbox_receipt.to_dict(),
        "sandbox_receipt_sha256": sandbox_receipt_sha256,
        "sandbox_output_sha256": sandbox_receipt.output_sha256,
        "sbom_sha256": sha256_bytes(sbom_bytes),
        "schema": "arc3.kaggle-build-receipt.v0.1",
        "status": build_status,
        "validation": validation_receipt.to_dict(),
        "wheel_manifest_sha256": wheel_manifest_sha256,
    }
    receipt_document = dict(receipt_core)
    receipt_document["receipt_sha256"] = sha256_bytes(canonical_json_bytes(receipt_core))
    _write_json(receipt_path, receipt_document)

    return BuildResult(
        output_directory=output_directory,
        candidate_archive=candidate_path,
        notebook=notebook_path,
        kernel_metadata=metadata_path,
        payload_archive=payload_path,
        package_manifest=manifest_path,
        sbom=sbom_path,
        submission_schema=schema_path,
        runtime_requirements=requirements_path,
        wheel_manifest=wheel_manifest_path,
        build_receipt=receipt_path,
        sandbox_submission=sandbox_submission,
        candidate_sha256=sha256_file(candidate_path),
        notebook_sha256=sha256_file(notebook_path),
        payload_sha256=sha256_file(payload_path),
        manifest_sha256=sha256_file(manifest_path),
        sbom_sha256=sha256_file(sbom_path),
        runtime_requirements_sha256=sha256_file(requirements_path),
        wheel_manifest_sha256=sha256_file(wheel_manifest_path),
        status=build_status,
        validation=validation_receipt,
        sandbox=sandbox_receipt,
    )


__all__ = ["build_kaggle_candidate", "collect_git_payload", "scan_payload_for_secrets"]
