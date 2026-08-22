from __future__ import annotations

import json
from collections.abc import Callable
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from typing import cast

import pytest

from arc3.adapters.synthetic import SYNTHETIC_GAME_ID, SyntheticAdapter
from arc3.config import ARC3Config, BudgetConfig
from arc3.errors import PolicyError
from arc3.policy import ARC3Controller, ControllerPhase, ControllerPreset, RunContext
from arc3.trace import sha256_json
from arc3.types import EnvironmentMode
from arc3.world_model import RetrodictionConfig, RetrodictionMode

_CACHED = RetrodictionConfig(mode=RetrodictionMode.CACHED_INCREMENTAL)
_EVENT_TRIGGERED = RetrodictionConfig(mode=RetrodictionMode.EVENT_TRIGGERED)


def _context(tmp_path: Path, *, label: str) -> RunContext:
    return RunContext(
        run_id=f"stage07-replay-{label}",
        episode_id=f"stage07-replay-{label}-episode",
        game_id=SYNTHETIC_GAME_ID,
        trace_root=tmp_path / label / "trace",
        checkpoint_root=tmp_path / label / "checkpoint",
        config=ARC3Config(
            mode=EnvironmentMode.SYNTHETIC,
            seed=37,
            profile=f"stage07-replay-{label}",
            budgets=BudgetConfig(max_actions=16, max_search_nodes=2_048),
        ),
        git_commit="stage07-retrodiction-replay",
    )


def _drive_cached(
    tmp_path: Path,
    *,
    label: str,
    awaiting_prediction: bool = False,
) -> tuple[ARC3Controller, RunContext, SyntheticAdapter]:
    context = _context(tmp_path, label=label)
    session = SyntheticAdapter(seed=37, size=8, max_steps=32).open(SYNTHETIC_GAME_ID)
    controller = ARC3Controller(
        ControllerPreset.FULL,
        retrodiction_config=_CACHED,
    )
    controller.reset(context)
    controller.observe(session.observation)
    for index in range(4):
        decision = controller.choose_action()
        controller.apply_consequence(session.step(decision.action))
        if index == 0:
            original = controller._transitions[0]
            marked = replace(
                original,
                compatible_model_ids=("generic-compatibility-marker",),
            )
            controller._transitions[0] = marked
            controller._transition_summaries[0][0] = marked
    if awaiting_prediction:
        decision = controller.choose_action()
        assert decision.prediction_receipt_id is not None
        assert controller.phase is ControllerPhase.AWAITING_CONSEQUENCE
    return controller, context, session


def _drive_event_reuse(
    tmp_path: Path,
    *,
    label: str,
) -> tuple[ARC3Controller, RunContext]:
    context = _context(tmp_path, label=label)
    session = SyntheticAdapter(seed=37, size=8, max_steps=32).open(SYNTHETIC_GAME_ID)
    controller = ARC3Controller(
        ControllerPreset.FULL,
        retrodiction_config=_EVENT_TRIGGERED,
    )
    controller.reset(context)
    controller.observe(session.observation)
    for _ in range(4):
        decision = controller.choose_action()
        controller.apply_consequence(session.step(decision.action))
    original_features = controller.features

    controller.features = replace(
        original_features,
        use_hypotheses=False,
        use_world_model=False,
    )
    first = controller.choose_action()
    assert first.prediction_receipt_id is not None
    controller.apply_consequence(session.step(first.action))

    controller.features = replace(original_features, use_hypotheses=False)
    second = controller.choose_action()
    assert second.prediction_receipt_id is not None
    controller.apply_consequence(session.step(second.action))
    controller.features = original_features

    completed = [
        event
        for event in controller.journal.verify_manifest()
        if event.event_type == "model.retrodiction_completed"
        and event.payload.get("reason") == "event-receipt-reuse"
    ]
    assert len(completed) == 1
    assert len(completed[0].payload["authorizing_matched_prediction_evidence"]) == 2
    return controller, context


