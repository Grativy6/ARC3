from __future__ import annotations

from dataclasses import replace

import pytest

from arc3.errors import ARC3ValidationError, TraceIntegrityError
from arc3.trace import (
    CodeIdentity,
    SourceIdentity,
    TraceEvent,
    canonical_json,
    verify_event_chain,
)
from arc3.trace.canonical import sha256_json

CONFIG_HASH = "sha256:" + "1" * 64
SOURCE = SourceIdentity("synthetic_test", "1")
CODE = CodeIdentity("abc123", CONFIG_HASH)
WHEN = "2026-08-21T00:00:00Z"


def event(*, event_id: str, previous: str | None = None) -> TraceEvent:
    return TraceEvent.create(
        run_id="run-1",
        episode_id="episode-1",
        game_id="synthetic-redacted",
        level_index=0,
        step_index=0,
        event_type="run.started",
        source=SOURCE,
        scope="run",
        payload={"seed": 7, "nested": {"b": 2, "a": 1}},
        code_identity=CODE,
        previous_event_hash=previous,
        event_id=event_id,
        occurred_at=WHEN,
        recorded_at=WHEN,
    )


def test_canonical_json_is_stable_and_rejects_non_finite_numbers() -> None:
    left = {"z": [3, 2, 1], "a": {"second": 2, "first": 1}}
    right = {"a": {"first": 1, "second": 2}, "z": [3, 2, 1]}

    assert canonical_json(left) == canonical_json(right)
    assert canonical_json(left) == '{"a":{"first":1,"second":2},"z":[3,2,1]}'
    with pytest.raises(ARC3ValidationError, match="NaN"):
        canonical_json({"bad": float("nan")})


def test_event_hash_round_trip_and_any_payload_mutation_is_detected() -> None:
    original = event(event_id="E-0001")
    parsed = TraceEvent.from_dict(original.to_dict())
    assert parsed == original
    assert parsed.computed_hash() == original.event_hash

    changed_payload = dict(original.payload)
    changed_payload["seed"] = 8
    mutated = replace(original, payload=changed_payload)
    with pytest.raises(TraceIntegrityError, match="hash mismatch"):
        mutated.verify_hash()


def test_chain_enforces_previous_hash_and_unique_event_ids() -> None:
    first = event(event_id="E-0001")
    second = event(event_id="E-0002", previous=first.event_hash)
    verify_event_chain([first, second])

    broken = replace(second, previous_event_hash="sha256:" + "2" * 64)
    broken = replace(broken, event_hash=sha256_json(broken.to_dict(include_hash=False)))
    with pytest.raises(TraceIntegrityError, match="links to"):
        verify_event_chain([first, broken])
    duplicate = replace(second, event_id=first.event_id)
    duplicate = replace(duplicate, event_hash=sha256_json(duplicate.to_dict(include_hash=False)))
    with pytest.raises(TraceIntegrityError, match="duplicate event_id"):
        verify_event_chain([first, duplicate])


def test_action_selection_requires_typed_concise_rationale() -> None:
    base_payload = {
        "selected_action": {"name": "ACTION1", "coordinate": None},
        "candidate_utilities": [{"action": "ACTION1", "utility": 0.5}],
        "selected_probe_or_plan_id": "probe-1",
        "active_hypothesis_ids": ["H-1"],
        "predicted_outcome_ids": ["P-1"],
        "rationale_category": "discriminate_models",
        "rationale_summary": "tests whether ACTION1 translates the salient component",
    }
    selected = TraceEvent.create(
        run_id="run-1",
        episode_id="episode-1",
        game_id="synthetic-redacted",
        level_index=0,
        step_index=1,
        event_type="action.selected",
        source=SOURCE,
        scope="episode",
        payload=base_payload,
        code_identity=CODE,
        previous_event_hash=None,
        event_id="E-ACTION",
        occurred_at=WHEN,
        recorded_at=WHEN,
    )
    assert selected.payload["rationale_category"] == "discriminate_models"

    with pytest.raises(ARC3ValidationError, match="typed RationaleCategory"):
        TraceEvent.create(
            run_id="run-1",
            episode_id="episode-1",
            game_id="synthetic-redacted",
            level_index=0,
            step_index=1,
            event_type="action.selected",
            source=SOURCE,
            scope="episode",
            payload={**base_payload, "rationale_category": "free_form"},
            code_identity=CODE,
            previous_event_hash=None,
        )

    with pytest.raises(ARC3ValidationError, match="hidden reasoning"):
        TraceEvent.create(
            run_id="run-1",
            episode_id="episode-1",
            game_id="synthetic-redacted",
            level_index=0,
            step_index=1,
            event_type="action.selected",
            source=SOURCE,
            scope="episode",
            payload={**base_payload, "chain_of_thought": "unrestricted private transcript"},
            code_identity=CODE,
            previous_event_hash=None,
        )


def test_receipts_reject_credential_bearing_fields_at_any_depth() -> None:
    with pytest.raises(ARC3ValidationError, match="credential-bearing field"):
        TraceEvent.create(
            run_id="run-1",
            episode_id="episode-1",
            game_id="synthetic-redacted",
            level_index=0,
            step_index=0,
            event_type="run.started",
            source=SOURCE,
            scope="run",
            payload={"nested": {"arc_api_key": "must-never-be-recorded"}},
            code_identity=CODE,
            previous_event_hash=None,
        )


