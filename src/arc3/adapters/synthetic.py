"""Small deterministic environment for adapter and controller integration tests."""

from __future__ import annotations

from collections.abc import Mapping

from arc3.adapters import (
    EnvironmentDescriptor,
    EnvironmentSession,
    GridFrame,
    Observation,
    ScoreRunSummary,
    ScoreSummary,
    validate_action_request,
)
from arc3.errors import AdapterError, ConfigurationError, EnvironmentStateError
from arc3.types import (
    ActionName,
    ActionRequest,
    EvaluationSurface,
    GameId,
    GameStateName,
    JSONValue,
)

SYNTHETIC_GAME_ID = "synthetic-grid-v1"
_MOVEMENT_ACTIONS = (
    ActionName.ACTION1,
    ActionName.ACTION2,
    ActionName.ACTION3,
    ActionName.ACTION4,
)


class SyntheticSession(EnvironmentSession):
    """Deterministic bounded grid walk with no textual goal leakage."""

    def __init__(self, *, seed: int, size: int, max_steps: int) -> None:
        self._seed = seed
        self._size = size
        self._max_steps = max_steps
        self._start, self._target = self._positions(seed)
        self._agent = self._start
        self._actions = 0
        self._actions_since_reset = 0
        self._resets = 0
        self._state = GameStateName.NOT_FINISHED
        self._closed = False
        self._closed_scorecard: ScoreSummary | None = None
        self._observation = self._make_observation(
            full_reset=True,
            returned_action=ActionRequest(ActionName.RESET),
        )

    def _positions(self, seed: int) -> tuple[tuple[int, int], tuple[int, int]]:
        unsigned = seed % (2**64)
        start = (unsigned % self._size, (unsigned // self._size) % self._size)
        target = (
            (unsigned * 3 + 1) % self._size,
            (unsigned * 5 + 2) % self._size,
        )
        if target == start:
            target = ((target[0] + 1) % self._size, target[1])
        return start, target

    def _frame(self) -> GridFrame:
        rows = [[0 for _ in range(self._size)] for _ in range(self._size)]
        target_x, target_y = self._target
        agent_x, agent_y = self._agent
        rows[target_y][target_x] = 2
        rows[agent_y][agent_x] = 1
        return GridFrame.from_rows(rows)

    def _make_observation(
        self,
        *,
        full_reset: bool,
        returned_action: ActionRequest,
    ) -> Observation:
        actions = _MOVEMENT_ACTIONS if self._state is GameStateName.NOT_FINISHED else ()
        return Observation(
            game_id=GameId(SYNTHETIC_GAME_ID),
            frames=(self._frame(),),
            state=self._state,
            levels_completed=1 if self._state is GameStateName.WIN else 0,
            win_levels=1,
            available_actions=actions,
            full_reset=full_reset,
            returned_action=returned_action,
            upstream_metadata=(("seed", self._seed), ("step", self._actions)),
        )

    @property
    def observation(self) -> Observation:
        return self._observation

    def _ensure_open(self) -> None:
        if self._closed:
            raise EnvironmentStateError("synthetic environment session is closed")

    def step(
        self,
        action: ActionRequest,
        *,
        reasoning: Mapping[str, JSONValue] | None = None,
    ) -> Observation:
        del reasoning
        self._ensure_open()
        validate_action_request(self._observation, action)
        if action.name is ActionName.RESET:
            return self.reset()

        x, y = self._agent
        if action.name is ActionName.ACTION1:
            y = max(0, y - 1)
        elif action.name is ActionName.ACTION2:
            y = min(self._size - 1, y + 1)
        elif action.name is ActionName.ACTION3:
            x = max(0, x - 1)
        elif action.name is ActionName.ACTION4:
            x = min(self._size - 1, x + 1)
        else:  # validation prevents this branch
            raise AdapterError(f"unsupported synthetic action {action.name.value}")

        self._agent = (x, y)
        self._actions += 1
        self._actions_since_reset += 1
        if self._agent == self._target:
            self._state = GameStateName.WIN
        elif self._actions_since_reset >= self._max_steps:
            self._state = GameStateName.GAME_OVER
        self._observation = self._make_observation(full_reset=False, returned_action=action)
        return self._observation

    def reset(self) -> Observation:
        self._ensure_open()
        self._agent = self._start
        self._actions_since_reset = 0
        self._resets += 1
        self._state = GameStateName.NOT_FINISHED
        self._observation = self._make_observation(
            full_reset=True,
            returned_action=ActionRequest(ActionName.RESET),
        )
        return self._observation

    def _score_summary(self) -> ScoreSummary:
        completed = self._state is GameStateName.WIN
        score = 1.0 if completed else 0.0
        return ScoreSummary(
            surface=EvaluationSurface.SYNTHETIC,
            verified=True,
            scorer="arc3.synthetic.v1",
            score=score,
            runs=(
                ScoreRunSummary(
                    game_id=GameId(SYNTHETIC_GAME_ID),
                    score=score,
                    levels_completed=1 if completed else 0,
                    actions=self._actions,
                    resets=self._resets,
                    state=self._state,
                    completed=completed,
                    level_scores=(score,),
                    level_actions=(self._actions,),
                    level_baseline_actions=(),
                ),
            ),
        )

    def scorecard(self) -> ScoreSummary:
        if self._closed and self._closed_scorecard is not None:
            return self._closed_scorecard
        return self._score_summary()

    def close(self) -> ScoreSummary:
        if self._closed_scorecard is None:
            self._closed_scorecard = self._score_summary()
        self._closed = True
        return self._closed_scorecard


class SyntheticAdapter:
    """Construct deterministic synthetic sessions with an official-like lifecycle."""

    def __init__(self, *, seed: int = 0, size: int = 8, max_steps: int = 64) -> None:
        if isinstance(seed, bool) or not -(2**63) <= seed < 2**63:
            raise ConfigurationError("seed must be a signed 64-bit integer")
        if isinstance(size, bool) or not isinstance(size, int) or not 3 <= size <= 64:
            raise ConfigurationError("synthetic grid size must be within 3..64")
        if isinstance(max_steps, bool) or not isinstance(max_steps, int) or max_steps <= 0:
            raise ConfigurationError("synthetic max_steps must be a positive integer")
        self._seed = seed
        self._size = size
        self._max_steps = max_steps

    def list_games(self) -> tuple[EnvironmentDescriptor, ...]:
        return (
            EnvironmentDescriptor(
                game_id=GameId(SYNTHETIC_GAME_ID),
                title="Deterministic synthetic grid",
                tags=("synthetic", "deterministic"),
                baseline_actions=(),
                locally_available=True,
            ),
        )

    def open(self, game_id: str, *, seed: int | None = None) -> SyntheticSession:
        if game_id != SYNTHETIC_GAME_ID:
            raise AdapterError(f"unknown synthetic environment {game_id!r}")
        selected_seed = self._seed if seed is None else seed
        if isinstance(selected_seed, bool) or not -(2**63) <= selected_seed < 2**63:
            raise ConfigurationError("seed must be a signed 64-bit integer")
        return SyntheticSession(
            seed=selected_seed,
            size=self._size,
            max_steps=self._max_steps,
        )


__all__ = ["SYNTHETIC_GAME_ID", "SyntheticAdapter", "SyntheticSession"]
