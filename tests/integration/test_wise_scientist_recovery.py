from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

import pytest

from arc3.adapters import EnvironmentSession, GridFrame, Observation, ScoreSummary
from arc3.errors import ARC3ValidationError
from arc3.types import ActionName, ActionRequest, GameId, GameStateName, JSONValue
from arc3.wise_scientist import (
    ActCommand,
    AssessCommand,
    ScanCommand,
    WiseJournal,
    WiseRunPhase,
    WiseScientistRun,
    observation_hash,
)

_SOURCE_COMMIT = "1" * 40
_RECOVERY_SOURCE_COMMIT = "3" * 40
_AUTHORIZATION_HASH = "sha256:" + ("2" * 64)


def _observation(*, cell: int, upstream_session_id: str) -> Observation:
    return Observation(
        game_id=GameId("wise-recovery-test"),
        frames=(GridFrame.from_rows(((0, cell), (cell, 0))),),
        state=GameStateName.NOT_FINISHED,
        levels_completed=0,
        win_levels=2,
        available_actions=(ActionName.ACTION1, ActionName.ACTION2),
        upstream_session_id=upstream_session_id,
    )


class _DeterministicSession(EnvironmentSession):
    def __init__(
        self,
        initial: Observation,
        script: list[tuple[ActionName, Observation]],
    ) -> None:
        self._observation = initial
        self._script = list(script)
        self.actions: list[ActionRequest] = []
        self.reasoning: list[Mapping[str, JSONValue] | None] = []

    @property
    def observation(self) -> Observation:
        return self._observation

    def step(
        self,
        action: ActionRequest,
        *,
        reasoning: Mapping[str, JSONValue] | None = None,
    ) -> Observation:
        if not self._script:
            raise AssertionError("deterministic recovery session exhausted its script")
        expected_action, consequence = self._script.pop(0)
        if action.name is not expected_action:
            raise AssertionError(
                f"expected replay action {expected_action.value}, got {action.name.value}"
            )
        self.actions.append(action)
        self.reasoning.append(reasoning)
        self._observation = consequence
        return consequence

    def reset(self) -> Observation:
        return self.step(ActionRequest(ActionName.RESET))

    def scorecard(self) -> ScoreSummary | None:
        return None

    def close(self) -> ScoreSummary | None:
        return None


def _scan(run: WiseScientistRun) -> ScanCommand:
    return ScanCommand.from_dict(
        {
            "observation_hash": run.current_observation_hash,
            "stage_summary": "Fresh no-action scan for deterministic recovery.",
            "distinctions": [
                {
                    "distinction_id": "D-RECOVERY",
                    "statement": "The selected route may progress or leave access unchanged.",
                    "predictions": [
                        {
                            "prediction_id": "P-RECOVERY-PROGRESS",
                            "consequence": "the visible marker changes",
                            "discriminator": "compare the next normalized observation",
                        },
                        {
                            "prediction_id": "P-RECOVERY-NOOP",
                            "consequence": "the visible marker is unchanged",
                            "discriminator": "compare the next normalized observation",
                        },
                    ],
                    "decision_that_could_change": "which route control to apply next",
                    "parent_goal_or_constraint_id": "G-RECOVERY",
                    "governing_objective_id": "OBJ-WIN",
                    "relevance": "ACTIVE",
                    "reopening_condition": "the retained route stops making progress",
                }
            ],
            "subgoals": [
                {
                    "goal_id": "G-RECOVERY",
                    "parent_goal_or_constraint_id": "OBJ-WIN",
                    "motivation": "Route uncertainty blocks progress toward official WIN.",
                    "decision_that_could_change": "which route control to apply next",
                    "smallest_test_or_plan": "apply one route control",
                    "success_condition": "official progress changes",
                    "abandonment_condition": "the route is disproved",
                    "reopening_condition": "progress is blocked again",
                    "status": "ACTIVE",
                }
            ],
        }
    )


def _act(run: WiseScientistRun, action: ActionName) -> ActCommand:
    alternative = ActionName.ACTION2 if action is ActionName.ACTION1 else ActionName.ACTION1
    return ActCommand.from_dict(
        {
            "observation_hash": run.current_observation_hash,
            "action": {"name": action.value, "coordinate": None},
            "active_goal_id": "G-RECOVERY",
            "distinction_ids": ["D-RECOVERY"],
            "predicted_consequence": "the visible marker changes",
            "alternatives": [
                {
                    "action": {"name": alternative.value, "coordinate": None},
                    "summary": "the less-supported route control",
                }
            ],
            "rationale": "DISCRIMINATE_LIVE_HYPOTHESES",
            "rationale_summary": "Apply the smallest progress-relevant discriminator.",
        }
    )


