from __future__ import annotations

from dataclasses import replace

import pytest
from test_visual_causal_policy import (
    _ENDPOINT_SHAPE,
    _HIERARCHY_PARENT_TARGET,
    _install_joint_hierarchy_for_test,
    _reach_two_layer_hierarchy,
    _two_layer_affine_frame,
    _TwoLayerAffineEnvironment,
)

from arc3.adapters import GridFrame
from arc3.errors import PolicyError
from arc3.mechanics.visual_causal import (
    VisualActionPurpose,
    VisualCausalPolicy,
    _child_isolation_target_surface_signature,
    _hierarchy_connector_evidence,
    _hierarchy_relation_key,
    _unique_affine_hierarchy,
    extract_visual_scene,
)
from arc3.types import ActionName, GameStateName


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
    assert policy._last_probe_failed is True
    with pytest.raises(PolicyError, match=r"already falsified.*NOT_FINISHED"):
        policy.select(observation)

    policy._begin_reset_epoch()
    assert isolation_relation_key in policy._failed_child_isolation_relation_keys
    with pytest.raises(PolicyError, match=r"already falsified.*NOT_FINISHED"):
        policy.select(observation)


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
