from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest
import test_visual_causal_policy as visual_policy_fixtures
from test_visual_causal_policy import (
    _ENDPOINT_SHAPE,
    _HIERARCHY_PARENT_TARGET,
    _install_joint_hierarchy_for_test,
    _reach_two_layer_hierarchy,
    _two_layer_affine_frame,
    _TwoLayerAffineEnvironment,
)

import arc3.mechanics.visual_causal as visual_causal
from arc3.adapters import GridFrame
from arc3.errors import PolicyError
from arc3.mechanics.visual_causal import (
    VisualActionPurpose,
    VisualCausalPolicy,
    _child_isolation_target_surface_signature,
    _hierarchy_connector_evidence,
    _hierarchy_projected_scene,
    _hierarchy_relation_key,
    _raster_line_cells,
    _unique_affine_hierarchy,
    extract_visual_scene,
)
from arc3.types import ActionName, GameStateName


def test_connector_raster_resolves_exact_ties_toward_the_endpoint_start() -> None:
    decreasing_x = _raster_line_cells((53, 36), (48, 46))
    increasing_y = _raster_line_cells((53, 17), (39, 26))

    assert (51, 41) in decreasing_x
    assert (50, 41) not in decreasing_x
    assert (46, 21) in increasing_y
    assert (46, 22) not in increasing_y


def test_connector_evidence_accepts_independently_rendered_start_tie_leg() -> None:
    groups = (
        ((10, 54), (28, 53)),
        ((41, 47), (52, 55), (53, 36)),
    )
    base = _two_layer_affine_frame(groups, active_group=1, active_index=2)
    rows = [list(row) for row in base.cells]

    def reference_line(
        start: tuple[int, int],
        end: tuple[int, int],
    ) -> frozenset[tuple[int, int]]:
        delta_x = end[0] - start[0]
        delta_y = end[1] - start[1]
        steps = max(abs(delta_x), abs(delta_y))
        cells: set[tuple[int, int]] = set()
        for step in range(steps + 1):
            coordinate: list[int] = []
            for origin, delta in ((start[0], delta_x), (start[1], delta_y)):
                quotient, remainder = divmod((origin * steps) + (delta * step), steps)
                if (2 * remainder) < steps:
                    rounded = quotient
                elif (2 * remainder) > steps:
                    rounded = quotient + 1
                else:
                    rounded = quotient if delta >= 0 else quotient + 1
                coordinate.append(rounded)
            cells.add((coordinate[0], coordinate[1]))
        return frozenset(cells)

    for endpoints in groups:
        mediator = (
            sum(x for x, _y in endpoints) // len(endpoints),
            sum(y for _x, y in endpoints) // len(endpoints),
        )
        for endpoint in endpoints:
            for x, y in reference_line(endpoint, mediator):
                if rows[y][x] == 5:
                    rows[y][x] = 9

    scene = extract_visual_scene(GridFrame.from_rows(rows))
    hierarchy = _unique_affine_hierarchy(scene, active_color=0)
    assert hierarchy is not None
    selected = next(child for child in hierarchy.children if child.arity == 3)
    connector = _hierarchy_connector_evidence(scene, selected)

    assert connector is not None
    color, cells = connector
    assert color == 9
    assert len(cells) == 13
    assert (51, 41) in cells
    assert (50, 41) not in cells


def test_hierarchy_projection_layers_mediator_over_an_overlapping_endpoint() -> None:
    scene = extract_visual_scene(_two_layer_affine_frame())
    hierarchy = _unique_affine_hierarchy(scene, active_color=0)
    assert hierarchy is not None
    selected = next(child for child in hierarchy.children if child.arity == 3)
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
    projected_centers = {
        (44, 48): (41, 47),
        (56, 48): (56, 31),
        (50, 36): (53, 36),
    }
    for endpoint in selected.endpoints:
        positions[endpoint.object_ref] = projected_centers[endpoint.rounded_center]

    projected = _hierarchy_projected_scene(
        scene,
        hierarchy,
        positions=positions,
        colors=colors,
    )

    # The recomputed mediator is centered at (50, 38).  Its outer glyph
    # occludes the stationary endpoint at (53, 36) on the official surface.
    assert projected.cells[36][51] == selected.mediator.color
    assert len(projected.endpoints) == len(scene.endpoints) - 1


