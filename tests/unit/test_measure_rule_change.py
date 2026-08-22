"""Focused contract tests for the frozen Stage 06 measurement harness."""

from __future__ import annotations

import subprocess
import sys
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from typing import cast
from unittest.mock import patch

import pytest
from scripts.measure_rule_change_reopening import (
    _CHECKPOINT_RESUMED_DIR,
    _CHECKPOINT_UNINTERRUPTED_DIR,
    _CHECKPOINT_WORKSPACE_DIR,
    _FOCUSED_VERIFICATION_TESTS,
    _INTERVENTION_WORKSPACE_DIR,
    _NOISE_WORKSPACE_DIR,
    _WORKSPACE_COMPONENT_MAX_CHARS,
    _WORKSPACE_PROJECTED_PATH_MAX_CHARS,
    DEFAULT_OUTPUT,
    DEFAULT_WORK_ROOT,
    MAX_ACTIONS,
    MAX_CHECKPOINT_BYTES,
    MAX_CONFIRMATION_ACTIONS,
    MAX_PEAK_RSS_BYTES,
    MAX_POST_TRIGGER_ACTIONS,
    MAX_TRACE_BYTES,
    MAX_TRIGGER_ACTION,
    PREDECLARATION,
    PREDECLARATION_SHA256,
    PUBLIC_PARTITION_MANIFEST_SHA256,
    ROOT,
    STAGE05_ACCEPTANCE_COMMIT,
    STAGE05_EVIDENCE_BLOB_OID,
    STAGE05_EVIDENCE_PATH,
    STAGE05_EVIDENCE_SHA256,
    _aggregate_measurements,
    _case_workspace_component,
    _causal_action_replay,
    _checkpoint_commitment_report,
    _checkpoint_resource_report,
    _checkpoint_suite,
    _checkpoint_workspace_component,
    _classify_stage_status,
    _coherent_candidate_confirmation,
    _event_source_closure_after,
    _failed_mechanism_predicates,
    _fold_lifecycle_timeline,
    _holdout_source_bindings,
    _infrastructure_failure_count,
    _intervention_suite,
    _invalidated_plan_ids,
    _lifecycle_summary,
    _linked_candidate_confirmation_support,
    _linked_lifecycle_chain,
    _linked_noise_closure,
    _metamorphic_groups,
    _noise_suite,
    _observation_blinding_report,
    _pretrigger_checkpoint_ready,
    _resource_summary,
    _run_verification_command,
    _schedule_workspace_paths,
    _semantic_identifier_projection,
    _source_identity_stability,
    _stale_authority_uses,
    _truth_receipt_report,
    _verification_pytest_basetemp,
)

from arc3.integrity.hashes import sha256_file
from arc3.lab.rule_change import (
    ActionVariant,
    PaletteVariant,
    RuleChangeCase,
    RuleChangeCaseKind,
    RuleChangeCheckpointCase,
    RuleChangeFamily,
    RuleChangeTiming,
    checkpoint_schedule,
    intervention_schedule,
    noise_control_schedule,
    open_rule_change_case,
)
from arc3.trace import CodeIdentity, SourceIdentity, TraceEvent
from arc3.trace.canonical import sha256_json
from arc3.types import ActionName, ActionRequest

_SOURCE = SourceIdentity("stage06-harness-test", "0.1")
_CODE = CodeIdentity("stage06-harness-test", "sha256:" + "1" * 64)
_WHEN = "2026-08-22T00:00:00Z"


def _event(
    event_id: str,
    event_type: str,
    payload: dict[str, object],
    *,
    previous_event_hash: str | None = None,
    scope: str = "episode",
    step: int = 0,
) -> TraceEvent:
    return TraceEvent.create(
        run_id="run-stage06-harness-test",
        episode_id="episode-stage06-harness-test",
        game_id="synthetic-redacted",
        level_index=0,
        step_index=step,
        event_type=event_type,
        source=_SOURCE,
        scope=scope,
        payload=payload,
        code_identity=_CODE,
        previous_event_hash=previous_event_hash,
        event_id=event_id,
        occurred_at=_WHEN,
        recorded_at=_WHEN,
    )


def _case(action_variant: ActionVariant = ActionVariant.IDENTITY) -> RuleChangeCase:
    return RuleChangeCase(
        case_id="stage06-intervention-action_effect_rotation-early_support_2-s7-test",
        kind=RuleChangeCaseKind.INTERVENTION,
        family=RuleChangeFamily.ACTION_EFFECT_ROTATION,
        timing=RuleChangeTiming.EARLY_SUPPORT_2,
        seed=7,
        palette_variant=PaletteVariant.IDENTITY,
        action_variant=action_variant,
    )


def _fake_result(*, palette: PaletteVariant, action: ActionVariant) -> dict[str, object]:
    raw_name = "ACTION1" if action is ActionVariant.IDENTITY else "ACTION2"
    return {
        "action_count": 8,
        "action_request_sequence": [{"coordinate": None, "name": raw_name}],
        "case": {
            "action_variant": action.value,
            "case_id": f"fake-{palette.value}-{action.value}",
            "family": RuleChangeFamily.ACTION_EFFECT_ROTATION.value,
            "kind": RuleChangeCaseKind.INTERVENTION.value,
            "palette_variant": palette.value,
            "seed": 7,
            "timing": RuleChangeTiming.EARLY_SUPPORT_2.value,
        },
        "case_passed": True,
        "lifecycle_summary": {"active_epoch_index": 1},
        "terminal_state": "WIN",
        "trigger_step": 5,
        "truth": {
            "receipts": [
                {
                    "after_position": [1, 1],
                    "attempted_role": "neutral-open",
                    "coherent_successor_receipts": 1,
                    "mechanics_epoch": 1,
                    "predecessor_effect": [0, -1],
                    "pulse_kind": "persistent-intervention",
                    "pulse_resolved": False,
                    "realized_effect": [1, 0],
                    "result_kind": "translation",
                    "resumed_predecessor_receipts": 0,
                    "terminal_state": "NOT_FINISHED",
                }
            ]
        },
    }


def test_frozen_paths_and_budget_constants_match_predeclaration() -> None:
    assert PREDECLARATION.name == "001-06-rule-change-predeclaration.json"
    assert PREDECLARATION_SHA256 == (
        "sha256:0bca5f32986c79008cf6ee01a83867262cda591f477239a5b8e9bccd90e37434"
    )
    assert STAGE05_ACCEPTANCE_COMMIT == "916c801"
    assert PUBLIC_PARTITION_MANIFEST_SHA256 == (
        "sha256:682d5891c2aface54803d9bd1173c55ed21e89856e13b8a478fb9276ee963f2f"
    )
    assert STAGE05_EVIDENCE_BLOB_OID == "b25078fe3ae2cbc57db2d367b0f7424bbde63195"
    assert STAGE05_EVIDENCE_SHA256 == (
        "sha256:7d9a72d9e222944a60cf92cb2b3bd5db2e33f46d5a64be4d22f91df224adf85a"
    )
    assert DEFAULT_OUTPUT.as_posix().endswith("stage06/rule-change-reopening.json")
    assert DEFAULT_WORK_ROOT.as_posix().endswith("stage06/rule-change-reopening-work")
    assert MAX_ACTIONS == 48
    assert MAX_TRIGGER_ACTION == 24
    assert MAX_CONFIRMATION_ACTIONS == 4
    assert MAX_POST_TRIGGER_ACTIONS == 16
    assert MAX_PEAK_RSS_BYTES == 1024 * 1024 * 1024
    assert MAX_TRACE_BYTES == 64 * 1024 * 1024
    assert MAX_CHECKPOINT_BYTES == 64 * 1024 * 1024


def test_content_addressed_workspaces_are_deterministic_unique_and_bounded() -> None:
    interventions = intervention_schedule()
    noise_controls = noise_control_schedule()
    checkpoints = checkpoint_schedule()

    intervention_names = tuple(_case_workspace_component(case) for case in interventions)
    noise_names = tuple(_case_workspace_component(case) for case in noise_controls)
    checkpoint_names = tuple(
        _checkpoint_workspace_component(specification) for specification in checkpoints
    )

    assert intervention_names == tuple(
        _case_workspace_component(case) for case in intervention_schedule()
    )
    assert noise_names == tuple(
        _case_workspace_component(case) for case in noise_control_schedule()
    )
    assert checkpoint_names == tuple(
        _checkpoint_workspace_component(specification) for specification in checkpoint_schedule()
    )
    assert len(set(intervention_names)) == len(interventions)
    assert len(set(noise_names)) == len(noise_controls)
    assert len(set(checkpoint_names)) == len(checkpoints)
    assert len(set((*intervention_names, *noise_names, *checkpoint_names))) == (
        len(interventions) + len(noise_controls) + len(checkpoints)
    )

    all_names = (*intervention_names, *noise_names, *checkpoint_names)
    assert all(len(name) <= _WORKSPACE_COMPONENT_MAX_CHARS for name in all_names)
    assert all(name[1] == "-" for name in all_names)
    assert all(len(name[2:]) == 32 for name in all_names)
    assert all(set(name[2:]) <= set("0123456789abcdef") for name in all_names)
    assert all(name.startswith("i-") for name in intervention_names)
    assert all(name.startswith("n-") for name in noise_names)
    assert all(name.startswith("c-") for name in checkpoint_names)

    relative_execution_roots = (
        *(Path(_INTERVENTION_WORKSPACE_DIR) / name for name in intervention_names),
        *(Path(_NOISE_WORKSPACE_DIR) / name for name in noise_names),
        *(
            Path(_CHECKPOINT_WORKSPACE_DIR) / name / branch
            for name in checkpoint_names
            for branch in (_CHECKPOINT_UNINTERRUPTED_DIR, _CHECKPOINT_RESUMED_DIR)
        ),
    )
    assert max(len(part) for path in relative_execution_roots for part in path.parts) <= (
        _WORKSPACE_COMPONENT_MAX_CHARS
    )
    assert max(len(path.as_posix()) for path in relative_execution_roots) <= 38

    attempt_02_root = DEFAULT_WORK_ROOT.with_name(f"{DEFAULT_WORK_ROOT.name}-attempt-02")
    temporary_blob_name = f".{('f' * 64)}.blob.{('f' * 32)}.tmp"

    def projected_temporary_blob(execution_root: Path) -> Path:
        return execution_root / "trace" / "blobs" / "sha256" / "ff" / temporary_blob_name

    projected_path_lengths = {
        "checkpoint-resumed": max(
            len(
                str(
                    projected_temporary_blob(
                        attempt_02_root / _CHECKPOINT_WORKSPACE_DIR / name / _CHECKPOINT_RESUMED_DIR
                    )
                )
            )
            for name in checkpoint_names
        ),
        "checkpoint-uninterrupted": max(
            len(
                str(
                    projected_temporary_blob(
                        attempt_02_root
                        / _CHECKPOINT_WORKSPACE_DIR
                        / name
                        / _CHECKPOINT_UNINTERRUPTED_DIR
                    )
                )
            )
            for name in checkpoint_names
        ),
        "intervention": max(
            len(str(projected_temporary_blob(attempt_02_root / _INTERVENTION_WORKSPACE_DIR / name)))
            for name in intervention_names
        ),
        "stationary-noise": max(
            len(str(projected_temporary_blob(attempt_02_root / _NOISE_WORKSPACE_DIR / name)))
            for name in noise_names
        ),
    }
    assert projected_path_lengths == {
        "checkpoint-resumed": 239,
        "checkpoint-uninterrupted": 239,
        "intervention": 237,
        "stationary-noise": 237,
    }
    assert max(projected_path_lengths.values()) <= _WORKSPACE_PROJECTED_PATH_MAX_CHARS


