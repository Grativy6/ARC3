from __future__ import annotations

import json
from dataclasses import dataclass, replace
from pathlib import Path
from typing import cast

import pytest

from arc3.adapters.synthetic import SYNTHETIC_GAME_ID, SyntheticAdapter, SyntheticSession
from arc3.config import ARC3Config, BudgetConfig
from arc3.errors import PolicyError
from arc3.memory import MemoryContractError
from arc3.policy import ARC3Controller, ControllerPhase, ControllerPreset, RunContext
from arc3.trace import CodeIdentity, SourceIdentity, sha256_json
from arc3.types import ActionRequest, EnvironmentMode

_CADENCE_CHECKPOINT_FIELDS = {
    "cadence_activation_event_id",
    "cadence_checkpoint_state_event_id",
    "cadence_config",
    "cadence_folded_observation_event_id",
    "cadence_state",
    "pending_goal_transitions",
    "prediction_cache",
    "reasoning_completed_event_id",
    "reasoning_force_fallback",
    "reasoning_selected_event_id",
    "reasoning_selection",
}


@dataclass(frozen=True, slots=True)
class _LegacyFixture:
    legacy_context: RunContext
    current_context: RunContext
    checkpoint_path: Path
    trace_path: Path
    legacy_code_identity: CodeIdentity
    legacy_source_identity: SourceIdentity
    pending_action: ActionRequest
    session: SyntheticSession


def _context(tmp_path: Path, *, git_commit: str, source_version: str) -> RunContext:
    return RunContext(
        run_id="stage08-legacy-migration",
        episode_id="stage08-legacy-migration-episode",
        game_id=SYNTHETIC_GAME_ID,
        trace_root=tmp_path / "trace",
        checkpoint_root=tmp_path / "checkpoint",
        config=ARC3Config(
            mode=EnvironmentMode.SYNTHETIC,
            seed=83,
            profile="stage08-legacy-migration",
            budgets=BudgetConfig(max_actions=16, max_search_nodes=2_048),
        ),
        git_commit=git_commit,
        source_version=source_version,
    )


