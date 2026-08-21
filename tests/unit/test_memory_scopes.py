from __future__ import annotations

from dataclasses import replace

import pytest

from arc3.memory import (
    AbstractState,
    MemoryAblations,
    MemoryBudget,
    MemoryContractError,
    MemoryKind,
    MemoryQuery,
    MemoryRecord,
    PersistentMemory,
    RuleSignature,
    SourceLinkedSummary,
    opaque_game_scope,
)
from arc3.trace import CodeIdentity, SourceIdentity, SummaryClaim, TraceEvent, TraceSummary
from arc3.types import StateScope

HASH_A = "sha256:" + "a" * 64
HASH_B = "sha256:" + "b" * 64
CODE = CodeIdentity("memory-test", HASH_A)
SOURCE = SourceIdentity("synthetic-memory-test", "1")


def source_link(prefix: str = "A") -> SourceLinkedSummary:
    first = TraceEvent.create(
        run_id="run-memory",
        episode_id="episode-memory",
        game_id="redacted",
        level_index=0,
        step_index=0,
        event_type="run.started",
        source=SOURCE,
        scope="run",
        payload={},
        code_identity=CODE,
        previous_event_hash=None,
        event_id=f"E-{prefix}-1",
        occurred_at="2026-08-21T00:00:00Z",
        recorded_at="2026-08-21T00:00:00Z",
    )
    second = TraceEvent.create(
        run_id="run-memory",
        episode_id="episode-memory",
        game_id="redacted",
        level_index=0,
        step_index=1,
        event_type="hypothesis.contradicted",
        source=SOURCE,
        scope="game",
        payload={"hypothesis_id": f"H-{prefix}", "evidence_event_ids": [first.event_id]},
        code_identity=CODE,
        previous_event_hash=first.event_hash,
        event_id=f"E-{prefix}-2",
        occurred_at="2026-08-21T00:00:01Z",
        recorded_at="2026-08-21T00:00:01Z",
    )
    summary = TraceSummary(
        source_event_start_id=first.event_id,
        source_event_end_id=second.event_id,
        source_chunk_hashes=(HASH_B,),
        generated_at="2026-08-21T00:00:02Z",
        generator_git_commit=CODE.git_commit,
        generator_config_hash=CODE.config_hash,
        claims=(
            SummaryClaim(
                claim={"effect": "translation"},
                supporting_event_ids=(first.event_id,),
                contradicting_event_ids=(second.event_id,),
            ),
        ),
        unresolved_residuals=("direction remains conditional",),
        retrieval_tags=("structural", "translation"),
    )
    return SourceLinkedSummary.from_events(summary, (first, second))


def test_summary_cannot_exist_without_exact_event_hashes_and_range() -> None:
    linked = source_link()
    assert linked.source_event_ids == ("E-A-1", "E-A-2")
    assert linked.source_hash.startswith("sha256:")
    with pytest.raises(MemoryContractError, match="equally sized"):
        replace(linked, source_event_hashes=())
    with pytest.raises(MemoryContractError, match="start"):
        replace(linked, source_event_ids=("E-WRONG", "E-A-2"))


def test_scoped_retrieval_orders_exact_state_contradiction_and_rule() -> None:
    scope = opaque_game_scope(run_scope_salt="run", environment_scope_token="opaque-A")
    other_scope = opaque_game_scope(run_scope_salt="run", environment_scope_token="opaque-B")
    state = AbstractState(("one-mobile-component", "target-adjacent"))
    rule = RuleSignature("movement", "translate", ("blocked-by-boundary",))
    memory = PersistentMemory(
        budget=MemoryBudget(max_records=16, max_bytes=200_000),
    )
    episode = MemoryRecord(
        memory_id="M-EPISODE",
        kind=MemoryKind.ABSTRACT_STATE,
        scope=StateScope.EPISODE,
        summary=source_link("EP"),
        episode_id="level-2",
        game_scope_hash=scope,
        abstract_state=state,
        importance=4,
    )
    game = MemoryRecord(
        memory_id="M-GAME",
        kind=MemoryKind.CONTRADICTION,
        scope=StateScope.GAME,
        summary=source_link("GM"),
        game_scope_hash=scope,
        active_contradiction_ids=("C-WALL",),
        rule_signature=rule,
    )
    hidden_other_game = replace(game, memory_id="M-OTHER", game_scope_hash=other_scope)
    generic = MemoryRecord(
        memory_id="M-GENERIC",
        kind=MemoryKind.RULE,
        scope=StateScope.GENERIC,
        summary=source_link("GN"),
        rule_signature=rule,
        origin_scope_hashes=(scope, other_scope),
    )
    for record in (episode, game, hidden_other_game, generic):
        assert memory.add(record).retained

    query = MemoryQuery(
        episode_id="level-2",
        game_scope_hash=scope,
        exact_event_id="E-EP-1",
        abstract_state=state,
        active_contradiction_ids=("C-WALL",),
        analogous_rule=rule,
        current_game_evidence_event_ids=("E-GM-1",),
    )
    hits = memory.retrieve(query)
    assert [hit.record.memory_id for hit in hits][:2] == ["M-EPISODE", "M-GAME"]
    assert "M-OTHER" not in {hit.record.memory_id for hit in hits}
    assert "M-GENERIC" in {hit.record.memory_id for hit in hits}
    assert hits[0].record.summary.source_event_hashes == episode.summary.source_event_hashes


