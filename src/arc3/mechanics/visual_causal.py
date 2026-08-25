"""Generic visual causal discovery for bounded coordinate-action games.

The policy in this module is deliberately identity-blind.  It discovers compact
objects, tests whether a coordinate action places one of them, estimates a
factored affine consequence, and then uses only target-relative, bounded
candidate points.  It contains no public-game identifiers, fixed layouts, or
walkthrough action sequences.
"""

from __future__ import annotations

import hashlib
import itertools
import math
from collections import Counter, deque
from dataclasses import dataclass
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
    stages_for_switch: bool = False


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
            if len(left_cells) > 12:
                continue
            for right_index in range(left_index + 1, len(working)):
                right_color, right_cells = working[right_index]
                if right_color != left_color or len(right_cells) > 12:
                    continue
                combined = tuple(
                    sorted((*left_cells, *right_cells), key=lambda item: (item[1], item[0]))
                )
                if len(combined) > 24:
                    continue
                xs = [item[0] for item in combined]
                ys = [item[1] for item in combined]
                if max(xs) - min(xs) + 1 > 9 or max(ys) - min(ys) + 1 > 9:
                    continue
                separation = min(
                    max(abs(lx - rx), abs(ly - ry))
                    for lx, ly in left_cells
                    for rx, ry in right_cells
                )
                if separation > 3:
                    continue
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
    targets = tuple(item for item in after.targets if item.color == after_hub.color)
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

    if not supported_prior or any(item.support_error > 6.0 for item in supported_prior):
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
    for active in active_candidates:
        pool = tuple(item for item in scene.endpoints if item.object_ref != active.object_ref)
        for hub in scene.mediators:
            targets = tuple(item for item in scene.targets if item.color == hub.color)
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
    if best is None or best[0] > 1.5:
        return None
    error, arity, hub, anchors, target = best
    source_refs = ",".join(sorted(item.mechanic_ref for item in supported_prior))
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
    arity: int,
    rejected_signatures: set[str],
) -> tuple[Coordinate, ...] | None:
    """Choose a small target-relative equivalence class, never a grid sweep."""

    if not 2 <= arity <= 6:
        return None
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
            if not all(scene.is_open(x, y) for x, y in raw):
                continue
            signature = ";".join(f"{x},{y}" for x, y in raw)
            if signature in rejected_signatures:
                continue
            return tuple(Coordinate(x, y) for x, y in raw)
    return None


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

    groups: list[_EmbeddedMarkerGroup] = []
    for marker_color, endpoints in endpoints_by_marker.items():
        mediators = tuple(item for item in scene.mediators if item.color == marker_color)
        targets = tuple(item for item in scene.targets if item.color == marker_color)
        if not 2 <= len(endpoints) <= 6 or len(mediators) != 1 or len(targets) != 1:
            continue
        groups.append(
            _EmbeddedMarkerGroup(
                marker_color=marker_color,
                endpoints=tuple(sorted(endpoints, key=lambda item: item.object_ref)),
                mediator=mediators[0],
                target=targets[0],
            )
        )
    return tuple(sorted(groups, key=lambda item: item.marker_color))


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


