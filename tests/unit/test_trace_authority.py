"""Closed authority classification for interrupted deliberation recovery."""

from __future__ import annotations

import pytest

from arc3.trace.authority import is_revisable_interruption_event_type
from arc3.trace.schema import CORE_EVENT_TYPES

_AUTHORITY_BOUNDARY_EVENT_TYPES = sorted(
    {
        event_type
        for event_type in CORE_EVENT_TYPES
        if event_type.startswith(("evaluation.", "migration.", "run."))
    }
    | {
        "action.rejected_by_environment",
        "action.submitted",
        "consequence.received",
        "observation.parse_failed",
        "observation.received",
        "reasoning.cadence_activated",
        "reasoning.checkpoint_state",
        "reasoning.interruption_reopened",
        "unknown.future_receipt",
    }
)


@pytest.mark.parametrize(
    "event_type",
    [
        "action.candidates_generated",
        "action.selected",
        "action.validated",
        "goal.selected_for_planning",
        "hypothesis.created",
        "model.retrodiction_completed",
        "reasoning.deliberation_completed",
        "reasoning.path_selected",
        "simulation.prediction_emitted",
    ],
)
def test_revisable_interruption_classifier_accepts_derived_decision_receipts(
    event_type: str,
) -> None:
    assert is_revisable_interruption_event_type(event_type)


@pytest.mark.parametrize(
    "event_type",
    _AUTHORITY_BOUNDARY_EVENT_TYPES,
)
def test_revisable_interruption_classifier_rejects_authority_boundaries(
    event_type: str,
) -> None:
    assert not is_revisable_interruption_event_type(event_type)
