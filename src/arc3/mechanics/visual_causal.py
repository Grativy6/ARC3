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

        if not (radius <= x < self.width - radius and radius <= y < self.height - radius):
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
            "level_index": self.level_index,
            "levels_after": self.levels_after,
            "levels_before": self.levels_before,
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
    if 7 <= area <= 24 and center_cell == background:
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
) -> AffineMechanic | None:
    """Apply a previously observed affine form to a new level layout.

    Only the form transfers.  Current endpoints, mediator, arity, and target are
    re-read from the new frame, and the relation must close geometrically before
    it is used.  Raw coordinates and object identities never cross levels.
    """

    active_candidates = tuple(item for item in scene.endpoints if item.color == active_color)
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
    identity = f"transfer|{level_index}|{active_color}|{hub.color}|{arity}|{scene.frame_hash}"
    return AffineMechanic(
        mechanic_ref="affine-transfer:" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:20],
        level_index=level_index,
        active_color=active_color,
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
        self._plan: deque[PlannedClick] = deque()
        self._mechanics: list[AffineMechanic] = []
        self._receipts: list[VisualActionReceipt] = []
        self._failed_plan_signatures: set[str] = set()
        self._attempted_activation_refs: set[str] = set()
        self._last_probe_failed = False
        self._last_active_color: int | None = None
        self._probe_ordinal = 0

    @property
    def mechanics(self) -> tuple[AffineMechanic, ...]:
        return tuple(self._mechanics)

    @property
    def receipts(self) -> tuple[VisualActionReceipt, ...]:
        return tuple(self._receipts)

    def _begin_level(self, observation: Observation) -> None:
        self._level_index = observation.levels_completed
        self._plan.clear()
        self._failed_plan_signatures.clear()
        self._attempted_activation_refs.clear()
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
                )
            )
            actions.append(
                PlannedClick(
                    coordinate=Coordinate(*anchor),
                    purpose=VisualActionPurpose.PROBE,
                    expectation="exchange active and fixed endpoint roles without global reset",
                    mechanic_ref=mechanic.mechanic_ref,
                    plan_id=plan_id,
                )
            )
        actions.append(
            PlannedClick(
                coordinate=points[-1],
                purpose=VisualActionPurpose.PROGRESS,
                expectation="complete the observed affine composition at the matched target",
                mechanic_ref=mechanic.mechanic_ref,
                plan_id=plan_id,
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

        if self._plan:
            planned = self._plan.popleft()
            action = ActionRequest(ActionName.ACTION6, planned.coordinate)
            self._stage_pending(
                observation,
                action,
                purpose=planned.purpose,
                prediction=planned.expectation,
                mechanic_refs=(planned.mechanic_ref,),
            )
            return action

        if ActionName.ACTION6 in observation.available_actions:
            scene = extract_visual_scene(observation.frames[-1])
            if self._last_active_color is not None and not self._last_probe_failed:
                transferred = infer_transferred_affine_mechanic(
                    scene,
                    level_index=observation.levels_completed,
                    active_color=self._last_active_color,
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
    ) -> None:
        if self._pending_action is not None:
            raise PolicyError("a consequence is required before selecting another action")
        self._pending_before = observation
        self._pending_action = action
        self._pending_purpose = purpose
        self._pending_prediction = prediction
        self._pending_mechanic_refs = mechanic_refs

    def accept_consequence(self, observation: Observation) -> None:
        before = self._pending_before
        action = self._pending_action
        if before is None or action is None:
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
        before_scene: VisualScene | None = None
        after_scene: VisualScene | None = None
        if action.name is ActionName.ACTION6 and action.coordinate is not None:
            before_scene = extract_visual_scene(before.frames[-1])
            after_scene = extract_visual_scene(observation.frames[-1])
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
        receipt = VisualActionReceipt(
            receipt_id="visual-receipt:"
            + hashlib.sha256(receipt_seed.encode("utf-8")).hexdigest()[:24],
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
        )
        self._receipts.append(receipt)

        if observation.state is GameStateName.GAME_OVER:
            self._plan.clear()
        elif level_progress:
            self._begin_level(observation)
        elif mechanic is not None and after_scene is not None and not self._pending_mechanic_refs:
            self._plan.clear()
            if not self._install_plan(mechanic, after_scene):
                residual = "no readable target-relative affine plan"
                self._last_probe_failed = True
        elif (
            self._pending_purpose is VisualActionPurpose.PROGRESS
            and not state_change
            and changed <= 2
        ):
            if self._plan:
                failed = self._plan[0].plan_id
                self._failed_plan_signatures.add(failed)
            self._plan.clear()
            self._last_probe_failed = True

        if (
            self._pending_prediction
            == "complete the observed affine composition at the matched target"
            and not level_progress
            and observation.state is GameStateName.NOT_FINISHED
        ):
            self._last_probe_failed = True

        self._previous_observation = observation
        self._pending_before = None
        self._pending_action = None
        self._pending_prediction = "all factored channels UNKNOWN"
        self._pending_mechanic_refs = ()

    def close(self) -> None:
        if self._pending_action is not None:
            raise PolicyError("cannot close with an unresolved submitted action")

    def snapshot(self) -> dict[str, JSONValue]:
        """Return bounded, deterministic campaign evidence."""

        return {
            "active_level_index": self._level_index,
            "failed_plan_count": len(self._failed_plan_signatures),
            "mechanics": [item.to_dict() for item in self._mechanics[-64:]],
            "pending_plan_actions": len(self._plan),
            "receipt_count": len(self._receipts),
            "receipts": [item.to_dict() for item in self._receipts[-192:]],
            "schema": "arc3.visual-causal-policy.v0.1",
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
