from __future__ import annotations

import math
from dataclasses import dataclass, field

import pytest

from arc3.adapters import GridFrame, Observation
from arc3.errors import PolicyError
from arc3.exploration.causal_events import RiskLevel
from arc3.mechanics.visual_causal import (
    VisualCausalPolicy,
    VisualObjectRole,
    VisualScene,
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

    mechanic = infer_transferred_affine_mechanic(
        scene,
        level_index=4,
        active_color=0,
        supported_prior=(prior,),
    )

    assert mechanic is not None
    assert mechanic.mechanic_ref.startswith("affine-transfer:")
    assert mechanic.arity == 3
    assert set(mechanic.anchor_centers) == {(28, 8), (18, 26)}
    assert mechanic.target_center == (25, 29)


def test_failed_target_relative_plan_signature_is_not_repeated() -> None:
    scene = extract_visual_scene(_frame((8, 32), (32, 32), (20, 10)))
    first = _radial_plan_points(
        scene,
        target=(20, 10),
        arity=2,
        rejected_signatures=set(),
    )
    assert first is not None
    signature = ";".join(f"{item.x},{item.y}" for item in first)

    second = _radial_plan_points(
        scene,
        target=(20, 10),
        arity=2,
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
    original_is_open = VisualScene.is_open

    def block_direct(
        scene: VisualScene,
        x: int,
        y: int,
        *,
        radius: int = 2,
    ) -> bool:
        if (x, y) == (blocked_direct.x, blocked_direct.y):
            return False
        return original_is_open(scene, x, y, radius=radius)

    monkeypatch.setattr(VisualScene, "is_open", block_direct)
    policy = VisualCausalPolicy()

    action = policy.select(environment.observation())

    assert action.coordinate != blocked_direct
    assert "marker-group" in policy._pending_prediction
    assert policy.snapshot()["pending_plan_actions"] == 0


def test_ambiguous_marker_active_role_fails_closed_without_legacy_relocation() -> None:
    environment = _MarkerAffineEnvironment(
        groups=[[(10, 50), (30, 50)], [(38, 52), (58, 52)]],
        targets=((20, 28), (48, 32)),
        marker_colors=(12, 14),
        active_color=3,
        fixed_color=3,
    )
    policy = VisualCausalPolicy()

    with pytest.raises(PolicyError, match="no bounded same-group action"):
        policy.select(environment.observation())

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
    selected = policy.select(observation)
    failed = _observation(
        environment.active,
        environment.anchor,
        environment.target,
        state=GameStateName.GAME_OVER,
        returned_action=selected,
    )

    policy.accept_consequence(failed)
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
    assert next_action != selected
