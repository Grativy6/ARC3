"""Launch-free Build 002 production-preflight bundle tests."""

from __future__ import annotations

import json
import os
import shutil
import stat
import uuid
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any

import pytest
from scripts.prepare_build002_preflight import _state_is_pristine

import arc3.evaluation.build002_holdout as build002_holdout
import arc3.evaluation.build002_preflight as preflight_module
from arc3.competition_runtime import load_competition_runtime
from arc3.errors import EvaluationError
from arc3.evaluation.artifacts import canonical_json_bytes, sha256_file
from arc3.evaluation.build002_preflight import (
    GATE_EVIDENCE_ROLES,
    PREFLIGHT_BLOCKER_SCHEMA,
    PREFLIGHT_REQUEST_SCHEMA,
    PreflightBundleRequest,
    _validate_cold_start,
    _validate_runtime_and_sources,
    _validate_static_asset_provenance,
    build_preflight_bundle,
    load_preflight_bundle_request,
)
from arc3.evaluation.public import PublicPartitionManifest
from arc3.packaging.builder import build_kaggle_candidate
from arc3.packaging.runtime_launcher import SAFE_FRAMEWORK_FIXTURE_IDENTITY
from arc3.packaging.util import sha256_bytes, write_bytes_atomic
from arc3.types import JSONValue

REPOSITORY = Path(__file__).resolve().parents[2]
MANIFEST = REPOSITORY / "docs" / "evaluation" / "public-game-partitions.v0.1.json"


@pytest.mark.parametrize(
    "state_name",
    (
        "exposure.jsonl",
        "failed-attempt.json",
        "holdout-consumed.json",
        "launch.json",
        "preflight.json",
        "result.json",
        "run.lock",
    ),
)
def test_preflight_stop_requires_pristine_canonical_holdout_state(
    tmp_path: Path, state_name: str
) -> None:
    state = tmp_path / "artifacts" / "build002" / "holdout-one-shot"
    state.mkdir(parents=True)
    assert _state_is_pristine(tmp_path)
    (state / state_name).touch()
    assert not _state_is_pristine(tmp_path)


def _sealed(document: Mapping[str, Any]) -> dict[str, Any]:
    result = dict(document)
    result["receipt_sha256"] = sha256_bytes(canonical_json_bytes(result))
    return result


def _write_json(path: Path, document: Mapping[str, Any]) -> None:
    write_bytes_atomic(path, canonical_json_bytes(dict(document)))


@pytest.fixture(scope="module")
def fixture_root() -> Iterator[Path]:
    parent = REPOSITORY / "artifacts" / "test-tmp" / "build002-preflight"
    parent.mkdir(parents=True, exist_ok=True)
    root = parent / uuid.uuid4().hex
    root.mkdir()
    try:
        yield root
    finally:

        def remove_readonly(function: Any, path: str, _error: BaseException) -> None:
            os.chmod(path, stat.S_IWRITE)
            function(path)

        shutil.rmtree(root, onexc=remove_readonly)


@pytest.fixture(scope="module")
def package_directory(fixture_root: Path) -> Path:
    result = build_kaggle_candidate(
        REPOSITORY,
        fixture_root / "package",
        allow_dirty_preacceptance=True,
    )
    assert result.status in {"PACKAGING_PASS", "PACKAGING_PREACCEPTANCE"}
    return result.output_directory


def _framework_fixture(root: Path) -> Path:
    framework = root / "framework"
    agents = framework / "agents"
    agents.mkdir(parents=True)
    (framework / ".arc3-safe-fixture").write_text(
        SAFE_FRAMEWORK_FIXTURE_IDENTITY,
        encoding="utf-8",
    )
    (agents / "agent.py").write_text("class Agent: pass\n", encoding="utf-8")
    (agents / "swarm.py").write_text("class Swarm: pass\n", encoding="utf-8")
    return framework


