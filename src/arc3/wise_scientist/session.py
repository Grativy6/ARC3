"""Strict action/assessment gate for one Wise Scientist environment run.

This module does not choose actions.  It makes a concise scientific decision
record mandatory before an official adapter call, preserves every consequence,
and refuses to equate a level transition with completion.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum
from math import isfinite
from pathlib import Path
from time import monotonic, sleep
from typing import cast

from arc3.adapters import EnvironmentSession, Observation, ScoreSummary, validate_action_request
from arc3.errors import ARC3ValidationError, EnvironmentStateError
from arc3.evaluation.artifacts import atomic_write_json, atomic_write_text
from arc3.perception import render_grid_svg, render_grid_text
from arc3.trace.canonical import is_sha256, normalize_json, sha256_json
from arc3.types import ActionName, GameStateName, JSONValue
from arc3.wise_scientist.journal import WiseEvent, WiseJournal
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
_CHECKPOINT_SCHEMA_V1 = "arc3.wise-scientist.checkpoint.v0.1"
_CHECKPOINT_SCHEMA = "arc3.wise-scientist.checkpoint.v0.2"
_FINAL_RECEIPT_SCHEMA = "arc3.wise-scientist.final-receipt.v0.2"
_CHECKPOINT_WRITE_ATTEMPTS = 8
WALL_CLOCK_EXTENSION_REASON_MAX_CHARACTERS = 500
ENVIRONMENT_ACTION_EXTENSION_REASON_MAX_CHARACTERS = 500


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
        source_commit: str,
        authorization_hash: str,
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
        if len(source_commit) != 40 or any(
            character not in "0123456789abcdef" for character in source_commit
        ):
            raise ARC3ValidationError("Wise Scientist source commit must be a lowercase SHA-1")
        if not is_sha256(authorization_hash):
            raise ARC3ValidationError("Wise Scientist authorization hash must be a tagged SHA-256")
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
        self._official_environment_actions = 0
        self._official_reset_count = 0
        self._replay_environment_actions = 0
        self._replay_reset_count = 0
        initial_session_id = self._observation.upstream_session_id
        self._official_session_ids = (initial_session_id,) if initial_session_id is not None else ()
        self._max_environment_actions = max_environment_actions
        self._max_resets = max_resets
        self._wall_clock_seconds = wall_clock_seconds
        self._source_commit = source_commit
        self._authorization_hash = authorization_hash
        self._started_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        self._started_monotonic = monotonic()
        self.phase = WiseRunPhase.NEEDS_SCAN

        self.journal.append(
            "run.started",
            {
                "game_id": str(self._observation.game_id),
                "governing_objective_id": GOVERNING_OBJECTIVE_ID,
                "governing_objective": GOVERNING_OBJECTIVE,
                "source_commit": self._source_commit,
                "authorization_hash": self._authorization_hash,
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

    @classmethod
    def resume(
        cls,
        session: EnvironmentSession,
        artifact_root: str | Path,
        *,
        recovery_source_commit: str,
        authorization_hash: str,
        max_environment_actions: int = 1_000,
        max_resets: int = 20,
        wall_clock_seconds: float = 14_400.0,
        allow_environment_action_extension: bool = False,
        environment_action_extension_reason: str | None = None,
        allow_wall_clock_extension: bool = False,
        wall_clock_extension_reason: str | None = None,
    ) -> WiseScientistRun:
        """Resume a local official run by verified deterministic action replay.

        The local SDK does not expose a serializable environment state.  Recovery
        therefore opens a fresh same-seed session, replays the already-journaled
        actions without creating duplicate logical action events, and compares
        every returned consequence with the immutable stored observation modulo
        the new session's upstream identity.  Only a current checkpoint or the
        exact suffix produced when a checkpoint write fails after an action is
        accepted.
        """

        root = Path(artifact_root).resolve()
        checkpoint_path = root / "checkpoint.json"
        journal = WiseJournal(root / "events.jsonl")
        if not journal.events:
            raise ARC3ValidationError("resume requires an existing Wise Scientist journal")
        checkpoint = cls._load_resume_checkpoint(checkpoint_path)
        environment_action_budget_extension, wall_clock_budget_extension = (
            cls._validate_resume_identity(
                checkpoint,
                journal=journal,
                session=session,
                recovery_source_commit=recovery_source_commit,
                authorization_hash=authorization_hash,
                max_environment_actions=max_environment_actions,
                max_resets=max_resets,
                wall_clock_seconds=wall_clock_seconds,
                allow_environment_action_extension=allow_environment_action_extension,
                environment_action_extension_reason=environment_action_extension_reason,
                allow_wall_clock_extension=allow_wall_clock_extension,
                wall_clock_extension_reason=wall_clock_extension_reason,
            )
        )
        checkpoint_event_count = cast(int, checkpoint["journal_event_count"])
        suffix = journal.events[checkpoint_event_count:]
        suffix_types = tuple(item.event_type for item in suffix)
        action_suffix = (
            suffix[:3]
            if suffix_types[:3]
            == (
                "action.selected",
                "observation.recorded",
                "action.consequence",
            )
            else ()
        )
        trailing_suffix = suffix[len(action_suffix) :]
        if suffix and any(item.event_type != "run.resumed" for item in trailing_suffix):
            raise ARC3ValidationError(
                "resume refuses an unsupported journal suffix after the last checkpoint"
            )

        replay_steps = cls._replay_steps(root, journal)
        recovery_journal = WiseJournal(root / "recovery-events.jsonl")
        prior_recovery_session_ids = cls._recovery_session_ids(recovery_journal)
        new_session_id = session.observation.upstream_session_id
        recovery_started = recovery_journal.append(
            "recovery.started",
            {
                "recovery_source_commit": recovery_source_commit,
                "new_official_session_id": new_session_id,
                "expected_replay_environment_actions": sum(
                    command.action.name is not ActionName.RESET for _, command, _ in replay_steps
                ),
                "expected_replay_resets": sum(
                    command.action.name is ActionName.RESET for _, command, _ in replay_steps
                ),
                "observation_equivalence_rule": (
                    "exact normalized observation payload after excluding only "
                    "upstream_session_id and upstream_metadata"
                ),
            },
        )
        try:
            cls._verify_replay_observation(
                session.observation,
                root=root,
                observation_path=cls._initial_observation_path(journal),
            )
        except ARC3ValidationError:
            recovery_journal.append(
                "recovery.initial_divergence",
                {
                    "recovery_started_event_hash": recovery_started.event_hash,
                    "new_official_session_id": new_session_id,
                    "official_environment_actions_executed": 0,
                    "official_resets_executed": 0,
                },
            )
            raise
        replayed_actions = 0
        replayed_resets = 0
        for replay_ordinal, (selected_event, command, observation_path) in enumerate(
            replay_steps, start=1
        ):
            reasoning: dict[str, JSONValue] = {
                "wise_scientist_event_hash": selected_event.event_hash,
                "active_goal_id": command.active_goal_id,
                "distinction_ids": list(command.distinction_ids),
                "predicted_consequence": command.predicted_consequence,
                "rationale": command.rationale.value,
            }
            try:
                returned = session.step(command.action, reasoning=reasoning)
            except Exception as error:
                recovery_journal.append(
                    "recovery.transport_failed",
                    {
                        "recovery_started_event_hash": recovery_started.event_hash,
                        "replay_ordinal": replay_ordinal,
                        "selected_event_hash": selected_event.event_hash,
                        "action": action_to_dict(command.action),
                        "error_type": type(error).__name__,
                        "action_application_unknown": True,
                    },
                )
                raise
            replay_error: ARC3ValidationError | None = None
            try:
                cls._verify_replay_observation(
                    returned,
                    root=root,
                    observation_path=observation_path,
                )
            except ARC3ValidationError as error:
                replay_error = error
            recovery_journal.append(
                "recovery.replay_action",
                {
                    "recovery_started_event_hash": recovery_started.event_hash,
                    "replay_ordinal": replay_ordinal,
                    "selected_event_hash": selected_event.event_hash,
                    "action": action_to_dict(command.action),
                    "stored_observation_path": observation_path,
                    "returned_observation_hash": observation_hash(returned),
                    "semantically_equivalent": replay_error is None,
                },
            )
            if command.action.name is ActionName.RESET:
                replayed_resets += 1
            else:
                replayed_actions += 1
            if replay_error is not None:
                recovery_journal.append(
                    "recovery.diverged",
                    {
                        "recovery_started_event_hash": recovery_started.event_hash,
                        "replay_ordinal": replay_ordinal,
                        "official_environment_actions_executed": replayed_actions,
                        "official_resets_executed": replayed_resets,
                    },
                )
                raise replay_error
        recovery_verified = recovery_journal.append(
            "recovery.verified",
            {
                "recovery_started_event_hash": recovery_started.event_hash,
                "official_environment_actions_executed": replayed_actions,
                "official_resets_executed": replayed_resets,
                "semantic_replay_verified": True,
            },
        )

        run = cls.__new__(cls)
        run._session = session
        run.artifact_root = root
        run.journal = journal
        run._observation = session.observation
        run._distinctions = {
            item.distinction_id: item
            for item in (
                Distinction.from_dict(value, field="checkpoint.distinctions[]")
                for value in cast(list[object], checkpoint["distinctions"])
            )
        }
        run._subgoals = {
            item.goal_id: item
            for item in (
                Subgoal.from_dict(value, field="checkpoint.subgoals[]")
                for value in cast(list[object], checkpoint["subgoals"])
            )
        }
        run._failed_action_guards = set(cast(list[str], checkpoint["failed_action_guards"]))
        run._environment_actions = cast(
            int,
            checkpoint.get("unique_logical_action_count", checkpoint["environment_action_count"]),
        )
        run._reset_count = cast(
            int, checkpoint.get("unique_logical_reset_count", checkpoint["reset_count"])
        )
        run._observation_index = cast(int, checkpoint["observation_count"])
        run._pending = cls._pending_from_checkpoint(checkpoint.get("pending"))
        run.phase = WiseRunPhase(cast(str, checkpoint["phase"]))

        previous_source_commit = cast(str, checkpoint["source_commit"])
        previous_observation_hash = cast(str, checkpoint["current_observation_hash"])
        if action_suffix:
            selected, recorded, consequence = action_suffix
            selected_payload = selected.payload
            consequence_payload = consequence.payload
            command = ActCommand.from_dict(selected_payload)
            if (
                recorded.payload.get("observation_hash")
                != consequence_payload.get("after_observation_hash")
                or consequence_payload.get("selected_event_hash") != selected.event_hash
                or consequence_payload.get("before_observation_hash") != previous_observation_hash
            ):
                raise ARC3ValidationError("resume journal suffix has inconsistent action links")
            belief_hash = selected_payload.get("belief_hash")
            if not isinstance(belief_hash, str) or not is_sha256(belief_hash):
                raise ARC3ValidationError("resume action suffix has invalid belief hash")
            run._pending = _PendingConsequence(
                command=command,
                before_observation_hash=previous_observation_hash,
                after_observation_hash=cast(str, consequence_payload["after_observation_hash"]),
                before_levels_completed=cast(int, checkpoint["levels_completed"]),
                before_belief_hash=belief_hash,
            )
            if command.action.name is ActionName.RESET:
                run._reset_count += 1
            else:
                run._environment_actions += 1
            run._observation_index += 1
            run.phase = WiseRunPhase.AWAITING_ASSESSMENT

        if run._environment_actions != replayed_actions or run._reset_count != replayed_resets:
            raise ARC3ValidationError(
                "resume replay counts do not match the recovered logical action counts"
            )
        if run.phase is WiseRunPhase.AWAITING_ASSESSMENT and run._pending is None:
            raise ARC3ValidationError("resume checkpoint is missing its pending consequence")
        if run.phase is not WiseRunPhase.AWAITING_ASSESSMENT and run._pending is not None:
            raise ARC3ValidationError("resume checkpoint has a consequence in the wrong phase")

        total_replay_actions, total_replay_resets = cls._recovery_action_totals(recovery_journal)
        official_before_recovery = (
            run._environment_actions + total_replay_actions - replayed_actions
        )
        official_resets_before_recovery = run._reset_count + total_replay_resets - replayed_resets
        run._official_environment_actions = run._environment_actions + total_replay_actions
        run._official_reset_count = run._reset_count + total_replay_resets
        run._replay_environment_actions = total_replay_actions
        run._replay_reset_count = total_replay_resets
        prior_session_ids = tuple(
            dict.fromkeys((*cls._stored_session_ids(root, journal), *prior_recovery_session_ids))
        )
        run._official_session_ids = tuple(
            dict.fromkeys(
                (*prior_session_ids, *((new_session_id,) if new_session_id is not None else ()))
            )
        )

        run._max_environment_actions = max_environment_actions
        run._max_resets = max_resets
        run._wall_clock_seconds = wall_clock_seconds
        run._source_commit = recovery_source_commit
        run._authorization_hash = authorization_hash
        started_at = cls._run_started_at(journal)
        run._started_at = started_at
        started = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
        elapsed = max(0.0, (datetime.now(UTC) - started).total_seconds())
        run._started_monotonic = monotonic() - elapsed

        replayed_observation_hash = run.current_observation_hash
        run.journal.append(
            "run.resumed",
            {
                "recovery_kind": "verified-deterministic-local-replay",
                "previous_source_commit": previous_source_commit,
                "recovery_source_commit": recovery_source_commit,
                "checkpoint_event_count": checkpoint_event_count,
                "checkpoint_suffix_event_types": [item.event_type for item in suffix],
                "new_official_session_id": new_session_id,
                "prior_official_session_ids": list(prior_session_ids),
                "replayed_environment_actions_this_recovery": replayed_actions,
                "replayed_resets_this_recovery": replayed_resets,
                "replay_environment_action_count": run._replay_environment_actions,
                "replay_reset_count": run._replay_reset_count,
                "official_environment_actions_before_recovery": official_before_recovery,
                "official_resets_before_recovery": official_resets_before_recovery,
                "official_environment_action_count": run._official_environment_actions,
                "official_reset_count": run._official_reset_count,
                "unique_logical_action_count": run._environment_actions,
                "unique_logical_reset_count": run._reset_count,
                "official_replay_actions_executed": replayed_actions > 0,
                "logical_actions_duplicated": False,
                "previous_observation_hash": previous_observation_hash,
                "replayed_observation_hash": replayed_observation_hash,
                "semantic_replay_verified": True,
                "recovery_ledger_path": "recovery-events.jsonl",
                "recovery_ledger_tail_hash": recovery_verified.event_hash,
                "environment_action_budget_extension": environment_action_budget_extension,
                "wall_clock_budget_extension": wall_clock_budget_extension,
                "observation_equivalence_rule": (
                    "exact normalized observation payload after excluding only "
                    "upstream_session_id and upstream_metadata"
                ),
            },
        )
        run._write_checkpoint()
        return run

    @staticmethod
    def _load_resume_checkpoint(path: Path) -> dict[str, JSONValue]:
        try:
            raw: object = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ARC3ValidationError(f"cannot read Wise Scientist checkpoint: {error}") from error
        normalized = normalize_json(raw)
        if not isinstance(normalized, dict):
            raise ARC3ValidationError("Wise Scientist checkpoint must be a JSON object")
        required = {
            "schema",
            "source_commit",
            "authorization_hash",
            "phase",
            "game_id",
            "governing_objective_id",
            "current_observation_hash",
            "current_official_state",
            "levels_completed",
            "win_levels",
            "environment_action_count",
            "reset_count",
            "observation_count",
            "distinctions",
            "subgoals",
            "failed_action_guards",
            "pending",
            "journal_tail_hash",
            "journal_event_count",
        }
        current_only = {
            "unique_logical_action_count",
            "unique_logical_reset_count",
            "replay_environment_action_count",
            "replay_reset_count",
            "official_session_ids",
        }
        schema = normalized.get("schema")
        expected = required if schema == _CHECKPOINT_SCHEMA_V1 else required | current_only
        if set(normalized) != expected or schema not in {
            _CHECKPOINT_SCHEMA_V1,
            _CHECKPOINT_SCHEMA,
        }:
            raise ARC3ValidationError("Wise Scientist checkpoint has invalid fields or schema")
        return normalized

    @staticmethod
    def _run_started_at(journal: WiseJournal) -> str:
        started = journal.events[0]
        value = started.payload.get("started_at") if started.event_type == "run.started" else None
        if not isinstance(value, str):
            raise ARC3ValidationError("Wise Scientist journal has no valid run.started event")
        return value

    @classmethod
    def _validate_resume_identity(
        cls,
        checkpoint: dict[str, JSONValue],
        *,
        journal: WiseJournal,
        session: EnvironmentSession,
        recovery_source_commit: str,
        authorization_hash: str,
        max_environment_actions: int,
        max_resets: int,
        wall_clock_seconds: float,
        allow_environment_action_extension: bool,
        environment_action_extension_reason: str | None,
        allow_wall_clock_extension: bool,
        wall_clock_extension_reason: str | None,
    ) -> tuple[dict[str, JSONValue] | None, dict[str, JSONValue] | None]:
        if len(recovery_source_commit) != 40 or any(
            character not in "0123456789abcdef" for character in recovery_source_commit
        ):
            raise ARC3ValidationError("recovery source commit must be a lowercase SHA-1")
        if not is_sha256(authorization_hash):
            raise ARC3ValidationError("resume authorization hash must be a tagged SHA-256")
        if checkpoint.get("authorization_hash") != authorization_hash:
            raise ARC3ValidationError("resume authorization differs from the checkpoint")
        if checkpoint.get("game_id") != str(session.observation.game_id):
            raise ARC3ValidationError("resume session game differs from the checkpoint")
        event_count = checkpoint.get("journal_event_count")
        if isinstance(event_count, bool) or not isinstance(event_count, int):
            raise ARC3ValidationError("resume checkpoint has invalid journal event count")
        if event_count <= 0 or event_count > len(journal.events):
            raise ARC3ValidationError("resume checkpoint event count is outside the journal")
        if journal.events[event_count - 1].event_hash != checkpoint.get("journal_tail_hash"):
            raise ARC3ValidationError("resume checkpoint does not identify its journal prefix")
        started = journal.events[0]
        if started.event_type != "run.started":
            raise ARC3ValidationError("resume journal does not begin with run.started")
        budgets = started.payload.get("budgets")
        if not isinstance(budgets, dict) or set(budgets) != {
            "max_environment_actions",
            "max_resets",
            "wall_clock_seconds",
        }:
            raise ARC3ValidationError("resume journal has invalid original budgets")
        original_max_actions = budgets.get("max_environment_actions")
        original_max_resets = budgets.get("max_resets")
        original_wall_clock = budgets.get("wall_clock_seconds")
        if (
            isinstance(original_max_actions, bool)
            or not isinstance(original_max_actions, int)
            or original_max_actions <= 0
            or isinstance(original_max_resets, bool)
            or not isinstance(original_max_resets, int)
            or original_max_resets <= 0
        ):
            raise ARC3ValidationError("resume journal has invalid original budgets")
        if (
            isinstance(max_environment_actions, bool)
            or not isinstance(max_environment_actions, int)
            or max_environment_actions <= 0
            or isinstance(max_resets, bool)
            or not isinstance(max_resets, int)
            or max_resets <= 0
        ):
            raise ARC3ValidationError("resume budgets must be positive")
        if (
            isinstance(wall_clock_seconds, bool)
            or not isinstance(wall_clock_seconds, (int, float))
            or not isfinite(wall_clock_seconds)
            or wall_clock_seconds <= 0
        ):
            raise ARC3ValidationError("resume wall-clock budget must be positive and finite")
        if original_max_resets != max_resets:
            raise ARC3ValidationError("resume budgets differ from the original run")
        effective_max_actions = cls._effective_environment_action_budget(
            journal,
            original_max_actions=original_max_actions,
        )
        if not isinstance(allow_environment_action_extension, bool):
            raise ARC3ValidationError("environment-action extension opt-in must be boolean")
        if not allow_environment_action_extension:
            if environment_action_extension_reason is not None:
                raise ARC3ValidationError(
                    "environment-action extension reason requires explicit extension opt-in"
                )
            if max_environment_actions != effective_max_actions:
                raise ARC3ValidationError("resume budgets differ from the original run")
            action_extension: dict[str, JSONValue] | None = None
        else:
            action_reason = cls.normalize_environment_action_extension_reason(
                environment_action_extension_reason
            )
            if max_environment_actions <= effective_max_actions:
                raise ARC3ValidationError(
                    "resume environment-action extension must monotonically increase "
                    "the effective budget"
                )
            action_extension = {
                "old_max_environment_actions": effective_max_actions,
                "new_max_environment_actions": max_environment_actions,
                "reason": action_reason,
            }
        effective_wall_clock = cls._effective_wall_clock_budget(
            journal,
            original_wall_clock=original_wall_clock,
        )
        if not isinstance(allow_wall_clock_extension, bool):
            raise ARC3ValidationError("wall-clock extension opt-in must be boolean")
        if not allow_wall_clock_extension:
            if wall_clock_extension_reason is not None:
                raise ARC3ValidationError(
                    "wall-clock extension reason requires explicit extension opt-in"
                )
            if wall_clock_seconds != effective_wall_clock:
                raise ARC3ValidationError("resume budgets differ from the original run")
            extension: dict[str, JSONValue] | None = None
        else:
            reason = cls.normalize_wall_clock_extension_reason(wall_clock_extension_reason)
            if wall_clock_seconds <= effective_wall_clock:
                raise ARC3ValidationError(
                    "resume wall-clock extension must monotonically increase the effective budget"
                )
            extension = {
                "old_wall_clock_seconds": effective_wall_clock,
                "new_wall_clock_seconds": wall_clock_seconds,
                "reason": reason,
            }
        if started.payload.get("authorization_hash") != authorization_hash:
            raise ARC3ValidationError("resume journal authorization mismatch")
        if started.payload.get("game_id") != checkpoint.get("game_id"):
            raise ARC3ValidationError("resume journal game mismatch")
        return action_extension, extension

    @staticmethod
    def normalize_environment_action_extension_reason(reason: str | None) -> str:
        """Return a bounded reason for a monotonic physical-action extension."""

        if not isinstance(reason, str):
            raise ARC3ValidationError("environment-action extension requires a nonempty reason")
        normalized = reason.strip()
        if not normalized:
            raise ARC3ValidationError("environment-action extension requires a nonempty reason")
        if len(normalized) > ENVIRONMENT_ACTION_EXTENSION_REASON_MAX_CHARACTERS:
            raise ARC3ValidationError(
                "environment-action extension reason exceeds "
                f"{ENVIRONMENT_ACTION_EXTENSION_REASON_MAX_CHARACTERS} characters"
            )
        return normalized

    @classmethod
    def _effective_environment_action_budget(
        cls,
        journal: WiseJournal,
        *,
        original_max_actions: JSONValue,
    ) -> int:
        if (
            isinstance(original_max_actions, bool)
            or not isinstance(original_max_actions, int)
            or original_max_actions <= 0
        ):
            raise ARC3ValidationError("resume journal has invalid original budgets")
        effective = original_max_actions
        for event in journal.events:
            if event.event_type != "run.resumed":
                continue
            value = event.payload.get("environment_action_budget_extension")
            if value is None:
                continue
            if not isinstance(value, dict) or set(value) != {
                "old_max_environment_actions",
                "new_max_environment_actions",
                "reason",
            }:
                raise ARC3ValidationError(
                    "resume journal has malformed environment-action extension"
                )
            old = value.get("old_max_environment_actions")
            new = value.get("new_max_environment_actions")
            reason = value.get("reason")
            if (
                isinstance(old, bool)
                or not isinstance(old, int)
                or isinstance(new, bool)
                or not isinstance(new, int)
                or old != effective
                or new <= effective
            ):
                raise ARC3ValidationError(
                    "resume journal has invalid environment-action extension chain"
                )
            cls.normalize_environment_action_extension_reason(
                reason if isinstance(reason, str) else None
            )
            effective = new
        return effective

    @staticmethod
    def normalize_wall_clock_extension_reason(reason: str | None) -> str:
        """Return a bounded nonempty reason suitable for an immutable receipt."""

        if not isinstance(reason, str):
            raise ARC3ValidationError("wall-clock extension requires a nonempty reason")
        normalized = reason.strip()
        if not normalized:
            raise ARC3ValidationError("wall-clock extension requires a nonempty reason")
        if len(normalized) > WALL_CLOCK_EXTENSION_REASON_MAX_CHARACTERS:
            raise ARC3ValidationError(
                "wall-clock extension reason exceeds "
                f"{WALL_CLOCK_EXTENSION_REASON_MAX_CHARACTERS} characters"
            )
        return normalized

    @classmethod
    def _effective_wall_clock_budget(
        cls,
        journal: WiseJournal,
        *,
        original_wall_clock: JSONValue,
    ) -> float:
        if (
            isinstance(original_wall_clock, bool)
            or not isinstance(original_wall_clock, (int, float))
            or not isfinite(original_wall_clock)
            or original_wall_clock <= 0
        ):
            raise ARC3ValidationError("resume journal has invalid original budgets")
        effective = float(original_wall_clock)
        for event in journal.events:
            if event.event_type != "run.resumed":
                continue
            value = event.payload.get("wall_clock_budget_extension")
            if value is None:
                continue
            if not isinstance(value, dict) or set(value) != {
                "old_wall_clock_seconds",
                "new_wall_clock_seconds",
                "reason",
            }:
                raise ARC3ValidationError("resume journal has malformed wall-clock extension")
            old = value.get("old_wall_clock_seconds")
            new = value.get("new_wall_clock_seconds")
            reason = value.get("reason")
            if (
                isinstance(old, bool)
                or not isinstance(old, (int, float))
                or not isfinite(old)
                or isinstance(new, bool)
                or not isinstance(new, (int, float))
                or not isfinite(new)
                or float(old) != effective
                or float(new) <= effective
            ):
                raise ARC3ValidationError("resume journal has invalid wall-clock extension chain")
            cls.normalize_wall_clock_extension_reason(reason if isinstance(reason, str) else None)
            effective = float(new)
        return effective

    @staticmethod
    def _initial_observation_path(journal: WiseJournal) -> str:
        for event in journal.events:
            if event.event_type == "observation.recorded":
                value = event.payload.get("observation_path")
                if isinstance(value, str):
                    return value
                break
        raise ARC3ValidationError("resume journal has no initial observation path")

    @classmethod
    def _stored_session_ids(cls, root: Path, journal: WiseJournal) -> tuple[str, ...]:
        path = (root / cls._initial_observation_path(journal)).resolve()
        if not path.is_relative_to(root) or path.parent != root:
            raise ARC3ValidationError("resume initial observation path escapes artifact root")
        try:
            raw: object = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ARC3ValidationError(f"cannot read initial replay observation: {error}") from error
        normalized = normalize_json(raw)
        if not isinstance(normalized, dict):
            raise ARC3ValidationError("initial replay observation must be an object")
        session_id = normalized.get("upstream_session_id")
        if session_id is None:
            return ()
        if not isinstance(session_id, str) or not session_id:
            raise ARC3ValidationError("initial replay observation has invalid session identity")
        return (session_id,)

    @staticmethod
    def _recovery_session_ids(journal: WiseJournal) -> tuple[str, ...]:
        session_ids: list[str] = []
        for event in journal.events:
            if event.event_type != "recovery.started":
                continue
            session_id = event.payload.get("new_official_session_id")
            if session_id is None:
                continue
            if not isinstance(session_id, str) or not session_id:
                raise ARC3ValidationError("recovery ledger has invalid session identity")
            session_ids.append(session_id)
        return tuple(dict.fromkeys(session_ids))

    @staticmethod
    def _recovery_action_totals(journal: WiseJournal) -> tuple[int, int]:
        environment_actions = 0
        resets = 0
        for event in journal.events:
            if event.event_type != "recovery.replay_action":
                continue
            raw_action = event.payload.get("action")
            if not isinstance(raw_action, dict):
                raise ARC3ValidationError("recovery ledger has invalid action receipt")
            name = raw_action.get("name")
            if name == ActionName.RESET.value:
                resets += 1
            elif isinstance(name, str) and name in {item.value for item in ActionName}:
                environment_actions += 1
            else:
                raise ARC3ValidationError("recovery ledger has unknown action receipt")
        return environment_actions, resets

    @classmethod
    def _replay_steps(
        cls, root: Path, journal: WiseJournal
    ) -> tuple[tuple[WiseEvent, ActCommand, str], ...]:
        del root
        pending: tuple[WiseEvent, ActCommand] | None = None
        recorded_path: str | None = None
        recorded_hash: str | None = None
        steps: list[tuple[WiseEvent, ActCommand, str]] = []
        for event in journal.events:
            if event.event_type == "action.transport_failed":
                raise ARC3ValidationError(
                    "resume refuses a journal with unknown action application"
                )
            if event.event_type == "action.selected":
                if pending is not None:
                    raise ARC3ValidationError("resume journal contains overlapping actions")
                pending = (event, ActCommand.from_dict(event.payload))
                recorded_path = None
                recorded_hash = None
            elif event.event_type == "observation.recorded" and pending is not None:
                path = event.payload.get("observation_path")
                identity = event.payload.get("observation_hash")
                if not isinstance(path, str) or not isinstance(identity, str):
                    raise ARC3ValidationError("resume journal has invalid observation record")
                recorded_path = path
                recorded_hash = identity
            elif event.event_type == "action.consequence":
                if pending is None or recorded_path is None or recorded_hash is None:
                    raise ARC3ValidationError("resume journal consequence has no selected action")
                selected, command = pending
                if (
                    event.payload.get("selected_event_hash") != selected.event_hash
                    or event.payload.get("after_observation_hash") != recorded_hash
                ):
                    raise ARC3ValidationError("resume journal action links are inconsistent")
                steps.append((selected, command, recorded_path))
                pending = None
                recorded_path = None
                recorded_hash = None
        if pending is not None:
            raise ARC3ValidationError("resume refuses an action with unknown consequence")
        return tuple(steps)

    @staticmethod
    def _replay_projection(value: object) -> dict[str, JSONValue]:
        if isinstance(value, Observation):
            payload = observation_payload(value)
        else:
            normalized = normalize_json(value)
            if not isinstance(normalized, dict):
                raise ARC3ValidationError("stored replay observation must be an object")
            payload = dict(normalized)
            payload.pop("schema", None)
            payload.pop("observation_hash", None)
        payload.pop("upstream_session_id", None)
        payload.pop("upstream_metadata", None)
        return payload

    @classmethod
    def _verify_replay_observation(
        cls, observation: Observation, *, root: Path, observation_path: str
    ) -> None:
        path = (root / observation_path).resolve()
        if not path.is_relative_to(root) or path.parent != root:
            raise ARC3ValidationError("resume observation path escapes the artifact root")
        try:
            stored: object = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ARC3ValidationError(f"cannot read replay observation: {error}") from error
        if cls._replay_projection(observation) != cls._replay_projection(stored):
            raise ARC3ValidationError(
                f"deterministic replay diverged at stored observation {observation_path}"
            )

    @staticmethod
    def _pending_from_checkpoint(value: JSONValue | None) -> _PendingConsequence | None:
        if value is None:
            return None
        if not isinstance(value, dict):
            raise ARC3ValidationError("resume checkpoint pending value must be an object")
        required = {
            "command",
            "before_observation_hash",
            "after_observation_hash",
            "before_levels_completed",
            "before_belief_hash",
        }
        if set(value) != required:
            raise ARC3ValidationError("resume checkpoint pending value has invalid fields")
        before_levels = value["before_levels_completed"]
        if isinstance(before_levels, bool) or not isinstance(before_levels, int):
            raise ARC3ValidationError("resume checkpoint pending level count is invalid")
        before_hash = value["before_observation_hash"]
        after_hash = value["after_observation_hash"]
        belief_hash = value["before_belief_hash"]
        if not all(
            isinstance(item, str) and is_sha256(item)
            for item in (before_hash, after_hash, belief_hash)
        ):
            raise ARC3ValidationError("resume checkpoint pending hashes are invalid")
        return _PendingConsequence(
            command=ActCommand.from_dict(value["command"]),
            before_observation_hash=cast(str, before_hash),
            after_observation_hash=cast(str, after_hash),
            before_levels_completed=before_levels,
            before_belief_hash=cast(str, belief_hash),
        )

    @property
    def observation(self) -> Observation:
        return self._observation

    @property
    def current_observation_hash(self) -> str:
        return observation_hash(self._observation)

    @property
    def environment_action_count(self) -> int:
        return self._official_environment_actions

    @property
    def unique_logical_action_count(self) -> int:
        return self._environment_actions

    @property
    def reset_count(self) -> int:
        return self._official_reset_count

    @property
    def unique_logical_reset_count(self) -> int:
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
        if (
            command.action.name is ActionName.RESET
            and self._official_reset_count >= self._max_resets
        ):
            raise EnvironmentStateError("Wise Scientist reset budget is exhausted")
        if (
            command.action.name is not ActionName.RESET
            and self._official_environment_actions >= self._max_environment_actions
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
            self._official_reset_count += 1
        else:
            self._environment_actions += 1
            self._official_environment_actions += 1
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
        recovery_path = self.artifact_root / "recovery-events.jsonl"
        recovery_tail_hash = (
            WiseJournal(recovery_path).tail_hash if recovery_path.is_file() else None
        )
        elapsed = monotonic() - self._started_monotonic
        receipt_core: dict[str, JSONValue] = {
            "schema": _FINAL_RECEIPT_SCHEMA,
            "source_commit": self._source_commit,
            "authorization_hash": self._authorization_hash,
            "game_id": str(self._observation.game_id),
            "final_official_state": self._observation.state.value,
            "levels_completed": self._observation.levels_completed,
            "win_levels": self._observation.win_levels,
            "environment_action_count": self._official_environment_actions,
            "reset_count": self._official_reset_count,
            "unique_logical_action_count": self._environment_actions,
            "unique_logical_reset_count": self._reset_count,
            "replay_environment_action_count": self._replay_environment_actions,
            "replay_reset_count": self._replay_reset_count,
            "official_session_ids": list(self._official_session_ids),
            "budgets": {
                "max_environment_actions": self._max_environment_actions,
                "max_resets": self._max_resets,
                "wall_clock_seconds": self._wall_clock_seconds,
            },
            "started_at": self._started_at,
            "elapsed_seconds": elapsed,
            "journal_path": "events.jsonl",
            "journal_tail_hash_before_completion": self.journal.tail_hash,
            "recovery_ledger_path": (
                "recovery-events.jsonl" if recovery_tail_hash is not None else None
            ),
            "recovery_ledger_tail_hash": recovery_tail_hash,
            "assessment_event_hash": assessment_event_hash,
            "win_observed": True,
            "current_session_scorecard": _scorecard_payload(scorecard),
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
            "environment_action_count": self._official_environment_actions,
            "reset_count": self._official_reset_count,
            "unique_logical_action_count": self._environment_actions,
            "unique_logical_reset_count": self._reset_count,
            "replay_environment_action_count": self._replay_environment_actions,
            "replay_reset_count": self._replay_reset_count,
            "official_session_ids": list(self._official_session_ids),
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
            "source_commit": self._source_commit,
            "authorization_hash": self._authorization_hash,
            "phase": self.phase.value,
            "game_id": str(self._observation.game_id),
            "governing_objective_id": GOVERNING_OBJECTIVE_ID,
            "current_observation_hash": self.current_observation_hash,
            "current_official_state": self._observation.state.value,
            "levels_completed": self._observation.levels_completed,
            "win_levels": self._observation.win_levels,
            "environment_action_count": self._official_environment_actions,
            "reset_count": self._official_reset_count,
            "unique_logical_action_count": self._environment_actions,
            "unique_logical_reset_count": self._reset_count,
            "replay_environment_action_count": self._replay_environment_actions,
            "replay_reset_count": self._replay_reset_count,
            "official_session_ids": list(self._official_session_ids),
            "observation_count": self._observation_index,
            "distinctions": [item.to_dict() for item in self.distinctions],
            "subgoals": [item.to_dict() for item in self.subgoals],
            "failed_action_guards": failed_action_guards,
            "pending": self._pending.to_dict() if self._pending is not None else None,
            "journal_tail_hash": self.journal.tail_hash,
            "journal_event_count": len(self.journal.events),
        }
        checkpoint_path = self.artifact_root / "checkpoint.json"
        for attempt in range(_CHECKPOINT_WRITE_ATTEMPTS):
            try:
                atomic_write_json(checkpoint_path, payload)
                return
            except PermissionError:
                if attempt + 1 == _CHECKPOINT_WRITE_ATTEMPTS:
                    raise
                sleep(0.05 * (2**attempt))


__all__ = [
    "GOVERNING_OBJECTIVE",
    "GOVERNING_OBJECTIVE_ID",
    "WiseRunPhase",
    "WiseScientistRun",
    "observation_hash",
    "observation_payload",
]
