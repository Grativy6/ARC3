"""Process isolation, recovery, failure retention, and artifact-seal tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from arc3.errors import EvaluationError
from arc3.evaluation import (
    EvaluationConfig,
    compare_evaluations,
    load_results,
    run_evaluation,
    verify_evaluation_artifacts,
)
from arc3.evaluation.artifacts import atomic_write_json, load_json, seal_object, sha256_file

pytestmark = pytest.mark.integration


def test_isolated_comparison_emits_and_verifies_every_artifact(tmp_path: Path) -> None:
    outcome = run_evaluation(
        EvaluationConfig(
            partition="smoke",
            agents=("random", "cycle", "full"),
            seeds=(7, 11),
            max_actions=1,
            max_resets=2,
            timeout_seconds=20,
            output_root=tmp_path,
            evaluation_id="integration-clean",
        )
    )

    assert outcome.status == "PASS"
    assert outcome.summary["successful_policy_count"] == 3
    assert outcome.summary["failure_count"] == 0
    assert (outcome.directory / "manifest.json").is_file()
    assert (outcome.directory / "results.jsonl").is_file()
    assert (outcome.directory / "summary.json").is_file()
    assert (outcome.directory / "report.md").is_file()
    assert (outcome.directory / "reproduce.txt").is_file()
    manifest = load_json(outcome.directory / "manifest.json")
    assert manifest["started_at"] < manifest["completed_at"]
    assert manifest["process_isolation"] == "multiprocessing-spawn"
    assert verify_evaluation_artifacts(outcome.directory)["verified"] is True
    results = load_results(outcome.directory)
    assert all(result["trace"]["replay_verified"] is True for result in results)
    assert all(
        result["trace"]["consequence_count"]
        == result["metrics"]["environment_actions"] + result["metrics"]["resets"]
        for result in results
    )
    assert all(result["receipt_hash"].startswith("sha256:") for result in results)
    assert all(result["score"]["official_rhae"] is None for result in results)

    summary_path = outcome.directory / "summary.json"
    summary_path.write_text("{}\n", encoding="utf-8")
    tampered_summary = summary_path.read_bytes()
    verification = verify_evaluation_artifacts(outcome.directory)
    assert verification["verified"] is False
    assert "hash mismatch: summary.json" in verification["errors"]
    with pytest.raises(EvaluationError, match="tampered terminal evaluation"):
        run_evaluation(
            EvaluationConfig(
                partition="smoke",
                agents=("random", "cycle", "full"),
                seeds=(7, 11),
                max_actions=1,
                max_resets=2,
                timeout_seconds=20,
                output_root=tmp_path,
                evaluation_id="integration-clean",
            )
        )
    assert summary_path.read_bytes() == tampered_summary


def test_tampered_run_receipt_is_never_trusted_or_resealed(tmp_path: Path) -> None:
    config = EvaluationConfig(
        partition="smoke",
        agents=("random", "cycle"),
        seeds=(7,),
        max_actions=1,
        timeout_seconds=20,
        output_root=tmp_path,
        evaluation_id="integration-tamper",
    )
    outcome = run_evaluation(config)
    receipt_path = outcome.directory / "runs" / "B0-random-seed-7.json"
    receipt = load_json(receipt_path)
    receipt["score"]["score"] = 999.0
    receipt_path.write_text(
        json.dumps(receipt, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    tampered_receipt = receipt_path.read_bytes()

    verification = verify_evaluation_artifacts(outcome.directory)
    assert verification["verified"] is False
    assert "hash mismatch: runs/B0-random-seed-7.json" in verification["errors"]
    with pytest.raises(EvaluationError, match="tampered terminal evaluation"):
        run_evaluation(config)
    assert receipt_path.read_bytes() == tampered_receipt


def test_in_progress_resume_preserves_tampered_attempt_and_restarts_cleanly(
    tmp_path: Path,
) -> None:
    config = EvaluationConfig(
        partition="smoke",
        agents=("random", "cycle"),
        seeds=(7,),
        max_actions=1,
        timeout_seconds=20,
        output_root=tmp_path,
        evaluation_id="integration-resume-tamper",
    )
    first = run_evaluation(config)
    manifest_path = first.directory / "manifest.json"
    manifest = load_json(manifest_path)
    manifest["status"] = "IN_PROGRESS"
    manifest["completed_at"] = None
    manifest["artifact_hashes"] = {}
    atomic_write_json(manifest_path, seal_object(manifest, hash_field="manifest_hash"))

    receipt_path = first.directory / "runs" / "B0-random-seed-7.json"
    receipt = load_json(receipt_path)
    receipt["score"]["score"] = 999.0
    atomic_write_json(receipt_path, receipt)

    resumed = run_evaluation(config)
    assert resumed.status == "PASS"
    assert verify_evaluation_artifacts(resumed.directory)["verified"] is True
    preserved_receipts = list((resumed.directory / "failures").glob("B0-*.invalid-*.json"))
    preserved_traces = list((resumed.directory / "failures" / "traces").glob("*.invalid-*"))
    assert len(preserved_receipts) == 1
    assert len(preserved_traces) == 1
    assert load_json(preserved_receipts[0])["score"]["score"] == 999.0
    replacement = load_json(receipt_path)
    assert replacement["score"]["score"] != 999.0
    assert replacement["trace"]["consequence_count"] == 1
    report = (resumed.directory / "report.md").read_text(encoding="utf-8")
    assert "Retained invalid/interrupted attempt evidence" in report


def test_cross_evaluation_comparison_pairs_only_controlled_runs(tmp_path: Path) -> None:
    common = {
        "partition": "smoke",
        "seeds": (7, 11),
        "max_actions": 1,
        "timeout_seconds": 20,
        "output_root": tmp_path,
    }
    left = run_evaluation(
        EvaluationConfig(agents=("random",), evaluation_id="comparison-left", **common)
    )
    right = run_evaluation(
        EvaluationConfig(agents=("cycle",), evaluation_id="comparison-right", **common)
    )

    comparison = compare_evaluations([left.directory, right.directory])
    assert comparison["controlled_comparison"] is True
    assert len(comparison["paired_differences"]) == 1
    paired = comparison["paired_differences"][0]
    assert paired["left_agent"] == "random"
    assert paired["right_agent"] == "cycle"
    assert paired["shared_seeds"] == [7, 11]
    assert [row["seed"] for row in paired["observations"]] == [7, 11]


def test_abnormal_worker_exit_is_preserved_and_resume_skips_terminal_receipts(
    tmp_path: Path,
) -> None:
    config = EvaluationConfig(
        partition="smoke",
        agents=("crash-test",),
        seeds=(5,),
        max_actions=4,
        timeout_seconds=20,
        output_root=tmp_path,
        evaluation_id="integration-crash",
    )
    first = run_evaluation(config)
    crash_path = first.directory / "runs" / "TEST-CRASH-crash-test-seed-5.json"
    crash_hash = sha256_file(crash_path)
    crash = load_json(crash_path)
    assert crash["status"] == "crash"
    assert crash["failure"]["kind"] == "abnormal_process_exit"
    assert (first.directory / "failures" / crash_path.name).is_file()

    second = run_evaluation(config)
    assert sha256_file(crash_path) == crash_hash
    assert second.summary["failure_count"] == 1
