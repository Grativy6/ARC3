from __future__ import annotations

import pytest

from arc3.mechanics import (
    CHANNEL_ORDER,
    ChannelValue,
    CompositionMode,
    ConsequenceChannel,
    ConsequenceVector,
    DelayedEffect,
    DisplacementEffect,
    EffectContribution,
    KnowledgeState,
    LegalActionEffect,
    MechanicContext,
    MechanicRef,
    MechanicScope,
    MechanicsError,
    ObjectEffect,
    ObjectOperation,
    QuantityEffect,
    ResidualKind,
    ScopeCeiling,
    ScoreProgressEffect,
    StatusEffect,
    TerminalEffect,
    TopologyEffect,
    TopologyOperation,
    compare_consequence,
    compose_contributions,
)
from arc3.types import ActionName, GameStateName


def _channel_vector(channel: ConsequenceChannel, value: ChannelValue) -> ConsequenceVector:
    return ConsequenceVector.unknown().with_channel(channel, value)


def test_complete_vector_distinguishes_unknown_from_known_empty() -> None:
    unknown = ConsequenceVector.unknown()
    known_empty = unknown.with_channel(
        ConsequenceChannel.RESOURCE_CHANGES, ChannelValue.known_empty()
    )

    assert tuple(channel for channel, _value in unknown.items()) == CHANNEL_ORDER
    assert unknown.resource_changes.knowledge is KnowledgeState.UNKNOWN
    assert known_empty.resource_changes.knowledge is KnowledgeState.KNOWN
    assert known_empty.resource_changes.is_known_empty
    assert unknown != known_empty
    assert ConsequenceVector.from_dict(known_empty.to_dict()) == known_empty


def test_vector_rejects_an_effect_in_the_wrong_factor() -> None:
    with pytest.raises(MechanicsError, match="incompatible effect"):
        ConsequenceVector(resource_changes=ChannelValue.known(DisplacementEffect("mover", 1, 0)))


def test_scope_composition_is_conjunctive_and_opaque_game_bounded() -> None:
    game = MechanicScope(
        ScopeCeiling.GAME,
        game_scope="opaque-game-a",
        object_roles=("controllable",),
    )
    level = MechanicScope(
        ScopeCeiling.LEVEL,
        game_scope="opaque-game-a",
        level_scope="level-2",
        region_tags=("near-door",),
    )

    composed = game.compose(level)

    assert composed is not None
    assert composed.ceiling is ScopeCeiling.LEVEL
    assert composed.matches(
        MechanicContext(
            "opaque-game-a",
            "level-2",
            region_tags=("near-door", "north"),
            object_roles=("controllable",),
        )
    )
    assert not composed.matches(MechanicContext("opaque-game-a", "level-3"))
    assert game.compose(MechanicScope(ScopeCeiling.GAME, game_scope="opaque-game-b")) is None


def test_every_typed_factor_roundtrips_without_semantic_loss() -> None:
    vector = ConsequenceVector(
        controlled_displacement=ChannelValue.known(DisplacementEffect("mover", 1, -1)),
        other_object_effects=ChannelValue.known(
            ObjectEffect("block", ObjectOperation.RECOLORED, "role-a")
        ),
        resource_changes=ChannelValue.known(QuantityEffect("energy", -1)),
        inventory_changes=ChannelValue.known(QuantityEffect("key", 1)),
        legal_action_changes=ChannelValue.known(LegalActionEffect(ActionName.ACTION5, True)),
        topology_changes=ChannelValue.known(
            TopologyEffect(
                "door-link",
                TopologyOperation.OPENED,
                "room-a",
                "room-b",
            )
        ),
        status_animation_changes=ChannelValue.known(StatusEffect("timer", "armed")),
        score_progress_changes=ChannelValue.known(ScoreProgressEffect("progress", 1)),
        terminal_changes=ChannelValue.known(TerminalEffect(GameStateName.WIN)),
        delayed_effects=ChannelValue.known(
            DelayedEffect(2, ConsequenceChannel.RESOURCE_CHANGES, "energy-drain")
        ),
    )

    assert ConsequenceVector.from_dict(vector.to_dict()) == vector


