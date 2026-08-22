from __future__ import annotations

from copy import deepcopy
from dataclasses import replace

import pytest

import arc3.policy.cadence as cadence_module
from arc3.errors import PolicyError
from arc3.policy.cadence import (
    DEEP_TRIGGER_PRIORITY,
    BoundedCanonicalLRU,
    CacheInvalidationReason,
    CacheValueKind,
    CadenceConfig,
    CadenceSelection,
    CadenceSignals,
    CadenceState,
    CanonicalCacheKey,
    DeepTrigger,
    DeliberationMode,
    DeliberationStatus,
    DerivedCacheValue,
    ModelCacheIdentity,
    ReasoningPath,
    select_reasoning_path,
)
from arc3.types import ActionName, ActionRequest, Coordinate
from arc3.world_model.model import AlternativeOutcome, EnsemblePrediction
from arc3.world_model.state import SymbolicState


def _signals(*, has_valid_plan: bool = True, observation: str = "E-OBS") -> CadenceSignals:
    return CadenceSignals(
        observation_event_id=observation,
        state_id="state:one",
        mechanics_epoch_id="epoch:one",
        goal_id="goal:one",
        goal_revision=3,
        plan_id="plan:one" if has_valid_plan else None,
        has_valid_plan=has_valid_plan,
    )


def _key(ordinal: int, *, coordinate: Coordinate | None = None) -> CanonicalCacheKey:
    action = (
        ActionRequest(ActionName.ACTION1)
        if coordinate is None
        else ActionRequest(ActionName.ACTION6, coordinate)
    )
    return CanonicalCacheKey(
        source_identity="source:fixture",
        configuration_identity="config:fixture",
        symbolic_state_id=f"state:{ordinal}",
        action=action,
        ordered_models=(
            ModelCacheIdentity("model-semantic:a", 7),
            ModelCacheIdentity("model-semantic:b", -2),
        ),
        mechanics_epoch_id="epoch:fixture",
        action_registry_identity="registry:fixture",
    )


def _value(
    ordinal: int = 0,
    *,
    action: ActionRequest | None = None,
) -> DerivedCacheValue:
    request = action or ActionRequest(ActionName.ACTION1)
    after_state = SymbolicState(
        width=3,
        height=2,
        facts=(f"predicted:{ordinal + 1}",),
        counters=(("rank", ordinal),),
    )
    return DerivedCacheValue(
        prediction=EnsemblePrediction(
            before_state_id=f"state:{ordinal}",
            action=request,
            alternatives=(
                AlternativeOutcome(
                    alternative_rank=1,
                    after_state=after_state,
                    supporting_model_ids=("model:a",),
                    prediction_ids=(f"prediction:{ordinal}",),
                    rank_weight=ordinal,
                ),
            ),
        ),
    )


def test_all_deep_triggers_are_selected_in_frozen_priority_order() -> None:
    config = CadenceConfig()
    state = CadenceState.initial(config).fold_consequence(
        progress_made=False,
        structural_identity="structure:one",
    )
    state = state.fold_consequence(progress_made=False, structural_identity="structure:one")
    state = CadenceState(
        configuration_hash=state.configuration_hash,
        fast_streak=config.maximum_fast_streak,
        no_progress_streak=state.no_progress_streak,
        last_structural_identity=state.last_structural_identity,
    )
    signals = CadenceSignals(
        observation_event_id="E-OBS",
        state_id="state:one",
        mechanics_epoch_id="epoch:one",
        goal_id=None,
        goal_revision=0,
        plan_id=None,
        has_valid_plan=False,
        startup_unknown_action_event_ids=("E-START",),
        reopening_event_ids=("E-REOPEN",),
        meaningful_contradiction_event_ids=("E-CONTRA",),
        structural_novelty_event_ids=("E-NOVEL",),
        high_goal_uncertainty_event_ids=("E-GOAL",),
    )

    selection = select_reasoning_path(config, state, signals)

    assert selection.path is ReasoningPath.DEEP
    assert selection.ordered_triggers == DEEP_TRIGGER_PRIORITY
    assert (
        tuple(trigger for trigger, _sources in selection.trigger_sources) == DEEP_TRIGGER_PRIORITY
    )
    assert CadenceSelection.from_dict(selection.to_dict()) == selection


def test_two_speed_is_fast_only_without_a_deep_trigger() -> None:
    config = CadenceConfig()
    state = CadenceState.initial(config)

    fast = select_reasoning_path(config, state, _signals())
    no_plan = select_reasoning_path(config, state, _signals(has_valid_plan=False))

    assert fast.path is ReasoningPath.FAST
    assert fast.ordered_triggers == ()
    assert no_plan.path is ReasoningPath.DEEP
    assert no_plan.ordered_triggers == (DeepTrigger.NO_VALID_PLAN,)
    assert no_plan.trigger_source_event_ids == ("E-OBS",)


