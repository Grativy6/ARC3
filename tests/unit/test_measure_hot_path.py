from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import pytest
from scripts import measure_hot_path

from arc3.evaluation.artifacts import canonical_json_bytes, verify_object_hash


def test_trial_modes_strictly_alternate_with_equal_sample_counts() -> None:
    assert measure_hot_path._trial_modes(3) == (False, True, False, True, False, True)

    with pytest.raises(ValueError, match="repetitions"):
        measure_hot_path._trial_modes(0)


def test_measurement_preserves_exact_seeded_decisions_and_reports_phases(
    tmp_path: Path,
) -> None:
    report = measure_hot_path.measure_hot_path_overhead(
        seed=25,
        repetitions=1,
        actions=2,
        work_root=tmp_path / "work",
    )

    assert report["schema"] == "arc3.hot-path-overhead.v0.1"
    assert report["status"] == "PASS"
    assert report["evidence_label"] == "synthetic"
    assert verify_object_hash(report, hash_field="artifact_core_hash")
    comparison = report["comparison"]
    assert isinstance(comparison, dict)
    assert comparison["exact_action_decision_signatures_match"] is True
    assert comparison["exact_outcomes_match"] is True
    assert isinstance(comparison["median_wall_overhead_ratio"], float)
    trials = report["trials"]
    assert isinstance(trials, list)
    assert [trial["profiler_enabled"] for trial in trials] == [False, True]
    assert trials[0]["decision_signature"] == trials[1]["decision_signature"]
    assert trials[0]["decision_count"] == trials[1]["decision_count"]
    assert trials[0]["phase_summary"]["enabled"] is False
    assert trials[1]["phase_summary"]["enabled"] is True
    assert trials[1]["phase_summary"]["phases"]["environment_step"]["calls"] > 0
    assert trials[1]["rss"]["scope"].startswith("whole-process")
    configuration = cast(dict[str, object], report["configuration"])
    assert configuration["game_id"] == "synthetic-grid-v1"
    assert configuration["network_enabled"] is False


def test_main_writes_canonical_json_atomically(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    fixture: dict[str, object] = {
        "schema": "arc3.hot-path-overhead.v0.1",
        "status": "PASS",
        "evidence_label": "synthetic",
    }

    def fake_measurement(
        *, seed: int, repetitions: int, actions: int, work_root: Path
    ) -> dict[str, object]:
        assert (seed, repetitions, actions) == (7, 2, 3)
        assert work_root == tmp_path / "work"
        return fixture

    monkeypatch.setattr(measure_hot_path, "measure_hot_path_overhead", fake_measurement)
    output = tmp_path / "result.json"
    result = measure_hot_path.main(
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


def test_measurement_refuses_to_mix_with_existing_work_data(tmp_path: Path) -> None:
    work_root = tmp_path / "occupied"
    work_root.mkdir()
    (work_root / "prior.txt").write_text("prior evidence", encoding="utf-8")

    with pytest.raises(ValueError, match="already contains data"):
        measure_hot_path.measure_hot_path_overhead(
            seed=25,
            repetitions=1,
            actions=1,
            work_root=work_root,
        )
