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

import ast
import hashlib
import json
import math
import os
import subprocess
import tomllib
import zipfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from importlib import import_module
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, cast

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
PREFLIGHT_SCHEMA = "arc3.build-002.one-shot-preflight.v0.2"
CONSUMPTION_SCHEMA = "arc3.build-002.holdout-consumption.v0.2"
EXPOSURE_EVENT_SCHEMA = "arc3.build-002.holdout-exposure-event.v0.1"
RESULT_SCHEMA = "arc3.build-002.local-public-result.v0.2"
RUNTIME_EVIDENCE_MANIFEST_SCHEMA = "arc3.build-002.runtime-evidence-manifest.v0.1"
RAW_RUNTIME_SCORECARD_SCHEMA = "arc3.build-002.raw-scorecard.v0.2"
FAILED_ATTEMPT_SCHEMA = "arc3.build-002.consumed-failed-attempt.v0.1"
SOURCE_PREVIEW_SCHEMA = "arc3.build-002.public-source-preview-contamination.v0.1"
LOCAL_SCORECARD_SCHEMA = "arc3.build-002.local-scorecard.v0.1"
EXECUTION_PROFILE_SCHEMA = "arc3.build-002.execution-profile.v0.2"
FAILURE_RECEIPTS_SCHEMA = "arc3.build-002.failure-receipts.v0.1"
COMPETITION_LAUNCH_ARTIFACT_SCHEMA = "arc3.build-002.competition-launch-artifact.v0.1"
BUILD_002_HOLDOUT_COUNT = 10
BUILD_002_ATTEMPT_ID = "build-002-ten-game-public-once-v0.1"
BUILD_002_RESULT_LABEL = "local-public-source-preview-exposed"
CANONICAL_STATE_RELATIVE = Path("artifacts/build002/holdout-one-shot")
PINNED_TOOLKIT_SCORER_COMMIT = "f12822c4d550121c35a275008d964afbbed47d2f"
PINNED_TOOLKIT_SCORER_PATH = "arc_agi/scorecard.py"
PINNED_TOOLKIT_SCORER_SHA256 = (
    "sha256:5eea296343ad086c5f8d3e6626bf6ea25e1c635400ed431b1db85bdab899cc9b"
)
PER_GAME_MEMORY_MEASUREMENT = "sampled-current-rss-window-maximum-50ms"
TOURNAMENT_MEMORY_MEASUREMENT = "kernel-process-peak-rss-high-water-mark"
KERNEL_RSS_MEASUREMENT_SOURCES = frozenset(
    {
        "linux-proc-status-rss-hwm",
        "windows-GetProcessMemoryInfo-working-set",
    }
)
_PINNED_AGENTS_COMMIT = "4743e7d0aaae0ded0d98a89a7e282e63564cd58b"
_PINNED_ORCHESTRATION = "arc3.sequential-pinned-swarm.v1"
_RUN_PLAN_SCHEMA = "arc3.build-002.holdout-run-plan.v0.1"
_ALLOWED_GATEWAY_HOSTS = frozenset({"127.0.0.1", "::1", "gateway", "localhost"})
_RUN_PLAN_FIELDS = frozenset(
    {
        "artifacts",
        "assets",
        "framework_root",
        "gateway_host",
        "gateway_port",
        "gates",
        "manifest",
        "production_agent",
        "schema",
        "seed",
        "submission_output",
    }
)
_PREFLIGHT_FIELDS = frozenset(
    {
        "artifacts",
        "attempt_id",
        "authority",
        "claim_boundary",
        "created_at",
        "execution",
        "execution_surface",
        "gates",
        "git",
        "manifest",
        "official_rhae",
        "preflight_hash",
        "private_surface",
        "run_plan",
        "schema",
        "source_preview_exposure",
        "status",
        "surface",
    }
)
_LAUNCH_RECEIPT_FIELDS = frozenset(
    {
        "agent_count",
        "all_environments_covered",
        "close_scorecard_count",
        "discovered_environments",
        "dotenv_imported",
        "framework_commit",
        "framework_fixture",
        "framework_identity",
        "game_count",
        "gateway_host",
        "gateway_port",
        "get_scorecard_during_flight_count",
        "hard_deadline_seconds",
        "hard_timeout_enforced",
        "lifecycle_enforced",
        "make_count",
        "max_concurrency",
        "notebook_started_at_seconds",
        "open_scorecard_count",
        "orchestration",
        "telemetry_imported",
        "tournament_configured",
        "tournament_finalized",
        "tournament_receipt",
        "worker_count",
    }
)
_TOURNAMENT_FINAL_FIELDS = frozenset(
    {
        "ceiling_remaining_seconds",
        "dropped_history_receipts",
        "effective_ceiling_respected",
        "elapsed_seconds",
        "expected_environments",
        "finalized_at_seconds",
        "finalized_environments",
        "future_opportunity_cost_total_seconds",
        "games",
        "maximum_total_actions",
        "maximum_resets_per_game",
        "maximum_total_resets",
        "outcome",
        "recent_history_receipts",
        "reserve_preserved",
        "reserve_remaining_seconds",
        "reserve_seconds",
        "selected_value_total",
        "sequence",
        "started_at_seconds",
        "total_actions_authorized",
        "total_resets_authorized",
    }
)
_GAME_FINAL_FIELDS = frozenset(
    {
        "actions_authorized",
        "allocated_seconds",
        "allocation_overrun_seconds",
        "began_at_seconds",
        "elapsed_action_cost_total_seconds",
        "elapsed_seconds",
        "fallback_actions",
        "finalized_at_seconds",
        "future_opportunity_cost_total_actions",
        "future_opportunity_cost_total_seconds",
        "game_id",
        "game_ordinal",
        "reason",
        "reset_limit",
        "resets_authorized",
        "reserve_remaining_seconds",
        "selected_value_total",
        "sequence",
        "tournament_playable_seconds_remaining",
        "unassigned_tail_elapsed_seconds",
    }
)
_GOVERNOR_STOP_REASONS = frozenset(
    {
        "agent-done",
        "failure",
        "game-action-limit",
        "game-reset-limit",
        "game-time-limit",
        "no-legal-actions",
        "tournament-action-limit",
        "tournament-playable-time-limit",
        "win",
    }
)

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
        "runtime-evidence-manifest",
        "submission-parquet",
    }
)
_RUNTIME_EVIDENCE_ROOTS = (
    Path("runtime/arc3-agent-state"),
    Path("runtime/arc3-runtime-receipts"),
)
_REQUIRED_RUNTIME_RECEIPTS = frozenset(
    {
        "runtime/arc3-runtime-receipts/raw-local-scorecard.json",
        "runtime/arc3-runtime-receipts/tournament-final.json",
        "runtime/arc3-runtime-receipts/tournament-start.json",
    }
)
_TERMINAL_RESULT_STATUSES = frozenset(
    {"PASS", "PARTIAL", "FAILED_INFRASTRUCTURE", "FAILED_MECHANISM"}
)

_GATE_SCHEMAS = {
    role: f"arc3.build-002.preflight-gate.{role}.v0.2" for role in _REQUIRED_GATE_ROLES
}
_GATE_CHECKS = {
    "competition-lifecycle": frozenset(
        {
            "competition_bounded_mode_configured",
            "governor_reserve_configured",
            "offline_evaluation_configured",
            "safe_fixture_lifecycle_rehearsal_passed",
        }
    ),
    "dependency-and-config-identity": frozenset(
        {
            "dependency_lock_verified",
            "pinned_public_toolkit_identity_verified",
            "python_312_compatible",
            "runtime_config_verified",
        }
    ),
    "deterministic-startup-and-replay": frozenset(
        {
            "compact_trace_retained",
            "deterministic_replay_verified",
            "deterministic_startup_verified",
            "sparse_recovery_checkpoint_verified",
        }
    ),
    "frozen-source-config-artifacts": frozenset(
        {
            "all_artifact_hashes_verified",
            "configuration_identity_verified",
            "source_identity_verified",
        }
    ),
    "notebook-build-and-offline-entry-point": frozenset(
        {
            "deterministic_package_bytes_bound",
            "notebook_contract_verified",
            "safe_fixture_entry_point_executed",
            "output_structurally_valid",
        }
    ),
    "offline-cold-start": frozenset(
        {
            "exact_generated_notebook_cells_executed",
            "host_site_packages_injected_false",
            "native_linux_packaged_entry_rehearsal",
            "network_attempts_zero",
            "packaged_dependencies_complete",
            "runtime_import_inventory_verified",
            "safe_fixture_platform_disclosed",
        }
    ),
    "official-source-identity": frozenset(
        {
            "available_public_source_hashes_verified",
            "evidence_class_source_boundary_verified",
            "official_result_absent_prelaunch",
        }
    ),
    "package-and-license-inventory": frozenset(
        {
            "candidate_archive_valid",
            "dependency_inventory_present",
            "license_notices_present",
            "packaged_runtime_payload_present",
        }
    ),
    "secret-and-integrity-scan": frozenset(
        {
            "blocking_findings_zero",
            "package_only_integrity_passed",
            "secret_scan_passed",
        }
    ),
    "submission-parquet-structure": frozenset(
        {
            "columns_exact",
            "encoding_readable",
            "row_ids_unique",
            "row_types_valid",
        }
    ),
}
_GATE_ARTIFACT_ROLES = {
    "competition-lifecycle": frozenset({"agent-wrapper", "competition-runtime-config"}),
    "dependency-and-config-identity": frozenset({"competition-runtime-config", "dependency-lock"}),
    "deterministic-startup-and-replay": frozenset(
        {"agent-wrapper", "competition-runtime-config", "offline-package-candidate"}
    ),
    "frozen-source-config-artifacts": _REQUIRED_ARTIFACT_ROLES,
    "notebook-build-and-offline-entry-point": frozenset(
        {"kaggle-notebook", "offline-package-candidate", "submission-parquet"}
    ),
    "offline-cold-start": frozenset(
        {"dependency-lock", "offline-package-candidate", "third-party-notices"}
    ),
    "official-source-identity": frozenset({"competition-runtime-config", "upstream-lock"}),
    "package-and-license-inventory": frozenset(
        {
            "dependency-lock",
            "offline-package-candidate",
            "third-party-notices",
            "upstream-lock",
        }
    ),
    "secret-and-integrity-scan": frozenset(
        {"agent-wrapper", "kaggle-notebook", "offline-package-candidate"}
    ),
    "submission-parquet-structure": frozenset({"submission-parquet"}),
}


