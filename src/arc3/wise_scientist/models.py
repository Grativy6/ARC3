"""Trace-safe command and state values for Wise Scientist play.

The values deliberately capture concise decision summaries, not unrestricted
chain-of-thought.  Every active distinction and subgoal has an explicit path
back to the governing WIN objective.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import cast

from arc3.errors import ARC3ValidationError
from arc3.trace.canonical import is_sha256
from arc3.types import ActionName, ActionRequest, Coordinate, JSONValue

_MAX_TEXT = 1_000


class DecisionRelevance(StrEnum):
    """Current decision relevance of a distinction."""

    ACTIVE = "ACTIVE"
    RELEVANCE_UNCERTAIN = "RELEVANCE_UNCERTAIN"
    PARKED = "PARKED"


class GoalStatus(StrEnum):
    """Lifecycle status of one instrumental or investigative goal."""

    ACTIVE = "ACTIVE"
    PARKED = "PARKED"
    SUCCEEDED = "SUCCEEDED"
    ABANDONED = "ABANDONED"


class WiseRationale(StrEnum):
    """Bounded reason for spending one environment action."""

    FOLLOW_SUPPORTED_ROUTE = "FOLLOW_SUPPORTED_ROUTE"
    DISCRIMINATE_LIVE_HYPOTHESES = "DISCRIMINATE_LIVE_HYPOTHESES"
    RECOVER_FROM_FAILURE = "RECOVER_FROM_FAILURE"
    MANDATORY_RESET = "MANDATORY_RESET"


class AssessmentKind(StrEnum):
    """Relation between a pre-action prediction and returned consequence."""

    MATCHED = "MATCHED"
    PARTIAL = "PARTIAL"
    MISMATCHED = "MISMATCHED"


class RevisionKind(StrEnum):
    """Localized change to one distinction after a consequence."""

    SUPPORT = "SUPPORT"
    NARROW = "NARROW"
    PARK = "PARK"
    REOPEN = "REOPEN"
    REJECT = "REJECT"


class SubgoalUpdateKind(StrEnum):
    """Localized lifecycle update for one subgoal."""

    SUCCEED = "SUCCEED"
    ABANDON = "ABANDON"
    PARK = "PARK"
    REOPEN = "REOPEN"


def _object(value: object, *, field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise ARC3ValidationError(f"{field} must be a JSON object with string keys")
    return cast(Mapping[str, object], value)


def _items(value: object, *, field: str) -> Sequence[object]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise ARC3ValidationError(f"{field} must be a JSON array")
    return cast(Sequence[object], value)


def _text(value: object, *, field: str, maximum: int = _MAX_TEXT) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ARC3ValidationError(f"{field} must be a non-empty string")
    normalized = value.strip()
    if len(normalized) > maximum:
        raise ARC3ValidationError(f"{field} exceeds the {maximum}-character trace-safe limit")
    return normalized


def _identifier(value: object, *, field: str) -> str:
    return _text(value, field=field, maximum=160)


def _enum_value[T: StrEnum](enum_type: type[T], value: object, *, field: str) -> T:
    if not isinstance(value, str):
        raise ARC3ValidationError(f"{field} must be a string")
    try:
        return enum_type(value)
    except ValueError as error:
        allowed = ", ".join(item.value for item in enum_type)
        raise ARC3ValidationError(f"{field} must be one of: {allowed}") from error


def _unique_strings(value: object, *, field: str, minimum: int = 0) -> tuple[str, ...]:
    result = tuple(_identifier(item, field=f"{field}[]") for item in _items(value, field=field))
    if len(result) < minimum:
        raise ARC3ValidationError(f"{field} must contain at least {minimum} item(s)")
    if len(set(result)) != len(result):
        raise ARC3ValidationError(f"{field} must not contain duplicates")
    return result


def _action_request(value: object, *, field: str = "action") -> ActionRequest:
    raw = _object(value, field=field)
    action = _enum_value(ActionName, raw.get("name"), field=f"{field}.name")
    coordinate_value = raw.get("coordinate")
    coordinate: Coordinate | None = None
    if coordinate_value is not None:
        coordinate_raw = _object(coordinate_value, field=f"{field}.coordinate")
        x = coordinate_raw.get("x")
        y = coordinate_raw.get("y")
        if isinstance(x, bool) or not isinstance(x, int):
            raise ARC3ValidationError(f"{field}.coordinate.x must be an integer")
        if isinstance(y, bool) or not isinstance(y, int):
            raise ARC3ValidationError(f"{field}.coordinate.y must be an integer")
        coordinate = Coordinate(x=x, y=y)
    try:
        return ActionRequest(name=action, coordinate=coordinate)
    except ValueError as error:
        raise ARC3ValidationError(str(error)) from error


def action_to_dict(action: ActionRequest) -> dict[str, JSONValue]:
    """Serialize one normalized action request."""

    coordinate = action.coordinate
    return {
        "name": action.name.value,
        "coordinate": ({"x": coordinate.x, "y": coordinate.y} if coordinate is not None else None),
    }


@dataclass(frozen=True, slots=True)
class Prediction:
    """One live consequence prediction and its discriminating observation."""

    prediction_id: str
    consequence: str
    discriminator: str

    @classmethod
    def from_dict(cls, value: object, *, field: str = "prediction") -> Prediction:
        raw = _object(value, field=field)
        return cls(
            prediction_id=_identifier(raw.get("prediction_id"), field=f"{field}.prediction_id"),
            consequence=_text(raw.get("consequence"), field=f"{field}.consequence"),
            discriminator=_text(raw.get("discriminator"), field=f"{field}.discriminator"),
        )

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "prediction_id": self.prediction_id,
            "consequence": self.consequence,
            "discriminator": self.discriminator,
        }


@dataclass(frozen=True, slots=True)
class Distinction:
    """A decision-relevant uncertainty with a complete relevance chain."""

    distinction_id: str
    statement: str
    predictions: tuple[Prediction, ...]
    decision_that_could_change: str
    parent_goal_or_constraint_id: str
    governing_objective_id: str
    relevance: DecisionRelevance
    reopening_condition: str

    @classmethod
    def from_dict(cls, value: object, *, field: str = "distinction") -> Distinction:
        raw = _object(value, field=field)
        predictions = tuple(
            Prediction.from_dict(item, field=f"{field}.predictions[]")
            for item in _items(raw.get("predictions"), field=f"{field}.predictions")
        )
        if len(predictions) < 2:
            raise ARC3ValidationError(f"{field}.predictions must contain competing predictions")
        prediction_ids = tuple(item.prediction_id for item in predictions)
        if len(set(prediction_ids)) != len(prediction_ids):
            raise ARC3ValidationError(f"{field}.predictions must have unique IDs")
        return cls(
            distinction_id=_identifier(raw.get("distinction_id"), field=f"{field}.distinction_id"),
            statement=_text(raw.get("statement"), field=f"{field}.statement"),
            predictions=predictions,
            decision_that_could_change=_text(
                raw.get("decision_that_could_change"),
                field=f"{field}.decision_that_could_change",
            ),
            parent_goal_or_constraint_id=_identifier(
                raw.get("parent_goal_or_constraint_id"),
                field=f"{field}.parent_goal_or_constraint_id",
            ),
            governing_objective_id=_identifier(
                raw.get("governing_objective_id"),
                field=f"{field}.governing_objective_id",
            ),
            relevance=_enum_value(
                DecisionRelevance, raw.get("relevance"), field=f"{field}.relevance"
            ),
            reopening_condition=_text(
                raw.get("reopening_condition"), field=f"{field}.reopening_condition"
            ),
        )

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "distinction_id": self.distinction_id,
            "statement": self.statement,
            "predictions": [item.to_dict() for item in self.predictions],
            "decision_that_could_change": self.decision_that_could_change,
            "parent_goal_or_constraint_id": self.parent_goal_or_constraint_id,
            "governing_objective_id": self.governing_objective_id,
            "relevance": self.relevance.value,
            "reopening_condition": self.reopening_condition,
        }


@dataclass(frozen=True, slots=True)
class Subgoal:
    """A small parent-linked goal with explicit lifecycle conditions."""

    goal_id: str
    parent_goal_or_constraint_id: str
    motivation: str
    decision_that_could_change: str
    smallest_test_or_plan: str
    success_condition: str
    abandonment_condition: str
    reopening_condition: str
    status: GoalStatus = GoalStatus.ACTIVE

    @classmethod
    def from_dict(cls, value: object, *, field: str = "subgoal") -> Subgoal:
        raw = _object(value, field=field)
        status_value = raw.get("status", GoalStatus.ACTIVE.value)
        return cls(
            goal_id=_identifier(raw.get("goal_id"), field=f"{field}.goal_id"),
            parent_goal_or_constraint_id=_identifier(
                raw.get("parent_goal_or_constraint_id"),
                field=f"{field}.parent_goal_or_constraint_id",
            ),
            motivation=_text(raw.get("motivation"), field=f"{field}.motivation"),
            decision_that_could_change=_text(
                raw.get("decision_that_could_change"),
                field=f"{field}.decision_that_could_change",
            ),
            smallest_test_or_plan=_text(
                raw.get("smallest_test_or_plan"), field=f"{field}.smallest_test_or_plan"
            ),
            success_condition=_text(
                raw.get("success_condition"), field=f"{field}.success_condition"
            ),
            abandonment_condition=_text(
                raw.get("abandonment_condition"), field=f"{field}.abandonment_condition"
            ),
            reopening_condition=_text(
                raw.get("reopening_condition"), field=f"{field}.reopening_condition"
            ),
            status=_enum_value(GoalStatus, status_value, field=f"{field}.status"),
        )

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "goal_id": self.goal_id,
            "parent_goal_or_constraint_id": self.parent_goal_or_constraint_id,
            "motivation": self.motivation,
            "decision_that_could_change": self.decision_that_could_change,
            "smallest_test_or_plan": self.smallest_test_or_plan,
            "success_condition": self.success_condition,
            "abandonment_condition": self.abandonment_condition,
            "reopening_condition": self.reopening_condition,
            "status": self.status.value,
        }


@dataclass(frozen=True, slots=True)
class ActionAlternative:
    """One concise alternative considered before the selected action."""

    action: ActionRequest
    summary: str

    @classmethod
    def from_dict(cls, value: object, *, field: str = "alternative") -> ActionAlternative:
        raw = _object(value, field=field)
        return cls(
            action=_action_request(raw.get("action"), field=f"{field}.action"),
            summary=_text(raw.get("summary"), field=f"{field}.summary", maximum=500),
        )

    def to_dict(self) -> dict[str, JSONValue]:
        return {"action": action_to_dict(self.action), "summary": self.summary}


@dataclass(frozen=True, slots=True)
class ScanCommand:
    """No-action distinction scan for an initial or substantially new stage."""

    observation_hash: str
    stage_summary: str
    distinctions: tuple[Distinction, ...]
    subgoals: tuple[Subgoal, ...]

    @classmethod
    def from_dict(cls, value: object) -> ScanCommand:
        raw = _object(value, field="scan")
        observation_hash = _text(
            raw.get("observation_hash"), field="scan.observation_hash", maximum=80
        )
        if not is_sha256(observation_hash):
            raise ARC3ValidationError("scan.observation_hash must be a tagged SHA-256")
        distinctions = tuple(
            Distinction.from_dict(item, field="scan.distinctions[]")
            for item in _items(raw.get("distinctions"), field="scan.distinctions")
        )
        subgoals = tuple(
            Subgoal.from_dict(item, field="scan.subgoals[]")
            for item in _items(raw.get("subgoals"), field="scan.subgoals")
        )
        if not subgoals:
            raise ARC3ValidationError("scan.subgoals must contain at least one subgoal")
        return cls(
            observation_hash=observation_hash,
            stage_summary=_text(raw.get("stage_summary"), field="scan.stage_summary"),
            distinctions=distinctions,
            subgoals=subgoals,
        )

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "observation_hash": self.observation_hash,
            "stage_summary": self.stage_summary,
            "distinctions": [item.to_dict() for item in self.distinctions],
            "subgoals": [item.to_dict() for item in self.subgoals],
        }


@dataclass(frozen=True, slots=True)
class ActCommand:
    """One predicted, relevance-linked environment action."""

    observation_hash: str
    action: ActionRequest
    active_goal_id: str
    distinction_ids: tuple[str, ...]
    predicted_consequence: str
    alternatives: tuple[ActionAlternative, ...]
    rationale: WiseRationale
    rationale_summary: str

    @classmethod
    def from_dict(cls, value: object) -> ActCommand:
        raw = _object(value, field="act")
        observation_hash = _text(
            raw.get("observation_hash"), field="act.observation_hash", maximum=80
        )
        if not is_sha256(observation_hash):
            raise ARC3ValidationError("act.observation_hash must be a tagged SHA-256")
        alternatives = tuple(
            ActionAlternative.from_dict(item, field="act.alternatives[]")
            for item in _items(raw.get("alternatives"), field="act.alternatives")
        )
        rationale = _enum_value(WiseRationale, raw.get("rationale"), field="act.rationale")
        if not alternatives and rationale is not WiseRationale.MANDATORY_RESET:
            raise ARC3ValidationError("act.alternatives may be empty only for a mandatory RESET")
        distinction_ids = _unique_strings(
            raw.get("distinction_ids", []), field="act.distinction_ids"
        )
        if not distinction_ids and rationale not in {
            WiseRationale.FOLLOW_SUPPORTED_ROUTE,
            WiseRationale.MANDATORY_RESET,
        }:
            raise ARC3ValidationError(
                "a discriminating or recovery action requires an implicated distinction"
            )
        return cls(
            observation_hash=observation_hash,
            action=_action_request(raw.get("action")),
            active_goal_id=_identifier(raw.get("active_goal_id"), field="act.active_goal_id"),
            distinction_ids=distinction_ids,
            predicted_consequence=_text(
                raw.get("predicted_consequence"), field="act.predicted_consequence"
            ),
            alternatives=alternatives,
            rationale=rationale,
            rationale_summary=_text(
                raw.get("rationale_summary"), field="act.rationale_summary", maximum=500
            ),
        )

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "observation_hash": self.observation_hash,
            "action": action_to_dict(self.action),
            "active_goal_id": self.active_goal_id,
            "distinction_ids": list(self.distinction_ids),
            "predicted_consequence": self.predicted_consequence,
            "alternatives": [item.to_dict() for item in self.alternatives],
            "rationale": self.rationale.value,
            "rationale_summary": self.rationale_summary,
        }


@dataclass(frozen=True, slots=True)
class DistinctionRevision:
    """One localized update, leaving unrelated distinctions untouched."""

    distinction_id: str
    kind: RevisionKind
    summary: str

    @classmethod
    def from_dict(
        cls, value: object, *, field: str = "distinction_revision"
    ) -> DistinctionRevision:
        raw = _object(value, field=field)
        return cls(
            distinction_id=_identifier(raw.get("distinction_id"), field=f"{field}.distinction_id"),
            kind=_enum_value(RevisionKind, raw.get("kind"), field=f"{field}.kind"),
            summary=_text(raw.get("summary"), field=f"{field}.summary", maximum=500),
        )

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "distinction_id": self.distinction_id,
            "kind": self.kind.value,
            "summary": self.summary,
        }


@dataclass(frozen=True, slots=True)
class GoalUpdate:
    """One explicit subgoal lifecycle update."""

    goal_id: str
    kind: SubgoalUpdateKind
    summary: str

    @classmethod
    def from_dict(cls, value: object, *, field: str = "goal_update") -> GoalUpdate:
        raw = _object(value, field=field)
        return cls(
            goal_id=_identifier(raw.get("goal_id"), field=f"{field}.goal_id"),
            kind=_enum_value(SubgoalUpdateKind, raw.get("kind"), field=f"{field}.kind"),
            summary=_text(raw.get("summary"), field=f"{field}.summary", maximum=500),
        )

    def to_dict(self) -> dict[str, JSONValue]:
        return {"goal_id": self.goal_id, "kind": self.kind.value, "summary": self.summary}


@dataclass(frozen=True, slots=True)
class AssessCommand:
    """Post-consequence residual and smallest-sufficient model update."""

    observation_hash: str
    assessment: AssessmentKind
    residual: str
    preserved_distinction_ids: tuple[str, ...]
    distinction_revisions: tuple[DistinctionRevision, ...]
    goal_updates: tuple[GoalUpdate, ...]
    new_distinctions: tuple[Distinction, ...]
    new_subgoals: tuple[Subgoal, ...]

    @classmethod
    def from_dict(cls, value: object) -> AssessCommand:
        raw = _object(value, field="assess")
        observation_hash = _text(
            raw.get("observation_hash"), field="assess.observation_hash", maximum=80
        )
        if not is_sha256(observation_hash):
            raise ARC3ValidationError("assess.observation_hash must be a tagged SHA-256")
        return cls(
            observation_hash=observation_hash,
            assessment=_enum_value(
                AssessmentKind, raw.get("assessment"), field="assess.assessment"
            ),
            residual=_text(raw.get("residual"), field="assess.residual"),
            preserved_distinction_ids=_unique_strings(
                raw.get("preserved_distinction_ids", []),
                field="assess.preserved_distinction_ids",
            ),
            distinction_revisions=tuple(
                DistinctionRevision.from_dict(item, field="assess.distinction_revisions[]")
                for item in _items(
                    raw.get("distinction_revisions", []),
                    field="assess.distinction_revisions",
                )
            ),
            goal_updates=tuple(
                GoalUpdate.from_dict(item, field="assess.goal_updates[]")
                for item in _items(raw.get("goal_updates", []), field="assess.goal_updates")
            ),
            new_distinctions=tuple(
                Distinction.from_dict(item, field="assess.new_distinctions[]")
                for item in _items(raw.get("new_distinctions", []), field="assess.new_distinctions")
            ),
            new_subgoals=tuple(
                Subgoal.from_dict(item, field="assess.new_subgoals[]")
                for item in _items(raw.get("new_subgoals", []), field="assess.new_subgoals")
            ),
        )

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "observation_hash": self.observation_hash,
            "assessment": self.assessment.value,
            "residual": self.residual,
            "preserved_distinction_ids": list(self.preserved_distinction_ids),
            "distinction_revisions": [item.to_dict() for item in self.distinction_revisions],
            "goal_updates": [item.to_dict() for item in self.goal_updates],
            "new_distinctions": [item.to_dict() for item in self.new_distinctions],
            "new_subgoals": [item.to_dict() for item in self.new_subgoals],
        }


__all__ = [
    "ActCommand",
    "ActionAlternative",
    "AssessCommand",
    "AssessmentKind",
    "DecisionRelevance",
    "Distinction",
    "DistinctionRevision",
    "GoalStatus",
    "GoalUpdate",
    "Prediction",
    "RevisionKind",
    "ScanCommand",
    "Subgoal",
    "SubgoalUpdateKind",
    "WiseRationale",
    "action_to_dict",
]
