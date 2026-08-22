from __future__ import annotations

from dataclasses import replace

import pytest

from arc3.errors import WorldModelError
from arc3.types import ActionName, ActionRequest
from arc3.world_model import (
    Cell,
    MatchedPredictionEvidence,
    MovementRule,
    PreservedTransition,
    RetrodictionConfig,
    RetrodictionMode,
    RetrodictionOmission,
    RetrodictionReason,
    RetrodictionRequest,
    RetrodictionRuntime,
    SymbolicEntity,
    SymbolicState,
    make_model_candidate,
    retrodict,
    transition_witness,
)


def _state(x: int) -> SymbolicState:
    return SymbolicState(96, 3, (SymbolicEntity("piece", "mover", (Cell(x, 1),)),))


def _transition(index: int, *, after_dx: int = 1) -> PreservedTransition:
    before_x = index + 10
    return PreservedTransition(
        transition_id=f"T-{index:03d}",
        before=_state(before_x),
        action=ActionRequest(ActionName.ACTION1),
        after=_state(before_x + after_dx),
        source_event_ids=(f"E-{index:03d}-before", f"E-{index:03d}-after"),
    )


def _model(*, rank_weight: int = 0):
    return make_model_candidate(
        hypothesis_ids=("H-RIGHT",),
        rules=(MovementRule("R-RIGHT", ActionName.ACTION1, 1, 0, entity_id="piece"),),
        rank_weight=rank_weight,
    )


def _request(
    history: tuple[PreservedTransition, ...],
    *,
    model=None,
    omissions: tuple[RetrodictionOmission, ...] = (),
    resolved_noise: tuple[str, ...] = (),
    force: tuple[str, ...] = (),
    evidence: tuple[MatchedPredictionEvidence, ...] = (),
    epoch: str = "mechanics-epoch:0",
) -> RetrodictionRequest:
    return RetrodictionRequest(
        model=_model() if model is None else model,
        transitions=history,
        mechanics_epoch_id=epoch,
        omissions=omissions,
        resolved_noise_transition_ids=resolved_noise,
        force_full_source_event_ids=force,
        matched_evidence=evidence,
    )


def _evaluate_and_commit(
    runtime: RetrodictionRuntime,
    request: RetrodictionRequest,
    *,
    receipt: str,
):
    plan = runtime.plan(request)
    evaluation = runtime.execute(plan)
    runtime.commit(evaluation, source_receipt_event_id=receipt)
    return evaluation


def _matched(transition: PreservedTransition, model_id: str) -> MatchedPredictionEvidence:
    return MatchedPredictionEvidence(
        transition_id=transition.transition_id,
        model_id=model_id,
        prediction_event_id=f"prediction-event:{transition.transition_id}",
        prediction_receipt_id=f"prediction-receipt:{transition.transition_id}",
        consequence_event_id=f"consequence-event:{transition.transition_id}",
        assessment_receipt_id=f"assessment:{transition.transition_id}",
        matched=True,
        match_scope="whole-symbolic-state",
    )


def test_config_and_empty_runtime_round_trip_exactly() -> None:
    config = RetrodictionConfig(
        RetrodictionMode.CACHED_INCREMENTAL,
        window=8,
        capacity=64,
    )
    runtime = RetrodictionRuntime(config)

    restored = RetrodictionRuntime.from_dict(runtime.to_dict(), expected_config=config)

    assert restored.state == runtime.state
    assert restored.to_dict() == runtime.to_dict()
    with pytest.raises(WorldModelError, match="does not match"):
        RetrodictionRuntime.from_dict(
            runtime.to_dict(),
            expected_config=RetrodictionConfig(RetrodictionMode.FULL),
        )
    tampered = runtime.to_dict()
    tampered["configuration_hash"] = "sha256:tampered"
    with pytest.raises(WorldModelError, match="configuration hash"):
        RetrodictionRuntime.from_dict(tampered, expected_config=config)


