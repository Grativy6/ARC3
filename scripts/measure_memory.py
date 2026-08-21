"""Measure pinned Stage 11 scoped-memory benefit and long-run bounds."""

from __future__ import annotations

import json
import time
import tracemalloc
from datetime import UTC, datetime
from typing import cast

from arc3.memory import (
    AbstractState,
    MemoryBudget,
    MemoryKind,
    MemoryQuery,
    MemoryRecord,
    PersistentMemory,
    RuleSignature,
    SourceLinkedSummary,
    opaque_game_scope,
)
from arc3.trace import CodeIdentity, SourceIdentity, SummaryClaim, TraceEvent, TraceSummary
from arc3.trace.canonical import sha256_json
from arc3.types import StateScope

CONFIG_HASH = "sha256:" + "6" * 64
CHUNK_HASH = "sha256:" + "7" * 64
CODE = CodeIdentity("stage11-memory-measurement", CONFIG_HASH)


def source_summary() -> SourceLinkedSummary:
    source = SourceIdentity("synthetic-direction-family", "1")
    event = TraceEvent.create(
        run_id="stage11-memory-measurement",
        episode_id="level-one",
        game_id="redacted",
        level_index=0,
        step_index=1,
        event_type="consequence.received",
        source=source,
        scope="episode",
        payload={"effect": "salient-component-translated-up"},
        code_identity=CODE,
        previous_event_hash=None,
        event_id="E-STAGE11-DIRECTION",
        occurred_at="2026-08-21T00:00:00Z",
        recorded_at="2026-08-21T00:00:00Z",
    )
    summary = TraceSummary(
        source_event_start_id=event.event_id,
        source_event_end_id=event.event_id,
        source_chunk_hashes=(CHUNK_HASH,),
        generated_at="2026-08-21T00:00:01Z",
        generator_git_commit=CODE.git_commit,
        generator_config_hash=CODE.config_hash,
        claims=(
            SummaryClaim(
                claim={"action": "ACTION3", "effect": "translate-up"},
                supporting_event_ids=(event.event_id,),
            ),
        ),
        unresolved_residuals=(),
        retrieval_tags=("directional-semantics", "cross-level"),
    )
    return SourceLinkedSummary.from_events(summary, (event,))


def measure_cross_level(summary: SourceLinkedSummary) -> dict[str, object]:
    scope = opaque_game_scope(
        run_scope_salt="stage11-synthetic-run",
        environment_scope_token="same-procedural-game",
    )
    rule = RuleSignature(
        family="unknown-directional-mapping",
        operation="translate-up",
        predicates=("one-controllable-component",),
    )
    memory = PersistentMemory()
    memory.add(
        MemoryRecord(
            memory_id="M-STAGE11-DIRECTION",
            kind=MemoryKind.RULE,
            scope=StateScope.GAME,
            summary=summary,
            game_scope_hash=scope,
            abstract_state=AbstractState(("one-controllable-component", "one-target-above")),
            rule_signature=rule,
            payload={"action": "ACTION3", "effect": "translate-up"},
        )
    )
    hits = memory.retrieve(
        MemoryQuery(
            episode_id="level-two",
            game_scope_hash=scope,
            abstract_state=AbstractState(("one-target-above", "one-controllable-component")),
            analogous_rule=rule,
        )
    )
    ordered_effects = (
        ("ACTION1", "translate-left"),
        ("ACTION2", "translate-down"),
        ("ACTION3", "translate-up"),
        ("ACTION4", "translate-right"),
    )
    no_memory_probes = next(
        ordinal
        for ordinal, (_action, effect) in enumerate(ordered_effects, start=1)
        if effect == "translate-up"
    )
    recalled_action = str(hits[0].record.payload["action"]) if hits else ""
    with_memory_probes = int(
        any(
            action == recalled_action and effect == "translate-up"
            for action, effect in ordered_effects
        )
    )
    return {
        "scorer": "arc3.memory.direction-validation-probes.v0.1",
        "with_memory_probes": with_memory_probes,
        "without_memory_probes": no_memory_probes,
        "probe_reduction": no_memory_probes - with_memory_probes,
        "probe_reduction_fraction": ((no_memory_probes - with_memory_probes) / no_memory_probes),
        "retrieved_source_event_ids": (
            list(hits[0].record.summary.source_event_ids) if hits else []
        ),
    }


def measure_bounds(summary: SourceLinkedSummary) -> dict[str, object]:
    budget = MemoryBudget(
        max_records=128,
        max_bytes=524_288,
        max_episode_records=128,
        max_game_records=128,
        max_generic_records=128,
    )
    scope = opaque_game_scope(
        run_scope_salt="stage11-long-run",
        environment_scope_token="bounded-procedural-game",
    )
    memory = PersistentMemory(budget=budget)
    tracemalloc.start()
    started = time.perf_counter()
    for ordinal in range(5_000):
        memory.add(
            MemoryRecord(
                memory_id=f"M-LONG-{ordinal:06d}",
                kind=MemoryKind.EVENT,
                scope=StateScope.GAME,
                summary=summary,
                game_scope_hash=scope,
                importance=(ordinal % 11) - 5,
                payload={"ordinal": ordinal, "bounded_note": "x" * (ordinal % 29)},
            )
        )
    elapsed_seconds = time.perf_counter() - started
    current_bytes, peak_bytes = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    snapshot = memory.to_dict()
    return {
        "insertions": 5_000,
        "elapsed_seconds": elapsed_seconds,
        "retained_records": memory.record_count,
        "record_limit": budget.max_records,
        "encoded_store_bytes": memory.byte_size,
        "encoded_byte_limit": budget.max_bytes,
        "tracemalloc_current_bytes": current_bytes,
        "tracemalloc_peak_bytes": peak_bytes,
        "record_bound_held": memory.record_count <= budget.max_records,
        "encoded_byte_bound_held": memory.byte_size <= budget.max_bytes,
        "snapshot_sha256": sha256_json(snapshot),
    }


def main() -> int:
    started_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    summary = source_summary()
    cross_level = measure_cross_level(summary)
    bounds = measure_bounds(summary)
    observed = (
        cast(int, cross_level["with_memory_probes"])
        < cast(int, cross_level["without_memory_probes"])
        and bounds["record_bound_held"] is True
        and bounds["encoded_byte_bound_held"] is True
    )
    print(
        json.dumps(
            {
                "schema": "arc3.memory.comparison.v0.1",
                "label": "synthetic",
                "status": ("MECHANISM_OBSERVED" if observed else "MECHANISM_NOT_OBSERVED"),
                "started_at": started_at,
                "completed_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                "cross_level": cross_level,
                "long_run": bounds,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
