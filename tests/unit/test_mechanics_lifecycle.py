from __future__ import annotations

from copy import deepcopy
from typing import cast

import pytest

from arc3.errors import WorldModelError
from arc3.types import JSONValue
from arc3.world_model import (
    MechanicsChangeDomain,
    MechanicsChangeStatus,
    MechanicsEpochStatus,
    MechanicsLifecycle,
)


def _opened_lifecycle(*, maximum_transitions_per_epoch: int = 64) -> tuple[MechanicsLifecycle, str]:
    lifecycle = MechanicsLifecycle(
        level_index=0,
        maximum_transitions_per_epoch=maximum_transitions_per_epoch,
    )
    epoch_id = lifecycle.active_epoch(0).epoch_id
    lifecycle.register_hypotheses(("H-PREDECESSOR",), epoch_id=epoch_id)
    lifecycle.register_models(("WM-PREDECESSOR",), epoch_id=epoch_id)
    lifecycle.register_transition("T-CONTRADICTION-1", epoch_id=epoch_id)
    candidate = lifecycle.open_candidate(
        level_index=0,
        change_domain=MechanicsChangeDomain.OPAQUE_HANDLE,
        opaque_handle="opaque-handle-a",
        predecessor_effect_signature="sha256:predecessor",
        successor_effect_signature="sha256:successor",
        observation_condition_signature="condition:stable",
        affected_hypothesis_ids=("H-PREDECESSOR",),
        affected_model_ids=("WM-PREDECESSOR",),
        contradiction_event_id="E-CONTRADICTION-1",
        contradiction_transition_id="T-CONTRADICTION-1",
        discrimination_context_id="opaque-handle:opaque-handle-a",
        invalidated_plan_ids=("PLAN-PREDECESSOR",),
        opened_step=5,
    )
    return lifecycle, candidate.candidate_id


def _confirmed_lifecycle(*, maximum_transitions_per_epoch: int = 64) -> MechanicsLifecycle:
    lifecycle, candidate_id = _opened_lifecycle(
        maximum_transitions_per_epoch=maximum_transitions_per_epoch
    )
    predecessor_epoch_id = lifecycle.active_epoch(0).epoch_id
    lifecycle.register_transition("T-CONFIRMATION", epoch_id=predecessor_epoch_id)
    lifecycle.support_successor(
        candidate_id,
        contradiction_event_id="E-CONTRADICTION-2",
        contradiction_transition_id="T-CONFIRMATION",
        discrimination_context_id="opaque-handle:opaque-handle-a",
        successor_effect_signature="sha256:successor",
        observation_condition_signature="condition:stable",
        observed_step=6,
    )
    lifecycle.open_successor_epoch(candidate_id, start_transition_id="T-CONFIRMATION")
    return lifecycle


def test_one_outlier_stays_candidate_and_never_opens_an_epoch() -> None:
    lifecycle, candidate_id = _opened_lifecycle()

    once = lifecycle.support_predecessor(
        candidate_id,
        evidence_event_id="E-PREDECESSOR-RECOVERY-1",
        observed_step=6,
    )

    assert once.provisional_status is MechanicsChangeStatus.CANDIDATE
    assert lifecycle.active_epoch(0).epoch_index == 0
    assert len(cast(list[JSONValue], lifecycle.projection(level_index=0)["epochs"])) == 1


def test_two_predecessor_receipts_resolve_noise_without_reopening() -> None:
    lifecycle, candidate_id = _opened_lifecycle()
    lifecycle.support_predecessor(
        candidate_id,
        evidence_event_id="E-PREDECESSOR-RECOVERY-1",
        observed_step=6,
    )

    resolved = lifecycle.support_predecessor(
        candidate_id,
        evidence_event_id="E-PREDECESSOR-RECOVERY-2",
        observed_step=7,
    )

    assert resolved.provisional_status is MechanicsChangeStatus.RESOLVED_NOISE
    assert resolved.predecessor_recovery_event_ids == (
        "E-PREDECESSOR-RECOVERY-1",
        "E-PREDECESSOR-RECOVERY-2",
    )
    assert lifecycle.active_epoch(0).epoch_index == 0