def test_capacity_is_bound_into_configuration_hash_and_cache_namespace() -> None:
    request = _request((_transition(0),))
    config_64 = RetrodictionConfig(RetrodictionMode.CACHED_INCREMENTAL, capacity=64)
    config_65 = RetrodictionConfig(RetrodictionMode.CACHED_INCREMENTAL, capacity=65)
    runtime_64 = RetrodictionRuntime(config_64)
    runtime_65 = RetrodictionRuntime(config_65)

    plan_64 = runtime_64.plan(request)
    plan_65 = runtime_65.plan(request)

    assert config_64.configuration_hash != config_65.configuration_hash
    assert plan_64.configuration_hash == config_64.configuration_hash
    assert plan_65.configuration_hash == config_65.configuration_hash
    assert plan_64.namespace_key != plan_65.namespace_key
    assert plan_64.cache_key != plan_65.cache_key
    assert runtime_64.execute(plan_64).artifact == runtime_65.execute(plan_65).artifact


def test_full_and_none_preserve_exact_legacy_artifacts() -> None:
    model = _model(rank_weight=7)
    history = (_transition(0), _transition(1, after_dx=-1))

    full = RetrodictionRuntime(RetrodictionConfig(RetrodictionMode.FULL))
    full_evaluation = full.execute(full.plan(_request(history, model=model)))
    none = RetrodictionRuntime(RetrodictionConfig(RetrodictionMode.NONE))
    none_evaluation = none.execute(none.plan(_request(history, model=model)))

    assert full_evaluation.artifact == retrodict(model, history)
    assert none_evaluation.artifact == retrodict(model, history, enabled=False)
    assert full_evaluation.plan.reason is RetrodictionReason.FULL
    assert none_evaluation.plan.selected_transitions == ()
    assert none_evaluation.plan.complete_scope is False


def test_recent_window_selects_exact_last_eight_and_names_every_omission() -> None:
    history = tuple(_transition(index) for index in range(12))
    inherited = RetrodictionOmission("T-UNCLAIMED", "unclaimed-action")
    runtime = RetrodictionRuntime(RetrodictionConfig(RetrodictionMode.RECENT_WINDOW_8))

    evaluation = runtime.execute(runtime.plan(_request(history, omissions=(inherited,))))

    assert evaluation.artifact == retrodict(_model(), history[-8:])
    assert evaluation.plan.selected_transitions == history[-8:]
    assert evaluation.plan.complete_scope is False
    assert evaluation.plan.omitted[0] == inherited
    assert [item.transition_id for item in evaluation.plan.omitted[1:]] == [
        item.transition_id for item in history[:4]
    ]
    assert {item.reason for item in evaluation.plan.omitted[1:]} == {"recent-window-8"}


def test_cached_incremental_suffix_and_exact_hit_rematerialize_full_artifact() -> None:
    runtime = RetrodictionRuntime(RetrodictionConfig(RetrodictionMode.CACHED_INCREMENTAL))
    prefix = tuple(_transition(index) for index in range(4))
    history = (*prefix, _transition(4), _transition(5))
    first = _evaluate_and_commit(runtime, _request(prefix), receipt="E-COMPLETE-1")

    extended_plan = runtime.plan(_request(history))
    extended = runtime.execute(extended_plan)
    runtime.commit(extended, source_receipt_event_id="E-COMPLETE-2")
    exact_plan = runtime.plan(_request(history))
    exact = runtime.execute(exact_plan)

    assert first.artifact == retrodict(_model(), prefix)
    assert extended.artifact == retrodict(_model(), history)
    assert extended_plan.cache_hit
    assert extended_plan.prefix_count == 4
    assert extended_plan.suffix_count == 2
    assert extended.reused
    assert exact.artifact == extended.artifact
    assert exact_plan.reason is RetrodictionReason.EXACT_CACHE_HIT
    assert exact_plan.suffix_count == 0
    assert exact.reused


def test_prefix_hit_requires_byte_equal_canonical_witnesses() -> None:
    runtime = RetrodictionRuntime(RetrodictionConfig(RetrodictionMode.CACHED_INCREMENTAL))
    original = (_transition(0), _transition(1))
    _evaluate_and_commit(runtime, _request(original), receipt="E-COMPLETE")
    changed_source = replace(
        original[0],
        source_event_ids=("E-DIFFERENT-before", "E-DIFFERENT-after"),
    )
    changed = (changed_source, original[1], _transition(2))

    plan = runtime.plan(_request(changed))

    assert transition_witness(changed_source) != transition_witness(original[0])
    assert plan.cache_hit is False
    assert plan.full_audit
    assert plan.reason is RetrodictionReason.NON_PREFIX


