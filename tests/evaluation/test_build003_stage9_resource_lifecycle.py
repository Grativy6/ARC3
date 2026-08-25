"""Stage 9 resource/failure behavior through the public observation boundary."""

from __future__ import annotations

from collections.abc import Mapping

from evaluation_only.arc3_build003_curriculum.variant_policy import (
    ObservationOnlyVariantPolicy,
)

from arc3.adapters import GridFrame, Observation
from arc3.mechanics import (
    CompositionMode,
    ConsequenceChannel,
    MechanicRef,
    MechanicStatus,
    QuantityEffect,
    ScopeCeiling,
    TerminalEffect,
)
from arc3.types import ActionName, ActionRequest, GameId, GameStateName

Point = tuple[int, int]
MOVES = (ActionName.ACTION1, ActionName.ACTION2)
ALL_MOVES = (
    ActionName.ACTION1,
    ActionName.ACTION2,
    ActionName.ACTION3,
    ActionName.ACTION4,
)


def _frame(resource: int, cells: dict[Point, int]) -> GridFrame:
    rows = [[0 for _ in range(9)] for _ in range(9)]
    for bit in range(5):
        rows[0][bit] = 1 if resource & (1 << bit) else 0
    for (x, y), value in cells.items():
        rows[y][x] = value
    return GridFrame.from_rows(rows)


def _observation(
    resource: int,
    cells: dict[Point, int],
    *,
    state: GameStateName = GameStateName.NOT_FINISHED,
    available: tuple[ActionName, ...] = MOVES,
    returned_action: ActionRequest | None = None,
    full_reset: bool = False,
    levels_completed: int = 0,
) -> Observation:
    return Observation(
        game_id=GameId("opaque-resource-lifecycle"),
        frames=(_frame(resource, cells),),
        state=state,
        levels_completed=levels_completed,
        win_levels=3,
        available_actions=available,
        full_reset=full_reset,
        returned_action=returned_action,
    )


def _failure_then_reset(
    *,
    reset_resource: int,
) -> tuple[ObservationOnlyVariantPolicy, Observation, ActionRequest]:
    policy = ObservationOnlyVariantPolicy("BLA_CLEF_FULL")
    initial = _observation(1, {(2, 3): 2})
    failed_action = policy.choose_action(initial)
    assert failed_action == ActionRequest(ActionName.ACTION1)

    failed = _observation(
        0,
        {(3, 3): 2},
        state=GameStateName.GAME_OVER,
        available=(ActionName.RESET,),
        returned_action=failed_action,
    )
    reset = policy.choose_action(failed)
    assert reset == ActionRequest(ActionName.RESET)

    recovered = _observation(
        reset_resource,
        {(2, 3): 2},
        returned_action=reset,
        full_reset=True,
    )
    next_action = policy.choose_action(recovered)
    return policy, recovered, next_action


def _view(policy: ObservationOnlyVariantPolicy, ref: MechanicRef) -> Mapping[str, object]:
    assert policy._learner is not None
    return policy._learner.ledger.get(ref).to_dict()


def test_resource_exhaustion_reset_strengthens_only_failure_link_and_avoids_failed_root() -> None:
    policy = ObservationOnlyVariantPolicy("BLA_CLEF_FULL")
    initial = _observation(1, {(2, 3): 2})
    failed_action = policy.choose_action(initial)
    assert failed_action == ActionRequest(ActionName.ACTION1)

    failed = _observation(
        0,
        {(3, 3): 2},
        state=GameStateName.GAME_OVER,
        available=(ActionName.RESET,),
        returned_action=failed_action,
    )
    reset = policy.choose_action(failed)
    assert reset == ActionRequest(ActionName.RESET)
    assert policy._learner is not None

    movement_ref = policy._baseline_refs[
        (ActionName.ACTION1, ConsequenceChannel.CONTROLLED_DISPLACEMENT)
    ]
    resource_ref = policy._baseline_refs[(ActionName.ACTION1, ConsequenceChannel.RESOURCE_CHANGES)]
    failure_ref = policy._failure_link_refs[ActionName.ACTION1]
    assert movement_ref == resource_ref
    baseline_before_reset = _view(policy, movement_ref)
    failure_before_reset = policy._learner.ledger.get(failure_ref)
    assert failure_before_reset.status is MechanicStatus.PROVISIONAL
    assert failure_before_reset.evidence_receipt_ids == ()
    assert failure_before_reset.version.scope.state_tags == ("visible-resource-exhaustion-risk",)
    terminal_effect = failure_before_reset.version.consequence.terminal_changes.effects[0]
    assert isinstance(terminal_effect, TerminalEffect)
    assert terminal_effect.state is GameStateName.GAME_OVER
    assert policy._learner.ledger.get(movement_ref).version.consequence.terminal_changes.is_unknown

    recovered = _observation(
        1,
        {(2, 3): 2},
        returned_action=reset,
        full_reset=True,
    )
    next_action = policy.choose_action(recovered)

    assert next_action == ActionRequest(ActionName.ACTION2)
    assert next_action != failed_action
    assert tuple(policy._failed_plan_roots)
    assert _view(policy, movement_ref) == baseline_before_reset
    failure_after_reset = policy._learner.ledger.get(failure_ref)
    assert failure_after_reset.status is MechanicStatus.PROVISIONAL
    terminal_support = failure_after_reset.summary_for(ConsequenceChannel.TERMINAL_CHANGES)
    assert terminal_support.occurrence_support_count == 1
    assert terminal_support.magnitude_support_count == 0
    assert failure_ref in policy._confirmed_failure_links
    assert set(policy._baseline_refs.values()) == {movement_ref}


