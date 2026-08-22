from __future__ import annotations

from pathlib import Path

import pytest

from arc3.adapters import GridFrame, Observation
from arc3.adapters.synthetic import SYNTHETIC_GAME_ID, SyntheticAdapter
from arc3.config import ARC3Config, BudgetConfig
from arc3.policy import ARC3Controller, ControllerPhase, ControllerPreset, RunContext
from arc3.policy.baselines import ActionCyclePolicy
from arc3.trace import verify_event_chain
from arc3.types import ActionName, EnvironmentMode, GameId, GameStateName


def _context(tmp_path: Path, *, seed: int, label: str) -> RunContext:
    return RunContext(
        run_id=f"run-{label}-{seed}",
        episode_id=f"episode-{label}-{seed}",
        game_id=SYNTHETIC_GAME_ID,
        trace_root=tmp_path / label / str(seed) / "trace",
        checkpoint_root=tmp_path / label / str(seed) / "checkpoint",
        config=ARC3Config(
            mode=EnvironmentMode.SYNTHETIC,
            seed=seed,
            profile="controller-integration",
            budgets=BudgetConfig(max_actions=16, max_search_nodes=2_048),
        ),
        git_commit="controller-integration",
    )


def _run_full(tmp_path: Path, seed: int) -> tuple[bool, int, ARC3Controller]:
    session = SyntheticAdapter(seed=seed, size=8, max_steps=32).open(SYNTHETIC_GAME_ID)
    controller = ARC3Controller(ControllerPreset.FULL)
    controller.reset(_context(tmp_path, seed=seed, label="full"))
    controller.observe(session.observation)
    actions = 0
    while controller.phase not in {ControllerPhase.COMPLETE, ControllerPhase.GAME_OVER}:
        decision = controller.choose_action()
        controller.apply_consequence(session.step(decision.action))
        actions += 1
        if actions >= 16:
            break
    return session.observation.state is GameStateName.WIN, actions, controller


def _run_cycle(seed: int) -> tuple[bool, int]:
    session = SyntheticAdapter(seed=seed, size=8, max_steps=32).open(SYNTHETIC_GAME_ID)
    policy = ActionCyclePolicy()
    actions = 0
    while session.observation.state not in {GameStateName.WIN, GameStateName.GAME_OVER}:
        session.step(policy.select(session.observation))
        actions += 1
        if actions >= 16:
            break
    return session.observation.state is GameStateName.WIN, actions


@pytest.mark.integration
def test_integrated_controller_outperforms_equal_budget_cycle_on_synthetic(tmp_path: Path) -> None:
    seeds = tuple(range(16))
    full_runs = [_run_full(tmp_path, seed) for seed in seeds]
    full = [run[:2] for run in full_runs]
    cycle = [_run_cycle(seed) for seed in seeds]

    assert sum(completed for completed, _actions in full) == len(seeds)
    assert sum(completed for completed, _actions in full) > sum(
        completed for completed, _actions in cycle
    )
    assert max(actions for _completed, actions in full) <= 16

    # The initially selected structural mover can be wrong. Once diverse
    # consequences establish the controlled lineage, an earlier paid-for
    # receipt is interpreted retrospectively while its raw transition remains.
    receipt_reuse = full_runs[1][2]
    events = receipt_reuse.journal.verify_manifest()
    retrospective = tuple(
        event
        for event in events
        if event.event_type == "action.controlled_effect_interpreted"
        and event.payload.get("interpretation_timing")
        == "retrospective-after-mover-lineage-confirmation"
    )
    assert len(retrospective) == 1
    source_transition_id = retrospective[0].payload["source_transition_id"]
    assert any(
        transition.transition_id == source_transition_id
        for transition in receipt_reuse._transitions
    )
    assert len(retrospective[0].payload["confirmation_consequence_event_ids"]) == 2
    assert retrospective[0].payload["authority_event_ids"]


@pytest.mark.integration
def test_every_action_has_ordered_receipts_and_verified_hash_chain(tmp_path: Path) -> None:
    completed, _actions, controller = _run_full(tmp_path, seed=7)
    events = list(controller.journal.verify_manifest())
    verify_event_chain(events)
    assert completed is True
    component_batches = [
        event for event in events if event.event_type == "perception.components_detected"
    ]
    assert component_batches
    assert all(
        event.payload["component_count"] == len(event.payload["components"])
        for event in component_batches
        if isinstance(event.payload["components"], list)
    )

    by_step: dict[int, list[str]] = {}
    for event in events:
        by_step.setdefault(event.step_index, []).append(event.event_type)
    action_steps = [items for items in by_step.values() if "action.submitted" in items]
    assert action_steps
    for event_types in action_steps:
        assert event_types.index("observation.received") < event_types.index(
            "action.candidates_generated"
        )
        assert event_types.index("action.selected") < event_types.index("action.validated")
        assert event_types.index("action.validated") < event_types.index("action.submitted")
        if "simulation.prediction_emitted" in event_types:
            assert event_types.index("action.validated") < event_types.index(
                "simulation.prediction_emitted"
            )
            assert event_types.index("simulation.prediction_emitted") < event_types.index(
                "action.submitted"
            )


