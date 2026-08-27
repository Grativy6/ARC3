from __future__ import annotations

import base64
import hashlib
import math
import zlib
from dataclasses import dataclass, field, replace
from functools import lru_cache

import pytest

import arc3.mechanics.visual_causal as visual_causal
from arc3.adapters import GridFrame, Observation
from arc3.errors import PolicyError
from arc3.evaluation.mechanical_replay import _family_state
from arc3.exploration.causal_events import RiskLevel
from arc3.mechanics.visual_causal import (
    VisualActionPurpose,
    VisualCausalPolicy,
    VisualObjectRole,
    VisualScene,
    _embedded_marker_groups,
    _endpoint_placement_is_open,
    _marker_mediator_remains_readable,
    _radial_plan_points,
    extract_visual_scene,
    infer_affine_mechanic,
    infer_transferred_affine_mechanic,
)
from arc3.types import ActionName, ActionRequest, Coordinate, GameId, GameStateName

_ENDPOINT_SHAPE = (
    (0, -2),
    (-1, -1),
    (0, -1),
    (1, -1),
    (-2, 0),
    (-1, 0),
    (0, 0),
    (1, 0),
    (2, 0),
    (-1, 1),
    (0, 1),
    (1, 1),
    (0, 2),
)
_HUB_OUTER = tuple(
    (dx, dy)
    for dy in range(-2, 3)
    for dx in range(-2, 3)
    if (abs(dx), abs(dy)) != (2, 2) and (dx, dy) != (0, 0)
)
_TARGET_RING = tuple(
    (dx, dy)
    for dx, dy in (
        (-1, -2),
        (0, -2),
        (1, -2),
        (-2, -1),
        (2, -1),
        (-2, 0),
        (2, 0),
        (-2, 1),
        (2, 1),
        (-1, 2),
        (0, 2),
        (1, 2),
    )
)
_SPARSE_TARGET_RING = (
    (-1, -3),
    (0, -3),
    (1, -3),
    (-3, -1),
    (3, -1),
    (-3, 0),
    (3, 0),
    (-3, 1),
    (3, 1),
    (-1, 3),
    (0, 3),
    (1, 3),
)

_OFFSET_SPARSE_TARGET_RING = (
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
)

_TARGET_LAYER_OVERLAY = (
    (-2, -4),
    (-3, -3),
    (-2, -3),
    (-3, -2),
    (-1, -2),
    (-3, -1),
    (0, -1),
    (1, 0),
    (-2, 1),
    (1, 1),
    (-2, 2),
    (-2, 3),
    (3, 3),
    (4, 4),
)


def _paint(
    rows: list[list[int]],
    center: tuple[int, int],
    shape: tuple[tuple[int, int], ...],
    color: int,
) -> None:
    for dx, dy in shape:
        rows[center[1] + dy][center[0] + dx] = color


def _frame(
    active: tuple[int, int],
    anchor: tuple[int, int],
    target: tuple[int, int],
) -> GridFrame:
    rows = [[5 for _ in range(40)] for _ in range(40)]
    hub = (round((active[0] + anchor[0]) / 2), round((active[1] + anchor[1]) / 2))
    _paint(rows, target, _TARGET_RING, 15)
    _paint(rows, active, _ENDPOINT_SHAPE, 0)
    _paint(rows, anchor, _ENDPOINT_SHAPE, 3)
    _paint(rows, hub, _HUB_OUTER, 15)
    rows[hub[1]][hub[0]] = 6
    return GridFrame.from_rows(rows)


def _palette_mismatched_target_frame(
    active: tuple[int, int],
    anchor: tuple[int, int],
    targets: tuple[tuple[tuple[int, int], int], ...],
) -> GridFrame:
    rows = [[5 for _ in range(64)] for _ in range(64)]
    hub = (round((active[0] + anchor[0]) / 2), round((active[1] + anchor[1]) / 2))
    for target, color in targets:
        _paint(rows, target, _TARGET_RING, color)
    _paint(rows, active, _ENDPOINT_SHAPE, 0)
    _paint(rows, anchor, _ENDPOINT_SHAPE, 3)
    _paint(rows, hub, _HUB_OUTER, 0)
    rows[hub[1]][hub[0]] = 6
    return GridFrame.from_rows(rows)


def _ordinary_two_group_frame(
    *,
    active: tuple[int, int],
    first_hub: tuple[int, int],
    fixed_endpoints: tuple[tuple[int, int], ...] = (
        (60, 28),
        (52, 55),
        (34, 55),
        (41, 47),
    ),
) -> GridFrame:
    rows = [[5 for _ in range(64)] for _ in range(64)]
    _paint(rows, (53, 28), _OFFSET_SPARSE_TARGET_RING, 14)
    for endpoint in fixed_endpoints:
        _paint(rows, endpoint, _ENDPOINT_SHAPE, 3)
        rows[endpoint[1]][endpoint[0]] = 4
    _paint(rows, active, _ENDPOINT_SHAPE, 0)
    rows[active[1]][active[0]] = 4
    for hub in (first_hub, (42, 52)):
        _paint(rows, hub, _HUB_OUTER, 0)
        rows[hub[1]][hub[0]] = 0
    return GridFrame.from_rows(rows)


def _ambiguous_mismatched_target_frame() -> GridFrame:
    rows = [[5 for _ in range(64)] for _ in range(64)]
    _paint(rows, (32, 12), _TARGET_RING, 14)
    _paint(rows, (32, 48), _ENDPOINT_SHAPE, 0)
    _paint(rows, (16, 48), _ENDPOINT_SHAPE, 3)
    _paint(rows, (48, 48), _ENDPOINT_SHAPE, 3)
    for hub in ((24, 48), (40, 48)):
        _paint(rows, hub, _HUB_OUTER, 0)
        rows[hub[1]][hub[0]] = 6
    return GridFrame.from_rows(rows)


def _observation(
    active: tuple[int, int],
    anchor: tuple[int, int],
    target: tuple[int, int],
    *,
    levels_completed: int = 0,
    state: GameStateName = GameStateName.NOT_FINISHED,
    returned_action: ActionRequest | None = None,
    available_actions: tuple[ActionName, ...] = (ActionName.ACTION6,),
    full_reset: bool = False,
) -> Observation:
    return Observation(
        game_id=GameId("synthetic-visual-mechanics"),
        frames=(_frame(active, anchor, target),),
        state=state,
        levels_completed=levels_completed,
        win_levels=2,
        available_actions=available_actions,
        full_reset=full_reset,
        returned_action=returned_action,
    )


def _three_endpoint_frame() -> GridFrame:
    rows = [[5 for _ in range(40)] for _ in range(40)]
    active = (8, 8)
    anchors = ((28, 8), (18, 26))
    hub = (
        round((active[0] + sum(item[0] for item in anchors)) / 3),
        round((active[1] + sum(item[1] for item in anchors)) / 3),
    )
    _paint(rows, (25, 29), _TARGET_RING, 12)
    _paint(rows, active, _ENDPOINT_SHAPE, 0)
    for anchor in anchors:
        _paint(rows, anchor, _ENDPOINT_SHAPE, 3)
    _paint(rows, hub, _HUB_OUTER, 12)
    rows[hub[1]][hub[0]] = 6
    return GridFrame.from_rows(rows)


def _marker_frame(
    groups: tuple[tuple[tuple[int, int], ...], ...],
    targets: tuple[tuple[int, int], ...],
    marker_colors: tuple[int, ...],
    *,
    active_group: int,
    active_index: int,
    background: int,
    active_color: int,
    fixed_color: int,
) -> GridFrame:
    rows = [[background for _ in range(64)] for _ in range(64)]
    center_fill = next(
        color
        for color in range(16)
        if color not in {background, active_color, fixed_color, *marker_colors}
    )
    for group_index, (endpoints, target, marker_color) in enumerate(
        zip(groups, targets, marker_colors, strict=True)
    ):
        _paint(rows, target, _TARGET_RING, marker_color)
        for endpoint_index, endpoint in enumerate(endpoints):
            outer_color = (
                active_color
                if (group_index, endpoint_index) == (active_group, active_index)
                else fixed_color
            )
            _paint(rows, endpoint, _ENDPOINT_SHAPE, outer_color)
            rows[endpoint[1]][endpoint[0]] = marker_color
        mediator = (
            math.floor(sum(x for x, _y in endpoints) / len(endpoints)),
            math.floor(sum(y for _x, y in endpoints) / len(endpoints)),
        )
        _paint(rows, mediator, _HUB_OUTER, marker_color)
        rows[mediator[1]][mediator[0]] = center_fill
    return GridFrame.from_rows(rows)


def _composite_marker_frame() -> GridFrame:
    rows = [[5 for _ in range(64)] for _ in range(64)]
    groups = {
        12: (((8, 8), (28, 8), (18, 24)), (45, 58)),
        14: (((6, 38), (10, 56), (32, 56)), (50, 10)),
        9: (((50, 34), (50, 50)), (38, 58)),
    }

    def sector_color(marker: int, dx: int, dy: int) -> int:
        if marker == 12:
            return 12 if dx < 0 else 7
        if marker == 14:
            return 14 if dx < 0 else 11
        return 9 if dx < 0 else 8

    for marker, (endpoints, target) in groups.items():
        for endpoint_index, endpoint in enumerate(endpoints):
            _paint(
                rows, endpoint, _ENDPOINT_SHAPE, 0 if marker == 12 and endpoint_index == 0 else 3
            )
            rows[endpoint[1]][endpoint[0]] = marker
        mediator = (
            sum(x for x, _y in endpoints) // len(endpoints),
            sum(y for _x, y in endpoints) // len(endpoints),
        )
        for dx, dy in _HUB_OUTER:
            rows[mediator[1] + dy][mediator[0] + dx] = sector_color(marker, dx, dy)
        rows[mediator[1]][mediator[0]] = 6
        for dx, dy in _OFFSET_SPARSE_TARGET_RING:
            rows[target[1] + dy][target[0] + dx] = sector_color(marker, dx, dy)

    for y in range(22, 39):
        for x in range(25, 43):
            rows[y][x] = 10
    _paint(rows, (54, 46), _OFFSET_SPARSE_TARGET_RING, 13)
    return GridFrame.from_rows(rows)


def _sparse_target_overlay_frame(
    *,
    target_center: tuple[int, int] = (30, 30),
    target_overlay: int = 1,
) -> GridFrame:
    groups = (((10, 50), (30, 50), (50, 30)),)
    frame = _marker_frame(
        groups,
        (target_center,),
        (12,),
        active_group=0,
        active_index=0,
        background=5,
        active_color=0,
        fixed_color=3,
    )
    rows = [list(row) for row in frame.cells]
    for dx, dy in _TARGET_RING:
        rows[target_center[1] + dy][target_center[0] + dx] = 5
    _paint(rows, target_center, _SPARSE_TARGET_RING, 12)
    rows[target_center[1]][target_center[0]] = target_overlay
    return GridFrame.from_rows(rows)


def _contaminated_marker_target_frame(*, active_index: int) -> GridFrame:
    target = (44, 44)
    endpoints = ((39, 22), (48, 40), (22, 22), (48, 58))
    rows = [[5 for _ in range(64)] for _ in range(64)]
    _paint(rows, target, _OFFSET_SPARSE_TARGET_RING, 12)
    for index, endpoint in enumerate(endpoints):
        _paint(rows, endpoint, _ENDPOINT_SHAPE, 0 if index == active_index else 3)
        rows[endpoint[1]][endpoint[0]] = 12
    mediator = (
        sum(x for x, _y in endpoints) // len(endpoints),
        sum(y for _x, y in endpoints) // len(endpoints),
    )
    _paint(rows, mediator, _HUB_OUTER, 12)
    rows[mediator[1]][mediator[0]] = 6
    return GridFrame.from_rows(rows)


def _compound_target_overlay_contamination_frame(
    *,
    active_index: int | None,
) -> GridFrame:
    """Render one endpoint center joined only to its compound-target color sector."""

    target = (40, 12)
    endpoints = ((34, 12), (52, 32), (21, 52))
    rows = [[5 for _ in range(64)] for _ in range(64)]
    for dx, dy in _OFFSET_SPARSE_TARGET_RING:
        rows[target[1] + dy][target[0] + dx] = 14 if dx < 0 else 11
    for index, endpoint in enumerate(endpoints):
        outer_color = 0 if index == active_index else 3
        _paint(rows, endpoint, _ENDPOINT_SHAPE, outer_color)
        rows[endpoint[1]][endpoint[0]] = 14
    mediator = (
        sum(x for x, _y in endpoints) // len(endpoints),
        sum(y for _x, y in endpoints) // len(endpoints),
    )
    for dx, dy in _HUB_OUTER:
        rows[mediator[1] + dy][mediator[0] + dx] = 14 if dx < 0 else 11
    rows[mediator[1]][mediator[0]] = 6
    return GridFrame.from_rows(rows)


@dataclass
class _MarkerAffineEnvironment:
    groups: list[list[tuple[int, int]]]
    targets: tuple[tuple[int, int], ...]
    marker_colors: tuple[int, ...]
    active_group: int = 0
    active_index: int = 0
    background: int = 5
    active_color: int = 0
    fixed_color: int = 3
    levels_completed: int = 0
    action_kinds: list[str] = field(default_factory=list)

    def observation(self, returned_action: ActionRequest | None = None) -> Observation:
        frame = _marker_frame(
            tuple(tuple(group) for group in self.groups),
            self.targets,
            self.marker_colors,
            active_group=self.active_group,
            active_index=self.active_index,
            background=self.background,
            active_color=self.active_color,
            fixed_color=self.fixed_color,
        )
        return Observation(
            game_id=GameId("synthetic-marker-affine"),
            frames=(frame,),
            state=GameStateName.NOT_FINISHED,
            levels_completed=self.levels_completed,
            win_levels=2,
            available_actions=(ActionName.ACTION6,),
            returned_action=returned_action,
        )

    def direct_solution(self) -> tuple[int, int]:
        endpoints = self.groups[self.active_group]
        target_x, target_y = self.targets[self.active_group]
        others = tuple(
            endpoint for index, endpoint in enumerate(endpoints) if index != self.active_index
        )
        return (
            len(endpoints) * target_x - sum(x for x, _y in others),
            len(endpoints) * target_y - sum(y for _x, y in others),
        )

    def step(self, action: ActionRequest) -> Observation:
        assert action.coordinate is not None
        clicked = (action.coordinate.x, action.coordinate.y)
        selected_endpoint: tuple[int, int] | None = None
        for group_index, endpoints in enumerate(self.groups):
            for endpoint_index, endpoint in enumerate(endpoints):
                if math.dist(clicked, endpoint) <= 2.25:
                    selected_endpoint = (group_index, endpoint_index)
                    break
            if selected_endpoint is not None:
                break
        if selected_endpoint is not None and selected_endpoint != (
            self.active_group,
            self.active_index,
        ):
            self.active_group, self.active_index = selected_endpoint
            self.action_kinds.append("switch")
        else:
            self.groups[self.active_group][self.active_index] = clicked
            self.action_kinds.append("move")

        solved = 0
        for endpoints, target in zip(self.groups, self.targets, strict=True):
            mediator = (
                math.floor(sum(x for x, _y in endpoints) / len(endpoints)),
                math.floor(sum(y for _x, y in endpoints) / len(endpoints)),
            )
            solved += mediator == target
        if solved == len(self.groups):
            self.levels_completed = 1
        return self.observation(returned_action=action)


def test_scene_roles_are_descriptive_and_identity_blind() -> None:
    scene = extract_visual_scene(_frame((8, 32), (32, 32), (20, 10)))

    assert len(scene.endpoints) == 2
    assert {item.color for item in scene.endpoints} == {0, 3}
    assert len(scene.mediators) == 1
    assert scene.mediators[0].role is VisualObjectRole.MEDIATOR_CANDIDATE
    assert len(scene.targets) == 1
    assert scene.targets[0].role is VisualObjectRole.HOLLOW_TARGET_CANDIDATE


def test_sparse_target_ring_survives_nonbackground_center_overlay() -> None:
    frame = _sparse_target_overlay_frame()
    scene = extract_visual_scene(frame)

    assert len(scene.targets) == 1
    assert scene.targets[0].rounded_center == (30, 30)
    assert scene.targets[0].area == 12
    assert (scene.targets[0].width, scene.targets[0].height) == (7, 7)
    assert scene.targets[0].center_cell == 1
    assert len(scene.endpoints) == 3
    assert len(scene.mediators) == 1
    assert len(_embedded_marker_groups(scene)) == 1

    observation = Observation(
        game_id=GameId("synthetic-sparse-overlay"),
        frames=(frame,),
        state=GameStateName.NOT_FINISHED,
        levels_completed=0,
        win_levels=1,
        available_actions=(ActionName.ACTION6,),
    )
    policy = VisualCausalPolicy()

    action = policy.select(observation)

    assert action.coordinate == Coordinate(10, 10)
    assert "marker-group affine solution" in policy._pending_prediction


def test_multicolor_marker_compounds_retain_affine_groups_and_blocker_gate() -> None:
    scene = extract_visual_scene(_composite_marker_frame())

    groups = {group.marker_color: group for group in _embedded_marker_groups(scene)}

    assert set(groups) == {9, 12, 14}
    assert groups[12].mediator.rounded_center == (18, 13)
    assert groups[12].target.rounded_center == (45, 58)
    assert groups[14].mediator.rounded_center == (16, 50)
    assert groups[14].target.rounded_center == (50, 10)
    assert groups[9].mediator.rounded_center == (50, 42)
    assert groups[9].target.rounded_center == (38, 58)

    plan = visual_causal._embedded_marker_plan(
        scene,
        level_index=3,
        active_color=0,
        staged_marker_color=None,
        rejected_signatures=set(),
    )

    assert plan is not None
    assert plan.plan_signature.startswith("marker:12:")
    resulting_mediator = (
        (28 + 18 + plan.coordinate.x) // 3,
        (8 + 24 + plan.coordinate.y) // 3,
    )
    assert visual_causal._marker_mediator_avoids_static_components(
        scene,
        groups[12],
        mediator_after=resulting_mediator,
    )
    assert not visual_causal._marker_mediator_avoids_static_components(
        scene,
        groups[12],
        mediator_after=(32, 28),
    )
    active = visual_causal._embedded_marker_active_endpoint(scene, active_color=0)
    assert active is not None
    assert not visual_causal._marker_mediator_remains_readable(
        scene,
        groups[12],
        active,
        coordinate=Coordinate(40, 20),
        mediator_after=groups[9].mediator.rounded_center,
        final=False,
    )
    assert not visual_causal._marker_mediator_remains_readable(
        scene,
        groups[12],
        active,
        coordinate=Coordinate(60, 3),
        mediator_after=(35, 11),
        final=False,
    )
    projection = visual_causal._scene_after_marker_stage(
        scene,
        groups[12],
        active,
        plan.coordinate,
    )
    assert projection is not None
    projected_scene, _projected_group = projection
    reparsed = {group.marker_color: group for group in _embedded_marker_groups(projected_scene)}
    assert reparsed[12].target.rounded_center == (45, 58)
    assert visual_causal._compound_outer_signature(
        projected_scene,
        cells=reparsed[12].mediator.cells,
        center=reparsed[12].mediator.rounded_center,
    ) == frozenset({7, 12})
    candidates = visual_causal._marker_relocation_candidates(
        scene,
        groups[12],
        active,
    )
    other_target_box = frozenset((x, y) for y in range(55, 62) for x in range(35, 42))
    assert Coordinate(41, 54) not in candidates
    assert all(
        not (
            visual_causal._translated_object_footprint(
                active,
                center=(candidate.x, candidate.y),
            )
            & other_target_box
        )
        for candidate in candidates
    )


def test_same_group_centerline_alias_is_not_independent_target_evidence() -> None:
    scene = extract_visual_scene(_composite_marker_frame())
    group = next(item for item in _embedded_marker_groups(scene) if item.marker_color == 14)
    footprint = visual_causal._marker_dynamic_footprint(group)
    alias_cells = tuple(sorted(footprint, key=lambda cell: (cell[1], cell[0]))[:11])
    xs = tuple(x for x, _y in alias_cells)
    ys = tuple(y for _x, y in alias_cells)
    template = next(item for item in scene.targets if item.color == 13)
    alias = replace(
        template,
        object_ref="visual:test-same-group-target-alias",
        color=1,
        cells=alias_cells,
        min_x=min(xs),
        min_y=min(ys),
        max_x=max(xs),
        max_y=max(ys),
        center_x=(min(xs) + max(xs)) / 2,
        center_y=(min(ys) + max(ys)) / 2,
    )
    aliased_scene = replace(scene, objects=(*scene.objects, alias))
    alias_region = (
        alias.rounded_center,
        frozenset(
            (x, y)
            for y in range(alias.min_y, alias.max_y + 1)
            for x in range(alias.min_x, alias.max_x + 1)
        ),
    )

    filtered = visual_causal._visible_target_regions(
        aliased_scene,
        same_group_raster_cells=footprint,
    )
    partially_explained = visual_causal._visible_target_regions(
        aliased_scene,
        same_group_raster_cells=footprint - {alias_cells[0]},
    )

    assert alias_region not in filtered
    assert alias_region in partially_explained


def test_same_group_alias_filter_never_removes_composite_target_proxy() -> None:
    scene = extract_visual_scene(_composite_marker_frame())
    group = next(item for item in _embedded_marker_groups(scene) if item.marker_color == 14)

    protected = visual_causal._visible_target_regions(
        scene,
        same_group_raster_cells=frozenset(group.target.cells),
    )

    assert any(center == group.target.rounded_center for center, _region in protected)


def test_same_group_alias_filter_preserves_other_complete_group_raw_target() -> None:
    scene = extract_visual_scene(
        _marker_frame(
            (
                ((10, 50), (30, 50)),
                ((42, 42), (54, 42)),
            ),
            ((20, 28), (48, 20)),
            (12, 14),
            active_group=0,
            active_index=0,
            background=5,
            active_color=0,
            fixed_color=3,
        )
    )
    groups = {group.marker_color: group for group in _embedded_marker_groups(scene)}
    other_target = groups[14].target

    protected = visual_causal._visible_target_regions(
        scene,
        same_group_raster_cells=frozenset(other_target.cells),
    )

    assert any(center == other_target.rounded_center for center, _region in protected)


def test_compound_group_uses_exact_raw_signature_only_when_filtered_match_is_lost() -> None:
    frame = _composite_marker_frame()
    rows = [list(row) for row in frame.cells]
    # Extend the right-hand color-7 sector of marker 12 one cell beyond the
    # exact 21-cell disk.  The primary connector filter must omit that extended
    # component, while the complete local disk still exactly matches one ring.
    rows[13][21] = 7
    scene = extract_visual_scene(GridFrame.from_rows(rows))

    groups = {group.marker_color: group for group in _embedded_marker_groups(scene)}

    assert 12 in groups
    assert groups[12].mediator.rounded_center == (18, 13)
    assert groups[12].target.rounded_center == (45, 58)
    assert visual_causal._compound_outer_signature(
        scene,
        cells=groups[12].mediator.cells,
        center=groups[12].mediator.rounded_center,
    ) == frozenset({12})
    assert visual_causal._compound_raw_outer_signature(
        scene,
        cells=groups[12].mediator.cells,
        center=groups[12].mediator.rounded_center,
    ) == frozenset({7, 12})


def test_marker_relocation_checks_the_observed_endpoint_footprint() -> None:
    frame = _marker_frame(
        (((8, 48), (48, 8)),),
        ((18, 38),),
        (12,),
        active_group=0,
        active_index=0,
        background=5,
        active_color=0,
        fixed_color=3,
    )
    rows = [list(row) for row in frame.cells]
    for x, y in (
        (39, 3),
        (46, 59),
        (55, 5),
        (59, 5),
        (55, 9),
        (59, 9),
    ):
        rows[y][x] = 9
    scene = extract_visual_scene(GridFrame.from_rows(rows))
    endpoint = next(item for item in scene.endpoints if item.color == 0)

    assert not _endpoint_placement_is_open(scene, endpoint, x=39, y=5)
    assert not _endpoint_placement_is_open(scene, endpoint, x=48, y=59)
    assert _endpoint_placement_is_open(scene, endpoint, x=57, y=7)
    assert _endpoint_placement_is_open(scene, endpoint, x=9, y=48)


def test_marker_relocation_preserves_outer_component_separation() -> None:
    frame = _marker_frame(
        (((8, 48), (48, 8)),),
        ((18, 38),),
        (12,),
        active_group=0,
        active_index=0,
        background=5,
        active_color=0,
        fixed_color=3,
    )
    rows = [list(row) for row in frame.cells]
    for x in range(23, 30):
        rows[20][x] = 0
    scene = extract_visual_scene(GridFrame.from_rows(rows))
    endpoint = next(item for item in scene.endpoints if item.color == 0)

    assert not _endpoint_placement_is_open(scene, endpoint, x=20, y=20)
    assert _endpoint_placement_is_open(scene, endpoint, x=20, y=30)


def test_nonfinal_mediator_rejects_observed_target_component_adjacency() -> None:
    scene = extract_visual_scene(_sparse_target_overlay_frame())
    group = _embedded_marker_groups(scene)[0]
    endpoint = next(item for item in group.endpoints if item.color == 0)

    assert not _marker_mediator_remains_readable(
        scene,
        group,
        endpoint,
        coordinate=Coordinate(10, 28),
        mediator_after=(30, 36),
        final=False,
    )
    assert _marker_mediator_remains_readable(
        scene,
        group,
        endpoint,
        coordinate=Coordinate(10, 31),
        mediator_after=(30, 37),
        final=False,
    )


def test_nonfinal_mediator_uses_sparse_target_footprint_not_bounding_radius() -> None:
    scene = extract_visual_scene(_sparse_target_overlay_frame())
    group = _embedded_marker_groups(scene)[0]
    endpoint = next(item for item in group.endpoints if item.color == 0)

    assert _marker_mediator_remains_readable(
        scene,
        group,
        endpoint,
        coordinate=Coordinate(10, 31),
        mediator_after=(25, 25),
        final=False,
    )


def test_predicted_mediator_permits_endpoint_tangent_but_rejects_overlap() -> None:
    scene = extract_visual_scene(
        _marker_frame(
            (
                ((10, 50), (30, 50), (50, 30)),
                ((40, 35), (55, 20)),
            ),
            ((20, 10), (50, 10)),
            (12, 14),
            active_group=0,
            active_index=0,
            background=5,
            active_color=0,
            fixed_color=3,
        )
    )
    group = next(item for item in _embedded_marker_groups(scene) if item.marker_color == 12)
    other_group = next(item for item in _embedded_marker_groups(scene) if item.marker_color == 14)
    endpoint = next(item for item in group.endpoints if item.color == 0)
    nearby_ordinary_mediator = visual_causal._translated_visual_object(
        other_group.mediator,
        center=(36, 35),
        width=scene.width,
        height=scene.height,
    )

    assert _marker_mediator_remains_readable(
        scene,
        group,
        endpoint,
        coordinate=Coordinate(25, 25),
        mediator_after=(35, 35),
        final=False,
        other_mediators=(nearby_ordinary_mediator,),
    )
    assert not _marker_mediator_remains_readable(
        scene,
        group,
        endpoint,
        coordinate=Coordinate(25, 25),
        mediator_after=(36, 35),
        final=False,
    )


def test_unmatched_hollow_overlay_does_not_block_matched_marker_planning() -> None:
    frame = _marker_frame(
        (((10, 50), (30, 50)),),
        ((20, 10),),
        (12,),
        active_group=0,
        active_index=0,
        background=5,
        active_color=0,
        fixed_color=3,
    )
    rows = [list(row) for row in frame.cells]
    _paint(rows, (40, 30), _TARGET_RING, 9)
    scene = extract_visual_scene(GridFrame.from_rows(rows))
    group = _embedded_marker_groups(scene)[0]
    endpoint = next(item for item in group.endpoints if item.color == 0)

    assert _marker_mediator_remains_readable(
        scene,
        group,
        endpoint,
        coordinate=Coordinate(50, 10),
        mediator_after=(40, 30),
        final=False,
    )
    assert Coordinate(37, 27) in visual_causal._marker_relocation_candidates(
        scene,
        group,
        endpoint,
    )


def test_predicted_mediator_rejects_large_static_component_by_relative_area() -> None:
    frame = _marker_frame(
        (((10, 50), (30, 50)),),
        ((40, 10),),
        (12,),
        active_group=0,
        active_index=0,
        background=5,
        active_color=0,
        fixed_color=3,
    )
    rows = [list(row) for row in frame.cells]
    for y in range(25, 36):
        for x in range(21, 30):
            rows[y][x] = 10
    for y in range(37, 45):
        for x in range(48, 56):
            rows[y][x] = 10
    scene = extract_visual_scene(GridFrame.from_rows(rows))
    group = _embedded_marker_groups(scene)[0]

    assert not visual_causal._marker_mediator_avoids_static_components(
        scene,
        group,
        mediator_after=(25, 30),
    )
    assert visual_causal._marker_mediator_avoids_static_components(
        scene,
        group,
        mediator_after=(52, 41),
    )


def test_virtual_marker_stage_cannot_overwrite_large_static_component() -> None:
    frame = _marker_frame(
        (((10, 50), (30, 50)),),
        ((40, 10),),
        (12,),
        active_group=0,
        active_index=0,
        background=5,
        active_color=0,
        fixed_color=3,
    )
    rows = [list(row) for row in frame.cells]
    for y in range(25, 36):
        for x in range(21, 30):
            rows[y][x] = 10
    scene = extract_visual_scene(GridFrame.from_rows(rows))
    group = _embedded_marker_groups(scene)[0]
    active = next(item for item in group.endpoints if item.color == 0)

    projection = visual_causal._scene_after_marker_stage(
        scene,
        group,
        active,
        Coordinate(20, 10),
    )

    assert projection is None


def test_role_switch_projects_outer_color_and_admits_exact_target_layer_solution() -> None:
    target = (55, 53)
    frame = _marker_frame(
        (((55, 39), (35, 33), (53, 60), (59, 60)),),
        (target,),
        (14,),
        active_group=0,
        active_index=0,
        background=5,
        active_color=0,
        fixed_color=3,
    )
    rows = [list(row) for row in frame.cells]
    for dx, dy in _TARGET_RING:
        rows[target[1] + dy][target[0] + dx] = 5
    _paint(rows, target, _OFFSET_SPARSE_TARGET_RING, 14)
    _paint(rows, (54, 54), _TARGET_LAYER_OVERLAY, 1)
    scene = extract_visual_scene(GridFrame.from_rows(rows))
    group = _embedded_marker_groups(scene)[0]
    active = next(item for item in group.endpoints if item.color == 0)
    low_anchor = next(item for item in group.endpoints if item.rounded_center == (35, 33))

    assert visual_causal._best_marker_relocation(
        scene,
        group,
        low_anchor,
        rejected_signatures=set(),
    ) != (0, Coordinate(54, 53))
    projection = visual_causal._scene_after_marker_role_switch(
        scene,
        group,
        active,
        low_anchor,
    )
    assert projection is not None
    projected_scene, projected_group, projected_active = projection
    assert projected_active.rounded_center == (35, 33)
    assert visual_causal._best_marker_relocation(
        projected_scene,
        projected_group,
        projected_active,
        rejected_signatures=set(),
    ) == (0, Coordinate(54, 53))

    plan = visual_causal._embedded_marker_plan(
        scene,
        level_index=2,
        active_color=0,
        staged_marker_color=None,
        rejected_signatures=set(),
    )
    assert plan is not None
    assert plan.coordinate == Coordinate(35, 33)
    assert "transfer the active role" in plan.expectation


def test_one_discriminating_transition_opens_provisional_affine_mechanic() -> None:
    target = (20, 10)
    before = extract_visual_scene(_frame((8, 32), (32, 32), target))
    action = ActionRequest(ActionName.ACTION6, Coordinate(12, 24))
    after = extract_visual_scene(_frame((12, 24), (32, 32), target))

    mechanic = infer_affine_mechanic(before, after, level_index=0, action=action)

    assert mechanic is not None
    assert mechanic.arity == 2
    assert mechanic.anchor_centers == ((32, 32),)
    assert mechanic.target_center == target
    assert mechanic.support_error <= 1.0


def test_supported_affine_form_transfers_without_coordinates_or_object_identity() -> None:
    scene = extract_visual_scene(_three_endpoint_frame())
    source_before = extract_visual_scene(_frame((8, 32), (32, 32), (20, 10)))
    source_after = extract_visual_scene(_frame((12, 24), (32, 32), (20, 10)))
    prior = infer_affine_mechanic(
        source_before,
        source_after,
        level_index=0,
        action=ActionRequest(ActionName.ACTION6, Coordinate(12, 24)),
    )
    assert prior is not None
    noisy_prior = replace(
        prior,
        mechanic_ref="affine:noisy-prior",
        support_error=7.0,
    )

    mechanic = infer_transferred_affine_mechanic(
        scene,
        level_index=4,
        active_color=0,
        supported_prior=(noisy_prior, prior),
    )

    assert mechanic is not None
    assert mechanic.mechanic_ref.startswith("affine-transfer:")
    assert mechanic.arity == 3
    assert set(mechanic.anchor_centers) == {(28, 8), (18, 26)}
    assert mechanic.target_center == (25, 29)


def test_unique_hollow_target_carries_role_when_palette_identity_changes() -> None:
    target = (53, 28)
    before = extract_visual_scene(
        _palette_mismatched_target_frame(
            (25, 35),
            (43, 34),
            ((target, 14),),
        )
    )
    after = extract_visual_scene(
        _palette_mismatched_target_frame(
            (21, 21),
            (43, 34),
            ((target, 14),),
        )
    )

    mechanic = infer_affine_mechanic(
        before,
        after,
        level_index=4,
        action=ActionRequest(ActionName.ACTION6, Coordinate(21, 21)),
    )

    assert mechanic is not None
    assert mechanic.mediator_color == 0
    assert mechanic.arity == 2
    assert mechanic.anchor_centers == ((43, 34),)
    assert mechanic.target_center == target


def test_mismatched_hollow_targets_remain_ambiguous() -> None:
    before = extract_visual_scene(
        _palette_mismatched_target_frame(
            (25, 35),
            (43, 34),
            (((53, 28), 14), ((13, 28), 8)),
        )
    )
    after = extract_visual_scene(
        _palette_mismatched_target_frame(
            (21, 21),
            (43, 34),
            (((53, 28), 14), ((13, 28), 8)),
        )
    )

    mechanic = infer_affine_mechanic(
        before,
        after,
        level_index=4,
        action=ActionRequest(ActionName.ACTION6, Coordinate(21, 21)),
    )

    assert mechanic is None


def test_one_mismatched_target_does_not_resolve_a_tied_mediator_relation() -> None:
    before = extract_visual_scene(_frame((8, 32), (32, 32), (20, 10)))
    after = extract_visual_scene(_frame((12, 24), (32, 32), (20, 10)))
    prior = infer_affine_mechanic(
        before,
        after,
        level_index=0,
        action=ActionRequest(ActionName.ACTION6, Coordinate(12, 24)),
    )
    assert prior is not None
    ambiguous = extract_visual_scene(_ambiguous_mismatched_target_frame())

    mechanic = infer_transferred_affine_mechanic(
        ambiguous,
        level_index=1,
        active_color=0,
        supported_prior=(prior,),
    )

    assert mechanic is None


def test_failed_target_relative_plan_signature_is_not_repeated() -> None:
    scene = extract_visual_scene(_frame((8, 32), (32, 32), (20, 10)))
    movers = (
        next(item for item in scene.endpoints if item.color == 0),
        next(item for item in scene.endpoints if item.color == 3),
    )
    first = _radial_plan_points(
        scene,
        target=(20, 10),
        movers=movers,
        rejected_signatures=set(),
    )
    assert first is not None
    signature = ";".join(f"{item.x},{item.y}" for item in first)

    second = _radial_plan_points(
        scene,
        target=(20, 10),
        movers=movers,
        rejected_signatures={signature},
    )

    assert second is not None
    assert second != first


@pytest.mark.parametrize(
    (
        "groups",
        "targets",
        "marker_colors",
        "active_group",
        "active_index",
        "background",
        "active_color",
        "fixed_color",
    ),
    (
        (
            (((10, 50), (30, 50)), ((38, 52), (58, 52))),
            ((20, 28), (48, 32)),
            (12, 14),
            0,
            0,
            5,
            0,
            3,
        ),
        (
            (((8, 14), (8, 34)), ((12, 46), (34, 46))),
            ((30, 24), (23, 28)),
            (13, 9),
            1,
            1,
            7,
            4,
            2,
        ),
    ),
)
def test_marker_planner_solves_distinct_groups_and_reobserves_after_switch(
    groups: tuple[tuple[tuple[int, int], ...], ...],
    targets: tuple[tuple[int, int], ...],
    marker_colors: tuple[int, ...],
    active_group: int,
    active_index: int,
    background: int,
    active_color: int,
    fixed_color: int,
) -> None:
    environment = _MarkerAffineEnvironment(
        groups=[list(group) for group in groups],
        targets=targets,
        marker_colors=marker_colors,
        active_group=active_group,
        active_index=active_index,
        background=background,
        active_color=active_color,
        fixed_color=fixed_color,
    )
    policy = VisualCausalPolicy()
    observation = environment.observation()

    first_solution = Coordinate(*environment.direct_solution())
    first = policy.select(observation)
    assert first.coordinate == first_solution
    observation = environment.step(first)
    policy.accept_consequence(observation)
    assert observation.state is GameStateName.NOT_FINISHED
    assert observation.levels_completed == 0

    solved_group = environment.active_group
    next_group = 1 - solved_group
    switch = policy.select(observation)
    assert switch.coordinate is not None
    assert (switch.coordinate.x, switch.coordinate.y) in environment.groups[next_group]
    observation = environment.step(switch)
    policy.accept_consequence(observation)
    assert environment.active_group == next_group
    assert observation.levels_completed == 0

    second_solution = Coordinate(*environment.direct_solution())
    second = policy.select(observation)
    assert second.coordinate == second_solution
    observation = environment.step(second)
    policy.accept_consequence(observation)

    assert observation.levels_completed == 1
    assert environment.action_kinds == ["move", "switch", "move"]
    assert policy.snapshot()["pending_plan_actions"] == 0
    assert policy.receipts[0].source_mechanic_refs[0].startswith("affine-marker:")
    assert "matched marker" in policy.receipts[1].prediction


def test_marker_planner_relocates_one_group_sequentially_when_direct_closure_is_out_of_bounds() -> (
    None
):
    environment = _MarkerAffineEnvironment(
        groups=[[(17, 6), (8, 21), (49, 9)]],
        targets=((40, 51),),
        marker_colors=(12,),
    )
    initial_direct = environment.direct_solution()
    assert initial_direct == (63, 123)
    policy = VisualCausalPolicy()
    observation = environment.observation()
    actions: list[ActionRequest] = []

    for _ in range(8):
        action = policy.select(observation)
        assert action.coordinate is not None
        assert 0 <= action.coordinate.x < 64
        assert 0 <= action.coordinate.y < 64
        actions.append(action)
        observation = environment.step(action)
        policy.accept_consequence(observation)
        if observation.levels_completed:
            break

    assert observation.levels_completed == 1
    assert len(actions) == 5
    assert environment.action_kinds == ["move", "switch", "move", "switch", "move"]
    assert all(
        "marker-group" in receipt.prediction or "same marker group" in receipt.prediction
        for receipt in policy.receipts
    )
    assert policy.snapshot()["pending_plan_actions"] == 0


