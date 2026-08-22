"""Frozen Stage 07 case-manifest, matrix, and decision-gate checks."""

from __future__ import annotations

import socket
import subprocess
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import cast
from unittest.mock import patch

import pytest
from scripts.measure_retrodiction_decision import (
    _event_receipt_integrity,
    _holdout_integrity,
    _require_fresh_targets,
    _run_verification_command,
    _SocketDeny,
    _source_stability,
    build_micro_history,
    measure_microbenchmark_cell,
)

from arc3.evaluation.public import PublicExposureLedger
from arc3.evaluation.retrodiction_decision import (
    AMENDMENT_SHA256,
    PREDECLARATION_SHA256,
    CellMeasurement,
    EvaluationGroup,
    MicrobenchmarkMeasurement,
    ModeGateResult,
    RetrodictionDecision,
    build_evaluation_matrix,
    build_false_rule_cases,
    build_false_rule_manifest,
    choose_retrodiction_decision,
    evaluate_replacement_gates,
    selected_rule_change_cases,
    validate_false_rule_manifest,
)
from arc3.lab.rule_change import ActionVariant, PaletteVariant
from arc3.trace import TraceEvent
from arc3.types import ActionName
from arc3.world_model.retrodiction import PromotionStatus, RetrodictionMode, retrodict
from arc3.world_model.rules import (
    CollisionRule,
    ContactRelation,
    ContactRule,
    MovementRule,
)


def _event(
    event_id: str,
    event_type: str,
    payload: dict[str, object],
) -> TraceEvent:
    return cast(
        TraceEvent,
        SimpleNamespace(event_id=event_id, event_type=event_type, payload=payload),
    )


def _event_reuse_timeline(
    *,
    authority_transition_id: str = "transition:t1",
    supporting_model_id: str = "model:successor",
) -> tuple[TraceEvent, ...]:
    model_id = "model:successor"
    action = {"coordinate": None, "name": "ACTION1"}
    prefix_plan = {
        "authorizing_matched_prediction_evidence": [],
        "cache_hit": False,
        "cache_key": "cache:prefix",
        "complete_scope": True,
        "full_eligible_history_count": 1,
        "full_eligible_history_hash": "history:prefix",
        "generation": 1,
        "mechanics_epoch_id": "epoch:0",
        "mode": "EVENT_TRIGGERED",
        "model_id": model_id,
        "model_semantic_fingerprint": "model-fingerprint",
        "prefix_count": 0,
        "prior_artifact_id": None,
        "prior_source_receipt_event_id": None,
        "reason": "first-use",
        "retrodiction_configuration_hash": "config:stage07",
        "selected_history_count": 1,
        "selected_history_hash": "selected:prefix",
        "selected_transition_ids": ["transition:t0"],
        "suffix_count": 1,
    }
    authority = {
        "assessment_receipt_id": "assessment:r1",
        "consequence_event_id": "consequence:1",
        "match_scope": "whole-symbolic-state",
        "matched": True,
        "model_id": model_id,
        "prediction_event_id": "prediction:1",
        "prediction_receipt_id": "prediction:r1",
        "source_ordered": True,
        "transition_id": authority_transition_id,
    }
    reuse_plan = {
        "authorizing_matched_prediction_evidence": [authority],
        "cache_hit": True,
        "cache_key": "cache:extended",
        "complete_scope": True,
        "full_eligible_history_count": 2,
        "full_eligible_history_hash": "history:extended",
        "generation": 2,
        "mechanics_epoch_id": "epoch:0",
        "mode": "EVENT_TRIGGERED",
        "model_id": model_id,
        "model_semantic_fingerprint": "model-fingerprint",
        "prefix_count": 1,
        "prior_artifact_id": "artifact:prefix",
        "prior_source_receipt_event_id": "completed:prefix",
        "reason": "event-receipt-reuse",
        "retrodiction_configuration_hash": "config:stage07",
        "selected_history_count": 2,
        "selected_history_hash": "selected:extended",
        "selected_transition_ids": ["transition:t0", "transition:t1"],
        "suffix_count": 1,
    }
    return (
        _event("started:prefix", "model.retrodiction_started", dict(prefix_plan)),
        _event(
            "completed:prefix",
            "model.retrodiction_completed",
            {
                **prefix_plan,
                "artifact_id": "artifact:prefix",
                "result_complete": True,
                "reused": False,
                "retrodiction_reused_event_id": None,
                "retrodiction_started_event_id": "started:prefix",
            },
        ),
        _event(
            "selected:1",
            "action.selected",
            {"decision_id": "decision:1"},
        ),
        _event(
            "prediction:1",
            "simulation.prediction_emitted",
            {
                "action": action,
                "action_decision_id": "decision:1",
                "alternatives": [
                    {
                        "prediction_ids": ["prediction:item:1"],
                        "supporting_model_ids": [supporting_model_id],
                    }
                ],
                "receipt_id": "prediction:r1",
            },
        ),
        _event(
            "consequence:1",
            "consequence.received",
            {"action": action, "selected_event_id": "selected:1"},
        ),
        _event(
            "assessment:1",
            "consequence.matched_prediction",
            {
                "controlled_projection_match_model_ids": [],
                "match_scope": "whole-symbolic-state",
                "matched_prediction_ids": ["prediction:item:1"],
                "prediction_receipt_id": "prediction:r1",
                "receipt_id": "assessment:r1",
            },
        ),
        _event("started:reuse", "model.retrodiction_started", dict(reuse_plan)),
        _event(
            "reused:1",
            "model.retrodiction_reused",
            {**reuse_plan, "retrodiction_started_event_id": "started:reuse"},
        ),
        _event(
            "completed:reuse",
            "model.retrodiction_completed",
            {
                **reuse_plan,
                "artifact_id": "artifact:extended",
                "result_complete": True,
                "reused": True,
                "retrodiction_reused_event_id": "reused:1",
                "retrodiction_started_event_id": "started:reuse",
            },
        ),
    )


