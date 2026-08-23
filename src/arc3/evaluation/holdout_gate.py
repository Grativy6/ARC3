"""Typed, hash-bound Build 001 Stage 11/12 holdout gate receipts.

This module is deliberately environment-free.  It hashes the sealed public
manifest as opaque bytes and never imports an ARC environment adapter, parses
game identities, or opens gameplay.  Public evaluation must separately
revalidate an earned receipt before it may parse the manifest.
"""

from __future__ import annotations

import json
import os
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, TypeGuard, cast

from arc3.competition_runtime import COMPETITION_RUNTIME_SCHEMA
from arc3.errors import EvaluationError
from arc3.evaluation.artifacts import (
    canonical_json_bytes,
    seal_object,
    sha256_bytes,
    sha256_file,
    verify_object_hash,
)
from arc3.evaluation.development_recovery import AGGREGATE_SCHEMA as STAGE09_SCHEMA
from arc3.evaluation.stage10_regression import (
    PREDECLARATION_SHA256 as STAGE10_PREDECLARATION_SHA256,
)
from arc3.evaluation.stage10_regression import STAGE10_RESULT_SCHEMA, SuiteDisposition
from arc3.integrity import INTEGRITY_SCHEMA, IntegrityReceipt, discover_policy_files
from arc3.types import JSONValue

STAGE11_GATE_SCHEMA = "arc3.build-001.stage-11-holdout-gate.v0.1"
STAGE12_NONCONSUMPTION_SCHEMA = "arc3.build-001.stage-12-nonconsumption.v0.1"
STAGE11_WORKFLOW_PATH = "docs/workflows/001-local-public-failure-recovery.md"
COMPETITION_CONFIG_PATH = "src/arc3/competition-runtime.v0.1.json"
DEPENDENCY_LOCK_PATH = "uv.lock"
OPAQUE_HOLDOUT_COUNT = 10
STAGE12_MILESTONE_ID = "build-001-stage12-v0.1"

_SOURCE_SUFFIXES = frozenset({".json", ".py", ".toml", ".yaml", ".yml"})
_STAGE10_SUITES = frozenset(
    {
        "action-equivariance",
        "checkpoint-replay",
        "competition-integrity",
        "palette-equivariance",
        "resource-profile",
        "rule-change",
        "stage13-evaluate",
        "stage13-verify",
        "stage14-ablations",
    }
)
_CRITERIA = (
    "stage09_pass",
    "stage10_pass",
    "competition_integrity_clear",
    "production_source_unchanged",
    "sealed_holdout_identity_matches",
)
_CLAIM_BOUNDARY = (
    "mechanical holdout-opening decision only; no gameplay, score, or hidden-game claim"
)


class HoldoutDecision(StrEnum):
    """The only two mechanically reachable Stage 11 decisions."""

    EARNED = "HOLDOUT_EARNED"
    NOT_EARNED = "HOLDOUT_NOT_EARNED"


@dataclass(frozen=True, slots=True)
class SourceIdentity:
    """Exact source and production-policy projection at one clean commit."""

    commit: str
    tree: str
    clean_worktree: bool
    first_party_source_sha256: str
    policy_projection_sha256: str
    policy_file_count: int
    competition_config_file_sha256: str
    competition_config_sha256: str
    dependency_lock_sha256: str

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "clean_worktree": self.clean_worktree,
            "commit": self.commit,
            "competition_config_file_sha256": self.competition_config_file_sha256,
            "competition_config_sha256": self.competition_config_sha256,
            "dependency_lock_sha256": self.dependency_lock_sha256,
            "first_party_source_sha256": self.first_party_source_sha256,
            "policy_file_count": self.policy_file_count,
            "policy_projection_sha256": self.policy_projection_sha256,
            "tree": self.tree,
        }

    @classmethod
    def from_mapping(cls, value: object, *, field: str) -> SourceIdentity:
        raw = _mapping(value, field=field)
        expected = {
            "clean_worktree",
            "commit",
            "competition_config_file_sha256",
            "competition_config_sha256",
            "dependency_lock_sha256",
            "first_party_source_sha256",
            "policy_file_count",
            "policy_projection_sha256",
            "tree",
        }
        _exact_keys(raw, expected, field=field)
        count = raw["policy_file_count"]
        if isinstance(count, bool) or not isinstance(count, int) or count <= 0:
            raise EvaluationError(f"{field} policy file count is invalid")
        clean = raw["clean_worktree"]
        if not isinstance(clean, bool):
            raise EvaluationError(f"{field} clean-worktree flag is invalid")
        strings = {
            name: _string(raw[name], field=f"{field}.{name}")
            for name in expected - {"clean_worktree", "policy_file_count"}
        }
        for name, text in strings.items():
            if name in {"commit", "tree"}:
                _validate_git_hash(text, field=f"{field}.{name}")
            else:
                _validate_sha256(text, field=f"{field}.{name}")
        return cls(
            commit=strings["commit"],
            tree=strings["tree"],
            clean_worktree=clean,
            first_party_source_sha256=strings["first_party_source_sha256"],
            policy_projection_sha256=strings["policy_projection_sha256"],
            policy_file_count=count,
            competition_config_file_sha256=strings["competition_config_file_sha256"],
            competition_config_sha256=strings["competition_config_sha256"],
            dependency_lock_sha256=strings["dependency_lock_sha256"],
        )


