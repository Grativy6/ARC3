"""Focused coverage for receipt-derived opaque action semantics."""

from __future__ import annotations

import pytest

from arc3.adapters import GridFrame, Observation
from arc3.exploration import (
    ActionEffectRegistry,
    ActionEffectStatus,
    CanonicalEffectKind,
    CoordinateRelation,
    action_condition_signature,
    derive_action_effect_observation,
)
from arc3.types import ActionName, ActionRequest, Coordinate, GameId, GameStateName


def _observation(
    rows: list[list[int]],
    *,
    available: tuple[ActionName, ...] = (
        ActionName.ACTION1,
        ActionName.ACTION2,
        ActionName.ACTION6,
        ActionName.ACTION7,
    ),
    returned_action: ActionRequest | None = None,
) -> Observation:
    return Observation(
        game_id=GameId("synthetic-fixture"),
        frames=(GridFrame.from_rows(rows),),
        state=GameStateName.NOT_FINISHED,
        levels_completed=0,
        win_levels=1,
        available_actions=available,
        returned_action=returned_action,
    )


_CENTER = _observation(
    [[0, 0, 0], [0, 1, 0], [0, 0, 0]],
)
_RIGHT = _observation(
    [[0, 0, 0], [0, 0, 1], [0, 0, 0]],
)
_LEFT = _observation(
    [[0, 0, 0], [1, 0, 0], [0, 0, 0]],
)


def test_canonical_translation_is_independent_of_raw_handle() -> None:
    first = ActionEffectRegistry(level_index=2)
    second = ActionEffectRegistry(level_index=2)

    first_observation = first.observe_transition(
        _CENTER,
        ActionRequest(ActionName.ACTION1),
        _RIGHT,
        source_event_id="event-first",
    )
    second_observation = second.observe_transition(
        _CENTER,
        ActionRequest(ActionName.ACTION7),
        _RIGHT,
        source_event_id="event-second",
    )

    assert first_observation.canonical_effects == second_observation.canonical_effects
    effect = first_observation.canonical_effects[0]
    assert effect.effect_kind is CanonicalEffectKind.TRANSLATION
    assert effect.translation == (1, 0)
    assert not hasattr(effect, "raw_handle")
    assert first.resolve_translation((1, 0)) is ActionName.ACTION1
    assert second.resolve_translation((1, 0)) is ActionName.ACTION7


def test_multiple_supported_displacements_remain_ambiguous() -> None:
    before = _observation(
        [
            [0, 0, 0, 0, 0],
            [0, 1, 0, 0, 0],
            [0, 0, 0, 0, 0],
            [0, 0, 0, 2, 2],
            [0, 0, 0, 0, 0],
        ]
    )
    after = _observation(
        [
            [0, 0, 0, 0, 0],
            [0, 0, 1, 0, 0],
            [0, 0, 0, 2, 2],
            [0, 0, 0, 0, 0],
            [0, 0, 0, 0, 0],
        ]
    )
    registry = ActionEffectRegistry()

    observed = registry.observe_transition(
        before,
        ActionRequest(ActionName.ACTION2),
        after,
        source_event_id="event-ambiguous",
    )

    assert observed.ambiguous is True
    assert {effect.translation for effect in observed.canonical_effects} == {(1, 0), (0, -1)}
    assert {item.status for item in registry.candidates_for(ActionName.ACTION2)} == {
        ActionEffectStatus.AMBIGUOUS
    }
    assert registry.accepted_effects(ActionName.ACTION2) == ()


def test_contradictions_reopen_then_require_net_reconfirmation_and_roundtrip() -> None:
    registry = ActionEffectRegistry(level_index=3)
    action = ActionRequest(ActionName.ACTION1)
    registry.observe_transition(_CENTER, action, _RIGHT, source_event_id="e1")
    registry.observe_transition(_CENTER, action, _LEFT, source_event_id="e2")
    registry.observe_transition(_CENTER, action, _LEFT, source_event_id="e3")

    right = next(
        item
        for item in registry.candidates_for(ActionName.ACTION1)
        if item.canonical_effect.translation == (1, 0)
    )
    assert right.status is ActionEffectStatus.CONTRADICTED
    assert right.source_event_ids == ("e1", "e2", "e3")

    registry.observe_transition(_CENTER, action, _RIGHT, source_event_id="e4")
    right = next(
        item
        for item in registry.candidates_for(ActionName.ACTION1)
        if item.canonical_effect.translation == (1, 0)
    )
    assert right.status is ActionEffectStatus.AMBIGUOUS
    assert right.support_count == right.contradiction_count == 2
    assert right.source_event_ids == ("e1", "e2", "e3", "e4")

    projection = registry.projection()
    restored = ActionEffectRegistry.from_projection(projection)
    assert restored.projection() == projection
    assert restored.level_index == 3

    restored.observe_transition(_CENTER, action, _RIGHT, source_event_id="e5")
    still_ambiguous = next(
        item
        for item in restored.candidates_for(ActionName.ACTION1)
        if item.canonical_effect.translation == (1, 0)
    )
    assert still_ambiguous.status is ActionEffectStatus.AMBIGUOUS
    restored.observe_transition(_CENTER, action, _RIGHT, source_event_id="e6")
    reconfirmed = next(
        item
        for item in restored.candidates_for(ActionName.ACTION1)
        if item.canonical_effect.translation == (1, 0)
    )
    assert reconfirmed.status is ActionEffectStatus.ACCEPTED