def _occluded_child_certificate_fixture() -> tuple[
    visual_causal.VisualScene,
    dict[str, Any],
]:
    scene = extract_visual_scene(_two_layer_affine_frame(connector_color=9))
    hierarchy = _unique_affine_hierarchy(scene, active_color=0)
    assert hierarchy is not None
    active_group = next(child for child in hierarchy.children if child.arity == 2)
    inactive_group = next(child for child in hierarchy.children if child.arity == 3)
    active = next(endpoint for endpoint in active_group.endpoints if endpoint.color == 0)
    activation = next(
        endpoint for endpoint in inactive_group.endpoints if endpoint.rounded_center == (44, 48)
    )
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
    colors[active.object_ref], colors[activation.object_ref] = (
        colors[activation.object_ref],
        colors[active.object_ref],
    )
    role_scene = _hierarchy_projected_scene(
        scene,
        hierarchy,
        positions=positions,
        colors=colors,
    )
    role_hierarchy = _unique_affine_hierarchy(role_scene, active_color=0)
    assert role_hierarchy is not None
    selected = next(child for child in role_hierarchy.children if child.arity == 3)
    frozen = next(child for child in role_hierarchy.children if child.arity == 2)
    positions = {
        endpoint.object_ref: endpoint.rounded_center
        for child in role_hierarchy.children
        for endpoint in child.endpoints
    }
    colors = {
        endpoint.object_ref: endpoint.color
        for child in role_hierarchy.children
        for endpoint in child.endpoints
    }
    projected_centers = {
        (44, 48): (41, 47),
        (56, 48): (56, 31),
        (50, 36): (53, 36),
    }
    for endpoint in selected.endpoints:
        positions[endpoint.object_ref] = projected_centers[endpoint.rounded_center]
    projected = _hierarchy_projected_scene(
        role_scene,
        role_hierarchy,
        positions=positions,
        colors=colors,
    )
    occlusion = visual_causal._projected_mediator_occluded_endpoint_centers(
        projected,
        role_hierarchy,
        selected,
        positions=positions,
        colors=colors,
    )
    assert occlusion == (((53, 36),), ((51, 36), (52, 37)))
    selected_centers = tuple(positions[item.object_ref] for item in selected.endpoints)
    selected_mediator_center = (
        sum(center[0] for center in selected_centers) // selected.arity,
        sum(center[1] for center in selected_centers) // selected.arity,
    )
    return projected, {
        "expected_protected_raster_hash": (
            visual_causal._child_isolation_protected_raster_hash(projected)
        ),
        "active_color": role_hierarchy.active_color,
        "sink_center": role_hierarchy.target.rounded_center,
        "target_signature": _child_isolation_target_surface_signature(
            role_scene,
            sink_center=role_hierarchy.target.rounded_center,
        ),
        "selected_mediator_signature": visual_causal._visual_object_state_signature(
            selected.mediator,
            position=selected_mediator_center,
        ),
        "selected_endpoint_signature": visual_causal._endpoint_state_signature(
            selected.endpoints,
            positions=positions,
            colors=colors,
        ),
        "selected_raster_signature": (
            visual_causal._child_isolation_selected_raster_signature(
                role_scene,
                projected,
                selected,
                positions=positions,
            )
        ),
        "occluded_endpoint_centers": occlusion[0],
        "occluded_endpoint_cells": occlusion[1],
        "expected_active_center": (41, 47),
        "frozen_mediator_signature": visual_causal._visual_object_state_signature(frozen.mediator),
        "frozen_endpoint_signature": visual_causal._endpoint_state_signature(frozen.endpoints),
        "frozen_connector_signature": visual_causal._hierarchy_connector_state_signature(
            projected,
            frozen,
        ),
    }


def _mutated_scene(
    scene: visual_causal.VisualScene,
    coordinate: tuple[int, int],
) -> visual_causal.VisualScene:
    rows = [list(row) for row in scene.cells]
    x, y = coordinate
    rows[y][x] = (rows[y][x] + 1) % 16
    return extract_visual_scene(GridFrame.from_rows(rows))


def test_exact_child_occlusion_certificate_matches_the_projected_raster() -> None:
    projected, certificate = _occluded_child_certificate_fixture()

    assert visual_causal._child_isolation_occlusion_certificate_matches(
        projected,
        **certificate,
    )


@pytest.mark.parametrize(
    "coordinate",
    [
        (51, 36),  # exact mediator/endpoint overlap
        (41, 45),  # active endpoint shell
        (12, 46),  # frozen endpoint center marker
        (16, 46),  # frozen connector
        (31, 13),  # parent-target surface
        (48, 42),  # selected connector
        (1, 1),  # unrelated interior surface
        (63, 10),  # non-HUD border surface
    ],
)
def test_child_occlusion_certificate_rejects_any_protected_raster_mutation(
    coordinate: tuple[int, int],
) -> None:
    projected, certificate = _occluded_child_certificate_fixture()

    assert not visual_causal._child_isolation_occlusion_certificate_matches(
        _mutated_scene(projected, coordinate),
        **certificate,
    )


def test_child_occlusion_certificate_allows_only_left_column_hud_evolution() -> None:
    projected, certificate = _occluded_child_certificate_fixture()

    assert visual_causal._child_isolation_occlusion_certificate_matches(
        _mutated_scene(projected, (0, 3)),
        **certificate,
    )


def test_child_occlusion_certificate_binds_the_exact_overlap_cells() -> None:
    projected, certificate = _occluded_child_certificate_fixture()

    certificate["occluded_endpoint_cells"] = ((51, 36),)
    assert not visual_causal._child_isolation_occlusion_certificate_matches(
        projected,
        **certificate,
    )


