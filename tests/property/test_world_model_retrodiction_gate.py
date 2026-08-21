from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from arc3.types import ActionName, ActionRequest
from arc3.world_model import (
    Cell,
    ConditionKind,
    MovementRule,
    PreservedTransition,
    PromotionStatus,
    RuleCondition,
    SymbolicEntity,
    SymbolicState,
    WorldModelEnsemble,
    make_model_candidate,
    retrodict,
    simulate_sequence,
)


def state(x: int, *, mode: bool = False) -> SymbolicState:
    return SymbolicState(
        64,
        3,
        (SymbolicEntity("piece", "mover", (Cell(x, 1),)),),
        facts=("mode",) if mode else (),
    )


@settings(max_examples=45, deadline=None)
@given(
    start=st.integers(min_value=10, max_value=50),
    expected_dx=st.integers(min_value=-5, max_value=5).filter(lambda value: value != 0),
    wrong_dx=st.integers(min_value=-5, max_value=5).filter(lambda value: value != 0),
)
def test_any_preserved_contradiction_blocks_promotion_without_narrowing(
    start: int, expected_dx: int, wrong_dx: int
) -> None:
    if expected_dx == wrong_dx:
        return
    model = make_model_candidate(
        hypothesis_ids=("H",),
        rules=(MovementRule("R", ActionName.ACTION1, wrong_dx, 0, entity_id="piece"),),
    )
    preserved = PreservedTransition(
        "T",
        state(start),
        ActionRequest(ActionName.ACTION1),
        state(start + expected_dx),
        ("E-before", "E-after"),
    )

    artifact = retrodict(model, (preserved,))

    assert artifact.status is PromotionStatus.REJECTED
    assert artifact.contradiction_transition_ids == ("T",)
    assert artifact.explicitly_excluded_transition_ids == ()


@settings(max_examples=35, deadline=None)
@given(start=st.integers(min_value=10, max_value=50), dx=st.sampled_from((-2, -1, 1, 2)))
def test_explicit_condition_may_narrow_scope_but_remains_in_artifact(start: int, dx: int) -> None:
    model = make_model_candidate(
        hypothesis_ids=("H-NARROW",),
        rules=(
            MovementRule(
                "R-NARROW",
                ActionName.ACTION1,
                dx,
                0,
                entity_id="piece",
                conditions=(RuleCondition(ConditionKind.FACT_PRESENT, "mode"),),
            ),
        ),
    )
    compatible = PreservedTransition(
        "T-IN",
        state(start, mode=True),
        ActionRequest(ActionName.ACTION1),
        state(start + dx, mode=True),
        ("E-1", "E-2"),
    )
    excluded = PreservedTransition(
        "T-OUT",
        state(start),
        ActionRequest(ActionName.ACTION1),
        state(start - dx),
        ("E-3", "E-4"),
    )

    artifact = retrodict(model, (compatible, excluded))

    assert artifact.status is PromotionStatus.PROMOTED
    assert artifact.tested_transition_ids == ("T-IN",)
    assert artifact.explicitly_excluded_transition_ids == ("T-OUT",)
    assert set(artifact.compatible_transition_ids) == {"T-IN", "T-OUT"}


@settings(max_examples=35, deadline=None)
@given(
    start=st.integers(min_value=10, max_value=40),
    dx=st.sampled_from((-2, -1, 1, 2)),
    horizon=st.integers(min_value=0, max_value=5),
)
def test_simulator_is_deterministic_under_state_and_model_identity(
    start: int, dx: int, horizon: int
) -> None:
    model = make_model_candidate(
        hypothesis_ids=("H-DETERMINISTIC",),
        rules=(MovementRule("R", ActionName.ACTION1, dx, 0, entity_id="piece"),),
    )
    ensemble = WorldModelEnsemble((model,))
    actions = (ActionRequest(ActionName.ACTION1),) * horizon

    first = simulate_sequence(ensemble, state(start), actions)
    second = simulate_sequence(ensemble, state(start), actions)

    assert first == second