def test_false_rule_cases_have_exact_old_contradiction_and_true_history() -> None:
    cases = build_false_rule_cases()

    assert len(cases) == 8
    assert [item.seed for item in cases] == list(range(1, 9))
    assert len({item.true_model.model_id for item in cases}) == 8
    assert len({item.false_model.model_id for item in cases}) == 8
    for item in cases:
        true_artifact = retrodict(item.true_model, item.transitions)
        false_artifact = retrodict(item.false_model, item.transitions)
        recent_false = retrodict(item.false_model, item.transitions[-8:])

        assert true_artifact.status is PromotionStatus.PROMOTED
        assert true_artifact.matched_transition_ids == tuple(
            transition.transition_id for transition in item.transitions
        )
        assert false_artifact.status is PromotionStatus.REJECTED
        assert false_artifact.contradiction_transition_ids == (item.transitions[0].transition_id,)
        assert recent_false.status is PromotionStatus.PROMOTED
        assert item.transitions[0].transition_id not in recent_false.tested_transition_ids


def test_event_reuse_receipt_binds_exact_selected_suffix_and_causal_match() -> None:
    parity, receipt_valid = _event_receipt_integrity(
        _event_reuse_timeline(), RetrodictionMode.EVENT_TRIGGERED
    )

    assert parity is True
    assert receipt_valid is True


@pytest.mark.parametrize(
    ("authority_transition_id", "supporting_model_id"),
    (
        ("transition:unrelated", "model:successor"),
        ("transition:t1", "model:unrelated"),
    ),
)
def test_event_reuse_receipt_rejects_unrelated_suffix_or_matching_model(
    authority_transition_id: str,
    supporting_model_id: str,
) -> None:
    _parity, receipt_valid = _event_receipt_integrity(
        _event_reuse_timeline(
            authority_transition_id=authority_transition_id,
            supporting_model_id=supporting_model_id,
        ),
        RetrodictionMode.EVENT_TRIGGERED,
    )

    assert receipt_valid is False


