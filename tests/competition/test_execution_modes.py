"""Build 002 execution-mode, interface-grant, and sparse-persistence contracts."""

from __future__ import annotations

import shutil
from dataclasses import replace
from pathlib import Path

import pytest

from arc3.adapters import GridFrame, Observation
from arc3.config import ARC3Config, RuntimePolicyConfig
from arc3.errors import CompetitionIntegrityError, ConfigurationError
from arc3.policy import ARC3Controller, ControllerPhase, ControllerPreset, RunContext
from arc3.trace import ReplayEngine, verify_event_chain
from arc3.types import (
    ActionName,
    ActionRequest,
    EnvironmentMode,
    ExecutionMode,
    GameId,
    GameStateName,
)


def _observation(*, returned_action: ActionRequest | None = None) -> Observation:
    return Observation(
        game_id=GameId("build-002-interface-fixture"),
        frames=(GridFrame.from_rows(((0, 1, 0), (0, 0, 2), (0, 0, 0))),),
        state=GameStateName.NOT_FINISHED,
        levels_completed=0,
        win_levels=2,
        available_actions=tuple(action for action in ActionName if action is not ActionName.RESET),
        returned_action=returned_action,
    )


def _context(tmp_path: Path, config: ARC3Config, suffix: str) -> RunContext:
    return RunContext(
        run_id=f"build-002-{suffix}",
        episode_id=f"build-002-{suffix}-episode",
        game_id="build-002-interface-fixture",
        trace_root=tmp_path / suffix / "trace",
        checkpoint_root=tmp_path / suffix / "checkpoints",
        config=config,
        git_commit="build-002-test",
    )


@pytest.mark.competition
def test_mode_presets_are_explicit_and_research_defaults_are_preserved() -> None:
    research = ARC3Config.for_mode(EnvironmentMode.LOCAL)
    competition = ARC3Config.for_mode(EnvironmentMode.COMPETITION)

    assert research.execution_mode is ExecutionMode.RESEARCH_UNBOUNDED
    assert research.runtime_policy == RuntimePolicyConfig.research_unbounded()
    assert research.runtime_policy.allocator_tracing_enabled is True
    assert research.runtime_policy.automatic_per_action_checkpoints is True
    assert competition.execution_mode is ExecutionMode.COMPETITION_BOUNDED
    assert competition.runtime_policy == RuntimePolicyConfig.competition_bounded()
    assert competition.runtime_policy.allocator_tracing_enabled is False
    assert competition.runtime_policy.automatic_per_action_checkpoints is False


@pytest.mark.competition
def test_search_wall_clock_boundary_changes_only_in_competition_mode(tmp_path: Path) -> None:
    research = ARC3Controller(ControllerPreset.FULL)
    research.reset(
        _context(tmp_path, ARC3Config.for_mode(EnvironmentMode.LOCAL), "research-search")
    )
    competition = ARC3Controller(ControllerPreset.COMPETITION)
    competition.reset(
        _context(
            tmp_path,
            ARC3Config.for_mode(EnvironmentMode.COMPETITION),
            "competition-search",
        )
    )

    assert research.search_time_budget_enforced is False
    assert competition.search_time_budget_enforced is True
    research.close()
    competition.close()


@pytest.mark.competition
def test_execution_mode_and_frozen_policy_mismatches_fail_closed() -> None:
    with pytest.raises(CompetitionIntegrityError, match="requires the competition"):
        ARC3Config(
            mode=EnvironmentMode.LOCAL,
            execution_mode=ExecutionMode.COMPETITION_BOUNDED,
            runtime_policy=RuntimePolicyConfig.competition_bounded(),
        )
    with pytest.raises(ConfigurationError, match="frozen runtime policy"):
        ARC3Config(
            mode=EnvironmentMode.COMPETITION,
            execution_mode=ExecutionMode.COMPETITION_BOUNDED,
        )


@pytest.mark.competition
def test_competition_uses_documented_fixed_actions_and_calibrates_only_variable_ones(
    tmp_path: Path,
) -> None:
    config = ARC3Config.for_mode(EnvironmentMode.COMPETITION)
    controller = ARC3Controller(ControllerPreset.COMPETITION)
    controller.reset(_context(tmp_path, config, "interface"))
    controller.observe(_observation())

    projection = controller.action_calibration_projection
    assert projection["handles"] == ["ACTION5", "ACTION6"]
    assert projection["granted_handles"] == [
        "ACTION1",
        "ACTION2",
        "ACTION3",
        "ACTION4",
        "ACTION7",
    ]
    semantics = projection["interface_semantics"]
    assert isinstance(semantics, dict)
    assert semantics["translations"] == {
        "ACTION1": [0, -1],
        "ACTION2": [0, 1],
        "ACTION3": [-1, 0],
        "ACTION4": [1, 0],
    }
    assert semantics["undo_action"] == "ACTION7"
    assert semantics["evidence_driven_actions"] == ["ACTION5", "ACTION6"]
    assert semantics["source_commit"] == "a5dfc0b64c625fb4a19cf074af845ebe0bb88ff8"
    event_types = [event.event_type for event in controller.journal.verify_manifest()]
    assert event_types.count("interface.semantics_granted") == 1
    controller.close()


