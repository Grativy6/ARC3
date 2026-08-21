"""Generic synthetic transformations used only for Stage 16 robustness tests."""

from __future__ import annotations

from enum import StrEnum

from arc3.adapters import (
    GridFrame,
    Observation,
    ScoreRunSummary,
    ScoreSummary,
    validate_action_request,
)
from arc3.adapters.synthetic import SYNTHETIC_GAME_ID, SyntheticAdapter, SyntheticSession
from arc3.types import (
    ActionName,
    ActionRequest,
    Coordinate,
    EvaluationSurface,
    GameId,
    GameStateName,
)

COMPONENT_STRESS_GAME_ID = "synthetic-stage16-component-stress"


class RobustnessVariant(StrEnum):
    """Predeclared, game-independent synthetic robustness axes."""

    BASE = "base"
    PALETTE = "palette"
    TRANSLATION = "translation"
    DISTRACTOR = "distractor"
    ACTION_REMAP = "action-remap"
    RULE_CHANGE = "rule-change"


_IDENTITY_ACTIONS: dict[ActionName, ActionName] = {
    ActionName.ACTION1: ActionName.ACTION1,
    ActionName.ACTION2: ActionName.ACTION2,
    ActionName.ACTION3: ActionName.ACTION3,
    ActionName.ACTION4: ActionName.ACTION4,
}
_ROTATED_ACTIONS: dict[ActionName, ActionName] = {
    ActionName.ACTION1: ActionName.ACTION4,
    ActionName.ACTION2: ActionName.ACTION3,
    ActionName.ACTION3: ActionName.ACTION2,
    ActionName.ACTION4: ActionName.ACTION1,
}


class TransformedSyntheticSession:
    """Observation-only metamorphisms around the generic synthetic adapter.

    The controller receives no variant label or evaluator truth. Action remaps
    translate only at the environment boundary and preserve returned-action
    identity from the controller's perspective.
    """

    def __init__(
        self,
        *,
        seed: int,
        size: int,
        max_steps: int,
        variant: RobustnessVariant | str,
        rule_change_step: int = 3,
    ) -> None:
        self.variant = RobustnessVariant(variant)
        self._session: SyntheticSession = SyntheticAdapter(
            seed=seed,
            size=size,
            max_steps=max_steps,
        ).open(SYNTHETIC_GAME_ID)
        self._submitted_actions = 0
        self._rule_change_step = rule_change_step
        self._observation = self._transform(self._session.observation, returned_action=None)

    @property
    def observation(self) -> Observation:
        return self._observation

    def _mapping(self) -> dict[ActionName, ActionName]:
        if self.variant is RobustnessVariant.ACTION_REMAP:
            return _ROTATED_ACTIONS
        if (
            self.variant is RobustnessVariant.RULE_CHANGE
            and self._submitted_actions >= self._rule_change_step
        ):
            return _ROTATED_ACTIONS
        return _IDENTITY_ACTIONS

    def _frame(self, frame: GridFrame) -> GridFrame:
        palette = (
            {0: 0, 1: 7, 2: 12}
            if self.variant is RobustnessVariant.PALETTE
            else {value: value for value in frame.palette}
        )
        shift_x = 2 if self.variant is RobustnessVariant.TRANSLATION else 0
        shift_y = 3 if self.variant is RobustnessVariant.TRANSLATION else 0
        width = frame.width + shift_x
        height = frame.height + shift_y
        rows = [[0 for _ in range(width)] for _ in range(height)]
        for y, row in enumerate(frame.cells):
            for x, value in enumerate(row):
                rows[y + shift_y][x + shift_x] = palette.get(value, value)
        if self.variant is RobustnessVariant.DISTRACTOR:
            rows[0][0] = 3
            rows[height - 1][width - 1] = 4
        return GridFrame.from_rows(rows)

    def _transform(
        self,
        observation: Observation,
        *,
        returned_action: ActionRequest | None,
    ) -> Observation:
        mapping = self._mapping()
        inverse = {internal: external for external, internal in mapping.items()}
        available = tuple(inverse.get(action, action) for action in observation.available_actions)
        return Observation(
            game_id=observation.game_id,
            frames=tuple(self._frame(frame) for frame in observation.frames),
            state=observation.state,
            levels_completed=observation.levels_completed,
            win_levels=observation.win_levels,
            available_actions=available,
            full_reset=observation.full_reset,
            returned_action=returned_action,
            upstream_session_id=observation.upstream_session_id,
            upstream_metadata=observation.upstream_metadata,
        )

    def step(self, action: ActionRequest) -> Observation:
        validate_action_request(self._observation, action)
        mapping = self._mapping()
        if action.name is ActionName.RESET:
            returned = self._session.reset()
        else:
            internal = ActionRequest(
                mapping.get(action.name, action.name),
                Coordinate(action.coordinate.x, action.coordinate.y)
                if action.coordinate is not None
                else None,
            )
            returned = self._session.step(internal)
            self._submitted_actions += 1
        self._observation = self._transform(returned, returned_action=action)
        return self._observation

    def close(self) -> ScoreSummary:
        return self._session.close()