def _source_identity_fixture(path: Path) -> None:
    upstream = json.loads((REPOSITORY / "upstream.lock.json").read_text(encoding="utf-8"))
    heads = upstream["build_002_refresh"]["public_repository_heads"]
    _write_json(
        path,
        {
            "blocked_external": [
                "exact private competition wheel set",
                "exact private framework input",
                "exact private gateway",
                "exact private scorer",
                "independently pinned ten-game static asset provenance",
            ],
            "fixture": True,
            "official_result": None,
            "project_lock": {"sha256": sha256_file(REPOSITORY / "upstream.lock.json")},
            "public_holdout_consumed": False,
            "repositories": [
                {"commit": commit, "name": name} for name, commit in sorted(heads.items())
            ],
            "schema": "arc3.build-002.official-source-identities.v0.1",
            "status": "PARTIAL",
        },
    )


def _runtime_profile_fixture(path: Path, *, commit: str) -> None:
    runtime = load_competition_runtime(
        REPOSITORY / "src" / "arc3" / "competition-runtime.v0.2.json"
    )
    policy = {
        "allocator_tracing_enabled": runtime.allocator_tracing_enabled,
        "automatic_per_action_checkpoints": runtime.automatic_per_action_checkpoints,
        "compact_trace_capacity": runtime.compact_trace_capacity,
        "sparse_checkpoint_interval_actions": runtime.sparse_checkpoint_interval_actions,
    }
    _write_json(
        path,
        _sealed(
            {
                "competition_runtime": runtime.to_dict(),
                "competition_runtime_match": True,
                "fixture": True,
                "git_commit": commit,
                "profile": {
                    "budget_assessment": {"fixture_budget": True},
                    "controller_execution": {
                        "execution_mode": "COMPETITION_BOUNDED",
                        "runtime_policy": policy,
                    },
                    "required_predicates": {"fixture_replay": True},
                    "trace_replay_verified": True,
                    "verified": True,
                },
                "schema": "arc3.stage16.profile.v0.1",
                "source_identity": {"verified": True},
                "startup": {"execution_mode": "COMPETITION_BOUNDED"},
                "status": "PASS",
                "verified": True,
            }
        ),
    )


def _cold_start_fixture(path: Path, package: Path) -> None:
    submission = package / "offline-sandbox" / "submission.parquet"
    notebook_sha256 = sha256_file(package / "arc3-submission.ipynb")
    payload_sha256 = sha256_file(package / "arc3-first-party.zip")
    requirements_sha256 = sha256_file(package / "runtime-requirements-linux-cp312.txt")
    _write_json(
        path,
        {
            "cold_start": {
                "determinism": {
                    "notebook_entry_projection_sha256": sha256_bytes(b"fixture-notebook-entry"),
                    "notebook_entry_repetitions": 1,
                    "repetitions": 2,
                    "stable_projection_sha256": sha256_bytes(b"fixture-stable-startup"),
                    "startup_projection_repetitions": 2,
                },
                "executed": True,
                "host": {
                    "implementation": "CPython",
                    "machine": "x86_64",
                    "python": "3.12.14",
                    "system": "Linux",
                },
                "identities": {
                    "manifest_sha256": sha256_file(package / "runtime-wheels-linux-cp312.json"),
                    "notebook_sha256": notebook_sha256,
                    "package_manifest_sha256": sha256_file(package / "package-manifest.json"),
                    "payload_sha256": payload_sha256,
                    "requirements_sha256": requirements_sha256,
                },
                "notebook_entry": {
                    "entrypoint": "exact-generated-notebook-code-cells",
                    "exact_generated_code_cells": 4,
                    "exact_production_requirements": True,
                    "executed": True,
                    "external_site_pth_entries": [],
                    "foreign_site_paths": [],
                    "framework_fixture": True,
                    "host_site_pth_bridge_present": False,
                    "kaggle_competition_rerun_branch": True,
                    "network_attempts": 0,
                    "network_attempt_scope": "non-loopback Python socket attempts",
                    "notebook_sha256": notebook_sha256,
                    "output_validation": {
                        "artifact_sha256": sha256_file(submission),
                        "parquet_engine": "pyarrow==21.0.0",
                        "status": "PASS",
                        "validation_level": "pinned-public-schema",
                    },
                    "payload_sha256": payload_sha256,
                    "peak_memory_bytes": 1024,
                    "platform_surface": "safe-loopback-gateway-and-framework-fixture",
                    "repetitions": 1,
                    "requirements_sha256": requirements_sha256,
                    "runtime_dependency_surface": "exact-embedded-production-requirements",
                    "status": "PASS",
                    "target_inventory_sha256": sha256_bytes(b"fixture-target-inventory"),
                },
                "pip": {
                    "isolated": True,
                    "no_deps": True,
                    "no_index": True,
                    "require_hashes": True,
                },
                "schema": "arc3.linux-cold-start.v0.2",
                "status": "PASS",
                "target": "CPython 3.12 / Linux x86_64 / manylinux_2_28",
                "validation_level": "native-linux-cp312-exact-notebook-cold-start",
            },
            "fixture": True,
            "kaggle_accessed": False,
            "public_environment_interactions": 0,
            "schema": "arc3.build-002-cold-start-command.v0.2",
            "status": "PASS",
        },
    )


