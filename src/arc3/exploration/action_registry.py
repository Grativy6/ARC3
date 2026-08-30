"""Bounded receipt-derived bindings from opaque handles to canonical effects.

The registry is derived state.  It never edits observations, returned actions, or
trace receipts; contradictory consequences revise only the candidate projection.
"""

from __future__ import annotations

import hashlib
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import cast

from arc3.adapters import Observation
from arc3.perception.delta import measure_delta
from arc3.perception.metadata import observation_metadata
from arc3.types import ActionName, ActionRequest, FrameHash, JSONValue

from .effects import movement_displacements, state_features

_PROJECTION_SCHEMA = "arc3.action-effect-registry.v1"
_WIRE_ORDER: tuple[ActionName, ...] = tuple(
    action for action in ActionName if action is not ActionName.RESET
)
_WIRE_RANK: dict[ActionName, int] = {action: index for index, action in enumerate(_WIRE_ORDER)}


class ActionEffectStatus(StrEnum):
    """Revisable evidence status for one handle/effect binding."""

    CANDIDATE = "CANDIDATE"
    ACCEPTED = "ACCEPTED"
    AMBIGUOUS = "AMBIGUOUS"
    CONTRADICTED = "CONTRADICTED"
    REOPENED = "REOPENED"


class CanonicalEffectKind(StrEnum):
    """Observation-level effects with no raw action identifier semantics."""

    UNKNOWN = "unknown"
    NO_OP = "no-op"
    TRANSLATION = "translation"
    TRANSFORM = "transform"
    METADATA_ONLY = "metadata-only"
    TERMINAL = "terminal"
    RESTORE = "restore"


class CoordinateRelation(StrEnum):
    """Measured relationship between a coordinate payload and changed cells."""

    NOT_APPLICABLE = "not-applicable"
    NO_CHANGE = "no-change"
    LOCAL = "local"
    DISTANT = "distant"
    MIXED = "mixed"


@dataclass(frozen=True, slots=True)
class CanonicalActionEffect:
    """A canonical consequence description independent of its raw handle."""

    effect_kind: CanonicalEffectKind
    translation: tuple[int, int] | None
    coordinate_relation: CoordinateRelation
    restore_digest: FrameHash | None
    condition_signature: str

    def __post_init__(self) -> None:
        if not self.condition_signature.strip():
            raise ValueError("condition_signature must not be empty")
        if self.translation == (0, 0):
            raise ValueError("translation must be non-zero when present")
        if self.effect_kind is CanonicalEffectKind.TRANSLATION and self.translation is None:
            raise ValueError("a translation effect requires a translation")
        if (
            self.effect_kind
            not in {
                CanonicalEffectKind.TRANSLATION,
                CanonicalEffectKind.TERMINAL,
                CanonicalEffectKind.RESTORE,
            }
            and self.translation is not None
        ):
            raise ValueError("only translation, terminal, or restore effects may carry translation")
        if self.effect_kind is CanonicalEffectKind.RESTORE and self.restore_digest is None:
            raise ValueError("a restore effect requires restore_digest")
        if self.effect_kind is not CanonicalEffectKind.RESTORE and self.restore_digest is not None:
            raise ValueError("only a restore effect may carry restore_digest")

    @property
    def semantic_key(self) -> tuple[str, int, int, str, str, str]:
        """Return a deterministic ordering key containing no raw handle."""

        dx, dy = self.translation or (0, 0)
        return (
            self.effect_kind.value,
            dx,
            dy,
            self.coordinate_relation.value,
            str(self.restore_digest or ""),
            self.condition_signature,
        )

    def projection(self) -> dict[str, JSONValue]:
        """Return a checkpoint-safe JSON projection."""

        return {
            "effect_kind": self.effect_kind.value,
            "translation": list(self.translation) if self.translation is not None else None,
            "coordinate_relation": self.coordinate_relation.value,
            "restore_digest": str(self.restore_digest) if self.restore_digest is not None else None,
            "condition_signature": self.condition_signature,
        }

    @classmethod
    def from_projection(cls, value: Mapping[str, object]) -> CanonicalActionEffect:
        """Restore one canonical effect from a validated projection."""

        raw_translation = value.get("translation")
        translation: tuple[int, int] | None
        if raw_translation is None:
            translation = None
        elif (
            isinstance(raw_translation, Sequence)
            and not isinstance(raw_translation, (str, bytes))
            and len(raw_translation) == 2
            and all(
                isinstance(item, int) and not isinstance(item, bool) for item in raw_translation
            )
        ):
            translation = (cast(int, raw_translation[0]), cast(int, raw_translation[1]))
        else:
            raise ValueError("canonical effect translation must be null or two integers")
        raw_restore = value.get("restore_digest")
        if raw_restore is not None and not isinstance(raw_restore, str):
            raise ValueError("restore_digest must be null or a string")
        condition = value.get("condition_signature")
        kind = value.get("effect_kind")
        relation = value.get("coordinate_relation")
        if (
            not isinstance(condition, str)
            or not isinstance(kind, str)
            or not isinstance(relation, str)
        ):
            raise ValueError("canonical effect projection has invalid scalar fields")
        return cls(
            effect_kind=CanonicalEffectKind(kind),
            translation=translation,
            coordinate_relation=CoordinateRelation(relation),
            restore_digest=FrameHash(raw_restore) if raw_restore is not None else None,
            condition_signature=condition,
        )


