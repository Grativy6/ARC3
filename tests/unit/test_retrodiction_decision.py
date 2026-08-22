"""Frozen Stage 07 case-manifest, matrix, and decision-gate checks."""

from __future__ import annotations

import json
import socket
import subprocess
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import cast
from unittest.mock import patch

import pytest
from scripts.measure_retrodiction_decision import (
    _EXPECTED_DEVELOPMENT_ASSET_IDENTITY,
    DEFAULT_ENVIRONMENTS_DIR,
    DEFAULT_EXPOSURE_LEDGER,
    DEFAULT_OUTPUT,
    DEFAULT_RECORDINGS_DIR,
    DEFAULT_WORK_ROOT,
    _apply_global_integrity,
    _development_asset_matrix_integrity,
    _development_asset_receipt,
    _event_receipt_integrity,
    _holdout_integrity,
    _memory_receipt,
    _profile_retrodiction,
    _require_fresh_targets,
    _require_official_paths,
    _run_public_cell,
    _run_verification_command,
    _SocketDeny,
    _source_stability,
    build_micro_history,
    main,
    measure_microbenchmark_cell,
)

from arc3.evaluation.public import LocalAssetIdentity, PublicExposureLedger
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
from arc3.types import ActionName, GameStateName
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
            cache_hit=(
                mode in {RetrodictionMode.EVENT_TRIGGERED, RetrodictionMode.CACHED_INCREMENTAL}
                and path.startswith("append")
            ),
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

    work_file = work / "receipt.json"
    work_file.unlink()
    exposure = tmp_path / "exposure.jsonl"
    exposure.write_text("preserve", encoding="utf-8")
    with pytest.raises(Exception, match="exposure ledger already exists"):
        _require_fresh_targets(output, work, exposure_ledger=exposure)

    exposure.unlink()
    recordings = tmp_path / "recordings"
    recordings.mkdir()
    (recordings / "receipt.json").write_text("preserve", encoding="utf-8")
    with pytest.raises(Exception, match="recordings root already exists"):
        _require_fresh_targets(output, work, recordings_dir=recordings)