def _integrity_fixture(path: Path, package: Path, *, commit: str) -> None:
    _write_json(
        path,
        _sealed(
            {
                "candidate_sha256": sha256_file(package / "arc3-kaggle-candidate.zip"),
                "checks": {"secret_scan": {"passed": True}},
                "dependency_inventory": [{"name": "fixture"}],
                "finding_counts": {"blocking": 0},
                "fixture": True,
                "package_only_passed": True,
                "schema": "arc3.build-002.fixture-integrity.v0.1",
                "secret_findings": 0,
                "source_commit": commit,
                "status": "PASS",
            }
        ),
    )


def _fixture_request(
    fixture_root: Path,
    package_directory: Path,
    *,
    name: str,
    include_assets: bool,
) -> PreflightBundleRequest:
    root = fixture_root / name
    root.mkdir()
    commit = (
        __import__("subprocess")
        .run(
            ("git", "rev-parse", "HEAD"),
            cwd=REPOSITORY,
            check=True,
            capture_output=True,
            text=True,
        )
        .stdout.strip()
    )
    framework = _framework_fixture(root)
    profile = root / "runtime-profile.json"
    cold = root / "linux-cold-start.json"
    integrity = root / "integrity.json"
    source_identity = root / "source-identity.json"
    _runtime_profile_fixture(profile, commit=commit)
    _cold_start_fixture(cold, package_directory)
    _integrity_fixture(integrity, package_directory, commit=commit)
    _source_identity_fixture(source_identity)
    manifest = PublicPartitionManifest.load(MANIFEST)
    games = tuple(sorted(item.game_id for item in manifest.games("public-holdout")))
    assets_root = root / "assets"
    assets_root.mkdir()
    assets: dict[str, Path] = {}
    for game_id in games:
        asset = assets_root / f"{game_id}.arc"
        if include_assets:
            asset.write_bytes((game_id + "\n").encode())
        assets[game_id] = asset
    return PreflightBundleRequest(
        root=REPOSITORY,
        seed=29,
        manifest=MANIFEST,
        assets=assets,
        framework_root=framework,
        production_agent=REPOSITORY / "agent" / "my_agent.py",
        gateway_host="127.0.0.1",
        gateway_port=8001,
        submission_output=root / "runtime-output" / "submission.parquet",
        package_directory=package_directory,
        integrity_receipt=integrity,
        runtime_profile_receipt=profile,
        native_linux_cold_start_receipt=cold,
        source_identity_receipt=source_identity,
        runtime_config=REPOSITORY / "src" / "arc3" / "competition-runtime.v0.2.json",
        dependency_lock=REPOSITORY / "uv.lock",
        upstream_lock=REPOSITORY / "upstream.lock.json",
        source_preview_receipt=(
            REPOSITORY / "docs" / "evidence" / "002-00-public-source-preview-contamination.json"
        ),
        third_party_notices=REPOSITORY / "THIRD_PARTY_NOTICES.md",
        license_file=REPOSITORY / "LICENSE",
        output_directory=root / "bundle",
    )