def _assess(run: WiseScientistRun) -> AssessCommand:
    return AssessCommand.from_dict(
        {
            "observation_hash": run.current_observation_hash,
            "assessment": "MATCHED",
            "residual": "No decision-relevant residual remains.",
            "preserved_distinction_ids": [],
            "distinction_revisions": [
                {
                    "distinction_id": "D-RECOVERY",
                    "kind": "SUPPORT",
                    "summary": "Retain the locally supported route distinction.",
                }
            ],
            "goal_updates": [],
            "new_distinctions": [],
            "new_subgoals": [],
        }
    )


def _new_run(root: Path) -> tuple[WiseScientistRun, _DeterministicSession]:
    initial = _observation(cell=1, upstream_session_id="original-session")
    first = _observation(cell=2, upstream_session_id="original-session")
    second = _observation(cell=3, upstream_session_id="original-session")
    session = _DeterministicSession(
        initial,
        [(ActionName.ACTION1, first), (ActionName.ACTION2, second)],
    )
    run = WiseScientistRun(
        session,
        root,
        source_commit=_SOURCE_COMMIT,
        authorization_hash=_AUTHORIZATION_HASH,
    )
    run.scan(_scan(run))
    return run, session


def _leave_exact_pending_suffix(root: Path) -> tuple[dict[str, JSONValue], tuple[str, ...]]:
    run, _ = _new_run(root)
    run.act(_act(run, ActionName.ACTION1))
    run.assess(_assess(run))

    checkpoint_path = root / "checkpoint.json"
    stale_checkpoint_bytes = checkpoint_path.read_bytes()
    stale_checkpoint: dict[str, JSONValue] = json.loads(stale_checkpoint_bytes)

    run.act(_act(run, ActionName.ACTION2))
    events = WiseJournal.verify(root / "events.jsonl")
    event_count = stale_checkpoint["journal_event_count"]
    assert isinstance(event_count, int)
    suffix = tuple(event.event_type for event in events[event_count:])
    assert suffix == (
        "action.selected",
        "observation.recorded",
        "action.consequence",
    )
    checkpoint_path.write_bytes(stale_checkpoint_bytes)
    return stale_checkpoint, tuple(event.event_hash for event in events)


def _resume_session(*, divergent_second_consequence: bool = False) -> _DeterministicSession:
    initial = _observation(cell=1, upstream_session_id="recovery-session")
    first = _observation(cell=2, upstream_session_id="recovery-session")
    second_cell = 9 if divergent_second_consequence else 3
    second = _observation(cell=second_cell, upstream_session_id="recovery-session")
    return _DeterministicSession(
        initial,
        [(ActionName.ACTION1, first), (ActionName.ACTION2, second)],
    )


def _empty_resume_session(*, upstream_session_id: str) -> _DeterministicSession:
    return _DeterministicSession(
        _observation(cell=1, upstream_session_id=upstream_session_id),
        [],
    )


