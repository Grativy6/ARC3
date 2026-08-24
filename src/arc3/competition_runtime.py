"""Validated, versioned competition runtime declaration shared by all entrypoints."""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlparse

from arc3.competition import TournamentGovernorConfig
from arc3.config import BudgetConfig, RuntimePolicyConfig
from arc3.types import ExecutionMode, JSONValue

COMPETITION_RUNTIME_SCHEMA = "arc3.competition-runtime.v0.1"
BUILD_002_COMPETITION_RUNTIME_SCHEMA = "arc3.competition-runtime.v0.2"
_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
_KAGGLE_METADATA_URL = (
    "https://www.kaggle.com/api/i/competitions.CompetitionService/GetCompetition"
    "?competitionName=arc-prize-2026-arc-agi-3"
)


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


@dataclass(frozen=True, slots=True)
class CompetitionRuntimeConfig:
    """Frozen tournament, controller, and persistence limits with source identity."""

    schema: str
    execution_mode: str
    allocator_tracing_enabled: bool
    automatic_per_action_checkpoints: bool
    sparse_checkpoint_interval_actions: int
    compact_trace_capacity: int
    max_actions: int
    max_resets: int
    decision_seconds: float
    per_game_wall_clock_seconds: float
    minimum_fallback_seconds: float
    memory_megabytes: int
    max_trace_bytes: int
    max_checkpoint_bytes: int
    max_coordinate_candidates: int
    max_search_nodes: int
    max_search_depth: int
    max_total_actions: int
    official_total_runtime_seconds: int
    generic_notebook_ceiling_seconds: int
    official_evaluation_games: int
    reserved_non_game_seconds: int
    kaggle_competition_id: int
    kaggle_metadata_url: str
    kaggle_metadata_accessed_at: str
    kaggle_metadata_response_sha256: str
    execution_backend: str
    rationale: str
    configuration_sha256: str

    def __post_init__(self) -> None:
        for name in (
            "schema",
            "execution_mode",
            "kaggle_metadata_url",
            "kaggle_metadata_accessed_at",
            "kaggle_metadata_response_sha256",
            "execution_backend",
            "rationale",
            "configuration_sha256",
        ):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be a non-empty string")
        for name in ("allocator_tracing_enabled", "automatic_per_action_checkpoints"):
            if not isinstance(getattr(self, name), bool):
                raise ValueError(f"{name} must be a boolean")
        if self.schema != BUILD_002_COMPETITION_RUNTIME_SCHEMA:
            raise ValueError("competition runtime schema is unsupported")
        if self.execution_mode != ExecutionMode.COMPETITION_BOUNDED.value:
            raise ValueError("competition runtime execution mode is unsupported")
        if self.allocator_tracing_enabled or self.automatic_per_action_checkpoints:
            raise ValueError("bounded competition runtime must disable measured hot-path costs")
        integer_fields = {
            "compact_trace_capacity": self.compact_trace_capacity,
            "generic_notebook_ceiling_seconds": self.generic_notebook_ceiling_seconds,
            "kaggle_competition_id": self.kaggle_competition_id,
            "max_actions": self.max_actions,
            "max_checkpoint_bytes": self.max_checkpoint_bytes,
            "max_coordinate_candidates": self.max_coordinate_candidates,
            "max_resets": self.max_resets,
            "max_search_depth": self.max_search_depth,
            "max_search_nodes": self.max_search_nodes,
            "max_total_actions": self.max_total_actions,
            "max_trace_bytes": self.max_trace_bytes,
            "memory_megabytes": self.memory_megabytes,
            "official_evaluation_games": self.official_evaluation_games,
            "official_total_runtime_seconds": self.official_total_runtime_seconds,
            "reserved_non_game_seconds": self.reserved_non_game_seconds,
            "sparse_checkpoint_interval_actions": self.sparse_checkpoint_interval_actions,
        }
        for name, value in integer_fields.items():
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"{name} must be a positive integer")
        for numeric_name, numeric_value in {
            "decision_seconds": self.decision_seconds,
            "minimum_fallback_seconds": self.minimum_fallback_seconds,
            "per_game_wall_clock_seconds": self.per_game_wall_clock_seconds,
        }.items():
            if (
                isinstance(numeric_value, bool)
                or not isinstance(numeric_value, (int, float))
                or not math.isfinite(numeric_value)
                or numeric_value <= 0
            ):
                raise ValueError(f"{numeric_name} must be finite and positive")
        if self.execution_backend != "cpu":
            raise ValueError("competition execution_backend must be cpu")
        if self.kaggle_competition_id != 133468:
            raise ValueError("competition runtime names an unexpected Kaggle competition")
        if self.kaggle_metadata_url != _KAGGLE_METADATA_URL:
            raise ValueError("competition runtime metadata URL is not the pinned official URL")
        parsed_url = urlparse(self.kaggle_metadata_url)
        if parsed_url.scheme != "https" or parsed_url.hostname != "www.kaggle.com":
            raise ValueError("competition runtime metadata URL is not HTTPS Kaggle")
        try:
            accessed_at = datetime.fromisoformat(
                self.kaggle_metadata_accessed_at.replace("Z", "+00:00")
            )
        except ValueError as error:
            raise ValueError("kaggle_metadata_accessed_at is not ISO-8601") from error
        if accessed_at.tzinfo is None:
            raise ValueError("kaggle_metadata_accessed_at must include a timezone")
        for hash_name, hash_value in (
            ("configuration_sha256", self.configuration_sha256),
            ("kaggle_metadata_response_sha256", self.kaggle_metadata_response_sha256),
        ):
            if _SHA256.fullmatch(hash_value) is None:
                raise ValueError(f"{hash_name} must be a tagged lowercase SHA-256")
        if self.official_total_runtime_seconds >= self.generic_notebook_ceiling_seconds:
            raise ValueError("competition-specific runtime must be stricter than generic ceiling")
        if self.reserved_non_game_seconds >= self.official_total_runtime_seconds:
            raise ValueError("runtime reserve must be below the competition-specific ceiling")
        if (
            self.per_game_wall_clock_seconds * self.official_evaluation_games
            + self.reserved_non_game_seconds
            > self.official_total_runtime_seconds
        ):
            raise ValueError("maximum per-game allocations plus reserve exceed the total runtime")
        if self.max_total_actions < self.max_actions * self.official_evaluation_games:
            raise ValueError("total action budget cannot cover each configured environment")
        if self.runtime_policy() != RuntimePolicyConfig.competition_bounded():
            raise ValueError("runtime persistence policy differs from the frozen bounded policy")

    def runtime_policy(self) -> RuntimePolicyConfig:
        """Return the exact controller execution-cost policy."""

        return RuntimePolicyConfig(
            allocator_tracing_enabled=self.allocator_tracing_enabled,
            automatic_per_action_checkpoints=self.automatic_per_action_checkpoints,
            sparse_checkpoint_interval_actions=self.sparse_checkpoint_interval_actions,
            compact_trace_capacity=self.compact_trace_capacity,
        )

    def budgets(self) -> BudgetConfig:
        """Build the maximum per-game production controller budget."""

        return BudgetConfig(
            max_actions=self.max_actions,
            max_resets=self.max_resets,
            decision_seconds=self.decision_seconds,
            wall_clock_seconds=self.per_game_wall_clock_seconds,
            memory_megabytes=self.memory_megabytes,
            max_coordinate_candidates=self.max_coordinate_candidates,
            max_search_nodes=self.max_search_nodes,
            max_search_depth=self.max_search_depth,
            max_trace_bytes=self.max_trace_bytes,
        )

    def governor_config(self, expected_environments: int) -> TournamentGovernorConfig:
        """Bind global limits to the gateway's exact discovered environment count."""

        if expected_environments <= 0 or expected_environments > self.official_evaluation_games:
            raise ValueError("discovered environment count is outside the official bound")
        return TournamentGovernorConfig(
            expected_environments=expected_environments,
            total_effective_ceiling_seconds=self.official_total_runtime_seconds,
            reserve_seconds=self.reserved_non_game_seconds,
            minimum_fallback_seconds=self.minimum_fallback_seconds,
            maximum_game_seconds=self.per_game_wall_clock_seconds,
            maximum_actions_per_game=self.max_actions,
            maximum_total_actions=min(
                self.max_total_actions,
                self.max_actions * expected_environments,
            ),
            history_capacity=max(self.compact_trace_capacity, expected_environments * 4),
        )

    def to_dict(self) -> dict[str, JSONValue]:
        """Return the complete validated declaration including content identity."""

        normalized = json.loads(_canonical_bytes(asdict(self)))
        return cast(dict[str, JSONValue], normalized)


