"""Generic visual causal discovery for bounded coordinate-action games.

The policy in this module is deliberately identity-blind.  It discovers compact
objects, tests whether a coordinate action places one of them, estimates a
factored affine consequence, and then uses only target-relative, bounded
candidate points.  It contains no public-game identifiers, fixed layouts, or
walkthrough action sequences.
"""

from __future__ import annotations

import hashlib
import heapq
import itertools
import math
from collections import Counter, deque
from dataclasses import dataclass, replace
from enum import StrEnum

from arc3.adapters import GridFrame, Observation
from arc3.errors import PolicyError
from arc3.exploration.causal_events import (
    CausalActionReceipt,
    EffectChannel,
    EffectKnowledge,
    EffectVector,
    FactoredEffect,
    ResourceFailureRisk,
    RiskLevel,
    compare_effect_vectors,
    extract_observed_effects,
)
from arc3.exploration.causal_events import (
    ResidualKind as CausalResidualKind,
)
from arc3.mechanics.learner import (
    LearningReceipt,
    MechanicalLearner,
    MechanicPredictionReceipt,
)
from arc3.mechanics.models import (
    ChannelValue,
    CompositionMode,
    ConsequenceChannel,
    ConsequenceVector,
    EvidenceProvenance,
    LegalActionEffect,
    MechanicContext,
    MechanicRef,
    MechanicScope,
    MechanicStatus,
    ObjectEffect,
    ObjectOperation,
    ScopeCeiling,
    ScoreProgressEffect,
    TerminalEffect,
)
from arc3.perception.delta import measure_delta
from arc3.perception.layers import ResidualDisposition
from arc3.perception.metadata import observation_metadata
from arc3.types import ActionName, ActionRequest, Coordinate, GameStateName, JSONValue


class VisualObjectRole(StrEnum):
    """Conservative shape roles; roles are descriptive, not mechanics."""

    ENDPOINT_CANDIDATE = "endpoint-candidate"
    MEDIATOR_CANDIDATE = "mediator-candidate"
    HOLLOW_TARGET_CANDIDATE = "hollow-target-candidate"
    OTHER = "other"


class VisualActionPurpose(StrEnum):
    """Pre-action reason used by the mechanical campaign."""

    PROGRESS = "PROGRESS"
    PROBE = "PROBE"
    MANDATORY_RESET = "MANDATORY_RESET"
    FALLBACK = "FALLBACK"


@dataclass(frozen=True, slots=True)
class VisualObject:
    """One eight-connected, single-color component."""

    object_ref: str
    color: int
    cells: tuple[tuple[int, int], ...]
    min_x: int
    min_y: int
    max_x: int
    max_y: int
    center_x: float
    center_y: float
    center_cell: int
    touches_edge: bool
    role: VisualObjectRole

    @property
    def area(self) -> int:
        return len(self.cells)

    @property
    def width(self) -> int:
        return self.max_x - self.min_x + 1

    @property
    def height(self) -> int:
        return self.max_y - self.min_y + 1

    @property
    def rounded_center(self) -> tuple[int, int]:
        return (round(self.center_x), round(self.center_y))

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "area": self.area,
            "bbox": [self.min_x, self.min_y, self.max_x, self.max_y],
            "center": [self.center_x, self.center_y],
            "color": self.color,
            "object_ref": self.object_ref,
            "role": self.role.value,
            "touches_edge": self.touches_edge,
        }


@dataclass(frozen=True, slots=True)
class VisualScene:
    """Bounded component projection of one frame."""

    frame_hash: str
    width: int
    height: int
    background: int
    objects: tuple[VisualObject, ...]
    cells: tuple[tuple[int, ...], ...]

    @property
    def endpoints(self) -> tuple[VisualObject, ...]:
        return tuple(
            item for item in self.objects if item.role is VisualObjectRole.ENDPOINT_CANDIDATE
        )

    @property
    def mediators(self) -> tuple[VisualObject, ...]:
        return tuple(
            item for item in self.objects if item.role is VisualObjectRole.MEDIATOR_CANDIDATE
        )

    @property
    def targets(self) -> tuple[VisualObject, ...]:
        return tuple(
            item for item in self.objects if item.role is VisualObjectRole.HOLLOW_TARGET_CANDIDATE
        )

    def is_open(self, x: int, y: int, *, radius: int = 2) -> bool:
        """Return whether a small readable neighborhood is mostly background."""

        if not (radius < x < self.width - radius - 1 and radius < y < self.height - radius - 1):
            return False
        values = [
            self.cells[yy][xx]
            for yy in range(y - radius, y + radius + 1)
            for xx in range(x - radius, x + radius + 1)
        ]
        return sum(value == self.background for value in values) / len(values) >= 0.72

    def to_dict(self) -> dict[str, JSONValue]:
        counts = Counter(item.role.value for item in self.objects)
        return {
            "background": self.background,
            "frame_hash": self.frame_hash,
            "height": self.height,
            "object_counts": dict(sorted(counts.items())),
            "width": self.width,
        }


type _TargetRegions = tuple[tuple[tuple[int, int], frozenset[tuple[int, int]]], ...]
type _TargetSurfaceSignature = tuple[
    tuple[
        str,
        tuple[int, int],
        tuple[tuple[int, int], ...],
        tuple[tuple[int, int, int], ...],
    ],
    ...,
]
type _VisualObjectStateSignature = tuple[
    tuple[int, int],
    int,
    int,
    tuple[tuple[int, int], ...],
]
type _EndpointStateSignature = tuple[_VisualObjectStateSignature, ...]
type _ConnectorStateSignature = tuple[int, tuple[tuple[int, int], ...]] | None
type _NormalizedConnectorStructure = tuple[int, int] | None
type _RasterStateSignature = tuple[tuple[int, int, int], ...]
type _ExplorationRootKey = tuple[str, str, int, int]
type _BridgeProjectedStateKey = tuple[
    tuple[tuple[str, tuple[int, int]], ...],
    tuple[tuple[str, int], ...],
]
type _CompositeCargoSourceKey = tuple[int, int]
type _SameChildCompositeCargoProjectedStateKey = tuple[
    tuple[tuple[str, tuple[int, int]], ...],
    tuple[tuple[str, int], ...],
    tuple[_CompositeCargoSourceKey, ...],
]
type _ChildStructureSignature = tuple[
    int,
    int,
    int,
    tuple[tuple[int, int], ...],
    tuple[tuple[int, tuple[tuple[int, int], ...]], ...],
    _NormalizedConnectorStructure,
]


@dataclass(frozen=True, slots=True)
class AffineMechanic:
    """Observed placement-plus-mediator relation for one visual scope."""

    mechanic_ref: str
    level_index: int
    active_color: int
    mediator_color: int
    arity: int
    source_before_hash: str
    source_after_hash: str
    support_error: float
    anchor_centers: tuple[tuple[int, int], ...]
    target_center: tuple[int, int]

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "active_color": self.active_color,
            "anchor_centers": [list(item) for item in self.anchor_centers],
            "arity": self.arity,
            "level_index": self.level_index,
            "mechanic_ref": self.mechanic_ref,
            "mediator_color": self.mediator_color,
            "source_after_hash": self.source_after_hash,
            "source_before_hash": self.source_before_hash,
            "support_error": self.support_error,
            "target_center": list(self.target_center),
        }


@dataclass(frozen=True, slots=True)
class _PostDepositMediatorAccessCertificate:
    """Exact observation and resource boundary for one mediator-access probe."""

    hypothesis_key: str
    mediator_signature: _VisualObjectStateSignature
    protected_raster_hash: str
    visible_endpoint_count: int
    resource_action_count: int
    exhausted_after_actions: int


@dataclass(frozen=True, slots=True)
class _PostAccessCompositeExitCertificate:
    """Exact transition lineage for one post-access composite discriminator."""

    hypothesis_key: str
    parent_access_hypothesis_key: str
    common_center: tuple[int, int]
    mediator_signature: _VisualObjectStateSignature
    target_signature: _VisualObjectStateSignature
    protected_raster_hash: str
    parent_protected_raster_hash: str
    visible_endpoint_count: int
    parent_visible_endpoint_count: int
    resource_action_count: int
    exhausted_after_actions: int


@dataclass(frozen=True, slots=True)
class _PostAccessCompositeMarkerCertificate:
    """Exact no-op and resource lineage for one embedded-marker discriminator."""

    hypothesis_key: str
    parent_access_hypothesis_key: str
    parent_composite_hypothesis_key: str
    common_center: tuple[int, int]
    marker_coordinate: tuple[int, int]
    marker_color: int
    mediator_signature: _VisualObjectStateSignature
    target_signature: _VisualObjectStateSignature
    endpoint_signature: _EndpointStateSignature
    protected_raster_hash: str
    parent_protected_raster_hash: str
    parent_resource_action_count: int
    resource_action_count: int
    exhausted_after_actions: int


@dataclass(frozen=True, slots=True)
class _SameChildCompositeCargoCertificate:
    """Exact per-action lineage for one complementary-source accumulation route."""

    relation_key: str
    child_index: int
    stage_index: int
    support_center: tuple[int, int]
    target_center: tuple[int, int]
    source_keys: tuple[_CompositeCargoSourceKey, ...]
    endpoint_marker_color: int
    required_collected_source_keys: tuple[_CompositeCargoSourceKey, ...]
    expected_collected_source_keys: tuple[_CompositeCargoSourceKey, ...]
    required_mediator_center: tuple[int, int]
    expected_mediator_center: tuple[int, int]
    required_visible_endpoint_count: int
    required_visible_mediator_count: int
    required_visible_active_endpoint_count: int
    expected_visible_active_endpoint_count: int
    completes_relation: bool


@dataclass(frozen=True, slots=True)
class PlannedClick:
    """One bounded action in a causally justified local plan."""

    coordinate: Coordinate
    purpose: VisualActionPurpose
    expectation: str
    mechanic_ref: str
    plan_id: str
    plan_signature: str
    target_center: tuple[int, int]
    mediator_color: int
    arity: int
    completes_local_target: bool = False
    completes_hierarchy: bool = False
    completes_child_isolation: bool = False
    completes_child_recovery: bool = False
    stages_for_switch: bool = False
    expected_child_mediator_center: tuple[int, int] | None = None
    expected_child_mediator_signature: _VisualObjectStateSignature | None = None
    expected_child_endpoint_centers: tuple[tuple[int, int], ...] = ()
    expected_child_endpoint_signature: _EndpointStateSignature = ()
    expected_child_connector_signature: _ConnectorStateSignature = None
    expected_active_center: tuple[int, int] | None = None
    required_child_protected_raster_hash: str | None = None
    expected_child_protected_raster_hash: str | None = None
    required_visible_active_endpoint_count: int | None = None
    required_child_raster_signature: _RasterStateSignature = ()
    expected_child_raster_signature: _RasterStateSignature = ()
    expected_occluded_endpoint_centers: tuple[tuple[int, int], ...] = ()
    expected_occluded_endpoint_cells: tuple[tuple[int, int], ...] = ()
    expected_visible_endpoint_count: int | None = None
    expected_visible_mediator_count: int | None = None
    carrier_source_recovery_alternative: PlannedClick | None = None
    carrier_source_recovery_candidates: tuple[PlannedClick, ...] = ()
    required_carried_source_support_indexes: tuple[int, ...] = ()
    expected_carried_source_support_indexes: tuple[int, ...] = ()
    carrier_source_delivery_actions: tuple[PlannedClick, ...] = ()
    carrier_source_delivery_step: bool = False
    completes_carrier_source_delivery: bool = False
    carrier_source_detachment_probe: PlannedClick | None = None
    carrier_source_detachment_step: bool = False
    carrier_source_target_center_role_exchange_step: bool = False
    carrier_source_attachment_continuation_actions: tuple[PlannedClick, ...] = ()
    carrier_source_untouched_role_exchange_step: bool = False
    carrier_source_untouched_discriminator_step: bool = False
    carrier_source_untouched_restoration_actions: tuple[PlannedClick, ...] = ()
    carrier_source_untouched_restoration_step: bool = False
    completes_carrier_source_untouched_restoration: bool = False
    carrier_source_paired_cargo_step: bool = False
    completes_carrier_source_paired_cargo: bool = False
    carrier_source_paired_cargo_initial_protected_raster_hash: str | None = None
    carrier_source_paired_cargo_restoration_actions: tuple[PlannedClick, ...] = ()
    carrier_source_paired_cargo_restoration_step: bool = False
    completes_carrier_source_paired_cargo_restoration: bool = False
    carrier_source_paired_cargo_role_handoff_family: bool = False
    carrier_source_paired_cargo_role_handoff: PlannedClick | None = None
    carrier_source_paired_cargo_role_handoff_step: bool = False
    carrier_source_paired_cargo_role_restoration_actions: tuple[PlannedClick, ...] = ()
    carrier_source_paired_cargo_role_restoration_step: bool = False
    carrier_source_paired_cargo_crossed_predecessor_family: bool = False
    carrier_source_paired_cargo_crossed_predecessor_actions: tuple[PlannedClick, ...] = ()
    carrier_source_paired_cargo_crossed_predecessor_step: bool = False
    completes_carrier_source_paired_cargo_crossed_predecessor: bool = False
    carrier_source_paired_cargo_crossed_delivery_step: bool = False
    completes_carrier_source_paired_cargo_crossed_delivery: bool = False
    post_deposit_mediator_access_certificate: _PostDepositMediatorAccessCertificate | None = None
    post_access_composite_exit_certificate: _PostAccessCompositeExitCertificate | None = None
    post_access_composite_marker_certificate: _PostAccessCompositeMarkerCertificate | None = None
    same_child_composite_cargo_certificate: _SameChildCompositeCargoCertificate | None = None
    expected_deposited_source_protected_raster_hash: str | None = None
    expected_deposited_visible_endpoint_count: int | None = None
    expected_deposited_visible_mediator_count: int | None = None


@dataclass(frozen=True, slots=True)
class _AffineChildGroup:
    """One uniquely assigned lower-layer affine relation."""

    mediator: VisualObject
    endpoints: tuple[VisualObject, ...]

    @property
    def arity(self) -> int:
        return len(self.endpoints)


@dataclass(frozen=True, slots=True)
class _AffineHierarchy:
    """A bounded candidate relation from child mediators to one parent target."""

    target: VisualObject
    children: tuple[_AffineChildGroup, ...]
    active_color: int
    mechanic_ref: str


@dataclass(frozen=True, slots=True)
class _HierarchyChildLayout:
    """One child group's final endpoint geometry around a distinct support."""

    group: _AffineChildGroup
    support: tuple[int, int]
    movers: tuple[VisualObject, ...]
    points: tuple[tuple[int, int], ...]
    dynamic_footprint: frozenset[tuple[int, int]]
    radius: int
    movement_cost: float


@dataclass(frozen=True, slots=True)
class _HierarchyPlan:
    """One fully preflighted, finite two-layer affine intervention."""

    actions: tuple[PlannedClick, ...]
    signature: str
    supports: tuple[tuple[int, int], ...]
    support_weights: tuple[int, ...]
    recovery_actions: tuple[PlannedClick, ...]
    carrier_source_attachment_replay_context: _CarrierSourceAttachmentReplayContext | None = None
    carrier_source_crossed_delivery_replay_context: (
        _CarrierSourceCrossedDeliveryReplayContext | None
    ) = None


@dataclass(frozen=True, slots=True)
class _CompositeFilledDisk:
    """One exact isolated 21-cell two-color disk read from the observation."""

    center: tuple[int, int]
    cells: tuple[tuple[int, int], ...]
    palette: frozenset[int]
    offsets_by_color: tuple[tuple[int, frozenset[tuple[int, int]]], ...]

    def offsets(self, color: int) -> frozenset[tuple[int, int]]:
        return next(
            (cells for value, cells in self.offsets_by_color if value == color), frozenset()
        )


@dataclass(frozen=True, slots=True)
class _CompositeBridgeExample:
    """Carrier-sharing disks and their exact residual-color ring."""

    carrier_color: int
    sources: tuple[_CompositeFilledDisk, ...]
    residual_colors: tuple[int, ...]
    target: VisualObject

    @property
    def aggregate_center_twice(self) -> tuple[int, int]:
        return (
            self.sources[0].center[0] + self.sources[1].center[0],
            self.sources[0].center[1] + self.sources[1].center[1],
        )


@dataclass(frozen=True, slots=True)
class _CompositeBridgeRelation:
    """A provisional proximity-assigned paired-sink intervention hypothesis."""

    assignments: tuple[tuple[_AffineChildGroup, _CompositeBridgeExample], ...]
    relation_key: str


@dataclass(frozen=True, slots=True)
class _HierarchyTargetSupport:
    """One child-to-target support derived from an observed bridge example."""

    child: _AffineChildGroup
    example: _CompositeBridgeExample
    target: VisualObject
    surface_signature: frozenset[int]


@dataclass(frozen=True, slots=True)
class _ResidualLinkedHierarchyRelation:
    """A unique residual-color link from one bridge child to the raw parent."""

    bridge_relation_key: str
    supports: tuple[_HierarchyTargetSupport, ...]
    relation_key: str


@dataclass(frozen=True, slots=True)
class _ExternalResidualLinkedHierarchyRelation:
    """A unique carrier-mask lineage from the raw target to one external surface."""

    bridge_relation_key: str
    mixed_relation_key: str
    supports: tuple[_HierarchyTargetSupport, ...]
    raw_source_center: tuple[int, int]
    counterpart_source_center: tuple[int, int]
    raw_color: int
    external_link_color: int
    carrier_offsets: frozenset[tuple[int, int]]
    relation_key: str


@dataclass(frozen=True, slots=True)
class _RawMatchingCompositeHierarchyRelation:
    """Retain the raw link and revise its counterpart to one containing sink."""

    bridge_relation_key: str
    mixed_relation_key: str
    external_relation_key: str
    supports: tuple[_HierarchyTargetSupport, ...]
    relation_key: str


@dataclass(frozen=True, slots=True)
class _ExternalOwnCompositeHierarchyRelation:
    """Use the external counterpart sink and the raw child's own bridge sink."""

    bridge_relation_key: str
    mixed_relation_key: str
    external_relation_key: str
    raw_matching_relation_key: str
    supports: tuple[_HierarchyTargetSupport, ...]
    relation_key: str


@dataclass(frozen=True, slots=True)
class _HierarchySourceSupport:
    """One child-to-filled-source support derived from a carrier-mask witness."""

    child: _AffineChildGroup
    example: _CompositeBridgeExample
    source: _CompositeFilledDisk


@dataclass(frozen=True, slots=True)
class _CarrierSourceOcclusionHierarchyRelation:
    """Map each child to its uniquely witnessed carrier-matched source disk."""

    bridge_relation_key: str
    mixed_relation_key: str
    external_relation_key: str
    raw_matching_relation_key: str
    external_own_relation_key: str
    supports: tuple[_HierarchySourceSupport, ...]
    relation_key: str


@dataclass(frozen=True, slots=True)
class _CarrierSourceAttachmentReplayContext:
    """Finite observed lineage needed to derive one post-restoration continuation."""

    hierarchy: _AffineHierarchy
    layouts: tuple[_HierarchyChildLayout, ...]
    scene: VisualScene
    move_order: tuple[str, ...] | None
    support_weights: tuple[int, ...] | None
    carrier_source_supports: tuple[_HierarchySourceSupport, ...]
    level_index: int
    rejected_external_residual_relation_key: str
    signature_prefix: str
    terminal_expectation: str


@dataclass(frozen=True, slots=True)
class _CarrierSourceCrossedDeliveryReplayContext:
    """Exact crossed endpoint state retained until its returned raster is observed."""

    attachment_context: _CarrierSourceAttachmentReplayContext
    carried_indexes: tuple[int, ...]
    positions: tuple[tuple[str, tuple[int, int]], ...]
    colors: tuple[tuple[str, int], ...]
    protected_raster_hash: str
    visible_endpoint_count: int
    visible_mediator_count: int
    delivery_plan_signature: str
    delivery_action_count: int


@dataclass(frozen=True, slots=True)
class _EdgeResourceProgress:
    """One observation-derived monotone border-fill candidate."""

    edge_index: int
    baseline: tuple[int, ...]
    fill_color: int
    filled_indexes: frozenset[int]
    filled_index_history: tuple[frozenset[int], ...]
    observed_actions: int


@dataclass(frozen=True, slots=True)
class _ResourceInterruptedPairedReplay:
    """Minimal semantic key authorizing one fresh-life crossed continuation."""

    level_index: int
    context_key: str
    setup_relation_key: str
    setup_plan_signature: str
    setup_action_count: int
    crossed_forward_action_count: int
    exhausted_edge_index: int
    exhausted_edge_baseline: tuple[int, ...]
    exhausted_edge_fill_color: int
    exhausted_filled_index_history: tuple[frozenset[int], ...]
    observed_actions: int
    authorized_reset_epoch: int
    setup_replay_started: bool = False


@dataclass(frozen=True, slots=True)
class _PostMarkerResourceResetBridge:
    """Exact no-op resource bridge authorizing one fresh reset epoch."""

    level_index: int
    marker_hypothesis_key: str
    no_op_coordinate: Coordinate
    protected_raster_hash: str
    edge_index: int
    edge_baseline: tuple[int, ...]
    edge_fill_color: int
    exhausted_filled_index_history: tuple[frozenset[int], ...]
    armed_after_actions: int
    exhausted_after_actions: int
    authorized_reset_epoch: int
    game_over_observed: bool = False


@dataclass(frozen=True, slots=True)
class _ActiveCrossedReplayResourceLineage:
    """Consumed fresh-life authorization retained through forward and inverse play."""

    level_index: int
    context_key: str
    edge_index: int
    edge_baseline: tuple[int, ...]
    edge_fill_color: int
    exhausted_filled_index_history: tuple[frozenset[int], ...]
    exhausted_after_actions: int
    reset_epoch: int
    forward_remaining_actions: int


@dataclass(frozen=True, slots=True)
class _HierarchyRasterCertificate:
    """Exact observation-derived board identity for one hierarchy action boundary."""

    protected_raster_hash: str
    visible_endpoint_count: int
    visible_mediator_count: int


@dataclass(frozen=True, slots=True)
class _ChildIsolationPlan:
    """One exact test of a previously untouched child against the parent target."""

    actions: tuple[PlannedClick, ...]
    signature: str
    relation_key: str
    hypothesis_key: str
    frozen_mediator_center: tuple[int, int]
    frozen_mediator_signature: _VisualObjectStateSignature
    frozen_endpoint_centers: tuple[tuple[int, int], ...]
    frozen_endpoint_signature: _EndpointStateSignature
    frozen_connector_signature: _ConnectorStateSignature
    frozen_mediator_color: int
    target_signature: _TargetSurfaceSignature
    recovery_actions: tuple[PlannedClick, ...]


@dataclass(frozen=True, slots=True)
class _ChildIsolationStateCertificate:
    """Exact projected state expected after one child-isolation action."""

    selected_mediator_signature: _VisualObjectStateSignature
    selected_endpoint_signature: _EndpointStateSignature
    selected_connector_signature: _ConnectorStateSignature
    frozen_connector_signature: _ConnectorStateSignature
    active_center: tuple[int, int]
    protected_raster_hash: str
    selected_raster_signature: _RasterStateSignature
    occluded_endpoint_centers: tuple[tuple[int, int], ...]
    occluded_endpoint_cells: tuple[tuple[int, int], ...]
    visible_endpoint_count: int
    visible_mediator_count: int


@dataclass(frozen=True, slots=True)
class _ChildIsolationRestoreCertificate:
    """Exact pre-discriminator state required after a bounded inverse replay."""

    protected_raster_hash: str
    relation_raster_signature: _RasterStateSignature
    visible_endpoint_count: int
    visible_mediator_count: int
    active_center: tuple[int, int]


@dataclass(frozen=True, slots=True)
class _EmbeddedMarkerGroup:
    """One observation-grounded affine group keyed by an endpoint marker."""

    marker_color: int
    endpoints: tuple[VisualObject, ...]
    mediator: VisualObject
    target: VisualObject

    @property
    def arity(self) -> int:
        return len(self.endpoints)

    @property
    def is_composite(self) -> bool:
        """Whether this group was assembled from a multicolor observed glyph."""

        return self.mediator.object_ref.startswith("visual-composite-mediator:")


@dataclass(frozen=True, slots=True)
class VisualActionReceipt:
    """Compact prediction/consequence receipt retained by the policy."""

    receipt_id: str
    level_index: int
    before_frame_hash: str
    after_frame_hash: str
    action: ActionRequest
    purpose: VisualActionPurpose
    prediction: str
    observed: str
    residual: str | None
    source_mechanic_refs: tuple[str, ...]
    before_state: GameStateName
    after_state: GameStateName
    levels_before: int
    levels_after: int
    changed_cells: int
    causal_action_receipt: CausalActionReceipt
    mechanic_prediction_receipt: MechanicPredictionReceipt
    mechanic_learning_receipt: LearningReceipt

    def to_dict(self) -> dict[str, JSONValue]:
        coordinate = self.action.coordinate
        return {
            "action": {
                "coordinate": (
                    {"x": coordinate.x, "y": coordinate.y} if coordinate is not None else None
                ),
                "name": self.action.name.value,
            },
            "after_frame_hash": self.after_frame_hash,
            "after_state": self.after_state.value,
            "before_frame_hash": self.before_frame_hash,
            "before_state": self.before_state.value,
            "changed_cells": self.changed_cells,
            "causal_action_receipt": self.causal_action_receipt.to_dict(),
            "level_index": self.level_index,
            "levels_after": self.levels_after,
            "levels_before": self.levels_before,
            "mechanic_learning_receipt": self.mechanic_learning_receipt.to_dict(),
            "mechanic_prediction_receipt": self.mechanic_prediction_receipt.to_dict(),
            "observed": self.observed,
            "prediction": self.prediction,
            "purpose": self.purpose.value,
            "receipt_id": self.receipt_id,
            "residual": self.residual,
            "source_mechanic_refs": list(self.source_mechanic_refs),
        }


def _object_ref(color: int, cells: tuple[tuple[int, int], ...]) -> str:
    payload = f"{color}:" + ";".join(f"{x},{y}" for x, y in cells)
    return "visual:" + hashlib.sha256(payload.encode("ascii")).hexdigest()[:20]


def _role_for(
    *,
    area: int,
    width: int,
    height: int,
    color: int,
    center_cell: int,
    background: int,
    touches_edge: bool,
) -> VisualObjectRole:
    if touches_edge or not (5 <= width <= 9 and 5 <= height <= 9):
        return VisualObjectRole.OTHER
    density = area / (width * height)
    sparse_hollow_geometry = center_cell != color and density <= 0.30
    if 7 <= area <= 24 and (center_cell == background or sparse_hollow_geometry):
        return VisualObjectRole.HOLLOW_TARGET_CANDIDATE
    if 8 <= area <= 18 and max(width, height) <= 7 and density >= 0.35:
        return VisualObjectRole.ENDPOINT_CANDIDATE
    if 15 <= area <= 30 and center_cell != background:
        return VisualObjectRole.MEDIATOR_CANDIDATE
    return VisualObjectRole.OTHER


_SMALL_COMPONENT_FRAGMENT_AREA = 12
_SMALL_COMPONENT_COMBINED_AREA = 24
_SMALL_COMPONENT_MAX_SPAN = 9
_SMALL_COMPONENT_MERGE_DISTANCE = 3
_MAX_HIERARCHY_CHILD_LAYOUTS = 8
_MAX_HIERARCHY_LAYOUT_COMBINATIONS = 512
_MAX_HIERARCHY_SEARCH_BUDGET = 131_072
_HIERARCHY_SEQUENCE_EVALUATION_COST = 1_024
_HIERARCHY_TRANSIENT_SEQUENCE_EVALUATION_COST = 32
_MAX_WEIGHTED_HIERARCHY_MOVE_ORDERS = 22
_WEIGHTED_HIERARCHY_SUPPORT_LOOKAHEAD = 1
_MAX_SAME_CHILD_COMPOSITE_CARGO_ROUTES = 8
_MAX_SAME_CHILD_COMPOSITE_CARGO_PATTERNS = 8
_MAX_SAME_CHILD_COMPOSITE_CARGO_REORIENTED_PATTERNS = 64
_HIERARCHY_PLAN_PREFIXES = (
    "affine-hierarchy:",
    "affine-hierarchy-recovery:",
    "affine-weighted-hierarchy:",
    "affine-weighted-hierarchy-recovery:",
    "affine-visible-node-hierarchy:",
    "affine-visible-node-hierarchy-recovery:",
    "affine-bridge-hierarchy:",
    "affine-bridge-hierarchy-recovery:",
    "affine-residual-linked-hierarchy:",
    "affine-residual-linked-hierarchy-recovery:",
    "affine-external-residual-linked-hierarchy:",
    "affine-external-residual-linked-hierarchy-recovery:",
    "affine-raw-matching-composite-hierarchy:",
    "affine-raw-matching-composite-hierarchy-recovery:",
    "affine-external-own-composite-hierarchy:",
    "affine-external-own-composite-hierarchy-recovery:",
    "affine-carrier-source-occlusion-hierarchy:",
    "affine-carrier-source-occlusion-hierarchy-recovery:",
    "affine-crossed-post-deposit-mediator-access:",
    "affine-crossed-post-access-composite-exit:",
    "affine-crossed-post-access-composite-marker:",
    "affine-same-child-composite-cargo:",
    "affine-child-isolation:",
    "affine-child-recovery:",
)
_CARRIER_SOURCE_MASKED_PLAN_PREFIXES = (
    "affine-carrier-source-occlusion-hierarchy:",
    "affine-carrier-source-occlusion-hierarchy-recovery:",
)


class _HierarchySearchExhausted(PolicyError):
    """The deterministic hierarchy ceiling was reached without an action."""


@dataclass(slots=True)
class _HierarchySearchBudget:
    """One global deterministic ceiling for a hierarchy search."""

    remaining: int

    def consume(self, cost: int = 1) -> None:
        if cost < 1:
            raise ValueError("hierarchy search cost must be positive")
        if cost > self.remaining:
            self.remaining = 0
            raise _HierarchySearchExhausted(
                "affine hierarchy deterministic search budget exhausted"
            )
        self.remaining -= cost


def _small_components_would_merge(
    left_cells: tuple[tuple[int, int], ...],
    right_cells: tuple[tuple[int, int], ...],
) -> bool:
    """Apply the exact bounded relation used by perception's fragment merge."""

    if (
        len(left_cells) > _SMALL_COMPONENT_FRAGMENT_AREA
        or len(right_cells) > _SMALL_COMPONENT_FRAGMENT_AREA
    ):
        return False
    combined = tuple(sorted({*left_cells, *right_cells}, key=lambda item: (item[1], item[0])))
    if len(combined) > _SMALL_COMPONENT_COMBINED_AREA:
        return False
    xs = [item[0] for item in combined]
    ys = [item[1] for item in combined]
    if (
        max(xs) - min(xs) + 1 > _SMALL_COMPONENT_MAX_SPAN
        or max(ys) - min(ys) + 1 > _SMALL_COMPONENT_MAX_SPAN
    ):
        return False
    separation = min(
        max(abs(lx - rx), abs(ly - ry)) for lx, ly in left_cells for rx, ry in right_cells
    )
    return separation <= _SMALL_COMPONENT_MERGE_DISTANCE


def _marker_center_would_merge_with_target(
    scene: VisualScene,
    group: _EmbeddedMarkerGroup,
    endpoint: VisualObject,
    *,
    center: tuple[int, int],
) -> bool:
    """Apply the parser's bounded merge rule to a prospective marker center."""

    residual_target = tuple(
        cell
        for cell in group.target.cells
        if cell != endpoint.rounded_center and scene.cells[cell[1]][cell[0]] == group.marker_color
    )
    return bool(residual_target and _small_components_would_merge((center,), residual_target))


def _marker_target_identity_constraint(marker_color: int) -> str:
    return f"marker:{marker_color}:preserve-target-identity"


def _merge_small_same_color_groups(
    groups: list[tuple[int, tuple[tuple[int, int], ...]]],
) -> list[tuple[int, tuple[tuple[int, int], ...]]]:
    """Join sparse nearby fragments into one bounded compound shape.

    Hollow rings in the official renderer can be split into four diagonal
    fragments under eight-connectivity.  The merge is limited to a 9x9 window
    and 24 cells, so it cannot absorb a route, border, or large object.
    """

    working = list(groups)
    changed = True
    while changed:
        changed = False
        for left_index, (left_color, left_cells) in enumerate(working):
            if len(left_cells) > _SMALL_COMPONENT_FRAGMENT_AREA:
                continue
            for right_index in range(left_index + 1, len(working)):
                right_color, right_cells = working[right_index]
                if right_color != left_color:
                    continue
                if not _small_components_would_merge(left_cells, right_cells):
                    continue
                combined = tuple(
                    sorted({*left_cells, *right_cells}, key=lambda item: (item[1], item[0]))
                )
                working[left_index] = (left_color, combined)
                working.pop(right_index)
                changed = True
                break
            if changed:
                break
    return working


def extract_visual_scene(frame: GridFrame) -> VisualScene:
    """Extract small eight-connected objects without assigning causal meaning."""

    background = Counter(value for row in frame.cells for value in row).most_common(1)[0][0]
    remaining = {
        (x, y)
        for y, row in enumerate(frame.cells)
        for x, value in enumerate(row)
        if value != background
    }
    groups: list[tuple[int, tuple[tuple[int, int], ...]]] = []
    while remaining:
        start = min(remaining, key=lambda item: (item[1], item[0]))
        remaining.remove(start)
        color = frame.cells[start[1]][start[0]]
        queue: deque[tuple[int, int]] = deque((start,))
        component_cells: list[tuple[int, int]] = [start]
        while queue:
            x, y = queue.popleft()
            for yy in range(max(0, y - 1), min(frame.height, y + 2)):
                for xx in range(max(0, x - 1), min(frame.width, x + 2)):
                    candidate = (xx, yy)
                    if candidate in remaining and frame.cells[yy][xx] == color:
                        remaining.remove(candidate)
                        queue.append(candidate)
                        component_cells.append(candidate)
        groups.append((color, tuple(sorted(component_cells, key=lambda item: (item[1], item[0])))))

    groups = _merge_small_same_color_groups(groups)
    objects: list[VisualObject] = []
    for color, cells in groups:
        xs = [item[0] for item in cells]
        ys = [item[1] for item in cells]
        min_x, max_x = min(xs), max(xs)
        min_y, max_y = min(ys), max(ys)
        box_center_x = (min_x + max_x) / 2
        box_center_y = (min_y + max_y) / 2
        center_x = round(box_center_x)
        center_y = round(box_center_y)
        touches_edge = (
            min_x == 0 or min_y == 0 or max_x == frame.width - 1 or max_y == frame.height - 1
        )
        role = _role_for(
            area=len(cells),
            width=max_x - min_x + 1,
            height=max_y - min_y + 1,
            color=color,
            center_cell=frame.cells[center_y][center_x],
            background=background,
            touches_edge=touches_edge,
        )
        objects.append(
            VisualObject(
                object_ref=_object_ref(color, cells),
                color=color,
                cells=cells,
                min_x=min_x,
                min_y=min_y,
                max_x=max_x,
                max_y=max_y,
                center_x=box_center_x,
                center_y=box_center_y,
                center_cell=frame.cells[center_y][center_x],
                touches_edge=touches_edge,
                role=role,
            )
        )
    return VisualScene(
        frame_hash=str(frame.digest),
        width=frame.width,
        height=frame.height,
        background=background,
        objects=tuple(sorted(objects, key=lambda item: item.object_ref)),
        cells=frame.cells,
    )


def _distance(left: tuple[float, float], right: tuple[float, float]) -> float:
    return math.hypot(left[0] - right[0], left[1] - right[1])


def _changed_cells(before: GridFrame, after: GridFrame) -> int:
    if before.width != after.width or before.height != after.height:
        return before.width * before.height + after.width * after.height
    return sum(
        before.cells[y][x] != after.cells[y][x]
        for y in range(before.height)
        for x in range(before.width)
    )


def _affine_target_candidates(
    scene: VisualScene,
    *,
    mediator_color: int,
) -> tuple[VisualObject, ...]:
    """Return the narrowest readable target role for an affine mediator.

    Same-color identity remains the primary relation.  When that relation is
    absent, one and only one readable hollow target can carry the role without
    inventing a palette mapping.  Multiple mismatched targets stay ambiguous.
    """

    same_color = tuple(item for item in scene.targets if item.color == mediator_color)
    if same_color:
        return same_color
    if len(scene.targets) == 1:
        return scene.targets
    return ()


def infer_affine_mechanic(
    before: VisualScene,
    after: VisualScene,
    *,
    level_index: int,
    action: ActionRequest,
) -> AffineMechanic | None:
    """Infer a placement/mediator receipt from one discriminating action.

    A single transition can open only a provisional mechanic.  The returned
    support error stays explicit so callers can require passive confirmation.
    """

    if action.name is not ActionName.ACTION6 or action.coordinate is None:
        return None
    clicked = (float(action.coordinate.x), float(action.coordinate.y))
    active_after = min(
        after.endpoints,
        key=lambda item: _distance((item.center_x, item.center_y), clicked),
        default=None,
    )
    if (
        active_after is None
        or _distance((active_after.center_x, active_after.center_y), clicked) > 2.25
    ):
        return None
    before_same_color = tuple(item for item in before.endpoints if item.color == active_after.color)
    if not before_same_color:
        return None
    active_before = max(
        before_same_color,
        key=lambda item: _distance(
            (item.center_x, item.center_y),
            (active_after.center_x, active_after.center_y),
        ),
    )
    delta_active = (
        active_after.center_x - active_before.center_x,
        active_after.center_y - active_before.center_y,
    )
    if math.hypot(*delta_active) < 3.0:
        return None

    best: tuple[float, int, VisualObject, VisualObject] | None = None
    for before_hub in before.mediators:
        for after_hub in after.mediators:
            if before_hub.color != after_hub.color:
                continue
            delta_hub = (
                after_hub.center_x - before_hub.center_x,
                after_hub.center_y - before_hub.center_y,
            )
            if math.hypot(*delta_hub) < 0.5:
                continue
            for arity in range(2, 7):
                error = abs(delta_hub[0] * arity - delta_active[0]) + abs(
                    delta_hub[1] * arity - delta_active[1]
                )
                candidate = (error, arity, before_hub, after_hub)
                if best is None or candidate[:2] < best[:2]:
                    best = candidate
    if best is None or best[0] > 3.0:
        return None
    error, arity, _before_hub, after_hub = best
    targets = _affine_target_candidates(after, mediator_color=after_hub.color)
    if not targets:
        return None
    target = min(
        targets,
        key=lambda item: _distance(
            (item.center_x, item.center_y), (after_hub.center_x, after_hub.center_y)
        ),
    )

    expected_sum_x = arity * after_hub.center_x - active_after.center_x
    expected_sum_y = arity * after_hub.center_y - active_after.center_y
    endpoint_pool = tuple(
        item for item in after.endpoints if item.object_ref != active_after.object_ref
    )
    best_anchors: tuple[float, tuple[VisualObject, ...]] | None = None
    for anchors in itertools.combinations(endpoint_pool, arity - 1):
        error_sum = abs(sum(item.center_x for item in anchors) - expected_sum_x) + abs(
            sum(item.center_y for item in anchors) - expected_sum_y
        )
        candidate_anchors = (error_sum, anchors)
        if best_anchors is None or candidate_anchors[0] < best_anchors[0]:
            best_anchors = candidate_anchors
    if best_anchors is None or best_anchors[0] > 2.5 * (arity - 1):
        return None

    identity = (
        f"{level_index}|{active_after.color}|{after_hub.color}|{arity}|"
        f"{before.frame_hash}|{after.frame_hash}"
    )
    mechanic_ref = "affine:" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:20]
    return AffineMechanic(
        mechanic_ref=mechanic_ref,
        level_index=level_index,
        active_color=active_after.color,
        mediator_color=after_hub.color,
        arity=arity,
        source_before_hash=before.frame_hash,
        source_after_hash=after.frame_hash,
        support_error=error + best_anchors[0],
        anchor_centers=tuple(item.rounded_center for item in best_anchors[1]),
        target_center=target.rounded_center,
    )


def infer_transferred_affine_mechanic(
    scene: VisualScene,
    *,
    level_index: int,
    active_color: int,
    supported_prior: tuple[AffineMechanic, ...],
) -> AffineMechanic | None:
    """Apply a previously observed affine form to a new level layout.

    Only an already observed affine form transfers.  Current endpoints,
    mediator, arity, and target are re-read from the new frame, and the relation
    must close geometrically before it is used.  Raw coordinates and object
    identities never cross levels.
    """

    reliable_prior = tuple(item for item in supported_prior if item.support_error <= 6.0)
    if not reliable_prior:
        return None
    active_candidates = tuple(item for item in scene.endpoints if item.color == active_color)
    if not active_candidates:
        color_counts = Counter(item.color for item in scene.endpoints)
        active_candidates = tuple(item for item in scene.endpoints if color_counts[item.color] == 1)
    if not active_candidates:
        return None
    best: (
        tuple[
            float,
            int,
            VisualObject,
            tuple[VisualObject, ...],
            VisualObject,
        ]
        | None
    ) = None
    best_is_ambiguous = False
    for active in active_candidates:
        pool = tuple(item for item in scene.endpoints if item.object_ref != active.object_ref)
        for hub in scene.mediators:
            targets = _affine_target_candidates(scene, mediator_color=hub.color)
            if not targets:
                continue
            target = min(
                targets,
                key=lambda item: _distance(
                    (item.center_x, item.center_y), (hub.center_x, hub.center_y)
                ),
            )
            if _distance((hub.center_x, hub.center_y), (target.center_x, target.center_y)) <= 2.0:
                continue
            for arity in range(2, 7):
                for anchors in itertools.combinations(pool, arity - 1):
                    error = abs(
                        (active.center_x + sum(item.center_x for item in anchors)) / arity
                        - hub.center_x
                    ) + abs(
                        (active.center_y + sum(item.center_y for item in anchors)) / arity
                        - hub.center_y
                    )
                    candidate = (error, arity, hub, anchors, target)
                    if best is None or candidate[:2] < best[:2]:
                        best = candidate
                        best_is_ambiguous = False
                    elif (
                        best is not None
                        and candidate[:2] == best[:2]
                        and (
                            candidate[2].object_ref != best[2].object_ref
                            or tuple(item.object_ref for item in candidate[3])
                            != tuple(item.object_ref for item in best[3])
                            or candidate[4].object_ref != best[4].object_ref
                        )
                    ):
                        best_is_ambiguous = True
    if best is None or best[0] > 1.5 or best_is_ambiguous:
        return None
    error, arity, hub, anchors, target = best
    source_refs = ",".join(sorted(item.mechanic_ref for item in reliable_prior))
    identity = (
        f"transfer|{source_refs}|{level_index}|{active.color}|{hub.color}|{arity}|"
        f"{scene.frame_hash}"
    )
    return AffineMechanic(
        mechanic_ref="affine-transfer:" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:20],
        level_index=level_index,
        active_color=active.color,
        mediator_color=hub.color,
        arity=arity,
        source_before_hash=scene.frame_hash,
        source_after_hash=scene.frame_hash,
        support_error=error,
        anchor_centers=tuple(item.rounded_center for item in anchors),
        target_center=target.rounded_center,
    )


def _radial_plan_points(
    scene: VisualScene,
    *,
    target: tuple[int, int],
    movers: tuple[VisualObject, ...],
    rejected_signatures: set[str],
) -> tuple[Coordinate, ...] | None:
    """Choose a small target-relative equivalence class, never a grid sweep."""

    arity = len(movers)
    if not 2 <= arity <= 6:
        return None
    active_color = movers[0].color
    unrelated_target_regions = tuple(
        region for center, region in _visible_target_regions(scene) if center != target
    )
    for radius in (7, 9, 11, 13, 16, 19, 23, 27):
        for rotation_index in range(16):
            rotation = (2 * math.pi * rotation_index) / 16
            raw = tuple(
                (
                    round(target[0] + radius * math.cos(rotation + 2 * math.pi * i / arity)),
                    round(target[1] + radius * math.sin(rotation + 2 * math.pi * i / arity)),
                )
                for i in range(arity)
            )
            if len(set(raw)) != arity:
                continue
            prospective_footprints: list[frozenset[tuple[int, int]]] = []
            plan_is_readable = True
            for index, (mover, (x, y)) in enumerate(zip(movers, raw, strict=True)):
                prior_and_current_refs = frozenset(item.object_ref for item in movers[: index + 1])
                vacated_footprints = frozenset(
                    cell
                    for prior_mover in movers[:index]
                    for cell in _object_footprint(prior_mover)
                )
                if not _endpoint_placement_is_open(
                    scene,
                    mover,
                    x=x,
                    y=y,
                    permitted_occupied_cells=vacated_footprints,
                    prospective_color=active_color,
                    ignored_object_refs=prior_and_current_refs,
                ):
                    plan_is_readable = False
                    break
                # Every support point except the last is only temporarily
                # active.  Clicking the next anchor transfers the active role
                # and recolors this endpoint to that anchor's prior color.
                # Preflight that returned-frame identity as well as the
                # immediate active-color placement; otherwise a plan can be
                # readable for one step and merge on the following role swap.
                if index + 1 < arity and not _endpoint_placement_is_open(
                    scene,
                    mover,
                    x=x,
                    y=y,
                    permitted_occupied_cells=vacated_footprints,
                    prospective_color=movers[index + 1].color,
                    ignored_object_refs=frozenset(item.object_ref for item in movers[: index + 2]),
                ):
                    plan_is_readable = False
                    break
                prospective = _translated_object_footprint(mover, center=(x, y))
                if any(prospective & region for region in unrelated_target_regions):
                    plan_is_readable = False
                    break
                if any(
                    min(
                        max(abs(lx - rx), abs(ly - ry))
                        for lx, ly in prospective
                        for rx, ry in prior
                    )
                    <= 1
                    for prior in prospective_footprints
                ):
                    plan_is_readable = False
                    break
                prospective_footprints.append(prospective)
            if not plan_is_readable:
                continue
            signature = ";".join(f"{x},{y}" for x, y in raw)
            if signature in rejected_signatures:
                continue
            return tuple(Coordinate(x, y) for x, y in raw)
    return None


_COMPOSITE_MEDIATOR_OFFSETS = frozenset(
    (dx, dy) for dy in range(-2, 3) for dx in range(-2, 3) if (abs(dx), abs(dy)) != (2, 2)
)
_COMPOSITE_TARGET_OFFSETS = frozenset(
    {
        (-1, -3),
        (1, -3),
        (-2, -2),
        (2, -2),
        (-3, -1),
        (3, -1),
        (-3, 1),
        (3, 1),
        (-2, 2),
        (2, 2),
        (-1, 3),
        (1, 3),
    }
)
_COMPOUND_MARKER_ENDPOINT_OFFSETS = frozenset(
    (dx, dy)
    for dy in range(-2, 3)
    for dx in range(-2, 3)
    if abs(dx) + abs(dy) <= 2 and (dx, dy) != (0, 0)
)


def _proxy_visual_object(
    scene: VisualScene,
    *,
    marker_color: int,
    cells: tuple[tuple[int, int], ...],
    center: tuple[int, int],
    center_cell: int,
    role: VisualObjectRole,
    identity_kind: str,
) -> VisualObject:
    """Build one bounded compound-object projection without changing base components."""

    ordered = tuple(sorted(cells, key=lambda cell: (cell[1], cell[0])))
    identity = identity_kind + "|" + ";".join(f"{x},{y},{scene.cells[y][x]}" for x, y in ordered)
    object_ref = (
        f"visual-{identity_kind}:"
        + hashlib.sha256(f"{marker_color}|{identity}".encode("ascii")).hexdigest()[:20]
    )
    min_x = min(x for x, _y in ordered)
    min_y = min(y for _x, y in ordered)
    max_x = max(x for x, _y in ordered)
    max_y = max(y for _x, y in ordered)
    return VisualObject(
        object_ref=object_ref,
        color=marker_color,
        cells=ordered,
        min_x=min_x,
        min_y=min_y,
        max_x=max_x,
        max_y=max_y,
        center_x=float(center[0]),
        center_y=float(center[1]),
        center_cell=center_cell,
        touches_edge=(
            min_x == 0 or min_y == 0 or max_x == scene.width - 1 or max_y == scene.height - 1
        ),
        role=role,
    )


def _compound_outer_signature(
    scene: VisualScene,
    *,
    cells: tuple[tuple[int, int], ...],
    center: tuple[int, int],
) -> frozenset[int]:
    """Return compound sector colors while excluding connector strokes and the core."""

    footprint = frozenset(cells)
    cell_to_object = {
        cell: item for item in scene.objects for cell in item.cells if cell in footprint
    }
    return frozenset(
        scene.cells[y][x]
        for x, y in cells
        if (x, y) != center
        and ((item := cell_to_object.get((x, y))) is None or frozenset(item.cells) <= footprint)
    )


def _compound_raw_outer_signature(
    scene: VisualScene,
    *,
    cells: tuple[tuple[int, int], ...],
    center: tuple[int, int],
) -> frozenset[int]:
    """Return every observed non-core color in an exact compound footprint."""

    return frozenset(scene.cells[y][x] for x, y in cells if (x, y) != center)


def _composite_marker_mediator(
    scene: VisualScene,
    *,
    marker_color: int,
    endpoints: tuple[VisualObject, ...],
) -> VisualObject | None:
    """Assemble the exact 21-cell compound disk at an endpoint-group centroid."""

    center = (
        sum(item.rounded_center[0] for item in endpoints) // len(endpoints),
        sum(item.rounded_center[1] for item in endpoints) // len(endpoints),
    )
    cells = tuple(
        sorted(
            ((center[0] + dx, center[1] + dy) for dx, dy in _COMPOSITE_MEDIATOR_OFFSETS),
            key=lambda cell: (cell[1], cell[0]),
        )
    )
    if any(
        not (0 <= x < scene.width and 0 <= y < scene.height)
        or scene.cells[y][x] == scene.background
        for x, y in cells
    ):
        return None
    signature = _compound_outer_signature(scene, cells=cells, center=center)
    if marker_color not in signature or scene.cells[center[1]][center[0]] == scene.background:
        return None
    return _proxy_visual_object(
        scene,
        marker_color=marker_color,
        cells=cells,
        center=center,
        center_cell=scene.cells[center[1]][center[0]],
        role=VisualObjectRole.MEDIATOR_CANDIDATE,
        identity_kind="composite-mediator",
    )


def _composite_sparse_targets(
    scene: VisualScene,
) -> tuple[tuple[VisualObject, frozenset[int]], ...]:
    """Find exact multicolor 12-cell rings without loosening component roles globally."""

    targets: list[tuple[VisualObject, frozenset[int]]] = []
    complete_box = frozenset((dx, dy) for dy in range(-3, 4) for dx in range(-3, 4))
    for center_y in range(3, scene.height - 3):
        for center_x in range(3, scene.width - 3):
            observed = frozenset(
                (dx, dy)
                for dx, dy in complete_box
                if scene.cells[center_y + dy][center_x + dx] != scene.background
            )
            if observed != _COMPOSITE_TARGET_OFFSETS:
                continue
            cells = tuple(
                sorted(
                    ((center_x + dx, center_y + dy) for dx, dy in _COMPOSITE_TARGET_OFFSETS),
                    key=lambda cell: (cell[1], cell[0]),
                )
            )
            signature = frozenset(scene.cells[y][x] for x, y in cells)
            proxy = _proxy_visual_object(
                scene,
                marker_color=min(signature),
                cells=cells,
                center=(center_x, center_y),
                center_cell=scene.background,
                role=VisualObjectRole.HOLLOW_TARGET_CANDIDATE,
                identity_kind="composite-target-candidate",
            )
            targets.append((proxy, signature))
    return tuple(targets)


def _composite_filled_disks(scene: VisualScene) -> tuple[_CompositeFilledDisk, ...]:
    """Find isolated exact 21-cell disks carrying exactly two observed colors."""

    disks: list[_CompositeFilledDisk] = []
    border = frozenset(
        (dx, dy) for dy in range(-3, 4) for dx in range(-3, 4) if max(abs(dx), abs(dy)) == 3
    )
    complete_box = frozenset((dx, dy) for dy in range(-2, 3) for dx in range(-2, 3))
    for center_y in range(3, scene.height - 3):
        for center_x in range(3, scene.width - 3):
            observed = frozenset(
                (dx, dy)
                for dx, dy in complete_box
                if scene.cells[center_y + dy][center_x + dx] != scene.background
            )
            if observed != _COMPOSITE_MEDIATOR_OFFSETS or any(
                scene.cells[center_y + dy][center_x + dx] != scene.background for dx, dy in border
            ):
                continue
            cells = tuple(
                sorted(
                    ((center_x + dx, center_y + dy) for dx, dy in _COMPOSITE_MEDIATOR_OFFSETS),
                    key=lambda cell: (cell[1], cell[0]),
                )
            )
            palette = frozenset(scene.cells[y][x] for x, y in cells)
            if len(palette) != 2:
                continue
            offsets_by_color = tuple(
                (
                    color,
                    frozenset(
                        (x - center_x, y - center_y) for x, y in cells if scene.cells[y][x] == color
                    ),
                )
                for color in sorted(palette)
            )
            disks.append(
                _CompositeFilledDisk(
                    center=(center_x, center_y),
                    cells=cells,
                    palette=palette,
                    offsets_by_color=offsets_by_color,
                )
            )
    return tuple(disks)


def _bridge_projection_offset(value: int) -> int:
    """Project one sparse radius-three ring coordinate onto a radius-two disk."""

    magnitude = (2 * abs(value) + 1) // 3
    return magnitude if value >= 0 else -magnitude


def _bridge_target_matches_sources(
    scene: VisualScene,
    *,
    sources: tuple[_CompositeFilledDisk, ...],
    residual_colors: tuple[int, ...],
    target: VisualObject,
) -> bool:
    """Require the ring sectors to be the radial residual projection of the disks."""

    target_center = target.rounded_center
    for x, y in target.cells:
        projected = (
            _bridge_projection_offset(x - target_center[0]),
            _bridge_projection_offset(y - target_center[1]),
        )
        owners = tuple(
            residual
            for source, residual in zip(sources, residual_colors, strict=True)
            if projected in source.offsets(residual)
        )
        if len(owners) != 1 or scene.cells[y][x] != owners[0]:
            return False
    return True


def _composite_bridge_examples(
    scene: VisualScene,
    *,
    carrier_color: int,
) -> tuple[_CompositeBridgeExample, ...]:
    """Return exact carrier-elimination examples without inferring a game rule."""

    disks = tuple(disk for disk in _composite_filled_disks(scene) if carrier_color in disk.palette)
    targets = _composite_sparse_targets(scene)
    examples: list[_CompositeBridgeExample] = []
    for left, right in itertools.combinations(disks, 2):
        if left.palette & right.palette != {carrier_color}:
            continue
        left_residuals = left.palette - {carrier_color}
        right_residuals = right.palette - {carrier_color}
        if len(left_residuals) != 1 or len(right_residuals) != 1:
            continue
        left_residual = next(iter(left_residuals))
        right_residual = next(iter(right_residuals))
        if left_residual == right_residual:
            continue
        left_carrier = left.offsets(carrier_color)
        right_carrier = right.offsets(carrier_color)
        if (
            left_carrier & right_carrier
            or left_carrier | right_carrier != _COMPOSITE_MEDIATOR_OFFSETS
        ):
            continue
        ordered_sources = sorted((left, right), key=lambda item: item.center)
        sources = (ordered_sources[0], ordered_sources[1])
        residual_colors = (
            next(iter(sources[0].palette - {carrier_color})),
            next(iter(sources[1].palette - {carrier_color})),
        )
        matching_targets = tuple(
            target
            for target, signature in targets
            if signature == frozenset(residual_colors)
            and _bridge_target_matches_sources(
                scene,
                sources=sources,
                residual_colors=residual_colors,
                target=target,
            )
        )
        if len(matching_targets) != 1:
            continue
        examples.append(
            _CompositeBridgeExample(
                carrier_color=carrier_color,
                sources=sources,
                residual_colors=residual_colors,
                target=matching_targets[0],
            )
        )
    examples.sort(
        key=lambda item: (
            item.target.rounded_center,
            tuple(source.center for source in item.sources),
            item.residual_colors,
        )
    )
    return tuple(examples)


def _compound_marker_endpoint_candidates(
    scene: VisualScene,
    *,
    active_color: int,
) -> tuple[VisualObject, ...]:
    """Return one exact marker-centered endpoint family, including a merged active glyph."""

    candidates_by_marker: dict[int, list[VisualObject]] = {}
    for center_y in range(2, scene.height - 2):
        for center_x in range(2, scene.width - 2):
            center_color = scene.cells[center_y][center_x]
            outer_colors = {
                scene.cells[center_y + dy][center_x + dx]
                for dx, dy in _COMPOUND_MARKER_ENDPOINT_OFFSETS
            }
            if (
                len(outer_colors) != 1
                or center_color == scene.background
                or center_color in outer_colors
                or scene.background in outer_colors
            ):
                continue
            outer_color = next(iter(outer_colors))
            cells = tuple(
                sorted(
                    (
                        (center_x + dx, center_y + dy)
                        for dx, dy in _COMPOUND_MARKER_ENDPOINT_OFFSETS
                    ),
                    key=lambda cell: (cell[1], cell[0]),
                )
            )
            candidates_by_marker.setdefault(center_color, []).append(
                _proxy_visual_object(
                    scene,
                    marker_color=outer_color,
                    cells=cells,
                    center=(center_x, center_y),
                    center_cell=center_color,
                    role=VisualObjectRole.ENDPOINT_CANDIDATE,
                    identity_kind="compound-marker-endpoint",
                )
            )

    families: list[tuple[VisualObject, ...]] = []
    for endpoints in candidates_by_marker.values():
        outer_counts = Counter(endpoint.color for endpoint in endpoints)
        if (
            4 <= len(endpoints) <= 12
            and outer_counts[active_color] == 1
            and len(outer_counts) == 2
            and sum(outer_counts.values()) == len(endpoints)
        ):
            families.append(tuple(sorted(endpoints, key=lambda item: item.object_ref)))
    return families[0] if len(families) == 1 else ()


def _compound_marker_mediator_candidate(
    scene: VisualScene,
    endpoints: tuple[VisualObject, ...],
    *,
    carrier_color: int,
) -> VisualObject | None:
    """Recover an exact carrier disk even when it joins the active same-color endpoint."""

    center = (
        sum(endpoint.rounded_center[0] for endpoint in endpoints) // len(endpoints),
        sum(endpoint.rounded_center[1] for endpoint in endpoints) // len(endpoints),
    )
    cells = tuple(
        sorted(
            ((center[0] + dx, center[1] + dy) for dx, dy in _COMPOSITE_MEDIATOR_OFFSETS),
            key=lambda cell: (cell[1], cell[0]),
        )
    )
    if any(
        not (0 <= x < scene.width and 0 <= y < scene.height) or scene.cells[y][x] != carrier_color
        for x, y in cells
    ):
        return None
    return _proxy_visual_object(
        scene,
        marker_color=carrier_color,
        cells=cells,
        center=center,
        center_cell=carrier_color,
        role=VisualObjectRole.MEDIATOR_CANDIDATE,
        identity_kind="compound-marker-mediator",
    )


def _unique_compound_marker_children(
    scene: VisualScene,
    *,
    active_color: int,
    search_budget: _HierarchySearchBudget,
) -> tuple[_AffineChildGroup, ...] | None:
    """Partition one marker family by exact centroid disks and connector evidence."""

    endpoints = _compound_marker_endpoint_candidates(scene, active_color=active_color)
    if not endpoints:
        return None
    candidate_groups: list[_AffineChildGroup] = []
    for arity in range(2, min(6, len(endpoints) - 1) + 1):
        for endpoint_group in itertools.combinations(endpoints, arity):
            search_budget.consume()
            mediator = _compound_marker_mediator_candidate(
                scene,
                endpoint_group,
                carrier_color=active_color,
            )
            if mediator is None:
                continue
            child = _AffineChildGroup(mediator=mediator, endpoints=endpoint_group)
            connector = _hierarchy_connector_evidence(scene, child)
            if connector is not None:
                candidate_groups.append(child)
    if not candidate_groups:
        return None

    all_refs = frozenset(endpoint.object_ref for endpoint in endpoints)
    solutions: dict[tuple[tuple[str, ...], ...], tuple[_AffineChildGroup, ...]] = {}

    def search(
        remaining: frozenset[str],
        chosen: tuple[_AffineChildGroup, ...],
    ) -> None:
        search_budget.consume()
        if len(solutions) > 1:
            return
        if not remaining:
            if len(chosen) < 2:
                return
            ordered = tuple(
                sorted(
                    chosen,
                    key=lambda child: (
                        child.mediator.rounded_center,
                        tuple(endpoint.object_ref for endpoint in child.endpoints),
                    ),
                )
            )
            identity = tuple(
                tuple(sorted(endpoint.object_ref for endpoint in child.endpoints))
                for child in ordered
            )
            solutions.setdefault(identity, ordered)
            return
        pivot = min(remaining)
        for child in candidate_groups:
            refs = frozenset(endpoint.object_ref for endpoint in child.endpoints)
            if pivot not in refs or not refs <= remaining:
                continue
            search(remaining - refs, (*chosen, child))

    search(all_refs, ())
    if len(solutions) != 1:
        return None
    children = next(iter(solutions.values()))
    active_children = tuple(
        child
        for child in children
        if any(endpoint.color == active_color for endpoint in child.endpoints)
    )
    if len(active_children) != 1:
        return None
    first = active_children[0]
    return (
        first,
        *(child for child in children if child is not first),
    )


def _multi_source_composite_bridge_examples(
    scene: VisualScene,
    *,
    carrier_color: int,
) -> tuple[_CompositeBridgeExample, ...]:
    """Return exact three-or-more-source residual projections onto sparse rings."""

    disks = tuple(
        disk
        for disk in _composite_filled_disks(scene)
        if carrier_color in disk.palette and len(disk.palette) == 2
    )
    examples: list[_CompositeBridgeExample] = []
    for target, signature in _composite_sparse_targets(scene):
        if not 3 <= len(signature) <= 6:
            continue
        selected: list[_CompositeFilledDisk] = []
        for residual_color in sorted(signature):
            matches = tuple(
                disk for disk in disks if disk.palette == frozenset({carrier_color, residual_color})
            )
            if len(matches) != 1:
                selected = []
                break
            selected.append(matches[0])
        if len(selected) != len(signature) or len(set(selected)) != len(selected):
            continue
        sources = tuple(sorted(selected, key=lambda item: item.center))
        residual_colors = tuple(next(iter(source.palette - {carrier_color})) for source in sources)
        residual_union = frozenset(
            offset
            for source, residual_color in zip(sources, residual_colors, strict=True)
            for offset in source.offsets(residual_color)
        )
        carrier_union = frozenset(
            offset for source in sources for offset in source.offsets(carrier_color)
        )
        if (
            residual_union != _COMPOSITE_MEDIATOR_OFFSETS
            or carrier_union != _COMPOSITE_MEDIATOR_OFFSETS
            or not _bridge_target_matches_sources(
                scene,
                sources=sources,
                residual_colors=residual_colors,
                target=target,
            )
        ):
            continue
        examples.append(
            _CompositeBridgeExample(
                carrier_color=carrier_color,
                sources=sources,
                residual_colors=residual_colors,
                target=target,
            )
        )
    return tuple(
        sorted(
            examples,
            key=lambda example: (
                example.target.rounded_center,
                tuple(source.center for source in example.sources),
            ),
        )
    )


def _marker_multi_source_composite_cargo_relation(
    scene: VisualScene,
    *,
    active_color: int,
    level_index: int,
    search_budget: _HierarchySearchBudget,
) -> tuple[_AffineHierarchy, _CompositeBridgeRelation] | None:
    """Build one exact marker hierarchy and unique multi-source sink assignment."""

    children = _unique_compound_marker_children(
        scene,
        active_color=active_color,
        search_budget=search_budget,
    )
    examples = _multi_source_composite_bridge_examples(scene, carrier_color=active_color)
    if (
        children is None
        or len(children) != len(examples)
        or len(children) < 2
        or len({source.center for example in examples for source in example.sources})
        != sum(len(example.sources) for example in examples)
    ):
        return None
    example_target_centers = {example.target.rounded_center for example in examples}
    unmatched_targets = tuple(
        target
        for target, _signature in _composite_sparse_targets(scene)
        if target.rounded_center not in example_target_centers
    )
    if len(unmatched_targets) != 1:
        return None

    permutation_items: list[tuple[_CompositeBridgeExample, ...]] = []
    for assignment in itertools.permutations(examples):
        search_budget.consume()
        permutation_items.append(assignment)
    permutations = tuple(permutation_items)

    def metric_score(
        assignment: tuple[_CompositeBridgeExample, ...],
        *,
        metric: str,
    ) -> float:
        parts: list[float] = []
        for child, example in zip(children, assignment, strict=True):
            source_count = len(example.sources)
            delta_x = (
                abs(
                    source_count * child.mediator.rounded_center[0]
                    - sum(source.center[0] for source in example.sources)
                )
                / source_count
            )
            delta_y = (
                abs(
                    source_count * child.mediator.rounded_center[1]
                    - sum(source.center[1] for source in example.sources)
                )
                / source_count
            )
            if metric == "euclidean":
                parts.append(math.hypot(delta_x, delta_y))
            elif metric == "manhattan":
                parts.append(delta_x + delta_y)
            else:
                parts.append(delta_x * delta_x + delta_y * delta_y)
        return math.fsum(parts)

    winners: list[tuple[_CompositeBridgeExample, ...]] = []
    for metric in ("euclidean", "manhattan", "squared-euclidean"):
        ranked = sorted(
            ((metric_score(items, metric=metric), items) for items in permutations),
            key=lambda item: (
                item[0],
                tuple(example.target.rounded_center for example in item[1]),
            ),
        )
        if len(ranked) > 1 and math.isclose(
            ranked[0][0],
            ranked[1][0],
            rel_tol=1e-12,
            abs_tol=1e-12,
        ):
            return None
        winners.append(ranked[0][1])
    if any(winner != winners[0] for winner in winners[1:]):
        return None

    assignments = tuple(zip(children, winners[0], strict=True))
    identity = (
        "marker-multi-source-composite-cargo-v1",
        level_index,
        tuple(
            (
                _child_structure_signature(scene, child),
                tuple(source.center for source in example.sources),
                example.residual_colors,
                example.target.rounded_center,
                tuple(sorted((x, y, scene.cells[y][x]) for x, y in example.target.cells)),
            )
            for child, example in assignments
        ),
        (
            unmatched_targets[0].rounded_center,
            tuple(sorted((x, y, scene.cells[y][x]) for x, y in unmatched_targets[0].cells)),
        ),
    )
    digest = hashlib.sha256(repr(identity).encode("ascii")).hexdigest()[:24]
    hierarchy = _AffineHierarchy(
        target=unmatched_targets[0],
        children=children,
        active_color=active_color,
        mechanic_ref=f"affine-marker-multi-source-mechanic:{digest}",
    )
    return (
        hierarchy,
        _CompositeBridgeRelation(
            assignments=assignments,
            relation_key=f"affine-marker-multi-source-relation:{digest}",
        ),
    )


def _embedded_marker_groups(scene: VisualScene) -> tuple[_EmbeddedMarkerGroup, ...]:
    """Read unambiguous endpoint groups from embedded center-cell colors.

    An endpoint marker is used only when its center-cell color names exactly
    one mediator and exactly one hollow target in the same frame.  Filled
    endpoints whose center merely repeats their outer color therefore stay on
    the existing discovery path.
    """

    endpoints_by_marker: dict[int, list[VisualObject]] = {}
    for endpoint in scene.endpoints:
        if endpoint.center_cell in {scene.background, endpoint.color}:
            continue
        endpoints_by_marker.setdefault(endpoint.center_cell, []).append(endpoint)

    composite_targets = _composite_sparse_targets(scene)
    groups: list[_EmbeddedMarkerGroup] = []
    for marker_color, endpoints in endpoints_by_marker.items():
        mediators = tuple(item for item in scene.mediators if item.color == marker_color)
        targets = tuple(item for item in scene.targets if item.color == marker_color)
        if not 2 <= len(endpoints) <= 6:
            continue
        mediator: VisualObject | None = None
        target: VisualObject | None = None
        if len(mediators) == 1 and len(targets) == 1:
            mediator = mediators[0]
            target = targets[0]
        else:
            mediator = _composite_marker_mediator(
                scene,
                marker_color=marker_color,
                endpoints=tuple(endpoints),
            )
            if mediator is not None:
                outer_colors = _compound_outer_signature(
                    scene,
                    cells=mediator.cells,
                    center=mediator.rounded_center,
                )
                matched_targets = tuple(
                    candidate
                    for candidate, signature in composite_targets
                    if len(signature) >= 2
                    and marker_color in signature
                    and signature == outer_colors
                )
                if len(matched_targets) != 1:
                    # Connector filtering is the primary identity surface, but
                    # an unrelated same-color component can extend beyond the
                    # exact disk and make that filter omit a genuine sector.
                    # Fall back only to the complete observed disk signature
                    # and still require an exact unique target match.
                    raw_outer_colors = _compound_raw_outer_signature(
                        scene,
                        cells=mediator.cells,
                        center=mediator.rounded_center,
                    )
                    matched_targets = tuple(
                        candidate
                        for candidate, signature in composite_targets
                        if len(signature) >= 2
                        and marker_color in signature
                        and signature == raw_outer_colors
                    )
                if len(matched_targets) == 1:
                    target = _proxy_visual_object(
                        scene,
                        marker_color=marker_color,
                        cells=matched_targets[0].cells,
                        center=matched_targets[0].rounded_center,
                        center_cell=scene.background,
                        role=VisualObjectRole.HOLLOW_TARGET_CANDIDATE,
                        identity_kind="composite-target",
                    )
        if mediator is None or target is None:
            continue
        groups.append(
            _EmbeddedMarkerGroup(
                marker_color=marker_color,
                endpoints=tuple(sorted(endpoints, key=lambda item: item.object_ref)),
                mediator=mediator,
                target=target,
            )
        )
    return tuple(sorted(groups, key=lambda item: item.marker_color))


def _unsolved_mediator_targets(
    scene: VisualScene,
) -> tuple[tuple[VisualObject, VisualObject], ...]:
    """Return readable same-color mediator/target pairs that still disagree."""

    pairs: list[tuple[VisualObject, VisualObject]] = []
    for mediator in scene.mediators:
        targets = _affine_target_candidates(scene, mediator_color=mediator.color)
        if not targets:
            continue
        target = min(
            targets,
            key=lambda item: _distance(
                (item.center_x, item.center_y),
                (mediator.center_x, mediator.center_y),
            ),
        )
        if (
            _distance(
                (mediator.center_x, mediator.center_y),
                (target.center_x, target.center_y),
            )
            > 2.0
        ):
            pairs.append((mediator, target))
    return tuple(sorted(pairs, key=lambda pair: (pair[0].color, pair[0].object_ref)))


def supports_visual_causal_observation(observation: Observation) -> bool:
    """Return whether visible evidence supports the coordinate learner.

    This compatibility gate is deliberately observation-only.  It consumes no
    game identity, retained mechanic, campaign constant, or hidden source: the
    current official frame must advertise ACTION6, expose at least two readable
    endpoints, and contain an unresolved mediator/target relation.
    """

    if (
        observation.state is not GameStateName.NOT_FINISHED
        or ActionName.ACTION6 not in observation.available_actions
        or not observation.frames
    ):
        return False
    scene = extract_visual_scene(observation.frames[-1])
    if len(scene.endpoints) < 2:
        return False
    marker_groups = _embedded_marker_groups(scene)
    if any(group.mediator.rounded_center != group.target.rounded_center for group in marker_groups):
        return True
    return bool(_unsolved_mediator_targets(scene))


def _embedded_marker_active_endpoint(
    scene: VisualScene,
    *,
    active_color: int | None,
) -> VisualObject | None:
    """Return the visible active endpoint only when its identity is unambiguous."""

    marked_endpoints = tuple(
        endpoint
        for endpoint in scene.endpoints
        if endpoint.center_cell not in {scene.background, endpoint.color}
    )
    observed_active = tuple(
        endpoint for endpoint in marked_endpoints if endpoint.color == active_color
    )
    if len(observed_active) == 1:
        return observed_active[0]
    outer_color_counts = Counter(endpoint.color for endpoint in marked_endpoints)
    active_candidates = tuple(
        endpoint for endpoint in marked_endpoints if outer_color_counts[endpoint.color] == 1
    )
    if len(active_candidates) != 1 or not any(count > 1 for count in outer_color_counts.values()):
        return None
    return active_candidates[0]


def _axis_box_distance(value: int, lower: int, upper: int) -> int:
    if value < lower:
        return lower - value
    if value > upper:
        return value - upper
    return 0


def _marker_group_potential(
    group: _EmbeddedMarkerGroup,
    *,
    sum_x: int,
    sum_y: int,
) -> int:
    """Squared distance of the endpoint sum from the floor-centroid goal box."""

    target_x, target_y = group.target.rounded_center
    lower_x = group.arity * target_x
    lower_y = group.arity * target_y
    dx = _axis_box_distance(sum_x, lower_x, lower_x + group.arity - 1)
    dy = _axis_box_distance(sum_y, lower_y, lower_y + group.arity - 1)
    return dx * dx + dy * dy


def _certified_marker_target_contaminant(
    group: _EmbeddedMarkerGroup,
) -> VisualObject | None:
    """Return one endpoint whose marker center is joined to an exact sparse ring.

    This is an observation-level parsing residual, not a target rewrite.  The
    endpoint is identified only when removing its center leaves the complete
    symmetric 12-cell ring used by the generic sparse-target detector.
    """

    candidates = tuple(
        endpoint for endpoint in group.endpoints if endpoint.rounded_center in group.target.cells
    )
    if len(candidates) != 1:
        return None
    contaminant = candidates[0]
    remaining = frozenset(group.target.cells) - {contaminant.rounded_center}
    if len(remaining) != len(_COMPOSITE_TARGET_OFFSETS):
        return None
    min_x = min(x for x, _y in remaining)
    max_x = max(x for x, _y in remaining)
    min_y = min(y for _x, y in remaining)
    max_y = max(y for _x, y in remaining)
    if (min_x + max_x) % 2 or (min_y + max_y) % 2:
        return None
    center = ((min_x + max_x) // 2, (min_y + max_y) // 2)
    offsets = frozenset((x - center[0], y - center[1]) for x, y in remaining)
    return contaminant if offsets == _COMPOSITE_TARGET_OFFSETS else None


def _certified_marker_target_overlay_contaminant(
    scene: VisualScene,
    group: _EmbeddedMarkerGroup,
) -> VisualObject | None:
    """Return one endpoint center joined to one color sector of a compound target.

    A compound target remains readable as a complete multicolor ring even when
    the parser also joins one nearby same-color endpoint center to a single
    color sector of that ring.  That secondary component is not an independent
    target: removing exactly the endpoint center must leave exactly every
    target cell whose observed color is the group's marker color.  Requiring
    this equality keeps the certificate local and prevents approximate target
    rewriting.
    """

    marker_target_cells = frozenset(
        (x, y) for x, y in group.target.cells if scene.cells[y][x] == group.marker_color
    )
    if not marker_target_cells:
        return None
    candidates = {
        endpoint.object_ref: endpoint
        for endpoint in group.endpoints
        for target in scene.targets
        if target.color == group.marker_color
        and frozenset(target.cells) == marker_target_cells | {endpoint.rounded_center}
        and endpoint.rounded_center not in marker_target_cells
    }
    return next(iter(candidates.values())) if len(candidates) == 1 else None


def _certified_marker_target_contaminant_in_scene(
    scene: VisualScene,
    group: _EmbeddedMarkerGroup,
) -> VisualObject | None:
    """Recognize either exact center-in-ring or sector-overlay contamination."""

    return _certified_marker_target_contaminant(
        group
    ) or _certified_marker_target_overlay_contaminant(scene, group)


def _final_marker_target_overlap_cells(
    scene: VisualScene,
    group: _EmbeddedMarkerGroup,
) -> frozenset[tuple[int, int]]:
    """Return only the small observed target-layer cells a final move may consume.

    Some rendered targets contain a second hollow overlay in the same bounding
    region.  A locally exact solution can require the endpoint glyph to enter
    that region before the official level transition consumes it.  Large or
    unrelated components remain protected.
    """

    target = group.target
    cells = set(target.cells)
    for item in scene.targets:
        boxes_overlap = not (
            item.max_x < target.min_x
            or item.min_x > target.max_x
            or item.max_y < target.min_y
            or item.min_y > target.max_y
        )
        if not boxes_overlap or item.area > _SMALL_COMPONENT_COMBINED_AREA:
            continue
        cells.update(
            (x, y)
            for x, y in item.cells
            if target.min_x <= x <= target.max_x and target.min_y <= y <= target.max_y
        )
    return frozenset(cells)


def _marker_relocation_candidates(
    scene: VisualScene,
    group: _EmbeddedMarkerGroup,
    endpoint: VisualObject,
    *,
    minimum_radius: int = 6,
    maximum_radius: int = 27,
    target_regions: _TargetRegions | None = None,
) -> tuple[Coordinate, ...]:
    """Return a bounded target-relative candidate set for one group endpoint."""

    sum_other_x = sum(
        item.rounded_center[0] for item in group.endpoints if item.object_ref != endpoint.object_ref
    )
    sum_other_y = sum(
        item.rounded_center[1] for item in group.endpoints if item.object_ref != endpoint.object_ref
    )
    target_x, target_y = group.target.rounded_center
    lower_x = group.arity * target_x
    lower_y = group.arity * target_y
    raw: set[tuple[int, int]] = {
        (x, y)
        for x in range(lower_x - sum_other_x, lower_x + group.arity - sum_other_x)
        for y in range(lower_y - sum_other_y, lower_y + group.arity - sum_other_y)
    }
    for radius in range(minimum_radius, maximum_radius + 1):
        for rotation_index in range(16):
            rotation = (2 * math.pi * rotation_index) / 16
            raw.add(
                (
                    round(target_x + radius * math.cos(rotation)),
                    round(target_y + radius * math.sin(rotation)),
                )
            )
    current_sum_x = sum(item.rounded_center[0] for item in group.endpoints)
    current_sum_y = sum(item.rounded_center[1] for item in group.endpoints)
    final_overlap_cells = _final_marker_target_overlap_cells(scene, group)
    protected_target_regions = _marker_protected_target_regions(
        scene,
        group,
        supplied=target_regions,
    )
    candidates: list[Coordinate] = []
    for x, y in sorted(raw, key=lambda item: (item[1], item[0])):
        if endpoint.min_x <= x <= endpoint.max_x and endpoint.min_y <= y <= endpoint.max_y:
            continue
        potential = _marker_group_potential(
            group,
            sum_x=current_sum_x - endpoint.rounded_center[0] + x,
            sum_y=current_sum_y - endpoint.rounded_center[1] + y,
        )
        if not _endpoint_placement_is_open(
            scene,
            endpoint,
            x=x,
            y=y,
            permitted_occupied_cells=(final_overlap_cells if potential == 0 else frozenset()),
        ):
            continue
        if any(
            item.object_ref != endpoint.object_ref
            and max(
                abs(x - item.rounded_center[0]),
                abs(y - item.rounded_center[1]),
            )
            < 6
            for item in scene.endpoints
        ):
            continue
        prospective_endpoint = _translated_object_footprint(endpoint, center=(x, y))
        if any(
            prospective_endpoint & region
            for center, region in protected_target_regions
            if potential != 0 or center != group.target.rounded_center
        ):
            continue
        candidates.append(Coordinate(x, y))
    return tuple(candidates)


def _endpoint_placement_is_open(
    scene: VisualScene,
    endpoint: VisualObject,
    *,
    x: int,
    y: int,
    permitted_occupied_cells: frozenset[tuple[int, int]] = frozenset(),
    prospective_color: int | None = None,
    ignored_object_refs: frozenset[str] = frozenset(),
) -> bool:
    """Check the observed endpoint footprint, not its enclosing square.

    The endpoint's center can be rendered in a marker color and therefore be
    absent from its outer-color component.  It remains part of the placement
    footprint.  Obstacles outside the observed glyph corners do not block a
    placement, while any occupied cell under the actual glyph fails closed.
    """

    center_x, center_y = endpoint.rounded_center
    current_footprint = set(endpoint.cells)
    current_footprint.add((center_x, center_y))
    outer_footprint = {(cell_x - center_x, cell_y - center_y) for cell_x, cell_y in endpoint.cells}
    footprint = set(outer_footprint)
    footprint.add((0, 0))
    placement_is_open = all(
        0 < x + dx < scene.width - 1
        and 0 < y + dy < scene.height - 1
        and (
            scene.cells[y + dy][x + dx] == scene.background
            or (x + dx, y + dy) in current_footprint
            or (x + dx, y + dy) in permitted_occupied_cells
        )
        for dx, dy in footprint
    )
    if not placement_is_open:
        return False

    # Component identity must remain readable under the same bounded merge rule
    # used by perception.  An otherwise open placement can put the endpoint's
    # outer glyph close enough to a small same-color overlay that the parser
    # joins them and severs the visible marker relation.  The current glyph is
    # erased by the move and therefore is not a prospective neighbor.
    prospective_outer = {(x + dx, y + dy) for dx, dy in outer_footprint}
    effective_color = endpoint.color if prospective_color is None else prospective_color
    if len(prospective_outer) <= _SMALL_COMPONENT_FRAGMENT_AREA:
        for item in scene.objects:
            if (
                item.object_ref == endpoint.object_ref
                or item.object_ref in ignored_object_refs
                or item.color != effective_color
            ):
                continue
            separation = min(
                max(abs(left_x - right_x), abs(left_y - right_y))
                for left_x, left_y in prospective_outer
                for right_x, right_y in item.cells
            )
            # A renderer overlay can split a sparse ring between frames.  Use
            # the perception merge distance against every visible fragment,
            # rather than trusting the current compound bounding box to remain
            # intact after the action.
            if item.area > _SMALL_COMPONENT_FRAGMENT_AREA:
                if separation <= 1:
                    return False
                continue
            if separation <= _SMALL_COMPONENT_MERGE_DISTANCE:
                return False
    return True


def _chebyshev_distance(left: tuple[int, int], right: tuple[int, int]) -> int:
    return max(abs(left[0] - right[0]), abs(left[1] - right[1]))


def _raster_line_cells(
    start: tuple[int, int],
    end: tuple[int, int],
) -> frozenset[tuple[int, int]]:
    """Raster endpoint ``start`` to mediator ``end``, resolving ties toward ``start``."""

    delta_x = end[0] - start[0]
    delta_y = end[1] - start[1]
    steps = max(abs(delta_x), abs(delta_y))
    if steps == 0:
        return frozenset({start})

    def rounded_displacement(delta: int, step: int) -> int:
        """Round an exact displacement to nearest, with ties toward the start."""

        quotient, remainder = divmod(abs(delta) * step, steps)
        magnitude = quotient + int((2 * remainder) > steps)
        return magnitude if delta >= 0 else -magnitude

    return frozenset(
        (
            start[0] + rounded_displacement(delta_x, step),
            start[1] + rounded_displacement(delta_y, step),
        )
        for step in range(steps + 1)
    )


def _visible_target_regions(
    scene: VisualScene,
    *,
    same_group_raster_cells: frozenset[tuple[int, int]] = frozenset(),
) -> _TargetRegions:
    """Return target centers and their evidence-sensitive observed bounding boxes.

    A raw component wholly contained in the supplied group's observed mediator
    plus inferred centerline raster is not counted as independent collision
    evidence for that same group. Exact composite rings remain protected; this
    local role filter never rewrites a partial target from history.
    """

    certified_raw_target_refs: set[str] = set()
    if same_group_raster_cells:
        endpoint_counts = Counter(
            endpoint.center_cell
            for endpoint in scene.endpoints
            if endpoint.center_cell not in {scene.background, endpoint.color}
        )
        for marker_color, endpoint_count in endpoint_counts.items():
            mediators = tuple(
                mediator for mediator in scene.mediators if mediator.color == marker_color
            )
            targets = tuple(target for target in scene.targets if target.color == marker_color)
            if 2 <= endpoint_count <= 6 and len(mediators) == 1 and len(targets) == 1:
                certified_raw_target_refs.add(targets[0].object_ref)
    visible_targets = {
        (item.rounded_center, item.object_ref): item
        for item in (
            *(
                item
                for item in scene.targets
                if item.object_ref in certified_raw_target_refs
                or not same_group_raster_cells
                or not frozenset(item.cells) <= same_group_raster_cells
            ),
            *(candidate for candidate, _signature in _composite_sparse_targets(scene)),
        )
    }
    return tuple(
        (
            item.rounded_center,
            frozenset(
                (target_x, target_y)
                for target_y in range(item.min_y, item.max_y + 1)
                for target_x in range(item.min_x, item.max_x + 1)
            ),
        )
        for item in visible_targets.values()
    )


def _target_surface_signature(scene: VisualScene) -> _TargetSurfaceSignature:
    """Return exact raw and composite target evidence for projection checks."""

    raw = tuple(
        (
            "raw",
            item.rounded_center,
            tuple(sorted(item.cells)),
            tuple(sorted((x, y, scene.cells[y][x]) for x, y in item.cells)),
        )
        for item in scene.targets
    )
    composite = tuple(
        (
            "composite",
            item.rounded_center,
            tuple(sorted(item.cells)),
            tuple(sorted((x, y, scene.cells[y][x]) for x, y in item.cells)),
        )
        for item, _signature in _composite_sparse_targets(scene)
    )
    return tuple(sorted((*raw, *composite)))


def _child_isolation_target_surface_signature(
    scene: VisualScene,
    *,
    sink_center: tuple[int, int],
) -> _TargetSurfaceSignature:
    """Preserve exact surfaces while allowing a filled sink to stop looking hollow."""

    raw_sink_surfaces = tuple(
        tuple(sorted(item.cells)) for item in scene.targets if item.rounded_center == sink_center
    )
    exempt_surface = raw_sink_surfaces[0] if len(raw_sink_surfaces) == 1 else ()
    return tuple(
        item
        for item in _target_surface_signature(scene)
        if not (item[0] == "composite" and item[1] == sink_center and item[2] == exempt_surface)
    )


def _glyph_radius(item: VisualObject) -> int:
    center_x, center_y = item.rounded_center
    return max(
        center_x - item.min_x,
        item.max_x - center_x,
        center_y - item.min_y,
        item.max_y - center_y,
    )


_STATIC_COMPONENT_FOOTPRINT_MULTIPLIER = 4


def _object_footprint(item: VisualObject) -> frozenset[tuple[int, int]]:
    """Return the observed glyph cells, including a differently colored center."""

    return frozenset((*item.cells, item.rounded_center))


def _marker_dynamic_footprint(group: _EmbeddedMarkerGroup) -> frozenset[tuple[int, int]]:
    """Return the observed mediator plus inferred centerline raster for one group."""

    return frozenset(
        (
            *_object_footprint(group.mediator),
            *(
                cell
                for endpoint in group.endpoints
                for cell in _raster_line_cells(
                    endpoint.rounded_center,
                    group.mediator.rounded_center,
                )
            ),
        )
    )


def _marker_protected_target_regions(
    scene: VisualScene,
    group: _EmbeddedMarkerGroup,
    *,
    supplied: _TargetRegions | None = None,
) -> _TargetRegions:
    """Resolve one composite group's protected target surface."""

    if not group.is_composite:
        return ()
    if supplied is not None:
        return supplied
    return _visible_target_regions(
        scene,
        same_group_raster_cells=_marker_dynamic_footprint(group),
    )


def _marker_action_structure_is_readable(
    before_scene: VisualScene,
    after_scene: VisualScene,
    *,
    marker_color: int,
    arity: int,
    coordinate: Coordinate,
    active_color: int | None,
    plan_signature: str,
    target_separation_observed: bool,
) -> bool:
    """Confirm the exact movement or role transfer predicted by a marker plan."""

    if active_color is None:
        return False
    signature_parts = plan_signature.split(":")
    if len(signature_parts) < 4 or signature_parts[0] != "marker":
        return False
    kind = signature_parts[2]
    before_groups = tuple(
        group
        for group in _embedded_marker_groups(before_scene)
        if group.marker_color == marker_color and group.arity == arity
    )
    after_groups = tuple(
        group
        for group in _embedded_marker_groups(after_scene)
        if group.marker_color == marker_color and group.arity == arity
    )

    movement_kinds = {"improve", "solve", "stage", "separate"}
    if kind in movement_kinds:
        before_active = _embedded_marker_active_endpoint(
            before_scene,
            active_color=active_color,
        )
        if before_active is None:
            return False
        matching_before = tuple(
            group
            for group in before_groups
            if before_active.object_ref in {endpoint.object_ref for endpoint in group.endpoints}
        )
        if len(matching_before) != 1:
            return False
        before_group = matching_before[0]
        expected_centers = {
            (coordinate.x, coordinate.y)
            if endpoint.object_ref == before_active.object_ref
            else endpoint.rounded_center
            for endpoint in before_group.endpoints
        }
        matching_after = tuple(
            group
            for group in after_groups
            if {endpoint.rounded_center for endpoint in group.endpoints} == expected_centers
            and any(
                endpoint.rounded_center == (coordinate.x, coordinate.y)
                and endpoint.color == active_color
                for endpoint in group.endpoints
            )
        )
        return len(matching_after) == 1 and (kind != "separate" or target_separation_observed)

    role_transfer_kinds = {"activate", "defer", "rotate", "separate-activate"}
    if kind not in role_transfer_kinds:
        return False
    selected = tuple(
        (group, endpoint)
        for group in before_groups
        for endpoint in group.endpoints
        if endpoint.rounded_center == (coordinate.x, coordinate.y)
    )
    if len(selected) != 1:
        return False
    selected_group, selected_endpoint = selected[0]
    selected_centers = {endpoint.rounded_center for endpoint in selected_group.endpoints}
    matching_after = tuple(
        group
        for group in after_groups
        if {endpoint.rounded_center for endpoint in group.endpoints} == selected_centers
        and any(
            endpoint.rounded_center == (coordinate.x, coordinate.y)
            and endpoint.color == active_color
            for endpoint in group.endpoints
        )
    )
    if len(matching_after) != 1:
        return False
    before_active = _embedded_marker_active_endpoint(
        before_scene,
        active_color=active_color,
    )
    if before_active is None:
        return kind == "activate"
    if before_active.rounded_center == (coordinate.x, coordinate.y):
        return False
    return any(
        endpoint.rounded_center == before_active.rounded_center
        and endpoint.color == selected_endpoint.color
        for endpoint in after_scene.endpoints
    )


def _marker_target_separation_observed(
    before_scene: VisualScene,
    after_scene: VisualScene,
    *,
    marker_color: int,
    arity: int,
    coordinate: Coordinate,
) -> bool:
    """Confirm that one planned separation restored the exact target ring."""

    before_groups = tuple(
        group
        for group in _embedded_marker_groups(before_scene)
        if group.marker_color == marker_color and group.arity == arity
    )
    after_groups = tuple(
        group
        for group in _embedded_marker_groups(after_scene)
        if group.marker_color == marker_color and group.arity == arity
    )
    for before_group in before_groups:
        contaminant = _certified_marker_target_contaminant_in_scene(
            before_scene,
            before_group,
        )
        if contaminant is None:
            continue
        expected_centers = {
            (coordinate.x, coordinate.y)
            if endpoint.object_ref == contaminant.object_ref
            else endpoint.rounded_center
            for endpoint in before_group.endpoints
        }
        clean_target_cells = frozenset(before_group.target.cells) - {contaminant.rounded_center}
        target_colors = {cell: before_scene.cells[cell[1]][cell[0]] for cell in clean_target_cells}
        target_colors_preserved = all(
            after_scene.cells[y][x] == color for (x, y), color in target_colors.items()
        )
        raw_target_components_exact = all(
            not (item_cells := frozenset(item.cells)) & clean_target_cells
            or item_cells
            <= frozenset(cell for cell, color in target_colors.items() if color == item.color)
            for item in after_scene.objects
        )
        contaminant_center_cleared = (
            after_scene.cells[contaminant.rounded_center[1]][contaminant.rounded_center[0]]
            != marker_color
        )
        if any(
            {endpoint.rounded_center for endpoint in after_group.endpoints} == expected_centers
            and frozenset(after_group.target.cells) == clean_target_cells
            and target_colors_preserved
            and raw_target_components_exact
            and contaminant_center_cleared
            and _certified_marker_target_contaminant_in_scene(after_scene, after_group) is None
            for after_group in after_groups
        ):
            return True
    return False


def _marker_bootstrap_active_color(
    scene: VisualScene,
    *,
    coordinate: Coordinate,
) -> int | None:
    """Recover the active outer color from one returned marker bootstrap."""

    matches = tuple(
        endpoint
        for endpoint in scene.endpoints
        if endpoint.center_cell not in {scene.background, endpoint.color}
        and endpoint.rounded_center == (coordinate.x, coordinate.y)
    )
    if len(matches) != 1:
        return None
    return matches[0].color


def _translated_object_footprint(
    item: VisualObject,
    *,
    center: tuple[int, int],
) -> frozenset[tuple[int, int]]:
    old_x, old_y = item.rounded_center
    dx = center[0] - old_x
    dy = center[1] - old_y
    return frozenset((x + dx, y + dy) for x, y in _object_footprint(item))


def _compound_mediator_retains_component_identity(
    scene: VisualScene,
    group: _EmbeddedMarkerGroup,
    endpoint: VisualObject,
    *,
    coordinate: Coordinate,
    mediator_after: tuple[int, int],
) -> bool:
    """Preflight compound sectors through perception's exact merge relation."""

    mediator_before = group.mediator.rounded_center
    erased_cells = _object_footprint(group.mediator) | _object_footprint(endpoint)
    prospective_by_color: dict[int, list[tuple[int, int]]] = {}
    for cell_x, cell_y in group.mediator.cells:
        if (cell_x, cell_y) == mediator_before:
            continue
        color = scene.cells[cell_y][cell_x]
        prospective_by_color.setdefault(color, []).append(
            (
                mediator_after[0] + cell_x - mediator_before[0],
                mediator_after[1] + cell_y - mediator_before[1],
            )
        )

    for color, raw_prospective in prospective_by_color.items():
        prospective = tuple(sorted(raw_prospective, key=lambda cell: (cell[1], cell[0])))
        for item in scene.objects:
            if item.color != color:
                continue
            residual = tuple(cell for cell in item.cells if cell not in erased_cells)
            if residual and _small_components_would_merge(prospective, residual):
                return False
        if endpoint.center_cell == color and _small_components_would_merge(
            prospective,
            ((coordinate.x, coordinate.y),),
        ):
            return False
    return True


def _large_static_component_cells(
    scene: VisualScene,
    *,
    reference_footprint_size: int,
) -> frozenset[tuple[int, int]]:
    """Return a conservative observation-derived static-terrain candidate mask.

    Recognized marker glyphs remain dynamic.  An unrecognized component is
    protected only when it is at least four times the observed movable glyph,
    which excludes small overlays and HUD-like fragments without assigning
    meaning to a color or object identity.
    """

    minimum_area = _STATIC_COMPONENT_FOOTPRINT_MULTIPLIER * reference_footprint_size
    return frozenset(
        cell
        for item in scene.objects
        if item.role is VisualObjectRole.OTHER and item.area >= minimum_area
        for cell in item.cells
    )


def _marker_mediator_avoids_static_components(
    scene: VisualScene,
    group: _EmbeddedMarkerGroup,
    *,
    mediator_after: tuple[int, int],
    static_cells: frozenset[tuple[int, int]] | None = None,
) -> bool:
    """Reject prospective mediator footprints that overwrite large terrain."""

    current_footprint = _object_footprint(group.mediator)
    protected = (
        _large_static_component_cells(
            scene,
            reference_footprint_size=len(current_footprint),
        )
        if static_cells is None
        else static_cells
    )
    prospective = _translated_object_footprint(group.mediator, center=mediator_after)
    return not (prospective & (protected - current_footprint))


def _marker_mediator_remains_readable(
    scene: VisualScene,
    group: _EmbeddedMarkerGroup,
    endpoint: VisualObject,
    *,
    coordinate: Coordinate,
    mediator_after: tuple[int, int],
    final: bool,
    static_cells: frozenset[tuple[int, int]] | None = None,
    other_mediators: tuple[VisualObject, ...] | None = None,
    target_regions: _TargetRegions | None = None,
) -> bool:
    """Preserve component separation for the predicted mediator glyph."""

    if not _marker_mediator_avoids_static_components(
        scene,
        group,
        mediator_after=mediator_after,
        static_cells=static_cells,
    ):
        return False
    mediator_radius = _glyph_radius(group.mediator)
    if group.is_composite:
        if not final and not _compound_mediator_retains_component_identity(
            scene,
            group,
            endpoint,
            coordinate=coordinate,
            mediator_after=mediator_after,
        ):
            return False
        protected_target_regions = tuple(
            region
            for center, region in (
                _visible_target_regions(
                    scene,
                    same_group_raster_cells=_marker_dynamic_footprint(group),
                )
                if target_regions is None
                else target_regions
            )
            if not (final and center == group.target.rounded_center)
        )
        prospective_mediator = _translated_object_footprint(
            group.mediator,
            center=mediator_after,
        )
        prospective_endpoint_centers = tuple(
            (coordinate.x, coordinate.y)
            if candidate.object_ref == endpoint.object_ref
            else candidate.rounded_center
            for candidate in group.endpoints
        )
        prospective_connectors = frozenset(
            cell
            for endpoint_center in prospective_endpoint_centers
            for cell in _raster_line_cells(endpoint_center, mediator_after)
        )
        if any(
            (prospective_mediator | prospective_connectors) & region
            for region in protected_target_regions
        ):
            return False
    if group.is_composite and any(
        _chebyshev_distance(mediator_after, other.rounded_center)
        < mediator_radius + _glyph_radius(other) + 1
        for other in (
            tuple(
                candidate.mediator
                for candidate in _embedded_marker_groups(scene)
                if candidate.marker_color != group.marker_color
            )
            if other_mediators is None
            else other_mediators
        )
    ):
        return False
    if not final:
        prospective_mediator = _translated_object_footprint(
            group.mediator,
            center=mediator_after,
        )
        if any(
            _chebyshev_distance(mediator_cell, target_cell) <= 1
            for mediator_cell in prospective_mediator
            for target_cell in group.target.cells
        ):
            return False
    for candidate_endpoint in scene.endpoints:
        if final and candidate_endpoint.object_ref == endpoint.object_ref:
            continue
        endpoint_center = (
            (coordinate.x, coordinate.y)
            if candidate_endpoint.object_ref == endpoint.object_ref
            else candidate_endpoint.rounded_center
        )
        endpoint_clearance = mediator_radius + _glyph_radius(candidate_endpoint) + 1
        endpoint_distance = _chebyshev_distance(mediator_after, endpoint_center)
        if endpoint_distance < endpoint_clearance or (
            group.is_composite and endpoint_distance == endpoint_clearance
        ):
            return False
    return True


def _translated_visual_object(
    item: VisualObject,
    *,
    center: tuple[int, int],
    width: int,
    height: int,
) -> VisualObject:
    """Translate one observed glyph without inventing a different footprint."""

    old_center_x, old_center_y = item.rounded_center
    dx = center[0] - old_center_x
    dy = center[1] - old_center_y
    cells = tuple(
        sorted(
            ((cell_x + dx, cell_y + dy) for cell_x, cell_y in item.cells),
            key=lambda cell: (cell[1], cell[0]),
        )
    )
    min_x = min(cell[0] for cell in cells)
    min_y = min(cell[1] for cell in cells)
    max_x = max(cell[0] for cell in cells)
    max_y = max(cell[1] for cell in cells)
    return VisualObject(
        object_ref=_object_ref(item.color, cells),
        color=item.color,
        cells=cells,
        min_x=min_x,
        min_y=min_y,
        max_x=max_x,
        max_y=max_y,
        center_x=float(center[0]),
        center_y=float(center[1]),
        center_cell=item.center_cell,
        touches_edge=(min_x == 0 or min_y == 0 or max_x == width - 1 or max_y == height - 1),
        role=item.role,
    )


def _scene_after_marker_stage(
    scene: VisualScene,
    group: _EmbeddedMarkerGroup,
    endpoint: VisualObject,
    coordinate: Coordinate,
) -> tuple[VisualScene, _EmbeddedMarkerGroup] | None:
    """Project one observed-footprint relocation for bounded lookahead only."""

    resulting_sum_x = (
        sum(item.rounded_center[0] for item in group.endpoints)
        - endpoint.rounded_center[0]
        + coordinate.x
    )
    resulting_sum_y = (
        sum(item.rounded_center[1] for item in group.endpoints)
        - endpoint.rounded_center[1]
        + coordinate.y
    )
    mediator_center = (
        resulting_sum_x // group.arity,
        resulting_sum_y // group.arity,
    )
    if not _marker_mediator_avoids_static_components(
        scene,
        group,
        mediator_after=mediator_center,
    ):
        return None
    endpoint_after = _translated_visual_object(
        endpoint,
        center=(coordinate.x, coordinate.y),
        width=scene.width,
        height=scene.height,
    )
    mediator_after = _translated_visual_object(
        group.mediator,
        center=mediator_center,
        width=scene.width,
        height=scene.height,
    )
    mediator_before_center = group.mediator.rounded_center
    mediator_cell_colors = {
        (cell_x - mediator_before_center[0], cell_y - mediator_before_center[1]): scene.cells[
            cell_y
        ][cell_x]
        for cell_x, cell_y in group.mediator.cells
    }
    rows = [list(row) for row in scene.cells]
    for item in (endpoint, group.mediator):
        for cell_x, cell_y in (*item.cells, item.rounded_center):
            rows[cell_y][cell_x] = scene.background
    for cell_x, cell_y in endpoint_after.cells:
        rows[cell_y][cell_x] = endpoint_after.color
    endpoint_center_x, endpoint_center_y = endpoint_after.rounded_center
    rows[endpoint_center_y][endpoint_center_x] = endpoint_after.center_cell
    mediator_after_center = mediator_after.rounded_center
    for cell_x, cell_y in mediator_after.cells:
        offset = (cell_x - mediator_after_center[0], cell_y - mediator_after_center[1])
        rows[cell_y][cell_x] = mediator_cell_colors[offset]
    mediator_center_x, mediator_center_y = mediator_after_center
    rows[mediator_center_y][mediator_center_x] = mediator_after.center_cell
    projected_frame = GridFrame.from_rows(rows)
    replacements = {
        endpoint.object_ref: endpoint_after,
        group.mediator.object_ref: mediator_after,
    }
    projected_scene = VisualScene(
        frame_hash=str(projected_frame.digest),
        width=scene.width,
        height=scene.height,
        background=scene.background,
        objects=tuple(replacements.get(item.object_ref, item) for item in scene.objects),
        cells=projected_frame.cells,
    )
    projected_group = _EmbeddedMarkerGroup(
        marker_color=group.marker_color,
        endpoints=tuple(
            endpoint_after if item.object_ref == endpoint.object_ref else item
            for item in group.endpoints
        ),
        mediator=mediator_after,
        target=group.target,
    )
    return projected_scene, projected_group


def _scene_after_marker_role_switch(
    scene: VisualScene,
    group: _EmbeddedMarkerGroup,
    active: VisualObject,
    selected: VisualObject,
) -> tuple[VisualScene, _EmbeddedMarkerGroup, VisualObject] | None:
    """Project the visible outer-color swap caused by selecting a fixed endpoint.

    A continuation for a fixed endpoint must be checked with the outer color it
    will have *after* becoming active.  Checking its current fixed color can
    falsely reject a legal placement because nearby fixed endpoints would be
    same-color fragments before the role swap but not afterward.  Re-extracting
    the projected frame also fails closed when the swap itself makes a marker
    group structurally unreadable.
    """

    if active.object_ref == selected.object_ref or active.color == selected.color:
        return None
    endpoint_refs = {item.object_ref for item in scene.endpoints}
    if active.object_ref not in endpoint_refs or selected.object_ref not in endpoint_refs:
        return None

    rows = [list(row) for row in scene.cells]
    for endpoint, outer_color in ((active, selected.color), (selected, active.color)):
        for cell_x, cell_y in endpoint.cells:
            rows[cell_y][cell_x] = outer_color
        center_x, center_y = endpoint.rounded_center
        rows[center_y][center_x] = endpoint.center_cell

    projected_scene = extract_visual_scene(GridFrame.from_rows(rows))
    expected_centers = {item.rounded_center for item in group.endpoints}
    projected_groups = tuple(
        candidate
        for candidate in _embedded_marker_groups(projected_scene)
        if candidate.marker_color == group.marker_color
        and candidate.arity == group.arity
        and {item.rounded_center for item in candidate.endpoints} == expected_centers
    )
    if len(projected_groups) != 1:
        return None
    projected_group = projected_groups[0]
    projected_active = tuple(
        endpoint
        for endpoint in projected_group.endpoints
        if endpoint.rounded_center == selected.rounded_center and endpoint.color == active.color
    )
    if len(projected_active) != 1:
        return None
    return projected_scene, projected_group, projected_active[0]


def _best_marker_target_separation(
    scene: VisualScene,
    group: _EmbeddedMarkerGroup,
    endpoint: VisualObject,
    *,
    rejected_signatures: set[str],
) -> Coordinate | None:
    """Find the smallest move that restores a contaminated sparse target."""

    contaminant = _certified_marker_target_contaminant_in_scene(scene, group)
    if contaminant is None or contaminant.object_ref != endpoint.object_ref:
        return None
    clean_target_cells = frozenset(group.target.cells) - {endpoint.rounded_center}
    sum_x = sum(item.rounded_center[0] for item in group.endpoints)
    sum_y = sum(item.rounded_center[1] for item in group.endpoints)
    static_cells = _large_static_component_cells(
        scene,
        reference_footprint_size=len(_object_footprint(group.mediator)),
    )
    other_mediators = (
        tuple(
            candidate.mediator
            for candidate in _embedded_marker_groups(scene)
            if candidate.marker_color != group.marker_color
        )
        if group.is_composite
        else ()
    )
    target_regions = (
        _visible_target_regions(
            scene,
            same_group_raster_cells=_marker_dynamic_footprint(group),
        )
        if group.is_composite
        else ()
    )
    best: tuple[int, int, int, int, Coordinate] | None = None
    relocation_candidates = _marker_relocation_candidates(
        scene,
        group,
        endpoint,
        target_regions=target_regions,
    )
    for coordinate in relocation_candidates:
        signature = f"marker:{group.marker_color}:separate:{coordinate.x},{coordinate.y}"
        if signature in rejected_signatures:
            continue
        resulting_sum_x = sum_x - endpoint.rounded_center[0] + coordinate.x
        resulting_sum_y = sum_y - endpoint.rounded_center[1] + coordinate.y
        mediator_after = (
            resulting_sum_x // group.arity,
            resulting_sum_y // group.arity,
        )
        if group.is_composite:
            remains_readable = _marker_mediator_remains_readable(
                scene,
                group,
                endpoint,
                coordinate=coordinate,
                mediator_after=mediator_after,
                final=False,
                static_cells=static_cells,
                other_mediators=other_mediators,
                target_regions=target_regions,
            )
        else:
            remains_readable = _marker_mediator_remains_readable(
                scene,
                group,
                endpoint,
                coordinate=coordinate,
                mediator_after=mediator_after,
                final=False,
                static_cells=static_cells,
            )
        if not remains_readable:
            continue
        projection = _scene_after_marker_stage(scene, group, endpoint, coordinate)
        if projection is None:
            continue
        projected_scene, _projected_group = projection
        refreshed_scene = extract_visual_scene(GridFrame(projected_scene.cells))
        expected_centers = {
            (coordinate.x, coordinate.y)
            if candidate.object_ref == endpoint.object_ref
            else candidate.rounded_center
            for candidate in group.endpoints
        }
        refreshed_groups = tuple(
            candidate
            for candidate in _embedded_marker_groups(refreshed_scene)
            if candidate.marker_color == group.marker_color
            and candidate.arity == group.arity
            and {item.rounded_center for item in candidate.endpoints} == expected_centers
            and frozenset(candidate.target.cells) == clean_target_cells
            and _certified_marker_target_contaminant_in_scene(refreshed_scene, candidate) is None
        )
        if len(refreshed_groups) != 1:
            continue
        refreshed_group = refreshed_groups[0]
        refreshed_sum_x = sum(item.rounded_center[0] for item in refreshed_group.endpoints)
        refreshed_sum_y = sum(item.rounded_center[1] for item in refreshed_group.endpoints)
        refreshed_potential = _marker_group_potential(
            refreshed_group,
            sum_x=refreshed_sum_x,
            sum_y=refreshed_sum_y,
        )
        displacement = (coordinate.x - endpoint.rounded_center[0]) ** 2 + (
            coordinate.y - endpoint.rounded_center[1]
        ) ** 2
        candidate = (
            displacement,
            refreshed_potential,
            coordinate.y,
            coordinate.x,
            coordinate,
        )
        if best is None or candidate[:4] < best[:4]:
            best = candidate
    return None if best is None else best[4]


def _scene_after_marker_reacquisition(
    scene: VisualScene,
    group: _EmbeddedMarkerGroup,
    selected: VisualObject,
    *,
    active_color: int,
) -> tuple[VisualScene, _EmbeddedMarkerGroup, VisualObject] | None:
    """Project selecting a visible endpoint after its old active peer collapsed.

    Exact target contact can consume the previously active endpoint's readable
    group while leaving other groups visible.  The retained active outer color
    and the observed one-click role-transfer mechanism are sufficient to test
    a local continuation without reconstructing the consumed endpoint.
    """

    if selected.color == active_color or selected.object_ref not in {
        endpoint.object_ref for endpoint in scene.endpoints
    }:
        return None
    rows = [list(row) for row in scene.cells]
    for cell_x, cell_y in selected.cells:
        rows[cell_y][cell_x] = active_color
    center_x, center_y = selected.rounded_center
    rows[center_y][center_x] = selected.center_cell

    projected_scene = extract_visual_scene(GridFrame.from_rows(rows))
    expected_centers = {item.rounded_center for item in group.endpoints}
    projected_groups = tuple(
        candidate
        for candidate in _embedded_marker_groups(projected_scene)
        if candidate.marker_color == group.marker_color
        and candidate.arity == group.arity
        and {item.rounded_center for item in candidate.endpoints} == expected_centers
    )
    if len(projected_groups) != 1:
        return None
    projected_group = projected_groups[0]
    projected_active = tuple(
        endpoint
        for endpoint in projected_group.endpoints
        if endpoint.rounded_center == selected.rounded_center and endpoint.color == active_color
    )
    if len(projected_active) != 1:
        return None
    return projected_scene, projected_group, projected_active[0]


def _best_marker_relocation_after_reacquisition(
    scene: VisualScene,
    group: _EmbeddedMarkerGroup,
    selected: VisualObject,
    *,
    active_color: int,
    rejected_signatures: set[str],
) -> tuple[int, Coordinate] | None:
    projection = _scene_after_marker_reacquisition(
        scene,
        group,
        selected,
        active_color=active_color,
    )
    if projection is None:
        return None
    projected_scene, projected_group, projected_active = projection
    return _best_marker_relocation(
        projected_scene,
        projected_group,
        projected_active,
        rejected_signatures=rejected_signatures,
    )


def _best_marker_separation_after_reacquisition(
    scene: VisualScene,
    group: _EmbeddedMarkerGroup,
    selected: VisualObject,
    *,
    active_color: int,
    rejected_signatures: set[str],
) -> tuple[int, Coordinate] | None:
    """Certify a target-restoring continuation after selecting one fixed endpoint."""

    projection = _scene_after_marker_reacquisition(
        scene,
        group,
        selected,
        active_color=active_color,
    )
    if projection is None:
        return None
    projected_scene, projected_group, projected_active = projection
    separation = _best_marker_target_separation(
        projected_scene,
        projected_group,
        projected_active,
        rejected_signatures=rejected_signatures,
    )
    if separation is None:
        return None
    resulting_sum_x = (
        sum(item.rounded_center[0] for item in projected_group.endpoints)
        - projected_active.rounded_center[0]
        + separation.x
    )
    resulting_sum_y = (
        sum(item.rounded_center[1] for item in projected_group.endpoints)
        - projected_active.rounded_center[1]
        + separation.y
    )
    return (
        _marker_group_potential(
            projected_group,
            sum_x=resulting_sum_x,
            sum_y=resulting_sum_y,
        ),
        separation,
    )


def _best_marker_relocation_after_switch(
    scene: VisualScene,
    group: _EmbeddedMarkerGroup,
    active: VisualObject,
    selected: VisualObject,
    *,
    rejected_signatures: set[str],
    allow_extended: bool = True,
    target_regions: _TargetRegions | None = None,
) -> tuple[int, Coordinate] | None:
    projection = _scene_after_marker_role_switch(scene, group, active, selected)
    if projection is None:
        return None
    projected_scene, projected_group, projected_active = projection
    if target_regions is not None and (
        projected_group.target.rounded_center != group.target.rounded_center
        or frozenset(projected_group.target.cells) != frozenset(group.target.cells)
    ):
        # A shallow target surface belongs only to the target identity observed
        # before staging.  Never carry it through a role-switch projection that
        # reparses the marker against a different target.
        return None
    return _best_marker_relocation(
        projected_scene,
        projected_group,
        projected_active,
        rejected_signatures=rejected_signatures,
        allow_extended=allow_extended,
        target_regions=target_regions,
    )


def _best_marker_separation_after_switch(
    scene: VisualScene,
    group: _EmbeddedMarkerGroup,
    active: VisualObject,
    selected: VisualObject,
    *,
    rejected_signatures: set[str],
) -> tuple[int, Coordinate] | None:
    """Certify target separation after transferring a visible active role."""

    projection = _scene_after_marker_role_switch(scene, group, active, selected)
    if projection is None:
        return None
    projected_scene, projected_group, projected_active = projection
    separation = _best_marker_target_separation(
        projected_scene,
        projected_group,
        projected_active,
        rejected_signatures=rejected_signatures,
    )
    if separation is None:
        return None
    resulting_sum_x = (
        sum(item.rounded_center[0] for item in projected_group.endpoints)
        - projected_active.rounded_center[0]
        + separation.x
    )
    resulting_sum_y = (
        sum(item.rounded_center[1] for item in projected_group.endpoints)
        - projected_active.rounded_center[1]
        + separation.y
    )
    return (
        _marker_group_potential(
            projected_group,
            sum_x=resulting_sum_x,
            sum_y=resulting_sum_y,
        ),
        separation,
    )


def _best_marker_staging_after_switch(
    scene: VisualScene,
    group: _EmbeddedMarkerGroup,
    active: VisualObject,
    selected: VisualObject,
    *,
    rejected_signatures: set[str],
) -> Coordinate | None:
    projection = _scene_after_marker_role_switch(scene, group, active, selected)
    if projection is None:
        return None
    projected_scene, projected_group, projected_active = projection
    return _best_marker_staging_relocation(
        projected_scene,
        projected_group,
        projected_active,
        rejected_signatures=rejected_signatures,
    )


def _best_marker_staging_relocation(
    scene: VisualScene,
    group: _EmbeddedMarkerGroup,
    endpoint: VisualObject,
    *,
    rejected_signatures: set[str],
) -> Coordinate | None:
    """Find one bounded stage that makes a post-switch decrease feasible."""

    sum_x = sum(item.rounded_center[0] for item in group.endpoints)
    sum_y = sum(item.rounded_center[1] for item in group.endpoints)
    current = _marker_group_potential(group, sum_x=sum_x, sum_y=sum_y)
    static_cells = _large_static_component_cells(
        scene,
        reference_footprint_size=len(_object_footprint(group.mediator)),
    )
    other_mediators = (
        tuple(
            candidate.mediator
            for candidate in _embedded_marker_groups(scene)
            if candidate.marker_color != group.marker_color
        )
        if group.is_composite
        else ()
    )
    target_regions = (
        _visible_target_regions(
            scene,
            same_group_raster_cells=_marker_dynamic_footprint(group),
        )
        if group.is_composite
        else ()
    )
    best: tuple[int, int, int, str, Coordinate] | None = None
    relocation_candidates = _marker_relocation_candidates(
        scene,
        group,
        endpoint,
        target_regions=target_regions,
    )
    for coordinate in relocation_candidates:
        resulting_sum_x = sum_x - endpoint.rounded_center[0] + coordinate.x
        resulting_sum_y = sum_y - endpoint.rounded_center[1] + coordinate.y
        stage_potential = _marker_group_potential(
            group,
            sum_x=resulting_sum_x,
            sum_y=resulting_sum_y,
        )
        if (
            _marker_target_identity_constraint(group.marker_color) in rejected_signatures
            and stage_potential != 0
            and _marker_center_would_merge_with_target(
                scene,
                group,
                endpoint,
                center=(coordinate.x, coordinate.y),
            )
        ):
            continue
        if stage_potential < current:
            continue
        signature = f"marker:{group.marker_color}:stage:{coordinate.x},{coordinate.y}"
        ordinary_kind = "solve" if stage_potential == 0 else "improve"
        ordinary_signature = (
            f"marker:{group.marker_color}:{ordinary_kind}:{coordinate.x},{coordinate.y}"
        )
        if signature in rejected_signatures or ordinary_signature in rejected_signatures:
            continue
        mediator_after = (
            resulting_sum_x // group.arity,
            resulting_sum_y // group.arity,
        )
        if group.is_composite:
            remains_readable = _marker_mediator_remains_readable(
                scene,
                group,
                endpoint,
                coordinate=coordinate,
                mediator_after=mediator_after,
                final=False,
                static_cells=static_cells,
                other_mediators=other_mediators,
                target_regions=target_regions,
            )
        else:
            remains_readable = _marker_mediator_remains_readable(
                scene,
                group,
                endpoint,
                coordinate=coordinate,
                mediator_after=mediator_after,
                final=False,
                static_cells=static_cells,
            )
        if not remains_readable:
            continue
        projection = _scene_after_marker_stage(
            scene,
            group,
            endpoint,
            coordinate,
        )
        if projection is None:
            continue
        projected_scene, projected_group = projection
        projected_endpoint = projected_group.endpoints[group.endpoints.index(endpoint)]
        for switch_endpoint in projected_group.endpoints:
            if switch_endpoint.object_ref == projected_endpoint.object_ref:
                continue
            followup = _best_marker_relocation_after_switch(
                projected_scene,
                projected_group,
                projected_endpoint,
                switch_endpoint,
                rejected_signatures=rejected_signatures,
                allow_extended=False,
                # The stage projection deliberately translates only observed
                # endpoint and mediator glyphs; it cannot rerender connectors.
                # Carry the starting observation's protected regions through
                # this one shallow certificate, then recompute after the real
                # environment returns the staged consequence.
                target_regions=target_regions,
            )
            if followup is None:
                continue
            followup_potential, _followup_coordinate = followup
            if followup_potential >= current:
                continue
            candidate = (
                followup_potential,
                stage_potential - current,
                coordinate.y,
                switch_endpoint.object_ref,
                coordinate,
            )
            if best is None or candidate[:4] < best[:4]:
                best = candidate
    return None if best is None else best[4]


def _best_marker_relocation(
    scene: VisualScene,
    group: _EmbeddedMarkerGroup,
    endpoint: VisualObject,
    *,
    rejected_signatures: set[str],
    allow_extended: bool = True,
    target_regions: _TargetRegions | None = None,
) -> tuple[int, Coordinate] | None:
    sum_x = sum(item.rounded_center[0] for item in group.endpoints)
    sum_y = sum(item.rounded_center[1] for item in group.endpoints)
    current = _marker_group_potential(group, sum_x=sum_x, sum_y=sum_y)
    static_cells = _large_static_component_cells(
        scene,
        reference_footprint_size=len(_object_footprint(group.mediator)),
    )
    other_mediators = (
        tuple(
            candidate.mediator
            for candidate in _embedded_marker_groups(scene)
            if candidate.marker_color != group.marker_color
        )
        if group.is_composite
        else ()
    )
    protected_target_regions = _marker_protected_target_regions(
        scene,
        group,
        supplied=target_regions,
    )
    ordinary = _marker_relocation_candidates(
        scene,
        group,
        endpoint,
        target_regions=protected_target_regions,
    )
    candidate_batches = [ordinary]
    if allow_extended:
        board_diagonal = math.ceil(math.hypot(scene.width - 1, scene.height - 1))
        candidate_batches.append(
            _marker_relocation_candidates(
                scene,
                group,
                endpoint,
                minimum_radius=28,
                maximum_radius=board_diagonal,
                target_regions=protected_target_regions,
            )
        )
    best: tuple[int, int, int, int, Coordinate] | None = None
    for coordinates in candidate_batches:
        for coordinate in coordinates:
            if (
                endpoint.min_x <= coordinate.x <= endpoint.max_x
                and endpoint.min_y <= coordinate.y <= endpoint.max_y
            ):
                # ACTION6 within the active glyph's observed bounding box does
                # not provide evidence of a relocation.  Even an unpainted
                # corner can remain inside the input hitbox and only animate
                # the rendered endpoint in place.
                continue
            resulting_sum_x = sum_x - endpoint.rounded_center[0] + coordinate.x
            resulting_sum_y = sum_y - endpoint.rounded_center[1] + coordinate.y
            potential = _marker_group_potential(
                group,
                sum_x=resulting_sum_x,
                sum_y=resulting_sum_y,
            )
            if (
                _marker_target_identity_constraint(group.marker_color) in rejected_signatures
                and potential != 0
                and _marker_center_would_merge_with_target(
                    scene,
                    group,
                    endpoint,
                    center=(coordinate.x, coordinate.y),
                )
            ):
                continue
            mediator_after = (
                resulting_sum_x // group.arity,
                resulting_sum_y // group.arity,
            )
            if group.is_composite:
                remains_readable = _marker_mediator_remains_readable(
                    scene,
                    group,
                    endpoint,
                    coordinate=coordinate,
                    mediator_after=mediator_after,
                    final=potential == 0,
                    static_cells=static_cells,
                    other_mediators=other_mediators,
                    target_regions=protected_target_regions,
                )
            else:
                remains_readable = _marker_mediator_remains_readable(
                    scene,
                    group,
                    endpoint,
                    coordinate=coordinate,
                    mediator_after=mediator_after,
                    final=potential == 0,
                    static_cells=static_cells,
                )
            if not remains_readable:
                continue
            signature_kind = "solve" if potential == 0 else "improve"
            signature = (
                f"marker:{group.marker_color}:{signature_kind}:{coordinate.x},{coordinate.y}"
            )
            if potential >= current or signature in rejected_signatures:
                continue
            target_overlap = len(
                _translated_object_footprint(
                    endpoint,
                    center=(coordinate.x, coordinate.y),
                )
                & frozenset(group.target.cells)
            )
            candidate = (
                potential,
                target_overlap,
                coordinate.y,
                coordinate.x,
                coordinate,
            )
            if best is None or candidate[:4] < best[:4]:
                best = candidate
        if best is not None:
            break
    return None if best is None else (best[0], best[4])


def _marker_structural_action_key(
    scene: VisualScene,
    active: VisualObject,
    plan_signature: str,
) -> str:
    """Hash marker geometry, active role, and action while ignoring HUD animation."""

    groups = _embedded_marker_groups(scene)
    parts = [f"active:{active.rounded_center[0]},{active.rounded_center[1]}"]
    for group in groups:
        endpoints = ";".join(
            f"{item.rounded_center[0]},{item.rounded_center[1]}"
            for item in sorted(group.endpoints, key=lambda item: item.rounded_center)
        )
        parts.append(
            f"group:{group.marker_color}:{group.arity}:{endpoints}:"
            f"m={group.mediator.rounded_center[0]},{group.mediator.rounded_center[1]}:"
            f"t={group.target.rounded_center[0]},{group.target.rounded_center[1]}"
        )
    parts.append(f"action:{plan_signature}")
    return hashlib.sha256("|".join(parts).encode("ascii")).hexdigest()


def _best_marker_group_transfer(
    scene: VisualScene,
    groups: tuple[_EmbeddedMarkerGroup, ...],
    active: VisualObject,
    *,
    rejected_signatures: set[str],
) -> tuple[_EmbeddedMarkerGroup, VisualObject] | None:
    """Choose a group switch only when a safe strict continuation is visible."""

    best: tuple[int, int, int, str, _EmbeddedMarkerGroup, VisualObject] | None = None
    for group in groups:
        for endpoint in group.endpoints:
            if endpoint.object_ref == active.object_ref:
                continue
            coordinate = Coordinate(*endpoint.rounded_center)
            role_transfer_signatures = {
                f"marker:{group.marker_color}:activate:{coordinate.x},{coordinate.y}",
                f"marker:{group.marker_color}:defer:{coordinate.x},{coordinate.y}",
                f"marker:{group.marker_color}:rotate:{coordinate.x},{coordinate.y}",
            }
            if role_transfer_signatures & rejected_signatures:
                continue
            prospective = _best_marker_relocation_after_switch(
                scene,
                group,
                active,
                endpoint,
                rejected_signatures=rejected_signatures,
            )
            if prospective is None:
                prospective = _best_marker_separation_after_switch(
                    scene,
                    group,
                    active,
                    endpoint,
                    rejected_signatures=rejected_signatures,
                )
                if prospective is None:
                    continue
            potential, _followup = prospective
            candidate = (
                potential,
                coordinate.y,
                coordinate.x,
                endpoint.object_ref,
                group,
                endpoint,
            )
            if best is None or candidate[:4] < best[:4]:
                best = candidate
    return None if best is None else (best[4], best[5])


def _best_marker_group_reacquisition(
    scene: VisualScene,
    groups: tuple[_EmbeddedMarkerGroup, ...],
    *,
    active_color: int,
    rejected_signatures: set[str],
) -> tuple[_EmbeddedMarkerGroup, VisualObject] | None:
    """Choose a visible group with a safe continuation after local collapse."""

    best: tuple[int, int, int, str, _EmbeddedMarkerGroup, VisualObject] | None = None
    for group in groups:
        for endpoint in group.endpoints:
            coordinate = Coordinate(*endpoint.rounded_center)
            signature = f"marker:{group.marker_color}:activate:{coordinate.x},{coordinate.y}"
            if signature in rejected_signatures:
                continue
            prospective = _best_marker_relocation_after_reacquisition(
                scene,
                group,
                endpoint,
                active_color=active_color,
                rejected_signatures=rejected_signatures,
            )
            if prospective is None:
                prospective = _best_marker_separation_after_reacquisition(
                    scene,
                    group,
                    endpoint,
                    active_color=active_color,
                    rejected_signatures=rejected_signatures,
                )
                if prospective is None:
                    continue
            potential, _followup = prospective
            candidate = (
                potential,
                coordinate.y,
                coordinate.x,
                endpoint.object_ref,
                group,
                endpoint,
            )
            if best is None or candidate[:4] < best[:4]:
                best = candidate
    return None if best is None else (best[4], best[5])


def _embedded_marker_plan(
    scene: VisualScene,
    *,
    level_index: int,
    active_color: int | None,
    staged_marker_color: int | None,
    rejected_signatures: set[str],
    allow_reacquisition: bool = False,
) -> PlannedClick | None:
    """Plan one direct, target-relative action from visible marker evidence.

    A previously observed active outer color controls when it identifies one
    marked endpoint.  Otherwise the globally unique outer color is used only
    when another outer color repeats.  If the active endpoint remains
    ambiguous, the caller must learn it with one bounded open-space probe.
    The caller re-reads the next frame before planning again, so coordinates
    and object identities never become a cross-action script.
    """

    groups = _embedded_marker_groups(scene)
    if not groups:
        return None
    unresolved = tuple(
        group for group in groups if group.mediator.rounded_center != group.target.rounded_center
    )
    if not unresolved:
        return None
    active = _embedded_marker_active_endpoint(scene, active_color=active_color)
    if active is None:
        if not allow_reacquisition or active_color is None:
            return None
        reacquisition = _best_marker_group_reacquisition(
            scene,
            unresolved,
            active_color=active_color,
            rejected_signatures=rejected_signatures,
        )
        if reacquisition is None:
            return None
        group, selected = reacquisition
        identity = f"marker|{level_index}|{group.marker_color}|{group.arity}|{scene.frame_hash}"
        mechanic_ref = "affine-marker:" + hashlib.sha256(identity.encode("ascii")).hexdigest()[:20]
        plan_id = (
            "visual-plan:"
            + hashlib.sha256(f"{mechanic_ref}|local".encode("ascii")).hexdigest()[:20]
        )
        coordinate = Coordinate(*selected.rounded_center)
        return PlannedClick(
            coordinate=coordinate,
            purpose=VisualActionPurpose.PROBE,
            expectation=(
                "reacquire the active role in a visible unresolved group after exact "
                "local target contact"
            ),
            mechanic_ref=mechanic_ref,
            plan_id=plan_id,
            plan_signature=(f"marker:{group.marker_color}:activate:{coordinate.x},{coordinate.y}"),
            target_center=group.target.rounded_center,
            mediator_color=group.marker_color,
            arity=group.arity,
        )
    active_group = next(
        (
            group
            for group in unresolved
            if active.object_ref in {item.object_ref for item in group.endpoints}
        ),
        None,
    )
    staged_group = next(
        (group for group in unresolved if group.marker_color == staged_marker_color),
        None,
    )
    if staged_marker_color is not None:
        if staged_group is None or active_group != staged_group:
            return None
        group = staged_group
    else:
        group = active_group or unresolved[0]
    identity = f"marker|{level_index}|{group.marker_color}|{group.arity}|{scene.frame_hash}"
    mechanic_ref = "affine-marker:" + hashlib.sha256(identity.encode("ascii")).hexdigest()[:20]
    plan_id = (
        "visual-plan:" + hashlib.sha256(f"{mechanic_ref}|local".encode("ascii")).hexdigest()[:20]
    )

    if staged_marker_color is not None:
        staged_switch_candidates: list[tuple[int, str, VisualObject]] = []
        for candidate_endpoint in group.endpoints:
            if candidate_endpoint.object_ref == active.object_ref:
                continue
            coordinate = Coordinate(*candidate_endpoint.rounded_center)
            signature = f"marker:{group.marker_color}:rotate:{coordinate.x},{coordinate.y}"
            if signature in rejected_signatures:
                continue
            prospective = _best_marker_relocation_after_switch(
                scene,
                group,
                active,
                candidate_endpoint,
                rejected_signatures=rejected_signatures,
            )
            if prospective is not None:
                staged_switch_candidates.append(
                    (prospective[0], candidate_endpoint.object_ref, candidate_endpoint)
                )
        if not staged_switch_candidates:
            return None
        _potential, _object_ref, selected = min(
            staged_switch_candidates,
            key=lambda item: item[:2],
        )
        coordinate = Coordinate(*selected.rounded_center)
        signature = f"marker:{group.marker_color}:rotate:{coordinate.x},{coordinate.y}"
        return PlannedClick(
            coordinate=coordinate,
            purpose=VisualActionPurpose.PROBE,
            expectation=(
                "transfer the active role after bounded marker staging before recomputing"
            ),
            mechanic_ref=mechanic_ref,
            plan_id=plan_id,
            plan_signature=signature,
            target_center=group.target.rounded_center,
            mediator_color=group.marker_color,
            arity=group.arity,
        )

    if active_group is None:
        transfer = _best_marker_group_transfer(
            scene,
            unresolved,
            active,
            rejected_signatures=rejected_signatures,
        )
        if transfer is None:
            return None
        group, selected = transfer
        identity = f"marker|{level_index}|{group.marker_color}|{group.arity}|{scene.frame_hash}"
        mechanic_ref = "affine-marker:" + hashlib.sha256(identity.encode("ascii")).hexdigest()[:20]
        plan_id = (
            "visual-plan:"
            + hashlib.sha256(f"{mechanic_ref}|local".encode("ascii")).hexdigest()[:20]
        )
        coordinate = Coordinate(*selected.rounded_center)
        signature = f"marker:{group.marker_color}:activate:{coordinate.x},{coordinate.y}"
        return PlannedClick(
            coordinate=coordinate,
            purpose=VisualActionPurpose.PROBE,
            expectation=(
                "transfer the active role to a fixed endpoint with the matched marker and "
                "a bounded collision-safe continuation"
            ),
            mechanic_ref=mechanic_ref,
            plan_id=plan_id,
            plan_signature=signature,
            target_center=group.target.rounded_center,
            mediator_color=group.marker_color,
            arity=group.arity,
        )

    relocation = _best_marker_relocation(
        scene,
        group,
        active,
        rejected_signatures=rejected_signatures,
    )
    exact_switch_candidates: list[tuple[str, VisualObject]] = []
    if relocation is None or relocation[0] != 0:
        for endpoint in group.endpoints:
            if endpoint.object_ref == active.object_ref:
                continue
            coordinate = Coordinate(*endpoint.rounded_center)
            signature = f"marker:{group.marker_color}:rotate:{coordinate.x},{coordinate.y}"
            if signature in rejected_signatures:
                continue
            prospective = _best_marker_relocation_after_switch(
                scene,
                group,
                active,
                endpoint,
                rejected_signatures=rejected_signatures,
            )
            if prospective is not None and prospective[0] == 0:
                exact_switch_candidates.append((endpoint.object_ref, endpoint))
    if exact_switch_candidates:
        _object_ref_value, selected = min(exact_switch_candidates, key=lambda item: item[0])
        coordinate = Coordinate(*selected.rounded_center)
        signature = f"marker:{group.marker_color}:rotate:{coordinate.x},{coordinate.y}"
        return PlannedClick(
            coordinate=coordinate,
            purpose=VisualActionPurpose.PROBE,
            expectation=(
                "transfer the active role within the same marker group to expose an exact "
                "target-relative relocation"
            ),
            mechanic_ref=mechanic_ref,
            plan_id=plan_id,
            plan_signature=signature,
            target_center=group.target.rounded_center,
            mediator_color=group.marker_color,
            arity=group.arity,
        )

    if relocation is not None:
        potential, coordinate = relocation
        signature_kind = "solve" if potential == 0 else "improve"
        signature = f"marker:{group.marker_color}:{signature_kind}:{coordinate.x},{coordinate.y}"
        return PlannedClick(
            coordinate=coordinate,
            purpose=VisualActionPurpose.PROGRESS,
            expectation=(
                "place the active endpoint at the marker-group affine solution"
                if potential == 0
                else "strictly reduce the marker-group floor-centroid residual"
            ),
            mechanic_ref=mechanic_ref,
            plan_id=plan_id,
            plan_signature=signature,
            target_center=group.target.rounded_center,
            mediator_color=group.marker_color,
            arity=group.arity,
            completes_local_target=potential == 0,
        )

    switch_candidates: list[tuple[int, str, VisualObject]] = []
    fallback_stage_switch_candidates: list[tuple[int, str, VisualObject]] = []
    for endpoint in group.endpoints:
        if endpoint.object_ref == active.object_ref:
            continue
        coordinate = Coordinate(*endpoint.rounded_center)
        signature = f"marker:{group.marker_color}:rotate:{coordinate.x},{coordinate.y}"
        if signature in rejected_signatures:
            continue
        prospective = _best_marker_relocation_after_switch(
            scene,
            group,
            active,
            endpoint,
            rejected_signatures=rejected_signatures,
        )
        if prospective is not None:
            switch_candidates.append((prospective[0], endpoint.object_ref, endpoint))
            continue
        staged_coordinate = _best_marker_staging_after_switch(
            scene,
            group,
            active,
            endpoint,
            rejected_signatures=rejected_signatures,
        )
        if staged_coordinate is None:
            continue
        sum_x = sum(item.rounded_center[0] for item in group.endpoints)
        sum_y = sum(item.rounded_center[1] for item in group.endpoints)
        staged_sum_x = sum_x - endpoint.rounded_center[0] + staged_coordinate.x
        staged_sum_y = sum_y - endpoint.rounded_center[1] + staged_coordinate.y
        staged_potential = _marker_group_potential(
            group,
            sum_x=staged_sum_x,
            sum_y=staged_sum_y,
        )
        fallback_stage_switch_candidates.append((staged_potential, endpoint.object_ref, endpoint))
    if not switch_candidates:
        target_contaminant = _certified_marker_target_contaminant_in_scene(scene, group)
        if target_contaminant is not None:
            if target_contaminant.object_ref == active.object_ref:
                separation = _best_marker_target_separation(
                    scene,
                    group,
                    active,
                    rejected_signatures=rejected_signatures,
                )
                if separation is not None:
                    signature = (
                        f"marker:{group.marker_color}:separate:{separation.x},{separation.y}"
                    )
                    return PlannedClick(
                        coordinate=separation,
                        purpose=VisualActionPurpose.PROBE,
                        expectation=(
                            "separate the active marker center from a certified "
                            "sparse-target ring after direct and switched progress "
                            "are exhausted"
                        ),
                        mechanic_ref=mechanic_ref,
                        plan_id=plan_id,
                        plan_signature=signature,
                        target_center=group.target.rounded_center,
                        mediator_color=group.marker_color,
                        arity=group.arity,
                    )
            else:
                coordinate = Coordinate(*target_contaminant.rounded_center)
                signature = (
                    f"marker:{group.marker_color}:separate-activate:{coordinate.x},{coordinate.y}"
                )
                projection = _scene_after_marker_role_switch(
                    scene,
                    group,
                    active,
                    target_contaminant,
                )
                if signature not in rejected_signatures and projection is not None:
                    projected_scene, projected_group, projected_active = projection
                    if (
                        _best_marker_target_separation(
                            projected_scene,
                            projected_group,
                            projected_active,
                            rejected_signatures=rejected_signatures,
                        )
                        is not None
                    ):
                        return PlannedClick(
                            coordinate=coordinate,
                            purpose=VisualActionPurpose.PROBE,
                            expectation=(
                                "transfer the active role to the endpoint whose marker "
                                "center is joined to a certified sparse-target ring after "
                                "direct and switched progress are exhausted"
                            ),
                            mechanic_ref=mechanic_ref,
                            plan_id=plan_id,
                            plan_signature=signature,
                            target_center=group.target.rounded_center,
                            mediator_color=group.marker_color,
                            arity=group.arity,
                        )
        stage = _best_marker_staging_relocation(
            scene,
            group,
            active,
            rejected_signatures=rejected_signatures,
        )
        if stage is None and fallback_stage_switch_candidates:
            _potential, _object_ref, selected = min(
                fallback_stage_switch_candidates,
                key=lambda item: item[:2],
            )
            coordinate = Coordinate(*selected.rounded_center)
            signature = f"marker:{group.marker_color}:rotate:{coordinate.x},{coordinate.y}"
            return PlannedClick(
                coordinate=coordinate,
                purpose=VisualActionPurpose.PROBE,
                expectation=(
                    "transfer the active role within the same marker group to expose a "
                    "bounded staged continuation"
                ),
                mechanic_ref=mechanic_ref,
                plan_id=plan_id,
                plan_signature=signature,
                target_center=group.target.rounded_center,
                mediator_color=group.marker_color,
                arity=group.arity,
            )
        if stage is None:
            deferred_groups = tuple(item for item in unresolved if item != group)
            transfer = _best_marker_group_transfer(
                scene,
                deferred_groups,
                active,
                rejected_signatures=rejected_signatures,
            )
            if transfer is None:
                return None
            deferred_group, selected = transfer
            identity = (
                f"marker|{level_index}|{deferred_group.marker_color}|"
                f"{deferred_group.arity}|{scene.frame_hash}"
            )
            deferred_ref = (
                "affine-marker:" + hashlib.sha256(identity.encode("ascii")).hexdigest()[:20]
            )
            deferred_plan_id = (
                "visual-plan:"
                + hashlib.sha256(f"{deferred_ref}|local".encode("ascii")).hexdigest()[:20]
            )
            coordinate = Coordinate(*selected.rounded_center)
            signature = f"marker:{deferred_group.marker_color}:defer:{coordinate.x},{coordinate.y}"
            return PlannedClick(
                coordinate=coordinate,
                purpose=VisualActionPurpose.PROBE,
                expectation=(
                    "defer a marker group with no bounded same-group continuation and "
                    "transfer the active role to another collision-safe unresolved group"
                ),
                mechanic_ref=deferred_ref,
                plan_id=deferred_plan_id,
                plan_signature=signature,
                target_center=deferred_group.target.rounded_center,
                mediator_color=deferred_group.marker_color,
                arity=deferred_group.arity,
            )
        signature = f"marker:{group.marker_color}:stage:{stage.x},{stage.y}"
        return PlannedClick(
            coordinate=stage,
            purpose=VisualActionPurpose.PROBE,
            expectation=(
                "stage the active endpoint so a same-marker role transfer opens a "
                "bounded improving relocation"
            ),
            mechanic_ref=mechanic_ref,
            plan_id=plan_id,
            plan_signature=signature,
            target_center=group.target.rounded_center,
            mediator_color=group.marker_color,
            arity=group.arity,
            stages_for_switch=True,
        )
    _potential, _object_ref, selected = min(switch_candidates, key=lambda item: item[:2])
    coordinate = Coordinate(*selected.rounded_center)
    signature = f"marker:{group.marker_color}:rotate:{coordinate.x},{coordinate.y}"
    return PlannedClick(
        coordinate=coordinate,
        purpose=VisualActionPurpose.PROBE,
        expectation="transfer the active role within the same marker group before recomputing",
        mechanic_ref=mechanic_ref,
        plan_id=plan_id,
        plan_signature=signature,
        target_center=group.target.rounded_center,
        mediator_color=group.marker_color,
        arity=group.arity,
    )


_COORDINATE_TRANSFORM: dict[str, JSONValue] = {
    "relation": "coordinate_action_transforms_readable_endpoint_system"
}
_COORDINATE_PLACEMENT: dict[str, JSONValue] = {
    "relation": "selected_coordinate_becomes_readable_endpoint_center"
}


def _predicted_clef_effects(
    *,
    purpose: VisualActionPurpose,
    mechanic_refs: tuple[str, ...],
    action: ActionRequest,
) -> EffectVector:
    effects: list[FactoredEffect] = []
    if mechanic_refs:
        refs = tuple(f"mechanic:{item}" for item in mechanic_refs)
        effects.append(
            FactoredEffect(
                EffectChannel.OTHER_OBJECT_CHANGE,
                EffectKnowledge.KNOWN,
                _COORDINATE_TRANSFORM,
                refs,
            )
        )
        if purpose is VisualActionPurpose.PROGRESS:
            effects.append(
                FactoredEffect(
                    EffectChannel.CONTROLLABLE_OBJECT_DISPLACEMENT,
                    EffectKnowledge.KNOWN,
                    _COORDINATE_PLACEMENT,
                    refs,
                )
            )
    if action.name is ActionName.RESET:
        effects.append(
            FactoredEffect(
                EffectChannel.TERMINAL_RESET_TRANSITION,
                EffectKnowledge.KNOWN,
                {"expected_after_state": GameStateName.NOT_FINISHED.value},
            )
        )
    return EffectVector.from_effects(tuple(effects))


def _coordinate_transform_observed(
    before_scene: VisualScene,
    after_scene: VisualScene,
    *,
    action: ActionRequest,
    changed_cells: int,
    level_progress: bool,
    inferred_mechanic: AffineMechanic | None,
    active_color: int | None,
) -> bool:
    if action.name is not ActionName.ACTION6 or changed_cells == 0:
        return False
    if inferred_mechanic is not None or level_progress:
        return True
    return _endpoint_role_switch_observed(
        before_scene,
        after_scene,
        action=action,
        active_color=active_color,
    )


def _endpoint_role_switch_observed(
    before_scene: VisualScene,
    after_scene: VisualScene,
    *,
    action: ActionRequest,
    active_color: int | None,
) -> bool:
    """Recognize an exact readable endpoint-role exchange without displacement."""

    if action.coordinate is None or active_color is None or not before_scene.endpoints:
        return False
    before_roles = {item.rounded_center: item.color for item in before_scene.endpoints}
    after_roles = {item.rounded_center: item.color for item in after_scene.endpoints}
    clicked = (action.coordinate.x, action.coordinate.y)
    if before_roles.keys() != after_roles.keys() or clicked not in before_roles:
        return False
    active_centers = tuple(
        center for center, color in before_roles.items() if color == active_color
    )
    if len(active_centers) != 1 or clicked == active_centers[0]:
        return False
    prior_active = active_centers[0]
    changed_centers = {
        center for center in before_roles if before_roles[center] != after_roles[center]
    }
    if changed_centers != {prior_active, clicked}:
        return False
    if (
        before_roles[clicked] == active_color
        or after_roles[clicked] != active_color
        or after_roles[prior_active] != before_roles[clicked]
    ):
        return False
    before_mediators = {item.rounded_center: item.color for item in before_scene.mediators}
    after_mediators = {item.rounded_center: item.color for item in after_scene.mediators}
    return before_mediators == after_mediators


def _unique_affine_endpoint_group(
    scene: VisualScene,
    hub: VisualObject,
) -> tuple[VisualObject, ...] | None:
    """Return one uniquely readable endpoint subset whose centroid explains a hub."""

    if not 2 <= len(scene.endpoints) <= 12:
        return None
    best: tuple[float, tuple[VisualObject, ...]] | None = None
    ambiguous = False
    for arity in range(2, min(6, len(scene.endpoints)) + 1):
        for endpoints in itertools.combinations(scene.endpoints, arity):
            centroid = (
                sum(item.center_x for item in endpoints) / arity,
                sum(item.center_y for item in endpoints) / arity,
            )
            error = abs(centroid[0] - hub.center_x) + abs(centroid[1] - hub.center_y)
            if best is None or error < best[0] - 1e-9:
                best = (error, endpoints)
                ambiguous = False
            elif (
                best is not None
                and math.isclose(error, best[0], abs_tol=1e-9)
                and tuple(item.object_ref for item in endpoints)
                != tuple(item.object_ref for item in best[1])
            ):
                ambiguous = True
    if best is None or best[0] > 1.5 or ambiguous:
        return None
    return best[1]


def _unique_affine_hierarchy(
    scene: VisualScene,
    *,
    active_color: int,
    search_budget: _HierarchySearchBudget | None = None,
) -> _AffineHierarchy | None:
    """Return one exact-cover child-mediator hierarchy, or fail closed.

    The relation is intentionally narrower than ordinary affine transfer.  It
    requires multiple same-palette child mediators, one differently paletted
    raw target, one active endpoint, and a unique global partition of every
    endpoint into centroid-supported child groups.  Local best matches are not
    enough: accepting them independently is the flat-target reuse failure this
    layer exists to prevent.
    """

    if search_budget is None:
        search_budget = _HierarchySearchBudget(_MAX_HIERARCHY_SEARCH_BUDGET)
    endpoints = scene.endpoints
    mediators = scene.mediators
    targets = scene.targets
    if (
        not 4 <= len(endpoints) <= 12
        or not 2 <= len(mediators) <= 6
        or len(targets) != 1
        or len({item.color for item in mediators}) != 1
        or targets[0].color == mediators[0].color
    ):
        return None
    active = tuple(item for item in endpoints if item.color == active_color)
    if len(active) != 1:
        return None

    candidates_by_mediator: list[tuple[tuple[float, tuple[VisualObject, ...]], ...]] = []
    for mediator in mediators:
        candidates: list[tuple[float, tuple[VisualObject, ...]]] = []
        for arity in range(2, min(6, len(endpoints)) + 1):
            for group in itertools.combinations(endpoints, arity):
                search_budget.consume()
                centroid_x = sum(item.center_x for item in group) / arity
                centroid_y = sum(item.center_y for item in group) / arity
                error = abs(centroid_x - mediator.center_x) + abs(centroid_y - mediator.center_y)
                if error <= 1.5:
                    candidates.append((error, group))
        if not candidates:
            return None
        candidates_by_mediator.append(
            tuple(
                sorted(
                    candidates,
                    key=lambda item: (
                        item[0],
                        len(item[1]),
                        tuple(endpoint.object_ref for endpoint in item[1]),
                    ),
                )
            )
        )

    all_refs = frozenset(item.object_ref for item in endpoints)
    solutions: list[tuple[_AffineChildGroup, ...]] = []

    def search_exact_cover(
        mediator_index: int,
        used_refs: frozenset[str],
        chosen: tuple[_AffineChildGroup, ...],
    ) -> None:
        search_budget.consume()
        if len(solutions) > 1:
            return
        if mediator_index == len(mediators):
            if used_refs == all_refs:
                solutions.append(chosen)
            return
        mediator = mediators[mediator_index]
        for _error, group in candidates_by_mediator[mediator_index]:
            refs = frozenset(item.object_ref for item in group)
            if refs & used_refs:
                continue
            search_exact_cover(
                mediator_index + 1,
                used_refs | refs,
                (*chosen, _AffineChildGroup(mediator=mediator, endpoints=group)),
            )

    search_exact_cover(0, frozenset(), ())
    if len(solutions) != 1:
        return None
    children = solutions[0]
    active_children = tuple(
        child
        for child in children
        if any(item.object_ref == active[0].object_ref for item in child.endpoints)
    )
    if len(active_children) != 1:
        return None
    first = active_children[0]
    ordered = (
        first,
        *sorted(
            (child for child in children if child is not first),
            key=lambda child: (
                child.arity,
                child.mediator.rounded_center[1],
                child.mediator.rounded_center[0],
                child.mediator.object_ref,
            ),
        ),
    )
    identity = f"{scene.frame_hash}|{targets[0].color}|{mediators[0].color}|" + "|".join(
        f"{child.mediator.rounded_center}:"
        + ",".join(sorted(item.object_ref for item in child.endpoints))
        for child in ordered
    )
    return _AffineHierarchy(
        target=targets[0],
        children=ordered,
        active_color=active_color,
        mechanic_ref=(
            "affine-hierarchy-mechanic:" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]
        ),
    )


def _normalized_visual_shape(item: VisualObject) -> tuple[tuple[int, int], ...]:
    """Return translation-invariant raster geometry for one parsed object."""

    return tuple(sorted((x - item.min_x, y - item.min_y) for x, y in item.cells))


def _normalized_connector_structure(
    scene: VisualScene,
    group: _AffineChildGroup,
) -> _NormalizedConnectorStructure:
    """Return stable connector color/degree without movable raster geometry."""

    evidence = _hierarchy_connector_evidence(scene, group)
    if evidence is None:
        return None
    color, cells = evidence
    supported_legs = sum(
        any(
            _chebyshev_distance(cell, endpoint_cell) <= 1
            for cell in cells
            for endpoint_cell in _object_footprint(endpoint)
        )
        for endpoint in group.endpoints
    )
    return (color, supported_legs)


def _child_structure_signature(
    scene: VisualScene,
    group: _AffineChildGroup,
) -> _ChildStructureSignature:
    """Describe one child stratum without movable identity or active-role color."""

    return (
        group.arity,
        group.mediator.color,
        group.mediator.center_cell,
        _normalized_visual_shape(group.mediator),
        tuple(
            sorted(
                (endpoint.center_cell, _normalized_visual_shape(endpoint))
                for endpoint in group.endpoints
            )
        ),
        _normalized_connector_structure(scene, group),
    )


def _child_isolation_hypothesis_key(
    scene: VisualScene,
    group: _AffineChildGroup,
    *,
    relation_key: str,
) -> str:
    """Scope child-only sufficiency to one stable structural equivalence class."""

    identity = (
        "child-only-sufficiency-v1",
        relation_key,
        _child_structure_signature(scene, group),
    )
    return (
        "affine-child-only-hypothesis:"
        + hashlib.sha256(repr(identity).encode("ascii")).hexdigest()[:24]
    )


def _hierarchy_relation_key(
    scene: VisualScene,
    hierarchy: _AffineHierarchy,
    *,
    level_index: int,
) -> str:
    """Return a level-scoped semantic key that ignores movable layout identity.

    Endpoint coordinates, endpoint object references, active-role placement, and
    the full frame hash all change while one hierarchy hypothesis is being
    tested.  None of those changes create a new parent relation.  The key keeps
    only the stable target geometry and the child relation signatures so an
    officially falsified completion hypothesis cannot reopen under a new frame
    identity after a same-level intervention or RESET.
    """

    target = hierarchy.target
    children = tuple(
        sorted(_child_structure_signature(scene, child) for child in hierarchy.children)
    )
    identity = (
        level_index,
        target.color,
        target.rounded_center,
        _normalized_visual_shape(target),
        children,
    )
    return (
        "affine-hierarchy-relation:"
        + hashlib.sha256(repr(identity).encode("ascii")).hexdigest()[:24]
    )


def _composite_bridge_relation(
    scene: VisualScene,
    hierarchy: _AffineHierarchy,
    *,
    level_index: int,
) -> _CompositeBridgeRelation | None:
    """Build a metric-stable proximity assignment to witnessed composite sinks."""

    if len(hierarchy.children) < 2:
        return None
    carrier_colors = {child.mediator.color for child in hierarchy.children}
    if len(carrier_colors) != 1:
        return None
    carrier_color = next(iter(carrier_colors))
    examples = _composite_bridge_examples(scene, carrier_color=carrier_color)
    eligible_disks = tuple(
        disk for disk in _composite_filled_disks(scene) if carrier_color in disk.palette
    )
    if (
        len(examples) != len(hierarchy.children)
        or len(examples) < 2
        or len(eligible_disks) != 2 * len(examples)
        or len({example.target.rounded_center for example in examples}) != len(examples)
        or len({source.center for example in examples for source in example.sources})
        != len(eligible_disks)
    ):
        return None

    permutations = tuple(itertools.permutations(examples))
    if not permutations:
        return None

    def metric_score(
        assignment: tuple[_CompositeBridgeExample, ...],
        *,
        metric: str,
    ) -> float:
        parts: list[float] = []
        for child, example in zip(hierarchy.children, assignment, strict=True):
            aggregate_x, aggregate_y = example.aggregate_center_twice
            delta_x = abs(2 * child.mediator.rounded_center[0] - aggregate_x)
            delta_y = abs(2 * child.mediator.rounded_center[1] - aggregate_y)
            if metric == "euclidean":
                parts.append(math.hypot(delta_x, delta_y))
            elif metric == "manhattan":
                parts.append(float(delta_x + delta_y))
            else:
                parts.append(float(delta_x * delta_x + delta_y * delta_y))
        return math.fsum(parts)

    winners: list[tuple[_CompositeBridgeExample, ...]] = []
    for metric in ("euclidean", "manhattan", "squared-euclidean"):
        ranked = sorted(
            ((metric_score(items, metric=metric), items) for items in permutations),
            key=lambda item: (
                item[0],
                tuple(example.target.rounded_center for example in item[1]),
            ),
        )
        if len(ranked) > 1 and math.isclose(
            ranked[0][0],
            ranked[1][0],
            rel_tol=1e-12,
            abs_tol=1e-12,
        ):
            return None
        winners.append(ranked[0][1])
    if any(winner != winners[0] for winner in winners[1:]):
        return None

    assignments = tuple(zip(hierarchy.children, winners[0], strict=True))
    identity = (
        "proximity-assigned-composite-sink-v1",
        _hierarchy_relation_key(scene, hierarchy, level_index=level_index),
        tuple(
            (
                _child_structure_signature(scene, child),
                example.carrier_color,
                tuple(source.center for source in example.sources),
                example.residual_colors,
                example.target.rounded_center,
                tuple(sorted((x, y, scene.cells[y][x]) for x, y in example.target.cells)),
            )
            for child, example in assignments
        ),
    )
    return _CompositeBridgeRelation(
        assignments=assignments,
        relation_key=(
            "affine-bridge-relation:"
            + hashlib.sha256(repr(identity).encode("ascii")).hexdigest()[:24]
        ),
    )


def _bridge_target_supports(
    relation: _CompositeBridgeRelation,
) -> tuple[_HierarchyTargetSupport, ...]:
    """Project the original bridge relation into explicit per-child supports."""

    return tuple(
        _HierarchyTargetSupport(
            child=child,
            example=example,
            target=example.target,
            surface_signature=frozenset(example.residual_colors),
        )
        for child, example in relation.assignments
    )


def _residual_linked_hierarchy_relation(
    scene: VisualScene,
    hierarchy: _AffineHierarchy,
    *,
    level_index: int,
) -> _ResidualLinkedHierarchyRelation | None:
    """Link exactly one metric-stable bridge child to a singleton raw target.

    The bridge relation is recomputed here rather than accepted from a caller so
    this family cannot reuse an arbitrary or ambiguous child-to-example pairing.
    Palette values and coordinates participate only through observed equality
    and structural identity; no game or campaign identifier is consulted.
    """

    bridge = _composite_bridge_relation(
        scene,
        hierarchy,
        level_index=level_index,
    )
    if bridge is None or len(bridge.assignments) < 2:
        return None
    raw_surface_signature = frozenset(scene.cells[y][x] for x, y in hierarchy.target.cells)
    if (
        len(raw_surface_signature) != 1
        or raw_surface_signature != frozenset({hierarchy.target.color})
        or any(
            _normalized_connector_structure(scene, child) is None for child in hierarchy.children
        )
    ):
        return None
    raw_color = next(iter(raw_surface_signature))
    linked = tuple(
        (child, example)
        for child, example in bridge.assignments
        if raw_color in example.residual_colors
    )
    if len(linked) != 1 or linked[0][1].target.rounded_center == hierarchy.target.rounded_center:
        return None
    linked_mediator_ref = linked[0][0].mediator.object_ref
    supports = tuple(
        _HierarchyTargetSupport(
            child=child,
            example=example,
            target=(
                hierarchy.target
                if child.mediator.object_ref == linked_mediator_ref
                else example.target
            ),
            surface_signature=(
                raw_surface_signature
                if child.mediator.object_ref == linked_mediator_ref
                else frozenset(example.residual_colors)
            ),
        )
        for child, example in bridge.assignments
    )
    support_centers = tuple(item.target.rounded_center for item in supports)
    if (
        tuple(item.child for item in supports) != hierarchy.children
        or len(set(support_centers)) != len(supports)
        or hierarchy.target.rounded_center
        in {
            item.example.target.rounded_center
            for item in supports
            if item.child.mediator.object_ref != linked_mediator_ref
        }
    ):
        return None
    identity = (
        "residual-linked-mixed-support-v1",
        bridge.relation_key,
        (
            hierarchy.target.color,
            hierarchy.target.rounded_center,
            _normalized_visual_shape(hierarchy.target),
            tuple(sorted((x, y, scene.cells[y][x]) for x, y in hierarchy.target.cells)),
        ),
        tuple(
            (
                _child_structure_signature(scene, item.child),
                item.example.residual_colors,
                item.example.target.rounded_center,
                item.target.rounded_center,
                item.child.mediator.object_ref == linked_mediator_ref,
            )
            for item in supports
        ),
    )
    return _ResidualLinkedHierarchyRelation(
        bridge_relation_key=bridge.relation_key,
        supports=supports,
        relation_key=(
            "affine-residual-linked-relation:"
            + hashlib.sha256(repr(identity).encode("ascii")).hexdigest()[:24]
        ),
    )


def _external_residual_linked_hierarchy_relation(
    scene: VisualScene,
    hierarchy: _AffineHierarchy,
    *,
    level_index: int,
    rejected_mixed_relation_keys: set[str] | frozenset[str],
) -> _ExternalResidualLinkedHierarchyRelation | None:
    """Extend a rejected mixed relation through one witnessed carrier-mask chain.

    The raw target color must occur in one source disk among exactly two bridge
    examples.  That source's normalized carrier mask must identify exactly one
    source in the other example.  Only the counterpart source's residual color
    may overlap one non-bridge sparse target.  These uniqueness gates prevent
    arbitrary per-child palette matching from manufacturing a relation.
    """

    bridge = _composite_bridge_relation(
        scene,
        hierarchy,
        level_index=level_index,
    )
    mixed = _residual_linked_hierarchy_relation(
        scene,
        hierarchy,
        level_index=level_index,
    )
    if (
        bridge is None
        or mixed is None
        or bridge.relation_key != mixed.bridge_relation_key
        or mixed.relation_key not in rejected_mixed_relation_keys
        or len(bridge.assignments) != 2
        or tuple(child for child, _example in bridge.assignments) != hierarchy.children
        or any(
            _normalized_connector_structure(scene, child) is None for child in hierarchy.children
        )
    ):
        return None

    raw_surface_signature = frozenset(scene.cells[y][x] for x, y in hierarchy.target.cells)
    if len(raw_surface_signature) != 1 or raw_surface_signature != frozenset(
        {hierarchy.target.color}
    ):
        return None
    raw_color = next(iter(raw_surface_signature))
    source_records = tuple(
        (child, example, source)
        for child, example in bridge.assignments
        for source in example.sources
    )
    raw_source_records = tuple(
        record
        for record in source_records
        if raw_color in (record[2].palette - {record[1].carrier_color})
    )
    if len(raw_source_records) != 1:
        return None
    raw_child, raw_example, raw_source = raw_source_records[0]
    other_assignments = tuple(
        (child, example) for child, example in bridge.assignments if example != raw_example
    )
    if len(other_assignments) != 1:
        return None
    counterpart_child, counterpart_example = other_assignments[0]
    carrier_offsets = raw_source.offsets(raw_example.carrier_color)
    counterpart_sources = tuple(
        source
        for source in counterpart_example.sources
        if source.offsets(counterpart_example.carrier_color) == carrier_offsets
    )
    if not carrier_offsets or len(counterpart_sources) != 1:
        return None
    counterpart_source = counterpart_sources[0]
    counterpart_residuals = counterpart_source.palette - {counterpart_example.carrier_color}
    if len(counterpart_residuals) != 1:
        return None
    external_link_color = next(iter(counterpart_residuals))
    if external_link_color == raw_color:
        return None

    bridge_sink_centers = frozenset(
        example.target.rounded_center for _child, example in bridge.assignments
    )
    external_targets = tuple(
        (target, surface_signature)
        for target, surface_signature in _composite_sparse_targets(scene)
        if target.rounded_center not in bridge_sink_centers
        and target.rounded_center != hierarchy.target.rounded_center
    )
    if len({target.rounded_center for target, _surface in external_targets}) != len(
        external_targets
    ):
        return None

    bridge_residual_colors = frozenset(
        color for _child, example in bridge.assignments for color in example.residual_colors
    )
    linked_external_targets = tuple(
        (target, surface_signature, surface_signature & bridge_residual_colors)
        for target, surface_signature in external_targets
        if surface_signature & bridge_residual_colors
    )
    if len(linked_external_targets) != 1 or linked_external_targets[0][2] != frozenset(
        {external_link_color}
    ):
        return None
    external_target, external_surface_signature, _overlap = linked_external_targets[0]

    supports = tuple(
        _HierarchyTargetSupport(
            child=child,
            example=example,
            target=(
                hierarchy.target
                if child == raw_child
                else external_target
                if child == counterpart_child
                else example.target
            ),
            surface_signature=(
                raw_surface_signature
                if child == raw_child
                else external_surface_signature
                if child == counterpart_child
                else frozenset(example.residual_colors)
            ),
        )
        for child, example in bridge.assignments
    )

    selected_centers = tuple(item.target.rounded_center for item in supports)
    raw_center = hierarchy.target.rounded_center
    raw_supports = tuple(item for item in supports if item.target.rounded_center == raw_center)
    mixed_raw_supports = tuple(
        item for item in mixed.supports if item.target.rounded_center == raw_center
    )
    if (
        tuple(item.child for item in supports) != hierarchy.children
        or len(set(selected_centers)) != len(supports)
        or len(raw_supports) != 1
        or len(mixed_raw_supports) != 1
        or raw_supports[0].child != raw_child
        or raw_supports[0].child != mixed_raw_supports[0].child
        or raw_supports[0].target.cells != hierarchy.target.cells
        or external_target.rounded_center in bridge_sink_centers
        or external_target.rounded_center == raw_center
    ):
        return None

    identity = (
        "external-residual-linked-support-v1",
        bridge.relation_key,
        mixed.relation_key,
        tuple(
            (
                _child_structure_signature(scene, item.child),
                item.example.residual_colors,
                item.example.target.rounded_center,
                item.target.rounded_center,
                item.surface_signature,
                tuple(sorted((x, y, scene.cells[y][x]) for x, y in item.target.cells)),
            )
            for item in supports
        ),
        raw_source.center,
        counterpart_source.center,
        raw_color,
        external_link_color,
        carrier_offsets,
    )
    return _ExternalResidualLinkedHierarchyRelation(
        bridge_relation_key=bridge.relation_key,
        mixed_relation_key=mixed.relation_key,
        supports=supports,
        raw_source_center=raw_source.center,
        counterpart_source_center=counterpart_source.center,
        raw_color=raw_color,
        external_link_color=external_link_color,
        carrier_offsets=carrier_offsets,
        relation_key=(
            "affine-external-residual-linked-relation:"
            + hashlib.sha256(repr(identity).encode("ascii")).hexdigest()[:24]
        ),
    )


def _raw_matching_composite_hierarchy_relation(
    scene: VisualScene,
    hierarchy: _AffineHierarchy,
    *,
    level_index: int,
    rejected_mixed_relation_keys: set[str] | frozenset[str],
    rejected_external_relation_keys: set[str] | frozenset[str],
) -> _RawMatchingCompositeHierarchyRelation | None:
    """Retain one raw-linked child while revising only its failed counterpart.

    The mixed relation identifies the unique child linked to the singleton raw
    target. After both mixed and external variants have failed, the counterpart
    may use the unique observed composite target whose exact surface strictly
    contains that singleton. The containing target must be the raw-linked
    child's own witnessed bridge sink, so this is a bounded containment test and
    not a scan over arbitrary target assignments.
    """

    bridge = _composite_bridge_relation(
        scene,
        hierarchy,
        level_index=level_index,
    )
    mixed = _residual_linked_hierarchy_relation(
        scene,
        hierarchy,
        level_index=level_index,
    )
    external = _external_residual_linked_hierarchy_relation(
        scene,
        hierarchy,
        level_index=level_index,
        rejected_mixed_relation_keys=rejected_mixed_relation_keys,
    )
    if (
        bridge is None
        or mixed is None
        or external is None
        or len(bridge.assignments) != 2
        or tuple(child for child, _example in bridge.assignments) != hierarchy.children
        or mixed.bridge_relation_key != bridge.relation_key
        or external.bridge_relation_key != bridge.relation_key
        or external.mixed_relation_key != mixed.relation_key
        or mixed.relation_key not in rejected_mixed_relation_keys
        or external.relation_key not in rejected_external_relation_keys
        or any(
            _normalized_connector_structure(scene, child) is None for child in hierarchy.children
        )
    ):
        return None

    raw_surface_signature = frozenset(scene.cells[y][x] for x, y in hierarchy.target.cells)
    if len(raw_surface_signature) != 1 or raw_surface_signature != frozenset(
        {hierarchy.target.color}
    ):
        return None
    raw_center = hierarchy.target.rounded_center
    mixed_raw_supports = tuple(
        support for support in mixed.supports if support.target.rounded_center == raw_center
    )
    external_raw_supports = tuple(
        support for support in external.supports if support.target.rounded_center == raw_center
    )
    if (
        len(mixed_raw_supports) != 1
        or len(external_raw_supports) != 1
        or mixed_raw_supports[0].child != external_raw_supports[0].child
    ):
        return None
    raw_child = mixed_raw_supports[0].child
    raw_assignments = tuple(
        (child, example) for child, example in bridge.assignments if child == raw_child
    )
    counterpart_assignments = tuple(
        (child, example) for child, example in bridge.assignments if child != raw_child
    )
    if len(raw_assignments) != 1 or len(counterpart_assignments) != 1:
        return None
    _raw_child, raw_example = raw_assignments[0]
    counterpart_child, _counterpart_example = counterpart_assignments[0]

    containing_targets = tuple(
        (target, surface_signature)
        for target, surface_signature in _composite_sparse_targets(scene)
        if raw_surface_signature < surface_signature
    )
    if len(containing_targets) != 1:
        return None
    containing_target, containing_surface_signature = containing_targets[0]
    if (
        containing_target.rounded_center != raw_example.target.rounded_center
        or containing_target.cells != raw_example.target.cells
        or containing_surface_signature != frozenset(raw_example.residual_colors)
        or containing_target.rounded_center == raw_center
    ):
        return None

    supports = tuple(
        _HierarchyTargetSupport(
            child=child,
            example=example,
            target=hierarchy.target if child == raw_child else containing_target,
            surface_signature=(
                raw_surface_signature if child == raw_child else containing_surface_signature
            ),
        )
        for child, example in bridge.assignments
    )
    selected_centers = tuple(support.target.rounded_center for support in supports)
    existing_support_tuples = {
        tuple(example.target.rounded_center for _child, example in bridge.assignments),
        tuple(support.target.rounded_center for support in mixed.supports),
        tuple(support.target.rounded_center for support in external.supports),
    }
    if (
        tuple(support.child for support in supports) != hierarchy.children
        or len(set(selected_centers)) != len(supports)
        or selected_centers in existing_support_tuples
        or sum(support.child == raw_child for support in supports) != 1
        or sum(support.child == counterpart_child for support in supports) != 1
        or next(support for support in supports if support.child == raw_child).target.cells
        != hierarchy.target.cells
        or next(support for support in supports if support.child == counterpart_child).target.cells
        != containing_target.cells
    ):
        return None

    identity = (
        "raw-matching-composite-support-v1",
        bridge.relation_key,
        mixed.relation_key,
        external.relation_key,
        tuple(
            (
                _child_structure_signature(scene, support.child),
                support.example.residual_colors,
                support.example.target.rounded_center,
                support.target.rounded_center,
                support.surface_signature,
                tuple(sorted((x, y, scene.cells[y][x]) for x, y in support.target.cells)),
            )
            for support in supports
        ),
    )
    return _RawMatchingCompositeHierarchyRelation(
        bridge_relation_key=bridge.relation_key,
        mixed_relation_key=mixed.relation_key,
        external_relation_key=external.relation_key,
        supports=supports,
        relation_key=(
            "affine-raw-matching-composite-relation:"
            + hashlib.sha256(repr(identity).encode("ascii")).hexdigest()[:24]
        ),
    )


def _external_own_composite_hierarchy_relation(
    scene: VisualScene,
    hierarchy: _AffineHierarchy,
    *,
    level_index: int,
    rejected_bridge_relation_keys: set[str] | frozenset[str],
    rejected_mixed_relation_keys: set[str] | frozenset[str],
    rejected_external_relation_keys: set[str] | frozenset[str],
    rejected_raw_matching_relation_keys: set[str] | frozenset[str],
) -> _ExternalOwnCompositeHierarchyRelation | None:
    """Recombine the two uniquely witnessed non-raw sinks after four failures.

    The external relation identifies the counterpart's carrier-mask sink.  The
    raw-matching relation identifies the unique raw-linked child while proving
    that child's own bridge sink is the sole observed containing composite.
    Only after the bridge, mixed, external, and raw-matching relations have all
    been falsified may those two independently witnessed sinks be combined.
    """

    bridge = _composite_bridge_relation(
        scene,
        hierarchy,
        level_index=level_index,
    )
    mixed = _residual_linked_hierarchy_relation(
        scene,
        hierarchy,
        level_index=level_index,
    )
    external = _external_residual_linked_hierarchy_relation(
        scene,
        hierarchy,
        level_index=level_index,
        rejected_mixed_relation_keys=rejected_mixed_relation_keys,
    )
    raw_matching = _raw_matching_composite_hierarchy_relation(
        scene,
        hierarchy,
        level_index=level_index,
        rejected_mixed_relation_keys=rejected_mixed_relation_keys,
        rejected_external_relation_keys=rejected_external_relation_keys,
    )
    if (
        bridge is None
        or mixed is None
        or external is None
        or raw_matching is None
        or len(bridge.assignments) != 2
        or tuple(child for child, _example in bridge.assignments) != hierarchy.children
        or bridge.relation_key not in rejected_bridge_relation_keys
        or mixed.relation_key not in rejected_mixed_relation_keys
        or external.relation_key not in rejected_external_relation_keys
        or raw_matching.relation_key not in rejected_raw_matching_relation_keys
        or mixed.bridge_relation_key != bridge.relation_key
        or external.bridge_relation_key != bridge.relation_key
        or external.mixed_relation_key != mixed.relation_key
        or raw_matching.bridge_relation_key != bridge.relation_key
        or raw_matching.mixed_relation_key != mixed.relation_key
        or raw_matching.external_relation_key != external.relation_key
        or any(
            _normalized_connector_structure(scene, child) is None for child in hierarchy.children
        )
    ):
        return None

    raw_surface_signature = frozenset(scene.cells[y][x] for x, y in hierarchy.target.cells)
    if len(raw_surface_signature) != 1 or raw_surface_signature != frozenset(
        {hierarchy.target.color}
    ):
        return None
    raw_center = hierarchy.target.rounded_center
    mixed_raw_supports = tuple(
        support for support in mixed.supports if support.target.rounded_center == raw_center
    )
    external_raw_supports = tuple(
        support for support in external.supports if support.target.rounded_center == raw_center
    )
    raw_matching_raw_supports = tuple(
        support for support in raw_matching.supports if support.target.rounded_center == raw_center
    )
    if (
        len(mixed_raw_supports) != 1
        or len(external_raw_supports) != 1
        or len(raw_matching_raw_supports) != 1
        or mixed_raw_supports[0].child != external_raw_supports[0].child
        or mixed_raw_supports[0].child != raw_matching_raw_supports[0].child
    ):
        return None
    raw_child = mixed_raw_supports[0].child

    raw_assignments = tuple(
        (child, example) for child, example in bridge.assignments if child == raw_child
    )
    counterpart_assignments = tuple(
        (child, example) for child, example in bridge.assignments if child != raw_child
    )
    external_counterpart_supports = tuple(
        support for support in external.supports if support.child != raw_child
    )
    raw_matching_counterpart_supports = tuple(
        support for support in raw_matching.supports if support.child != raw_child
    )
    if (
        len(raw_assignments) != 1
        or len(counterpart_assignments) != 1
        or len(external_counterpart_supports) != 1
        or len(raw_matching_counterpart_supports) != 1
    ):
        return None
    _raw_child, raw_example = raw_assignments[0]
    counterpart_child, counterpart_example = counterpart_assignments[0]
    external_support = external_counterpart_supports[0]
    raw_matching_counterpart_support = raw_matching_counterpart_supports[0]
    if (
        external_support.child != counterpart_child
        or external_support.example != counterpart_example
        or raw_matching_counterpart_support.child != counterpart_child
        or raw_matching_counterpart_support.target.cells != raw_example.target.cells
        or raw_matching_counterpart_support.surface_signature
        != frozenset(raw_example.residual_colors)
    ):
        return None

    supports = tuple(
        _HierarchyTargetSupport(
            child=child,
            example=example,
            target=(raw_example.target if child == raw_child else external_support.target),
            surface_signature=(
                frozenset(raw_example.residual_colors)
                if child == raw_child
                else external_support.surface_signature
            ),
        )
        for child, example in bridge.assignments
    )
    selected_centers = tuple(support.target.rounded_center for support in supports)
    existing_support_tuples = {
        tuple(example.target.rounded_center for _child, example in bridge.assignments),
        tuple(support.target.rounded_center for support in mixed.supports),
        tuple(support.target.rounded_center for support in external.supports),
        tuple(support.target.rounded_center for support in raw_matching.supports),
    }
    raw_support = next((support for support in supports if support.child == raw_child), None)
    counterpart_support = next(
        (support for support in supports if support.child == counterpart_child),
        None,
    )
    if (
        tuple(support.child for support in supports) != hierarchy.children
        or len(existing_support_tuples) != 4
        or len(set(selected_centers)) != len(supports)
        or raw_center in selected_centers
        or selected_centers in existing_support_tuples
        or raw_support is None
        or counterpart_support is None
        or raw_support.target.cells != raw_example.target.cells
        or raw_support.surface_signature != frozenset(raw_example.residual_colors)
        or counterpart_support.target.cells != external_support.target.cells
        or counterpart_support.surface_signature != external_support.surface_signature
    ):
        return None

    identity = (
        "external-own-composite-support-v1",
        bridge.relation_key,
        mixed.relation_key,
        external.relation_key,
        raw_matching.relation_key,
        (
            hierarchy.target.color,
            _normalized_visual_shape(hierarchy.target),
            tuple(sorted((x, y, scene.cells[y][x]) for x, y in hierarchy.target.cells)),
        ),
        tuple(
            (
                _child_structure_signature(scene, support.child),
                support.example.residual_colors,
                support.example.target.rounded_center,
                support.target.rounded_center,
                support.surface_signature,
                tuple(sorted((x, y, scene.cells[y][x]) for x, y in support.target.cells)),
                support.child == raw_child,
            )
            for support in supports
        ),
    )
    return _ExternalOwnCompositeHierarchyRelation(
        bridge_relation_key=bridge.relation_key,
        mixed_relation_key=mixed.relation_key,
        external_relation_key=external.relation_key,
        raw_matching_relation_key=raw_matching.relation_key,
        supports=supports,
        relation_key=(
            "affine-external-own-composite-relation:"
            + hashlib.sha256(repr(identity).encode("ascii")).hexdigest()[:24]
        ),
    )


def _carrier_source_occlusion_hierarchy_relation(
    scene: VisualScene,
    hierarchy: _AffineHierarchy,
    *,
    level_index: int,
    rejected_bridge_relation_keys: set[str] | frozenset[str],
    rejected_mixed_relation_keys: set[str] | frozenset[str],
    rejected_external_relation_keys: set[str] | frozenset[str],
    rejected_raw_matching_relation_keys: set[str] | frozenset[str],
    rejected_external_own_relation_keys: set[str] | frozenset[str],
) -> _CarrierSourceOcclusionHierarchyRelation | None:
    """Derive the one carrier-matched pair of filled source supports.

    This relation is available only after every target-sink family that supplied
    its evidence has been rejected.  The singleton raw color identifies exactly
    one source disk in one bridge example.  Its normalized carrier mask then
    identifies exactly one source in the other bridge example.  No unobserved
    source, color, coordinate, or support permutation is introduced.
    """

    bridge = _composite_bridge_relation(scene, hierarchy, level_index=level_index)
    mixed = _residual_linked_hierarchy_relation(scene, hierarchy, level_index=level_index)
    external = _external_residual_linked_hierarchy_relation(
        scene,
        hierarchy,
        level_index=level_index,
        rejected_mixed_relation_keys=rejected_mixed_relation_keys,
    )
    raw_matching = _raw_matching_composite_hierarchy_relation(
        scene,
        hierarchy,
        level_index=level_index,
        rejected_mixed_relation_keys=rejected_mixed_relation_keys,
        rejected_external_relation_keys=rejected_external_relation_keys,
    )
    external_own = _external_own_composite_hierarchy_relation(
        scene,
        hierarchy,
        level_index=level_index,
        rejected_bridge_relation_keys=rejected_bridge_relation_keys,
        rejected_mixed_relation_keys=rejected_mixed_relation_keys,
        rejected_external_relation_keys=rejected_external_relation_keys,
        rejected_raw_matching_relation_keys=rejected_raw_matching_relation_keys,
    )
    if (
        bridge is None
        or mixed is None
        or external is None
        or raw_matching is None
        or external_own is None
        or len(bridge.assignments) != 2
        or tuple(child for child, _example in bridge.assignments) != hierarchy.children
        or bridge.relation_key not in rejected_bridge_relation_keys
        or mixed.relation_key not in rejected_mixed_relation_keys
        or external.relation_key not in rejected_external_relation_keys
        or raw_matching.relation_key not in rejected_raw_matching_relation_keys
        or external_own.relation_key not in rejected_external_own_relation_keys
        or mixed.bridge_relation_key != bridge.relation_key
        or external.bridge_relation_key != bridge.relation_key
        or external.mixed_relation_key != mixed.relation_key
        or raw_matching.bridge_relation_key != bridge.relation_key
        or raw_matching.mixed_relation_key != mixed.relation_key
        or raw_matching.external_relation_key != external.relation_key
        or external_own.bridge_relation_key != bridge.relation_key
        or external_own.mixed_relation_key != mixed.relation_key
        or external_own.external_relation_key != external.relation_key
        or external_own.raw_matching_relation_key != raw_matching.relation_key
    ):
        return None

    raw_surface_signature = frozenset(scene.cells[y][x] for x, y in hierarchy.target.cells)
    if raw_surface_signature != frozenset({hierarchy.target.color}):
        return None
    raw_supports = tuple(
        support
        for support in mixed.supports
        if support.target.rounded_center == hierarchy.target.rounded_center
    )
    if len(raw_supports) != 1:
        return None
    raw_child = raw_supports[0].child
    raw_assignments = tuple(
        (child, example) for child, example in bridge.assignments if child == raw_child
    )
    counterpart_assignments = tuple(
        (child, example) for child, example in bridge.assignments if child != raw_child
    )
    if len(raw_assignments) != 1 or len(counterpart_assignments) != 1:
        return None
    _raw_child, raw_example = raw_assignments[0]
    counterpart_child, counterpart_example = counterpart_assignments[0]

    raw_sources = tuple(
        source
        for source in raw_example.sources
        if source.center == external.raw_source_center
        and external.raw_color in (source.palette - {raw_example.carrier_color})
        and source.offsets(raw_example.carrier_color) == external.carrier_offsets
    )
    counterpart_sources = tuple(
        source
        for source in counterpart_example.sources
        if source.center == external.counterpart_source_center
        and source.offsets(counterpart_example.carrier_color) == external.carrier_offsets
        and source.palette - {counterpart_example.carrier_color}
        == frozenset({external.external_link_color})
    )
    if len(raw_sources) != 1 or len(counterpart_sources) != 1:
        return None
    raw_source = raw_sources[0]
    counterpart_source = counterpart_sources[0]

    supports = tuple(
        _HierarchySourceSupport(
            child=child,
            example=example,
            source=raw_source if child == raw_child else counterpart_source,
        )
        for child, example in bridge.assignments
    )
    expected_disk_offsets = _COMPOSITE_MEDIATOR_OFFSETS
    if (
        tuple(support.child for support in supports) != hierarchy.children
        or len({support.source.center for support in supports}) != len(supports)
        or sum(support.child == raw_child and support.source == raw_source for support in supports)
        != 1
        or sum(
            support.child == counterpart_child and support.source == counterpart_source
            for support in supports
        )
        != 1
        or any(
            len(support.source.cells) != len(expected_disk_offsets)
            or frozenset(support.source.cells)
            != frozenset(
                (support.source.center[0] + dx, support.source.center[1] + dy)
                for dx, dy in expected_disk_offsets
            )
            or _translated_object_footprint(
                support.child.mediator,
                center=support.source.center,
            )
            != frozenset(support.source.cells)
            for support in supports
        )
    ):
        return None

    identity = (
        "carrier-source-occlusion-support-v1",
        bridge.relation_key,
        mixed.relation_key,
        external.relation_key,
        raw_matching.relation_key,
        external_own.relation_key,
        external.carrier_offsets,
        tuple(
            (
                _child_structure_signature(scene, support.child),
                support.example.residual_colors,
                support.example.target.rounded_center,
                support.source.center,
                support.source.palette,
                support.source.offsets_by_color,
                tuple(sorted((x, y, scene.cells[y][x]) for x, y in support.source.cells)),
                support.child == raw_child,
            )
            for support in supports
        ),
    )
    return _CarrierSourceOcclusionHierarchyRelation(
        bridge_relation_key=bridge.relation_key,
        mixed_relation_key=mixed.relation_key,
        external_relation_key=external.relation_key,
        raw_matching_relation_key=raw_matching.relation_key,
        external_own_relation_key=external_own.relation_key,
        supports=supports,
        relation_key=(
            "affine-carrier-source-occlusion-relation:"
            + hashlib.sha256(repr(identity).encode("ascii")).hexdigest()[:24]
        ),
    )


def _hierarchy_dynamic_footprint(
    scene: VisualScene,
    group: _AffineChildGroup,
) -> frozenset[tuple[int, int]]:
    """Return one observed child relation's movable glyph and connector surface."""

    glyph_cells = frozenset(
        (
            *_object_footprint(group.mediator),
            *(cell for endpoint in group.endpoints for cell in _object_footprint(endpoint)),
        )
    )
    connector_evidence = _hierarchy_connector_evidence(scene, group)
    if connector_evidence is None:
        return glyph_cells
    _connector_color, observed_connector_cells = connector_evidence
    return glyph_cells | observed_connector_cells


def _hierarchy_projected_group_footprint(
    group: _AffineChildGroup,
    *,
    endpoint_centers: tuple[tuple[int, int], ...],
    mediator_center: tuple[int, int],
    endpoints: tuple[VisualObject, ...] | None = None,
) -> frozenset[tuple[int, int]]:
    projected_endpoints = group.endpoints if endpoints is None else endpoints
    return frozenset(
        (
            *_translated_object_footprint(group.mediator, center=mediator_center),
            *(
                cell
                for endpoint, center in zip(projected_endpoints, endpoint_centers, strict=True)
                for cell in _translated_object_footprint(endpoint, center=center)
            ),
            *(
                cell
                for center in endpoint_centers
                for cell in _raster_line_cells(center, mediator_center)
            ),
        )
    )


def _hierarchy_connector_evidence(
    scene: VisualScene,
    group: _AffineChildGroup,
) -> tuple[int, frozenset[tuple[int, int]]] | None:
    glyph_cells = frozenset(
        (
            *_object_footprint(group.mediator),
            *(cell for endpoint in group.endpoints for cell in _object_footprint(endpoint)),
        )
    )
    mediator_cells = _object_footprint(group.mediator)
    colors = {
        scene.cells[y][x]
        for endpoint in group.endpoints
        for x, y in _raster_line_cells(
            endpoint.rounded_center,
            group.mediator.rounded_center,
        )
        if (x, y) not in glyph_cells and scene.cells[y][x] != scene.background
    }
    supported: list[tuple[int, frozenset[tuple[int, int]]]] = []
    for color in sorted(colors):
        evidence_cells: set[tuple[int, int]] = set()
        supporting_legs = 0
        for endpoint in group.endpoints:
            endpoint_cells = _object_footprint(endpoint)
            candidates = {
                (x, y)
                for x, y in _raster_line_cells(
                    endpoint.rounded_center,
                    group.mediator.rounded_center,
                )
                if (x, y) not in glyph_cells and scene.cells[y][x] == color
            }
            bridging_component: frozenset[tuple[int, int]] | None = None
            while candidates:
                frontier = [candidates.pop()]
                component: set[tuple[int, int]] = set(frontier)
                while frontier:
                    current = frontier.pop()
                    adjacent = {
                        cell for cell in candidates if _chebyshev_distance(current, cell) <= 1
                    }
                    candidates.difference_update(adjacent)
                    component.update(adjacent)
                    frontier.extend(adjacent)
                if any(
                    _chebyshev_distance(cell, mediator_cell) <= 1
                    for cell in component
                    for mediator_cell in mediator_cells
                ) and any(
                    _chebyshev_distance(cell, endpoint_cell) <= 1
                    for cell in component
                    for endpoint_cell in endpoint_cells
                ):
                    bridging_component = frozenset(component)
                    break
            if bridging_component is not None:
                supporting_legs += 1
                evidence_cells.update(bridging_component)
        if supporting_legs >= min(2, group.arity):
            supported.append((color, frozenset(evidence_cells)))
    if len(supported) != 1:
        return None
    return supported[0]


def _hierarchy_connector_color(
    scene: VisualScene,
    group: _AffineChildGroup,
) -> int | None:
    evidence = _hierarchy_connector_evidence(scene, group)
    return evidence[0] if evidence is not None else None


def _hierarchy_connector_state_signature(
    scene: VisualScene,
    group: _AffineChildGroup,
) -> _ConnectorStateSignature:
    evidence = _hierarchy_connector_evidence(scene, group)
    if evidence is None:
        return None
    color, cells = evidence
    return (color, tuple(sorted(cells)))


def _hierarchy_projected_scene(
    scene: VisualScene,
    hierarchy: _AffineHierarchy,
    *,
    positions: dict[str, tuple[int, int]],
    colors: dict[str, int],
) -> VisualScene:
    """Render one observation-derived consequence for exact parser preflight."""

    rows = [list(row) for row in scene.cells]
    initial_dynamic = frozenset(
        cell for child in hierarchy.children for cell in _hierarchy_dynamic_footprint(scene, child)
    )
    for x, y in initial_dynamic:
        rows[y][x] = scene.background

    mediator_centers: dict[str, tuple[int, int]] = {}
    for group in hierarchy.children:
        centers = tuple(positions[endpoint.object_ref] for endpoint in group.endpoints)
        mediator_centers[group.mediator.object_ref] = (
            sum(center[0] for center in centers) // group.arity,
            sum(center[1] for center in centers) // group.arity,
        )
        connector_color = _hierarchy_connector_color(scene, group)
        if connector_color is not None:
            for center in centers:
                for x, y in _raster_line_cells(
                    center,
                    mediator_centers[group.mediator.object_ref],
                ):
                    rows[y][x] = connector_color

    def paint_object(
        item: VisualObject,
        *,
        center: tuple[int, int],
        color: int,
    ) -> None:
        old_x, old_y = item.rounded_center
        for x, y in item.cells:
            rows[center[1] + y - old_y][center[0] + x - old_x] = color
        rows[center[1]][center[0]] = item.center_cell

    for group in hierarchy.children:
        for endpoint in group.endpoints:
            paint_object(
                endpoint,
                center=positions[endpoint.object_ref],
                color=colors[endpoint.object_ref],
            )
        # The official renderer layers each recomputed mediator over its
        # endpoints.  Matching that order makes parser preflight reject a
        # projected layout whenever the mediator would occlude an endpoint.
        paint_object(
            group.mediator,
            center=mediator_centers[group.mediator.object_ref],
            color=group.mediator.color,
        )
    return extract_visual_scene(GridFrame.from_rows(rows))


def _carrier_source_residual_foreground(
    support: _HierarchySourceSupport,
) -> tuple[int, frozenset[tuple[int, int]]]:
    """Derive one exact non-carrier source mask for the Campaign 35 candidate."""

    residual_colors = support.source.palette - {support.example.carrier_color}
    if len(residual_colors) != 1:
        raise ValueError("carrier-source foreground requires one residual source color")
    residual_color = next(iter(residual_colors))
    residual_offsets = support.source.offsets(residual_color)
    residual_cells = frozenset(
        (support.source.center[0] + dx, support.source.center[1] + dy)
        for dx, dy in residual_offsets
    )
    if not residual_offsets or not residual_cells < frozenset(support.source.cells):
        raise ValueError("carrier-source residual mask must be a proper source subset")
    return residual_color, residual_cells


def _carrier_source_residual_foreground_overlay(
    projected: VisualScene,
    hierarchy: _AffineHierarchy,
    supports: tuple[_HierarchySourceSupport, ...],
    *,
    positions: dict[str, tuple[int, int]],
) -> VisualScene:
    """Apply the observation-grounded residual-above-mediator candidate.

    Campaign 35 showed this ordering at one assigned source: a centered
    hierarchy mediator covered the carrier-colored source layer while the exact
    complementary non-carrier mask remained foreground.  Applying the same
    source-relative rule to the assigned counterpart is a bounded candidate
    transfer, not an observed counterpart consequence.  No other projected cell
    is relaxed.
    """

    if tuple(item.child for item in supports) != hierarchy.children:
        raise ValueError("carrier-source supports must retain hierarchy child order")
    rows = [list(row) for row in projected.cells]
    for support in supports:
        endpoint_centers = tuple(
            positions[endpoint.object_ref] for endpoint in support.child.endpoints
        )
        mediator_center = (
            sum(center[0] for center in endpoint_centers) // support.child.arity,
            sum(center[1] for center in endpoint_centers) // support.child.arity,
        )
        if mediator_center != support.source.center:
            continue
        residual_color, residual_cells = _carrier_source_residual_foreground(support)
        for x, y in residual_cells:
            rows[y][x] = residual_color
    return extract_visual_scene(GridFrame.from_rows(rows))


def _carrier_source_residual_foreground_projected_scene(
    scene: VisualScene,
    hierarchy: _AffineHierarchy,
    supports: tuple[_HierarchySourceSupport, ...],
    *,
    positions: dict[str, tuple[int, int]],
    colors: dict[str, int],
) -> VisualScene:
    """Project hierarchy motion plus the bounded residual-foreground candidate."""

    projected = _hierarchy_projected_scene(
        scene,
        hierarchy,
        positions=positions,
        colors=colors,
    )
    return _carrier_source_residual_foreground_overlay(
        projected,
        hierarchy,
        supports,
        positions=positions,
    )


def _carrier_source_carried_projected_scene(
    scene: VisualScene,
    hierarchy: _AffineHierarchy,
    supports: tuple[_HierarchySourceSupport, ...],
    *,
    positions: dict[str, tuple[int, int]],
    colors: dict[str, int],
    carried_support_indexes: frozenset[int],
    fixed_source_centers: dict[int, tuple[int, int]] | None = None,
) -> VisualScene:
    """Project an exact, observation-certified subset of carried sources.

    A carried source is removed before hierarchy rendering so unrelated dynamic
    cells rendered through its old footprint are preserved.  Its complete observed
    cell/color pattern is then translated over its own recomputed child mediator.
    Sources outside the certified subset retain the static residual-overlay model.
    """

    fixed_centers = {} if fixed_source_centers is None else fixed_source_centers
    if tuple(item.child for item in supports) != hierarchy.children:
        raise ValueError("carrier-source supports must retain hierarchy child order")
    if any(index < 0 or index >= len(supports) for index in carried_support_indexes):
        raise ValueError("carried-source subset contains an unknown support")
    if not set(fixed_centers) <= set(carried_support_indexes):
        raise ValueError("fixed source centers must belong to the carried-source subset")
    source_surfaces = tuple(frozenset(support.source.cells) for support in supports)
    if len(frozenset(cell for surface in source_surfaces for cell in surface)) != sum(
        len(surface) for surface in source_surfaces
    ):
        raise ValueError("carrier-source carried projection requires disjoint sources")

    base_rows = [list(row) for row in scene.cells]
    for index in carried_support_indexes:
        for x, y in source_surfaces[index]:
            base_rows[y][x] = scene.background
    source_stripped_scene = extract_visual_scene(GridFrame.from_rows(base_rows))
    projected = _hierarchy_projected_scene(
        source_stripped_scene,
        hierarchy,
        positions=positions,
        colors=colors,
    )
    rows = [list(row) for row in projected.cells]
    for index, support in enumerate(supports):
        if index in carried_support_indexes:
            continue
        endpoint_centers = tuple(
            positions[endpoint.object_ref] for endpoint in support.child.endpoints
        )
        mediator_center = (
            sum(center[0] for center in endpoint_centers) // support.child.arity,
            sum(center[1] for center in endpoint_centers) // support.child.arity,
        )
        if mediator_center == support.source.center:
            residual_color, residual_cells = _carrier_source_residual_foreground(support)
            for x, y in residual_cells:
                rows[y][x] = residual_color

    translated_surfaces: list[frozenset[tuple[int, int]]] = []
    for index in sorted(carried_support_indexes):
        support = supports[index]
        endpoint_centers = tuple(
            positions[endpoint.object_ref] for endpoint in support.child.endpoints
        )
        mediator_center = (
            sum(center[0] for center in endpoint_centers) // support.child.arity,
            sum(center[1] for center in endpoint_centers) // support.child.arity,
        )
        translated_center = fixed_centers.get(index, mediator_center)
        source_x, source_y = support.source.center
        translated = frozenset(
            (translated_center[0] + x - source_x, translated_center[1] + y - source_y)
            for x, y in support.source.cells
        )
        if (
            len(translated) != len(support.source.cells)
            or not _hierarchy_cells_in_bounds(scene, translated)
            or any(translated & prior for prior in translated_surfaces)
        ):
            raise ValueError("carrier-source carried projection is not a unique safe translation")
        translated_surfaces.append(translated)
        for x, y in support.source.cells:
            translated_x = translated_center[0] + x - source_x
            translated_y = translated_center[1] + y - source_y
            rows[translated_y][translated_x] = scene.cells[y][x]
    return extract_visual_scene(GridFrame.from_rows(rows))


def _same_child_composite_cargo_source_keys(
    relation: _CompositeBridgeRelation,
) -> tuple[_CompositeCargoSourceKey, ...]:
    """Return the finite source identity carried by one bridge relation."""

    return tuple(
        (child_index, source_index)
        for child_index, (_child, example) in enumerate(relation.assignments)
        for source_index, _source in enumerate(example.sources)
    )


def _same_child_composite_cargo_endpoint_marker_color(
    hierarchy: _AffineHierarchy,
) -> int | None:
    """Return the one center-cell marker shared by every observed endpoint glyph."""

    marker_colors = {
        endpoint.center_cell for child in hierarchy.children for endpoint in child.endpoints
    }
    return next(iter(marker_colors)) if len(marker_colors) == 1 else None


def _same_child_composite_cargo_visible_endpoints(
    scene: VisualScene,
    *,
    marker_color: int,
) -> tuple[VisualObject, ...]:
    """Exclude carrier-source fragments that the base shape parser labels as endpoints."""

    return tuple(endpoint for endpoint in scene.endpoints if endpoint.center_cell == marker_color)


def _same_child_composite_cargo_delivered_child_indexes(
    hierarchy: _AffineHierarchy,
    relation: _CompositeBridgeRelation,
    *,
    positions: dict[str, tuple[int, int]],
    collected_source_keys: frozenset[_CompositeCargoSourceKey],
) -> frozenset[int]:
    """Identify exact local deliveries without inferring a global terminal result."""

    mediator_centers = _same_child_composite_cargo_mediator_centers(hierarchy, positions)
    return frozenset(
        child_index
        for child_index, (_child, example) in enumerate(relation.assignments)
        if mediator_centers[child_index] == example.target.rounded_center
        and all(
            (child_index, source_index) in collected_source_keys
            for source_index, _source in enumerate(example.sources)
        )
    )


def _same_child_composite_cargo_relation_is_well_formed(
    scene: VisualScene,
    hierarchy: _AffineHierarchy,
    relation: _CompositeBridgeRelation,
) -> bool:
    """Revalidate the exact complementary-source evidence consumed by the route."""

    if (
        len(relation.assignments) < 2
        or tuple(child for child, _example in relation.assignments) != hierarchy.children
        or _same_child_composite_cargo_endpoint_marker_color(hierarchy) is None
        or len({example.target.rounded_center for _child, example in relation.assignments})
        != len(relation.assignments)
    ):
        return False
    source_surfaces: list[frozenset[tuple[int, int]]] = []
    for child, example in relation.assignments:
        if (
            example.carrier_color != child.mediator.color
            or not 2 <= len(example.sources) <= 6
            or len(example.residual_colors) != len(example.sources)
            or len(set(example.residual_colors)) != len(example.residual_colors)
            or frozenset(scene.cells[y][x] for x, y in example.target.cells)
            != frozenset(example.residual_colors)
            or not _bridge_target_matches_sources(
                scene,
                sources=example.sources,
                residual_colors=example.residual_colors,
                target=example.target,
            )
        ):
            return False
        carrier_masks: list[frozenset[tuple[int, int]]] = []
        for source, residual_color in zip(
            example.sources,
            example.residual_colors,
            strict=True,
        ):
            residuals = source.palette - {example.carrier_color}
            surface = frozenset(source.cells)
            if (
                residuals != {residual_color}
                or source.offsets(residual_color) == frozenset()
                or source.offsets(example.carrier_color) == frozenset()
                or surface
                != _translated_object_footprint(
                    child.mediator,
                    center=source.center,
                )
            ):
                return False
            carrier_masks.append(source.offsets(example.carrier_color))
            source_surfaces.append(surface)
        residual_union = frozenset(
            offset
            for source, residual_color in zip(
                example.sources,
                example.residual_colors,
                strict=True,
            )
            for offset in source.offsets(residual_color)
        )
        carrier_union = frozenset(offset for mask in carrier_masks for offset in mask)
        if (
            residual_union != _COMPOSITE_MEDIATOR_OFFSETS
            or carrier_union != _COMPOSITE_MEDIATOR_OFFSETS
            or (len(carrier_masks) == 2 and bool(carrier_masks[0] & carrier_masks[1]))
        ):
            return False
    return len(frozenset(cell for surface in source_surfaces for cell in surface)) == sum(
        len(surface) for surface in source_surfaces
    )


def _same_child_composite_cargo_projected_scene(
    scene: VisualScene,
    hierarchy: _AffineHierarchy,
    relation: _CompositeBridgeRelation,
    *,
    positions: dict[str, tuple[int, int]],
    colors: dict[str, int],
    collected_source_keys: frozenset[_CompositeCargoSourceKey],
) -> VisualScene:
    """Project complementary residual masks accumulated on their assigned child.

    The child's observed mediator supplies the carrier-colored disk.  Contact with
    an uncollected assigned source exposes that source's residual mask.  Once the
    child leaves the source, the source is removed from its original location and
    its residual mask remains over the moving mediator.  The witnessed masks
    therefore replace the carrier disk without inventing a color, shape, source,
    or destination.  Later observed source layers cover any interior overlap;
    exact target sectors remain uniquely owned.  Once every assigned mask reaches
    its exact ring, the observed carrier color consumes that ring locally; this
    earns continuation for the other child but does not imply level completion.
    """

    if not _same_child_composite_cargo_relation_is_well_formed(scene, hierarchy, relation):
        raise ValueError("same-child composite cargo requires one exact bridge relation")
    source_keys = frozenset(_same_child_composite_cargo_source_keys(relation))
    if not collected_source_keys <= source_keys:
        raise ValueError("same-child composite cargo contains an unknown source key")
    endpoint_refs = {
        endpoint.object_ref for child in hierarchy.children for endpoint in child.endpoints
    }
    if set(positions) != endpoint_refs or set(colors) != endpoint_refs:
        raise ValueError("same-child composite cargo requires the complete endpoint state")

    base_rows = [list(row) for row in scene.cells]
    for child_index, source_index in sorted(collected_source_keys):
        source = relation.assignments[child_index][1].sources[source_index]
        for x, y in source.cells:
            base_rows[y][x] = scene.background
    source_stripped_scene = extract_visual_scene(GridFrame.from_rows(base_rows))
    projected = _hierarchy_projected_scene(
        source_stripped_scene,
        hierarchy,
        positions=positions,
        colors=colors,
    )
    rows = [list(row) for row in projected.cells]
    initial_dynamic = frozenset(
        cell for child in hierarchy.children for cell in _hierarchy_dynamic_footprint(scene, child)
    )
    consumable_cells = frozenset(
        cell
        for _child, example in relation.assignments
        for source in example.sources
        for cell in source.cells
    ) | frozenset(cell for _child, example in relation.assignments for cell in example.target.cells)
    protected_static = (
        frozenset(
            (x, y)
            for y, row in enumerate(scene.cells)
            for x, value in enumerate(row)
            if value != scene.background
        )
        - initial_dynamic
        - consumable_cells
    )
    # Connectors are a relation layer, not authority to erase an unrelated
    # foreground glyph.  Endpoint and mediator footprints are collision-checked
    # separately; restore only the static pixels a connector may cross behind.
    for x, y in protected_static:
        rows[y][x] = scene.cells[y][x]
    # Static source glyphs remain above a passing connector.  Exact mediator
    # contact is the only witnessed source interaction, so restore an
    # uncollected source unless its assigned child is centered on it.
    mediator_centers: dict[int, tuple[int, int]] = {}
    for child_index, (_child, example) in enumerate(relation.assignments):
        endpoint_centers = tuple(
            positions[endpoint.object_ref] for endpoint in hierarchy.children[child_index].endpoints
        )
        mediator_center = (
            sum(center[0] for center in endpoint_centers) // hierarchy.children[child_index].arity,
            sum(center[1] for center in endpoint_centers) // hierarchy.children[child_index].arity,
        )
        mediator_centers[child_index] = mediator_center
        for source_index, source in enumerate(example.sources):
            if (
                child_index,
                source_index,
            ) in collected_source_keys or mediator_center == source.center:
                continue
            for x, y in source.cells:
                rows[y][x] = scene.cells[y][x]
    # The assigned ring is likewise a fixed foreground surface.  Cargo can
    # match it exactly, but a connector passing behind it cannot mutate it.
    for _child, example in relation.assignments:
        for x, y in example.target.cells:
            rows[y][x] = scene.cells[y][x]
    overlays: dict[tuple[int, int], int] = {}
    overlay_lineage: dict[tuple[int, int], tuple[int, int, bool]] = {}
    for child_index, (_child, example) in enumerate(relation.assignments):
        mediator_center = mediator_centers[child_index]
        for source_index, (source, residual_color) in enumerate(
            zip(example.sources, example.residual_colors, strict=True)
        ):
            source_key = (child_index, source_index)
            if source_key not in collected_source_keys and mediator_center != source.center:
                continue
            transported = source_key in collected_source_keys and mediator_center != source.center
            for dx, dy in source.offsets(residual_color):
                cell = (mediator_center[0] + dx, mediator_center[1] + dy)
                if not (0 < cell[0] < scene.width - 1 and 0 < cell[1] < scene.height - 1):
                    raise ValueError("same-child composite cargo residual left the board")
                prior = overlays.get(cell)
                if prior is not None and prior != residual_color and len(example.sources) == 2:
                    raise ValueError("paired same-child cargo residual masks overlap")
                overlays[cell] = residual_color
                overlay_lineage[cell] = (child_index, source_index, transported)
    for (x, y), color in overlays.items():
        rows[y][x] = color

    delivered_child_indexes = _same_child_composite_cargo_delivered_child_indexes(
        hierarchy,
        relation,
        positions=positions,
        collected_source_keys=collected_source_keys,
    )
    # One returned consequence placed a binary child's connector ingress above
    # its earliest transported residual after another child had already delivered.
    # A later returned consequence retained the next observed source layer above
    # that same ingress.  Preserve the source-layer lineage so the connector is
    # composed with only the earliest transported layer and later source layers
    # can occlude it.  Earlier returned consequences retain residual precedence
    # for the ternary child, including the same offsets and connector directions.
    # Restrict the exception to that observed structural phase and the exact
    # residual/own-child-connector intersection.  The mediator center and carrier-
    # colored remainder of its footprint stay hierarchy-rendered; endpoints and
    # retained static/source/target surfaces stay foreground.
    retained_source_cells = frozenset(
        cell
        for child_index, (_child, example) in enumerate(relation.assignments)
        for source_index, source in enumerate(example.sources)
        if (child_index, source_index) not in collected_source_keys
        or mediator_centers[child_index] == source.center
        for cell in source.cells
    )
    assigned_target_cells = frozenset(
        cell for _child, example in relation.assignments for cell in example.target.cells
    )
    endpoint_cells = frozenset(
        cell
        for child in hierarchy.children
        for endpoint in child.endpoints
        for cell in _translated_object_footprint(
            endpoint,
            center=positions[endpoint.object_ref],
        )
    )
    connector_protected = (
        protected_static
        | retained_source_cells
        | assigned_target_cells
        | endpoint_cells
        | frozenset(mediator_centers.values())
    )
    connector_layers: dict[int, tuple[int, frozenset[tuple[int, int]]]] = {}
    for child_index, child in enumerate(hierarchy.children):
        if child.arity != 2 or not any(
            delivered_index != child_index for delivered_index in delivered_child_indexes
        ):
            continue
        connector_color = _hierarchy_connector_color(scene, child)
        if connector_color is None:
            continue
        connector_layers[child_index] = (
            connector_color,
            frozenset(
                cell
                for endpoint in child.endpoints
                for cell in _raster_line_cells(
                    positions[endpoint.object_ref],
                    mediator_centers[child_index],
                )
            ),
        )
    first_transported_source_index_by_child = {
        child_index: min(
            source_index
            for source_index, source in enumerate(example.sources)
            if (child_index, source_index) in collected_source_keys
            and mediator_centers[child_index] != source.center
        )
        for child_index, (_child, example) in enumerate(relation.assignments)
        if any(
            (child_index, source_index) in collected_source_keys
            and mediator_centers[child_index] != source.center
            for source_index, source in enumerate(example.sources)
        )
    }
    for cell, (child_index, source_index, transported) in overlay_lineage.items():
        connector_layer = connector_layers.get(child_index)
        if (
            not transported
            or connector_layer is None
            or source_index != first_transported_source_index_by_child[child_index]
            or cell in connector_protected
        ):
            continue
        connector_color, connector_cells = connector_layer
        if cell in connector_cells:
            x, y = cell
            rows[y][x] = connector_color
    for child_index in delivered_child_indexes:
        child, example = relation.assignments[child_index]
        for x, y in example.target.cells:
            rows[y][x] = child.mediator.color
    return extract_visual_scene(GridFrame.from_rows(rows))


def _hierarchy_cells_in_bounds(scene: VisualScene, cells: frozenset[tuple[int, int]]) -> bool:
    return all(0 < x < scene.width - 1 and 0 < y < scene.height - 1 for x, y in cells)


def _hierarchy_avoids_target_regions(
    cells: frozenset[tuple[int, int]],
    target_regions: _TargetRegions,
) -> bool:
    return all(not (cells & region) for _center, region in target_regions)


def _footprints_have_gap(
    left: frozenset[tuple[int, int]],
    right: frozenset[tuple[int, int]],
    *,
    gap: int,
) -> bool:
    return all(
        max(abs(left_x - right_x), abs(left_y - right_y)) > gap
        for left_x, left_y in left
        for right_x, right_y in right
    )


def _hierarchy_endpoint_orders(
    group: _AffineChildGroup,
    *,
    active_ref: str | None,
) -> tuple[tuple[VisualObject, ...], ...]:
    ordered = tuple(sorted(group.endpoints, key=lambda item: item.object_ref))
    if active_ref is not None:
        active = tuple(item for item in ordered if item.object_ref == active_ref)
        if len(active) != 1:
            return ()
        remainder = tuple(item for item in ordered if item.object_ref != active_ref)
        return tuple((active[0], *tail) for tail in itertools.permutations(remainder))
    # Six endpoints admit 720 orders.  The finite cap retains several choices
    # for every possible activation endpoint without turning planning into an
    # exhaustive interaction search.
    by_first: list[tuple[VisualObject, ...]] = []
    for first in ordered:
        remainder = tuple(item for item in ordered if item.object_ref != first.object_ref)
        by_first.extend(
            (first, *tail) for tail in itertools.islice(itertools.permutations(remainder), 20)
        )
    return tuple(by_first[:120])


def _regular_exact_centroid_points(
    center: tuple[int, int],
    *,
    arity: int,
    radius: int,
    rotation_index: int,
) -> tuple[tuple[int, int], ...] | None:
    direction = -1 if rotation_index >= 32 else 1
    rotation = (2 * math.pi * (rotation_index % 32)) / 32
    points = tuple(
        (
            round(
                center[0] + radius * math.cos(rotation + direction * 2 * math.pi * index / arity)
            ),
            round(
                center[1] + radius * math.sin(rotation + direction * 2 * math.pi * index / arity)
            ),
        )
        for index in range(arity)
    )
    if (
        len(set(points)) != arity
        or sum(point[0] for point in points) != arity * center[0]
        or sum(point[1] for point in points) != arity * center[1]
    ):
        return None
    return points


def _hierarchy_child_layouts(
    scene: VisualScene,
    hierarchy: _AffineHierarchy,
    group: _AffineChildGroup,
    *,
    support: tuple[int, int],
    active_ref: str | None,
    static_cells: frozenset[tuple[int, int]],
    target_regions: _TargetRegions,
    endpoint_target_regions: _TargetRegions | None = None,
    ignored_refs: frozenset[str],
    search_budget: _HierarchySearchBudget,
    result_limit: int = _MAX_HIERARCHY_CHILD_LAYOUTS,
) -> tuple[_HierarchyChildLayout, ...]:
    del ignored_refs
    if endpoint_target_regions is None:
        endpoint_target_regions = target_regions
    if result_limit < 1:
        return ()
    layouts: list[_HierarchyChildLayout] = []
    mover_orders = _hierarchy_endpoint_orders(group, active_ref=active_ref)
    for radius in range(6, 28):
        for rotation_index in range(64):
            for movers in mover_orders:
                search_budget.consume()
                points = _regular_exact_centroid_points(
                    support,
                    arity=group.arity,
                    radius=radius,
                    rotation_index=rotation_index,
                )
                if points is None:
                    continue
                endpoint_footprints = tuple(
                    _translated_object_footprint(mover, center=point)
                    for mover, point in zip(movers, points, strict=True)
                )
                if any(
                    not _hierarchy_cells_in_bounds(scene, footprint)
                    or footprint & static_cells
                    or not _hierarchy_avoids_target_regions(
                        footprint,
                        endpoint_target_regions,
                    )
                    for footprint in endpoint_footprints
                ):
                    continue
                if any(
                    not _footprints_have_gap(left, right, gap=1)
                    for left, right in itertools.combinations(endpoint_footprints, 2)
                ):
                    continue
                dynamic = _hierarchy_projected_group_footprint(
                    group,
                    endpoint_centers=points,
                    mediator_center=support,
                    endpoints=movers,
                )
                if (
                    not _hierarchy_cells_in_bounds(scene, dynamic)
                    or dynamic & static_cells
                    or not _hierarchy_avoids_target_regions(dynamic, target_regions)
                ):
                    continue
                movement_cost = sum(
                    _distance(mover.rounded_center, point)
                    for mover, point in zip(movers, points, strict=True)
                )
                if any(
                    mover.rounded_center == point
                    for mover, point in zip(movers, points, strict=True)
                ):
                    # A PROGRESS click is a claimed placement intervention.  Do
                    # not emit role-animation-only clicks for endpoints already
                    # at their projected locations.
                    continue
                layouts.append(
                    _HierarchyChildLayout(
                        group=group,
                        support=support,
                        movers=movers,
                        points=points,
                        dynamic_footprint=dynamic,
                        radius=radius,
                        movement_cost=movement_cost,
                    )
                )
        # Finish a whole shell before applying the cap so every rotation and
        # activation order at the smallest feasible radius is represented.
        if len(layouts) >= 256:
            break
    layouts.sort(
        key=lambda item: (
            -_distance(
                item.movers[0].rounded_center,
                item.group.mediator.rounded_center,
            ),
            tuple(
                _distance(mover.rounded_center, item.group.mediator.rounded_center)
                for mover in item.movers[1:]
            ),
            item.radius,
            item.movement_cost,
            item.points,
            tuple(mover.object_ref for mover in item.movers),
        )
    )
    # The joint parser check is deliberately expensive.  Preserve a fair
    # radius shell above, then keep only the best bounded *distinct*
    # discriminators for each child.  Several rotations can round to the same
    # ordered endpoint geometry; applying the cap before deduplication would
    # let those aliases hide a later viable layout.
    distinct_layouts: list[_HierarchyChildLayout] = []
    seen_layouts: set[tuple[tuple[str, ...], tuple[tuple[int, int], ...]]] = set()
    for layout in layouts:
        identity = (
            tuple(item.object_ref for item in layout.movers),
            layout.points,
        )
        if identity in seen_layouts:
            continue
        seen_layouts.add(identity)
        distinct_layouts.append(layout)
        if len(distinct_layouts) == result_limit:
            break
    return tuple(distinct_layouts)


def _fair_index_products(
    lengths: tuple[int, ...],
    *,
    limit: int,
) -> tuple[tuple[int, ...], ...]:
    """Return a bounded diagonal traversal instead of a lexicographic prefix."""

    if limit < 1 or not lengths or any(length < 1 for length in lengths):
        return ()
    start = tuple(0 for _length in lengths)
    frontier: list[tuple[int, tuple[int, ...]]] = [(0, start)]
    seen = {start}
    result: list[tuple[int, ...]] = []
    while frontier and len(result) < limit:
        _rank, indices = heapq.heappop(frontier)
        result.append(indices)
        for axis, length in enumerate(lengths):
            if indices[axis] + 1 >= length:
                continue
            advanced = list(indices)
            advanced[axis] += 1
            candidate = tuple(advanced)
            if candidate in seen:
                continue
            seen.add(candidate)
            heapq.heappush(frontier, (sum(candidate), candidate))
    return tuple(result)


def _fair_support_orders(
    hierarchy: _AffineHierarchy,
    raw_supports: tuple[tuple[int, int], ...],
    *,
    limit: int,
) -> tuple[tuple[tuple[int, int], ...], ...]:
    """Round-robin the active child's support before applying the global cap."""

    if limit < 1 or len(raw_supports) != len(hierarchy.children):
        return ()

    def assignment_cost(supports: tuple[tuple[int, int], ...]) -> float:
        return sum(
            _distance(group.mediator.rounded_center, support)
            for group, support in zip(hierarchy.children, supports, strict=True)
        )

    buckets: list[tuple[tuple[tuple[int, int], ...], ...]] = []
    for first_support in raw_supports:
        remainder = tuple(item for item in raw_supports if item != first_support)
        assignments = tuple(
            sorted(
                ((first_support, *tail) for tail in itertools.permutations(remainder)),
                key=lambda supports: (assignment_cost(supports), supports),
            )
        )
        buckets.append(assignments)
    buckets.sort(
        key=lambda items: (
            assignment_cost(items[0]),
            items[0],
        )
    )
    result: list[tuple[tuple[int, int], ...]] = []
    for rank in range(max(len(items) for items in buckets)):
        for items in buckets:
            if rank >= len(items):
                continue
            result.append(items[rank])
            if len(result) == limit:
                return tuple(result)
    return tuple(result)


def _hierarchy_projected_state_is_safe(
    scene: VisualScene,
    hierarchy: _AffineHierarchy,
    *,
    positions: dict[str, tuple[int, int]],
    colors: dict[str, int],
    static_cells: frozenset[tuple[int, int]],
    target_regions: _TargetRegions,
    search_budget: _HierarchySearchBudget,
) -> bool:
    group_dynamic: list[frozenset[tuple[int, int]]] = []
    mediator_footprints: list[frozenset[tuple[int, int]]] = []
    endpoint_footprints: list[tuple[str, frozenset[tuple[int, int]]]] = []
    for group in hierarchy.children:
        centers = tuple(positions[item.object_ref] for item in group.endpoints)
        mediator_center = (
            sum(center[0] for center in centers) // group.arity,
            sum(center[1] for center in centers) // group.arity,
        )
        dynamic = _hierarchy_projected_group_footprint(
            group,
            endpoint_centers=centers,
            mediator_center=mediator_center,
        )
        if (
            not _hierarchy_cells_in_bounds(scene, dynamic)
            or dynamic & static_cells
            or not _hierarchy_avoids_target_regions(dynamic, target_regions)
        ):
            return False
        group_dynamic.append(dynamic)
        mediator_footprints.append(
            _translated_object_footprint(group.mediator, center=mediator_center)
        )
        endpoint_footprints.extend(
            (endpoint.object_ref, _translated_object_footprint(endpoint, center=center))
            for endpoint, center in zip(group.endpoints, centers, strict=True)
        )
    if any(left & right for left, right in itertools.combinations(group_dynamic, 2)):
        return False
    if any(
        not _footprints_have_gap(left, right, gap=1)
        for left, right in itertools.combinations(mediator_footprints, 2)
    ):
        return False
    for (left_ref, left), (right_ref, right) in itertools.combinations(endpoint_footprints, 2):
        if colors[left_ref] == colors[right_ref] and not _footprints_have_gap(
            left,
            right,
            gap=1,
        ):
            return False
    projected = _hierarchy_projected_scene(
        scene,
        hierarchy,
        positions=positions,
        colors=colors,
    )
    return bool(
        len(projected.endpoints) == len(scene.endpoints)
        and len(projected.mediators) == len(scene.mediators)
        and set(_visible_target_regions(projected)) == set(_visible_target_regions(scene))
        and _unique_affine_hierarchy(
            projected,
            active_color=hierarchy.active_color,
            search_budget=search_budget,
        )
        is not None
    )


def _hierarchy_sequence_is_safe(
    scene: VisualScene,
    hierarchy: _AffineHierarchy,
    layouts: tuple[_HierarchyChildLayout, ...],
    *,
    static_cells: frozenset[tuple[int, int]],
    target_regions: _TargetRegions,
    search_budget: _HierarchySearchBudget,
    support_weights: tuple[int, ...] | None = None,
) -> bool:
    """Validate every projected move and role exchange, not only the endpoint."""

    if tuple(layout.group for layout in layouts) != hierarchy.children:
        return False
    if any(
        mover.rounded_center == point
        for layout in layouts
        for mover, point in zip(layout.movers, layout.points, strict=True)
    ):
        return False
    positions = {
        endpoint.object_ref: endpoint.rounded_center
        for child in hierarchy.children
        for endpoint in child.endpoints
    }
    colors = {
        endpoint.object_ref: endpoint.color
        for child in hierarchy.children
        for endpoint in child.endpoints
    }
    active = tuple(ref for ref, color in colors.items() if color == hierarchy.active_color)
    if len(active) != 1:
        return False
    active_ref = active[0]
    if not _hierarchy_projected_state_is_safe(
        scene,
        hierarchy,
        positions=positions,
        colors=colors,
        static_cells=static_cells,
        target_regions=target_regions,
        search_budget=search_budget,
    ):
        return False

    for child_index, layout in enumerate(layouts):
        if child_index:
            selected_ref = layout.movers[0].object_ref
            if selected_ref == active_ref or colors[selected_ref] == hierarchy.active_color:
                return False
            colors[active_ref], colors[selected_ref] = colors[selected_ref], colors[active_ref]
            active_ref = selected_ref
        if layout.movers[0].object_ref != active_ref:
            return False
        for mover_index, (mover, point) in enumerate(
            zip(layout.movers, layout.points, strict=True)
        ):
            if mover.object_ref != active_ref:
                return False
            positions[active_ref] = point
            if not _hierarchy_projected_state_is_safe(
                scene,
                hierarchy,
                positions=positions,
                colors=colors,
                static_cells=static_cells,
                target_regions=target_regions,
                search_budget=search_budget,
            ):
                return False
            if mover_index + 1 < len(layout.movers):
                selected_ref = layout.movers[mover_index + 1].object_ref
                if selected_ref == active_ref or colors[selected_ref] == hierarchy.active_color:
                    return False
                colors[active_ref], colors[selected_ref] = colors[selected_ref], colors[active_ref]
                active_ref = selected_ref
        final_centers = tuple(positions[item.object_ref] for item in layout.group.endpoints)
        final_mediator = (
            sum(center[0] for center in final_centers) // layout.group.arity,
            sum(center[1] for center in final_centers) // layout.group.arity,
        )
        if final_mediator != layout.support:
            return False

    supports = tuple(layout.support for layout in layouts)
    weights = tuple(1 for _support in supports) if support_weights is None else support_weights
    if len(weights) != len(supports) or any(weight < 1 for weight in weights):
        return False
    total_weight = sum(weights)
    target = hierarchy.target.rounded_center
    return (
        len(set(supports)) == len(supports)
        and sum(weight * item[0] for weight, item in zip(weights, supports, strict=True))
        == total_weight * target[0]
        and sum(weight * item[1] for weight, item in zip(weights, supports, strict=True))
        == total_weight * target[1]
    )


def _projected_hierarchy_lineages_match(
    scene: VisualScene,
    projected: VisualScene,
    hierarchy: _AffineHierarchy,
    *,
    positions: dict[str, tuple[int, int]],
    colors: dict[str, int],
    mediator_centers: dict[str, tuple[int, int]],
) -> bool:
    """Require every projected endpoint, mediator, and connector lineage exactly."""

    expected_endpoint_signatures = {
        endpoint.object_ref: _visual_object_state_signature(
            endpoint,
            position=positions[endpoint.object_ref],
            color=colors[endpoint.object_ref],
        )
        for child in hierarchy.children
        for endpoint in child.endpoints
    }
    observed_endpoints = {
        _visual_object_state_signature(endpoint): endpoint for endpoint in projected.endpoints
    }
    expected_mediator_signatures = {
        child.mediator.object_ref: _visual_object_state_signature(
            child.mediator,
            position=mediator_centers[child.mediator.object_ref],
        )
        for child in hierarchy.children
    }
    observed_mediators = {
        _visual_object_state_signature(mediator): mediator for mediator in projected.mediators
    }
    if (
        len(expected_endpoint_signatures) != len(projected.endpoints)
        or len(observed_endpoints) != len(projected.endpoints)
        or set(expected_endpoint_signatures.values()) != set(observed_endpoints)
        or len(expected_mediator_signatures) != len(projected.mediators)
        or len(observed_mediators) != len(projected.mediators)
        or set(expected_mediator_signatures.values()) != set(observed_mediators)
    ):
        return False
    active = tuple(item for item in projected.endpoints if item.color == hierarchy.active_color)
    if len(active) != 1:
        return False
    for child in hierarchy.children:
        projected_group = _AffineChildGroup(
            mediator=observed_mediators[expected_mediator_signatures[child.mediator.object_ref]],
            endpoints=tuple(
                observed_endpoints[expected_endpoint_signatures[endpoint.object_ref]]
                for endpoint in child.endpoints
            ),
        )
        if _hierarchy_connector_color(projected, projected_group) != _hierarchy_connector_color(
            scene,
            child,
        ):
            return False
    return True


def _residual_linked_projected_state_is_safe(
    scene: VisualScene,
    hierarchy: _AffineHierarchy,
    supports: tuple[_HierarchyTargetSupport, ...],
    *,
    positions: dict[str, tuple[int, int]],
    colors: dict[str, int],
    static_cells: frozenset[tuple[int, int]],
    dynamic_target_regions: _TargetRegions,
    endpoint_target_regions: _TargetRegions,
    preserved_target_signature: _TargetSurfaceSignature,
    search_budget: _HierarchySearchBudget,
) -> bool:
    """Certify one target-support state while permitting only assigned interiors."""

    support_by_mediator = {item.child.mediator.object_ref: item for item in supports}
    if tuple(item.child for item in supports) != hierarchy.children or len(
        support_by_mediator
    ) != len(hierarchy.children):
        return False
    group_dynamic: list[frozenset[tuple[int, int]]] = []
    mediator_centers: dict[str, tuple[int, int]] = {}
    mediator_footprints: list[frozenset[tuple[int, int]]] = []
    endpoint_footprints: list[tuple[str, frozenset[tuple[int, int]]]] = []
    for child in hierarchy.children:
        support = support_by_mediator.get(child.mediator.object_ref)
        if support is None:
            return False
        centers = tuple(positions[item.object_ref] for item in child.endpoints)
        mediator_center = (
            sum(center[0] for center in centers) // child.arity,
            sum(center[1] for center in centers) // child.arity,
        )
        mediator_centers[child.mediator.object_ref] = mediator_center
        endpoints = tuple(
            _translated_object_footprint(endpoint, center=center)
            for endpoint, center in zip(child.endpoints, centers, strict=True)
        )
        if any(
            not _hierarchy_cells_in_bounds(scene, footprint)
            or footprint & static_cells
            or not _hierarchy_avoids_target_regions(footprint, endpoint_target_regions)
            for footprint in endpoints
        ) or any(
            not _footprints_have_gap(left, right, gap=1)
            for left, right in itertools.combinations(endpoints, 2)
        ):
            return False
        dynamic = _hierarchy_projected_group_footprint(
            child,
            endpoint_centers=centers,
            mediator_center=mediator_center,
        )
        if (
            not _hierarchy_cells_in_bounds(scene, dynamic)
            or dynamic & static_cells
            or not _hierarchy_avoids_target_regions(dynamic, dynamic_target_regions)
        ):
            return False
        group_dynamic.append(dynamic)
        mediator_footprints.append(
            _translated_object_footprint(child.mediator, center=mediator_center)
        )
        endpoint_footprints.extend(
            (endpoint.object_ref, footprint)
            for endpoint, footprint in zip(child.endpoints, endpoints, strict=True)
        )
        if mediator_center == support.target.rounded_center and any(
            (x, y) in dynamic for x, y in support.target.cells
        ):
            return False

    if any(left & right for left, right in itertools.combinations(group_dynamic, 2)) or any(
        not _footprints_have_gap(left, right, gap=1)
        for left, right in itertools.combinations(mediator_footprints, 2)
    ):
        return False
    for (left_ref, left), (right_ref, right) in itertools.combinations(
        endpoint_footprints,
        2,
    ):
        if colors[left_ref] == colors[right_ref] and not _footprints_have_gap(
            left,
            right,
            gap=1,
        ):
            return False

    projected = _hierarchy_projected_scene(
        scene,
        hierarchy,
        positions=positions,
        colors=colors,
    )
    sink_centers = frozenset(item.target.rounded_center for item in supports)
    projected_preserved = tuple(
        item for item in _target_surface_signature(projected) if item[1] not in sink_centers
    )
    if projected_preserved != preserved_target_signature:
        return False
    projected_composite = _composite_sparse_targets(projected)
    for support in supports:
        if any(projected.cells[y][x] != scene.cells[y][x] for x, y in support.target.cells):
            return False
        target_still_hollow = any(
            item.rounded_center == support.target.rounded_center
            and signature == support.surface_signature
            for item, signature in projected_composite
        )
        if target_still_hollow != (
            mediator_centers[support.child.mediator.object_ref] != support.target.rounded_center
        ):
            return False

    projected_regions = {
        item for item in _visible_target_regions(projected) if item[0] not in sink_centers
    }
    original_regions = {
        item for item in _visible_target_regions(scene) if item[0] not in sink_centers
    }
    if projected_regions != original_regions:
        return False
    search_budget.consume()
    return _projected_hierarchy_lineages_match(
        scene,
        projected,
        hierarchy,
        positions=positions,
        colors=colors,
        mediator_centers=mediator_centers,
    )


def _carrier_source_occlusion_projected_state_is_safe(
    scene: VisualScene,
    hierarchy: _AffineHierarchy,
    supports: tuple[_HierarchySourceSupport, ...],
    *,
    positions: dict[str, tuple[int, int]],
    colors: dict[str, int],
    static_cells: frozenset[tuple[int, int]],
    target_regions: _TargetRegions,
    preserved_target_signature: _TargetSurfaceSignature,
    search_budget: _HierarchySearchBudget,
) -> bool:
    """Certify one transient with only exact assigned-source occlusion allowed."""

    support_by_mediator = {item.child.mediator.object_ref: item for item in supports}
    assigned_surfaces = tuple(frozenset(item.source.cells) for item in supports)
    assigned_cells = frozenset(cell for surface in assigned_surfaces for cell in surface)
    if (
        tuple(item.child for item in supports) != hierarchy.children
        or len(support_by_mediator) != len(hierarchy.children)
        or len(assigned_cells) != sum(len(surface) for surface in assigned_surfaces)
        or any(len(surface) != len(_COMPOSITE_MEDIATOR_OFFSETS) for surface in assigned_surfaces)
    ):
        return False

    group_dynamic: list[frozenset[tuple[int, int]]] = []
    mediator_centers: dict[str, tuple[int, int]] = {}
    mediator_footprints: list[frozenset[tuple[int, int]]] = []
    endpoint_footprints: list[tuple[str, frozenset[tuple[int, int]]]] = []
    for child in hierarchy.children:
        support = support_by_mediator.get(child.mediator.object_ref)
        if support is None:
            return False
        centers = tuple(positions[item.object_ref] for item in child.endpoints)
        mediator_center = (
            sum(center[0] for center in centers) // child.arity,
            sum(center[1] for center in centers) // child.arity,
        )
        mediator_centers[child.mediator.object_ref] = mediator_center
        endpoints = tuple(
            _translated_object_footprint(endpoint, center=center)
            for endpoint, center in zip(child.endpoints, centers, strict=True)
        )
        if any(
            not _hierarchy_cells_in_bounds(scene, footprint)
            or footprint & static_cells
            or footprint & assigned_cells
            or not _hierarchy_avoids_target_regions(footprint, target_regions)
            for footprint in endpoints
        ) or any(
            not _footprints_have_gap(left, right, gap=1)
            for left, right in itertools.combinations(endpoints, 2)
        ):
            return False

        mediator_footprint = _translated_object_footprint(
            child.mediator,
            center=mediator_center,
        )
        own_surface = frozenset(support.source.cells)
        dynamic = _hierarchy_projected_group_footprint(
            child,
            endpoint_centers=centers,
            mediator_center=mediator_center,
        )
        if (
            not _hierarchy_cells_in_bounds(scene, dynamic)
            or dynamic & static_cells
            or not _hierarchy_avoids_target_regions(dynamic, target_regions)
            or any(dynamic & surface for surface in assigned_surfaces if surface != own_surface)
        ):
            return False
        own_intersection = dynamic & own_surface
        if mediator_center == support.source.center:
            if mediator_footprint != own_surface or own_intersection != own_surface:
                return False
        elif own_intersection:
            return False

        group_dynamic.append(dynamic)
        mediator_footprints.append(mediator_footprint)
        endpoint_footprints.extend(
            (endpoint.object_ref, footprint)
            for endpoint, footprint in zip(child.endpoints, endpoints, strict=True)
        )

    if any(left & right for left, right in itertools.combinations(group_dynamic, 2)) or any(
        not _footprints_have_gap(left, right, gap=1)
        for left, right in itertools.combinations(mediator_footprints, 2)
    ):
        return False
    for (left_ref, left), (right_ref, right) in itertools.combinations(
        endpoint_footprints,
        2,
    ):
        if colors[left_ref] == colors[right_ref] and not _footprints_have_gap(
            left,
            right,
            gap=1,
        ):
            return False

    latent_projected = _hierarchy_projected_scene(
        scene,
        hierarchy,
        positions=positions,
        colors=colors,
    )
    projected = _carrier_source_residual_foreground_overlay(
        latent_projected,
        hierarchy,
        supports,
        positions=positions,
    )
    foreground_cells: dict[tuple[int, int], int] = {}
    for support in supports:
        if mediator_centers[support.child.mediator.object_ref] != support.source.center:
            continue
        residual_color, residual_cells = _carrier_source_residual_foreground(support)
        for cell in residual_cells:
            if cell in foreground_cells:
                return False
            foreground_cells[cell] = residual_color
    if any(
        projected.cells[y][x] != foreground_cells.get((x, y), latent_projected.cells[y][x])
        for y, row in enumerate(projected.cells)
        for x, _value in enumerate(row)
    ):
        return False
    if (
        _target_surface_signature(projected) != preserved_target_signature
        or _visible_target_regions(projected) != target_regions
    ):
        return False

    # The renderer may change only the old hierarchy footprint, its projected
    # footprint, and an assigned source disk currently covered by that child's
    # exact mediator footprint.  All other static evidence remains byte-exact.
    initial_dynamic = frozenset(
        cell for child in hierarchy.children for cell in _hierarchy_dynamic_footprint(scene, child)
    )
    allowed_changed = (
        initial_dynamic
        | assigned_cells
        | frozenset(cell for dynamic in group_dynamic for cell in dynamic)
    )
    if any(
        projected.cells[y][x] != value and (x, y) not in allowed_changed
        for y, row in enumerate(scene.cells)
        for x, value in enumerate(row)
    ):
        return False
    for support in supports:
        mediator_center = mediator_centers[support.child.mediator.object_ref]
        if mediator_center != support.source.center and any(
            projected.cells[y][x] != scene.cells[y][x] for x, y in support.source.cells
        ):
            return False

    search_budget.consume()
    return _projected_hierarchy_lineages_match(
        scene,
        latent_projected,
        hierarchy,
        positions=positions,
        colors=colors,
        mediator_centers=mediator_centers,
    )


def _bridge_projected_state_is_safe(
    scene: VisualScene,
    hierarchy: _AffineHierarchy,
    relation: _CompositeBridgeRelation,
    *,
    positions: dict[str, tuple[int, int]],
    colors: dict[str, int],
    static_cells: frozenset[tuple[int, int]],
    dynamic_target_regions: _TargetRegions,
    endpoint_target_regions: _TargetRegions,
    preserved_target_signature: _TargetSurfaceSignature,
    search_budget: _HierarchySearchBudget,
) -> bool:
    """Certify one bridge state while permitting only sink interiors to fill."""

    assignment_by_mediator = {
        child.mediator.object_ref: example for child, example in relation.assignments
    }
    group_dynamic: list[frozenset[tuple[int, int]]] = []
    mediator_centers: dict[str, tuple[int, int]] = {}
    mediator_footprints: list[frozenset[tuple[int, int]]] = []
    endpoint_footprints: list[tuple[str, frozenset[tuple[int, int]]]] = []
    for child in hierarchy.children:
        example = assignment_by_mediator.get(child.mediator.object_ref)
        if example is None:
            return False
        centers = tuple(positions[item.object_ref] for item in child.endpoints)
        mediator_center = (
            sum(center[0] for center in centers) // child.arity,
            sum(center[1] for center in centers) // child.arity,
        )
        mediator_centers[child.mediator.object_ref] = mediator_center
        endpoints = tuple(
            _translated_object_footprint(endpoint, center=center)
            for endpoint, center in zip(child.endpoints, centers, strict=True)
        )
        if any(
            not _hierarchy_cells_in_bounds(scene, footprint)
            or footprint & static_cells
            or not _hierarchy_avoids_target_regions(footprint, endpoint_target_regions)
            for footprint in endpoints
        ) or any(
            not _footprints_have_gap(left, right, gap=1)
            for left, right in itertools.combinations(endpoints, 2)
        ):
            return False
        dynamic = _hierarchy_projected_group_footprint(
            child,
            endpoint_centers=centers,
            mediator_center=mediator_center,
        )
        if (
            not _hierarchy_cells_in_bounds(scene, dynamic)
            or dynamic & static_cells
            or not _hierarchy_avoids_target_regions(dynamic, dynamic_target_regions)
        ):
            return False
        group_dynamic.append(dynamic)
        mediator_footprints.append(
            _translated_object_footprint(child.mediator, center=mediator_center)
        )
        endpoint_footprints.extend(
            (endpoint.object_ref, footprint)
            for endpoint, footprint in zip(child.endpoints, endpoints, strict=True)
        )
        if mediator_center == example.target.rounded_center and any(
            (x, y) in dynamic for x, y in example.target.cells
        ):
            return False

    if any(left & right for left, right in itertools.combinations(group_dynamic, 2)) or any(
        not _footprints_have_gap(left, right, gap=1)
        for left, right in itertools.combinations(mediator_footprints, 2)
    ):
        return False
    for (left_ref, left), (right_ref, right) in itertools.combinations(
        endpoint_footprints,
        2,
    ):
        if colors[left_ref] == colors[right_ref] and not _footprints_have_gap(
            left,
            right,
            gap=1,
        ):
            return False

    projected = _hierarchy_projected_scene(
        scene,
        hierarchy,
        positions=positions,
        colors=colors,
    )
    sink_centers = frozenset(
        example.target.rounded_center for _child, example in relation.assignments
    )
    projected_preserved = tuple(
        item
        for item in _target_surface_signature(projected)
        if not (item[0] == "composite" and item[1] in sink_centers)
    )
    if projected_preserved != preserved_target_signature:
        return False
    projected_composite = _composite_sparse_targets(projected)
    for child, example in relation.assignments:
        if any(projected.cells[y][x] != scene.cells[y][x] for x, y in example.target.cells):
            return False
        target_still_hollow = any(
            item.rounded_center == example.target.rounded_center
            and signature == frozenset(example.residual_colors)
            for item, signature in projected_composite
        )
        if target_still_hollow != (
            mediator_centers[child.mediator.object_ref] != example.target.rounded_center
        ):
            return False

    projected_regions = {
        item for item in _visible_target_regions(projected) if item[0] not in sink_centers
    }
    original_regions = {
        item for item in _visible_target_regions(scene) if item[0] not in sink_centers
    }
    if projected_regions != original_regions:
        return False
    parsed = _unique_affine_hierarchy(
        projected,
        active_color=hierarchy.active_color,
        search_budget=search_budget,
    )
    active = tuple(item for item in projected.endpoints if item.color == hierarchy.active_color)
    expected_geometry = tuple(
        sorted(
            (
                mediator_centers[child.mediator.object_ref],
                tuple(sorted(positions[item.object_ref] for item in child.endpoints)),
            )
            for child in hierarchy.children
        )
    )
    observed_geometry = tuple(
        sorted(
            (
                child.mediator.rounded_center,
                tuple(sorted(item.rounded_center for item in child.endpoints)),
            )
            for child in (() if parsed is None else parsed.children)
        )
    )
    return bool(
        len(projected.endpoints) == len(scene.endpoints)
        and len(projected.mediators) == len(scene.mediators)
        and len(active) == 1
        and parsed is not None
        and parsed.target.rounded_center == hierarchy.target.rounded_center
        and parsed.target.color == hierarchy.target.color
        and observed_geometry == expected_geometry
    )


def _bridge_final_layout_geometry_is_safe(
    hierarchy: _AffineHierarchy,
    layouts: tuple[_HierarchyChildLayout, ...],
) -> bool:
    """Reject jointly impossible terminal geometry before projected parsing.

    Each child layout has already passed its own static, target, and bounds
    checks. This filter reproduces only the cross-child and role-dependent
    terminal constraints from ``_bridge_projected_state_is_safe``; acceptance
    here never substitutes for the full sequential parser certificate.
    """

    if tuple(layout.group for layout in layouts) != hierarchy.children or any(
        mover.rounded_center == point
        for layout in layouts
        for mover, point in zip(layout.movers, layout.points, strict=True)
    ):
        return False
    positions = {
        endpoint.object_ref: endpoint.rounded_center
        for child in hierarchy.children
        for endpoint in child.endpoints
    }
    colors = {
        endpoint.object_ref: endpoint.color
        for child in hierarchy.children
        for endpoint in child.endpoints
    }
    active = tuple(ref for ref, color in colors.items() if color == hierarchy.active_color)
    if len(active) != 1:
        return False
    active_ref = active[0]

    for child_index, layout in enumerate(layouts):
        if child_index:
            selected_ref = layout.movers[0].object_ref
            if selected_ref == active_ref or colors[selected_ref] == hierarchy.active_color:
                return False
            colors[active_ref], colors[selected_ref] = colors[selected_ref], colors[active_ref]
            active_ref = selected_ref
        if layout.movers[0].object_ref != active_ref:
            return False
        for mover_index, (mover, point) in enumerate(
            zip(layout.movers, layout.points, strict=True)
        ):
            if mover.object_ref != active_ref:
                return False
            positions[active_ref] = point
            if mover_index + 1 < len(layout.movers):
                selected_ref = layout.movers[mover_index + 1].object_ref
                if selected_ref == active_ref or colors[selected_ref] == hierarchy.active_color:
                    return False
                colors[active_ref], colors[selected_ref] = (
                    colors[selected_ref],
                    colors[active_ref],
                )
                active_ref = selected_ref

    group_dynamic: list[frozenset[tuple[int, int]]] = []
    mediator_footprints: list[frozenset[tuple[int, int]]] = []
    endpoint_footprints: list[tuple[str, frozenset[tuple[int, int]]]] = []
    for layout in layouts:
        centers = tuple(positions[item.object_ref] for item in layout.group.endpoints)
        mediator_center = (
            sum(center[0] for center in centers) // layout.group.arity,
            sum(center[1] for center in centers) // layout.group.arity,
        )
        if mediator_center != layout.support:
            return False
        endpoints = tuple(
            _translated_object_footprint(endpoint, center=center)
            for endpoint, center in zip(layout.group.endpoints, centers, strict=True)
        )
        if any(
            not _footprints_have_gap(left, right, gap=1)
            for left, right in itertools.combinations(endpoints, 2)
        ):
            return False
        group_dynamic.append(
            _hierarchy_projected_group_footprint(
                layout.group,
                endpoint_centers=centers,
                mediator_center=mediator_center,
            )
        )
        mediator_footprints.append(
            _translated_object_footprint(layout.group.mediator, center=mediator_center)
        )
        endpoint_footprints.extend(
            (endpoint.object_ref, footprint)
            for endpoint, footprint in zip(layout.group.endpoints, endpoints, strict=True)
        )

    if any(left & right for left, right in itertools.combinations(group_dynamic, 2)) or any(
        not _footprints_have_gap(left, right, gap=1)
        for left, right in itertools.combinations(mediator_footprints, 2)
    ):
        return False
    return all(
        colors[left_ref] != colors[right_ref] or _footprints_have_gap(left, right, gap=1)
        for (left_ref, left), (right_ref, right) in itertools.combinations(
            endpoint_footprints,
            2,
        )
    )


def _residual_linked_hierarchy_sequence_is_safe(
    scene: VisualScene,
    hierarchy: _AffineHierarchy,
    supports: tuple[_HierarchyTargetSupport, ...],
    layouts: tuple[_HierarchyChildLayout, ...],
    *,
    static_cells: frozenset[tuple[int, int]],
    dynamic_target_regions: _TargetRegions,
    endpoint_target_regions: _TargetRegions,
    preserved_target_signature: _TargetSurfaceSignature,
    search_budget: _HierarchySearchBudget,
    state_cache: dict[_BridgeProjectedStateKey, bool],
) -> bool:
    """Validate all target-support placements and intervening role exchanges."""

    if tuple(layout.group for layout in layouts) != hierarchy.children or any(
        mover.rounded_center == point
        for layout in layouts
        for mover, point in zip(layout.movers, layout.points, strict=True)
    ):
        return False
    positions = {
        endpoint.object_ref: endpoint.rounded_center
        for child in hierarchy.children
        for endpoint in child.endpoints
    }
    colors = {
        endpoint.object_ref: endpoint.color
        for child in hierarchy.children
        for endpoint in child.endpoints
    }
    active = tuple(ref for ref, color in colors.items() if color == hierarchy.active_color)
    if len(active) != 1:
        return False
    active_ref = active[0]

    def state_is_safe() -> bool:
        key: _BridgeProjectedStateKey = (
            tuple(sorted(positions.items())),
            tuple(sorted(colors.items())),
        )
        cached = state_cache.get(key)
        if cached is not None:
            return cached
        safe = _residual_linked_projected_state_is_safe(
            scene,
            hierarchy,
            supports,
            positions=positions,
            colors=colors,
            static_cells=static_cells,
            dynamic_target_regions=dynamic_target_regions,
            endpoint_target_regions=endpoint_target_regions,
            preserved_target_signature=preserved_target_signature,
            search_budget=search_budget,
        )
        state_cache[key] = safe
        return safe

    if not state_is_safe():
        return False
    for child_index, layout in enumerate(layouts):
        if child_index:
            selected_ref = layout.movers[0].object_ref
            if selected_ref == active_ref or colors[selected_ref] == hierarchy.active_color:
                return False
            colors[active_ref], colors[selected_ref] = colors[selected_ref], colors[active_ref]
            active_ref = selected_ref
            if not state_is_safe():
                return False
        if layout.movers[0].object_ref != active_ref:
            return False
        for mover_index, (mover, point) in enumerate(
            zip(layout.movers, layout.points, strict=True)
        ):
            if mover.object_ref != active_ref:
                return False
            positions[active_ref] = point
            if not state_is_safe():
                return False
            if mover_index + 1 < len(layout.movers):
                selected_ref = layout.movers[mover_index + 1].object_ref
                if selected_ref == active_ref or colors[selected_ref] == hierarchy.active_color:
                    return False
                colors[active_ref], colors[selected_ref] = (
                    colors[selected_ref],
                    colors[active_ref],
                )
                active_ref = selected_ref
                if not state_is_safe():
                    return False
        centers = tuple(positions[item.object_ref] for item in layout.group.endpoints)
        mediator_center = (
            sum(center[0] for center in centers) // layout.group.arity,
            sum(center[1] for center in centers) // layout.group.arity,
        )
        if mediator_center != layout.support:
            return False
    return True


def _carrier_source_occlusion_hierarchy_sequence_is_safe(
    scene: VisualScene,
    hierarchy: _AffineHierarchy,
    supports: tuple[_HierarchySourceSupport, ...],
    layouts: tuple[_HierarchyChildLayout, ...],
    *,
    static_cells: frozenset[tuple[int, int]],
    target_regions: _TargetRegions,
    preserved_target_signature: _TargetSurfaceSignature,
    search_budget: _HierarchySearchBudget,
    state_cache: dict[_BridgeProjectedStateKey, bool],
) -> bool:
    """Certify every forward and exact-inverse source-occlusion transient."""

    if tuple(layout.group for layout in layouts) != hierarchy.children or any(
        mover.rounded_center == point
        for layout in layouts
        for mover, point in zip(layout.movers, layout.points, strict=True)
    ):
        return False
    positions = {
        endpoint.object_ref: endpoint.rounded_center
        for child in hierarchy.children
        for endpoint in child.endpoints
    }
    colors = {
        endpoint.object_ref: endpoint.color
        for child in hierarchy.children
        for endpoint in child.endpoints
    }
    active = tuple(ref for ref, color in colors.items() if color == hierarchy.active_color)
    if len(active) != 1:
        return False
    active_ref = active[0]

    def state_is_safe(*, use_cache: bool = True) -> bool:
        key: _BridgeProjectedStateKey = (
            tuple(sorted(positions.items())),
            tuple(sorted(colors.items())),
        )
        if use_cache:
            cached = state_cache.get(key)
            if cached is not None:
                return cached
        safe = _carrier_source_occlusion_projected_state_is_safe(
            scene,
            hierarchy,
            supports,
            positions=positions,
            colors=colors,
            static_cells=static_cells,
            target_regions=target_regions,
            preserved_target_signature=preserved_target_signature,
            search_budget=search_budget,
        )
        if use_cache:
            state_cache[key] = safe
        return safe

    if not state_is_safe():
        return False
    initial_positions = dict(positions)
    initial_colors = dict(colors)
    transitions: list[tuple[str, str, str | None, tuple[int, int] | None]] = []
    for child_index, layout in enumerate(layouts):
        if child_index:
            selected_ref = layout.movers[0].object_ref
            if selected_ref == active_ref or colors[selected_ref] == hierarchy.active_color:
                return False
            previous_active_ref = active_ref
            colors[active_ref], colors[selected_ref] = colors[selected_ref], colors[active_ref]
            active_ref = selected_ref
            transitions.append(("switch", previous_active_ref, selected_ref, None))
            if not state_is_safe():
                return False
        if layout.movers[0].object_ref != active_ref:
            return False
        for mover_index, (mover, point) in enumerate(
            zip(layout.movers, layout.points, strict=True)
        ):
            if mover.object_ref != active_ref:
                return False
            before_position = positions[active_ref]
            positions[active_ref] = point
            transitions.append(("move", active_ref, None, before_position))
            if not state_is_safe():
                return False
            if mover_index + 1 < len(layout.movers):
                selected_ref = layout.movers[mover_index + 1].object_ref
                if selected_ref == active_ref or colors[selected_ref] == hierarchy.active_color:
                    return False
                previous_active_ref = active_ref
                colors[active_ref], colors[selected_ref] = (
                    colors[selected_ref],
                    colors[active_ref],
                )
                active_ref = selected_ref
                transitions.append(("switch", previous_active_ref, selected_ref, None))
                if not state_is_safe():
                    return False
        centers = tuple(positions[item.object_ref] for item in layout.group.endpoints)
        mediator_center = (
            sum(center[0] for center in centers) // layout.group.arity,
            sum(center[1] for center in centers) // layout.group.arity,
        )
        if mediator_center != layout.support:
            return False

    # Simulate the complete recovery sequence independently of the plan
    # builder.  Clearing the cache forces every reverse transient through the
    # source-restoration and lineage certificate again.
    for (
        transition,
        previous_ref,
        inverse_selected_ref,
        previous_position,
    ) in reversed(transitions):
        if transition == "move":
            if active_ref != previous_ref or previous_position is None:
                return False
            positions[active_ref] = previous_position
        else:
            if inverse_selected_ref is None or active_ref != inverse_selected_ref:
                return False
            colors[inverse_selected_ref], colors[previous_ref] = (
                colors[previous_ref],
                colors[inverse_selected_ref],
            )
            active_ref = previous_ref
        if not state_is_safe(use_cache=False):
            return False
    return positions == initial_positions and colors == initial_colors


def _bridge_hierarchy_sequence_is_safe(
    scene: VisualScene,
    hierarchy: _AffineHierarchy,
    relation: _CompositeBridgeRelation,
    layouts: tuple[_HierarchyChildLayout, ...],
    *,
    static_cells: frozenset[tuple[int, int]],
    dynamic_target_regions: _TargetRegions,
    endpoint_target_regions: _TargetRegions,
    preserved_target_signature: _TargetSurfaceSignature,
    search_budget: _HierarchySearchBudget,
    state_cache: dict[_BridgeProjectedStateKey, bool],
) -> bool:
    """Validate both bridge placements and every intervening role exchange."""

    if tuple(layout.group for layout in layouts) != hierarchy.children or any(
        mover.rounded_center == point
        for layout in layouts
        for mover, point in zip(layout.movers, layout.points, strict=True)
    ):
        return False
    positions = {
        endpoint.object_ref: endpoint.rounded_center
        for child in hierarchy.children
        for endpoint in child.endpoints
    }
    colors = {
        endpoint.object_ref: endpoint.color
        for child in hierarchy.children
        for endpoint in child.endpoints
    }
    active = tuple(ref for ref, color in colors.items() if color == hierarchy.active_color)
    if len(active) != 1:
        return False
    active_ref = active[0]

    def state_is_safe() -> bool:
        key: _BridgeProjectedStateKey = (
            tuple(sorted(positions.items())),
            tuple(sorted(colors.items())),
        )
        cached = state_cache.get(key)
        if cached is not None:
            return cached
        safe = _bridge_projected_state_is_safe(
            scene,
            hierarchy,
            relation,
            positions=positions,
            colors=colors,
            static_cells=static_cells,
            dynamic_target_regions=dynamic_target_regions,
            endpoint_target_regions=endpoint_target_regions,
            preserved_target_signature=preserved_target_signature,
            search_budget=search_budget,
        )
        state_cache[key] = safe
        return safe

    if not state_is_safe():
        return False
    for child_index, layout in enumerate(layouts):
        if child_index:
            selected_ref = layout.movers[0].object_ref
            if selected_ref == active_ref or colors[selected_ref] == hierarchy.active_color:
                return False
            colors[active_ref], colors[selected_ref] = colors[selected_ref], colors[active_ref]
            active_ref = selected_ref
            if not state_is_safe():
                return False
        if layout.movers[0].object_ref != active_ref:
            return False
        for mover_index, (mover, point) in enumerate(
            zip(layout.movers, layout.points, strict=True)
        ):
            if mover.object_ref != active_ref:
                return False
            positions[active_ref] = point
            if not state_is_safe():
                return False
            if mover_index + 1 < len(layout.movers):
                selected_ref = layout.movers[mover_index + 1].object_ref
                if selected_ref == active_ref or colors[selected_ref] == hierarchy.active_color:
                    return False
                colors[active_ref], colors[selected_ref] = (
                    colors[selected_ref],
                    colors[active_ref],
                )
                active_ref = selected_ref
                if not state_is_safe():
                    return False
        centers = tuple(positions[item.object_ref] for item in layout.group.endpoints)
        mediator_center = (
            sum(center[0] for center in centers) // layout.group.arity,
            sum(center[1] for center in centers) // layout.group.arity,
        )
        if mediator_center != layout.support:
            return False
    return True


def _carrier_source_raw_target_child_route(
    scene: VisualScene,
    hierarchy: _AffineHierarchy,
    supports: tuple[_HierarchySourceSupport, ...],
) -> tuple[int, tuple[tuple[str, tuple[int, int]], ...]] | None:
    """Reuse the unique raw-linked child's earlier target-isolation layout.

    The carrier relation is permitted to add a destination only when exactly one
    source's non-carrier palette equals exactly one observed monochrome target
    surface.  The endpoint destinations themselves come from the existing
    child-isolation planner; only their endpoint identities are retained so role
    exchanges can later be rebased through the post-carry positions.
    """

    if tuple(item.child for item in supports) != hierarchy.children:
        return None
    target_palette = frozenset(scene.cells[y][x] for x, y in hierarchy.target.cells)
    matching_targets = tuple(
        target
        for target in scene.targets
        if frozenset(scene.cells[y][x] for x, y in target.cells) == target_palette
    )
    if (
        len(target_palette) != 1
        or hierarchy.target.color not in target_palette
        or matching_targets != (hierarchy.target,)
    ):
        return None
    joined = tuple(
        (index, support)
        for index, support in enumerate(supports)
        if support.source.palette - {support.example.carrier_color} == target_palette
        and target_palette <= frozenset(support.example.residual_colors)
    )
    if len(joined) != 1:
        return None
    support_index, support = joined[0]

    # Level zero is used only as a deterministic namespace for this structural
    # layout lookup.  No level-specific evidence or coordinate enters the route.
    relation_key = _hierarchy_relation_key(scene, hierarchy, level_index=0)
    hypothesis_keys = tuple(
        (
            child,
            _child_isolation_hypothesis_key(
                scene,
                child,
                relation_key=relation_key,
            ),
        )
        for child in hierarchy.children
    )
    selected_keys = tuple(key for child, key in hypothesis_keys if child == support.child)
    if len(selected_keys) != 1:
        return None
    selected_key = selected_keys[0]
    if any(child != support.child and key == selected_key for child, key in hypothesis_keys):
        return None
    child_plan = _child_isolation_plan(
        scene,
        hierarchy,
        level_index=0,
        rejected_signatures=set(),
        rejected_hypothesis_keys={key for child, key in hypothesis_keys if child != support.child},
    )
    if (
        child_plan is None
        or child_plan.hypothesis_key != selected_key
        or not child_plan.actions
        or not child_plan.actions[-1].completes_child_isolation
        or child_plan.actions[-1].arity != support.child.arity
        or child_plan.actions[-1].mediator_color != support.child.mediator.color
    ):
        return None

    endpoint_by_center: dict[tuple[int, int], str] = {}
    for endpoint in support.child.endpoints:
        if endpoint.rounded_center in endpoint_by_center:
            return None
        endpoint_by_center[endpoint.rounded_center] = endpoint.object_ref
    active_refs = tuple(
        endpoint.object_ref
        for endpoint in support.child.endpoints
        if endpoint.color == hierarchy.active_color
    )
    actions = list(child_plan.actions)
    if actions[0].purpose is VisualActionPurpose.PROBE:
        activation = actions.pop(0)
        active_ref = endpoint_by_center.get((activation.coordinate.x, activation.coordinate.y))
        if active_ref is None:
            return None
    elif len(active_refs) == 1:
        active_ref = active_refs[0]
    else:
        return None

    route: list[tuple[str, tuple[int, int]]] = []
    for mover_index in range(support.child.arity):
        if not actions:
            return None
        movement = actions.pop(0)
        if movement.purpose is not VisualActionPurpose.PROGRESS:
            return None
        route.append((active_ref, (movement.coordinate.x, movement.coordinate.y)))
        if mover_index + 1 == support.child.arity:
            continue
        if not actions:
            return None
        role_exchange = actions.pop(0)
        if role_exchange.purpose is not VisualActionPurpose.PROBE:
            return None
        selected_ref = endpoint_by_center.get(
            (role_exchange.coordinate.x, role_exchange.coordinate.y)
        )
        if selected_ref is None or selected_ref == active_ref:
            return None
        active_ref = selected_ref
    points = tuple(point for _ref, point in route)
    return (
        (support_index, tuple(route))
        if not actions
        and len({ref for ref, _point in route}) == support.child.arity
        and {ref for ref, _point in route}
        == {endpoint.object_ref for endpoint in support.child.endpoints}
        and sum(point[0] for point in points)
        == support.child.arity * hierarchy.target.rounded_center[0]
        and sum(point[1] for point in points)
        == support.child.arity * hierarchy.target.rounded_center[1]
        else None
    )


def _carrier_source_target_delivery_projected_state_is_safe(
    scene: VisualScene,
    baseline_scene: VisualScene,
    hierarchy: _AffineHierarchy,
    supports: tuple[_HierarchySourceSupport, ...],
    *,
    support_index: int,
    baseline_positions: dict[str, tuple[int, int]],
    positions: dict[str, tuple[int, int]],
    colors: dict[str, int],
    completes_delivery: bool,
) -> VisualScene | None:
    """Return one exact carried-source state only when unrelated cells survive."""

    if (
        tuple(item.child for item in supports) != hierarchy.children
        or support_index < 0
        or support_index >= len(supports)
    ):
        return None
    support = supports[support_index]
    endpoint_centers = tuple(positions[endpoint.object_ref] for endpoint in support.child.endpoints)
    mediator_center = (
        sum(center[0] for center in endpoint_centers) // support.child.arity,
        sum(center[1] for center in endpoint_centers) // support.child.arity,
    )
    source_x, source_y = support.source.center
    translated_source = frozenset(
        (mediator_center[0] + x - source_x, mediator_center[1] + y - source_y)
        for x, y in support.source.cells
    )
    endpoint_footprints = tuple(
        _translated_object_footprint(endpoint, center=positions[endpoint.object_ref])
        for endpoint in support.child.endpoints
    )
    if (
        len(translated_source) != len(support.source.cells)
        or not _hierarchy_cells_in_bounds(scene, translated_source)
        or any(translated_source & footprint for footprint in endpoint_footprints)
    ):
        return None
    selected_dynamic = _hierarchy_projected_group_footprint(
        support.child,
        endpoint_centers=endpoint_centers,
        mediator_center=mediator_center,
    )
    target_regions = _visible_target_regions(baseline_scene)
    if completes_delivery:
        if (
            mediator_center != hierarchy.target.rounded_center
            or bool(frozenset(hierarchy.target.cells) & translated_source)
            or not _hierarchy_avoids_target_regions(
                selected_dynamic | translated_source,
                tuple(
                    (center, region)
                    for center, region in target_regions
                    if center != hierarchy.target.rounded_center
                ),
            )
        ):
            return None
    elif mediator_center == hierarchy.target.rounded_center or not _hierarchy_avoids_target_regions(
        selected_dynamic | translated_source,
        target_regions,
    ):
        return None

    try:
        projected = _carrier_source_carried_projected_scene(
            scene,
            hierarchy,
            supports,
            positions=positions,
            colors=colors,
            carried_support_indexes=frozenset({support_index}),
        )
    except ValueError:
        return None
    for x, y in support.source.cells:
        translated = (mediator_center[0] + x - source_x, mediator_center[1] + y - source_y)
        if projected.cells[translated[1]][translated[0]] != scene.cells[y][x]:
            return None

    frozen_dynamic = frozenset(
        cell
        for child in hierarchy.children
        if child != support.child
        for cell in _hierarchy_projected_group_footprint(
            child,
            endpoint_centers=tuple(
                baseline_positions[endpoint.object_ref] for endpoint in child.endpoints
            ),
            mediator_center=(
                sum(baseline_positions[endpoint.object_ref][0] for endpoint in child.endpoints)
                // child.arity,
                sum(baseline_positions[endpoint.object_ref][1] for endpoint in child.endpoints)
                // child.arity,
            ),
        )
    )
    protected_cells = set(frozen_dynamic)
    for index, other_support in enumerate(supports):
        if index != support_index:
            protected_cells.update(other_support.source.cells)
    for target in scene.targets:
        protected_cells.update(target.cells)
    if any(projected.cells[y][x] != baseline_scene.cells[y][x] for x, y in protected_cells):
        return None

    baseline_endpoint_centers = tuple(
        baseline_positions[endpoint.object_ref] for endpoint in support.child.endpoints
    )
    baseline_mediator_center = (
        sum(center[0] for center in baseline_endpoint_centers) // support.child.arity,
        sum(center[1] for center in baseline_endpoint_centers) // support.child.arity,
    )
    initial_selected_dynamic = _hierarchy_projected_group_footprint(
        support.child,
        endpoint_centers=baseline_endpoint_centers,
        mediator_center=baseline_mediator_center,
    )
    baseline_translated_source = frozenset(
        (
            baseline_mediator_center[0] + x - source_x,
            baseline_mediator_center[1] + y - source_y,
        )
        for x, y in support.source.cells
    )
    baseline_occupied = frozenset(
        (x, y)
        for y, row in enumerate(baseline_scene.cells)
        for x, value in enumerate(row)
        if value != baseline_scene.background
    )
    stationary_occupied = baseline_occupied - initial_selected_dynamic - baseline_translated_source
    if (selected_dynamic | translated_source) & stationary_occupied:
        return None
    mutable_cells = (
        initial_selected_dynamic | selected_dynamic | baseline_translated_source | translated_source
    )
    if any(
        projected.cells[y][x] != baseline_scene.cells[y][x]
        for y in range(scene.height)
        for x in range(scene.width)
        if (x, y) not in mutable_cells
    ):
        return None
    return projected


def _carrier_source_attachment_alternative_inverse(
    route: tuple[tuple[str, tuple[int, int]], ...],
    *,
    baseline_positions: dict[str, tuple[int, int]],
    safe_endpoint_refs: frozenset[str],
) -> tuple[str, tuple[int, int], tuple[int, int]] | None:
    """Return the unique smallest projected-safe alternative historical inverse."""

    route_refs = tuple(ref for ref, _point in route)
    alternate_refs = frozenset(route_refs[:-1])
    if (
        len(route) < 2
        or len(set(route_refs)) != len(route_refs)
        or any(ref not in baseline_positions for ref in route_refs)
        or not safe_endpoint_refs
        or not safe_endpoint_refs <= alternate_refs
    ):
        return None
    inverse_candidates = tuple(
        (
            ref,
            point,
            baseline_positions[ref],
            (point[0] - baseline_positions[ref][0]) ** 2
            + (point[1] - baseline_positions[ref][1]) ** 2,
        )
        for ref, point in route[:-1]
        if ref in safe_endpoint_refs
    )
    inverse_distances = tuple(candidate[3] for candidate in inverse_candidates)
    minimum_distance = min(inverse_distances)
    if (
        any(candidate[1] == candidate[2] for candidate in inverse_candidates)
        or inverse_distances.count(minimum_distance) != 1
    ):
        return None
    ref, point, predecessor, _distance_squared = next(
        candidate for candidate in inverse_candidates if candidate[3] == minimum_distance
    )
    return ref, point, predecessor


def _build_hierarchy_plan(
    hierarchy: _AffineHierarchy,
    layouts: tuple[_HierarchyChildLayout, ...],
    *,
    scene: VisualScene,
    move_order: tuple[str, ...] | None = None,
    support_weights: tuple[int, ...] | None = None,
    carrier_source_supports: tuple[_HierarchySourceSupport, ...] = (),
    carrier_source_level_index: int | None = None,
    carrier_source_rejected_external_relation_key: str | None = None,
    signature_prefix: str = "affine-hierarchy",
    terminal_expectation: str = "complete the distinct child-mediator centroid relation",
    derive_carrier_source_attachment_continuations: bool = False,
) -> _HierarchyPlan:
    geometry = "|".join(
        f"{layout.support[0]},{layout.support[1]}:"
        + ";".join(
            f"{mover.rounded_center[0]},{mover.rounded_center[1]}>{point[0]},{point[1]}"
            for mover, point in zip(layout.movers, layout.points, strict=True)
        )
        for layout in layouts
    )
    weights = tuple(1 for _layout in layouts) if support_weights is None else support_weights
    if len(weights) != len(layouts) or any(weight < 1 for weight in weights):
        raise ValueError("hierarchy support weights must be positive and match the layouts")

    moves = {
        mover.object_ref: (layout, mover, point)
        for layout in layouts
        for mover, point in zip(layout.movers, layout.points, strict=True)
    }
    if len(moves) != sum(len(layout.movers) for layout in layouts):
        raise ValueError("hierarchy layouts must move each endpoint at most once")
    ordered_refs = (
        tuple(mover.object_ref for layout in layouts for mover in layout.movers)
        if move_order is None
        else move_order
    )
    if len(ordered_refs) != len(moves) or set(ordered_refs) != set(moves):
        raise ValueError("hierarchy move order must contain every planned endpoint exactly once")

    identity = f"{hierarchy.mechanic_ref}|{geometry}"
    if support_weights is not None:
        identity = f"{identity}|weights={','.join(str(item) for item in weights)}"
    if move_order is not None:
        identity = f"{identity}|order={','.join(ordered_refs)}"
    if carrier_source_supports:
        if (
            carrier_source_level_index is None
            or carrier_source_rejected_external_relation_key is None
        ):
            raise ValueError(
                "carrier-source replay requires level-scoped rejected external provenance"
            )
        if tuple(item.child for item in carrier_source_supports) != hierarchy.children:
            raise ValueError("carrier-source supports must retain hierarchy child order")
        identity = (
            f"{identity}|source-layer=residual-foreground-v2"
            f"|rejected-external={carrier_source_rejected_external_relation_key}"
        )
    signature = signature_prefix + ":" + hashlib.sha256(identity.encode()).hexdigest()[:24]
    plan_id = "visual-hierarchy-plan:" + signature.rsplit(":", 1)[-1]

    initial_positions = {
        endpoint.object_ref: endpoint.rounded_center
        for child in hierarchy.children
        for endpoint in child.endpoints
    }
    initial_colors = {
        endpoint.object_ref: endpoint.color
        for child in hierarchy.children
        for endpoint in child.endpoints
    }
    positions = dict(initial_positions)
    colors = dict(initial_colors)
    active = tuple(ref for ref, color in colors.items() if color == hierarchy.active_color)
    if len(active) != 1:
        raise ValueError("hierarchy plan requires exactly one active endpoint")
    active_ref = active[0]

    def projected_scene() -> VisualScene:
        return (
            _carrier_source_residual_foreground_projected_scene(
                scene,
                hierarchy,
                carrier_source_supports,
                positions=positions,
                colors=colors,
            )
            if carrier_source_supports
            else _hierarchy_projected_scene(
                scene,
                hierarchy,
                positions=positions,
                colors=colors,
            )
        )

    def certificate() -> _HierarchyRasterCertificate:
        projected = projected_scene()
        return _HierarchyRasterCertificate(
            protected_raster_hash=_child_isolation_protected_raster_hash(projected),
            visible_endpoint_count=len(projected.endpoints),
            visible_mediator_count=len(projected.mediators),
        )

    def require_masked_lineage_only_if_needed(
        planned: PlannedClick,
        required_scene: VisualScene | None,
    ) -> PlannedClick:
        if required_scene is None or _hierarchy_planned_click_is_safe(
            required_scene,
            planned,
            active_color=hierarchy.active_color,
        ):
            return planned
        visible_active_count = sum(
            endpoint.color == hierarchy.active_color for endpoint in required_scene.endpoints
        )
        masked = replace(
            planned,
            required_visible_active_endpoint_count=visible_active_count,
        )
        if not _hierarchy_planned_click_is_safe(
            required_scene,
            masked,
            active_color=hierarchy.active_color,
        ):
            raise ValueError("carrier-source action lacks an exact masked-lineage precondition")
        return masked

    initial_certificate = certificate()
    if initial_certificate.protected_raster_hash != _child_isolation_protected_raster_hash(scene):
        raise ValueError("projected hierarchy origin does not match the observed protected board")

    actions: list[PlannedClick] = []
    inverse_specs: list[tuple[VisualActionPurpose, str, tuple[int, int], _AffineChildGroup]] = []
    required = initial_certificate
    for move_index, mover_ref in enumerate(ordered_refs):
        layout, _mover, point = moves[mover_ref]
        if mover_ref != active_ref:
            required_scene = projected_scene() if carrier_source_supports else None
            old_active_ref = active_ref
            old_active_group = next(
                child
                for child in hierarchy.children
                if any(endpoint.object_ref == old_active_ref for endpoint in child.endpoints)
            )
            selected_at = positions[mover_ref]
            old_active_at = positions[old_active_ref]
            colors[old_active_ref], colors[mover_ref] = (
                colors[mover_ref],
                colors[old_active_ref],
            )
            active_ref = mover_ref
            expected = certificate()
            actions.append(
                require_masked_lineage_only_if_needed(
                    PlannedClick(
                        coordinate=Coordinate(*selected_at),
                        purpose=VisualActionPurpose.PROBE,
                        expectation=(
                            "exchange the active role while preserving the certified "
                            "two-layer hierarchy raster"
                        ),
                        mechanic_ref=hierarchy.mechanic_ref,
                        plan_id=plan_id,
                        plan_signature=signature,
                        target_center=hierarchy.target.rounded_center,
                        mediator_color=layout.group.mediator.color,
                        arity=layout.group.arity,
                        expected_active_center=selected_at,
                        required_child_protected_raster_hash=required.protected_raster_hash,
                        expected_child_protected_raster_hash=expected.protected_raster_hash,
                        expected_visible_endpoint_count=expected.visible_endpoint_count,
                        expected_visible_mediator_count=expected.visible_mediator_count,
                    ),
                    required_scene,
                )
            )
            inverse_specs.append(
                (
                    VisualActionPurpose.PROBE,
                    old_active_ref,
                    old_active_at,
                    old_active_group,
                )
            )
            required = expected

        required_scene = projected_scene() if carrier_source_supports else None
        before_position = positions[mover_ref]
        positions[mover_ref] = point
        expected = certificate()
        final_action = move_index + 1 == len(ordered_refs)
        actions.append(
            require_masked_lineage_only_if_needed(
                PlannedClick(
                    coordinate=Coordinate(*point),
                    purpose=VisualActionPurpose.PROGRESS,
                    expectation=(
                        terminal_expectation
                        if final_action
                        else "place the active endpoint on a protected child-support layout"
                    ),
                    mechanic_ref=hierarchy.mechanic_ref,
                    plan_id=plan_id,
                    plan_signature=signature,
                    target_center=hierarchy.target.rounded_center,
                    mediator_color=layout.group.mediator.color,
                    arity=layout.group.arity,
                    completes_hierarchy=final_action,
                    expected_active_center=point,
                    required_child_protected_raster_hash=required.protected_raster_hash,
                    expected_child_protected_raster_hash=expected.protected_raster_hash,
                    expected_visible_endpoint_count=expected.visible_endpoint_count,
                    expected_visible_mediator_count=expected.visible_mediator_count,
                ),
                required_scene,
            )
        )
        inverse_specs.append(
            (
                VisualActionPurpose.PROGRESS,
                mover_ref,
                before_position,
                layout.group,
            )
        )
        required = expected

    recovery_prefix = {
        "affine-weighted-hierarchy": "affine-weighted-hierarchy-recovery",
        "affine-visible-node-hierarchy": "affine-visible-node-hierarchy-recovery",
        "affine-bridge-hierarchy": "affine-bridge-hierarchy-recovery",
        "affine-residual-linked-hierarchy": ("affine-residual-linked-hierarchy-recovery"),
        "affine-external-residual-linked-hierarchy": (
            "affine-external-residual-linked-hierarchy-recovery"
        ),
        "affine-raw-matching-composite-hierarchy": (
            "affine-raw-matching-composite-hierarchy-recovery"
        ),
        "affine-external-own-composite-hierarchy": (
            "affine-external-own-composite-hierarchy-recovery"
        ),
        "affine-carrier-source-occlusion-hierarchy": (
            "affine-carrier-source-occlusion-hierarchy-recovery"
        ),
    }.get(signature_prefix, "affine-hierarchy-recovery")
    recovery_signature = (
        recovery_prefix
        + ":"
        + hashlib.sha256(f"{signature}:recovery".encode("ascii")).hexdigest()[:24]
    )
    recovery_plan_id = "visual-hierarchy-recovery:" + signature.rsplit(":", 1)[-1]
    terminal_positions = dict(positions)
    terminal_colors = dict(colors)
    terminal_active_ref = active_ref
    terminal_certificate = required
    recovery_actions: list[PlannedClick] = []
    for purpose, endpoint_ref, inverse_coordinate, group in reversed(inverse_specs):
        required_scene = projected_scene() if carrier_source_supports else None
        if purpose is VisualActionPurpose.PROBE:
            if endpoint_ref == active_ref or colors[endpoint_ref] == hierarchy.active_color:
                raise ValueError("hierarchy recovery role exchange is not reversible")
            colors[active_ref], colors[endpoint_ref] = (
                colors[endpoint_ref],
                colors[active_ref],
            )
            active_ref = endpoint_ref
            expectation = "reverse one certified hierarchy active-role exchange"
        else:
            if endpoint_ref != active_ref:
                raise ValueError("hierarchy recovery movement lost active-endpoint lineage")
            positions[active_ref] = inverse_coordinate
            expectation = "restore one endpoint to its exact pre-hypothesis position"
        expected = certificate()
        recovery_actions.append(
            require_masked_lineage_only_if_needed(
                PlannedClick(
                    coordinate=Coordinate(*inverse_coordinate),
                    purpose=purpose,
                    expectation=expectation,
                    mechanic_ref=hierarchy.mechanic_ref,
                    plan_id=recovery_plan_id,
                    plan_signature=recovery_signature,
                    target_center=hierarchy.target.rounded_center,
                    mediator_color=group.mediator.color,
                    arity=group.arity,
                    expected_active_center=positions[active_ref],
                    required_child_protected_raster_hash=required.protected_raster_hash,
                    expected_child_protected_raster_hash=expected.protected_raster_hash,
                    expected_visible_endpoint_count=expected.visible_endpoint_count,
                    expected_visible_mediator_count=expected.visible_mediator_count,
                ),
                required_scene,
            )
        )
        required = expected

    if (
        positions != initial_positions
        or colors != initial_colors
        or required != initial_certificate
    ):
        raise ValueError("hierarchy recovery did not return to its exact observed origin")

    if carrier_source_supports:
        positions.clear()
        positions.update(terminal_positions)
        colors.clear()
        colors.update(terminal_colors)
        active_ref = terminal_active_ref

        def source_subset_projected_scene(
            carried_support_indexes: frozenset[int],
            *,
            projected_positions: dict[str, tuple[int, int]],
            projected_colors: dict[str, int],
        ) -> VisualScene:
            return _carrier_source_carried_projected_scene(
                scene,
                hierarchy,
                carrier_source_supports,
                positions=projected_positions,
                colors=projected_colors,
                carried_support_indexes=carried_support_indexes,
            )

        def source_subset_certificate(projected: VisualScene) -> _HierarchyRasterCertificate:
            return _HierarchyRasterCertificate(
                protected_raster_hash=_child_isolation_protected_raster_hash(projected),
                visible_endpoint_count=len(projected.endpoints),
                visible_mediator_count=len(projected.mediators),
            )

        empty_terminal_scene = source_subset_projected_scene(
            frozenset(),
            projected_positions=positions,
            projected_colors=colors,
        )
        if source_subset_certificate(empty_terminal_scene) != terminal_certificate:
            raise ValueError(
                "carrier-source recovery lattice must share the observed terminal boundary"
            )

        raw_target_route = _carrier_source_raw_target_child_route(
            scene,
            hierarchy,
            carrier_source_supports,
        )

        def target_delivery_actions(
            *,
            support_index: int,
            carried_subset: frozenset[int],
        ) -> tuple[PlannedClick, ...]:
            if (
                raw_target_route is None
                or raw_target_route[0] != support_index
                or carried_subset != frozenset({support_index})
            ):
                return ()
            support = carrier_source_supports[support_index]
            route = raw_target_route[1]
            delivery_positions = dict(positions)
            delivery_colors = dict(colors)
            delivery_active_refs = tuple(
                ref for ref, color in delivery_colors.items() if color == hierarchy.active_color
            )
            if len(delivery_active_refs) != 1 or delivery_active_refs[0] != route[0][0]:
                return ()
            delivery_active_ref = delivery_active_refs[0]
            baseline_positions = dict(delivery_positions)
            baseline_scene = source_subset_projected_scene(
                carried_subset,
                projected_positions=delivery_positions,
                projected_colors=delivery_colors,
            )
            if (
                _carrier_source_target_delivery_projected_state_is_safe(
                    scene,
                    baseline_scene,
                    hierarchy,
                    carrier_source_supports,
                    support_index=support_index,
                    baseline_positions=baseline_positions,
                    positions=delivery_positions,
                    colors=delivery_colors,
                    completes_delivery=False,
                )
                is None
            ):
                return ()
            delivery_plan_id = (
                "visual-carrier-source-delivery:"
                + hashlib.sha256(
                    (
                        f"{recovery_signature}|{support.child.mediator.object_ref}|"
                        + ";".join(f"{ref}>{point[0]},{point[1]}" for ref, point in route)
                    ).encode("ascii")
                ).hexdigest()[:24]
            )
            subset_indexes = tuple(sorted(carried_subset))
            required_scene = baseline_scene
            required_certificate = source_subset_certificate(required_scene)
            planned_actions: list[PlannedClick] = []

            def attachment_continuation_actions(
                *,
                restored_positions: dict[str, tuple[int, int]],
                restored_colors: dict[str, int],
                restored_scene: VisualScene,
            ) -> tuple[PlannedClick, ...]:
                """Derive one exact alternative-endpoint detachment after restoration."""

                final_mover_ref, final_point = route[-1]
                active_refs = tuple(
                    ref for ref, color in restored_colors.items() if color == hierarchy.active_color
                )
                if len(active_refs) != 1 or active_refs[0] != final_mover_ref:
                    return ()

                redelivery_positions = dict(restored_positions)
                redelivery_positions[final_mover_ref] = final_point
                redelivery_scene = _carrier_source_target_delivery_projected_state_is_safe(
                    scene,
                    baseline_scene,
                    hierarchy,
                    carrier_source_supports,
                    support_index=support_index,
                    baseline_positions=baseline_positions,
                    positions=redelivery_positions,
                    colors=restored_colors,
                    completes_delivery=True,
                )
                if redelivery_scene is None:
                    return ()
                restored_certificate = source_subset_certificate(restored_scene)
                redelivery_certificate = source_subset_certificate(redelivery_scene)
                continuation_candidates: dict[str, tuple[PlannedClick, ...]] = {}
                for alternate_ref, alternate_point in route[:-1]:
                    alternate_predecessor = baseline_positions.get(alternate_ref)
                    if (
                        alternate_predecessor is None
                        or alternate_ref == final_mover_ref
                        or restored_positions.get(alternate_ref) != alternate_point
                        or alternate_point == alternate_predecessor
                    ):
                        continue
                    continuation_plan_id = (
                        "visual-carrier-source-detachment:"
                        + hashlib.sha256(
                            (
                                f"{delivery_plan_id}|{final_mover_ref}|{alternate_ref}|"
                                f"{alternate_predecessor[0]},{alternate_predecessor[1]}"
                            ).encode("ascii")
                        ).hexdigest()[:24]
                    )
                    alternate_colors = dict(restored_colors)
                    alternate_colors[final_mover_ref], alternate_colors[alternate_ref] = (
                        alternate_colors[alternate_ref],
                        alternate_colors[final_mover_ref],
                    )
                    role_scene = _carrier_source_target_delivery_projected_state_is_safe(
                        scene,
                        baseline_scene,
                        hierarchy,
                        carrier_source_supports,
                        support_index=support_index,
                        baseline_positions=baseline_positions,
                        positions=redelivery_positions,
                        colors=alternate_colors,
                        completes_delivery=True,
                    )
                    if role_scene is None:
                        continue
                    role_certificate = source_subset_certificate(role_scene)
                    alternate_positions = dict(redelivery_positions)
                    alternate_positions[alternate_ref] = alternate_predecessor
                    try:
                        redelivery = require_masked_lineage_only_if_needed(
                            PlannedClick(
                                coordinate=Coordinate(*final_point),
                                purpose=VisualActionPurpose.PROGRESS,
                                expectation=(
                                    "re-establish the exact observed target-centered carrier "
                                    "state before an alternative-endpoint detachment"
                                ),
                                mechanic_ref=hierarchy.mechanic_ref,
                                plan_id=continuation_plan_id,
                                plan_signature=recovery_signature,
                                target_center=hierarchy.target.rounded_center,
                                mediator_color=support.child.mediator.color,
                                arity=support.child.arity,
                                expected_active_center=final_point,
                                required_child_protected_raster_hash=(
                                    restored_certificate.protected_raster_hash
                                ),
                                expected_child_protected_raster_hash=(
                                    redelivery_certificate.protected_raster_hash
                                ),
                                expected_visible_endpoint_count=(
                                    redelivery_certificate.visible_endpoint_count
                                ),
                                expected_visible_mediator_count=(
                                    redelivery_certificate.visible_mediator_count
                                ),
                                required_carried_source_support_indexes=subset_indexes,
                                expected_carried_source_support_indexes=subset_indexes,
                                carrier_source_delivery_step=True,
                            ),
                            restored_scene,
                        )
                        role_exchange = require_masked_lineage_only_if_needed(
                            PlannedClick(
                                coordinate=Coordinate(*alternate_point),
                                purpose=VisualActionPurpose.PROBE,
                                expectation=(
                                    "select the unique minimum-distance endpoint among exact "
                                    "target-preserving historical inverse candidates"
                                ),
                                mechanic_ref=hierarchy.mechanic_ref,
                                plan_id=continuation_plan_id,
                                plan_signature=recovery_signature,
                                target_center=hierarchy.target.rounded_center,
                                mediator_color=support.child.mediator.color,
                                arity=support.child.arity,
                                expected_active_center=alternate_point,
                                required_child_protected_raster_hash=(
                                    redelivery_certificate.protected_raster_hash
                                ),
                                expected_child_protected_raster_hash=(
                                    role_certificate.protected_raster_hash
                                ),
                                expected_visible_endpoint_count=(
                                    role_certificate.visible_endpoint_count
                                ),
                                expected_visible_mediator_count=(
                                    role_certificate.visible_mediator_count
                                ),
                                required_carried_source_support_indexes=subset_indexes,
                                expected_carried_source_support_indexes=subset_indexes,
                                carrier_source_delivery_step=True,
                                carrier_source_target_center_role_exchange_step=True,
                            ),
                            redelivery_scene,
                        )
                        carried_alternate_scene = _carrier_source_carried_projected_scene(
                            scene,
                            hierarchy,
                            carrier_source_supports,
                            positions=alternate_positions,
                            colors=alternate_colors,
                            carried_support_indexes=carried_subset,
                        )
                        deposited_alternate_scene = _carrier_source_carried_projected_scene(
                            scene,
                            hierarchy,
                            carrier_source_supports,
                            positions=alternate_positions,
                            colors=alternate_colors,
                            carried_support_indexes=carried_subset,
                            fixed_source_centers={support_index: hierarchy.target.rounded_center},
                        )
                    except ValueError:
                        continue

                    alternate_endpoint_centers = tuple(
                        alternate_positions[endpoint.object_ref]
                        for endpoint in support.child.endpoints
                    )
                    alternate_mediator_center = (
                        sum(center[0] for center in alternate_endpoint_centers)
                        // support.child.arity,
                        sum(center[1] for center in alternate_endpoint_centers)
                        // support.child.arity,
                    )
                    role_endpoint_centers = tuple(
                        redelivery_positions[endpoint.object_ref]
                        for endpoint in support.child.endpoints
                    )
                    role_dynamic = _hierarchy_projected_group_footprint(
                        support.child,
                        endpoint_centers=role_endpoint_centers,
                        mediator_center=hierarchy.target.rounded_center,
                    )
                    alternate_dynamic = _hierarchy_projected_group_footprint(
                        support.child,
                        endpoint_centers=alternate_endpoint_centers,
                        mediator_center=alternate_mediator_center,
                    )
                    source_x, source_y = support.source.center
                    role_source = frozenset(
                        (
                            hierarchy.target.rounded_center[0] + x - source_x,
                            hierarchy.target.rounded_center[1] + y - source_y,
                        )
                        for x, y in support.source.cells
                    )
                    alternate_source = frozenset(
                        (
                            alternate_mediator_center[0] + x - source_x,
                            alternate_mediator_center[1] + y - source_y,
                        )
                        for x, y in support.source.cells
                    )
                    stationary_occupied = (
                        frozenset(
                            (x, y)
                            for y, row in enumerate(role_scene.cells)
                            for x, value in enumerate(row)
                            if value != role_scene.background
                        )
                        - role_dynamic
                        - role_source
                    )
                    alternate_mutable = (
                        role_dynamic | alternate_dynamic | role_source | alternate_source
                    )
                    target_surface = frozenset(hierarchy.target.cells)
                    if (
                        len(alternate_source) != len(support.source.cells)
                        or not _hierarchy_cells_in_bounds(scene, alternate_source)
                        or any(
                            alternate_source
                            & _translated_object_footprint(
                                endpoint,
                                center=alternate_positions[endpoint.object_ref],
                            )
                            for endpoint in support.child.endpoints
                        )
                        or bool(alternate_source & target_surface)
                        or bool((alternate_dynamic | alternate_source) & stationary_occupied)
                        or any(
                            carried_alternate_scene.cells[y][x] != role_scene.cells[y][x]
                            for y in range(scene.height)
                            for x in range(scene.width)
                            if (x, y) not in alternate_mutable
                        )
                        or any(
                            carried_alternate_scene.cells[y][x] != baseline_scene.cells[y][x]
                            or deposited_alternate_scene.cells[y][x] != baseline_scene.cells[y][x]
                            for x, y in hierarchy.target.cells
                        )
                        or any(
                            carried_alternate_scene.cells[
                                alternate_mediator_center[1] + y - source_y
                            ][alternate_mediator_center[0] + x - source_x]
                            != scene.cells[y][x]
                            for x, y in support.source.cells
                        )
                    ):
                        continue
                    carried_alternate_certificate = source_subset_certificate(
                        carried_alternate_scene
                    )
                    deposited_alternate_certificate = source_subset_certificate(
                        deposited_alternate_scene
                    )
                    target_x, target_y = hierarchy.target.rounded_center
                    if not (
                        carried_alternate_certificate != deposited_alternate_certificate
                        and all(
                            deposited_alternate_scene.cells[target_y + y - source_y][
                                target_x + x - source_x
                            ]
                            == scene.cells[y][x]
                            for x, y in support.source.cells
                        )
                    ):
                        continue
                    try:
                        alternate_detachment = require_masked_lineage_only_if_needed(
                            PlannedClick(
                                coordinate=Coordinate(*alternate_predecessor),
                                purpose=VisualActionPurpose.PROGRESS,
                                expectation=(
                                    "move the uniquely selected endpoint to its exact "
                                    "historical predecessor to discriminate deposition from "
                                    "continued attachment"
                                ),
                                mechanic_ref=hierarchy.mechanic_ref,
                                plan_id=continuation_plan_id,
                                plan_signature=recovery_signature,
                                target_center=hierarchy.target.rounded_center,
                                mediator_color=support.child.mediator.color,
                                arity=support.child.arity,
                                expected_active_center=alternate_predecessor,
                                required_child_protected_raster_hash=(
                                    role_certificate.protected_raster_hash
                                ),
                                expected_child_protected_raster_hash=(
                                    carried_alternate_certificate.protected_raster_hash
                                ),
                                expected_visible_endpoint_count=(
                                    carried_alternate_certificate.visible_endpoint_count
                                ),
                                expected_visible_mediator_count=(
                                    carried_alternate_certificate.visible_mediator_count
                                ),
                                required_carried_source_support_indexes=subset_indexes,
                                expected_carried_source_support_indexes=subset_indexes,
                                carrier_source_detachment_step=True,
                                expected_deposited_source_protected_raster_hash=(
                                    deposited_alternate_certificate.protected_raster_hash
                                ),
                                expected_deposited_visible_endpoint_count=(
                                    deposited_alternate_certificate.visible_endpoint_count
                                ),
                                expected_deposited_visible_mediator_count=(
                                    deposited_alternate_certificate.visible_mediator_count
                                ),
                            ),
                            role_scene,
                        )
                    except ValueError:
                        continue
                    continuation_candidates[alternate_ref] = (
                        redelivery,
                        role_exchange,
                        alternate_detachment,
                    )

                alternative_inverse = _carrier_source_attachment_alternative_inverse(
                    route,
                    baseline_positions=baseline_positions,
                    safe_endpoint_refs=frozenset(continuation_candidates),
                )
                if alternative_inverse is None:
                    return ()
                return continuation_candidates[alternative_inverse[0]]

            for mover_index, (mover_ref, point) in enumerate(route):
                if mover_ref != delivery_active_ref:
                    if delivery_colors[mover_ref] == hierarchy.active_color:
                        return ()
                    selected_at = delivery_positions[mover_ref]
                    if sum(center == selected_at for center in delivery_positions.values()) != 1:
                        return ()
                    delivery_colors[delivery_active_ref], delivery_colors[mover_ref] = (
                        delivery_colors[mover_ref],
                        delivery_colors[delivery_active_ref],
                    )
                    delivery_active_ref = mover_ref
                    expected_scene = _carrier_source_target_delivery_projected_state_is_safe(
                        scene,
                        baseline_scene,
                        hierarchy,
                        carrier_source_supports,
                        support_index=support_index,
                        baseline_positions=baseline_positions,
                        positions=delivery_positions,
                        colors=delivery_colors,
                        completes_delivery=False,
                    )
                    if expected_scene is None:
                        return ()
                    expected_certificate = source_subset_certificate(expected_scene)
                    planned_actions.append(
                        require_masked_lineage_only_if_needed(
                            PlannedClick(
                                coordinate=Coordinate(*selected_at),
                                purpose=VisualActionPurpose.PROBE,
                                expectation=(
                                    "exchange roles within the uniquely raw-linked carried "
                                    "child while preserving exact source attachment"
                                ),
                                mechanic_ref=hierarchy.mechanic_ref,
                                plan_id=delivery_plan_id,
                                plan_signature=recovery_signature,
                                target_center=hierarchy.target.rounded_center,
                                mediator_color=support.child.mediator.color,
                                arity=support.child.arity,
                                expected_active_center=selected_at,
                                required_child_protected_raster_hash=(
                                    required_certificate.protected_raster_hash
                                ),
                                expected_child_protected_raster_hash=(
                                    expected_certificate.protected_raster_hash
                                ),
                                expected_visible_endpoint_count=(
                                    expected_certificate.visible_endpoint_count
                                ),
                                expected_visible_mediator_count=(
                                    expected_certificate.visible_mediator_count
                                ),
                                required_carried_source_support_indexes=subset_indexes,
                                expected_carried_source_support_indexes=subset_indexes,
                                carrier_source_delivery_step=True,
                            ),
                            required_scene,
                        )
                    )
                    required_scene = expected_scene
                    required_certificate = expected_certificate

                if mover_ref != delivery_active_ref or delivery_positions[mover_ref] == point:
                    return ()
                inverse_positions = dict(delivery_positions)
                inverse_coordinate = delivery_positions[mover_ref]
                delivery_positions[mover_ref] = point
                completes_delivery = mover_index + 1 == len(route)
                expected_scene = _carrier_source_target_delivery_projected_state_is_safe(
                    scene,
                    baseline_scene,
                    hierarchy,
                    carrier_source_supports,
                    support_index=support_index,
                    baseline_positions=baseline_positions,
                    positions=delivery_positions,
                    colors=delivery_colors,
                    completes_delivery=completes_delivery,
                )
                if expected_scene is None:
                    return ()
                expected_certificate = source_subset_certificate(expected_scene)
                detachment_probe: PlannedClick | None = None
                if completes_delivery:
                    try:
                        carried_inverse_scene = source_subset_projected_scene(
                            carried_subset,
                            projected_positions=inverse_positions,
                            projected_colors=delivery_colors,
                        )
                        carried_inverse_certificate = source_subset_certificate(
                            carried_inverse_scene
                        )
                        deposited_inverse_scene: VisualScene | None = None
                        if carried_inverse_scene.cells == required_scene.cells:
                            deposited_inverse_scene = _carrier_source_carried_projected_scene(
                                scene,
                                hierarchy,
                                carrier_source_supports,
                                positions=inverse_positions,
                                colors=delivery_colors,
                                carried_support_indexes=carried_subset,
                                fixed_source_centers={
                                    support_index: hierarchy.target.rounded_center
                                },
                            )
                        if deposited_inverse_scene is not None:
                            deposited_inverse_certificate = source_subset_certificate(
                                deposited_inverse_scene
                            )
                            attachment_continuation = (
                                attachment_continuation_actions(
                                    restored_positions=inverse_positions,
                                    restored_colors=delivery_colors,
                                    restored_scene=carried_inverse_scene,
                                )
                                if derive_carrier_source_attachment_continuations
                                else ()
                            )
                            source_x, source_y = support.source.center
                            target_x, target_y = hierarchy.target.rounded_center
                            detachment_branches_are_exact = bool(
                                deposited_inverse_certificate != carried_inverse_certificate
                                and (
                                    not derive_carrier_source_attachment_continuations
                                    or attachment_continuation
                                )
                                and all(
                                    deposited_inverse_scene.cells[y][x]
                                    == expected_scene.cells[y][x]
                                    for x, y in hierarchy.target.cells
                                )
                                and all(
                                    deposited_inverse_scene.cells[target_y + y - source_y][
                                        target_x + x - source_x
                                    ]
                                    == scene.cells[y][x]
                                    for x, y in support.source.cells
                                )
                            )
                            if detachment_branches_are_exact:
                                detachment_plan_id = (
                                    "visual-carrier-source-detachment:"
                                    + hashlib.sha256(
                                        (
                                            f"{delivery_plan_id}|{mover_ref}|"
                                            f"{inverse_coordinate[0]},{inverse_coordinate[1]}"
                                        ).encode("ascii")
                                    ).hexdigest()[:24]
                                )
                                detachment_probe = require_masked_lineage_only_if_needed(
                                    PlannedClick(
                                        coordinate=Coordinate(*inverse_coordinate),
                                        purpose=VisualActionPurpose.PROGRESS,
                                        expectation=(
                                            "detach the target-centered child with one exact "
                                            "inverse to discriminate deposited source from "
                                            "continued attachment"
                                        ),
                                        mechanic_ref=hierarchy.mechanic_ref,
                                        plan_id=detachment_plan_id,
                                        plan_signature=recovery_signature,
                                        target_center=hierarchy.target.rounded_center,
                                        mediator_color=support.child.mediator.color,
                                        arity=support.child.arity,
                                        expected_active_center=inverse_coordinate,
                                        required_child_protected_raster_hash=(
                                            expected_certificate.protected_raster_hash
                                        ),
                                        expected_child_protected_raster_hash=(
                                            carried_inverse_certificate.protected_raster_hash
                                        ),
                                        expected_visible_endpoint_count=(
                                            carried_inverse_certificate.visible_endpoint_count
                                        ),
                                        expected_visible_mediator_count=(
                                            carried_inverse_certificate.visible_mediator_count
                                        ),
                                        required_carried_source_support_indexes=subset_indexes,
                                        expected_carried_source_support_indexes=subset_indexes,
                                        carrier_source_detachment_step=True,
                                        carrier_source_attachment_continuation_actions=(
                                            attachment_continuation
                                        ),
                                        expected_deposited_source_protected_raster_hash=(
                                            deposited_inverse_certificate.protected_raster_hash
                                        ),
                                        expected_deposited_visible_endpoint_count=(
                                            deposited_inverse_certificate.visible_endpoint_count
                                        ),
                                        expected_deposited_visible_mediator_count=(
                                            deposited_inverse_certificate.visible_mediator_count
                                        ),
                                    ),
                                    expected_scene,
                                )
                    except (IndexError, ValueError):
                        detachment_probe = None
                planned_actions.append(
                    require_masked_lineage_only_if_needed(
                        PlannedClick(
                            coordinate=Coordinate(*point),
                            purpose=VisualActionPurpose.PROGRESS,
                            expectation=(
                                "deliver the exact carried source to its unique observed raw "
                                "target; only official progress or WIN establishes completion"
                                if completes_delivery
                                else (
                                    "move the exact carried source along its previously "
                                    "certified target-centered child layout"
                                )
                            ),
                            mechanic_ref=hierarchy.mechanic_ref,
                            plan_id=delivery_plan_id,
                            plan_signature=recovery_signature,
                            target_center=hierarchy.target.rounded_center,
                            mediator_color=support.child.mediator.color,
                            arity=support.child.arity,
                            expected_active_center=point,
                            required_child_protected_raster_hash=(
                                required_certificate.protected_raster_hash
                            ),
                            expected_child_protected_raster_hash=(
                                expected_certificate.protected_raster_hash
                            ),
                            expected_visible_endpoint_count=(
                                expected_certificate.visible_endpoint_count
                            ),
                            expected_visible_mediator_count=(
                                expected_certificate.visible_mediator_count
                            ),
                            required_carried_source_support_indexes=subset_indexes,
                            expected_carried_source_support_indexes=subset_indexes,
                            carrier_source_delivery_step=True,
                            completes_carrier_source_delivery=completes_delivery,
                            carrier_source_detachment_probe=detachment_probe,
                        ),
                        required_scene,
                    )
                )
                required_scene = expected_scene
                required_certificate = expected_certificate
            return (
                tuple(planned_actions)
                if len(planned_actions) == 2 * support.child.arity - 1
                and planned_actions[-1].completes_carrier_source_delivery
                else ()
            )

        reachable_subsets: set[frozenset[int]] = {frozenset()}
        for action_index, (purpose, endpoint_ref, inverse_coordinate, group) in enumerate(
            reversed(inverse_specs)
        ):
            before_positions = dict(positions)
            before_colors = dict(colors)
            if purpose is VisualActionPurpose.PROBE:
                if endpoint_ref == active_ref or colors[endpoint_ref] == hierarchy.active_color:
                    raise ValueError("carrier-source recovery role exchange is not reversible")
                colors[active_ref], colors[endpoint_ref] = (
                    colors[endpoint_ref],
                    colors[active_ref],
                )
                active_ref = endpoint_ref
                expectation = "reverse one certified hierarchy active-role exchange"
            else:
                if endpoint_ref != active_ref:
                    raise ValueError(
                        "carrier-source recovery movement lost active-endpoint lineage"
                    )
                positions[active_ref] = inverse_coordinate
                expectation = "restore one endpoint to its exact pre-hypothesis position"

            moved_support_index: int | None = None
            if purpose is VisualActionPurpose.PROGRESS:
                support_index = next(
                    index
                    for index, support in enumerate(carrier_source_supports)
                    if support.child.mediator.object_ref == group.mediator.object_ref
                )
                support = carrier_source_supports[support_index]
                before_endpoint_centers = tuple(
                    before_positions[endpoint.object_ref] for endpoint in support.child.endpoints
                )
                after_endpoint_centers = tuple(
                    positions[endpoint.object_ref] for endpoint in support.child.endpoints
                )
                before_support_center = (
                    sum(center[0] for center in before_endpoint_centers) // support.child.arity,
                    sum(center[1] for center in before_endpoint_centers) // support.child.arity,
                )
                after_support_center = (
                    sum(center[0] for center in after_endpoint_centers) // support.child.arity,
                    sum(center[1] for center in after_endpoint_centers) // support.child.arity,
                )
                if before_support_center != after_support_center:
                    moved_support_index = support_index

            state_candidates: list[tuple[frozenset[int], PlannedClick]] = []
            next_reachable_subsets: set[frozenset[int]] = set()
            for carried_subset in sorted(reachable_subsets, key=lambda item: tuple(sorted(item))):
                required_scene = source_subset_projected_scene(
                    carried_subset,
                    projected_positions=before_positions,
                    projected_colors=before_colors,
                )
                required_certificate = source_subset_certificate(required_scene)
                expected_scene = source_subset_projected_scene(
                    carried_subset,
                    projected_positions=positions,
                    projected_colors=colors,
                )
                expected_certificate = source_subset_certificate(expected_scene)
                candidate = require_masked_lineage_only_if_needed(
                    PlannedClick(
                        coordinate=Coordinate(*inverse_coordinate),
                        purpose=purpose,
                        expectation=expectation,
                        mechanic_ref=hierarchy.mechanic_ref,
                        plan_id=recovery_plan_id,
                        plan_signature=recovery_signature,
                        target_center=hierarchy.target.rounded_center,
                        mediator_color=group.mediator.color,
                        arity=group.arity,
                        expected_active_center=positions[active_ref],
                        required_child_protected_raster_hash=(
                            required_certificate.protected_raster_hash
                        ),
                        expected_child_protected_raster_hash=(
                            expected_certificate.protected_raster_hash
                        ),
                        expected_visible_endpoint_count=(
                            expected_certificate.visible_endpoint_count
                        ),
                        expected_visible_mediator_count=(
                            expected_certificate.visible_mediator_count
                        ),
                        required_carried_source_support_indexes=tuple(sorted(carried_subset)),
                        expected_carried_source_support_indexes=tuple(sorted(carried_subset)),
                    ),
                    required_scene,
                )
                next_reachable_subsets.add(carried_subset)
                if moved_support_index is not None and moved_support_index not in carried_subset:
                    newly_carried_subset = carried_subset | {moved_support_index}
                    carried_expected_scene = source_subset_projected_scene(
                        newly_carried_subset,
                        projected_positions=positions,
                        projected_colors=colors,
                    )
                    carried_expected_certificate = source_subset_certificate(carried_expected_scene)
                    alternative = require_masked_lineage_only_if_needed(
                        replace(
                            candidate,
                            expected_child_protected_raster_hash=(
                                carried_expected_certificate.protected_raster_hash
                            ),
                            expected_visible_endpoint_count=(
                                carried_expected_certificate.visible_endpoint_count
                            ),
                            expected_visible_mediator_count=(
                                carried_expected_certificate.visible_mediator_count
                            ),
                            expected_carried_source_support_indexes=tuple(
                                sorted(newly_carried_subset)
                            ),
                        ),
                        required_scene,
                    )
                    delivery_actions = target_delivery_actions(
                        support_index=moved_support_index,
                        carried_subset=frozenset(newly_carried_subset),
                    )
                    if delivery_actions:
                        alternative = replace(
                            alternative,
                            carrier_source_delivery_actions=delivery_actions,
                        )
                    candidate = replace(
                        candidate,
                        carrier_source_recovery_alternative=alternative,
                    )
                    next_reachable_subsets.add(frozenset(newly_carried_subset))
                state_candidates.append((carried_subset, candidate))

            primary = next(candidate for subset, candidate in state_candidates if not subset)
            if (
                replace(
                    primary,
                    carrier_source_recovery_alternative=None,
                )
                != recovery_actions[action_index]
            ):
                raise ValueError("carrier-source recovery changed its static certificate")
            recovery_actions[action_index] = replace(
                primary,
                carrier_source_recovery_candidates=tuple(
                    candidate for subset, candidate in state_candidates if subset
                ),
            )
            reachable_subsets = next_reachable_subsets

        if positions != initial_positions or colors != initial_colors:
            raise ValueError(
                "carrier-source recovery lattice did not restore endpoint state exactly"
            )

    attachment_replay_context: _CarrierSourceAttachmentReplayContext | None = None
    if carrier_source_supports:
        assert carrier_source_level_index is not None
        assert carrier_source_rejected_external_relation_key is not None
        attachment_replay_context = _CarrierSourceAttachmentReplayContext(
            hierarchy=hierarchy,
            layouts=layouts,
            scene=scene,
            move_order=move_order,
            support_weights=support_weights,
            carrier_source_supports=carrier_source_supports,
            level_index=carrier_source_level_index,
            rejected_external_residual_relation_key=(carrier_source_rejected_external_relation_key),
            signature_prefix=signature_prefix,
            terminal_expectation=terminal_expectation,
        )
    return _HierarchyPlan(
        actions=tuple(actions),
        signature=signature,
        supports=tuple(layout.support for layout in layouts),
        support_weights=weights,
        recovery_actions=tuple(recovery_actions),
        carrier_source_attachment_replay_context=attachment_replay_context,
    )


def _target_support_hierarchy_plan(
    scene: VisualScene,
    hierarchy: _AffineHierarchy,
    supports: tuple[_HierarchyTargetSupport, ...],
    *,
    bridge_relation: _CompositeBridgeRelation | None,
    rejected_signatures: set[str],
    signature_prefix: str,
    terminal_expectation: str,
    search_budget: _HierarchySearchBudget | None = None,
) -> _HierarchyPlan | None:
    """Find one exact route to an observation-derived per-child support tuple."""

    if search_budget is None:
        search_budget = _HierarchySearchBudget(_MAX_HIERARCHY_SEARCH_BUDGET)
    if tuple(item.child for item in supports) != hierarchy.children:
        return None
    active = tuple(item for item in scene.endpoints if item.color == hierarchy.active_color)
    if len(active) != 1 or active[0] not in hierarchy.children[0].endpoints:
        return None
    initial_dynamic = frozenset(
        cell for child in hierarchy.children for cell in _hierarchy_dynamic_footprint(scene, child)
    )
    occupied = frozenset(
        (x, y)
        for y, row in enumerate(scene.cells)
        for x, value in enumerate(row)
        if value != scene.background
    )
    static_cells = occupied - initial_dynamic
    endpoint_target_regions = _visible_target_regions(scene)
    sink_surfaces = {item.target.rounded_center: frozenset(item.target.cells) for item in supports}
    dynamic_target_regions = tuple(
        (center, sink_surfaces.get(center, region)) for center, region in endpoint_target_regions
    )
    sink_centers = frozenset(sink_surfaces)
    preserved_target_signature = tuple(
        item for item in _target_surface_signature(scene) if item[1] not in sink_centers
    )
    ignored_refs = frozenset(
        item.object_ref
        for child in hierarchy.children
        for item in (*child.endpoints, child.mediator)
    )
    layout_sets: list[tuple[_HierarchyChildLayout, ...]] = []
    for child_index, support in enumerate(supports):
        child = support.child
        layouts = _hierarchy_child_layouts(
            scene,
            hierarchy,
            child,
            support=support.target.rounded_center,
            active_ref=active[0].object_ref if child_index == 0 else None,
            static_cells=static_cells,
            target_regions=dynamic_target_regions,
            endpoint_target_regions=endpoint_target_regions,
            ignored_refs=ignored_refs,
            search_budget=search_budget,
            result_limit=128,
        )
        if not layouts:
            return None
        layout_sets.append(
            tuple(
                sorted(
                    layouts,
                    key=lambda item: (
                        item.radius,
                        item.movement_cost,
                        item.points,
                        tuple(mover.object_ref for mover in item.movers),
                    ),
                )
            )
        )

    lengths = tuple(len(items) for items in layout_sets)
    # Bridge search shares the same bounded layout-combination authority as the
    # other hierarchy planners. State memoization retains fair traversal without
    # needing a larger family-specific cap.
    combination_limit = min(math.prod(lengths), _MAX_HIERARCHY_LAYOUT_COMBINATIONS)
    state_cache: dict[_BridgeProjectedStateKey, bool] = {}
    for indices in _fair_index_products(lengths, limit=combination_limit):
        search_budget.consume()
        layouts = tuple(
            layout_sets[index][layout_index] for index, layout_index in enumerate(indices)
        )
        if not _bridge_final_layout_geometry_is_safe(hierarchy, layouts):
            continue
        if bridge_relation is not None:
            sequence_is_safe = _bridge_hierarchy_sequence_is_safe(
                scene,
                hierarchy,
                bridge_relation,
                layouts,
                static_cells=static_cells,
                dynamic_target_regions=dynamic_target_regions,
                endpoint_target_regions=endpoint_target_regions,
                preserved_target_signature=preserved_target_signature,
                search_budget=search_budget,
                state_cache=state_cache,
            )
        else:
            sequence_is_safe = _residual_linked_hierarchy_sequence_is_safe(
                scene,
                hierarchy,
                supports,
                layouts,
                static_cells=static_cells,
                dynamic_target_regions=dynamic_target_regions,
                endpoint_target_regions=endpoint_target_regions,
                preserved_target_signature=preserved_target_signature,
                search_budget=search_budget,
                state_cache=state_cache,
            )
        if not sequence_is_safe:
            continue
        plan = _build_hierarchy_plan(
            hierarchy,
            layouts,
            scene=scene,
            signature_prefix=signature_prefix,
            terminal_expectation=terminal_expectation,
        )
        if plan.signature not in rejected_signatures:
            return plan
    return None


def _same_child_composite_cargo_mediator_centers(
    hierarchy: _AffineHierarchy,
    positions: dict[str, tuple[int, int]],
) -> tuple[tuple[int, int], ...]:
    """Return every child centroid from one complete endpoint-position state."""

    return tuple(
        (
            sum(positions[endpoint.object_ref][0] for endpoint in child.endpoints) // child.arity,
            sum(positions[endpoint.object_ref][1] for endpoint in child.endpoints) // child.arity,
        )
        for child in hierarchy.children
    )


def _same_child_composite_cargo_projected_state_is_safe_uncached(
    scene: VisualScene,
    hierarchy: _AffineHierarchy,
    relation: _CompositeBridgeRelation,
    *,
    positions: dict[str, tuple[int, int]],
    colors: dict[str, int],
    collected_source_keys: frozenset[_CompositeCargoSourceKey],
    static_cells: frozenset[tuple[int, int]],
) -> VisualScene | None:
    """Return an exact cargo projection only when every unrelated cell is protected."""

    mediator_centers = _same_child_composite_cargo_mediator_centers(hierarchy, positions)
    group_dynamic: list[frozenset[tuple[int, int]]] = []
    mediator_footprints: list[frozenset[tuple[int, int]]] = []
    endpoint_footprints: list[tuple[str, frozenset[tuple[int, int]]]] = []
    for child, mediator_center in zip(
        hierarchy.children,
        mediator_centers,
        strict=True,
    ):
        endpoint_centers = tuple(positions[endpoint.object_ref] for endpoint in child.endpoints)
        dynamic = _hierarchy_projected_group_footprint(
            child,
            endpoint_centers=endpoint_centers,
            mediator_center=mediator_center,
        )
        endpoints = tuple(
            (
                endpoint.object_ref,
                _translated_object_footprint(endpoint, center=center),
            )
            for endpoint, center in zip(
                child.endpoints,
                endpoint_centers,
                strict=True,
            )
        )
        mediator_footprint = _translated_object_footprint(
            child.mediator,
            center=mediator_center,
        )
        if (
            not _hierarchy_cells_in_bounds(scene, dynamic)
            or mediator_footprint & static_cells
            or any(
                not _hierarchy_cells_in_bounds(scene, footprint) for _ref, footprint in endpoints
            )
            or any(
                not _footprints_have_gap(left, right, gap=1)
                for (_left_ref, left), (_right_ref, right) in itertools.combinations(
                    endpoints,
                    2,
                )
            )
        ):
            return None
        group_dynamic.append(dynamic)
        mediator_footprints.append(mediator_footprint)
        endpoint_footprints.extend(endpoints)
    if any(left & right for left, right in itertools.combinations(group_dynamic, 2)) or any(
        colors[left_ref] == colors[right_ref] and not _footprints_have_gap(left, right, gap=1)
        for (left_ref, left), (right_ref, right) in itertools.combinations(
            endpoint_footprints,
            2,
        )
    ):
        return None

    source_surfaces = {
        (child_index, source_index): frozenset(source.cells)
        for child_index, (_child, example) in enumerate(relation.assignments)
        for source_index, source in enumerate(example.sources)
    }
    assigned_target_cells = frozenset(
        cell for _child, example in relation.assignments for cell in example.target.cells
    )
    if any(footprint & assigned_target_cells for _endpoint_ref, footprint in endpoint_footprints):
        return None
    for source_key, surface in source_surfaces.items():
        if source_key in collected_source_keys:
            continue
        child_index, source_index = source_key
        source = relation.assignments[child_index][1].sources[source_index]
        if any(footprint & surface for _endpoint_ref, footprint in endpoint_footprints):
            return None
        for dynamic_index, mediator_footprint in enumerate(mediator_footprints):
            overlap = mediator_footprint & surface
            if dynamic_index == child_index and mediator_centers[child_index] == source.center:
                if overlap != surface:
                    return None
            elif overlap:
                return None

    try:
        projected = _same_child_composite_cargo_projected_scene(
            scene,
            hierarchy,
            relation,
            positions=positions,
            colors=colors,
            collected_source_keys=collected_source_keys,
        )
    except ValueError:
        return None
    marker_color = _same_child_composite_cargo_endpoint_marker_color(hierarchy)
    if marker_color is None:
        return None
    visible_endpoints = _same_child_composite_cargo_visible_endpoints(
        projected,
        marker_color=marker_color,
    )
    observed_endpoint_signatures = _endpoint_state_signature(visible_endpoints)
    expected_endpoint_signatures = _endpoint_state_signature(
        tuple(endpoint for child in hierarchy.children for endpoint in child.endpoints),
        positions=positions,
        colors=colors,
    )
    if any(
        signature not in expected_endpoint_signatures for signature in observed_endpoint_signatures
    ):
        return None
    active = tuple(
        endpoint for endpoint in visible_endpoints if endpoint.color == hierarchy.active_color
    )
    if len(active) > 1:
        return None
    delivered_child_indexes = _same_child_composite_cargo_delivered_child_indexes(
        hierarchy,
        relation,
        positions=positions,
        collected_source_keys=collected_source_keys,
    )
    assigned_targets_match = all(
        projected.cells[y][x]
        == (child.mediator.color if child_index in delivered_child_indexes else scene.cells[y][x])
        for child_index, (child, example) in enumerate(relation.assignments)
        for x, y in example.target.cells
    )
    if not assigned_targets_match or any(
        projected.cells[y][x] != scene.cells[y][x] for x, y in hierarchy.target.cells
    ):
        return None
    return projected


def _same_child_composite_cargo_projected_state_is_safe(
    scene: VisualScene,
    hierarchy: _AffineHierarchy,
    relation: _CompositeBridgeRelation,
    *,
    positions: dict[str, tuple[int, int]],
    colors: dict[str, int],
    collected_source_keys: frozenset[_CompositeCargoSourceKey],
    static_cells: frozenset[tuple[int, int]],
    search_budget: _HierarchySearchBudget,
    state_cache: dict[_SameChildCompositeCargoProjectedStateKey, VisualScene | None],
) -> VisualScene | None:
    """Return one cached exact projection while preserving the search charge."""

    search_budget.consume()
    key: _SameChildCompositeCargoProjectedStateKey = (
        tuple(sorted(positions.items())),
        tuple(sorted(colors.items())),
        tuple(sorted(collected_source_keys)),
    )
    if key not in state_cache:
        state_cache[key] = _same_child_composite_cargo_projected_state_is_safe_uncached(
            scene,
            hierarchy,
            relation,
            positions=positions,
            colors=colors,
            collected_source_keys=collected_source_keys,
            static_cells=static_cells,
        )
    return state_cache[key]


def _same_child_composite_cargo_support_variants(
    example: _CompositeBridgeExample,
    *,
    source_order: tuple[int, ...],
) -> tuple[tuple[tuple[int, int], ...], ...]:
    """Return the direct route and two bounded, geometry-derived detours.

    The detours are not board-specific coordinates.  They offset the midpoint
    of the final-source-to-target segment along its normalized perpendicular.
    The clearance is four witnessed source radii, which is large enough to move
    the carried composite disk around one equally scaled foreground object while
    remaining tied to the observed cargo geometry.
    """

    sources = tuple(example.sources[index].center for index in source_order)
    target = example.target.rounded_center
    direct = (*sources, target)
    final_source = sources[-1]
    delta_x = target[0] - final_source[0]
    delta_y = target[1] - final_source[1]
    scale = max(abs(delta_x), abs(delta_y))
    source = example.sources[source_order[-1]]
    source_radius = max(
        (max(abs(x - source.center[0]), abs(y - source.center[1])) for x, y in source.cells),
        default=0,
    )
    if scale == 0 or source_radius == 0:
        return (direct,)

    clearance = 4 * source_radius

    def rounded_scaled(value: int) -> int:
        quotient, remainder = divmod(abs(value) * clearance, scale)
        magnitude = quotient + int(2 * remainder >= scale)
        return magnitude if value >= 0 else -magnitude

    midpoint = (
        (final_source[0] + target[0]) // 2,
        (final_source[1] + target[1]) // 2,
    )
    perpendicular = (rounded_scaled(delta_y), rounded_scaled(-delta_x))
    waypoint_candidates = {
        (midpoint[0] + sign * perpendicular[0], midpoint[1] + sign * perpendicular[1])
        for sign in (-1, 1)
    }
    waypoint_candidates -= {final_source, target, *sources}
    ordered_waypoints = tuple(
        sorted(
            waypoint_candidates,
            key=lambda waypoint: (
                _distance(final_source, waypoint) + _distance(waypoint, target),
                waypoint,
            ),
        )
    )
    return (direct, *(tuple((*sources, waypoint, target)) for waypoint in ordered_waypoints))


def _same_child_composite_cargo_route_key(
    route: tuple[_HierarchyChildLayout, ...],
) -> tuple[tuple[tuple[int, int], tuple[tuple[str, tuple[int, int]], ...]], ...]:
    """Return the complete exact identity of one finite layout route."""

    return tuple(
        (
            layout.support,
            tuple(
                (endpoint.object_ref, point)
                for endpoint, point in zip(layout.movers, layout.points, strict=True)
            ),
        )
        for layout in route
    )


def _same_child_composite_cargo_reoriented_layout_patterns(
    scene: VisualScene,
    hierarchy: _AffineHierarchy,
    relation: _CompositeBridgeRelation,
    *,
    child_index: int,
    source_order: tuple[int, ...],
    static_cells: frozenset[tuple[int, int]],
    search_budget: _HierarchySearchBudget,
) -> tuple[tuple[_HierarchyChildLayout, ...], ...]:
    """Find bounded routes whose formation may change between exact supports.

    Three or more sequential movers can be unable to translate one fixed
    formation onto a nearby source without an intermediate endpoint collision
    or premature mediator overlap.  Each stage therefore draws from the same
    finite observation-derived radius/rotation family used by the base affine
    planner, while every complete route still undergoes exact action-by-action
    raster preflight before it can be selected.
    """

    child, example = relation.assignments[child_index]
    if set(source_order) != set(range(len(example.sources))):
        return ()
    supports = (
        *(example.sources[source_index].center for source_index in source_order),
        example.target.rounded_center,
    )
    all_source_cells = frozenset(
        cell
        for _assigned_child, assigned_example in relation.assignments
        for source in assigned_example.sources
        for cell in source.cells
    )
    layout_sets: list[tuple[_HierarchyChildLayout, ...]] = []
    for support in supports:
        raw_layouts = _hierarchy_child_layouts(
            scene,
            hierarchy,
            child,
            support=support,
            active_ref=None,
            static_cells=static_cells,
            target_regions=(),
            endpoint_target_regions=(),
            ignored_refs=frozenset(),
            search_budget=search_budget,
            result_limit=512,
        )
        source_at_support = next(
            (
                example.sources[source_index]
                for source_index in source_order
                if example.sources[source_index].center == support
            ),
            None,
        )
        expected_source_surface = (
            frozenset(source_at_support.cells) if source_at_support is not None else frozenset()
        )
        valid_layouts: list[_HierarchyChildLayout] = []
        for layout in raw_layouts:
            endpoint_footprints = tuple(
                _translated_object_footprint(endpoint, center=point)
                for endpoint, point in zip(layout.movers, layout.points, strict=True)
            )
            if (
                any(footprint & all_source_cells for footprint in endpoint_footprints)
                or layout.dynamic_footprint & all_source_cells != expected_source_surface
            ):
                continue
            valid_layouts.append(layout)
            if len(valid_layouts) == 32:
                break
        if not valid_layouts:
            return ()
        layout_sets.append(tuple(valid_layouts))

    routes: dict[
        tuple[tuple[tuple[int, int], tuple[tuple[str, tuple[int, int]], ...]], ...],
        tuple[_HierarchyChildLayout, ...],
    ] = {}
    for layout_indexes in _fair_index_products(
        tuple(len(layouts) for layouts in layout_sets),
        limit=64,
    ):
        route = tuple(
            layout_sets[index][layout_index] for index, layout_index in enumerate(layout_indexes)
        )
        routes.setdefault(_same_child_composite_cargo_route_key(route), route)
        if len(routes) == _MAX_SAME_CHILD_COMPOSITE_CARGO_REORIENTED_PATTERNS:
            break
    return tuple(routes.values())


def _same_child_composite_cargo_layout_patterns(
    scene: VisualScene,
    hierarchy: _AffineHierarchy,
    relation: _CompositeBridgeRelation,
    *,
    child_index: int,
    source_order: tuple[int, ...],
    static_cells: frozenset[tuple[int, int]],
    search_budget: _HierarchySearchBudget,
) -> tuple[tuple[_HierarchyChildLayout, ...], ...]:
    """Find bounded translation-compatible direct and perpendicular routes."""

    child, example = relation.assignments[child_index]
    if set(source_order) != set(range(len(example.sources))):
        return ()
    if child.arity >= 3 and len(example.sources) >= 3:
        return _same_child_composite_cargo_reoriented_layout_patterns(
            scene,
            hierarchy,
            relation,
            child_index=child_index,
            source_order=source_order,
            static_cells=static_cells,
            search_budget=search_budget,
        )
    support_variants = _same_child_composite_cargo_support_variants(
        example,
        source_order=source_order,
    )
    all_source_cells = frozenset(
        cell
        for _assigned_child, assigned_example in relation.assignments
        for source in assigned_example.sources
        for cell in source.cells
    )
    ordered_endpoints = tuple(sorted(child.endpoints, key=lambda item: item.object_ref))
    patterns: list[tuple[_HierarchyChildLayout, ...]] = []
    for supports in support_variants:
        support_patterns: dict[
            tuple[tuple[tuple[int, int], tuple[tuple[str, tuple[int, int]], ...]], ...],
            tuple[_HierarchyChildLayout, ...],
        ] = {}
        for radius in range(6, 28):
            shell_patterns: list[tuple[_HierarchyChildLayout, ...]] = []
            for rotation_index in range(64):
                relative_points = _regular_exact_centroid_points(
                    (0, 0),
                    arity=child.arity,
                    radius=radius,
                    rotation_index=rotation_index,
                )
                if relative_points is None:
                    continue
                for point_order in itertools.permutations(relative_points):
                    search_budget.consume()
                    layouts: list[_HierarchyChildLayout] = []
                    prior_positions = {
                        endpoint.object_ref: endpoint.rounded_center for endpoint in child.endpoints
                    }
                    movement_cost = 0.0
                    for stage_index, support in enumerate(supports):
                        points = tuple((support[0] + dx, support[1] + dy) for dx, dy in point_order)
                        if (
                            sum(point[0] for point in points) != child.arity * support[0]
                            or sum(point[1] for point in points) != child.arity * support[1]
                            or any(
                                prior_positions[endpoint.object_ref] == point
                                for endpoint, point in zip(
                                    ordered_endpoints,
                                    points,
                                    strict=True,
                                )
                            )
                        ):
                            layouts = []
                            break
                        endpoint_footprints = tuple(
                            _translated_object_footprint(endpoint, center=point)
                            for endpoint, point in zip(
                                ordered_endpoints,
                                points,
                                strict=True,
                            )
                        )
                        dynamic = _hierarchy_projected_group_footprint(
                            child,
                            endpoint_centers=points,
                            mediator_center=support,
                            endpoints=ordered_endpoints,
                        )
                        mediator_footprint = _translated_object_footprint(
                            child.mediator,
                            center=support,
                        )
                        expected_source_surface = (
                            frozenset(example.sources[source_order[stage_index]].cells)
                            if stage_index < len(source_order)
                            else frozenset()
                        )
                        if (
                            any(
                                not _hierarchy_cells_in_bounds(scene, footprint)
                                or footprint & static_cells
                                or footprint & all_source_cells
                                for footprint in endpoint_footprints
                            )
                            or any(
                                not _footprints_have_gap(left, right, gap=1)
                                for left, right in itertools.combinations(
                                    endpoint_footprints,
                                    2,
                                )
                            )
                            or not _hierarchy_cells_in_bounds(scene, dynamic)
                            or mediator_footprint & static_cells
                            or dynamic & all_source_cells != expected_source_surface
                        ):
                            layouts = []
                            break
                        movement_cost += sum(
                            _distance(prior_positions[endpoint.object_ref], point)
                            for endpoint, point in zip(
                                ordered_endpoints,
                                points,
                                strict=True,
                            )
                        )
                        layouts.append(
                            _HierarchyChildLayout(
                                group=child,
                                support=support,
                                movers=ordered_endpoints,
                                points=points,
                                dynamic_footprint=dynamic,
                                radius=radius,
                                movement_cost=movement_cost,
                            )
                        )
                        prior_positions.update(
                            {
                                endpoint.object_ref: point
                                for endpoint, point in zip(
                                    ordered_endpoints,
                                    points,
                                    strict=True,
                                )
                            }
                        )
                    if len(layouts) == len(supports):
                        shell_patterns.append(tuple(layouts))
            shell_patterns.sort(
                key=lambda route: (
                    route[-1].movement_cost,
                    tuple(layout.points for layout in route),
                    tuple(endpoint.object_ref for endpoint in route[0].movers),
                )
            )
            for route in shell_patterns:
                support_patterns.setdefault(
                    _same_child_composite_cargo_route_key(route),
                    route,
                )
                if len(support_patterns) >= 2:
                    break
            # Preserve two exact, distinct radius/layout alternatives per route
            # family so parser preflight can reject one without broad search.
            if len(support_patterns) >= 2:
                break
        patterns.extend(support_patterns.values())

    unique_patterns: dict[
        tuple[tuple[tuple[int, int], tuple[tuple[str, tuple[int, int]], ...]], ...],
        tuple[_HierarchyChildLayout, ...],
    ] = {}
    for route in patterns:
        unique_patterns.setdefault(_same_child_composite_cargo_route_key(route), route)
    return tuple(unique_patterns.values())[:_MAX_SAME_CHILD_COMPOSITE_CARGO_PATTERNS]


def _same_child_composite_cargo_step_is_compatible(planned: PlannedClick) -> bool:
    """Validate the closed shape of one complementary-source cargo action."""

    certificate = planned.same_child_composite_cargo_certificate
    if certificate is None:
        return False
    source_keys = certificate.source_keys
    required = certificate.required_collected_source_keys
    expected = certificate.expected_collected_source_keys
    newly_collected = set(expected) - set(required)
    child_source_count = sum(key[0] == certificate.child_index for key in source_keys)
    return bool(
        planned.plan_signature.startswith("affine-same-child-composite-cargo:")
        and certificate.relation_key
        and certificate.child_index >= 0
        and certificate.stage_index in range(child_source_count + 1)
        and planned.target_center == certificate.target_center
        and len(source_keys) >= 4
        and 0 <= certificate.endpoint_marker_color <= 15
        and tuple(sorted(set(source_keys))) == source_keys
        and tuple(sorted(set(required))) == required
        and tuple(sorted(set(expected))) == expected
        and set(required) <= set(expected) <= set(source_keys)
        and len(newly_collected) <= 1
        and all(key[0] == certificate.child_index for key in newly_collected)
        and certificate.required_visible_endpoint_count > 0
        and certificate.required_visible_mediator_count >= 0
        and certificate.required_visible_active_endpoint_count in {0, 1}
        and certificate.expected_visible_active_endpoint_count in {0, 1}
        and planned.required_child_protected_raster_hash is not None
        and planned.expected_child_protected_raster_hash is not None
        and planned.expected_visible_endpoint_count is not None
        and planned.expected_visible_mediator_count is not None
        and planned.post_deposit_mediator_access_certificate is None
        and planned.post_access_composite_exit_certificate is None
        and planned.post_access_composite_marker_certificate is None
        and not planned.carrier_source_delivery_step
        and not planned.carrier_source_detachment_step
        and not planned.carrier_source_paired_cargo_step
        and not planned.carrier_source_paired_cargo_restoration_step
        and (
            (
                planned.purpose is VisualActionPurpose.PROBE
                and not newly_collected
                and certificate.required_mediator_center == certificate.expected_mediator_center
            )
            or planned.purpose is VisualActionPurpose.PROGRESS
        )
        and certificate.completes_relation == planned.completes_hierarchy
        and (
            not certificate.completes_relation
            or (
                expected == source_keys
                and certificate.stage_index == child_source_count
                and certificate.support_center == certificate.target_center
            )
        )
    )


def _same_child_composite_cargo_move_order(
    scene: VisualScene,
    hierarchy: _AffineHierarchy,
    relation: _CompositeBridgeRelation,
    *,
    child_index: int,
    destinations: dict[str, tuple[int, int]],
    positions: dict[str, tuple[int, int]],
    colors: dict[str, int],
    collected_source_keys: frozenset[_CompositeCargoSourceKey],
    static_cells: frozenset[tuple[int, int]],
    search_budget: _HierarchySearchBudget,
    state_cache: dict[_SameChildCompositeCargoProjectedStateKey, VisualScene | None],
) -> tuple[str, ...] | None:
    """Choose the first bounded endpoint order whose every returned frame is readable."""

    child, example = relation.assignments[child_index]
    expected_refs = frozenset(endpoint.object_ref for endpoint in child.endpoints)
    if frozenset(destinations) != expected_refs:
        return None
    active_refs = tuple(ref for ref, color in colors.items() if color == hierarchy.active_color)
    if len(active_refs) != 1:
        return None
    active_ref = active_refs[0]
    orders = tuple(
        sorted(
            _hierarchy_endpoint_orders(child, active_ref=None),
            key=lambda order: (
                order[0].object_ref != active_ref,
                tuple(endpoint.object_ref for endpoint in order),
            ),
        )
    )
    for endpoint_order in orders:
        trial_positions = dict(positions)
        trial_colors = dict(colors)
        trial_collected = collected_source_keys
        trial_active_ref = active_ref
        move_refs = tuple(endpoint.object_ref for endpoint in endpoint_order)
        valid = True
        trial_scene = _same_child_composite_cargo_projected_state_is_safe(
            scene,
            hierarchy,
            relation,
            positions=trial_positions,
            colors=trial_colors,
            collected_source_keys=trial_collected,
            static_cells=static_cells,
            search_budget=search_budget,
            state_cache=state_cache,
        )
        if trial_scene is None:
            continue
        for mover_ref in move_refs:
            if mover_ref != trial_active_ref:
                marker_color = _same_child_composite_cargo_endpoint_marker_color(hierarchy)
                if marker_color is None:
                    valid = False
                    break
                selected = tuple(
                    endpoint
                    for endpoint in _same_child_composite_cargo_visible_endpoints(
                        trial_scene,
                        marker_color=marker_color,
                    )
                    if endpoint.rounded_center == trial_positions[mover_ref]
                )
                if len(selected) != 1 or selected[0].color == hierarchy.active_color:
                    valid = False
                    break
                trial_colors[trial_active_ref], trial_colors[mover_ref] = (
                    trial_colors[mover_ref],
                    trial_colors[trial_active_ref],
                )
                trial_active_ref = mover_ref
                trial_scene = _same_child_composite_cargo_projected_state_is_safe(
                    scene,
                    hierarchy,
                    relation,
                    positions=trial_positions,
                    colors=trial_colors,
                    collected_source_keys=trial_collected,
                    static_cells=static_cells,
                    search_budget=search_budget,
                    state_cache=state_cache,
                )
                if trial_scene is None:
                    valid = False
                    break
            destination = destinations[mover_ref]
            if trial_positions[mover_ref] == destination:
                valid = False
                break
            required_mediator_center = _same_child_composite_cargo_mediator_centers(
                hierarchy,
                trial_positions,
            )[child_index]
            trial_positions[mover_ref] = destination
            expected_mediator_center = _same_child_composite_cargo_mediator_centers(
                hierarchy,
                trial_positions,
            )[child_index]
            newly_collected = set(trial_collected)
            for source_index, source in enumerate(example.sources):
                source_key = (child_index, source_index)
                if (
                    source_key not in newly_collected
                    and required_mediator_center == source.center
                    and expected_mediator_center != source.center
                ):
                    newly_collected.add(source_key)
            trial_collected = frozenset(newly_collected)
            trial_scene = _same_child_composite_cargo_projected_state_is_safe(
                scene,
                hierarchy,
                relation,
                positions=trial_positions,
                colors=trial_colors,
                collected_source_keys=trial_collected,
                static_cells=static_cells,
                search_budget=search_budget,
                state_cache=state_cache,
            )
            if trial_scene is None:
                valid = False
                break
        if valid:
            return move_refs
    return None


def _build_same_child_composite_cargo_plan(
    scene: VisualScene,
    hierarchy: _AffineHierarchy,
    relation: _CompositeBridgeRelation,
    *,
    child_order: tuple[int, ...],
    source_orders: tuple[tuple[int, ...], ...],
    layout_routes: tuple[tuple[_HierarchyChildLayout, ...], ...],
    static_cells: frozenset[tuple[int, int]],
    search_budget: _HierarchySearchBudget,
    state_cache: dict[_SameChildCompositeCargoProjectedStateKey, VisualScene | None],
) -> _HierarchyPlan | None:
    """Simulate and certificate one fully specified finite accumulation route."""

    identity = (
        relation.relation_key,
        child_order,
        source_orders,
        tuple(
            tuple(
                (
                    layout.support,
                    tuple(
                        (endpoint.object_ref, point)
                        for endpoint, point in zip(
                            layout.movers,
                            layout.points,
                            strict=True,
                        )
                    ),
                )
                for layout in route
            )
            for route in layout_routes
        ),
    )
    digest = hashlib.sha256(repr(identity).encode("ascii")).hexdigest()[:24]
    signature = f"affine-same-child-composite-cargo:{digest}"
    plan_id = f"visual-same-child-composite-cargo:{digest}"
    source_keys = _same_child_composite_cargo_source_keys(relation)
    positions = {
        endpoint.object_ref: endpoint.rounded_center
        for child in hierarchy.children
        for endpoint in child.endpoints
    }
    colors = {
        endpoint.object_ref: endpoint.color
        for child in hierarchy.children
        for endpoint in child.endpoints
    }
    active_refs = tuple(ref for ref, color in colors.items() if color == hierarchy.active_color)
    if len(active_refs) != 1:
        return None
    active_ref = active_refs[0]
    collected: frozenset[_CompositeCargoSourceKey] = frozenset()
    required_scene = _same_child_composite_cargo_projected_state_is_safe(
        scene,
        hierarchy,
        relation,
        positions=positions,
        colors=colors,
        collected_source_keys=collected,
        static_cells=static_cells,
        search_budget=search_budget,
        state_cache=state_cache,
    )
    if required_scene is None or required_scene.cells != scene.cells:
        return None
    actions: list[PlannedClick] = []
    total_stage_count = sum(len(route) for route in layout_routes)
    completed_stage_count = 0

    def append_action(
        *,
        child_index: int,
        stage_index: int,
        support_center: tuple[int, int],
        coordinate: tuple[int, int],
        purpose: VisualActionPurpose,
        required_collected: frozenset[_CompositeCargoSourceKey],
        expected_collected: frozenset[_CompositeCargoSourceKey],
        required_mediator_center: tuple[int, int],
        expected_mediator_center: tuple[int, int],
        expected_scene: VisualScene,
        completes_relation: bool,
    ) -> None:
        nonlocal required_scene
        if required_scene is None:
            raise ValueError("same-child composite cargo route lost its required scene")
        current_required_scene = required_scene
        child, example = relation.assignments[child_index]
        endpoint_marker_color = _same_child_composite_cargo_endpoint_marker_color(hierarchy)
        if endpoint_marker_color is None:
            raise ValueError("same-child composite cargo endpoint marker is ambiguous")
        required_visible_endpoints = _same_child_composite_cargo_visible_endpoints(
            current_required_scene,
            marker_color=endpoint_marker_color,
        )
        expected_visible_endpoints = _same_child_composite_cargo_visible_endpoints(
            expected_scene,
            marker_color=endpoint_marker_color,
        )
        certificate = _SameChildCompositeCargoCertificate(
            relation_key=relation.relation_key,
            child_index=child_index,
            stage_index=stage_index,
            support_center=support_center,
            target_center=example.target.rounded_center,
            source_keys=source_keys,
            endpoint_marker_color=endpoint_marker_color,
            required_collected_source_keys=tuple(sorted(required_collected)),
            expected_collected_source_keys=tuple(sorted(expected_collected)),
            required_mediator_center=required_mediator_center,
            expected_mediator_center=expected_mediator_center,
            required_visible_endpoint_count=len(required_visible_endpoints),
            required_visible_mediator_count=len(current_required_scene.mediators),
            required_visible_active_endpoint_count=sum(
                endpoint.color == hierarchy.active_color for endpoint in required_visible_endpoints
            ),
            expected_visible_active_endpoint_count=sum(
                endpoint.color == hierarchy.active_color for endpoint in expected_visible_endpoints
            ),
            completes_relation=completes_relation,
        )
        planned = PlannedClick(
            coordinate=Coordinate(*coordinate),
            purpose=purpose,
            expectation=(
                "test the exact same-child complementary-source composite at its assigned ring"
                if completes_relation
                else (
                    "exchange the active role while preserving exact complementary-source cargo"
                    if purpose is VisualActionPurpose.PROBE
                    else "move one endpoint along an exact complementary-source cargo route"
                )
            ),
            mechanic_ref=hierarchy.mechanic_ref,
            plan_id=plan_id,
            plan_signature=signature,
            target_center=example.target.rounded_center,
            mediator_color=child.mediator.color,
            arity=child.arity,
            completes_hierarchy=completes_relation,
            expected_active_center=coordinate,
            required_child_protected_raster_hash=(
                _child_isolation_protected_raster_hash(current_required_scene)
            ),
            expected_child_protected_raster_hash=(
                _child_isolation_protected_raster_hash(expected_scene)
            ),
            expected_visible_endpoint_count=len(expected_scene.endpoints),
            expected_visible_mediator_count=len(expected_scene.mediators),
            same_child_composite_cargo_certificate=certificate,
        )
        if not _same_child_composite_cargo_step_is_compatible(planned):
            raise ValueError("same-child composite cargo action certificate is malformed")
        actions.append(planned)
        required_scene = expected_scene

    for child_index in child_order:
        _child, example = relation.assignments[child_index]
        route = layout_routes[child_index]
        source_order = source_orders[child_index]
        for route_stage_index, layout in enumerate(route):
            stage_index = min(route_stage_index, len(source_order))
            completed_stage_count += 1
            destinations = {
                endpoint.object_ref: point
                for endpoint, point in zip(layout.movers, layout.points, strict=True)
            }
            move_refs = _same_child_composite_cargo_move_order(
                scene,
                hierarchy,
                relation,
                child_index=child_index,
                destinations=destinations,
                positions=positions,
                colors=colors,
                collected_source_keys=collected,
                static_cells=static_cells,
                search_budget=search_budget,
                state_cache=state_cache,
            )
            if move_refs is None:
                return None
            for mover_ref in move_refs:
                required_mediator_center = _same_child_composite_cargo_mediator_centers(
                    hierarchy,
                    positions,
                )[child_index]
                if mover_ref != active_ref:
                    selected_at = positions[mover_ref]
                    colors[active_ref], colors[mover_ref] = colors[mover_ref], colors[active_ref]
                    active_ref = mover_ref
                    expected_scene = _same_child_composite_cargo_projected_state_is_safe(
                        scene,
                        hierarchy,
                        relation,
                        positions=positions,
                        colors=colors,
                        collected_source_keys=collected,
                        static_cells=static_cells,
                        search_budget=search_budget,
                        state_cache=state_cache,
                    )
                    if expected_scene is None:
                        return None
                    append_action(
                        child_index=child_index,
                        stage_index=stage_index,
                        support_center=layout.support,
                        coordinate=selected_at,
                        purpose=VisualActionPurpose.PROBE,
                        required_collected=collected,
                        expected_collected=collected,
                        required_mediator_center=required_mediator_center,
                        expected_mediator_center=required_mediator_center,
                        expected_scene=expected_scene,
                        completes_relation=False,
                    )
                destination = destinations[mover_ref]
                if positions[mover_ref] == destination:
                    return None
                required_mediator_center = _same_child_composite_cargo_mediator_centers(
                    hierarchy,
                    positions,
                )[child_index]
                positions[mover_ref] = destination
                expected_mediator_center = _same_child_composite_cargo_mediator_centers(
                    hierarchy,
                    positions,
                )[child_index]
                newly_collected = set(collected)
                for source_index, source in enumerate(example.sources):
                    source_key = (child_index, source_index)
                    if (
                        source_key not in newly_collected
                        and required_mediator_center == source.center
                        and expected_mediator_center != source.center
                    ):
                        newly_collected.add(source_key)
                expected_collected = frozenset(newly_collected)
                expected_scene = _same_child_composite_cargo_projected_state_is_safe(
                    scene,
                    hierarchy,
                    relation,
                    positions=positions,
                    colors=colors,
                    collected_source_keys=expected_collected,
                    static_cells=static_cells,
                    search_budget=search_budget,
                    state_cache=state_cache,
                )
                if expected_scene is None:
                    return None
                final_action = bool(
                    completed_stage_count == total_stage_count and mover_ref == move_refs[-1]
                )
                append_action(
                    child_index=child_index,
                    stage_index=stage_index,
                    support_center=layout.support,
                    coordinate=destination,
                    purpose=VisualActionPurpose.PROGRESS,
                    required_collected=collected,
                    expected_collected=expected_collected,
                    required_mediator_center=required_mediator_center,
                    expected_mediator_center=expected_mediator_center,
                    expected_scene=expected_scene,
                    completes_relation=final_action,
                )
                collected = expected_collected
            if (
                _same_child_composite_cargo_mediator_centers(hierarchy, positions)[child_index]
                != layout.support
            ):
                return None
            if (
                stage_index < len(source_order)
                and (child_index, source_order[stage_index]) in collected
            ):
                return None
        if not all((child_index, source_index) in collected for source_index in source_order):
            return None
    if (
        tuple(sorted(collected)) != source_keys
        or not actions
        or not actions[-1].completes_hierarchy
    ):
        return None
    return _HierarchyPlan(
        actions=tuple(actions),
        signature=signature,
        supports=tuple(
            relation.assignments[index][1].target.rounded_center
            for index in range(len(relation.assignments))
        ),
        support_weights=tuple(1 for _assignment in relation.assignments),
        recovery_actions=(),
    )


def _same_child_composite_cargo_plan(
    scene: VisualScene,
    hierarchy: _AffineHierarchy,
    relation: _CompositeBridgeRelation,
    *,
    rejected_signatures: set[str],
    search_budget: _HierarchySearchBudget | None = None,
) -> _HierarchyPlan | None:
    """Find one bounded route that accumulates every witnessed source per child."""

    if not _same_child_composite_cargo_relation_is_well_formed(scene, hierarchy, relation):
        return None
    if search_budget is None:
        search_budget = _HierarchySearchBudget(_MAX_HIERARCHY_SEARCH_BUDGET)
    active = tuple(
        endpoint
        for child in hierarchy.children
        for endpoint in child.endpoints
        if endpoint.color == hierarchy.active_color
    )
    if len(active) != 1:
        return None
    initial_dynamic = frozenset(
        cell for child in hierarchy.children for cell in _hierarchy_dynamic_footprint(scene, child)
    )
    source_cells = frozenset(
        cell
        for _child, example in relation.assignments
        for source in example.sources
        for cell in source.cells
    )
    assigned_target_cells = frozenset(
        cell for _child, example in relation.assignments for cell in example.target.cells
    )
    occupied = frozenset(
        (x, y)
        for y, row in enumerate(scene.cells)
        for x, value in enumerate(row)
        if value != scene.background
    )
    # Assigned source disks and assigned target rings are the only witnessed
    # consumable/overwritable surfaces.  The exact projection below still
    # requires every target-ring cell to retain its observed value, so removing
    # those cells from the coarse collision mask does not weaken preservation.
    static_cells = occupied - initial_dynamic - source_cells - assigned_target_cells
    child_count = len(relation.assignments)
    child_orders = tuple(itertools.permutations(range(child_count)))
    per_child_source_orders = tuple(
        (((0, 1), (1, 0)) if len(example.sources) == 2 else (tuple(range(len(example.sources))),))
        for _child, example in relation.assignments
    )
    source_order_options = tuple(itertools.product(*per_child_source_orders))
    route_specs = tuple(
        itertools.islice(
            itertools.product(child_orders, source_order_options),
            _MAX_SAME_CHILD_COMPOSITE_CARGO_ROUTES,
        )
    )
    pattern_cache: dict[
        tuple[int, tuple[int, ...]],
        tuple[tuple[_HierarchyChildLayout, ...], ...],
    ] = {}
    state_cache: dict[_SameChildCompositeCargoProjectedStateKey, VisualScene | None] = {}
    for child_order, source_orders in route_specs:
        pattern_sets: list[tuple[tuple[_HierarchyChildLayout, ...], ...]] = []
        for child_index, source_order in enumerate(source_orders):
            cache_key = (child_index, source_order)
            patterns = pattern_cache.get(cache_key)
            if patterns is None:
                patterns = _same_child_composite_cargo_layout_patterns(
                    scene,
                    hierarchy,
                    relation,
                    child_index=child_index,
                    source_order=source_order,
                    static_cells=static_cells,
                    search_budget=search_budget,
                )
                pattern_cache[cache_key] = patterns
            if not patterns:
                pattern_sets = []
                break
            pattern_sets.append(patterns)
        if not pattern_sets:
            continue
        lengths = tuple(len(patterns) for patterns in pattern_sets)
        for pattern_indexes in _fair_index_products(
            lengths,
            limit=min(math.prod(lengths), _MAX_HIERARCHY_LAYOUT_COMBINATIONS),
        ):
            layout_routes = tuple(
                pattern_sets[index][pattern_index]
                for index, pattern_index in enumerate(pattern_indexes)
            )
            plan = _build_same_child_composite_cargo_plan(
                scene,
                hierarchy,
                relation,
                child_order=child_order,
                source_orders=source_orders,
                layout_routes=layout_routes,
                static_cells=static_cells,
                search_budget=search_budget,
                state_cache=state_cache,
            )
            if plan is not None and plan.signature not in rejected_signatures:
                return plan
    return None


def _bridge_hierarchy_plan(
    scene: VisualScene,
    hierarchy: _AffineHierarchy,
    relation: _CompositeBridgeRelation,
    *,
    rejected_signatures: set[str],
    search_budget: _HierarchySearchBudget | None = None,
) -> _HierarchyPlan | None:
    """Find one exact route for the provisional paired-sink hypothesis."""

    return _target_support_hierarchy_plan(
        scene,
        hierarchy,
        _bridge_target_supports(relation),
        bridge_relation=relation,
        rejected_signatures=rejected_signatures,
        signature_prefix="affine-bridge-hierarchy",
        terminal_expectation="test the proximity-assigned paired composite-sink hypothesis",
        search_budget=search_budget,
    )


def _residual_linked_hierarchy_plan(
    scene: VisualScene,
    hierarchy: _AffineHierarchy,
    relation: _ResidualLinkedHierarchyRelation,
    *,
    rejected_signatures: set[str],
    search_budget: _HierarchySearchBudget | None = None,
) -> _HierarchyPlan | None:
    """Find one exact route for the residual-linked mixed-support hypothesis."""

    return _target_support_hierarchy_plan(
        scene,
        hierarchy,
        relation.supports,
        bridge_relation=None,
        rejected_signatures=rejected_signatures,
        signature_prefix="affine-residual-linked-hierarchy",
        terminal_expectation="test the residual-linked mixed-support hypothesis",
        search_budget=search_budget,
    )


def _external_residual_linked_hierarchy_plan(
    scene: VisualScene,
    hierarchy: _AffineHierarchy,
    relation: _ExternalResidualLinkedHierarchyRelation,
    *,
    rejected_signatures: set[str],
    search_budget: _HierarchySearchBudget | None = None,
) -> _HierarchyPlan | None:
    """Find one exact route for the external residual-chain hypothesis."""

    return _target_support_hierarchy_plan(
        scene,
        hierarchy,
        relation.supports,
        bridge_relation=None,
        rejected_signatures=rejected_signatures,
        signature_prefix="affine-external-residual-linked-hierarchy",
        terminal_expectation="test the unique external residual-chain support hypothesis",
        search_budget=search_budget,
    )


def _raw_matching_composite_hierarchy_plan(
    scene: VisualScene,
    hierarchy: _AffineHierarchy,
    relation: _RawMatchingCompositeHierarchyRelation,
    *,
    rejected_signatures: set[str],
    search_budget: _HierarchySearchBudget | None = None,
) -> _HierarchyPlan | None:
    """Find one exact route for the raw-matching containing-sink hypothesis."""

    return _target_support_hierarchy_plan(
        scene,
        hierarchy,
        relation.supports,
        bridge_relation=None,
        rejected_signatures=rejected_signatures,
        signature_prefix="affine-raw-matching-composite-hierarchy",
        terminal_expectation="test the raw-matching containing-composite support hypothesis",
        search_budget=search_budget,
    )


def _external_own_composite_hierarchy_plan(
    scene: VisualScene,
    hierarchy: _AffineHierarchy,
    relation: _ExternalOwnCompositeHierarchyRelation,
    *,
    rejected_signatures: set[str],
    search_budget: _HierarchySearchBudget | None = None,
) -> _HierarchyPlan | None:
    """Find one exact route for the external-own-composite hypothesis."""

    return _target_support_hierarchy_plan(
        scene,
        hierarchy,
        relation.supports,
        bridge_relation=None,
        rejected_signatures=rejected_signatures,
        signature_prefix="affine-external-own-composite-hierarchy",
        terminal_expectation=(
            "test the unique external-counterpart and own-composite support hypothesis"
        ),
        search_budget=search_budget,
    )


def _carrier_source_occlusion_hierarchy_plan(
    scene: VisualScene,
    hierarchy: _AffineHierarchy,
    relation: _CarrierSourceOcclusionHierarchyRelation,
    *,
    level_index: int,
    rejected_signatures: set[str],
    required_replay_plan_signature: str | None = None,
    required_replay_context_key: str | None = None,
    search_budget: _HierarchySearchBudget | None = None,
) -> _HierarchyPlan | None:
    """Find one exact reversible route onto the carrier-matched source disks."""

    if (required_replay_plan_signature is None) != (required_replay_context_key is None):
        return None
    if search_budget is None:
        search_budget = _HierarchySearchBudget(_MAX_HIERARCHY_SEARCH_BUDGET)
    supports = relation.supports
    if tuple(item.child for item in supports) != hierarchy.children:
        return None
    active = tuple(item for item in scene.endpoints if item.color == hierarchy.active_color)
    if len(active) != 1 or active[0] not in hierarchy.children[0].endpoints:
        return None

    initial_dynamic = frozenset(
        cell for child in hierarchy.children for cell in _hierarchy_dynamic_footprint(scene, child)
    )
    assigned_surfaces = tuple(frozenset(item.source.cells) for item in supports)
    assigned_cells = frozenset(cell for surface in assigned_surfaces for cell in surface)
    if (
        len(assigned_cells) != sum(len(surface) for surface in assigned_surfaces)
        or initial_dynamic & assigned_cells
        or any(
            _translated_object_footprint(
                support.child.mediator,
                center=support.source.center,
            )
            != frozenset(support.source.cells)
            for support in supports
        )
    ):
        return None
    occupied = frozenset(
        (x, y)
        for y, row in enumerate(scene.cells)
        for x, value in enumerate(row)
        if value != scene.background
    )
    static_cells = occupied - initial_dynamic - assigned_cells
    target_regions = _visible_target_regions(scene)
    preserved_target_signature = _target_surface_signature(scene)
    ignored_refs = frozenset(
        item.object_ref
        for child in hierarchy.children
        for item in (*child.endpoints, child.mediator)
    )

    layout_sets: list[tuple[_HierarchyChildLayout, ...]] = []
    for child_index, support in enumerate(supports):
        candidates = _hierarchy_child_layouts(
            scene,
            hierarchy,
            support.child,
            support=support.source.center,
            active_ref=active[0].object_ref if child_index == 0 else None,
            static_cells=static_cells,
            target_regions=target_regions,
            endpoint_target_regions=target_regions,
            ignored_refs=ignored_refs,
            search_budget=search_budget,
            result_limit=128,
        )
        own_surface = frozenset(support.source.cells)
        safe_candidates = tuple(
            layout
            for layout in candidates
            if all(
                not (_translated_object_footprint(mover, center=point) & assigned_cells)
                for mover, point in zip(layout.movers, layout.points, strict=True)
            )
            and layout.dynamic_footprint & assigned_cells == own_surface
            and _translated_object_footprint(
                support.child.mediator,
                center=support.source.center,
            )
            == own_surface
        )
        if not safe_candidates:
            return None
        # Retain the standard bounded active-child alternatives, but do not
        # truncate the counterpart alternatives before joint transient
        # certification.  The latter's mover order determines whether its
        # intermediate centroids remain parser-readable around the occluded
        # disk, so an early geometric prefix is not an evidence-based filter.
        layout_sets.append(
            safe_candidates[:_MAX_HIERARCHY_CHILD_LAYOUTS] if child_index == 0 else safe_candidates
        )

    lengths = tuple(len(items) for items in layout_sets)
    combination_limit = min(math.prod(lengths), _MAX_HIERARCHY_LAYOUT_COMBINATIONS)
    state_cache: dict[_BridgeProjectedStateKey, bool] = {}
    index_products: tuple[tuple[int, ...], ...]
    if len(lengths) == 2:
        # Round-robin the complete bounded counterpart set across every
        # retained active-child layout.  This preserves mover-order diversity
        # under the same global 512-combination ceiling.
        index_products = tuple(
            (first_index, counterpart_index)
            for counterpart_index in range(lengths[1])
            for first_index in range(lengths[0])
        )[:combination_limit]
    else:
        index_products = _fair_index_products(lengths, limit=combination_limit)
    for indices in index_products:
        search_budget.consume()
        layouts = tuple(
            layout_sets[index][layout_index] for index, layout_index in enumerate(indices)
        )
        if not _bridge_final_layout_geometry_is_safe(hierarchy, layouts):
            continue
        if not _carrier_source_occlusion_hierarchy_sequence_is_safe(
            scene,
            hierarchy,
            supports,
            layouts,
            static_cells=static_cells,
            target_regions=target_regions,
            preserved_target_signature=preserved_target_signature,
            search_budget=search_budget,
            state_cache=state_cache,
        ):
            continue
        plan = _build_hierarchy_plan(
            hierarchy,
            layouts,
            scene=scene,
            carrier_source_supports=supports,
            carrier_source_level_index=level_index,
            carrier_source_rejected_external_relation_key=relation.external_relation_key,
            signature_prefix="affine-carrier-source-occlusion-hierarchy",
            terminal_expectation=(
                "test the unique carrier-matched source-occlusion support hypothesis"
            ),
        )
        attachment_context = plan.carrier_source_attachment_replay_context
        if required_replay_plan_signature is not None:
            if (
                plan.signature == required_replay_plan_signature
                and attachment_context is not None
                and _carrier_source_attachment_context_key(attachment_context)
                == required_replay_context_key
            ):
                return plan
            continue
        if plan.signature not in rejected_signatures:
            return plan
    return None


def _hierarchy_joint_layout(
    scene: VisualScene,
    hierarchy: _AffineHierarchy,
    *,
    rejected_signatures: set[str],
    search_budget: _HierarchySearchBudget | None = None,
) -> _HierarchyPlan | None:
    """Find one finite, fully joint and sequentially safe hierarchy layout."""

    if search_budget is None:
        search_budget = _HierarchySearchBudget(_MAX_HIERARCHY_SEARCH_BUDGET)
    target_regions = _visible_target_regions(scene)
    initial_dynamic = frozenset(
        cell for child in hierarchy.children for cell in _hierarchy_dynamic_footprint(scene, child)
    )
    occupied = frozenset(
        (x, y)
        for y, row in enumerate(scene.cells)
        for x, value in enumerate(row)
        if value != scene.background
    )
    static_cells = occupied - initial_dynamic
    if not _hierarchy_cells_in_bounds(
        scene, initial_dynamic
    ) or not _hierarchy_avoids_target_regions(initial_dynamic, target_regions):
        return None
    ignored_refs = frozenset(
        item.object_ref
        for child in hierarchy.children
        for item in (*child.endpoints, child.mediator)
    )
    active = tuple(
        item for item in hierarchy.children[0].endpoints if item.color == hierarchy.active_color
    )
    if len(active) != 1:
        return None

    layout_cache: dict[
        tuple[str, tuple[int, int], str | None], tuple[_HierarchyChildLayout, ...]
    ] = {}
    target = hierarchy.target.rounded_center
    child_count = len(hierarchy.children)
    parent_radii = (7, 9, 11, 13, 16, 19, 23, 27)
    parent_candidates = sorted(
        itertools.product(range(len(parent_radii)), range(32)),
        key=lambda item: (item[0] + item[1], item[0], item[1]),
    )
    for radius_index, parent_rotation in parent_candidates:
        search_budget.consume()
        for parent_radius in parent_radii[radius_index : radius_index + 1]:
            raw_supports = _regular_exact_centroid_points(
                target,
                arity=child_count,
                radius=parent_radius,
                rotation_index=parent_rotation,
            )
            if raw_supports is None:
                continue
            support_orders = _fair_support_orders(
                hierarchy,
                raw_supports,
                limit=120,
            )
            for supports in support_orders:
                search_budget.consume()
                choices: list[tuple[_HierarchyChildLayout, ...]] = []
                for index, (group, support) in enumerate(
                    zip(hierarchy.children, supports, strict=True)
                ):
                    mediator_footprint = _translated_object_footprint(
                        group.mediator,
                        center=support,
                    )
                    if (
                        not _hierarchy_cells_in_bounds(scene, mediator_footprint)
                        or mediator_footprint & static_cells
                        or not _hierarchy_avoids_target_regions(
                            mediator_footprint,
                            target_regions,
                        )
                    ):
                        choices = []
                        break
                    active_ref = active[0].object_ref if index == 0 else None
                    cache_key = (group.mediator.object_ref, support, active_ref)
                    candidates = layout_cache.get(cache_key)
                    if candidates is None:
                        candidates = _hierarchy_child_layouts(
                            scene,
                            hierarchy,
                            group,
                            support=support,
                            active_ref=active_ref,
                            static_cells=static_cells,
                            target_regions=target_regions,
                            ignored_refs=ignored_refs,
                            search_budget=search_budget,
                        )
                        layout_cache[cache_key] = candidates
                    if not candidates:
                        choices = []
                        break
                    choices.append(candidates)
                if not choices:
                    continue
                for indices in _fair_index_products(
                    tuple(len(items) for items in choices),
                    limit=_MAX_HIERARCHY_LAYOUT_COMBINATIONS,
                ):
                    search_budget.consume()
                    typed_layouts = tuple(
                        items[index] for items, index in zip(choices, indices, strict=True)
                    )
                    if any(
                        left.dynamic_footprint & right.dynamic_footprint
                        for left, right in itertools.combinations(typed_layouts, 2)
                    ):
                        continue
                    plan = _build_hierarchy_plan(
                        hierarchy,
                        typed_layouts,
                        scene=scene,
                    )
                    if plan.signature in rejected_signatures:
                        continue
                    search_budget.consume(_HIERARCHY_SEQUENCE_EVALUATION_COST)
                    if _hierarchy_sequence_is_safe(
                        scene,
                        hierarchy,
                        typed_layouts,
                        static_cells=static_cells,
                        target_regions=target_regions,
                        search_budget=search_budget,
                    ):
                        return plan
    return None


def _weighted_translation_support_candidates(
    hierarchy: _AffineHierarchy,
    *,
    support_weights: tuple[int, ...] | None = None,
    max_translation: int = 24,
    limit: int = 128,
) -> tuple[tuple[tuple[int, int], ...], ...]:
    """Rank small child translations for one explicit parent weighting."""

    weights = (
        tuple(child.arity for child in hierarchy.children)
        if support_weights is None
        else support_weights
    )
    if (
        len(weights) != 2
        or weights[0] < 1
        or weights[1] < 1
        or weights[0] == weights[1]
        or max_translation < 1
        or limit < 1
    ):
        return ()
    current = tuple(child.mediator.rounded_center for child in hierarchy.children)
    target = hierarchy.target.rounded_center
    total_weight = sum(weights)
    required = (
        total_weight * target[0]
        - sum(weight * support[0] for weight, support in zip(weights, current, strict=True)),
        total_weight * target[1]
        - sum(weight * support[1] for weight, support in zip(weights, current, strict=True)),
    )
    ranked: list[tuple[int, int, tuple[tuple[int, int], ...]]] = []
    seen: set[tuple[tuple[int, int], ...]] = set()
    for first_dx in range(-max_translation, max_translation + 1):
        for first_dy in range(-max_translation, max_translation + 1):
            first_delta = (first_dx, first_dy)
            if first_delta == (0, 0):
                continue
            second_numerator = (
                required[0] - weights[0] * first_dx,
                required[1] - weights[0] * first_dy,
            )
            if second_numerator[0] % weights[1] != 0 or second_numerator[1] % weights[1] != 0:
                continue
            second_delta = (
                second_numerator[0] // weights[1],
                second_numerator[1] // weights[1],
            )
            if (
                second_delta == (0, 0)
                or max(abs(second_delta[0]), abs(second_delta[1])) > max_translation
            ):
                continue
            supports = (
                (current[0][0] + first_dx, current[0][1] + first_dy),
                (
                    current[1][0] + second_delta[0],
                    current[1][1] + second_delta[1],
                ),
            )
            if supports in seen or len(set(supports)) != len(supports):
                continue
            if (
                sum(weight * support[0] for weight, support in zip(weights, supports, strict=True))
                != total_weight * target[0]
                or sum(
                    weight * support[1] for weight, support in zip(weights, supports, strict=True)
                )
                != total_weight * target[1]
            ):
                continue
            seen.add(supports)
            squared_cost = weights[0] * (first_dx**2 + first_dy**2) + weights[1] * (
                second_delta[0] ** 2 + second_delta[1] ** 2
            )
            max_shift = max(
                abs(first_dx),
                abs(first_dy),
                abs(second_delta[0]),
                abs(second_delta[1]),
            )
            ranked.append((squared_cost, max_shift, supports))
    ranked.sort()
    return tuple(item[2] for item in ranked[:limit])


def _translated_hierarchy_child_layouts(
    scene: VisualScene,
    group: _AffineChildGroup,
    *,
    support: tuple[int, int],
    active_ref: str | None,
    static_cells: frozenset[tuple[int, int]],
    target_regions: _TargetRegions,
    search_budget: _HierarchySearchBudget,
) -> tuple[_HierarchyChildLayout, ...]:
    """Preserve one learned child relation while translating its mediator."""

    delta = (
        support[0] - group.mediator.rounded_center[0],
        support[1] - group.mediator.rounded_center[1],
    )
    if delta == (0, 0):
        return ()
    layouts: list[_HierarchyChildLayout] = []
    for movers in _hierarchy_endpoint_orders(group, active_ref=active_ref):
        search_budget.consume()
        points = tuple(
            (mover.rounded_center[0] + delta[0], mover.rounded_center[1] + delta[1])
            for mover in movers
        )
        dynamic = _hierarchy_projected_group_footprint(
            group,
            endpoint_centers=points,
            mediator_center=support,
            endpoints=movers,
        )
        if (
            not _hierarchy_cells_in_bounds(scene, dynamic)
            or dynamic & static_cells
            or not _hierarchy_avoids_target_regions(dynamic, target_regions)
        ):
            continue
        layouts.append(
            _HierarchyChildLayout(
                group=group,
                support=support,
                movers=movers,
                points=points,
                dynamic_footprint=dynamic,
                radius=max(abs(delta[0]), abs(delta[1])),
                movement_cost=sum(
                    _distance(mover.rounded_center, point)
                    for mover, point in zip(movers, points, strict=True)
                ),
            )
        )
    return tuple(layouts)


def _bounded_weighted_move_orders(
    mover_refs: tuple[str, ...],
    *,
    active_ref: str,
    limit: int = _MAX_WEIGHTED_HIERARCHY_MOVE_ORDERS,
) -> tuple[tuple[str, ...], ...]:
    """Stratify a small deterministic order sample across possible first movers."""

    if (
        limit < 1
        or len(mover_refs) < 2
        or len(set(mover_refs)) != len(mover_refs)
        or active_ref not in mover_refs
    ):
        return ()
    others = tuple(ref for ref in mover_refs if ref != active_ref)
    candidates: list[tuple[str, ...]] = []

    def append(first: str, second: str) -> None:
        remainder = tuple(ref for ref in mover_refs if ref not in {first, second})
        candidate = (first, second, *remainder)
        if candidate not in candidates:
            candidates.append(candidate)

    # Prefer moving the currently active endpoint, but cover every possible
    # immediate successor instead of taking a lexicographic permutation prefix.
    for second in others:
        append(active_ref, second)
    # Preserve bounded fallback diversity for layouts that must free another
    # endpoint's destination before the current active endpoint can move.
    for first in others:
        append(first, active_ref)
    if len(others) > 1:
        for index, first in enumerate(others):
            append(first, others[(index + 1) % len(others)])
    return tuple(candidates[:limit])


def _hierarchy_transient_state_gap(
    scene: VisualScene,
    hierarchy: _AffineHierarchy,
    *,
    positions: dict[str, tuple[int, int]],
    colors: dict[str, int],
    static_cells: frozenset[tuple[int, int]],
    target_regions: _TargetRegions,
    search_budget: _HierarchySearchBudget,
) -> int | None:
    """Return the mediator parse gap for one safe exact-lineage transient state."""

    search_budget.consume()
    group_dynamic: list[frozenset[tuple[int, int]]] = []
    mediator_footprints: list[frozenset[tuple[int, int]]] = []
    endpoint_footprints: list[tuple[str, frozenset[tuple[int, int]]]] = []
    for group in hierarchy.children:
        centers = tuple(positions[item.object_ref] for item in group.endpoints)
        mediator_center = (
            sum(center[0] for center in centers) // group.arity,
            sum(center[1] for center in centers) // group.arity,
        )
        dynamic = _hierarchy_projected_group_footprint(
            group,
            endpoint_centers=centers,
            mediator_center=mediator_center,
        )
        if (
            not _hierarchy_cells_in_bounds(scene, dynamic)
            or dynamic & static_cells
            or not _hierarchy_avoids_target_regions(dynamic, target_regions)
        ):
            return None
        group_dynamic.append(dynamic)
        mediator_footprints.append(
            _translated_object_footprint(group.mediator, center=mediator_center)
        )
        endpoint_footprints.extend(
            (endpoint.object_ref, _translated_object_footprint(endpoint, center=center))
            for endpoint, center in zip(group.endpoints, centers, strict=True)
        )
    if any(left & right for left, right in itertools.combinations(group_dynamic, 2)):
        return None
    if any(
        not _footprints_have_gap(left, right, gap=1)
        for left, right in itertools.combinations(mediator_footprints, 2)
    ):
        return None
    if any(
        colors[left_ref] == colors[right_ref] and not _footprints_have_gap(left, right, gap=1)
        for (left_ref, left), (right_ref, right) in itertools.combinations(
            endpoint_footprints,
            2,
        )
    ):
        return None

    projected = _hierarchy_projected_scene(
        scene,
        hierarchy,
        positions=positions,
        colors=colors,
    )
    active_refs = tuple(ref for ref, color in colors.items() if color == hierarchy.active_color)
    active = tuple(
        endpoint for endpoint in projected.endpoints if endpoint.color == hierarchy.active_color
    )
    if not (
        len(active_refs) == len(active) == 1
        and active[0].rounded_center == positions[active_refs[0]]
        and len(projected.endpoints) == len(scene.endpoints)
        and sorted(item.rounded_center for item in projected.endpoints)
        == sorted(positions.values())
        and 1 <= len(projected.mediators) <= len(scene.mediators)
        and set(_visible_target_regions(projected)) == set(target_regions)
    ):
        return None
    return int(len(projected.mediators) != len(scene.mediators))


def _hierarchy_interleaved_sequence_is_certified(
    scene: VisualScene,
    hierarchy: _AffineHierarchy,
    layouts: tuple[_HierarchyChildLayout, ...],
    *,
    move_order: tuple[str, ...],
    static_cells: frozenset[tuple[int, int]],
    target_regions: _TargetRegions,
    search_budget: _HierarchySearchBudget,
    support_weights: tuple[int, ...],
) -> int | None:
    """Preflight a finite weighted plan while retaining endpoint raster identity."""

    if tuple(layout.group for layout in layouts) != hierarchy.children:
        return None
    moves = {
        mover.object_ref: point
        for layout in layouts
        for mover, point in zip(layout.movers, layout.points, strict=True)
    }
    if (
        len(moves) != sum(len(layout.movers) for layout in layouts)
        or len(move_order) != len(moves)
        or set(move_order) != set(moves)
        or any(
            mover.rounded_center == point
            for layout in layouts
            for mover, point in zip(layout.movers, layout.points, strict=True)
        )
    ):
        return None
    positions = {
        endpoint.object_ref: endpoint.rounded_center
        for child in hierarchy.children
        for endpoint in child.endpoints
    }
    colors = {
        endpoint.object_ref: endpoint.color
        for child in hierarchy.children
        for endpoint in child.endpoints
    }
    active = tuple(ref for ref, color in colors.items() if color == hierarchy.active_color)
    if len(active) != 1:
        return None
    active_ref = active[0]
    initial_gap = _hierarchy_transient_state_gap(
        scene,
        hierarchy,
        positions=positions,
        colors=colors,
        static_cells=static_cells,
        target_regions=target_regions,
        search_budget=search_budget,
    )
    if initial_gap is None:
        return None

    transient_gap_states = 0

    for mover_ref in move_order:
        if mover_ref != active_ref:
            if colors[mover_ref] == hierarchy.active_color:
                return None
            colors[active_ref], colors[mover_ref] = colors[mover_ref], colors[active_ref]
            active_ref = mover_ref
            role_gap = _hierarchy_transient_state_gap(
                scene,
                hierarchy,
                positions=positions,
                colors=colors,
                static_cells=static_cells,
                target_regions=target_regions,
                search_budget=search_budget,
            )
            if role_gap is None:
                return None
            transient_gap_states += role_gap
        positions[active_ref] = moves[mover_ref]
        move_gap = _hierarchy_transient_state_gap(
            scene,
            hierarchy,
            positions=positions,
            colors=colors,
            static_cells=static_cells,
            target_regions=target_regions,
            search_budget=search_budget,
        )
        if move_gap is None:
            return None
        transient_gap_states += move_gap

    supports = tuple(layout.support for layout in layouts)
    total_weight = sum(support_weights)
    target = hierarchy.target.rounded_center
    final_state_is_safe = bool(
        len(support_weights) == len(supports)
        and all(weight >= 1 for weight in support_weights)
        and len(set(supports)) == len(supports)
        and sum(
            weight * support[0] for weight, support in zip(support_weights, supports, strict=True)
        )
        == total_weight * target[0]
        and sum(
            weight * support[1] for weight, support in zip(support_weights, supports, strict=True)
        )
        == total_weight * target[1]
        and _hierarchy_projected_state_is_safe(
            scene,
            hierarchy,
            positions=positions,
            colors=colors,
            static_cells=static_cells,
            target_regions=target_regions,
            search_budget=search_budget,
        )
    )
    return transient_gap_states if final_state_is_safe else None


def _hierarchy_weighted_layout(
    scene: VisualScene,
    hierarchy: _AffineHierarchy,
    *,
    rejected_signatures: set[str],
    search_budget: _HierarchySearchBudget | None = None,
    support_weights: tuple[int, ...] | None = None,
    signature_prefix: str = "affine-weighted-hierarchy",
    terminal_expectation: str = ("complete the arity-weighted child-mediator centroid relation"),
) -> _HierarchyPlan | None:
    """Test one explicit weighted parent composition after equal weighting fails."""

    if search_budget is None:
        search_budget = _HierarchySearchBudget(_MAX_HIERARCHY_SEARCH_BUDGET)
    weights = (
        tuple(child.arity for child in hierarchy.children)
        if support_weights is None
        else support_weights
    )
    if len(weights) != 2 or weights[0] == weights[1]:
        return None
    target_regions = _visible_target_regions(scene)
    initial_dynamic = frozenset(
        cell for child in hierarchy.children for cell in _hierarchy_dynamic_footprint(scene, child)
    )
    occupied = frozenset(
        (x, y)
        for y, row in enumerate(scene.cells)
        for x, value in enumerate(row)
        if value != scene.background
    )
    static_cells = occupied - initial_dynamic
    if not _hierarchy_cells_in_bounds(
        scene, initial_dynamic
    ) or not _hierarchy_avoids_target_regions(initial_dynamic, target_regions):
        return None
    active = tuple(
        item
        for child in hierarchy.children
        for item in child.endpoints
        if item.color == hierarchy.active_color
    )
    if len(active) != 1:
        return None

    ignored_refs = frozenset(
        item.object_ref
        for child in hierarchy.children
        for item in (*child.endpoints, child.mediator)
    )
    layout_cache: dict[
        tuple[str, tuple[int, int], str | None], tuple[_HierarchyChildLayout, ...]
    ] = {}
    best_plan: tuple[int, int, float, str, _HierarchyPlan] | None = None
    first_competitive_support_index: int | None = None
    support_candidates = (
        _weighted_translation_support_candidates(hierarchy)
        if support_weights is None
        else _weighted_translation_support_candidates(
            hierarchy,
            support_weights=weights,
        )
    )
    for support_index, supports in enumerate(support_candidates):
        if (
            first_competitive_support_index is not None
            and support_index
            > first_competitive_support_index + _WEIGHTED_HIERARCHY_SUPPORT_LOOKAHEAD
        ):
            break
        search_budget.consume()
        choices: list[tuple[_HierarchyChildLayout, ...]] = []
        for group, support in zip(hierarchy.children, supports, strict=True):
            mediator_footprint = _translated_object_footprint(
                group.mediator,
                center=support,
            )
            if (
                not _hierarchy_cells_in_bounds(scene, mediator_footprint)
                or mediator_footprint & static_cells
                or not _hierarchy_avoids_target_regions(mediator_footprint, target_regions)
            ):
                choices = []
                break
            active_ref = (
                active[0].object_ref
                if any(item.object_ref == active[0].object_ref for item in group.endpoints)
                else None
            )
            cache_key = (group.mediator.object_ref, support, active_ref)
            candidates = layout_cache.get(cache_key)
            if candidates is None:
                candidates = _hierarchy_child_layouts(
                    scene,
                    hierarchy,
                    group,
                    support=support,
                    active_ref=active_ref,
                    static_cells=static_cells,
                    target_regions=target_regions,
                    ignored_refs=ignored_refs,
                    search_budget=search_budget,
                )
                layout_cache[cache_key] = candidates
            if not candidates:
                choices = []
                break
            choices.append(candidates)
        if not choices:
            continue
        support_has_competitive_plan = False
        for indices in _fair_index_products(
            tuple(len(items) for items in choices),
            limit=min(8, _MAX_HIERARCHY_LAYOUT_COMBINATIONS),
        ):
            search_budget.consume()
            typed_layouts = tuple(
                items[index] for items, index in zip(choices, indices, strict=True)
            )
            if any(
                left.dynamic_footprint & right.dynamic_footprint
                for left, right in itertools.combinations(typed_layouts, 2)
            ):
                continue
            mover_refs = tuple(
                mover.object_ref for layout in typed_layouts for mover in layout.movers
            )
            active_ref = active[0].object_ref
            if active_ref not in mover_refs:
                continue
            move_orders = _bounded_weighted_move_orders(
                mover_refs,
                active_ref=active_ref,
            )
            for move_order in move_orders:
                search_budget.consume(_HIERARCHY_TRANSIENT_SEQUENCE_EVALUATION_COST)
                transient_gap_states = _hierarchy_interleaved_sequence_is_certified(
                    scene,
                    hierarchy,
                    typed_layouts,
                    move_order=move_order,
                    static_cells=static_cells,
                    target_regions=target_regions,
                    search_budget=search_budget,
                    support_weights=weights,
                )
                if transient_gap_states is None:
                    continue
                plan = _build_hierarchy_plan(
                    hierarchy,
                    typed_layouts,
                    scene=scene,
                    move_order=move_order,
                    support_weights=weights,
                    signature_prefix=signature_prefix,
                    terminal_expectation=terminal_expectation,
                )
                if plan.signature in rejected_signatures:
                    continue
                score = (
                    transient_gap_states,
                    len(plan.actions),
                    sum(layout.movement_cost for layout in typed_layouts),
                    plan.signature,
                    plan,
                )
                if best_plan is None or score[:4] < best_plan[:4]:
                    best_plan = score
                if transient_gap_states == 0:
                    return plan
                if transient_gap_states <= 2:
                    support_has_competitive_plan = True
                    # The first low-gap order is enough to compare the remaining
                    # bounded layout/support candidates.  A merely safe order
                    # with a larger parser gap must not hide a later sampled
                    # order that preserves more of the readable hierarchy.
                    break
            if support_has_competitive_plan:
                break
        if support_has_competitive_plan:
            if first_competitive_support_index is None:
                first_competitive_support_index = support_index
            if (
                support_index
                >= first_competitive_support_index + _WEIGHTED_HIERARCHY_SUPPORT_LOOKAHEAD
            ):
                break
    return None if best_plan is None else best_plan[4]


def _hierarchy_visible_node_layout(
    scene: VisualScene,
    hierarchy: _AffineHierarchy,
    *,
    rejected_signatures: set[str],
    search_budget: _HierarchySearchBudget | None = None,
) -> _HierarchyPlan | None:
    """Test weighting each child by its endpoints plus its visible mediator."""

    return _hierarchy_weighted_layout(
        scene,
        hierarchy,
        rejected_signatures=rejected_signatures,
        search_budget=search_budget,
        support_weights=tuple(child.arity + 1 for child in hierarchy.children),
        signature_prefix="affine-visible-node-hierarchy",
        terminal_expectation=(
            "complete the visible-node-weighted child-mediator centroid relation"
        ),
    )


def _visual_object_state_signature(
    item: VisualObject,
    *,
    position: tuple[int, int] | None = None,
    color: int | None = None,
) -> _VisualObjectStateSignature:
    return (
        item.rounded_center if position is None else position,
        item.color if color is None else color,
        item.center_cell,
        tuple(sorted((x - item.min_x, y - item.min_y) for x, y in item.cells)),
    )


def _endpoint_state_signature(
    endpoints: tuple[VisualObject, ...],
    *,
    positions: dict[str, tuple[int, int]] | None = None,
    colors: dict[str, int] | None = None,
) -> _EndpointStateSignature:
    """Describe endpoint center, role color, and translation-invariant shape exactly."""

    return tuple(
        sorted(
            _visual_object_state_signature(
                endpoint,
                position=(
                    positions.get(endpoint.object_ref, endpoint.rounded_center)
                    if positions is not None
                    else None
                ),
                color=(
                    colors.get(endpoint.object_ref, endpoint.color) if colors is not None else None
                ),
            )
            for endpoint in endpoints
        )
    )


def _state_signature_footprint(
    signature: _VisualObjectStateSignature,
) -> frozenset[tuple[int, int]] | None:
    """Reconstruct one odd-bounded glyph footprint from its exact state signature."""

    center, _color, _center_cell, relative_cells = signature
    if not relative_cells:
        return None
    max_x = max(x for x, _y in relative_cells)
    max_y = max(y for _x, y in relative_cells)
    if max_x % 2 != 0 or max_y % 2 != 0:
        return None
    min_x = center[0] - (max_x // 2)
    min_y = center[1] - (max_y // 2)
    return frozenset(
        (
            *((min_x + x, min_y + y) for x, y in relative_cells),
            center,
        )
    )


def _child_group_matches_geometry(
    group: _AffineChildGroup,
    *,
    mediator_center: tuple[int, int],
    endpoint_centers: tuple[tuple[int, int], ...],
    mediator_color: int,
) -> bool:
    return bool(
        group.mediator.rounded_center == mediator_center
        and group.mediator.color == mediator_color
        and sorted(item.rounded_center for item in group.endpoints) == sorted(endpoint_centers)
    )


def _child_group_matches_state(
    group: _AffineChildGroup,
    *,
    mediator_signature: _VisualObjectStateSignature,
    endpoint_signature: _EndpointStateSignature,
) -> bool:
    return bool(
        _visual_object_state_signature(group.mediator) == mediator_signature
        and _endpoint_state_signature(group.endpoints) == endpoint_signature
    )


def _child_isolation_target_regions(
    scene: VisualScene,
    hierarchy: _AffineHierarchy,
) -> tuple[_TargetRegions, _TargetRegions]:
    """Protect target boxes from endpoints while allowing a hollow sink interior."""

    endpoint_regions = _visible_target_regions(scene)
    sink_center = hierarchy.target.rounded_center
    sink_surface = frozenset(
        cell
        for target in (
            *(item for item in scene.targets if item.rounded_center == sink_center),
            *(
                item
                for item, _signature in _composite_sparse_targets(scene)
                if item.rounded_center == sink_center
            ),
        )
        for cell in target.cells
    )
    dynamic_regions = tuple(
        (center, sink_surface if center == sink_center else region)
        for center, region in endpoint_regions
    )
    return dynamic_regions, endpoint_regions


def _child_isolation_selected_raster_signature(
    scene: VisualScene,
    projected: VisualScene,
    selected_group: _AffineChildGroup,
    *,
    positions: dict[str, tuple[int, int]],
) -> _RasterStateSignature:
    """Capture the exact selected-child raster over every mutable relation cell."""

    endpoint_centers = tuple(positions[item.object_ref] for item in selected_group.endpoints)
    mediator_center = (
        sum(center[0] for center in endpoint_centers) // selected_group.arity,
        sum(center[1] for center in endpoint_centers) // selected_group.arity,
    )
    mutable_cells = _hierarchy_dynamic_footprint(
        scene,
        selected_group,
    ) | _hierarchy_projected_group_footprint(
        selected_group,
        endpoint_centers=endpoint_centers,
        mediator_center=mediator_center,
    )
    return tuple(sorted((x, y, projected.cells[y][x]) for x, y in mutable_cells))


def _child_isolation_protected_raster_hash(scene: VisualScene) -> str:
    """Hash every board cell except the observation-derived left HUD column."""

    payload = repr(
        (
            scene.width,
            scene.height,
            tuple(tuple(row[1:]) for row in scene.cells),
        )
    ).encode("ascii")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _frame_edge_signatures(frame: GridFrame) -> tuple[tuple[int, ...], ...]:
    """Return the four visible borders without assigning any semantic role."""

    cells = frame.cells
    if not cells or not cells[0]:
        return ()
    width = len(cells[0])
    if any(len(row) != width for row in cells):
        return ()
    return (
        tuple(cells[0]),
        tuple(row[-1] for row in cells),
        tuple(reversed(cells[-1])),
        tuple(row[0] for row in reversed(cells)),
    )


def _edge_excluded_raster_hash(frame: GridFrame, *, edge_index: int) -> str | None:
    """Hash every cell outside one observation-derived resource border."""

    cells = frame.cells
    if (
        edge_index not in range(4)
        or not cells
        or not cells[0]
        or any(len(row) != len(cells[0]) for row in cells)
    ):
        return None
    width = len(cells[0])
    height = len(cells)
    protected = tuple(
        (x, y, value)
        for y, row in enumerate(cells)
        for x, value in enumerate(row)
        if not (
            (edge_index == 0 and y == 0)
            or (edge_index == 1 and x == width - 1)
            or (edge_index == 2 and y == height - 1)
            or (edge_index == 3 and x == 0)
        )
    )
    payload = repr((width, height, edge_index, protected)).encode("ascii")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _advance_edge_resource_progress(
    baseline_edges: tuple[tuple[int, ...], ...],
    candidates: tuple[_EdgeResourceProgress, ...],
    before: GridFrame,
    after: GridFrame,
    *,
    observed_actions: int,
) -> tuple[_EdgeResourceProgress, ...]:
    """Retain only borders that monotonically fill from the reset raster.

    No edge, direction, palette value, capacity, or per-action increment is
    assumed.  A candidate must add at least one baseline-different cell on
    every observed action and may never rewrite or remove an earlier fill.
    """

    before_edges = _frame_edge_signatures(before)
    after_edges = _frame_edge_signatures(after)
    if (
        len(baseline_edges) != 4
        or len(before_edges) != 4
        or len(after_edges) != 4
        or any(
            not baseline or not (len(baseline) == len(before_edge) == len(after_edge))
            for baseline, before_edge, after_edge in zip(
                baseline_edges,
                before_edges,
                after_edges,
                strict=True,
            )
        )
    ):
        return ()

    prior_by_edge = {candidate.edge_index: candidate for candidate in candidates}
    result: list[_EdgeResourceProgress] = []
    for edge_index, (baseline, before_edge, after_edge) in enumerate(
        zip(baseline_edges, before_edges, after_edges, strict=True)
    ):
        prior = prior_by_edge.get(edge_index)
        if observed_actions > 1 and prior is None:
            continue
        before_filled = frozenset(
            index for index, value in enumerate(before_edge) if value != baseline[index]
        )
        after_filled = frozenset(
            index for index, value in enumerate(after_edge) if value != baseline[index]
        )
        filled_index_history: tuple[frozenset[int], ...]
        if prior is None:
            if observed_actions != 1 or before_filled or not after_filled:
                continue
            fill_values = {after_edge[index] for index in after_filled}
            if len(fill_values) != 1:
                continue
            fill_color = next(iter(fill_values))
            filled_index_history = (after_filled,)
        else:
            if (
                prior.observed_actions + 1 != observed_actions
                or len(prior.filled_index_history) != prior.observed_actions
                or prior.filled_index_history[-1] != prior.filled_indexes
                or before_filled != prior.filled_indexes
                or not before_filled < after_filled
                or any(before_edge[index] != prior.fill_color for index in before_filled)
            ):
                continue
            fill_color = prior.fill_color
            filled_index_history = (*prior.filled_index_history, after_filled)
        if any(after_edge[index] != fill_color for index in after_filled):
            continue
        if any(
            before_edge[index] != after_edge[index]
            for index in range(len(baseline))
            if index not in after_filled - before_filled
        ):
            continue
        result.append(
            _EdgeResourceProgress(
                edge_index=edge_index,
                baseline=baseline,
                fill_color=fill_color,
                filled_indexes=after_filled,
                filled_index_history=filled_index_history,
                observed_actions=observed_actions,
            )
        )
    return tuple(result)


def _exhausted_edge_resource_candidate(
    candidates: tuple[_EdgeResourceProgress, ...],
) -> _EdgeResourceProgress | None:
    """Return one uniquely full, repeatedly observed border-fill candidate."""

    exhausted = tuple(
        candidate
        for candidate in candidates
        if candidate.observed_actions >= 3
        and candidate.filled_indexes == frozenset(range(len(candidate.baseline)))
    )
    return exhausted[0] if len(exhausted) == 1 else None


def _matching_edge_resource_lineage(
    candidates: tuple[_EdgeResourceProgress, ...],
    *,
    edge_index: int,
    baseline: tuple[int, ...],
    fill_color: int,
    observed_actions: int,
    exhausted_filled_index_history: tuple[frozenset[int], ...],
) -> _EdgeResourceProgress | None:
    """Require the exact learned prefix, not merely the same border and count."""

    expected_history = exhausted_filled_index_history[:observed_actions]
    if (
        observed_actions <= 0
        or len(exhausted_filled_index_history) < observed_actions
        or len(expected_history) != observed_actions
    ):
        return None

    matches = tuple(
        candidate
        for candidate in candidates
        if candidate.edge_index == edge_index
        and candidate.baseline == baseline
        and candidate.fill_color == fill_color
        and candidate.observed_actions == observed_actions
        and candidate.filled_index_history == expected_history
        and candidate.filled_indexes == expected_history[-1]
    )
    return matches[0] if len(matches) == 1 else None


def _projected_mediator_occluded_endpoint_centers(
    projected: VisualScene,
    hierarchy: _AffineHierarchy,
    selected_group: _AffineChildGroup,
    *,
    positions: dict[str, tuple[int, int]],
    colors: dict[str, int],
) -> tuple[tuple[tuple[int, int], ...], tuple[tuple[int, int], ...]] | None:
    """Certify one passive endpoint hidden only by its recomputed mediator.

    The latent endpoint geometry comes from the unique pre-action hierarchy.
    The projected frame must contain every other endpoint and both mediators
    exactly; no arbitrary parser loss is accepted as occlusion evidence.
    """

    expected_endpoints = tuple(
        (
            endpoint,
            _visual_object_state_signature(
                endpoint,
                position=positions[endpoint.object_ref],
                color=colors[endpoint.object_ref],
            ),
        )
        for child in hierarchy.children
        for endpoint in child.endpoints
    )
    expected_endpoint_signatures = {signature for _endpoint, signature in expected_endpoints}
    observed_endpoint_signatures = {
        _visual_object_state_signature(endpoint) for endpoint in projected.endpoints
    }
    if (
        len(expected_endpoint_signatures) != len(expected_endpoints)
        or len(observed_endpoint_signatures) != len(projected.endpoints)
        or len(projected.endpoints) != len(expected_endpoints) - 1
        or not observed_endpoint_signatures < expected_endpoint_signatures
    ):
        return None
    missing_signatures = expected_endpoint_signatures - observed_endpoint_signatures
    if len(missing_signatures) != 1:
        return None
    missing = next(
        (
            endpoint
            for endpoint, signature in expected_endpoints
            if signature in missing_signatures and endpoint in selected_group.endpoints
        ),
        None,
    )
    if missing is None or colors[missing.object_ref] == hierarchy.active_color:
        return None

    selected_centers = tuple(positions[item.object_ref] for item in selected_group.endpoints)
    selected_mediator_center = (
        sum(center[0] for center in selected_centers) // selected_group.arity,
        sum(center[1] for center in selected_centers) // selected_group.arity,
    )
    expected_mediator_signatures = {
        _visual_object_state_signature(
            child.mediator,
            position=(
                sum(positions[item.object_ref][0] for item in child.endpoints) // child.arity,
                sum(positions[item.object_ref][1] for item in child.endpoints) // child.arity,
            ),
        )
        for child in hierarchy.children
    }
    observed_mediator_signatures = {
        _visual_object_state_signature(mediator) for mediator in projected.mediators
    }
    if (
        len(expected_mediator_signatures) != len(hierarchy.children)
        or observed_mediator_signatures != expected_mediator_signatures
    ):
        return None

    missing_center = positions[missing.object_ref]
    missing_footprint = _translated_object_footprint(missing, center=missing_center)
    mediator_footprint = _translated_object_footprint(
        selected_group.mediator,
        center=selected_mediator_center,
    )
    overlap = missing_footprint & mediator_footprint
    if (
        not overlap
        or missing_center in mediator_footprint
        or colors[missing.object_ref] == selected_group.mediator.color
    ):
        return None
    return ((missing_center,), tuple(sorted(overlap)))


def _child_isolation_projected_state_is_safe(
    scene: VisualScene,
    hierarchy: _AffineHierarchy,
    selected_group: _AffineChildGroup,
    frozen_group: _AffineChildGroup,
    *,
    positions: dict[str, tuple[int, int]],
    colors: dict[str, int],
    static_cells: frozenset[tuple[int, int]],
    dynamic_target_regions: _TargetRegions,
    endpoint_target_regions: _TargetRegions,
    target_signature: _TargetSurfaceSignature,
    search_budget: _HierarchySearchBudget,
) -> _ChildIsolationStateCertificate | None:
    """Preflight and certify one exact selected-child projected state."""

    selected_centers = tuple(positions[item.object_ref] for item in selected_group.endpoints)
    selected_mediator = (
        sum(center[0] for center in selected_centers) // selected_group.arity,
        sum(center[1] for center in selected_centers) // selected_group.arity,
    )
    endpoint_footprints = tuple(
        _translated_object_footprint(endpoint, center=center)
        for endpoint, center in zip(selected_group.endpoints, selected_centers, strict=True)
    )
    if any(
        not _hierarchy_cells_in_bounds(scene, footprint)
        or footprint & static_cells
        or not _hierarchy_avoids_target_regions(footprint, endpoint_target_regions)
        for footprint in endpoint_footprints
    ):
        return None
    if any(
        not _footprints_have_gap(left, right, gap=1)
        for left, right in itertools.combinations(endpoint_footprints, 2)
    ):
        return None
    selected_dynamic = _hierarchy_projected_group_footprint(
        selected_group,
        endpoint_centers=selected_centers,
        mediator_center=selected_mediator,
    )
    if (
        not _hierarchy_cells_in_bounds(scene, selected_dynamic)
        or selected_dynamic & static_cells
        or not _hierarchy_avoids_target_regions(selected_dynamic, dynamic_target_regions)
    ):
        return None

    projected = _hierarchy_projected_scene(
        scene,
        hierarchy,
        positions=positions,
        colors=colors,
    )
    selected_raster_signature = _child_isolation_selected_raster_signature(
        scene,
        projected,
        selected_group,
        positions=positions,
    )
    if _child_isolation_target_surface_signature(
        projected,
        sink_center=hierarchy.target.rounded_center,
    ) != target_signature or set(_visible_target_regions(projected)) != set(
        _visible_target_regions(scene)
    ):
        return None
    parsed = _unique_affine_hierarchy(
        projected,
        active_color=hierarchy.active_color,
        search_budget=search_budget,
    )
    active = tuple(item for item in projected.endpoints if item.color == hierarchy.active_color)
    if len(active) != 1:
        return None
    frozen_endpoint_signature = _endpoint_state_signature(frozen_group.endpoints)
    frozen_matches = tuple(
        child
        for child in (() if parsed is None else parsed.children)
        if _child_group_matches_state(
            child,
            mediator_signature=_visual_object_state_signature(frozen_group.mediator),
            endpoint_signature=frozen_endpoint_signature,
        )
    )
    selected_endpoint_signature = _endpoint_state_signature(
        selected_group.endpoints,
        positions=positions,
        colors=colors,
    )
    selected_matches = tuple(
        child
        for child in (() if parsed is None else parsed.children)
        if child.mediator.rounded_center == selected_mediator
        and child.mediator.color == selected_group.mediator.color
        and _endpoint_state_signature(child.endpoints) == selected_endpoint_signature
        and any(item.color == hierarchy.active_color for item in child.endpoints)
    )
    if (
        len(projected.endpoints) == len(scene.endpoints)
        and len(projected.mediators) == len(scene.mediators)
        and parsed is not None
        and len(parsed.children) == 2
        and len(frozen_matches) == 1
        and len(selected_matches) == 1
        and frozen_matches[0] is not selected_matches[0]
        and parsed.target.rounded_center == hierarchy.target.rounded_center
        and parsed.target.color == hierarchy.target.color
    ):
        return _ChildIsolationStateCertificate(
            selected_mediator_signature=_visual_object_state_signature(
                selected_matches[0].mediator
            ),
            selected_endpoint_signature=selected_endpoint_signature,
            selected_connector_signature=_hierarchy_connector_state_signature(
                projected,
                selected_matches[0],
            ),
            frozen_connector_signature=_hierarchy_connector_state_signature(
                projected,
                frozen_matches[0],
            ),
            active_center=active[0].rounded_center,
            protected_raster_hash=_child_isolation_protected_raster_hash(projected),
            selected_raster_signature=selected_raster_signature,
            occluded_endpoint_centers=(),
            occluded_endpoint_cells=(),
            visible_endpoint_count=len(projected.endpoints),
            visible_mediator_count=len(projected.mediators),
        )

    occlusion = _projected_mediator_occluded_endpoint_centers(
        projected,
        hierarchy,
        selected_group,
        positions=positions,
        colors=colors,
    )
    if not (
        occlusion is not None
        and _visual_object_state_signature(
            selected_group.mediator,
            position=selected_mediator,
        )
        in {_visual_object_state_signature(item) for item in projected.mediators}
    ):
        return None
    frozen_connector_signature = _hierarchy_connector_state_signature(
        projected,
        frozen_group,
    )
    if not (
        frozen_connector_signature == _hierarchy_connector_state_signature(scene, frozen_group)
    ):
        return None
    return _ChildIsolationStateCertificate(
        selected_mediator_signature=_visual_object_state_signature(
            selected_group.mediator,
            position=selected_mediator,
        ),
        selected_endpoint_signature=selected_endpoint_signature,
        selected_connector_signature=None,
        frozen_connector_signature=frozen_connector_signature,
        active_center=active[0].rounded_center,
        protected_raster_hash=_child_isolation_protected_raster_hash(projected),
        selected_raster_signature=selected_raster_signature,
        occluded_endpoint_centers=occlusion[0],
        occluded_endpoint_cells=occlusion[1],
        visible_endpoint_count=len(projected.endpoints),
        visible_mediator_count=len(projected.mediators),
    )


def _child_isolation_sequence_is_safe(
    scene: VisualScene,
    hierarchy: _AffineHierarchy,
    selected_group: _AffineChildGroup,
    frozen_group: _AffineChildGroup,
    layout: _HierarchyChildLayout,
    *,
    static_cells: frozenset[tuple[int, int]],
    dynamic_target_regions: _TargetRegions,
    endpoint_target_regions: _TargetRegions,
    target_signature: _TargetSurfaceSignature,
    search_budget: _HierarchySearchBudget,
) -> tuple[_ChildIsolationStateCertificate, ...] | None:
    """Validate and certify every state in one child-only discriminator."""

    if layout.group != selected_group or any(
        mover.rounded_center == point
        for mover, point in zip(layout.movers, layout.points, strict=True)
    ):
        return None
    positions = {
        endpoint.object_ref: endpoint.rounded_center
        for child in hierarchy.children
        for endpoint in child.endpoints
    }
    colors = {
        endpoint.object_ref: endpoint.color
        for child in hierarchy.children
        for endpoint in child.endpoints
    }
    active = tuple(ref for ref, color in colors.items() if color == hierarchy.active_color)
    if len(active) != 1 or layout.movers[0].object_ref != active[0]:
        return None
    active_ref = active[0]
    certificates: list[_ChildIsolationStateCertificate] = []
    initial_certificate = _child_isolation_projected_state_is_safe(
        scene,
        hierarchy,
        selected_group,
        frozen_group,
        positions=positions,
        colors=colors,
        static_cells=static_cells,
        dynamic_target_regions=dynamic_target_regions,
        endpoint_target_regions=endpoint_target_regions,
        target_signature=target_signature,
        search_budget=search_budget,
    )
    if initial_certificate is None:
        return None
    certificates.append(initial_certificate)
    for mover_index, (mover, point) in enumerate(zip(layout.movers, layout.points, strict=True)):
        if mover.object_ref != active_ref:
            return None
        positions[active_ref] = point
        movement_certificate = _child_isolation_projected_state_is_safe(
            scene,
            hierarchy,
            selected_group,
            frozen_group,
            positions=positions,
            colors=colors,
            static_cells=static_cells,
            dynamic_target_regions=dynamic_target_regions,
            endpoint_target_regions=endpoint_target_regions,
            target_signature=target_signature,
            search_budget=search_budget,
        )
        if movement_certificate is None:
            return None
        if (
            movement_certificate.frozen_connector_signature
            != initial_certificate.frozen_connector_signature
        ):
            return None
        certificates.append(movement_certificate)
        if mover_index + 1 >= len(layout.movers):
            continue
        selected_ref = layout.movers[mover_index + 1].object_ref
        if selected_ref == active_ref or colors[selected_ref] == hierarchy.active_color:
            return None
        colors[active_ref], colors[selected_ref] = colors[selected_ref], colors[active_ref]
        active_ref = selected_ref
        switch_certificate = _child_isolation_projected_state_is_safe(
            scene,
            hierarchy,
            selected_group,
            frozen_group,
            positions=positions,
            colors=colors,
            static_cells=static_cells,
            dynamic_target_regions=dynamic_target_regions,
            endpoint_target_regions=endpoint_target_regions,
            target_signature=target_signature,
            search_budget=search_budget,
        )
        if switch_certificate is None:
            return None
        if (
            switch_certificate.frozen_connector_signature
            != initial_certificate.frozen_connector_signature
        ):
            return None
        certificates.append(switch_certificate)
    centers = tuple(positions[item.object_ref] for item in selected_group.endpoints)
    target = hierarchy.target.rounded_center
    if not (
        not certificates[-1].occluded_endpoint_centers
        and not certificates[-1].occluded_endpoint_cells
        and sum(center[0] for center in centers) == selected_group.arity * target[0]
        and sum(center[1] for center in centers) == selected_group.arity * target[1]
        and layout.support == target
    ):
        return None
    return tuple(certificates)


def _build_child_isolation_plan(
    hierarchy: _AffineHierarchy,
    *,
    activation: VisualObject | None,
    layout: _HierarchyChildLayout,
    state_certificates: tuple[_ChildIsolationStateCertificate, ...],
    restore_certificate: _ChildIsolationRestoreCertificate,
    frozen_group: _AffineChildGroup,
    target_signature: _TargetSurfaceSignature,
    relation_key: str,
    hypothesis_key: str,
) -> _ChildIsolationPlan:
    route = (
        "direct"
        if activation is None
        else f"activate:{activation.rounded_center[0]},{activation.rounded_center[1]}"
    )
    geometry = (
        route
        + "|"
        + ";".join(
            f"{mover.rounded_center[0]},{mover.rounded_center[1]}>{point[0]},{point[1]}"
            for mover, point in zip(layout.movers, layout.points, strict=True)
        )
    )
    signature = (
        "affine-child-isolation:"
        + hashlib.sha256(f"{hypothesis_key}|{geometry}".encode("ascii")).hexdigest()[:24]
    )
    plan_id = "visual-child-isolation-plan:" + signature.rsplit(":", 1)[-1]
    expected_certificate_count = 2 * len(layout.movers)
    if len(state_certificates) != expected_certificate_count:
        raise ValueError("child-isolation action/state certificate count mismatch")
    certificate_index = 0
    initial_certificate = state_certificates[certificate_index]
    certificate_index += 1
    actions: list[PlannedClick] = []
    if activation is not None:
        actions.append(
            PlannedClick(
                coordinate=Coordinate(*activation.rounded_center),
                purpose=VisualActionPurpose.PROBE,
                expectation=(
                    "exchange the active role into the untested affine child while "
                    "preserving the previously tested child"
                ),
                mechanic_ref=hierarchy.mechanic_ref,
                plan_id=plan_id,
                plan_signature=signature,
                target_center=hierarchy.target.rounded_center,
                mediator_color=layout.group.mediator.color,
                arity=layout.group.arity,
                expected_child_mediator_center=(initial_certificate.selected_mediator_signature[0]),
                expected_child_mediator_signature=(initial_certificate.selected_mediator_signature),
                expected_child_endpoint_centers=tuple(
                    item[0] for item in initial_certificate.selected_endpoint_signature
                ),
                expected_child_endpoint_signature=(initial_certificate.selected_endpoint_signature),
                expected_child_connector_signature=(
                    initial_certificate.selected_connector_signature
                ),
                expected_active_center=initial_certificate.active_center,
                expected_child_protected_raster_hash=(initial_certificate.protected_raster_hash),
                expected_child_raster_signature=initial_certificate.selected_raster_signature,
                expected_occluded_endpoint_centers=(initial_certificate.occluded_endpoint_centers),
                expected_occluded_endpoint_cells=(initial_certificate.occluded_endpoint_cells),
                expected_visible_endpoint_count=initial_certificate.visible_endpoint_count,
                expected_visible_mediator_count=initial_certificate.visible_mediator_count,
            )
        )
    for mover_index, (_mover, point) in enumerate(zip(layout.movers, layout.points, strict=True)):
        final_action = mover_index + 1 == len(layout.movers)
        movement_before_certificate = state_certificates[certificate_index - 1]
        movement_certificate = state_certificates[certificate_index]
        certificate_index += 1
        actions.append(
            PlannedClick(
                coordinate=Coordinate(*point),
                purpose=VisualActionPurpose.PROGRESS,
                expectation=(
                    "place only the selected child mediator at the parent target"
                    if final_action
                    else "place the active endpoint on an exact child-isolation layout"
                ),
                mechanic_ref=hierarchy.mechanic_ref,
                plan_id=plan_id,
                plan_signature=signature,
                target_center=hierarchy.target.rounded_center,
                mediator_color=layout.group.mediator.color,
                arity=layout.group.arity,
                completes_child_isolation=final_action,
                expected_child_mediator_center=(
                    movement_certificate.selected_mediator_signature[0]
                ),
                expected_child_mediator_signature=(
                    movement_certificate.selected_mediator_signature
                ),
                expected_child_endpoint_centers=tuple(
                    item[0] for item in movement_certificate.selected_endpoint_signature
                ),
                expected_child_endpoint_signature=(
                    movement_certificate.selected_endpoint_signature
                ),
                expected_child_connector_signature=(
                    movement_certificate.selected_connector_signature
                ),
                expected_active_center=movement_certificate.active_center,
                required_child_protected_raster_hash=(
                    movement_before_certificate.protected_raster_hash
                ),
                expected_child_protected_raster_hash=(movement_certificate.protected_raster_hash),
                required_child_raster_signature=(
                    movement_before_certificate.selected_raster_signature
                ),
                expected_child_raster_signature=(movement_certificate.selected_raster_signature),
                expected_occluded_endpoint_centers=(movement_certificate.occluded_endpoint_centers),
                expected_occluded_endpoint_cells=(movement_certificate.occluded_endpoint_cells),
                expected_visible_endpoint_count=(movement_certificate.visible_endpoint_count),
                expected_visible_mediator_count=(movement_certificate.visible_mediator_count),
            )
        )
        if not final_action:
            selected = layout.movers[mover_index + 1]
            switch_certificate = state_certificates[certificate_index]
            certificate_index += 1
            actions.append(
                PlannedClick(
                    coordinate=Coordinate(*selected.rounded_center),
                    purpose=VisualActionPurpose.PROBE,
                    expectation=(
                        "exchange active and fixed endpoint roles within the isolated child"
                    ),
                    mechanic_ref=hierarchy.mechanic_ref,
                    plan_id=plan_id,
                    plan_signature=signature,
                    target_center=hierarchy.target.rounded_center,
                    mediator_color=layout.group.mediator.color,
                    arity=layout.group.arity,
                    expected_child_mediator_center=(
                        switch_certificate.selected_mediator_signature[0]
                    ),
                    expected_child_mediator_signature=(
                        switch_certificate.selected_mediator_signature
                    ),
                    expected_child_endpoint_centers=tuple(
                        item[0] for item in switch_certificate.selected_endpoint_signature
                    ),
                    expected_child_endpoint_signature=(
                        switch_certificate.selected_endpoint_signature
                    ),
                    expected_child_connector_signature=(
                        switch_certificate.selected_connector_signature
                    ),
                    expected_active_center=switch_certificate.active_center,
                    required_child_protected_raster_hash=(
                        movement_certificate.protected_raster_hash
                    ),
                    expected_child_protected_raster_hash=(switch_certificate.protected_raster_hash),
                    required_child_raster_signature=(
                        movement_certificate.selected_raster_signature
                    ),
                    expected_child_raster_signature=(switch_certificate.selected_raster_signature),
                    expected_occluded_endpoint_centers=(
                        switch_certificate.occluded_endpoint_centers
                    ),
                    expected_occluded_endpoint_cells=(switch_certificate.occluded_endpoint_cells),
                    expected_visible_endpoint_count=(switch_certificate.visible_endpoint_count),
                    expected_visible_mediator_count=(switch_certificate.visible_mediator_count),
                )
            )
    if certificate_index != len(state_certificates):
        raise ValueError("unused child-isolation state certificate")
    forward_actions = tuple(actions)
    recovery_signature = (
        "affine-child-recovery:"
        + hashlib.sha256(f"{signature}:recovery".encode("ascii")).hexdigest()[:24]
    )
    recovery_plan_id = "visual-child-isolation-recovery:" + signature.rsplit(":", 1)[-1]
    recovery_actions: list[PlannedClick] = []
    required_certificate = state_certificates[-1]
    inverse_certificates = (
        state_certificates[:-1] if activation is not None else state_certificates[1:-1]
    )
    for source_action, expected_certificate in zip(
        reversed(forward_actions[:-1]),
        reversed(inverse_certificates),
        strict=True,
    ):
        reverse_purpose = (
            VisualActionPurpose.PROGRESS
            if source_action.purpose is VisualActionPurpose.PROBE
            else VisualActionPurpose.PROBE
        )
        recovery_actions.append(
            PlannedClick(
                coordinate=source_action.coordinate,
                purpose=reverse_purpose,
                expectation=(
                    "restore one endpoint to its exact pre-discriminator position"
                    if reverse_purpose is VisualActionPurpose.PROGRESS
                    else "reverse one certified active-role exchange"
                ),
                mechanic_ref=hierarchy.mechanic_ref,
                plan_id=recovery_plan_id,
                plan_signature=recovery_signature,
                target_center=hierarchy.target.rounded_center,
                mediator_color=layout.group.mediator.color,
                arity=layout.group.arity,
                expected_child_mediator_center=(
                    expected_certificate.selected_mediator_signature[0]
                ),
                expected_child_mediator_signature=(
                    expected_certificate.selected_mediator_signature
                ),
                expected_child_endpoint_centers=tuple(
                    item[0] for item in expected_certificate.selected_endpoint_signature
                ),
                expected_child_endpoint_signature=(
                    expected_certificate.selected_endpoint_signature
                ),
                expected_child_connector_signature=(
                    expected_certificate.selected_connector_signature
                ),
                expected_active_center=expected_certificate.active_center,
                required_child_protected_raster_hash=(required_certificate.protected_raster_hash),
                expected_child_protected_raster_hash=(expected_certificate.protected_raster_hash),
                required_child_raster_signature=(required_certificate.selected_raster_signature),
                expected_child_raster_signature=(expected_certificate.selected_raster_signature),
                expected_occluded_endpoint_centers=(expected_certificate.occluded_endpoint_centers),
                expected_occluded_endpoint_cells=(expected_certificate.occluded_endpoint_cells),
                expected_visible_endpoint_count=(expected_certificate.visible_endpoint_count),
                expected_visible_mediator_count=(expected_certificate.visible_mediator_count),
            )
        )
        required_certificate = expected_certificate
    final_recovery_purpose = (
        VisualActionPurpose.PROBE if activation is not None else VisualActionPurpose.PROGRESS
    )
    recovery_actions.append(
        PlannedClick(
            coordinate=Coordinate(*restore_certificate.active_center),
            purpose=final_recovery_purpose,
            expectation=(
                "restore the exact pre-discriminator active-role binding before testing "
                "a distinct hierarchy hypothesis"
                if activation is not None
                else (
                    "restore the initially active endpoint to its exact pre-discriminator position"
                )
            ),
            mechanic_ref=hierarchy.mechanic_ref,
            plan_id=recovery_plan_id,
            plan_signature=recovery_signature,
            target_center=hierarchy.target.rounded_center,
            mediator_color=layout.group.mediator.color,
            arity=layout.group.arity,
            completes_child_recovery=True,
            expected_active_center=restore_certificate.active_center,
            required_child_protected_raster_hash=(required_certificate.protected_raster_hash),
            expected_child_protected_raster_hash=(restore_certificate.protected_raster_hash),
            required_child_raster_signature=(required_certificate.selected_raster_signature),
            expected_child_raster_signature=(restore_certificate.relation_raster_signature),
            expected_visible_endpoint_count=restore_certificate.visible_endpoint_count,
            expected_visible_mediator_count=restore_certificate.visible_mediator_count,
        )
    )
    return _ChildIsolationPlan(
        actions=forward_actions,
        signature=signature,
        relation_key=relation_key,
        hypothesis_key=hypothesis_key,
        frozen_mediator_center=frozen_group.mediator.rounded_center,
        frozen_mediator_signature=_visual_object_state_signature(frozen_group.mediator),
        frozen_endpoint_centers=tuple(
            sorted(item.rounded_center for item in frozen_group.endpoints)
        ),
        frozen_endpoint_signature=_endpoint_state_signature(frozen_group.endpoints),
        frozen_connector_signature=initial_certificate.frozen_connector_signature,
        frozen_mediator_color=frozen_group.mediator.color,
        target_signature=target_signature,
        recovery_actions=tuple(recovery_actions),
    )


def _child_isolation_plan(
    scene: VisualScene,
    hierarchy: _AffineHierarchy,
    *,
    level_index: int,
    rejected_signatures: set[str],
    rejected_hypothesis_keys: set[str] | frozenset[str] = frozenset(),
    search_budget: _HierarchySearchBudget | None = None,
) -> _ChildIsolationPlan | None:
    """Find one exact test of an unfalsified structural child stratum alone."""

    if len(hierarchy.children) != 2:
        return None
    if search_budget is None:
        search_budget = _HierarchySearchBudget(_MAX_HIERARCHY_SEARCH_BUDGET)
    active = tuple(item for item in scene.endpoints if item.color == hierarchy.active_color)
    if len(active) != 1:
        return None
    restore_cells = frozenset(
        cell for child in hierarchy.children for cell in _hierarchy_dynamic_footprint(scene, child)
    )
    restore_certificate = _ChildIsolationRestoreCertificate(
        protected_raster_hash=_child_isolation_protected_raster_hash(scene),
        relation_raster_signature=tuple(
            sorted((x, y, scene.cells[y][x]) for x, y in restore_cells)
        ),
        visible_endpoint_count=len(scene.endpoints),
        visible_mediator_count=len(scene.mediators),
        active_center=active[0].rounded_center,
    )
    active_groups = tuple(child for child in hierarchy.children if active[0] in child.endpoints)
    if len(active_groups) != 1:
        return None
    active_group = active_groups[0]
    relation_key = _hierarchy_relation_key(scene, hierarchy, level_index=level_index)
    # Structurally identical children share one hypothesis.  Prefer an active
    # representative so an equivalent stratum never pays an unnecessary role
    # exchange merely because parser ordering changed.
    groups_by_hypothesis: dict[str, _AffineChildGroup] = {}
    for group in sorted(
        hierarchy.children,
        key=lambda item: (
            item is not active_group,
            _child_structure_signature(scene, item),
        ),
    ):
        hypothesis_key = _child_isolation_hypothesis_key(
            scene,
            group,
            relation_key=relation_key,
        )
        groups_by_hypothesis.setdefault(hypothesis_key, group)
    current_hypothesis_keys = frozenset(groups_by_hypothesis)
    relation_has_failure = bool(current_hypothesis_keys & rejected_hypothesis_keys)
    candidate_groups = sorted(
        groups_by_hypothesis.items(),
        key=lambda item: (
            0
            if (
                (item[1] is active_group) if relation_has_failure else (item[1] is not active_group)
            )
            else 1,
            _child_structure_signature(scene, item[1]),
        ),
    )
    baseline_target_signature = _target_surface_signature(scene)
    baseline_target_regions = set(_visible_target_regions(scene))
    initial_positions = {
        endpoint.object_ref: endpoint.rounded_center
        for child in hierarchy.children
        for endpoint in child.endpoints
    }
    initial_colors = {
        endpoint.object_ref: endpoint.color
        for child in hierarchy.children
        for endpoint in child.endpoints
    }

    def activation_candidate_order(
        item: VisualObject,
    ) -> tuple[float, int, int, str]:
        return (
            _distance(item.rounded_center, hierarchy.target.rounded_center),
            item.rounded_center[1],
            item.rounded_center[0],
            item.object_ref,
        )

    for hypothesis_key, source_selected_group in candidate_groups:
        if hypothesis_key in rejected_hypothesis_keys:
            continue
        source_frozen_groups = tuple(
            group for group in hierarchy.children if group is not source_selected_group
        )
        if len(source_frozen_groups) != 1:
            continue
        source_frozen_group = source_frozen_groups[0]
        activation_candidates: tuple[VisualObject | None, ...]
        if source_selected_group is active_group:
            activation_candidates = (None,)
        else:
            available_activations: tuple[VisualObject, ...] = source_selected_group.endpoints
            ordered_activations: tuple[VisualObject, ...] = tuple(
                sorted(
                    available_activations,
                    key=activation_candidate_order,
                )
            )
            activation_candidates = ordered_activations
        for activation in activation_candidates:
            role_hierarchy: _AffineHierarchy | None
            if activation is None:
                role_scene = scene
                role_hierarchy = hierarchy
                selected_group = source_selected_group
                frozen_group = source_frozen_group
            else:
                search_budget.consume()
                if not _role_swap_remains_readable(
                    scene,
                    activation,
                    active_color=hierarchy.active_color,
                ):
                    continue
                positions = dict(initial_positions)
                colors = dict(initial_colors)
                colors[active[0].object_ref], colors[activation.object_ref] = (
                    colors[activation.object_ref],
                    colors[active[0].object_ref],
                )
                role_scene = _hierarchy_projected_scene(
                    scene,
                    hierarchy,
                    positions=positions,
                    colors=colors,
                )
                if (
                    len(role_scene.endpoints) != len(scene.endpoints)
                    or len(role_scene.mediators) != len(scene.mediators)
                    or _target_surface_signature(role_scene) != baseline_target_signature
                    or set(_visible_target_regions(role_scene)) != baseline_target_regions
                ):
                    continue
                role_hierarchy = _unique_affine_hierarchy(
                    role_scene,
                    active_color=hierarchy.active_color,
                    search_budget=search_budget,
                )
                if role_hierarchy is None or len(role_hierarchy.children) != 2:
                    continue
                selected_group = role_hierarchy.children[0]
                frozen_group = role_hierarchy.children[1]
                if not _child_group_matches_geometry(
                    selected_group,
                    mediator_center=source_selected_group.mediator.rounded_center,
                    endpoint_centers=tuple(
                        item.rounded_center for item in source_selected_group.endpoints
                    ),
                    mediator_color=source_selected_group.mediator.color,
                ) or not _child_group_matches_geometry(
                    frozen_group,
                    mediator_center=source_frozen_group.mediator.rounded_center,
                    endpoint_centers=tuple(
                        item.rounded_center for item in source_frozen_group.endpoints
                    ),
                    mediator_color=source_frozen_group.mediator.color,
                ):
                    continue
            role_active = tuple(
                item for item in selected_group.endpoints if item.color == hierarchy.active_color
            )
            if len(role_active) != 1:
                continue
            selected_dynamic = _hierarchy_dynamic_footprint(role_scene, selected_group)
            occupied = frozenset(
                (x, y)
                for y, row in enumerate(role_scene.cells)
                for x, value in enumerate(row)
                if value != role_scene.background
            )
            static_cells = occupied - selected_dynamic
            dynamic_target_regions, endpoint_target_regions = _child_isolation_target_regions(
                role_scene,
                role_hierarchy,
            )
            ignored_refs = frozenset(
                item.object_ref for item in (*selected_group.endpoints, selected_group.mediator)
            )
            layouts = _hierarchy_child_layouts(
                role_scene,
                role_hierarchy,
                selected_group,
                support=role_hierarchy.target.rounded_center,
                active_ref=role_active[0].object_ref,
                static_cells=static_cells,
                target_regions=dynamic_target_regions,
                endpoint_target_regions=endpoint_target_regions,
                ignored_refs=ignored_refs,
                search_budget=search_budget,
                result_limit=64,
            )
            for layout in layouts:
                search_budget.consume(_HIERARCHY_SEQUENCE_EVALUATION_COST)
                target_signature = _child_isolation_target_surface_signature(
                    role_scene,
                    sink_center=role_hierarchy.target.rounded_center,
                )
                state_certificates = _child_isolation_sequence_is_safe(
                    role_scene,
                    role_hierarchy,
                    selected_group,
                    frozen_group,
                    layout,
                    static_cells=static_cells,
                    dynamic_target_regions=dynamic_target_regions,
                    endpoint_target_regions=endpoint_target_regions,
                    target_signature=target_signature,
                    search_budget=search_budget,
                )
                if state_certificates is None:
                    continue
                plan = _build_child_isolation_plan(
                    hierarchy,
                    activation=activation,
                    layout=layout,
                    state_certificates=state_certificates,
                    restore_certificate=restore_certificate,
                    frozen_group=frozen_group,
                    target_signature=target_signature,
                    relation_key=relation_key,
                    hypothesis_key=hypothesis_key,
                )
                if plan.signature not in rejected_signatures:
                    return plan
    return None


def _child_isolation_occlusion_certificate_matches(
    scene: VisualScene,
    *,
    expected_protected_raster_hash: str,
    active_color: int,
    sink_center: tuple[int, int],
    target_signature: _TargetSurfaceSignature,
    selected_mediator_signature: _VisualObjectStateSignature,
    selected_endpoint_signature: _EndpointStateSignature,
    selected_raster_signature: _RasterStateSignature,
    occluded_endpoint_centers: tuple[tuple[int, int], ...],
    occluded_endpoint_cells: tuple[tuple[int, int], ...],
    expected_active_center: tuple[int, int],
    frozen_mediator_signature: _VisualObjectStateSignature,
    frozen_endpoint_signature: _EndpointStateSignature,
    frozen_connector_signature: _ConnectorStateSignature,
) -> bool:
    """Match one predeclared passive-endpoint occlusion without reparsing history."""

    if (
        _child_isolation_protected_raster_hash(scene) != expected_protected_raster_hash
        or len(occluded_endpoint_centers) != 1
        or not occluded_endpoint_cells
        or occluded_endpoint_centers[0] in occluded_endpoint_cells
        or _child_isolation_target_surface_signature(scene, sink_center=sink_center)
        != target_signature
        or any(scene.cells[y][x] != value for x, y, value in selected_raster_signature)
        or not set(occluded_endpoint_cells)
        <= {(x, y) for x, y, _value in selected_raster_signature}
    ):
        return False

    occluded_centers = set(occluded_endpoint_centers)
    occluded_endpoint_signatures = tuple(
        signature for signature in selected_endpoint_signature if signature[0] in occluded_centers
    )
    if len(occluded_endpoint_signatures) != 1:
        return False
    endpoint_footprint = _state_signature_footprint(occluded_endpoint_signatures[0])
    mediator_footprint = _state_signature_footprint(selected_mediator_signature)
    if (
        endpoint_footprint is None
        or mediator_footprint is None
        or endpoint_footprint & mediator_footprint != set(occluded_endpoint_cells)
    ):
        return False
    expected_visible_selected = tuple(
        signature
        for signature in selected_endpoint_signature
        if signature[0] not in occluded_centers
    )
    if len(expected_visible_selected) + 1 != len(selected_endpoint_signature):
        return False
    observed_endpoint_signature = tuple(
        sorted(_visual_object_state_signature(endpoint) for endpoint in scene.endpoints)
    )
    if observed_endpoint_signature != tuple(
        sorted((*expected_visible_selected, *frozen_endpoint_signature))
    ):
        return False

    observed_mediator_signature = tuple(
        sorted(_visual_object_state_signature(mediator) for mediator in scene.mediators)
    )
    if observed_mediator_signature != tuple(
        sorted((selected_mediator_signature, frozen_mediator_signature))
    ):
        return False
    active = tuple(endpoint for endpoint in scene.endpoints if endpoint.color == active_color)
    if len(active) != 1 or active[0].rounded_center != expected_active_center:
        return False

    frozen_endpoints = tuple(
        endpoint
        for endpoint in scene.endpoints
        if _visual_object_state_signature(endpoint) in set(frozen_endpoint_signature)
    )
    frozen_mediators = tuple(
        mediator
        for mediator in scene.mediators
        if _visual_object_state_signature(mediator) == frozen_mediator_signature
    )
    return bool(
        len(frozen_endpoints) == len(frozen_endpoint_signature)
        and len(frozen_mediators) == 1
        and _hierarchy_connector_state_signature(
            scene,
            _AffineChildGroup(
                mediator=frozen_mediators[0],
                endpoints=frozen_endpoints,
            ),
        )
        == frozen_connector_signature
    )


def _child_isolation_was_observed(
    hierarchy: _AffineHierarchy,
    *,
    target_center: tuple[int, int] | None,
    mediator_color: int | None,
    arity: int | None,
) -> bool:
    """Require exactly one child at the sink and a distinct frozen sibling."""

    if target_center is None or mediator_color is None or arity is None:
        return False
    isolated = tuple(
        child
        for child in hierarchy.children
        if child.arity == arity
        and child.mediator.color == mediator_color
        and child.mediator.rounded_center == target_center
        and sum(item.rounded_center[0] for item in child.endpoints) == arity * target_center[0]
        and sum(item.rounded_center[1] for item in child.endpoints) == arity * target_center[1]
    )
    return bool(
        len(hierarchy.children) == 2
        and len(isolated) == 1
        and all(
            child is isolated[0] or child.mediator.rounded_center != target_center
            for child in hierarchy.children
        )
    )


def _single_hierarchy_planned_click_is_safe(
    scene: VisualScene,
    planned: PlannedClick,
    *,
    active_color: int,
) -> bool:
    """Revalidate one queued hierarchy action against the returned frame."""

    if not planned.plan_signature.startswith(_HIERARCHY_PLAN_PREFIXES):
        return True
    access_certificate = planned.post_deposit_mediator_access_certificate
    if access_certificate is not None:
        return bool(
            _post_deposit_mediator_access_step_is_compatible(planned)
            and not scene.targets
            and len(scene.mediators) == 1
            and _visual_object_state_signature(scene.mediators[0])
            == access_certificate.mediator_signature
            and _child_isolation_protected_raster_hash(scene)
            == access_certificate.protected_raster_hash
            and len(scene.endpoints) == access_certificate.visible_endpoint_count
        )
    composite_certificate = planned.post_access_composite_exit_certificate
    if composite_certificate is not None:
        composite = _unique_post_access_composite(scene)
        return bool(
            _post_access_composite_exit_step_is_compatible(planned)
            and composite is not None
            and composite[2] == composite_certificate.common_center
            and _visual_object_state_signature(composite[0])
            == composite_certificate.mediator_signature
            and _visual_object_state_signature(composite[1])
            == composite_certificate.target_signature
            and _child_isolation_protected_raster_hash(scene)
            == composite_certificate.protected_raster_hash
            and len(scene.endpoints) == composite_certificate.visible_endpoint_count
        )
    marker_certificate = planned.post_access_composite_marker_certificate
    if marker_certificate is not None:
        composite = _unique_post_access_composite(scene)
        marker = _unique_post_access_composite_marker(scene)
        return bool(
            _post_access_composite_marker_step_is_compatible(planned)
            and composite is not None
            and composite[2] == marker_certificate.common_center
            and _visual_object_state_signature(composite[0])
            == marker_certificate.mediator_signature
            and _visual_object_state_signature(composite[1]) == marker_certificate.target_signature
            and _endpoint_state_signature(scene.endpoints) == marker_certificate.endpoint_signature
            and _child_isolation_protected_raster_hash(scene)
            == marker_certificate.protected_raster_hash
            and marker == (marker_certificate.marker_color, marker_certificate.marker_coordinate)
        )
    cargo_certificate = planned.same_child_composite_cargo_certificate
    if cargo_certificate is not None:
        visible_endpoints = _same_child_composite_cargo_visible_endpoints(
            scene,
            marker_color=cargo_certificate.endpoint_marker_color,
        )
        active = tuple(endpoint for endpoint in visible_endpoints if endpoint.color == active_color)
        selected = tuple(
            endpoint
            for endpoint in visible_endpoints
            if endpoint.rounded_center == (planned.coordinate.x, planned.coordinate.y)
        )
        action_precondition = bool(
            (
                planned.purpose is VisualActionPurpose.PROBE
                and len(selected) == 1
                and selected[0].color != active_color
            )
            or (
                planned.purpose is VisualActionPurpose.PROGRESS
                and len(active) == cargo_certificate.required_visible_active_endpoint_count
            )
        )
        return bool(
            _same_child_composite_cargo_step_is_compatible(planned)
            and action_precondition
            and planned.required_child_protected_raster_hash is not None
            and _child_isolation_protected_raster_hash(scene)
            == planned.required_child_protected_raster_hash
            and len(visible_endpoints) == cargo_certificate.required_visible_endpoint_count
            and len(scene.mediators) == cargo_certificate.required_visible_mediator_count
            and len(active) == cargo_certificate.required_visible_active_endpoint_count
        )
    paired_cargo_step = bool(
        planned.carrier_source_paired_cargo_step
        or planned.carrier_source_paired_cargo_restoration_step
        or planned.carrier_source_paired_cargo_role_handoff_step
        or planned.carrier_source_paired_cargo_role_restoration_step
        or planned.carrier_source_paired_cargo_crossed_predecessor_step
        or planned.carrier_source_paired_cargo_crossed_delivery_step
    )
    if paired_cargo_step:
        if not (
            _carrier_source_paired_cargo_step_is_compatible(planned)
            or _carrier_source_paired_cargo_restoration_step_is_compatible(planned)
            or _carrier_source_paired_cargo_role_handoff_step_is_compatible(planned)
            or _carrier_source_paired_cargo_role_restoration_step_is_compatible(planned)
            or _carrier_source_paired_cargo_crossed_predecessor_step_is_compatible(planned)
            or _carrier_source_paired_cargo_crossed_delivery_step_is_compatible(planned)
        ):
            return False
    elif planned.carrier_source_target_center_role_exchange_step:
        if (
            not _carrier_source_delivery_step_is_compatible(planned)
            or any(target.rounded_center == planned.target_center for target in scene.targets)
            or len(
                tuple(
                    mediator
                    for mediator in scene.mediators
                    if mediator.rounded_center == planned.target_center
                )
            )
            != 1
        ):
            return False
    elif planned.carrier_source_detachment_step:
        if (
            not _carrier_source_detachment_step_is_compatible(planned)
            or any(target.rounded_center == planned.target_center for target in scene.targets)
            or len(
                tuple(
                    mediator
                    for mediator in scene.mediators
                    if mediator.rounded_center == planned.target_center
                )
            )
            != 1
        ):
            return False
    elif not any(target.rounded_center == planned.target_center for target in scene.targets):
        return False
    if planned.required_child_protected_raster_hash is not None and (
        _child_isolation_protected_raster_hash(scene)
        != planned.required_child_protected_raster_hash
    ):
        return False
    if planned.required_child_raster_signature and any(
        scene.cells[y][x] != value for x, y, value in planned.required_child_raster_signature
    ):
        return False
    if planned.completes_carrier_source_delivery:
        detachment_probe = planned.carrier_source_detachment_probe
        if detachment_probe is not None:
            prior_active = tuple(
                endpoint for endpoint in scene.endpoints if endpoint.color == active_color
            )
            if (
                not _carrier_source_detachment_step_is_compatible(detachment_probe)
                or len(prior_active) != 1
                or detachment_probe.coordinate != Coordinate(*prior_active[0].rounded_center)
            ):
                return False
    if planned.required_visible_active_endpoint_count is not None:
        if (
            planned.required_child_protected_raster_hash is None
            or planned.expected_child_protected_raster_hash is None
            or planned.expected_visible_endpoint_count is None
            or planned.expected_visible_mediator_count is None
            or not planned.plan_signature.startswith(_CARRIER_SOURCE_MASKED_PLAN_PREFIXES)
        ):
            return False
        coordinate = (planned.coordinate.x, planned.coordinate.y)
        visible_active = tuple(
            endpoint for endpoint in scene.endpoints if endpoint.color == active_color
        )
        if len(visible_active) != planned.required_visible_active_endpoint_count:
            return False
        if planned.purpose is VisualActionPurpose.PROBE:
            selected = tuple(
                endpoint for endpoint in scene.endpoints if endpoint.rounded_center == coordinate
            )
            return bool(
                planned.required_visible_active_endpoint_count in {0, 1}
                and planned.expected_active_center == coordinate
                and len(selected) == 1
                and selected[0].color != active_color
                and not _role_swap_remains_readable(
                    scene,
                    selected[0],
                    active_color=active_color,
                )
            )
        if planned.purpose is VisualActionPurpose.PROGRESS:
            destination = frozenset({coordinate})
            return bool(
                planned.required_visible_active_endpoint_count == 0
                and planned.expected_active_center == coordinate
                and _hierarchy_cells_in_bounds(scene, destination)
                and _hierarchy_avoids_target_regions(
                    destination,
                    _visible_target_regions(scene),
                )
            )
        return False
    if planned.purpose is VisualActionPurpose.PROBE:
        selected = tuple(
            endpoint
            for endpoint in scene.endpoints
            if endpoint.rounded_center == (planned.coordinate.x, planned.coordinate.y)
        )
        active = tuple(endpoint for endpoint in scene.endpoints if endpoint.color == active_color)
        if (
            planned.carrier_source_paired_cargo_crossed_predecessor_family
            and planned.carrier_source_paired_cargo_crossed_predecessor_step
            and planned.completes_carrier_source_paired_cargo_crossed_predecessor
            and planned.required_child_protected_raster_hash is not None
            and planned.expected_child_protected_raster_hash is not None
            and planned.expected_visible_endpoint_count is not None
            and planned.expected_visible_mediator_count is not None
            and len(active) == 1
            and len(selected) == 1
            and selected[0].color != active_color
            and len(scene.endpoints) - 1 == planned.expected_visible_endpoint_count
            and len(scene.mediators) + 1 == planned.expected_visible_mediator_count
        ):
            return True
        return len(selected) == 1 and _role_swap_remains_readable(
            scene,
            selected[0],
            active_color=active_color,
        )
    active = tuple(endpoint for endpoint in scene.endpoints if endpoint.color == active_color)
    if len(active) != 1:
        return False
    target_regions = _visible_target_regions(scene)
    prospective = _translated_object_footprint(
        active[0],
        center=(planned.coordinate.x, planned.coordinate.y),
    )
    return _hierarchy_cells_in_bounds(
        scene,
        prospective,
    ) and _hierarchy_avoids_target_regions(
        prospective,
        target_regions,
    )


def _carrier_source_recovery_action_signature(planned: PlannedClick) -> tuple[object, ...]:
    """Fields that no carrier-source recovery branch is permitted to change."""

    return (
        planned.coordinate,
        planned.purpose,
        planned.expectation,
        planned.mechanic_ref,
        planned.plan_id,
        planned.plan_signature,
        planned.target_center,
        planned.mediator_color,
        planned.arity,
        planned.completes_local_target,
        planned.completes_hierarchy,
        planned.completes_child_isolation,
        planned.completes_child_recovery,
        planned.stages_for_switch,
        planned.expected_child_mediator_center,
        planned.expected_child_mediator_signature,
        planned.expected_child_endpoint_centers,
        planned.expected_child_endpoint_signature,
        planned.expected_child_connector_signature,
        planned.expected_active_center,
        planned.expected_child_raster_signature,
        planned.expected_occluded_endpoint_centers,
        planned.expected_occluded_endpoint_cells,
        planned.carrier_source_delivery_step,
        planned.completes_carrier_source_delivery,
        planned.carrier_source_detachment_step,
        planned.carrier_source_target_center_role_exchange_step,
        planned.carrier_source_attachment_continuation_actions,
        planned.carrier_source_untouched_role_exchange_step,
        planned.carrier_source_untouched_discriminator_step,
        planned.carrier_source_untouched_restoration_step,
        planned.completes_carrier_source_untouched_restoration,
        planned.carrier_source_paired_cargo_step,
        planned.completes_carrier_source_paired_cargo,
        planned.carrier_source_paired_cargo_initial_protected_raster_hash,
        planned.carrier_source_paired_cargo_restoration_actions,
        planned.carrier_source_paired_cargo_restoration_step,
        planned.completes_carrier_source_paired_cargo_restoration,
        planned.carrier_source_paired_cargo_role_handoff_family,
        planned.carrier_source_paired_cargo_role_handoff,
        planned.carrier_source_paired_cargo_role_handoff_step,
        planned.carrier_source_paired_cargo_role_restoration_actions,
        planned.carrier_source_paired_cargo_role_restoration_step,
        planned.carrier_source_paired_cargo_crossed_predecessor_family,
        planned.carrier_source_paired_cargo_crossed_predecessor_actions,
        planned.carrier_source_paired_cargo_crossed_predecessor_step,
        planned.completes_carrier_source_paired_cargo_crossed_predecessor,
        planned.carrier_source_paired_cargo_crossed_delivery_step,
        planned.completes_carrier_source_paired_cargo_crossed_delivery,
        planned.expected_deposited_source_protected_raster_hash,
        planned.expected_deposited_visible_endpoint_count,
        planned.expected_deposited_visible_mediator_count,
    )


def _carrier_source_delivery_step_is_compatible(planned: PlannedClick) -> bool:
    """Reject a destination step without one closed carried-source boundary."""

    required_indexes = planned.required_carried_source_support_indexes
    return bool(
        planned.carrier_source_delivery_step
        and planned.plan_signature.startswith("affine-carrier-source-occlusion-hierarchy-recovery:")
        and planned.carrier_source_recovery_alternative is None
        and not planned.carrier_source_recovery_candidates
        and not planned.carrier_source_delivery_actions
        and not planned.carrier_source_attachment_continuation_actions
        and not planned.carrier_source_untouched_role_exchange_step
        and not planned.carrier_source_untouched_discriminator_step
        and not planned.carrier_source_untouched_restoration_actions
        and not planned.carrier_source_untouched_restoration_step
        and not planned.completes_carrier_source_untouched_restoration
        and len(required_indexes) == 1
        and planned.expected_carried_source_support_indexes == required_indexes
        and planned.required_child_protected_raster_hash is not None
        and planned.expected_child_protected_raster_hash is not None
        and planned.expected_visible_endpoint_count is not None
        and planned.expected_visible_mediator_count is not None
        and planned.expected_active_center == (planned.coordinate.x, planned.coordinate.y)
        and (
            not planned.completes_carrier_source_delivery
            or planned.purpose is VisualActionPurpose.PROGRESS
        )
        and not planned.completes_hierarchy
        and not planned.completes_child_isolation
        and not planned.completes_child_recovery
        and not planned.completes_local_target
        and not planned.stages_for_switch
        and not planned.carrier_source_detachment_step
        and (
            not planned.carrier_source_target_center_role_exchange_step
            or (
                planned.purpose is VisualActionPurpose.PROBE
                and planned.plan_id.startswith("visual-carrier-source-detachment:")
                and not planned.completes_carrier_source_delivery
            )
        )
        and planned.expected_deposited_source_protected_raster_hash is None
        and planned.expected_deposited_visible_endpoint_count is None
        and planned.expected_deposited_visible_mediator_count is None
        and (
            planned.carrier_source_detachment_probe is None
            or (
                planned.completes_carrier_source_delivery
                and _carrier_source_detachment_step_is_compatible(
                    planned.carrier_source_detachment_probe
                )
            )
        )
    )


def _carrier_source_attachment_continuation_actions_are_compatible(
    planned: PlannedClick,
) -> bool:
    """Validate one consequence-gated alternative-endpoint detachment route."""

    actions = planned.carrier_source_attachment_continuation_actions
    expected_indexes = planned.expected_carried_source_support_indexes
    if (
        len(actions) != 3
        or len(expected_indexes) != 1
        or not actions[0].plan_id.startswith("visual-carrier-source-detachment:")
        or actions[0].required_child_protected_raster_hash
        != planned.expected_child_protected_raster_hash
    ):
        return False
    for index, action in enumerate(actions):
        if (
            action.plan_signature != planned.plan_signature
            or action.mechanic_ref != planned.mechanic_ref
            or action.plan_id != actions[0].plan_id
            or action.target_center != planned.target_center
            or action.mediator_color != planned.mediator_color
            or action.arity != planned.arity
            or action.required_carried_source_support_indexes != expected_indexes
            or action.expected_carried_source_support_indexes != expected_indexes
            or action.carrier_source_attachment_continuation_actions
            or action.carrier_source_target_center_role_exchange_step != (index == 1)
        ):
            return False
        if index and (
            actions[index - 1].expected_child_protected_raster_hash
            != action.required_child_protected_raster_hash
        ):
            return False
    return bool(
        actions[0].purpose is VisualActionPurpose.PROGRESS
        and actions[1].purpose is VisualActionPurpose.PROBE
        and actions[2].purpose is VisualActionPurpose.PROGRESS
        and _carrier_source_delivery_step_is_compatible(actions[0])
        and _carrier_source_delivery_step_is_compatible(actions[1])
        and not actions[0].completes_carrier_source_delivery
        and not actions[1].completes_carrier_source_delivery
        and _carrier_source_detachment_step_is_compatible(actions[2])
    )


def _carrier_source_detachment_step_is_compatible(planned: PlannedClick) -> bool:
    """Require one exact inverse with two exclusive source-attachment outcomes."""

    required_indexes = planned.required_carried_source_support_indexes
    return bool(
        planned.carrier_source_detachment_step
        and planned.plan_id.startswith("visual-carrier-source-detachment:")
        and planned.plan_signature.startswith("affine-carrier-source-occlusion-hierarchy-recovery:")
        and planned.purpose is VisualActionPurpose.PROGRESS
        and planned.carrier_source_recovery_alternative is None
        and not planned.carrier_source_recovery_candidates
        and not planned.carrier_source_delivery_actions
        and planned.carrier_source_detachment_probe is None
        and not planned.carrier_source_target_center_role_exchange_step
        and not planned.carrier_source_untouched_role_exchange_step
        and not planned.carrier_source_untouched_discriminator_step
        and not planned.carrier_source_untouched_restoration_actions
        and not planned.carrier_source_untouched_restoration_step
        and not planned.completes_carrier_source_untouched_restoration
        and (
            not planned.carrier_source_attachment_continuation_actions
            or _carrier_source_attachment_continuation_actions_are_compatible(planned)
        )
        and len(required_indexes) == 1
        and planned.expected_carried_source_support_indexes == required_indexes
        and planned.required_child_protected_raster_hash is not None
        and planned.expected_child_protected_raster_hash is not None
        and planned.expected_deposited_source_protected_raster_hash is not None
        and planned.expected_child_protected_raster_hash
        != planned.expected_deposited_source_protected_raster_hash
        and planned.expected_visible_endpoint_count is not None
        and planned.expected_visible_mediator_count is not None
        and planned.expected_deposited_visible_endpoint_count is not None
        and planned.expected_deposited_visible_mediator_count is not None
        and planned.expected_active_center == (planned.coordinate.x, planned.coordinate.y)
        and not planned.carrier_source_delivery_step
        and not planned.completes_carrier_source_delivery
        and not planned.completes_hierarchy
        and not planned.completes_child_isolation
        and not planned.completes_child_recovery
        and not planned.completes_local_target
        and not planned.stages_for_switch
    )


def _carrier_source_delivery_actions_are_compatible(alternative: PlannedClick) -> bool:
    """Validate the target route attached to one exact carried consequence."""

    actions = alternative.carrier_source_delivery_actions
    expected_indexes = alternative.expected_carried_source_support_indexes
    if (
        not actions
        or len(expected_indexes) != 1
        or len(actions) != 2 * alternative.arity - 1
        or not actions[0].plan_id.startswith("visual-carrier-source-delivery:")
        or actions[0].required_child_protected_raster_hash
        != alternative.expected_child_protected_raster_hash
    ):
        return False
    for index, action in enumerate(actions):
        expected_purpose = (
            VisualActionPurpose.PROGRESS if index % 2 == 0 else VisualActionPurpose.PROBE
        )
        if (
            not _carrier_source_delivery_step_is_compatible(action)
            or action.plan_signature != alternative.plan_signature
            or action.mechanic_ref != alternative.mechanic_ref
            or action.plan_id != actions[0].plan_id
            or action.target_center != alternative.target_center
            or action.mediator_color != alternative.mediator_color
            or action.arity != alternative.arity
            or action.required_carried_source_support_indexes != expected_indexes
            or action.expected_carried_source_support_indexes != expected_indexes
            or action.purpose is not expected_purpose
            or action.completes_carrier_source_delivery != (index + 1 == len(actions))
            or (action.carrier_source_detachment_probe is not None and index + 1 != len(actions))
        ):
            return False
        if index and (
            actions[index - 1].expected_child_protected_raster_hash
            != action.required_child_protected_raster_hash
        ):
            return False
    final_probe = actions[-1].carrier_source_detachment_probe
    if final_probe is None:
        return True
    if (
        not _carrier_source_detachment_step_is_compatible(final_probe)
        or final_probe.plan_signature != alternative.plan_signature
        or final_probe.mechanic_ref != alternative.mechanic_ref
        or final_probe.target_center != alternative.target_center
        or final_probe.mediator_color != alternative.mediator_color
        or final_probe.arity != alternative.arity
        or final_probe.required_carried_source_support_indexes != expected_indexes
        or final_probe.required_child_protected_raster_hash
        != actions[-1].expected_child_protected_raster_hash
        or final_probe.coordinate != actions[-2].coordinate
        or final_probe.expected_child_protected_raster_hash
        != actions[-1].required_child_protected_raster_hash
        or final_probe.expected_visible_endpoint_count
        != actions[-2].expected_visible_endpoint_count
        or final_probe.expected_visible_mediator_count
        != actions[-2].expected_visible_mediator_count
        or (
            bool(final_probe.carrier_source_attachment_continuation_actions)
            and (
                final_probe.carrier_source_attachment_continuation_actions[0].coordinate
                != actions[-1].coordinate
                or final_probe.carrier_source_attachment_continuation_actions[
                    0
                ].expected_child_protected_raster_hash
                != actions[-1].expected_child_protected_raster_hash
                or final_probe.carrier_source_attachment_continuation_actions[
                    0
                ].expected_visible_endpoint_count
                != actions[-1].expected_visible_endpoint_count
                or final_probe.carrier_source_attachment_continuation_actions[
                    0
                ].expected_visible_mediator_count
                != actions[-1].expected_visible_mediator_count
            )
        )
    ):
        return False
    return True


def _carrier_source_attachment_continuation_after_observed_restoration(
    context: _CarrierSourceAttachmentReplayContext,
    planned: PlannedClick,
    restored_scene: VisualScene,
) -> tuple[PlannedClick, ...]:
    """Derive one finite continuation only after the carried restoration is observed."""

    if (
        planned.carrier_source_attachment_continuation_actions
        or not _carrier_source_detachment_step_is_compatible(planned)
        or planned.expected_child_protected_raster_hash is None
        or _child_isolation_protected_raster_hash(restored_scene)
        != planned.expected_child_protected_raster_hash
        or planned.expected_visible_endpoint_count != len(restored_scene.endpoints)
        or planned.expected_visible_mediator_count != len(restored_scene.mediators)
    ):
        return ()
    regenerated = _build_hierarchy_plan(
        context.hierarchy,
        context.layouts,
        scene=context.scene,
        move_order=context.move_order,
        support_weights=context.support_weights,
        carrier_source_supports=context.carrier_source_supports,
        carrier_source_level_index=context.level_index,
        carrier_source_rejected_external_relation_key=(
            context.rejected_external_residual_relation_key
        ),
        signature_prefix=context.signature_prefix,
        terminal_expectation=context.terminal_expectation,
        derive_carrier_source_attachment_continuations=True,
    )
    matches: list[PlannedClick] = []
    for recovery in regenerated.recovery_actions:
        for state_candidate in (recovery, *recovery.carrier_source_recovery_candidates):
            alternative = state_candidate.carrier_source_recovery_alternative
            if alternative is None or not alternative.carrier_source_delivery_actions:
                continue
            probe = alternative.carrier_source_delivery_actions[-1].carrier_source_detachment_probe
            if (
                probe is not None
                and probe.plan_id == planned.plan_id
                and probe.carrier_source_attachment_continuation_actions
                and replace(probe, carrier_source_attachment_continuation_actions=()) == planned
            ):
                matches.append(probe)
    if len(matches) != 1:
        return ()
    derived = matches[0]
    if not _carrier_source_attachment_continuation_actions_are_compatible(derived):
        return ()
    return derived.carrier_source_attachment_continuation_actions


def _carrier_source_untouched_discriminator_after_observed_attachment(
    context: _CarrierSourceAttachmentReplayContext,
    planned: PlannedClick,
    restored_scene: VisualScene,
) -> tuple[PlannedClick, ...]:
    """Derive one untouched-carrier test only from the exact final carried receipt."""

    if (
        planned.carrier_source_attachment_continuation_actions
        or not _carrier_source_detachment_step_is_compatible(planned)
        or planned.expected_child_protected_raster_hash is None
        or _child_isolation_protected_raster_hash(restored_scene)
        != planned.expected_child_protected_raster_hash
        or planned.expected_visible_endpoint_count != len(restored_scene.endpoints)
        or planned.expected_visible_mediator_count != len(restored_scene.mediators)
    ):
        return ()
    regenerated = _build_hierarchy_plan(
        context.hierarchy,
        context.layouts,
        scene=context.scene,
        move_order=context.move_order,
        support_weights=context.support_weights,
        carrier_source_supports=context.carrier_source_supports,
        carrier_source_level_index=context.level_index,
        carrier_source_rejected_external_relation_key=(
            context.rejected_external_residual_relation_key
        ),
        signature_prefix=context.signature_prefix,
        terminal_expectation=context.terminal_expectation,
        derive_carrier_source_attachment_continuations=True,
    )

    def replay(
        actions: tuple[PlannedClick, ...],
    ) -> tuple[dict[str, tuple[int, int]], dict[str, int]] | None:
        positions = {
            endpoint.object_ref: endpoint.rounded_center
            for child in context.hierarchy.children
            for endpoint in child.endpoints
        }
        colors = {
            endpoint.object_ref: endpoint.color
            for child in context.hierarchy.children
            for endpoint in child.endpoints
        }
        for action in actions:
            active_refs = tuple(
                ref for ref, color in colors.items() if color == context.hierarchy.active_color
            )
            if len(active_refs) != 1:
                return None
            active_ref = active_refs[0]
            coordinate = (action.coordinate.x, action.coordinate.y)
            if action.purpose is VisualActionPurpose.PROBE:
                selected_refs = tuple(
                    ref for ref, center in positions.items() if center == coordinate
                )
                if len(selected_refs) != 1 or selected_refs[0] == active_ref:
                    return None
                selected_ref = selected_refs[0]
                colors[active_ref], colors[selected_ref] = (
                    colors[selected_ref],
                    colors[active_ref],
                )
            elif action.purpose is VisualActionPurpose.PROGRESS:
                positions[active_ref] = coordinate
            else:
                return None
        return positions, colors

    replay_matches: list[
        tuple[
            dict[str, tuple[int, int]],
            dict[str, int],
            tuple[int, ...],
        ]
    ] = []
    for recovery_index, recovery in enumerate(regenerated.recovery_actions):
        for state_candidate in (recovery, *recovery.carrier_source_recovery_candidates):
            alternative = state_candidate.carrier_source_recovery_alternative
            if alternative is None or not alternative.carrier_source_delivery_actions:
                continue
            delivery = alternative.carrier_source_delivery_actions
            initial_probe = delivery[-1].carrier_source_detachment_probe
            if initial_probe is None:
                continue
            continuation = initial_probe.carrier_source_attachment_continuation_actions
            if not continuation or continuation[-1] != planned:
                continue
            replayed = replay(
                (
                    *regenerated.actions,
                    *regenerated.recovery_actions[: recovery_index + 1],
                    *delivery,
                    initial_probe,
                    *continuation,
                )
            )
            if replayed is None:
                continue
            positions, colors = replayed
            carried_indexes = planned.expected_carried_source_support_indexes
            try:
                projected = _carrier_source_carried_projected_scene(
                    context.scene,
                    context.hierarchy,
                    context.carrier_source_supports,
                    positions=positions,
                    colors=colors,
                    carried_support_indexes=frozenset(carried_indexes),
                )
            except ValueError:
                continue
            if (
                tuple(tuple(row[1:]) for row in projected.cells)
                != tuple(tuple(row[1:]) for row in restored_scene.cells)
                or len(projected.endpoints) != len(restored_scene.endpoints)
                or len(projected.mediators) != len(restored_scene.mediators)
            ):
                continue
            replay_matches.append((positions, colors, carried_indexes))
    if len(replay_matches) != 1:
        return ()

    positions, colors, carried_indexes = replay_matches[0]
    support_count = len(context.carrier_source_supports)
    carried = frozenset(carried_indexes)
    unresolved_indexes = tuple(index for index in range(support_count) if index not in carried)
    if len(carried) != 1 or len(unresolved_indexes) != 1:
        return ()
    untouched_index = unresolved_indexes[0]
    untouched_support = context.carrier_source_supports[untouched_index]
    matching_layouts = tuple(
        layout for layout in context.layouts if layout.group == untouched_support.child
    )
    if len(matching_layouts) != 1 or not matching_layouts[0].movers:
        return ()
    untouched_layout = matching_layouts[0]
    untouched_mover = untouched_layout.movers[-1]
    untouched_ref = untouched_mover.object_ref
    current_point = untouched_layout.points[-1]
    predecessor = untouched_mover.rounded_center
    active_refs = tuple(
        ref for ref, color in colors.items() if color == context.hierarchy.active_color
    )
    if (
        len(active_refs) != 1
        or active_refs[0] == untouched_ref
        or positions.get(untouched_ref) != current_point
        or current_point == predecessor
        or sum(center == current_point for center in positions.values()) != 1
    ):
        return ()
    prior_active_ref = active_refs[0]
    prior_active_point = positions[prior_active_ref]
    visible_current = tuple(
        endpoint
        for endpoint in restored_scene.endpoints
        if endpoint.rounded_center == current_point
    )
    visible_prior_active = tuple(
        endpoint
        for endpoint in restored_scene.endpoints
        if endpoint.rounded_center == prior_active_point
    )
    if (
        len(visible_current) != 1
        or visible_current[0].color == context.hierarchy.active_color
        or len(visible_prior_active) != 1
        or visible_prior_active[0].color != context.hierarchy.active_color
    ):
        return ()

    def project(
        projected_positions: dict[str, tuple[int, int]],
        projected_colors: dict[str, int],
        indexes: frozenset[int],
    ) -> VisualScene | None:
        try:
            return _carrier_source_carried_projected_scene(
                context.scene,
                context.hierarchy,
                context.carrier_source_supports,
                positions=projected_positions,
                colors=projected_colors,
                carried_support_indexes=indexes,
            )
        except ValueError:
            return None

    def certificate(projected: VisualScene) -> _HierarchyRasterCertificate:
        return _HierarchyRasterCertificate(
            protected_raster_hash=_child_isolation_protected_raster_hash(projected),
            visible_endpoint_count=len(projected.endpoints),
            visible_mediator_count=len(projected.mediators),
        )

    def require_exact_lineage(
        candidate: PlannedClick,
        required_scene: VisualScene,
        *,
        required_indexes: tuple[int, ...],
    ) -> PlannedClick:
        if _hierarchy_planned_click_is_safe(
            required_scene,
            candidate,
            active_color=context.hierarchy.active_color,
            required_carried_source_support_indexes=required_indexes,
        ):
            return candidate
        visible_active_count = sum(
            endpoint.color == context.hierarchy.active_color
            for endpoint in required_scene.endpoints
        )
        alternative = candidate.carrier_source_recovery_alternative
        recovery_candidates = candidate.carrier_source_recovery_candidates
        masked = replace(
            candidate,
            required_visible_active_endpoint_count=visible_active_count,
            carrier_source_recovery_alternative=(
                replace(
                    alternative,
                    required_visible_active_endpoint_count=visible_active_count,
                )
                if alternative is not None
                else None
            ),
            carrier_source_recovery_candidates=tuple(
                replace(
                    recovery_candidate,
                    required_visible_active_endpoint_count=visible_active_count,
                )
                for recovery_candidate in recovery_candidates
            ),
        )
        if not _hierarchy_planned_click_is_safe(
            required_scene,
            masked,
            active_color=context.hierarchy.active_color,
            required_carried_source_support_indexes=required_indexes,
        ):
            raise ValueError("untouched carrier action lacks an exact masked-lineage precondition")
        return masked

    baseline_scene = project(positions, colors, carried)
    if baseline_scene is None or tuple(tuple(row[1:]) for row in baseline_scene.cells) != tuple(
        tuple(row[1:]) for row in restored_scene.cells
    ):
        return ()
    role_colors = dict(colors)
    role_colors[prior_active_ref], role_colors[untouched_ref] = (
        role_colors[untouched_ref],
        role_colors[prior_active_ref],
    )
    role_scene = project(positions, role_colors, carried)
    if role_scene is None or role_scene.cells == baseline_scene.cells:
        return ()
    moved_positions = dict(positions)
    moved_positions[untouched_ref] = predecessor
    newly_carried = carried | {untouched_index}
    stationary_scene = project(moved_positions, role_colors, carried)
    newly_carried_scene = project(moved_positions, role_colors, newly_carried)
    if stationary_scene is None or newly_carried_scene is None:
        return ()

    untouched_centers = tuple(
        positions[endpoint.object_ref] for endpoint in untouched_support.child.endpoints
    )
    untouched_moved_centers = tuple(
        moved_positions[endpoint.object_ref] for endpoint in untouched_support.child.endpoints
    )
    untouched_center = (
        sum(point[0] for point in untouched_centers) // untouched_support.child.arity,
        sum(point[1] for point in untouched_centers) // untouched_support.child.arity,
    )
    untouched_moved_center = (
        sum(point[0] for point in untouched_moved_centers) // untouched_support.child.arity,
        sum(point[1] for point in untouched_moved_centers) // untouched_support.child.arity,
    )
    current_dynamic = _hierarchy_projected_group_footprint(
        untouched_support.child,
        endpoint_centers=untouched_centers,
        mediator_center=untouched_center,
    )
    moved_dynamic = _hierarchy_projected_group_footprint(
        untouched_support.child,
        endpoint_centers=untouched_moved_centers,
        mediator_center=untouched_moved_center,
    )
    source_x, source_y = untouched_support.source.center
    moved_source = frozenset(
        (untouched_moved_center[0] + x - source_x, untouched_moved_center[1] + y - source_y)
        for x, y in untouched_support.source.cells
    )
    target_cells = frozenset(cell for target in context.scene.targets for cell in target.cells)
    protected_cells = set(target_cells)
    for index in carried:
        support = context.carrier_source_supports[index]
        support_centers = tuple(
            positions[endpoint.object_ref] for endpoint in support.child.endpoints
        )
        support_center = (
            sum(point[0] for point in support_centers) // support.child.arity,
            sum(point[1] for point in support_centers) // support.child.arity,
        )
        protected_cells.update(support.source.cells)
        protected_cells.update(
            _hierarchy_projected_group_footprint(
                support.child,
                endpoint_centers=support_centers,
                mediator_center=support_center,
            )
        )
        support_source_x, support_source_y = support.source.center
        protected_cells.update(
            (support_center[0] + x - support_source_x, support_center[1] + y - support_source_y)
            for x, y in support.source.cells
        )
    mutable_cells = (
        current_dynamic | moved_dynamic | frozenset(untouched_support.source.cells) | moved_source
    )
    stationary_occupied = (
        frozenset(
            (x, y)
            for y, row in enumerate(role_scene.cells)
            for x, value in enumerate(row)
            if value != role_scene.background
        )
        - current_dynamic
        - frozenset(untouched_support.source.cells)
    )
    if (
        not _hierarchy_cells_in_bounds(context.scene, moved_dynamic | moved_source)
        or bool((moved_dynamic | moved_source) & frozenset(protected_cells))
        or bool((moved_dynamic | moved_source) & stationary_occupied)
        or any(
            projected.cells[y][x] != role_scene.cells[y][x]
            for projected in (stationary_scene, newly_carried_scene)
            for y in range(context.scene.height)
            for x in range(context.scene.width)
            if (x, y) not in mutable_cells
        )
        or any(
            projected.cells[y][x] != role_scene.cells[y][x]
            for projected in (stationary_scene, newly_carried_scene)
            for x, y in protected_cells
        )
    ):
        return ()
    stationary_certificate = certificate(stationary_scene)
    newly_carried_certificate = certificate(newly_carried_scene)
    if stationary_certificate == newly_carried_certificate:
        return ()

    stationary_restored = project(positions, role_colors, carried)
    newly_carried_restored = project(positions, role_colors, newly_carried)
    restored_colors = dict(role_colors)
    restored_colors[prior_active_ref], restored_colors[untouched_ref] = (
        restored_colors[untouched_ref],
        restored_colors[prior_active_ref],
    )
    stationary_final = project(positions, restored_colors, carried)
    newly_carried_final = project(positions, restored_colors, newly_carried)
    if (
        stationary_restored is None
        or newly_carried_restored is None
        or stationary_final is None
        or newly_carried_final is None
        or tuple(tuple(row[1:]) for row in stationary_restored.cells)
        != tuple(tuple(row[1:]) for row in role_scene.cells)
        or tuple(tuple(row[1:]) for row in newly_carried_restored.cells)
        != tuple(tuple(row[1:]) for row in role_scene.cells)
        or tuple(tuple(row[1:]) for row in stationary_final.cells)
        != tuple(tuple(row[1:]) for row in baseline_scene.cells)
        or tuple(tuple(row[1:]) for row in newly_carried_final.cells)
        != tuple(tuple(row[1:]) for row in baseline_scene.cells)
    ):
        return ()

    baseline_certificate = certificate(baseline_scene)
    role_certificate = certificate(role_scene)
    stationary_restored_certificate = certificate(stationary_restored)
    newly_carried_restored_certificate = certificate(newly_carried_restored)
    stationary_final_certificate = certificate(stationary_final)
    newly_carried_final_certificate = certificate(newly_carried_final)
    plan_id = (
        "visual-carrier-source-untouched:"
        + hashlib.sha256(
            (
                f"{planned.plan_id}|{untouched_support.child.mediator.object_ref}|"
                f"{untouched_ref}|{predecessor[0]},{predecessor[1]}"
            ).encode("ascii")
        ).hexdigest()[:24]
    )

    def restoration_actions(
        *,
        indexes: tuple[int, ...],
        moved_certificate: _HierarchyRasterCertificate,
        restored_certificate: _HierarchyRasterCertificate,
        final_certificate: _HierarchyRasterCertificate,
    ) -> tuple[PlannedClick, ...]:
        return (
            PlannedClick(
                coordinate=Coordinate(*current_point),
                purpose=VisualActionPurpose.PROGRESS,
                expectation=(
                    "restore the untouched carrier endpoint to its exact pre-discriminator position"
                ),
                mechanic_ref=planned.mechanic_ref,
                plan_id=plan_id,
                plan_signature=planned.plan_signature,
                target_center=planned.target_center,
                mediator_color=untouched_support.child.mediator.color,
                arity=untouched_support.child.arity,
                expected_active_center=current_point,
                required_child_protected_raster_hash=(moved_certificate.protected_raster_hash),
                expected_child_protected_raster_hash=(restored_certificate.protected_raster_hash),
                expected_visible_endpoint_count=restored_certificate.visible_endpoint_count,
                expected_visible_mediator_count=restored_certificate.visible_mediator_count,
                required_carried_source_support_indexes=indexes,
                expected_carried_source_support_indexes=indexes,
                carrier_source_untouched_restoration_step=True,
            ),
            PlannedClick(
                coordinate=Coordinate(*prior_active_point),
                purpose=VisualActionPurpose.PROBE,
                expectation="restore the exact active endpoint role held before the discriminator",
                mechanic_ref=planned.mechanic_ref,
                plan_id=plan_id,
                plan_signature=planned.plan_signature,
                target_center=planned.target_center,
                mediator_color=untouched_support.child.mediator.color,
                arity=untouched_support.child.arity,
                expected_active_center=prior_active_point,
                required_child_protected_raster_hash=(restored_certificate.protected_raster_hash),
                expected_child_protected_raster_hash=final_certificate.protected_raster_hash,
                expected_visible_endpoint_count=final_certificate.visible_endpoint_count,
                expected_visible_mediator_count=final_certificate.visible_mediator_count,
                required_carried_source_support_indexes=indexes,
                expected_carried_source_support_indexes=indexes,
                carrier_source_untouched_restoration_step=True,
                completes_carrier_source_untouched_restoration=True,
            ),
        )

    stationary_indexes = tuple(sorted(carried))
    newly_carried_indexes = tuple(sorted(newly_carried))
    stationary_restoration = restoration_actions(
        indexes=stationary_indexes,
        moved_certificate=stationary_certificate,
        restored_certificate=stationary_restored_certificate,
        final_certificate=stationary_final_certificate,
    )
    newly_carried_restoration = restoration_actions(
        indexes=newly_carried_indexes,
        moved_certificate=newly_carried_certificate,
        restored_certificate=newly_carried_restored_certificate,
        final_certificate=newly_carried_final_certificate,
    )
    try:
        stationary_restoration = (
            require_exact_lineage(
                stationary_restoration[0],
                stationary_scene,
                required_indexes=stationary_indexes,
            ),
            require_exact_lineage(
                stationary_restoration[1],
                stationary_restored,
                required_indexes=stationary_indexes,
            ),
        )
        newly_carried_restoration = (
            require_exact_lineage(
                newly_carried_restoration[0],
                newly_carried_scene,
                required_indexes=newly_carried_indexes,
            ),
            require_exact_lineage(
                newly_carried_restoration[1],
                newly_carried_restored,
                required_indexes=newly_carried_indexes,
            ),
        )
    except ValueError:
        return ()
    alternative = PlannedClick(
        coordinate=Coordinate(*predecessor),
        purpose=VisualActionPurpose.PROGRESS,
        expectation=(
            "move the unique unresolved carrier lineage-last-moved endpoint to its exact "
            "historical predecessor and accept only stationary or carried projections"
        ),
        mechanic_ref=planned.mechanic_ref,
        plan_id=plan_id,
        plan_signature=planned.plan_signature,
        target_center=planned.target_center,
        mediator_color=untouched_support.child.mediator.color,
        arity=untouched_support.child.arity,
        expected_active_center=predecessor,
        required_child_protected_raster_hash=role_certificate.protected_raster_hash,
        expected_child_protected_raster_hash=newly_carried_certificate.protected_raster_hash,
        expected_visible_endpoint_count=newly_carried_certificate.visible_endpoint_count,
        expected_visible_mediator_count=newly_carried_certificate.visible_mediator_count,
        required_carried_source_support_indexes=stationary_indexes,
        expected_carried_source_support_indexes=newly_carried_indexes,
        carrier_source_untouched_discriminator_step=True,
        carrier_source_untouched_restoration_actions=newly_carried_restoration,
    )
    discriminator = PlannedClick(
        coordinate=Coordinate(*predecessor),
        purpose=VisualActionPurpose.PROGRESS,
        expectation=(
            "move the unique unresolved carrier lineage-last-moved endpoint to its exact "
            "historical predecessor and accept only stationary or carried projections"
        ),
        mechanic_ref=planned.mechanic_ref,
        plan_id=plan_id,
        plan_signature=planned.plan_signature,
        target_center=planned.target_center,
        mediator_color=untouched_support.child.mediator.color,
        arity=untouched_support.child.arity,
        expected_active_center=predecessor,
        required_child_protected_raster_hash=role_certificate.protected_raster_hash,
        expected_child_protected_raster_hash=stationary_certificate.protected_raster_hash,
        expected_visible_endpoint_count=stationary_certificate.visible_endpoint_count,
        expected_visible_mediator_count=stationary_certificate.visible_mediator_count,
        carrier_source_recovery_alternative=alternative,
        required_carried_source_support_indexes=stationary_indexes,
        expected_carried_source_support_indexes=stationary_indexes,
        carrier_source_untouched_discriminator_step=True,
        carrier_source_untouched_restoration_actions=stationary_restoration,
    )
    role_exchange = PlannedClick(
        coordinate=Coordinate(*current_point),
        purpose=VisualActionPurpose.PROBE,
        expectation=(
            "select the unique unresolved carrier lineage-last-moved endpoint while "
            "preserving the exact carried-source receipt"
        ),
        mechanic_ref=planned.mechanic_ref,
        plan_id=plan_id,
        plan_signature=planned.plan_signature,
        target_center=planned.target_center,
        mediator_color=untouched_support.child.mediator.color,
        arity=untouched_support.child.arity,
        expected_active_center=current_point,
        required_child_protected_raster_hash=baseline_certificate.protected_raster_hash,
        expected_child_protected_raster_hash=role_certificate.protected_raster_hash,
        expected_visible_endpoint_count=role_certificate.visible_endpoint_count,
        expected_visible_mediator_count=role_certificate.visible_mediator_count,
        required_carried_source_support_indexes=stationary_indexes,
        expected_carried_source_support_indexes=stationary_indexes,
        carrier_source_untouched_role_exchange_step=True,
    )
    try:
        role_exchange = require_exact_lineage(
            role_exchange,
            baseline_scene,
            required_indexes=stationary_indexes,
        )
        discriminator = require_exact_lineage(
            discriminator,
            role_scene,
            required_indexes=stationary_indexes,
        )
    except ValueError:
        return ()
    if not _carrier_source_untouched_role_exchange_step_is_compatible(
        role_exchange
    ) or not _carrier_source_untouched_discriminator_step_is_compatible(discriminator):
        return ()
    return role_exchange, discriminator


def _carrier_source_paired_cargo_target_supports(
    scene: VisualScene,
    hierarchy: _AffineHierarchy,
    supports: tuple[_HierarchySourceSupport, ...],
    *,
    level_index: int,
    rejected_external_relation_key: str,
) -> tuple[_HierarchyTargetSupport, ...] | None:
    """Rebind carried sources to the exact previously rejected external-chain sinks."""

    if (
        len(supports) != 2
        or tuple(item.child for item in supports) != hierarchy.children
        or len({item.example.carrier_color for item in supports}) != 1
        or not rejected_external_relation_key.startswith(
            "affine-external-residual-linked-relation:"
        )
    ):
        return None
    mixed = _residual_linked_hierarchy_relation(
        scene,
        hierarchy,
        level_index=level_index,
    )
    if mixed is None:
        return None
    external = _external_residual_linked_hierarchy_relation(
        scene,
        hierarchy,
        level_index=level_index,
        rejected_mixed_relation_keys={mixed.relation_key},
    )
    if (
        external is None
        or external.relation_key != rejected_external_relation_key
        or external.mixed_relation_key != mixed.relation_key
        or tuple(item.child for item in external.supports) != hierarchy.children
        or len({item.target.rounded_center for item in external.supports}) != 2
        or external.raw_source_center == external.counterpart_source_center
    ):
        return None

    target_by_child = {item.child: item for item in external.supports}
    result: list[_HierarchyTargetSupport] = []
    witnessed_roles: list[str] = []
    for support in supports:
        target_support = target_by_child.get(support.child)
        residual = support.source.palette - {support.example.carrier_color}
        if (
            target_support is None
            or target_support.example != support.example
            or sum(support.source == source for source in support.example.sources) != 1
            or not residual
            or support.source.offsets(support.example.carrier_color) != external.carrier_offsets
            or not target_support.target.cells
            or frozenset(scene.cells[y][x] for x, y in target_support.target.cells)
            != target_support.surface_signature
            or target_support.target.cells == support.example.target.cells
        ):
            return None
        if support.source.center == external.raw_source_center:
            if residual != frozenset({external.raw_color}):
                return None
            witnessed_roles.append("raw")
        elif support.source.center == external.counterpart_source_center:
            if residual != frozenset({external.external_link_color}):
                return None
            witnessed_roles.append("counterpart")
        else:
            return None
        result.append(target_support)
    if (
        tuple(witnessed_roles).count("raw") != 1
        or tuple(witnessed_roles).count("counterpart") != 1
        or tuple(item.child for item in result) != hierarchy.children
        or tuple(item.target.rounded_center for item in result)
        != tuple(item.target.rounded_center for item in external.supports)
    ):
        return None
    return tuple(result)


def _replay_carrier_source_actions(
    hierarchy: _AffineHierarchy,
    actions: tuple[PlannedClick, ...],
) -> tuple[dict[str, tuple[int, int]], dict[str, int]] | None:
    """Replay one finite observed action lineage without consulting game semantics."""

    positions = {
        endpoint.object_ref: endpoint.rounded_center
        for child in hierarchy.children
        for endpoint in child.endpoints
    }
    colors = {
        endpoint.object_ref: endpoint.color
        for child in hierarchy.children
        for endpoint in child.endpoints
    }
    for action in actions:
        active_refs = tuple(ref for ref, color in colors.items() if color == hierarchy.active_color)
        if len(active_refs) != 1:
            return None
        active_ref = active_refs[0]
        coordinate = (action.coordinate.x, action.coordinate.y)
        if action.purpose is VisualActionPurpose.PROBE:
            selected_refs = tuple(ref for ref, center in positions.items() if center == coordinate)
            if len(selected_refs) != 1 or selected_refs[0] == active_ref:
                return None
            selected_ref = selected_refs[0]
            colors[active_ref], colors[selected_ref] = colors[selected_ref], colors[active_ref]
        elif action.purpose is VisualActionPurpose.PROGRESS:
            positions[active_ref] = coordinate
        else:
            return None
    return positions, colors


def _carrier_source_replayed_attachment_state(
    context: _CarrierSourceAttachmentReplayContext,
    restored_scene: VisualScene,
    *,
    carried_indexes: tuple[int, ...],
) -> tuple[dict[str, tuple[int, int]], dict[str, int]] | None:
    """Recover the one exact endpoint state that projects to an observed attachment."""

    if tuple(sorted(set(carried_indexes))) != carried_indexes or frozenset(
        carried_indexes
    ) != frozenset(range(len(context.carrier_source_supports))):
        return None
    regenerated = _build_hierarchy_plan(
        context.hierarchy,
        context.layouts,
        scene=context.scene,
        move_order=context.move_order,
        support_weights=context.support_weights,
        carrier_source_supports=context.carrier_source_supports,
        carrier_source_level_index=context.level_index,
        carrier_source_rejected_external_relation_key=(
            context.rejected_external_residual_relation_key
        ),
        signature_prefix=context.signature_prefix,
        terminal_expectation=context.terminal_expectation,
        derive_carrier_source_attachment_continuations=True,
    )
    matches: dict[
        tuple[tuple[tuple[str, tuple[int, int]], ...], tuple[tuple[str, int], ...]],
        tuple[dict[str, tuple[int, int]], dict[str, int]],
    ] = {}
    for recovery_index, recovery in enumerate(regenerated.recovery_actions):
        for candidate in (recovery, *recovery.carrier_source_recovery_candidates):
            alternative = candidate.carrier_source_recovery_alternative
            if alternative is None or not alternative.carrier_source_delivery_actions:
                continue
            delivery = alternative.carrier_source_delivery_actions
            detachment = delivery[-1].carrier_source_detachment_probe
            if detachment is None or not detachment.carrier_source_attachment_continuation_actions:
                continue
            replayed = _replay_carrier_source_actions(
                context.hierarchy,
                (
                    *regenerated.actions,
                    *regenerated.recovery_actions[: recovery_index + 1],
                    *delivery,
                    detachment,
                    *detachment.carrier_source_attachment_continuation_actions,
                ),
            )
            if replayed is None:
                continue
            positions, colors = replayed
            try:
                projected = _carrier_source_carried_projected_scene(
                    context.scene,
                    context.hierarchy,
                    context.carrier_source_supports,
                    positions=positions,
                    colors=colors,
                    carried_support_indexes=frozenset(carried_indexes),
                )
            except ValueError:
                continue
            if (
                tuple(tuple(row[1:]) for row in projected.cells)
                != tuple(tuple(row[1:]) for row in restored_scene.cells)
                or len(projected.endpoints) != len(restored_scene.endpoints)
                or len(projected.mediators) != len(restored_scene.mediators)
            ):
                continue
            key = (tuple(sorted(positions.items())), tuple(sorted(colors.items())))
            matches[key] = (positions, colors)
    return next(iter(matches.values())) if len(matches) == 1 else None


def _carrier_source_paired_cargo_plan_after_observed_restoration(
    context: _CarrierSourceAttachmentReplayContext,
    restored_scene: VisualScene,
    *,
    carried_indexes: tuple[int, ...],
    rejected_signatures: set[str] | frozenset[str],
    include_terminal_role_handoff: bool = False,
    include_crossed_predecessor: bool = False,
    replayed_state: tuple[dict[str, tuple[int, int]], dict[str, int]] | None = None,
    crossed_delivery: bool = False,
) -> _HierarchyPlan | None:
    """Derive one reversible route to the rejected external-chain supports."""

    if (include_crossed_predecessor and not include_terminal_role_handoff) or crossed_delivery != (
        replayed_state is not None
    ):
        return None

    hierarchy = context.hierarchy
    source_supports = context.carrier_source_supports
    target_supports = _carrier_source_paired_cargo_target_supports(
        context.scene,
        hierarchy,
        source_supports,
        level_index=context.level_index,
        rejected_external_relation_key=context.rejected_external_residual_relation_key,
    )
    replayed = replayed_state or _carrier_source_replayed_attachment_state(
        context,
        restored_scene,
        carried_indexes=carried_indexes,
    )
    if target_supports is None or replayed is None:
        return None
    initial_positions, initial_colors = replayed
    carried = frozenset(carried_indexes)

    def project(
        positions: dict[str, tuple[int, int]],
        colors: dict[str, int],
    ) -> VisualScene | None:
        try:
            return _carrier_source_carried_projected_scene(
                context.scene,
                hierarchy,
                source_supports,
                positions=positions,
                colors=colors,
                carried_support_indexes=carried,
            )
        except ValueError:
            return None

    baseline = project(initial_positions, initial_colors)
    if baseline is None or tuple(tuple(row[1:]) for row in baseline.cells) != tuple(
        tuple(row[1:]) for row in restored_scene.cells
    ):
        return None

    def footprints(
        positions: dict[str, tuple[int, int]],
    ) -> tuple[
        tuple[frozenset[tuple[int, int]], ...],
        tuple[frozenset[tuple[int, int]], ...],
        tuple[tuple[frozenset[tuple[int, int]], ...], ...],
    ]:
        dynamics: list[frozenset[tuple[int, int]]] = []
        cargos: list[frozenset[tuple[int, int]]] = []
        endpoints: list[tuple[frozenset[tuple[int, int]], ...]] = []
        for support in source_supports:
            centers = tuple(positions[item.object_ref] for item in support.child.endpoints)
            mediator_center = (
                sum(point[0] for point in centers) // support.child.arity,
                sum(point[1] for point in centers) // support.child.arity,
            )
            dynamics.append(
                _hierarchy_projected_group_footprint(
                    support.child,
                    endpoint_centers=centers,
                    mediator_center=mediator_center,
                )
            )
            endpoints.append(
                tuple(
                    _translated_object_footprint(item, center=positions[item.object_ref])
                    for item in support.child.endpoints
                )
            )
            source_x, source_y = support.source.center
            cargos.append(
                frozenset(
                    (mediator_center[0] + x - source_x, mediator_center[1] + y - source_y)
                    for x, y in support.source.cells
                )
            )
        return tuple(dynamics), tuple(cargos), tuple(endpoints)

    baseline_dynamic, baseline_cargo, _baseline_endpoints = footprints(initial_positions)
    baseline_mutable = frozenset().union(*baseline_dynamic, *baseline_cargo)
    baseline_occupied = frozenset(
        (x, y)
        for y, row in enumerate(baseline.cells)
        for x, value in enumerate(row)
        if value != baseline.background
    )
    stationary_occupied = baseline_occupied - baseline_mutable
    endpoint_target_regions = _visible_target_regions(context.scene)
    sink_surfaces = {
        item.target.rounded_center: frozenset(item.target.cells) for item in target_supports
    }
    dynamic_target_regions = tuple(
        (center, sink_surfaces.get(center, region)) for center, region in endpoint_target_regions
    )
    sink_centers = frozenset(sink_surfaces)
    baseline_intrusions = {
        center: baseline_mutable & region for center, region in endpoint_target_regions
    }
    protected_target_surface = frozenset(
        cell
        for _center, region in endpoint_target_regions
        for cell in region
        if context.scene.cells[cell[1]][cell[0]] != context.scene.background
    )

    def raster_safe_state(
        positions: dict[str, tuple[int, int]],
        colors: dict[str, int],
    ) -> VisualScene | None:
        dynamics, cargos, endpoint_footprints = footprints(positions)
        moving = frozenset().union(*dynamics, *cargos)
        mutable = baseline_mutable | moving
        geometry_safe = bool(
            all(_hierarchy_cells_in_bounds(context.scene, item) for item in (*dynamics, *cargos))
            and not any(
                left & right
                for left, right in itertools.combinations(
                    tuple(dynamic | cargo for dynamic, cargo in zip(dynamics, cargos, strict=True)),
                    2,
                )
            )
            and not any(
                cargo & endpoint
                for cargo, group_endpoints in zip(cargos, endpoint_footprints, strict=True)
                for endpoint in group_endpoints
            )
            and not (moving & stationary_occupied)
            and all(
                (moving & region) <= baseline_intrusions[center]
                for center, region in endpoint_target_regions
                if center not in sink_centers
            )
        )
        if not geometry_safe:
            return None
        projected = project(positions, colors)
        if projected is None:
            return None
        raster_safe = bool(
            not any(
                projected.cells[y][x] != baseline.cells[y][x]
                for y in range(context.scene.height)
                for x in range(context.scene.width)
                if (x, y) not in mutable
            )
            and not any(
                projected.cells[y][x] != baseline.cells[y][x] for x, y in protected_target_surface
            )
        )
        return projected if raster_safe else None

    state_cache: dict[_BridgeProjectedStateKey, VisualScene | None] = {}

    def safe_state(
        positions: dict[str, tuple[int, int]],
        colors: dict[str, int],
    ) -> VisualScene | None:
        key: _BridgeProjectedStateKey = (
            tuple(sorted(positions.items())),
            tuple(sorted(colors.items())),
        )
        if key in state_cache:
            return state_cache[key]
        projected = raster_safe_state(positions, colors)
        if (
            projected is None
            or sum(item.color == hierarchy.active_color for item in projected.endpoints) != 1
        ):
            state_cache[key] = None
        else:
            state_cache[key] = projected
        return state_cache[key]

    observed_endpoint_positions = dict(initial_positions)

    def group_for_ref(endpoint_ref: str) -> _AffineChildGroup | None:
        matches = tuple(
            group
            for group in hierarchy.children
            if any(endpoint.object_ref == endpoint_ref for endpoint in group.endpoints)
        )
        return matches[0] if len(matches) == 1 else None

    def latent_crossed_boundary_state(
        positions: dict[str, tuple[int, int]],
        colors: dict[str, int],
        *,
        expected_active_ref: str,
    ) -> VisualScene | None:
        """Certify only the final carried boundary whose active shell is occluded.

        The exception is deliberately local to the crossed predecessor/delivery
        boundary.  It requires the exact observation-derived endpoint geometry,
        every certified carried support, one latent active identity, no visible
        active endpoint, and one active-colored parsed mediator containing that
        identity's translated shell.  The shell center is the one occluded cell;
        ordinary route states still require a visible active endpoint through
        ``safe_state``.
        """

        active_refs = tuple(ref for ref, color in colors.items() if color == hierarchy.active_color)
        active_group = group_for_ref(expected_active_ref)
        if (
            positions != observed_endpoint_positions
            or carried != frozenset(range(len(source_supports)))
            or active_refs != (expected_active_ref,)
            or active_group is None
        ):
            return None
        projected = raster_safe_state(positions, colors)
        if projected is None:
            return None
        active_endpoints = tuple(
            item for item in active_group.endpoints if item.object_ref == expected_active_ref
        )
        if len(active_endpoints) != 1:
            return None
        active_center = positions[expected_active_ref]
        active_shell = _translated_object_footprint(active_endpoints[0], center=active_center) - {
            active_center
        }
        if not active_shell:
            return None
        latent_mediators = tuple(
            item
            for item in projected.mediators
            if item.color == hierarchy.active_color
            and active_shell <= frozenset(item.cells)
            and active_center not in item.cells
        )
        if (
            any(item.color == hierarchy.active_color for item in projected.endpoints)
            or len(projected.endpoints) + 1 != len(observed_endpoint_positions)
            or len(latent_mediators) != 1
        ):
            return None
        return projected

    initial_active_refs = tuple(
        ref for ref, color in initial_colors.items() if color == hierarchy.active_color
    )
    initial_safe_state = safe_state(initial_positions, initial_colors)
    if initial_safe_state is None and (
        not crossed_delivery
        or len(initial_active_refs) != 1
        or latent_crossed_boundary_state(
            initial_positions,
            initial_colors,
            expected_active_ref=initial_active_refs[0],
        )
        is None
    ):
        return None
    search_budget = _HierarchySearchBudget(_MAX_HIERARCHY_SEARCH_BUDGET)
    layout_sets: list[tuple[_HierarchyChildLayout, ...]] = []
    try:
        for support in target_supports:
            layouts = _hierarchy_child_layouts(
                context.scene,
                hierarchy,
                support.child,
                support=support.target.rounded_center,
                active_ref=None,
                static_cells=stationary_occupied,
                target_regions=dynamic_target_regions,
                endpoint_target_regions=endpoint_target_regions,
                ignored_refs=frozenset(),
                search_budget=search_budget,
                result_limit=256,
            )
            layout_sets.append(
                tuple(
                    sorted(
                        layouts,
                        key=lambda item: (
                            item.radius,
                            sum(
                                _distance(initial_positions[mover.object_ref], point)
                                for mover, point in zip(item.movers, item.points, strict=True)
                            ),
                            item.points,
                            tuple(mover.object_ref for mover in item.movers),
                        ),
                    )
                )
            )
    except _HierarchySearchExhausted:
        return None
    if any(not items for items in layout_sets):
        return None

    type Transition = tuple[
        VisualActionPurpose,
        tuple[int, int],
        tuple[int, int],
        _AffineChildGroup,
        VisualScene,
        VisualScene,
    ]

    def apply_layout(
        layout: _HierarchyChildLayout,
        positions: dict[str, tuple[int, int]],
        colors: dict[str, int],
        active_ref: str,
        transitions: list[Transition],
    ) -> str | None:
        def required_state() -> VisualScene | None:
            observed = safe_state(positions, colors)
            if observed is not None:
                return observed
            if (
                crossed_delivery
                and not transitions
                and positions == initial_positions
                and colors == initial_colors
            ):
                return latent_crossed_boundary_state(
                    positions,
                    colors,
                    expected_active_ref=active_ref,
                )
            return None

        for mover, point in zip(layout.movers, layout.points, strict=True):
            mover_ref = mover.object_ref
            if mover_ref != active_ref:
                required_scene = required_state()
                if required_scene is None:
                    return None
                inverse_coordinate = positions[active_ref]
                coordinate = positions[mover_ref]
                colors[active_ref], colors[mover_ref] = colors[mover_ref], colors[active_ref]
                active_ref = mover_ref
                expected_scene = safe_state(positions, colors)
                if expected_scene is None:
                    return None
                transitions.append(
                    (
                        VisualActionPurpose.PROBE,
                        coordinate,
                        inverse_coordinate,
                        layout.group,
                        required_scene,
                        expected_scene,
                    )
                )
            required_scene = required_state()
            if required_scene is None or positions[active_ref] == point:
                return None
            inverse_coordinate = positions[active_ref]
            positions[active_ref] = point
            expected_scene = safe_state(positions, colors)
            if expected_scene is None:
                return None
            transitions.append(
                (
                    VisualActionPurpose.PROGRESS,
                    point,
                    inverse_coordinate,
                    layout.group,
                    required_scene,
                    expected_scene,
                )
            )
        return active_ref

    active_refs = tuple(
        ref for ref, color in initial_colors.items() if color == hierarchy.active_color
    )
    if len(active_refs) != 1:
        return None
    terminal_centers = tuple(support.target.rounded_center for support in target_supports)
    route_search_budget = _HierarchySearchBudget(_MAX_HIERARCHY_SEARCH_BUDGET)

    def search_layouts(
        child_order: tuple[int, ...],
        depth: int,
        positions: dict[str, tuple[int, int]],
        colors: dict[str, int],
        active_ref: str,
        layouts: tuple[_HierarchyChildLayout, ...],
        transitions: tuple[Transition, ...],
    ) -> tuple[tuple[_HierarchyChildLayout, ...], tuple[Transition, ...]] | None:
        if depth == len(child_order):
            observed_centers = tuple(
                (
                    sum(positions[item.object_ref][0] for item in support.child.endpoints)
                    // support.child.arity,
                    sum(positions[item.object_ref][1] for item in support.child.endpoints)
                    // support.child.arity,
                )
                for support in source_supports
            )
            if observed_centers != terminal_centers:
                return None
            by_child = {layout.group: layout for layout in layouts}
            return tuple(by_child[child] for child in hierarchy.children), transitions
        child_index = child_order[depth]
        for layout in layout_sets[child_index]:
            route_search_budget.consume(2 * len(layout.movers))
            next_positions = dict(positions)
            next_colors = dict(colors)
            next_transitions = list(transitions)
            next_active = apply_layout(
                layout,
                next_positions,
                next_colors,
                active_ref,
                next_transitions,
            )
            if next_active is None:
                continue
            selected = search_layouts(
                child_order,
                depth + 1,
                next_positions,
                next_colors,
                next_active,
                (*layouts, layout),
                tuple(next_transitions),
            )
            if selected is not None:
                return selected
        return None

    try:
        selected = next(
            (
                candidate
                for child_order in itertools.permutations(range(len(source_supports)))
                if (
                    candidate := search_layouts(
                        child_order,
                        0,
                        dict(initial_positions),
                        dict(initial_colors),
                        active_refs[0],
                        (),
                        (),
                    )
                )
                is not None
            ),
            None,
        )
    except _HierarchySearchExhausted:
        return None
    if selected is None:
        return None
    selected_layouts, transitions = selected
    identity = (
        context.rejected_external_residual_relation_key,
        tuple(sorted(initial_positions.items())),
        tuple(sorted(initial_colors.items())),
        tuple(
            (
                support.source.center,
                target_support.target.rounded_center,
                tuple(mover.object_ref for mover in layout.movers),
                layout.points,
            )
            for support, target_support, layout in zip(
                source_supports,
                target_supports,
                selected_layouts,
                strict=True,
            )
        ),
    )
    base_suffix = hashlib.sha256(repr(identity).encode("ascii")).hexdigest()[:24]
    base_signature = f"affine-carrier-source-occlusion-hierarchy-recovery:{base_suffix}"
    role_suffix = hashlib.sha256(
        repr((identity, "paired-terminal-active-role-handoff-v1")).encode("ascii")
    ).hexdigest()[:24]
    role_signature = f"affine-carrier-source-occlusion-hierarchy-recovery:{role_suffix}"
    if include_terminal_role_handoff and base_signature not in rejected_signatures:
        return None
    if include_crossed_predecessor and role_signature not in rejected_signatures:
        return None
    suffix = (
        hashlib.sha256(
            repr((identity, "paired-terminal-crossed-predecessor-v1")).encode("ascii")
        ).hexdigest()[:24]
        if include_crossed_predecessor
        else (
            hashlib.sha256(
                repr((identity, "paired-terminal-crossed-delivery-v1")).encode("ascii")
            ).hexdigest()[:24]
            if crossed_delivery
            else role_suffix
            if include_terminal_role_handoff
            else base_suffix
        )
    )
    signature = f"affine-carrier-source-occlusion-hierarchy-recovery:{suffix}"
    if signature in rejected_signatures:
        return None
    plan_id = (
        f"visual-carrier-source-paired-cargo-crossed-delivery:{suffix}"
        if crossed_delivery
        else f"visual-carrier-source-paired-cargo:{suffix}"
    )
    restoration_plan_id = f"visual-carrier-source-paired-cargo-restoration:{suffix}"

    def certificate(scene: VisualScene) -> _HierarchyRasterCertificate:
        return _HierarchyRasterCertificate(
            protected_raster_hash=_child_isolation_protected_raster_hash(scene),
            visible_endpoint_count=len(scene.endpoints),
            visible_mediator_count=len(scene.mediators),
        )

    forward: list[PlannedClick] = []
    restoration: list[PlannedClick] = []
    initial_boundary_hash = certificate(baseline).protected_raster_hash
    for index, (purpose, coordinate, _inverse, group, required_scene, expected_scene) in enumerate(
        transitions
    ):
        required = certificate(required_scene)
        expected = certificate(expected_scene)
        forward.append(
            PlannedClick(
                coordinate=Coordinate(*coordinate),
                purpose=purpose,
                expectation=(
                    "place both exact carried sources at the previously rejected "
                    "external-chain targets"
                    if index + 1 == len(transitions)
                    else "advance the exact paired-cargo route without expanding any residual"
                ),
                mechanic_ref=hierarchy.mechanic_ref,
                plan_id=plan_id,
                plan_signature=signature,
                target_center=hierarchy.target.rounded_center,
                mediator_color=group.mediator.color,
                arity=group.arity,
                expected_active_center=coordinate,
                required_child_protected_raster_hash=required.protected_raster_hash,
                expected_child_protected_raster_hash=expected.protected_raster_hash,
                expected_visible_endpoint_count=expected.visible_endpoint_count,
                expected_visible_mediator_count=expected.visible_mediator_count,
                required_visible_active_endpoint_count=(
                    0 if crossed_delivery and index == 0 and initial_safe_state is None else None
                ),
                required_carried_source_support_indexes=carried_indexes,
                expected_carried_source_support_indexes=carried_indexes,
                carrier_source_paired_cargo_step=not crossed_delivery,
                completes_carrier_source_paired_cargo=(
                    not crossed_delivery and index + 1 == len(transitions)
                ),
                carrier_source_paired_cargo_initial_protected_raster_hash=(initial_boundary_hash),
                carrier_source_paired_cargo_role_handoff_family=(include_terminal_role_handoff),
                carrier_source_paired_cargo_crossed_predecessor_family=(
                    include_crossed_predecessor
                ),
                carrier_source_paired_cargo_crossed_delivery_step=crossed_delivery,
                completes_carrier_source_paired_cargo_crossed_delivery=(
                    crossed_delivery and index + 1 == len(transitions)
                ),
            )
        )
    for index, (purpose, _coordinate, inverse, group, required_scene, expected_scene) in enumerate(
        reversed(transitions)
    ):
        required = certificate(expected_scene)
        expected = certificate(required_scene)
        restoration.append(
            PlannedClick(
                coordinate=Coordinate(*inverse),
                purpose=purpose,
                expectation="restore the exact pre-placement paired-cargo raster",
                mechanic_ref=hierarchy.mechanic_ref,
                plan_id=restoration_plan_id,
                plan_signature=signature,
                target_center=hierarchy.target.rounded_center,
                mediator_color=group.mediator.color,
                arity=group.arity,
                expected_active_center=inverse,
                required_child_protected_raster_hash=required.protected_raster_hash,
                expected_child_protected_raster_hash=expected.protected_raster_hash,
                expected_visible_endpoint_count=expected.visible_endpoint_count,
                expected_visible_mediator_count=expected.visible_mediator_count,
                required_carried_source_support_indexes=carried_indexes,
                expected_carried_source_support_indexes=carried_indexes,
                carrier_source_paired_cargo_initial_protected_raster_hash=(initial_boundary_hash),
                carrier_source_paired_cargo_restoration_step=True,
                completes_carrier_source_paired_cargo_restoration=(index + 1 == len(transitions)),
                carrier_source_paired_cargo_role_handoff_family=(include_terminal_role_handoff),
                carrier_source_paired_cargo_crossed_predecessor_family=(
                    include_crossed_predecessor
                ),
            )
        )
    role_handoff: PlannedClick | None = None
    crossed_delivery_context: _CarrierSourceCrossedDeliveryReplayContext | None = None
    if include_terminal_role_handoff:
        terminal_positions = dict(initial_positions)
        terminal_colors = dict(initial_colors)
        active_ref = active_refs[0]
        predecessor_by_ref: dict[str, str] = {}
        for purpose, coordinate, _inverse, _group, _required, _expected in transitions:
            if purpose is VisualActionPurpose.PROBE:
                selected_refs = tuple(
                    ref for ref, position in terminal_positions.items() if position == coordinate
                )
                if len(selected_refs) != 1 or selected_refs[0] == active_ref:
                    return None
                selected_ref = selected_refs[0]
                if selected_ref in predecessor_by_ref:
                    return None
                predecessor_by_ref[selected_ref] = active_ref
                terminal_colors[active_ref], terminal_colors[selected_ref] = (
                    terminal_colors[selected_ref],
                    terminal_colors[active_ref],
                )
                active_ref = selected_ref
            else:
                terminal_positions[active_ref] = coordinate
        current_active_refs = tuple(
            ref for ref, color in terminal_colors.items() if color == hierarchy.active_color
        )
        if len(current_active_refs) != 1 or current_active_refs[0] != active_ref:
            return None
        terminal_group = transitions[-1][3]
        complementary_groups = tuple(
            group for group in hierarchy.children if group != terminal_group
        )
        if len(complementary_groups) != 1:
            return None
        complementary_group = complementary_groups[0]
        complementary_progress = tuple(
            transition
            for transition in transitions
            if transition[0] is VisualActionPurpose.PROGRESS
            and transition[3] == complementary_group
        )
        if not complementary_progress:
            return None
        complementary_coordinate = complementary_progress[-1][1]
        complementary_refs = tuple(
            endpoint.object_ref
            for endpoint in complementary_group.endpoints
            if terminal_positions[endpoint.object_ref] == complementary_coordinate
        )
        if (
            len(complementary_refs) != 1
            or complementary_refs[0] == active_ref
            or terminal_colors[complementary_refs[0]] == hierarchy.active_color
        ):
            return None
        complementary_ref = complementary_refs[0]
        terminal_scene = safe_state(terminal_positions, terminal_colors)
        handoff_colors = dict(terminal_colors)
        handoff_colors[active_ref], handoff_colors[complementary_ref] = (
            handoff_colors[complementary_ref],
            handoff_colors[active_ref],
        )
        handoff_scene = safe_state(terminal_positions, handoff_colors)
        if terminal_scene is None or handoff_scene is None:
            return None
        terminal_certificate = certificate(terminal_scene)
        handoff_certificate = certificate(handoff_scene)
        crossed_predecessor: list[PlannedClick] = []
        if include_crossed_predecessor:
            if set(predecessor_by_ref) != set(initial_positions) or set(
                predecessor_by_ref.values()
            ) != set(initial_positions):
                return None
            crossed_positions = dict(terminal_positions)
            crossed_colors = dict(handoff_colors)
            crossed_active_ref = complementary_ref
            crossed_plan_id = f"visual-carrier-source-paired-cargo-crossed-predecessor:{suffix}"

            for _index in range(len(initial_positions)):
                predecessor_ref = predecessor_by_ref.get(crossed_active_ref)
                active_group = group_for_ref(crossed_active_ref)
                predecessor_group = (
                    group_for_ref(predecessor_ref) if predecessor_ref is not None else None
                )
                if (
                    predecessor_ref is None
                    or active_group is None
                    or predecessor_group is None
                    or crossed_positions[crossed_active_ref]
                    == initial_positions[crossed_active_ref]
                ):
                    return None
                crossed_required_scene: VisualScene | None = safe_state(
                    crossed_positions,
                    crossed_colors,
                )
                destination = initial_positions[crossed_active_ref]
                crossed_positions[crossed_active_ref] = destination
                crossed_expected_scene: VisualScene | None = safe_state(
                    crossed_positions,
                    crossed_colors,
                )
                if crossed_required_scene is None or crossed_expected_scene is None:
                    return None
                required = certificate(crossed_required_scene)
                expected = certificate(crossed_expected_scene)
                crossed_predecessor.append(
                    PlannedClick(
                        coordinate=Coordinate(*destination),
                        purpose=VisualActionPurpose.PROGRESS,
                        expectation=(
                            "restore one observation-derived predecessor position while "
                            "preserving the complementary active lineage"
                        ),
                        mechanic_ref=hierarchy.mechanic_ref,
                        plan_id=crossed_plan_id,
                        plan_signature=signature,
                        target_center=hierarchy.target.rounded_center,
                        mediator_color=active_group.mediator.color,
                        arity=active_group.arity,
                        expected_active_center=destination,
                        required_child_protected_raster_hash=required.protected_raster_hash,
                        expected_child_protected_raster_hash=expected.protected_raster_hash,
                        expected_visible_endpoint_count=expected.visible_endpoint_count,
                        expected_visible_mediator_count=expected.visible_mediator_count,
                        required_carried_source_support_indexes=carried_indexes,
                        expected_carried_source_support_indexes=carried_indexes,
                        carrier_source_paired_cargo_initial_protected_raster_hash=(
                            initial_boundary_hash
                        ),
                        carrier_source_paired_cargo_role_handoff_family=True,
                        carrier_source_paired_cargo_crossed_predecessor_family=True,
                        carrier_source_paired_cargo_crossed_predecessor_step=True,
                    )
                )
                crossed_required_scene = crossed_expected_scene
                selected_coordinate = crossed_positions[predecessor_ref]
                if predecessor_ref == crossed_active_ref:
                    return None
                crossed_colors[crossed_active_ref], crossed_colors[predecessor_ref] = (
                    crossed_colors[predecessor_ref],
                    crossed_colors[crossed_active_ref],
                )
                crossed_expected_scene = safe_state(
                    crossed_positions,
                    crossed_colors,
                )
                if (
                    crossed_expected_scene is None
                    and len(crossed_predecessor) + 1 == 2 * len(initial_positions)
                    and predecessor_ref == complementary_ref
                ):
                    crossed_expected_scene = latent_crossed_boundary_state(
                        crossed_positions,
                        crossed_colors,
                        expected_active_ref=predecessor_ref,
                    )
                if crossed_expected_scene is None:
                    return None
                required = certificate(crossed_required_scene)
                expected = certificate(crossed_expected_scene)
                crossed_predecessor.append(
                    PlannedClick(
                        coordinate=Coordinate(*selected_coordinate),
                        purpose=VisualActionPurpose.PROBE,
                        expectation=(
                            "follow the observed predecessor map without restoring the "
                            "pre-handoff role lineage"
                        ),
                        mechanic_ref=hierarchy.mechanic_ref,
                        plan_id=crossed_plan_id,
                        plan_signature=signature,
                        target_center=hierarchy.target.rounded_center,
                        mediator_color=predecessor_group.mediator.color,
                        arity=predecessor_group.arity,
                        expected_active_center=selected_coordinate,
                        required_child_protected_raster_hash=required.protected_raster_hash,
                        expected_child_protected_raster_hash=expected.protected_raster_hash,
                        expected_visible_endpoint_count=expected.visible_endpoint_count,
                        expected_visible_mediator_count=expected.visible_mediator_count,
                        required_carried_source_support_indexes=carried_indexes,
                        expected_carried_source_support_indexes=carried_indexes,
                        carrier_source_paired_cargo_initial_protected_raster_hash=(
                            initial_boundary_hash
                        ),
                        carrier_source_paired_cargo_role_handoff_family=True,
                        carrier_source_paired_cargo_crossed_predecessor_family=True,
                        carrier_source_paired_cargo_crossed_predecessor_step=True,
                        completes_carrier_source_paired_cargo_crossed_predecessor=(
                            len(crossed_predecessor) + 1 == 2 * len(initial_positions)
                        ),
                    )
                )
                crossed_active_ref = predecessor_ref
            if (
                crossed_positions != initial_positions
                or crossed_active_ref != complementary_ref
                or len(crossed_predecessor) != 2 * len(initial_positions)
            ):
                return None
            crossed_scene = latent_crossed_boundary_state(
                crossed_positions,
                crossed_colors,
                expected_active_ref=crossed_active_ref,
            )
            if crossed_scene is None:
                return None
            crossed_certificate = certificate(crossed_scene)
            delivery_preview = _carrier_source_paired_cargo_plan_after_observed_restoration(
                context,
                crossed_scene,
                carried_indexes=carried_indexes,
                rejected_signatures=set(rejected_signatures) | {signature},
                replayed_state=(dict(crossed_positions), dict(crossed_colors)),
                crossed_delivery=True,
            )
            if delivery_preview is None or not delivery_preview.actions:
                return None
            crossed_delivery_context = _CarrierSourceCrossedDeliveryReplayContext(
                attachment_context=context,
                carried_indexes=carried_indexes,
                positions=tuple(sorted(crossed_positions.items())),
                colors=tuple(sorted(crossed_colors.items())),
                protected_raster_hash=crossed_certificate.protected_raster_hash,
                visible_endpoint_count=crossed_certificate.visible_endpoint_count,
                visible_mediator_count=crossed_certificate.visible_mediator_count,
                delivery_plan_signature=delivery_preview.signature,
                delivery_action_count=len(delivery_preview.actions),
            )
        role_restoration = PlannedClick(
            coordinate=Coordinate(*terminal_positions[active_ref]),
            purpose=VisualActionPurpose.PROBE,
            expectation="restore the paired-terminal active endpoint before the exact inverse",
            mechanic_ref=hierarchy.mechanic_ref,
            plan_id=f"visual-carrier-source-paired-cargo-role-restoration:{suffix}",
            plan_signature=signature,
            target_center=hierarchy.target.rounded_center,
            mediator_color=terminal_group.mediator.color,
            arity=terminal_group.arity,
            expected_active_center=terminal_positions[active_ref],
            required_child_protected_raster_hash=handoff_certificate.protected_raster_hash,
            expected_child_protected_raster_hash=terminal_certificate.protected_raster_hash,
            expected_visible_endpoint_count=terminal_certificate.visible_endpoint_count,
            expected_visible_mediator_count=terminal_certificate.visible_mediator_count,
            required_carried_source_support_indexes=carried_indexes,
            expected_carried_source_support_indexes=carried_indexes,
            carrier_source_paired_cargo_initial_protected_raster_hash=initial_boundary_hash,
            carrier_source_paired_cargo_role_handoff_family=True,
            carrier_source_paired_cargo_role_restoration_step=True,
            carrier_source_paired_cargo_crossed_predecessor_family=(include_crossed_predecessor),
        )
        role_handoff = PlannedClick(
            coordinate=Coordinate(*complementary_coordinate),
            purpose=VisualActionPurpose.PROBE,
            expectation=(
                "handoff the paired-terminal active role to the complementary terminal endpoint"
            ),
            mechanic_ref=hierarchy.mechanic_ref,
            plan_id=f"visual-carrier-source-paired-cargo-role-handoff:{suffix}",
            plan_signature=signature,
            target_center=hierarchy.target.rounded_center,
            mediator_color=complementary_group.mediator.color,
            arity=complementary_group.arity,
            expected_active_center=complementary_coordinate,
            required_child_protected_raster_hash=terminal_certificate.protected_raster_hash,
            expected_child_protected_raster_hash=handoff_certificate.protected_raster_hash,
            expected_visible_endpoint_count=handoff_certificate.visible_endpoint_count,
            expected_visible_mediator_count=handoff_certificate.visible_mediator_count,
            required_carried_source_support_indexes=carried_indexes,
            expected_carried_source_support_indexes=carried_indexes,
            carrier_source_paired_cargo_initial_protected_raster_hash=initial_boundary_hash,
            carrier_source_paired_cargo_role_handoff_family=True,
            carrier_source_paired_cargo_role_handoff_step=True,
            carrier_source_paired_cargo_role_restoration_actions=(
                ()
                if include_crossed_predecessor
                else (
                    role_restoration,
                    *restoration,
                )
            ),
            carrier_source_paired_cargo_crossed_predecessor_family=(include_crossed_predecessor),
            carrier_source_paired_cargo_crossed_predecessor_actions=(tuple(crossed_predecessor)),
        )
    forward[-1] = replace(
        forward[-1],
        carrier_source_paired_cargo_restoration_actions=(
            () if crossed_delivery else tuple(restoration)
        ),
        carrier_source_paired_cargo_role_handoff=role_handoff,
    )
    return _HierarchyPlan(
        actions=tuple(forward),
        signature=signature,
        supports=tuple(item.target.rounded_center for item in target_supports),
        support_weights=tuple(1 for _item in target_supports),
        recovery_actions=tuple(restoration),
        carrier_source_attachment_replay_context=context,
        carrier_source_crossed_delivery_replay_context=crossed_delivery_context,
    )


def _carrier_source_attachment_context_key(
    context: _CarrierSourceAttachmentReplayContext,
) -> str:
    """Hash only the observed relation lineage needed after a fresh RESET."""

    identity = (
        context.level_index,
        context.hierarchy.mechanic_ref,
        context.rejected_external_residual_relation_key,
        tuple(
            (
                support.child.mediator.object_ref,
                tuple(endpoint.object_ref for endpoint in support.child.endpoints),
                support.source.center,
                tuple(sorted(support.source.palette)),
                tuple(sorted(support.source.cells)),
            )
            for support in context.carrier_source_supports
        ),
    )
    return (
        "carrier-source-replay:" + hashlib.sha256(repr(identity).encode("ascii")).hexdigest()[:24]
    )


def _carrier_source_attachment_setup_plan_signature(
    context: _CarrierSourceAttachmentReplayContext,
) -> str | None:
    """Regenerate the exact coordinate-free root-plan identity from its live context."""

    try:
        plan = _build_hierarchy_plan(
            context.hierarchy,
            context.layouts,
            scene=context.scene,
            move_order=context.move_order,
            support_weights=context.support_weights,
            carrier_source_supports=context.carrier_source_supports,
            carrier_source_level_index=context.level_index,
            carrier_source_rejected_external_relation_key=(
                context.rejected_external_residual_relation_key
            ),
            signature_prefix=context.signature_prefix,
            terminal_expectation=context.terminal_expectation,
        )
    except ValueError:
        return None
    return plan.signature


def _carrier_source_crossed_delivery_after_observed_predecessor(
    replay: _CarrierSourceCrossedDeliveryReplayContext,
    restored_scene: VisualScene,
    *,
    rejected_signatures: set[str] | frozenset[str],
) -> _HierarchyPlan | None:
    """Recompute one crossed delivery only after its boundary is exact."""

    if (
        _child_isolation_protected_raster_hash(restored_scene) != replay.protected_raster_hash
        or len(restored_scene.endpoints) != replay.visible_endpoint_count
        or len(restored_scene.mediators) != replay.visible_mediator_count
    ):
        return None
    positions = dict(replay.positions)
    colors = dict(replay.colors)
    endpoint_refs = {
        endpoint.object_ref
        for child in replay.attachment_context.hierarchy.children
        for endpoint in child.endpoints
    }
    if (
        set(positions) != endpoint_refs
        or set(colors) != endpoint_refs
        or sum(
            color == replay.attachment_context.hierarchy.active_color for color in colors.values()
        )
        != 1
    ):
        return None
    plan = _carrier_source_paired_cargo_plan_after_observed_restoration(
        replay.attachment_context,
        restored_scene,
        carried_indexes=replay.carried_indexes,
        rejected_signatures=rejected_signatures,
        replayed_state=(positions, colors),
        crossed_delivery=True,
    )
    if (
        plan is None
        or plan.signature != replay.delivery_plan_signature
        or len(plan.actions) != replay.delivery_action_count
    ):
        return None
    return plan


def _carrier_source_crossed_replay_action_budget(
    plan: _HierarchyPlan,
    *,
    rejected_signatures: set[str] | frozenset[str],
) -> int | None:
    """Bound the complete paired, handoff, predecessor, and delivery route."""

    replay = plan.carrier_source_crossed_delivery_replay_context
    if not plan.actions or replay is None:
        return None
    role_handoff = plan.actions[-1].carrier_source_paired_cargo_role_handoff
    if (
        role_handoff is None
        or not _carrier_source_paired_cargo_role_handoff_step_is_compatible(role_handoff)
        or not role_handoff.carrier_source_paired_cargo_crossed_predecessor_family
        or not _carrier_source_paired_cargo_crossed_predecessor_actions_are_compatible(role_handoff)
    ):
        return None
    predecessor = role_handoff.carrier_source_paired_cargo_crossed_predecessor_actions
    endpoint_refs = {
        endpoint.object_ref
        for child in replay.attachment_context.hierarchy.children
        for endpoint in child.endpoints
    }
    if (
        not endpoint_refs
        or set(dict(replay.positions)) != endpoint_refs
        or set(dict(replay.colors)) != endpoint_refs
        or replay.carried_indexes
        != tuple(range(len(replay.attachment_context.carrier_source_supports)))
        or plan.signature in rejected_signatures
    ):
        return None
    if replay.delivery_action_count <= 0 or not replay.delivery_plan_signature:
        return None
    return len(plan.actions) + 1 + len(predecessor) + replay.delivery_action_count


def _carrier_source_crossed_replay_action_budget_preview(
    context: _CarrierSourceAttachmentReplayContext,
    restored_scene: VisualScene,
    *,
    carried_indexes: tuple[int, ...],
) -> int | None:
    """Derive the exact later crossed budget while its fresh boundary is live."""

    base = _carrier_source_paired_cargo_plan_after_observed_restoration(
        context,
        restored_scene,
        carried_indexes=carried_indexes,
        rejected_signatures=set(),
    )
    if base is None:
        return None
    role = _carrier_source_paired_cargo_plan_after_observed_restoration(
        context,
        restored_scene,
        carried_indexes=carried_indexes,
        rejected_signatures={base.signature},
        include_terminal_role_handoff=True,
    )
    if role is None:
        return None
    crossed = _carrier_source_paired_cargo_plan_after_observed_restoration(
        context,
        restored_scene,
        carried_indexes=carried_indexes,
        rejected_signatures={base.signature, role.signature},
        include_terminal_role_handoff=True,
        include_crossed_predecessor=True,
    )
    if crossed is None:
        return None
    return _carrier_source_crossed_replay_action_budget(
        crossed,
        rejected_signatures={base.signature, role.signature},
    )


def _carrier_source_crossed_replay_context_endpoint_count(
    context: _CarrierSourceAttachmentReplayContext,
    *,
    carried_indexes: tuple[int, ...],
) -> int | None:
    """Count one exact all-carried endpoint lineage without route enumeration."""

    supports = context.carrier_source_supports
    endpoint_refs = tuple(
        endpoint.object_ref for child in context.hierarchy.children for endpoint in child.endpoints
    )
    if (
        not supports
        or carried_indexes != tuple(range(len(supports)))
        or not endpoint_refs
        or len(set(endpoint_refs)) != len(endpoint_refs)
    ):
        return None
    return len(endpoint_refs)


def _crossed_replay_action_budget_from_metadata(
    *,
    paired_action_count: int,
    predecessor_action_count: int,
    delivery_action_count: int,
) -> int | None:
    """Return the exact forward count from validated finite-plan metadata."""

    if paired_action_count <= 0 or predecessor_action_count <= 0 or delivery_action_count <= 0:
        return None
    return paired_action_count + 1 + predecessor_action_count + delivery_action_count


def _strict_crossed_replay_budget_closes(
    *,
    current_actions: int,
    route_action_upper_bound: int | None,
    exhausted_after_actions: int,
) -> bool:
    """Require every route action to finish strictly before learned exhaustion."""

    return bool(
        route_action_upper_bound is not None
        and current_actions >= 0
        and current_actions + route_action_upper_bound < exhausted_after_actions
    )


def _matching_resource_interrupted_paired_replay(
    replay: _ResourceInterruptedPairedReplay | None,
    *,
    level_index: int,
    context_key: str,
    reset_epoch: int,
    candidates: tuple[_EdgeResourceProgress, ...],
    current_actions: int,
) -> _EdgeResourceProgress | None:
    """Match a fresh life to the exact prefix learned from the exhausted life."""

    if (
        replay is None
        or replay.level_index != level_index
        or replay.context_key != context_key
        or replay.authorized_reset_epoch != reset_epoch
        or not replay.setup_replay_started
        or current_actions != replay.setup_action_count
        or len(replay.exhausted_filled_index_history) != replay.observed_actions
    ):
        return None
    return _matching_edge_resource_lineage(
        candidates,
        edge_index=replay.exhausted_edge_index,
        baseline=replay.exhausted_edge_baseline,
        fill_color=replay.exhausted_edge_fill_color,
        observed_actions=current_actions,
        exhausted_filled_index_history=replay.exhausted_filled_index_history,
    )


def _authorize_resource_interrupted_paired_replay(
    replay: _ResourceInterruptedPairedReplay | None,
    *,
    level_index: int,
    context_key: str,
    reset_epoch: int,
    candidates: tuple[_EdgeResourceProgress, ...],
    current_actions: int,
    forward_remaining_actions: int | None,
) -> _ActiveCrossedReplayResourceLineage | None:
    """Consume one exact-prefix token using the validated plan's exact count."""

    current_resource = _matching_resource_interrupted_paired_replay(
        replay,
        level_index=level_index,
        context_key=context_key,
        reset_epoch=reset_epoch,
        candidates=candidates,
        current_actions=current_actions,
    )
    if (
        replay is None
        or current_resource is None
        or forward_remaining_actions != replay.crossed_forward_action_count
        or not _strict_crossed_replay_budget_closes(
            current_actions=current_actions,
            route_action_upper_bound=forward_remaining_actions,
            exhausted_after_actions=replay.observed_actions,
        )
    ):
        return None
    assert forward_remaining_actions is not None
    return _ActiveCrossedReplayResourceLineage(
        level_index=replay.level_index,
        context_key=replay.context_key,
        edge_index=current_resource.edge_index,
        edge_baseline=current_resource.baseline,
        edge_fill_color=current_resource.fill_color,
        exhausted_filled_index_history=replay.exhausted_filled_index_history,
        exhausted_after_actions=replay.observed_actions,
        reset_epoch=reset_epoch,
        forward_remaining_actions=forward_remaining_actions,
    )


def _is_crossed_replay_forward_action(planned: PlannedClick) -> bool:
    """Identify only actions in the consumed token's exact forward family."""

    return bool(
        planned.carrier_source_paired_cargo_crossed_delivery_step
        or (
            planned.carrier_source_paired_cargo_crossed_predecessor_family
            and (
                planned.carrier_source_paired_cargo_step
                or planned.carrier_source_paired_cargo_role_handoff_step
                or planned.carrier_source_paired_cargo_crossed_predecessor_step
            )
        )
    )


def _is_crossed_replay_inverse_action(
    planned: PlannedClick,
    *,
    recovery_signature: str | None,
) -> bool:
    """Identify one exact inverse action issued only after crossed delivery."""

    return bool(
        recovery_signature is not None
        and planned.plan_signature == recovery_signature
        and planned.carrier_source_paired_cargo_restoration_step
        and not _is_crossed_replay_forward_action(planned)
    )


def _post_deposit_mediator_access_step_is_compatible(planned: PlannedClick) -> bool:
    """Validate the closed, observation-derived shape of one access probe."""

    certificate = planned.post_deposit_mediator_access_certificate
    return bool(
        certificate is not None
        and planned.plan_signature.startswith("affine-crossed-post-deposit-mediator-access:")
        and planned.coordinate == Coordinate(*certificate.mediator_signature[0])
        and planned.target_center == certificate.mediator_signature[0]
        and planned.mediator_color == certificate.mediator_signature[1]
        and planned.arity == 1
        and planned.required_child_protected_raster_hash == certificate.protected_raster_hash
        and certificate.visible_endpoint_count > 0
        and certificate.resource_action_count >= 0
        and certificate.resource_action_count + 1 < certificate.exhausted_after_actions
        and not planned.carrier_source_paired_cargo_crossed_delivery_step
        and not planned.carrier_source_paired_cargo_restoration_step
    )


def _post_deposit_mediator_access_plan(
    before_scene: VisualScene,
    returned_scene: VisualScene,
    *,
    target_center: tuple[int, int] | None,
    crossed_delivery_plan_signature: str | None,
    recovery_actions: tuple[PlannedClick, ...],
    resource_lineage: _ActiveCrossedReplayResourceLineage | None,
    current_actions: int,
    excluded_hypothesis_keys: set[str] | frozenset[str],
) -> PlannedClick | None:
    """Derive one access test from a unique target-to-mediator transition.

    The target identity, click coordinate, and resource limit all come from the
    returned observation and the already-consumed crossed replay token.  The
    active resource lineage is already bound to the observed episode prefix;
    the new discriminator consumes only one action strictly before its learned
    failure boundary.
    """

    prior_targets = tuple(
        target for target in before_scene.targets if target.rounded_center == target_center
    )
    if (
        target_center is None
        or crossed_delivery_plan_signature is None
        or len(prior_targets) != 1
        or returned_scene.targets
        or len(returned_scene.mediators) != 1
        or not recovery_actions
        or resource_lineage is None
        or resource_lineage.forward_remaining_actions != 0
        or not _strict_crossed_replay_budget_closes(
            current_actions=current_actions,
            route_action_upper_bound=1,
            exhausted_after_actions=resource_lineage.exhausted_after_actions,
        )
    ):
        return None

    prior_target = prior_targets[0]
    mediator = returned_scene.mediators[0]
    if (
        mediator.rounded_center != target_center
        or mediator.color != prior_target.color
        or (mediator.min_x, mediator.min_y, mediator.max_x, mediator.max_y)
        != (prior_target.min_x, prior_target.min_y, prior_target.max_x, prior_target.max_y)
    ):
        return None

    mediator_signature = _visual_object_state_signature(mediator)
    protected_raster_hash = _child_isolation_protected_raster_hash(returned_scene)
    identity = (
        crossed_delivery_plan_signature,
        prior_target.color,
        (prior_target.min_x, prior_target.min_y, prior_target.max_x, prior_target.max_y),
        mediator_signature,
        protected_raster_hash,
        len(returned_scene.endpoints),
        current_actions,
        resource_lineage.exhausted_after_actions,
    )
    digest = hashlib.sha256(repr(identity).encode("ascii")).hexdigest()[:24]
    hypothesis_key = f"post-deposit-mediator-access:{digest}"
    if hypothesis_key in excluded_hypothesis_keys:
        return None
    certificate = _PostDepositMediatorAccessCertificate(
        hypothesis_key=hypothesis_key,
        mediator_signature=mediator_signature,
        protected_raster_hash=protected_raster_hash,
        visible_endpoint_count=len(returned_scene.endpoints),
        resource_action_count=current_actions,
        exhausted_after_actions=resource_lineage.exhausted_after_actions,
    )
    planned = PlannedClick(
        coordinate=Coordinate(*mediator.rounded_center),
        purpose=VisualActionPurpose.PROBE,
        expectation=(
            "test whether the unique post-deposit mediator is an access or completion control"
        ),
        mechanic_ref="visual-post-deposit-mediator-access",
        plan_id=f"visual-post-deposit-mediator-access:{digest}",
        plan_signature=f"affine-crossed-post-deposit-mediator-access:{digest}",
        target_center=mediator.rounded_center,
        mediator_color=mediator.color,
        arity=1,
        required_child_protected_raster_hash=protected_raster_hash,
        post_deposit_mediator_access_certificate=certificate,
    )
    return planned if _post_deposit_mediator_access_step_is_compatible(planned) else None


def _post_access_composite_exit_step_is_compatible(planned: PlannedClick) -> bool:
    """Validate one exact action on a newly formed mediator-target composite."""

    certificate = planned.post_access_composite_exit_certificate
    return bool(
        certificate is not None
        and planned.plan_signature.startswith("affine-crossed-post-access-composite-exit:")
        and planned.coordinate == Coordinate(*certificate.common_center)
        and planned.target_center == certificate.common_center
        and planned.mediator_color == certificate.mediator_signature[1]
        and planned.arity == 1
        and planned.required_child_protected_raster_hash == certificate.protected_raster_hash
        and certificate.parent_visible_endpoint_count == certificate.visible_endpoint_count + 1
        and certificate.visible_endpoint_count > 0
        and certificate.parent_protected_raster_hash != certificate.protected_raster_hash
        and certificate.resource_action_count > 0
        and certificate.resource_action_count + 1 < certificate.exhausted_after_actions
        and planned.post_deposit_mediator_access_certificate is None
        and not planned.carrier_source_paired_cargo_crossed_delivery_step
        and not planned.carrier_source_paired_cargo_restoration_step
    )


def _unique_post_access_composite(
    scene: VisualScene,
) -> tuple[VisualObject, VisualObject, tuple[int, int]] | None:
    """Return one co-centered, visibly overlapping mediator-target pair."""

    if len(scene.mediators) != 1 or len(scene.targets) != 1:
        return None
    mediator = scene.mediators[0]
    target = scene.targets[0]
    common_center = mediator.rounded_center
    boxes_overlap = bool(
        max(mediator.min_x, target.min_x) <= min(mediator.max_x, target.max_x)
        and max(mediator.min_y, target.min_y) <= min(mediator.max_y, target.max_y)
    )
    center_is_contained = bool(
        mediator.min_x <= common_center[0] <= mediator.max_x
        and mediator.min_y <= common_center[1] <= mediator.max_y
        and target.min_x <= common_center[0] <= target.max_x
        and target.min_y <= common_center[1] <= target.max_y
    )
    if target.rounded_center != common_center or not boxes_overlap or not center_is_contained:
        return None
    return mediator, target, common_center


def _post_access_composite_exit_plan(
    before_scene: VisualScene,
    returned_scene: VisualScene,
    *,
    access_certificate: _PostDepositMediatorAccessCertificate | None,
    resource_lineage: _ActiveCrossedReplayResourceLineage | None,
    current_actions: int,
    excluded_hypothesis_keys: set[str] | frozenset[str],
) -> PlannedClick | None:
    """Derive one exit test from the exact effect of a submitted access action."""

    if (
        access_certificate is None
        or len(before_scene.endpoints) != access_certificate.visible_endpoint_count
        or before_scene.targets
        or len(before_scene.mediators) != 1
        or _visual_object_state_signature(before_scene.mediators[0])
        != access_certificate.mediator_signature
        or _child_isolation_protected_raster_hash(before_scene)
        != access_certificate.protected_raster_hash
        or len(returned_scene.endpoints) != access_certificate.visible_endpoint_count - 1
        or resource_lineage is None
        or resource_lineage.forward_remaining_actions != 0
        or resource_lineage.exhausted_after_actions != access_certificate.exhausted_after_actions
        or current_actions != access_certificate.resource_action_count + 1
        or not _strict_crossed_replay_budget_closes(
            current_actions=current_actions,
            route_action_upper_bound=1,
            exhausted_after_actions=resource_lineage.exhausted_after_actions,
        )
    ):
        return None

    composite = _unique_post_access_composite(returned_scene)
    if composite is None:
        return None
    mediator, target, common_center = composite
    if _visual_object_state_signature(mediator) == access_certificate.mediator_signature:
        return None

    mediator_signature = _visual_object_state_signature(mediator)
    target_signature = _visual_object_state_signature(target)
    protected_raster_hash = _child_isolation_protected_raster_hash(returned_scene)
    identity = (
        access_certificate.hypothesis_key,
        access_certificate.protected_raster_hash,
        protected_raster_hash,
        mediator_signature,
        target_signature,
        len(returned_scene.endpoints),
        current_actions,
        resource_lineage.exhausted_after_actions,
    )
    digest = hashlib.sha256(repr(identity).encode("ascii")).hexdigest()[:24]
    hypothesis_key = f"post-access-composite-exit:{digest}"
    if hypothesis_key in excluded_hypothesis_keys:
        return None
    certificate = _PostAccessCompositeExitCertificate(
        hypothesis_key=hypothesis_key,
        parent_access_hypothesis_key=access_certificate.hypothesis_key,
        common_center=common_center,
        mediator_signature=mediator_signature,
        target_signature=target_signature,
        protected_raster_hash=protected_raster_hash,
        parent_protected_raster_hash=access_certificate.protected_raster_hash,
        visible_endpoint_count=len(returned_scene.endpoints),
        parent_visible_endpoint_count=access_certificate.visible_endpoint_count,
        resource_action_count=current_actions,
        exhausted_after_actions=resource_lineage.exhausted_after_actions,
    )
    planned = PlannedClick(
        coordinate=Coordinate(*common_center),
        purpose=VisualActionPurpose.PROBE,
        expectation=(
            "test whether the newly formed post-access mediator-target composite has a "
            "distinct exit or completion transition"
        ),
        mechanic_ref="visual-post-access-composite-exit",
        plan_id=f"visual-post-access-composite-exit:{digest}",
        plan_signature=f"affine-crossed-post-access-composite-exit:{digest}",
        target_center=common_center,
        mediator_color=mediator.color,
        arity=1,
        required_child_protected_raster_hash=protected_raster_hash,
        post_access_composite_exit_certificate=certificate,
    )
    return planned if _post_access_composite_exit_step_is_compatible(planned) else None


def _unique_post_access_composite_marker(
    scene: VisualScene,
) -> tuple[int, tuple[int, int]] | None:
    """Return one endpoint-marker-colored cell embedded in the composite bounds."""

    composite = _unique_post_access_composite(scene)
    if composite is None or not scene.endpoints:
        return None
    mediator, target, common_center = composite
    marker_colors = {
        endpoint.center_cell
        for endpoint in scene.endpoints
        if endpoint.center_cell not in {scene.background, endpoint.color}
    }
    if len(marker_colors) != 1:
        return None
    marker_color = next(iter(marker_colors))
    min_x = max(mediator.min_x, target.min_x)
    max_x = min(mediator.max_x, target.max_x)
    min_y = max(mediator.min_y, target.min_y)
    max_y = min(mediator.max_y, target.max_y)
    marker_cells = tuple(
        (x, y)
        for y in range(min_y, max_y + 1)
        for x in range(min_x, max_x + 1)
        if scene.cells[y][x] == marker_color
    )
    if len(marker_cells) != 1 or marker_cells[0] == common_center:
        return None
    return marker_color, marker_cells[0]


def _post_access_composite_marker_step_is_compatible(planned: PlannedClick) -> bool:
    """Validate one marker action after the exact common-center no-op."""

    certificate = planned.post_access_composite_marker_certificate
    return bool(
        certificate is not None
        and planned.plan_signature.startswith("affine-crossed-post-access-composite-marker:")
        and planned.coordinate == Coordinate(*certificate.marker_coordinate)
        and planned.target_center == certificate.marker_coordinate
        and planned.mediator_color == certificate.marker_color
        and planned.arity == 1
        and planned.required_child_protected_raster_hash == certificate.protected_raster_hash
        and certificate.marker_coordinate != certificate.common_center
        and certificate.parent_protected_raster_hash == certificate.protected_raster_hash
        and certificate.parent_resource_action_count + 1 == certificate.resource_action_count
        and certificate.resource_action_count > 0
        and certificate.resource_action_count + 1 < certificate.exhausted_after_actions
        and planned.post_deposit_mediator_access_certificate is None
        and planned.post_access_composite_exit_certificate is None
        and not planned.carrier_source_paired_cargo_crossed_delivery_step
        and not planned.carrier_source_paired_cargo_restoration_step
    )


def _post_access_composite_marker_plan(
    before_scene: VisualScene,
    returned_scene: VisualScene,
    *,
    composite_certificate: _PostAccessCompositeExitCertificate | None,
    resource_lineage: _ActiveCrossedReplayResourceLineage | None,
    current_actions: int,
    excluded_hypothesis_keys: set[str] | frozenset[str],
) -> PlannedClick | None:
    """Derive one embedded-marker test from an exact common-center no-op."""

    if (
        composite_certificate is None
        or resource_lineage is None
        or resource_lineage.forward_remaining_actions != 0
        or resource_lineage.exhausted_after_actions != composite_certificate.exhausted_after_actions
        or current_actions != composite_certificate.resource_action_count + 1
        or not _strict_crossed_replay_budget_closes(
            current_actions=current_actions,
            route_action_upper_bound=1,
            exhausted_after_actions=resource_lineage.exhausted_after_actions,
        )
    ):
        return None
    before_composite = _unique_post_access_composite(before_scene)
    returned_composite = _unique_post_access_composite(returned_scene)
    if (
        before_composite is None
        or returned_composite is None
        or before_composite[2] != composite_certificate.common_center
        or returned_composite[2] != composite_certificate.common_center
        or _visual_object_state_signature(before_composite[0])
        != composite_certificate.mediator_signature
        or _visual_object_state_signature(before_composite[1])
        != composite_certificate.target_signature
        or _visual_object_state_signature(returned_composite[0])
        != composite_certificate.mediator_signature
        or _visual_object_state_signature(returned_composite[1])
        != composite_certificate.target_signature
        or _endpoint_state_signature(before_scene.endpoints)
        != _endpoint_state_signature(returned_scene.endpoints)
        or len(returned_scene.endpoints) != composite_certificate.visible_endpoint_count
    ):
        return None
    before_protected_raster_hash = _child_isolation_protected_raster_hash(before_scene)
    protected_raster_hash = _child_isolation_protected_raster_hash(returned_scene)
    if not (
        before_protected_raster_hash
        == protected_raster_hash
        == composite_certificate.protected_raster_hash
    ):
        return None
    marker = _unique_post_access_composite_marker(returned_scene)
    if marker is None:
        return None
    marker_color, marker_coordinate = marker
    endpoint_signature = _endpoint_state_signature(returned_scene.endpoints)
    identity = (
        composite_certificate.parent_access_hypothesis_key,
        composite_certificate.hypothesis_key,
        composite_certificate.common_center,
        marker_coordinate,
        marker_color,
        composite_certificate.mediator_signature,
        composite_certificate.target_signature,
        endpoint_signature,
        before_protected_raster_hash,
        protected_raster_hash,
        composite_certificate.resource_action_count,
        current_actions,
        resource_lineage.exhausted_after_actions,
    )
    digest = hashlib.sha256(repr(identity).encode("ascii")).hexdigest()[:24]
    hypothesis_key = f"post-access-composite-marker:{digest}"
    if hypothesis_key in excluded_hypothesis_keys:
        return None
    certificate = _PostAccessCompositeMarkerCertificate(
        hypothesis_key=hypothesis_key,
        parent_access_hypothesis_key=composite_certificate.parent_access_hypothesis_key,
        parent_composite_hypothesis_key=composite_certificate.hypothesis_key,
        common_center=composite_certificate.common_center,
        marker_coordinate=marker_coordinate,
        marker_color=marker_color,
        mediator_signature=composite_certificate.mediator_signature,
        target_signature=composite_certificate.target_signature,
        endpoint_signature=endpoint_signature,
        protected_raster_hash=protected_raster_hash,
        parent_protected_raster_hash=before_protected_raster_hash,
        parent_resource_action_count=composite_certificate.resource_action_count,
        resource_action_count=current_actions,
        exhausted_after_actions=resource_lineage.exhausted_after_actions,
    )
    planned = PlannedClick(
        coordinate=Coordinate(*marker_coordinate),
        purpose=VisualActionPurpose.PROBE,
        expectation=(
            "test whether the unique endpoint-marker-colored cell exposed inside the "
            "post-access composite has a distinct access or completion transition"
        ),
        mechanic_ref="visual-post-access-composite-marker",
        plan_id=f"visual-post-access-composite-marker:{digest}",
        plan_signature=f"affine-crossed-post-access-composite-marker:{digest}",
        target_center=marker_coordinate,
        mediator_color=marker_color,
        arity=1,
        required_child_protected_raster_hash=protected_raster_hash,
        post_access_composite_marker_certificate=certificate,
    )
    return planned if _post_access_composite_marker_step_is_compatible(planned) else None


def _carrier_source_recovery_consequence_alternative_is_compatible(
    planned: PlannedClick,
    alternative: PlannedClick,
) -> bool:
    """Allow only one newly carried support to differ in an exact consequence."""

    required_indexes = frozenset(planned.required_carried_source_support_indexes)
    expected_indexes = frozenset(planned.expected_carried_source_support_indexes)
    alternative_required_indexes = frozenset(alternative.required_carried_source_support_indexes)
    alternative_expected_indexes = frozenset(alternative.expected_carried_source_support_indexes)
    return bool(
        planned.plan_signature.startswith("affine-carrier-source-occlusion-hierarchy-recovery:")
        and alternative.carrier_source_recovery_alternative is None
        and not alternative.carrier_source_recovery_candidates
        and _carrier_source_recovery_action_signature(alternative)
        == _carrier_source_recovery_action_signature(planned)
        and alternative.required_child_protected_raster_hash
        == planned.required_child_protected_raster_hash
        and alternative.required_child_raster_signature == planned.required_child_raster_signature
        and alternative.required_visible_active_endpoint_count
        == planned.required_visible_active_endpoint_count
        and alternative_required_indexes == required_indexes == expected_indexes
        and len(alternative_expected_indexes - expected_indexes) == 1
        and expected_indexes < alternative_expected_indexes
        and alternative.expected_child_protected_raster_hash is not None
        and alternative.expected_visible_endpoint_count is not None
        and alternative.expected_visible_mediator_count is not None
        and (
            not alternative.carrier_source_delivery_actions
            or _carrier_source_delivery_actions_are_compatible(alternative)
        )
    )


def _carrier_source_untouched_role_exchange_step_is_compatible(
    planned: PlannedClick,
) -> bool:
    """Require the observation-derived role selection that opens one discriminator."""

    required_indexes = planned.required_carried_source_support_indexes
    return bool(
        planned.carrier_source_untouched_role_exchange_step
        and planned.plan_id.startswith("visual-carrier-source-untouched:")
        and planned.plan_signature.startswith("affine-carrier-source-occlusion-hierarchy-recovery:")
        and planned.purpose is VisualActionPurpose.PROBE
        and planned.carrier_source_recovery_alternative is None
        and not planned.carrier_source_recovery_candidates
        and not planned.carrier_source_delivery_actions
        and planned.carrier_source_detachment_probe is None
        and not planned.carrier_source_detachment_step
        and not planned.carrier_source_target_center_role_exchange_step
        and not planned.carrier_source_attachment_continuation_actions
        and not planned.carrier_source_untouched_discriminator_step
        and not planned.carrier_source_untouched_restoration_actions
        and not planned.carrier_source_untouched_restoration_step
        and not planned.completes_carrier_source_untouched_restoration
        and required_indexes
        and tuple(sorted(set(required_indexes))) == required_indexes
        and planned.expected_carried_source_support_indexes == required_indexes
        and planned.required_child_protected_raster_hash is not None
        and planned.expected_child_protected_raster_hash is not None
        and planned.expected_visible_endpoint_count is not None
        and planned.expected_visible_mediator_count is not None
        and planned.expected_active_center == (planned.coordinate.x, planned.coordinate.y)
        and not planned.carrier_source_delivery_step
        and not planned.completes_carrier_source_delivery
        and not planned.completes_hierarchy
        and not planned.completes_child_isolation
        and not planned.completes_child_recovery
        and not planned.completes_local_target
        and not planned.stages_for_switch
        and planned.expected_deposited_source_protected_raster_hash is None
        and planned.expected_deposited_visible_endpoint_count is None
        and planned.expected_deposited_visible_mediator_count is None
    )


def _carrier_source_untouched_restoration_step_is_compatible(
    planned: PlannedClick,
) -> bool:
    """Require one exact branch-preserving move or role restoration."""

    required_indexes = planned.required_carried_source_support_indexes
    return bool(
        planned.carrier_source_untouched_restoration_step
        and planned.plan_id.startswith("visual-carrier-source-untouched:")
        and planned.plan_signature.startswith("affine-carrier-source-occlusion-hierarchy-recovery:")
        and planned.purpose in {VisualActionPurpose.PROGRESS, VisualActionPurpose.PROBE}
        and planned.carrier_source_recovery_alternative is None
        and not planned.carrier_source_recovery_candidates
        and not planned.carrier_source_delivery_actions
        and planned.carrier_source_detachment_probe is None
        and not planned.carrier_source_detachment_step
        and not planned.carrier_source_target_center_role_exchange_step
        and not planned.carrier_source_attachment_continuation_actions
        and not planned.carrier_source_untouched_role_exchange_step
        and not planned.carrier_source_untouched_discriminator_step
        and not planned.carrier_source_untouched_restoration_actions
        and required_indexes
        and tuple(sorted(set(required_indexes))) == required_indexes
        and planned.expected_carried_source_support_indexes == required_indexes
        and planned.required_child_protected_raster_hash is not None
        and planned.expected_child_protected_raster_hash is not None
        and planned.expected_visible_endpoint_count is not None
        and planned.expected_visible_mediator_count is not None
        and planned.expected_active_center == (planned.coordinate.x, planned.coordinate.y)
        and not planned.carrier_source_delivery_step
        and not planned.completes_carrier_source_delivery
        and not planned.completes_hierarchy
        and not planned.completes_child_isolation
        and not planned.completes_child_recovery
        and not planned.completes_local_target
        and not planned.stages_for_switch
        and planned.expected_deposited_source_protected_raster_hash is None
        and planned.expected_deposited_visible_endpoint_count is None
        and planned.expected_deposited_visible_mediator_count is None
        and (
            planned.completes_carrier_source_untouched_restoration
            == (planned.purpose is VisualActionPurpose.PROBE)
        )
    )


def _carrier_source_untouched_restoration_actions_are_compatible(
    planned: PlannedClick,
) -> bool:
    """Validate the exact inverse move and prior-role restoration for one branch."""

    actions = planned.carrier_source_untouched_restoration_actions
    expected_indexes = planned.expected_carried_source_support_indexes
    return bool(
        len(actions) == 2
        and actions[0].purpose is VisualActionPurpose.PROGRESS
        and actions[1].purpose is VisualActionPurpose.PROBE
        and not actions[0].completes_carrier_source_untouched_restoration
        and actions[1].completes_carrier_source_untouched_restoration
        and all(_carrier_source_untouched_restoration_step_is_compatible(item) for item in actions)
        and all(item.plan_id == planned.plan_id for item in actions)
        and all(item.plan_signature == planned.plan_signature for item in actions)
        and all(item.mechanic_ref == planned.mechanic_ref for item in actions)
        and all(item.target_center == planned.target_center for item in actions)
        and all(item.mediator_color == planned.mediator_color for item in actions)
        and all(item.arity == planned.arity for item in actions)
        and all(
            item.required_carried_source_support_indexes == expected_indexes for item in actions
        )
        and actions[0].required_child_protected_raster_hash
        == planned.expected_child_protected_raster_hash
        and actions[0].expected_child_protected_raster_hash
        == actions[1].required_child_protected_raster_hash
    )


def _carrier_source_untouched_discriminator_step_is_compatible(
    planned: PlannedClick,
) -> bool:
    """Require exactly two projected outcomes and a closed restoration per outcome."""

    alternative = planned.carrier_source_recovery_alternative
    required_indexes = planned.required_carried_source_support_indexes
    if (
        not planned.carrier_source_untouched_discriminator_step
        or alternative is None
        or planned.plan_id != alternative.plan_id
        or not planned.plan_id.startswith("visual-carrier-source-untouched:")
        or planned.purpose is not VisualActionPurpose.PROGRESS
        or planned.carrier_source_recovery_candidates
        or planned.carrier_source_delivery_actions
        or planned.carrier_source_detachment_probe is not None
        or planned.carrier_source_detachment_step
        or planned.carrier_source_target_center_role_exchange_step
        or planned.carrier_source_attachment_continuation_actions
        or planned.carrier_source_untouched_role_exchange_step
        or planned.carrier_source_untouched_restoration_step
        or planned.completes_carrier_source_untouched_restoration
        or not required_indexes
        or tuple(sorted(set(required_indexes))) != required_indexes
        or planned.expected_carried_source_support_indexes != required_indexes
        or planned.required_child_protected_raster_hash is None
        or planned.expected_child_protected_raster_hash is None
        or planned.expected_visible_endpoint_count is None
        or planned.expected_visible_mediator_count is None
        or planned.expected_active_center != (planned.coordinate.x, planned.coordinate.y)
        or planned.carrier_source_delivery_step
        or planned.completes_carrier_source_delivery
        or planned.completes_hierarchy
        or planned.completes_child_isolation
        or planned.completes_child_recovery
        or planned.completes_local_target
        or planned.stages_for_switch
        or planned.expected_deposited_source_protected_raster_hash is not None
        or planned.expected_deposited_visible_endpoint_count is not None
        or planned.expected_deposited_visible_mediator_count is not None
        or not _carrier_source_recovery_consequence_alternative_is_compatible(
            planned,
            alternative,
        )
        or not alternative.carrier_source_untouched_discriminator_step
        or not _carrier_source_untouched_restoration_actions_are_compatible(planned)
        or not _carrier_source_untouched_restoration_actions_are_compatible(alternative)
    ):
        return False
    planned_restoration = planned.carrier_source_untouched_restoration_actions
    alternative_restoration = alternative.carrier_source_untouched_restoration_actions
    return bool(
        tuple(item.coordinate for item in planned_restoration)
        == tuple(item.coordinate for item in alternative_restoration)
        and planned_restoration[-1].expected_child_protected_raster_hash
        == alternative_restoration[-1].expected_child_protected_raster_hash
        and planned_restoration[-1].expected_visible_endpoint_count
        == alternative_restoration[-1].expected_visible_endpoint_count
        and planned_restoration[-1].expected_visible_mediator_count
        == alternative_restoration[-1].expected_visible_mediator_count
    )


def _carrier_source_paired_cargo_common_is_compatible(planned: PlannedClick) -> bool:
    """Require the closed exact-raster boundary shared by paired cargo actions."""

    required_indexes = planned.required_carried_source_support_indexes
    return bool(
        planned.plan_signature.startswith("affine-carrier-source-occlusion-hierarchy-recovery:")
        and planned.purpose in {VisualActionPurpose.PROGRESS, VisualActionPurpose.PROBE}
        and planned.carrier_source_recovery_alternative is None
        and not planned.carrier_source_recovery_candidates
        and not planned.carrier_source_delivery_actions
        and planned.carrier_source_detachment_probe is None
        and not planned.carrier_source_detachment_step
        and not planned.carrier_source_target_center_role_exchange_step
        and not planned.carrier_source_attachment_continuation_actions
        and not planned.carrier_source_untouched_role_exchange_step
        and not planned.carrier_source_untouched_discriminator_step
        and not planned.carrier_source_untouched_restoration_actions
        and not planned.carrier_source_untouched_restoration_step
        and not planned.completes_carrier_source_untouched_restoration
        and len(required_indexes) == 2
        and tuple(sorted(set(required_indexes))) == required_indexes
        and planned.expected_carried_source_support_indexes == required_indexes
        and planned.required_child_protected_raster_hash is not None
        and planned.expected_child_protected_raster_hash is not None
        and planned.carrier_source_paired_cargo_initial_protected_raster_hash is not None
        and planned.expected_visible_endpoint_count is not None
        and planned.expected_visible_mediator_count is not None
        and planned.expected_active_center == (planned.coordinate.x, planned.coordinate.y)
        and not planned.carrier_source_delivery_step
        and not planned.completes_carrier_source_delivery
        and not planned.completes_hierarchy
        and not planned.completes_child_isolation
        and not planned.completes_child_recovery
        and not planned.completes_local_target
        and not planned.stages_for_switch
        and planned.expected_deposited_source_protected_raster_hash is None
        and planned.expected_deposited_visible_endpoint_count is None
        and planned.expected_deposited_visible_mediator_count is None
    )


def _carrier_source_paired_cargo_restoration_step_is_compatible(
    planned: PlannedClick,
) -> bool:
    """Require one exact carried-pair inverse step with no competing branch."""

    return bool(
        planned.carrier_source_paired_cargo_restoration_step
        and planned.plan_id.startswith("visual-carrier-source-paired-cargo-restoration:")
        and _carrier_source_paired_cargo_common_is_compatible(planned)
        and not planned.carrier_source_paired_cargo_step
        and not planned.completes_carrier_source_paired_cargo
        and not planned.carrier_source_paired_cargo_restoration_actions
        and planned.carrier_source_paired_cargo_role_handoff is None
        and not planned.carrier_source_paired_cargo_role_handoff_step
        and not planned.carrier_source_paired_cargo_role_restoration_actions
        and not planned.carrier_source_paired_cargo_role_restoration_step
    )


def _carrier_source_paired_cargo_restoration_actions_are_compatible(
    planned: PlannedClick,
) -> bool:
    """Validate a finite exact inverse from the paired destination to its replay boundary."""

    actions = planned.carrier_source_paired_cargo_restoration_actions
    expected_indexes = planned.expected_carried_source_support_indexes
    if (
        len(actions) < 2
        or not planned.completes_carrier_source_paired_cargo
        or actions[0].required_child_protected_raster_hash
        != planned.expected_child_protected_raster_hash
        or actions[-1].expected_child_protected_raster_hash
        != planned.carrier_source_paired_cargo_initial_protected_raster_hash
    ):
        return False
    for index, action in enumerate(actions):
        if (
            not _carrier_source_paired_cargo_restoration_step_is_compatible(action)
            or action.plan_id != actions[0].plan_id
            or action.plan_signature != planned.plan_signature
            or action.mechanic_ref != planned.mechanic_ref
            or action.target_center != planned.target_center
            or action.required_carried_source_support_indexes != expected_indexes
            or action.expected_carried_source_support_indexes != expected_indexes
            or action.carrier_source_paired_cargo_initial_protected_raster_hash
            != planned.carrier_source_paired_cargo_initial_protected_raster_hash
            or action.carrier_source_paired_cargo_role_handoff_family
            != planned.carrier_source_paired_cargo_role_handoff_family
            or action.completes_carrier_source_paired_cargo_restoration
            != (index + 1 == len(actions))
        ):
            return False
        if index and (
            actions[index - 1].expected_child_protected_raster_hash
            != action.required_child_protected_raster_hash
        ):
            return False
    return True


def _carrier_source_paired_cargo_role_restoration_step_is_compatible(
    planned: PlannedClick,
) -> bool:
    """Require the single exact role restoration preceding the paired inverse."""

    return bool(
        planned.carrier_source_paired_cargo_role_handoff_family
        and planned.carrier_source_paired_cargo_role_restoration_step
        and planned.plan_id.startswith("visual-carrier-source-paired-cargo-role-restoration:")
        and planned.purpose is VisualActionPurpose.PROBE
        and _carrier_source_paired_cargo_common_is_compatible(planned)
        and not planned.carrier_source_paired_cargo_step
        and not planned.completes_carrier_source_paired_cargo
        and not planned.carrier_source_paired_cargo_restoration_actions
        and not planned.carrier_source_paired_cargo_restoration_step
        and not planned.completes_carrier_source_paired_cargo_restoration
        and planned.carrier_source_paired_cargo_role_handoff is None
        and not planned.carrier_source_paired_cargo_role_handoff_step
        and not planned.carrier_source_paired_cargo_role_restoration_actions
    )


def _carrier_source_paired_cargo_role_restoration_actions_are_compatible(
    planned: PlannedClick,
) -> bool:
    """Validate role restoration followed by the already-certified exact inverse."""

    actions = planned.carrier_source_paired_cargo_role_restoration_actions
    if len(actions) < 3 or not actions:
        return False
    role_restoration, *inverse = actions
    expected_indexes = planned.expected_carried_source_support_indexes
    if (
        not _carrier_source_paired_cargo_role_restoration_step_is_compatible(role_restoration)
        or not all(
            _carrier_source_paired_cargo_restoration_step_is_compatible(action)
            for action in inverse
        )
        or not inverse[-1].completes_carrier_source_paired_cargo_restoration
        or role_restoration.required_child_protected_raster_hash
        != planned.expected_child_protected_raster_hash
        or role_restoration.expected_child_protected_raster_hash
        != inverse[0].required_child_protected_raster_hash
        or inverse[-1].expected_child_protected_raster_hash
        != planned.carrier_source_paired_cargo_initial_protected_raster_hash
    ):
        return False
    return bool(
        all(action.plan_signature == planned.plan_signature for action in actions)
        and all(action.mechanic_ref == planned.mechanic_ref for action in actions)
        and all(action.target_center == planned.target_center for action in actions)
        and all(action.carrier_source_paired_cargo_role_handoff_family for action in actions)
        and all(
            action.required_carried_source_support_indexes == expected_indexes
            and action.expected_carried_source_support_indexes == expected_indexes
            for action in actions
        )
        and all(
            actions[index - 1].expected_child_protected_raster_hash
            == action.required_child_protected_raster_hash
            for index, action in enumerate(actions)
            if index
        )
    )


def _carrier_source_paired_cargo_crossed_predecessor_step_is_compatible(
    planned: PlannedClick,
) -> bool:
    """Require one exact step in the handoff-preserving predecessor cycle."""

    return bool(
        planned.carrier_source_paired_cargo_role_handoff_family
        and planned.carrier_source_paired_cargo_crossed_predecessor_family
        and planned.carrier_source_paired_cargo_crossed_predecessor_step
        and planned.plan_id.startswith("visual-carrier-source-paired-cargo-crossed-predecessor:")
        and _carrier_source_paired_cargo_common_is_compatible(planned)
        and not planned.carrier_source_paired_cargo_step
        and not planned.completes_carrier_source_paired_cargo
        and not planned.carrier_source_paired_cargo_restoration_actions
        and not planned.carrier_source_paired_cargo_restoration_step
        and not planned.completes_carrier_source_paired_cargo_restoration
        and planned.carrier_source_paired_cargo_role_handoff is None
        and not planned.carrier_source_paired_cargo_role_handoff_step
        and not planned.carrier_source_paired_cargo_role_restoration_actions
        and not planned.carrier_source_paired_cargo_role_restoration_step
        and not planned.carrier_source_paired_cargo_crossed_predecessor_actions
        and not planned.carrier_source_paired_cargo_crossed_delivery_step
        and not planned.completes_carrier_source_paired_cargo_crossed_delivery
        and (
            not planned.completes_carrier_source_paired_cargo_crossed_predecessor
            or planned.purpose is VisualActionPurpose.PROBE
        )
    )


def _carrier_source_paired_cargo_crossed_predecessor_actions_are_compatible(
    planned: PlannedClick,
) -> bool:
    """Validate one complete predecessor cycle from the exact handoff raster."""

    actions = planned.carrier_source_paired_cargo_crossed_predecessor_actions
    expected_indexes = planned.expected_carried_source_support_indexes
    if (
        len(actions) < 2
        or len(actions) % 2
        or not planned.carrier_source_paired_cargo_crossed_predecessor_family
        or actions[0].required_child_protected_raster_hash
        != planned.expected_child_protected_raster_hash
        or actions[-1].expected_child_protected_raster_hash
        == planned.carrier_source_paired_cargo_initial_protected_raster_hash
    ):
        return False
    for index, action in enumerate(actions):
        if (
            not _carrier_source_paired_cargo_crossed_predecessor_step_is_compatible(action)
            or action.plan_id != actions[0].plan_id
            or action.plan_signature != planned.plan_signature
            or action.mechanic_ref != planned.mechanic_ref
            or action.target_center != planned.target_center
            or action.required_carried_source_support_indexes != expected_indexes
            or action.expected_carried_source_support_indexes != expected_indexes
            or action.carrier_source_paired_cargo_initial_protected_raster_hash
            != planned.carrier_source_paired_cargo_initial_protected_raster_hash
            or action.completes_carrier_source_paired_cargo_crossed_predecessor
            != (index + 1 == len(actions))
            or action.purpose
            is not (VisualActionPurpose.PROGRESS if index % 2 == 0 else VisualActionPurpose.PROBE)
        ):
            return False
        if index and (
            actions[index - 1].expected_child_protected_raster_hash
            != action.required_child_protected_raster_hash
        ):
            return False
    return True


def _carrier_source_paired_cargo_crossed_delivery_step_is_compatible(
    planned: PlannedClick,
) -> bool:
    """Require one post-receipt target-relative action from the crossed state."""

    return bool(
        planned.carrier_source_paired_cargo_crossed_delivery_step
        and planned.plan_id.startswith("visual-carrier-source-paired-cargo-crossed-delivery:")
        and _carrier_source_paired_cargo_common_is_compatible(planned)
        and not planned.carrier_source_paired_cargo_step
        and not planned.completes_carrier_source_paired_cargo
        and not planned.carrier_source_paired_cargo_restoration_actions
        and not planned.carrier_source_paired_cargo_restoration_step
        and not planned.completes_carrier_source_paired_cargo_restoration
        and not planned.carrier_source_paired_cargo_role_handoff_family
        and planned.carrier_source_paired_cargo_role_handoff is None
        and not planned.carrier_source_paired_cargo_role_handoff_step
        and not planned.carrier_source_paired_cargo_role_restoration_actions
        and not planned.carrier_source_paired_cargo_role_restoration_step
        and not planned.carrier_source_paired_cargo_crossed_predecessor_family
        and not planned.carrier_source_paired_cargo_crossed_predecessor_actions
        and not planned.carrier_source_paired_cargo_crossed_predecessor_step
        and not planned.completes_carrier_source_paired_cargo_crossed_predecessor
        and (
            not planned.completes_carrier_source_paired_cargo_crossed_delivery
            or planned.purpose is VisualActionPurpose.PROGRESS
        )
    )


def _carrier_source_crossed_delivery_recovery_is_compatible(
    plan: _HierarchyPlan,
) -> bool:
    """Require a closed inverse for the one crossed delivery route."""

    forward = plan.actions
    recovery = plan.recovery_actions
    if (
        not forward
        or len(recovery) != len(forward)
        or not all(
            _carrier_source_paired_cargo_crossed_delivery_step_is_compatible(action)
            for action in forward
        )
        or not forward[-1].completes_carrier_source_paired_cargo_crossed_delivery
        or not all(
            _carrier_source_paired_cargo_restoration_step_is_compatible(action)
            for action in recovery
        )
        or recovery[0].required_child_protected_raster_hash
        != forward[-1].expected_child_protected_raster_hash
        or recovery[-1].expected_child_protected_raster_hash
        != forward[0].required_child_protected_raster_hash
    ):
        return False
    return bool(
        all(action.plan_signature == plan.signature for action in (*forward, *recovery))
        and all(
            recovery[index - 1].expected_child_protected_raster_hash
            == action.required_child_protected_raster_hash
            for index, action in enumerate(recovery)
            if index
        )
        and all(
            action.completes_carrier_source_paired_cargo_restoration == (index + 1 == len(recovery))
            for index, action in enumerate(recovery)
        )
    )


def _carrier_source_paired_cargo_role_handoff_step_is_compatible(
    planned: PlannedClick,
) -> bool:
    """Require one complementary paired-terminal role handoff and closed restoration."""

    return bool(
        planned.carrier_source_paired_cargo_role_handoff_family
        and planned.carrier_source_paired_cargo_role_handoff_step
        and planned.plan_id.startswith("visual-carrier-source-paired-cargo-role-handoff:")
        and planned.purpose is VisualActionPurpose.PROBE
        and _carrier_source_paired_cargo_common_is_compatible(planned)
        and not planned.carrier_source_paired_cargo_step
        and not planned.completes_carrier_source_paired_cargo
        and not planned.carrier_source_paired_cargo_restoration_actions
        and not planned.carrier_source_paired_cargo_restoration_step
        and not planned.completes_carrier_source_paired_cargo_restoration
        and planned.carrier_source_paired_cargo_role_handoff is None
        and not planned.carrier_source_paired_cargo_role_restoration_step
        and not planned.carrier_source_paired_cargo_crossed_predecessor_step
        and not planned.completes_carrier_source_paired_cargo_crossed_predecessor
        and not planned.carrier_source_paired_cargo_crossed_delivery_step
        and not planned.completes_carrier_source_paired_cargo_crossed_delivery
        and (
            (
                planned.carrier_source_paired_cargo_crossed_predecessor_family
                and not planned.carrier_source_paired_cargo_role_restoration_actions
                and _carrier_source_paired_cargo_crossed_predecessor_actions_are_compatible(planned)
            )
            or (
                not planned.carrier_source_paired_cargo_crossed_predecessor_family
                and not planned.carrier_source_paired_cargo_crossed_predecessor_actions
                and _carrier_source_paired_cargo_role_restoration_actions_are_compatible(planned)
            )
        )
    )


def _carrier_source_paired_cargo_step_is_compatible(planned: PlannedClick) -> bool:
    """Require one exact carried-pair placement step and a closed terminal inverse."""

    restoration = planned.carrier_source_paired_cargo_restoration_actions
    return bool(
        planned.carrier_source_paired_cargo_step
        and planned.plan_id.startswith("visual-carrier-source-paired-cargo:")
        and _carrier_source_paired_cargo_common_is_compatible(planned)
        and not planned.carrier_source_paired_cargo_restoration_step
        and not planned.completes_carrier_source_paired_cargo_restoration
        and not planned.carrier_source_paired_cargo_role_handoff_step
        and not planned.carrier_source_paired_cargo_role_restoration_actions
        and not planned.carrier_source_paired_cargo_role_restoration_step
        and not planned.carrier_source_paired_cargo_crossed_predecessor_actions
        and not planned.carrier_source_paired_cargo_crossed_predecessor_step
        and not planned.completes_carrier_source_paired_cargo_crossed_predecessor
        and not planned.carrier_source_paired_cargo_crossed_delivery_step
        and not planned.completes_carrier_source_paired_cargo_crossed_delivery
        and bool(restoration) == planned.completes_carrier_source_paired_cargo
        and bool(planned.carrier_source_paired_cargo_role_handoff)
        == (
            planned.carrier_source_paired_cargo_role_handoff_family
            and planned.completes_carrier_source_paired_cargo
        )
        and (
            not planned.completes_carrier_source_paired_cargo
            or (
                planned.purpose is VisualActionPurpose.PROGRESS
                and _carrier_source_paired_cargo_restoration_actions_are_compatible(planned)
                and (
                    planned.carrier_source_paired_cargo_role_handoff is None
                    or _carrier_source_paired_cargo_role_handoff_step_is_compatible(
                        planned.carrier_source_paired_cargo_role_handoff
                    )
                )
            )
        )
    )


def _carrier_source_recovery_state_candidate_is_compatible(
    planned: PlannedClick,
    candidate: PlannedClick,
) -> bool:
    """Validate a precomputed carried-subset state candidate before raster matching."""

    required_indexes = candidate.required_carried_source_support_indexes
    return bool(
        not candidate.carrier_source_recovery_candidates
        and not candidate.carrier_source_delivery_actions
        and candidate.carrier_source_detachment_probe is None
        and not candidate.carrier_source_target_center_role_exchange_step
        and not candidate.carrier_source_attachment_continuation_actions
        and not candidate.carrier_source_untouched_role_exchange_step
        and not candidate.carrier_source_untouched_discriminator_step
        and not candidate.carrier_source_untouched_restoration_actions
        and not candidate.carrier_source_untouched_restoration_step
        and not candidate.completes_carrier_source_untouched_restoration
        and not candidate.carrier_source_delivery_step
        and not candidate.carrier_source_detachment_step
        and not candidate.completes_carrier_source_delivery
        and _carrier_source_recovery_action_signature(candidate)
        == _carrier_source_recovery_action_signature(planned)
        and candidate.required_child_protected_raster_hash is not None
        and candidate.expected_child_protected_raster_hash is not None
        and candidate.expected_visible_endpoint_count is not None
        and candidate.expected_visible_mediator_count is not None
        and len(required_indexes) == len(set(required_indexes))
        and tuple(sorted(required_indexes)) == required_indexes
        and candidate.expected_carried_source_support_indexes == required_indexes
        and (
            candidate.carrier_source_recovery_alternative is None
            or _carrier_source_recovery_consequence_alternative_is_compatible(
                candidate,
                candidate.carrier_source_recovery_alternative,
            )
        )
    )


def _hierarchy_planned_click_matching_candidate(
    scene: VisualScene,
    planned: PlannedClick,
    *,
    active_color: int,
    required_carried_source_support_indexes: tuple[int, ...] | None = None,
) -> PlannedClick | None:
    """Return the exact queued raster lineage certified by the current frame."""

    paired_cargo_fields = bool(
        planned.carrier_source_paired_cargo_step
        or planned.completes_carrier_source_paired_cargo
        or planned.carrier_source_paired_cargo_initial_protected_raster_hash is not None
        or planned.carrier_source_paired_cargo_restoration_actions
        or planned.carrier_source_paired_cargo_restoration_step
        or planned.completes_carrier_source_paired_cargo_restoration
        or planned.carrier_source_paired_cargo_role_handoff_family
        or planned.carrier_source_paired_cargo_role_handoff is not None
        or planned.carrier_source_paired_cargo_role_handoff_step
        or planned.carrier_source_paired_cargo_role_restoration_actions
        or planned.carrier_source_paired_cargo_role_restoration_step
        or planned.carrier_source_paired_cargo_crossed_predecessor_family
        or planned.carrier_source_paired_cargo_crossed_predecessor_actions
        or planned.carrier_source_paired_cargo_crossed_predecessor_step
        or planned.completes_carrier_source_paired_cargo_crossed_predecessor
        or planned.carrier_source_paired_cargo_crossed_delivery_step
        or planned.completes_carrier_source_paired_cargo_crossed_delivery
    )
    if paired_cargo_fields and not (
        _carrier_source_paired_cargo_step_is_compatible(planned)
        or _carrier_source_paired_cargo_restoration_step_is_compatible(planned)
        or _carrier_source_paired_cargo_role_handoff_step_is_compatible(planned)
        or _carrier_source_paired_cargo_role_restoration_step_is_compatible(planned)
        or _carrier_source_paired_cargo_crossed_predecessor_step_is_compatible(planned)
        or _carrier_source_paired_cargo_crossed_delivery_step_is_compatible(planned)
    ):
        return None
    if planned.carrier_source_delivery_step and not _carrier_source_delivery_step_is_compatible(
        planned
    ):
        return None
    if planned.carrier_source_detachment_step and not (
        _carrier_source_detachment_step_is_compatible(planned)
    ):
        return None
    if planned.carrier_source_untouched_role_exchange_step and not (
        _carrier_source_untouched_role_exchange_step_is_compatible(planned)
    ):
        return None
    if planned.carrier_source_untouched_discriminator_step and not (
        _carrier_source_untouched_discriminator_step_is_compatible(planned)
    ):
        return None
    if planned.carrier_source_untouched_restoration_step and not (
        _carrier_source_untouched_restoration_step_is_compatible(planned)
    ):
        return None
    candidates = (planned, *planned.carrier_source_recovery_candidates)
    for candidate in candidates:
        if candidate is not planned and not _carrier_source_recovery_state_candidate_is_compatible(
            planned,
            candidate,
        ):
            return None
        if (
            candidate is planned
            and candidate.carrier_source_recovery_alternative is not None
            and not _carrier_source_recovery_consequence_alternative_is_compatible(
                candidate,
                candidate.carrier_source_recovery_alternative,
            )
        ):
            return None
        if (
            required_carried_source_support_indexes is not None
            and candidate.required_carried_source_support_indexes
            != required_carried_source_support_indexes
        ):
            continue
        if _single_hierarchy_planned_click_is_safe(
            scene,
            candidate,
            active_color=active_color,
        ):
            return candidate
    return None


def _hierarchy_planned_click_is_safe(
    scene: VisualScene,
    planned: PlannedClick,
    *,
    active_color: int,
    required_carried_source_support_indexes: tuple[int, ...] | None = None,
) -> bool:
    """Revalidate either the primary or exact carrier-source recovery lineage."""

    return (
        _hierarchy_planned_click_matching_candidate(
            scene,
            planned,
            active_color=active_color,
            required_carried_source_support_indexes=(required_carried_source_support_indexes),
        )
        is not None
    )


def _remaining_unsatisfied_affine_hubs(
    scene: VisualScene,
    *,
    completed_target_center: tuple[int, int],
) -> tuple[VisualObject, ...]:
    """Exclude the just-completed hub and any hub on another visible target."""

    visible_target_centers = tuple(item.rounded_center for item in scene.targets)
    return tuple(
        hub
        for hub in scene.mediators
        if _distance((hub.center_x, hub.center_y), completed_target_center) > 2.0
        and all(
            _distance((hub.center_x, hub.center_y), target_center) > 2.0
            for target_center in visible_target_centers
        )
    )


def _component_cells_remain_distinct(
    scene: VisualScene,
    cells: tuple[tuple[int, int], ...],
    *,
    prospective_color: int,
    ignored_object_refs: frozenset[str],
) -> bool:
    for item in scene.objects:
        if item.object_ref in ignored_object_refs or item.color != prospective_color:
            continue
        separation = min(
            max(abs(left_x - right_x), abs(left_y - right_y))
            for left_x, left_y in cells
            for right_x, right_y in item.cells
        )
        if separation <= 1 or _small_components_would_merge(cells, item.cells):
            return False
    return True


def _role_swap_remains_readable(
    scene: VisualScene,
    selected: VisualObject,
    *,
    active_color: int,
) -> bool:
    """Preflight both recolored endpoint components for a role exchange."""

    active_endpoints = tuple(item for item in scene.endpoints if item.color == active_color)
    if len(active_endpoints) != 1 or selected.color == active_color:
        return False
    current_active = active_endpoints[0]
    ignored = frozenset({selected.object_ref, current_active.object_ref})
    return _component_cells_remain_distinct(
        scene,
        selected.cells,
        prospective_color=active_color,
        ignored_object_refs=ignored,
    ) and _component_cells_remain_distinct(
        scene,
        current_active.cells,
        prospective_color=selected.color,
        ignored_object_refs=ignored,
    )


def _local_target_satisfied(
    scene: VisualScene,
    *,
    target_center: tuple[int, int] | None,
    mediator_color: int | None,
    arity: int | None,
) -> bool:
    if target_center is None or mediator_color is None or arity is None:
        return False
    marker_endpoints = tuple(item for item in scene.endpoints if item.center_cell == mediator_color)
    if len(marker_endpoints) == arity:
        marker_centroid = (
            sum(item.center_x for item in marker_endpoints) / arity,
            sum(item.center_y for item in marker_endpoints) / arity,
        )
        if _distance(marker_centroid, target_center) <= 2.0:
            return True
    if any(
        group.marker_color == mediator_color
        and group.arity == arity
        and _distance(group.mediator.rounded_center, target_center) <= 2.0
        for group in _embedded_marker_groups(scene)
    ):
        return True
    targets = tuple(
        item
        for item in scene.targets
        if item.color == mediator_color
        and _distance((item.center_x, item.center_y), target_center) <= 2.0
    )
    mediators = tuple(item for item in scene.mediators if item.color == mediator_color)
    visible_overlap = any(
        _distance(
            (mediator.center_x, mediator.center_y),
            (target.center_x, target.center_y),
        )
        <= 2.0
        for target in targets
        for mediator in mediators
    )
    if visible_overlap:
        return True
    for endpoints in itertools.combinations(scene.endpoints, arity):
        centroid = (
            sum(item.center_x for item in endpoints) / arity,
            sum(item.center_y for item in endpoints) / arity,
        )
        if _distance(centroid, target_center) <= 2.0:
            return True
    return False


def _projected_marker_target_satisfied(
    scene: VisualScene,
    *,
    target_center: tuple[int, int] | None,
    mediator_color: int | None,
    arity: int | None,
    active_color: int | None,
    coordinate: Coordinate | None,
) -> bool:
    """Confirm an exact target contact from the pre-action affine evidence.

    The official result frame may consume or occlude a locally completed
    group.  This bounded check only recognizes the target contact predicted by
    the observed endpoint sum; it never promotes that contact to level or game
    completion.
    """

    if (
        target_center is None
        or mediator_color is None
        or arity is None
        or active_color is None
        or coordinate is None
    ):
        return False
    active = _embedded_marker_active_endpoint(scene, active_color=active_color)
    if active is None:
        return False
    groups = tuple(
        group
        for group in _embedded_marker_groups(scene)
        if group.marker_color == mediator_color
        and group.arity == arity
        and group.target.rounded_center == target_center
        and active.object_ref in {endpoint.object_ref for endpoint in group.endpoints}
    )
    if len(groups) != 1:
        return False
    group = groups[0]
    sum_x = (
        sum(endpoint.rounded_center[0] for endpoint in group.endpoints)
        - active.rounded_center[0]
        + coordinate.x
    )
    sum_y = (
        sum(endpoint.rounded_center[1] for endpoint in group.endpoints)
        - active.rounded_center[1]
        + coordinate.y
    )
    return _marker_group_potential(group, sum_x=sum_x, sum_y=sum_y) == 0


def _observed_bla_consequence(
    before: Observation,
    after: Observation,
    *,
    action: ActionRequest,
    coordinate_transform: bool,
    changed_cells: int,
) -> ConsequenceVector:
    vector = ConsequenceVector.unknown()
    if coordinate_transform:
        vector = vector.with_channel(
            ConsequenceChannel.OTHER_OBJECT_EFFECTS,
            ChannelValue.known(
                ObjectEffect(
                    "readable-endpoint-system",
                    ObjectOperation.TRANSFORMED,
                    "coordinate-causal",
                )
            ),
        )
    elif action.name is ActionName.ACTION6 and changed_cells == 0:
        vector = vector.with_channel(
            ConsequenceChannel.OTHER_OBJECT_EFFECTS,
            ChannelValue.known_empty(),
        )

    before_actions = set(before.available_actions)
    after_actions = set(after.available_actions)
    if before_actions != after_actions:
        legal_effects = tuple(
            LegalActionEffect(item, item in after_actions)
            for item in sorted(before_actions | after_actions, key=lambda value: value.value)
            if (item in before_actions) != (item in after_actions)
        )
        vector = vector.with_channel(
            ConsequenceChannel.LEGAL_ACTION_CHANGES,
            ChannelValue.known(*legal_effects),
        )
    if before.levels_completed != after.levels_completed:
        vector = vector.with_channel(
            ConsequenceChannel.SCORE_PROGRESS_CHANGES,
            ChannelValue.known(
                ScoreProgressEffect(
                    "levels_completed",
                    after.levels_completed - before.levels_completed,
                )
            ),
        )
    if before.state is not after.state or before.full_reset != after.full_reset:
        vector = vector.with_channel(
            ConsequenceChannel.TERMINAL_CHANGES,
            ChannelValue.known(TerminalEffect(after.state)),
        )
    return vector


def _affine_base_consequence() -> ConsequenceVector:
    return ConsequenceVector.unknown().with_channel(
        ConsequenceChannel.OTHER_OBJECT_EFFECTS,
        ChannelValue.known(
            ObjectEffect(
                "readable-endpoint-system",
                ObjectOperation.TRANSFORMED,
                "coordinate-causal",
            )
        ),
    )


class VisualCausalPolicy:
    """Bounded mechanical learner for readable coordinate-action scenes.

    The policy keeps game-level support receipts across level boundaries, but
    clears object identities, coordinates, and plans whenever the official
    level counter changes.  GAME_OVER evidence is accepted before RESET.
    """

    manages_trace = False
    _MAX_MARKER_STRUCTURAL_ACTIONS = 512
    _MAX_FAILED_EXPLORATION_ROOTS = 64

    def __init__(self, *, max_coordinate_candidates: int = 8) -> None:
        if not 1 <= max_coordinate_candidates <= 32:
            raise ValueError("max_coordinate_candidates must be in 1..32")
        self._max_coordinate_candidates = max_coordinate_candidates
        self._level_index = 0
        self._previous_observation: Observation | None = None
        self._pending_before: Observation | None = None
        self._pending_action: ActionRequest | None = None
        self._pending_purpose = VisualActionPurpose.PROBE
        self._pending_prediction = "all factored channels UNKNOWN"
        self._pending_mechanic_refs: tuple[str, ...] = ()
        self._pending_plan_signature: str | None = None
        self._pending_target_center: tuple[int, int] | None = None
        self._pending_mediator_color: int | None = None
        self._pending_arity: int | None = None
        self._pending_completes_local_target = False
        self._pending_completes_hierarchy = False
        self._pending_completes_child_isolation = False
        self._pending_completes_child_recovery = False
        self._pending_expected_child_mediator_center: tuple[int, int] | None = None
        self._pending_expected_child_mediator_signature: _VisualObjectStateSignature | None = None
        self._pending_expected_child_endpoint_centers: tuple[tuple[int, int], ...] = ()
        self._pending_expected_child_endpoint_signature: _EndpointStateSignature = ()
        self._pending_expected_child_connector_signature: _ConnectorStateSignature = None
        self._pending_expected_active_center: tuple[int, int] | None = None
        self._pending_expected_child_protected_raster_hash: str | None = None
        self._pending_expected_child_raster_signature: _RasterStateSignature = ()
        self._pending_expected_occluded_endpoint_centers: tuple[tuple[int, int], ...] = ()
        self._pending_expected_occluded_endpoint_cells: tuple[tuple[int, int], ...] = ()
        self._pending_expected_visible_endpoint_count: int | None = None
        self._pending_expected_visible_mediator_count: int | None = None
        self._pending_carrier_source_recovery_candidate: PlannedClick | None = None
        self._pending_clef_prediction = EffectVector.unknown()
        self._pending_mechanic_prediction: MechanicPredictionReceipt | None = None
        self._plan: deque[PlannedClick] = deque()
        self._mechanics: list[AffineMechanic] = []
        self._receipts: list[VisualActionReceipt] = []
        self._durable_receipts: deque[dict[str, JSONValue]] = deque()
        self._mechanical_learner: MechanicalLearner | None = None
        self._affine_ledger_ref: MechanicRef | None = None
        self._transfer_confirmed_levels: set[int] = set()
        self._failed_plan_signatures: set[str] = set()
        self._preterminal_hierarchy_retry_signature: str | None = None
        self._attempted_activation_refs: set[str] = set()
        self._marker_bootstrap_attempted = False
        self._marker_stage_pending_switch: int | None = None
        self._marker_reacquire_after_local_solve = False
        self._affine_reacquire_target_center: tuple[int, int] | None = None
        self._pending_affine_reacquisition = False
        self._active_hierarchy_signature: str | None = None
        self._active_hierarchy_relation_key: str | None = None
        self._active_hierarchy_supports: tuple[tuple[int, int], ...] = ()
        self._active_hierarchy_support_weights: tuple[int, ...] = ()
        self._active_hierarchy_recovery_actions: tuple[PlannedClick, ...] = ()
        self._active_carrier_source_attachment_replay_context: (
            _CarrierSourceAttachmentReplayContext | None
        ) = None
        self._active_crossed_delivery_replay_context: (
            _CarrierSourceCrossedDeliveryReplayContext | None
        ) = None
        self._active_carried_source_recovery_support_indexes: tuple[int, ...] = ()
        self._active_carrier_source_setup_start_action_count: int | None = None
        self._active_carrier_source_setup_action_count: int | None = None
        self._active_carrier_source_crossed_forward_action_count: int | None = None
        self._resource_interrupted_paired_replay: _ResourceInterruptedPairedReplay | None = None
        self._post_marker_resource_reset_bridge: _PostMarkerResourceResetBridge | None = None
        self._active_crossed_replay_resource_lineage: _ActiveCrossedReplayResourceLineage | None = (
            None
        )
        self._reset_epoch_index = 0
        self._paired_role_handoff_observed_signature: str | None = None
        self._paired_role_handoff_observed_context_key: str | None = None
        self._paired_role_handoff_observed_setup_relation_key: str | None = None
        self._paired_role_handoff_observed_setup_plan_signature: str | None = None
        self._paired_role_handoff_observed_setup_action_count: int | None = None
        self._paired_role_handoff_observed_crossed_forward_action_count: int | None = None
        self._crossed_delivery_recovery_signature: str | None = None
        self._attempted_post_deposit_mediator_access_hypothesis_keys: set[str] = set()
        self._failed_post_deposit_mediator_access_hypothesis_keys: set[str] = set()
        self._post_deposit_mediator_access_closed: str | None = None
        self._attempted_post_access_composite_exit_hypothesis_keys: set[str] = set()
        self._failed_post_access_composite_exit_hypothesis_keys: set[str] = set()
        self._post_access_composite_exit_closed: str | None = None
        self._attempted_post_access_composite_marker_hypothesis_keys: set[str] = set()
        self._failed_post_access_composite_marker_hypothesis_keys: set[str] = set()
        self._post_access_composite_marker_closed: str | None = None
        self._episode_resource_baseline_edges: tuple[tuple[int, ...], ...] = ()
        self._episode_resource_candidates: tuple[_EdgeResourceProgress, ...] = ()
        self._episode_action6_count = 0
        self._failed_hierarchy_relation_keys: set[str] = set()
        self._failed_weighted_hierarchy_relation_keys: set[str] = set()
        self._failed_visible_node_hierarchy_relation_keys: set[str] = set()
        self._failed_bridge_hierarchy_relation_keys: set[str] = set()
        self._failed_residual_linked_hierarchy_relation_keys: set[str] = set()
        self._failed_external_residual_linked_hierarchy_relation_keys: set[str] = set()
        self._failed_raw_matching_composite_hierarchy_relation_keys: set[str] = set()
        self._failed_external_own_composite_hierarchy_relation_keys: set[str] = set()
        self._failed_carrier_source_occlusion_hierarchy_relation_keys: set[str] = set()
        self._hierarchy_lineage_lost: tuple[int, str, str, str] | None = None
        self._failed_hierarchy_lineages: set[tuple[int, str, str, str]] = set()
        self._active_child_isolation_relation_key: str | None = None
        self._active_child_isolation_hypothesis_key: str | None = None
        self._active_child_isolation_frozen_mediator_center: tuple[int, int] | None = None
        self._active_child_isolation_frozen_mediator_signature: (
            _VisualObjectStateSignature | None
        ) = None
        self._active_child_isolation_frozen_endpoint_centers: tuple[tuple[int, int], ...] = ()
        self._active_child_isolation_frozen_endpoint_signature: _EndpointStateSignature = ()
        self._active_child_isolation_frozen_connector_signature: _ConnectorStateSignature = None
        self._active_child_isolation_frozen_mediator_color: int | None = None
        self._active_child_isolation_target_signature: _TargetSurfaceSignature | None = None
        self._active_child_isolation_recovery_actions: tuple[PlannedClick, ...] = ()
        self._failed_child_isolation_hypothesis_keys: set[str] = set()
        self._failed_child_isolation_hypothesis_reasons: dict[str, str] = {}
        self._child_isolation_hypotheses_by_relation: dict[str, frozenset[str]] = {}
        self._current_child_isolation_hypothesis_keys: frozenset[str] = frozenset()
        self._hierarchy_search_deferred_count = 0
        self._last_hierarchy_search_residual: str | None = None
        self._marker_target_identity_constraints: set[int] = set()
        self._marker_structural_actions: set[str] = set()
        self._marker_structural_action_order: deque[str] = deque()
        self._episode_exploration_root: _ExplorationRootKey | None = None
        self._failed_exploration_roots: set[_ExplorationRootKey] = set()
        self._exploration_root_capacity_exhausted = False
        self._last_probe_failed = False
        self._last_active_color: int | None = None
        self._probe_ordinal = 0
        self._step_index = 0

    @property
    def mechanics(self) -> tuple[AffineMechanic, ...]:
        return tuple(self._mechanics)

    @property
    def receipts(self) -> tuple[VisualActionReceipt, ...]:
        return tuple(self._receipts)

    @property
    def mechanical_learner(self) -> MechanicalLearner | None:
        return self._mechanical_learner

    @property
    def _failed_child_isolation_relation_keys(self) -> set[str]:
        """Derive parent relations with child-stratum failure evidence for compatibility.

        Selection never consumes this aggregate: a parent appears here after any
        child stratum fails, while only the hypothesis-key set can suppress a
        future child-only test.
        """

        return {
            relation_key
            for relation_key, hypothesis_keys in (
                self._child_isolation_hypotheses_by_relation.items()
            )
            if hypothesis_keys & self._failed_child_isolation_hypothesis_keys
        }

    def _ensure_learner(self, observation: Observation) -> MechanicalLearner:
        if self._mechanical_learner is None:
            digest = hashlib.sha256(str(observation.game_id).encode("utf-8")).hexdigest()[:20]
            self._mechanical_learner = MechanicalLearner(
                game_scope=f"runtime-game:{digest}",
                level_scope=f"level:{observation.levels_completed}",
            )
        return self._mechanical_learner

    def _mechanic_context(
        self,
        observation: Observation,
        action: ActionRequest,
        purpose: VisualActionPurpose,
    ) -> MechanicContext:
        learner = self._ensure_learner(observation)
        scene = extract_visual_scene(observation.frames[-1])
        coordinate = action.coordinate
        coordinate_tag = (
            "coordinate:none"
            if coordinate is None
            else f"coordinate-quadrant:{coordinate.x // 16}:{coordinate.y // 16}"
        )
        return MechanicContext(
            learner.game_scope,
            learner.level_scope,
            object_roles=tuple(sorted({item.role.value for item in scene.objects})),
            state_tags=(
                coordinate_tag,
                f"purpose:{purpose.value.lower()}",
                f"endpoint-count:{len(scene.endpoints)}",
                f"mediator-count:{len(scene.mediators)}",
                f"target-count:{len(scene.targets)}",
                f"unresolved-target-count:{len(self._unsolved_pairs(scene))}",
            ),
        )

    def _begin_level(self, observation: Observation) -> None:
        self._level_index = observation.levels_completed
        learner = self._ensure_learner(observation)
        level_scope = f"level:{observation.levels_completed}"
        if learner.level_scope != level_scope:
            learner.start_level(level_scope)
        self._plan.clear()
        self._failed_plan_signatures.clear()
        self._preterminal_hierarchy_retry_signature = None
        self._attempted_activation_refs.clear()
        self._marker_bootstrap_attempted = False
        self._marker_stage_pending_switch = None
        self._marker_reacquire_after_local_solve = False
        self._affine_reacquire_target_center = None
        self._pending_affine_reacquisition = False
        self._active_hierarchy_signature = None
        self._active_hierarchy_relation_key = None
        self._active_hierarchy_supports = ()
        self._active_hierarchy_support_weights = ()
        self._active_hierarchy_recovery_actions = ()
        self._active_carrier_source_attachment_replay_context = None
        self._active_crossed_delivery_replay_context = None
        self._active_carried_source_recovery_support_indexes = ()
        self._active_carrier_source_setup_start_action_count = None
        self._active_carrier_source_setup_action_count = None
        self._active_carrier_source_crossed_forward_action_count = None
        self._resource_interrupted_paired_replay = None
        self._post_marker_resource_reset_bridge = None
        self._active_crossed_replay_resource_lineage = None
        self._reset_epoch_index = 0
        self._paired_role_handoff_observed_signature = None
        self._paired_role_handoff_observed_context_key = None
        self._paired_role_handoff_observed_setup_relation_key = None
        self._paired_role_handoff_observed_setup_plan_signature = None
        self._paired_role_handoff_observed_setup_action_count = None
        self._paired_role_handoff_observed_crossed_forward_action_count = None
        self._crossed_delivery_recovery_signature = None
        self._attempted_post_deposit_mediator_access_hypothesis_keys.clear()
        self._failed_post_deposit_mediator_access_hypothesis_keys.clear()
        self._post_deposit_mediator_access_closed = None
        self._attempted_post_access_composite_exit_hypothesis_keys.clear()
        self._failed_post_access_composite_exit_hypothesis_keys.clear()
        self._post_access_composite_exit_closed = None
        self._attempted_post_access_composite_marker_hypothesis_keys.clear()
        self._failed_post_access_composite_marker_hypothesis_keys.clear()
        self._post_access_composite_marker_closed = None
        self._episode_resource_baseline_edges = _frame_edge_signatures(observation.frames[-1])
        self._episode_resource_candidates = ()
        self._episode_action6_count = 0
        self._failed_hierarchy_relation_keys.clear()
        self._failed_weighted_hierarchy_relation_keys.clear()
        self._failed_visible_node_hierarchy_relation_keys.clear()
        self._failed_bridge_hierarchy_relation_keys.clear()
        self._failed_residual_linked_hierarchy_relation_keys.clear()
        self._failed_external_residual_linked_hierarchy_relation_keys.clear()
        self._failed_raw_matching_composite_hierarchy_relation_keys.clear()
        self._failed_external_own_composite_hierarchy_relation_keys.clear()
        self._failed_carrier_source_occlusion_hierarchy_relation_keys.clear()
        self._hierarchy_lineage_lost = None
        self._failed_hierarchy_lineages.clear()
        self._clear_child_isolation_execution()
        self._failed_child_isolation_hypothesis_keys.clear()
        self._failed_child_isolation_hypothesis_reasons.clear()
        self._child_isolation_hypotheses_by_relation.clear()
        self._current_child_isolation_hypothesis_keys = frozenset()
        self._marker_target_identity_constraints.clear()
        self._marker_structural_actions.clear()
        self._marker_structural_action_order.clear()
        self._episode_exploration_root = None
        self._failed_exploration_roots.clear()
        self._exploration_root_capacity_exhausted = False
        self._last_probe_failed = False
        self._probe_ordinal = 0

    def _begin_reset_epoch(self, observation: Observation) -> None:
        """Clear episode-local search state while retaining learned evidence."""

        self._reset_epoch_index += 1
        post_marker_bridge = self._post_marker_resource_reset_bridge
        if post_marker_bridge is not None and (
            not post_marker_bridge.game_over_observed
            or post_marker_bridge.level_index != observation.levels_completed
            or post_marker_bridge.authorized_reset_epoch != self._reset_epoch_index
        ):
            self._post_marker_resource_reset_bridge = None
        interrupted_replay = self._resource_interrupted_paired_replay
        if (
            interrupted_replay is not None
            and interrupted_replay.authorized_reset_epoch != self._reset_epoch_index
        ):
            self._resource_interrupted_paired_replay = None
        self._active_crossed_replay_resource_lineage = None
        self._plan.clear()
        self._attempted_activation_refs.clear()
        self._marker_bootstrap_attempted = False
        self._marker_stage_pending_switch = None
        self._marker_reacquire_after_local_solve = False
        self._affine_reacquire_target_center = None
        self._pending_affine_reacquisition = False
        self._active_hierarchy_signature = None
        self._active_hierarchy_relation_key = None
        self._active_hierarchy_supports = ()
        self._active_hierarchy_support_weights = ()
        self._active_hierarchy_recovery_actions = ()
        self._active_carrier_source_attachment_replay_context = None
        self._active_crossed_delivery_replay_context = None
        self._active_carried_source_recovery_support_indexes = ()
        self._active_carrier_source_setup_start_action_count = None
        self._active_carrier_source_setup_action_count = None
        self._active_carrier_source_crossed_forward_action_count = None
        self._paired_role_handoff_observed_signature = None
        self._paired_role_handoff_observed_context_key = None
        self._paired_role_handoff_observed_setup_relation_key = None
        self._paired_role_handoff_observed_setup_plan_signature = None
        self._paired_role_handoff_observed_setup_action_count = None
        self._paired_role_handoff_observed_crossed_forward_action_count = None
        self._crossed_delivery_recovery_signature = None
        self._post_deposit_mediator_access_closed = None
        self._post_access_composite_exit_closed = None
        self._post_access_composite_marker_closed = None
        self._episode_resource_baseline_edges = _frame_edge_signatures(observation.frames[-1])
        self._episode_resource_candidates = ()
        self._episode_action6_count = 0
        self._hierarchy_lineage_lost = None
        self._clear_child_isolation_execution()
        self._marker_structural_actions.clear()
        self._marker_structural_action_order.clear()
        self._episode_exploration_root = None
        self._last_probe_failed = False
        self._install_post_marker_reset_plan(observation)

    def _install_post_marker_reset_plan(self, observation: Observation) -> bool:
        """Consume one exact reset token only after its fresh-life plan exists."""

        bridge = self._post_marker_resource_reset_bridge
        if (
            bridge is None
            or not bridge.game_over_observed
            or observation.levels_completed != bridge.level_index
            or self._reset_epoch_index != bridge.authorized_reset_epoch
            or self._last_active_color is None
        ):
            return False
        scene = extract_visual_scene(observation.frames[-1])
        try:
            hierarchy = _unique_affine_hierarchy(
                scene,
                active_color=self._last_active_color,
            )
        except _HierarchySearchExhausted:
            return False
        if hierarchy is None:
            return False
        relation = _composite_bridge_relation(
            scene,
            hierarchy,
            level_index=observation.levels_completed,
        )
        if relation is None:
            return False
        try:
            plan = _same_child_composite_cargo_plan(
                scene,
                hierarchy,
                relation,
                rejected_signatures=self._failed_plan_signatures,
            )
        except _HierarchySearchExhausted:
            return False
        if plan is None:
            return False
        self._plan.extend(plan.actions)
        self._active_hierarchy_signature = plan.signature
        self._active_hierarchy_relation_key = relation.relation_key
        self._active_hierarchy_supports = plan.supports
        self._active_hierarchy_support_weights = plan.support_weights
        self._active_hierarchy_recovery_actions = plan.recovery_actions
        self._post_marker_resource_reset_bridge = None
        self._last_probe_failed = False
        return True

    def _clear_crossed_replay_execution(self) -> None:
        """Fail closed without reopening an unrelated hierarchy continuation."""

        self._plan.clear()
        self._active_hierarchy_signature = None
        self._active_hierarchy_relation_key = None
        self._active_hierarchy_supports = ()
        self._active_hierarchy_support_weights = ()
        self._active_hierarchy_recovery_actions = ()
        self._active_carrier_source_attachment_replay_context = None
        self._active_crossed_delivery_replay_context = None
        self._active_carried_source_recovery_support_indexes = ()
        self._active_carrier_source_setup_start_action_count = None
        self._active_carrier_source_setup_action_count = None
        self._active_carrier_source_crossed_forward_action_count = None
        self._active_crossed_replay_resource_lineage = None
        self._crossed_delivery_recovery_signature = None
        self._last_probe_failed = True

    def _active_crossed_resource_matches(self, observation: Observation) -> bool:
        """Revalidate reset, level, edge raster, and every learned fill prefix."""

        lineage = self._active_crossed_replay_resource_lineage
        if (
            lineage is None
            or observation.levels_completed != lineage.level_index
            or self._reset_epoch_index != lineage.reset_epoch
        ):
            return False
        current_resource = _matching_edge_resource_lineage(
            self._episode_resource_candidates,
            edge_index=lineage.edge_index,
            baseline=lineage.edge_baseline,
            fill_color=lineage.edge_fill_color,
            observed_actions=self._episode_action6_count,
            exhausted_filled_index_history=lineage.exhausted_filled_index_history,
        )
        edges = _frame_edge_signatures(observation.frames[-1])
        if current_resource is None or not 0 <= lineage.edge_index < len(edges):
            return False
        current_edge = edges[lineage.edge_index]
        if len(current_edge) != len(lineage.edge_baseline):
            return False
        return all(
            value
            == (
                lineage.edge_fill_color
                if index in current_resource.filled_indexes
                else lineage.edge_baseline[index]
            )
            for index, value in enumerate(current_edge)
        )

    def _post_marker_resource_bridge_matches(self, observation: Observation) -> bool:
        """Revalidate the exact board-no-op and learned meter prefix."""

        bridge = self._post_marker_resource_reset_bridge
        if (
            bridge is None
            or bridge.game_over_observed
            or observation.levels_completed != bridge.level_index
            or bridge.authorized_reset_epoch != self._reset_epoch_index + 1
            or not bridge.armed_after_actions <= self._episode_action6_count
            or self._episode_action6_count > bridge.exhausted_after_actions
            or _edge_excluded_raster_hash(
                observation.frames[-1],
                edge_index=bridge.edge_index,
            )
            != bridge.protected_raster_hash
        ):
            return False
        current_resource = _matching_edge_resource_lineage(
            self._episode_resource_candidates,
            edge_index=bridge.edge_index,
            baseline=bridge.edge_baseline,
            fill_color=bridge.edge_fill_color,
            observed_actions=self._episode_action6_count,
            exhausted_filled_index_history=bridge.exhausted_filled_index_history,
        )
        edges = _frame_edge_signatures(observation.frames[-1])
        if current_resource is None or not 0 <= bridge.edge_index < len(edges):
            return False
        current_edge = edges[bridge.edge_index]
        return len(current_edge) == len(bridge.edge_baseline) and all(
            value
            == (
                bridge.edge_fill_color
                if index in current_resource.filled_indexes
                else bridge.edge_baseline[index]
            )
            for index, value in enumerate(current_edge)
        )

    def _resource_setup_replay_prefix_matches(
        self,
        observation: Observation,
        replay: _ResourceInterruptedPairedReplay,
    ) -> bool:
        """Revalidate one fresh setup against the exact learned meter prefix."""

        if (
            observation.levels_completed != replay.level_index
            or self._reset_epoch_index != replay.authorized_reset_epoch
            or self._episode_action6_count < 0
            or self._episode_action6_count >= replay.observed_actions
        ):
            return False
        edges = _frame_edge_signatures(observation.frames[-1])
        if (
            not 0 <= replay.exhausted_edge_index < len(edges)
            or not 0 <= replay.exhausted_edge_index < len(self._episode_resource_baseline_edges)
            or self._episode_resource_baseline_edges[replay.exhausted_edge_index]
            != replay.exhausted_edge_baseline
        ):
            return False
        current_edge = edges[replay.exhausted_edge_index]
        if self._episode_action6_count == 0:
            return current_edge == replay.exhausted_edge_baseline
        current_resource = _matching_edge_resource_lineage(
            self._episode_resource_candidates,
            edge_index=replay.exhausted_edge_index,
            baseline=replay.exhausted_edge_baseline,
            fill_color=replay.exhausted_edge_fill_color,
            observed_actions=self._episode_action6_count,
            exhausted_filled_index_history=replay.exhausted_filled_index_history,
        )
        if current_resource is None or len(current_edge) != len(replay.exhausted_edge_baseline):
            return False
        return all(
            value
            == (
                replay.exhausted_edge_fill_color
                if index in current_resource.filled_indexes
                else replay.exhausted_edge_baseline[index]
            )
            for index, value in enumerate(current_edge)
        )

    def _clear_child_isolation_execution(self) -> None:
        self._active_child_isolation_relation_key = None
        self._active_child_isolation_hypothesis_key = None
        self._active_child_isolation_frozen_mediator_center = None
        self._active_child_isolation_frozen_mediator_signature = None
        self._active_child_isolation_frozen_endpoint_centers = ()
        self._active_child_isolation_frozen_endpoint_signature = ()
        self._active_child_isolation_frozen_connector_signature = None
        self._active_child_isolation_frozen_mediator_color = None
        self._active_child_isolation_target_signature = None
        self._active_child_isolation_recovery_actions = ()

    def _latch_hierarchy_lineage_failure(
        self,
        *,
        level_index: int,
        plan_signature: str,
        phase: str,
    ) -> None:
        relation_key = (
            self._active_child_isolation_relation_key
            or self._active_hierarchy_relation_key
            or "unbound-hierarchy-relation"
        )
        failure = (level_index, relation_key, plan_signature, phase)
        self._failed_hierarchy_lineages.add(failure)
        self._hierarchy_lineage_lost = failure
        interrupted_replay = self._resource_interrupted_paired_replay
        if interrupted_replay is not None and interrupted_replay.setup_replay_started:
            self._resource_interrupted_paired_replay = None

    @staticmethod
    def _exploration_root_key(
        scene: VisualScene,
        *,
        kind: str,
        coordinate: Coordinate,
    ) -> _ExplorationRootKey:
        return (scene.frame_hash, kind, coordinate.x, coordinate.y)

    def _remember_exploration_root(
        self,
        scene: VisualScene,
        *,
        kind: str,
        coordinate: Coordinate,
    ) -> None:
        if self._episode_exploration_root is None:
            self._episode_exploration_root = self._exploration_root_key(
                scene,
                kind=kind,
                coordinate=coordinate,
            )

    def _unsolved_pairs(self, scene: VisualScene) -> tuple[tuple[VisualObject, VisualObject], ...]:
        return _unsolved_mediator_targets(scene)

    def _probe_coordinate(
        self,
        scene: VisualScene,
        *,
        kind: str = "coordinate",
    ) -> Coordinate:
        if self._exploration_root_capacity_exhausted:
            raise PolicyError("level-scoped exploration-root capacity exhausted")
        pairs = self._unsolved_pairs(scene)
        centers = tuple((item.center_x, item.center_y) for item in scene.endpoints)
        candidates: list[tuple[float, int, int]] = []
        origins = tuple(target.rounded_center for _, target in pairs) or (
            (scene.width // 2, scene.height // 2),
        )
        for origin_x, origin_y in origins[: self._max_coordinate_candidates]:
            for radius, dx, dy in (
                (11, 1, 0),
                (11, -1, 0),
                (11, 0, 1),
                (11, 0, -1),
                (16, 1, 1),
                (16, -1, 1),
                (16, 1, -1),
                (16, -1, -1),
            ):
                scale = radius / max(1.0, math.hypot(dx, dy))
                x = round(origin_x + dx * scale)
                y = round(origin_y + dy * scale)
                if not scene.is_open(x, y):
                    continue
                nearest = min(
                    (_distance((x, y), center) for center in centers),
                    default=float(scene.width + scene.height),
                )
                candidates.append((nearest, x, y))
        if not candidates:
            raise PolicyError("no causally bounded readable coordinate probe is available")
        unique = sorted(set(candidates), key=lambda item: (-item[0], item[2], item[1]))
        bounded = unique[: self._max_coordinate_candidates]
        start = self._probe_ordinal % len(bounded)
        for offset in range(len(bounded)):
            selected = bounded[(start + offset) % len(bounded)]
            coordinate = Coordinate(selected[1], selected[2])
            if self._episode_exploration_root is None and (
                self._exploration_root_key(
                    scene,
                    kind=kind,
                    coordinate=coordinate,
                )
                in self._failed_exploration_roots
            ):
                continue
            self._probe_ordinal += offset + 1
            return coordinate
        raise PolicyError("all bounded coordinate-probe episode roots already failed")

    def _activation_coordinate(
        self,
        scene: VisualScene,
        *,
        completed_target_center: tuple[int, int] | None = None,
    ) -> Coordinate | None:
        if self._exploration_root_capacity_exhausted:
            raise PolicyError("level-scoped exploration-root capacity exhausted")
        if completed_target_center is None:
            hubs = tuple(hub for hub, _target in self._unsolved_pairs(scene))
        else:
            hubs = _remaining_unsatisfied_affine_hubs(
                scene,
                completed_target_center=completed_target_center,
            )
        candidates: list[tuple[float, str, VisualObject]] = []
        for hub in hubs:
            group = _unique_affine_endpoint_group(scene, hub)
            if group is None:
                continue
            for item in group:
                if item.object_ref in self._attempted_activation_refs or (
                    self._last_active_color is not None
                    and (
                        item.color == self._last_active_color
                        or not _role_swap_remains_readable(
                            scene,
                            item,
                            active_color=self._last_active_color,
                        )
                    )
                ):
                    continue
                coordinate = Coordinate(*item.rounded_center)
                if self._episode_exploration_root is None and (
                    self._exploration_root_key(
                        scene,
                        kind="activation",
                        coordinate=coordinate,
                    )
                    in self._failed_exploration_roots
                ):
                    continue
                candidates.append(
                    (
                        _distance((item.center_x, item.center_y), (hub.center_x, hub.center_y)),
                        item.object_ref,
                        item,
                    )
                )
        if not candidates:
            return None
        candidates.sort(key=lambda item: item[:2])
        minimum_distance = candidates[0][0]
        nearest = tuple(
            item for item in candidates if math.isclose(item[0], minimum_distance, abs_tol=1e-9)
        )
        if self._last_active_color is not None and len(nearest) != 1:
            return None
        selected = nearest[0][2]
        x, y = selected.rounded_center
        coordinate = Coordinate(x, y)
        self._attempted_activation_refs.add(selected.object_ref)
        return coordinate

    def _install_plan(self, mechanic: AffineMechanic, scene: VisualScene) -> bool:
        active = tuple(item for item in scene.endpoints if item.color == mechanic.active_color)
        if len(active) != 1:
            return False
        movers: list[VisualObject] = [active[0]]
        used_refs = {active[0].object_ref}
        for center in mechanic.anchor_centers:
            matches = tuple(
                item
                for item in scene.endpoints
                if item.rounded_center == center and item.object_ref not in used_refs
            )
            if len(matches) != 1:
                return False
            movers.append(matches[0])
            used_refs.add(matches[0].object_ref)
        if len(movers) != mechanic.arity:
            return False
        points = _radial_plan_points(
            scene,
            target=mechanic.target_center,
            movers=tuple(movers),
            rejected_signatures=self._failed_plan_signatures,
        )
        if points is None:
            return False
        signature = ";".join(f"{item.x},{item.y}" for item in points)
        plan_id = (
            "visual-plan:"
            + hashlib.sha256(f"{mechanic.mechanic_ref}|{signature}".encode("ascii")).hexdigest()[
                :20
            ]
        )
        actions: list[PlannedClick] = []
        for index, anchor in enumerate(mechanic.anchor_centers):
            actions.append(
                PlannedClick(
                    coordinate=points[index],
                    purpose=VisualActionPurpose.PROGRESS,
                    expectation="place active endpoint at a target-relative support point",
                    mechanic_ref=mechanic.mechanic_ref,
                    plan_id=plan_id,
                    plan_signature=signature,
                    target_center=mechanic.target_center,
                    mediator_color=mechanic.mediator_color,
                    arity=mechanic.arity,
                )
            )
            actions.append(
                PlannedClick(
                    coordinate=Coordinate(*anchor),
                    purpose=VisualActionPurpose.PROBE,
                    expectation="exchange active and fixed endpoint roles without global reset",
                    mechanic_ref=mechanic.mechanic_ref,
                    plan_id=plan_id,
                    plan_signature=signature,
                    target_center=mechanic.target_center,
                    mediator_color=mechanic.mediator_color,
                    arity=mechanic.arity,
                )
            )
        actions.append(
            PlannedClick(
                coordinate=points[-1],
                purpose=VisualActionPurpose.PROGRESS,
                expectation="complete the observed affine composition at the matched target",
                mechanic_ref=mechanic.mechanic_ref,
                plan_id=plan_id,
                plan_signature=signature,
                target_center=mechanic.target_center,
                mediator_color=mechanic.mediator_color,
                arity=mechanic.arity,
                completes_local_target=True,
            )
        )
        self._plan.extend(actions)
        return True

    def _install_hierarchy_plan(
        self,
        plan: _HierarchyPlan,
        *,
        relation_key: str,
    ) -> None:
        self._plan.clear()
        self._plan.extend(plan.actions)
        self._active_hierarchy_signature = plan.signature
        self._active_hierarchy_relation_key = relation_key
        self._active_hierarchy_supports = plan.supports
        self._active_hierarchy_support_weights = plan.support_weights
        self._active_hierarchy_recovery_actions = plan.recovery_actions
        self._active_carrier_source_attachment_replay_context = (
            plan.carrier_source_attachment_replay_context
        )
        self._active_crossed_delivery_replay_context = (
            plan.carrier_source_crossed_delivery_replay_context
        )
        self._active_carried_source_recovery_support_indexes = ()
        if plan.carrier_source_attachment_replay_context is not None:
            self._active_carrier_source_setup_start_action_count = self._episode_action6_count
            self._active_carrier_source_setup_action_count = None
            self._active_carrier_source_crossed_forward_action_count = None
        else:
            self._active_carrier_source_setup_start_action_count = None
            self._active_carrier_source_setup_action_count = None
            self._active_carrier_source_crossed_forward_action_count = None

    def _install_child_isolation_plan(self, plan: _ChildIsolationPlan) -> None:
        self._plan.clear()
        self._plan.extend(plan.actions)
        self._active_child_isolation_relation_key = plan.relation_key
        self._active_child_isolation_hypothesis_key = plan.hypothesis_key
        self._active_child_isolation_frozen_mediator_center = plan.frozen_mediator_center
        self._active_child_isolation_frozen_mediator_signature = plan.frozen_mediator_signature
        self._active_child_isolation_frozen_endpoint_centers = plan.frozen_endpoint_centers
        self._active_child_isolation_frozen_endpoint_signature = plan.frozen_endpoint_signature
        self._active_child_isolation_frozen_connector_signature = plan.frozen_connector_signature
        self._active_child_isolation_frozen_mediator_color = plan.frozen_mediator_color
        self._active_child_isolation_target_signature = plan.target_signature
        self._active_child_isolation_recovery_actions = plan.recovery_actions

    def select(self, observation: Observation) -> ActionRequest:
        if observation.state in {GameStateName.GAME_OVER, GameStateName.NOT_PLAYED}:
            if self._active_crossed_replay_resource_lineage is not None:
                self._clear_crossed_replay_execution()
            action = ActionRequest(ActionName.RESET)
            self._stage_pending(
                observation,
                action,
                purpose=VisualActionPurpose.MANDATORY_RESET,
                prediction="reset lifecycle while retaining game-scoped mechanics",
            )
            return action
        if observation.state is GameStateName.WIN:
            if self._active_crossed_replay_resource_lineage is not None:
                self._clear_crossed_replay_execution()
            raise PolicyError("the official environment already reports WIN")
        if observation.state is GameStateName.UNKNOWN:
            interrupted_setup_replay = self._resource_interrupted_paired_replay
            self._resource_interrupted_paired_replay = None
            if (
                interrupted_setup_replay is not None
                or self._active_crossed_replay_resource_lineage is not None
            ):
                self._clear_crossed_replay_execution()
            raise PolicyError("cannot act on an unknown environment state")
        if observation.levels_completed < self._level_index:
            raise PolicyError("levels_completed regressed within one policy lifetime")
        if observation.levels_completed > self._level_index:
            self._begin_level(observation)
        post_marker_bridge = self._post_marker_resource_reset_bridge
        if post_marker_bridge is not None:
            if post_marker_bridge.game_over_observed:
                if (
                    self._reset_epoch_index == post_marker_bridge.authorized_reset_epoch
                    and self._install_post_marker_reset_plan(observation)
                ):
                    post_marker_bridge = None
                else:
                    raise PolicyError(
                        "the one authorized fresh reset epoch did not yield the exact "
                        "same-child composite-cargo plan"
                    )
            else:
                if ActionName.ACTION6 not in observation.available_actions:
                    self._post_marker_resource_reset_bridge = None
                    raise PolicyError(
                        "the exact post-marker resource bridge action became unavailable"
                    )
                if (
                    self._episode_action6_count >= post_marker_bridge.exhausted_after_actions
                    or not self._post_marker_resource_bridge_matches(observation)
                ):
                    self._post_marker_resource_reset_bridge = None
                    raise PolicyError(
                        "the post-marker board-no-op or learned resource prefix no longer "
                        "matches; no unrelated action is authorized"
                    )
                next_action_count = self._episode_action6_count + 1
                action = ActionRequest(
                    ActionName.ACTION6,
                    post_marker_bridge.no_op_coordinate,
                )
                self._stage_pending(
                    observation,
                    action,
                    purpose=VisualActionPurpose.PROBE,
                    prediction=(
                        "repeat one observation-proven board no-op to reach the exact learned "
                        "resource GAME_OVER boundary"
                    ),
                    plan_signature=(
                        "post-marker-resource-reset-bridge:"
                        f"{post_marker_bridge.marker_hypothesis_key}:{next_action_count}"
                    ),
                )
                return action
        queued_composite_certificate = (
            self._plan[0].post_access_composite_exit_certificate if self._plan else None
        )
        queued_marker_certificate = (
            self._plan[0].post_access_composite_marker_certificate if self._plan else None
        )
        access_closed_into_exact_composite = bool(
            self._post_deposit_mediator_access_closed is not None
            and (
                (
                    queued_composite_certificate is not None
                    and queued_composite_certificate.parent_access_hypothesis_key
                    == self._post_deposit_mediator_access_closed
                )
                or (
                    queued_marker_certificate is not None
                    and queued_marker_certificate.parent_access_hypothesis_key
                    == self._post_deposit_mediator_access_closed
                )
            )
        )
        composite_closed_into_exact_marker = bool(
            self._post_access_composite_exit_closed is not None
            and queued_marker_certificate is not None
            and queued_marker_certificate.parent_composite_hypothesis_key
            == self._post_access_composite_exit_closed
        )
        if self._post_access_composite_marker_closed is not None:
            raise PolicyError(
                "the one-shot post-access composite-marker sufficiency hypothesis "
                "was rejected; no repeated or unrelated continuation is authorized"
            )
        if (
            self._post_access_composite_exit_closed is not None
            and not composite_closed_into_exact_marker
        ):
            raise PolicyError(
                "the one-shot post-access composite-exit sufficiency hypothesis "
                "was rejected; no repeated or unrelated continuation is authorized"
            )
        if (
            self._post_deposit_mediator_access_closed is not None
            and not access_closed_into_exact_composite
        ):
            raise PolicyError(
                "the one-shot post-deposit mediator-access sufficiency hypothesis "
                "was rejected; no repeated or unrelated continuation is authorized"
            )
        if self._hierarchy_lineage_lost is not None:
            raise PolicyError(
                "hierarchy lineage was lost after a nonmatching returned consequence; "
                "no unrelated fallback is authorized"
            )
        interrupted_setup_replay = self._resource_interrupted_paired_replay
        if (
            interrupted_setup_replay is not None
            and not interrupted_setup_replay.setup_replay_started
        ):
            if (
                self._episode_action6_count != 0
                or interrupted_setup_replay.setup_action_count <= 0
                or interrupted_setup_replay.crossed_forward_action_count <= 0
                or interrupted_setup_replay.setup_action_count
                + interrupted_setup_replay.crossed_forward_action_count
                >= interrupted_setup_replay.observed_actions
                or not self._resource_setup_replay_prefix_matches(
                    observation,
                    interrupted_setup_replay,
                )
            ):
                self._resource_interrupted_paired_replay = None
                self._plan.clear()
                raise PolicyError(
                    "fresh setup replay no longer matches its exact reset, baseline, or "
                    "resource budget; no unrelated fallback is authorized"
                )
        elif interrupted_setup_replay is not None:
            active_context = self._active_carrier_source_attachment_replay_context
            context_matches = bool(
                active_context is not None
                and _carrier_source_attachment_context_key(active_context)
                == interrupted_setup_replay.context_key
            )
            remaining_setup_actions = (
                interrupted_setup_replay.setup_action_count - self._episode_action6_count
            )
            setup_matches = bool(
                self._plan
                and self._active_hierarchy_relation_key
                == interrupted_setup_replay.setup_relation_key
                and self._active_hierarchy_signature
                == interrupted_setup_replay.setup_plan_signature
                and context_matches
                and self._resource_setup_replay_prefix_matches(
                    observation,
                    interrupted_setup_replay,
                )
                and remaining_setup_actions > 0
                and len(self._plan) <= remaining_setup_actions
                and self._episode_action6_count
                + remaining_setup_actions
                + interrupted_setup_replay.crossed_forward_action_count
                < interrupted_setup_replay.observed_actions
            )
            if not setup_matches:
                plan_signature = (
                    self._plan[0].plan_signature
                    if self._plan
                    else interrupted_setup_replay.setup_plan_signature
                )
                self._latch_hierarchy_lineage_failure(
                    level_index=observation.levels_completed,
                    plan_signature=plan_signature,
                    phase=f"resource-setup-precondition:{self._step_index}",
                )
                self._clear_crossed_replay_execution()
                raise PolicyError(
                    "fresh setup replay, exact meter prefix, or remaining action budget "
                    "no longer matches; no further setup action is authorized"
                )
        if self._active_carried_source_recovery_support_indexes and not self._plan:
            raise PolicyError(
                "an exact carrier-source attachment remains active and requires an "
                "observation-derived target-delivery continuation"
            )

        active_crossed_lineage = self._active_crossed_replay_resource_lineage
        if active_crossed_lineage is not None and not self._plan:
            self._clear_crossed_replay_execution()
            raise PolicyError(
                "crossed resource lineage has no exact queued continuation; "
                "no unrelated fallback is authorized"
            )
        if self._plan:
            queued_crossed = self._plan[0]
            crossed_forward = _is_crossed_replay_forward_action(queued_crossed)
            crossed_inverse = _is_crossed_replay_inverse_action(
                queued_crossed,
                recovery_signature=self._crossed_delivery_recovery_signature,
            )
            access_certificate = queued_crossed.post_deposit_mediator_access_certificate
            composite_certificate = queued_crossed.post_access_composite_exit_certificate
            marker_certificate = queued_crossed.post_access_composite_marker_certificate
            crossed_family = bool(
                crossed_forward
                or crossed_inverse
                or access_certificate is not None
                or composite_certificate is not None
                or marker_certificate is not None
                or queued_crossed.carrier_source_paired_cargo_crossed_predecessor_family
                or queued_crossed.carrier_source_paired_cargo_crossed_delivery_step
            )
            resource_matches = bool(
                active_crossed_lineage is not None
                and self._active_crossed_resource_matches(observation)
            )
            forward_budget_closes = bool(
                active_crossed_lineage is not None
                and crossed_forward
                and active_crossed_lineage.forward_remaining_actions > 0
                and _strict_crossed_replay_budget_closes(
                    current_actions=self._episode_action6_count,
                    route_action_upper_bound=(active_crossed_lineage.forward_remaining_actions),
                    exhausted_after_actions=(active_crossed_lineage.exhausted_after_actions),
                )
            )
            inverse_prefix_open = bool(
                active_crossed_lineage is not None
                and crossed_inverse
                and active_crossed_lineage.forward_remaining_actions == 0
                and self._episode_action6_count < active_crossed_lineage.exhausted_after_actions
            )
            access_prefix_open = bool(
                active_crossed_lineage is not None
                and access_certificate is not None
                and _post_deposit_mediator_access_step_is_compatible(queued_crossed)
                and active_crossed_lineage.forward_remaining_actions == 0
                and self._episode_action6_count == access_certificate.resource_action_count
                and active_crossed_lineage.exhausted_after_actions
                == access_certificate.exhausted_after_actions
                and _strict_crossed_replay_budget_closes(
                    current_actions=self._episode_action6_count,
                    route_action_upper_bound=1,
                    exhausted_after_actions=(active_crossed_lineage.exhausted_after_actions),
                )
            )
            composite_prefix_open = bool(
                active_crossed_lineage is not None
                and composite_certificate is not None
                and _post_access_composite_exit_step_is_compatible(queued_crossed)
                and active_crossed_lineage.forward_remaining_actions == 0
                and self._episode_action6_count == composite_certificate.resource_action_count
                and active_crossed_lineage.exhausted_after_actions
                == composite_certificate.exhausted_after_actions
                and _strict_crossed_replay_budget_closes(
                    current_actions=self._episode_action6_count,
                    route_action_upper_bound=1,
                    exhausted_after_actions=(active_crossed_lineage.exhausted_after_actions),
                )
            )
            marker_prefix_open = bool(
                active_crossed_lineage is not None
                and marker_certificate is not None
                and _post_access_composite_marker_step_is_compatible(queued_crossed)
                and active_crossed_lineage.forward_remaining_actions == 0
                and self._episode_action6_count == marker_certificate.resource_action_count
                and active_crossed_lineage.exhausted_after_actions
                == marker_certificate.exhausted_after_actions
                and _strict_crossed_replay_budget_closes(
                    current_actions=self._episode_action6_count,
                    route_action_upper_bound=1,
                    exhausted_after_actions=(active_crossed_lineage.exhausted_after_actions),
                )
            )
            if (active_crossed_lineage is not None or crossed_family) and not (
                resource_matches
                and (
                    forward_budget_closes
                    or inverse_prefix_open
                    or access_prefix_open
                    or composite_prefix_open
                    or marker_prefix_open
                )
            ):
                self._latch_hierarchy_lineage_failure(
                    level_index=observation.levels_completed,
                    plan_signature=queued_crossed.plan_signature,
                    phase=f"crossed-resource-precondition:{self._step_index}",
                )
                self._clear_crossed_replay_execution()
                raise PolicyError(
                    "crossed resource lineage, exact meter prefix, or remaining action "
                    "budget no longer matches; no further crossed action is authorized"
                )

        if self._plan and ActionName.ACTION6 not in observation.available_actions:
            blocked_plan = self._plan[0]
            self._failed_plan_signatures.add(blocked_plan.plan_signature)
            hierarchy_blocked = blocked_plan.plan_signature.startswith(_HIERARCHY_PLAN_PREFIXES)
            if hierarchy_blocked:
                self._latch_hierarchy_lineage_failure(
                    level_index=observation.levels_completed,
                    plan_signature=blocked_plan.plan_signature,
                    phase=f"queued-action-unavailable:{self._step_index}",
                )
            self._plan.clear()
            self._active_hierarchy_signature = None
            self._active_hierarchy_relation_key = None
            self._active_hierarchy_supports = ()
            self._active_hierarchy_support_weights = ()
            self._active_hierarchy_recovery_actions = ()
            self._active_carrier_source_attachment_replay_context = None
            self._active_crossed_delivery_replay_context = None
            self._active_carried_source_recovery_support_indexes = ()
            self._resource_interrupted_paired_replay = None
            self._active_crossed_replay_resource_lineage = None
            self._crossed_delivery_recovery_signature = None
            self._clear_child_isolation_execution()
            self._last_probe_failed = True
            if hierarchy_blocked:
                raise PolicyError(
                    "queued hierarchy action became unavailable; no unrelated fallback "
                    "is authorized"
                )
        if (
            ActionName.ACTION6 in observation.available_actions
            and interrupted_setup_replay is None
            and not (
                self._plan and self._plan[0].plan_signature.startswith(_HIERARCHY_PLAN_PREFIXES)
            )
        ):
            marker_scene = extract_visual_scene(observation.frames[-1])
            marker_groups = _embedded_marker_groups(marker_scene)
            marker_plan: PlannedClick | None = None
            structural_rejections: set[str] = set()
            for _attempt in range(64):
                target_identity_constraints = {
                    _marker_target_identity_constraint(marker_color)
                    for marker_color in self._marker_target_identity_constraints
                }
                candidate_plan = _embedded_marker_plan(
                    marker_scene,
                    level_index=observation.levels_completed,
                    active_color=self._last_active_color,
                    staged_marker_color=self._marker_stage_pending_switch,
                    rejected_signatures=(
                        self._failed_plan_signatures
                        | structural_rejections
                        | target_identity_constraints
                    ),
                    allow_reacquisition=self._marker_reacquire_after_local_solve,
                )
                if candidate_plan is None:
                    break
                active_endpoint = _embedded_marker_active_endpoint(
                    marker_scene,
                    active_color=self._last_active_color,
                )
                if active_endpoint is None:
                    marker_plan = candidate_plan
                    break
                structural_key = _marker_structural_action_key(
                    marker_scene,
                    active_endpoint,
                    candidate_plan.plan_signature,
                )
                if structural_key not in self._marker_structural_actions:
                    marker_plan = candidate_plan
                    self._marker_structural_actions.add(structural_key)
                    self._marker_structural_action_order.append(structural_key)
                    while (
                        len(self._marker_structural_action_order)
                        > self._MAX_MARKER_STRUCTURAL_ACTIONS
                    ):
                        expired = self._marker_structural_action_order.popleft()
                        self._marker_structural_actions.discard(expired)
                    break
                structural_rejections.add(candidate_plan.plan_signature)
            if marker_plan is not None:
                # Marker plans contain exactly one locally justified action and
                # are recomputed from the returned frame.  A queued radial
                # hypothesis for this level must not override stronger visible
                # grouping evidence.
                self._plan.clear()
                self._affine_reacquire_target_center = None
                if marker_plan.stages_for_switch:
                    self._marker_stage_pending_switch = marker_plan.mediator_color
                elif self._marker_stage_pending_switch is not None:
                    self._marker_stage_pending_switch = None
                action = ActionRequest(ActionName.ACTION6, marker_plan.coordinate)
                self._stage_pending(
                    observation,
                    action,
                    purpose=marker_plan.purpose,
                    prediction=marker_plan.expectation,
                    mechanic_refs=(marker_plan.mechanic_ref,),
                    plan_signature=marker_plan.plan_signature,
                    target_center=marker_plan.target_center,
                    mediator_color=marker_plan.mediator_color,
                    arity=marker_plan.arity,
                    completes_local_target=marker_plan.completes_local_target,
                )
                return action
            if any(
                group.mediator.rounded_center != group.target.rounded_center
                for group in marker_groups
            ):
                active_is_ambiguous = (
                    _embedded_marker_active_endpoint(
                        marker_scene,
                        active_color=self._last_active_color,
                    )
                    is None
                )
                if active_is_ambiguous and not self._marker_bootstrap_attempted:
                    coordinate = self._probe_coordinate(
                        marker_scene,
                        kind="marker-bootstrap",
                    )
                    if any(
                        _distance(endpoint.rounded_center, (coordinate.x, coordinate.y)) <= 2.25
                        for group in marker_groups
                        for endpoint in group.endpoints
                    ):
                        raise PolicyError(
                            "embedded marker bootstrap coordinate overlaps an endpoint"
                        )
                    self._plan.clear()
                    action = ActionRequest(ActionName.ACTION6, coordinate)
                    signature = (
                        f"marker-bootstrap:{observation.levels_completed}:"
                        f"{marker_scene.frame_hash}:{coordinate.x},{coordinate.y}"
                    )
                    self._stage_pending(
                        observation,
                        action,
                        purpose=VisualActionPurpose.PROBE,
                        prediction=(
                            "identify the active marker endpoint with one bounded "
                            "open-space intervention"
                        ),
                        plan_signature=signature,
                    )
                    self._remember_exploration_root(
                        marker_scene,
                        kind="marker-bootstrap",
                        coordinate=coordinate,
                    )
                    self._marker_bootstrap_attempted = True
                    return action
                raise PolicyError(
                    "embedded marker group is unresolved but has no bounded same-group action"
                )
        queued_carried_source_support_indexes = (
            self._active_carried_source_recovery_support_indexes
            if self._plan
            and self._plan[0].plan_signature.startswith(
                "affine-carrier-source-occlusion-hierarchy-recovery:"
            )
            else None
        )
        if (
            self._plan
            and self._plan[0].plan_signature.startswith(_HIERARCHY_PLAN_PREFIXES)
            and (
                self._last_active_color is None
                or not _hierarchy_planned_click_is_safe(
                    extract_visual_scene(observation.frames[-1]),
                    self._plan[0],
                    active_color=self._last_active_color,
                    required_carried_source_support_indexes=(queued_carried_source_support_indexes),
                )
            )
        ):
            unsafe_plan = self._plan[0]
            self._failed_plan_signatures.add(unsafe_plan.plan_signature)
            self._latch_hierarchy_lineage_failure(
                level_index=observation.levels_completed,
                plan_signature=unsafe_plan.plan_signature,
                phase=f"queued-precondition-mismatch:{self._step_index}",
            )
            self._plan.clear()
            self._active_hierarchy_signature = None
            self._active_hierarchy_relation_key = None
            self._active_hierarchy_supports = ()
            self._active_hierarchy_support_weights = ()
            self._active_hierarchy_recovery_actions = ()
            self._active_carrier_source_attachment_replay_context = None
            self._active_crossed_delivery_replay_context = None
            self._active_carried_source_recovery_support_indexes = ()
            self._active_crossed_replay_resource_lineage = None
            self._crossed_delivery_recovery_signature = None
            self._clear_child_isolation_execution()
            raise PolicyError(
                "queued hierarchy precondition no longer matches the returned frame; "
                "no unrelated fallback is authorized"
            )
        if self._plan:
            queued = self._plan.popleft()
            planned = queued
            if queued.plan_signature.startswith(_HIERARCHY_PLAN_PREFIXES):
                assert self._last_active_color is not None
                matched = _hierarchy_planned_click_matching_candidate(
                    extract_visual_scene(observation.frames[-1]),
                    queued,
                    active_color=self._last_active_color,
                    required_carried_source_support_indexes=(queued_carried_source_support_indexes),
                )
                if matched is None:
                    raise PolicyError("validated hierarchy action lost its exact raster lineage")
                planned = matched
            action = ActionRequest(ActionName.ACTION6, planned.coordinate)
            self._stage_pending(
                observation,
                action,
                purpose=planned.purpose,
                prediction=planned.expectation,
                mechanic_refs=(planned.mechanic_ref,),
                plan_signature=planned.plan_signature,
                target_center=planned.target_center,
                mediator_color=planned.mediator_color,
                arity=planned.arity,
                completes_local_target=planned.completes_local_target,
                completes_hierarchy=planned.completes_hierarchy,
                completes_child_isolation=planned.completes_child_isolation,
                completes_child_recovery=planned.completes_child_recovery,
                expected_child_mediator_center=(planned.expected_child_mediator_center),
                expected_child_mediator_signature=(planned.expected_child_mediator_signature),
                expected_child_endpoint_centers=(planned.expected_child_endpoint_centers),
                expected_child_endpoint_signature=(planned.expected_child_endpoint_signature),
                expected_child_connector_signature=(planned.expected_child_connector_signature),
                expected_active_center=planned.expected_active_center,
                expected_child_protected_raster_hash=(planned.expected_child_protected_raster_hash),
                expected_child_raster_signature=(planned.expected_child_raster_signature),
                expected_occluded_endpoint_centers=(planned.expected_occluded_endpoint_centers),
                expected_occluded_endpoint_cells=(planned.expected_occluded_endpoint_cells),
                expected_visible_endpoint_count=planned.expected_visible_endpoint_count,
                expected_visible_mediator_count=planned.expected_visible_mediator_count,
                carrier_source_recovery_candidate=planned,
            )
            return action

        if ActionName.ACTION6 in observation.available_actions:
            scene = extract_visual_scene(observation.frames[-1])
            learner = self._ensure_learner(observation)
            deferred_hierarchy: _AffineHierarchy | None = None
            deferred_hierarchy_ref: str | None = None
            deferred_hierarchy_reason: str | None = None
            transferable = self._affine_ledger_ref is not None and learner.ledger.get(
                self._affine_ledger_ref
            ).status in {MechanicStatus.SUPPORTED, MechanicStatus.STABLE_WITHIN_SCOPE}
            if self._last_active_color is not None and transferable:
                marker_search_budget = _HierarchySearchBudget(_MAX_HIERARCHY_SEARCH_BUDGET)
                try:
                    marker_cargo_pair = _marker_multi_source_composite_cargo_relation(
                        scene,
                        active_color=self._last_active_color,
                        level_index=observation.levels_completed,
                        search_budget=marker_search_budget,
                    )
                except _HierarchySearchExhausted as exc:
                    self._hierarchy_search_deferred_count += 1
                    self._last_hierarchy_search_residual = str(exc)
                    self._last_probe_failed = True
                    raise PolicyError(
                        f"{exc}; no unrelated coordinate fallback is authorized"
                    ) from exc
                if marker_cargo_pair is not None:
                    marker_hierarchy, marker_cargo_relation = marker_cargo_pair
                    try:
                        marker_cargo_plan = _same_child_composite_cargo_plan(
                            scene,
                            marker_hierarchy,
                            marker_cargo_relation,
                            rejected_signatures=self._failed_plan_signatures,
                            search_budget=marker_search_budget,
                        )
                    except _HierarchySearchExhausted as exc:
                        marker_cargo_plan = None
                        marker_cargo_residual = str(exc)
                    else:
                        marker_cargo_residual = (
                            "the exact marker-group multi-source relation has no bounded "
                            "parser-safe accumulation route"
                        )
                    if marker_cargo_plan is None:
                        self._hierarchy_search_deferred_count += 1
                        self._last_hierarchy_search_residual = marker_cargo_residual
                        self._last_probe_failed = True
                        raise PolicyError(
                            f"{marker_cargo_residual}; no unrelated coordinate fallback "
                            "is authorized"
                        )
                    self._install_hierarchy_plan(
                        marker_cargo_plan,
                        relation_key=marker_cargo_relation.relation_key,
                    )
                    planned = self._plan.popleft()
                    action = ActionRequest(ActionName.ACTION6, planned.coordinate)
                    self._stage_pending(
                        observation,
                        action,
                        purpose=planned.purpose,
                        prediction=planned.expectation,
                        mechanic_refs=(planned.mechanic_ref,),
                        plan_signature=planned.plan_signature,
                        target_center=planned.target_center,
                        mediator_color=planned.mediator_color,
                        arity=planned.arity,
                        completes_hierarchy=planned.completes_hierarchy,
                        expected_active_center=planned.expected_active_center,
                        expected_child_protected_raster_hash=(
                            planned.expected_child_protected_raster_hash
                        ),
                        expected_visible_endpoint_count=(planned.expected_visible_endpoint_count),
                        expected_visible_mediator_count=(planned.expected_visible_mediator_count),
                        carrier_source_recovery_candidate=planned,
                    )
                    return action
                hierarchy: _AffineHierarchy | None = None
                hierarchy_plan: _HierarchyPlan | None = None
                child_isolation_plan: _ChildIsolationPlan | None = None
                hierarchy_relation_key: str | None = None
                starting_resource_setup_replay = False
                search_budget = _HierarchySearchBudget(_MAX_HIERARCHY_SEARCH_BUDGET)
                try:
                    hierarchy = _unique_affine_hierarchy(
                        scene,
                        active_color=self._last_active_color,
                        search_budget=search_budget,
                    )
                    if hierarchy is not None:
                        deferred_hierarchy = hierarchy
                        deferred_hierarchy_ref = hierarchy.mechanic_ref
                        hierarchy_relation_key = _hierarchy_relation_key(
                            scene,
                            hierarchy,
                            level_index=observation.levels_completed,
                        )
                        child_hypothesis_keys = frozenset(
                            _child_isolation_hypothesis_key(
                                scene,
                                child,
                                relation_key=hierarchy_relation_key,
                            )
                            for child in hierarchy.children
                        )
                        self._current_child_isolation_hypothesis_keys = child_hypothesis_keys
                        self._child_isolation_hypotheses_by_relation[hierarchy_relation_key] = (
                            child_hypothesis_keys
                        )
                        all_child_hypotheses_rejected = bool(
                            child_hypothesis_keys
                        ) and child_hypothesis_keys <= (
                            self._failed_child_isolation_hypothesis_keys
                        )
                        untested_child_hypotheses = child_hypothesis_keys - (
                            self._failed_child_isolation_hypothesis_keys
                        )
                        joint_relation_rejected = (
                            hierarchy_relation_key in self._failed_hierarchy_relation_keys
                        )
                        weighted_relation_rejected = (
                            hierarchy_relation_key in self._failed_weighted_hierarchy_relation_keys
                        )
                        visible_node_relation_rejected = (
                            hierarchy_relation_key
                            in self._failed_visible_node_hierarchy_relation_keys
                        )
                        if untested_child_hypotheses:
                            child_isolation_plan = _child_isolation_plan(
                                scene,
                                hierarchy,
                                level_index=observation.levels_completed,
                                rejected_signatures=self._failed_plan_signatures,
                                rejected_hypothesis_keys=(
                                    self._failed_child_isolation_hypothesis_keys
                                ),
                                search_budget=search_budget,
                            )
                        if child_isolation_plan is None:
                            if (
                                joint_relation_rejected
                                and weighted_relation_rejected
                                and visible_node_relation_rejected
                            ):
                                if all_child_hypotheses_rejected:
                                    bridge_relation = _composite_bridge_relation(
                                        scene,
                                        hierarchy,
                                        level_index=observation.levels_completed,
                                    )
                                    if bridge_relation is None:
                                        deferred_hierarchy_reason = (
                                            "all structurally distinct child-only sufficiency, "
                                            "equal-weight, arity-weighted, and visible-node-weighted "
                                            "hierarchy hypotheses were already falsified and no "
                                            "twice-witnessed composite sinks with a unique "
                                            "proximity assignment are readable"
                                        )
                                    elif (
                                        bridge_relation.relation_key
                                        in self._failed_bridge_hierarchy_relation_keys
                                    ):
                                        residual_linked_relation = (
                                            _residual_linked_hierarchy_relation(
                                                scene,
                                                hierarchy,
                                                level_index=observation.levels_completed,
                                            )
                                        )
                                        if residual_linked_relation is None:
                                            deferred_hierarchy_reason = (
                                                "the proximity-assigned paired composite-sink "
                                                "hypothesis was falsified and no unique singleton "
                                                "raw-target color belongs to exactly one witnessed "
                                                "composite residual palette"
                                            )
                                        elif (
                                            residual_linked_relation.relation_key
                                            in self._failed_residual_linked_hierarchy_relation_keys
                                        ):
                                            external_residual_linked_relation = _external_residual_linked_hierarchy_relation(
                                                scene,
                                                hierarchy,
                                                level_index=(observation.levels_completed),
                                                rejected_mixed_relation_keys=(
                                                    self._failed_residual_linked_hierarchy_relation_keys
                                                ),
                                            )
                                            if external_residual_linked_relation is None:
                                                deferred_hierarchy_reason = (
                                                    "both child strata, all parent-composition "
                                                    "families, the proximity-assigned paired "
                                                    "composite-sink hypothesis, and the "
                                                    "residual-linked mixed-support hypothesis were "
                                                    "already falsified, but no unique external "
                                                    "carrier-mask residual chain is readable"
                                                )
                                            elif (
                                                external_residual_linked_relation.relation_key
                                                in self._failed_external_residual_linked_hierarchy_relation_keys
                                            ):
                                                raw_matching_composite_relation = _raw_matching_composite_hierarchy_relation(
                                                    scene,
                                                    hierarchy,
                                                    level_index=(observation.levels_completed),
                                                    rejected_mixed_relation_keys=(
                                                        self._failed_residual_linked_hierarchy_relation_keys
                                                    ),
                                                    rejected_external_relation_keys=(
                                                        self._failed_external_residual_linked_hierarchy_relation_keys
                                                    ),
                                                )
                                                if raw_matching_composite_relation is None:
                                                    deferred_hierarchy_reason = (
                                                        "all earlier hierarchy families and the unique "
                                                        "external carrier-mask residual-chain hypothesis "
                                                        "were already falsified, but no unique observed "
                                                        "composite sink strictly contains the retained "
                                                        "singleton raw support"
                                                    )
                                                elif (
                                                    raw_matching_composite_relation.relation_key
                                                    in self._failed_raw_matching_composite_hierarchy_relation_keys
                                                ):
                                                    external_own_composite_relation = _external_own_composite_hierarchy_relation(
                                                        scene,
                                                        hierarchy,
                                                        level_index=(observation.levels_completed),
                                                        rejected_bridge_relation_keys=(
                                                            self._failed_bridge_hierarchy_relation_keys
                                                        ),
                                                        rejected_mixed_relation_keys=(
                                                            self._failed_residual_linked_hierarchy_relation_keys
                                                        ),
                                                        rejected_external_relation_keys=(
                                                            self._failed_external_residual_linked_hierarchy_relation_keys
                                                        ),
                                                        rejected_raw_matching_relation_keys=(
                                                            self._failed_raw_matching_composite_hierarchy_relation_keys
                                                        ),
                                                    )
                                                    if external_own_composite_relation is None:
                                                        deferred_hierarchy_reason = (
                                                            "the bridge, mixed, external, and "
                                                            "raw-matching hierarchy relations were "
                                                            "falsified, but their evidence does not "
                                                            "identify one unique external-counterpart "
                                                            "and own-composite support tuple"
                                                        )
                                                    elif (
                                                        external_own_composite_relation.relation_key
                                                        in self._failed_external_own_composite_hierarchy_relation_keys
                                                    ):
                                                        carrier_source_relation = _carrier_source_occlusion_hierarchy_relation(
                                                            scene,
                                                            hierarchy,
                                                            level_index=(
                                                                observation.levels_completed
                                                            ),
                                                            rejected_bridge_relation_keys=(
                                                                self._failed_bridge_hierarchy_relation_keys
                                                            ),
                                                            rejected_mixed_relation_keys=(
                                                                self._failed_residual_linked_hierarchy_relation_keys
                                                            ),
                                                            rejected_external_relation_keys=(
                                                                self._failed_external_residual_linked_hierarchy_relation_keys
                                                            ),
                                                            rejected_raw_matching_relation_keys=(
                                                                self._failed_raw_matching_composite_hierarchy_relation_keys
                                                            ),
                                                            rejected_external_own_relation_keys=(
                                                                self._failed_external_own_composite_hierarchy_relation_keys
                                                            ),
                                                        )
                                                        pending_setup_replay: (
                                                            _ResourceInterruptedPairedReplay | None
                                                        ) = None
                                                        exact_setup_replay = False
                                                        if carrier_source_relation is None:
                                                            deferred_hierarchy_reason = (
                                                                "the bridge, mixed, external, raw-matching, "
                                                                "and external-own hierarchy relations were "
                                                                "falsified, but their evidence does not "
                                                                "identify one unique raw source and exact "
                                                                "carrier-mask counterpart source pair"
                                                            )
                                                        else:
                                                            pending_setup_replay = self._resource_interrupted_paired_replay
                                                            exact_setup_replay = bool(
                                                                pending_setup_replay is not None
                                                                and not pending_setup_replay.setup_replay_started
                                                                and carrier_source_relation.relation_key
                                                                == pending_setup_replay.setup_relation_key
                                                                and self._episode_action6_count == 0
                                                                and pending_setup_replay.setup_action_count
                                                                + pending_setup_replay.crossed_forward_action_count
                                                                < pending_setup_replay.observed_actions
                                                            )
                                                        if (
                                                            carrier_source_relation is not None
                                                            and pending_setup_replay is not None
                                                            and not exact_setup_replay
                                                        ):
                                                            deferred_hierarchy_reason = (
                                                                "the fresh resource replay token does not "
                                                                "match the regenerated carrier-source relation"
                                                            )
                                                        elif (
                                                            carrier_source_relation is not None
                                                            and carrier_source_relation.relation_key
                                                            in self._failed_carrier_source_occlusion_hierarchy_relation_keys
                                                            and not exact_setup_replay
                                                        ):
                                                            deferred_hierarchy_reason = (
                                                                "all bounded observation-grounded hierarchy "
                                                                "families, including the one-shot carrier-"
                                                                "source occlusion discriminator, were already "
                                                                "rejected or operationally exhausted by "
                                                                "official consequences"
                                                            )
                                                        elif carrier_source_relation is not None:
                                                            assert (
                                                                pending_setup_replay is not None
                                                                or not exact_setup_replay
                                                            )
                                                            hierarchy_plan = _carrier_source_occlusion_hierarchy_plan(
                                                                scene,
                                                                hierarchy,
                                                                carrier_source_relation,
                                                                level_index=(
                                                                    observation.levels_completed
                                                                ),
                                                                rejected_signatures=(
                                                                    self._failed_plan_signatures
                                                                ),
                                                                required_replay_plan_signature=(
                                                                    pending_setup_replay.setup_plan_signature
                                                                    if exact_setup_replay
                                                                    and pending_setup_replay
                                                                    is not None
                                                                    else None
                                                                ),
                                                                required_replay_context_key=(
                                                                    pending_setup_replay.context_key
                                                                    if exact_setup_replay
                                                                    and pending_setup_replay
                                                                    is not None
                                                                    else None
                                                                ),
                                                                search_budget=search_budget,
                                                            )
                                                            if hierarchy_plan is None:
                                                                deferred_hierarchy_reason = (
                                                                    "the unique carrier-matched source pair "
                                                                    "has no exact parser-safe reversible "
                                                                    "occlusion layout"
                                                                )
                                                            else:
                                                                hierarchy_relation_key = carrier_source_relation.relation_key
                                                                starting_resource_setup_replay = (
                                                                    exact_setup_replay
                                                                )
                                                    else:
                                                        hierarchy_plan = (
                                                            _external_own_composite_hierarchy_plan(
                                                                scene,
                                                                hierarchy,
                                                                external_own_composite_relation,
                                                                rejected_signatures=(
                                                                    self._failed_plan_signatures
                                                                ),
                                                                search_budget=search_budget,
                                                            )
                                                        )
                                                        if hierarchy_plan is None:
                                                            deferred_hierarchy_reason = (
                                                                "the unique external-own-composite "
                                                                "hypothesis has no exact target-surface-"
                                                                "preserving layout"
                                                            )
                                                        else:
                                                            hierarchy_relation_key = external_own_composite_relation.relation_key
                                                else:
                                                    hierarchy_plan = (
                                                        _raw_matching_composite_hierarchy_plan(
                                                            scene,
                                                            hierarchy,
                                                            raw_matching_composite_relation,
                                                            rejected_signatures=(
                                                                self._failed_plan_signatures
                                                            ),
                                                            search_budget=search_budget,
                                                        )
                                                    )
                                                    if hierarchy_plan is None:
                                                        deferred_hierarchy_reason = (
                                                            "the bounded raw-matching containing-composite "
                                                            "hypothesis has no exact target-surface-preserving "
                                                            "layout"
                                                        )
                                                    else:
                                                        hierarchy_relation_key = raw_matching_composite_relation.relation_key
                                            else:
                                                hierarchy_plan = (
                                                    _external_residual_linked_hierarchy_plan(
                                                        scene,
                                                        hierarchy,
                                                        external_residual_linked_relation,
                                                        rejected_signatures=(
                                                            self._failed_plan_signatures
                                                        ),
                                                        search_budget=search_budget,
                                                    )
                                                )
                                                if hierarchy_plan is None:
                                                    deferred_hierarchy_reason = (
                                                        "the unique external carrier-mask "
                                                        "residual-chain hypothesis has no exact "
                                                        "target-surface-preserving layout"
                                                    )
                                                else:
                                                    hierarchy_relation_key = external_residual_linked_relation.relation_key
                                        else:
                                            hierarchy_plan = _residual_linked_hierarchy_plan(
                                                scene,
                                                hierarchy,
                                                residual_linked_relation,
                                                rejected_signatures=(self._failed_plan_signatures),
                                                search_budget=search_budget,
                                            )
                                            if hierarchy_plan is None:
                                                deferred_hierarchy_reason = (
                                                    "the residual-linked mixed-support hypothesis "
                                                    "has no exact target-surface-preserving layout"
                                                )
                                            else:
                                                hierarchy_relation_key = (
                                                    residual_linked_relation.relation_key
                                                )
                                    else:
                                        hierarchy_plan = _bridge_hierarchy_plan(
                                            scene,
                                            hierarchy,
                                            bridge_relation,
                                            rejected_signatures=self._failed_plan_signatures,
                                            search_budget=search_budget,
                                        )
                                        if hierarchy_plan is None:
                                            deferred_hierarchy_reason = (
                                                "the proximity-assigned paired composite-sink "
                                                "hypothesis has "
                                                "no exact target-preserving paired layout"
                                            )
                                        else:
                                            hierarchy_relation_key = bridge_relation.relation_key
                                else:
                                    deferred_hierarchy_reason = (
                                        "an unfalsified structural child stratum has no exact "
                                        "target-protected isolation layout and all three bounded "
                                        "joint completion hypotheses were already falsified by "
                                        "official NOT_FINISHED consequences"
                                    )
                            elif joint_relation_rejected and weighted_relation_rejected:
                                hierarchy_plan = _hierarchy_visible_node_layout(
                                    scene,
                                    hierarchy,
                                    rejected_signatures=self._failed_plan_signatures,
                                    search_budget=search_budget,
                                )
                                if hierarchy_plan is None:
                                    deferred_hierarchy_reason = (
                                        "equal-weight and arity-weighted joint completion were "
                                        "falsified and the distinct visible-node-weighted "
                                        "composition has no target-protected layout"
                                    )
                            elif joint_relation_rejected:
                                hierarchy_plan = _hierarchy_weighted_layout(
                                    scene,
                                    hierarchy,
                                    rejected_signatures=self._failed_plan_signatures,
                                    search_budget=search_budget,
                                )
                                if hierarchy_plan is None:
                                    deferred_hierarchy_reason = (
                                        "equal-weight joint completion was falsified and the "
                                        "distinct arity-weighted endpoint-centroid hypothesis "
                                        "has no target-protected layout"
                                    )
                            else:
                                hierarchy_plan = _hierarchy_joint_layout(
                                    scene,
                                    hierarchy,
                                    rejected_signatures=self._failed_plan_signatures,
                                    search_budget=search_budget,
                                )
                        if child_isolation_plan is None and hierarchy_plan is None:
                            if deferred_hierarchy_reason is None:
                                deferred_hierarchy_reason = (
                                    "readable affine hierarchy has no bounded target-protected "
                                    "layout for its next unfalsified composition hypothesis"
                                )
                except _HierarchySearchExhausted as exc:
                    deferred_hierarchy_reason = str(exc)
                if hierarchy is not None:
                    if child_isolation_plan is not None:
                        self._install_child_isolation_plan(child_isolation_plan)
                        planned = self._plan.popleft()
                        action = ActionRequest(ActionName.ACTION6, planned.coordinate)
                        self._stage_pending(
                            observation,
                            action,
                            purpose=planned.purpose,
                            prediction=planned.expectation,
                            mechanic_refs=(planned.mechanic_ref,),
                            plan_signature=planned.plan_signature,
                            target_center=planned.target_center,
                            mediator_color=planned.mediator_color,
                            arity=planned.arity,
                            completes_child_isolation=planned.completes_child_isolation,
                            completes_child_recovery=planned.completes_child_recovery,
                            expected_child_mediator_center=(planned.expected_child_mediator_center),
                            expected_child_mediator_signature=(
                                planned.expected_child_mediator_signature
                            ),
                            expected_child_endpoint_centers=(
                                planned.expected_child_endpoint_centers
                            ),
                            expected_child_endpoint_signature=(
                                planned.expected_child_endpoint_signature
                            ),
                            expected_child_connector_signature=(
                                planned.expected_child_connector_signature
                            ),
                            expected_active_center=planned.expected_active_center,
                            expected_child_protected_raster_hash=(
                                planned.expected_child_protected_raster_hash
                            ),
                            expected_child_raster_signature=(
                                planned.expected_child_raster_signature
                            ),
                            expected_occluded_endpoint_centers=(
                                planned.expected_occluded_endpoint_centers
                            ),
                            expected_occluded_endpoint_cells=(
                                planned.expected_occluded_endpoint_cells
                            ),
                            expected_visible_endpoint_count=(
                                planned.expected_visible_endpoint_count
                            ),
                            expected_visible_mediator_count=(
                                planned.expected_visible_mediator_count
                            ),
                        )
                        return action
                    if hierarchy_plan is not None:
                        assert hierarchy_relation_key is not None
                        self._install_hierarchy_plan(
                            hierarchy_plan,
                            relation_key=hierarchy_relation_key,
                        )
                        if starting_resource_setup_replay:
                            replay = self._resource_interrupted_paired_replay
                            assert replay is not None and not replay.setup_replay_started
                            self._resource_interrupted_paired_replay = replace(
                                replay,
                                setup_replay_started=True,
                            )
                        planned = self._plan.popleft()
                        action = ActionRequest(ActionName.ACTION6, planned.coordinate)
                        self._stage_pending(
                            observation,
                            action,
                            purpose=planned.purpose,
                            prediction=planned.expectation,
                            mechanic_refs=(planned.mechanic_ref,),
                            plan_signature=planned.plan_signature,
                            target_center=planned.target_center,
                            mediator_color=planned.mediator_color,
                            arity=planned.arity,
                            completes_hierarchy=planned.completes_hierarchy,
                            expected_active_center=planned.expected_active_center,
                            expected_child_protected_raster_hash=(
                                planned.expected_child_protected_raster_hash
                            ),
                            expected_visible_endpoint_count=(
                                planned.expected_visible_endpoint_count
                            ),
                            expected_visible_mediator_count=(
                                planned.expected_visible_mediator_count
                            ),
                        )
                        return action
                elif deferred_hierarchy_reason is None and not self._last_probe_failed:
                    transferred = infer_transferred_affine_mechanic(
                        scene,
                        level_index=observation.levels_completed,
                        active_color=self._last_active_color,
                        supported_prior=tuple(self._mechanics[-16:]),
                    )
                    if transferred is not None and self._install_plan(transferred, scene):
                        self._mechanics.append(transferred)
                        planned = self._plan.popleft()
                        action = ActionRequest(ActionName.ACTION6, planned.coordinate)
                        self._stage_pending(
                            observation,
                            action,
                            purpose=planned.purpose,
                            prediction=planned.expectation,
                            mechanic_refs=(planned.mechanic_ref,),
                            plan_signature=planned.plan_signature,
                            target_center=planned.target_center,
                            mediator_color=planned.mediator_color,
                            arity=planned.arity,
                            completes_local_target=planned.completes_local_target,
                        )
                        return action
                if deferred_hierarchy_reason is not None:
                    replay = self._resource_interrupted_paired_replay
                    if replay is not None and not replay.setup_replay_started:
                        self._resource_interrupted_paired_replay = None
                        self._plan.clear()
                    self._hierarchy_search_deferred_count += 1
                    self._last_hierarchy_search_residual = deferred_hierarchy_reason
                    self._last_probe_failed = True
            reacquire_target = self._affine_reacquire_target_center
            activation = (
                self._activation_coordinate(
                    scene,
                    completed_target_center=reacquire_target,
                )
                if deferred_hierarchy_reason is None
                and deferred_hierarchy is None
                and (self._last_probe_failed or reacquire_target is not None)
                else None
            )
            if activation is not None:
                action = ActionRequest(ActionName.ACTION6, activation)
                self._remember_exploration_root(
                    scene,
                    kind="activation",
                    coordinate=activation,
                )
                self._last_probe_failed = False
                dedicated_reacquisition = reacquire_target is not None
                self._affine_reacquire_target_center = None
                self._stage_pending(
                    observation,
                    action,
                    purpose=VisualActionPurpose.PROBE,
                    prediction=(
                        "reacquire the active role within the remaining readable affine group"
                        if dedicated_reacquisition
                        else "test whether a nearby endpoint transfers the active intervention role"
                    ),
                    mechanic_refs=(),
                    affine_reacquisition=dedicated_reacquisition,
                )
                return action
            if reacquire_target is not None:
                raise PolicyError(
                    "a local affine target is complete but no unique structurally safe "
                    "remaining-group role exchange is readable"
                )
            if deferred_hierarchy is not None or deferred_hierarchy_reason is not None:
                reason = deferred_hierarchy_reason or (
                    "readable affine hierarchy has no certified layout"
                )
                raise PolicyError(
                    f"{reason}; readable affine hierarchy has no parser-safe "
                    "target-preserving continuation"
                )
            coordinate = self._probe_coordinate(scene)
            action = ActionRequest(ActionName.ACTION6, coordinate)
            self._remember_exploration_root(
                scene,
                kind="coordinate",
                coordinate=coordinate,
            )
            self._stage_pending(
                observation,
                action,
                purpose=VisualActionPurpose.PROBE,
                prediction=(
                    f"{deferred_hierarchy_reason}; test one bounded coordinate alternative"
                    if deferred_hierarchy_reason is not None
                    else "test coordinate placement and localized affine mediator response"
                ),
                mechanic_refs=(
                    (deferred_hierarchy_ref,) if deferred_hierarchy_ref is not None else ()
                ),
            )
            return action

        available = tuple(
            name
            for name in (
                ActionName.ACTION1,
                ActionName.ACTION2,
                ActionName.ACTION3,
                ActionName.ACTION4,
                ActionName.ACTION5,
                ActionName.ACTION7,
            )
            if name in observation.available_actions
        )
        if not available:
            raise PolicyError("the environment advertises no supported non-reset action")
        action = ActionRequest(available[0])
        self._stage_pending(
            observation,
            action,
            purpose=VisualActionPurpose.FALLBACK,
            prediction="all factored channels UNKNOWN; bounded legal fallback",
        )
        return action

    def _stage_pending(
        self,
        observation: Observation,
        action: ActionRequest,
        *,
        purpose: VisualActionPurpose,
        prediction: str,
        mechanic_refs: tuple[str, ...] = (),
        plan_signature: str | None = None,
        target_center: tuple[int, int] | None = None,
        mediator_color: int | None = None,
        arity: int | None = None,
        completes_local_target: bool = False,
        completes_hierarchy: bool = False,
        completes_child_isolation: bool = False,
        completes_child_recovery: bool = False,
        expected_child_mediator_center: tuple[int, int] | None = None,
        expected_child_mediator_signature: _VisualObjectStateSignature | None = None,
        expected_child_endpoint_centers: tuple[tuple[int, int], ...] = (),
        expected_child_endpoint_signature: _EndpointStateSignature = (),
        expected_child_connector_signature: _ConnectorStateSignature = None,
        expected_active_center: tuple[int, int] | None = None,
        expected_child_protected_raster_hash: str | None = None,
        expected_child_raster_signature: _RasterStateSignature = (),
        expected_occluded_endpoint_centers: tuple[tuple[int, int], ...] = (),
        expected_occluded_endpoint_cells: tuple[tuple[int, int], ...] = (),
        expected_visible_endpoint_count: int | None = None,
        expected_visible_mediator_count: int | None = None,
        carrier_source_recovery_candidate: PlannedClick | None = None,
        affine_reacquisition: bool = False,
    ) -> None:
        if self._pending_action is not None:
            raise PolicyError("a consequence is required before selecting another action")
        learner = self._ensure_learner(observation)
        context = self._mechanic_context(observation, action, purpose)
        mechanic_prediction = learner.predict(action, context, emitted_step=self._step_index)
        self._pending_before = observation
        self._pending_action = action
        self._pending_purpose = purpose
        self._pending_prediction = prediction
        self._pending_mechanic_refs = mechanic_refs
        self._pending_plan_signature = plan_signature
        self._pending_target_center = target_center
        self._pending_mediator_color = mediator_color
        self._pending_arity = arity
        self._pending_completes_local_target = completes_local_target
        self._pending_completes_hierarchy = completes_hierarchy
        self._pending_completes_child_isolation = completes_child_isolation
        self._pending_completes_child_recovery = completes_child_recovery
        self._pending_expected_child_mediator_center = expected_child_mediator_center
        self._pending_expected_child_mediator_signature = expected_child_mediator_signature
        self._pending_expected_child_endpoint_centers = expected_child_endpoint_centers
        self._pending_expected_child_endpoint_signature = expected_child_endpoint_signature
        self._pending_expected_child_connector_signature = expected_child_connector_signature
        self._pending_expected_active_center = expected_active_center
        self._pending_expected_child_protected_raster_hash = expected_child_protected_raster_hash
        self._pending_expected_child_raster_signature = expected_child_raster_signature
        self._pending_expected_occluded_endpoint_centers = expected_occluded_endpoint_centers
        self._pending_expected_occluded_endpoint_cells = expected_occluded_endpoint_cells
        self._pending_expected_visible_endpoint_count = expected_visible_endpoint_count
        self._pending_expected_visible_mediator_count = expected_visible_mediator_count
        self._pending_carrier_source_recovery_candidate = carrier_source_recovery_candidate
        self._pending_affine_reacquisition = affine_reacquisition
        self._pending_clef_prediction = _predicted_clef_effects(
            purpose=purpose,
            mechanic_refs=mechanic_refs,
            action=action,
        )
        self._pending_mechanic_prediction = mechanic_prediction

    def _clear_pending_action_state(self) -> None:
        """Restore the exact no-pending invariant after acceptance or cancellation."""

        self._pending_before = None
        self._pending_action = None
        self._pending_purpose = VisualActionPurpose.PROBE
        self._pending_prediction = "all factored channels UNKNOWN"
        self._pending_mechanic_refs = ()
        self._pending_plan_signature = None
        self._pending_target_center = None
        self._pending_mediator_color = None
        self._pending_arity = None
        self._pending_completes_local_target = False
        self._pending_completes_hierarchy = False
        self._pending_completes_child_isolation = False
        self._pending_completes_child_recovery = False
        self._pending_expected_child_mediator_center = None
        self._pending_expected_child_mediator_signature = None
        self._pending_expected_child_endpoint_centers = ()
        self._pending_expected_child_endpoint_signature = ()
        self._pending_expected_child_connector_signature = None
        self._pending_expected_active_center = None
        self._pending_expected_child_protected_raster_hash = None
        self._pending_expected_child_raster_signature = ()
        self._pending_expected_occluded_endpoint_centers = ()
        self._pending_expected_occluded_endpoint_cells = ()
        self._pending_expected_visible_endpoint_count = None
        self._pending_expected_visible_mediator_count = None
        self._pending_carrier_source_recovery_candidate = None
        self._pending_affine_reacquisition = False
        self._pending_clef_prediction = EffectVector.unknown()
        self._pending_mechanic_prediction = None

    def accept_consequence(self, observation: Observation) -> None:
        before = self._pending_before
        action = self._pending_action
        mechanic_prediction = self._pending_mechanic_prediction
        carrier_source_recovery_candidate = self._pending_carrier_source_recovery_candidate
        carrier_source_recovery_alternative = (
            carrier_source_recovery_candidate.carrier_source_recovery_alternative
            if carrier_source_recovery_candidate is not None
            else None
        )
        learner = self._mechanical_learner
        if before is None or action is None or mechanic_prediction is None or learner is None:
            raise PolicyError("mechanical policy received a consequence without a pending action")
        changed = _changed_cells(before.frames[-1], observation.frames[-1])
        level_progress = observation.levels_completed > before.levels_completed
        resource_exhaustion_candidate: _EdgeResourceProgress | None = None
        if (
            action.name is ActionName.ACTION6
            and before.state is GameStateName.NOT_FINISHED
            and not level_progress
        ):
            if not self._episode_resource_baseline_edges:
                self._episode_resource_baseline_edges = _frame_edge_signatures(before.frames[-1])
            self._episode_action6_count += 1
            self._episode_resource_candidates = _advance_edge_resource_progress(
                self._episode_resource_baseline_edges,
                self._episode_resource_candidates,
                before.frames[-1],
                observation.frames[-1],
                observed_actions=self._episode_action6_count,
            )
            if observation.state is GameStateName.GAME_OVER:
                resource_exhaustion_candidate = _exhausted_edge_resource_candidate(
                    self._episode_resource_candidates
                )
        state_change = observation.state is not before.state
        observed = (
            "official level progress"
            if level_progress
            else (
                f"official state {observation.state.value}"
                if state_change
                else ("visual consequence" if changed else "known no-change")
            )
        )
        residual: str | None = None
        post_receipt_attachment_continuation: tuple[PlannedClick, ...] = ()
        post_receipt_untouched_context: _CarrierSourceAttachmentReplayContext | None = None
        post_receipt_untouched_restoration: tuple[PlannedClick, ...] = ()
        post_receipt_paired_cargo_context: _CarrierSourceAttachmentReplayContext | None = None
        post_receipt_paired_cargo_indexes: tuple[int, ...] = ()
        post_receipt_paired_cargo_restoration: tuple[PlannedClick, ...] = ()
        post_receipt_paired_cargo_role_handoff_family = False
        post_receipt_crossed_delivery_context: _CarrierSourceCrossedDeliveryReplayContext | None = (
            None
        )
        post_receipt_post_access_composite_exit: tuple[PlannedClick, ...] = ()
        post_receipt_post_access_composite_marker: tuple[PlannedClick, ...] = ()
        post_receipt_resource_interrupted_replay: _ResourceInterruptedPairedReplay | None = None
        mechanic: AffineMechanic | None = None
        before_scene = extract_visual_scene(before.frames[-1])
        after_scene = extract_visual_scene(observation.frames[-1])
        weighted_hierarchy_action = (
            self._pending_plan_signature is not None
            and self._pending_plan_signature.startswith("affine-weighted-hierarchy:")
        )
        visible_node_hierarchy_action = (
            self._pending_plan_signature is not None
            and self._pending_plan_signature.startswith("affine-visible-node-hierarchy:")
        )
        bridge_hierarchy_action = (
            self._pending_plan_signature is not None
            and self._pending_plan_signature.startswith("affine-bridge-hierarchy:")
        )
        residual_linked_hierarchy_action = (
            self._pending_plan_signature is not None
            and self._pending_plan_signature.startswith("affine-residual-linked-hierarchy:")
        )
        external_residual_linked_hierarchy_action = (
            self._pending_plan_signature is not None
            and self._pending_plan_signature.startswith(
                "affine-external-residual-linked-hierarchy:"
            )
        )
        raw_matching_composite_hierarchy_action = (
            self._pending_plan_signature is not None
            and self._pending_plan_signature.startswith("affine-raw-matching-composite-hierarchy:")
        )
        external_own_composite_hierarchy_action = (
            self._pending_plan_signature is not None
            and self._pending_plan_signature.startswith("affine-external-own-composite-hierarchy:")
        )
        carrier_source_occlusion_hierarchy_action = (
            self._pending_plan_signature is not None
            and self._pending_plan_signature.startswith(
                "affine-carrier-source-occlusion-hierarchy:"
            )
        )
        same_child_composite_cargo_action = bool(
            self._pending_plan_signature is not None
            and self._pending_plan_signature.startswith("affine-same-child-composite-cargo:")
            and carrier_source_recovery_candidate is not None
            and carrier_source_recovery_candidate.same_child_composite_cargo_certificate is not None
            and _same_child_composite_cargo_step_is_compatible(carrier_source_recovery_candidate)
        )
        joint_hierarchy_action = (
            self._pending_plan_signature is not None
            and self._pending_plan_signature.startswith(
                (
                    "affine-hierarchy:",
                    "affine-weighted-hierarchy:",
                    "affine-visible-node-hierarchy:",
                    "affine-bridge-hierarchy:",
                    "affine-residual-linked-hierarchy:",
                    "affine-external-residual-linked-hierarchy:",
                    "affine-raw-matching-composite-hierarchy:",
                    "affine-external-own-composite-hierarchy:",
                    "affine-carrier-source-occlusion-hierarchy:",
                    "affine-same-child-composite-cargo:",
                )
            )
        )
        residual_linked_hierarchy_recovery_action = (
            self._pending_plan_signature is not None
            and self._pending_plan_signature.startswith(
                "affine-residual-linked-hierarchy-recovery:"
            )
        )
        external_residual_linked_hierarchy_recovery_action = (
            self._pending_plan_signature is not None
            and self._pending_plan_signature.startswith(
                "affine-external-residual-linked-hierarchy-recovery:"
            )
        )
        raw_matching_composite_hierarchy_recovery_action = (
            self._pending_plan_signature is not None
            and self._pending_plan_signature.startswith(
                "affine-raw-matching-composite-hierarchy-recovery:"
            )
        )
        external_own_composite_hierarchy_recovery_action = (
            self._pending_plan_signature is not None
            and self._pending_plan_signature.startswith(
                "affine-external-own-composite-hierarchy-recovery:"
            )
        )
        carrier_source_occlusion_hierarchy_recovery_action = (
            self._pending_plan_signature is not None
            and self._pending_plan_signature.startswith(
                "affine-carrier-source-occlusion-hierarchy-recovery:"
            )
        )
        carrier_source_delivery_action = bool(
            carrier_source_occlusion_hierarchy_recovery_action
            and carrier_source_recovery_candidate is not None
            and carrier_source_recovery_candidate.carrier_source_delivery_step
        )
        carrier_source_detachment_action = bool(
            carrier_source_occlusion_hierarchy_recovery_action
            and carrier_source_recovery_candidate is not None
            and carrier_source_recovery_candidate.carrier_source_detachment_step
        )
        carrier_source_untouched_discriminator_action = bool(
            carrier_source_occlusion_hierarchy_recovery_action
            and carrier_source_recovery_candidate is not None
            and carrier_source_recovery_candidate.carrier_source_untouched_discriminator_step
        )
        carrier_source_untouched_restoration_action = bool(
            carrier_source_occlusion_hierarchy_recovery_action
            and carrier_source_recovery_candidate is not None
            and carrier_source_recovery_candidate.carrier_source_untouched_restoration_step
        )
        carrier_source_paired_cargo_action = bool(
            carrier_source_occlusion_hierarchy_recovery_action
            and carrier_source_recovery_candidate is not None
            and carrier_source_recovery_candidate.carrier_source_paired_cargo_step
        )
        carrier_source_paired_cargo_restoration_action = bool(
            carrier_source_occlusion_hierarchy_recovery_action
            and carrier_source_recovery_candidate is not None
            and carrier_source_recovery_candidate.carrier_source_paired_cargo_restoration_step
        )
        carrier_source_paired_cargo_role_handoff_action = bool(
            carrier_source_occlusion_hierarchy_recovery_action
            and carrier_source_recovery_candidate is not None
            and carrier_source_recovery_candidate.carrier_source_paired_cargo_role_handoff_step
        )
        carrier_source_paired_cargo_role_restoration_action = bool(
            carrier_source_occlusion_hierarchy_recovery_action
            and carrier_source_recovery_candidate is not None
            and carrier_source_recovery_candidate.carrier_source_paired_cargo_role_restoration_step
        )
        carrier_source_paired_cargo_crossed_predecessor_action = bool(
            carrier_source_occlusion_hierarchy_recovery_action
            and carrier_source_recovery_candidate is not None
            and carrier_source_recovery_candidate.carrier_source_paired_cargo_crossed_predecessor_step
        )
        carrier_source_paired_cargo_crossed_delivery_action = bool(
            carrier_source_occlusion_hierarchy_recovery_action
            and carrier_source_recovery_candidate is not None
            and carrier_source_recovery_candidate.carrier_source_paired_cargo_crossed_delivery_step
        )
        post_deposit_mediator_access_action = bool(
            carrier_source_recovery_candidate is not None
            and carrier_source_recovery_candidate.post_deposit_mediator_access_certificate
            is not None
        )
        post_access_composite_exit_action = bool(
            carrier_source_recovery_candidate is not None
            and carrier_source_recovery_candidate.post_access_composite_exit_certificate is not None
        )
        post_access_composite_marker_action = bool(
            carrier_source_recovery_candidate is not None
            and carrier_source_recovery_candidate.post_access_composite_marker_certificate
            is not None
        )
        post_marker_resource_reset_bridge_action = bool(
            self._post_marker_resource_reset_bridge is not None
            and self._pending_plan_signature is not None
            and self._pending_plan_signature.startswith("post-marker-resource-reset-bridge:")
        )
        carrier_source_untouched_action = bool(
            carrier_source_untouched_discriminator_action
            or carrier_source_untouched_restoration_action
            or (
                carrier_source_occlusion_hierarchy_recovery_action
                and carrier_source_recovery_candidate is not None
                and carrier_source_recovery_candidate.carrier_source_untouched_role_exchange_step
            )
        )
        paired_resource_exhaustion_candidate = bool(
            resource_exhaustion_candidate is not None
            and carrier_source_recovery_candidate is not None
            and (
                carrier_source_paired_cargo_action
                or carrier_source_paired_cargo_restoration_action
                or carrier_source_paired_cargo_role_handoff_action
                or carrier_source_paired_cargo_role_restoration_action
                or carrier_source_paired_cargo_crossed_predecessor_action
                or carrier_source_paired_cargo_crossed_delivery_action
            )
        )
        active_post_marker_bridge = self._post_marker_resource_reset_bridge
        post_marker_resource_exhaustion = bool(
            post_marker_resource_reset_bridge_action
            and active_post_marker_bridge is not None
            and resource_exhaustion_candidate is not None
            and self._episode_action6_count == active_post_marker_bridge.exhausted_after_actions
            and resource_exhaustion_candidate.edge_index == active_post_marker_bridge.edge_index
            and resource_exhaustion_candidate.baseline == active_post_marker_bridge.edge_baseline
            and resource_exhaustion_candidate.fill_color
            == active_post_marker_bridge.edge_fill_color
            and resource_exhaustion_candidate.filled_index_history
            == active_post_marker_bridge.exhausted_filled_index_history
            and self._post_marker_resource_bridge_matches(observation)
        )
        hierarchy_recovery_action = (
            self._pending_plan_signature is not None
            and self._pending_plan_signature.startswith(
                (
                    "affine-hierarchy-recovery:",
                    "affine-weighted-hierarchy-recovery:",
                    "affine-visible-node-hierarchy-recovery:",
                    "affine-bridge-hierarchy-recovery:",
                    "affine-residual-linked-hierarchy-recovery:",
                    "affine-external-residual-linked-hierarchy-recovery:",
                    "affine-raw-matching-composite-hierarchy-recovery:",
                    "affine-external-own-composite-hierarchy-recovery:",
                    "affine-carrier-source-occlusion-hierarchy-recovery:",
                )
            )
        )
        child_recovery_action = (
            self._pending_plan_signature is not None
            and self._pending_plan_signature.startswith("affine-child-recovery:")
        )
        child_isolation_action = (
            self._pending_plan_signature is not None
            and self._pending_plan_signature.startswith(
                ("affine-child-isolation:", "affine-child-recovery:")
            )
        )
        hierarchy_action = (
            joint_hierarchy_action or hierarchy_recovery_action or child_isolation_action
        )
        hierarchy_relation_key = (
            self._active_hierarchy_relation_key
            if joint_hierarchy_action or hierarchy_recovery_action
            else None
        )
        child_isolation_relation_key = (
            self._active_child_isolation_relation_key if child_isolation_action else None
        )
        child_isolation_hypothesis_key = (
            self._active_child_isolation_hypothesis_key if child_isolation_action else None
        )
        hierarchy_target_readable = bool(
            self._pending_target_center is not None
            and any(
                target.rounded_center == self._pending_target_center
                for target in after_scene.targets
            )
        )
        endpoint_role_switch = _endpoint_role_switch_observed(
            before_scene,
            after_scene,
            action=action,
            active_color=self._last_active_color,
        )
        after_hierarchy: _AffineHierarchy | None = None
        hierarchy_recognition_residual: str | None = None
        if hierarchy_action and self._last_active_color is not None:
            try:
                after_hierarchy = _unique_affine_hierarchy(
                    after_scene,
                    active_color=self._last_active_color,
                )
            except _HierarchySearchExhausted as exc:
                hierarchy_recognition_residual = (
                    f"returned hierarchy recognition failed closed: {exc}"
                )
        before_parent_targets = tuple(
            target
            for target in before_scene.targets
            if target.rounded_center == self._pending_target_center
        )
        after_parent_targets = tuple(
            target
            for target in after_scene.targets
            if target.rounded_center == self._pending_target_center
        )
        hierarchy_parent_target_preserved = (
            len(before_parent_targets) == len(after_parent_targets) == 1
            and before_parent_targets[0].object_ref == after_parent_targets[0].object_ref
        )
        carrier_source_target_promoted_to_mediator = bool(
            carrier_source_delivery_action
            and len(before_parent_targets) == 1
            and not after_parent_targets
            and self._pending_target_center is not None
            and sum(
                mediator.rounded_center == self._pending_target_center
                for mediator in after_scene.mediators
            )
            == 1
        )
        expected_child_protected_raster_hash = self._pending_expected_child_protected_raster_hash
        expected_child_protected_raster_hash_value = expected_child_protected_raster_hash or ""
        child_isolation_raster_certified = bool(
            child_isolation_action
            and expected_child_protected_raster_hash is not None
            and self._pending_expected_child_raster_signature
            and _child_isolation_protected_raster_hash(after_scene)
            == expected_child_protected_raster_hash
            and all(
                after_scene.cells[y][x] == value
                for x, y, value in self._pending_expected_child_raster_signature
            )
        )
        child_isolation_visible_counts_certified = bool(
            child_isolation_action
            and child_isolation_raster_certified
            and self._pending_expected_visible_endpoint_count is not None
            and self._pending_expected_visible_mediator_count is not None
            and len(after_scene.endpoints) == self._pending_expected_visible_endpoint_count
            and len(after_scene.mediators) == self._pending_expected_visible_mediator_count
        )
        carrier_source_recovery_candidate_is_current = bool(
            not carrier_source_occlusion_hierarchy_recovery_action
            or (
                carrier_source_recovery_candidate is not None
                and carrier_source_recovery_candidate.plan_signature == self._pending_plan_signature
                and carrier_source_recovery_candidate.coordinate == action.coordinate
                and carrier_source_recovery_candidate.required_carried_source_support_indexes
                == self._active_carried_source_recovery_support_indexes
                and carrier_source_recovery_candidate.expected_child_protected_raster_hash
                == expected_child_protected_raster_hash
                and carrier_source_recovery_candidate.expected_visible_endpoint_count
                == self._pending_expected_visible_endpoint_count
                and carrier_source_recovery_candidate.expected_visible_mediator_count
                == self._pending_expected_visible_mediator_count
            )
        )
        hierarchy_raster_common_boundary = bool(
            (joint_hierarchy_action or hierarchy_recovery_action)
            and carrier_source_recovery_candidate_is_current
            and observation.levels_completed == before.levels_completed
            and changed > 0
            and (
                carrier_source_delivery_action
                or carrier_source_detachment_action
                or carrier_source_paired_cargo_action
                or carrier_source_paired_cargo_restoration_action
                or carrier_source_paired_cargo_role_handoff_action
                or carrier_source_paired_cargo_role_restoration_action
                or carrier_source_paired_cargo_crossed_predecessor_action
                or carrier_source_paired_cargo_crossed_delivery_action
                or same_child_composite_cargo_action
                or (hierarchy_target_readable and hierarchy_parent_target_preserved)
            )
        )
        returned_protected_raster_hash = _child_isolation_protected_raster_hash(after_scene)
        before_protected_raster_hash = _child_isolation_protected_raster_hash(before_scene)
        hierarchy_primary_raster_matches = bool(
            hierarchy_raster_common_boundary
            and expected_child_protected_raster_hash is not None
            and returned_protected_raster_hash == expected_child_protected_raster_hash
            and self._pending_expected_visible_endpoint_count is not None
            and self._pending_expected_visible_mediator_count is not None
            and len(after_scene.endpoints) == self._pending_expected_visible_endpoint_count
            and len(after_scene.mediators) == self._pending_expected_visible_mediator_count
        )
        paired_resource_exhausted_before_effect = bool(
            paired_resource_exhaustion_candidate
            and resource_exhaustion_candidate is not None
            and resource_exhaustion_candidate.observed_actions == self._episode_action6_count
            and len(resource_exhaustion_candidate.filled_index_history)
            == resource_exhaustion_candidate.observed_actions
            and carrier_source_recovery_candidate_is_current
            and carrier_source_recovery_candidate is not None
            and carrier_source_recovery_candidate.required_child_protected_raster_hash
            == before_protected_raster_hash
            and returned_protected_raster_hash == before_protected_raster_hash
            and len(after_scene.endpoints) == len(before_scene.endpoints)
            and len(after_scene.mediators) == len(before_scene.mediators)
            and observation.levels_completed == before.levels_completed
            and observation.state is GameStateName.GAME_OVER
        )
        paired_resource_exhaustion = bool(
            paired_resource_exhaustion_candidate
            and (hierarchy_primary_raster_matches or paired_resource_exhausted_before_effect)
            and observation.state is GameStateName.GAME_OVER
        )
        resource_interrupted_role_replay = bool(
            paired_resource_exhaustion
            and carrier_source_recovery_candidate is not None
            and carrier_source_recovery_candidate.carrier_source_paired_cargo_role_handoff_family
            and not carrier_source_recovery_candidate.carrier_source_paired_cargo_crossed_predecessor_family
            and self._pending_plan_signature is not None
            and self._paired_role_handoff_observed_signature == self._pending_plan_signature
            and self._paired_role_handoff_observed_context_key is not None
            and self._paired_role_handoff_observed_setup_relation_key is not None
            and self._paired_role_handoff_observed_setup_plan_signature is not None
            and self._paired_role_handoff_observed_setup_action_count is not None
            and self._paired_role_handoff_observed_crossed_forward_action_count is not None
            and self._paired_role_handoff_observed_setup_action_count
            + self._paired_role_handoff_observed_crossed_forward_action_count
            < self._episode_action6_count
        )
        carried_source_recovery_alternative_matches = bool(
            hierarchy_raster_common_boundary
            and carrier_source_occlusion_hierarchy_recovery_action
            and carrier_source_recovery_candidate is not None
            and carrier_source_recovery_alternative is not None
            and _carrier_source_recovery_consequence_alternative_is_compatible(
                carrier_source_recovery_candidate,
                carrier_source_recovery_alternative,
            )
            and carrier_source_recovery_alternative.coordinate == action.coordinate
            and carrier_source_recovery_alternative.plan_signature == self._pending_plan_signature
            and carrier_source_recovery_alternative.expected_child_protected_raster_hash is not None
            and returned_protected_raster_hash
            == carrier_source_recovery_alternative.expected_child_protected_raster_hash
            and carrier_source_recovery_alternative.expected_visible_endpoint_count is not None
            and carrier_source_recovery_alternative.expected_visible_mediator_count is not None
            and len(after_scene.endpoints)
            == carrier_source_recovery_alternative.expected_visible_endpoint_count
            and len(after_scene.mediators)
            == carrier_source_recovery_alternative.expected_visible_mediator_count
        )
        carried_source_recovery_certified = bool(
            carried_source_recovery_alternative_matches and not hierarchy_primary_raster_matches
        )
        deposited_source_detachment_matches = bool(
            hierarchy_raster_common_boundary
            and carrier_source_detachment_action
            and carrier_source_recovery_candidate is not None
            and _carrier_source_detachment_step_is_compatible(carrier_source_recovery_candidate)
            and carrier_source_recovery_candidate.expected_deposited_source_protected_raster_hash
            is not None
            and returned_protected_raster_hash
            == carrier_source_recovery_candidate.expected_deposited_source_protected_raster_hash
            and carrier_source_recovery_candidate.expected_deposited_visible_endpoint_count
            is not None
            and carrier_source_recovery_candidate.expected_deposited_visible_mediator_count
            is not None
            and len(after_scene.endpoints)
            == carrier_source_recovery_candidate.expected_deposited_visible_endpoint_count
            and len(after_scene.mediators)
            == carrier_source_recovery_candidate.expected_deposited_visible_mediator_count
        )
        hierarchy_expected_raster_matches = bool(
            sum(
                (
                    hierarchy_primary_raster_matches,
                    carried_source_recovery_alternative_matches,
                    deposited_source_detachment_matches,
                )
            )
            == 1
        )
        hierarchy_raster_certified = bool(
            hierarchy_expected_raster_matches and observation.state is GameStateName.NOT_FINISHED
        )
        if hierarchy_raster_certified and carrier_source_occlusion_hierarchy_recovery_action:
            matched_carrier_source_recovery = (
                carrier_source_recovery_alternative
                if carried_source_recovery_certified
                else carrier_source_recovery_candidate
            )
            assert matched_carrier_source_recovery is not None
            self._active_carried_source_recovery_support_indexes = (
                matched_carrier_source_recovery.expected_carried_source_support_indexes
            )
            if (
                carried_source_recovery_certified
                and carrier_source_recovery_alternative is not None
                and carrier_source_recovery_alternative.carrier_source_delivery_actions
                and _carrier_source_delivery_actions_are_compatible(
                    carrier_source_recovery_alternative
                )
            ):
                self._plan.clear()
                self._plan.extend(
                    carrier_source_recovery_alternative.carrier_source_delivery_actions
                )
        hierarchy_terminal_game_over_observed = bool(
            joint_hierarchy_action
            and self._pending_completes_hierarchy
            and hierarchy_expected_raster_matches
            and observation.state is GameStateName.GAME_OVER
        )
        hierarchy_preterminal_game_over_observed = bool(
            (
                bridge_hierarchy_action
                or residual_linked_hierarchy_action
                or external_residual_linked_hierarchy_action
                or raw_matching_composite_hierarchy_action
                or external_own_composite_hierarchy_action
                or carrier_source_occlusion_hierarchy_action
                or same_child_composite_cargo_action
            )
            and not self._pending_completes_hierarchy
            and not carrier_source_paired_cargo_action
            and not carrier_source_paired_cargo_restoration_action
            and not carrier_source_paired_cargo_role_handoff_action
            and not carrier_source_paired_cargo_role_restoration_action
            and not carrier_source_paired_cargo_crossed_predecessor_action
            and not carrier_source_paired_cargo_crossed_delivery_action
            and observation.state is GameStateName.GAME_OVER
        )
        hierarchy_visible_counts_certified = bool(
            child_isolation_visible_counts_certified
            if child_isolation_action
            else (
                len(before_scene.endpoints) == len(after_scene.endpoints)
                and len(before_scene.mediators) == len(after_scene.mediators)
            )
        )
        child_isolation_occlusion_certified = bool(
            child_isolation_action
            and child_isolation_raster_certified
            and not self._pending_completes_child_isolation
            and observation.state is GameStateName.NOT_FINISHED
            and observation.levels_completed == before.levels_completed
            and changed > 0
            and self._last_active_color is not None
            and self._pending_target_center is not None
            and self._active_child_isolation_target_signature is not None
            and self._pending_expected_child_mediator_signature is not None
            and self._pending_expected_child_endpoint_signature
            and self._pending_expected_child_raster_signature
            and self._pending_expected_occluded_endpoint_centers
            and self._pending_expected_occluded_endpoint_cells
            and self._pending_expected_active_center is not None
            and self._active_child_isolation_frozen_mediator_signature is not None
            and self._active_child_isolation_frozen_endpoint_signature
            and _child_isolation_occlusion_certificate_matches(
                after_scene,
                expected_protected_raster_hash=(expected_child_protected_raster_hash_value),
                active_color=self._last_active_color,
                sink_center=self._pending_target_center,
                target_signature=self._active_child_isolation_target_signature,
                selected_mediator_signature=(self._pending_expected_child_mediator_signature),
                selected_endpoint_signature=self._pending_expected_child_endpoint_signature,
                selected_raster_signature=self._pending_expected_child_raster_signature,
                occluded_endpoint_centers=(self._pending_expected_occluded_endpoint_centers),
                occluded_endpoint_cells=self._pending_expected_occluded_endpoint_cells,
                expected_active_center=self._pending_expected_active_center,
                frozen_mediator_signature=(self._active_child_isolation_frozen_mediator_signature),
                frozen_endpoint_signature=(self._active_child_isolation_frozen_endpoint_signature),
                frozen_connector_signature=(
                    self._active_child_isolation_frozen_connector_signature
                ),
            )
        )
        child_isolation_constraints_preserved = bool(
            not child_isolation_action
            or (
                after_hierarchy is not None
                and child_isolation_raster_certified
                and self._pending_target_center is not None
                and self._active_child_isolation_frozen_mediator_center is not None
                and self._active_child_isolation_frozen_mediator_signature is not None
                and self._active_child_isolation_frozen_endpoint_centers
                and self._active_child_isolation_frozen_endpoint_signature
                and self._active_child_isolation_frozen_mediator_color is not None
                and self._active_child_isolation_target_signature is not None
                and self._pending_expected_child_mediator_center is not None
                and self._pending_expected_child_mediator_signature is not None
                and self._pending_expected_child_endpoint_centers
                and self._pending_expected_child_endpoint_signature
                and self._pending_expected_active_center is not None
                and self._pending_mediator_color is not None
                and _child_isolation_target_surface_signature(
                    after_scene,
                    sink_center=self._pending_target_center,
                )
                == self._active_child_isolation_target_signature
                and any(
                    _child_group_matches_state(
                        child,
                        mediator_signature=(self._active_child_isolation_frozen_mediator_signature),
                        endpoint_signature=(self._active_child_isolation_frozen_endpoint_signature),
                    )
                    and _hierarchy_connector_state_signature(after_scene, child)
                    == self._active_child_isolation_frozen_connector_signature
                    for child in after_hierarchy.children
                )
                and any(
                    _child_group_matches_state(
                        child,
                        mediator_signature=self._pending_expected_child_mediator_signature,
                        endpoint_signature=self._pending_expected_child_endpoint_signature,
                    )
                    and _hierarchy_connector_state_signature(after_scene, child)
                    == self._pending_expected_child_connector_signature
                    and any(
                        endpoint.color == after_hierarchy.active_color
                        and endpoint.rounded_center == self._pending_expected_active_center
                        for endpoint in child.endpoints
                    )
                    for child in after_hierarchy.children
                )
            )
            or child_isolation_occlusion_certified
        )
        child_recovery_restoration_certified = bool(
            child_recovery_action
            and self._pending_completes_child_recovery
            and observation.state is GameStateName.NOT_FINISHED
            and observation.levels_completed == before.levels_completed
            and changed > 0
            and hierarchy_target_readable
            and hierarchy_parent_target_preserved
            and child_isolation_raster_certified
            and child_isolation_visible_counts_certified
            and after_hierarchy is not None
            and len(after_hierarchy.children) == 2
            and self._pending_target_center is not None
            and self._active_child_isolation_target_signature is not None
            and _child_isolation_target_surface_signature(
                after_scene,
                sink_center=self._pending_target_center,
            )
            == self._active_child_isolation_target_signature
            and self._last_active_color is not None
            and self._pending_expected_active_center is not None
            and any(
                endpoint.color == self._last_active_color
                and endpoint.rounded_center == self._pending_expected_active_center
                for endpoint in after_scene.endpoints
            )
            and (
                endpoint_role_switch
                if self._pending_purpose is VisualActionPurpose.PROBE
                else self._pending_purpose is VisualActionPurpose.PROGRESS
                and action.coordinate is not None
                and self._pending_expected_active_center
                == (action.coordinate.x, action.coordinate.y)
            )
        )
        hierarchy_structure_readable = bool(
            hierarchy_action
            and changed > 0
            and hierarchy_target_readable
            and hierarchy_parent_target_preserved
            and child_isolation_constraints_preserved
            and after_hierarchy is not None
            and hierarchy_visible_counts_certified
            and (
                endpoint_role_switch
                if self._pending_purpose is VisualActionPurpose.PROBE
                else action.coordinate is not None
                and any(
                    endpoint.color == self._last_active_color
                    and endpoint.rounded_center == (action.coordinate.x, action.coordinate.y)
                    for endpoint in after_scene.endpoints
                )
            )
        )
        hierarchy_consequence_certified = bool(
            hierarchy_raster_certified
            if joint_hierarchy_action or hierarchy_recovery_action
            else (
                hierarchy_structure_readable
                or child_isolation_occlusion_certified
                or child_recovery_restoration_certified
            )
        )
        # An exact protected-raster match can preserve plan lineage without
        # making the transformed hierarchy structurally readable.  The
        # carrier-source foreground candidate deliberately uses that narrower
        # boundary: its masked transient earns continuation under the exact
        # certificate, but it does not manufacture a generic observed
        # coordinate-transform fact from components the parser cannot read.
        hierarchy_observed_effect_readable = bool(
            hierarchy_consequence_certified
            and not (
                (
                    carrier_source_occlusion_hierarchy_action
                    or carrier_source_occlusion_hierarchy_recovery_action
                    or same_child_composite_cargo_action
                )
                and hierarchy_raster_certified
                and not hierarchy_structure_readable
            )
        )
        hierarchy_supports_observed = bool(
            joint_hierarchy_action
            and self._pending_completes_hierarchy
            and hierarchy_raster_certified
        )
        child_isolation_observed = bool(
            child_isolation_action
            and hierarchy_structure_readable
            and after_hierarchy is not None
            and _child_isolation_was_observed(
                after_hierarchy,
                target_center=self._pending_target_center,
                mediator_color=self._pending_mediator_color,
                arity=self._pending_arity,
            )
        )
        if hierarchy_recognition_residual is not None:
            residual = hierarchy_recognition_residual
        marker_bootstrap = (
            self._pending_plan_signature is not None
            and self._pending_plan_signature.startswith("marker-bootstrap:")
        )
        bootstrap_active_color = (
            _marker_bootstrap_active_color(after_scene, coordinate=action.coordinate)
            if marker_bootstrap
            and action.name is ActionName.ACTION6
            and action.coordinate is not None
            and observation.state is GameStateName.NOT_FINISHED
            else None
        )
        marker_bootstrap_succeeded = bootstrap_active_color is not None
        # ARC's official post-GAME_OVER life recovery returns full_reset=False,
        # and MyAgent deliberately strips the upstream returned_action before
        # policy dispatch.  The exact staged RESET plus official state recovery
        # at the unchanged level is therefore the authoritative local receipt.
        reset_recovered = (
            action.name is ActionName.RESET
            and before.state in {GameStateName.GAME_OVER, GameStateName.NOT_PLAYED}
            and observation.state is GameStateName.NOT_FINISHED
            and observation.levels_completed == before.levels_completed
        )
        if (
            action.name is ActionName.ACTION6
            and action.coordinate is not None
            and observation.levels_completed == before.levels_completed
            and observation.state is GameStateName.NOT_FINISHED
        ):
            mechanic = infer_affine_mechanic(
                before_scene,
                after_scene,
                level_index=before.levels_completed,
                action=action,
            )
            if mechanic is not None:
                self._mechanics.append(mechanic)
                self._last_active_color = mechanic.active_color
                self._last_probe_failed = False
            elif marker_bootstrap_succeeded:
                self._last_active_color = bootstrap_active_color
                self._last_probe_failed = False
            elif endpoint_role_switch:
                self._last_probe_failed = False
            elif self._pending_affine_reacquisition:
                self._last_probe_failed = True
                residual = "remaining-group role reacquisition was not structurally readable"
            elif (
                self._pending_purpose is VisualActionPurpose.PROBE
                and not self._pending_mechanic_refs
                and not level_progress
                and observation.state is GameStateName.NOT_FINISHED
            ):
                self._last_probe_failed = True
                residual = "probe did not localize a supported affine response"

        receipt_seed = (
            f"{len(self._receipts)}|{before.frames[-1].digest}|{action!r}|"
            f"{observation.frames[-1].digest}|{observation.state.value}"
        )
        receipt_id = (
            "visual-receipt:" + hashlib.sha256(receipt_seed.encode("utf-8")).hexdigest()[:24]
        )
        projected_target_satisfied = (
            self._pending_completes_local_target
            and observation.state is not GameStateName.GAME_OVER
            and changed > 0
            and _projected_marker_target_satisfied(
                before_scene,
                target_center=self._pending_target_center,
                mediator_color=self._pending_mediator_color,
                arity=self._pending_arity,
                active_color=self._last_active_color,
                coordinate=action.coordinate,
            )
        )
        local_target_satisfied = (
            self._pending_completes_local_target
            and observation.state is not GameStateName.GAME_OVER
            and changed > 0
            and (
                projected_target_satisfied
                or _local_target_satisfied(
                    after_scene,
                    target_center=self._pending_target_center,
                    mediator_color=self._pending_mediator_color,
                    arity=self._pending_arity,
                )
            )
        )
        marker_action_planned = (
            self._pending_plan_signature is not None
            and self._pending_plan_signature.startswith("marker:")
            and self._pending_mediator_color is not None
            and self._pending_arity is not None
            and action.name is ActionName.ACTION6
            and action.coordinate is not None
            and not level_progress
            and observation.state is GameStateName.NOT_FINISHED
            and not local_target_satisfied
        )
        marker_action_structure_readable = False
        marker_target_separated = False
        if marker_action_planned:
            assert self._pending_plan_signature is not None
            assert self._pending_mediator_color is not None
            assert self._pending_arity is not None
            assert action.coordinate is not None
            marker_target_separated = _marker_target_separation_observed(
                before_scene,
                after_scene,
                marker_color=self._pending_mediator_color,
                arity=self._pending_arity,
                coordinate=action.coordinate,
            )
            marker_action_structure_readable = bool(
                changed > 0
                and _marker_action_structure_is_readable(
                    before_scene,
                    after_scene,
                    marker_color=self._pending_mediator_color,
                    arity=self._pending_arity,
                    coordinate=action.coordinate,
                    active_color=self._last_active_color,
                    plan_signature=self._pending_plan_signature,
                    target_separation_observed=marker_target_separated,
                )
            )
        if marker_action_structure_readable and marker_target_separated:
            assert self._pending_mediator_color is not None
            self._marker_target_identity_constraints.add(self._pending_mediator_color)
        marker_action_structure_failed = (
            marker_action_planned and not marker_action_structure_readable
        )
        if marker_action_structure_failed:
            residual = (
                "planned marker target separation was not observed"
                if self._pending_plan_signature is not None
                and ":separate:" in self._pending_plan_signature
                and not marker_target_separated
                else "planned marker endpoint became structurally unreadable"
            )
        if (
            hierarchy_action
            and not level_progress
            and observation.state is GameStateName.NOT_FINISHED
            and not hierarchy_observed_effect_readable
            and residual is None
        ):
            residual = (
                "planned child-recovery inverse certificate was not structurally readable"
                if child_recovery_action
                else (
                    "planned child-isolation consequence was not structurally readable"
                    if child_isolation_action
                    else "planned hierarchy consequence was not structurally readable"
                )
            )
        coordinate_transform = (
            local_target_satisfied
            or hierarchy_observed_effect_readable
            or marker_action_structure_readable
            or marker_bootstrap_succeeded
            or _coordinate_transform_observed(
                before_scene,
                after_scene,
                action=action,
                changed_cells=changed,
                level_progress=level_progress,
                inferred_mechanic=mechanic,
                active_color=self._last_active_color,
            )
        )
        recognized_effects: list[FactoredEffect] = []
        if coordinate_transform:
            recognized_effects.append(
                FactoredEffect(
                    EffectChannel.OTHER_OBJECT_CHANGE,
                    EffectKnowledge.KNOWN,
                    _COORDINATE_TRANSFORM,
                    (receipt_id,),
                )
            )
        if (
            mechanic is not None
            or local_target_satisfied
            or child_isolation_occlusion_certified
            or marker_action_structure_readable
            or marker_bootstrap_succeeded
        ):
            recognized_effects.append(
                FactoredEffect(
                    EffectChannel.CONTROLLABLE_OBJECT_DISPLACEMENT,
                    EffectKnowledge.KNOWN,
                    _COORDINATE_PLACEMENT,
                    (receipt_id,),
                )
            )
        delta = measure_delta(
            before.frames[-1],
            observation.frames[-1],
            before_metadata=observation_metadata(before),
            after_metadata=observation_metadata(observation),
            background_colors=frozenset({before_scene.background}),
        )
        observed_effects = extract_observed_effects(
            before,
            observation,
            delta,
            recognized_effects=tuple(recognized_effects),
            evidence_refs=(receipt_id,),
        )
        effect_comparison = compare_effect_vectors(
            self._pending_clef_prediction,
            observed_effects,
            dispositions={
                EffectChannel.CONTROLLABLE_OBJECT_DISPLACEMENT: ResidualDisposition.PROMOTE,
                EffectChannel.OTHER_OBJECT_CHANGE: ResidualDisposition.PROMOTE,
                EffectChannel.RESOURCE_HUD_CHANGE: ResidualDisposition.PROMOTE,
                EffectChannel.INVENTORY_COUNT_CHANGE: ResidualDisposition.PROMOTE,
                EffectChannel.LEGAL_ACTION_CHANGE: ResidualDisposition.PROMOTE,
                EffectChannel.TOPOLOGY_REACHABILITY_CHANGE: ResidualDisposition.PROMOTE,
                EffectChannel.SCORE_PROGRESS_CHANGE: ResidualDisposition.PROMOTE,
                EffectChannel.TERMINAL_RESET_TRANSITION: ResidualDisposition.PROMOTE,
                EffectChannel.STATUS_ANIMATION_CHANGE: ResidualDisposition.STOP,
                EffectChannel.DELAYED_UNRESOLVED: ResidualDisposition.PARK,
            },
        )
        observed_consequence = _observed_bla_consequence(
            before,
            observation,
            action=action,
            coordinate_transform=coordinate_transform,
            changed_cells=changed,
        )
        learning = learner.observe_consequence(
            mechanic_prediction.prediction_id,
            observed_consequence,
            source_event_ids=(receipt_id,),
            context_key=mechanic_prediction.context.context_key,
            observed_step=self._step_index + 1,
        )
        if mechanic is not None and self._affine_ledger_ref is None:
            opened = learner.ledger.open(
                action=ActionName.ACTION6,
                scope=MechanicScope(ScopeCeiling.GAME, game_scope=learner.game_scope),
                consequence=_affine_base_consequence(),
                composition_mode=CompositionMode.BASE,
                created_step=self._step_index + 1,
                created_from_event_ids=(receipt_id,),
                provenance=EvidenceProvenance.OBSERVED_THIS_GAME,
                priority=40,
                note="coordinate action produced an observed endpoint and mediator change",
            )
            self._affine_ledger_ref = opened.ref
            learner.resolve_residual(learning.residual.residual_id)
        elif (
            self._affine_ledger_ref is not None
            and before.levels_completed > 0
            and coordinate_transform
            and before.levels_completed not in self._transfer_confirmed_levels
        ):
            transfer_seed = f"{self._affine_ledger_ref!r}|{before.levels_completed}|{receipt_id}"
            learner.confirm_transfer(
                self._affine_ledger_ref,
                channels=(ConsequenceChannel.OTHER_OBJECT_EFFECTS,),
                source_event_ids=(receipt_id,),
                context_key=mechanic_prediction.context.context_key,
                observed_step=self._step_index + 1,
                receipt_id="mechanic-transfer:"
                + hashlib.sha256(transfer_seed.encode("utf-8")).hexdigest()[:24],
            )
            self._transfer_confirmed_levels.add(before.levels_completed)
        if learning.residual.consequential and residual is None:
            residual = learning.residual.residual_id

        active_refs = {
            f"{ref.mechanic_id}@{ref.version}"
            for channel in ConsequenceChannel
            for ref in mechanic_prediction.composition.contributors_for(channel)
        }
        active_refs.update(self._pending_mechanic_refs)
        causal_receipt = CausalActionReceipt(
            receipt_id=receipt_id,
            game_scope_id=learner.game_scope,
            level_scope_id=mechanic_prediction.context.level_scope,
            step_index=self._step_index,
            before_state_ref=str(before.frames[-1].digest),
            chosen_action_and_coordinates=action,
            legal_actions_before=before.available_actions,
            predicted_effects=self._pending_clef_prediction,
            observed_effects=observed_effects,
            explained_effects=effect_comparison.explained_effects,
            residual_effects=effect_comparison.residual_effects,
            objects_or_regions_implicated=tuple(
                item.object_ref
                for item in (
                    *before_scene.endpoints,
                    *before_scene.mediators,
                    *before_scene.targets,
                )[:8]
            ),
            active_hypotheses_used=tuple(sorted(active_refs)),
            probe_or_progress_reason=self._pending_prediction,
            resource_and_failure_risk=ResourceFailureRisk(
                RiskLevel.TERMINAL
                if observation.state is GameStateName.GAME_OVER
                or before.state is GameStateName.GAME_OVER
                else RiskLevel.ELEVATED,
                "No readable resource quantity; preserve official failure and bound probes.",
            ),
            terminal_state=observation.state,
        )
        plan_prediction_failed = (
            self._pending_plan_signature is not None
            and not level_progress
            and observation.state is GameStateName.NOT_FINISHED
            and (
                (hierarchy_action and not hierarchy_consequence_certified)
                or (
                    not hierarchy_action
                    and (
                        marker_action_structure_failed
                        or any(
                            item.channel
                            in {
                                EffectChannel.CONTROLLABLE_OBJECT_DISPLACEMENT,
                                EffectChannel.OTHER_OBJECT_CHANGE,
                            }
                            and item.predicted.knowledge is EffectKnowledge.KNOWN
                            and item.kind
                            in {
                                CausalResidualKind.MISMATCH,
                                CausalResidualKind.MISSING_EFFECT,
                                CausalResidualKind.UNREADABLE,
                            }
                            for item in effect_comparison.residual_effects
                        )
                    )
                )
            )
        )
        crossed_resource_lineage_mismatch = False
        crossed_forward_action = bool(
            carrier_source_recovery_candidate is not None
            and _is_crossed_replay_forward_action(carrier_source_recovery_candidate)
        )
        crossed_inverse_action = bool(
            carrier_source_recovery_candidate is not None
            and _is_crossed_replay_inverse_action(
                carrier_source_recovery_candidate,
                recovery_signature=self._crossed_delivery_recovery_signature,
            )
        )
        access_certificate = (
            carrier_source_recovery_candidate.post_deposit_mediator_access_certificate
            if carrier_source_recovery_candidate is not None
            else None
        )
        composite_certificate = (
            carrier_source_recovery_candidate.post_access_composite_exit_certificate
            if carrier_source_recovery_candidate is not None
            else None
        )
        marker_certificate = (
            carrier_source_recovery_candidate.post_access_composite_marker_certificate
            if carrier_source_recovery_candidate is not None
            else None
        )
        if post_deposit_mediator_access_action and access_certificate is not None:
            # A submitted discriminator is one-shot even when its consequence
            # is GAME_OVER, UNKNOWN, or loses the exact resource lineage.  This
            # records only that the action was attempted; epistemic rejection
            # remains confined to an exact NOT_FINISHED consequence below.
            self._attempted_post_deposit_mediator_access_hypothesis_keys.add(
                access_certificate.hypothesis_key
            )
        if post_access_composite_exit_action and composite_certificate is not None:
            # Submission closes this exact transition-bound action across RESET,
            # while epistemic rejection remains confined to exact NOT_FINISHED.
            self._attempted_post_access_composite_exit_hypothesis_keys.add(
                composite_certificate.hypothesis_key
            )
        if post_access_composite_marker_action and marker_certificate is not None:
            self._attempted_post_access_composite_marker_hypothesis_keys.add(
                marker_certificate.hypothesis_key
            )
        if (
            (
                crossed_forward_action
                or crossed_inverse_action
                or access_certificate is not None
                or composite_certificate is not None
                or marker_certificate is not None
            )
            and not level_progress
            and observation.state is GameStateName.NOT_FINISHED
        ):
            active_lineage = self._active_crossed_replay_resource_lineage
            if marker_certificate is not None:
                assert carrier_source_recovery_candidate is not None
                crossed_resource_lineage_mismatch = bool(
                    active_lineage is None
                    or not _post_access_composite_marker_step_is_compatible(
                        carrier_source_recovery_candidate
                    )
                    or not self._active_crossed_resource_matches(observation)
                    or active_lineage.forward_remaining_actions != 0
                    or active_lineage.exhausted_after_actions
                    != marker_certificate.exhausted_after_actions
                    or self._episode_action6_count != marker_certificate.resource_action_count + 1
                )
            elif composite_certificate is not None:
                assert carrier_source_recovery_candidate is not None
                crossed_resource_lineage_mismatch = bool(
                    active_lineage is None
                    or not _post_access_composite_exit_step_is_compatible(
                        carrier_source_recovery_candidate
                    )
                    or not self._active_crossed_resource_matches(observation)
                    or active_lineage.forward_remaining_actions != 0
                    or active_lineage.exhausted_after_actions
                    != composite_certificate.exhausted_after_actions
                    or self._episode_action6_count
                    != composite_certificate.resource_action_count + 1
                )
            elif access_certificate is not None:
                assert carrier_source_recovery_candidate is not None
                crossed_resource_lineage_mismatch = bool(
                    active_lineage is None
                    or not _post_deposit_mediator_access_step_is_compatible(
                        carrier_source_recovery_candidate
                    )
                    or not self._active_crossed_resource_matches(observation)
                    or active_lineage.forward_remaining_actions != 0
                    or active_lineage.exhausted_after_actions
                    != access_certificate.exhausted_after_actions
                    or self._episode_action6_count != access_certificate.resource_action_count + 1
                )
            else:
                crossed_resource_lineage_mismatch = bool(
                    active_lineage is None
                    or not hierarchy_raster_certified
                    or not self._active_crossed_resource_matches(observation)
                    or (crossed_forward_action and active_lineage.forward_remaining_actions <= 0)
                    or (crossed_inverse_action and active_lineage.forward_remaining_actions != 0)
                )
            if not crossed_resource_lineage_mismatch and crossed_forward_action:
                assert active_lineage is not None
                self._active_crossed_replay_resource_lineage = replace(
                    active_lineage,
                    forward_remaining_actions=(active_lineage.forward_remaining_actions - 1),
                )
            elif crossed_resource_lineage_mismatch:
                if self._pending_plan_signature is not None:
                    self._latch_hierarchy_lineage_failure(
                        level_index=before.levels_completed,
                        plan_signature=self._pending_plan_signature,
                        phase=f"crossed-resource-consequence:{self._step_index}",
                    )
                self._clear_crossed_replay_execution()
        if plan_prediction_failed and hierarchy_action:
            self._active_crossed_replay_resource_lineage = None
            relation_key = child_isolation_relation_key or hierarchy_relation_key
            if relation_key is not None and self._pending_plan_signature is not None:
                self._latch_hierarchy_lineage_failure(
                    level_index=before.levels_completed,
                    plan_signature=self._pending_plan_signature,
                    phase=f"returned-consequence:{self._step_index}",
                )
        if marker_action_structure_readable:
            self._marker_reacquire_after_local_solve = False
            self._affine_reacquire_target_center = None
        if observation.state in {GameStateName.GAME_OVER, GameStateName.NOT_PLAYED}:
            self._resource_interrupted_paired_replay = None
            self._active_crossed_replay_resource_lineage = None
            if hierarchy_terminal_game_over_observed:
                self._preterminal_hierarchy_retry_signature = None
            if self._pending_plan_signature is not None and not (
                paired_resource_exhaustion or post_marker_resource_reset_bridge_action
            ):
                if hierarchy_preterminal_game_over_observed:
                    if self._preterminal_hierarchy_retry_signature == self._pending_plan_signature:
                        self._preterminal_hierarchy_retry_signature = None
                        self._failed_plan_signatures.add(self._pending_plan_signature)
                        if (
                            carrier_source_occlusion_hierarchy_action
                            and hierarchy_relation_key is not None
                        ):
                            self._failed_carrier_source_occlusion_hierarchy_relation_keys.add(
                                hierarchy_relation_key
                            )
                            residual = (
                                "the same carrier-source occlusion hierarchy plan returned "
                                "GAME_OVER before its terminal action on its one bounded "
                                "post-RESET retry; that relation is closed rather than "
                                "reopened through an alternate layout"
                            )
                        elif (
                            external_own_composite_hierarchy_action
                            and hierarchy_relation_key is not None
                        ):
                            self._failed_external_own_composite_hierarchy_relation_keys.add(
                                hierarchy_relation_key
                            )
                            residual = (
                                "the same external-own-composite hierarchy plan returned "
                                "GAME_OVER before its terminal action on its one bounded "
                                "post-RESET retry; that relation is closed rather than "
                                "reopened through an alternate layout"
                            )
                        else:
                            residual = (
                                "the same hierarchy plan returned GAME_OVER before its terminal "
                                "action on its one bounded post-RESET retry"
                            )
                    elif self._preterminal_hierarchy_retry_signature is None:
                        self._preterminal_hierarchy_retry_signature = self._pending_plan_signature
                        residual = (
                            "the hierarchy plan returned GAME_OVER before its terminal action; "
                            "one same-level retry is retained after legal RESET"
                        )
                    else:
                        self._failed_plan_signatures.add(
                            self._preterminal_hierarchy_retry_signature
                        )
                        self._failed_plan_signatures.add(self._pending_plan_signature)
                        self._preterminal_hierarchy_retry_signature = None
                        residual = (
                            "a different hierarchy plan returned GAME_OVER while the one "
                            "same-level retry was already reserved; no additional retry is retained"
                        )
                else:
                    if self._preterminal_hierarchy_retry_signature == self._pending_plan_signature:
                        self._preterminal_hierarchy_retry_signature = None
                    self._failed_plan_signatures.add(self._pending_plan_signature)
            if hierarchy_terminal_game_over_observed and hierarchy_relation_key is not None:
                if same_child_composite_cargo_action:
                    residual = (
                        "the exact same-child complementary-source composite terminal "
                        "returned GAME_OVER"
                    )
                elif carrier_source_occlusion_hierarchy_action:
                    self._failed_carrier_source_occlusion_hierarchy_relation_keys.add(
                        hierarchy_relation_key
                    )
                    residual = (
                        "the exact carrier-source occlusion discriminator terminal returned "
                        "GAME_OVER"
                    )
                elif external_own_composite_hierarchy_action:
                    self._failed_external_own_composite_hierarchy_relation_keys.add(
                        hierarchy_relation_key
                    )
                    residual = (
                        "the exact external-own-composite recombination terminal returned GAME_OVER"
                    )
                elif raw_matching_composite_hierarchy_action:
                    self._failed_raw_matching_composite_hierarchy_relation_keys.add(
                        hierarchy_relation_key
                    )
                    residual = (
                        "the exact raw-matching containing-composite terminal returned GAME_OVER"
                    )
                elif external_residual_linked_hierarchy_action:
                    self._failed_external_residual_linked_hierarchy_relation_keys.add(
                        hierarchy_relation_key
                    )
                    residual = (
                        "the exact external carrier-mask residual-chain terminal returned GAME_OVER"
                    )
                elif residual_linked_hierarchy_action:
                    self._failed_residual_linked_hierarchy_relation_keys.add(hierarchy_relation_key)
                    residual = "the exact residual-linked mixed-support terminal returned GAME_OVER"
                elif bridge_hierarchy_action:
                    self._failed_bridge_hierarchy_relation_keys.add(hierarchy_relation_key)
                    residual = (
                        "the proximity-assigned paired composite-sink terminal returned GAME_OVER"
                    )
                elif visible_node_hierarchy_action:
                    self._failed_visible_node_hierarchy_relation_keys.add(hierarchy_relation_key)
                    residual = (
                        "the exact visible-node-weighted hierarchy terminal returned GAME_OVER"
                    )
                elif weighted_hierarchy_action:
                    self._failed_weighted_hierarchy_relation_keys.add(hierarchy_relation_key)
                    residual = "the exact arity-weighted hierarchy terminal returned GAME_OVER"
                else:
                    self._failed_hierarchy_relation_keys.add(hierarchy_relation_key)
                    residual = "the exact equal-weight hierarchy terminal returned GAME_OVER"
            if post_marker_resource_reset_bridge_action:
                if post_marker_resource_exhaustion and active_post_marker_bridge is not None:
                    self._post_marker_resource_reset_bridge = replace(
                        active_post_marker_bridge,
                        game_over_observed=True,
                    )
                    residual = (
                        "the observation-proven board no-op reached the exact learned resource "
                        "boundary and returned official GAME_OVER; one fresh RESET epoch is "
                        "authorized"
                    )
                else:
                    self._post_marker_resource_reset_bridge = None
                    residual = (
                        "the post-marker resource bridge reached a nonmatching terminal boundary "
                        "and failed closed"
                    )
            elif (
                carrier_source_paired_cargo_action
                or carrier_source_paired_cargo_restoration_action
                or carrier_source_paired_cargo_role_handoff_action
                or carrier_source_paired_cargo_role_restoration_action
                or carrier_source_paired_cargo_crossed_predecessor_action
                or carrier_source_paired_cargo_crossed_delivery_action
            ):
                self._preterminal_hierarchy_retry_signature = None
                if paired_resource_exhaustion:
                    if (
                        resource_interrupted_role_replay
                        and self._paired_role_handoff_observed_context_key is not None
                        and resource_exhaustion_candidate is not None
                    ):
                        setup_relation_key = self._paired_role_handoff_observed_setup_relation_key
                        setup_plan_signature = (
                            self._paired_role_handoff_observed_setup_plan_signature
                        )
                        setup_action_count = self._paired_role_handoff_observed_setup_action_count
                        crossed_forward_action_count = (
                            self._paired_role_handoff_observed_crossed_forward_action_count
                        )
                        assert setup_relation_key is not None
                        assert setup_plan_signature is not None
                        assert setup_action_count is not None
                        assert crossed_forward_action_count is not None
                        post_receipt_resource_interrupted_replay = _ResourceInterruptedPairedReplay(
                            level_index=before.levels_completed,
                            context_key=self._paired_role_handoff_observed_context_key,
                            setup_relation_key=setup_relation_key,
                            setup_plan_signature=setup_plan_signature,
                            setup_action_count=setup_action_count,
                            crossed_forward_action_count=crossed_forward_action_count,
                            exhausted_edge_index=(resource_exhaustion_candidate.edge_index),
                            exhausted_edge_baseline=(resource_exhaustion_candidate.baseline),
                            exhausted_edge_fill_color=(resource_exhaustion_candidate.fill_color),
                            exhausted_filled_index_history=(
                                resource_exhaustion_candidate.filled_index_history
                            ),
                            observed_actions=(resource_exhaustion_candidate.observed_actions),
                            authorized_reset_epoch=self._reset_epoch_index + 1,
                        )
                    residual = (
                        "the exact paired-cargo placement, active-role handoff, or inverse "
                        "returned official GAME_OVER"
                    )
                else:
                    if self._pending_plan_signature is not None:
                        self._failed_plan_signatures.add(self._pending_plan_signature)
                    residual = (
                        "the exact paired-cargo placement, active-role handoff, or inverse "
                        "returned official GAME_OVER"
                    )
            elif carrier_source_delivery_action:
                if hierarchy_relation_key is not None:
                    self._failed_carrier_source_occlusion_hierarchy_relation_keys.add(
                        hierarchy_relation_key
                    )
                residual = "the exact carried-source delivery action returned official GAME_OVER"
            elif post_deposit_mediator_access_action:
                residual = (
                    "the one-shot post-deposit mediator-access discriminator returned "
                    "official GAME_OVER"
                )
            elif post_access_composite_exit_action:
                residual = (
                    "the one-shot post-access composite-exit discriminator returned "
                    f"official {observation.state.value}"
                )
            elif post_access_composite_marker_action:
                residual = (
                    "the one-shot post-access composite-marker discriminator returned "
                    f"official {observation.state.value}"
                )
            elif carrier_source_detachment_action:
                if hierarchy_relation_key is not None:
                    self._failed_carrier_source_occlusion_hierarchy_relation_keys.add(
                        hierarchy_relation_key
                    )
                residual = "the exact carrier-source detachment discriminator returned GAME_OVER"
            elif carrier_source_untouched_action:
                residual = (
                    "the exact untouched-carrier discriminator or restoration returned GAME_OVER"
                )
            if (
                observation.state is GameStateName.GAME_OVER
                and self._pending_completes_child_isolation
                and child_isolation_observed
                and child_isolation_hypothesis_key is not None
            ):
                self._failed_child_isolation_hypothesis_keys.add(child_isolation_hypothesis_key)
                self._failed_child_isolation_hypothesis_reasons[child_isolation_hypothesis_key] = (
                    "was falsified by an exact child-at-target official GAME_OVER "
                    "consequence for this structural child stratum"
                )
            if self._episode_exploration_root is not None and not (
                paired_resource_exhaustion or post_marker_resource_exhaustion
            ):
                if self._episode_exploration_root in self._failed_exploration_roots:
                    pass
                elif len(self._failed_exploration_roots) < self._MAX_FAILED_EXPLORATION_ROOTS:
                    self._failed_exploration_roots.add(self._episode_exploration_root)
                else:
                    self._exploration_root_capacity_exhausted = True
            self._paired_role_handoff_observed_signature = None
            self._paired_role_handoff_observed_context_key = None
            self._paired_role_handoff_observed_setup_relation_key = None
            self._paired_role_handoff_observed_setup_plan_signature = None
            self._paired_role_handoff_observed_setup_action_count = None
            self._paired_role_handoff_observed_crossed_forward_action_count = None
            self._plan.clear()
            self._marker_stage_pending_switch = None
            self._marker_reacquire_after_local_solve = False
            self._affine_reacquire_target_center = None
            self._active_hierarchy_signature = None
            self._active_hierarchy_relation_key = None
            self._active_hierarchy_supports = ()
            self._active_hierarchy_support_weights = ()
            self._active_hierarchy_recovery_actions = ()
            self._active_carrier_source_attachment_replay_context = None
            self._active_crossed_delivery_replay_context = None
            self._active_carried_source_recovery_support_indexes = ()
            self._active_carrier_source_setup_start_action_count = None
            self._active_carrier_source_setup_action_count = None
            self._active_carrier_source_crossed_forward_action_count = None
            self._crossed_delivery_recovery_signature = None
            self._clear_child_isolation_execution()
            self._last_probe_failed = not (
                paired_resource_exhaustion or post_marker_resource_exhaustion
            )
        elif observation.state is GameStateName.WIN:
            self._preterminal_hierarchy_retry_signature = None
            self._plan.clear()
            self._marker_stage_pending_switch = None
            self._marker_reacquire_after_local_solve = False
            self._affine_reacquire_target_center = None
            self._active_hierarchy_signature = None
            self._active_hierarchy_relation_key = None
            self._active_hierarchy_supports = ()
            self._active_hierarchy_support_weights = ()
            self._active_hierarchy_recovery_actions = ()
            self._active_carrier_source_attachment_replay_context = None
            self._active_crossed_delivery_replay_context = None
            self._active_carried_source_recovery_support_indexes = ()
            self._active_carrier_source_setup_start_action_count = None
            self._active_carrier_source_setup_action_count = None
            self._active_carrier_source_crossed_forward_action_count = None
            self._resource_interrupted_paired_replay = None
            self._post_marker_resource_reset_bridge = None
            self._active_crossed_replay_resource_lineage = None
            self._paired_role_handoff_observed_signature = None
            self._paired_role_handoff_observed_context_key = None
            self._paired_role_handoff_observed_setup_relation_key = None
            self._paired_role_handoff_observed_setup_plan_signature = None
            self._paired_role_handoff_observed_setup_action_count = None
            self._paired_role_handoff_observed_crossed_forward_action_count = None
            self._crossed_delivery_recovery_signature = None
            self._clear_child_isolation_execution()
            self._last_probe_failed = False
        elif level_progress:
            self._begin_level(observation)
        elif reset_recovered:
            self._begin_reset_epoch(observation)
        elif observation.state is GameStateName.UNKNOWN:
            if (
                self._pending_plan_signature is not None
                and not post_marker_resource_reset_bridge_action
            ):
                if hierarchy_action:
                    self._preterminal_hierarchy_retry_signature = None
                elif self._preterminal_hierarchy_retry_signature == self._pending_plan_signature:
                    self._preterminal_hierarchy_retry_signature = None
                self._failed_plan_signatures.add(self._pending_plan_signature)
            self._plan.clear()
            self._active_hierarchy_signature = None
            self._active_hierarchy_relation_key = None
            self._active_hierarchy_supports = ()
            self._active_hierarchy_support_weights = ()
            self._active_hierarchy_recovery_actions = ()
            self._active_carrier_source_attachment_replay_context = None
            self._active_crossed_delivery_replay_context = None
            self._active_carried_source_recovery_support_indexes = ()
            self._active_carrier_source_setup_start_action_count = None
            self._active_carrier_source_setup_action_count = None
            self._active_carrier_source_crossed_forward_action_count = None
            self._resource_interrupted_paired_replay = None
            self._post_marker_resource_reset_bridge = None
            self._active_crossed_replay_resource_lineage = None
            self._paired_role_handoff_observed_signature = None
            self._paired_role_handoff_observed_context_key = None
            self._paired_role_handoff_observed_setup_relation_key = None
            self._paired_role_handoff_observed_setup_plan_signature = None
            self._paired_role_handoff_observed_setup_action_count = None
            self._paired_role_handoff_observed_crossed_forward_action_count = None
            self._crossed_delivery_recovery_signature = None
            self._clear_child_isolation_execution()
            self._last_probe_failed = True
            if residual is None:
                residual = (
                    "official environment state was UNKNOWN; planned hierarchy sufficiency "
                    "was not assessed"
                    if hierarchy_action
                    else "official environment state was UNKNOWN"
                )
        elif post_deposit_mediator_access_action:
            if access_certificate is None or crossed_resource_lineage_mismatch:
                self._clear_crossed_replay_execution()
                residual = (
                    "the one-shot post-deposit mediator-access discriminator lost its exact "
                    "resource lineage and failed closed"
                )
            else:
                self._failed_post_deposit_mediator_access_hypothesis_keys.add(
                    access_certificate.hypothesis_key
                )
                self._post_deposit_mediator_access_closed = access_certificate.hypothesis_key
                active_lineage = self._active_crossed_replay_resource_lineage
                composite_plan = _post_access_composite_exit_plan(
                    before_scene,
                    after_scene,
                    access_certificate=access_certificate,
                    resource_lineage=active_lineage,
                    current_actions=self._episode_action6_count,
                    excluded_hypothesis_keys=(
                        self._failed_post_access_composite_exit_hypothesis_keys
                        | self._attempted_post_access_composite_exit_hypothesis_keys
                    ),
                )
                if composite_plan is None:
                    self._clear_crossed_replay_execution()
                else:
                    post_receipt_post_access_composite_exit = (composite_plan,)
                    self._last_probe_failed = False
                residual = (
                    "the unique post-deposit mediator was accessed under the exact crossed "
                    "delivery and resource certificate, but the official environment remained "
                    "NOT_FINISHED; only mediator-access sufficiency is rejected and no repeat "
                    "is authorized"
                )
        elif post_access_composite_exit_action:
            if composite_certificate is None or crossed_resource_lineage_mismatch:
                self._clear_crossed_replay_execution()
                residual = (
                    "the one-shot post-access composite-exit discriminator lost its exact "
                    "transition or resource lineage and failed closed"
                )
            else:
                self._failed_post_access_composite_exit_hypothesis_keys.add(
                    composite_certificate.hypothesis_key
                )
                self._post_access_composite_exit_closed = composite_certificate.hypothesis_key
                active_lineage = self._active_crossed_replay_resource_lineage
                marker_plan = _post_access_composite_marker_plan(
                    before_scene,
                    after_scene,
                    composite_certificate=composite_certificate,
                    resource_lineage=active_lineage,
                    current_actions=self._episode_action6_count,
                    excluded_hypothesis_keys=(
                        self._failed_post_access_composite_marker_hypothesis_keys
                        | self._attempted_post_access_composite_marker_hypothesis_keys
                    ),
                )
                if marker_plan is None:
                    self._clear_crossed_replay_execution()
                else:
                    post_receipt_post_access_composite_marker = (marker_plan,)
                    self._last_probe_failed = False
                residual = (
                    "the newly formed mediator-target composite received its one exact "
                    "lineage-bound exit action, but the official environment remained "
                    "NOT_FINISHED; only this composite-exit sufficiency hypothesis is "
                    "rejected and no repeat is authorized"
                )
        elif post_access_composite_marker_action:
            if marker_certificate is None or crossed_resource_lineage_mismatch:
                self._clear_crossed_replay_execution()
                residual = (
                    "the one-shot post-access composite-marker discriminator lost its exact "
                    "transition or resource lineage and failed closed"
                )
            else:
                self._failed_post_access_composite_marker_hypothesis_keys.add(
                    marker_certificate.hypothesis_key
                )
                self._post_access_composite_marker_closed = marker_certificate.hypothesis_key
                active_lineage = self._active_crossed_replay_resource_lineage
                protected_before = (
                    _edge_excluded_raster_hash(
                        before.frames[-1],
                        edge_index=active_lineage.edge_index,
                    )
                    if active_lineage is not None
                    else None
                )
                protected_after = (
                    _edge_excluded_raster_hash(
                        observation.frames[-1],
                        edge_index=active_lineage.edge_index,
                    )
                    if active_lineage is not None
                    else None
                )
                if (
                    active_lineage is not None
                    and action.coordinate is not None
                    and protected_before is not None
                    and protected_before == protected_after
                    and self._episode_action6_count < active_lineage.exhausted_after_actions
                    and len(active_lineage.exhausted_filled_index_history)
                    == active_lineage.exhausted_after_actions
                ):
                    self._post_marker_resource_reset_bridge = _PostMarkerResourceResetBridge(
                        level_index=before.levels_completed,
                        marker_hypothesis_key=marker_certificate.hypothesis_key,
                        no_op_coordinate=action.coordinate,
                        protected_raster_hash=protected_before,
                        edge_index=active_lineage.edge_index,
                        edge_baseline=active_lineage.edge_baseline,
                        edge_fill_color=active_lineage.edge_fill_color,
                        exhausted_filled_index_history=(
                            active_lineage.exhausted_filled_index_history
                        ),
                        armed_after_actions=self._episode_action6_count,
                        exhausted_after_actions=active_lineage.exhausted_after_actions,
                        authorized_reset_epoch=self._reset_epoch_index + 1,
                    )
                self._clear_crossed_replay_execution()
                residual = (
                    "the unique endpoint-marker-colored cell inside the post-access "
                    "composite received its one exact lineage-bound action, but the official "
                    "environment remained NOT_FINISHED; only this marker-access sufficiency "
                    "hypothesis is rejected and no repeat is authorized"
                )
        elif post_marker_resource_reset_bridge_action:
            active_bridge = self._post_marker_resource_reset_bridge
            if (
                active_bridge is not None
                and self._episode_action6_count < active_bridge.exhausted_after_actions
                and self._post_marker_resource_bridge_matches(observation)
            ):
                self._last_probe_failed = False
                residual = (
                    "the observation-proven board no-op preserved the exact learned resource "
                    "prefix before its GAME_OVER boundary"
                )
            else:
                self._post_marker_resource_reset_bridge = None
                self._last_probe_failed = True
                residual = (
                    "the post-marker board-no-op or learned resource boundary diverged and "
                    "the reset bridge failed closed"
                )
        elif marker_bootstrap:
            self._plan.clear()
            if mechanic is None and not marker_bootstrap_succeeded:
                if self._pending_plan_signature is not None:
                    self._failed_plan_signatures.add(self._pending_plan_signature)
                self._last_probe_failed = True
            else:
                self._marker_reacquire_after_local_solve = False
                self._last_probe_failed = False
        elif (
            self._pending_completes_child_isolation
            and observation.state is GameStateName.NOT_FINISHED
        ):
            if self._pending_plan_signature is not None:
                self._failed_plan_signatures.add(self._pending_plan_signature)
            if child_isolation_observed and child_isolation_hypothesis_key is not None:
                self._failed_child_isolation_hypothesis_keys.add(child_isolation_hypothesis_key)
                self._failed_child_isolation_hypothesis_reasons[child_isolation_hypothesis_key] = (
                    "was already falsified by an exact child-at-target official "
                    "NOT_FINISHED consequence for this structural child stratum"
                )
            self._plan.clear()
            if child_isolation_observed:
                if self._active_child_isolation_recovery_actions:
                    self._plan.extend(self._active_child_isolation_recovery_actions)
                    self._last_probe_failed = False
                else:
                    self._latch_hierarchy_lineage_failure(
                        level_index=before.levels_completed,
                        plan_signature=(self._pending_plan_signature or "unbound-child-plan"),
                        phase=f"missing-recovery-lineage:{self._step_index}",
                    )
                    self._clear_child_isolation_execution()
                    self._last_probe_failed = True
                residual = (
                    "the selected child mediator reached the parent target while its "
                    "sibling remained distinct, but the official environment remained "
                    "NOT_FINISHED"
                )
            else:
                self._clear_child_isolation_execution()
                self._last_probe_failed = True
                if residual is None:
                    residual = "planned child-isolation consequence was not structurally readable"
        elif self._pending_completes_child_recovery and child_recovery_restoration_certified:
            self._plan.clear()
            self._clear_child_isolation_execution()
            self._last_probe_failed = False
            residual = (
                "exact pre-discriminator hierarchy restored after child-only sufficiency "
                "was falsified"
            )
        elif carrier_source_paired_cargo_role_restoration_action and hierarchy_raster_certified:
            self._last_probe_failed = False
            residual = (
                "the paired-terminal active role restored exactly before the certified inverse"
            )
        elif hierarchy_recovery_action and not self._plan and hierarchy_raster_certified:
            if (
                carrier_source_paired_cargo_crossed_predecessor_action
                and carrier_source_recovery_candidate is not None
                and carrier_source_recovery_candidate.completes_carrier_source_paired_cargo_crossed_predecessor
            ):
                crossed_context = self._active_crossed_delivery_replay_context
                if crossed_context is not None:
                    post_receipt_crossed_delivery_context = crossed_context
                    self._last_probe_failed = False
                    residual = (
                        "the handoff-preserving predecessor cycle restored the exact "
                        "carried geometry with crossed active lineage; one target-relative "
                        "delivery is recomputed only from this returned boundary"
                    )
                else:
                    self._active_crossed_replay_resource_lineage = None
                    self._last_probe_failed = True
                    residual = (
                        "the exact crossed predecessor boundary had no retained "
                        "observation-lineage delivery context"
                    )
            elif (
                carrier_source_paired_cargo_crossed_delivery_action
                and carrier_source_recovery_candidate is not None
                and carrier_source_recovery_candidate.completes_carrier_source_paired_cargo_crossed_delivery
            ):
                active_lineage = self._active_crossed_replay_resource_lineage
                delivery_lineage_complete = bool(
                    active_lineage is not None
                    and active_lineage.forward_remaining_actions == 0
                    and self._active_crossed_resource_matches(observation)
                    and self._episode_action6_count < active_lineage.exhausted_after_actions
                )
                if self._pending_plan_signature is not None and delivery_lineage_complete:
                    self._failed_plan_signatures.add(self._pending_plan_signature)
                recovery_actions = self._active_hierarchy_recovery_actions
                self._plan.clear()
                access_plan = (
                    _post_deposit_mediator_access_plan(
                        before_scene,
                        after_scene,
                        target_center=self._pending_target_center,
                        crossed_delivery_plan_signature=self._pending_plan_signature,
                        recovery_actions=recovery_actions,
                        resource_lineage=active_lineage,
                        current_actions=self._episode_action6_count,
                        excluded_hypothesis_keys=(
                            self._failed_post_deposit_mediator_access_hypothesis_keys
                            | self._attempted_post_deposit_mediator_access_hypothesis_keys
                        ),
                    )
                    if delivery_lineage_complete and not after_scene.targets
                    else None
                )
                if access_plan is not None:
                    self._plan.append(access_plan)
                    self._last_probe_failed = False
                elif delivery_lineage_complete and after_scene.targets and recovery_actions:
                    self._crossed_delivery_recovery_signature = self._pending_plan_signature
                    self._plan.extend(recovery_actions)
                    self._last_probe_failed = False
                else:
                    self._clear_crossed_replay_execution()
                self._active_crossed_delivery_replay_context = None
                self._resource_interrupted_paired_replay = None
                residual = (
                    "the one recomputed crossed delivery matched its protected raster "
                    "but remained NOT_FINISHED; one unique observation-derived "
                    "post-deposit mediator access test is authorized strictly before "
                    "the learned resource boundary"
                    if access_plan is not None
                    else (
                        "the one recomputed crossed delivery matched its protected raster "
                        "but remained NOT_FINISHED; only its certified inverse prefix is "
                        "authorized before the learned resource boundary"
                        if self._plan
                        else (
                            "the one recomputed crossed delivery had no unique "
                            "resource-safe post-deposit mediator identity; continuation "
                            "failed closed"
                        )
                    )
                )
            elif (
                carrier_source_paired_cargo_action
                and carrier_source_recovery_candidate is not None
                and carrier_source_recovery_candidate.completes_carrier_source_paired_cargo
            ):
                if _carrier_source_paired_cargo_restoration_actions_are_compatible(
                    carrier_source_recovery_candidate
                ):
                    if self._pending_plan_signature is not None:
                        self._failed_plan_signatures.add(self._pending_plan_signature)
                    role_handoff = (
                        carrier_source_recovery_candidate.carrier_source_paired_cargo_role_handoff
                    )
                    if (
                        carrier_source_recovery_candidate.carrier_source_paired_cargo_role_handoff_family
                        and role_handoff is not None
                        and _carrier_source_paired_cargo_role_handoff_step_is_compatible(
                            role_handoff
                        )
                    ):
                        post_receipt_paired_cargo_restoration = (role_handoff,)
                    else:
                        post_receipt_paired_cargo_restoration = carrier_source_recovery_candidate.carrier_source_paired_cargo_restoration_actions
                    self._last_probe_failed = False
                else:
                    self._last_probe_failed = True
                residual = (
                    "both exact carried sources reached the previously rejected "
                    "external-chain targets, "
                    "but the official environment remained NOT_FINISHED"
                )
            elif (
                carrier_source_paired_cargo_role_handoff_action
                and carrier_source_recovery_candidate is not None
            ):
                attachment_context = self._active_carrier_source_attachment_replay_context
                setup_plan_signature = (
                    _carrier_source_attachment_setup_plan_signature(attachment_context)
                    if attachment_context is not None
                    else None
                )
                setup_relation_key = self._active_hierarchy_relation_key
                setup_action_count = self._active_carrier_source_setup_action_count
                crossed_forward_action_count = (
                    self._active_carrier_source_crossed_forward_action_count
                )
                if (
                    carrier_source_recovery_candidate.carrier_source_paired_cargo_crossed_predecessor_family
                    and _carrier_source_paired_cargo_crossed_predecessor_actions_are_compatible(
                        carrier_source_recovery_candidate
                    )
                    and self._active_crossed_delivery_replay_context is not None
                    and attachment_context is not None
                ):
                    post_receipt_paired_cargo_restoration = carrier_source_recovery_candidate.carrier_source_paired_cargo_crossed_predecessor_actions
                    self._paired_role_handoff_observed_signature = self._pending_plan_signature
                    self._paired_role_handoff_observed_context_key = (
                        _carrier_source_attachment_context_key(attachment_context)
                    )
                    self._last_probe_failed = False
                elif (
                    not carrier_source_recovery_candidate.carrier_source_paired_cargo_crossed_predecessor_family
                    and _carrier_source_paired_cargo_role_restoration_actions_are_compatible(
                        carrier_source_recovery_candidate
                    )
                    and attachment_context is not None
                    and setup_plan_signature is not None
                    and setup_plan_signature == self._active_hierarchy_signature
                    and setup_relation_key is not None
                    and setup_relation_key.startswith("affine-carrier-source-occlusion-relation:")
                    and setup_action_count is not None
                    and setup_action_count > 0
                    and crossed_forward_action_count is not None
                    and crossed_forward_action_count > 0
                ):
                    post_receipt_paired_cargo_restoration = carrier_source_recovery_candidate.carrier_source_paired_cargo_role_restoration_actions
                    self._paired_role_handoff_observed_signature = self._pending_plan_signature
                    self._paired_role_handoff_observed_context_key = (
                        _carrier_source_attachment_context_key(attachment_context)
                    )
                    self._paired_role_handoff_observed_setup_relation_key = setup_relation_key
                    self._paired_role_handoff_observed_setup_plan_signature = setup_plan_signature
                    self._paired_role_handoff_observed_setup_action_count = setup_action_count
                    self._paired_role_handoff_observed_crossed_forward_action_count = (
                        crossed_forward_action_count
                    )
                    self._last_probe_failed = False
                else:
                    self._paired_role_handoff_observed_setup_relation_key = None
                    self._paired_role_handoff_observed_setup_plan_signature = None
                    self._paired_role_handoff_observed_setup_action_count = None
                    self._paired_role_handoff_observed_crossed_forward_action_count = None
                    self._last_probe_failed = True
                residual = (
                    "the complementary paired-terminal active-role handoff was exact, but "
                    "the official environment remained NOT_FINISHED"
                )
            elif (
                carrier_source_paired_cargo_restoration_action
                and carrier_source_recovery_candidate is not None
                and carrier_source_recovery_candidate.completes_carrier_source_paired_cargo_restoration
            ):
                if self._pending_plan_signature is not None:
                    self._failed_plan_signatures.add(self._pending_plan_signature)
                attachment_context = self._active_carrier_source_attachment_replay_context
                carried_indexes = self._active_carried_source_recovery_support_indexes
                if self._pending_plan_signature == self._crossed_delivery_recovery_signature:
                    self._preterminal_hierarchy_retry_signature = None
                    self._active_hierarchy_signature = None
                    self._active_hierarchy_relation_key = None
                    self._active_hierarchy_supports = ()
                    self._active_hierarchy_support_weights = ()
                    self._active_hierarchy_recovery_actions = ()
                    self._active_carrier_source_attachment_replay_context = None
                    self._active_crossed_delivery_replay_context = None
                    self._active_carried_source_recovery_support_indexes = ()
                    self._active_crossed_replay_resource_lineage = None
                    self._crossed_delivery_recovery_signature = None
                    self._last_probe_failed = True
                    residual = (
                        "the certified crossed-delivery inverse completed without WIN; "
                        "no further interaction is authorized"
                    )
                elif (
                    not carrier_source_recovery_candidate.carrier_source_paired_cargo_role_handoff_family
                    and attachment_context is not None
                    and len(carried_indexes) == len(attachment_context.carrier_source_supports)
                ):
                    post_receipt_paired_cargo_context = attachment_context
                    post_receipt_paired_cargo_indexes = carried_indexes
                    post_receipt_paired_cargo_role_handoff_family = True
                    self._last_probe_failed = False
                else:
                    self._last_probe_failed = True
                residual = (
                    "the exact paired-cargo inverse restored the observed carried-source "
                    "boundary after paired placement remained NOT_FINISHED"
                )
            elif carrier_source_detachment_action and carrier_source_recovery_candidate is not None:
                if hierarchy_relation_key is not None:
                    self._failed_carrier_source_occlusion_hierarchy_relation_keys.add(
                        hierarchy_relation_key
                    )
                if deposited_source_detachment_matches:
                    self._preterminal_hierarchy_retry_signature = None
                    self._active_hierarchy_signature = None
                    self._active_hierarchy_relation_key = None
                    self._active_hierarchy_supports = ()
                    self._active_hierarchy_support_weights = ()
                    self._active_hierarchy_recovery_actions = ()
                    self._active_carrier_source_attachment_replay_context = None
                    self._active_crossed_delivery_replay_context = None
                    self._active_carried_source_recovery_support_indexes = ()
                    self._crossed_delivery_recovery_signature = None
                    self._last_probe_failed = False
                    residual = (
                        "the exact inverse detached the endpoint group while the delivered "
                        "source remained deposited at the former target; continuation is "
                        "reopened only from this observation"
                    )
                else:
                    attachment_context = self._active_carrier_source_attachment_replay_context
                    if attachment_context is not None:
                        post_receipt_attachment_continuation = (
                            _carrier_source_attachment_continuation_after_observed_restoration(
                                attachment_context,
                                carrier_source_recovery_candidate,
                                after_scene,
                            )
                        )
                    if post_receipt_attachment_continuation:
                        # The same immutable replay boundary is still needed to identify
                        # the final alternative-endpoint consequence.  It is consumed
                        # exactly once after that later receipt, never by a queued action.
                        self._active_carrier_source_attachment_replay_context = attachment_context
                    else:
                        post_receipt_untouched_context = attachment_context
                        self._active_carrier_source_attachment_replay_context = None
                        self._active_crossed_delivery_replay_context = None
                    self._last_probe_failed = True
                    residual = (
                        "the exact inverse restored the pre-delivery raster with the source "
                        "still attached; repeated target delivery is rejected"
                    )
            elif (
                carrier_source_untouched_discriminator_action
                and carrier_source_recovery_candidate is not None
            ):
                matched_discriminator = (
                    carrier_source_recovery_alternative
                    if carried_source_recovery_certified
                    else carrier_source_recovery_candidate
                )
                if (
                    matched_discriminator is not None
                    and _carrier_source_untouched_restoration_actions_are_compatible(
                        matched_discriminator
                    )
                ):
                    post_receipt_untouched_restoration = (
                        matched_discriminator.carrier_source_untouched_restoration_actions
                    )
                    self._last_probe_failed = False
                    residual = (
                        "the untouched carrier followed its endpoint exactly; restore the "
                        "discriminator while retaining the newly certified attachment"
                        if carried_source_recovery_certified
                        else (
                            "the untouched source remained stationary under the exact historical "
                            "inverse; restore the discriminator without promoting attachment"
                        )
                    )
                else:
                    self._last_probe_failed = True
                    residual = "the untouched-carrier consequence had no exact closed restoration"
            elif (
                carrier_source_delivery_action
                and carrier_source_recovery_candidate is not None
                and carrier_source_recovery_candidate.completes_carrier_source_delivery
            ):
                if hierarchy_relation_key is not None:
                    self._failed_carrier_source_occlusion_hierarchy_relation_keys.add(
                        hierarchy_relation_key
                    )
                detachment_probe = carrier_source_recovery_candidate.carrier_source_detachment_probe
                if (
                    carrier_source_target_promoted_to_mediator
                    and detachment_probe is not None
                    and _carrier_source_detachment_step_is_compatible(detachment_probe)
                ):
                    self._plan.append(detachment_probe)
                    self._last_probe_failed = False
                else:
                    self._last_probe_failed = True
                residual = (
                    "the exact carried source reached its unique observed raw target, but "
                    "the official environment remained NOT_FINISHED"
                )
            elif (
                carrier_source_untouched_restoration_action
                and carrier_source_recovery_candidate is not None
                and carrier_source_recovery_candidate.completes_carrier_source_untouched_restoration
            ):
                attachment_context = self._active_carrier_source_attachment_replay_context
                carried_indexes = self._active_carried_source_recovery_support_indexes
                if attachment_context is not None and len(carried_indexes) == len(
                    attachment_context.carrier_source_supports
                ):
                    post_receipt_paired_cargo_context = attachment_context
                    post_receipt_paired_cargo_indexes = carried_indexes
                    self._last_probe_failed = False
                    residual = (
                        "exact endpoint recovery ended with an observation-certified source "
                        "attachment; no unrelated continuation is authorized"
                    )
                else:
                    self._last_probe_failed = True
                    residual = (
                        "the untouched-carrier restoration preserved an incomplete carried set; "
                        "no paired continuation is authorized"
                    )
            elif (
                carrier_source_occlusion_hierarchy_recovery_action
                and self._active_carried_source_recovery_support_indexes
            ):
                self._last_probe_failed = True
                residual = (
                    "exact endpoint recovery ended with an observation-certified source "
                    "attachment; no unrelated continuation is authorized"
                )
            else:
                self._preterminal_hierarchy_retry_signature = None
                self._active_hierarchy_signature = None
                self._active_hierarchy_relation_key = None
                self._active_hierarchy_supports = ()
                self._active_hierarchy_support_weights = ()
                self._active_hierarchy_recovery_actions = ()
                self._active_carrier_source_attachment_replay_context = None
                self._active_crossed_delivery_replay_context = None
                self._active_carried_source_recovery_support_indexes = ()
                self._crossed_delivery_recovery_signature = None
                self._last_probe_failed = False
                residual = (
                    "exact pre-hypothesis hierarchy and both filled source disks restored after "
                    "carrier-source occlusion sufficiency failed"
                    if carrier_source_occlusion_hierarchy_recovery_action
                    else (
                        "exact pre-hypothesis hierarchy restored after external-own-composite "
                        "recombination sufficiency failed"
                        if external_own_composite_hierarchy_recovery_action
                        else (
                            "exact pre-hypothesis hierarchy restored after raw-matching "
                            "containing-composite sufficiency failed"
                            if raw_matching_composite_hierarchy_recovery_action
                            else (
                                "exact pre-hypothesis hierarchy restored after external carrier-mask "
                                "residual-chain sufficiency failed"
                                if external_residual_linked_hierarchy_recovery_action
                                else (
                                    "exact pre-hypothesis hierarchy restored after residual-linked "
                                    "mixed-support sufficiency failed"
                                    if residual_linked_hierarchy_recovery_action
                                    else (
                                        "exact pre-hypothesis hierarchy restored after joint "
                                        "sufficiency failed"
                                    )
                                )
                            )
                        )
                    )
                )
        elif self._pending_completes_hierarchy and observation.state is GameStateName.NOT_FINISHED:
            self._preterminal_hierarchy_retry_signature = None
            if self._pending_plan_signature is not None:
                self._failed_plan_signatures.add(self._pending_plan_signature)
            if hierarchy_supports_observed and hierarchy_relation_key is not None:
                if same_child_composite_cargo_action:
                    # The bridge relation remains observed evidence; only this
                    # finite same-child composition plan is falsified.
                    pass
                elif carrier_source_occlusion_hierarchy_action:
                    self._failed_carrier_source_occlusion_hierarchy_relation_keys.add(
                        hierarchy_relation_key
                    )
                elif external_own_composite_hierarchy_action:
                    self._failed_external_own_composite_hierarchy_relation_keys.add(
                        hierarchy_relation_key
                    )
                elif raw_matching_composite_hierarchy_action:
                    self._failed_raw_matching_composite_hierarchy_relation_keys.add(
                        hierarchy_relation_key
                    )
                elif external_residual_linked_hierarchy_action:
                    self._failed_external_residual_linked_hierarchy_relation_keys.add(
                        hierarchy_relation_key
                    )
                elif residual_linked_hierarchy_action:
                    self._failed_residual_linked_hierarchy_relation_keys.add(hierarchy_relation_key)
                elif bridge_hierarchy_action:
                    self._failed_bridge_hierarchy_relation_keys.add(hierarchy_relation_key)
                elif visible_node_hierarchy_action:
                    self._failed_visible_node_hierarchy_relation_keys.add(hierarchy_relation_key)
                elif weighted_hierarchy_action:
                    self._failed_weighted_hierarchy_relation_keys.add(hierarchy_relation_key)
                else:
                    self._failed_hierarchy_relation_keys.add(hierarchy_relation_key)
            recovery_actions = self._active_hierarchy_recovery_actions
            self._plan.clear()
            if hierarchy_supports_observed and recovery_actions:
                self._plan.extend(recovery_actions)
                self._last_probe_failed = False
            else:
                self._active_hierarchy_signature = None
                self._active_hierarchy_relation_key = None
                self._active_hierarchy_supports = ()
                self._active_hierarchy_support_weights = ()
                self._active_hierarchy_recovery_actions = ()
                self._active_carrier_source_attachment_replay_context = None
                self._active_crossed_delivery_replay_context = None
                self._active_carried_source_recovery_support_indexes = ()
                self._crossed_delivery_recovery_signature = None
                self._last_probe_failed = True
            if hierarchy_supports_observed:
                residual = (
                    (
                        "both complementary source masks were accumulated on each assigned "
                        "child and delivered to their exact residual-color rings, but the "
                        "official environment remained NOT_FINISHED"
                    )
                    if same_child_composite_cargo_action
                    else (
                        "the raw-linked child and its exact carrier-mask counterpart each "
                        "occluded only their assigned filled source disk, but the official "
                        "environment remained NOT_FINISHED"
                    )
                    if carrier_source_occlusion_hierarchy_action
                    else (
                        "the carrier-mask counterpart reached its unique external sink while "
                        "the raw-linked child reached its own bridge composite sink, but the "
                        "official environment remained NOT_FINISHED"
                    )
                    if external_own_composite_hierarchy_action
                    else (
                        "the raw-linked child retained the singleton raw support while "
                        "its counterpart reached the unique containing composite sink, "
                        "but the official environment remained NOT_FINISHED"
                    )
                    if raw_matching_composite_hierarchy_action
                    else (
                        "the raw-linked child and its carrier-mask counterpart reached "
                        "their unique external residual-chain supports, but the official "
                        "environment remained NOT_FINISHED"
                    )
                    if external_residual_linked_hierarchy_action
                    else (
                        "the residual-linked child reached the raw parent while every "
                        "other child reached its nonmatching composite sink, but the "
                        "official environment remained NOT_FINISHED"
                    )
                    if residual_linked_hierarchy_action
                    else (
                        "both child mediators reached their proximity-assigned composite sinks "
                        "but the official environment remained NOT_FINISHED"
                    )
                    if bridge_hierarchy_action
                    else (
                        "the visible-node-weighted child-mediator centroid reached the target "
                        "but the official environment remained NOT_FINISHED"
                        if visible_node_hierarchy_action
                        else (
                            "the arity-weighted child-mediator centroid reached the parent "
                            "target but the official environment remained NOT_FINISHED"
                            if weighted_hierarchy_action
                            else (
                                "distinct child mediators reached the predicted parent "
                                "centroid but the official environment remained NOT_FINISHED"
                            )
                        )
                    )
                )
            elif residual is None:
                residual = "planned hierarchy consequence was not structurally readable"
        elif mechanic is not None and not self._pending_mechanic_refs:
            self._plan.clear()
            if not self._install_plan(mechanic, after_scene):
                residual = "no readable target-relative affine plan"
                self._last_probe_failed = True
        elif local_target_satisfied:
            self._plan.clear()
            self._marker_reacquire_after_local_solve = True
            is_ordinary_affine = any(
                item.startswith(("affine:", "affine-transfer:"))
                for item in self._pending_mechanic_refs
            )
            completed_target = self._pending_target_center
            has_remaining_group = bool(
                is_ordinary_affine
                and completed_target is not None
                and any(
                    _unique_affine_endpoint_group(after_scene, hub) is not None
                    for hub in _remaining_unsatisfied_affine_hubs(
                        after_scene,
                        completed_target_center=completed_target,
                    )
                )
            )
            self._affine_reacquire_target_center = completed_target if has_remaining_group else None
            self._last_probe_failed = False
        elif plan_prediction_failed or self._pending_completes_local_target:
            if self._pending_plan_signature is not None:
                if hierarchy_action:
                    self._preterminal_hierarchy_retry_signature = None
                elif self._preterminal_hierarchy_retry_signature == self._pending_plan_signature:
                    self._preterminal_hierarchy_retry_signature = None
                self._failed_plan_signatures.add(self._pending_plan_signature)
            self._plan.clear()
            self._marker_stage_pending_switch = None
            if hierarchy_action:
                self._active_hierarchy_signature = None
                self._active_hierarchy_relation_key = None
                self._active_hierarchy_supports = ()
                self._active_hierarchy_support_weights = ()
                self._active_hierarchy_recovery_actions = ()
                self._active_carrier_source_attachment_replay_context = None
                self._active_crossed_delivery_replay_context = None
                self._active_carried_source_recovery_support_indexes = ()
                self._crossed_delivery_recovery_signature = None
            if child_isolation_action:
                self._clear_child_isolation_execution()
            self._last_probe_failed = True

        receipt = VisualActionReceipt(
            receipt_id=receipt_id,
            level_index=before.levels_completed,
            before_frame_hash=str(before.frames[-1].digest),
            after_frame_hash=str(observation.frames[-1].digest),
            action=action,
            purpose=self._pending_purpose,
            prediction=self._pending_prediction,
            observed=observed,
            residual=residual,
            source_mechanic_refs=self._pending_mechanic_refs,
            before_state=before.state,
            after_state=observation.state,
            levels_before=before.levels_completed,
            levels_after=observation.levels_completed,
            changed_cells=changed,
            causal_action_receipt=causal_receipt,
            mechanic_prediction_receipt=mechanic_prediction,
            mechanic_learning_receipt=learning,
        )
        self._receipts.append(receipt)
        self._durable_receipts.append(receipt.to_dict())
        if post_receipt_resource_interrupted_replay is not None:
            self._resource_interrupted_paired_replay = post_receipt_resource_interrupted_replay

        # A completed action receipt is immutable.  Only after preserving the exact
        # observed consequence may a finite consequence-gated continuation become
        # executable or even be derived from its retained replay context.
        if crossed_resource_lineage_mismatch:
            self._clear_crossed_replay_execution()
        elif post_receipt_post_access_composite_exit:
            self._plan.extend(post_receipt_post_access_composite_exit)
            self._last_probe_failed = False
        elif post_receipt_post_access_composite_marker:
            self._plan.extend(post_receipt_post_access_composite_marker)
            self._last_probe_failed = False
        elif post_receipt_attachment_continuation:
            self._plan.extend(post_receipt_attachment_continuation)
            self._last_probe_failed = False
        elif (
            post_receipt_untouched_context is not None
            and carrier_source_recovery_candidate is not None
        ):
            try:
                untouched_continuation = (
                    _carrier_source_untouched_discriminator_after_observed_attachment(
                        post_receipt_untouched_context,
                        carrier_source_recovery_candidate,
                        after_scene,
                    )
                )
            except ValueError:
                # The factual action receipt is already durable.  A malformed or
                # internally inconsistent replay context may suppress only the future
                # hypothesis; pending action state must still close normally.
                untouched_continuation = ()
            if untouched_continuation:
                self._plan.extend(untouched_continuation)
                self._active_carrier_source_attachment_replay_context = (
                    post_receipt_untouched_context
                )
                self._last_probe_failed = False
        elif post_receipt_untouched_restoration:
            self._plan.extend(post_receipt_untouched_restoration)
            self._last_probe_failed = False
        elif post_receipt_paired_cargo_restoration:
            self._plan.extend(post_receipt_paired_cargo_restoration)
            self._last_probe_failed = False
        elif post_receipt_crossed_delivery_context is not None:
            active_lineage = self._active_crossed_replay_resource_lineage
            context_key = _carrier_source_attachment_context_key(
                post_receipt_crossed_delivery_context.attachment_context
            )
            current_resource_matches = bool(
                active_lineage is not None and self._active_crossed_resource_matches(observation)
            )
            crossed_delivery_plan = (
                _carrier_source_crossed_delivery_after_observed_predecessor(
                    post_receipt_crossed_delivery_context,
                    after_scene,
                    rejected_signatures=self._failed_plan_signatures,
                )
                if active_lineage is not None
                and active_lineage.level_index == observation.levels_completed
                and active_lineage.context_key == context_key
                and active_lineage.reset_epoch == self._reset_epoch_index
                and current_resource_matches
                else None
            )
            budget_closes = bool(
                crossed_delivery_plan is not None
                and active_lineage is not None
                and active_lineage.forward_remaining_actions == len(crossed_delivery_plan.actions)
                and _strict_crossed_replay_budget_closes(
                    current_actions=self._episode_action6_count,
                    route_action_upper_bound=(active_lineage.forward_remaining_actions),
                    exhausted_after_actions=active_lineage.exhausted_after_actions,
                )
            )
            self._active_crossed_delivery_replay_context = None
            if (
                crossed_delivery_plan is not None
                and budget_closes
                and _carrier_source_crossed_delivery_recovery_is_compatible(crossed_delivery_plan)
            ):
                self._plan.extend(crossed_delivery_plan.actions)
                self._active_hierarchy_signature = crossed_delivery_plan.signature
                self._active_hierarchy_supports = crossed_delivery_plan.supports
                self._active_hierarchy_support_weights = crossed_delivery_plan.support_weights
                self._active_hierarchy_recovery_actions = crossed_delivery_plan.recovery_actions
                self._active_carrier_source_attachment_replay_context = (
                    post_receipt_crossed_delivery_context.attachment_context
                )
                self._last_probe_failed = False
            else:
                self._clear_crossed_replay_execution()
        elif post_receipt_paired_cargo_context is not None:
            interrupted_replay = self._resource_interrupted_paired_replay
            context_key = _carrier_source_attachment_context_key(post_receipt_paired_cargo_context)
            setup_start = self._active_carrier_source_setup_start_action_count
            if (
                self._active_carrier_source_setup_action_count is None
                and setup_start is not None
                and self._episode_action6_count > setup_start
            ):
                self._active_carrier_source_setup_action_count = (
                    self._episode_action6_count - setup_start
                )
            if self._active_carrier_source_crossed_forward_action_count is None:
                if interrupted_replay is not None and interrupted_replay.setup_replay_started:
                    self._active_carrier_source_crossed_forward_action_count = (
                        interrupted_replay.crossed_forward_action_count
                    )
                else:
                    self._active_carrier_source_crossed_forward_action_count = (
                        _carrier_source_crossed_replay_action_budget_preview(
                            post_receipt_paired_cargo_context,
                            after_scene,
                            carried_indexes=post_receipt_paired_cargo_indexes,
                        )
                    )
            endpoint_count = _carrier_source_crossed_replay_context_endpoint_count(
                post_receipt_paired_cargo_context,
                carried_indexes=post_receipt_paired_cargo_indexes,
            )
            replay_prefix_matches = bool(
                endpoint_count is not None
                and _matching_resource_interrupted_paired_replay(
                    interrupted_replay,
                    level_index=observation.levels_completed,
                    context_key=context_key,
                    reset_epoch=self._reset_epoch_index,
                    candidates=self._episode_resource_candidates,
                    current_actions=self._episode_action6_count,
                )
                is not None
            )
            paired_cargo_plan = (
                _carrier_source_paired_cargo_plan_after_observed_restoration(
                    post_receipt_paired_cargo_context,
                    after_scene,
                    carried_indexes=post_receipt_paired_cargo_indexes,
                    rejected_signatures=self._failed_plan_signatures,
                    include_terminal_role_handoff=(
                        replay_prefix_matches or post_receipt_paired_cargo_role_handoff_family
                    ),
                    include_crossed_predecessor=replay_prefix_matches,
                )
                if interrupted_replay is None or replay_prefix_matches
                else None
            )
            replay_action_budget = (
                _carrier_source_crossed_replay_action_budget(
                    paired_cargo_plan,
                    rejected_signatures=self._failed_plan_signatures,
                )
                if replay_prefix_matches and paired_cargo_plan is not None
                else None
            )
            authorized_lineage = _authorize_resource_interrupted_paired_replay(
                interrupted_replay,
                level_index=observation.levels_completed,
                context_key=context_key,
                reset_epoch=self._reset_epoch_index,
                candidates=self._episode_resource_candidates,
                current_actions=self._episode_action6_count,
                forward_remaining_actions=replay_action_budget,
            )
            install_plan = bool(
                paired_cargo_plan is not None
                and (interrupted_replay is None or authorized_lineage is not None)
            )
            if install_plan and paired_cargo_plan is not None:
                self._plan.extend(paired_cargo_plan.actions)
                self._active_carrier_source_attachment_replay_context = (
                    post_receipt_paired_cargo_context
                )
                self._active_crossed_delivery_replay_context = (
                    paired_cargo_plan.carrier_source_crossed_delivery_replay_context
                )
                if interrupted_replay is not None and authorized_lineage is not None:
                    self._active_crossed_replay_resource_lineage = authorized_lineage
                    self._resource_interrupted_paired_replay = None
                self._last_probe_failed = False
            else:
                self._active_crossed_delivery_replay_context = None
                self._active_crossed_replay_resource_lineage = None
                if interrupted_replay is not None:
                    self._resource_interrupted_paired_replay = None
                self._last_probe_failed = True

        self._previous_observation = observation
        self._clear_pending_action_state()
        self._step_index += 1

    def close(self) -> None:
        if self._pending_action is not None:
            raise PolicyError("cannot close with an unresolved submitted action")

    def cancel_unsubmitted_action(self) -> None:
        """Discard a selected action that never crossed the environment boundary.

        Cancellation earns no receipt, learning update, or prediction sequence.
        The learner prediction is retracted before every policy-side pending
        field is restored to the same invariant used after a real consequence.
        """

        before = self._pending_before
        action = self._pending_action
        prediction = self._pending_mechanic_prediction
        carrier_source_candidate = self._pending_carrier_source_recovery_candidate
        interrupted_setup_replay = self._resource_interrupted_paired_replay is not None
        interrupted_untouched_continuation = bool(
            carrier_source_candidate is not None
            and (
                carrier_source_candidate.carrier_source_untouched_role_exchange_step
                or carrier_source_candidate.carrier_source_untouched_discriminator_step
                or carrier_source_candidate.carrier_source_untouched_restoration_step
                or carrier_source_candidate.carrier_source_paired_cargo_step
                or carrier_source_candidate.carrier_source_paired_cargo_restoration_step
                or carrier_source_candidate.carrier_source_paired_cargo_role_handoff_step
                or carrier_source_candidate.carrier_source_paired_cargo_role_restoration_step
                or carrier_source_candidate.carrier_source_paired_cargo_crossed_predecessor_step
                or carrier_source_candidate.carrier_source_paired_cargo_crossed_delivery_step
                or carrier_source_candidate.post_deposit_mediator_access_certificate is not None
                or carrier_source_candidate.post_access_composite_exit_certificate is not None
                or carrier_source_candidate.post_access_composite_marker_certificate is not None
            )
        )
        learner = self._mechanical_learner
        learner_pending = learner.pending if learner is not None else ()
        if before is None and action is None and prediction is None and not learner_pending:
            return
        if learner is None:
            raise PolicyError("cannot cancel pending policy state without its mechanical learner")
        prediction_id = prediction.prediction_id if prediction is not None else None
        if prediction_id is None:
            if len(learner_pending) != 1:
                raise PolicyError("cannot identify the sole interrupted mechanical prediction")
            prediction_id = learner_pending[0].prediction_id
        elif tuple(item.prediction_id for item in learner_pending) != (prediction_id,):
            raise PolicyError("policy and learner pending prediction identities disagree")
        learner.cancel_unsubmitted_prediction(prediction_id)
        self._clear_pending_action_state()
        if interrupted_setup_replay:
            self._resource_interrupted_paired_replay = None
            self._clear_crossed_replay_execution()
            return
        self._active_carrier_source_attachment_replay_context = None
        self._active_crossed_delivery_replay_context = None
        self._resource_interrupted_paired_replay = None
        self._active_crossed_replay_resource_lineage = None
        self._crossed_delivery_recovery_signature = None
        if interrupted_untouched_continuation:
            self._plan.clear()
            self._last_probe_failed = True

    def drain_durable_receipts(self) -> tuple[dict[str, JSONValue], ...]:
        """Return each newly completed receipt exactly once for durable journaling."""

        receipts = tuple(self._durable_receipts)
        self._durable_receipts.clear()
        return receipts

    def snapshot(self) -> dict[str, JSONValue]:
        """Return bounded, deterministic campaign evidence."""

        learner = self._mechanical_learner
        transfer_levels: list[JSONValue] = []
        for level in sorted(self._transfer_confirmed_levels):
            transfer_levels.append(level)
        lineage_failures: list[JSONValue] = []
        for level_index, relation_key, plan_signature, phase in sorted(
            self._failed_hierarchy_lineages
        )[-32:]:
            lineage_failures.append(
                {
                    "level_index": level_index,
                    "relation_key": relation_key,
                    "plan_signature": plan_signature,
                    "phase": phase,
                }
            )
        current_lineage_failure: JSONValue = None
        if self._hierarchy_lineage_lost is not None:
            level_index, relation_key, plan_signature, phase = self._hierarchy_lineage_lost
            current_lineage_failure = {
                "level_index": level_index,
                "relation_key": relation_key,
                "plan_signature": plan_signature,
                "phase": phase,
            }
        rejected_child_hypotheses = self._failed_child_isolation_hypothesis_keys
        child_family_rejected_relations = sum(
            bool(hypothesis_keys) and hypothesis_keys <= rejected_child_hypotheses
            for hypothesis_keys in self._child_isolation_hypotheses_by_relation.values()
        )
        remaining_child_hypotheses = (
            self._current_child_isolation_hypothesis_keys - rejected_child_hypotheses
        )
        return {
            "active_level_index": self._level_index,
            "affine_reacquire_after_local_solve": (
                self._affine_reacquire_target_center is not None
            ),
            "affine_ledger_ref": (
                self._affine_ledger_ref.to_dict() if self._affine_ledger_ref is not None else None
            ),
            "episode_exploration_root_active": self._episode_exploration_root is not None,
            "exploration_root_capacity_exhausted": (self._exploration_root_capacity_exhausted),
            "failed_exploration_root_count": len(self._failed_exploration_roots),
            "failed_plan_count": len(self._failed_plan_signatures),
            "edge_resource_candidate_count": len(self._episode_resource_candidates),
            "episode_action6_count": self._episode_action6_count,
            "post_marker_resource_reset_bridge_active": (
                self._post_marker_resource_reset_bridge is not None
            ),
            "post_marker_resource_reset_bridge_game_over_observed": (
                self._post_marker_resource_reset_bridge.game_over_observed
                if self._post_marker_resource_reset_bridge is not None
                else False
            ),
            "post_marker_resource_reset_bridge_armed_after_actions": (
                self._post_marker_resource_reset_bridge.armed_after_actions
                if self._post_marker_resource_reset_bridge is not None
                else None
            ),
            "post_marker_resource_reset_bridge_exhausted_after_actions": (
                self._post_marker_resource_reset_bridge.exhausted_after_actions
                if self._post_marker_resource_reset_bridge is not None
                else None
            ),
            "post_marker_resource_reset_bridge_authorized_reset_epoch": (
                self._post_marker_resource_reset_bridge.authorized_reset_epoch
                if self._post_marker_resource_reset_bridge is not None
                else None
            ),
            "resource_interrupted_paired_replay_active": (
                self._resource_interrupted_paired_replay is not None
            ),
            "resource_interrupted_observed_actions": (
                self._resource_interrupted_paired_replay.observed_actions
                if self._resource_interrupted_paired_replay is not None
                else None
            ),
            "crossed_delivery_boundary_active": (
                self._active_crossed_delivery_replay_context is not None
            ),
            "crossed_delivery_recovery_active": (
                self._crossed_delivery_recovery_signature is not None
            ),
            "post_deposit_mediator_access_active": bool(
                (
                    self._pending_plan_signature is not None
                    and self._pending_plan_signature.startswith(
                        "affine-crossed-post-deposit-mediator-access:"
                    )
                )
                or any(
                    planned.post_deposit_mediator_access_certificate is not None
                    for planned in self._plan
                )
            ),
            "post_deposit_mediator_access_closed": (
                self._post_deposit_mediator_access_closed is not None
            ),
            "post_deposit_mediator_access_attempted_count": len(
                self._attempted_post_deposit_mediator_access_hypothesis_keys
            ),
            "post_deposit_mediator_access_rejected_count": len(
                self._failed_post_deposit_mediator_access_hypothesis_keys
            ),
            "post_access_composite_exit_active": bool(
                (
                    self._pending_plan_signature is not None
                    and self._pending_plan_signature.startswith(
                        "affine-crossed-post-access-composite-exit:"
                    )
                )
                or any(
                    planned.post_access_composite_exit_certificate is not None
                    for planned in self._plan
                )
            ),
            "post_access_composite_exit_closed": (
                self._post_access_composite_exit_closed is not None
            ),
            "post_access_composite_exit_attempted_count": len(
                self._attempted_post_access_composite_exit_hypothesis_keys
            ),
            "post_access_composite_exit_rejected_count": len(
                self._failed_post_access_composite_exit_hypothesis_keys
            ),
            "post_access_composite_marker_active": bool(
                (
                    self._pending_plan_signature is not None
                    and self._pending_plan_signature.startswith(
                        "affine-crossed-post-access-composite-marker:"
                    )
                )
                or any(
                    planned.post_access_composite_marker_certificate is not None
                    for planned in self._plan
                )
            ),
            "post_access_composite_marker_closed": (
                self._post_access_composite_marker_closed is not None
            ),
            "post_access_composite_marker_attempted_count": len(
                self._attempted_post_access_composite_marker_hypothesis_keys
            ),
            "post_access_composite_marker_rejected_count": len(
                self._failed_post_access_composite_marker_hypothesis_keys
            ),
            "hierarchy_preterminal_retry_count": int(
                self._preterminal_hierarchy_retry_signature is not None
            ),
            "child_isolation_active": (self._active_child_isolation_relation_key is not None),
            "child_isolation_relation_key": self._active_child_isolation_relation_key,
            "child_isolation_hypothesis_key": self._active_child_isolation_hypothesis_key,
            "child_isolation_hypothesis_rejected_count": len(rejected_child_hypotheses),
            "child_isolation_distinct_strata_count": len(
                self._current_child_isolation_hypothesis_keys
            ),
            "child_isolation_remaining_strata_count": len(remaining_child_hypotheses),
            "child_isolation_relation_rejected_count": child_family_rejected_relations,
            "child_isolation_rejected_count": sum(
                item.startswith("affine-child-isolation:") for item in self._failed_plan_signatures
            ),
            "hierarchy_active": self._active_hierarchy_signature is not None,
            "hierarchy_rejected_count": sum(
                item.startswith(
                    (
                        "affine-hierarchy:",
                        "affine-weighted-hierarchy:",
                        "affine-visible-node-hierarchy:",
                        "affine-bridge-hierarchy:",
                        "affine-residual-linked-hierarchy:",
                        "affine-external-residual-linked-hierarchy:",
                        "affine-raw-matching-composite-hierarchy:",
                        "affine-external-own-composite-hierarchy:",
                        "affine-carrier-source-occlusion-hierarchy:",
                    )
                )
                for item in self._failed_plan_signatures
            ),
            "hierarchy_relation_key": self._active_hierarchy_relation_key,
            "hierarchy_relation_rejected_count": len(
                self._failed_hierarchy_relation_keys
                | self._failed_weighted_hierarchy_relation_keys
                | self._failed_visible_node_hierarchy_relation_keys
                | self._failed_bridge_hierarchy_relation_keys
                | self._failed_residual_linked_hierarchy_relation_keys
                | self._failed_external_residual_linked_hierarchy_relation_keys
                | self._failed_raw_matching_composite_hierarchy_relation_keys
                | self._failed_external_own_composite_hierarchy_relation_keys
                | self._failed_carrier_source_occlusion_hierarchy_relation_keys
            ),
            "hierarchy_hypothesis_rejected_count": (
                len(self._failed_hierarchy_relation_keys)
                + len(self._failed_weighted_hierarchy_relation_keys)
                + len(self._failed_visible_node_hierarchy_relation_keys)
                + len(self._failed_bridge_hierarchy_relation_keys)
                + len(self._failed_residual_linked_hierarchy_relation_keys)
                + len(self._failed_external_residual_linked_hierarchy_relation_keys)
                + len(self._failed_raw_matching_composite_hierarchy_relation_keys)
                + len(self._failed_external_own_composite_hierarchy_relation_keys)
                + len(self._failed_carrier_source_occlusion_hierarchy_relation_keys)
            ),
            "hierarchy_equal_relation_rejected_count": len(self._failed_hierarchy_relation_keys),
            "hierarchy_weighted_relation_rejected_count": len(
                self._failed_weighted_hierarchy_relation_keys
            ),
            "hierarchy_visible_node_relation_rejected_count": len(
                self._failed_visible_node_hierarchy_relation_keys
            ),
            "hierarchy_bridge_relation_rejected_count": len(
                self._failed_bridge_hierarchy_relation_keys
            ),
            "hierarchy_residual_linked_relation_rejected_count": len(
                self._failed_residual_linked_hierarchy_relation_keys
            ),
            "hierarchy_external_residual_linked_relation_rejected_count": len(
                self._failed_external_residual_linked_hierarchy_relation_keys
            ),
            "hierarchy_raw_matching_composite_relation_rejected_count": len(
                self._failed_raw_matching_composite_hierarchy_relation_keys
            ),
            "hierarchy_external_own_composite_relation_rejected_count": len(
                self._failed_external_own_composite_hierarchy_relation_keys
            ),
            "hierarchy_carrier_source_occlusion_relation_rejected_count": len(
                self._failed_carrier_source_occlusion_hierarchy_relation_keys
            ),
            "hierarchy_lineage_failure": current_lineage_failure,
            "hierarchy_lineage_failures": lineage_failures,
            "hierarchy_lineage_lost": self._hierarchy_lineage_lost is not None,
            "hierarchy_lineage_failure_count": len(self._failed_hierarchy_lineages),
            "hierarchy_search_deferred_count": self._hierarchy_search_deferred_count,
            "hierarchy_search_residual": self._last_hierarchy_search_residual,
            "hierarchy_signature": self._active_hierarchy_signature,
            "hierarchy_supports": [list(item) for item in self._active_hierarchy_supports],
            "hierarchy_support_weights": list(self._active_hierarchy_support_weights),
            "hierarchy_carried_source_support_indexes": list(
                self._active_carried_source_recovery_support_indexes
            ),
            "hierarchy_recovery_active": bool(
                self._plan
                and self._plan[0].plan_signature.startswith(
                    (
                        "affine-hierarchy-recovery:",
                        "affine-weighted-hierarchy-recovery:",
                        "affine-visible-node-hierarchy-recovery:",
                        "affine-bridge-hierarchy-recovery:",
                        "affine-residual-linked-hierarchy-recovery:",
                        "affine-external-residual-linked-hierarchy-recovery:",
                        "affine-raw-matching-composite-hierarchy-recovery:",
                        "affine-external-own-composite-hierarchy-recovery:",
                        "affine-carrier-source-occlusion-hierarchy-recovery:",
                    )
                )
            ),
            "hierarchy_recovery_signature": (
                self._plan[0].plan_signature
                if self._plan
                and self._plan[0].plan_signature.startswith(
                    (
                        "affine-hierarchy-recovery:",
                        "affine-weighted-hierarchy-recovery:",
                        "affine-visible-node-hierarchy-recovery:",
                        "affine-bridge-hierarchy-recovery:",
                        "affine-residual-linked-hierarchy-recovery:",
                        "affine-external-residual-linked-hierarchy-recovery:",
                        "affine-raw-matching-composite-hierarchy-recovery:",
                        "affine-external-own-composite-hierarchy-recovery:",
                        "affine-carrier-source-occlusion-hierarchy-recovery:",
                    )
                )
                else None
            ),
            "mechanical_learner": learner.to_dict() if learner is not None else None,
            "mechanical_learner_compact_bytes": (
                len(learner.compact_bytes()) if learner is not None else 0
            ),
            "mechanics": [item.to_dict() for item in self._mechanics[-64:]],
            "marker_bootstrap_attempted": self._marker_bootstrap_attempted,
            "marker_reacquire_after_local_solve": (self._marker_reacquire_after_local_solve),
            "marker_stage_pending_switch": self._marker_stage_pending_switch,
            "marker_structural_action_count": len(self._marker_structural_actions),
            "marker_target_identity_constraint_count": len(
                self._marker_target_identity_constraints
            ),
            "pending_action": (
                {
                    "coordinate": (
                        [self._pending_action.coordinate.x, self._pending_action.coordinate.y]
                        if self._pending_action.coordinate is not None
                        else None
                    ),
                    "name": self._pending_action.name.value,
                }
                if self._pending_action is not None
                else None
            ),
            "pending_prediction_id": (
                self._pending_mechanic_prediction.prediction_id
                if self._pending_mechanic_prediction is not None
                else None
            ),
            "pending_plan_signature": self._pending_plan_signature,
            "pending_plan_actions": len(self._plan),
            "receipt_count": len(self._receipts),
            "receipts": [item.to_dict() for item in self._receipts[-192:]],
            "schema": "arc3.visual-causal-policy.v0.4",
            "transfer_confirmed_levels": transfer_levels,
        }


__all__ = [
    "AffineMechanic",
    "PlannedClick",
    "VisualActionPurpose",
    "VisualActionReceipt",
    "VisualCausalPolicy",
    "VisualObject",
    "VisualObjectRole",
    "VisualScene",
    "extract_visual_scene",
    "infer_affine_mechanic",
    "infer_transferred_affine_mechanic",
    "supports_visual_causal_observation",
]
