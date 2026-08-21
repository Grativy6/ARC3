from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from arc3.goals import (
    EvidenceDirection,
    GoalCandidate,
    GoalEventType,
    GoalEvidence,
    GoalKind,
    GoalRegistry,
    GoalRole,
    GoalStatus,
)
from arc3.hypotheses import HypothesisScope


def evidence(
    identifier: str,
    direction: EvidenceDirection,
    *,
    step: int,
    level: int = 0,
) -> GoalEvidence:
    return GoalEvidence(
        evidence_id=identifier,
        direction=direction,
        source_event_ids=(f"event-{identifier}",),
        observed_step=step,
        level_index=level,
        summary=f"bounded evidence {identifier}",
        rank_impact=2,
    )


def candidate() -> GoalCandidate:
    return GoalCandidate(
        goal_id="goal-pattern",
        kind=GoalKind.COMPLETION_PATTERN,
        role=GoalRole.TERMINAL_HYPOTHESIS,
        scope=HypothesisScope.LEVEL,
        scope_ref="level-a",
        target_state="complete-repeated-pattern",
        source_evidence=(evidence("created", EvidenceDirection.SUPPORT, step=0),),
        created_step=0,
    )


def test_candidate_and_source_evidence_are_immutable_and_convert_to_hypothesis() -> None:
    goal = candidate()

    with pytest.raises(FrozenInstanceError):
        goal.target_state = "rewritten"  # type: ignore[misc]

    statement = goal.as_hypothesis_statement()
    assert statement.target_state == "complete-repeated-pattern"
    assert statement.terminal_indicators == (GoalKind.COMPLETION_PATTERN.value,)


def test_contradiction_retires_without_deleting_history_and_support_reopens() -> None:
    registry = GoalRegistry(retirement_threshold=2)
    registry.register(candidate())
    registry.support("goal-pattern", evidence("support", EvidenceDirection.SUPPORT, step=1))
    registry.contradict(
        "goal-pattern", evidence("contradiction-a", EvidenceDirection.CONTRADICTION, step=2)
    )
    retired = registry.contradict(
        "goal-pattern", evidence("contradiction-b", EvidenceDirection.CONTRADICTION, step=3)
    )

    assert retired.status is GoalStatus.RETIRED
    assert len(retired.evidence) == 4

    reopened = registry.support(
        "goal-pattern", evidence("later-support", EvidenceDirection.SUPPORT, step=4, level=1)
    )

    assert reopened.status is GoalStatus.ACTIVE
    assert reopened.reopen_count == 1
    assert {event.event_type for event in registry.events} >= {
        GoalEventType.CREATED,
        GoalEventType.SUPPORTED,
        GoalEventType.CONTRADICTED,
        GoalEventType.RETIRED,
        GoalEventType.REOPENED,
    }
    assert registry.get("goal-pattern").source_event_ids == (
        "event-contradiction-a",
        "event-contradiction-b",
        "event-created",
        "event-later-support",
        "event-support",
    )


def test_retired_goal_cannot_be_selected_for_planning() -> None:
    registry = GoalRegistry(retirement_threshold=1)
    registry.register(candidate())
    registry.contradict(
        "goal-pattern", evidence("contradiction", EvidenceDirection.CONTRADICTION, step=1)
    )

    with pytest.raises(ValueError, match="retired"):
        registry.selected("goal-pattern")
