from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest

from arc3.adapters import GridFrame, Observation
from arc3.adapters.synthetic import SYNTHETIC_GAME_ID, SyntheticAdapter
from arc3.config import ARC3Config, BudgetConfig
from arc3.errors import CompetitionIntegrityError, EnvironmentStateError, PolicyError
from arc3.policy import (
    ARC3Controller,
    ControllerPhase,
    ControllerPreset,
    LocalProposal,
    ProposalContext,
    RunContext,
    preset_features,
)
from arc3.trace import EventJournal
from arc3.types import (
    ActionName,
    ActionRequest,
    EnvironmentMode,
    GameId,
    GameStateName,
    JSONScalar,
)


class _Provider:
    def propose(self, context: ProposalContext) -> tuple[LocalProposal, ...]:
        return (LocalProposal("P-1", "action-semantics", {"frame": context.frame_hash}),)


def _context(
    tmp_path: Path,
    *,
    mode: EnvironmentMode = EnvironmentMode.SYNTHETIC,
    max_actions: int = 16,
    max_resets: int = 8,
) -> RunContext:
    config = ARC3Config(
        mode=mode,
        seed=17,
        profile="controller-test",
        budgets=BudgetConfig(max_actions=max_actions, max_resets=max_resets),
    )
    return RunContext(
        run_id="run-controller-test",
        episode_id="episode-controller-test",
        game_id=SYNTHETIC_GAME_ID,
        trace_root=tmp_path / "trace",
        checkpoint_root=tmp_path / "checkpoint",
        config=config,
        git_commit="controller-test",
    )


def test_presets_have_monotonic_named_mechanism_boundaries() -> None:
    baseline = preset_features(ControllerPreset.BASELINE)
    trace = preset_features(ControllerPreset.TRACE)
    world = preset_features(ControllerPreset.WORLD_MODEL)
    full = preset_features(ControllerPreset.FULL)
    competition = preset_features(ControllerPreset.COMPETITION)

    assert baseline.use_measurements is False
    assert trace.use_measurements is True and trace.use_world_model is False
    assert world.use_world_model is True and world.use_planning is False
    assert full.use_planning is True and full.use_memory is True
    assert competition == full
    assert competition.allow_local_proposals is False


def test_local_proposal_interface_is_disabled_and_has_no_action_field() -> None:
    assert "action" not in LocalProposal.__dataclass_fields__
    with pytest.raises(PolicyError, match="local proposals are disabled"):
        ARC3Controller(ControllerPreset.FULL, local_proposal_provider=_Provider())
    with pytest.raises(CompetitionIntegrityError, match="forbids"):
        ARC3Controller(ControllerPreset.COMPETITION, local_proposal_provider=_Provider())


def test_competition_controller_requires_offline_competition_config(tmp_path: Path) -> None:
    controller = ARC3Controller(ControllerPreset.COMPETITION)
    with pytest.raises(CompetitionIntegrityError, match="competition-mode"):
        controller.reset(_context(tmp_path))


def test_malformed_observation_is_preserved_as_a_fault_receipt(tmp_path: Path) -> None:
    controller = ARC3Controller(ControllerPreset.TRACE)
    controller.reset(_context(tmp_path))

    with pytest.raises(PolicyError, match="malformed observation preserved"):
        controller.observe({"mutable": "not-an-observation"})

    events = controller.journal.verify_manifest()
    assert events[-1].event_type == "observation.parse_failed"
    assert controller.phase is ControllerPhase.FAULTED
    assert controller.snapshot.fault_count == 1


def test_empty_frame_batch_is_preserved_as_a_fault_receipt(tmp_path: Path) -> None:
    controller = ARC3Controller(ControllerPreset.TRACE)
    controller.reset(_context(tmp_path))
    observation = Observation(
        game_id=GameId(SYNTHETIC_GAME_ID),
        frames=(),
        state=GameStateName.NOT_FINISHED,
        levels_completed=0,
        win_levels=1,
        available_actions=(ActionName.ACTION1,),
    )

    with pytest.raises(PolicyError, match="malformed observation preserved"):
        controller.observe(observation)

    events = controller.journal.verify_manifest()
    assert events[-1].event_type == "observation.parse_failed"
    assert events[-1].payload == {
        "fault": "observation requires at least one normalized frame",
        "input_type": f"{Observation.__module__}.{Observation.__name__}",
    }
    assert controller.phase is ControllerPhase.FAULTED
    assert controller.snapshot.fault_count == 1


