"""Validated configuration values for the Stage 13 evaluation harness."""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class EvaluationConfig:
    """One deterministic, bounded synthetic batch declaration."""

    partition: str
    agents: tuple[str, ...]
    seeds: tuple[int, ...]
    max_actions: int = 100
    max_resets: int = 8
    timeout_seconds: float = 30.0
    output_root: Path = Path("artifacts/evaluations")
    evaluation_id: str | None = None

    def __post_init__(self) -> None:
        if self.partition != "smoke":
            raise ValueError("Stage 13 currently supports only the synthetic smoke partition")
        if not self.agents or len(set(self.agents)) != len(self.agents):
            raise ValueError("agents must be a non-empty list without duplicates")
        if not self.seeds or len(set(self.seeds)) != len(self.seeds):
            raise ValueError("seeds must be a non-empty list without duplicates")
        if any(
            isinstance(seed, bool) or not isinstance(seed, int) or not -(2**63) <= seed < 2**63
            for seed in self.seeds
        ):
            raise ValueError("every seed must be a signed 64-bit integer")
        if (
            isinstance(self.max_actions, bool)
            or not isinstance(self.max_actions, int)
            or self.max_actions <= 0
        ):
            raise ValueError("max_actions must be a positive integer")
        if (
            isinstance(self.max_resets, bool)
            or not isinstance(self.max_resets, int)
            or self.max_resets <= 0
        ):
            raise ValueError("max_resets must be a positive integer")
        if (
            isinstance(self.timeout_seconds, bool)
            or not isinstance(self.timeout_seconds, (int, float))
            or not math.isfinite(self.timeout_seconds)
            or self.timeout_seconds <= 0
        ):
            raise ValueError("timeout_seconds must be a finite positive number")
        if self.evaluation_id is not None and (
            not self.evaluation_id
            or any(
                char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_"
                for char in self.evaluation_id
            )
        ):
            raise ValueError(
                "evaluation_id may contain only letters, digits, hyphens, and underscores"
            )

    def declaration(self) -> dict[str, object]:
        return {
            "partition": self.partition,
            "agents": list(self.agents),
            "seeds": list(self.seeds),
            "max_actions": self.max_actions,
            "max_resets": self.max_resets,
            "timeout_seconds": self.timeout_seconds,
            "surface": "synthetic",
            "network_mode": "offline",
        }


@dataclass(frozen=True, slots=True)
class EvaluationOutcome:
    """Paths and compact status returned by a completed batch invocation."""

    evaluation_id: str
    directory: Path
    status: str
    summary: dict[str, object]


__all__ = ["EvaluationConfig", "EvaluationOutcome"]