def test_restoration_residual_preserves_movement_and_minimal_probe_resolves_additive() -> None:
    policy, _recovered, selected = _failure_then_reset(reset_resource=10)
    assert selected == ActionRequest(ActionName.ACTION2)

    left = _observation(
        9,
        {(1, 3): 2},
        available=(ActionName.ACTION1,),
        returned_action=selected,
    )
    return_to_center = policy.choose_action(left)
    assert return_to_center == ActionRequest(ActionName.ACTION1)

    center = _observation(
        8,
        {(2, 3): 2, (3, 3): 4},
        available=(ActionName.ACTION1,),
        returned_action=return_to_center,
    )
    enter_restoration = policy.choose_action(center)
    assert enter_restoration == ActionRequest(ActionName.ACTION1)
    assert policy._learner is not None
    base_ref = policy._baseline_refs[(ActionName.ACTION1, ConsequenceChannel.RESOURCE_CHANGES)]
    base_before = policy._learner.ledger.get(base_ref)
    movement_support_before = base_before.summary_for(
        ConsequenceChannel.CONTROLLED_DISPLACEMENT
    ).occurrence_support_count
    resource_support_before = base_before.summary_for(
        ConsequenceChannel.RESOURCE_CHANGES
    ).occurrence_support_count

    restored = _observation(
        12,
        {(3, 3): 2},
        returned_action=enter_restoration,
    )
    leave_probe = policy.choose_action(restored)

    assert leave_probe == ActionRequest(ActionName.ACTION2)
    base_after = policy._learner.ledger.get(base_ref)
    assert (
        base_after.summary_for(ConsequenceChannel.CONTROLLED_DISPLACEMENT).occurrence_support_count
        == movement_support_before + 1
    )
    assert (
        base_after.summary_for(ConsequenceChannel.RESOURCE_CHANGES).occurrence_support_count
        == resource_support_before
    )
    assert base_after.status not in {
        MechanicStatus.STRESSED,
        MechanicStatus.REOPENED,
        MechanicStatus.REJECTED_OR_SUPERSEDED,
    }
    assert len(policy._resource_ambiguities) == 1
    ambiguity = next(iter(policy._resource_ambiguities.values()))
    assert ambiguity.additive_bonus == 5
    assert ambiguity.set_value == 12
    assert ambiguity.material_reason == "confirmed-visible-resource-failure-link"
    assert ambiguity.competing_modes == (
        CompositionMode.ADDITIVE,
        CompositionMode.OVERRIDE,
    )
    additive = policy._learner.ledger.get(ambiguity.additive_ref)
    assert additive.status is MechanicStatus.PROVISIONAL
    assert additive.version.composition_mode is CompositionMode.ADDITIVE
    assert additive.version.scope.object_roles

    left_restoration = _observation(
        11,
        {(2, 3): 2, (3, 3): 4},
        available=(ActionName.ACTION1,),
        returned_action=leave_probe,
    )
    reenter_probe = policy.choose_action(left_restoration)
    assert reenter_probe == enter_restoration

    additive_result = _observation(
        15,
        {(3, 3): 2},
        returned_action=reenter_probe,
    )
    summary = policy.finalize(additive_result)

    assert policy._resource_ambiguities == {}
    assert len(policy._resource_discrimination_receipts) == 1
    receipt = policy._resource_discrimination_receipts[0]
    assert receipt.planned_actions == (ActionName.ACTION2, ActionName.ACTION1)
    assert receipt.observed_actions == receipt.planned_actions
    assert receipt.additive_expected_after == 15
    assert receipt.override_expected_after == 12
    assert receipt.observed_after == 15
    assert receipt.resolved_mode is CompositionMode.ADDITIVE
    assert receipt.complete is True
    assert summary["resource_lifecycle"] == {
        "confirmed_failure_links": 1,
        "failed_plan_roots": 1,
        "open_restoration_ambiguities": 0,
        "resource_discriminations": [receipt.to_dict()],
    }
    assert policy._learner.ledger.get(base_ref).status not in {
        MechanicStatus.STRESSED,
        MechanicStatus.REOPENED,
        MechanicStatus.REJECTED_OR_SUPERSEDED,
    }


