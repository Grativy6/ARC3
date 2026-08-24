from __future__ import annotations

import importlib
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import arc3.evaluation.integrity_authority as authority
from arc3.errors import EvaluationError
from arc3.evaluation.artifacts import (
    atomic_write_json,
    canonical_json_bytes,
    seal_object,
    sha256_bytes,
    sha256_file,
)
from arc3.integrity import INTEGRITY_SCHEMA, IntegrityReceipt


def test_integrity_authority_git_disables_replacements_and_redirection(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("GIT_DIR", str(tmp_path / "redirected.git"))
    monkeypatch.setenv("git_work_tree", str(tmp_path / "redirected-worktree"))
    captured: dict[str, Any] = {}

    def fake_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        captured["argv"] = args[0]
        captured["cwd"] = kwargs["cwd"]
        captured.update(kwargs["env"])
        return subprocess.CompletedProcess([], 0, stdout="", stderr="")

    monkeypatch.setattr(authority.subprocess, "run", fake_run)

    assert authority._git(tmp_path, "rev-parse", "HEAD") == ""
    assert captured["GIT_NO_REPLACE_OBJECTS"] == "1"
    assert "GIT_DIR" not in captured
    assert "git_work_tree" not in captured
    assert captured["argv"] == (
        "git",
        "--no-replace-objects",
        "-C",
        str(tmp_path.resolve()),
        "rev-parse",
        "HEAD",
    )
    assert captured["cwd"] == tmp_path.resolve()


def _receipt_body(
    *,
    commit: str,
    candidates: dict[str, str],
    reachable: dict[str, str],
) -> dict[str, Any]:
    checks: dict[str, dict[str, object]] = {
        name: {"passed": True}
        for name in (
            "archive_static",
            "policy_static",
            "secret_scan",
            "source_identity",
            "supply_chain",
        )
    }
    checks["supply_chain"]["status"] = "PASS"
    return {
        "assurance_scope": {
            "kind": "static-only",
            "public_identifier_scan": ("NOT_EVALUATED_PACKAGE_ONLY_NO_SEMANTIC_MANIFEST_ACCESS"),
            "scanner_network_mode": "offline-by-construction",
        },
        "checks": checks,
        "finding_counts": {"blocking": 0, "total": 0, "warnings": 0},
        "findings": [],
        "full_competition_integrity_status": "NOT_EVALUATED_PUBLIC_IDENTIFIERS",
        "git": {"commit": commit, "dirty_worktree": False},
        "inputs": {
            "candidate_file_count": len(candidates),
            "candidate_mode": "caller-supplied",
            "candidate_paths": list(candidates),
            "entry_points": ["agent/my_agent.py"],
            "manifest": None,
            "manifest_binding": {
                "declaration": "disabled-package-only",
                "expected_sha256": None,
                "issue": "semantic public-manifest access is prohibited in this profile",
            },
            "manifest_sha256": None,
            "public_identifier_count": 0,
            "public_identifier_mode": "disabled-package-only",
            "reachable_policy_file_count": len(reachable),
            "reachable_policy_paths": list(reachable),
            "run_state": None,
        },
        "integrity_scope": "package-only-no-public-identifiers",
        "license_summary": {
            "first_party_license_status": "MIT-0",
            "installed_version_mismatch_count": 0,
            "not_evaluated_count": 0,
            "status": "PASS",
            "unknown_or_missing_metadata_count": 0,
        },
        "package_only_passed": True,
        "passed": False,
        "production_policy_static_coverage": {
            "algorithm": "static-first-party-import-closure-v0.1",
            "entry_points": ["agent/my_agent.py"],
            "entry_points_reached": ["agent/my_agent.py"],
            "limitations": (
                "Static first-party import reachability does not prove runtime dynamic-import "
                "or native-extension containment."
            ),
            "policy_scan_covers_reachable_paths": True,
            "reachable_file_count": len(reachable),
            "reachable_paths_hashed": True,
            "status": "PASS",
        },
        "reachable_policy_source_hashes": reachable,
        "schema": INTEGRITY_SCHEMA,
        "source_hashes": candidates,
    }


@pytest.mark.parametrize("tamper", ["omit", "add"])
def test_package_only_candidate_set_tamper_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    tamper: str,
) -> None:
    (tmp_path / "agent").mkdir()
    (tmp_path / "src/arc3").mkdir(parents=True)
    (tmp_path / "agent/my_agent.py").write_text("VALUE = 1\n", encoding="utf-8")
    (tmp_path / "src/arc3/competition-runtime.v0.1.json").write_text("{}\n", encoding="utf-8")
    (tmp_path / "uv.lock").write_text("version = 1\n", encoding="utf-8")
    candidates = {
        "agent/my_agent.py": sha256_file(tmp_path / "agent/my_agent.py"),
        "src/arc3/competition-runtime.v0.1.json": sha256_file(
            tmp_path / "src/arc3/competition-runtime.v0.1.json"
        ),
        "uv.lock": sha256_file(tmp_path / "uv.lock"),
    }
    reachable = {"agent/my_agent.py": candidates["agent/my_agent.py"]}
    monkeypatch.setattr(authority, "_package_candidate_projection", lambda _root: candidates)
    body = _receipt_body(
        commit="a" * 40,
        candidates=candidates,
        reachable=reachable,
    )
    paths = body["inputs"]["candidate_paths"]
    assert isinstance(paths, list)
    if tamper == "omit":
        paths.pop()
        body["inputs"]["candidate_file_count"] = len(paths)
    else:
        paths.append("untracked-extra.py")
        body["inputs"]["candidate_file_count"] = len(paths)
    receipt_path = tmp_path / "integrity.json"
    receipt_path.write_bytes(IntegrityReceipt(body=body).canonical_bytes())

    with pytest.raises(EvaluationError, match="not clear and exact"):
        authority._package_only_summary(
            tmp_path,
            receipt_path,
            current_source={"commit": "a" * 40},
            projection=reachable,
        )


