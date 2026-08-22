from __future__ import annotations

import json
from collections.abc import Callable
from copy import deepcopy
from pathlib import Path
from typing import cast
from unittest.mock import patch

import pytest

from arc3.config import ARC3Config, BudgetConfig
from arc3.errors import ARC3ValidationError, CheckpointError, PolicyError
from arc3.lab.rule_change import (
    RuleChangeCase,
    RuleChangeEvaluatorEpisode,
    intervention_schedule,
    noise_control_schedule,
    open_rule_change_case,
)
from arc3.policy import ARC3Controller, ControllerPhase, ControllerPreset, RunContext
from arc3.trace import sha256_json
from arc3.types import EnvironmentMode, GameStateName, JSONValue, RationaleCategory


def _context(tmp_path: Path, case: RuleChangeCase, *, label: str) -> RunContext:
    return RunContext(
        run_id=f"run-stage06-{label}",
        episode_id=f"episode-stage06-{label}",
        game_id=str(open_rule_change_case(case).session.observation.game_id),
        trace_root=tmp_path / label / "trace",
        checkpoint_root=tmp_path / label / "checkpoint",
        config=ARC3Config(
            mode=EnvironmentMode.SYNTHETIC,
            seed=case.seed,
            profile="stage06-controller-test",
            budgets=BudgetConfig(max_actions=48, max_search_nodes=2_048),
        ),
        git_commit="stage06-controller-test",
    )


def _projection(controller: ARC3Controller) -> dict[str, JSONValue]:
    return controller.mechanics_lifecycle_projection


def _write_rehashed_checkpoint(
    source: Path,
    target: Path,
    mutate: Callable[[dict[str, object]], None],
) -> Path:
    raw = json.loads(source.read_text(encoding="utf-8"))
    assert isinstance(raw, dict)
    mutated = deepcopy(raw)
    mutate(mutated)
    material = {key: value for key, value in mutated.items() if key != "checkpoint_hash"}
    mutated["checkpoint_hash"] = sha256_json(material)
    target.write_text(json.dumps(mutated, sort_keys=True), encoding="utf-8")
    return target


def _rewrite_trace_tail(
    path: Path,
    mutate: Callable[[dict[str, object]], None],
) -> None:
    lines = path.read_text(encoding="utf-8").splitlines()
    assert lines
    raw_tail = json.loads(lines[-1])
    assert isinstance(raw_tail, dict)
    mutate(raw_tail)
    material = {key: value for key, value in raw_tail.items() if key != "event_hash"}
    raw_tail["event_hash"] = sha256_json(material)
    lines[-1] = json.dumps(raw_tail, sort_keys=True, separators=(",", ":"))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _rewrite_support_index_and_checkpoint(
    *,
    trace_path: Path,
    checkpoint_path: Path,
    target_checkpoint_path: Path,
    event_type: str,
    support_index: object,
) -> Path:
    """Rehash a support receipt, its suffix, and the bound checkpoint commitment."""

    raw_events = [
        cast(dict[str, object], json.loads(line))
        for line in trace_path.read_text(encoding="utf-8").splitlines()
    ]
    target_index = next(
        index for index, event in enumerate(raw_events) if event["event_type"] == event_type
    )
    target_payload = cast(dict[str, object], raw_events[target_index]["payload"])
    target_payload["support_index"] = support_index

    raw_checkpoint = cast(
        dict[str, object], json.loads(checkpoint_path.read_text(encoding="utf-8"))
    )
    prior_tail_event_id = cast(str, raw_checkpoint["trace_tail_event_id"])
    prior_tail_index = next(
        index for index, event in enumerate(raw_events) if event["event_id"] == prior_tail_event_id
    )
    assert target_index <= prior_tail_index
    assert prior_tail_index + 1 == len(raw_events) - 1
    receipt = raw_events[-1]
    assert receipt["event_type"] == "run.checkpoint_written"

    for index in range(target_index, prior_tail_index + 1):
        event = raw_events[index]
        event["previous_event_hash"] = raw_events[index - 1]["event_hash"]
        material = {key: value for key, value in event.items() if key != "event_hash"}
        event["event_hash"] = sha256_json(material)

    prior_tail_hash = cast(str, raw_events[prior_tail_index]["event_hash"])
    raw_checkpoint["trace_tail_hash"] = prior_tail_hash
    checkpoint_material = {
        key: value for key, value in raw_checkpoint.items() if key != "checkpoint_hash"
    }
    checkpoint_hash = sha256_json(checkpoint_material)
    raw_checkpoint["checkpoint_hash"] = checkpoint_hash

    receipt["previous_event_hash"] = prior_tail_hash
    receipt_payload = cast(dict[str, object], receipt["payload"])
    receipt_payload["checkpoint_hash"] = checkpoint_hash
    receipt_payload["envelope_prior_trace_tail_hash"] = prior_tail_hash
    receipt_material = {key: value for key, value in receipt.items() if key != "event_hash"}
    receipt["event_hash"] = sha256_json(receipt_material)

    trace_path.write_text(
        "".join(
            json.dumps(event, sort_keys=True, separators=(",", ":")) + "\n" for event in raw_events
        ),
        encoding="utf-8",
    )
    target_checkpoint_path.write_text(json.dumps(raw_checkpoint, sort_keys=True), encoding="utf-8")
    return target_checkpoint_path


