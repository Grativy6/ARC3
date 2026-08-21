from __future__ import annotations

import pytest

from arc3.errors import HypothesisError
from arc3.hypotheses import (
    ActionSemanticsStatement,
    CandidateGoalStatement,
    Compatibility,
    EvidenceKind,
    EvidenceReceipt,
    HypothesisEvent,
    HypothesisRegistry,
    HypothesisScope,
    render_hypothesis_report,
    structured_hypothesis_report,
)
from arc3.types import HypothesisStatus


def receipt(
    identifier: str,
    kind: EvidenceKind,
    source: str,
    step: int,
    *,
    impact: int = 1,
) -> EvidenceReceipt:
    return EvidenceReceipt(identifier, kind, (source,), f"evidence {identifier}", step, impact)


def test_status_updates_never_erase_support_contradiction_or_residual_receipts() -> None:
    registry = HypothesisRegistry()
    created = registry.create(
        hypothesis_id="H-MOVE",
        event_id="HE-CREATE",
        statement=ActionSemanticsStatement("ACTION1", "translate", {"dx": 0, "dy": -1}),
        scope=HypothesisScope.GAME,
        scope_ref="game-a",
        created_from_event_ids=("E-OBS-0",),
        occurred_step=0,
        initial_rank_weight=2,
    )
    assert created.status is HypothesisStatus.CANDIDATE

    supported = registry.support(
        "H-MOVE", receipt("R-S", EvidenceKind.SUPPORT, "E-C-1", 1, impact=3)
    )
    contradicted = registry.contradict(
        "H-MOVE", receipt("R-C", EvidenceKind.CONTRADICTION, "E-C-2", 2, impact=4)
    )

    assert supported.status is HypothesisStatus.ACTIVE
    assert contradicted.status is HypothesisStatus.UNRESOLVED
    assert contradicted.rank_weight == 1
    assert contradicted.support_event_ids == ("E-C-1",)
    assert contradicted.contradiction_event_ids == ("E-C-2",)
    assert tuple(event.event_type.value for event in registry.events) == (
        "hypothesis.created",
        "hypothesis.supported",
        "hypothesis.contradicted",
    )


def test_rejected_records_remain_queryable_and_scope_history_is_retained() -> None:
    registry = HypothesisRegistry()
    registry.create(
        hypothesis_id="H-RETAINED",
        statement=ActionSemanticsStatement("ACTION4", "wait", {}),
        scope=HypothesisScope.STEP,
        scope_ref="game-a/level-0/step-0",
        created_from_event_ids=("E-0",),
        occurred_step=0,
    )
    registry.change_scope(
        "H-RETAINED",
        HypothesisScope.LEVEL,
        new_scope_ref="game-a/level-0",
        occurred_step=1,
        caused_by_event_ids=("E-1",),
    )
    registry.reject("H-RETAINED", receipt("R-REJECT", EvidenceKind.RESIDUAL, "E-2", 2))

    assert registry.rejected()[0].hypothesis_id == "H-RETAINED"
    assert registry.find("H-RETAINED") is not None
    assert [revision.new_scope for revision in registry.get("H-RETAINED").scope_history] == [
        HypothesisScope.STEP,
        HypothesisScope.LEVEL,
    ]
    assert len(registry.history("H-RETAINED")) == 3


