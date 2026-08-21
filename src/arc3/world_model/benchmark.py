"""Pinned Stage 08 retrodiction-gate mechanism comparison."""

from __future__ import annotations

from dataclasses import dataclass

from arc3.types import ActionName, ActionRequest

from .model import WorldModelEnsemble, make_model_candidate
from .retrodiction import PreservedTransition, gated_ensemble, retrodict
from .rules import CollisionBehavior, CollisionRule, MovementRule
from .simulator import simulate_sequence
from .state import Cell, SymbolicEntity, SymbolicState


@dataclass(frozen=True, slots=True)
class RetrodictionComparison:
    """Exact bounded comparison against the retrodiction-off ablation."""

    label: str
    status: str
    cases: int
    action_budget: int
    gated_completed: int
    ungated_completed: int
    gated_actions: int
    ungated_actions: int
    gated_model_ids: tuple[str, ...]
    ungated_model_ids: tuple[str, ...]
    gated_artifact_ids: tuple[str, ...]
    ungated_artifact_ids: tuple[str, ...]


def _state(x: int, *, target: int = 6) -> SymbolicState:
    facts = ("goal",) if x == target else ()
    return SymbolicState(
        8,
        3,
        (
            SymbolicEntity("piece", "mover", (Cell(x, 1),), color=2),
            SymbolicEntity("target", "target", (Cell(target, 1),), color=7),
        ),
        facts=facts,
    )


def _transition(identifier: str, before_x: int, after_x: int) -> PreservedTransition:
    return PreservedTransition(
        identifier,
        _state(before_x),
        ActionRequest(ActionName.ACTION1),
        _state(after_x),
        (f"event:{identifier}:before", f"event:{identifier}:after"),
    )


def _reaches_goal(final: SymbolicState) -> bool:
    piece = final.entity("piece")
    target = final.entity("target")
    return piece is not None and target is not None and piece.cells == target.cells


def measure_retrodiction_comparison() -> RetrodictionComparison:
    """Run four unseen parameter combinations under equal planned actions."""

    correct = make_model_candidate(
        hypothesis_ids=("H-RIGHT",),
        rules=(
            MovementRule("R-RIGHT", ActionName.ACTION1, 1, 0, entity_id="piece"),
            CollisionRule("R-TARGET-PASS", "mover", "target", CollisionBehavior.PASS),
        ),
        rank_weight=1,
    )
    false_high_rank = make_model_candidate(
        hypothesis_ids=("H-LEFT",),
        rules=(
            MovementRule("R-LEFT", ActionName.ACTION1, -1, 0, entity_id="piece"),
            CollisionRule("R-TARGET-PASS", "mover", "target", CollisionBehavior.PASS),
        ),
        rank_weight=9,
    )
    development_history = (
        _transition("T-DEV-1", 1, 2),
        _transition("T-DEV-2", 2, 3),
    )
    gated_artifacts = tuple(
        retrodict(model, development_history) for model in (correct, false_high_rank)
    )
    ungated_artifacts = tuple(
        retrodict(model, development_history, enabled=False) for model in (correct, false_high_rank)
    )
    gated = gated_ensemble((correct, false_high_rank), gated_artifacts)
    ungated = gated_ensemble(
        (correct, false_high_rank),
        ungated_artifacts,
        allow_ungated_ablation=True,
    )
    ablation_top_model = WorldModelEnsemble((ungated.candidates[0],))
    held_out_cases = ((0, 4), (1, 5), (2, 7), (3, 6))
    gated_completions = 0
    ablation_completions = 0
    gated_actions = 0
    ablation_actions = 0
    for start, target in held_out_cases:
        held_out_start = _state(start, target=target)
        plan = (ActionRequest(ActionName.ACTION1),) * (target - start)
        gated_final = simulate_sequence(gated, held_out_start, plan).paths[0].state
        ablation_final = simulate_sequence(ablation_top_model, held_out_start, plan).paths[0].state
        gated_completions += int(_reaches_goal(gated_final))
        ablation_completions += int(_reaches_goal(ablation_final))
        gated_actions += len(plan)
        ablation_actions += len(plan)
    return RetrodictionComparison(
        label="synthetic",
        status="MECHANISM_OBSERVED",
        cases=len(held_out_cases),
        action_budget=16,
        gated_completed=gated_completions,
        ungated_completed=ablation_completions,
        gated_actions=gated_actions,
        ungated_actions=ablation_actions,
        gated_model_ids=tuple(model.model_id for model in gated.candidates),
        ungated_model_ids=tuple(model.model_id for model in ungated.candidates),
        gated_artifact_ids=tuple(artifact.artifact_id for artifact in gated_artifacts),
        ungated_artifact_ids=tuple(artifact.artifact_id for artifact in ungated_artifacts),
    )


__all__ = ["RetrodictionComparison", "measure_retrodiction_comparison"]
