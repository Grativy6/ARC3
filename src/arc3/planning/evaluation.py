"""Frozen synthetic Stage 10 mechanism comparisons, never official scores."""

from __future__ import annotations

import random
from dataclasses import dataclass

from arc3.trace.canonical import sha256_json
from arc3.types import ActionName, ActionRequest, EvaluationSurface
from arc3.world_model import Cell, ModelCandidate, MovementRule, SymbolicEntity, SymbolicState

from .models import PlanProblem, SearchAlgorithm, SearchBudget, SearchStatus
from .search import search


@dataclass(frozen=True, slots=True)
class PlanningComparison:
    """Exact equal-budget aggregate over generated held-out symbolic tasks."""

    surface: EvaluationSurface
    split: str
    seed: int
    task_manifest_sha256: str
    tasks: int
    action_budget_per_task: int
    planning_completed: int
    planning_actions: int
    exploration_only_completed: int
    exploration_only_actions: int
    recovery_completed: int
    recovery_actions: int
    no_recovery_completed: int
    no_recovery_actions: int

    @property
    def planning_completion_rate(self) -> float:
        return self.planning_completed / self.tasks

    @property
    def exploration_completion_rate(self) -> float:
        return self.exploration_only_completed / self.tasks


@dataclass(frozen=True, slots=True)
class _Task:
    task_id: str
    state: SymbolicState
    target: Cell
    model: ModelCandidate
    actions: tuple[ActionRequest, ...]


def measure_planning_comparison(
    *, seed: int = 20260821, tasks: int = 24, action_budget_per_task: int = 24
) -> PlanningComparison:
    """Compare planning, exploration-only, and recovery ablations on one frozen split."""

    if tasks <= 0 or action_budget_per_task <= 0:
        raise ValueError("tasks and action budget must be positive")
    generated = _held_out_tasks(seed=seed, count=tasks)
    planning_completed = planning_actions = 0
    exploration_completed = exploration_actions = 0
    recovery_completed = recovery_actions = 0
    no_recovery_completed = no_recovery_actions = 0
    for task in generated:
        completed, actions = _run_planner(task, action_budget_per_task)
        planning_completed += int(completed)
        planning_actions += actions
        completed, actions = _run_exploration_only(task, action_budget_per_task)
        exploration_completed += int(completed)
        exploration_actions += actions
        completed, actions = _run_fault_recovery(task, action_budget_per_task, enabled=True)
        recovery_completed += int(completed)
        recovery_actions += actions
        completed, actions = _run_fault_recovery(task, action_budget_per_task, enabled=False)
        no_recovery_completed += int(completed)
        no_recovery_actions += actions
    return PlanningComparison(
        surface=EvaluationSurface.SYNTHETIC,
        split="held-out-symbolic-multistep-v0.1",
        seed=seed,
        task_manifest_sha256=sha256_json(generated),
        tasks=tasks,
        action_budget_per_task=action_budget_per_task,
        planning_completed=planning_completed,
        planning_actions=planning_actions,
        exploration_only_completed=exploration_completed,
        exploration_only_actions=exploration_actions,
        recovery_completed=recovery_completed,
        recovery_actions=recovery_actions,
        no_recovery_completed=no_recovery_completed,
        no_recovery_actions=no_recovery_actions,
    )


def _held_out_tasks(*, seed: int, count: int) -> tuple[_Task, ...]:
    rng = random.Random(seed)
    tasks: list[_Task] = []
    directions = ((-1, 0), (1, 0), (0, -1), (0, 1))
    names = (ActionName.ACTION1, ActionName.ACTION2, ActionName.ACTION3, ActionName.ACTION4)
    for index in range(count):
        width = height = 8
        while True:
            start = Cell(rng.randrange(width), rng.randrange(height))
            target = Cell(rng.randrange(width), rng.randrange(height))
            if abs(start.x - target.x) + abs(start.y - target.y) >= 4:
                break
        shuffled = list(directions)
        rng.shuffle(shuffled)
        rules = tuple(
            MovementRule(
                rule_id=f"generic-direction-{ordinal}",
                action=name,
                dx=direction[0],
                dy=direction[1],
                entity_id="mover",
            )
            for ordinal, (name, direction) in enumerate(zip(names, shuffled, strict=True))
        )
        model = ModelCandidate(
            model_id=f"synthetic-model-{index:03d}",
            hypothesis_ids=(f"direction-map-{index:03d}",),
            rules=rules,
            rank_weight=1,
        )
        state = SymbolicState(
            width,
            height,
            entities=(SymbolicEntity("mover", "controllable", (start,)),),
        )
        tasks.append(
            _Task(
                task_id=f"held-out-{index:03d}",
                state=state,
                target=target,
                model=model,
                actions=tuple(ActionRequest(name) for name in names),
            )
        )
    return tuple(tasks)


def _problem(task: _Task, state: SymbolicState) -> PlanProblem:
    def reached(candidate: SymbolicState) -> bool:
        mover = candidate.entity("mover")
        return mover is not None and mover.anchor == task.target

    def distance(candidate: SymbolicState) -> float:
        mover = candidate.entity("mover")
        if mover is None:
            return float(candidate.width + candidate.height)
        return float(abs(mover.anchor.x - task.target.x) + abs(mover.anchor.y - task.target.y))

    return PlanProblem(
        problem_id=task.task_id,
        initial_state=state,
        model=task.model,
        goal_id="reach-observed-target",
        goal_revision="v1",
        available_actions=task.actions,
        goal_test=reached,
        heuristic=distance,
    )


def _run_planner(task: _Task, budget: int) -> tuple[bool, int]:
    result = search(
        _problem(task, task.state),
        algorithm=SearchAlgorithm.A_STAR,
        budget=SearchBudget(max_nodes=512, max_depth=budget, max_time_ms=1_000),
    )
    if result.status is not SearchStatus.FOUND or result.plan is None:
        return False, 0
    actions = min(len(result.plan.steps), budget)
    state = task.state
    for step in result.plan.steps[:actions]:
        state = task.model.predict(state, step.action).after_state
    return _problem(task, state).goal_test(state), actions


def _run_exploration_only(task: _Task, budget: int) -> tuple[bool, int]:
    state = task.state
    problem = _problem(task, state)
    for index in range(budget):
        action = task.actions[index % len(task.actions)]
        state = task.model.predict(state, action).after_state
        if problem.goal_test(state):
            return True, index + 1
    return False, budget


def _run_fault_recovery(task: _Task, budget: int, *, enabled: bool) -> tuple[bool, int]:
    """Inject one failed first prediction; disabled recovery stops instead of continuing blind."""

    initial = search(
        _problem(task, task.state),
        algorithm=SearchAlgorithm.A_STAR,
        budget=SearchBudget(max_nodes=512, max_depth=budget, max_time_ms=1_000),
    )
    if initial.plan is None or not initial.plan.steps:
        return False, 0
    actions = 1
    observed = task.state  # The first predicted movement deliberately did not occur.
    if not enabled:
        return False, actions
    replanned = search(
        _problem(task, observed),
        algorithm=SearchAlgorithm.A_STAR,
        budget=SearchBudget(max_nodes=512, max_depth=max(1, budget - actions), max_time_ms=1_000),
    )
    if replanned.plan is None:
        return False, actions
    state = observed
    for step in replanned.plan.steps:
        if actions >= budget:
            break
        state = task.model.predict(state, step.action).after_state
        actions += 1
    return _problem(task, state).goal_test(state), actions


__all__ = ["PlanningComparison", "measure_planning_comparison"]
