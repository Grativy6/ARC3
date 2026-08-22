from __future__ import annotations

import pytest

from arc3.errors import WorldModelError
from arc3.hypotheses import (
    ActionSemanticsStatement,
    ControllableObjectStatement,
    HypothesisRegistry,
    HypothesisScope,
)
from arc3.policy import ARC3Controller
from arc3.types import ActionName, ActionRequest
from arc3.world_model import (
    Cell,
    CollisionBehavior,
    CollisionRule,
    MovementRule,
    NoOpRule,
    PreservedTransition,
    PromotionStatus,
    SymbolicEntity,
    SymbolicState,
    WorldModelEnsemble,
    compile_hypotheses,
    execute_rules,
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


def scene_state(*entities: SymbolicEntity, width: int = 8) -> SymbolicState:
    return SymbolicState(width, 3, entities)


def scene_transition(
    identifier: str,
    before: SymbolicState,
    after: SymbolicState,
) -> PreservedTransition:
    return PreservedTransition(
        identifier,
        before,
        ActionRequest(ActionName.ACTION1),
        after,
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


def test_compiled_noop_is_action_scoped_and_keeps_other_action_rules() -> None:
    registry = HypothesisRegistry()
    registry.create(
        hypothesis_id="H-NOOP",
        statement=ActionSemanticsStatement("ACTION1", "no-op", {"entity_id": "piece"}),
        scope=HypothesisScope.LEVEL,
        created_from_event_ids=("E-NOOP",),
        occurred_step=0,
    )
    registry.create(
        hypothesis_id="H-MOVE",
        statement=ActionSemanticsStatement(
            "ACTION2", "translation", {"entity_id": "piece", "dx": 1, "dy": 0}
        ),
        scope=HypothesisScope.LEVEL,
        created_from_event_ids=("E-MOVE",),
        occurred_step=1,
    )

    candidate = compile_hypotheses(registry.all()).candidates[0]

    assert any(isinstance(rule, NoOpRule) for rule in candidate.rules)
    assert execute_rules(
        candidate.rules, state(1), ActionRequest(ActionName.ACTION1)
    ).state == state(1)
    moved = execute_rules(
        candidate.rules, state(1), ActionRequest(ActionName.ACTION2)
    ).state.entity("piece")
    assert moved is not None and moved.anchor == Cell(2, 1)


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


def test_controlled_projection_ignores_exogenous_motion_without_mutating_raw_receipt() -> None:
    mover_rule = MovementRule("R-MOVER", ActionName.ACTION1, 1, 0, entity_id="mover")
    model = make_model_candidate(hypothesis_ids=("H-MOVER",), rules=(mover_rule,))
    before = scene_state(
        SymbolicEntity("mover", "mover", (Cell(1, 1),)),
        SymbolicEntity("guide", "guide", (Cell(5, 1),)),
    )
    after = scene_state(
        SymbolicEntity("mover", "mover", (Cell(2, 1),)),
        SymbolicEntity("guide", "guide", (Cell(6, 1),)),
    )
    raw = scene_transition("T-EXOGENOUS", before, after)

    assert retrodict(model, (raw,)).status is PromotionStatus.REJECTED
    projected = ARC3Controller._candidate_retrodiction_projection(model, raw)
    artifact = retrodict(model, (projected,))

    assert artifact.status is PromotionStatus.PROMOTED
    assert projected.source_event_ids == raw.source_event_ids
    assert projected.before.entity("guide") is None
    assert projected.after.entity("guide") is None
    assert raw.before == before
    assert raw.after == after
    assert raw.after.entity("guide") is not None


def test_stationary_component_absent_boundary_is_deferred_not_counted_as_a_match() -> None:
    model = make_model_candidate(
        hypothesis_ids=("H-MOVER",),
        rules=(MovementRule("R-MOVER", ActionName.ACTION1, 1, 0, entity_id="mover"),),
    )
    stationary = scene_transition(
        "T-MODAL-BOUNDARY",
        scene_state(SymbolicEntity("mover", "mover", (Cell(2, 1),)), width=5),
        scene_state(SymbolicEntity("mover", "mover", (Cell(2, 1),)), width=5),
    )

    compatible = ARC3Controller._candidate_retrodiction_transitions(model, (stationary,))

    assert compatible == ()
    assert stationary.before == stationary.after
    assert retrodict(model, compatible).matched_transition_ids == ()


def test_partial_action_model_defers_unclaimed_action_without_assuming_identity() -> None:
    model = make_model_candidate(
        hypothesis_ids=("H-ACTION2",),
        rules=(MovementRule("R-ACTION2", ActionName.ACTION2, 0, 1, entity_id="mover"),),
    )
    before = scene_state(SymbolicEntity("mover", "mover", (Cell(2, 1),)))
    unclaimed = PreservedTransition(
        "T-UNCLAIMED",
        before,
        ActionRequest(ActionName.ACTION1),
        scene_state(SymbolicEntity("mover", "mover", (Cell(3, 1),))),
        ("E-UNCLAIMED-BEFORE", "E-UNCLAIMED-AFTER"),
    )
    claimed = PreservedTransition(
        "T-CLAIMED",
        before,
        ActionRequest(ActionName.ACTION2),
        scene_state(SymbolicEntity("mover", "mover", (Cell(2, 2),))),
        ("E-CLAIMED-BEFORE", "E-CLAIMED-AFTER"),
    )

    compatible, unclaimed_ids, collision_ids = ARC3Controller._candidate_retrodiction_partition(
        model, (unclaimed, claimed)
    )
    artifact = retrodict(
        model,
        tuple(
            ARC3Controller._candidate_retrodiction_projection(model, item) for item in compatible
        ),
    )

    assert compatible == (claimed,)
    assert unclaimed_ids == (unclaimed.transition_id,)
    assert collision_ids == ()
    assert artifact.status is PromotionStatus.PROMOTED
    assert artifact.matched_transition_ids == (claimed.transition_id,)


def test_unobstructed_wrong_mover_displacement_remains_a_contradiction() -> None:
    model = make_model_candidate(
        hypothesis_ids=("H-MOVER",),
        rules=(MovementRule("R-MOVER", ActionName.ACTION1, 1, 0, entity_id="mover"),),
    )
    wrong = scene_transition(
        "T-WRONG",
        scene_state(SymbolicEntity("mover", "mover", (Cell(2, 1),))),
        scene_state(SymbolicEntity("mover", "mover", (Cell(1, 1),))),
    )

    compatible = ARC3Controller._candidate_retrodiction_transitions(model, (wrong,))
    artifact = retrodict(
        model,
        tuple(
            ARC3Controller._candidate_retrodiction_projection(model, item) for item in compatible
        ),
    )

    assert compatible == (wrong,)
    assert artifact.status is PromotionStatus.REJECTED
    assert artifact.contradiction_transition_ids == (wrong.transition_id,)


def test_occupied_destination_pass_is_tested_while_block_and_unknown_are_deferred() -> None:
    movement = MovementRule("R-MOVER", ActionName.ACTION1, 1, 0, entity_id="mover")
    pass_model = make_model_candidate(
        hypothesis_ids=("H-PASS",),
        rules=(
            movement,
            CollisionRule(
                "R-PASS",
                moving_kind="mover",
                obstacle_kind="terrain",
                behavior=CollisionBehavior.PASS,
            ),
        ),
    )
    block_model = make_model_candidate(
        hypothesis_ids=("H-BLOCK",),
        rules=(
            movement,
            CollisionRule(
                "R-BLOCK",
                moving_kind="mover",
                obstacle_kind="terrain",
                behavior=CollisionBehavior.BLOCK,
            ),
        ),
    )
    unknown_model = make_model_candidate(hypothesis_ids=("H-UNKNOWN",), rules=(movement,))
    before = scene_state(
        SymbolicEntity("mover", "mover", (Cell(1, 1),)),
        SymbolicEntity("terrain", "terrain", (Cell(2, 1),)),
    )
    passed = scene_transition(
        "T-PASS",
        before,
        scene_state(
            SymbolicEntity("mover", "mover", (Cell(2, 1),)),
            SymbolicEntity("terrain", "terrain", (Cell(2, 1),)),
        ),
    )

    assert ARC3Controller._candidate_retrodiction_transitions(pass_model, (passed,)) == (passed,)
    assert (
        retrodict(
            pass_model,
            (ARC3Controller._candidate_retrodiction_projection(pass_model, passed),),
        ).status
        is PromotionStatus.PROMOTED
    )
    assert ARC3Controller._candidate_retrodiction_transitions(block_model, (passed,)) == ()
    assert ARC3Controller._candidate_retrodiction_transitions(unknown_model, (passed,)) == ()
