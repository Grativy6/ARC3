from __future__ import annotations

import json
import random
from pathlib import Path
from typing import cast

import pytest

from arc3.adapters import GridFrame, Observation
from arc3.adapters.synthetic import SYNTHETIC_GAME_ID, SyntheticAdapter
from arc3.config import ARC3Config, BudgetConfig
from arc3.errors import PolicyError, TraceIntegrityError
from arc3.memory import MemoryContractError
from arc3.policy import ARC3Controller, ControllerPhase, ControllerPreset, RunContext
from arc3.trace import (
    CheckpointStore,
    EventJournal,
    ReplayEngine,
    authoritative_events,
    verify_event_chain,
)
from arc3.types import ActionName, EnvironmentMode, GameId, GameStateName, JSONValue


def _context(tmp_path: Path) -> RunContext:
    return RunContext(
        run_id="controller-resume",
        episode_id="controller-resume-episode",
        game_id=SYNTHETIC_GAME_ID,
        trace_root=tmp_path / "trace",
        checkpoint_root=tmp_path / "checkpoint",
        config=ARC3Config(
            mode=EnvironmentMode.SYNTHETIC,
            seed=23,
            profile="controller-resume",
            budgets=BudgetConfig(max_actions=16),
        ),
        git_commit="controller-resume",
    )


@pytest.mark.replay
def test_pending_action_checkpoint_restores_without_resubmission(tmp_path: Path) -> None:
    session = SyntheticAdapter(seed=23, size=8, max_steps=32).open(SYNTHETIC_GAME_ID)
    context = _context(tmp_path)
    original = ARC3Controller(ControllerPreset.FULL)
    original.reset(context)
    original.observe(session.observation)
    decision = original.choose_action()
    assert decision.action.name is ActionName.ACTION1
    assert original.action_calibration_projection["pending_handle"] == "ACTION1"
    checkpoint = original.checkpoint()
    expected_registry = original.action_effect_projection
    expected_calibration = original.action_calibration_projection
    event_count = original.journal.event_count
    checkpoint_tail = original.journal.tail_event
    assert checkpoint_tail is not None
    assert checkpoint_tail.event_type == "run.checkpoint_written"
    assert checkpoint_tail.payload["checkpoint_hash"] == checkpoint.envelope.checkpoint_hash
    assert checkpoint_tail.payload["pending_submitted_event_id"] == decision.submitted_event_id
    original.close()

    restored = ARC3Controller.restore(
        context,
        preset=ControllerPreset.FULL,
        checkpoint_path=checkpoint.path,
    )
    assert restored.phase is ControllerPhase.AWAITING_CONSEQUENCE
    assert restored.snapshot.pending_action == decision.action
    assert restored.action_effect_projection == expected_registry
    assert restored.action_calibration_projection == expected_calibration
    assert restored.journal.event_count == event_count
    with pytest.raises(PolicyError, match="do not resubmit"):
        restored.choose_action()
    assert restored.journal.event_count == event_count

    receipt = restored.apply_consequence(session.step(decision.action))
    assert receipt.phase is ControllerPhase.OBSERVED
    assert restored.snapshot.pending_action is None
    assert restored.action_calibration_projection["completed_handles"] == ["ACTION1"]
    assert restored.action_effect_projection["observation_counts"]["ACTION1"] == 1
    assert restored.journal.event_count > event_count
    assert (
        sum(
            event.event_type == "consequence.received"
            and event.payload.get("submitted_event_id") == decision.submitted_event_id
            for event in restored.journal.verify_manifest()
        )
        == 1
    )

    actions = 1
    while restored.phase not in {ControllerPhase.COMPLETE, ControllerPhase.GAME_OVER}:
        continued = restored.choose_action()
        restored.apply_consequence(session.step(continued.action))
        actions += 1
        assert actions <= 16
    assert restored.phase is ControllerPhase.COMPLETE
    assert restored.snapshot.fault_count == 0