def _cadence_less_fixture(tmp_path: Path) -> _LegacyFixture:
    legacy_context = _context(
        tmp_path,
        git_commit="stage08-pre-cadence-legacy-commit",
        source_version="pre-cadence-test-v0.1",
    )
    current_context = replace(
        legacy_context,
        git_commit="stage08-current-cadence-commit",
        source_version="cadence-test-v0.2",
    )
    session = SyntheticAdapter(seed=83, size=8, max_steps=32).open(SYNTHETIC_GAME_ID)
    controller = ARC3Controller(ControllerPreset.FULL)
    controller.reset(legacy_context)
    controller.observe(session.observation)
    decision = controller.choose_action()
    checkpoint = controller.checkpoint()
    legacy_source = controller._source
    assert legacy_source is not None
    controller.journal.close()

    raw_checkpoint = cast(
        dict[str, object], json.loads(checkpoint.path.read_text(encoding="utf-8"))
    )
    state_wrapper = cast(dict[str, object], raw_checkpoint["state"])
    derived_state = cast(dict[str, object], state_wrapper["derived_controller_state"])
    planner_state = cast(dict[str, object], derived_state["planner_state"])
    for field_name in _CADENCE_CHECKPOINT_FIELDS:
        planner_state.pop(field_name)

    trace_path = legacy_context.trace_root / "active.jsonl"
    events = [
        cast(dict[str, object], json.loads(line))
        for line in trace_path.read_text(encoding="utf-8").splitlines()
    ]
    assert events[-2]["event_type"] == "reasoning.checkpoint_state"
    del events[-2]

    previous_hash: str | None = None
    for event in events[:-1]:
        event["source"] = legacy_source.to_dict()
        if event["event_type"] == "run.started":
            started_payload = cast(dict[str, object], event["payload"])
            started_payload.pop("cadence_config", None)
            started_payload.pop("cadence_configuration_hash", None)
        event["previous_event_hash"] = previous_hash
        event_material = {key: value for key, value in event.items() if key != "event_hash"}
        event["event_hash"] = sha256_json(event_material)
        previous_hash = cast(str, event["event_hash"])

    prior_event = events[-2]
    raw_checkpoint["trace_tail_event_id"] = prior_event["event_id"]
    raw_checkpoint["trace_tail_hash"] = prior_event["event_hash"]
    checkpoint_material = {
        key: value for key, value in raw_checkpoint.items() if key != "checkpoint_hash"
    }
    checkpoint_hash = sha256_json(checkpoint_material)
    raw_checkpoint["checkpoint_hash"] = checkpoint_hash

    commitment = events[-1]
    commitment["source"] = legacy_source.to_dict()
    commitment["previous_event_hash"] = prior_event["event_hash"]
    commitment_payload = cast(dict[str, object], commitment["payload"])
    commitment_payload["checkpoint_hash"] = checkpoint_hash
    commitment_payload["derived_controller_state_hash"] = sha256_json(derived_state)
    commitment_payload["envelope_prior_trace_tail_event_id"] = prior_event["event_id"]
    commitment_payload["envelope_prior_trace_tail_hash"] = prior_event["event_hash"]
    commitment_material = {key: value for key, value in commitment.items() if key != "event_hash"}
    commitment["event_hash"] = sha256_json(commitment_material)

    legacy_checkpoint_path = legacy_context.checkpoint_root / "legacy-cadence-less.json"
    legacy_checkpoint_path.write_text(json.dumps(raw_checkpoint, sort_keys=True), encoding="utf-8")
    trace_path.write_text(
        "".join(
            json.dumps(event, sort_keys=True, separators=(",", ":")) + "\n" for event in events
        ),
        encoding="utf-8",
    )
    legacy_code = CodeIdentity(
        legacy_context.git_commit,
        str(legacy_context.config.hash),
        {"profile": legacy_context.config.profile},
    )
    return _LegacyFixture(
        legacy_context=legacy_context,
        current_context=current_context,
        checkpoint_path=legacy_checkpoint_path,
        trace_path=trace_path,
        legacy_code_identity=legacy_code,
        legacy_source_identity=legacy_source,
        pending_action=decision.action,
        session=session,
    )


