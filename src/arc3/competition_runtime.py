"""Validated, versioned competition runtime declaration shared by all entrypoints."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from arc3.config import BudgetConfig
from arc3.types import JSONValue

COMPETITION_RUNTIME_SCHEMA = "arc3.competition-runtime.v0.1"


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
    """Frozen offline evaluation budget and its public-rule accounting."""

    schema: str
    max_actions: int
    max_resets: int
    decision_seconds: float
    per_game_wall_clock_seconds: float
    memory_megabytes: int
    max_trace_bytes: int
    max_checkpoint_bytes: int
    max_coordinate_candidates: int
    max_search_nodes: int
    max_search_depth: int
    official_total_runtime_seconds: int
    official_evaluation_games: int
    reserved_non_game_seconds: int
    execution_backend: str
    rationale: str
    configuration_sha256: str

    def __post_init__(self) -> None:
        if self.schema != COMPETITION_RUNTIME_SCHEMA:
            raise ValueError("competition runtime schema is unsupported")
        integer_fields = {
            "max_actions": self.max_actions,
            "max_resets": self.max_resets,
            "memory_megabytes": self.memory_megabytes,
            "max_trace_bytes": self.max_trace_bytes,
            "max_checkpoint_bytes": self.max_checkpoint_bytes,
            "max_coordinate_candidates": self.max_coordinate_candidates,
            "max_search_nodes": self.max_search_nodes,
            "max_search_depth": self.max_search_depth,
            "official_total_runtime_seconds": self.official_total_runtime_seconds,
            "official_evaluation_games": self.official_evaluation_games,
            "reserved_non_game_seconds": self.reserved_non_game_seconds,
        }
        for name, value in integer_fields.items():
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"{name} must be a positive integer")
        for name, float_value in {
            "decision_seconds": self.decision_seconds,
            "per_game_wall_clock_seconds": self.per_game_wall_clock_seconds,
        }.items():
            if isinstance(float_value, bool) or not math.isfinite(float_value) or float_value <= 0:
                raise ValueError(f"{name} must be finite and positive")
        if self.execution_backend != "cpu":
            raise ValueError("v0.1 competition execution_backend must be cpu")
        if not self.rationale.strip():
            raise ValueError("competition runtime rationale must not be empty")
        game_seconds = self.per_game_wall_clock_seconds * self.official_evaluation_games
        if game_seconds + self.reserved_non_game_seconds > self.official_total_runtime_seconds:
            raise ValueError("per-game runtime plus reserve exceeds the official total runtime")

    def budgets(self) -> BudgetConfig:
        """Build the exact production controller budget."""

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

    def to_dict(self) -> dict[str, JSONValue]:
        """Return the validated declaration including its content identity."""

        return {
            "configuration_sha256": self.configuration_sha256,
            "decision_seconds": self.decision_seconds,
            "execution_backend": self.execution_backend,
            "max_actions": self.max_actions,
            "max_checkpoint_bytes": self.max_checkpoint_bytes,
            "max_coordinate_candidates": self.max_coordinate_candidates,
            "max_resets": self.max_resets,
            "max_search_depth": self.max_search_depth,
            "max_search_nodes": self.max_search_nodes,
            "max_trace_bytes": self.max_trace_bytes,
            "memory_megabytes": self.memory_megabytes,
            "official_evaluation_games": self.official_evaluation_games,
            "official_total_runtime_seconds": self.official_total_runtime_seconds,
            "per_game_wall_clock_seconds": self.per_game_wall_clock_seconds,
            "rationale": self.rationale,
            "reserved_non_game_seconds": self.reserved_non_game_seconds,
            "schema": self.schema,
        }


def load_competition_runtime(path: Path | None = None) -> CompetitionRuntimeConfig:
    """Load and content-verify the frozen declaration."""

    source = path or Path(__file__).with_name("competition-runtime.v0.1.json")
    raw_object: object = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(raw_object, dict):
        raise ValueError("competition runtime declaration must be a JSON object")
    raw = cast(dict[str, object], raw_object)
    expected_keys = {
        "configuration_sha256",
        "decision_seconds",
        "execution_backend",
        "max_actions",
        "max_checkpoint_bytes",
        "max_coordinate_candidates",
        "max_resets",
        "max_search_depth",
        "max_search_nodes",
        "max_trace_bytes",
        "memory_megabytes",
        "official_evaluation_games",
        "official_total_runtime_seconds",
        "per_game_wall_clock_seconds",
        "rationale",
        "reserved_non_game_seconds",
        "schema",
    }
    if set(raw) != expected_keys:
        raise ValueError("competition runtime declaration keys do not match the schema")
    integer_names = {
        "max_actions",
        "max_checkpoint_bytes",
        "max_coordinate_candidates",
        "max_resets",
        "max_search_depth",
        "max_search_nodes",
        "max_trace_bytes",
        "memory_megabytes",
        "official_evaluation_games",
        "official_total_runtime_seconds",
        "reserved_non_game_seconds",
    }
    if any(type(raw[name]) is not int for name in integer_names):
        raise ValueError("competition runtime integer field has an invalid type")
    number_names = {"decision_seconds", "per_game_wall_clock_seconds"}
    if any(type(raw[name]) not in {int, float} for name in number_names):
        raise ValueError("competition runtime numeric field has an invalid type")
    string_names = {
        "configuration_sha256",
        "execution_backend",
        "rationale",
        "schema",
    }
    if any(type(raw[name]) is not str for name in string_names):
        raise ValueError("competition runtime string field has an invalid type")
    claimed = raw.get("configuration_sha256")
    body = {key: value for key, value in raw.items() if key != "configuration_sha256"}
    actual = f"sha256:{hashlib.sha256(_canonical_bytes(body)).hexdigest()}"
    if claimed != actual:
        raise ValueError("competition runtime configuration hash mismatch")
    return CompetitionRuntimeConfig(
        schema=cast(str, raw["schema"]),
        max_actions=cast(int, raw["max_actions"]),
        max_resets=cast(int, raw["max_resets"]),
        decision_seconds=float(cast(float | int, raw["decision_seconds"])),
        per_game_wall_clock_seconds=float(cast(float | int, raw["per_game_wall_clock_seconds"])),
        memory_megabytes=cast(int, raw["memory_megabytes"]),
        max_trace_bytes=cast(int, raw["max_trace_bytes"]),
        max_checkpoint_bytes=cast(int, raw["max_checkpoint_bytes"]),
        max_coordinate_candidates=cast(int, raw["max_coordinate_candidates"]),
        max_search_nodes=cast(int, raw["max_search_nodes"]),
        max_search_depth=cast(int, raw["max_search_depth"]),
        official_total_runtime_seconds=cast(int, raw["official_total_runtime_seconds"]),
        official_evaluation_games=cast(int, raw["official_evaluation_games"]),
        reserved_non_game_seconds=cast(int, raw["reserved_non_game_seconds"]),
        execution_backend=cast(str, raw["execution_backend"]),
        rationale=cast(str, raw["rationale"]),
        configuration_sha256=claimed,
    )


FROZEN_COMPETITION_RUNTIME = load_competition_runtime()

__all__ = [
    "COMPETITION_RUNTIME_SCHEMA",
    "FROZEN_COMPETITION_RUNTIME",
    "CompetitionRuntimeConfig",
    "load_competition_runtime",
]