@pytest.mark.competition
def test_fixture_bundle_constructs_run_plan_without_arming_or_opening_environment(
    fixture_root: Path,
    package_directory: Path,
) -> None:
    request = _fixture_request(
        fixture_root,
        package_directory,
        name="complete",
        include_assets=True,
    )
    result = build_preflight_bundle(request, allow_test_fixtures=True)

    assert result.status == "FIXTURE_READY_NOT_ARMABLE"
    assert result.environment_make_interactions == 0
    assert result.holdout_authority_consumed is False
    assert result.run_plan is not None and result.run_plan.is_file()
    assert not (REPOSITORY / "artifacts" / "build002" / "holdout-one-shot" / "launch.json").exists()
    plan = json.loads(result.run_plan.read_text(encoding="utf-8"))
    assert plan["schema"] == "arc3.build-002.holdout-run-plan.v0.1"
    assert set(plan["gates"]) == {
        "competition-lifecycle",
        "dependency-and-config-identity",
        "deterministic-startup-and-replay",
        "frozen-source-config-artifacts",
        "notebook-build-and-offline-entry-point",
        "offline-cold-start",
        "official-source-identity",
        "package-and-license-inventory",
        "secret-and-integrity-scan",
        "submission-parquet-structure",
    }
    gate = json.loads((REPOSITORY / plan["gates"]["offline-cold-start"]).read_text())
    assert gate["evidence_class"] == "fixture"
    assert set(gate["evidence"]) == GATE_EVIDENCE_ROLES


@pytest.mark.competition
def test_missing_exact_assets_emits_blocked_external_with_zero_consumption(
    fixture_root: Path,
    package_directory: Path,
) -> None:
    request = _fixture_request(
        fixture_root,
        package_directory,
        name="missing-assets",
        include_assets=False,
    )
    result = build_preflight_bundle(request, allow_test_fixtures=True)

    assert result.status == "BLOCKED_EXTERNAL"
    assert result.run_plan is None
    assert result.blocker is not None
    blocker = json.loads(result.blocker.read_text(encoding="utf-8"))
    assert blocker["schema"] == PREFLIGHT_BLOCKER_SCHEMA
    assert blocker["environment_make_interactions"] == 0
    assert blocker["environment_actions"] == 0
    assert blocker["authority"] == {
        "authorized_runs_remaining": 1,
        "holdout_authority_consumed": False,
        "rerun_authorized": True,
    }
    assert len(blocker["missing_asset_game_ids"]) == 10
    assert not (request.output_directory / "gates").exists()
    assert not (request.output_directory / "run-plan.json").exists()


@pytest.mark.competition
def test_production_validation_rejects_explicit_native_cold_start_fixture(
    fixture_root: Path,
    package_directory: Path,
) -> None:
    request = _fixture_request(
        fixture_root,
        package_directory,
        name="production-rejection",
        include_assets=True,
    )
    with pytest.raises(EvaluationError, match="rejects fixture cold-start evidence"):
        _validate_cold_start(
            request.native_linux_cold_start_receipt,
            package_paths={
                "package-manifest": package_directory / "package-manifest.json",
                "payload": package_directory / "arc3-first-party.zip",
                "requirements": package_directory / "runtime-requirements-linux-cp312.txt",
                "wheel-manifest": package_directory / "runtime-wheels-linux-cp312.json",
            },
            allow_test_fixtures=False,
        )


@pytest.mark.competition
def test_production_validation_rejects_safe_framework_rehearsal_as_exact_platform(
    fixture_root: Path,
    package_directory: Path,
) -> None:
    request = _fixture_request(
        fixture_root,
        package_directory,
        name="safe-platform-production-rejection",
        include_assets=True,
    )
    receipt = json.loads(request.native_linux_cold_start_receipt.read_text(encoding="utf-8"))
    receipt.pop("fixture")
    _write_json(request.native_linux_cold_start_receipt, receipt)

    with pytest.raises(FileNotFoundError, match="exact Kaggle competition platform"):
        _validate_cold_start(
            request.native_linux_cold_start_receipt,
            package_paths={
                "package-manifest": package_directory / "package-manifest.json",
                "payload": package_directory / "arc3-first-party.zip",
                "requirements": package_directory / "runtime-requirements-linux-cp312.txt",
                "wheel-manifest": package_directory / "runtime-wheels-linux-cp312.json",
            },
            allow_test_fixtures=False,
        )


