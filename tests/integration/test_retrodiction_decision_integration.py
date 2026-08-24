"""Synthetic integration checks for the frozen Stage 07 retrodiction modes."""

from __future__ import annotations

from pathlib import Path

import pytest
from scripts.measure_retrodiction_decision import _run_stage06_cell, _run_stage14_cell

from arc3.evaluation.retrodiction_decision import (
    EvaluationGroup,
    build_evaluation_matrix,
    build_false_rule_cases,
)
from arc3.world_model.retrodiction import (
    MatchedPredictionEvidence,
    PromotionStatus,
    RetrodictionConfig,
    RetrodictionEvaluation,
    RetrodictionMode,
    RetrodictionPlan,
    RetrodictionReason,
    RetrodictionRequest,
    RetrodictionRuntime,
)


def _request(
    *,
    case_index: int,
    truth: bool,
    matched_evidence: tuple[MatchedPredictionEvidence, ...] = (),
) -> RetrodictionRequest:
    case = build_false_rule_cases()[case_index]
    return RetrodictionRequest(
        model=case.true_model if truth else case.false_model,
        transitions=case.transitions,
        mechanics_epoch_id=f"mechanics-epoch:stage07:{case.code}",
        matched_evidence=matched_evidence,
    )


def _execute(
    runtime: RetrodictionRuntime,
    request: RetrodictionRequest,
    *,
    receipt_id: str,
) -> tuple[RetrodictionPlan, RetrodictionEvaluation]:
    plan = runtime.plan(request)
    evaluation = runtime.execute(plan)
    runtime.commit(evaluation, source_receipt_event_id=receipt_id)
    return plan, evaluation


@pytest.mark.parametrize("case_index", range(8))
@pytest.mark.parametrize("mode", tuple(RetrodictionMode))
def test_all_modes_face_all_eight_old_contradictions(
    case_index: int, mode: RetrodictionMode
) -> None:
    runtime_true = RetrodictionRuntime(RetrodictionConfig(mode))
    true_plan, true_evaluation = _execute(
        runtime_true,
        _request(case_index=case_index, truth=True),
        receipt_id=f"receipt:true:{mode.value}:{case_index}",
    )
    runtime_false = RetrodictionRuntime(RetrodictionConfig(mode))
    false_plan, false_evaluation = _execute(
        runtime_false,
        _request(case_index=case_index, truth=False),
        receipt_id=f"receipt:false:{mode.value}:{case_index}",
    )

    if mode is RetrodictionMode.NONE:
        assert true_evaluation.artifact.status is PromotionStatus.UNGATED_ABLATION
        assert false_evaluation.artifact.status is PromotionStatus.UNGATED_ABLATION
        assert true_plan.selected_transitions == false_plan.selected_transitions == ()
    elif mode is RetrodictionMode.RECENT_WINDOW_8:
        assert true_evaluation.artifact.status is PromotionStatus.PROMOTED
        assert false_evaluation.artifact.status is PromotionStatus.PROMOTED
        assert false_plan.reason is RetrodictionReason.RECENT_WINDOW
        assert tuple(item.transition_id for item in false_plan.selected_transitions) == tuple(
            item.transition_id
            for item in _request(case_index=case_index, truth=False).transitions[-8:]
        )
        assert false_plan.omitted[0].transition_id.endswith("t00")
    else:
        assert true_evaluation.artifact.status is PromotionStatus.PROMOTED
        assert false_evaluation.artifact.status is PromotionStatus.REJECTED
        assert false_evaluation.artifact.contradiction_transition_ids == (
            _request(case_index=case_index, truth=False).transitions[0].transition_id,
        )


def test_cached_incremental_prefix_extension_rematerializes_exact_full_artifact() -> None:
    request = _request(case_index=0, truth=True)
    runtime = RetrodictionRuntime(RetrodictionConfig(RetrodictionMode.CACHED_INCREMENTAL))
    prefix = RetrodictionRequest(
        model=request.model,
        transitions=request.transitions[:-1],
        mechanics_epoch_id=request.mechanics_epoch_id,
    )
    _execute(runtime, prefix, receipt_id="receipt:cached:prefix")

    plan, incremental = _execute(runtime, request, receipt_id="receipt:cached:full")
    full_runtime = RetrodictionRuntime(RetrodictionConfig(RetrodictionMode.FULL))
    _full_plan, full = _execute(full_runtime, request, receipt_id="receipt:full")

    assert plan.reason is RetrodictionReason.PREFIX_EXTENSION
    assert plan.cache_hit is True
    assert plan.prefix_count == 11
    assert plan.suffix_count == 1
    assert incremental.reused is True
    assert incremental.artifact == full.artifact


