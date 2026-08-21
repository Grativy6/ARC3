"""Baseline-to-ledger integration preserves complete action context."""

from __future__ import annotations

from pathlib import Path

from arc3.adapters.synthetic import SYNTHETIC_GAME_ID, SyntheticAdapter
from arc3.baseline_runner import run_baseline_episode
from arc3.policy.baselines import ActionCyclePolicy
from arc3.trace import (
    BaselineTraceSink,
    CodeIdentity,
    EventJournal,
    ReplayEngine,
    SourceIdentity,
)


def test_every_baseline_action_has_observation_selection_and_consequence_receipts(
    tmp_path: Path,
) -> None:
    root = tmp_path / "trace"
    journal = EventJournal(root, run_id="run-traced-baseline", fsync_on_flush=False)
    sink = BaselineTraceSink(
        journal=journal,
        episode_id="episode-1",
        source=SourceIdentity("synthetic_environment", "arc3.synthetic.v1"),
        code_identity=CodeIdentity("test-commit", "sha256:" + "1" * 64),
    )
    session = SyntheticAdapter(seed=3, max_steps=16).open(SYNTHETIC_GAME_ID)

    result = run_baseline_episode(
        session,
        ActionCyclePolicy(),
        max_actions=4,
        max_resets=2,
        receipt_sink=sink,
    )
    journal.flush()
    events = tuple(journal.iter_events())
    journal.close()

    event_types = [event.event_type for event in events]
    assert event_types.count("observation.received") == len(result.receipts) + 1
    assert event_types.count("action.candidates_generated") == len(result.receipts)
    assert event_types.count("action.selected") == len(result.receipts)
    assert event_types.count("action.submitted") == len(result.receipts)
    assert event_types.count("consequence.received") == len(result.receipts)
    assert all(
        event.payload.get("rationale_category") == "baseline"
        for event in events
        if event.event_type == "action.selected"
    )

    reopened = EventJournal(root, run_id="run-traced-baseline", fsync_on_flush=False)
    replay = ReplayEngine(reopened)
    assert replay.verify_integrity(verify_blobs=True) == tuple(reopened.iter_events())
    assert len(replay.replay_frames()) == len(result.receipts) + 1
    reopened.close()
