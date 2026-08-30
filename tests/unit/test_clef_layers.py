from __future__ import annotations

import pytest

from arc3.perception import (
    ActionWindow,
    DynamicClaimContext,
    EvidenceFamily,
    EvidenceReading,
    LayerAssessment,
    LayerDeclaration,
    LogicalLayer,
    ReadabilityThreshold,
    ReadabilityWall,
    ResidualDisposition,
    ResidualReason,
    ValidityGate,
    assess_residual,
)
from arc3.types import ActionName, ActionRequest, StateScope


def _declaration(
    *,
    wall: ReadabilityWall | None = None,
) -> LayerDeclaration:
    return LayerDeclaration(
        declaration_id="layer:components:1",
        layer=LogicalLayer.COMPONENTS,
        available_fields=("components", "frame.cells"),
        aperture="connected component",
        noise_thresholds=(
            ReadabilityThreshold(EvidenceFamily.FRAME_CELLS, 2),
            ReadabilityThreshold(EvidenceFamily.COMPONENT_GEOMETRY, 1),
        ),
        extraction_method="connected-components-v1",
        reader_identity="arc3.perception.components",
        readability_wall=wall or ReadabilityWall(max_detail_units=8, used_detail_units=2),
    )


def _assessment(*, gate_passed: bool = True) -> LayerAssessment:
    return LayerAssessment(
        declaration=_declaration(),
        readings=(
            EvidenceReading(EvidenceFamily.FRAME_CELLS, "frame:1", 100, ("event:cells",)),
            EvidenceReading(
                EvidenceFamily.COMPONENT_GEOMETRY,
                "component:1",
                2,
                ("event:component",),
            ),
            EvidenceReading(EvidenceFamily.FRAME_CELLS, "frame:2", 100),
        ),
        validity_gates=(
            ValidityGate("temporal-correspondence", gate_passed, evidence_event_ids=("event:t",)),
        ),
    )


def test_all_five_logical_layers_are_declared() -> None:
    assert tuple(LogicalLayer) == (
        LogicalLayer.RAW_FRAME_AND_METADATA,
        LogicalLayer.COMPONENTS,
        LogicalLayer.RELATIONS,
        LogicalLayer.ACTION_EFFECTS,
        LogicalLayer.PLANNING,
    )


def test_dynamic_action_effect_layer_requires_the_intervention_boundary() -> None:
    with pytest.raises(ValueError, match="dynamic claim context"):
        LayerDeclaration(
            declaration_id="layer:effect:missing-context",
            layer=LogicalLayer.ACTION_EFFECTS,
            available_fields=("delta",),
            aperture="one action",
            noise_thresholds=(ReadabilityThreshold(EvidenceFamily.TEMPORAL_TRACKING, 1),),
            extraction_method="temporal-correspondence",
            reader_identity="test-reader",
            readability_wall=ReadabilityWall(4),
        )

    declaration = LayerDeclaration(
        declaration_id="layer:effect:1",
        layer=LogicalLayer.ACTION_EFFECTS,
        available_fields=("delta",),
        aperture="one action",
        noise_thresholds=(ReadabilityThreshold(EvidenceFamily.TEMPORAL_TRACKING, 1),),
        extraction_method="temporal-correspondence",
        reader_identity="test-reader",
        readability_wall=ReadabilityWall(4),
        dynamic_context=DynamicClaimContext(
            window=ActionWindow(4, 5),
            intervention=ActionRequest(ActionName.ACTION1),
            assumed_scope=StateScope.LEVEL,
            observation_return_path=("event:before", "event:after"),
        ),
    )

    assert declaration.to_dict()["dynamic_context"] == {
        "window": {"before_step": 4, "after_step": 5},
        "intervention": {"name": "ACTION1", "coordinate": None},
        "assumed_scope": "level",
        "observation_return_path": ["event:before", "event:after"],
    }


def test_independent_evidence_families_do_not_double_count_contexts() -> None:
    assessment = _assessment()

    assert assessment.readable_evidence_families == (
        EvidenceFamily.COMPONENT_GEOMETRY,
        EvidenceFamily.FRAME_CELLS,
    )
    assert assessment.has_independent_support()
    assert assessment.distinct_dependency_contexts == (
        "component:1",
        "frame:1",
        "frame:2",
    )


def test_failed_required_gate_cannot_be_averaged_away_by_large_signals() -> None:
    assessment = _assessment(gate_passed=False)

    assert assessment.has_independent_support()
    decision = assess_residual(
        assessment,
        already_explained=False,
        changes_prediction=True,
        changes_action_selection=True,
        additional_detail_cost=1,
        expected_decision_value=100,
    )

    assert decision.disposition is ResidualDisposition.PARK
    assert decision.reason is ResidualReason.VALIDITY_GATE_FAILED


def test_residual_promotion_and_stopping_are_explicit() -> None:
    promoted = assess_residual(
        _assessment(),
        already_explained=False,
        changes_prediction=True,
        changes_action_selection=False,
        additional_detail_cost=2,
        expected_decision_value=3,
    )
    parked = assess_residual(
        _assessment(),
        already_explained=False,
        changes_prediction=False,
        changes_action_selection=False,
        additional_detail_cost=0,
        expected_decision_value=0,
    )
    wall_assessment = LayerAssessment(
        declaration=_declaration(wall=ReadabilityWall(2, used_detail_units=2)),
        readings=(EvidenceReading(EvidenceFamily.FRAME_CELLS, "frame:1", 2),),
        validity_gates=(ValidityGate("grid-valid", True),),
    )
    stopped = assess_residual(
        wall_assessment,
        already_explained=False,
        changes_prediction=True,
        changes_action_selection=True,
        additional_detail_cost=0,
        expected_decision_value=1,
    )

    assert promoted.disposition is ResidualDisposition.PROMOTE
    assert parked.disposition is ResidualDisposition.PARK
    assert parked.reason is ResidualReason.NO_DECISION_EFFECT
    assert stopped.disposition is ResidualDisposition.STOP
    assert stopped.reason is ResidualReason.READABILITY_WALL