def test_schedule_workspace_wiring_preserves_full_receipt_case_ids(tmp_path: Path) -> None:
    executed_cases: list[tuple[RuleChangeCase, Path]] = []

    def fake_run_case(
        case: RuleChangeCase,
        *,
        root: Path,
        git_commit: str,
        **_: object,
    ) -> dict[str, object]:
        assert git_commit == "test-commit"
        executed_cases.append((case, root))
        return {
            "case": {"case_id": case.case_id, "family": case.family.value},
            "case_passed": True,
            "lifecycle": {
                "false_positive_event_ids": [],
                "predicates": {"candidate_resolved_as_noise": True},
            },
            "trigger_step": None,
        }

    with (
        patch(
            "scripts.measure_rule_change_reopening._run_case",
            side_effect=fake_run_case,
        ),
        patch(
            "scripts.measure_rule_change_reopening._metamorphic_groups",
            return_value={"passed": True},
        ),
    ):
        intervention = _intervention_suite(tmp_path / _INTERVENTION_WORKSPACE_DIR, "test-commit")
        noise = _noise_suite(tmp_path / _NOISE_WORKSPACE_DIR, "test-commit")

    expected_cases = (*intervention_schedule(), *noise_control_schedule())
    assert tuple(case for case, _ in executed_cases) == expected_cases
    intervention_records = cast(list[dict[str, object]], intervention["cases"])
    noise_records = cast(list[dict[str, object]], noise["cases"])
    assert tuple(
        cast(dict[str, object], item["case"])["case_id"]
        for item in (*intervention_records, *noise_records)
    ) == tuple(case.case_id for case in expected_cases)
    assert all(root.name != case.case_id for case, root in executed_cases)
    assert all(len(root.name) <= _WORKSPACE_COMPONENT_MAX_CHARS for _, root in executed_cases)

    checkpoint_roots: list[tuple[RuleChangeCheckpointCase, Path]] = []

    def fake_checkpoint_pair(
        specification: RuleChangeCheckpointCase,
        *,
        root: Path,
        git_commit: str,
    ) -> dict[str, object]:
        assert git_commit == "test-commit"
        checkpoint_roots.append((specification, root))
        case_receipt = {"case_id": specification.case_id}
        return {
            "case_id": specification.case_id,
            "failures": [],
            "pair_passed": True,
            "resumed": {"case": case_receipt},
            "uninterrupted": {"case": case_receipt},
        }

    with patch(
        "scripts.measure_rule_change_reopening._checkpoint_pair",
        side_effect=fake_checkpoint_pair,
    ):
        checkpoint = _checkpoint_suite(tmp_path / _CHECKPOINT_WORKSPACE_DIR, "test-commit")

    expected_checkpoints = checkpoint_schedule()
    assert tuple(specification for specification, _ in checkpoint_roots) == expected_checkpoints
    checkpoint_pairs = cast(list[dict[str, object]], checkpoint["pairs"])
    assert tuple(pair["case_id"] for pair in checkpoint_pairs) == tuple(
        specification.case_id for specification in expected_checkpoints
    )
    assert all(root.name != specification.case_id for specification, root in checkpoint_roots)
    assert all(len(root.name) <= _WORKSPACE_COMPONENT_MAX_CHARS for _, root in checkpoint_roots)


def test_schedule_workspace_paths_fail_closed_on_unsafe_or_colliding_names(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValueError, match="workspace address collision"):
        _schedule_workspace_paths(
            tmp_path,
            ("i-0123456789abcdef", "i-0123456789abcdef"),
            schedule_name="duplicate test schedule",
        )

    for invalid in (
        "../outside",
        f"i-{'0' * _WORKSPACE_COMPONENT_MAX_CHARS}",
    ):
        with pytest.raises(ValueError, match="invalid workspace component"):
            _schedule_workspace_paths(
                tmp_path,
                (invalid,),
                schedule_name="invalid test schedule",
            )


def test_holdout_source_bindings_reject_manifest_or_stage05_replacement() -> None:
    manifest_bytes = (ROOT / "docs/evaluation/public-game-partitions.v0.1.json").read_bytes()
    stage05_bytes = (ROOT / STAGE05_EVIDENCE_PATH).read_bytes()
    nominal = _holdout_source_bindings(
        manifest_bytes=manifest_bytes,
        stage05_bytes=stage05_bytes,
        accepted_stage05_bytes=stage05_bytes,
        accepted_stage05_blob_oid=STAGE05_EVIDENCE_BLOB_OID,
    )
    assert nominal["passed"] is True

    manifest_mutation = _holdout_source_bindings(
        manifest_bytes=manifest_bytes + b" ",
        stage05_bytes=stage05_bytes,
        accepted_stage05_bytes=stage05_bytes,
        accepted_stage05_blob_oid=STAGE05_EVIDENCE_BLOB_OID,
    )
    assert manifest_mutation["passed"] is False
    assert manifest_mutation["predicates"]["public_partition_manifest_sha256"] is False

    evidence_mutation = _holdout_source_bindings(
        manifest_bytes=manifest_bytes,
        stage05_bytes=stage05_bytes + b" ",
        accepted_stage05_bytes=stage05_bytes,
        accepted_stage05_blob_oid=STAGE05_EVIDENCE_BLOB_OID,
    )
    assert evidence_mutation["passed"] is False
    assert evidence_mutation["predicates"]["stage05_current_evidence_sha256"] is False
    assert evidence_mutation["predicates"]["stage05_current_bytes_equal_accepted_blob"] is False

    wrong_blob = _holdout_source_bindings(
        manifest_bytes=manifest_bytes,
        stage05_bytes=stage05_bytes,
        accepted_stage05_bytes=stage05_bytes,
        accepted_stage05_blob_oid="0" * 40,
    )
    assert wrong_blob["passed"] is False
    assert wrong_blob["predicates"]["stage05_acceptance_commit_blob_oid"] is False


def test_lifecycle_summary_inverse_maps_cycle_handle() -> None:
    projection = {
        "active_epoch_id": "epoch-1",
        "change_candidates": [
            {
                "opaque_handle": "ACTION2",
                "predecessor_effect_signature": "before",
                "predecessor_recovery_event_ids": [],
                "provisional_status": "CONFIRMED",
                "successor_effect_signature": "after",
                "supporting_contradiction_event_ids": ["event-1", "event-2"],
            }
        ],
        "demoted_model_ids": ["model-0"],
        "epochs": [
            {
                "active_hypothesis_ids": [],
                "active_model_ids": [],
                "epoch_id": "epoch-0",
                "epoch_index": 0,
                "parent_epoch_id": None,
                "status": "HISTORICAL",
            },
            {
                "active_hypothesis_ids": ["hypothesis-1"],
                "active_model_ids": ["model-1"],
                "epoch_id": "epoch-1",
                "epoch_index": 1,
                "parent_epoch_id": "epoch-0",
                "status": "ACTIVE",
            },
        ],
        "invalidated_plan_ids": ["plan-0"],
        "reexploration_handle": "ACTION2",
        "suspended_model_ids": [],
    }
    summary = _lifecycle_summary(projection, _case(ActionVariant.CYCLE1234))
    candidates = summary["candidates"]
    assert isinstance(candidates, list)
    assert candidates[0]["opaque_handle"] == "ACTION1"
    assert summary["reexploration_handle"] == "ACTION1"
    assert summary["active_epoch_index"] == 1


def test_nested_consequence_assessment_plan_invalidations_are_visible() -> None:
    payload = {
        "invalidated_plan_ids": ["plan:direct"],
        "reopenings": [
            {"invalidated_plan_ids": ["plan:nested"]},
            {"invalidated_plan_ids": []},
        ],
    }
    assert _invalidated_plan_ids(payload) == {"plan:direct", "plan:nested"}


def test_stale_authority_is_evaluated_at_event_time_not_from_final_union() -> None:
    timeline: tuple[tuple[str, dict[str, object]], ...] = (
        ("model.rule_demoted", {"model_id": "world-model:old"}),
        ("hypothesis.reopened", {"hypothesis_id": "H-OLD"}),
        ("mechanics.epoch_opened", {}),
        (
            "action.selected",
            {
                "active_hypothesis_ids": ["H-OLD"],
                "selected_probe_or_plan_id": "plan:new",
            },
        ),
        (
            "consequence.mismatched_prediction",
            {"reopenings": [{"invalidated_plan_ids": ["plan:new"]}]},
        ),
        (
            "simulation.prediction_emitted",
            {
                "alternatives": [{"supporting_model_ids": ["world-model:old"]}],
                "dependent_plan_ids": ["plan:new"],
            },
        ),
    )
    stale_models, stale_plans, stale_hypotheses = _stale_authority_uses(
        timeline, epoch_open_index=2
    )
    assert stale_models == ["world-model:old"]
    assert stale_plans == ["plan:new"]
    assert stale_hypotheses == ["H-OLD"]


def test_stale_authority_is_forbidden_before_successor_epoch_opens() -> None:
    timeline: tuple[tuple[str, dict[str, object]], ...] = (
        (
            "mechanics.change_candidate_created",
            {
                "affected_model_ids": ["world-model:old"],
                "invalidated_plan_ids": ["plan:old"],
            },
        ),
        (
            "simulation.prediction_emitted",
            {
                "alternatives": [{"supporting_model_ids": ["world-model:old"]}],
                "dependent_plan_ids": ["plan:old"],
            },
        ),
        ("hypothesis.reopened", {"hypothesis_id": "H-OLD"}),
        (
            "action.selected",
            {
                "active_hypothesis_ids": ["H-OLD"],
                "active_world_model_ids": ["world-model:old"],
                "selected_probe_or_plan_id": "plan:old",
            },
        ),
        ("mechanics.epoch_opened", {}),
    )
    stale_models, stale_plans, stale_hypotheses = _stale_authority_uses(
        timeline, epoch_open_index=4
    )
    assert stale_models == ["world-model:old", "world-model:old"]
    assert stale_plans == ["plan:old", "plan:old"]
    assert stale_hypotheses == ["H-OLD"]