def test_predecessor_recoveries_preserve_arrival_order_and_ignore_exact_duplicate() -> None:
    lifecycle, candidate_id = _opened_lifecycle()
    first = lifecycle.support_predecessor(
        candidate_id,
        evidence_event_id="E-RECOVERY-Z",
        observed_step=6,
    )
    duplicate = lifecycle.support_predecessor(
        candidate_id,
        evidence_event_id="E-RECOVERY-Z",
        observed_step=7,
    )
    resolved = lifecycle.support_predecessor(
        candidate_id,
        evidence_event_id="E-RECOVERY-A",
        observed_step=8,
    )

    assert duplicate is first
    assert duplicate.last_tested_step == 6
    assert resolved.predecessor_recovery_event_ids == ("E-RECOVERY-Z", "E-RECOVERY-A")
    serialized = lifecycle.to_dict()
    assert MechanicsLifecycle.from_dict(serialized).to_dict() == serialized


def test_confirmed_successor_opens_monotonic_epoch_and_roundtrips_exactly() -> None:
    lifecycle, candidate_id = _opened_lifecycle()
    predecessor_epoch_id = lifecycle.active_epoch(0).epoch_id
    lifecycle.register_transition("T-CONFIRMATION", epoch_id=predecessor_epoch_id)
    confirmed = lifecycle.support_successor(
        candidate_id,
        contradiction_event_id="E-CONTRADICTION-2",
        contradiction_transition_id="T-CONFIRMATION",
        discrimination_context_id="opaque-handle:opaque-handle-a",
        successor_effect_signature="sha256:successor",
        observation_condition_signature="condition:stable",
        observed_step=6,
    )
    successor = lifecycle.open_successor_epoch(
        candidate_id,
        start_transition_id="T-CONFIRMATION",
    )
    lifecycle.register_hypotheses(("H-SUCCESSOR",), epoch_id=successor.epoch_id)
    lifecycle.register_models(("WM-SUCCESSOR",), epoch_id=successor.epoch_id)

    assert confirmed.provisional_status is MechanicsChangeStatus.CONFIRMED
    assert successor.epoch_index == 1
    assert successor.parent_epoch_id == "mechanics-epoch:L0:0000"
    assert lifecycle.epoch(successor.parent_epoch_id).status is MechanicsEpochStatus.CLOSED
    assert lifecycle.hypothesis_epoch("H-PREDECESSOR") == successor.parent_epoch_id
    assert lifecycle.hypothesis_epoch("H-SUCCESSOR") == successor.epoch_id

    serialized = lifecycle.to_dict()
    restored = MechanicsLifecycle.from_dict(serialized)
    assert restored.to_dict() == serialized
    assert restored.active_epoch(0) == lifecycle.active_epoch(0)
    assert restored.candidate(candidate_id) == lifecycle.candidate(candidate_id)


def test_duplicate_successor_receipt_cannot_confirm_a_change() -> None:
    lifecycle, candidate_id = _opened_lifecycle()
    before = lifecycle.candidate(candidate_id)

    duplicate = lifecycle.support_successor(
        candidate_id,
        contradiction_event_id="E-CONTRADICTION-1",
        contradiction_transition_id="T-CONTRADICTION-1",
        discrimination_context_id="opaque-handle:opaque-handle-a",
        successor_effect_signature="sha256:successor",
        observation_condition_signature="condition:stable",
        observed_step=6,
    )

    assert duplicate is before
    assert duplicate.last_tested_step == 5
    assert duplicate.provisional_status is MechanicsChangeStatus.CANDIDATE
    assert duplicate.supporting_contradiction_event_ids == ("E-CONTRADICTION-1",)
    assert duplicate.supporting_successor_transition_ids == ("T-CONTRADICTION-1",)


@pytest.mark.parametrize(
    ("contradiction_event_id", "transition_id", "context_id"),
    (
        ("E-CONTRADICTION-1", "T-CONTRADICTION-2", "opaque-handle:opaque-handle-a"),
        ("E-CONTRADICTION-2", "T-CONTRADICTION-1", "opaque-handle:opaque-handle-a"),
        ("E-CONTRADICTION-1", "T-CONTRADICTION-1", "opaque-handle:opaque-handle-b"),
    ),
)
def test_partial_or_mismatched_successor_duplicate_fails_closed(
    contradiction_event_id: str,
    transition_id: str,
    context_id: str,
) -> None:
    lifecycle, candidate_id = _opened_lifecycle()
    epoch_id = lifecycle.active_epoch(0).epoch_id
    lifecycle.register_transition("T-CONTRADICTION-2", epoch_id=epoch_id)

    with pytest.raises(WorldModelError, match="partially duplicates or mismatches"):
        lifecycle.support_successor(
            candidate_id,
            contradiction_event_id=contradiction_event_id,
            contradiction_transition_id=transition_id,
            discrimination_context_id=context_id,
            successor_effect_signature="sha256:successor",
            observation_condition_signature="condition:stable",
            observed_step=6,
        )