@pytest.mark.replay
def test_explicit_legacy_migration_preserves_bytes_and_crosses_identity_once(
    tmp_path: Path,
) -> None:
    fixture = _cadence_less_fixture(tmp_path)
    legacy_checkpoint_bytes = fixture.checkpoint_path.read_bytes()
    legacy_trace_prefix = fixture.trace_path.read_bytes()

    restored = ARC3Controller.restore(
        fixture.current_context,
        preset=ControllerPreset.FULL,
        checkpoint_path=fixture.checkpoint_path,
        legacy_checkpoint_code_identity=fixture.legacy_code_identity,
        legacy_checkpoint_source_identity=fixture.legacy_source_identity,
    )

    assert fixture.checkpoint_path.read_bytes() == legacy_checkpoint_bytes
    assert fixture.trace_path.read_bytes().startswith(legacy_trace_prefix)
    assert restored.phase is ControllerPhase.AWAITING_CONSEQUENCE
    assert restored.snapshot.pending_action == fixture.pending_action
    migration_checkpoint = restored._last_checkpoint
    assert migration_checkpoint is not None
    assert migration_checkpoint.path != fixture.checkpoint_path
    assert migration_checkpoint.envelope.git_commit == fixture.current_context.git_commit

    events = restored.journal.verify_manifest()
    activations = tuple(
        event for event in events if event.event_type == "reasoning.cadence_activated"
    )
    assert len(activations) == 1
    activation = activations[0]
    assert activation.code_identity.git_commit == fixture.current_context.git_commit
    assert activation.code_identity == restored._code
    assert activation.source == restored._source
    assert activation.source != fixture.legacy_source_identity
    assert (
        activation.payload["legacy_checkpoint_code_identity"]
        == fixture.legacy_code_identity.to_dict()
    )
    assert (
        activation.payload["legacy_checkpoint_source_identity"]
        == fixture.legacy_source_identity.to_dict()
    )
    activation_index = events.index(activation)
    current_events = events[activation_index:]
    assert all(event.code_identity == restored._code for event in current_events)
    assert all(event.source == restored._source for event in current_events)
    assert any(event.event_type == "run.checkpoint_written" for event in current_events)

    event_count = restored.journal.event_count
    with pytest.raises(PolicyError, match="do not resubmit"):
        restored.choose_action()
    assert restored.journal.event_count == event_count
    restored.journal.close()

    resumed = ARC3Controller.restore(
        fixture.current_context,
        preset=ControllerPreset.FULL,
        checkpoint_path=migration_checkpoint.path,
    )
    assert resumed.phase is ControllerPhase.AWAITING_CONSEQUENCE
    assert resumed.snapshot.pending_action == fixture.pending_action
    assert (
        sum(
            event.event_type == "reasoning.cadence_activated"
            for event in resumed.journal.verify_manifest()
        )
        == 1
    )
    resumed.apply_consequence(fixture.session.step(fixture.pending_action))
    next_decision = resumed.choose_action()
    continued_checkpoint = resumed._last_checkpoint
    assert continued_checkpoint is not None
    assert continued_checkpoint.envelope.git_commit == fixture.current_context.git_commit
    assert resumed.journal.tail_event is not None
    assert resumed.journal.tail_event.code_identity.git_commit == fixture.current_context.git_commit
    resumed.journal.close()

    continued = ARC3Controller.restore(
        fixture.current_context,
        preset=ControllerPreset.FULL,
        checkpoint_path=continued_checkpoint.path,
    )
    assert continued.phase is ControllerPhase.AWAITING_CONSEQUENCE
    assert continued.snapshot.pending_action == next_decision.action
    continued.journal.close()


@pytest.mark.replay
def test_cadence_less_checkpoint_requires_complete_explicit_legacy_identity(
    tmp_path: Path,
) -> None:
    fixture = _cadence_less_fixture(tmp_path)
    with pytest.raises(MemoryContractError, match="exactly bound"):
        ARC3Controller.restore(
            fixture.current_context,
            preset=ControllerPreset.FULL,
            checkpoint_path=fixture.checkpoint_path,
        )
    with pytest.raises(PolicyError, match="requires both exact code and source identities"):
        ARC3Controller.restore(
            fixture.current_context,
            preset=ControllerPreset.FULL,
            checkpoint_path=fixture.checkpoint_path,
            legacy_checkpoint_code_identity=fixture.legacy_code_identity,
        )


@pytest.mark.replay
def test_cadence_less_checkpoint_never_implicitly_activates(tmp_path: Path) -> None:
    fixture = _cadence_less_fixture(tmp_path)
    old_trace_bytes = fixture.trace_path.read_bytes()
    old_checkpoint_bytes = fixture.checkpoint_path.read_bytes()
    with pytest.raises(PolicyError, match="requires explicit legacy code and source identities"):
        ARC3Controller.restore(
            fixture.legacy_context,
            preset=ControllerPreset.FULL,
            checkpoint_path=fixture.checkpoint_path,
        )
    assert fixture.trace_path.read_bytes() == old_trace_bytes
    assert fixture.checkpoint_path.read_bytes() == old_checkpoint_bytes