def test_resume_replays_all_actions_and_folds_exact_pending_suffix(tmp_path: Path) -> None:
    root = tmp_path / "run"
    stale_checkpoint, original_event_hashes = _leave_exact_pending_suffix(root)
    resumed_session = _resume_session()

    recovered = WiseScientistRun.resume(
        resumed_session,
        root,
        recovery_source_commit=_RECOVERY_SOURCE_COMMIT,
        authorization_hash=_AUTHORIZATION_HASH,
    )

    assert [action.name for action in resumed_session.actions] == [
        ActionName.ACTION1,
        ActionName.ACTION2,
    ]
    assert recovered.phase is WiseRunPhase.AWAITING_ASSESSMENT
    assert recovered.environment_action_count == 4
    assert recovered.unique_logical_action_count == 2
    assert recovered.reset_count == 0
    assert recovered.current_observation_hash == observation_hash(resumed_session.observation)
    assert recovered.observation.upstream_session_id == "recovery-session"
    status = recovered.status()
    assert status["environment_action_count"] == 4
    assert status["unique_logical_action_count"] == 2
    assert status["replay_environment_action_count"] == 2

    repaired_checkpoint = json.loads((root / "checkpoint.json").read_text())
    assert repaired_checkpoint["phase"] == WiseRunPhase.AWAITING_ASSESSMENT.value
    assert repaired_checkpoint["environment_action_count"] == 4
    assert repaired_checkpoint["unique_logical_action_count"] == 2
    assert repaired_checkpoint["replay_environment_action_count"] == 2
    assert repaired_checkpoint["pending"] is not None
    assert repaired_checkpoint["journal_event_count"] == len(original_event_hashes) + 1
    assert stale_checkpoint["environment_action_count"] == 1

    recovered_events = WiseJournal.verify(root / "events.jsonl")
    assert tuple(event.event_hash for event in recovered_events[:-1]) == original_event_hashes
    assert recovered_events[-1].event_type == "run.resumed"
    assert recovered_events[-1].payload["new_official_session_id"] == "recovery-session"
    assert recovered_events[-1].payload["observation_equivalence_rule"] == (
        "exact normalized observation payload after excluding only "
        "upstream_session_id and upstream_metadata"
    )
    assert recovered_events[-1].payload["official_replay_actions_executed"] is True
    assert recovered_events[-1].payload["logical_actions_duplicated"] is False
    assert sum(event.event_type == "action.selected" for event in recovered_events) == 2
    assert sum(event.event_type == "observation.recorded" for event in recovered_events) == 3
    assert sum(event.event_type == "action.consequence" for event in recovered_events) == 2
    recovery_events = WiseJournal.verify(root / "recovery-events.jsonl")
    assert [event.event_type for event in recovery_events] == [
        "recovery.started",
        "recovery.replay_action",
        "recovery.replay_action",
        "recovery.verified",
    ]
    assert recovery_events[-2].payload["semantically_equivalent"] is True

    recovered.assess(_assess(recovered))
    assert recovered.status()["phase"] == WiseRunPhase.READY_TO_ACT.value
    assert recovered.environment_action_count == 4
    assert recovered.unique_logical_action_count == 2
    assert recovered.status()["replay_environment_action_count"] == 2
    assert len(resumed_session.actions) == 2


def test_resume_rejects_deterministic_replay_divergence_without_journal_mutation(
    tmp_path: Path,
) -> None:
    root = tmp_path / "run"
    _, original_event_hashes = _leave_exact_pending_suffix(root)
    divergent_session = _resume_session(divergent_second_consequence=True)

    with pytest.raises(ARC3ValidationError, match=r"(?i)diverg"):
        WiseScientistRun.resume(
            divergent_session,
            root,
            recovery_source_commit=_RECOVERY_SOURCE_COMMIT,
            authorization_hash=_AUTHORIZATION_HASH,
        )

    assert [action.name for action in divergent_session.actions] == [
        ActionName.ACTION1,
        ActionName.ACTION2,
    ]
    events = WiseJournal.verify(root / "events.jsonl")
    assert tuple(event.event_hash for event in events) == original_event_hashes
    recovery_events = WiseJournal.verify(root / "recovery-events.jsonl")
    assert [event.event_type for event in recovery_events] == [
        "recovery.started",
        "recovery.replay_action",
        "recovery.replay_action",
        "recovery.diverged",
    ]
    assert recovery_events[-2].payload["semantically_equivalent"] is False


def test_resume_rejects_non_exact_trailing_suffix(tmp_path: Path) -> None:
    root = tmp_path / "run"
    _leave_exact_pending_suffix(root)
    WiseJournal(root / "events.jsonl").append(
        "unexpected.trailing",
        {"reason": "test-only malformed recovery suffix"},
    )

    with pytest.raises(ARC3ValidationError, match=r"(?i)suffix"):
        WiseScientistRun.resume(
            _resume_session(),
            root,
            recovery_source_commit=_RECOVERY_SOURCE_COMMIT,
            authorization_hash=_AUTHORIZATION_HASH,
        )


