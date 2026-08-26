from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

import arc3.evaluation.mechanical_replay as replay_module
from arc3.evaluation.mechanical_replay import (
    MechanicalReplayError,
    replay_unfinished_mechanical_recording,
)
from arc3.mechanics.visual_causal import VisualCausalPolicy
from arc3.types import GameStateName


def _row(
    *,
    action: str,
    timestamp: str,
    full_reset: bool,
    guid: str = "synthetic-guid",
    game_id: str = "synthetic-recording",
    levels_completed: int = 0,
    state: str = "NOT_FINISHED",
    win_levels: int = 2,
) -> dict[str, Any]:
    return {
        "data": {
            "action_input": {
                "data": {},
                "id": action,
                "reasoning": (
                    None
                    if action == "RESET"
                    else {"category": "synthetic", "summary": "recorded fixture action"}
                ),
            },
            "available_actions": [1],
            "frame": [[[0]]],
            "full_reset": full_reset,
            "game_id": game_id,
            "guid": guid,
            "levels_completed": levels_completed,
            "state": state,
            "win_levels": win_levels,
        },
        "timestamp": timestamp,
    }


def _good_rows() -> list[dict[str, Any]]:
    return [
        _row(
            action="RESET",
            timestamp="2026-08-25T12:00:00+00:00",
            full_reset=True,
        ),
        _row(
            action="ACTION1",
            timestamp="2026-08-25T12:00:01+00:00",
            full_reset=False,
        ),
    ]


def _encoded(rows: list[dict[str, Any]], *, trailing_newline: bool = True) -> bytes:
    raw = b"\n".join(
        json.dumps(row, sort_keys=True, separators=(",", ":")).encode("utf-8") for row in rows
    )
    return raw + (b"\n" if trailing_newline else b"")


def _replay(
    tmp_path: Path,
    rows: list[dict[str, Any]],
    *,
    trailing_newline: bool = True,
    expected_state: GameStateName = GameStateName.NOT_FINISHED,
    expected_levels: int = 0,
) -> dict[str, object]:
    raw = _encoded(rows, trailing_newline=trailing_newline)
    path = tmp_path / "recording.jsonl"
    path.write_bytes(raw)
    return replay_unfinished_mechanical_recording(
        path,
        expected_game_id="synthetic-recording",
        expected_recording_sha256=hashlib.sha256(raw).hexdigest(),
        expected_byte_length=len(raw),
        expected_row_count=len(rows),
        expected_final_state=expected_state,
        expected_levels_completed=expected_levels,
        expected_win_levels=2,
        max_coordinate_candidates=8,
    )


def test_replay_matches_recorded_policy_then_cancels_the_unsubmitted_candidate(
    tmp_path: Path,
) -> None:
    receipt = _replay(tmp_path, _good_rows())

    assert receipt["boundaries"] == {
        "completion_claimed": False,
        "environment_actions_issued": False,
        "game_source_inspected": False,
        "holdout_accessed": False,
        "session_or_adapter_constructed": False,
    }
    assert receipt["final_recorded_observation"] == {
        "available_actions": ["ACTION1"],
        "frame_count": 1,
        "frame_sha256": ("sha256:5a3185e7dcdffae368b2ad4ae7910dc535a0c19e7ad962ab66c10364596be53c"),
        "full_reset": False,
        "levels_completed": 0,
        "state": "NOT_FINISHED",
        "win_levels": 2,
    }
    candidate = receipt["candidate_next_submission"]
    assert isinstance(candidate, dict)
    assert candidate["action"] == {"coordinate": None, "name": "ACTION1"}
    assert candidate["submitted"] is False
    cancellation = receipt["cancellation_verification"]
    assert isinstance(cancellation, dict)
    assert cancellation["verified"] is True
    assert cancellation["close_status"] == "PASS"
    assert cancellation["learner_pending_after"] == 0
    assert cancellation["policy_receipt_count_before"] == 1
    assert cancellation["policy_receipt_count_after"] == 1
    result = receipt["replay_result"]
    assert isinstance(result, dict)
    assert result["accepted_consequence_count"] == 1
    assert result["action_counts"] == {"ACTION1": 1}
    assert result["candidate_cancelled"] is True
    assert result["candidate_cancellation_verified"] is True
    assert result["matched_submission_count"] == 1
    assert result["matched_through_submission"] == 1
    assert result["mismatch"] is None
    assert result["policy_receipt_count"] == 1
    assert result["state_counts"] == {"NOT_FINISHED": 1}
    assert result["status"] == "PASS_RECORDED_FRAME_REPLAY"
    assert isinstance(result["candidate_selection_snapshot_sha256"], str)
    assert result["candidate_selection_snapshot_sha256"].startswith("sha256:")
    family_state = receipt["family_state_after_candidate_selection"]
    assert isinstance(family_state, dict)
    assert family_state["hierarchy_bridge_relation_rejected_count"] == 0