@dataclass(frozen=True, slots=True)
class HoldoutEvaluationDeclaration:
    """The exact one-shot declaration authorized by an earned receipt."""

    evaluation_id: str
    agents: tuple[str, ...]
    seeds: tuple[int, ...]
    max_actions: int
    max_resets: int
    timeout_seconds: float
    milestone_id: str = STAGE12_MILESTONE_ID

    def __post_init__(self) -> None:
        if not self.evaluation_id or self.evaluation_id != self.evaluation_id.strip():
            raise ValueError("holdout evaluation ID must be normalized and non-empty")
        if self.agents != ("full",):
            raise ValueError("the sealed Stage 12 declaration must run only FULL")
        if not self.seeds or len(set(self.seeds)) != len(self.seeds):
            raise ValueError("the sealed Stage 12 seeds must be non-empty and unique")
        for name, value in {"max_actions": self.max_actions, "max_resets": self.max_resets}.items():
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"{name} must be a positive integer")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if self.milestone_id != STAGE12_MILESTONE_ID:
            raise ValueError("Stage 12 milestone identity changed")

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "agents": list(self.agents),
            "automatic_checkpointing": True,
            "evaluation_id": self.evaluation_id,
            "game_subset": None,
            "hot_path_profile": False,
            "max_actions": self.max_actions,
            "max_resets": self.max_resets,
            "milestone_id": self.milestone_id,
            "partition": "public-holdout",
            "python_allocation_tracing": True,
            "seeds": list(self.seeds),
            "timeout_seconds": self.timeout_seconds,
        }

    @classmethod
    def from_mapping(cls, value: object) -> HoldoutEvaluationDeclaration:
        raw = _mapping(value, field="holdout_evaluation")
        expected = {
            "agents",
            "automatic_checkpointing",
            "evaluation_id",
            "game_subset",
            "hot_path_profile",
            "max_actions",
            "max_resets",
            "milestone_id",
            "partition",
            "python_allocation_tracing",
            "seeds",
            "timeout_seconds",
        }
        _exact_keys(raw, expected, field="holdout_evaluation")
        if (
            raw["partition"] != "public-holdout"
            or raw["game_subset"] is not None
            or raw["hot_path_profile"] is not False
            or raw["automatic_checkpointing"] is not True
            or raw["python_allocation_tracing"] is not True
        ):
            raise EvaluationError("holdout evaluation safety declaration changed")
        agents = raw["agents"]
        seeds = raw["seeds"]
        if not isinstance(agents, list) or any(not isinstance(item, str) for item in agents):
            raise EvaluationError("holdout evaluation agents are invalid")
        if not isinstance(seeds, list) or any(
            isinstance(item, bool) or not isinstance(item, int) for item in seeds
        ):
            raise EvaluationError("holdout evaluation seeds are invalid")
        timeout = raw["timeout_seconds"]
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)):
            raise EvaluationError("holdout evaluation timeout is invalid")
        try:
            return cls(
                evaluation_id=_string(raw["evaluation_id"], field="evaluation_id"),
                agents=tuple(cast(list[str], agents)),
                seeds=tuple(cast(list[int], seeds)),
                max_actions=_positive_int(raw["max_actions"], field="max_actions"),
                max_resets=_positive_int(raw["max_resets"], field="max_resets"),
                timeout_seconds=float(timeout),
                milestone_id=_string(raw["milestone_id"], field="milestone_id"),
            )
        except ValueError as error:
            raise EvaluationError(str(error)) from error


@dataclass(frozen=True, slots=True)
class ValidatedHoldoutGate:
    """A parsed Stage 11 receipt whose structure and self-hash are valid."""

    receipt: Mapping[str, Any]
    decision: HoldoutDecision
    criteria: Mapping[str, bool]
    development_source: SourceIdentity
    execution_source: SourceIdentity
    evaluation: HoldoutEvaluationDeclaration
    manifest_sha256: str
    opaque_count: int


