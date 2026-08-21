from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from arc3.hypotheses import (
    ActionSemanticsStatement,
    EvidenceKind,
    EvidenceReceipt,
    HypothesisEvent,
    HypothesisRegistry,
    HypothesisScope,
)


@settings(max_examples=35, deadline=None)
@given(st.lists(st.integers(min_value=1, max_value=20), min_size=1, max_size=12))
def test_arbitrary_support_history_rebuild_is_deterministic(impacts: list[int]) -> None:
    registry = HypothesisRegistry()
    registry.create(
        hypothesis_id="H-PROPERTY",
        statement=ActionSemanticsStatement("ACTION1", "translate", {"dy": -1}),
        scope=HypothesisScope.GENERIC,
        created_from_event_ids=("E-CREATE",),
        occurred_step=0,
    )
    for step, impact in enumerate(impacts, start=1):
        registry.support(
            "H-PROPERTY",
            EvidenceReceipt(
                f"R-{step}",
                EvidenceKind.SUPPORT,
                (f"E-{step}",),
                "matching transition",
                step,
                impact,
            ),
        )

    replayed = HypothesisRegistry(
        HypothesisEvent.from_dict(event.to_dict()) for event in registry.events
    )

    assert replayed.canonical_snapshot() == registry.canonical_snapshot()
    assert replayed.get("H-PROPERTY").rank_weight == sum(impacts)
    assert len(replayed.get("H-PROPERTY").support_receipts) == len(impacts)


@settings(max_examples=30, deadline=None)
@given(st.integers(min_value=-20, max_value=20), st.integers(min_value=-20, max_value=20))
def test_conflicting_tie_break_is_stable_for_all_integer_weights(
    left_weight: int, right_weight: int
) -> None:
    registry = HypothesisRegistry()
    registry.create(
        hypothesis_id="H-A",
        statement=ActionSemanticsStatement("ACTION2", "translate", {"dx": -1}),
        scope=HypothesisScope.LEVEL,
        created_from_event_ids=("E-0",),
        occurred_step=0,
        initial_rank_weight=left_weight,
    )
    registry.create(
        hypothesis_id="H-B",
        statement=ActionSemanticsStatement("ACTION2", "translate", {"dx": 1}),
        scope=HypothesisScope.LEVEL,
        created_from_event_ids=("E-0",),
        occurred_step=0,
        initial_rank_weight=right_weight,
    )

    forward = registry.resolve_conflict(("H-A", "H-B"))
    reverse = registry.resolve_conflict(("H-B", "H-A"))

    assert forward == reverse
    assert forward.hypothesis_id == ("H-A" if left_weight >= right_weight else "H-B")