def test_source_stability_requires_clean_exact_start_and_end() -> None:
    identity = {
        "amendment_sha256": "A",
        "branch": "build/001-local-public-recovery",
        "dirty_worktree": False,
        "false_rule_manifest_sha256": "M",
        "first_party_source_hash": "S",
        "git_commit": "C",
        "git_tree": "T",
        "identity_hash": "I",
        "predeclaration_sha256": "P",
        "public_partition_sha256": "H",
        "source_baseline_ancestor": True,
        "source_baseline_commit": "B",
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
    result = _holdout_integrity(
        ledger_path,
        tmp_path / "empty-assets",
        inherited_ledgers=(),
    )

    assert result["passed"] is False
    assert result["public_holdout_gameplay_events"] == 1


def test_verification_timeout_is_not_relabelled_as_infrastructure(tmp_path: Path) -> None:
    timeout = subprocess.TimeoutExpired(["python", "-m", "pytest"], 300.0)
    with patch("scripts.measure_retrodiction_decision.subprocess.run", side_effect=timeout):
        receipt = _run_verification_command(("python", "-m", "pytest"), tmp_path, 0)

    assert receipt["timed_out"] is True
    assert receipt["infrastructure_failure"] is False
    assert receipt["passed"] is False


def test_retrodiction_cache_hits_are_phase_scoped() -> None:
    profile = {
        "cache_totals": {"hits": 99},
        "phases": {
            "retrodiction": {
                "cache_hits": 2,
                "inclusive_cpu_ns": 11,
                "inclusive_wall_ns": 13,
            }
        },
    }

    assert _profile_retrodiction(profile) == (13, 11, 2)


def test_memory_receipt_fails_closed_when_rss_is_unavailable() -> None:
    receipt = _memory_receipt(
        {
            "current_rss_bytes": None,
            "measurement_source": "unavailable",
            "peak_rss_bytes": None,
        }
    )

    assert receipt["passed"] is False
    assert receipt["peak_rss_bytes"] == 0


def test_missing_typed_artifact_receipt_fails_hard_integrity() -> None:
    measurement = _complete_measurements()[0]

    assert measurement.hard_integrity_passed is True
    assert replace(measurement, artifact_receipts_valid=False).hard_integrity_passed is False


def test_official_path_guard_rejects_alternate_exposure_or_asset_roots(tmp_path: Path) -> None:
    _require_official_paths(
        output=DEFAULT_OUTPUT,
        work_root=DEFAULT_WORK_ROOT,
        exposure_ledger=DEFAULT_EXPOSURE_LEDGER,
        environments_dir=DEFAULT_ENVIRONMENTS_DIR,
        recordings_dir=DEFAULT_RECORDINGS_DIR,
    )
    with pytest.raises(Exception, match="frozen contract"):
        _require_official_paths(
            output=DEFAULT_OUTPUT,
            work_root=DEFAULT_WORK_ROOT,
            exposure_ledger=tmp_path / "fresh-exposure.jsonl",
            environments_dir=tmp_path / "fresh-assets",
            recordings_dir=DEFAULT_RECORDINGS_DIR,
        )


def test_inherited_holdout_ledger_hash_is_mandatory(tmp_path: Path) -> None:
    inherited = tmp_path / "inherited.jsonl"
    PublicExposureLedger(inherited).append(
        "test.development",
        {"game_id": "ar25-0c556536", "partition": "development"},
    )
    result = _holdout_integrity(
        tmp_path / "current.jsonl",
        tmp_path / "assets",
        inherited_ledgers=(("inherited", inherited, "sha256:not-the-file"),),
    )

    assert result["passed"] is False
    assert result["public_holdout_gameplay_events"] == 0


def test_frozen_development_asset_identity_accepts_exact_measured_bytes() -> None:
    receipt = _development_asset_receipt(_EXPECTED_DEVELOPMENT_ASSET_IDENTITY)

    assert receipt["passed"] is True
    assert all(cast(dict[str, bool], receipt["predicates"]).values())


@pytest.mark.parametrize(
    "observed",
    (
        replace(
            _EXPECTED_DEVELOPMENT_ASSET_IDENTITY,
            aggregate_sha256="sha256:forged",
        ),
        replace(
            _EXPECTED_DEVELOPMENT_ASSET_IDENTITY,
            files=(
                ("renamed.py", 77_599, _EXPECTED_DEVELOPMENT_ASSET_IDENTITY.files[0][2]),
                _EXPECTED_DEVELOPMENT_ASSET_IDENTITY.files[1],
            ),
        ),
        replace(
            _EXPECTED_DEVELOPMENT_ASSET_IDENTITY,
            files=(
                (
                    _EXPECTED_DEVELOPMENT_ASSET_IDENTITY.files[0][0],
                    77_600,
                    _EXPECTED_DEVELOPMENT_ASSET_IDENTITY.files[0][2],
                ),
                _EXPECTED_DEVELOPMENT_ASSET_IDENTITY.files[1],
            ),
        ),
        replace(
            _EXPECTED_DEVELOPMENT_ASSET_IDENTITY,
            files=(
                (
                    _EXPECTED_DEVELOPMENT_ASSET_IDENTITY.files[0][0],
                    _EXPECTED_DEVELOPMENT_ASSET_IDENTITY.files[0][1],
                    "sha256:forged",
                ),
                _EXPECTED_DEVELOPMENT_ASSET_IDENTITY.files[1],
            ),
        ),
    ),
)
def test_frozen_development_asset_identity_rejects_every_byte_identity_drift(
    observed: LocalAssetIdentity,
) -> None:
    assert _development_asset_receipt(observed)["passed"] is False


def test_development_asset_matrix_requires_all_ten_exact_three_point_receipts() -> None:
    matrix = build_evaluation_matrix()
    development = tuple(item for item in matrix if item.group is EvaluationGroup.D_LOCAL_PUBLIC)
    exact = _development_asset_receipt(_EXPECTED_DEVELOPMENT_ASSET_IDENTITY)
    raw = {
        cell.cell_id: {
            "asset_identity_before_open": exact,
            "asset_identity_after_open": exact,
            "asset_identity_after_episode": exact,
            "asset_identity_stable": True,
        }
        for cell in development
    }

    accepted = _development_asset_matrix_integrity(matrix, raw)
    assert accepted["passed"] is True

    drifted = dict(raw)
    drifted_receipt = _development_asset_receipt(
        replace(_EXPECTED_DEVELOPMENT_ASSET_IDENTITY, aggregate_sha256="sha256:forged")
    )
    drifted[development[0].cell_id] = {
        **raw[development[0].cell_id],
        "asset_identity_after_episode": drifted_receipt,
    }
    rejected = _development_asset_matrix_integrity(matrix, drifted)
    assert rejected["passed"] is False
    assert cast(dict[str, bool], rejected["per_cell"])[development[0].cell_id] is False

    missing = dict(raw)
    missing.pop(development[-1].cell_id)
    assert _development_asset_matrix_integrity(matrix, missing)["passed"] is False


def test_holdout_integrity_rejects_development_asset_drift_before_launch(
    tmp_path: Path,
) -> None:
    wrong = replace(
        _EXPECTED_DEVELOPMENT_ASSET_IDENTITY,
        aggregate_sha256="sha256:forged",
    )

    def identity_for_entry(_root: Path, entry: object) -> LocalAssetIdentity | None:
        return wrong if getattr(entry, "game_id", None) == wrong.game_id else None

    with patch(
        "scripts.measure_retrodiction_decision.local_asset_identity",
        side_effect=identity_for_entry,
    ):
        result = _holdout_integrity(
            tmp_path / "current.jsonl",
            tmp_path / "assets",
            inherited_ledgers=(),
        )

    assert result["passed"] is False
    assert cast(dict[str, bool], result["predicates"])["development_asset_identity"] is False


def test_holdout_integrity_accepts_exact_development_asset_before_launch(
    tmp_path: Path,
) -> None:
    expected = _EXPECTED_DEVELOPMENT_ASSET_IDENTITY

    def identity_for_entry(_root: Path, entry: object) -> LocalAssetIdentity | None:
        return expected if getattr(entry, "game_id", None) == expected.game_id else None

    with patch(
        "scripts.measure_retrodiction_decision.local_asset_identity",
        side_effect=identity_for_entry,
    ):
        result = _holdout_integrity(
            tmp_path / "current.jsonl",
            tmp_path / "assets",
            inherited_ledgers=(),
        )

    assert result["passed"] is True


def test_failed_development_asset_matrix_marks_d_cell_hard_integrity_false() -> None:
    matrix = build_evaluation_matrix()
    measurements = _complete_measurements()
    development = tuple(item for item in matrix if item.group is EvaluationGroup.D_LOCAL_PUBLIC)
    exact = _development_asset_receipt(_EXPECTED_DEVELOPMENT_ASSET_IDENTITY)
    raw = {
        cell.cell_id: {
            "asset_identity_before_open": exact,
            "asset_identity_after_open": exact,
            "asset_identity_after_episode": exact,
            "asset_identity_stable": True,
        }
        for cell in development
    }
    failed_cell = development[0]
    raw[failed_cell.cell_id] = {
        **raw[failed_cell.cell_id],
        "asset_identity_stable": False,
    }
    integrity = _development_asset_matrix_integrity(matrix, raw)

    updated = _apply_global_integrity(
        matrix,
        measurements,
        raw,
        development_asset_integrity=integrity,
        source_valid=True,
        holdout_exposure_count=0,
    )
    failed = next(item for item in updated if item.cell_id == failed_cell.cell_id)
    assert failed.source_identity_valid is False
    assert failed.hard_integrity_passed is False


@pytest.mark.parametrize("drift_call", (1, 2))
def test_public_cell_rejects_asset_mutation_after_open_or_episode_without_gameplay(
    tmp_path: Path,
    drift_call: int,
) -> None:
    cell = next(
        item
        for item in build_evaluation_matrix()
        if item.group is EvaluationGroup.D_LOCAL_PUBLIC and item.mode is RetrodictionMode.FULL
    )
    wrong = replace(
        _EXPECTED_DEVELOPMENT_ASSET_IDENTITY,
        aggregate_sha256="sha256:forged",
    )
    identities = [_EXPECTED_DEVELOPMENT_ASSET_IDENTITY] * 3
    identities[drift_call] = wrong
    fake_session = SimpleNamespace(observation=SimpleNamespace(game_id=cell.case_id))
    fake_run = SimpleNamespace(
        completed=False,
        levels_completed=0,
        score=0.0,
        state=GameStateName.GAME_OVER,
    )
    fake_scorecard = SimpleNamespace(runs=[fake_run])

    with (
        patch(
            "scripts.measure_retrodiction_decision.local_asset_identity",
            side_effect=identities,
        ),
        patch(
            "scripts.measure_retrodiction_decision.ArcAGIAdapter",
            return_value=SimpleNamespace(open=lambda _game_id, seed: fake_session),
        ),
        patch(
            "scripts.measure_retrodiction_decision.run_public_episode",
            return_value=(fake_scorecard, {"environment_actions": 0, "resets": 0}),
        ),
        patch(
            "scripts.measure_retrodiction_decision._checkpoint_restore",
            return_value=(str(tmp_path / "checkpoint.json"), True),
        ),
    ):
        with pytest.raises(Exception, match="asset identity changed"):
            _run_public_cell(
                cell,
                cell_root=tmp_path / "cell",
                git_commit="test-commit",
                exposure_ledger=tmp_path / "exposure.jsonl",
                environments_dir=tmp_path / "assets",
                recordings_dir=tmp_path / "recordings",
            )


def test_cached_false_rule_parity_is_paired_to_full_not_self_roundtrip() -> None:
    matrix = build_evaluation_matrix()
    measurements = _complete_measurements()
    raw: dict[str, dict[str, object]] = {}
    pair = next(item.pair_key for item in matrix if item.group is EvaluationGroup.B_FALSE_RULE)
    full = next(
        item for item in matrix if item.pair_key == pair and item.mode is RetrodictionMode.FULL
    )
    cached = next(
        item
        for item in matrix
        if item.pair_key == pair and item.mode is RetrodictionMode.CACHED_INCREMENTAL
    )
    raw[full.cell_id] = {"artifact_projection": [{"artifact_id": "full"}]}
    raw[cached.cell_id] = {"artifact_projection": [{"artifact_id": "different"}]}

    updated = _apply_global_integrity(
        matrix,
        measurements,
        raw,
        source_valid=True,
        holdout_exposure_count=0,
    )
    cached_measurement = next(item for item in updated if item.cell_id == cached.cell_id)
    assert cached_measurement.full_artifact_parity is False


def test_global_integrity_preserves_an_incomplete_measured_prefix() -> None:
    matrix = build_evaluation_matrix()
    measurements = _complete_measurements()[:-1]

    updated = _apply_global_integrity(
        matrix,
        measurements,
        {},
        source_valid=True,
        holdout_exposure_count=0,
    )

    assert len(updated) == 279
    assert tuple(item.cell_id for item in updated) == tuple(item.cell_id for item in measurements)
    assert matrix[-1].cell_id not in {item.cell_id for item in updated}


def test_main_serializes_partial_result_and_returns_nonzero(tmp_path: Path) -> None:
    output = tmp_path / "partial.json"
    partial = {
        "artifact_core_hash": "sha256:partial",
        "decision": "KEEP_FULL",
        "status": "PARTIAL",
    }

    with (
        patch("scripts.measure_retrodiction_decision._require_composite_contract", return_value={}),
        patch(
            "scripts.measure_retrodiction_decision.measure_retrodiction_decision",
            return_value=partial,
        ),
    ):
        returncode = main(["--execute", "--output", str(output)])

    assert returncode == 1
    assert json.loads(output.read_text(encoding="utf-8")) == partial


def test_replacement_gate_rejects_a_frozen_cell_wall_budget_overrun() -> None:
    measurements = _complete_measurements()
    target = next(
        item
        for item in build_evaluation_matrix()
        if item.group is EvaluationGroup.A_STAGE14
        and item.mode is RetrodictionMode.CACHED_INCREMENTAL
    )
    index = next(index for index, item in enumerate(measurements) if item.cell_id == target.cell_id)
    measurements[index] = replace(measurements[index], wall_ns=121_000_000_000)

    results = evaluate_replacement_gates(measurements, _complete_microbenchmarks())
    cached = next(item for item in results if item.mode is RetrodictionMode.CACHED_INCREMENTAL)
    assert dict(cached.predicates)["per_cell_budget_integrity"] is False
    assert cached.eligible is False