def _drive_case(
    tmp_path: Path,
    case: RuleChangeCase,
    *,
    label: str,
    stop: Callable[[ARC3Controller, RuleChangeEvaluatorEpisode], bool] | None = None,
) -> tuple[ARC3Controller, RuleChangeEvaluatorEpisode]:
    episode = open_rule_change_case(case)
    controller = ARC3Controller(ControllerPreset.FULL)
    controller.reset(_context(tmp_path, case, label=label))
    controller.observe(episode.session.observation)
    armed = False
    while controller.phase not in {ControllerPhase.COMPLETE, ControllerPhase.GAME_OVER}:
        if controller.snapshot.actions_used >= 48:
            raise AssertionError(
                {
                    "armed": armed,
                    "environment": episode.projection.to_dict(),
                    "actions": [
                        {
                            "action": item.action.name.value,
                            "before": item.before_position,
                            "after": item.after_position,
                            "result": item.result_kind,
                        }
                        for item in episode.truth_receipts
                    ],
                    "mechanics": _projection(controller),
                }
            )
        decision = controller.choose_action()
        if (
            not armed
            and episode.ready_for_evaluator_arm
            and episode.trigger_eligible(decision.action)
        ):
            readiness = cast(dict[str, object], _projection(controller)["readiness"])
            assert readiness["calibration_complete"] is True
            assert readiness["active_hypothesis_ids"]
            assert readiness["active_model_ids"], (
                _projection(controller),
                [item.to_dict() for item in episode.truth_receipts],
            )
            assert readiness["pending_prediction_receipt_id"] is not None
            episode.arm_trigger()
            armed = True
        controller.apply_consequence(episode.take(decision.action).observation)
        if stop is not None and stop(controller, episode):
            break
        assert controller.snapshot.actions_used <= 48
    assert armed
    return controller, episode


def _drive_to_staged_pretrigger(
    tmp_path: Path,
    case: RuleChangeCase,
    *,
    label: str,
) -> tuple[ARC3Controller, RuleChangeEvaluatorEpisode, dict[str, object]]:
    """Reach the frozen before-choose boundary without arming evaluator truth."""

    episode = open_rule_change_case(case)
    controller = ARC3Controller(ControllerPreset.FULL)
    controller.reset(_context(tmp_path, case, label=label))
    controller.observe(episode.session.observation)
    while controller.snapshot.actions_used < 32:
        readiness = cast(dict[str, object], _projection(controller)["readiness"])
        if (
            episode.ready_for_evaluator_arm
            and readiness["calibration_complete"] is True
            and readiness["active_model_ids"]
            and readiness["active_plan_id"] is not None
            and readiness["active_plan_dependency_satisfied"] is True
            and readiness["active_plan_current_at_latest_state"] is True
            and readiness["active_plan_current_step_nontrivial"] is True
            and readiness["active_plan_invalidated"] is False
            and readiness["higher_priority_probe_present"] is False
            and readiness["action_boundary_open"] is True
            and readiness["pending_action_present"] is False
            and readiness["pending_prediction_receipt_id"] is None
            and readiness["pending_prediction_model_ids"] == []
            and readiness["pending_prediction_dependent_plan_ids"] == []
        ):
            assert episode.projection.prechange_support_receipts == case.support_required
            return controller, episode, readiness
        decision = controller.choose_action()
        controller.apply_consequence(episode.take(decision.action).observation)
    raise AssertionError(
        {
            "environment": episode.projection.to_dict(),
            "mechanics": _projection(controller),
        }
    )


@pytest.mark.integration
@pytest.mark.parametrize(
    ("schedule_index", "label", "expected_contexts"),
    (
        (
            0,
            "intervention",
            ["opaque-handle:ACTION4", "opaque-handle:ACTION1"],
        ),
        (
            3,
            "intervention-cycle1234",
            ["opaque-handle:ACTION1", "opaque-handle:ACTION2"],
        ),
    ),
)
def test_repeated_successor_contradiction_reopens_in_order_and_completes(
    tmp_path: Path,
    schedule_index: int,
    label: str,
    expected_contexts: list[str] | None,
) -> None:
    controller, episode = _drive_case(
        tmp_path,
        intervention_schedule()[schedule_index],
        label=label,
    )

    assert episode.session.observation.state is GameStateName.WIN
    projection = _projection(controller)
    candidates = cast(list[dict[str, object]], projection["change_candidates"])
    assert [item["provisional_status"] for item in candidates] == ["CONFIRMED"]
    epochs = cast(list[dict[str, object]], projection["epochs"])
    assert [item["epoch_index"] for item in epochs if item["level_index"] == 0] == [0, 1]
    assert projection["suspended_model_ids"] == []
    assert projection["demoted_model_ids"]

    events = controller.journal.verify_manifest(include_active=True)
    event_types = [event.event_type for event in events]
    successor_support = [
        event for event in events if event.event_type == "mechanics.successor_evidence_supported"
    ]
    assert [event.payload["support_index"] for event in successor_support] == [1, 2]
    assert all(
        event.payload["observed_effect_signature"] == candidates[0]["successor_effect_signature"]
        for event in successor_support
    )
    assert candidates[0]["supporting_contradiction_event_ids"] == [
        event.payload["contradiction_event_id"] for event in successor_support
    ]
    assert candidates[0]["supporting_successor_transition_ids"] == [
        event.payload["source_transition_id"] for event in successor_support
    ]
    assert candidates[0]["supporting_discrimination_context_ids"] == [
        event.payload["discrimination_context_id"] for event in successor_support
    ]
    if expected_contexts is not None:
        assert candidates[0]["supporting_discrimination_context_ids"] == expected_contexts
    required = (
        "hypothesis.contradicted",
        "mechanics.change_candidate_created",
        "model.rule_demoted",
        "hypothesis.reopened",
        "mechanics.change_confirmed",
        "mechanics.epoch_opened",
    )
    indices = [event_types.index(event_type) for event_type in required]
    assert indices == sorted(indices)
    reexploration = next(
        event
        for event in events
        if event.event_type == "action.selected" and event.payload["reexploration"] is True
    )
    assert reexploration.payload["rationale_category"] == RationaleCategory.REEXPLORATION
    assert reexploration.payload["active_world_model_ids"] == []


