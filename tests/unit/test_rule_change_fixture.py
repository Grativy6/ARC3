"""Focused tests for the frozen Stage 06 synthetic fixture."""

from __future__ import annotations

from collections import Counter

from arc3.lab.rule_change import (
    RULE_CHANGE_ACTIONS,
    RULE_CHANGE_GAME_ID,
    ActionVariant,
    CheckpointBoundary,
    PaletteVariant,
    RuleChangeCaseKind,
    RuleChangeEvaluatorEpisode,
    RuleChangeFamily,
    RuleChangeTiming,
    checkpoint_schedule,
    intervention_schedule,
    noise_control_schedule,
    open_rule_change_case,
)
from arc3.trace.canonical import canonical_bytes, sha256_json
from arc3.types import ActionName, ActionRequest, GameStateName


def _calibrate_and_support(
    case_index: int, *, noise: bool = False
) -> tuple[RuleChangeEvaluatorEpisode, ActionRequest]:
    case = (noise_control_schedule() if noise else intervention_schedule())[case_index]
    episode = open_rule_change_case(case)
    for action in RULE_CHANGE_ACTIONS:
        episode.take(ActionRequest(action))
    horizontal = episode.action_for_predecessor_effect((1, 0))
    while episode.projection.prechange_support_receipts < case.support_required:
        position = episode.projection.position
        target = episode.projection.visible_target
        if position[1] != target[1]:
            vertical = (0, 1 if target[1] > position[1] else -1)
            episode.take(episode.action_for_predecessor_effect(vertical))
        else:
            horizontal_effect = (1 if target[0] > position[0] else -1, 0)
            horizontal = episode.action_for_predecessor_effect(horizontal_effect)
            episode.take(horizontal)
    return episode, horizontal


def _finish_with_truth_plan(episode: RuleChangeEvaluatorEpisode, *, successor: bool) -> None:
    plan = episode.successor_oracle_plan() if successor else episode.stationary_oracle_plan()
    for action in plan:
        episode.take(action)


def test_frozen_schedule_cardinalities_ids_and_order() -> None:
    interventions = intervention_schedule()
    noise = noise_control_schedule()
    checkpoints = checkpoint_schedule()

    assert len(interventions) == 64
    assert len(noise) == 32
    assert len(checkpoints) == 8
    assert len({case.case_id for case in (*interventions, *noise)}) == 96
    assert Counter(case.family for case in interventions) == {
        RuleChangeFamily.ACTION_EFFECT_ROTATION: 32,
        RuleChangeFamily.TRAVERSABILITY_FLIP: 32,
    }
    assert Counter(case.timing for case in interventions) == {
        RuleChangeTiming.EARLY_SUPPORT_2: 32,
        RuleChangeTiming.LATE_SUPPORT_4: 32,
    }
    assert interventions[0].case_id == (
        "stage06-intervention-action_effect_rotation-early_support_2-s7-identity-identity"
    )
    assert interventions[-1].case_id == (
        "stage06-intervention-traversability_flip-late_support_4-s29-affine_nonidentity-cycle1234"
    )
    assert noise[0].case_id == "stage06-noise-early_support_2-s7-identity-identity"
    assert noise[-1].case_id == ("stage06-noise-late_support_4-s29-affine_nonidentity-cycle1234")
    assert [item.boundary for item in checkpoints[:4]] == [CheckpointBoundary.PRE_TRIGGER] * 4
    assert [item.boundary for item in checkpoints[4:]] == [CheckpointBoundary.POST_REOPEN] * 4
    assert all(item.palette_variant is PaletteVariant.AFFINE_NONIDENTITY for item in checkpoints)
    assert all(item.action_variant is ActionVariant.CYCLE1234 for item in checkpoints)


def test_policy_surface_is_common_and_contains_no_evaluator_truth() -> None:
    identities: set[str] = set()
    metadata_shapes: set[tuple[str, ...]] = set()
    for case in (*intervention_schedule(), *noise_control_schedule()):
        episode = open_rule_change_case(case)
        episode.assert_policy_blinded()
        identities.add(str(episode.session.observation.game_id))
        metadata_shapes.add(
            tuple(key for key, _value in episode.session.observation.upstream_metadata)
        )
        assert episode.session.observation.available_actions == RULE_CHANGE_ACTIONS
    assert identities == {str(RULE_CHANGE_GAME_ID)}
    assert metadata_shapes == {("attempt", "step")}