def _valid_lifecycle_timeline() -> list[dict[str, object]]:
    candidate = {
        "affected_hypothesis_ids": ["H-OLD"],
        "affected_model_ids": ["world-model:old"],
        "candidate_id": "mechanics-change:one",
        "change_domain": "ACTION_MAPPING",
        "first_contradiction_event_id": "E-C1",
        "invalidated_plan_ids": ["plan:old"],
        "last_tested_step": 6,
        "level_index": 0,
        "opaque_handle": "ACTION1",
        "opened_step": 6,
        "predecessor_effect_signature": "sha256:" + "1" * 64,
        "predecessor_epoch_id": "mechanics-epoch:L0:0000",
        "predecessor_recovery_event_ids": [],
        "provisional_status": "CANDIDATE",
        "successor_effect_signature": "sha256:" + "2" * 64,
        "supporting_contradiction_event_ids": ["E-C1"],
        "supporting_discrimination_context_ids": ["opaque-handle:ACTION1"],
        "supporting_successor_transition_ids": ["transition:one"],
        "source_transition_id": "transition:one",
    }
    confirmed = {
        **candidate,
        "last_tested_step": 8,
        "provisional_status": "CONFIRMED",
        "supporting_contradiction_event_ids": ["E-C1", "E-C2"],
        "supporting_discrimination_context_ids": [
            "opaque-handle:ACTION1",
            "opaque-handle:ACTION2",
        ],
        "supporting_successor_transition_ids": ["transition:one", "transition:two"],
        "source_transition_id": "transition:two",
    }
    return [
        {
            "event_id": "E-A0",
            "event_type": "action.selected",
            "level_index": 0,
            "payload": {"mechanics_epoch_id": "mechanics-epoch:L0:0000"},
        },
        {
            "event_id": "E-H0",
            "event_type": "hypothesis.created",
            "level_index": 0,
            "payload": {
                "hypothesis_id": "H-OLD",
                "mechanics_epoch_id": "mechanics-epoch:L0:0000",
            },
        },
        {
            "event_id": "E-M0",
            "event_type": "model.rule_promoted",
            "level_index": 0,
            "payload": {
                "model_id": "world-model:old",
                "mechanics_epoch_id": "mechanics-epoch:L0:0000",
            },
        },
        {
            "event_id": "E-CREATED",
            "event_type": "mechanics.change_candidate_created",
            "level_index": 0,
            "payload": candidate,
        },
        {
            "event_id": "E-SUPPORT-1",
            "event_type": "mechanics.successor_evidence_supported",
            "level_index": 0,
            "step_index": 6,
            "payload": {
                "candidate_id": "mechanics-change:one",
                "contradiction_event_id": "E-C1",
                "discrimination_context_id": "opaque-handle:ACTION1",
                "source_transition_id": "transition:one",
                "support_index": 1,
            },
        },
        {
            "event_id": "E-SUPPORT-2",
            "event_type": "mechanics.successor_evidence_supported",
            "level_index": 0,
            "step_index": 8,
            "payload": {
                "candidate_id": "mechanics-change:one",
                "contradiction_event_id": "E-C2",
                "discrimination_context_id": "opaque-handle:ACTION2",
                "source_transition_id": "transition:two",
                "support_index": 2,
            },
        },
        {
            "event_id": "E-DEMOTED",
            "event_type": "model.rule_demoted",
            "level_index": 0,
            "payload": {
                "change_candidate_id": "mechanics-change:one",
                "model_id": "world-model:old",
            },
        },
        {
            "event_id": "E-CONFIRMED",
            "event_type": "mechanics.change_confirmed",
            "level_index": 0,
            "payload": confirmed,
        },
        {
            "event_id": "E-OPENED",
            "event_type": "mechanics.epoch_opened",
            "level_index": 0,
            "payload": {
                "caused_by_change_candidate_id": "mechanics-change:one",
                "epoch_id": "mechanics-epoch:L0:0001",
                "epoch_index": 1,
                "level_index": 0,
                "parent_epoch_id": "mechanics-epoch:L0:0000",
                "start_transition_id": "transition:one",
                "status": "ACTIVE",
            },
        },
        {
            "event_id": "E-H1",
            "event_type": "hypothesis.created",
            "level_index": 0,
            "payload": {
                "hypothesis_id": "H-NEW",
                "mechanics_epoch_id": "mechanics-epoch:L0:0001",
            },
        },
        {
            "event_id": "E-M1",
            "event_type": "model.rule_promoted",
            "level_index": 0,
            "payload": {
                "model_id": "world-model:new",
                "mechanics_epoch_id": "mechanics-epoch:L0:0001",
            },
        },
    ]


def test_lifecycle_event_fold_rebuilds_without_final_projection_authority() -> None:
    folded, failures = _fold_lifecycle_timeline(_valid_lifecycle_timeline())
    assert failures == []
    assert folded["active_epoch_id"] == "mechanics-epoch:L0:0001"
    assert folded["demoted_model_ids"] == ["world-model:old"]
    candidates = folded["change_candidates"]
    assert isinstance(candidates, list)
    assert candidates[0]["provisional_status"] == "CONFIRMED"


@pytest.mark.parametrize(
    ("mutation", "expected_failure"),
    (
        ("missing-support", "terminal support arrays disagree"),
        ("duplicate-index", "indices are not contiguous"),
        ("noncontiguous-index", "indices are not contiguous"),
        ("terminal-only", "terminal event lacks a creation event"),
        ("context-reordered", "terminal support arrays disagree"),
        ("creation-source-mismatch", "does not bind support index zero"),
    ),
)
def test_lifecycle_event_fold_rejects_unlinked_or_reordered_support(
    mutation: str,
    expected_failure: str,
) -> None:
    timeline = deepcopy(_valid_lifecycle_timeline())
    created = next(
        event for event in timeline if event["event_type"] == "mechanics.change_candidate_created"
    )
    confirmed = next(
        event for event in timeline if event["event_type"] == "mechanics.change_confirmed"
    )
    supports = [
        event
        for event in timeline
        if event["event_type"] == "mechanics.successor_evidence_supported"
    ]
    if mutation == "missing-support":
        timeline.remove(supports[1])
    elif mutation == "duplicate-index":
        cast(dict[str, object], supports[1]["payload"])["support_index"] = 1
    elif mutation == "noncontiguous-index":
        cast(dict[str, object], supports[1]["payload"])["support_index"] = 3
    elif mutation == "terminal-only":
        timeline.remove(created)
    elif mutation == "context-reordered":
        payload = cast(dict[str, object], confirmed["payload"])
        contexts = cast(list[str], payload["supporting_discrimination_context_ids"])
        contexts.reverse()
    else:
        cast(dict[str, object], created["payload"])["source_transition_id"] = "transition:invented"

    _folded, failures = _fold_lifecycle_timeline(timeline)
    assert any(expected_failure in failure for failure in failures)


def test_lifecycle_event_fold_preserves_recovery_arrival_order_and_rejects_reorder() -> None:
    source = _valid_lifecycle_timeline()
    created = deepcopy(
        next(
            event for event in source if event["event_type"] == "mechanics.change_candidate_created"
        )
    )
    first_support = deepcopy(
        next(
            event
            for event in source
            if event["event_type"] == "mechanics.successor_evidence_supported"
        )
    )
    opening_events = [
        deepcopy(event)
        for event in source
        if event["event_type"] in {"action.selected", "hypothesis.created", "model.rule_promoted"}
        and event["event_id"] in {"E-A0", "E-H0", "E-M0"}
    ]
    recovery_ids = ("E-RECOVERY-Z", "E-RECOVERY-A")
    recoveries = [
        {
            "event_id": event_id,
            "event_type": "mechanics.predecessor_recovery_supported",
            "level_index": 0,
            "step_index": support_index + 6,
            "payload": {
                "candidate_id": "mechanics-change:one",
                "support_index": support_index,
            },
        }
        for support_index, event_id in enumerate(recovery_ids, start=1)
    ]
    resolved_payload = deepcopy(cast(dict[str, object], created["payload"]))
    resolved_payload["last_tested_step"] = 8
    resolved_payload["predecessor_recovery_event_ids"] = list(recovery_ids)
    resolved_payload["provisional_status"] = "RESOLVED_NOISE"
    resolved = {
        "event_id": "E-RESOLVED",
        "event_type": "mechanics.change_candidate_resolved",
        "level_index": 0,
        "step_index": 8,
        "payload": resolved_payload,
    }
    timeline = [*opening_events, created, first_support, *recoveries, resolved]

    folded, failures = _fold_lifecycle_timeline(timeline)
    assert failures == []
    candidates = cast(list[dict[str, object]], folded["change_candidates"])
    assert candidates[0]["predecessor_recovery_event_ids"] == list(recovery_ids)

    tampered = deepcopy(timeline)
    terminal = cast(dict[str, object], tampered[-1]["payload"])
    cast(list[str], terminal["predecessor_recovery_event_ids"]).reverse()
    _folded, failures = _fold_lifecycle_timeline(tampered)
    assert "mechanics candidate terminal recoveries disagree with receipts" in failures


def test_lifecycle_event_fold_rejects_tampered_epoch_without_confirmation() -> None:
    tampered = [
        event
        for event in _valid_lifecycle_timeline()
        if event["event_type"] != "mechanics.change_confirmed"
    ]
    _folded, failures = _fold_lifecycle_timeline(tampered)
    assert "opened epoch lacks a confirmed causal candidate" in failures


def test_lifecycle_fold_distinguishes_persistent_plan_invalidations() -> None:
    timeline: list[dict[str, object]] = [
        {
            "event_id": "E-PLAN",
            "event_type": "simulation.plan_evaluated",
            "level_index": 0,
            "payload": {"goal_id": "goal:contact", "plan_id": "plan:contact"},
        },
        {
            "event_id": "E-SELECT",
            "event_type": "action.selected",
            "level_index": 0,
            "payload": {
                "mechanics_epoch_id": "mechanics-epoch:L0:0000",
                "selected_probe_or_plan_id": "plan:contact",
            },
        },
        {
            "event_id": "E-MISMATCH",
            "event_type": "consequence.mismatched_prediction",
            "level_index": 0,
            "payload": {"reopenings": [{"invalidated_plan_ids": ["plan:transient"]}]},
        },
        {
            "event_id": "E-PROBE",
            "event_type": "action.selected",
            "level_index": 0,
            "payload": {
                "mechanics_epoch_id": "mechanics-epoch:L0:0000",
                "selected_probe_or_plan_id": "probe:follow-up",
            },
        },
        {
            "event_id": "E-RETIRE",
            "event_type": "goal.retired",
            "level_index": 0,
            "payload": {
                "goal_id": "goal:contact",
                "summary": "contact target changed after mover reached its prior observed cells",
            },
        },
        {
            "event_id": "E-INVALIDATE",
            "event_type": "simulation.plan_invalidated",
            "level_index": 0,
            "payload": {
                "plan_ids": ["plan:contact"],
                "reason": "contact target changed after observed progress",
                "source_goal_id": "goal:contact",
            },
        },
        {
            "event_id": "E-CANDIDATE",
            "event_type": "mechanics.change_candidate_created",
            "level_index": 0,
            "payload": {
                "candidate_id": "mechanics-change:one",
                "first_contradiction_event_id": "E-C1",
                "invalidated_plan_ids": ["plan:mechanics"],
                "predecessor_epoch_id": "mechanics-epoch:L0:0000",
                "provisional_status": "CANDIDATE",
                "supporting_contradiction_event_ids": ["E-C1"],
                "supporting_discrimination_context_ids": ["opaque-handle:ACTION1"],
                "supporting_successor_transition_ids": ["transition:one"],
                "source_transition_id": "transition:one",
            },
        },
        {
            "event_id": "E-SUPPORT",
            "event_type": "mechanics.successor_evidence_supported",
            "level_index": 0,
            "payload": {
                "candidate_id": "mechanics-change:one",
                "contradiction_event_id": "E-C1",
                "discrimination_context_id": "opaque-handle:ACTION1",
                "source_transition_id": "transition:one",
                "support_index": 1,
            },
        },
    ]
    folded, failures = _fold_lifecycle_timeline(timeline)
    assert failures == []
    assert folded["invalidated_plan_ids"] == ["plan:contact", "plan:mechanics"]


