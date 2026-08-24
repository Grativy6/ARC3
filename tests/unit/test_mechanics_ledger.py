from __future__ import annotations

from copy import deepcopy

import pytest

from arc3.mechanics import (
    DEFAULT_MECHANIC_LEDGER_MAX_EVENTS,
    ChannelValue,
    CompositionMode,
    ConfirmationMode,
    ConsequenceChannel,
    ConsequenceVector,
    DisplacementEffect,
    EvidenceProvenance,
    MechanicEvidence,
    MechanicEvidenceKind,
    MechanicLedger,
    MechanicLedgerBudget,
    MechanicRef,
    MechanicScope,
    MechanicsError,
    MechanicStatus,
    ScopeCeiling,
    SupportDimension,
)
from arc3.types import ActionName


def _movement_vector(dx: int = 1) -> ConsequenceVector:
    return ConsequenceVector.unknown().with_channel(
        ConsequenceChannel.CONTROLLED_DISPLACEMENT,
        ChannelValue.known(DisplacementEffect("controllable", dx, 0)),
    )


def _opened_ledger(
    *, budget: MechanicLedgerBudget | None = None
) -> tuple[MechanicLedger, MechanicRef]:
    ledger = MechanicLedger(game_scope="opaque-game", budget=budget)
    view = ledger.open(
        action=ActionName.ACTION1,
        scope=MechanicScope(ScopeCeiling.GAME, game_scope="opaque-game"),
        consequence=_movement_vector(),
        composition_mode=CompositionMode.BASE,
        created_step=0,
        created_from_event_ids=("E-OBS-0",),
        provenance=EvidenceProvenance.OBSERVED_THIS_GAME,
        mechanic_id="M-MOVE",
    )
    return ledger, view.ref


def _support(receipt_id: str, context: str, step: int) -> MechanicEvidence:
    return MechanicEvidence(
        receipt_id=receipt_id,
        kind=MechanicEvidenceKind.SUPPORT,
        confirmation_mode=(ConfirmationMode.PASSIVE if step == 3 else ConfirmationMode.DELIBERATE),
        provenance=EvidenceProvenance.OBSERVED_THIS_GAME,
        source_event_ids=(f"E-{step}",),
        channels=(ConsequenceChannel.CONTROLLED_DISPLACEMENT,),
        context_key=context,
        observed_step=step,
        support_dimensions=(SupportDimension.OCCURRENCE, SupportDimension.MAGNITUDE),
    )


def test_distinct_contexts_promote_but_duplicate_context_does_not() -> None:
    ledger, ref = _opened_ledger()
    ledger.record_evidence(ref, _support("R-1", "same", 1))
    duplicate_context = ledger.record_evidence(ref, _support("R-2", "same", 2))

    assert duplicate_context.status is MechanicStatus.PROVISIONAL
    supported = ledger.record_evidence(ref, _support("R-3", "different", 2))
    stable = ledger.record_evidence(ref, _support("R-4", "third", 3))

    assert supported.status is MechanicStatus.SUPPORTED
    assert stable.status is MechanicStatus.STABLE_WITHIN_SCOPE
    summary = stable.summary_for(ConsequenceChannel.CONTROLLED_DISPLACEMENT)
    assert summary.occurrence_support_count == 3
    assert summary.passive_contexts == ("third",)


def test_transfer_confirmation_is_separate_source_linked_support() -> None:
    ledger, ref = _opened_ledger()

    transferred = ledger.confirm_transfer(
        ref,
        channels=(ConsequenceChannel.CONTROLLED_DISPLACEMENT,),
        source_event_ids=("E-LEVEL-TRANSFER",),
        context_key="level-1-validation",
        observed_step=4,
        receipt_id="R-TRANSFER",
    )

    summary = transferred.summary_for(ConsequenceChannel.CONTROLLED_DISPLACEMENT)
    assert summary.transfer_contexts == ("level-1-validation",)
    assert summary.occurrence_support_count == 1


