"""Typed action-semantics, interaction, and coordinate-target claims."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from arc3.errors import HypothesisError
from arc3.types import JSONValue

from .base import (
    HypothesisFamily,
    normalize_object,
    normalize_string_tuple,
    normalize_strings,
    require_int,
    require_text,
)


@dataclass(frozen=True, slots=True)
class ActionSemanticsStatement:
    """Claim that an action produces a declared symbolic effect."""

    action: str
    effect: str
    parameters: dict[str, JSONValue]
    conditions: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        require_text(self.action, field="action")
        require_text(self.effect, field="effect")
        object.__setattr__(
            self,
            "parameters",
            normalize_object(self.parameters, field="action parameters"),
        )
        object.__setattr__(
            self, "conditions", normalize_strings(self.conditions, field="condition")
        )

    @property
    def family(self) -> HypothesisFamily:
        return HypothesisFamily.ACTION_SEMANTICS

    def conflict_domain(self) -> tuple[str, ...]:
        return (self.action, *self.conditions)

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "action": self.action,
            "effect": self.effect,
            "parameters": self.parameters,
            "conditions": list(self.conditions),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> ActionSemanticsStatement:
        parameters = value.get("parameters", {})
        if not isinstance(parameters, Mapping):
            raise HypothesisError("action parameters must be an object")
        return cls(
            action=require_text(value.get("action"), field="action"),
            effect=require_text(value.get("effect"), field="effect"),
            parameters=normalize_object(parameters, field="action parameters"),
            conditions=normalize_string_tuple(value.get("conditions", []), field="conditions"),
        )


@dataclass(frozen=True, slots=True)
class InteractionToggleStatement:
    """Claim that a trigger changes a persistent interaction/toggle state."""

    trigger: str
    target: str
    resulting_state: str
    conditions: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        require_text(self.trigger, field="trigger")
        require_text(self.target, field="target")
        require_text(self.resulting_state, field="resulting_state")
        object.__setattr__(
            self, "conditions", normalize_strings(self.conditions, field="condition")
        )

    @property
    def family(self) -> HypothesisFamily:
        return HypothesisFamily.INTERACTION_TOGGLE

    def conflict_domain(self) -> tuple[str, ...]:
        return (self.trigger, self.target, *self.conditions)

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "trigger": self.trigger,
            "target": self.target,
            "resulting_state": self.resulting_state,
            "conditions": list(self.conditions),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> InteractionToggleStatement:
        return cls(
            trigger=require_text(value.get("trigger"), field="trigger"),
            target=require_text(value.get("target"), field="target"),
            resulting_state=require_text(value.get("resulting_state"), field="resulting_state"),
            conditions=normalize_string_tuple(value.get("conditions", []), field="conditions"),
        )


@dataclass(frozen=True, slots=True)
class CoordinateActionTargetStatement:
    """Claim about coordinate-action targeting semantics."""

    action: str
    target_kind: str
    effect: str
    radius: int = 0
    conditions: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        require_text(self.action, field="action")
        require_text(self.target_kind, field="target_kind")
        require_text(self.effect, field="effect")
        if isinstance(self.radius, bool) or not isinstance(self.radius, int) or self.radius < 0:
            raise HypothesisError("radius must be a non-negative integer")
        object.__setattr__(
            self, "conditions", normalize_strings(self.conditions, field="condition")
        )

    @property
    def family(self) -> HypothesisFamily:
        return HypothesisFamily.COORDINATE_ACTION_TARGET

    def conflict_domain(self) -> tuple[str, ...]:
        return (self.action, self.target_kind, *self.conditions)

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "action": self.action,
            "target_kind": self.target_kind,
            "effect": self.effect,
            "radius": self.radius,
            "conditions": list(self.conditions),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> CoordinateActionTargetStatement:
        return cls(
            action=require_text(value.get("action"), field="action"),
            target_kind=require_text(value.get("target_kind"), field="target_kind"),
            effect=require_text(value.get("effect"), field="effect"),
            radius=require_int(value.get("radius", 0), field="radius"),
            conditions=normalize_string_tuple(value.get("conditions", []), field="conditions"),
        )
