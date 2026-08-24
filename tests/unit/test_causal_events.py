from __future__ import annotations

from arc3.adapters import GridFrame, Observation
from arc3.exploration import (
    FIXED_EFFECT_CHANNELS,
    CausalActionReceipt,
    EffectChannel,
    EffectKnowledge,
    EffectVector,
    FactoredEffect,
    ResidualKind,
    ResourceFailureRisk,
    RiskLevel,
    compare_effect_vectors,
    consequence_priority,
    extract_observed_effects,
)
from arc3.perception import FrameDelta, measure_delta, observation_metadata
from arc3.perception.layers import ResidualDisposition
from arc3.types import ActionName, ActionRequest, GameId, GameStateName


def _observation(
    rows: list[list[int]],
    *,
    state: GameStateName = GameStateName.NOT_FINISHED,
    levels: int = 0,
    win_levels: int = 3,
    actions: tuple[ActionName, ...] = (ActionName.ACTION1,),
    metadata: tuple[tuple[str, int], ...] = (),
    full_reset: bool = False,
) -> Observation:
    return Observation(
        game_id=GameId("fixture"),
        frames=(GridFrame.from_rows(rows),),
        state=state,
        levels_completed=levels,
        win_levels=win_levels,
        available_actions=actions,
        full_reset=full_reset,
        upstream_metadata=metadata,
    )


def _delta(before: Observation, after: Observation) -> FrameDelta:
    return measure_delta(
        before.frames[-1],
        after.frames[-1],
        before_metadata=observation_metadata(before),
        after_metadata=observation_metadata(after),
    )


def test_effect_vector_has_exact_fixed_channels_and_explicit_unknowns() -> None:
    vector = EffectVector.unknown()

    assert tuple(effect.channel for effect in vector.effects) == FIXED_EFFECT_CHANNELS
    assert tuple(EffectChannel) == FIXED_EFFECT_CHANNELS
    assert all(effect.knowledge is EffectKnowledge.UNKNOWN for effect in vector.effects)


def test_arbitrary_counter_and_large_visual_change_stay_dynamic_candidates() -> None:
    before = _observation([[0, 0], [0, 0]], metadata=(("visual_counter_17", 0),))
    after = _observation([[1, 1], [1, 1]], metadata=(("visual_counter_17", 999),))
    observed = extract_observed_effects(
        before,
        after,
        _delta(before, after),
        evidence_refs=("event:delta",),
    )

    assert observed.get(EffectChannel.RESOURCE_HUD_CHANGE).knowledge is EffectKnowledge.UNKNOWN
    assert observed.get(EffectChannel.INVENTORY_COUNT_CHANGE).knowledge is EffectKnowledge.UNKNOWN
    assert observed.get(EffectChannel.STATUS_ANIMATION_CHANGE).knowledge is EffectKnowledge.UNKNOWN
    unresolved = observed.get(EffectChannel.DELAYED_UNRESOLVED)
    assert unresolved.knowledge is EffectKnowledge.KNOWN
    assert unresolved.dynamic_candidate
    assert unresolved.value == {
        "unclassified_changed_cell_count": 4,
        "dynamic_fields": [
            {
                "field": "visual_counter_17",
                "before_present": True,
                "after_present": True,
                "before": 0,
                "after": 999,
                "evidence_refs": ["event:delta"],
            }
        ],
    }


def test_official_small_metadata_effects_remain_visible_without_pixel_change() -> None:
    before = _observation([[0]], actions=(ActionName.ACTION1,))
    after = _observation(
        [[0]],
        state=GameStateName.WIN,
        levels=1,
        actions=(ActionName.ACTION1, ActionName.ACTION2),
    )
    delta = _delta(before, after)
    observed = extract_observed_effects(before, after, delta, evidence_refs=("event:metadata",))

    assert delta.changed_cell_count == 0
    assert not delta.apparent_noop
    assert observed.get(EffectChannel.LEGAL_ACTION_CHANGE).knowledge is EffectKnowledge.KNOWN
    assert observed.get(EffectChannel.SCORE_PROGRESS_CHANGE).knowledge is EffectKnowledge.KNOWN
    terminal = observed.get(EffectChannel.TERMINAL_RESET_TRANSITION)
    assert terminal.knowledge is EffectKnowledge.KNOWN
    assert terminal.value == {
        "before_state": "NOT_FINISHED",
        "after_state": "WIN",
        "before_full_reset": False,
        "after_full_reset": False,
    }


