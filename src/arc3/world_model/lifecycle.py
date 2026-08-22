"""Typed, bounded mechanics-change and epoch lifecycle state.

The lifecycle is derived from immutable consequence and hypothesis receipts.  It
never edits those receipts, and it deliberately keeps candidate change points
separate from confirmed mechanics epochs.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import cast

from arc3.errors import WorldModelError
from arc3.trace.canonical import normalize_json, sha256_json
from arc3.types import JSONValue


class MechanicsChangeStatus(StrEnum):
    """Lifecycle state of one provisional change point."""

    CANDIDATE = "CANDIDATE"
    CONFIRMED = "CONFIRMED"
    RESOLVED_NOISE = "RESOLVED_NOISE"
    CONTRADICTED = "CONTRADICTED"


class MechanicsChangeDomain(StrEnum):
    """Identity domain used to accumulate independent change evidence."""

    OPAQUE_HANDLE = "OPAQUE_HANDLE"
    ACTION_MAPPING = "ACTION_MAPPING"
    DESTINATION_ROLE = "DESTINATION_ROLE"


class MechanicsEpochStatus(StrEnum):
    """Whether an epoch currently has action authority."""

    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"


def _strings(values: Iterable[str], *, field: str) -> tuple[str, ...]:
    normalized = tuple(sorted(set(values)))
    if any(not isinstance(item, str) or not item.strip() for item in normalized):
        raise WorldModelError(f"{field} must contain non-empty strings")
    return normalized


def _non_negative(value: object, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise WorldModelError(f"{field} must be a non-negative integer")
    return value


def _required_text(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise WorldModelError(f"{field} must be a non-empty string")
    return value


def _string_array(value: object, *, field: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise WorldModelError(f"{field} must be an array of strings")
    return _strings(cast(list[str], value), field=field)


def _ordered_support_strings(
    values: Iterable[str],
    *,
    field: str,
    unique: bool,
) -> tuple[str, ...]:
    """Validate one arrival-ordered successor-support field without normalizing it."""

    ordered = tuple(values)
    if any(not isinstance(item, str) or not item.strip() for item in ordered):
        raise WorldModelError(f"{field} must contain non-empty strings")
    if unique and len(set(ordered)) != len(ordered):
        raise WorldModelError(f"{field} must contain unique strings")
    return ordered


def _ordered_support_array(
    value: object,
    *,
    field: str,
    unique: bool,
) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise WorldModelError(f"{field} must be an array of strings")
    return _ordered_support_strings(cast(list[str], value), field=field, unique=unique)


def _candidate_identifier(
    *,
    level_index: int,
    predecessor_epoch_id: str,
    change_domain: MechanicsChangeDomain,
    opaque_handle: str,
    affected_hypothesis_ids: Iterable[str],
    predecessor_effect_signature: str,
    successor_effect_signature: str,
    observation_condition_signature: str,
    opened_step: int,
) -> str:
    domain_identity: JSONValue
    if change_domain is MechanicsChangeDomain.OPAQUE_HANDLE:
        domain_identity = opaque_handle
    elif change_domain is MechanicsChangeDomain.ACTION_MAPPING:
        domain_identity = "global-action-mapping"
    else:
        domain_identity = list(_strings(affected_hypothesis_ids, field="affected_hypothesis_ids"))
    digest = sha256_json(
        {
            "level_index": level_index,
            "predecessor_epoch_id": predecessor_epoch_id,
            "change_domain": change_domain.value,
            "domain_identity": domain_identity,
            "predecessor_effect_signature": predecessor_effect_signature,
            "successor_effect_signature": successor_effect_signature,
            "observation_condition_signature": observation_condition_signature,
            "opened_step": opened_step,
        }
    ).removeprefix("sha256:")[:24]
    return f"mechanics-change:{digest}"


def _live_domains_overlap(
    *,
    left_domain: MechanicsChangeDomain,
    left_handle: str,
    left_hypothesis_ids: Iterable[str],
    right_domain: MechanicsChangeDomain,
    right_handle: str,
    right_hypothesis_ids: Iterable[str],
) -> bool:
    """Whether two live candidates claim the same typed affected domain."""

    if left_domain is not right_domain:
        return False
    if left_domain is MechanicsChangeDomain.OPAQUE_HANDLE:
        return left_handle == right_handle
    if left_domain is MechanicsChangeDomain.ACTION_MAPPING:
        return True
    return bool(set(left_hypothesis_ids) & set(right_hypothesis_ids))


@dataclass(frozen=True, slots=True)
class MechanicsChangeCandidate:
    """A revisable possible boundary opened by an affected-rule contradiction."""

    candidate_id: str
    level_index: int
    predecessor_epoch_id: str
    affected_hypothesis_ids: tuple[str, ...]
    affected_model_ids: tuple[str, ...]
    first_contradiction_event_id: str
    supporting_contradiction_event_ids: tuple[str, ...]
    provisional_status: MechanicsChangeStatus
    opened_step: int
    last_tested_step: int
    change_domain: MechanicsChangeDomain
    opaque_handle: str
    predecessor_effect_signature: str
    successor_effect_signature: str
    observation_condition_signature: str
    supporting_successor_transition_ids: tuple[str, ...]
    supporting_discrimination_context_ids: tuple[str, ...]
    predecessor_recovery_event_ids: tuple[str, ...] = ()
    invalidated_plan_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for field, value in (
            ("candidate_id", self.candidate_id),
            ("predecessor_epoch_id", self.predecessor_epoch_id),
            ("first_contradiction_event_id", self.first_contradiction_event_id),
            ("opaque_handle", self.opaque_handle),
            ("predecessor_effect_signature", self.predecessor_effect_signature),
            ("successor_effect_signature", self.successor_effect_signature),
            ("observation_condition_signature", self.observation_condition_signature),
        ):
            _required_text(value, field=field)
        _non_negative(self.level_index, field="level_index")
        _non_negative(self.opened_step, field="opened_step")
        _non_negative(self.last_tested_step, field="last_tested_step")
        if self.last_tested_step < self.opened_step:
            raise WorldModelError("last_tested_step cannot precede opened_step")
        if self.predecessor_effect_signature == self.successor_effect_signature:
            raise WorldModelError("mechanics predecessor and successor effects must differ")
        object.__setattr__(
            self,
            "affected_hypothesis_ids",
            _strings(self.affected_hypothesis_ids, field="affected_hypothesis_ids"),
        )
        object.__setattr__(
            self,
            "affected_model_ids",
            _strings(self.affected_model_ids, field="affected_model_ids"),
        )
        if not self.affected_hypothesis_ids or not self.affected_model_ids:
            raise WorldModelError("a mechanics candidate requires affected rules and models")
        supporting = _ordered_support_strings(
            self.supporting_contradiction_event_ids,
            field="supporting_contradiction_event_ids",
            unique=True,
        )
        if not supporting or supporting[0] != self.first_contradiction_event_id:
            raise WorldModelError("first contradiction must be support index zero")
        object.__setattr__(self, "supporting_contradiction_event_ids", supporting)
        successor_transitions = _ordered_support_strings(
            self.supporting_successor_transition_ids,
            field="supporting_successor_transition_ids",
            unique=True,
        )
        if not successor_transitions:
            raise WorldModelError("a mechanics candidate requires its opening transition")
        object.__setattr__(
            self,
            "supporting_successor_transition_ids",
            successor_transitions,
        )
        discrimination_contexts = _ordered_support_strings(
            self.supporting_discrimination_context_ids,
            field="supporting_discrimination_context_ids",
            unique=False,
        )
        if not discrimination_contexts:
            raise WorldModelError("a mechanics candidate requires its opening context")
        object.__setattr__(
            self,
            "supporting_discrimination_context_ids",
            discrimination_contexts,
        )
        if not (len(supporting) == len(successor_transitions) == len(discrimination_contexts)):
            raise WorldModelError("mechanics successor support arrays must have equal lengths")
        object.__setattr__(
            self,
            "predecessor_recovery_event_ids",
            _ordered_support_strings(
                self.predecessor_recovery_event_ids,
                field="predecessor_recovery_event_ids",
                unique=True,
            ),
        )
        object.__setattr__(
            self,
            "invalidated_plan_ids",
            _strings(self.invalidated_plan_ids, field="invalidated_plan_ids"),
        )

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "candidate_id": self.candidate_id,
            "level_index": self.level_index,
            "predecessor_epoch_id": self.predecessor_epoch_id,
            "affected_hypothesis_ids": list(self.affected_hypothesis_ids),
            "affected_model_ids": list(self.affected_model_ids),
            "first_contradiction_event_id": self.first_contradiction_event_id,
            "supporting_contradiction_event_ids": list(self.supporting_contradiction_event_ids),
            "provisional_status": self.provisional_status.value,
            "opened_step": self.opened_step,
            "last_tested_step": self.last_tested_step,
            "change_domain": self.change_domain.value,
            "opaque_handle": self.opaque_handle,
            "predecessor_effect_signature": self.predecessor_effect_signature,
            "successor_effect_signature": self.successor_effect_signature,
            "observation_condition_signature": self.observation_condition_signature,
            "supporting_successor_transition_ids": list(self.supporting_successor_transition_ids),
            "supporting_discrimination_context_ids": list(
                self.supporting_discrimination_context_ids
            ),
            "predecessor_recovery_event_ids": list(self.predecessor_recovery_event_ids),
            "invalidated_plan_ids": list(self.invalidated_plan_ids),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> MechanicsChangeCandidate:
        try:
            status = MechanicsChangeStatus(
                _required_text(value.get("provisional_status"), field="provisional_status")
            )
        except ValueError as error:
            raise WorldModelError("unsupported mechanics change status") from error
        try:
            domain = MechanicsChangeDomain(
                _required_text(value.get("change_domain"), field="change_domain")
            )
        except ValueError as error:
            raise WorldModelError("unsupported mechanics change domain") from error
        return cls(
            candidate_id=_required_text(value.get("candidate_id"), field="candidate_id"),
            level_index=_non_negative(value.get("level_index"), field="level_index"),
            predecessor_epoch_id=_required_text(
                value.get("predecessor_epoch_id"), field="predecessor_epoch_id"
            ),
            affected_hypothesis_ids=_string_array(
                value.get("affected_hypothesis_ids"), field="affected_hypothesis_ids"
            ),
            affected_model_ids=_string_array(
                value.get("affected_model_ids"), field="affected_model_ids"
            ),
            first_contradiction_event_id=_required_text(
                value.get("first_contradiction_event_id"),
                field="first_contradiction_event_id",
            ),
            supporting_contradiction_event_ids=_ordered_support_array(
                value.get("supporting_contradiction_event_ids"),
                field="supporting_contradiction_event_ids",
                unique=True,
            ),
            provisional_status=status,
            opened_step=_non_negative(value.get("opened_step"), field="opened_step"),
            last_tested_step=_non_negative(value.get("last_tested_step"), field="last_tested_step"),
            change_domain=domain,
            opaque_handle=_required_text(value.get("opaque_handle"), field="opaque_handle"),
            predecessor_effect_signature=_required_text(
                value.get("predecessor_effect_signature"),
                field="predecessor_effect_signature",
            ),
            successor_effect_signature=_required_text(
                value.get("successor_effect_signature"), field="successor_effect_signature"
            ),
            observation_condition_signature=_required_text(
                value.get("observation_condition_signature"),
                field="observation_condition_signature",
            ),
            supporting_successor_transition_ids=_ordered_support_array(
                value.get("supporting_successor_transition_ids"),
                field="supporting_successor_transition_ids",
                unique=True,
            ),
            supporting_discrimination_context_ids=_ordered_support_array(
                value.get("supporting_discrimination_context_ids"),
                field="supporting_discrimination_context_ids",
                unique=False,
            ),
            predecessor_recovery_event_ids=_ordered_support_array(
                value.get("predecessor_recovery_event_ids", []),
                field="predecessor_recovery_event_ids",
                unique=True,
            ),
            invalidated_plan_ids=_string_array(
                value.get("invalidated_plan_ids", []), field="invalidated_plan_ids"
            ),
        )


@dataclass(frozen=True, slots=True)
class MechanicsEpoch:
    """One immutable-lineage mechanics scope with replaceable active members."""

    epoch_id: str
    level_index: int
    epoch_index: int
    parent_epoch_id: str | None
    start_transition_id: str | None
    caused_by_change_candidate_id: str | None
    active_hypothesis_ids: tuple[str, ...]
    active_model_ids: tuple[str, ...]
    status: MechanicsEpochStatus

    def __post_init__(self) -> None:
        _required_text(self.epoch_id, field="epoch_id")
        _non_negative(self.level_index, field="level_index")
        _non_negative(self.epoch_index, field="epoch_index")
        for field, value in (
            ("parent_epoch_id", self.parent_epoch_id),
            ("start_transition_id", self.start_transition_id),
            ("caused_by_change_candidate_id", self.caused_by_change_candidate_id),
        ):
            if value is not None:
                _required_text(value, field=field)
        if self.epoch_index == 0 and self.parent_epoch_id is not None:
            raise WorldModelError("initial mechanics epoch cannot have a parent")
        if self.epoch_index == 0 and any(
            item is not None
            for item in (self.start_transition_id, self.caused_by_change_candidate_id)
        ):
            raise WorldModelError("initial mechanics epoch cannot have a change boundary")
        if self.epoch_index > 0 and any(
            item is None
            for item in (
                self.parent_epoch_id,
                self.start_transition_id,
                self.caused_by_change_candidate_id,
            )
        ):
            raise WorldModelError("successor mechanics epoch requires complete boundary links")
        expected_id = f"mechanics-epoch:L{self.level_index}:{self.epoch_index:04d}"
        if self.epoch_id != expected_id:
            raise WorldModelError("mechanics epoch identity disagrees with level/index")
        object.__setattr__(
            self,
            "active_hypothesis_ids",
            _strings(self.active_hypothesis_ids, field="active_hypothesis_ids"),
        )
        object.__setattr__(
            self,
            "active_model_ids",
            _strings(self.active_model_ids, field="active_model_ids"),
        )

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "epoch_id": self.epoch_id,
            "level_index": self.level_index,
            "epoch_index": self.epoch_index,
            "parent_epoch_id": self.parent_epoch_id,
            "start_transition_id": self.start_transition_id,
            "caused_by_change_candidate_id": self.caused_by_change_candidate_id,
            "active_hypothesis_ids": list(self.active_hypothesis_ids),
            "active_model_ids": list(self.active_model_ids),
            "status": self.status.value,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> MechanicsEpoch:
        try:
            status = MechanicsEpochStatus(_required_text(value.get("status"), field="epoch status"))
        except ValueError as error:
            raise WorldModelError("unsupported mechanics epoch status") from error
        nullable: dict[str, str | None] = {}
        for field in (
            "parent_epoch_id",
            "start_transition_id",
            "caused_by_change_candidate_id",
        ):
            raw = value.get(field)
            if raw is not None and not isinstance(raw, str):
                raise WorldModelError(f"{field} must be a string or null")
            nullable[field] = raw
        return cls(
            epoch_id=_required_text(value.get("epoch_id"), field="epoch_id"),
            level_index=_non_negative(value.get("level_index"), field="level_index"),
            epoch_index=_non_negative(value.get("epoch_index"), field="epoch_index"),
            parent_epoch_id=nullable["parent_epoch_id"],
            start_transition_id=nullable["start_transition_id"],
            caused_by_change_candidate_id=nullable["caused_by_change_candidate_id"],
            active_hypothesis_ids=_string_array(
                value.get("active_hypothesis_ids"), field="active_hypothesis_ids"
            ),
            active_model_ids=_string_array(value.get("active_model_ids"), field="active_model_ids"),
            status=status,
        )


class MechanicsLifecycle:
    """Bounded event-derived mechanics epochs and provisional change points."""

    SCHEMA = "arc3.mechanics-lifecycle.v0.1"
    MAX_EPOCHS_PER_LEVEL = 4
    MAX_LIVE_CHANGE_CANDIDATES = 8
    MAX_TRANSITIONS_PER_EPOCH = 64

    def __init__(self, *, level_index: int = 0) -> None:
        _non_negative(level_index, field="level_index")
        initial = self._initial_epoch(level_index)
        self._epochs: dict[str, MechanicsEpoch] = {initial.epoch_id: initial}
        self._active_epoch_by_level: dict[int, str] = {level_index: initial.epoch_id}
        self._candidates: dict[str, MechanicsChangeCandidate] = {}
        self._hypothesis_epochs: dict[str, str] = {}
        self._model_epochs: dict[str, str] = {}
        self._transition_epochs: dict[str, str] = {}

    @staticmethod
    def _initial_epoch(level_index: int) -> MechanicsEpoch:
        return MechanicsEpoch(
            epoch_id=f"mechanics-epoch:L{level_index}:0000",
            level_index=level_index,
            epoch_index=0,
            parent_epoch_id=None,
            start_transition_id=None,
            caused_by_change_candidate_id=None,
            active_hypothesis_ids=(),
            active_model_ids=(),
            status=MechanicsEpochStatus.ACTIVE,
        )

    def start_level(self, level_index: int) -> MechanicsEpoch:
        """Select or create the initial mechanics scope for a level."""

        _non_negative(level_index, field="level_index")
        known = self._active_epoch_by_level.get(level_index)
        if known is None:
            initial = self._initial_epoch(level_index)
            self._epochs[initial.epoch_id] = initial
            self._active_epoch_by_level[level_index] = initial.epoch_id
            return initial
        return self._epochs[known]

    def active_epoch(self, level_index: int) -> MechanicsEpoch:
        return self.start_level(level_index)

    def epoch(self, epoch_id: str) -> MechanicsEpoch:
        try:
            return self._epochs[epoch_id]
        except KeyError as error:
            raise WorldModelError(f"unknown mechanics epoch: {epoch_id}") from error

    def candidates(self) -> tuple[MechanicsChangeCandidate, ...]:
        return tuple(self._candidates[key] for key in sorted(self._candidates))

    def candidate(self, candidate_id: str) -> MechanicsChangeCandidate:
        try:
            return self._candidates[candidate_id]
        except KeyError as error:
            raise WorldModelError(f"unknown mechanics change candidate: {candidate_id}") from error

    def live_candidate(
        self,
        *,
        level_index: int,
        opaque_handle: str,
        affected_hypothesis_ids: Iterable[str] = (),
    ) -> MechanicsChangeCandidate | None:
        epoch_id = self.active_epoch(level_index).epoch_id
        affected = set(affected_hypothesis_ids)
        live = tuple(
            candidate
            for candidate in self._candidates.values()
            if candidate.level_index == level_index
            and candidate.predecessor_epoch_id == epoch_id
            and candidate.provisional_status is MechanicsChangeStatus.CANDIDATE
            and (
                (
                    candidate.change_domain is MechanicsChangeDomain.OPAQUE_HANDLE
                    and candidate.opaque_handle == opaque_handle
                )
                or candidate.change_domain is MechanicsChangeDomain.ACTION_MAPPING
                or (
                    candidate.change_domain is MechanicsChangeDomain.DESTINATION_ROLE
                    and (
                        bool(affected & set(candidate.affected_hypothesis_ids))
                        or (not affected and candidate.opaque_handle == opaque_handle)
                    )
                )
            )
        )
        if len(live) > 1:
            raise WorldModelError("multiple live mechanics candidates share one affected domain")
        return live[0] if live else None

    def open_candidate(
        self,
        *,
        level_index: int,
        change_domain: MechanicsChangeDomain,
        opaque_handle: str,
        predecessor_effect_signature: str,
        successor_effect_signature: str,
        observation_condition_signature: str,
        affected_hypothesis_ids: Iterable[str],
        affected_model_ids: Iterable[str],
        contradiction_event_id: str,
        contradiction_transition_id: str,
        discrimination_context_id: str,
        invalidated_plan_ids: Iterable[str],
        opened_step: int,
    ) -> MechanicsChangeCandidate:
        affected_hypotheses = _strings(affected_hypothesis_ids, field="affected_hypothesis_ids")
        affected_models = _strings(affected_model_ids, field="affected_model_ids")
        invalidated_plans = _strings(invalidated_plan_ids, field="invalidated_plan_ids")
        if not affected_hypotheses or not affected_models:
            raise WorldModelError("a mechanics candidate requires affected rules and models")
        live_count = sum(
            item.provisional_status is MechanicsChangeStatus.CANDIDATE
            for item in self._candidates.values()
        )
        if live_count >= self.MAX_LIVE_CHANGE_CANDIDATES:
            raise WorldModelError("live mechanics change-candidate bound exceeded")
        epoch = self.active_epoch(level_index)
        if any(
            self._hypothesis_epochs.get(identifier) != epoch.epoch_id
            for identifier in affected_hypotheses
        ):
            raise WorldModelError("affected hypothesis is outside the predecessor epoch")
        if any(
            self._model_epochs.get(identifier) != epoch.epoch_id for identifier in affected_models
        ):
            raise WorldModelError("affected model is outside the predecessor epoch")
        if any(
            item.level_index == level_index
            and item.predecessor_epoch_id == epoch.epoch_id
            and item.provisional_status is MechanicsChangeStatus.CANDIDATE
            and _live_domains_overlap(
                left_domain=item.change_domain,
                left_handle=item.opaque_handle,
                left_hypothesis_ids=item.affected_hypothesis_ids,
                right_domain=change_domain,
                right_handle=opaque_handle,
                right_hypothesis_ids=affected_hypotheses,
            )
            for item in self._candidates.values()
        ):
            raise WorldModelError("a live mechanics candidate already covers this domain")
        _required_text(observation_condition_signature, field="observation_condition_signature")
        _required_text(discrimination_context_id, field="discrimination_context_id")
        if self._transition_epochs.get(contradiction_transition_id) != epoch.epoch_id:
            raise WorldModelError("candidate opening transition is outside its predecessor epoch")
        candidate = MechanicsChangeCandidate(
            candidate_id=_candidate_identifier(
                level_index=level_index,
                predecessor_epoch_id=epoch.epoch_id,
                change_domain=change_domain,
                opaque_handle=opaque_handle,
                affected_hypothesis_ids=affected_hypotheses,
                predecessor_effect_signature=predecessor_effect_signature,
                successor_effect_signature=successor_effect_signature,
                observation_condition_signature=observation_condition_signature,
                opened_step=opened_step,
            ),
            level_index=level_index,
            predecessor_epoch_id=epoch.epoch_id,
            affected_hypothesis_ids=affected_hypotheses,
            affected_model_ids=affected_models,
            first_contradiction_event_id=contradiction_event_id,
            supporting_contradiction_event_ids=(contradiction_event_id,),
            provisional_status=MechanicsChangeStatus.CANDIDATE,
            opened_step=opened_step,
            last_tested_step=opened_step,
            change_domain=change_domain,
            opaque_handle=opaque_handle,
            predecessor_effect_signature=predecessor_effect_signature,
            successor_effect_signature=successor_effect_signature,
            observation_condition_signature=observation_condition_signature,
            supporting_successor_transition_ids=(contradiction_transition_id,),
            supporting_discrimination_context_ids=(discrimination_context_id,),
            invalidated_plan_ids=invalidated_plans,
        )
        self._candidates[candidate.candidate_id] = candidate
        return candidate

    def successor_support_is_new(
        self,
        candidate_id: str,
        *,
        contradiction_event_id: str,
        contradiction_transition_id: str,
        discrimination_context_id: str,
        successor_effect_signature: str,
        observation_condition_signature: str,
    ) -> bool:
        """Validate a support triple and report whether it would add new evidence."""

        candidate = self.candidate(candidate_id)
        if candidate.provisional_status is not MechanicsChangeStatus.CANDIDATE:
            raise WorldModelError("only a live change candidate accepts successor support")
        if successor_effect_signature != candidate.successor_effect_signature:
            raise WorldModelError("successor support has a different effect signature")
        if observation_condition_signature != candidate.observation_condition_signature:
            raise WorldModelError("successor support has a different observation condition")
        if (
            self._transition_epochs.get(contradiction_transition_id)
            != candidate.predecessor_epoch_id
        ):
            raise WorldModelError("successor support transition is outside the predecessor epoch")
        _required_text(contradiction_event_id, field="contradiction_event_id")
        _required_text(contradiction_transition_id, field="contradiction_transition_id")
        _required_text(discrimination_context_id, field="discrimination_context_id")
        contradiction_index = next(
            (
                index
                for index, identifier in enumerate(candidate.supporting_contradiction_event_ids)
                if identifier == contradiction_event_id
            ),
            None,
        )
        transition_index = next(
            (
                index
                for index, identifier in enumerate(candidate.supporting_successor_transition_ids)
                if identifier == contradiction_transition_id
            ),
            None,
        )
        if contradiction_index is not None or transition_index is not None:
            if (
                contradiction_index is not None
                and contradiction_index == transition_index
                and candidate.supporting_discrimination_context_ids[contradiction_index]
                == discrimination_context_id
            ):
                return False
            raise WorldModelError(
                "successor support partially duplicates or mismatches an existing receipt"
            )
        return True

    def support_successor(
        self,
        candidate_id: str,
        *,
        contradiction_event_id: str,
        contradiction_transition_id: str,
        discrimination_context_id: str,
        successor_effect_signature: str,
        observation_condition_signature: str,
        observed_step: int,
    ) -> MechanicsChangeCandidate:
        candidate = self.candidate(candidate_id)
        if not self.successor_support_is_new(
            candidate_id,
            contradiction_event_id=contradiction_event_id,
            contradiction_transition_id=contradiction_transition_id,
            discrimination_context_id=discrimination_context_id,
            successor_effect_signature=successor_effect_signature,
            observation_condition_signature=observation_condition_signature,
        ):
            return candidate
        supporting_events = (
            *candidate.supporting_contradiction_event_ids,
            contradiction_event_id,
        )
        supporting_transitions = (
            *candidate.supporting_successor_transition_ids,
            contradiction_transition_id,
        )
        supporting_contexts = (
            *candidate.supporting_discrimination_context_ids,
            discrimination_context_id,
        )
        context_gate_met = (
            candidate.change_domain is MechanicsChangeDomain.OPAQUE_HANDLE
            or len(set(supporting_contexts)) >= 2
        )
        updated = replace(
            candidate,
            supporting_contradiction_event_ids=supporting_events,
            supporting_successor_transition_ids=supporting_transitions,
            supporting_discrimination_context_ids=supporting_contexts,
            provisional_status=(
                MechanicsChangeStatus.CONFIRMED
                if (
                    len(supporting_events) >= 2
                    and len(supporting_transitions) >= 2
                    and context_gate_met
                )
                else MechanicsChangeStatus.CANDIDATE
            ),
            last_tested_step=observed_step,
        )
        self._candidates[candidate_id] = updated
        return updated

    def support_predecessor(
        self, candidate_id: str, *, evidence_event_id: str, observed_step: int
    ) -> MechanicsChangeCandidate:
        candidate = self.candidate(candidate_id)
        if candidate.provisional_status is not MechanicsChangeStatus.CANDIDATE:
            raise WorldModelError("only a live change candidate accepts predecessor recovery")
        _required_text(evidence_event_id, field="evidence_event_id")
        if evidence_event_id in candidate.predecessor_recovery_event_ids:
            return candidate
        receipts = (*candidate.predecessor_recovery_event_ids, evidence_event_id)
        updated = replace(
            candidate,
            predecessor_recovery_event_ids=receipts,
            provisional_status=(
                MechanicsChangeStatus.RESOLVED_NOISE
                if len(receipts) >= 2
                else MechanicsChangeStatus.CANDIDATE
            ),
            last_tested_step=observed_step,
        )
        self._candidates[candidate_id] = updated
        return updated

    def contradict_candidate(
        self, candidate_id: str, *, observed_step: int
    ) -> MechanicsChangeCandidate:
        candidate = self.candidate(candidate_id)
        updated = replace(
            candidate,
            provisional_status=MechanicsChangeStatus.CONTRADICTED,
            last_tested_step=observed_step,
        )
        self._candidates[candidate_id] = updated
        return updated

    def open_successor_epoch(
        self,
        candidate_id: str,
        *,
        start_transition_id: str,
    ) -> MechanicsEpoch:
        candidate = self.candidate(candidate_id)
        if candidate.provisional_status is not MechanicsChangeStatus.CONFIRMED:
            raise WorldModelError("successor epoch requires a confirmed change candidate")
        predecessor = self.epoch(candidate.predecessor_epoch_id)
        if predecessor.status is not MechanicsEpochStatus.ACTIVE:
            raise WorldModelError("predecessor mechanics epoch is not active")
        next_index = predecessor.epoch_index + 1
        if next_index >= self.MAX_EPOCHS_PER_LEVEL:
            raise WorldModelError("mechanics epoch bound exceeded for level")
        successor_id = f"mechanics-epoch:L{candidate.level_index}:{next_index:04d}"
        if successor_id in self._epochs:
            raise WorldModelError("duplicate successor mechanics epoch")
        self._epochs[predecessor.epoch_id] = replace(
            predecessor, status=MechanicsEpochStatus.CLOSED
        )
        successor = MechanicsEpoch(
            epoch_id=successor_id,
            level_index=candidate.level_index,
            epoch_index=next_index,
            parent_epoch_id=predecessor.epoch_id,
            start_transition_id=start_transition_id,
            caused_by_change_candidate_id=candidate_id,
            active_hypothesis_ids=(),
            active_model_ids=(),
            status=MechanicsEpochStatus.ACTIVE,
        )
        self._epochs[successor_id] = successor
        self._active_epoch_by_level[candidate.level_index] = successor_id
        return successor

    def register_hypotheses(
        self, hypothesis_ids: Iterable[str], *, epoch_id: str | None = None
    ) -> None:
        identifiers = _strings(hypothesis_ids, field="hypothesis_ids")
        if not identifiers:
            return
        target = self.epoch(epoch_id) if epoch_id is not None else None
        if target is None:
            raise WorldModelError("hypothesis epoch must be explicit")
        if target.status is not MechanicsEpochStatus.ACTIVE:
            raise WorldModelError("cannot register hypotheses in a closed mechanics epoch")
        for hypothesis_id in identifiers:
            known = self._hypothesis_epochs.get(hypothesis_id)
            if known is not None and known != target.epoch_id:
                raise WorldModelError("hypothesis identity cannot move between mechanics epochs")
            self._hypothesis_epochs[hypothesis_id] = target.epoch_id
        self._epochs[target.epoch_id] = replace(
            target,
            active_hypothesis_ids=_strings(
                (*target.active_hypothesis_ids, *identifiers), field="active_hypothesis_ids"
            ),
        )

    def register_models(self, model_ids: Iterable[str], *, epoch_id: str) -> None:
        identifiers = _strings(model_ids, field="model_ids")
        target = self.epoch(epoch_id)
        if target.status is not MechanicsEpochStatus.ACTIVE:
            raise WorldModelError("cannot register models in a closed mechanics epoch")
        for model_id in identifiers:
            known = self._model_epochs.get(model_id)
            if known is not None and known != target.epoch_id:
                raise WorldModelError("model identity cannot move between mechanics epochs")
            self._model_epochs[model_id] = target.epoch_id
        self._epochs[target.epoch_id] = replace(
            target,
            active_model_ids=_strings(
                (*target.active_model_ids, *identifiers), field="active_model_ids"
            ),
        )

    def register_transition(self, transition_id: str, *, epoch_id: str) -> None:
        """Bind one immutable transition to an epoch under the frozen memory bound."""

        identifier = _required_text(transition_id, field="transition_id")
        target = self.epoch(epoch_id)
        if target.status is not MechanicsEpochStatus.ACTIVE:
            raise WorldModelError("cannot register transitions in a closed mechanics epoch")
        known = self._transition_epochs.get(identifier)
        if known is not None:
            if known != target.epoch_id:
                raise WorldModelError("transition identity cannot move between mechanics epochs")
            return
        count = sum(item == target.epoch_id for item in self._transition_epochs.values())
        if count >= self.MAX_TRANSITIONS_PER_EPOCH:
            raise WorldModelError("mechanics transition bound exceeded for epoch")
        self._transition_epochs[identifier] = target.epoch_id

    def transition_epoch(self, transition_id: str) -> str | None:
        return self._transition_epochs.get(transition_id)

    def hypothesis_epoch(self, hypothesis_id: str) -> str | None:
        return self._hypothesis_epochs.get(hypothesis_id)

    def model_epoch(self, model_id: str) -> str | None:
        return self._model_epochs.get(model_id)

    def projection(self, *, level_index: int) -> dict[str, JSONValue]:
        active = self.active_epoch(level_index)
        level_epoch_ids = {
            item.epoch_id for item in self._epochs.values() if item.level_index == level_index
        }
        payload = normalize_json(
            {
                "schema": self.SCHEMA,
                "active_epoch_id": active.epoch_id,
                "epochs": [
                    item.to_dict()
                    for item in self._ordered_epochs()
                    if item.level_index == level_index
                ],
                "change_candidates": [
                    item.to_dict() for item in self.candidates() if item.level_index == level_index
                ],
                "hypothesis_epochs": {
                    key: value
                    for key, value in sorted(self._hypothesis_epochs.items())
                    if value in level_epoch_ids
                },
                "model_epochs": {
                    key: value
                    for key, value in sorted(self._model_epochs.items())
                    if value in level_epoch_ids
                },
                "transition_epochs": {
                    key: value
                    for key, value in sorted(self._transition_epochs.items())
                    if value in level_epoch_ids
                },
                "limits": {
                    "maximum_epochs_per_level": self.MAX_EPOCHS_PER_LEVEL,
                    "maximum_live_change_candidates": self.MAX_LIVE_CHANGE_CANDIDATES,
                    "maximum_transitions_per_epoch": self.MAX_TRANSITIONS_PER_EPOCH,
                },
            }
        )
        assert isinstance(payload, dict)
        return payload

    def to_dict(self) -> dict[str, JSONValue]:
        payload = normalize_json(
            {
                "schema": self.SCHEMA,
                "active_epoch_id": self._active_epoch_by_level[min(self._active_epoch_by_level)],
                "epochs": [item.to_dict() for item in self._ordered_epochs()],
                "change_candidates": [item.to_dict() for item in self.candidates()],
                "hypothesis_epochs": dict(sorted(self._hypothesis_epochs.items())),
                "model_epochs": dict(sorted(self._model_epochs.items())),
                "transition_epochs": dict(sorted(self._transition_epochs.items())),
                "limits": {
                    "maximum_epochs_per_level": self.MAX_EPOCHS_PER_LEVEL,
                    "maximum_live_change_candidates": self.MAX_LIVE_CHANGE_CANDIDATES,
                    "maximum_transitions_per_epoch": self.MAX_TRANSITIONS_PER_EPOCH,
                },
            }
        )
        assert isinstance(payload, dict)
        payload["active_epoch_by_level"] = {
            str(key): value for key, value in sorted(self._active_epoch_by_level.items())
        }
        return payload

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> MechanicsLifecycle:
        if value.get("schema") != cls.SCHEMA:
            raise WorldModelError("unsupported mechanics lifecycle schema")
        raw_epochs = value.get("epochs")
        raw_candidates = value.get("change_candidates")
        raw_active = value.get("active_epoch_by_level")
        raw_hypotheses = value.get("hypothesis_epochs")
        raw_models = value.get("model_epochs")
        raw_transitions = value.get("transition_epochs")
        raw_limits = value.get("limits")
        if (
            not isinstance(raw_epochs, list)
            or not all(isinstance(item, Mapping) for item in raw_epochs)
            or not isinstance(raw_candidates, list)
            or not all(isinstance(item, Mapping) for item in raw_candidates)
            or not isinstance(raw_active, Mapping)
            or not isinstance(raw_hypotheses, Mapping)
            or not isinstance(raw_models, Mapping)
            or not isinstance(raw_transitions, Mapping)
            or not isinstance(raw_limits, Mapping)
        ):
            raise WorldModelError("mechanics lifecycle projection is malformed")
        expected_limits = {
            "maximum_epochs_per_level": cls.MAX_EPOCHS_PER_LEVEL,
            "maximum_live_change_candidates": cls.MAX_LIVE_CHANGE_CANDIDATES,
            "maximum_transitions_per_epoch": cls.MAX_TRANSITIONS_PER_EPOCH,
        }
        if dict(raw_limits) != expected_limits:
            raise WorldModelError("mechanics lifecycle limits do not match the runtime contract")
        epochs = tuple(MechanicsEpoch.from_dict(item) for item in raw_epochs)
        if not epochs:
            raise WorldModelError("mechanics lifecycle requires at least one epoch")
        lifecycle = cls(level_index=epochs[0].level_index)
        lifecycle._epochs = {item.epoch_id: item for item in epochs}
        if len(lifecycle._epochs) != len(epochs):
            raise WorldModelError("duplicate mechanics epoch identity")
        lifecycle._candidates = {
            item.candidate_id: item
            for item in (MechanicsChangeCandidate.from_dict(raw) for raw in raw_candidates)
        }
        if len(lifecycle._candidates) != len(raw_candidates):
            raise WorldModelError("duplicate mechanics change-candidate identity")
        if (
            sum(
                item.provisional_status is MechanicsChangeStatus.CANDIDATE
                for item in lifecycle._candidates.values()
            )
            > cls.MAX_LIVE_CHANGE_CANDIDATES
        ):
            raise WorldModelError("live mechanics change-candidate bound exceeded")
        active: dict[int, str] = {}
        for raw_level, raw_epoch in raw_active.items():
            if not isinstance(raw_level, str) or not raw_level.isdigit():
                raise WorldModelError("mechanics active level key is malformed")
            if not isinstance(raw_epoch, str) or raw_epoch not in lifecycle._epochs:
                raise WorldModelError("mechanics active epoch identity is malformed")
            level = int(raw_level)
            if lifecycle._epochs[raw_epoch].level_index != level:
                raise WorldModelError("mechanics active epoch level mismatch")
            if lifecycle._epochs[raw_epoch].status is not MechanicsEpochStatus.ACTIVE:
                raise WorldModelError("mechanics active epoch is not active")
            if level in active:
                raise WorldModelError("duplicate mechanics active level identity")
            active[level] = raw_epoch
        lifecycle._active_epoch_by_level = active
        raw_primary_active = value.get("active_epoch_id")
        if (
            not active
            or not isinstance(raw_primary_active, str)
            or raw_primary_active != active[min(active)]
        ):
            raise WorldModelError("mechanics primary active epoch identity is inconsistent")
        lifecycle._hypothesis_epochs = cls._parse_identity_map(
            raw_hypotheses, lifecycle._epochs, field="hypothesis_epochs"
        )
        lifecycle._model_epochs = cls._parse_identity_map(
            raw_models, lifecycle._epochs, field="model_epochs"
        )
        lifecycle._transition_epochs = cls._parse_identity_map(
            raw_transitions, lifecycle._epochs, field="transition_epochs"
        )
        lifecycle._validate_memberships()
        return lifecycle

    @staticmethod
    def _parse_identity_map(
        value: Mapping[object, object],
        epochs: Mapping[str, MechanicsEpoch],
        *,
        field: str,
    ) -> dict[str, str]:
        result: dict[str, str] = {}
        for identifier, epoch_id in value.items():
            if (
                not isinstance(identifier, str)
                or not identifier.strip()
                or not isinstance(epoch_id, str)
                or epoch_id not in epochs
            ):
                raise WorldModelError(f"{field} contains an invalid identity mapping")
            result[identifier] = epoch_id
        return result

    def _validate_memberships(self) -> None:
        levels = {epoch.level_index for epoch in self._epochs.values()}
        if set(self._active_epoch_by_level) != levels:
            raise WorldModelError("mechanics active epoch map must cover every level exactly")
        for level_index in levels:
            level_epochs = tuple(
                sorted(
                    (item for item in self._epochs.values() if item.level_index == level_index),
                    key=lambda item: item.epoch_index,
                )
            )
            if len(level_epochs) > self.MAX_EPOCHS_PER_LEVEL:
                raise WorldModelError("mechanics epoch bound exceeded for level")
            if tuple(item.epoch_index for item in level_epochs) != tuple(range(len(level_epochs))):
                raise WorldModelError("mechanics epoch indices must be contiguous")
            active_epochs = tuple(
                item for item in level_epochs if item.status is MechanicsEpochStatus.ACTIVE
            )
            if len(active_epochs) != 1:
                raise WorldModelError("each mechanics level requires exactly one active epoch")
            if self._active_epoch_by_level[level_index] != active_epochs[0].epoch_id:
                raise WorldModelError("mechanics active epoch map disagrees with epoch status")
            if active_epochs[0].epoch_index != level_epochs[-1].epoch_index:
                raise WorldModelError("mechanics active epoch must be the latest epoch")
            for index, epoch in enumerate(level_epochs):
                if index == 0:
                    continue
                predecessor = level_epochs[index - 1]
                if epoch.parent_epoch_id != predecessor.epoch_id:
                    raise WorldModelError("mechanics epoch parent lineage is broken")
                if predecessor.status is not MechanicsEpochStatus.CLOSED:
                    raise WorldModelError("mechanics predecessor epoch must be closed")
                if self._transition_epochs.get(epoch.start_transition_id or "") != (
                    predecessor.epoch_id
                ):
                    raise WorldModelError("mechanics epoch start transition is outside its parent")
                candidate = self._candidates.get(epoch.caused_by_change_candidate_id or "")
                if (
                    candidate is None
                    or candidate.provisional_status is not MechanicsChangeStatus.CONFIRMED
                    or candidate.predecessor_epoch_id != predecessor.epoch_id
                    or candidate.level_index != level_index
                    or epoch.start_transition_id
                    not in candidate.supporting_successor_transition_ids
                ):
                    raise WorldModelError("mechanics epoch change-candidate link is broken")
        for epoch in self._epochs.values():
            mapped_hypotheses = {
                identifier
                for identifier, member_epoch in self._hypothesis_epochs.items()
                if member_epoch == epoch.epoch_id
            }
            if mapped_hypotheses != set(epoch.active_hypothesis_ids):
                raise WorldModelError("mechanics hypothesis membership projection disagrees")
            mapped_models = {
                identifier
                for identifier, member_epoch in self._model_epochs.items()
                if member_epoch == epoch.epoch_id
            }
            if mapped_models != set(epoch.active_model_ids):
                raise WorldModelError("mechanics model membership projection disagrees")
            transition_count = sum(
                member_epoch == epoch.epoch_id for member_epoch in self._transition_epochs.values()
            )
            if transition_count > self.MAX_TRANSITIONS_PER_EPOCH:
                raise WorldModelError("mechanics transition bound exceeded for epoch")
        for candidate in self._candidates.values():
            candidate_predecessor = self._epochs.get(candidate.predecessor_epoch_id)
            if (
                candidate_predecessor is None
                or candidate_predecessor.level_index != candidate.level_index
            ):
                raise WorldModelError("mechanics candidate predecessor epoch is inconsistent")
            if candidate.candidate_id != _candidate_identifier(
                level_index=candidate.level_index,
                predecessor_epoch_id=candidate.predecessor_epoch_id,
                change_domain=candidate.change_domain,
                opaque_handle=candidate.opaque_handle,
                affected_hypothesis_ids=candidate.affected_hypothesis_ids,
                predecessor_effect_signature=candidate.predecessor_effect_signature,
                successor_effect_signature=candidate.successor_effect_signature,
                observation_condition_signature=candidate.observation_condition_signature,
                opened_step=candidate.opened_step,
            ):
                raise WorldModelError("mechanics change-candidate identity is inconsistent")
            if any(
                self._hypothesis_epochs.get(identifier) != candidate.predecessor_epoch_id
                for identifier in candidate.affected_hypothesis_ids
            ):
                raise WorldModelError("mechanics candidate hypothesis dependency is inconsistent")
            if any(
                self._model_epochs.get(identifier) != candidate.predecessor_epoch_id
                for identifier in candidate.affected_model_ids
            ):
                raise WorldModelError("mechanics candidate model dependency is inconsistent")
            if any(
                self._transition_epochs.get(transition_id) != candidate.predecessor_epoch_id
                for transition_id in candidate.supporting_successor_transition_ids
            ):
                raise WorldModelError("mechanics candidate support crosses epoch boundaries")
            if candidate.provisional_status is MechanicsChangeStatus.CONFIRMED and (
                len(candidate.supporting_contradiction_event_ids) < 2
                or len(candidate.supporting_successor_transition_ids) < 2
                or (
                    candidate.change_domain
                    in {
                        MechanicsChangeDomain.ACTION_MAPPING,
                        MechanicsChangeDomain.DESTINATION_ROLE,
                    }
                    and len(set(candidate.supporting_discrimination_context_ids)) < 2
                )
            ):
                raise WorldModelError("confirmed mechanics candidate lacks distinct support")
            successor_gate_met = (
                len(candidate.supporting_contradiction_event_ids) >= 2
                and len(candidate.supporting_successor_transition_ids) >= 2
                and (
                    candidate.change_domain is MechanicsChangeDomain.OPAQUE_HANDLE
                    or len(set(candidate.supporting_discrimination_context_ids)) >= 2
                )
            )
            predecessor_gate_met = len(candidate.predecessor_recovery_event_ids) >= 2
            if candidate.provisional_status is MechanicsChangeStatus.CANDIDATE and (
                successor_gate_met or predecessor_gate_met
            ):
                raise WorldModelError("live mechanics candidate already satisfies a terminal gate")
            if (
                candidate.provisional_status is MechanicsChangeStatus.RESOLVED_NOISE
                and not predecessor_gate_met
            ):
                raise WorldModelError("noise-resolved mechanics candidate lacks recovery support")
            if candidate.provisional_status is MechanicsChangeStatus.CANDIDATE and (
                candidate_predecessor.status is not MechanicsEpochStatus.ACTIVE
            ):
                raise WorldModelError("live mechanics candidate cannot target a closed epoch")
            successor_links = tuple(
                epoch
                for epoch in self._epochs.values()
                if epoch.caused_by_change_candidate_id == candidate.candidate_id
            )
            if candidate.provisional_status is MechanicsChangeStatus.CONFIRMED:
                if len(successor_links) != 1:
                    raise WorldModelError("confirmed mechanics candidate needs one successor epoch")
            elif successor_links:
                raise WorldModelError("unconfirmed mechanics candidate cannot open an epoch")
        live_candidates = tuple(
            candidate
            for candidate in self._candidates.values()
            if candidate.provisional_status is MechanicsChangeStatus.CANDIDATE
        )
        for index, left in enumerate(live_candidates):
            for right in live_candidates[index + 1 :]:
                if (
                    left.level_index == right.level_index
                    and left.predecessor_epoch_id == right.predecessor_epoch_id
                    and _live_domains_overlap(
                        left_domain=left.change_domain,
                        left_handle=left.opaque_handle,
                        left_hypothesis_ids=left.affected_hypothesis_ids,
                        right_domain=right.change_domain,
                        right_handle=right.opaque_handle,
                        right_hypothesis_ids=right.affected_hypothesis_ids,
                    )
                ):
                    raise WorldModelError(
                        "multiple live mechanics candidates share one affected domain"
                    )

    def _ordered_epochs(self) -> tuple[MechanicsEpoch, ...]:
        return tuple(
            sorted(
                self._epochs.values(),
                key=lambda item: (item.level_index, item.epoch_index, item.epoch_id),
            )
        )


__all__ = [
    "MechanicsChangeCandidate",
    "MechanicsChangeDomain",
    "MechanicsChangeStatus",
    "MechanicsEpoch",
    "MechanicsEpochStatus",
    "MechanicsLifecycle",
]