def test_conditioned_noop_and_translation_do_not_contradict_each_other() -> None:
    one_component = _CENTER
    two_components = _observation(
        [[0, 0, 2], [0, 1, 0], [0, 0, 0]],
    )
    two_components_moved = _observation(
        [[0, 0, 2], [0, 0, 1], [0, 0, 0]],
    )
    action = ActionRequest(ActionName.ACTION2)
    registry = ActionEffectRegistry()

    registry.observe_transition(
        one_component,
        action,
        one_component,
        source_event_id="noop-condition",
    )
    registry.observe_transition(
        two_components,
        action,
        two_components_moved,
        source_event_id="movement-condition",
    )

    assert action_condition_signature(one_component) != action_condition_signature(two_components)
    candidates = registry.candidates_for(ActionName.ACTION2)
    assert {item.canonical_effect.effect_kind for item in candidates} == {
        CanonicalEffectKind.NO_OP,
        CanonicalEffectKind.TRANSLATION,
    }
    assert all(item.status is ActionEffectStatus.ACCEPTED for item in candidates)
    assert all(item.contradiction_count == 0 for item in candidates)


def test_restore_and_coordinate_relation_are_receipt_derived() -> None:
    registry = ActionEffectRegistry()
    arbitrary_restore = registry.observe_transition(
        _RIGHT,
        ActionRequest(ActionName.ACTION2),
        _CENTER,
        source_event_id="restore-action2",
        prior_frame_hashes=(_CENTER.frames[-1].digest,),
    )
    action7_transform = registry.observe_transition(
        _CENTER,
        ActionRequest(ActionName.ACTION7),
        _observation([[0, 0, 0], [0, 2, 0], [0, 0, 0]]),
        source_event_id="action7-negative",
        prior_frame_hashes=(_RIGHT.frames[-1].digest,),
    )

    assert arbitrary_restore.canonical_effects[0].effect_kind is CanonicalEffectKind.RESTORE
    assert arbitrary_restore.canonical_effects[0].translation == (-1, 0)
    assert registry.resolve_translation((-1, 0)) is ActionName.ACTION2
    assert action7_transform.canonical_effects[0].effect_kind is CanonicalEffectKind.TRANSFORM

    local = derive_action_effect_observation(
        _CENTER,
        ActionRequest(ActionName.ACTION6, Coordinate(1, 1)),
        _observation([[0, 0, 0], [0, 2, 0], [0, 0, 0]]),
        source_event_id="coordinate-local",
    )
    distant = derive_action_effect_observation(
        _CENTER,
        ActionRequest(ActionName.ACTION6, Coordinate(0, 0)),
        _observation([[0, 0, 0], [0, 2, 0], [0, 0, 0]]),
        source_event_id="coordinate-distant",
    )
    assert local.canonical_effects[0].coordinate_relation is CoordinateRelation.LOCAL
    assert distant.canonical_effects[0].coordinate_relation is CoordinateRelation.DISTANT


def test_inverse_translation_returning_to_prior_digest_keeps_both_semantics() -> None:
    registry = ActionEffectRegistry(level_index=4)
    registry.observe_transition(
        _CENTER,
        ActionRequest(ActionName.ACTION1),
        _RIGHT,
        source_event_id="forward",
        prior_frame_hashes=(_CENTER.frames[-1].digest,),
    )
    inverse = registry.observe_transition(
        _RIGHT,
        ActionRequest(ActionName.ACTION2),
        _CENTER,
        source_event_id="inverse-restores",
        prior_frame_hashes=(_CENTER.frames[-1].digest, _RIGHT.frames[-1].digest),
    )

    assert inverse.ambiguous is False
    assert len(inverse.canonical_effects) == 1
    combined = inverse.canonical_effects[0]
    assert combined.effect_kind is CanonicalEffectKind.RESTORE
    assert combined.restore_digest == _CENTER.frames[-1].digest
    assert combined.translation == (-1, 0)
    assert registry.resolve_translation((-1, 0)) is ActionName.ACTION2

    projection = registry.checkpoint_projection()
    restored = ActionEffectRegistry.from_projection(projection)
    assert restored.projection() == projection
    assert restored.resolve_translation((-1, 0)) is ActionName.ACTION2
    restored_inverse = restored.accepted_effects(ActionName.ACTION2)
    assert restored_inverse == (combined,)