def test_override_discriminator_installs_local_override_without_rewriting_base() -> None:
    policy, _recovered, selected = _failure_then_reset(reset_resource=10)
    left = _observation(
        9,
        {(1, 3): 2},
        available=(ActionName.ACTION1,),
        returned_action=selected,
    )
    return_to_center = policy.choose_action(left)
    center = _observation(
        8,
        {(2, 3): 2, (3, 3): 4},
        available=(ActionName.ACTION1,),
        returned_action=return_to_center,
    )
    enter_restoration = policy.choose_action(center)
    restored = _observation(12, {(3, 3): 2}, returned_action=enter_restoration)
    leave_probe = policy.choose_action(restored)

    assert policy._learner is not None
    base_ref = policy._baseline_refs[(ActionName.ACTION1, ConsequenceChannel.RESOURCE_CHANGES)]
    base_version_before = policy._learner.ledger.get(base_ref).version.to_dict()
    ambiguity = next(iter(policy._resource_ambiguities.values()))

    left_restoration = _observation(
        11,
        {(2, 3): 2, (3, 3): 4},
        available=(ActionName.ACTION1,),
        returned_action=leave_probe,
    )
    reenter_probe = policy.choose_action(left_restoration)
    override_result = _observation(12, {(3, 3): 2}, returned_action=reenter_probe)
    summary = policy.finalize(override_result)

    receipt = policy._resource_discrimination_receipts[-1]
    assert receipt.resolved_mode is CompositionMode.OVERRIDE
    assert receipt.complete is True
    assert summary["resource_lifecycle"]["open_restoration_ambiguities"] == 0
    assert (
        policy._learner.ledger.get(ambiguity.additive_ref).status
        is MechanicStatus.REJECTED_OR_SUPERSEDED
    )
    assert ambiguity.additive_ref not in policy._repairs
    assert ambiguity.additive_ref not in policy._repair_keys.values()
    assert ambiguity.additive_ref not in policy._origin_residuals

    overrides = tuple(
        view
        for view in policy._learner.ledger.active()
        if view.version.composition_mode is CompositionMode.OVERRIDE
        and not view.version.consequence.resource_changes.is_unknown
    )
    assert len(overrides) == 1
    override = overrides[0]
    assert override.version.scope.ceiling is ScopeCeiling.LEVEL
    assert override.version.scope.object_roles
    assert override.version.scope.state_tags == ("visible-resource-value-11",)
    effect = override.version.consequence.resource_changes.effects[0]
    assert isinstance(effect, QuantityEffect)
    assert effect.delta == 1
    support = override.summary_for(ConsequenceChannel.RESOURCE_CHANGES)
    assert support.occurrence_support_count == 1
    assert support.magnitude_support_count == 0
    assert policy._learner.ledger.get(base_ref).version.to_dict() == base_version_before
    assert policy._learner.ledger.get(base_ref).status not in {
        MechanicStatus.STRESSED,
        MechanicStatus.REOPENED,
        MechanicStatus.REJECTED_OR_SUPERSEDED,
    }
    assert all(
        {item.channel for item in record.residual.consequential}
        != {ConsequenceChannel.RESOURCE_CHANGES}
        for record in policy._learner.open_residuals
    )


