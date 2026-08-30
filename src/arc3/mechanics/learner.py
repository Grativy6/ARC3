"""Controller-facing facade for bounded prediction, learning, and probing."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Self, cast

from arc3.trace.canonical import canonical_bytes, normalize_json, parse_json_bytes, sha256_json
from arc3.types import ActionName, ActionRequest, Coordinate, JSONValue

from .effects import (
    DEFAULT_CHANNEL_RELEVANCE,
    CompositionResult,
    ConsequenceResidual,
    EffectContribution,
    ResidualKind,
    compare_consequence,
    compose_contributions,
)
from .ledger import MechanicLedger
from .models import (
    CHANNEL_ORDER,
    ConfirmationMode,
    ConsequenceChannel,
    ConsequenceVector,
    EvidenceProvenance,
    MechanicContext,
    MechanicEvidence,
    MechanicEvidenceKind,
    MechanicLedgerBudget,
    MechanicRef,
    MechanicsError,
    MechanicStatus,
    ScopeCeiling,
)
from .repair import LocalRepairPlanner, RepairCandidate, RepairTracker

LEARNER_SCHEMA = "arc3.mechanics.learner.v0.1"


@dataclass(frozen=True, slots=True)
class MechanicPredictionReceipt:
    """Complete prediction issued before exactly one environment action."""

    prediction_id: str
    sequence: int
    emitted_step: int
    action: ActionRequest
    context: MechanicContext
    composition: CompositionResult

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "prediction_id": self.prediction_id,
            "sequence": self.sequence,
            "emitted_step": self.emitted_step,
            "action": _action_to_dict(self.action),
            "context": self.context.to_dict(),
            "composition": self.composition.to_dict(),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> MechanicPredictionReceipt:
        action = value.get("action")
        context = value.get("context")
        composition = value.get("composition")
        if not isinstance(action, Mapping) or not isinstance(context, Mapping):
            raise MechanicsError("prediction action and context must be objects")
        if not isinstance(composition, Mapping):
            raise MechanicsError("prediction composition must be an object")
        return cls(
            prediction_id=_text(value.get("prediction_id"), field="prediction_id"),
            sequence=_non_negative(value.get("sequence"), field="prediction sequence"),
            emitted_step=_non_negative(value.get("emitted_step"), field="emitted_step"),
            action=_action_from_dict(action),
            context=MechanicContext.from_dict(context),
            composition=CompositionResult.from_dict(composition),
        )


@dataclass(frozen=True, slots=True)
class ResidualRecord:
    residual: ConsequenceResidual
    context: MechanicContext
    observed_step: int

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "residual": self.residual.to_dict(),
            "context": self.context.to_dict(),
            "observed_step": self.observed_step,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> ResidualRecord:
        residual = value.get("residual")
        context = value.get("context")
        if not isinstance(residual, Mapping) or not isinstance(context, Mapping):
            raise MechanicsError("open residual and context must be objects")
        return cls(
            residual=ConsequenceResidual.from_dict(residual),
            context=MechanicContext.from_dict(context),
            observed_step=_non_negative(value.get("observed_step"), field="observed_step"),
        )


@dataclass(frozen=True, slots=True)
class LearningReceipt:
    prediction_id: str
    residual: ConsequenceResidual
    passive_support_receipt_ids: tuple[str, ...]
    repair_candidates: tuple[RepairCandidate, ...]

    @property
    def fully_matched(self) -> bool:
        return not self.residual.mismatches

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "prediction_id": self.prediction_id,
            "residual": self.residual.to_dict(),
            "passive_support_receipt_ids": list(self.passive_support_receipt_ids),
            "repair_candidates": [item.to_dict() for item in self.repair_candidates],
        }


@dataclass(frozen=True, slots=True)
class LevelBoundaryReceipt:
    previous_level_scope: str
    current_level_scope: str
    retained_refs: tuple[MechanicRef, ...]
    quarantined_refs: tuple[MechanicRef, ...]

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "previous_level_scope": self.previous_level_scope,
            "current_level_scope": self.current_level_scope,
            "retained_refs": [item.to_dict() for item in self.retained_refs],
            "quarantined_refs": [item.to_dict() for item in self.quarantined_refs],
        }


@dataclass(frozen=True, slots=True)
class ProbeCandidate:
    """A caller-supplied legal action candidate; no coordinate enumeration occurs here."""

    action: ActionRequest
    context: MechanicContext
    target_channels: tuple[ConsequenceChannel, ...]
    expected_information_gain: int = 0
    expected_progress: int = 0
    reversibility: int = 0
    failure_cost: int = 0
    novelty: int = 0
    repetition_count: int = 0

    def __post_init__(self) -> None:
        channels = tuple(sorted(set(self.target_channels), key=CHANNEL_ORDER.index))
        if not channels:
            raise MechanicsError("probe candidates require at least one target channel")
        object.__setattr__(self, "target_channels", channels)
        for name in (
            "expected_information_gain",
            "expected_progress",
            "reversibility",
            "failure_cost",
            "novelty",
            "repetition_count",
        ):
            _non_negative(getattr(self, name), field=name)

    @property
    def signature(self) -> str:
        return sha256_json(self.to_dict())

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "action": _action_to_dict(self.action),
            "context": self.context.to_dict(),
            "target_channels": [item.value for item in self.target_channels],
            "expected_information_gain": self.expected_information_gain,
            "expected_progress": self.expected_progress,
            "reversibility": self.reversibility,
            "failure_cost": self.failure_cost,
            "novelty": self.novelty,
            "repetition_count": self.repetition_count,
        }


@dataclass(frozen=True, slots=True)
class ProbeChoice:
    selected: ProbeCandidate
    score: int
    considered_signatures: tuple[str, ...]
    targeted_residual_ids: tuple[str, ...]

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "selected": self.selected.to_dict(),
            "score": self.score,
            "considered_signatures": list(self.considered_signatures),
            "targeted_residual_ids": list(self.targeted_residual_ids),
        }


class MechanicalLearner:
    """A small deterministic API intended for later controller integration."""

    def __init__(
        self,
        *,
        game_scope: str,
        level_scope: str,
        budget: MechanicLedgerBudget | None = None,
        ledger: MechanicLedger | None = None,
    ) -> None:
        self.game_scope = _text(game_scope, field="learner game_scope")
        self.level_scope = _text(level_scope, field="learner level_scope")
        self.budget = budget or MechanicLedgerBudget()
        self.ledger = ledger or MechanicLedger(game_scope=self.game_scope, budget=self.budget)
        if self.ledger.game_scope != self.game_scope or self.ledger.budget != self.budget:
            raise MechanicsError("learner and mechanic ledger identity/budget disagree")
        self._pending: dict[str, MechanicPredictionReceipt] = {}
        self._open_residuals: dict[str, ResidualRecord] = {}
        self._repair_tracker = RepairTracker(max_residuals=self.budget.max_open_residuals)
        self._repair_planner = LocalRepairPlanner(budget=self.budget)
        self._prediction_sequence = 0
        self._dropped_residual_count = 0

    @property
    def pending(self) -> tuple[MechanicPredictionReceipt, ...]:
        return tuple(self._pending[key] for key in sorted(self._pending))

    @property
    def open_residuals(self) -> tuple[ResidualRecord, ...]:
        return tuple(
            sorted(
                self._open_residuals.values(),
                key=lambda item: (-item.residual.priority, item.residual.residual_id),
            )
        )

    @property
    def dropped_residual_count(self) -> int:
        return self._dropped_residual_count

    def start_level(self, level_scope: str) -> LevelBoundaryReceipt:
        """Advance level context while retaining, not promoting, prior knowledge."""

        if self._pending:
            raise MechanicsError("cannot cross a level boundary with a pending prediction")
        new_level = _text(level_scope, field="level_scope")
        previous = self.level_scope
        self.level_scope = new_level
        context = MechanicContext(self.game_scope, self.level_scope)
        retained = tuple(
            item.ref
            for item in self.ledger.active()
            if item.version.scope.ceiling in {ScopeCeiling.GENERIC, ScopeCeiling.GAME}
            or item.version.scope.matches(context)
        )
        quarantined = tuple(item.ref for item in self.ledger.quarantined_for(context))
        return LevelBoundaryReceipt(previous, new_level, retained, quarantined)

    def predict(
        self,
        action: ActionRequest,
        context: MechanicContext,
        *,
        emitted_step: int,
    ) -> MechanicPredictionReceipt:
        """Emit and retain the sole pending complete consequence prediction."""

        self._validate_context(context)
        _non_negative(emitted_step, field="emitted_step")
        if len(self._pending) >= self.budget.max_pending_predictions:
            raise MechanicsError("a consequence must match before another prediction is emitted")
        applicable = self.ledger.applicable(action.name, context)
        composition = compose_contributions(
            EffectContribution.from_version(item.version) for item in applicable
        )
        if (
            len(composition.consequence.delayed_effects.effects)
            > self.budget.max_pending_delayed_effects
        ):
            raise MechanicsError("predicted delayed effects exceed the competition bound")
        sequence = self._prediction_sequence
        content: dict[str, JSONValue] = {
            "sequence": sequence,
            "emitted_step": emitted_step,
            "action": _action_to_dict(action),
            "context": context.to_dict(),
            "composition_signature": composition.signature,
            "ledger_tail_hash": self.ledger.tail_hash,
        }
        digest = sha256_json(content).removeprefix("sha256:")
        receipt = MechanicPredictionReceipt(
            prediction_id=f"mechanic-prediction:{digest[:24]}",
            sequence=sequence,
            emitted_step=emitted_step,
            action=action,
            context=context,
            composition=composition,
        )
        self._pending[receipt.prediction_id] = receipt
        self._prediction_sequence += 1
        return receipt

    def cancel_unsubmitted_prediction(self, prediction_id: str) -> None:
        """Retract only the latest prediction before its action is submitted.

        The mechanical policy emits a prediction while selecting an action, but
        the outer competition governor can still reject that request.  Such a
        request earned no environment consequence and therefore must consume
        neither the learner's sole pending slot nor a prediction sequence ID.
        """

        try:
            prediction = self._pending[prediction_id]
        except KeyError as error:
            raise MechanicsError(
                "unsubmitted cancellation requires the current pending prediction"
            ) from error
        if len(self._pending) != 1 or prediction.sequence != self._prediction_sequence - 1:
            raise MechanicsError("only the latest sole pending prediction can be cancelled")
        del self._pending[prediction_id]
        self._prediction_sequence -= 1

    def observe_consequence(
        self,
        prediction_id: str,
        observed: ConsequenceVector,
        *,
        source_event_ids: Iterable[str],
        context_key: str,
        observed_step: int,
    ) -> LearningReceipt:
        """Match one returned consequence and passively support exact channels."""

        try:
            prediction = self._pending[prediction_id]
        except KeyError as error:
            raise MechanicsError("consequence requires the current pending prediction") from error
        sources = tuple(
            _text(item, field="consequence source event ID") for item in source_event_ids
        )
        if not sources:
            raise MechanicsError("consequence learning requires a source event ID")
        _text(context_key, field="consequence context_key")
        _non_negative(observed_step, field="observed_step")
        del self._pending[prediction_id]
        residual = compare_consequence(prediction.composition, observed)

        matched_channels = {
            item.channel
            for item in residual.channels
            if item.kind is ResidualKind.MATCH and not item.predicted.is_unknown
        }
        channels_by_ref: dict[MechanicRef, set[ConsequenceChannel]] = {}
        for channel in matched_channels:
            for ref in prediction.composition.contributors_for(channel):
                channels_by_ref.setdefault(ref, set()).add(channel)

        support_ids: list[str] = []
        for ref in sorted(channels_by_ref):
            channels = tuple(sorted(channels_by_ref[ref], key=CHANNEL_ORDER.index))
            content: dict[str, JSONValue] = {
                "prediction_id": prediction.prediction_id,
                "ref": ref.to_dict(),
                "channels": [item.value for item in channels],
                "context_key": context_key,
                "source_event_ids": list(sorted(sources)),
            }
            digest = sha256_json(content).removeprefix("sha256:")
            receipt_id = f"mechanic-passive-support:{digest[:24]}"
            self.ledger.confirm_passively(
                ref,
                channels=channels,
                source_event_ids=sources,
                context_key=context_key,
                observed_step=observed_step,
                receipt_id=receipt_id,
            )
            support_ids.append(receipt_id)

        repairs: tuple[RepairCandidate, ...] = ()
        if residual.consequential:
            record = ResidualRecord(residual, prediction.context, observed_step)
            self._remember_residual(record)
            repairs = self._repair_planner.propose(
                residual,
                prediction.context,
                failed_local_attempts=self._repair_tracker.failures(residual.residual_id),
            )
        else:
            self.resolve_residual(residual.residual_id)
        return LearningReceipt(
            prediction_id=prediction.prediction_id,
            residual=residual,
            passive_support_receipt_ids=tuple(support_ids),
            repair_candidates=repairs,
        )

    def record_local_repair_failure(self, residual_id: str) -> tuple[RepairCandidate, ...]:
        record = self._residual(residual_id)
        attempts = self._repair_tracker.record_local_failure(residual_id)
        return self._repair_planner.propose(
            record.residual,
            record.context,
            failed_local_attempts=attempts,
        )

    def reopen_implicated(
        self,
        residual_id: str,
        *,
        source_event_ids: Iterable[str],
        observed_step: int,
    ) -> tuple[MechanicRef, ...]:
        """Reopen only contributors after the local-repair threshold is met."""

        record = self._residual(residual_id)
        failures = self._repair_tracker.failures(residual_id)
        if failures < self._repair_planner.local_failure_threshold:
            raise MechanicsError("base reopening is unavailable before local repairs fail")
        sources = tuple(source_event_ids)
        implicated: dict[MechanicRef, set[ConsequenceChannel]] = {}
        for item in record.residual.consequential:
            for ref in item.contributor_refs:
                implicated.setdefault(ref, set()).add(item.channel)
        reopened: list[MechanicRef] = []
        for ref in sorted(implicated):
            channels = tuple(sorted(implicated[ref], key=CHANNEL_ORDER.index))
            digest = sha256_json(
                {
                    "residual_id": residual_id,
                    "ref": ref.to_dict(),
                    "channels": [item.value for item in channels],
                    "failures": failures,
                }
            ).removeprefix("sha256:")
            self.ledger.record_evidence(
                ref,
                MechanicEvidence(
                    receipt_id=f"mechanic-residual-evidence:{digest[:24]}",
                    kind=MechanicEvidenceKind.RESIDUAL,
                    confirmation_mode=ConfirmationMode.DELIBERATE,
                    provenance=EvidenceProvenance.OBSERVED_THIS_GAME,
                    source_event_ids=sources,
                    channels=channels,
                    context_key=record.context.context_key,
                    observed_step=observed_step,
                    summary="local repair candidates failed",
                ),
            )
            current = self.ledger.get(ref)
            if current.status is not MechanicStatus.REOPENED:
                self.ledger.reopen(
                    ref,
                    occurred_step=observed_step,
                    caused_by_event_ids=sources,
                    note="reopened after bounded local-first repair failure",
                )
            reopened.append(ref)
        return tuple(reopened)

    def confirm_transfer(
        self,
        ref: MechanicRef,
        *,
        channels: Iterable[ConsequenceChannel],
        source_event_ids: Iterable[str],
        context_key: str,
        observed_step: int,
        receipt_id: str,
    ) -> None:
        self.ledger.confirm_transfer(
            ref,
            channels=channels,
            source_event_ids=source_event_ids,
            context_key=context_key,
            observed_step=observed_step,
            receipt_id=receipt_id,
        )

    def resolve_residual(self, residual_id: str) -> None:
        self._open_residuals.pop(residual_id, None)
        self._repair_tracker.resolve(residual_id)

    def choose_probe(self, candidates: Iterable[ProbeCandidate]) -> ProbeChoice:
        """Choose among a bounded caller-provided set by consequential relevance."""

        eligible: list[ProbeCandidate] = []
        for item in candidates:
            if (
                item.context.game_scope == self.game_scope
                and item.context.level_scope == self.level_scope
                and item.repetition_count < self.budget.max_deliberate_repeats
            ):
                eligible.append(item)
                if len(eligible) == self.budget.max_probe_candidates:
                    break
        if not eligible:
            raise MechanicsError("no bounded, current-context probe candidate is eligible")
        ranked = sorted(eligible, key=self._probe_ranking_key)
        considered = tuple(ranked)
        selected = considered[0]
        targeted = tuple(
            sorted(
                {
                    record.residual.residual_id
                    for record in self.open_residuals
                    if set(selected.target_channels)
                    & {item.channel for item in record.residual.consequential}
                }
            )
        )
        return ProbeChoice(
            selected=selected,
            score=self._probe_score(selected),
            considered_signatures=tuple(item.signature for item in considered),
            targeted_residual_ids=targeted,
        )

    def _probe_ranking_key(self, candidate: ProbeCandidate) -> tuple[int, str, int, int]:
        coordinate = candidate.action.coordinate
        return (
            -self._probe_score(candidate),
            candidate.action.name.value,
            coordinate.x if coordinate else -1,
            coordinate.y if coordinate else -1,
        )

    def _probe_score(self, candidate: ProbeCandidate) -> int:
        unresolved = 0
        for record in self.open_residuals:
            for item in record.residual.consequential:
                if item.channel in candidate.target_channels:
                    unresolved += item.relevance
        inherent = sum(DEFAULT_CHANNEL_RELEVANCE[item] for item in candidate.target_channels)
        return (
            unresolved
            + inherent
            + 20 * candidate.expected_information_gain
            + 15 * candidate.expected_progress
            + 5 * candidate.reversibility
            + candidate.novelty
            - 20 * candidate.failure_cost
            - 10 * candidate.repetition_count
        )

    def _remember_residual(self, record: ResidualRecord) -> None:
        self._open_residuals[record.residual.residual_id] = record
        if len(self._open_residuals) <= self.budget.max_open_residuals:
            return
        ordered = sorted(
            self._open_residuals.values(),
            key=lambda item: (-item.residual.priority, item.residual.residual_id),
        )
        retained = ordered[: self.budget.max_open_residuals]
        removed = len(ordered) - len(retained)
        self._open_residuals = {item.residual.residual_id: item for item in retained}
        self._dropped_residual_count += removed

    def _residual(self, residual_id: str) -> ResidualRecord:
        try:
            return self._open_residuals[residual_id]
        except KeyError as error:
            raise MechanicsError(f"unknown open mechanic residual: {residual_id}") from error

    def _validate_context(self, context: MechanicContext) -> None:
        if context.game_scope != self.game_scope:
            raise MechanicsError("mechanic context belongs to a different opaque game")
        if context.level_scope != self.level_scope:
            raise MechanicsError("mechanic context is quarantined outside the current level")

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "schema": LEARNER_SCHEMA,
            "game_scope": self.game_scope,
            "level_scope": self.level_scope,
            "budget": self.budget.to_dict(),
            "ledger": self.ledger.compact_dict(),
            "pending": [item.to_dict() for item in self.pending],
            "open_residuals": [item.to_dict() for item in self.open_residuals],
            "repair_tracker": self._repair_tracker.to_dict(),
            "prediction_sequence": self._prediction_sequence,
            "dropped_residual_count": self._dropped_residual_count,
        }

    def compact_bytes(self) -> bytes:
        return canonical_bytes(self.to_dict())

    @classmethod
    def from_compact_bytes(cls, data: bytes, *, expected_game_scope: str) -> Self:
        parsed = parse_json_bytes(data)
        if not isinstance(parsed, dict):
            raise MechanicsError("compact mechanical learner must be a JSON object")
        return cls.from_dict(
            cast(Mapping[str, object], parsed), expected_game_scope=expected_game_scope
        )

    @classmethod
    def from_dict(cls, value: Mapping[str, object], *, expected_game_scope: str) -> Self:
        if value.get("schema") != LEARNER_SCHEMA:
            raise MechanicsError("unsupported mechanical learner schema")
        game_scope = _text(value.get("game_scope"), field="learner game_scope")
        if game_scope != _text(expected_game_scope, field="expected game_scope"):
            raise MechanicsError("mechanical learner belongs to a different opaque game")
        level_scope = _text(value.get("level_scope"), field="learner level_scope")
        budget_value = value.get("budget")
        ledger_value = value.get("ledger")
        if not isinstance(budget_value, Mapping) or not isinstance(ledger_value, Mapping):
            raise MechanicsError("learner budget and ledger must be objects")
        budget = MechanicLedgerBudget.from_dict(budget_value)
        ledger = MechanicLedger.from_dict(ledger_value, expected_game_scope=game_scope)
        learner = cls(
            game_scope=game_scope,
            level_scope=level_scope,
            budget=budget,
            ledger=ledger,
        )
        pending = value.get("pending")
        open_residuals = value.get("open_residuals")
        tracker = value.get("repair_tracker")
        if not isinstance(pending, list) or not all(isinstance(item, Mapping) for item in pending):
            raise MechanicsError("pending predictions must be an array of objects")
        if len(pending) > budget.max_pending_predictions:
            raise MechanicsError("restored learner exceeds the pending-prediction bound")
        for item in pending:
            receipt = MechanicPredictionReceipt.from_dict(item)
            learner._validate_context(receipt.context)
            learner._pending[receipt.prediction_id] = receipt
        if not isinstance(open_residuals, list) or not all(
            isinstance(item, Mapping) for item in open_residuals
        ):
            raise MechanicsError("open residuals must be an array of objects")
        if len(open_residuals) > budget.max_open_residuals:
            raise MechanicsError("restored learner exceeds the open-residual bound")
        for item in open_residuals:
            record = ResidualRecord.from_dict(item)
            learner._validate_context(record.context)
            learner._open_residuals[record.residual.residual_id] = record
        if not isinstance(tracker, Mapping):
            raise MechanicsError("repair tracker must be an object")
        learner._repair_tracker = RepairTracker.from_dict(tracker)
        if learner._repair_tracker.max_residuals != budget.max_open_residuals:
            raise MechanicsError("repair tracker bound disagrees with learner budget")
        learner._prediction_sequence = _non_negative(
            value.get("prediction_sequence"), field="prediction_sequence"
        )
        learner._dropped_residual_count = _non_negative(
            value.get("dropped_residual_count"), field="dropped_residual_count"
        )
        if (
            learner._pending
            and max(item.sequence for item in learner._pending.values())
            >= learner._prediction_sequence
        ):
            raise MechanicsError("prediction sequence does not follow restored pending receipts")
        # Reject semantically different but superficially parseable state.
        supplied = normalize_json(value)
        if supplied != normalize_json(learner.to_dict()):
            raise MechanicsError("serialized mechanical learner disagrees with rebuilt state")
        return learner


def _action_to_dict(action: ActionRequest) -> dict[str, JSONValue]:
    return {
        "name": action.name.value,
        "coordinate": (
            [action.coordinate.x, action.coordinate.y] if action.coordinate is not None else None
        ),
    }


def _action_from_dict(value: Mapping[str, object]) -> ActionRequest:
    name_value = value.get("name")
    if not isinstance(name_value, str):
        raise MechanicsError("action name must be a string")
    try:
        name = ActionName(name_value)
    except ValueError as error:
        raise MechanicsError(f"unsupported action name: {name_value!r}") from error
    coordinate_value = value.get("coordinate")
    coordinate: Coordinate | None = None
    if coordinate_value is not None:
        if (
            not isinstance(coordinate_value, list)
            or len(coordinate_value) != 2
            or any(isinstance(item, bool) or not isinstance(item, int) for item in coordinate_value)
        ):
            raise MechanicsError("action coordinate must be a two-integer array")
        coordinate = Coordinate(coordinate_value[0], coordinate_value[1])
    return ActionRequest(name, coordinate)


def _text(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise MechanicsError(f"{field} must be a non-empty string")
    return value


def _non_negative(value: object, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise MechanicsError(f"{field} must be a non-negative integer")
    return value


__all__ = [
    "LEARNER_SCHEMA",
    "LearningReceipt",
    "LevelBoundaryReceipt",
    "MechanicPredictionReceipt",
    "MechanicalLearner",
    "ProbeCandidate",
    "ProbeChoice",
    "ResidualRecord",
]
