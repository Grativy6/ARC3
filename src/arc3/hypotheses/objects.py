"""Typed object-identity and collision/traversability claims."""

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
class ControllableObjectStatement:
    """Claim that a tracked object is controlled under declared cues."""

    object_id: str
    identity_cues: tuple[str, ...]
    response_actions: tuple[str, ...]

    def __post_init__(self) -> None:
        require_text(self.object_id, field="object_id")
        cues = normalize_strings(self.identity_cues, field="identity cue")
        actions = normalize_strings(self.response_actions, field="response action")
        if not cues:
            raise HypothesisError("controllable-object identity requires at least one cue")
        if not actions:
            raise HypothesisError("controllable-object identity requires a response action")
        object.__setattr__(self, "identity_cues", cues)
        object.__setattr__(self, "response_actions", actions)

    @property
    def family(self) -> HypothesisFamily:
        return HypothesisFamily.CONTROLLABLE_OBJECT_IDENTITY

    def conflict_domain(self) -> tuple[str, ...]:
        return (*self.response_actions,)

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "object_id": self.object_id,
            "identity_cues": list(self.identity_cues),
            "response_actions": list(self.response_actions),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> ControllableObjectStatement:
        return cls(
            object_id=require_text(value.get("object_id"), field="object_id"),
            identity_cues=normalize_string_tuple(value.get("identity_cues"), field="identity_cues"),
            response_actions=normalize_string_tuple(
                value.get("response_actions"), field="response_actions"
            ),
        )


@dataclass(frozen=True, slots=True)
class CollisionTraversabilityStatement:
    """Claim that one object class can or cannot traverse another."""

    moving_kind: str
    obstacle_kind: str
    traversable: bool
    consequence: str
    conditions: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        require_text(self.moving_kind, field="moving_kind")
        require_text(self.obstacle_kind, field="obstacle_kind")
        if not isinstance(self.traversable, bool):
            raise HypothesisError("traversable must be a boolean")
        require_text(self.consequence, field="consequence")
        object.__setattr__(
            self, "conditions", normalize_strings(self.conditions, field="condition")
        )

    @property
    def family(self) -> HypothesisFamily:
        return HypothesisFamily.COLLISION_TRAVERSABILITY

    def conflict_domain(self) -> tuple[str, ...]:
        return (self.moving_kind, self.obstacle_kind, *self.conditions)

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "moving_kind": self.moving_kind,
            "obstacle_kind": self.obstacle_kind,
            "traversable": self.traversable,
            "consequence": self.consequence,
            "conditions": list(self.conditions),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> CollisionTraversabilityStatement:
        traversable = value.get("traversable")
        if not isinstance(traversable, bool):
            raise HypothesisError("traversable must be a boolean")
        return cls(
            moving_kind=require_text(value.get("moving_kind"), field="moving_kind"),
            obstacle_kind=require_text(value.get("obstacle_kind"), field="obstacle_kind"),
            traversable=traversable,
            consequence=require_text(value.get("consequence"), field="consequence"),
            conditions=normalize_string_tuple(value.get("conditions", []), field="conditions"),
        )