def _marker_relocation_candidates(
    scene: VisualScene,
    group: _EmbeddedMarkerGroup,
    endpoint: VisualObject,
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
    for radius in range(6, 28):
        for rotation_index in range(16):
            rotation = (2 * math.pi * rotation_index) / 16
            raw.add(
                (
                    round(target_x + radius * math.cos(rotation)),
                    round(target_y + radius * math.sin(rotation)),
                )
            )
    return tuple(
        Coordinate(x, y)
        for x, y in sorted(raw, key=lambda item: (item[1], item[0]))
        if _endpoint_placement_is_open(scene, endpoint, x=x, y=y)
        and all(
            item.object_ref == endpoint.object_ref
            or max(
                abs(x - item.rounded_center[0]),
                abs(y - item.rounded_center[1]),
            )
            >= 6
            for item in scene.endpoints
        )
    )


def _endpoint_placement_is_open(
    scene: VisualScene,
    endpoint: VisualObject,
    *,
    x: int,
    y: int,
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
    footprint = {(cell_x - center_x, cell_y - center_y) for cell_x, cell_y in endpoint.cells}
    footprint.add((0, 0))
    return all(
        0 < x + dx < scene.width - 1
        and 0 < y + dy < scene.height - 1
        and (
            scene.cells[y + dy][x + dx] == scene.background or (x + dx, y + dy) in current_footprint
        )
        for dx, dy in footprint
    )


def _chebyshev_distance(left: tuple[int, int], right: tuple[int, int]) -> int:
    return max(abs(left[0] - right[0]), abs(left[1] - right[1]))


def _glyph_radius(item: VisualObject) -> int:
    center_x, center_y = item.rounded_center
    return max(
        center_x - item.min_x,
        item.max_x - center_x,
        center_y - item.min_y,
        item.max_y - center_y,
    )


def _marker_mediator_remains_readable(
    scene: VisualScene,
    group: _EmbeddedMarkerGroup,
    endpoint: VisualObject,
    *,
    coordinate: Coordinate,
    mediator_after: tuple[int, int],
    final: bool,
) -> bool:
    """Preserve component separation for the predicted mediator glyph."""

    mediator_radius = _glyph_radius(group.mediator)
    if not final:
        target_clearance = mediator_radius + _glyph_radius(group.target) + 1
        if _chebyshev_distance(mediator_after, group.target.rounded_center) <= target_clearance:
            return False
    for candidate_endpoint in scene.endpoints:
        endpoint_center = (
            (coordinate.x, coordinate.y)
            if candidate_endpoint.object_ref == endpoint.object_ref
            else candidate_endpoint.rounded_center
        )
        endpoint_clearance = mediator_radius + _glyph_radius(candidate_endpoint) + 1
        if _chebyshev_distance(mediator_after, endpoint_center) <= endpoint_clearance:
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
) -> tuple[VisualScene, _EmbeddedMarkerGroup]:
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
    rows = [list(row) for row in scene.cells]
    for item in (endpoint, group.mediator):
        for cell_x, cell_y in (*item.cells, item.rounded_center):
            rows[cell_y][cell_x] = scene.background
    for item in (endpoint_after, mediator_after):
        for cell_x, cell_y in item.cells:
            rows[cell_y][cell_x] = item.color
        center_x, center_y = item.rounded_center
        rows[center_y][center_x] = item.center_cell
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
    best: tuple[int, int, int, str, Coordinate] | None = None
    for coordinate in _marker_relocation_candidates(scene, group, endpoint):
        resulting_sum_x = sum_x - endpoint.rounded_center[0] + coordinate.x
        resulting_sum_y = sum_y - endpoint.rounded_center[1] + coordinate.y
        stage_potential = _marker_group_potential(
            group,
            sum_x=resulting_sum_x,
            sum_y=resulting_sum_y,
        )
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
        if not _marker_mediator_remains_readable(
            scene,
            group,
            endpoint,
            coordinate=coordinate,
            mediator_after=mediator_after,
            final=False,
        ):
            continue
        projected_scene, projected_group = _scene_after_marker_stage(
            scene,
            group,
            endpoint,
            coordinate,
        )
        projected_endpoint_ref = projected_group.endpoints[
            group.endpoints.index(endpoint)
        ].object_ref
        for switch_endpoint in projected_group.endpoints:
            if switch_endpoint.object_ref == projected_endpoint_ref:
                continue
            followup = _best_marker_relocation(
                projected_scene,
                projected_group,
                switch_endpoint,
                rejected_signatures=rejected_signatures,
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
) -> tuple[int, Coordinate] | None:
    sum_x = sum(item.rounded_center[0] for item in group.endpoints)
    sum_y = sum(item.rounded_center[1] for item in group.endpoints)
    current = _marker_group_potential(group, sum_x=sum_x, sum_y=sum_y)
    best: tuple[int, int, int, Coordinate] | None = None
    for coordinate in _marker_relocation_candidates(scene, group, endpoint):
        resulting_sum_x = sum_x - endpoint.rounded_center[0] + coordinate.x
        resulting_sum_y = sum_y - endpoint.rounded_center[1] + coordinate.y
        potential = _marker_group_potential(
            group,
            sum_x=resulting_sum_x,
            sum_y=resulting_sum_y,
        )
        mediator_after = (
            resulting_sum_x // group.arity,
            resulting_sum_y // group.arity,
        )
        if not _marker_mediator_remains_readable(
            scene,
            group,
            endpoint,
            coordinate=coordinate,
            mediator_after=mediator_after,
            final=potential == 0,
        ):
            continue
        signature_kind = "solve" if potential == 0 else "improve"
        signature = f"marker:{group.marker_color}:{signature_kind}:{coordinate.x},{coordinate.y}"
        if potential >= current or signature in rejected_signatures:
            continue
        candidate = (potential, coordinate.y, coordinate.x, coordinate)
        if best is None or candidate[:3] < best[:3]:
            best = candidate
    return None if best is None else (best[0], best[3])


def _embedded_marker_plan(
    scene: VisualScene,
    *,
    level_index: int,
    active_color: int | None,
    staged_marker_color: int | None,
    rejected_signatures: set[str],
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
    active = _embedded_marker_active_endpoint(scene, active_color=active_color)
    if active is None:
        return None
    unresolved = tuple(
        group for group in groups if group.mediator.rounded_center != group.target.rounded_center
    )
    if not unresolved:
        return None
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
            prospective = _best_marker_relocation(
                scene,
                group,
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
        candidates = tuple(
            item
            for item in group.endpoints
            if (
                f"marker:{group.marker_color}:activate:"
                f"{item.rounded_center[0]},{item.rounded_center[1]}"
            )
            not in rejected_signatures
        )
        if not candidates:
            return None
        selected = min(candidates, key=lambda item: item.object_ref)
        coordinate = Coordinate(*selected.rounded_center)
        signature = f"marker:{group.marker_color}:activate:{coordinate.x},{coordinate.y}"
        return PlannedClick(
            coordinate=coordinate,
            purpose=VisualActionPurpose.PROBE,
            expectation="transfer the active role to a fixed endpoint with the matched marker",
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
    for endpoint in group.endpoints:
        if endpoint.object_ref == active.object_ref:
            continue
        coordinate = Coordinate(*endpoint.rounded_center)
        signature = f"marker:{group.marker_color}:rotate:{coordinate.x},{coordinate.y}"
        if signature in rejected_signatures:
            continue
        prospective = _best_marker_relocation(
            scene,
            group,
            endpoint,
            rejected_signatures=rejected_signatures,
        )
        if prospective is not None:
            switch_candidates.append((prospective[0], endpoint.object_ref, endpoint))
    if not switch_candidates:
        stage = _best_marker_staging_relocation(
            scene,
            group,
            active,
            rejected_signatures=rejected_signatures,
        )
        if stage is None:
            return None
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
) -> bool:
    if action.name is not ActionName.ACTION6 or changed_cells == 0:
        return False
    if inferred_mechanic is not None or level_progress:
        return True
    if action.coordinate is None or not before_scene.endpoints:
        return False
    before_roles = {item.rounded_center: item.color for item in before_scene.endpoints}
    after_roles = {item.rounded_center: item.color for item in after_scene.endpoints}
    clicked = (action.coordinate.x, action.coordinate.y)
    return (
        before_roles.keys() == after_roles.keys()
        and before_roles != after_roles
        and any(_distance(item.rounded_center, clicked) <= 2.25 for item in after_scene.endpoints)
        and {item.rounded_center for item in before_scene.mediators}
        == {item.rounded_center for item in after_scene.mediators}
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
        self._attempted_activation_refs: set[str] = set()
        self._marker_bootstrap_attempted = False
        self._marker_stage_pending_switch: int | None = None
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
        self._attempted_activation_refs.clear()
        self._marker_bootstrap_attempted = False
        self._marker_stage_pending_switch = None
        self._last_probe_failed = False
        self._probe_ordinal = 0

    def _unsolved_pairs(self, scene: VisualScene) -> tuple[tuple[VisualObject, VisualObject], ...]:
        pairs: list[tuple[VisualObject, VisualObject]] = []
        for hub in scene.mediators:
            targets = tuple(item for item in scene.targets if item.color == hub.color)
            if not targets:
                continue
            target = min(
                targets,
                key=lambda item: _distance(
                    (item.center_x, item.center_y), (hub.center_x, hub.center_y)
                ),
            )
            if _distance((hub.center_x, hub.center_y), (target.center_x, target.center_y)) > 2.0:
                pairs.append((hub, target))
        return tuple(sorted(pairs, key=lambda pair: (pair[0].color, pair[0].object_ref)))

    def _probe_coordinate(self, scene: VisualScene) -> Coordinate:
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
        selected = unique[self._probe_ordinal % min(len(unique), self._max_coordinate_candidates)]
        self._probe_ordinal += 1
        return Coordinate(selected[1], selected[2])

    def _activation_coordinate(self, scene: VisualScene) -> Coordinate | None:
        pairs = self._unsolved_pairs(scene)
        if not pairs:
            return None
        hub, _target = pairs[0]
        candidates = sorted(
            (
                item
                for item in scene.endpoints
                if item.object_ref not in self._attempted_activation_refs
                and item.color != self._last_active_color
            ),
            key=lambda item: (
                _distance((item.center_x, item.center_y), (hub.center_x, hub.center_y)),
                item.object_ref,
            ),
        )
        if not candidates:
            return None
        selected = candidates[0]
        self._attempted_activation_refs.add(selected.object_ref)
        x, y = selected.rounded_center
        return Coordinate(x, y)

    def _install_plan(self, mechanic: AffineMechanic, scene: VisualScene) -> bool:
        points = _radial_plan_points(
            scene,
            target=mechanic.target_center,
            arity=mechanic.arity,
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

    def select(self, observation: Observation) -> ActionRequest:
        if observation.state in {GameStateName.GAME_OVER, GameStateName.NOT_PLAYED}:
            action = ActionRequest(ActionName.RESET)
            self._stage_pending(
                observation,
                action,
                purpose=VisualActionPurpose.MANDATORY_RESET,
                prediction="reset lifecycle while retaining game-scoped mechanics",
            )
            return action
        if observation.state is GameStateName.WIN:
            raise PolicyError("the official environment already reports WIN")
        if observation.state is GameStateName.UNKNOWN:
            raise PolicyError("cannot act on an unknown environment state")
        if observation.levels_completed != self._level_index:
            self._begin_level(observation)

        if self._plan and ActionName.ACTION6 not in observation.available_actions:
            self._failed_plan_signatures.add(self._plan[0].plan_signature)
            self._plan.clear()
            self._last_probe_failed = True
        if ActionName.ACTION6 in observation.available_actions:
            marker_scene = extract_visual_scene(observation.frames[-1])
            marker_groups = _embedded_marker_groups(marker_scene)
            marker_plan = _embedded_marker_plan(
                marker_scene,
                level_index=observation.levels_completed,
                active_color=self._last_active_color,
                staged_marker_color=self._marker_stage_pending_switch,
                rejected_signatures=self._failed_plan_signatures,
            )
            if marker_plan is not None:
                # Marker plans contain exactly one locally justified action and
                # are recomputed from the returned frame.  A queued radial
                # hypothesis for this level must not override stronger visible
                # grouping evidence.
                self._plan.clear()
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
                    coordinate = self._probe_coordinate(marker_scene)
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
                    self._marker_bootstrap_attempted = True
                    return action
                raise PolicyError(
                    "embedded marker group is unresolved but has no bounded same-group action"
                )
        if self._plan:
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

        if ActionName.ACTION6 in observation.available_actions:
            scene = extract_visual_scene(observation.frames[-1])
            learner = self._ensure_learner(observation)
            transferable = self._affine_ledger_ref is not None and learner.ledger.get(
                self._affine_ledger_ref
            ).status in {MechanicStatus.SUPPORTED, MechanicStatus.STABLE_WITHIN_SCOPE}
            if self._last_active_color is not None and not self._last_probe_failed and transferable:
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
            activation = self._activation_coordinate(scene) if self._last_probe_failed else None
            if activation is not None:
                action = ActionRequest(ActionName.ACTION6, activation)
                self._last_probe_failed = False
                self._stage_pending(
                    observation,
                    action,
                    purpose=VisualActionPurpose.PROBE,
                    prediction="test whether a nearby endpoint transfers the active intervention role",
                )
                return action
            coordinate = self._probe_coordinate(scene)
            action = ActionRequest(ActionName.ACTION6, coordinate)
            self._stage_pending(
                observation,
                action,
                purpose=VisualActionPurpose.PROBE,
                prediction="test coordinate placement and localized affine mediator response",
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
        self._pending_clef_prediction = _predicted_clef_effects(
            purpose=purpose,
            mechanic_refs=mechanic_refs,
            action=action,
        )
        self._pending_mechanic_prediction = mechanic_prediction

    def accept_consequence(self, observation: Observation) -> None:
        before = self._pending_before
        action = self._pending_action
        mechanic_prediction = self._pending_mechanic_prediction
        learner = self._mechanical_learner
        if before is None or action is None or mechanic_prediction is None or learner is None:
            raise PolicyError("mechanical policy received a consequence without a pending action")
        changed = _changed_cells(before.frames[-1], observation.frames[-1])
        level_progress = observation.levels_completed > before.levels_completed
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
        mechanic: AffineMechanic | None = None
        before_scene = extract_visual_scene(before.frames[-1])
        after_scene = extract_visual_scene(observation.frames[-1])
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
        local_target_satisfied = self._pending_completes_local_target and (
            _local_target_satisfied(
                after_scene,
                target_center=self._pending_target_center,
                mediator_color=self._pending_mediator_color,
                arity=self._pending_arity,
            )
        )
        coordinate_transform = local_target_satisfied or _coordinate_transform_observed(
            before_scene,
            after_scene,
            action=action,
            changed_cells=changed,
            level_progress=level_progress,
            inferred_mechanic=mechanic,
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
        if mechanic is not None or local_target_satisfied:
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
                note="coordinate action transformed a readable endpoint system and its mediator",
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
            and any(
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
        marker_bootstrap = (
            self._pending_plan_signature is not None
            and self._pending_plan_signature.startswith("marker-bootstrap:")
        )
        if observation.state is GameStateName.GAME_OVER:
            if self._pending_plan_signature is not None:
                self._failed_plan_signatures.add(self._pending_plan_signature)
            self._plan.clear()
            self._marker_stage_pending_switch = None
            self._last_probe_failed = True
        elif observation.state is GameStateName.WIN:
            self._plan.clear()
            self._marker_stage_pending_switch = None
            self._last_probe_failed = False
        elif level_progress:
            self._begin_level(observation)
        elif marker_bootstrap:
            self._plan.clear()
            if mechanic is None:
                if self._pending_plan_signature is not None:
                    self._failed_plan_signatures.add(self._pending_plan_signature)
                self._last_probe_failed = True
            else:
                self._last_probe_failed = False
        elif mechanic is not None and not self._pending_mechanic_refs:
            self._plan.clear()
            if not self._install_plan(mechanic, after_scene):
                residual = "no readable target-relative affine plan"
                self._last_probe_failed = True
        elif local_target_satisfied:
            self._plan.clear()
            self._last_probe_failed = False
        elif plan_prediction_failed or self._pending_completes_local_target:
            if self._pending_plan_signature is not None:
                self._failed_plan_signatures.add(self._pending_plan_signature)
            self._plan.clear()
            self._marker_stage_pending_switch = None
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

        self._previous_observation = observation
        self._pending_before = None
        self._pending_action = None
        self._pending_prediction = "all factored channels UNKNOWN"
        self._pending_mechanic_refs = ()
        self._pending_plan_signature = None
        self._pending_target_center = None
        self._pending_mediator_color = None
        self._pending_arity = None
        self._pending_completes_local_target = False
        self._pending_clef_prediction = EffectVector.unknown()
        self._pending_mechanic_prediction = None
        self._step_index += 1

    def close(self) -> None:
        if self._pending_action is not None:
            raise PolicyError("cannot close with an unresolved submitted action")

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
        return {
            "active_level_index": self._level_index,
            "affine_ledger_ref": (
                self._affine_ledger_ref.to_dict() if self._affine_ledger_ref is not None else None
            ),
            "failed_plan_count": len(self._failed_plan_signatures),
            "mechanical_learner": learner.to_dict() if learner is not None else None,
            "mechanical_learner_compact_bytes": (
                len(learner.compact_bytes()) if learner is not None else 0
            ),
            "mechanics": [item.to_dict() for item in self._mechanics[-64:]],
            "marker_bootstrap_attempted": self._marker_bootstrap_attempted,
            "marker_stage_pending_switch": self._marker_stage_pending_switch,
            "pending_plan_actions": len(self._plan),
            "receipt_count": len(self._receipts),
            "receipts": [item.to_dict() for item in self._receipts[-192:]],
            "schema": "arc3.visual-causal-policy.v0.2",
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
]