def test_lifecycle_fold_does_not_infer_plan_invalidation_from_goal_narrative() -> None:
    timeline: list[dict[str, object]] = [
        {
            "event_id": "E-PLAN",
            "event_type": "simulation.plan_evaluated",
            "level_index": 0,
            "payload": {"goal_id": "goal:contact", "plan_id": "plan:contact"},
        },
        {
            "event_id": "E-SELECT",
            "event_type": "action.selected",
            "level_index": 0,
            "payload": {
                "mechanics_epoch_id": "mechanics-epoch:L0:0000",
                "selected_probe_or_plan_id": "plan:contact",
            },
        },
        {
            "event_id": "E-RETIRE",
            "event_type": "goal.retired",
            "level_index": 0,
            "payload": {
                "goal_id": "goal:contact",
                "summary": "contact target changed after mover reached its prior observed cells",
            },
        },
    ]
    folded, failures = _fold_lifecycle_timeline(timeline)
    assert failures == []
    assert folded["invalidated_plan_ids"] == []


def test_top_level_status_classifier_preserves_all_four_frozen_labels() -> None:
    no_mechanism_failure = {"example": False}
    assert (
        _classify_stage_status(
            acceptance_passed=True,
            failed_mechanism_predicates=no_mechanism_failure,
            infrastructure_failure_count=0,
        )
        == "PASS"
    )
    assert (
        _classify_stage_status(
            acceptance_passed=False,
            failed_mechanism_predicates=no_mechanism_failure,
            infrastructure_failure_count=0,
        )
        == "PARTIAL"
    )
    assert (
        _classify_stage_status(
            acceptance_passed=False,
            failed_mechanism_predicates={"stale_authority_retained": True},
            infrastructure_failure_count=0,
        )
        == "FAILED_MECHANISM"
    )
    assert (
        _classify_stage_status(
            acceptance_passed=False,
            failed_mechanism_predicates={"resource_limit_missed": False},
            infrastructure_failure_count=1,
        )
        == "FAILED_INFRASTRUCTURE"
    )


def test_checkpoint_preparation_failure_is_counted_as_infrastructure_not_placeholder() -> None:
    checkpoint = {
        "pairs": [
            {
                "failures": [
                    {
                        "kind": "FileNotFoundError",
                        "message": "checkpoint root unavailable",
                    }
                ],
                "resumed": {},
                "uninterrupted": {},
            }
        ]
    }
    intervention = {"cases": []}
    noise = {"cases": []}
    aggregate = _aggregate_measurements(intervention, noise, checkpoint)
    assert aggregate["planned_controller_execution_count"] == 2
    assert aggregate["controller_execution_count"] == 0
    assert aggregate["shared_prefix_preparation_failure_count"] == 1
    assert aggregate["failure_count"] == 1
    assert _infrastructure_failure_count(intervention, noise, checkpoint) == 1
    assert (
        _classify_stage_status(
            acceptance_passed=False,
            failed_mechanism_predicates={"mechanism": False},
            infrastructure_failure_count=_infrastructure_failure_count(
                intervention, noise, checkpoint
            ),
        )
        == "FAILED_INFRASTRUCTURE"
    )

    invalid_checkpoint = {
        "pairs": [
            {
                "failures": [
                    {
                        "kind": "InvalidActionError",
                        "message": "shared-prefix action was invalid",
                    }
                ],
                "resumed": {},
                "uninterrupted": {},
            }
        ]
    }
    invalid_aggregate = _aggregate_measurements(intervention, noise, invalid_checkpoint)
    assert invalid_aggregate["invalid_request_count"] == 1
    assert _infrastructure_failure_count(intervention, noise, invalid_checkpoint) == 0

    timed_out_checkpoint = {
        "pairs": [
            {
                "failures": [
                    {
                        "kind": "TimeoutExpired",
                        "message": "controller execution exceeded its declared bound",
                    }
                ],
                "resumed": {},
                "uninterrupted": {},
            }
        ]
    }
    assert _infrastructure_failure_count(intervention, noise, timed_out_checkpoint) == 0


def _nominal_classifier_suites() -> tuple[dict[str, object], dict[str, object]]:
    interventions: list[dict[str, object]] = []
    for case in intervention_schedule():
        interventions.append(
            {
                "case": {
                    "action_variant": case.action_variant.value,
                    "family": case.family.value,
                    "palette_variant": case.palette_variant.value,
                    "seed": case.seed,
                    "timing": case.timing.value,
                },
                "final_evaluator_projection": {"mechanics_epoch": 1},
                "lifecycle": {
                    "predicates": {
                        "completion_within_post_trigger_budget": True,
                        "ordered_lifecycle_chain": True,
                        "pulse_resolved": True,
                        "stale_model_absent": True,
                        "stale_plan_absent": True,
                        "stale_predecessor_hypothesis_absent": True,
                        "successor_epoch_retained": True,
                    }
                },
                "trace": {
                    "observation_blinding": {"passed": True},
                    "prefix_immutability": {"passed": True},
                },
                "trigger_step": 6,
            }
        )
    noise: list[dict[str, object]] = []
    for case in noise_control_schedule():
        noise.append(
            {
                "case": {
                    "action_variant": case.action_variant.value,
                    "family": case.family.value,
                    "palette_variant": case.palette_variant.value,
                    "seed": case.seed,
                    "timing": case.timing.value,
                },
                "final_evaluator_projection": {"mechanics_epoch": 0},
                "trace": {"observation_blinding": {"passed": True}},
            }
        )
    return {"cases": interventions}, {"cases": noise, "false_positive_reopenings": 0}


def test_failed_mechanism_classifier_matches_frozen_predicates() -> None:
    intervention, noise = _nominal_classifier_suites()
    nominal = _failed_mechanism_predicates(intervention, noise, {"passed": True})
    assert not any(nominal.values())

    missing = deepcopy(intervention)
    cases = missing["cases"]
    assert isinstance(cases, list)
    cases.pop()
    assert _failed_mechanism_predicates(missing, noise, {"passed": True})[
        "required_seed_transform_exposure_missing"
    ]

    stale = deepcopy(intervention)
    stale_cases = stale["cases"]
    assert isinstance(stale_cases, list)
    first = stale_cases[0]
    assert isinstance(first, dict)
    lifecycle = first["lifecycle"]
    assert isinstance(lifecycle, dict)
    predicates = lifecycle["predicates"]
    assert isinstance(predicates, dict)
    predicates["stale_model_absent"] = False
    assert _failed_mechanism_predicates(stale, noise, {"passed": True})[
        "stale_authority_retained_after_reopening"
    ]

    false_positive_noise = {**noise, "false_positive_reopenings": 1}
    assert _failed_mechanism_predicates(intervention, false_positive_noise, {"passed": True})[
        "single_stationary_outlier_confirmed_epoch"
    ]
    assert _failed_mechanism_predicates(intervention, noise, {"passed": False})[
        "action_or_game_identity_leaked"
    ]


def test_bound_verification_receipt_preserves_exact_command_output(tmp_path: Path) -> None:
    receipt = _run_verification_command(
        check_id="unit-command",
        command=(sys.executable, "-c", "print('receipt-ok')"),
        output_root=tmp_path,
        timeout_seconds=10.0,
    )
    artifact = Path(str(receipt["artifact_path"]))
    assert receipt["passed"] is True
    assert receipt["exit_code"] == 0
    assert receipt["stdout"] == "receipt-ok\n"
    assert artifact.is_file()
    assert receipt["artifact_sha256"] == sha256_file(artifact)


def test_verification_timeout_is_not_relabelled_as_infrastructure(
    tmp_path: Path,
) -> None:
    receipt = _run_verification_command(
        check_id="unit-timeout",
        command=(sys.executable, "-c", "import time; time.sleep(5)"),
        output_root=tmp_path,
        timeout_seconds=0.05,
    )
    assert receipt["passed"] is False
    assert receipt["timed_out"] is True
    assert receipt["infrastructure_failure"] is False
    assert (
        _classify_stage_status(
            acceptance_passed=False,
            failed_mechanism_predicates={"mechanism": False},
            infrastructure_failure_count=0,
        )
        == "PARTIAL"
    )


def test_focused_verification_binds_lifecycle_checkpoint_and_replay_regressions() -> None:
    assert set(_FOCUSED_VERIFICATION_TESTS) == {
        "tests/unit/test_rule_change_fixture.py",
        "tests/unit/test_measure_rule_change.py",
        "tests/unit/test_mechanics_lifecycle.py",
        "tests/integration/test_rule_change_reopening.py",
        "tests/integration/test_memory_checkpoint_resume.py",
        "tests/replay/test_controller_checkpoint.py",
    }


def test_verification_pytest_basetemp_is_short_and_overrideable(tmp_path: Path) -> None:
    default = _verification_pytest_basetemp({})
    overridden = _verification_pytest_basetemp({"ARC3_STAGE06_PYTEST_BASETEMP": str(tmp_path)})
    assert default.name == "arc3-stage06-verification"
    assert "artifacts" not in default.parts
    assert overridden == tmp_path.resolve()


def test_global_action_confirmation_rejects_same_handle_repetition() -> None:
    created = {
        "candidate_id": "mechanics-change:one",
        "change_domain": "ACTION_MAPPING",
        "predecessor_effect_signature": "sha256:" + "1" * 64,
        "successor_effect_signature": "sha256:" + "2" * 64,
    }
    confirmation = {
        **created,
        "provisional_status": "CONFIRMED",
        "supporting_contradiction_event_ids": ["E-C1", "E-C2"],
        "supporting_successor_transition_ids": ["transition:one", "transition:two"],
        "supporting_discrimination_context_ids": [
            "opaque-handle:ACTION1",
            "opaque-handle:ACTION1",
        ],
    }
    assert not _coherent_candidate_confirmation(created, confirmation)
    confirmation["supporting_discrimination_context_ids"] = [
        "opaque-handle:ACTION1",
        "opaque-handle:ACTION2",
    ]
    assert _coherent_candidate_confirmation(created, confirmation)


def _selected(
    event_id: str,
    action_name: str,
    *,
    step: int,
    epoch_id: str,
    probe_or_plan_id: str,
    reexploration: bool,
    decision_id: str,
) -> TraceEvent:
    return _event(
        event_id,
        "action.selected",
        {
            "active_hypothesis_ids": [],
            "candidate_utilities": [],
            "decision_id": decision_id,
            "mechanics_epoch_id": epoch_id,
            "predicted_outcome_ids": [],
            "rationale_category": "reexploration" if reexploration else "follow_plan",
            "reexploration": reexploration,
            "selected_action": {"coordinate": None, "name": action_name},
            "selected_probe_or_plan_id": probe_or_plan_id,
        },
        step=step,
    )


def _observation(event_id: str, action_name: str, *, step: int) -> TraceEvent:
    return _event(
        event_id,
        "observation.received",
        {
            "available_actions": ["ACTION1", "ACTION2", "ACTION3", "ACTION4"],
            "frame_count": 1,
            "frames": [
                {
                    "blob_hash": "sha256:" + f"{step % 10}" * 64,
                    "frame_hash": "sha256:" + f"{step % 10}" * 64,
                    "height": 1,
                    "palette": [0],
                    "width": 1,
                }
            ],
            "game_state": "NOT_FINISHED",
            "returned_action": {"coordinate": None, "name": action_name},
            "score": None,
            "upstream_metadata": {},
        },
        step=step,
    )