def test_fresh_two_child_hierarchy_isolates_the_initially_nonactive_child() -> None:
    environment = _TwoLayerAffineEnvironment(win_on_hierarchy=False)
    policy = VisualCausalPolicy(max_coordinate_candidates=8)
    observation = _reach_two_layer_hierarchy(environment, policy)

    groups_before = tuple(tuple(group) for group in environment.groups)
    initially_active_child = environment.active_group
    isolated_child = 1 - initially_active_child
    untouched_child = initially_active_child
    isolated_before = groups_before[isolated_child]
    assert len(groups_before[untouched_child]) == 2
    assert len(isolated_before) == 3

    scene_before = extract_visual_scene(observation.frames[-1])
    hierarchy_before = _unique_affine_hierarchy(scene_before, active_color=0)
    assert hierarchy_before is not None
    sink_center = hierarchy_before.target.rounded_center
    target_surfaces_before = _child_isolation_target_surface_signature(
        scene_before,
        sink_center=sink_center,
    )
    sink_surface_before = {
        cell: scene_before.cells[cell[1]][cell[0]] for cell in hierarchy_before.target.cells
    }
    assert len(sink_surface_before) == 12

    selection = policy.select(observation)
    isolation_signature = policy._pending_plan_signature
    isolation_relation_key = policy._active_child_isolation_relation_key

    assert selection.name is ActionName.ACTION6
    assert selection.coordinate is not None
    assert isolation_signature is not None
    assert isolation_signature.startswith("affine-child-isolation:")
    assert not isolation_signature.startswith("affine-hierarchy:")
    assert isolation_relation_key is not None
    assert policy._pending_purpose is VisualActionPurpose.PROBE
    assert (selection.coordinate.x, selection.coordinate.y) in isolated_before

    terminal_not_finished = False
    progress_actions = 0
    for _ in range(16):
        action = selection
        purpose = policy._pending_purpose
        completes_isolation = policy._pending_completes_child_isolation
        assert policy._pending_plan_signature == isolation_signature

        isolated_before_action = tuple(environment.groups[isolated_child])
        observation = environment.step(action)
        isolated_after_action = tuple(environment.groups[isolated_child])
        returned_scene = extract_visual_scene(observation.frames[-1])
        assert (
            _child_isolation_target_surface_signature(
                returned_scene,
                sink_center=sink_center,
            )
            == target_surfaces_before
        )
        assert {
            cell: returned_scene.cells[cell[1]][cell[0]] for cell in sink_surface_before
        } == sink_surface_before
        policy.accept_consequence(observation)
        assert tuple(environment.groups[untouched_child]) == groups_before[untouched_child]

        if purpose is VisualActionPurpose.PROGRESS:
            assert isolated_after_action != isolated_before_action
            progress_actions += 1
        if completes_isolation:
            terminal_not_finished = observation.state is GameStateName.NOT_FINISHED
            break
        selection = policy.select(observation)
    else:
        raise AssertionError("the child-isolation plan never reached its terminal action")

    isolated_after = tuple(environment.groups[isolated_child])
    assert progress_actions > 0
    assert isolated_after != isolated_before
    assert sum(x for x, _y in isolated_after) == (len(isolated_after) * _HIERARCHY_PARENT_TARGET[0])
    assert sum(y for _x, y in isolated_after) == (len(isolated_after) * _HIERARCHY_PARENT_TARGET[1])
    assert terminal_not_finished
    assert policy.receipts[-1].residual == (
        "the selected child mediator reached the parent target while its sibling "
        "remained distinct, but the official environment remained NOT_FINISHED"
    )

    assert isolation_signature in policy._failed_plan_signatures
    assert isolation_relation_key in policy._failed_child_isolation_relation_keys
    assert policy.snapshot()["child_isolation_relation_rejected_count"] == 1
    assert policy._last_probe_failed is False
    assert policy.snapshot()["pending_plan_actions"] == 6
    recovery = policy.select(observation)
    assert recovery.name is ActionName.ACTION6
    assert policy._pending_plan_signature is not None
    assert policy._pending_plan_signature.startswith("affine-child-recovery:")