def test_conflict_resolution_and_ensemble_selection_are_deterministic() -> None:
    registry = HypothesisRegistry()
    low = registry.create(
        hypothesis_id="H-LOW",
        statement=ActionSemanticsStatement("ACTION1", "translate", {"dy": -1}),
        scope=HypothesisScope.GAME,
        scope_ref="game-a",
        created_from_event_ids=("E-0",),
        occurred_step=0,
        initial_rank_weight=1,
    )
    high = registry.create(
        hypothesis_id="H-HIGH",
        statement=ActionSemanticsStatement("ACTION1", "translate", {"dy": 1}),
        scope=HypothesisScope.GAME,
        scope_ref="game-a",
        created_from_event_ids=("E-0",),
        occurred_step=0,
        initial_rank_weight=4,
    )
    goal = registry.create(
        hypothesis_id="H-GOAL",
        statement=CandidateGoalStatement("reach_exit", "at_exit", ("score_increase",)),
        scope=HypothesisScope.GAME,
        scope_ref="game-a",
        created_from_event_ids=("E-0",),
        occurred_step=0,
        initial_rank_weight=2,
    )

    assert (
        registry.compatibility(low.hypothesis_id, high.hypothesis_id) is Compatibility.INCOMPATIBLE
    )
    assert (
        registry.compatibility(high.hypothesis_id, low.hypothesis_id) is Compatibility.INCOMPATIBLE
    )
    assert registry.resolve_conflict((low.hypothesis_id, high.hypothesis_id)) == high
    assert tuple(record.hypothesis_id for record in registry.compatible_ensemble()) == (
        "H-HIGH",
        goal.hypothesis_id,
    )


def test_superseding_lineage_retains_both_records() -> None:
    registry = HypothesisRegistry()
    registry.create(
        hypothesis_id="H-OLD",
        statement=ActionSemanticsStatement("ACTION5", "toggle", {"state": "unknown"}),
        scope=HypothesisScope.GAME,
        created_from_event_ids=("E-0",),
        occurred_step=0,
    )
    successor = registry.create(
        hypothesis_id="H-NEW",
        statement=ActionSemanticsStatement("ACTION5", "toggle", {"state": "selected"}),
        scope=HypothesisScope.GAME,
        created_from_event_ids=("E-1",),
        occurred_step=1,
        parent_ids=("H-OLD",),
    )
    old = registry.supersede(
        "H-OLD",
        successor.hypothesis_id,
        occurred_step=1,
        caused_by_event_ids=("E-1",),
    )

    assert old.status is HypothesisStatus.SUPERSEDED
    assert old.superseded_by == "H-NEW"
    assert tuple(record.hypothesis_id for record in registry.lineage("H-OLD")) == (
        "H-OLD",
        "H-NEW",
    )


def test_event_rebuild_and_human_report_are_derived_deterministically() -> None:
    registry = HypothesisRegistry()
    registry.create(
        hypothesis_id="H-REPORT",
        statement=ActionSemanticsStatement("ACTION2", "translate", {"dx": 1}),
        scope=HypothesisScope.LEVEL,
        scope_ref="level-1",
        created_from_event_ids=("E-0",),
        occurred_step=0,
    )
    registry.support("H-REPORT", receipt("R-REPORT", EvidenceKind.SUPPORT, "E-1", 1, impact=2))

    rebuilt = HypothesisRegistry(
        HypothesisEvent.from_dict(event.to_dict()) for event in registry.events
    )
    restored = HypothesisRegistry.from_dict(registry.to_dict())
    report = structured_hypothesis_report(rebuilt)
    markdown = render_hypothesis_report(rebuilt)

    assert rebuilt.canonical_snapshot() == registry.canonical_snapshot()
    assert restored.canonical_snapshot() == registry.canonical_snapshot()
    assert report["weight_semantics"] == "uncalibrated deterministic rank; not probability or proof"
    assert "Rank weight: 2 (uncalibrated)" in markdown
    assert "chain_of_thought" not in markdown


def test_invalid_evidence_transition_is_rejected_without_appending() -> None:
    registry = HypothesisRegistry()
    registry.create(
        hypothesis_id="H-X",
        statement=ActionSemanticsStatement("ACTION3", "noop", {}),
        scope=HypothesisScope.GAME,
        created_from_event_ids=("E-0",),
        occurred_step=0,
    )

    with pytest.raises(HypothesisError, match="requires evidence kind"):
        registry.reject("H-X", receipt("R-BAD", EvidenceKind.SUPPORT, "E-1", 1))
    assert len(registry.events) == 1
