from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

import pytest

from arc3.adapters import EnvironmentSession, GridFrame, Observation, ScoreSummary
from arc3.errors import ARC3ValidationError, EnvironmentStateError
from arc3.types import ActionName, ActionRequest, GameId, GameStateName, JSONValue
from arc3.wise_scientist import (
    ActCommand,
    AssessCommand,
    ScanCommand,
    WiseJournal,
    WiseRunPhase,
    WiseScientistRun,
)

_SOURCE_COMMIT = "1" * 40
_AUTHORIZATION_HASH = "sha256:" + ("2" * 64)


def _observation(
    state: GameStateName,
    *,
    levels_completed: int = 0,
    cell: int = 1,
    full_reset: bool = False,
) -> Observation:
    available = (
        ()
        if state in {GameStateName.WIN, GameStateName.GAME_OVER}
        else (ActionName.ACTION1, ActionName.ACTION2)
    )
    return Observation(
        game_id=GameId("public-development-test"),
        frames=(GridFrame.from_rows(((0, cell), (cell, 0))),),
        state=state,
        levels_completed=levels_completed,
        win_levels=2,
        available_actions=available,
        full_reset=full_reset,
    )


class _FakeSession(EnvironmentSession):
    def __init__(self, initial: Observation, consequences: list[Observation]) -> None:
        self._observation = initial
        self._consequences = consequences
        self.actions: list[ActionRequest] = []
        self.reasoning: list[Mapping[str, JSONValue] | None] = []
        self.closed = False

    @property
    def observation(self) -> Observation:
        return self._observation

    def step(
        self,
        action: ActionRequest,
        *,
        reasoning: Mapping[str, JSONValue] | None = None,
    ) -> Observation:
        self.actions.append(action)
        self.reasoning.append(reasoning)
        self._observation = self._consequences.pop(0)
        return self._observation

    def reset(self) -> Observation:
        return self.step(ActionRequest(ActionName.RESET))

    def scorecard(self) -> ScoreSummary | None:
        return None

    def close(self) -> ScoreSummary | None:
        self.closed = True
        return None


def _scan(run: WiseScientistRun, suffix: str) -> ScanCommand:
    return ScanCommand.from_dict(
        {
            "observation_hash": run.current_observation_hash,
            "stage_summary": f"Fresh no-action scan for stage {suffix}.",
            "distinctions": [
                {
                    "distinction_id": f"D-{suffix}",
                    "statement": "The control may progress or leave access unchanged.",
                    "predictions": [
                        {
                            "prediction_id": f"P-{suffix}-PROGRESS",
                            "consequence": "progress marker changes",
                            "discriminator": "observe marker and level count",
                        },
                        {
                            "prediction_id": f"P-{suffix}-NOOP",
                            "consequence": "no progress marker changes",
                            "discriminator": "observe unchanged marker and level count",
                        },
                    ],
                    "decision_that_could_change": "whether to repeat this route",
                    "parent_goal_or_constraint_id": f"G-{suffix}",
                    "governing_objective_id": "OBJ-WIN",
                    "relevance": "ACTIVE",
                    "reopening_condition": "the retained route stops making progress",
                }
            ],
            "subgoals": [
                {
                    "goal_id": f"G-{suffix}",
                    "parent_goal_or_constraint_id": "OBJ-WIN",
                    "motivation": "A route-control uncertainty blocks progress.",
                    "decision_that_could_change": "which control to apply next",
                    "smallest_test_or_plan": "apply one route control",
                    "success_condition": "official progress changes",
                    "abandonment_condition": "the route is disproved",
                    "reopening_condition": "progress is blocked again",
                    "status": "ACTIVE",
                }
            ],
        }
    )


def _act(
    run: WiseScientistRun,
    suffix: str,
    action: str = "ACTION1",
) -> ActCommand:
    alternative = "ACTION2" if action == "ACTION1" else "ACTION1"
    return ActCommand.from_dict(
        {
            "observation_hash": run.current_observation_hash,
            "action": {"name": action, "coordinate": None},
            "active_goal_id": f"G-{suffix}",
            "distinction_ids": [f"D-{suffix}"],
            "predicted_consequence": "official progress changes",
            "alternatives": [
                {
                    "action": {"name": alternative, "coordinate": None},
                    "summary": "less supported route control",
                }
            ],
            "rationale": "DISCRIMINATE_LIVE_HYPOTHESES",
            "rationale_summary": "Smallest progress-relevant discriminating action.",
        }
    )


def _assess(
    run: WiseScientistRun,
    suffix: str,
    *,
    kind: str = "MATCHED",
    revision: str = "SUPPORT",
) -> AssessCommand:
    return AssessCommand.from_dict(
        {
            "observation_hash": run.current_observation_hash,
            "assessment": kind,
            "residual": "No unexplained decision-relevant residual remains.",
            "preserved_distinction_ids": [],
            "distinction_revisions": [
                {
                    "distinction_id": f"D-{suffix}",
                    "kind": revision,
                    "summary": "Update only the implicated route distinction.",
                }
            ],
            "goal_updates": [],
            "new_distinctions": [],
            "new_subgoals": [],
        }
    )


