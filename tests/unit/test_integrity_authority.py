from __future__ import annotations

import importlib
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import arc3.evaluation.integrity_authority as authority
from arc3.errors import EvaluationError
from arc3.evaluation.artifacts import atomic_write_json, seal_object, sha256_file
from arc3.integrity import INTEGRITY_SCHEMA, IntegrityReceipt


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