def test_successor_support_triples_preserve_action4_action1_order_and_roundtrip() -> None:
    lifecycle = MechanicsLifecycle(level_index=0)
    epoch_id = lifecycle.active_epoch(0).epoch_id
    lifecycle.register_hypotheses(("H-ACTION-MAPPING",), epoch_id=epoch_id)
    lifecycle.register_models(("WM-ACTION-MAPPING",), epoch_id=epoch_id)
    lifecycle.register_transition("T-ACTION4", epoch_id=epoch_id)
    candidate = lifecycle.open_candidate(
        level_index=0,
        change_domain=MechanicsChangeDomain.ACTION_MAPPING,
        opaque_handle="ACTION4",
        predecessor_effect_signature="sha256:identity-map",
        successor_effect_signature="sha256:clockwise-map",
        observation_condition_signature="condition:stable",
        affected_hypothesis_ids=("H-ACTION-MAPPING",),
        affected_model_ids=("WM-ACTION-MAPPING",),
        contradiction_event_id="E-ACTION4",
        contradiction_transition_id="T-ACTION4",
        discrimination_context_id="opaque-handle:ACTION4",
        invalidated_plan_ids=(),
        opened_step=5,
    )
    lifecycle.register_transition("T-ACTION1", epoch_id=epoch_id)
    confirmed = lifecycle.support_successor(
        candidate.candidate_id,
        contradiction_event_id="E-ACTION1",
        contradiction_transition_id="T-ACTION1",
        discrimination_context_id="opaque-handle:ACTION1",
        successor_effect_signature="sha256:clockwise-map",
        observation_condition_signature="condition:stable",
        observed_step=6,
    )
    lifecycle.open_successor_epoch(candidate.candidate_id, start_transition_id="T-ACTION1")

    assert confirmed.supporting_contradiction_event_ids == ("E-ACTION4", "E-ACTION1")
    assert confirmed.supporting_successor_transition_ids == ("T-ACTION4", "T-ACTION1")
    assert confirmed.supporting_discrimination_context_ids == (
        "opaque-handle:ACTION4",
        "opaque-handle:ACTION1",
    )
    serialized = lifecycle.to_dict()
    assert MechanicsLifecycle.from_dict(serialized).to_dict() == serialized


@pytest.mark.parametrize(
    ("mutation", "message"),
    (
        ("unequal", "equal lengths"),
        ("duplicate-contradiction", "supporting_contradiction_event_ids.*unique"),
        ("duplicate-transition", "supporting_successor_transition_ids.*unique"),
        ("first-not-zero", "support index zero"),
        ("duplicate-recovery", "predecessor_recovery_event_ids.*unique"),
    ),
)
def test_deserialization_rejects_misaligned_successor_support_arrays(
    mutation: str,
    message: str,
) -> None:
    payload = deepcopy(_opened_lifecycle()[0].to_dict())
    candidates = payload["change_candidates"]
    assert isinstance(candidates, list)
    candidate = candidates[0]
    assert isinstance(candidate, dict)
    contradictions = candidate["supporting_contradiction_event_ids"]
    transitions = candidate["supporting_successor_transition_ids"]
    contexts = candidate["supporting_discrimination_context_ids"]
    assert isinstance(contradictions, list)
    assert isinstance(transitions, list)
    assert isinstance(contexts, list)
    if mutation == "unequal":
        contexts.append("opaque-handle:extra")
    elif mutation == "duplicate-contradiction":
        contradictions.append(contradictions[0])
        transitions.append("T-EXTRA")
        contexts.append("opaque-handle:extra")
    elif mutation == "duplicate-transition":
        contradictions.append("E-EXTRA")
        transitions.append(transitions[0])
        contexts.append("opaque-handle:extra")
    elif mutation == "duplicate-recovery":
        candidate["predecessor_recovery_event_ids"] = ["E-RECOVERY", "E-RECOVERY"]
    else:
        candidate["first_contradiction_event_id"] = "E-NOT-INDEX-ZERO"

    with pytest.raises(WorldModelError, match=message):
        MechanicsLifecycle.from_dict(payload)