def test_level_transition_is_not_completion_and_direct_win_is(tmp_path: Path) -> None:
    session = _FakeSession(
        _observation(GameStateName.NOT_FINISHED),
        [
            _observation(GameStateName.NOT_FINISHED, levels_completed=1, cell=2),
            _observation(GameStateName.WIN, levels_completed=2, cell=3),
        ],
    )
    run = WiseScientistRun(
        session,
        tmp_path / "run",
        source_commit=_SOURCE_COMMIT,
        authorization_hash=_AUTHORIZATION_HASH,
    )

    run.scan(_scan(run, "L0"))
    run.act(_act(run, "L0"))
    assert run.phase is WiseRunPhase.AWAITING_ASSESSMENT
    with pytest.raises(EnvironmentStateError, match="action is not allowed"):
        run.act(_act(run, "L0"))
    run.assess(_assess(run, "L0"))

    assert run.status()["phase"] == WiseRunPhase.NEEDS_SCAN.value
    assert not (tmp_path / "run" / "final-receipt.json").exists()
    assert run.observation.state is GameStateName.NOT_FINISHED

    run.scan(_scan(run, "L1"))
    run.act(_act(run, "L1", action="ACTION2"))
    run.assess(_assess(run, "L1"))

    assert run.status()["phase"] == WiseRunPhase.COMPLETE.value
    assert session.closed is True
    receipt = json.loads((tmp_path / "run" / "final-receipt.json").read_text())
    assert receipt["final_official_state"] == "WIN"
    assert receipt["win_observed"] is True
    assert receipt["levels_completed"] == 2
    assert receipt["environment_action_count"] == 2
    events = WiseJournal.verify(tmp_path / "run" / "events.jsonl")
    assert events[-1].event_type == "run.completed"
    assert sum(item.event_type == "run.completed" for item in events) == 1


def test_game_over_is_failure_evidence_then_reset_requires_fresh_scan(
    tmp_path: Path,
) -> None:
    session = _FakeSession(
        _observation(GameStateName.NOT_FINISHED),
        [
            _observation(GameStateName.GAME_OVER, cell=4),
            _observation(GameStateName.NOT_FINISHED, cell=1, full_reset=True),
        ],
    )
    run = WiseScientistRun(
        session,
        tmp_path / "run",
        source_commit=_SOURCE_COMMIT,
        authorization_hash=_AUTHORIZATION_HASH,
    )
    run.scan(_scan(run, "TRY"))
    run.act(_act(run, "TRY"))
    run.assess(_assess(run, "TRY", kind="MISMATCHED", revision="NARROW"))

    assert run.phase is WiseRunPhase.READY_TO_ACT
    assert run.observation.state is GameStateName.GAME_OVER
    assert not (tmp_path / "run" / "final-receipt.json").exists()
    with pytest.raises(ARC3ValidationError, match="RESET requires"):
        run.act(
            ActCommand.from_dict(
                {
                    "observation_hash": run.current_observation_hash,
                    "action": {"name": "RESET", "coordinate": None},
                    "active_goal_id": "OBJ-WIN",
                    "distinction_ids": [],
                    "predicted_consequence": "official restart",
                    "alternatives": [
                        {
                            "action": {"name": "ACTION1", "coordinate": None},
                            "summary": "illegal while GAME_OVER",
                        }
                    ],
                    "rationale": "FOLLOW_SUPPORTED_ROUTE",
                    "rationale_summary": "wrong rationale for test",
                }
            )
        )

    reset = ActCommand.from_dict(
        {
            "observation_hash": run.current_observation_hash,
            "action": {"name": "RESET", "coordinate": None},
            "active_goal_id": "OBJ-WIN",
            "distinction_ids": [],
            "predicted_consequence": "the official environment restarts",
            "alternatives": [],
            "rationale": "MANDATORY_RESET",
            "rationale_summary": "RESET is the only officially legal recovery action.",
        }
    )
    run.act(reset)
    run.assess(
        AssessCommand.from_dict(
            {
                "observation_hash": run.current_observation_hash,
                "assessment": "MATCHED",
                "residual": "The official reset returned a playable observation.",
                "preserved_distinction_ids": ["D-TRY"],
                "distinction_revisions": [],
                "goal_updates": [],
                "new_distinctions": [],
                "new_subgoals": [],
            }
        )
    )

    assert run.status()["phase"] == WiseRunPhase.NEEDS_SCAN.value
    assert run.environment_action_count == 1
    assert run.reset_count == 1
    event_types = [
        item.event_type for item in WiseJournal.verify(tmp_path / "run" / "events.jsonl")
    ]
    assert "failure.game_over" in event_types
    assert "run.completed" not in event_types


def test_orphan_subgoal_and_wrong_objective_are_rejected(tmp_path: Path) -> None:
    run = WiseScientistRun(
        _FakeSession(_observation(GameStateName.NOT_FINISHED), []),
        tmp_path / "run",
        source_commit=_SOURCE_COMMIT,
        authorization_hash=_AUTHORIZATION_HASH,
    )
    raw = _scan(run, "ORPHAN").to_dict()
    subgoals = raw["subgoals"]
    assert isinstance(subgoals, list)
    assert isinstance(subgoals[0], dict)
    subgoals[0]["parent_goal_or_constraint_id"] = "UNKNOWN-PARENT"

    with pytest.raises(ARC3ValidationError, match="unknown parent"):
        run.scan(ScanCommand.from_dict(raw))