def test_child_isolation_accepts_exact_projected_endpoint_deocclusion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parent_target = (53, 28)
    monkeypatch.setattr(
        visual_policy_fixtures,
        "_HIERARCHY_PARENT_TARGET",
        parent_target,
    )
    environment = _TwoLayerAffineEnvironment(
        groups=[
            [(43, 34), (25, 35)],
            [(34, 55), (41, 47), (52, 55)],
        ],
        active_group=0,
        active_index=0,
        win_on_hierarchy=False,
    )
    policy = VisualCausalPolicy(max_coordinate_candidates=8)
    observation = _reach_two_layer_hierarchy(environment, policy)
    entry_frame = observation.frames[-1]
    entry_active = tuple(
        endpoint.rounded_center
        for endpoint in extract_visual_scene(entry_frame).endpoints
        if endpoint.color == 0
    )
    assert len(entry_active) == 1

    deocclusion_observed = False
    terminal_observed = False
    relation_key: str | None = None
    forward_coordinates: list[tuple[int, int]] = []
    for _ in range(16):
        before_scene = extract_visual_scene(observation.frames[-1])
        action = policy.select(observation)
        assert action.coordinate is not None
        forward_coordinates.append((action.coordinate.x, action.coordinate.y))
        relation_key = policy._active_child_isolation_relation_key
        completes_isolation = policy._pending_completes_child_isolation
        expected_endpoint_count = policy._pending_expected_visible_endpoint_count
        expected_mediator_count = policy._pending_expected_visible_mediator_count
        expected_raster_hash = policy._pending_expected_child_protected_raster_hash

        observation = environment.step(action)
        after_scene = extract_visual_scene(observation.frames[-1])
        if len(after_scene.endpoints) > len(before_scene.endpoints):
            deocclusion_observed = True
            assert len(before_scene.endpoints) == 4
            assert len(after_scene.endpoints) == 5
            assert expected_endpoint_count == len(after_scene.endpoints)
            assert expected_mediator_count == len(after_scene.mediators)
            assert (
                visual_causal._child_isolation_protected_raster_hash(after_scene)
                == expected_raster_hash
            )

        policy.accept_consequence(observation)
        assert policy.snapshot()["hierarchy_lineage_lost"] is False
        if completes_isolation:
            terminal_observed = True
            break
    else:
        raise AssertionError("the child-isolation plan never reached its terminal action")

    assert deocclusion_observed
    assert terminal_observed
    assert relation_key is not None
    assert relation_key in policy._failed_child_isolation_relation_keys
    assert policy.receipts[-1].residual == (
        "the selected child mediator reached the parent target while its sibling "
        "remained distinct, but the official environment remained NOT_FINISHED"
    )
    assert policy.snapshot()["pending_plan_actions"] == 6
    recovery_actions = 0
    recovery_coordinates: list[tuple[int, int]] = []
    for _ in range(8):
        recovery = policy.select(observation)
        assert recovery.coordinate is not None
        recovery_coordinates.append((recovery.coordinate.x, recovery.coordinate.y))
        completes_recovery = policy._pending_completes_child_recovery
        observation = environment.step(recovery)
        policy.accept_consequence(observation)
        recovery_actions += 1
        assert policy.snapshot()["hierarchy_lineage_lost"] is False
        if completes_recovery:
            break
    else:
        raise AssertionError("the exact child-isolation rollback never completed")

    assert recovery_actions == 6
    assert recovery_coordinates == [*reversed(forward_coordinates[:-1]), entry_active[0]]
    assert observation.frames[-1].digest == entry_frame.digest
    assert relation_key in policy._failed_child_isolation_relation_keys
    assert policy.receipts[-1].residual == (
        "exact pre-discriminator hierarchy restored after child-only sufficiency was falsified"
    )
    continuation = policy.select(observation)
    assert continuation.name is ActionName.ACTION6
    assert policy._pending_plan_signature is not None
    assert policy._pending_plan_signature.startswith("affine-hierarchy:")


def test_child_isolation_rejects_only_the_failed_layout_after_sibling_displacement() -> None:
    environment = _TwoLayerAffineEnvironment(win_on_hierarchy=False)
    policy = VisualCausalPolicy(max_coordinate_candidates=8)
    observation = _reach_two_layer_hierarchy(environment, policy)
    frozen_child = environment.active_group

    action = policy.select(observation)
    relation_key = policy._active_child_isolation_relation_key
    assert relation_key is not None
    assert policy._pending_plan_signature is not None
    assert policy._pending_plan_signature.startswith("affine-child-isolation:")

    environment.step(action)
    old_x, old_y = environment.groups[frozen_child][0]
    environment.groups[frozen_child][0] = (old_x + 1, old_y)
    displaced = environment.observation(returned_action=action)
    policy.accept_consequence(displaced)

    assert policy.receipts[-1].residual == (
        "planned child-isolation consequence was not structurally readable"
    )
    assert policy.snapshot()["pending_plan_actions"] == 0
    assert policy._pending_plan_signature is None
    assert relation_key not in policy._failed_child_isolation_relation_keys
    assert policy.snapshot()["child_isolation_relation_rejected_count"] == 0
    assert policy._active_child_isolation_relation_key is None
    assert policy.snapshot()["hierarchy_lineage_lost"] is True
    assert policy.snapshot()["hierarchy_lineage_failure_count"] == 1
    lineage_failure = policy.snapshot()["hierarchy_lineage_failure"]
    assert isinstance(lineage_failure, dict)
    assert lineage_failure["level_index"] == displaced.levels_completed
    assert lineage_failure["relation_key"] == relation_key
    assert lineage_failure["plan_signature"] in policy._failed_plan_signatures
    assert str(lineage_failure["phase"]).startswith("returned-consequence:")
    with pytest.raises(PolicyError, match="hierarchy lineage was lost"):
        policy.select(displaced)

    policy._begin_reset_epoch()
    assert policy.snapshot()["hierarchy_lineage_lost"] is False
    assert policy.snapshot()["hierarchy_lineage_failure_count"] == 1