def _lifecycle_trace(
    *,
    absent_second_confirmation_source: bool = False,
    destination_role: bool = False,
    unrelated_role_statement: bool = False,
    unrelated_successor_hypothesis: bool = False,
    unrelated_model_matches: bool = False,
) -> tuple[TraceEvent, ...]:
    predecessor_epoch = "mechanics-epoch:L0:0000"
    successor_epoch = "mechanics-epoch:L0:0001"
    candidate_id = "mechanics-change:one"
    moving_kind = "palette-role:mover"
    obstacle_kind = "palette-role:terrain"
    change_domain = "DESTINATION_ROLE" if destination_role else "ACTION_MAPPING"
    predecessor_signature = (
        sha256_json(
            {
                "domain": "DESTINATION_ROLE",
                "moving_kind": moving_kind,
                "obstacle_kind": obstacle_kind,
                "traversable": False,
            }
        )
        if destination_role
        else "sha256:" + "1" * 64
    )
    successor_signature = (
        sha256_json(
            {
                "domain": "DESTINATION_ROLE",
                "moving_kind": moving_kind,
                "obstacle_kind": obstacle_kind,
                "traversable": True,
            }
        )
        if destination_role
        else "sha256:" + "2" * 64
    )
    condition_signature = (
        sha256_json(
            {
                "domain": "DESTINATION_ROLE",
                "width": 1,
                "height": 1,
                "moving_kind": moving_kind,
                "obstacle_kind": obstacle_kind,
            }
        )
        if destination_role
        else "condition:" + "3" * 64
    )
    affected_hypotheses = ("H-OLD", "H-OLD-2")
    affected_models = ("world-model:old", "world-model:old-2")
    contexts = (
        (sha256_json({"destination": 1}), sha256_json({"destination": 2}))
        if destination_role
        else ("opaque-handle:ACTION1", "opaque-handle:ACTION2")
    )
    contradiction_ids = (
        "E-CONTRADICTION-1",
        "E-ABSENT" if absent_second_confirmation_source else "E-CONTRADICTION-2",
    )
    transition_ids = ("transition:E-SUBMITTED-1", "transition:E-SUBMITTED-2")
    candidate = {
        "affected_hypothesis_ids": list(affected_hypotheses),
        "affected_model_ids": list(affected_models),
        "candidate_id": candidate_id,
        "change_domain": change_domain,
        "first_contradiction_event_id": contradiction_ids[0],
        "invalidated_plan_ids": ["plan:old"],
        "observation_condition_signature": condition_signature,
        "opaque_handle": "ACTION1",
        "predecessor_effect_signature": predecessor_signature,
        "predecessor_epoch_id": predecessor_epoch,
        "provisional_status": "CANDIDATE",
        "source_consequence_event_id": "E-CONSEQUENCE-1",
        "source_transition_id": transition_ids[0],
        "successor_effect_signature": successor_signature,
        "supporting_contradiction_event_ids": [contradiction_ids[0]],
        "supporting_discrimination_context_ids": [contexts[0]],
        "supporting_successor_transition_ids": [transition_ids[0]],
    }
    confirmed = {
        **candidate,
        "provisional_status": "CONFIRMED",
        "source_transition_id": transition_ids[1],
        "supporting_contradiction_event_ids": list(contradiction_ids),
        "supporting_discrimination_context_ids": list(contexts),
        "supporting_successor_transition_ids": list(transition_ids),
    }
    events: list[TraceEvent] = []
    for support_index, action_name in enumerate(("ACTION1", "ACTION2"), start=1):
        action_step = support_index + 4
        evidence_step = action_step + 1
        selected_id = f"E-SELECTED-{support_index}"
        submitted_id = f"E-SUBMITTED-{support_index}"
        consequence_id = f"E-CONSEQUENCE-{support_index}"
        observation_id = f"E-OBSERVATION-{support_index}"
        contradiction_id = f"E-CONTRADICTION-{support_index}"
        action = {"coordinate": None, "name": action_name}
        events.extend(
            (
                _selected(
                    selected_id,
                    action_name,
                    step=action_step,
                    epoch_id=predecessor_epoch,
                    probe_or_plan_id=("plan:old" if support_index == 1 else candidate_id),
                    reexploration=False,
                    decision_id=f"decision:{support_index}",
                ),
                _event(
                    submitted_id,
                    "action.submitted",
                    {
                        "action": action,
                        "decision_id": f"decision:{support_index}",
                        "selected_event_id": selected_id,
                    },
                    step=action_step,
                ),
                _event(
                    consequence_id,
                    "consequence.received",
                    {
                        "action": action,
                        "returned_action": action,
                        "selected_event_id": selected_id,
                        "submitted_action": action,
                        "submitted_event_id": submitted_id,
                    },
                    step=action_step,
                ),
                _observation(observation_id, action_name, step=evidence_step),
                _event(
                    f"E-NORMALIZED-{support_index}",
                    "observation.normalized",
                    {
                        "frame_hash": "sha256:" + "4" * 64,
                        "height": 1,
                        "source_observation_event_id": observation_id,
                        "width": 1,
                    },
                    step=evidence_step,
                ),
                _event(
                    f"E-CONTROLLED-{support_index}",
                    "action.controlled_effect_interpreted",
                    {
                        "controlled_canonical_effect": {
                            "effect_kind": "translation",
                            "translation": [1, 0],
                        },
                        "mechanics_epoch_id": predecessor_epoch,
                        "source_consequence_event_id": consequence_id,
                        "source_transition_id": transition_ids[support_index - 1],
                    },
                    step=evidence_step,
                ),
                _event(
                    contradiction_id,
                    "hypothesis.contradicted",
                    {
                        "caused_by_event_ids": [consequence_id],
                        "evidence_event_ids": [consequence_id],
                        "evidence_receipt": {
                            "evidence_event_ids": [consequence_id],
                            "kind": "contradiction",
                        },
                        "hypothesis_id": affected_hypotheses[0],
                        "mechanics_epoch_id": predecessor_epoch,
                    },
                    step=evidence_step,
                ),
            )
        )
        if support_index == 1:
            events.append(
                _event(
                    "E-CANDIDATE",
                    "mechanics.change_candidate_created",
                    candidate,
                    step=evidence_step,
                )
            )
        events.append(
            _event(
                f"E-SUCCESSOR-SUPPORT-{support_index}",
                "mechanics.successor_evidence_supported",
                {
                    "action": action,
                    "affected_hypothesis_ids": list(affected_hypotheses),
                    "candidate_id": candidate_id,
                    "change_domain": change_domain,
                    "contradiction_event_id": (contradiction_ids[support_index - 1]),
                    "discrimination_context_id": contexts[support_index - 1],
                    "interpretation": "successor-consistent contradiction consequence",
                    "observation_condition_signature": condition_signature,
                    "observed_effect_signature": successor_signature,
                    "opaque_handle": "ACTION1",
                    "predecessor_epoch_id": predecessor_epoch,
                    "raw_action_handle": action_name,
                    "source_action_selected_event_id": selected_id,
                    "source_action_submitted_event_id": submitted_id,
                    "source_consequence_event_id": consequence_id,
                    "source_observation_event_id": observation_id,
                    "source_transition_id": transition_ids[support_index - 1],
                    "support_index": support_index,
                },
                step=evidence_step,
            )
        )
    events.append(
        _event(
            "E-DEMOTED",
            "model.rule_demoted",
            {
                "change_candidate_id": candidate_id,
                "hypothesis_ids": list(affected_hypotheses),
                "invalidated_plan_ids": ["plan:old"],
                "mechanics_epoch_id": predecessor_epoch,
                "model_ids": list(affected_models),
                "new_status": "demoted",
                "supporting_contradiction_event_ids": list(contradiction_ids),
            },
            step=7,
        )
    )
    for reopening_index, hypothesis_id in enumerate(affected_hypotheses, start=1):
        events.append(
            _event(
                f"E-REOPENED-{reopening_index}",
                "hypothesis.reopened",
                {
                    "caused_by_event_ids": list(contradiction_ids),
                    "change_candidate_id": candidate_id,
                    "evidence_event_ids": list(contradiction_ids),
                    "hypothesis_id": hypothesis_id,
                    "invalidated_plan_ids": ["plan:old"],
                    "mechanics_epoch_id": predecessor_epoch,
                    "new_status": "candidate",
                    "receipt": {
                        "evidence_event_ids": list(contradiction_ids),
                        "kind": "contradiction",
                    },
                },
                step=7,
            )
        )
    events.extend(
        (
            _event(
                "E-CONFIRMED",
                "mechanics.change_confirmed",
                confirmed,
                step=7,
            ),
            _event(
                "E-OPENED",
                "mechanics.epoch_opened",
                {
                    "caused_by_change_candidate_id": candidate_id,
                    "epoch_id": successor_epoch,
                    "parent_epoch_id": predecessor_epoch,
                },
                step=7,
            ),
        )
    )
    successor_probe_id = (
        "mechanics-change:unrelated" if unrelated_successor_hypothesis else candidate_id
    )
    successor_action = {"coordinate": None, "name": "ACTION3"}
    successor_family = "collision_traversability" if destination_role else "action_semantics"
    successor_statement = (
        {
            "conditions": [],
            "consequence": "entered",
            "moving_kind": moving_kind,
            "obstacle_kind": (
                "palette-role:unrelated" if unrelated_role_statement else obstacle_kind
            ),
            "traversable": True,
        }
        if destination_role
        else {
            "action": "ACTION3",
            "effect": "translation",
            "parameters": {"dx": 1, "dy": 0},
        }
    )
    events.extend(
        (
            _selected(
                "E-REEXPLORE",
                "ACTION3",
                step=8,
                epoch_id=successor_epoch,
                probe_or_plan_id=successor_probe_id,
                reexploration=True,
                decision_id="decision:successor",
            ),
            _event(
                "E-SUCCESSOR-SUBMITTED",
                "action.submitted",
                {
                    "action": successor_action,
                    "decision_id": "decision:successor",
                    "selected_event_id": "E-REEXPLORE",
                },
                step=8,
            ),
            _event(
                "E-SUCCESSOR-CONSEQUENCE",
                "consequence.received",
                {
                    "action": successor_action,
                    "returned_action": successor_action,
                    "selected_event_id": "E-REEXPLORE",
                    "submitted_action": successor_action,
                    "submitted_event_id": "E-SUCCESSOR-SUBMITTED",
                },
                step=8,
            ),
            _observation("E-SUCCESSOR-OBSERVATION", "ACTION3", step=9),
            _event(
                "E-SUCCESSOR-CONTROLLED",
                "action.controlled_effect_interpreted",
                {
                    "controlled_canonical_effect": {
                        "effect_kind": "translation",
                        "translation": [1, 0],
                    },
                    "mechanics_epoch_id": successor_epoch,
                    "source_consequence_event_id": "E-SUCCESSOR-CONSEQUENCE",
                    "source_transition_id": "transition:E-SUCCESSOR-SUBMITTED",
                },
                step=9,
            ),
            _event(
                "E-SUCCESSOR-H-CREATED",
                "hypothesis.created",
                {
                    "created_from_event_ids": [
                        "E-REEXPLORE",
                        "E-SUCCESSOR-SUBMITTED",
                        "E-SUCCESSOR-CONSEQUENCE",
                        "E-SUCCESSOR-OBSERVATION",
                    ],
                    "family": successor_family,
                    "hypothesis_id": "H-SUCCESSOR",
                    "hypothesis_type": successor_family,
                    "mechanics_epoch_id": successor_epoch,
                    "statement": successor_statement,
                },
                step=9,
            ),
            _event(
                "E-SUCCESSOR-H-SUPPORTED",
                "hypothesis.supported",
                {
                    "caused_by_event_ids": ["E-SUCCESSOR-CONSEQUENCE"],
                    "evidence_event_ids": ["E-SUCCESSOR-CONSEQUENCE"],
                    "evidence_receipt": {"evidence_event_ids": ["E-SUCCESSOR-CONSEQUENCE"]},
                    "hypothesis_id": "H-SUCCESSOR",
                    "mechanics_epoch_id": successor_epoch,
                },
                step=9,
            ),
            _event(
                "E-SUCCESSOR-PROMOTED",
                "model.rule_promoted",
                {
                    "hypothesis_ids": ["H-SUCCESSOR"],
                    "mechanics_epoch_id": successor_epoch,
                    "model_id": "world-model:successor",
                },
                step=9,
            ),
        )
    )
    matched_prediction = "prediction:unrelated" if unrelated_model_matches else "prediction:good"
    model_prediction = "prediction:wrong" if unrelated_model_matches else "prediction:good"
    final_action = {"coordinate": None, "name": "ACTION4"}
    events.extend(
        (
            _selected(
                "E-FINAL-SELECTED",
                "ACTION4",
                step=9,
                epoch_id=successor_epoch,
                probe_or_plan_id="plan:successor",
                reexploration=False,
                decision_id="decision:final",
            ),
            _event(
                "E-FINAL-PREDICTION",
                "simulation.prediction_emitted",
                {
                    "action": final_action,
                    "action_decision_id": "decision:final",
                    "alternatives": [
                        {
                            "prediction_ids": [model_prediction],
                            "supporting_model_ids": ["world-model:successor"],
                        },
                        {
                            "prediction_ids": ["prediction:unrelated"],
                            "supporting_model_ids": ["world-model:unrelated"],
                        },
                    ],
                    "mechanics_epoch_id": successor_epoch,
                    "receipt_id": "prediction-receipt:final",
                },
                step=9,
            ),
            _event(
                "E-FINAL-SUBMITTED",
                "action.submitted",
                {
                    "action": final_action,
                    "decision_id": "decision:final",
                    "prediction_receipt_id": "prediction-receipt:final",
                    "selected_event_id": "E-FINAL-SELECTED",
                },
                step=9,
            ),
            _event(
                "E-FINAL-CONSEQUENCE",
                "consequence.received",
                {
                    "action": final_action,
                    "returned_action": final_action,
                    "selected_event_id": "E-FINAL-SELECTED",
                    "submitted_action": final_action,
                    "submitted_event_id": "E-FINAL-SUBMITTED",
                },
                step=9,
            ),
            _observation("E-FINAL-OBSERVATION", "ACTION4", step=10),
            _event(
                "E-FINAL-MATCHED",
                "consequence.matched_prediction",
                {
                    "controlled_projection_match_model_ids": [],
                    "matched_prediction_ids": [matched_prediction],
                    "mechanics_epoch_id": successor_epoch,
                    "prediction_receipt_id": "prediction-receipt:final",
                },
                step=10,
            ),
        )
    )
    return tuple(events)