@pytest.mark.parametrize("tamper", ["input-entry", "coverage-entry", "license"])
def test_package_only_scope_metadata_tamper_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    tamper: str,
) -> None:
    (tmp_path / "agent").mkdir()
    (tmp_path / "src/arc3").mkdir(parents=True)
    (tmp_path / "agent/my_agent.py").write_text("VALUE = 1\n", encoding="utf-8")
    (tmp_path / "src/arc3/competition-runtime.v0.1.json").write_text("{}\n", encoding="utf-8")
    (tmp_path / "uv.lock").write_text("version = 1\n", encoding="utf-8")
    candidates = {
        "agent/my_agent.py": sha256_file(tmp_path / "agent/my_agent.py"),
        "src/arc3/competition-runtime.v0.1.json": sha256_file(
            tmp_path / "src/arc3/competition-runtime.v0.1.json"
        ),
        "uv.lock": sha256_file(tmp_path / "uv.lock"),
    }
    reachable = {"agent/my_agent.py": candidates["agent/my_agent.py"]}
    monkeypatch.setattr(authority, "_package_candidate_projection", lambda _root: candidates)
    body = _receipt_body(commit="a" * 40, candidates=candidates, reachable=reachable)
    if tamper == "input-entry":
        body["inputs"]["entry_points"] = ["agent/alternate.py"]
    elif tamper == "coverage-entry":
        body["production_policy_static_coverage"]["entry_points"] = ["agent/alternate.py"]
        body["production_policy_static_coverage"]["entry_points_reached"] = ["agent/alternate.py"]
    else:
        body["license_summary"]["first_party_license_status"] = "UNKNOWN"
    receipt_path = tmp_path / "integrity.json"
    receipt_path.write_bytes(IntegrityReceipt(body=body).canonical_bytes())

    with pytest.raises(EvaluationError, match="not clear and exact"):
        authority._package_only_summary(
            tmp_path,
            receipt_path,
            current_source={"commit": "a" * 40},
            projection=reachable,
        )