def test_unknown_prediction_opens_information_instead_of_a_contradiction() -> None:
    predicted = EffectVector.from_effects(
        (
            FactoredEffect(
                EffectChannel.RESOURCE_HUD_CHANGE,
                EffectKnowledge.UNKNOWN,
            ),
        ),
        unspecified=EffectKnowledge.NOT_APPLICABLE,
    )
    observed = EffectVector.from_effects(
        (
            FactoredEffect(
                EffectChannel.RESOURCE_HUD_CHANGE,
                EffectKnowledge.KNOWN,
                {"delta": -1},
                ("event:resource",),
            ),
        ),
        unspecified=EffectKnowledge.NOT_APPLICABLE,
    )

    comparison = compare_effect_vectors(predicted, observed)

    assert comparison.explained_effects == ()
    assert len(comparison.residual_effects) == 1
    residual = comparison.residual_effects[0]
    assert residual.kind is ResidualKind.OPEN_INFORMATION
    assert residual.disposition is ResidualDisposition.PARK


def test_factored_comparison_preserves_correct_movement_when_resource_is_wrong() -> None:
    movement = FactoredEffect(
        EffectChannel.CONTROLLABLE_OBJECT_DISPLACEMENT,
        EffectKnowledge.KNOWN,
        {"dx": 1, "dy": 0},
    )
    predicted = EffectVector.from_effects(
        (
            movement,
            FactoredEffect(
                EffectChannel.RESOURCE_HUD_CHANGE,
                EffectKnowledge.KNOWN,
                {"delta": -1},
            ),
        ),
        unspecified=EffectKnowledge.NOT_APPLICABLE,
    )
    observed = EffectVector.from_effects(
        (
            movement,
            FactoredEffect(
                EffectChannel.RESOURCE_HUD_CHANGE,
                EffectKnowledge.KNOWN,
                {"delta": 4},
            ),
        ),
        unspecified=EffectKnowledge.NOT_APPLICABLE,
    )

    comparison = compare_effect_vectors(
        predicted,
        observed,
        dispositions={EffectChannel.RESOURCE_HUD_CHANGE: ResidualDisposition.PROMOTE},
    )

    assert tuple(effect.channel for effect in comparison.explained_effects) == (
        EffectChannel.CONTROLLABLE_OBJECT_DISPLACEMENT,
    )
    assert tuple(residual.channel for residual in comparison.residual_effects) == (
        EffectChannel.RESOURCE_HUD_CHANGE,
    )
    assert comparison.residual_effects[0].kind is ResidualKind.MISMATCH
    assert comparison.residual_effects[0].disposition is ResidualDisposition.PROMOTE


def test_critical_metadata_lexicographically_outranks_large_decoration() -> None:
    small_resource_change = FactoredEffect(
        EffectChannel.RESOURCE_HUD_CHANGE,
        EffectKnowledge.KNOWN,
        {"delta": 1},
    )
    large_decoration = FactoredEffect(
        EffectChannel.STATUS_ANIMATION_CHANGE,
        EffectKnowledge.KNOWN,
        {"changed_cell_count": 4096},
    )

    resource_priority = consequence_priority(small_resource_change, visual_magnitude=1)
    decoration_priority = consequence_priority(large_decoration, visual_magnitude=4096)

    assert resource_priority.sort_key > decoration_priority.sort_key


def test_causal_action_receipt_contains_every_required_field() -> None:
    predicted = EffectVector.unknown()
    observed = EffectVector.from_effects((), unspecified=EffectKnowledge.NOT_APPLICABLE)
    comparison = compare_effect_vectors(predicted, observed)
    receipt = CausalActionReceipt(
        receipt_id="receipt:1",
        game_scope_id="game-scope:1",
        level_scope_id="level-scope:1",
        step_index=1,
        before_state_ref="event:before",
        chosen_action_and_coordinates=ActionRequest(ActionName.ACTION1),
        legal_actions_before=(ActionName.ACTION1,),
        predicted_effects=predicted,
        observed_effects=observed,
        explained_effects=comparison.explained_effects,
        residual_effects=comparison.residual_effects,
        objects_or_regions_implicated=(),
        active_hypotheses_used=(),
        probe_or_progress_reason="smallest discriminating action",
        resource_and_failure_risk=ResourceFailureRisk(
            RiskLevel.UNKNOWN,
            "no supported resource or failure link",
        ),
        terminal_state=GameStateName.NOT_FINISHED,
    )

    assert receipt.complete
    assert set(receipt.to_dict()) == {
        "receipt_id",
        "game_scope_id",
        "level_scope_id",
        "step_index",
        "before_state_ref",
        "chosen_action_and_coordinates",
        "legal_actions_before",
        "predicted_effects",
        "observed_effects",
        "explained_effects",
        "residual_effects",
        "objects_or_regions_implicated",
        "active_hypotheses_used",
        "probe_or_progress_reason",
        "resource_and_failure_risk",
        "terminal_state",
    }
