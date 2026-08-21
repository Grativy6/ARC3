"""Bounded deterministic local simulation over a world-model ensemble."""

from __future__ import annotations

from dataclasses import dataclass

from arc3.errors import WorldModelError
from arc3.types import ActionRequest

from .model import WorldModelEnsemble
from .state import SymbolicState


@dataclass(frozen=True, slots=True)
class SimulatedPath:
    state: SymbolicState
    action_ids: tuple[str, ...]
    supporting_model_ids: tuple[str, ...]
    prediction_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SimulationResult:
    initial_state_id: str
    requested_horizon: int
    explored_transitions: int
    truncated: bool
    paths: tuple[SimulatedPath, ...]


def simulate_sequence(
    ensemble: WorldModelEnsemble,
    initial: SymbolicState,
    actions: tuple[ActionRequest, ...],
    *,
    max_horizon: int = 8,
    max_paths: int = 64,
) -> SimulationResult:
    """Branch on model disagreement without touching the environment."""

    if max_horizon < 0 or max_paths < 1:
        raise WorldModelError("simulation bounds must be non-negative with at least one path")
    selected_actions = actions[:max_horizon]
    truncated = len(selected_actions) != len(actions)
    paths: tuple[SimulatedPath, ...] = (SimulatedPath(initial, (), (), ()),)
    explored = 0
    for action in selected_actions:
        next_paths: dict[tuple[str, tuple[str, ...]], SimulatedPath] = {}
        for path in paths:
            prediction = ensemble.predict(path.state, action)
            explored += len(prediction.alternatives)
            for alternative in prediction.alternatives:
                model_ids = tuple(
                    sorted(set(path.supporting_model_ids) | set(alternative.supporting_model_ids))
                )
                candidate = SimulatedPath(
                    state=alternative.after_state,
                    action_ids=(*path.action_ids, _action_id(action)),
                    supporting_model_ids=model_ids,
                    prediction_ids=(*path.prediction_ids, *alternative.prediction_ids),
                )
                next_paths[(candidate.state.state_id, candidate.action_ids)] = candidate
        ordered = tuple(
            sorted(
                next_paths.values(),
                key=lambda item: (item.state.state_id, item.supporting_model_ids),
            )
        )
        if len(ordered) > max_paths:
            truncated = True
        paths = ordered[:max_paths]
    return SimulationResult(initial.state_id, len(selected_actions), explored, truncated, paths)


def _action_id(action: ActionRequest) -> str:
    if action.coordinate is None:
        return action.name.value
    return f"{action.name.value}@{action.coordinate.x},{action.coordinate.y}"


__all__ = ["SimulatedPath", "SimulationResult", "simulate_sequence"]