def test_false_rule_rule_compositions_are_exact_and_b07_uses_amended_adjacency() -> None:
    cases = build_false_rule_cases()
    by_code = {item.code: item for item in cases}

    for code in ("B01", "B02", "B04", "B05", "B06", "B08"):
        assert len(by_code[code].true_model.rules) == 2
        assert len(by_code[code].false_model.rules) == 2
    for code in ("B03", "B07"):
        assert sum(isinstance(rule, MovementRule) for rule in by_code[code].true_model.rules) == 1
        assert sum(isinstance(rule, MovementRule) for rule in by_code[code].false_model.rules) == 1
    assert sum(isinstance(rule, CollisionRule) for rule in by_code["B03"].true_model.rules) == 1

    b07 = by_code["B07"]
    true_contact = next(rule for rule in b07.true_model.rules if isinstance(rule, ContactRule))
    false_contact = next(rule for rule in b07.false_model.rules if isinstance(rule, ContactRule))
    assert true_contact.relation is ContactRelation.ADJACENT
    assert false_contact.relation is ContactRelation.ADJACENT
    assert not any(isinstance(rule, CollisionRule) for rule in b07.true_model.rules)
    assert not any(isinstance(rule, CollisionRule) for rule in b07.false_model.rules)
    before = b07.transitions[0].before
    after = b07.transitions[0].after
    assert before.entity("mover").anchor.x == 2  # type: ignore[union-attr]
    assert before.entity("beacon").anchor.x == 4  # type: ignore[union-attr]
    assert after.entity("mover").anchor.x == 3  # type: ignore[union-attr]
    assert "contacted" in after.facts
    assert after.toggle("contacted") == "off"


def test_coordinate_selection_case_preserves_exact_action_and_truth() -> None:
    b08 = build_false_rule_cases()[-1]

    assert b08.action.name is ActionName.ACTION6
    assert b08.action.coordinate is not None
    assert (b08.action.coordinate.x, b08.action.coordinate.y) == (2, 1)
    assert b08.transitions[0].after.selected_id == "choice-good"
    assert (
        b08.false_model.predict(b08.transitions[0].before, b08.action).after_state.selected_id
        == "choice-bad"
    )


def test_matrix_is_exact_280_cells_in_frozen_group_case_mode_order() -> None:
    matrix = build_evaluation_matrix()

    assert len(matrix) == 280
    assert len({item.cell_id for item in matrix}) == 280
    assert [item.mode for item in matrix[:5]] == list(RetrodictionMode)
    assert [item.group for item in matrix[:70]] == [EvaluationGroup.A_STAGE14] * 70
    assert [item.group for item in matrix[70:110]] == [EvaluationGroup.B_FALSE_RULE] * 40
    assert [item.group for item in matrix[110:270]] == [EvaluationGroup.C_RULE_CHANGE] * 160
    assert [item.group for item in matrix[270:]] == [EvaluationGroup.D_LOCAL_PUBLIC] * 10
    assert matrix[0].case_id == "navigation-seed-101"
    assert matrix[69].case_id == "held-out-families-0002"
    assert matrix[70].case_id == "stage07-false-rule-b01-movement-sign"
    assert matrix[109].case_id == "stage07-false-rule-b08-coordinate-selection"
    assert matrix[270].case_id == "ar25-0c556536"
    assert matrix[-1].seed == 23


def test_rule_change_subset_is_exact_balanced_frozen_selection() -> None:
    selected = selected_rule_change_cases()

    assert len(selected) == 32
    assert len({item.case_id for item in selected}) == 32
    assert sum("intervention-action_effect_rotation" in item.case_id for item in selected) == 8
    assert sum("intervention-traversability_flip" in item.case_id for item in selected) == 8
    assert sum("stage06-noise" in item.case_id for item in selected) == 16
    assert {item.seed for item in selected} == {7, 11, 23, 29}
    assert (
        sum(
            item.palette_variant is PaletteVariant.IDENTITY
            and item.action_variant is ActionVariant.IDENTITY
            for item in selected
        )
        == 8
    )
    assert (
        sum(
            item.palette_variant is PaletteVariant.AFFINE_NONIDENTITY
            and item.action_variant is ActionVariant.CYCLE1234
            for item in selected
        )
        == 8
    )


