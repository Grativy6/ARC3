"""Private deterministic generator and transition engine for the ARC3 lab."""

from __future__ import annotations

import hashlib
import random
from collections import deque
from dataclasses import dataclass, replace

from arc3.adapters import GridFrame
from arc3.types import ActionName, ActionRequest, Coordinate, GameStateName

from .models import LabCase, LabPartition, RuleFamily

_DIRECTIONS = ("north", "south", "west", "east")
_SEMANTICS = (*_DIRECTIONS, "interact")
_ACTION_LABELS = (
    ActionName.ACTION1,
    ActionName.ACTION2,
    ActionName.ACTION3,
    ActionName.ACTION4,
    ActionName.ACTION5,
)
_DEVELOPMENT_FAMILIES = tuple(RuleFamily)[:12]
_HELD_OUT_FAMILIES = tuple(RuleFamily)[12:]
_SHAPES = (
    ((0, 0),),
    ((0, 0), (1, 0)),
    ((0, 0), (0, 1)),
    ((0, 0), (1, 0), (0, 1)),
    ((0, 0), (1, 0), (1, 1)),
    ((0, 0), (1, 0), (0, 1), (1, 1)),
)


@dataclass(frozen=True, slots=True)
class _EpisodeSpec:
    case: LabCase
    family: RuleFamily
    size: int
    palette: tuple[int, ...]
    player_shape: tuple[tuple[int, int], ...]
    target_shape: tuple[tuple[int, int], ...]
    start: tuple[int, int]
    target: tuple[int, int]
    secondary: tuple[int, int]
    switch: tuple[int, int]
    key: tuple[int, int]
    door: tuple[int, int]
    walls: frozenset[tuple[int, int]]
    distractors: tuple[tuple[int, int], ...]
    action_map: tuple[tuple[ActionName, str], ...]
    reversible: bool
    max_steps: int

    @property
    def available_actions(self) -> tuple[ActionName, ...]:
        actions = list(_ACTION_LABELS)
        if self.family in {
            RuleFamily.COORDINATE_UNKNOWN_TARGET,
            RuleFamily.COLOR_SHAPE_MATCHING,
            RuleFamily.MULTIPLE_COMPATIBLE_MODELS,
            RuleFamily.GAME_OVER_RESET_RECOVERY,
        }:
            actions.append(ActionName.ACTION6)
        if self.family is RuleFamily.REVERSIBLE_IRREVERSIBLE:
            actions.append(ActionName.ACTION7)
        return tuple(actions)


@dataclass(frozen=True, slots=True)
class _WorldState:
    player: tuple[int, int]
    phase: int = 0
    counter: int = 0
    has_key: bool = False
    door_open: bool = False
    reversible_open: bool = False
    recovered: bool = False
    stage: int = 0
    terminal: GameStateName = GameStateName.NOT_FINISHED
    steps: int = 0


@dataclass(frozen=True, slots=True)
class _Transition:
    state: _WorldState
    effects: tuple[str, ...]
    contradiction: bool = False


def _derived_seed(root_seed: int, label: str, ordinal: int) -> int:
    material = f"arc3.lab.v1\0{root_seed}\0{label}\0{ordinal}".encode()
    return int.from_bytes(hashlib.sha256(material).digest()[:8], "big", signed=True)


def build_catalog(
    partition: LabPartition, *, root_seed: int, count: int
) -> tuple[tuple[LabCase, _EpisodeSpec], ...]:
    """Build a deterministic opaque catalog for one predeclared partition."""

    if isinstance(root_seed, bool) or not -(2**63) <= root_seed < 2**63:
        raise ValueError("root_seed must be a signed 64-bit integer")
    if isinstance(count, bool) or count <= 0:
        raise ValueError("count must be a positive integer")
    families = (
        _HELD_OUT_FAMILIES if partition is LabPartition.HELD_OUT_FAMILIES else _DEVELOPMENT_FAMILIES
    )
    offset = _derived_seed(root_seed, partition.value, 0) % len(families)
    built: list[tuple[LabCase, _EpisodeSpec]] = []
    for ordinal in range(count):
        family = families[(offset + ordinal) % len(families)]
        seed = _derived_seed(root_seed, partition.value, ordinal + 1)
        opaque = hashlib.sha256(
            f"arc3.lab.case.v1\0{partition.value}\0{seed}\0{ordinal}".encode()
        ).hexdigest()[:16]
        case = LabCase(
            case_id=f"synthetic-lab-v1-{ordinal:04d}-{opaque}",
            partition=partition,
            seed=seed,
        )
        built.append((case, _generate_spec(case, family)))
    return tuple(built)


