from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import cast

import pytest

from arc3.adapters.synthetic import SYNTHETIC_GAME_ID, SyntheticAdapter
from arc3.config import ARC3Config, BudgetConfig
from arc3.errors import PolicyError
from arc3.policy import (
    ARC3Controller,
    CacheInvalidationReason,
    CadenceConfig,
    ControllerPhase,
    ControllerPreset,
    RunContext,
)
from arc3.trace import TraceEvent, sha256_json
from arc3.types import EnvironmentMode


def _context(tmp_path: Path, *, label: str) -> RunContext:
    return RunContext(
        run_id=f"cadence-{label}",
        episode_id=f"cadence-{label}-episode",
        game_id=SYNTHETIC_GAME_ID,
        trace_root=tmp_path / label / "trace",
        checkpoint_root=tmp_path / label / "checkpoint",
        config=ARC3Config(
            mode=EnvironmentMode.SYNTHETIC,
            seed=7,
            profile="controller-cadence-integration",
            budgets=BudgetConfig(max_actions=16, max_search_nodes=2_048),
        ),
        git_commit="controller-cadence-integration",
    )


def _event(events: tuple[TraceEvent, ...], event_id: str) -> TraceEvent:
    return next(item for item in events if item.event_id == event_id)


@pytest.mark.integration
def test_automatic_checkpoint_keeps_one_reasoning_cycle_per_observation_boundary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = SyntheticAdapter(seed=7, size=8, max_steps=32).open(SYNTHETIC_GAME_ID)
    cadence = CadenceConfig(repeated_no_progress_threshold=16)
    controller = ARC3Controller(ControllerPreset.FULL, cadence_config=cadence)
    controller.reset(_context(tmp_path, label="automatic-checkpoint"))
    retarget_paths: list[str] = []
    acquisition_paths: list[str] = []
    original_retarget = controller._retarget_contact_goal_after_progress
    original_acquire = controller._acquire_goal_transition

    def track_retarget(*args: object, **kwargs: object) -> None:
        selection = controller._reasoning_selection
        retarget_paths.append(selection.path.value if selection is not None else "MISSING")
        original_retarget(*args, **kwargs)

    monkeypatch.setattr(
        controller,
        "_retarget_contact_goal_after_progress",
        track_retarget,
    )

    def track_acquisition(*args: object, **kwargs: object) -> object:
        selection = controller._reasoning_selection
        acquisition_paths.append(selection.path.value if selection is not None else "MISSING")
        return original_acquire(*args, **kwargs)

    monkeypatch.setattr(controller, "_acquire_goal_transition", track_acquisition)
    controller.observe(session.observation)

    assert controller.cadence_state["no_progress_streak"] == 0
    initial_events = controller.journal.verify_manifest()
    assert sum(item.event_type == "reasoning.path_selected" for item in initial_events) == 1
    assert not any(
        item.event_type in {"reasoning.deliberation_completed", "reasoning.fallback_used"}
        for item in initial_events
    )
    assert any(item.event_type == "run.checkpoint_written" for item in initial_events)
    initial_event_ids = tuple(item.event_id for item in initial_events)
    safe_checkpoint = controller._last_checkpoint
    assert safe_checkpoint is not None
    returned_checkpoint = controller.checkpoint()
    assert returned_checkpoint == safe_checkpoint
    assert (
        tuple(item.event_id for item in controller.journal.verify_manifest()) == initial_event_ids
    )

    required_work_counts = {
        "compilation_invocations",
        "prediction_invocations",
        "retrodicted_transitions",
        "simulation_invocations",
        "search_expanded_nodes",
    }
    expected_invalidation_reasons = {item.value for item in CacheInvalidationReason}
    saw_fast = False
    saw_current_action_prediction = False

    for ordinal in range(6):
        before_choose = controller.journal.verify_manifest()
        observation_count = sum(item.event_type == "observation.received" for item in before_choose)
        assert (
            sum(item.event_type == "reasoning.path_selected" for item in before_choose)
            == observation_count
        )

        decision = controller.choose_action()
        events = controller.journal.verify_manifest()
        selected = _event(events, decision.selected_event_id)
        terminal_id = selected.payload["reasoning_completed_event_id"]
        assert isinstance(terminal_id, str)
        terminal = _event(events, terminal_id)
        selected_path_id = terminal.payload["path_selected_event_id"]
        assert isinstance(selected_path_id, str)
        selected_path = _event(events, selected_path_id)
        event_order = {item.event_id: index for index, item in enumerate(events)}

        assert selected_path.event_type == "reasoning.path_selected"
        assert terminal.event_type == "reasoning.deliberation_completed"
        assert event_order[selected_path.event_id] < event_order[terminal.event_id]
        assert event_order[terminal.event_id] < event_order[selected.event_id]
        assert (
            selected_path.payload["observation_event_id"]
            == selected.payload["source_observation_event_id"]
            == decision.observation_event_id
        )
        assert terminal.payload["path"] == selected_path.payload["path"]

        work = terminal.payload["integer_work_counts"]
        assert isinstance(work, dict)
        assert required_work_counts <= set(work)
        assert not any("elapsed" in key or "wall" in key for key in work)
        if terminal.payload["path"] == "DEEP":
            assert work["deep_invocations"] == 1
            assert work["compilation_invocations"] == 1
        else:
            saw_fast = True
            assert work["deep_invocations"] == 0
            assert work["compilation_invocations"] == 0
            assert work["retrodicted_transitions"] == 0
            assert work["retrodiction_invocations"] == 0
            assert work["search_expanded_nodes"] == 0
            assert work["search_generated_transitions"] == 0

        invalidations = terminal.payload["cache_invalidation_counts"]
        assert isinstance(invalidations, dict)
        assert set(invalidations) == expected_invalidation_reasons
        assert all(isinstance(value, int) and value >= 0 for value in invalidations.values())

        prediction_events = tuple(
            item
            for item in events
            if item.event_type == "simulation.prediction_emitted"
            and item.payload.get("action_decision_id") == decision.decision_id
        )
        if prediction_events:
            saw_current_action_prediction = True
            assert len(prediction_events) == 1
            cache_hit = prediction_events[0].payload["cache_hit"]
            assert isinstance(cache_hit, bool)
            assert terminal.payload["cache_hits"] == int(cache_hit)
            assert terminal.payload["cache_misses"] == int(not cache_hit)
            assert work["prediction_invocations"] >= int(not cache_hit)

        controller.apply_consequence(session.step(decision.action))
        assert controller.phase is ControllerPhase.OBSERVED
        after_consequence = controller.journal.verify_manifest()
        # The automatic evidence-fold checkpoint is written before selection.
        # It must not close the new cycle and make choose_action repeat DEEP work.
        assert sum(
            item.event_type == "reasoning.path_selected" for item in after_consequence
        ) == sum(item.event_type == "observation.received" for item in after_consequence)
        assert (
            sum(
                item.event_type in {"reasoning.deliberation_completed", "reasoning.fallback_used"}
                for item in after_consequence
            )
            == ordinal + 1
        )

    assert saw_fast is True
    assert saw_current_action_prediction is True
    assert retarget_paths
    assert set(retarget_paths) == {"DEEP"}
    assert acquisition_paths
    assert set(acquisition_paths) == {"DEEP"}
    controller.close()