def test_candidate_confirmation_and_successor_use_require_exact_causal_chain() -> None:
    events = _lifecycle_trace()
    passed, matched, failures = _linked_lifecycle_chain(
        events, predecessor_epoch_id="mechanics-epoch:L0:0000"
    )
    assert passed is True, failures
    assert len(matched) == 12

    created = next(
        event for event in events if event.event_type == "mechanics.change_candidate_created"
    )
    confirmed = next(event for event in events if event.event_type == "mechanics.change_confirmed")
    assert _linked_candidate_confirmation_support(events, created, confirmed)["passed"] is True


def test_post_boundary_source_closure_is_recursive_explicit_and_narrative_blind() -> None:
    action = {"coordinate": None, "name": "ACTION1"}
    root_observation = _observation("E-PREFIX-OBSERVATION", "ACTION1", step=1)
    selected_payload = deepcopy(
        _selected(
            "E-PREFIX-SELECTED",
            "ACTION1",
            step=1,
            epoch_id="mechanics-epoch:L0:0000",
            probe_or_plan_id="plan:old",
            reexploration=False,
            decision_id="decision:prefix",
        ).payload
    )
    selected_payload["source_observation_event_id"] = root_observation.event_id
    selected = _event(
        "E-PREFIX-SELECTED",
        "action.selected",
        selected_payload,
        step=1,
    )
    unrelated_confirmation = _event(
        "E-PREFIX-UNRELATED-CONFIRMATION",
        "mechanics.change_confirmed",
        {"candidate_id": "mechanics-change:unrelated"},
        step=1,
    )
    submitted = _event(
        "E-POST-SUBMITTED",
        "action.submitted",
        {
            "action": action,
            "decision_id": "decision:prefix",
            "selected_event_id": selected.event_id,
        },
        step=1,
    )
    consequence = _event(
        "E-POST-CONSEQUENCE",
        "consequence.received",
        {
            "action": action,
            "returned_action": action,
            "selected_event_id": selected.event_id,
            "submitted_action": action,
            "submitted_event_id": submitted.event_id,
        },
        step=1,
    )
    narrative = _event(
        "E-POST-NARRATIVE",
        "goal.supported",
        {
            "summary": (
                "untrusted prose mentions E-PREFIX-UNRELATED-CONFIRMATION but does not cite it"
            )
        },
        step=2,
    )
    events = (
        root_observation,
        selected,
        unrelated_confirmation,
        submitted,
        consequence,
        narrative,
    )
    closed = _event_source_closure_after(events, 3)
    assert [event.event_id for event in closed] == [
        root_observation.event_id,
        selected.event_id,
        submitted.event_id,
        consequence.event_id,
        narrative.event_id,
    ]
    assert unrelated_confirmation.event_id not in {event.event_id for event in closed}

    lifecycle_events = _lifecycle_trace()
    source_closed_lifecycle = _event_source_closure_after(lifecycle_events, 1)
    passed, _, failures = _linked_lifecycle_chain(
        source_closed_lifecycle,
        predecessor_epoch_id="mechanics-epoch:L0:0000",
    )
    assert passed is True, failures


def test_candidate_confirmation_rejects_absent_second_causal_tuple() -> None:
    events = _lifecycle_trace(absent_second_confirmation_source=True)
    passed, _, failures = _linked_lifecycle_chain(
        events, predecessor_epoch_id="mechanics-epoch:L0:0000"
    )
    assert passed is False
    assert any("confirmation support" in failure for failure in failures)


def test_candidate_confirmation_rejects_reversed_or_precreated_second_support() -> None:
    events = list(_lifecycle_trace())
    created = next(
        event for event in events if event.event_type == "mechanics.change_candidate_created"
    )
    confirmed = next(event for event in events if event.event_type == "mechanics.change_confirmed")

    first_support_index = next(
        index for index, event in enumerate(events) if event.event_id == "E-SUCCESSOR-SUPPORT-1"
    )
    second_support_index = next(
        index for index, event in enumerate(events) if event.event_id == "E-SUCCESSOR-SUPPORT-2"
    )
    reversed_supports = list(events)
    reversed_supports[first_support_index], reversed_supports[second_support_index] = (
        reversed_supports[second_support_index],
        reversed_supports[first_support_index],
    )
    reversed_report = _linked_candidate_confirmation_support(reversed_supports, created, confirmed)
    assert reversed_report["passed"] is False
    assert reversed_report["predicates"]["support_ordered_around_candidate"] is False

    precreated_second_support = list(events)
    second_source_start = next(
        index
        for index, event in enumerate(precreated_second_support)
        if event.event_id == "E-SELECTED-2"
    )
    second_source_end = next(
        index
        for index, event in enumerate(precreated_second_support)
        if event.event_id == "E-SUCCESSOR-SUPPORT-2"
    )
    second_source_block = precreated_second_support[second_source_start : second_source_end + 1]
    del precreated_second_support[second_source_start : second_source_end + 1]
    created_index = next(
        index
        for index, event in enumerate(precreated_second_support)
        if event.event_id == created.event_id
    )
    precreated_second_support[created_index:created_index] = second_source_block
    precreated_report = _linked_candidate_confirmation_support(
        precreated_second_support, created, confirmed
    )
    assert precreated_report["passed"] is False
    second_receipt = next(
        receipt
        for receipt in precreated_report["support_receipts"]
        if receipt["support_index"] == 2
    )
    assert second_receipt["causal_order"] is False


def test_candidate_authority_closure_requires_complete_sets_and_static_identity() -> None:
    events = list(_lifecycle_trace())
    demotion_index = next(
        index for index, event in enumerate(events) if event.event_id == "E-DEMOTED"
    )
    demotion = events[demotion_index]
    incomplete_demotion_payload = deepcopy(demotion.payload)
    incomplete_demotion_payload["model_ids"] = ["world-model:old"]
    incomplete_demotion = list(events)
    incomplete_demotion[demotion_index] = _event(
        demotion.event_id,
        demotion.event_type,
        incomplete_demotion_payload,
        step=demotion.step_index,
    )
    passed, _, failures = _linked_lifecycle_chain(
        incomplete_demotion, predecessor_epoch_id="mechanics-epoch:L0:0000"
    )
    assert passed is False
    assert any("authority closure" in failure for failure in failures)

    incomplete_reopening = [event for event in events if event.event_id != "E-REOPENED-2"]
    passed, _, failures = _linked_lifecycle_chain(
        incomplete_reopening, predecessor_epoch_id="mechanics-epoch:L0:0000"
    )
    assert passed is False
    assert any("authority closure" in failure for failure in failures)

    confirmation_index = next(
        index for index, event in enumerate(events) if event.event_id == "E-CONFIRMED"
    )
    confirmation = events[confirmation_index]
    mismatched_confirmation_payload = deepcopy(confirmation.payload)
    mismatched_confirmation_payload["opaque_handle"] = "ACTION4"
    mismatched_confirmation = list(events)
    mismatched_confirmation[confirmation_index] = _event(
        confirmation.event_id,
        confirmation.event_type,
        mismatched_confirmation_payload,
        step=confirmation.step_index,
    )
    passed, _, failures = _linked_lifecycle_chain(
        mismatched_confirmation, predecessor_epoch_id="mechanics-epoch:L0:0000"
    )
    assert passed is False
    assert any("linked confirmation" in failure for failure in failures)


def test_destination_role_successor_requires_exact_candidate_signatures() -> None:
    valid = _lifecycle_trace(destination_role=True)
    passed, _, failures = _linked_lifecycle_chain(
        valid, predecessor_epoch_id="mechanics-epoch:L0:0000"
    )
    assert passed is True, failures

    unrelated = _lifecycle_trace(
        destination_role=True,
        unrelated_role_statement=True,
    )
    passed, _, failures = _linked_lifecycle_chain(
        unrelated, predecessor_epoch_id="mechanics-epoch:L0:0000"
    )
    assert passed is False
    assert any("typed successor hypothesis" in failure for failure in failures)


