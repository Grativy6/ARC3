from __future__ import annotations

from arc3.goals import (
    ActionGoalEstimate,
    EvidenceDirection,
    GoalCandidate,
    GoalEvidence,
    GoalKind,
    GoalRegistry,
    GoalRole,
    IntrinsicExplorationUtility,
    render_goal_report,
    select_goal_action,
    structured_goal_report,
)
from arc3.hypotheses import HypothesisScope
from arc3.types import ActionName, ActionRequest


def external_record() -> tuple[GoalRegistry, str]:
    evidence = GoalEvidence(
        evidence_id="score-evidence",
        direction=EvidenceDirection.SUPPORT,
        source_event_ids=("score-event",),
        observed_step=2,
        level_index=0,
        summary="explicit score-increase: 0 -> 1",
        rank_impact=4,
    )
    candidate = GoalCandidate(
        goal_id="goal-score",
        kind=GoalKind.EXPLICIT_PROGRESS,
        role=GoalRole.EXTERNAL_PROGRESS,
        scope=HypothesisScope.LEVEL,
        scope_ref="level-a",
        target_state="continue-score-increase",
        source_evidence=(evidence,),
        created_step=2,
        initial_rank=4,
    )
    registry = GoalRegistry()
    registry.register(candidate)
    return registry, candidate.goal_id


def test_strong_external_progress_suppresses_novelty_trap() -> None:
    registry, goal_id = external_record()
    progress_action = ActionRequest(ActionName.ACTION1)
    novelty_action = ActionRequest(ActionName.ACTION2)
    selection = select_goal_action(
        registry.records(),
        (
            ActionGoalEstimate(
                progress_action,
                goal_id,
                goal_advance_rank=2,
                reachability_rank=2,
                exploration=IntrinsicExplorationUtility(0.0, 0.0),
            ),
            ActionGoalEstimate(
                novelty_action,
                None,
                goal_advance_rank=0,
                reachability_rank=0,
                exploration=IntrinsicExplorationUtility(1.0, 0.0),
            ),
        ),
    )

    assert selection.action == progress_action
    assert selection.goal_id == goal_id
    assert selection.novelty_suppressed is True
    assert selection.exploration_utility == 0.0


def test_intrinsic_exploration_is_a_separate_type_not_a_goal_candidate() -> None:
    utility = IntrinsicExplorationUtility(novelty=1.0, information_gain=0.5)

    assert utility.novelty == 1.0
    assert "intrinsic" not in {role.value for role in GoalRole}


def test_report_is_source_linked_concise_and_non_anthropomorphic() -> None:
    registry, goal_id = external_record()
    selection = select_goal_action(
        registry.records(),
        (
            ActionGoalEstimate(
                ActionRequest(ActionName.ACTION1),
                goal_id,
                goal_advance_rank=1,
                reachability_rank=1,
                exploration=IntrinsicExplorationUtility(0.0, 0.0),
            ),
        ),
    )

    structured = structured_goal_report(registry.records(), selection)
    rendered = render_goal_report(registry.records(), selection)

    assert structured["schema"] == "arc3.goal.report.v1"
    assert "score-event" in rendered
    assert len(rendered.splitlines()) == 4
    assert not {"want", "think", "feel", "believe"} & set(rendered.lower().split())