def test_normal_progress_never_replays_an_exact_failed_root_after_reset() -> None:
    policy = ObservationOnlyVariantPolicy("BLA_CLEF_FULL")
    initial = _observation(1, {(2, 3): 2, (3, 3): 4}, available=ALL_MOVES)
    policy._game_scope = str(initial.game_id)
    policy._enter_level(0, observation=initial)
    policy._previous = initial
    policy._movement = {
        ActionName.ACTION1: (1, 0),
        ActionName.ACTION2: (-1, 0),
        ActionName.ACTION3: (0, 1),
        ActionName.ACTION4: (0, -1),
    }
    policy._resource_delta_by_action = {
        ActionName.ACTION1: -1,
        ActionName.ACTION2: 0,
        ActionName.ACTION3: 0,
        ActionName.ACTION4: 0,
    }
    policy._player_position = (2, 3)
    policy._player_color = 2

    failed_action = ActionRequest(ActionName.ACTION1)
    policy._begin_action(
        failed_action,
        "progress-nearest-visible-candidate",
        target=(3, 3),
    )
    failed = _observation(
        0,
        {(3, 3): 2},
        state=GameStateName.GAME_OVER,
        available=(ActionName.RESET,),
        returned_action=failed_action,
    )
    reset = policy.choose_action(failed)
    recovered = _observation(
        1,
        {(2, 3): 2, (3, 3): 4},
        available=ALL_MOVES,
        returned_action=reset,
        full_reset=True,
    )
    recovery_probe = policy.choose_action(recovered)
    assert recovery_probe == ActionRequest(ActionName.ACTION3)

    after_probe = _observation(
        1,
        {(2, 4): 2, (3, 3): 4},
        available=ALL_MOVES,
        returned_action=recovery_probe,
    )
    return_to_root = policy.choose_action(after_probe)
    assert return_to_root == ActionRequest(ActionName.ACTION4)
    same_root = _observation(
        1,
        {(2, 3): 2, (3, 3): 4},
        available=ALL_MOVES,
        returned_action=return_to_root,
    )
    alternative = policy.choose_action(same_root)

    assert policy._plan_root_signature(same_root, failed_action) in policy._failed_plan_roots
    assert alternative != failed_action
    assert alternative.name in same_root.available_actions
    assert policy._plan_root_signature(same_root, alternative) not in policy._failed_plan_roots
    assert policy._last_reason == "avoid-exact-failed-plan-root"


def test_true_level_boundary_quarantines_local_work_and_clears_pending_state() -> None:
    policy, _recovered, selected = _failure_then_reset(reset_resource=10)
    left = _observation(
        9,
        {(1, 3): 2},
        available=(ActionName.ACTION1,),
        returned_action=selected,
    )
    return_to_center = policy.choose_action(left)
    center = _observation(
        8,
        {(2, 3): 2, (3, 3): 4},
        available=(ActionName.ACTION1,),
        returned_action=return_to_center,
    )
    enter_restoration = policy.choose_action(center)
    restored = _observation(12, {(3, 3): 2}, returned_action=enter_restoration)
    leave_probe = policy.choose_action(restored)

    assert policy._learner is not None
    base_ref = policy._baseline_refs[(ActionName.ACTION1, ConsequenceChannel.RESOURCE_CHANGES)]
    ambiguity = next(iter(policy._resource_ambiguities.values()))
    old_ambiguity_id = ambiguity.ambiguity_id
    old_repair_refs = set(policy._repairs)

    advanced = _observation(
        11,
        {(2, 3): 2, (3, 3): 4},
        available=(ActionName.ACTION1,),
        returned_action=leave_probe,
        levels_completed=1,
    )
    policy.choose_action(advanced)

    assert policy._resource_ambiguities == {}
    assert policy._active_resource_probe is None
    assert policy._repairs == {}
    assert policy._repair_keys == {}
    assert policy._origin_residuals == {}
    assert policy._pending_residual_refs == {}
    assert policy._learner.open_residuals == ()
    assert policy._learner.ledger.get(base_ref).is_live
    assert policy._learner.ledger.get(base_ref).version.scope.ceiling is ScopeCeiling.GAME
    quarantined = {view.ref for view in policy._learner.ledger.quarantined_for(policy._context)}
    assert old_repair_refs <= quarantined
    assert ambiguity.additive_ref in quarantined
    assert base_ref not in quarantined

    disposition = policy._level_boundary_dispositions[-1]
    assert disposition.previous_level_scope == "level-1-attempt-1"
    assert disposition.current_level_scope == "level-2-attempt-1"
    assert old_repair_refs <= set(disposition.quarantined_repair_refs)
    assert disposition.archived_residual_ids
    assert ambiguity.residual_id in disposition.archived_residual_ids
    assert old_ambiguity_id in disposition.archived_ambiguity_ids
