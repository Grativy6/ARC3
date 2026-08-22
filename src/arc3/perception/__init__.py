"""Measurement-only perception primitives for ARC3 grid observations."""

from arc3.perception.components import (
    BoundingBox,
    Component,
    ComponentConfig,
    GridPoint,
    ShapeInvariance,
    component_signature,
    extract_components,
    infer_background_candidates,
)
from arc3.perception.delta import (
    CellChange,
    CellChangeKind,
    FrameDelta,
    MetadataChange,
    measure_delta,
)
from arc3.perception.frame import NormalizedFrame, NormalizedGrid, normalize_grid
from arc3.perception.palette import (
    MAX_PALETTE_ROLES,
    PALETTE_ROLE_SCHEMA,
    PaletteRoleAssignment,
    PaletteRoleEvidence,
    PaletteRoleRegistry,
)
from arc3.perception.relations import (
    ComponentRelation,
    RelationKind,
    RepetitionGroup,
    component_relations,
    find_repetitions,
)
from arc3.perception.render import render_grid_svg, render_grid_text, summarize_perception
from arc3.perception.salience import (
    ActionEffectEvidence,
    ControllabilityCandidate,
    ControllabilityStatus,
    infer_controllability_candidates,
)
from arc3.perception.tracking import (
    ComponentChange,
    ComponentChangeKind,
    Correspondence,
    CorrespondenceAlternative,
    GlobalShift,
    TrackingResult,
    detect_global_shift,
    track_components,
)

__all__ = [
    "MAX_PALETTE_ROLES",
    "PALETTE_ROLE_SCHEMA",
    "ActionEffectEvidence",
    "BoundingBox",
    "CellChange",
    "CellChangeKind",
    "Component",
    "ComponentChange",
    "ComponentChangeKind",
    "ComponentConfig",
    "ComponentRelation",
    "ControllabilityCandidate",
    "ControllabilityStatus",
    "Correspondence",
    "CorrespondenceAlternative",
    "FrameDelta",
    "GlobalShift",
    "GridPoint",
    "MetadataChange",
    "NormalizedFrame",
    "NormalizedGrid",
    "PaletteRoleAssignment",
    "PaletteRoleEvidence",
    "PaletteRoleRegistry",
    "RelationKind",
    "RepetitionGroup",
    "ShapeInvariance",
    "TrackingResult",
    "component_relations",
    "component_signature",
    "detect_global_shift",
    "extract_components",
    "find_repetitions",
    "infer_background_candidates",
    "infer_controllability_candidates",
    "measure_delta",
    "normalize_grid",
    "render_grid_svg",
    "render_grid_text",
    "summarize_perception",
    "track_components",
]
