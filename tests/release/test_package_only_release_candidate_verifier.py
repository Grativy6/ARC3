"""Forward-audit tests for the Build 001 package-only verifier profile."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import scripts.release_candidate_verifier as verifier
from scripts.package_only_pytest import (
    BUILD001_BOUNDARY_EXCLUSIONS,
    ORDINARY_CI_FULL_SUITE_COMMAND,
    _PytestEvidence,
    build001_test_selection,
)
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
    }
    assert by_id["dependency-sync"].argv[-1] == "--offline"
    assert by_id["dependency-lock"].argv[-1] == "--offline"
    assert "--package-only" in by_id["package-integrity"].argv
    assert (
        by_id["package-integrity"].argv[
            by_id["package-integrity"].argv.index("--expected-commit") + 1
        ]
        == "{CANDIDATE_COMMIT}"
    )
    assert "scripts.package_only_pytest" in by_id["package-safe-test-suite"].argv
    assert "--select-in-process-tests" in by_id["package-safe-test-suite"].argv
    assert "--build001-boundary-policy" in by_id["package-safe-test-suite"].argv
    assert by_id["package-safe-test-suite"].timeout_seconds == 2700.0
    assert (
        by_id["package-safe-test-suite"].argv[
            by_id["package-safe-test-suite"].argv.index("--expected-commit") + 1
        ]
        == "{CANDIDATE_COMMIT}"
    )
    assert "package-only-test-guard.json" in " ".join(by_id["package-safe-test-suite"].argv)
    assert "--ignore" not in by_id["package-safe-test-suite"].argv
    selection = build001_test_selection(repository)
    assert "tests/property/test_trace_properties.py" in selection.selected_test_files
    assert all(
        relative in selection.selected_test_files
        for relative in (
            "tests/replay/test_controller_checkpoint.py",
            "tests/replay/test_legacy_checkpoint_migration.py",
            "tests/replay/test_memory_source_replay.py",
            "tests/replay/test_retrodiction_checkpoint.py",
            "tests/replay/test_trace_replay.py",
        )
    )
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


def test_rendered_package_only_plan_preserves_one_literal_commit_binding(
    tmp_path: Path,
) -> None:
    repository = Path(__file__).resolve().parents[2]
    output_root = tmp_path / "output"
    specs = build_plan(
        repository=repository,
        output_root=output_root,
        transient_root=tmp_path / "transient",
        expectation=None,
        uv_command=("uv",),
        official_environments=None,
        profile=BUILD001_PACKAGE_ONLY_PROFILE,
    )
    commit = "a" * 40
    rendered = tuple(verifier._replace_candidate_commit(spec, commit) for spec in specs)

    _validate_package_only_plan(
        rendered,
        repository=repository,
        output_root=output_root,
    )

    mismatched = tuple(
        verifier.replace(
            spec,
            argv=tuple(
                "b" * 40 if spec.check_id == "package-integrity" and value == commit else value
                for value in spec.argv
            ),
        )
        for spec in rendered
    )
    with pytest.raises(ValueError, match="bind different commits"):
        _validate_package_only_plan(
            mismatched,
            repository=repository,
            output_root=output_root,
        )


def test_package_only_test_selection_is_exact_and_full_ci_retains_excluded_coverage() -> None:
    repository = Path(__file__).resolve().parents[2]
    selection = build001_test_selection(repository)
    reasons = dict(BUILD001_BOUNDARY_EXCLUSIONS)
    workflow = (repository / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    assert selection.selected_test_files
    assert "tests/integrity/test_nested_archive_scan.py" in selection.selected_test_files
    assert tuple(sorted(reasons)) == tuple(path for path, _ in selection.boundary_exclusion_reasons)
    assert all(reason.strip() for reason in reasons.values())
    assert {
        "tests/evaluation/test_build003_curriculum.py",
        "tests/evaluation/test_build003_development_performance.py",
        "tests/evaluation/test_build003_protocol_v02.py",
        "tests/evaluation/test_build003_results.py",
        "tests/integration/test_pinned_agents_framework.py",
        "tests/integrity/test_dependencies.py",
        "tests/integrity/test_first_party_license.py",
        "tests/integrity/test_receipt.py",
        "tests/integrity/test_secret_scan.py",
        "tests/unit/test_diagnose_hot_path.py",
        "tests/unit/test_measure_hot_path.py",
    } <= set(reasons)
    assert (
        "tests/evaluation/test_build003_development_performance.py"
        not in selection.selected_test_files
    )
    assert f"run: {ORDINARY_CI_FULL_SUITE_COMMAND}" in workflow
    assert "scripts.package_only_pytest" not in workflow
    assert "--ignore" not in workflow


def test_package_only_collection_count_comes_from_finished_items(tmp_path: Path) -> None:
    test_file = tmp_path / "tests" / "test_fixture.py"
    session = type(
        "FinishedCollection",
        (),
        {
            "items": [type("Item", (), {"path": test_file})()],
            "testscollected": 0,
        },
    )()
    evidence = _PytestEvidence(tmp_path)

    evidence.pytest_collection_finish(session)

    assert evidence.collected_test_count == 1
    assert evidence.collected_test_files == ("tests/test_fixture.py",)


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


@pytest.mark.parametrize(
    "argv",
    [
        (sys.executable, "-m", "pytest", "-q", "tests/replay"),
        ("pytest", "-q", "tests/replay"),
        ("pytest.exe", "-q", "tests/replay"),
    ],
)
def test_package_only_plan_rejects_every_direct_pytest_command(
    argv: tuple[str, ...],
) -> None:
    direct = CommandSpec("unguarded-tests", "tests", argv, 30.0)
    with pytest.raises(ValueError, match="direct pytest"):
        _validate_package_only_plan((direct,))


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


def test_package_runtime_format_metrics_bind_archive_and_wheel_inventory() -> None:
    metrics = _package_runtime_format_metrics(
        candidate_snapshot=b"candidate",
        payload_snapshot=b"payload",
        candidate_members={
            "runtime-wheels-linux-cp312.json": (b'{"packages":[{"name":"alpha"},{"name":"beta"}]}')
        },
    )

    assert metrics["archive_size_bytes"] == len(b"candidate")
    assert metrics["payload_size_bytes"] == len(b"payload")
    assert metrics["runtime_wheel_count"] == 2
    assert isinstance(metrics["runtime_wheel_names_sha256"], str)
