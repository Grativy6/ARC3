from __future__ import annotations

import json
import random
from pathlib import Path

import pytest

from arc3.errors import CheckpointError
from arc3.trace import (
    CheckpointStore,
    CodeIdentity,
    EventJournal,
    SourceIdentity,
    TraceEvent,
    rebuild_index,
)

CONFIG_HASH = "sha256:" + "1" * 64
TRACE_HASH = "sha256:" + "2" * 64
SOURCE = SourceIdentity("synthetic_test", "1")
CODE = CodeIdentity("abc123", CONFIG_HASH)


def make_event(
    *,
    event_id: str,
    event_type: str,
    payload: dict[str, object],
    previous: str | None,
) -> TraceEvent:
    return TraceEvent.create(
        run_id="run-1",
        episode_id="episode-1",
        game_id="synthetic-redacted",
        level_index=0,
        step_index=0,
        event_type=event_type,
        source=SOURCE,
        scope="episode",
        payload=payload,
        code_identity=CODE,
        previous_event_hash=previous,
        event_id=event_id,
        occurred_at="2026-08-21T00:00:00Z",
        recorded_at="2026-08-21T00:00:00Z",
    )


def test_checkpoint_restores_rng_and_derived_state_exactly(tmp_path: Path) -> None:
    rng = random.Random(742)
    assert rng.random() >= 0.0
    store = CheckpointStore(tmp_path / "checkpoints")
    path, envelope = store.write(
        run_id="run-1",
        episode_id="episode-1",
        trace_tail_event_id="E-TAIL",
        trace_tail_hash=TRACE_HASH,
        git_commit="abc123",
        config_hash=CONFIG_HASH,
        rng=rng,
        state={
            "hypothesis_registry": {"H-1": {"status": "candidate"}},
            "world_model_ensemble": {},
            "goal_registry": {},
            "state_graph": {},
            "current_plan": None,
            "memory_indices": {},
            "unresolved_residuals": ["ACTION1 effect remains ambiguous"],
        },
    )
    expected_numbers = [rng.random() for _ in range(5)]

    restored = store.restore(
        path=path,
        expected_run_id="run-1",
        expected_episode_id="episode-1",
        expected_trace_tail_event_id="E-TAIL",
        expected_trace_tail_hash=TRACE_HASH,
        expected_git_commit="abc123",
        expected_config_hash=CONFIG_HASH,
    )
    assert [restored.rng.random() for _ in range(5)] == expected_numbers
    assert restored.state == envelope.state
    assert restored.state["unresolved_residuals"] == ["ACTION1 effect remains ambiguous"]


def test_checkpoint_wrong_config_and_content_tamper_are_rejected(tmp_path: Path) -> None:
    store = CheckpointStore(tmp_path / "checkpoints")
    path, _ = store.write(
        run_id="run-1",
        episode_id="episode-1",
        trace_tail_event_id="E-TAIL",
        trace_tail_hash=TRACE_HASH,
        git_commit="abc123",
        config_hash=CONFIG_HASH,
        rng=random.Random(1),
        state={"counter": 4},
    )
    with pytest.raises(CheckpointError, match="config_hash"):
        store.restore(
            path=path,
            expected_run_id="run-1",
            expected_episode_id="episode-1",
            expected_trace_tail_event_id="E-TAIL",
            expected_trace_tail_hash=TRACE_HASH,
            expected_git_commit="abc123",
            expected_config_hash="sha256:" + "3" * 64,
        )

    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["state"]["counter"] = 5
    path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(CheckpointError, match="hash mismatch"):
        store.load(path)


def test_checkpoint_rejection_is_receipted_without_modifying_file(tmp_path: Path) -> None:
    journal = EventJournal(tmp_path / "trace", run_id="run-1")
    tail = journal.append(
        episode_id="episode-1",
        game_id="synthetic-redacted",
        level_index=0,
        step_index=0,
        event_type="run.started",
        source=SOURCE,
        scope="run",
        payload={},
        code_identity=CODE,
        event_id="E-TAIL",
    )
    store = CheckpointStore(tmp_path / "checkpoints")
    path, _ = store.write(
        run_id="run-1",
        episode_id="episode-1",
        trace_tail_event_id=tail.event_id,
        trace_tail_hash=tail.event_hash,
        git_commit=CODE.git_commit,
        config_hash=CODE.config_hash,
        rng=random.Random(1),
        state={"counter": 4},
    )
    before = path.read_bytes()
    incompatible_code = CodeIdentity("abc123", "sha256:" + "3" * 64)
    restored = store.restore_with_journal_receipt(
        journal=journal,
        episode_id="episode-1",
        game_id="synthetic-redacted",
        level_index=0,
        step_index=0,
        source=SOURCE,
        code_identity=incompatible_code,
        path=path,
    )
    assert restored is None
    assert path.read_bytes() == before
    assert journal.tail_event_id is not None
    assert journal.verify_manifest()[-1].event_type == "run.checkpoint_rejected"
    journal.close()


def test_derived_index_rebuild_is_deterministic_and_keeps_rejections() -> None:
    created = make_event(
        event_id="E-CREATE",
        event_type="hypothesis.created",
        payload={
            "hypothesis_id": "H-1",
            "status": "candidate",
            "parent_ids": [],
            "scope": "game",
        },
        previous=None,
    )
    contradicted = make_event(
        event_id="E-CONTRA",
        event_type="hypothesis.contradicted",
        payload={"hypothesis_id": "H-1", "evidence_event_ids": [created.event_id]},
        previous=created.event_hash,
    )
    rejected = make_event(
        event_id="E-REJECT",
        event_type="hypothesis.rejected",
        payload={"hypothesis_id": "H-1"},
        previous=contradicted.event_hash,
    )
    first = rebuild_index([created, contradicted, rejected])
    second = rebuild_index([created, contradicted, rejected])

    assert first.canonical_snapshot() == second.canonical_snapshot()
    assert first.hypothesis("H-1") is not None
    assert first.hypothesis("H-1").status == "rejected"  # type: ignore[union-attr]
    assert [item.hypothesis_id for item in first.rejected_hypotheses()] == ["H-1"]
