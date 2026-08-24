"""Fail-closed Build 002 one-shot local-public competition evidence.

This module is deliberately separate from Build 001's holdout gate.  Build 001
remains immutable, ``PARTIAL``, and ``SEALED_UNCONSUMED``.  The owner supplied a
new Build 002 authority for exactly one run, conditional on a complete frozen
preflight.  The first attempted environment ``make`` consumes that authority,
even if the upstream call subsequently fails.

Static asset inventory hashes and manifest metadata do not open an environment.
No function in this module imports the ARC toolkit or calls ``make`` itself.
"""

from __future__ import annotations

import json
import math
import os
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from arc3.errors import EvaluationError
from arc3.evaluation.artifacts import (
    canonical_json_bytes,
    seal_object,
    sha256_file,
    verify_object_hash,
)
from arc3.evaluation.holdout_authority import PUBLIC_PARTITION_MANIFEST_SHA256
from arc3.evaluation.public import PublicPartitionManifest
from arc3.types import JSONValue

ASSET_INVENTORY_SCHEMA = "arc3.build-002.static-holdout-assets.v0.1"
PREFLIGHT_SCHEMA = "arc3.build-002.one-shot-preflight.v0.1"
CONSUMPTION_SCHEMA = "arc3.build-002.holdout-consumption.v0.1"
EXPOSURE_EVENT_SCHEMA = "arc3.build-002.holdout-exposure-event.v0.1"
RESULT_SCHEMA = "arc3.build-002.local-public-result.v0.1"
FAILED_ATTEMPT_SCHEMA = "arc3.build-002.consumed-failed-attempt.v0.1"
SOURCE_PREVIEW_SCHEMA = "arc3.build-002.public-source-preview-contamination.v0.1"
BUILD_002_HOLDOUT_COUNT = 10
BUILD_002_ATTEMPT_ID = "build-002-ten-game-public-once-v0.1"
BUILD_002_RESULT_LABEL = "local-public-source-preview-exposed"
CANONICAL_STATE_RELATIVE = Path("artifacts/build002/holdout-one-shot")

if TYPE_CHECKING:
    from arc3.packaging.runtime_launcher import CompetitionLaunchReceipt

_REQUIRED_GATE_ROLES = frozenset(
    {
        "competition-lifecycle",
        "dependency-and-config-identity",
        "deterministic-startup-and-replay",
        "frozen-source-config-artifacts",
        "notebook-build-and-offline-entry-point",
        "offline-cold-start",
        "official-source-identity",
        "package-and-license-inventory",
        "secret-and-integrity-scan",
        "submission-parquet-structure",
    }
)
_REQUIRED_ARTIFACT_ROLES = frozenset(
    {
        "agent-wrapper",
        "competition-runtime-config",
        "dependency-lock",
        "holdout-asset-inventory",
        "kaggle-notebook",
        "offline-package-candidate",
        "source-preview-contamination-receipt",
        "submission-parquet",
        "third-party-notices",
        "upstream-lock",
    }
)
_REQUIRED_RESULT_ARTIFACT_ROLES = frozenset(
    {
        "competition-launch-receipt",
        "execution-profile",
        "failure-receipts",
        "local-scorecard",
        "submission-parquet",
    }
)
_TERMINAL_RESULT_STATUSES = frozenset(
    {"PASS", "PARTIAL", "FAILED_INFRASTRUCTURE", "FAILED_MECHANISM"}
)


class FailureClassification(StrEnum):
    """The exhaustive primary-failure taxonomy required by Build 002."""

    PERCEPTION = "perception"
    GOAL_INFERENCE = "goal inference"
    RULE_LEARNING = "rule learning"
    PLANNING = "planning"
    EXECUTION = "execution"
    PLATFORM = "platform"
    BUDGET_EXHAUSTION = "budget exhaustion"


@dataclass(frozen=True, slots=True)
class ReceiptBinding:
    """One exact PASS receipt required by the frozen preflight."""

    role: str
    path: Path


@dataclass(frozen=True, slots=True)
class ArtifactBinding:
    """One exact file identity required by the frozen run."""

    role: str
    path: Path


@dataclass(frozen=True, slots=True)
class LevelMeasurement:
    """One scorecard-derived per-level measurement."""

    level_index: int
    completed: bool
    toolkit_score: float
    agent_actions: int | None
    human_baseline_actions: int | None

    def __post_init__(self) -> None:
        if (
            isinstance(self.level_index, bool)
            or not isinstance(self.level_index, int)
            or self.level_index <= 0
        ):
            raise ValueError("level_index must be a positive integer")
        if not isinstance(self.completed, bool):
            raise ValueError("completed must be boolean")
        if (
            isinstance(self.toolkit_score, bool)
            or not isinstance(self.toolkit_score, (int, float))
            or not math.isfinite(float(self.toolkit_score))
            or not 0.0 <= float(self.toolkit_score) <= 1.3225
        ):
            raise ValueError("toolkit_score must be finite and within the public-toolkit range")
        for name, value in {
            "agent_actions": self.agent_actions,
            "human_baseline_actions": self.human_baseline_actions,
        }.items():
            if value is not None and (
                isinstance(value, bool) or not isinstance(value, int) or value < 0
            ):
                raise ValueError(f"{name} must be a non-negative integer or null")
        if self.completed and (
            self.agent_actions is None
            or self.agent_actions <= 0
            or self.human_baseline_actions is None
            or self.human_baseline_actions <= 0
        ):
            raise ValueError("completed levels require positive agent and human action counts")

    def to_dict(self) -> dict[str, JSONValue]:
        documented = _documented_level_score(self)
        return {
            "agent_actions": self.agent_actions,
            "completed": self.completed,
            "documented_formula_score": documented,
            "human_baseline_actions": self.human_baseline_actions,
            "level_index": self.level_index,
            "toolkit_score": float(self.toolkit_score),
        }


