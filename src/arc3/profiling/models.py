"""Typed configuration for bounded Stage 16 measurements."""

from __future__ import annotations

import math
from dataclasses import dataclass

from arc3.competition_runtime import FROZEN_COMPETITION_RUNTIME
from arc3.config import BudgetConfig
from arc3.types import JSONValue


@dataclass(frozen=True, slots=True)
class RuntimeProfileConfig:
    """One explicit synthetic/offline controller profiling envelope."""

    seed: int = 25
    frame_size: int = 32
    fixture: str = "component-stress"
    component_count: int = 64
    max_actions: int = FROZEN_COMPETITION_RUNTIME.max_actions
    max_resets: int = FROZEN_COMPETITION_RUNTIME.max_resets
    # The frozen competition profile measures the production sparse-checkpoint
    # path. Explicit restart injection remains opt-in for recovery tests.
    restart_every: int = 0
    decision_seconds: float = FROZEN_COMPETITION_RUNTIME.decision_seconds
    wall_clock_seconds: float = FROZEN_COMPETITION_RUNTIME.per_game_wall_clock_seconds
    memory_megabytes: int = FROZEN_COMPETITION_RUNTIME.memory_megabytes
    max_trace_bytes: int = FROZEN_COMPETITION_RUNTIME.max_trace_bytes
    max_checkpoint_bytes: int = FROZEN_COMPETITION_RUNTIME.max_checkpoint_bytes
    max_coordinate_candidates: int = FROZEN_COMPETITION_RUNTIME.max_coordinate_candidates
    max_search_nodes: int = FROZEN_COMPETITION_RUNTIME.max_search_nodes
    max_search_depth: int = FROZEN_COMPETITION_RUNTIME.max_search_depth

    def __post_init__(self) -> None:
        integer_fields = {
            "frame_size": self.frame_size,
            "component_count": self.component_count,
            "max_actions": self.max_actions,
            "max_resets": self.max_resets,
            "memory_megabytes": self.memory_megabytes,
            "max_trace_bytes": self.max_trace_bytes,
            "max_checkpoint_bytes": self.max_checkpoint_bytes,
            "max_coordinate_candidates": self.max_coordinate_candidates,
            "max_search_nodes": self.max_search_nodes,
            "max_search_depth": self.max_search_depth,
        }
        for name, value in integer_fields.items():
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"{name} must be a positive integer")
        if not 3 <= self.frame_size <= 64:
            raise ValueError("frame_size must be within 3..64")
        if self.fixture not in {"component-stress", "navigation"}:
            raise ValueError("fixture must be 'component-stress' or 'navigation'")
        if (
            self.fixture == "component-stress"
            and self.component_count > (self.frame_size // 2) ** 2
        ):
            raise ValueError("component_count does not fit the separated-component fixture")
        if (
            isinstance(self.restart_every, bool)
            or not isinstance(self.restart_every, int)
            or self.restart_every < 0
        ):
            raise ValueError("restart_every must be a non-negative integer")
        if (
            isinstance(self.seed, bool)
            or not isinstance(self.seed, int)
            or not -(2**63) <= self.seed < 2**63
        ):
            raise ValueError("seed must be a signed 64-bit integer")
        for name, float_value in {
            "decision_seconds": self.decision_seconds,
            "wall_clock_seconds": self.wall_clock_seconds,
        }.items():
            if isinstance(float_value, bool) or not math.isfinite(float_value) or float_value <= 0:
                raise ValueError(f"{name} must be a finite positive number")

    def budgets(self) -> BudgetConfig:
        """Return the production controller budget represented by this profile."""

        return BudgetConfig(
            max_actions=self.max_actions,
            max_resets=self.max_resets,
            decision_seconds=self.decision_seconds,
            wall_clock_seconds=self.wall_clock_seconds,
            memory_megabytes=self.memory_megabytes,
            max_coordinate_candidates=self.max_coordinate_candidates,
            max_search_nodes=self.max_search_nodes,
            max_search_depth=self.max_search_depth,
            max_trace_bytes=self.max_trace_bytes,
        )

    def to_dict(self) -> dict[str, JSONValue]:
        """Return the complete deterministic measurement declaration."""

        return {
            "decision_seconds": self.decision_seconds,
            "component_count": self.component_count,
            "fixture": self.fixture,
            "frame_size": self.frame_size,
            "max_actions": self.max_actions,
            "max_coordinate_candidates": self.max_coordinate_candidates,
            "max_resets": self.max_resets,
            "max_checkpoint_bytes": self.max_checkpoint_bytes,
            "max_search_depth": self.max_search_depth,
            "max_search_nodes": self.max_search_nodes,
            "max_trace_bytes": self.max_trace_bytes,
            "memory_megabytes": self.memory_megabytes,
            "restart_every": self.restart_every,
            "seed": self.seed,
            "wall_clock_seconds": self.wall_clock_seconds,
        }


__all__ = ["RuntimeProfileConfig"]
