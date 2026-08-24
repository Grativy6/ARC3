"""Typed values for the bounded BLA mechanical learner.

The module deliberately separates a missing prediction (``UNKNOWN``) from a
prediction that a channel has no effects (known-empty).  Every consequence
vector contains every channel so callers cannot accidentally omit an
unobserved part of an action's consequence.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, replace
from enum import StrEnum
from typing import Self

from arc3.errors import ARC3ValidationError
from arc3.trace.canonical import canonical_json, normalize_json, sha256_json
from arc3.types import ActionName, GameStateName, JSONValue


class MechanicsError(ARC3ValidationError):
    """A mechanic value, transition, or bounded operation is invalid."""


class KnowledgeState(StrEnum):
    """Whether a consequence channel has an asserted value."""

    UNKNOWN = "unknown"
    KNOWN = "known"


class ConsequenceChannel(StrEnum):
    """The complete, fixed factorization of one action consequence."""

    CONTROLLED_DISPLACEMENT = "controlled_displacement"
    OTHER_OBJECT_EFFECTS = "other_object_effects"
    RESOURCE_CHANGES = "resource_changes"
    INVENTORY_CHANGES = "inventory_changes"
    LEGAL_ACTION_CHANGES = "legal_action_changes"
    TOPOLOGY_CHANGES = "topology_changes"
    STATUS_ANIMATION_CHANGES = "status_animation_changes"
    SCORE_PROGRESS_CHANGES = "score_progress_changes"
    TERMINAL_CHANGES = "terminal_changes"
    DELAYED_EFFECTS = "delayed_effects"


CHANNEL_ORDER: tuple[ConsequenceChannel, ...] = tuple(ConsequenceChannel)


class ObjectOperation(StrEnum):
    CREATED = "created"
    REMOVED = "removed"
    RECOLORED = "recolored"
    TRANSFORMED = "transformed"
    MOVED = "moved"


class TopologyOperation(StrEnum):
    OPENED = "opened"
    CLOSED = "closed"
    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    WRAPPED = "wrapped"


class EffectKind(StrEnum):
    DISPLACEMENT = "displacement"
    OBJECT = "object"
    QUANTITY = "quantity"
    LEGAL_ACTION = "legal_action"
    TOPOLOGY = "topology"
    STATUS = "status"
    SCORE_PROGRESS = "score_progress"
    TERMINAL = "terminal"
    DELAYED = "delayed"


@dataclass(frozen=True, slots=True)
class DisplacementEffect:
    subject: str
    dx: int
    dy: int

    def __post_init__(self) -> None:
        _require_text(self.subject, field="displacement subject")
        _require_int(self.dx, field="dx")
        _require_int(self.dy, field="dy")

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "kind": EffectKind.DISPLACEMENT.value,
            "subject": self.subject,
            "dx": self.dx,
            "dy": self.dy,
        }


@dataclass(frozen=True, slots=True)
class ObjectEffect:
    subject: str
    operation: ObjectOperation
    value: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.operation, ObjectOperation):
            raise MechanicsError("object operation must be typed")
        _require_text(self.subject, field="object subject")
        if self.value is not None:
            _require_text(self.value, field="object effect value")

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "kind": EffectKind.OBJECT.value,
            "subject": self.subject,
            "operation": self.operation.value,
            "value": self.value,
        }


@dataclass(frozen=True, slots=True)
class QuantityEffect:
    subject: str
    delta: int

    def __post_init__(self) -> None:
        _require_text(self.subject, field="quantity subject")
        _require_int(self.delta, field="quantity delta")

    def to_dict(self) -> dict[str, JSONValue]:
        return {"kind": EffectKind.QUANTITY.value, "subject": self.subject, "delta": self.delta}


@dataclass(frozen=True, slots=True)
class LegalActionEffect:
    action: ActionName
    available: bool

    def __post_init__(self) -> None:
        if not isinstance(self.action, ActionName):
            raise MechanicsError("legal action must be an ActionName")
        if not isinstance(self.available, bool):
            raise MechanicsError("legal-action availability must be boolean")

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "kind": EffectKind.LEGAL_ACTION.value,
            "action": self.action.value,
            "available": self.available,
        }


@dataclass(frozen=True, slots=True)
class TopologyEffect:
    relation: str
    operation: TopologyOperation
    source: str
    target: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.operation, TopologyOperation):
            raise MechanicsError("topology operation must be typed")
        _require_text(self.relation, field="topology relation")
        _require_text(self.source, field="topology source")
        if self.target is not None:
            _require_text(self.target, field="topology target")

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "kind": EffectKind.TOPOLOGY.value,
            "relation": self.relation,
            "operation": self.operation.value,
            "source": self.source,
            "target": self.target,
        }


@dataclass(frozen=True, slots=True)
class StatusEffect:
    subject: str
    value: str

    def __post_init__(self) -> None:
        _require_text(self.subject, field="status subject")
        _require_text(self.value, field="status value")

    def to_dict(self) -> dict[str, JSONValue]:
        return {"kind": EffectKind.STATUS.value, "subject": self.subject, "value": self.value}


@dataclass(frozen=True, slots=True)
class ScoreProgressEffect:
    metric: str
    delta: int

    def __post_init__(self) -> None:
        _require_text(self.metric, field="score/progress metric")
        _require_int(self.delta, field="score/progress delta")

    def to_dict(self) -> dict[str, JSONValue]:
        return {"kind": EffectKind.SCORE_PROGRESS.value, "metric": self.metric, "delta": self.delta}


@dataclass(frozen=True, slots=True)
class TerminalEffect:
    state: GameStateName

    def __post_init__(self) -> None:
        if not isinstance(self.state, GameStateName):
            raise MechanicsError("terminal state must be a GameStateName")

    def to_dict(self) -> dict[str, JSONValue]:
        return {"kind": EffectKind.TERMINAL.value, "state": self.state.value}


@dataclass(frozen=True, slots=True)
class DelayedEffect:
    delay_steps: int
    target_channel: ConsequenceChannel
    signature: str

    def __post_init__(self) -> None:
        if not isinstance(self.target_channel, ConsequenceChannel):
            raise MechanicsError("delayed target channel must be typed")
        if _require_int(self.delay_steps, field="delay_steps") <= 0:
            raise MechanicsError("delay_steps must be positive")
        if self.target_channel is ConsequenceChannel.DELAYED_EFFECTS:
            raise MechanicsError("a delayed effect cannot target the delayed-effects channel")
        _require_text(self.signature, field="delayed effect signature")

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "kind": EffectKind.DELAYED.value,
            "delay_steps": self.delay_steps,
            "target_channel": self.target_channel.value,
            "signature": self.signature,
        }


type EffectAtom = (
    DisplacementEffect
    | ObjectEffect
    | QuantityEffect
    | LegalActionEffect
    | TopologyEffect
    | StatusEffect
    | ScoreProgressEffect
    | TerminalEffect
    | DelayedEffect
)


_EFFECT_TYPES = (
    DisplacementEffect,
    ObjectEffect,
    QuantityEffect,
    LegalActionEffect,
    TopologyEffect,
    StatusEffect,
    ScoreProgressEffect,
    TerminalEffect,
    DelayedEffect,
)


_CHANNEL_EFFECT_TYPE: dict[ConsequenceChannel, type[object]] = {
    ConsequenceChannel.CONTROLLED_DISPLACEMENT: DisplacementEffect,
    ConsequenceChannel.OTHER_OBJECT_EFFECTS: ObjectEffect,
    ConsequenceChannel.RESOURCE_CHANGES: QuantityEffect,
    ConsequenceChannel.INVENTORY_CHANGES: QuantityEffect,
    ConsequenceChannel.LEGAL_ACTION_CHANGES: LegalActionEffect,
    ConsequenceChannel.TOPOLOGY_CHANGES: TopologyEffect,
    ConsequenceChannel.STATUS_ANIMATION_CHANGES: StatusEffect,
    ConsequenceChannel.SCORE_PROGRESS_CHANGES: ScoreProgressEffect,
    ConsequenceChannel.TERMINAL_CHANGES: TerminalEffect,
    ConsequenceChannel.DELAYED_EFFECTS: DelayedEffect,
}


def effect_to_dict(effect: EffectAtom) -> dict[str, JSONValue]:
    """Serialize one typed effect atom."""

    return effect.to_dict()


def effect_from_dict(value: Mapping[str, object]) -> EffectAtom:
    """Parse one effect atom without coercing malformed values."""

    kind = _parse_enum(EffectKind, value.get("kind"), field="effect kind")
    if kind is EffectKind.DISPLACEMENT:
        return DisplacementEffect(
            subject=_require_text(value.get("subject"), field="displacement subject"),
            dx=_require_int(value.get("dx"), field="dx"),
            dy=_require_int(value.get("dy"), field="dy"),
        )
    if kind is EffectKind.OBJECT:
        raw_value = value.get("value")
        return ObjectEffect(
            subject=_require_text(value.get("subject"), field="object subject"),
            operation=_parse_enum(
                ObjectOperation, value.get("operation"), field="object operation"
            ),
            value=None
            if raw_value is None
            else _require_text(raw_value, field="object effect value"),
        )
    if kind is EffectKind.QUANTITY:
        return QuantityEffect(
            subject=_require_text(value.get("subject"), field="quantity subject"),
            delta=_require_int(value.get("delta"), field="quantity delta"),
        )
    if kind is EffectKind.LEGAL_ACTION:
        available = value.get("available")
        if not isinstance(available, bool):
            raise MechanicsError("legal-action availability must be boolean")
        return LegalActionEffect(
            action=_parse_enum(ActionName, value.get("action"), field="legal action"),
            available=available,
        )
    if kind is EffectKind.TOPOLOGY:
        target = value.get("target")
        return TopologyEffect(
            relation=_require_text(value.get("relation"), field="topology relation"),
            operation=_parse_enum(
                TopologyOperation, value.get("operation"), field="topology operation"
            ),
            source=_require_text(value.get("source"), field="topology source"),
            target=None if target is None else _require_text(target, field="topology target"),
        )
    if kind is EffectKind.STATUS:
        return StatusEffect(
            subject=_require_text(value.get("subject"), field="status subject"),
            value=_require_text(value.get("value"), field="status value"),
        )
    if kind is EffectKind.SCORE_PROGRESS:
        return ScoreProgressEffect(
            metric=_require_text(value.get("metric"), field="score/progress metric"),
            delta=_require_int(value.get("delta"), field="score/progress delta"),
        )
    if kind is EffectKind.TERMINAL:
        return TerminalEffect(
            state=_parse_enum(GameStateName, value.get("state"), field="terminal state")
        )
    return DelayedEffect(
        delay_steps=_require_int(value.get("delay_steps"), field="delay_steps"),
        target_channel=_parse_enum(
            ConsequenceChannel, value.get("target_channel"), field="delayed target channel"
        ),
        signature=_require_text(value.get("signature"), field="delayed effect signature"),
    )


@dataclass(frozen=True, slots=True)
class ChannelValue:
    """One consequence factor, including an explicit epistemic state."""

    knowledge: KnowledgeState
    effects: tuple[EffectAtom, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.knowledge, KnowledgeState):
            raise MechanicsError("channel knowledge must be a KnowledgeState")
        if self.knowledge is KnowledgeState.UNKNOWN and self.effects:
            raise MechanicsError("UNKNOWN consequence channels cannot carry effects")
        unique: dict[str, EffectAtom] = {}
        for effect in self.effects:
            if not isinstance(effect, _EFFECT_TYPES):
                raise MechanicsError("channel effects must be typed effect atoms")
            unique[canonical_json(effect_to_dict(effect))] = effect
        object.__setattr__(self, "effects", tuple(unique[key] for key in sorted(unique)))

    @classmethod
    def unknown(cls) -> Self:
        return cls(KnowledgeState.UNKNOWN)

    @classmethod
    def known_empty(cls) -> Self:
        return cls(KnowledgeState.KNOWN)

    @classmethod
    def known(cls, *effects: EffectAtom) -> Self:
        return cls(KnowledgeState.KNOWN, tuple(effects))

    @property
    def is_unknown(self) -> bool:
        return self.knowledge is KnowledgeState.UNKNOWN

    @property
    def is_known_empty(self) -> bool:
        return self.knowledge is KnowledgeState.KNOWN and not self.effects

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "knowledge": self.knowledge.value,
            "effects": [effect_to_dict(effect) for effect in self.effects],
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object], *, channel: ConsequenceChannel) -> Self:
        knowledge = _parse_enum(KnowledgeState, value.get("knowledge"), field="knowledge")
        raw_effects = _require_list(value.get("effects"), field=f"{channel.value} effects")
        effects = tuple(
            effect_from_dict(_require_mapping(item, field=f"{channel.value} effect"))
            for item in raw_effects
        )
        expected = _CHANNEL_EFFECT_TYPE[channel]
        if any(not isinstance(effect, expected) for effect in effects):
            raise MechanicsError(f"{channel.value} contains an incompatible effect kind")
        return cls(knowledge, effects)


def _unknown_channel() -> ChannelValue:
    return ChannelValue.unknown()


@dataclass(frozen=True, slots=True)
class ConsequenceVector:
    """A complete fixed consequence vector; no channel is optional."""

    controlled_displacement: ChannelValue = field(default_factory=_unknown_channel)
    other_object_effects: ChannelValue = field(default_factory=_unknown_channel)
    resource_changes: ChannelValue = field(default_factory=_unknown_channel)
    inventory_changes: ChannelValue = field(default_factory=_unknown_channel)
    legal_action_changes: ChannelValue = field(default_factory=_unknown_channel)
    topology_changes: ChannelValue = field(default_factory=_unknown_channel)
    status_animation_changes: ChannelValue = field(default_factory=_unknown_channel)
    score_progress_changes: ChannelValue = field(default_factory=_unknown_channel)
    terminal_changes: ChannelValue = field(default_factory=_unknown_channel)
    delayed_effects: ChannelValue = field(default_factory=_unknown_channel)

    def __post_init__(self) -> None:
        for channel, value in self.items():
            if not isinstance(value, ChannelValue):
                raise MechanicsError(f"{channel.value} must be a ChannelValue")
            expected = _CHANNEL_EFFECT_TYPE[channel]
            if any(not isinstance(effect, expected) for effect in value.effects):
                raise MechanicsError(f"{channel.value} contains an incompatible effect kind")

    @classmethod
    def unknown(cls) -> Self:
        return cls()

    @classmethod
    def known_empty(cls) -> Self:
        empty = ChannelValue.known_empty()
        return cls(*(empty for _channel in CHANNEL_ORDER))

    def get(self, channel: ConsequenceChannel) -> ChannelValue:
        return {
            ConsequenceChannel.CONTROLLED_DISPLACEMENT: self.controlled_displacement,
            ConsequenceChannel.OTHER_OBJECT_EFFECTS: self.other_object_effects,
            ConsequenceChannel.RESOURCE_CHANGES: self.resource_changes,
            ConsequenceChannel.INVENTORY_CHANGES: self.inventory_changes,
            ConsequenceChannel.LEGAL_ACTION_CHANGES: self.legal_action_changes,
            ConsequenceChannel.TOPOLOGY_CHANGES: self.topology_changes,
            ConsequenceChannel.STATUS_ANIMATION_CHANGES: self.status_animation_changes,
            ConsequenceChannel.SCORE_PROGRESS_CHANGES: self.score_progress_changes,
            ConsequenceChannel.TERMINAL_CHANGES: self.terminal_changes,
            ConsequenceChannel.DELAYED_EFFECTS: self.delayed_effects,
        }[channel]

    def with_channel(self, channel: ConsequenceChannel, value: ChannelValue) -> Self:
        if channel is ConsequenceChannel.CONTROLLED_DISPLACEMENT:
            return replace(self, controlled_displacement=value)
        if channel is ConsequenceChannel.OTHER_OBJECT_EFFECTS:
            return replace(self, other_object_effects=value)
        if channel is ConsequenceChannel.RESOURCE_CHANGES:
            return replace(self, resource_changes=value)
        if channel is ConsequenceChannel.INVENTORY_CHANGES:
            return replace(self, inventory_changes=value)
        if channel is ConsequenceChannel.LEGAL_ACTION_CHANGES:
            return replace(self, legal_action_changes=value)
        if channel is ConsequenceChannel.TOPOLOGY_CHANGES:
            return replace(self, topology_changes=value)
        if channel is ConsequenceChannel.STATUS_ANIMATION_CHANGES:
            return replace(self, status_animation_changes=value)
        if channel is ConsequenceChannel.SCORE_PROGRESS_CHANGES:
            return replace(self, score_progress_changes=value)
        if channel is ConsequenceChannel.TERMINAL_CHANGES:
            return replace(self, terminal_changes=value)
        return replace(self, delayed_effects=value)

    def items(self) -> tuple[tuple[ConsequenceChannel, ChannelValue], ...]:
        return tuple((channel, self.get(channel)) for channel in CHANNEL_ORDER)

    @property
    def known_channels(self) -> tuple[ConsequenceChannel, ...]:
        return tuple(channel for channel, value in self.items() if not value.is_unknown)

    @property
    def is_fully_unknown(self) -> bool:
        return not self.known_channels

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "schema": "arc3.mechanics.consequence-vector.v0.1",
            "channels": {channel.value: value.to_dict() for channel, value in self.items()},
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> Self:
        if value.get("schema") != "arc3.mechanics.consequence-vector.v0.1":
            raise MechanicsError("unsupported consequence-vector schema")
        channels = _require_mapping(value.get("channels"), field="consequence channels")
        if set(channels) != {channel.value for channel in CHANNEL_ORDER}:
            raise MechanicsError(
                "consequence vectors must contain every fixed channel exactly once"
            )
        parsed = {
            channel: ChannelValue.from_dict(
                _require_mapping(channels[channel.value], field=channel.value), channel=channel
            )
            for channel in CHANNEL_ORDER
        }
        return cls(*(parsed[channel] for channel in CHANNEL_ORDER))


class ScopeCeiling(StrEnum):
    GENERIC = "generic"
    GAME = "game"
    LEVEL = "level"


_SCOPE_RANK = {ScopeCeiling.GENERIC: 0, ScopeCeiling.GAME: 1, ScopeCeiling.LEVEL: 2}


@dataclass(frozen=True, slots=True)
class MechanicContext:
    """Opaque current context against which mechanic scopes are matched."""

    game_scope: str
    level_scope: str
    region_tags: tuple[str, ...] = ()
    object_roles: tuple[str, ...] = ()
    state_tags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_text(self.game_scope, field="game_scope")
        _require_text(self.level_scope, field="level_scope")
        object.__setattr__(
            self, "region_tags", _normalize_strings(self.region_tags, field="region tag")
        )
        object.__setattr__(
            self, "object_roles", _normalize_strings(self.object_roles, field="object role")
        )
        object.__setattr__(
            self, "state_tags", _normalize_strings(self.state_tags, field="state tag")
        )

    @property
    def context_key(self) -> str:
        digest = sha256_json(self.to_dict()).removeprefix("sha256:")
        return f"mechanic-context:{digest[:24]}"

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "game_scope": self.game_scope,
            "level_scope": self.level_scope,
            "region_tags": list(self.region_tags),
            "object_roles": list(self.object_roles),
            "state_tags": list(self.state_tags),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> Self:
        return cls(
            game_scope=_require_text(value.get("game_scope"), field="game_scope"),
            level_scope=_require_text(value.get("level_scope"), field="level_scope"),
            region_tags=_parse_string_tuple(value.get("region_tags", []), field="region_tags"),
            object_roles=_parse_string_tuple(value.get("object_roles", []), field="object_roles"),
            state_tags=_parse_string_tuple(value.get("state_tags", []), field="state_tags"),
        )


@dataclass(frozen=True, slots=True)
class MechanicScope:
    """A composable scope ceiling plus optional conjunctive selectors."""

    ceiling: ScopeCeiling
    game_scope: str | None = None
    level_scope: str | None = None
    region_tags: tuple[str, ...] = ()
    object_roles: tuple[str, ...] = ()
    state_tags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.ceiling, ScopeCeiling):
            raise MechanicsError("scope ceiling must be typed")
        if self.ceiling is ScopeCeiling.GENERIC:
            if self.game_scope is not None or self.level_scope is not None:
                raise MechanicsError("generic scopes cannot name a game or level")
        elif self.ceiling is ScopeCeiling.GAME:
            _require_text(self.game_scope, field="game_scope")
            if self.level_scope is not None:
                raise MechanicsError("game scopes cannot name a level")
        else:
            _require_text(self.game_scope, field="game_scope")
            _require_text(self.level_scope, field="level_scope")
        object.__setattr__(
            self, "region_tags", _normalize_strings(self.region_tags, field="region tag")
        )
        object.__setattr__(
            self, "object_roles", _normalize_strings(self.object_roles, field="object role")
        )
        object.__setattr__(
            self, "state_tags", _normalize_strings(self.state_tags, field="state tag")
        )

    @property
    def specificity(self) -> int:
        return (
            100 * _SCOPE_RANK[self.ceiling]
            + len(self.region_tags)
            + len(self.object_roles)
            + len(self.state_tags)
        )

    def matches(self, context: MechanicContext) -> bool:
        if self.ceiling is not ScopeCeiling.GENERIC and self.game_scope != context.game_scope:
            return False
        if self.ceiling is ScopeCeiling.LEVEL and self.level_scope != context.level_scope:
            return False
        return (
            set(self.region_tags).issubset(context.region_tags)
            and set(self.object_roles).issubset(context.object_roles)
            and set(self.state_tags).issubset(context.state_tags)
        )

    def compose(self, other: MechanicScope) -> MechanicScope | None:
        """Return the conjunction of two compatible scopes, or ``None``."""

        game_values = {item for item in (self.game_scope, other.game_scope) if item is not None}
        level_values = {item for item in (self.level_scope, other.level_scope) if item is not None}
        if len(game_values) > 1 or len(level_values) > 1:
            return None
        ceiling = max((self.ceiling, other.ceiling), key=_SCOPE_RANK.__getitem__)
        game_scope = next(iter(game_values), None)
        level_scope = next(iter(level_values), None)
        if ceiling is ScopeCeiling.GAME and game_scope is None:
            return None
        if ceiling is ScopeCeiling.LEVEL and (game_scope is None or level_scope is None):
            return None
        return MechanicScope(
            ceiling=ceiling,
            game_scope=game_scope,
            level_scope=level_scope,
            region_tags=(*self.region_tags, *other.region_tags),
            object_roles=(*self.object_roles, *other.object_roles),
            state_tags=(*self.state_tags, *other.state_tags),
        )

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "ceiling": self.ceiling.value,
            "game_scope": self.game_scope,
            "level_scope": self.level_scope,
            "region_tags": list(self.region_tags),
            "object_roles": list(self.object_roles),
            "state_tags": list(self.state_tags),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> Self:
        game_scope = value.get("game_scope")
        level_scope = value.get("level_scope")
        return cls(
            ceiling=_parse_enum(ScopeCeiling, value.get("ceiling"), field="scope ceiling"),
            game_scope=None
            if game_scope is None
            else _require_text(game_scope, field="game_scope"),
            level_scope=None
            if level_scope is None
            else _require_text(level_scope, field="level_scope"),
            region_tags=_parse_string_tuple(value.get("region_tags", []), field="region_tags"),
            object_roles=_parse_string_tuple(value.get("object_roles", []), field="object_roles"),
            state_tags=_parse_string_tuple(value.get("state_tags", []), field="state_tags"),
        )


class MechanicStatus(StrEnum):
    PROVISIONAL = "provisional"
    SUPPORTED = "supported"
    STABLE_WITHIN_SCOPE = "stable_within_scope"
    STRESSED = "stressed"
    RECURRING_UNRESOLVED = "recurring_unresolved"
    REOPENED = "reopened"
    REJECTED_OR_SUPERSEDED = "rejected_or_superseded"


class CompositionMode(StrEnum):
    BASE = "base"
    ADDITIVE = "additive"
    CONDITIONAL = "conditional"
    GATING = "gating"
    OVERRIDE = "override"
    DELAYED = "delayed"


class EvidenceProvenance(StrEnum):
    OFFICIAL_INTERFACE = "official_interface"
    GENERIC_GAME_PRIOR = "generic_game_prior"
    OBSERVED_THIS_GAME = "observed_this_game"
    DERIVED_THIS_GAME = "derived_this_game"


class ConfirmationMode(StrEnum):
    DELIBERATE = "deliberate"
    PASSIVE = "passive"
    TRANSFER = "transfer"


class MechanicEvidenceKind(StrEnum):
    SUPPORT = "support"
    CONTRADICTION = "contradiction"
    RESIDUAL = "residual"


class SupportDimension(StrEnum):
    OCCURRENCE = "occurrence"
    MAGNITUDE = "magnitude"


@dataclass(frozen=True, slots=True, order=True)
class MechanicRef:
    mechanic_id: str
    version: int

    def __post_init__(self) -> None:
        _require_text(self.mechanic_id, field="mechanic_id")
        if _require_int(self.version, field="mechanic version") <= 0:
            raise MechanicsError("mechanic versions must be positive")

    def to_dict(self) -> dict[str, JSONValue]:
        return {"mechanic_id": self.mechanic_id, "version": self.version}

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> Self:
        return cls(
            mechanic_id=_require_text(value.get("mechanic_id"), field="mechanic_id"),
            version=_require_int(value.get("version"), field="mechanic version"),
        )


@dataclass(frozen=True, slots=True)
class MechanicVersion:
    """One immutable semantic version of an action mechanic."""

    ref: MechanicRef
    action: ActionName
    scope: MechanicScope
    consequence: ConsequenceVector
    composition_mode: CompositionMode
    created_step: int
    created_from_event_ids: tuple[str, ...]
    provenance: EvidenceProvenance
    parent_ref: MechanicRef | None = None
    priority: int = 0
    note: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.ref, MechanicRef):
            raise MechanicsError("mechanic ref must be typed")
        if not isinstance(self.action, ActionName):
            raise MechanicsError("mechanic action must be an ActionName")
        if not isinstance(self.scope, MechanicScope):
            raise MechanicsError("mechanic scope must be typed")
        if not isinstance(self.consequence, ConsequenceVector):
            raise MechanicsError("mechanic consequence must be typed")
        if not isinstance(self.composition_mode, CompositionMode):
            raise MechanicsError("mechanic composition mode must be typed")
        if not isinstance(self.provenance, EvidenceProvenance):
            raise MechanicsError("mechanic provenance must be typed")
        _require_non_negative_int(self.created_step, field="created_step")
        sources = _normalize_strings(self.created_from_event_ids, field="created source event ID")
        if not sources:
            raise MechanicsError("mechanic versions require at least one source event ID")
        object.__setattr__(self, "created_from_event_ids", sources)
        _require_int(self.priority, field="mechanic priority")
        if self.parent_ref is not None and self.parent_ref.mechanic_id != self.ref.mechanic_id:
            raise MechanicsError("a mechanic revision parent must keep the same mechanic_id")
        if self.consequence.is_fully_unknown:
            raise MechanicsError("a mechanic version must assert at least one known channel")
        if len(self.note) > 512:
            raise MechanicsError("mechanic note must not exceed 512 characters")

    @property
    def semantic_hash(self) -> str:
        return sha256_json(self.to_dict())

    @property
    def specificity(self) -> int:
        return self.scope.specificity + self.priority

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "ref": self.ref.to_dict(),
            "action": self.action.value,
            "scope": self.scope.to_dict(),
            "consequence": self.consequence.to_dict(),
            "composition_mode": self.composition_mode.value,
            "created_step": self.created_step,
            "created_from_event_ids": list(self.created_from_event_ids),
            "provenance": self.provenance.value,
            "parent_ref": self.parent_ref.to_dict() if self.parent_ref is not None else None,
            "priority": self.priority,
            "note": self.note,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> Self:
        parent = value.get("parent_ref")
        return cls(
            ref=MechanicRef.from_dict(_require_mapping(value.get("ref"), field="mechanic ref")),
            action=_parse_enum(ActionName, value.get("action"), field="mechanic action"),
            scope=MechanicScope.from_dict(
                _require_mapping(value.get("scope"), field="mechanic scope")
            ),
            consequence=ConsequenceVector.from_dict(
                _require_mapping(value.get("consequence"), field="mechanic consequence")
            ),
            composition_mode=_parse_enum(
                CompositionMode, value.get("composition_mode"), field="composition mode"
            ),
            created_step=_require_non_negative_int(value.get("created_step"), field="created_step"),
            created_from_event_ids=_parse_string_tuple(
                value.get("created_from_event_ids"), field="created_from_event_ids"
            ),
            provenance=_parse_enum(
                EvidenceProvenance, value.get("provenance"), field="mechanic provenance"
            ),
            parent_ref=(
                None
                if parent is None
                else MechanicRef.from_dict(_require_mapping(parent, field="parent_ref"))
            ),
            priority=_require_int(value.get("priority", 0), field="mechanic priority"),
            note=_require_string(value.get("note", ""), field="mechanic note"),
        )


@dataclass(frozen=True, slots=True)
class MechanicEvidence:
    """Source-linked evidence bearing only on named consequence channels."""

    receipt_id: str
    kind: MechanicEvidenceKind
    confirmation_mode: ConfirmationMode
    provenance: EvidenceProvenance
    source_event_ids: tuple[str, ...]
    channels: tuple[ConsequenceChannel, ...]
    context_key: str
    observed_step: int
    support_dimensions: tuple[SupportDimension, ...] = ()
    summary: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.kind, MechanicEvidenceKind):
            raise MechanicsError("mechanic evidence kind must be typed")
        if not isinstance(self.confirmation_mode, ConfirmationMode):
            raise MechanicsError("confirmation mode must be typed")
        if not isinstance(self.provenance, EvidenceProvenance):
            raise MechanicsError("evidence provenance must be typed")
        if any(not isinstance(channel, ConsequenceChannel) for channel in self.channels):
            raise MechanicsError("mechanic evidence channels must be typed")
        if any(not isinstance(item, SupportDimension) for item in self.support_dimensions):
            raise MechanicsError("support dimensions must be typed")
        _require_text(self.receipt_id, field="mechanic evidence receipt_id")
        sources = _normalize_strings(self.source_event_ids, field="source event ID")
        if not sources:
            raise MechanicsError("mechanic evidence requires at least one source event ID")
        object.__setattr__(self, "source_event_ids", sources)
        channels = tuple(sorted(set(self.channels), key=CHANNEL_ORDER.index))
        if not channels:
            raise MechanicsError("mechanic evidence requires at least one consequence channel")
        object.__setattr__(self, "channels", channels)
        _require_text(self.context_key, field="mechanic evidence context_key")
        _require_non_negative_int(self.observed_step, field="observed_step")
        dimensions = tuple(sorted(set(self.support_dimensions), key=lambda item: item.value))
        object.__setattr__(self, "support_dimensions", dimensions)
        if self.kind is MechanicEvidenceKind.SUPPORT and not dimensions:
            raise MechanicsError("support evidence requires an occurrence or magnitude dimension")
        if self.kind is not MechanicEvidenceKind.SUPPORT and dimensions:
            raise MechanicsError("only support evidence may carry support dimensions")
        if len(self.summary) > 512:
            raise MechanicsError("evidence summary must not exceed 512 characters")

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "receipt_id": self.receipt_id,
            "kind": self.kind.value,
            "confirmation_mode": self.confirmation_mode.value,
            "provenance": self.provenance.value,
            "source_event_ids": list(self.source_event_ids),
            "channels": [channel.value for channel in self.channels],
            "context_key": self.context_key,
            "observed_step": self.observed_step,
            "support_dimensions": [item.value for item in self.support_dimensions],
            "summary": self.summary,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> Self:
        raw_channels = _require_list(value.get("channels"), field="evidence channels")
        raw_dimensions = _require_list(
            value.get("support_dimensions", []), field="support dimensions"
        )
        return cls(
            receipt_id=_require_text(value.get("receipt_id"), field="mechanic evidence receipt_id"),
            kind=_parse_enum(
                MechanicEvidenceKind, value.get("kind"), field="mechanic evidence kind"
            ),
            confirmation_mode=_parse_enum(
                ConfirmationMode, value.get("confirmation_mode"), field="confirmation mode"
            ),
            provenance=_parse_enum(
                EvidenceProvenance, value.get("provenance"), field="evidence provenance"
            ),
            source_event_ids=_parse_string_tuple(
                value.get("source_event_ids"), field="source_event_ids"
            ),
            channels=tuple(
                _parse_enum(ConsequenceChannel, item, field="evidence channel")
                for item in raw_channels
            ),
            context_key=_require_text(value.get("context_key"), field="context_key"),
            observed_step=_require_non_negative_int(
                value.get("observed_step"), field="observed_step"
            ),
            support_dimensions=tuple(
                _parse_enum(SupportDimension, item, field="support dimension")
                for item in raw_dimensions
            ),
            summary=_require_string(value.get("summary", ""), field="evidence summary"),
        )


@dataclass(frozen=True, slots=True)
class ChannelEvidenceSummary:
    channel: ConsequenceChannel
    occurrence_support_count: int = 0
    magnitude_support_count: int = 0
    contradiction_count: int = 0
    residual_count: int = 0
    deliberate_contexts: tuple[str, ...] = ()
    passive_contexts: tuple[str, ...] = ()
    transfer_contexts: tuple[str, ...] = ()
    contradiction_contexts: tuple[str, ...] = ()
    contexts_truncated: bool = False

    def to_dict(self) -> dict[str, JSONValue]:
        payload = normalize_json(self)
        assert isinstance(payload, dict)
        return payload


@dataclass(frozen=True, slots=True)
class MechanicView:
    """Replaceable state reconstructed only from immutable ledger events."""

    version: MechanicVersion
    status: MechanicStatus
    evidence_receipt_ids: tuple[str, ...]
    channel_evidence: tuple[ChannelEvidenceSummary, ...]
    event_ids: tuple[str, ...]
    superseded_by: MechanicRef | None = None

    @property
    def ref(self) -> MechanicRef:
        return self.version.ref

    @property
    def is_live(self) -> bool:
        return self.status is not MechanicStatus.REJECTED_OR_SUPERSEDED

    @property
    def is_prediction_eligible(self) -> bool:
        """Whether this view may currently contribute to an action prediction."""

        return self.status in {
            MechanicStatus.PROVISIONAL,
            MechanicStatus.SUPPORTED,
            MechanicStatus.STABLE_WITHIN_SCOPE,
        }

    def summary_for(self, channel: ConsequenceChannel) -> ChannelEvidenceSummary:
        return next(item for item in self.channel_evidence if item.channel is channel)

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "version": self.version.to_dict(),
            "status": self.status.value,
            "evidence_receipt_ids": list(self.evidence_receipt_ids),
            "channel_evidence": [item.to_dict() for item in self.channel_evidence],
            "event_ids": list(self.event_ids),
            "superseded_by": self.superseded_by.to_dict() if self.superseded_by else None,
        }


@dataclass(frozen=True, slots=True)
class MechanicLedgerBudget:
    """Fail-closed competition bounds for the learner's active state."""

    max_active_mechanics: int = 64
    max_versions: int = 192
    max_events: int = 1024
    max_open_residuals: int = 8
    max_candidates_per_residual: int = 4
    max_contexts_per_channel: int = 32
    max_pending_predictions: int = 1
    max_pending_delayed_effects: int = 8
    max_probe_candidates: int = 8
    max_deliberate_repeats: int = 2

    def __post_init__(self) -> None:
        for name, value in self.to_dict().items():
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise MechanicsError(f"{name} must be a positive integer")
        if self.max_pending_predictions != 1:
            raise MechanicsError("the consequence gate permits exactly one pending prediction")

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "max_active_mechanics": self.max_active_mechanics,
            "max_versions": self.max_versions,
            "max_events": self.max_events,
            "max_open_residuals": self.max_open_residuals,
            "max_candidates_per_residual": self.max_candidates_per_residual,
            "max_contexts_per_channel": self.max_contexts_per_channel,
            "max_pending_predictions": self.max_pending_predictions,
            "max_pending_delayed_effects": self.max_pending_delayed_effects,
            "max_probe_candidates": self.max_probe_candidates,
            "max_deliberate_repeats": self.max_deliberate_repeats,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> Self:
        return cls(
            max_active_mechanics=_require_int(
                value.get("max_active_mechanics"), field="max_active_mechanics"
            ),
            max_versions=_require_int(value.get("max_versions"), field="max_versions"),
            max_events=_require_int(value.get("max_events"), field="max_events"),
            max_open_residuals=_require_int(
                value.get("max_open_residuals"), field="max_open_residuals"
            ),
            max_candidates_per_residual=_require_int(
                value.get("max_candidates_per_residual"), field="max_candidates_per_residual"
            ),
            max_contexts_per_channel=_require_int(
                value.get("max_contexts_per_channel"), field="max_contexts_per_channel"
            ),
            max_pending_predictions=_require_int(
                value.get("max_pending_predictions"), field="max_pending_predictions"
            ),
            max_pending_delayed_effects=_require_int(
                value.get("max_pending_delayed_effects"),
                field="max_pending_delayed_effects",
            ),
            max_probe_candidates=_require_int(
                value.get("max_probe_candidates"), field="max_probe_candidates"
            ),
            max_deliberate_repeats=_require_int(
                value.get("max_deliberate_repeats"), field="max_deliberate_repeats"
            ),
        )


