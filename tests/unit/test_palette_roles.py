from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from arc3.adapters import GridFrame
from arc3.adapters.synthetic import SYNTHETIC_GAME_ID, SyntheticAdapter
from arc3.config import ARC3Config, BudgetConfig
from arc3.errors import ARC3ValidationError, PolicyError
from arc3.perception import PaletteRoleRegistry
from arc3.policy import ARC3Controller, ControllerPreset, RunContext, preset_features
from arc3.types import EnvironmentMode


def _permuted(frame: GridFrame, mapping: dict[int, int]) -> GridFrame:
    return GridFrame.from_rows(tuple(tuple(mapping[value] for value in row) for row in frame.cells))


def _context(tmp_path: Path, label: str) -> RunContext:
    return RunContext(
        run_id=f"palette-{label}",
        episode_id=f"palette-{label}",
        game_id=SYNTHETIC_GAME_ID,
        trace_root=tmp_path / label / "trace",
        checkpoint_root=tmp_path / label / "checkpoint",
        config=ARC3Config(
            mode=EnvironmentMode.SYNTHETIC,
            seed=11,
            profile="palette-role-test",
            budgets=BudgetConfig(max_actions=16, max_resets=2),
        ),
        git_commit="palette-role-test",
    )


def test_bijective_palette_relabeling_preserves_canonical_projection() -> None:
    frame = GridFrame.from_rows(
        (
            (0, 0, 0, 1),
            (0, 2, 0, 0),
            (0, 0, 3, 3),
        )
    )
    transformed = _permuted(frame, {0: 9, 1: 4, 2: 15, 3: 6})
    original_registry = PaletteRoleRegistry(level_index=3)
    transformed_registry = PaletteRoleRegistry(level_index=3)

    original_registry.observe(frame, background_colors=(0,))
    transformed_registry.observe(transformed, background_colors=(9,))

    assert original_registry.canonical_projection() == transformed_registry.canonical_projection()
    assert original_registry.canonical_role(0) == transformed_registry.canonical_role(9)
    assert original_registry.canonical_role(1) == transformed_registry.canonical_role(4)
    assert original_registry.canonical_role(2) == transformed_registry.canonical_role(15)
    assert original_registry.canonical_role(3) == transformed_registry.canonical_role(6)
    assert original_registry.anonymous_identity(0) == transformed_registry.anonymous_identity(9)
    assert original_registry.anonymous_identity(1) == transformed_registry.anonymous_identity(4)
    assert original_registry.anonymous_identity(2) == transformed_registry.anonymous_identity(15)
    assert original_registry.anonymous_identity(3) == transformed_registry.anonymous_identity(6)


def test_indistinguishable_colors_share_an_explicit_ambiguous_role() -> None:
    frame = GridFrame.from_rows(
        (
            (0, 0, 0, 0, 0),
            (0, 1, 0, 2, 0),
            (0, 0, 0, 0, 0),
        )
    )
    registry = PaletteRoleRegistry()
    registry.observe(frame, background_colors=(0,))

    left = registry.role_for(1)
    right = registry.role_for(2)
    assert left.role_id == right.role_id
    assert left.identity_token != right.identity_token
    assert left.ambiguous is True
    assert right.ambiguous is True


def test_assignment_is_stable_across_motion_and_round_trips() -> None:
    before = GridFrame.from_rows(((0, 0, 0), (0, 1, 2), (0, 0, 0)))
    after = GridFrame.from_rows(((0, 0, 0), (1, 0, 2), (0, 0, 0)))
    registry = PaletteRoleRegistry(level_index=2)
    registry.observe(before, background_colors=(0,))
    original = registry.role_for(1)

    registry.observe(after, background_colors=(0,))
    restored = PaletteRoleRegistry.from_dict(registry.to_dict())

    assert registry.role_for(1) == original
    assert restored.to_dict() == registry.to_dict()
    assert restored.canonical_projection() == registry.canonical_projection()


