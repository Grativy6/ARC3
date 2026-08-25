"""Hand-built Stage 9 fixtures for relevance and persistence boundaries.

Named gap: ``STAGE9_SEQUENTIAL_GAME_CONTROLLER_ORCHESTRATION_NOT_MEASURED``.
The final test proves the mechanic-ledger admission boundary, but this bounded
slice does not exercise a production controller driving two environments.
"""

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
    MechanicEventType,
    MechanicLedger,
    MechanicRef,
    MechanicScope,
    MechanicsError,
    MechanicStatus,
    ProbeCandidate,
    QuantityEffect,
    ResidualKind,
    ScopeCeiling,
    StatusEffect,
    TerminalEffect,
)
from arc3.perception import (
    EvidenceFamily,
    EvidenceReading,
    LayerAssessment,
    LayerDeclaration,
    LogicalLayer,
    ReadabilityThreshold,
    ReadabilityWall,
    ResidualDisposition,
    ResidualReason,
    ValidityGate,
    assess_residual,
)
from arc3.types import ActionName, ActionRequest, GameStateName


def _movement_vector() -> ConsequenceVector:
    return ConsequenceVector.unknown().with_channel(
        ConsequenceChannel.CONTROLLED_DISPLACEMENT,
        ChannelValue.known(DisplacementEffect("controllable", 1, 0)),
    )


def _clef_assessment() -> LayerAssessment:
    declaration = LayerDeclaration(
        declaration_id="stage9:harmless-animation",
        layer=LogicalLayer.COMPONENTS,
        available_fields=("components", "frame.cells"),
        aperture="changed decorative components",
        noise_thresholds=(
            ReadabilityThreshold(EvidenceFamily.FRAME_CELLS, 1),
            ReadabilityThreshold(EvidenceFamily.COMPONENT_GEOMETRY, 1),
        ),
        extraction_method="hand-built-stage9-fixture",
        reader_identity="tests.stage9.boundaries",
        readability_wall=ReadabilityWall(max_detail_units=4, used_detail_units=1),
    )
    return LayerAssessment(
        declaration=declaration,
        readings=(
            EvidenceReading(EvidenceFamily.FRAME_CELLS, "decorative-frame-delta", 32),
            EvidenceReading(EvidenceFamily.COMPONENT_GEOMETRY, "stationary-decoration", 1),
        ),
        validity_gates=(ValidityGate("temporal-correspondence", True),),
    )


def _stable_movement_learner(
    *, game_scope: str = "stage9-game", level_scope: str = "palette-a"
) -> tuple[MechanicalLearner, MechanicRef]:
    learner = MechanicalLearner(game_scope=game_scope, level_scope=level_scope)
    view = learner.ledger.open(
        action=ActionName.ACTION1,
        scope=MechanicScope(ScopeCeiling.GAME, game_scope=game_scope),
        consequence=_movement_vector(),
        composition_mode=CompositionMode.BASE,
        created_step=0,
        created_from_event_ids=("E-MOVEMENT-DECLARED",),
        provenance=EvidenceProvenance.OBSERVED_THIS_GAME,
        mechanic_id="M-STABLE-MOVEMENT",
    )
    for index in range(3):
        learner.ledger.confirm_passively(
            view.ref,
            channels=(ConsequenceChannel.CONTROLLED_DISPLACEMENT,),
            source_event_ids=(f"E-MOVEMENT-SUPPORT-{index}",),
            context_key=f"movement-context-{index}",
            observed_step=index + 1,
            receipt_id=f"R-MOVEMENT-SUPPORT-{index}",
        )
    assert learner.ledger.get(view.ref).status is MechanicStatus.STABLE_WITHIN_SCOPE
    return learner, view.ref


def test_harmless_animation_is_parked_without_opening_a_probe_burden() -> None:
    clef = assess_residual(
        _clef_assessment(),
        already_explained=False,
        changes_prediction=False,
        changes_action_selection=False,
        additional_detail_cost=0,
        expected_decision_value=0,
    )
    learner = MechanicalLearner(game_scope="animation-game", level_scope="level-0")
    context = MechanicContext("animation-game", "level-0")
    prediction = learner.predict(ActionRequest(ActionName.ACTION1), context, emitted_step=0)
    observed = ConsequenceVector.unknown().with_channel(
        ConsequenceChannel.STATUS_ANIMATION_CHANGES,
        ChannelValue.known(
            *(StatusEffect(f"decoration-{index}", f"phase-{index}") for index in range(32))
        ),
    )

    learning = learner.observe_consequence(
        prediction.prediction_id,
        observed,
        source_event_ids=("E-HARMLESS-ANIMATION",),
        context_key="stationary-decoration",
        observed_step=0,
    )
    animation = learning.residual.for_channel(ConsequenceChannel.STATUS_ANIMATION_CHANGES)

    assert clef.disposition is ResidualDisposition.PARK
    assert clef.reason is ResidualReason.NO_DECISION_EFFECT
    assert animation.kind is ResidualKind.UNKNOWN_PREDICTION
    assert not animation.consequential
    assert learning.repair_candidates == ()
    assert learner.open_residuals == ()
    assert learner.pending == ()