def test_force_epoch_exclusion_and_model_semantics_fail_closed_to_full() -> None:
    runtime = RetrodictionRuntime(RetrodictionConfig(RetrodictionMode.CACHED_INCREMENTAL))
    prefix = (_transition(0), _transition(1))
    _evaluate_and_commit(runtime, _request(prefix), receipt="E-COMPLETE")
    history = (*prefix, _transition(2))

    forced = runtime.plan(_request(history, force=("E-MISMATCH",)))
    epoch = runtime.plan(_request(history, epoch="mechanics-epoch:1"))
    excluded = runtime.plan(
        _request(
            history,
            omissions=(RetrodictionOmission("T-NOISE", "resolved-noise"),),
        )
    )
    ranked = runtime.plan(_request(history, model=_model(rank_weight=99)))

    assert forced.reason is RetrodictionReason.INVALIDATED
    assert all(plan.full_audit and not plan.cache_hit for plan in (forced, epoch, excluded, ranked))


def test_event_triggered_reuses_only_complete_matched_source_ordered_evidence() -> None:
    runtime = RetrodictionRuntime(RetrodictionConfig(RetrodictionMode.EVENT_TRIGGERED))
    prefix = tuple(_transition(index) for index in range(3))
    _evaluate_and_commit(runtime, _request(prefix), receipt="E-COMPLETE-1")
    suffix = _transition(3)
    history = (*prefix, suffix)
    model = _model()

    accepted_plan = runtime.plan(
        _request(history, model=model, evidence=(_matched(suffix, model.model_id),))
    )
    accepted = runtime.execute(accepted_plan)
    missing = runtime.plan(_request(history, model=model))
    malformed = replace(_matched(suffix, model.model_id), source_ordered=False)
    rejected = runtime.plan(_request(history, model=model, evidence=(malformed,)))

    assert accepted_plan.reason is RetrodictionReason.EVENT_RECEIPT_REUSE
    assert accepted.reused
    assert accepted.artifact == retrodict(model, history)
    assert accepted_plan.to_trace_payload()["authorizing_matched_prediction_evidence"] == [
        _matched(suffix, model.model_id).to_dict()
    ]
    assert missing.reason is RetrodictionReason.EVENT_FULL_AUDIT
    assert missing.full_audit and not missing.cache_hit
    assert missing.to_trace_payload()["authorizing_matched_prediction_evidence"] == []
    assert rejected.reason is RetrodictionReason.EVENT_FULL_AUDIT
    assert rejected.to_trace_payload()["authorizing_matched_prediction_evidence"] == []


def test_event_triggered_payload_orders_only_authorizing_suffix_evidence() -> None:
    runtime = RetrodictionRuntime(RetrodictionConfig(RetrodictionMode.EVENT_TRIGGERED))
    prefix = (_transition(0), _transition(1))
    _evaluate_and_commit(runtime, _request(prefix), receipt="E-COMPLETE-1")
    suffix = (_transition(2), _transition(3))
    history = (*prefix, *suffix)
    model = _model()
    ordered = tuple(_matched(item, model.model_id) for item in suffix)
    unrelated_prefix_evidence = _matched(prefix[0], model.model_id)
    request = _request(
        history,
        model=model,
        evidence=(ordered[1], unrelated_prefix_evidence, ordered[0]),
    )

    plan = runtime.plan(request)

    assert plan.reason is RetrodictionReason.EVENT_RECEIPT_REUSE
    assert plan.authorizing_matched_prediction_evidence == ordered
    assert plan.to_trace_payload()["authorizing_matched_prediction_evidence"] == [
        item.to_dict() for item in ordered
    ]
    with pytest.raises(WorldModelError, match="ordered and bound"):
        replace(plan, authorizing_matched_prediction_evidence=tuple(reversed(ordered)))

    evaluation = runtime.execute(plan)
    runtime.commit(evaluation, source_receipt_event_id="E-COMPLETE-2")
    exact_plan = runtime.plan(request)
    assert exact_plan.reason is RetrodictionReason.EXACT_CACHE_HIT
    assert exact_plan.to_trace_payload()["authorizing_matched_prediction_evidence"] == []


