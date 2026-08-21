"""Public controller values for the integrated ARC3 policy boundary."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from arc3.config import ARC3Config
from arc3.trace import CheckpointEnvelope
from arc3.types import ActionRequest, JSONValue, RationaleCategory


class ControllerPreset(StrEnum):
    """Stable controller configurations used by baselines and deployment."""

    BASELINE = "baseline"
    TRACE = "trace"
    WORLD_MODEL = "world-model"
    FULL = "full"
    COMPETITION = "competition"


class ControllerPhase(StrEnum):
    """Explicit legal phases of the observation/action handshake."""

    NEW = "new"
    OBSERVED = "observed"
    AWAITING_CONSEQUENCE = "awaiting-consequence"
    GAME_OVER = "game-over"
    COMPLETE = "complete"
    FAULTED = "faulted"
    CLOSED = "closed"


@dataclass(frozen=True, slots=True)
class PresetFeatures:
    """Named mechanism switches; none changes the environment contract."""

    use_measurements: bool
    use_hypotheses: bool
    use_world_model: bool
    use_goals: bool
    use_planning: bool
    use_memory: bool
    allow_local_proposals: bool = False


_PRESET_FEATURES: dict[ControllerPreset, PresetFeatures] = {
    ControllerPreset.BASELINE: PresetFeatures(False, False, False, False, False, False),
    ControllerPreset.TRACE: PresetFeatures(True, False, False, False, False, False),
    ControllerPreset.WORLD_MODEL: PresetFeatures(True, True, True, False, False, False),
    ControllerPreset.FULL: PresetFeatures(True, True, True, True, True, True),
    ControllerPreset.COMPETITION: PresetFeatures(True, True, True, True, True, True),
}


def preset_features(preset: ControllerPreset | str) -> PresetFeatures:
    """Resolve one stable preset without accepting silent fallback names."""

    parsed = preset if isinstance(preset, ControllerPreset) else ControllerPreset(preset)
    return _PRESET_FEATURES[parsed]


@dataclass(frozen=True, slots=True)
class RunContext:
    """Identity and storage supplied before any observation is consumed."""

    run_id: str
    episode_id: str
    game_id: str
    trace_root: Path
    checkpoint_root: Path
    config: ARC3Config
    git_commit: str
    source_kind: str = "arc3-controller"
    source_version: str = "0.1"

    def __post_init__(self) -> None:
        for name, value in (
            ("run_id", self.run_id),
            ("episode_id", self.episode_id),
            ("game_id", self.game_id),
            ("git_commit", self.git_commit),
            ("source_kind", self.source_kind),
            ("source_version", self.source_version),
        ):
            if not value.strip():
                raise ValueError(f"{name} must be non-empty")


@dataclass(frozen=True, slots=True)
class ObservationReceipt:
    """Pointer to an immutable raw observation and its replaceable measurements."""

    observation_event_id: str
    observation_event_hash: str
    frame_hashes: tuple[str, ...]
    measurement_event_ids: tuple[str, ...]
    valid: bool = True
    fault_event_id: str | None = None


@dataclass(frozen=True, slots=True)
class CandidateAction:
    """One legal alternative and its concise, trace-safe ranking summary."""

    action: ActionRequest
    source: str
    utility: float
    expected_progress: float
    information: float
    failure_risk: float

    def to_trace_payload(self) -> dict[str, JSONValue]:
        coordinate = self.action.coordinate
        return {
            "action": self.action.name.value,
            "coordinate": (
                {"x": coordinate.x, "y": coordinate.y} if coordinate is not None else None
            ),
            "source": self.source,
            "utility": self.utility,
            "expected_progress": self.expected_progress,
            "information": self.information,
            "failure_risk": self.failure_risk,
            "weight_kind": "uncalibrated_utility",
        }


@dataclass(frozen=True, slots=True)
class ActionDecision:
    """Validated environment action plus the complete local receipt linkage."""

    decision_id: str
    action: ActionRequest
    selected_event_id: str
    validated_event_id: str
    submitted_event_id: str
    observation_event_id: str
    prediction_receipt_id: str | None
    prediction_ids: tuple[str, ...]
    active_hypothesis_ids: tuple[str, ...]
    active_world_model_ids: tuple[str, ...]
    active_goal_ids: tuple[str, ...]
    selected_probe_or_plan_id: str | None
    alternatives: tuple[CandidateAction, ...]
    rationale_category: RationaleCategory
    rationale_summary: str


@dataclass(frozen=True, slots=True)
class ConsequenceReceipt:
    """Immutable consequence pointer plus bounded revision outcomes."""

    consequence_event_id: str
    consequence_event_hash: str
    observation_receipt: ObservationReceipt
    matched_prediction: bool | None
    reopened_model_ids: tuple[str, ...]
    invalidated_plan_ids: tuple[str, ...]
    progress_signal_ids: tuple[str, ...]
    phase: ControllerPhase


@dataclass(frozen=True, slots=True)
class ControllerCheckpoint:
    """Validated durable controller snapshot."""

    path: Path
    envelope: CheckpointEnvelope
    phase: ControllerPhase


@dataclass(frozen=True, slots=True)
class ControllerSnapshot:
    """Small read-only status surface for adapters and tests."""

    phase: ControllerPhase
    step_index: int
    level_index: int
    actions_used: int
    resets_used: int
    trace_events: int
    pending_action: ActionRequest | None
    active_hypothesis_ids: tuple[str, ...]
    active_world_model_ids: tuple[str, ...]
    active_goal_ids: tuple[str, ...]
    fault_count: int


__all__ = [
    "ActionDecision",
    "CandidateAction",
    "ConsequenceReceipt",
    "ControllerCheckpoint",
    "ControllerPhase",
    "ControllerPreset",
    "ControllerSnapshot",
    "ObservationReceipt",
    "PresetFeatures",
    "RunContext",
    "preset_features",
]
