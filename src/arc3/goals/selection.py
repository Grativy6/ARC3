"""Goal selection with bounded novelty after strong external progress evidence."""

from __future__ import annotations

from collections.abc import Iterable

from .models import (
    ActionGoalEstimate,
    GoalKind,
    GoalRecord,
    GoalRole,
    GoalSelection,
    GoalStatus,
)


def has_strong_external_progress(records: Iterable[GoalRecord], *, threshold: int = 3) -> bool:
    """Return whether explicit score/level/win evidence clears an integer rank threshold."""

    if isinstance(threshold, bool) or threshold <= 0:
        raise ValueError("threshold must be a positive integer")
    explicit_kinds = {
        GoalKind.EXPLICIT_PROGRESS,
        GoalKind.LEVEL_ADVANCE,
        GoalKind.WIN,
    }
    return any(
        record.status is not GoalStatus.RETIRED
        and record.candidate.kind in explicit_kinds
        and record.rank >= threshold
        for record in records
    )


def _role_bonus(role: GoalRole) -> int:
    if role is GoalRole.EXTERNAL_PROGRESS:
        return 3
    if role is GoalRole.TERMINAL_HYPOTHESIS:
        return 2
    return 1


def select_goal_action(
    records: tuple[GoalRecord, ...],
    options: tuple[ActionGoalEstimate, ...],
    *,
    strong_progress_threshold: int = 3,
) -> GoalSelection:
    """Rank model estimates without converting a goal hypothesis into permission."""

    if not options:
        return GoalSelection(None, None, 0, 0, 0.0, False, "no-action-estimates")
    by_id = {
        record.candidate.goal_id: record
        for record in records
        if record.status is not GoalStatus.RETIRED
    }
    for option in options:
        if option.goal_id is not None and option.goal_id not in by_id:
            raise ValueError(f"action estimate references unavailable goal: {option.goal_id}")
    suppress_novelty = has_strong_external_progress(
        by_id.values(), threshold=strong_progress_threshold
    )

    def rank(option: ActionGoalEstimate) -> tuple[float, int, int, str, str]:
        record = by_id.get(option.goal_id) if option.goal_id is not None else None
        desirability = (
            record.rank + _role_bonus(record.candidate.role) + option.goal_advance_rank
            if record is not None
            else 0
        )
        exploration = option.exploration.information_gain + option.exploration.reversibility
        if not suppress_novelty:
            exploration += option.exploration.novelty
        total = (
            float(desirability * 2 + option.reachability_rank - option.failure_risk_rank)
            + exploration
        )
        return (
            total,
            desirability,
            option.reachability_rank,
            option.action.name.value,
            repr(option.action.coordinate),
        )

    selected = max(options, key=rank)
    record = by_id.get(selected.goal_id) if selected.goal_id is not None else None
    desirability = (
        record.rank + _role_bonus(record.candidate.role) + selected.goal_advance_rank
        if record is not None
        else 0
    )
    exploration = selected.exploration.information_gain + selected.exploration.reversibility
    if not suppress_novelty:
        exploration += selected.exploration.novelty
    rationale = (
        "external-progress-supported-goal"
        if suppress_novelty and record is not None
        else "goal-and-exploration-ranking"
        if record is not None
        else "intrinsic-exploration-only"
    )
    return GoalSelection(
        goal_id=selected.goal_id,
        action=selected.action,
        desirability_rank=desirability,
        reachability_rank=selected.reachability_rank,
        exploration_utility=exploration,
        novelty_suppressed=suppress_novelty,
        rationale=rationale,
    )


__all__ = ["has_strong_external_progress", "select_goal_action"]
