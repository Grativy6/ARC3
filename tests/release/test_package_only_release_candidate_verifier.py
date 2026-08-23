"""Forward-audit tests for the Build 001 package-only verifier profile."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import scripts.release_candidate_verifier as verifier
from scripts.release_candidate_verifier import (
    BUILD001_PACKAGE_ONLY_PROFILE,
    CommandSpec,
    _overall_status,
    _package_runtime_format_metrics,
    _validate_package_only_plan,
    build_plan,
    canonical_json_bytes,
)


def test_package_only_plan_has_no_public_inventory_or_gameplay(tmp_path: Path) -> None:
    repository = Path(__file__).resolve().parents[2]
    specs = build_plan(
        repository=repository,
        output_root=tmp_path / "output",
        transient_root=tmp_path / "transient",
        expectation=None,
        uv_command=("uv",),
        official_environments=None,
        profile=BUILD001_PACKAGE_ONLY_PROFILE,
    )
    by_id = {spec.check_id: spec for spec in specs}
    assert set(by_id) == {
        "dependency-lock",
        "dependency-sync",
        "doctor",
        "mypy-strict",
        "offline-package-a",
        "offline-package-b",
        "offline-package-startup",
        "package-safe-test-suite",
        "package-integrity",
        "ruff-format",
        "ruff-lint",
        "trace-replay-tamper",
    }
    assert by_id["dependency-sync"].argv[-1] == "--offline"
    assert by_id["dependency-lock"].argv[-1] == "--offline"
    assert "--package-only" in by_id["package-integrity"].argv
    assert "scripts.package_only_pytest" in by_id["package-safe-test-suite"].argv
    assert "--select-in-process-tests" in by_id["package-safe-test-suite"].argv
    assert "package-only-test-guard.json" in " ".join(by_id["package-safe-test-suite"].argv)
    safe_test_argv = set(by_id["package-safe-test-suite"].argv)
    assert {
        "tests/integration/test_evaluation_cli.py",
        "tests/integration/test_kaggle_package_determinism.py",
        "tests/integration/test_retrodiction_decision_integration.py",
        "tests/integration/test_stage16_runtime_profile.py",
    } <= safe_test_argv
    assert all(
        by_id[check_id].measure_peak_rss
        for check_id in (
            "offline-package-a",
            "offline-package-b",
            "offline-package-startup",
        )
    )
    rendered = canonical_json_bytes([spec.to_dict() for spec in specs]).lower()
    for forbidden in (
        b"scripts.evaluate_public",
        b"official-inventory",
        b"official-smoke",
        b"docs/evaluation/",
        b"--manifest",
        b"--run-state",
    ):
        assert forbidden not in rendered


@pytest.mark.parametrize(
    "argv",
    [
        (sys.executable, "-m", "scripts.evaluate_public", "--inventory-only"),
        (sys.executable, "scripts/evaluate_public.py", "--inventory-only"),
        (sys.executable, "tool.py", "--manifest", "sealed.json"),
    ],
)
def test_package_only_plan_guard_rejects_public_semantic_reachability(
    argv: tuple[str, ...],
) -> None:
    dangerous = CommandSpec("dangerous", "fixture", argv, 30.0)
    with pytest.raises(ValueError, match="package-only"):
        _validate_package_only_plan((dangerous,))


def test_package_only_plan_rejects_substring_only_integrity_impostor(tmp_path: Path) -> None:
    impostor = CommandSpec(
        "package-integrity",
        "integrity",
        (
            sys.executable,
            "-c",
            "print('scripts.check_competition_integrity')",
            "--package-only",
            "--root",
            str(tmp_path),
            "--archive",
            str(tmp_path / "candidate.zip"),
            "--output",
            str(tmp_path / "receipt.json"),
        ),
        30.0,
        dependencies=("dependency-sync", "dependency-lock", "offline-package-a"),
    )

    with pytest.raises(ValueError, match="production static scanner"):
        _validate_package_only_plan((impostor,))


def test_package_only_plan_rejects_extra_static_scanner_overrides(tmp_path: Path) -> None:
    evasive = CommandSpec(
        "package-integrity",
        "integrity",
        (
            sys.executable,
            "-m",
            "scripts.check_competition_integrity",
            "--root",
            str(tmp_path),
            "--package-only",
            "--archive",
            str(tmp_path / "candidate.zip"),
            "--output",
            str(tmp_path / "receipt.json"),
            "--max-candidate-bytes",
            "1",
        ),
        30.0,
        dependencies=("dependency-sync", "dependency-lock", "offline-package-a"),
    )

    with pytest.raises(ValueError, match="argv shape"):
        _validate_package_only_plan((evasive,))


def test_missing_private_surface_keeps_package_profile_blocked() -> None:
    passing = verifier.internal_result("package-check", "fixture", status="PASS")
    blocked = verifier.internal_result(
        "private-kaggle-surfaces",
        "external-boundary",
        status="BLOCKED_EXTERNAL",
    )
    assert _overall_status((passing, blocked), blocked_is_complete=True) == "BLOCKED_EXTERNAL"
    assert _overall_status((passing, blocked)) == "FAILED_MECHANISM"


def test_private_surface_boundary_does_not_claim_unassessed_inputs_are_unavailable() -> None:
    details, reason = verifier._private_kaggle_surface_boundary()

    assert details["availability_assessment"] == "NOT_ASSESSED"
    assert details["compatibility_status"] == "NOT_VERIFIED"
    assert details["access_attempted"] is False
    assert all(
        details[key] == "NOT_PROVIDED_TO_VERIFIER"
        for key in (
            "exact_private_gateway",
            "exact_private_platform_agents_input",
            "exact_private_scorer",
            "exact_private_wheel_inventory",
        )
    )
    assert "unavailable" not in canonical_json_bytes(details).decode("utf-8").lower()
    assert "not provided" in reason
    assert "availability was not assessed" in reason


def test_package_workflow_normalizes_expected_blocked_exit_only_after_receipt_checks() -> None:
    repository = Path(__file__).resolve().parents[2]
    workflow = (repository / ".github/workflows/build001-package-only.yml").read_text(
        encoding="utf-8"
    )

    expected_exit = workflow.index("if ($verifierExit -ne 1)")
    blocked_status = workflow.index('$receipt.status -ne "BLOCKED_EXTERNAL"')
    sealed_boundary = workflow.index("$receipt.sealed_artifact_set.complete")
    normalized_exit = workflow.index("exit 0", sealed_boundary)

    assert expected_exit < blocked_status < sealed_boundary < normalized_exit
    assert 'push:\n    branches:\n      - "build/**"' in workflow
    assert "pull_request:\n    branches:\n      - main" in workflow


def test_package_workflow_uploads_available_failure_evidence() -> None:
    repository = Path(__file__).resolve().parents[2]
    workflow = (repository / ".github/workflows/build001-package-only.yml").read_text(
        encoding="utf-8"
    )

    environment_export = workflow.index('"ARC3_OUTPUT_ROOT=$outputRoot"')
    verifier_launch = workflow.index("& $python -m scripts.release_candidate_verifier")
    evidence_step = workflow.index("Detect verifier evidence after success or failure")
    upload_step = workflow.index("Upload hash-bound verifier evidence")

    assert environment_export < verifier_launch < evidence_step < upload_step
    assert "id: evidence\n        if: always()" in workflow
    assert "if: always() && steps.evidence.outputs.available == 'true'" in workflow
    assert "if-no-files-found: error" in workflow


def test_package_runtime_format_metrics_bind_archive_and_wheel_inventory(
    tmp_path: Path,
) -> None:
    (tmp_path / "arc3-kaggle-candidate.zip").write_bytes(b"candidate")
    (tmp_path / "arc3-first-party.zip").write_bytes(b"payload")
    (tmp_path / "runtime-wheels-linux-cp312.json").write_text(
        '{"packages":[{"name":"alpha"},{"name":"beta"}]}',
        encoding="utf-8",
    )

    metrics = _package_runtime_format_metrics(tmp_path)

    assert metrics["archive_size_bytes"] == len(b"candidate")
    assert metrics["payload_size_bytes"] == len(b"payload")
    assert metrics["runtime_wheel_count"] == 2
    assert isinstance(metrics["runtime_wheel_names_sha256"], str)
