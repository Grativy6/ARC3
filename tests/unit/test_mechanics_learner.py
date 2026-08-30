from __future__ import annotations

import pytest

from arc3.mechanics import (
    ChannelValue,
    CompositionMode,
    ConsequenceChannel,
    ConsequenceVector,
    DisplacementEffect,
    EvidenceProvenance,
    MechanicalLearner,
    MechanicContext,
    MechanicLedgerBudget,
    MechanicRef,
    MechanicScope,
    MechanicsError,
    MechanicStatus,
    ProbeCandidate,
    QuantityEffect,
    RepairCandidateKind,
    ScopeCeiling,
    StatusEffect,
)
from arc3.types import ActionName, ActionRequest


def _two_channel_vector() -> ConsequenceVector:
    return (
        ConsequenceVector.unknown()
        .with_channel(
            ConsequenceChannel.CONTROLLED_DISPLACEMENT,
            ChannelValue.known(DisplacementEffect("controllable", 1, 0)),
        )
        .with_channel(
            ConsequenceChannel.RESOURCE_CHANGES,
            ChannelValue.known(QuantityEffect("energy", -1)),
        )
    )


def _learner() -> tuple[MechanicalLearner, MechanicRef]:
    learner = MechanicalLearner(game_scope="opaque-game", level_scope="L0")
    view = learner.ledger.open(
        action=ActionName.ACTION1,
        scope=MechanicScope(ScopeCeiling.GAME, game_scope="opaque-game"),
        consequence=_two_channel_vector(),
        composition_mode=CompositionMode.BASE,
        created_step=0,
        created_from_event_ids=("E-OBS-0",),
        provenance=EvidenceProvenance.OBSERVED_THIS_GAME,
        mechanic_id="M-ACTION1",
    )
    return learner, view.ref


def test_passive_confirmation_updates_only_matching_contribution_channels() -> None:
    learner, ref = _learner()
    context = MechanicContext("opaque-game", "L0")
    prediction = learner.predict(ActionRequest(ActionName.ACTION1), context, emitted_step=1)
    observed = _two_channel_vector().with_channel(
        ConsequenceChannel.RESOURCE_CHANGES,
        ChannelValue.known(QuantityEffect("energy", -2)),
    )

    result = learner.observe_consequence(
        prediction.prediction_id,
        observed,
        source_event_ids=("E-CONSEQUENCE-1",),
        context_key="position-a/resources-2",
        observed_step=1,
    )

    view = learner.ledger.get(ref)
    assert (
        view.summary_for(ConsequenceChannel.CONTROLLED_DISPLACEMENT).occurrence_support_count == 1
    )
    assert view.summary_for(ConsequenceChannel.RESOURCE_CHANGES).occurrence_support_count == 0
    assert result.residual.for_channel(ConsequenceChannel.RESOURCE_CHANGES).consequential
    assert not result.residual.for_channel(ConsequenceChannel.CONTROLLED_DISPLACEMENT).consequential


def test_local_repairs_precede_and_gate_base_reopening() -> None:
    learner, ref = _learner()
    context = MechanicContext(
        "opaque-game",
        "L0",
        region_tags=("doorway",),
        object_roles=("controllable", "barrier"),
    )
    prediction = learner.predict(ActionRequest(ActionName.ACTION1), context, emitted_step=1)
    observed = _two_channel_vector().with_channel(
        ConsequenceChannel.CONTROLLED_DISPLACEMENT, ChannelValue.known_empty()
    )
    learned = learner.observe_consequence(
        prediction.prediction_id,
        observed,
        source_event_ids=("E-CONSEQUENCE",),
        context_key="doorway-a",
        observed_step=1,
    )

    assert learned.repair_candidates
    assert all(
        item.kind is not RepairCandidateKind.BASE_REOPEN for item in learned.repair_candidates
    )
    first = learner.record_local_repair_failure(learned.residual.residual_id)
    second = learner.record_local_repair_failure(learned.residual.residual_id)
    assert all(item.kind is not RepairCandidateKind.BASE_REOPEN for item in first)
    assert second[-1].kind is RepairCandidateKind.BASE_REOPEN

    reopened = learner.reopen_implicated(
        learned.residual.residual_id,
        source_event_ids=("E-LOCAL-FAILURES",),
        observed_step=3,
    )
    assert reopened == (ref,)
    assert learner.ledger.get(ref).status is MechanicStatus.REOPENED


def test_game_mechanics_survive_level_boundary_while_level_layout_is_quarantined() -> None:
    learner, game_ref = _learner()
    level_view = learner.ledger.open(
        action=ActionName.ACTION2,
        scope=MechanicScope(
            ScopeCeiling.LEVEL,
            game_scope="opaque-game",
            level_scope="L0",
            region_tags=("layout-a",),
        ),
        consequence=ConsequenceVector.unknown().with_channel(
            ConsequenceChannel.STATUS_ANIMATION_CHANGES,
            ChannelValue.known(StatusEffect("gate", "open")),
        ),
        composition_mode=CompositionMode.CONDITIONAL,
        created_step=1,
        created_from_event_ids=("E-LAYOUT",),
        provenance=EvidenceProvenance.OBSERVED_THIS_GAME,
        mechanic_id="M-LAYOUT",
    )

    boundary = learner.start_level("L1")

    assert game_ref in boundary.retained_refs
    assert level_view.ref in boundary.quarantined_refs
    assert (
        learner.ledger.applicable(ActionName.ACTION1, MechanicContext("opaque-game", "L1"))[0].ref
        == game_ref
    )
    assert not learner.ledger.applicable(
        ActionName.ACTION2,
        MechanicContext("opaque-game", "L1", region_tags=("layout-a",)),
    )