def test_affine_palette_moves_zero_and_action_cycle_changes_raw_east_handle() -> None:
    identity = next(
        case
        for case in intervention_schedule()
        if case.family is RuleChangeFamily.ACTION_EFFECT_ROTATION
        and case.seed == 7
        and case.palette_variant is PaletteVariant.IDENTITY
        and case.action_variant is ActionVariant.IDENTITY
    )
    transformed = next(
        case
        for case in intervention_schedule()
        if case.family is RuleChangeFamily.ACTION_EFFECT_ROTATION
        and case.seed == 7
        and case.palette_variant is PaletteVariant.AFFINE_NONIDENTITY
        and case.action_variant is ActionVariant.CYCLE1234
    )
    base_episode = open_rule_change_case(identity)
    transformed_episode = open_rule_change_case(transformed)
    assert 0 in base_episode.session.observation.frames[-1].palette
    assert 0 not in transformed_episode.session.observation.frames[-1].palette
    assert base_episode.action_for_predecessor_effect((1, 0)) != (
        transformed_episode.action_for_predecessor_effect((1, 0))
    )


def test_training_support_does_not_advance_during_four_handle_calibration() -> None:
    for case in (*intervention_schedule(), *noise_control_schedule()):
        if case.family is RuleChangeFamily.ACTION_EFFECT_ROTATION:
            continue
        episode = open_rule_change_case(case)
        initial_guide = episode.projection.visible_target
        for action in RULE_CHANGE_ACTIONS:
            episode.take(ActionRequest(action))
        assert episode.projection.visible_target == initial_guide
        assert episode.projection.prechange_support_receipts == 0


def test_seed_derived_traversability_layouts_are_distinct_and_non_degenerate() -> None:
    cases = [
        case
        for case in intervention_schedule()
        if case.family is RuleChangeFamily.TRAVERSABILITY_FLIP
        and case.timing is RuleChangeTiming.EARLY_SUPPORT_2
        and case.palette_variant is PaletteVariant.IDENTITY
        and case.action_variant is ActionVariant.IDENTITY
    ]
    receipts = [open_rule_change_case(case).layout_receipt for case in cases]
    assert len({str(item["layout_id"]) for item in receipts}) == 4
    starts: set[tuple[int, int]] = set()
    for receipt in receipts:
        start = receipt["start"]
        assert isinstance(start, list)
        assert len(start) == 2
        start_x, start_y = start
        assert isinstance(start_x, int) and not isinstance(start_x, bool)
        assert isinstance(start_y, int) and not isinstance(start_y, bool)
        starts.add((start_x, start_y))
        assert receipt["rejected_candidate_count"] == 0
        assert receipt["rejection_reasons"] == []
        route_length = receipt["successor_route_length"]
        assert isinstance(route_length, int) and not isinstance(route_length, bool)
        assert 3 <= route_length <= 12
        predicates = receipt["predicates"]
        assert isinstance(predicates, dict)
        assert predicates
        assert all(value is True for value in predicates.values())
    assert len(starts) == 4


