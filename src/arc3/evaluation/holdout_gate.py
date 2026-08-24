"""Typed, hash-bound Build 001 Stage 11/12 holdout gate receipts.

This module is deliberately environment-free.  It hashes the sealed public
manifest as opaque bytes and never imports an ARC environment adapter, parses
game identities, or opens gameplay.  Public evaluation must separately
revalidate an earned receipt before it may parse the manifest.
"""

from __future__ import annotations

import importlib
import json
import os
import subprocess
import sys
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
from arc3.evaluation.integrity_authority import (
    COMPOSITE_INTEGRITY_HASH_FIELD,
    COMPOSITE_INTEGRITY_SCHEMA,
    validate_composite_integrity_authority,
)
from arc3.evaluation.stage10_regression import (
    PREDECLARATION_SHA256 as STAGE10_PREDECLARATION_SHA256,
)
from arc3.evaluation.stage10_regression import (
    STAGE10_RESULT_SCHEMA,
    Stage10Status,
    SuiteDisposition,
)
from arc3.integrity import discover_policy_files
from arc3.types import JSONValue

STAGE11_GATE_SCHEMA = "arc3.build-001.stage-11-holdout-gate.v0.3"
STAGE11_LEGACY_GATE_SCHEMA = "arc3.build-001.stage-11-holdout-gate.v0.2"
STAGE12_NONCONSUMPTION_SCHEMA = "arc3.build-001.stage-12-nonconsumption.v0.1"
STAGE11_WORKFLOW_PATH = "docs/workflows/001-local-public-failure-recovery.md"
COMPETITION_CONFIG_PATH = "src/arc3/competition-runtime.v0.1.json"
DEPENDENCY_LOCK_PATH = "uv.lock"
OPAQUE_HOLDOUT_COUNT = 10
STAGE12_MILESTONE_ID = "build-001-stage12-v0.1"
STAGE09_TERMINAL_VERIFICATION_SCHEMA = "arc3.build-001.stage-09-terminal-verification.v0.2"
_ABSENT_INTEGRITY_REASON = "AUTHENTICATED_STAGE10_FAILED_INFRASTRUCTURE_NO_COMPOSITE"
_STAGE11_GATE_SCHEMAS = frozenset({STAGE11_GATE_SCHEMA, STAGE11_LEGACY_GATE_SCHEMA})

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
_STAGE09_TERMINAL_VERIFICATION_FIELDS = {
    "attempt_root",
    "competition_integrity",
    "evidence_integrity",
    "execution_complete",
    "exposure",
    "gate",
    "output",
    "passed",
    "prior_authority",
    "schema",
    "source_end",
    "source_root",
    "source_stable",
    "status",
    "terminal_finalization",
    "verification_hash",
    "work_authority",
}


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
    schema: str | frozenset[str],
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
    accepted_schemas = frozenset({schema}) if isinstance(schema, str) else schema
    if document.get("schema") not in accepted_schemas:
        raise EvaluationError(f"{field} artifact schema changed")
    if not verify_object_hash(document, hash_field=hash_field):
        raise EvaluationError(f"{field} artifact self-hash is invalid")
    if document.get(hash_field) != expected_core_hash:
        raise EvaluationError(f"{field} artifact core hash changed")
    return document


