"""Typed Stage 14 mechanism removals with one switch per comparison."""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum

from arc3.policy import ControllerPreset, PresetFeatures, preset_features


class AblationId(StrEnum):
    """Stable identifiers from the controlling evaluation protocol."""

    A1 = "A1"
    A2 = "A2"
    A3 = "A3"
    A4 = "A4"
    A5 = "A5"
    A6 = "A6"
    A7 = "A7"
    A8 = "A8"
    A9 = "A9"
    A10 = "A10"


@dataclass(frozen=True, slots=True)
class AblationSpec:
    """One declared removal and the question it can test."""

    ablation_id: AblationId
    component: str
    question: str
    disabled_feature: str
    expected_effect_surface: str


_SPECS: tuple[AblationSpec, ...] = (
    AblationSpec(
        AblationId.A1,
        "persistent game memory",
        "Does cross-level trace help?",
        "use_memory",
        "behavior-and-runtime",
    ),
    AblationSpec(
        AblationId.A2,
        "rejected-hypothesis retention",
        "Does preserving failures reduce repeated mistakes?",
        "retain_rejected_hypotheses",
        "behavior",
    ),
    AblationSpec(
        AblationId.A3,
        "retrodiction gate",
        "Does history consistency improve action efficiency?",
        "use_retrodiction_gate",
        "behavior-and-trace",
    ),
    AblationSpec(
        AblationId.A4,
        "world-model simulation",
        "Does internal planning save environment actions?",
        "use_world_model_simulation",
        "behavior-and-runtime",
    ),
    AblationSpec(
        AblationId.A5,
        "goal inference",
        "Is progress coming only from novelty or exploration?",
        "use_goals",
        "behavior-and-trace",
    ),
    AblationSpec(
        AblationId.A6,
        "coordinate salience",
        "Does structured coordinate targeting beat uniform search?",
        "use_coordinate_salience",
        "behavior",
    ),
    AblationSpec(
        AblationId.A7,
        "planner recovery",
        "Does mismatch-triggered replanning matter?",
        "use_planner_recovery",
        "behavior",
    ),
    AblationSpec(
        AblationId.A8,
        "object tracking",
        "Are temporal identities useful beyond raw deltas?",
        "use_object_tracking",
        "behavior-and-trace",
    ),
    AblationSpec(
        AblationId.A9,
        "information-gain term",
        "Does discriminating action choice beat heuristic order?",
        "use_information_gain",
        "behavior",
    ),
    AblationSpec(
        AblationId.A10,
        "trace summaries",
        "Do derived transition summaries help runtime without losing evidence?",
        "use_trace_summaries",
        "runtime-only",
    ),
)
_SPEC_BY_ID = {spec.ablation_id: spec for spec in _SPECS}


def ablation_specs() -> tuple[AblationSpec, ...]:
    """Return the complete ordered A1--A10 protocol matrix."""

    return _SPECS


def ablation_spec(ablation_id: AblationId | str) -> AblationSpec:
    """Resolve one declared identifier without accepting aliases."""

    return _SPEC_BY_ID[AblationId(ablation_id)]


def features_for_ablation(ablation_id: AblationId | str) -> PresetFeatures:
    """Disable exactly one mechanism from the ordinary FULL preset."""

    selected = AblationId(ablation_id)
    full = preset_features(ControllerPreset.FULL)
    if selected is AblationId.A1:
        return replace(full, use_memory=False)
    if selected is AblationId.A2:
        return replace(full, retain_rejected_hypotheses=False)
    if selected is AblationId.A3:
        return replace(full, use_retrodiction_gate=False)
    if selected is AblationId.A4:
        return replace(full, use_world_model_simulation=False)
    if selected is AblationId.A5:
        return replace(full, use_goals=False)
    if selected is AblationId.A6:
        return replace(full, use_coordinate_salience=False)
    if selected is AblationId.A7:
        return replace(full, use_planner_recovery=False)
    if selected is AblationId.A8:
        return replace(full, use_object_tracking=False)
    if selected is AblationId.A9:
        return replace(full, use_information_gain=False)
    return replace(full, use_trace_summaries=False)


__all__ = [
    "AblationId",
    "AblationSpec",
    "ablation_spec",
    "ablation_specs",
    "features_for_ablation",
]