def _mapping(value: object, *, field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise EvaluationError(f"{field} must be an object")
    return cast(Mapping[str, object], value)


def _exact_keys(value: Mapping[str, object], expected: set[str], *, field: str) -> None:
    if set(value) != expected:
        raise EvaluationError(f"{field} fields do not match the frozen schema")


def _string(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise EvaluationError(f"{field} must be a non-empty string")
    return value


def _positive_int(value: object, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise EvaluationError(f"{field} must be a positive integer")
    return value


def _validate_sha256(value: str, *, field: str) -> None:
    digest = value.removeprefix("sha256:")
    if (
        not value.startswith("sha256:")
        or len(digest) != 64
        or any(character not in "0123456789abcdef" for character in digest)
    ):
        raise EvaluationError(f"{field} must be a canonical sha256 identity")


def _validate_git_hash(value: str, *, field: str) -> None:
    if len(value) != 40 or any(character not in "0123456789abcdef" for character in value):
        raise EvaluationError(f"{field} must be a full lowercase git object identity")


def _load_json_object(raw: bytes, *, field: str) -> dict[str, Any]:
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise EvaluationError(f"{field} is not valid JSON") from error
    if not isinstance(value, dict):
        raise EvaluationError(f"{field} must contain a JSON object")
    return cast(dict[str, Any], value)


def _load_bound_artifact(
    path: Path,
    *,
    expected_file_sha256: str,
    expected_core_hash: str,
    schema: str,
    hash_field: str,
    field: str,
) -> dict[str, Any]:
    _validate_sha256(expected_file_sha256, field=f"{field} file hash")
    _validate_sha256(expected_core_hash, field=f"{field} core hash")
    try:
        raw = path.resolve().read_bytes()
    except OSError as error:
        raise EvaluationError(f"{field} artifact is unreadable") from error
    if sha256_bytes(raw) != expected_file_sha256:
        raise EvaluationError(f"{field} artifact file hash changed")
    document = _load_json_object(raw, field=field)
    if canonical_json_bytes(document) != raw:
        raise EvaluationError(f"{field} artifact is not canonical JSON")
    if document.get("schema") != schema:
        raise EvaluationError(f"{field} artifact schema changed")
    if not verify_object_hash(document, hash_field=hash_field):
        raise EvaluationError(f"{field} artifact self-hash is invalid")
    if document.get(hash_field) != expected_core_hash:
        raise EvaluationError(f"{field} artifact core hash changed")
    return document


def _git(root: Path, *arguments: str) -> str:
    try:
        completed = subprocess.run(
            ("git", *arguments),
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise EvaluationError("source git identity is unavailable") from error
    return completed.stdout.strip()


def _first_party_source_hash(root: Path) -> str:
    candidates: list[Path] = []
    for directory in (root / "src" / "arc3", root / "agent"):
        if directory.is_dir():
            candidates.extend(
                path
                for path in directory.rglob("*")
                if path.is_file()
                and path.suffix.lower() in _SOURCE_SUFFIXES
                and "__pycache__" not in path.parts
            )
    for relative in ("pyproject.toml", DEPENDENCY_LOCK_PATH):
        path = root / relative
        if path.is_file():
            candidates.append(path)
    entries = [
        {"path": path.relative_to(root).as_posix(), "sha256": sha256_file(path)}
        for path in sorted(set(candidates))
    ]
    return sha256_bytes(canonical_json_bytes(entries))


def _competition_config_identity(path: Path) -> tuple[str, str]:
    raw = path.read_bytes()
    document = _load_json_object(raw, field="competition config")
    if document.get("schema") != COMPETITION_RUNTIME_SCHEMA:
        raise EvaluationError("competition config schema changed")
    claimed = document.get("configuration_sha256")
    if not isinstance(claimed, str):
        raise EvaluationError("competition config has no configuration hash")
    _validate_sha256(claimed, field="competition config hash")
    body = {key: value for key, value in document.items() if key != "configuration_sha256"}
    # The production loader hashes canonical JSON without a trailing newline.
    encoded = json.dumps(
        body,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    if sha256_bytes(encoded) != claimed:
        raise EvaluationError("competition config self-hash changed")
    return sha256_bytes(raw), claimed


def source_identity(root: Path) -> SourceIdentity:
    """Measure a repository source identity without importing code from it."""

    repository = root.resolve()
    commit = _git(repository, "rev-parse", "HEAD")
    tree = _git(repository, "rev-parse", "HEAD^{tree}")
    status = _git(repository, "status", "--porcelain=v1", "--untracked-files=all")
    _validate_git_hash(commit, field="source commit")
    _validate_git_hash(tree, field="source tree")
    config_file_hash, config_hash = _competition_config_identity(
        repository / COMPETITION_CONFIG_PATH
    )
    lock_hash = sha256_file(repository / DEPENDENCY_LOCK_PATH)
    policy_files = discover_policy_files(repository)
    policy_entries = [
        {"path": path.relative_to(repository).as_posix(), "sha256": sha256_file(path)}
        for path in policy_files
    ]
    return SourceIdentity(
        commit=commit,
        tree=tree,
        clean_worktree=status == "",
        first_party_source_sha256=_first_party_source_hash(repository),
        policy_projection_sha256=sha256_bytes(canonical_json_bytes(policy_entries)),
        policy_file_count=len(policy_entries),
        competition_config_file_sha256=config_file_hash,
        competition_config_sha256=config_hash,
        dependency_lock_sha256=lock_hash,
    )


def _stage09_source(document: Mapping[str, object]) -> Mapping[str, object] | None:
    for parent_name in ("source_end", "preflight"):
        parent = document.get(parent_name)
        if not isinstance(parent, Mapping):
            continue
        sources = parent.get("sources") if parent_name == "preflight" else parent
        if not isinstance(sources, Mapping):
            continue
        source = sources.get("build_001")
        if isinstance(source, Mapping):
            return cast(Mapping[str, object], source)
    return None


def _stage09_pass(document: Mapping[str, object]) -> bool:
    gate = document.get("gate")
    resources = document.get("resources")
    asset_end = document.get("asset_end")
    preflight = document.get("preflight")
    integrity = preflight.get("competition_integrity") if isinstance(preflight, Mapping) else None
    return bool(
        document.get("status") == "PASS"
        and document.get("evidence_label") == "local-public"
        and document.get("execution_complete") is True
        and document.get("source_stable") is True
        and document.get("cell_count") == document.get("expected_cell_count")
        and isinstance(gate, Mapping)
        and set(gate)
        == {
            "all_evidence_verifies",
            "build_001_full_beats_b0",
            "competition_integrity",
            "distinct_new_completed_games",
            "normal_termination_fraction",
        }
        and all(value is True for value in gate.values())
        and isinstance(resources, Mapping)
        and resources.get("wall_measurement_complete") is True
        and resources.get("wall_within_limit") is True
        and isinstance(asset_end, Mapping)
        and asset_end.get("passed") is True
        and isinstance(integrity, Mapping)
        and bool(integrity)
        and all(
            isinstance(value, Mapping) and value.get("passed") is True
            for value in integrity.values()
        )
    )


def _stage09_integrity_clear(document: Mapping[str, object]) -> bool:
    gate = document.get("gate")
    preflight = document.get("preflight")
    checks = preflight.get("competition_integrity") if isinstance(preflight, Mapping) else None
    return bool(
        isinstance(gate, Mapping)
        and gate.get("competition_integrity") is True
        and isinstance(checks, Mapping)
        and bool(checks)
        and all(
            isinstance(item, Mapping) and item.get("passed") is True for item in checks.values()
        )
    )


def _stage09_holdout_sealed(document: Mapping[str, object]) -> bool:
    holdout = document.get("holdout")
    return bool(
        isinstance(holdout, Mapping)
        and holdout.get("identities_loaded") == 0
        and holdout.get("manifest_loaded_as_metadata") is False
        and holdout.get("public_holdout_gameplay_events") == 0
    )


def _stage09_manifest_bound(document: Mapping[str, object], expected_sha256: str) -> bool:
    preflight = document.get("preflight")
    hashes = preflight.get("public_manifest_hashes") if isinstance(preflight, Mapping) else None
    return bool(
        isinstance(hashes, Mapping)
        and set(hashes) == {"build_000", "build_001"}
        and set(hashes.values()) == {expected_sha256}
    )


def _stage10_pass(document: Mapping[str, object], *, expected_source: SourceIdentity) -> bool:
    validations = document.get("suite_validations")
    if not isinstance(validations, list):
        return False
    suites: dict[str, Mapping[str, object]] = {}
    for value in validations:
        if not isinstance(value, Mapping):
            return False
        suite_id = value.get("suite_id")
        if not isinstance(suite_id, str) or suite_id in suites:
            return False
        suites[suite_id] = cast(Mapping[str, object], value)
    start = document.get("source_identity_start")
    end = document.get("source_identity_end")
    return bool(
        document.get("status") == "PASS"
        and document.get("evidence_label") == "synthetic"
        and document.get("claim") == "NO_GENERALIZATION_CLAIM"
        and document.get("infrastructure_failure") is None
        and document.get("predeclaration_sha256") == STAGE10_PREDECLARATION_SHA256
        and set(suites) == _STAGE10_SUITES
        and all(
            value.get("disposition") == SuiteDisposition.PASS.value
            and value.get("artifact_valid") is True
            and value.get("errors") == []
            for value in suites.values()
        )
        and isinstance(start, Mapping)
        and isinstance(end, Mapping)
        and start == end
        and start.get("verified") is True
        and start.get("clean_worktree") is True
        and start.get("exact_frozen_commit") is True
        and start.get("commit") == expected_source.commit
        and start.get("tree") == expected_source.tree
    )


def _stage10_integrity_clear(document: Mapping[str, object]) -> bool:
    validations = document.get("suite_validations")
    if not isinstance(validations, list):
        return False
    matches = [
        value
        for value in validations
        if isinstance(value, Mapping) and value.get("suite_id") == "competition-integrity"
    ]
    return bool(
        len(matches) == 1
        and matches[0].get("disposition") == SuiteDisposition.PASS.value
        and matches[0].get("artifact_valid") is True
        and matches[0].get("errors") == []
    )


def _integrity_clear(
    raw: bytes,
    *,
    expected_file_sha256: str,
    expected_receipt_sha256: str,
    expected_source: SourceIdentity,
    expected_manifest_sha256: str,
) -> tuple[IntegrityReceipt, bool]:
    _validate_sha256(expected_file_sha256, field="integrity file hash")
    _validate_sha256(expected_receipt_sha256, field="integrity receipt hash")
    if sha256_bytes(raw) != expected_file_sha256:
        raise EvaluationError("competition-integrity artifact file hash changed")
    try:
        receipt = IntegrityReceipt.from_bytes(raw)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        raise EvaluationError(
            "competition-integrity artifact is not canonical and self-hashed"
        ) from error
    if receipt.receipt_sha256 != expected_receipt_sha256:
        raise EvaluationError("competition-integrity receipt authority changed")
    body = receipt.body
    counts = body.get("finding_counts")
    checks = body.get("checks")
    inputs = body.get("inputs")
    git = body.get("git")
    assurance = body.get("assurance_scope")
    source_hashes = body.get("source_hashes")
    required_checks = {
        "archive_static",
        "policy_static",
        "secret_scan",
        "source_identity",
        "supply_chain",
    }
    clear = bool(
        body.get("schema") == INTEGRITY_SCHEMA
        and receipt.passed
        and isinstance(counts, Mapping)
        and counts.get("blocking") == 0
        and counts.get("total") == 0
        and isinstance(checks, Mapping)
        and set(checks) == required_checks
        and all(
            isinstance(value, Mapping) and value.get("passed") is True for value in checks.values()
        )
        and isinstance(inputs, Mapping)
        and inputs.get("manifest_sha256") == expected_manifest_sha256
        and isinstance(git, Mapping)
        and git.get("commit") == expected_source.commit
        and git.get("dirty_worktree") is False
        and isinstance(assurance, Mapping)
        and assurance.get("kind") == "static-only"
        and assurance.get("scanner_network_mode") == "offline-by-construction"
        and isinstance(source_hashes, Mapping)
        and source_hashes.get(DEPENDENCY_LOCK_PATH) == expected_source.dependency_lock_sha256
        and source_hashes.get(COMPETITION_CONFIG_PATH)
        == expected_source.competition_config_file_sha256
    )
    return receipt, clear


def _source_matches_stage09(source: SourceIdentity, document: Mapping[str, object]) -> bool:
    recorded = _stage09_source(document)
    return bool(
        recorded is not None
        and recorded.get("git_commit") == source.commit
        and recorded.get("git_tree") == source.tree
        and recorded.get("first_party_source_sha256") == source.first_party_source_sha256
        and recorded.get("dirty_worktree") is False
        and recorded.get("passed") is True
    )


def _policy_unchanged(development: SourceIdentity, execution: SourceIdentity) -> bool:
    return bool(
        development.clean_worktree
        and execution.clean_worktree
        and development.policy_projection_sha256 == execution.policy_projection_sha256
        and development.policy_file_count == execution.policy_file_count
        and development.competition_config_file_sha256 == execution.competition_config_file_sha256
        and development.competition_config_sha256 == execution.competition_config_sha256
        and development.dependency_lock_sha256 == execution.dependency_lock_sha256
    )


def _workflow_rule(workflow_sha256: str) -> dict[str, JSONValue]:
    return {
        "criteria_order": list(_CRITERIA),
        "decision_expression": (
            "HOLDOUT_EARNED iff all five criteria are true; otherwise HOLDOUT_NOT_EARNED"
        ),
        "owner_override_during_autonomous_run": False,
        "rule_text": [
            "Stage 09 = PASS",
            "Stage 10 = PASS",
            "no unresolved competition-integrity failure exists",
            "production source has not changed since decisive development evaluation",
            "holdout identity matches the sealed Build 000 manifest",
        ],
        "workflow_path": STAGE11_WORKFLOW_PATH,
        "workflow_sha256": workflow_sha256,
    }


def _utc_timestamp(value: str | None) -> str:
    result = value or datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")
    try:
        parsed = datetime.fromisoformat(result.replace("Z", "+00:00"))
    except ValueError as error:
        raise EvaluationError("receipt timestamp is not ISO-8601") from error
    if parsed.tzinfo is None:
        raise EvaluationError("receipt timestamp must include a timezone")
    return result


def create_holdout_gate_receipt(
    *,
    stage09_path: Path,
    stage09_file_sha256: str,
    stage09_core_hash: str,
    stage10_path: Path,
    stage10_file_sha256: str,
    stage10_core_hash: str,
    integrity_path: Path,
    integrity_file_sha256: str,
    integrity_receipt_sha256: str,
    development_source_root: Path,
    execution_source_root: Path,
    expected_execution_commit: str,
    manifest_path: Path,
    expected_manifest_sha256: str,
    evaluation: HoldoutEvaluationDeclaration,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Evaluate the five frozen criteria without opening the sealed manifest."""

    _validate_git_hash(expected_execution_commit, field="expected execution commit")
    _validate_sha256(expected_manifest_sha256, field="sealed manifest hash")
    stage09 = _load_bound_artifact(
        stage09_path,
        expected_file_sha256=stage09_file_sha256,
        expected_core_hash=stage09_core_hash,
        schema=STAGE09_SCHEMA,
        hash_field="artifact_core_hash",
        field="Stage 09",
    )
    stage10 = _load_bound_artifact(
        stage10_path,
        expected_file_sha256=stage10_file_sha256,
        expected_core_hash=stage10_core_hash,
        schema=STAGE10_RESULT_SCHEMA,
        hash_field="artifact_core_hash",
        field="Stage 10",
    )
    development_source = source_identity(development_source_root)
    execution_source = source_identity(execution_source_root)
    if execution_source.commit != expected_execution_commit or not execution_source.clean_worktree:
        raise EvaluationError("Stage 11 execution source is not the exact clean frozen commit")
    try:
        manifest_sha256 = sha256_file(manifest_path.resolve())
        workflow_sha256 = sha256_file(execution_source_root.resolve() / STAGE11_WORKFLOW_PATH)
        integrity_raw = integrity_path.resolve().read_bytes()
    except OSError as error:
        raise EvaluationError("Stage 11 authority input is unreadable") from error
    _, integrity_clear = _integrity_clear(
        integrity_raw,
        expected_file_sha256=integrity_file_sha256,
        expected_receipt_sha256=integrity_receipt_sha256,
        expected_source=execution_source,
        expected_manifest_sha256=expected_manifest_sha256,
    )
    source_unchanged = bool(
        _source_matches_stage09(development_source, stage09)
        and _policy_unchanged(development_source, execution_source)
    )
    criteria = {
        "stage09_pass": _stage09_pass(stage09),
        "stage10_pass": _stage10_pass(stage10, expected_source=execution_source),
        "competition_integrity_clear": bool(
            integrity_clear
            and _stage09_integrity_clear(stage09)
            and _stage10_integrity_clear(stage10)
        ),
        "production_source_unchanged": source_unchanged,
        "sealed_holdout_identity_matches": bool(
            manifest_sha256 == expected_manifest_sha256
            and _stage09_holdout_sealed(stage09)
            and _stage09_manifest_bound(stage09, expected_manifest_sha256)
            and OPAQUE_HOLDOUT_COUNT == 10
        ),
    }
    decision = (
        HoldoutDecision.EARNED
        if all(criteria[name] for name in _CRITERIA)
        else HoldoutDecision.NOT_EARNED
    )
    stage09_status = _string(stage09.get("status"), field="Stage 09 status")
    stage10_status = _string(stage10.get("status"), field="Stage 10 status")
    payload: dict[str, Any] = {
        "claim_boundary": _CLAIM_BOUNDARY,
        "criteria": criteria,
        "decision": decision.value,
        "dependency_lock": {
            "path": DEPENDENCY_LOCK_PATH,
            "sha256": execution_source.dependency_lock_sha256,
        },
        "evidence_label": "synthetic",
        "generated_at": _utc_timestamp(generated_at),
        "holdout": {
            "identities_loaded": 0,
            "manifest_parsed": False,
            "manifest_sha256": manifest_sha256,
            "opaque_partition_count": OPAQUE_HOLDOUT_COUNT,
        },
        "holdout_evaluation": evaluation.to_dict(),
        "integrity_authority": {
            "file_sha256": integrity_file_sha256,
            "receipt_sha256": integrity_receipt_sha256,
            "schema": INTEGRITY_SCHEMA,
        },
        "production_source": {
            "development": development_source.to_dict(),
            "execution": execution_source.to_dict(),
        },
        "production_config": {
            "configuration_sha256": execution_source.competition_config_sha256,
            "file_sha256": execution_source.competition_config_file_sha256,
            "path": COMPETITION_CONFIG_PATH,
        },
        "schema": STAGE11_GATE_SCHEMA,
        "stage09": {
            "artifact_core_hash": stage09_core_hash,
            "file_sha256": stage09_file_sha256,
            "schema": STAGE09_SCHEMA,
            "status": stage09_status,
        },
        "stage10": {
            "artifact_core_hash": stage10_core_hash,
            "file_sha256": stage10_file_sha256,
            "schema": STAGE10_RESULT_SCHEMA,
            "status": stage10_status,
        },
        "workflow_rule": _workflow_rule(workflow_sha256),
    }
    return seal_object(payload, hash_field="artifact_core_hash")


def validate_holdout_gate_receipt(document: Mapping[str, Any]) -> ValidatedHoldoutGate:
    """Validate the exact Stage 11 schema and recompute its decision."""

    expected = {
        "artifact_core_hash",
        "claim_boundary",
        "criteria",
        "decision",
        "dependency_lock",
        "evidence_label",
        "generated_at",
        "holdout",
        "holdout_evaluation",
        "integrity_authority",
        "production_config",
        "production_source",
        "schema",
        "stage09",
        "stage10",
        "workflow_rule",
    }
    _exact_keys(document, expected, field="Stage 11 receipt")
    if (
        document.get("schema") != STAGE11_GATE_SCHEMA
        or document.get("claim_boundary") != _CLAIM_BOUNDARY
        or document.get("evidence_label") != "synthetic"
        or not verify_object_hash(dict(document), hash_field="artifact_core_hash")
    ):
        raise EvaluationError("Stage 11 receipt identity/self-hash changed")
    _utc_timestamp(_string(document.get("generated_at"), field="generated_at"))
    criteria_raw = _mapping(document.get("criteria"), field="criteria")
    _exact_keys(criteria_raw, set(_CRITERIA), field="criteria")
    if any(not isinstance(value, bool) for value in criteria_raw.values()):
        raise EvaluationError("Stage 11 criteria must be boolean")
    criteria = cast(Mapping[str, bool], criteria_raw)
    expected_decision = (
        HoldoutDecision.EARNED
        if all(criteria[name] for name in _CRITERIA)
        else HoldoutDecision.NOT_EARNED
    )
    if document.get("decision") != expected_decision.value:
        raise EvaluationError("Stage 11 decision does not follow the frozen rule")
    source = _mapping(document.get("production_source"), field="production_source")
    _exact_keys(source, {"development", "execution"}, field="production_source")
    development = SourceIdentity.from_mapping(source["development"], field="development source")
    execution = SourceIdentity.from_mapping(source["execution"], field="execution source")
    dependency = _mapping(document.get("dependency_lock"), field="dependency_lock")
    _exact_keys(dependency, {"path", "sha256"}, field="dependency_lock")
    config = _mapping(document.get("production_config"), field="production_config")
    _exact_keys(
        config,
        {"configuration_sha256", "file_sha256", "path"},
        field="production_config",
    )
    if (
        dependency.get("path") != DEPENDENCY_LOCK_PATH
        or dependency.get("sha256") != execution.dependency_lock_sha256
        or config.get("path") != COMPETITION_CONFIG_PATH
        or config.get("file_sha256") != execution.competition_config_file_sha256
        or config.get("configuration_sha256") != execution.competition_config_sha256
    ):
        raise EvaluationError("Stage 11 config/dependency binding changed")
    holdout = _mapping(document.get("holdout"), field="holdout")
    _exact_keys(
        holdout,
        {"identities_loaded", "manifest_parsed", "manifest_sha256", "opaque_partition_count"},
        field="holdout",
    )
    manifest_hash = _string(holdout.get("manifest_sha256"), field="holdout manifest hash")
    _validate_sha256(manifest_hash, field="holdout manifest hash")
    if (
        holdout.get("identities_loaded") != 0
        or holdout.get("manifest_parsed") is not False
        or holdout.get("opaque_partition_count") != OPAQUE_HOLDOUT_COUNT
    ):
        raise EvaluationError("Stage 11 receipt claims holdout identity access")
    workflow = _mapping(document.get("workflow_rule"), field="workflow_rule")
    expected_workflow = _workflow_rule(
        _string(workflow.get("workflow_sha256"), field="workflow hash")
    )
    if dict(workflow) != expected_workflow:
        raise EvaluationError("Stage 11 workflow rule changed")
    for name, schema in (("stage09", STAGE09_SCHEMA), ("stage10", STAGE10_RESULT_SCHEMA)):
        binding = _mapping(document.get(name), field=name)
        _exact_keys(
            binding,
            {"artifact_core_hash", "file_sha256", "schema", "status"},
            field=name,
        )
        if binding.get("schema") != schema:
            raise EvaluationError(f"{name} bound schema changed")
        for hash_name in ("artifact_core_hash", "file_sha256"):
            _validate_sha256(
                _string(binding.get(hash_name), field=f"{name}.{hash_name}"),
                field=f"{name}.{hash_name}",
            )
        _string(binding.get("status"), field=f"{name}.status")
    integrity = _mapping(document.get("integrity_authority"), field="integrity_authority")
    _exact_keys(
        integrity,
        {"file_sha256", "receipt_sha256", "schema"},
        field="integrity_authority",
    )
    if integrity.get("schema") != INTEGRITY_SCHEMA:
        raise EvaluationError("integrity authority schema changed")
    for hash_name in ("file_sha256", "receipt_sha256"):
        _validate_sha256(
            _string(integrity.get(hash_name), field=f"integrity_authority.{hash_name}"),
            field=f"integrity_authority.{hash_name}",
        )
    evaluation = HoldoutEvaluationDeclaration.from_mapping(document.get("holdout_evaluation"))
    return ValidatedHoldoutGate(
        receipt=document,
        decision=expected_decision,
        criteria=criteria,
        development_source=development,
        execution_source=execution,
        evaluation=evaluation,
        manifest_sha256=manifest_hash,
        opaque_count=OPAQUE_HOLDOUT_COUNT,
    )


def load_bound_holdout_gate(
    path: Path,
    *,
    expected_file_sha256: str,
    expected_core_hash: str,
) -> ValidatedHoldoutGate:
    """Load a canonical Stage 11 receipt under two external hash anchors."""

    document = _load_bound_artifact(
        path,
        expected_file_sha256=expected_file_sha256,
        expected_core_hash=expected_core_hash,
        schema=STAGE11_GATE_SCHEMA,
        hash_field="artifact_core_hash",
        field="Stage 11",
    )
    return validate_holdout_gate_receipt(document)


def revalidate_earned_holdout_gate(
    *,
    gate_path: Path,
    gate_file_sha256: str,
    gate_core_hash: str,
    stage09_path: Path,
    stage10_path: Path,
    integrity_path: Path,
    manifest_path: Path,
    source_root: Path,
) -> ValidatedHoldoutGate:
    """Revalidate every Stage 11 authority before public manifest parsing."""

    gate = load_bound_holdout_gate(
        gate_path,
        expected_file_sha256=gate_file_sha256,
        expected_core_hash=gate_core_hash,
    )
    if gate.decision is not HoldoutDecision.EARNED:
        raise EvaluationError("public holdout was not earned by the frozen Stage 11 rule")
    stage09_binding = _mapping(gate.receipt["stage09"], field="stage09")
    stage10_binding = _mapping(gate.receipt["stage10"], field="stage10")
    integrity_binding = _mapping(gate.receipt["integrity_authority"], field="integrity")
    stage09 = _load_bound_artifact(
        stage09_path,
        expected_file_sha256=cast(str, stage09_binding["file_sha256"]),
        expected_core_hash=cast(str, stage09_binding["artifact_core_hash"]),
        schema=STAGE09_SCHEMA,
        hash_field="artifact_core_hash",
        field="Stage 09",
    )
    stage10 = _load_bound_artifact(
        stage10_path,
        expected_file_sha256=cast(str, stage10_binding["file_sha256"]),
        expected_core_hash=cast(str, stage10_binding["artifact_core_hash"]),
        schema=STAGE10_RESULT_SCHEMA,
        hash_field="artifact_core_hash",
        field="Stage 10",
    )
    current_source = source_identity(source_root)
    if current_source != gate.execution_source or not current_source.clean_worktree:
        raise EvaluationError("production source changed after the Stage 11 receipt")
    workflow = _mapping(gate.receipt["workflow_rule"], field="workflow_rule")
    if sha256_file(source_root.resolve() / STAGE11_WORKFLOW_PATH) != workflow["workflow_sha256"]:
        raise EvaluationError("Stage 11 controlling workflow changed")
    if sha256_file(manifest_path.resolve()) != gate.manifest_sha256:
        raise EvaluationError("sealed holdout manifest bytes changed")
    integrity_raw = integrity_path.resolve().read_bytes()
    _, integrity_clear = _integrity_clear(
        integrity_raw,
        expected_file_sha256=cast(str, integrity_binding["file_sha256"]),
        expected_receipt_sha256=cast(str, integrity_binding["receipt_sha256"]),
        expected_source=current_source,
        expected_manifest_sha256=gate.manifest_sha256,
    )
    recomputed = {
        "stage09_pass": _stage09_pass(stage09),
        "stage10_pass": _stage10_pass(stage10, expected_source=current_source),
        "competition_integrity_clear": bool(
            integrity_clear
            and _stage09_integrity_clear(stage09)
            and _stage10_integrity_clear(stage10)
        ),
        "production_source_unchanged": bool(
            _source_matches_stage09(gate.development_source, stage09)
            and _policy_unchanged(gate.development_source, current_source)
        ),
        "sealed_holdout_identity_matches": bool(
            _stage09_holdout_sealed(stage09)
            and _stage09_manifest_bound(stage09, gate.manifest_sha256)
            and sha256_file(manifest_path.resolve()) == gate.manifest_sha256
            and gate.opaque_count == OPAQUE_HOLDOUT_COUNT
        ),
    }
    if recomputed != dict(gate.criteria) or not all(recomputed.values()):
        raise EvaluationError("Stage 11 criteria no longer revalidate from bound evidence")
    return gate


def create_nonconsumption_receipt(
    *,
    gate_path: Path,
    gate_file_sha256: str,
    gate_core_hash: str,
    manifest_path: Path,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Create the only Stage 12 result reachable from a not-earned gate."""

    gate = load_bound_holdout_gate(
        gate_path,
        expected_file_sha256=gate_file_sha256,
        expected_core_hash=gate_core_hash,
    )
    if gate.decision is not HoldoutDecision.NOT_EARNED:
        raise EvaluationError("nonconsumption receipt is reachable only for HOLDOUT_NOT_EARNED")
    if sha256_file(manifest_path.resolve()) != gate.manifest_sha256:
        raise EvaluationError("sealed manifest changed before nonconsumption receipt")
    payload: dict[str, Any] = {
        "claim_boundary": "nonconsumption only; no public-holdout result or score exists",
        "decision": HoldoutDecision.NOT_EARNED.value,
        "environment_adapter_loaded": False,
        "environment_actions": 0,
        "evidence_label": "synthetic",
        "gameplay_opened": False,
        "generated_at": _utc_timestamp(generated_at),
        "holdout": {
            "identities_loaded": 0,
            "manifest_parsed": False,
            "manifest_sha256": gate.manifest_sha256,
            "opaque_partition_count": gate.opaque_count,
        },
        "schema": STAGE12_NONCONSUMPTION_SCHEMA,
        "stage11": {
            "artifact_core_hash": gate_core_hash,
            "decision": gate.decision.value,
            "file_sha256": gate_file_sha256,
        },
    }
    return seal_object(payload, hash_field="artifact_core_hash")


def validate_nonconsumption_receipt(
    document: Mapping[str, Any],
    *,
    gate_path: Path,
    manifest_path: Path,
) -> None:
    """Validate a Stage 12 receipt and its exact Stage 11/manifest anchors."""

    expected = {
        "artifact_core_hash",
        "claim_boundary",
        "decision",
        "environment_adapter_loaded",
        "environment_actions",
        "evidence_label",
        "gameplay_opened",
        "generated_at",
        "holdout",
        "schema",
        "stage11",
    }
    _exact_keys(document, expected, field="Stage 12 nonconsumption receipt")
    if (
        document.get("schema") != STAGE12_NONCONSUMPTION_SCHEMA
        or document.get("claim_boundary")
        != "nonconsumption only; no public-holdout result or score exists"
        or document.get("decision") != HoldoutDecision.NOT_EARNED.value
        or document.get("environment_adapter_loaded") is not False
        or document.get("environment_actions") != 0
        or document.get("evidence_label") != "synthetic"
        or document.get("gameplay_opened") is not False
        or not verify_object_hash(dict(document), hash_field="artifact_core_hash")
    ):
        raise EvaluationError("Stage 12 nonconsumption receipt is invalid")
    _utc_timestamp(_string(document.get("generated_at"), field="generated_at"))
    stage11 = _mapping(document.get("stage11"), field="stage11")
    _exact_keys(stage11, {"artifact_core_hash", "decision", "file_sha256"}, field="stage11")
    if stage11.get("decision") != HoldoutDecision.NOT_EARNED.value:
        raise EvaluationError("Stage 12 receipt does not bind a not-earned gate")
    gate = load_bound_holdout_gate(
        gate_path,
        expected_file_sha256=_string(stage11.get("file_sha256"), field="stage11 file hash"),
        expected_core_hash=_string(stage11.get("artifact_core_hash"), field="stage11 core hash"),
    )
    if gate.decision is not HoldoutDecision.NOT_EARNED:
        raise EvaluationError("Stage 12 receipt's gate is no longer not-earned")
    holdout = _mapping(document.get("holdout"), field="holdout")
    if dict(holdout) != {
        "identities_loaded": 0,
        "manifest_parsed": False,
        "manifest_sha256": gate.manifest_sha256,
        "opaque_partition_count": gate.opaque_count,
    }:
        raise EvaluationError("Stage 12 holdout nonconsumption binding changed")
    if sha256_file(manifest_path.resolve()) != gate.manifest_sha256:
        raise EvaluationError("sealed manifest changed after nonconsumption")


def write_canonical_once(path: Path, document: Mapping[str, object]) -> None:
    """Create a canonical receipt without permitting replacement or truncation."""

    destination = path.resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("xb") as handle:
        handle.write(canonical_json_bytes(document))
        handle.flush()
        os.fsync(handle.fileno())


def load_canonical_receipt(path: Path) -> dict[str, Any]:
    """Load a generic canonical JSON receipt for verification CLIs/tests."""

    raw = path.resolve().read_bytes()
    document = _load_json_object(raw, field=path.name)
    if canonical_json_bytes(document) != raw:
        raise EvaluationError(f"{path.name} is not canonical JSON")
    return document


def is_stage11_receipt(value: object) -> TypeGuard[Mapping[str, Any]]:
    """Narrow a JSON value to the object shape accepted by the validator."""

    return isinstance(value, Mapping) and value.get("schema") == STAGE11_GATE_SCHEMA


__all__ = [
    "COMPETITION_CONFIG_PATH",
    "DEPENDENCY_LOCK_PATH",
    "OPAQUE_HOLDOUT_COUNT",
    "STAGE11_GATE_SCHEMA",
    "STAGE11_WORKFLOW_PATH",
    "STAGE12_MILESTONE_ID",
    "STAGE12_NONCONSUMPTION_SCHEMA",
    "HoldoutDecision",
    "HoldoutEvaluationDeclaration",
    "SourceIdentity",
    "ValidatedHoldoutGate",
    "create_holdout_gate_receipt",
    "create_nonconsumption_receipt",
    "is_stage11_receipt",
    "load_bound_holdout_gate",
    "load_canonical_receipt",
    "revalidate_earned_holdout_gate",
    "source_identity",
    "validate_holdout_gate_receipt",
    "validate_nonconsumption_receipt",
    "write_canonical_once",
]