def test_base_and_additive_mechanics_compose_with_contribution_identity() -> None:
    channel = ConsequenceChannel.RESOURCE_CHANGES
    result = compose_contributions(
        (
            EffectContribution(
                MechanicRef("M-BASE", 1),
                CompositionMode.BASE,
                100,
                _channel_vector(channel, ChannelValue.known(QuantityEffect("energy", 3))),
            ),
            EffectContribution(
                MechanicRef("M-BONUS", 1),
                CompositionMode.ADDITIVE,
                201,
                _channel_vector(channel, ChannelValue.known(QuantityEffect("energy", 1))),
            ),
        )
    )

    assert result.consequence.resource_changes == ChannelValue.known(QuantityEffect("energy", 4))
    assert result.contributors_for(channel) == (
        MechanicRef("M-BASE", 1),
        MechanicRef("M-BONUS", 1),
    )


def test_equal_specificity_override_disagreement_remains_unknown() -> None:
    channel = ConsequenceChannel.CONTROLLED_DISPLACEMENT
    result = compose_contributions(
        (
            EffectContribution(
                MechanicRef("M-A", 1),
                CompositionMode.OVERRIDE,
                201,
                _channel_vector(channel, ChannelValue.known(DisplacementEffect("mover", 1, 0))),
            ),
            EffectContribution(
                MechanicRef("M-B", 1),
                CompositionMode.OVERRIDE,
                201,
                _channel_vector(channel, ChannelValue.known(DisplacementEffect("mover", 0, 1))),
            ),
        )
    )

    assert result.consequence.controlled_displacement.is_unknown
    assert result.ambiguities[0].channel is channel


def test_unknown_noncontributor_does_not_poison_a_known_contribution() -> None:
    channel = ConsequenceChannel.RESOURCE_CHANGES
    result = compose_contributions(
        (
            EffectContribution(
                MechanicRef("M-UNKNOWN", 1),
                CompositionMode.CONDITIONAL,
                200,
                ConsequenceVector.unknown(),
            ),
            EffectContribution(
                MechanicRef("M-KNOWN", 1),
                CompositionMode.BASE,
                100,
                _channel_vector(channel, ChannelValue.known_empty()),
            ),
        )
    )

    assert result.consequence.resource_changes.is_known_empty
    assert result.contributors_for(channel) == (MechanicRef("M-KNOWN", 1),)


def test_residuals_keep_occurrence_magnitude_and_relevance_separate() -> None:
    predicted = ConsequenceVector.unknown().with_channel(
        ConsequenceChannel.RESOURCE_CHANGES,
        ChannelValue.known(QuantityEffect("energy", -1)),
    )
    observed = ConsequenceVector.unknown().with_channel(
        ConsequenceChannel.RESOURCE_CHANGES,
        ChannelValue.known(QuantityEffect("energy", -2)),
    )
    residual = compare_consequence(predicted, observed)

    assert (
        residual.for_channel(ConsequenceChannel.RESOURCE_CHANGES).kind
        is ResidualKind.MAGNITUDE_MISMATCH
    )
    assert (
        residual.for_channel(ConsequenceChannel.RESOURCE_CHANGES).relevance
        > residual.for_channel(ConsequenceChannel.STATUS_ANIMATION_CHANGES).relevance
    )


def test_unknown_prediction_is_not_treated_as_a_known_noop() -> None:
    observed = ConsequenceVector.unknown().with_channel(
        ConsequenceChannel.STATUS_ANIMATION_CHANGES,
        ChannelValue.known(StatusEffect("lamp", "blink")),
    )

    residual = compare_consequence(ConsequenceVector.unknown(), observed)

    assert (
        residual.for_channel(ConsequenceChannel.STATUS_ANIMATION_CHANGES).kind
        is ResidualKind.UNKNOWN_PREDICTION
    )
