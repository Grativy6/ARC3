"""Production-shaped adapter and session for procedural laboratory episodes."""

from __future__ import annotations

from collections.abc import Mapping

from arc3.adapters import (
    EnvironmentDescriptor,
    Observation,
    ScoreRunSummary,
    ScoreSummary,
    validate_action_request,
)
from arc3.errors import AdapterError, EnvironmentStateError
from arc3.types import (
    ActionName,
    ActionRequest,
    EvaluationSurface,
    GameId,
    GameStateName,
    JSONValue,
)

from ._engine import (
    _EpisodeSpec,
    advance,
    build_catalog,
    initial_state,
    render,
    reset_state,
)
from .models import LabCase, LabPartition


class LabSession:
    """Official-shaped session with no public evaluator or oracle surface."""

    __slots__ = (
        "__actions",
        "__closed",
        "__closed_scorecard",
        "__observation",
        "__resets",
        "__spec",
        "__state",
    )

    def __init__(self, spec: _EpisodeSpec) -> None:
        self.__spec = spec
        self.__state = initial_state(spec)
        self.__actions = 0
        self.__resets = 0
        self.__closed = False
        self.__closed_scorecard: ScoreSummary | None = None
        self.__observation = self.__make_observation(
            full_reset=True,
            returned_action=ActionRequest(ActionName.RESET),
        )

    def __make_observation(
        self, *, full_reset: bool, returned_action: ActionRequest
    ) -> Observation:
        available = (
            self.__spec.available_actions
            if self.__state.terminal is GameStateName.NOT_FINISHED
            else ()
        )
        return Observation(
            game_id=GameId(self.__spec.case.case_id),
            frames=(render(self.__spec, self.__state),),
            state=self.__state.terminal,
            levels_completed=1 if self.__state.terminal is GameStateName.WIN else 0,
            win_levels=1,
            available_actions=available,
            full_reset=full_reset,
            returned_action=returned_action,
            upstream_metadata=(("step", self.__state.steps), ("attempt", self.__resets)),
        )

    @property
    def observation(self) -> Observation:
        return self.__observation

    def __ensure_open(self) -> None:
        if self.__closed:
            raise EnvironmentStateError("laboratory environment session is closed")

    def step(
        self,
        action: ActionRequest,
        *,
        reasoning: Mapping[str, JSONValue] | None = None,
    ) -> Observation:
        del reasoning
        self.__ensure_open()
        validate_action_request(self.__observation, action)
        if action.name is ActionName.RESET:
            return self.reset()
        self.__state = advance(self.__spec, self.__state, action).state
        self.__actions += 1
        self.__observation = self.__make_observation(
            full_reset=False,
            returned_action=action,
        )
        return self.__observation

    def reset(self) -> Observation:
        self.__ensure_open()
        self.__state = reset_state(self.__spec, self.__state)
        self.__resets += 1
        self.__observation = self.__make_observation(
            full_reset=True,
            returned_action=ActionRequest(ActionName.RESET),
        )
        return self.__observation

    def __score_summary(self) -> ScoreSummary:
        completed = self.__state.terminal is GameStateName.WIN
        score = 1.0 if completed else 0.0
        return ScoreSummary(
            surface=EvaluationSurface.SYNTHETIC,
            verified=True,
            scorer="arc3.lab.exact.v1",
            score=score,
            runs=(
                ScoreRunSummary(
                    game_id=GameId(self.__spec.case.case_id),
                    score=score,
                    levels_completed=int(completed),
                    actions=self.__actions,
                    resets=self.__resets,
                    state=self.__state.terminal,
                    completed=completed,
                    level_scores=(score,),
                    level_actions=(self.__actions,),
                    level_baseline_actions=(),
                ),
            ),
        )

    def scorecard(self) -> ScoreSummary:
        if self.__closed_scorecard is not None:
            return self.__closed_scorecard
        return self.__score_summary()

    def close(self) -> ScoreSummary:
        if self.__closed_scorecard is None:
            self.__closed_scorecard = self.__score_summary()
        self.__closed = True
        return self.__closed_scorecard


class LabAdapter:
    """Generate opaque procedural cases for production-policy evaluation."""

    def __init__(
        self,
        *,
        partition: LabPartition = LabPartition.DEVELOPMENT,
        root_seed: int = 0,
        count: int = 15,
    ) -> None:
        self.__partition = LabPartition(partition)
        self.__catalog = build_catalog(self.__partition, root_seed=root_seed, count=count)
        self.__specs = {case.case_id: spec for case, spec in self.__catalog}

    def cases(self) -> tuple[LabCase, ...]:
        """Return identities and seeds, never their evaluator annotations."""

        return tuple(case for case, _spec in self.__catalog)

    def list_games(self) -> tuple[EnvironmentDescriptor, ...]:
        return tuple(
            EnvironmentDescriptor(
                game_id=GameId(case.case_id),
                title="Procedural synthetic episode",
                tags=("synthetic", "procedural"),
                locally_available=True,
            )
            for case, _spec in self.__catalog
        )

    def open(self, game_id: str, *, seed: int | None = None) -> LabSession:
        """Open a fixed catalog case; per-open seed changes are intentionally forbidden."""

        if seed is not None:
            raise AdapterError("laboratory cases have catalog-fixed seeds")
        try:
            spec = self.__specs[game_id]
        except KeyError as error:
            raise AdapterError(f"unknown laboratory environment {game_id!r}") from error
        return LabSession(spec)


__all__ = ["LabAdapter", "LabSession"]