@pytest.mark.integration
def test_stationary_outlier_resolves_without_confirmed_reopening(tmp_path: Path) -> None:
    controller, episode = _drive_case(
        tmp_path,
        noise_control_schedule()[0],
        label="noise",
    )

    assert episode.session.observation.state is GameStateName.WIN
    projection = _projection(controller)
    candidates = cast(list[dict[str, object]], projection["change_candidates"])
    assert [item["provisional_status"] for item in candidates] == ["RESOLVED_NOISE"]
    epochs = cast(list[dict[str, object]], projection["epochs"])
    assert [item["epoch_index"] for item in epochs if item["level_index"] == 0] == [0]
    assert projection["demoted_model_ids"] == []
    assert projection["resolved_noise_transition_ids"]
    events = controller.journal.verify_manifest(include_active=True)
    recovery_events = [
        event for event in events if event.event_type == "mechanics.predecessor_recovery_supported"
    ]
    assert len(recovery_events) == 2
    assert cast(list[str], candidates[0]["predecessor_recovery_event_ids"]) == [
        event.event_id for event in recovery_events
    ]
    resolved_index = next(
        index
        for index, event in enumerate(events)
        if event.event_type == "mechanics.change_candidate_resolved"
    )
    assert all(events.index(event) < resolved_index for event in recovery_events)
    forbidden = {
        "model.rule_demoted",
        "hypothesis.reopened",
        "mechanics.change_confirmed",
        "mechanics.epoch_opened",
    }
    assert not forbidden & {event.event_type for event in events}
    checkpoint = controller.checkpoint()
    expected_projection = controller.mechanics_lifecycle_projection
    controller.journal.close()
    restored = ARC3Controller.restore(
        _context(tmp_path, noise_control_schedule()[0], label="noise"),
        preset=ControllerPreset.FULL,
        checkpoint_path=checkpoint.path,
    )
    assert restored.mechanics_lifecycle_projection == expected_projection
    restored.journal.close()


@pytest.mark.replay
@pytest.mark.parametrize(
    ("receipt_kind", "invalid_index"),
    (
        ("successor", True),
        ("successor", 1.0),
        ("recovery", True),
        ("recovery", 1.0),
    ),
)
def test_restore_rejects_non_integer_mechanics_support_indices(
    tmp_path: Path,
    receipt_kind: str,
    invalid_index: object,
) -> None:
    is_successor = receipt_kind == "successor"
    case = intervention_schedule()[0] if is_successor else noise_control_schedule()[0]
    label = f"typed-{receipt_kind}-support-index-{type(invalid_index).__name__}"
    controller, _ = _drive_case(tmp_path, case, label=label)
    checkpoint = controller.checkpoint()
    controller.journal.close()
    context = _context(tmp_path, case, label=label)
    tampered = _rewrite_support_index_and_checkpoint(
        trace_path=context.trace_root / "active.jsonl",
        checkpoint_path=checkpoint.path,
        target_checkpoint_path=tmp_path / f"tampered-{label}.json",
        event_type=(
            "mechanics.successor_evidence_supported"
            if is_successor
            else "mechanics.predecessor_recovery_supported"
        ),
        support_index=invalid_index,
    )

    with pytest.raises(
        PolicyError,
        match=("successor support disagrees" if is_successor else "predecessor recovery linkage"),
    ):
        ARC3Controller.restore(
            context,
            preset=ControllerPreset.FULL,
            checkpoint_path=tampered,
        )


@pytest.mark.replay
def test_rehashed_checkpoint_cannot_invent_predecessor_recovery_authority(
    tmp_path: Path,
) -> None:
    def has_live_candidate(
        controller: ARC3Controller, _episode: RuleChangeEvaluatorEpisode
    ) -> bool:
        return any(
            item["provisional_status"] == "CANDIDATE"
            for item in cast(
                list[dict[str, object]],
                controller.mechanics_lifecycle_projection["change_candidates"],
            )
        )

    cases = (
        (intervention_schedule()[0], "live-recovery-tamper", has_live_candidate),
        (noise_control_schedule()[0], "terminal-recovery-tamper", None),
    )
    for case, label, stop in cases:
        controller, _ = _drive_case(tmp_path, case, label=label, stop=stop)
        events = controller.journal.verify_manifest(include_active=True)
        projection = controller.mechanics_lifecycle_projection
        candidates = cast(list[dict[str, object]], projection["change_candidates"])
        candidate = candidates[0]
        candidate_id = cast(str, candidate["candidate_id"])
        opening_index = next(
            index
            for index, event in enumerate(events)
            if event.event_type == "mechanics.change_candidate_created"
            and event.payload.get("candidate_id") == candidate_id
        )
        unrelated_observation_id = next(
            event.event_id
            for event in events[:opening_index]
            if event.event_type == "observation.received"
        )
        original_recovery_ids = cast(list[str], candidate["predecessor_recovery_event_ids"])
        if stop is None:
            assert candidate["provisional_status"] == "RESOLVED_NOISE"
            assert len(original_recovery_ids) == 2
        else:
            assert candidate["provisional_status"] == "CANDIDATE"
            assert original_recovery_ids == []
        checkpoint = controller.checkpoint()
        controller.journal.close()

        def inject_unrelated_observation(
            raw: dict[str, object],
            *,
            expected_candidate_id: str = candidate_id,
            unrelated_source_id: str = unrelated_observation_id,
        ) -> None:
            state = cast(
                dict[str, object], cast(dict[str, object], raw["state"])["derived_controller_state"]
            )
            world = cast(dict[str, object], state["world_model_ensemble"])
            mechanics = cast(dict[str, object], world["mechanics_lifecycle"])
            restored_candidates = cast(list[dict[str, object]], mechanics["change_candidates"])
            restored_candidate = next(
                item
                for item in restored_candidates
                if item["candidate_id"] == expected_candidate_id
            )
            recovered = cast(list[str], restored_candidate["predecessor_recovery_event_ids"])
            if recovered:
                recovered[0] = unrelated_source_id
            else:
                recovered.append(unrelated_source_id)

        tampered = _write_rehashed_checkpoint(
            checkpoint.path,
            tmp_path / f"tampered-{label}.json",
            inject_unrelated_observation,
        )
        with pytest.raises(PolicyError, match="predecessor recovery"):
            ARC3Controller.restore(
                _context(tmp_path, case, label=label),
                preset=ControllerPreset.FULL,
                checkpoint_path=tampered,
            )