class _ParquetTable(Protocol):
    def to_pylist(self) -> list[dict[str, object]]: ...


class _ParquetModule(Protocol):
    def read_table(self, where: Path) -> _ParquetTable: ...


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
            or not 0.0 <= float(self.toolkit_score) <= 1.15
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
        recomputed = recompute_pinned_toolkit_level_score(self)
        if not math.isclose(float(self.toolkit_score), recomputed, rel_tol=0.0, abs_tol=1e-12):
            raise ValueError("toolkit_score disagrees with the pinned public-toolkit formula")

    def to_dict(self) -> dict[str, JSONValue]:
        documented = _documented_level_score(self)
        return {
            "agent_actions": self.agent_actions,
            "completed": self.completed,
            "documented_formula_score": documented,
            "human_baseline_actions": self.human_baseline_actions,
            "level_index": self.level_index,
            "pinned_toolkit_recomputed_score": recompute_pinned_toolkit_level_score(self),
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
    sampled_current_rss_max_bytes: int
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
            ("sampled_current_rss_max_bytes", self.sampled_current_rss_max_bytes),
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
        if float(self.toolkit_score) > 1.0:
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
        recomputed = recompute_pinned_toolkit_game_score(self.levels)
        if not math.isclose(float(self.toolkit_score), recomputed, rel_tol=0.0, abs_tol=1e-12):
            raise ValueError("game toolkit_score disagrees with the pinned public-toolkit formula")

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
            "pinned_toolkit_recomputed_score": recompute_pinned_toolkit_game_score(self.levels),
            "primary_failure": (
                self.primary_failure.value if self.primary_failure is not None else None
            ),
            "reserve_remaining_seconds": float(self.reserve_remaining_seconds),
            "resets": self.resets,
            "sampled_current_rss_max_bytes": self.sampled_current_rss_max_bytes,
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
        _fsync_parent(path)
    except FileExistsError as error:
        raise EvaluationError(
            f"immutable Build 002 artifact already exists: {path.name}"
        ) from error


def _append_fsynced(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    existed = path.exists()
    with path.open("ab") as stream:
        stream.write(canonical_json_bytes(payload))
        stream.flush()
        os.fsync(stream.fileno())
    if not existed:
        _fsync_parent(path)


def _fsync_parent(path: Path) -> None:
    """Durably publish a newly created evidence file on the Linux runtime."""

    if os.name != "posix":
        return
    descriptor = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


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


def _runtime_evidence_rows(
    state_root: Path,
    *,
    expected_games: Sequence[str],
) -> list[dict[str, JSONValue]]:
    """Inventory the two canonical runtime evidence trees without following links."""

    resolved_state = state_root.resolve()
    games = tuple(expected_games)
    if (
        len(games) != BUILD_002_HOLDOUT_COUNT
        or len(set(games)) != BUILD_002_HOLDOUT_COUNT
        or any(not game_id or game_id.strip() != game_id for game_id in games)
    ):
        raise EvaluationError("runtime evidence requires the exact ten-game identity")
    runtime_root = resolved_state / "runtime"
    if runtime_root.is_symlink() or not runtime_root.is_dir():
        raise EvaluationError("canonical Build 002 runtime evidence root is unavailable")

    rows: list[dict[str, JSONValue]] = []
    for relative_root in _RUNTIME_EVIDENCE_ROOTS:
        evidence_root = resolved_state / relative_root
        if evidence_root.is_symlink() or not evidence_root.is_dir():
            raise EvaluationError(
                f"runtime evidence root is unavailable: {relative_root.as_posix()}"
            )
        for directory, directory_names, file_names in os.walk(
            evidence_root, topdown=True, followlinks=False
        ):
            directory_path = Path(directory)
            for name in sorted(directory_names):
                child = directory_path / name
                if child.is_symlink():
                    raise EvaluationError("runtime evidence contains a symbolic-link directory")
            for name in sorted(file_names):
                path = directory_path / name
                if path.is_symlink() or not path.is_file():
                    raise EvaluationError("runtime evidence contains a non-regular file")
                try:
                    relative = path.relative_to(resolved_state).as_posix()
                except ValueError as error:  # pragma: no cover - guarded by fixed roots
                    raise EvaluationError(
                        "runtime evidence path escaped canonical state"
                    ) from error
                if any(part in {"", ".", ".."} for part in relative.split("/")):
                    raise EvaluationError("runtime evidence path is not canonical")
                rows.append(
                    {
                        "byte_length": path.stat().st_size,
                        "path": relative,
                        "sha256": sha256_file(path),
                    }
                )
    rows.sort(key=lambda row: cast(str, row["path"]))
    paths = {cast(str, row["path"]) for row in rows}
    missing = _REQUIRED_RUNTIME_RECEIPTS - paths
    if missing:
        raise EvaluationError(
            "runtime evidence is missing required raw/tournament receipts: "
            + ", ".join(sorted(missing))
        )
    return rows


def create_runtime_evidence_manifest(
    state_root: Path,
    *,
    expected_games: Sequence[str],
) -> dict[str, Any]:
    """Create the content-free hash/size/path inventory for terminal runtime evidence."""

    return {
        "files": _runtime_evidence_rows(state_root, expected_games=expected_games),
        "schema": RUNTIME_EVIDENCE_MANIFEST_SCHEMA,
        "status": "PASS",
    }


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


def _rows_by_role(rows: Sequence[Mapping[str, JSONValue]]) -> dict[str, Mapping[str, JSONValue]]:
    return {cast(str, row["role"]): row for row in rows}


def _bound_path(root: Path, row: Mapping[str, JSONValue]) -> Path:
    relative = row.get("path")
    if not isinstance(relative, str):
        raise EvaluationError("Build 002 binding path is malformed")
    resolved, canonical = _safe_relative(root, root / relative)
    if canonical != relative or not resolved.is_file():
        raise EvaluationError("Build 002 binding path is unavailable")
    return resolved


def _validate_submission_file(path: Path) -> list[dict[str, object]]:
    try:
        from arc3.packaging.submission import validate_submission_parquet

        receipt = validate_submission_parquet(path)
        if receipt.status != "PASS":
            raise EvaluationError("submission Parquet validator did not return PASS")
        parquet = cast(_ParquetModule, import_module("pyarrow.parquet"))
        return parquet.read_table(path).to_pylist()
    except EvaluationError:
        raise
    except Exception as error:
        raise EvaluationError("submission Parquet failed semantic validation") from error


def _validate_gate_receipts(
    root: Path,
    gate_rows: Sequence[Mapping[str, JSONValue]],
    artifact_rows: Sequence[Mapping[str, JSONValue]],
) -> None:
    artifacts = _rows_by_role(artifact_rows)
    canonical_evidence: dict[str, Mapping[str, JSONValue]] | None = None
    actual_gate_checks: dict[str, Mapping[str, JSONValue]] = {}
    for row in gate_rows:
        role = cast(str, row["role"])
        receipt = _load_object(_bound_path(root, row))
        if set(receipt) != {
            "artifact_sha256",
            "checks",
            "evidence",
            "evidence_class",
            "schema",
            "status",
        }:
            raise EvaluationError(f"Build 002 gate has unexpected fields: {role}")
        if (
            receipt.get("schema") != _GATE_SCHEMAS[role]
            or receipt.get("status") != "PASS"
            or receipt.get("evidence_class") != "production"
        ):
            raise EvaluationError(f"Build 002 gate schema or status is invalid: {role}")
        checks = receipt.get("checks")
        if (
            not isinstance(checks, dict)
            or set(checks) != _GATE_CHECKS[role]
            or any(value is not True for value in checks.values())
        ):
            raise EvaluationError(f"Build 002 gate semantic checks are invalid: {role}")
        actual_gate_checks[role] = cast(Mapping[str, JSONValue], checks)
        bindings = receipt.get("artifact_sha256")
        expected_roles = _GATE_ARTIFACT_ROLES[role]
        if not isinstance(bindings, dict) or set(bindings) != expected_roles:
            raise EvaluationError(f"Build 002 gate artifact bindings are invalid: {role}")
        for artifact_role in expected_roles:
            if bindings.get(artifact_role) != artifacts[artifact_role].get("sha256"):
                raise EvaluationError(
                    f"Build 002 gate artifact identity disagrees with freeze: {role}"
                )
        from arc3.evaluation.build002_preflight import GATE_EVIDENCE_ROLES

        evidence = receipt.get("evidence")
        if not isinstance(evidence, dict) or set(evidence) != GATE_EVIDENCE_ROLES:
            raise EvaluationError(f"Build 002 gate evidence roles are invalid: {role}")
        normalized: dict[str, Mapping[str, JSONValue]] = {}
        for evidence_role, raw_evidence_row in evidence.items():
            if (
                not isinstance(evidence_role, str)
                or not isinstance(raw_evidence_row, dict)
                or set(raw_evidence_row) != {"byte_length", "path", "sha256"}
            ):
                raise EvaluationError(f"Build 002 gate evidence row is invalid: {role}")
            evidence_path = _bound_path(
                root,
                cast(Mapping[str, JSONValue], raw_evidence_row),
            )
            if raw_evidence_row.get(
                "byte_length"
            ) != evidence_path.stat().st_size or raw_evidence_row.get("sha256") != sha256_file(
                evidence_path
            ):
                raise EvaluationError(f"Build 002 gate evidence identity changed: {role}")
            normalized[evidence_role] = cast(Mapping[str, JSONValue], raw_evidence_row)
        if canonical_evidence is None:
            canonical_evidence = normalized
        elif normalized != canonical_evidence:
            raise EvaluationError("Build 002 gates do not bind one identical evidence set")
    if canonical_evidence is None:
        raise EvaluationError("Build 002 preflight has no gate evidence")
    from arc3.evaluation.build002_preflight import validate_production_evidence_rows

    validate_production_evidence_rows(
        root,
        canonical_evidence,
        artifacts,
        gate_checks=actual_gate_checks,
    )


def _validate_agent_wrapper(path: Path) -> None:
    try:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=path.name)
    except (OSError, UnicodeError, SyntaxError) as error:
        raise EvaluationError("Build 002 agent wrapper is not valid UTF-8 Python") from error
    agent_classes = [
        node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "MyAgent"
    ]
    if len(agent_classes) != 1:
        raise EvaluationError("Build 002 agent wrapper must define exactly one MyAgent")
    methods = {
        node.name
        for node in agent_classes[0].body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    if not {"choose_action", "is_done"}.issubset(methods):
        raise EvaluationError("Build 002 MyAgent lacks the official adapter methods")


def _validate_preflight_artifacts(
    root: Path,
    artifact_rows: Sequence[Mapping[str, JSONValue]],
    games: tuple[str, ...],
) -> None:
    rows = _rows_by_role(artifact_rows)
    paths = {role: _bound_path(root, row) for role, row in rows.items()}
    _validate_agent_wrapper(paths["agent-wrapper"])

    try:
        from arc3.competition_runtime import load_competition_runtime

        runtime = load_competition_runtime(paths["competition-runtime-config"])
    except Exception as error:
        raise EvaluationError("Build 002 competition runtime config is invalid") from error

    try:
        dependency_lock = tomllib.loads(paths["dependency-lock"].read_text(encoding="utf-8"))
    except (OSError, UnicodeError, tomllib.TOMLDecodeError) as error:
        raise EvaluationError("Build 002 dependency lock is invalid TOML") from error
    packages = dependency_lock.get("package")
    package_names = (
        {item.get("name") for item in packages if isinstance(item, dict)}
        if isinstance(packages, list)
        else set()
    )
    if (
        dependency_lock.get("version") != 1
        or dependency_lock.get("requires-python") != "==3.12.*"
        or not {"arc3", "arc-agi", "arcengine", "pyarrow"}.issubset(package_names)
    ):
        raise EvaluationError("Build 002 dependency lock lacks the exact runtime identities")

    inventory = _load_object(paths["holdout-asset-inventory"])
    inventory_games = inventory.get("assets")
    if (
        inventory.get("schema") != ASSET_INVENTORY_SCHEMA
        or inventory.get("status") != "PASS"
        or inventory.get("manifest_sha256") != PUBLIC_PARTITION_MANIFEST_SHA256
        or inventory.get("game_count") != BUILD_002_HOLDOUT_COUNT
        or inventory.get("environment_make_interactions") != 0
        or inventory.get("gameplay_observed") is not False
        or not verify_object_hash(inventory, hash_field="inventory_hash")
        or not isinstance(inventory_games, list)
        or tuple(item.get("game_id") for item in inventory_games if isinstance(item, dict)) != games
    ):
        raise EvaluationError("Build 002 static asset inventory is invalid")

    try:
        from arc3.packaging.notebook import notebook_embedded_inputs, validate_notebook

        notebook = cast(dict[str, JSONValue], _load_object(paths["kaggle-notebook"]))
        validate_notebook(notebook)
        embedded = notebook_embedded_inputs(notebook)
    except Exception as error:
        raise EvaluationError("Build 002 Kaggle notebook contract is invalid") from error

    try:
        from arc3.packaging.candidate import (
            EXPECTED_CANDIDATE_MEMBERS,
            validate_candidate_archive,
        )

        with zipfile.ZipFile(paths["offline-package-candidate"]) as candidate:
            if tuple(candidate.namelist()) != EXPECTED_CANDIDATE_MEMBERS:
                raise EvaluationError("Build 002 offline package member set is invalid")
            corrupt = candidate.testzip()
            if corrupt is not None:
                raise EvaluationError("Build 002 offline package has a corrupt member")
            candidate_payload = candidate.read("arc3-first-party.zip")
        validation = validate_candidate_archive(paths["offline-package-candidate"])
        if validation.get("status") != "PASS":
            raise EvaluationError("Build 002 offline candidate validator did not return PASS")
    except EvaluationError:
        raise
    except (OSError, zipfile.BadZipFile) as error:
        raise EvaluationError("Build 002 offline package is not a readable ZIP") from error
    if embedded.payload != candidate_payload:
        raise EvaluationError("Build 002 notebook embeds a different first-party payload")
    if embedded.validation_parquet != paths["submission-parquet"].read_bytes():
        raise EvaluationError("Build 002 notebook embeds a different validation submission")

    preview = _load_object(paths["source-preview-contamination-receipt"])
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

    _validate_submission_file(paths["submission-parquet"])

    try:
        notices = paths["third-party-notices"].read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise EvaluationError("Build 002 third-party notices are unreadable") from error
    if not all(
        marker in notices
        for marker in (
            "# Third-party notices",
            "Competition runtime distributions",
            "License evidence",
        )
    ):
        raise EvaluationError("Build 002 third-party notices lack the required inventory")

    upstream = _load_object(paths["upstream-lock"])
    refresh = upstream.get("build_002_refresh")
    if upstream.get("schema") != "arc3.upstream-lock.v0.1" or not isinstance(refresh, dict):
        raise EvaluationError("Build 002 upstream lock schema is invalid")
    heads = refresh.get("public_repository_heads")
    hashes = refresh.get("controlling_file_sha256")
    metadata = refresh.get("kaggle_competition_metadata")
    grants = refresh.get("competition_adapter_interface_grants")
    if (
        refresh.get("schema") != "arc3.upstream-lock.build-002.v0.1"
        or not isinstance(heads, dict)
        or not {
            "arcprize/ARC-AGI",
            "arcprize/ARC-AGI-3-Agents",
            "arcprize/ARC-AGI-3-Kaggle-Starter",
            "arcprize/docs",
        }.issubset(heads)
        or not isinstance(hashes, dict)
        or len(hashes) < 8
        or not isinstance(metadata, dict)
        or metadata.get("competition_id") != 133468
        or metadata.get("internet_enabled") is not False
        or metadata.get("required_submission_file") != "submission.parquet"
        or not isinstance(grants, dict)
        or grants.get("scope") != "COMPETITION_BOUNDED only"
        or grants.get("research_mode_opaque_action_mechanism_preserved") is not True
    ):
        raise EvaluationError("Build 002 upstream lock lacks controlling source semantics")
    if metadata.get("response_sha256") != runtime.kaggle_metadata_response_sha256:
        raise EvaluationError("Build 002 Kaggle metadata identity differs across frozen sources")


def _repo_plan_path(root: Path, value: object, *, label: str) -> tuple[Path, str]:
    if not isinstance(value, str) or not value or value.strip() != value:
        raise EvaluationError(f"Build 002 run plan {label} path is malformed")
    if Path(value).is_absolute() or "\\" in value:
        raise EvaluationError(
            f"Build 002 run plan {label} must be a repository-relative POSIX path"
        )
    resolved, relative = _safe_relative(root, root / value)
    if relative != value:
        raise EvaluationError(f"Build 002 run plan {label} path is not canonical")
    return resolved, relative


def _external_plan_path(value: object, *, label: str) -> Path:
    if not isinstance(value, str) or not value or value.strip() != value:
        raise EvaluationError(f"Build 002 run plan {label} path is malformed")
    raw = Path(value)
    if not raw.is_absolute():
        raise EvaluationError(f"Build 002 run plan {label} must be an absolute path")
    resolved = raw.resolve()
    if str(resolved) != value:
        raise EvaluationError(f"Build 002 run plan {label} path is not canonical")
    return resolved


def _validate_collector_policy_binding(wrapper: Path, production_agent: Path) -> str:
    """Prove that the frozen wrapper delegates to the named production policy bytes."""

    expected = sha256_file(production_agent)
    try:
        tree = ast.parse(wrapper.read_text(encoding="utf-8"), filename=wrapper.name)
    except (OSError, UnicodeError, SyntaxError) as error:
        raise EvaluationError("Build 002 frozen collector is not readable Python") from error
    literals: list[str] = []
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if (
            isinstance(target, ast.Name)
            and target.id == "_EXPECTED_POLICY_SHA256"
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        ):
            literals.append(node.value.value)
    if literals != [expected]:
        raise EvaluationError("Build 002 collector does not bind the planned production policy")
    return expected


def _validate_run_plan_binding(
    root: Path,
    run_plan_path: Path,
    *,
    seed: int,
    manifest_path: Path,
    games: tuple[str, ...],
    gate_rows: Sequence[Mapping[str, JSONValue]],
    artifact_rows: Sequence[Mapping[str, JSONValue]],
) -> tuple[dict[str, JSONValue], dict[str, JSONValue]]:
    """Bind the exact live launcher surface to the frozen evidence graph."""

    resolved_plan, plan_relative = _safe_relative(root, run_plan_path)
    if not resolved_plan.is_file():
        raise EvaluationError("Build 002 run plan is unavailable")
    plan = _load_object(resolved_plan)
    if set(plan) != _RUN_PLAN_FIELDS or plan.get("schema") != _RUN_PLAN_SCHEMA:
        raise EvaluationError("Build 002 run plan schema or exact field set changed")
    if plan.get("seed") != seed:
        raise EvaluationError("Build 002 run plan seed differs from the freeze")

    resolved_manifest, manifest_relative = _repo_plan_path(
        root, plan.get("manifest"), label="manifest"
    )
    if resolved_manifest != manifest_path.resolve():
        raise EvaluationError("Build 002 run plan manifest differs from the freeze")

    def validate_binding_map(
        field: str,
        rows: Sequence[Mapping[str, JSONValue]],
        expected_roles: frozenset[str],
    ) -> None:
        value = plan.get(field)
        expected = {cast(str, row["role"]): cast(str, row["path"]) for row in rows}
        if not isinstance(value, dict) or set(value) != expected_roles or value != expected:
            raise EvaluationError(f"Build 002 run plan {field} differ from frozen bindings")
        for role, raw_path in value.items():
            _repo_plan_path(root, raw_path, label=f"{field}.{role}")

    validate_binding_map("gates", gate_rows, _REQUIRED_GATE_ROLES)
    validate_binding_map("artifacts", artifact_rows, _REQUIRED_ARTIFACT_ROLES)
    artifacts = _rows_by_role(artifact_rows)

    raw_assets = plan.get("assets")
    if not isinstance(raw_assets, dict) or set(raw_assets) != set(games):
        raise EvaluationError("Build 002 run plan assets differ from the exact holdout")
    inventory = _load_object(_bound_path(root, artifacts["holdout-asset-inventory"]))
    inventory_rows = inventory.get("assets")
    if not isinstance(inventory_rows, list) or len(inventory_rows) != len(games):
        raise EvaluationError("Build 002 asset inventory rows are unavailable")
    inventory_by_game: dict[str, Mapping[str, Any]] = {}
    for row in inventory_rows:
        if (
            not isinstance(row, dict)
            or set(row) != {"byte_length", "game_id", "sha256"}
            or not isinstance(row.get("game_id"), str)
        ):
            raise EvaluationError("Build 002 asset inventory row is malformed")
        inventory_by_game[cast(str, row["game_id"])] = row
    if set(inventory_by_game) != set(games):
        raise EvaluationError("Build 002 asset inventory game identities changed")
    asset_identity: dict[str, JSONValue] = {}
    for game_id in games:
        asset_path = _external_plan_path(raw_assets[game_id], label=f"assets.{game_id}")
        if not asset_path.is_file():
            raise EvaluationError(f"Build 002 planned asset is unavailable: {game_id}")
        row = inventory_by_game[game_id]
        asset_hash = sha256_file(asset_path)
        if row.get("sha256") != asset_hash or row.get("byte_length") != asset_path.stat().st_size:
            raise EvaluationError(f"Build 002 planned asset identity changed: {game_id}")
        asset_identity[game_id] = asset_hash

    production_agent, production_relative = _repo_plan_path(
        root, plan.get("production_agent"), label="production_agent"
    )
    if not production_agent.is_file():
        raise EvaluationError("Build 002 planned production policy is unavailable")
    policy_hash = _validate_collector_policy_binding(
        _bound_path(root, artifacts["agent-wrapper"]), production_agent
    )
    framework_root = _external_plan_path(plan.get("framework_root"), label="framework_root")
    if not framework_root.is_dir():
        raise EvaluationError("Build 002 planned framework root is unavailable")
    host = plan.get("gateway_host")
    port = plan.get("gateway_port")
    if (
        host not in _ALLOWED_GATEWAY_HOSTS
        or isinstance(port, bool)
        or not isinstance(port, int)
        or not 1 <= port <= 65535
    ):
        raise EvaluationError("Build 002 planned gateway endpoint is invalid")
    submission_output = _external_plan_path(
        plan.get("submission_output"), label="submission_output"
    )
    if submission_output.name != "submission.parquet":
        raise EvaluationError("Build 002 planned output is not submission.parquet")

    plan_row: dict[str, JSONValue] = {
        "byte_length": resolved_plan.stat().st_size,
        "path": plan_relative,
        "sha256": sha256_file(resolved_plan),
    }
    surface: dict[str, JSONValue] = {
        "asset_sha256": asset_identity,
        "framework_root_path_sha256": "sha256:"
        + hashlib.sha256(str(framework_root).encode("utf-8")).hexdigest(),
        "gateway_host": cast(str, host),
        "gateway_port": port,
        "manifest_path": manifest_relative,
        "production_agent_path": production_relative,
        "production_agent_sha256": policy_hash,
        "submission_output_path_sha256": "sha256:"
        + hashlib.sha256(str(submission_output).encode("utf-8")).hexdigest(),
    }
    return plan_row, surface


def create_frozen_preflight(
    root: Path,
    *,
    attempt_id: str,
    seed: int,
    manifest_path: Path,
    run_plan_path: Path,
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
    _validate_gate_receipts(resolved_root, gate_rows, artifact_rows)
    _validate_preflight_artifacts(resolved_root, artifact_rows, games)
    run_plan, execution_surface = _validate_run_plan_binding(
        resolved_root,
        run_plan_path,
        seed=seed,
        manifest_path=manifest_path,
        games=games,
        gate_rows=gate_rows,
        artifact_rows=artifact_rows,
    )
    preview_row = next(
        row for row in artifact_rows if row["role"] == "source-preview-contamination-receipt"
    )

    report: dict[str, Any] = {
        "artifacts": artifact_rows,
        "attempt_id": attempt_id,
        "authority": {
            "authorized_runs": 1,
            "consumption_boundary": "durable marker immediately before scorecard open",
            "failure_after_boundary_consumes_authority": True,
            "retry_authorized": False,
        },
        "claim_boundary": "frozen local-public preflight only; no gameplay or official score",
        "created_at": _utc_now(),
        "execution": {
            "environment_make_interactions_per_game": 1,
            "environment_order": list(games),
            "mode": "COMPETITION_BOUNDED",
            "network_mode": "competition-local-sidecar-intended-os-containment-unattested",
            "scorecard_count": 1,
            "scorecard_open_interactions": 1,
            "seed": seed,
        },
        "execution_surface": execution_surface,
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
            "os_network_containment_attested": False,
            "status": "BLOCKED_EXTERNAL",
        },
        "run_plan": run_plan,
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
        set(value) != _PREFLIGHT_FIELDS
        or value.get("schema") != PREFLIGHT_SCHEMA
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
    validated_rows: dict[str, list[Mapping[str, JSONValue]]] = {}
    for field, expected_roles, require_pass in (
        ("gates", _REQUIRED_GATE_ROLES, True),
        ("artifacts", _REQUIRED_ARTIFACT_ROLES, False),
    ):
        rows = value.get(field)
        if not isinstance(rows, list) or len(rows) != len(expected_roles):
            raise EvaluationError(f"Build 002 preflight {field} set changed")
        roles: set[str] = set()
        typed_rows: list[Mapping[str, JSONValue]] = []
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
            typed_rows.append(cast(Mapping[str, JSONValue], row))
        if roles != expected_roles:
            raise EvaluationError(f"Build 002 preflight {field} roles changed")
        validated_rows[field] = typed_rows
    _validate_gate_receipts(root, validated_rows["gates"], validated_rows["artifacts"])
    _validate_preflight_artifacts(root, validated_rows["artifacts"], manifest_games)
    run_plan_row = value.get("run_plan")
    if not isinstance(run_plan_row, dict) or set(run_plan_row) != {
        "byte_length",
        "path",
        "sha256",
    }:
        raise EvaluationError("Build 002 frozen run-plan binding is malformed")
    run_plan_path = _bound_path(root, cast(Mapping[str, JSONValue], run_plan_row))
    if run_plan_row.get("byte_length") != run_plan_path.stat().st_size or run_plan_row.get(
        "sha256"
    ) != sha256_file(run_plan_path):
        raise EvaluationError("Build 002 frozen run-plan identity changed")
    execution = value.get("execution")
    if not isinstance(execution, dict) or execution != {
        "environment_make_interactions_per_game": 1,
        "environment_order": list(manifest_games),
        "mode": "COMPETITION_BOUNDED",
        "network_mode": "competition-local-sidecar-intended-os-containment-unattested",
        "scorecard_count": 1,
        "scorecard_open_interactions": 1,
        "seed": execution.get("seed") if isinstance(execution, dict) else None,
    }:
        raise EvaluationError("Build 002 preflight execution declaration changed")
    authority = value.get("authority")
    if authority != {
        "authorized_runs": 1,
        "consumption_boundary": "durable marker immediately before scorecard open",
        "failure_after_boundary_consumes_authority": True,
        "retry_authorized": False,
    }:
        raise EvaluationError("Build 002 preflight authority declaration changed")
    if value.get("private_surface") != {
        "exact_kaggle_runtime_available": False,
        "os_network_containment_attested": False,
        "status": "BLOCKED_EXTERNAL",
    }:
        raise EvaluationError("Build 002 private execution surface boundary changed")
    seed = execution.get("seed")
    if isinstance(seed, bool) or not isinstance(seed, int) or not -(2**63) <= seed < 2**63:
        raise EvaluationError("Build 002 preflight seed is invalid")
    expected_plan_row, expected_surface = _validate_run_plan_binding(
        root,
        run_plan_path,
        seed=seed,
        manifest_path=root / cast(str, manifest["path"]),
        games=manifest_games,
        gate_rows=validated_rows["gates"],
        artifact_rows=validated_rows["artifacts"],
    )
    if run_plan_row != expected_plan_row or value.get("execution_surface") != expected_surface:
        raise EvaluationError("Build 002 live execution surface differs from the freeze")
    return manifest_games


class OneShotHoldoutSeal:
    """Durable pre-scorecard boundary and terminal result seal for one process run."""

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
        self._owns_lock = False

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
        lock_path = resolved_state / "run.lock"
        lock = seal_object(
            {
                "attempt_id": preflight.get("attempt_id"),
                "pid": os.getpid(),
                "preflight_hash": preflight.get("preflight_hash"),
                "schema": "arc3.build-002.one-shot-process-lock.v0.1",
                "started_at": _utc_now(),
                "status": "ACTIVE",
            },
            hash_field="lock_hash",
        )
        try:
            _write_once(lock_path, lock)
        except EvaluationError as error:
            raise EvaluationError(
                "another Build 002 one-shot process is active or requires recovery"
            ) from error
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
        try:
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
        except BaseException:
            lock_path.unlink(missing_ok=True)
            _fsync_parent(lock_path)
            raise
        armed = cls(resolved_root, resolved_state, preflight, games)
        armed._owns_lock = True
        return armed

    @property
    def expected_games(self) -> tuple[str, ...]:
        return self._games

    @property
    def consumed(self) -> bool:
        return self._owns_consumption

    def release_unconsumed(self) -> None:
        """Release only before the durable scorecard-open intent exists."""

        if self._owns_consumption:
            raise EvaluationError("consumed Build 002 authority cannot be released")
        if not self._owns_lock:
            return
        lock_path = self._state_root / "run.lock"
        lock_path.unlink(missing_ok=False)
        _fsync_parent(lock_path)
        self._owns_lock = False

    def _refresh_make_intents_from_durable_ledger(self) -> None:
        exposure_path = self._state_root / "exposure.jsonl"
        if not exposure_path.exists():
            self._make_intents = []
            self._previous_event_hash = None
            return
        try:
            count = len(exposure_path.read_text(encoding="utf-8").splitlines())
        except (OSError, UnicodeError) as error:
            raise EvaluationError("Build 002 exposure ledger cannot be recovered") from error
        events = _validate_exposure_chain(
            self._state_root,
            preflight_hash=self._preflight.get("preflight_hash"),
            games=self._games,
            expected_count=count,
        )
        self._make_intents = [cast(str, event["game_id"]) for event in events]
        self._previous_event_hash = cast(str, events[-1]["event_hash"]) if events else None

    def before_scorecard_open(self) -> None:
        """Consume the one-run authority directly before upstream scorecard open."""

        if not self._owns_lock:
            raise EvaluationError("Build 002 scorecard open requires the active process lock")
        if self._owns_consumption:
            raise EvaluationError("Build 002 scorecard open intent was already recorded")
        marker = seal_object(
            {
                "attempt_id": self._preflight.get("attempt_id"),
                "consumed_at": _utc_now(),
                "consumption_boundary": "scorecard.open_intent",
                "environment_make_interactions": 0,
                "failure_after_boundary_consumes_authority": True,
                "preflight_hash": self._preflight.get("preflight_hash"),
                "rerun_authorized": False,
                "schema": CONSUMPTION_SCHEMA,
                "scorecard_open_intent_count": 1,
                "status": "INTENTIONALLY_CONSUMED",
            },
            hash_field="consumption_hash",
        )
        _write_once(self._state_root / "holdout-consumed.json", marker)
        self._owns_consumption = True

    def before_environment_make(self, game_id: str, ordinal: int) -> None:
        """Persist a make intent after scorecard-open consumption."""

        if not self._owns_consumption:
            raise EvaluationError("environment make preceded the durable scorecard open intent")

        if isinstance(ordinal, bool) or not isinstance(ordinal, int):
            raise EvaluationError("environment ordinal must be an integer")
        expected_ordinal = len(self._make_intents)
        if ordinal != expected_ordinal or ordinal >= len(self._games):
            raise EvaluationError("Build 002 environment make ordinal changed")
        if game_id != self._games[ordinal]:
            raise EvaluationError("Build 002 environment make order or identity changed")
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
        peak_memory_source: str,
        result_artifacts: Sequence[ArtifactBinding],
    ) -> dict[str, Any]:
        """Validate and immutably seal the complete local-public result."""

        self._refresh_make_intents_from_durable_ledger()
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
        if peak_memory_source not in KERNEL_RSS_MEASUREMENT_SOURCES:
            raise EvaluationError("terminal peak memory source is not an accepted kernel surface")
        tournament = _validate_launch_receipt(launch_receipt, self._games)
        _validate_launch_execution_surface(launch_receipt, self._preflight)
        tournament_games = cast(list[dict[str, Any]], tournament["games"])
        for measured_game, governor_game in zip(measured, tournament_games, strict=True):
            if not math.isclose(
                measured_game.wall_seconds,
                _finite_nonnegative_number(
                    governor_game.get("elapsed_seconds"),
                    field="governor elapsed_seconds",
                ),
                rel_tol=0.0,
                abs_tol=1e-9,
            ):
                raise EvaluationError("per-game wall time differs from governor receipt")
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
            if authorized != measured_game.actions:
                raise EvaluationError("per-game actions differ from governor receipt")
            authorized_resets = governor_game.get("resets_authorized")
            if authorized_resets != measured_game.resets:
                raise EvaluationError("per-game resets differ from governor receipt")
            if governor_game.get("reason") != measured_game.stop_reason:
                raise EvaluationError("per-game stop reason differs from governor receipt")
        tournament_elapsed = _finite_nonnegative_number(
            tournament.get("elapsed_seconds"), field="tournament elapsed_seconds"
        )
        if float(total_wall_seconds) + 1e-9 < tournament_elapsed:
            raise EvaluationError("terminal wall time is below the governor tournament duration")
        if peak_memory_bytes < max(game.sampled_current_rss_max_bytes for game in measured):
            raise EvaluationError("terminal peak RSS is below a sampled per-game current RSS")
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
        _validate_result_artifact_semantics(
            self._root,
            artifacts,
            games=measured,
            launch_receipt=cast(dict[str, Any], launch),
            total_wall_seconds=float(total_wall_seconds),
            peak_memory_bytes=peak_memory_bytes,
            peak_memory_source=peak_memory_source,
        )
        _validate_terminal_status(status, measured, self._root, artifacts)
        report: dict[str, Any] = {
            "artifacts": artifacts,
            "attempt_id": self._preflight.get("attempt_id"),
            "completed_games": sum(game.completed for game in measured),
            "completed_levels": sum(game.levels_completed for game in measured),
            "consumption": _validate_consumption_marker(
                _load_object(self._state_root / "holdout-consumed.json"),
                preflight_hash=self._preflight.get("preflight_hash"),
            ),
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
            "peak_memory_measurement": TOURNAMENT_MEMORY_MEASUREMENT,
            "peak_memory_source": peak_memory_source,
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
                "local_toolkit_cross_check": "exact-from-level-action-baseline-completion-rows",
                "local_toolkit_recomputed_total": toolkit_total,
                "local_toolkit_scorer": pinned_toolkit_scorer_identity(),
                "official": False,
            },
            "source_config_artifact_hashes": self._preflight.get("artifacts"),
            "status": status,
            "surface": "local-public",
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

        self._refresh_make_intents_from_durable_ledger()
        if not self._owns_consumption:
            raise EvaluationError("an unconsumed launch is not a consumed failed attempt")
        if not isinstance(classification, FailureClassification):
            raise EvaluationError("consumed failure requires the exact Build 002 taxonomy")
        if not boundary or boundary.strip() != boundary:
            raise EvaluationError("consumed failure boundary must be canonical and non-empty")
        report: dict[str, Any] = {
            "attempt_id": self._preflight.get("attempt_id"),
            "boundary": boundary,
            "consumption": _validate_consumption_marker(
                _load_object(self._state_root / "holdout-consumed.json"),
                preflight_hash=self._preflight.get("preflight_hash"),
            ),
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


def recompute_pinned_toolkit_level_score(level: LevelMeasurement) -> float:
    """Recompute ARC-AGI 0.9.9's normalized per-level score exactly."""

    if not level.completed:
        return 0.0
    if (
        level.agent_actions is None
        or level.agent_actions <= 0
        or level.human_baseline_actions is None
        or level.human_baseline_actions <= 0
    ):
        # ``LevelMeasurement`` rejects this state. Keep the helper total so it
        # remains safe during dataclass validation.
        return 0.0
    return min((level.human_baseline_actions / level.agent_actions) ** 2, 1.15)


def recompute_pinned_toolkit_game_score(levels: Sequence[LevelMeasurement]) -> float:
    """Recompute ARC-AGI 0.9.9's normalized weighted game score exactly."""

    if not levels:
        return 0.0
    total_weight = sum(level.level_index for level in levels)
    completed_weight = sum(level.level_index for level in levels if level.completed)
    weighted_score = sum(
        level.level_index * recompute_pinned_toolkit_level_score(level) for level in levels
    )
    return min(weighted_score / total_weight, completed_weight / total_weight)


def pinned_toolkit_scorer_identity() -> dict[str, JSONValue]:
    return {
        "commit": PINNED_TOOLKIT_SCORER_COMMIT,
        "path": PINNED_TOOLKIT_SCORER_PATH,
        "repository": "arcprize/ARC-AGI",
        "sha256": PINNED_TOOLKIT_SCORER_SHA256,
    }


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


def _finite_number(value: object, *, field: str) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
    ):
        raise EvaluationError(f"{field} is not a finite number")
    return float(value)


def _validate_consumption_marker(
    marker: Mapping[str, Any], *, preflight_hash: object
) -> dict[str, Any]:
    expected_fields = {
        "attempt_id",
        "consumed_at",
        "consumption_boundary",
        "consumption_hash",
        "environment_make_interactions",
        "failure_after_boundary_consumes_authority",
        "preflight_hash",
        "rerun_authorized",
        "schema",
        "scorecard_open_intent_count",
        "status",
    }
    value = dict(marker)
    if (
        set(value) != expected_fields
        or value.get("attempt_id") != BUILD_002_ATTEMPT_ID
        or value.get("schema") != CONSUMPTION_SCHEMA
        or value.get("status") != "INTENTIONALLY_CONSUMED"
        or value.get("consumption_boundary") != "scorecard.open_intent"
        or value.get("scorecard_open_intent_count") != 1
        or value.get("environment_make_interactions") != 0
        or value.get("failure_after_boundary_consumes_authority") is not True
        or value.get("rerun_authorized") is not False
        or value.get("preflight_hash") != preflight_hash
        or not verify_object_hash(value, hash_field="consumption_hash")
    ):
        raise EvaluationError("Build 002 scorecard-open consumption marker is invalid")
    consumed_at = value.get("consumed_at")
    if not isinstance(consumed_at, str) or not consumed_at.endswith("Z"):
        raise EvaluationError("Build 002 scorecard-open consumption time is invalid")
    return value


def _validate_launch_execution_surface(
    receipt: Mapping[str, Any], preflight: Mapping[str, Any]
) -> None:
    """Bind the live launch endpoint to the endpoint frozen before consumption."""

    surface = preflight.get("execution_surface")
    if not isinstance(surface, dict):
        raise EvaluationError("Build 002 preflight execution surface is unavailable")
    if receipt.get("gateway_host") != surface.get("gateway_host") or receipt.get(
        "gateway_port"
    ) != surface.get("gateway_port"):
        raise EvaluationError("competition launch endpoint differs from frozen execution surface")


def _validate_launch_receipt(receipt: Mapping[str, Any], games: tuple[str, ...]) -> dict[str, Any]:
    expected_count = len(games)
    if set(receipt) != _LAUNCH_RECEIPT_FIELDS:
        raise EvaluationError("competition launch receipt field set changed")
    exact = {
        "agent_count": expected_count,
        "all_environments_covered": True,
        "close_scorecard_count": 1,
        "dotenv_imported": False,
        "framework_commit": _PINNED_AGENTS_COMMIT,
        "framework_fixture": False,
        "framework_identity": f"git:{_PINNED_AGENTS_COMMIT}",
        "game_count": expected_count,
        "get_scorecard_during_flight_count": 0,
        "hard_timeout_enforced": True,
        "lifecycle_enforced": True,
        "make_count": expected_count,
        "max_concurrency": 1,
        "open_scorecard_count": 1,
        "orchestration": _PINNED_ORCHESTRATION,
        "telemetry_imported": False,
        "tournament_configured": True,
        "tournament_finalized": True,
        "worker_count": expected_count,
    }
    for field, expected in exact.items():
        if receipt.get(field) != expected:
            raise EvaluationError(f"competition launch receipt violates {field}")
    discovered = receipt.get("discovered_environments")
    if discovered != games and discovered != list(games):
        raise EvaluationError("competition launch receipt environment order changed")
    host = receipt.get("gateway_host")
    port = receipt.get("gateway_port")
    notebook_start = _finite_nonnegative_number(
        receipt.get("notebook_started_at_seconds"), field="notebook start"
    )
    hard_deadline = _finite_nonnegative_number(
        receipt.get("hard_deadline_seconds"), field="hard deadline"
    )
    if (
        host not in _ALLOWED_GATEWAY_HOSTS
        or isinstance(port, bool)
        or not isinstance(port, int)
        or not 1 <= port <= 65535
        or not math.isclose(hard_deadline - notebook_start, 32370.0, abs_tol=1e-6)
    ):
        raise EvaluationError("competition launch endpoint or deadline identity changed")
    tournament_wrapper = receipt.get("tournament_receipt")
    if not isinstance(tournament_wrapper, dict) or tournament_wrapper.get("status") != "PASS":
        raise EvaluationError("competition tournament receipt is not PASS")
    tournament = tournament_wrapper.get("receipt")
    if not isinstance(tournament, dict):
        raise EvaluationError("competition tournament terminal receipt is missing")
    if set(tournament) != _TOURNAMENT_FINAL_FIELDS:
        raise EvaluationError("competition tournament terminal field set changed")
    if (
        tournament.get("expected_environments") != expected_count
        or tournament.get("finalized_environments") != expected_count
        or tournament.get("maximum_total_actions") != 80 * expected_count
        or tournament.get("maximum_resets_per_game") != 8
        or tournament.get("maximum_total_resets") != 8 * expected_count
        or tournament.get("reserve_seconds") != 6000.0
        or tournament.get("reserve_preserved") is not True
        or tournament.get("effective_ceiling_respected") is not True
        or tournament.get("outcome") != "complete-reserve-preserved"
    ):
        raise EvaluationError("competition tournament terminal invariants failed")
    game_rows = tournament.get("games")
    if (
        not isinstance(game_rows, list)
        or tuple(row.get("game_id") for row in game_rows if isinstance(row, dict)) != games
    ):
        raise EvaluationError("competition tournament game receipts differ from the freeze")
    tournament_start = _finite_nonnegative_number(
        tournament.get("started_at_seconds"), field="tournament started_at_seconds"
    )
    tournament_end = _finite_nonnegative_number(
        tournament.get("finalized_at_seconds"), field="tournament finalized_at_seconds"
    )
    tournament_elapsed = _finite_nonnegative_number(
        tournament.get("elapsed_seconds"), field="tournament elapsed_seconds"
    )
    tournament_reserve = _finite_nonnegative_number(
        tournament.get("reserve_remaining_seconds"), field="tournament reserve_remaining_seconds"
    )
    ceiling_remaining = _finite_nonnegative_number(
        tournament.get("ceiling_remaining_seconds"), field="tournament ceiling_remaining_seconds"
    )
    selected_value_total = _finite_number(
        tournament.get("selected_value_total"), field="tournament selected_value_total"
    )
    opportunity_total = _finite_nonnegative_number(
        tournament.get("future_opportunity_cost_total_seconds"),
        field="tournament future_opportunity_cost_total_seconds",
    )
    if (
        not math.isclose(tournament_start, notebook_start, rel_tol=0.0, abs_tol=1e-6)
        or tournament_end < tournament_start
        or not math.isclose(
            tournament_elapsed,
            tournament_end - tournament_start,
            rel_tol=0.0,
            abs_tol=1e-6,
        )
        or tournament_end > hard_deadline + 1e-6
        or not math.isclose(
            ceiling_remaining,
            max(0.0, notebook_start + 32400.0 - tournament_end),
            rel_tol=0.0,
            abs_tol=1e-6,
        )
        or not math.isclose(
            tournament_reserve,
            max(0.0, 6000.0 - max(0.0, tournament_elapsed - 26400.0)),
            rel_tol=0.0,
            abs_tol=1e-6,
        )
    ):
        raise EvaluationError("competition tournament timing or reserve accounting changed")
    for integer_field in (
        "sequence",
        "recent_history_receipts",
        "dropped_history_receipts",
    ):
        integer_value = tournament.get(integer_field)
        if (
            isinstance(integer_value, bool)
            or not isinstance(integer_value, int)
            or integer_value < 0
        ):
            raise EvaluationError("competition tournament receipt counters are invalid")
    total_actions = tournament.get("total_actions_authorized")
    if isinstance(total_actions, bool) or not isinstance(total_actions, int) or total_actions < 0:
        raise EvaluationError("competition tournament total action accounting is invalid")
    total_resets = tournament.get("total_resets_authorized")
    if (
        isinstance(total_resets, bool)
        or not isinstance(total_resets, int)
        or not 0 <= total_resets <= 8 * expected_count
    ):
        raise EvaluationError("competition tournament total reset accounting is invalid")
    summed_actions = 0
    summed_resets = 0
    summed_selected_value = 0.0
    summed_opportunity_seconds = 0.0
    previous_reserve = 6000.0
    previous_finalized = tournament_start
    for ordinal, row in enumerate(game_rows):
        if not isinstance(row, dict):  # pragma: no cover - excluded by identity projection above
            raise EvaluationError("competition tournament game receipt is not an object")
        if set(row) != _GAME_FINAL_FIELDS:
            raise EvaluationError("competition tournament game receipt field set changed")
        allocated = _finite_nonnegative_number(
            row.get("allocated_seconds"), field="governor allocated_seconds"
        )
        began = _finite_nonnegative_number(
            row.get("began_at_seconds"), field="governor began_at_seconds"
        )
        finalized = _finite_nonnegative_number(
            row.get("finalized_at_seconds"), field="governor finalized_at_seconds"
        )
        elapsed = _finite_nonnegative_number(
            row.get("elapsed_seconds"), field="governor elapsed_seconds"
        )
        allocation_overrun = _finite_nonnegative_number(
            row.get("allocation_overrun_seconds"), field="governor allocation_overrun_seconds"
        )
        action_elapsed = _finite_nonnegative_number(
            row.get("elapsed_action_cost_total_seconds"),
            field="governor elapsed_action_cost_total_seconds",
        )
        tail_elapsed = _finite_nonnegative_number(
            row.get("unassigned_tail_elapsed_seconds"),
            field="governor unassigned_tail_elapsed_seconds",
        )
        opportunity_seconds = _finite_nonnegative_number(
            row.get("future_opportunity_cost_total_seconds"),
            field="governor future_opportunity_cost_total_seconds",
        )
        reserve = _finite_nonnegative_number(
            row.get("reserve_remaining_seconds"),
            field="governor reserve_remaining_seconds",
        )
        _finite_nonnegative_number(
            row.get("tournament_playable_seconds_remaining"),
            field="governor tournament_playable_seconds_remaining",
        )
        selected_value = _finite_number(
            row.get("selected_value_total"), field="governor selected_value_total"
        )
        actions = row.get("actions_authorized")
        resets = row.get("resets_authorized")
        reset_limit = row.get("reset_limit")
        fallback_actions = row.get("fallback_actions")
        opportunity_actions = row.get("future_opportunity_cost_total_actions")
        row_sequence = row.get("sequence")
        reason = row.get("reason")
        if (
            isinstance(actions, bool)
            or not isinstance(actions, int)
            or not 0 <= actions <= 80
            or isinstance(resets, bool)
            or not isinstance(resets, int)
            or isinstance(reset_limit, bool)
            or not isinstance(reset_limit, int)
            or not 0 <= resets <= reset_limit <= 8
            or resets > actions
            or isinstance(fallback_actions, bool)
            or not isinstance(fallback_actions, int)
            or not 0 <= fallback_actions <= actions
            or isinstance(opportunity_actions, bool)
            or not isinstance(opportunity_actions, int)
            or not 0 <= opportunity_actions <= actions
            or (ordinal == expected_count - 1 and opportunity_actions != 0)
            or isinstance(row_sequence, bool)
            or not isinstance(row_sequence, int)
            or row_sequence <= 0
            or row.get("game_ordinal") != ordinal + 1
            or reason not in _GOVERNOR_STOP_REASONS
            or began < previous_finalized
            or finalized < began
            or allocated > 240.0
            or not math.isclose(elapsed, finalized - began, rel_tol=0.0, abs_tol=1e-6)
            or not math.isclose(
                allocation_overrun,
                max(0.0, elapsed - allocated),
                rel_tol=0.0,
                abs_tol=1e-6,
            )
            or not math.isclose(
                elapsed,
                action_elapsed + tail_elapsed,
                rel_tol=0.0,
                abs_tol=1e-6,
            )
            or reserve > previous_reserve + 1e-6
        ):
            raise EvaluationError("competition tournament game action accounting is invalid")
        summed_actions += actions
        summed_resets += resets
        summed_selected_value += selected_value
        summed_opportunity_seconds += opportunity_seconds
        previous_reserve = reserve
        previous_finalized = finalized
    if (
        total_actions != summed_actions
        or total_resets != summed_resets
        or tournament_end < previous_finalized
        or tournament_reserve > previous_reserve + 1e-6
        or not math.isclose(selected_value_total, summed_selected_value, rel_tol=0.0, abs_tol=1e-6)
        or not math.isclose(
            opportunity_total,
            summed_opportunity_seconds,
            rel_tol=0.0,
            abs_tol=1e-6,
        )
    ):
        raise EvaluationError("competition tournament aggregate accounting does not reconcile")
    return tournament


def _scorecard_game_projection(game: GameMeasurement) -> dict[str, JSONValue]:
    return {
        "actions": game.actions,
        "completed": game.completed,
        "game_id": game.game_id,
        "levels": [
            {
                "agent_actions": level.agent_actions,
                "completed": level.completed,
                "human_baseline_actions": level.human_baseline_actions,
                "level_index": level.level_index,
                "toolkit_score": float(level.toolkit_score),
            }
            for level in game.levels
        ],
        "levels_completed": game.levels_completed,
        "resets": game.resets,
        "toolkit_score": float(game.toolkit_score),
    }


def _validate_runtime_evidence_manifest(
    root: Path,
    manifest_path: Path,
    *,
    games: tuple[GameMeasurement, ...],
    launch_receipt: Mapping[str, Any],
) -> None:
    """Recompute the complete runtime inventory and bind its key raw receipts."""

    expected_path = (
        root.resolve()
        / CANONICAL_STATE_RELATIVE
        / "result-artifacts"
        / "runtime-evidence-manifest.json"
    ).resolve()
    if manifest_path.resolve() != expected_path or manifest_path.is_symlink():
        raise EvaluationError("Build 002 runtime evidence manifest path is not canonical")
    state_root = (root.resolve() / CANONICAL_STATE_RELATIVE).resolve()
    expected_game_ids = tuple(game.game_id for game in games)
    manifest = _load_object(manifest_path)
    expected_manifest = create_runtime_evidence_manifest(
        state_root,
        expected_games=expected_game_ids,
    )
    if manifest != expected_manifest:
        raise EvaluationError("Build 002 runtime evidence manifest does not recompute")

    receipt_root = state_root / "runtime" / "arc3-runtime-receipts"
    raw_scorecard = _load_object(receipt_root / "raw-local-scorecard.json")
    raw_games = raw_scorecard.get("games")
    if (
        set(raw_scorecard) != {"games", "scorer_identity", "schema", "status", "surface"}
        or raw_scorecard.get("schema") != RAW_RUNTIME_SCORECARD_SCHEMA
        or raw_scorecard.get("status") != "PASS"
        or raw_scorecard.get("surface") != "local-public"
        or raw_scorecard.get("scorer_identity") != pinned_toolkit_scorer_identity()
        or not isinstance(raw_games, list)
        or len(raw_games) != len(games)
    ):
        raise EvaluationError("Build 002 raw runtime scorecard is invalid")
    for raw_game, measured_game in zip(raw_games, games, strict=True):
        if not isinstance(raw_game, dict) or set(raw_game) != {
            "actions",
            "completed",
            "game_id",
            "levels",
            "levels_completed",
            "resets",
            "state",
            "toolkit_score",
        }:
            raise EvaluationError("Build 002 raw runtime scorecard game row is invalid")
        state = raw_game.get("state")
        if state is not None and (not isinstance(state, str) or not state):
            raise EvaluationError("Build 002 raw runtime scorecard state is invalid")
        projection = dict(raw_game)
        del projection["state"]
        if projection != _scorecard_game_projection(measured_game):
            raise EvaluationError("Build 002 raw runtime scorecard differs from terminal rows")

    tournament_wrapper = launch_receipt.get("tournament_receipt")
    tournament = tournament_wrapper.get("receipt") if isinstance(tournament_wrapper, dict) else None
    if not isinstance(tournament, dict):  # pragma: no cover - checked by launch validation first
        raise EvaluationError("Build 002 launch has no tournament receipt")
    tournament_final = _load_object(receipt_root / "tournament-final.json")
    if tournament_final != tournament:
        raise EvaluationError("Build 002 raw tournament-final receipt differs from launch")

    tournament_start = _load_object(receipt_root / "tournament-start.json")
    if set(tournament_start) != {
        "effective_ceiling_deadline_seconds",
        "expected_environments",
        "maximum_resets_per_game",
        "maximum_total_actions",
        "maximum_total_resets",
        "playable_deadline_seconds",
        "sequence",
        "started_at_seconds",
    }:
        raise EvaluationError("Build 002 raw tournament-start receipt field set changed")
    for field in (
        "expected_environments",
        "maximum_resets_per_game",
        "maximum_total_actions",
        "maximum_total_resets",
        "started_at_seconds",
    ):
        if tournament_start.get(field) != tournament.get(field):
            raise EvaluationError("Build 002 raw tournament-start receipt differs from final")

    raw_game_receipts: dict[str, dict[str, Any]] = {}
    for path in sorted(receipt_root.glob("game-*.json")):
        value = _load_object(path)
        game_id = value.get("game_id")
        if not isinstance(game_id, str) or game_id in raw_game_receipts:
            raise EvaluationError("Build 002 raw game receipt identity is invalid")
        raw_game_receipts[game_id] = value
    tournament_games = tournament.get("games")
    if not isinstance(tournament_games, list) or any(
        not isinstance(item, dict) for item in tournament_games
    ):
        raise EvaluationError("Build 002 final tournament game receipts are invalid")
    expected_game_receipts = {
        cast(str, item["game_id"]): item for item in cast(list[dict[str, Any]], tournament_games)
    }
    if any(
        expected_game_receipts.get(game_id) != value for game_id, value in raw_game_receipts.items()
    ):
        raise EvaluationError("Build 002 raw game receipts differ from final tournament")


def _validate_result_artifact_semantics(
    root: Path,
    artifact_rows: Sequence[Mapping[str, JSONValue]],
    *,
    games: tuple[GameMeasurement, ...],
    launch_receipt: Mapping[str, Any],
    total_wall_seconds: float,
    peak_memory_bytes: int,
    peak_memory_source: str,
) -> None:
    rows = _rows_by_role(artifact_rows)
    paths = {role: _bound_path(root, row) for role, row in rows.items()}
    expected_game_ids = tuple(game.game_id for game in games)

    launch_artifact = _load_object(paths["competition-launch-receipt"])
    if (
        set(launch_artifact) != {"receipt", "schema", "status"}
        or launch_artifact.get("schema") != COMPETITION_LAUNCH_ARTIFACT_SCHEMA
        or launch_artifact.get("status") != "PASS"
        or launch_artifact.get("receipt") != launch_receipt
    ):
        raise EvaluationError("Build 002 launch artifact differs from the sealed launch receipt")
    _validate_launch_receipt(launch_receipt, expected_game_ids)

    _validate_runtime_evidence_manifest(
        root,
        paths["runtime-evidence-manifest"],
        games=games,
        launch_receipt=launch_receipt,
    )

    scorecard = _load_object(paths["local-scorecard"])
    expected_scorecard = {
        "completed_games": sum(game.completed for game in games),
        "completed_levels": sum(game.levels_completed for game in games),
        "games": [_scorecard_game_projection(game) for game in games],
        "official": False,
        "schema": LOCAL_SCORECARD_SCHEMA,
        "status": "PASS",
        "surface": "local-public",
        "total_actions": sum(game.actions for game in games),
        "total_resets": sum(game.resets for game in games),
        "total_score": sum(game.toolkit_score for game in games) / len(games),
    }
    if scorecard != expected_scorecard:
        raise EvaluationError("Build 002 local scorecard disagrees with measured game rows")

    profile = _load_object(paths["execution-profile"])
    expected_profile = {
        "games": [
            {
                "game_id": game.game_id,
                "sampled_current_rss_max_bytes": game.sampled_current_rss_max_bytes,
                "wall_seconds": float(game.wall_seconds),
            }
            for game in games
        ],
        "peak_memory_bytes": peak_memory_bytes,
        "peak_memory_source": peak_memory_source,
        "per_game_memory_measurement": PER_GAME_MEMORY_MEASUREMENT,
        "schema": EXECUTION_PROFILE_SCHEMA,
        "status": "PASS",
        "total_wall_seconds": float(total_wall_seconds),
        "tournament_memory_measurement": TOURNAMENT_MEMORY_MEASUREMENT,
    }
    if profile != expected_profile:
        raise EvaluationError("Build 002 execution profile disagrees with measured runtime")

    failures = _load_object(paths["failure-receipts"])
    expected_failure_games = [
        {
            "game_id": game.game_id,
            "primary_failure": (
                game.primary_failure.value if game.primary_failure is not None else None
            ),
            "stop_reason": game.stop_reason,
        }
        for game in games
    ]
    raw_receipts = failures.get("receipts")
    if (
        set(failures) != {"games", "receipts", "schema", "status"}
        or failures.get("schema") != FAILURE_RECEIPTS_SCHEMA
        or failures.get("status") != "PASS"
        or failures.get("games") != expected_failure_games
        or not isinstance(raw_receipts, list)
    ):
        raise EvaluationError("Build 002 failure artifact disagrees with terminal classifications")
    normalized_receipts: list[dict[str, object]] = []
    for receipt in raw_receipts:
        if not isinstance(receipt, dict) or set(receipt) != {
            "boundary",
            "classification",
            "game_id",
        }:
            raise EvaluationError("Build 002 failure artifact contains a malformed receipt")
        game_id = receipt.get("game_id")
        classification = receipt.get("classification")
        boundary = receipt.get("boundary")
        if (
            game_id not in expected_game_ids
            or not isinstance(classification, str)
            or not isinstance(boundary, str)
            or not boundary
        ):
            raise EvaluationError("Build 002 failure artifact contains an invalid receipt")
        try:
            FailureClassification(classification)
        except ValueError as error:
            raise EvaluationError("Build 002 failure artifact taxonomy is invalid") from error
        normalized_receipts.append(cast(dict[str, object], receipt))
    for game in games:
        if game.primary_failure is None:
            continue
        if not any(
            receipt["game_id"] == game.game_id
            and receipt["classification"] == game.primary_failure.value
            for receipt in normalized_receipts
        ):
            raise EvaluationError("Build 002 incomplete game has no matching failure receipt")

    submission_rows = _validate_submission_file(paths["submission-parquet"])
    submission_game_ids = {row.get("game_id") for row in submission_rows}
    if submission_game_ids != set(expected_game_ids):
        raise EvaluationError("Build 002 result submission environment set is incomplete")
    for game in games:
        terminal_rows = [
            row
            for row in submission_rows
            if row.get("game_id") == game.game_id and row.get("end_of_game") is True
        ]
        if len(terminal_rows) != 1:
            raise EvaluationError("Build 002 result submission needs one terminal row per game")
        score = terminal_rows[0].get("score")
        if (
            isinstance(score, bool)
            or not isinstance(score, (int, float))
            or not math.isclose(float(score), game.toolkit_score, rel_tol=0.0, abs_tol=1e-12)
        ):
            raise EvaluationError("Build 002 result submission score disagrees with scorecard")


def _validate_terminal_status(
    status: str,
    games: Sequence[GameMeasurement],
    root: Path,
    artifact_rows: Sequence[Mapping[str, JSONValue]],
) -> None:
    """Keep PASS reserved for a fully completed run with no failure receipts."""

    if status not in {"PASS", "PARTIAL"}:
        return
    rows = _rows_by_role(artifact_rows)
    failures = _load_object(_bound_path(root, rows["failure-receipts"]))
    receipts = failures.get("receipts")
    if not isinstance(receipts, list):
        raise EvaluationError("Build 002 failure receipt list is unavailable")
    healthy = all(game.completed for game in games) and not receipts
    if (status == "PASS") != healthy:
        raise EvaluationError(
            "Build 002 terminal status disagrees with completion/failure evidence"
        )


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
    """Run the pinned lifecycle with durable callbacks before scorecard open and each make."""

    from arc3.packaging.runtime_launcher import launch_competition_framework

    try:
        return launch_competition_framework(
            framework_root,
            agent_path,
            gateway_host=gateway_host,
            gateway_port=gateway_port,
            working_root=working_root,
            allow_test_fixture=allow_test_fixture,
            before_scorecard_open=seal.before_scorecard_open,
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
            sampled_current_rss_max_bytes=value["sampled_current_rss_max_bytes"],
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


def _verify_result_artifacts(root: Path, value: object) -> list[Mapping[str, JSONValue]]:
    if not isinstance(value, list):
        raise EvaluationError("Build 002 result artifact list is invalid")
    roles: set[str] = set()
    typed_rows: list[Mapping[str, JSONValue]] = []
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
        typed_rows.append(cast(Mapping[str, JSONValue], row))
    if roles != _REQUIRED_RESULT_ARTIFACT_ROLES:
        raise EvaluationError("Build 002 result artifact role set changed")
    return typed_rows


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
    consumption = _validate_consumption_marker(
        _load_object(resolved_state / "holdout-consumed.json"),
        preflight_hash=preflight.get("preflight_hash"),
    )
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
        or result.get("surface") != "local-public"
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
    _validate_launch_execution_surface(launch, preflight)
    tournament_games = cast(list[dict[str, Any]], tournament["games"])
    for measured_game, governor_game in zip(measurements, tournament_games, strict=True):
        if not math.isclose(
            measured_game.wall_seconds,
            _finite_nonnegative_number(
                governor_game.get("elapsed_seconds"), field="governor elapsed_seconds"
            ),
            rel_tol=0.0,
            abs_tol=1e-9,
        ):
            raise EvaluationError("Build 002 result wall time disagrees with governor")
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
        if governor_game.get("actions_authorized") != measured_game.actions:
            raise EvaluationError("Build 002 result actions disagree with governor")
        if governor_game.get("resets_authorized") != measured_game.resets:
            raise EvaluationError("Build 002 result resets disagree with governor")
        if governor_game.get("reason") != measured_game.stop_reason:
            raise EvaluationError("Build 002 result stop reason disagrees with governor")
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
        "local_toolkit_cross_check": "exact-from-level-action-baseline-completion-rows",
        "local_toolkit_recomputed_total": toolkit_total,
        "local_toolkit_scorer": pinned_toolkit_scorer_identity(),
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
    total_wall_seconds = _finite_nonnegative_number(
        result.get("total_wall_seconds"), field="result wall time"
    )
    if total_wall_seconds + 1e-9 < _finite_nonnegative_number(
        tournament.get("elapsed_seconds"), field="tournament elapsed seconds"
    ):
        raise EvaluationError("Build 002 result wall time is below the governor duration")
    peak = result.get("peak_memory_bytes")
    if isinstance(peak, bool) or not isinstance(peak, int) or peak < 0:
        raise EvaluationError("Build 002 result peak memory is invalid")
    if result.get("peak_memory_measurement") != TOURNAMENT_MEMORY_MEASUREMENT:
        raise EvaluationError("Build 002 result peak memory measurement is mislabeled")
    peak_source = result.get("peak_memory_source")
    if peak_source not in KERNEL_RSS_MEASUREMENT_SOURCES:
        raise EvaluationError("Build 002 result peak memory source is invalid")
    if peak < max(measurement.sampled_current_rss_max_bytes for measurement in measurements):
        raise EvaluationError("Build 002 result peak RSS is below sampled current RSS")
    if result.get("remaining_reserve_seconds") != tournament.get("reserve_remaining_seconds"):
        raise EvaluationError("Build 002 result terminal reserve changed")
    if result.get("source_config_artifact_hashes") != preflight.get("artifacts"):
        raise EvaluationError("Build 002 result source/config/artifact freeze changed")
    if result.get("consumption") != consumption:
        raise EvaluationError("Build 002 result embedded consumption marker changed")
    artifact_rows = _verify_result_artifacts(resolved_root, result.get("artifacts"))
    _validate_result_artifact_semantics(
        resolved_root,
        artifact_rows,
        games=measurements,
        launch_receipt=launch,
        total_wall_seconds=total_wall_seconds,
        peak_memory_bytes=peak,
        peak_memory_source=cast(str, peak_source),
    )
    _validate_terminal_status(
        cast(str, result["status"]), measurements, resolved_root, artifact_rows
    )
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
    consumption = _validate_consumption_marker(
        _load_object(resolved_state / "holdout-consumed.json"),
        preflight_hash=preflight.get("preflight_hash"),
    )
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
    "RAW_RUNTIME_SCORECARD_SCHEMA",
    "RESULT_SCHEMA",
    "RUNTIME_EVIDENCE_MANIFEST_SCHEMA",
    "SOURCE_PREVIEW_SCHEMA",
    "ArtifactBinding",
    "FailureClassification",
    "GameMeasurement",
    "LevelMeasurement",
    "OneShotHoldoutSeal",
    "ReceiptBinding",
    "create_frozen_preflight",
    "create_runtime_evidence_manifest",
    "create_static_asset_inventory",
    "launch_frozen_framework_once",
    "validate_consumed_failure",
    "validate_terminal_result",
]