@pytest.mark.parametrize(
    ("status", "tamper", "accepted"),
    [
        ("PASS", None, True),
        ("FAILED_MECHANISM", None, True),
        ("FAILED_INFRASTRUCTURE", None, False),
        ("PASS", "identifier-list", False),
        ("PASS", "predeclaration-file", False),
    ],
)
def test_stage09_complete_mechanism_terminal_is_valid_evidence_authority(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    status: str,
    tamper: str | None,
    accepted: bool,
) -> None:
    source_root = tmp_path / "source"
    script = source_root / "scripts/measure_development_recovery.py"
    script.parent.mkdir(parents=True)
    script.write_text("# synthetic origin\n", encoding="utf-8")
    holdout_hash = "sha256:" + "1" * 64
    identifier_hash = "sha256:" + "0" * 64
    original_file_hash = "sha256:" + "a" * 64
    original_core_hash = "sha256:" + "9" * 64
    receipt: dict[str, Any] = {
        "attempt_root": (tmp_path / "attempt").resolve().as_posix(),
        "competition_integrity": True,
        "evidence_integrity": True,
        "execution_complete": True,
        "exposure": {
            "path": (tmp_path / "exposure.jsonl").resolve().as_posix(),
            "sha256": "sha256:" + "2" * 64,
        },
        "gate": {"passed": status == "PASS"},
        "output": {
            "artifact_core_hash": "sha256:" + "3" * 64,
            "path": (tmp_path / "stage09.json").resolve().as_posix(),
            "sha256": "sha256:" + "4" * 64,
        },
        "passed": True,
        "prior_authority": {
            "assurance_limitation": (
                "Package and development scans are static; dynamic-import and native-extension "
                "containment are not proven; Build 001 public identifiers were not fully evaluated."
            ),
            "build_001_package_only": {
                "candidate_set_recomputed": True,
                "file_sha256": "sha256:" + "1" * 64,
                "git_commit": "a" * 40,
                "live_source_hashes_match": True,
                "package_only_passed": True,
                "policy_scan_covers_reachable_paths": True,
                "reachable_paths_recomputed": True,
                "receipt_sha256": "sha256:" + "2" * 64,
                "status": "PASS",
            },
            "development_scans": {
                "build_000_finding_count": 0,
                "build_000_passed": True,
                "build_001_finding_count": 0,
                "build_001_passed": True,
                "development_identity_count": 12,
                "identifier_list_hash": identifier_hash,
                "identifier_string_count": 24,
                "identity_values_disclosed": False,
            },
            "full_public_integrity_status": "NOT_EVALUATED_BUILD_001_PUBLIC_IDENTIFIERS",
            "holdout": {
                "file_sha256": holdout_hash,
                "identities_loaded": 0,
                "manifest_loaded_as_metadata": False,
                "pinned_manifest_sha256": authority.OPAQUE_PUBLIC_MANIFEST_SHA256,
                "public_holdout_gameplay_events": 0,
                "status": "SEALED_UNCONSUMED",
            },
            "predeclaration": {
                "amendment": {
                    "core_hash": "sha256:" + "5" * 64,
                    "file_sha256": "sha256:" + "6" * 64,
                    "path": (tmp_path / "amendment.json").resolve().as_posix(),
                    "result_state": "READY_NOT_EXECUTED",
                },
                "effective_build_001_commit": "a" * 40,
                "effective_build_001_source_sha256": "sha256:" + "7" * 64,
                "effective_build_001_tree": "b" * 40,
                "effective_matrix_hash": "sha256:" + "8" * 64,
                "live_validated": True,
                "original": {
                    "core_hash": original_core_hash,
                    "file_sha256": original_file_hash,
                    "path": (
                        source_root
                        / "docs/evidence/001-09-development-recovery-predeclaration.json"
                    )
                    .resolve()
                    .as_posix(),
                    "preserved_unchanged": True,
                },
            },
            "prior_authority_hash": "sha256:" + "b" * 64,
        },
        "schema": "arc3.build-001.stage-09-terminal-verification.v0.2",
        "source_end": {"passed": True},
        "source_root": source_root.resolve().as_posix(),
        "source_stable": True,
        "status": status,
        "terminal_finalization": {
            "path": (tmp_path / "finalization.json").resolve().as_posix(),
            "sha256": "sha256:" + "c" * 64,
            "terminal_finalization_hash": "sha256:" + "d" * 64,
        },
        "work_authority": {
            "cell_count": 96,
            "cell_finalization_hashes": ["sha256:" + "e" * 64] * 96,
            "cell_receipt_hashes": ["sha256:" + "f" * 64] * 96,
            "matrix_hash": "sha256:" + "8" * 64,
        },
    }
    prior = receipt["prior_authority"]
    assert isinstance(prior, dict)
    if tamper == "identifier-list":
        scans = prior["development_scans"]
        assert isinstance(scans, dict)
        scans["identifier_list_hash"] = "sha256:" + "f" * 64
    elif tamper == "predeclaration-file":
        predeclaration = prior["predeclaration"]
        assert isinstance(predeclaration, dict)
        original = predeclaration["original"]
        assert isinstance(original, dict)
        original["file_sha256"] = "sha256:" + "f" * 64
    receipt = seal_object(receipt, hash_field="verification_hash")
    verification_path = tmp_path / "verification.json"
    atomic_write_json(verification_path, receipt)
    namespace: dict[str, object] = {"RESULT": receipt}
    exec(
        compile(
            "def verify_complete_terminal(**_kwargs):\n    return RESULT\n",
            str(script),
            "exec",
        ),
        namespace,
    )
    module = SimpleNamespace(
        __file__=str(script),
        verify_complete_terminal=namespace["verify_complete_terminal"],
    )
    monkeypatch.setattr(importlib, "import_module", lambda _name: module)

    arguments: dict[str, Any] = {
        "expected_file_sha256": sha256_file(verification_path),
        "expected_verification_hash": receipt["verification_hash"],
        "source_root": source_root,
        "expected_holdout_nonconsumption_sha256": holdout_hash,
        "expected_development_identifier_sha256": identifier_hash,
        "expected_development_predeclaration_file_sha256": original_file_hash,
        "expected_development_predeclaration_core_hash": original_core_hash,
    }
    if not accepted:
        with pytest.raises(EvaluationError, match="not exact and passing"):
            authority._stage09_verification_summary(verification_path, **arguments)
        return
    summary = authority._stage09_verification_summary(verification_path, **arguments)
    assert summary["status"] == status


