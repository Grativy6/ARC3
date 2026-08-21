"""Bounded baseline episode runner with concise action receipts."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from arc3.adapters import EnvironmentSession, Observation, ScoreSummary
from arc3.types import ActionRequest, FrameHash, GameStateName, RationaleCategory


class BaselinePolicy(Protocol):
    """Small policy surface shared by deterministic Stage 02 baselines."""

    def select(self, observation: Observation) -> ActionRequest:
        """Select one valid action from the current observation."""


class StopReason(StrEnum):
    """Why a bounded baseline episode stopped."""

    WIN = "win"
    ACTION_BUDGET = "action_budget"
    RESET_BUDGET = "reset_budget"


@dataclass(frozen=True, slots=True)
class BaselineActionReceipt:
    """Compact, non-secret evidence for one submitted action."""

    ordinal: int
    action: ActionRequest
    before_state: GameStateName
    before_frames: tuple[FrameHash, ...]
    after_state: GameStateName
    after_frames: tuple[FrameHash, ...]


@dataclass(frozen=True, slots=True)
class BaselineEpisodeResult:
    """Bounded episode result separate from an upstream scorecard."""

    stop_reason: StopReason
    environment_actions: int
    resets: int
    final_observation: Observation
    scorecard: ScoreSummary | None
    receipts: tuple[BaselineActionReceipt, ...]


def _frame_hashes(observation: Observation) -> tuple[FrameHash, ...]:
    return tuple(frame.digest for frame in observation.frames)


def run_baseline_episode(
    session: EnvironmentSession,
    policy: BaselinePolicy,
    *,
    max_actions: int,
    max_resets: int,
) -> BaselineEpisodeResult:
    """Run one policy under explicit action/reset budgets.

    Reset calls are recorded but do not consume the environment-action budget. The
    reasoning payload is a typed category and concise summary, never hidden
    chain-of-thought.
    """

    if isinstance(max_actions, bool) or max_actions <= 0:
        raise ValueError("max_actions must be a positive integer")
    if isinstance(max_resets, bool) or max_resets <= 0:
        raise ValueError("max_resets must be a positive integer")

    observation = session.observation
    environment_actions = 0
    resets = 0
    receipts: list[BaselineActionReceipt] = []
    stop_reason = StopReason.ACTION_BUDGET

    while environment_actions < max_actions:
        if observation.state is GameStateName.WIN:
            stop_reason = StopReason.WIN
            break

        action = policy.select(observation)
        is_reset = action.name.value == "RESET"
        if is_reset and resets >= max_resets:
            stop_reason = StopReason.RESET_BUDGET
            break

        before = observation
        observation = session.step(
            action,
            reasoning={
                "category": RationaleCategory.BASELINE.value,
                "summary": "bounded deterministic baseline selection",
            },
        )
        if is_reset:
            resets += 1
        else:
            environment_actions += 1
        receipts.append(
            BaselineActionReceipt(
                ordinal=len(receipts),
                action=action,
                before_state=before.state,
                before_frames=_frame_hashes(before),
                after_state=observation.state,
                after_frames=_frame_hashes(observation),
            )
        )
    else:
        stop_reason = StopReason.ACTION_BUDGET

    scorecard = session.close()
    return BaselineEpisodeResult(
        stop_reason=stop_reason,
        environment_actions=environment_actions,
        resets=resets,
        final_observation=observation,
        scorecard=scorecard,
        receipts=tuple(receipts),
    )


__all__ = [
    "BaselineActionReceipt",
    "BaselineEpisodeResult",
    "BaselinePolicy",
    "StopReason",
    "run_baseline_episode",
]