def test_legacy_control_is_deep_without_inventing_a_trigger() -> None:
    config = CadenceConfig(mode=DeliberationMode.LEGACY_ALWAYS_DEEP)
    selection = select_reasoning_path(config, CadenceState.initial(config), _signals())

    assert selection.path is ReasoningPath.DEEP
    assert selection.ordered_triggers == ()
    assert CadenceSelection.from_dict(selection.to_dict()) == selection


def test_fast_streak_and_no_progress_are_deterministic_checkpointed_triggers() -> None:
    config = CadenceConfig(maximum_fast_streak=2, repeated_no_progress_threshold=2)
    state = CadenceState.initial(config)
    for ordinal in range(2):
        selection = select_reasoning_path(
            config,
            state,
            _signals(observation=f"E-OBS-{ordinal}"),
        )
        assert selection.path is ReasoningPath.FAST
        state = state.begin(selection).complete(
            selection,
            completed_event_id=f"E-COMPLETE-{ordinal}",
            status=DeliberationStatus.COMPLETED,
        )
    cadence_due = select_reasoning_path(config, state, _signals(observation="E-CADENCE"))
    assert cadence_due.ordered_triggers == (DeepTrigger.MAX_FAST_STREAK,)

    state = state.fold_consequence(progress_made=False, structural_identity="structure:one")
    state = state.fold_consequence(progress_made=False, structural_identity="structure:one")
    both_due = select_reasoning_path(config, state, _signals(observation="E-NO-PROGRESS"))
    assert both_due.ordered_triggers == (
        DeepTrigger.REPEATED_NO_PROGRESS,
        DeepTrigger.MAX_FAST_STREAK,
    )


def test_cadence_state_roundtrips_and_rejects_mid_deliberation_checkpoint() -> None:
    config = CadenceConfig()
    state = CadenceState.initial(config).fold_consequence(
        progress_made=True,
        structural_identity="structure:one",
    )
    selection = select_reasoning_path(config, state, _signals())
    pending = state.begin(selection)

    assert CadenceState.from_dict(pending.to_dict()) == pending
    with pytest.raises(PolicyError, match="mid-deliberation"):
        pending.to_checkpoint_dict()
    with pytest.raises(PolicyError, match="mid-deliberation"):
        CadenceState.from_checkpoint_dict(pending.to_dict())

    completed = pending.complete(
        selection,
        completed_event_id="E-COMPLETE",
        status=DeliberationStatus.FALLBACK_USED,
    )
    assert CadenceState.from_checkpoint_dict(completed.to_checkpoint_dict()) == completed
    assert completed.last_completed_deliberation_event_id == "E-COMPLETE"
    assert completed.fast_streak == 1


def test_config_identity_mismatch_fails_closed() -> None:
    state = CadenceState.initial(CadenceConfig())
    changed = CadenceConfig(maximum_fast_streak=5)

    with pytest.raises(PolicyError, match="configuration disagrees"):
        select_reasoning_path(changed, state, _signals())


def test_cache_key_roundtrip_includes_coordinate_and_ordered_rank_weights() -> None:
    key = _key(7, coordinate=Coordinate(3, 61))

    assert CanonicalCacheKey.from_dict(key.to_dict()) == key
    assert key.to_dict()["action"] == {
        "coordinate": {"x": 3, "y": 61},
        "name": "ACTION6",
    }
    assert key.to_dict()["ordered_models"] == [
        {
            "rank_weight": 7,
            "semantic_identity": "model-semantic:a",
            "weight_kind": "uncalibrated_rank",
        },
        {
            "rank_weight": -2,
            "semantic_identity": "model-semantic:b",
            "weight_kind": "uncalibrated_rank",
        },
    ]
    assert key.to_dict()["value_kind"] == "PREDICTION"


def test_lru_hit_updates_order_and_eviction_is_deterministic() -> None:
    cache = BoundedCanonicalLRU(capacity=2)
    first, second, third = (_key(ordinal) for ordinal in range(3))
    cache.put(first, _value(0))
    cache.put(second, _value(1))
    assert cache.get(first) == _value(0)

    assert cache.put(third, _value(2)) == (second.key_hash,)
    assert cache.get(second) is None
    assert cache.get(first) == _value(0)
    assert len(cache) == 2
    assert cache.evictions == 1


def test_cache_roundtrip_preserves_access_order_counters_and_projection() -> None:
    cache = BoundedCanonicalLRU(capacity=3)
    for ordinal in range(3):
        cache.put(_key(ordinal), _value(ordinal))
    assert cache.get(_key(0)) == _value(0)
    assert cache.get(_key(99)) is None
    cache.invalidate(CacheInvalidationReason.GOAL_REVISION)
    cache.put(_key(4), _value(4))
    serialized = cache.to_dict()

    restored = BoundedCanonicalLRU.from_dict(serialized)

    assert restored.to_dict() == serialized
    assert restored.projection_hash == cache.projection_hash
    assert restored.invalidation_counts[CacheInvalidationReason.GOAL_REVISION] == 1


