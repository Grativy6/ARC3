"""Typed identities and evaluator records for the procedural ARC3 laboratory."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from arc3.adapters import Observation
from arc3.types import ActionRequest, Coordinate, GameStateName


class LabPartition(StrEnum):
    """Predeclared procedural partitions with distinct generation domains."""

    DEVELOPMENT = "development"
    HELD_OUT_COMBINATIONS = "held-out-combinations"
    HELD_OUT_FAMILIES = "held-out-families"


class RuleFamily(StrEnum):
    """Diagnostic rule families required by the evaluation protocol."""

    UNKNOWN_DIRECTIONAL_MAPPING = "unknown-directional-mapping"
    CONTROLLABLE_IDENTIFICATION = "controllable-identification"
    CONDITIONAL_TRAVERSAL = "conditional-traversal"
    TOGGLE_DOOR_KEY = "toggle-door-key"
    COORDINATE_UNKNOWN_TARGET = "coordinate-unknown-target"
    COLOR_SHAPE_MATCHING = "color-shape-matching"
    CYCLIC_TIMING = "cyclic-timing"
    REVERSIBLE_IRREVERSIBLE = "reversible-irreversible"
    DELAYED_REWARD = "delayed-reward"
    MISLEADING_NOVELTY = "misleading-novelty"
    PARTIAL_OBSERVABILITY = "partial-observability"
    RULE_CHANGE_BETWEEN_LEVELS = "rule-change-between-levels"
    FALSE_INITIAL_HYPOTHESIS = "false-initial-hypothesis"
    MULTIPLE_COMPATIBLE_MODELS = "multiple-compatible-models"
    GAME_OVER_RESET_RECOVERY = "game-over-reset-recovery"


@dataclass(frozen=True, slots=True)
class LabCase:
    """Opaque production-safe identity for one generated episode."""

    case_id: str
    partition: LabPartition
    seed: int


@dataclass(frozen=True, slots=True)
class TransitionTruth:
    """Evaluator-only exact annotation for one executed transition."""

    step: int
    family: RuleFamily
    action: ActionRequest
    before_state: str
    after_state: str
    effects: tuple[str, ...]
    goal_reached: bool
    contradiction_revealed: bool


@dataclass(frozen=True, slots=True)
class EpisodeGroundTruth:
    """Evaluator-only goal, transition, and solvability annotation."""

    case_id: str
    family: RuleFamily
    partition: LabPartition
    seed: int
    goal: str
    transition_rule: str
    action_semantics: tuple[tuple[str, str], ...]
    grid_size: int
    palette: tuple[int, ...]
    player_shape: tuple[tuple[int, int], ...]
    target_shape: tuple[tuple[int, int], ...]
    start: Coordinate
    target: Coordinate
    distractors: tuple[Coordinate, ...]
    walls: tuple[Coordinate, ...]
    oracle_plan: tuple[ActionRequest, ...]
    false_leading_prefix: tuple[ActionRequest, ...]
    contradiction_action: ActionRequest | None
    reversible_consequences: bool


@dataclass(frozen=True, slots=True)
class EvaluatedStep:
    """Observation plus its separately held evaluator annotation."""

    observation: Observation
    truth: TransitionTruth


@dataclass(frozen=True, slots=True)
class EpisodeRecord:
    """Compact immutable recording emitted by fast laboratory batches."""

    case_id: str
    family: RuleFamily
    seed: int
    completed: bool
    final_state: GameStateName
    actions: tuple[ActionRequest, ...]
    frame_hashes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class BaselineMeasurement:
    """Measured synthetic baseline result, explicitly not an official score."""

    policy: str
    partition: LabPartition
    root_seed: int
    episodes: int
    completed: int
    environment_actions: int
    resets: int
    completion_rate: float
    mean_actions: float
    scorer: str
    records: tuple[EpisodeRecord, ...]


__all__ = [
    "BaselineMeasurement",
    "EpisodeGroundTruth",
    "EpisodeRecord",
    "EvaluatedStep",
    "LabCase",
    "LabPartition",
    "RuleFamily",
    "TransitionTruth",
]