def test_noncanonical_metadata_is_not_serialized_in_fault_receipt(tmp_path: Path) -> None:
    class PoisonMetadata:
        def __repr__(self) -> str:
            return "DO_NOT_SERIALIZE_POISON_METADATA"

    controller = ARC3Controller(ControllerPreset.TRACE)
    controller.reset(_context(tmp_path))
    observation = Observation(
        game_id=GameId(SYNTHETIC_GAME_ID),
        frames=(GridFrame.from_rows(((0, 1), (0, 2))),),
        state=GameStateName.NOT_FINISHED,
        levels_completed=0,
        win_levels=1,
        available_actions=(ActionName.ACTION1,),
        upstream_metadata=(("non_canonical", cast(JSONScalar, PoisonMetadata())),),
    )

    with pytest.raises(PolicyError, match="malformed observation preserved"):
        controller.observe(observation)

    events = controller.journal.verify_manifest()
    assert events[-1].event_type == "observation.parse_failed"
    assert events[-1].payload == {
        "fault": "upstream metadata is not canonical JSON",
        "input_type": f"{Observation.__module__}.{Observation.__name__}",
    }
    trace_text = "\n".join(
        path.read_text(encoding="utf-8") for path in controller.context.trace_root.rglob("*.jsonl")
    )
    assert "DO_NOT_SERIALIZE_POISON_METADATA" not in trace_text
    assert controller.phase is ControllerPhase.FAULTED
    assert controller.snapshot.fault_count == 1


def test_malformed_observation_fault_restores_from_close_checkpoint(tmp_path: Path) -> None:
    context = _context(tmp_path)
    controller = ARC3Controller(ControllerPreset.FULL)
    controller.reset(context)
    observation = Observation(
        game_id=GameId(SYNTHETIC_GAME_ID),
        frames=(),
        state=GameStateName.NOT_FINISHED,
        levels_completed=0,
        win_levels=1,
        available_actions=(ActionName.ACTION1,),
    )
    with pytest.raises(PolicyError, match="malformed observation preserved"):
        controller.observe(observation)
    controller.close()

    restored = ARC3Controller.restore(context, preset=ControllerPreset.FULL)
    assert restored.phase is ControllerPhase.FAULTED
    assert restored.snapshot.fault_count == 1
    assert (
        sum(
            event.event_type == "observation.parse_failed"
            for event in restored.journal.verify_manifest()
        )
        == 1
    )
    restored.close()


def test_wrong_game_observation_uses_the_same_fault_receipt_boundary(tmp_path: Path) -> None:
    controller = ARC3Controller(ControllerPreset.TRACE)
    controller.reset(_context(tmp_path))
    observation = Observation(
        game_id=GameId("different-synthetic-game"),
        frames=(GridFrame.from_rows(((0, 1), (0, 2))),),
        state=GameStateName.NOT_FINISHED,
        levels_completed=0,
        win_levels=1,
        available_actions=(ActionName.ACTION1,),
    )

    with pytest.raises(PolicyError, match="malformed observation preserved"):
        controller.observe(observation)

    events = controller.journal.verify_manifest()
    assert events[-1].event_type == "observation.parse_failed"
    assert events[-1].payload["fault"] == "observation game identity does not match run context"
    assert controller.phase is ControllerPhase.FAULTED
    assert controller.snapshot.fault_count == 1


def test_canonical_upstream_metadata_remains_accepted(tmp_path: Path) -> None:
    controller = ARC3Controller(ControllerPreset.TRACE)
    controller.reset(_context(tmp_path))
    observation = Observation(
        game_id=GameId(SYNTHETIC_GAME_ID),
        frames=(GridFrame.from_rows(((0, 1), (0, 2))),),
        state=GameStateName.NOT_FINISHED,
        levels_completed=0,
        win_levels=1,
        available_actions=(ActionName.ACTION1,),
        upstream_metadata=(("source_revision", "v0.1"), ("retry_count", 0)),
    )

    controller.observe(observation)

    events = controller.journal.verify_manifest()
    assert events[-1].event_type != "observation.parse_failed"
    received = next(event for event in events if event.event_type == "observation.received")
    assert received.payload["upstream_metadata"] == {
        "full_reset": False,
        "levels_completed": 0,
        "retry_count": 0,
        "source_revision": "v0.1",
        "win_levels": 1,
    }
    assert controller.phase is ControllerPhase.OBSERVED
    assert controller.snapshot.fault_count == 0


def test_game_over_only_selects_reset_and_accepts_reset_consequence(tmp_path: Path) -> None:
    session = SyntheticAdapter(seed=17, size=8, max_steps=1).open(SYNTHETIC_GAME_ID)
    controller = ARC3Controller(ControllerPreset.FULL)
    controller.reset(_context(tmp_path))
    controller.observe(session.observation)

    first = controller.choose_action()
    controller.apply_consequence(session.step(first.action))
    assert controller.phase is ControllerPhase.GAME_OVER

    reset = controller.choose_action()
    assert reset.action.name is ActionName.RESET
    controller.apply_consequence(session.step(reset.action))
    assert controller.phase is ControllerPhase.OBSERVED


def test_unknown_state_is_not_authorized_to_act(tmp_path: Path) -> None:
    observation = Observation(
        game_id=GameId(SYNTHETIC_GAME_ID),
        frames=(GridFrame.from_rows(((0, 1), (0, 2))),),
        state=GameStateName.UNKNOWN,
        levels_completed=0,
        win_levels=1,
        available_actions=(ActionName.ACTION1,),
    )
    controller = ARC3Controller(ControllerPreset.FULL)
    controller.reset(_context(tmp_path))
    controller.observe(observation)

    with pytest.raises(EnvironmentStateError, match="state is unknown"):
        controller.choose_action()


