"""Bounded CLEF-style layer declarations and residual stopping decisions.

These records describe what a reader can inspect and when more representation
is worth constructing.  They do not assign game mechanics to visual features.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from arc3.types import ActionRequest, JSONValue, StateScope


class LogicalLayer(StrEnum):
    """The five software layers required by the Build 003 workflow."""

    RAW_FRAME_AND_METADATA = "raw_frame_and_official_metadata"
    COMPONENTS = "stable_regions_components_and_object_candidates"
    RELATIONS = "relations_and_reachability"
    ACTION_EFFECTS = "action_effect_events_and_mechanic_hypotheses"
    PLANNING = "planning_state"


class EvidenceFamily(StrEnum):
    """Independent measurement families retained without scalar averaging."""

    OFFICIAL_METADATA = "official_metadata"
    FRAME_CELLS = "frame_cells"
    COMPONENT_GEOMETRY = "component_geometry"
    TEMPORAL_TRACKING = "temporal_tracking"
    SPATIAL_RELATIONS = "spatial_relations"
    CAUSAL_TRANSFER = "causal_transfer"


class ResidualDisposition(StrEnum):
    """Explicit next state for a prediction residual."""

    PROMOTE = "PROMOTE"
    PARK = "PARK"
    STOP = "STOP"


class ResidualReason(StrEnum):
    """Auditable reason for promotion, parking, or stopping."""

    PREDICTION_OR_ACTION_RELEVANT = "prediction_or_action_relevant"
    VALIDITY_GATE_FAILED = "validity_gate_failed"
    BELOW_NOISE = "below_noise"
    ALREADY_EXPLAINED = "already_explained"
    READABILITY_WALL = "readability_wall"
    NO_DECISION_EFFECT = "no_relevant_prediction_or_action_change"
    COST_EXCEEDS_VALUE = "cost_exceeds_expected_decision_value"


def _require_text(value: str, *, field: str) -> str:
    if not value.strip():
        raise ValueError(f"{field} must not be empty")
    return value


def _normalize_refs(values: tuple[str, ...], *, field: str) -> tuple[str, ...]:
    if any(not value.strip() for value in values):
        raise ValueError(f"{field} entries must not be empty")
    return tuple(sorted(set(values)))


@dataclass(frozen=True, slots=True)
class ActionWindow:
    """Inclusive before/after step bounds for one dynamic reading."""

    before_step: int
    after_step: int

    def __post_init__(self) -> None:
        if any(
            isinstance(value, bool) or not isinstance(value, int) or value < 0
            for value in (self.before_step, self.after_step)
        ):
            raise ValueError("action window steps must be non-negative integers")
        if self.after_step <= self.before_step:
            raise ValueError("action window after_step must follow before_step")

    def to_dict(self) -> dict[str, JSONValue]:
        return {"before_step": self.before_step, "after_step": self.after_step}


@dataclass(frozen=True, slots=True)
class DynamicClaimContext:
    """The intervention boundary needed for a dynamic action-effect claim."""

    window: ActionWindow
    intervention: ActionRequest
    assumed_scope: StateScope
    observation_return_path: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.observation_return_path:
            raise ValueError("dynamic claims require an observation return path")
        if any(not item.strip() for item in self.observation_return_path):
            raise ValueError("observation return path entries must not be empty")

    def to_dict(self) -> dict[str, JSONValue]:
        coordinate = self.intervention.coordinate
        return {
            "window": self.window.to_dict(),
            "intervention": {
                "name": self.intervention.name.value,
                "coordinate": (
                    {"x": coordinate.x, "y": coordinate.y} if coordinate is not None else None
                ),
            },
            "assumed_scope": self.assumed_scope.value,
            "observation_return_path": list(self.observation_return_path),
        }


@dataclass(frozen=True, slots=True)
class ReadabilityThreshold:
    """A declared per-family noise floor expressed in ordinal signal units."""

    family: EvidenceFamily
    minimum_signal_units: int

    def __post_init__(self) -> None:
        if (
            isinstance(self.minimum_signal_units, bool)
            or not isinstance(self.minimum_signal_units, int)
            or self.minimum_signal_units < 0
        ):
            raise ValueError("minimum_signal_units must be a non-negative integer")

    def admits(self, signal_units: int) -> bool:
        """Return whether this family is readable without combining families."""

        if isinstance(signal_units, bool) or not isinstance(signal_units, int) or signal_units < 0:
            raise ValueError("signal_units must be a non-negative integer")
        return signal_units >= self.minimum_signal_units

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "family": self.family.value,
            "minimum_signal_units": self.minimum_signal_units,
        }


@dataclass(frozen=True, slots=True)
class ReadabilityWall:
    """Declared boundary beyond which additional detail is unavailable."""

    max_detail_units: int
    used_detail_units: int = 0
    additional_detail_available: bool = True

    def __post_init__(self) -> None:
        if (
            isinstance(self.max_detail_units, bool)
            or not isinstance(self.max_detail_units, int)
            or self.max_detail_units < 1
        ):
            raise ValueError("max_detail_units must be a positive integer")
        if (
            isinstance(self.used_detail_units, bool)
            or not isinstance(self.used_detail_units, int)
            or self.used_detail_units < 0
        ):
            raise ValueError("used_detail_units must be a non-negative integer")

    @property
    def reached(self) -> bool:
        return (
            not self.additional_detail_available or self.used_detail_units >= self.max_detail_units
        )

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "max_detail_units": self.max_detail_units,
            "used_detail_units": self.used_detail_units,
            "additional_detail_available": self.additional_detail_available,
            "reached": self.reached,
        }


@dataclass(frozen=True, slots=True)
class LayerDeclaration:
    """Compact ``(X, r, N_L, A_L, W_L)`` declaration for one reader."""

    declaration_id: str
    layer: LogicalLayer
    available_fields: tuple[str, ...]
    aperture: str
    noise_thresholds: tuple[ReadabilityThreshold, ...]
    extraction_method: str
    reader_identity: str
    readability_wall: ReadabilityWall
    dynamic_context: DynamicClaimContext | None = None

    def __post_init__(self) -> None:
        _require_text(self.declaration_id, field="declaration_id")
        fields = _normalize_refs(self.available_fields, field="available field")
        if not fields:
            raise ValueError("layer declarations require at least one available field")
        object.__setattr__(self, "available_fields", fields)
        _require_text(self.aperture, field="aperture")
        _require_text(self.extraction_method, field="extraction_method")
        _require_text(self.reader_identity, field="reader_identity")
        threshold_families = tuple(item.family for item in self.noise_thresholds)
        if not threshold_families:
            raise ValueError("layer declarations require at least one noise threshold")
        if len(set(threshold_families)) != len(threshold_families):
            raise ValueError("noise thresholds must name each evidence family at most once")
        object.__setattr__(
            self,
            "noise_thresholds",
            tuple(sorted(self.noise_thresholds, key=lambda item: item.family.value)),
        )
        if self.layer is LogicalLayer.ACTION_EFFECTS and self.dynamic_context is None:
            raise ValueError("action-effect layer declarations require dynamic claim context")

    def threshold_for(self, family: EvidenceFamily) -> ReadabilityThreshold | None:
        return next((item for item in self.noise_thresholds if item.family is family), None)

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "declaration_id": self.declaration_id,
            "layer": self.layer.value,
            "available_fields": list(self.available_fields),
            "aperture": self.aperture,
            "noise_thresholds": [item.to_dict() for item in self.noise_thresholds],
            "extraction_method": self.extraction_method,
            "reader_identity": self.reader_identity,
            "readability_wall": self.readability_wall.to_dict(),
            "dynamic_context": (
                self.dynamic_context.to_dict() if self.dynamic_context is not None else None
            ),
        }


@dataclass(frozen=True, slots=True)
class ValidityGate:
    """A hard validity check; failed required gates cannot be averaged away."""

    name: str
    passed: bool
    required: bool = True
    evidence_event_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_text(self.name, field="validity gate name")
        object.__setattr__(
            self,
            "evidence_event_ids",
            _normalize_refs(self.evidence_event_ids, field="validity evidence event ID"),
        )

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "name": self.name,
            "passed": self.passed,
            "required": self.required,
            "evidence_event_ids": list(self.evidence_event_ids),
        }


@dataclass(frozen=True, slots=True)
class EvidenceReading:
    """One family-specific reading in one dependency context."""

    family: EvidenceFamily
    dependency_context: str
    signal_units: int
    evidence_event_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_text(self.dependency_context, field="dependency_context")
        if (
            isinstance(self.signal_units, bool)
            or not isinstance(self.signal_units, int)
            or self.signal_units < 0
        ):
            raise ValueError("signal_units must be a non-negative integer")
        object.__setattr__(
            self,
            "evidence_event_ids",
            _normalize_refs(self.evidence_event_ids, field="reading evidence event ID"),
        )

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "family": self.family.value,
            "dependency_context": self.dependency_context,
            "signal_units": self.signal_units,
            "evidence_event_ids": list(self.evidence_event_ids),
        }


@dataclass(frozen=True, slots=True)
class LayerAssessment:
    """Evidence vector and validity gates evaluated against one declaration."""

    declaration: LayerDeclaration
    readings: tuple[EvidenceReading, ...]
    validity_gates: tuple[ValidityGate, ...]

    def __post_init__(self) -> None:
        undeclared = sorted(
            {
                reading.family.value
                for reading in self.readings
                if self.declaration.threshold_for(reading.family) is None
            }
        )
        if undeclared:
            raise ValueError("readings use undeclared evidence families: " + ", ".join(undeclared))
        gate_names = tuple(gate.name for gate in self.validity_gates)
        if len(set(gate_names)) != len(gate_names):
            raise ValueError("validity gate names must be unique")

    @property
    def required_gates_pass(self) -> bool:
        """Evaluate hard gates directly, without a weighted or averaged score."""

        return all(not gate.required or gate.passed for gate in self.validity_gates)

    @property
    def readable_evidence_families(self) -> tuple[EvidenceFamily, ...]:
        """Return independently readable families; duplicate readings do not add families."""

        families = {
            reading.family
            for reading in self.readings
            if (threshold := self.declaration.threshold_for(reading.family)) is not None
            and threshold.admits(reading.signal_units)
        }
        return tuple(sorted(families, key=lambda item: item.value))

    @property
    def distinct_dependency_contexts(self) -> tuple[str, ...]:
        return tuple(sorted({reading.dependency_context for reading in self.readings}))

    def has_independent_support(self, *, minimum_families: int = 2) -> bool:
        if (
            isinstance(minimum_families, bool)
            or not isinstance(minimum_families, int)
            or minimum_families < 1
        ):
            raise ValueError("minimum_families must be a positive integer")
        return len(self.readable_evidence_families) >= minimum_families

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "declaration": self.declaration.to_dict(),
            "readings": [item.to_dict() for item in self.readings],
            "validity_gates": [item.to_dict() for item in self.validity_gates],
            "required_gates_pass": self.required_gates_pass,
            "readable_evidence_families": [item.value for item in self.readable_evidence_families],
            "distinct_dependency_contexts": list(self.distinct_dependency_contexts),
        }


@dataclass(frozen=True, slots=True)
class ResidualDecision:
    """One explicit, bounded disposition for a lower-layer residual."""

    disposition: ResidualDisposition
    reason: ResidualReason

    def to_dict(self) -> dict[str, JSONValue]:
        return {"disposition": self.disposition.value, "reason": self.reason.value}


def assess_residual(
    assessment: LayerAssessment,
    *,
    already_explained: bool,
    changes_prediction: bool,
    changes_action_selection: bool,
    additional_detail_cost: int,
    expected_decision_value: int,
) -> ResidualDecision:
    """Promote only readable, valid, decision-relevant, economical residuals."""

    for field, value in (
        ("additional_detail_cost", additional_detail_cost),
        ("expected_decision_value", expected_decision_value),
    ):
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"{field} must be a non-negative integer")
    if already_explained:
        return ResidualDecision(ResidualDisposition.STOP, ResidualReason.ALREADY_EXPLAINED)
    if not assessment.readable_evidence_families:
        return ResidualDecision(ResidualDisposition.STOP, ResidualReason.BELOW_NOISE)
    if assessment.declaration.readability_wall.reached:
        return ResidualDecision(ResidualDisposition.STOP, ResidualReason.READABILITY_WALL)
    if not assessment.required_gates_pass:
        return ResidualDecision(ResidualDisposition.PARK, ResidualReason.VALIDITY_GATE_FAILED)
    if not changes_prediction and not changes_action_selection:
        return ResidualDecision(ResidualDisposition.PARK, ResidualReason.NO_DECISION_EFFECT)
    if additional_detail_cost > expected_decision_value:
        return ResidualDecision(ResidualDisposition.STOP, ResidualReason.COST_EXCEEDS_VALUE)
    return ResidualDecision(
        ResidualDisposition.PROMOTE,
        ResidualReason.PREDICTION_OR_ACTION_RELEVANT,
    )


__all__ = [
    "ActionWindow",
    "DynamicClaimContext",
    "EvidenceFamily",
    "EvidenceReading",
    "LayerAssessment",
    "LayerDeclaration",
    "LogicalLayer",
    "ReadabilityThreshold",
    "ReadabilityWall",
    "ResidualDecision",
    "ResidualDisposition",
    "ResidualReason",
    "ValidityGate",
    "assess_residual",
]