@pytest.mark.integration
def test_probe_plan_fallback_and_reset_paths_all_accept_consequences(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    session = SyntheticAdapter(seed=7, size=8, max_steps=32).open(SYNTHETIC_GAME_ID)
    controller = ARC3Controller(ControllerPreset.FULL)
    controller.reset(_context(tmp_path, seed=7, label="paths"))
    controller.observe(session.observation)

    for expected in (
        ActionName.ACTION1,
        ActionName.ACTION2,
        ActionName.ACTION3,
        ActionName.ACTION4,
    ):
        calibration = controller.choose_action()
        assert calibration.action.name is expected
        assert calibration.rationale_summary == "frozen one-receipt opaque-handle calibration"
        controller.apply_consequence(session.step(calibration.action))
    plan = controller.choose_action()
    assert plan.rationale_summary == "bounded A* plan under retrodicted model"
    controller.apply_consequence(session.step(plan.action))

    def fail_probe(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError("injected candidate-selection fault")

    monkeypatch.setattr(controller, "_plan_action", fail_probe)
    fallback = controller.choose_action()
    assert fallback.rationale_summary.startswith("deterministic legal fallback")
    controller.apply_consequence(session.step(fallback.action))
    assert controller.phase is ControllerPhase.OBSERVED
    staging_faults = tuple(
        event
        for event in controller.journal.verify_manifest()
        if event.event_type == "run.environment_fault"
        and event.payload.get("boundary") == "consequence-tail-plan-staging"
    )
    assert len(staging_faults) == 1


@pytest.mark.integration
def test_level_transition_records_old_effect_before_resetting_successor_registry(
    tmp_path: Path,
) -> None:
    controller = ARC3Controller(ControllerPreset.FULL)
    controller.reset(_context(tmp_path, seed=29, label="level-transition"))
    before = Observation(
        game_id=GameId(SYNTHETIC_GAME_ID),
        frames=(GridFrame.from_rows(((0, 1, 0), (0, 0, 2), (0, 0, 0))),),
        state=GameStateName.NOT_FINISHED,
        levels_completed=0,
        win_levels=2,
        available_actions=(
            ActionName.ACTION1,
            ActionName.ACTION2,
            ActionName.ACTION3,
            ActionName.ACTION4,
        ),
    )
    controller.observe(before)
    old_goal_ids = {
        record.candidate.goal_id
        for record in controller._goals.records()
        if record.candidate.scope_ref == "level:0"
    }
    assert old_goal_ids
    decision = controller.choose_action()
    controller.apply_consequence(
        Observation(
            game_id=before.game_id,
            frames=before.frames,
            state=GameStateName.NOT_FINISHED,
            levels_completed=1,
            win_levels=2,
            available_actions=before.available_actions,
            returned_action=decision.action,
        )
    )

    assert controller.snapshot.level_index == 1
    assert controller.action_effect_projection["level_index"] == 1
    assert controller.action_effect_projection["candidates"] == []
    assert controller.action_effect_projection["observation_counts"] == {
        action.value: 0 for action in before.available_actions
    }
    assert controller.action_calibration_projection == {
        "level_index": 1,
        "handles": [action.value for action in before.available_actions],
        "completed_handles": [],
        "cursor": 0,
        "pending_handle": None,
    }
    assert any(
        record.candidate.scope_ref == "level:1"
        for record in controller._goals.records(include_retired=False)
    )

    events = controller.journal.verify_manifest()
    consequence = next(event for event in events if event.event_type == "consequence.received")
    new_observation = next(
        event
        for event in events
        if event.event_type == "observation.received" and event.level_index == 1
    )
    assert consequence.level_index == 0
    assert new_observation.level_index == 1
    registry_update = next(
        event for event in events if event.event_type == "action.effect_observed"
    )
    assert registry_update.payload["registry_level_index"] == 0
    assert registry_update.payload["raw_handle"] == decision.action.name.value
    assert registry_update.payload["candidate_count"] == 1
    retired = [event for event in events if event.event_type == "goal.retired"]
    assert retired
    assert all(event.payload["source_event_ids"] for event in retired)

    second = controller.choose_action()
    assert second.action == decision.action
    assert second.rationale_summary == "frozen one-receipt opaque-handle calibration"
