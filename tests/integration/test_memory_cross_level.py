from __future__ import annotations

import pytest

from arc3.memory import (
    AbstractState,
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

CONFIG_HASH = "sha256:" + "6" * 64
CHUNK_HASH = "sha256:" + "7" * 64
CODE = CodeIdentity("cross-level-memory", CONFIG_HASH)
SOURCE = SourceIdentity("procedural-direction-family", "1")


def learned_direction_summary() -> SourceLinkedSummary:
    observed = TraceEvent.create(
        run_id="cross-level-run",
        episode_id="level-one",
        game_id="redacted",
        level_index=0,
        step_index=1,
        event_type="consequence.received",
        source=SOURCE,
        scope="episode",
        payload={"effect": "salient-component-translated-up"},
        code_identity=CODE,
        previous_event_hash=None,
        event_id="E-LEARNED-DIRECTION",
        occurred_at="2026-08-21T00:00:00Z",
        recorded_at="2026-08-21T00:00:00Z",
    )
    summary = TraceSummary(
        source_event_start_id=observed.event_id,
        source_event_end_id=observed.event_id,
        source_chunk_hashes=(CHUNK_HASH,),
        generated_at="2026-08-21T00:00:01Z",
        generator_git_commit=CODE.git_commit,
        generator_config_hash=CODE.config_hash,
        claims=(
            SummaryClaim(
                claim={"action": "ACTION3", "effect": "translate-up"},
                supporting_event_ids=(observed.event_id,),
            ),
        ),
        unresolved_residuals=(),
        retrieval_tags=("directional-semantics", "cross-level"),
    )
    return SourceLinkedSummary.from_events(summary, (observed,))


@pytest.mark.integration
def test_cross_level_rule_memory_reduces_probes_on_a_procedural_family() -> None:
    """Synthetic mechanism receipt: one prior level removes three mapping probes."""

    scope = opaque_game_scope(
        run_scope_salt="synthetic-run",
        environment_scope_token="same-procedural-game",
    )
    rule = RuleSignature(
        family="unknown-directional-mapping",
        operation="translate-up",
        predicates=("one-controllable-component",),
    )
    memory = PersistentMemory()
    record = MemoryRecord(
        memory_id="M-LEVEL-ONE-DIRECTION",
        kind=MemoryKind.RULE,
        scope=StateScope.GAME,
        summary=learned_direction_summary(),
        game_scope_hash=scope,
        abstract_state=AbstractState(("one-controllable-component", "one-target-above")),
        rule_signature=rule,
        payload={"action": "ACTION3", "effect": "translate-up"},
    )
    assert memory.add(record).retained

    # The second level changes palette and positions but retains the same abstract rule.
    level_two_state = AbstractState(("one-target-above", "one-controllable-component"))
    hits = memory.retrieve(
        MemoryQuery(
            episode_id="level-two",
            game_scope_hash=scope,
            abstract_state=level_two_state,
            analogous_rule=rule,
        )
    )
    assert len(hits) == 1
    recalled_action = hits[0].record.payload["action"]
    hidden_level_two_effects = {
        "ACTION1": "translate-left",
        "ACTION2": "translate-down",
        "ACTION3": "translate-up",
        "ACTION4": "translate-right",
    }
    no_memory_probe_actions = next(
        ordinal
        for ordinal, action in enumerate(hidden_level_two_effects, start=1)
        if hidden_level_two_effects[action] == "translate-up"
    )
    with_memory_probe_actions = int(
        hidden_level_two_effects[str(recalled_action)] == "translate-up"
    )
    assert recalled_action == "ACTION3"
    assert with_memory_probe_actions < no_memory_probe_actions
    assert hits[0].record.summary.source_event_ids == ("E-LEARNED-DIRECTION",)
