"""Small deterministic environment for the hidden progressive curriculum."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace

from arc3.adapters import (
    GridFrame,
    Observation,
    ScoreRunSummary,
    ScoreSummary,
    validate_action_request,
)
from arc3.types import (
    ActionName,
    ActionRequest,
    EvaluationSurface,
    GameId,
    GameStateName,
    JSONValue,
)

from .generator import BOARD_MAX, BOARD_MIN
from .models import (
    CurriculumFamily,
    CurriculumSpec,
    CurriculumState,
    LevelSpec,
    LevelState,
    Point,
    TransitionTruth,
)

MOVES: dict[ActionName, Point] = {
    ActionName.ACTION1: (0, -1),
    ActionName.ACTION2: (0, 1),
    ActionName.ACTION3: (-1, 0),
    ActionName.ACTION4: (1, 0),
}
AVAILABLE_ACTIONS = (*MOVES, ActionName.ACTION5)

# Semantic roles are stable; the per-level color assigned to each role is not.
_PLAYER = 1
_GOAL = 2
_WALL = 3
_RESTORER = 4
_ONE_SHOT = 5
_SWITCH = 6
_CLOSED_GATE = 7
_OPEN_GATE = 8
_PUSHABLE = 9
_PUSHABLE_GOAL = 10
_TERRAIN = 11
_TRIGGER = 12
_DECORATION_A = 13
_DECORATION_B = 14
_HUD_ON = 15


def initial_level_state(spec: LevelSpec) -> LevelState:
    """Construct a fresh exact state for one level."""

    return LevelState(
        player=spec.start,
        resource=spec.resource_start,
        pushable=spec.pushable_start,
    )


def initial_curriculum_state(spec: CurriculumSpec) -> CurriculumState:
    """Construct a fresh exact state for the complete sequence."""

    return CurriculumState(level_index=0, level=initial_level_state(spec.levels[0]))


def _inside(point: Point) -> bool:
    return all(BOARD_MIN <= value <= BOARD_MAX for value in point)


def _add(left: Point, right: Point) -> Point:
    return left[0] + right[0], left[1] + right[1]


def _blocked(spec: LevelSpec, state: LevelState, point: Point) -> bool:
    return not _inside(point) or point in spec.walls or (point == spec.gate and not state.gate_open)


def _is_complete(spec: LevelSpec, state: LevelState) -> bool:
    if spec.family is CurriculumFamily.PUSHING:
        return state.pushable == spec.pushable_goal
    if spec.family is CurriculumFamily.HELD_OUT_COMPOSITION:
        return state.pushable == spec.pushable_goal and state.player == spec.goal
    return state.player == spec.goal


def advance_level(
    spec: LevelSpec,
    state: LevelState,
    action: ActionRequest,
) -> tuple[LevelState, tuple[str, ...]]:
    """Apply one action to a nonterminal evaluator state."""

    if state.terminal is not GameStateName.NOT_FINISHED:
        raise ValueError("advance_level requires a nonterminal level state")
    if action.coordinate is not None or action.name not in AVAILABLE_ACTIONS:
        raise ValueError("curriculum accepts only coordinate-free ACTION1 through ACTION5")

    effects: list[str] = []
    player = state.player
    pushable = state.pushable
    gate_open = state.gate_open
    delayed_remaining = state.delayed_remaining
    consumed = state.consumed_one_shot

    if delayed_remaining is not None and delayed_remaining > 0:
        delayed_remaining -= 1
        effects.append("delay-tick")
        if delayed_remaining == 0:
            gate_open = True
            effects.append("gate-open-delayed")

    if action.name in MOVES:
        target = _add(player, MOVES[action.name])
        if target == pushable:
            pushed_target = _add(target, MOVES[action.name])
            push_state = replace(state, gate_open=gate_open)
            if (
                _blocked(spec, push_state, pushed_target)
                or pushed_target == pushable
                or pushed_target == player
            ):
                effects.append("push-blocked")
            else:
                player = target
                pushable = pushed_target
                effects.extend(("move", "push"))
        elif _blocked(spec, replace(state, gate_open=gate_open), target):
            effects.append("move-blocked")
        else:
            player = target
            effects.append("move")
    elif action.name is ActionName.ACTION5:
        effects.append("interact")
        if player == spec.switch and not gate_open:
            gate_open = True
            effects.append("gate-open-switch")

    if player == spec.delayed_trigger and delayed_remaining is None and not gate_open:
        delayed_remaining = spec.delayed_actions
        effects.append("delay-armed")

    cost = spec.base_cost + (spec.terrain_extra_cost if player in spec.terrain else 0)
    resource = state.resource - cost
    if player in spec.one_shot_restorers and player not in consumed:
        consumed = consumed | {player}
        resource = min(spec.resource_cap, resource + spec.restoration_amount)
        effects.append("restore-one-shot")
    if player in spec.reusable_restorers:
        resource = min(spec.resource_cap, resource + spec.restoration_amount)
        effects.append("restore-reusable")

    next_state = LevelState(
        player=player,
        resource=resource,
        pushable=pushable,
        consumed_one_shot=consumed,
        gate_open=gate_open,
        delayed_remaining=delayed_remaining,
        animation_phase=(state.animation_phase + 1) % 4,
        steps=state.steps + 1,
    )
    if _is_complete(spec, next_state):
        effects.append("level-complete")
        next_state = replace(next_state, terminal=GameStateName.WIN)
    elif resource <= 0 or next_state.steps >= spec.max_steps:
        effects.append("game-over")
        next_state = replace(next_state, terminal=GameStateName.GAME_OVER)
    return next_state, tuple(effects)


def _paint(rows: list[list[int]], spec: LevelSpec, point: Point, role: int) -> None:
    rows[point[1]][point[0]] = spec.palette[role - 1]


def render_level(spec: LevelSpec, state: LevelState) -> GridFrame:
    """Render only public pixels, including a visual resource gauge."""

    rows = [[0 for _ in range(spec.size)] for _ in range(spec.size)]
    for bit in range(5):
        if state.resource & (1 << bit):
            _paint(rows, spec, (bit, 0), _HUD_ON)
    for index, point in enumerate(sorted(spec.decorations)):
        role = _DECORATION_A if (index + state.animation_phase) % 2 == 0 else _DECORATION_B
        _paint(rows, spec, point, role)
    for point in spec.terrain:
        _paint(rows, spec, point, _TERRAIN)
    for point in spec.reusable_restorers:
        _paint(rows, spec, point, _RESTORER)
    for point in spec.one_shot_restorers - state.consumed_one_shot:
        _paint(rows, spec, point, _ONE_SHOT)
    if spec.delayed_trigger is not None:
        _paint(rows, spec, spec.delayed_trigger, _TRIGGER)
    if spec.switch is not None:
        _paint(rows, spec, spec.switch, _SWITCH)
    _paint(rows, spec, spec.goal, _GOAL)
    if spec.pushable_goal is not None:
        _paint(rows, spec, spec.pushable_goal, _PUSHABLE_GOAL)
    for point in spec.walls:
        _paint(rows, spec, point, _WALL)
    if spec.gate is not None:
        _paint(rows, spec, spec.gate, _OPEN_GATE if state.gate_open else _CLOSED_GATE)
    if state.pushable is not None:
        _paint(rows, spec, state.pushable, _PUSHABLE)
    _paint(rows, spec, state.player, _PLAYER)
    return GridFrame.from_rows(rows)


class CurriculumSession:
    """Normalized session whose private state never crosses the observation boundary."""

    def __init__(self, spec: CurriculumSpec) -> None:
        self._spec = spec
        self._state = initial_curriculum_state(spec)
        self._actions = 0
        self._resets = 0
        self._level_actions: list[int] = []
        self._current_level_actions = 0
        self._attempt = 0
        self._closed = False
        self._last_action: ActionRequest | None = None
        self._last_full_reset = False

    @property
    def exact_state(self) -> CurriculumState:
        """Evaluator-only state for oracle verification; never serialize to the worker."""

        return self._state

    @property
    def observation(self) -> Observation:
        level_spec = self._spec.levels[self._state.level_index]
        available = (
            ()
            if self._state.terminal in {GameStateName.WIN, GameStateName.GAME_OVER}
            else AVAILABLE_ACTIONS
        )
        if self._state.terminal is GameStateName.GAME_OVER:
            available = (ActionName.RESET,)
        return Observation(
            game_id=GameId(self._spec.case.case_id),
            frames=(render_level(level_spec, self._state.level),),
            state=self._state.terminal,
            levels_completed=self._state.levels_completed,
            win_levels=len(self._spec.levels),
            available_actions=tuple(available),
            full_reset=self._last_full_reset,
            returned_action=self._last_action,
            upstream_metadata=(("attempt", self._attempt), ("step", self._actions)),
        )

    def step(
        self,
        action: ActionRequest,
        *,
        reasoning: Mapping[str, JSONValue] | None = None,
    ) -> Observation:
        del reasoning
        if self._closed:
            raise ValueError("curriculum session is closed")
        validate_action_request(self.observation, action)
        if action.name is ActionName.RESET:
            return self.reset()
        level_index = self._state.level_index
        level_spec = self._spec.levels[level_index]
        level_state, _ = advance_level(level_spec, self._state.level, action)
        self._actions += 1
        self._current_level_actions += 1
        self._last_action = action
        self._last_full_reset = False
        if level_state.terminal is GameStateName.WIN:
            self._level_actions.append(self._current_level_actions)
            completed = level_index + 1
            if completed == len(self._spec.levels):
                self._state = CurriculumState(
                    level_index=level_index,
                    level=level_state,
                    levels_completed=completed,
                    terminal=GameStateName.WIN,
                )
            else:
                next_index = level_index + 1
                self._current_level_actions = 0
                self._state = CurriculumState(
                    level_index=next_index,
                    level=initial_level_state(self._spec.levels[next_index]),
                    levels_completed=completed,
                    terminal=GameStateName.NOT_FINISHED,
                )
        else:
            self._state = CurriculumState(
                level_index=level_index,
                level=level_state,
                levels_completed=self._state.levels_completed,
                terminal=level_state.terminal,
            )
        return self.observation

    def reset(self) -> Observation:
        if self._closed:
            raise ValueError("curriculum session is closed")
        self._resets += 1
        self._attempt += 1
        self._state = initial_curriculum_state(self._spec)
        self._level_actions = []
        self._current_level_actions = 0
        self._last_action = ActionRequest(ActionName.RESET)
        self._last_full_reset = True
        return self.observation

    def scorecard(self) -> ScoreSummary:
        run = ScoreRunSummary(
            game_id=GameId(self._spec.case.case_id),
            score=float(self._state.levels_completed),
            levels_completed=self._state.levels_completed,
            actions=self._actions,
            resets=self._resets,
            state=self._state.terminal,
            completed=self._state.terminal is GameStateName.WIN,
            level_scores=tuple(1.0 for _ in self._level_actions),
            level_actions=tuple(self._level_actions),
        )
        return ScoreSummary(
            surface=EvaluationSurface.SYNTHETIC,
            verified=True,
            scorer="arc3-build003-curriculum-v0.1",
            score=run.score,
            runs=(run,),
        )

    def close(self) -> ScoreSummary:
        self._closed = True
        return self.scorecard()


def transition_truth(
    spec: CurriculumSpec,
    before: CurriculumState,
    action: ActionRequest,
) -> TransitionTruth:
    """Return an evaluator annotation without mutating a session."""

    level, effects = advance_level(spec.levels[before.level_index], before.level, action)
    completed = level.terminal is GameStateName.WIN
    won = completed and before.level_index + 1 == len(spec.levels)
    return TransitionTruth(
        action=action,
        family=spec.levels[before.level_index].family,
        level_index_before=before.level_index,
        level_index_after=before.level_index + int(completed and not won),
        effects=effects,
        level_completed=completed,
        game_won=won,
        game_over=level.terminal is GameStateName.GAME_OVER,
    )


__all__ = [
    "AVAILABLE_ACTIONS",
    "MOVES",
    "CurriculumSession",
    "advance_level",
    "initial_curriculum_state",
    "initial_level_state",
    "render_level",
    "transition_truth",
]
