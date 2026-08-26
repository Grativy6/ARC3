from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

import arc3.evaluation.mechanical_replay as replay_module
from arc3.adapters import GridFrame, Observation
from arc3.evaluation.mechanical_replay import (
    MechanicalReplayError,
    replay_unfinished_mechanical_recording,
    replay_unfinished_mechanical_trace,
)
from arc3.mechanics.visual_causal import VisualCausalPolicy
from arc3.trace import CodeIdentity, EventJournal, SourceIdentity
from arc3.trace.canonical import sha256_json
from arc3.trace.instrumentation import BaselineTraceSink
from arc3.types import ActionName, ActionRequest, GameId, GameStateName, JSONValue

TRACE_COMMIT = "c" * 40
TRACE_GAME = "synthetic-trace"
TRACE_RUN = "synthetic-trace-run"


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
) -> dict[str, JSONValue]:
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


def _trace_observation_fixture(
    *,
    state: GameStateName,
    levels_completed: int,
    full_reset: bool,
    returned_action: ActionRequest | None,
) -> Observation:
    available = () if state is GameStateName.GAME_OVER else (ActionName.ACTION1,)
    return Observation(
        game_id=GameId(TRACE_GAME),
        frames=(GridFrame(((0,),)),),
        state=state,
        levels_completed=levels_completed,
        win_levels=2,
        available_actions=available,
        full_reset=full_reset,
        returned_action=returned_action,
        upstream_session_id="synthetic-trace-session",
        upstream_metadata=(("upstream_type", "synthetic-trace"),),
    )


def _build_sealed_trace(
    tmp_path: Path,
    *,
    initial_full_reset: bool = True,
    include_reset_cycle: bool = False,
    omit_first_mechanical_receipt: bool = False,
    first_after_state: GameStateName | None = None,
    reset_recovery_state: GameStateName = GameStateName.NOT_FINISHED,
) -> dict[str, Any]:
    trace_path = tmp_path / "trace"
    journal = EventJournal(trace_path, run_id=TRACE_RUN, fsync_on_flush=False)
    sink = BaselineTraceSink(
        journal=journal,
        episode_id="episode:synthetic-trace",
        source=SourceIdentity(
            kind="synthetic-trace",
            version="1",
            details={"baseline_id": "B5"},
        ),
        code_identity=CodeIdentity(
            git_commit=TRACE_COMMIT,
            config_hash="sha256:" + ("0" * 64),
        ),
        observation_level_scoping=True,
    )
    policy = VisualCausalPolicy(max_coordinate_candidates=8)
    current = _trace_observation_fixture(
        state=GameStateName.NOT_FINISHED,
        levels_completed=0,
        full_reset=initial_full_reset,
        returned_action=ActionRequest(ActionName.RESET),
    )
    sink.record_observation(current)

    def append_cycle(after_state: GameStateName, *, omit_mechanical: bool = False) -> None:
        nonlocal current
        sink.record_candidates(current)
        selected = policy.select(current)
        sink.record_selected(current, selected)
        sink.record_submitted(current, selected)
        after = _trace_observation_fixture(
            state=after_state,
            levels_completed=current.levels_completed,
            full_reset=False,
            returned_action=selected,
        )
        sink.record_consequence(current, selected, after)
        sink.record_observation(after)
        policy.accept_consequence(after)
        durable = policy.drain_durable_receipts()
        if not omit_mechanical:
            sink.record_mechanical_receipts(after, durable)
        current = after

    if first_after_state is None:
        first_after_state = (
            GameStateName.GAME_OVER if include_reset_cycle else GameStateName.NOT_FINISHED
        )
    append_cycle(first_after_state, omit_mechanical=omit_first_mechanical_receipt)
    submission_count = 1
    if include_reset_cycle:
        append_cycle(reset_recovery_state)
        submission_count += 1
    sink.record_candidates(current)
    journal.seal()
    events = journal.verify_manifest()
    manifest_hash = journal.manifest.manifest_hash
    tail_hash = events[-1].event_hash
    journal.close()
    policy.close()
    return {
        "event_count": len(events),
        "manifest_hash": manifest_hash,
        "submission_count": submission_count,
        "tail_hash": tail_hash,
        "trace_path": trace_path,
    }


def _trace_replay(
    trace: dict[str, Any],
    *,
    manifest_hash: str | None = None,
    tail_hash: str | None = None,
) -> dict[str, Any]:
    return replay_unfinished_mechanical_trace(
        trace["trace_path"],
        expected_run_id=TRACE_RUN,
        expected_game_id=TRACE_GAME,
        expected_git_commit=TRACE_COMMIT,
        expected_trace_manifest_hash=manifest_hash or trace["manifest_hash"],
        expected_tail_event_hash=tail_hash or trace["tail_hash"],
        expected_event_count=trace["event_count"],
        expected_submission_count=trace["submission_count"],
        expected_final_state=GameStateName.NOT_FINISHED,
        expected_levels_completed=0,
        expected_win_levels=2,
        max_coordinate_candidates=8,
    )


