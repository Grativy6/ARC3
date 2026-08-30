"""Strict action/assessment gate for one Wise Scientist environment run.

This module does not choose actions.  It makes a concise scientific decision
record mandatory before an official adapter call, preserves every consequence,
and refuses to equate a level transition with completion.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from time import monotonic

from arc3.adapters import EnvironmentSession, Observation, ScoreSummary, validate_action_request
from arc3.errors import ARC3ValidationError, EnvironmentStateError
from arc3.evaluation.artifacts import atomic_write_json, atomic_write_text
from arc3.perception import render_grid_svg, render_grid_text
from arc3.trace.canonical import sha256_json
from arc3.types import ActionName, GameStateName, JSONValue
from arc3.wise_scientist.journal import WiseJournal
from arc3.wise_scientist.models import (
    ActCommand,
    AssessCommand,
    DecisionRelevance,
    Distinction,
    GoalStatus,
    RevisionKind,
    ScanCommand,
    Subgoal,
    SubgoalUpdateKind,
    WiseRationale,
    action_to_dict,
)

GOVERNING_OBJECTIVE_ID = "OBJ-WIN"
GOVERNING_OBJECTIVE = "Reach a directly observed official GameState.WIN."
_CHECKPOINT_SCHEMA = "arc3.wise-scientist.checkpoint.v0.1"
_FINAL_RECEIPT_SCHEMA = "arc3.wise-scientist.final-receipt.v0.1"


class WiseRunPhase(StrEnum):
    """Externally visible action-gate phase."""

    NEEDS_SCAN = "NEEDS_SCAN"
    READY_TO_ACT = "READY_TO_ACT"
    AWAITING_ASSESSMENT = "AWAITING_ASSESSMENT"
    COMPLETE = "COMPLETE"
    FAULTED = "FAULTED"


@dataclass(frozen=True, slots=True)
class _PendingConsequence:
    command: ActCommand
    before_observation_hash: str
    after_observation_hash: str
    before_levels_completed: int
    before_belief_hash: str

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "command": self.command.to_dict(),
            "before_observation_hash": self.before_observation_hash,
            "after_observation_hash": self.after_observation_hash,
            "before_levels_completed": self.before_levels_completed,
            "before_belief_hash": self.before_belief_hash,
        }


def observation_payload(observation: Observation) -> dict[str, JSONValue]:
    """Return the complete normalized observation used for its stable identity."""

    returned_action = observation.returned_action
    return {
        "game_id": str(observation.game_id),
        "state": observation.state.value,
        "levels_completed": observation.levels_completed,
        "win_levels": observation.win_levels,
        "available_actions": [item.value for item in observation.available_actions],
        "full_reset": observation.full_reset,
        "returned_action": (
            action_to_dict(returned_action) if returned_action is not None else None
        ),
        "upstream_session_id": observation.upstream_session_id,
        "upstream_metadata": {key: value for key, value in observation.upstream_metadata},
        "frames": [
            {
                "digest": str(frame.digest),
                "width": frame.width,
                "height": frame.height,
                "palette": list(frame.palette),
                "cells": [list(row) for row in frame.cells],
            }
            for frame in observation.frames
        ],
    }


def observation_hash(observation: Observation) -> str:
    """Return the tagged canonical identity of one normalized observation."""

    return sha256_json(
        {
            "schema": "arc3.wise-scientist.observation.v0.1",
            **observation_payload(observation),
        }
    )


def _scorecard_payload(scorecard: ScoreSummary | None) -> JSONValue:
    if scorecard is None:
        return None
    return {
        "surface": scorecard.surface.value,
        "verified": scorecard.verified,
        "scorer": scorecard.scorer,
        "score": scorecard.score,
        "runs": [
            {
                "game_id": str(run.game_id),
                "score": run.score,
                "levels_completed": run.levels_completed,
                "actions": run.actions,
                "resets": run.resets,
                "state": run.state.value,
                "completed": run.completed,
                "level_scores": list(run.level_scores),
                "level_actions": list(run.level_actions),
                "level_baseline_actions": list(run.level_baseline_actions),
            }
            for run in scorecard.runs
        ],
    }


class WiseScientistRun:
    """Validate, execute, assess, and journal one official environment run."""

    def __init__(
        self,
        session: EnvironmentSession,
        artifact_root: str | Path,
        *,
        max_environment_actions: int = 1_000,
        max_resets: int = 20,
        wall_clock_seconds: float = 14_400.0,
    ) -> None:
        if (
            isinstance(max_environment_actions, bool)
            or max_environment_actions <= 0
            or isinstance(max_resets, bool)
            or max_resets <= 0
        ):
            raise ARC3ValidationError("Wise Scientist action and reset budgets must be positive")
        if isinstance(wall_clock_seconds, bool) or wall_clock_seconds <= 0:
            raise ARC3ValidationError("Wise Scientist wall-clock budget must be positive")
        self._session = session
        self.artifact_root = Path(artifact_root).resolve()
        self.artifact_root.mkdir(parents=True, exist_ok=True)
        self.journal = WiseJournal(self.artifact_root / "events.jsonl")
        if self.journal.events:
            raise ARC3ValidationError(
                "artifact root already contains a Wise Scientist journal; "
                "refuse an unsafe implicit resume"
            )
        self._observation = session.observation
        self._observation_index = 0
        self._distinctions: dict[str, Distinction] = {}
        self._subgoals: dict[str, Subgoal] = {}
        self._failed_action_guards: set[str] = set()
        self._pending: _PendingConsequence | None = None
        self._environment_actions = 0
        self._reset_count = 0
        self._max_environment_actions = max_environment_actions
        self._max_resets = max_resets
        self._wall_clock_seconds = wall_clock_seconds
        self._started_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        self._started_monotonic = monotonic()
        self.phase = WiseRunPhase.NEEDS_SCAN

        self.journal.append(
            "run.started",
            {
                "game_id": str(self._observation.game_id),
                "governing_objective_id": GOVERNING_OBJECTIVE_ID,
                "governing_objective": GOVERNING_OBJECTIVE,
                "started_at": self._started_at,
                "budgets": {
                    "max_environment_actions": self._max_environment_actions,
                    "max_resets": self._max_resets,
                    "wall_clock_seconds": self._wall_clock_seconds,
                },
            },
        )
        self._record_observation(source="initial")
        if self._observation.state is GameStateName.WIN:
            self._complete_without_action()
        self._write_checkpoint()

    @property
    def observation(self) -> Observation:
        return self._observation

    @property
    def current_observation_hash(self) -> str:
        return observation_hash(self._observation)

    @property
    def environment_action_count(self) -> int:
        return self._environment_actions

    @property
    def reset_count(self) -> int:
        return self._reset_count

    @property
    def distinctions(self) -> tuple[Distinction, ...]:
        return tuple(self._distinctions[key] for key in sorted(self._distinctions))

    @property
    def subgoals(self) -> tuple[Subgoal, ...]:
        return tuple(self._subgoals[key] for key in sorted(self._subgoals))

    def _belief_hash(self) -> str:
        return sha256_json(
            {
                "distinctions": [item.to_dict() for item in self.distinctions],
                "subgoals": [item.to_dict() for item in self.subgoals],
            }
        )

    def _failure_guard_key(
        self, *, observation_identity: str, belief_identity: str, action: object
    ) -> str:
        return sha256_json(
            {
                "observation_hash": observation_identity,
                "belief_hash": belief_identity,
                "action": action,
            }
        )

    def _record_observation(self, *, source: str) -> None:
        payload = observation_payload(self._observation)
        identity = observation_hash(self._observation)
        index = self._observation_index
        observation_name = f"observation-{index:06d}.json"
        atomic_write_json(
            self.artifact_root / observation_name,
            {
                "schema": "arc3.wise-scientist.observation.v0.1",
                "observation_hash": identity,
                **payload,
            },
        )
        frame_paths: list[JSONValue] = []
        for frame_index, frame in enumerate(self._observation.frames):
            svg_name = f"observation-{index:06d}-frame-{frame_index:02d}.svg"
            text_name = f"observation-{index:06d}-frame-{frame_index:02d}.txt"
            atomic_write_text(self.artifact_root / svg_name, render_grid_svg(frame))
            atomic_write_text(
                self.artifact_root / text_name,
                render_grid_text(frame, spaced=True) + "\n",
            )
            frame_paths.append(
                {
                    "frame_index": frame_index,
                    "digest": str(frame.digest),
                    "svg_path": svg_name,
                    "text_path": text_name,
                }
            )
        self.journal.append(
            "observation.recorded",
            {
                "source": source,
                "observation_index": index,
                "observation_hash": identity,
                "observation_path": observation_name,
                "state": self._observation.state.value,
                "levels_completed": self._observation.levels_completed,
                "win_levels": self._observation.win_levels,
                "available_actions": [item.value for item in self._observation.available_actions],
                "frames": frame_paths,
            },
        )
        self._observation_index += 1

    def _validate_goal_graph(self, additions: tuple[Subgoal, ...]) -> None:
        combined = dict(self._subgoals)
        for goal in additions:
            if goal.goal_id == GOVERNING_OBJECTIVE_ID or goal.goal_id in combined:
                raise ARC3ValidationError(f"duplicate subgoal ID: {goal.goal_id}")
            combined[goal.goal_id] = goal

        for goal in additions:
            visited = {goal.goal_id}
            parent = goal.parent_goal_or_constraint_id
            while parent != GOVERNING_OBJECTIVE_ID:
                if parent in visited:
                    raise ARC3ValidationError(f"cyclic subgoal parent chain at {parent}")
                visited.add(parent)
                parent_goal = combined.get(parent)
                if parent_goal is None:
                    raise ARC3ValidationError(f"subgoal {goal.goal_id} has unknown parent {parent}")
                parent = parent_goal.parent_goal_or_constraint_id

    def _validate_distinctions(
        self,
        additions: tuple[Distinction, ...],
        goal_additions: tuple[Subgoal, ...],
    ) -> None:
        known_goals = {*self._subgoals, *(item.goal_id for item in goal_additions)}
        for distinction in additions:
            if distinction.distinction_id in self._distinctions:
                raise ARC3ValidationError(f"duplicate distinction ID: {distinction.distinction_id}")
            if distinction.governing_objective_id != GOVERNING_OBJECTIVE_ID:
                raise ARC3ValidationError(
                    f"distinction {distinction.distinction_id} does not serve "
                    f"{GOVERNING_OBJECTIVE_ID}"
                )
            parent = distinction.parent_goal_or_constraint_id
            if parent != GOVERNING_OBJECTIVE_ID and parent not in known_goals:
                raise ARC3ValidationError(
                    f"distinction {distinction.distinction_id} has unknown parent {parent}"
                )

    def scan(self, command: ScanCommand) -> dict[str, JSONValue]:
        """Record a fresh no-action stage scan and open the action gate."""

        if self.phase is not WiseRunPhase.NEEDS_SCAN:
            raise EnvironmentStateError(f"scan is not allowed while phase={self.phase.value}")
        if command.observation_hash != self.current_observation_hash:
            raise ARC3ValidationError("scan refers to a stale or different observation")
        self._validate_goal_graph(command.subgoals)
        self._validate_distinctions(command.distinctions, command.subgoals)
        for goal in command.subgoals:
            self._subgoals[goal.goal_id] = goal
        for distinction in command.distinctions:
            self._distinctions[distinction.distinction_id] = distinction
        event = self.journal.append("distinction.scan", command.to_dict())
        self.phase = WiseRunPhase.READY_TO_ACT
        self._write_checkpoint()
        return {
            "phase": self.phase.value,
            "event_hash": event.event_hash,
            "observation_hash": self.current_observation_hash,
        }

    def _validate_action_context(self, command: ActCommand) -> None:
        if command.observation_hash != self.current_observation_hash:
            raise ARC3ValidationError("action refers to a stale or different observation")
        validate_action_request(self._observation, command.action)
        if command.active_goal_id != GOVERNING_OBJECTIVE_ID:
            goal = self._subgoals.get(command.active_goal_id)
            if goal is None:
                raise ARC3ValidationError(
                    f"action has unknown active goal {command.active_goal_id}"
                )
            if goal.status is not GoalStatus.ACTIVE:
                raise ARC3ValidationError(f"action goal {command.active_goal_id} is not ACTIVE")
        for distinction_id in command.distinction_ids:
            distinction = self._distinctions.get(distinction_id)
            if distinction is None:
                raise ARC3ValidationError(f"action has unknown distinction {distinction_id}")
            if distinction.relevance is DecisionRelevance.PARKED:
                raise ARC3ValidationError(f"action cannot cite parked distinction {distinction_id}")
        if command.action.name is ActionName.RESET:
            if command.rationale is not WiseRationale.MANDATORY_RESET:
                raise ARC3ValidationError("RESET requires MANDATORY_RESET rationale")
        elif command.rationale is WiseRationale.MANDATORY_RESET:
            raise ARC3ValidationError("MANDATORY_RESET rationale requires RESET")
        selected = action_to_dict(command.action)
        alternative_actions: list[dict[str, JSONValue]] = []
        for alternative in command.alternatives:
            validate_action_request(self._observation, alternative.action)
            alternative_actions.append(action_to_dict(alternative.action))
        if any(item == selected for item in alternative_actions):
            raise ARC3ValidationError("alternatives must differ from the selected action")
        if len({sha256_json(item) for item in alternative_actions}) != len(alternative_actions):
            raise ARC3ValidationError("alternatives must not contain duplicate actions")
        guard_key = self._failure_guard_key(
            observation_identity=command.observation_hash,
            belief_identity=self._belief_hash(),
            action=selected,
        )
        if guard_key in self._failed_action_guards:
            raise ARC3ValidationError(
                "refuse to repeat a GAME_OVER action under unchanged observation and beliefs"
            )

    def act(self, command: ActCommand) -> dict[str, JSONValue]:
        """Durably predict, then submit exactly one validated environment action."""

        if self.phase is not WiseRunPhase.READY_TO_ACT:
            raise EnvironmentStateError(f"action is not allowed while phase={self.phase.value}")
        elapsed = monotonic() - self._started_monotonic
        if elapsed >= self._wall_clock_seconds:
            raise EnvironmentStateError("Wise Scientist wall-clock budget is exhausted")
        if command.action.name is ActionName.RESET and self._reset_count >= self._max_resets:
            raise EnvironmentStateError("Wise Scientist reset budget is exhausted")
        if (
            command.action.name is not ActionName.RESET
            and self._environment_actions >= self._max_environment_actions
        ):
            raise EnvironmentStateError("Wise Scientist environment-action budget is exhausted")
        self._validate_action_context(command)
        before = self._observation
        before_hash = self.current_observation_hash
        before_belief_hash = self._belief_hash()
        selected_event = self.journal.append(
            "action.selected",
            {
                **command.to_dict(),
                "belief_hash": before_belief_hash,
                "action_ordinal": self._environment_actions + self._reset_count + 1,
            },
        )
        reasoning: dict[str, JSONValue] = {
            "wise_scientist_event_hash": selected_event.event_hash,
            "active_goal_id": command.active_goal_id,
            "distinction_ids": list(command.distinction_ids),
            "predicted_consequence": command.predicted_consequence,
            "rationale": command.rationale.value,
        }
        try:
            after = self._session.step(command.action, reasoning=reasoning)
        except Exception as error:
            self.phase = WiseRunPhase.FAULTED
            self.journal.append(
                "action.transport_failed",
                {
                    "selected_event_hash": selected_event.event_hash,
                    "error_type": type(error).__name__,
                    "action_application_unknown": True,
                },
            )
            self._write_checkpoint()
            raise

        if command.action.name is ActionName.RESET:
            self._reset_count += 1
        else:
            self._environment_actions += 1
        self._observation = after
        self._record_observation(source="environment-consequence")
        after_hash = self.current_observation_hash
        self._pending = _PendingConsequence(
            command=command,
            before_observation_hash=before_hash,
            after_observation_hash=after_hash,
            before_levels_completed=before.levels_completed,
            before_belief_hash=before_belief_hash,
        )
        self.phase = WiseRunPhase.AWAITING_ASSESSMENT
        self.journal.append(
            "action.consequence",
            {
                "selected_event_hash": selected_event.event_hash,
                "before_observation_hash": before_hash,
                "after_observation_hash": after_hash,
                "returned_state": after.state.value,
                "levels_completed": after.levels_completed,
                "win_levels": after.win_levels,
            },
        )
        self._write_checkpoint()
        return self.status()

    def _apply_assessment(self, command: AssessCommand) -> None:
        revision_ids = tuple(item.distinction_id for item in command.distinction_revisions)
        goal_ids = tuple(item.goal_id for item in command.goal_updates)
        if len(set(revision_ids)) != len(revision_ids):
            raise ARC3ValidationError("assessment revises a distinction more than once")
        if len(set(goal_ids)) != len(goal_ids):
            raise ARC3ValidationError("assessment updates a subgoal more than once")
        if set(revision_ids) & set(command.preserved_distinction_ids):
            raise ARC3ValidationError(
                "a distinction cannot be both preserved and revised in one assessment"
            )
        for distinction_id in (*revision_ids, *command.preserved_distinction_ids):
            if distinction_id not in self._distinctions:
                raise ARC3ValidationError(
                    f"assessment refers to unknown distinction {distinction_id}"
                )
        for update in command.goal_updates:
            if update.goal_id not in self._subgoals:
                raise ARC3ValidationError(f"assessment refers to unknown subgoal {update.goal_id}")
        self._validate_goal_graph(command.new_subgoals)
        self._validate_distinctions(command.new_distinctions, command.new_subgoals)

        for revision in command.distinction_revisions:
            current = self._distinctions[revision.distinction_id]
            relevance = current.relevance
            if revision.kind is RevisionKind.PARK or revision.kind is RevisionKind.REJECT:
                relevance = DecisionRelevance.PARKED
            elif revision.kind is RevisionKind.REOPEN:
                relevance = DecisionRelevance.ACTIVE
            self._distinctions[revision.distinction_id] = replace(current, relevance=relevance)
        goal_status = {
            SubgoalUpdateKind.SUCCEED: GoalStatus.SUCCEEDED,
            SubgoalUpdateKind.ABANDON: GoalStatus.ABANDONED,
            SubgoalUpdateKind.PARK: GoalStatus.PARKED,
            SubgoalUpdateKind.REOPEN: GoalStatus.ACTIVE,
        }
        for update in command.goal_updates:
            current_goal = self._subgoals[update.goal_id]
            self._subgoals[update.goal_id] = replace(current_goal, status=goal_status[update.kind])
        for goal in command.new_subgoals:
            self._subgoals[goal.goal_id] = goal
        for distinction in command.new_distinctions:
            self._distinctions[distinction.distinction_id] = distinction

    def assess(self, command: AssessCommand) -> dict[str, JSONValue]:
        """Record the residual and reopen only the smallest implicated state."""

        if self.phase is not WiseRunPhase.AWAITING_ASSESSMENT or self._pending is None:
            raise EnvironmentStateError(f"assessment is not allowed while phase={self.phase.value}")
        if command.observation_hash != self.current_observation_hash:
            raise ARC3ValidationError("assessment refers to a stale or different observation")
        self._apply_assessment(command)
        pending = self._pending
        assessment_event = self.journal.append(
            "consequence.assessed",
            {
                **command.to_dict(),
                "before_observation_hash": pending.before_observation_hash,
                "selected_action": action_to_dict(pending.command.action),
                "predicted_consequence": pending.command.predicted_consequence,
                "returned_state": self._observation.state.value,
            },
        )
        if self._observation.state is GameStateName.GAME_OVER:
            self._failed_action_guards.add(
                self._failure_guard_key(
                    observation_identity=pending.before_observation_hash,
                    belief_identity=pending.before_belief_hash,
                    action=action_to_dict(pending.command.action),
                )
            )
            self.journal.append(
                "failure.game_over",
                {
                    "assessment_event_hash": assessment_event.event_hash,
                    "failed_action": action_to_dict(pending.command.action),
                    "failed_observation_hash": pending.before_observation_hash,
                    "failed_belief_hash": pending.before_belief_hash,
                    "win_observed": False,
                },
            )
        self._pending = None

        if self._observation.state is GameStateName.WIN:
            self.phase = WiseRunPhase.COMPLETE
            self._write_final_receipt(assessment_event_hash=assessment_event.event_hash)
        elif (
            pending.command.action.name is ActionName.RESET
            or self._observation.levels_completed > pending.before_levels_completed
        ):
            self._park_live_stage_state(reason="substantially-new-stage")
            self.phase = WiseRunPhase.NEEDS_SCAN
        else:
            self.phase = WiseRunPhase.READY_TO_ACT
        self._write_checkpoint()
        return self.status()

    def _park_live_stage_state(self, *, reason: str) -> None:
        parked_distinctions: list[JSONValue] = []
        parked_goals: list[JSONValue] = []
        for distinction_id, distinction in tuple(self._distinctions.items()):
            if distinction.relevance is DecisionRelevance.ACTIVE:
                self._distinctions[distinction_id] = replace(
                    distinction, relevance=DecisionRelevance.PARKED
                )
                parked_distinctions.append(distinction_id)
        for goal_id, goal in tuple(self._subgoals.items()):
            if goal.status is GoalStatus.ACTIVE:
                self._subgoals[goal_id] = replace(goal, status=GoalStatus.PARKED)
                parked_goals.append(goal_id)
        self.journal.append(
            "stage.attention_closed",
            {
                "reason": reason,
                "observation_hash": self.current_observation_hash,
                "parked_distinction_ids": parked_distinctions,
                "parked_goal_ids": parked_goals,
                "completion_claimed": False,
            },
        )

    def _complete_without_action(self) -> None:
        self.phase = WiseRunPhase.COMPLETE
        event = self.journal.append(
            "run.initial_win_observed",
            {
                "observation_hash": self.current_observation_hash,
                "state": self._observation.state.value,
            },
        )
        self._write_final_receipt(assessment_event_hash=event.event_hash)

    def _write_final_receipt(self, *, assessment_event_hash: str) -> None:
        if self._observation.state is not GameStateName.WIN:
            raise EnvironmentStateError("a success receipt requires direct observed WIN")
        try:
            scorecard = self._session.close()
            close_error: str | None = None
        except Exception as error:
            scorecard = None
            close_error = type(error).__name__
            self.journal.append(
                "scorecard.close_failed",
                {"error_type": close_error, "win_observed": True},
            )
        elapsed = monotonic() - self._started_monotonic
        receipt_core: dict[str, JSONValue] = {
            "schema": _FINAL_RECEIPT_SCHEMA,
            "game_id": str(self._observation.game_id),
            "final_official_state": self._observation.state.value,
            "levels_completed": self._observation.levels_completed,
            "win_levels": self._observation.win_levels,
            "environment_action_count": self._environment_actions,
            "reset_count": self._reset_count,
            "budgets": {
                "max_environment_actions": self._max_environment_actions,
                "max_resets": self._max_resets,
                "wall_clock_seconds": self._wall_clock_seconds,
            },
            "started_at": self._started_at,
            "elapsed_seconds": elapsed,
            "journal_path": "events.jsonl",
            "journal_tail_hash_before_completion": self.journal.tail_hash,
            "assessment_event_hash": assessment_event_hash,
            "win_observed": True,
            "scorecard": _scorecard_payload(scorecard),
            "scorecard_close_error": close_error,
            "parked_distinction_ids": [
                item.distinction_id
                for item in self.distinctions
                if item.relevance is DecisionRelevance.PARKED
            ],
        }
        receipt_hash = sha256_json(receipt_core)
        receipt = {**receipt_core, "receipt_hash": receipt_hash}
        atomic_write_json(self.artifact_root / "final-receipt.json", receipt)
        completion_event = self.journal.append(
            "run.completed",
            {
                "final_receipt_path": "final-receipt.json",
                "final_receipt_hash": receipt_hash,
                "final_official_state": GameStateName.WIN.value,
                "win_observed": True,
            },
        )
        atomic_write_json(
            self.artifact_root / "final-journal-receipt.json",
            {
                "journal_path": "events.jsonl",
                "journal_tail_hash": completion_event.event_hash,
                "event_count": len(self.journal.events),
            },
        )

    def status(self) -> dict[str, JSONValue]:
        """Return a bounded observable status suitable for an interactive driver."""

        return {
            "phase": self.phase.value,
            "game_id": str(self._observation.game_id),
            "governing_objective_id": GOVERNING_OBJECTIVE_ID,
            "observation_hash": self.current_observation_hash,
            "state": self._observation.state.value,
            "levels_completed": self._observation.levels_completed,
            "win_levels": self._observation.win_levels,
            "available_actions": [item.value for item in self._observation.available_actions],
            "environment_action_count": self._environment_actions,
            "reset_count": self._reset_count,
            "max_environment_actions": self._max_environment_actions,
            "max_resets": self._max_resets,
            "wall_clock_seconds": self._wall_clock_seconds,
            "frame_text": [
                render_grid_text(frame, spaced=True) for frame in self._observation.frames
            ],
            "frame_digests": [str(frame.digest) for frame in self._observation.frames],
            "active_distinction_ids": [
                item.distinction_id
                for item in self.distinctions
                if item.relevance is DecisionRelevance.ACTIVE
            ],
            "active_goal_ids": [
                item.goal_id for item in self.subgoals if item.status is GoalStatus.ACTIVE
            ],
            "journal_tail_hash": self.journal.tail_hash,
        }

    def _write_checkpoint(self) -> None:
        failed_action_guards: list[JSONValue] = [
            item for item in sorted(self._failed_action_guards)
        ]
        payload: dict[str, JSONValue] = {
            "schema": _CHECKPOINT_SCHEMA,
            "phase": self.phase.value,
            "game_id": str(self._observation.game_id),
            "governing_objective_id": GOVERNING_OBJECTIVE_ID,
            "current_observation_hash": self.current_observation_hash,
            "current_official_state": self._observation.state.value,
            "levels_completed": self._observation.levels_completed,
            "win_levels": self._observation.win_levels,
            "environment_action_count": self._environment_actions,
            "reset_count": self._reset_count,
            "observation_count": self._observation_index,
            "distinctions": [item.to_dict() for item in self.distinctions],
            "subgoals": [item.to_dict() for item in self.subgoals],
            "failed_action_guards": failed_action_guards,
            "pending": self._pending.to_dict() if self._pending is not None else None,
            "journal_tail_hash": self.journal.tail_hash,
            "journal_event_count": len(self.journal.events),
        }
        atomic_write_json(self.artifact_root / "checkpoint.json", payload)


__all__ = [
    "GOVERNING_OBJECTIVE",
    "GOVERNING_OBJECTIVE_ID",
    "WiseRunPhase",
    "WiseScientistRun",
    "observation_hash",
    "observation_payload",
]
