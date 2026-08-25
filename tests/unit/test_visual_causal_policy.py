from __future__ import annotations

import math
from dataclasses import dataclass, field, replace

import pytest

import arc3.mechanics.visual_causal as visual_causal
from arc3.adapters import GridFrame, Observation
from arc3.errors import PolicyError
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
