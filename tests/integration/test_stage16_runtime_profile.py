"""Integrated Stage 16 restart, replay, robustness, and fault measurements."""

from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest

from arc3.policy import ControllerPreset
from arc3.profiling import (
    RobustnessVariant,
    RuntimeProfileConfig,
    run_fault_matrix,
    run_robustness_suite,
    run_runtime_profile,
)
from arc3.types import JSONValue


@pytest.mark.integration
def test_runtime_profile_restarts_pending_actions_and_replays_exact_trace(
    tmp_path: Path,
) -> None:
    result = run_runtime_profile(
        tmp_path / "profile",
        config=RuntimeProfileConfig(
            seed=7,
            frame_size=8,
            fixture="navigation",
            max_actions=12,
            max_resets=2,
            restart_every=2,
            wall_clock_seconds=60.0,
            max_search_nodes=2048,
            max_search_depth=32,
        ),
        git_commit="stage16-profile-test",
        preset=ControllerPreset.COMPETITION,
    )
    assert result["label"] == "synthetic"
    assert result["complete_action_chains"] is True
    assert cast(int, result["restart_count"]) >= 1
    assert result["duplicate_event_ids"] == 0
    assert result["controller_fault_count"] == 0
    assert result["submitted_action_count"] == result["consequence_count"]
    assert cast(int, result["replayed_frame_count"]) > 0
    assert cast(int, result["trace_bytes"]) > 0
    budget_assessment = cast(dict[str, JSONValue], result["budget_assessment"])
    assert set(budget_assessment) == {
        "checkpoint_bytes_within_declared_limit",
        "checkpoint_latency_within_declared_limit",
        "consequence_latency_within_declared_limit",
        "decision_latency_within_declared_limit",
        "observation_latency_within_declared_limit",
        "peak_rss_within_declared_limit",
        "total_step_latency_within_declared_limit",
        "trace_within_declared_limit",
        "wall_clock_within_declared_limit",
    }
    assert all(
        value is True
        for value in cast(dict[str, JSONValue], result["required_predicates"]).values()
    )
    assert result["trace_replay_verified"] is True
    assert result["wall_clock_cutoff_triggered"] is False
    assert cast(dict[str, JSONValue], result["checkpoint_latency_seconds"])["count"] > 0
    assert cast(dict[str, JSONValue], result["consequence_latency_seconds"])["count"] > 0
    assert cast(dict[str, JSONValue], result["total_step_latency_seconds"])["count"] > 0
    assert result["python_tracemalloc_peak_bytes"] is None
    memory_after = cast(dict[str, JSONValue], result["kernel_memory_after"])
    assert isinstance(memory_after["peak_rss_bytes"], int)


@pytest.mark.integration
def test_declared_wall_cutoff_is_a_measured_mechanism_failure(tmp_path: Path) -> None:
    result = run_runtime_profile(
        tmp_path / "wall-cutoff",
        config=RuntimeProfileConfig(
            seed=7,
            frame_size=8,
            fixture="component-stress",
            component_count=16,
            max_actions=80,
            max_resets=1,
            restart_every=0,
            decision_seconds=2.0,
            wall_clock_seconds=0.001,
            max_search_nodes=2048,
            max_search_depth=32,
        ),
        git_commit="stage16-wall-cutoff",
        preset=ControllerPreset.COMPETITION,
    )
    predicates = cast(dict[str, JSONValue], result["required_predicates"])
    budgets = cast(dict[str, JSONValue], result["budget_assessment"])
    assert result["wall_clock_cutoff_triggered"] is True
    assert predicates["forced_length_workload_completed"] is False
    assert budgets["wall_clock_within_declared_limit"] is False
    assert result["verified"] is False