def _git(root: Path, *arguments: str) -> str:
    environment = {
        key: value for key, value in os.environ.items() if not key.upper().startswith("GIT_")
    }
    environment["GIT_NO_REPLACE_OBJECTS"] = "1"
    try:
        completed = subprocess.run(
            ("git", *arguments),
            cwd=root,
            env=environment,
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
    if Path(_git(repository, "rev-parse", "--show-toplevel")).resolve() != repository:
        raise EvaluationError("source Git root differs from the requested repository")
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
        and not isinstance(holdout.get("identities_loaded"), bool)
        and holdout.get("identities_loaded") == 0
        and holdout.get("manifest_loaded_as_metadata") is False
        and not isinstance(holdout.get("public_holdout_gameplay_events"), bool)
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


def _stage10_integrity_clear(
    document: Mapping[str, object],
    *,
    expected_composite: Mapping[str, object],
) -> bool:
    validations = document.get("suite_validations")
    if not isinstance(validations, list):
        return False
    matches = [
        value
        for value in validations
        if isinstance(value, Mapping) and value.get("suite_id") == "competition-integrity"
    ]
    if len(matches) != 1:
        return False
    measurements = matches[0].get("measurements")
    return bool(
        matches[0].get("disposition") == SuiteDisposition.PASS.value
        and matches[0].get("artifact_valid") is True
        and matches[0].get("errors") == []
        and isinstance(measurements, Mapping)
        and measurements.get("composite_integrity_schema") == expected_composite.get("schema")
        and measurements.get("composite_integrity_file_sha256")
        == expected_composite.get("file_sha256")
        and measurements.get("composite_integrity_core_hash")
        == expected_composite.get("artifact_core_hash")
    )


def _stage10_graph_clear(
    *,
    source_root: Path,
    attempt_root: Path,
    output: Path,
    frozen_commit: str,
) -> bool:
    """Reconstruct the persisted Stage 10 graph without launching a suite."""

    try:
        from scripts.measure_stage10_regression import verify_terminal_evidence

        if (
            Path(verify_terminal_evidence.__code__.co_filename).resolve()
            != source_root.resolve() / "scripts/measure_stage10_regression.py"
        ):
            return False
        return verify_terminal_evidence(
            source_root=source_root.resolve(),
            attempt_root=attempt_root.resolve(),
            output=output.resolve(),
            frozen_commit=frozen_commit,
        )
    except (
        ImportError,
        KeyError,
        OSError,
        RuntimeError,
        TypeError,
        ValueError,
        EvaluationError,
        subprocess.SubprocessError,
    ):
        return False


def _stage10_terminal_status(
    *,
    verifier_source_root: Path,
    execution_source_root: Path,
    attempt_root: Path,
    output: Path,
    frozen_commit: str,
) -> Stage10Status | None:
    """Authenticate a terminal Stage 10 status without launching any child.

    The verifier is loaded from the current frozen Stage 11 source, while the
    graph is reconstructed against the exact historical source that executed
    the sole Stage 10 attempt.  Returning ``None`` is deliberately distinct
    from a terminal failure status and carries no gate authority.
    """

    try:
        module = importlib.import_module("scripts.measure_stage10_regression")
        verifier = module.reconstruct_terminal_status
        code = getattr(verifier, "__code__", None)
        if (
            code is None
            or Path(code.co_filename).resolve()
            != verifier_source_root.resolve() / "scripts/measure_stage10_regression.py"
        ):
            return None
        value: object = verifier(
            verifier_source_root=verifier_source_root.resolve(),
            execution_source_root=execution_source_root.resolve(),
            attempt_root=attempt_root.resolve(),
            output=output.resolve(),
            frozen_commit=frozen_commit,
        )
    except (
        AttributeError,
        ImportError,
        KeyError,
        OSError,
        RuntimeError,
        TypeError,
        ValueError,
        EvaluationError,
        subprocess.SubprocessError,
    ):
        return None
    if isinstance(value, Stage10Status):
        return value
    return None


def _valid_stage09_terminal_verification(value: object) -> bool:
    return bool(
        isinstance(value, Mapping)
        and set(value) == _STAGE09_TERMINAL_VERIFICATION_FIELDS
        and value.get("schema") == STAGE09_TERMINAL_VERIFICATION_SCHEMA
        and value.get("passed") is True
        and value.get("status") in {"PASS", "FAILED_MECHANISM"}
        and value.get("execution_complete") is True
        and value.get("evidence_integrity") is True
        and value.get("competition_integrity") is True
        and value.get("source_stable") is True
        and verify_object_hash(dict(value), hash_field="verification_hash")
    )


def _stage09_graph_verification(
    *,
    source_root: Path,
    attempt_root: Path,
    output: Path,
    exposure: Path,
    expected_output_sha256: str,
    expected_artifact_core_hash: str,
    expected_terminal_finalization_sha256: str,
    expected_terminal_finalization_hash: str,
) -> dict[str, object] | None:
    """Reconstruct the complete Stage 09 graph without opening an environment."""

    try:
        module = importlib.import_module("scripts.measure_development_recovery")
        verifier = module.verify_complete_terminal
        code = getattr(verifier, "__code__", None)
        if (
            code is None
            or Path(code.co_filename).resolve()
            != source_root.resolve() / "scripts/measure_development_recovery.py"
        ):
            return None
        value: object = verifier(
            source_root=source_root.resolve(),
            attempt_root=attempt_root.resolve(),
            output=output.resolve(),
            exposure=exposure.resolve(),
            expected_output_sha256=expected_output_sha256,
            expected_artifact_core_hash=expected_artifact_core_hash,
            expected_terminal_finalization_sha256=expected_terminal_finalization_sha256,
            expected_terminal_finalization_hash=expected_terminal_finalization_hash,
        )
    except (
        AttributeError,
        ImportError,
        OSError,
        RuntimeError,
        TypeError,
        ValueError,
        EvaluationError,
        subprocess.SubprocessError,
    ):
        return None
    if not _valid_stage09_terminal_verification(value):
        return None
    return dict(cast(Mapping[str, object], value))


def _require_runtime_import_origin(source_root: Path) -> None:
    """Reject any mixed-tree first-party validation closure.

    Stage 11 is an authority boundary, so checking only this module is not
    sufficient: an already-loaded scanner or canonical-artifact helper from a
    different checkout could otherwise validate bytes in the declared source
    tree.  Every loaded ``arc3`` module must map to its canonical module or
    package path beneath the explicit execution root.  Critical imported
    callables are checked as well so a rebound helper cannot escape the module
    inventory check.
    """

    root = source_root.resolve()
    source = (root / "src").resolve()
    observed_modules: dict[str, Path] = {}
    for name, module in sorted(sys.modules.items()):
        if name != "arc3" and not name.startswith("arc3."):
            continue
        origin_value = getattr(module, "__file__", None)
        if not isinstance(origin_value, str):
            raise EvaluationError(f"Stage 11 first-party module has no file origin: {name}")
        origin = Path(origin_value).resolve()
        components = name.split(".")
        module_path = source.joinpath(*components).with_suffix(".py").resolve()
        package_path = source.joinpath(*components, "__init__.py").resolve()
        if origin not in {module_path, package_path} or not origin.is_file():
            raise EvaluationError(
                f"Stage 11 first-party module origin is outside the execution source: {name}"
            )
        observed_modules[name] = origin

    required_modules = {
        "arc3": source / "arc3/__init__.py",
        "arc3.competition_runtime": source / "arc3/competition_runtime.py",
        "arc3.errors": source / "arc3/errors.py",
        "arc3.evaluation": source / "arc3/evaluation/__init__.py",
        "arc3.evaluation.artifacts": source / "arc3/evaluation/artifacts.py",
        "arc3.evaluation.development_recovery": (
            source / "arc3/evaluation/development_recovery.py"
        ),
        "arc3.evaluation.holdout_gate": source / "arc3/evaluation/holdout_gate.py",
        "arc3.evaluation.integrity_authority": (source / "arc3/evaluation/integrity_authority.py"),
        "arc3.evaluation.stage10_regression": (source / "arc3/evaluation/stage10_regression.py"),
        "arc3.integrity": source / "arc3/integrity/__init__.py",
        "arc3.integrity.models": source / "arc3/integrity/models.py",
        "arc3.integrity.scanner": source / "arc3/integrity/scanner.py",
        "arc3.types": source / "arc3/types.py",
    }
    if any(
        observed_modules.get(name) != expected.resolve()
        for name, expected in required_modules.items()
    ):
        raise EvaluationError("Stage 11 runtime import closure is not the execution source root")

    callable_origins = {
        canonical_json_bytes: source / "arc3/evaluation/artifacts.py",
        seal_object: source / "arc3/evaluation/artifacts.py",
        sha256_bytes: source / "arc3/evaluation/artifacts.py",
        sha256_file: source / "arc3/evaluation/artifacts.py",
        verify_object_hash: source / "arc3/evaluation/artifacts.py",
        discover_policy_files: source / "arc3/integrity/scanner.py",
        validate_composite_integrity_authority: (source / "arc3/evaluation/integrity_authority.py"),
    }
    if any(
        Path(function.__code__.co_filename).resolve() != expected.resolve()
        for function, expected in callable_origins.items()
    ):
        raise EvaluationError("Stage 11 authority callable origin is not the execution source root")


def _stage10_ledger_binding(
    document: Mapping[str, object], *, attempt_root: Path
) -> dict[str, object]:
    ledger = _mapping(document.get("invocation_ledger"), field="Stage 10 invocation ledger")
    _exact_keys(
        ledger,
        {"byte_length", "path", "sha256"},
        field="Stage 10 invocation ledger",
    )
    byte_length = ledger.get("byte_length")
    ledger_path = _string(ledger.get("path"), field="Stage 10 invocation ledger path")
    ledger_sha256 = _string(ledger.get("sha256"), field="Stage 10 invocation ledger hash")
    _validate_sha256(ledger_sha256, field="Stage 10 invocation ledger hash")
    if (
        isinstance(byte_length, bool)
        or not isinstance(byte_length, int)
        or byte_length <= 0
        or Path(ledger_path).resolve() != (attempt_root.resolve() / "invocations.jsonl").resolve()
    ):
        raise EvaluationError("Stage 10 invocation ledger binding is invalid")
    return dict(ledger)


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
    stage09_attempt_root: Path,
    stage09_exposure_path: Path,
    stage09_file_sha256: str,
    stage09_core_hash: str,
    stage09_terminal_finalization_sha256: str,
    stage09_terminal_finalization_hash: str,
    stage10_path: Path,
    stage10_attempt_root: Path,
    stage10_file_sha256: str,
    stage10_core_hash: str,
    integrity_path: Path,
    integrity_file_sha256: str | None,
    integrity_core_hash: str | None,
    development_source_root: Path,
    execution_source_root: Path,
    expected_execution_commit: str,
    expected_manifest_sha256: str,
    evaluation: HoldoutEvaluationDeclaration,
    generated_at: str | None = None,
    stage10_source_root: Path | None = None,
    stage10_frozen_commit: str | None = None,
) -> dict[str, Any]:
    """Evaluate the five frozen criteria without touching the sealed manifest.

    Stage 11 binds the opaque manifest identity already carried by the sealed
    Stage 09 authority.  The manifest itself is first opened only on an earned
    Stage 12 execution path, immediately before public-manifest parsing.
    """

    _validate_git_hash(expected_execution_commit, field="expected execution commit")
    _validate_sha256(expected_manifest_sha256, field="sealed manifest hash")
    _validate_sha256(
        stage09_terminal_finalization_sha256,
        field="Stage 09 terminal finalization file hash",
    )
    _validate_sha256(
        stage09_terminal_finalization_hash,
        field="Stage 09 terminal finalization core hash",
    )
    _require_runtime_import_origin(execution_source_root)
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
    stage10_ledger = _stage10_ledger_binding(stage10, attempt_root=stage10_attempt_root)
    development_source = source_identity(development_source_root)
    execution_source = source_identity(execution_source_root)
    if execution_source.commit != expected_execution_commit or not execution_source.clean_worktree:
        raise EvaluationError("Stage 11 execution source is not the exact clean frozen commit")
    historical_stage10_root = (stage10_source_root or execution_source_root).resolve()
    historical_stage10_commit = stage10_frozen_commit or expected_execution_commit
    _validate_git_hash(historical_stage10_commit, field="Stage 10 frozen commit")
    historical_stage10_source = source_identity(historical_stage10_root)
    if (
        historical_stage10_source.commit != historical_stage10_commit
        or not historical_stage10_source.clean_worktree
    ):
        raise EvaluationError("Stage 10 source is not the exact clean historical commit")
    try:
        workflow_sha256 = sha256_file(execution_source_root.resolve() / STAGE11_WORKFLOW_PATH)
    except OSError as error:
        raise EvaluationError("Stage 11 authority input is unreadable") from error
    integrity_hashes_present = integrity_file_sha256 is not None and integrity_core_hash is not None
    if (integrity_file_sha256 is None) != (integrity_core_hash is None):
        raise EvaluationError("composite integrity hashes must be supplied together")
    terminal_status: Stage10Status | None = None
    if integrity_hashes_present:
        if (
            historical_stage10_root != execution_source_root.resolve()
            or historical_stage10_commit != expected_execution_commit
        ):
            raise EvaluationError(
                "separate historical Stage 10 source is denial-only without a composite"
            )
        composite = validate_composite_integrity_authority(
            integrity_path,
            expected_file_sha256=cast(str, integrity_file_sha256),
            expected_core_hash=cast(str, integrity_core_hash),
            source_root=execution_source_root,
        )
        integrity_clear = bool(
            composite.get("status") == "PASS"
            and composite.get("claim") == "BOUNDED_STATIC_COMPETITION_INTEGRITY_WITH_OPAQUE_HOLDOUT"
            and composite.get("full_public_integrity_status")
            == "NOT_EVALUATED_BUILD_001_PUBLIC_IDENTIFIERS"
            and composite.get("assurance_limitation")
            == (
                "Package and development scans are static; dynamic-import and native-extension "
                "containment are not proven; Build 001 public identifiers were not fully evaluated."
            )
            and composite.get("semantic_public_manifest_access") is False
            and composite.get("opaque_public_manifest_sha256") == expected_manifest_sha256
        )
        composite_binding: dict[str, object] = {
            "artifact_core_hash": cast(str, integrity_core_hash),
            "file_sha256": cast(str, integrity_file_sha256),
            "schema": COMPOSITE_INTEGRITY_SCHEMA,
        }
        integrity_binding: dict[str, object] = {
            **composite_binding,
            "path": integrity_path.resolve().as_posix(),
        }
    else:
        if integrity_path.resolve().exists():
            raise EvaluationError("composite integrity artifact exists but has no hash authority")
        terminal_status = _stage10_terminal_status(
            verifier_source_root=execution_source_root,
            execution_source_root=historical_stage10_root,
            attempt_root=stage10_attempt_root,
            output=stage10_path,
            frozen_commit=historical_stage10_commit,
        )
        if (
            terminal_status is not Stage10Status.FAILED_INFRASTRUCTURE
            or stage10.get("status") != Stage10Status.FAILED_INFRASTRUCTURE.value
        ):
            raise EvaluationError(
                "absent composite requires authenticated Stage 10 FAILED_INFRASTRUCTURE"
            )
        integrity_clear = False
        composite_binding = {}
        integrity_binding = {
            "availability": "ABSENT",
            "expected_schema": COMPOSITE_INTEGRITY_SCHEMA,
            "path": integrity_path.resolve().as_posix(),
            "reason": _ABSENT_INTEGRITY_REASON,
            "terminal_authority": {
                "execution_commit": historical_stage10_source.commit,
                "execution_source_root": historical_stage10_root.as_posix(),
                "execution_tree": historical_stage10_source.tree,
                "status": terminal_status.value,
                "verified": True,
                "verifier_commit": execution_source.commit,
                "verifier_source_root": execution_source_root.resolve().as_posix(),
                "verifier_tree": execution_source.tree,
            },
        }
    source_unchanged = bool(
        _source_matches_stage09(development_source, stage09)
        and _policy_unchanged(development_source, execution_source)
    )
    stage09_verification = _stage09_graph_verification(
        source_root=execution_source_root,
        attempt_root=stage09_attempt_root,
        output=stage09_path,
        exposure=stage09_exposure_path,
        expected_output_sha256=stage09_file_sha256,
        expected_artifact_core_hash=stage09_core_hash,
        expected_terminal_finalization_sha256=stage09_terminal_finalization_sha256,
        expected_terminal_finalization_hash=stage09_terminal_finalization_hash,
    )
    if terminal_status is not None:
        stage10_graph_clear = terminal_status is Stage10Status.PASS
    elif historical_stage10_root == execution_source_root.resolve() and (
        historical_stage10_commit == expected_execution_commit
    ):
        stage10_graph_clear = _stage10_graph_clear(
            source_root=execution_source_root,
            attempt_root=stage10_attempt_root,
            output=stage10_path,
            frozen_commit=expected_execution_commit,
        )
    else:
        terminal_status = _stage10_terminal_status(
            verifier_source_root=execution_source_root,
            execution_source_root=historical_stage10_root,
            attempt_root=stage10_attempt_root,
            output=stage10_path,
            frozen_commit=historical_stage10_commit,
        )
        stage10_graph_clear = terminal_status is Stage10Status.PASS
    # The graph verifiers can import additional first-party validation modules.
    # Bind that expanded closure before it contributes to the gate decision.
    _require_runtime_import_origin(execution_source_root)
    criteria = {
        "stage09_pass": bool(
            stage09_verification is not None
            and stage09_verification.get("status") == "PASS"
            and _stage09_pass(stage09)
        ),
        "stage10_pass": bool(
            stage10_graph_clear
            and _stage10_pass(stage10, expected_source=historical_stage10_source)
        ),
        "competition_integrity_clear": bool(
            integrity_clear
            and _stage09_integrity_clear(stage09)
            and bool(composite_binding)
            and _stage10_integrity_clear(
                stage10,
                expected_composite=composite_binding,
            )
        ),
        "production_source_unchanged": source_unchanged,
        "sealed_holdout_identity_matches": bool(
            _stage09_holdout_sealed(stage09)
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
            "manifest_sha256": expected_manifest_sha256,
            "opaque_partition_count": OPAQUE_HOLDOUT_COUNT,
        },
        "holdout_evaluation": evaluation.to_dict(),
        "integrity_authority": integrity_binding,
        "production_source": {
            "development": development_source.to_dict(),
            "development_root": development_source_root.resolve().as_posix(),
            "execution": execution_source.to_dict(),
            "execution_root": execution_source_root.resolve().as_posix(),
        },
        "production_config": {
            "configuration_sha256": execution_source.competition_config_sha256,
            "file_sha256": execution_source.competition_config_file_sha256,
            "path": COMPETITION_CONFIG_PATH,
        },
        "schema": STAGE11_GATE_SCHEMA,
        "stage09": {
            "artifact_core_hash": stage09_core_hash,
            "attempt_root": stage09_attempt_root.resolve().as_posix(),
            "exposure_path": stage09_exposure_path.resolve().as_posix(),
            "file_sha256": stage09_file_sha256,
            "path": stage09_path.resolve().as_posix(),
            "schema": STAGE09_SCHEMA,
            "status": stage09_status,
            "terminal_finalization_hash": stage09_terminal_finalization_hash,
            "terminal_finalization_sha256": stage09_terminal_finalization_sha256,
            "terminal_verification": stage09_verification,
        },
        "stage10": {
            "artifact_core_hash": stage10_core_hash,
            "attempt_root": stage10_attempt_root.resolve().as_posix(),
            "file_sha256": stage10_file_sha256,
            "invocation_ledger": stage10_ledger,
            "path": stage10_path.resolve().as_posix(),
            "plan_hash": _string(stage10.get("plan_hash"), field="Stage 10 plan hash"),
            "predeclaration_sha256": _string(
                stage10.get("predeclaration_sha256"),
                field="Stage 10 predeclaration hash",
            ),
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
    receipt_schema = document.get("schema")
    if (
        receipt_schema not in _STAGE11_GATE_SCHEMAS
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
    _exact_keys(
        source,
        {"development", "development_root", "execution", "execution_root"},
        field="production_source",
    )
    _string(source.get("development_root"), field="development source root")
    _string(source.get("execution_root"), field="execution source root")
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
        expected_binding_fields = {"artifact_core_hash", "file_sha256", "schema", "status"}
        if name == "stage09":
            expected_binding_fields.update(
                {
                    "attempt_root",
                    "exposure_path",
                    "path",
                    "terminal_finalization_hash",
                    "terminal_finalization_sha256",
                    "terminal_verification",
                }
            )
        else:
            expected_binding_fields.update(
                {
                    "attempt_root",
                    "invocation_ledger",
                    "path",
                    "plan_hash",
                    "predeclaration_sha256",
                }
            )
        _exact_keys(
            binding,
            expected_binding_fields,
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
        _string(binding.get("path"), field=f"{name}.path")
        if name == "stage09":
            _string(binding.get("attempt_root"), field="stage09.attempt_root")
            _string(binding.get("exposure_path"), field="stage09.exposure_path")
            for hash_name in (
                "terminal_finalization_hash",
                "terminal_finalization_sha256",
            ):
                _validate_sha256(
                    _string(binding.get(hash_name), field=f"stage09.{hash_name}"),
                    field=f"stage09.{hash_name}",
                )
            verification = binding.get("terminal_verification")
            if verification is not None and not _valid_stage09_terminal_verification(verification):
                raise EvaluationError("stage09 terminal verification binding is invalid")
            if criteria["stage09_pass"] and verification is None:
                raise EvaluationError("stage09 criterion disagrees with terminal verification")
        else:
            attempt_root = Path(_string(binding.get("attempt_root"), field="stage10.attempt_root"))
            _stage10_ledger_binding(
                {"invocation_ledger": binding.get("invocation_ledger")},
                attempt_root=attempt_root,
            )
            plan_hash = _string(binding.get("plan_hash"), field="stage10.plan_hash")
            _validate_sha256(plan_hash, field="stage10.plan_hash")
            if binding.get("predeclaration_sha256") != STAGE10_PREDECLARATION_SHA256:
                raise EvaluationError("stage10 predeclaration binding changed")
    integrity = _mapping(document.get("integrity_authority"), field="integrity_authority")
    present_integrity_fields = {"artifact_core_hash", "file_sha256", "path", "schema"}
    absent_integrity_fields = {
        "availability",
        "expected_schema",
        "path",
        "reason",
        "terminal_authority",
    }
    if set(integrity) == present_integrity_fields:
        if integrity.get("schema") != COMPOSITE_INTEGRITY_SCHEMA:
            raise EvaluationError("integrity authority schema changed")
        _string(integrity.get("path"), field="integrity authority path")
        for hash_name in ("artifact_core_hash", "file_sha256"):
            _validate_sha256(
                _string(integrity.get(hash_name), field=f"integrity_authority.{hash_name}"),
                field=f"integrity_authority.{hash_name}",
            )
    elif set(integrity) == absent_integrity_fields:
        if receipt_schema != STAGE11_GATE_SCHEMA:
            raise EvaluationError("legacy Stage 11 receipt cannot claim absent integrity authority")
        if (
            integrity.get("availability") != "ABSENT"
            or integrity.get("expected_schema") != COMPOSITE_INTEGRITY_SCHEMA
            or integrity.get("reason") != _ABSENT_INTEGRITY_REASON
        ):
            raise EvaluationError("absent integrity authority declaration changed")
        _string(integrity.get("path"), field="integrity authority path")
        terminal = _mapping(
            integrity.get("terminal_authority"),
            field="integrity_authority.terminal_authority",
        )
        _exact_keys(
            terminal,
            {
                "execution_commit",
                "execution_source_root",
                "execution_tree",
                "status",
                "verified",
                "verifier_commit",
                "verifier_source_root",
                "verifier_tree",
            },
            field="integrity_authority.terminal_authority",
        )
        for name in ("execution_commit", "execution_tree", "verifier_commit", "verifier_tree"):
            _validate_git_hash(
                _string(terminal.get(name), field=f"terminal_authority.{name}"),
                field=f"terminal_authority.{name}",
            )
        _string(terminal.get("execution_source_root"), field="terminal execution source root")
        _string(terminal.get("verifier_source_root"), field="terminal verifier source root")
        stage10_binding = _mapping(document.get("stage10"), field="stage10")
        if (
            terminal.get("status") != Stage10Status.FAILED_INFRASTRUCTURE.value
            or terminal.get("verified") is not True
            or stage10_binding.get("status") != Stage10Status.FAILED_INFRASTRUCTURE.value
            or criteria["stage10_pass"]
            or criteria["competition_integrity_clear"]
            or expected_decision is not HoldoutDecision.NOT_EARNED
            or terminal.get("verifier_commit") != execution.commit
            or terminal.get("verifier_tree") != execution.tree
            or terminal.get("verifier_source_root") != source.get("execution_root")
        ):
            raise EvaluationError("absent composite cannot authorize a holdout-opening decision")
    else:
        raise EvaluationError("integrity_authority fields do not match a supported schema")
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
        schema=_STAGE11_GATE_SCHEMAS,
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
    _require_runtime_import_origin(source_root)
    stage09_binding = _mapping(gate.receipt["stage09"], field="stage09")
    stage10_binding = _mapping(gate.receipt["stage10"], field="stage10")
    integrity_binding = _mapping(gate.receipt["integrity_authority"], field="integrity")
    production_source = _mapping(gate.receipt["production_source"], field="production_source")
    if (
        source_root.resolve().as_posix() != production_source.get("execution_root")
        or stage09_path.resolve().as_posix() != stage09_binding.get("path")
        or stage10_path.resolve().as_posix() != stage10_binding.get("path")
        or integrity_path.resolve().as_posix() != integrity_binding.get("path")
    ):
        raise EvaluationError("Stage 11 execution/evidence paths changed")
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
    stage10_attempt_root = Path(
        _string(stage10_binding.get("attempt_root"), field="Stage 10 attempt root")
    )
    stage09_verification = _stage09_graph_verification(
        source_root=source_root,
        attempt_root=Path(
            _string(stage09_binding.get("attempt_root"), field="Stage 09 attempt root")
        ),
        output=stage09_path,
        exposure=Path(
            _string(stage09_binding.get("exposure_path"), field="Stage 09 exposure path")
        ),
        expected_output_sha256=cast(str, stage09_binding["file_sha256"]),
        expected_artifact_core_hash=cast(str, stage09_binding["artifact_core_hash"]),
        expected_terminal_finalization_sha256=_string(
            stage09_binding.get("terminal_finalization_sha256"),
            field="Stage 09 terminal finalization file hash",
        ),
        expected_terminal_finalization_hash=_string(
            stage09_binding.get("terminal_finalization_hash"),
            field="Stage 09 terminal finalization core hash",
        ),
    )
    if stage09_verification != stage09_binding.get("terminal_verification"):
        raise EvaluationError("Stage 09 complete terminal graph no longer revalidates")
    if (
        stage10.get("invocation_ledger") != stage10_binding.get("invocation_ledger")
        or stage10.get("plan_hash") != stage10_binding.get("plan_hash")
        or stage10.get("predeclaration_sha256") != stage10_binding.get("predeclaration_sha256")
    ):
        raise EvaluationError("Stage 10 projected evidence changed after the Stage 11 receipt")
    current_source = source_identity(source_root)
    if current_source != gate.execution_source or not current_source.clean_worktree:
        raise EvaluationError("production source changed after the Stage 11 receipt")
    workflow = _mapping(gate.receipt["workflow_rule"], field="workflow_rule")
    if sha256_file(source_root.resolve() / STAGE11_WORKFLOW_PATH) != workflow["workflow_sha256"]:
        raise EvaluationError("Stage 11 controlling workflow changed")
    composite = validate_composite_integrity_authority(
        integrity_path,
        expected_file_sha256=cast(str, integrity_binding["file_sha256"]),
        expected_core_hash=cast(str, integrity_binding[COMPOSITE_INTEGRITY_HASH_FIELD]),
        source_root=source_root,
    )
    integrity_clear = bool(
        composite.get("status") == "PASS"
        and composite.get("claim") == "BOUNDED_STATIC_COMPETITION_INTEGRITY_WITH_OPAQUE_HOLDOUT"
        and composite.get("full_public_integrity_status")
        == "NOT_EVALUATED_BUILD_001_PUBLIC_IDENTIFIERS"
        and composite.get("assurance_limitation")
        == (
            "Package and development scans are static; dynamic-import and native-extension "
            "containment are not proven; Build 001 public identifiers were not fully evaluated."
        )
        and composite.get("semantic_public_manifest_access") is False
        and composite.get("opaque_public_manifest_sha256") == gate.manifest_sha256
    )
    stage10_graph_clear = _stage10_graph_clear(
        source_root=source_root,
        attempt_root=stage10_attempt_root,
        output=stage10_path,
        frozen_commit=current_source.commit,
    )
    recomputed = {
        "stage09_pass": bool(stage09_verification is not None and _stage09_pass(stage09)),
        "stage10_pass": bool(
            stage10_graph_clear and _stage10_pass(stage10, expected_source=current_source)
        ),
        "competition_integrity_clear": bool(
            integrity_clear
            and _stage09_integrity_clear(stage09)
            and _stage10_integrity_clear(
                stage10,
                expected_composite=integrity_binding,
            )
        ),
        "production_source_unchanged": bool(
            _source_matches_stage09(gate.development_source, stage09)
            and _policy_unchanged(gate.development_source, current_source)
        ),
        "sealed_holdout_identity_matches": bool(
            _stage09_holdout_sealed(stage09)
            and _stage09_manifest_bound(stage09, gate.manifest_sha256)
            and gate.opaque_count == OPAQUE_HOLDOUT_COUNT
        ),
    }
    if recomputed != dict(gate.criteria) or not all(recomputed.values()):
        raise EvaluationError("Stage 11 criteria no longer revalidate from bound evidence")
    # Recheck after both terminal verifiers and composite reconstruction.  No
    # mixed-tree helper loaded by those operations may reach manifest bytes.
    _require_runtime_import_origin(source_root)
    # The manifest stays opaque until every non-manifest authority has passed.
    if sha256_file(manifest_path.resolve()) != gate.manifest_sha256:
        raise EvaluationError("sealed holdout manifest bytes changed")
    return gate


def create_nonconsumption_receipt(
    *,
    gate_path: Path,
    gate_file_sha256: str,
    gate_core_hash: str,
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
) -> None:
    """Validate Stage 12 solely from its exact Stage 11 opaque authority."""

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

    return isinstance(value, Mapping) and value.get("schema") in _STAGE11_GATE_SCHEMAS


__all__ = [
    "COMPETITION_CONFIG_PATH",
    "DEPENDENCY_LOCK_PATH",
    "OPAQUE_HOLDOUT_COUNT",
    "STAGE11_GATE_SCHEMA",
    "STAGE11_LEGACY_GATE_SCHEMA",
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
