"""Derived authority projection for immutable interrupted-deliberation receipts."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Final

from arc3.errors import TraceIntegrityError

from .schema import TraceEvent

_REVISABLE_INTERRUPTION_EVENT_TYPES: Final[frozenset[str]] = frozenset(
    {
        "action.candidates_generated",
        "action.fallback_used",
        "action.selected",
        "action.validated",
        "goal.candidate_created",
        "goal.contradicted",
        "goal.reopened",
        "goal.retired",
        "goal.selected_for_planning",
        "goal.supported",
        "goal.target_bound",
        "hypothesis.contradicted",
        "hypothesis.created",
        "hypothesis.narrowed",
        "hypothesis.rejected",
        "hypothesis.reopened",
        "hypothesis.scope_changed",
        "hypothesis.superseded",
        "hypothesis.supported",
        "model.retrodiction_completed",
        "model.retrodiction_reused",
        "model.retrodiction_started",
        "model.rule_demoted",
        "model.rule_promoted",
        "reasoning.deliberation_completed",
        "reasoning.fallback_used",
        "reasoning.path_selected",
        "simulation.plan_evaluated",
        "simulation.plan_invalidated",
        "simulation.prediction_emitted",
    }
)


def is_revisable_interruption_event_type(event_type: str) -> bool:
    """Return whether a receipt may be recomputed after pre-action recovery.

    This is intentionally a closed allowlist.  Raw environment receipts,
    adapter crossings, evaluation/migration/run lifecycle events, checkpoint
    receipts, and newly introduced event types remain authoritative until they
    receive an explicit recovery-safety audit.
    """

    return event_type in _REVISABLE_INTERRUPTION_EVENT_TYPES


def abandoned_event_ids(events: Sequence[TraceEvent]) -> frozenset[str]:
    """Validate reopen receipts and return only safely abandoned derived IDs.

    Raw environment receipts and adapter crossings are immutable *and* remain
    authoritative.  A recovery may exclude only the exact contiguous suffix
    after a non-pending checkpoint and before its own receipt.
    """

    ordered = tuple(events)
    event_by_id = {event.event_id: event for event in ordered}
    event_order = {event.event_id: index for index, event in enumerate(ordered)}
    abandoned: set[str] = set()
    for recovery in (
        event for event in ordered if event.event_type == "reasoning.interruption_reopened"
    ):
        checkpoint_id = recovery.payload.get("checkpoint_commitment_event_id")
        checkpoint = event_by_id.get(checkpoint_id) if isinstance(checkpoint_id, str) else None
        raw_ids = recovery.payload.get("abandoned_event_ids")
        raw_hashes = recovery.payload.get("abandoned_event_hashes")
        raw_tail_hash = recovery.payload.get("abandoned_tail_hash")
        if (
            checkpoint is None
            or checkpoint.event_type != "run.checkpoint_written"
            or checkpoint.payload.get("pending_submitted_event_id") is not None
            or not isinstance(raw_ids, list)
            or not raw_ids
            or not all(isinstance(item, str) and item for item in raw_ids)
            or len(set(raw_ids)) != len(raw_ids)
            or not isinstance(raw_hashes, list)
            or len(raw_hashes) != len(raw_ids)
            or not all(isinstance(item, str) and item for item in raw_hashes)
            or not isinstance(raw_tail_hash, str)
        ):
            raise TraceIntegrityError("interruption recovery receipt is malformed")
        checkpoint_index = event_order[checkpoint.event_id]
        recovery_index = event_order[recovery.event_id]
        exact_suffix = ordered[checkpoint_index + 1 : recovery_index]
        exact_ids = [event.event_id for event in exact_suffix]
        exact_hashes = [event.event_hash for event in exact_suffix]
        if (
            exact_ids != raw_ids
            or exact_hashes != raw_hashes
            or raw_tail_hash != exact_hashes[-1]
            or recovery.previous_event_hash != raw_tail_hash
            or recovery.episode_id != checkpoint.episode_id
            or recovery.level_index != checkpoint.level_index
            or recovery.step_index != checkpoint.step_index
            or any(
                event.episode_id != checkpoint.episode_id
                or event.level_index != checkpoint.level_index
                or event.step_index != checkpoint.step_index
                or not is_revisable_interruption_event_type(event.event_type)
                for event in exact_suffix
            )
        ):
            raise TraceIntegrityError(
                "interruption recovery does not name one exact safe derived suffix"
            )
        abandoned.update(exact_ids)
    return frozenset(abandoned)


def authoritative_events(events: Sequence[TraceEvent]) -> tuple[TraceEvent, ...]:
    """Project immutable receipts to the revisable policy-authority surface."""

    ordered = tuple(events)
    abandoned = abandoned_event_ids(ordered)
    return tuple(event for event in ordered if event.event_id not in abandoned)


__all__ = [
    "abandoned_event_ids",
    "authoritative_events",
    "is_revisable_interruption_event_type",
]