def test_trace_replay_matches_complete_cycles_and_cancels_candidate(tmp_path: Path) -> None:
    trace = _build_sealed_trace(tmp_path)

    receipt = _trace_replay(trace)

    assert receipt["boundaries"] == {
        "completion_claimed": False,
        "environment_actions_issued": False,
        "game_source_inspected": False,
        "holdout_accessed": False,
        "initial_returned_action_represented": False,
        "initial_returned_action_reconstructed": False,
        "recording_rewritten": False,
        "session_or_adapter_constructed": False,
        "trace_root_modified": False,
    }
    assert receipt["evidence_completeness"] == {
        "official_recording_evaluated": False,
        "receipt_complete": False,
        "recording_verified": False,
        "run_evidence_complete": False,
        "trace_replay_does_not_repair_sdk_recording": True,
    }
    candidate = receipt["candidate_next_submission"]
    assert isinstance(candidate, dict)
    assert candidate["action"] == {"coordinate": None, "name": "ACTION1"}
    assert candidate["submitted"] is False
    cancellation = receipt["cancellation_verification"]
    assert isinstance(cancellation, dict)
    assert cancellation["verified"] is True
    replay = receipt["replay_result"]
    assert isinstance(replay, dict)
    assert replay["status"] == "PASS_SEALED_TRACE_REPLAY"
    assert replay["matched_submission_count"] == 1
    assert replay["matched_regenerated_mechanics_receipt_count"] == 1
    assert replay["reset_count"] == 0
    assert replay["candidate_cancelled"] is True
    trace_receipt = receipt["trace"]
    assert isinstance(trace_receipt, dict)
    assert trace_receipt["event_count"] == 8
    assert trace_receipt["game_id"] == TRACE_GAME
    assert trace_receipt["submission_count"] == 1
    assert trace_receipt["manifest_hash"] == trace["manifest_hash"]
    assert trace_receipt["tail_event_hash"] == trace["tail_hash"]
    assert trace_receipt["replayed_from_immutable_copy"] is True
    assert trace_receipt["projection_file_count"] > 0
    assert str(trace_receipt["projection_sha256"]).startswith("sha256:")


def test_trace_replay_preserves_missing_initial_returned_action_boundary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    trace = _build_sealed_trace(tmp_path)
    returned_actions: list[ActionRequest | None] = []

    class InitialBoundaryPolicy(VisualCausalPolicy):
        def select(self, observation: Observation) -> ActionRequest:
            if not returned_actions:
                returned_actions.append(observation.returned_action)
            return super().select(observation)

    monkeypatch.setattr(replay_module, "VisualCausalPolicy", InitialBoundaryPolicy)

    receipt = _trace_replay(trace)

    method = receipt["method"]
    assert isinstance(method, dict)
    assert method["initial_returned_action"] == ("unavailable in trace schema; retained as None")
    assert receipt["boundaries"]["initial_returned_action_reconstructed"] is False
    assert returned_actions == [None]


def test_trace_replay_enforces_game_over_reset_and_level_recovery(tmp_path: Path) -> None:
    trace = _build_sealed_trace(tmp_path, include_reset_cycle=True)

    receipt = _trace_replay(trace)

    replay = receipt["replay_result"]
    assert isinstance(replay, dict)
    assert replay["matched_submission_count"] == 2
    assert replay["matched_regenerated_mechanics_receipt_count"] == 2
    assert replay["action_counts"] == {"ACTION1": 1, "RESET": 1}
    assert replay["state_counts"] == {"GAME_OVER": 1, "NOT_FINISHED": 1}
    assert replay["reset_count"] == 1


def test_trace_replay_rejects_a_validly_sealed_incomplete_cycle(tmp_path: Path) -> None:
    trace = _build_sealed_trace(tmp_path, omit_first_mechanical_receipt=True)

    with pytest.raises(MechanicalReplayError, match="complete six-event action cycles"):
        _trace_replay(trace)


def test_trace_replay_rejects_tampered_sealed_chunk(tmp_path: Path) -> None:
    trace = _build_sealed_trace(tmp_path)
    trace_path = trace["trace_path"]
    chunk = next(trace_path.glob("chunk-*.jsonl"))
    raw = chunk.read_bytes()
    chunk.write_bytes(raw.replace(b'"summary"', b'"summarx"', 1))

    with pytest.raises(MechanicalReplayError, match="integrity verification failed"):
        _trace_replay(trace)


def test_trace_replay_rejects_tampered_frame_blob_without_modifying_source(
    tmp_path: Path,
) -> None:
    trace = _build_sealed_trace(tmp_path)
    trace_path = trace["trace_path"]
    blob = next(trace_path.rglob("*.blob"))
    blob.write_bytes(b"[[1]]")
    active = trace_path / "active.jsonl"
    blob_before = blob.read_bytes()
    active_before = active.read_bytes()

    with pytest.raises(MechanicalReplayError, match="integrity verification failed"):
        _trace_replay(trace)

    assert blob.read_bytes() == blob_before
    assert active.read_bytes() == active_before