def test_destination_role_requires_distinct_discrimination_contexts() -> None:
    lifecycle = MechanicsLifecycle(level_index=0)
    epoch_id = lifecycle.active_epoch(0).epoch_id
    lifecycle.register_hypotheses(("H-TERRAIN",), epoch_id=epoch_id)
    lifecycle.register_models(("WM-TERRAIN",), epoch_id=epoch_id)
    lifecycle.register_transition("T-ROLE-1", epoch_id=epoch_id)
    candidate = lifecycle.open_candidate(
        level_index=0,
        change_domain=MechanicsChangeDomain.DESTINATION_ROLE,
        opaque_handle="opaque-handle-a",
        predecessor_effect_signature="sha256:role-predecessor",
        successor_effect_signature="sha256:role-successor",
        observation_condition_signature="condition:role",
        affected_hypothesis_ids=("H-TERRAIN",),
        affected_model_ids=("WM-TERRAIN",),
        contradiction_event_id="E-ROLE-1",
        contradiction_transition_id="T-ROLE-1",
        discrimination_context_id="cell:primary:1",
        invalidated_plan_ids=(),
        opened_step=5,
    )
    lifecycle.register_transition("T-ROLE-2", epoch_id=epoch_id)

    same_cell = lifecycle.support_successor(
        candidate.candidate_id,
        contradiction_event_id="E-ROLE-2",
        contradiction_transition_id="T-ROLE-2",
        discrimination_context_id="cell:primary:1",
        successor_effect_signature="sha256:role-successor",
        observation_condition_signature="condition:role",
        observed_step=6,
    )

    assert same_cell.provisional_status is MechanicsChangeStatus.CANDIDATE
    lifecycle.register_transition("T-ROLE-3", epoch_id=epoch_id)
    distinct_cell = lifecycle.support_successor(
        candidate.candidate_id,
        contradiction_event_id="E-ROLE-3",
        contradiction_transition_id="T-ROLE-3",
        discrimination_context_id="cell:primary:2",
        successor_effect_signature="sha256:role-successor",
        observation_condition_signature="condition:role",
        observed_step=7,
    )
    assert distinct_cell.provisional_status is MechanicsChangeStatus.CONFIRMED


def test_destination_role_live_candidate_can_match_a_different_handle() -> None:
    lifecycle = MechanicsLifecycle(level_index=0)
    epoch_id = lifecycle.active_epoch(0).epoch_id
    lifecycle.register_hypotheses(("H-TERRAIN",), epoch_id=epoch_id)
    lifecycle.register_models(("WM-TERRAIN",), epoch_id=epoch_id)
    lifecycle.register_transition("T-ROLE-1", epoch_id=epoch_id)
    candidate = lifecycle.open_candidate(
        level_index=0,
        change_domain=MechanicsChangeDomain.DESTINATION_ROLE,
        opaque_handle="opaque-handle-a",
        predecessor_effect_signature="sha256:role-predecessor",
        successor_effect_signature="sha256:role-successor",
        observation_condition_signature="condition:role",
        affected_hypothesis_ids=("H-TERRAIN",),
        affected_model_ids=("WM-TERRAIN",),
        contradiction_event_id="E-ROLE-1",
        contradiction_transition_id="T-ROLE-1",
        discrimination_context_id="cell:primary:1",
        invalidated_plan_ids=(),
        opened_step=5,
    )

    matched = lifecycle.live_candidate(
        level_index=0,
        opaque_handle="opaque-handle-b",
        affected_hypothesis_ids=("H-TERRAIN",),
    )
    assert matched == candidate