def test_child_isolation_recovery_raster_mismatch_latches_lineage() -> None:
    environment = _TwoLayerAffineEnvironment(win_on_hierarchy=False)
    policy = VisualCausalPolicy(max_coordinate_candidates=8)
    observation = _reach_two_layer_hierarchy(environment, policy)

    for _ in range(16):
        action = policy.select(observation)
        completes_isolation = policy._pending_completes_child_isolation
        observation = environment.step(action)
        policy.accept_consequence(observation)
        if completes_isolation:
            break
    else:
        raise AssertionError("the child-isolation plan never reached its terminal action")

    recovery = policy.select(observation)
    returned = environment.step(recovery)
    rows = [list(row) for row in returned.frames[-1].cells]
    rows[1][1] = 6
    mutated = replace(returned, frames=(GridFrame.from_rows(rows),))
    policy.accept_consequence(mutated)

    assert policy.receipts[-1].residual == (
        "planned child-recovery inverse certificate was not structurally readable"
    )
    assert policy.snapshot()["hierarchy_lineage_lost"] is True
    assert policy.snapshot()["child_isolation_rejected_count"] == 1
    assert policy.snapshot()["pending_plan_actions"] == 0
    with pytest.raises(PolicyError, match="hierarchy lineage was lost"):
        policy.select(mutated)


def test_child_isolation_terminal_recovery_mismatch_latches_lineage() -> None:
    environment = _TwoLayerAffineEnvironment(win_on_hierarchy=False)
    policy = VisualCausalPolicy(max_coordinate_candidates=8)
    observation = _reach_two_layer_hierarchy(environment, policy)

    for _ in range(16):
        action = policy.select(observation)
        completes_isolation = policy._pending_completes_child_isolation
        observation = environment.step(action)
        policy.accept_consequence(observation)
        if completes_isolation:
            break
    else:
        raise AssertionError("the child-isolation plan never reached its terminal action")

    for _ in range(8):
        recovery = policy.select(observation)
        completes_recovery = policy._pending_completes_child_recovery
        returned = environment.step(recovery)
        if completes_recovery:
            rows = [list(row) for row in returned.frames[-1].cells]
            rows[1][1] = 6
            mutated = replace(returned, frames=(GridFrame.from_rows(rows),))
            policy.accept_consequence(mutated)
            observation = mutated
            break
        policy.accept_consequence(returned)
        observation = returned
    else:
        raise AssertionError("the exact child-isolation rollback never reached restoration")

    assert policy.receipts[-1].residual == (
        "planned child-recovery inverse certificate was not structurally readable"
    )
    assert policy.snapshot()["hierarchy_lineage_lost"] is True
    assert policy.snapshot()["child_isolation_rejected_count"] == 1
    assert policy.snapshot()["pending_plan_actions"] == 0
    with pytest.raises(PolicyError, match="hierarchy lineage was lost"):
        policy.select(observation)


def test_queued_child_recovery_precondition_mismatch_fails_closed() -> None:
    environment = _TwoLayerAffineEnvironment(win_on_hierarchy=False)
    policy = VisualCausalPolicy(max_coordinate_candidates=8)
    observation = _reach_two_layer_hierarchy(environment, policy)

    for _ in range(16):
        action = policy.select(observation)
        completes_isolation = policy._pending_completes_child_isolation
        observation = environment.step(action)
        policy.accept_consequence(observation)
        if completes_isolation:
            break
    else:
        raise AssertionError("the child-isolation plan never reached its terminal action")

    recovery = policy.select(observation)
    recovery_signature = policy._pending_plan_signature
    assert recovery_signature is not None
    assert recovery_signature.startswith("affine-child-recovery:")
    returned = environment.step(recovery)
    policy.accept_consequence(returned)
    assert policy.snapshot()["pending_plan_actions"] == 5

    rows = [list(row) for row in returned.frames[-1].cells]
    rows[1][1] = 6
    mutated = replace(returned, frames=(GridFrame.from_rows(rows),))
    with pytest.raises(PolicyError, match="queued hierarchy precondition"):
        policy.select(mutated)

    assert recovery_signature in policy._failed_plan_signatures
    assert policy.snapshot()["hierarchy_lineage_lost"] is True
    assert policy.snapshot()["child_isolation_rejected_count"] == 1
    assert policy.snapshot()["pending_plan_actions"] == 0


def test_game_over_reset_during_child_recovery_preserves_relation_rejection() -> None:
    environment = _TwoLayerAffineEnvironment(win_on_hierarchy=False)
    policy = VisualCausalPolicy(max_coordinate_candidates=8)
    entry = _reach_two_layer_hierarchy(environment, policy)
    observation = entry

    for _ in range(16):
        action = policy.select(observation)
        completes_isolation = policy._pending_completes_child_isolation
        observation = environment.step(action)
        policy.accept_consequence(observation)
        if completes_isolation:
            break
    else:
        raise AssertionError("the child-isolation plan never reached its terminal action")

    relation_key = next(iter(policy._failed_child_isolation_relation_keys))
    recovery = policy.select(observation)
    game_over = replace(environment.step(recovery), state=GameStateName.GAME_OVER)
    policy.accept_consequence(game_over)

    assert policy.snapshot()["child_isolation_active"] is False
    assert policy.snapshot()["pending_plan_actions"] == 0
    assert relation_key in policy._failed_child_isolation_relation_keys
    reset = policy.select(game_over)
    assert reset.name is ActionName.RESET
    recovered = replace(entry, returned_action=reset)
    policy.accept_consequence(recovered)

    assert relation_key in policy._failed_child_isolation_relation_keys
    continuation = policy.select(recovered)
    assert continuation.name is ActionName.ACTION6
    assert policy._pending_plan_signature is not None
    assert policy._pending_plan_signature.startswith("affine-hierarchy:")


