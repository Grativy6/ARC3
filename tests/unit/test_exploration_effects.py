"""Unit coverage for generic action-effect classification and statistics."""

from __future__ import annotations

import pytest

from arc3.adapters import GridFrame, Observation
from arc3.exploration import (
    ActionEffectStatistics,
    EffectKind,
    StateFeatures,
    classify_effect,
    state_features,
)
from arc3.types import ActionName, ActionRequest, Coordinate, GameId, GameStateName


def _observation(
    rows: list[list[int]],
    *,
    state: GameStateName = GameStateName.NOT_FINISHED,
    metadata: tuple[tuple[str, int], ...] = (("step", 0),),
) -> Observation:
    return Observation(
        game_id=GameId("fixture"),
        frames=(GridFrame.from_rows(rows),),
        state=state,
        levels_completed=int(state is GameStateName.WIN),
        win_levels=1,
        available_actions=tuple(ActionName)[1:],
        upstream_metadata=metadata,
    )


def test_classifies_noop_movement_and_metadata_only_without_causal_overclaim() -> None:
    start = _observation([[0, 0, 0], [0, 1, 0], [0, 0, 0]])
    moved = _observation([[0, 0, 0], [0, 0, 1], [0, 0, 0]], metadata=(("step", 1),))
    metadata = _observation([[0, 0, 0], [0, 1, 0], [0, 0, 0]], metadata=(("step", 1),))

    noop = classify_effect(start, start, ActionRequest(ActionName.ACTION5))
    movement = classify_effect(start, moved, ActionRequest(ActionName.ACTION1))
    metadata_only = classify_effect(start, metadata, ActionRequest(ActionName.ACTION5))

    assert noop.kinds == frozenset({EffectKind.NO_OP})
    assert movement.primary is EffectKind.MOVEMENT
    assert movement.displacement == (1, 0)
    assert "step" in movement.metadata_fields
    assert metadata_only.kinds == frozenset({EffectKind.METADATA_ONLY})


def test_classifies_selection_interaction_supported_undo_and_terminal() -> None:
    start = _observation([[0, 0, 0], [0, 1, 0], [0, 0, 0]])
    changed = _observation([[0, 0, 0], [0, 2, 0], [0, 0, 0]], metadata=(("step", 1),))
    terminal = _observation(
        [[0, 0, 0], [0, 2, 0], [0, 0, 0]],
        state=GameStateName.WIN,
        metadata=(("step", 1),),
    )
    action6 = ActionRequest(ActionName.ACTION6, Coordinate(1, 1))

    selection = classify_effect(start, changed, action6)
    interaction = classify_effect(start, changed, ActionRequest(ActionName.ACTION5))
    undo = classify_effect(
        changed,
        start,
        ActionRequest(ActionName.ACTION7),
        undo_target=start.frames[-1].digest,
    )
    ended = classify_effect(start, terminal, action6)

    assert selection.primary is EffectKind.SELECTION
    assert interaction.primary is EffectKind.INTERACTION
    assert undo.primary is EffectKind.UNDO
    assert EffectKind.TERMINAL in ended.kinds
    assert EffectKind.SELECTION in ended.kinds


def test_stationary_duplicate_components_do_not_create_false_movement() -> None:
    before = _observation([[1, 0, 1], [0, 2, 0], [0, 0, 0]], metadata=(("step", 0),))
    after = _observation([[1, 0, 1], [0, 3, 0], [0, 0, 0]], metadata=(("step", 1),))

    effect = classify_effect(before, after, ActionRequest(ActionName.ACTION5))

    assert effect.primary is EffectKind.INTERACTION
    assert EffectKind.MOVEMENT not in effect.kinds


def test_observation_overrides_weak_directional_prior_within_condition() -> None:
    observation = _observation([[0, 0, 0], [0, 1, 0], [0, 0, 0]])
    features = state_features(observation)
    action = ActionRequest(ActionName.ACTION1)
    statistics = ActionEffectStatistics(directional_prior_weight=0.25)

    prior = statistics.estimate(features, action)
    statistics.observe(
        features,
        action,
        classify_effect(
            observation,
            _observation([[0, 0, 0], [0, 0, 1], [0, 0, 0]]),
            action,
        ),
    )
    learned = statistics.estimate(features, action)

    assert prior.prior_only is True
    assert prior.displacement == (0, -1)
    assert learned.prior_only is False
    assert learned.displacement == (1, 0)
    assert learned.observations == 1


def test_state_features_reject_non_integer_measurements() -> None:
    with pytest.raises(ValueError, match="width"):
        StateFeatures(
            width=1.5,  # type: ignore[arg-type]
            height=8,
            palette_size=2,
            component_count=1,
            changed_cell_count=0,
            game_state=GameStateName.NOT_FINISHED,
            available_actions=(ActionName.ACTION1,),
        )
