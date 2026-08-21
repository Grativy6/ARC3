from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from arc3.errors import TraceIntegrityError
from arc3.trace import (
    CodeIdentity,
    EventJournal,
    SourceIdentity,
    TraceEvent,
    canonical_bytes,
    identity_migrate,
    rebuild_index,
    sha256_bytes,
    verify_migration_manifest,
)

CONFIG_HASH = "sha256:" + "1" * 64
SOURCE = SourceIdentity("property_test", "1")
CODE = CodeIdentity("abc123", CONFIG_HASH)
WHEN = "2026-08-21T00:00:00Z"

json_scalars = st.none() | st.booleans() | st.integers(-(2**53), 2**53) | st.text(max_size=30)
receipt_safe_keys = st.text(min_size=1, max_size=12).map(lambda value: f"field_{value}")
json_values = st.recursive(
    json_scalars,
    lambda children: (
        st.lists(children, max_size=5) | st.dictionaries(receipt_safe_keys, children, max_size=5)
    ),
    max_leaves=15,
)
json_objects = st.dictionaries(receipt_safe_keys, json_values, max_size=8)


def run_event(payload: dict[str, object], *, event_id: str = "E-PROPERTY") -> TraceEvent:
    return TraceEvent.create(
        run_id="run-property",
        episode_id="episode-1",
        game_id="synthetic-redacted",
        level_index=0,
        step_index=0,
        event_type="run.started",
        source=SOURCE,
        scope="run",
        payload=payload,
        code_identity=CODE,
        previous_event_hash=None,
        event_id=event_id,
        occurred_at=WHEN,
        recorded_at=WHEN,
    )


@pytest.mark.property
@settings(max_examples=60, deadline=None)
@given(json_objects)
def test_arbitrary_valid_event_round_trips_without_semantic_loss(
    payload: dict[str, object],
) -> None:
    original = run_event(payload)
    restored = TraceEvent.from_dict(original.to_dict())
    assert restored == original
    assert restored.payload == original.payload


@pytest.mark.property
@settings(max_examples=20, deadline=None)
@given(st.integers(min_value=0, max_value=10_000))
def test_mutating_any_position_of_a_sealed_chunk_fails_manifest_verification(
    selector: int,
) -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary) / "trace"
        journal = EventJournal(root, run_id="run-property")
        journal.append_event(run_event({"selector": selector}))
        entry = journal.seal()
        journal.close()

        chunk_path = root / entry.path
        content = bytearray(chunk_path.read_bytes())
        position = selector % (len(content) - 1)
        content[position] ^= 1
        chunk_path.write_bytes(content)

        with pytest.raises(TraceIntegrityError):
            EventJournal(root, run_id="run-property")


@pytest.mark.property
@settings(max_examples=30, deadline=None)
@given(st.lists(st.text(min_size=1, max_size=20), min_size=1, max_size=10))
def test_derived_index_rebuild_is_deterministic_for_arbitrary_receipts(
    payloads: list[str],
) -> None:
    events: list[TraceEvent] = []
    previous: str | None = None
    for index, value in enumerate(payloads):
        event = TraceEvent.create(
            run_id="run-property",
            episode_id="episode-1",
            game_id="synthetic-redacted",
            level_index=0,
            step_index=index,
            event_type="run.environment_fault",
            source=SOURCE,
            scope="run",
            payload={"value": value},
            code_identity=CODE,
            previous_event_hash=previous,
            event_id=f"E-{index:04d}",
            occurred_at=WHEN,
            recorded_at=WHEN,
        )
        events.append(event)
        previous = event.event_hash
    assert (
        rebuild_index(events).canonical_snapshot()
        == rebuild_index(tuple(events)).canonical_snapshot()
    )


@pytest.mark.property
@settings(max_examples=20, deadline=None)
@given(st.lists(st.sampled_from(["supported", "contradicted", "narrowed"]), max_size=8))
def test_rejected_hypothesis_remains_queryable_after_any_prior_history(
    history: list[str],
) -> None:
    events: list[TraceEvent] = []
    created = TraceEvent.create(
        run_id="run-property",
        episode_id="episode-1",
        game_id="synthetic-redacted",
        level_index=0,
        step_index=0,
        event_type="hypothesis.created",
        source=SOURCE,
        scope="game",
        payload={"hypothesis_id": "H-1", "status": "candidate", "parent_ids": []},
        code_identity=CODE,
        previous_event_hash=None,
        event_id="E-CREATED",
        occurred_at=WHEN,
        recorded_at=WHEN,
    )
    events.append(created)
    previous = created.event_hash
    for index, transition in enumerate(history):
        event = TraceEvent.create(
            run_id="run-property",
            episode_id="episode-1",
            game_id="synthetic-redacted",
            level_index=0,
            step_index=index,
            event_type=f"hypothesis.{transition}",
            source=SOURCE,
            scope="game",
            payload={"hypothesis_id": "H-1", "evidence_event_ids": [created.event_id]},
            code_identity=CODE,
            previous_event_hash=previous,
            event_id=f"E-{index:04d}-{transition}",
            occurred_at=WHEN,
            recorded_at=WHEN,
        )
        events.append(event)
        previous = event.event_hash
    rejected = TraceEvent.create(
        run_id="run-property",
        episode_id="episode-1",
        game_id="synthetic-redacted",
        level_index=0,
        step_index=len(history),
        event_type="hypothesis.rejected",
        source=SOURCE,
        scope="game",
        payload={"hypothesis_id": "H-1"},
        code_identity=CODE,
        previous_event_hash=previous,
        event_id="E-REJECTED",
        occurred_at=WHEN,
        recorded_at=WHEN,
    )
    index = rebuild_index([*events, rejected])
    assert index.hypothesis("H-1") is not None
    assert index.hypothesis("H-1").status == "rejected"  # type: ignore[union-attr]


@pytest.mark.property
@settings(max_examples=20, deadline=None)
@given(json_objects)
def test_identity_migration_preserves_source_hash_and_event_hashes(
    payload: dict[str, object],
) -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        source = root / "source.jsonl"
        source.write_bytes(canonical_bytes(run_event(payload).to_dict()) + b"\n")
        source_hash = sha256_bytes(source.read_bytes())
        manifest_path, manifest = identity_migrate(source, root / "destination.jsonl")

        assert sha256_bytes(source.read_bytes()) == source_hash == manifest.source_hash
        assert manifest.source_event_hashes == manifest.destination_event_hashes
        assert verify_migration_manifest(manifest_path).replay_equivalent is True