def test_generic_retrieval_requires_current_game_evidence() -> None:
    first_scope = opaque_game_scope(run_scope_salt="run", environment_scope_token="first")
    second_scope = opaque_game_scope(run_scope_salt="run", environment_scope_token="second")
    rule = RuleSignature("contact", "toggle", ("adjacent",))
    memory = PersistentMemory()
    generic = MemoryRecord(
        memory_id="M-GENERIC",
        kind=MemoryKind.RULE,
        scope=StateScope.GENERIC,
        summary=source_link("G"),
        rule_signature=rule,
        origin_scope_hashes=(first_scope, second_scope),
    )
    assert memory.add(generic).retained
    assert not memory.retrieve(MemoryQuery(game_scope_hash=first_scope, analogous_rule=rule))

    game_record = MemoryRecord(
        memory_id="M-CURRENT",
        kind=MemoryKind.EVENT,
        scope=StateScope.GAME,
        summary=source_link("CURRENT"),
        game_scope_hash=first_scope,
    )
    memory.add(game_record)
    hits = memory.retrieve(
        MemoryQuery(
            game_scope_hash=first_scope,
            analogous_rule=rule,
            current_game_evidence_event_ids=("E-CURRENT-1",),
        )
    )
    assert [hit.record.memory_id for hit in hits] == ["M-GENERIC"]


def test_ablation_switches_disable_memory_and_rejected_retention() -> None:
    scope = opaque_game_scope(run_scope_salt="run", environment_scope_token="scope")
    rejected = MemoryRecord(
        memory_id="M-REJECTED",
        kind=MemoryKind.CONTRADICTION,
        scope=StateScope.GAME,
        summary=source_link("R"),
        game_scope_hash=scope,
        active_contradiction_ids=("C-1",),
        rejected_hypothesis_ids=("H-REJECTED",),
    )
    no_memory = PersistentMemory(ablations=MemoryAblations(memory_enabled=False))
    assert no_memory.add(rejected).reason == "memory_disabled_ablation"
    assert no_memory.record_count == 0

    no_rejected = PersistentMemory(ablations=MemoryAblations(retain_rejected_hypotheses=False))
    assert no_rejected.add(rejected).reason == "rejected_retention_disabled_ablation"
    assert no_rejected.record_count == 0


def test_solution_shaped_payload_and_generic_single_scope_promotion_are_rejected() -> None:
    scope = opaque_game_scope(run_scope_salt="run", environment_scope_token="scope")
    with pytest.raises(MemoryContractError, match="solution lookup"):
        MemoryRecord(
            memory_id="M-BAD",
            kind=MemoryKind.EVENT,
            scope=StateScope.GAME,
            summary=source_link("BAD"),
            game_scope_hash=scope,
            payload={"action_sequence": ["ACTION1", "ACTION2"]},
        )
    with pytest.raises(MemoryContractError, match="at least two"):
        MemoryRecord(
            memory_id="M-PREMATURE",
            kind=MemoryKind.RULE,
            scope=StateScope.GENERIC,
            summary=source_link("PRE"),
            rule_signature=RuleSignature("movement", "translate"),
            origin_scope_hashes=(scope,),
        )