def test_successor_use_rejects_unrelated_hypothesis_or_matched_model() -> None:
    unrelated_hypothesis = _lifecycle_trace(unrelated_successor_hypothesis=True)
    assert not _linked_lifecycle_chain(
        unrelated_hypothesis, predecessor_epoch_id="mechanics-epoch:L0:0000"
    )[0]

    unrelated_match = _lifecycle_trace(unrelated_model_matches=True)
    assert not _linked_lifecycle_chain(
        unrelated_match, predecessor_epoch_id="mechanics-epoch:L0:0000"
    )[0]


def test_metamorphic_group_requires_all_four_transform_combinations() -> None:
    results = [
        _fake_result(palette=palette, action=action)
        for palette in PaletteVariant
        for action in ActionVariant
    ]
    summary = _metamorphic_groups(results, noise=False)
    assert summary["group_count"] == 1
    assert summary["passed_groups"] == 1


def test_metamorphic_group_rejects_duplicate_transform_in_four_items() -> None:
    results = [
        _fake_result(palette=palette, action=action)
        for palette in PaletteVariant
        for action in ActionVariant
    ]
    duplicate = _fake_result(
        palette=PaletteVariant.IDENTITY,
        action=ActionVariant.IDENTITY,
    )
    source_case = results[-1]["case"]
    assert isinstance(source_case, dict)
    duplicate["case"] = dict(source_case)
    duplicate_case = duplicate["case"]
    assert isinstance(duplicate_case, dict)
    duplicate_case["palette_variant"] = PaletteVariant.IDENTITY.value
    duplicate_case["action_variant"] = ActionVariant.IDENTITY.value
    results[-1] = duplicate

    summary = _metamorphic_groups(results, noise=False)
    groups = summary["groups"]
    assert isinstance(groups, list)
    predicates = groups[0]["predicates"]
    assert isinstance(predicates, dict)
    assert predicates["all_four_transforms"] is True
    assert predicates["exact_2x2_transform_membership"] is False
    assert summary["passed_groups"] == 0


def _action_trace(*, submitted_action_name: str = "ACTION1") -> tuple[TraceEvent, ...]:
    action = {"coordinate": None, "name": "ACTION1"}
    return (
        _event(
            "E-SELECTED",
            "action.selected",
            {
                "active_hypothesis_ids": ["H-1"],
                "candidate_utilities": [],
                "decision_id": "action-decision:one",
                "predicted_outcome_ids": [],
                "rationale_category": "follow_plan",
                "selected_action": action,
                "selected_probe_or_plan_id": "plan:one",
            },
        ),
        _event(
            "E-VALIDATED",
            "action.validated",
            {
                "action": action,
                "decision_id": "action-decision:one",
                "selected_event_id": "E-SELECTED",
            },
        ),
        _event(
            "E-SUBMITTED",
            "action.submitted",
            {
                "action": {"coordinate": None, "name": submitted_action_name},
                "decision_id": "action-decision:one",
                "selected_event_id": "E-SELECTED",
                "validated_event_id": "E-VALIDATED",
            },
        ),
        _event(
            "E-CONSEQUENCE",
            "consequence.received",
            {
                "action": action,
                "returned_action": action,
                "selected_event_id": "E-SELECTED",
                "submitted_action": action,
                "submitted_event_id": "E-SUBMITTED",
            },
            step=1,
        ),
    )


def test_causal_action_replay_rejects_tampered_submitted_payload() -> None:
    expected = [{"coordinate": None, "name": "ACTION1"}]
    valid = _causal_action_replay(
        _action_trace(), expected_actions=expected, expected_reset_count=0
    )
    assert valid["passed"] is True

    tampered = _causal_action_replay(
        _action_trace(submitted_action_name="ACTION2"),
        expected_actions=expected,
        expected_reset_count=0,
    )
    predicates = tampered["predicates"]
    assert isinstance(predicates, dict)
    assert predicates["causal_quartets"] is False
    assert tampered["passed"] is False


def test_observation_blinding_checks_each_receipt_for_truth_keys() -> None:
    payload: dict[str, object] = {
        "available_actions": ["ACTION1"],
        "frame_count": 1,
        "frames": [
            {
                "blob_hash": "sha256:" + "a" * 64,
                "frame_hash": "sha256:" + "b" * 64,
                "height": 1,
                "palette": [0],
                "width": 1,
            }
        ],
        "game_state": "NOT_FINISHED",
        "score": None,
        "upstream_metadata": {},
    }
    clean = _observation_blinding_report((_event("E-OBS-CLEAN", "observation.received", payload),))
    assert clean["passed"] is True
    blinded_violation = _observation_blinding_report(
        (
            _event("E-OBS-CLEAN", "observation.received", payload),
            _event(
                "E-OBS-BAD",
                "observation.received",
                {**payload, "upstream_metadata": {"case_id": "evaluator-secret"}},
            ),
        )
    )
    assert blinded_violation["observation_count"] == 2
    assert blinded_violation["passed"] is False
    value_violation = _observation_blinding_report(
        (
            _event(
                "E-OBS-VALUE",
                "observation.received",
                {**payload, "upstream_metadata": {"opaque": "truth-receipt:secret"}},
            ),
        ),
        forbidden_values=("truth-receipt:secret",),
    )
    assert value_violation["passed"] is False


def _noise_trace(
    *,
    resolved_candidate_id: str,
    typed_recovery_events: bool = True,
    second_signature: str = "sha256:predecessor",
) -> tuple[tuple[TraceEvent, ...], tuple[dict[str, object], ...]]:
    candidate_id = "mechanics-change:one"
    predecessor_epoch_id = "mechanics-epoch:L0:0000"
    condition_signature = "sha256:condition"
    predecessor_signature = "sha256:predecessor"
    events: list[TraceEvent] = [
        _event(
            "E-TRIGGER",
            "consequence.received",
            {"action": {"coordinate": None, "name": "ACTION1"}},
            step=7,
        ),
        _event(
            "E-CREATED",
            "mechanics.change_candidate_created",
            {
                "affected_hypothesis_ids": ["H-OLD"],
                "candidate_id": candidate_id,
                "change_domain": "DESTINATION_ROLE",
                "observation_condition_signature": condition_signature,
                "predecessor_effect_signature": predecessor_signature,
                "predecessor_epoch_id": predecessor_epoch_id,
                "source_consequence_event_id": "E-TRIGGER",
            },
            step=8,
        ),
    ]
    for support_index, (action_name, step) in enumerate((("ACTION2", 9), ("ACTION3", 10)), start=1):
        selected_id = f"E-SELECTED-{support_index}"
        submitted_id = f"E-SUBMITTED-{support_index}"
        consequence_id = f"E-CONSEQUENCE-{support_index}"
        observation_id = f"E-OBSERVATION-{support_index}"
        transition_id = f"transition:{submitted_id}"
        recovery_id = f"E-RECOVERY-{support_index}"
        action = {"coordinate": None, "name": action_name}
        events.extend(
            (
                _event(
                    selected_id,
                    "action.selected",
                    {
                        "active_hypothesis_ids": ["H-OLD"],
                        "candidate_utilities": [],
                        "predicted_outcome_ids": [],
                        "rationale_category": "reexploration",
                        "selected_action": action,
                        "selected_probe_or_plan_id": candidate_id,
                    },
                    step=step - 1,
                ),
                _event(
                    submitted_id,
                    "action.submitted",
                    {"action": action, "selected_event_id": selected_id},
                    step=step - 1,
                ),
                _event(
                    consequence_id,
                    "consequence.received",
                    {
                        "action": action,
                        "returned_action": action,
                        "selected_event_id": selected_id,
                        "submitted_action": action,
                        "submitted_event_id": submitted_id,
                    },
                    step=step - 1,
                ),
                _event(
                    observation_id,
                    "observation.received",
                    {
                        "available_actions": ["ACTION1", "ACTION2", "ACTION3", "ACTION4"],
                        "frame_count": 1,
                        "frames": [
                            {
                                "blob_hash": "sha256:" + str(support_index) * 64,
                                "frame_hash": "sha256:" + str(support_index) * 64,
                                "height": 1,
                                "palette": [0],
                                "width": 1,
                            }
                        ],
                        "game_state": "NOT_FINISHED",
                        "returned_action": action,
                        "score": None,
                        "upstream_metadata": {},
                    },
                    step=step,
                ),
                _event(
                    f"E-INTERPRETATION-{support_index}",
                    "action.controlled_effect_interpreted",
                    {
                        "mechanics_epoch_id": predecessor_epoch_id,
                        "source_consequence_event_id": consequence_id,
                        "source_transition_id": transition_id,
                    },
                    step=step,
                ),
                _event(
                    recovery_id,
                    (
                        "mechanics.predecessor_recovery_supported"
                        if typed_recovery_events
                        else "hypothesis.supported"
                    ),
                    {
                        "affected_hypothesis_ids": ["H-OLD"],
                        "candidate_id": candidate_id,
                        "discrimination_context_id": f"sha256:context-{support_index}",
                        "interpretation": "predecessor-consistent consequence",
                        "observation_condition_signature": condition_signature,
                        "observed_effect_signature": (
                            second_signature if support_index == 2 else predecessor_signature
                        ),
                        "predecessor_epoch_id": predecessor_epoch_id,
                        "source_consequence_event_id": consequence_id,
                        "source_observation_event_id": observation_id,
                        "source_transition_id": transition_id,
                        "support_index": support_index,
                    },
                    step=step,
                ),
            )
        )
    events.append(
        _event(
            "E-RESOLVED",
            "mechanics.change_candidate_resolved",
            {
                "candidate_id": resolved_candidate_id,
                "predecessor_recovery_event_ids": ["E-RECOVERY-1", "E-RECOVERY-2"],
                "provisional_status": "RESOLVED_NOISE",
            },
            step=10,
        )
    )
    truth = (
        {
            "pulse_triggered": True,
            "resumed_predecessor_receipts": 0,
            "step": 8,
            "trigger_step": 8,
        },
        {
            "pulse_triggered": True,
            "resumed_predecessor_receipts": 1,
            "step": 9,
            "trigger_step": 8,
        },
        {
            "pulse_triggered": True,
            "resumed_predecessor_receipts": 2,
            "step": 10,
            "trigger_step": 8,
        },
    )
    return tuple(events), truth


def test_noise_closure_is_specific_to_trigger_sourced_candidate() -> None:
    events, truth = _noise_trace(resolved_candidate_id="mechanics-change:one")
    valid = _linked_noise_closure(events, truth)
    assert valid["passed"] is True

    events, truth = _noise_trace(resolved_candidate_id="mechanics-change:other")
    wrong_candidate = _linked_noise_closure(events, truth)
    predicates = wrong_candidate["predicates"]
    assert isinstance(predicates, dict)
    assert predicates["same_candidate_resolved_noise"] is False
    assert wrong_candidate["passed"] is False


def test_noise_closure_rejects_arbitrary_or_nonqualifying_recovery_ids() -> None:
    events, truth = _noise_trace(
        resolved_candidate_id="mechanics-change:one", typed_recovery_events=False
    )
    arbitrary = _linked_noise_closure(events, truth)
    arbitrary_predicates = arbitrary["predicates"]
    assert isinstance(arbitrary_predicates, dict)
    assert arbitrary_predicates["two_exact_typed_causal_recoveries"] is False

    events, truth = _noise_trace(
        resolved_candidate_id="mechanics-change:one",
        second_signature="sha256:not-predecessor",
    )
    nonqualifying = _linked_noise_closure(events, truth)
    nonqualifying_predicates = nonqualifying["predicates"]
    assert isinstance(nonqualifying_predicates, dict)
    assert nonqualifying_predicates["two_exact_typed_causal_recoveries"] is False
    assert nonqualifying["passed"] is False


