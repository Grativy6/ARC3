"""Focused contract tests for the frozen Stage 05 measurement harness."""

from __future__ import annotations

import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

from scripts.measure_action_equivariance import (
    CALIBRATION_COORDINATE,
    ROOT,
    ToroidalActionSession,
    _causal_control_suite,
    _checkpoint_suite,
    _holdout_integrity,
    _post_prefix_trajectories,
    _procedural_pair,
    _registry_bounds_summary,
    _resource_summary,
    action_suite_schedule,
)

from arc3.types import ActionName, ActionRequest, Coordinate, GameStateName


def test_schedule_has_exact_frozen_cardinality_and_order() -> None:
    schedule = action_suite_schedule()
    assert len(schedule) == 128
    assert Counter(item.family for item in schedule) == {
        "full_four_handle": 96,
        "partial_two_handle": 8,
        "partial_three_handle": 8,
        "mixed_coordinate": 16,
    }
    assert [(item.seed, item.permutation_id) for item in schedule[:6]] == [
        (0, "swap12"),
        (0, "swap34"),
        (0, "swap12_swap34"),
        (0, "cycle1234"),
        (0, "cycle1432"),
        (0, "reverse"),
    ]
    assert [item.seed for item in schedule[96:]] == list(range(16, 48))
    assert all(item.pi[ActionName.ACTION6] is ActionName.ACTION6 for item in schedule[112:])


def test_toroidal_cardinal_arena_commutes_over_complete_prefix() -> None:
    specification = action_suite_schedule()[0]
    base = ToroidalActionSession(specification, transformed=False)
    paired = ToroidalActionSession(specification, transformed=True)
    cardinal_effects: set[tuple[int, int]] = set()
    for handle in sorted(specification.handles, key=lambda item: item.value):
        request = ActionRequest(handle)
        effect = base.canonical_effect(request)
        translation = effect["translation"]
        assert isinstance(translation, list)
        cardinal_effects.add((int(translation[0]), int(translation[1])))
        base.step(request)
        paired.step(request)
    assert cardinal_effects == {
        (-1, 0),
        (0, -1),
        (0, 1),
        (1, 0),
    }
    assert base.observation.state is GameStateName.NOT_FINISHED
    assert paired.observation.state is GameStateName.NOT_FINISHED
    assert base.canonical_state() == paired.canonical_state()
    base.close()
    paired.close()


def test_post_prefix_state_slice_skips_initial_and_boundary_state() -> None:
    episode = {
        "canonical_effect_trajectory": ["effect-1", "effect-2", "effect-3"],
        "canonical_state_trajectory": ["initial", "state-1", "state-2", "state-3"],
    }
    effects, states = _post_prefix_trajectories(episode, 2)
    assert effects == ["effect-3"]
    assert states == ["state-3"]


def test_mixed_pair_executes_action6_after_calibration_with_exact_parity(
    tmp_path: Path,
) -> None:
    specification = action_suite_schedule()[112]
    result = _procedural_pair(specification, root=tmp_path, git_commit="test")
    k = specification.calibration_length
    base = result["base"]
    paired = result["permuted"]
    assert isinstance(base, dict)
    assert isinstance(paired, dict)
    base_actions = base["action_request_sequence"]
    paired_actions = paired["action_request_sequence"]
    assert isinstance(base_actions, list)
    assert isinstance(paired_actions, list)
    assert base_actions[k - 1] == {
        "name": "ACTION6",
        "coordinate": {"x": 3, "y": 3},
    }
    base_post = [item for item in base_actions[k:] if item["name"] == "ACTION6"]
    paired_post = [item for item in paired_actions[k:] if item["name"] == "ACTION6"]
    assert base_post
    assert base_post == paired_post
    assert result["predicates"]["coordinate_exact_request_and_consequence"] is True
    assert result["pair_passed"] is True


def test_all_causal_controls_pass_and_roundtrip() -> None:
    suite = _causal_control_suite()
    assert suite["case_count"] == 64
    assert suite["passed_cases"] == 64
    assert all(case["replay"]["projection_roundtrip_exact"] for case in suite["cases"])


def test_checkpoint_resume_one_frozen_seed_is_exact(tmp_path: Path) -> None:
    suite = _checkpoint_suite(tmp_path, "test", seeds=(0,))
    assert suite["case_count"] == 1
    assert suite["passed_cases"] == 1
    case = suite["cases"][0]
    assert case["predicates"]["boundary_registry_projection"] is True
    assert case["predicates"]["next_canonical_choice"] is True
    assert case["predicates"]["no_resubmission"] is True


def test_registry_bounds_are_measured_from_projection_contents() -> None:
    within = {
        "registry": {
            "schema": "arc3.action-effect-registry.v1",
            "max_raw_handles": 7,
            "max_candidates_per_handle": 32,
            "handles": ["ACTION1"],
            "candidates": [{"raw_handle": "ACTION1"}] * 32,
        }
    }
    measured = _registry_bounds_summary(within)
    assert measured["passed"] is True
    assert measured["maximum_observed_raw_handles"] == 1
    assert measured["maximum_observed_candidates_per_handle"] == 32

    exceeded = {
        "registry": {
            **within["registry"],
            "candidates": [{"raw_handle": "ACTION1"}] * 33,
        }
    }
    failed = _registry_bounds_summary(exceeded)
    assert failed["passed"] is False
    assert failed["maximum_observed_candidates_per_handle"] == 33
    assert failed["violations"]


def test_holdout_identity_aggregation_descends_into_both_ledgers(
    tmp_path: Path,
) -> None:
    manifest = tmp_path / "partition.json"
    manifest.write_text(
        json.dumps(
            {
                "games": [
                    {"game_id": f"holdout-{index:08x}", "partition": "public-holdout"}
                    for index in range(10)
                ]
            }
        ),
        encoding="utf-8",
    )
    build000 = tmp_path / "build000.jsonl"
    stage03 = tmp_path / "stage03.jsonl"
    build000.write_text(
        json.dumps({"payload": {"game_id": "holdout-00000000"}}) + "\n",
        encoding="utf-8",
    )
    stage03.write_text(
        json.dumps({"payload": {"game_id": "holdout-00000001"}}) + "\n",
        encoding="utf-8",
    )
    report = _holdout_integrity(
        manifest_path=manifest,
        exposure_ledgers=(("build-000", build000), ("stage-03", stage03)),
        acquisition_roots=(tmp_path / "environments-a", tmp_path / "environments-b"),
    )
    assert report["public_holdout_gameplay_events"] == 2
    assert [item["holdout_event_count"] for item in report["exposure_ledgers"]] == [1, 1]
    assert report["status"] == "INTEGRITY_FAILURE"


def test_resource_summary_always_exposes_peak_and_episode_limit_keys() -> None:
    summary = _resource_summary(
        {"wall_ns": 10, "rss": {"process_peak_rss_bytes": 20}},
        wall_ns=30,
        cpu_ns=15,
    )
    assert summary["peak_rss_bytes"] == 20
    assert summary["maximum_episode_wall_within_limit"] is True


def test_direct_script_help_imports_without_package_execution() -> None:
    completed = subprocess.run(
        [sys.executable, str(ROOT / "scripts/measure_action_equivariance.py"), "--help"],
        cwd=ROOT,
        capture_output=True,
        check=False,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr
    assert "--work-root" in completed.stdout
    assert CALIBRATION_COORDINATE == Coordinate(3, 3)