class ManyComponentStressSession:
    """A forced-length maximum-frame fixture with many separated components.

    This fixture deliberately has no win transition. It measures the declared
    action budget instead of accidentally terminating on the navigation toy.
    """

    def __init__(self, *, size: int, component_count: int) -> None:
        if not 3 <= size <= 64:
            raise ValueError("stress fixture size must be within 3..64")
        capacity = (size // 2) ** 2
        if not 1 <= component_count <= capacity:
            raise ValueError("stress fixture component_count exceeds separated-cell capacity")
        self._size = size
        self._component_count = component_count
        self._actions = 0
        self._resets = 0
        self._closed = False
        self._cells = self._initial_cells()
        self._observation = self._make_observation(returned_action=None, full_reset=False)

    @property
    def observation(self) -> Observation:
        return self._observation

    def _initial_cells(self) -> list[list[int]]:
        rows = [[0 for _ in range(self._size)] for _ in range(self._size)]
        for index in range(self._component_count):
            x = 1 + 2 * (index % (self._size // 2))
            y = 1 + 2 * (index // (self._size // 2))
            rows[y][x] = 1 + index % 15
        return rows

    def _make_observation(
        self,
        *,
        returned_action: ActionRequest | None,
        full_reset: bool,
    ) -> Observation:
        return Observation(
            game_id=GameId(COMPONENT_STRESS_GAME_ID),
            frames=(GridFrame.from_rows(self._cells),),
            state=GameStateName.NOT_FINISHED,
            levels_completed=0,
            win_levels=1,
            available_actions=(
                ActionName.ACTION1,
                ActionName.ACTION2,
                ActionName.ACTION3,
                ActionName.ACTION4,
            ),
            full_reset=full_reset,
            returned_action=returned_action,
        )

    def step(self, action: ActionRequest) -> Observation:
        if self._closed:
            raise RuntimeError("stress fixture session is closed")
        validate_action_request(self._observation, action)
        if action.name is ActionName.RESET:
            self._resets += 1
            self._cells = self._initial_cells()
            self._observation = self._make_observation(
                returned_action=action,
                full_reset=True,
            )
            return self._observation
        index = self._actions % self._component_count
        x = 1 + 2 * (index % (self._size // 2))
        y = 1 + 2 * (index // (self._size // 2))
        action_offset = int(action.name.value.removeprefix("ACTION"))
        self._cells[y][x] = 1 + (self._cells[y][x] - 1 + action_offset) % 15
        self._actions += 1
        self._observation = self._make_observation(
            returned_action=action,
            full_reset=False,
        )
        return self._observation

    def close(self) -> ScoreSummary:
        self._closed = True
        run = ScoreRunSummary(
            game_id=GameId(COMPONENT_STRESS_GAME_ID),
            score=0.0,
            levels_completed=0,
            actions=self._actions,
            resets=self._resets,
            state=GameStateName.NOT_FINISHED,
            completed=False,
            level_scores=(0.0,),
            level_actions=(self._actions,),
        )
        return ScoreSummary(
            surface=EvaluationSurface.SYNTHETIC,
            verified=True,
            scorer="arc3.stage16.component-stress.v0.1",
            score=0.0,
            runs=(run,),
        )


__all__ = [
    "COMPONENT_STRESS_GAME_ID",
    "ManyComponentStressSession",
    "RobustnessVariant",
    "TransformedSyntheticSession",
]
