from __future__ import annotations

import json
from pathlib import Path

import pytest

from arc3.memory import (
    MemoryContractError,
    MemoryKind,
    MemoryQuery,
    MemoryRecord,
    PersistentMemory,
    SourceLinkedSummary,
    opaque_game_scope,
)
from arc3.trace import (
    CodeIdentity,
    EventJournal,
    ReplayEngine,
    SourceIdentity,
    SummaryClaim,
)
from arc3.types import StateScope

CONFIG_HASH = "sha256:" + "8" * 64
CODE = CodeIdentity("memory-replay", CONFIG_HASH)
SOURCE = SourceIdentity("memory-replay", "1")


@pytest.mark.replay
def test_memory_snapshot_round_trip_preserves_source_links_and_detects_tamper(
    tmp_path: Path,
) -> None:
    journal = EventJournal(tmp_path / "trace", run_id="run-replay-memory")
    started = journal.append(
        episode_id="episode-replay",
        game_id="redacted",
        level_index=0,
        step_index=0,
        event_type="run.started",
        source=SOURCE,
        scope="run",
        payload={},
        code_identity=CODE,
        event_id="E-MEMORY-START",
    )
    contradiction = journal.append(
        episode_id="episode-replay",
        game_id="redacted",
        level_index=0,
        step_index=1,
        event_type="hypothesis.contradicted",
        source=SOURCE,
        scope="game",
        payload={"hypothesis_id": "H-1", "evidence_event_ids": [started.event_id]},
        code_identity=CODE,
        event_id="E-MEMORY-CONTRADICTION",
    )
    journal.seal()
    replay = ReplayEngine(journal)
    events = replay.verify_integrity(verify_blobs=False)
    trace_summary = replay.summarize(
        generator_git_commit=CODE.git_commit,
        generator_config_hash=CODE.config_hash,
        claims=(
            SummaryClaim(
                claim="the initial direction candidate has a counterexample",
                supporting_event_ids=(contradiction.event_id,),
                contradicting_event_ids=(started.event_id,),
            ),
        ),
        unresolved_residuals=("condition remains unknown",),
        retrieval_tags=("contradiction", "direction"),
    )
    linked = SourceLinkedSummary.from_events(trace_summary, events)
    scope = opaque_game_scope(run_scope_salt="replay", environment_scope_token="scope")
    record = MemoryRecord(
        memory_id="M-REPLAY",
        kind=MemoryKind.CONTRADICTION,
        scope=StateScope.GAME,
        summary=linked,
        game_scope_hash=scope,
        active_contradiction_ids=("H-1",),
    )
    memory = PersistentMemory()
    memory.add(record)
    snapshot = tmp_path / "memory.json"
    memory.save(snapshot)

    restored = PersistentMemory.load(snapshot)
    hits = restored.retrieve(
        MemoryQuery(
            game_scope_hash=scope,
            exact_event_id=contradiction.event_id,
            active_contradiction_ids=("H-1",),
        )
    )
    assert [hit.record.memory_id for hit in hits] == ["M-REPLAY"]
    assert hits[0].record.summary.source_event_hashes == tuple(event.event_hash for event in events)
    assert hits[0].record.summary.trace_summary.source_chunk_hashes == journal.chunk_hashes()
    hits[0].record.summary.verify_events(events)

    raw = json.loads(snapshot.read_text(encoding="utf-8"))
    raw["game_stores"][0]["store"]["slots"][0]["record"]["summary"]["source_event_hashes"][0] = (
        "sha256:" + "0" * 64
    )
    snapshot.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(MemoryContractError, match="source-link hash mismatch"):
        PersistentMemory.load(snapshot)
    journal.close()