def test_probe_choice_prioritizes_consequential_resource_anomaly_and_is_bounded() -> None:
    learner, _ref = _learner()
    context = MechanicContext("opaque-game", "L0")
    candidates = [
        ProbeCandidate(
            ActionRequest(ActionName.ACTION2),
            context,
            (ConsequenceChannel.STATUS_ANIMATION_CHANGES,),
            expected_information_gain=4,
        ),
        ProbeCandidate(
            ActionRequest(ActionName.ACTION3),
            context,
            (ConsequenceChannel.RESOURCE_CHANGES,),
            expected_information_gain=1,
        ),
    ]
    candidates.extend(
        ProbeCandidate(
            ActionRequest(ActionName.ACTION4),
            context,
            (ConsequenceChannel.OTHER_OBJECT_EFFECTS,),
            novelty=index,
        )
        for index in range(12)
    )

    choice = learner.choose_probe(candidates)

    assert choice.selected.action.name is ActionName.ACTION3
    assert len(choice.considered_signatures) == learner.budget.max_probe_candidates


def test_pending_prediction_and_compact_state_roundtrip_without_game_rebinding() -> None:
    learner, _ref = _learner()
    context = MechanicContext("opaque-game", "L0")
    pending = learner.predict(ActionRequest(ActionName.ACTION1), context, emitted_step=1)
    encoded = learner.compact_bytes()

    restored = MechanicalLearner.from_compact_bytes(encoded, expected_game_scope="opaque-game")

    assert restored.compact_bytes() == encoded
    assert restored.pending[0].prediction_id == pending.prediction_id
    with pytest.raises(MechanicsError, match="different opaque game"):
        MechanicalLearner.from_compact_bytes(encoded, expected_game_scope="other-game")


def test_prediction_gate_allows_exactly_one_unmatched_action() -> None:
    learner, _ref = _learner()
    context = MechanicContext("opaque-game", "L0")
    learner.predict(ActionRequest(ActionName.ACTION1), context, emitted_step=1)

    with pytest.raises(MechanicsError, match="must match"):
        learner.predict(ActionRequest(ActionName.ACTION1), context, emitted_step=2)


def test_invalid_consequence_receipt_does_not_consume_pending_prediction() -> None:
    learner, _ref = _learner()
    context = MechanicContext("opaque-game", "L0")
    pending = learner.predict(ActionRequest(ActionName.ACTION1), context, emitted_step=1)

    with pytest.raises(MechanicsError, match="source event"):
        learner.observe_consequence(
            pending.prediction_id,
            _two_channel_vector(),
            source_event_ids=(),
            context_key="context",
            observed_step=1,
        )

    assert learner.pending == (pending,)


def test_open_residual_queue_retains_only_highest_bounded_anomalies() -> None:
    learner = MechanicalLearner(
        game_scope="opaque-game",
        level_scope="L0",
        budget=MechanicLedgerBudget(max_open_residuals=2),
    )
    context = MechanicContext("opaque-game", "L0")
    for index in range(3):
        prediction = learner.predict(ActionRequest(ActionName.ACTION1), context, emitted_step=index)
        observed = ConsequenceVector.unknown().with_channel(
            ConsequenceChannel.RESOURCE_CHANGES,
            ChannelValue.known(QuantityEffect("energy", index + 1)),
        )
        learner.observe_consequence(
            prediction.prediction_id,
            observed,
            source_event_ids=(f"E-{index}",),
            context_key=f"context-{index}",
            observed_step=index,
        )

    assert len(learner.open_residuals) == 2
    assert learner.dropped_residual_count == 1


def test_open_residual_and_repair_state_roundtrip_deterministically() -> None:
    learner, _ref = _learner()
    context = MechanicContext("opaque-game", "L0", region_tags=("gate",))
    prediction = learner.predict(ActionRequest(ActionName.ACTION1), context, emitted_step=1)
    result = learner.observe_consequence(
        prediction.prediction_id,
        _two_channel_vector().with_channel(
            ConsequenceChannel.RESOURCE_CHANGES,
            ChannelValue.known(QuantityEffect("energy", -3)),
        ),
        source_event_ids=("E-CONSEQUENCE",),
        context_key="gate-resource",
        observed_step=1,
    )
    learner.record_local_repair_failure(result.residual.residual_id)
    encoded = learner.compact_bytes()

    restored = MechanicalLearner.from_compact_bytes(encoded, expected_game_scope="opaque-game")

    assert restored.compact_bytes() == encoded
    assert restored.open_residuals[0].residual.residual_id == result.residual.residual_id