@pytest.mark.replay
def test_checkpoint_commitment_rejects_missing_receipt_and_rehashed_state_or_rng(
    tmp_path: Path,
) -> None:
    case = intervention_schedule()[0]
    label = "checkpoint-commitment"
    controller, _, _ = _drive_to_staged_pretrigger(
        tmp_path,
        case,
        label=label,
    )
    checkpoint = controller.checkpoint()
    receipt = controller.journal.tail_event
    assert receipt is not None
    assert receipt.event_type == "run.checkpoint_written"
    assert receipt.payload == {
        "commitment_schema": "arc3.memory.checkpoint-commitment.v0.1",
        "checkpoint_sequence": receipt.payload["checkpoint_sequence"],
        "checkpoint_hash": checkpoint.envelope.checkpoint_hash,
        "checkpoint_schema": "arc3.checkpoint.v0.1",
        "derived_controller_schema": "arc3.memory.derived-controller.v0.1",
        "derived_controller_state_hash": receipt.payload["derived_controller_state_hash"],
        "rng_state_hash": receipt.payload["rng_state_hash"],
        "envelope_prior_trace_tail_event_id": checkpoint.envelope.trace_tail_event_id,
        "envelope_prior_trace_tail_hash": checkpoint.envelope.trace_tail_hash,
        "git_commit": "stage06-controller-test",
        "config_hash": str(_context(tmp_path, case, label=label).config.hash),
        "memory_phase": "ready",
        "controller_phase": "observed",
        "level_index": controller.snapshot.level_index,
        "step_index": controller.snapshot.step_index,
        "pending_submitted_event_id": None,
    }
    assert isinstance(receipt.payload["checkpoint_sequence"], int)
    assert receipt.previous_event_hash == checkpoint.envelope.trace_tail_hash
    controller.journal.close()

    context = _context(tmp_path, case, label=label)
    active_trace = context.trace_root / "active.jsonl"
    original_trace = active_trace.read_bytes()
    trace_lines = original_trace.splitlines(keepends=True)
    assert len(trace_lines) >= 2
    active_trace.write_bytes(b"".join(trace_lines[:-1]))
    with pytest.raises(
        (ARC3ValidationError, CheckpointError),
        match=r"current checkpoint commitment receipt|checkpoint identity mismatch",
    ):
        ARC3Controller.restore(
            context,
            preset=ControllerPreset.FULL,
            checkpoint_path=checkpoint.path,
        )
    active_trace.write_bytes(original_trace)

    def change_receipt_hash(raw: dict[str, object]) -> None:
        payload = cast(dict[str, object], raw["payload"])
        payload["checkpoint_hash"] = "sha256:" + "f" * 64

    _rewrite_trace_tail(active_trace, change_receipt_hash)
    with pytest.raises(ARC3ValidationError, match="immutable state commitment"):
        ARC3Controller.restore(
            context,
            preset=ControllerPreset.FULL,
            checkpoint_path=checkpoint.path,
        )
    active_trace.write_bytes(original_trace)

    def invent_unfolded_residual(raw: dict[str, object]) -> None:
        state = cast(
            dict[str, object], cast(dict[str, object], raw["state"])["derived_controller_state"]
        )
        state["unresolved_residuals"] = ["invented checkpoint-only authority"]

    state_tampered = _write_rehashed_checkpoint(
        checkpoint.path,
        tmp_path / "tampered-state-commitment.json",
        invent_unfolded_residual,
    )
    with pytest.raises(ARC3ValidationError, match="immutable state commitment"):
        ARC3Controller.restore(
            context,
            preset=ControllerPreset.FULL,
            checkpoint_path=state_tampered,
        )

    def perturb_rng(raw: dict[str, object]) -> None:
        rng_state = cast(list[object], raw["rng_state"])
        internal = cast(list[int], rng_state[1])
        internal[0] ^= 1

    rng_tampered = _write_rehashed_checkpoint(
        checkpoint.path,
        tmp_path / "tampered-rng-commitment.json",
        perturb_rng,
    )
    with pytest.raises(ARC3ValidationError, match="immutable state commitment"):
        ARC3Controller.restore(
            context,
            preset=ControllerPreset.FULL,
            checkpoint_path=rng_tampered,
        )


@pytest.mark.replay
def test_rehashed_checkpoint_cannot_invent_active_goal_target_binding(tmp_path: Path) -> None:
    case = intervention_schedule()[0]
    controller, _ = _drive_case(
        tmp_path,
        case,
        label="goal-target-tamper",
        stop=lambda current, _episode: any(
            item["provisional_status"] == "CANDIDATE"
            for item in cast(
                list[dict[str, object]],
                current.mechanics_lifecycle_projection["change_candidates"],
            )
        ),
    )
    checkpoint = controller.checkpoint()
    controller.journal.close()

    def invent_target_binding(raw: dict[str, object]) -> None:
        state = cast(
            dict[str, object], cast(dict[str, object], raw["state"])["derived_controller_state"]
        )
        goals = cast(dict[str, object], state["goal_registry"])
        active_goal_id = cast(str, goals["active_goal_id"])
        targets = cast(dict[str, list[str]], goals["goal_targets"])
        targets[active_goal_id] = [
            "entity:checkpoint-invented-mover",
            "entity:checkpoint-invented-target",
        ]

    tampered = _write_rehashed_checkpoint(
        checkpoint.path,
        tmp_path / "tampered-goal-target.json",
        invent_target_binding,
    )
    with pytest.raises(PolicyError, match="active goal/target authority"):
        ARC3Controller.restore(
            _context(tmp_path, case, label="goal-target-tamper"),
            preset=ControllerPreset.FULL,
            checkpoint_path=tampered,
        )