def test_readable_child_consequence_with_one_raster_residual_latches_lineage() -> None:
    environment = _TwoLayerAffineEnvironment(win_on_hierarchy=False)
    policy = VisualCausalPolicy(max_coordinate_candidates=8)
    observation = _reach_two_layer_hierarchy(environment, policy)

    action = policy.select(observation)
    plan_signature = policy._pending_plan_signature
    assert plan_signature is not None
    returned = environment.step(action)
    rows = [list(row) for row in returned.frames[-1].cells]
    rows[47][46] = 6
    mutated = replace(returned, frames=(GridFrame.from_rows(rows),))
    assert (
        _unique_affine_hierarchy(
            extract_visual_scene(mutated.frames[-1]),
            active_color=0,
        )
        is not None
    )

    policy.accept_consequence(mutated)

    assert policy.receipts[-1].residual == (
        "planned child-isolation consequence was not structurally readable"
    )
    assert plan_signature in policy._failed_plan_signatures
    assert policy.snapshot()["hierarchy_lineage_lost"] is True
    assert policy.snapshot()["pending_plan_actions"] == 0
    with pytest.raises(PolicyError, match="hierarchy lineage was lost"):
        policy.select(mutated)


def test_child_raster_residual_latches_even_when_hierarchy_search_exhausts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    environment = _TwoLayerAffineEnvironment(win_on_hierarchy=False)
    policy = VisualCausalPolicy(max_coordinate_candidates=8)
    observation = _reach_two_layer_hierarchy(environment, policy)

    action = policy.select(observation)
    returned = environment.step(action)
    rows = [list(row) for row in returned.frames[-1].cells]
    rows[1][1] = 6
    mutated = replace(returned, frames=(GridFrame.from_rows(rows),))

    def exhaust_hierarchy_search(*_args: object, **_kwargs: object) -> None:
        raise visual_causal._HierarchySearchExhausted("test consequence exhaustion")

    monkeypatch.setattr(
        visual_causal,
        "_unique_affine_hierarchy",
        exhaust_hierarchy_search,
    )
    policy.accept_consequence(mutated)

    assert policy.receipts[-1].residual == (
        "returned hierarchy recognition failed closed: test consequence exhaustion"
    )
    assert policy.snapshot()["hierarchy_lineage_lost"] is True
    assert policy.snapshot()["hierarchy_lineage_failure_count"] == 1
    with pytest.raises(PolicyError, match="hierarchy lineage was lost"):
        policy.select(mutated)


def test_queued_child_precondition_mismatch_fails_closed_before_fallback() -> None:
    environment = _TwoLayerAffineEnvironment(win_on_hierarchy=False)
    policy = VisualCausalPolicy(max_coordinate_candidates=8)
    observation = _reach_two_layer_hierarchy(environment, policy)

    action = policy.select(observation)
    plan_signature = policy._pending_plan_signature
    assert plan_signature is not None
    returned = environment.step(action)
    policy.accept_consequence(returned)
    assert policy.snapshot()["pending_plan_actions"] > 0

    rows = [list(row) for row in returned.frames[-1].cells]
    rows[1][1] = 6
    changed_before_selection = replace(returned, frames=(GridFrame.from_rows(rows),))
    with pytest.raises(PolicyError, match="queued hierarchy precondition"):
        policy.select(changed_before_selection)

    assert plan_signature in policy._failed_plan_signatures
    assert policy.snapshot()["hierarchy_lineage_lost"] is True
    assert policy.snapshot()["hierarchy_lineage_failure_count"] == 1
    assert policy.snapshot()["pending_plan_actions"] == 0


