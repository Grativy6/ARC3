from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from arc3.memory import (
    MemoryBudget,
    MemoryKind,
    MemoryRecord,
    PersistentMemory,
    SourceLinkedSummary,
    TraceChunkPlanner,
    opaque_game_scope,
)
from arc3.trace import CodeIdentity, SourceIdentity, SummaryClaim, TraceEvent, TraceSummary
from arc3.types import StateScope

CONFIG_HASH = "sha256:" + "1" * 64
CHUNK_HASH = "sha256:" + "2" * 64
CODE = CodeIdentity("property-memory", CONFIG_HASH)
SOURCE = SourceIdentity("property-memory", "1")


def event(ordinal: int, previous_hash: str | None = None) -> TraceEvent:
    return TraceEvent.create(
        run_id="memory-property-run",
        episode_id="memory-property-episode",
        game_id="redacted",
        level_index=0,
        step_index=ordinal,
        event_type="run.resumed",
        source=SOURCE,
        scope="run",
        payload={"ordinal": ordinal},
        code_identity=CODE,
        previous_event_hash=previous_hash,
        event_id=f"E-PROPERTY-{ordinal:06d}",
        occurred_at="2026-08-21T00:00:00Z",
        recorded_at="2026-08-21T00:00:00Z",
    )


def source() -> SourceLinkedSummary:
    receipt = event(0)
    summary = TraceSummary(
        source_event_start_id=receipt.event_id,
        source_event_end_id=receipt.event_id,
        source_chunk_hashes=(CHUNK_HASH,),
        generated_at="2026-08-21T00:00:01Z",
        generator_git_commit=CODE.git_commit,
        generator_config_hash=CODE.config_hash,
        claims=(SummaryClaim(claim="bounded source", supporting_event_ids=(receipt.event_id,)),),
        unresolved_residuals=(),
        retrieval_tags=("bounded",),
    )
    return SourceLinkedSummary.from_events(summary, (receipt,))


@settings(max_examples=30, deadline=None)
@given(importances=st.lists(st.integers(min_value=-5, max_value=5), min_size=25, max_size=100))
def test_memory_eviction_is_deterministic_and_never_exceeds_bounds(
    importances: list[int],
) -> None:
    budget = MemoryBudget(
        max_records=12,
        max_bytes=30_000,
        max_episode_records=12,
        max_game_records=12,
        max_generic_records=12,
    )
    scope = opaque_game_scope(run_scope_salt="property", environment_scope_token="scope")

    def populate() -> PersistentMemory:
        memory = PersistentMemory(budget=budget)
        for ordinal, importance in enumerate(importances):
            memory.add(
                MemoryRecord(
                    memory_id=f"M-{ordinal:04d}",
                    kind=MemoryKind.EVENT,
                    scope=StateScope.GAME,
                    summary=source(),
                    game_scope_hash=scope,
                    importance=importance,
                    payload={"bounded_note": "x" * (ordinal % 29)},
                )
            )
            assert memory.record_count <= budget.max_records
            assert memory.byte_size <= budget.max_bytes
        return memory

    first = populate()
    second = populate()
    assert first.to_dict() == second.to_dict()


@settings(max_examples=30, deadline=None)
@given(
    event_count=st.integers(min_value=1, max_value=80),
    max_events=st.integers(min_value=1, max_value=12),
    max_bytes=st.integers(min_value=200, max_value=5_000),
)
def test_trace_chunk_plans_preserve_order_and_boundaries(
    event_count: int,
    max_events: int,
    max_bytes: int,
) -> None:
    events: list[TraceEvent] = []
    previous: str | None = None
    for ordinal in range(event_count):
        receipt = event(ordinal, previous)
        events.append(receipt)
        previous = receipt.event_hash
    plans = TraceChunkPlanner(max_events=max_events, max_bytes=max_bytes).plan(events)
    assert sum(plan.event_count for plan in plans) == event_count
    assert plans[0].first_event_id == events[0].event_id
    assert plans[-1].last_event_id == events[-1].event_id
    assert all(plan.event_count <= max_events for plan in plans)
    assert all(plan.byte_length <= max_bytes or plan.oversize_single_event for plan in plans)