@pytest.mark.replay
def test_restore_ignores_orphan_newer_latest_without_commitment_receipt(
    tmp_path: Path,
) -> None:
    context = _context(tmp_path)
    controller = ARC3Controller(ControllerPreset.FULL)
    controller.reset(context)
    observation = (
        SyntheticAdapter(seed=23, size=8, max_steps=32).open(SYNTHETIC_GAME_ID).observation
    )
    controller.observe(observation)
    controller.choose_action()
    checkpoint = controller.checkpoint()
    committed_receipt = controller.journal.tail_event
    assert committed_receipt is not None
    assert committed_receipt.event_type == "run.checkpoint_written"

    raw_checkpoint = json.loads(checkpoint.path.read_text(encoding="utf-8"))
    raw_state = cast(dict[str, JSONValue], raw_checkpoint["state"])
    orphan_path, orphan = CheckpointStore(context.checkpoint_root).write(
        run_id=context.run_id,
        episode_id=context.episode_id,
        trace_tail_event_id=committed_receipt.event_id,
        trace_tail_hash=committed_receipt.event_hash,
        git_commit=context.git_commit,
        config_hash=str(context.config.hash),
        rng=random.Random(999),
        state=raw_state,
    )
    assert orphan_path != checkpoint.path
    assert orphan.checkpoint_hash != checkpoint.envelope.checkpoint_hash
    assert (
        json.loads((context.checkpoint_root / "latest.json").read_text(encoding="utf-8"))[
            "checkpoint_hash"
        ]
        == orphan.checkpoint_hash
    )
    controller.journal.close()

    restored = ARC3Controller.restore(context, preset=ControllerPreset.FULL)
    assert restored.snapshot.phase is ControllerPhase.AWAITING_CONSEQUENCE
    assert restored.journal.tail_event_id == committed_receipt.event_id
    assert restored.journal.tail_hash == committed_receipt.event_hash