@pytest.mark.integration
def test_reasoning_failure_is_terminally_receipted_before_fallback_action(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = SyntheticAdapter(seed=7, size=8, max_steps=32).open(SYNTHETIC_GAME_ID)
    controller = ARC3Controller(ControllerPreset.FULL)
    controller.reset(_context(tmp_path, label="fallback"))

    def fail_compilation(_observation: object) -> None:
        raise RuntimeError("injected deep-compilation fault")

    monkeypatch.setattr(controller, "_update_world_models", fail_compilation)
    controller.observe(session.observation)
    decision = controller.choose_action()
    events = controller.journal.verify_manifest()
    selected = _event(events, decision.selected_event_id)
    terminal_id = selected.payload["reasoning_completed_event_id"]
    assert isinstance(terminal_id, str)
    terminal = _event(events, terminal_id)

    assert terminal.event_type == "reasoning.fallback_used"
    assert terminal.payload["status"] == "FALLBACK_USED"
    assert terminal.payload["fault_type"] == "RuntimeError"
    assert decision.rationale_category.value == "fault_fallback"
    assert (
        next(
            item for item in events if item.event_id == terminal.payload["path_selected_event_id"]
        ).event_type
        == "reasoning.path_selected"
    )
    controller.close()


@pytest.mark.integration
def test_trace_checkpoint_aborts_without_becoming_a_cadence_policy_input(
    tmp_path: Path,
) -> None:
    session_a = SyntheticAdapter(seed=7, size=8, max_steps=32).open(SYNTHETIC_GAME_ID)
    session_b = SyntheticAdapter(seed=7, size=8, max_steps=32).open(SYNTHETIC_GAME_ID)
    checkpointed = ARC3Controller(ControllerPreset.TRACE)
    uninterrupted = ARC3Controller(ControllerPreset.TRACE)
    checkpoint_context = _context(tmp_path, label="trace-checkpointed")
    checkpointed.reset(checkpoint_context)
    uninterrupted.reset(_context(tmp_path, label="trace-uninterrupted"))
    checkpointed.observe(session_a.observation)
    uninterrupted.observe(session_b.observation)
    before = checkpointed.cadence_state

    checkpoint = checkpointed.checkpoint()
    after = checkpointed.cadence_state
    assert after["fast_streak"] == before["fast_streak"]
    assert after["no_progress_streak"] == before["no_progress_streak"]
    events = checkpointed.journal.verify_manifest()
    assert [item.event_type for item in events[-3:]] == [
        "reasoning.deliberation_completed",
        "reasoning.checkpoint_state",
        "run.checkpoint_written",
    ]
    assert events[-3].payload["status"] == "FAILED"
    assert events[-3].payload["fault_type"] == "CheckpointRequestedBeforeAction"

    checkpointed.journal.close()
    restored = ARC3Controller.restore(
        checkpoint_context,
        preset=ControllerPreset.TRACE,
        checkpoint_path=checkpoint.path,
    )
    checkpointed_decision = restored.choose_action()
    uninterrupted_decision = uninterrupted.choose_action()
    assert checkpointed_decision.action == uninterrupted_decision.action
    assert checkpointed_decision.rationale_category == uninterrupted_decision.rationale_category
    assert checkpointed_decision.rationale_summary == uninterrupted_decision.rationale_summary
    assert restored.cadence_state["fast_streak"] == uninterrupted.cadence_state["fast_streak"]
    assert (
        restored.cadence_state["no_progress_streak"]
        == uninterrupted.cadence_state["no_progress_streak"]
    )
    restored_selection = next(
        item
        for item in reversed(restored.journal.verify_manifest())
        if item.event_type == "reasoning.path_selected"
    )
    uninterrupted_selection = next(
        item
        for item in reversed(uninterrupted.journal.verify_manifest())
        if item.event_type == "reasoning.path_selected"
    )
    assert restored_selection.payload["path"] == uninterrupted_selection.payload["path"]
    assert (
        restored_selection.payload["ordered_triggers"]
        == uninterrupted_selection.payload["ordered_triggers"]
    )
    restored.close()
    uninterrupted.close()


@pytest.mark.integration
def test_close_before_action_aborts_without_changing_restored_cadence_path(
    tmp_path: Path,
) -> None:
    session_a = SyntheticAdapter(seed=7, size=8, max_steps=32).open(SYNTHETIC_GAME_ID)
    session_b = SyntheticAdapter(seed=7, size=8, max_steps=32).open(SYNTHETIC_GAME_ID)
    cadence = CadenceConfig(repeated_no_progress_threshold=16)
    closed = ARC3Controller(ControllerPreset.FULL, cadence_config=cadence)
    uninterrupted = ARC3Controller(ControllerPreset.FULL, cadence_config=cadence)
    closed_context = _context(tmp_path, label="closed-before-action")
    closed.reset(closed_context)
    uninterrupted.reset(_context(tmp_path, label="close-uninterrupted"))
    closed.observe(session_a.observation)
    uninterrupted.observe(session_b.observation)
    for _ in range(6):
        closed_selection = closed._reasoning_selection
        uninterrupted_pending = uninterrupted._reasoning_selection
        assert closed_selection is not None
        assert uninterrupted_pending is not None
        assert closed_selection.path == uninterrupted_pending.path
        if closed_selection.path.value == "FAST":
            break
        closed_decision = closed.choose_action()
        uninterrupted_decision = uninterrupted.choose_action()
        assert closed_decision.action == uninterrupted_decision.action
        closed.apply_consequence(session_a.step(closed_decision.action))
        uninterrupted.apply_consequence(session_b.step(uninterrupted_decision.action))
    else:
        pytest.fail("fixture did not reach a pending FAST cadence path")
    assert closed._reasoning_selection is not None
    assert closed._reasoning_selection.path.value == "FAST"
    before = closed.cadence_state

    closed.close()
    checkpoint = closed._last_checkpoint
    assert checkpoint is not None
    assert checkpoint.phase is ControllerPhase.OBSERVED

    restored = ARC3Controller.restore(
        closed_context,
        preset=ControllerPreset.FULL,
        checkpoint_path=checkpoint.path,
        cadence_config=cadence,
    )
    events = restored.journal.verify_manifest()
    terminal = next(
        item for item in reversed(events) if item.event_type == "reasoning.deliberation_completed"
    )
    assert terminal.payload["status"] == "FAILED"
    assert terminal.payload["fault_type"] == "ControllerClosedBeforeAction"
    assert restored.cadence_state["fast_streak"] == before["fast_streak"]
    assert restored.cadence_state["no_progress_streak"] == before["no_progress_streak"]
    restored_decision = restored.choose_action()
    uninterrupted_decision = uninterrupted.choose_action()
    assert restored_decision.action == uninterrupted_decision.action
    assert restored_decision.rationale_category == uninterrupted_decision.rationale_category
    assert restored_decision.rationale_summary == uninterrupted_decision.rationale_summary
    restored_selection = next(
        item
        for item in reversed(restored.journal.verify_manifest())
        if item.event_type == "reasoning.path_selected"
    )
    uninterrupted_selection = next(
        item
        for item in reversed(uninterrupted.journal.verify_manifest())
        if item.event_type == "reasoning.path_selected"
    )
    assert restored_selection.payload["path"] == uninterrupted_selection.payload["path"]
    assert (
        restored_selection.payload["ordered_triggers"]
        == uninterrupted_selection.payload["ordered_triggers"]
    )
    restored.close()
    uninterrupted.close()


@pytest.mark.integration
def test_checkpoint_restore_preserves_exact_cadence_identity_and_rejects_mismatch(
    tmp_path: Path,
) -> None:
    context = _context(tmp_path, label="restore")
    cadence = CadenceConfig(cache_capacity=7, repeated_no_progress_threshold=16)
    session = SyntheticAdapter(seed=7, size=8, max_steps=32).open(SYNTHETIC_GAME_ID)
    original = ARC3Controller(ControllerPreset.FULL, cadence_config=cadence)
    original.reset(context)
    original.observe(session.observation)
    original.choose_action()
    checkpoint = original.checkpoint()
    expected_cadence_state = original.cadence_state
    expected_cache_state = original.prediction_cache_state
    original.close()

    restored = ARC3Controller.restore(
        context,
        preset=ControllerPreset.FULL,
        checkpoint_path=checkpoint.path,
        cadence_config=cadence,
    )
    assert restored.cadence_config == cadence
    assert restored.cadence_state == expected_cadence_state
    assert restored.prediction_cache_state == expected_cache_state
    restored.close()

    with pytest.raises(PolicyError, match=r"cadence|configuration|source|cache"):
        ARC3Controller.restore(
            context,
            preset=ControllerPreset.FULL,
            checkpoint_path=checkpoint.path,
            cadence_config=replace(cadence, cache_capacity=8),
        )

    raw = json.loads(checkpoint.path.read_text(encoding="utf-8"))
    assert isinstance(raw, dict)
    raw_state = raw["state"]
    assert isinstance(raw_state, dict)
    derived = raw_state["derived_controller_state"]
    assert isinstance(derived, dict)
    planner = derived["planner_state"]
    assert isinstance(planner, dict)
    cadence_state = planner["cadence_state"]
    assert isinstance(cadence_state, dict)
    fast_streak = cadence_state["fast_streak"]
    assert isinstance(fast_streak, int)
    cadence_state["fast_streak"] = fast_streak + 1
    raw["checkpoint_hash"] = sha256_json(
        {key: value for key, value in raw.items() if key != "checkpoint_hash"}
    )
    tampered = tmp_path / "tampered-cadence-checkpoint.json"
    tampered.write_text(json.dumps(raw, sort_keys=True), encoding="utf-8")

    with pytest.raises(PolicyError, match="immutable commitment"):
        ARC3Controller.restore(
            context,
            preset=ControllerPreset.FULL,
            checkpoint_path=tampered,
            cadence_config=cadence,
        )


@pytest.mark.integration
def test_fast_goal_updates_remain_deferred_and_checkpointed_until_deep(
    tmp_path: Path,
) -> None:
    context = _context(tmp_path, label="deferred-goal-updates")
    cadence = CadenceConfig(repeated_no_progress_threshold=16)
    session = SyntheticAdapter(seed=7, size=8, max_steps=32).open(SYNTHETIC_GAME_ID)
    controller = ARC3Controller(ControllerPreset.FULL, cadence_config=cadence)
    controller.reset(context)
    controller.observe(session.observation)

    checkpoint = None
    expected_queue: list[dict[str, object]] = []
    for _ordinal in range(10):
        decision = controller.choose_action()
        controller.apply_consequence(session.step(decision.action))
        selection = controller._reasoning_selection
        if selection is not None and selection.path.value == "FAST":
            assert controller._pending_goal_transitions
            checkpoint = controller._last_checkpoint
            expected_queue = [
                cast(dict[str, object], controller._serialize_goal_transition(item))
                for item in controller._pending_goal_transitions
            ]
            break
    assert checkpoint is not None
    controller.journal.close()

    restored = ARC3Controller.restore(
        context,
        preset=ControllerPreset.FULL,
        checkpoint_path=checkpoint.path,
        cadence_config=cadence,
    )
    assert [
        cast(dict[str, object], restored._serialize_goal_transition(item))
        for item in restored._pending_goal_transitions
    ] == expected_queue
    restored.close()


@pytest.mark.integration
def test_game_over_contradiction_counts_toward_repeated_no_progress(
    tmp_path: Path,
) -> None:
    context = _context(tmp_path, label="game-over-no-progress")
    cadence = CadenceConfig(repeated_no_progress_threshold=2)
    session = SyntheticAdapter(seed=7, size=8, max_steps=1).open(SYNTHETIC_GAME_ID)
    controller = ARC3Controller(ControllerPreset.FULL, cadence_config=cadence)
    controller.reset(context)
    controller.observe(session.observation)

    first = controller.choose_action()
    loss = session.step(first.action)
    assert loss.state.value == "GAME_OVER"
    controller.apply_consequence(loss)
    assert controller.cadence_state["no_progress_streak"] == 1

    reset = controller.choose_action()
    controller.apply_consequence(session.step(reset.action))
    assert controller.cadence_state["no_progress_streak"] == 2
    selection = controller._reasoning_selection
    assert selection is not None
    assert "REPEATED_NO_PROGRESS" in {trigger.value for trigger in selection.ordered_triggers}
    controller.close()


@pytest.mark.integration
def test_fast_pending_action_checkpoint_restores_prediction_exactly(
    tmp_path: Path,
) -> None:
    context = _context(tmp_path, label="fast-pending-restore")
    cadence = CadenceConfig(repeated_no_progress_threshold=16)
    session = SyntheticAdapter(seed=7, size=8, max_steps=32).open(SYNTHETIC_GAME_ID)
    controller = ARC3Controller(ControllerPreset.FULL, cadence_config=cadence)
    controller.reset(context)
    controller.observe(session.observation)

    pending_decision = None
    checkpoint = None
    for _ordinal in range(10):
        decision = controller.choose_action()
        controller.apply_consequence(session.step(decision.action))
        selection = controller._reasoning_selection
        if selection is not None and selection.path.value == "FAST":
            pending_decision = controller.choose_action()
            checkpoint = controller._last_checkpoint
            break
    assert pending_decision is not None
    assert checkpoint is not None
    controller.journal.close()

    restored = ARC3Controller.restore(
        context,
        preset=ControllerPreset.FULL,
        checkpoint_path=checkpoint.path,
        cadence_config=cadence,
    )
    assert restored.phase is ControllerPhase.AWAITING_CONSEQUENCE
    assert restored.snapshot.pending_action == pending_decision.action
    restored.close()
