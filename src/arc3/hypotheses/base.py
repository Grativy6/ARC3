"""Shared typed values for falsifiable ARC3 hypotheses.

Weights in this package are deterministic ranking aids.  They are deliberately
integer-valued and are never described as calibrated probabilities.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum

from arc3.errors import HypothesisError
from arc3.trace.canonical import normalize_json
from arc3.types import JSONValue


class HypothesisFamily(StrEnum):
    """Primary hypothesis families required by the target architecture."""

    ACTION_SEMANTICS = "action_semantics"
    CONTROLLABLE_OBJECT_IDENTITY = "controllable_object_identity"
    COLLISION_TRAVERSABILITY = "collision_traversability"
    INTERACTION_TOGGLE = "interaction_toggle"
    COORDINATE_ACTION_TARGET = "coordinate_action_target"
    STATE_TRANSITION = "state_transition"
    PROGRESS_TERMINAL = "progress_terminal"
    CANDIDATE_GOAL = "candidate_goal"
    LEVEL_INVARIANT = "level_invariant"


class HypothesisScope(StrEnum):
    """Scope ceiling for a hypothesis claim."""

    STEP = "step"
    LEVEL = "level"
    GAME = "game"
    GENERIC = "generic"


class EvidenceKind(StrEnum):
    """How an immutable source receipt bears on a hypothesis."""

    SUPPORT = "support"
    CONTRADICTION = "contradiction"
    RESIDUAL = "residual"


class Compatibility(StrEnum):
    """Deterministic relation between two candidate records."""

    COMPATIBLE = "compatible"
    INCOMPATIBLE = "incompatible"
    REDUNDANT = "redundant"


def require_text(value: object, *, field: str) -> str:
    """Return a non-empty string or reject malformed structured state."""

    if not isinstance(value, str) or not value.strip():
        raise HypothesisError(f"{field} must be a non-empty string")
    return value


def require_non_negative_int(value: object, *, field: str) -> int:
    """Return a non-negative integer, explicitly rejecting booleans."""

    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise HypothesisError(f"{field} must be a non-negative integer")
    return value


def require_int(value: object, *, field: str) -> int:
    """Return an integer, explicitly rejecting booleans."""

    if isinstance(value, bool) or not isinstance(value, int):
        raise HypothesisError(f"{field} must be an integer")
    return value


def normalize_strings(values: Iterable[str], *, field: str) -> tuple[str, ...]:
    """Validate, deduplicate, and sort identifiers or symbolic labels."""

    normalized: set[str] = set()
    for value in values:
        normalized.add(require_text(value, field=field))
    return tuple(sorted(normalized))


def normalize_string_tuple(value: object, *, field: str) -> tuple[str, ...]:
    """Parse a JSON array of strings into deterministic tuple form."""

    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise HypothesisError(f"{field} must be an array of strings")
    return normalize_strings(value, field=field)


def normalize_object(value: Mapping[str, object], *, field: str) -> dict[str, JSONValue]:
    """Normalize a machine-readable mapping without lossy coercion."""

    normalized = normalize_json(value)
    if not isinstance(normalized, dict):  # pragma: no cover - Mapping is statically an object
        raise HypothesisError(f"{field} must be an object")
    return normalized


@dataclass(frozen=True, slots=True)
class HypothesisPrediction:
    """A falsifiable outcome predicted for one possible action."""

    prediction_id: str
    action: str
    expected: dict[str, JSONValue]
    conditions: tuple[str, ...] = ()
    rank_weight: int = 0

    def __post_init__(self) -> None:
        require_text(self.prediction_id, field="prediction_id")
        require_text(self.action, field="prediction action")
        object.__setattr__(
            self,
            "expected",
            normalize_object(self.expected, field="prediction expected outcome"),
        )
        object.__setattr__(
            self,
            "conditions",
            normalize_strings(self.conditions, field="prediction condition"),
        )
        require_int(self.rank_weight, field="prediction rank_weight")

    def to_dict(self) -> dict[str, JSONValue]:
        """Return canonicalizable structured state."""

        return {
            "prediction_id": self.prediction_id,
            "action": self.action,
            "expected": self.expected,
            "conditions": list(self.conditions),
            "rank_weight": self.rank_weight,
            "weight_kind": "uncalibrated_rank",
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> HypothesisPrediction:
        """Parse a serialized prediction with strict field validation."""

        expected = value.get("expected")
        if not isinstance(expected, Mapping):
            raise HypothesisError("prediction expected outcome must be an object")
        return cls(
            prediction_id=require_text(value.get("prediction_id"), field="prediction_id"),
            action=require_text(value.get("action"), field="prediction action"),
            expected=normalize_object(expected, field="prediction expected outcome"),
            conditions=normalize_string_tuple(value.get("conditions", []), field="conditions"),
            rank_weight=require_int(value.get("rank_weight", 0), field="prediction rank_weight"),
        )


@dataclass(frozen=True, slots=True)
class EvidenceReceipt:
    """Typed pointer to immutable evidence; summaries never replace source IDs."""

    receipt_id: str
    kind: EvidenceKind
    evidence_event_ids: tuple[str, ...]
    summary: str
    observed_step: int
    rank_impact: int = 1

    def __post_init__(self) -> None:
        require_text(self.receipt_id, field="receipt_id")
        event_ids = normalize_strings(self.evidence_event_ids, field="evidence_event_id")
        if not event_ids:
            raise HypothesisError("evidence receipts require at least one source event ID")
        object.__setattr__(self, "evidence_event_ids", event_ids)
        summary = require_text(self.summary, field="evidence summary")
        if len(summary) > 512:
            raise HypothesisError("evidence summary must not exceed 512 characters")
        require_non_negative_int(self.observed_step, field="observed_step")
        if (
            isinstance(self.rank_impact, bool)
            or not isinstance(self.rank_impact, int)
            or self.rank_impact <= 0
        ):
            raise HypothesisError("rank_impact must be a positive integer")

    @property
    def signed_rank_impact(self) -> int:
        """Return the declared deterministic ranking contribution."""

        return self.rank_impact if self.kind is EvidenceKind.SUPPORT else -self.rank_impact

    def to_dict(self) -> dict[str, JSONValue]:
        """Return canonicalizable structured state."""

        return {
            "receipt_id": self.receipt_id,
            "kind": self.kind.value,
            "evidence_event_ids": list(self.evidence_event_ids),
            "summary": self.summary,
            "observed_step": self.observed_step,
            "rank_impact": self.rank_impact,
            "weight_kind": "uncalibrated_rank",
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> EvidenceReceipt:
        """Parse a serialized evidence pointer."""

        try:
            kind = EvidenceKind(require_text(value.get("kind"), field="evidence kind"))
        except ValueError as error:
            raise HypothesisError("evidence kind is not supported") from error
        return cls(
            receipt_id=require_text(value.get("receipt_id"), field="receipt_id"),
            kind=kind,
            evidence_event_ids=normalize_string_tuple(
                value.get("evidence_event_ids"), field="evidence_event_ids"
            ),
            summary=require_text(value.get("summary"), field="evidence summary"),
            observed_step=require_non_negative_int(
                value.get("observed_step"), field="observed_step"
            ),
            rank_impact=require_int(value.get("rank_impact", 1), field="rank_impact"),
        )
