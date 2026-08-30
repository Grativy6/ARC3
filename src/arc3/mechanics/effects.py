"""Consequence composition and typed prediction-residual measurement."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum

from arc3.trace.canonical import canonical_json, sha256_json
from arc3.types import ActionName, JSONValue

from .models import (
    CHANNEL_ORDER,
    ChannelValue,
    CompositionMode,
    ConsequenceChannel,
    ConsequenceVector,
    DelayedEffect,
    DisplacementEffect,
    EffectAtom,
    LegalActionEffect,
    MechanicRef,
    MechanicsError,
    MechanicVersion,
    ObjectEffect,
    QuantityEffect,
    ScoreProgressEffect,
    StatusEffect,
    TerminalEffect,
    TopologyEffect,
)


@dataclass(frozen=True, slots=True)
class EffectContribution:
    """One applicable mechanic and the exact vector it contributes."""

    ref: MechanicRef
    mode: CompositionMode
    specificity: int
    consequence: ConsequenceVector

    @classmethod
    def from_version(cls, version: MechanicVersion) -> EffectContribution:
        return cls(
            ref=version.ref,
            mode=version.composition_mode,
            specificity=version.specificity,
            consequence=version.consequence,
        )

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "ref": self.ref.to_dict(),
            "mode": self.mode.value,
            "specificity": self.specificity,
            "consequence": self.consequence.to_dict(),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> EffectContribution:
        ref = value.get("ref")
        consequence = value.get("consequence")
        mode = value.get("mode")
        specificity = value.get("specificity")
        if not isinstance(ref, Mapping) or not isinstance(consequence, Mapping):
            raise MechanicsError("effect contribution ref and consequence must be objects")
        if not isinstance(mode, str):
            raise MechanicsError("effect contribution mode must be a string")
        if isinstance(specificity, bool) or not isinstance(specificity, int):
            raise MechanicsError("effect contribution specificity must be an integer")
        try:
            parsed_mode = CompositionMode(mode)
        except ValueError as error:
            raise MechanicsError(f"unsupported composition mode: {mode!r}") from error
        return cls(
            ref=MechanicRef.from_dict(ref),
            mode=parsed_mode,
            specificity=specificity,
            consequence=ConsequenceVector.from_dict(consequence),
        )


@dataclass(frozen=True, slots=True)
class CompositionAmbiguity:
    channel: ConsequenceChannel
    reason: str
    contributor_refs: tuple[MechanicRef, ...]

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "channel": self.channel.value,
            "reason": self.reason,
            "contributor_refs": [item.to_dict() for item in self.contributor_refs],
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> CompositionAmbiguity:
        channel = _channel(value.get("channel"))
        reason = value.get("reason")
        refs = value.get("contributor_refs")
        if not isinstance(reason, str) or not reason:
            raise MechanicsError("composition ambiguity reason must be non-empty")
        if not isinstance(refs, list) or not all(isinstance(item, Mapping) for item in refs):
            raise MechanicsError("composition contributor_refs must be an array of objects")
        return cls(
            channel=channel,
            reason=reason,
            contributor_refs=tuple(MechanicRef.from_dict(item) for item in refs),
        )


@dataclass(frozen=True, slots=True)
class CompositionResult:
    """A prediction plus channel-exact provenance and unresolved ambiguity."""

    consequence: ConsequenceVector
    contributors: tuple[tuple[ConsequenceChannel, tuple[MechanicRef, ...]], ...]
    ambiguities: tuple[CompositionAmbiguity, ...] = ()

    def contributors_for(self, channel: ConsequenceChannel) -> tuple[MechanicRef, ...]:
        return next((refs for current, refs in self.contributors if current is channel), ())

    @property
    def signature(self) -> str:
        return sha256_json(self.to_dict())

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "consequence": self.consequence.to_dict(),
            "contributors": {
                channel.value: [ref.to_dict() for ref in refs]
                for channel, refs in self.contributors
            },
            "ambiguities": [item.to_dict() for item in self.ambiguities],
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> CompositionResult:
        consequence = value.get("consequence")
        contributors = value.get("contributors")
        ambiguities = value.get("ambiguities", [])
        if not isinstance(consequence, Mapping) or not isinstance(contributors, Mapping):
            raise MechanicsError("composition result fields must be objects")
        if set(contributors) != {channel.value for channel in CHANNEL_ORDER}:
            raise MechanicsError("composition result must name every contributor channel")
        parsed_contributors: list[tuple[ConsequenceChannel, tuple[MechanicRef, ...]]] = []
        for channel in CHANNEL_ORDER:
            refs = contributors[channel.value]
            if not isinstance(refs, list) or not all(isinstance(item, Mapping) for item in refs):
                raise MechanicsError("composition contributors must be arrays of mechanic refs")
            parsed_contributors.append(
                (channel, tuple(MechanicRef.from_dict(item) for item in refs))
            )
        if not isinstance(ambiguities, list) or not all(
            isinstance(item, Mapping) for item in ambiguities
        ):
            raise MechanicsError("composition ambiguities must be an array of objects")
        return cls(
            consequence=ConsequenceVector.from_dict(consequence),
            contributors=tuple(parsed_contributors),
            ambiguities=tuple(CompositionAmbiguity.from_dict(item) for item in ambiguities),
        )


def compose_contributions(contributions: Iterable[EffectContribution]) -> CompositionResult:
    """Compose applicable mechanics without discarding contribution identity.

    Unknown fields are treated as "this mechanic makes no assertion".  A
    channel stays unknown only when no applicable mechanic makes a known
    assertion, or when equally specific assertions conflict.
    """

    ordered = tuple(sorted(contributions, key=_contribution_key))
    vector = ConsequenceVector.unknown()
    provenance: list[tuple[ConsequenceChannel, tuple[MechanicRef, ...]]] = []
    ambiguities: list[CompositionAmbiguity] = []
    for channel in CHANNEL_ORDER:
        value, refs, ambiguity = _compose_channel(channel, ordered)
        vector = vector.with_channel(channel, value)
        provenance.append((channel, refs))
        if ambiguity is not None:
            ambiguities.append(ambiguity)
    return CompositionResult(vector, tuple(provenance), tuple(ambiguities))


def _compose_channel(
    channel: ConsequenceChannel,
    contributions: tuple[EffectContribution, ...],
) -> tuple[ChannelValue, tuple[MechanicRef, ...], CompositionAmbiguity | None]:
    known = tuple(item for item in contributions if not item.consequence.get(channel).is_unknown)
    if not known:
        return ChannelValue.unknown(), (), None

    overrides = tuple(item for item in known if item.mode is CompositionMode.OVERRIDE)
    if overrides:
        return _choose_specific(channel, overrides, label="override")

    gates = tuple(item for item in known if item.mode is CompositionMode.GATING)
    if gates:
        # A gate is an authoritative context-local outcome: known-empty blocks
        # the channel, while a non-empty value names the gated outcome.
        return _choose_specific(channel, gates, label="gate")

    bases = tuple(item for item in known if item.mode is CompositionMode.BASE)
    selected: list[EffectContribution] = []
    values: list[ChannelValue] = []
    if bases:
        base_value, base_refs, ambiguity = _choose_specific(channel, bases, label="base")
        if ambiguity is not None:
            return base_value, base_refs, ambiguity
        values.append(base_value)
        selected.extend(item for item in bases if item.ref in base_refs)

    additive_modes = {CompositionMode.ADDITIVE, CompositionMode.CONDITIONAL}
    if channel is ConsequenceChannel.DELAYED_EFFECTS:
        additive_modes.add(CompositionMode.DELAYED)
    additives = tuple(item for item in known if item.mode in additive_modes)
    for item in additives:
        values.append(item.consequence.get(channel))
        selected.append(item)

    if not values:
        delayed_elsewhere = tuple(item for item in known if item.mode is CompositionMode.DELAYED)
        refs = tuple(item.ref for item in delayed_elsewhere)
        return (
            ChannelValue.unknown(),
            refs,
            CompositionAmbiguity(
                channel,
                "delayed composition may assert only the delayed-effects channel",
                refs,
            ),
        )

    merged, reason = _merge_known_values(channel, values)
    refs = tuple(sorted({item.ref for item in selected}))
    if reason is not None:
        return ChannelValue.unknown(), refs, CompositionAmbiguity(channel, reason, refs)
    return merged, refs, None


def _choose_specific(
    channel: ConsequenceChannel,
    candidates: tuple[EffectContribution, ...],
    *,
    label: str,
) -> tuple[ChannelValue, tuple[MechanicRef, ...], CompositionAmbiguity | None]:
    specificity = max(item.specificity for item in candidates)
    winners = tuple(item for item in candidates if item.specificity == specificity)
    signatures = {canonical_json(item.consequence.get(channel).to_dict()) for item in winners}
    refs = tuple(sorted(item.ref for item in winners))
    if len(signatures) != 1:
        return (
            ChannelValue.unknown(),
            refs,
            CompositionAmbiguity(
                channel,
                f"equally specific {label} mechanics disagree",
                refs,
            ),
        )
    return winners[0].consequence.get(channel), refs, None


def _merge_known_values(
    channel: ConsequenceChannel, values: Iterable[ChannelValue]
) -> tuple[ChannelValue, str | None]:
    effects = tuple(effect for value in values for effect in value.effects)
    if channel is ConsequenceChannel.CONTROLLED_DISPLACEMENT:
        totals: dict[str, tuple[int, int]] = {}
        for raw in effects:
            assert isinstance(raw, DisplacementEffect)
            dx, dy = totals.get(raw.subject, (0, 0))
            totals[raw.subject] = (dx + raw.dx, dy + raw.dy)
        merged: tuple[EffectAtom, ...] = tuple(
            DisplacementEffect(subject, dx, dy)
            for subject, (dx, dy) in sorted(totals.items())
            if dx != 0 or dy != 0
        )
        return ChannelValue.known(*merged), None
    if channel in {
        ConsequenceChannel.RESOURCE_CHANGES,
        ConsequenceChannel.INVENTORY_CHANGES,
    }:
        quantities: dict[str, int] = {}
        for raw in effects:
            assert isinstance(raw, QuantityEffect)
            quantities[raw.subject] = quantities.get(raw.subject, 0) + raw.delta
        merged = tuple(
            QuantityEffect(subject, delta)
            for subject, delta in sorted(quantities.items())
            if delta != 0
        )
        return ChannelValue.known(*merged), None
    if channel is ConsequenceChannel.SCORE_PROGRESS_CHANGES:
        progress: dict[str, int] = {}
        for raw in effects:
            assert isinstance(raw, ScoreProgressEffect)
            progress[raw.metric] = progress.get(raw.metric, 0) + raw.delta
        merged = tuple(
            ScoreProgressEffect(metric, delta)
            for metric, delta in sorted(progress.items())
            if delta != 0
        )
        return ChannelValue.known(*merged), None
    if channel is ConsequenceChannel.LEGAL_ACTION_CHANGES:
        actions: dict[str, bool] = {}
        for raw in effects:
            assert isinstance(raw, LegalActionEffect)
            previous_available = actions.get(raw.action.value)
            if previous_available is not None and previous_available != raw.available:
                return ChannelValue.unknown(), "legal-action contributions conflict"
            actions[raw.action.value] = raw.available
        merged = tuple(
            LegalActionEffect(_action(action), available)
            for action, available in sorted(actions.items())
        )
        return ChannelValue.known(*merged), None
    if channel is ConsequenceChannel.STATUS_ANIMATION_CHANGES:
        statuses: dict[str, str] = {}
        for raw in effects:
            assert isinstance(raw, StatusEffect)
            previous_status = statuses.get(raw.subject)
            if previous_status is not None and previous_status != raw.value:
                return ChannelValue.unknown(), "status contributions conflict"
            statuses[raw.subject] = raw.value
        merged = tuple(StatusEffect(subject, value) for subject, value in sorted(statuses.items()))
        return ChannelValue.known(*merged), None
    if channel is ConsequenceChannel.TERMINAL_CHANGES:
        terminal = {raw.state for raw in effects if isinstance(raw, TerminalEffect)}
        if len(terminal) > 1:
            return ChannelValue.unknown(), "terminal contributions conflict"
        merged = tuple(
            TerminalEffect(state) for state in sorted(terminal, key=lambda item: item.value)
        )
        return ChannelValue.known(*merged), None
    if channel is ConsequenceChannel.OTHER_OBJECT_EFFECTS:
        objects: dict[str, ObjectEffect] = {}
        for raw in effects:
            assert isinstance(raw, ObjectEffect)
            previous_object = objects.get(raw.subject)
            if previous_object is not None and previous_object != raw:
                return ChannelValue.unknown(), "object-effect contributions conflict"
            objects[raw.subject] = raw
        return ChannelValue.known(*tuple(objects[key] for key in sorted(objects))), None
    if channel is ConsequenceChannel.TOPOLOGY_CHANGES:
        topology: dict[tuple[str, str], TopologyEffect] = {}
        for raw in effects:
            assert isinstance(raw, TopologyEffect)
            key = (raw.relation, raw.source)
            previous_topology = topology.get(key)
            if previous_topology is not None and previous_topology != raw:
                return ChannelValue.unknown(), "topology contributions conflict"
            topology[key] = raw
        return ChannelValue.known(*tuple(topology[key] for key in sorted(topology))), None
    delayed: dict[tuple[int, ConsequenceChannel, str], DelayedEffect] = {}
    for raw in effects:
        assert isinstance(raw, DelayedEffect)
        delayed[(raw.delay_steps, raw.target_channel, raw.signature)] = raw
    return ChannelValue.known(*tuple(delayed[key] for key in sorted(delayed))), None


class ResidualKind(StrEnum):
    MATCH = "match"
    UNKNOWN_PREDICTION = "unknown_prediction"
    UNREADABLE_OBSERVATION = "unreadable_observation"
    MISSING_EFFECT = "missing_effect"
    UNEXPECTED_EFFECT = "unexpected_effect"
    MAGNITUDE_MISMATCH = "magnitude_mismatch"
    VALUE_MISMATCH = "value_mismatch"
    AMBIGUOUS_COMPOSITION = "ambiguous_composition"


DEFAULT_CHANNEL_RELEVANCE: dict[ConsequenceChannel, int] = {
    ConsequenceChannel.TERMINAL_CHANGES: 100,
    ConsequenceChannel.LEGAL_ACTION_CHANGES: 90,
    ConsequenceChannel.RESOURCE_CHANGES: 85,
    ConsequenceChannel.INVENTORY_CHANGES: 85,
    ConsequenceChannel.SCORE_PROGRESS_CHANGES: 80,
    ConsequenceChannel.CONTROLLED_DISPLACEMENT: 75,
    ConsequenceChannel.TOPOLOGY_CHANGES: 70,
    ConsequenceChannel.OTHER_OBJECT_EFFECTS: 50,
    ConsequenceChannel.DELAYED_EFFECTS: 45,
    ConsequenceChannel.STATUS_ANIMATION_CHANGES: 20,
}


@dataclass(frozen=True, slots=True)
class ChannelResidual:
    channel: ConsequenceChannel
    kind: ResidualKind
    predicted: ChannelValue
    observed: ChannelValue
    relevance: int
    contributor_refs: tuple[MechanicRef, ...] = ()
    reason: str = ""

    @property
    def matched(self) -> bool:
        return self.kind is ResidualKind.MATCH

    @property
    def consequential(self) -> bool:
        return (
            self.kind
            not in {
                ResidualKind.MATCH,
                ResidualKind.UNREADABLE_OBSERVATION,
            }
            and self.relevance >= 40
        )

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "channel": self.channel.value,
            "kind": self.kind.value,
            "predicted": self.predicted.to_dict(),
            "observed": self.observed.to_dict(),
            "relevance": self.relevance,
            "contributor_refs": [item.to_dict() for item in self.contributor_refs],
            "reason": self.reason,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> ChannelResidual:
        channel = _channel(value.get("channel"))
        kind = value.get("kind")
        predicted = value.get("predicted")
        observed = value.get("observed")
        relevance = value.get("relevance")
        refs = value.get("contributor_refs", [])
        reason = value.get("reason", "")
        if not isinstance(kind, str):
            raise MechanicsError("residual kind must be a string")
        try:
            parsed_kind = ResidualKind(kind)
        except ValueError as error:
            raise MechanicsError(f"unsupported residual kind: {kind!r}") from error
        if not isinstance(predicted, Mapping) or not isinstance(observed, Mapping):
            raise MechanicsError("residual channel values must be objects")
        if isinstance(relevance, bool) or not isinstance(relevance, int) or relevance < 0:
            raise MechanicsError("residual relevance must be a non-negative integer")
        if not isinstance(refs, list) or not all(isinstance(item, Mapping) for item in refs):
            raise MechanicsError("residual contributor_refs must be an array of objects")
        if not isinstance(reason, str):
            raise MechanicsError("residual reason must be a string")
        return cls(
            channel=channel,
            kind=parsed_kind,
            predicted=ChannelValue.from_dict(predicted, channel=channel),
            observed=ChannelValue.from_dict(observed, channel=channel),
            relevance=relevance,
            contributor_refs=tuple(MechanicRef.from_dict(item) for item in refs),
            reason=reason,
        )


@dataclass(frozen=True, slots=True)
class ConsequenceResidual:
    residual_id: str
    channels: tuple[ChannelResidual, ...]

    @property
    def mismatches(self) -> tuple[ChannelResidual, ...]:
        return tuple(item for item in self.channels if not item.matched)

    @property
    def consequential(self) -> tuple[ChannelResidual, ...]:
        return tuple(item for item in self.channels if item.consequential)

    @property
    def priority(self) -> int:
        return max((item.relevance for item in self.consequential), default=0)

    def for_channel(self, channel: ConsequenceChannel) -> ChannelResidual:
        return next(item for item in self.channels if item.channel is channel)

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "residual_id": self.residual_id,
            "channels": [item.to_dict() for item in self.channels],
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> ConsequenceResidual:
        residual_id = value.get("residual_id")
        channels = value.get("channels")
        if not isinstance(residual_id, str) or not residual_id:
            raise MechanicsError("residual_id must be non-empty")
        if not isinstance(channels, list) or not all(
            isinstance(item, Mapping) for item in channels
        ):
            raise MechanicsError("residual channels must be an array of objects")
        parsed = tuple(ChannelResidual.from_dict(item) for item in channels)
        if tuple(item.channel for item in parsed) != CHANNEL_ORDER:
            raise MechanicsError("a consequence residual must contain every channel in fixed order")
        return cls(residual_id=residual_id, channels=parsed)


def compare_consequence(
    prediction: CompositionResult | ConsequenceVector,
    observed: ConsequenceVector,
    *,
    relevance: Mapping[ConsequenceChannel, int] | None = None,
) -> ConsequenceResidual:
    """Compare predicted and observed factors without collapsing residual type."""

    result = (
        prediction
        if isinstance(prediction, CompositionResult)
        else CompositionResult(
            prediction,
            tuple((channel, ()) for channel in CHANNEL_ORDER),
        )
    )
    weights = DEFAULT_CHANNEL_RELEVANCE if relevance is None else relevance
    ambiguities = {item.channel: item for item in result.ambiguities}
    residuals: list[ChannelResidual] = []
    for channel in CHANNEL_ORDER:
        predicted = result.consequence.get(channel)
        actual = observed.get(channel)
        ambiguity = ambiguities.get(channel)
        if ambiguity is not None:
            kind = ResidualKind.AMBIGUOUS_COMPOSITION
            reason = ambiguity.reason
        else:
            kind = _residual_kind(channel, predicted, actual)
            reason = ""
        residuals.append(
            ChannelResidual(
                channel=channel,
                kind=kind,
                predicted=predicted,
                observed=actual,
                relevance=weights.get(channel, 0),
                contributor_refs=result.contributors_for(channel),
                reason=reason,
            )
        )
    content = [item.to_dict() for item in residuals]
    digest = sha256_json(content).removeprefix("sha256:")
    return ConsequenceResidual(f"mechanic-residual:{digest[:24]}", tuple(residuals))


def _residual_kind(
    channel: ConsequenceChannel, predicted: ChannelValue, observed: ChannelValue
) -> ResidualKind:
    if observed.is_unknown:
        return ResidualKind.UNREADABLE_OBSERVATION
    if predicted.is_unknown:
        return ResidualKind.UNKNOWN_PREDICTION
    if predicted == observed:
        return ResidualKind.MATCH
    if predicted.is_known_empty and not observed.is_known_empty:
        return ResidualKind.UNEXPECTED_EFFECT
    if observed.is_known_empty and not predicted.is_known_empty:
        return ResidualKind.MISSING_EFFECT
    if _numeric_magnitude_only(channel, predicted.effects, observed.effects):
        return ResidualKind.MAGNITUDE_MISMATCH
    return ResidualKind.VALUE_MISMATCH


def _numeric_magnitude_only(
    channel: ConsequenceChannel,
    predicted: tuple[EffectAtom, ...],
    observed: tuple[EffectAtom, ...],
) -> bool:
    if channel is ConsequenceChannel.CONTROLLED_DISPLACEMENT:
        return {item.subject for item in predicted if isinstance(item, DisplacementEffect)} == {
            item.subject for item in observed if isinstance(item, DisplacementEffect)
        }
    if channel in {
        ConsequenceChannel.RESOURCE_CHANGES,
        ConsequenceChannel.INVENTORY_CHANGES,
    }:
        return {item.subject for item in predicted if isinstance(item, QuantityEffect)} == {
            item.subject for item in observed if isinstance(item, QuantityEffect)
        }
    if channel is ConsequenceChannel.SCORE_PROGRESS_CHANGES:
        return {item.metric for item in predicted if isinstance(item, ScoreProgressEffect)} == {
            item.metric for item in observed if isinstance(item, ScoreProgressEffect)
        }
    return False


def _contribution_key(item: EffectContribution) -> tuple[int, str, int, str]:
    return (item.specificity, item.ref.mechanic_id, item.ref.version, item.mode.value)


def _channel(value: object) -> ConsequenceChannel:
    if not isinstance(value, str):
        raise MechanicsError("consequence channel must be a string")
    try:
        return ConsequenceChannel(value)
    except ValueError as error:
        raise MechanicsError(f"unsupported consequence channel: {value!r}") from error


def _action(value: str) -> ActionName:
    return ActionName(value)


__all__ = [
    "DEFAULT_CHANNEL_RELEVANCE",
    "ChannelResidual",
    "CompositionAmbiguity",
    "CompositionResult",
    "ConsequenceResidual",
    "EffectContribution",
    "ResidualKind",
    "compare_consequence",
    "compose_contributions",
]