def test_observation_schema_validates_frame_receipt() -> None:
    payload = {
        "frame_count": 1,
        "frames": [
            {
                "blob_hash": "sha256:" + "a" * 64,
                "frame_hash": "sha256:" + "a" * 64,
                "width": 2,
                "height": 2,
                "palette": [0, 1],
            }
        ],
        "game_state": "NOT_FINISHED",
        "score": None,
        "available_actions": ["ACTION1"],
        "upstream_metadata": {"unknown": "preserved"},
    }
    receipt = TraceEvent.create(
        run_id="run-1",
        episode_id="episode-1",
        game_id="synthetic-redacted",
        level_index=0,
        step_index=0,
        event_type="observation.received",
        source=SOURCE,
        scope="episode",
        payload=payload,
        code_identity=CODE,
        previous_event_hash=None,
    )
    assert receipt.payload["upstream_metadata"] == {"unknown": "preserved"}

    payload["frames"][0]["width"] = 65
    with pytest.raises(ARC3ValidationError, match="dimensions"):
        TraceEvent.create(
            run_id="run-1",
            episode_id="episode-1",
            game_id="synthetic-redacted",
            level_index=0,
            step_index=0,
            event_type="observation.received",
            source=SOURCE,
            scope="episode",
            payload=payload,
            code_identity=CODE,
            previous_event_hash=None,
        )


def test_delta_schema_requires_empty_cells_and_metadata_for_apparent_noop() -> None:
    payload = {
        "before_frame_hash": "sha256:" + "a" * 64,
        "after_frame_hash": "sha256:" + "a" * 64,
        "changed_cell_count": 0,
        "cell_changes": [],
        "changed_bbox": None,
        "component_changes": [],
        "metadata_changes": {"state": {"before": "NOT_FINISHED", "after": "GAME_OVER"}},
        "apparent_noop": False,
    }
    receipt = TraceEvent.create(
        run_id="run-1",
        episode_id="episode-1",
        game_id="synthetic-redacted",
        level_index=0,
        step_index=1,
        event_type="observation.delta_measured",
        source=SOURCE,
        scope="episode",
        payload=payload,
        code_identity=CODE,
        previous_event_hash=None,
    )
    assert receipt.payload["apparent_noop"] is False

    with pytest.raises(ARC3ValidationError, match="empty cell and metadata"):
        TraceEvent.create(
            run_id="run-1",
            episode_id="episode-1",
            game_id="synthetic-redacted",
            level_index=0,
            step_index=1,
            event_type="observation.delta_measured",
            source=SOURCE,
            scope="episode",
            payload={**payload, "apparent_noop": True},
            code_identity=CODE,
            previous_event_hash=None,
        )


def test_reasoning_selection_requires_complete_typed_trigger_projection() -> None:
    source_event_id = "E-OBSERVATION"
    payload = {
        "action_registry_identity": "sha256:" + "2" * 64,
        "budget_limits": {"cache_capacity": 256, "search_nodes": 64},
        "cache_projection_hash": "sha256:" + "3" * 64,
        "cadence_mode": "TWO_SPEED",
        "configuration_hash": "sha256:" + "4" * 64,
        "goal_id": None,
        "goal_revision": 0,
        "mechanics_epoch_id": "mechanics-epoch:L0:0000",
        "observation_event_id": source_event_id,
        "ordered_triggers": ["STARTUP_UNKNOWN_ACTION"],
        "path": "DEEP",
        "plan_id": None,
        "schema": "arc3.reasoning-cadence-selection.v0.1",
        "state_id": "state:initial",
        "trigger_source_event_ids": [source_event_id],
        "trigger_sources": [
            {
                "source_event_ids": [source_event_id],
                "trigger": "STARTUP_UNKNOWN_ACTION",
            }
        ],
    }
    selected = TraceEvent.create(
        run_id="run-1",
        episode_id="episode-1",
        game_id="synthetic-redacted",
        level_index=0,
        step_index=0,
        event_type="reasoning.path_selected",
        source=SOURCE,
        scope="episode",
        payload=payload,
        code_identity=CODE,
        previous_event_hash=None,
    )
    assert selected.payload["trigger_source_event_ids"] == [source_event_id]

    with pytest.raises(ARC3ValidationError, match="requires a typed trigger"):
        TraceEvent.create(
            run_id="run-1",
            episode_id="episode-1",
            game_id="synthetic-redacted",
            level_index=0,
            step_index=0,
            event_type="reasoning.path_selected",
            source=SOURCE,
            scope="episode",
            payload={
                **payload,
                "ordered_triggers": [],
                "trigger_source_event_ids": [],
                "trigger_sources": [],
            },
            code_identity=CODE,
            previous_event_hash=None,
        )

    with pytest.raises(ARC3ValidationError, match="flattened trigger sources"):
        TraceEvent.create(
            run_id="run-1",
            episode_id="episode-1",
            game_id="synthetic-redacted",
            level_index=0,
            step_index=0,
            event_type="reasoning.path_selected",
            source=SOURCE,
            scope="episode",
            payload={**payload, "trigger_source_event_ids": ["E-BOGUS"]},
            code_identity=CODE,
            previous_event_hash=None,
        )
