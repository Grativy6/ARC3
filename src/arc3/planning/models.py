"""Typed symbolic planning values with explicit identities and budgets."""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

from arc3.errors import PlanningError
from arc3.types import ActionRequest, JSONValue
from arc3.world_model import ModelCandidate, SymbolicState

type GoalTest = Callable[[SymbolicState], bool]
type Heuristic = Callable[[SymbolicState], float]
type TransitionMetric = Callable[[SymbolicState, ActionRequest, SymbolicState], float]


def _zero_heuristic(_state: SymbolicState) -> float:
    return 0.0


def _unit_cost(_before: SymbolicState, _action: ActionRequest, _after: SymbolicState) -> float:
    return 1.0


def _zero_metric(_before: SymbolicState, _action: ActionRequest, _after: SymbolicState) -> float:
    return 0.0


class SearchAlgorithm(StrEnum):
    """Supported bounded deterministic search orders."""

    BREADTH_FIRST = "breadth-first"
    UNIFORM_COST = "uniform-cost"
    A_STAR = "a-star"


class SearchStatus(StrEnum):
    """Measured termination reason for one search."""

    FOUND = "found"
    EXHAUSTED = "exhausted"
    NODE_BUDGET = "node-budget"
    TIME_BUDGET = "time-budget"
    DEPTH_BUDGET = "depth-budget"


@dataclass(frozen=True, slots=True)
class SearchBudget:
    """Hard internal-computation limits; none spends an environment action."""

    max_nodes: int = 1_024
    max_depth: int = 32
    max_time_ms: int = 100

    def __post_init__(self) -> None:
        for name, value in (
            ("max_nodes", self.max_nodes),
            ("max_depth", self.max_depth),
            ("max_time_ms", self.max_time_ms),
        ):
            if isinstance(value, bool) or value <= 0:
                raise PlanningError(f"{name} must be a positive integer")


@dataclass(frozen=True, slots=True)
class PlanScoreWeights:
    """Declared plan-ranking terms; likelihood remains an estimate, not evidence."""

    completion: float = 10.0
    action_count: float = 1.0
    risk: float = 2.0
    information: float = 0.25

    def __post_init__(self) -> None:
        values = (self.completion, self.action_count, self.risk, self.information)
        if any(not math.isfinite(value) or value < 0 for value in values):
            raise PlanningError("plan score weights must be finite and non-negative")


@dataclass(frozen=True, slots=True)
class PlanProblem:
    """A symbolic state, executable model, and candidate goal supplied to search."""

    problem_id: str
    initial_state: SymbolicState
    model: ModelCandidate
    goal_id: str
    goal_revision: str
    available_actions: tuple[ActionRequest, ...]
    goal_test: GoalTest
    heuristic: Heuristic = _zero_heuristic
    action_cost: TransitionMetric = _unit_cost
    failure_risk: TransitionMetric = _zero_metric
    information_value: TransitionMetric = _zero_metric
    completion_likelihood: float = 1.0

    def __post_init__(self) -> None:
        if (
            not self.problem_id.strip()
            or not self.goal_id.strip()
            or not self.goal_revision.strip()
        ):
            raise PlanningError("problem and goal identities must be non-empty")
        actions = tuple(sorted(set(self.available_actions), key=action_key))
        if not actions:
            raise PlanningError("a plan problem requires at least one available action")
        if not 0.0 <= self.completion_likelihood <= 1.0:
            raise PlanningError("completion_likelihood must be within 0..1")
        object.__setattr__(self, "available_actions", actions)

    @property
    def model_id(self) -> str:
        return self.model.model_id

    @property
    def identity(self) -> tuple[str, str]:
        return self.model_id, f"{self.goal_id}@{self.goal_revision}"


@dataclass(frozen=True, slots=True)
class PlanStep:
    """One predicted transition; execution must validate it before advancing."""

    index: int
    action: ActionRequest
    before_state_id: str
    predicted_state: SymbolicState
    cost: float
    failure_risk: float
    information_value: float

    @property
    def predicted_state_id(self) -> str:
        return self.predicted_state.state_id


@dataclass(frozen=True, slots=True)
class PlanScore:
    completion_likelihood: float
    action_count: int
    total_cost: float
    total_risk: float
    total_information: float
    utility: float
    likelihood_kind: str = "model_estimate"


@dataclass(frozen=True, slots=True)
class Plan:
    plan_id: str
    problem_id: str
    model_id: str
    goal_id: str
    goal_revision: str
    algorithm: SearchAlgorithm
    initial_state_id: str
    final_state_id: str
    steps: tuple[PlanStep, ...]
    score: PlanScore

    def is_current(self, *, model_id: str, goal_id: str, goal_revision: str) -> bool:
        return (
            self.model_id == model_id
            and self.goal_id == goal_id
            and self.goal_revision == goal_revision
        )


@dataclass(frozen=True, slots=True)
class SearchResult:
    status: SearchStatus
    algorithm: SearchAlgorithm
    plan: Plan | None
    expanded_nodes: int
    generated_transitions: int
    maximum_depth_reached: int
    elapsed_ms: float
    budget: SearchBudget

    def to_trace_payload(self) -> dict[str, JSONValue]:
        return {
            "status": self.status.value,
            "algorithm": self.algorithm.value,
            "plan_id": self.plan.plan_id if self.plan is not None else None,
            "expanded_nodes": self.expanded_nodes,
            "generated_transitions": self.generated_transitions,
            "maximum_depth_reached": self.maximum_depth_reached,
            "elapsed_ms": self.elapsed_ms,
            "budget": {
                "max_nodes": self.budget.max_nodes,
                "max_depth": self.budget.max_depth,
                "max_time_ms": self.budget.max_time_ms,
            },
        }


def action_key(action: ActionRequest) -> tuple[str, int, int]:
    """Game-identity-free deterministic action tie-break."""

    coordinate = action.coordinate
    return (
        action.name.value,
        coordinate.x if coordinate is not None else -1,
        coordinate.y if coordinate is not None else -1,
    )


__all__ = [
    "GoalTest",
    "Heuristic",
    "Plan",
    "PlanProblem",
    "PlanScore",
    "PlanScoreWeights",
    "PlanStep",
    "SearchAlgorithm",
    "SearchBudget",
    "SearchResult",
    "SearchStatus",
    "TransitionMetric",
    "action_key",
]
