from __future__ import annotations

from arc3.adapters import GridFrame, Observation
from arc3.goals import (
    GoalAcquirer,
    GoalKind,
    GoalStatus,
    GoalTransition,
)
from arc3.hypotheses import HypothesisScope
from arc3.types import ActionName, GameId, GameStateName


def observation(rows: tuple[tuple[int, ...], ...], *, score: int, levels: int = 0) -> Observation:
    return Observation(
        game_id=GameId("opaque-procedural-scope"),
        frames=(GridFrame.from_rows(rows),),
        state=GameStateName.NOT_FINISHED,
        levels_completed=levels,
        win_levels=3,
        available_actions=(ActionName.ACTION1, ActionName.ACTION2),
        upstream_metadata=(("score", score),),
    )


def transition(
    *,
    step: int,
    level_ref: str,
    before_score: int,
    after_score: int,
    source_prefix: str,
) -> GoalTransition:
    return GoalTransition(
        before=observation(((1, 1, 1), (1, 1, 1), (1, 0, 1)), score=before_score),
        after=observation(((1, 1, 1), (1, 1, 1), (1, 1, 1)), score=after_score),
        before_event_ids=(f"{source_prefix}-before",),
        after_event_ids=(f"{source_prefix}-after",),
        step=step,
        level_scope_ref=level_ref,
        game_scope_ref="game-session",
    )


def test_progress_correlated_structure_is_supported_and_compared_across_levels() -> None:
    acquirer = GoalAcquirer()

    first = acquirer.observe_transition(
        transition(
            step=1,
            level_ref="level-0",
            before_score=0,
            after_score=1,
            source_prefix="first",
        )
    )
    second = acquirer.observe_transition(
        transition(
            step=2,
            level_ref="level-1",
            before_score=1,
            after_score=2,
            source_prefix="second",
        )
    )

    assert first.progress_signals
    assert any(change.improved for change in first.structural_changes)
    completion_records = tuple(
        record
        for record in acquirer.registry.records()
        if record.candidate.kind is GoalKind.COMPLETION_PATTERN
    )
    assert len(completion_records) == 3
    assert {record.candidate.scope for record in completion_records} == {
        HypothesisScope.LEVEL,
        HypothesisScope.GAME,
    }
    game_record = next(
        record for record in completion_records if record.candidate.scope is HypothesisScope.GAME
    )
    assert game_record.source_event_ids == (
        "first-after",
        "first-before",
        "second-after",
        "second-before",
    )
    assert second.touched_goal_ids


def test_tested_goal_retires_then_reopens_on_later_external_progress() -> None:
    acquirer = GoalAcquirer()
    initial = acquirer.observe_transition(
        transition(
            step=1,
            level_ref="level-0",
            before_score=0,
            after_score=1,
            source_prefix="initial",
        )
    )
    goal_id = next(
        goal_id
        for goal_id in initial.touched_goal_ids
        if acquirer.registry.get(goal_id).candidate.kind is GoalKind.COMPLETION_PATTERN
    )
    for index in (2, 3):
        no_progress = transition(
            step=index,
            level_ref="level-0",
            before_score=1,
            after_score=1,
            source_prefix=f"no-progress-{index}",
        )
        acquirer.record_goal_test(goal_id, no_progress, target_condition_reached=True)

    assert acquirer.registry.get(goal_id).status is GoalStatus.RETIRED

    later = transition(
        step=4,
        level_ref="level-0",
        before_score=1,
        after_score=2,
        source_prefix="later",
    )
    reopened = acquirer.record_goal_test(goal_id, later, target_condition_reached=True)

    assert reopened.status is GoalStatus.ACTIVE
    assert reopened.reopen_count == 1
    assert reopened.contradiction_count == 2
