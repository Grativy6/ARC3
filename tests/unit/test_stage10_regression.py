from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

from arc3.evaluation.artifacts import atomic_write_json, seal_object
from arc3.evaluation.stage10_regression import (
    PREDECLARATION_PATH,
    STAGE10_CHECKPOINT_SCHEMA,
    STAGE14_PROTOCOL_SHA256,
    Stage10Status,
    SuiteDisposition,
    SuiteValidation,
    build_suite_plan,
    classify_stage,
    validate_ablations,
    validate_action,
    validate_checkpoint_replay,
    validate_integrity,
    validate_palette,
    validate_predeclaration_bytes,
    validate_resource_profile,
    validate_rule_change,
    validate_stage13,
    validate_stage13_verification,
)
from arc3.trace import sha256_json

ROOT = Path(__file__).resolve().parents[2]
COMMIT = "a" * 40
ACTION_ACCEPTANCE = {
    name: True
    for name in (
        "aggregate_runtime_integrity",
        "causal_controls",
        "checkpoint_resume",
        "historical_regressions",
        "holdout_integrity",
        "procedural_pairs",
        "registry_bounds",
        "resource_limits",
        "source_clean",
        "static_action_semantics",
    )
}
PALETTE_ACCEPTANCE = {
    **{
        name: True
        for name in (
            "causal_controls",
            "checkpoint_resume",
            "historical_regressions",
            "procedural_pairs",
            "source_clean",
            "within_600_second_wall_limit",
        )
    },
    "registry_max_entries": 16,
}
RULE_ACCEPTANCE = {
    name: True
    for name in (
        "aggregate_trace_replay_and_immutability",
        "checkpoint_resume_pairs",
        "competition_integrity_delegated_to_stage10_parent",
        "holdout_integrity",
        "intervention_cases",
        "noise_controls",
        "resource_limits",
        "socket_deny_guard",
        "source_clean",
        "source_stable",
        "static_action_semantics",
        "verification_receipts",
    )
}


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
    original = ROOT / "docs/evidence/001-10-robustness-regression-predeclaration.json"
    original_hash = f"sha256:{hashlib.sha256(original.read_bytes()).hexdigest()}"
    assert original_hash == (
        "sha256:02ad73f25cd6c21459cf425a29de0b830fa27bd660c58777b272ac57116d26e3"
    )
    assert declaration["supersedes"] == {
        "path": "docs/evidence/001-10-robustness-regression-predeclaration.json",
        "reason": (
            "Pre-execution safety audit required opaque nonconsumption authority, "
            "integrity-first ordering, exact runtime binding, process socket denial, "
            "and fail-closed structural classification."
        ),
        "sha256": original_hash,
    }
    plan = build_suite_plan(
        python=Path("C:/Python/python.exe"),
        source_root=ROOT,
        attempt_root=tmp_path / "attempt",
        frozen_commit=COMMIT,
    )
    assert [suite.suite_id for suite in plan] == [
        "competition-integrity",
        "stage13-evaluate",
        "stage13-verify",
        "stage14-ablations",
        "palette-equivariance",
        "action-equivariance",
        "rule-change",
        "checkpoint-replay",
        "resource-profile",
    ]
    stage13 = plan[1].command
    assert stage13[stage13.index("--partition") + 1] == "smoke"
    assert "evaluate-public" not in " ".join(item for suite in plan for item in suite.command)
    assert all("_stage10_offline_child.py" in suite.command[1] for suite in plan)
    assert all(suite.network_guard_path is not None for suite in plan)
    integrity = plan[0]
    assert "--package-only" in integrity.command
    assert "--manifest" not in integrity.command
    assert "--run-state" not in integrity.command
    assert "--expected-manifest-sha256" not in integrity.command
    assert integrity.authority_path is None
    assert integrity.integrity_composite_path is not None
    assert all(suite.authority_path is not None for suite in plan[1:])


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
        "acceptance": dict(ACTION_ACCEPTANCE),
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
        "acceptance": dict(RULE_ACCEPTANCE),
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