@pytest.mark.replay
def test_interrupted_derived_suffix_is_preserved_reopened_and_excluded_from_replay(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _context(tmp_path)
    session = SyntheticAdapter(seed=23, size=8, max_steps=32).open(SYNTHETIC_GAME_ID)
    controller = ARC3Controller(ControllerPreset.FULL)
    controller.reset(context)
    controller.observe(session.observation)
    original_append = controller._append

    def interrupt_after_selection(
        game_id: str,
        event_type: str,
        payload: object,
        **kwargs: object,
    ) -> object:
        event = original_append(game_id, event_type, cast(dict[str, object], payload), **kwargs)
        if event_type == "action.validated":
            raise RuntimeError("injected interruption after action.validated")
        return event

    monkeypatch.setattr(controller, "_append", interrupt_after_selection)
    with pytest.raises(RuntimeError, match="injected interruption"):
        controller.choose_action()
    interrupted_events = controller.journal.verify_manifest()
    old_selected = tuple(
        event for event in interrupted_events if event.event_type == "action.selected"
    )
    old_validated = tuple(
        event for event in interrupted_events if event.event_type == "action.validated"
    )
    assert len(old_selected) == 1
    assert len(old_validated) == 1
    assert interrupted_events[-1].event_id == old_validated[0].event_id
    controller.close()
    closed_events = EventJournal(context.trace_root, run_id=context.run_id).verify_manifest()
    assert closed_events == interrupted_events
    assert all(event.event_type != "run.completed" for event in closed_events)

    restored = ARC3Controller.restore(context, preset=ControllerPreset.FULL)
    all_events = restored.journal.verify_manifest()
    recovery = next(
        event for event in all_events if event.event_type == "reasoning.interruption_reopened"
    )
    assert old_selected[0].event_id in recovery.payload["abandoned_event_ids"]
    assert old_validated[0].event_id in recovery.payload["abandoned_event_ids"]
    authoritative_ids = {event.event_id for event in authoritative_events(all_events)}
    assert old_selected[0].event_id not in authoritative_ids
    assert old_validated[0].event_id not in authoritative_ids
    assert ReplayEngine(restored.journal).decision_inputs(step_index=0) == ()
    assert (
        old_selected[0].event_id not in ReplayEngine(restored.journal).rebuild_index().event_offsets
    )

    replacement = restored.choose_action()
    replayed = ReplayEngine(restored.journal).decision_inputs(step_index=0)
    assert tuple(item.action_event_id for item in replayed) == (replacement.selected_event_id,)


@pytest.mark.replay
def test_restore_refuses_uncertain_submitted_action_suffix(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _context(tmp_path)
    session = SyntheticAdapter(seed=23, size=8, max_steps=32).open(SYNTHETIC_GAME_ID)
    controller = ARC3Controller(ControllerPreset.FULL)
    controller.reset(context)
    controller.observe(session.observation)

    def interrupt_checkpoint() -> object:
        raise RuntimeError("injected interruption before pending-action checkpoint")

    monkeypatch.setattr(controller, "checkpoint", interrupt_checkpoint)
    with pytest.raises(RuntimeError, match="pending-action checkpoint"):
        controller.choose_action()
    assert controller.journal.tail_event is not None
    assert controller.journal.tail_event.event_type == "action.submitted"
    controller.journal.close()

    with pytest.raises(MemoryContractError, match="crosses an action"):
        ARC3Controller.restore(context, preset=ControllerPreset.FULL)


@pytest.mark.replay
def test_restore_refuses_run_lifecycle_suffix(tmp_path: Path) -> None:
    context = _context(tmp_path)
    session = SyntheticAdapter(seed=23, size=8, max_steps=32).open(SYNTHETIC_GAME_ID)
    controller = ARC3Controller(ControllerPreset.FULL)
    controller.reset(context)
    controller.observe(session.observation)
    controller._append(
        context.game_id,
        "run.aborted",
        {"reason": "test-only interrupted lifecycle boundary"},
        scope="run",
    )
    controller.journal.close()

    with pytest.raises(MemoryContractError, match="non-revisable boundary"):
        ARC3Controller.restore(context, preset=ControllerPreset.FULL)


@pytest.mark.replay
def test_partial_initial_observation_close_never_checkpoints_transient_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _context(tmp_path)
    observation = (
        SyntheticAdapter(seed=23, size=8, max_steps=32).open(SYNTHETIC_GAME_ID).observation
    )
    controller = ARC3Controller(ControllerPreset.FULL)
    controller.reset(context)
    original_append = controller._append

    def interrupt_after_raw_observation(
        game_id: str,
        event_type: str,
        payload: object,
        **kwargs: object,
    ) -> object:
        event = original_append(game_id, event_type, cast(dict[str, object], payload), **kwargs)
        if event_type == "observation.received":
            raise RuntimeError("injected interruption after raw observation")
        return event

    monkeypatch.setattr(controller, "_append", interrupt_after_raw_observation)
    with pytest.raises(RuntimeError, match="raw observation"):
        controller.observe(observation)
    interrupted_events = controller.journal.verify_manifest()
    assert interrupted_events[-1].event_type == "observation.received"
    controller.close()

    closed_events = EventJournal(context.trace_root, run_id=context.run_id).verify_manifest()
    assert closed_events == interrupted_events
    assert all(event.event_type != "run.completed" for event in closed_events)
    assert all(event.event_type != "run.checkpoint_written" for event in closed_events)


@pytest.mark.replay
def test_partial_consequence_close_preserves_uncertain_raw_suffix_without_checkpoint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _context(tmp_path)
    session = SyntheticAdapter(seed=23, size=8, max_steps=32).open(SYNTHETIC_GAME_ID)
    controller = ARC3Controller(ControllerPreset.FULL)
    controller.reset(context)
    controller.observe(session.observation)
    decision = controller.choose_action()
    after = session.step(decision.action)
    checkpoint = controller._last_checkpoint
    assert checkpoint is not None

    def interrupt_before_returned_observation(*args: object, **kwargs: object) -> object:
        del args, kwargs
        raise RuntimeError("injected interruption after consequence receipt")

    monkeypatch.setattr(controller, "_record_observation", interrupt_before_returned_observation)
    with pytest.raises(RuntimeError, match="consequence receipt"):
        controller.apply_consequence(after)
    interrupted_events = controller.journal.verify_manifest()
    assert interrupted_events[-1].event_type == "consequence.received"
    controller.close()
    closed_events = EventJournal(context.trace_root, run_id=context.run_id).verify_manifest()
    assert closed_events == interrupted_events

    with pytest.raises(MemoryContractError):
        ARC3Controller.restore(
            context,
            preset=ControllerPreset.FULL,
            checkpoint_path=checkpoint.path,
        )


@pytest.mark.replay
def test_malformed_pending_consequence_close_preserves_parse_failure_boundary(
    tmp_path: Path,
) -> None:
    context = _context(tmp_path)
    session = SyntheticAdapter(seed=23, size=8, max_steps=32).open(SYNTHETIC_GAME_ID)
    controller = ARC3Controller(ControllerPreset.FULL)
    controller.reset(context)
    controller.observe(session.observation)
    controller.choose_action()
    checkpoint = controller._last_checkpoint
    assert checkpoint is not None

    with pytest.raises(PolicyError, match="malformed observation"):
        controller.apply_consequence(object())
    interrupted_events = controller.journal.verify_manifest()
    assert interrupted_events[-1].event_type == "observation.parse_failed"
    controller.close()
    closed_events = EventJournal(context.trace_root, run_id=context.run_id).verify_manifest()
    assert closed_events == interrupted_events

    with pytest.raises(MemoryContractError):
        ARC3Controller.restore(
            context,
            preset=ControllerPreset.FULL,
            checkpoint_path=checkpoint.path,
        )


@pytest.mark.replay
def test_authority_projection_refuses_recovery_that_hides_a_raw_observation(
    tmp_path: Path,
) -> None:
    context = _context(tmp_path)
    session = SyntheticAdapter(seed=23, size=8, max_steps=32).open(SYNTHETIC_GAME_ID)
    controller = ARC3Controller(ControllerPreset.FULL)
    controller.reset(context)
    controller.observe(session.observation)
    events = controller.journal.verify_manifest()
    checkpoint_index = max(
        index for index, event in enumerate(events) if event.event_type == "run.checkpoint_written"
    )
    checkpoint = events[checkpoint_index]
    source_observation = next(
        event for event in events if event.event_type == "observation.received"
    )
    controller._append(
        context.game_id,
        "observation.received",
        source_observation.payload,
        scope=source_observation.scope,
    )
    before_recovery = controller.journal.verify_manifest()
    suffix = before_recovery[checkpoint_index + 1 :]
    controller._append(
        context.game_id,
        "reasoning.interruption_reopened",
        {
            "checkpoint_commitment_event_id": checkpoint.event_id,
            "abandoned_event_ids": [event.event_id for event in suffix],
            "abandoned_event_hashes": [event.event_hash for event in suffix],
            "abandoned_tail_hash": suffix[-1].event_hash,
            "recovery_policy": "malicious test fixture",
        },
        scope="run",
    )

    with pytest.raises(TraceIntegrityError, match="exact safe derived suffix"):
        authoritative_events(controller.journal.verify_manifest())
    controller.journal.close()


@pytest.mark.replay
def test_pending_plan_and_prediction_restore_exactly(tmp_path: Path) -> None:
    session = SyntheticAdapter(seed=23, size=8, max_steps=32).open(SYNTHETIC_GAME_ID)
    context = _context(tmp_path)
    original = ARC3Controller(ControllerPreset.FULL)
    original.reset(context)
    original.observe(session.observation)
    for expected_name in (
        ActionName.ACTION1,
        ActionName.ACTION2,
        ActionName.ACTION3,
        ActionName.ACTION4,
    ):
        calibration = original.choose_action()
        assert calibration.action.name is expected_name
        original.apply_consequence(session.step(calibration.action))
    assert original.action_calibration_projection["cursor"] == 4
    planned = original.choose_action()
    assert planned.rationale_summary == "bounded A* plan under retrodicted model"
    assert planned.prediction_receipt_id is not None
    checkpoint = original.checkpoint()
    expected = original.snapshot
    expected_registry = original.action_effect_projection
    expected_calibration = original.action_calibration_projection
    event_count = original.journal.event_count
    original.close()

    restored = ARC3Controller.restore(
        context,
        preset=ControllerPreset.FULL,
        checkpoint_path=checkpoint.path,
    )
    assert restored.snapshot.phase is ControllerPhase.AWAITING_CONSEQUENCE
    assert restored.snapshot.pending_action == expected.pending_action == planned.action
    assert restored.snapshot.actions_used == expected.actions_used == 4
    assert restored.action_effect_projection == expected_registry
    assert restored.action_calibration_projection == expected_calibration
    assert restored.journal.event_count == event_count
    receipt = restored.apply_consequence(session.step(planned.action))
    assert receipt.matched_prediction is not None
    assert restored.snapshot.actions_used == 5


@pytest.mark.replay
def test_close_checkpoint_restores_complete_phase_without_duplicate_completion(
    tmp_path: Path,
) -> None:
    session = SyntheticAdapter(seed=7, size=8, max_steps=32).open(SYNTHETIC_GAME_ID)
    context = _context(tmp_path)
    controller = ARC3Controller(ControllerPreset.FULL)
    controller.reset(context)
    controller.observe(session.observation)
    while controller.phase is not ControllerPhase.COMPLETE:
        decision = controller.choose_action()
        controller.apply_consequence(session.step(decision.action))
    expected = controller.snapshot
    controller.close()
    before_auditor = EventJournal(context.trace_root, run_id=context.run_id)
    before = before_auditor.verify_manifest()
    before_auditor.close()
    assert before[-1].event_type == "run.checkpoint_written"
    assert before[-2].event_type == "reasoning.checkpoint_state"
    assert before[-2].payload["pending_submitted_event_id"] is None
    assert before[-3].event_type == "run.completed"
    assert sum(event.event_type == "run.completed" for event in before) == 1

    restored = ARC3Controller.restore(context, preset=ControllerPreset.FULL)
    assert restored.phase is ControllerPhase.COMPLETE
    assert restored.snapshot.step_index == expected.step_index
    assert restored.snapshot.level_index == expected.level_index
    assert restored.snapshot.actions_used == expected.actions_used
    assert restored.snapshot.resets_used == expected.resets_used
    assert restored.snapshot.fault_count == expected.fault_count
    restored.close()
    after_auditor = EventJournal(context.trace_root, run_id=context.run_id)
    after = after_auditor.verify_manifest()
    after_auditor.close()
    verify_event_chain(list(after))
    assert len(after) == len(before)
    assert sum(event.event_type == "run.completed" for event in after) == 1


@pytest.mark.replay
def test_action6_explored_coordinate_continues_after_restore(tmp_path: Path) -> None:
    context = _context(tmp_path)
    observation = Observation(
        game_id=GameId(SYNTHETIC_GAME_ID),
        frames=(GridFrame.from_rows(((0, 1, 0), (0, 0, 2), (0, 0, 0))),),
        state=GameStateName.NOT_FINISHED,
        levels_completed=0,
        win_levels=1,
        available_actions=(ActionName.ACTION6,),
    )
    controller = ARC3Controller(ControllerPreset.FULL)
    controller.reset(context)
    controller.observe(observation)
    selected = controller.choose_action()
    assert selected.action.coordinate is not None
    assert (selected.action.coordinate.x, selected.action.coordinate.y) == (3, 3)
    controller.apply_consequence(
        Observation(
            game_id=observation.game_id,
            frames=observation.frames,
            state=observation.state,
            levels_completed=0,
            win_levels=1,
            available_actions=observation.available_actions,
            returned_action=selected.action,
        )
    )
    controller.close()

    restored = ARC3Controller.restore(context, preset=ControllerPreset.FULL)
    assert restored._explored_coordinates == {selected.action.coordinate}
    continued = restored.choose_action()
    assert continued.action.coordinate is not None
    assert continued.action.coordinate != selected.action.coordinate
