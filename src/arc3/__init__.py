"""ARC3: an offline-first, evidence-preserving ARC-AGI-3 agent."""

from __future__ import annotations

from arc3.config import ARC3Config, BudgetConfig, config_hash, default_config
from arc3.types import (
    ActionName,
    EnvironmentMode,
    EvaluationSurface,
    GameStateName,
    HypothesisStatus,
    StateScope,
)

__all__ = [
    "ARC3Config",
    "ActionName",
    "BudgetConfig",
    "EnvironmentMode",
    "EvaluationSurface",
    "GameStateName",
    "HypothesisStatus",
    "StateScope",
    "config_hash",
    "default_config",
]

__version__ = "0.1.0"