def load_competition_runtime(path: Path | None = None) -> CompetitionRuntimeConfig:
    """Load and content-verify the frozen Build 002 declaration."""

    source = path or Path(__file__).with_name("competition-runtime.v0.2.json")
    raw_object: object = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(raw_object, dict):
        raise ValueError("competition runtime declaration must be a JSON object")
    raw = cast(dict[str, object], raw_object)
    expected_keys = set(CompetitionRuntimeConfig.__dataclass_fields__)
    if set(raw) != expected_keys:
        raise ValueError("competition runtime declaration keys do not match the schema")
    claimed = raw.get("configuration_sha256")
    body = {key: value for key, value in raw.items() if key != "configuration_sha256"}
    actual = f"sha256:{hashlib.sha256(_canonical_bytes(body)).hexdigest()}"
    if claimed != actual:
        raise ValueError("competition runtime configuration hash mismatch")
    try:
        return CompetitionRuntimeConfig(**cast(dict[str, Any], raw))
    except TypeError as error:
        raise ValueError(f"competition runtime declaration has invalid types: {error}") from error


FROZEN_COMPETITION_RUNTIME = load_competition_runtime()

__all__ = [
    "BUILD_002_COMPETITION_RUNTIME_SCHEMA",
    "COMPETITION_RUNTIME_SCHEMA",
    "FROZEN_COMPETITION_RUNTIME",
    "CompetitionRuntimeConfig",
    "load_competition_runtime",
]