@pytest.mark.competition
def test_production_validation_rejects_explicit_source_identity_fixture(
    fixture_root: Path,
    package_directory: Path,
) -> None:
    request = _fixture_request(
        fixture_root,
        package_directory,
        name="source-production-rejection",
        include_assets=True,
    )
    commit = (
        __import__("subprocess")
        .run(
            ("git", "rev-parse", "HEAD"),
            cwd=REPOSITORY,
            check=True,
            capture_output=True,
            text=True,
        )
        .stdout.strip()
    )
    with pytest.raises(EvaluationError, match="rejects fixture source-identity evidence"):
        _validate_runtime_and_sources(
            request,
            commit=commit,
            allow_test_fixtures=False,
            validate_framework=False,
        )


@pytest.mark.competition
def test_production_validation_fails_closed_on_partial_official_surfaces(
    fixture_root: Path,
    package_directory: Path,
) -> None:
    request = _fixture_request(
        fixture_root,
        package_directory,
        name="partial-source-production-rejection",
        include_assets=True,
    )
    source = json.loads(request.source_identity_receipt.read_text(encoding="utf-8"))
    source.pop("fixture")
    _write_json(request.source_identity_receipt, source)
    commit = (
        __import__("subprocess")
        .run(
            ("git", "rev-parse", "HEAD"),
            cwd=REPOSITORY,
            check=True,
            capture_output=True,
            text=True,
        )
        .stdout.strip()
    )

    with pytest.raises(FileNotFoundError, match="static asset provenance"):
        _validate_runtime_and_sources(
            request,
            commit=commit,
            allow_test_fixtures=False,
            validate_framework=False,
        )


@pytest.mark.competition
def test_production_pass_label_cannot_replace_official_surface_attestations(
    fixture_root: Path,
    package_directory: Path,
) -> None:
    request = _fixture_request(
        fixture_root,
        package_directory,
        name="unattested-pass-production-rejection",
        include_assets=True,
    )
    source = json.loads(request.source_identity_receipt.read_text(encoding="utf-8"))
    source.pop("fixture")
    source["status"] = "PASS"
    source["blocked_external"] = []
    _write_json(request.source_identity_receipt, source)
    commit = (
        __import__("subprocess")
        .run(
            ("git", "rev-parse", "HEAD"),
            cwd=REPOSITORY,
            check=True,
            capture_output=True,
            text=True,
        )
        .stdout.strip()
    )

    with pytest.raises(FileNotFoundError, match="official evidence attestations"):
        _validate_runtime_and_sources(
            request,
            commit=commit,
            allow_test_fixtures=False,
            validate_framework=False,
        )


@pytest.mark.competition
def test_production_assets_require_independent_official_byte_identities(tmp_path: Path) -> None:
    games = ("game-a",)
    asset = tmp_path / "game-a.json"
    asset.write_text("arbitrary caller bytes", encoding="utf-8")

    with pytest.raises(FileNotFoundError, match="independently pinned"):
        _validate_static_asset_provenance({}, games, {"game-a": asset}, allow_test_fixtures=False)

    provenance = {
        "public_holdout_asset_provenance": {
            "assets": [
                {
                    "byte_length": asset.stat().st_size,
                    "game_id": "game-a",
                    "game_version": "v1",
                    "sha256": sha256_file(asset),
                }
            ],
            "schema": "arc3.build-002.official-static-asset-provenance.v0.1",
            "source_kind": "official-static-asset-manifest",
            "source_manifest_sha256": sha256_bytes(b"official-manifest"),
            "source_url": "https://github.com/arcprize/example",
            "status": "PASS",
        }
    }
    _validate_static_asset_provenance(
        provenance, games, {"game-a": asset}, allow_test_fixtures=False
    )
    asset.write_text("different bytes", encoding="utf-8")
    with pytest.raises(EvaluationError, match="identity changed"):
        _validate_static_asset_provenance(
            provenance, games, {"game-a": asset}, allow_test_fixtures=False
        )


