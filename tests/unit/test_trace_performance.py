from __future__ import annotations

import time
import tracemalloc
from pathlib import Path

from arc3.trace import CodeIdentity, EventJournal, SourceIdentity, rebuild_index

CONFIG_HASH = "sha256:" + "1" * 64
SOURCE = SourceIdentity("synthetic_performance_test", "1")
CODE = CodeIdentity("abc123", CONFIG_HASH)


def test_long_episode_append_memory_and_index_retrieval_are_bounded(tmp_path: Path) -> None:
    journal = EventJournal(
        tmp_path / "trace",
        run_id="run-performance",
        flush_every=100,
        fsync_on_flush=False,
    )
    tracemalloc.start()
    started = time.perf_counter()
    for step in range(500):
        journal.append(
            episode_id="episode-1",
            game_id="synthetic-redacted",
            level_index=0,
            step_index=step,
            event_type="run.environment_fault",
            source=SOURCE,
            scope="run",
            payload={"fault": "synthetic-noop", "ordinal": step},
            code_identity=CODE,
            event_id=f"E-{step:06d}",
        )
    journal.flush()
    append_seconds = time.perf_counter() - started
    _, peak_bytes = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    retrieval_started = time.perf_counter()
    index = rebuild_index(journal.verify_manifest())
    retrieval_seconds = time.perf_counter() - retrieval_started

    assert len(index.event_order) == 500
    assert append_seconds / 500 < 0.02
    assert retrieval_seconds < 2.0
    assert peak_bytes < 32 * 1024 * 1024
    journal.close()