@pytest.mark.parametrize(
    "corruption",
    ["outer-role-color", "center-marker-color", "mediator-center-color"],
)
def test_child_isolation_rejects_endpoint_signature_change_without_falsifying_relation(
    corruption: str,
) -> None:
    environment = _TwoLayerAffineEnvironment(win_on_hierarchy=False)
    policy = VisualCausalPolicy(max_coordinate_candidates=8)
    observation = _reach_two_layer_hierarchy(environment, policy)
    frozen_child = environment.active_group

    action = policy.select(observation)
    relation_key = policy._active_child_isolation_relation_key
    assert relation_key is not None
    returned = environment.step(action)
    frozen_endpoint = environment.groups[frozen_child][0]
    rows = [list(row) for row in returned.frames[-1].cells]
    if corruption == "outer-role-color":
        for dx, dy in _ENDPOINT_SHAPE:
            x = frozen_endpoint[0] + dx
            y = frozen_endpoint[1] + dy
            if rows[y][x] == 3:
                rows[y][x] = 6
    elif corruption == "center-marker-color":
        rows[frozen_endpoint[1]][frozen_endpoint[0]] = 6
    else:
        frozen_group = environment.groups[frozen_child]
        frozen_mediator = (
            sum(x for x, _y in frozen_group) // len(frozen_group),
            sum(y for _x, y in frozen_group) // len(frozen_group),
        )
        rows[frozen_mediator[1]][frozen_mediator[0]] = 6
    recolored = replace(returned, frames=(GridFrame.from_rows(rows),))

    policy.accept_consequence(recolored)

    assert policy.receipts[-1].residual == (
        "planned child-isolation consequence was not structurally readable"
    )
    assert policy.snapshot()["pending_plan_actions"] == 0
    assert relation_key not in policy._failed_child_isolation_relation_keys
    assert policy.snapshot()["child_isolation_relation_rejected_count"] == 0


def test_child_isolation_unknown_terminal_state_does_not_claim_not_finished() -> None:
    environment = _TwoLayerAffineEnvironment(win_on_hierarchy=False)
    policy = VisualCausalPolicy(max_coordinate_candidates=8)
    observation = _reach_two_layer_hierarchy(environment, policy)
    selection = policy.select(observation)
    relation_key = policy._active_child_isolation_relation_key
    assert relation_key is not None

    for _ in range(16):
        action = selection
        completes_isolation = policy._pending_completes_child_isolation
        observation = environment.step(action)
        if completes_isolation:
            unknown = replace(observation, state=GameStateName.UNKNOWN)
            policy.accept_consequence(unknown)
            break
        policy.accept_consequence(observation)
        selection = policy.select(observation)
    else:
        raise AssertionError("the child-isolation plan never reached its terminal action")

    assert policy.receipts[-1].after_state is GameStateName.UNKNOWN
    assert policy.receipts[-1].residual != (
        "the selected child mediator reached the parent target while its sibling "
        "remained distinct, but the official environment remained NOT_FINISHED"
    )
    assert relation_key not in policy._failed_child_isolation_relation_keys
    assert policy.snapshot()["child_isolation_active"] is False
    assert policy.snapshot()["pending_plan_actions"] == 0


def test_child_isolation_terminal_raster_residual_does_not_falsify_the_relation() -> None:
    environment = _TwoLayerAffineEnvironment(win_on_hierarchy=False)
    policy = VisualCausalPolicy(max_coordinate_candidates=8)
    observation = _reach_two_layer_hierarchy(environment, policy)
    selection = policy.select(observation)
    relation_key = policy._active_child_isolation_relation_key
    assert relation_key is not None

    for _ in range(16):
        action = selection
        completes_isolation = policy._pending_completes_child_isolation
        observation = environment.step(action)
        if completes_isolation:
            rows = [list(row) for row in observation.frames[-1].cells]
            rows[1][1] = 6
            mutated = replace(observation, frames=(GridFrame.from_rows(rows),))
            assert (
                _unique_affine_hierarchy(
                    extract_visual_scene(mutated.frames[-1]),
                    active_color=0,
                )
                is not None
            )
            policy.accept_consequence(mutated)
            observation = mutated
            break
        policy.accept_consequence(observation)
        selection = policy.select(observation)
    else:
        raise AssertionError("the child-isolation plan never reached its terminal action")

    assert policy.receipts[-1].residual == (
        "planned child-isolation consequence was not structurally readable"
    )
    assert relation_key not in policy._failed_child_isolation_relation_keys
    assert policy.snapshot()["hierarchy_lineage_lost"] is True
    with pytest.raises(PolicyError, match="hierarchy lineage was lost"):
        policy.select(observation)


def test_joint_hierarchy_unknown_terminal_state_does_not_claim_not_finished() -> None:
    environment = _TwoLayerAffineEnvironment(win_on_hierarchy=False)
    policy = VisualCausalPolicy(max_coordinate_candidates=8)
    observation = _reach_two_layer_hierarchy(environment, policy)
    hierarchy = _unique_affine_hierarchy(
        extract_visual_scene(observation.frames[-1]), active_color=0
    )
    assert hierarchy is not None
    _install_joint_hierarchy_for_test(policy, observation)

    for _ in range(20):
        action = policy.select(observation)
        completes_hierarchy = policy._pending_completes_hierarchy
        observation = environment.step(action)
        if completes_hierarchy:
            unknown = replace(observation, state=GameStateName.UNKNOWN)
            policy.accept_consequence(unknown)
            break
        policy.accept_consequence(observation)
    else:
        raise AssertionError("the joint hierarchy plan never reached its terminal action")

    assert policy.receipts[-1].after_state is GameStateName.UNKNOWN
    assert policy.receipts[-1].residual != (
        "distinct child mediators reached the predicted parent centroid but "
        "the official environment remained NOT_FINISHED"
    )
    assert not policy._failed_hierarchy_relation_keys
    assert policy.snapshot()["hierarchy_active"] is False
    assert policy.snapshot()["pending_plan_actions"] == 0