def test_replay_action_mismatch_cancels_the_policy_pending_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    instances: list[VisualCausalPolicy] = []

    class TrackedPolicy(VisualCausalPolicy):
        def __init__(self, *, max_coordinate_candidates: int) -> None:
            super().__init__(max_coordinate_candidates=max_coordinate_candidates)
            instances.append(self)

    rows = _good_rows()
    rows[1]["data"]["action_input"]["id"] = "ACTION2"
    monkeypatch.setattr(replay_module, "VisualCausalPolicy", TrackedPolicy)

    with pytest.raises(MechanicalReplayError, match="divergence at recorded submission 1"):
        _replay(tmp_path, rows)

    assert len(instances) == 1
    policy = instances[0]
    learner = policy.mechanical_learner
    assert learner is not None
    assert learner.pending == ()
    assert policy.snapshot()["pending_action"] is None
    assert policy.snapshot()["pending_prediction_id"] is None
    policy.close()


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (
            lambda rows: rows[1].update({"extra": True}),
            "must contain exactly data and timestamp",
        ),
        (
            lambda rows: rows[1]["data"].update({"guid": "changed-guid"}),
            "changed guid",
        ),
        (
            lambda rows: rows[1].update({"timestamp": "2026-08-25T12:00:00+00:00"}),
            "not strictly increasing",
        ),
        (
            lambda rows: rows[0]["data"].update({"levels_completed": 1}),
            "regressed levels_completed",
        ),
        (
            lambda rows: rows[1]["data"].update({"win_levels": 3}),
            "changed win_levels",
        ),
        (
            lambda rows: rows[0]["data"]["action_input"].update({"id": "ACTION1"}),
            "first row is not the official RESET return",
        ),
    ],
)
def test_replay_rejects_malformed_or_inconsistent_rows(
    tmp_path: Path,
    mutate: Callable[[list[dict[str, Any]]], None],
    message: str,
) -> None:
    rows = copy.deepcopy(_good_rows())
    mutate(rows)

    with pytest.raises(MechanicalReplayError, match=message):
        _replay(tmp_path, rows)


def test_replay_rejects_missing_final_newline(tmp_path: Path) -> None:
    with pytest.raises(MechanicalReplayError, match="not newline terminated"):
        _replay(tmp_path, _good_rows(), trailing_newline=False)


def test_replay_rejects_recording_identity_mismatches(tmp_path: Path) -> None:
    rows = _good_rows()
    raw = _encoded(rows)
    path = tmp_path / "recording.jsonl"
    path.write_bytes(raw)

    with pytest.raises(MechanicalReplayError, match="SHA-256"):
        replay_unfinished_mechanical_recording(
            path,
            expected_game_id="synthetic-recording",
            expected_recording_sha256="0" * 64,
            expected_byte_length=len(raw),
            expected_row_count=2,
            expected_final_state=GameStateName.NOT_FINISHED,
            expected_levels_completed=0,
            expected_win_levels=2,
        )
    with pytest.raises(MechanicalReplayError, match="row count"):
        replay_unfinished_mechanical_recording(
            path,
            expected_game_id="synthetic-recording",
            expected_recording_sha256=hashlib.sha256(raw).hexdigest(),
            expected_byte_length=len(raw),
            expected_row_count=3,
            expected_final_state=GameStateName.NOT_FINISHED,
            expected_levels_completed=0,
            expected_win_levels=2,
        )


def test_replay_rejects_a_nonunfinished_final_observation(tmp_path: Path) -> None:
    rows = _good_rows()
    rows[-1]["data"].update({"state": "WIN", "levels_completed": 2})

    with pytest.raises(MechanicalReplayError, match="final state WIN"):
        _replay(tmp_path, rows, expected_levels=2)