def _parse_enum[EnumT: StrEnum](enum_type: type[EnumT], value: object, *, field: str) -> EnumT:
    if not isinstance(value, str):
        raise MechanicsError(f"{field} must be a string")
    try:
        return enum_type(value)
    except ValueError as error:
        raise MechanicsError(f"unsupported {field}: {value!r}") from error


def _require_text(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise MechanicsError(f"{field} must be a non-empty string")
    return value


def _require_string(value: object, *, field: str) -> str:
    if not isinstance(value, str):
        raise MechanicsError(f"{field} must be a string")
    return value


def _require_int(value: object, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise MechanicsError(f"{field} must be an integer")
    return value


def _require_non_negative_int(value: object, *, field: str) -> int:
    result = _require_int(value, field=field)
    if result < 0:
        raise MechanicsError(f"{field} must be non-negative")
    return result


def _require_mapping(value: object, *, field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or not all(isinstance(key, str) for key in value):
        raise MechanicsError(f"{field} must be an object with string keys")
    return value


def _require_list(value: object, *, field: str) -> list[object]:
    if not isinstance(value, list):
        raise MechanicsError(f"{field} must be an array")
    return value


def _normalize_strings(values: Iterable[str], *, field: str) -> tuple[str, ...]:
    return tuple(sorted({_require_text(value, field=field) for value in values}))


def _parse_string_tuple(value: object, *, field: str) -> tuple[str, ...]:
    items = _require_list(value, field=field)
    return _normalize_strings(
        (_require_text(item, field=field) for item in items),
        field=field,
    )


__all__ = [
    "CHANNEL_ORDER",
    "ChannelEvidenceSummary",
    "ChannelValue",
    "CompositionMode",
    "ConfirmationMode",
    "ConsequenceChannel",
    "ConsequenceVector",
    "DelayedEffect",
    "DisplacementEffect",
    "EffectAtom",
    "EffectKind",
    "EvidenceProvenance",
    "KnowledgeState",
    "LegalActionEffect",
    "MechanicContext",
    "MechanicEvidence",
    "MechanicEvidenceKind",
    "MechanicLedgerBudget",
    "MechanicRef",
    "MechanicScope",
    "MechanicStatus",
    "MechanicVersion",
    "MechanicView",
    "MechanicsError",
    "ObjectEffect",
    "ObjectOperation",
    "QuantityEffect",
    "ScopeCeiling",
    "ScoreProgressEffect",
    "StatusEffect",
    "SupportDimension",
    "TerminalEffect",
    "TopologyEffect",
    "TopologyOperation",
    "effect_from_dict",
    "effect_to_dict",
]
