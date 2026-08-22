"""Full derived-controller checkpointing on the Stage 03 checkpoint primitive."""

from __future__ import annotations

import random
from collections.abc import Mapping
from dataclasses import dataclass, replace
from enum import StrEnum
from pathlib import Path
from typing import cast

from arc3.errors import ARC3ValidationError
from arc3.trace import CHECKPOINT_COMMITMENT_SCHEMA as CHECKPOINT_COMMITMENT_SCHEMA
from arc3.trace import (
    CheckpointEnvelope,
    CheckpointStore,
    CodeIdentity,
    EventJournal,
    TraceEvent,
)
from arc3.trace.canonical import normalize_json, require_sha256, sha256_json
from arc3.types import ActionName, ActionRequest, Coordinate, JSONValue

from .models import MemoryContractError
from .retrieval import PersistentMemory

DERIVED_CONTROLLER_SCHEMA = "arc3.memory.derived-controller.v0.1"


class ControllerPhase(StrEnum):
    READY = "ready"
    AWAITING_CONSEQUENCE = "awaiting_consequence"
    GAME_OVER = "game_over"


class RestartDirective(StrEnum):
    """The only safe first operation after restoring controller state."""

    CHOOSE_ACTION = "choose_action"
    AWAIT_CONSEQUENCE = "await_consequence_without_resubmitting"
    MANDATORY_RESET = "mandatory_reset"


def _normalized_object(value: Mapping[str, object], *, field_name: str) -> dict[str, JSONValue]:
    normalized = normalize_json(value)
    if not isinstance(normalized, dict):  # pragma: no cover - Mapping invariant
        raise MemoryContractError(f"{field_name} must be an object")
    return normalized


def _object_from_mapping(value: object, *, field_name: str) -> dict[str, JSONValue]:
    if not isinstance(value, Mapping):
        raise MemoryContractError(f"{field_name} must be an object")
    return _normalized_object(value, field_name=field_name)