def test_event_triggered_reuse_requires_exact_matched_suffix_receipt() -> None:
    request = _request(case_index=0, truth=True)
    prefix = RetrodictionRequest(
        model=request.model,
        transitions=request.transitions[:-1],
        mechanics_epoch_id=request.mechanics_epoch_id,
    )
    suffix = request.transitions[-1]
    evidence = MatchedPredictionEvidence(
        transition_id=suffix.transition_id,
        model_id=request.model.model_id,
        prediction_event_id="event:prediction:t11",
        prediction_receipt_id="receipt:prediction:t11",
        consequence_event_id="event:consequence:t11",
        assessment_receipt_id="receipt:assessment:t11",
        matched=True,
        match_scope="whole-symbolic-state",
    )
    runtime = RetrodictionRuntime(RetrodictionConfig(RetrodictionMode.EVENT_TRIGGERED))
    _execute(runtime, prefix, receipt_id="receipt:event:prefix")
    with_evidence = RetrodictionRequest(
        model=request.model,
        transitions=request.transitions,
        mechanics_epoch_id=request.mechanics_epoch_id,
        matched_evidence=(evidence,),
    )

    reuse_plan, reuse = _execute(runtime, with_evidence, receipt_id="receipt:event:extension")
    assert reuse_plan.reason is RetrodictionReason.EVENT_RECEIPT_REUSE
    assert reuse_plan.prefix_count == 11
    assert reuse_plan.suffix_count == 1
    assert reuse.reused is True
    assert reuse_plan.authorizing_matched_prediction_evidence == (evidence,)
    assert reuse_plan.to_trace_payload()["authorizing_matched_prediction_evidence"] == [
        evidence.to_dict()
    ]

    forced = RetrodictionRuntime(RetrodictionConfig(RetrodictionMode.EVENT_TRIGGERED))
    _execute(forced, prefix, receipt_id="receipt:event:prefix:missing")
    forced_plan = forced.plan(request)
    assert forced_plan.reason is RetrodictionReason.EVENT_FULL_AUDIT
    assert forced_plan.cache_hit is False
    assert forced_plan.full_audit is True
    assert forced_plan.authorizing_matched_prediction_evidence == ()


@pytest.mark.parametrize("mode", tuple(RetrodictionMode))
def test_stage07_stage14_adapter_preserves_checkpoint_and_replay(
    tmp_path: Path,
    mode: RetrodictionMode,
) -> None:
    cell = next(
        item
        for item in build_evaluation_matrix()
        if item.group is EvaluationGroup.A_STAGE14 and item.mode is mode
    )

    measurement, raw = _run_stage14_cell(
        cell,
        cell_root=tmp_path / "stage14",
        git_commit="stage07-integration-test",
    )

    assert measurement.trace_valid is True
    assert measurement.replay_valid is True
    assert measurement.checkpoint_valid is True
    assert measurement.event_reuse_receipts_valid is True
    retrodiction_phase = raw["hot_path_profile"]["phases"]["retrodiction"]
    assert measurement.cache_hit_count == retrodiction_phase["cache_hits"]
    assert raw["trace_tail_hash"] is not None


def test_stage07_stage06_adapter_uses_blinded_frozen_fixture(tmp_path: Path) -> None:
    cell = next(
        item
        for item in build_evaluation_matrix()
        if item.group is EvaluationGroup.C_RULE_CHANGE
        and item.group_case_ordinal == 0
        and item.mode is RetrodictionMode.FULL
    )

    measurement, raw = _run_stage06_cell(
        cell,
        cell_root=tmp_path / "stage06",
        git_commit="stage07-integration-test",
    )

    assert measurement.intervention_triggered is True
    assert measurement.checkpoint_valid is True
    assert measurement.trace_valid is True
    assert measurement.replay_valid is True
    stage06 = raw["stage06_result"]
    assert stage06["trace"]["prefix_immutability"]["passed"] is True
    assert "stage06_result" in raw
