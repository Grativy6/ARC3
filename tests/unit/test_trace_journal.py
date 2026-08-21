from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from arc3.errors import TraceIntegrityError
from arc3.trace import BlobStore, CodeIdentity, EventJournal, SourceIdentity, TraceEvent
from arc3.trace.canonical import sha256_json

CONFIG_HASH = "sha256:" + "1" * 64
SOURCE = SourceIdentity("synthetic_test", "1")
CODE = CodeIdentity("abc123", CONFIG_HASH)


def append_started(journal: EventJournal, *, event_id: str = "E-START") -> TraceEvent:
    return journal.append(
        episode_id="episode-1",
        game_id="synthetic-redacted",
        level_index=0,
        step_index=0,
        event_type="run.started",
        source=SOURCE,
        scope="run",
        payload={"seed": 11},
        code_identity=CODE,
        event_id=event_id,
        occurred_at="2026-08-21T00:00:00Z",
    )


def test_blob_store_deduplicates_frames_and_detects_missing_blob(tmp_path: Path) -> None:
    store = BlobStore(tmp_path / "blobs")
    first = store.put_frame([[0, 1], [1, 0]])
    second = store.put_frame([[0, 1], [1, 0]])

    assert first.created is True
    assert second.created is False
    assert first.blob_hash == second.blob_hash == first.frame_hash
    assert store.get_frame(first.blob_hash) == ((0, 1), (1, 0))

    store.path_for(first.blob_hash).unlink()
    with pytest.raises(TraceIntegrityError, match="missing trace blob"):
        store.get_frame(first.blob_hash)


def test_append_reopen_and_partial_line_recovery(tmp_path: Path) -> None:
    root = tmp_path / "trace"
    journal = EventJournal(root, run_id="run-1")
    first = append_started(journal)
    journal.append(
        episode_id="episode-1",
        game_id="synthetic-redacted",
        level_index=0,
        step_index=0,
        event_type="run.environment_fault",
        source=SOURCE,
        scope="run",
        payload={"category": "injected_interrupt"},
        code_identity=CODE,
        event_id="E-FAULT",
    )
    journal.close()

    with (root / "active.jsonl").open("ab") as handle:
        handle.write(b'{"schema":"arc3.trace.event.v0.1","event_id":"PARTIAL')

    resumed = EventJournal(root, run_id="run-1")
    assert resumed.recovery_receipt.discarded_byte_length > 0
    assert [item.event_id for item in resumed.verify_manifest()] == ["E-START", "E-FAULT"]
    assert resumed.get_event("E-START") == first
    assert resumed.get_event("missing") is None
    assert resumed.tail_event is not None
    assert resumed.tail_event.event_id == "E-FAULT"
    assert resumed.tail_hash != first.event_hash
    appended = resumed.append(
        episode_id="episode-1",
        game_id="synthetic-redacted",
        level_index=0,
        step_index=0,
        event_type="run.resumed",
        source=SOURCE,
        scope="run",
        payload={"recovered_to": "E-FAULT"},
        code_identity=CODE,
        event_id="E-RESUMED",
    )
    assert resumed.event_count == 3
    assert resumed.get_event("E-RESUMED") == appended
    assert resumed.tail_event == appended
    resumed.close()


@pytest.mark.parametrize("remove_uncompressed", [False, True])
def test_sealed_gzip_chunk_and_manifest_round_trip(
    tmp_path: Path, remove_uncompressed: bool
) -> None:
    root = tmp_path / "trace"
    journal = EventJournal(root, run_id="run-1")
    append_started(journal)
    entry = journal.seal(compress=True, remove_uncompressed=remove_uncompressed)
    assert entry.event_count == 1
    assert entry.compression == ("gzip" if remove_uncompressed else None)
    assert len(journal.verify_manifest()) == 1
    journal.close()

    reopened = EventJournal(root, run_id="run-1")
    assert reopened.manifest.chunks[0].chunk_hash == entry.chunk_hash
    assert [item.event_id for item in reopened.verify_manifest()] == ["E-START"]
    reopened.close()


def test_corrupt_byte_in_sealed_chunk_is_detected(tmp_path: Path) -> None:
    root = tmp_path / "trace"
    journal = EventJournal(root, run_id="run-1")
    append_started(journal)
    entry = journal.seal()
    journal.close()

    chunk_path = root / entry.path
    content = bytearray(chunk_path.read_bytes())
    content[len(content) // 2] ^= 1
    chunk_path.write_bytes(content)

    with pytest.raises(TraceIntegrityError, match="stored chunk identity mismatch"):
        EventJournal(root, run_id="run-1")


def test_duplicate_event_id_and_broken_previous_hash_are_rejected(tmp_path: Path) -> None:
    journal = EventJournal(tmp_path / "trace", run_id="run-1")
    first = append_started(journal)
    duplicate = TraceEvent.create(
        run_id="run-1",
        episode_id="episode-1",
        game_id="synthetic-redacted",
        level_index=0,
        step_index=0,
        event_type="run.resumed",
        source=SOURCE,
        scope="run",
        payload={},
        code_identity=CODE,
        previous_event_hash=first.event_hash,
        event_id=first.event_id,
    )
    with pytest.raises(TraceIntegrityError, match="duplicate event_id"):
        journal.append_event(duplicate)

    broken = replace(duplicate, event_id="E-BROKEN", previous_event_hash="sha256:" + "9" * 64)
    broken = replace(broken, event_hash=sha256_json(broken.to_dict(include_hash=False)))
    with pytest.raises(TraceIntegrityError, match="does not match journal tail"):
        journal.append_event(broken)
    journal.close()


def test_missing_referenced_frame_blob_is_detected(tmp_path: Path) -> None:
    journal = EventJournal(tmp_path / "trace", run_id="run-1")
    frame = journal.blobs.put_frame([[0, 1], [1, 0]])
    journal.append(
        episode_id="episode-1",
        game_id="synthetic-redacted",
        level_index=0,
        step_index=0,
        event_type="observation.received",
        source=SOURCE,
        scope="episode",
        payload={
            "frame_count": 1,
            "frames": [frame.to_payload()],
            "game_state": "NOT_FINISHED",
            "score": None,
            "available_actions": ["ACTION1"],
            "upstream_metadata": {},
        },
        code_identity=CODE,
    )
    journal.blobs.path_for(frame.blob_hash).unlink()
    with pytest.raises(TraceIntegrityError, match="missing trace blob"):
        journal.verify_referenced_blobs()
    journal.close()
