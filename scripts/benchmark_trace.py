"""Run the reproducible Stage 03 trace-ledger microbenchmark."""

from __future__ import annotations

import argparse
import json
import random
import tempfile
import time
import tracemalloc
from datetime import UTC, datetime
from pathlib import Path

from arc3.trace import BlobStore, CheckpointStore, CodeIdentity, EventJournal, SourceIdentity


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--git-commit", required=True)
    parser.add_argument("--events", type=int, default=500)
    parser.add_argument("--frame-repeats", type=int, default=100)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.events <= 0 or args.frame_repeats <= 0:
        raise SystemExit("events and frame-repeats must be positive")
    started_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    with tempfile.TemporaryDirectory(prefix="arc3-trace-bench-") as raw:
        root = Path(raw)
        source = SourceIdentity("synthetic_trace_benchmark", "1")
        code = CodeIdentity(args.git_commit, "sha256:" + "1" * 64)
        journal = EventJournal(
            root / "trace",
            run_id="stage03-benchmark",
            flush_every=100,
            fsync_on_flush=False,
        )
        tracemalloc.start()
        started = time.perf_counter()
        for step in range(args.events):
            journal.append(
                episode_id="episode-1",
                game_id="synthetic-redacted",
                level_index=0,
                step_index=step,
                event_type="run.environment_fault",
                source=source,
                scope="run",
                payload={"fault": "synthetic-noop", "ordinal": step},
                code_identity=code,
                event_id=f"E-{step:06d}",
                occurred_at="2026-08-21T00:00:00Z",
            )
        journal.flush()
        append_seconds = time.perf_counter() - started
        _, peak_bytes = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        started = time.perf_counter()
        events = journal.verify_manifest()
        retrieval_seconds = time.perf_counter() - started

        frame = tuple(tuple((x + y) % 4 for x in range(64)) for y in range(64))
        blobs = BlobStore(root / "frame-blobs")
        first_frame = blobs.put_frame(frame)
        duplicate_creations = 0
        started = time.perf_counter()
        for _ in range(args.frame_repeats):
            duplicate_creations += int(blobs.put_frame(frame).created)
        dedup_seconds = time.perf_counter() - started

        checkpoint_path, checkpoint = CheckpointStore(root / "checkpoints").write(
            run_id="stage03-benchmark",
            episode_id="episode-1",
            trace_tail_event_id=journal.tail_event_id or "",
            trace_tail_hash=journal.tail_hash or "",
            git_commit=code.git_commit,
            config_hash=code.config_hash,
            rng=random.Random(17),
            state={
                "step": args.events,
                "active_hypotheses": ["H-1"],
                "world_model": {"objects": 3},
            },
        )
        result = {
            "schema": "arc3.trace.benchmark.v0.1",
            "label": "synthetic",
            "started_at": started_at,
            "completed_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "event_count": len(events),
            "append_seconds": append_seconds,
            "append_ms_per_event": append_seconds * 1000 / args.events,
            "retrieval_seconds": retrieval_seconds,
            "peak_traced_bytes": peak_bytes,
            "trace_disk_bytes": sum(
                path.stat().st_size for path in (root / "trace").rglob("*") if path.is_file()
            ),
            "frame_dimensions": [64, 64],
            "frame_canonical_bytes": first_frame.byte_length,
            "first_frame_created": first_frame.created,
            "duplicate_frame_writes": args.frame_repeats,
            "duplicate_blob_creations": duplicate_creations,
            "dedup_seconds": dedup_seconds,
            "checkpoint_bytes": checkpoint_path.stat().st_size,
            "checkpoint_hash": checkpoint.checkpoint_hash,
        }
        journal.close()
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