@pytest.mark.replay
def test_rehashed_live_candidate_cannot_invent_context_or_last_tested_step(
    tmp_path: Path,
) -> None:
    case = intervention_schedule()[0]
    controller, _ = _drive_case(
        tmp_path,
        case,
        label="live-candidate-dynamic-tamper",
        stop=lambda current, _episode: any(
            item["provisional_status"] == "CANDIDATE"
            for item in cast(
                list[dict[str, object]],
                current.mechanics_lifecycle_projection["change_candidates"],
            )
        ),
    )
    checkpoint = controller.checkpoint()
    controller.journal.close()

    def candidate_projection(raw: dict[str, object]) -> dict[str, object]:
        state = cast(
            dict[str, object], cast(dict[str, object], raw["state"])["derived_controller_state"]
        )
        world = cast(dict[str, object], state["world_model_ensemble"])
        mechanics = cast(dict[str, object], world["mechanics_lifecycle"])
        return cast(list[dict[str, object]], mechanics["change_candidates"])[0]

    def invent_context(raw: dict[str, object]) -> None:
        candidate = candidate_projection(raw)
        contexts = cast(list[str], candidate["supporting_discrimination_context_ids"])
        contexts.append("opaque-handle:checkpoint-invented")

    def advance_last_tested_step(raw: dict[str, object]) -> None:
        candidate = candidate_projection(raw)
        candidate["last_tested_step"] = cast(int, candidate["last_tested_step"]) + 1

    def invent_planning_disabled(raw: dict[str, object]) -> None:
        state = cast(
            dict[str, object], cast(dict[str, object], raw["state"])["derived_controller_state"]
        )
        planner = cast(dict[str, object], state["planner_state"])
        assert planner["planning_disabled_after_mismatch"] is False
        planner["planning_disabled_after_mismatch"] = True

    for index, (mutation, message) in enumerate(
        (
            (invent_context, "mechanics lifecycle is malformed"),
            (advance_last_tested_step, "last-tested step"),
            (invent_planning_disabled, "planner-recovery disable flag"),
        )
    ):
        tampered = _write_rehashed_checkpoint(
            checkpoint.path,
            tmp_path / f"tampered-live-candidate-dynamic-{index}.json",
            mutation,
        )
        with pytest.raises(PolicyError, match=message):
            ARC3Controller.restore(
                _context(tmp_path, case, label="live-candidate-dynamic-tamper"),
                preset=ControllerPreset.FULL,
                checkpoint_path=tampered,
            )


@pytest.mark.integration
def test_successor_support_append_failure_does_not_advance_candidate(
    tmp_path: Path,
) -> None:
    case = intervention_schedule()[0]
    controller, episode = _drive_case(
        tmp_path,
        case,
        label="successor-support-append-failure",
        stop=lambda current, _episode: any(
            item["provisional_status"] == "CANDIDATE"
            for item in cast(
                list[dict[str, object]],
                current.mechanics_lifecycle_projection["change_candidates"],
            )
        ),
    )
    before = cast(
        list[dict[str, object]],
        controller.mechanics_lifecycle_projection["change_candidates"],
    )[0]
    assert len(cast(list[str], before["supporting_successor_transition_ids"])) == 1

    decision = controller.choose_action()
    consequence = episode.take(decision.action).observation
    with patch.object(
        controller,
        "_append_mechanics_successor_support",
        side_effect=OSError("injected successor support append failure"),
    ) as append_support:
        with pytest.raises(OSError, match="injected successor support append failure"):
            controller.apply_consequence(consequence)
    append_support.assert_called_once()

    after = cast(
        list[dict[str, object]],
        controller.mechanics_lifecycle_projection["change_candidates"],
    )[0]
    assert after == before
    support_events = [
        event
        for event in controller.journal.verify_manifest(include_active=True)
        if event.event_type == "mechanics.successor_evidence_supported"
        and event.payload.get("candidate_id") == before["candidate_id"]
    ]
    assert [event.payload["support_index"] for event in support_events] == [1]
    controller.journal.close()


@pytest.mark.replay
def test_learned_successor_epoch_checkpoint_restores_exactly(tmp_path: Path) -> None:
    case = intervention_schedule()[0]
    controller, episode = _drive_case(
        tmp_path,
        case,
        label="successor-restore",
    )
    assert episode.session.observation.state is GameStateName.WIN
    expected = controller.mechanics_lifecycle_projection
    epochs = cast(list[dict[str, object]], expected["epochs"])
    successor = max(epochs, key=lambda item: cast(int, item["epoch_index"]))
    assert successor["epoch_index"] == 1
    assert successor["active_hypothesis_ids"]
    assert successor["active_model_ids"]
    checkpoint = controller.checkpoint()
    controller.journal.close()

    restored = ARC3Controller.restore(
        _context(tmp_path, case, label="successor-restore"),
        preset=ControllerPreset.FULL,
        checkpoint_path=checkpoint.path,
    )
    assert restored.mechanics_lifecycle_projection == expected
    restored.journal.close()


@pytest.mark.replay
def test_staged_pretrigger_plan_restores_before_one_real_prediction_and_submit(
    tmp_path: Path,
) -> None:
    case = intervention_schedule()[35]
    controller, episode, readiness = _drive_to_staged_pretrigger(
        tmp_path,
        case,
        label="staged-pretrigger",
    )
    assert case.palette_variant.value == "affine_nonidentity"
    assert case.action_variant.value == "cycle1234"
    plan_id = cast(str, readiness["active_plan_id"])
    plan_action = cast(dict[str, object], readiness["active_plan_current_step_action"])
    before_events = controller.journal.verify_manifest(include_active=True)
    retired_contact_index = max(
        index
        for index, event in enumerate(before_events)
        if event.event_type == "goal.retired"
        and str(event.payload.get("goal_id", "")).startswith("goal:contact:")
        and event.payload.get("summary")
        == "contact target changed after mover reached its prior observed cells"
    )
    successor_contact_index = (
        next(
            index
            for index, event in enumerate(before_events[retired_contact_index + 1 :], start=1)
            if event.event_type == "goal.candidate_created"
            and str(event.payload.get("goal_id", "")).startswith("goal:contact:")
        )
        + retired_contact_index
    )
    successor_contact = before_events[successor_contact_index]
    retirement = before_events[retired_contact_index]
    assert set(cast(list[str], successor_contact.payload["source_event_ids"])) & set(
        cast(list[str], retirement.payload["source_event_ids"])
    )
    assert any(
        event.event_type == "simulation.plan_evaluated"
        and event.payload.get("goal_id") == successor_contact.payload["goal_id"]
        and event.payload.get("plan_id") == plan_id
        for event in before_events[successor_contact_index + 1 :]
    )
    assert sum(event.event_type == "action.submitted" for event in before_events) == (
        controller.snapshot.actions_used
    )
    checkpoint = controller.checkpoint()
    expected_projection = controller.mechanics_lifecycle_projection
    expected_actions = controller.snapshot.actions_used
    controller.journal.close()

    restored = ARC3Controller.restore(
        _context(tmp_path, case, label="staged-pretrigger"),
        preset=ControllerPreset.FULL,
        checkpoint_path=checkpoint.path,
    )
    assert restored.phase is ControllerPhase.OBSERVED
    assert restored.mechanics_lifecycle_projection == expected_projection
    assert restored.snapshot.actions_used == expected_actions
    decision = restored.choose_action()
    assert decision.selected_probe_or_plan_id == plan_id
    assert decision.action.name.value == plan_action["name"]
    assert decision.prediction_receipt_id is not None
    after_readiness = cast(dict[str, object], restored.mechanics_lifecycle_projection["readiness"])
    assert after_readiness["pending_action_present"] is True
    assert after_readiness["action_boundary_open"] is False
    assert after_readiness["pending_prediction_receipt_id"] == decision.prediction_receipt_id
    assert after_readiness["pending_prediction_nontrivial"] is True
    assert after_readiness["pending_prediction_dependent_plan_ids"] == [plan_id]
    after_events = restored.journal.verify_manifest(include_active=True)
    assert sum(event.event_type == "action.submitted" for event in after_events) == (
        expected_actions + 1
    )
    assert episode.trigger_eligible(decision.action)
    restored.journal.close()