def test_global_action_mapping_requires_two_distinct_handle_contexts() -> None:
    lifecycle = MechanicsLifecycle(level_index=0)
    epoch_id = lifecycle.active_epoch(0).epoch_id
    lifecycle.register_hypotheses(("H-A", "H-B"), epoch_id=epoch_id)
    lifecycle.register_models(("WM-MAPPING",), epoch_id=epoch_id)
    lifecycle.register_transition("T-MAP-1", epoch_id=epoch_id)
    candidate = lifecycle.open_candidate(
        level_index=0,
        change_domain=MechanicsChangeDomain.ACTION_MAPPING,
        opaque_handle="opaque-handle-a",
        predecessor_effect_signature="sha256:identity-map",
        successor_effect_signature="sha256:clockwise-map",
        observation_condition_signature="condition:stable",
        affected_hypothesis_ids=("H-A", "H-B"),
        affected_model_ids=("WM-MAPPING",),
        contradiction_event_id="E-MAP-1",
        contradiction_transition_id="T-MAP-1",
        discrimination_context_id="opaque-handle:opaque-handle-a",
        invalidated_plan_ids=(),
        opened_step=5,
    )
    lifecycle.register_transition("T-MAP-2", epoch_id=epoch_id)
    repeated_handle = lifecycle.support_successor(
        candidate.candidate_id,
        contradiction_event_id="E-MAP-2",
        contradiction_transition_id="T-MAP-2",
        discrimination_context_id="opaque-handle:opaque-handle-a",
        successor_effect_signature="sha256:clockwise-map",
        observation_condition_signature="condition:stable",
        observed_step=6,
    )
    assert repeated_handle.provisional_status is MechanicsChangeStatus.CANDIDATE
    assert repeated_handle.supporting_discrimination_context_ids == (
        "opaque-handle:opaque-handle-a",
        "opaque-handle:opaque-handle-a",
    )

    lifecycle.register_transition("T-MAP-3", epoch_id=epoch_id)
    distinct_handle = lifecycle.support_successor(
        candidate.candidate_id,
        contradiction_event_id="E-MAP-3",
        contradiction_transition_id="T-MAP-3",
        discrimination_context_id="opaque-handle:opaque-handle-b",
        successor_effect_signature="sha256:clockwise-map",
        observation_condition_signature="condition:stable",
        observed_step=7,
    )
    assert distinct_handle.provisional_status is MechanicsChangeStatus.CONFIRMED
    assert distinct_handle.supporting_discrimination_context_ids == (
        "opaque-handle:opaque-handle-a",
        "opaque-handle:opaque-handle-a",
        "opaque-handle:opaque-handle-b",
    )
    assert (
        lifecycle.live_candidate(
            level_index=0,
            opaque_handle="opaque-handle-c",
        )
        is None
    )


@pytest.mark.parametrize(
    "change_domain",
    (
        MechanicsChangeDomain.OPAQUE_HANDLE,
        MechanicsChangeDomain.ACTION_MAPPING,
        MechanicsChangeDomain.DESTINATION_ROLE,
    ),
)
def test_registration_rejects_a_second_live_candidate_for_one_affected_domain(
    change_domain: MechanicsChangeDomain,
) -> None:
    lifecycle = MechanicsLifecycle(level_index=0)
    epoch_id = lifecycle.active_epoch(0).epoch_id
    lifecycle.register_hypotheses(("H-DOMAIN",), epoch_id=epoch_id)
    lifecycle.register_models(("WM-DOMAIN",), epoch_id=epoch_id)
    lifecycle.register_transition("T-DOMAIN-1", epoch_id=epoch_id)
    lifecycle.open_candidate(
        level_index=0,
        change_domain=change_domain,
        opaque_handle="opaque-handle-a",
        predecessor_effect_signature="sha256:predecessor-1",
        successor_effect_signature="sha256:successor-1",
        observation_condition_signature="condition:stable",
        affected_hypothesis_ids=("H-DOMAIN",),
        affected_model_ids=("WM-DOMAIN",),
        contradiction_event_id="E-DOMAIN-1",
        contradiction_transition_id="T-DOMAIN-1",
        discrimination_context_id="context:domain-1",
        invalidated_plan_ids=(),
        opened_step=1,
    )
    lifecycle.register_transition("T-DOMAIN-2", epoch_id=epoch_id)

    with pytest.raises(WorldModelError, match="already covers this domain"):
        lifecycle.open_candidate(
            level_index=0,
            change_domain=change_domain,
            opaque_handle=(
                "opaque-handle-a"
                if change_domain is MechanicsChangeDomain.OPAQUE_HANDLE
                else "opaque-handle-b"
            ),
            predecessor_effect_signature="sha256:predecessor-2",
            successor_effect_signature="sha256:successor-2",
            observation_condition_signature="condition:stable",
            affected_hypothesis_ids=("H-DOMAIN",),
            affected_model_ids=("WM-DOMAIN",),
            contradiction_event_id="E-DOMAIN-2",
            contradiction_transition_id="T-DOMAIN-2",
            discrimination_context_id="context:domain-2",
            invalidated_plan_ids=(),
            opened_step=2,
        )