def test_small_failure_linked_resource_anomaly_outranks_large_decoration() -> None:
    learner = MechanicalLearner(game_scope="failure-game", level_scope="level-0")
    context = MechanicContext("failure-game", "level-0")
    prediction = learner.predict(ActionRequest(ActionName.ACTION1), context, emitted_step=0)
    decoration = tuple(
        StatusEffect(f"decorative-cell-{index}", f"phase-{index}") for index in range(32)
    )
    observed = (
        ConsequenceVector.unknown()
        .with_channel(
            ConsequenceChannel.RESOURCE_CHANGES,
            ChannelValue.known(QuantityEffect("energy", -1)),
        )
        .with_channel(
            ConsequenceChannel.STATUS_ANIMATION_CHANGES,
            ChannelValue.known(*decoration),
        )
        .with_channel(
            ConsequenceChannel.TERMINAL_CHANGES,
            ChannelValue.known(TerminalEffect(GameStateName.GAME_OVER)),
        )
    )
    learning = learner.observe_consequence(
        prediction.prediction_id,
        observed,
        source_event_ids=("E-RESOURCE-EXHAUSTION", "E-GAME-OVER"),
        context_key="energy-zero",
        observed_step=0,
    )
    resource = learning.residual.for_channel(ConsequenceChannel.RESOURCE_CHANGES)
    animation = learning.residual.for_channel(ConsequenceChannel.STATUS_ANIMATION_CHANGES)
    terminal = learning.residual.for_channel(ConsequenceChannel.TERMINAL_CHANGES)
    decorative_probe = ProbeCandidate(
        ActionRequest(ActionName.ACTION2),
        context,
        (ConsequenceChannel.STATUS_ANIMATION_CHANGES,),
        expected_information_gain=4,
        novelty=100,
    )
    failure_probe = ProbeCandidate(
        ActionRequest(ActionName.ACTION3),
        context,
        (ConsequenceChannel.RESOURCE_CHANGES, ConsequenceChannel.TERMINAL_CHANGES),
        failure_cost=1,
    )

    choice = learner.choose_probe((decorative_probe, failure_probe))

    assert len(animation.observed.effects) == 32
    assert resource.relevance > animation.relevance
    assert terminal.relevance > resource.relevance
    assert resource.consequential and terminal.consequential
    assert not animation.consequential
    assert choice.selected is failure_probe
    assert choice.targeted_residual_ids == (learning.residual.residual_id,)


def test_low_confidence_high_impact_probe_preempts_stable_base_mechanic() -> None:
    learner, stable_ref = _stable_movement_learner()
    context = MechanicContext(learner.game_scope, learner.level_scope)
    prediction = learner.predict(ActionRequest(ActionName.ACTION2), context, emitted_step=4)
    learning = learner.observe_consequence(
        prediction.prediction_id,
        ConsequenceVector.unknown().with_channel(
            ConsequenceChannel.TERMINAL_CHANGES,
            ChannelValue.known(TerminalEffect(GameStateName.GAME_OVER)),
        ),
        source_event_ids=("E-LOW-CONFIDENCE-HAZARD",),
        context_key="unresolved-hazard",
        observed_step=4,
    )
    stable_base_check = ProbeCandidate(
        ActionRequest(ActionName.ACTION1),
        context,
        (ConsequenceChannel.CONTROLLED_DISPLACEMENT,),
        expected_information_gain=0,
        repetition_count=1,
    )
    # Expected information gain is the probe API's uncertainty proxy: the
    # unresolved hazard has some value, while the stable base rule has none.
    uncertain_high_impact = ProbeCandidate(
        ActionRequest(ActionName.ACTION2),
        context,
        (ConsequenceChannel.TERMINAL_CHANGES,),
        expected_information_gain=1,
        failure_cost=3,
    )

    choice = learner.choose_probe((stable_base_check, uncertain_high_impact))

    assert learner.ledger.get(stable_ref).status is MechanicStatus.STABLE_WITHIN_SCOPE
    assert learning.residual.for_channel(ConsequenceChannel.TERMINAL_CHANGES).consequential
    assert choice.selected is uncertain_high_impact
    assert choice.targeted_residual_ids == (learning.residual.residual_id,)