def test_restore_then_ordinary_motion_retains_unique_translation_facet() -> None:
    registry = ActionEffectRegistry()
    action = ActionRequest(ActionName.ACTION2)
    registry.observe_transition(
        _RIGHT,
        action,
        _CENTER,
        source_event_id="restore-with-translation",
        prior_frame_hashes=(_CENTER.frames[-1].digest,),
    )
    registry.observe_transition(
        _CENTER,
        action,
        _LEFT,
        source_event_id="ordinary-same-translation",
        prior_frame_hashes=(),
    )

    assert registry.accepted_effects(ActionName.ACTION2) == ()
    assert registry.accepted_translation(ActionName.ACTION2) == (-1, 0)
    assert registry.resolve_translation((-1, 0)) is ActionName.ACTION2
    assert {candidate.status for candidate in registry.candidates_for(ActionName.ACTION2)} == {
        ActionEffectStatus.AMBIGUOUS,
        ActionEffectStatus.REOPENED,
    }


def test_conflicting_live_translations_do_not_resolve_translation_facet() -> None:
    registry = ActionEffectRegistry()
    action = ActionRequest(ActionName.ACTION2)
    registry.observe_transition(
        _CENTER,
        action,
        _RIGHT,
        source_event_id="translation-right",
    )
    registry.observe_transition(
        _CENTER,
        action,
        _LEFT,
        source_event_id="translation-left",
    )

    assert registry.accepted_translation(ActionName.ACTION2) is None
    assert registry.resolve_translation((1, 0)) is None
    assert registry.resolve_translation((-1, 0)) is None


def test_canonical_order_uses_translation_facet_before_raw_wire_identity() -> None:
    def build(left_handle: ActionName, right_handle: ActionName) -> ActionEffectRegistry:
        registry = ActionEffectRegistry()
        registry.observe_transition(
            _RIGHT,
            ActionRequest(left_handle),
            _CENTER,
            source_event_id=f"{left_handle.value}-restore-left",
            prior_frame_hashes=(_CENTER.frames[-1].digest,),
        )
        registry.observe_transition(
            _CENTER,
            ActionRequest(left_handle),
            _LEFT,
            source_event_id=f"{left_handle.value}-ordinary-left",
        )
        registry.observe_transition(
            _CENTER,
            ActionRequest(right_handle),
            _RIGHT,
            source_event_id=f"{right_handle.value}-ordinary-right",
        )
        return registry

    base = build(ActionName.ACTION1, ActionName.ACTION2)
    remapped = build(ActionName.ACTION7, ActionName.ACTION1)

    base_order = base.canonical_order((ActionName.ACTION1, ActionName.ACTION2))
    remapped_order = remapped.canonical_order((ActionName.ACTION7, ActionName.ACTION1))
    assert tuple(base.accepted_translation(handle) for handle in base_order) == (
        (-1, 0),
        (1, 0),
    )
    assert tuple(remapped.accepted_translation(handle) for handle in remapped_order) == (
        (-1, 0),
        (1, 0),
    )

    unseen_condition = action_condition_signature(_observation([[2, 0, 0], [0, 1, 0], [0, 0, 0]]))
    assert all(
        not base.candidates_for(handle, condition_signature=unseen_condition)
        for handle in (ActionName.ACTION1, ActionName.ACTION2)
    )
    base_unseen_order = base.canonical_order(
        (ActionName.ACTION1, ActionName.ACTION2),
        condition_signature=unseen_condition,
    )
    remapped_unseen_order = remapped.canonical_order(
        (ActionName.ACTION7, ActionName.ACTION1),
        condition_signature=unseen_condition,
    )
    assert tuple(base.accepted_translation(handle) for handle in base_unseen_order) == (
        (-1, 0),
        (1, 0),
    )
    assert tuple(remapped.accepted_translation(handle) for handle in remapped_unseen_order) == (
        (-1, 0),
        (1, 0),
    )


