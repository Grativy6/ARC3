from __future__ import annotations

import pytest

from arc3.errors import ARC3ValidationError
from arc3.trace.canonical import sha256_json
from arc3.wise_scientist import ActCommand, ScanCommand


def _prediction(prediction_id: str, consequence: str) -> dict[str, object]:
    return {
        "prediction_id": prediction_id,
        "consequence": consequence,
        "discriminator": f"observe whether {consequence}",
    }


def _distinction() -> dict[str, object]:
    return {
        "distinction_id": "D-1",
        "statement": "The control may move or transform the marked object.",
        "predictions": [
            _prediction("P-MOVE", "the marked object moves"),
            _prediction("P-TRANSFORM", "the marked object transforms in place"),
        ],
        "decision_that_could_change": "whether to repeat the control",
        "parent_goal_or_constraint_id": "G-1",
        "governing_objective_id": "OBJ-WIN",
        "relevance": "ACTIVE",
        "reopening_condition": "a later control has a different consequence",
    }


def _subgoal() -> dict[str, object]:
    return {
        "goal_id": "G-1",
        "parent_goal_or_constraint_id": "OBJ-WIN",
        "motivation": "The effect of the advertised control blocks a route choice.",
        "decision_that_could_change": "which route is shortest",
        "smallest_test_or_plan": "apply the control once",
        "success_condition": "the route effect is observed",
        "abandonment_condition": "the control cannot affect access",
        "reopening_condition": "access becomes blocked again",
        "status": "ACTIVE",
    }


def test_scan_rejects_a_distinction_without_competing_predictions() -> None:
    distinction = _distinction()
    distinction["predictions"] = [_prediction("P-ONLY", "one consequence")]

    with pytest.raises(ARC3ValidationError, match="competing predictions"):
        ScanCommand.from_dict(
            {
                "observation_hash": sha256_json({"observation": 1}),
                "stage_summary": "Initial surface.",
                "distinctions": [distinction],
                "subgoals": [_subgoal()],
            }
        )


def test_scan_allows_no_live_distinction_when_supported_plan_has_provenance() -> None:
    command = ScanCommand.from_dict(
        {
            "observation_hash": sha256_json({"observation": 1}),
            "stage_summary": "A supported route is directly visible.",
            "distinctions": [],
            "subgoals": [_subgoal()],
        }
    )

    assert command.distinctions == ()
    assert command.subgoals[0].parent_goal_or_constraint_id == "OBJ-WIN"


def test_discriminating_action_requires_an_implicated_distinction() -> None:
    with pytest.raises(ARC3ValidationError, match="requires an implicated distinction"):
        ActCommand.from_dict(
            {
                "observation_hash": sha256_json({"observation": 1}),
                "action": {"name": "ACTION1", "coordinate": None},
                "active_goal_id": "G-1",
                "distinction_ids": [],
                "predicted_consequence": "the marker moves",
                "alternatives": [
                    {
                        "action": {"name": "ACTION2", "coordinate": None},
                        "summary": "may move away from access",
                    }
                ],
                "rationale": "DISCRIMINATE_LIVE_HYPOTHESES",
                "rationale_summary": "Smallest safe discriminating probe.",
            }
        )


def test_mandatory_reset_needs_no_artificial_alternative_or_distinction() -> None:
    command = ActCommand.from_dict(
        {
            "observation_hash": sha256_json({"observation": 1}),
            "action": {"name": "RESET", "coordinate": None},
            "active_goal_id": "OBJ-WIN",
            "distinction_ids": [],
            "predicted_consequence": "the official environment restarts",
            "alternatives": [],
            "rationale": "MANDATORY_RESET",
            "rationale_summary": "RESET is the only legal recovery action.",
        }
    )

    assert command.alternatives == ()
    assert command.distinction_ids == ()