def _rewrite_checkpoint_and_commitment(
    *,
    checkpoint_path: Path,
    trace_path: Path,
    target: Path,
    mutate: Callable[[dict[str, object]], None],
) -> Path:
    raw_checkpoint = cast(
        dict[str, object], json.loads(checkpoint_path.read_text(encoding="utf-8"))
    )
    mutated = deepcopy(raw_checkpoint)
    mutate(mutated)
    checkpoint_material = {key: value for key, value in mutated.items() if key != "checkpoint_hash"}
    checkpoint_hash = sha256_json(checkpoint_material)
    mutated["checkpoint_hash"] = checkpoint_hash
    target.write_text(json.dumps(mutated, sort_keys=True), encoding="utf-8")

    lines = trace_path.read_text(encoding="utf-8").splitlines()
    tail = cast(dict[str, object], json.loads(lines[-1]))
    assert tail["event_type"] == "run.checkpoint_written"
    payload = cast(dict[str, object], tail["payload"])
    state_wrapper = cast(dict[str, object], mutated["state"])
    derived = cast(dict[str, object], state_wrapper["derived_controller_state"])
    payload["checkpoint_hash"] = checkpoint_hash
    payload["derived_controller_state_hash"] = sha256_json(derived)
    tail_material = {key: value for key, value in tail.items() if key != "event_hash"}
    tail["event_hash"] = sha256_json(tail_material)
    lines[-1] = json.dumps(tail, sort_keys=True, separators=(",", ":"))
    trace_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return target


def _rewrite_trace_suffix_and_checkpoint(
    *,
    checkpoint_path: Path,
    trace_path: Path,
    target: Path,
    event_type: str,
    predicate: Callable[[dict[str, object]], bool],
    mutate_payload: Callable[[dict[str, object]], None],
) -> Path:
    events = [
        cast(dict[str, object], json.loads(line))
        for line in trace_path.read_text(encoding="utf-8").splitlines()
    ]
    target_index = next(
        index
        for index, event in enumerate(events)
        if event["event_type"] == event_type
        and predicate(cast(dict[str, object], event["payload"]))
    )
    mutate_payload(cast(dict[str, object], events[target_index]["payload"]))

    raw_checkpoint = cast(
        dict[str, object], json.loads(checkpoint_path.read_text(encoding="utf-8"))
    )
    prior_tail_id = cast(str, raw_checkpoint["trace_tail_event_id"])
    prior_tail_index = next(
        index for index, event in enumerate(events) if event["event_id"] == prior_tail_id
    )
    assert prior_tail_index + 1 == len(events) - 1
    for index in range(target_index, prior_tail_index + 1):
        events[index]["previous_event_hash"] = events[index - 1]["event_hash"]
        material = {key: value for key, value in events[index].items() if key != "event_hash"}
        events[index]["event_hash"] = sha256_json(material)

    prior_tail_hash = cast(str, events[prior_tail_index]["event_hash"])
    raw_checkpoint["trace_tail_hash"] = prior_tail_hash
    checkpoint_material = {
        key: value for key, value in raw_checkpoint.items() if key != "checkpoint_hash"
    }
    checkpoint_hash = sha256_json(checkpoint_material)
    raw_checkpoint["checkpoint_hash"] = checkpoint_hash
    target.write_text(json.dumps(raw_checkpoint, sort_keys=True), encoding="utf-8")

    commitment = events[-1]
    commitment["previous_event_hash"] = prior_tail_hash
    commitment_payload = cast(dict[str, object], commitment["payload"])
    commitment_payload["checkpoint_hash"] = checkpoint_hash
    commitment_payload["envelope_prior_trace_tail_hash"] = prior_tail_hash
    commitment_material = {key: value for key, value in commitment.items() if key != "event_hash"}
    commitment["event_hash"] = sha256_json(commitment_material)
    trace_path.write_text(
        "".join(
            json.dumps(event, sort_keys=True, separators=(",", ":")) + "\n" for event in events
        ),
        encoding="utf-8",
    )
    return target


@pytest.mark.replay
def test_cached_runtime_and_prediction_receipts_restore_exactly(tmp_path: Path) -> None:
    controller, context, _ = _drive_cached(
        tmp_path,
        label="exact",
        awaiting_prediction=True,
    )
    checkpoint = controller.checkpoint()
    expected_state = controller.retrodiction_state
    expected_prediction_event_id = controller._pending_prediction_event_id
    controller.journal.close()

    restored = ARC3Controller.restore(
        context,
        preset=ControllerPreset.FULL,
        checkpoint_path=checkpoint.path,
        retrodiction_config=_CACHED,
    )
    assert restored.retrodiction_state == expected_state
    assert restored._pending_prediction_event_id == expected_prediction_event_id
    assert restored._transitions[0].compatible_model_ids == ("generic-compatibility-marker",)
    prediction_event = restored.journal.get_event(expected_prediction_event_id)
    assert prediction_event is not None
    assert prediction_event.event_type == "simulation.prediction_emitted"


