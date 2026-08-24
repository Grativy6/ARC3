"""Factored causal-effect observations and compact external-action receipts."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

from arc3.adapters import Observation
from arc3.perception.delta import FrameDelta, MetadataChange
from arc3.perception.layers import ResidualDisposition
from arc3.types import ActionName, ActionRequest, GameStateName, JSONScalar, JSONValue


class EffectChannel(StrEnum):
    """The fixed, non-collapsing consequence channels for each action."""

    CONTROLLABLE_OBJECT_DISPLACEMENT = "controllable_object_displacement"
    OTHER_OBJECT_CHANGE = "other_object_displacement_or_transformation"
    RESOURCE_HUD_CHANGE = "resource_or_hud_change"
    INVENTORY_COUNT_CHANGE = "inventory_or_count_change"
    LEGAL_ACTION_CHANGE = "legal_action_change"
    TOPOLOGY_REACHABILITY_CHANGE = "topology_blocking_gate_or_reachability_change"
    STATUS_ANIMATION_CHANGE = "status_or_animation_change"
    SCORE_PROGRESS_CHANGE = "score_or_progress_change"
    TERMINAL_RESET_TRANSITION = "terminal_or_reset_transition"
    DELAYED_UNRESOLVED = "delayed_or_currently_unresolved_consequence"


FIXED_EFFECT_CHANNELS: tuple[EffectChannel, ...] = tuple(EffectChannel)


class EffectKnowledge(StrEnum):
    """Epistemic status of one channel; absence is never silently treated as zero."""

    KNOWN = "KNOWN"
    UNKNOWN = "UNKNOWN"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class ResidualKind(StrEnum):
    """Relationship between one predicted and observed effect channel."""

    OPEN_INFORMATION = "open_information"
    MISMATCH = "known_value_mismatch"
    UNEXPECTED_EFFECT = "unexpected_applicable_effect"
    MISSING_EFFECT = "predicted_effect_not_observed"
    UNREADABLE = "observed_effect_unreadable"


class RiskLevel(StrEnum):
    """Qualitative risk label without fabricated probability."""

    UNKNOWN = "UNKNOWN"
    LOW = "LOW"
    ELEVATED = "ELEVATED"
    TERMINAL = "TERMINAL"


def _require_text(value: str, *, field: str) -> str:
    if not value.strip():
        raise ValueError(f"{field} must not be empty")
    return value


def _normalize_refs(values: tuple[str, ...], *, field: str) -> tuple[str, ...]:
    if any(not value.strip() for value in values):
        raise ValueError(f"{field} entries must not be empty")
    return tuple(sorted(set(values)))


@dataclass(frozen=True, slots=True)
class FactoredEffect:
    """One explicit effect-channel value with compact evidence pointers."""

    channel: EffectChannel
    knowledge: EffectKnowledge
    value: JSONValue = None
    evidence_refs: tuple[str, ...] = ()
    dynamic_candidate: bool = False

    def __post_init__(self) -> None:
        if self.knowledge is EffectKnowledge.KNOWN and self.value is None:
            raise ValueError("KNOWN effects require an explicit non-null value")
        if self.knowledge is not EffectKnowledge.KNOWN and self.value is not None:
            raise ValueError("UNKNOWN and NOT_APPLICABLE effects must have null value")
        if self.dynamic_candidate and self.knowledge is not EffectKnowledge.KNOWN:
            raise ValueError("only a measured value can remain a dynamic candidate")
        object.__setattr__(
            self,
            "evidence_refs",
            _normalize_refs(self.evidence_refs, field="effect evidence reference"),
        )

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "channel": self.channel.value,
            "knowledge": self.knowledge.value,
            "value": self.value,
            "evidence_refs": list(self.evidence_refs),
            "dynamic_candidate": self.dynamic_candidate,
        }


@dataclass(frozen=True, slots=True)
class EffectVector:
    """Exactly one epistemically explicit value for every fixed channel."""

    effects: tuple[FactoredEffect, ...]

    def __post_init__(self) -> None:
        channels = tuple(effect.channel for effect in self.effects)
        if len(set(channels)) != len(channels):
            raise ValueError("effect vectors may name each channel only once")
        missing = set(FIXED_EFFECT_CHANNELS) - set(channels)
        extra = set(channels) - set(FIXED_EFFECT_CHANNELS)
        if missing or extra:
            names = ", ".join(sorted(item.value for item in missing | extra))
            raise ValueError(f"effect vector must contain exactly the fixed channels: {names}")
        by_channel = {effect.channel: effect for effect in self.effects}
        object.__setattr__(
            self,
            "effects",
            tuple(by_channel[channel] for channel in FIXED_EFFECT_CHANNELS),
        )

    @classmethod
    def unknown(cls) -> EffectVector:
        """Construct a complete vector that makes every unknown explicit."""

        return cls(
            tuple(
                FactoredEffect(channel=channel, knowledge=EffectKnowledge.UNKNOWN)
                for channel in FIXED_EFFECT_CHANNELS
            )
        )

    @classmethod
    def from_effects(
        cls,
        effects: tuple[FactoredEffect, ...],
        *,
        unspecified: EffectKnowledge = EffectKnowledge.UNKNOWN,
    ) -> EffectVector:
        """Fill unspecified fixed channels with an explicit shared knowledge state."""

        if unspecified is EffectKnowledge.KNOWN:
            raise ValueError("unspecified channels cannot be filled as KNOWN")
        channels = tuple(effect.channel for effect in effects)
        if len(set(channels)) != len(channels):
            raise ValueError("effects may name each channel only once")
        by_channel = {effect.channel: effect for effect in effects}
        return cls(
            tuple(
                by_channel.get(
                    channel,
                    FactoredEffect(channel=channel, knowledge=unspecified),
                )
                for channel in FIXED_EFFECT_CHANNELS
            )
        )

    def get(self, channel: EffectChannel) -> FactoredEffect:
        return self.effects[FIXED_EFFECT_CHANNELS.index(channel)]

    def to_dict(self) -> dict[str, JSONValue]:
        return {effect.channel.value: effect.to_dict() for effect in self.effects}


@dataclass(frozen=True, slots=True)
class DynamicFieldCandidate:
    """Measured scalar change whose game meaning remains unpromoted."""

    field: str
    before_present: bool
    after_present: bool
    before: JSONScalar
    after: JSONScalar
    evidence_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_text(self.field, field="dynamic field")
        object.__setattr__(
            self,
            "evidence_refs",
            _normalize_refs(self.evidence_refs, field="dynamic field evidence reference"),
        )

    @classmethod
    def from_metadata_change(
        cls,
        change: MetadataChange,
        *,
        evidence_refs: tuple[str, ...] = (),
    ) -> DynamicFieldCandidate:
        return cls(
            field=change.field,
            before_present=change.before_present,
            after_present=change.after_present,
            before=change.before,
            after=change.after,
            evidence_refs=evidence_refs,
        )

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "field": self.field,
            "before_present": self.before_present,
            "after_present": self.after_present,
            "before": self.before,
            "after": self.after,
            "evidence_refs": list(self.evidence_refs),
        }


_DIRECT_OFFICIAL_FIELDS = frozenset(
    {"state", "levels_completed", "win_levels", "available_actions", "full_reset"}
)


def dynamic_candidates_from_delta(
    delta: FrameDelta,
    *,
    evidence_refs: tuple[str, ...] = (),
) -> tuple[DynamicFieldCandidate, ...]:
    """Retain arbitrary scalar changes as candidates without naming their mechanics."""

    return tuple(
        DynamicFieldCandidate.from_metadata_change(change, evidence_refs=evidence_refs)
        for change in delta.metadata_changes
        if change.field not in _DIRECT_OFFICIAL_FIELDS
    )


def _known(
    channel: EffectChannel,
    value: JSONValue,
    *,
    evidence_refs: tuple[str, ...],
    dynamic_candidate: bool = False,
) -> FactoredEffect:
    return FactoredEffect(
        channel=channel,
        knowledge=EffectKnowledge.KNOWN,
        value=value,
        evidence_refs=evidence_refs,
        dynamic_candidate=dynamic_candidate,
    )


def _not_applicable(channel: EffectChannel) -> FactoredEffect:
    return FactoredEffect(channel=channel, knowledge=EffectKnowledge.NOT_APPLICABLE)


def extract_observed_effects(
    before: Observation,
    after: Observation,
    delta: FrameDelta,
    *,
    recognized_effects: tuple[FactoredEffect, ...] = (),
    dynamic_candidates: tuple[DynamicFieldCandidate, ...] = (),
    evidence_refs: tuple[str, ...] = (),
) -> EffectVector:
    """Factor readable consequences while leaving semantics explicitly unknown.

    Official lifecycle, progress, and legal-action metadata are direct readings.
    Unnamed counters and raw visual changes remain dynamic candidates in the
    delayed/unresolved channel; they never become resources or inventory merely
    because they changed.
    """

    refs = _normalize_refs(evidence_refs, field="observed effect evidence reference")
    recognized_channels = tuple(effect.channel for effect in recognized_effects)
    if len(set(recognized_channels)) != len(recognized_channels):
        raise ValueError("recognized effects may name each channel only once")
    if any(effect.knowledge is not EffectKnowledge.KNOWN for effect in recognized_effects):
        raise ValueError("recognized effects must carry KNOWN values")

    measured: dict[EffectChannel, FactoredEffect] = {
        channel: FactoredEffect(channel=channel, knowledge=EffectKnowledge.UNKNOWN)
        for channel in FIXED_EFFECT_CHANNELS
    }
    before_actions = sorted(action.value for action in before.available_actions)
    after_actions = sorted(action.value for action in after.available_actions)
    if before_actions != after_actions:
        before_action_values: list[JSONValue] = []
        before_action_values.extend(before_actions)
        after_action_values: list[JSONValue] = []
        after_action_values.extend(after_actions)
        measured[EffectChannel.LEGAL_ACTION_CHANGE] = _known(
            EffectChannel.LEGAL_ACTION_CHANGE,
            {"before": before_action_values, "after": after_action_values},
            evidence_refs=refs,
        )
    else:
        measured[EffectChannel.LEGAL_ACTION_CHANGE] = _not_applicable(
            EffectChannel.LEGAL_ACTION_CHANGE
        )

    if before.levels_completed != after.levels_completed or before.win_levels != after.win_levels:
        measured[EffectChannel.SCORE_PROGRESS_CHANGE] = _known(
            EffectChannel.SCORE_PROGRESS_CHANGE,
            {
                "levels_completed": {
                    "before": before.levels_completed,
                    "after": after.levels_completed,
                },
                "win_levels": {"before": before.win_levels, "after": after.win_levels},
            },
            evidence_refs=refs,
        )
    else:
        measured[EffectChannel.SCORE_PROGRESS_CHANGE] = _not_applicable(
            EffectChannel.SCORE_PROGRESS_CHANGE
        )

    if before.state is not after.state or before.full_reset != after.full_reset:
        measured[EffectChannel.TERMINAL_RESET_TRANSITION] = _known(
            EffectChannel.TERMINAL_RESET_TRANSITION,
            {
                "before_state": before.state.value,
                "after_state": after.state.value,
                "before_full_reset": before.full_reset,
                "after_full_reset": after.full_reset,
            },
            evidence_refs=refs,
        )
    else:
        measured[EffectChannel.TERMINAL_RESET_TRANSITION] = _not_applicable(
            EffectChannel.TERMINAL_RESET_TRANSITION
        )

    if not delta.cell_changes:
        measured[EffectChannel.STATUS_ANIMATION_CHANGE] = _not_applicable(
            EffectChannel.STATUS_ANIMATION_CHANGE
        )

    inferred_candidates = dynamic_candidates_from_delta(delta, evidence_refs=refs)
    candidates_by_field = {
        candidate.field: candidate for candidate in (*inferred_candidates, *dynamic_candidates)
    }
    unresolved: dict[str, JSONValue] = {}
    if delta.cell_changes:
        unresolved["unclassified_changed_cell_count"] = delta.changed_cell_count
    if candidates_by_field:
        unresolved["dynamic_fields"] = [
            candidates_by_field[field].to_dict() for field in sorted(candidates_by_field)
        ]
    if unresolved:
        measured[EffectChannel.DELAYED_UNRESOLVED] = _known(
            EffectChannel.DELAYED_UNRESOLVED,
            unresolved,
            evidence_refs=refs,
            dynamic_candidate=True,
        )
    else:
        measured[EffectChannel.DELAYED_UNRESOLVED] = _not_applicable(
            EffectChannel.DELAYED_UNRESOLVED
        )

    measured.update({effect.channel: effect for effect in recognized_effects})
    return EffectVector(tuple(measured[channel] for channel in FIXED_EFFECT_CHANNELS))


@dataclass(frozen=True, slots=True)
class EffectResidual:
    """Structured mismatch or open information with an explicit disposition."""

    channel: EffectChannel
    kind: ResidualKind
    predicted: FactoredEffect
    observed: FactoredEffect
    disposition: ResidualDisposition

    def __post_init__(self) -> None:
        if self.predicted.channel is not self.channel or self.observed.channel is not self.channel:
            raise ValueError("residual channel must match predicted and observed effects")

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "channel": self.channel.value,
            "kind": self.kind.value,
            "predicted": self.predicted.to_dict(),
            "observed": self.observed.to_dict(),
            "disposition": self.disposition.value,
        }


@dataclass(frozen=True, slots=True)
class EffectComparison:
    """Factored explained effects and residuals for one action transition."""

    explained_effects: tuple[FactoredEffect, ...]
    residual_effects: tuple[EffectResidual, ...]

    def __post_init__(self) -> None:
        explained = tuple(effect.channel for effect in self.explained_effects)
        residual = tuple(effect.channel for effect in self.residual_effects)
        if len(set(explained)) != len(explained) or len(set(residual)) != len(residual):
            raise ValueError("comparison channels must be unique within each result")
        if set(explained) & set(residual):
            raise ValueError("an effect cannot be both explained and residual")


def compare_effect_vectors(
    predicted: EffectVector,
    observed: EffectVector,
    *,
    dispositions: Mapping[EffectChannel, ResidualDisposition] | None = None,
) -> EffectComparison:
    """Compare vectors without converting an acknowledged unknown into contradiction."""

    disposition_by_channel = dispositions or {}
    explained: list[FactoredEffect] = []
    residuals: list[EffectResidual] = []
    for channel in FIXED_EFFECT_CHANNELS:
        expected = predicted.get(channel)
        actual = observed.get(channel)
        kind: ResidualKind | None = None
        if expected.knowledge is EffectKnowledge.UNKNOWN:
            if actual.knowledge is EffectKnowledge.KNOWN:
                kind = ResidualKind.OPEN_INFORMATION
        elif expected.knowledge is EffectKnowledge.NOT_APPLICABLE:
            if actual.knowledge is EffectKnowledge.KNOWN:
                kind = ResidualKind.UNEXPECTED_EFFECT
            elif actual.knowledge is EffectKnowledge.UNKNOWN:
                kind = ResidualKind.UNREADABLE
        elif actual.knowledge is EffectKnowledge.UNKNOWN:
            kind = ResidualKind.UNREADABLE
        elif actual.knowledge is EffectKnowledge.NOT_APPLICABLE:
            kind = ResidualKind.MISSING_EFFECT
        elif expected.value == actual.value:
            explained.append(actual)
        else:
            kind = ResidualKind.MISMATCH
        if kind is not None:
            residuals.append(
                EffectResidual(
                    channel=channel,
                    kind=kind,
                    predicted=expected,
                    observed=actual,
                    disposition=disposition_by_channel.get(
                        channel,
                        ResidualDisposition.PARK,
                    ),
                )
            )
    return EffectComparison(tuple(explained), tuple(residuals))


@dataclass(frozen=True, slots=True)
class ConsequencePriority:
    """Lexicographic importance; visual magnitude is the final tie-break only."""

    terminal_or_failure: bool = False
    legal_access_or_resource: bool = False
    movement_topology_or_progress: bool = False
    recurring_unresolved: bool = False
    visual_magnitude: int = 0

    def __post_init__(self) -> None:
        if (
            isinstance(self.visual_magnitude, bool)
            or not isinstance(self.visual_magnitude, int)
            or self.visual_magnitude < 0
        ):
            raise ValueError("visual_magnitude must be a non-negative integer")

    @property
    def sort_key(self) -> tuple[int, int, int, int, int]:
        """Use descending tuple order; critical metadata precedes decorative size."""

        return (
            int(self.terminal_or_failure),
            int(self.legal_access_or_resource),
            int(self.movement_topology_or_progress),
            int(self.recurring_unresolved),
            self.visual_magnitude,
        )


def consequence_priority(
    effect: FactoredEffect,
    *,
    recurring: bool = False,
    visual_magnitude: int = 0,
) -> ConsequencePriority:
    """Map one known consequence onto the declared lexicographic dimensions."""

    known = effect.knowledge is EffectKnowledge.KNOWN
    return ConsequencePriority(
        terminal_or_failure=known and effect.channel is EffectChannel.TERMINAL_RESET_TRANSITION,
        legal_access_or_resource=known
        and effect.channel
        in {
            EffectChannel.RESOURCE_HUD_CHANGE,
            EffectChannel.INVENTORY_COUNT_CHANGE,
            EffectChannel.LEGAL_ACTION_CHANGE,
        },
        movement_topology_or_progress=known
        and effect.channel
        in {
            EffectChannel.CONTROLLABLE_OBJECT_DISPLACEMENT,
            EffectChannel.OTHER_OBJECT_CHANGE,
            EffectChannel.TOPOLOGY_REACHABILITY_CHANGE,
            EffectChannel.SCORE_PROGRESS_CHANGE,
        },
        recurring_unresolved=known
        and recurring
        and effect.channel is EffectChannel.DELAYED_UNRESOLVED,
        visual_magnitude=visual_magnitude,
    )


@dataclass(frozen=True, slots=True)
class ResourceFailureRisk:
    """Qualitative pre-action risk record used by a causal action receipt."""

    level: RiskLevel
    summary: str
    resource_state_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_text(self.summary, field="risk summary")
        object.__setattr__(
            self,
            "resource_state_refs",
            _normalize_refs(self.resource_state_refs, field="resource state reference"),
        )

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "level": self.level.value,
            "summary": self.summary,
            "resource_state_refs": list(self.resource_state_refs),
        }


@dataclass(frozen=True, slots=True)
class CausalActionReceipt:
    """Complete compact receipt for exactly one external environment action."""

    receipt_id: str
    game_scope_id: str
    level_scope_id: str
    step_index: int
    before_state_ref: str
    chosen_action_and_coordinates: ActionRequest
    legal_actions_before: tuple[ActionName, ...]
    predicted_effects: EffectVector
    observed_effects: EffectVector
    explained_effects: tuple[FactoredEffect, ...]
    residual_effects: tuple[EffectResidual, ...]
    objects_or_regions_implicated: tuple[str, ...]
    active_hypotheses_used: tuple[str, ...]
    probe_or_progress_reason: str
    resource_and_failure_risk: ResourceFailureRisk
    terminal_state: GameStateName

    def __post_init__(self) -> None:
        for field, value in (
            ("receipt_id", self.receipt_id),
            ("game_scope_id", self.game_scope_id),
            ("level_scope_id", self.level_scope_id),
            ("before_state_ref", self.before_state_ref),
            ("probe_or_progress_reason", self.probe_or_progress_reason),
        ):
            _require_text(value, field=field)
        if isinstance(self.step_index, bool) or not isinstance(self.step_index, int):
            raise ValueError("step_index must be a non-negative integer")
        if self.step_index < 0:
            raise ValueError("step_index must be a non-negative integer")
        if len(set(self.legal_actions_before)) != len(self.legal_actions_before):
            raise ValueError("legal_actions_before must not contain duplicates")
        if (
            self.chosen_action_and_coordinates.name is not ActionName.RESET
            and self.chosen_action_and_coordinates.name not in self.legal_actions_before
        ):
            raise ValueError("chosen action must be present in legal_actions_before")
        object.__setattr__(
            self,
            "legal_actions_before",
            tuple(sorted(self.legal_actions_before, key=lambda action: action.value)),
        )
        object.__setattr__(
            self,
            "objects_or_regions_implicated",
            _normalize_refs(
                self.objects_or_regions_implicated,
                field="implicated object or region",
            ),
        )
        object.__setattr__(
            self,
            "active_hypotheses_used",
            _normalize_refs(self.active_hypotheses_used, field="active hypothesis"),
        )
        explained_channels = tuple(effect.channel for effect in self.explained_effects)
        residual_channels = tuple(effect.channel for effect in self.residual_effects)
        if len(set(explained_channels)) != len(explained_channels):
            raise ValueError("explained effects must name each channel at most once")
        if len(set(residual_channels)) != len(residual_channels):
            raise ValueError("residual effects must name each channel at most once")
        if set(explained_channels) & set(residual_channels):
            raise ValueError("a channel cannot be both explained and residual")

    @property
    def complete(self) -> bool:
        """Typed construction guarantees every mandatory receipt field is present."""

        return len(self.predicted_effects.effects) == len(FIXED_EFFECT_CHANNELS) and len(
            self.observed_effects.effects
        ) == len(FIXED_EFFECT_CHANNELS)

    def to_dict(self) -> dict[str, JSONValue]:
        coordinate = self.chosen_action_and_coordinates.coordinate
        return {
            "receipt_id": self.receipt_id,
            "game_scope_id": self.game_scope_id,
            "level_scope_id": self.level_scope_id,
            "step_index": self.step_index,
            "before_state_ref": self.before_state_ref,
            "chosen_action_and_coordinates": {
                "name": self.chosen_action_and_coordinates.name.value,
                "coordinate": (
                    {"x": coordinate.x, "y": coordinate.y} if coordinate is not None else None
                ),
            },
            "legal_actions_before": [action.value for action in self.legal_actions_before],
            "predicted_effects": self.predicted_effects.to_dict(),
            "observed_effects": self.observed_effects.to_dict(),
            "explained_effects": [effect.to_dict() for effect in self.explained_effects],
            "residual_effects": [effect.to_dict() for effect in self.residual_effects],
            "objects_or_regions_implicated": list(self.objects_or_regions_implicated),
            "active_hypotheses_used": list(self.active_hypotheses_used),
            "probe_or_progress_reason": self.probe_or_progress_reason,
            "resource_and_failure_risk": self.resource_and_failure_risk.to_dict(),
            "terminal_state": self.terminal_state.value,
        }


__all__ = [
    "FIXED_EFFECT_CHANNELS",
    "CausalActionReceipt",
    "ConsequencePriority",
    "DynamicFieldCandidate",
    "EffectChannel",
    "EffectComparison",
    "EffectKnowledge",
    "EffectResidual",
    "EffectVector",
    "FactoredEffect",
    "ResidualKind",
    "ResourceFailureRisk",
    "RiskLevel",
    "compare_effect_vectors",
    "consequence_priority",
    "dynamic_candidates_from_delta",
    "extract_observed_effects",
]