def _generate_spec(case: LabCase, family: RuleFamily) -> _EpisodeSpec:
    rng = random.Random(case.seed)
    held_combo = case.partition is not LabPartition.DEVELOPMENT
    size = rng.choice((9, 10) if held_combo else (7, 8))
    wall_x = rng.randint(2, size - 3)
    palette = tuple(rng.sample(range(1, 16), 9))
    shape_domain = range(3, len(_SHAPES)) if held_combo else range(3)
    player_shape = _SHAPES[rng.choice(shape_domain)]
    target_shape = _SHAPES[rng.choice(shape_domain)]
    anchors = [(x, y) for y in range(1, size - 2, 2) for x in range(1, size - 2, 2)]
    rng.shuffle(anchors)
    while len(anchors) < 6:
        anchors.append((rng.randrange(1, size - 1), rng.randrange(1, size - 1)))
    start, target, secondary, switch, key, door = anchors[:6]
    if family in {
        RuleFamily.CYCLIC_TIMING,
        RuleFamily.DELAYED_REWARD,
        RuleFamily.MULTIPLE_COMPATIBLE_MODELS,
    }:
        target = start
    if family is RuleFamily.FALSE_INITIAL_HYPOTHESIS:
        start = (1, 0)
    if family is RuleFamily.CONDITIONAL_TRAVERSAL:
        start = (1, 1)
        target = (size - 2, size - 2)
        switch = (1, size - 2)
        door = (wall_x, size // 2)
    if family is RuleFamily.REVERSIBLE_IRREVERSIBLE:
        start = (1, 1)
        target = (size - 2, size - 2)
    distractor_count = rng.randint(3, 5) if held_combo else rng.randint(0, 2)
    occupied = {start, target, secondary, switch, key, door}
    cells = [(x, y) for y in range(size) for x in range(size) if (x, y) not in occupied]
    rng.shuffle(cells)
    distractors = tuple(cells[:distractor_count])
    walls = frozenset((wall_x, y) for y in range(size))
    labels = list(_ACTION_LABELS)
    rng.shuffle(labels)
    action_map = tuple(zip(labels, _SEMANTICS, strict=True))
    reversible = rng.choice((True, False)) if not held_combo else (case.seed % 2 == 0)
    return _EpisodeSpec(
        case=case,
        family=family,
        size=size,
        palette=palette,
        player_shape=player_shape,
        target_shape=target_shape,
        start=start,
        target=target,
        secondary=secondary,
        switch=switch,
        key=key,
        door=door,
        walls=walls,
        distractors=distractors,
        action_map=action_map,
        reversible=reversible,
        max_steps=size * size + 24,
    )


def initial_state(spec: _EpisodeSpec, *, recovered: bool = False) -> _WorldState:
    return _WorldState(player=spec.start, recovered=recovered)


def false_leading_action(spec: _EpisodeSpec) -> ActionName:
    """Return the label whose initially stable east effect later contradicts itself."""

    return next(action for action, semantic in spec.action_map if semantic == "east")


def _semantic(spec: _EpisodeSpec, state: _WorldState, action: ActionName) -> str:
    mapping = dict(spec.action_map)
    semantic = mapping.get(action, action.value.lower())
    if spec.family is RuleFamily.RULE_CHANGE_BETWEEN_LEVELS and state.stage == 1:
        rotation = {"north": "east", "east": "south", "south": "west", "west": "north"}
        semantic = rotation.get(semantic, semantic)
    if spec.family is RuleFamily.FALSE_INITIAL_HYPOTHESIS and action is false_leading_action(spec):
        return "west" if state.counter == 2 else "east"
    return semantic


def _move(
    spec: _EpisodeSpec, state: _WorldState, semantic: str
) -> tuple[tuple[int, int], tuple[str, ...]]:
    dx, dy = {
        "north": (0, -1),
        "south": (0, 1),
        "west": (-1, 0),
        "east": (1, 0),
    }[semantic]
    candidate = (
        min(spec.size - 1, max(0, state.player[0] + dx)),
        min(spec.size - 1, max(0, state.player[1] + dy)),
    )
    blocked = False
    if spec.family is RuleFamily.CONDITIONAL_TRAVERSAL:
        blocked = candidate in spec.walls and not state.door_open
    elif spec.family is RuleFamily.TOGGLE_DOOR_KEY:
        blocked = candidate == spec.door and not state.door_open
    elif spec.family is RuleFamily.REVERSIBLE_IRREVERSIBLE:
        blocked = candidate in spec.walls and not state.reversible_open
    if blocked:
        return state.player, ("collision",)
    if candidate == state.player:
        return state.player, ("boundary-no-op",)
    return candidate, ("translation",)


def advance(spec: _EpisodeSpec, state: _WorldState, action: ActionRequest) -> _Transition:
    """Apply one exact transition without mutating either input."""

    if state.terminal is not GameStateName.NOT_FINISHED:
        raise ValueError("cannot advance a terminal laboratory state")
    semantic = _semantic(spec, state, action.name)
    next_state = replace(state, steps=state.steps + 1)
    effects: list[str] = []
    contradiction = False

    if semantic in _DIRECTIONS:
        player, movement_effects = _move(spec, state, semantic)
        next_state = replace(next_state, player=player)
        effects.extend(movement_effects)
        if (
            spec.family is RuleFamily.FALSE_INITIAL_HYPOTHESIS
            and action.name is false_leading_action(spec)
        ):
            next_state = replace(next_state, counter=state.counter + 1)
            contradiction = state.counter == 2
    elif action.name is ActionName.ACTION6 and action.coordinate is not None:
        point = (action.coordinate.x, action.coordinate.y)
        effects.append("coordinate-probe")
        if spec.family is RuleFamily.COORDINATE_UNKNOWN_TARGET and point == spec.target:
            next_state = replace(next_state, terminal=GameStateName.WIN)
            effects.append("target-selected")
        elif spec.family is RuleFamily.COLOR_SHAPE_MATCHING and point == spec.secondary:
            next_state = replace(next_state, terminal=GameStateName.WIN)
            effects.append("matching-object-selected")
        elif (
            spec.family is RuleFamily.MULTIPLE_COMPATIBLE_MODELS
            and state.door_open
            and point == spec.target
        ):
            next_state = replace(next_state, terminal=GameStateName.WIN)
            effects.append("post-probe-target-selected")
        elif (
            spec.family is RuleFamily.GAME_OVER_RESET_RECOVERY
            and state.recovered
            and point == spec.target
        ):
            next_state = replace(next_state, terminal=GameStateName.WIN)
            effects.append("recovery-target-selected")
        else:
            effects.append("coordinate-no-op")
    elif action.name is ActionName.ACTION7:
        if (
            spec.family is RuleFamily.REVERSIBLE_IRREVERSIBLE
            and spec.reversible
            and state.reversible_open
        ):
            next_state = replace(next_state, reversible_open=False)
            effects.append("reversible-state-restored")
        else:
            effects.append("undo-no-op")
    elif semantic == "interact":
        if spec.family is RuleFamily.CONDITIONAL_TRAVERSAL and state.player == spec.switch:
            next_state = replace(next_state, door_open=True)
            effects.append("conditional-wall-opened")
        elif spec.family is RuleFamily.TOGGLE_DOOR_KEY and state.has_key:
            next_state = replace(next_state, door_open=not state.door_open)
            effects.append("door-toggled")
        elif spec.family is RuleFamily.CYCLIC_TIMING:
            phase = (state.phase + 1) % 3
            next_state = replace(next_state, phase=phase)
            effects.append("cycle-advanced")
            if phase == 0:
                next_state = replace(next_state, terminal=GameStateName.WIN)
                effects.append("timed-goal")
        elif spec.family is RuleFamily.REVERSIBLE_IRREVERSIBLE:
            bridge_open = not state.reversible_open if spec.reversible else True
            next_state = replace(next_state, reversible_open=bridge_open)
            effects.append("bridge-toggled" if spec.reversible else "bridge-opened-one-way")
        elif spec.family is RuleFamily.DELAYED_REWARD:
            counter = state.counter + 1
            next_state = replace(next_state, counter=counter)
            effects.append("latent-counter-advanced")
            if counter == 3:
                next_state = replace(next_state, terminal=GameStateName.WIN)
                effects.append("delayed-goal")
        elif spec.family is RuleFamily.MISLEADING_NOVELTY:
            next_state = replace(next_state, phase=(state.phase + 1) % 8)
            effects.append("novel-distractor-only")
        elif spec.family is RuleFamily.MULTIPLE_COMPATIBLE_MODELS:
            next_state = replace(next_state, door_open=True)
            effects.append("models-discriminated")
        elif spec.family is RuleFamily.GAME_OVER_RESET_RECOVERY and not state.recovered:
            next_state = replace(next_state, terminal=GameStateName.GAME_OVER)
            effects.append("irreversible-failure")
        else:
            effects.append("interaction-no-op")

    if spec.family is RuleFamily.TOGGLE_DOOR_KEY and next_state.player == spec.key:
        next_state = replace(next_state, has_key=True)
        effects.append("key-collected")
    if spec.family is RuleFamily.PARTIAL_OBSERVABILITY:
        next_state = replace(next_state, phase=(state.phase + 1) % 3)
        effects.append("visibility-window-advanced")
    if spec.family is RuleFamily.RULE_CHANGE_BETWEEN_LEVELS:
        if next_state.stage == 0 and next_state.player == spec.secondary:
            next_state = replace(next_state, stage=1)
            effects.extend(("level-advanced", "action-map-changed"))
        elif next_state.stage == 1 and next_state.player == spec.target:
            next_state = replace(next_state, terminal=GameStateName.WIN)
            effects.append("second-level-goal")
    elif (
        spec.family
        not in {
            RuleFamily.COORDINATE_UNKNOWN_TARGET,
            RuleFamily.COLOR_SHAPE_MATCHING,
            RuleFamily.CYCLIC_TIMING,
            RuleFamily.REVERSIBLE_IRREVERSIBLE,
            RuleFamily.DELAYED_REWARD,
            RuleFamily.MULTIPLE_COMPATIBLE_MODELS,
            RuleFamily.GAME_OVER_RESET_RECOVERY,
        }
        and next_state.player == spec.target
    ):
        next_state = replace(next_state, terminal=GameStateName.WIN)
        effects.append("spatial-goal")
    elif (
        spec.family is RuleFamily.REVERSIBLE_IRREVERSIBLE
        and next_state.player == spec.target
        and next_state.reversible_open
    ):
        next_state = replace(next_state, terminal=GameStateName.WIN)
        effects.append("bridge-goal")

    if next_state.steps >= spec.max_steps and next_state.terminal is GameStateName.NOT_FINISHED:
        next_state = replace(next_state, terminal=GameStateName.GAME_OVER)
        effects.append("action-budget-exhausted")
    return _Transition(next_state, tuple(effects) or ("no-op",), contradiction)


def reset_state(spec: _EpisodeSpec, state: _WorldState) -> _WorldState:
    recovered = state.recovered or (
        spec.family is RuleFamily.GAME_OVER_RESET_RECOVERY
        and state.terminal is GameStateName.GAME_OVER
    )
    return initial_state(spec, recovered=recovered)


def _paint_shape(
    rows: list[list[int]], position: tuple[int, int], shape: tuple[tuple[int, int], ...], color: int
) -> None:
    for dx, dy in shape:
        x, y = position[0] + dx, position[1] + dy
        if 0 <= y < len(rows) and 0 <= x < len(rows[0]):
            rows[y][x] = color


def render(spec: _EpisodeSpec, state: _WorldState) -> GridFrame:
    """Render only public visual state; no rule or goal annotation is encoded."""

    rows = [[0 for _ in range(spec.size)] for _ in range(spec.size)]
    wall_color, target_color, player_color = spec.palette[:3]
    if spec.family in {
        RuleFamily.CONDITIONAL_TRAVERSAL,
        RuleFamily.REVERSIBLE_IRREVERSIBLE,
    }:
        for x, y in spec.walls:
            if not (
                (spec.family is RuleFamily.CONDITIONAL_TRAVERSAL and state.door_open)
                or (spec.family is RuleFamily.REVERSIBLE_IRREVERSIBLE and state.reversible_open)
            ):
                rows[y][x] = wall_color
    if spec.family is RuleFamily.TOGGLE_DOOR_KEY and not state.door_open:
        rows[spec.door[1]][spec.door[0]] = wall_color
    for ordinal, (x, y) in enumerate(spec.distractors):
        rows[y][x] = spec.palette[(4 + ordinal + state.phase) % len(spec.palette)]
    if spec.family is RuleFamily.CONDITIONAL_TRAVERSAL:
        rows[spec.switch[1]][spec.switch[0]] = spec.palette[5]
    if spec.family is RuleFamily.TOGGLE_DOOR_KEY and not state.has_key:
        rows[spec.key[1]][spec.key[0]] = spec.palette[6]
    if spec.family is RuleFamily.COLOR_SHAPE_MATCHING:
        _paint_shape(rows, spec.secondary, spec.target_shape, target_color)
    target_visible = not (spec.family is RuleFamily.PARTIAL_OBSERVABILITY and state.phase == 1)
    player_visible = not (spec.family is RuleFamily.PARTIAL_OBSERVABILITY and state.phase == 2)
    visible_goal = (
        spec.secondary
        if spec.family is RuleFamily.RULE_CHANGE_BETWEEN_LEVELS and state.stage == 0
        else spec.target
    )
    if target_visible:
        _paint_shape(rows, visible_goal, spec.target_shape, target_color)
    if player_visible:
        _paint_shape(rows, state.player, spec.player_shape, player_color)
    return GridFrame.from_rows(rows)


def state_token(state: _WorldState) -> str:
    material = repr(state).encode()
    return f"sha256:{hashlib.sha256(material).hexdigest()}"


def _candidate_actions(spec: _EpisodeSpec, state: _WorldState) -> tuple[ActionRequest, ...]:
    actions = [
        ActionRequest(name) for name in spec.available_actions if name is not ActionName.ACTION6
    ]
    if ActionName.ACTION6 in spec.available_actions:
        points = {spec.target, spec.secondary, spec.switch, spec.key, spec.door, (0, 0)}
        actions.extend(
            ActionRequest(ActionName.ACTION6, Coordinate(*point)) for point in sorted(points)
        )
    if state.terminal is GameStateName.GAME_OVER:
        return (ActionRequest(ActionName.RESET),)
    return tuple(actions)


def solve(spec: _EpisodeSpec, *, max_depth: int = 40) -> tuple[ActionRequest, ...]:
    """Return a shortest evaluator-only plan found by exact state-space search."""

    start = initial_state(spec)
    queue: deque[tuple[_WorldState, tuple[ActionRequest, ...]]] = deque(((start, ()),))
    visited = {start}
    while queue:
        state, plan = queue.popleft()
        if state.terminal is GameStateName.WIN:
            return plan
        if len(plan) >= max_depth:
            continue
        for action in _candidate_actions(spec, state):
            successor = (
                reset_state(spec, state)
                if action.name is ActionName.RESET
                else advance(spec, state, action).state
            )
            if successor not in visited:
                visited.add(successor)
                queue.append((successor, (*plan, action)))
    raise ValueError(f"generated laboratory case {spec.case.case_id} is not solvable")


def goal_description(family: RuleFamily) -> str:
    return {
        RuleFamily.COORDINATE_UNKNOWN_TARGET: "select the hidden responsive target coordinate",
        RuleFamily.COLOR_SHAPE_MATCHING: "select the object matching the displayed target",
        RuleFamily.CYCLIC_TIMING: "act at the completing phase of a cyclic mechanism",
        RuleFamily.REVERSIBLE_IRREVERSIBLE: "open the reversible passage and reach its endpoint",
        RuleFamily.DELAYED_REWARD: "repeat the causal interaction until delayed completion",
        RuleFamily.MULTIPLE_COMPATIBLE_MODELS: "run a discriminating probe before selecting the target",
        RuleFamily.GAME_OVER_RESET_RECOVERY: "recover from terminal failure, then select the target",
    }.get(family, "move the controllable object into the completing configuration")


__all__ = [
    "_EpisodeSpec",
    "_Transition",
    "_WorldState",
    "advance",
    "build_catalog",
    "false_leading_action",
    "goal_description",
    "initial_state",
    "render",
    "reset_state",
    "solve",
    "state_token",
]