def test_visual_remap_retains_stable_mechanic_without_redeclaration() -> None:
    learner, movement_ref = _stable_movement_learner(
        game_scope="remap-game", level_scope="palette-a"
    )
    declarations_before = sum(
        event.event_type is MechanicEventType.VERSION_DECLARED for event in learner.ledger.events
    )

    boundary = learner.start_level("palette-b")
    remapped_context = MechanicContext(
        "remap-game",
        "palette-b",
        region_tags=("same-layout-d4", "palette-permutation-b"),
        object_roles=("controllable-recolored",),
    )
    prediction = learner.predict(
        ActionRequest(ActionName.ACTION1), remapped_context, emitted_step=5
    )
    learning = learner.observe_consequence(
        prediction.prediction_id,
        _movement_vector(),
        source_event_ids=("E-REMAPPED-MOVEMENT",),
        context_key="palette-b/same-displacement",
        observed_step=5,
    )
    declarations_after = sum(
        event.event_type is MechanicEventType.VERSION_DECLARED for event in learner.ledger.events
    )

    assert movement_ref in boundary.retained_refs
    assert movement_ref not in boundary.quarantined_refs
    assert prediction.composition.contributors_for(ConsequenceChannel.CONTROLLED_DISPLACEMENT) == (
        movement_ref,
    )
    assert (
        learning.residual.for_channel(ConsequenceChannel.CONTROLLED_DISPLACEMENT).kind
        is ResidualKind.MATCH
    )
    assert learning.residual.consequential == ()
    assert learning.repair_candidates == ()
    assert learner.open_residuals == ()
    assert learner.ledger.get(movement_ref).status is MechanicStatus.STABLE_WITHIN_SCOPE
    assert declarations_after == declarations_before == 1


def test_sequential_games_admit_generic_prior_and_quarantine_game_fact() -> None:
    first = MechanicalLearner(game_scope="opaque-game-a", level_scope="level-a")
    generic = first.ledger.open(
        action=ActionName.ACTION1,
        scope=MechanicScope(ScopeCeiling.GENERIC),
        consequence=_movement_vector(),
        composition_mode=CompositionMode.BASE,
        created_step=0,
        created_from_event_ids=("E-SOURCE-LABELED-GENERIC-PRIOR",),
        provenance=EvidenceProvenance.GENERIC_GAME_PRIOR,
        mechanic_id="M-GENERIC-MOVEMENT-PRIOR",
    )
    game_fact = first.ledger.open(
        action=ActionName.ACTION2,
        scope=MechanicScope(ScopeCeiling.GAME, game_scope="opaque-game-a"),
        consequence=ConsequenceVector.unknown().with_channel(
            ConsequenceChannel.RESOURCE_CHANGES,
            ChannelValue.known(QuantityEffect("game-a-energy", -2)),
        ),
        composition_mode=CompositionMode.CONDITIONAL,
        created_step=1,
        created_from_event_ids=("E-GAME-A-ONLY",),
        provenance=EvidenceProvenance.OBSERVED_THIS_GAME,
        mechanic_id="M-GAME-A-RESOURCE",
    )

    second_ledger = MechanicLedger(game_scope="opaque-game-b", budget=first.budget)
    second_ledger.declare(generic.version)
    with pytest.raises(MechanicsError, match="different opaque game"):
        second_ledger.declare(game_fact.version)
    second = MechanicalLearner(
        game_scope="opaque-game-b",
        level_scope="level-b",
        budget=first.budget,
        ledger=second_ledger,
    )
    second_context = MechanicContext("opaque-game-b", "level-b")
    prediction = second.predict(ActionRequest(ActionName.ACTION1), second_context, emitted_step=0)

    assert generic.version.scope.matches(second_context)
    assert not game_fact.version.scope.matches(second_context)
    assert tuple(item.ref for item in second.ledger.active()) == (generic.ref,)
    assert second.ledger.get(generic.ref).status is MechanicStatus.PROVISIONAL
    assert second.ledger.get(generic.ref).evidence_receipt_ids == ()
    assert prediction.composition.contributors_for(ConsequenceChannel.CONTROLLED_DISPLACEMENT) == (
        generic.ref,
    )
    assert all(
        item.version.provenance is EvidenceProvenance.GENERIC_GAME_PRIOR
        for item in second.ledger.active()
    )
    with pytest.raises(MechanicsError, match="different opaque game"):
        first.predict(ActionRequest(ActionName.ACTION2), second_context, emitted_step=2)