@pytest.mark.replay
def test_rehashed_staged_plan_mutations_cannot_escape_immutable_plan_receipt(
    tmp_path: Path,
) -> None:
    case = intervention_schedule()[35]
    controller, _, _ = _drive_to_staged_pretrigger(
        tmp_path,
        case,
        label="staged-plan-tamper",
    )
    checkpoint = controller.checkpoint()
    controller.journal.close()

    def mutate_later_step_cost(raw: dict[str, object]) -> None:
        state = cast(
            dict[str, object], cast(dict[str, object], raw["state"])["derived_controller_state"]
        )
        planner = cast(dict[str, object], state["planner_state"])
        plan = cast(dict[str, object], planner["plan"])
        steps = cast(list[dict[str, object]], plan["steps"])
        assert len(steps) > 1
        steps[1]["cost"] = cast(float, steps[1]["cost"]) + 0.25
        score = cast(dict[str, object], plan["score"])
        score["total_cost"] = cast(float, score["total_cost"]) + 0.25

    def mutate_score_estimate(raw: dict[str, object]) -> None:
        state = cast(
            dict[str, object], cast(dict[str, object], raw["state"])["derived_controller_state"]
        )
        planner = cast(dict[str, object], state["planner_state"])
        plan = cast(dict[str, object], planner["plan"])
        score = cast(dict[str, object], plan["score"])
        score["completion_likelihood"] = 0.125
        score["utility"] = cast(float, score["utility"]) - 0.5

    def remove_registered_dependency(raw: dict[str, object]) -> None:
        state = cast(
            dict[str, object], cast(dict[str, object], raw["state"])["derived_controller_state"]
        )
        registry = cast(dict[str, object], state["hypothesis_registry"])
        dependencies = cast(dict[str, list[str]], registry["dependent_plans"])
        hypothesis_id = next(iter(sorted(dependencies)))
        dependencies[hypothesis_id].pop()
        if not dependencies[hypothesis_id]:
            del dependencies[hypothesis_id]

    def inject_dependency_not_registered_by_its_model(raw: dict[str, object]) -> None:
        state = cast(
            dict[str, object], cast(dict[str, object], raw["state"])["derived_controller_state"]
        )
        registry = cast(dict[str, object], state["hypothesis_registry"])
        dependencies = cast(dict[str, list[str]], registry["dependent_plans"])
        target_id = min(dependencies, key=lambda item: (len(dependencies[item]), item))
        donor_plan_id = next(
            plan_id
            for hypothesis_id in sorted(dependencies)
            for plan_id in dependencies[hypothesis_id]
            if plan_id not in dependencies[target_id]
        )
        dependencies[target_id].append(donor_plan_id)
        dependencies[target_id].sort()

    for index, (mutation, message) in enumerate(
        (
            (mutate_later_step_cost, "immutable evaluation receipt"),
            (mutate_score_estimate, "immutable evaluation receipt"),
            (remove_registered_dependency, "depend"),
            (
                inject_dependency_not_registered_by_its_model,
                "depend",
            ),
        )
    ):
        tampered = _write_rehashed_checkpoint(
            checkpoint.path,
            tmp_path / f"tampered-staged-plan-{index}.json",
            mutation,
        )
        with pytest.raises(PolicyError, match=message):
            ARC3Controller.restore(
                _context(tmp_path, case, label="staged-plan-tamper"),
                preset=ControllerPreset.FULL,
                checkpoint_path=tampered,
            )


