"""Typed candidate-goal claims kept distinct from action permission."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from arc3.errors import HypothesisError
from arc3.types import JSONValue

from .base import (
    HypothesisFamily,
    normalize_string_tuple,
    normalize_strings,
    require_text,
)


@dataclass(frozen=True, slots=True)
class CandidateGoalStatement:
    """Claim that a symbolic state is externally desirable.

    This record carries evidence-relevant structure only; it grants no
    permission to act and is not itself a plan.
    """

    objective: str
    target_state: str
    progress_indicators: tuple[str, ...]
    terminal_indicators: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        require_text(self.objective, field="objective")
        require_text(self.target_state, field="target_state")
        indicators = normalize_strings(self.progress_indicators, field="progress indicator")
        if not indicators:
            raise HypothesisError("candidate goal requires a progress indicator")
        object.__setattr__(self, "progress_indicators", indicators)
        object.__setattr__(
            self,
            "terminal_indicators",
            normalize_strings(self.terminal_indicators, field="terminal indicator"),
        )

    @property
    def family(self) -> HypothesisFamily:
        return HypothesisFamily.CANDIDATE_GOAL

    def conflict_domain(self) -> tuple[str, ...]:
        return (self.objective,)

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "objective": self.objective,
            "target_state": self.target_state,
            "progress_indicators": list(self.progress_indicators),
            "terminal_indicators": list(self.terminal_indicators),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> CandidateGoalStatement:
        return cls(
            objective=require_text(value.get("objective"), field="objective"),
            target_state=require_text(value.get("target_state"), field="target_state"),
            progress_indicators=normalize_string_tuple(
                value.get("progress_indicators"), field="progress_indicators"
            ),
            terminal_indicators=normalize_string_tuple(
                value.get("terminal_indicators", []), field="terminal_indicators"
            ),
        )