def test_marker_planner_does_not_emit_an_unreadable_direct_destination(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    environment = _MarkerAffineEnvironment(
        groups=[[(8, 50), (32, 58), (52, 42)]],
        targets=((30, 40),),
        marker_colors=(12,),
    )
    blocked_direct = Coordinate(*environment.direct_solution())
    original_is_open = visual_causal._endpoint_placement_is_open

    def block_direct(
        scene: VisualScene,
        endpoint: visual_causal.VisualObject,
        *,
        x: int,
        y: int,
        permitted_occupied_cells: frozenset[tuple[int, int]] = frozenset(),
    ) -> bool:
        if (x, y) == (blocked_direct.x, blocked_direct.y):
            return False
        return original_is_open(
            scene,
            endpoint,
            x=x,
            y=y,
            permitted_occupied_cells=permitted_occupied_cells,
        )

    monkeypatch.setattr(visual_causal, "_endpoint_placement_is_open", block_direct)
    policy = VisualCausalPolicy()

    action = policy.select(environment.observation())

    assert action.coordinate != blocked_direct
    assert (
        "marker-group" in policy._pending_prediction or "marker group" in policy._pending_prediction
    )
    assert policy.snapshot()["pending_plan_actions"] == 0


def test_marker_relocation_uses_board_derived_rings_after_local_exhaustion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scene = extract_visual_scene(
        _marker_frame(
            (((10, 50), (30, 50)),),
            ((20, 28),),
            (12,),
            active_group=0,
            active_index=0,
            background=5,
            active_color=0,
            fixed_color=3,
        )
    )
    group = _embedded_marker_groups(scene)[0]
    endpoint = next(item for item in group.endpoints if item.color == 0)
    calls: list[tuple[int, int]] = []

    def candidate_batches(
        _scene: VisualScene,
        _group: visual_causal._EmbeddedMarkerGroup,
        _endpoint: visual_causal.VisualObject,
        *,
        minimum_radius: int = 6,
        maximum_radius: int = 27,
        **_kwargs: object,
    ) -> tuple[Coordinate, ...]:
        calls.append((minimum_radius, maximum_radius))
        if maximum_radius == 27:
            return ()
        return (Coordinate(10, 6),)

    monkeypatch.setattr(
        visual_causal,
        "_marker_relocation_candidates",
        candidate_batches,
    )

    result = visual_causal._best_marker_relocation(
        scene,
        group,
        endpoint,
        rejected_signatures=set(),
    )

    assert result == (0, Coordinate(10, 6))
    assert calls[0] == (6, 27)
    assert calls[1][0] == 28
    assert calls[1][1] == math.ceil(math.hypot(scene.width - 1, scene.height - 1))


def test_marker_planner_prefers_safe_same_group_transfer_before_deferral(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    environment = _MarkerAffineEnvironment(
        groups=[[(10, 50), (30, 50)], [(38, 52), (58, 52)]],
        targets=((20, 28), (48, 32)),
        marker_colors=(12, 14),
    )
    policy = VisualCausalPolicy()
    policy._last_active_color = environment.active_color
    original_readable = visual_causal._marker_mediator_remains_readable

    def block_active_endpoint(
        scene: VisualScene,
        group: visual_causal._EmbeddedMarkerGroup,
        endpoint: visual_causal.VisualObject,
        **kwargs: object,
    ) -> bool:
        if group.marker_color == 12 and endpoint.rounded_center == (10, 50):
            return False
        return original_readable(scene, group, endpoint, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(
        visual_causal,
        "_marker_mediator_remains_readable",
        block_active_endpoint,
    )

    action = policy.select(environment.observation())

    assert action.coordinate == Coordinate(*environment.groups[0][1])
    assert "same marker group" in policy._pending_prediction


def test_terrain_blocked_active_group_defers_to_safe_unresolved_group(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    environment = _MarkerAffineEnvironment(
        groups=[[(10, 50), (30, 50)], [(38, 52), (58, 52)]],
        targets=((20, 28), (48, 32)),
        marker_colors=(12, 14),
    )
    policy = VisualCausalPolicy()
    policy._last_active_color = environment.active_color
    original_readable = visual_causal._marker_mediator_remains_readable

    def block_first_group(
        scene: VisualScene,
        group: visual_causal._EmbeddedMarkerGroup,
        endpoint: visual_causal.VisualObject,
        **kwargs: object,
    ) -> bool:
        if group.marker_color == 12:
            return False
        return original_readable(scene, group, endpoint, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(
        visual_causal,
        "_marker_mediator_remains_readable",
        block_first_group,
    )
    observation = environment.observation()

    deferred = policy.select(observation)

    assert deferred.coordinate is not None
    assert (deferred.coordinate.x, deferred.coordinate.y) in environment.groups[1]
    assert "defer a marker group" in policy._pending_prediction
    observation = environment.step(deferred)
    policy.accept_consequence(observation)
    assert environment.active_group == 1

    next_action = policy.select(observation)
    assert next_action.coordinate not in {
        Coordinate(*endpoint) for endpoint in environment.groups[1]
    }
    assert "marker-group" in policy._pending_prediction


def test_active_known_without_a_safe_marker_plan_does_not_bootstrap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    environment = _MarkerAffineEnvironment(
        groups=[[(10, 50), (30, 50)]],
        targets=((20, 28),),
        marker_colors=(12,),
    )
    policy = VisualCausalPolicy()
    policy._last_active_color = environment.active_color
    monkeypatch.setattr(
        visual_causal,
        "_endpoint_placement_is_open",
        lambda *_args, **_kwargs: False,
    )

    with pytest.raises(PolicyError, match="no bounded same-group action"):
        policy.select(environment.observation())

    assert policy.snapshot()["marker_bootstrap_attempted"] is False
    assert policy.snapshot()["pending_plan_actions"] == 0


def test_marker_staging_reobserves_then_switches_before_exact_solve(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    environment = _MarkerAffineEnvironment(
        groups=[[(8, 48), (48, 8)]],
        targets=((18, 38),),
        marker_colors=(12,),
    )
    policy = VisualCausalPolicy()
    policy._last_active_color = environment.active_color
    original_open = visual_causal._endpoint_placement_is_open
    original_readable = visual_causal._marker_mediator_remains_readable
    stage = Coordinate(18, 22)
    solve = Coordinate(18, 54)

    def potential() -> int:
        endpoints = environment.groups[0]
        sum_x = sum(x for x, _y in endpoints)
        sum_y = sum(y for _x, y in endpoints)
        lower_x = len(endpoints) * environment.targets[0][0]
        lower_y = len(endpoints) * environment.targets[0][1]
        dx = min(abs(sum_x - value) for value in range(lower_x, lower_x + len(endpoints)))
        dy = min(abs(sum_y - value) for value in range(lower_y, lower_y + len(endpoints)))
        return dx * dx + dy * dy

    def constrained_open(
        scene: VisualScene,
        endpoint: visual_causal.VisualObject,
        *,
        x: int,
        y: int,
        permitted_occupied_cells: frozenset[tuple[int, int]] = frozenset(),
    ) -> bool:
        center = endpoint.rounded_center
        allowed = (center == (8, 48) and (x, y) == (stage.x, stage.y)) or (
            center == (48, 8) and (x, y) == (solve.x, solve.y)
        )
        return allowed and original_open(
            scene,
            endpoint,
            x=x,
            y=y,
            permitted_occupied_cells=permitted_occupied_cells,
        )

    monkeypatch.setattr(visual_causal, "_endpoint_placement_is_open", constrained_open)

    def constrained_readable(
        scene: VisualScene,
        group: visual_causal._EmbeddedMarkerGroup,
        endpoint: visual_causal.VisualObject,
        *,
        coordinate: Coordinate,
        mediator_after: tuple[int, int],
        final: bool,
        static_cells: frozenset[tuple[int, int]] | None = None,
    ) -> bool:
        initial_active_center_is_present = any(
            candidate.rounded_center == (8, 48) for candidate in group.endpoints
        )
        if endpoint.rounded_center == (48, 8) and initial_active_center_is_present:
            return False
        return original_readable(
            scene,
            group,
            endpoint,
            coordinate=coordinate,
            mediator_after=mediator_after,
            final=final,
            static_cells=static_cells,
        )

    monkeypatch.setattr(
        visual_causal,
        "_marker_mediator_remains_readable",
        constrained_readable,
    )
    observation = environment.observation()
    initial_potential = potential()

    first = policy.select(observation)
    assert first.coordinate == stage
    assert "stage the active endpoint" in policy._pending_prediction
    observation = environment.step(first)
    policy.accept_consequence(observation)
    staged_potential = potential()

    second = policy.select(observation)
    assert second.coordinate == Coordinate(48, 8)
    assert "after bounded marker staging" in policy._pending_prediction
    observation = environment.step(second)
    policy.accept_consequence(observation)

    third = policy.select(observation)
    assert third.coordinate == solve
    observation = environment.step(third)
    policy.accept_consequence(observation)
    final_potential = potential()

    assert observation.levels_completed == 1
    assert environment.action_kinds == ["move", "switch", "move"]
    assert staged_potential > initial_potential
    assert final_potential < initial_potential
    assert policy.snapshot()["marker_stage_pending_switch"] is None
    assert policy.snapshot()["pending_plan_actions"] == 0


def test_staging_projection_carries_only_the_starting_protected_target_surface(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scene = extract_visual_scene(_composite_marker_frame())
    group = next(item for item in _embedded_marker_groups(scene) if item.marker_color == 12)
    endpoint = next(item for item in group.endpoints if item.color == 0)
    stage = Coordinate(5, 5)
    expected_regions = visual_causal._visible_target_regions(
        scene,
        same_group_raster_cells=visual_causal._marker_dynamic_footprint(group),
    )
    carried_regions: list[
        tuple[tuple[tuple[int, int], frozenset[tuple[int, int]]], ...] | None
    ] = []

    monkeypatch.setattr(
        visual_causal,
        "_marker_relocation_candidates",
        lambda *_args, **_kwargs: (stage,),
    )
    monkeypatch.setattr(
        visual_causal,
        "_marker_mediator_remains_readable",
        lambda *_args, **_kwargs: True,
    )
    monkeypatch.setattr(
        visual_causal,
        "_scene_after_marker_stage",
        lambda *_args, **_kwargs: (scene, group),
    )

    def shallow_followup(
        *_args: object,
        target_regions: tuple[tuple[tuple[int, int], frozenset[tuple[int, int]]], ...]
        | None = None,
        **_kwargs: object,
    ) -> tuple[int, Coordinate]:
        carried_regions.append(target_regions)
        return (0, Coordinate(10, 10))

    monkeypatch.setattr(
        visual_causal,
        "_best_marker_relocation_after_switch",
        shallow_followup,
    )

    selected = visual_causal._best_marker_staging_relocation(
        scene,
        group,
        endpoint,
        rejected_signatures=set(),
    )

    assert selected == stage
    assert carried_regions
    assert all(regions == expected_regions for regions in carried_regions)


def test_staging_projection_rejects_a_reparsed_target_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scene = extract_visual_scene(_composite_marker_frame())
    groups = {item.marker_color: item for item in _embedded_marker_groups(scene)}
    group = groups[12]
    active = next(item for item in group.endpoints if item.color == 0)
    selected = next(item for item in group.endpoints if item.object_ref != active.object_ref)
    remapped_group = replace(group, target=groups[14].target)
    target_regions = visual_causal._visible_target_regions(
        scene,
        same_group_raster_cells=visual_causal._marker_dynamic_footprint(group),
    )
    relocation_called = False

    monkeypatch.setattr(
        visual_causal,
        "_scene_after_marker_role_switch",
        lambda *_args, **_kwargs: (scene, remapped_group, selected),
    )

    def unexpected_relocation(*_args: object, **_kwargs: object) -> None:
        nonlocal relocation_called
        relocation_called = True
        return None

    monkeypatch.setattr(
        visual_causal,
        "_best_marker_relocation",
        unexpected_relocation,
    )

    result = visual_causal._best_marker_relocation_after_switch(
        scene,
        group,
        active,
        selected,
        rejected_signatures=set(),
        target_regions=target_regions,
    )

    assert result is None
    assert not relocation_called


def test_marker_relocation_rejects_coordinate_inside_active_glyph(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scene = extract_visual_scene(
        _marker_frame(
            (((10, 50), (30, 50)),),
            ((20, 28),),
            (12,),
            active_group=0,
            active_index=0,
            background=5,
            active_color=0,
            fixed_color=3,
        )
    )
    group = _embedded_marker_groups(scene)[0]
    endpoint = next(item for item in group.endpoints if item.color == 0)

    monkeypatch.setattr(
        visual_causal,
        "_marker_relocation_candidates",
        lambda *_args, **_kwargs: (Coordinate(10, 48),),
    )
    monkeypatch.setattr(
        visual_causal,
        "_marker_mediator_remains_readable",
        lambda *_args, **_kwargs: True,
    )

    assert (
        visual_causal._best_marker_relocation(
            scene,
            group,
            endpoint,
            rejected_signatures=set(),
            allow_extended=False,
        )
        is None
    )


def test_marker_relocation_rejects_empty_active_bbox_corner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scene = extract_visual_scene(
        _marker_frame(
            (((10, 50), (30, 50)),),
            ((20, 28),),
            (12,),
            active_group=0,
            active_index=0,
            background=5,
            active_color=0,
            fixed_color=3,
        )
    )
    group = _embedded_marker_groups(scene)[0]
    endpoint = next(item for item in group.endpoints if item.color == 0)
    assert scene.cells[48][8] == 5

    monkeypatch.setattr(
        visual_causal,
        "_marker_relocation_candidates",
        lambda *_args, **_kwargs: (Coordinate(8, 48),),
    )
    monkeypatch.setattr(
        visual_causal,
        "_marker_mediator_remains_readable",
        lambda *_args, **_kwargs: True,
    )

    assert (
        visual_causal._best_marker_relocation(
            scene,
            group,
            endpoint,
            rejected_signatures=set(),
            allow_extended=False,
        )
        is None
    )


def test_unchanged_marker_role_switch_is_rejected() -> None:
    environment = _MarkerAffineEnvironment(
        groups=[[(10, 50), (30, 50)]],
        targets=((20, 28),),
        marker_colors=(12,),
    )
    policy = VisualCausalPolicy()
    policy._last_active_color = environment.active_color
    before = environment.observation()
    action = ActionRequest(ActionName.ACTION6, Coordinate(30, 50))
    policy._stage_pending(
        before,
        action,
        purpose=visual_causal.VisualActionPurpose.PROBE,
        prediction="transfer the active role within the same marker group",
        mechanic_refs=("affine-marker:test",),
        plan_signature="marker:12:rotate:30,50",
        target_center=(20, 28),
        mediator_color=12,
        arity=2,
    )
    unchanged = Observation(
        game_id=before.game_id,
        frames=before.frames,
        state=before.state,
        levels_completed=before.levels_completed,
        win_levels=before.win_levels,
        available_actions=before.available_actions,
        returned_action=action,
    )

    policy.accept_consequence(unchanged)

    assert policy.snapshot()["failed_plan_count"] == 1
    assert policy.receipts[-1].residual == "planned marker endpoint became structurally unreadable"


def test_marker_target_contamination_transfers_then_restores_sparse_ring(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_best_relocation = visual_causal._best_marker_relocation
    monkeypatch.setattr(
        visual_causal,
        "_best_marker_relocation",
        lambda *_args, **_kwargs: None,
    )
    inactive_scene = extract_visual_scene(_contaminated_marker_target_frame(active_index=0))
    inactive_group = _embedded_marker_groups(inactive_scene)[0]
    contaminant = visual_causal._certified_marker_target_contaminant(inactive_group)

    assert contaminant is not None
    assert contaminant.rounded_center == (48, 40)
    transfer = visual_causal._embedded_marker_plan(
        inactive_scene,
        level_index=0,
        active_color=0,
        staged_marker_color=None,
        rejected_signatures=set(),
    )
    assert transfer is not None
    assert transfer.coordinate == Coordinate(48, 40)
    assert "transfer the active role" in transfer.expectation

    active_frame = _contaminated_marker_target_frame(active_index=1)
    active_scene = extract_visual_scene(active_frame)
    active_group = _embedded_marker_groups(active_scene)[0]
    active = visual_causal._embedded_marker_active_endpoint(active_scene, active_color=0)
    assert active is not None
    separation = visual_causal._embedded_marker_plan(
        active_scene,
        level_index=0,
        active_color=0,
        staged_marker_color=None,
        rejected_signatures=set(),
    )
    assert separation is not None
    assert separation.coordinate == Coordinate(51, 41)
    assert "separate the active marker center" in separation.expectation

    monkeypatch.setattr(
        visual_causal,
        "_best_marker_relocation",
        original_best_relocation,
    )

    projection = visual_causal._scene_after_marker_stage(
        active_scene,
        active_group,
        active,
        separation.coordinate,
    )
    assert projection is not None
    projected_scene, _projected_group = projection
    refreshed = extract_visual_scene(GridFrame(projected_scene.cells))
    refreshed_group = _embedded_marker_groups(refreshed)[0]
    assert refreshed_group.target.area == len(_OFFSET_SPARSE_TARGET_RING)
    assert refreshed_group.target.rounded_center == (44, 44)
    assert visual_causal._certified_marker_target_contaminant(refreshed_group) is None
    assert visual_causal._marker_target_separation_observed(
        active_scene,
        refreshed,
        marker_color=12,
        arity=4,
        coordinate=separation.coordinate,
    )

    before = Observation(
        game_id=GameId("synthetic-contaminated-target"),
        frames=(active_frame,),
        state=GameStateName.NOT_FINISHED,
        levels_completed=0,
        win_levels=1,
        available_actions=(ActionName.ACTION6,),
    )
    after = Observation(
        game_id=before.game_id,
        frames=(GridFrame(projected_scene.cells),),
        state=GameStateName.NOT_FINISHED,
        levels_completed=0,
        win_levels=1,
        available_actions=(ActionName.ACTION6,),
        returned_action=ActionRequest(ActionName.ACTION6, separation.coordinate),
    )
    policy = VisualCausalPolicy()
    policy._last_active_color = 0
    policy._stage_pending(
        before,
        ActionRequest(ActionName.ACTION6, separation.coordinate),
        purpose=visual_causal.VisualActionPurpose.PROBE,
        prediction="restore one certified sparse target ring",
        mechanic_refs=("affine-marker:test",),
        plan_signature="marker:12:separate:51,41",
        target_center=(44, 44),
        mediator_color=12,
        arity=4,
    )
    policy.accept_consequence(after)
    assert policy.snapshot()["marker_target_identity_constraint_count"] == 1


def test_compound_target_sector_overlay_is_separated_and_not_rejoined(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scene = extract_visual_scene(_compound_target_overlay_contamination_frame(active_index=0))
    group = _embedded_marker_groups(scene)[0]
    active = visual_causal._embedded_marker_active_endpoint(scene, active_color=0)
    assert active is not None
    contaminant = visual_causal._certified_marker_target_contaminant_in_scene(
        scene,
        group,
    )
    assert contaminant is not None
    assert contaminant.rounded_center == (34, 12)

    monkeypatch.setattr(
        visual_causal,
        "_best_marker_relocation",
        lambda *_args, **_kwargs: None,
    )
    separation = visual_causal._embedded_marker_plan(
        scene,
        level_index=0,
        active_color=0,
        staged_marker_color=None,
        rejected_signatures=set(),
    )
    assert separation is not None
    assert separation.plan_signature.startswith("marker:14:separate:")
    assert separation.coordinate == Coordinate(31, 12)

    projection = visual_causal._scene_after_marker_stage(
        scene,
        group,
        active,
        separation.coordinate,
    )
    assert projection is not None
    projected_scene, _projected_group = projection
    refreshed = extract_visual_scene(GridFrame(projected_scene.cells))
    refreshed_group = _embedded_marker_groups(refreshed)[0]
    refreshed_active = visual_causal._embedded_marker_active_endpoint(
        refreshed,
        active_color=0,
    )
    assert refreshed_active is not None
    assert (
        visual_causal._certified_marker_target_contaminant_in_scene(
            refreshed,
            refreshed_group,
        )
        is None
    )
    assert visual_causal._marker_target_separation_observed(
        scene,
        refreshed,
        marker_color=14,
        arity=3,
        coordinate=separation.coordinate,
    )

    monkeypatch.setattr(
        visual_causal,
        "_marker_relocation_candidates",
        lambda *_args, **_kwargs: (Coordinate(34, 12),),
    )
    monkeypatch.setattr(
        visual_causal,
        "_marker_mediator_remains_readable",
        lambda *_args, **_kwargs: True,
    )
    assert (
        visual_causal._best_marker_relocation(
            refreshed,
            refreshed_group,
            refreshed_active,
            rejected_signatures={visual_causal._marker_target_identity_constraint(14)},
            allow_extended=False,
        )
        is None
    )


def test_marker_target_separation_requires_exact_raw_target_restoration() -> None:
    before = extract_visual_scene(_compound_target_overlay_contamination_frame(active_index=0))
    group = _embedded_marker_groups(before)[0]
    active = visual_causal._embedded_marker_active_endpoint(before, active_color=0)
    assert active is not None
    coordinate = Coordinate(31, 12)
    projection = visual_causal._scene_after_marker_stage(
        before,
        group,
        active,
        coordinate,
    )
    assert projection is not None
    clean_rows = [list(row) for row in projection[0].cells]

    bridged_rows = [row.copy() for row in clean_rows]
    bridged_rows[12][34] = 14
    bridged = extract_visual_scene(GridFrame.from_rows(bridged_rows))
    assert not visual_causal._marker_target_separation_observed(
        before,
        bridged,
        marker_color=14,
        arity=3,
        coordinate=coordinate,
    )

    swapped_rows = [row.copy() for row in clean_rows]
    swapped_rows[9][39], swapped_rows[9][41] = swapped_rows[9][41], swapped_rows[9][39]
    swapped = extract_visual_scene(GridFrame.from_rows(swapped_rows))
    assert not visual_causal._marker_target_separation_observed(
        before,
        swapped,
        marker_color=14,
        arity=3,
        coordinate=coordinate,
    )


def test_local_collapse_reacquires_endpoint_with_certified_separation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scene = extract_visual_scene(_compound_target_overlay_contamination_frame(active_index=None))
    group = _embedded_marker_groups(scene)[0]
    assert visual_causal._embedded_marker_active_endpoint(scene, active_color=0) is None

    monkeypatch.setattr(
        visual_causal,
        "_best_marker_relocation",
        lambda *_args, **_kwargs: None,
    )
    reacquisition = visual_causal._embedded_marker_plan(
        scene,
        level_index=0,
        active_color=0,
        staged_marker_color=None,
        rejected_signatures=set(),
        allow_reacquisition=True,
    )
    assert reacquisition is not None
    assert reacquisition.coordinate == Coordinate(34, 12)
    assert reacquisition.plan_signature == "marker:14:activate:34,12"

    projection = visual_causal._scene_after_marker_reacquisition(
        scene,
        group,
        next(endpoint for endpoint in group.endpoints if endpoint.rounded_center == (34, 12)),
        active_color=0,
    )
    assert projection is not None
    projected_scene, _projected_group, _projected_active = projection
    activated = extract_visual_scene(GridFrame(projected_scene.cells))
    separation = visual_causal._embedded_marker_plan(
        activated,
        level_index=0,
        active_color=0,
        staged_marker_color=None,
        rejected_signatures=set(),
    )
    assert separation is not None
    assert separation.coordinate == Coordinate(31, 12)
    assert separation.plan_signature == "marker:14:separate:31,12"


def test_visible_active_outside_group_transfers_to_certified_separation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base = _compound_target_overlay_contamination_frame(active_index=None)
    rows = [list(row) for row in base.cells]
    outside_active = (6, 43)
    _paint(rows, outside_active, _ENDPOINT_SHAPE, 0)
    rows[outside_active[1]][outside_active[0]] = 9
    scene = extract_visual_scene(GridFrame.from_rows(rows))
    groups = _embedded_marker_groups(scene)
    assert len(groups) == 1
    assert all(
        endpoint.rounded_center != outside_active
        for group in groups
        for endpoint in group.endpoints
    )
    assert (
        visual_causal._marker_bootstrap_active_color(
            scene,
            coordinate=Coordinate(*outside_active),
        )
        == 0
    )

    monkeypatch.setattr(
        visual_causal,
        "_best_marker_relocation_after_switch",
        lambda *_args, **_kwargs: None,
    )
    transfer = visual_causal._embedded_marker_plan(
        scene,
        level_index=0,
        active_color=0,
        staged_marker_color=None,
        rejected_signatures=set(),
    )
    assert transfer is not None
    assert transfer.coordinate == Coordinate(34, 12)
    assert transfer.plan_signature == "marker:14:activate:34,12"

    outside = next(
        endpoint for endpoint in scene.endpoints if endpoint.rounded_center == outside_active
    )
    contaminant = next(
        endpoint for endpoint in groups[0].endpoints if endpoint.rounded_center == (34, 12)
    )
    projected = visual_causal._scene_after_marker_role_switch(
        scene,
        groups[0],
        outside,
        contaminant,
    )
    assert projected is not None
    assert visual_causal._best_marker_target_separation(
        projected[0],
        projected[1],
        projected[2],
        rejected_signatures=set(),
    ) == Coordinate(31, 12)


def test_near_target_endpoint_without_exact_sector_equality_is_not_certified() -> None:
    frame = _compound_target_overlay_contamination_frame(active_index=0)
    scene = extract_visual_scene(frame)
    group = _embedded_marker_groups(scene)[0]
    overlay = next(
        target
        for target in scene.targets
        if target.color == group.marker_color and set(target.cells) - set(group.target.cells)
    )
    near_overlay = replace(
        overlay,
        object_ref=f"{overlay.object_ref}:near",
        cells=tuple((*overlay.cells, (36, 12))),
        max_x=max(overlay.max_x, 36),
    )
    near_scene = replace(
        scene,
        objects=tuple(
            near_overlay if item.object_ref == overlay.object_ref else item
            for item in scene.objects
        ),
    )

    assert visual_causal._certified_marker_target_overlay_contaminant(near_scene, group) is None


def test_ordinary_marker_improvement_retains_restored_target_identity() -> None:
    before_frame = _contaminated_marker_target_frame(active_index=1)
    before_scene = extract_visual_scene(before_frame)
    group = _embedded_marker_groups(before_scene)[0]
    active = visual_causal._embedded_marker_active_endpoint(before_scene, active_color=0)
    assert active is not None
    coordinate = Coordinate(52, 52)
    projection = visual_causal._scene_after_marker_stage(
        before_scene,
        group,
        active,
        coordinate,
    )
    assert projection is not None
    projected_scene, _projected_group = projection
    after_frame = GridFrame(projected_scene.cells)
    after_scene = extract_visual_scene(after_frame)
    assert visual_causal._marker_target_separation_observed(
        before_scene,
        after_scene,
        marker_color=12,
        arity=4,
        coordinate=coordinate,
    )

    before = Observation(
        game_id=GameId("synthetic-ordinary-target-separation"),
        frames=(before_frame,),
        state=GameStateName.NOT_FINISHED,
        levels_completed=0,
        win_levels=1,
        available_actions=(ActionName.ACTION6,),
    )
    after = Observation(
        game_id=before.game_id,
        frames=(after_frame,),
        state=GameStateName.NOT_FINISHED,
        levels_completed=0,
        win_levels=1,
        available_actions=(ActionName.ACTION6,),
        returned_action=ActionRequest(ActionName.ACTION6, coordinate),
    )
    policy = VisualCausalPolicy()
    policy._last_active_color = 0
    policy._stage_pending(
        before,
        ActionRequest(ActionName.ACTION6, coordinate),
        purpose=visual_causal.VisualActionPurpose.PROGRESS,
        prediction="strictly reduce the marker-group floor-centroid residual",
        mechanic_refs=("affine-marker:test",),
        plan_signature="marker:12:improve:52,52",
        target_center=(44, 44),
        mediator_color=12,
        arity=4,
    )

    policy.accept_consequence(after)

    assert policy.snapshot()["marker_target_identity_constraint_count"] == 1
    assert policy.snapshot()["failed_plan_count"] == 0


def test_dedicated_marker_separation_requires_restored_target_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    before_frame = _contaminated_marker_target_frame(active_index=1)
    before_scene = extract_visual_scene(before_frame)
    group = _embedded_marker_groups(before_scene)[0]
    active = visual_causal._embedded_marker_active_endpoint(before_scene, active_color=0)
    assert active is not None
    coordinate = Coordinate(51, 41)
    projection = visual_causal._scene_after_marker_stage(
        before_scene,
        group,
        active,
        coordinate,
    )
    assert projection is not None
    projected_scene, _projected_group = projection
    before = Observation(
        game_id=GameId("synthetic-failed-target-separation"),
        frames=(before_frame,),
        state=GameStateName.NOT_FINISHED,
        levels_completed=0,
        win_levels=1,
        available_actions=(ActionName.ACTION6,),
    )
    after = Observation(
        game_id=before.game_id,
        frames=(GridFrame(projected_scene.cells),),
        state=GameStateName.NOT_FINISHED,
        levels_completed=0,
        win_levels=1,
        available_actions=(ActionName.ACTION6,),
        returned_action=ActionRequest(ActionName.ACTION6, coordinate),
    )
    policy = VisualCausalPolicy()
    policy._last_active_color = 0
    policy._stage_pending(
        before,
        ActionRequest(ActionName.ACTION6, coordinate),
        purpose=visual_causal.VisualActionPurpose.PROBE,
        prediction="restore one certified sparse target ring",
        mechanic_refs=("affine-marker:test",),
        plan_signature="marker:12:separate:51,41",
        target_center=(44, 44),
        mediator_color=12,
        arity=4,
    )
    monkeypatch.setattr(
        visual_causal,
        "_marker_target_separation_observed",
        lambda *_args, **_kwargs: False,
    )

    policy.accept_consequence(after)

    assert policy.snapshot()["failed_plan_count"] == 1
    assert policy.snapshot()["marker_target_identity_constraint_count"] == 0
    assert policy.receipts[-1].residual == "planned marker target separation was not observed"


def test_marker_relocation_does_not_rejoin_center_to_nonfinal_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    contaminated = extract_visual_scene(_contaminated_marker_target_frame(active_index=1))
    contaminated_group = _embedded_marker_groups(contaminated)[0]
    contaminated_endpoint = visual_causal._embedded_marker_active_endpoint(
        contaminated,
        active_color=0,
    )
    assert contaminated_endpoint is not None
    projection = visual_causal._scene_after_marker_stage(
        contaminated,
        contaminated_group,
        contaminated_endpoint,
        Coordinate(51, 41),
    )
    assert projection is not None
    projected_scene, _projected_group = projection
    scene = extract_visual_scene(GridFrame(projected_scene.cells))
    group = _embedded_marker_groups(scene)[0]
    endpoint = visual_causal._embedded_marker_active_endpoint(scene, active_color=0)
    assert endpoint is not None
    assert endpoint.rounded_center == (51, 41)

    monkeypatch.setattr(
        visual_causal,
        "_marker_relocation_candidates",
        lambda *_args, **_kwargs: (Coordinate(48, 40),),
    )
    monkeypatch.setattr(
        visual_causal,
        "_marker_mediator_remains_readable",
        lambda *_args, **_kwargs: True,
    )

    assert (
        visual_causal._best_marker_relocation(
            scene,
            group,
            endpoint,
            rejected_signatures={visual_causal._marker_target_identity_constraint(12)},
            allow_extended=False,
        )
        is None
    )


def test_readable_marker_stage_survives_generic_effect_unreadability(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    environment = _MarkerAffineEnvironment(
        groups=[[(10, 50), (30, 50)]],
        targets=((20, 28),),
        marker_colors=(12,),
    )
    policy = VisualCausalPolicy()
    policy._last_active_color = environment.active_color
    before = environment.observation()
    action = ActionRequest(ActionName.ACTION6, Coordinate(10, 40))
    policy._marker_stage_pending_switch = 12
    policy._stage_pending(
        before,
        action,
        purpose=visual_causal.VisualActionPurpose.PROBE,
        prediction=(
            "stage the active endpoint so a same-marker role transfer opens a bounded "
            "improving relocation"
        ),
        mechanic_refs=("affine-marker:test",),
        plan_signature="marker:12:stage:10,40",
        target_center=(20, 28),
        mediator_color=12,
        arity=2,
    )
    after = environment.step(action)
    monkeypatch.setattr(visual_causal, "infer_affine_mechanic", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        visual_causal,
        "_coordinate_transform_observed",
        lambda *_args, **_kwargs: False,
    )

    policy.accept_consequence(after)

    assert policy.snapshot()["marker_stage_pending_switch"] == 12
    assert policy.snapshot()["failed_plan_count"] == 0
    assert policy.receipts[-1].residual != "planned marker endpoint became structurally unreadable"


def test_marker_planner_switches_to_endpoint_with_certified_staged_route(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    environment = _MarkerAffineEnvironment(
        groups=[[(8, 48), (48, 8), (48, 48)]],
        targets=((18, 38),),
        marker_colors=(12,),
    )
    policy = VisualCausalPolicy()
    policy._last_active_color = environment.active_color
    staged_endpoint = environment.groups[0][1]

    monkeypatch.setattr(
        visual_causal,
        "_best_marker_relocation",
        lambda *_args, **_kwargs: None,
    )

    def staged_route(
        _scene: VisualScene,
        _group: visual_causal._EmbeddedMarkerGroup,
        endpoint: visual_causal.VisualObject,
        **_kwargs: object,
    ) -> Coordinate | None:
        if endpoint.rounded_center == staged_endpoint:
            return Coordinate(20, 20)
        return None

    monkeypatch.setattr(
        visual_causal,
        "_best_marker_staging_relocation",
        staged_route,
    )

    action = policy.select(environment.observation())

    assert action.coordinate == Coordinate(*staged_endpoint)
    assert "expose a bounded staged continuation" in policy._pending_prediction


def test_structural_marker_cycle_is_rejected_despite_frame_animation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    environment = _MarkerAffineEnvironment(
        groups=[[(10, 50), (30, 50)]],
        targets=((20, 28),),
        marker_colors=(12,),
    )
    policy = VisualCausalPolicy()
    policy._last_active_color = environment.active_color

    monkeypatch.setattr(
        visual_causal,
        "_best_marker_relocation",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        visual_causal,
        "_best_marker_relocation_after_switch",
        lambda *_args, **_kwargs: (0, Coordinate(20, 20)),
    )
    monkeypatch.setattr(
        visual_causal,
        "_best_marker_staging_relocation",
        lambda *_args, **_kwargs: None,
    )

    observation = environment.observation()
    first = policy.select(observation)
    observation = environment.step(first)
    policy.accept_consequence(observation)
    second = policy.select(observation)
    observation = environment.step(second)
    policy.accept_consequence(observation)

    assert first.coordinate == Coordinate(30, 50)
    assert second.coordinate == Coordinate(10, 50)
    with pytest.raises(PolicyError, match="no bounded same-group action"):
        policy.select(observation)
    assert policy.snapshot()["marker_structural_action_count"] == 2


def test_marker_planner_uses_previously_observed_unique_active_color_for_arity_two() -> None:
    environment = _MarkerAffineEnvironment(
        groups=[[(10, 50), (30, 50)]],
        targets=((20, 28),),
        marker_colors=(12,),
    )
    policy = VisualCausalPolicy()
    policy._last_active_color = environment.active_color

    action = policy.select(environment.observation())

    assert action.coordinate == Coordinate(*environment.direct_solution())
    assert policy.snapshot()["marker_bootstrap_attempted"] is False
    assert policy.snapshot()["pending_plan_actions"] == 0


@pytest.mark.parametrize("stale_active_color", (None, 9))
def test_ambiguous_arity_two_bootstraps_once_then_replans_from_learned_color(
    stale_active_color: int | None,
) -> None:
    environment = _MarkerAffineEnvironment(
        groups=[[(10, 50), (30, 50)]],
        targets=((20, 28),),
        marker_colors=(12,),
    )
    policy = VisualCausalPolicy()
    policy._last_active_color = stale_active_color
    before = environment.observation()
    scene = extract_visual_scene(before.frames[-1])

    bootstrap = policy.select(before)

    assert bootstrap.coordinate is not None
    assert scene.is_open(bootstrap.coordinate.x, bootstrap.coordinate.y)
    assert all(
        math.dist((bootstrap.coordinate.x, bootstrap.coordinate.y), endpoint) > 2.25
        for endpoint in environment.groups[0]
    )
    assert "identify the active marker endpoint" in policy._pending_prediction
    assert policy.snapshot()["marker_bootstrap_attempted"] is True
    assert policy.snapshot()["pending_plan_actions"] == 0

    observation = environment.step(bootstrap)
    policy.accept_consequence(observation)

    assert policy._last_active_color == environment.active_color
    assert policy.snapshot()["pending_plan_actions"] == 0
    direct = policy.select(observation)
    assert direct.coordinate == Coordinate(*environment.direct_solution())


def test_readable_marker_bootstrap_succeeds_without_generic_affine_inference(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    environment = _MarkerAffineEnvironment(
        groups=[[(10, 50), (30, 50)]],
        targets=((20, 28),),
        marker_colors=(12,),
    )
    policy = VisualCausalPolicy()
    before = environment.observation()
    bootstrap = policy.select(before)
    after = environment.step(bootstrap)
    monkeypatch.setattr(
        visual_causal,
        "infer_affine_mechanic",
        lambda *_args, **_kwargs: None,
    )

    policy.accept_consequence(after)

    assert policy._last_active_color == environment.active_color
    assert policy.snapshot()["failed_plan_count"] == 0
    assert policy.receipts[-1].residual != "probe did not localize a supported affine response"
    assert (
        policy.receipts[-1]
        .causal_action_receipt.observed_effects.get(
            visual_causal.EffectChannel.CONTROLLABLE_OBJECT_DISPLACEMENT
        )
        .knowledge
        is visual_causal.EffectKnowledge.KNOWN
    )


def test_failed_marker_bootstrap_is_not_repeated_or_replaced_by_legacy_relocation() -> None:
    environment = _MarkerAffineEnvironment(
        groups=[[(10, 50), (30, 50)], [(38, 52), (58, 52)]],
        targets=((20, 28), (48, 32)),
        marker_colors=(12, 14),
        active_color=3,
        fixed_color=3,
    )
    policy = VisualCausalPolicy()
    before = environment.observation()

    bootstrap = policy.select(before)
    assert bootstrap.coordinate is not None
    assert policy.snapshot()["pending_plan_actions"] == 0
    policy.accept_consequence(environment.observation(returned_action=bootstrap))

    with pytest.raises(PolicyError, match="no bounded same-group action"):
        policy.select(environment.observation())

    assert len(policy.receipts) == 1
    assert policy.receipts[0].action == bootstrap
    assert policy.receipts[0].residual == "probe did not localize a supported affine response"
    assert policy.snapshot()["failed_plan_count"] == 1
    assert policy.snapshot()["pending_plan_actions"] == 0


@dataclass
class _TwoEndpointEnvironment:
    active: tuple[int, int] = (8, 32)
    anchor: tuple[int, int] = (32, 32)
    target: tuple[int, int] = (20, 10)
    levels_completed: int = 0

    def observation(self, returned_action: ActionRequest | None = None) -> Observation:
        return _observation(
            self.active,
            self.anchor,
            self.target,
            levels_completed=self.levels_completed,
            returned_action=returned_action,
        )

    def step(self, action: ActionRequest) -> Observation:
        assert action.coordinate is not None
        clicked = (action.coordinate.x, action.coordinate.y)
        if math.dist(clicked, self.anchor) <= 2.5:
            self.active, self.anchor = self.anchor, self.active
        else:
            self.active = clicked
        hub = (
            (self.active[0] + self.anchor[0]) / 2,
            (self.active[1] + self.anchor[1]) / 2,
        )
        if math.dist(hub, self.target) <= 1.0:
            self.levels_completed = 1
        return self.observation(returned_action=action)


@dataclass
class _TwoLevelEnvironment:
    active: tuple[int, int] = (8, 32)
    anchor: tuple[int, int] = (32, 32)
    target: tuple[int, int] = (20, 10)
    levels_completed: int = 0
    state: GameStateName = GameStateName.NOT_FINISHED

    def observation(self, returned_action: ActionRequest | None = None) -> Observation:
        return _observation(
            self.active,
            self.anchor,
            self.target,
            levels_completed=self.levels_completed,
            state=self.state,
            returned_action=returned_action,
        )

    def step(self, action: ActionRequest) -> Observation:
        assert action.coordinate is not None
        clicked = (action.coordinate.x, action.coordinate.y)
        if math.dist(clicked, self.anchor) <= 2.5:
            self.active, self.anchor = self.anchor, self.active
        else:
            self.active = clicked
        hub = (
            (self.active[0] + self.anchor[0]) / 2,
            (self.active[1] + self.anchor[1]) / 2,
        )
        if math.dist(hub, self.target) <= 1.0:
            self.levels_completed += 1
            if self.levels_completed == 1:
                self.active = (7, 33)
                self.anchor = (31, 31)
                self.target = (22, 8)
            else:
                self.state = GameStateName.WIN
        return self.observation(returned_action=action)


@dataclass
class _LocalTargetEnvironment(_TwoEndpointEnvironment):
    solved: bool = False

    def step(self, action: ActionRequest) -> Observation:
        assert action.coordinate is not None
        clicked = (action.coordinate.x, action.coordinate.y)
        if math.dist(clicked, self.anchor) <= 2.5:
            self.active, self.anchor = self.anchor, self.active
        else:
            self.active = clicked
        hub = (
            (self.active[0] + self.anchor[0]) / 2,
            (self.active[1] + self.anchor[1]) / 2,
        )
        self.solved = math.dist(hub, self.target) <= 1.0
        return self.observation(returned_action=action)


def test_policy_learns_then_completes_target_relative_plan_without_grid_sweep() -> None:
    environment = _TwoEndpointEnvironment()
    policy = VisualCausalPolicy(max_coordinate_candidates=8)
    observation = environment.observation()
    coordinates: list[Coordinate] = []

    for _ in range(12):
        action = policy.select(observation)
        assert action.name is ActionName.ACTION6
        assert action.coordinate is not None
        coordinates.append(action.coordinate)
        observation = environment.step(action)
        policy.accept_consequence(observation)
        if observation.levels_completed:
            break

    assert observation.levels_completed == 1
    assert policy.mechanics
    assert len(coordinates) <= 6
    assert len(set(coordinates)) == len(coordinates)
    assert all(receipt.before_state is GameStateName.NOT_FINISHED for receipt in policy.receipts)
    durable = policy.drain_durable_receipts()
    assert len(durable) == len(coordinates)
    assert policy.drain_durable_receipts() == ()


def test_policy_continues_after_level_transition_until_final_win() -> None:
    environment = _TwoLevelEnvironment()
    policy = VisualCausalPolicy(max_coordinate_candidates=8)
    observation = environment.observation()

    for _ in range(24):
        if observation.state is GameStateName.WIN:
            break
        action = policy.select(observation)
        observation = environment.step(action)
        policy.accept_consequence(observation)

    assert observation.state is GameStateName.WIN
    assert observation.levels_completed == 2
    assert policy.mechanical_learner is not None
    assert policy.mechanical_learner.ledger.active()
    with pytest.raises(PolicyError, match="already reports WIN"):
        policy.select(observation)


def test_local_target_success_is_not_mislabeled_as_level_failure() -> None:
    environment = _LocalTargetEnvironment()
    policy = VisualCausalPolicy()
    observation = environment.observation()

    for _ in range(10):
        action = policy.select(observation)
        observation = environment.step(action)
        policy.accept_consequence(observation)
        if environment.solved:
            break

    assert environment.solved
    assert observation.state is GameStateName.NOT_FINISHED
    assert observation.levels_completed == 0
    assert policy.snapshot()["failed_plan_count"] == 0
    assert policy.snapshot()["pending_plan_actions"] == 0


def test_local_affine_closure_reacquires_a_safe_remaining_group() -> None:
    def observation(
        frame: GridFrame,
        *,
        returned_action: ActionRequest | None = None,
    ) -> Observation:
        return Observation(
            game_id=GameId("synthetic-ordinary-affine-reacquisition"),
            frames=(frame,),
            state=GameStateName.NOT_FINISHED,
            levels_completed=4,
            win_levels=6,
            available_actions=(ActionName.ACTION6,),
            returned_action=returned_action,
        )

    before = observation(_ordinary_two_group_frame(active=(43, 34), first_hub=(52, 31)))
    completion = ActionRequest(ActionName.ACTION6, Coordinate(46, 28))
    completed = observation(
        _ordinary_two_group_frame(active=(46, 28), first_hub=(53, 28)),
        returned_action=completion,
    )
    policy = VisualCausalPolicy()
    policy._begin_level(before)
    policy._last_active_color = 0
    policy._stage_pending(
        before,
        completion,
        purpose=VisualActionPurpose.PROGRESS,
        prediction="complete one observed affine relation",
        mechanic_refs=("affine-transfer:synthetic",),
        plan_signature="synthetic-local-completion",
        target_center=(53, 28),
        mediator_color=0,
        arity=2,
        completes_local_target=True,
    )
    policy.accept_consequence(completed)

    assert policy.snapshot()["affine_reacquire_after_local_solve"] is True
    completed_scene = extract_visual_scene(completed.frames[-1])
    unsafe = next(item for item in completed_scene.endpoints if item.rounded_center == (41, 47))
    assert not visual_causal._role_swap_remains_readable(
        completed_scene,
        unsafe,
        active_color=0,
    )

    reacquire = policy.select(completed)

    assert reacquire == ActionRequest(ActionName.ACTION6, Coordinate(34, 55))
    assert "reacquire the active role" in policy._pending_prediction
    swapped = observation(
        _ordinary_two_group_frame(
            active=(34, 55),
            first_hub=(53, 28),
            fixed_endpoints=((60, 28), (52, 55), (46, 28), (41, 47)),
        ),
        returned_action=reacquire,
    )
    policy.accept_consequence(swapped)

    assert policy._last_probe_failed is False
    assert policy.snapshot()["affine_reacquire_after_local_solve"] is False
    assert policy.receipts[-1].residual != "probe did not localize a supported affine response"

    transferred = infer_transferred_affine_mechanic(
        extract_visual_scene(swapped.frames[-1]),
        level_index=4,
        active_color=0,
        supported_prior=policy.mechanics,
    )
    assert transferred is not None
    assert transferred.arity == 3
    assert set(transferred.anchor_centers) == {(52, 55), (41, 47)}
    assert transferred.target_center == (53, 28)


def test_endpoint_role_switch_requires_exact_clicked_active_exchange() -> None:
    before = extract_visual_scene(_ordinary_two_group_frame(active=(46, 28), first_hub=(53, 28)))
    valid_after_frame = _ordinary_two_group_frame(
        active=(34, 55),
        first_hub=(53, 28),
        fixed_endpoints=((60, 28), (52, 55), (46, 28), (41, 47)),
    )
    valid_after = extract_visual_scene(valid_after_frame)
    selected_action = ActionRequest(ActionName.ACTION6, Coordinate(34, 55))

    assert visual_causal._endpoint_role_switch_observed(
        before,
        valid_after,
        action=selected_action,
        active_color=0,
    )

    third_recolor_rows = [list(row) for row in valid_after_frame.cells]
    _paint(third_recolor_rows, (52, 55), _ENDPOINT_SHAPE, 2)
    third_recolor_rows[55][52] = 4
    third_recolor = extract_visual_scene(GridFrame.from_rows(third_recolor_rows))

    assert not visual_causal._endpoint_role_switch_observed(
        before,
        third_recolor,
        action=selected_action,
        active_color=0,
    )
    assert not visual_causal._endpoint_role_switch_observed(
        before,
        valid_after,
        action=ActionRequest(ActionName.ACTION6, Coordinate(52, 55)),
        active_color=0,
    )


def test_affine_endpoint_group_rejects_exact_cross_arity_tie() -> None:
    rows = [[5 for _ in range(64)] for _ in range(64)]
    for endpoint in ((12, 32), (52, 32), (32, 10), (10, 43), (54, 43)):
        _paint(rows, endpoint, _ENDPOINT_SHAPE, 3)
        rows[endpoint[1]][endpoint[0]] = 4
    _paint(rows, (32, 32), _HUB_OUTER, 0)
    rows[32][32] = 0
    scene = extract_visual_scene(GridFrame.from_rows(rows))

    assert len(scene.mediators) == 1
    assert visual_causal._unique_affine_endpoint_group(scene, scene.mediators[0]) is None


def test_affine_reacquisition_does_not_undo_another_visible_satisfied_group() -> None:
    rows = [[5 for _ in range(64)] for _ in range(64)]
    for target in ((20, 20), (44, 44)):
        _paint(rows, target, _OFFSET_SPARSE_TARGET_RING, 14)
    for endpoint, color in (
        ((12, 20), 0),
        ((28, 20), 3),
        ((36, 44), 3),
        ((52, 44), 3),
    ):
        _paint(rows, endpoint, _ENDPOINT_SHAPE, color)
        rows[endpoint[1]][endpoint[0]] = 4
    for hub in ((20, 20), (44, 44)):
        _paint(rows, hub, _HUB_OUTER, 0)
        rows[hub[1]][hub[0]] = 0
    scene = extract_visual_scene(GridFrame.from_rows(rows))

    assert len(scene.targets) == 2
    assert len(scene.mediators) == 2
    assert not visual_causal._remaining_unsatisfied_affine_hubs(
        scene,
        completed_target_center=(20, 20),
    )
    policy = VisualCausalPolicy()
    policy._last_active_color = 0
    assert policy._activation_coordinate(scene, completed_target_center=(20, 20)) is None


def test_radial_affine_plan_uses_parser_safe_mover_footprints() -> None:
    scene = extract_visual_scene(
        _ordinary_two_group_frame(
            active=(34, 55),
            first_hub=(53, 28),
            fixed_endpoints=((60, 28), (52, 55), (46, 28), (41, 47)),
        )
    )
    movers = (
        next(item for item in scene.endpoints if item.rounded_center == (34, 55)),
        next(item for item in scene.endpoints if item.rounded_center == (52, 55)),
        next(item for item in scene.endpoints if item.rounded_center == (41, 47)),
    )

    points = _radial_plan_points(
        scene,
        target=(53, 28),
        movers=movers,
        rejected_signatures=set(),
    )

    assert points is not None
    assert Coordinate(59, 31) not in points
    assert points != (Coordinate(53, 35), Coordinate(47, 24), Coordinate(59, 24))
    assert len(points) == 3
    for index, point in enumerate(points[:-1]):
        assert visual_causal._endpoint_placement_is_open(
            scene,
            movers[index],
            x=point.x,
            y=point.y,
            prospective_color=movers[index + 1].color,
            ignored_object_refs=frozenset(item.object_ref for item in movers[: index + 2]),
        )
    centroid = (
        sum(point.x for point in points) / len(points),
        sum(point.y for point in points) / len(points),
    )
    assert math.dist(centroid, (53, 28)) <= 1.0


def test_exact_marker_collapse_reacquires_another_visible_group() -> None:
    environment = _MarkerAffineEnvironment(
        groups=[[(10, 50), (30, 50)], [(38, 52), (58, 52)]],
        targets=((20, 28), (48, 32)),
        marker_colors=(12, 14),
    )
    policy = VisualCausalPolicy()
    policy._last_active_color = environment.active_color
    before = environment.observation()

    solve = policy.select(before)
    assert solve.coordinate == Coordinate(*environment.direct_solution())

    remaining_frame = _marker_frame(
        (((38, 52), (58, 52)),),
        ((48, 32),),
        (14,),
        active_group=0,
        active_index=0,
        background=environment.background,
        active_color=environment.fixed_color,
        fixed_color=environment.fixed_color,
    )
    collapsed = Observation(
        game_id=before.game_id,
        frames=(remaining_frame,),
        state=GameStateName.NOT_FINISHED,
        levels_completed=0,
        win_levels=before.win_levels,
        available_actions=(ActionName.ACTION6,),
        returned_action=solve,
    )
    policy.accept_consequence(collapsed)

    assert policy.snapshot()["failed_plan_count"] == 0
    assert policy.snapshot()["marker_reacquire_after_local_solve"] is True
    reacquire = policy.select(collapsed)
    remaining_endpoints = {(38, 52), (58, 52)}
    assert reacquire.coordinate is not None
    assert (reacquire.coordinate.x, reacquire.coordinate.y) in remaining_endpoints
    assert "reacquire the active role" in policy._pending_prediction

    selected_index = ((38, 52), (58, 52)).index((reacquire.coordinate.x, reacquire.coordinate.y))
    reacquired_frame = _marker_frame(
        (((38, 52), (58, 52)),),
        ((48, 32),),
        (14,),
        active_group=0,
        active_index=selected_index,
        background=environment.background,
        active_color=environment.active_color,
        fixed_color=environment.fixed_color,
    )
    reacquired = Observation(
        game_id=before.game_id,
        frames=(reacquired_frame,),
        state=GameStateName.NOT_FINISHED,
        levels_completed=0,
        win_levels=before.win_levels,
        available_actions=(ActionName.ACTION6,),
        returned_action=reacquire,
    )
    policy.accept_consequence(reacquired)

    assert policy.snapshot()["failed_plan_count"] == 0
    assert policy.snapshot()["marker_reacquire_after_local_solve"] is False
    continuation = policy.select(reacquired)
    assert continuation.coordinate is not None
    assert (continuation.coordinate.x, continuation.coordinate.y) not in remaining_endpoints


def test_level_transition_frame_cannot_open_an_affine_mechanic() -> None:
    policy = VisualCausalPolicy()
    before = _observation((8, 32), (32, 32), (20, 10))
    action = policy.select(before)
    transitioned = _observation(
        (9, 30),
        (30, 30),
        (21, 9),
        levels_completed=1,
        returned_action=action,
    )

    policy.accept_consequence(transitioned)

    assert not policy.mechanics


def test_large_plan_residual_aborts_the_stale_queue() -> None:
    environment = _TwoEndpointEnvironment()
    policy = VisualCausalPolicy()
    observation = environment.observation()
    probe = policy.select(observation)
    observation = environment.step(probe)
    policy.accept_consequence(observation)
    assert policy.snapshot()["pending_plan_actions"]

    planned = policy.select(observation)
    wrong_rows = [[5 for _ in range(40)] for _ in range(40)]
    for y in range(8, 24):
        for x in range(8, 24):
            wrong_rows[y][x] = 2
    wrong = Observation(
        game_id=observation.game_id,
        frames=(GridFrame.from_rows(wrong_rows),),
        state=GameStateName.NOT_FINISHED,
        levels_completed=0,
        win_levels=2,
        available_actions=(ActionName.ACTION6,),
        returned_action=planned,
    )
    policy.accept_consequence(wrong)

    assert policy.snapshot()["pending_plan_actions"] == 0
    assert policy.snapshot()["failed_plan_count"] == 1


def test_marker_group_unlink_rejects_the_planned_signature(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    environment = _MarkerAffineEnvironment(
        groups=[[(10, 50), (30, 50)]],
        targets=((20, 28),),
        marker_colors=(12,),
    )
    policy = VisualCausalPolicy()
    policy._last_active_color = environment.active_color

    def planned_improvement(
        _scene: VisualScene,
        _group: visual_causal._EmbeddedMarkerGroup,
        endpoint: visual_causal.VisualObject,
        **_kwargs: object,
    ) -> tuple[int, Coordinate] | None:
        if endpoint.color == environment.active_color:
            return (100, Coordinate(20, 20))
        return None

    monkeypatch.setattr(
        visual_causal,
        "_best_marker_relocation",
        planned_improvement,
    )
    before = environment.observation()
    action = policy.select(before)
    assert action == ActionRequest(ActionName.ACTION6, Coordinate(20, 20))

    after_frame = _marker_frame(
        (((20, 20), (30, 50)),),
        environment.targets,
        environment.marker_colors,
        active_group=0,
        active_index=0,
        background=environment.background,
        active_color=environment.active_color,
        fixed_color=environment.fixed_color,
    )
    rows = [list(row) for row in after_frame.cells]
    rows[20][20] = environment.active_color
    after = Observation(
        game_id=before.game_id,
        frames=(GridFrame.from_rows(rows),),
        state=GameStateName.NOT_FINISHED,
        levels_completed=0,
        win_levels=before.win_levels,
        available_actions=(ActionName.ACTION6,),
        returned_action=action,
    )

    policy.accept_consequence(after)

    assert policy.receipts[-1].residual == (
        "planned marker endpoint became structurally unreadable"
    )
    assert policy.snapshot()["failed_plan_count"] == 1
    assert "marker:12:improve:20,20" in policy._failed_plan_signatures


def test_pending_coordinate_plan_respects_changed_action_space() -> None:
    environment = _TwoEndpointEnvironment()
    policy = VisualCausalPolicy()
    observation = environment.observation()
    probe = policy.select(observation)
    observation = environment.step(probe)
    policy.accept_consequence(observation)
    without_coordinate_action = _observation(
        environment.active,
        environment.anchor,
        environment.target,
        returned_action=probe,
        available_actions=(ActionName.ACTION1,),
    )

    selected = policy.select(without_coordinate_action)

    assert selected == ActionRequest(ActionName.ACTION1)
    assert policy.snapshot()["pending_plan_actions"] == 0


def test_no_readable_plan_residual_is_preserved_in_receipt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    environment = _TwoEndpointEnvironment()
    policy = VisualCausalPolicy()

    def reject_plan(_policy: VisualCausalPolicy, _mechanic: object, _scene: object) -> bool:
        return False

    monkeypatch.setattr(VisualCausalPolicy, "_install_plan", reject_plan)
    before = environment.observation()
    action = policy.select(before)
    after = environment.step(action)
    policy.accept_consequence(after)

    assert policy.receipts[-1].residual == "no readable target-relative affine plan"


def test_game_over_consequence_is_receipted_before_mandatory_reset() -> None:
    environment = _TwoEndpointEnvironment()
    policy = VisualCausalPolicy()
    observation = environment.observation()
    probe = policy.select(observation)
    observation = environment.step(probe)
    policy.accept_consequence(observation)
    learner = policy.mechanical_learner
    assert learner is not None
    retained_refs = tuple(item.ref for item in learner.ledger.active())
    assert retained_refs
    selected = policy.select(observation)
    failed = _observation(
        environment.active,
        environment.anchor,
        environment.target,
        state=GameStateName.GAME_OVER,
        returned_action=selected,
    )

    policy.accept_consequence(failed)
    policy._marker_bootstrap_attempted = True
    policy._marker_structural_actions.add("episode-local-action")
    policy._marker_structural_action_order.append("episode-local-action")
    reset = policy.select(failed)
    recovered = _observation(
        (8, 32),
        (32, 32),
        (20, 10),
        returned_action=reset,
        full_reset=True,
    )
    policy.accept_consequence(recovered)
    next_action = policy.select(recovered)

    failure_receipt = policy.receipts[-2]
    assert failure_receipt.after_state is GameStateName.GAME_OVER
    assert (
        failure_receipt.causal_action_receipt.resource_and_failure_risk.level is RiskLevel.TERMINAL
    )
    assert reset == ActionRequest(ActionName.RESET)
    assert policy.snapshot()["failed_plan_count"] == 1
    assert policy.snapshot()["marker_bootstrap_attempted"] is False
    assert policy.snapshot()["marker_structural_action_count"] == 0
    assert tuple(item.ref for item in learner.ledger.active()) == retained_refs
    assert next_action != selected


def test_failed_exploration_root_is_not_replayed_after_same_level_reset() -> None:
    frame = _palette_mismatched_target_frame(
        (25, 35),
        (43, 34),
        (((53, 28), 14), ((13, 28), 8)),
    )
    base = Observation(
        game_id=GameId("synthetic-exploration-root"),
        frames=(frame,),
        state=GameStateName.NOT_FINISHED,
        levels_completed=4,
        win_levels=6,
        available_actions=(ActionName.ACTION6,),
    )
    policy = VisualCausalPolicy()
    first = policy.select(base)
    failed = replace(
        base,
        state=GameStateName.GAME_OVER,
        returned_action=first,
    )
    policy.accept_consequence(failed)

    reset = policy.select(failed)
    recovered = replace(
        base,
        full_reset=True,
        returned_action=reset,
    )
    policy.accept_consequence(recovered)
    policy._probe_ordinal = 0
    second = policy.select(recovered)

    assert reset == ActionRequest(ActionName.RESET)
    assert first.coordinate is not None
    assert second.coordinate is not None
    assert second != first
    assert policy.snapshot()["failed_exploration_root_count"] == 1
    assert policy.snapshot()["failed_plan_count"] == 0


def test_single_failed_coordinate_root_exhausts_same_frame_explicitly() -> None:
    frame = _palette_mismatched_target_frame(
        (25, 35),
        (43, 34),
        (((53, 28), 14), ((13, 28), 8)),
    )
    base = Observation(
        game_id=GameId("synthetic-coordinate-root-exhaustion"),
        frames=(frame,),
        state=GameStateName.NOT_FINISHED,
        levels_completed=4,
        win_levels=6,
        available_actions=(ActionName.ACTION6,),
    )
    policy = VisualCausalPolicy(max_coordinate_candidates=1)
    first = policy.select(base)
    failed = replace(base, state=GameStateName.GAME_OVER, returned_action=first)
    policy.accept_consequence(failed)
    reset = policy.select(failed)
    recovered = replace(base, full_reset=True, returned_action=reset)
    policy.accept_consequence(recovered)

    with pytest.raises(
        PolicyError,
        match="all bounded coordinate-probe episode roots already failed",
    ):
        policy.select(recovered)


def test_failed_activation_root_is_not_replayed_after_same_level_reset() -> None:
    base = _observation((8, 32), (32, 32), (20, 10))
    policy = VisualCausalPolicy()
    policy._begin_level(base)
    policy._last_probe_failed = True
    first = policy.select(base)
    failed = replace(base, state=GameStateName.GAME_OVER, returned_action=first)
    policy.accept_consequence(failed)
    reset = policy.select(failed)
    recovered = replace(base, full_reset=True, returned_action=reset)
    policy.accept_consequence(recovered)
    policy._last_probe_failed = True
    second = policy.select(recovered)

    assert first.coordinate in {Coordinate(8, 32), Coordinate(32, 32)}
    assert second.coordinate in {Coordinate(8, 32), Coordinate(32, 32)}
    assert second != first
    assert policy.snapshot()["failed_exploration_root_count"] == 1


def test_level_progress_clears_failed_exploration_roots() -> None:
    frame = _palette_mismatched_target_frame(
        (25, 35),
        (43, 34),
        (((53, 28), 14), ((13, 28), 8)),
    )
    base = Observation(
        game_id=GameId("synthetic-level-root-scope"),
        frames=(frame,),
        state=GameStateName.NOT_FINISHED,
        levels_completed=4,
        win_levels=6,
        available_actions=(ActionName.ACTION6,),
    )
    policy = VisualCausalPolicy(max_coordinate_candidates=1)
    first = policy.select(base)
    failed = replace(base, state=GameStateName.GAME_OVER, returned_action=first)
    policy.accept_consequence(failed)
    reset = policy.select(failed)
    recovered = replace(base, full_reset=True, returned_action=reset)
    policy.accept_consequence(recovered)

    advanced = replace(base, levels_completed=5)
    replayed_on_new_level = policy.select(advanced)

    assert replayed_on_new_level == first
    assert policy.snapshot()["failed_exploration_root_count"] == 0


def test_marker_bootstrap_root_is_excluded_after_same_level_reset() -> None:
    environment = _MarkerAffineEnvironment(
        groups=[[(10, 50), (30, 50)]],
        targets=((20, 28),),
        marker_colors=(12,),
    )
    policy = VisualCausalPolicy(max_coordinate_candidates=1)
    base = environment.observation()
    bootstrap = policy.select(base)
    failed = replace(base, state=GameStateName.GAME_OVER, returned_action=bootstrap)
    policy.accept_consequence(failed)
    reset = policy.select(failed)
    recovered = replace(base, full_reset=True, returned_action=reset)
    policy.accept_consequence(recovered)

    with pytest.raises(
        PolicyError,
        match="all bounded coordinate-probe episode roots already failed",
    ):
        policy.select(recovered)


def test_exploration_root_capacity_fails_closed() -> None:
    frame = _palette_mismatched_target_frame(
        (25, 35),
        (43, 34),
        (((53, 28), 14), ((13, 28), 8)),
    )
    base = Observation(
        game_id=GameId("synthetic-root-capacity"),
        frames=(frame,),
        state=GameStateName.NOT_FINISHED,
        levels_completed=4,
        win_levels=6,
        available_actions=(ActionName.ACTION6,),
    )
    policy = VisualCausalPolicy()
    first = policy.select(base)
    policy._failed_exploration_roots.update(
        (f"frame-{index}", "coordinate", index, index)
        for index in range(policy._MAX_FAILED_EXPLORATION_ROOTS)
    )
    failed = replace(base, state=GameStateName.GAME_OVER, returned_action=first)
    policy.accept_consequence(failed)
    reset = policy.select(failed)
    recovered = replace(base, full_reset=True, returned_action=reset)
    policy.accept_consequence(recovered)

    assert policy.snapshot()["exploration_root_capacity_exhausted"] is True
    with pytest.raises(
        PolicyError,
        match="level-scoped exploration-root capacity exhausted",
    ):
        policy.select(recovered)


def test_level_counter_regression_fails_closed() -> None:
    base = _observation((8, 32), (32, 32), (20, 10), levels_completed=1)
    policy = VisualCausalPolicy()
    policy._begin_level(base)

    with pytest.raises(PolicyError, match="levels_completed regressed"):
        policy.select(replace(base, levels_completed=0))


def test_marker_bootstrap_accepts_unique_marked_endpoint_outside_complete_group() -> None:
    rows = [[5 for _ in range(64)] for _ in range(64)]
    _paint(rows, (6, 43), _ENDPOINT_SHAPE, 0)
    rows[43][6] = 9
    scene = extract_visual_scene(GridFrame.from_rows(rows))

    assert not _embedded_marker_groups(scene)
    assert (
        visual_causal._marker_bootstrap_active_color(
            scene,
            coordinate=Coordinate(6, 43),
        )
        == 0
    )
    assert (
        visual_causal._marker_bootstrap_active_color(
            scene,
            coordinate=Coordinate(7, 43),
        )
        is None
    )


_HIERARCHY_PARENT_TARGET = (32, 16)
_HIERARCHY_COMPOSITE_TARGETS = ((25, 18), (39, 18))


def _two_layer_affine_frame(
    groups: tuple[tuple[tuple[int, int], ...], ...] = (
        ((12, 46), (28, 46)),
        ((44, 48), (56, 48), (50, 36)),
    ),
    *,
    active_group: int = 0,
    active_index: int = 0,
    connector_color: int | None = None,
) -> GridFrame:
    """Render a generic two-child affine hierarchy plus unrelated target surfaces."""

    rows = [[5 for _ in range(64)] for _ in range(64)]
    _paint(rows, _HIERARCHY_PARENT_TARGET, _OFFSET_SPARSE_TARGET_RING, 14)
    for target in _HIERARCHY_COMPOSITE_TARGETS:
        for dx, dy in _OFFSET_SPARSE_TARGET_RING:
            rows[target[1] + dy][target[0] + dx] = 11 if dx < 0 else 13
    for group_index, endpoints in enumerate(groups):
        hub = (
            sum(x for x, _y in endpoints) // len(endpoints),
            sum(y for _x, y in endpoints) // len(endpoints),
        )
        if connector_color is not None:
            for endpoint in endpoints:
                for x, y in visual_causal._raster_line_cells(endpoint, hub):
                    rows[y][x] = connector_color
        for endpoint_index, endpoint in enumerate(endpoints):
            color = 0 if (group_index, endpoint_index) == (active_group, active_index) else 3
            _paint(rows, endpoint, _ENDPOINT_SHAPE, color)
            rows[endpoint[1]][endpoint[0]] = 4
        _paint(rows, hub, _HUB_OUTER, 0)
        rows[hub[1]][hub[0]] = 0
    return GridFrame.from_rows(rows)


_CAMPAIGN26_WEIGHTED_ORIGIN_ZLIB_B64 = (
    "eNrN142OgyAMAOAKqwfR8P6Peyg4+WktiF4OM7MwvkIRWEQVC2ZFVQXpBviOr2O855Er"
    "b/rjd+R5HiDUOFzu+YNjEqDd48nTAHsbHCs9nuq/qziBW38JAQoOOUcpQFmg4L0B4OZ"
    "M/Pir9GtyF3n45P2vNQdjGB7u+fjXintvBvJn/Py9i55OYD6CSPPvPVk/xzHA4Pb5T9"
    "6iadyFjvLbwjeNm9jVPuwb03iIuMfzH+5/MP/h+Wd3QPymyZ8V8wcIXx4DaK07fFDTt"
    "PvJF60/VADGA3w2Ntr/eP7i9KbeQvdyTL210B3gWd+cACwLlb9t5d4v1/P/soder8sBY"
    "JenV2+zZ3bPn/XP7J4OzyxNqLmjWp7ngOSdo1ryHgW/J36cY9VUUD5LwE/8FA+y/UDc"
    "TkJ95bcBXD34vAak6a8ffFqjRE88+ISre/vvfD95wqv7fMSrDk+8RKrTq4b3z7JdrPk"
    "FSUFKaQ=="
)


def _campaign26_weighted_origin_frame() -> GridFrame:
    """Decode the public-observation-only Campaign 26 row-73 fixture.

    The uncompressed 64x64 bytes have SHA-256
    ``77984fab5fbc45f6c470995b0747981c1318d914256834608bdc4288ce99f617``.
    No environment or game source is consulted by this frozen replay fixture.
    """

    raw = zlib.decompress(base64.b64decode(_CAMPAIGN26_WEIGHTED_ORIGIN_ZLIB_B64))
    assert len(raw) == 64 * 64
    assert hashlib.sha256(raw).hexdigest() == (
        "77984fab5fbc45f6c470995b0747981c1318d914256834608bdc4288ce99f617"
    )
    return GridFrame.from_rows(tuple(tuple(raw[y * 64 : (y + 1) * 64]) for y in range(64)))


_CAMPAIGN35_RESIDUAL_FOREGROUND_AFTER_A3_ZLIB_B64 = (
    "eNrdl2FvxCAIhhGPTtPF//9zZ12bswqVyvXDRpPmwvm8CIhJCXejk2FnxC+gZ/he4zmeJHuSP/4nGT8L/HoSrXP8gVMlo"
    "OfpjdcCZQ3Z7A7Pxb9laYDH/AwErnEaCdAANwncsK/8tPZdvYc4CQINDiEIOC/Q4pkPhjQFfqneA55PYNHhZQOsf9Hhf8oi"
    "BeUUJun4B+UQJ2l6gvISSQ9kb4xvzN9c/8n7G/E/8N7Ge+8tvPevTSACzMd3LmYeDPkfPEzWP24Czmk2AevK9C/z2435Ggp"
    "A5lep/4r4l7wifwC44Fnz7QbunV/xgOn4/YDNz48xvjxgWl7qao8nbiWAINDxKXErZZ4GfEncFd65vhQMf0qgTLY78s8/3bk"
    "VffUyf9X4xjMqf9/42oNDnmm8r4Nb7m/8DI/zOMI8jzd45iMS3zwqvj/bdbvnB8spS9I="
)


def _campaign35_residual_foreground_after_a3_frame() -> GridFrame:
    """Decode the official Campaign 35 consequence after its third setup action.

    The uncompressed 64x64 public-development observation has SHA-256
    ``10502941cabb15b6379a2995c39f0e1b67b5225349f91bfa007d72866cd78688``.
    It is recording row 240 from the frozen public-development Campaign 35
    artifact set.  No game
    source or environment is consulted by this regression fixture.
    """

    raw = zlib.decompress(base64.b64decode(_CAMPAIGN35_RESIDUAL_FOREGROUND_AFTER_A3_ZLIB_B64))
    assert len(raw) == 64 * 64
    assert hashlib.sha256(raw).hexdigest() == (
        "10502941cabb15b6379a2995c39f0e1b67b5225349f91bfa007d72866cd78688"
    )
    return GridFrame.from_rows(tuple(tuple(raw[y * 64 : (y + 1) * 64]) for y in range(64)))


@dataclass
class _ProjectedWeightedHierarchyEnvironment:
    """Replay generic endpoint placement against one frozen public observation."""

    scene: VisualScene
    hierarchy: visual_causal._AffineHierarchy
    carrier_source_supports: tuple[visual_causal._HierarchySourceSupport, ...] = ()
    positions: dict[str, tuple[int, int]] = field(init=False)
    colors: dict[str, int] = field(init=False)

    def __post_init__(self) -> None:
        self.positions = {
            endpoint.object_ref: endpoint.rounded_center
            for child in self.hierarchy.children
            for endpoint in child.endpoints
        }
        self.colors = {
            endpoint.object_ref: endpoint.color
            for child in self.hierarchy.children
            for endpoint in child.endpoints
        }

    def observation(self, *, returned_action: ActionRequest | None = None) -> Observation:
        projected = (
            visual_causal._carrier_source_residual_foreground_projected_scene(
                self.scene,
                self.hierarchy,
                self.carrier_source_supports,
                positions=self.positions,
                colors=self.colors,
            )
            if self.carrier_source_supports
            else visual_causal._hierarchy_projected_scene(
                self.scene,
                self.hierarchy,
                positions=self.positions,
                colors=self.colors,
            )
        )
        return Observation(
            game_id=GameId("synthetic-weighted-hierarchy-replay"),
            frames=(GridFrame(projected.cells),),
            state=GameStateName.NOT_FINISHED,
            levels_completed=4,
            win_levels=6,
            available_actions=(ActionName.ACTION6,),
            returned_action=returned_action,
        )

    def step(self, action: ActionRequest) -> Observation:
        assert action.name is ActionName.ACTION6
        assert action.coordinate is not None
        coordinate = (action.coordinate.x, action.coordinate.y)
        active_refs = tuple(
            ref for ref, color in self.colors.items() if color == self.hierarchy.active_color
        )
        assert len(active_refs) == 1
        active_ref = active_refs[0]
        selected_refs = tuple(ref for ref, center in self.positions.items() if center == coordinate)
        if selected_refs and selected_refs != (active_ref,):
            assert len(selected_refs) == 1
            selected_ref = selected_refs[0]
            self.colors[active_ref], self.colors[selected_ref] = (
                self.colors[selected_ref],
                self.colors[active_ref],
            )
        else:
            self.positions[active_ref] = coordinate
        return self.observation(returned_action=action)


@dataclass
class _TwoLayerAffineEnvironment:
    """Synthetic game that wins only on a nondegenerate second-order centroid."""

    training_active: tuple[int, int] = (8, 32)
    training_anchor: tuple[int, int] = (32, 32)
    training_target: tuple[int, int] = (20, 10)
    groups: list[list[tuple[int, int]]] = field(
        default_factory=lambda: [
            [(12, 46), (28, 46)],
            [(44, 48), (56, 48), (50, 36)],
        ]
    )
    active_group: int = 0
    active_index: int = 0
    levels_completed: int = 0
    state: GameStateName = GameStateName.NOT_FINISHED
    win_on_hierarchy: bool = True
    connector_color: int | None = None
    hierarchy_actions: list[Coordinate] = field(default_factory=list)
    unsafe_hierarchy_actions: list[Coordinate] = field(default_factory=list)
    unreadable_hierarchy_actions: list[Coordinate] = field(default_factory=list)
    protected_regions: tuple[frozenset[tuple[int, int]], ...] = ()
    target_surface_signature: tuple[tuple[tuple[int, int], frozenset[tuple[int, int]]], ...] = ()

    def observation(self, returned_action: ActionRequest | None = None) -> Observation:
        if self.levels_completed == 0:
            frame = _frame(self.training_active, self.training_anchor, self.training_target)
        else:
            frame = _two_layer_affine_frame(
                tuple(tuple(group) for group in self.groups),
                active_group=self.active_group,
                active_index=self.active_index,
                connector_color=self.connector_color,
            )
        return Observation(
            game_id=GameId("synthetic-two-layer-affine"),
            frames=(frame,),
            state=self.state,
            levels_completed=self.levels_completed,
            win_levels=2,
            available_actions=(ActionName.ACTION6,),
            returned_action=returned_action,
        )

    def _hierarchy_centers(self) -> tuple[tuple[int, int], ...]:
        return tuple(
            (
                sum(x for x, _y in endpoints) // len(endpoints),
                sum(y for _x, y in endpoints) // len(endpoints),
            )
            for endpoints in self.groups
        )

    def _hierarchy_dynamic_footprint(self) -> frozenset[tuple[int, int]]:
        cells: set[tuple[int, int]] = set()
        for endpoints, hub in zip(self.groups, self._hierarchy_centers(), strict=True):
            cells.update((x + dx, y + dy) for x, y in endpoints for dx, dy in _ENDPOINT_SHAPE)
            cells.update(endpoints)
            cells.update((hub[0] + dx, hub[1] + dy) for dx, dy in _HUB_OUTER)
            cells.add(hub)
            for endpoint in endpoints:
                cells.update(visual_causal._raster_line_cells(endpoint, hub))
        return frozenset(cells)

    def _step_training(self, clicked: tuple[int, int], action: ActionRequest) -> Observation:
        if math.dist(clicked, self.training_anchor) <= 2.5:
            self.training_active, self.training_anchor = (
                self.training_anchor,
                self.training_active,
            )
        else:
            self.training_active = clicked
        hub = (
            (self.training_active[0] + self.training_anchor[0]) / 2,
            (self.training_active[1] + self.training_anchor[1]) / 2,
        )
        if math.dist(hub, self.training_target) <= 1.0:
            self.levels_completed = 1
            scene = extract_visual_scene(_two_layer_affine_frame())
            visible_targets = visual_causal._visible_target_regions(scene)
            self.protected_regions = tuple(region for _center, region in visible_targets)
            self.target_surface_signature = tuple(sorted(visible_targets, key=lambda item: item[0]))
        return self.observation(returned_action=action)

    def step(self, action: ActionRequest) -> Observation:
        assert action.coordinate is not None
        clicked = (action.coordinate.x, action.coordinate.y)
        if self.levels_completed == 0:
            return self._step_training(clicked, action)

        selected: tuple[int, int] | None = None
        for group_index, endpoints in enumerate(self.groups):
            for endpoint_index, endpoint in enumerate(endpoints):
                if math.dist(clicked, endpoint) <= 2.25:
                    selected = (group_index, endpoint_index)
                    break
            if selected is not None:
                break
        if selected is not None and selected != (self.active_group, self.active_index):
            self.active_group, self.active_index = selected
        else:
            self.groups[self.active_group][self.active_index] = clicked

        self.hierarchy_actions.append(action.coordinate)
        dynamic = self._hierarchy_dynamic_footprint()
        if any(dynamic & region for region in self.protected_regions):
            self.unsafe_hierarchy_actions.append(action.coordinate)

        returned_scene = extract_visual_scene(
            _two_layer_affine_frame(
                tuple(tuple(group) for group in self.groups),
                active_group=self.active_group,
                active_index=self.active_index,
            )
        )
        returned_targets = tuple(
            sorted(
                visual_causal._visible_target_regions(returned_scene),
                key=lambda item: item[0],
            )
        )
        returned_hierarchy = visual_causal._unique_affine_hierarchy(
            returned_scene,
            active_color=0,
        )
        if (
            returned_targets != self.target_surface_signature
            or returned_hierarchy is None
            or sorted(len(child.endpoints) for child in returned_hierarchy.children) != [2, 3]
        ):
            self.unreadable_hierarchy_actions.append(action.coordinate)

        hubs = self._hierarchy_centers()
        exact_child_centers = all(
            sum(x for x, _y in endpoints) == len(endpoints) * hub[0]
            and sum(y for _x, y in endpoints) == len(endpoints) * hub[1]
            for endpoints, hub in zip(self.groups, hubs, strict=True)
        )
        if self.win_on_hierarchy and (
            exact_child_centers
            and len(set(hubs)) == len(hubs)
            and sum(x for x, _y in hubs) == len(hubs) * _HIERARCHY_PARENT_TARGET[0]
            and sum(y for _x, y in hubs) == len(hubs) * _HIERARCHY_PARENT_TARGET[1]
            and not self.unsafe_hierarchy_actions
            and not self.unreadable_hierarchy_actions
        ):
            self.levels_completed = 2
            self.state = GameStateName.WIN
        return self.observation(returned_action=action)


def _reach_two_layer_hierarchy(
    environment: _TwoLayerAffineEnvironment,
    policy: VisualCausalPolicy,
) -> Observation:
    observation = environment.observation()
    for _ in range(12):
        action = policy.select(observation)
        observation = environment.step(action)
        policy.accept_consequence(observation)
        if observation.levels_completed == 1:
            break
    assert observation.levels_completed == 1
    return observation


def _install_joint_hierarchy_for_test(
    policy: VisualCausalPolicy,
    observation: Observation,
) -> visual_causal._AffineHierarchy:
    """Exercise the retained joint mechanism independently of policy priority."""

    scene = extract_visual_scene(observation.frames[-1])
    hierarchy = visual_causal._unique_affine_hierarchy(scene, active_color=0)
    assert hierarchy is not None
    plan = visual_causal._hierarchy_joint_layout(
        scene,
        hierarchy,
        rejected_signatures=set(),
    )
    assert plan is not None
    policy._install_hierarchy_plan(
        plan,
        relation_key=visual_causal._hierarchy_relation_key(
            scene,
            hierarchy,
            level_index=observation.levels_completed,
        ),
    )
    return hierarchy


def _replace_observation_cell(
    observation: Observation,
    *,
    coordinate: tuple[int, int],
    value: int,
) -> Observation:
    """Return one observation with a single explicit protected-board mutation."""

    x, y = coordinate
    rows = [list(row) for row in observation.frames[-1].cells]
    rows[y][x] = value
    return replace(observation, frames=(GridFrame.from_rows(rows),))


@lru_cache(maxsize=1)
def _external_residual_chain_fixture() -> tuple[
    GridFrame,
    VisualScene,
    visual_causal._AffineHierarchy,
    visual_causal._CompositeBridgeRelation,
    visual_causal._ResidualLinkedHierarchyRelation,
    visual_causal._ExternalResidualLinkedHierarchyRelation,
    visual_causal._HierarchyPlan,
]:
    """Return one immutable observation-derived external-chain fixture and plan."""

    frame = _campaign26_weighted_origin_frame()
    scene = extract_visual_scene(frame)
    hierarchy = visual_causal._unique_affine_hierarchy(scene, active_color=0)
    assert hierarchy is not None
    bridge = visual_causal._composite_bridge_relation(scene, hierarchy, level_index=4)
    mixed = visual_causal._residual_linked_hierarchy_relation(scene, hierarchy, level_index=4)
    assert bridge is not None
    assert mixed is not None
    assert (
        visual_causal._external_residual_linked_hierarchy_relation(
            scene,
            hierarchy,
            level_index=4,
            rejected_mixed_relation_keys=set(),
        )
        is None
    )
    external = visual_causal._external_residual_linked_hierarchy_relation(
        scene,
        hierarchy,
        level_index=4,
        rejected_mixed_relation_keys={mixed.relation_key},
    )
    assert external is not None
    plan = visual_causal._external_residual_linked_hierarchy_plan(
        scene,
        hierarchy,
        external,
        rejected_signatures=set(),
    )
    assert plan is not None
    return frame, scene, hierarchy, bridge, mixed, external, plan


@lru_cache(maxsize=1)
def _raw_matching_composite_fixture() -> tuple[
    GridFrame,
    VisualScene,
    visual_causal._AffineHierarchy,
    visual_causal._CompositeBridgeRelation,
    visual_causal._ResidualLinkedHierarchyRelation,
    visual_causal._ExternalResidualLinkedHierarchyRelation,
    visual_causal._RawMatchingCompositeHierarchyRelation,
    visual_causal._HierarchyPlan,
]:
    """Return the bounded post-external containment hypothesis and exact plan."""

    frame, scene, hierarchy, bridge, mixed, external, _external_plan = (
        _external_residual_chain_fixture()
    )
    assert (
        visual_causal._raw_matching_composite_hierarchy_relation(
            scene,
            hierarchy,
            level_index=4,
            rejected_mixed_relation_keys={mixed.relation_key},
            rejected_external_relation_keys=set(),
        )
        is None
    )
    relation = visual_causal._raw_matching_composite_hierarchy_relation(
        scene,
        hierarchy,
        level_index=4,
        rejected_mixed_relation_keys={mixed.relation_key},
        rejected_external_relation_keys={external.relation_key},
    )
    assert relation is not None
    plan = visual_causal._raw_matching_composite_hierarchy_plan(
        scene,
        hierarchy,
        relation,
        rejected_signatures=set(),
    )
    assert plan is not None
    return frame, scene, hierarchy, bridge, mixed, external, relation, plan


@lru_cache(maxsize=1)
def _external_own_composite_fixture() -> tuple[
    GridFrame,
    VisualScene,
    visual_causal._AffineHierarchy,
    visual_causal._CompositeBridgeRelation,
    visual_causal._ResidualLinkedHierarchyRelation,
    visual_causal._ExternalResidualLinkedHierarchyRelation,
    visual_causal._RawMatchingCompositeHierarchyRelation,
    visual_causal._ExternalOwnCompositeHierarchyRelation,
    visual_causal._HierarchyPlan,
]:
    """Return the sole bounded post-raw-matching recombination and exact plan."""

    frame, scene, hierarchy, bridge, mixed, external, raw_matching, _raw_plan = (
        _raw_matching_composite_fixture()
    )
    assert (
        visual_causal._external_own_composite_hierarchy_relation(
            scene,
            hierarchy,
            level_index=4,
            rejected_bridge_relation_keys={bridge.relation_key},
            rejected_mixed_relation_keys={mixed.relation_key},
            rejected_external_relation_keys={external.relation_key},
            rejected_raw_matching_relation_keys=set(),
        )
        is None
    )
    relation = visual_causal._external_own_composite_hierarchy_relation(
        scene,
        hierarchy,
        level_index=4,
        rejected_bridge_relation_keys={bridge.relation_key},
        rejected_mixed_relation_keys={mixed.relation_key},
        rejected_external_relation_keys={external.relation_key},
        rejected_raw_matching_relation_keys={raw_matching.relation_key},
    )
    assert relation is not None
    plan = visual_causal._external_own_composite_hierarchy_plan(
        scene,
        hierarchy,
        relation,
        rejected_signatures=set(),
    )
    assert plan is not None
    return (
        frame,
        scene,
        hierarchy,
        bridge,
        mixed,
        external,
        raw_matching,
        relation,
        plan,
    )


@lru_cache(maxsize=1)
def _carrier_source_occlusion_fixture() -> tuple[
    GridFrame,
    VisualScene,
    visual_causal._AffineHierarchy,
    visual_causal._CompositeBridgeRelation,
    visual_causal._ResidualLinkedHierarchyRelation,
    visual_causal._ExternalResidualLinkedHierarchyRelation,
    visual_causal._RawMatchingCompositeHierarchyRelation,
    visual_causal._ExternalOwnCompositeHierarchyRelation,
    visual_causal._CarrierSourceOcclusionHierarchyRelation,
    visual_causal._HierarchyPlan,
]:
    """Return the final one-shot carrier-source discriminator and exact plan."""

    (
        frame,
        scene,
        hierarchy,
        bridge,
        mixed,
        external,
        raw_matching,
        external_own,
        _external_own_plan,
    ) = _external_own_composite_fixture()
    relation = visual_causal._carrier_source_occlusion_hierarchy_relation(
        scene,
        hierarchy,
        level_index=4,
        rejected_bridge_relation_keys={bridge.relation_key},
        rejected_mixed_relation_keys={mixed.relation_key},
        rejected_external_relation_keys={external.relation_key},
        rejected_raw_matching_relation_keys={raw_matching.relation_key},
        rejected_external_own_relation_keys={external_own.relation_key},
    )
    assert relation is not None
    plan = visual_causal._carrier_source_occlusion_hierarchy_plan(
        scene,
        hierarchy,
        relation,
        rejected_signatures=set(),
    )
    assert plan is not None
    return (
        frame,
        scene,
        hierarchy,
        bridge,
        mixed,
        external,
        raw_matching,
        external_own,
        relation,
        plan,
    )


def _seed_external_chain_prerequisites(
    policy: VisualCausalPolicy,
    scene: VisualScene,
    hierarchy: visual_causal._AffineHierarchy,
    bridge: visual_causal._CompositeBridgeRelation,
    mixed: visual_causal._ResidualLinkedHierarchyRelation,
) -> None:
    """Record only the generic earlier-family terminal rejections."""

    raw_relation_key = visual_causal._hierarchy_relation_key(
        scene,
        hierarchy,
        level_index=4,
    )
    child_keys = frozenset(
        visual_causal._child_isolation_hypothesis_key(
            scene,
            child,
            relation_key=raw_relation_key,
        )
        for child in hierarchy.children
    )
    policy._failed_child_isolation_hypothesis_keys.update(child_keys)
    policy._child_isolation_hypotheses_by_relation[raw_relation_key] = child_keys
    policy._failed_hierarchy_relation_keys.add(raw_relation_key)
    policy._failed_weighted_hierarchy_relation_keys.add(raw_relation_key)
    policy._failed_visible_node_hierarchy_relation_keys.add(raw_relation_key)
    policy._failed_bridge_hierarchy_relation_keys.add(bridge.relation_key)
    policy._failed_residual_linked_hierarchy_relation_keys.add(mixed.relation_key)
    policy._failed_external_residual_linked_hierarchy_relation_keys.clear()


def _seed_raw_matching_composite_prerequisites(
    policy: VisualCausalPolicy,
    scene: VisualScene,
    hierarchy: visual_causal._AffineHierarchy,
    bridge: visual_causal._CompositeBridgeRelation,
    mixed: visual_causal._ResidualLinkedHierarchyRelation,
    external: visual_causal._ExternalResidualLinkedHierarchyRelation,
) -> None:
    """Record the exact earlier-family rejections required by the bounded revision."""

    _seed_external_chain_prerequisites(policy, scene, hierarchy, bridge, mixed)
    policy._failed_external_residual_linked_hierarchy_relation_keys.add(external.relation_key)
    policy._failed_raw_matching_composite_hierarchy_relation_keys.clear()


def _seed_external_own_composite_prerequisites(
    policy: VisualCausalPolicy,
    scene: VisualScene,
    hierarchy: visual_causal._AffineHierarchy,
    bridge: visual_causal._CompositeBridgeRelation,
    mixed: visual_causal._ResidualLinkedHierarchyRelation,
    external: visual_causal._ExternalResidualLinkedHierarchyRelation,
    raw_matching: visual_causal._RawMatchingCompositeHierarchyRelation,
) -> None:
    """Record exactly the four prior relation failures needed by this family."""

    _seed_raw_matching_composite_prerequisites(
        policy,
        scene,
        hierarchy,
        bridge,
        mixed,
        external,
    )
    policy._failed_raw_matching_composite_hierarchy_relation_keys.add(raw_matching.relation_key)
    policy._failed_external_own_composite_hierarchy_relation_keys.clear()


def _seed_carrier_source_occlusion_prerequisites(
    policy: VisualCausalPolicy,
    scene: VisualScene,
    hierarchy: visual_causal._AffineHierarchy,
    bridge: visual_causal._CompositeBridgeRelation,
    mixed: visual_causal._ResidualLinkedHierarchyRelation,
    external: visual_causal._ExternalResidualLinkedHierarchyRelation,
    raw_matching: visual_causal._RawMatchingCompositeHierarchyRelation,
    external_own: visual_causal._ExternalOwnCompositeHierarchyRelation,
) -> None:
    """Record exactly the five prior failures needed by the one-shot family."""

    _seed_external_own_composite_prerequisites(
        policy,
        scene,
        hierarchy,
        bridge,
        mixed,
        external,
        raw_matching,
    )
    policy._failed_external_own_composite_hierarchy_relation_keys.add(external_own.relation_key)
    policy._failed_carrier_source_occlusion_hierarchy_relation_keys.clear()


def test_two_layer_affine_hierarchy_is_an_exact_disjoint_cover() -> None:
    scene = extract_visual_scene(_two_layer_affine_frame())

    hierarchy = visual_causal._unique_affine_hierarchy(scene, active_color=0)

    assert hierarchy is not None
    assert hierarchy.target.rounded_center == _HIERARCHY_PARENT_TARGET
    assert sorted(len(child.endpoints) for child in hierarchy.children) == [2, 3]
    endpoint_refs = [
        endpoint.object_ref for child in hierarchy.children for endpoint in child.endpoints
    ]
    assert len(endpoint_refs) == len(set(endpoint_refs)) == len(scene.endpoints)
    assert {child.mediator.object_ref for child in hierarchy.children} == {
        mediator.object_ref for mediator in scene.mediators
    }


def test_hierarchy_joint_layout_is_distinct_and_protects_every_visible_target() -> None:
    scene = extract_visual_scene(_two_layer_affine_frame())
    hierarchy = visual_causal._unique_affine_hierarchy(scene, active_color=0)
    assert hierarchy is not None
    protected = visual_causal._visible_target_regions(scene)
    protected_centers = {center for center, _region in protected}
    assert {
        _HIERARCHY_PARENT_TARGET,
        *_HIERARCHY_COMPOSITE_TARGETS,
    } <= protected_centers

    plan = visual_causal._hierarchy_joint_layout(
        scene,
        hierarchy,
        rejected_signatures=set(),
    )

    assert plan is not None
    assert len(set(plan.supports)) == len(hierarchy.children)
    assert (
        sum(x for x, _y in plan.supports) == len(plan.supports) * hierarchy.target.rounded_center[0]
    )
    assert (
        sum(y for _x, y in plan.supports) == len(plan.supports) * hierarchy.target.rounded_center[1]
    )
    assert plan.signature
    for support in plan.supports:
        assert all(support not in region for _center, region in protected)
    for planned in plan.actions:
        assert all(
            (planned.coordinate.x, planned.coordinate.y) not in region
            for _center, region in protected
        )


def test_policy_completes_two_layer_affine_hierarchy_without_flat_target_collapse() -> None:
    environment = _TwoLayerAffineEnvironment()
    policy = VisualCausalPolicy(max_coordinate_candidates=8)
    observation = environment.observation()

    for _ in range(12):
        action = policy.select(observation)
        observation = environment.step(action)
        policy.accept_consequence(observation)
        if observation.levels_completed == 1:
            break
    assert observation.levels_completed == 1

    hierarchy_scene = extract_visual_scene(observation.frames[-1])
    hierarchy = visual_causal._unique_affine_hierarchy(hierarchy_scene, active_color=0)
    assert hierarchy is not None
    active_child = next(
        child
        for child in hierarchy.children
        if any(endpoint.color == 0 for endpoint in child.endpoints)
    )
    ordered_movers = tuple(sorted(active_child.endpoints, key=lambda item: item.color != 0))
    harmful_flat = _radial_plan_points(
        hierarchy_scene,
        target=hierarchy.target.rounded_center,
        movers=ordered_movers,
        rejected_signatures=set(),
    )
    assert harmful_flat is not None

    _install_joint_hierarchy_for_test(policy, observation)
    first_hierarchy_action = policy.select(observation)
    assert first_hierarchy_action.coordinate not in {
        harmful_flat[0],
        Coordinate(60, 28),
        Coordinate(57, 18),
    }
    assert "child-support" in policy._pending_prediction or any(
        mechanic_ref.startswith("affine-hierarchy-mechanic:")
        for mechanic_ref in policy._pending_mechanic_refs
    )

    for _ in range(20):
        observation = environment.step(first_hierarchy_action)
        policy.accept_consequence(observation)
        if observation.state is GameStateName.WIN:
            break
        first_hierarchy_action = policy.select(observation)

    assert observation.state is GameStateName.WIN
    assert observation.levels_completed == observation.win_levels == 2
    assert not environment.unsafe_hierarchy_actions
    assert not environment.unreadable_hierarchy_actions
    hubs = environment._hierarchy_centers()
    assert len(set(hubs)) == 2
    assert (
        sum(x for x, _y in hubs),
        sum(y for _x, y in hubs),
    ) == (2 * _HIERARCHY_PARENT_TARGET[0], 2 * _HIERARCHY_PARENT_TARGET[1])
    assert policy.snapshot()["hierarchy_active"] is False


def test_weighted_hierarchy_transient_bridge_and_recovery_replay_exactly() -> None:
    frame = _campaign26_weighted_origin_frame()
    scene = extract_visual_scene(frame)
    hierarchy = visual_causal._unique_affine_hierarchy(scene, active_color=0)
    assert hierarchy is not None
    assert [(child.arity, child.mediator.rounded_center) for child in hierarchy.children] == [
        (2, (34, 34)),
        (3, (42, 52)),
    ]
    relation_key = visual_causal._hierarchy_relation_key(
        scene,
        hierarchy,
        level_index=4,
    )
    search_budget = visual_causal._HierarchySearchBudget(visual_causal._MAX_HIERARCHY_SEARCH_BUDGET)
    plan = visual_causal._hierarchy_weighted_layout(
        scene,
        hierarchy,
        rejected_signatures=set(),
        search_budget=search_budget,
    )
    assert plan is not None
    assert search_budget.remaining >= 94_000
    assert plan.signature.startswith("affine-weighted-hierarchy:")
    assert plan.supports == ((47, 19), (57, 34))
    assert plan.support_weights == (2, 3)
    assert [(action.coordinate.x, action.coordinate.y) for action in plan.actions] == [
        (42, 16),
        (43, 34),
        (52, 22),
        (52, 55),
        (60, 29),
        (41, 47),
        (60, 39),
        (34, 55),
        (51, 34),
    ]
    target = hierarchy.target.rounded_center
    assert (
        sum(
            weight * support[0]
            for weight, support in zip(plan.support_weights, plan.supports, strict=True)
        )
        == sum(plan.support_weights) * target[0]
    )
    assert (
        sum(
            weight * support[1]
            for weight, support in zip(plan.support_weights, plan.supports, strict=True)
        )
        == sum(plan.support_weights) * target[1]
    )
    assert all(action.expected_visible_endpoint_count == 5 for action in plan.actions)
    transient_indices = [
        index
        for index, action in enumerate(plan.actions)
        if action.expected_visible_mediator_count == 1
    ]
    assert transient_indices == [6, 7]
    assert plan.actions[-1].expected_visible_mediator_count == 2

    environment = _ProjectedWeightedHierarchyEnvironment(scene, hierarchy)
    initial_positions = dict(environment.positions)
    initial_colors = dict(environment.colors)
    initial_hash = visual_causal._child_isolation_protected_raster_hash(scene)
    assert initial_hash == (
        "sha256:e2bab5b0964c3c52fc01c81ba29791531136a4c95cad347ab7466b9ce67228f6"
    )
    policy = VisualCausalPolicy(max_coordinate_candidates=8)
    policy._level_index = 4
    policy._last_active_color = hierarchy.active_color
    policy._failed_hierarchy_relation_keys.add(relation_key)
    policy._install_hierarchy_plan(plan, relation_key=relation_key)
    observation = environment.observation()

    for index, expected in enumerate(plan.actions):
        action = policy.select(observation)
        assert action.coordinate == expected.coordinate
        observation = environment.step(action)
        returned_scene = extract_visual_scene(observation.frames[-1])
        assert visual_causal._child_isolation_protected_raster_hash(returned_scene) == (
            expected.expected_child_protected_raster_hash
        )
        assert len(returned_scene.endpoints) == expected.expected_visible_endpoint_count
        assert len(returned_scene.mediators) == expected.expected_visible_mediator_count
        if index in transient_indices:
            assert (
                visual_causal._unique_affine_hierarchy(
                    returned_scene,
                    active_color=hierarchy.active_color,
                )
                is None
            )
        policy.accept_consequence(observation)
        assert policy._hierarchy_lineage_lost is None

    terminal_scene = extract_visual_scene(observation.frames[-1])
    assert visual_causal._child_isolation_protected_raster_hash(terminal_scene) == (
        "sha256:a3a625a0beb6993982533da09f99fc0a3aee4aa8a38bd230077cb259502cea14"
    )
    assert policy._failed_hierarchy_relation_keys == {relation_key}
    assert policy._failed_weighted_hierarchy_relation_keys == {relation_key}
    snapshot = policy.snapshot()
    assert snapshot["hierarchy_relation_rejected_count"] == 1
    assert snapshot["hierarchy_hypothesis_rejected_count"] == 2
    assert snapshot["hierarchy_recovery_active"] is True
    assert snapshot["hierarchy_recovery_signature"].startswith(
        "affine-weighted-hierarchy-recovery:"
    )
    assert len(policy._plan) == len(plan.recovery_actions)

    for expected in plan.recovery_actions:
        action = policy.select(observation)
        assert action.coordinate == expected.coordinate
        assert policy._pending_plan_signature is not None
        assert policy._pending_plan_signature.startswith("affine-weighted-hierarchy-recovery:")
        observation = environment.step(action)
        returned_scene = extract_visual_scene(observation.frames[-1])
        assert visual_causal._child_isolation_protected_raster_hash(returned_scene) == (
            expected.expected_child_protected_raster_hash
        )
        assert len(returned_scene.endpoints) == expected.expected_visible_endpoint_count
        assert len(returned_scene.mediators) == expected.expected_visible_mediator_count
        policy.accept_consequence(observation)
        assert policy._hierarchy_lineage_lost is None

    restored_scene = extract_visual_scene(observation.frames[-1])
    assert visual_causal._child_isolation_protected_raster_hash(restored_scene) == initial_hash
    assert environment.positions == initial_positions
    assert environment.colors == initial_colors
    assert policy.snapshot()["hierarchy_active"] is False
    assert policy.snapshot()["hierarchy_recovery_active"] is False
    assert policy.snapshot()["pending_plan_actions"] == 0
    assert policy.receipts[-1].residual == (
        "exact pre-hypothesis hierarchy restored after joint sufficiency failed"
    )


def test_composite_bridge_relation_and_plan_replay_exactly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    frame = _campaign26_weighted_origin_frame()
    scene = extract_visual_scene(frame)
    hierarchy = visual_causal._unique_affine_hierarchy(scene, active_color=0)
    assert hierarchy is not None

    relation = visual_causal._composite_bridge_relation(
        scene,
        hierarchy,
        level_index=4,
    )
    assert relation is not None
    assert tuple(
        (child.arity, example.target.rounded_center) for child, example in relation.assignments
    ) == ((2, (13, 28)), (3, (48, 9)))
    assert tuple(
        tuple(source.center for source in example.sources)
        for _child, example in relation.assignments
    ) == (((14, 40), (33, 19)), ((20, 53), (56, 43)))

    plan = visual_causal._bridge_hierarchy_plan(
        scene,
        hierarchy,
        relation,
        rejected_signatures=set(),
    )
    assert plan is not None
    assert plan.signature.startswith("affine-bridge-hierarchy:")
    assert plan.supports == ((13, 28), (48, 9))
    assert len(plan.actions) == len(plan.recovery_actions) == 9

    environment = _ProjectedWeightedHierarchyEnvironment(scene, hierarchy)
    observation = environment.observation()
    for planned in plan.actions:
        current_scene = extract_visual_scene(observation.frames[-1])
        assert visual_causal._hierarchy_planned_click_is_safe(
            current_scene,
            planned,
            active_color=hierarchy.active_color,
        )
        action = ActionRequest(ActionName.ACTION6, planned.coordinate)
        observation = environment.step(action)
        returned_scene = extract_visual_scene(observation.frames[-1])
        assert visual_causal._child_isolation_protected_raster_hash(returned_scene) == (
            planned.expected_child_protected_raster_hash
        )
    terminal_scene = extract_visual_scene(observation.frames[-1])
    terminal_targets = {
        item.rounded_center
        for item, _signature in visual_causal._composite_sparse_targets(terminal_scene)
    }
    assert (13, 28) not in terminal_targets
    assert (48, 9) not in terminal_targets
    assert any(target.rounded_center == (53, 28) for target in terminal_scene.targets)

    for planned in plan.recovery_actions:
        current_scene = extract_visual_scene(observation.frames[-1])
        assert visual_causal._hierarchy_planned_click_is_safe(
            current_scene,
            planned,
            active_color=hierarchy.active_color,
        )
        action = ActionRequest(ActionName.ACTION6, planned.coordinate)
        observation = environment.step(action)
        returned_scene = extract_visual_scene(observation.frames[-1])
        assert visual_causal._child_isolation_protected_raster_hash(returned_scene) == (
            planned.expected_child_protected_raster_hash
        )
    assert observation.frames[-1].cells == frame.cells

    policy_environment = _ProjectedWeightedHierarchyEnvironment(scene, hierarchy)
    policy_observation = policy_environment.observation()
    policy = VisualCausalPolicy(max_coordinate_candidates=8)
    policy._level_index = 4
    policy._last_active_color = hierarchy.active_color
    policy._ensure_learner(policy_observation)
    policy._install_hierarchy_plan(plan, relation_key=relation.relation_key)
    for action_index, expected in enumerate(plan.actions):
        action = policy.select(policy_observation)
        assert action.coordinate == expected.coordinate
        policy_observation = policy_environment.step(action)
        policy.accept_consequence(policy_observation)
        if action_index == 2:
            assert relation.relation_key not in policy._failed_bridge_hierarchy_relation_keys
            assert len(policy._plan) == 6
    assert relation.relation_key in policy._failed_bridge_hierarchy_relation_keys
    assert len(policy._plan) == 9
    for expected in plan.recovery_actions:
        action = policy.select(policy_observation)
        assert action.coordinate == expected.coordinate
        policy_observation = policy_environment.step(action)
        policy.accept_consequence(policy_observation)
    assert policy_observation.frames[-1].cells == frame.cells
    assert policy.snapshot()["hierarchy_bridge_relation_rejected_count"] == 1
    assert policy.snapshot()["hierarchy_recovery_active"] is False

    assert policy._affine_ledger_ref is not None
    raw_relation_key = visual_causal._hierarchy_relation_key(
        scene,
        hierarchy,
        level_index=4,
    )
    child_hypothesis_keys = {
        visual_causal._child_isolation_hypothesis_key(
            scene,
            child,
            relation_key=raw_relation_key,
        )
        for child in hierarchy.children
    }

    def restore_prior_family_failures() -> None:
        policy._failed_child_isolation_hypothesis_keys.clear()
        policy._failed_child_isolation_hypothesis_keys.update(child_hypothesis_keys)
        policy._failed_hierarchy_relation_keys.clear()
        policy._failed_hierarchy_relation_keys.add(raw_relation_key)
        policy._failed_weighted_hierarchy_relation_keys.clear()
        policy._failed_weighted_hierarchy_relation_keys.add(raw_relation_key)
        policy._failed_visible_node_hierarchy_relation_keys.clear()
        policy._failed_visible_node_hierarchy_relation_keys.add(raw_relation_key)
        policy._failed_bridge_hierarchy_relation_keys.clear()
        policy._failed_residual_linked_hierarchy_relation_keys.clear()
        policy._failed_plan_signatures.clear()

    class EarlierHierarchyFamilySelected(Exception):
        pass

    def reject_early_bridge(*_args: object, **_kwargs: object) -> None:
        pytest.fail("bridge planning ran before every earlier hierarchy family was falsified")

    gate_cases = (
        ("child", "_child_isolation_plan"),
        ("equal", "_hierarchy_joint_layout"),
        ("weighted", "_hierarchy_weighted_layout"),
        ("visible-node", "_hierarchy_visible_node_layout"),
    )
    for missing_family, expected_planner in gate_cases:
        restore_prior_family_failures()
        if missing_family == "child":
            policy._failed_child_isolation_hypothesis_keys.remove(min(child_hypothesis_keys))
        elif missing_family == "equal":
            policy._failed_hierarchy_relation_keys.clear()
        elif missing_family == "weighted":
            policy._failed_weighted_hierarchy_relation_keys.clear()
        else:
            policy._failed_visible_node_hierarchy_relation_keys.clear()

        def select_earlier_family(
            *_args: object,
            family: str = missing_family,
            **_kwargs: object,
        ) -> None:
            raise EarlierHierarchyFamilySelected(family)

        with monkeypatch.context() as gate_patch:
            gate_patch.setattr(visual_causal, "_bridge_hierarchy_plan", reject_early_bridge)
            gate_patch.setattr(visual_causal, expected_planner, select_earlier_family)
            with pytest.raises(EarlierHierarchyFamilySelected, match=missing_family):
                policy.select(policy_observation)
        assert policy.snapshot()["pending_action"] is None

    restore_prior_family_failures()
    policy._failed_bridge_hierarchy_relation_keys.add(relation.relation_key)

    class ResidualLinkedFamilySelected(Exception):
        pass

    def select_residual_linked_family(
        candidate_scene: VisualScene,
        candidate_hierarchy: visual_causal._AffineHierarchy,
        candidate_relation: visual_causal._ResidualLinkedHierarchyRelation,
        **_kwargs: object,
    ) -> None:
        assert candidate_scene == scene
        assert candidate_hierarchy == hierarchy
        assert candidate_relation.bridge_relation_key == relation.relation_key
        raise ResidualLinkedFamilySelected

    with monkeypatch.context() as rejected_patch:
        rejected_patch.setattr(visual_causal, "_bridge_hierarchy_plan", reject_early_bridge)
        rejected_patch.setattr(
            visual_causal,
            "_residual_linked_hierarchy_plan",
            select_residual_linked_family,
        )
        with pytest.raises(ResidualLinkedFamilySelected):
            policy.select(policy_observation)
    assert policy.snapshot()["pending_action"] is None

    restore_prior_family_failures()
    bridge_planner_calls = 0

    def return_certified_plan(
        candidate_scene: VisualScene,
        candidate_hierarchy: visual_causal._AffineHierarchy,
        candidate_relation: visual_causal._CompositeBridgeRelation,
        *,
        rejected_signatures: set[str],
        search_budget: visual_causal._HierarchySearchBudget | None = None,
    ) -> visual_causal._HierarchyPlan:
        nonlocal bridge_planner_calls
        assert candidate_scene == scene
        assert candidate_hierarchy == hierarchy
        assert candidate_relation == relation
        assert rejected_signatures is policy._failed_plan_signatures
        assert search_budget is not None
        bridge_planner_calls += 1
        return plan

    monkeypatch.setattr(visual_causal, "_bridge_hierarchy_plan", return_certified_plan)
    selected_bridge_action = policy.select(policy_observation)
    assert selected_bridge_action.coordinate == plan.actions[0].coordinate
    assert bridge_planner_calls == 1
    assert policy._active_hierarchy_relation_key == relation.relation_key

    interrupted_environment = _ProjectedWeightedHierarchyEnvironment(scene, hierarchy)
    interrupted_observation = interrupted_environment.observation()
    interrupted_policy = VisualCausalPolicy(max_coordinate_candidates=8)
    interrupted_policy._level_index = 4
    interrupted_policy._last_active_color = hierarchy.active_color
    interrupted_policy._ensure_learner(interrupted_observation)
    interrupted_policy._install_hierarchy_plan(plan, relation_key=relation.relation_key)
    interrupted_action = interrupted_policy.select(interrupted_observation)
    interrupted_return = interrupted_environment.step(interrupted_action)
    interrupted_return = replace(
        interrupted_return,
        state=GameStateName.GAME_OVER,
        available_actions=(ActionName.RESET,),
    )
    interrupted_policy.accept_consequence(interrupted_return)
    assert not interrupted_policy._failed_bridge_hierarchy_relation_keys
    assert plan.signature not in interrupted_policy._failed_plan_signatures
    assert interrupted_policy.snapshot()["hierarchy_preterminal_retry_count"] == 1
    interrupted_reset = interrupted_policy.select(interrupted_return)
    assert interrupted_reset.name is ActionName.RESET
    interrupted_reset_environment = _ProjectedWeightedHierarchyEnvironment(scene, hierarchy)
    interrupted_recovered = replace(
        interrupted_reset_environment.observation(returned_action=interrupted_reset),
        full_reset=True,
    )
    interrupted_policy.accept_consequence(interrupted_recovered)
    assert not interrupted_policy._failed_bridge_hierarchy_relation_keys
    assert plan.signature not in interrupted_policy._failed_plan_signatures
    assert interrupted_policy.snapshot()["hierarchy_preterminal_retry_count"] == 1
    assert interrupted_policy.snapshot()["hierarchy_active"] is False
    assert interrupted_policy.snapshot()["pending_plan_actions"] == 0

    for corrupt_terminal_state in (
        GameStateName.NOT_FINISHED,
        GameStateName.GAME_OVER,
    ):
        corrupt_environment = _ProjectedWeightedHierarchyEnvironment(scene, hierarchy)
        corrupt_observation = corrupt_environment.observation()
        corrupt_policy = VisualCausalPolicy(max_coordinate_candidates=8)
        corrupt_policy._level_index = 4
        corrupt_policy._last_active_color = hierarchy.active_color
        corrupt_policy._ensure_learner(corrupt_observation)
        corrupt_policy._install_hierarchy_plan(plan, relation_key=relation.relation_key)
        for _expected in plan.actions[:-1]:
            corrupt_action = corrupt_policy.select(corrupt_observation)
            corrupt_observation = corrupt_environment.step(corrupt_action)
            corrupt_policy.accept_consequence(corrupt_observation)
        corrupt_action = corrupt_policy.select(corrupt_observation)
        corrupt_return = corrupt_environment.step(corrupt_action)
        original_value = corrupt_return.frames[-1].cells[1][1]
        corrupt_return = _replace_observation_cell(
            corrupt_return,
            coordinate=(1, 1),
            value=6 if original_value != 6 else 7,
        )
        if corrupt_terminal_state is GameStateName.GAME_OVER:
            corrupt_return = replace(
                corrupt_return,
                state=GameStateName.GAME_OVER,
                available_actions=(ActionName.RESET,),
            )
        corrupt_policy.accept_consequence(corrupt_return)
        assert relation.relation_key not in corrupt_policy._failed_bridge_hierarchy_relation_keys
        assert corrupt_policy.snapshot()["pending_plan_actions"] == 0
        assert corrupt_policy.snapshot()["hierarchy_lineage_lost"] is (
            corrupt_terminal_state is GameStateName.NOT_FINISHED
        )

    progress_environment = _ProjectedWeightedHierarchyEnvironment(scene, hierarchy)
    progress_observation = progress_environment.observation()
    progress_policy = VisualCausalPolicy(max_coordinate_candidates=8)
    progress_policy._level_index = 4
    progress_policy._last_active_color = hierarchy.active_color
    progress_policy._ensure_learner(progress_observation)
    progress_policy._failed_hierarchy_relation_keys.add(raw_relation_key)
    progress_policy._failed_weighted_hierarchy_relation_keys.add(raw_relation_key)
    progress_policy._failed_visible_node_hierarchy_relation_keys.add(raw_relation_key)
    progress_policy._failed_bridge_hierarchy_relation_keys.add(relation.relation_key)
    progress_policy._install_hierarchy_plan(plan, relation_key=relation.relation_key)
    for action_index in range(len(plan.actions)):
        progress_action = progress_policy.select(progress_observation)
        progress_observation = progress_environment.step(progress_action)
        if action_index + 1 == len(plan.actions):
            progress_observation = replace(progress_observation, levels_completed=5)
        progress_policy.accept_consequence(progress_observation)
    progress_snapshot = progress_policy.snapshot()
    assert progress_snapshot["active_level_index"] == 5
    assert progress_snapshot["hierarchy_active"] is False
    assert progress_snapshot["pending_plan_actions"] == 0
    assert progress_snapshot["hierarchy_hypothesis_rejected_count"] == 0
    assert progress_snapshot["hierarchy_bridge_relation_rejected_count"] == 0

    terminal_environment = _ProjectedWeightedHierarchyEnvironment(scene, hierarchy)
    terminal_observation = terminal_environment.observation()
    terminal_policy = VisualCausalPolicy(max_coordinate_candidates=8)
    terminal_policy._level_index = 4
    terminal_policy._last_active_color = hierarchy.active_color
    terminal_policy._ensure_learner(terminal_observation)
    terminal_policy._install_hierarchy_plan(plan, relation_key=relation.relation_key)
    for action_index in range(len(plan.actions)):
        terminal_action = terminal_policy.select(terminal_observation)
        terminal_observation = terminal_environment.step(terminal_action)
        if action_index + 1 == len(plan.actions):
            terminal_observation = replace(
                terminal_observation,
                state=GameStateName.GAME_OVER,
                available_actions=(ActionName.RESET,),
            )
        terminal_policy.accept_consequence(terminal_observation)
    assert terminal_policy._failed_bridge_hierarchy_relation_keys == {relation.relation_key}
    reset_action = terminal_policy.select(terminal_observation)
    assert reset_action.name is ActionName.RESET
    reset_environment = _ProjectedWeightedHierarchyEnvironment(scene, hierarchy)
    reset_observation = replace(
        reset_environment.observation(returned_action=reset_action),
        full_reset=True,
    )
    terminal_policy.accept_consequence(reset_observation)
    assert terminal_policy._failed_bridge_hierarchy_relation_keys == {relation.relation_key}
    terminal_policy._begin_level(replace(reset_observation, levels_completed=5))
    assert not terminal_policy._failed_bridge_hierarchy_relation_keys


def test_residual_linked_mixed_support_plan_replay_and_terminal_lifecycle() -> None:
    frame = _campaign26_weighted_origin_frame()
    scene = extract_visual_scene(frame)
    hierarchy = visual_causal._unique_affine_hierarchy(scene, active_color=0)
    assert hierarchy is not None
    bridge = visual_causal._composite_bridge_relation(scene, hierarchy, level_index=4)
    relation = visual_causal._residual_linked_hierarchy_relation(
        scene,
        hierarchy,
        level_index=4,
    )
    assert bridge is not None
    assert relation is not None
    assert relation.bridge_relation_key == bridge.relation_key
    assert tuple(support.child for support in relation.supports) == hierarchy.children
    assert tuple(support.target.rounded_center for support in relation.supports) == (
        (13, 28),
        (53, 28),
    )
    linked_supports = tuple(
        support for support in relation.supports if support.target == hierarchy.target
    )
    assert len(linked_supports) == 1
    linked_support = linked_supports[0]
    assert hierarchy.target.color in linked_support.example.residual_colors
    nonlinked_supports = tuple(
        support for support in relation.supports if support.target != hierarchy.target
    )
    assert len(nonlinked_supports) == len(relation.supports) - 1
    assert all(
        support.target == support.example.target
        and hierarchy.target.color not in support.example.residual_colors
        for support in nonlinked_supports
    )

    plan = visual_causal._residual_linked_hierarchy_plan(
        scene,
        hierarchy,
        relation,
        rejected_signatures=set(),
    )
    assert plan is not None
    assert plan.signature.startswith("affine-residual-linked-hierarchy:")
    assert plan.supports == ((13, 28), (53, 28))
    assert len(plan.actions) == len(plan.recovery_actions) == 9
    assert plan.recovery_actions[-1].expected_child_protected_raster_hash == (
        visual_causal._child_isolation_protected_raster_hash(scene)
    )
    protected_target_cells = {
        (x, y): scene.cells[y][x] for support in relation.supports for x, y in support.target.cells
    }

    environment = _ProjectedWeightedHierarchyEnvironment(scene, hierarchy)
    observation = environment.observation()
    for planned in plan.actions:
        current_scene = extract_visual_scene(observation.frames[-1])
        assert visual_causal._hierarchy_planned_click_is_safe(
            current_scene,
            planned,
            active_color=hierarchy.active_color,
        )
        observation = environment.step(ActionRequest(ActionName.ACTION6, planned.coordinate))
        returned_scene = extract_visual_scene(observation.frames[-1])
        assert visual_causal._child_isolation_protected_raster_hash(returned_scene) == (
            planned.expected_child_protected_raster_hash
        )
        assert all(
            returned_scene.cells[y][x] == value for (x, y), value in protected_target_cells.items()
        )
    terminal_scene = extract_visual_scene(observation.frames[-1])
    terminal_composite_centers = {
        target.rounded_center
        for target, _signature in visual_causal._composite_sparse_targets(terminal_scene)
    }
    assert hierarchy.target.rounded_center in {
        target.rounded_center for target in terminal_scene.targets
    }
    assert all(
        support.target.rounded_center not in terminal_composite_centers
        for support in nonlinked_supports
    )
    assert linked_support.example.target.rounded_center in terminal_composite_centers
    mediator_centers = {
        child.mediator.object_ref: (
            sum(environment.positions[item.object_ref][0] for item in child.endpoints)
            // child.arity,
            sum(environment.positions[item.object_ref][1] for item in child.endpoints)
            // child.arity,
        )
        for child in hierarchy.children
    }
    assert visual_causal._projected_hierarchy_lineages_match(
        scene,
        terminal_scene,
        hierarchy,
        positions=environment.positions,
        colors=environment.colors,
        mediator_centers=mediator_centers,
    )

    for planned in plan.recovery_actions:
        current_scene = extract_visual_scene(observation.frames[-1])
        assert visual_causal._hierarchy_planned_click_is_safe(
            current_scene,
            planned,
            active_color=hierarchy.active_color,
        )
        observation = environment.step(ActionRequest(ActionName.ACTION6, planned.coordinate))
        returned_scene = extract_visual_scene(observation.frames[-1])
        assert visual_causal._child_isolation_protected_raster_hash(returned_scene) == (
            planned.expected_child_protected_raster_hash
        )
    assert observation.frames[-1].cells == frame.cells

    policy_environment = _ProjectedWeightedHierarchyEnvironment(scene, hierarchy)
    policy_observation = policy_environment.observation()
    policy = VisualCausalPolicy(max_coordinate_candidates=8)
    policy._level_index = 4
    policy._last_active_color = hierarchy.active_color
    policy._ensure_learner(policy_observation)
    policy._install_hierarchy_plan(plan, relation_key=relation.relation_key)
    for action_index, expected in enumerate(plan.actions):
        action = policy.select(policy_observation)
        assert action.coordinate == expected.coordinate
        policy_observation = policy_environment.step(action)
        policy.accept_consequence(policy_observation)
        if action_index + 1 < len(plan.actions):
            assert relation.relation_key not in (
                policy._failed_residual_linked_hierarchy_relation_keys
            )
    assert policy._failed_residual_linked_hierarchy_relation_keys == {relation.relation_key}
    assert len(policy._plan) == len(plan.recovery_actions)
    for expected in plan.recovery_actions:
        action = policy.select(policy_observation)
        assert action.coordinate == expected.coordinate
        policy_observation = policy_environment.step(action)
        policy.accept_consequence(policy_observation)
    assert policy_observation.frames[-1].cells == frame.cells
    snapshot = policy.snapshot()
    assert snapshot["hierarchy_residual_linked_relation_rejected_count"] == 1
    assert snapshot["hierarchy_recovery_active"] is False
    assert policy.receipts[-1].residual == (
        "exact pre-hypothesis hierarchy restored after residual-linked "
        "mixed-support sufficiency failed"
    )

    mismatch_environment = _ProjectedWeightedHierarchyEnvironment(scene, hierarchy)
    mismatch_observation = mismatch_environment.observation()
    mismatch_policy = VisualCausalPolicy(max_coordinate_candidates=8)
    mismatch_policy._level_index = 4
    mismatch_policy._last_active_color = hierarchy.active_color
    mismatch_policy._ensure_learner(mismatch_observation)
    mismatch_policy._install_hierarchy_plan(plan, relation_key=relation.relation_key)
    mismatch_action = mismatch_policy.select(mismatch_observation)
    mismatch_return = mismatch_environment.step(mismatch_action)
    mismatch_return = _replace_observation_cell(
        mismatch_return,
        coordinate=(1, 1),
        value=6 if mismatch_return.frames[-1].cells[1][1] != 6 else 7,
    )
    mismatch_policy.accept_consequence(mismatch_return)
    assert not mismatch_policy._failed_residual_linked_hierarchy_relation_keys
    assert plan.signature in mismatch_policy._failed_plan_signatures
    assert mismatch_policy.snapshot()["hierarchy_lineage_lost"] is True
    assert mismatch_policy.snapshot()["pending_plan_actions"] == 0

    interrupted_environment = _ProjectedWeightedHierarchyEnvironment(scene, hierarchy)
    interrupted_observation = interrupted_environment.observation()
    interrupted_policy = VisualCausalPolicy(max_coordinate_candidates=8)
    interrupted_policy._level_index = 4
    interrupted_policy._last_active_color = hierarchy.active_color
    interrupted_policy._ensure_learner(interrupted_observation)
    interrupted_policy._install_hierarchy_plan(plan, relation_key=relation.relation_key)
    interrupted_action = interrupted_policy.select(interrupted_observation)
    interrupted_return = replace(
        interrupted_environment.step(interrupted_action),
        state=GameStateName.GAME_OVER,
        available_actions=(ActionName.RESET,),
    )
    interrupted_policy.accept_consequence(interrupted_return)
    assert not interrupted_policy._failed_residual_linked_hierarchy_relation_keys
    interrupted_reset = interrupted_policy.select(interrupted_return)
    assert interrupted_reset.name is ActionName.RESET
    interrupted_reset_environment = _ProjectedWeightedHierarchyEnvironment(scene, hierarchy)
    interrupted_recovered = replace(
        interrupted_reset_environment.observation(returned_action=interrupted_reset),
        full_reset=True,
    )
    interrupted_policy.accept_consequence(interrupted_recovered)
    assert not interrupted_policy._failed_residual_linked_hierarchy_relation_keys

    for corrupt_terminal_state in (
        GameStateName.NOT_FINISHED,
        GameStateName.GAME_OVER,
    ):
        corrupt_environment = _ProjectedWeightedHierarchyEnvironment(scene, hierarchy)
        corrupt_observation = corrupt_environment.observation()
        corrupt_policy = VisualCausalPolicy(max_coordinate_candidates=8)
        corrupt_policy._level_index = 4
        corrupt_policy._last_active_color = hierarchy.active_color
        corrupt_policy._ensure_learner(corrupt_observation)
        corrupt_policy._install_hierarchy_plan(plan, relation_key=relation.relation_key)
        for _expected in plan.actions[:-1]:
            corrupt_action = corrupt_policy.select(corrupt_observation)
            corrupt_observation = corrupt_environment.step(corrupt_action)
            corrupt_policy.accept_consequence(corrupt_observation)
        corrupt_action = corrupt_policy.select(corrupt_observation)
        corrupt_return = corrupt_environment.step(corrupt_action)
        corrupt_return = _replace_observation_cell(
            corrupt_return,
            coordinate=(1, 1),
            value=6 if corrupt_return.frames[-1].cells[1][1] != 6 else 7,
        )
        if corrupt_terminal_state is GameStateName.GAME_OVER:
            corrupt_return = replace(
                corrupt_return,
                state=GameStateName.GAME_OVER,
                available_actions=(ActionName.RESET,),
            )
        corrupt_policy.accept_consequence(corrupt_return)
        assert not corrupt_policy._failed_residual_linked_hierarchy_relation_keys
        assert corrupt_policy.snapshot()["pending_plan_actions"] == 0

    terminal_environment = _ProjectedWeightedHierarchyEnvironment(scene, hierarchy)
    terminal_observation = terminal_environment.observation()
    terminal_policy = VisualCausalPolicy(max_coordinate_candidates=8)
    terminal_policy._level_index = 4
    terminal_policy._last_active_color = hierarchy.active_color
    terminal_policy._ensure_learner(terminal_observation)
    terminal_policy._install_hierarchy_plan(plan, relation_key=relation.relation_key)
    for action_index in range(len(plan.actions)):
        terminal_action = terminal_policy.select(terminal_observation)
        terminal_observation = terminal_environment.step(terminal_action)
        if action_index + 1 == len(plan.actions):
            terminal_observation = replace(
                terminal_observation,
                state=GameStateName.GAME_OVER,
                available_actions=(ActionName.RESET,),
            )
        terminal_policy.accept_consequence(terminal_observation)
    assert terminal_policy._failed_residual_linked_hierarchy_relation_keys == {
        relation.relation_key
    }
    terminal_reset = terminal_policy.select(terminal_observation)
    assert terminal_reset.name is ActionName.RESET
    reset_environment = _ProjectedWeightedHierarchyEnvironment(scene, hierarchy)
    reset_observation = replace(
        reset_environment.observation(returned_action=terminal_reset),
        full_reset=True,
    )
    terminal_policy.accept_consequence(reset_observation)
    assert terminal_policy._failed_residual_linked_hierarchy_relation_keys == {
        relation.relation_key
    }
    terminal_policy._begin_level(replace(reset_observation, levels_completed=5))
    assert not terminal_policy._failed_residual_linked_hierarchy_relation_keys

    progress_environment = _ProjectedWeightedHierarchyEnvironment(scene, hierarchy)
    progress_observation = progress_environment.observation()
    progress_policy = VisualCausalPolicy(max_coordinate_candidates=8)
    progress_policy._level_index = 4
    progress_policy._last_active_color = hierarchy.active_color
    progress_policy._ensure_learner(progress_observation)
    progress_policy._failed_residual_linked_hierarchy_relation_keys.add(relation.relation_key)
    progress_policy._install_hierarchy_plan(plan, relation_key=relation.relation_key)
    for action_index in range(len(plan.actions)):
        progress_action = progress_policy.select(progress_observation)
        progress_observation = progress_environment.step(progress_action)
        if action_index + 1 == len(plan.actions):
            progress_observation = replace(progress_observation, levels_completed=5)
        progress_policy.accept_consequence(progress_observation)
    progress_snapshot = progress_policy.snapshot()
    assert progress_snapshot["active_level_index"] == 5
    assert progress_snapshot["hierarchy_residual_linked_relation_rejected_count"] == 0
    assert progress_snapshot["hierarchy_active"] is False


def test_residual_linked_detector_is_equivariant_and_fails_closed_on_ambiguity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    frame = _campaign26_weighted_origin_frame()
    scene = extract_visual_scene(frame)
    hierarchy = visual_causal._unique_affine_hierarchy(scene, active_color=0)
    assert hierarchy is not None
    bridge = visual_causal._composite_bridge_relation(scene, hierarchy, level_index=4)
    relation = visual_causal._residual_linked_hierarchy_relation(
        scene,
        hierarchy,
        level_index=4,
    )
    assert bridge is not None
    assert relation is not None

    palette_swap = {8: 9, 9: 8, 11: 14, 14: 11}
    swapped_frame = GridFrame.from_rows(
        tuple(tuple(palette_swap.get(value, value) for value in row) for row in frame.cells)
    )
    swapped_scene = extract_visual_scene(swapped_frame)
    swapped_hierarchy = visual_causal._unique_affine_hierarchy(swapped_scene, active_color=0)
    assert swapped_hierarchy is not None
    swapped_relation = visual_causal._residual_linked_hierarchy_relation(
        swapped_scene,
        swapped_hierarchy,
        level_index=4,
    )
    assert swapped_relation is not None
    assert tuple(item.target.rounded_center for item in swapped_relation.supports) == tuple(
        item.target.rounded_center for item in relation.supports
    )
    assert (
        len(
            tuple(
                item
                for item in swapped_relation.supports
                if item.target == swapped_hierarchy.target
            )
        )
        == 1
    )

    relevant_cells = set(hierarchy.target.cells)
    for child in hierarchy.children:
        relevant_cells.update(visual_causal._hierarchy_dynamic_footprint(scene, child))
    for _child, example in bridge.assignments:
        relevant_cells.update(example.target.cells)
        for source in example.sources:
            relevant_cells.update(source.cells)
    delta_x, delta_y = 2, 2
    translated_rows = [[scene.background] * scene.width for _row in range(scene.height)]
    for x, y in relevant_cells:
        translated_rows[y + delta_y][x + delta_x] = scene.cells[y][x]
    translated_scene = extract_visual_scene(GridFrame.from_rows(translated_rows))
    translated_hierarchy = visual_causal._unique_affine_hierarchy(
        translated_scene,
        active_color=0,
    )
    assert translated_hierarchy is not None
    translated_relation = visual_causal._residual_linked_hierarchy_relation(
        translated_scene,
        translated_hierarchy,
        level_index=4,
    )
    assert translated_relation is not None
    assert tuple(item.target.rounded_center for item in translated_relation.supports) == tuple(
        (item.target.rounded_center[0] + delta_x, item.target.rounded_center[1] + delta_y)
        for item in relation.supports
    )

    for candidate_scene, candidate_hierarchy, candidate_bridge in (
        (scene, hierarchy, bridge),
        (
            translated_scene,
            translated_hierarchy,
            visual_causal._composite_bridge_relation(
                translated_scene,
                translated_hierarchy,
                level_index=4,
            ),
        ),
    ):
        assert candidate_bridge is not None
        aliased_bridge = replace(
            candidate_bridge,
            assignments=tuple(
                (
                    child,
                    replace(example, target=candidate_hierarchy.target)
                    if candidate_hierarchy.target.color in example.residual_colors
                    else example,
                )
                for child, example in candidate_bridge.assignments
            ),
        )
        assert tuple(
            example.target.rounded_center
            for _child, example in aliased_bridge.assignments
            if candidate_hierarchy.target.color in example.residual_colors
        ) == (candidate_hierarchy.target.rounded_center,)
        with monkeypatch.context() as alias_patch:
            alias_patch.setattr(
                visual_causal,
                "_composite_bridge_relation",
                lambda *_args, relation=aliased_bridge, **_kwargs: relation,
            )
            assert (
                visual_causal._residual_linked_hierarchy_relation(
                    candidate_scene,
                    candidate_hierarchy,
                    level_index=4,
                )
                is None
            )

    ambiguous_rows = [list(row) for row in frame.cells]
    nonlinked = next(
        (child, example)
        for child, example in bridge.assignments
        if hierarchy.target.color not in example.residual_colors
    )
    ambiguous_color = nonlinked[1].residual_colors[1]
    ambiguous_cells = set(nonlinked[1].target.cells)
    for source in nonlinked[1].sources:
        ambiguous_cells.update(source.cells)
    for x, y in ambiguous_cells:
        if ambiguous_rows[y][x] == ambiguous_color:
            ambiguous_rows[y][x] = hierarchy.target.color
    ambiguous_scene = extract_visual_scene(GridFrame.from_rows(ambiguous_rows))
    ambiguous_hierarchy = visual_causal._unique_affine_hierarchy(
        ambiguous_scene,
        active_color=0,
    )
    assert ambiguous_hierarchy is not None
    ambiguous_bridge = visual_causal._composite_bridge_relation(
        ambiguous_scene,
        ambiguous_hierarchy,
        level_index=4,
    )
    assert ambiguous_bridge is not None
    assert (
        sum(
            ambiguous_hierarchy.target.color in example.residual_colors
            for _child, example in ambiguous_bridge.assignments
        )
        == 2
    )
    assert (
        visual_causal._residual_linked_hierarchy_relation(
            ambiguous_scene,
            ambiguous_hierarchy,
            level_index=4,
        )
        is None
    )


def test_external_carrier_mask_chain_selects_and_replays_exact_9_plus_9(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    frame, scene, hierarchy, bridge, mixed, relation, plan = _external_residual_chain_fixture()

    assert relation.bridge_relation_key == bridge.relation_key
    assert relation.mixed_relation_key == mixed.relation_key
    assert tuple(support.child for support in relation.supports) == hierarchy.children
    assert tuple(support.target.rounded_center for support in relation.supports) == (
        (15, 15),
        (53, 28),
    )
    assert relation.raw_color == 14
    assert relation.external_link_color == 9
    assert relation.raw_color != relation.external_link_color
    disks = {
        disk.center: disk for _child, example in bridge.assignments for disk in example.sources
    }
    raw_source = disks[relation.raw_source_center]
    counterpart_source = disks[relation.counterpart_source_center]
    carrier_color = bridge.assignments[0][1].carrier_color
    assert raw_source.offsets(carrier_color) == relation.carrier_offsets
    assert counterpart_source.offsets(carrier_color) == relation.carrier_offsets
    assert (
        sum(
            relation.raw_color in (disk.palette - {example.carrier_color})
            for _child, example in bridge.assignments
            for disk in example.sources
        )
        == 1
    )
    assert relation.external_link_color in (counterpart_source.palette - {carrier_color})
    bridge_outputs = {example.target.rounded_center for _child, example in bridge.assignments}
    assert relation.supports[0].target.rounded_center not in bridge_outputs
    assert relation.supports[0].surface_signature == frozenset({9, 12})
    assert relation.supports[1].target == hierarchy.target
    assert relation.supports[1].surface_signature == frozenset({14})
    assert sum(support.target == hierarchy.target for support in relation.supports) == 1

    assert plan.signature.startswith("affine-external-residual-linked-hierarchy:")
    assert plan.supports == ((15, 15), (53, 28))
    assert tuple((item.coordinate.x, item.coordinate.y) for item in plan.actions) == (
        (15, 21),
        (43, 34),
        (15, 9),
        (34, 55),
        (47, 24),
        (52, 55),
        (53, 35),
        (41, 47),
        (59, 25),
    )
    assert tuple((item.coordinate.x, item.coordinate.y) for item in plan.recovery_actions) == (
        (41, 47),
        (53, 35),
        (52, 55),
        (47, 24),
        (34, 55),
        (15, 9),
        (43, 34),
        (15, 21),
        (25, 35),
    )

    environment = _ProjectedWeightedHierarchyEnvironment(scene, hierarchy)
    observation = environment.observation()
    policy = VisualCausalPolicy(max_coordinate_candidates=8)
    policy._level_index = 4
    policy._last_active_color = hierarchy.active_color
    policy._ensure_learner(observation)
    policy._failed_residual_linked_hierarchy_relation_keys.add(mixed.relation_key)
    policy._install_hierarchy_plan(plan, relation_key=relation.relation_key)
    for expected in plan.actions:
        action = policy.select(observation)
        assert action.coordinate == expected.coordinate
        observation = environment.step(action)
        policy.accept_consequence(observation)

    assert policy._failed_external_residual_linked_hierarchy_relation_keys == {
        relation.relation_key
    }
    assert len(policy._plan) == 9
    assert policy.receipts[-1].residual == (
        "the raw-linked child and its carrier-mask counterpart reached their unique external "
        "residual-chain supports, but the official environment remained NOT_FINISHED"
    )
    terminal_snapshot = policy.snapshot()
    assert terminal_snapshot["hierarchy_external_residual_linked_relation_rejected_count"] == 1
    assert terminal_snapshot["hierarchy_recovery_active"] is True

    for expected in plan.recovery_actions:
        action = policy.select(observation)
        assert action.coordinate == expected.coordinate
        observation = environment.step(action)
        policy.accept_consequence(observation)
    assert observation.frames[-1].cells == frame.cells
    assert policy.snapshot()["hierarchy_recovery_active"] is False
    assert policy.receipts[-1].residual == (
        "exact pre-hypothesis hierarchy restored after external carrier-mask residual-chain "
        "sufficiency failed"
    )

    _seed_external_chain_prerequisites(policy, scene, hierarchy, bridge, mixed)
    policy._failed_plan_signatures.clear()

    class ExternalFamilySelected(Exception):
        pass

    def select_external_family(
        candidate_scene: VisualScene,
        candidate_hierarchy: visual_causal._AffineHierarchy,
        candidate_relation: visual_causal._ExternalResidualLinkedHierarchyRelation,
        *,
        rejected_signatures: set[str],
        search_budget: visual_causal._HierarchySearchBudget | None = None,
    ) -> None:
        assert candidate_scene == scene
        assert candidate_hierarchy == hierarchy
        assert candidate_relation == relation
        assert rejected_signatures is policy._failed_plan_signatures
        assert search_budget is not None
        raise ExternalFamilySelected

    with monkeypatch.context() as selection_patch:
        selection_patch.setattr(
            visual_causal,
            "_external_residual_linked_hierarchy_plan",
            select_external_family,
        )
        with pytest.raises(ExternalFamilySelected):
            policy.select(observation)
    assert policy.snapshot()["pending_action"] is None

    game_over_environment = _ProjectedWeightedHierarchyEnvironment(scene, hierarchy)
    game_over_observation = game_over_environment.observation()
    game_over_policy = VisualCausalPolicy(max_coordinate_candidates=8)
    game_over_policy._level_index = 4
    game_over_policy._last_active_color = hierarchy.active_color
    game_over_policy._ensure_learner(game_over_observation)
    game_over_policy._failed_residual_linked_hierarchy_relation_keys.add(mixed.relation_key)
    game_over_policy._install_hierarchy_plan(plan, relation_key=relation.relation_key)
    for action_index in range(len(plan.actions)):
        action = game_over_policy.select(game_over_observation)
        game_over_observation = game_over_environment.step(action)
        if action_index + 1 == len(plan.actions):
            game_over_observation = replace(
                game_over_observation,
                state=GameStateName.GAME_OVER,
                available_actions=(ActionName.RESET,),
            )
        game_over_policy.accept_consequence(game_over_observation)
    assert game_over_policy._failed_external_residual_linked_hierarchy_relation_keys == {
        relation.relation_key
    }
    assert game_over_policy.receipts[-1].residual == (
        "the exact external carrier-mask residual-chain terminal returned GAME_OVER"
    )
    reset = game_over_policy.select(game_over_observation)
    reset_environment = _ProjectedWeightedHierarchyEnvironment(scene, hierarchy)
    reset_observation = replace(
        reset_environment.observation(returned_action=reset),
        full_reset=True,
    )
    game_over_policy.accept_consequence(reset_observation)
    assert game_over_policy._failed_external_residual_linked_hierarchy_relation_keys == {
        relation.relation_key
    }

    game_over_policy._install_hierarchy_plan(plan, relation_key=relation.relation_key)
    progress_action = game_over_policy.select(reset_observation)
    progress_observation = replace(
        reset_environment.step(progress_action),
        levels_completed=5,
    )
    game_over_policy.accept_consequence(progress_observation)
    assert not game_over_policy._failed_external_residual_linked_hierarchy_relation_keys
    assert game_over_policy.snapshot()["active_level_index"] == 5

    win_environment = _ProjectedWeightedHierarchyEnvironment(scene, hierarchy)
    win_observation = win_environment.observation()
    win_policy = VisualCausalPolicy(max_coordinate_candidates=8)
    win_policy._level_index = 4
    win_policy._last_active_color = hierarchy.active_color
    win_policy._ensure_learner(win_observation)
    win_policy._failed_residual_linked_hierarchy_relation_keys.add(mixed.relation_key)
    win_policy._install_hierarchy_plan(plan, relation_key=relation.relation_key)
    for action_index in range(len(plan.actions)):
        action = win_policy.select(win_observation)
        win_observation = win_environment.step(action)
        if action_index + 1 == len(plan.actions):
            win_observation = replace(
                win_observation,
                state=GameStateName.WIN,
                available_actions=(),
            )
        win_policy.accept_consequence(win_observation)
    assert not win_policy._failed_external_residual_linked_hierarchy_relation_keys
    assert plan.signature not in win_policy._failed_plan_signatures
    assert win_policy.snapshot()["hierarchy_active"] is False
    assert win_policy.snapshot()["hierarchy_preterminal_retry_count"] == 0


def test_raw_matching_composite_selects_and_replays_exact_9_plus_9(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    frame, scene, hierarchy, bridge, mixed, external, relation, plan = (
        _raw_matching_composite_fixture()
    )

    assert relation.bridge_relation_key == bridge.relation_key
    assert relation.mixed_relation_key == mixed.relation_key
    assert relation.external_relation_key == external.relation_key
    assert tuple(support.child for support in relation.supports) == hierarchy.children
    assert tuple(support.target.rounded_center for support in relation.supports) == (
        (48, 9),
        (53, 28),
    )
    assert sum(support.target == hierarchy.target for support in relation.supports) == 1
    raw_surface = frozenset(scene.cells[y][x] for x, y in hierarchy.target.cells)
    containing_support = next(
        support for support in relation.supports if support.target != hierarchy.target
    )
    assert raw_surface < containing_support.surface_signature
    assert plan.signature.startswith("affine-raw-matching-composite-hierarchy:")
    assert plan.supports == ((48, 9), (53, 28))
    assert plan.support_weights == (1, 1)
    assert tuple((item.coordinate.x, item.coordinate.y) for item in plan.actions) == (
        (42, 9),
        (43, 34),
        (54, 9),
        (34, 55),
        (47, 24),
        (52, 55),
        (53, 35),
        (41, 47),
        (59, 25),
    )
    assert tuple((item.coordinate.x, item.coordinate.y) for item in plan.recovery_actions) == (
        (41, 47),
        (53, 35),
        (52, 55),
        (47, 24),
        (34, 55),
        (54, 9),
        (43, 34),
        (42, 9),
        (25, 35),
    )

    environment = _ProjectedWeightedHierarchyEnvironment(scene, hierarchy)
    observation = environment.observation()
    policy = VisualCausalPolicy(max_coordinate_candidates=8)
    policy._level_index = 4
    policy._last_active_color = hierarchy.active_color
    policy._ensure_learner(observation)
    _seed_raw_matching_composite_prerequisites(
        policy,
        scene,
        hierarchy,
        bridge,
        mixed,
        external,
    )
    policy._install_hierarchy_plan(plan, relation_key=relation.relation_key)
    for expected in plan.actions:
        action = policy.select(observation)
        assert action.coordinate == expected.coordinate
        observation = environment.step(action)
        policy.accept_consequence(observation)

    assert policy._failed_raw_matching_composite_hierarchy_relation_keys == {relation.relation_key}
    assert len(policy._plan) == 9
    assert policy.receipts[-1].residual == (
        "the raw-linked child retained the singleton raw support while its counterpart reached "
        "the unique containing composite sink, but the official environment remained "
        "NOT_FINISHED"
    )
    terminal_snapshot = policy.snapshot()
    assert terminal_snapshot["hierarchy_raw_matching_composite_relation_rejected_count"] == 1
    assert terminal_snapshot["hierarchy_preterminal_retry_count"] == 0
    assert terminal_snapshot["hierarchy_recovery_active"] is True

    for expected in plan.recovery_actions:
        action = policy.select(observation)
        assert action.coordinate == expected.coordinate
        observation = environment.step(action)
        policy.accept_consequence(observation)
    assert observation.frames[-1].cells == frame.cells
    assert policy.snapshot()["hierarchy_recovery_active"] is False
    assert policy.receipts[-1].residual == (
        "exact pre-hypothesis hierarchy restored after raw-matching containing-composite "
        "sufficiency failed"
    )

    _seed_raw_matching_composite_prerequisites(
        policy,
        scene,
        hierarchy,
        bridge,
        mixed,
        external,
    )
    policy._failed_plan_signatures.clear()

    class RawMatchingCompositeSelected(Exception):
        pass

    def select_raw_matching_composite(
        candidate_scene: VisualScene,
        candidate_hierarchy: visual_causal._AffineHierarchy,
        candidate_relation: visual_causal._RawMatchingCompositeHierarchyRelation,
        *,
        rejected_signatures: set[str],
        search_budget: visual_causal._HierarchySearchBudget | None = None,
    ) -> None:
        assert candidate_scene == scene
        assert candidate_hierarchy == hierarchy
        assert candidate_relation == relation
        assert rejected_signatures is policy._failed_plan_signatures
        assert search_budget is not None
        raise RawMatchingCompositeSelected

    with monkeypatch.context() as selection_patch:
        selection_patch.setattr(
            visual_causal,
            "_raw_matching_composite_hierarchy_plan",
            select_raw_matching_composite,
        )
        with pytest.raises(RawMatchingCompositeSelected):
            policy.select(observation)
    assert policy.snapshot()["pending_action"] is None

    game_over_environment = _ProjectedWeightedHierarchyEnvironment(scene, hierarchy)
    game_over_observation = game_over_environment.observation()
    game_over_policy = VisualCausalPolicy(max_coordinate_candidates=8)
    game_over_policy._level_index = 4
    game_over_policy._last_active_color = hierarchy.active_color
    game_over_policy._ensure_learner(game_over_observation)
    game_over_policy._install_hierarchy_plan(plan, relation_key=relation.relation_key)
    for action_index in range(len(plan.actions)):
        action = game_over_policy.select(game_over_observation)
        game_over_observation = game_over_environment.step(action)
        if action_index + 1 == len(plan.actions):
            game_over_observation = replace(
                game_over_observation,
                state=GameStateName.GAME_OVER,
                available_actions=(ActionName.RESET,),
            )
        game_over_policy.accept_consequence(game_over_observation)
    assert game_over_policy._failed_raw_matching_composite_hierarchy_relation_keys == {
        relation.relation_key
    }
    assert game_over_policy.snapshot()["hierarchy_preterminal_retry_count"] == 0
    assert game_over_policy.receipts[-1].residual == (
        "the exact raw-matching containing-composite terminal returned GAME_OVER"
    )


def test_raw_matching_composite_preterminal_game_over_retains_one_retry() -> None:
    _frame, scene, hierarchy, _bridge, _mixed, _external, relation, plan = (
        _raw_matching_composite_fixture()
    )
    environment = _ProjectedWeightedHierarchyEnvironment(scene, hierarchy)
    observation = environment.observation()
    policy = VisualCausalPolicy(max_coordinate_candidates=8)
    policy._level_index = 4
    policy._last_active_color = hierarchy.active_color
    policy._ensure_learner(observation)
    policy._install_hierarchy_plan(plan, relation_key=relation.relation_key)

    action = policy.select(observation)
    interrupted = replace(
        environment.step(action),
        state=GameStateName.GAME_OVER,
        available_actions=(ActionName.RESET,),
    )
    policy.accept_consequence(interrupted)

    assert plan.signature not in policy._failed_plan_signatures
    assert not policy._failed_raw_matching_composite_hierarchy_relation_keys
    assert policy.snapshot()["hierarchy_preterminal_retry_count"] == 1
    assert policy.receipts[-1].residual == (
        "the hierarchy plan returned GAME_OVER before its terminal action; one same-level retry "
        "is retained after legal RESET"
    )


def test_raw_matching_composite_is_equivariant_and_fails_closed_on_ambiguity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    frame, scene, hierarchy, bridge, mixed, external, relation, _plan = (
        _raw_matching_composite_fixture()
    )

    palette_swap = {8: 9, 9: 8, 11: 14, 14: 11}
    swapped_frame = GridFrame.from_rows(
        tuple(tuple(palette_swap.get(value, value) for value in row) for row in frame.cells)
    )
    swapped_scene = extract_visual_scene(swapped_frame)
    swapped_hierarchy = visual_causal._unique_affine_hierarchy(swapped_scene, active_color=0)
    assert swapped_hierarchy is not None
    swapped_mixed = visual_causal._residual_linked_hierarchy_relation(
        swapped_scene,
        swapped_hierarchy,
        level_index=4,
    )
    assert swapped_mixed is not None
    swapped_external = visual_causal._external_residual_linked_hierarchy_relation(
        swapped_scene,
        swapped_hierarchy,
        level_index=4,
        rejected_mixed_relation_keys={swapped_mixed.relation_key},
    )
    assert swapped_external is not None
    swapped_relation = visual_causal._raw_matching_composite_hierarchy_relation(
        swapped_scene,
        swapped_hierarchy,
        level_index=4,
        rejected_mixed_relation_keys={swapped_mixed.relation_key},
        rejected_external_relation_keys={swapped_external.relation_key},
    )
    assert swapped_relation is not None
    assert tuple(support.target.rounded_center for support in swapped_relation.supports) == tuple(
        support.target.rounded_center for support in relation.supports
    )
    assert tuple(support.surface_signature for support in swapped_relation.supports) == tuple(
        frozenset(palette_swap.get(value, value) for value in support.surface_signature)
        for support in relation.supports
    )

    relevant_cells = set(hierarchy.target.cells)
    for child in hierarchy.children:
        relevant_cells.update(visual_causal._hierarchy_dynamic_footprint(scene, child))
    for _child, example in bridge.assignments:
        relevant_cells.update(example.target.cells)
        for source in example.sources:
            relevant_cells.update(source.cells)
    for target, _surface in visual_causal._composite_sparse_targets(scene):
        relevant_cells.update(target.cells)
    delta_x, delta_y = 2, 2
    translated_rows = [[scene.background] * scene.width for _row in range(scene.height)]
    for x, y in relevant_cells:
        translated_rows[y + delta_y][x + delta_x] = scene.cells[y][x]
    translated_scene = extract_visual_scene(GridFrame.from_rows(translated_rows))
    translated_hierarchy = visual_causal._unique_affine_hierarchy(
        translated_scene,
        active_color=0,
    )
    assert translated_hierarchy is not None
    translated_mixed = visual_causal._residual_linked_hierarchy_relation(
        translated_scene,
        translated_hierarchy,
        level_index=4,
    )
    assert translated_mixed is not None
    translated_external = visual_causal._external_residual_linked_hierarchy_relation(
        translated_scene,
        translated_hierarchy,
        level_index=4,
        rejected_mixed_relation_keys={translated_mixed.relation_key},
    )
    assert translated_external is not None
    translated_relation = visual_causal._raw_matching_composite_hierarchy_relation(
        translated_scene,
        translated_hierarchy,
        level_index=4,
        rejected_mixed_relation_keys={translated_mixed.relation_key},
        rejected_external_relation_keys={translated_external.relation_key},
    )
    assert translated_relation is not None
    assert tuple(
        support.target.rounded_center for support in translated_relation.supports
    ) == tuple(
        (
            support.target.rounded_center[0] + delta_x,
            support.target.rounded_center[1] + delta_y,
        )
        for support in relation.supports
    )

    containing_target, containing_surface = next(
        (target, surface)
        for target, surface in visual_causal._composite_sparse_targets(scene)
        if frozenset(scene.cells[y][x] for x, y in hierarchy.target.cells) < surface
    )
    original_sparse_targets = visual_causal._composite_sparse_targets
    with monkeypatch.context() as ambiguity_patch:
        ambiguity_patch.setattr(
            visual_causal,
            "_composite_bridge_relation",
            lambda *_args, **_kwargs: bridge,
        )
        ambiguity_patch.setattr(
            visual_causal,
            "_residual_linked_hierarchy_relation",
            lambda *_args, **_kwargs: mixed,
        )
        ambiguity_patch.setattr(
            visual_causal,
            "_external_residual_linked_hierarchy_relation",
            lambda *_args, **_kwargs: external,
        )
        ambiguity_patch.setattr(
            visual_causal,
            "_composite_sparse_targets",
            lambda candidate_scene: (
                *original_sparse_targets(candidate_scene),
                (containing_target, containing_surface),
            ),
        )
        assert (
            visual_causal._raw_matching_composite_hierarchy_relation(
                scene,
                hierarchy,
                level_index=4,
                rejected_mixed_relation_keys={mixed.relation_key},
                rejected_external_relation_keys={external.relation_key},
            )
            is None
        )


def test_external_own_composite_selects_and_replays_exact_9_plus_9(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (
        frame,
        scene,
        hierarchy,
        bridge,
        mixed,
        external,
        raw_matching,
        relation,
        plan,
    ) = _external_own_composite_fixture()

    assert relation.bridge_relation_key == bridge.relation_key
    assert relation.mixed_relation_key == mixed.relation_key
    assert relation.external_relation_key == external.relation_key
    assert relation.raw_matching_relation_key == raw_matching.relation_key
    assert tuple(support.child for support in relation.supports) == hierarchy.children
    assert tuple(support.target.rounded_center for support in relation.supports) == (
        (15, 15),
        (48, 9),
    )
    assert all(support.target != hierarchy.target for support in relation.supports)
    assert plan.signature.startswith("affine-external-own-composite-hierarchy:")
    assert plan.supports == ((15, 15), (48, 9))
    assert plan.support_weights == (1, 1)
    assert tuple((item.coordinate.x, item.coordinate.y) for item in plan.actions) == (
        (15, 21),
        (43, 34),
        (15, 9),
        (34, 55),
        (44, 15),
        (52, 55),
        (55, 9),
        (41, 47),
        (45, 3),
    )
    assert tuple((item.coordinate.x, item.coordinate.y) for item in plan.recovery_actions) == (
        (41, 47),
        (55, 9),
        (52, 55),
        (44, 15),
        (34, 55),
        (15, 9),
        (43, 34),
        (15, 21),
        (25, 35),
    )

    environment = _ProjectedWeightedHierarchyEnvironment(scene, hierarchy)
    observation = environment.observation()
    policy = VisualCausalPolicy(max_coordinate_candidates=8)
    policy._level_index = 4
    policy._last_active_color = hierarchy.active_color
    policy._ensure_learner(observation)
    _seed_external_own_composite_prerequisites(
        policy,
        scene,
        hierarchy,
        bridge,
        mixed,
        external,
        raw_matching,
    )
    policy._install_hierarchy_plan(plan, relation_key=relation.relation_key)
    for expected in plan.actions:
        action = policy.select(observation)
        assert action.coordinate == expected.coordinate
        observation = environment.step(action)
        policy.accept_consequence(observation)

    assert policy._failed_external_own_composite_hierarchy_relation_keys == {relation.relation_key}
    assert len(policy._plan) == 9
    assert policy.receipts[-1].residual == (
        "the carrier-mask counterpart reached its unique external sink while the raw-linked "
        "child reached its own bridge composite sink, but the official environment remained "
        "NOT_FINISHED"
    )
    terminal_snapshot = policy.snapshot()
    assert terminal_snapshot["hierarchy_external_own_composite_relation_rejected_count"] == 1
    assert terminal_snapshot["hierarchy_preterminal_retry_count"] == 0
    assert terminal_snapshot["hierarchy_recovery_active"] is True

    for expected in plan.recovery_actions:
        action = policy.select(observation)
        assert action.coordinate == expected.coordinate
        observation = environment.step(action)
        policy.accept_consequence(observation)
    assert observation.frames[-1].cells == frame.cells
    assert policy.snapshot()["hierarchy_recovery_active"] is False
    assert policy.receipts[-1].residual == (
        "exact pre-hypothesis hierarchy restored after external-own-composite recombination "
        "sufficiency failed"
    )

    _seed_external_own_composite_prerequisites(
        policy,
        scene,
        hierarchy,
        bridge,
        mixed,
        external,
        raw_matching,
    )
    policy._failed_plan_signatures.clear()

    class ExternalOwnCompositeSelected(Exception):
        pass

    def select_external_own_composite(
        candidate_scene: VisualScene,
        candidate_hierarchy: visual_causal._AffineHierarchy,
        candidate_relation: visual_causal._ExternalOwnCompositeHierarchyRelation,
        *,
        rejected_signatures: set[str],
        search_budget: visual_causal._HierarchySearchBudget | None = None,
    ) -> None:
        assert candidate_scene == scene
        assert candidate_hierarchy == hierarchy
        assert candidate_relation == relation
        assert rejected_signatures is policy._failed_plan_signatures
        assert search_budget is not None
        raise ExternalOwnCompositeSelected

    with monkeypatch.context() as selection_patch:
        selection_patch.setattr(
            visual_causal,
            "_external_own_composite_hierarchy_plan",
            select_external_own_composite,
        )
        with pytest.raises(ExternalOwnCompositeSelected):
            policy.select(observation)
    assert policy.snapshot()["pending_action"] is None

    game_over_environment = _ProjectedWeightedHierarchyEnvironment(scene, hierarchy)
    game_over_observation = game_over_environment.observation()
    game_over_policy = VisualCausalPolicy(max_coordinate_candidates=8)
    game_over_policy._level_index = 4
    game_over_policy._last_active_color = hierarchy.active_color
    game_over_policy._ensure_learner(game_over_observation)
    _seed_external_own_composite_prerequisites(
        game_over_policy,
        scene,
        hierarchy,
        bridge,
        mixed,
        external,
        raw_matching,
    )
    game_over_policy._install_hierarchy_plan(plan, relation_key=relation.relation_key)
    for action_index in range(len(plan.actions)):
        action = game_over_policy.select(game_over_observation)
        game_over_observation = game_over_environment.step(action)
        if action_index + 1 == len(plan.actions):
            game_over_observation = replace(
                game_over_observation,
                state=GameStateName.GAME_OVER,
                available_actions=(ActionName.RESET,),
            )
        game_over_policy.accept_consequence(game_over_observation)
    assert game_over_policy._failed_external_own_composite_hierarchy_relation_keys == {
        relation.relation_key
    }
    assert game_over_policy.snapshot()["hierarchy_preterminal_retry_count"] == 0
    assert game_over_policy.receipts[-1].residual == (
        "the exact external-own-composite recombination terminal returned GAME_OVER"
    )

    reset_action = game_over_policy.select(game_over_observation)
    assert reset_action.name is ActionName.RESET
    reset_observation = _ProjectedWeightedHierarchyEnvironment(scene, hierarchy).observation(
        returned_action=reset_action
    )
    game_over_policy.accept_consequence(reset_observation)
    assert (
        game_over_policy.snapshot()["hierarchy_external_own_composite_relation_rejected_count"] == 1
    )
    assert game_over_policy.snapshot()["hierarchy_preterminal_retry_count"] == 0


def test_external_own_composite_preterminal_game_over_closes_after_one_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (
        _frame_value,
        scene,
        hierarchy,
        bridge,
        mixed,
        external,
        raw_matching,
        relation,
        plan,
    ) = _external_own_composite_fixture()
    environment = _ProjectedWeightedHierarchyEnvironment(scene, hierarchy)
    observation = environment.observation()
    policy = VisualCausalPolicy(max_coordinate_candidates=8)
    policy._level_index = 4
    policy._last_active_color = hierarchy.active_color
    policy._ensure_learner(observation)
    _seed_external_own_composite_prerequisites(
        policy,
        scene,
        hierarchy,
        bridge,
        mixed,
        external,
        raw_matching,
    )
    policy._install_hierarchy_plan(plan, relation_key=relation.relation_key)

    for expected in plan.actions[:-2]:
        action = policy.select(observation)
        assert action.coordinate == expected.coordinate
        observation = environment.step(action)
        policy.accept_consequence(observation)
    assert policy._affine_ledger_ref is not None

    first_action = policy.select(observation)
    assert first_action.coordinate == plan.actions[-2].coordinate
    first_interruption = replace(
        environment.step(first_action),
        state=GameStateName.GAME_OVER,
        available_actions=(ActionName.RESET,),
    )
    policy.accept_consequence(first_interruption)

    assert plan.signature not in policy._failed_plan_signatures
    assert not policy._failed_external_own_composite_hierarchy_relation_keys
    assert policy.snapshot()["hierarchy_preterminal_retry_count"] == 1
    assert policy.receipts[-1].residual == (
        "the hierarchy plan returned GAME_OVER before its terminal action; one same-level retry "
        "is retained after legal RESET"
    )

    reset_action = policy.select(first_interruption)
    assert reset_action.name is ActionName.RESET
    reset_environment = _ProjectedWeightedHierarchyEnvironment(scene, hierarchy)
    reset_observation = replace(
        reset_environment.observation(returned_action=reset_action),
        full_reset=True,
    )
    policy.accept_consequence(reset_observation)
    assert policy.snapshot()["hierarchy_preterminal_retry_count"] == 1
    assert not policy._failed_external_own_composite_hierarchy_relation_keys
    assert policy.snapshot()["pending_action"] is None

    planner_calls = 0

    def return_same_plan(
        candidate_scene: VisualScene,
        candidate_hierarchy: visual_causal._AffineHierarchy,
        candidate_relation: visual_causal._ExternalOwnCompositeHierarchyRelation,
        *,
        rejected_signatures: set[str],
        search_budget: visual_causal._HierarchySearchBudget | None = None,
    ) -> visual_causal._HierarchyPlan:
        nonlocal planner_calls
        assert candidate_scene == scene
        assert candidate_hierarchy == hierarchy
        assert candidate_relation == relation
        assert plan.signature not in rejected_signatures
        assert search_budget is not None
        planner_calls += 1
        return plan

    with monkeypatch.context() as retry_patch:
        retry_patch.setattr(
            visual_causal,
            "_external_own_composite_hierarchy_plan",
            return_same_plan,
        )
        retry_action = policy.select(reset_observation)
        assert planner_calls == 1
        assert retry_action.coordinate == plan.actions[0].coordinate
        assert policy._active_hierarchy_signature == plan.signature

        second_interruption = replace(
            reset_environment.step(retry_action),
            state=GameStateName.GAME_OVER,
            available_actions=(ActionName.RESET,),
        )
        policy.accept_consequence(second_interruption)
        assert plan.signature in policy._failed_plan_signatures
        assert policy._failed_external_own_composite_hierarchy_relation_keys == {
            relation.relation_key
        }
        assert policy.snapshot()["hierarchy_external_own_composite_relation_rejected_count"] == 1
        assert policy.snapshot()["hierarchy_preterminal_retry_count"] == 0
        assert policy.receipts[-1].residual == (
            "the same external-own-composite hierarchy plan returned GAME_OVER before its "
            "terminal action on its one bounded post-RESET retry; that relation is closed "
            "rather than reopened through an alternate layout"
        )

        second_reset = policy.select(second_interruption)
        assert second_reset.name is ActionName.RESET
        second_reset_environment = _ProjectedWeightedHierarchyEnvironment(scene, hierarchy)
        second_reset_observation = replace(
            second_reset_environment.observation(returned_action=second_reset),
            full_reset=True,
        )
        policy.accept_consequence(second_reset_observation)
        receipt_count = len(policy.receipts)
        next_family_action = policy.select(second_reset_observation)

    assert planner_calls == 1
    assert next_family_action.coordinate == Coordinate(8, 38)
    assert policy._active_hierarchy_signature is not None
    assert policy._active_hierarchy_signature.startswith(
        "affine-carrier-source-occlusion-hierarchy:"
    )
    assert len(policy.receipts) == receipt_count
    assert policy.snapshot()["pending_action"] is not None
    assert policy.snapshot()["pending_plan_actions"] == 8


def test_external_own_composite_is_equivariant_and_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (
        frame,
        scene,
        hierarchy,
        bridge,
        mixed,
        external,
        raw_matching,
        relation,
        _plan,
    ) = _external_own_composite_fixture()

    complete_gates = {
        "rejected_bridge_relation_keys": {bridge.relation_key},
        "rejected_mixed_relation_keys": {mixed.relation_key},
        "rejected_external_relation_keys": {external.relation_key},
        "rejected_raw_matching_relation_keys": {raw_matching.relation_key},
    }
    for missing_gate in complete_gates:
        gates = {name: set(keys) for name, keys in complete_gates.items()}
        gates[missing_gate].clear()
        assert (
            visual_causal._external_own_composite_hierarchy_relation(
                scene,
                hierarchy,
                level_index=4,
                **gates,
            )
            is None
        )

    palette_swap = {8: 9, 9: 8, 11: 14, 14: 11}
    swapped_frame = GridFrame.from_rows(
        tuple(tuple(palette_swap.get(value, value) for value in row) for row in frame.cells)
    )
    swapped_scene = extract_visual_scene(swapped_frame)
    swapped_hierarchy = visual_causal._unique_affine_hierarchy(swapped_scene, active_color=0)
    assert swapped_hierarchy is not None
    swapped_bridge = visual_causal._composite_bridge_relation(
        swapped_scene,
        swapped_hierarchy,
        level_index=4,
    )
    swapped_mixed = visual_causal._residual_linked_hierarchy_relation(
        swapped_scene,
        swapped_hierarchy,
        level_index=4,
    )
    assert swapped_bridge is not None
    assert swapped_mixed is not None
    swapped_external = visual_causal._external_residual_linked_hierarchy_relation(
        swapped_scene,
        swapped_hierarchy,
        level_index=4,
        rejected_mixed_relation_keys={swapped_mixed.relation_key},
    )
    assert swapped_external is not None
    swapped_raw_matching = visual_causal._raw_matching_composite_hierarchy_relation(
        swapped_scene,
        swapped_hierarchy,
        level_index=4,
        rejected_mixed_relation_keys={swapped_mixed.relation_key},
        rejected_external_relation_keys={swapped_external.relation_key},
    )
    assert swapped_raw_matching is not None
    swapped_relation = visual_causal._external_own_composite_hierarchy_relation(
        swapped_scene,
        swapped_hierarchy,
        level_index=4,
        rejected_bridge_relation_keys={swapped_bridge.relation_key},
        rejected_mixed_relation_keys={swapped_mixed.relation_key},
        rejected_external_relation_keys={swapped_external.relation_key},
        rejected_raw_matching_relation_keys={swapped_raw_matching.relation_key},
    )
    assert swapped_relation is not None
    assert tuple(support.target.rounded_center for support in swapped_relation.supports) == tuple(
        support.target.rounded_center for support in relation.supports
    )
    assert tuple(support.surface_signature for support in swapped_relation.supports) == tuple(
        frozenset(palette_swap.get(value, value) for value in support.surface_signature)
        for support in relation.supports
    )

    relevant_cells = set(hierarchy.target.cells)
    for child in hierarchy.children:
        relevant_cells.update(visual_causal._hierarchy_dynamic_footprint(scene, child))
    for _child, example in bridge.assignments:
        relevant_cells.update(example.target.cells)
        for source in example.sources:
            relevant_cells.update(source.cells)
    for target, _surface in visual_causal._composite_sparse_targets(scene):
        relevant_cells.update(target.cells)
    delta_x, delta_y = 2, 2
    translated_rows = [[scene.background] * scene.width for _row in range(scene.height)]
    for x, y in relevant_cells:
        translated_rows[y + delta_y][x + delta_x] = scene.cells[y][x]
    translated_scene = extract_visual_scene(GridFrame.from_rows(translated_rows))
    translated_hierarchy = visual_causal._unique_affine_hierarchy(
        translated_scene,
        active_color=0,
    )
    assert translated_hierarchy is not None
    translated_bridge = visual_causal._composite_bridge_relation(
        translated_scene,
        translated_hierarchy,
        level_index=4,
    )
    translated_mixed = visual_causal._residual_linked_hierarchy_relation(
        translated_scene,
        translated_hierarchy,
        level_index=4,
    )
    assert translated_bridge is not None
    assert translated_mixed is not None
    translated_external = visual_causal._external_residual_linked_hierarchy_relation(
        translated_scene,
        translated_hierarchy,
        level_index=4,
        rejected_mixed_relation_keys={translated_mixed.relation_key},
    )
    assert translated_external is not None
    translated_raw_matching = visual_causal._raw_matching_composite_hierarchy_relation(
        translated_scene,
        translated_hierarchy,
        level_index=4,
        rejected_mixed_relation_keys={translated_mixed.relation_key},
        rejected_external_relation_keys={translated_external.relation_key},
    )
    assert translated_raw_matching is not None
    translated_relation = visual_causal._external_own_composite_hierarchy_relation(
        translated_scene,
        translated_hierarchy,
        level_index=4,
        rejected_bridge_relation_keys={translated_bridge.relation_key},
        rejected_mixed_relation_keys={translated_mixed.relation_key},
        rejected_external_relation_keys={translated_external.relation_key},
        rejected_raw_matching_relation_keys={translated_raw_matching.relation_key},
    )
    assert translated_relation is not None
    assert tuple(
        support.target.rounded_center for support in translated_relation.supports
    ) == tuple(
        (
            support.target.rounded_center[0] + delta_x,
            support.target.rounded_center[1] + delta_y,
        )
        for support in relation.supports
    )

    ambiguous_external = replace(
        external,
        supports=(*external.supports, external.supports[0]),
    )
    with monkeypatch.context() as ambiguity_patch:
        ambiguity_patch.setattr(
            visual_causal,
            "_composite_bridge_relation",
            lambda *_args, **_kwargs: bridge,
        )
        ambiguity_patch.setattr(
            visual_causal,
            "_residual_linked_hierarchy_relation",
            lambda *_args, **_kwargs: mixed,
        )
        ambiguity_patch.setattr(
            visual_causal,
            "_external_residual_linked_hierarchy_relation",
            lambda *_args, **_kwargs: ambiguous_external,
        )
        ambiguity_patch.setattr(
            visual_causal,
            "_raw_matching_composite_hierarchy_relation",
            lambda *_args, **_kwargs: raw_matching,
        )
        assert (
            visual_causal._external_own_composite_hierarchy_relation(
                scene,
                hierarchy,
                level_index=4,
                **complete_gates,
            )
            is None
        )


def test_carrier_source_residual_foreground_projection_matches_campaign35() -> None:
    (
        _frame,
        scene,
        hierarchy,
        _bridge,
        _mixed,
        _external,
        _raw_matching,
        _external_own,
        relation,
        plan,
    ) = _carrier_source_occlusion_fixture()
    environment = _ProjectedWeightedHierarchyEnvironment(
        scene,
        hierarchy,
        carrier_source_supports=relation.supports,
    )
    observation = environment.observation()

    for planned in plan.actions[:3]:
        observation = environment.step(ActionRequest(ActionName.ACTION6, planned.coordinate))
        projected_scene = extract_visual_scene(observation.frames[-1])
        assert visual_causal._child_isolation_protected_raster_hash(projected_scene) == (
            planned.expected_child_protected_raster_hash
        )

    official = _campaign35_residual_foreground_after_a3_frame()
    assert all(
        observation.frames[-1].cells[y][x] == official.cells[y][x]
        for y in range(64)
        for x in range(1, 64)
    )

    mediator_centers = {
        child.mediator.object_ref: (
            sum(environment.positions[endpoint.object_ref][0] for endpoint in child.endpoints)
            // child.arity,
            sum(environment.positions[endpoint.object_ref][1] for endpoint in child.endpoints)
            // child.arity,
        )
        for child in hierarchy.children
    }
    occluded_supports = tuple(
        support
        for support in relation.supports
        if mediator_centers[support.child.mediator.object_ref] == support.source.center
    )
    assert len(occluded_supports) == 1
    support = occluded_supports[0]
    residual_colors = support.source.palette - {support.example.carrier_color}
    assert len(residual_colors) == 1
    residual_color = next(iter(residual_colors))
    residual_cells = frozenset(
        (support.source.center[0] + dx, support.source.center[1] + dy)
        for dx, dy in support.source.offsets(residual_color)
    )
    latent = visual_causal._hierarchy_projected_scene(
        scene,
        hierarchy,
        positions=environment.positions,
        colors=environment.colors,
    )
    official_foreground_delta = frozenset(
        (x, y)
        for y in range(64)
        for x in range(1, 64)
        if latent.cells[y][x] != official.cells[y][x]
    )
    assert official_foreground_delta == residual_cells
    assert all(official.cells[y][x] == residual_color for x, y in residual_cells)
    official_scene = extract_visual_scene(official)
    assert len(official_scene.endpoints) == 4
    assert sorted(len(item.cells) for item in official_scene.mediators) == [21, 23]
    fourth = plan.actions[3]
    assert fourth.required_visible_active_endpoint_count == 0
    assert tuple(
        (
            item.coordinate.x,
            item.coordinate.y,
            item.required_visible_active_endpoint_count,
        )
        for item in plan.actions
        if item.required_visible_active_endpoint_count is not None
    ) == ((52, 55, 0),)
    assert tuple(
        (
            item.coordinate.x,
            item.coordinate.y,
            item.required_visible_active_endpoint_count,
        )
        for item in plan.recovery_actions
        if item.required_visible_active_endpoint_count is not None
    ) == ((20, 42, 1), (43, 34, 0))
    assert visual_causal._hierarchy_planned_click_is_safe(
        official_scene,
        fourth,
        active_color=hierarchy.active_color,
    )
    corrupted_rows = [list(row) for row in official.cells]
    corrupted_rows[1][1] = 6 if corrupted_rows[1][1] != 6 else 7
    assert not visual_causal._hierarchy_planned_click_is_safe(
        extract_visual_scene(GridFrame.from_rows(corrupted_rows)),
        fourth,
        active_color=hierarchy.active_color,
    )

    # The next unsubmitted discriminator remains model-derived: the role switch
    # restores all five endpoint glyphs while retaining one source-masked child
    # mediator.  It is not official progress or a terminal claim.
    next_observation = environment.step(ActionRequest(ActionName.ACTION6, fourth.coordinate))
    next_scene = extract_visual_scene(next_observation.frames[-1])
    assert len(next_scene.endpoints) == 5
    assert len(next_scene.mediators) == 1
    assert visual_causal._child_isolation_protected_raster_hash(next_scene) == (
        fourth.expected_child_protected_raster_hash
    )


def test_carrier_source_occlusion_selects_replays_and_restores_exact_sources() -> None:
    (
        frame,
        scene,
        hierarchy,
        bridge,
        mixed,
        external,
        raw_matching,
        external_own,
        relation,
        plan,
    ) = _carrier_source_occlusion_fixture()

    assert relation.bridge_relation_key == bridge.relation_key
    assert relation.mixed_relation_key == mixed.relation_key
    assert relation.external_relation_key == external.relation_key
    assert relation.raw_matching_relation_key == raw_matching.relation_key
    assert relation.external_own_relation_key == external_own.relation_key
    assert tuple(support.child for support in relation.supports) == hierarchy.children
    assert tuple(support.source.center for support in relation.supports) == ((14, 40), (20, 53))
    assert all(len(support.source.cells) == 21 for support in relation.supports)
    assert plan.signature.startswith("affine-carrier-source-occlusion-hierarchy:")
    assert plan.supports == ((14, 40), (20, 53))
    assert tuple((item.coordinate.x, item.coordinate.y) for item in plan.actions) == (
        (8, 38),
        (43, 34),
        (20, 42),
        (52, 55),
        (23, 48),
        (41, 47),
        (23, 58),
        (34, 55),
        (14, 53),
    )
    assert tuple((item.coordinate.x, item.coordinate.y) for item in plan.recovery_actions) == (
        (34, 55),
        (23, 58),
        (41, 47),
        (23, 48),
        (52, 55),
        (20, 42),
        (43, 34),
        (8, 38),
        (25, 35),
    )

    # The frozen frame must retain a plan under the production cap and global
    # search ceiling; this guards the counterpart mover-order round robin.
    assert visual_causal._MAX_HIERARCHY_CHILD_LAYOUTS == 8
    budget = visual_causal._HierarchySearchBudget(visual_causal._MAX_HIERARCHY_SEARCH_BUDGET)
    capped_plan = visual_causal._carrier_source_occlusion_hierarchy_plan(
        scene,
        hierarchy,
        relation,
        rejected_signatures=set(),
        search_budget=budget,
    )
    assert capped_plan == plan
    assert budget.remaining > 0

    environment = _ProjectedWeightedHierarchyEnvironment(
        scene,
        hierarchy,
        carrier_source_supports=relation.supports,
    )
    observation = environment.observation()
    policy = VisualCausalPolicy(max_coordinate_candidates=8)
    policy._level_index = 4
    policy._last_active_color = hierarchy.active_color
    policy._ensure_learner(observation)
    _seed_carrier_source_occlusion_prerequisites(
        policy,
        scene,
        hierarchy,
        bridge,
        mixed,
        external,
        raw_matching,
        external_own,
    )
    policy._install_hierarchy_plan(plan, relation_key=relation.relation_key)
    for action_index, expected in enumerate(plan.actions):
        action = policy.select(observation)
        assert action.coordinate == expected.coordinate
        observation = environment.step(action)
        policy.accept_consequence(observation)
        durable = policy.drain_durable_receipts()
        assert len(durable) == 1
        if action_index == 2:
            receipt = durable[0]
            assert receipt["residual"] == (
                "planned hierarchy consequence was not structurally readable"
            )
            causal = receipt["causal_action_receipt"]
            assert isinstance(causal, dict)
            observed = causal["observed_effects"]
            assert isinstance(observed, dict)
            assert observed["other_object_displacement_or_transformation"] == {
                "channel": "other_object_displacement_or_transformation",
                "dynamic_candidate": False,
                "evidence_refs": [],
                "knowledge": "UNKNOWN",
                "value": None,
            }
            assert causal["explained_effects"] == []
            learning = receipt["mechanic_learning_receipt"]
            assert isinstance(learning, dict)
            assert learning["passive_support_receipt_ids"] == []
            residual = learning["residual"]
            assert isinstance(residual, dict)
            channels = residual["channels"]
            assert isinstance(channels, list)
            assert channels[1]["channel"] == "other_object_effects"
            assert channels[1]["kind"] == "unreadable_observation"
            snapshot = policy.snapshot()
            assert snapshot["hierarchy_lineage_lost"] is False
            assert snapshot["hierarchy_signature"] == plan.signature

    assert policy._failed_carrier_source_occlusion_hierarchy_relation_keys == {
        relation.relation_key
    }
    terminal_snapshot = policy.snapshot()
    assert terminal_snapshot["hierarchy_carrier_source_occlusion_relation_rejected_count"] == 1
    assert (
        _family_state(terminal_snapshot)[
            "hierarchy_carrier_source_occlusion_relation_rejected_count"
        ]
        == 1
    )
    assert terminal_snapshot["hierarchy_recovery_active"] is True
    assert policy.receipts[-1].residual == (
        "the raw-linked child and its exact carrier-mask counterpart each occluded only their "
        "assigned filled source disk, but the official environment remained NOT_FINISHED"
    )

    for expected in plan.recovery_actions:
        action = policy.select(observation)
        assert action.coordinate == expected.coordinate
        observation = environment.step(action)
        policy.accept_consequence(observation)
    assert observation.frames[-1].cells == frame.cells
    assert policy.snapshot()["hierarchy_recovery_active"] is False
    assert policy.receipts[-1].residual == (
        "exact pre-hypothesis hierarchy and both filled source disks restored after "
        "carrier-source occlusion sufficiency failed"
    )

    _seed_carrier_source_occlusion_prerequisites(
        policy,
        scene,
        hierarchy,
        bridge,
        mixed,
        external,
        raw_matching,
        external_own,
    )
    policy._failed_plan_signatures.clear()
    selected = policy.select(observation)
    assert selected.coordinate == plan.actions[0].coordinate
    assert policy._active_hierarchy_signature == plan.signature
    assert policy._active_hierarchy_relation_key == relation.relation_key


def test_carrier_source_occlusion_requires_all_gates_and_is_equivariant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (
        frame,
        scene,
        hierarchy,
        bridge,
        mixed,
        external,
        raw_matching,
        external_own,
        relation,
        _plan,
    ) = _carrier_source_occlusion_fixture()
    complete_gates = {
        "rejected_bridge_relation_keys": {bridge.relation_key},
        "rejected_mixed_relation_keys": {mixed.relation_key},
        "rejected_external_relation_keys": {external.relation_key},
        "rejected_raw_matching_relation_keys": {raw_matching.relation_key},
        "rejected_external_own_relation_keys": {external_own.relation_key},
    }
    for missing_gate in complete_gates:
        gates = {name: set(keys) for name, keys in complete_gates.items()}
        gates[missing_gate].clear()
        assert (
            visual_causal._carrier_source_occlusion_hierarchy_relation(
                scene,
                hierarchy,
                level_index=4,
                **gates,
            )
            is None
        )

    def derive(
        candidate_scene: VisualScene,
        candidate_hierarchy: visual_causal._AffineHierarchy,
    ) -> visual_causal._CarrierSourceOcclusionHierarchyRelation:
        candidate_bridge = visual_causal._composite_bridge_relation(
            candidate_scene,
            candidate_hierarchy,
            level_index=4,
        )
        candidate_mixed = visual_causal._residual_linked_hierarchy_relation(
            candidate_scene,
            candidate_hierarchy,
            level_index=4,
        )
        assert candidate_bridge is not None
        assert candidate_mixed is not None
        candidate_external = visual_causal._external_residual_linked_hierarchy_relation(
            candidate_scene,
            candidate_hierarchy,
            level_index=4,
            rejected_mixed_relation_keys={candidate_mixed.relation_key},
        )
        assert candidate_external is not None
        candidate_raw_matching = visual_causal._raw_matching_composite_hierarchy_relation(
            candidate_scene,
            candidate_hierarchy,
            level_index=4,
            rejected_mixed_relation_keys={candidate_mixed.relation_key},
            rejected_external_relation_keys={candidate_external.relation_key},
        )
        assert candidate_raw_matching is not None
        candidate_external_own = visual_causal._external_own_composite_hierarchy_relation(
            candidate_scene,
            candidate_hierarchy,
            level_index=4,
            rejected_bridge_relation_keys={candidate_bridge.relation_key},
            rejected_mixed_relation_keys={candidate_mixed.relation_key},
            rejected_external_relation_keys={candidate_external.relation_key},
            rejected_raw_matching_relation_keys={candidate_raw_matching.relation_key},
        )
        assert candidate_external_own is not None
        candidate_relation = visual_causal._carrier_source_occlusion_hierarchy_relation(
            candidate_scene,
            candidate_hierarchy,
            level_index=4,
            rejected_bridge_relation_keys={candidate_bridge.relation_key},
            rejected_mixed_relation_keys={candidate_mixed.relation_key},
            rejected_external_relation_keys={candidate_external.relation_key},
            rejected_raw_matching_relation_keys={candidate_raw_matching.relation_key},
            rejected_external_own_relation_keys={candidate_external_own.relation_key},
        )
        assert candidate_relation is not None
        return candidate_relation

    palette_swap = {8: 9, 9: 8, 11: 14, 14: 11}
    swapped_scene = extract_visual_scene(
        GridFrame.from_rows(
            tuple(tuple(palette_swap.get(value, value) for value in row) for row in frame.cells)
        )
    )
    swapped_hierarchy = visual_causal._unique_affine_hierarchy(
        swapped_scene,
        active_color=0,
    )
    assert swapped_hierarchy is not None
    swapped_relation = derive(swapped_scene, swapped_hierarchy)
    assert tuple(support.source.center for support in swapped_relation.supports) == tuple(
        support.source.center for support in relation.supports
    )
    assert tuple(support.source.palette for support in swapped_relation.supports) == tuple(
        frozenset(palette_swap.get(value, value) for value in support.source.palette)
        for support in relation.supports
    )

    relevant_cells = set(hierarchy.target.cells)
    for child in hierarchy.children:
        relevant_cells.update(visual_causal._hierarchy_dynamic_footprint(scene, child))
    for _child, example in bridge.assignments:
        relevant_cells.update(example.target.cells)
        for source in example.sources:
            relevant_cells.update(source.cells)
    for target, _surface in visual_causal._composite_sparse_targets(scene):
        relevant_cells.update(target.cells)
    delta_x, delta_y = 2, 2
    translated_rows = [[scene.background] * scene.width for _row in range(scene.height)]
    for x, y in relevant_cells:
        translated_rows[y + delta_y][x + delta_x] = scene.cells[y][x]
    translated_scene = extract_visual_scene(GridFrame.from_rows(translated_rows))
    translated_hierarchy = visual_causal._unique_affine_hierarchy(
        translated_scene,
        active_color=0,
    )
    assert translated_hierarchy is not None
    translated_relation = derive(translated_scene, translated_hierarchy)
    assert tuple(support.source.center for support in translated_relation.supports) == tuple(
        (support.source.center[0] + delta_x, support.source.center[1] + delta_y)
        for support in relation.supports
    )

    counterpart_assignment = next(
        (child, example)
        for child, example in bridge.assignments
        if any(source.center == external.counterpart_source_center for source in example.sources)
    )
    ambiguous_example = replace(
        counterpart_assignment[1],
        sources=(
            *counterpart_assignment[1].sources,
            next(
                source
                for source in counterpart_assignment[1].sources
                if source.center == external.counterpart_source_center
            ),
        ),
    )
    ambiguous_bridge = replace(
        bridge,
        assignments=tuple(
            (child, ambiguous_example if child == counterpart_assignment[0] else example)
            for child, example in bridge.assignments
        ),
    )
    with monkeypatch.context() as ambiguity_patch:
        ambiguity_patch.setattr(
            visual_causal,
            "_composite_bridge_relation",
            lambda *_args, **_kwargs: ambiguous_bridge,
        )
        ambiguity_patch.setattr(
            visual_causal,
            "_residual_linked_hierarchy_relation",
            lambda *_args, **_kwargs: mixed,
        )
        ambiguity_patch.setattr(
            visual_causal,
            "_external_residual_linked_hierarchy_relation",
            lambda *_args, **_kwargs: external,
        )
        ambiguity_patch.setattr(
            visual_causal,
            "_raw_matching_composite_hierarchy_relation",
            lambda *_args, **_kwargs: raw_matching,
        )
        ambiguity_patch.setattr(
            visual_causal,
            "_external_own_composite_hierarchy_relation",
            lambda *_args, **_kwargs: external_own,
        )
        assert (
            visual_causal._carrier_source_occlusion_hierarchy_relation(
                scene,
                hierarchy,
                level_index=4,
                **complete_gates,
            )
            is None
        )


def test_carrier_source_occlusion_rejects_cross_source_and_unsafe_inverse(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (
        _frame_value,
        scene,
        hierarchy,
        _bridge,
        _mixed,
        _external,
        _raw_matching,
        _external_own,
        relation,
        _plan,
    ) = _carrier_source_occlusion_fixture()
    first, second = hierarchy.children
    first_movers = tuple(
        next(endpoint for endpoint in first.endpoints if endpoint.rounded_center == center)
        for center in ((25, 35), (43, 34))
    )
    second_movers = tuple(
        next(endpoint for endpoint in second.endpoints if endpoint.rounded_center == center)
        for center in ((52, 55), (41, 47), (34, 55))
    )
    first_points = ((8, 38), (20, 42))
    second_points = ((23, 48), (23, 58), (14, 53))
    layouts = (
        visual_causal._HierarchyChildLayout(
            group=first,
            support=relation.supports[0].source.center,
            movers=first_movers,
            points=first_points,
            dynamic_footprint=visual_causal._hierarchy_projected_group_footprint(
                first,
                endpoint_centers=first_points,
                mediator_center=relation.supports[0].source.center,
                endpoints=first_movers,
            ),
            radius=6,
            movement_cost=0.0,
        ),
        visual_causal._HierarchyChildLayout(
            group=second,
            support=relation.supports[1].source.center,
            movers=second_movers,
            points=second_points,
            dynamic_footprint=visual_causal._hierarchy_projected_group_footprint(
                second,
                endpoint_centers=second_points,
                mediator_center=relation.supports[1].source.center,
                endpoints=second_movers,
            ),
            radius=6,
            movement_cost=0.0,
        ),
    )
    initial_dynamic = frozenset(
        cell
        for child in hierarchy.children
        for cell in visual_causal._hierarchy_dynamic_footprint(scene, child)
    )
    assigned_cells = frozenset(
        cell for support in relation.supports for cell in support.source.cells
    )
    occupied = frozenset(
        (x, y)
        for y, row in enumerate(scene.cells)
        for x, value in enumerate(row)
        if value != scene.background
    )
    static_cells = occupied - initial_dynamic - assigned_cells
    target_regions = visual_causal._visible_target_regions(scene)
    target_signature = visual_causal._target_surface_signature(scene)

    def sequence_is_safe(
        supports: tuple[visual_causal._HierarchySourceSupport, ...],
    ) -> bool:
        return visual_causal._carrier_source_occlusion_hierarchy_sequence_is_safe(
            scene,
            hierarchy,
            supports,
            layouts,
            static_cells=static_cells,
            target_regions=target_regions,
            preserved_target_signature=target_signature,
            search_budget=visual_causal._HierarchySearchBudget(32_768),
            state_cache={},
        )

    assert sequence_is_safe(relation.supports)
    wrong_owner_supports = tuple(
        replace(support, source=relation.supports[1 - index].source)
        for index, support in enumerate(relation.supports)
    )
    assert not sequence_is_safe(wrong_owner_supports)

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
    original_checker = visual_causal._carrier_source_occlusion_projected_state_is_safe
    origin_checks = 0

    def reject_inverse_origin(
        candidate_scene: VisualScene,
        candidate_hierarchy: visual_causal._AffineHierarchy,
        candidate_supports: tuple[visual_causal._HierarchySourceSupport, ...],
        **kwargs: object,
    ) -> bool:
        nonlocal origin_checks
        result = original_checker(
            candidate_scene,
            candidate_hierarchy,
            candidate_supports,
            **kwargs,
        )
        if kwargs["positions"] == initial_positions and kwargs["colors"] == initial_colors:
            origin_checks += 1
            return result and origin_checks == 1
        return result

    monkeypatch.setattr(
        visual_causal,
        "_carrier_source_occlusion_projected_state_is_safe",
        reject_inverse_origin,
    )
    assert not sequence_is_safe(relation.supports)
    assert origin_checks == 2


def test_carrier_source_occlusion_game_over_lifecycle() -> None:
    (
        _frame_value,
        scene,
        hierarchy,
        bridge,
        mixed,
        external,
        raw_matching,
        external_own,
        relation,
        plan,
    ) = _carrier_source_occlusion_fixture()

    def prepared() -> tuple[
        _ProjectedWeightedHierarchyEnvironment,
        Observation,
        VisualCausalPolicy,
    ]:
        environment = _ProjectedWeightedHierarchyEnvironment(
            scene,
            hierarchy,
            carrier_source_supports=relation.supports,
        )
        observation = environment.observation()
        policy = VisualCausalPolicy(max_coordinate_candidates=8)
        policy._level_index = 4
        policy._last_active_color = hierarchy.active_color
        policy._ensure_learner(observation)
        _seed_carrier_source_occlusion_prerequisites(
            policy,
            scene,
            hierarchy,
            bridge,
            mixed,
            external,
            raw_matching,
            external_own,
        )
        policy._install_hierarchy_plan(plan, relation_key=relation.relation_key)
        return environment, observation, policy

    terminal_environment, terminal_observation, terminal_policy = prepared()
    for action_index in range(len(plan.actions)):
        action = terminal_policy.select(terminal_observation)
        terminal_observation = terminal_environment.step(action)
        if action_index + 1 == len(plan.actions):
            terminal_observation = replace(
                terminal_observation,
                state=GameStateName.GAME_OVER,
                available_actions=(ActionName.RESET,),
            )
        terminal_policy.accept_consequence(terminal_observation)
    assert terminal_policy._failed_carrier_source_occlusion_hierarchy_relation_keys == {
        relation.relation_key
    }
    assert terminal_policy.receipts[-1].residual == (
        "the exact carrier-source occlusion discriminator terminal returned GAME_OVER"
    )

    retry_environment, retry_observation, retry_policy = prepared()
    first_action = retry_policy.select(retry_observation)
    first_game_over = replace(
        retry_environment.step(first_action),
        state=GameStateName.GAME_OVER,
        available_actions=(ActionName.RESET,),
    )
    retry_policy.accept_consequence(first_game_over)
    assert retry_policy.snapshot()["hierarchy_preterminal_retry_count"] == 1
    assert not retry_policy._failed_carrier_source_occlusion_hierarchy_relation_keys

    reset_action = retry_policy.select(first_game_over)
    assert reset_action.name is ActionName.RESET
    reset_environment = _ProjectedWeightedHierarchyEnvironment(
        scene,
        hierarchy,
        carrier_source_supports=relation.supports,
    )
    reset_observation = replace(
        reset_environment.observation(returned_action=reset_action),
        full_reset=True,
    )
    retry_policy.accept_consequence(reset_observation)
    retry_policy._install_hierarchy_plan(plan, relation_key=relation.relation_key)
    retry_action = retry_policy.select(reset_observation)
    second_game_over = replace(
        reset_environment.step(retry_action),
        state=GameStateName.GAME_OVER,
        available_actions=(ActionName.RESET,),
    )
    retry_policy.accept_consequence(second_game_over)
    assert retry_policy._failed_carrier_source_occlusion_hierarchy_relation_keys == {
        relation.relation_key
    }
    assert retry_policy.snapshot()["hierarchy_preterminal_retry_count"] == 0
    assert retry_policy.receipts[-1].residual == (
        "the same carrier-source occlusion hierarchy plan returned GAME_OVER before its "
        "terminal action on its one bounded post-RESET retry; that relation is closed rather "
        "than reopened through an alternate layout"
    )


def test_equal_weight_hierarchy_preterminal_game_over_remains_a_failed_plan() -> None:
    _frame_value, scene, hierarchy, _bridge, _mixed, relation, external_plan = (
        _external_residual_chain_fixture()
    )
    signature = "affine-hierarchy:compatibility-probe"
    plan = replace(
        external_plan,
        actions=tuple(
            replace(planned, plan_signature=signature) for planned in external_plan.actions
        ),
        signature=signature,
        recovery_actions=tuple(
            replace(planned, plan_signature=f"{signature}-recovery")
            for planned in external_plan.recovery_actions
        ),
    )
    environment = _ProjectedWeightedHierarchyEnvironment(scene, hierarchy)
    observation = environment.observation()
    policy = VisualCausalPolicy(max_coordinate_candidates=8)
    policy._level_index = 4
    policy._last_active_color = hierarchy.active_color
    policy._ensure_learner(observation)
    policy._install_hierarchy_plan(plan, relation_key=relation.relation_key)

    action = policy.select(observation)
    interrupted = replace(
        environment.step(action),
        state=GameStateName.GAME_OVER,
        available_actions=(ActionName.RESET,),
    )
    policy.accept_consequence(interrupted)

    assert plan.signature in policy._failed_plan_signatures
    assert policy.snapshot()["hierarchy_preterminal_retry_count"] == 0
    assert "post-RESET retry" not in (policy.receipts[-1].residual or "")


def test_hierarchy_preterminal_game_over_allows_one_same_plan_retry_after_reset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _frame_value, scene, hierarchy, bridge, mixed, relation, plan = (
        _external_residual_chain_fixture()
    )
    environment = _ProjectedWeightedHierarchyEnvironment(scene, hierarchy)
    observation = environment.observation()
    policy = VisualCausalPolicy(max_coordinate_candidates=8)
    policy._level_index = 4
    policy._last_active_color = hierarchy.active_color
    policy._ensure_learner(observation)
    _seed_external_chain_prerequisites(policy, scene, hierarchy, bridge, mixed)
    policy._install_hierarchy_plan(plan, relation_key=relation.relation_key)

    for expected in plan.actions[:-2]:
        action = policy.select(observation)
        assert action.coordinate == expected.coordinate
        observation = environment.step(action)
        policy.accept_consequence(observation)
    assert policy._affine_ledger_ref is not None

    action = policy.select(observation)
    assert action.coordinate == plan.actions[-2].coordinate
    first_interruption = replace(
        environment.step(action),
        state=GameStateName.GAME_OVER,
        available_actions=(ActionName.RESET,),
    )
    policy.accept_consequence(first_interruption)
    assert plan.signature not in policy._failed_plan_signatures
    assert not policy._failed_external_residual_linked_hierarchy_relation_keys
    assert policy.snapshot()["hierarchy_preterminal_retry_count"] == 1

    reset = policy.select(first_interruption)
    assert reset.name is ActionName.RESET
    reset_environment = _ProjectedWeightedHierarchyEnvironment(scene, hierarchy)
    reset_observation = replace(
        reset_environment.observation(returned_action=reset),
        full_reset=True,
    )
    policy.accept_consequence(reset_observation)
    assert plan.signature not in policy._failed_plan_signatures
    assert policy.snapshot()["hierarchy_preterminal_retry_count"] == 1
    assert policy.snapshot()["pending_plan_actions"] == 0

    planner_calls = 0

    def return_same_plan(
        candidate_scene: VisualScene,
        candidate_hierarchy: visual_causal._AffineHierarchy,
        candidate_relation: visual_causal._ExternalResidualLinkedHierarchyRelation,
        *,
        rejected_signatures: set[str],
        search_budget: visual_causal._HierarchySearchBudget | None = None,
    ) -> visual_causal._HierarchyPlan:
        nonlocal planner_calls
        assert candidate_scene == scene
        assert candidate_hierarchy == hierarchy
        assert candidate_relation == relation
        assert plan.signature not in rejected_signatures
        assert search_budget is not None
        planner_calls += 1
        return plan

    with monkeypatch.context() as retry_patch:
        retry_patch.setattr(
            visual_causal,
            "_external_residual_linked_hierarchy_plan",
            return_same_plan,
        )
        retry_action = policy.select(reset_observation)
    assert planner_calls == 1
    assert retry_action.coordinate == plan.actions[0].coordinate
    assert policy._active_hierarchy_signature == plan.signature

    second_interruption = replace(
        reset_environment.step(retry_action),
        state=GameStateName.GAME_OVER,
        available_actions=(ActionName.RESET,),
    )
    policy.accept_consequence(second_interruption)
    assert plan.signature in policy._failed_plan_signatures
    assert not policy._failed_external_residual_linked_hierarchy_relation_keys
    assert policy.snapshot()["hierarchy_preterminal_retry_count"] == 0
    assert policy.receipts[-1].residual == (
        "the same hierarchy plan returned GAME_OVER before its terminal action on its one "
        "bounded post-RESET retry"
    )
    second_reset = policy.select(second_interruption)
    second_reset_environment = _ProjectedWeightedHierarchyEnvironment(scene, hierarchy)
    second_reset_observation = replace(
        second_reset_environment.observation(returned_action=second_reset),
        full_reset=True,
    )
    policy.accept_consequence(second_reset_observation)
    assert plan.signature in policy._failed_plan_signatures
    assert policy.snapshot()["hierarchy_preterminal_retry_count"] == 0


def test_hierarchy_preterminal_retry_clears_after_regenerated_terminal_and_recovery() -> None:
    frame, scene, hierarchy, _bridge, mixed, relation, plan = _external_residual_chain_fixture()
    environment = _ProjectedWeightedHierarchyEnvironment(scene, hierarchy)
    observation = environment.observation()
    policy = VisualCausalPolicy(max_coordinate_candidates=8)
    policy._level_index = 4
    policy._last_active_color = hierarchy.active_color
    policy._ensure_learner(observation)
    policy._install_hierarchy_plan(plan, relation_key=relation.relation_key)

    first_action = policy.select(observation)
    first_interruption = replace(
        environment.step(first_action),
        state=GameStateName.GAME_OVER,
        available_actions=(ActionName.RESET,),
    )
    policy.accept_consequence(first_interruption)
    assert policy.snapshot()["hierarchy_preterminal_retry_count"] == 1
    assert plan.signature not in policy._failed_plan_signatures

    reset = policy.select(first_interruption)
    retry_environment = _ProjectedWeightedHierarchyEnvironment(scene, hierarchy)
    retry_observation = replace(
        retry_environment.observation(returned_action=reset),
        full_reset=True,
    )
    policy.accept_consequence(retry_observation)
    assert policy.snapshot()["hierarchy_preterminal_retry_count"] == 1

    regenerated_signature = "affine-external-residual-linked-hierarchy:regenerated"
    regenerated_recovery_signature = (
        "affine-external-residual-linked-hierarchy-recovery:regenerated"
    )
    regenerated_plan = replace(
        plan,
        signature=regenerated_signature,
        actions=tuple(
            replace(action, plan_signature=regenerated_signature) for action in plan.actions
        ),
        recovery_actions=tuple(
            replace(action, plan_signature=regenerated_recovery_signature)
            for action in plan.recovery_actions
        ),
    )
    policy._failed_residual_linked_hierarchy_relation_keys.add(mixed.relation_key)
    policy._install_hierarchy_plan(regenerated_plan, relation_key=relation.relation_key)
    for expected in regenerated_plan.actions:
        action = policy.select(retry_observation)
        assert action.coordinate == expected.coordinate
        retry_observation = retry_environment.step(action)
        policy.accept_consequence(retry_observation)

    assert policy.snapshot()["hierarchy_preterminal_retry_count"] == 0
    assert regenerated_signature in policy._failed_plan_signatures
    assert plan.signature not in policy._failed_plan_signatures
    assert policy._failed_external_residual_linked_hierarchy_relation_keys == {
        relation.relation_key
    }
    assert len(policy._plan) == len(regenerated_plan.recovery_actions)
    assert policy.receipts[-1].residual == (
        "the raw-linked child and its carrier-mask counterpart reached their unique external "
        "residual-chain supports, but the official environment remained NOT_FINISHED"
    )

    for expected in regenerated_plan.recovery_actions:
        action = policy.select(retry_observation)
        assert action.coordinate == expected.coordinate
        retry_observation = retry_environment.step(action)
        policy.accept_consequence(retry_observation)
    assert retry_observation.frames[-1].cells == frame.cells
    assert policy.snapshot()["hierarchy_preterminal_retry_count"] == 0
    assert policy.receipts[-1].residual == (
        "exact pre-hypothesis hierarchy restored after external carrier-mask residual-chain "
        "sufficiency failed"
    )


def test_hierarchy_preterminal_retry_clears_on_regenerated_terminal_game_over() -> None:
    _frame, scene, hierarchy, _bridge, _mixed, relation, plan = _external_residual_chain_fixture()
    environment = _ProjectedWeightedHierarchyEnvironment(scene, hierarchy)
    observation = environment.observation()
    policy = VisualCausalPolicy(max_coordinate_candidates=8)
    policy._level_index = 4
    policy._last_active_color = hierarchy.active_color
    policy._ensure_learner(observation)
    policy._install_hierarchy_plan(plan, relation_key=relation.relation_key)

    first_action = policy.select(observation)
    first_interruption = replace(
        environment.step(first_action),
        state=GameStateName.GAME_OVER,
        available_actions=(ActionName.RESET,),
    )
    policy.accept_consequence(first_interruption)
    assert policy.snapshot()["hierarchy_preterminal_retry_count"] == 1

    reset = policy.select(first_interruption)
    retry_environment = _ProjectedWeightedHierarchyEnvironment(scene, hierarchy)
    retry_observation = replace(
        retry_environment.observation(returned_action=reset),
        full_reset=True,
    )
    policy.accept_consequence(retry_observation)
    regenerated_signature = (
        "affine-external-residual-linked-hierarchy:regenerated-terminal-game-over"
    )
    regenerated_plan = replace(
        plan,
        signature=regenerated_signature,
        actions=tuple(
            replace(action, plan_signature=regenerated_signature) for action in plan.actions
        ),
    )
    policy._install_hierarchy_plan(regenerated_plan, relation_key=relation.relation_key)
    for action_index, expected in enumerate(regenerated_plan.actions):
        action = policy.select(retry_observation)
        assert action.coordinate == expected.coordinate
        retry_observation = retry_environment.step(action)
        if action_index + 1 == len(regenerated_plan.actions):
            retry_observation = replace(
                retry_observation,
                state=GameStateName.GAME_OVER,
                available_actions=(ActionName.RESET,),
            )
        policy.accept_consequence(retry_observation)

    assert policy.snapshot()["hierarchy_preterminal_retry_count"] == 0
    assert regenerated_signature in policy._failed_plan_signatures
    assert plan.signature not in policy._failed_plan_signatures
    assert policy._failed_external_residual_linked_hierarchy_relation_keys == {
        relation.relation_key
    }
    assert policy.receipts[-1].residual == (
        "the exact external carrier-mask residual-chain terminal returned GAME_OVER"
    )


@pytest.mark.parametrize(
    "returned_state",
    (GameStateName.NOT_FINISHED, GameStateName.UNKNOWN),
)
def test_hierarchy_preterminal_retry_reservation_clears_on_nonterminal_mismatch(
    returned_state: GameStateName,
) -> None:
    _frame_value, scene, hierarchy, _bridge, _mixed, relation, plan = (
        _external_residual_chain_fixture()
    )
    environment = _ProjectedWeightedHierarchyEnvironment(scene, hierarchy)
    observation = environment.observation()
    policy = VisualCausalPolicy(max_coordinate_candidates=8)
    policy._level_index = 4
    policy._last_active_color = hierarchy.active_color
    policy._ensure_learner(observation)
    policy._install_hierarchy_plan(plan, relation_key=relation.relation_key)

    first_action = policy.select(observation)
    interrupted = replace(
        environment.step(first_action),
        state=GameStateName.GAME_OVER,
        available_actions=(ActionName.RESET,),
    )
    policy.accept_consequence(interrupted)
    assert policy.snapshot()["hierarchy_preterminal_retry_count"] == 1

    reset = policy.select(interrupted)
    retry_environment = _ProjectedWeightedHierarchyEnvironment(scene, hierarchy)
    retry_observation = replace(
        retry_environment.observation(returned_action=reset),
        full_reset=True,
    )
    policy.accept_consequence(retry_observation)
    regenerated_signature = (
        "affine-external-residual-linked-hierarchy:regenerated-nonterminal-"
        f"{returned_state.value.lower()}"
    )
    regenerated_plan = replace(
        plan,
        signature=regenerated_signature,
        actions=tuple(
            replace(action, plan_signature=regenerated_signature) for action in plan.actions
        ),
    )
    policy._install_hierarchy_plan(regenerated_plan, relation_key=relation.relation_key)
    retry_action = policy.select(retry_observation)

    unchanged_mismatch = replace(
        retry_observation,
        returned_action=retry_action,
        state=returned_state,
    )
    policy.accept_consequence(unchanged_mismatch)

    assert regenerated_signature in policy._failed_plan_signatures
    assert plan.signature not in policy._failed_plan_signatures
    assert policy.snapshot()["hierarchy_preterminal_retry_count"] == 0
    if returned_state is GameStateName.NOT_FINISHED:
        assert policy.snapshot()["hierarchy_lineage_lost"] is True


@pytest.mark.parametrize("outcome", (GameStateName.NOT_FINISHED, GameStateName.WIN))
def test_hierarchy_preterminal_retry_clears_on_progress_or_win(
    outcome: GameStateName,
) -> None:
    _frame_value, scene, hierarchy, _bridge, _mixed, relation, plan = (
        _external_residual_chain_fixture()
    )
    environment = _ProjectedWeightedHierarchyEnvironment(scene, hierarchy)
    observation = environment.observation()
    policy = VisualCausalPolicy(max_coordinate_candidates=8)
    policy._level_index = 4
    policy._last_active_color = hierarchy.active_color
    policy._ensure_learner(observation)
    policy._install_hierarchy_plan(plan, relation_key=relation.relation_key)
    first_action = policy.select(observation)
    interrupted = replace(
        environment.step(first_action),
        state=GameStateName.GAME_OVER,
        available_actions=(ActionName.RESET,),
    )
    policy.accept_consequence(interrupted)
    assert policy.snapshot()["hierarchy_preterminal_retry_count"] == 1

    reset = policy.select(interrupted)
    retry_environment = _ProjectedWeightedHierarchyEnvironment(scene, hierarchy)
    retry_observation = replace(
        retry_environment.observation(returned_action=reset),
        full_reset=True,
    )
    policy.accept_consequence(retry_observation)
    policy._install_hierarchy_plan(plan, relation_key=relation.relation_key)
    retry_action = policy.select(retry_observation)
    returned = retry_environment.step(retry_action)
    if outcome is GameStateName.WIN:
        returned = replace(returned, state=outcome, available_actions=())
    else:
        returned = replace(returned, levels_completed=5)
    policy.accept_consequence(returned)
    assert policy.snapshot()["hierarchy_preterminal_retry_count"] == 0
    assert plan.signature not in policy._failed_plan_signatures


def test_external_carrier_mask_chain_is_equivariant_and_fails_closed_on_ambiguity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    frame, scene, hierarchy, bridge, mixed, relation, _plan = _external_residual_chain_fixture()

    palette_swap = {8: 9, 9: 8, 11: 14, 14: 11}
    swapped_frame = GridFrame.from_rows(
        tuple(tuple(palette_swap.get(value, value) for value in row) for row in frame.cells)
    )
    swapped_scene = extract_visual_scene(swapped_frame)
    swapped_hierarchy = visual_causal._unique_affine_hierarchy(swapped_scene, active_color=0)
    assert swapped_hierarchy is not None
    swapped_mixed = visual_causal._residual_linked_hierarchy_relation(
        swapped_scene,
        swapped_hierarchy,
        level_index=4,
    )
    assert swapped_mixed is not None
    swapped_relation = visual_causal._external_residual_linked_hierarchy_relation(
        swapped_scene,
        swapped_hierarchy,
        level_index=4,
        rejected_mixed_relation_keys={swapped_mixed.relation_key},
    )
    assert swapped_relation is not None
    assert tuple(item.target.rounded_center for item in swapped_relation.supports) == tuple(
        item.target.rounded_center for item in relation.supports
    )
    assert swapped_relation.raw_color == palette_swap[relation.raw_color]
    assert swapped_relation.external_link_color == palette_swap[relation.external_link_color]
    assert swapped_relation.carrier_offsets == relation.carrier_offsets

    relevant_cells = set(hierarchy.target.cells)
    for child in hierarchy.children:
        relevant_cells.update(visual_causal._hierarchy_dynamic_footprint(scene, child))
    for _child, example in bridge.assignments:
        relevant_cells.update(example.target.cells)
        for source in example.sources:
            relevant_cells.update(source.cells)
    for target, _surface in visual_causal._composite_sparse_targets(scene):
        relevant_cells.update(target.cells)
    delta_x, delta_y = 2, 2
    translated_rows = [[scene.background] * scene.width for _row in range(scene.height)]
    for x, y in relevant_cells:
        translated_rows[y + delta_y][x + delta_x] = scene.cells[y][x]
    translated_scene = extract_visual_scene(GridFrame.from_rows(translated_rows))
    translated_hierarchy = visual_causal._unique_affine_hierarchy(
        translated_scene,
        active_color=0,
    )
    assert translated_hierarchy is not None
    translated_mixed = visual_causal._residual_linked_hierarchy_relation(
        translated_scene,
        translated_hierarchy,
        level_index=4,
    )
    assert translated_mixed is not None
    translated_relation = visual_causal._external_residual_linked_hierarchy_relation(
        translated_scene,
        translated_hierarchy,
        level_index=4,
        rejected_mixed_relation_keys={translated_mixed.relation_key},
    )
    assert translated_relation is not None
    assert tuple(item.target.rounded_center for item in translated_relation.supports) == tuple(
        (item.target.rounded_center[0] + delta_x, item.target.rounded_center[1] + delta_y)
        for item in relation.supports
    )
    assert translated_relation.raw_source_center == (
        relation.raw_source_center[0] + delta_x,
        relation.raw_source_center[1] + delta_y,
    )
    assert translated_relation.counterpart_source_center == (
        relation.counterpart_source_center[0] + delta_x,
        relation.counterpart_source_center[1] + delta_y,
    )
    assert translated_relation.carrier_offsets == relation.carrier_offsets

    external_target = next(
        support.target for support in relation.supports if support.target != hierarchy.target
    )
    wrong_link_rows = [list(row) for row in frame.cells]
    for x, y in external_target.cells:
        if wrong_link_rows[y][x] == relation.external_link_color:
            wrong_link_rows[y][x] = next(
                color
                for color in frozenset(
                    value
                    for _child, example in bridge.assignments
                    for value in example.residual_colors
                )
                if color not in {relation.external_link_color, relation.raw_color}
            )
    wrong_link_scene = extract_visual_scene(GridFrame.from_rows(wrong_link_rows))
    wrong_link_hierarchy = visual_causal._unique_affine_hierarchy(
        wrong_link_scene,
        active_color=0,
    )
    assert wrong_link_hierarchy is not None
    wrong_link_mixed = visual_causal._residual_linked_hierarchy_relation(
        wrong_link_scene,
        wrong_link_hierarchy,
        level_index=4,
    )
    assert wrong_link_mixed is not None
    assert (
        visual_causal._external_residual_linked_hierarchy_relation(
            wrong_link_scene,
            wrong_link_hierarchy,
            level_index=4,
            rejected_mixed_relation_keys={wrong_link_mixed.relation_key},
        )
        is None
    )

    bridge_residuals = frozenset(
        value for _child, example in bridge.assignments for value in example.residual_colors
    )
    unlinked_target, unlinked_surface = next(
        (target, surface)
        for target, surface in visual_causal._composite_sparse_targets(scene)
        if target.rounded_center
        not in {
            hierarchy.target.rounded_center,
            external_target.rounded_center,
            *(example.target.rounded_center for _child, example in bridge.assignments),
        }
        and not (surface & bridge_residuals)
    )
    duplicate_rows = [list(row) for row in frame.cells]
    replaced_color = min(unlinked_surface)
    for x, y in unlinked_target.cells:
        if duplicate_rows[y][x] == replaced_color:
            duplicate_rows[y][x] = relation.external_link_color
    duplicate_scene = extract_visual_scene(GridFrame.from_rows(duplicate_rows))
    duplicate_hierarchy = visual_causal._unique_affine_hierarchy(duplicate_scene, active_color=0)
    assert duplicate_hierarchy is not None
    duplicate_mixed = visual_causal._residual_linked_hierarchy_relation(
        duplicate_scene,
        duplicate_hierarchy,
        level_index=4,
    )
    assert duplicate_mixed is not None
    assert (
        visual_causal._external_residual_linked_hierarchy_relation(
            duplicate_scene,
            duplicate_hierarchy,
            level_index=4,
            rejected_mixed_relation_keys={duplicate_mixed.relation_key},
        )
        is None
    )

    raw_assignment = next(
        (child, example)
        for child, example in bridge.assignments
        if any(source.center == relation.raw_source_center for source in example.sources)
    )
    counterpart_assignment = next(
        (child, example) for child, example in bridge.assignments if child != raw_assignment[0]
    )
    ambiguous_sources = tuple(
        source
        if source.center == relation.counterpart_source_center
        else replace(
            source,
            offsets_by_color=tuple(
                (
                    color,
                    relation.carrier_offsets
                    if color == counterpart_assignment[1].carrier_color
                    else cells,
                )
                for color, cells in source.offsets_by_color
            ),
        )
        for source in counterpart_assignment[1].sources
    )
    ambiguous_example = replace(counterpart_assignment[1], sources=ambiguous_sources)
    ambiguous_bridge = replace(
        bridge,
        assignments=tuple(
            (child, ambiguous_example if child == counterpart_assignment[0] else example)
            for child, example in bridge.assignments
        ),
    )
    with monkeypatch.context() as mask_patch:
        mask_patch.setattr(
            visual_causal,
            "_composite_bridge_relation",
            lambda *_args, **_kwargs: ambiguous_bridge,
        )
        assert (
            visual_causal._external_residual_linked_hierarchy_relation(
                scene,
                hierarchy,
                level_index=4,
                rejected_mixed_relation_keys={mixed.relation_key},
            )
            is None
        )

    original_connector = visual_causal._normalized_connector_structure
    with monkeypatch.context() as connector_patch:
        connector_patch.setattr(
            visual_causal,
            "_normalized_connector_structure",
            lambda candidate_scene, child: (
                None
                if child == hierarchy.children[0]
                else original_connector(candidate_scene, child)
            ),
        )
        assert (
            visual_causal._external_residual_linked_hierarchy_relation(
                scene,
                hierarchy,
                level_index=4,
                rejected_mixed_relation_keys={mixed.relation_key},
            )
            is None
        )


def test_composite_bridge_detector_fails_closed_on_corruption_and_duplicate_sink() -> None:
    frame = _campaign26_weighted_origin_frame()
    scene = extract_visual_scene(frame)
    hierarchy = visual_causal._unique_affine_hierarchy(scene, active_color=0)
    assert hierarchy is not None

    palette_swap = {8: 9, 9: 8, 11: 14, 14: 11}
    swapped = GridFrame.from_rows(
        tuple(tuple(palette_swap.get(value, value) for value in row) for row in frame.cells)
    )
    swapped_scene = extract_visual_scene(swapped)
    swapped_hierarchy = visual_causal._unique_affine_hierarchy(swapped_scene, active_color=0)
    assert swapped_hierarchy is not None
    assert (
        visual_causal._composite_bridge_relation(
            swapped_scene,
            swapped_hierarchy,
            level_index=4,
        )
        is not None
    )

    missing_rows = [list(row) for row in frame.cells]
    missing_rows[17][32] = scene.background
    missing_scene = extract_visual_scene(GridFrame.from_rows(missing_rows))
    missing_hierarchy = visual_causal._unique_affine_hierarchy(missing_scene, active_color=0)
    assert missing_hierarchy is not None
    assert (
        visual_causal._composite_bridge_relation(
            missing_scene,
            missing_hierarchy,
            level_index=4,
        )
        is None
    )

    duplicate_rows = [list(row) for row in frame.cells]
    duplicate_center = next(
        (center_x, center_y)
        for center_y in range(3, scene.height - 3)
        for center_x in range(3, scene.width - 3)
        if all(
            duplicate_rows[center_y + dy][center_x + dx] == scene.background
            for dy in range(-3, 4)
            for dx in range(-3, 4)
        )
    )
    source_target = next(
        target
        for target, signature in visual_causal._composite_sparse_targets(scene)
        if signature == frozenset({8, 9})
    )
    source_center = source_target.rounded_center
    for x, y in source_target.cells:
        duplicate_rows[duplicate_center[1] + y - source_center[1]][
            duplicate_center[0] + x - source_center[0]
        ] = scene.cells[y][x]
    duplicate_scene = extract_visual_scene(GridFrame.from_rows(duplicate_rows))
    duplicate_hierarchy = visual_causal._unique_affine_hierarchy(
        duplicate_scene,
        active_color=0,
    )
    assert duplicate_hierarchy is not None
    assert (
        visual_causal._composite_bridge_relation(
            duplicate_scene,
            duplicate_hierarchy,
            level_index=4,
        )
        is None
    )


def test_visible_node_hierarchy_transient_bridge_and_recovery_replay_exactly() -> None:
    frame = _campaign26_weighted_origin_frame()
    scene = extract_visual_scene(frame)
    hierarchy = visual_causal._unique_affine_hierarchy(scene, active_color=0)
    assert hierarchy is not None
    relation_key = visual_causal._hierarchy_relation_key(
        scene,
        hierarchy,
        level_index=4,
    )
    search_budget = visual_causal._HierarchySearchBudget(visual_causal._MAX_HIERARCHY_SEARCH_BUDGET)
    plan = visual_causal._hierarchy_visible_node_layout(
        scene,
        hierarchy,
        rejected_signatures=set(),
        search_budget=search_budget,
    )
    assert plan is not None
    assert search_budget.remaining >= 100_000
    assert plan.signature == "affine-visible-node-hierarchy:63b8f4d612ca1e4024e3c176"
    assert plan.supports == ((49, 20), (56, 34))
    assert plan.support_weights == (3, 4)
    assert [(action.coordinate.x, action.coordinate.y) for action in plan.actions] == [
        (52, 14),
        (34, 55),
        (59, 29),
        (43, 34),
        (46, 26),
        (52, 55),
        (59, 39),
        (41, 47),
        (50, 34),
    ]
    target = hierarchy.target.rounded_center
    assert (
        sum(
            weight * support[0]
            for weight, support in zip(plan.support_weights, plan.supports, strict=True)
        )
        == sum(plan.support_weights) * target[0]
    )
    assert (
        sum(
            weight * support[1]
            for weight, support in zip(plan.support_weights, plan.supports, strict=True)
        )
        == sum(plan.support_weights) * target[1]
    )
    assert all(action.expected_visible_endpoint_count == 5 for action in plan.actions)
    assert [
        index
        for index, action in enumerate(plan.actions)
        if action.expected_visible_mediator_count == 1
    ] == [6, 7]
    assert plan.actions[-1].expected_child_protected_raster_hash == (
        "sha256:65b5ab3f32593e1d36cd5a2b13013a162d8840a87e68141aeca38790b5fe6372"
    )

    environment = _ProjectedWeightedHierarchyEnvironment(scene, hierarchy)
    initial_positions = dict(environment.positions)
    initial_colors = dict(environment.colors)
    initial_hash = visual_causal._child_isolation_protected_raster_hash(scene)
    policy = VisualCausalPolicy(max_coordinate_candidates=8)
    policy._level_index = 4
    policy._last_active_color = hierarchy.active_color
    policy._failed_hierarchy_relation_keys.add(relation_key)
    policy._failed_weighted_hierarchy_relation_keys.add(relation_key)
    policy._install_hierarchy_plan(plan, relation_key=relation_key)
    observation = environment.observation()

    for expected in plan.actions:
        action = policy.select(observation)
        assert action.coordinate == expected.coordinate
        observation = environment.step(action)
        returned_scene = extract_visual_scene(observation.frames[-1])
        assert visual_causal._child_isolation_protected_raster_hash(returned_scene) == (
            expected.expected_child_protected_raster_hash
        )
        assert len(returned_scene.endpoints) == expected.expected_visible_endpoint_count
        assert len(returned_scene.mediators) == expected.expected_visible_mediator_count
        policy.accept_consequence(observation)
        assert policy._hierarchy_lineage_lost is None

    assert policy._failed_hierarchy_relation_keys == {relation_key}
    assert policy._failed_weighted_hierarchy_relation_keys == {relation_key}
    assert policy._failed_visible_node_hierarchy_relation_keys == {relation_key}
    snapshot = policy.snapshot()
    assert snapshot["hierarchy_relation_rejected_count"] == 1
    assert snapshot["hierarchy_hypothesis_rejected_count"] == 3
    assert snapshot["hierarchy_visible_node_relation_rejected_count"] == 1
    assert snapshot["hierarchy_recovery_active"] is True
    assert snapshot["hierarchy_recovery_signature"].startswith(
        "affine-visible-node-hierarchy-recovery:"
    )
    assert len(policy._plan) == len(plan.recovery_actions)

    for expected in plan.recovery_actions:
        action = policy.select(observation)
        assert action.coordinate == expected.coordinate
        assert policy._pending_plan_signature is not None
        assert policy._pending_plan_signature.startswith("affine-visible-node-hierarchy-recovery:")
        observation = environment.step(action)
        returned_scene = extract_visual_scene(observation.frames[-1])
        assert visual_causal._child_isolation_protected_raster_hash(returned_scene) == (
            expected.expected_child_protected_raster_hash
        )
        assert len(returned_scene.endpoints) == expected.expected_visible_endpoint_count
        assert len(returned_scene.mediators) == expected.expected_visible_mediator_count
        policy.accept_consequence(observation)
        assert policy._hierarchy_lineage_lost is None

    restored_scene = extract_visual_scene(observation.frames[-1])
    assert visual_causal._child_isolation_protected_raster_hash(restored_scene) == initial_hash
    assert environment.positions == initial_positions
    assert environment.colors == initial_colors
    assert policy.snapshot()["hierarchy_active"] is False
    assert policy.snapshot()["hierarchy_recovery_active"] is False
    assert policy.snapshot()["pending_plan_actions"] == 0
    assert policy.receipts[-1].residual == (
        "exact pre-hypothesis hierarchy restored after joint sufficiency failed"
    )


def test_visible_node_terminal_raster_mismatch_does_not_falsify_relation() -> None:
    scene = extract_visual_scene(_campaign26_weighted_origin_frame())
    hierarchy = visual_causal._unique_affine_hierarchy(scene, active_color=0)
    assert hierarchy is not None
    relation_key = visual_causal._hierarchy_relation_key(scene, hierarchy, level_index=4)
    plan = visual_causal._hierarchy_visible_node_layout(
        scene,
        hierarchy,
        rejected_signatures=set(),
    )
    assert plan is not None
    environment = _ProjectedWeightedHierarchyEnvironment(scene, hierarchy)
    policy = VisualCausalPolicy(max_coordinate_candidates=8)
    policy._level_index = 4
    policy._last_active_color = hierarchy.active_color
    policy._failed_hierarchy_relation_keys.add(relation_key)
    policy._failed_weighted_hierarchy_relation_keys.add(relation_key)
    policy._install_hierarchy_plan(plan, relation_key=relation_key)
    observation = environment.observation()

    for expected in plan.actions[:-1]:
        action = policy.select(observation)
        assert action.coordinate == expected.coordinate
        observation = environment.step(action)
        policy.accept_consequence(observation)

    terminal = policy.select(observation)
    returned = environment.step(terminal)
    rows = [list(row) for row in returned.frames[-1].cells]
    rows[1][1] = 6 if rows[1][1] != 6 else 7
    corrupted = replace(returned, frames=(GridFrame.from_rows(rows),))
    policy.accept_consequence(corrupted)

    assert relation_key not in policy._failed_visible_node_hierarchy_relation_keys
    assert policy.snapshot()["hierarchy_lineage_lost"] is True
    assert policy.snapshot()["pending_plan_actions"] == 0


def test_visible_node_exact_game_over_rejects_family_and_survives_reset() -> None:
    scene = extract_visual_scene(_campaign26_weighted_origin_frame())
    hierarchy = visual_causal._unique_affine_hierarchy(scene, active_color=0)
    assert hierarchy is not None
    relation_key = visual_causal._hierarchy_relation_key(scene, hierarchy, level_index=4)
    plan = visual_causal._hierarchy_visible_node_layout(
        scene,
        hierarchy,
        rejected_signatures=set(),
    )
    assert plan is not None
    environment = _ProjectedWeightedHierarchyEnvironment(scene, hierarchy)
    policy = VisualCausalPolicy(max_coordinate_candidates=8)
    policy._level_index = 4
    policy._last_active_color = hierarchy.active_color
    policy._failed_hierarchy_relation_keys.add(relation_key)
    policy._failed_weighted_hierarchy_relation_keys.add(relation_key)
    policy._install_hierarchy_plan(plan, relation_key=relation_key)
    observation = environment.observation()

    for expected in plan.actions[:-1]:
        action = policy.select(observation)
        assert action.coordinate == expected.coordinate
        observation = environment.step(action)
        policy.accept_consequence(observation)

    terminal = policy.select(observation)
    returned = environment.step(terminal)
    game_over = replace(
        returned,
        state=GameStateName.GAME_OVER,
        available_actions=(ActionName.RESET,),
    )
    policy.accept_consequence(game_over)

    assert policy._failed_hierarchy_relation_keys == {relation_key}
    assert policy._failed_weighted_hierarchy_relation_keys == {relation_key}
    assert policy._failed_visible_node_hierarchy_relation_keys == {relation_key}
    assert policy.receipts[-1].residual == (
        "the exact visible-node-weighted hierarchy terminal returned GAME_OVER"
    )
    assert policy.snapshot()["pending_plan_actions"] == 0

    reset = policy.select(game_over)
    assert reset.name is ActionName.RESET
    reset_environment = _ProjectedWeightedHierarchyEnvironment(scene, hierarchy)
    reset_returned = reset_environment.observation(returned_action=reset)
    policy.accept_consequence(reset_returned)

    assert policy._failed_hierarchy_relation_keys == {relation_key}
    assert policy._failed_weighted_hierarchy_relation_keys == {relation_key}
    assert policy._failed_visible_node_hierarchy_relation_keys == {relation_key}
    assert policy.snapshot()["pending_plan_actions"] == 0


def test_visible_node_failure_survives_reset_and_clears_on_level_progress() -> None:
    policy = VisualCausalPolicy(max_coordinate_candidates=8)
    relation_key = "affine-hierarchy-relation:visible-node-retention"
    policy._failed_visible_node_hierarchy_relation_keys.add(relation_key)

    policy._begin_reset_epoch()

    assert policy._failed_visible_node_hierarchy_relation_keys == {relation_key}
    next_level = _observation((8, 32), (32, 32), (20, 10), levels_completed=5)
    policy._begin_level(next_level)
    assert policy._failed_visible_node_hierarchy_relation_keys == set()


def test_active_arity_two_child_isolates_and_recovers_on_campaign27_boundary() -> None:
    frame = _campaign26_weighted_origin_frame()
    scene = extract_visual_scene(frame)
    hierarchy = visual_causal._unique_affine_hierarchy(scene, active_color=0)
    assert hierarchy is not None
    relation_key = visual_causal._hierarchy_relation_key(scene, hierarchy, level_index=4)
    hypothesis_keys = {
        child.arity: visual_causal._child_isolation_hypothesis_key(
            scene,
            child,
            relation_key=relation_key,
        )
        for child in hierarchy.children
    }
    assert set(hypothesis_keys) == {2, 3}

    plan = visual_causal._child_isolation_plan(
        scene,
        hierarchy,
        level_index=4,
        rejected_signatures=set(),
        rejected_hypothesis_keys={hypothesis_keys[3]},
    )
    assert plan is not None
    assert plan.hypothesis_key == hypothesis_keys[2]
    assert [(item.coordinate.x, item.coordinate.y) for item in plan.actions] == [
        (50, 22),
        (43, 34),
        (56, 34),
    ]
    assert [item.purpose for item in plan.actions] == [
        VisualActionPurpose.PROGRESS,
        VisualActionPurpose.PROBE,
        VisualActionPurpose.PROGRESS,
    ]
    assert [item.expected_child_protected_raster_hash for item in plan.actions] == [
        "sha256:54e6cf1538d879848e5dad91562ecbab7790b79e62441e8559cb5d8ec01d7314",
        "sha256:496ca0f16d7e60f1e1129126f4db1d2aa9fde32d6505eeea4b59c53541bb6125",
        "sha256:2e16a8705f23412d22a3154118e36e351e89e6e5e9fb12c978dbfaed74da5d75",
    ]
    assert all(item.expected_visible_endpoint_count == 5 for item in plan.actions)
    assert all(item.expected_visible_mediator_count == 2 for item in plan.actions)
    assert plan.actions[-1].completes_child_isolation is True
    assert [(item.coordinate.x, item.coordinate.y) for item in plan.recovery_actions] == [
        (43, 34),
        (50, 22),
        (25, 35),
    ]
    assert [item.purpose for item in plan.recovery_actions] == [
        VisualActionPurpose.PROGRESS,
        VisualActionPurpose.PROBE,
        VisualActionPurpose.PROGRESS,
    ]

    environment = _ProjectedWeightedHierarchyEnvironment(scene, hierarchy)
    initial_positions = dict(environment.positions)
    initial_colors = dict(environment.colors)
    initial_hash = visual_causal._child_isolation_protected_raster_hash(scene)
    policy = VisualCausalPolicy(max_coordinate_candidates=8)
    policy._level_index = 4
    policy._last_active_color = hierarchy.active_color
    policy._failed_child_isolation_hypothesis_keys.add(hypothesis_keys[3])
    policy._child_isolation_hypotheses_by_relation[relation_key] = frozenset(
        hypothesis_keys.values()
    )
    policy._current_child_isolation_hypothesis_keys = frozenset(hypothesis_keys.values())
    policy._install_child_isolation_plan(plan)
    observation = environment.observation()

    for expected in plan.actions:
        action = policy.select(observation)
        assert action.coordinate == expected.coordinate
        observation = environment.step(action)
        returned_scene = extract_visual_scene(observation.frames[-1])
        assert visual_causal._child_isolation_protected_raster_hash(returned_scene) == (
            expected.expected_child_protected_raster_hash
        )
        policy.accept_consequence(observation)
        assert policy.snapshot()["hierarchy_lineage_lost"] is False

    assert hypothesis_keys[2] in policy._failed_child_isolation_hypothesis_keys
    assert policy.snapshot()["child_isolation_hypothesis_rejected_count"] == 2
    assert policy.snapshot()["child_isolation_relation_rejected_count"] == 1
    assert policy.snapshot()["pending_plan_actions"] == 3

    for expected in plan.recovery_actions:
        action = policy.select(observation)
        assert action.coordinate == expected.coordinate
        observation = environment.step(action)
        returned_scene = extract_visual_scene(observation.frames[-1])
        assert visual_causal._child_isolation_protected_raster_hash(returned_scene) == (
            expected.expected_child_protected_raster_hash
        )
        policy.accept_consequence(observation)
        assert policy.snapshot()["hierarchy_lineage_lost"] is False

    restored_scene = extract_visual_scene(observation.frames[-1])
    assert visual_causal._child_isolation_protected_raster_hash(restored_scene) == initial_hash
    assert environment.positions == initial_positions
    assert environment.colors == initial_colors
    assert policy.snapshot()["pending_plan_actions"] == 0
    assert policy.receipts[-1].residual == (
        "exact pre-discriminator hierarchy restored after child-only sufficiency was falsified"
    )


def test_active_arity_two_forward_corruption_does_not_reject_its_stratum() -> None:
    scene = extract_visual_scene(_campaign26_weighted_origin_frame())
    hierarchy = visual_causal._unique_affine_hierarchy(scene, active_color=0)
    assert hierarchy is not None
    relation_key = visual_causal._hierarchy_relation_key(scene, hierarchy, level_index=4)
    hypothesis_keys = {
        child.arity: visual_causal._child_isolation_hypothesis_key(
            scene,
            child,
            relation_key=relation_key,
        )
        for child in hierarchy.children
    }
    plan = visual_causal._child_isolation_plan(
        scene,
        hierarchy,
        level_index=4,
        rejected_signatures=set(),
        rejected_hypothesis_keys={hypothesis_keys[3]},
    )
    assert plan is not None
    environment = _ProjectedWeightedHierarchyEnvironment(scene, hierarchy)
    policy = VisualCausalPolicy(max_coordinate_candidates=8)
    policy._level_index = 4
    policy._last_active_color = hierarchy.active_color
    policy._failed_child_isolation_hypothesis_keys.add(hypothesis_keys[3])
    policy._child_isolation_hypotheses_by_relation[relation_key] = frozenset(
        hypothesis_keys.values()
    )
    policy._current_child_isolation_hypothesis_keys = frozenset(hypothesis_keys.values())
    policy._install_child_isolation_plan(plan)
    observation = environment.observation()

    action = policy.select(observation)
    plan_signature = policy._pending_plan_signature
    assert plan_signature is not None
    returned = environment.step(action)
    rows = [list(row) for row in returned.frames[-1].cells]
    rows[1][1] = 6
    corrupted = replace(returned, frames=(GridFrame.from_rows(rows),))
    policy.accept_consequence(corrupted)

    assert hypothesis_keys[3] in policy._failed_child_isolation_hypothesis_keys
    assert hypothesis_keys[2] not in policy._failed_child_isolation_hypothesis_keys
    assert plan_signature in policy._failed_plan_signatures
    assert policy.snapshot()["child_isolation_hypothesis_rejected_count"] == 1
    assert policy.snapshot()["child_isolation_relation_rejected_count"] == 0
    assert policy.snapshot()["hierarchy_lineage_lost"] is True
    assert policy.snapshot()["pending_plan_actions"] == 0


def test_active_arity_two_recovery_corruption_latches_lineage() -> None:
    scene = extract_visual_scene(_campaign26_weighted_origin_frame())
    hierarchy = visual_causal._unique_affine_hierarchy(scene, active_color=0)
    assert hierarchy is not None
    relation_key = visual_causal._hierarchy_relation_key(scene, hierarchy, level_index=4)
    hypothesis_keys = {
        child.arity: visual_causal._child_isolation_hypothesis_key(
            scene,
            child,
            relation_key=relation_key,
        )
        for child in hierarchy.children
    }
    plan = visual_causal._child_isolation_plan(
        scene,
        hierarchy,
        level_index=4,
        rejected_signatures=set(),
        rejected_hypothesis_keys={hypothesis_keys[3]},
    )
    assert plan is not None
    environment = _ProjectedWeightedHierarchyEnvironment(scene, hierarchy)
    policy = VisualCausalPolicy(max_coordinate_candidates=8)
    policy._level_index = 4
    policy._last_active_color = hierarchy.active_color
    policy._failed_child_isolation_hypothesis_keys.add(hypothesis_keys[3])
    policy._child_isolation_hypotheses_by_relation[relation_key] = frozenset(
        hypothesis_keys.values()
    )
    policy._current_child_isolation_hypothesis_keys = frozenset(hypothesis_keys.values())
    policy._install_child_isolation_plan(plan)
    observation = environment.observation()

    for expected in plan.actions:
        action = policy.select(observation)
        assert action.coordinate == expected.coordinate
        observation = environment.step(action)
        policy.accept_consequence(observation)

    recovery = policy.select(observation)
    recovery_signature = policy._pending_plan_signature
    assert recovery_signature is not None
    returned = environment.step(recovery)
    rows = [list(row) for row in returned.frames[-1].cells]
    rows[1][1] = 6
    corrupted = replace(returned, frames=(GridFrame.from_rows(rows),))
    policy.accept_consequence(corrupted)

    assert recovery_signature in policy._failed_plan_signatures
    assert set(hypothesis_keys.values()) <= policy._failed_child_isolation_hypothesis_keys
    assert policy.receipts[-1].residual == (
        "planned child-recovery inverse certificate was not structurally readable"
    )
    assert policy.snapshot()["hierarchy_lineage_lost"] is True
    assert policy.snapshot()["child_isolation_hypothesis_rejected_count"] == 2
    assert policy.snapshot()["pending_plan_actions"] == 0


def test_active_arity_two_queued_inverse_precondition_mismatch_fails_closed() -> None:
    scene = extract_visual_scene(_campaign26_weighted_origin_frame())
    hierarchy = visual_causal._unique_affine_hierarchy(scene, active_color=0)
    assert hierarchy is not None
    relation_key = visual_causal._hierarchy_relation_key(scene, hierarchy, level_index=4)
    hypothesis_keys = {
        child.arity: visual_causal._child_isolation_hypothesis_key(
            scene,
            child,
            relation_key=relation_key,
        )
        for child in hierarchy.children
    }
    plan = visual_causal._child_isolation_plan(
        scene,
        hierarchy,
        level_index=4,
        rejected_signatures=set(),
        rejected_hypothesis_keys={hypothesis_keys[3]},
    )
    assert plan is not None
    environment = _ProjectedWeightedHierarchyEnvironment(scene, hierarchy)
    policy = VisualCausalPolicy(max_coordinate_candidates=8)
    policy._level_index = 4
    policy._last_active_color = hierarchy.active_color
    policy._failed_child_isolation_hypothesis_keys.add(hypothesis_keys[3])
    policy._child_isolation_hypotheses_by_relation[relation_key] = frozenset(
        hypothesis_keys.values()
    )
    policy._current_child_isolation_hypothesis_keys = frozenset(hypothesis_keys.values())
    policy._install_child_isolation_plan(plan)
    observation = environment.observation()

    for expected in plan.actions:
        action = policy.select(observation)
        assert action.coordinate == expected.coordinate
        observation = environment.step(action)
        policy.accept_consequence(observation)

    recovery = policy.select(observation)
    returned = environment.step(recovery)
    policy.accept_consequence(returned)
    assert len(policy._plan) == 2
    queued_signature = policy._plan[0].plan_signature
    rows = [list(row) for row in returned.frames[-1].cells]
    rows[1][1] = 6
    corrupted = replace(returned, frames=(GridFrame.from_rows(rows),))

    with pytest.raises(PolicyError, match="queued hierarchy precondition"):
        policy.select(corrupted)

    assert queued_signature in policy._failed_plan_signatures
    assert policy.snapshot()["hierarchy_lineage_lost"] is True
    assert policy.snapshot()["child_isolation_hypothesis_rejected_count"] == 2
    assert policy.snapshot()["pending_plan_actions"] == 0


def test_policy_selects_visible_node_weighting_only_after_smaller_hypotheses_fail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    environment = _TwoLayerAffineEnvironment()
    policy = VisualCausalPolicy(max_coordinate_candidates=8)
    observation = _reach_two_layer_hierarchy(environment, policy)
    scene = extract_visual_scene(observation.frames[-1])
    hierarchy = visual_causal._unique_affine_hierarchy(scene, active_color=0)
    assert hierarchy is not None
    relation_key = visual_causal._hierarchy_relation_key(
        scene,
        hierarchy,
        level_index=observation.levels_completed,
    )
    hypothesis_keys = frozenset(
        visual_causal._child_isolation_hypothesis_key(
            scene,
            child,
            relation_key=relation_key,
        )
        for child in hierarchy.children
    )
    policy._failed_child_isolation_hypothesis_keys.update(hypothesis_keys)
    policy._failed_hierarchy_relation_keys.add(relation_key)
    policy._failed_weighted_hierarchy_relation_keys.add(relation_key)

    def reject_smaller_planner(*_args: object, **_kwargs: object) -> None:
        pytest.fail("an already-falsified smaller hierarchy hypothesis was replanned")

    visible_calls = 0

    class VisibleNodeSelected(RuntimeError):
        pass

    def mark_visible_node_selection(
        candidate_scene: visual_causal.VisualScene,
        candidate_hierarchy: visual_causal._AffineHierarchy,
        *,
        rejected_signatures: set[str],
        search_budget: visual_causal._HierarchySearchBudget | None = None,
    ) -> None:
        nonlocal visible_calls
        assert candidate_scene == scene
        assert candidate_hierarchy == hierarchy
        assert rejected_signatures is policy._failed_plan_signatures
        assert search_budget is not None
        visible_calls += 1
        raise VisibleNodeSelected

    monkeypatch.setattr(visual_causal, "_child_isolation_plan", reject_smaller_planner)
    monkeypatch.setattr(visual_causal, "_hierarchy_joint_layout", reject_smaller_planner)
    monkeypatch.setattr(
        visual_causal,
        "_hierarchy_visible_node_layout",
        mark_visible_node_selection,
    )

    with pytest.raises(VisibleNodeSelected):
        policy.select(observation)

    assert visible_calls == 1
    assert policy._pending_plan_signature is None
    assert relation_key not in policy._failed_visible_node_hierarchy_relation_keys


def test_all_child_equal_weighted_and_visible_node_hypotheses_exhaustion_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    environment = _TwoLayerAffineEnvironment()
    policy = VisualCausalPolicy(max_coordinate_candidates=8)
    observation = _reach_two_layer_hierarchy(environment, policy)
    scene = extract_visual_scene(observation.frames[-1])
    hierarchy = visual_causal._unique_affine_hierarchy(scene, active_color=0)
    assert hierarchy is not None
    relation_key = visual_causal._hierarchy_relation_key(
        scene,
        hierarchy,
        level_index=observation.levels_completed,
    )
    hypothesis_keys = frozenset(
        visual_causal._child_isolation_hypothesis_key(
            scene,
            child,
            relation_key=relation_key,
        )
        for child in hierarchy.children
    )
    assert len(hypothesis_keys) == 2
    policy._failed_child_isolation_hypothesis_keys.update(hypothesis_keys)
    policy._failed_hierarchy_relation_keys.add(relation_key)
    policy._failed_weighted_hierarchy_relation_keys.add(relation_key)
    policy._failed_visible_node_hierarchy_relation_keys.add(relation_key)

    def reject_unfalsified_planner(*_args: object, **_kwargs: object) -> None:
        pytest.fail("a falsified hierarchy hypothesis was replanned")

    def reject_raw_fallback(*_args: object, **_kwargs: object) -> Coordinate:
        pytest.fail("uncertified hierarchy fallback was called")

    monkeypatch.setattr(visual_causal, "_child_isolation_plan", reject_unfalsified_planner)
    monkeypatch.setattr(visual_causal, "_hierarchy_joint_layout", reject_unfalsified_planner)
    monkeypatch.setattr(visual_causal, "_hierarchy_weighted_layout", reject_unfalsified_planner)
    monkeypatch.setattr(
        visual_causal,
        "_hierarchy_visible_node_layout",
        reject_unfalsified_planner,
    )
    monkeypatch.setattr(policy, "_activation_coordinate", reject_raw_fallback)
    monkeypatch.setattr(policy, "_probe_coordinate", reject_raw_fallback)

    with pytest.raises(
        PolicyError,
        match="all structurally distinct child-only sufficiency",
    ):
        policy.select(observation)

    snapshot = policy.snapshot()
    assert policy._pending_action is None
    assert snapshot["child_isolation_hypothesis_rejected_count"] == 2
    assert snapshot["child_isolation_remaining_strata_count"] == 0
    assert snapshot["child_isolation_relation_rejected_count"] == 1
    assert snapshot["hierarchy_hypothesis_rejected_count"] == 3
    assert snapshot["hierarchy_visible_node_relation_rejected_count"] == 1
    assert snapshot["pending_plan_actions"] == 0


def test_weighted_move_order_sample_covers_first_and_active_successor_roles() -> None:
    for endpoint_count in range(2, 13):
        mover_refs = ("active", *(f"endpoint-{index}" for index in range(1, endpoint_count)))
        orders = visual_causal._bounded_weighted_move_orders(
            mover_refs,
            active_ref="active",
        )

        assert len(set(orders)) == len(orders)
        assert all(
            len(order) == len(mover_refs) and set(order) == set(mover_refs) for order in orders
        )
        assert {order[0] for order in orders} == set(mover_refs)
        assert {order[1] for order in orders if order[0] == "active"} == set(mover_refs) - {
            "active"
        }
    assert visual_causal._bounded_weighted_move_orders(
        ("active", "endpoint-b"),
        active_ref="active",
    ) == (("active", "endpoint-b"), ("endpoint-b", "active"))


def test_weighted_layout_continues_past_safe_high_gap_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scene = extract_visual_scene(_campaign26_weighted_origin_frame())
    hierarchy = visual_causal._unique_affine_hierarchy(scene, active_color=0)
    assert hierarchy is not None
    observed_orders: list[tuple[str, ...]] = []
    built_plans: list[visual_causal._HierarchyPlan] = []
    original_build = visual_causal._build_hierarchy_plan

    monkeypatch.setattr(
        visual_causal,
        "_weighted_translation_support_candidates",
        lambda _hierarchy: (((47, 19), (57, 34)),),
    )

    def staged_certificate(
        _scene: VisualScene,
        _hierarchy: object,
        _layouts: object,
        *,
        move_order: tuple[str, ...],
        static_cells: frozenset[tuple[int, int]],
        target_regions: object,
        search_budget: object,
        support_weights: tuple[int, ...],
    ) -> int:
        del static_cells, target_regions, search_budget, support_weights
        observed_orders.append(move_order)
        return 4 if len(observed_orders) == 1 else 1

    def recording_build(
        hierarchy_arg: visual_causal._AffineHierarchy,
        layouts: tuple[visual_causal._HierarchyChildLayout, ...],
        **kwargs: object,
    ) -> visual_causal._HierarchyPlan:
        plan = original_build(hierarchy_arg, layouts, **kwargs)
        built_plans.append(plan)
        return plan

    monkeypatch.setattr(
        visual_causal,
        "_hierarchy_interleaved_sequence_is_certified",
        staged_certificate,
    )
    monkeypatch.setattr(visual_causal, "_build_hierarchy_plan", recording_build)

    plan = visual_causal._hierarchy_weighted_layout(
        scene,
        hierarchy,
        rejected_signatures=set(),
    )

    assert plan is not None
    assert len(observed_orders) == 2
    assert observed_orders[0] != observed_orders[1]
    assert len(built_plans) == 2
    assert plan.signature == built_plans[1].signature


def test_weighted_child_layout_cap_keeps_eight_distinct_frozen_candidates() -> None:
    scene = extract_visual_scene(_campaign26_weighted_origin_frame())
    hierarchy = visual_causal._unique_affine_hierarchy(scene, active_color=0)
    assert hierarchy is not None
    target_regions = visual_causal._visible_target_regions(scene)
    initial_dynamic = frozenset(
        cell
        for child in hierarchy.children
        for cell in visual_causal._hierarchy_dynamic_footprint(scene, child)
    )
    occupied = frozenset(
        (x, y)
        for y, row in enumerate(scene.cells)
        for x, value in enumerate(row)
        if value != scene.background
    )
    static_cells = occupied - initial_dynamic
    ignored_refs = frozenset(
        item.object_ref
        for child in hierarchy.children
        for item in (*child.endpoints, child.mediator)
    )
    active = tuple(
        endpoint
        for child in hierarchy.children
        for endpoint in child.endpoints
        if endpoint.color == hierarchy.active_color
    )
    assert len(active) == 1

    for child, support in zip(
        hierarchy.children,
        ((47, 19), (57, 34)),
        strict=True,
    ):
        active_ref = (
            active[0].object_ref
            if any(endpoint.object_ref == active[0].object_ref for endpoint in child.endpoints)
            else None
        )
        layouts = visual_causal._hierarchy_child_layouts(
            scene,
            hierarchy,
            child,
            support=support,
            active_ref=active_ref,
            static_cells=static_cells,
            target_regions=target_regions,
            ignored_refs=ignored_refs,
            search_budget=visual_causal._HierarchySearchBudget(
                visual_causal._MAX_HIERARCHY_SEARCH_BUDGET
            ),
            result_limit=visual_causal._MAX_HIERARCHY_CHILD_LAYOUTS,
        )
        identities = {
            (tuple(item.object_ref for item in layout.movers), layout.points) for layout in layouts
        }

        assert len(layouts) == visual_causal._MAX_HIERARCHY_CHILD_LAYOUTS
        assert len(identities) == len(layouts)


def test_ignored_final_hierarchy_action_preserves_structural_failure() -> None:
    environment = _TwoLayerAffineEnvironment()
    policy = VisualCausalPolicy(max_coordinate_candidates=8)
    observation = environment.observation()

    for _ in range(12):
        action = policy.select(observation)
        observation = environment.step(action)
        policy.accept_consequence(observation)
        if observation.levels_completed == 1:
            break
    assert observation.levels_completed == 1

    _install_joint_hierarchy_for_test(policy, observation)

    ignored_final_action = False
    for _ in range(20):
        action = policy.select(observation)
        if policy._pending_completes_hierarchy:
            ignored_final_action = True
            observation = environment.observation(returned_action=action)
            policy.accept_consequence(observation)
            break
        observation = environment.step(action)
        policy.accept_consequence(observation)

    assert ignored_final_action
    assert observation.state is GameStateName.NOT_FINISHED
    assert observation.levels_completed == 1
    assert policy.receipts[-1].changed_cells == 0
    assert (
        policy.receipts[-1].residual
        == "planned hierarchy consequence was not structurally readable"
    )
    snapshot = policy.snapshot()
    assert snapshot["hierarchy_active"] is False
    assert snapshot["hierarchy_supports"] == []
    assert snapshot["pending_plan_actions"] == 0
    assert snapshot["hierarchy_rejected_count"] == 1
    assert policy._last_probe_failed is True


def test_structurally_complete_not_finished_hierarchy_is_rejected_across_reset() -> None:
    environment = _TwoLayerAffineEnvironment(win_on_hierarchy=False)
    policy = VisualCausalPolicy(max_coordinate_candidates=8)
    observation = _reach_two_layer_hierarchy(environment, policy)
    initial_scene = extract_visual_scene(observation.frames[-1])
    initial_hierarchy = visual_causal._unique_affine_hierarchy(
        initial_scene,
        active_color=0,
    )
    assert initial_hierarchy is not None
    relation_key = visual_causal._hierarchy_relation_key(
        initial_scene,
        initial_hierarchy,
        level_index=observation.levels_completed,
    )
    _install_joint_hierarchy_for_test(policy, observation)
    recovery_action_count = len(policy._active_hierarchy_recovery_actions)
    initial_groups = tuple(tuple(group) for group in environment.groups)
    initial_active = (environment.active_group, environment.active_index)

    completed = False
    for _ in range(20):
        action = policy.select(observation)
        completes_hierarchy = policy._pending_completes_hierarchy
        observation = environment.step(action)
        policy.accept_consequence(observation)
        if completes_hierarchy:
            completed = True
            break

    assert completed
    assert observation.state is GameStateName.NOT_FINISHED
    assert policy.receipts[-1].residual == (
        "distinct child mediators reached the predicted parent centroid but "
        "the official environment remained NOT_FINISHED"
    )
    returned_scene = extract_visual_scene(observation.frames[-1])
    returned_hierarchy = visual_causal._unique_affine_hierarchy(
        returned_scene,
        active_color=0,
    )
    assert returned_hierarchy is not None
    assert (
        visual_causal._hierarchy_relation_key(
            returned_scene,
            returned_hierarchy,
            level_index=observation.levels_completed,
        )
        == relation_key
    )
    assert policy._failed_hierarchy_relation_keys == {relation_key}
    assert policy.snapshot()["hierarchy_relation_rejected_count"] == 1
    assert policy._last_probe_failed is False
    assert len(policy._plan) == recovery_action_count

    for recovery_index in range(recovery_action_count):
        recovery_action = policy.select(observation)
        assert policy._pending_plan_signature is not None
        assert policy._pending_plan_signature.startswith("affine-hierarchy-recovery:")
        observation = environment.step(recovery_action)
        policy.accept_consequence(observation)
        if recovery_index + 1 < recovery_action_count:
            assert policy.snapshot()["hierarchy_active"] is True

    assert tuple(tuple(group) for group in environment.groups) == initial_groups
    assert (environment.active_group, environment.active_index) == initial_active
    assert policy.receipts[-1].residual == (
        "exact pre-hypothesis hierarchy restored after joint sufficiency failed"
    )
    assert policy.snapshot()["hierarchy_active"] is False
    assert policy.snapshot()["pending_plan_actions"] == 0

    alternative = policy.select(observation)
    assert alternative.name is ActionName.ACTION6
    assert policy._pending_plan_signature is not None
    assert policy._pending_plan_signature.startswith("affine-child-isolation:")
    failed = replace(
        observation,
        state=GameStateName.GAME_OVER,
        returned_action=alternative,
    )
    policy.accept_consequence(failed)
    reset = policy.select(failed)
    recovered = replace(
        observation,
        full_reset=False,
        returned_action=reset,
    )
    policy.accept_consequence(recovered)

    assert reset == ActionRequest(ActionName.RESET)
    assert policy._failed_hierarchy_relation_keys == {relation_key}
    assert policy._failed_child_isolation_relation_keys == set()
    retry = policy.select(recovered)
    assert retry.name is ActionName.ACTION6
    assert policy._pending_plan_signature is not None
    assert policy._pending_plan_signature.startswith("affine-child-isolation:")

    advanced = replace(
        recovered,
        levels_completed=2,
        win_levels=3,
        returned_action=retry,
    )
    policy.accept_consequence(advanced)
    assert policy.snapshot()["hierarchy_relation_rejected_count"] == 0
    assert policy.snapshot()["child_isolation_relation_rejected_count"] == 0


def test_terminal_joint_hierarchy_raster_mismatch_does_not_falsify_relation() -> None:
    environment = _TwoLayerAffineEnvironment(win_on_hierarchy=False)
    policy = VisualCausalPolicy(max_coordinate_candidates=8)
    observation = _reach_two_layer_hierarchy(environment, policy)
    scene = extract_visual_scene(observation.frames[-1])
    hierarchy = _install_joint_hierarchy_for_test(policy, observation)
    relation_key = visual_causal._hierarchy_relation_key(
        scene,
        hierarchy,
        level_index=observation.levels_completed,
    )

    for _ in range(20):
        action = policy.select(observation)
        completes_hierarchy = policy._pending_completes_hierarchy
        observation = environment.step(action)
        if completes_hierarchy:
            observation = _replace_observation_cell(
                observation,
                coordinate=(63, 63),
                value=9,
            )
        policy.accept_consequence(observation)
        if completes_hierarchy:
            break
    else:
        pytest.fail("joint hierarchy plan did not reach its terminal action")

    assert relation_key not in policy._failed_hierarchy_relation_keys
    assert policy._hierarchy_lineage_lost is not None
    assert policy.snapshot()["pending_plan_actions"] == 0
    with pytest.raises(PolicyError, match="hierarchy lineage was lost"):
        policy.select(observation)


@pytest.mark.parametrize("mismatch_index", [0, 4, 8])
def test_joint_hierarchy_recovery_raster_mismatch_latches_lineage(
    mismatch_index: int,
) -> None:
    environment = _TwoLayerAffineEnvironment(win_on_hierarchy=False)
    policy = VisualCausalPolicy(max_coordinate_candidates=8)
    observation = _reach_two_layer_hierarchy(environment, policy)
    scene = extract_visual_scene(observation.frames[-1])
    hierarchy = _install_joint_hierarchy_for_test(policy, observation)
    relation_key = visual_causal._hierarchy_relation_key(
        scene,
        hierarchy,
        level_index=observation.levels_completed,
    )

    for _ in range(20):
        action = policy.select(observation)
        completes_hierarchy = policy._pending_completes_hierarchy
        observation = environment.step(action)
        policy.accept_consequence(observation)
        if completes_hierarchy:
            break
    else:
        pytest.fail("joint hierarchy plan did not reach its terminal action")

    assert relation_key in policy._failed_hierarchy_relation_keys
    assert len(policy._plan) == 9
    for recovery_index in range(mismatch_index + 1):
        action = policy.select(observation)
        observation = environment.step(action)
        if recovery_index == mismatch_index:
            observation = _replace_observation_cell(
                observation,
                coordinate=(63, 63),
                value=9,
            )
        policy.accept_consequence(observation)

    assert policy._hierarchy_lineage_lost is not None
    assert policy.snapshot()["pending_plan_actions"] == 0
    with pytest.raises(PolicyError, match="hierarchy lineage was lost"):
        policy.select(observation)


def test_hierarchy_child_layouts_reject_zero_displacement_progress() -> None:
    environment = _TwoLayerAffineEnvironment(win_on_hierarchy=False)
    policy = VisualCausalPolicy(max_coordinate_candidates=8)
    observation = _reach_two_layer_hierarchy(environment, policy)
    scene = extract_visual_scene(observation.frames[-1])
    hierarchy = visual_causal._unique_affine_hierarchy(scene, active_color=0)
    assert hierarchy is not None
    plan = visual_causal._hierarchy_joint_layout(
        scene,
        hierarchy,
        rejected_signatures=set(),
    )
    assert plan is not None
    for planned in plan.actions:
        observation = environment.step(ActionRequest(ActionName.ACTION6, planned.coordinate))

    completed_scene = extract_visual_scene(observation.frames[-1])
    completed_hierarchy = visual_causal._unique_affine_hierarchy(
        completed_scene,
        active_color=0,
    )
    assert completed_hierarchy is not None
    initial_dynamic = frozenset(
        cell
        for child in completed_hierarchy.children
        for cell in visual_causal._hierarchy_dynamic_footprint(completed_scene, child)
    )
    occupied = frozenset(
        (x, y)
        for y, row in enumerate(completed_scene.cells)
        for x, value in enumerate(row)
        if value != completed_scene.background
    )
    static_cells = occupied - initial_dynamic
    target_regions = visual_causal._visible_target_regions(completed_scene)
    ignored_refs = frozenset(
        item.object_ref
        for child in completed_hierarchy.children
        for item in (*child.endpoints, child.mediator)
    )

    for child_index, child in enumerate(completed_hierarchy.children):
        active = tuple(endpoint for endpoint in child.endpoints if endpoint.color == 0)
        active_ref = active[0].object_ref if child_index == 0 else None
        layouts = visual_causal._hierarchy_child_layouts(
            completed_scene,
            completed_hierarchy,
            child,
            support=child.mediator.rounded_center,
            active_ref=active_ref,
            static_cells=static_cells,
            target_regions=target_regions,
            ignored_refs=ignored_refs,
            search_budget=visual_causal._HierarchySearchBudget(
                visual_causal._MAX_HIERARCHY_SEARCH_BUDGET
            ),
        )

        assert layouts
        assert all(layout.movement_cost > 0 for layout in layouts)
        assert all(
            mover.rounded_center != point
            for layout in layouts
            for mover, point in zip(layout.movers, layout.points, strict=True)
        )


def test_hierarchy_no_solution_has_one_deterministic_global_evaluation_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scene = extract_visual_scene(_two_layer_affine_frame())
    hierarchy = visual_causal._unique_affine_hierarchy(scene, active_color=0)
    assert hierarchy is not None

    def two_parent_candidates(
        center: tuple[int, int],
        *,
        arity: int,
        radius: int,
        rotation_index: int,
    ) -> tuple[tuple[int, int], ...] | None:
        if (
            center == hierarchy.target.rounded_center
            and arity == len(hierarchy.children)
            and radius == 16
            and rotation_index in {0, 1}
        ):
            return ((48, 16), (16, 16))
        return None

    def many_child_layouts(
        _scene: VisualScene,
        _hierarchy: object,
        group: object,
        *,
        support: tuple[int, int],
        active_ref: str | None,
        static_cells: frozenset[tuple[int, int]],
        target_regions: object,
        ignored_refs: frozenset[str],
        search_budget: object,
    ) -> tuple[object, ...]:
        del active_ref, static_cells, target_regions, ignored_refs, search_budget
        child = next(item for item in hierarchy.children if item == group)
        child_index = hierarchy.children.index(child)
        expected_support = (16, 16) if child_index == 0 else (48, 16)
        if support != expected_support:
            return ()
        return tuple(
            visual_causal._HierarchyChildLayout(
                group=child,
                support=support,
                movers=child.endpoints,
                points=tuple(endpoint.rounded_center for endpoint in child.endpoints),
                dynamic_footprint=frozenset({(child_index + 1, 1)}),
                radius=6,
                movement_cost=float(index),
            )
            for index in range(32)
        )

    monkeypatch.setattr(
        visual_causal,
        "_regular_exact_centroid_points",
        two_parent_candidates,
    )
    monkeypatch.setattr(visual_causal, "_hierarchy_child_layouts", many_child_layouts)

    evaluation_counts: list[int] = []
    for _ in range(2):
        evaluated = 0

        def reject_candidate(*_args: object, **_kwargs: object) -> bool:
            nonlocal evaluated
            evaluated += 1
            return False

        monkeypatch.setattr(
            visual_causal,
            "_hierarchy_sequence_is_safe",
            reject_candidate,
        )
        with pytest.raises(
            visual_causal._HierarchySearchExhausted,
            match="affine hierarchy deterministic search budget exhausted",
        ):
            visual_causal._hierarchy_joint_layout(
                scene,
                hierarchy,
                rejected_signatures=set(),
            )
        evaluation_counts.append(evaluated)

    assert evaluation_counts[0] == evaluation_counts[1]
    assert (
        0
        < evaluation_counts[0]
        <= visual_causal._MAX_HIERARCHY_SEARCH_BUDGET
        // visual_causal._HIERARCHY_SEQUENCE_EVALUATION_COST
    )


def test_six_child_support_orders_are_fair_before_the_120_assignment_cap() -> None:
    scene = extract_visual_scene(_two_layer_affine_frame())
    hierarchy = visual_causal._unique_affine_hierarchy(scene, active_color=0)
    assert hierarchy is not None
    raw_supports = ((8, 8), (16, 8), (24, 8), (32, 8), (40, 8), (48, 8))
    six_child_hierarchy = replace(
        hierarchy,
        children=tuple(hierarchy.children[0] for _ in raw_supports),
    )

    orders = visual_causal._fair_support_orders(
        six_child_hierarchy,
        raw_supports,
        limit=120,
    )

    assert len(orders) == 120
    first_occurrence = {
        support: next(index for index, order in enumerate(orders) if order[0] == support)
        for support in raw_supports
    }
    assert set(first_occurrence) == set(raw_supports)
    assert max(first_occurrence.values()) < 120
    assert orders == visual_causal._fair_support_orders(
        six_child_hierarchy,
        raw_supports,
        limit=120,
    )


@pytest.mark.parametrize(
    ("deferred_mode", "expected_residual"),
    (
        (
            "no-layout",
            "readable affine hierarchy has no bounded target-protected layout for its "
            "next unfalsified composition hypothesis",
        ),
        (
            "budget-exhausted",
            "affine hierarchy deterministic search budget exhausted",
        ),
    ),
)
def test_policy_defers_unavailable_hierarchy_layout_without_flat_reuse(
    monkeypatch: pytest.MonkeyPatch,
    deferred_mode: str,
    expected_residual: str,
) -> None:
    environment = _TwoLayerAffineEnvironment()
    policy = VisualCausalPolicy(max_coordinate_candidates=8)
    observation = environment.observation()

    for _ in range(12):
        action = policy.select(observation)
        observation = environment.step(action)
        policy.accept_consequence(observation)
        if observation.levels_completed == 1:
            break
    assert observation.levels_completed == 1

    def unavailable_layout(*_args: object, **_kwargs: object) -> None:
        if deferred_mode == "budget-exhausted":
            raise visual_causal._HierarchySearchExhausted(expected_residual)
        return None

    monkeypatch.setattr(
        visual_causal,
        "_hierarchy_joint_layout",
        unavailable_layout,
    )
    monkeypatch.setattr(
        visual_causal,
        "_child_isolation_plan",
        lambda *_args, **_kwargs: None,
    )
    scene = extract_visual_scene(observation.frames[-1])
    hierarchy = visual_causal._unique_affine_hierarchy(scene, active_color=0)
    assert hierarchy is not None

    with pytest.raises(
        PolicyError,
        match="no parser-safe target-preserving continuation",
    ) as exc_info:
        policy.select(observation)

    assert expected_residual in str(exc_info.value)
    assert policy._pending_action is None
    assert policy._pending_plan_signature is None
    assert policy._pending_target_center is None
    assert policy._pending_completes_local_target is False
    snapshot = policy.snapshot()
    assert snapshot["hierarchy_search_deferred_count"] == 1
    assert snapshot["hierarchy_search_residual"] == expected_residual
    assert snapshot["hierarchy_active"] is False
    assert snapshot["hierarchy_supports"] == []
    assert snapshot["pending_plan_actions"] == 0


def test_exhausted_readable_hierarchy_never_falls_back_to_coordinate_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    environment = _TwoLayerAffineEnvironment()
    policy = VisualCausalPolicy(max_coordinate_candidates=8)
    observation = _reach_two_layer_hierarchy(environment, policy)
    scene = extract_visual_scene(observation.frames[-1])
    hierarchy = visual_causal._unique_affine_hierarchy(scene, active_color=0)
    assert hierarchy is not None

    monkeypatch.setattr(
        visual_causal,
        "_child_isolation_plan",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        visual_causal,
        "_hierarchy_joint_layout",
        lambda *_args, **_kwargs: None,
    )

    def reject_unsafe_fallback(*_args: object, **_kwargs: object) -> Coordinate:
        pytest.fail("uncertified hierarchy fallback was called")

    monkeypatch.setattr(policy, "_activation_coordinate", reject_unsafe_fallback)
    monkeypatch.setattr(policy, "_probe_coordinate", reject_unsafe_fallback)

    with pytest.raises(
        PolicyError,
        match="no parser-safe target-preserving continuation",
    ):
        policy.select(observation)

    assert policy._pending_action is None
    assert observation.frames[-1].digest == environment.observation().frames[-1].digest


def test_hierarchy_recognition_exhaustion_never_uses_raw_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    environment = _TwoLayerAffineEnvironment()
    policy = VisualCausalPolicy(max_coordinate_candidates=8)
    observation = _reach_two_layer_hierarchy(environment, policy)
    residual = "affine hierarchy recognition budget exhausted"

    def exhaust_recognition(*_args: object, **_kwargs: object) -> None:
        raise visual_causal._HierarchySearchExhausted(residual)

    def reject_raw_fallback(*_args: object, **_kwargs: object) -> Coordinate:
        pytest.fail("uncertified raw hierarchy fallback was called")

    monkeypatch.setattr(visual_causal, "_unique_affine_hierarchy", exhaust_recognition)
    monkeypatch.setattr(policy, "_activation_coordinate", reject_raw_fallback)
    monkeypatch.setattr(policy, "_probe_coordinate", reject_raw_fallback)

    with pytest.raises(
        PolicyError,
        match="no parser-safe target-preserving continuation",
    ) as exc_info:
        policy.select(observation)

    assert residual in str(exc_info.value)
    assert policy._pending_action is None
    snapshot = policy.snapshot()
    assert snapshot["hierarchy_search_deferred_count"] == 1
    assert snapshot["hierarchy_search_residual"] == residual


def test_unrelated_centerline_occupant_rejects_hierarchy_plan() -> None:
    rows = [list(row) for row in _two_layer_affine_frame().cells]
    blocker = (16, 46)
    rows[blocker[1]][blocker[0]] = 9
    scene = extract_visual_scene(GridFrame.from_rows(rows))
    blocker_objects = tuple(item for item in scene.objects if blocker in item.cells)
    assert len(blocker_objects) == 1
    assert blocker_objects[0].role is VisualObjectRole.OTHER

    hierarchy = visual_causal._unique_affine_hierarchy(scene, active_color=0)
    assert hierarchy is not None
    observed_dynamic = frozenset(
        cell
        for child in hierarchy.children
        for cell in visual_causal._hierarchy_dynamic_footprint(scene, child)
    )
    assert blocker not in observed_dynamic
    assert scene.cells[blocker[1]][blocker[0]] != scene.background

    for _ in range(2):
        with pytest.raises(
            visual_causal._HierarchySearchExhausted,
            match="affine hierarchy deterministic search budget exhausted",
        ):
            visual_causal._hierarchy_joint_layout(
                scene,
                hierarchy,
                rejected_signatures=set(),
            )


def test_consequence_hierarchy_search_exhaustion_preserves_exact_raster_plan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    environment = _TwoLayerAffineEnvironment()
    policy = VisualCausalPolicy(max_coordinate_candidates=8)
    observation = environment.observation()

    for _ in range(12):
        action = policy.select(observation)
        observation = environment.step(action)
        policy.accept_consequence(observation)
        if observation.levels_completed == 1:
            break
    assert observation.levels_completed == 1

    _install_joint_hierarchy_for_test(policy, observation)
    hierarchy_action = policy.select(observation)
    hierarchy_signature = policy._pending_plan_signature
    assert hierarchy_signature is not None
    assert hierarchy_signature.startswith("affine-hierarchy:")
    failed_before = set(policy._failed_plan_signatures)
    returned = environment.step(hierarchy_action)
    assert returned.state is GameStateName.NOT_FINISHED
    exhaustion_calls = 0

    def exhaust_consequence_search(*_args: object, **_kwargs: object) -> None:
        nonlocal exhaustion_calls
        exhaustion_calls += 1
        raise visual_causal._HierarchySearchExhausted(
            "affine hierarchy deterministic search budget exhausted"
        )

    monkeypatch.setattr(
        visual_causal,
        "_unique_affine_hierarchy",
        exhaust_consequence_search,
    )

    policy.accept_consequence(returned)

    assert exhaustion_calls == 1
    assert policy.receipts[-1].after_state is GameStateName.NOT_FINISHED
    assert policy.receipts[-1].residual is not None
    assert "hierarchy" in policy.receipts[-1].residual
    assert (
        "search budget exhausted" in policy.receipts[-1].residual
        or "not structurally readable" in policy.receipts[-1].residual
    )
    assert policy._failed_plan_signatures == failed_before
    snapshot = policy.snapshot()
    assert snapshot["hierarchy_active"] is True
    assert snapshot["hierarchy_supports"]
    assert snapshot["pending_plan_actions"] > 0
    assert snapshot["hierarchy_rejected_count"] == sum(
        item.startswith("affine-hierarchy:") for item in failed_before
    )
    assert policy._last_probe_failed is False
    assert policy._pending_action is None

    continued_action = policy.select(returned)
    assert continued_action.name is ActionName.ACTION6
    assert continued_action.coordinate is not None
    assert policy._pending_plan_signature == hierarchy_signature
    assert policy._pending_completes_local_target is False


def test_isolated_same_color_cells_on_distinct_legs_remain_static() -> None:
    rows = [list(row) for row in _two_layer_affine_frame().cells]
    blockers = frozenset({(16, 46), (24, 46)})
    for x, y in blockers:
        rows[y][x] = 9
    scene = extract_visual_scene(GridFrame.from_rows(rows))
    blocker_objects = tuple(
        item for item in scene.objects if any(blocker in item.cells for blocker in blockers)
    )
    assert len(blocker_objects) == 2
    assert all(item.color == 9 for item in blocker_objects)
    assert all(item.area == 1 for item in blocker_objects)
    assert all(item.role is VisualObjectRole.OTHER for item in blocker_objects)

    hierarchy = visual_causal._unique_affine_hierarchy(scene, active_color=0)
    assert hierarchy is not None
    observed_dynamic = frozenset(
        cell
        for child in hierarchy.children
        for cell in visual_causal._hierarchy_dynamic_footprint(scene, child)
    )
    assert blockers.isdisjoint(observed_dynamic)
    assert all(scene.cells[y][x] == 9 for x, y in blockers)