@pytest.mark.replay
def test_preconfirmation_checkpoint_restores_probe_and_confirms_exactly(
    tmp_path: Path,
) -> None:
    def provisional_change(
        controller: ARC3Controller, _episode: RuleChangeEvaluatorEpisode
    ) -> bool:
        projection = _projection(controller)
        candidates = cast(list[dict[str, object]], projection["change_candidates"])
        return any(item["provisional_status"] == "CANDIDATE" for item in candidates)

    case = intervention_schedule()[0]
    controller, episode = _drive_case(
        tmp_path,
        case,
        label="checkpoint",
        stop=provisional_change,
    )
    expected_projection = _projection(controller)
    expected_actions = controller.snapshot.actions_used
    candidates = cast(list[dict[str, object]], expected_projection["change_candidates"])
    live_candidate = next(item for item in candidates if item["provisional_status"] == "CANDIDATE")
    expected_handle = str(live_candidate["opaque_handle"])
    tested_contexts = cast(list[str], live_candidate["supporting_discrimination_context_ids"])
    checkpoint = controller.checkpoint()
    controller.journal.close()

    restored = ARC3Controller.restore(
        _context(tmp_path, case, label="checkpoint"),
        preset=ControllerPreset.FULL,
        checkpoint_path=checkpoint.path,
    )
    assert restored.mechanics_lifecycle_projection == expected_projection
    assert restored.snapshot.actions_used == expected_actions
    decision = restored.choose_action()
    assert decision.rationale_category is RationaleCategory.DISCRIMINATE_MODELS
    assert live_candidate["change_domain"] == "ACTION_MAPPING"
    assert decision.action.name.value != expected_handle
    assert f"opaque-handle:{decision.action.name.value}" not in tested_contexts
    restored.apply_consequence(episode.take(decision.action).observation)
    resumed_projection = restored.mechanics_lifecycle_projection
    resumed_candidates = cast(list[dict[str, object]], resumed_projection["change_candidates"])
    assert [item["provisional_status"] for item in resumed_candidates] == ["CONFIRMED"]
    resumed_events = restored.journal.verify_manifest(include_active=True)
    successor_support = [
        event
        for event in resumed_events
        if event.event_type == "mechanics.successor_evidence_supported"
        and event.payload.get("candidate_id") == live_candidate["candidate_id"]
    ]
    assert [event.payload["support_index"] for event in successor_support] == [1, 2]
    assert resumed_candidates[0]["supporting_contradiction_event_ids"] == [
        event.payload["contradiction_event_id"] for event in successor_support
    ]
    assert resumed_candidates[0]["supporting_successor_transition_ids"] == [
        event.payload["source_transition_id"] for event in successor_support
    ]
    assert resumed_candidates[0]["supporting_discrimination_context_ids"] == [
        event.payload["discrimination_context_id"] for event in successor_support
    ]
    epochs = cast(list[dict[str, object]], resumed_projection["epochs"])
    assert [item["epoch_index"] for item in epochs if item["level_index"] == 0] == [0, 1]
    assert episode.session.observation.state is GameStateName.NOT_FINISHED