@pytest.mark.competition
def test_competition_suppresses_per_action_checkpoints_but_retains_sparse_recovery(
    tmp_path: Path,
) -> None:
    config = ARC3Config.for_mode(EnvironmentMode.COMPETITION)
    controller = ARC3Controller(ControllerPreset.COMPETITION)
    context = _context(tmp_path, config, "sparse")
    controller.reset(context)
    controller.observe(_observation())
    before = [
        event
        for event in controller.journal.verify_manifest()
        if event.event_type == "run.checkpoint_written"
    ]
    decision = controller.choose_action()
    after_decision = [
        event
        for event in controller.journal.verify_manifest()
        if event.event_type == "run.checkpoint_written"
    ]
    assert len(before) == 1
    assert len(after_decision) == len(before)

    controller.apply_consequence(_observation(returned_action=decision.action))
    after_consequence = [
        event
        for event in controller.journal.verify_manifest()
        if event.event_type == "run.checkpoint_written"
    ]
    assert len(after_consequence) == len(before)
    assert controller.compact_trace_projection
    immutable_before_close = tuple(context.checkpoint_root.glob("checkpoint-*.json"))
    controller.close()
    immutable_after_close = tuple(context.checkpoint_root.glob("checkpoint-*.json"))
    assert len(immutable_after_close) == len(immutable_before_close) + 1

    restored = ARC3Controller.restore(context, preset=ControllerPreset.COMPETITION)
    assert restored.compact_trace_projection
    assert restored.interface_semantics_projection is not None
    restored.close()


@pytest.mark.competition
@pytest.mark.replay
def test_competition_sparse_checkpoint_restores_and_replays_deterministically(
    tmp_path: Path,
) -> None:
    config = ARC3Config.for_mode(EnvironmentMode.COMPETITION, seed=208)
    interval = config.runtime_policy.sparse_checkpoint_interval_actions
    assert config.execution_mode is ExecutionMode.COMPETITION_BOUNDED
    assert config.runtime_policy.automatic_per_action_checkpoints is False
    assert interval == 16

    context = _context(tmp_path, config, "sparse-replay-source")
    controller = ARC3Controller(ControllerPreset.COMPETITION)
    controller.reset(context)
    controller.observe(_observation())

    for _ in range(interval - 1):
        decision = controller.choose_action()
        controller.apply_consequence(_observation(returned_action=decision.action))

    before_due = tuple(
        event
        for event in controller.journal.verify_manifest()
        if event.event_type == "run.checkpoint_written"
    )
    assert controller.snapshot.step_index == interval - 1
    assert len(before_due) == 1

    due_decision = controller.choose_action()
    controller.apply_consequence(_observation(returned_action=due_decision.action))
    after_due = tuple(
        event
        for event in controller.journal.verify_manifest()
        if event.event_type == "run.checkpoint_written"
    )
    assert controller.snapshot.phase is ControllerPhase.OBSERVED
    assert controller.snapshot.step_index == interval
    assert controller.snapshot.actions_used == interval
    assert len(after_due) == 2
    assert after_due[-1].step_index == interval
    assert controller._last_checkpoint is not None
    sparse_checkpoint = controller._last_checkpoint.path
    assert sparse_checkpoint.is_file()
    assert (
        after_due[-1].payload["checkpoint_hash"]
        == controller._last_checkpoint.envelope.checkpoint_hash
    )

    expected_snapshot = controller.snapshot
    source_replay = ReplayEngine(controller.journal)
    source_events = source_replay.verify_integrity()
    verify_event_chain(list(source_events))
    source_frames = source_replay.replay_frames()
    assert len(source_frames) == interval + 1
    assert controller.compact_trace_projection
    controller.journal.close()

    def restore_branch(label: str) -> ARC3Controller:
        branch_root = tmp_path / label
        trace_root = branch_root / "trace"
        checkpoint_root = branch_root / "checkpoints"
        shutil.copytree(context.trace_root, trace_root)
        shutil.copytree(context.checkpoint_root, checkpoint_root)
        branch_context = replace(
            context,
            trace_root=trace_root,
            checkpoint_root=checkpoint_root,
        )
        return ARC3Controller.restore(
            branch_context,
            preset=ControllerPreset.COMPETITION,
            checkpoint_path=checkpoint_root / sparse_checkpoint.name,
        )

    restored_a = restore_branch("sparse-replay-a")
    restored_b = restore_branch("sparse-replay-b")
    for restored in (restored_a, restored_b):
        assert restored.snapshot.phase is ControllerPhase.OBSERVED
        assert restored.snapshot.step_index == expected_snapshot.step_index
        assert restored.snapshot.actions_used == expected_snapshot.actions_used
        assert restored.snapshot.fault_count == expected_snapshot.fault_count
        assert restored.compact_trace_projection
        assert restored.interface_semantics_projection is not None

    continued_actions_a: list[ActionRequest] = []
    continued_actions_b: list[ActionRequest] = []
    for _ in range(3):
        decision_a = restored_a.choose_action()
        decision_b = restored_b.choose_action()
        continued_actions_a.append(decision_a.action)
        continued_actions_b.append(decision_b.action)
        restored_a.apply_consequence(_observation(returned_action=decision_a.action))
        restored_b.apply_consequence(_observation(returned_action=decision_b.action))

    assert continued_actions_a == continued_actions_b
    assert restored_a.snapshot == restored_b.snapshot

    replay_a = ReplayEngine(restored_a.journal)
    replay_b = ReplayEngine(restored_b.journal)
    events_a = replay_a.verify_integrity()
    events_b = replay_b.verify_integrity()
    verify_event_chain(list(events_a))
    verify_event_chain(list(events_b))
    frame_projection_a = tuple(
        (frame.level_index, frame.step_index, frame.frame_hash, frame.frame)
        for frame in replay_a.replay_frames()
    )
    frame_projection_b = tuple(
        (frame.level_index, frame.step_index, frame.frame_hash, frame.frame)
        for frame in replay_b.replay_frames()
    )
    assert frame_projection_a == frame_projection_b
    assert frame_projection_a[: len(source_frames)] == tuple(
        (frame.level_index, frame.step_index, frame.frame_hash, frame.frame)
        for frame in source_frames
    )
    assert len(frame_projection_a) == interval + 4

    restored_a.close()
    restored_b.close()
