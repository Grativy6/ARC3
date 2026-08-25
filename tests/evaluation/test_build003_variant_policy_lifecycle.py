"""Focused observation-only lifecycle coverage for the Build 003 evaluator policy."""

from __future__ import annotations

import copy

from evaluation_only.arc3_build003_curriculum.broker import observation_to_bytes
from evaluation_only.arc3_build003_curriculum.runner import (
    _receipt_link_audit,
    _sequence_counter_audit,
)
from evaluation_only.arc3_build003_curriculum.variant_policy import (
    ObservationOnlyVariantPolicy,
)

from arc3.adapters import GridFrame, Observation
from arc3.mechanics import (
    ChannelResidual,
    ChannelValue,
    CompositionMode,
    ConsequenceChannel,
    DisplacementEffect,
    EvidenceProvenance,
    KnowledgeState,
)
from arc3.types import ActionName, ActionRequest, GameId, GameStateName

Point = tuple[int, int]
AVAILABLE = (
    ActionName.ACTION1,
    ActionName.ACTION2,
    ActionName.ACTION3,
    ActionName.ACTION4,
    ActionName.ACTION5,
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
    levels_completed: int = 0,
    returned_action: ActionRequest | None = None,
) -> Observation:
    return Observation(
        game_id=GameId("opaque-evaluator-case"),
        frames=(_frame(resource, cells),),
        state=GameStateName.NOT_FINISHED,
        levels_completed=levels_completed,
        win_levels=10,
        available_actions=AVAILABLE,
        returned_action=returned_action,
    )


def _initialized(
    variant: str = "BLA_CLEF_FULL",
    *,
    observation: Observation | None = None,
) -> tuple[ObservationOnlyVariantPolicy, Observation]:
    before = observation or _observation(7, {(2, 3): 2})
    policy = ObservationOnlyVariantPolicy(variant)
    policy._game_scope = str(before.game_id)
    policy._enter_level(0)
    policy._previous = before
    return policy, before


def _submit(
    policy: ObservationOnlyVariantPolicy,
    before: Observation,
    action: ActionRequest,
    after: Observation,
) -> None:
    policy._previous = before
    policy._begin_action(action, "test-observation-only", target=None)
    policy._consume_observation(after)


def test_transition_facts_cover_all_channels_without_inventing_hidden_state() -> None:
    policy, before = _initialized()
    action = ActionRequest(ActionName.ACTION1)
    after = _observation(7, {(3, 3): 2}, returned_action=action)
    policy._last_player_position = (2, 3)
    policy._last_player_color = 2
    policy._last_target = (3, 3)
    displacement = ((2, 3), (3, 3), 2)

    facts = policy._transition_facts(
        action=action,
        displacement=displacement,
        resource_delta=0,
        before=before,
        after=after,
    )

    assert len(facts.observed.items()) == 10
    assert facts.observed.controlled_displacement.knowledge is KnowledgeState.KNOWN
    assert facts.observed.other_object_effects.is_known_empty
    assert facts.observed.legal_action_changes.is_known_empty
    assert facts.observed.inventory_changes.is_unknown
    assert facts.observed.topology_changes.is_unknown
    assert facts.observed.delayed_effects.is_unknown


def test_full_prediction_is_replay_linked_and_runner_rejects_tampering() -> None:
    before = _observation(7, {(2, 3): 2})
    policy = ObservationOnlyVariantPolicy("BLA_CLEF_FULL")
    action = policy.choose_action(before)
    after = _observation(7, {(3, 3): 2}, returned_action=action)

    summary = policy.finalize(after)
    transcript = [(action, observation_to_bytes(after))]

    assert summary["receipt_count"] == 1
    links = summary["action_links"]
    assert isinstance(links, list) and len(links) == 1
    assert links[0]["complete"] is True
    audited = _receipt_link_audit(summary, before, transcript, require_prediction_links=True)
    assert audited[0] is True
    assert not any(audited[1:])

    tampered = copy.deepcopy(summary)
    tampered["action_links"][0]["after_ref"] = "sha256:" + "0" * 64
    assert not _receipt_link_audit(tampered, before, transcript, require_prediction_links=True)[0]


