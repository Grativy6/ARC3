from __future__ import annotations

from pathlib import Path

import pytest

from arc3.adapters import GridFrame, Observation
from arc3.adapters.synthetic import SYNTHETIC_GAME_ID, SyntheticAdapter
from arc3.config import ARC3Config, BudgetConfig
from arc3.errors import PolicyError
from arc3.policy import ARC3Controller, ControllerPhase, ControllerPreset, RunContext
from arc3.trace import EventJournal, verify_event_chain
from arc3.types import ActionName, EnvironmentMode, GameId, GameStateName


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
    checkpoint = original.checkpoint()
    event_count = original.journal.event_count
    original.close()

    restored = ARC3Controller.restore(
        context,
        preset=ControllerPreset.FULL,
        checkpoint_path=checkpoint.path,
    )
    assert restored.phase is ControllerPhase.AWAITING_CONSEQUENCE
    assert restored.snapshot.pending_action == decision.action
    assert restored.journal.event_count == event_count
    with pytest.raises(PolicyError, match="do not resubmit"):
        restored.choose_action()
    assert restored.journal.event_count == event_count

    receipt = restored.apply_consequence(session.step(decision.action))
    assert receipt.phase is ControllerPhase.OBSERVED
    assert restored.snapshot.pending_action is None
    assert restored.journal.event_count > event_count

    actions = 1
    while restored.phase not in {ControllerPhase.COMPLETE, ControllerPhase.GAME_OVER}:
        continued = restored.choose_action()
        restored.apply_consequence(session.step(continued.action))
        actions += 1
        assert actions <= 16
    assert restored.phase is ControllerPhase.COMPLETE
    assert restored.snapshot.fault_count == 0


@pytest.mark.replay
def test_pending_plan_and_prediction_restore_exactly(tmp_path: Path) -> None:
    session = SyntheticAdapter(seed=23, size=8, max_steps=32).open(SYNTHETIC_GAME_ID)
    context = _context(tmp_path)
    original = ARC3Controller(ControllerPreset.FULL)
    original.reset(context)
    original.observe(session.observation)
    probe = original.choose_action()
    original.apply_consequence(session.step(probe.action))
    planned = original.choose_action()
    assert planned.rationale_summary == "bounded A* plan under retrodicted model"
    assert planned.prediction_receipt_id is not None
    checkpoint = original.checkpoint()
    expected = original.snapshot
    event_count = original.journal.event_count
    original.close()

    restored = ARC3Controller.restore(
        context,
        preset=ControllerPreset.FULL,
        checkpoint_path=checkpoint.path,
    )
    assert restored.snapshot.phase is ControllerPhase.AWAITING_CONSEQUENCE
    assert restored.snapshot.pending_action == expected.pending_action == planned.action
    assert restored.snapshot.actions_used == expected.actions_used == 1
    assert restored.journal.event_count == event_count
    receipt = restored.apply_consequence(session.step(planned.action))
    assert receipt.matched_prediction is not None
    assert restored.snapshot.actions_used == 2


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
    assert before[-1].event_type == "run.completed"
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
