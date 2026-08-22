"""Canonical receipt determinism and source-identity tests."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from arc3.integrity import IntegrityReceipt, build_integrity_receipt


@pytest.mark.competition
def test_receipt_is_byte_deterministic_and_self_verifying(
    integrity_repo: tuple[Path, str, str],
) -> None:
    root, _, _ = integrity_repo
    policy = root / "policy" / "clean.py"
    policy.write_text("GENERIC_PRIOR = ('north', 'south')\n", encoding="utf-8")
    first = build_integrity_receipt(
        root,
        policy_paths=("policy",),
        candidate_files=(policy,),
        include_installed_metadata=False,
    )
    second = build_integrity_receipt(
        root,
        policy_paths=("policy",),
        candidate_files=(policy,),
        include_installed_metadata=False,
    )
    checks = first.body["checks"]
    assert isinstance(checks, dict)
    assert checks["policy_static"] == {"passed": True}
    assert checks["secret_scan"] == {"passed": True}
    assert checks["supply_chain"] == {"passed": False, "status": "NOT_EVALUATED"}
    assert not first.passed
    assert first.canonical_bytes() == second.canonical_bytes()
    assert IntegrityReceipt.from_bytes(first.canonical_bytes()) == first
    assert first.body["generated_at"] is None


@pytest.mark.competition
def test_source_change_changes_receipt_identity(integrity_repo: tuple[Path, str, str]) -> None:
    root, _, _ = integrity_repo
    policy = root / "policy" / "clean.py"
    policy.write_text("VALUE = 1\n", encoding="utf-8")
    before = build_integrity_receipt(
        root,
        policy_paths=("policy",),
        candidate_files=(policy,),
        include_installed_metadata=False,
    )
    policy.write_text("VALUE = 2\n", encoding="utf-8")
    after = build_integrity_receipt(
        root,
        policy_paths=("policy",),
        candidate_files=(policy,),
        include_installed_metadata=False,
    )
    assert before.receipt_sha256 != after.receipt_sha256
    assert before.body["source_hashes"] != after.body["source_hashes"]


@pytest.mark.competition
def test_manifest_must_match_run_state_declared_identity(
    integrity_repo: tuple[Path, str, str],
) -> None:
    root, _, _ = integrity_repo
    manifest = root / "docs" / "evaluation" / "public-game-partitions.v0.1.json"
    manifest.write_bytes(manifest.read_bytes() + b"\n")
    receipt = build_integrity_receipt(root, include_installed_metadata=False)
    assert not receipt.passed
    assert any(
        finding["rule_id"] == "manifest-identity-mismatch"
        for finding in receipt.body["findings"]
        if isinstance(finding, dict)
    )
    checks = receipt.body["checks"]
    assert isinstance(checks, dict)
    assert checks["source_identity"] == {"passed": False}


@pytest.mark.competition
def test_explicit_manifest_identity_is_an_auditable_override(
    integrity_repo: tuple[Path, str, str],
) -> None:
    root, _, _ = integrity_repo
    manifest = root / "docs" / "evaluation" / "public-game-partitions.v0.1.json"
    changed = manifest.read_bytes() + b"\n"
    manifest.write_bytes(changed)
    expected = "sha256:" + hashlib.sha256(changed).hexdigest()
    receipt = build_integrity_receipt(
        root,
        expected_manifest_sha256=expected,
        include_installed_metadata=False,
    )
    checks = receipt.body["checks"]
    assert isinstance(checks, dict)
    assert checks["source_identity"] == {"passed": True}
    inputs = receipt.body["inputs"]
    assert isinstance(inputs, dict)
    assert inputs["manifest_binding"] == {
        "declaration": "explicit-argument",
        "expected_sha256": expected,
        "issue": None,
    }


@pytest.mark.competition
def test_build_run_holdout_manifest_identity_is_an_auditable_binding(
    integrity_repo: tuple[Path, str, str],
) -> None:
    root, _, _ = integrity_repo
    manifest = root / "docs" / "evaluation" / "public-game-partitions.v0.1.json"
    expected = "sha256:" + hashlib.sha256(manifest.read_bytes()).hexdigest()
    run_state = root / "docs" / "ledger" / "build-001-run-state.json"
    run_state.write_text(
        json.dumps(
            {
                "holdout": {
                    "manifest": "docs/evaluation/public-game-partitions.v0.1.json",
                    "manifest_sha256": expected,
                    "status": "SEALED_UNCONSUMED",
                }
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    receipt = build_integrity_receipt(
        root,
        run_state_path=run_state,
        include_installed_metadata=False,
    )
    checks = receipt.body["checks"]
    assert isinstance(checks, dict)
    assert checks["source_identity"] == {"passed": True}
    inputs = receipt.body["inputs"]
    assert isinstance(inputs, dict)
    assert inputs["manifest_binding"] == {
        "declaration": "docs/ledger/build-001-run-state.json",
        "expected_sha256": expected,
        "issue": None,
    }


@pytest.mark.competition
def test_missing_required_notices_is_explicit_supply_failure(
    integrity_repo: tuple[Path, str, str],
) -> None:
    root, _, _ = integrity_repo
    (root / "THIRD_PARTY_NOTICES.md").unlink()
    receipt = build_integrity_receipt(root, include_installed_metadata=False)
    assert not receipt.passed
    checks = receipt.body["checks"]
    assert isinstance(checks, dict)
    assert checks["supply_chain"] == {"passed": False, "status": "FAIL"}
    assert any(
        finding["rule_id"] == "required-input-missing"
        and finding["path"] == "THIRD_PARTY_NOTICES.md"
        for finding in receipt.body["findings"]
        if isinstance(finding, dict)
    )


@pytest.mark.competition
def test_owner_approved_license_is_reported_from_first_party_inventory(
    integrity_repo: tuple[Path, str, str],
) -> None:
    root, _, _ = integrity_repo
    receipt = build_integrity_receipt(root, include_installed_metadata=False)
    summary = receipt.body["license_summary"]
    assert isinstance(summary, dict)
    assert summary["first_party_license_status"] == "MIT-0"
    assert "owner_license_decision_pending" not in summary
