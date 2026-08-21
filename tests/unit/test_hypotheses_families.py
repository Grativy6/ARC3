from __future__ import annotations

from collections.abc import Mapping

import pytest

from arc3.errors import HypothesisError
from arc3.hypotheses import (
    ActionSemanticsStatement,
    CandidateGoalStatement,
    CollisionTraversabilityStatement,
    ControllableObjectStatement,
    CoordinateActionTargetStatement,
    EvidenceKind,
    EvidenceReceipt,
    HypothesisFamily,
    HypothesisPrediction,
    InteractionToggleStatement,
    LevelInvariantStatement,
    ProgressTerminalStatement,
    StateTransitionStatement,
    statement_from_dict,
)
from arc3.hypotheses.families import HypothesisStatement


@pytest.mark.parametrize(
    "statement",
    [
        ActionSemanticsStatement("ACTION1", "translate", {"dx": 0, "dy": -1}),
        ControllableObjectStatement("O-1", ("persists", "moves"), ("ACTION1",)),
        CollisionTraversabilityStatement("avatar", "wall", False, "blocked"),
        InteractionToggleStatement("contact", "switch", "on"),
        CoordinateActionTargetStatement("ACTION6", "component", "select", radius=1),
        StateTransitionStatement("ACTION2", ("selected",), ("attached",)),
        ProgressTerminalStatement("all_slots_filled", "level_complete", True),
        CandidateGoalStatement("fill_slots", "all_slots_filled", ("score_increase",)),
        LevelInvariantStatement("colors map to roles", ("avatar", "target")),
    ],
)
def test_all_required_statement_families_round_trip(statement: HypothesisStatement) -> None:
    parsed = statement_from_dict(statement.family, statement.to_dict())

    assert parsed == statement
    assert parsed.family in set(HypothesisFamily)
    assert isinstance(parsed.to_dict(), Mapping)


def test_receipts_and_predictions_are_typed_and_do_not_claim_probability() -> None:
    prediction = HypothesisPrediction("P-1", "ACTION1", {"delta": "up"}, rank_weight=7)
    receipt = EvidenceReceipt(
        "R-1",
        EvidenceKind.CONTRADICTION,
        ("E-2", "E-1", "E-1"),
        "the observed component moved right",
        observed_step=2,
        rank_impact=3,
    )

    assert prediction.to_dict()["weight_kind"] == "uncalibrated_rank"
    assert "probability" not in prediction.to_dict()
    assert receipt.evidence_event_ids == ("E-1", "E-2")
    assert receipt.signed_rank_impact == -3
    assert EvidenceReceipt.from_dict(receipt.to_dict()) == receipt
    assert HypothesisPrediction.from_dict(prediction.to_dict()) == prediction


def test_malformed_evidence_and_family_fields_are_rejected() -> None:
    with pytest.raises(HypothesisError, match="source event"):
        EvidenceReceipt("R-1", EvidenceKind.SUPPORT, (), "no source", 0)
    with pytest.raises(HypothesisError, match="traversable"):
        CollisionTraversabilityStatement.from_dict(
            {
                "moving_kind": "avatar",
                "obstacle_kind": "wall",
                "traversable": 1,
                "consequence": "blocked",
            }
        )
