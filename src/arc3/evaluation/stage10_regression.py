"""Frozen Build 001 Stage 10 robustness and regression contract.

The module contains only synthetic measurement declarations and validators.  It
does not import a public-game adapter, select a public identity, or execute an
environment.  The command-line supervisor owns process execution separately so
that importing this module is always non-playing.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import TypeGuard, cast

from arc3.evaluation.artifacts import canonical_object_hash, verify_object_hash
from arc3.types import JSONValue

PREDECLARATION_PATH = Path("docs/evidence/001-10-robustness-regression-predeclaration-v0.2.json")
# Updated only when the frozen declaration is first sealed.  Runtime validation
# refuses any later byte drift.
PREDECLARATION_SHA256 = "sha256:e056eea0d4a6664996ae9078e15b4cdddb5f6c40d5b770540b8e9068cc224613"
PREDECLARATION_AMENDMENT_PATH = Path(
    "docs/evidence/001-10-robustness-regression-predeclaration-amendment-v0.1.json"
)
PREDECLARATION_AMENDMENT_SHA256 = (
    "sha256:6eb1a9f5fba2ce02fbe601ffa123d5f9fb8a9ecc44c0a7db5c91fefdaf5bf2a6"
)
SOURCE_FLOOR_COMMIT = "2e78c258cfbee8be62462f61ed08ad04c00a8934"
SOURCE_FLOOR_TREE = "4145356c116944bbd7c0c412771de9179ba22efe"
BUILD_000_PRODUCTION_COMMIT = "90ecf7267d5bb23d751d6f7ce3e8aa75f2f1a130"
BUILD_000_PRODUCTION_TREE = "0cf6e00b2fcc399e7a99a62c20e91bb84d485f13"
PUBLIC_PARTITION_MANIFEST_SHA256 = (
    "sha256:682d5891c2aface54803d9bd1173c55ed21e89856e13b8a478fb9276ee963f2f"
)
STAGE13_EVIDENCE_SHA256 = "sha256:ab354deec3ef4f7a84d285a8e7603dbe357afcf6c6bbff7862fe94979b94780e"
STAGE14_PROTOCOL_SHA256 = "sha256:b00c45337f451ecde9af097ce68c8eb60203a7516bff55d9ed7c40868700b369"

STAGE10_PREFLIGHT_SCHEMA = "arc3.build-001.stage-10-preflight.v0.3"
STAGE10_PARENT_RECEIPT_SCHEMA = "arc3.build-001.stage-10-parent-receipt.v0.3"
STAGE10_RESULT_SCHEMA = "arc3.build-001.stage-10-robustness-regression.v0.3"
STAGE10_CHECKPOINT_SCHEMA = "arc3.build-001.stage-10-checkpoint-replay.v0.1"
STAGE10_SOCKET_DENIAL_SCHEMA = "arc3.build-001.stage-10-socket-denial.v0.3"
STAGE10_CHILD_AUTHORITY_SCHEMA = "arc3.build-001.stage-10-child-authority.v0.3"
STAGE10_PROCESS_LAUNCH_SCHEMA = "arc3.build-001.stage-10-process-launch.v0.1"
STAGE10_LAUNCH_AUTHORIZATION_SCHEMA = "arc3.build-001.stage-10-launch-authorization.v0.1"
STAGE10_WORKER_ABORT_SCHEMA = "arc3.build-001.stage-10-worker-abort.v0.1"
STAGE10_PROCESS_CLEANUP_SCHEMA = "arc3.build-001.stage-10-process-cleanup.v0.1"
UV_LOCK_SHA256 = "sha256:3bf42dcbe45720f71b7433584f56a5d5982ec1c687c341ad2626222fa5de285b"

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
    network_guard_path: Path | None = None
    authority_path: Path | None = None
    prior_integrity_path: Path | None = None
    integrity_composite_path: Path | None = None
    launch_path: Path | None = None
    authorization_path: Path | None = None
    abort_path: Path | None = None
    cleanup_path: Path | None = None
    launch_token: str | None = None
    integrity_inputs_hash: str | None = None

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "allowed_returncodes": list(self.allowed_returncodes),
            "artifact_path": (
                self.artifact_path.resolve().as_posix() if self.artifact_path is not None else None
            ),
            "abort_path": (
                self.abort_path.resolve().as_posix() if self.abort_path is not None else None
            ),
            "authorization_path": (
                self.authorization_path.resolve().as_posix()
                if self.authorization_path is not None
                else None
            ),
            "authority_path": (
                self.authority_path.resolve().as_posix()
                if self.authority_path is not None
                else None
            ),
            "command": list(self.command),
            "cleanup_path": (
                self.cleanup_path.resolve().as_posix() if self.cleanup_path is not None else None
            ),
            "integrity_composite_path": (
                self.integrity_composite_path.resolve().as_posix()
                if self.integrity_composite_path is not None
                else None
            ),
            "integrity_inputs_hash": self.integrity_inputs_hash,
            "network_guard_path": (
                self.network_guard_path.resolve().as_posix()
                if self.network_guard_path is not None
                else None
            ),
            "launch_path": (
                self.launch_path.resolve().as_posix() if self.launch_path is not None else None
            ),
            "launch_token": self.launch_token,
            "prior_integrity_path": (
                self.prior_integrity_path.resolve().as_posix()
                if self.prior_integrity_path is not None
                else None
            ),
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


def _boolean_acceptance_is_typed(value: object) -> bool:
    fields = _object(value)
    return bool(fields) and all(isinstance(item, bool) for item in fields.values())


def _exact_field_types(
    value: object,
    *,
    booleans: frozenset[str] = frozenset(),
    integers: frozenset[str] = frozenset(),
    numbers: frozenset[str] = frozenset(),
) -> bool:
    """Validate the exact structural proof surface before applying any floor."""

    fields = _object(value)
    if set(fields) != set(booleans | integers | numbers):
        return False
    return bool(
        all(isinstance(fields[name], bool) for name in booleans)
        and all(_is_int(fields[name]) for name in integers)
        and all(
            _is_number(fields[name]) and math.isfinite(float(cast(int | float, fields[name])))
            for name in numbers
        )
    )


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
    if declaration.get("schema") != "arc3.build-001.stage-10-predeclaration.v0.2":
        raise ValueError("Stage 10 predeclaration schema is not frozen v0.2")
    if declaration.get("status") != "FROZEN_PREMEASUREMENT":
        raise ValueError("Stage 10 predeclaration is not frozen")
    return declaration


def validate_predeclaration_amendment_bytes(content: bytes) -> dict[str, object]:
    """Validate the frozen pre-execution Stage 09 infrastructure amendment."""

    actual = f"sha256:{hashlib.sha256(content).hexdigest()}"
    try:
        value: object = json.loads(content)
    except json.JSONDecodeError as error:
        raise ValueError("Stage 10 predeclaration amendment is invalid JSON") from error
    if not isinstance(value, dict):
        raise ValueError("Stage 10 predeclaration amendment must be an object")
    amendment = cast(dict[str, object], value)
    supplement = amendment.get("supplements")
    if actual != PREDECLARATION_AMENDMENT_SHA256:
        raise ValueError("Stage 10 predeclaration amendment bytes do not match the frozen hash")
    if amendment.get("schema") != "arc3.build-001.stage-10-predeclaration-amendment.v0.1":
        raise ValueError("Stage 10 predeclaration amendment schema is not frozen v0.1")
    if amendment.get("status") != "FROZEN_PREMEASUREMENT":
        raise ValueError("Stage 10 predeclaration amendment is not frozen")
    if amendment.get("supersedes") is not None:
        raise ValueError("Stage 10 predeclaration amendment may not supersede frozen v0.2")
    if not isinstance(supplement, Mapping) or dict(supplement) != {
        "path": PREDECLARATION_PATH.as_posix(),
        "sha256": PREDECLARATION_SHA256,
    }:
        raise ValueError("Stage 10 predeclaration amendment does not bind frozen v0.2")
    return amendment


def build_suite_plan(
    *,
    python: Path,
    source_root: Path,
    attempt_root: Path,
    frozen_commit: str,
    prior_integrity_path: Path | None = None,
    integrity_inputs_hash: str | None = None,
) -> tuple[SuiteSpec, ...]:
    """Build the exact serial plan; this function never launches a child."""

    executable = str(Path(os.path.abspath(python)))
    root = source_root.resolve()
    attempt = attempt_root.resolve()
    short = frozen_commit[:7]
    evaluation_id = f"build001-stage10-stage13-{short}"
    evaluation_root = attempt / "stage13"
    evaluation_dir = evaluation_root / evaluation_id
    wrapper = root / "scripts/_stage10_offline_child.py"
    child_authority = attempt / "authorities" / "no-semantic-surface.json"
    integrity_composite = attempt / "integrity-composite.json"

    def guarded_spec(
        *,
        suite_id: str,
        target_kind: str,
        target: str,
        arguments: tuple[str, ...],
        timeout_seconds: float,
        allowed_returncodes: tuple[int, ...],
        artifact_path: Path | None,
        requires_parent_authority: bool = True,
        prior_integrity_authority: Path | None = None,
        integrity_composite_output: Path | None = None,
    ) -> SuiteSpec:
        guard_path = attempt / "network" / f"{suite_id}.json"
        launch_path = attempt / "process" / f"{suite_id}.launch.json"
        authorization_path = attempt / "process" / f"{suite_id}.authorization.json"
        abort_path = attempt / "process" / f"{suite_id}.abort.json"
        cleanup_path = attempt / "process" / f"{suite_id}.cleanup.json"
        selector = "--module" if target_kind == "module" else "--script"
        target_command = (
            executable,
            str(wrapper),
            "--receipt",
            str(guard_path),
            "--suite-id",
            suite_id,
            "--frozen-commit",
            frozen_commit,
            *(("--authority", str(child_authority)) if requires_parent_authority else ()),
            "--launch-receipt",
            str(launch_path),
            "--authorization",
            str(authorization_path),
            "--abort-receipt",
            str(abort_path),
        )
        launch_token = (
            "sha256:"
            + hashlib.sha256(
                json.dumps(
                    {
                        "attempt_root": attempt.as_posix(),
                        "frozen_commit": frozen_commit,
                        "predeclaration_amendment_sha256": (PREDECLARATION_AMENDMENT_SHA256),
                        "predeclaration_sha256": PREDECLARATION_SHA256,
                        "suite_id": suite_id,
                        "target": [target_kind, target, *arguments],
                    },
                    allow_nan=False,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    sort_keys=True,
                ).encode("utf-8")
            ).hexdigest()
        )
        return SuiteSpec(
            suite_id=suite_id,
            command=(
                *target_command,
                "--launch-token",
                launch_token,
                selector,
                target,
                "--",
                *arguments,
            ),
            timeout_seconds=timeout_seconds,
            allowed_returncodes=allowed_returncodes,
            artifact_path=artifact_path,
            network_guard_path=guard_path,
            authority_path=child_authority if requires_parent_authority else None,
            prior_integrity_path=prior_integrity_authority,
            integrity_composite_path=integrity_composite_output,
            integrity_inputs_hash=integrity_inputs_hash,
            launch_path=launch_path,
            authorization_path=authorization_path,
            abort_path=abort_path,
            cleanup_path=cleanup_path,
            launch_token=launch_token,
        )

    return (
        guarded_spec(
            suite_id="competition-integrity",
            target_kind="script",
            target=str(root / "scripts/check_competition_integrity.py"),
            arguments=(
                "--root",
                str(root),
                "--package-only",
                "--expected-commit",
                frozen_commit,
                "--output",
                str(attempt / "integrity.json"),
            ),
            timeout_seconds=600.0,
            allowed_returncodes=(0, 1),
            artifact_path=attempt / "integrity.json",
            requires_parent_authority=False,
            prior_integrity_authority=prior_integrity_path,
            integrity_composite_output=integrity_composite,
        ),
        guarded_spec(
            suite_id="stage13-evaluate",
            target_kind="module",
            target="arc3",
            arguments=(
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
        guarded_spec(
            suite_id="stage13-verify",
            target_kind="module",
            target="arc3",
            arguments=(
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
        guarded_spec(
            suite_id="stage14-ablations",
            target_kind="script",
            target=str(root / "scripts/measure_ablations.py"),
            arguments=(
                "--output",
                str(attempt / "stage14.json"),
                "--work-root",
                str(attempt / "stage14-work"),
            ),
            timeout_seconds=1_200.0,
            allowed_returncodes=(0, 1),
            artifact_path=attempt / "stage14.json",
        ),
        guarded_spec(
            suite_id="palette-equivariance",
            target_kind="script",
            target=str(root / "scripts/measure_palette_equivariance.py"),
            arguments=(
                "--output",
                str(attempt / "palette.json"),
                "--work-root",
                str(attempt / "palette-work"),
            ),
            timeout_seconds=900.0,
            allowed_returncodes=(0, 1),
            artifact_path=attempt / "palette.json",
        ),
        guarded_spec(
            suite_id="action-equivariance",
            target_kind="script",
            target=str(root / "scripts/measure_action_equivariance.py"),
            arguments=(
                "--output",
                str(attempt / "action.json"),
                "--work-root",
                str(attempt / "action-work"),
            ),
            timeout_seconds=900.0,
            allowed_returncodes=(0, 1),
            artifact_path=attempt / "action.json",
        ),
        guarded_spec(
            suite_id="rule-change",
            target_kind="script",
            target=str(root / "scripts/measure_rule_change_reopening.py"),
            arguments=(
                "--output",
                str(attempt / "rule-change.json"),
                "--work-root",
                str(attempt / "rule-change-work"),
            ),
            timeout_seconds=1_500.0,
            allowed_returncodes=(0, 1),
            artifact_path=attempt / "rule-change.json",
        ),
        guarded_spec(
            suite_id="checkpoint-replay",
            target_kind="script",
            target=str(root / "scripts/_stage10_checkpoint_worker.py"),
            arguments=(
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
        guarded_spec(
            suite_id="resource-profile",
            target_kind="script",
            target=str(root / "scripts/profile_competition.py"),
            arguments=(
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
    infrastructure_predicates: Mapping[str, bool],
    metric_predicates: Mapping[str, bool],
    measurements: Mapping[str, JSONValue],
    infrastructure_errors: Sequence[str] = (),
) -> SuiteValidation:
    failed_infrastructure = tuple(
        f"infrastructure-predicate-failed:{name}"
        for name, passed in infrastructure_predicates.items()
        if not passed
    )
    errors = (*infrastructure_errors, *failed_infrastructure)
    if errors:
        disposition = SuiteDisposition.FAILED_INFRASTRUCTURE
    elif all(metric_predicates.values()):
        disposition = SuiteDisposition.PASS
    else:
        disposition = SuiteDisposition.FAILED_MECHANISM
    return SuiteValidation(
        suite_id=suite_id,
        disposition=disposition,
        predicates={**infrastructure_predicates, **metric_predicates},
        measurements=dict(measurements),
        errors=errors,
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
    result_structure_typed = bool(results) and all(
        isinstance(item.get("agent"), str)
        and _is_int(item.get("seed"))
        and isinstance(item.get("status"), str)
        and _is_mapping(item.get("identity"))
        and _is_mapping(item.get("metrics"))
        and _is_nonnegative_int(_object(item.get("metrics")).get("environment_actions"))
        and _is_mapping(item.get("score"))
        and isinstance(_object(item.get("score")).get("completed"), bool)
        and isinstance(_object(item.get("score")).get("verified"), bool)
        and _is_mapping(item.get("trace"))
        and isinstance(_object(item.get("trace")).get("replay_verified"), bool)
        for item in results
    )
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
    infrastructure_predicates = {
        "checkpoint_receipts_verified": checkpoints_verified,
        "exact_full_rows": len(full) == 2
        and {_integer(item.get("seed")) for item in full} == {7, 11},
        "exact_result_rows": len(results) == 10,
        "result_proofs_are_typed": result_structure_typed,
        "source_clean_and_exact": source_bound,
        "summary_schema": summary.get("schema") == "arc3.evaluation.summary.v0.1",
        "summary_status_is_typed": isinstance(summary.get("status"), str)
        and _is_nonnegative_int(summary.get("failure_count")),
        "trace_and_scores_verified": traces_verified,
    }
    metric_predicates = {
        "full_completed_2_of_2": full_completed == 2,
        "full_total_actions_at_most_8": full_actions <= 8,
        "summary_has_no_failures": summary.get("status") == "PASS"
        and summary.get("failure_count") == 0,
    }
    return _validation(
        "stage13-evaluate",
        infrastructure_predicates=infrastructure_predicates,
        metric_predicates=metric_predicates,
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
    infrastructure_predicates = {
        "returncode_zero": returncode == 0,
        "sealed_artifacts_verified": report.get("verified") is True,
        "verification_has_no_errors": _array(report.get("errors")) == [],
    }
    return _validation(
        "stage13-verify",
        infrastructure_predicates=infrastructure_predicates,
        metric_predicates={},
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
    aggregate_structure_typed = bool(
        set(variants) == {"FULL", "A4", "A5"}
        and all(_is_mapping(variants.get(name)) for name in ("FULL", "A4", "A5"))
        and _is_nonnegative_int(full.get("completed"))
        and _is_nonnegative_int(full.get("total_actions"))
        and _is_nonnegative_int(a4.get("completed"))
        and _is_nonnegative_int(a5.get("completed"))
    )
    infrastructure_predicates = {
        "aggregate_proofs_are_typed": aggregate_structure_typed,
        "artifact_self_hash": _verify_hash_without_newline(report, hash_field="artifact_core_hash"),
        "exact_protocol": report.get("protocol_manifest_hash") == STAGE14_PROTOCOL_SHA256
        and report.get("protocol_manifest_matches_run") is True,
        "schema": report.get("schema") == "arc3.ablations.paired.v0.1",
        "source_clean_and_exact": report.get("git_commit") == frozen_commit
        and report.get("dirty_worktree") is False,
        "typed_rows_verified": report.get("verified") is True and report.get("status") == "PASS",
    }
    metric_predicates = {
        "full_actions_at_most_157": 0 <= full_actions <= 157,
        "full_at_least_8_of_14": full_completed >= 8,
        "full_gap_over_a4_at_least_7": full_completed - a4_completed >= 7,
        "full_gap_over_a5_at_least_8": full_completed - a5_completed >= 8,
        "no_world_model_at_most_1": 0 <= a4_completed <= 1,
        "no_goal_exactly_0": a5_completed == 0,
    }
    return _validation(
        "stage14-ablations",
        infrastructure_predicates=infrastructure_predicates,
        metric_predicates=metric_predicates,
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
    infrastructure_predicates = {
        "artifact_self_hash": verify_object_hash(report, hash_field="artifact_core_hash"),
        "acceptance_is_typed": _exact_field_types(
            report.get("acceptance"),
            booleans=frozenset(
                {
                    "causal_controls",
                    "checkpoint_resume",
                    "historical_regressions",
                    "procedural_pairs",
                    "source_clean",
                    "within_600_second_wall_limit",
                }
            ),
            integers=frozenset({"registry_max_entries"}),
        ),
        "measurement_proofs_are_typed": all(
            _is_nonnegative_int(value)
            for value in (
                checkpoint.get("case_count"),
                checkpoint.get("passed_cases"),
                procedural.get("pair_count"),
                procedural.get("passed_pairs"),
            )
        ),
        "schema": report.get("schema") == "arc3.build-001.stage-04-palette-equivariance.v0.1",
        "source_clean_and_exact": _source_commit(report) == frozen_commit
        and _object(report.get("source_identity")).get("dirty_worktree") is False,
        "typed_child_status": report.get("status") in {"PASS", "FAILED_MECHANISM"},
    }
    metric_predicates = {
        "checkpoint_16_of_16": checkpoint.get("case_count") == 16
        and checkpoint.get("passed_cases") == 16,
        "full_child_acceptance": report.get("status") == "PASS"
        and _boolean_acceptance_passes(report.get("acceptance")),
        "procedural_256_of_256": procedural.get("pair_count") == 256
        and procedural.get("passed_pairs") == 256,
    }
    return _validation(
        "palette-equivariance",
        infrastructure_predicates=infrastructure_predicates,
        metric_predicates=metric_predicates,
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
    infrastructure_predicates = {
        "artifact_self_hash": verify_object_hash(report, hash_field="artifact_core_hash"),
        "acceptance_is_typed": _exact_field_types(
            report.get("acceptance"),
            booleans=frozenset(
                {
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
                }
            ),
        ),
        "measurement_proofs_are_typed": all(
            _is_nonnegative_int(value)
            for value in (
                checkpoint.get("case_count"),
                checkpoint.get("passed_cases"),
                procedural.get("pair_count"),
                procedural.get("passed_pairs"),
                procedural.get("post_calibration_inverse_request_denominator"),
                procedural.get("post_calibration_inverse_request_numerator"),
            )
        ),
        "schema": report.get("schema") == "arc3.build-001.stage-05-action-equivariance.v0.1",
        "source_clean_and_exact": _source_commit(report) == frozen_commit
        and _object(report.get("source_identity")).get("dirty_worktree") is False,
        "typed_child_status": report.get("status") in {"PASS", "FAILED_MECHANISM"},
    }
    metric_predicates = {
        "checkpoint_16_of_16": checkpoint.get("case_count") == 16
        and checkpoint.get("passed_cases") == 16,
        "full_child_acceptance": report.get("status") == "PASS"
        and _boolean_acceptance_passes(report.get("acceptance")),
        "inverse_528_of_528": inverse == 528 and inverse_pass == 528,
        "procedural_128_of_128": procedural.get("pair_count") == 128
        and procedural.get("passed_pairs") == 128,
    }
    return _validation(
        "action-equivariance",
        infrastructure_predicates=infrastructure_predicates,
        metric_predicates=metric_predicates,
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
    intervention_cases = _array(intervention.get("cases"))
    case_proofs_typed = len(intervention_cases) == 64 and all(
        _is_mapping(raw)
        and _is_mapping(_object(raw).get("case"))
        and isinstance(_object(_object(raw).get("case")).get("family"), str)
        and isinstance(_object(raw).get("case_passed"), bool)
        for raw in intervention_cases
    )
    if returncode not in {0, 1}:
        errors.append(f"invalid-rule-child-returncode:{returncode}")
    infrastructure_predicates = {
        "artifact_self_hash": verify_object_hash(report, hash_field="artifact_core_hash"),
        "acceptance_is_typed": _exact_field_types(
            report.get("acceptance"),
            booleans=frozenset(
                {
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
                }
            ),
        ),
        "case_proofs_are_typed": case_proofs_typed,
        "measurement_proofs_are_typed": all(
            _is_nonnegative_int(value)
            for value in (
                intervention.get("case_count"),
                intervention.get("exercised_cases"),
                intervention.get("passed_cases"),
                noise.get("case_count"),
                noise.get("passed_cases"),
                noise.get("resolved_as_noise"),
                decision.get("infrastructure_failure_count"),
            )
        ),
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
        and _object(report.get("acceptance")).get(
            "competition_integrity_delegated_to_stage10_parent"
        )
        is True
        and _object(report.get("acceptance")).get("holdout_integrity") is True,
    }
    metric_predicates = {
        "action_effect_rotation_32_of_32": len(action_rows) == 32 and action_passed == 32,
        "all_interventions_exercised": intervention.get("case_count") == 64
        and intervention.get("exercised_cases") == 64,
        "known_failures_retained": _integer(intervention.get("passed_cases")) >= 32
        and noise.get("case_count") == 32
        and _is_nonnegative_int(noise.get("passed_cases")),
    }
    # The current Stage 06 failed traversability/noise mechanisms remain a
    # separately visible measurement.  They do not erase the frozen Stage 10
    # regression floor, which requires exact action-effect preservation and
    # complete exposure rather than retroactive relabeling.
    return _validation(
        "rule-change",
        infrastructure_predicates=infrastructure_predicates,
        metric_predicates=metric_predicates,
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
    infrastructure_predicates = {
        "artifact_self_hash": verify_object_hash(report, hash_field="artifact_core_hash"),
        "acceptance_is_typed": _exact_field_types(
            report.get("acceptance"),
            booleans=frozenset(
                {
                    "checkpoint_tamper_rejected",
                    "deep_exact_continuation",
                    "deterministic_seed_repeatability",
                    "fast_exact_continuation",
                    "trace_replay",
                    "trace_tamper_rejected",
                }
            ),
        ),
        "schema": report.get("schema") == STAGE10_CHECKPOINT_SCHEMA,
        "source_clean_and_exact": _object(report.get("source_identity")).get("git_commit")
        == frozen_commit
        and _object(report.get("source_identity")).get("dirty_worktree") is False,
    }
    metric_predicates = {
        "deep_exact_continuation": acceptance.get("deep_exact_continuation") is True,
        "deterministic_repeat": acceptance.get("deterministic_seed_repeatability") is True,
        "fast_exact_continuation": acceptance.get("fast_exact_continuation") is True,
        "trace_replay": acceptance.get("trace_replay") is True,
        "trace_tamper_rejected": acceptance.get("trace_tamper_rejected") is True,
        "checkpoint_tamper_rejected": acceptance.get("checkpoint_tamper_rejected") is True,
    }
    return _validation(
        "checkpoint-replay",
        infrastructure_predicates=infrastructure_predicates,
        metric_predicates=metric_predicates,
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
    peak_value = _object(profile.get("kernel_memory_after")).get("peak_rss_bytes")
    working_set_value = _object(profile.get("kernel_memory_after")).get("working_set_peak_bytes")
    peak_typed = _is_nonnegative_int(peak_value) or _is_nonnegative_int(working_set_value)
    infrastructure_predicates = {
        "artifact_self_hash": isinstance(receipt_hash, str)
        and _verify_hash_without_newline(report, hash_field="receipt_sha256"),
        "profile_valid": profile.get("verified") is True,
        "measurement_proofs_are_typed": _is_number(decision.get("maximum"))
        and math.isfinite(float(cast(int | float, decision.get("maximum"))))
        and float(cast(int | float, decision.get("maximum"))) >= 0.0
        and peak_typed
        and _is_nonnegative_int(profile.get("trace_bytes")),
        "schema": report.get("schema") == "arc3.stage16.profile.v0.1",
        "source_clean_and_exact": report.get("git_commit") == frozen_commit
        and _object(report.get("source_identity")).get("verified") is True,
        "typed_child_status": report.get("status") in {"PASS", "PARTIAL", "FAILED_MECHANISM"},
        "valid_child_return": returncode in {0, 1},
    }
    metric_predicates = {
        "decision_max_at_most_2_seconds": 0.0
        <= _number(decision.get("maximum"))
        <= MAX_DECISION_SECONDS,
        "rss_at_most_2_gib": 0
        <= _integer(_object(profile.get("kernel_memory_after")).get("peak_rss_bytes"))
        <= MAX_PEAK_RSS_BYTES,
        "trace_at_most_256_mib": 0
        <= _integer(profile.get("trace_bytes"))
        <= MAX_TRACE_BYTES_PER_RUN,
    }
    peak = _integer(_object(profile.get("kernel_memory_after")).get("peak_rss_bytes"))
    if peak < 0:
        peak = _integer(_object(profile.get("kernel_memory_after")).get("working_set_peak_bytes"))
        metric_predicates["rss_at_most_2_gib"] = 0 <= peak <= MAX_PEAK_RSS_BYTES
    return _validation(
        "resource-profile",
        infrastructure_predicates=infrastructure_predicates,
        metric_predicates=metric_predicates,
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
    license_summary = _object(report.get("license_summary"))
    git = _object(report.get("git"))
    reachable_paths = report.get("inputs")
    reachable_paths = _object(reachable_paths).get("reachable_policy_paths")
    reachable_hashes = report.get("reachable_policy_source_hashes")
    coverage = _object(report.get("production_policy_static_coverage"))
    expected_checks = (
        "archive_static",
        "policy_static",
        "secret_scan",
        "source_identity",
        "supply_chain",
    )
    checks_typed = set(checks) == set(expected_checks) and all(
        isinstance(checks.get(name), Mapping)
        and isinstance(_object(checks.get(name)).get("passed"), bool)
        for name in expected_checks
    )
    reachable_proofs_typed = (
        _is_list(reachable_paths)
        and all(isinstance(item, str) and item for item in reachable_paths)
        and list(cast(list[str], reachable_paths)) == sorted(set(cast(list[str], reachable_paths)))
        and _is_mapping(reachable_hashes)
        and set(reachable_hashes) == set(reachable_paths)
        and all(
            isinstance(value, str) and value.startswith("sha256:") and len(value) == 71
            for value in reachable_hashes.values()
        )
    )
    infrastructure_predicates = {
        "artifact_self_hash": isinstance(receipt_hash, str)
        and _verify_hash_without_newline(report, hash_field="receipt_sha256"),
        "checks_are_typed": checks_typed,
        "finding_counts_are_typed": isinstance(counts := finding_counts, Mapping)
        and set(counts) == {"blocking", "total", "warnings"}
        and _is_nonnegative_int(counts.get("blocking"))
        and _is_nonnegative_int(counts.get("total"))
        and _is_nonnegative_int(counts.get("warnings"))
        and isinstance(report.get("passed"), bool),
        "package_only_inputs": set(inputs)
        >= {
            "manifest",
            "manifest_binding",
            "manifest_sha256",
            "public_identifier_count",
            "public_identifier_mode",
            "run_state",
        }
        and inputs.get("manifest") is None
        and inputs.get("manifest_sha256") is None
        and inputs.get("run_state") is None
        and inputs.get("public_identifier_count") == 0
        and not isinstance(inputs.get("public_identifier_count"), bool)
        and inputs.get("public_identifier_mode") == "disabled-package-only"
        and _object(inputs.get("manifest_binding"))
        == {
            "declaration": "disabled-package-only",
            "expected_sha256": None,
            "issue": "semantic public-manifest access is prohibited in this profile",
        },
        "package_only_scope_exact": report.get("passed") is False
        and report.get("full_competition_integrity_status") == "NOT_EVALUATED_PUBLIC_IDENTIFIERS"
        and report.get("integrity_scope") == "package-only-no-public-identifiers"
        and isinstance(report.get("package_only_passed"), bool),
        "reachable_policy_proofs_are_typed": reachable_proofs_typed,
        "static_policy_coverage_exact": set(coverage)
        == {
            "algorithm",
            "entry_points",
            "entry_points_reached",
            "limitations",
            "policy_scan_covers_reachable_paths",
            "reachable_file_count",
            "reachable_paths_hashed",
            "status",
        }
        and coverage.get("algorithm") == "static-first-party-import-closure-v0.1"
        and inputs.get("entry_points") == ["agent/my_agent.py"]
        and coverage.get("entry_points") == ["agent/my_agent.py"]
        and coverage.get("entry_points_reached") == coverage.get("entry_points")
        and coverage.get("limitations")
        == (
            "Static first-party import reachability does not prove runtime dynamic-import "
            "or native-extension containment."
        )
        and coverage.get("policy_scan_covers_reachable_paths") is True
        and coverage.get("reachable_paths_hashed") is True
        and _is_list(reachable_paths)
        and coverage.get("reachable_file_count") == len(reachable_paths)
        and not isinstance(coverage.get("reachable_file_count"), bool)
        and coverage.get("status") == "PASS",
        "offline_scanner_contract": assurance.get("kind") == "static-only"
        and assurance.get("scanner_network_mode") == "offline-by-construction"
        and assurance.get("public_identifier_scan")
        == "NOT_EVALUATED_PACKAGE_ONLY_NO_SEMANTIC_MANIFEST_ACCESS",
        "schema": report.get("schema") == "arc3.integrity.receipt.v0.2",
        "supply_chain_license_exact": license_summary.get("first_party_license_status") == "MIT-0"
        and license_summary.get("status") == "PASS"
        and all(
            _is_nonnegative_int(license_summary.get(name)) and license_summary.get(name) == 0
            for name in (
                "installed_version_mismatch_count",
                "not_evaluated_count",
                "unknown_or_missing_metadata_count",
            )
        ),
        "source_clean_and_exact": git.get("commit") == frozen_commit
        and git.get("dirty_worktree") is False,
    }
    metric_predicates = {
        "package_only_checks_pass": report.get("package_only_passed") is True
        and all(_object(checks.get(name)).get("passed") is True for name in expected_checks),
        "zero_blocking_findings": finding_counts.get("blocking") == 0,
        "zero_total_findings": finding_counts.get("total") == 0,
    }
    return _validation(
        "competition-integrity",
        infrastructure_predicates=infrastructure_predicates,
        metric_predicates=metric_predicates,
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
    "PREDECLARATION_AMENDMENT_PATH",
    "PREDECLARATION_AMENDMENT_SHA256",
    "PREDECLARATION_PATH",
    "PREDECLARATION_SHA256",
    "PUBLIC_PARTITION_MANIFEST_SHA256",
    "SOURCE_FLOOR_COMMIT",
    "SOURCE_FLOOR_TREE",
    "STAGE10_CHECKPOINT_SCHEMA",
    "STAGE10_CHILD_AUTHORITY_SCHEMA",
    "STAGE10_PARENT_RECEIPT_SCHEMA",
    "STAGE10_PREFLIGHT_SCHEMA",
    "STAGE10_RESULT_SCHEMA",
    "STAGE10_SOCKET_DENIAL_SCHEMA",
    "STAGE13_EVIDENCE_SHA256",
    "STAGE14_PROTOCOL_SHA256",
    "UV_LOCK_SHA256",
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
    "validate_predeclaration_amendment_bytes",
    "validate_predeclaration_bytes",
    "validate_resource_profile",
    "validate_rule_change",
    "validate_stage13",
    "validate_stage13_verification",
]
