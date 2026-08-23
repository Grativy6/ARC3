"""Frozen Build 001 Stage 10 robustness and regression contract.

The module contains only synthetic measurement declarations and validators.  It
does not import a public-game adapter, select a public identity, or execute an
environment.  The command-line supervisor owns process execution separately so
that importing this module is always non-playing.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import TypeGuard, cast

from arc3.evaluation.artifacts import canonical_object_hash, verify_object_hash
from arc3.types import JSONValue

PREDECLARATION_PATH = Path("docs/evidence/001-10-robustness-regression-predeclaration.json")
# Updated only when the frozen declaration is first sealed.  Runtime validation
# refuses any later byte drift.
PREDECLARATION_SHA256 = "sha256:02ad73f25cd6c21459cf425a29de0b830fa27bd660c58777b272ac57116d26e3"
SOURCE_FLOOR_COMMIT = "2e78c258cfbee8be62462f61ed08ad04c00a8934"
SOURCE_FLOOR_TREE = "4145356c116944bbd7c0c412771de9179ba22efe"
BUILD_000_PRODUCTION_COMMIT = "90ecf7267d5bb23d751d6f7ce3e8aa75f2f1a130"
BUILD_000_PRODUCTION_TREE = "0cf6e00b2fcc399e7a99a62c20e91bb84d485f13"
PUBLIC_PARTITION_MANIFEST_SHA256 = (
    "sha256:682d5891c2aface54803d9bd1173c55ed21e89856e13b8a478fb9276ee963f2f"
)
STAGE13_EVIDENCE_SHA256 = "sha256:ab354deec3ef4f7a84d285a8e7603dbe357afcf6c6bbff7862fe94979b94780e"
STAGE14_PROTOCOL_SHA256 = "sha256:b00c45337f451ecde9af097ce68c8eb60203a7516bff55d9ed7c40868700b369"

STAGE10_PREFLIGHT_SCHEMA = "arc3.build-001.stage-10-preflight.v0.1"
STAGE10_PARENT_RECEIPT_SCHEMA = "arc3.build-001.stage-10-parent-receipt.v0.1"
STAGE10_RESULT_SCHEMA = "arc3.build-001.stage-10-robustness-regression.v0.1"
STAGE10_CHECKPOINT_SCHEMA = "arc3.build-001.stage-10-checkpoint-replay.v0.1"

MAX_PEAK_RSS_BYTES = 2_147_483_648
MAX_TRACE_BYTES_PER_RUN = 268_435_456
MAX_DECISION_SECONDS = 2.0


class Stage10Status(StrEnum):
    """Terminal Stage 10 status with fail-closed precedence."""

    PASS = "PASS"
    FAILED_MECHANISM = "FAILED_MECHANISM"
    FAILED_INFRASTRUCTURE = "FAILED_INFRASTRUCTURE"


class SuiteDisposition(StrEnum):
    """Whether a validated child satisfies its frozen regression floor."""

    PASS = "PASS"
    FAILED_MECHANISM = "FAILED_MECHANISM"
    FAILED_INFRASTRUCTURE = "FAILED_INFRASTRUCTURE"


@dataclass(frozen=True, slots=True)
class SuiteSpec:
    """One serial, resumable Stage 10 subprocess declaration."""

    suite_id: str
    command: tuple[str, ...]
    timeout_seconds: float
    allowed_returncodes: tuple[int, ...]
    artifact_path: Path | None

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "allowed_returncodes": list(self.allowed_returncodes),
            "artifact_path": (
                self.artifact_path.resolve().as_posix() if self.artifact_path is not None else None
            ),
            "command": list(self.command),
            "suite_id": self.suite_id,
            "timeout_seconds": self.timeout_seconds,
        }


@dataclass(frozen=True, slots=True)
class SuiteValidation:
    """Typed validation result for one retained child artifact."""

    suite_id: str
    disposition: SuiteDisposition
    predicates: Mapping[str, bool]
    measurements: Mapping[str, JSONValue]
    errors: tuple[str, ...] = ()

    @property
    def artifact_valid(self) -> bool:
        return self.disposition is not SuiteDisposition.FAILED_INFRASTRUCTURE

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "artifact_valid": self.artifact_valid,
            "disposition": self.disposition.value,
            "errors": list(self.errors),
            "measurements": dict(self.measurements),
            "predicates": dict(self.predicates),
            "suite_id": self.suite_id,
        }


def _is_mapping(value: object) -> TypeGuard[Mapping[str, object]]:
    return isinstance(value, Mapping)


def _is_list(value: object) -> TypeGuard[list[object]]:
    return isinstance(value, list)


def _is_int(value: object) -> TypeGuard[int]:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_nonnegative_int(value: object) -> TypeGuard[int]:
    return _is_int(value) and value >= 0


def _is_number(value: object) -> TypeGuard[int | float]:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _object(value: object) -> Mapping[str, object]:
    return value if _is_mapping(value) else {}


def _array(value: object) -> list[object]:
    return value if _is_list(value) else []


def _integer(value: object, default: int = -1) -> int:
    return value if _is_int(value) else default


def _number(value: object, default: float = -1.0) -> float:
    return float(value) if _is_number(value) else default


def _string(value: object) -> str:
    return value if isinstance(value, str) else ""


def _boolean_acceptance_passes(value: object) -> bool:
    booleans = [item for item in _object(value).values() if isinstance(item, bool)]
    return bool(booleans) and all(booleans)


def _load_json_object(path: Path) -> dict[str, object]:
    value: object = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON artifact is not an object: {path}")
    return cast(dict[str, object], value)


def _verify_hash_without_newline(value: Mapping[str, object], *, hash_field: str) -> bool:
    expected = value.get(hash_field)
    unsigned = {key: item for key, item in value.items() if key != hash_field}
    try:
        canonical = json.dumps(
            unsigned,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError):
        return False
    actual = f"sha256:{hashlib.sha256(canonical).hexdigest()}"
    return isinstance(expected, str) and expected == actual


def validate_predeclaration_bytes(content: bytes) -> dict[str, object]:
    """Validate the frozen declaration without executing any child process."""

    import hashlib

    actual = f"sha256:{hashlib.sha256(content).hexdigest()}"
    try:
        value: object = json.loads(content)
    except json.JSONDecodeError as error:
        raise ValueError("Stage 10 predeclaration is invalid JSON") from error
    if not isinstance(value, dict):
        raise ValueError("Stage 10 predeclaration must be an object")
    declaration = cast(dict[str, object], value)
    if actual != PREDECLARATION_SHA256:
        raise ValueError("Stage 10 predeclaration bytes do not match the frozen hash")
    if declaration.get("schema") != "arc3.build-001.stage-10-predeclaration.v0.1":
        raise ValueError("Stage 10 predeclaration schema is not frozen v0.1")
    if declaration.get("status") != "FROZEN_PREMEASUREMENT":
        raise ValueError("Stage 10 predeclaration is not frozen")
    return declaration


def build_suite_plan(
    *,
    python: Path,
    source_root: Path,
    attempt_root: Path,
    frozen_commit: str,
) -> tuple[SuiteSpec, ...]:
    """Build the exact serial plan; this function never launches a child."""

    executable = str(python.resolve())
    root = source_root.resolve()
    attempt = attempt_root.resolve()
    short = frozen_commit[:7]
    evaluation_id = f"build001-stage10-stage13-{short}"
    evaluation_root = attempt / "stage13"
    evaluation_dir = evaluation_root / evaluation_id
    return (
        SuiteSpec(
            suite_id="stage13-evaluate",
            command=(
                executable,
                "-m",
                "arc3",
                "evaluate",
                "--partition",
                "smoke",
                "--agents",
                "random,cycle,novelty,trace,full",
                "--seeds",
                "7,11",
                "--max-actions",
                "16",
                "--max-resets",
                "2",
                "--timeout-seconds",
                "30",
                "--output-root",
                str(evaluation_root),
                "--evaluation-id",
                evaluation_id,
            ),
            timeout_seconds=600.0,
            allowed_returncodes=(0, 1),
            artifact_path=evaluation_dir / "summary.json",
        ),
        SuiteSpec(
            suite_id="stage13-verify",
            command=(
                executable,
                "-m",
                "arc3",
                "verify-artifacts",
                "--evaluation",
                evaluation_id,
                "--output-root",
                str(evaluation_root),
            ),
            timeout_seconds=300.0,
            allowed_returncodes=(0, 1),
            artifact_path=evaluation_dir / "manifest.json",
        ),
        SuiteSpec(
            suite_id="stage14-ablations",
            command=(
                executable,
                str(root / "scripts/measure_ablations.py"),
                "--output",
                str(attempt / "stage14.json"),
                "--work-root",
                str(attempt / "stage14-work"),
            ),
            timeout_seconds=1_200.0,
            allowed_returncodes=(0, 1),
            artifact_path=attempt / "stage14.json",
        ),
        SuiteSpec(
            suite_id="palette-equivariance",
            command=(
                executable,
                str(root / "scripts/measure_palette_equivariance.py"),
                "--output",
                str(attempt / "palette.json"),
                "--work-root",
                str(attempt / "palette-work"),
            ),
            timeout_seconds=900.0,
            allowed_returncodes=(0, 1),
            artifact_path=attempt / "palette.json",
        ),
        SuiteSpec(
            suite_id="action-equivariance",
            command=(
                executable,
                str(root / "scripts/measure_action_equivariance.py"),
                "--output",
                str(attempt / "action.json"),
                "--work-root",
                str(attempt / "action-work"),
            ),
            timeout_seconds=900.0,
            allowed_returncodes=(0, 1),
            artifact_path=attempt / "action.json",
        ),
        SuiteSpec(
            suite_id="rule-change",
            command=(
                executable,
                str(root / "scripts/measure_rule_change_reopening.py"),
                "--output",
                str(attempt / "rule-change.json"),
                "--work-root",
                str(attempt / "rule-change-work"),
            ),
            timeout_seconds=1_500.0,
            allowed_returncodes=(0, 1),
            artifact_path=attempt / "rule-change.json",
        ),
        SuiteSpec(
            suite_id="checkpoint-replay",
            command=(
                executable,
                str(root / "scripts/_stage10_checkpoint_worker.py"),
                "--output",
                str(attempt / "checkpoint-replay.json"),
                "--work-root",
                str(attempt / "checkpoint-replay-work"),
                "--frozen-commit",
                frozen_commit,
            ),
            timeout_seconds=600.0,
            allowed_returncodes=(0, 1),
            artifact_path=attempt / "checkpoint-replay.json",
        ),
        SuiteSpec(
            suite_id="resource-profile",
            command=(
                executable,
                str(root / "scripts/profile_competition.py"),
                "--root",
                str(root),
                "--output",
                str(attempt / "resource.json"),
                "--work-root",
                str(attempt / "resource-work"),
                "--frozen-commit",
                frozen_commit,
            ),
            timeout_seconds=1_800.0,
            allowed_returncodes=(0, 1),
            artifact_path=attempt / "resource.json",
        ),
        SuiteSpec(
            suite_id="competition-integrity",
            command=(
                executable,
                str(root / "scripts/check_competition_integrity.py"),
                "--root",
                str(root),
                "--manifest",
                str(root / "docs/evaluation/public-game-partitions.v0.1.json"),
                "--lock",
                str(root / "uv.lock"),
                "--run-state",
                str(root / "docs/ledger/build-001-run-state.json"),
                "--expected-manifest-sha256",
                PUBLIC_PARTITION_MANIFEST_SHA256,
                "--output",
                str(attempt / "integrity.json"),
            ),
            timeout_seconds=600.0,
            allowed_returncodes=(0, 1),
            artifact_path=attempt / "integrity.json",
        ),
    )


def suite_plan_hash(plan: Sequence[SuiteSpec]) -> str:
    value: dict[str, object] = {"suites": [item.to_dict() for item in plan]}
    return canonical_object_hash(value, hash_field="plan_hash")


def classify_stage(validations: Sequence[SuiteValidation]) -> Stage10Status:
    """Classify only complete required suites; unknown evidence fails closed."""

    required = {
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
    by_id = {item.suite_id: item for item in validations}
    if set(by_id) != required:
        return Stage10Status.FAILED_INFRASTRUCTURE
    if any(item.disposition is SuiteDisposition.FAILED_INFRASTRUCTURE for item in by_id.values()):
        return Stage10Status.FAILED_INFRASTRUCTURE
    if any(item.disposition is SuiteDisposition.FAILED_MECHANISM for item in by_id.values()):
        return Stage10Status.FAILED_MECHANISM
    return Stage10Status.PASS


def _validation(
    suite_id: str,
    *,
    predicates: Mapping[str, bool],
    measurements: Mapping[str, JSONValue],
    infrastructure_errors: Sequence[str] = (),
) -> SuiteValidation:
    if infrastructure_errors:
        disposition = SuiteDisposition.FAILED_INFRASTRUCTURE
    elif all(predicates.values()):
        disposition = SuiteDisposition.PASS
    else:
        disposition = SuiteDisposition.FAILED_MECHANISM
    return SuiteValidation(
        suite_id=suite_id,
        disposition=disposition,
        predicates=dict(predicates),
        measurements=dict(measurements),
        errors=tuple(infrastructure_errors),
    )


def _source_commit(report: Mapping[str, object]) -> str:
    source = _object(report.get("source_identity"))
    return _string(source.get("git_commit"))


def validate_stage13(
    evaluation_directory: Path,
    *,
    frozen_commit: str,
) -> SuiteValidation:
    """Validate exact Stage 13 FULL floors from sealed synthetic rows."""

    errors: list[str] = []
    try:
        summary = _load_json_object(evaluation_directory / "summary.json")
        result_lines = (
            (evaluation_directory / "results.jsonl").read_text(encoding="utf-8").splitlines()
        )
        results = [_load_json_line(line) for line in result_lines if line]
    except (OSError, ValueError, json.JSONDecodeError) as error:
        errors.append(f"unreadable-stage13-artifact:{type(error).__name__}:{error}")
        summary = {}
        results = []
    full = [item for item in results if item.get("agent") == "full"]
    full_actions = sum(
        _integer(_object(item.get("metrics")).get("environment_actions"), default=10**9)
        for item in full
    )
    full_completed = sum(_object(item.get("score")).get("completed") is True for item in full)
    source_bound = bool(full) and all(
        _object(item.get("identity")).get("git_commit") == frozen_commit
        and _object(item.get("identity")).get("dirty_worktree") is False
        for item in results
    )
    traces_verified = len(full) == 2 and all(
        _object(item.get("trace")).get("replay_verified") is True
        and _object(item.get("score")).get("verified") is True
        and item.get("status") == "success"
        for item in full
    )
    checkpoints_verified = len(full) == 2 and all(
        _integer(
            _object(_object(item.get("trace")).get("event_type_counts")).get(
                "run.checkpoint_written"
            ),
            default=0,
        )
        > 0
        for item in full
    )
    predicates = {
        "checkpoint_receipts_verified": checkpoints_verified,
        "exact_full_rows": len(full) == 2
        and {_integer(item.get("seed")) for item in full} == {7, 11},
        "full_completed_2_of_2": full_completed == 2,
        "full_total_actions_at_most_8": full_actions <= 8,
        "source_clean_and_exact": source_bound,
        "summary_pass": summary.get("schema") == "arc3.evaluation.summary.v0.1"
        and summary.get("status") == "PASS"
        and summary.get("failure_count") == 0,
        "trace_and_scores_verified": traces_verified,
    }
    return _validation(
        "stage13-evaluate",
        predicates=predicates,
        measurements={
            "full_actions": full_actions if full else None,
            "full_completed": full_completed,
            "full_rows": len(full),
            "full_rows_with_checkpoint": (len(full) if checkpoints_verified else 0),
            "result_count": len(results),
        },
        infrastructure_errors=errors,
    )


def _load_json_line(line: str) -> dict[str, object]:
    value: object = json.loads(line)
    if not isinstance(value, dict):
        raise ValueError("JSONL row is not an object")
    return cast(dict[str, object], value)


def validate_stage13_verification(stdout: bytes, returncode: int | None) -> SuiteValidation:
    errors: list[str] = []
    try:
        payload: object = json.loads(stdout.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        errors.append(f"invalid-verifier-output:{type(error).__name__}")
        payload = {}
    report = _object(payload)
    predicates = {
        "returncode_zero": returncode == 0,
        "sealed_artifacts_verified": report.get("verified") is True,
        "verification_has_no_errors": _array(report.get("errors")) == [],
    }
    return _validation(
        "stage13-verify",
        predicates=predicates,
        measurements={"returncode": returncode},
        infrastructure_errors=errors,
    )


def validate_ablations(path: Path, *, frozen_commit: str) -> SuiteValidation:
    errors: list[str] = []
    try:
        report = _load_json_object(path)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        errors.append(f"unreadable-ablation-artifact:{type(error).__name__}:{error}")
        report = {}
    variants = _object(report.get("variants"))

    def aggregate(name: str) -> Mapping[str, object]:
        return _object(_object(variants.get(name)).get("aggregate"))

    full = aggregate("FULL")
    a4 = aggregate("A4")
    a5 = aggregate("A5")
    full_completed = _integer(full.get("completed"))
    full_actions = _integer(full.get("total_actions"))
    a4_completed = _integer(a4.get("completed"))
    a5_completed = _integer(a5.get("completed"))
    predicates = {
        "artifact_self_hash": _verify_hash_without_newline(report, hash_field="artifact_core_hash"),
        "exact_protocol": report.get("protocol_manifest_hash") == STAGE14_PROTOCOL_SHA256
        and report.get("protocol_manifest_matches_run") is True,
        "full_actions_at_most_157": 0 <= full_actions <= 157,
        "full_at_least_8_of_14": full_completed >= 8,
        "full_gap_over_a4_at_least_7": full_completed - a4_completed >= 7,
        "full_gap_over_a5_at_least_8": full_completed - a5_completed >= 8,
        "no_world_model_at_most_1": 0 <= a4_completed <= 1,
        "no_goal_exactly_0": a5_completed == 0,
        "source_clean_and_exact": report.get("git_commit") == frozen_commit
        and report.get("dirty_worktree") is False,
        "typed_rows_verified": report.get("schema") == "arc3.ablations.paired.v0.1"
        and report.get("verified") is True
        and report.get("status") == "PASS",
    }
    return _validation(
        "stage14-ablations",
        predicates=predicates,
        measurements={
            "a4_completed": a4_completed,
            "a5_completed": a5_completed,
            "full_actions": full_actions,
            "full_completed": full_completed,
        },
        infrastructure_errors=errors,
    )


def validate_palette(path: Path, *, frozen_commit: str) -> SuiteValidation:
    errors: list[str] = []
    try:
        report = _load_json_object(path)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        errors.append(f"unreadable-palette-artifact:{type(error).__name__}:{error}")
        report = {}
    procedural = _object(report.get("procedural_paired_suite"))
    checkpoint = _object(report.get("checkpoint_resume_suite"))
    predicates = {
        "artifact_self_hash": verify_object_hash(report, hash_field="artifact_core_hash"),
        "checkpoint_16_of_16": checkpoint.get("case_count") == 16
        and checkpoint.get("passed_cases") == 16,
        "full_child_acceptance": report.get("status") == "PASS"
        and _boolean_acceptance_passes(report.get("acceptance")),
        "procedural_256_of_256": procedural.get("pair_count") == 256
        and procedural.get("passed_pairs") == 256,
        "schema": report.get("schema") == "arc3.build-001.stage-04-palette-equivariance.v0.1",
        "source_clean_and_exact": _source_commit(report) == frozen_commit
        and _object(report.get("source_identity")).get("dirty_worktree") is False,
    }
    return _validation(
        "palette-equivariance",
        predicates=predicates,
        measurements={
            "checkpoint_passed": _integer(checkpoint.get("passed_cases")),
            "procedural_passed": _integer(procedural.get("passed_pairs")),
        },
        infrastructure_errors=errors,
    )


def validate_action(path: Path, *, frozen_commit: str) -> SuiteValidation:
    errors: list[str] = []
    try:
        report = _load_json_object(path)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        errors.append(f"unreadable-action-artifact:{type(error).__name__}:{error}")
        report = {}
    procedural = _object(report.get("procedural_paired_suite"))
    checkpoint = _object(report.get("checkpoint_resume_suite"))
    inverse = _integer(procedural.get("post_calibration_inverse_request_denominator"))
    inverse_pass = _integer(procedural.get("post_calibration_inverse_request_numerator"))
    predicates = {
        "artifact_self_hash": verify_object_hash(report, hash_field="artifact_core_hash"),
        "checkpoint_16_of_16": checkpoint.get("case_count") == 16
        and checkpoint.get("passed_cases") == 16,
        "full_child_acceptance": report.get("status") == "PASS"
        and _boolean_acceptance_passes(report.get("acceptance")),
        "inverse_528_of_528": inverse == 528 and inverse_pass == 528,
        "procedural_128_of_128": procedural.get("pair_count") == 128
        and procedural.get("passed_pairs") == 128,
        "schema": report.get("schema") == "arc3.build-001.stage-05-action-equivariance.v0.1",
        "source_clean_and_exact": _source_commit(report) == frozen_commit
        and _object(report.get("source_identity")).get("dirty_worktree") is False,
    }
    return _validation(
        "action-equivariance",
        predicates=predicates,
        measurements={
            "checkpoint_passed": _integer(checkpoint.get("passed_cases")),
            "inverse_passed": inverse_pass,
            "procedural_passed": _integer(procedural.get("passed_pairs")),
        },
        infrastructure_errors=errors,
    )


def validate_rule_change(
    path: Path,
    *,
    frozen_commit: str,
    returncode: int | None,
) -> SuiteValidation:
    """Accept a valid child FAILED_MECHANISM while preserving its failed gates."""

    errors: list[str] = []
    try:
        report = _load_json_object(path)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        errors.append(f"unreadable-rule-artifact:{type(error).__name__}:{error}")
        report = {}
    intervention = _object(report.get("intervention_suite"))
    noise = _object(report.get("stationary_noise_control_suite"))
    decision = _object(report.get("decision_rule"))
    action_rows = [
        row
        for raw in _array(intervention.get("cases"))
        for row in (_object(raw),)
        if _object(row.get("case")).get("family") == "action_effect_rotation"
    ]
    action_passed = sum(row.get("case_passed") is True for row in action_rows)
    if returncode not in {0, 1}:
        errors.append(f"invalid-rule-child-returncode:{returncode}")
    predicates = {
        "action_effect_rotation_32_of_32": len(action_rows) == 32 and action_passed == 32,
        "artifact_self_hash": verify_object_hash(report, hash_field="artifact_core_hash"),
        "all_interventions_exercised": intervention.get("case_count") == 64
        and intervention.get("exercised_cases") == 64,
        "known_failures_retained": _integer(intervention.get("passed_cases")) >= 32
        and noise.get("case_count") == 32
        and _is_nonnegative_int(noise.get("passed_cases")),
        "no_infrastructure_failure": decision.get("infrastructure_failure_count") == 0,
        "nonzero_child_is_typed": returncode in {0, 1}
        and report.get("status") in {"PASS", "FAILED_MECHANISM"},
        "schema": report.get("schema") == "arc3.build-001.stage-06-rule-change-reopening.v0.1",
        "source_clean_and_exact": _source_commit(report) == frozen_commit
        and _object(report.get("source_identity")).get("dirty_worktree") is False
        and _object(report.get("source_identity_stability")).get("passed") is True,
        "trace_and_integrity": _object(report.get("acceptance")).get(
            "aggregate_trace_replay_and_immutability"
        )
        is True
        and _object(report.get("acceptance")).get("competition_integrity") is True
        and _object(report.get("acceptance")).get("holdout_integrity") is True,
    }
    # The current Stage 06 failed traversability/noise mechanisms remain a
    # separately visible measurement.  They do not erase the frozen Stage 10
    # regression floor, which requires exact action-effect preservation and
    # complete exposure rather than retroactive relabeling.
    return _validation(
        "rule-change",
        predicates=predicates,
        measurements={
            "action_effect_rotation_passed": action_passed,
            "child_status": _string(report.get("status")),
            "noise_passed": _integer(noise.get("passed_cases")),
            "noise_resolved_as_noise": _integer(noise.get("resolved_as_noise")),
            "returncode": returncode,
            "traversability_and_action_total_passed": _integer(intervention.get("passed_cases")),
        },
        infrastructure_errors=errors,
    )


def validate_checkpoint_replay(path: Path, *, frozen_commit: str) -> SuiteValidation:
    errors: list[str] = []
    try:
        report = _load_json_object(path)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        errors.append(f"unreadable-checkpoint-artifact:{type(error).__name__}:{error}")
        report = {}
    acceptance = _object(report.get("acceptance"))
    predicates = {
        "artifact_self_hash": verify_object_hash(report, hash_field="artifact_core_hash"),
        "deep_exact_continuation": acceptance.get("deep_exact_continuation") is True,
        "deterministic_repeat": acceptance.get("deterministic_seed_repeatability") is True,
        "fast_exact_continuation": acceptance.get("fast_exact_continuation") is True,
        "schema": report.get("schema") == STAGE10_CHECKPOINT_SCHEMA,
        "source_clean_and_exact": _object(report.get("source_identity")).get("git_commit")
        == frozen_commit
        and _object(report.get("source_identity")).get("dirty_worktree") is False,
        "trace_replay": acceptance.get("trace_replay") is True,
        "trace_tamper_rejected": acceptance.get("trace_tamper_rejected") is True,
        "checkpoint_tamper_rejected": acceptance.get("checkpoint_tamper_rejected") is True,
    }
    return _validation(
        "checkpoint-replay",
        predicates=predicates,
        measurements={
            "deep_path": _string(_object(report.get("deep_continuation")).get("path")),
            "fast_path": _string(_object(report.get("fast_continuation")).get("path")),
        },
        infrastructure_errors=errors,
    )


def validate_resource_profile(
    path: Path,
    *,
    frozen_commit: str,
    returncode: int | None,
) -> SuiteValidation:
    errors: list[str] = []
    try:
        report = _load_json_object(path)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        errors.append(f"unreadable-resource-artifact:{type(error).__name__}:{error}")
        report = {}
    profile = _object(report.get("profile"))
    decision = _object(profile.get("decision_latency_seconds"))
    receipt_hash = report.get("receipt_sha256")
    if returncode not in {0, 1}:
        errors.append(f"invalid-resource-child-returncode:{returncode}")
    predicates = {
        "artifact_self_hash": isinstance(receipt_hash, str)
        and _verify_hash_without_newline(report, hash_field="receipt_sha256"),
        "decision_max_at_most_2_seconds": 0.0
        <= _number(decision.get("maximum"))
        <= MAX_DECISION_SECONDS,
        "profile_valid": profile.get("verified") is True,
        "rss_at_most_2_gib": 0
        <= _integer(_object(profile.get("kernel_memory_after")).get("peak_rss_bytes"))
        <= MAX_PEAK_RSS_BYTES,
        "schema": report.get("schema") == "arc3.stage16.profile.v0.1",
        "source_clean_and_exact": report.get("git_commit") == frozen_commit
        and _object(report.get("source_identity")).get("verified") is True,
        "trace_at_most_256_mib": 0
        <= _integer(profile.get("trace_bytes"))
        <= MAX_TRACE_BYTES_PER_RUN,
        "valid_child_return": returncode in {0, 1},
    }
    peak = _integer(_object(profile.get("kernel_memory_after")).get("peak_rss_bytes"))
    if peak < 0:
        peak = _integer(_object(profile.get("kernel_memory_after")).get("working_set_peak_bytes"))
        predicates["rss_at_most_2_gib"] = 0 <= peak <= MAX_PEAK_RSS_BYTES
    return _validation(
        "resource-profile",
        predicates=predicates,
        measurements={
            "child_status": _string(report.get("status")),
            "decision_max_seconds": _number(decision.get("maximum")),
            "peak_rss_bytes": peak,
            "returncode": returncode,
            "trace_bytes": _integer(profile.get("trace_bytes")),
        },
        infrastructure_errors=errors,
    )


def validate_integrity(path: Path, *, frozen_commit: str) -> SuiteValidation:
    errors: list[str] = []
    try:
        report = _load_json_object(path)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        errors.append(f"unreadable-integrity-artifact:{type(error).__name__}:{error}")
        report = {}
    receipt_hash = report.get("receipt_sha256")
    finding_counts = _object(report.get("finding_counts"))
    checks = _object(report.get("checks"))
    inputs = _object(report.get("inputs"))
    assurance = _object(report.get("assurance_scope"))
    git = _object(report.get("git"))
    predicates = {
        "artifact_self_hash": isinstance(receipt_hash, str)
        and _verify_hash_without_newline(report, hash_field="receipt_sha256"),
        "manifest_hash_bound": inputs.get("manifest_sha256") == PUBLIC_PARTITION_MANIFEST_SHA256,
        "offline_policy": report.get("passed") is True
        and assurance.get("scanner_network_mode") == "offline-by-construction"
        and _object(checks.get("policy_static")).get("passed") is True
        and _object(checks.get("secret_scan")).get("passed") is True
        and _object(checks.get("source_identity")).get("passed") is True
        and _object(checks.get("supply_chain")).get("passed") is True,
        "schema": report.get("schema") == "arc3.integrity.receipt.v0.2",
        "source_clean_and_exact": git.get("commit") == frozen_commit
        and git.get("dirty_worktree") is False,
        "zero_blocking_findings": finding_counts.get("blocking") == 0,
        "zero_total_findings": finding_counts.get("total") == 0,
    }
    return _validation(
        "competition-integrity",
        predicates=predicates,
        measurements={
            "blocking_findings": _integer(finding_counts.get("blocking")),
            "total_findings": _integer(finding_counts.get("total")),
        },
        infrastructure_errors=errors,
    )


__all__ = [
    "BUILD_000_PRODUCTION_COMMIT",
    "BUILD_000_PRODUCTION_TREE",
    "MAX_DECISION_SECONDS",
    "MAX_PEAK_RSS_BYTES",
    "MAX_TRACE_BYTES_PER_RUN",
    "PREDECLARATION_PATH",
    "PREDECLARATION_SHA256",
    "PUBLIC_PARTITION_MANIFEST_SHA256",
    "SOURCE_FLOOR_COMMIT",
    "SOURCE_FLOOR_TREE",
    "STAGE10_CHECKPOINT_SCHEMA",
    "STAGE10_PARENT_RECEIPT_SCHEMA",
    "STAGE10_PREFLIGHT_SCHEMA",
    "STAGE10_RESULT_SCHEMA",
    "STAGE13_EVIDENCE_SHA256",
    "STAGE14_PROTOCOL_SHA256",
    "Stage10Status",
    "SuiteDisposition",
    "SuiteSpec",
    "SuiteValidation",
    "build_suite_plan",
    "classify_stage",
    "suite_plan_hash",
    "validate_ablations",
    "validate_action",
    "validate_checkpoint_replay",
    "validate_integrity",
    "validate_palette",
    "validate_predeclaration_bytes",
    "validate_resource_profile",
    "validate_rule_change",
    "validate_stage13",
    "validate_stage13_verification",
]