@dataclass(frozen=True, slots=True)
class GameMeasurement:
    """One exact environment row in the terminal ten-game result."""

    game_id: str
    completed: bool
    levels_completed: int
    actions: int
    resets: int
    toolkit_score: float
    wall_seconds: float
    peak_memory_bytes: int
    allocated_seconds: float
    reserve_remaining_seconds: float
    stop_reason: str
    primary_failure: FailureClassification | None
    levels: tuple[LevelMeasurement, ...]

    def __post_init__(self) -> None:
        if not self.game_id or self.game_id.strip() != self.game_id:
            raise ValueError("game_id must be a canonical non-empty string")
        if not isinstance(self.completed, bool):
            raise ValueError("completed must be boolean")
        integer_fields = (
            ("levels_completed", self.levels_completed),
            ("actions", self.actions),
            ("resets", self.resets),
            ("peak_memory_bytes", self.peak_memory_bytes),
        )
        for name, value in integer_fields:
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")
        numeric_fields: tuple[tuple[str, int | float], ...] = (
            ("toolkit_score", self.toolkit_score),
            ("wall_seconds", self.wall_seconds),
            ("allocated_seconds", self.allocated_seconds),
            ("reserve_remaining_seconds", self.reserve_remaining_seconds),
        )
        for name, numeric_value in numeric_fields:
            if (
                isinstance(numeric_value, bool)
                or not isinstance(numeric_value, (int, float))
                or not math.isfinite(float(numeric_value))
                or float(numeric_value) < 0.0
            ):
                raise ValueError(f"{name} must be a finite non-negative number")
        if float(self.toolkit_score) > 1.3225:
            raise ValueError("toolkit_score exceeds the pinned public-toolkit cap")
        if not self.stop_reason or self.stop_reason.strip() != self.stop_reason:
            raise ValueError("stop_reason must be a canonical non-empty string")
        if self.completed != (self.primary_failure is None):
            raise ValueError("only incomplete games require one primary failure classification")
        if not self.levels:
            raise ValueError("each game requires at least one level row")
        if tuple(level.level_index for level in self.levels) != tuple(
            range(1, len(self.levels) + 1)
        ):
            raise ValueError("level rows must be contiguous and one-indexed")
        if self.levels_completed != sum(level.completed for level in self.levels):
            raise ValueError("levels_completed disagrees with per-level rows")
        if self.completed and self.levels_completed != len(self.levels):
            raise ValueError("completed game must complete every declared level")

    def documented_formula_score(self) -> float | None:
        scores = [_documented_level_score(level) for level in self.levels]
        if any(score is None for score in scores):
            return None
        weighted = sum(
            level.level_index * cast(float, score)
            for level, score in zip(self.levels, scores, strict=True)
        )
        return weighted / sum(level.level_index for level in self.levels)

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "actions": self.actions,
            "allocated_seconds": float(self.allocated_seconds),
            "completed": self.completed,
            "documented_formula_score": self.documented_formula_score(),
            "game_id": self.game_id,
            "human_baselines_available_for_completed_levels": all(
                not level.completed
                or (level.human_baseline_actions is not None and level.human_baseline_actions > 0)
                for level in self.levels
            ),
            "levels": [level.to_dict() for level in self.levels],
            "levels_completed": self.levels_completed,
            "peak_memory_bytes": self.peak_memory_bytes,
            "primary_failure": (
                self.primary_failure.value if self.primary_failure is not None else None
            ),
            "reserve_remaining_seconds": float(self.reserve_remaining_seconds),
            "resets": self.resets,
            "stop_reason": self.stop_reason,
            "toolkit_score": float(self.toolkit_score),
            "wall_seconds": float(self.wall_seconds),
        }


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _git(root: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if completed.returncode != 0:
        raise EvaluationError(f"git {' '.join(args)} failed during Build 002 freeze")
    return completed.stdout.strip()


def _safe_relative(root: Path, path: Path) -> tuple[Path, str]:
    resolved_root = root.resolve()
    resolved = path.resolve()
    try:
        relative = resolved.relative_to(resolved_root).as_posix()
    except ValueError as error:
        raise EvaluationError("Build 002 evidence path escapes the repository root") from error
    if not relative or any(part in {"", ".", ".."} for part in relative.split("/")):
        raise EvaluationError("Build 002 evidence path is not canonical")
    return resolved, relative


def _canonical_state_root(root: Path, state_root: Path) -> Path:
    expected = (root.resolve() / CANONICAL_STATE_RELATIVE).resolve()
    resolved = state_root.resolve()
    if resolved != expected:
        raise EvaluationError("Build 002 one-shot state root is not canonical")
    return resolved


def _load_object(path: Path) -> dict[str, Any]:
    try:
        value: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise EvaluationError(f"{path.name} is not a readable JSON object") from error
    if not isinstance(value, dict):
        raise EvaluationError(f"{path.name} must contain a JSON object")
    return value


def _write_once(path: Path, payload: dict[str, Any]) -> None:
    encoded = canonical_json_bytes(payload)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError as error:
        raise EvaluationError(
            f"immutable Build 002 artifact already exists: {path.name}"
        ) from error


def _append_fsynced(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("ab") as stream:
        stream.write(canonical_json_bytes(payload))
        stream.flush()
        os.fsync(stream.fileno())


def _exact_holdout_games(manifest_path: Path) -> tuple[str, ...]:
    if sha256_file(manifest_path) != PUBLIC_PARTITION_MANIFEST_SHA256:
        raise EvaluationError("Build 002 public partition bytes changed")
    manifest = PublicPartitionManifest.load(manifest_path)
    games = tuple(sorted(entry.game_id for entry in manifest.games("public-holdout")))
    if len(games) != BUILD_002_HOLDOUT_COUNT or len(set(games)) != BUILD_002_HOLDOUT_COUNT:
        raise EvaluationError("Build 002 holdout is not exactly ten unique games")
    return games


def create_static_asset_inventory(
    manifest_path: Path,
    assets: Mapping[str, Path],
) -> dict[str, Any]:
    """Hash ten exact static assets without importing or opening an environment."""

    games = _exact_holdout_games(manifest_path)
    if set(assets) != set(games):
        raise EvaluationError("static asset inventory differs from the exact ten-game holdout")
    rows: list[dict[str, JSONValue]] = []
    seen_paths: set[Path] = set()
    for game_id in games:
        path = assets[game_id].resolve()
        if not path.is_file():
            raise EvaluationError(f"static holdout asset is unavailable for {game_id}")
        if path in seen_paths:
            raise EvaluationError("two holdout games resolve to the same static asset")
        seen_paths.add(path)
        rows.append(
            {
                "byte_length": path.stat().st_size,
                "game_id": game_id,
                "sha256": sha256_file(path),
            }
        )
    report: dict[str, Any] = {
        "assets": rows,
        "claim_boundary": "static byte identity only; no environment opened or observed",
        "environment_make_interactions": 0,
        "game_count": BUILD_002_HOLDOUT_COUNT,
        "gameplay_observed": False,
        "manifest_sha256": PUBLIC_PARTITION_MANIFEST_SHA256,
        "schema": ASSET_INVENTORY_SCHEMA,
        "status": "PASS",
    }
    return seal_object(report, hash_field="inventory_hash")


def _binding_rows(
    root: Path,
    bindings: Sequence[ReceiptBinding | ArtifactBinding],
    *,
    require_pass: bool,
) -> list[dict[str, JSONValue]]:
    roles = [binding.role for binding in bindings]
    if any(not role or role.strip() != role for role in roles) or len(set(roles)) != len(roles):
        raise EvaluationError("Build 002 binding roles must be unique canonical strings")
    rows: list[dict[str, JSONValue]] = []
    for binding in sorted(bindings, key=lambda item: item.role):
        resolved, relative = _safe_relative(root, binding.path)
        if not resolved.is_file():
            raise EvaluationError(f"required Build 002 file is missing: {binding.role}")
        row: dict[str, JSONValue] = {
            "byte_length": resolved.stat().st_size,
            "path": relative,
            "role": binding.role,
            "sha256": sha256_file(resolved),
        }
        if require_pass:
            value = _load_object(resolved)
            if value.get("status") != "PASS":
                raise EvaluationError(f"required Build 002 gate is not PASS: {binding.role}")
            row["receipt_schema"] = (
                cast(str, value["schema"]) if isinstance(value.get("schema"), str) else None
            )
        rows.append(row)
    return rows


def create_frozen_preflight(
    root: Path,
    *,
    attempt_id: str,
    seed: int,
    manifest_path: Path,
    gates: Sequence[ReceiptBinding],
    artifacts: Sequence[ArtifactBinding],
) -> dict[str, Any]:
    """Create a clean-commit, exact-file preflight for the one authorized run."""

    resolved_root = root.resolve()
    if attempt_id != BUILD_002_ATTEMPT_ID:
        raise EvaluationError("Build 002 one-shot attempt identity changed")
    if isinstance(seed, bool) or not isinstance(seed, int) or not -(2**63) <= seed < 2**63:
        raise EvaluationError("seed must be a signed 64-bit integer")
    status = _git(resolved_root, "status", "--porcelain", "--untracked-files=all")
    if status:
        raise EvaluationError("Build 002 one-shot preflight requires a clean worktree")
    commit = _git(resolved_root, "rev-parse", "HEAD")
    tree = _git(resolved_root, "rev-parse", "HEAD^{tree}")
    if len(commit) != 40 or len(tree) != 40:
        raise EvaluationError("Build 002 git identity is not a full SHA-1")
    games = _exact_holdout_games(manifest_path)
    gate_rows = _binding_rows(resolved_root, gates, require_pass=True)
    artifact_rows = _binding_rows(resolved_root, artifacts, require_pass=False)
    if {cast(str, row["role"]) for row in gate_rows} != _REQUIRED_GATE_ROLES:
        raise EvaluationError("Build 002 preflight gate set is incomplete or expanded")
    if {cast(str, row["role"]) for row in artifact_rows} != _REQUIRED_ARTIFACT_ROLES:
        raise EvaluationError("Build 002 frozen artifact set is incomplete or expanded")
    inventory_row = next(row for row in artifact_rows if row["role"] == "holdout-asset-inventory")
    inventory_path = resolved_root / cast(str, inventory_row["path"])
    inventory = _load_object(inventory_path)
    if (
        inventory.get("schema") != ASSET_INVENTORY_SCHEMA
        or inventory.get("status") != "PASS"
        or inventory.get("manifest_sha256") != PUBLIC_PARTITION_MANIFEST_SHA256
        or inventory.get("game_count") != BUILD_002_HOLDOUT_COUNT
        or inventory.get("environment_make_interactions") != 0
        or inventory.get("gameplay_observed") is not False
        or not verify_object_hash(inventory, hash_field="inventory_hash")
    ):
        raise EvaluationError("Build 002 static asset inventory is invalid")
    inventory_games = inventory.get("assets")
    if (
        not isinstance(inventory_games, list)
        or tuple(item.get("game_id") for item in inventory_games if isinstance(item, dict)) != games
    ):
        raise EvaluationError("Build 002 static asset inventory game order changed")
    preview_row = next(
        row for row in artifact_rows if row["role"] == "source-preview-contamination-receipt"
    )
    preview = _load_object(resolved_root / cast(str, preview_row["path"]))
    preview_exposure = preview.get("exposure")
    preview_authority = preview.get("authority")
    preview_consequence = preview.get("consequence")
    if (
        preview.get("schema") != SOURCE_PREVIEW_SCHEMA
        or not isinstance(preview_exposure, dict)
        or preview_exposure.get("environment_make_interactions") != 0
        or preview_exposure.get("environment_actions") != 0
        or preview_exposure.get("production_policy_changes_derived_from_snippet") is not False
        or not isinstance(preview_authority, dict)
        or preview_authority.get("build_002_mechanical_consumption_boundary_crossed") is not False
        or not isinstance(preview_consequence, dict)
        or preview_consequence.get("future_public_run_may_be_labeled_pristine_or_unseen")
        is not False
        or preview_consequence.get("future_public_run_evidence_label") != BUILD_002_RESULT_LABEL
    ):
        raise EvaluationError("Build 002 source-preview contamination receipt is invalid")

    report: dict[str, Any] = {
        "artifacts": artifact_rows,
        "attempt_id": attempt_id,
        "authority": {
            "authorized_runs": 1,
            "consumption_boundary": "durable marker immediately before first make",
            "failure_after_boundary_consumes_authority": True,
            "retry_authorized": False,
        },
        "claim_boundary": "frozen local-public preflight only; no gameplay or official score",
        "created_at": _utc_now(),
        "execution": {
            "environment_make_interactions_per_game": 1,
            "environment_order": list(games),
            "mode": "COMPETITION_BOUNDED",
            "network_mode": "offline-loopback-only",
            "scorecard_count": 1,
            "seed": seed,
        },
        "gates": gate_rows,
        "git": {"clean_worktree": True, "commit": commit, "tree": tree},
        "manifest": {
            "game_count": BUILD_002_HOLDOUT_COUNT,
            "game_ids": list(games),
            "path": _safe_relative(resolved_root, manifest_path)[1],
            "sha256": PUBLIC_PARTITION_MANIFEST_SHA256,
        },
        "official_rhae": None,
        "private_surface": {
            "exact_kaggle_runtime_available": False,
            "status": "BLOCKED_EXTERNAL",
        },
        "schema": PREFLIGHT_SCHEMA,
        "status": "PASS",
        "source_preview_exposure": {
            "receipt_sha256": preview_row["sha256"],
            "result_label": BUILD_002_RESULT_LABEL,
        },
        "surface": "local-public",
    }
    return seal_object(report, hash_field="preflight_hash")


def _validate_preflight(root: Path, receipt: Mapping[str, Any]) -> tuple[str, ...]:
    value = dict(receipt)
    if (
        value.get("schema") != PREFLIGHT_SCHEMA
        or value.get("status") != "PASS"
        or value.get("surface") != "local-public"
        or value.get("official_rhae") is not None
        or not verify_object_hash(value, hash_field="preflight_hash")
    ):
        raise EvaluationError("Build 002 preflight receipt is invalid")
    git = value.get("git")
    if not isinstance(git, dict) or git.get("clean_worktree") is not True:
        raise EvaluationError("Build 002 preflight has no clean git identity")
    if _git(root, "rev-parse", "HEAD") != git.get("commit"):
        raise EvaluationError("current commit differs from the frozen Build 002 preflight")
    if _git(root, "rev-parse", "HEAD^{tree}") != git.get("tree"):
        raise EvaluationError("current tree differs from the frozen Build 002 preflight")
    if _git(root, "status", "--porcelain", "--untracked-files=all"):
        raise EvaluationError("one-shot holdout execution requires the frozen clean worktree")

    manifest = value.get("manifest")
    if not isinstance(manifest, dict) or not isinstance(manifest.get("path"), str):
        raise EvaluationError("Build 002 preflight manifest binding is invalid")
    manifest_games = _exact_holdout_games(root / cast(str, manifest["path"]))
    if (
        manifest.get("sha256") != PUBLIC_PARTITION_MANIFEST_SHA256
        or manifest.get("game_count") != BUILD_002_HOLDOUT_COUNT
        or manifest.get("game_ids") != list(manifest_games)
    ):
        raise EvaluationError("Build 002 preflight manifest identity changed")
    for field, expected_roles, require_pass in (
        ("gates", _REQUIRED_GATE_ROLES, True),
        ("artifacts", _REQUIRED_ARTIFACT_ROLES, False),
    ):
        rows = value.get(field)
        if not isinstance(rows, list) or len(rows) != len(expected_roles):
            raise EvaluationError(f"Build 002 preflight {field} set changed")
        roles: set[str] = set()
        for row in rows:
            if not isinstance(row, dict):
                raise EvaluationError(f"Build 002 preflight {field} contains a non-object")
            role = row.get("role")
            relative = row.get("path")
            if not isinstance(role, str) or not isinstance(relative, str):
                raise EvaluationError(f"Build 002 preflight {field} binding is malformed")
            roles.add(role)
            resolved, canonical = _safe_relative(root, root / relative)
            if canonical != relative or not resolved.is_file():
                raise EvaluationError(f"Build 002 preflight binding disappeared: {role}")
            if (
                row.get("sha256") != sha256_file(resolved)
                or row.get("byte_length") != resolved.stat().st_size
            ):
                raise EvaluationError(f"Build 002 preflight binding changed: {role}")
            if require_pass and _load_object(resolved).get("status") != "PASS":
                raise EvaluationError(f"Build 002 preflight gate regressed: {role}")
        if roles != expected_roles:
            raise EvaluationError(f"Build 002 preflight {field} roles changed")
    execution = value.get("execution")
    if not isinstance(execution, dict) or execution != {
        "environment_make_interactions_per_game": 1,
        "environment_order": list(manifest_games),
        "mode": "COMPETITION_BOUNDED",
        "network_mode": "offline-loopback-only",
        "scorecard_count": 1,
        "seed": execution.get("seed") if isinstance(execution, dict) else None,
    }:
        raise EvaluationError("Build 002 preflight execution declaration changed")
    seed = execution.get("seed")
    if isinstance(seed, bool) or not isinstance(seed, int) or not -(2**63) <= seed < 2**63:
        raise EvaluationError("Build 002 preflight seed is invalid")
    return manifest_games


class OneShotHoldoutSeal:
    """Durable pre-make boundary and terminal result seal for one process run."""

    def __init__(
        self,
        root: Path,
        state_root: Path,
        preflight: Mapping[str, Any],
        games: tuple[str, ...],
    ) -> None:
        self._root = root.resolve()
        self._state_root = state_root.resolve()
        self._preflight = dict(preflight)
        self._games = games
        self._make_intents: list[str] = []
        self._previous_event_hash: str | None = None
        self._owns_consumption = False

    @classmethod
    def arm(
        cls,
        root: Path,
        *,
        state_root: Path,
        preflight_path: Path,
    ) -> OneShotHoldoutSeal:
        """Validate the complete freeze and write a launch receipt before execution."""

        resolved_root = root.resolve()
        resolved_state = _canonical_state_root(resolved_root, state_root)
        if preflight_path.resolve() != (resolved_state / "preflight.json").resolve():
            raise EvaluationError("Build 002 one-shot preflight path is not canonical")
        _, preflight_relative = _safe_relative(resolved_root, preflight_path)
        preflight = _load_object(preflight_path)
        games = _validate_preflight(resolved_root, preflight)
        resolved_state.mkdir(parents=True, exist_ok=True)
        consumption_path = resolved_state / "holdout-consumed.json"
        result_path = resolved_state / "result.json"
        if consumption_path.exists():
            raise EvaluationError(
                "Build 002 holdout authority was already consumed; no rerun is authorized"
            )
        if result_path.exists():
            raise EvaluationError("Build 002 holdout already has a terminal result")
        launch = seal_object(
            {
                "attempt_id": preflight.get("attempt_id"),
                "created_at": _utc_now(),
                "game_count": BUILD_002_HOLDOUT_COUNT,
                "preflight_hash": preflight.get("preflight_hash"),
                "preflight_path": preflight_relative,
                "schema": "arc3.build-002.holdout-launch.v0.1",
                "status": "ARMED_NOT_CONSUMED",
            },
            hash_field="launch_hash",
        )
        launch_path = resolved_state / "launch.json"
        if launch_path.exists():
            prior = _load_object(launch_path)
            if (
                prior.get("schema") != launch.get("schema")
                or prior.get("attempt_id") != launch.get("attempt_id")
                or prior.get("preflight_hash") != launch.get("preflight_hash")
                or prior.get("preflight_path") != launch.get("preflight_path")
                or not verify_object_hash(prior, hash_field="launch_hash")
            ):
                raise EvaluationError("a different Build 002 launch is already armed")
        else:
            _write_once(launch_path, launch)
        return cls(resolved_root, resolved_state, preflight, games)

    @property
    def expected_games(self) -> tuple[str, ...]:
        return self._games

    @property
    def consumed(self) -> bool:
        return self._owns_consumption

    def before_environment_make(self, game_id: str, ordinal: int) -> None:
        """Persist consumption/make intent before the upstream ``make`` call."""

        if isinstance(ordinal, bool) or not isinstance(ordinal, int):
            raise EvaluationError("environment ordinal must be an integer")
        expected_ordinal = len(self._make_intents)
        if ordinal != expected_ordinal or ordinal >= len(self._games):
            raise EvaluationError("Build 002 environment make ordinal changed")
        if game_id != self._games[ordinal]:
            raise EvaluationError("Build 002 environment make order or identity changed")
        if not self._owns_consumption:
            marker = seal_object(
                {
                    "attempt_id": self._preflight.get("attempt_id"),
                    "consumed_at": _utc_now(),
                    "failure_after_boundary_consumes_authority": True,
                    "first_game_id": game_id,
                    "first_make_ordinal": ordinal,
                    "preflight_hash": self._preflight.get("preflight_hash"),
                    "rerun_authorized": False,
                    "schema": CONSUMPTION_SCHEMA,
                    "status": "INTENTIONALLY_CONSUMED",
                },
                hash_field="consumption_hash",
            )
            _write_once(self._state_root / "holdout-consumed.json", marker)
            self._owns_consumption = True
        event = seal_object(
            {
                "attempt_id": self._preflight.get("attempt_id"),
                "event_type": "environment.make_intent",
                "game_id": game_id,
                "occurred_at": _utc_now(),
                "ordinal": ordinal,
                "preflight_hash": self._preflight.get("preflight_hash"),
                "previous_event_hash": self._previous_event_hash,
                "schema": EXPOSURE_EVENT_SCHEMA,
                "sequence": ordinal,
            },
            hash_field="event_hash",
        )
        _append_fsynced(self._state_root / "exposure.jsonl", event)
        self._previous_event_hash = cast(str, event["event_hash"])
        self._make_intents.append(game_id)

    def seal_terminal_result(
        self,
        *,
        status: str,
        games: Sequence[GameMeasurement],
        launch_receipt: Mapping[str, Any],
        total_wall_seconds: float,
        peak_memory_bytes: int,
        result_artifacts: Sequence[ArtifactBinding],
    ) -> dict[str, Any]:
        """Validate and immutably seal the complete local-public result."""

        if status not in _TERMINAL_RESULT_STATUSES:
            raise EvaluationError("Build 002 terminal result status is invalid")
        if not self._owns_consumption:
            raise EvaluationError("cannot seal a run result before holdout consumption")
        if tuple(self._make_intents) != self._games:
            raise EvaluationError("cannot seal result before all ten make intents")
        measured = tuple(games)
        if tuple(game.game_id for game in measured) != self._games:
            raise EvaluationError("terminal game rows differ from frozen environment order")
        if (
            isinstance(total_wall_seconds, bool)
            or not isinstance(total_wall_seconds, (int, float))
            or not math.isfinite(float(total_wall_seconds))
            or total_wall_seconds < 0
        ):
            raise EvaluationError("terminal wall time is invalid")
        if (
            isinstance(peak_memory_bytes, bool)
            or not isinstance(peak_memory_bytes, int)
            or peak_memory_bytes < 0
        ):
            raise EvaluationError("terminal peak memory is invalid")
        tournament = _validate_launch_receipt(launch_receipt, self._games)
        tournament_games = cast(list[dict[str, Any]], tournament["games"])
        for measured_game, governor_game in zip(measured, tournament_games, strict=True):
            if not math.isclose(
                measured_game.allocated_seconds,
                _finite_nonnegative_number(
                    governor_game.get("allocated_seconds"),
                    field="governor allocated_seconds",
                ),
                rel_tol=0.0,
                abs_tol=1e-9,
            ):
                raise EvaluationError("per-game allocation differs from governor receipt")
            if not math.isclose(
                measured_game.reserve_remaining_seconds,
                _finite_nonnegative_number(
                    governor_game.get("reserve_remaining_seconds"),
                    field="governor reserve_remaining_seconds",
                ),
                rel_tol=0.0,
                abs_tol=1e-9,
            ):
                raise EvaluationError("per-game reserve differs from governor receipt")
            authorized = governor_game.get("actions_authorized")
            if authorized is not None and authorized != measured_game.actions:
                raise EvaluationError("per-game actions differ from governor receipt")
        toolkit_total = sum(game.toolkit_score for game in measured) / len(measured)
        documented_games = [game.documented_formula_score() for game in measured]
        documented_total = (
            None
            if any(score is None for score in documented_games)
            else sum(cast(float, score) for score in documented_games) / len(documented_games)
        )
        failure_counts = {classification.value: 0 for classification in FailureClassification}
        for game in measured:
            if game.primary_failure is not None:
                failure_counts[game.primary_failure.value] += 1
        launch = json.loads(
            json.dumps(launch_receipt, allow_nan=False, sort_keys=True, separators=(",", ":"))
        )
        artifacts = _binding_rows(self._root, result_artifacts, require_pass=False)
        if {cast(str, row["role"]) for row in artifacts} != _REQUIRED_RESULT_ARTIFACT_ROLES:
            raise EvaluationError(
                "Build 002 terminal result artifact set is incomplete or expanded"
            )
        report: dict[str, Any] = {
            "artifacts": artifacts,
            "attempt_id": self._preflight.get("attempt_id"),
            "completed_games": sum(game.completed for game in measured),
            "completed_levels": sum(game.levels_completed for game in measured),
            "consumption": _load_object(self._state_root / "holdout-consumed.json"),
            "evidence_label": BUILD_002_RESULT_LABEL,
            "failure_classification_counts": failure_counts,
            "games": [game.to_dict() for game in measured],
            "launch_receipt": launch,
            "official_rhae": None,
            "official_rhae_reason": (
                "no Kaggle evaluator returned this score; public-toolkit and independently "
                "documented-formula values are local-public evidence only"
            ),
            "peak_memory_bytes": peak_memory_bytes,
            "preflight_hash": self._preflight.get("preflight_hash"),
            "sealed_at": _utc_now(),
            "remaining_reserve_seconds": tournament.get("reserve_remaining_seconds"),
            "schema": RESULT_SCHEMA,
            "scores": {
                "documented_formula_rhae": documented_total,
                "documented_formula_scope": (
                    "independent local computation from scorecard human/action pairs"
                    if documented_total is not None
                    else "unavailable because at least one completed level lacks an exact pair"
                ),
                "local_toolkit_total": toolkit_total,
                "official": False,
            },
            "source_config_artifact_hashes": self._preflight.get("artifacts"),
            "status": status,
            "total_actions": sum(game.actions for game in measured),
            "total_resets": sum(game.resets for game in measured),
            "total_wall_seconds": float(total_wall_seconds),
        }
        sealed = seal_object(report, hash_field="result_hash")
        _write_once(self._state_root / "result.json", sealed)
        return sealed

    def seal_consumed_failure(
        self,
        *,
        classification: FailureClassification,
        boundary: str,
        error: BaseException,
    ) -> dict[str, Any]:
        """Seal a crash after consumption without authorizing a rerun."""

        if not self._owns_consumption:
            raise EvaluationError("an unconsumed launch is not a consumed failed attempt")
        if not isinstance(classification, FailureClassification):
            raise EvaluationError("consumed failure requires the exact Build 002 taxonomy")
        if not boundary or boundary.strip() != boundary:
            raise EvaluationError("consumed failure boundary must be canonical and non-empty")
        import hashlib

        report: dict[str, Any] = {
            "attempt_id": self._preflight.get("attempt_id"),
            "boundary": boundary,
            "consumption": _load_object(self._state_root / "holdout-consumed.json"),
            "error_type": type(error).__name__,
            "failure_classification": classification.value,
            "game_count": BUILD_002_HOLDOUT_COUNT,
            "make_intent_count": len(self._make_intents),
            "make_intents": list(self._make_intents),
            "message_sha256": f"sha256:{hashlib.sha256(str(error).encode()).hexdigest()}",
            "missing_games": list(self._games[len(self._make_intents) :]),
            "official_rhae": None,
            "preflight_hash": self._preflight.get("preflight_hash"),
            "rerun_authorized": False,
            "schema": FAILED_ATTEMPT_SCHEMA,
            "sealed_at": _utc_now(),
            "status": "FAILED_INFRASTRUCTURE",
            "evidence_label": BUILD_002_RESULT_LABEL,
            "surface": "local-public",
        }
        sealed = seal_object(report, hash_field="failure_hash")
        _write_once(self._state_root / "failed-attempt.json", sealed)
        return sealed


def _documented_level_score(level: LevelMeasurement) -> float | None:
    if not level.completed:
        return 0.0
    if (
        level.agent_actions is None
        or level.agent_actions <= 0
        or level.human_baseline_actions is None
        or level.human_baseline_actions <= 0
    ):
        return None
    ratio = min(level.human_baseline_actions / level.agent_actions, 1.0)
    return ratio * ratio


def _finite_nonnegative_number(value: object, *, field: str) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        or float(value) < 0.0
    ):
        raise EvaluationError(f"{field} is not a finite non-negative number")
    return float(value)


def _validate_launch_receipt(receipt: Mapping[str, Any], games: tuple[str, ...]) -> dict[str, Any]:
    expected_count = len(games)
    exact = {
        "all_environments_covered": True,
        "close_scorecard_count": 1,
        "game_count": expected_count,
        "get_scorecard_during_flight_count": 0,
        "lifecycle_enforced": True,
        "make_count": expected_count,
        "open_scorecard_count": 1,
        "tournament_configured": True,
        "tournament_finalized": True,
    }
    for field, expected in exact.items():
        if receipt.get(field) != expected:
            raise EvaluationError(f"competition launch receipt violates {field}")
    discovered = receipt.get("discovered_environments")
    if discovered != games and discovered != list(games):
        raise EvaluationError("competition launch receipt environment order changed")
    tournament_wrapper = receipt.get("tournament_receipt")
    if not isinstance(tournament_wrapper, dict) or tournament_wrapper.get("status") != "PASS":
        raise EvaluationError("competition tournament receipt is not PASS")
    tournament = tournament_wrapper.get("receipt")
    if not isinstance(tournament, dict):
        raise EvaluationError("competition tournament terminal receipt is missing")
    if (
        tournament.get("expected_environments") != expected_count
        or tournament.get("finalized_environments") != expected_count
        or tournament.get("reserve_preserved") is not True
        or tournament.get("effective_ceiling_respected") is not True
    ):
        raise EvaluationError("competition tournament terminal invariants failed")
    game_rows = tournament.get("games")
    if (
        not isinstance(game_rows, list)
        or tuple(row.get("game_id") for row in game_rows if isinstance(row, dict)) != games
    ):
        raise EvaluationError("competition tournament game receipts differ from the freeze")
    _finite_nonnegative_number(
        tournament.get("reserve_remaining_seconds"), field="tournament reserve_remaining_seconds"
    )
    for row in game_rows:
        if not isinstance(row, dict):  # pragma: no cover - excluded by identity projection above
            raise EvaluationError("competition tournament game receipt is not an object")
        _finite_nonnegative_number(row.get("allocated_seconds"), field="governor allocated_seconds")
        _finite_nonnegative_number(
            row.get("reserve_remaining_seconds"),
            field="governor reserve_remaining_seconds",
        )
    return tournament


def launch_frozen_framework_once(
    seal: OneShotHoldoutSeal,
    framework_root: Path,
    agent_path: Path,
    *,
    gateway_host: str = "127.0.0.1",
    gateway_port: int = 8001,
    working_root: Path | None = None,
    allow_test_fixture: bool = False,
    notebook_started_at_seconds: float | None = None,
) -> CompetitionLaunchReceipt:
    """Run the pinned lifecycle with the durable callback directly before each make."""

    from arc3.packaging.runtime_launcher import launch_competition_framework

    try:
        return launch_competition_framework(
            framework_root,
            agent_path,
            gateway_host=gateway_host,
            gateway_port=gateway_port,
            working_root=working_root,
            allow_test_fixture=allow_test_fixture,
            before_environment_make=seal.before_environment_make,
            notebook_started_at_seconds=notebook_started_at_seconds,
        )
    except BaseException as error:
        if seal.consumed:
            seal.seal_consumed_failure(
                classification=FailureClassification.PLATFORM,
                boundary="official-framework-launch",
                error=error,
            )
        raise


def _measurement_from_dict(value: object) -> GameMeasurement:
    if not isinstance(value, dict):
        raise EvaluationError("Build 002 result contains a non-object game row")
    level_values = value.get("levels")
    if not isinstance(level_values, list):
        raise EvaluationError("Build 002 result game has no level rows")
    levels: list[LevelMeasurement] = []
    for raw_level in level_values:
        if not isinstance(raw_level, dict):
            raise EvaluationError("Build 002 result contains a non-object level row")
        try:
            level = LevelMeasurement(
                level_index=raw_level["level_index"],
                completed=raw_level["completed"],
                toolkit_score=raw_level["toolkit_score"],
                agent_actions=raw_level["agent_actions"],
                human_baseline_actions=raw_level["human_baseline_actions"],
            )
        except (KeyError, TypeError, ValueError) as error:
            raise EvaluationError("Build 002 result level row is invalid") from error
        if level.to_dict() != raw_level:
            raise EvaluationError("Build 002 result level row has extra or derived-field changes")
        levels.append(level)
    raw_failure = value.get("primary_failure")
    try:
        failure = None if raw_failure is None else FailureClassification(raw_failure)
        measurement = GameMeasurement(
            game_id=value["game_id"],
            completed=value["completed"],
            levels_completed=value["levels_completed"],
            actions=value["actions"],
            resets=value["resets"],
            toolkit_score=value["toolkit_score"],
            wall_seconds=value["wall_seconds"],
            peak_memory_bytes=value["peak_memory_bytes"],
            allocated_seconds=value["allocated_seconds"],
            reserve_remaining_seconds=value["reserve_remaining_seconds"],
            stop_reason=value["stop_reason"],
            primary_failure=failure,
            levels=tuple(levels),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise EvaluationError("Build 002 result game row is invalid") from error
    if measurement.to_dict() != value:
        raise EvaluationError("Build 002 result game row has extra or derived-field changes")
    return measurement


def _verify_result_artifacts(root: Path, value: object) -> None:
    if not isinstance(value, list):
        raise EvaluationError("Build 002 result artifact list is invalid")
    roles: set[str] = set()
    for row in value:
        if not isinstance(row, dict):
            raise EvaluationError("Build 002 result artifact row is not an object")
        if set(row) != {"byte_length", "path", "role", "sha256"}:
            raise EvaluationError("Build 002 result artifact row fields changed")
        role = row.get("role")
        relative = row.get("path")
        if not isinstance(role, str) or not role or role in roles or not isinstance(relative, str):
            raise EvaluationError("Build 002 result artifact identity is invalid")
        roles.add(role)
        resolved, canonical = _safe_relative(root, root / relative)
        if canonical != relative or not resolved.is_file():
            raise EvaluationError(f"Build 002 result artifact disappeared: {role}")
        if row.get("byte_length") != resolved.stat().st_size or row.get("sha256") != sha256_file(
            resolved
        ):
            raise EvaluationError(f"Build 002 result artifact changed: {role}")
    if roles != _REQUIRED_RESULT_ARTIFACT_ROLES:
        raise EvaluationError("Build 002 result artifact role set changed")


def _validate_exposure_chain(
    state_root: Path,
    *,
    preflight_hash: object,
    games: tuple[str, ...],
    expected_count: int,
) -> list[dict[str, Any]]:
    if not 0 <= expected_count <= len(games):
        raise EvaluationError("Build 002 exposure expected count is invalid")
    exposure_path = state_root / "exposure.jsonl"
    if expected_count == 0 and not exposure_path.exists():
        return []
    try:
        lines = exposure_path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as error:
        raise EvaluationError("Build 002 exposure ledger is unreadable") from error
    if len(lines) != expected_count:
        raise EvaluationError("Build 002 exposure ledger has an unexpected intent count")
    events: list[dict[str, Any]] = []
    prior_hash: str | None = None
    for sequence, line in enumerate(lines):
        try:
            item: object = json.loads(line)
        except json.JSONDecodeError as error:
            raise EvaluationError("Build 002 exposure ledger is invalid JSONL") from error
        if not isinstance(item, dict):
            raise EvaluationError("Build 002 exposure ledger contains a non-object")
        if (
            item.get("schema") != EXPOSURE_EVENT_SCHEMA
            or item.get("event_type") != "environment.make_intent"
            or item.get("sequence") != sequence
            or item.get("ordinal") != sequence
            or item.get("game_id") != games[sequence]
            or item.get("previous_event_hash") != prior_hash
            or item.get("preflight_hash") != preflight_hash
            or not verify_object_hash(item, hash_field="event_hash")
        ):
            raise EvaluationError("Build 002 exposure event chain is invalid")
        prior_hash = cast(str, item["event_hash"])
        events.append(item)
    return events


def validate_terminal_result(
    root: Path,
    *,
    state_root: Path,
    preflight_path: Path,
) -> dict[str, Any]:
    """Independently verify the frozen preflight, exposure chain, and result seal."""

    resolved_root = root.resolve()
    preflight = _load_object(preflight_path)
    games = _validate_preflight(resolved_root, preflight)
    resolved_state = _canonical_state_root(resolved_root, state_root)
    if preflight_path.resolve() != (resolved_state / "preflight.json").resolve():
        raise EvaluationError("Build 002 one-shot preflight path is not canonical")
    consumption = _load_object(resolved_state / "holdout-consumed.json")
    if (
        consumption.get("schema") != CONSUMPTION_SCHEMA
        or consumption.get("status") != "INTENTIONALLY_CONSUMED"
        or consumption.get("preflight_hash") != preflight.get("preflight_hash")
        or consumption.get("first_game_id") != games[0]
        or consumption.get("first_make_ordinal") != 0
        or consumption.get("rerun_authorized") is not False
        or not verify_object_hash(consumption, hash_field="consumption_hash")
    ):
        raise EvaluationError("Build 002 consumption marker is invalid")
    _validate_exposure_chain(
        resolved_state,
        preflight_hash=preflight.get("preflight_hash"),
        games=games,
        expected_count=BUILD_002_HOLDOUT_COUNT,
    )
    result = _load_object(resolved_state / "result.json")
    if (
        result.get("schema") != RESULT_SCHEMA
        or result.get("status") not in _TERMINAL_RESULT_STATUSES
        or result.get("preflight_hash") != preflight.get("preflight_hash")
        or result.get("official_rhae") is not None
        or result.get("evidence_label") != BUILD_002_RESULT_LABEL
        or not verify_object_hash(result, hash_field="result_hash")
    ):
        raise EvaluationError("Build 002 terminal result seal is invalid")
    result_games = result.get("games")
    if not isinstance(result_games, list):
        raise EvaluationError("Build 002 result game rows are missing")
    measurements = tuple(_measurement_from_dict(row) for row in result_games)
    if tuple(measurement.game_id for measurement in measurements) != games:
        raise EvaluationError("Build 002 result game rows differ from the freeze")
    launch = result.get("launch_receipt")
    if not isinstance(launch, dict):
        raise EvaluationError("Build 002 result launch receipt is invalid")
    tournament = _validate_launch_receipt(launch, games)
    tournament_games = cast(list[dict[str, Any]], tournament["games"])
    for measured_game, governor_game in zip(measurements, tournament_games, strict=True):
        if not math.isclose(
            measured_game.allocated_seconds,
            _finite_nonnegative_number(
                governor_game.get("allocated_seconds"), field="governor allocated_seconds"
            ),
            rel_tol=0.0,
            abs_tol=1e-9,
        ):
            raise EvaluationError("Build 002 result allocation disagrees with governor")
        if not math.isclose(
            measured_game.reserve_remaining_seconds,
            _finite_nonnegative_number(
                governor_game.get("reserve_remaining_seconds"),
                field="governor reserve_remaining_seconds",
            ),
            rel_tol=0.0,
            abs_tol=1e-9,
        ):
            raise EvaluationError("Build 002 result reserve disagrees with governor")
    documented_games = [measurement.documented_formula_score() for measurement in measurements]
    documented_total = (
        None
        if any(score is None for score in documented_games)
        else sum(cast(float, score) for score in documented_games) / len(documented_games)
    )
    toolkit_total = sum(measurement.toolkit_score for measurement in measurements) / len(
        measurements
    )
    scores = result.get("scores")
    expected_scores = {
        "documented_formula_rhae": documented_total,
        "documented_formula_scope": (
            "independent local computation from scorecard human/action pairs"
            if documented_total is not None
            else "unavailable because at least one completed level lacks an exact pair"
        ),
        "local_toolkit_total": toolkit_total,
        "official": False,
    }
    if scores != expected_scores:
        raise EvaluationError("Build 002 result aggregate scores do not recompute")
    failure_counts = {classification.value: 0 for classification in FailureClassification}
    for measurement in measurements:
        if measurement.primary_failure is not None:
            failure_counts[measurement.primary_failure.value] += 1
    if result.get("failure_classification_counts") != failure_counts:
        raise EvaluationError("Build 002 result failure taxonomy does not recompute")
    if result.get("completed_games") != sum(item.completed for item in measurements):
        raise EvaluationError("Build 002 result completed-game count does not recompute")
    if result.get("completed_levels") != sum(item.levels_completed for item in measurements):
        raise EvaluationError("Build 002 result completed-level count does not recompute")
    if result.get("total_actions") != sum(item.actions for item in measurements):
        raise EvaluationError("Build 002 result action count does not recompute")
    if result.get("total_resets") != sum(item.resets for item in measurements):
        raise EvaluationError("Build 002 result reset count does not recompute")
    _finite_nonnegative_number(result.get("total_wall_seconds"), field="result wall time")
    peak = result.get("peak_memory_bytes")
    if isinstance(peak, bool) or not isinstance(peak, int) or peak < 0:
        raise EvaluationError("Build 002 result peak memory is invalid")
    if result.get("remaining_reserve_seconds") != tournament.get("reserve_remaining_seconds"):
        raise EvaluationError("Build 002 result terminal reserve changed")
    if result.get("source_config_artifact_hashes") != preflight.get("artifacts"):
        raise EvaluationError("Build 002 result source/config/artifact freeze changed")
    if result.get("consumption") != consumption:
        raise EvaluationError("Build 002 result embedded consumption marker changed")
    _verify_result_artifacts(resolved_root, result.get("artifacts"))
    return result


def validate_consumed_failure(
    root: Path,
    *,
    state_root: Path,
    preflight_path: Path,
) -> dict[str, Any]:
    """Validate a consumed crash receipt without turning it into a score."""

    resolved_root = root.resolve()
    preflight = _load_object(preflight_path)
    games = _validate_preflight(resolved_root, preflight)
    resolved_state = _canonical_state_root(resolved_root, state_root)
    if preflight_path.resolve() != (resolved_state / "preflight.json").resolve():
        raise EvaluationError("Build 002 one-shot preflight path is not canonical")
    consumption = _load_object(resolved_state / "holdout-consumed.json")
    if (
        consumption.get("schema") != CONSUMPTION_SCHEMA
        or consumption.get("status") != "INTENTIONALLY_CONSUMED"
        or consumption.get("preflight_hash") != preflight.get("preflight_hash")
        or not verify_object_hash(consumption, hash_field="consumption_hash")
    ):
        raise EvaluationError("Build 002 consumed failure has an invalid consumption marker")
    failure = _load_object(resolved_state / "failed-attempt.json")
    if (
        failure.get("schema") != FAILED_ATTEMPT_SCHEMA
        or failure.get("status") != "FAILED_INFRASTRUCTURE"
        or failure.get("surface") != "local-public"
        or failure.get("evidence_label") != BUILD_002_RESULT_LABEL
        or failure.get("official_rhae") is not None
        or failure.get("rerun_authorized") is not False
        or failure.get("preflight_hash") != preflight.get("preflight_hash")
        or failure.get("consumption") != consumption
        or not verify_object_hash(failure, hash_field="failure_hash")
    ):
        raise EvaluationError("Build 002 consumed failure receipt is invalid")
    raw_classification = failure.get("failure_classification")
    if not isinstance(raw_classification, str):
        raise EvaluationError("Build 002 consumed failure taxonomy is invalid")
    try:
        FailureClassification(raw_classification)
    except (TypeError, ValueError) as error:
        raise EvaluationError("Build 002 consumed failure taxonomy is invalid") from error
    intents = failure.get("make_intents")
    count = failure.get("make_intent_count")
    missing = failure.get("missing_games")
    if (
        not isinstance(count, int)
        or isinstance(count, bool)
        or not 0 <= count <= BUILD_002_HOLDOUT_COUNT
        or intents != list(games[:count])
        or missing != list(games[count:])
    ):
        raise EvaluationError("Build 002 consumed failure make accounting is invalid")
    _validate_exposure_chain(
        resolved_state,
        preflight_hash=preflight.get("preflight_hash"),
        games=games,
        expected_count=count,
    )
    return failure


__all__ = [
    "ASSET_INVENTORY_SCHEMA",
    "BUILD_002_ATTEMPT_ID",
    "BUILD_002_HOLDOUT_COUNT",
    "BUILD_002_RESULT_LABEL",
    "CANONICAL_STATE_RELATIVE",
    "CONSUMPTION_SCHEMA",
    "EXPOSURE_EVENT_SCHEMA",
    "FAILED_ATTEMPT_SCHEMA",
    "PREFLIGHT_SCHEMA",
    "RESULT_SCHEMA",
    "SOURCE_PREVIEW_SCHEMA",
    "ArtifactBinding",
    "FailureClassification",
    "GameMeasurement",
    "LevelMeasurement",
    "OneShotHoldoutSeal",
    "ReceiptBinding",
    "create_frozen_preflight",
    "create_static_asset_inventory",
    "launch_frozen_framework_once",
    "validate_consumed_failure",
    "validate_terminal_result",
]
