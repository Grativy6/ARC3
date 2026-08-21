from __future__ import annotations

from dataclasses import fields

from arc3.perception.components import ComponentConfig, extract_components
from arc3.perception.delta import measure_delta
from arc3.perception.frame import normalize_grid
from arc3.perception.render import render_grid_svg, render_grid_text, summarize_perception
from arc3.perception.salience import (
    ActionEffectEvidence,
    ControllabilityCandidate,
    ControllabilityStatus,
    infer_controllability_candidates,
)
from arc3.types import ActionName


def test_single_action_effect_remains_insufficient() -> None:
    candidates = infer_controllability_candidates(
        (ActionEffectEvidence(ActionName.ACTION1, "shape-a", True, 1.0),)
    )
    assert candidates[0].status is ControllabilityStatus.INSUFFICIENT


def test_repeated_action_correlated_change_creates_only_a_candidate() -> None:
    evidence = (
        ActionEffectEvidence(ActionName.ACTION1, "shape-a", True, 1.0),
        ActionEffectEvidence(ActionName.ACTION2, "shape-a", True, 0.8),
        ActionEffectEvidence(ActionName.ACTION1, "shape-a", False, 0.2),
    )
    candidate = infer_controllability_candidates(evidence)[0]
    assert candidate.status is ControllabilityStatus.CANDIDATE
    assert candidate.evidence_count == 3
    assert candidate.changed_evidence_count == 2
    assert candidate.weighted_change_ratio == 0.9


def test_observation_layer_candidate_fields_are_measurement_only() -> None:
    field_names = {field.name for field in fields(ControllabilityCandidate)}
    assert "player" not in field_names
    assert "goal" not in field_names
    assert "accepted" not in {status.value for status in ControllabilityStatus}


def test_debug_renderers_are_bounded_and_escape_palette_values() -> None:
    before = normalize_grid([[0, 1], [2, 3]])
    after = normalize_grid([[0, 1], [2, 4]])
    components = extract_components(after, config=ComponentConfig(background_candidates=(0,)))
    assert render_grid_text(before) == "01\n23"
    palette = tuple(["#000"] * 15 + ['"><script>'])
    svg = render_grid_svg(normalize_grid([[15]]), palette=palette)
    assert "<script>" not in svg
    assert "&lt;script&gt;" in svg
    summary = summarize_perception(after, components=components, delta=measure_delta(before, after))
    assert "changed_cells=1" in summary
    assert len(summary.splitlines()) <= 3 + len(components)