def test_resume_accepts_checkpoint_current_with_no_suffix(tmp_path: Path) -> None:
    root = tmp_path / "run"
    initial = _observation(cell=1, upstream_session_id="original-session")
    consequence = _observation(cell=2, upstream_session_id="original-session")
    original_session = _DeterministicSession(
        initial,
        [(ActionName.ACTION1, consequence)],
    )
    run = WiseScientistRun(
        original_session,
        root,
        source_commit=_SOURCE_COMMIT,
        authorization_hash=_AUTHORIZATION_HASH,
    )
    run.scan(_scan(run))
    run.act(_act(run, ActionName.ACTION1))

    before = WiseJournal.verify(root / "events.jsonl")
    checkpoint = json.loads((root / "checkpoint.json").read_text())
    assert checkpoint["journal_event_count"] == len(before)
    assert checkpoint["journal_tail_hash"] == before[-1].event_hash

    resumed_initial = _observation(cell=1, upstream_session_id="recovery-session")
    resumed_consequence = _observation(cell=2, upstream_session_id="recovery-session")
    resumed_session = _DeterministicSession(
        resumed_initial,
        [(ActionName.ACTION1, resumed_consequence)],
    )
    recovered = WiseScientistRun.resume(
        resumed_session,
        root,
        recovery_source_commit=_RECOVERY_SOURCE_COMMIT,
        authorization_hash=_AUTHORIZATION_HASH,
    )

    assert recovered.phase is WiseRunPhase.AWAITING_ASSESSMENT
    assert recovered.environment_action_count == 2
    assert recovered.unique_logical_action_count == 1
    assert recovered.current_observation_hash == observation_hash(resumed_consequence)
    status = recovered.status()
    assert status["environment_action_count"] == 2
    assert status["unique_logical_action_count"] == 1
    assert status["replay_environment_action_count"] == 1
    after = WiseJournal.verify(root / "events.jsonl")
    assert tuple(event.event_hash for event in after[:-1]) == tuple(
        event.event_hash for event in before
    )
    assert after[-1].event_type == "run.resumed"
    assert after[-1].payload["new_official_session_id"] == "recovery-session"
    assert after[-1].payload["observation_equivalence_rule"] == (
        "exact normalized observation payload after excluding only "
        "upstream_session_id and upstream_metadata"
    )
    assert after[-1].payload["official_replay_actions_executed"] is True
    assert after[-1].payload["logical_actions_duplicated"] is False
    assert sum(event.event_type == "action.selected" for event in after) == 1


def test_resume_requires_explicit_opt_in_for_wall_clock_budget_mismatch(
    tmp_path: Path,
) -> None:
    root = tmp_path / "run"
    WiseScientistRun(
        _empty_resume_session(upstream_session_id="original-session"),
        root,
        source_commit=_SOURCE_COMMIT,
        authorization_hash=_AUTHORIZATION_HASH,
    )
    before = WiseJournal.verify(root / "events.jsonl")

    with pytest.raises(ARC3ValidationError, match="budgets differ from the original run"):
        WiseScientistRun.resume(
            _empty_resume_session(upstream_session_id="recovery-session"),
            root,
            recovery_source_commit=_RECOVERY_SOURCE_COMMIT,
            authorization_hash=_AUTHORIZATION_HASH,
            wall_clock_seconds=28_800.0,
        )

    after = WiseJournal.verify(root / "events.jsonl")
    assert tuple(event.event_hash for event in after) == tuple(event.event_hash for event in before)
    assert not (root / "recovery-events.jsonl").exists()


def test_explicit_wall_clock_extension_is_append_only_and_survives_later_resume(
    tmp_path: Path,
) -> None:
    root = tmp_path / "run"
    WiseScientistRun(
        _empty_resume_session(upstream_session_id="original-session"),
        root,
        source_commit=_SOURCE_COMMIT,
        authorization_hash=_AUTHORIZATION_HASH,
    )
    original = WiseJournal.verify(root / "events.jsonl")

    extended = WiseScientistRun.resume(
        _empty_resume_session(upstream_session_id="extension-session"),
        root,
        recovery_source_commit=_RECOVERY_SOURCE_COMMIT,
        authorization_hash=_AUTHORIZATION_HASH,
        wall_clock_seconds=28_800.0,
        allow_wall_clock_extension=True,
        wall_clock_extension_reason="  Continue the bounded observed-WIN attempt.  ",
    )

    extended_events = WiseJournal.verify(root / "events.jsonl")
    assert tuple(event.event_hash for event in extended_events[: len(original)]) == tuple(
        event.event_hash for event in original
    )
    assert extended_events[0].payload["budgets"] == {
        "max_environment_actions": 1_000,
        "max_resets": 20,
        "wall_clock_seconds": 14_400.0,
    }
    assert extended_events[-1].event_type == "run.resumed"
    assert extended_events[-1].payload["wall_clock_budget_extension"] == {
        "old_wall_clock_seconds": 14_400.0,
        "new_wall_clock_seconds": 28_800.0,
        "reason": "Continue the bounded observed-WIN attempt.",
    }
    assert extended.status()["wall_clock_seconds"] == 28_800.0

    resumed = WiseScientistRun.resume(
        _empty_resume_session(upstream_session_id="later-session"),
        root,
        recovery_source_commit="4" * 40,
        authorization_hash=_AUTHORIZATION_HASH,
        wall_clock_seconds=28_800.0,
    )

    final_events = WiseJournal.verify(root / "events.jsonl")
    assert final_events[-1].event_type == "run.resumed"
    assert final_events[-1].payload["wall_clock_budget_extension"] is None
    assert resumed.status()["wall_clock_seconds"] == 28_800.0