def _manual_observation(
    *,
    state: GameStateName,
    returned_action: ActionRequest | None = None,
    levels_completed: int = 0,
) -> Observation:
    return Observation(
        game_id=GameId(SYNTHETIC_GAME_ID),
        frames=(GridFrame.from_rows(((0, 1, 0), (0, 0, 2), (0, 0, 0))),),
        state=state,
        levels_completed=levels_completed,
        win_levels=2,
        available_actions=(ActionName.ACTION1, ActionName.ACTION2),
        returned_action=returned_action,
    )


def test_action_and_reset_budgets_are_enforced_independently(tmp_path: Path) -> None:
    active = _manual_observation(state=GameStateName.NOT_FINISHED)
    action_controller = ARC3Controller(ControllerPreset.FULL)
    action_controller.reset(_context(tmp_path / "actions", max_actions=1, max_resets=1))
    action_controller.observe(active)
    first = action_controller.choose_action()
    action_controller.apply_consequence(
        _manual_observation(
            state=GameStateName.NOT_FINISHED,
            returned_action=first.action,
        )
    )
    assert action_controller.snapshot.actions_used == 1
    assert action_controller.snapshot.resets_used == 0
    with pytest.raises(PolicyError, match=r"max_actions budget exhausted \(1/1\)"):
        action_controller.choose_action()
    assert action_controller.phase is ControllerPhase.FAULTED
    with pytest.raises(PolicyError, match="faulted controller cannot act"):
        action_controller.choose_action()

    reset_controller = ARC3Controller(ControllerPreset.FULL)
    reset_controller.reset(_context(tmp_path / "resets", max_actions=1, max_resets=1))
    not_played = _manual_observation(state=GameStateName.NOT_PLAYED)
    reset_controller.observe(not_played)
    reset = reset_controller.choose_action()
    assert reset.action.name is ActionName.RESET
    reset_controller.apply_consequence(
        _manual_observation(
            state=GameStateName.NOT_FINISHED,
            returned_action=reset.action,
        )
    )
    assert reset_controller.snapshot.actions_used == 0
    assert reset_controller.snapshot.resets_used == 1
    reset_controller.observe(_manual_observation(state=GameStateName.GAME_OVER))
    with pytest.raises(PolicyError, match=r"max_resets budget exhausted \(1/1\)"):
        reset_controller.choose_action()


def test_returned_action_mismatch_preserves_raw_receipts_before_fault(tmp_path: Path) -> None:
    context = _context(tmp_path / "mismatch", max_actions=4, max_resets=2)
    controller = ARC3Controller(ControllerPreset.FULL)
    controller.reset(context)
    controller.observe(_manual_observation(state=GameStateName.NOT_FINISHED))
    submitted = controller.choose_action()
    returned_name = (
        ActionName.ACTION2 if submitted.action.name is ActionName.ACTION1 else ActionName.ACTION1
    )
    returned = ActionRequest(returned_name)

    with pytest.raises(PolicyError, match="raw receipt preserved"):
        controller.apply_consequence(
            _manual_observation(
                state=GameStateName.NOT_FINISHED,
                returned_action=returned,
            )
        )

    events = controller.journal.verify_manifest()
    consequence_index = next(
        index for index, event in enumerate(events) if event.event_type == "consequence.received"
    )
    observation_index = next(
        index
        for index, event in enumerate(events)
        if index > consequence_index and event.event_type == "observation.received"
    )
    rejection_index = next(
        index
        for index, event in enumerate(events)
        if event.event_type == "action.rejected_by_environment"
    )
    assert consequence_index < observation_index < rejection_index
    assert events[consequence_index].payload["returned_action"] == {
        "name": returned_name.value,
        "coordinate": None,
    }
    assert events[observation_index].payload["returned_action"] == {
        "name": returned_name.value,
        "coordinate": None,
    }
    assert controller.phase is ControllerPhase.FAULTED
    assert controller.snapshot.pending_action is None
    assert controller.snapshot.actions_used == 1
    assert controller.snapshot.resets_used == 0
    assert controller.snapshot.fault_count == 1

    controller.close()
    restored = ARC3Controller.restore(context, preset=ControllerPreset.FULL)
    assert restored.phase is ControllerPhase.FAULTED
    assert restored.snapshot.actions_used == 1
    assert restored.snapshot.resets_used == 0
    assert restored.snapshot.fault_count == 1
    with pytest.raises(PolicyError, match="faulted controller cannot act"):
        restored.choose_action()
    restored.close()
    auditor = EventJournal(context.trace_root, run_id=context.run_id)
    assert sum(event.event_type == "run.completed" for event in auditor.verify_manifest()) == 1
    auditor.close()
