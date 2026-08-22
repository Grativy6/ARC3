from __future__ import annotations

import json
from itertools import pairwise
from pathlib import Path

import pytest
from scripts import diagnose_hot_path

from arc3.evaluation.artifacts import canonical_json_bytes, verify_object_hash


def test_factor_schedule_balances_complete_block_and_changes_one_factor_at_a_time() -> None:
    schedule = diagnose_hot_path._factor_schedule(4)
    expected_cells = {
        (False, False),
        (True, False),
        (True, True),
        (False, True),
    }
    assert len(schedule) == 4
    assert all(
        {(cell.tracemalloc_enabled, cell.automatic_checkpointing_enabled) for cell in order}
        == expected_cells
        for order in schedule
    )
    for position in range(4):
        assert {
            (
                order[position].tracemalloc_enabled,
                order[position].automatic_checkpointing_enabled,
            )
            for order in schedule
        } == expected_cells
    for order in schedule:
        for left, right in pairwise(order):
            changed = int(left.tracemalloc_enabled != right.tracemalloc_enabled) + int(
                left.automatic_checkpointing_enabled != right.automatic_checkpointing_enabled
            )
            assert changed == 1

    with pytest.raises(ValueError, match="repetitions"):
        diagnose_hot_path._factor_schedule(0)


def test_factorial_metrics_report_marginal_and_interaction_effects() -> None:
    values = {
        (False, False): 10,
        (True, False): 20,
        (True, True): 80,
        (False, True): 30,
    }
    trials: list[dict[str, object]] = []
    for (tracing, checkpoints), value in values.items():
        trials.append(
            {
                "cpu_ns": value * 2,
                "factors": {
                    "automatic_checkpointing_enabled": checkpoints,
                    "tracemalloc_enabled": tracing,
                },
                "wall_ns": value,
                "wall_ns_per_environment_action": value / 2,
            }
        )

    wall = diagnose_hot_path._factorial_metrics(trials)["wall_ns"]
    assert isinstance(wall, dict)
    assert wall["tracemalloc_marginal_delta"] == 30.0
    assert wall["checkpoint_marginal_delta"] == 40.0
    interaction = wall["interaction"]
    assert isinstance(interaction, dict)
    assert interaction["additive_difference_of_differences"] == 40.0
    assert interaction["multiplicative_cross_ratio"] == pytest.approx(4 / 3)
    trace_effect = wall["tracemalloc_effect_by_checkpoint"]
    assert isinstance(trace_effect, dict)
    assert trace_effect["checkpoints_disabled_ratio"] == 2.0
    checkpoint_effect = wall["checkpoint_effect_by_tracemalloc"]
    assert isinstance(checkpoint_effect, dict)
    assert checkpoint_effect["tracemalloc_enabled_ratio"] == 4.0


def test_synthetic_diagnosis_is_self_hashed_and_behavior_preserving(tmp_path: Path) -> None:
    report = diagnose_hot_path.diagnose_hot_path(
        seed=25,
        repetitions=1,
        actions=1,
        work_root=tmp_path / "work",
    )

    assert report["schema"] == "arc3.hot-path-causal-diagnosis.v0.1"
    assert report["status"] == "PASS"
    assert report["evidence_label"] == "synthetic"
    assert verify_object_hash(report, hash_field="artifact_core_hash")
    controls = report["controls"]
    assert isinstance(controls, dict)
    assert controls["exact_action_decision_signatures_match"] is True
    assert controls["exact_environment_outcomes_match"] is True
    assert controls["hot_path_profile_enabled_every_trial"] is True

    trials = report["trials"]
    assert isinstance(trials, list)
    assert len(trials) == 4
    factor_cells = {
        (
            trial["factors"]["tracemalloc_enabled"],
            trial["factors"]["automatic_checkpointing_enabled"],
        )
        for trial in trials
    }
    assert factor_cells == {
        (False, False),
        (True, False),
        (True, True),
        (False, True),
    }
    assert all(trial["hot_path_profile"]["enabled"] is True for trial in trials)
    assert all(trial["trace_metrics"]["event_count"] > 0 for trial in trials)
    assert all(
        trial["checkpoint_metrics"]["immutable_checkpoint_count"] > 0
        for trial in trials
        if trial["factors"]["automatic_checkpointing_enabled"] is True
    )
    assert all(
        trial["checkpoint_metrics"]["immutable_checkpoint_count"] == 0
        for trial in trials
        if trial["factors"]["automatic_checkpointing_enabled"] is False
    )
    microbenchmark = report["microbenchmark"]
    assert isinstance(microbenchmark, dict)
    assert microbenchmark["status"] == "PASS"
    comparison = microbenchmark["comparison"]
    assert isinstance(comparison, dict)
    assert comparison["policy_state_unchanged"] is True
    assert comparison["method_outputs_unchanged"] is True
    assert comparison["exact_candidate_signatures_match"] is True
    assert comparison["active_ensemble_sampled_every_trial"] is True
    assert comparison["prediction_and_state_identity_rows_present_every_trial"] is True
    for trial in microbenchmark["trials"]:
        assert trial["setup_actions"] == 2
        assert trial["setup_active_world_model_count"] > 0
        assert trial["setup_active_hypothesis_count"] > 0
        assert trial["setup_candidate_count"] > 0
        assert trial["cprofile_top_by_cumulative_time"]
        assert trial["cprofile_prediction_rows"]
        assert trial["cprofile_state_identity_rows"]


def test_main_writes_canonical_json_atomically(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    fixture: dict[str, object] = {
        "schema": "arc3.hot-path-causal-diagnosis.v0.1",
        "status": "PASS",
        "evidence_label": "synthetic",
    }

    def fake_diagnosis(
        *, seed: int, repetitions: int, actions: int, work_root: Path
    ) -> dict[str, object]:
        assert (seed, repetitions, actions) == (7, 2, 3)
        assert work_root == tmp_path / "work"
        return fixture

    monkeypatch.setattr(diagnose_hot_path, "diagnose_hot_path", fake_diagnosis)
    output = tmp_path / "result.json"
    result = diagnose_hot_path.main(
        [
            "--seed",
            "7",
            "--repetitions",
            "2",
            "--actions",
            "3",
            "--output",
            str(output),
            "--work-root",
            str(tmp_path / "work"),
        ]
    )

    assert result == 0
    assert output.read_bytes() == canonical_json_bytes(fixture)
    assert json.loads(capsys.readouterr().out) == fixture


def test_diagnosis_refuses_to_mix_with_existing_work_data(tmp_path: Path) -> None:
    work_root = tmp_path / "occupied"
    work_root.mkdir()
    (work_root / "prior.txt").write_text("prior evidence", encoding="utf-8")

    with pytest.raises(ValueError, match="already contains data"):
        diagnose_hot_path.diagnose_hot_path(
            seed=25,
            repetitions=1,
            actions=1,
            work_root=work_root,
        )