def test_trace_replay_rejects_named_manifest_or_tail_hash_mismatch(tmp_path: Path) -> None:
    trace = _build_sealed_trace(tmp_path)

    with pytest.raises(MechanicalReplayError, match="manifest hash"):
        _trace_replay(trace, manifest_hash="sha256:" + ("1" * 64))
    with pytest.raises(MechanicalReplayError, match="tail hash"):
        _trace_replay(trace, tail_hash="sha256:" + ("2" * 64))


@pytest.mark.parametrize("path_kind", ["parent-escape", "absolute"])
def test_trace_replay_rejects_escaping_manifest_compressed_copy_path(
    tmp_path: Path,
    path_kind: str,
) -> None:
    trace = _build_sealed_trace(tmp_path)
    trace_path = trace["trace_path"]
    outside = tmp_path / "outside.gz"
    outside.write_bytes(b"external-compressed-copy")
    manifest_path = trace_path / "manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    compressed_copy_path = "../outside.gz" if path_kind == "parent-escape" else str(outside)
    manifest["chunks"][0]["compressed_copy_path"] = compressed_copy_path
    manifest["chunks"][0]["compressed_copy_hash"] = (
        "sha256:" + hashlib.sha256(outside.read_bytes()).hexdigest()
    )
    unsigned = {key: value for key, value in manifest.items() if key != "manifest_hash"}
    manifest["manifest_hash"] = sha256_json(unsigned)
    manifest_path.write_bytes(json.dumps(manifest, sort_keys=True).encode("utf-8"))

    with pytest.raises(MechanicalReplayError, match="compressed_copy_path"):
        _trace_replay(trace)


def test_trace_replay_revalidates_copied_manifest_immediately_before_journal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    trace = _build_sealed_trace(tmp_path)
    source_path = trace["trace_path"].resolve()
    original_projection = replay_module._sealed_trace_projection
    copied_manifest_swapped = False

    def projection_with_post_snapshot_swap(path: Path) -> tuple[dict[str, str], int]:
        nonlocal copied_manifest_swapped
        projection = original_projection(path)
        if path.resolve() != source_path and not copied_manifest_swapped:
            manifest_path = path / "manifest.json"
            manifest = json.loads(manifest_path.read_bytes())
            manifest["chunks"][0]["compressed_copy_path"] = "../external-copy.gz"
            manifest["chunks"][0]["compressed_copy_hash"] = "sha256:" + ("0" * 64)
            unsigned = {key: value for key, value in manifest.items() if key != "manifest_hash"}
            manifest["manifest_hash"] = sha256_json(unsigned)
            manifest_path.write_bytes(json.dumps(manifest, sort_keys=True).encode("utf-8"))
            copied_manifest_swapped = True
        return projection

    class JournalMustNotOpen:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            raise AssertionError("EventJournal opened before copied-manifest revalidation")

    monkeypatch.setattr(
        replay_module,
        "_sealed_trace_projection",
        projection_with_post_snapshot_swap,
    )
    monkeypatch.setattr(replay_module, "EventJournal", JournalMustNotOpen)

    with pytest.raises(MechanicalReplayError, match="compressed_copy_path"):
        _trace_replay(trace)

    assert copied_manifest_swapped is True


def test_trace_replay_rejects_reset_without_not_finished_recovery(tmp_path: Path) -> None:
    trace = _build_sealed_trace(
        tmp_path,
        include_reset_cycle=True,
        reset_recovery_state=GameStateName.GAME_OVER,
    )

    with pytest.raises(MechanicalReplayError, match="does not preserve level recovery"):
        _trace_replay(trace)


def test_trace_replay_refuses_authoritative_win_in_an_unfinished_trace(tmp_path: Path) -> None:
    trace = _build_sealed_trace(tmp_path, first_after_state=GameStateName.WIN)

    with pytest.raises(MechanicalReplayError, match="authoritative WIN"):
        _trace_replay(trace)


def test_trace_replay_rejects_initial_observation_without_full_reset(tmp_path: Path) -> None:
    trace = _build_sealed_trace(tmp_path, initial_full_reset=False)

    with pytest.raises(MechanicalReplayError, match="initial observation is not marked full_reset"):
        _trace_replay(trace)


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
    assert family_state["hierarchy_residual_linked_relation_rejected_count"] == 0
    assert family_state["hierarchy_external_residual_linked_relation_rejected_count"] == 0
    assert family_state["hierarchy_raw_matching_composite_relation_rejected_count"] == 0
    assert family_state["hierarchy_external_own_composite_relation_rejected_count"] == 0
    assert family_state["hierarchy_preterminal_retry_count"] == 0


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