def test_manifest_binds_both_contracts_and_rejects_any_mutation() -> None:
    manifest = build_false_rule_manifest()

    contracts = cast(dict[str, object], manifest["composite_contract"])
    assert contracts["base_sha256"] == PREDECLARATION_SHA256
    assert contracts["amendment_sha256"] == AMENDMENT_SHA256
    assert manifest["case_count"] == 8
    assert manifest["evaluation_cell_count"] == 280
    assert all(validate_false_rule_manifest(manifest).values())

    changed = {**manifest, "evaluation_cell_count": 279}
    predicates = validate_false_rule_manifest(changed)
    assert predicates["exact_manifest"] is False
    assert predicates["evaluation_cell_count"] is False


def _measurement(
    cell_id: str,
    *,
    mode: RetrodictionMode,
    group: str,
    accepted_true_model_id: str | None = None,
) -> CellMeasurement:
    is_full = mode is RetrodictionMode.FULL
    is_b = group == EvaluationGroup.B_FALSE_RULE.value
    return CellMeasurement(
        cell_id=cell_id,
        completed=True,
        score=1.0,
        levels_completed=1,
        actions=0 if is_b else 10,
        resets=0,
        wall_ns=1_000_000 if is_full else 800_000,
        cpu_ns=900_000 if is_full else 700_000,
        retrodiction_wall_ns=10_000 if is_full else 5_000,
        retrodiction_cpu_ns=8_000 if is_full else 4_000,
        peak_rss_bytes=100_000_000,
        accepted_true_model_ids=(accepted_true_model_id,)
        if is_b and accepted_true_model_id
        else (),
        accepted_false_model_ids=(),
        intervention_triggered=True if group == EvaluationGroup.C_RULE_CHANGE.value else None,
        strict_stage06_lifecycle_passed=(
            True if group == EvaluationGroup.C_RULE_CHANGE.value else None
        ),
        raw_noise_resolved=True if group == EvaluationGroup.C_RULE_CHANGE.value else None,
        cache_hit_count=1 if mode is RetrodictionMode.CACHED_INCREMENTAL else 0,
    )


def _complete_measurements() -> list[CellMeasurement]:
    result: list[CellMeasurement] = []
    false_cases = {item.case_id: item for item in build_false_rule_cases()}
    for cell in build_evaluation_matrix():
        false_case = false_cases.get(cell.case_id)
        measurement = _measurement(
            cell.cell_id,
            mode=cell.mode,
            group=cell.group.value,
            accepted_true_model_id=(
                false_case.true_model.model_id if false_case is not None else None
            ),
        )
        if cell.group is EvaluationGroup.C_RULE_CHANGE:
            is_noise = cell.group_case_ordinal >= 16
            measurement = replace(
                measurement,
                intervention_triggered=not is_noise,
                raw_noise_resolved=is_noise,
            )
        result.append(measurement)
    return result


def _complete_microbenchmarks() -> list[MicrobenchmarkMeasurement]:
    return [
        MicrobenchmarkMeasurement(
            mode=mode,
            history_size=size,
            path=path,
            median_wall_ns=1_000 if mode is RetrodictionMode.FULL else 500,
            median_cpu_ns=800 if mode is RetrodictionMode.FULL else 400,
            semantic_parity=True,
            cache_hit=mode is RetrodictionMode.CACHED_INCREMENTAL and path.startswith("append"),
        )
        for mode in RetrodictionMode
        for size in (2, 4, 8, 16, 32, 64)
        for path in ("cold_exact_n", "append_one_from_verified_n_minus_1_prefix")
    ]


def test_gate_evaluator_uses_fixed_full_cost_rows_and_coverage_tie_break() -> None:
    results = evaluate_replacement_gates(_complete_measurements(), _complete_microbenchmarks())

    assert len(results) == 4
    assert all(item.eligible for item in results)
    assert choose_retrodiction_decision(results) is RetrodictionDecision.CACHE_INCREMENTAL


def test_false_rule_acceptance_disqualifies_only_the_affected_mode() -> None:
    measurements = _complete_measurements()
    target = next(
        cell
        for cell in build_evaluation_matrix()
        if cell.group is EvaluationGroup.B_FALSE_RULE
        and cell.mode is RetrodictionMode.RECENT_WINDOW_8
    )
    index = next(index for index, item in enumerate(measurements) if item.cell_id == target.cell_id)
    measurements[index] = replace(measurements[index], accepted_false_model_ids=("FALSE",))

    results = evaluate_replacement_gates(measurements, _complete_microbenchmarks())
    recent = next(item for item in results if item.mode is RetrodictionMode.RECENT_WINDOW_8)
    others = tuple(item for item in results if item.mode is not RetrodictionMode.RECENT_WINDOW_8)
    assert dict(recent.predicates)["false_rule_gate_B"] is False
    assert recent.eligible is False
    assert all(item.eligible for item in others)


