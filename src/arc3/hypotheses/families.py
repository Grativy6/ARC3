"""Closed union and parser for all Stage 05 hypothesis statement families."""

from __future__ import annotations

from collections.abc import Mapping

from arc3.errors import HypothesisError

from .actions import (
    ActionSemanticsStatement,
    CoordinateActionTargetStatement,
    InteractionToggleStatement,
)
from .base import HypothesisFamily
from .goals import CandidateGoalStatement
from .objects import CollisionTraversabilityStatement, ControllableObjectStatement
from .transitions import (
    LevelInvariantStatement,
    ProgressTerminalStatement,
    StateTransitionStatement,
)

type HypothesisStatement = (
    ActionSemanticsStatement
    | ControllableObjectStatement
    | CollisionTraversabilityStatement
    | InteractionToggleStatement
    | CoordinateActionTargetStatement
    | StateTransitionStatement
    | ProgressTerminalStatement
    | CandidateGoalStatement
    | LevelInvariantStatement
)


def statement_from_dict(
    family: HypothesisFamily, value: Mapping[str, object]
) -> HypothesisStatement:
    """Parse a family-tagged statement without guessing its type."""

    if family is HypothesisFamily.ACTION_SEMANTICS:
        return ActionSemanticsStatement.from_dict(value)
    if family is HypothesisFamily.CONTROLLABLE_OBJECT_IDENTITY:
        return ControllableObjectStatement.from_dict(value)
    if family is HypothesisFamily.COLLISION_TRAVERSABILITY:
        return CollisionTraversabilityStatement.from_dict(value)
    if family is HypothesisFamily.INTERACTION_TOGGLE:
        return InteractionToggleStatement.from_dict(value)
    if family is HypothesisFamily.COORDINATE_ACTION_TARGET:
        return CoordinateActionTargetStatement.from_dict(value)
    if family is HypothesisFamily.STATE_TRANSITION:
        return StateTransitionStatement.from_dict(value)
    if family is HypothesisFamily.PROGRESS_TERMINAL:
        return ProgressTerminalStatement.from_dict(value)
    if family is HypothesisFamily.CANDIDATE_GOAL:
        return CandidateGoalStatement.from_dict(value)
    if family is HypothesisFamily.LEVEL_INVARIANT:
        return LevelInvariantStatement.from_dict(value)
    raise HypothesisError(f"unsupported hypothesis family: {family}")