def test_non_event_reuse_payload_omits_supplied_matched_evidence() -> None:
    transition = _transition(0)
    model = _model()
    request = _request(
        (transition,),
        model=model,
        evidence=(_matched(transition, model.model_id),),
    )

    full_plan = RetrodictionRuntime(RetrodictionConfig(RetrodictionMode.FULL)).plan(request)
    first_use_plan = RetrodictionRuntime(RetrodictionConfig(RetrodictionMode.EVENT_TRIGGERED)).plan(
        request
    )

    assert full_plan.reason is RetrodictionReason.FULL
    assert first_use_plan.reason is RetrodictionReason.FIRST_USE
    for plan in (full_plan, first_use_plan):
        assert plan.authorizing_matched_prediction_evidence == ()
        assert plan.to_trace_payload()["authorizing_matched_prediction_evidence"] == []
        with pytest.raises(WorldModelError, match="only event-receipt reuse"):
            replace(
                plan,
                authorizing_matched_prediction_evidence=request.matched_evidence,
            )


def test_lru_eviction_is_access_ordinal_then_cache_key_deterministic() -> None:
    runtime = RetrodictionRuntime(
        RetrodictionConfig(RetrodictionMode.CACHED_INCREMENTAL, capacity=2)
    )
    h1 = (_transition(0),)
    h2 = (*h1, _transition(1))
    h3 = (*h2, _transition(2))
    _evaluate_and_commit(runtime, _request(h1), receipt="E-1")
    second = _evaluate_and_commit(runtime, _request(h2), receipt="E-2")
    _evaluate_and_commit(runtime, _request(h1), receipt="E-3")

    third_plan = runtime.plan(_request(h3))
    third = runtime.execute(third_plan)
    runtime.commit(third, source_receipt_event_id="E-4")

    assert third.evicted_cache_keys == (second.plan.cache_key,)
    assert {item.cache_key for item in runtime.state.cache_entries} == {
        third.plan.cache_key,
        runtime.plan(_request(h1)).cache_key,
    }
    assert len(runtime.state.cache_entries) == 2


def test_runtime_state_rejects_rehashed_internal_cache_tamper() -> None:
    config = RetrodictionConfig(RetrodictionMode.CACHED_INCREMENTAL)
    runtime = RetrodictionRuntime(config)
    _evaluate_and_commit(runtime, _request((_transition(0),)), receipt="E-COMPLETE")
    raw = runtime.to_dict()
    entries = raw["cache_entries"]
    assert isinstance(entries, list) and isinstance(entries[0], dict)
    entries[0]["history_key"] = "sha256:" + "0" * 64

    with pytest.raises(WorldModelError, match="history key"):
        RetrodictionRuntime.from_dict(raw, expected_config=config)


def test_cache_checkpoint_exposes_and_revalidates_typed_semantic_identities() -> None:
    config = RetrodictionConfig(RetrodictionMode.CACHED_INCREMENTAL)
    runtime = RetrodictionRuntime(config)
    request = _request(
        (_transition(0),),
        omissions=(RetrodictionOmission("T-OMITTED", "unclaimed-action"),),
        resolved_noise=("T-NOISE-2", "T-NOISE-1"),
        epoch="mechanics-epoch:typed",
    )
    evaluation = _evaluate_and_commit(runtime, request, receipt="E-COMPLETE-TYPED")
    raw = runtime.to_dict()
    entries = raw["cache_entries"]
    assert isinstance(entries, list) and isinstance(entries[0], dict)
    entry_raw = entries[0]

    assert raw["configuration_hash"] == config.configuration_hash
    assert entry_raw["configuration_hash"] == config.configuration_hash
    assert entry_raw["model_id"] == request.model.model_id
    assert entry_raw["mechanics_epoch_id"] == request.mechanics_epoch_id
    assert entry_raw["projection_version"] == config.projection_version
    assert entry_raw["resolved_noise_transition_ids"] == ["T-NOISE-2", "T-NOISE-1"]
    assert entry_raw["omissions"] == [{"reason": "unclaimed-action", "transition_id": "T-OMITTED"}]

    entry = runtime.state.cache_entries[0]
    entry.validate_against(
        config=config,
        request=request,
        materialized_artifact_id=evaluation.artifact.artifact_id,
        source_receipt_event_id="E-COMPLETE-TYPED",
    )
    assert RetrodictionRuntime.from_dict(raw, expected_config=config).to_dict() == raw


