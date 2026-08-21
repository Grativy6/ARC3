from __future__ import annotations

from pathlib import Path

import pytest

from arc3.errors import ReplayError
from arc3.trace import (
    CodeIdentity,
    EventJournal,
    ReplayEngine,
    SourceIdentity,
    SummaryClaim,
    apply_frame_delta,
    compute_frame_delta,
    summary_from_mapping,
    validate_summary,
)

CONFIG_HASH = "sha256:" + "1" * 64
SOURCE = SourceIdentity("synthetic_test", "1")
CODE = CodeIdentity("abc123", CONFIG_HASH)


def observation_payload(journal: EventJournal, frame: list[list[int]]) -> dict[str, object]:
    receipt = journal.blobs.put_frame(frame)
    return {
        "frame_count": 1,
        "frames": [receipt.to_payload()],
        "game_state": "NOT_FINISHED",
        "score": None,
        "available_actions": ["ACTION1", "ACTION2"],
        "upstream_metadata": {"test_surface": "synthetic"},
    }


def build_replayable_journal(tmp_path: Path) -> tuple[EventJournal, str, str, str]:
    journal = EventJournal(tmp_path / "trace", run_id="run-1")
    first = journal.append(
        episode_id="episode-1",
        game_id="synthetic-redacted",
        level_index=0,
        step_index=0,
        event_type="observation.received",
        source=SOURCE,
        scope="episode",
        payload=observation_payload(journal, [[0, 1], [0, 0]]),
        code_identity=CODE,
        event_id="E-OBS-0",
    )
    selected = journal.append(
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
                {"action": "ACTION1", "utility": 0.8},
                {"action": "ACTION2", "utility": 0.2},
            ],
            "selected_probe_or_plan_id": "PROBE-1",
            "active_hypothesis_ids": ["H-MOVE"],
            "predicted_outcome_ids": ["P-MOVE-UP"],
            "active_goal_ids": ["G-PROGRESS"],
            "active_world_model_ids": ["WM-1"],
            "rationale_category": "discriminate_models",
            "rationale_summary": "distinguishes vertical from horizontal translation",
        },
        code_identity=CODE,
        event_id="E-ACTION-1",
    )
    second = journal.append(
        episode_id="episode-1",
        game_id="synthetic-redacted",
        level_index=0,
        step_index=1,
        event_type="observation.received",
        source=SOURCE,
        scope="episode",
        payload=observation_payload(journal, [[0, 0], [0, 1]]),
        code_identity=CODE,
        event_id="E-OBS-1",
    )
    journal.seal(compress=True)
    return journal, first.event_id, selected.event_id, second.event_id


@pytest.mark.replay
def test_offline_replay_reconstructs_frames_deltas_and_decision_inputs(tmp_path: Path) -> None:
    journal, _, selected_id, _ = build_replayable_journal(tmp_path)
    replay = ReplayEngine(journal)

    frames = replay.replay_frames()
    assert [item.frame for item in frames] == [((0, 1), (0, 0)), ((0, 0), (0, 1))]
    assert replay.render_frame(frames[0].frame_hash) == "01\n00"

    deltas = replay.rebuild_deltas()
    assert len(deltas) == 1
    assert deltas[0].changed_cell_count == 2
    assert deltas[0].changed_bbox == (1, 0, 1, 1)
    assert apply_frame_delta(frames[0].frame, deltas[0]) == frames[1].frame

    decisions = replay.decision_inputs(step_index=1, episode_id="episode-1")
    assert len(decisions) == 1
    assert decisions[0].action_event_id == selected_id
    assert decisions[0].observation_event_id == "E-OBS-0"
    assert decisions[0].active_hypothesis_ids == ("H-MOVE",)
    assert decisions[0].rationale_category == "discriminate_models"
    journal.close()


@pytest.mark.replay
def test_source_cited_summary_round_trip_preserves_residuals(tmp_path: Path) -> None:
    journal, first_id, selected_id, _ = build_replayable_journal(tmp_path)
    replay = ReplayEngine(journal)
    summary = replay.summarize(
        generator_git_commit="abc123",
        generator_config_hash=CONFIG_HASH,
        claims=[
            SummaryClaim(
                claim={"candidate": "ACTION1 may move the marked cell downward"},
                supporting_event_ids=(selected_id,),
                contradicting_event_ids=(first_id,),
            )
        ],
        unresolved_residuals=[
            {"residual": "one transition cannot establish generic action semantics"}
        ],
        retrieval_tags=["synthetic", "action-semantics"],
    )
    parsed = summary_from_mapping(summary.to_dict())
    source_events = journal.verify_manifest()
    validate_summary(parsed, source_events)

    assert parsed.to_dict() == summary.to_dict()
    assert parsed.unresolved_residuals == (
        {"residual": "one transition cannot establish generic action semantics"},
    )

    with pytest.raises(ReplayError, match="unknown events"):
        replay.summarize(
            generator_git_commit="abc123",
            generator_config_hash=CONFIG_HASH,
            claims=[SummaryClaim(claim="bad", supporting_event_ids=("E-MISSING",))],
            unresolved_residuals=[],
            retrieval_tags=["synthetic"],
        )
    journal.close()


def test_delta_rejects_wrong_dimensions_and_wrong_base() -> None:
    with pytest.raises(ReplayError, match="identical dimensions"):
        compute_frame_delta([[0]], [[0, 1]])

    delta = compute_frame_delta([[0, 1]], [[1, 0]])
    with pytest.raises(ReplayError, match="base frame hash mismatch"):
        apply_frame_delta([[0, 0]], delta)