def test_runner_rejects_worker_counter_or_transcript_mismatch() -> None:
    levels = [
        {
            "environment_actions": 0,
            "resets": 0,
        }
        for _ in range(10)
    ]
    levels[0] = {"environment_actions": 2, "resets": 1}
    summary: dict[str, object] = {"levels": levels}
    assert _sequence_counter_audit(
        summary, environment_actions=2, resets=1, transcript_count=3
    ) == (True, 2, 1)
    assert (
        _sequence_counter_audit(summary, environment_actions=2, resets=0, transcript_count=2)[0]
        is False
    )
    assert (
        _sequence_counter_audit(summary, environment_actions=2, resets=1, transcript_count=2)[0]
        is False
    )


def test_consequential_residual_waits_for_passive_confirmation() -> None:
    policy, before = _initialized()
    action = ActionRequest(ActionName.ACTION1)
    first = _observation(7, {(3, 3): 2}, returned_action=action)
    _submit(policy, before, action, first)

    assert policy._learner is not None
    assert policy._learner.open_residuals
    assert policy._metrics[0].residuals_resolved == 0

    second = _observation(7, {(4, 3): 2}, returned_action=action)
    _submit(policy, first, action, second)

    assert policy._metrics[0].passive_confirmations > 0
    assert policy._metrics[0].residuals_resolved > 0


def test_additive_local_repair_fails_twice_before_implicated_base_reopens() -> None:
    policy, before = _initialized(observation=_observation(7, {(2, 3): 2}))
    action = ActionRequest(ActionName.ACTION5)
    policy._resource_delta_by_action[action.name] = -1
    base_ref = policy._open_resource_mechanic(action.name, -1)
    assert base_ref is not None

    first = _observation(8, {(2, 3): 2}, returned_action=action)
    _submit(policy, before, action, first)
    assert policy._repairs
    repair_ref = next(iter(policy._repairs))
    assert policy._mode_for_ref(repair_ref) is CompositionMode.ADDITIVE
    assert policy._metrics[0].base_reopenings == 0

    second = _observation(10, {(2, 3): 2}, returned_action=action)
    _submit(policy, first, action, second)
    assert policy._metrics[0].local_repair_failures == 1
    assert policy._metrics[0].base_reopenings == 0

    third = _observation(12, {(2, 3): 2}, returned_action=action)
    _submit(policy, second, action, third)
    assert policy._metrics[0].local_repair_failures == 2
    assert policy._metrics[0].base_reopenings == 1
    assert policy._metrics[0].erroneous_global_reopenings is None


def test_cross_level_retention_is_counted_only_after_confirm_transfer() -> None:
    policy, before = _initialized(observation=_observation(10, {(2, 3): 2}))
    action = ActionRequest(ActionName.ACTION5)
    policy._resource_delta_by_action[action.name] = -1
    assert policy._open_resource_mechanic(action.name, -1) is not None
    supported = _observation(9, {(2, 3): 2}, returned_action=action)
    _submit(policy, before, action, supported)

    policy._enter_level(1)
    next_before = _observation(9, {(2, 3): 2}, levels_completed=1)
    next_after = _observation(
        8,
        {(2, 3): 2},
        levels_completed=1,
        returned_action=action,
    )
    _submit(policy, next_before, action, next_after)

    metric = policy._metrics[1]
    assert metric.transfer_confirmations > 0
    assert metric.observed_retained_matches > 0
    assert metric.base_mechanics_retained is True


def test_clef_disposes_relevant_recolor_while_bla_only_retains_pressure() -> None:
    before = _observation(7, {(2, 3): 2, (4, 3): 4})
    after = _observation(7, {(2, 3): 2, (4, 3): 5})
    action = ActionRequest(ActionName.ACTION5)

    full, _ = _initialized(observation=before)
    full._last_target = (4, 3)
    full_facts = full._transition_facts(
        action=action,
        displacement=None,
        resource_delta=0,
        before=before,
        after=after,
    )
    full._update_dynamic_residuals(before, after, action, full_facts)

    bla_only, _ = _initialized("BLA_ONLY_PERSISTENT", observation=before)
    bla_only._last_target = (4, 3)
    bla_facts = bla_only._transition_facts(
        action=action,
        displacement=None,
        resource_delta=0,
        before=before,
        after=after,
    )
    bla_only._update_dynamic_residuals(before, after, action, bla_facts)

    assert full._metrics[0].clef_promotions == 1
    assert full._metrics[0].clef_parks == full._metrics[0].clef_stops == 0
    assert bla_only._metrics[0].clef_promotions == 0
    assert bla_only._recolor_counts[(4, 3)] == 1