def _string_tuple(value: object, *, field_name: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        raise MemoryContractError(f"{field_name} must be an array of non-empty strings")
    return tuple(cast(str, item) for item in value)


@dataclass(frozen=True, slots=True)
class PendingAction:
    """Durable proof that an action was submitted but has no consequence yet."""

    selected_event_id: str
    submitted_event_id: str
    step_index: int
    action: ActionRequest
    prediction_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.selected_event_id or not self.submitted_event_id:
            raise MemoryContractError("pending action receipt IDs must be non-empty")
        if isinstance(self.step_index, bool) or self.step_index < 0:
            raise MemoryContractError("pending action step_index must be non-negative")

    def to_dict(self) -> dict[str, JSONValue]:
        coordinate = self.action.coordinate
        return {
            "selected_event_id": self.selected_event_id,
            "submitted_event_id": self.submitted_event_id,
            "step_index": self.step_index,
            "action": {
                "name": self.action.name.value,
                "coordinate": (
                    {"x": coordinate.x, "y": coordinate.y} if coordinate is not None else None
                ),
            },
            "prediction_ids": list(self.prediction_ids),
        }

    @classmethod
    def from_dict(cls, value: object) -> PendingAction:
        if not isinstance(value, Mapping):
            raise MemoryContractError("pending_action must be an object")
        raw_action = value.get("action")
        if not isinstance(raw_action, Mapping):
            raise MemoryContractError("pending action payload must be an object")
        try:
            name = ActionName(str(raw_action.get("name")))
        except ValueError as error:
            raise MemoryContractError("pending action name is invalid") from error
        raw_coordinate = raw_action.get("coordinate")
        coordinate: Coordinate | None = None
        if raw_coordinate is not None:
            if not isinstance(raw_coordinate, Mapping):
                raise MemoryContractError("pending action coordinate must be an object")
            x = raw_coordinate.get("x")
            y = raw_coordinate.get("y")
            if (
                isinstance(x, bool)
                or not isinstance(x, int)
                or isinstance(y, bool)
                or not isinstance(y, int)
            ):
                raise MemoryContractError("pending action coordinate values must be integers")
            coordinate = Coordinate(x=x, y=y)
        step_index = value.get("step_index")
        if isinstance(step_index, bool) or not isinstance(step_index, int):
            raise MemoryContractError("pending action step_index must be an integer")
        selected = value.get("selected_event_id")
        submitted = value.get("submitted_event_id")
        if not isinstance(selected, str) or not isinstance(submitted, str):
            raise MemoryContractError("pending action receipt IDs must be strings")
        return cls(
            selected_event_id=selected,
            submitted_event_id=submitted,
            step_index=step_index,
            action=ActionRequest(name=name, coordinate=coordinate),
            prediction_ids=_string_tuple(
                value.get("prediction_ids", []), field_name="prediction_ids"
            ),
        )


@dataclass(frozen=True, slots=True)
class DerivedControllerState:
    """All replaceable state needed to continue the observe-model-plan-act loop."""

    normalized_state_hash: str
    level_index: int
    step_index: int
    phase: ControllerPhase
    perception_state: dict[str, JSONValue]
    action_semantics: dict[str, JSONValue]
    hypothesis_registry: dict[str, JSONValue]
    world_model_ensemble: dict[str, JSONValue]
    goal_registry: dict[str, JSONValue]
    explored_state_graph: dict[str, JSONValue]
    planner_state: dict[str, JSONValue]
    memory: PersistentMemory
    pending_action: PendingAction | None = None
    unresolved_residuals: tuple[JSONValue, ...] = ()
    schema: str = DERIVED_CONTROLLER_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != DERIVED_CONTROLLER_SCHEMA:
            raise MemoryContractError(f"unsupported derived-controller schema: {self.schema!r}")
        try:
            require_sha256(self.normalized_state_hash, field="normalized_state_hash")
        except ARC3ValidationError as error:
            raise MemoryContractError(str(error)) from error
        if (
            isinstance(self.level_index, bool)
            or self.level_index < 0
            or isinstance(self.step_index, bool)
            or self.step_index < 0
        ):
            raise MemoryContractError("controller level and step indices must be non-negative")
        try:
            phase = (
                self.phase
                if isinstance(self.phase, ControllerPhase)
                else ControllerPhase(self.phase)
            )
        except ValueError as error:
            raise MemoryContractError("controller phase is invalid") from error
        object.__setattr__(self, "phase", phase)
        if phase is ControllerPhase.AWAITING_CONSEQUENCE and self.pending_action is None:
            raise MemoryContractError("awaiting-consequence phase requires a pending action")
        if phase is not ControllerPhase.AWAITING_CONSEQUENCE and self.pending_action is not None:
            raise MemoryContractError("pending action is valid only while awaiting its consequence")
        for field_name in (
            "perception_state",
            "action_semantics",
            "hypothesis_registry",
            "world_model_ensemble",
            "goal_registry",
            "explored_state_graph",
            "planner_state",
        ):
            value = getattr(self, field_name)
            object.__setattr__(self, field_name, _normalized_object(value, field_name=field_name))
        normalized_residuals = tuple(normalize_json(item) for item in self.unresolved_residuals)
        object.__setattr__(self, "unresolved_residuals", normalized_residuals)

    @property
    def restart_directive(self) -> RestartDirective:
        if self.phase is ControllerPhase.AWAITING_CONSEQUENCE:
            return RestartDirective.AWAIT_CONSEQUENCE
        if self.phase is ControllerPhase.GAME_OVER:
            return RestartDirective.MANDATORY_RESET
        return RestartDirective.CHOOSE_ACTION

    def after_consequence(self, consequence_event: TraceEvent) -> DerivedControllerState:
        if self.pending_action is None:
            raise MemoryContractError("cannot apply a consequence without a pending action")
        if not consequence_event.event_type.startswith("consequence."):
            raise MemoryContractError("pending action can only be cleared by a consequence receipt")
        if consequence_event.step_index != self.pending_action.step_index:
            raise MemoryContractError("consequence receipt step does not match pending action")
        return replace(self, phase=ControllerPhase.READY, pending_action=None)

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "schema": self.schema,
            "normalized_state_hash": self.normalized_state_hash,
            "level_index": self.level_index,
            "step_index": self.step_index,
            "phase": self.phase.value,
            "perception_state": self.perception_state,
            "action_semantics": self.action_semantics,
            "hypothesis_registry": self.hypothesis_registry,
            "world_model_ensemble": self.world_model_ensemble,
            "goal_registry": self.goal_registry,
            "explored_state_graph": self.explored_state_graph,
            "planner_state": self.planner_state,
            "memory": self.memory.to_dict(),
            "pending_action": self.pending_action.to_dict() if self.pending_action else None,
            "unresolved_residuals": list(self.unresolved_residuals),
        }

    @classmethod
    def from_dict(cls, value: object) -> DerivedControllerState:
        if not isinstance(value, Mapping):
            raise MemoryContractError("derived controller state must be an object")
        normalized_hash = value.get("normalized_state_hash")
        level_index = value.get("level_index")
        step_index = value.get("step_index")
        if not isinstance(normalized_hash, str):
            raise MemoryContractError("normalized_state_hash must be a string")
        if isinstance(level_index, bool) or not isinstance(level_index, int):
            raise MemoryContractError("level_index must be an integer")
        if isinstance(step_index, bool) or not isinstance(step_index, int):
            raise MemoryContractError("step_index must be an integer")
        raw_pending = value.get("pending_action")
        raw_residuals = value.get("unresolved_residuals", [])
        if not isinstance(raw_residuals, list):
            raise MemoryContractError("unresolved_residuals must be an array")
        try:
            phase = ControllerPhase(str(value.get("phase")))
        except ValueError as error:
            raise MemoryContractError("controller phase is invalid") from error
        return cls(
            schema=str(value.get("schema")),
            normalized_state_hash=normalized_hash,
            level_index=level_index,
            step_index=step_index,
            phase=phase,
            perception_state=_object_from_mapping(
                value.get("perception_state"), field_name="perception_state"
            ),
            action_semantics=_object_from_mapping(
                value.get("action_semantics"), field_name="action_semantics"
            ),
            hypothesis_registry=_object_from_mapping(
                value.get("hypothesis_registry"), field_name="hypothesis_registry"
            ),
            world_model_ensemble=_object_from_mapping(
                value.get("world_model_ensemble"), field_name="world_model_ensemble"
            ),
            goal_registry=_object_from_mapping(
                value.get("goal_registry"), field_name="goal_registry"
            ),
            explored_state_graph=_object_from_mapping(
                value.get("explored_state_graph"), field_name="explored_state_graph"
            ),
            planner_state=_object_from_mapping(
                value.get("planner_state"), field_name="planner_state"
            ),
            memory=PersistentMemory.from_dict(value.get("memory")),
            pending_action=PendingAction.from_dict(raw_pending)
            if raw_pending is not None
            else None,
            unresolved_residuals=tuple(normalize_json(item) for item in raw_residuals),
        )