@pytest.mark.parametrize(
    "change_domain",
    (
        MechanicsChangeDomain.OPAQUE_HANDLE,
        MechanicsChangeDomain.ACTION_MAPPING,
        MechanicsChangeDomain.DESTINATION_ROLE,
    ),
)
def test_deserialization_rejects_duplicate_live_affected_domains(
    change_domain: MechanicsChangeDomain,
) -> None:
    def candidate_payload(
        *,
        handle: str,
        predecessor: str,
        successor: str,
        opened_step: int,
    ) -> dict[str, JSONValue]:
        lifecycle = MechanicsLifecycle(level_index=0)
        epoch_id = lifecycle.active_epoch(0).epoch_id
        lifecycle.register_hypotheses(("H-DOMAIN",), epoch_id=epoch_id)
        lifecycle.register_models(("WM-DOMAIN",), epoch_id=epoch_id)
        lifecycle.register_transition("T-DOMAIN", epoch_id=epoch_id)
        candidate = lifecycle.open_candidate(
            level_index=0,
            change_domain=change_domain,
            opaque_handle=handle,
            predecessor_effect_signature=predecessor,
            successor_effect_signature=successor,
            observation_condition_signature="condition:stable",
            affected_hypothesis_ids=("H-DOMAIN",),
            affected_model_ids=("WM-DOMAIN",),
            contradiction_event_id=f"E-DOMAIN-{opened_step}",
            contradiction_transition_id="T-DOMAIN",
            discrimination_context_id=f"context:domain-{opened_step}",
            invalidated_plan_ids=(),
            opened_step=opened_step,
        )
        return candidate.to_dict()

    lifecycle = MechanicsLifecycle(level_index=0)
    epoch_id = lifecycle.active_epoch(0).epoch_id
    lifecycle.register_hypotheses(("H-DOMAIN",), epoch_id=epoch_id)
    lifecycle.register_models(("WM-DOMAIN",), epoch_id=epoch_id)
    lifecycle.register_transition("T-DOMAIN", epoch_id=epoch_id)
    payload = lifecycle.to_dict()
    candidates = payload["change_candidates"]
    assert isinstance(candidates, list)
    candidates.extend(
        (
            candidate_payload(
                handle="opaque-handle-a",
                predecessor="sha256:predecessor-1",
                successor="sha256:successor-1",
                opened_step=1,
            ),
            candidate_payload(
                handle=(
                    "opaque-handle-a"
                    if change_domain is MechanicsChangeDomain.OPAQUE_HANDLE
                    else "opaque-handle-b"
                ),
                predecessor="sha256:predecessor-2",
                successor="sha256:successor-2",
                opened_step=2,
            ),
        )
    )

    with pytest.raises(WorldModelError, match="share one affected domain"):
        MechanicsLifecycle.from_dict(payload)


def test_transition_bound_is_enforced_per_epoch() -> None:
    lifecycle = MechanicsLifecycle(level_index=0, maximum_transitions_per_epoch=80)
    epoch_id = lifecycle.active_epoch(0).epoch_id
    for index in range(lifecycle.maximum_transitions_per_epoch):
        lifecycle.register_transition(f"T-{index:03d}", epoch_id=epoch_id)

    assert lifecycle.maximum_transitions_per_epoch == 80
    serialized = lifecycle.to_dict()
    restored = MechanicsLifecycle.from_dict(
        serialized,
        expected_maximum_transitions_per_epoch=80,
    )
    assert restored.to_dict() == serialized
    with pytest.raises(WorldModelError, match="transition bound"):
        lifecycle.register_transition("T-OVERFLOW", epoch_id=epoch_id)


def test_serialized_transition_capacity_must_match_the_expected_run_contract() -> None:
    lifecycle = MechanicsLifecycle(level_index=0, maximum_transitions_per_epoch=80)
    epoch_id = lifecycle.active_epoch(0).epoch_id
    for index in range(65):
        lifecycle.register_transition(f"T-{index:03d}", epoch_id=epoch_id)

    with pytest.raises(WorldModelError, match="limits do not match"):
        MechanicsLifecycle.from_dict(
            lifecycle.to_dict(),
            expected_maximum_transitions_per_epoch=79,
        )