def test_anonymous_identity_is_stable_when_ambiguous_colors_cross() -> None:
    before = GridFrame.from_rows(((0, 0, 0), (1, 0, 2), (0, 0, 0)))
    after = GridFrame.from_rows(((0, 0, 0), (2, 0, 1), (0, 0, 0)))
    registry = PaletteRoleRegistry()
    registry.observe(before, background_colors=(0,))
    left_identity = registry.anonymous_identity(1)
    right_identity = registry.anonymous_identity(2)

    registry.observe(after, background_colors=(0,))

    assert registry.role_for(1).role_id == registry.role_for(2).role_id
    assert registry.anonymous_identity(1) == left_identity
    assert registry.anonymous_identity(2) == right_identity
    assert left_identity != right_identity


def test_registry_rejects_more_than_sixteen_entries_or_tampered_roles() -> None:
    with pytest.raises(ARC3ValidationError, match=r"within 1\.\.16"):
        PaletteRoleRegistry(max_entries=17)

    registry = PaletteRoleRegistry()
    registry.observe(GridFrame.from_rows(((0, 1),)), background_colors=(0,))
    payload = registry.to_dict()
    assignments = payload["assignments"]
    assert isinstance(assignments, list)
    assert isinstance(assignments[0], dict)
    assignments[0]["role_id"] = "palette-role:structural:0000000000000000"
    with pytest.raises(ARC3ValidationError, match="does not match"):
        PaletteRoleRegistry.from_dict(payload)

    identity_payload = registry.to_dict()
    identity_assignments = identity_payload["assignments"]
    assert isinstance(identity_assignments, list)
    assert isinstance(identity_assignments[0], dict)
    identity_assignments[0]["identity_token"] = "palette-identity:0000000000000000:0"
    with pytest.raises(ARC3ValidationError, match="anonymous identity"):
        PaletteRoleRegistry.from_dict(identity_payload)


def test_controller_action_and_derived_roles_are_palette_equivariant(tmp_path: Path) -> None:
    session = SyntheticAdapter(seed=11, size=8, max_steps=32).open(SYNTHETIC_GAME_ID)
    observation = session.observation
    palette_observation = replace(
        observation,
        frames=tuple(_permuted(frame, {0: 5, 1: 14, 2: 3}) for frame in observation.frames),
    )
    features = replace(preset_features(ControllerPreset.FULL), use_memory=False)
    original = ARC3Controller(ControllerPreset.FULL, features=features)
    transformed = ARC3Controller(ControllerPreset.FULL, features=features)
    original.reset(_context(tmp_path, "base"))
    transformed.reset(_context(tmp_path, "permuted"))
    original.observe(observation)
    transformed.observe(palette_observation)

    assert original.palette_role_projection == transformed.palette_role_projection
    assert original.choose_action().action == transformed.choose_action().action

    original.close()
    transformed.close()
    session.close()


def test_checkpoint_restores_registry_before_rebuilding_symbolic_state(tmp_path: Path) -> None:
    session = SyntheticAdapter(seed=11, size=8, max_steps=32).open(SYNTHETIC_GAME_ID)
    context = _context(tmp_path, "restart")
    controller = ARC3Controller(ControllerPreset.FULL)
    controller.reset(context)
    controller.observe(session.observation)
    expected = controller.palette_role_projection
    decision = controller.choose_action()
    checkpoint = controller.checkpoint()
    controller.close()

    restored = ARC3Controller.restore(
        context,
        preset=ControllerPreset.FULL,
        checkpoint_path=checkpoint.path,
    )
    assert restored.palette_role_projection == expected
    with pytest.raises(PolicyError, match="pending action"):
        restored.choose_action()
    returned = session.step(decision.action)
    restored.apply_consequence(returned)
    assert restored.palette_role_projection == expected

    restored.close()
    session.close()