def test_decision_falls_back_to_full_when_no_replacement_is_eligible() -> None:
    results = tuple(
        ModeGateResult(mode, False, None, (("failed", False),))
        for mode in tuple(RetrodictionMode)[1:]
    )
    assert choose_retrodiction_decision(results) is RetrodictionDecision.KEEP_FULL


def test_microbenchmark_fixture_and_incremental_paths_are_exact() -> None:
    model, transitions = build_micro_history(16)

    assert len(transitions) == 16
    assert tuple(item.transition_id for item in transitions) == tuple(
        f"stage07-micro-n0016-t{index:03d}" for index in range(16)
    )
    assert all(item.compatible_model_ids == (model.model_id,) for item in transitions)
    for mode in RetrodictionMode:
        measured = measure_microbenchmark_cell(
            mode,
            16,
            "append_one_from_verified_n_minus_1_prefix",
            warmups=0,
            repetitions=1,
        )
        assert measured.measurement.semantic_parity is True
        assert len(measured.measured_wall_ns) == 1
        assert len(measured.measured_cpu_ns) == 1
        if mode in {
            RetrodictionMode.EVENT_TRIGGERED,
            RetrodictionMode.CACHED_INCREMENTAL,
        }:
            assert measured.measurement.cache_hit is True
            assert measured.prefix_counts == (15,)
            assert measured.suffix_counts == (1,)


def test_runner_no_overwrite_guard_rejects_existing_targets(tmp_path: Path) -> None:
    output = tmp_path / "result.json"
    work = tmp_path / "work"
    output.write_text("preserve", encoding="utf-8")
    with pytest.raises(Exception, match="cannot be overwritten"):
        _require_fresh_targets(output, work)

    output.unlink()
    work.mkdir()
    (work / "receipt.json").write_text("preserve", encoding="utf-8")
    with pytest.raises(Exception, match="not empty"):
        _require_fresh_targets(output, work)


def test_source_stability_requires_clean_exact_start_and_end() -> None:
    identity = {
        "amendment_sha256": "A",
        "dirty_worktree": False,
        "false_rule_manifest_sha256": "M",
        "first_party_source_hash": "S",
        "git_commit": "C",
        "git_tree": "T",
        "identity_hash": "I",
        "predeclaration_sha256": "P",
        "public_partition_sha256": "H",
    }
    assert _source_stability(identity, identity)["passed"] is True
    drifted = {**identity, "git_tree": "changed", "identity_hash": "J"}
    assert _source_stability(identity, drifted)["passed"] is False


def test_socket_deny_counts_attempt_and_restores_constructor() -> None:
    original = socket.socket
    guard = _SocketDeny()
    with guard, pytest.raises(RuntimeError, match="socket access denied"):
        socket.socket()
    assert guard.attempt_count == 1
    assert socket.socket is original


def test_holdout_guard_fails_closed_on_a_holdout_exposure_receipt(tmp_path: Path) -> None:
    ledger_path = tmp_path / "exposure.jsonl"
    PublicExposureLedger(ledger_path).append(
        "test.holdout_attempt",
        {"game_id": "ls20-7880a0b6", "partition": "public-holdout"},
    )
    result = _holdout_integrity(ledger_path, tmp_path / "empty-assets")

    assert result["passed"] is False
    assert result["public_holdout_gameplay_events"] == 1


def test_verification_timeout_is_not_relabelled_as_infrastructure(tmp_path: Path) -> None:
    timeout = subprocess.TimeoutExpired(["python", "-m", "pytest"], 300.0)
    with patch("scripts.measure_retrodiction_decision.subprocess.run", side_effect=timeout):
        receipt = _run_verification_command(("python", "-m", "pytest"), tmp_path, 0)

    assert receipt["timed_out"] is True
    assert receipt["infrastructure_failure"] is False
    assert receipt["passed"] is False