@pytest.mark.parametrize(
    ("field", "replacement", "message"),
    (
        ("configuration_hash", "sha256:tampered", "configuration hash"),
        ("mechanics_epoch_id", "mechanics-epoch:tampered", "namespace"),
        ("projection_version", "projection:tampered", "projection version"),
        ("model_id", "M-TAMPERED", "namespace"),
        ("model_semantic_fingerprint", "sha256:tampered", "namespace"),
    ),
)
def test_runtime_state_rejects_typed_cache_identity_tamper(
    field: str,
    replacement: str,
    message: str,
) -> None:
    config = RetrodictionConfig(RetrodictionMode.CACHED_INCREMENTAL)
    runtime = RetrodictionRuntime(config)
    _evaluate_and_commit(runtime, _request((_transition(0),)), receipt="E-COMPLETE")
    raw = runtime.to_dict()
    entries = raw["cache_entries"]
    assert isinstance(entries, list) and isinstance(entries[0], dict)
    entries[0][field] = replacement

    with pytest.raises(WorldModelError, match=message):
        RetrodictionRuntime.from_dict(raw, expected_config=config)


def test_runtime_state_rejects_typed_exclusion_identity_tamper() -> None:
    config = RetrodictionConfig(RetrodictionMode.CACHED_INCREMENTAL)
    runtime = RetrodictionRuntime(config)
    request = _request(
        (_transition(0),),
        omissions=(RetrodictionOmission("T-OMITTED", "unclaimed-action"),),
        resolved_noise=("T-NOISE",),
    )
    _evaluate_and_commit(runtime, request, receipt="E-COMPLETE")
    raw = runtime.to_dict()
    entries = raw["cache_entries"]
    assert isinstance(entries, list) and isinstance(entries[0], dict)
    omissions = entries[0]["omissions"]
    assert isinstance(omissions, list) and isinstance(omissions[0], dict)
    omissions[0]["reason"] = "tampered-reason"

    with pytest.raises(WorldModelError, match="exclusion identity"):
        RetrodictionRuntime.from_dict(raw, expected_config=config)


def test_entry_restore_validator_binds_model_and_completion_receipt() -> None:
    config = RetrodictionConfig(RetrodictionMode.CACHED_INCREMENTAL)
    runtime = RetrodictionRuntime(config)
    request = _request((_transition(0),))
    evaluation = _evaluate_and_commit(runtime, request, receipt="E-COMPLETE")
    entry = runtime.state.cache_entries[0]

    with pytest.raises(WorldModelError, match="model ID"):
        entry.validate_against(
            config=config,
            request=replace(request, model=replace(request.model, model_id="M-TAMPERED")),
            materialized_artifact_id=evaluation.artifact.artifact_id,
            source_receipt_event_id="E-COMPLETE",
        )
    with pytest.raises(WorldModelError, match="source receipt"):
        entry.validate_against(
            config=config,
            request=request,
            materialized_artifact_id=evaluation.artifact.artifact_id,
            source_receipt_event_id="E-WRONG-COMPLETION",
        )


def test_entry_restore_validator_rejects_residual_content_tamper() -> None:
    config = RetrodictionConfig(RetrodictionMode.CACHED_INCREMENTAL)
    runtime = RetrodictionRuntime(config)
    request = _request((_transition(0, after_dx=-1),))
    evaluation = _evaluate_and_commit(runtime, request, receipt="E-COMPLETE")
    raw = runtime.to_dict()
    entries = raw["cache_entries"]
    assert isinstance(entries, list) and isinstance(entries[0], dict)
    outcomes = entries[0]["outcomes"]
    assert isinstance(outcomes, list) and isinstance(outcomes[0], dict)
    residual = outcomes[0]["residual"]
    assert isinstance(residual, dict)
    residual["changed_entities"] = ["forged-entity"]

    restored = RetrodictionRuntime.from_dict(raw, expected_config=config)
    entry = restored.state.cache_entries[0]
    assert entry.materialized_artifact_id == evaluation.artifact.artifact_id
    with pytest.raises(WorldModelError, match="outcomes disagree"):
        entry.validate_against(
            config=config,
            request=request,
            materialized_artifact_id=evaluation.artifact.artifact_id,
            source_receipt_event_id="E-COMPLETE",
        )