def test_unique_other_object_motion_and_behavioral_topology_are_not_conflated() -> None:
    policy, before = _initialized(observation=_observation(7, {(2, 3): 2, (5, 5): 3}))
    action = ActionRequest(ActionName.ACTION5)
    moved = _observation(7, {(2, 3): 2, (6, 5): 3}, returned_action=action)
    facts = policy._transition_facts(
        action=action,
        displacement=None,
        resource_delta=0,
        before=before,
        after=moved,
    )
    assert facts.other_object_motion is not None
    assert not facts.observed.other_object_effects.is_unknown
    assert facts.observed.topology_changes.is_unknown

    move = ActionRequest(ActionName.ACTION1)
    destination = (3, 3)
    policy._blocked_history[destination] = "opaque-visible-role"
    traversed = _observation(7, {destination: 2}, returned_action=move)
    topology = policy._transition_facts(
        action=move,
        displacement=((2, 3), destination, 2),
        resource_delta=0,
        before=_observation(7, {(2, 3): 2}),
        after=traversed,
    )
    assert not topology.observed.topology_changes.is_unknown


def test_delayed_mechanic_requires_two_distinct_fixed_lag_associations() -> None:
    policy, quiet = _initialized(observation=_observation(7, {(2, 3): 2, (5, 5): 4}))
    changed = _observation(7, {(2, 3): 2, (5, 5): 5})
    action5 = ActionRequest(ActionName.ACTION5)
    action1 = ActionRequest(ActionName.ACTION1)

    for step, action, before, after in (
        (1, action5, quiet, quiet),
        (2, action1, quiet, changed),
        (3, action5, quiet, quiet),
        (4, action1, quiet, changed),
    ):
        policy._step = step
        facts = policy._transition_facts(
            action=action,
            displacement=None,
            resource_delta=0,
            before=before,
            after=after,
        )
        policy._update_delayed_evidence(action, facts)

    assert policy._metrics[0].delayed_candidates_confirmed == 1
    assert policy._delayed_refs
    policy._previous = quiet
    policy._begin_action(action5, "test-delayed-composition", target=None)
    assert policy._last_prediction is not None
    delayed = policy._last_prediction.composition.consequence.delayed_effects
    assert delayed.knowledge is KnowledgeState.KNOWN
    assert policy._metrics[0].composition_events[CompositionMode.DELAYED.value] == 1


def test_gating_and_override_repairs_are_derived_from_observed_consequences() -> None:
    policy, before = _initialized()
    action = ActionName.ACTION1
    policy._movement[action] = (1, 0)
    base_ref = policy._open_movement_mechanic(
        action,
        (1, 0),
        source="test-observation:0",
        provenance=EvidenceProvenance.OBSERVED_THIS_GAME,
    )
    assert base_ref is not None
    policy._last_player_position = (2, 3)
    policy._last_player_color = 2
    policy._last_target = (3, 3)
    facts = policy._transition_facts(
        action=ActionRequest(action),
        displacement=None,
        resource_delta=0,
        before=before,
        after=before,
    )
    assert policy._learner is not None
    learner = policy._learner
    prediction = learner.predict(ActionRequest(action), facts.context, emitted_step=0)
    learning = learner.observe_consequence(
        prediction.prediction_id,
        facts.observed,
        source_event_ids=(facts.source_event_id,),
        context_key=facts.context.context_key,
        observed_step=1,
    )
    controlled = learning.residual.for_channel(ConsequenceChannel.CONTROLLED_DISPLACEMENT)
    gate_ref = policy._open_local_repair(action, controlled, facts)
    assert gate_ref is not None
    assert policy._mode_for_ref(gate_ref) is CompositionMode.GATING

    observed_move = ChannelValue.known(DisplacementEffect("controllable-object", 1, 0))
    override_residual = ChannelResidual(
        channel=controlled.channel,
        kind=controlled.kind,
        predicted=ChannelValue.known_empty(),
        observed=observed_move,
        relevance=controlled.relevance,
        contributor_refs=(gate_ref,),
    )
    override_ref = policy._open_local_repair(action, override_residual, facts)
    assert override_ref is not None
    assert policy._mode_for_ref(override_ref) is CompositionMode.OVERRIDE