def test_current_condition_ambiguity_blocks_cross_condition_translation_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = ActionEffectRegistry()
    registry.observe_transition(
        _CENTER,
        ActionRequest(ActionName.ACTION1),
        _LEFT,
        source_event_id="prior-action1-left",
    )
    registry.observe_transition(
        _CENTER,
        ActionRequest(ActionName.ACTION2),
        _RIGHT,
        source_event_id="prior-action2-right",
    )
    current_before = _observation(
        [
            [0, 0, 0, 0, 0],
            [0, 0, 1, 0, 0],
            [0, 0, 0, 2, 2],
            [0, 0, 0, 0, 0],
            [0, 0, 0, 0, 0],
        ]
    )
    current_after = _observation(
        [
            [0, 0, 0, 0, 0],
            [0, 1, 0, 0, 0],
            [0, 0, 0, 0, 0],
            [0, 0, 0, 2, 2],
            [0, 0, 0, 0, 0],
        ]
    )
    ambiguous = registry.observe_transition(
        current_before,
        ActionRequest(ActionName.ACTION1),
        current_after,
        source_event_id="current-action1-ambiguous",
        prior_frame_hashes=(current_after.frames[-1].digest,),
    )
    current_condition = action_condition_signature(current_before)
    current_candidates = registry.candidates_for(
        ActionName.ACTION1,
        condition_signature=current_condition,
    )
    assert ambiguous.ambiguous is True
    assert current_candidates
    assert {candidate.status for candidate in current_candidates} == {ActionEffectStatus.AMBIGUOUS}
    assert not registry.candidates_for(
        ActionName.ACTION2,
        condition_signature=current_condition,
    )

    original = ActionEffectRegistry.accepted_translation
    calls: list[tuple[ActionName, str | None]] = []

    def tracked_translation(
        self: ActionEffectRegistry,
        raw_handle: ActionName,
        *,
        condition_signature: str | None = None,
    ) -> tuple[int, int] | None:
        calls.append((raw_handle, condition_signature))
        return original(
            self,
            raw_handle,
            condition_signature=condition_signature,
        )

    monkeypatch.setattr(ActionEffectRegistry, "accepted_translation", tracked_translation)
    ordered = registry.canonical_order(
        (ActionName.ACTION1, ActionName.ACTION2),
        condition_signature=current_condition,
    )

    assert (ActionName.ACTION1, None) not in calls
    assert (ActionName.ACTION2, None) in calls
    assert ordered[0] is ActionName.ACTION2


def test_restore_with_multiple_displacements_preserves_ambiguity() -> None:
    prior = _observation(
        [
            [0, 0, 0, 0, 0],
            [0, 1, 0, 0, 0],
            [0, 0, 0, 0, 0],
            [0, 0, 0, 2, 2],
            [0, 0, 0, 0, 0],
        ]
    )
    displaced = _observation(
        [
            [0, 0, 0, 0, 0],
            [0, 0, 1, 0, 0],
            [0, 0, 0, 2, 2],
            [0, 0, 0, 0, 0],
            [0, 0, 0, 0, 0],
        ]
    )
    registry = ActionEffectRegistry()

    observation = registry.observe_transition(
        displaced,
        ActionRequest(ActionName.ACTION7),
        prior,
        source_event_id="ambiguous-restore",
        prior_frame_hashes=(prior.frames[-1].digest,),
    )

    assert observation.ambiguous is True
    assert {effect.effect_kind for effect in observation.canonical_effects} == {
        CanonicalEffectKind.RESTORE
    }
    assert {effect.translation for effect in observation.canonical_effects} == {
        (-1, 0),
        (0, 1),
    }
    assert registry.accepted_effects(ActionName.ACTION7) == ()


def test_registry_enforces_handle_and_candidate_bounds_before_mutation() -> None:
    with pytest.raises(ValueError, match="must not exceed 32"):
        ActionEffectRegistry(max_candidates_per_handle=33)

    handles = ActionEffectRegistry(max_raw_handles=1)
    handles.register_handles((ActionName.ACTION1,))
    with pytest.raises(ValueError, match="raw-handle bound"):
        handles.register_handles((ActionName.ACTION2,))

    candidates = ActionEffectRegistry(max_candidates_per_handle=1)
    action = ActionRequest(ActionName.ACTION1)
    candidates.observe_transition(_CENTER, action, _RIGHT, source_event_id="bounded-1")
    before_projection = candidates.projection()
    with pytest.raises(ValueError, match="candidate bound"):
        candidates.observe_transition(_CENTER, action, _LEFT, source_event_id="bounded-2")
    assert candidates.projection() == before_projection

    with pytest.raises(ValueError, match="already been processed"):
        candidates.observe_transition(_CENTER, action, _RIGHT, source_event_id="bounded-1")
    assert candidates.projection() == before_projection


def test_returned_action_mismatch_is_rejected_without_receipt_mutation() -> None:
    returned = _observation(
        [[0, 0, 0], [0, 0, 1], [0, 0, 0]],
        returned_action=ActionRequest(ActionName.ACTION2),
    )
    before_digest = _CENTER.frames[-1].digest
    after_digest = returned.frames[-1].digest

    with pytest.raises(ValueError, match="does not match"):
        derive_action_effect_observation(
            _CENTER,
            ActionRequest(ActionName.ACTION1),
            returned,
            source_event_id="mismatch",
        )

    assert _CENTER.frames[-1].digest == before_digest
    assert returned.frames[-1].digest == after_digest
