from __future__ import annotations

import random
import socket
from pathlib import Path

import pytest

from arc3.trace import (
    CheckpointStore,
    CodeIdentity,
    EventJournal,
    ReplayEngine,
    SourceIdentity,
    SummaryClaim,
    identity_migrate,
    verify_migration_manifest,
)

CONFIG_HASH = "sha256:" + "1" * 64
SOURCE = SourceIdentity("arc3_synthetic_lab", "0.1")
CODE = CodeIdentity("abc123", CONFIG_HASH)


def observation(journal: EventJournal, frame: list[list[int]]) -> dict[str, object]:
    receipt = journal.blobs.put_frame(frame)
    return {
        "frame_count": 1,
        "frames": [receipt.to_payload()],
        "game_state": "NOT_FINISHED",
        "score": None,
        "available_actions": ["ACTION1", "ACTION2"],
        "upstream_metadata": {"surface": "synthetic", "seed": 17},
    }


@pytest.mark.integration
def test_full_synthetic_episode_seal_interrupt_restore_and_continue(tmp_path: Path) -> None:
    trace_root = tmp_path / "trace"
    checkpoints = CheckpointStore(tmp_path / "checkpoints")
    rng = random.Random(17)
    journal = EventJournal(trace_root, run_id="run-synthetic")
    journal.append(
        episode_id="episode-1",
        game_id="synthetic-redacted",
        level_index=0,
        step_index=0,
        event_type="run.started",
        source=SOURCE,
        scope="run",
        payload={"seed": 17, "result_surface": "synthetic"},
        code_identity=CODE,
        event_id="E-000-RUN",
    )
    journal.append(
        episode_id="episode-1",
        game_id="synthetic-redacted",
        level_index=0,
        step_index=0,
        event_type="observation.received",
        source=SOURCE,
        scope="episode",
        payload=observation(journal, [[0, 2, 0], [0, 0, 0], [0, 3, 0]]),
        code_identity=CODE,
        event_id="E-001-OBS",
    )
    journal.append(
        episode_id="episode-1",
        game_id="synthetic-redacted",
        level_index=0,
        step_index=0,
        event_type="hypothesis.created",
        source=SOURCE,
        scope="game",
        payload={
            "hypothesis_id": "H-ACTION1-UP",
            "status": "candidate",
            "scope": "game",
            "parent_ids": [],
            "statement": {"action": "ACTION1", "dy": -1},
        },
        code_identity=CODE,
        event_id="E-002-HYP",
    )
    journal.append(
        episode_id="episode-1",
        game_id="synthetic-redacted",
        level_index=0,
        step_index=1,
        event_type="simulation.prediction_emitted",
        source=SOURCE,
        scope="episode",
        payload={
            "prediction_id": "P-1",
            "action_decision_id": "A-1",
            "world_model_id": "WM-1",
            "predicted_delta": {"kind": "translation", "dy": -1},
            "probability_or_weight": 0.55,
            "alternative_rank": 1,
        },
        code_identity=CODE,
        event_id="E-003-PRED",
    )
    journal.append(
        episode_id="episode-1",
        game_id="synthetic-redacted",
        level_index=0,
        step_index=1,
        event_type="action.selected",
        source=SOURCE,
        scope="episode",
        payload={
            "selected_action": {"name": "ACTION1", "coordinate": None},
            "candidate_utilities": [
                {"action": "ACTION1", "information_gain": 0.7},
                {"action": "ACTION2", "information_gain": 0.3},
            ],
            "selected_probe_or_plan_id": "PLAN-1",
            "active_hypothesis_ids": ["H-ACTION1-UP"],
            "predicted_outcome_ids": ["P-1"],
            "active_goal_ids": ["G-REACH-3"],
            "active_world_model_ids": ["WM-1"],
            "rationale_category": "discriminate_models",
            "rationale_summary": "tests the leading vertical-motion candidate",
        },
        code_identity=CODE,
        event_id="E-004-ACTION",
    )
    mismatch = journal.append(
        episode_id="episode-1",
        game_id="synthetic-redacted",
        level_index=0,
        step_index=1,
        event_type="consequence.mismatched_prediction",
        source=SOURCE,
        scope="episode",
        payload={
            "prediction_id": "P-1",
            "residual": "the marked cell moved down rather than up",
            "invalidated_plan_ids": ["PLAN-1"],
        },
        code_identity=CODE,
        event_id="E-005-MISMATCH",
    )
    reopened = journal.append(
        episode_id="episode-1",
        game_id="synthetic-redacted",
        level_index=0,
        step_index=1,
        event_type="hypothesis.reopened",
        source=SOURCE,
        scope="game",
        payload={
            "hypothesis_id": "H-ACTION1-UP",
            "caused_by_event_ids": [mismatch.event_id],
            "previous_status": "active",
            "new_status": "candidate",
            "invalidated_plan_ids": ["PLAN-1"],
            "residual": "ACTION1 moved the salient cell in the opposite direction",
        },
        code_identity=CODE,
        event_id="E-006-REOPEN",
    )
    journal.append(
        episode_id="episode-1",
        game_id="synthetic-redacted",
        level_index=0,
        step_index=1,
        event_type="observation.received",
        source=SOURCE,
        scope="episode",
        payload=observation(journal, [[0, 0, 0], [0, 2, 0], [0, 3, 0]]),
        code_identity=CODE,
        event_id="E-007-OBS",
    )
    assert journal.tail_event_id == "E-007-OBS"
    assert journal.tail_hash is not None
    checkpoint_path, _ = checkpoints.write(
        run_id=journal.run_id,
        episode_id="episode-1",
        trace_tail_event_id=journal.tail_event_id,
        trace_tail_hash=journal.tail_hash,
        git_commit=CODE.git_commit,
        config_hash=CODE.config_hash,
        rng=rng,
        state={
            "hypothesis_registry": {"H-ACTION1-UP": {"status": "candidate"}},
            "world_model_ensemble": {"WM-1": {"status": "reopened"}},
            "goal_registry": {"G-REACH-3": {"status": "active"}},
            "state_graph": {},
            "current_plan": None,
            "memory_indices": {},
            "unresolved_residuals": ["ACTION1 direction depends on an unresolved condition"],
        },
    )
    expected_random = rng.random()
    first_chunk = journal.seal(compress=True)
    journal.close()

    # Fault injection: process termination left a partial event in the new active chunk.
    with (trace_root / "active.jsonl").open("ab") as handle:
        handle.write(b'{"schema":"arc3.trace.event.v0.1","event_id":"INTERRUPTED')

    resumed_journal = EventJournal(trace_root, run_id="run-synthetic")
    assert resumed_journal.recovery_receipt.discarded_byte_length > 0
    restored = checkpoints.restore(
        path=checkpoint_path,
        expected_run_id="run-synthetic",
        expected_episode_id="episode-1",
        expected_trace_tail_event_id=resumed_journal.tail_event_id or "",
        expected_trace_tail_hash=resumed_journal.tail_hash or "",
        expected_git_commit=CODE.git_commit,
        expected_config_hash=CODE.config_hash,
    )
    assert restored.rng.random() == expected_random
    assert restored.state["unresolved_residuals"] == [
        "ACTION1 direction depends on an unresolved condition"
    ]
    resumed_journal.append(
        episode_id="episode-1",
        game_id="synthetic-redacted",
        level_index=0,
        step_index=1,
        event_type="run.resumed",
        source=SOURCE,
        scope="run",
        payload={"checkpoint_hash": restored.envelope.checkpoint_hash},
        code_identity=CODE,
        event_id="E-008-RESUMED",
    )
    resumed_journal.append(
        episode_id="episode-1",
        game_id="synthetic-redacted",
        level_index=0,
        step_index=2,
        event_type="run.completed",
        source=SOURCE,
        scope="run",
        payload={"result_surface": "synthetic", "status": "bounded_complete"},
        code_identity=CODE,
        event_id="E-009-COMPLETE",
    )
    resumed_journal.seal()

    replay = ReplayEngine(resumed_journal)
    events = replay.verify_integrity()
    index = replay.rebuild_index()
    assert len(events) == 10
    assert index.hypothesis("H-ACTION1-UP") is not None
    assert index.hypothesis("H-ACTION1-UP").status == "candidate"  # type: ignore[union-attr]
    assert replay.rebuild_deltas()[0].changed_cell_count == 2
    summary = replay.summarize(
        generator_git_commit=CODE.git_commit,
        generator_config_hash=CODE.config_hash,
        claims=[
            SummaryClaim(
                claim="ACTION1-UP remained a candidate after contradictory evidence",
                supporting_event_ids=(reopened.event_id,),
                contradicting_event_ids=(mismatch.event_id,),
            )
        ],
        unresolved_residuals=restored.state["unresolved_residuals"],
        retrieval_tags=["synthetic", "resume", "reopening"],
    )
    assert summary.unresolved_residuals

    migration_path, manifest = identity_migrate(
        trace_root / first_chunk.path,
        tmp_path / "migration" / "chunk-v0.1.jsonl",
    )
    assert manifest.replay_equivalent is True
    assert verify_migration_manifest(migration_path) == manifest
    resumed_journal.close()


@pytest.mark.integration
def test_competition_style_trace_writes_without_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def network_forbidden(*_args: object, **_kwargs: object) -> socket.socket:
        raise AssertionError("trace subsystem attempted network access")

    monkeypatch.setattr(socket, "create_connection", network_forbidden)
    journal = EventJournal(tmp_path / "offline", run_id="offline-run")
    event = journal.append(
        episode_id="episode-1",
        game_id="redacted",
        level_index=0,
        step_index=0,
        event_type="run.started",
        source=SOURCE,
        scope="run",
        payload={"mode": "competition", "network_enabled": False},
        code_identity=CODE,
    )
    assert event.event_type == "run.started"
    journal.seal()
    assert len(journal.verify_manifest()) == 1
    journal.close()