@pytest.mark.parametrize(
    ("override", "expected"),
    [
        ({"max_environment_actions": 1_001}, "budgets differ"),
        ({"max_resets": 21}, "budgets differ"),
        ({"wall_clock_seconds": 14_400.0}, "monotonically increase"),
        ({"wall_clock_seconds": 7_200.0}, "monotonically increase"),
        ({"wall_clock_extension_reason": "   "}, "nonempty reason"),
        ({"wall_clock_extension_reason": "x" * 501}, "exceeds 500 characters"),
    ],
)
def test_wall_clock_extension_rejects_nonmonotonic_or_broader_budget_changes(
    tmp_path: Path,
    override: dict[str, object],
    expected: str,
) -> None:
    root = tmp_path / "run"
    WiseScientistRun(
        _empty_resume_session(upstream_session_id="original-session"),
        root,
        source_commit=_SOURCE_COMMIT,
        authorization_hash=_AUTHORIZATION_HASH,
    )
    arguments: dict[str, object] = {
        "recovery_source_commit": _RECOVERY_SOURCE_COMMIT,
        "authorization_hash": _AUTHORIZATION_HASH,
        "max_environment_actions": 1_000,
        "max_resets": 20,
        "wall_clock_seconds": 28_800.0,
        "allow_wall_clock_extension": True,
        "wall_clock_extension_reason": "Bounded continuation.",
    }
    arguments.update(override)

    with pytest.raises(ARC3ValidationError, match=expected):
        WiseScientistRun.resume(
            _empty_resume_session(upstream_session_id="recovery-session"),
            root,
            **arguments,  # type: ignore[arg-type]
        )


def test_wall_clock_extension_reason_requires_opt_in(tmp_path: Path) -> None:
    root = tmp_path / "run"
    WiseScientistRun(
        _empty_resume_session(upstream_session_id="original-session"),
        root,
        source_commit=_SOURCE_COMMIT,
        authorization_hash=_AUTHORIZATION_HASH,
    )

    with pytest.raises(ARC3ValidationError, match="requires explicit extension opt-in"):
        WiseScientistRun.resume(
            _empty_resume_session(upstream_session_id="recovery-session"),
            root,
            recovery_source_commit=_RECOVERY_SOURCE_COMMIT,
            authorization_hash=_AUTHORIZATION_HASH,
            wall_clock_extension_reason="Unrequested reason.",
        )