@pytest.mark.integration
def test_component_stress_profile_exercises_a_bounded_planner(tmp_path: Path) -> None:
    result = run_runtime_profile(
        tmp_path / "component-planner",
        config=RuntimeProfileConfig(
            seed=25,
            frame_size=32,
            fixture="component-stress",
            component_count=64,
            max_actions=16,
            max_resets=2,
            restart_every=8,
            wall_clock_seconds=60.0,
            max_search_nodes=10_000,
            max_search_depth=32,
        ),
        git_commit="stage16-component-planner",
        preset=ControllerPreset.COMPETITION,
    )
    planner = cast(dict[str, JSONValue], result["planner"])
    assert cast(int, planner["evaluation_count"]) > 0
    assert cast(int, planner["maximum_expanded_nodes"]) <= 10_000
    assert (
        cast(dict[str, JSONValue], result["required_predicates"])["planner_exercised_and_bounded"]
        is True
    )


@pytest.mark.integration
def test_profiled_policy_is_deterministic_under_same_seed_and_budget(tmp_path: Path) -> None:
    config = RuntimeProfileConfig(
        seed=11,
        frame_size=8,
        fixture="navigation",
        max_actions=10,
        max_resets=2,
        restart_every=0,
        wall_clock_seconds=60.0,
        max_search_nodes=2048,
        max_search_depth=32,
    )
    first = run_runtime_profile(
        tmp_path / "first",
        config=config,
        git_commit="stage16-determinism",
        preset=ControllerPreset.COMPETITION,
    )
    second = run_runtime_profile(
        tmp_path / "second",
        config=config,
        git_commit="stage16-determinism",
        preset=ControllerPreset.COMPETITION,
    )
    for field in (
        "action_sequence",
        "actions",
        "consequence_count",
        "controller_fault_count",
        "final_phase",
        "resets",
        "score",
        "submitted_action_count",
        "trace_event_count",
    ):
        assert first[field] == second[field]


@pytest.mark.integration
def test_all_required_synthetic_robustness_axes_are_measured(tmp_path: Path) -> None:
    result = run_robustness_suite(
        tmp_path / "robustness",
        seeds=(7,),
        max_actions=10,
        git_commit="stage16-robustness",
        preset=ControllerPreset.COMPETITION,
    )
    cases = cast(list[dict[str, JSONValue]], result["cases"])
    assert result["case_count"] == len(RobustnessVariant)
    assert {case["variant"] for case in cases} == {variant.value for variant in RobustnessVariant}
    assert all(case["complete_action_chains"] is True for case in cases)
    assert all(case["controller_fault_count"] == 0 for case in cases)
    assert all(case["duplicate_event_ids"] == 0 for case in cases)


@pytest.mark.integration
def test_fault_matrix_receipts_every_malformed_input_boundary(tmp_path: Path) -> None:
    result = run_fault_matrix(tmp_path / "faults", git_commit="stage16-faults")
    cases = {
        cast(str, case["case"]): case for case in cast(list[dict[str, JSONValue]], result["cases"])
    }
    assert result["case_count"] == 11
    assert cases["malformed-observation-type"]["phase"] == "faulted"
    assert cases["malformed-observation-type"]["parse_receipt_count"] == 1
    assert cases["returned-action-mismatch"]["consequence_receipt_count"] == 1
    assert cases["returned-action-mismatch"]["rejection_receipt_count"] == 1
    assert cases["action-budget-exhaustion"]["phase"] == "faulted"
    assert cases["game-over-reset-only"]["reset_action"] == "RESET"
    assert cases["partial-checkpoint"]["error"] == "CheckpointError"
    assert cases["partial-checkpoint"]["preserved"] is True
    assert cases["incompatible-checkpoint"]["error"] == "CheckpointError"
    assert cases["upstream-error-before-consequence"]["phase"] == "awaiting-consequence"

    assert cases["empty-frame-batch"]["error"] == "PolicyError"
    assert cases["empty-frame-batch"]["verified"] is True
    assert cases["non-canonical-metadata"]["error"] == "PolicyError"
    assert cases["non-canonical-metadata"]["verified"] is True
    assert cases["partial-checkpoint"]["valid_checkpoint_load_error"] is None
    assert cases["partial-checkpoint"]["valid_checkpoint_preserved"] is True
    assert all(case["verified"] is True for case in cases.values())
    assert result["known_input_gaps"] == []
    assert result["status"] == "PASS"