def _write_hash_style(
    path: Path,
    report: dict[str, object],
    *,
    hash_field: str,
    trace_style: bool,
) -> None:
    unsigned = {key: value for key, value in report.items() if key != hash_field}
    if trace_style:
        unsigned[hash_field] = sha256_json(unsigned)
        atomic_write_json(path, unsigned)
    else:
        atomic_write_json(path, seal_object(unsigned, hash_field=hash_field))


def test_structural_tamper_is_infrastructure_across_self_hashed_validators(
    tmp_path: Path,
) -> None:
    action = {
        "acceptance": dict(ACTION_ACCEPTANCE),
        "checkpoint_resume_suite": {"case_count": 16, "passed_cases": 16},
        "procedural_paired_suite": {
            "pair_count": 128,
            "passed_pairs": 128,
            "post_calibration_inverse_request_denominator": 528,
            "post_calibration_inverse_request_numerator": 528,
        },
        "schema": "arc3.build-001.stage-05-action-equivariance.v0.1",
        "source_identity": {"dirty_worktree": False, "git_commit": COMMIT},
        "status": "PASS",
    }
    palette = {
        "acceptance": dict(PALETTE_ACCEPTANCE),
        "checkpoint_resume_suite": {"case_count": 16, "passed_cases": 16},
        "procedural_paired_suite": {"pair_count": 256, "passed_pairs": 256},
        "schema": "arc3.build-001.stage-04-palette-equivariance.v0.1",
        "source_identity": {"dirty_worktree": False, "git_commit": COMMIT},
        "status": "PASS",
    }
    rule_cases = [
        {"case": {"family": "action_effect_rotation"}, "case_passed": True} for _ in range(32)
    ]
    rule_cases.extend(
        {"case": {"family": "traversability"}, "case_passed": False} for _ in range(32)
    )
    rule = {
        "acceptance": dict(RULE_ACCEPTANCE),
        "decision_rule": {"infrastructure_failure_count": 0},
        "intervention_suite": {
            "case_count": 64,
            "cases": rule_cases,
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
    checkpoint = {
        "acceptance": {
            "checkpoint_tamper_rejected": True,
            "deep_exact_continuation": True,
            "deterministic_seed_repeatability": True,
            "fast_exact_continuation": True,
            "trace_replay": True,
            "trace_tamper_rejected": True,
        },
        "deep_continuation": {"path": "DELIBERATIVE"},
        "fast_continuation": {"path": "FAST"},
        "schema": STAGE10_CHECKPOINT_SCHEMA,
        "source_identity": {"dirty_worktree": False, "git_commit": COMMIT},
    }
    ablations = {
        "dirty_worktree": False,
        "git_commit": COMMIT,
        "protocol_manifest_hash": STAGE14_PROTOCOL_SHA256,
        "protocol_manifest_matches_run": True,
        "schema": "arc3.ablations.paired.v0.1",
        "status": "PASS",
        "variants": {
            "A4": {"aggregate": {"completed": 1}},
            "A5": {"aggregate": {"completed": 0}},
            "FULL": {"aggregate": {"completed": 8, "total_actions": 157}},
        },
        "verified": True,
    }
    resource = {
        "git_commit": COMMIT,
        "profile": {
            "decision_latency_seconds": {"maximum": 1.0},
            "kernel_memory_after": {"peak_rss_bytes": 1000},
            "trace_bytes": 1000,
            "verified": True,
        },
        "schema": "arc3.stage16.profile.v0.1",
        "source_identity": {"verified": True},
        "status": "PASS",
    }
    checks = {
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
    integrity: dict[str, object] = {
        "assurance_scope": {
            "kind": "static-only",
            "public_identifier_scan": ("NOT_EVALUATED_PACKAGE_ONLY_NO_SEMANTIC_MANIFEST_ACCESS"),
            "scanner_network_mode": "offline-by-construction",
        },
        "checks": checks,
        "finding_counts": {"blocking": 0, "total": 0, "warnings": 0},
        "full_competition_integrity_status": "NOT_EVALUATED_PUBLIC_IDENTIFIERS",
        "git": {"commit": COMMIT, "dirty_worktree": False},
        "inputs": {
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
            "reachable_policy_paths": ["agent/my_agent.py"],
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
            "reachable_file_count": 1,
            "reachable_paths_hashed": True,
            "status": "PASS",
        },
        "reachable_policy_source_hashes": {"agent/my_agent.py": "sha256:" + "1" * 64},
        "schema": "arc3.integrity.receipt.v0.2",
    }

    def integrity_metric_miss(report: dict[str, object]) -> None:
        report["package_only_passed"] = False
        cast_checks = report["checks"]
        assert isinstance(cast_checks, dict)
        cast_checks["policy_static"] = {"passed": False}
        report["finding_counts"] = {"blocking": 1, "total": 1, "warnings": 0}

    cases = (
        (
            "action",
            action,
            "artifact_core_hash",
            False,
            lambda path: validate_action(path, frozen_commit=COMMIT),
            lambda report: report["source_identity"].__setitem__("git_commit", "b" * 40),
            lambda report: report["procedural_paired_suite"].__setitem__("passed_pairs", 127),
        ),
        (
            "palette",
            palette,
            "artifact_core_hash",
            False,
            lambda path: validate_palette(path, frozen_commit=COMMIT),
            lambda report: report["source_identity"].__setitem__("git_commit", "b" * 40),
            lambda report: report["procedural_paired_suite"].__setitem__("passed_pairs", 255),
        ),
        (
            "rule",
            rule,
            "artifact_core_hash",
            False,
            lambda path: validate_rule_change(path, frozen_commit=COMMIT, returncode=1),
            lambda report: report["source_identity"].__setitem__("git_commit", "b" * 40),
            lambda report: report["intervention_suite"]["cases"][0].__setitem__(
                "case_passed", False
            ),
        ),
        (
            "checkpoint",
            checkpoint,
            "artifact_core_hash",
            False,
            lambda path: validate_checkpoint_replay(path, frozen_commit=COMMIT),
            lambda report: report["source_identity"].__setitem__("git_commit", "b" * 40),
            lambda report: report["acceptance"].__setitem__("trace_replay", False),
        ),
        (
            "ablations",
            ablations,
            "artifact_core_hash",
            True,
            lambda path: validate_ablations(path, frozen_commit=COMMIT),
            lambda report: report.__setitem__("git_commit", "b" * 40),
            lambda report: report["variants"]["FULL"]["aggregate"].__setitem__(
                "total_actions", 158
            ),
        ),
        (
            "resource",
            resource,
            "receipt_sha256",
            True,
            lambda path: validate_resource_profile(path, frozen_commit=COMMIT, returncode=0),
            lambda report: report.__setitem__("git_commit", "b" * 40),
            lambda report: report["profile"]["decision_latency_seconds"].__setitem__(
                "maximum", 3.0
            ),
        ),
        (
            "integrity",
            integrity,
            "receipt_sha256",
            True,
            lambda path: validate_integrity(path, frozen_commit=COMMIT),
            lambda report: report["git"].__setitem__("commit", "b" * 40),
            integrity_metric_miss,
        ),
    )
    for name, report, hash_field, trace_style, validator, source_tamper, metric_miss in cases:
        path = tmp_path / f"{name}.json"
        _write_hash_style(path, report, hash_field=hash_field, trace_style=trace_style)
        assert validator(path).disposition is SuiteDisposition.PASS

        original_schema = report["schema"]
        report["schema"] = "tampered.schema"
        _write_hash_style(path, report, hash_field=hash_field, trace_style=trace_style)
        structurally_tampered = validator(path)
        assert structurally_tampered.disposition is SuiteDisposition.FAILED_INFRASTRUCTURE
        assert any("schema" in error for error in structurally_tampered.errors)

        report["schema"] = original_schema
        _write_hash_style(path, report, hash_field=hash_field, trace_style=trace_style)
        loaded = json.loads(path.read_text(encoding="utf-8"))
        loaded[hash_field] = "sha256:" + "0" * 64
        atomic_write_json(path, loaded)
        assert validator(path).disposition is SuiteDisposition.FAILED_INFRASTRUCTURE

        source_report = copy.deepcopy(report)
        source_tamper(source_report)
        _write_hash_style(
            path,
            source_report,
            hash_field=hash_field,
            trace_style=trace_style,
        )
        assert validator(path).disposition is SuiteDisposition.FAILED_INFRASTRUCTURE

        metric_report = copy.deepcopy(report)
        metric_miss(metric_report)
        _write_hash_style(
            path,
            metric_report,
            hash_field=hash_field,
            trace_style=trace_style,
        )
        assert validator(path).disposition is SuiteDisposition.FAILED_MECHANISM


def test_stage13_structural_and_verifier_tamper_are_infrastructure(
    tmp_path: Path,
) -> None:
    directory = tmp_path / "evaluation"
    directory.mkdir()
    rows: list[dict[str, object]] = []
    for agent in ("random", "cycle", "novelty", "trace", "full"):
        for seed in (7, 11):
            rows.append(
                {
                    "agent": agent,
                    "identity": {"dirty_worktree": False, "git_commit": COMMIT},
                    "metrics": {"environment_actions": 4},
                    "score": {"completed": agent == "full", "verified": True},
                    "seed": seed,
                    "status": "success",
                    "trace": {
                        "event_type_counts": {"run.checkpoint_written": 1},
                        "replay_verified": True,
                    },
                }
            )
    (directory / "results.jsonl").write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )
    atomic_write_json(
        directory / "summary.json",
        {"failure_count": 0, "schema": "arc3.evaluation.summary.v0.1", "status": "PASS"},
    )
    assert validate_stage13(directory, frozen_commit=COMMIT).disposition is SuiteDisposition.PASS

    full_row = next(row for row in rows if row["agent"] == "full")
    full_score = full_row["score"]
    assert isinstance(full_score, dict)
    full_score["completed"] = False
    (directory / "results.jsonl").write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )
    assert (
        validate_stage13(directory, frozen_commit=COMMIT).disposition
        is SuiteDisposition.FAILED_MECHANISM
    )
    full_score["completed"] = True
    rows[0]["identity"] = {"dirty_worktree": False, "git_commit": "b" * 40}
    (directory / "results.jsonl").write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )
    assert (
        validate_stage13(directory, frozen_commit=COMMIT).disposition
        is SuiteDisposition.FAILED_INFRASTRUCTURE
    )

    good_verifier = json.dumps({"errors": [], "verified": True}).encode("utf-8")
    assert validate_stage13_verification(good_verifier, 0).disposition is SuiteDisposition.PASS
    assert (
        validate_stage13_verification(
            json.dumps({"errors": [], "verified": False}).encode(), 0
        ).disposition
        is SuiteDisposition.FAILED_INFRASTRUCTURE
    )
    assert (
        validate_stage13_verification(b"not-json", 0).disposition
        is SuiteDisposition.FAILED_INFRASTRUCTURE
    )


def test_reused_stage10_children_have_no_semantic_holdout_path() -> None:
    forbidden = (
        "holdout_ids",
        'manifest["games"]',
        "public-environments",
        "_contains_exact_string",
        "acquisition_roots",
    )
    for relative in (
        "scripts/measure_action_equivariance.py",
        "scripts/measure_rule_change_reopening.py",
    ):
        content = (ROOT / relative).read_text(encoding="utf-8")
        assert not any(fragment in content for fragment in forbidden)
        assert "build_opaque_holdout_authority" in content
    authority = (ROOT / "src/arc3/evaluation/holdout_authority.py").read_text(encoding="utf-8")
    assert "manifest_path" not in authority
    assert '"holdout_path_accesses": 0' in authority
    assert '"manifest_bytes_accessed": False' in authority