def test_contradictions_stress_recur_and_reopen_without_deleting_history() -> None:
    ledger, ref = _opened_ledger()
    for index, context in enumerate(("wall-a", "wall-b"), start=1):
        view = ledger.record_evidence(
            ref,
            MechanicEvidence(
                receipt_id=f"R-C-{index}",
                kind=MechanicEvidenceKind.CONTRADICTION,
                confirmation_mode=ConfirmationMode.DELIBERATE,
                provenance=EvidenceProvenance.OBSERVED_THIS_GAME,
                source_event_ids=(f"E-C-{index}",),
                channels=(ConsequenceChannel.CONTROLLED_DISPLACEMENT,),
                context_key=context,
                observed_step=index,
            ),
        )

    assert view.status is MechanicStatus.RECURRING_UNRESOLVED
    reopened = ledger.reopen(
        ref,
        occurred_step=3,
        caused_by_event_ids=("E-REPAIR",),
    )
    assert reopened.status is MechanicStatus.REOPENED
    assert reopened.evidence_receipt_ids == ("R-C-1", "R-C-2")


def test_semantic_revision_is_immutable_and_supersedes_only_the_old_version() -> None:
    ledger, old_ref = _opened_ledger()
    old_snapshot = ledger.get(old_ref).version.to_dict()

    revised = ledger.revise(
        old_ref,
        created_step=4,
        created_from_event_ids=("E-RESIDUAL",),
        consequence=_movement_vector(dx=2),
    )

    assert revised.ref.version == 2
    assert ledger.get(old_ref).version.to_dict() == old_snapshot
    assert ledger.get(old_ref).status is MechanicStatus.REJECTED_OR_SUPERSEDED
    assert ledger.get(old_ref).superseded_by == revised.ref


def test_compact_restore_is_deterministic_hash_checked_and_game_bounded() -> None:
    ledger, ref = _opened_ledger()
    ledger.record_evidence(ref, _support("R-1", "context-a", 1))
    encoded = ledger.compact_bytes()
    full = ledger.canonical_snapshot(compact=False).encode("utf-8")

    restored = MechanicLedger.from_compact_bytes(encoded, expected_game_scope="opaque-game")

    assert restored.compact_bytes() == encoded
    assert "records" not in ledger.compact_dict()
    assert len(encoded) < len(full)
    with pytest.raises(MechanicsError, match="different opaque game"):
        MechanicLedger.from_compact_bytes(encoded, expected_game_scope="other-game")

    tampered = deepcopy(ledger.compact_dict())
    events = tampered["events"]
    assert isinstance(events, list)
    event = events[0]
    assert isinstance(event, dict)
    event["note"] = "changed without rehashing"
    with pytest.raises(MechanicsError, match="hash does not match"):
        MechanicLedger.from_dict(tampered, expected_game_scope="opaque-game")


def test_default_event_bound_covers_declared_build003_campaign_with_finite_headroom() -> None:
    declared_submission_bound = 3064
    budget = MechanicLedgerBudget()

    assert DEFAULT_MECHANIC_LEDGER_MAX_EVENTS == 4096
    assert budget.max_events == DEFAULT_MECHANIC_LEDGER_MAX_EVENTS
    assert budget.max_events - declared_submission_bound == 1032
    assert budget.max_events < 8192


def test_bounds_fail_closed_without_eviction_or_overwrite() -> None:
    budget = MechanicLedgerBudget(max_active_mechanics=1, max_versions=2, max_events=8)
    ledger, _ref = _opened_ledger(budget=budget)

    with pytest.raises(MechanicsError, match="active mechanic bound"):
        ledger.open(
            action=ActionName.ACTION2,
            scope=MechanicScope(ScopeCeiling.GAME, game_scope="opaque-game"),
            consequence=_movement_vector(-1),
            composition_mode=CompositionMode.BASE,
            created_step=1,
            created_from_event_ids=("E-OBS-1",),
            provenance=EvidenceProvenance.OBSERVED_THIS_GAME,
        )
    assert len(ledger.records()) == 1


def test_version_bound_rejects_revision_before_superseding_current_record() -> None:
    ledger, ref = _opened_ledger(budget=MechanicLedgerBudget(max_versions=1, max_events=8))

    with pytest.raises(MechanicsError, match="semantic-version bound"):
        ledger.revise(
            ref,
            created_step=2,
            created_from_event_ids=("E-REVISION",),
            consequence=_movement_vector(2),
        )

    assert ledger.get(ref).status is MechanicStatus.PROVISIONAL
    assert len(ledger.events) == 1