def test_child_isolation_level_progress_is_not_receipted_as_structural_failure() -> None:
    environment = _TwoLayerAffineEnvironment(win_on_hierarchy=False)
    policy = VisualCausalPolicy(max_coordinate_candidates=8)
    observation = _reach_two_layer_hierarchy(environment, policy)
    selection = policy.select(observation)

    for _ in range(16):
        action = selection
        completes_isolation = policy._pending_completes_child_isolation
        observation = environment.step(action)
        if completes_isolation:
            progressed = replace(
                observation,
                frames=(GridFrame.from_rows([[5 for _x in range(64)] for _y in range(64)]),),
                levels_completed=2,
            )
            policy.accept_consequence(progressed)
            break
        policy.accept_consequence(observation)
        selection = policy.select(observation)
    else:
        raise AssertionError("the child-isolation plan never reached its terminal action")

    assert policy.receipts[-1].levels_after == 2
    assert policy.receipts[-1].residual != (
        "planned child-isolation consequence was not structurally readable"
    )
    assert policy.snapshot()["active_level_index"] == 2


def test_child_isolation_rejects_frozen_connector_mutation() -> None:
    environment = _TwoLayerAffineEnvironment(
        win_on_hierarchy=False,
        connector_color=9,
    )
    policy = VisualCausalPolicy(max_coordinate_candidates=8)
    observation = _reach_two_layer_hierarchy(environment, policy)
    initial_scene = extract_visual_scene(observation.frames[-1])
    initial_hierarchy = _unique_affine_hierarchy(initial_scene, active_color=0)
    assert initial_hierarchy is not None
    frozen_group = initial_hierarchy.children[0]
    connector = _hierarchy_connector_evidence(initial_scene, frozen_group)
    assert connector is not None
    _connector_color, connector_cells = connector

    action = policy.select(observation)
    relation_key = policy._active_child_isolation_relation_key
    assert relation_key is not None
    returned = environment.step(action)
    rows = [list(row) for row in returned.frames[-1].cells]
    removed_x, removed_y = sorted(connector_cells)[len(connector_cells) // 2]
    rows[removed_y][removed_x] = 5
    mutated = replace(returned, frames=(GridFrame.from_rows(rows),))

    policy.accept_consequence(mutated)

    assert policy.receipts[-1].residual == (
        "planned child-isolation consequence was not structurally readable"
    )
    assert policy.snapshot()["pending_plan_actions"] == 0
    assert relation_key not in policy._failed_child_isolation_relation_keys


def test_hierarchy_relation_key_tracks_stable_center_markers_not_active_role_color() -> None:
    base_frame = _two_layer_affine_frame()
    base_scene = extract_visual_scene(base_frame)
    base_hierarchy = _unique_affine_hierarchy(base_scene, active_color=0)
    assert base_hierarchy is not None
    base_key = _hierarchy_relation_key(base_hierarchy, level_index=1)

    role_swapped_scene = extract_visual_scene(
        _two_layer_affine_frame(active_group=1, active_index=0)
    )
    role_swapped_hierarchy = _unique_affine_hierarchy(role_swapped_scene, active_color=0)
    assert role_swapped_hierarchy is not None
    assert _hierarchy_relation_key(role_swapped_hierarchy, level_index=1) == base_key

    rows = [list(row) for row in base_frame.cells]
    for child in base_hierarchy.children:
        for endpoint in child.endpoints:
            center_x, center_y = endpoint.rounded_center
            rows[center_y][center_x] = 6
    remarked_scene = extract_visual_scene(GridFrame.from_rows(rows))
    remarked_hierarchy = _unique_affine_hierarchy(remarked_scene, active_color=0)
    assert remarked_hierarchy is not None
    assert _hierarchy_relation_key(remarked_hierarchy, level_index=1) != base_key


def test_child_isolation_not_played_return_clears_plan_and_reset_recovers() -> None:
    environment = _TwoLayerAffineEnvironment(win_on_hierarchy=False)
    policy = VisualCausalPolicy(max_coordinate_candidates=8)
    observation = _reach_two_layer_hierarchy(environment, policy)

    action = policy.select(observation)
    relation_key = policy._active_child_isolation_relation_key
    assert relation_key is not None
    not_played = replace(
        observation,
        state=GameStateName.NOT_PLAYED,
        returned_action=action,
    )
    policy.accept_consequence(not_played)

    assert policy.snapshot()["child_isolation_active"] is False
    assert policy.snapshot()["pending_plan_actions"] == 0
    assert relation_key not in policy._failed_child_isolation_relation_keys
    reset = policy.select(not_played)
    assert reset.name is ActionName.RESET
    recovered = replace(
        observation,
        returned_action=reset,
    )
    policy.accept_consequence(recovered)

    retry = policy.select(recovered)
    assert retry.name is ActionName.ACTION6
    assert policy._pending_plan_signature is not None
    assert policy._pending_plan_signature.startswith("affine-child-isolation:")
