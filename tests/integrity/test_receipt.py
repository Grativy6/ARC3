"""Canonical receipt determinism and source-identity tests."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
import scripts.release_candidate_verifier as verifier

import arc3.integrity.scanner as scanner
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
    inputs = first.body["inputs"]
    assurance = first.body["assurance_scope"]
    assert isinstance(inputs, dict)
    assert isinstance(assurance, dict)
    assert "public_identifier_mode" not in inputs
    assert "public_identifier_scan" not in assurance


@pytest.mark.competition
def test_package_only_receipt_cannot_load_or_hash_public_manifest(
    integrity_repo: tuple[Path, str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    root, _, _ = integrity_repo
    policy = root / "policy" / "clean.py"
    policy.write_text("GENERIC_PRIOR = ('north', 'south')\n", encoding="utf-8")

    def refuse_manifest_access(_path: Path) -> scanner.PublicIdentifierSet:
        raise AssertionError("semantic manifest loader must be unreachable")

    monkeypatch.setattr(scanner, "load_public_identifiers", refuse_manifest_access)
    receipt = build_integrity_receipt(
        root,
        policy_paths=("policy",),
        candidate_files=(policy,),
        include_installed_metadata=False,
        semantic_public_manifest_access=False,
    )

    inputs = receipt.body["inputs"]
    assurance = receipt.body["assurance_scope"]
    source_hashes = receipt.body["source_hashes"]
    assert isinstance(inputs, dict)
    assert isinstance(assurance, dict)
    assert isinstance(source_hashes, dict)
    assert inputs["manifest"] is None
    assert inputs["run_state"] is None
    assert inputs["public_identifier_count"] == 0
    assert inputs["public_identifier_mode"] == "disabled-package-only"
    assert receipt.body["passed"] is False
    assert receipt.body["package_only_passed"] is False
    assert receipt.body["full_competition_integrity_status"] == "NOT_EVALUATED_PUBLIC_IDENTIFIERS"
    reachable = inputs["reachable_policy_paths"]
    reachable_hashes = receipt.body["reachable_policy_source_hashes"]
    assert isinstance(reachable, list)
    assert isinstance(reachable_hashes, dict)
    assert set(reachable) == set(reachable_hashes)
    assert receipt.body["production_policy_static_coverage"] == {
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
    }
    assert (
        assurance["public_identifier_scan"]
        == "NOT_EVALUATED_PACKAGE_ONLY_NO_SEMANTIC_MANIFEST_ACCESS"
    )
    assert "docs/evaluation/public-game-partitions.v0.1.json" not in source_hashes


@pytest.mark.competition
def test_package_only_static_coverage_hashes_reachable_module_outside_policy_root(
    integrity_repo: tuple[Path, str, str],
) -> None:
    root, _, _ = integrity_repo
    helper_package = root / "helpers"
    helper_package.mkdir()
    helper_init = helper_package / "__init__.py"
    helper_runtime = helper_package / "runtime.py"
    helper_init.write_text("from helpers.runtime import VALUE\n", encoding="utf-8")
    helper_runtime.write_text("VALUE = 42\n", encoding="utf-8")
    entry = root / "agent" / "my_agent.py"
    entry.write_text("from helpers.runtime import VALUE\n", encoding="utf-8")

    receipt = build_integrity_receipt(
        root,
        policy_paths=("policy",),
        candidate_files=(entry, helper_init, helper_runtime),
        include_installed_metadata=False,
        semantic_public_manifest_access=False,
    )

    reachable = receipt.body["inputs"]["reachable_policy_paths"]  # type: ignore[index]
    hashes = receipt.body["reachable_policy_source_hashes"]
    assert reachable == ["agent/my_agent.py", "helpers/__init__.py", "helpers/runtime.py"]
    assert isinstance(hashes, dict)
    assert set(hashes) == set(reachable)
    assert receipt.body["production_policy_static_coverage"]["status"] == "PASS"  # type: ignore[index]


@pytest.mark.competition
def test_package_only_static_coverage_fails_when_entry_point_is_not_reached(
    integrity_repo: tuple[Path, str, str],
) -> None:
    root, _, _ = integrity_repo
    policy = root / "policy" / "clean.py"
    policy.write_text("VALUE = 1\n", encoding="utf-8")

    receipt = build_integrity_receipt(
        root,
        policy_paths=("policy",),
        candidate_files=(policy,),
        entry_points=("agent/missing.py",),
        include_installed_metadata=False,
        semantic_public_manifest_access=False,
    )

    coverage = receipt.body["production_policy_static_coverage"]
    assert isinstance(coverage, dict)
    assert coverage["entry_points_reached"] == []
    assert coverage["status"] == "FAIL"
    assert receipt.body["package_only_passed"] is False


@pytest.mark.competition
def test_release_validator_recomputes_reachable_policy_hashes(
    integrity_repo: tuple[Path, str, str], tmp_path: Path
) -> None:
    root, _, _ = integrity_repo
    entry = root / "agent" / "my_agent.py"
    receipt = build_integrity_receipt(
        root,
        candidate_files=(entry,),
        include_installed_metadata=False,
        semantic_public_manifest_access=False,
    )
    tampered = dict(receipt.body)
    reachable_hashes = dict(tampered["reachable_policy_source_hashes"])  # type: ignore[arg-type]
    reachable_hashes["agent/my_agent.py"] = f"sha256:{'0' * 64}"
    tampered["reachable_policy_source_hashes"] = reachable_hashes
    source_hashes = dict(tampered["source_hashes"])  # type: ignore[arg-type]
    source_hashes["agent/my_agent.py"] = f"sha256:{'0' * 64}"
    tampered["source_hashes"] = source_hashes
    path = tmp_path / "integrity.json"
    path.write_bytes(IntegrityReceipt(body=tampered).canonical_bytes())

    passed, details = verifier._validate_package_only_integrity(
        path,
        expected_commit="0" * 40,
        repository=root,
    )

    assert passed is False
    assert details["policy_continuity_passed"] is False


@pytest.mark.competition
def test_package_only_receipt_rejects_manifest_identity_inputs(
    integrity_repo: tuple[Path, str, str],
) -> None:
    root, _, _ = integrity_repo
    manifest = root / "docs" / "evaluation" / "public-game-partitions.v0.1.json"
    with pytest.raises(ValueError, match="package-only integrity forbids"):
        build_integrity_receipt(
            root,
            manifest_path=manifest,
            semantic_public_manifest_access=False,
        )


@pytest.mark.competition
@pytest.mark.parametrize(
    "protected_relative",
    (
        "artifacts/sealed-fixture.bin",
        "docs/evaluation/sealed-fixture.json",
        "docs/ledger/build-001-run-state.json",
        "docs/ledger/run-state.json",
    ),
)
def test_package_only_receipt_rejects_protected_candidate_before_scanning(
    integrity_repo: tuple[Path, str, str],
    protected_relative: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, _, _ = integrity_repo

    def refuse_scan(*_args: object, **_kwargs: object) -> tuple[Path, ...]:
        raise AssertionError("protected candidate must be rejected before policy discovery")

    monkeypatch.setattr(scanner, "discover_reachable_policy_files", refuse_scan)
    with pytest.raises(ValueError, match="forbids protected candidate file"):
        build_integrity_receipt(
            root,
            candidate_files=(root / protected_relative,),
            include_installed_metadata=False,
            semantic_public_manifest_access=False,
        )


@pytest.mark.competition
def test_package_only_receipt_requires_explicit_candidate_boundary(
    integrity_repo: tuple[Path, str, str],
) -> None:
    root, _, _ = integrity_repo
    with pytest.raises(ValueError, match="requires an explicit protected-surface-free"):
        build_integrity_receipt(
            root,
            include_installed_metadata=False,
            semantic_public_manifest_access=False,
        )


@pytest.mark.competition
def test_package_only_protected_candidate_cannot_hide_as_receipt_output(
    integrity_repo: tuple[Path, str, str],
) -> None:
    root, _, _ = integrity_repo
    protected = root / "artifacts" / "integrity-receipt.json"
    with pytest.raises(ValueError, match="forbids protected candidate file"):
        build_integrity_receipt(
            root,
            candidate_files=(protected,),
            include_installed_metadata=False,
            receipt_output_path=protected,
            semantic_public_manifest_access=False,
        )


@pytest.mark.competition
def test_package_only_receipt_rejects_symlink_alias_to_protected_candidate(
    integrity_repo: tuple[Path, str, str],
) -> None:
    root, _, _ = integrity_repo
    protected = root / "docs" / "evaluation" / "public-game-partitions.v0.1.json"
    alias = root / "policy" / "protected-alias.py"
    try:
        alias.symlink_to(protected)
    except OSError as error:
        pytest.skip(f"symlink creation is unavailable on this host: {error}")

    with pytest.raises(ValueError, match="forbids protected candidate file"):
        build_integrity_receipt(
            root,
            policy_paths=("policy",),
            candidate_files=(alias,),
            include_installed_metadata=False,
            semantic_public_manifest_access=False,
        )


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
