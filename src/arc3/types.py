"""Dependency-free core identifiers and enums used across ARC3 boundaries."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import NewType

RunId = NewType("RunId", str)
EpisodeId = NewType("EpisodeId", str)
EventId = NewType("EventId", str)
GameId = NewType("GameId", str)
FrameHash = NewType("FrameHash", str)
BlobHash = NewType("BlobHash", str)
ConfigHash = NewType("ConfigHash", str)
HypothesisId = NewType("HypothesisId", str)
WorldModelId = NewType("WorldModelId", str)
GoalId = NewType("GoalId", str)
PlanId = NewType("PlanId", str)
PredictionId = NewType("PredictionId", str)
ActionDecisionId = NewType("ActionDecisionId", str)
CheckpointId = NewType("CheckpointId", str)
EvaluationId = NewType("EvaluationId", str)

type JSONScalar = str | int | float | bool | None
type JSONValue = JSONScalar | list[JSONValue] | dict[str, JSONValue]


class EnvironmentMode(StrEnum):
    """Execution surface; only ``online`` enables networking by default."""

    SYNTHETIC = "synthetic"
    LOCAL = "local"
    ONLINE = "online"
    COMPETITION = "competition"


class ExecutionMode(StrEnum):
    """Controller resource contract, independent of the environment surface."""

    RESEARCH_UNBOUNDED = "RESEARCH_UNBOUNDED"
    COMPETITION_BOUNDED = "COMPETITION_BOUNDED"


class ActionName(StrEnum):
    """First-party names for the official variable action vocabulary."""

    RESET = "RESET"
    ACTION1 = "ACTION1"
    ACTION2 = "ACTION2"
    ACTION3 = "ACTION3"
    ACTION4 = "ACTION4"
    ACTION5 = "ACTION5"
    ACTION6 = "ACTION6"
    ACTION7 = "ACTION7"

    @property
    def requires_coordinates(self) -> bool:
        """Whether this action carries an ``(x, y)`` coordinate payload."""

        return self is ActionName.ACTION6


class GameStateName(StrEnum):
    """Normalized lifecycle states exposed by the current official toolkit."""

    NOT_PLAYED = "NOT_PLAYED"
    NOT_FINISHED = "NOT_FINISHED"
    WIN = "WIN"
    GAME_OVER = "GAME_OVER"
    UNKNOWN = "UNKNOWN"


class StateScope(StrEnum):
    """Maximum scope at which derived state is supported."""

    STEP = "step"
    EPISODE = "episode"
    LEVEL = "level"
    GAME = "game"
    GENERIC = "generic"


class HypothesisStatus(StrEnum):
    """Event-sourced hypothesis lifecycle state."""

    CANDIDATE = "candidate"
    ACTIVE = "active"
    NARROWED = "narrowed"
    REJECTED = "rejected"
    UNRESOLVED = "unresolved"
    SUPERSEDED = "superseded"


class EvaluationSurface(StrEnum):
    """Exact evidence labels required by the evaluation protocol."""

    SYNTHETIC = "synthetic"
    LOCAL_PUBLIC = "local-public"
    ONLINE_PUBLIC = "online-public"
    KAGGLE_PUBLIC = "Kaggle-public"
    SEMI_PRIVATE = "semi-private"
    OFFICIAL_PRIVATE = "official-private"


class StageState(StrEnum):
    """Allowed workflow-stage outcomes."""

    READY = "READY"
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    PASS = "PASS"
    PARTIAL = "PARTIAL"
    BLOCKED_EXTERNAL = "BLOCKED_EXTERNAL"
    FAILED_MECHANISM = "FAILED_MECHANISM"
    FAILED_INFRASTRUCTURE = "FAILED_INFRASTRUCTURE"


class RationaleCategory(StrEnum):
    """Concise decision categories suitable for an auditable trace."""

    DISCRIMINATE_MODELS = "discriminate_models"
    REEXPLORATION = "reexploration"
    FOLLOW_PLAN = "follow_plan"
    MANDATORY_RESET = "mandatory_reset"
    FAULT_FALLBACK = "fault_fallback"
    BASELINE = "baseline"


class DisplacementEvidenceKind(StrEnum):
    """Receipt status of one interpreted mover displacement."""

    DIRECT_OBSERVATION = "direct-observation"
    WRAP_TOPOLOGY_CANDIDATE = "wrap-topology-candidate"


@dataclass(frozen=True, slots=True, order=True)
class Coordinate:
    """A validated coordinate in the official 64 by 64 action domain."""

    x: int
    y: int

    def __post_init__(self) -> None:
        if isinstance(self.x, bool) or isinstance(self.y, bool):
            raise ValueError("coordinates must be integers, not booleans")
        if not 0 <= self.x <= 63 or not 0 <= self.y <= 63:
            raise ValueError("coordinates must be within the inclusive range 0..63")


@dataclass(frozen=True, slots=True)
class ActionRequest:
    """Normalized environment action, separate from policy rationale metadata."""

    name: ActionName
    coordinate: Coordinate | None = None

    def __post_init__(self) -> None:
        if self.name.requires_coordinates != (self.coordinate is not None):
            requirement = "requires" if self.name.requires_coordinates else "forbids"
            raise ValueError(f"{self.name.value} {requirement} coordinate data")


# Conservative aliases for callers that prefer shorter vocabulary.
ActionKind = ActionName
GameState = GameStateName
ResultSurface = EvaluationSurface
Scope = StateScope
StageStatus = StageState
RunMode = EnvironmentMode
