from __future__ import annotations

from arc3.hypotheses import (
    ActionSemanticsStatement,
    EvidenceKind,
    EvidenceReceipt,
    HypothesisRegistry,
    HypothesisScope,
)
from arc3.trace import CodeIdentity, SourceIdentity, TraceEvent, rebuild_index, verify_event_chain
from arc3.types import HypothesisStatus

SOURCE = SourceIdentity("synthetic_test", "1")
CODE = CodeIdentity("stage-05-test", "sha256:" + "5" * 64)
WHEN = "2026-08-21T00:00:00Z"


def evidence(
    identifier: str, kind: EvidenceKind, source: str, step: int, impact: int = 1
) -> EvidenceReceipt:
    return EvidenceReceipt(identifier, kind, (source,), f"receipt {identifier}", step, impact)


def test_create_support_contradict_narrow_reject_reopen_preserves_complete_lineage() -> None:
    registry = HypothesisRegistry()
    registry.create(
        hypothesis_id="H-BROAD",
        event_id="HE-1-CREATE",
        statement=ActionSemanticsStatement("ACTION1", "translate", {"dx": 0, "dy": -1}),
        scope=HypothesisScope.GAME,
        scope_ref="synthetic-family/seed-7",
        created_from_event_ids=("E-OBS-0",),
        occurred_step=0,
        initial_rank_weight=2,
    )
    registry.support(
        "H-BROAD",
        evidence("R-SUPPORT", EvidenceKind.SUPPORT, "E-CONSEQUENCE-1", 1, 3),
        event_id="HE-2-SUPPORT",
    )
    registry.contradict(
        "H-BROAD",
        evidence("R-CONTRADICT", EvidenceKind.CONTRADICTION, "E-CONSEQUENCE-2", 2, 4),
        event_id="HE-3-CONTRADICT",
    )
    child = registry.narrow(
        "H-BROAD",
        new_hypothesis_id="H-CONTACT",
        narrowed_event_id="HE-5-NARROW",
        created_event_id="HE-4-CREATE-CHILD",
        statement=ActionSemanticsStatement(
            "ACTION1",
            "translate",
            {"dx": 0, "dy": -1},
            conditions=("not_in_contact",),
        ),
        receipt=evidence("R-RESIDUAL", EvidenceKind.RESIDUAL, "E-CONSEQUENCE-2", 2, 2),
        occurred_step=2,
    )
    registry.register_dependent_plan("PLAN-7", (child.hypothesis_id,))
    registry.reject(
        child.hypothesis_id,
        evidence("R-REJECT", EvidenceKind.CONTRADICTION, "E-CONSEQUENCE-3", 3, 2),
        event_id="HE-6-REJECT",
    )
    signal = registry.reopen(
        child.hypothesis_id,
        evidence("R-REOPEN", EvidenceKind.RESIDUAL, "E-CONSEQUENCE-4", 4, 1),
        event_id="HE-7-REOPEN",
    )

    broad = registry.get("H-BROAD")
    reopened = registry.get("H-CONTACT")
    lineage_history = registry.history("H-CONTACT", include_lineage=True)

    assert broad.status is HypothesisStatus.NARROWED
    assert broad.narrowed_to_ids == ("H-CONTACT",)
    assert reopened.status is HypothesisStatus.CANDIDATE
    assert reopened.parent_ids == ("H-BROAD",)
    assert reopened.contradiction_event_ids == ("E-CONSEQUENCE-3",)
    assert reopened.residual_event_ids == ("E-CONSEQUENCE-4",)
    assert registry.ever_rejected() == (reopened,)
    assert signal.plan_ids == ("PLAN-7",)
    assert signal.reason_receipt_id == "R-REOPEN"
    assert registry.dependent_plan_ids("H-CONTACT") == ()
    assert [event.event_id for event in lineage_history] == [
        "HE-1-CREATE",
        "HE-2-SUPPORT",
        "HE-3-CONTRADICT",
        "HE-4-CREATE-CHILD",
        "HE-5-NARROW",
        "HE-6-REJECT",
        "HE-7-REOPEN",
    ]

    trace_events: list[TraceEvent] = []
    previous_hash: str | None = None
    for event in registry.events:
        trace_event = TraceEvent.create(
            run_id="run-stage-05",
            episode_id="episode-stage-05",
            game_id="synthetic-redacted",
            level_index=0,
            step_index=event.occurred_step,
            event_type=event.event_type.value,
            source=SOURCE,
            scope="game",
            payload=event.to_trace_payload(),
            code_identity=CODE,
            previous_event_hash=previous_hash,
            event_id=f"T-{event.event_id}",
            occurred_at=WHEN,
            recorded_at=WHEN,
        )
        trace_events.append(trace_event)
        previous_hash = trace_event.event_hash

    verify_event_chain(trace_events)
    trace_index = rebuild_index(trace_events)
    assert trace_index.hypothesis("H-BROAD") is not None
    assert trace_index.hypothesis("H-BROAD").status == "narrowed"  # type: ignore[union-attr]
    assert trace_index.hypothesis("H-CONTACT") is not None
    assert trace_index.hypothesis("H-CONTACT").status == "candidate"  # type: ignore[union-attr]
    assert trace_index.hypothesis("H-CONTACT").parent_ids == ("H-BROAD",)  # type: ignore[union-attr]