def test_all_interventions_trigger_once_resolve_and_complete_with_immutable_truth() -> None:
    for index, case in enumerate(intervention_schedule()):
        episode, trigger_action = _calibrate_and_support(index)
        assert episode.ready_for_evaluator_arm
        assert len(episode.successor_oracle_plan()) >= 3
        prefix = canonical_bytes([item.to_dict() for item in episode.truth_receipts])
        prefix_hashes = tuple(item.receipt_hash for item in episode.truth_receipts)
        episode.arm_trigger()
        trigger = episode.take(trigger_action)
        assert trigger.truth.pulse_triggered
        assert trigger.truth.trigger_step is not None
        assert trigger.truth.trigger_step <= case.timing.latest_trigger_action
        assert trigger.truth.mechanics_epoch == 1
        assert not trigger.truth.pulse_resolved
        if case.family is RuleChangeFamily.TRAVERSABILITY_FLIP:
            repeated = episode.take(trigger_action)
            assert repeated.truth.attempted_cell == trigger.truth.attempted_cell
            assert not repeated.truth.distinct_successor_evidence
            assert repeated.truth.coherent_successor_receipts == 1
            assert not repeated.truth.pulse_resolved
            distinct_primary = episode.action_for_predecessor_effect((0, -1))
            confirmation = episode.take(distinct_primary)
            assert confirmation.truth.attempted_cell != trigger.truth.attempted_cell
        else:
            repeated = episode.take(trigger_action)
            assert repeated.truth.action.name is trigger.truth.action.name
            assert not repeated.truth.distinct_successor_evidence
            assert repeated.truth.coherent_successor_receipts == 1
            assert not repeated.truth.pulse_resolved
            distinct_handle = ActionRequest(
                next(item for item in RULE_CHANGE_ACTIONS if item is not trigger_action.name)
            )
            confirmation = episode.take(distinct_handle)
            assert confirmation.truth.action.name is not trigger.truth.action.name
        assert confirmation.truth.distinct_successor_evidence
        assert confirmation.truth.coherent_successor_receipts == 2
        assert confirmation.truth.pulse_resolved
        assert len(confirmation.truth.successor_evidence_cells) == 2
        if case.family is RuleChangeFamily.ACTION_EFFECT_ROTATION:
            assert len(confirmation.truth.successor_evidence_handles) == 2
        else:
            assert confirmation.truth.successor_evidence_handles == ()
        _finish_with_truth_plan(episode, successor=True)
        assert episode.session.observation.state is GameStateName.WIN
        assert episode.projection.action_count <= 48
        assert (
            sum(item.pulse_kind == "persistent-intervention" for item in episode.truth_receipts)
            >= 2
        )
        assert (
            canonical_bytes(
                [item.to_dict() for item in episode.truth_receipts[: len(prefix_hashes)]]
            )
            == prefix
        )
        assert (
            tuple(item.receipt_hash for item in episode.truth_receipts[: len(prefix_hashes)])
            == prefix_hashes
        )
        assert len({item.receipt_id for item in episode.truth_receipts}) == len(
            episode.truth_receipts
        )


def test_all_noise_controls_emit_one_outlier_resolve_without_epoch_change() -> None:
    for index, case in enumerate(noise_control_schedule()):
        episode, trigger_action = _calibrate_and_support(index, noise=True)
        assert case.kind is RuleChangeCaseKind.NOISE
        assert episode.ready_for_evaluator_arm
        assert len(episode.stationary_oracle_plan()) >= 3
        episode.arm_trigger()
        outlier = episode.take(trigger_action)
        assert outlier.truth.pulse_kind == "transient-noise"
        assert outlier.truth.realized_effect == (0, 0)
        assert outlier.truth.mechanics_epoch == 0
        first_recovery = episode.take(trigger_action)
        second_recovery = episode.take(trigger_action)
        assert first_recovery.truth.resumed_predecessor_receipts == 1
        assert second_recovery.truth.resumed_predecessor_receipts == 2
        assert second_recovery.truth.pulse_resolved
        assert second_recovery.truth.mechanics_epoch == 0
        _finish_with_truth_plan(episode, successor=False)
        assert episode.session.observation.state is GameStateName.WIN
        assert episode.projection.action_count <= 48
        assert sum(item.pulse_kind == "transient-noise" for item in episode.truth_receipts) == 1
        assert sha256_json([item.to_dict() for item in episode.truth_receipts]).startswith(
            "sha256:"
        )


def test_reset_does_not_rearm_or_erase_trigger_truth() -> None:
    episode, trigger_action = _calibrate_and_support(0)
    episode.arm_trigger()
    episode.take(trigger_action)
    trigger_step = episode.projection.trigger_step
    episode.take(ActionRequest(name=ActionName.RESET))
    assert episode.projection.pulse_triggered
    assert episode.projection.trigger_step == trigger_step
    assert episode.projection.reset_count == 1


def test_evaluator_fork_preserves_shared_prefix_and_then_diverges_independently() -> None:
    episode = open_rule_change_case(intervention_schedule()[0])
    first = ActionRequest(RULE_CHANGE_ACTIONS[0])
    episode.take(first)
    fork = episode.fork()

    original_step = episode.take(ActionRequest(RULE_CHANGE_ACTIONS[1]))
    fork_step = fork.take(ActionRequest(RULE_CHANGE_ACTIONS[1]))
    assert original_step.observation == fork_step.observation
    assert original_step.truth == fork_step.truth
    assert episode.projection == fork.projection
    assert episode.truth_receipts == fork.truth_receipts

    fork.take(ActionRequest(RULE_CHANGE_ACTIONS[2]))
    assert episode.projection.action_count == 2
    assert fork.projection.action_count == 3
    assert len(episode.truth_receipts) == 2
    assert len(fork.truth_receipts) == 3
