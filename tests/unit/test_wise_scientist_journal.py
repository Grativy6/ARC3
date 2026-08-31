from __future__ import annotations

import json
from pathlib import Path

import pytest

from arc3.errors import TraceIntegrityError
from arc3.wise_scientist import WiseJournal


def test_wise_journal_round_trip_and_hash_linkage(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    journal = WiseJournal(path)
    first = journal.append("run.started", {"objective": "WIN"})
    second = journal.append("observation.recorded", {"state": "NOT_FINISHED"})

    verified = WiseJournal.verify(path)
    assert verified == (first, second)
    assert second.previous_event_hash == first.event_hash
    assert WiseJournal(path).tail_hash == second.event_hash


def test_wise_journal_detects_tampering_and_partial_lines(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    journal = WiseJournal(path)
    journal.append("run.started", {"objective": "WIN"})
    parsed = json.loads(path.read_text(encoding="utf-8"))
    parsed["payload"]["objective"] = "NOT_WIN"
    path.write_text(json.dumps(parsed) + "\n", encoding="utf-8")

    with pytest.raises(TraceIntegrityError, match="hash mismatch"):
        WiseJournal.verify(path)

    partial = tmp_path / "partial.jsonl"
    partial.write_bytes(b'{"schema":"incomplete"}')
    with pytest.raises(TraceIntegrityError, match="incomplete"):
        WiseJournal.verify(partial)