def test_resource_summary_counts_primary_and_checkpoint_executions() -> None:
    episode = {
        "rss": {"process_peak_rss_bytes": 1234},
        "wall_ns": 100,
    }
    summary = _resource_summary(
        {"cases": [episode]},
        {"cases": [episode]},
        {"pairs": [{"uninterrupted": episode, "resumed": episode}]},
        wall_ns=1000,
        cpu_ns=500,
    )
    assert summary["maximum_execution_wall_ns"] == 100
    assert summary["median_execution_wall_ns"] == 100.0
    assert summary["peak_rss_bytes"] == 1234
    assert summary["maximum_execution_wall_within_limit"] is True


def test_checkpoint_limit_covers_boundary_and_final_aggregate_root() -> None:
    within = _checkpoint_resource_report(
        checkpointing=True,
        boundary_checkpoint_bytes=MAX_CHECKPOINT_BYTES,
        final_checkpoint_bytes=MAX_CHECKPOINT_BYTES,
    )
    assert within["passed"] is True
    assert within["final_checkpoint_within_limit"] is True
    assert "aggregate bytes" in str(within["measurement_scope"])

    late_growth = _checkpoint_resource_report(
        checkpointing=True,
        boundary_checkpoint_bytes=MAX_CHECKPOINT_BYTES - 1,
        final_checkpoint_bytes=MAX_CHECKPOINT_BYTES + 1,
    )
    assert late_growth["boundary_checkpoint_within_limit"] is True
    assert late_growth["final_checkpoint_within_limit"] is False
    assert late_growth["passed"] is False


def test_checkpoint_commitment_distinguishes_envelope_prior_tail_from_receipt_tail() -> None:
    prior = _event("E-CHECKPOINT-PRIOR", "hypothesis.supported", {})
    derived_state = {
        "schema": "arc3.memory.derived-controller.v0.1",
        "phase": "ready",
        "level_index": 0,
        "step_index": 7,
        "pending_action": None,
    }
    rng_state = [3, [1, 2, 3], None]
    checkpoint_hash = "sha256:" + "4" * 64
    envelope = {
        "checkpoint_hash": checkpoint_hash,
        "config_hash": _CODE.config_hash,
        "episode_id": "episode-stage06-harness-test",
        "git_commit": _CODE.git_commit,
        "rng_state": rng_state,
        "run_id": "run-stage06-harness-test",
        "schema": "arc3.checkpoint.v0.1",
        "state": {"derived_controller_state": derived_state},
        "trace_tail_event_id": prior.event_id,
        "trace_tail_hash": prior.event_hash,
    }
    receipt = _event(
        "E-CHECKPOINT-RECEIPT",
        "run.checkpoint_written",
        {
            "checkpoint_hash": checkpoint_hash,
            "checkpoint_schema": "arc3.checkpoint.v0.1",
            "checkpoint_sequence": 1,
            "commitment_schema": "arc3.memory.checkpoint-commitment.v0.1",
            "config_hash": _CODE.config_hash,
            "controller_phase": "ready",
            "derived_controller_schema": "arc3.memory.derived-controller.v0.1",
            "derived_controller_state_hash": sha256_json(derived_state),
            "envelope_prior_trace_tail_event_id": prior.event_id,
            "envelope_prior_trace_tail_hash": prior.event_hash,
            "git_commit": _CODE.git_commit,
            "level_index": 0,
            "memory_phase": "ready",
            "pending_submitted_event_id": None,
            "rng_state_hash": sha256_json(rng_state),
            "step_index": 7,
        },
        previous_event_hash=prior.event_hash,
        scope="run",
        step=7,
    )
    report = _checkpoint_commitment_report((prior, receipt), envelope=envelope)
    assert report["passed"] is True
    assert report["envelope_prior_trace_tail_event_id"] == prior.event_id
    assert report["current_trace_tail_event_id"] == receipt.event_id
    assert report["envelope_prior_trace_tail_event_hash"] == prior.event_hash
    assert report["current_trace_tail_event_hash"] == receipt.event_hash

    tampered_envelope = deepcopy(envelope)
    tampered_envelope["rng_state"] = [3, [9], None]
    tampered = _checkpoint_commitment_report((prior, receipt), envelope=tampered_envelope)
    assert tampered["passed"] is False
    assert tampered["predicates"]["rng_state_hash"] is False


def test_source_identity_requires_exact_clean_start_end_equality() -> None:
    start = {
        "dirty_worktree": False,
        "first_party_source_hash": "sha256:" + "1" * 64,
        "git_commit": "a" * 40,
        "git_tree": "b" * 40,
        "identity_hash": "sha256:" + "2" * 64,
        "predeclaration_sha256": PREDECLARATION_SHA256,
    }
    stable = _source_identity_stability(start, deepcopy(start))
    assert stable["passed"] is True

    drifted = deepcopy(start)
    drifted["first_party_source_hash"] = "sha256:" + "3" * 64
    drifted["identity_hash"] = "sha256:" + "4" * 64
    report = _source_identity_stability(start, drifted)
    predicates = report["predicates"]
    assert isinstance(predicates, dict)
    assert predicates["first_party_source_hash"] is False
    assert predicates["exact_identity"] is False
    assert report["passed"] is False

    dirty_end = deepcopy(start)
    dirty_end["dirty_worktree"] = True
    dirty_end["identity_hash"] = "sha256:" + "5" * 64
    assert _source_identity_stability(start, dirty_end)["passed"] is False


def test_semantic_checkpoint_projection_canonicalizes_unordered_dynamic_ids() -> None:
    left_events = (
        _event(
            "E-LEFT-1",
            "model.rule_promoted",
            {"evidence_id": "gev:z", "model_id": "world-model:z"},
        ),
        _event("E-LEFT-2", "model.rule_promoted", {"model_id": "world-model:a"}),
    )
    right_events = (
        _event(
            "E-RIGHT-1",
            "model.rule_promoted",
            {"evidence_id": "gev:a", "model_id": "world-model:a"},
        ),
        _event("E-RIGHT-2", "model.rule_promoted", {"model_id": "world-model:z"}),
    )
    left = {
        "active_model_ids": ["world-model:a", "world-model:z"],
        "goal_evidence": {"evidence_id": "gev:z"},
    }
    right = {
        "active_model_ids": ["world-model:a", "world-model:z"],
        "goal_evidence": {"evidence_id": "gev:a"},
    }

    assert _semantic_identifier_projection(left, left_events) == (
        _semantic_identifier_projection(right, right_events)
    )


def test_pretrigger_checkpoint_requires_plan_only_open_action_boundary() -> None:
    readiness = {
        "action_boundary_open": True,
        "active_action_bindings": {"ACTION1": ["H-ACTION"]},
        "active_hypothesis_domains": {"H-ACTION": "action_semantics"},
        "active_hypothesis_support_counts": {"H-ACTION": 2},
        "active_model_hypothesis_ids": {"world-model:one": ["H-ACTION"]},
        "active_model_ids": ["world-model:one"],
        "active_plan_current_at_latest_state": True,
        "active_plan_current_step_action": {"coordinate": None, "name": "ACTION1"},
        "active_plan_current_step_before_state_id": "state:before",
        "active_plan_current_step_nontrivial": True,
        "active_plan_current_step_predicted_state_id": "state:after",
        "active_plan_cursor": 0,
        "active_plan_dependency_satisfied": True,
        "active_plan_id": "plan:one",
        "active_plan_invalidated": False,
        "active_plan_model_id": "world-model:one",
        "active_plan_nontrivial": True,
        "active_plan_step_count": 1,
        "calibration_complete": True,
        "higher_priority_probe_present": False,
        "latest_symbolic_state_id": "state:before",
        "pending_action_present": False,
        "pending_prediction_alternatives": [],
        "pending_prediction_dependent_plan_ids": [],
        "pending_prediction_model_ids": [],
        "pending_prediction_nontrivial": False,
        "pending_prediction_receipt_id": None,
    }
    episode = SimpleNamespace(
        ready_for_evaluator_arm=True,
        case=SimpleNamespace(
            family=RuleChangeFamily.ACTION_EFFECT_ROTATION,
            support_required=2,
        ),
        projection=SimpleNamespace(prechange_support_receipts=2),
        session=SimpleNamespace(
            observation=SimpleNamespace(available_actions=(ActionName.ACTION1,))
        ),
        trigger_eligible=lambda action: action.name is ActionName.ACTION1,
    )
    support_events = (
        _event(
            "E-SUPPORT-1",
            "hypothesis.supported",
            {
                "evidence_receipt": {"receipt_id": "evidence:one"},
                "hypothesis_id": "H-ACTION",
            },
        ),
        _event(
            "E-SUPPORT-2",
            "hypothesis.supported",
            {
                "evidence_receipt": {"receipt_id": "evidence:two"},
                "hypothesis_id": "H-ACTION",
            },
        ),
    )
    journal = SimpleNamespace(
        flush=lambda: None,
        verify_manifest=lambda *, include_active: support_events,
    )
    controller = SimpleNamespace(
        journal=journal,
        mechanics_lifecycle_projection={"readiness": readiness},
    )
    assert _pretrigger_checkpoint_ready(controller, episode) is True

    pending_action = deepcopy(readiness)
    pending_action["pending_action_present"] = True
    pending_action["action_boundary_open"] = False
    controller.mechanics_lifecycle_projection = {"readiness": pending_action}
    assert _pretrigger_checkpoint_ready(controller, episode) is False

    pending_prediction = deepcopy(readiness)
    pending_prediction["pending_prediction_receipt_id"] = "prediction-receipt:one"
    pending_prediction["pending_prediction_nontrivial"] = True
    pending_prediction["pending_prediction_model_ids"] = ["world-model:one"]
    controller.mechanics_lifecycle_projection = {"readiness": pending_prediction}
    assert _pretrigger_checkpoint_ready(controller, episode) is False

    current_step_noop = deepcopy(readiness)
    current_step_noop["active_plan_current_step_nontrivial"] = False
    current_step_noop["active_plan_nontrivial"] = False
    current_step_noop["active_plan_current_step_predicted_state_id"] = "state:before"
    controller.mechanics_lifecycle_projection = {"readiness": current_step_noop}
    assert _pretrigger_checkpoint_ready(controller, episode) is False

    preempted = deepcopy(readiness)
    preempted["higher_priority_probe_present"] = True
    controller.mechanics_lifecycle_projection = {"readiness": preempted}
    assert _pretrigger_checkpoint_ready(controller, episode) is False


def test_truth_receipt_report_verifies_chained_evaluator_receipts() -> None:
    episode = open_rule_change_case(_case())
    for action in episode.session.observation.available_actions:
        episode.take(ActionRequest(action))
    report = _truth_receipt_report(episode)
    assert report["receipt_count"] == 4
    assert report["duplicate_receipt_ids"] == 0
    assert report["verified"] is True


def test_direct_script_help_imports_without_package_execution() -> None:
    completed = subprocess.run(
        [sys.executable, str(ROOT / "scripts/measure_rule_change_reopening.py"), "--help"],
        cwd=ROOT,
        capture_output=True,
        check=False,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr
    assert "--work-root" in completed.stdout