@pytest.mark.replay
def test_rehashed_checkpoint_cannot_invent_derived_authority(tmp_path: Path) -> None:
    case = intervention_schedule()[0]
    controller, _ = _drive_case(tmp_path, case, label="tamper")
    trace_events = controller.journal.verify_manifest(include_active=True)
    projection = _projection(controller)
    actual_suspended_model_ids = set(cast(list[str], projection["suspended_model_ids"]))
    known_model_ids = {
        model_id
        for event in trace_events
        if event.event_type == "model.rule_promoted"
        if isinstance((model_id := event.payload.get("model_id")), str)
    }
    replacement_suspended_model_id = next(
        iter(sorted(known_model_ids - actual_suspended_model_ids))
    )
    actual_invalidated_plan_ids = set(cast(list[str], projection["invalidated_plan_ids"]))
    known_plan_ids = {
        plan_id
        for event in trace_events
        if event.event_type == "simulation.plan_evaluated"
        if isinstance((plan_id := event.payload.get("plan_id")), str)
    }
    never_invalidated_plan_id = next(iter(sorted(known_plan_ids - actual_invalidated_plan_ids)))
    unrelated_prior_event_id = next(
        event.event_id for event in trace_events if event.event_type == "run.started"
    )
    checkpoint = controller.checkpoint()
    controller.journal.close()

    def replace_latest_hash(raw: dict[str, object]) -> None:
        state = cast(
            dict[str, object], cast(dict[str, object], raw["state"])["derived_controller_state"]
        )
        state["normalized_state_hash"] = "sha256:" + "f" * 64

    def invent_suspended_model(raw: dict[str, object]) -> None:
        state = cast(
            dict[str, object], cast(dict[str, object], raw["state"])["derived_controller_state"]
        )
        world = cast(dict[str, object], state["world_model_ensemble"])
        world["suspended_model_ids"] = ["WM-INVENTED"]

    def invent_transition_membership(raw: dict[str, object]) -> None:
        state = cast(
            dict[str, object], cast(dict[str, object], raw["state"])["derived_controller_state"]
        )
        world = cast(dict[str, object], state["world_model_ensemble"])
        mechanics = cast(dict[str, object], world["mechanics_lifecycle"])
        transition_epochs = cast(dict[str, object], mechanics["transition_epochs"])
        transition_epochs["transition:invented"] = str(mechanics["active_epoch_id"])

    def remap_suspended_model(raw: dict[str, object]) -> None:
        state = cast(
            dict[str, object], cast(dict[str, object], raw["state"])["derived_controller_state"]
        )
        world = cast(dict[str, object], state["world_model_ensemble"])
        world["suspended_model_ids"] = [replacement_suspended_model_id]

    def inject_known_but_never_invalidated_plan(raw: dict[str, object]) -> None:
        state = cast(
            dict[str, object], cast(dict[str, object], raw["state"])["derived_controller_state"]
        )
        world = cast(dict[str, object], state["world_model_ensemble"])
        invalidated = cast(list[str], world["invalidated_plan_ids"])
        invalidated.append(never_invalidated_plan_id)

    def rewrite_hypothesis_source(raw: dict[str, object]) -> None:
        state = cast(
            dict[str, object], cast(dict[str, object], raw["state"])["derived_controller_state"]
        )
        registry = cast(dict[str, object], state["hypothesis_registry"])
        events = cast(list[dict[str, object]], registry["events"])
        created = next(item for item in events if item["event_type"] == "hypothesis.created")
        hypothesis_id = cast(str, created["hypothesis_id"])
        sources = cast(list[str], created["created_from_event_ids"])
        sources[0] = unrelated_prior_event_id
        records = cast(dict[str, dict[str, object]], registry["records"])
        records[hypothesis_id]["created_from_event_ids"] = list(sources)

    def lower_action_totals(raw: dict[str, object]) -> None:
        state = cast(
            dict[str, object], cast(dict[str, object], raw["state"])["derived_controller_state"]
        )
        semantics = cast(dict[str, object], state["action_semantics"])
        semantics["actions_used"] = cast(int, semantics["actions_used"]) - 1
        counts = cast(list[dict[str, object]], semantics["action_counts"])
        counted = next(
            item for item in counts if cast(dict[str, object], item["action"])["name"] != "RESET"
        )
        counted["count"] = cast(int, counted["count"]) - 1

    def replace_accepted_effect(raw: dict[str, object]) -> None:
        state = cast(
            dict[str, object], cast(dict[str, object], raw["state"])["derived_controller_state"]
        )
        semantics = cast(dict[str, object], state["action_semantics"])
        registries = [cast(dict[str, object], semantics["registry"])]
        registries.extend(
            cast(dict[str, object], value)
            for value in cast(dict[str, object], semantics["epoch_history"]).values()
        )
        candidate = next(
            item
            for registry in registries
            for item in cast(list[dict[str, object]], registry["candidates"])
            if item["status"] == "ACCEPTED"
        )
        effect = cast(dict[str, object], candidate["canonical_effect"])
        translation = cast(list[int], effect["translation"])
        effect["translation"] = [translation[0] + 2, translation[1]]

    def lower_calibration(raw: dict[str, object]) -> None:
        state = cast(
            dict[str, object], cast(dict[str, object], raw["state"])["derived_controller_state"]
        )
        semantics = cast(dict[str, object], state["action_semantics"])
        recent_frame_hashes = cast(list[str], semantics["recent_frame_hashes"])
        recent_frame_hashes.pop()

    def invent_candidate_confirmation(raw: dict[str, object]) -> None:
        state = cast(
            dict[str, object], cast(dict[str, object], raw["state"])["derived_controller_state"]
        )
        world = cast(dict[str, object], state["world_model_ensemble"])
        mechanics = cast(dict[str, object], world["mechanics_lifecycle"])
        candidate = cast(list[dict[str, object]], mechanics["change_candidates"])[0]
        transition_epochs = cast(dict[str, str], mechanics["transition_epochs"])
        second_transition = next(
            transition_id
            for transition_id in transition_epochs
            if transition_id
            not in cast(list[str], candidate["supporting_successor_transition_ids"])
        )
        candidate["provisional_status"] = "CONTRADICTED"
        candidate["supporting_contradiction_event_ids"] = [
            candidate["first_contradiction_event_id"],
            "hypothesis-event:invented",
        ]
        candidate["supporting_successor_transition_ids"] = [
            *cast(list[str], candidate["supporting_successor_transition_ids"]),
            second_transition,
        ]
        candidate["supporting_discrimination_context_ids"] = [
            *cast(list[str], candidate["supporting_discrimination_context_ids"]),
            "opaque-handle:invented",
        ]

    def reorder_candidate_contexts_only(raw: dict[str, object]) -> None:
        state = cast(
            dict[str, object], cast(dict[str, object], raw["state"])["derived_controller_state"]
        )
        world = cast(dict[str, object], state["world_model_ensemble"])
        mechanics = cast(dict[str, object], world["mechanics_lifecycle"])
        candidate = cast(list[dict[str, object]], mechanics["change_candidates"])[0]
        contexts = cast(list[str], candidate["supporting_discrimination_context_ids"])
        assert len(contexts) == 2
        contexts.reverse()

    def swap_transition_after_receipt(raw: dict[str, object]) -> None:
        state = cast(
            dict[str, object], cast(dict[str, object], raw["state"])["derived_controller_state"]
        )
        world = cast(dict[str, object], state["world_model_ensemble"])
        transitions = cast(list[dict[str, object]], world["preserved_transitions"])
        first, second = transitions[0], transitions[1]
        first_sources = cast(list[str], first["source_event_ids"])
        second_sources = cast(list[str], second["source_event_ids"])
        first_sources[-1] = second_sources[-1]
        first["after"] = deepcopy(second["after"])

    for index, (mutation, message) in enumerate(
        (
            (replace_latest_hash, "normalized state hash"),
            (invent_suspended_model, "unknown model"),
            (remap_suspended_model, "suspended-model authority"),
            (
                inject_known_but_never_invalidated_plan,
                "invalidated-plan authority disagrees",
            ),
            (rewrite_hypothesis_source, "hypothesis payload"),
            (invent_transition_membership, "transition set"),
            (lower_action_totals, "action/fault totals"),
            (replace_accepted_effect, "action semantics/calibration"),
            (lower_calibration, "action semantics/calibration"),
            (reorder_candidate_contexts_only, "successor support disagrees with trace fold"),
            (invent_candidate_confirmation, "mechanics lifecycle"),
            (swap_transition_after_receipt, "source order/type"),
        )
    ):
        tampered = _write_rehashed_checkpoint(
            checkpoint.path,
            tmp_path / f"tampered-{index}.json",
            mutation,
        )
        with pytest.raises(PolicyError, match=message):
            ARC3Controller.restore(
                _context(tmp_path, case, label="tamper"),
                preset=ControllerPreset.FULL,
                checkpoint_path=tampered,
            )


@pytest.mark.replay
def test_rehashed_pending_checkpoint_cannot_borrow_an_older_selection(tmp_path: Path) -> None:
    case = intervention_schedule()[0]
    controller, _ = _drive_case(
        tmp_path,
        case,
        label="pending-tamper",
        stop=lambda current, _episode: any(
            item["provisional_status"] == "CANDIDATE"
            for item in cast(
                list[dict[str, object]],
                current.mechanics_lifecycle_projection["change_candidates"],
            )
        ),
    )
    older_selected = next(
        event.event_id
        for event in controller.journal.verify_manifest(include_active=True)
        if event.event_type == "action.selected"
    )
    controller.choose_action()
    checkpoint = controller.checkpoint()
    controller.journal.close()

    def borrow_selection(raw: dict[str, object]) -> None:
        state = cast(
            dict[str, object], cast(dict[str, object], raw["state"])["derived_controller_state"]
        )
        pending = cast(dict[str, object], state["pending_action"])
        pending["selected_event_id"] = older_selected

    tampered = _write_rehashed_checkpoint(
        checkpoint.path,
        tmp_path / "tampered-pending.json",
        borrow_selection,
    )
    with pytest.raises(ARC3ValidationError, match="exactly bound"):
        ARC3Controller.restore(
            _context(tmp_path, case, label="pending-tamper"),
            preset=ControllerPreset.FULL,
            checkpoint_path=tampered,
        )