def test_prediction_cache_value_is_deep_isolated_from_reads_and_serialization() -> None:
    key = _key(1)
    value = _value(1)
    cache = BoundedCanonicalLRU(capacity=2)
    cache.put(key, value)
    projection_hash = cache.projection_hash

    serialized = cache.to_dict()
    entries = serialized["entries_lru_to_mru"]
    assert isinstance(entries, list)
    assert isinstance(entries[0], dict)
    serialized_value = entries[0]["value"]
    assert isinstance(serialized_value, dict)
    serialized_payload = serialized_value["payload"]
    assert isinstance(serialized_payload, dict)
    serialized_payload["authority"] = {"permission": True}
    alternatives = serialized_payload["alternatives"]
    assert isinstance(alternatives, list)
    assert isinstance(alternatives[0], dict)
    after_state = alternatives[0]["after_state"]
    assert isinstance(after_state, dict)
    facts = after_state["facts"]
    assert isinstance(facts, list)
    facts.append("mutated-through-checkpoint")

    detached_payload = value.payload
    detached_payload["data"] = {"id": "E-FOREIGN", "content": "environment-return"}

    assert cache.projection_hash == projection_hash
    assert cache.get(key) == value
    assert "authority" not in value.payload
    assert "data" not in value.payload


def test_prediction_cache_value_rejects_neutral_key_authority_smuggling() -> None:
    serialized = _value(1).to_dict()
    payload = serialized["payload"]
    assert isinstance(payload, dict)
    payload["data"] = {"id": "E-FOREIGN", "content": "environment-return"}

    with pytest.raises(PolicyError, match="keys disagree"):
        DerivedCacheValue.from_dict(serialized)


def test_cache_key_namespace_prevents_cross_kind_reuse() -> None:
    prediction_key = _key(1)
    plan_key = replace(prediction_key, value_kind=CacheValueKind.REUSABLE_PLAN)
    value = _value(1)
    cache = BoundedCanonicalLRU(capacity=2)
    cache.put(prediction_key, value)

    assert plan_key.key_hash != prediction_key.key_hash
    assert cache.get(plan_key) is None
    with pytest.raises(PolicyError, match="namespace disagrees"):
        cache.put(plan_key, value)


def test_cache_restore_optionally_rejects_runtime_capacity_mismatch() -> None:
    cache = BoundedCanonicalLRU(capacity=2)
    cache.put(_key(1), _value(1))
    serialized = cache.to_dict()

    assert BoundedCanonicalLRU.from_dict(serialized, expected_capacity=2).capacity == 2
    with pytest.raises(PolicyError, match="capacity disagrees"):
        BoundedCanonicalLRU.from_dict(serialized, expected_capacity=3)


def test_every_predeclared_reason_invalidates_even_an_empty_cache() -> None:
    cache = BoundedCanonicalLRU(capacity=2)
    for reason in CacheInvalidationReason:
        cache.put(_key(1), _value(1))
        assert cache.invalidate(reason) == 1
        assert cache.invalidate(reason) == 0
        assert cache.invalidation_counts[reason] == 2


def test_cache_rejects_tampered_checkpoint_hash() -> None:
    cache = BoundedCanonicalLRU(capacity=2)
    cache.put(_key(1), _value(1))
    tampered = deepcopy(cache.to_dict())
    entries = tampered["entries_lru_to_mru"]
    assert isinstance(entries, list)
    assert isinstance(entries[0], dict)
    entries[0]["key_hash"] = "sha256:" + "0" * 64

    with pytest.raises(PolicyError, match="key hash disagrees"):
        BoundedCanonicalLRU.from_dict(tampered)


def test_digest_match_never_reuses_or_overwrites_an_unequal_complete_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    collision = "sha256:" + "f" * 64
    monkeypatch.setattr(cadence_module, "_cache_key_hash", lambda _value: collision)
    cache = BoundedCanonicalLRU(capacity=2)
    first = _key(1)
    second = _key(2)
    cache.put(first, _value(1))

    assert cache.get(second) is None
    with pytest.raises(PolicyError, match="digest collision"):
        cache.put(second, _value(2))


def test_serializers_reject_unknown_fields_and_inconsistent_source_projection() -> None:
    config_payload = CadenceConfig().to_dict()
    config_payload["decision_seconds"] = 1
    with pytest.raises(PolicyError, match="keys disagree"):
        CadenceConfig.from_dict(config_payload)

    selection = select_reasoning_path(
        CadenceConfig(),
        CadenceState.initial(CadenceConfig()),
        _signals(has_valid_plan=False),
    )
    selection_payload = selection.to_dict()
    selection_payload["trigger_source_event_ids"] = ["E-INVENTED"]
    with pytest.raises(PolicyError, match="disagree"):
        CadenceSelection.from_dict(selection_payload)