@pytest.mark.replay
@pytest.mark.parametrize("wrong_field", ["code", "source"])
def test_legacy_migration_rejects_wrong_identity(
    tmp_path: Path,
    wrong_field: str,
) -> None:
    fixture = _cadence_less_fixture(tmp_path)
    code_identity = fixture.legacy_code_identity
    source_identity = fixture.legacy_source_identity
    if wrong_field == "code":
        code_identity = replace(code_identity, git_commit="wrong-legacy-commit")
    else:
        source_identity = replace(source_identity, version="wrong-legacy-source")
    with pytest.raises(MemoryContractError, match="exactly bound"):
        ARC3Controller.restore(
            fixture.current_context,
            preset=ControllerPreset.FULL,
            checkpoint_path=fixture.checkpoint_path,
            legacy_checkpoint_code_identity=code_identity,
            legacy_checkpoint_source_identity=source_identity,
        )


@pytest.mark.replay
@pytest.mark.parametrize("invalid_field", ["current_commit", "configuration"])
def test_legacy_migration_rejects_non_cadence_identity_crossing(
    tmp_path: Path,
    invalid_field: str,
) -> None:
    fixture = _cadence_less_fixture(tmp_path)
    code_identity = (
        replace(
            fixture.legacy_code_identity,
            git_commit=fixture.current_context.git_commit,
        )
        if invalid_field == "current_commit"
        else replace(
            fixture.legacy_code_identity,
            config_hash="sha256:" + "f" * 64,
        )
    )
    with pytest.raises(PolicyError, match="same configuration identity"):
        ARC3Controller.restore(
            fixture.current_context,
            preset=ControllerPreset.FULL,
            checkpoint_path=fixture.checkpoint_path,
            legacy_checkpoint_code_identity=code_identity,
            legacy_checkpoint_source_identity=fixture.legacy_source_identity,
        )


@pytest.mark.replay
def test_explicit_legacy_migration_rejects_cadence_bearing_checkpoint(
    tmp_path: Path,
) -> None:
    legacy_context = _context(
        tmp_path,
        git_commit="stage08-cadence-bearing-old-commit",
        source_version="cadence-bearing-old-v0.1",
    )
    session = SyntheticAdapter(seed=83, size=8, max_steps=32).open(SYNTHETIC_GAME_ID)
    controller = ARC3Controller(ControllerPreset.FULL)
    controller.reset(legacy_context)
    controller.observe(session.observation)
    controller.choose_action()
    checkpoint = controller.checkpoint()
    commitment = controller.journal.tail_event
    assert commitment is not None
    old_trace_bytes = (legacy_context.trace_root / "active.jsonl").read_bytes()
    old_checkpoint_bytes = checkpoint.path.read_bytes()
    controller.journal.close()

    current_context = replace(
        legacy_context,
        git_commit="stage08-cadence-bearing-current-commit",
        source_version="cadence-bearing-current-v0.2",
    )
    with pytest.raises(PolicyError, match="restricted to cadence-less checkpoints"):
        ARC3Controller.restore(
            current_context,
            preset=ControllerPreset.FULL,
            checkpoint_path=checkpoint.path,
            legacy_checkpoint_code_identity=commitment.code_identity,
            legacy_checkpoint_source_identity=commitment.source,
        )
    assert (legacy_context.trace_root / "active.jsonl").read_bytes() == old_trace_bytes
    assert checkpoint.path.read_bytes() == old_checkpoint_bytes


@pytest.mark.replay
def test_normal_restore_rejects_current_source_identity_drift(tmp_path: Path) -> None:
    context = _context(
        tmp_path,
        git_commit="stage08-current-cadence-commit",
        source_version="cadence-source-v0.1",
    )
    session = SyntheticAdapter(seed=83, size=8, max_steps=32).open(SYNTHETIC_GAME_ID)
    controller = ARC3Controller(ControllerPreset.FULL)
    controller.reset(context)
    controller.observe(session.observation)
    controller.choose_action()
    checkpoint = controller.checkpoint()
    controller.journal.close()

    drifted_context = replace(context, source_version="cadence-source-v0.2")
    with pytest.raises(MemoryContractError, match="exactly bound"):
        ARC3Controller.restore(
            drifted_context,
            preset=ControllerPreset.FULL,
            checkpoint_path=checkpoint.path,
        )