def test_explicit_environment_action_extension_is_append_only_and_survives_resume(
    tmp_path: Path,
) -> None:
    root = tmp_path / "run"
    WiseScientistRun(
        _empty_resume_session(upstream_session_id="original-session"),
        root,
        source_commit=_SOURCE_COMMIT,
        authorization_hash=_AUTHORIZATION_HASH,
    )
    original = WiseJournal.verify(root / "events.jsonl")

    extended = WiseScientistRun.resume(
        _empty_resume_session(upstream_session_id="extension-session"),
        root,
        recovery_source_commit=_RECOVERY_SOURCE_COMMIT,
        authorization_hash=_AUTHORIZATION_HASH,
        max_environment_actions=3_000,
        allow_environment_action_extension=True,
        environment_action_extension_reason=(
            "  Replay the immutable terminal checkpoint and continue toward observed WIN.  "
        ),
    )

    extended_events = WiseJournal.verify(root / "events.jsonl")
    assert tuple(event.event_hash for event in extended_events[: len(original)]) == tuple(
        event.event_hash for event in original
    )
    assert extended_events[0].payload["budgets"] == {
        "max_environment_actions": 1_000,
        "max_resets": 20,
        "wall_clock_seconds": 14_400.0,
    }
    assert extended_events[-1].payload["environment_action_budget_extension"] == {
        "old_max_environment_actions": 1_000,
        "new_max_environment_actions": 3_000,
        "reason": "Replay the immutable terminal checkpoint and continue toward observed WIN.",
    }
    assert extended.status()["max_environment_actions"] == 3_000

    resumed = WiseScientistRun.resume(
        _empty_resume_session(upstream_session_id="later-session"),
        root,
        recovery_source_commit="4" * 40,
        authorization_hash=_AUTHORIZATION_HASH,
        max_environment_actions=3_000,
    )

    final_events = WiseJournal.verify(root / "events.jsonl")
    assert final_events[-1].payload["environment_action_budget_extension"] is None
    assert resumed.status()["max_environment_actions"] == 3_000


@pytest.mark.parametrize(
    ("override", "expected"),
    [
        ({"max_environment_actions": 1_000}, "monotonically increase"),
        ({"max_environment_actions": 999}, "monotonically increase"),
        ({"max_resets": 21}, "budgets differ"),
        ({"wall_clock_seconds": 28_800.0}, "budgets differ"),
        ({"environment_action_extension_reason": "   "}, "nonempty reason"),
        ({"environment_action_extension_reason": "x" * 501}, "exceeds 500 characters"),
        ({"allow_environment_action_extension": 1}, "opt-in must be boolean"),
    ],
)
def test_environment_action_extension_rejects_nonmonotonic_or_broader_changes(
    tmp_path: Path,
    override: dict[str, object],
    expected: str,
) -> None:
    root = tmp_path / "run"
    WiseScientistRun(
        _empty_resume_session(upstream_session_id="original-session"),
        root,
        source_commit=_SOURCE_COMMIT,
        authorization_hash=_AUTHORIZATION_HASH,
    )
    arguments: dict[str, object] = {
        "recovery_source_commit": _RECOVERY_SOURCE_COMMIT,
        "authorization_hash": _AUTHORIZATION_HASH,
        "max_environment_actions": 3_000,
        "max_resets": 20,
        "wall_clock_seconds": 14_400.0,
        "allow_environment_action_extension": True,
        "environment_action_extension_reason": "Bounded physical-action continuation.",
    }
    arguments.update(override)

    with pytest.raises(ARC3ValidationError, match=expected):
        WiseScientistRun.resume(
            _empty_resume_session(upstream_session_id="recovery-session"),
            root,
            **arguments,  # type: ignore[arg-type]
        )


def test_environment_action_extension_reason_requires_opt_in(tmp_path: Path) -> None:
    root = tmp_path / "run"
    WiseScientistRun(
        _empty_resume_session(upstream_session_id="original-session"),
        root,
        source_commit=_SOURCE_COMMIT,
        authorization_hash=_AUTHORIZATION_HASH,
    )

    with pytest.raises(ARC3ValidationError, match="requires explicit extension opt-in"):
        WiseScientistRun.resume(
            _empty_resume_session(upstream_session_id="recovery-session"),
            root,
            recovery_source_commit=_RECOVERY_SOURCE_COMMIT,
            authorization_hash=_AUTHORIZATION_HASH,
            environment_action_extension_reason="Unrequested reason.",
        )


def test_environment_action_extension_chain_rejects_malformed_receipt(
    tmp_path: Path,
) -> None:
    root = tmp_path / "run"
    WiseScientistRun(
        _empty_resume_session(upstream_session_id="original-session"),
        root,
        source_commit=_SOURCE_COMMIT,
        authorization_hash=_AUTHORIZATION_HASH,
    )
    journal = WiseJournal(root / "events.jsonl")
    journal.append(
        "run.resumed",
        {
            "environment_action_budget_extension": {
                "old_max_environment_actions": 999,
                "new_max_environment_actions": 3_000,
                "reason": "Broken predecessor identity.",
            }
        },
    )

    with pytest.raises(ARC3ValidationError, match="invalid environment-action extension chain"):
        WiseScientistRun._effective_environment_action_budget(
            journal,
            original_max_actions=1_000,
        )