@dataclass(frozen=True, slots=True)
class ActionEffectCandidate:
    """One evidence-backed, revisable binding for an opaque raw handle."""

    raw_handle: ActionName
    canonical_effect: CanonicalActionEffect
    support_count: int
    contradiction_count: int
    source_event_ids: tuple[str, ...]
    status: ActionEffectStatus

    def __post_init__(self) -> None:
        if self.raw_handle is ActionName.RESET:
            raise ValueError("RESET is a lifecycle action, not a gameplay effect handle")
        for name, value in (
            ("support_count", self.support_count),
            ("contradiction_count", self.contradiction_count),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")
        if self.support_count == 0:
            raise ValueError("an action-effect candidate requires supporting evidence")
        if not self.source_event_ids or any(not item.strip() for item in self.source_event_ids):
            raise ValueError("source_event_ids must contain non-empty receipt identifiers")
        if len(set(self.source_event_ids)) != len(self.source_event_ids):
            raise ValueError("source_event_ids must not contain duplicates")

    @property
    def semantic_key(self) -> tuple[str, int, int, str, str, str]:
        return self.canonical_effect.semantic_key

    def projection(self) -> dict[str, JSONValue]:
        return {
            "raw_handle": self.raw_handle.value,
            "canonical_effect": self.canonical_effect.projection(),
            "support_count": self.support_count,
            "contradiction_count": self.contradiction_count,
            "source_event_ids": list(self.source_event_ids),
            "status": self.status.value,
        }

    @classmethod
    def from_projection(cls, value: Mapping[str, object]) -> ActionEffectCandidate:
        raw_handle = value.get("raw_handle")
        raw_effect = value.get("canonical_effect")
        support = value.get("support_count")
        contradictions = value.get("contradiction_count")
        sources = value.get("source_event_ids")
        status = value.get("status")
        if not isinstance(raw_handle, str) or not isinstance(status, str):
            raise ValueError("candidate handle and status must be strings")
        if not isinstance(raw_effect, Mapping):
            raise ValueError("candidate canonical_effect must be an object")
        if isinstance(support, bool) or not isinstance(support, int):
            raise ValueError("candidate support_count must be an integer")
        if isinstance(contradictions, bool) or not isinstance(contradictions, int):
            raise ValueError("candidate contradiction_count must be an integer")
        if not isinstance(sources, Sequence) or isinstance(sources, (str, bytes)):
            raise ValueError("candidate source_event_ids must be an array")
        source_ids = tuple(sources)
        if any(not isinstance(item, str) for item in source_ids):
            raise ValueError("candidate source_event_ids must contain strings")
        return cls(
            raw_handle=ActionName(raw_handle),
            canonical_effect=CanonicalActionEffect.from_projection(
                cast(Mapping[str, object], raw_effect)
            ),
            support_count=support,
            contradiction_count=contradictions,
            source_event_ids=cast(tuple[str, ...], source_ids),
            status=ActionEffectStatus(status),
        )


@dataclass(frozen=True, slots=True)
class ActionEffectObservation:
    """A compact derived observation retaining immutable receipt identities."""

    source_event_id: str
    raw_handle: ActionName
    canonical_effects: tuple[CanonicalActionEffect, ...]
    before_digest: FrameHash
    after_digest: FrameHash

    def __post_init__(self) -> None:
        if not self.source_event_id.strip():
            raise ValueError("source_event_id must not be empty")
        if self.raw_handle is ActionName.RESET:
            raise ValueError("RESET consequences do not enter the gameplay registry")
        if not self.canonical_effects:
            raise ValueError("an action-effect observation needs at least one candidate effect")
        ordered = tuple(sorted(set(self.canonical_effects), key=lambda item: item.semantic_key))
        object.__setattr__(self, "canonical_effects", ordered)

    @property
    def ambiguous(self) -> bool:
        """Whether one receipt supports more than one canonical consequence."""

        return len(self.canonical_effects) > 1


def _coordinate_relation(
    before: Observation,
    action: ActionRequest,
    after: Observation,
) -> CoordinateRelation:
    coordinate = action.coordinate
    if coordinate is None:
        return CoordinateRelation.NOT_APPLICABLE
    delta = measure_delta(
        before.frames[-1],
        after.frames[-1],
        before_metadata=observation_metadata(before),
        after_metadata=observation_metadata(after),
    )
    if not delta.cell_changes:
        return CoordinateRelation.NO_CHANGE
    locality = tuple(
        change.x == coordinate.x and change.y == coordinate.y for change in delta.cell_changes
    )
    if all(locality):
        return CoordinateRelation.LOCAL
    if not any(locality):
        return CoordinateRelation.DISTANT
    return CoordinateRelation.MIXED


def action_condition_signature(observation: Observation) -> str:
    """Return a bounded structural condition key, excluding game and action identity."""

    features = state_features(observation)
    material = (
        "arc3.action-condition.v1",
        features.width,
        features.height,
        features.palette_size,
        features.component_count,
        features.game_state.value,
        len(features.available_actions),
        features.condition_tokens,
    )
    return f"condition:{hashlib.sha256(repr(material).encode()).hexdigest()}"


def derive_action_effect_observation(
    before: Observation,
    action: ActionRequest,
    after: Observation,
    *,
    source_event_id: str,
    prior_frame_hashes: Collection[FrameHash] = (),
) -> ActionEffectObservation:
    """Derive canonical candidates solely from before/action/consequence receipts."""

    if action.name is ActionName.RESET:
        raise ValueError("RESET consequences do not enter the gameplay registry")
    if after.returned_action is not None and after.returned_action != action:
        raise ValueError("returned consequence does not match the submitted action")
    before_grid = before.frames[-1]
    after_grid = after.frames[-1]
    delta = measure_delta(
        before_grid,
        after_grid,
        before_metadata=observation_metadata(before),
        after_metadata=observation_metadata(after),
    )
    condition = action_condition_signature(before)
    relation = _coordinate_relation(before, action, after)
    translations = movement_displacements(before, after)
    restored = after_grid.digest != before_grid.digest and after_grid.digest in prior_frame_hashes
    became_terminal = before.state != after.state and after.state.value in {"WIN", "GAME_OVER"}

    effects: tuple[CanonicalActionEffect, ...]
    if restored:
        effects = tuple(
            CanonicalActionEffect(
                CanonicalEffectKind.RESTORE,
                translation,
                relation,
                after_grid.digest,
                condition,
            )
            for translation in (translations or (None,))
        )
    elif became_terminal:
        effects = (
            CanonicalActionEffect(
                CanonicalEffectKind.TERMINAL,
                translations[0] if len(translations) == 1 else None,
                relation,
                None,
                condition,
            ),
        )
    elif translations:
        effects = tuple(
            CanonicalActionEffect(
                CanonicalEffectKind.TRANSLATION,
                translation,
                relation,
                None,
                condition,
            )
            for translation in translations
        )
    elif delta.cell_changes:
        effects = (
            CanonicalActionEffect(
                CanonicalEffectKind.TRANSFORM,
                None,
                relation,
                None,
                condition,
            ),
        )
    elif delta.metadata_changes:
        effects = (
            CanonicalActionEffect(
                CanonicalEffectKind.METADATA_ONLY,
                None,
                relation,
                None,
                condition,
            ),
        )
    else:
        effects = (
            CanonicalActionEffect(
                CanonicalEffectKind.NO_OP,
                None,
                relation,
                None,
                condition,
            ),
        )
    return ActionEffectObservation(
        source_event_id=source_event_id,
        raw_handle=action.name,
        canonical_effects=effects,
        before_digest=before_grid.digest,
        after_digest=after_grid.digest,
    )


class ActionEffectRegistry:
    """Bounded episode/level index over immutable transition receipts."""

    def __init__(
        self,
        *,
        level_index: int = 0,
        max_raw_handles: int = 7,
        max_candidates_per_handle: int = 32,
    ) -> None:
        if isinstance(level_index, bool) or not isinstance(level_index, int) or level_index < 0:
            raise ValueError("level_index must be a non-negative integer")
        for name, value in (
            ("max_raw_handles", max_raw_handles),
            ("max_candidates_per_handle", max_candidates_per_handle),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"{name} must be a positive integer")
        if max_raw_handles > 7:
            raise ValueError("max_raw_handles must not exceed the seven gameplay handles")
        if max_candidates_per_handle > 32:
            raise ValueError("max_candidates_per_handle must not exceed 32")
        self._level_index = level_index
        self._max_raw_handles = max_raw_handles
        self._max_candidates_per_handle = max_candidates_per_handle
        self._handles: set[ActionName] = set()
        self._candidates: dict[tuple[ActionName, CanonicalActionEffect], ActionEffectCandidate] = {}
        self._observation_counts: dict[ActionName, int] = {}
        self._processed_event_ids: set[str] = set()

    @property
    def level_index(self) -> int:
        """Level to which this episode-local derived registry is bound."""

        return self._level_index

    @property
    def max_raw_handles(self) -> int:
        return self._max_raw_handles

    @property
    def max_candidates_per_handle(self) -> int:
        return self._max_candidates_per_handle

    @property
    def handles(self) -> tuple[ActionName, ...]:
        return tuple(sorted(self._handles, key=_WIRE_RANK.__getitem__))

    @property
    def candidate_count(self) -> int:
        return len(self._candidates)

    def register_handles(self, handles: Collection[ActionName]) -> None:
        """Register advertised opaque handles without assigning gameplay semantics."""

        gameplay = {handle for handle in handles if handle is not ActionName.RESET}
        if len(self._handles | gameplay) > self._max_raw_handles:
            raise ValueError("action-effect registry raw-handle bound exceeded")
        self._handles.update(gameplay)

    def observation_count(self, raw_handle: ActionName) -> int:
        return self._observation_counts.get(raw_handle, 0)

    def observe_transition(
        self,
        before: Observation,
        action: ActionRequest,
        after: Observation,
        *,
        source_event_id: str,
        prior_frame_hashes: Collection[FrameHash] = (),
    ) -> ActionEffectObservation:
        """Append derived support/contradiction counts for one returned consequence."""

        if source_event_id in self._processed_event_ids:
            raise ValueError("source_event_id has already been processed")
        observation = derive_action_effect_observation(
            before,
            action,
            after,
            source_event_id=source_event_id,
            prior_frame_hashes=prior_frame_hashes,
        )
        self.register_handles((action.name,))
        handle_candidates = sum(
            candidate.raw_handle is action.name for candidate in self._candidates.values()
        )
        new_effects = tuple(
            effect
            for effect in observation.canonical_effects
            if (action.name, effect) not in self._candidates
        )
        if handle_candidates + len(new_effects) > self._max_candidates_per_handle:
            raise ValueError("action-effect registry per-handle candidate bound exceeded")

        condition = observation.canonical_effects[0].condition_signature
        observed_effects = frozenset(observation.canonical_effects)
        reopened = False
        for key, candidate in tuple(self._candidates.items()):
            if (
                candidate.raw_handle is not action.name
                or candidate.canonical_effect.condition_signature != condition
                or candidate.canonical_effect in observed_effects
            ):
                continue
            contradictions = candidate.contradiction_count + 1
            status = (
                ActionEffectStatus.REOPENED
                if contradictions <= candidate.support_count
                else ActionEffectStatus.CONTRADICTED
            )
            reopened = reopened or status is ActionEffectStatus.REOPENED
            sources = candidate.source_event_ids
            if source_event_id not in sources:
                sources += (source_event_id,)
            self._candidates[key] = replace(
                candidate,
                contradiction_count=contradictions,
                source_event_ids=sources,
                status=status,
            )

        prior_statuses: dict[CanonicalActionEffect, ActionEffectStatus | None] = {}
        for effect in observation.canonical_effects:
            key = (action.name, effect)
            existing = self._candidates.get(key)
            prior_statuses[effect] = existing.status if existing is not None else None
            if existing is None:
                self._candidates[key] = ActionEffectCandidate(
                    raw_handle=action.name,
                    canonical_effect=effect,
                    support_count=1,
                    contradiction_count=0,
                    source_event_ids=(source_event_id,),
                    status=ActionEffectStatus.CANDIDATE,
                )
            else:
                sources = existing.source_event_ids
                if source_event_id not in sources:
                    sources += (source_event_id,)
                self._candidates[key] = replace(
                    existing,
                    support_count=existing.support_count + 1,
                    source_event_ids=sources,
                    status=ActionEffectStatus.CANDIDATE,
                )

        ambiguous = observation.ambiguous or reopened
        for effect in observation.canonical_effects:
            key = (action.name, effect)
            candidate = self._candidates[key]
            was_revising = prior_statuses[effect] in {
                ActionEffectStatus.REOPENED,
                ActionEffectStatus.CONTRADICTED,
            }
            sufficiently_reconfirmed = candidate.support_count > candidate.contradiction_count
            self._candidates[key] = replace(
                candidate,
                status=(
                    ActionEffectStatus.AMBIGUOUS
                    if ambiguous
                    else (
                        ActionEffectStatus.REOPENED
                        if was_revising and not sufficiently_reconfirmed
                        else ActionEffectStatus.ACCEPTED
                    )
                ),
            )
        self._observation_counts[action.name] = self.observation_count(action.name) + 1
        self._processed_event_ids.add(source_event_id)
        return observation

    def candidates_for(
        self,
        raw_handle: ActionName,
        *,
        condition_signature: str | None = None,
    ) -> tuple[ActionEffectCandidate, ...]:
        """Return stable candidate state without mutating the registry."""

        return tuple(
            sorted(
                (
                    candidate
                    for candidate in self._candidates.values()
                    if candidate.raw_handle is raw_handle
                    and (
                        condition_signature is None
                        or candidate.canonical_effect.condition_signature == condition_signature
                    )
                ),
                key=lambda item: (item.semantic_key, item.status.value),
            )
        )

    def accepted_effects(
        self,
        raw_handle: ActionName,
        *,
        condition_signature: str | None = None,
    ) -> tuple[CanonicalActionEffect, ...]:
        return tuple(
            candidate.canonical_effect
            for candidate in self.candidates_for(
                raw_handle,
                condition_signature=condition_signature,
            )
            if candidate.status is ActionEffectStatus.ACCEPTED
        )

    def best_effect(
        self,
        raw_handle: ActionName,
        *,
        condition_signature: str | None = None,
    ) -> CanonicalActionEffect | None:
        accepted = self.accepted_effects(
            raw_handle,
            condition_signature=condition_signature,
        )
        return min(accepted, key=lambda effect: effect.semantic_key) if accepted else None

    def accepted_translation(
        self,
        raw_handle: ActionName,
        *,
        condition_signature: str | None = None,
    ) -> tuple[int, int] | None:
        """Return a uniquely supported displacement facet for one opaque handle.

        Restore and terminal annotations are orthogonal to displacement: the
        same handle can restore a preserved frame on one receipt and make the
        same ordinary translation on another.  Whole-effect candidates remain
        revisable and ambiguous, but those annotations must not erase a
        displacement on which every live candidate agrees.  A live candidate
        without a displacement, or two differing live displacements, keeps the
        translation facet unresolved.
        """

        live = tuple(
            candidate
            for candidate in self.candidates_for(
                raw_handle,
                condition_signature=condition_signature,
            )
            if candidate.status is not ActionEffectStatus.CONTRADICTED
        )
        if not live or any(candidate.canonical_effect.translation is None for candidate in live):
            return None
        translations = {
            candidate.canonical_effect.translation
            for candidate in live
            if candidate.canonical_effect.translation is not None
        }
        if len(translations) != 1:
            return None
        supported = any(
            candidate.support_count > candidate.contradiction_count for candidate in live
        )
        return next(iter(translations)) if supported else None

    def resolve(
        self,
        canonical_effect: CanonicalActionEffect,
        *,
        available_actions: Collection[ActionName] = (),
    ) -> ActionName | None:
        """Resolve an accepted canonical effect, using raw order only after semantic equality."""

        allowed = set(available_actions) if available_actions else set(self._handles)
        matches = tuple(
            candidate.raw_handle
            for candidate in self._candidates.values()
            if candidate.status is ActionEffectStatus.ACCEPTED
            and candidate.canonical_effect == canonical_effect
            and candidate.raw_handle in allowed
        )
        return min(matches, key=_WIRE_RANK.__getitem__) if matches else None

    def resolve_translation(
        self,
        translation: tuple[int, int],
        *,
        condition_signature: str | None = None,
        available_actions: Collection[ActionName] = (),
    ) -> ActionName | None:
        """Resolve observed translation semantics without a cardinal-name prior."""

        allowed = set(available_actions) if available_actions else set(self._handles)
        matches = tuple(
            raw_handle
            for raw_handle in allowed
            if raw_handle is not ActionName.RESET
            and self.accepted_translation(
                raw_handle,
                condition_signature=condition_signature,
            )
            == translation
        )
        if not matches:
            return None
        return min(matches, key=_WIRE_RANK.__getitem__)

    def unseen_handles(self, available_actions: Collection[ActionName]) -> tuple[ActionName, ...]:
        return tuple(
            action
            for action in sorted(
                (item for item in available_actions if item is not ActionName.RESET),
                key=_WIRE_RANK.__getitem__,
            )
            if self.observation_count(action) == 0
        )

    def canonical_order(
        self,
        available_actions: Collection[ActionName],
        *,
        condition_signature: str | None = None,
    ) -> tuple[ActionName, ...]:
        """Order handles by learned semantics, then raw identity only for true ties."""

        def key(action: ActionName) -> tuple[int, tuple[str, int, int, str, str, str], int]:
            condition_candidates = self.candidates_for(
                action,
                condition_signature=condition_signature,
            )
            effect = self.best_effect(action, condition_signature=condition_signature)
            if effect is not None:
                return 0, effect.semantic_key, _WIRE_RANK[action]
            translation = self.accepted_translation(
                action,
                condition_signature=condition_signature,
            )
            if translation is None and condition_signature is not None and not condition_candidates:
                # A changed structural condition can be unseen because a mover
                # or target is temporarily occluded.  Preserve the condition-
                # scoped receipts, but retain equivariant ordering when every
                # live observation of this handle supports one displacement.
                # Any evidence in the current condition, including ambiguity,
                # prevents this cross-condition fallback.
                translation = self.accepted_translation(action)
            if translation is not None:
                dx, dy = translation
                return (
                    0,
                    (
                        CanonicalEffectKind.TRANSLATION.value,
                        dx,
                        dy,
                        CoordinateRelation.NOT_APPLICABLE.value,
                        "",
                        condition_signature or "",
                    ),
                    _WIRE_RANK[action],
                )
            has_evidence = bool(condition_candidates)
            rank = 1 if has_evidence else 2
            unknown_key = (
                CanonicalEffectKind.UNKNOWN.value,
                0,
                0,
                CoordinateRelation.NOT_APPLICABLE.value,
                "",
                "",
            )
            return rank, unknown_key, _WIRE_RANK[action]

        gameplay = (item for item in available_actions if item is not ActionName.RESET)
        return tuple(sorted(set(gameplay), key=key))

    def projection(self) -> dict[str, JSONValue]:
        """Return a deterministic checkpoint projection of all derived state."""

        candidates = sorted(
            self._candidates.values(),
            key=lambda item: (_WIRE_RANK[item.raw_handle], item.semantic_key),
        )
        return {
            "schema": _PROJECTION_SCHEMA,
            "level_index": self._level_index,
            "max_raw_handles": self._max_raw_handles,
            "max_candidates_per_handle": self._max_candidates_per_handle,
            "handles": [handle.value for handle in self.handles],
            "observation_counts": {
                handle.value: self.observation_count(handle) for handle in self.handles
            },
            "processed_event_ids": cast(list[JSONValue], sorted(self._processed_event_ids)),
            "candidates": [candidate.projection() for candidate in candidates],
        }

    checkpoint_projection = projection

    @classmethod
    def from_projection(cls, value: Mapping[str, object]) -> ActionEffectRegistry:
        """Restore a registry without fabricating or resubmitting evidence."""

        if value.get("schema") != _PROJECTION_SCHEMA:
            raise ValueError("unsupported action-effect registry projection schema")
        max_handles = value.get("max_raw_handles")
        max_candidates = value.get("max_candidates_per_handle")
        level_index = value.get("level_index")
        if isinstance(level_index, bool) or not isinstance(level_index, int):
            raise ValueError("level_index must be an integer")
        if isinstance(max_handles, bool) or not isinstance(max_handles, int):
            raise ValueError("max_raw_handles must be an integer")
        if isinstance(max_candidates, bool) or not isinstance(max_candidates, int):
            raise ValueError("max_candidates_per_handle must be an integer")
        registry = cls(
            level_index=level_index,
            max_raw_handles=max_handles,
            max_candidates_per_handle=max_candidates,
        )
        raw_handles = value.get("handles")
        if not isinstance(raw_handles, Sequence) or isinstance(raw_handles, (str, bytes)):
            raise ValueError("handles must be an array")
        handles = tuple(ActionName(item) for item in raw_handles if isinstance(item, str))
        if len(handles) != len(raw_handles):
            raise ValueError("handles must contain action-name strings")
        registry.register_handles(handles)

        raw_candidates = value.get("candidates")
        if not isinstance(raw_candidates, Sequence) or isinstance(raw_candidates, (str, bytes)):
            raise ValueError("candidates must be an array")
        for item in raw_candidates:
            if not isinstance(item, Mapping):
                raise ValueError("candidate projection entries must be objects")
            candidate = ActionEffectCandidate.from_projection(cast(Mapping[str, object], item))
            registry.register_handles((candidate.raw_handle,))
            key = (candidate.raw_handle, candidate.canonical_effect)
            if key in registry._candidates:
                raise ValueError("candidate projection contains a duplicate binding")
            per_handle = sum(
                current.raw_handle is candidate.raw_handle
                for current in registry._candidates.values()
            )
            if per_handle >= registry._max_candidates_per_handle:
                raise ValueError("candidate projection exceeds the per-handle bound")
            registry._candidates[key] = candidate

        raw_events = value.get("processed_event_ids")
        if not isinstance(raw_events, Sequence) or isinstance(raw_events, (str, bytes)):
            raise ValueError("processed_event_ids must be an array")
        if any(not isinstance(item, str) or not item for item in raw_events):
            raise ValueError("processed_event_ids must contain non-empty strings")
        if len(set(raw_events)) != len(raw_events):
            raise ValueError("processed_event_ids must not contain duplicates")
        candidate_events = {
            source
            for candidate in registry._candidates.values()
            for source in candidate.source_event_ids
        }
        if candidate_events != set(raw_events):
            raise ValueError("processed_event_ids do not match candidate evidence provenance")
        registry._processed_event_ids = cast(set[str], set(raw_events))

        raw_counts = value.get("observation_counts")
        if not isinstance(raw_counts, Mapping):
            raise ValueError("observation_counts must be an object")
        for raw_handle, count in raw_counts.items():
            if not isinstance(raw_handle, str):
                raise ValueError("observation count handles must be strings")
            if isinstance(count, bool) or not isinstance(count, int) or count < 0:
                raise ValueError("observation counts must be non-negative integers")
            handle = ActionName(raw_handle)
            if handle not in registry._handles:
                raise ValueError("observation count references an unregistered handle")
            registry._observation_counts[handle] = count
        return registry


__all__ = [
    "ActionEffectCandidate",
    "ActionEffectObservation",
    "ActionEffectRegistry",
    "ActionEffectStatus",
    "CanonicalActionEffect",
    "CanonicalEffectKind",
    "CoordinateRelation",
    "action_condition_signature",
    "derive_action_effect_observation",
]
