"""Generic official-shaped Stage 15 episode-loop tests."""

from __future__ import annotations

from collections.abc import Mapping

from arc3.adapters import GridFrame, Observation, ScoreRunSummary, ScoreSummary
from arc3.evaluation.public import run_public_episode
from arc3.types import (
    ActionName,
    ActionRequest,
    EvaluationSurface,
    GameId,
    GameStateName,
    JSONValue,
)


def _observation(
    value: int,
    *,
    state: GameStateName,
    levels: int,
    returned: ActionRequest | None = None,
) -> Observation:
    return Observation(
        game_id=GameId("opaque-official-fixture"),
        frames=(GridFrame(((value, 0), (0, 0))),),
        state=state,
        levels_completed=levels,
        win_levels=1,
        available_actions=(ActionName.ACTION1,),
        returned_action=returned,
    )


class _OneStepOfficialSession:
    def __init__(self) -> None:
        self._observation = _observation(1, state=GameStateName.NOT_FINISHED, levels=0)
        self.steps: list[ActionRequest] = []

    @property
    def observation(self) -> Observation:
        return self._observation

    def step(
        self,
        action: ActionRequest,
        *,
        reasoning: Mapping[str, JSONValue] | None = None,
    ) -> Observation:
        assert reasoning is not None
        assert reasoning["category"] == "stage15-local-public"
        self.steps.append(action)
        self._observation = _observation(
            2,
            state=GameStateName.WIN,
            levels=1,
            returned=action,
        )
        return self._observation

    def reset(self) -> Observation:
        raise AssertionError("reset is not needed in this fixture")

    def scorecard(self) -> ScoreSummary | None:
        return None

    def close(self) -> ScoreSummary:
        return ScoreSummary(
            surface=EvaluationSurface.LOCAL_PUBLIC,
            verified=True,
            scorer="arc-agi==0.9.9 local ScorecardManager",
            score=1.0,
            runs=(
                ScoreRunSummary(
                    game_id=GameId("opaque-official-fixture"),
                    score=1.0,
                    levels_completed=1,
                    actions=1,
                    resets=0,
                    state=GameStateName.WIN,
                    completed=True,
                    level_scores=(1.0,),
                    level_actions=(1,),
                    level_baseline_actions=(1,),
                ),
            ),
        )


class _OneStepPolicy:
    manages_trace = False

    def __init__(self) -> None:
        self.consequences: list[Observation] = []
        self.closed = False

    def select(self, observation: Observation) -> ActionRequest:
        assert observation.state is GameStateName.NOT_FINISHED
        return ActionRequest(ActionName.ACTION1)

    def accept_consequence(self, observation: Observation) -> None:
        self.consequences.append(observation)

    def close(self) -> None:
        self.closed = True


def test_public_episode_uses_only_observation_action_consequence_boundary() -> None:
    session = _OneStepOfficialSession()
    policy = _OneStepPolicy()

    scorecard, metrics = run_public_episode(
        session,
        policy,
        max_actions=10,
        max_resets=2,
    )

    assert session.steps == [ActionRequest(ActionName.ACTION1)]
    assert len(policy.consequences) == 1
    assert scorecard is not None
    assert scorecard.surface is EvaluationSurface.LOCAL_PUBLIC
    assert scorecard.score == 1.0
    assert metrics["environment_actions"] == 1
    assert metrics["actions_to_first_completed_level"] == 1
    assert metrics["invalid_action_rate"] == 0.0
    assert metrics["final_state"] == GameStateName.WIN.value
