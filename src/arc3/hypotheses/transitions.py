"""Typed transition, terminal-progress, and cross-level invariant claims."""

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
class StateTransitionStatement:
    """Claim mapping symbolic preconditions and an action to effects."""

    action: str
    preconditions: tuple[str, ...]
    effects: tuple[str, ...]

    def __post_init__(self) -> None:
        require_text(self.action, field="action")
        effects = normalize_strings(self.effects, field="effect")
        if not effects:
            raise HypothesisError("state-transition statements require an effect")
        object.__setattr__(
            self,
            "preconditions",
            normalize_strings(self.preconditions, field="precondition"),
        )
        object.__setattr__(self, "effects", effects)

    @property
    def family(self) -> HypothesisFamily:
        return HypothesisFamily.STATE_TRANSITION

    def conflict_domain(self) -> tuple[str, ...]:
        return (self.action, *self.preconditions)

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "action": self.action,
            "preconditions": list(self.preconditions),
            "effects": list(self.effects),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> StateTransitionStatement:
        return cls(
            action=require_text(value.get("action"), field="action"),
            preconditions=normalize_string_tuple(
                value.get("preconditions", []), field="preconditions"
            ),
            effects=normalize_string_tuple(value.get("effects"), field="effects"),
        )


@dataclass(frozen=True, slots=True)
class ProgressTerminalStatement:
    """Claim connecting an observable condition to progress or termination."""

    condition: str
    outcome: str
    terminal: bool
    indicators: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        require_text(self.condition, field="condition")
        require_text(self.outcome, field="outcome")
        if not isinstance(self.terminal, bool):
            raise HypothesisError("terminal must be a boolean")
        object.__setattr__(
            self, "indicators", normalize_strings(self.indicators, field="indicator")
        )

    @property
    def family(self) -> HypothesisFamily:
        return HypothesisFamily.PROGRESS_TERMINAL

    def conflict_domain(self) -> tuple[str, ...]:
        return (self.condition,)

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "condition": self.condition,
            "outcome": self.outcome,
            "terminal": self.terminal,
            "indicators": list(self.indicators),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> ProgressTerminalStatement:
        terminal = value.get("terminal")
        if not isinstance(terminal, bool):
            raise HypothesisError("terminal must be a boolean")
        return cls(
            condition=require_text(value.get("condition"), field="condition"),
            outcome=require_text(value.get("outcome"), field="outcome"),
            terminal=terminal,
            indicators=normalize_string_tuple(value.get("indicators", []), field="indicators"),
        )


@dataclass(frozen=True, slots=True)
class LevelInvariantStatement:
    """Claim that an abstract relation persists across levels."""

    invariant: str
    roles: tuple[str, ...]
    exceptions: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        require_text(self.invariant, field="invariant")
        roles = normalize_strings(self.roles, field="role")
        if not roles:
            raise HypothesisError("level invariant requires at least one abstract role")
        object.__setattr__(self, "roles", roles)
        object.__setattr__(
            self, "exceptions", normalize_strings(self.exceptions, field="exception")
        )

    @property
    def family(self) -> HypothesisFamily:
        return HypothesisFamily.LEVEL_INVARIANT

    def conflict_domain(self) -> tuple[str, ...]:
        return self.roles

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "invariant": self.invariant,
            "roles": list(self.roles),
            "exceptions": list(self.exceptions),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> LevelInvariantStatement:
        return cls(
            invariant=require_text(value.get("invariant"), field="invariant"),
            roles=normalize_string_tuple(value.get("roles"), field="roles"),
            exceptions=normalize_string_tuple(value.get("exceptions", []), field="exceptions"),
        )