@pytest.mark.replay
def test_cached_checkpoint_rejects_omitted_or_wrong_mode(tmp_path: Path) -> None:
    controller, context, _ = _drive_cached(tmp_path, label="wrong-mode")
    checkpoint = controller.checkpoint()
    controller.journal.close()

    with pytest.raises(PolicyError, match="retrodiction runtime"):
        ARC3Controller.restore(
            context,
            preset=ControllerPreset.FULL,
            checkpoint_path=checkpoint.path,
        )
    with pytest.raises(PolicyError, match="retrodiction runtime"):
        ARC3Controller.restore(
            context,
            preset=ControllerPreset.FULL,
            checkpoint_path=checkpoint.path,
            retrodiction_config=RetrodictionConfig(
                mode=RetrodictionMode.CACHED_INCREMENTAL,
                capacity=32,
            ),
        )


@pytest.mark.replay
def test_rehashed_cache_entry_tamper_fails_receipt_reconstruction(tmp_path: Path) -> None:
    controller, context, _ = _drive_cached(tmp_path, label="tamper")
    checkpoint = controller.checkpoint()
    assert cast(list[object], controller.retrodiction_state["cache_entries"])
    controller.journal.close()

    def tamper(raw: dict[str, object]) -> None:
        state = cast(dict[str, object], raw["state"])
        derived = cast(dict[str, object], state["derived_controller_state"])
        world = cast(dict[str, object], derived["world_model_ensemble"])
        runtime = cast(dict[str, object], world["retrodiction_state"])
        entries = cast(list[dict[str, object]], runtime["cache_entries"])
        witnesses = cast(list[str], entries[0]["transition_witnesses_hex"])
        witnesses[0] = "00" + witnesses[0][2:]

    tampered = _rewrite_checkpoint_and_commitment(
        checkpoint_path=checkpoint.path,
        trace_path=context.trace_root / "active.jsonl",
        target=tmp_path / "tampered-retrodiction.json",
        mutate=tamper,
    )
    with pytest.raises(PolicyError, match=r"retrodiction runtime|exact reconstruction"):
        ARC3Controller.restore(
            context,
            preset=ControllerPreset.FULL,
            checkpoint_path=tampered,
            retrodiction_config=_CACHED,
        )


@pytest.mark.replay
def test_event_triggered_suffix_authorization_restores_in_exact_order(
    tmp_path: Path,
) -> None:
    controller, context = _drive_event_reuse(tmp_path, label="event-authorization")
    completion = next(
        event
        for event in controller.journal.verify_manifest()
        if event.event_type == "model.retrodiction_completed"
        and event.payload.get("reason") == "event-receipt-reuse"
    )
    prefix_count = cast(int, completion.payload["prefix_count"])
    selected_ids = cast(list[str], completion.payload["selected_transition_ids"])
    authorization = cast(
        list[dict[str, object]],
        completion.payload["authorizing_matched_prediction_evidence"],
    )
    assert [item["transition_id"] for item in authorization] == selected_ids[prefix_count:]
    assert all(item["matched"] is True for item in authorization)
    checkpoint = controller.checkpoint()
    expected_state = controller.retrodiction_state
    controller.journal.close()

    restored = ARC3Controller.restore(
        context,
        preset=ControllerPreset.FULL,
        checkpoint_path=checkpoint.path,
        retrodiction_config=_EVENT_TRIGGERED,
    )
    assert restored.retrodiction_state == expected_state


@pytest.mark.replay
def test_rehashed_event_authorization_order_tamper_is_rejected(tmp_path: Path) -> None:
    controller, context = _drive_event_reuse(tmp_path, label="event-order-tamper")
    checkpoint = controller.checkpoint()
    controller.journal.close()

    def reverse_authorization(payload: dict[str, object]) -> None:
        authorization = cast(
            list[dict[str, object]],
            payload["authorizing_matched_prediction_evidence"],
        )
        authorization.reverse()

    tampered = _rewrite_trace_suffix_and_checkpoint(
        checkpoint_path=checkpoint.path,
        trace_path=context.trace_root / "active.jsonl",
        target=tmp_path / "tampered-event-authorization.json",
        event_type="model.retrodiction_completed",
        predicate=lambda payload: payload.get("reason") == "event-receipt-reuse",
        mutate_payload=reverse_authorization,
    )
    with pytest.raises(PolicyError, match=r"authorization|start/completion"):
        ARC3Controller.restore(
            context,
            preset=ControllerPreset.FULL,
            checkpoint_path=tampered,
            retrodiction_config=_EVENT_TRIGGERED,
        )
