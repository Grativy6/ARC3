from __future__ import annotations

from pathlib import Path

import pytest

from arc3.adapters import GridFrame, Observation
from arc3.adapters.synthetic import SYNTHETIC_GAME_ID, SyntheticAdapter
from arc3.config import ARC3Config, BudgetConfig
from arc3.goals import GoalStatus
from arc3.hypotheses import HypothesisScope
from arc3.policy import ARC3Controller, ControllerPhase, ControllerPreset, RunContext
from arc3.policy.baselines import ActionCyclePolicy
from arc3.trace import verify_event_chain
from arc3.types import ActionName, EnvironmentMode, GameId, GameStateName, HypothesisStatus


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
    full = [_run_full(tmp_path, seed)[:2] for seed in seeds]
    cycle = [_run_cycle(seed) for seed in seeds]

    assert sum(completed for completed, _actions in full) == len(seeds)
    assert sum(completed for completed, _actions in full) > sum(
        completed for completed, _actions in cycle
    )
    assert max(actions for _completed, actions in full) <= 16


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

    probe = controller.choose_action()
    controller.apply_consequence(session.step(probe.action))
    plan = controller.choose_action()
    assert plan.rationale_summary == "bounded A* plan under retrodicted model"
    controller.apply_consequence(session.step(plan.action))

    def fail_probe(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError("injected candidate-selection fault")

    monkeypatch.setattr(controller, "_plan_action", fail_probe)
    fallback = controller.choose_action()
    assert fallback.rationale_summary.startswith("deterministic legal fallback")
    controller.apply_consequence(session.step(fallback.action))


@pytest.mark.integration
def test_level_transition_closes_old_scope_and_reseeds_collision_free_history(
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
    old_hypothesis_ids = {
        record.hypothesis_id
        for record in controller._hypotheses.all()
        if record.scope is HypothesisScope.LEVEL and record.scope_ref == "level:0"
    }
    old_goal_ids = {
        record.candidate.goal_id
        for record in controller._goals.records()
        if record.candidate.scope_ref == "level:0"
    }
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
    all_hypotheses = controller._hypotheses.all()
    new_hypothesis_ids = {
        record.hypothesis_id
        for record in all_hypotheses
        if record.scope is HypothesisScope.LEVEL and record.scope_ref == "level:1"
    }
    assert old_hypothesis_ids
    assert len(new_hypothesis_ids) == len(old_hypothesis_ids)
    assert old_hypothesis_ids.isdisjoint(new_hypothesis_ids)
    assert all(
        controller._hypotheses.get(identifier).status is HypothesisStatus.SUPERSEDED
        for identifier in old_hypothesis_ids
    )
    assert all(
        controller._goals.get(identifier).status is GoalStatus.RETIRED
        for identifier in old_goal_ids
    )
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
    superseded = [event for event in events if event.event_type == "hypothesis.superseded"]
    retired = [event for event in events if event.event_type == "goal.retired"]
    assert len(superseded) == len(old_hypothesis_ids)
    assert retired
    assert all(event.payload["evidence_event_ids"] for event in superseded)
    assert all(event.payload["source_event_ids"] for event in retired)

    second = controller.choose_action()
    controller.apply_consequence(
        Observation(
            game_id=before.game_id,
            frames=before.frames,
            state=GameStateName.NOT_FINISHED,
            levels_completed=0,
            win_levels=2,
            available_actions=before.available_actions,
            full_reset=True,
            returned_action=second.action,
        )
    )
    revisited_level_ids = {
        record.hypothesis_id
        for record in controller._hypotheses.all()
        if record.scope_ref == "level:0" and record.status is not HypothesisStatus.SUPERSEDED
    }
    assert len(revisited_level_ids) == len(old_hypothesis_ids)
    assert revisited_level_ids.isdisjoint(old_hypothesis_ids)
    assert all(
        controller._hypotheses.get(identifier).status is HypothesisStatus.SUPERSEDED
        for identifier in new_hypothesis_ids
    )
    live_revisited_goals = {
        record.candidate.goal_id
        for record in controller._goals.records(include_retired=False)
        if record.candidate.scope_ref == "level:0"
    }
    assert live_revisited_goals
    assert live_revisited_goals.isdisjoint(old_goal_ids)
    reset_transition = [
        event
        for event in controller.journal.verify_manifest()
        if event.event_type == "observation.metadata_changed"
        and event.payload.get("transition_kind") == "level-index-reopened-or-reset"
    ]
    assert len(reset_transition) == 1
