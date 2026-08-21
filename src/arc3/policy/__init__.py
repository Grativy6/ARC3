"""Policy interfaces and deterministic baseline implementations."""

from __future__ import annotations

from typing import Protocol

from arc3.adapters import Observation
from arc3.types import ActionRequest


class Policy(Protocol):
    """Minimal policy boundary: select one action from one observation."""

    def select(self, observation: Observation) -> ActionRequest:
        """Return one normalized action without touching the environment."""


from arc3.policy.baselines import (  # noqa: E402
    ActionCyclePolicy,
    CoordinateSweepPolicy,
    RandomValidPolicy,
    make_baseline,
)

__all__ = [
    "ActionCyclePolicy",
    "CoordinateSweepPolicy",
    "Policy",
    "RandomValidPolicy",
    "make_baseline",
]
