from __future__ import annotations

from pathlib import Path

from arc3.evaluation.artifacts import atomic_write_json, seal_object
from arc3.evaluation.stage10_regression import (
    PREDECLARATION_PATH,
    STAGE14_PROTOCOL_SHA256,
    Stage10Status,
    SuiteDisposition,
    SuiteValidation,
    build_suite_plan,
    classify_stage,
    validate_ablations,
    validate_action,
    validate_predeclaration_bytes,
    validate_rule_change,
)
from arc3.trace import sha256_json

ROOT = Path(__file__).resolve().parents[2]
COMMIT = "a" * 40


def _validation(suite_id: str, disposition: SuiteDisposition) -> SuiteValidation:
    return SuiteValidation(
        suite_id=suite_id,
        disposition=disposition,
        predicates={"floor": disposition is SuiteDisposition.PASS},
        measurements={},
    )


def test_predeclaration_bytes_and_non_playing_plan_are_frozen(tmp_path: Path) -> None:
    declaration = validate_predeclaration_bytes((ROOT / PREDECLARATION_PATH).read_bytes())
    assert declaration["status"] == "FROZEN_PREMEASUREMENT"
    plan = build_suite_plan(
        python=Path("C:/Python/python.exe"),
        source_root=ROOT,
        attempt_root=tmp_path / "attempt",
        frozen_commit=COMMIT,
    )
    assert [suite.suite_id for suite in plan] == [
        "stage13-evaluate",
        "stage13-verify",
        "stage14-ablations",
        "palette-equivariance",
        "action-equivariance",
        "rule-change",
        "checkpoint-replay",
        "resource-profile",
        "competition-integrity",
    ]
    stage13 = plan[0].command
    assert stage13[stage13.index("--partition") + 1] == "smoke"
    assert "evaluate-public" not in " ".join(item for suite in plan for item in suite.command)


def test_fail_closed_classification_preserves_mechanism_failure() -> None:
    ids = {
        "stage13-evaluate",
        "stage13-verify",
        "stage14-ablations",
        "palette-equivariance",
        "action-equivariance",
        "rule-change",
        "checkpoint-replay",
        "resource-profile",
        "competition-integrity",
    }
    passing = [_validation(suite_id, SuiteDisposition.PASS) for suite_id in sorted(ids)]
    assert classify_stage(passing) is Stage10Status.PASS
    passing[0] = _validation(passing[0].suite_id, SuiteDisposition.FAILED_MECHANISM)
    assert classify_stage(passing) is Stage10Status.FAILED_MECHANISM
    passing[1] = _validation(passing[1].suite_id, SuiteDisposition.FAILED_INFRASTRUCTURE)
    assert classify_stage(passing) is Stage10Status.FAILED_INFRASTRUCTURE
    assert classify_stage(passing[:-1]) is Stage10Status.FAILED_INFRASTRUCTURE


def test_action_floor_uses_exact_528_numerator_and_denominator(tmp_path: Path) -> None:
    procedural = {
        "pair_count": 128,
        "passed_pairs": 128,
        "post_calibration_inverse_request_denominator": 528,
        "post_calibration_inverse_request_numerator": 528,
    }
    report = {
        "acceptance": {"all": True},
        "checkpoint_resume_suite": {"case_count": 16, "passed_cases": 16},
        "procedural_paired_suite": procedural,
        "schema": "arc3.build-001.stage-05-action-equivariance.v0.1",
        "source_identity": {"dirty_worktree": False, "git_commit": COMMIT},
        "status": "PASS",
    }
    path = tmp_path / "action.json"
    atomic_write_json(path, seal_object(report, hash_field="artifact_core_hash"))
    assert validate_action(path, frozen_commit=COMMIT).disposition is SuiteDisposition.PASS
    procedural["post_calibration_inverse_request_numerator"] = 527
    atomic_write_json(path, seal_object(report, hash_field="artifact_core_hash"))
    failed = validate_action(path, frozen_commit=COMMIT)
    assert failed.disposition is SuiteDisposition.FAILED_MECHANISM
    assert failed.predicates["inverse_528_of_528"] is False


def test_rule_exit_one_is_valid_evidence_when_frozen_floor_passes(tmp_path: Path) -> None:
    cases = [
        {
            "case": {"family": "action_effect_rotation"},
            "case_passed": True,
        }
        for _ in range(32)
    ]
    cases.extend({"case": {"family": "traversability"}, "case_passed": False} for _ in range(32))
    report = {
        "acceptance": {
            "aggregate_trace_replay_and_immutability": True,
            "competition_integrity": True,
            "holdout_integrity": True,
        },
        "decision_rule": {"infrastructure_failure_count": 0},
        "intervention_suite": {
            "case_count": 64,
            "cases": cases,
            "exercised_cases": 64,
            "passed_cases": 32,
        },
        "schema": "arc3.build-001.stage-06-rule-change-reopening.v0.1",
        "source_identity": {"dirty_worktree": False, "git_commit": COMMIT},
        "source_identity_stability": {"passed": True},
        "stationary_noise_control_suite": {
            "case_count": 32,
            "passed_cases": 0,
            "resolved_as_noise": 0,
        },
        "status": "FAILED_MECHANISM",
    }
    path = tmp_path / "rule.json"
    atomic_write_json(path, seal_object(report, hash_field="artifact_core_hash"))
    validation = validate_rule_change(path, frozen_commit=COMMIT, returncode=1)
    assert validation.disposition is SuiteDisposition.PASS
    assert validation.measurements["child_status"] == "FAILED_MECHANISM"
    invalid = validate_rule_change(path, frozen_commit=COMMIT, returncode=2)
    assert invalid.disposition is SuiteDisposition.FAILED_INFRASTRUCTURE


def test_stage14_floor_verifies_trace_style_hash_and_total_actions(tmp_path: Path) -> None:
    full = {"completed": 8, "total_actions": 157}
    report = {
        "dirty_worktree": False,
        "git_commit": COMMIT,
        "protocol_manifest_hash": STAGE14_PROTOCOL_SHA256,
        "protocol_manifest_matches_run": True,
        "schema": "arc3.ablations.paired.v0.1",
        "status": "PASS",
        "variants": {
            "A4": {"aggregate": {"completed": 1}},
            "A5": {"aggregate": {"completed": 0}},
            "FULL": {"aggregate": full},
        },
        "verified": True,
    }
    report["artifact_core_hash"] = sha256_json(report)
    path = tmp_path / "ablations.json"
    atomic_write_json(path, report)
    assert validate_ablations(path, frozen_commit=COMMIT).disposition is SuiteDisposition.PASS
    full["total_actions"] = 158
    report["artifact_core_hash"] = sha256_json(
        {key: value for key, value in report.items() if key != "artifact_core_hash"}
    )
    atomic_write_json(path, report)
    failed = validate_ablations(path, frozen_commit=COMMIT)
    assert failed.disposition is SuiteDisposition.FAILED_MECHANISM
    assert failed.predicates["full_actions_at_most_157"] is False
