from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from arc3.policy.cadence import (
    DEEP_TRIGGER_PRIORITY,
    BoundedCanonicalLRU,
    CadenceConfig,
    CadenceSignals,
    CadenceState,
    CanonicalCacheKey,
    DeepTrigger,
    DerivedCacheValue,
    ModelCacheIdentity,
    select_reasoning_path,
)
from arc3.types import ActionName, ActionRequest
from arc3.world_model.model import AlternativeOutcome, EnsemblePrediction
from arc3.world_model.state import SymbolicState


def _key(ordinal: int) -> CanonicalCacheKey:
    return CanonicalCacheKey(
        source_identity="source:property",
        configuration_identity="config:property",
        symbolic_state_id=f"state:{ordinal}",
        action=ActionRequest(ActionName.ACTION1),
        ordered_models=(ModelCacheIdentity("model:property", ordinal % 5),),
        mechanics_epoch_id="epoch:property",
        action_registry_identity="registry:property",
    )


def _value(ordinal: int) -> DerivedCacheValue:
    after_state = SymbolicState(
        width=2,
        height=2,
        facts=(f"predicted:{ordinal + 1}",),
    )
    return DerivedCacheValue(
        prediction=EnsemblePrediction(
            before_state_id=f"state:{ordinal}",
            action=ActionRequest(ActionName.ACTION1),
            alternatives=(
                AlternativeOutcome(
                    alternative_rank=1,
                    after_state=after_state,
                    supporting_model_ids=("model:property",),
                    prediction_ids=(f"prediction:{ordinal}",),
                    rank_weight=ordinal % 5,
                ),
            ),
        ),
    )


@settings(max_examples=40, deadline=None)
@given(
    active=st.sets(st.sampled_from(tuple(DeepTrigger))),
)
def test_trigger_selection_is_deterministic_and_priority_ordered(
    active: set[DeepTrigger],
) -> None:
    config = CadenceConfig(maximum_fast_streak=2, repeated_no_progress_threshold=2)
    state = CadenceState(
        configuration_hash=config.configuration_hash,
        fast_streak=(2 if DeepTrigger.MAX_FAST_STREAK in active else 0),
        no_progress_streak=(2 if DeepTrigger.REPEATED_NO_PROGRESS in active else 0),
    )
    has_plan = DeepTrigger.NO_VALID_PLAN not in active
    signals = CadenceSignals(
        observation_event_id="E-OBS",
        state_id="state:property",
        mechanics_epoch_id="epoch:property",
        goal_id="goal:property",
        goal_revision=0,
        plan_id="plan:property" if has_plan else None,
        has_valid_plan=has_plan,
        startup_unknown_action_event_ids=(
            ("E-START",) if DeepTrigger.STARTUP_UNKNOWN_ACTION in active else ()
        ),
        reopening_event_ids=(("E-REOPEN",) if DeepTrigger.REOPENING in active else ()),
        meaningful_contradiction_event_ids=(
            ("E-CONTRADICTION",) if DeepTrigger.MEANINGFUL_CONTRADICTION in active else ()
        ),
        structural_novelty_event_ids=(
            ("E-NOVEL",) if DeepTrigger.STRUCTURAL_NOVELTY in active else ()
        ),
        high_goal_uncertainty_event_ids=(
            ("E-GOAL",) if DeepTrigger.HIGH_GOAL_UNCERTAINTY in active else ()
        ),
    )

    first = select_reasoning_path(config, state, signals)
    second = select_reasoning_path(config, state, signals)
    expected = tuple(trigger for trigger in DEEP_TRIGGER_PRIORITY if trigger in active)

    assert first == second
    assert first.ordered_triggers == expected
    assert first.to_dict() == second.to_dict()


@settings(max_examples=40, deadline=None)
@given(
    capacity=st.integers(min_value=1, max_value=12),
    operations=st.lists(
        st.tuples(
            st.sampled_from(("put", "get")),
            st.integers(min_value=0, max_value=24),
        ),
        min_size=1,
        max_size=80,
    ),
)
def test_lru_is_bounded_deterministic_and_checkpoint_roundtrippable(
    capacity: int,
    operations: list[tuple[str, int]],
) -> None:
    def run() -> BoundedCanonicalLRU:
        cache = BoundedCanonicalLRU(capacity=capacity)
        for operation, ordinal in operations:
            if operation == "put":
                cache.put(_key(ordinal), _value(ordinal))
            else:
                cache.get(_key(ordinal))
            assert len(cache) <= capacity
        return cache

    first = run()
    second = run()
    restored = BoundedCanonicalLRU.from_dict(
        first.to_dict(),
        expected_capacity=capacity,
    )

    assert first.to_dict() == second.to_dict()
    assert restored.to_dict() == first.to_dict()
