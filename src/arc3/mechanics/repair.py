"""Smallest-first repair proposals for consequential mechanic residuals."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

from arc3.trace.canonical import sha256_json
from arc3.types import JSONValue

from .effects import ChannelResidual, ConsequenceResidual, ResidualKind
from .models import (
    CHANNEL_ORDER,
    CompositionMode,
    ConsequenceChannel,
    MechanicContext,
    MechanicLedgerBudget,
    MechanicRef,
    MechanicScope,
    MechanicsError,
    ScopeCeiling,
)


class RepairCandidateKind(StrEnum):
    OBJECT_OR_TERRAIN_MODIFIER = "object_or_terrain_modifier"
    RESOURCE_OR_STATUS_MODIFIER = "resource_or_status_modifier"
    TEMPORAL_MODIFIER = "temporal_modifier"
    BASE_REOPEN = "base_reopen"


_KIND_PRIORITY = {
    RepairCandidateKind.OBJECT_OR_TERRAIN_MODIFIER: 0,
    RepairCandidateKind.RESOURCE_OR_STATUS_MODIFIER: 1,
    RepairCandidateKind.TEMPORAL_MODIFIER: 2,
    RepairCandidateKind.BASE_REOPEN: 9,
}


@dataclass(frozen=True, slots=True)
class RepairCandidate:
    candidate_id: str
    residual_id: str
    kind: RepairCandidateKind
    channels: tuple[ConsequenceChannel, ...]
    scope: MechanicScope
    implicated_refs: tuple[MechanicRef, ...]
    suggested_mode: CompositionMode
    priority: int
    rationale: str

    @property
    def is_local(self) -> bool:
        return self.kind is not RepairCandidateKind.BASE_REOPEN

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "candidate_id": self.candidate_id,
            "residual_id": self.residual_id,
            "kind": self.kind.value,
            "channels": [channel.value for channel in self.channels],
            "scope": self.scope.to_dict(),
            "implicated_refs": [ref.to_dict() for ref in self.implicated_refs],
            "suggested_mode": self.suggested_mode.value,
            "priority": self.priority,
            "rationale": self.rationale,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> RepairCandidate:
        candidate_id = _text(value.get("candidate_id"), field="repair candidate_id")
        residual_id = _text(value.get("residual_id"), field="repair residual_id")
        kind = _enum(RepairCandidateKind, value.get("kind"), field="repair kind")
        channels_value = value.get("channels")
        scope_value = value.get("scope")
        refs_value = value.get("implicated_refs")
        mode = _enum(CompositionMode, value.get("suggested_mode"), field="suggested mode")
        priority = _int(value.get("priority"), field="repair priority")
        rationale = _text(value.get("rationale"), field="repair rationale")
        if not isinstance(channels_value, list):
            raise MechanicsError("repair channels must be an array")
        if not isinstance(scope_value, Mapping):
            raise MechanicsError("repair scope must be an object")
        if not isinstance(refs_value, list) or not all(
            isinstance(item, Mapping) for item in refs_value
        ):
            raise MechanicsError("repair implicated_refs must be an array of objects")
        return cls(
            candidate_id=candidate_id,
            residual_id=residual_id,
            kind=kind,
            channels=tuple(
                _enum(ConsequenceChannel, item, field="repair channel") for item in channels_value
            ),
            scope=MechanicScope.from_dict(scope_value),
            implicated_refs=tuple(MechanicRef.from_dict(item) for item in refs_value),
            suggested_mode=mode,
            priority=priority,
            rationale=rationale,
        )


class LocalRepairPlanner:
    """Generate bounded local explanations before offering base reopening."""

    def __init__(
        self,
        *,
        budget: MechanicLedgerBudget | None = None,
        local_failure_threshold: int = 2,
    ) -> None:
        self.budget = budget or MechanicLedgerBudget()
        if isinstance(local_failure_threshold, bool) or local_failure_threshold < 1:
            raise MechanicsError("local_failure_threshold must be positive")
        self.local_failure_threshold = local_failure_threshold

    def propose(
        self,
        residual: ConsequenceResidual,
        context: MechanicContext,
        *,
        failed_local_attempts: int = 0,
    ) -> tuple[RepairCandidate, ...]:
        if isinstance(failed_local_attempts, bool) or failed_local_attempts < 0:
            raise MechanicsError("failed_local_attempts must be non-negative")
        mismatches = tuple(
            sorted(
                residual.consequential,
                key=lambda item: (-item.relevance, CHANNEL_ORDER.index(item.channel)),
            )
        )
        groups: dict[RepairCandidateKind, list[ChannelResidual]] = {}
        for mismatch in mismatches:
            kind = _local_kind(mismatch)
            groups.setdefault(kind, []).append(mismatch)

        candidates: list[RepairCandidate] = []
        for kind in sorted(groups, key=_KIND_PRIORITY.__getitem__):
            items = groups[kind]
            channels = tuple(sorted({item.channel for item in items}, key=CHANNEL_ORDER.index))
            refs = tuple(sorted({ref for item in items for ref in item.contributor_refs}))
            scope = MechanicScope(
                ScopeCeiling.LEVEL,
                game_scope=context.game_scope,
                level_scope=context.level_scope,
                region_tags=context.region_tags,
                object_roles=context.object_roles,
                state_tags=context.state_tags,
            )
            mode = (
                CompositionMode.DELAYED
                if kind is RepairCandidateKind.TEMPORAL_MODIFIER
                else CompositionMode.CONDITIONAL
            )
            candidates.append(
                _candidate(
                    residual.residual_id,
                    kind,
                    channels,
                    scope,
                    refs,
                    mode,
                    max(item.relevance for item in items),
                    "test the narrowest observed context before changing the base mechanic",
                )
            )

        if failed_local_attempts >= self.local_failure_threshold and mismatches:
            refs = tuple(sorted({ref for item in mismatches for ref in item.contributor_refs}))
            channels = tuple(sorted({item.channel for item in mismatches}, key=CHANNEL_ORDER.index))
            candidates.append(
                _candidate(
                    residual.residual_id,
                    RepairCandidateKind.BASE_REOPEN,
                    channels,
                    MechanicScope(ScopeCeiling.GAME, game_scope=context.game_scope),
                    refs,
                    CompositionMode.BASE,
                    max(item.relevance for item in mismatches) - 1,
                    "local modifiers failed repeatedly; reopen only implicated base channels",
                )
            )

        return tuple(candidates[: self.budget.max_candidates_per_residual])


class RepairTracker:
    """Bounded failure counts used to delay broad base reopening."""

    def __init__(self, *, max_residuals: int = 8) -> None:
        if isinstance(max_residuals, bool) or max_residuals <= 0:
            raise MechanicsError("max_residuals must be positive")
        self.max_residuals = max_residuals
        self._attempts: dict[str, int] = {}

    def failures(self, residual_id: str) -> int:
        return self._attempts.get(residual_id, 0)

    def record_local_failure(self, residual_id: str) -> int:
        identifier = _text(residual_id, field="residual_id")
        if identifier not in self._attempts and len(self._attempts) >= self.max_residuals:
            # Retain the largest failure burdens, with stable lexical tie-break.
            victim = min(self._attempts, key=lambda item: (self._attempts[item], item))
            del self._attempts[victim]
        self._attempts[identifier] = self._attempts.get(identifier, 0) + 1
        return self._attempts[identifier]

    def resolve(self, residual_id: str) -> None:
        self._attempts.pop(residual_id, None)

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "max_residuals": self.max_residuals,
            "attempts": dict(sorted(self._attempts.items())),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> RepairTracker:
        maximum = _int(value.get("max_residuals"), field="max_residuals")
        attempts = value.get("attempts")
        if not isinstance(attempts, Mapping):
            raise MechanicsError("repair attempts must be an object")
        tracker = cls(max_residuals=maximum)
        for key, raw_count in sorted(attempts.items()):
            identifier = _text(key, field="residual_id")
            count = _int(raw_count, field="repair failure count")
            if count <= 0:
                raise MechanicsError("repair failure counts must be positive")
            tracker._attempts[identifier] = count
        if len(tracker._attempts) > maximum:
            raise MechanicsError("restored repair tracker exceeds its bound")
        return tracker


def _local_kind(residual: ChannelResidual) -> RepairCandidateKind:
    if residual.channel in {
        ConsequenceChannel.CONTROLLED_DISPLACEMENT,
        ConsequenceChannel.OTHER_OBJECT_EFFECTS,
        ConsequenceChannel.TOPOLOGY_CHANGES,
    }:
        return RepairCandidateKind.OBJECT_OR_TERRAIN_MODIFIER
    if residual.channel is ConsequenceChannel.DELAYED_EFFECTS or residual.kind in {
        ResidualKind.MISSING_EFFECT,
        ResidualKind.UNEXPECTED_EFFECT,
    }:
        return RepairCandidateKind.TEMPORAL_MODIFIER
    return RepairCandidateKind.RESOURCE_OR_STATUS_MODIFIER


def _candidate(
    residual_id: str,
    kind: RepairCandidateKind,
    channels: tuple[ConsequenceChannel, ...],
    scope: MechanicScope,
    refs: tuple[MechanicRef, ...],
    mode: CompositionMode,
    priority: int,
    rationale: str,
) -> RepairCandidate:
    content: dict[str, JSONValue] = {
        "residual_id": residual_id,
        "kind": kind.value,
        "channels": [item.value for item in channels],
        "scope": scope.to_dict(),
        "refs": [item.to_dict() for item in refs],
        "mode": mode.value,
    }
    digest = sha256_json(content).removeprefix("sha256:")
    return RepairCandidate(
        candidate_id=f"repair:{digest[:24]}",
        residual_id=residual_id,
        kind=kind,
        channels=channels,
        scope=scope,
        implicated_refs=refs,
        suggested_mode=mode,
        priority=priority,
        rationale=rationale,
    )


def _enum[EnumT: StrEnum](enum_type: type[EnumT], value: object, *, field: str) -> EnumT:
    if not isinstance(value, str):
        raise MechanicsError(f"{field} must be a string")
    try:
        return enum_type(value)
    except ValueError as error:
        raise MechanicsError(f"unsupported {field}: {value!r}") from error


def _text(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise MechanicsError(f"{field} must be a non-empty string")
    return value


def _int(value: object, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise MechanicsError(f"{field} must be an integer")
    return value


__all__ = [
    "LocalRepairPlanner",
    "RepairCandidate",
    "RepairCandidateKind",
    "RepairTracker",
]
