"""Deterministic delayed/proxy-goal comparison against novelty-only choice."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import StrEnum

from arc3.hypotheses import HypothesisScope
from arc3.types import ActionName, ActionRequest

from .models import (
    ActionGoalEstimate,
    EvidenceDirection,
    GoalCandidate,
    GoalEvidence,
    GoalKind,
    GoalRole,
    IntrinsicExplorationUtility,
)
from .registry import GoalRegistry
from .selection import select_goal_action


class GoalMechanismStatus(StrEnum):
    """Bounded outcome vocabulary for the Stage 09 comparison."""

    OBSERVED = "MECHANISM_OBSERVED"
    NOT_OBSERVED = "MECHANISM_NOT_OBSERVED"


@dataclass(frozen=True, slots=True)
class GoalTrapCase:
    """Evaluator-owned path where novelty is an attractive non-progressing proxy."""

    case_id: str
    progress_actions: tuple[ActionRequest, ...]
    novelty_actions: tuple[ActionRequest, ...]

    def __post_init__(self) -> None:
        if not self.case_id.strip() or not self.progress_actions:
            raise ValueError("goal trap cases require identity and at least one delayed step")
        if len(self.progress_actions) != len(self.novelty_actions):
            raise ValueError("goal trap paths must have paired progress and novelty actions")
        if any(
            progress == novelty
            for progress, novelty in zip(self.progress_actions, self.novelty_actions, strict=True)
        ):
            raise ValueError("progress and novelty actions must differ at each step")


@dataclass(frozen=True, slots=True)
class GoalComparison:
    """Measured synthetic completion result under identical action budgets."""

    surface: str
    scorer: str
    episodes: int
    action_budget_per_episode: int
    goal_completions: int
    novelty_completions: int
    goal_actions: int
    novelty_actions: int
    status: GoalMechanismStatus

    @property
    def goal_completion_rate(self) -> float:
        return self.goal_completions / self.episodes

    @property
    def novelty_completion_rate(self) -> float:
        return self.novelty_completions / self.episodes

    @property
    def completion_rate_difference(self) -> float:
        return self.goal_completion_rate - self.novelty_completion_rate


def held_out_goal_traps(*, seed: int, count: int, horizon: int = 4) -> tuple[GoalTrapCase, ...]:
    """Generate label-permuted delayed paths with no public environment identities."""

    if isinstance(seed, bool) or not -(2**63) <= seed < 2**63:
        raise ValueError("seed must be a signed 64-bit integer")
    if isinstance(count, bool) or count <= 0:
        raise ValueError("count must be a positive integer")
    if isinstance(horizon, bool) or horizon < 2:
        raise ValueError("horizon must be at least two delayed steps")
    actions = tuple(ActionRequest(name) for name in tuple(ActionName)[1:6])
    cases: list[GoalTrapCase] = []
    for ordinal in range(count):
        digest = hashlib.sha256(f"arc3.goals.trap.v1\0{seed}\0{ordinal}".encode()).digest()
        progress: list[ActionRequest] = []
        novelty: list[ActionRequest] = []
        for step in range(horizon):
            progress_index = digest[(step * 2) % len(digest)] % len(actions)
            novelty_index = digest[(step * 2 + 1) % len(digest)] % (len(actions) - 1)
            if novelty_index >= progress_index:
                novelty_index += 1
            progress.append(actions[progress_index])
            novelty.append(actions[novelty_index])
        cases.append(
            GoalTrapCase(
                case_id=f"held-out-goal-trap-{ordinal:04d}-{digest.hex()[:10]}",
                progress_actions=tuple(progress),
                novelty_actions=tuple(novelty),
            )
        )
    return tuple(cases)


def _strong_goal(case: GoalTrapCase) -> tuple[GoalRegistry, str]:
    evidence = GoalEvidence(
        evidence_id=f"anchor-{case.case_id}",
        direction=EvidenceDirection.SUPPORT,
        source_event_ids=(f"source-{case.case_id}",),
        observed_step=0,
        level_index=0,
        summary="explicit score increase followed discrepancy reduction",
        rank_impact=4,
    )
    candidate = GoalCandidate(
        goal_id=f"goal-{case.case_id}",
        kind=GoalKind.EXPLICIT_PROGRESS,
        role=GoalRole.EXTERNAL_PROGRESS,
        scope=HypothesisScope.LEVEL,
        scope_ref=f"level-{case.case_id}",
        target_state="continue-supported-discrepancy-reduction",
        source_evidence=(evidence,),
        created_step=0,
        initial_rank=4,
    )
    registry = GoalRegistry()
    registry.register(candidate)
    return registry, candidate.goal_id


def _goal_policy_completes(case: GoalTrapCase) -> tuple[bool, int]:
    registry, goal_id = _strong_goal(case)
    records = registry.records()
    for step, (progress, novelty) in enumerate(
        zip(case.progress_actions, case.novelty_actions, strict=True), start=1
    ):
        options = (
            ActionGoalEstimate(
                action=progress,
                goal_id=goal_id,
                goal_advance_rank=2,
                reachability_rank=2,
                exploration=IntrinsicExplorationUtility(0.05, 0.1, 0.2),
            ),
            ActionGoalEstimate(
                action=novelty,
                goal_id=None,
                goal_advance_rank=0,
                reachability_rank=0,
                exploration=IntrinsicExplorationUtility(1.0, 0.2, 0.0),
            ),
        )
        selection = select_goal_action(records, options)
        if selection.action != progress:
            return False, step
    return True, len(case.progress_actions)


def _novelty_policy_completes(case: GoalTrapCase) -> tuple[bool, int]:
    position = 0
    for progress, novelty in zip(case.progress_actions, case.novelty_actions, strict=True):
        options = (
            (0.05, progress),
            (1.0, novelty),
        )
        selected = max(options, key=lambda item: (item[0], item[1].name.value))[1]
        if selected == progress:
            position += 1
        else:
            position = 0
    return position == len(case.progress_actions), len(case.progress_actions)


def compare_goal_policy_to_novelty(cases: tuple[GoalTrapCase, ...]) -> GoalComparison:
    """Run a fixed-budget A5-style goal-inference comparison on synthetic cases."""

    if not cases:
        raise ValueError("at least one goal trap case is required")
    horizons = {len(case.progress_actions) for case in cases}
    if len(horizons) != 1:
        raise ValueError("comparison cases must use one shared action budget")
    goal_runs = tuple(_goal_policy_completes(case) for case in cases)
    novelty_runs = tuple(_novelty_policy_completes(case) for case in cases)
    goal_completions = sum(completed for completed, _actions in goal_runs)
    novelty_completions = sum(completed for completed, _actions in novelty_runs)
    observed = goal_completions > novelty_completions
    return GoalComparison(
        surface="synthetic",
        scorer="arc3.goals.delayed-proxy-completion.v1",
        episodes=len(cases),
        action_budget_per_episode=next(iter(horizons)),
        goal_completions=goal_completions,
        novelty_completions=novelty_completions,
        goal_actions=sum(actions for _completed, actions in goal_runs),
        novelty_actions=sum(actions for _completed, actions in novelty_runs),
        status=(GoalMechanismStatus.OBSERVED if observed else GoalMechanismStatus.NOT_OBSERVED),
    )


__all__ = [
    "GoalComparison",
    "GoalMechanismStatus",
    "GoalTrapCase",
    "compare_goal_policy_to_novelty",
    "held_out_goal_traps",
]
