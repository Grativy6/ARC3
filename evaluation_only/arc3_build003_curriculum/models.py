"""Typed evaluator-only identities and hidden curriculum state."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from arc3.types import ActionRequest, GameStateName

type Point = tuple[int, int]


class CurriculumFamily(StrEnum):
    """The ten preregistered progressive mechanic families, in level order."""

    MOVEMENT_RESOURCE_COST = "movement-resource-cost"
    BLOCKING_WALLS = "blocking-walls"
    RESOURCE_RESTORATION = "resource-restoration"
    REUSABLE_ONE_SHOT = "reusable-versus-one-shot-restoration"
    GATE_SWITCH = "gate-switch-reachability"
    PUSHING = "pushing-other-object"
    TERRAIN_STATUS = "terrain-status-modifier"
    DELAYED_RESPONSE = "delayed-hidden-state-response"
    HARMLESS_ANIMATION = "harmless-animation"
    HELD_OUT_COMPOSITION = "held-out-mechanic-composition"


class CurriculumVariant(StrEnum):
    """The four frozen Build 003 comparison variants."""

    BUILD002_FROZEN = "BUILD002_FROZEN"
    BLA_CLEF_LEVEL_RESET = "BLA_CLEF_LEVEL_RESET"
    BLA_ONLY_PERSISTENT = "BLA_ONLY_PERSISTENT"
    BLA_CLEF_FULL = "BLA_CLEF_FULL"


@dataclass(frozen=True, slots=True)
class CurriculumCase:
    """Opaque public identity plus evaluator-held seed."""

    case_id: str
    seed: int

    def __post_init__(self) -> None:
        if not self.case_id:
            raise ValueError("case_id must not be empty")
        if (
            isinstance(self.seed, bool)
            or not isinstance(self.seed, int)
            or not 0 <= self.seed < 2**63
        ):
            raise ValueError("seed must be an unsigned 63-bit integer")


@dataclass(frozen=True, slots=True)
class LevelSpec:
    """Privileged mechanic configuration never sent to a policy worker."""

    family: CurriculumFamily
    size: int
    start: Point
    goal: Point
    walls: frozenset[Point]
    base_cost: int
    resource_start: int
    resource_cap: int
    reusable_restorers: frozenset[Point] = frozenset()
    one_shot_restorers: frozenset[Point] = frozenset()
    restoration_amount: int = 0
    switch: Point | None = None
    gate: Point | None = None
    pushable_start: Point | None = None
    pushable_goal: Point | None = None
    terrain: frozenset[Point] = frozenset()
    terrain_extra_cost: int = 0
    delayed_trigger: Point | None = None
    delayed_actions: int = 0
    decorations: frozenset[Point] = frozenset()
    palette: tuple[int, ...] = ()
    max_steps: int = 96

    def __post_init__(self) -> None:
        if self.size != 10:
            raise ValueError("Build 003 curriculum uses a fixed 10 by 10 observation aperture")
        if len(self.palette) != 15 or set(self.palette) != set(range(1, 16)):
            raise ValueError("level palette must be a permutation of colors 1 through 15")
        if not 0 < self.resource_start <= self.resource_cap <= 31:
            raise ValueError("initial resource must be positive and within its cap")
        if self.base_cost <= 0 or self.max_steps <= 0:
            raise ValueError("cost and step bounds must be positive")
        if (self.pushable_start is None) != (self.pushable_goal is None):
            raise ValueError("pushable start and goal must be declared together")
        if (self.delayed_trigger is None) != (self.delayed_actions == 0):
            raise ValueError("a delayed trigger requires a positive delayed action count")
        if self.switch is not None and self.gate is None:
            raise ValueError("a switch requires a gate")
        if bool(self.reusable_restorers or self.one_shot_restorers) != bool(
            self.restoration_amount
        ):
            raise ValueError("restorers and their positive restoration amount require each other")
        if bool(self.terrain) != bool(self.terrain_extra_cost):
            raise ValueError("terrain and its positive extra cost require each other")
        points = (
            {self.start, self.goal}
            | set(self.walls)
            | set(self.reusable_restorers)
            | set(self.one_shot_restorers)
            | set(self.terrain)
            | set(self.decorations)
            | {
                point
                for point in (
                    self.switch,
                    self.gate,
                    self.pushable_start,
                    self.pushable_goal,
                    self.delayed_trigger,
                )
                if point is not None
            }
        )
        if any(not all(1 <= coordinate <= 8 for coordinate in point) for point in points):
            raise ValueError("all mechanic points must lie inside the 1..8 board")
        if self.start in self.walls or self.goal in self.walls or self.gate in self.walls:
            raise ValueError("start, goal, and gate must not overlap blocking walls")


@dataclass(frozen=True, slots=True)
class CurriculumSpec:
    """A hidden ten-level sequence."""

    case: CurriculumCase
    levels: tuple[LevelSpec, ...]

    def __post_init__(self) -> None:
        if tuple(level.family for level in self.levels) != tuple(CurriculumFamily):
            raise ValueError("curriculum must contain every family exactly once in frozen order")


@dataclass(frozen=True, slots=True)
class LevelState:
    """Exact evaluator state for one level."""

    player: Point
    resource: int
    pushable: Point | None = None
    consumed_one_shot: frozenset[Point] = frozenset()
    gate_open: bool = False
    delayed_remaining: int | None = None
    animation_phase: int = 0
    steps: int = 0
    terminal: GameStateName = GameStateName.NOT_FINISHED


@dataclass(frozen=True, slots=True)
class CurriculumState:
    """Exact sequence state retained only by the evaluator process."""

    level_index: int
    level: LevelState
    levels_completed: int = 0
    terminal: GameStateName = GameStateName.NOT_FINISHED


@dataclass(frozen=True, slots=True)
class TransitionTruth:
    """Evaluator annotation for one action consequence."""

    action: ActionRequest
    family: CurriculumFamily
    level_index_before: int
    level_index_after: int
    effects: tuple[str, ...]
    level_completed: bool
    game_won: bool
    game_over: bool


@dataclass(frozen=True, slots=True)
class LevelOraclePlan:
    """Shortest evaluator-only plan for one independently initialized level."""

    family: CurriculumFamily
    actions: tuple[ActionRequest, ...]
    explored_states: int


@dataclass(frozen=True, slots=True)
class SequenceOracleReceipt:
    """Exact self-test result for one hidden sequence."""

    case_id: str
    seed: int
    plans: tuple[LevelOraclePlan, ...]
    environment_actions: int
    final_state: GameStateName
    levels_completed: int
    win_levels: int
    action_digest: str


__all__ = [
    "CurriculumCase",
    "CurriculumFamily",
    "CurriculumSpec",
    "CurriculumState",
    "CurriculumVariant",
    "LevelOraclePlan",
    "LevelSpec",
    "LevelState",
    "Point",
    "SequenceOracleReceipt",
    "TransitionTruth",
]