def _git_command(root: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ("git", *arguments),
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return completed.stdout.strip()


def _detached_repository(root: Path, label: str) -> tuple[str, str]:
    root.mkdir()
    _git_command(root, "init", "--quiet")
    _git_command(root, "config", "user.name", "ARC3 Test")
    _git_command(root, "config", "user.email", "arc3-test@example.invalid")
    (root / "identity.txt").write_text(f"{label}\n", encoding="utf-8")
    _git_command(root, "add", "identity.txt")
    _git_command(root, "commit", "--quiet", "--no-gpg-sign", "-m", label)
    commit = _git_command(root, "rev-parse", "HEAD")
    tree = _git_command(root, "rev-parse", "HEAD^{tree}")
    _git_command(root, "checkout", "--quiet", "--detach", commit)
    return commit, tree


def _recorded_source(
    root: Path,
    *,
    commit: str,
    tree: str,
    source_hash: str,
) -> dict[str, Any]:
    return {
        "branch": "",
        "dirty_worktree": False,
        "first_party_source_sha256": source_hash,
        "git_commit": commit,
        "git_tree": tree,
        "passed": True,
        "predicates": {
            "clean": True,
            "commit": True,
            "detached": True,
            "import_root": True,
            "source_bytes": True,
            "tree": True,
        },
        "probe_returncode": 0,
        "probe_stderr_sha256": "sha256:" + "0" * 64,
        "root": root.resolve().as_posix(),
    }


def _write_pretty_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def _stage09_partial_fixture(tmp_path: Path) -> dict[str, Any]:
    harness_root = tmp_path / "harness"
    production_root = tmp_path / "production"
    build_000_root = tmp_path / "build-000"
    harness_commit, harness_tree = _detached_repository(harness_root, "harness")
    production_commit, production_tree = _detached_repository(production_root, "production")
    build_000_commit, build_000_tree = _detached_repository(build_000_root, "build-000")

    holdout_hash = "sha256:" + "1" * 64
    identifier_hash = "sha256:" + "2" * 64
    predeclaration_file_hash = "sha256:" + "3" * 64
    predeclaration_core_hash = "sha256:" + "4" * 64
    production_source_hash = "sha256:" + "5" * 64
    build_000_source_hash = "sha256:" + "6" * 64
    matrix_hash = "sha256:" + "7" * 64
    receipt_hash = "sha256:" + "8" * 64
    cell_finalization_hash = "sha256:" + "9" * 64
    exposure_hash = "sha256:" + "a" * 64
    exposure_ledger_hash = "sha256:" + "b" * 64

    harness_binding = seal_object(
        {
            "files": {},
            "git_commit": harness_commit,
            "git_object_format": "sha1",
            "git_tree": harness_tree,
            "schema": "arc3.build-001.stage-09-harness-source-binding.v0.2",
            "source_projection": {},
        },
        hash_field="binding_hash",
    )
    harness_observation = seal_object(
        {
            "binding_hash": harness_binding["binding_hash"],
            "branch": "",
            "dirty_worktree": False,
            "extra_non_cache_paths": [],
            "files": {},
            "git_commit": harness_commit,
            "git_object_format": "sha1",
            "git_tree": harness_tree,
            "index_non_h_paths": [],
            "passed": True,
            "predicates": {
                "clean": True,
                "commit": True,
                "detached": True,
                "extra_files": True,
                "files": True,
                "index_flags": True,
                "object_format": True,
                "projection": True,
                "root": True,
                "tree": True,
            },
            "root": harness_root.resolve().as_posix(),
            "schema": "arc3.build-001.stage-09-harness-source-observation.v0.2",
            "source_projection": {},
        },
        hash_field="observation_hash",
    )
    sealed_holdout = {
        "identities_loaded": 0,
        "manifest_loaded_as_metadata": False,
        "public_holdout_gameplay_events": 0,
        "status": "SEALED_UNCONSUMED",
    }
    prior_holdout = {
        **sealed_holdout,
        "file_sha256": holdout_hash,
        "pinned_manifest_sha256": authority.OPAQUE_PUBLIC_MANIFEST_SHA256,
    }
    prior_authority = seal_object(
        {
            "holdout": prior_holdout,
            "integrity": {
                "development_scans": {"identifier_list_hash": identifier_hash},
            },
            "passed": True,
            "predicates": {"holdout_nonconsumption": True},
            "schema": "arc3.build-001.stage-09-prior-authority.v0.3",
        },
        hash_field="authority_hash",
    )
    preflight = seal_object(
        {
            "gameplay_opened": False,
            "harness_source": {
                "expected": harness_binding,
                "start": harness_observation,
            },
            "holdout": sealed_holdout,
            "matrix_hash": matrix_hash,
            "paths": {
                "build_000_root": build_000_root.resolve().as_posix(),
                "build_001_root": production_root.resolve().as_posix(),
            },
            "predeclaration_core_hash": predeclaration_core_hash,
            "predeclaration_sha256": predeclaration_file_hash,
            "prior_authority": prior_authority,
            "public_manifest_identity": {
                "pinned_sha256": authority.OPAQUE_PUBLIC_MANIFEST_SHA256,
                "semantic_access": False,
                "verified_by_prior_authority": True,
            },
            "schema": "arc3.build-001.stage-09-preflight.v0.5",
            "sources": {
                "build_000": _recorded_source(
                    build_000_root,
                    commit=build_000_commit,
                    tree=build_000_tree,
                    source_hash=build_000_source_hash,
                ),
                "build_001": _recorded_source(
                    production_root,
                    commit=production_commit,
                    tree=production_tree,
                    source_hash=production_source_hash,
                ),
            },
            "stage09_exposure_event_count": 0,
            "status": "READY_NOT_EXECUTED",
        },
        hash_field="preflight_hash",
    )
    aggregate = seal_object(
        {
            "cell_count": 1,
            "cell_finalization_hashes": [cell_finalization_hash],
            "cell_receipt_hashes": [receipt_hash],
            "claim_boundary": (
                "development recovery only; no public-holdout or hidden-game generalization claim"
            ),
            "evidence_label": "local-public",
            "execution_complete": False,
            "expected_cell_count": 96,
            "exposure_ledger_sha256": exposure_ledger_hash,
            "failure": {
                "cell_id": "synthetic-cell-00",
                "cell_ordinal": 0,
                "exposure_event_hash": exposure_hash,
                "kind": "terminal-cell-infrastructure-failure",
            },
            "holdout": sealed_holdout,
            "matrix_hash": matrix_hash,
            "orphan_process": None,
            "preflight": preflight,
            "schema": "arc3.build-001.stage-09-aggregate.v0.4",
            "status": "FAILED_INFRASTRUCTURE",
        },
        hash_field="artifact_core_hash",
    )
    aggregate_path = tmp_path / "aggregate.json"
    atomic_write_json(aggregate_path, aggregate)
    aggregate_file_hash = sha256_file(aggregate_path)

    final_evidence = {
        "development_scans": {"identifier_list_hash": identifier_hash},
        "holdout": prior_holdout,
        "predeclaration": {
            "effective_build_001_commit": production_commit,
            "effective_build_001_source_sha256": production_source_hash,
            "effective_build_001_tree": production_tree,
            "original": {
                "core_hash": predeclaration_core_hash,
                "file_sha256": predeclaration_file_hash,
            },
        },
    }
    finalization = seal_object(
        {
            "artifact_core_hash": aggregate["artifact_core_hash"],
            "evidence_authority": final_evidence,
            "output_path": aggregate_path.resolve().as_posix(),
            "output_sha256": aggregate_file_hash,
            "recovery_kind": None,
            "schema": "arc3.build-001.stage-09-terminal-finalization.v0.3",
            "terminal_authority_passed": True,
            "timing_measurement_available": True,
            "within_overall_active_wall": True,
        },
        hash_field="terminal_finalization_hash",
    )
    finalization_path = tmp_path / "aggregate.json.finalization.json"
    atomic_write_json(finalization_path, finalization)

    acceptance = seal_object(
        {
            "attempt": {
                "environment_opened_cell_count": 0,
                "execution_complete": False,
                "exit_code": 1,
                "exposed_cell_count": 1,
                "gameplay_action_count": 0,
                "identity": "development-recovery-attempt-01",
                "scheduled_cells_not_started": 95,
                "terminal_cell_receipt_count": 1,
            },
            "claim": "NO_LOCAL_PUBLIC_RECOVERY_OR_GENERALIZATION_CLAIM",
            "claim_boundary": (
                "The unique predeclared attempt exposed one development cell but aborted "
                "before opening its environment. It supplies infrastructure and evidence-"
                "integrity observations only, not gameplay, baseline, recovery, action-"
                "efficiency, holdout, private-platform, or hidden-game performance evidence."
            ),
            "decision": {
                "attempt_will_not_be_rerun": True,
                "baseline_or_ablation_comparison_available": False,
                "development_recovery_gate": "NOT_EVALUATED_DUE_INFRASTRUCTURE_FAILURE",
                "holdout_opening_predicate_stage_09_pass": False,
                "local_public_recovery_observed": False,
                "stage_acceptance_satisfied": False,
                "stage_status": "FAILED_INFRASTRUCTURE",
            },
            "evidence_label": "local-public",
            "failure_diagnosis": {"environment_opened": False},
            "frozen_identity": {
                "build_000_comparator_commit": build_000_commit,
                "build_000_comparator_tree": build_000_tree,
                "harness_binding_hash": harness_binding["binding_hash"],
                "harness_commit": harness_commit,
                "harness_root": harness_root.resolve().as_posix(),
                "harness_tree": harness_tree,
                "preflight_hash_before_execution": "sha256:" + "c" * 64,
                "production_policy_commit": production_commit,
                "production_policy_source_sha256": production_source_hash,
                "production_policy_tree": production_tree,
                "runtime_binding_file_sha256": "sha256:" + "d" * 64,
            },
            "integrity": {
                "build_000_blocking_comparator_findings": 0,
                "hosted_inference_calls": 0,
                "official_submission": False,
                "production_static_findings": 0,
                "public_holdout_gameplay_events": 0,
                "public_holdout_identities_loaded": 0,
                "public_holdout_manifest_loaded_as_metadata": False,
                "public_holdout_status": "SEALED_UNCONSUMED",
            },
            "key_artifact_sha256": {},
            "protocol": {
                "attempt_limit": 1,
                "attempts_consumed": 1,
                "development_identity_count": 12,
                "expected_cells": 96,
                "matrix_hash": matrix_hash,
                "maximum_actions_per_cell": 80,
                "maximum_resets_per_cell": 8,
                "overall_active_wall_seconds": 14400.0,
                "rerun_allowed": False,
                "seeds": [7, 11],
                "worker_wall_seconds": 120.0,
            },
            "recorded_at": "2026-08-23T00:00:00Z",
            "resources": {},
            "schema": "arc3.build-001.stage-09-development-recovery-acceptance.v0.1",
            "status": "FAILED_INFRASTRUCTURE",
            "terminal": {
                "artifact_core_hash": aggregate["artifact_core_hash"],
                "cell_finalization_hash": cell_finalization_hash,
                "cell_receipt_hash": receipt_hash,
                "execution_complete": False,
                "exposure_event_hash": exposure_hash,
                "exposure_ledger_sha256": exposure_ledger_hash,
                "failed_cell_ordinal": 0,
                "failure_kind": "terminal-cell-infrastructure-failure",
                "file_bytes": aggregate_path.stat().st_size,
                "file_sha256": aggregate_file_hash,
                "path": aggregate_path.resolve().as_posix(),
                "schema": "arc3.build-001.stage-09-aggregate.v0.4",
                "status": "FAILED_INFRASTRUCTURE",
                "terminal_finalization": {
                    "file_sha256": sha256_file(finalization_path),
                    "path": finalization_path.resolve().as_posix(),
                    "recovery_kind": None,
                    "terminal_authority_passed": True,
                    "terminal_finalization_hash": finalization["terminal_finalization_hash"],
                    "timing_measurement_available": True,
                    "within_overall_active_wall": True,
                },
            },
            "validation": {},
        },
        hash_field="evidence_hash",
    )
    acceptance_path = tmp_path / "acceptance.json"
    _write_pretty_json(acceptance_path, acceptance)
    arguments: dict[str, Any] = {
        "expected_build_000_commit": build_000_commit,
        "expected_build_000_root": build_000_root,
        "expected_build_000_tree": build_000_tree,
        "expected_development_identifier_sha256": identifier_hash,
        "expected_development_predeclaration_core_hash": predeclaration_core_hash,
        "expected_development_predeclaration_file_sha256": predeclaration_file_hash,
        "expected_file_sha256": sha256_file(acceptance_path),
        "expected_holdout_nonconsumption_sha256": holdout_hash,
        "expected_verification_hash": acceptance["evidence_hash"],
        "source_root": tmp_path,
    }
    return {
        "acceptance_path": acceptance_path,
        "aggregate_path": aggregate_path,
        "arguments": arguments,
        "finalization_path": finalization_path,
        "harness_root": harness_root,
    }


def _refresh_acceptance_arguments(fixture: dict[str, Any], acceptance: dict[str, Any]) -> None:
    path = fixture["acceptance_path"]
    arguments = fixture["arguments"]
    assert isinstance(path, Path)
    assert isinstance(arguments, dict)
    _write_pretty_json(path, acceptance)
    arguments["expected_file_sha256"] = sha256_file(path)
    arguments["expected_verification_hash"] = acceptance["evidence_hash"]


def _authorize_synthetic_acceptance(
    fixture: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    arguments = fixture["arguments"]
    assert isinstance(arguments, dict)
    monkeypatch.setattr(
        authority,
        "_STAGE09_ACCEPTANCE_FILE_SHA256",
        arguments["expected_file_sha256"],
    )
    monkeypatch.setattr(
        authority,
        "_STAGE09_ACCEPTANCE_EVIDENCE_HASH",
        arguments["expected_verification_hash"],
    )
    monkeypatch.setattr(
        authority,
        "_stage09_partial_graph_authority",
        lambda **_kwargs: None,
    )


def _partial_inventory_fixture(tmp_path: Path) -> dict[str, Any]:
    stage_root = tmp_path / "stage09"
    work_root = stage_root / "development-recovery-work-attempt-01"
    aggregate_path = stage_root / "development-recovery-attempt-01.json"
    finalization_path = stage_root / "development-recovery-attempt-01.json.finalization.json"
    exposure_path = stage_root / "public-exposure.jsonl"
    cell_id = "s09-00-synthetic"
    cell_prefix = f"00-{cell_id}"
    filename = f"{cell_prefix}.json"
    relative_paths = (
        Path("active-cell-segments") / filename,
        Path("cell-finalizations") / filename,
        Path("launch-authorizations") / filename,
        Path("parent-evidence") / filename,
        Path("parent-receipts") / filename,
        Path("parent-streams") / cell_prefix / "stderr.bin",
        Path("parent-streams") / cell_prefix / "stdout.bin",
        Path("process-launches") / filename,
        Path("run-clock.json"),
        Path("spawn-intents") / filename,
        Path("specs") / filename,
        Path("supervision-receipts") / filename,
        Path("worker-aborts") / filename,
    )
    for index, relative in enumerate(relative_paths):
        artifact = work_root / relative
        artifact.parent.mkdir(parents=True, exist_ok=True)
        artifact.write_bytes(f"artifact-{index}:{relative.as_posix()}\n".encode())
    stage_root.mkdir(parents=True, exist_ok=True)
    aggregate_path.write_bytes(b"aggregate\n")
    finalization_path.write_bytes(b"finalization\n")
    exposure_path.write_bytes(b"exposure\n")
    inventory, key_paths = authority._stage09_partial_evidence_inventory(
        aggregate_path=aggregate_path,
        finalization_path=finalization_path,
        exposure_path=exposure_path,
        work_root=work_root,
        cell_ordinal=0,
        cell_id=cell_id,
    )
    return {
        "aggregate_path": aggregate_path,
        "cell_id": cell_id,
        "expected_file_count": len(inventory),
        "expected_key_artifacts": {label: sha256_file(path) for label, path in key_paths.items()},
        "expected_manifest_sha256": sha256_bytes(canonical_json_bytes(inventory)),
        "expected_total_bytes": sum(item["bytes"] for item in inventory.values()),
        "exposure_path": exposure_path,
        "finalization_path": finalization_path,
        "key_paths": key_paths,
        "work_root": work_root,
    }


def test_stage09_failed_infrastructure_requires_frozen_acceptance_identity(
    tmp_path: Path,
) -> None:
    fixture = _stage09_partial_fixture(tmp_path)
    assert authority._STAGE09_ACCEPTANCE_FILE_SHA256 == (
        "sha256:e44473f2335fee5ccf8bd4f911a0d615caf92f9696375ebe6e57697e5622b3b8"
    )
    assert authority._STAGE09_ACCEPTANCE_EVIDENCE_HASH == (
        "sha256:29d1961ae7b30e50222806a066b4d1d4a51c7255391a06a0b87ed9d1e8140b23"
    )

    with pytest.raises(EvaluationError, match="acceptance identity changed"):
        authority._stage09_verification_summary(
            fixture["acceptance_path"],
            **fixture["arguments"],
        )


def test_stage09_failed_infrastructure_requires_live_raw_graph(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _stage09_partial_fixture(tmp_path)
    arguments = fixture["arguments"]
    assert isinstance(arguments, dict)
    monkeypatch.setattr(
        authority,
        "_STAGE09_ACCEPTANCE_FILE_SHA256",
        arguments["expected_file_sha256"],
    )
    monkeypatch.setattr(
        authority,
        "_STAGE09_ACCEPTANCE_EVIDENCE_HASH",
        arguments["expected_verification_hash"],
    )

    with pytest.raises(EvaluationError, match="preflight output path must be an absolute path"):
        authority._stage09_verification_summary(
            fixture["acceptance_path"],
            **arguments,
        )


@pytest.mark.parametrize("tamper", ["missing", "swapped", "tampered"])
def test_stage09_partial_underlying_receipt_drift_fails_closed(
    tmp_path: Path,
    tamper: str,
) -> None:
    fixture = _partial_inventory_fixture(tmp_path)
    key_paths = fixture["key_paths"]
    assert isinstance(key_paths, dict)
    parent_receipt = key_paths["parent_receipt"]
    supervision_receipt = key_paths["supervision_receipt"]
    launch_authorization = key_paths["launch_authorization"]
    assert isinstance(parent_receipt, Path)
    assert isinstance(supervision_receipt, Path)
    assert isinstance(launch_authorization, Path)
    if tamper == "missing":
        parent_receipt.unlink()
    elif tamper == "swapped":
        parent_bytes = parent_receipt.read_bytes()
        supervision_bytes = supervision_receipt.read_bytes()
        parent_receipt.write_bytes(supervision_bytes)
        supervision_receipt.write_bytes(parent_bytes)
    else:
        launch_authorization.write_bytes(launch_authorization.read_bytes() + b"tamper\n")

    with pytest.raises(EvaluationError, match=r"evidence|artifact|file hash"):
        authority._validated_stage09_partial_evidence_inventory(
            aggregate_path=fixture["aggregate_path"],
            finalization_path=fixture["finalization_path"],
            exposure_path=fixture["exposure_path"],
            work_root=fixture["work_root"],
            cell_ordinal=0,
            cell_id=fixture["cell_id"],
            expected_file_count=fixture["expected_file_count"],
            expected_total_bytes=fixture["expected_total_bytes"],
            expected_manifest_sha256=fixture["expected_manifest_sha256"],
            expected_key_artifacts=fixture["expected_key_artifacts"],
        )


def test_stage09_failed_infrastructure_acceptance_is_evidence_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _stage09_partial_fixture(tmp_path)
    _authorize_synthetic_acceptance(fixture, monkeypatch)
    summary = authority._stage09_verification_summary(
        fixture["acceptance_path"],
        **fixture["arguments"],
    )

    assert summary["status"] == "FAILED_INFRASTRUCTURE"
    assert summary["execution_complete"] is False
    assert summary["authority_scope"] == "EVIDENCE_INTEGRITY_ONLY"
    assert summary["stage09_acceptance_satisfied"] is False
    assert summary["stage09_pass"] is False
    assert summary["performance_claim"] is False


@pytest.mark.parametrize(
    "tamper",
    [
        "status",
        "execution-complete",
        "exposure-count",
        "environment-opened",
        "gameplay",
        "rerun",
        "holdout",
        "stage09-promotion",
    ],
)
def test_stage09_failed_infrastructure_resealed_semantic_tamper_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    tamper: str,
) -> None:
    fixture = _stage09_partial_fixture(tmp_path)
    acceptance_path = fixture["acceptance_path"]
    assert isinstance(acceptance_path, Path)
    acceptance = json.loads(acceptance_path.read_text(encoding="utf-8"))
    if tamper == "status":
        acceptance["status"] = "PASS"
    elif tamper == "execution-complete":
        acceptance["attempt"]["execution_complete"] = True
    elif tamper == "exposure-count":
        acceptance["attempt"]["exposed_cell_count"] = True
    elif tamper == "environment-opened":
        acceptance["attempt"]["environment_opened_cell_count"] = 1
    elif tamper == "gameplay":
        acceptance["attempt"]["gameplay_action_count"] = 1
    elif tamper == "rerun":
        acceptance["protocol"]["rerun_allowed"] = True
    elif tamper == "holdout":
        acceptance["integrity"]["public_holdout_status"] = "OPENED"
    else:
        acceptance["decision"]["stage_acceptance_satisfied"] = True
        acceptance["decision"]["holdout_opening_predicate_stage_09_pass"] = True
    acceptance = seal_object(acceptance, hash_field="evidence_hash")
    _refresh_acceptance_arguments(fixture, acceptance)
    _authorize_synthetic_acceptance(fixture, monkeypatch)

    with pytest.raises(EvaluationError):
        authority._stage09_verification_summary(
            acceptance_path,
            **fixture["arguments"],
        )


def test_stage09_failed_infrastructure_resealed_raw_drift_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _stage09_partial_fixture(tmp_path)
    aggregate_path = fixture["aggregate_path"]
    acceptance_path = fixture["acceptance_path"]
    assert isinstance(aggregate_path, Path)
    assert isinstance(acceptance_path, Path)
    aggregate = json.loads(aggregate_path.read_text(encoding="utf-8"))
    aggregate["holdout"]["status"] = "OPENED"
    aggregate = seal_object(aggregate, hash_field="artifact_core_hash")
    atomic_write_json(aggregate_path, aggregate)
    acceptance = json.loads(acceptance_path.read_text(encoding="utf-8"))
    acceptance["terminal"]["artifact_core_hash"] = aggregate["artifact_core_hash"]
    acceptance["terminal"]["file_bytes"] = aggregate_path.stat().st_size
    acceptance["terminal"]["file_sha256"] = sha256_file(aggregate_path)
    acceptance = seal_object(acceptance, hash_field="evidence_hash")
    _refresh_acceptance_arguments(fixture, acceptance)
    _authorize_synthetic_acceptance(fixture, monkeypatch)

    with pytest.raises(EvaluationError, match="aggregate is not the accepted partial terminal"):
        authority._stage09_verification_summary(
            acceptance_path,
            **fixture["arguments"],
        )


def test_stage09_failed_infrastructure_resealed_finalization_drift_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _stage09_partial_fixture(tmp_path)
    finalization_path = fixture["finalization_path"]
    acceptance_path = fixture["acceptance_path"]
    assert isinstance(finalization_path, Path)
    assert isinstance(acceptance_path, Path)
    finalization = json.loads(finalization_path.read_text(encoding="utf-8"))
    finalization["recovery_kind"] = (
        "terminal-output-durable-finalization-missing-after-interruption"
    )
    finalization = seal_object(finalization, hash_field="terminal_finalization_hash")
    atomic_write_json(finalization_path, finalization)
    acceptance = json.loads(acceptance_path.read_text(encoding="utf-8"))
    binding = acceptance["terminal"]["terminal_finalization"]
    binding["file_sha256"] = sha256_file(finalization_path)
    binding["terminal_finalization_hash"] = finalization["terminal_finalization_hash"]
    acceptance = seal_object(acceptance, hash_field="evidence_hash")
    _refresh_acceptance_arguments(fixture, acceptance)
    _authorize_synthetic_acceptance(fixture, monkeypatch)

    with pytest.raises(EvaluationError, match="finalization authority changed"):
        authority._stage09_verification_summary(
            acceptance_path,
            **fixture["arguments"],
        )


def test_stage09_failed_infrastructure_dirty_harness_source_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _stage09_partial_fixture(tmp_path)
    _authorize_synthetic_acceptance(fixture, monkeypatch)
    harness_root = fixture["harness_root"]
    assert isinstance(harness_root, Path)
    (harness_root / "untracked.txt").write_text("drift\n", encoding="utf-8")

    with pytest.raises(EvaluationError, match="exact clean detached Git source"):
        authority._stage09_verification_summary(
            fixture["acceptance_path"],
            **fixture["arguments"],
        )
