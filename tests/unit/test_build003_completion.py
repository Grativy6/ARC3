"""Focused Build 003 public-play completion boundary tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from arc3.evaluation.public import PublicEvaluationConfig
from arc3.evaluation.public_runner import (
    _TERMINAL_STATUSES,
    _finalize_mechanical_result,
    _mechanical_aggregate,
    _recording_artifacts,
    _recording_evidence,
)

FROZEN = "a" * 40


def _recording_event(
    *, state: str, levels: int, action: str, guid: str = "fixture-guid"
) -> dict[str, object]:
    return {
        "timestamp": "2026-08-24T00:00:00+00:00",
        "data": {
            "game_id": "opaque-build003-fixture",
            "state": state,
            "levels_completed": levels,
            "win_levels": 1,
            "action_input": {"id": action, "data": {}, "reasoning": None},
            "guid": guid,
            "full_reset": action == "RESET",
            "available_actions": [1],
            "frame": [[[0]]],
        },
    }


def _write_recording(root: Path, *, final_state: str = "WIN") -> None:
    scorecard = root / "scorecard-fixture"
    scorecard.mkdir(parents=True)
    path = scorecard / "opaque-build003-fixture-fixture-guid.jsonl"
    events = (
        _recording_event(state="NOT_FINISHED", levels=0, action="RESET"),
        _recording_event(state="NOT_FINISHED", levels=0, action="RESET"),
        _recording_event(state=final_state, levels=1, action="ACTION1"),
    )
    path.write_text("".join(json.dumps(event) + "\n" for event in events), encoding="utf-8")


def _result(*, raw_state: str = "WIN", official_state: str = "WIN") -> dict[str, Any]:
    return {
        "status": "success",
        "score": {
            "completed": official_state == "WIN",
            "verified": True,
            "levels_completed": 1,
            "official_run_game_id": "opaque-build003-fixture",
            "official_run_actions": 2,
            "official_run_resets": 1,
            "official_run_state": official_state,
        },
        "metrics": {
            "final_state": raw_state,
            "final_levels_completed": 1,
            "final_win_levels": 1,
        },
        "trace": {
            "path": "t/fixture",
            "replay_verified": True,
            "mechanical_receipts_replay_linked": True,
            "environment_action_count": 1,
            "reset_count": 1,
            "submitted_action_count": 2,
            "consequence_count": 2,
            "mechanical_action_receipt_count": 2,
            "consequence_actions": [
                {"name": "RESET", "coordinate": None},
                {"name": "ACTION1", "coordinate": None},
            ],
            "final_upstream_session_id": "fixture-guid",
            "final_state": raw_state,
            "final_levels_completed": 1,
            "final_win_levels": 1,
        },
    }


def _specification() -> dict[str, object]:
    return {
        "agent": "mechanical",
        "game_id": "opaque-build003-fixture",
        "run_id": "mechanical-fixture",
    }


def test_completion_requires_authoritative_win_and_strict_official_recording(
    tmp_path: Path,
) -> None:
    recordings = tmp_path / "recordings"
    _write_recording(recordings)
    artifacts, state_counts = _recording_evidence(
        recordings,
        relative_root="official-recordings/fixture",
        expected_game_id="opaque-build003-fixture",
    )

    completed = _finalize_mechanical_result(
        _result(),
        _specification(),
        recording_artifacts=artifacts,
        recording_state_counts=state_counts,
    )
    completion = completed["build003_completion"]
    assert completed["status"] == "success"
    assert completion["completion_observed"] is True
    assert completion["recording_verified"] is True
    assert completion["receipt_complete"] is True
    assert completion["official_run_action_count"] == 2
    assert completion["submission_count"] == 2
    assert completion["non_reset_environment_action_count"] == 1
    assert completion["reset_count"] == 1
    assert completed["metrics"]["recording_consequence_state_counts"] == {
        "NOT_FINISHED": 1,
        "WIN": 1,
    }
    assert completed["metrics"]["game_over_events"] == 0
    assert completed["metrics"]["win_events"] == 1

    stale_non_reset_binding = _result()
    stale_non_reset_binding["score"]["official_run_actions"] = 1
    invalid = _finalize_mechanical_result(
        stale_non_reset_binding,
        _specification(),
        recording_artifacts=artifacts,
    )
    assert invalid["status"] == "failure"
    assert invalid["failure"]["kind"] == "mechanical_run_evidence_incomplete"

    unfinished_recordings = tmp_path / "unfinished-recordings"
    _write_recording(unfinished_recordings, final_state="NOT_FINISHED")
    unfinished_artifacts, unfinished_state_counts = _recording_evidence(
        unfinished_recordings,
        relative_root="official-recordings/unfinished-fixture",
        expected_game_id="opaque-build003-fixture",
    )
    not_finished = _finalize_mechanical_result(
        _result(raw_state="NOT_FINISHED", official_state="NOT_FINISHED"),
        _specification(),
        recording_artifacts=unfinished_artifacts,
        recording_state_counts=unfinished_state_counts,
    )
    assert not_finished["status"] == "not_finished"
    assert not_finished["build003_completion"]["completion_observed"] is False


def test_arbitrary_recording_file_cannot_complete_a_win(tmp_path: Path) -> None:
    recordings = tmp_path / "recordings"
    recordings.mkdir()
    (recordings / "unrelated.txt").write_text("not official evidence", encoding="utf-8")

    artifacts = _recording_artifacts(
        recordings,
        relative_root="official-recordings/fixture",
        expected_game_id="opaque-build003-fixture",
    )
    result = _finalize_mechanical_result(_result(), _specification(), recording_artifacts=artifacts)

    assert artifacts == []
    assert result["status"] == "failure"
    assert result["failure"]["kind"] == "mechanical_run_evidence_incomplete"


def test_mechanical_not_finished_has_a_distinct_nonpass_summary() -> None:
    result = _result(raw_state="NOT_FINISHED", official_state="NOT_FINISHED")
    result.update(
        {
            "agent": "mechanical",
            "baseline_id": "B5",
            "status": "not_finished",
            "score": {
                **result["score"],
                "verified": True,
                "score": 0.0,
            },
            "metrics": {
                **result["metrics"],
                "environment_actions": 1,
                "resets": 0,
                "fault_count": 0,
            },
        }
    )

    summary = _mechanical_aggregate([result], partition="development")

    assert summary["schema"] == "arc3.public-evaluation.summary.v0.3"
    assert summary["status"] == "NOT_FINISHED"
    assert summary["not_finished_count"] == 1


@pytest.mark.parametrize(
    ("failure", "expected_status"),
    (
        (
            {
                "kind": "PolicyError",
                "message": "bounded candidates exhausted",
                "disposition": "FAILED_MECHANISM",
            },
            "FAILED_MECHANISM",
        ),
        (
            {"kind": "PolicyError", "message": "legacy sealed receipt"},
            "FAILED_INFRASTRUCTURE",
        ),
        (
            {"kind": "RuntimeError", "message": "worker failed"},
            "FAILED_INFRASTRUCTURE",
        ),
    ),
)
def test_mechanical_failure_disposition_controls_terminal_summary(
    failure: dict[str, str], expected_status: str
) -> None:
    result = _result(raw_state="NOT_FINISHED", official_state="NOT_FINISHED")
    result.update(
        {
            "agent": "mechanical",
            "baseline_id": "B5",
            "status": "failure",
            "failure": failure,
            "score": {**result["score"], "score": 0.0},
            "metrics": {
                **result["metrics"],
                "environment_actions": 1,
                "resets": 0,
                "fault_count": 1,
            },
        }
    )

    summary = _mechanical_aggregate([result], partition="development")

    assert summary["status"] == expected_status


def test_failed_mechanism_is_a_terminal_public_status() -> None:
    assert "FAILED_MECHANISM" in _TERMINAL_STATUSES


def test_recording_salvage_restores_missing_final_metadata(tmp_path: Path) -> None:
    recordings = tmp_path / "recordings"
    _write_recording(recordings, final_state="NOT_FINISHED")
    artifacts, state_counts = _recording_evidence(
        recordings,
        relative_root="official-recordings/fixture",
        expected_game_id="opaque-build003-fixture",
    )
    result = _result(raw_state="NOT_FINISHED", official_state="NOT_FINISHED")
    result["status"] = "failure"
    result["failure"] = {
        "kind": "PolicyError",
        "message": "bounded candidates exhausted",
        "disposition": "FAILED_MECHANISM",
    }
    for field in ("final_state", "final_levels_completed", "final_win_levels"):
        result["metrics"].pop(field)

    finalized = _finalize_mechanical_result(
        result,
        _specification(),
        recording_artifacts=artifacts,
        recording_state_counts=state_counts,
    )

    assert finalized["status"] == "failure"
    assert finalized["metrics"]["final_state"] == "NOT_FINISHED"
    assert finalized["metrics"]["final_levels_completed"] == 1
    assert finalized["metrics"]["final_win_levels"] == 1
    assert finalized["metrics"]["recording_consequence_state_counts"] == {"NOT_FINISHED": 2}
    assert finalized["build003_completion"]["completion_observed"] is False


def test_allocator_trace_opt_out_is_mechanical_development_only() -> None:
    config = PublicEvaluationConfig(
        partition="development",
        agents=("mechanical",),
        seeds=(7,),
        frozen_commit=FROZEN,
        python_allocation_tracing=False,
    )
    assert config.python_allocation_tracing is False

    with pytest.raises(ValueError, match="FULL policy only"):
        PublicEvaluationConfig(
            partition="development",
            agents=("mechanical",),
            seeds=(7,),
            frozen_commit=FROZEN,
            python_allocation_tracing=False,
            automatic_checkpointing=False,
        )
    with pytest.raises(ValueError, match="local-public development only"):
        PublicEvaluationConfig(
            partition="public-holdout",
            agents=("mechanical",),
            seeds=(7,),
            frozen_commit=FROZEN,
            python_allocation_tracing=False,
        )
    with pytest.raises(ValueError, match="must run alone"):
        PublicEvaluationConfig(
            partition="development",
            agents=("full", "mechanical"),
            seeds=(7,),
            frozen_commit=FROZEN,
        )
