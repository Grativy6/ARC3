from __future__ import annotations

import pytest

from arc3.errors import WorldModelError
from arc3.hypotheses import (
    ActionSemanticsStatement,
    ControllableObjectStatement,
    HypothesisRegistry,
    HypothesisScope,
)
from arc3.types import ActionName, ActionRequest
from arc3.world_model import (
    Cell,
    MovementRule,
    PreservedTransition,
    PromotionStatus,
    SymbolicEntity,
    SymbolicState,
    WorldModelEnsemble,
    compile_hypotheses,
    gated_ensemble,
    make_model_candidate,
    retrodict,
    simulate_sequence,
)


def state(x: int) -> SymbolicState:
    return SymbolicState(8, 3, (SymbolicEntity("piece", "mover", (Cell(x, 1),)),))


def transition(identifier: str, before_x: int, after_x: int) -> PreservedTransition:
    return PreservedTransition(
        identifier,
        state(before_x),
        ActionRequest(ActionName.ACTION1),
        state(after_x),
        (f"event:{identifier}:before", f"event:{identifier}:after"),
    )


def test_compiler_preserves_conflicting_action_semantics_as_candidates() -> None:
    registry = HypothesisRegistry()
    registry.create(
        hypothesis_id="H-OBJECT",
        statement=ControllableObjectStatement("piece", ("moves",), ("ACTION1",)),
        scope=HypothesisScope.LEVEL,
        created_from_event_ids=("E-0",),
        occurred_step=0,
    )
    registry.create(
        hypothesis_id="H-RIGHT",
        statement=ActionSemanticsStatement("ACTION1", "translate", {"dx": 1}),
        scope=HypothesisScope.LEVEL,
        created_from_event_ids=("E-1",),
        occurred_step=1,
        initial_rank_weight=2,
    )
    registry.create(
        hypothesis_id="H-LEFT",
        statement=ActionSemanticsStatement("ACTION1", "translate", {"dx": -1}),
        scope=HypothesisScope.LEVEL,
        created_from_event_ids=("E-1",),
        occurred_step=1,
        initial_rank_weight=3,
    )

    compiled = compile_hypotheses(registry.all())

    movement_directions = {
        (rule.dx, rule.dy)
        for candidate in compiled.candidates
        for rule in candidate.rules
        if isinstance(rule, MovementRule)
    }
    assert movement_directions == {(-1, 0), (1, 0)}
    assert len(compiled.candidates) == 2
    assert all("H-OBJECT" in candidate.hypothesis_ids for candidate in compiled.candidates)


def test_gate_scores_fit_complexity_contradictions_and_residuals() -> None:
    good = make_model_candidate(
        hypothesis_ids=("H-GOOD",),
        rules=(MovementRule("R-GOOD", ActionName.ACTION1, 1, 0, entity_id="piece"),),
    )
    bad = make_model_candidate(
        hypothesis_ids=("H-BAD",),
        rules=(MovementRule("R-BAD", ActionName.ACTION1, -1, 0, entity_id="piece"),),
        rank_weight=10,
    )
    history = (transition("T-1", 1, 2), transition("T-2", 2, 3))

    good_artifact = retrodict(good, history)
    bad_artifact = retrodict(bad, history)

    assert good_artifact.status is PromotionStatus.PROMOTED
    assert good_artifact.score.fit == 1.0
    assert good_artifact.score.contradictions == 0
    assert good_artifact.complete
    assert bad_artifact.status is PromotionStatus.REJECTED
    assert bad_artifact.score.contradictions == 2
    assert bad_artifact.residuals[0].changed_entities == ("piece",)
    assert set(bad_artifact.compatible_transition_ids) == {"T-1", "T-2"}

    ensemble = gated_ensemble((good, bad), (good_artifact, bad_artifact))
    simulation = simulate_sequence(
        ensemble,
        state(3),
        (ActionRequest(ActionName.ACTION1), ActionRequest(ActionName.ACTION1)),
    )
    assert simulation.paths[0].state.entity("piece").anchor == Cell(5, 1)  # type: ignore[union-attr]


def test_retrodiction_off_is_explicit_and_cannot_silently_promote() -> None:
    model = make_model_candidate(
        hypothesis_ids=("H",),
        rules=(MovementRule("R", ActionName.ACTION1, 1, 0, entity_id="piece"),),
    )
    artifact = retrodict(model, (transition("T", 1, 2),), enabled=False)

    assert artifact.status is PromotionStatus.UNGATED_ABLATION
    assert not artifact.promotable
    with pytest.raises(WorldModelError, match="cannot be empty"):
        gated_ensemble((model,), (artifact,))
    assert gated_ensemble((model,), (artifact,), allow_ungated_ablation=True).candidates == (model,)


def test_ensemble_returns_explicit_alternative_outcomes_with_rank_weights() -> None:
    right = make_model_candidate(
        hypothesis_ids=("H-R",),
        rules=(MovementRule("R-R", ActionName.ACTION1, 1, 0, entity_id="piece"),),
        rank_weight=1,
    )
    left = make_model_candidate(
        hypothesis_ids=("H-L",),
        rules=(MovementRule("R-L", ActionName.ACTION1, -1, 0, entity_id="piece"),),
        rank_weight=2,
    )
    prediction = WorldModelEnsemble((right, left)).predict(
        state(3), ActionRequest(ActionName.ACTION1)
    )

    assert prediction.underdetermined
    assert [item.rank_weight for item in prediction.alternatives] == [2, 1]
    assert all(item.weight_kind == "uncalibrated_rank" for item in prediction.alternatives)
    assert {item.after_state.entity("piece").anchor.x for item in prediction.alternatives} == {2, 4}  # type: ignore[union-attr]