def test_evidence_driven_successor_epoch_retains_the_run_capacity() -> None:
    lifecycle = _confirmed_lifecycle(maximum_transitions_per_epoch=80)
    successor = lifecycle.active_epoch(0)

    assert successor.epoch_index == 1
    assert lifecycle.maximum_transitions_per_epoch == 80
    assert lifecycle.projection(level_index=0)["limits"] == {
        "maximum_epochs_per_level": 4,
        "maximum_live_change_candidates": 8,
        "maximum_transitions_per_epoch": 80,
    }
    for index in range(80):
        lifecycle.register_transition(f"T-SUCCESSOR-{index:03d}", epoch_id=successor.epoch_id)
    with pytest.raises(WorldModelError, match="transition bound"):
        lifecycle.register_transition("T-SUCCESSOR-OVERFLOW", epoch_id=successor.epoch_id)


def test_closed_epoch_rejects_new_authority_registration() -> None:
    lifecycle = _confirmed_lifecycle()
    closed_epoch = "mechanics-epoch:L0:0000"

    with pytest.raises(WorldModelError, match="closed mechanics epoch"):
        lifecycle.register_hypotheses(("H-LATE",), epoch_id=closed_epoch)
    with pytest.raises(WorldModelError, match="closed mechanics epoch"):
        lifecycle.register_models(("WM-LATE",), epoch_id=closed_epoch)
    with pytest.raises(WorldModelError, match="closed mechanics epoch"):
        lifecycle.register_transition("T-LATE", epoch_id=closed_epoch)


@pytest.mark.parametrize(
    ("mutation", "message"),
    (
        ("zero-active", "active epoch"),
        ("multiple-active", "exactly one active"),
        ("broken-parent", "parent lineage"),
        ("reverse-map", "membership projection"),
        ("bad-start", "start transition"),
        ("bad-candidate-link", "change-candidate link"),
    ),
)
def test_deserialization_rejects_inconsistent_epoch_authority(
    mutation: str,
    message: str,
) -> None:
    payload = deepcopy(_confirmed_lifecycle().to_dict())
    epochs = payload["epochs"]
    assert isinstance(epochs, list)
    predecessor = epochs[0]
    successor = epochs[1]
    assert isinstance(predecessor, dict) and isinstance(successor, dict)
    if mutation == "zero-active":
        successor["status"] = "CLOSED"
    elif mutation == "multiple-active":
        predecessor["status"] = "ACTIVE"
    elif mutation == "broken-parent":
        successor["parent_epoch_id"] = "mechanics-epoch:L0:9999"
    elif mutation == "reverse-map":
        hypotheses = payload["hypothesis_epochs"]
        assert isinstance(hypotheses, dict)
        hypotheses.clear()
    elif mutation == "bad-start":
        successor["start_transition_id"] = "T-UNKNOWN"
    elif mutation == "bad-candidate-link":
        successor["caused_by_change_candidate_id"] = "mechanics-change:unknown"

    with pytest.raises(WorldModelError, match=message):
        MechanicsLifecycle.from_dict(payload)


def test_deserialization_rejects_epoch_and_live_candidate_bounds() -> None:
    epoch_payload = deepcopy(_confirmed_lifecycle().to_dict())
    epochs = epoch_payload["epochs"]
    assert isinstance(epochs, list)
    template = epochs[-1]
    assert isinstance(template, dict)
    for index in range(2, 5):
        extra = deepcopy(template)
        extra["epoch_id"] = f"mechanics-epoch:L0:{index:04d}"
        extra["epoch_index"] = index
        epochs.append(extra)
    with pytest.raises(WorldModelError, match="epoch bound"):
        MechanicsLifecycle.from_dict(epoch_payload)

    candidate_payload = deepcopy(_opened_lifecycle()[0].to_dict())
    candidates = candidate_payload["change_candidates"]
    assert isinstance(candidates, list) and len(candidates) == 1
    template_candidate = candidates[0]
    assert isinstance(template_candidate, dict)
    for index in range(1, 9):
        extra_candidate = deepcopy(template_candidate)
        extra_candidate["candidate_id"] = f"mechanics-change:{index:024d}"
        extra_candidate["opaque_handle"] = f"opaque-handle-{index}"
        candidates.append(extra_candidate)
    with pytest.raises(WorldModelError, match="change-candidate bound"):
        MechanicsLifecycle.from_dict(candidate_payload)
