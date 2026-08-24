"""Typed packaging records kept independent from Kaggle credentials."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from arc3.types import JSONValue

PYTHON_NETWORK_ENFORCEMENT = (
    "Python-level socket guard: loopback-only connect, connect_ex, create_connection, sendto, "
    "and sendmsg; getaddrinfo permits numeric loopback only; gethostbyname, gethostbyname_ex, "
    "gethostbyaddr, and getnameinfo are denied; OS-level network containment is absent."
)


class PackagingError(RuntimeError):
    """Raised when a candidate cannot be built or validated safely."""


class ExternalSurfaceUnavailableError(PackagingError):
    """A required competition-local service could not be reached."""


@dataclass(frozen=True, slots=True)
class FileRecord:
    """Content identity for one package member."""

    path: str
    sha256: str
    size_bytes: int
    role: str

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "path": self.path,
            "role": self.role,
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
        }


@dataclass(frozen=True, slots=True)
class ValidationReceipt:
    """Measured result from one local output-artifact validation."""

    status: str
    validation_level: str
    artifact_sha256: str
    artifact_size_bytes: int
    columns: tuple[str, ...]
    rows: int
    parquet_engine: str
    limitations: tuple[str, ...]

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "artifact_sha256": self.artifact_sha256,
            "artifact_size_bytes": self.artifact_size_bytes,
            "columns": list(self.columns),
            "limitations": list(self.limitations),
            "parquet_engine": self.parquet_engine,
            "rows": self.rows,
            "status": self.status,
            "validation_level": self.validation_level,
        }


@dataclass(frozen=True, slots=True)
class SandboxReceipt:
    """Result of executing the generated notebook in a network-blocked subprocess."""

    status: str
    notebook_entrypoint: str
    platform_surface: str
    runtime_dependency_surface: str
    exact_generated_code_cells: int
    exact_production_requirements: bool
    host_site_pth_bridge_present: bool
    agent_action_cycle_status: str
    agent_consequence_state: str
    agent_cycle_actions: tuple[str, str]
    network_attempts: int
    network_enforcement: str
    credentials_present: tuple[str, ...]
    imported_agent_path: str
    imported_arc3_path: str
    output_sha256: str
    output_size_bytes: int
    notebook_sha256: str
    payload_sha256: str
    requirements_sha256: str
    rehearsal_requirements_sha256: str
    installed_wheel_sha256: tuple[str, ...]
    framework_commit: str
    framework_identity: str
    framework_fixture: bool
    agent_count: int
    worker_count: int
    max_concurrency: int
    orchestration: str
    production_rerun_exercised: bool
    dependency_install_status: str
    gateway_connections: int
    secret_scan_status: str
    limitations: tuple[str, ...]

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "exact_generated_code_cells": self.exact_generated_code_cells,
            "exact_production_requirements": self.exact_production_requirements,
            "host_site_pth_bridge_present": self.host_site_pth_bridge_present,
            "notebook_entrypoint": self.notebook_entrypoint,
            "platform_surface": self.platform_surface,
            "runtime_dependency_surface": self.runtime_dependency_surface,
            "agent_action_cycle_status": self.agent_action_cycle_status,
            "agent_consequence_state": self.agent_consequence_state,
            "agent_cycle_actions": list(self.agent_cycle_actions),
            "credentials_present": list(self.credentials_present),
            "imported_agent_path": self.imported_agent_path,
            "imported_arc3_path": self.imported_arc3_path,
            "dependency_install_status": self.dependency_install_status,
            "framework_commit": self.framework_commit,
            "framework_identity": self.framework_identity,
            "framework_fixture": self.framework_fixture,
            "agent_count": self.agent_count,
            "gateway_connections": self.gateway_connections,
            "installed_wheel_sha256": list(self.installed_wheel_sha256),
            "limitations": list(self.limitations),
            "network_attempts": self.network_attempts,
            "network_enforcement": self.network_enforcement,
            "notebook_sha256": self.notebook_sha256,
            "max_concurrency": self.max_concurrency,
            "orchestration": self.orchestration,
            "output_sha256": self.output_sha256,
            "output_size_bytes": self.output_size_bytes,
            "payload_sha256": self.payload_sha256,
            "production_rerun_exercised": self.production_rerun_exercised,
            "requirements_sha256": self.requirements_sha256,
            "rehearsal_requirements_sha256": self.rehearsal_requirements_sha256,
            "secret_scan_status": self.secret_scan_status,
            "status": self.status,
            "worker_count": self.worker_count,
        }


@dataclass(frozen=True, slots=True)
class BuildResult:
    """Paths and identities emitted by one deterministic package build."""

    output_directory: Path
    candidate_archive: Path
    notebook: Path
    kernel_metadata: Path
    payload_archive: Path
    package_manifest: Path
    sbom: Path
    submission_schema: Path
    runtime_requirements: Path
    wheel_manifest: Path
    build_receipt: Path
    sandbox_submission: Path
    candidate_sha256: str
    notebook_sha256: str
    payload_sha256: str
    manifest_sha256: str
    sbom_sha256: str
    runtime_requirements_sha256: str
    wheel_manifest_sha256: str
    status: str
    validation: ValidationReceipt
    sandbox: SandboxReceipt

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "artifacts": {
                "build_receipt": self.build_receipt.name,
                "candidate_archive": self.candidate_archive.name,
                "kernel_metadata": self.kernel_metadata.name,
                "notebook": self.notebook.name,
                "package_manifest": self.package_manifest.name,
                "payload_archive": self.payload_archive.name,
                "runtime_requirements": self.runtime_requirements.name,
                "sandbox_submission": self.sandbox_submission.relative_to(
                    self.output_directory
                ).as_posix(),
                "sbom": self.sbom.name,
                "submission_schema": self.submission_schema.name,
                "wheel_manifest": self.wheel_manifest.name,
            },
            "hashes": {
                "candidate": self.candidate_sha256,
                "manifest": self.manifest_sha256,
                "notebook": self.notebook_sha256,
                "payload": self.payload_sha256,
                "sbom": self.sbom_sha256,
                "runtime_requirements": self.runtime_requirements_sha256,
                "wheel_manifest": self.wheel_manifest_sha256,
            },
            "output_directory": self.output_directory.as_posix(),
            "sandbox": self.sandbox.to_dict(),
            "schema": "arc3.kaggle-build-result.v0.1",
            "status": self.status,
            "validation": self.validation.to_dict(),
        }