@pytest.mark.competition
def test_request_loader_preserves_exact_paths_and_rejects_extra_fields(
    fixture_root: Path,
    package_directory: Path,
) -> None:
    request = _fixture_request(
        fixture_root,
        package_directory,
        name="request-loader",
        include_assets=True,
    )
    path = fixture_root / "request-loader.json"
    document: dict[str, Any] = {
        "assets": {key: str(value) for key, value in request.assets.items()},
        "dependency_lock": str(request.dependency_lock),
        "framework_root": str(request.framework_root),
        "gateway_host": request.gateway_host,
        "gateway_port": request.gateway_port,
        "integrity_receipt": str(request.integrity_receipt),
        "license_file": str(request.license_file),
        "manifest": str(request.manifest),
        "native_linux_cold_start_receipt": str(request.native_linux_cold_start_receipt),
        "output_directory": str(request.output_directory),
        "package_directory": str(request.package_directory),
        "production_agent": str(request.production_agent),
        "runtime_config": str(request.runtime_config),
        "runtime_profile_receipt": str(request.runtime_profile_receipt),
        "schema": PREFLIGHT_REQUEST_SCHEMA,
        "seed": request.seed,
        "source_identity_receipt": str(request.source_identity_receipt),
        "source_preview_receipt": str(request.source_preview_receipt),
        "submission_output": str(request.submission_output),
        "third_party_notices": str(request.third_party_notices),
        "upstream_lock": str(request.upstream_lock),
    }
    _write_json(path, document)
    loaded = load_preflight_bundle_request(REPOSITORY, path)
    assert loaded.assets == request.assets
    document["unexpected"] = True
    _write_json(path, document)
    with pytest.raises(EvaluationError, match="schema or fields"):
        load_preflight_bundle_request(REPOSITORY, path)


@pytest.mark.competition
def test_forged_all_true_v02_gates_cannot_bypass_semantic_evidence_validation(
    fixture_root: Path,
    package_directory: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _fixture_request(
        fixture_root,
        package_directory,
        name="forged-pass",
        include_assets=True,
    )
    result = build_preflight_bundle(request, allow_test_fixtures=True)
    assert result.run_plan is not None
    plan = json.loads(result.run_plan.read_text(encoding="utf-8"))
    gate_rows: list[dict[str, JSONValue]] = []
    for role, relative in sorted(plan["gates"].items()):
        gate_path = REPOSITORY / relative
        gate = json.loads(gate_path.read_text(encoding="utf-8"))
        gate["evidence_class"] = "production"
        _write_json(gate_path, gate)
        gate_rows.append(
            {
                "byte_length": gate_path.stat().st_size,
                "path": relative,
                "role": role,
                "sha256": sha256_file(gate_path),
            }
        )
    artifact_rows = []
    for role, relative in sorted(plan["artifacts"].items()):
        artifact_path = REPOSITORY / relative
        artifact_rows.append(
            {
                "byte_length": artifact_path.stat().st_size,
                "path": relative,
                "role": role,
                "sha256": sha256_file(artifact_path),
            }
        )
    commit = (
        __import__("subprocess")
        .run(
            ("git", "rev-parse", "HEAD"),
            cwd=REPOSITORY,
            check=True,
            capture_output=True,
            text=True,
        )
        .stdout.strip()
    )
    monkeypatch.setattr(preflight_module, "_current_commit", lambda *_args, **_kwargs: commit)

    with pytest.raises(EvaluationError, match="build receipt is not valid"):
        build002_holdout._validate_gate_receipts(REPOSITORY, gate_rows, artifact_rows)