@dataclass(frozen=True, slots=True)
class RestoredController:
    state: DerivedControllerState
    rng: random.Random
    envelope: CheckpointEnvelope
    commitment_event: TraceEvent

    @property
    def restart_directive(self) -> RestartDirective:
        return self.state.restart_directive


class ControllerCheckpointManager:
    """Bind full derived state to the verified live trace tail."""

    def __init__(self, root: str | Path) -> None:
        self.store = CheckpointStore(root)
        self._next_checkpoint_sequence: int | None = None

    @staticmethod
    def _validate_pending_tail(
        state: DerivedControllerState,
        journal: EventJournal,
        *,
        commitment_event: TraceEvent | None = None,
    ) -> None:
        pending = state.pending_action
        if pending is None:
            if (
                commitment_event is not None
                and commitment_event.payload.get("pending_submitted_event_id") is not None
            ):
                raise MemoryContractError(
                    "checkpoint commitment invents a pending submitted action"
                )
            return
        submitted = journal.get_event(pending.submitted_event_id)
        if submitted is None:
            raise MemoryContractError(
                "pending action must point to a submitted receipt before checkpointing"
            )
        if commitment_event is None and journal.tail_event_id != pending.submitted_event_id:
            tail = journal.tail_event
            if (
                tail is None
                or tail.event_type != "run.checkpoint_written"
                or tail.payload.get("pending_submitted_event_id") != pending.submitted_event_id
            ):
                raise MemoryContractError(
                    "pending action must point to the submitted tail or its checkpoint suffix"
                )
        if commitment_event is not None and (
            commitment_event.payload.get("pending_submitted_event_id") != pending.submitted_event_id
        ):
            raise MemoryContractError(
                "pending action does not match the checkpoint commitment receipt"
            )
        if submitted.event_type != "action.submitted":
            raise MemoryContractError("pending action tail is not an action.submitted receipt")
        if submitted.step_index != pending.step_index:
            raise MemoryContractError("pending action step does not match submitted receipt")
        selected = journal.get_event(pending.selected_event_id)
        if selected is None or selected.event_type != "action.selected":
            raise MemoryContractError("pending action selected receipt is absent from trace")
        coordinate = pending.action.coordinate
        action_payload: dict[str, JSONValue] = {
            "name": pending.action.name.value,
            "coordinate": (
                {"x": coordinate.x, "y": coordinate.y} if coordinate is not None else None
            ),
        }
        latest_observation_id = state.perception_state.get("latest_observation_event_id")
        if (
            selected.step_index != pending.step_index
            or selected.level_index != state.level_index
            or selected.payload.get("source_observation_event_id") != latest_observation_id
            or selected.payload.get("selected_action") != action_payload
            or submitted.payload.get("selected_event_id") != pending.selected_event_id
            or submitted.payload.get("action") != action_payload
            or submitted.payload.get("decision_id") != selected.payload.get("decision_id")
        ):
            raise MemoryContractError("pending action is not exactly bound to its trace receipts")
        validated_id = submitted.payload.get("validated_event_id")
        validated = journal.get_event(validated_id) if isinstance(validated_id, str) else None
        if (
            validated is None
            or validated.event_type != "action.validated"
            or validated.payload.get("selected_event_id") != pending.selected_event_id
            or validated.payload.get("action") != action_payload
        ):
            raise MemoryContractError("pending action validation receipt is inconsistent")

    @staticmethod
    def _checkpoint_events(
        journal: EventJournal,
        *,
        episode_id: str,
    ) -> tuple[TraceEvent, ...]:
        return tuple(
            event
            for event in journal.verify_manifest()
            if event.episode_id == episode_id and event.event_type == "run.checkpoint_written"
        )

    def _allocate_checkpoint_sequence(
        self,
        journal: EventJournal,
        *,
        episode_id: str,
    ) -> int:
        if self._next_checkpoint_sequence is None:
            existing = self._checkpoint_events(journal, episode_id=episode_id)
            sequences = tuple(event.payload.get("checkpoint_sequence") for event in existing)
            if any(
                isinstance(item, bool) or not isinstance(item, int) for item in sequences
            ) or sequences != tuple(range(1, len(existing) + 1)):
                raise MemoryContractError("checkpoint commitment sequence is not contiguous")
            self._next_checkpoint_sequence = len(existing) + 1
        return self._next_checkpoint_sequence

    @classmethod
    def _validate_commitment_receipt(
        cls,
        *,
        journal: EventJournal,
        episode_id: str,
        code_identity: CodeIdentity,
    ) -> TraceEvent:
        events = journal.verify_manifest()
        if not events:
            raise MemoryContractError("controller restore requires a non-empty verified trace")
        receipt = events[-1]
        if (
            receipt.event_type != "run.checkpoint_written"
            or receipt.episode_id != episode_id
            or receipt.scope != "run"
        ):
            raise MemoryContractError(
                "controller restore requires a current checkpoint commitment receipt"
            )
        checkpoint_events = tuple(
            event
            for event in events
            if event.episode_id == episode_id and event.event_type == "run.checkpoint_written"
        )
        observed_sequences = tuple(
            event.payload.get("checkpoint_sequence") for event in checkpoint_events
        )
        if any(
            isinstance(item, bool) or not isinstance(item, int) for item in observed_sequences
        ) or observed_sequences != tuple(range(1, len(checkpoint_events) + 1)):
            raise MemoryContractError("checkpoint commitment sequence is not contiguous")
        payload = receipt.payload
        prior_event_id = payload.get("envelope_prior_trace_tail_event_id")
        prior_hash = payload.get("envelope_prior_trace_tail_hash")
        prior = journal.get_event(prior_event_id) if isinstance(prior_event_id, str) else None
        try:
            if isinstance(prior_hash, str):
                require_sha256(prior_hash, field="envelope_prior_trace_tail_hash")
        except ARC3ValidationError as error:
            raise MemoryContractError(str(error)) from error
        if (
            payload.get("commitment_schema") != CHECKPOINT_COMMITMENT_SCHEMA
            or payload.get("derived_controller_schema") != DERIVED_CONTROLLER_SCHEMA
            or payload.get("checkpoint_sequence") != len(checkpoint_events)
            or prior is None
            or prior.event_hash != prior_hash
            or receipt.previous_event_hash != prior_hash
            or len(events) < 2
            or events[-2].event_id != prior_event_id
            or receipt.game_id != prior.game_id
            or receipt.source != prior.source
            or receipt.code_identity != code_identity
            or payload.get("git_commit") != code_identity.git_commit
            or payload.get("config_hash") != code_identity.config_hash
        ):
            raise MemoryContractError(
                "checkpoint commitment receipt is not exactly bound to its prior trace tail"
            )
        for field_name in (
            "checkpoint_hash",
            "derived_controller_state_hash",
            "rng_state_hash",
        ):
            value = payload.get(field_name)
            try:
                if not isinstance(value, str):
                    raise ARC3ValidationError(f"{field_name} must be a string")
                require_sha256(value, field=field_name)
            except ARC3ValidationError as error:
                raise MemoryContractError(str(error)) from error
        return receipt

    @staticmethod
    def validate_restored_commitment(restored: RestoredController) -> None:
        """Verify the immutable receipt's complete state and RNG commitments."""

        payload = restored.commitment_event.payload
        envelope = restored.envelope
        if (
            payload.get("checkpoint_hash") != envelope.checkpoint_hash
            or payload.get("envelope_prior_trace_tail_event_id") != envelope.trace_tail_event_id
            or payload.get("envelope_prior_trace_tail_hash") != envelope.trace_tail_hash
            or payload.get("derived_controller_state_hash") != sha256_json(restored.state.to_dict())
            or payload.get("rng_state_hash") != sha256_json(envelope.rng_state)
            or payload.get("checkpoint_schema") != envelope.schema
            or payload.get("memory_phase") != restored.state.phase.value
            or payload.get("controller_phase")
            != (
                restored.state.planner_state.get("controller_phase")
                if isinstance(restored.state.planner_state.get("controller_phase"), str)
                else restored.state.phase.value
            )
            or payload.get("level_index") != restored.state.level_index
            or payload.get("step_index") != restored.state.step_index
            or restored.commitment_event.level_index != restored.state.level_index
            or restored.commitment_event.step_index != restored.state.step_index
            or payload.get("pending_submitted_event_id")
            != (
                restored.state.pending_action.submitted_event_id
                if restored.state.pending_action is not None
                else None
            )
        ):
            raise MemoryContractError(
                "checkpoint envelope disagrees with its immutable state commitment"
            )

    def write(
        self,
        *,
        journal: EventJournal,
        episode_id: str,
        code_identity: CodeIdentity,
        rng: random.Random,
        state: DerivedControllerState,
    ) -> tuple[Path, CheckpointEnvelope]:
        # Opening the journal verifies every pre-existing byte, and append_event
        # verifies each new event and its link before retaining it.  Flush the
        # live tail for durability, then bind the checkpoint to that verified
        # in-memory identity instead of reparsing the complete growing ledger.
        journal.flush()
        if journal.tail_event is None or journal.tail_event_id is None or journal.tail_hash is None:
            raise MemoryContractError("controller checkpoint requires a non-empty verified trace")
        self._validate_pending_tail(state, journal)
        prior_event_id = journal.tail_event_id
        prior_hash = journal.tail_hash
        prior_event = journal.tail_event
        assert prior_event_id is not None
        assert prior_hash is not None
        assert prior_event is not None
        checkpoint_sequence = self._allocate_checkpoint_sequence(
            journal,
            episode_id=episode_id,
        )
        path, envelope = self.store.write(
            run_id=journal.run_id,
            episode_id=episode_id,
            trace_tail_event_id=prior_event_id,
            trace_tail_hash=prior_hash,
            git_commit=code_identity.git_commit,
            config_hash=code_identity.config_hash,
            rng=rng,
            state={"derived_controller_state": state.to_dict()},
        )
        journal.append(
            episode_id=episode_id,
            game_id=prior_event.game_id,
            level_index=state.level_index,
            step_index=state.step_index,
            event_type="run.checkpoint_written",
            source=prior_event.source,
            scope="run",
            payload={
                "commitment_schema": CHECKPOINT_COMMITMENT_SCHEMA,
                "checkpoint_sequence": checkpoint_sequence,
                "checkpoint_hash": envelope.checkpoint_hash,
                "checkpoint_schema": envelope.schema,
                "derived_controller_schema": state.schema,
                "derived_controller_state_hash": sha256_json(state.to_dict()),
                "rng_state_hash": sha256_json(envelope.rng_state),
                "envelope_prior_trace_tail_event_id": prior_event_id,
                "envelope_prior_trace_tail_hash": prior_hash,
                "git_commit": code_identity.git_commit,
                "config_hash": code_identity.config_hash,
                "memory_phase": state.phase.value,
                "controller_phase": (
                    state.planner_state.get("controller_phase")
                    if isinstance(state.planner_state.get("controller_phase"), str)
                    else state.phase.value
                ),
                "level_index": state.level_index,
                "step_index": state.step_index,
                "pending_submitted_event_id": (
                    state.pending_action.submitted_event_id
                    if state.pending_action is not None
                    else None
                ),
            },
            code_identity=code_identity,
        )
        journal.flush()
        self._next_checkpoint_sequence = checkpoint_sequence + 1
        return path, envelope

    def restore(
        self,
        *,
        journal: EventJournal,
        episode_id: str,
        code_identity: CodeIdentity,
        path: str | Path | None = None,
        defer_payload_commitment: bool = False,
    ) -> RestoredController:
        commitment_event = self._validate_commitment_receipt(
            journal=journal,
            episode_id=episode_id,
            code_identity=code_identity,
        )
        raw_sequence = commitment_event.payload.get("checkpoint_sequence")
        assert isinstance(raw_sequence, int) and not isinstance(raw_sequence, bool)
        self._next_checkpoint_sequence = raw_sequence + 1
        prior_event_id = commitment_event.payload.get("envelope_prior_trace_tail_event_id")
        prior_hash = commitment_event.payload.get("envelope_prior_trace_tail_hash")
        committed_checkpoint_hash = commitment_event.payload.get("checkpoint_hash")
        assert isinstance(prior_event_id, str)
        assert isinstance(prior_hash, str)
        assert isinstance(committed_checkpoint_hash, str)
        authoritative_path = (
            self.store.content_addressed_path(committed_checkpoint_hash) if path is None else path
        )
        restored = self.store.restore(
            path=authoritative_path,
            expected_run_id=journal.run_id,
            expected_episode_id=episode_id,
            expected_trace_tail_event_id=prior_event_id,
            expected_trace_tail_hash=prior_hash,
            expected_git_commit=code_identity.git_commit,
            expected_config_hash=code_identity.config_hash,
        )
        state = DerivedControllerState.from_dict(restored.state.get("derived_controller_state"))
        result = RestoredController(
            state=state,
            rng=restored.rng,
            envelope=restored.envelope,
            commitment_event=commitment_event,
        )
        self._validate_pending_tail(state, journal, commitment_event=commitment_event)
        if not defer_payload_commitment:
            self.validate_restored_commitment(result)
        return result
