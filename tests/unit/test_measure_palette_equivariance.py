"""Focused contracts for the frozen Stage 04 synthetic measurement harness."""

from __future__ import annotations

from pathlib import Path

from scripts.measure_palette_equivariance import (
    CAUSAL_CONTROL_CASES,
    CHECKPOINT_SEEDS,
    ENVIRONMENT_SEEDS,
    PERMUTATIONS_PER_SEED,
    CheckpointWalkSession,
    PaletteMappedSession,
    _causal_control_suite,
    _checkpoint_resumed_episode,
    _pair_parity,
    _run_episode,
    palette_permutation,
    palette_suite_schedule,
)

from arc3.adapters.synthetic import SYNTHETIC_GAME_ID, SyntheticAdapter
from arc3.types import ActionName, ActionRequest, GameStateName


def test_frozen_palette_schedule_is_exact_deterministic_and_full_domain() -> None:
    schedule = palette_suite_schedule()
    assert len(schedule) == len(ENVIRONMENT_SEEDS) * PERMUTATIONS_PER_SEED == 256
    assert schedule == palette_suite_schedule()
    assert {(seed, index) for seed, index, _mapping in schedule} == {
        (seed, index) for seed in ENVIRONMENT_SEEDS for index in range(PERMUTATIONS_PER_SEED)
    }
    for seed, index, mapping in schedule:
        assert mapping == palette_permutation(seed, index)
        assert tuple(sorted(mapping)) == tuple(range(16))
        assert mapping != tuple(range(16))


def test_mapped_session_changes_only_raw_observations_and_preserves_actions() -> None:
    source = SyntheticAdapter(seed=7, size=8, max_steps=16).open(
        SYNTHETIC_GAME_ID,
        seed=7,
    )
    source_initial = source.observation
    permutation = palette_permutation(7, 0)
    mapped = PaletteMappedSession(source, permutation)
    assert mapped.observation.frames[-1].digest != source_initial.frames[-1].digest
    assert source.observation.frames[-1].digest == source_initial.frames[-1].digest
    assert mapped.observation.state == source_initial.state
    assert mapped.observation.available_actions == source_initial.available_actions

    action = ActionRequest(ActionName.ACTION4)
    returned = mapped.step(action)
    assert returned.returned_action == action
    assert source.observation.returned_action == action
    assert returned.frames[-1].digest != source.observation.frames[-1].digest


def test_all_frozen_color_causal_controls_preserve_joint_and_one_sided_distinction() -> None:
    suite = _causal_control_suite()
    assert suite["case_count"] == CAUSAL_CONTROL_CASES == 64
    assert suite["joint_equivalent_cases"] == CAUSAL_CONTROL_CASES
    assert suite["one_sided_distinguishable_cases"] == CAUSAL_CONTROL_CASES
    for case in suite["cases"]:  # type: ignore[union-attr]
        assert case["one_sided_recolor_count"] > 0
        assert case["base_before_hash"] != case["one_sided_after_hash"]


def test_checkpoint_walk_has_a_nonterminal_first_boundary_for_every_frozen_seed() -> None:
    assert len(CHECKPOINT_SEEDS) == 16
    for seed in CHECKPOINT_SEEDS:
        session = CheckpointWalkSession(seed=seed)
        returned = session.step(ActionRequest(ActionName.ACTION1))
        assert returned.state is GameStateName.NOT_FINISHED


def test_one_full_controller_pair_has_exact_palette_equivariance_and_trace_replay(
    tmp_path: Path,
) -> None:
    seed = 11
    base = _run_episode(
        SyntheticAdapter(seed=seed, size=8, max_steps=16).open(
            SYNTHETIC_GAME_ID,
            seed=seed,
        ),
        root=tmp_path / "base",
        run_id="test-stage04-base",
        seed=seed,
        git_commit="test-stage04",
        automatic_checkpoints=False,
    )
    transformed = _run_episode(
        PaletteMappedSession(
            SyntheticAdapter(seed=seed, size=8, max_steps=16).open(
                SYNTHETIC_GAME_ID,
                seed=seed,
            ),
            palette_permutation(seed, 0),
        ),
        root=tmp_path / "transformed",
        run_id="test-stage04-transformed",
        seed=seed,
        git_commit="test-stage04",
        automatic_checkpoints=False,
    )
    parity = _pair_parity(base, transformed)
    assert all(parity.values())
    assert base["completed"] is True
    assert transformed["completed"] is True
    assert base["initial_raw_frame_hash"] != transformed["initial_raw_frame_hash"]


def test_checkpoint_restore_preserves_palette_roles_and_does_not_resubmit(
    tmp_path: Path,
) -> None:
    result = _checkpoint_resumed_episode(
        seed=0,
        permutation=palette_permutation(0, 0),
        root=tmp_path / "resume",
        git_commit="test-stage04",
    )
    assert result["checkpoint_palette_registry_serialized"] is True
    assert result["projection_stable_across_restore"] is True
    assert result["no_resubmission"] is True
    assert result["completed"] is True
    assert result["controller_fault_count"] == 0
