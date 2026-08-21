from __future__ import annotations

from pathlib import Path

import pytest

from arc3.ablations import AblationId, AblationProtocol, measure_ablations


@pytest.mark.integration
def test_paired_ablation_runner_uses_identical_cases_budgets_and_exact_scores(
    tmp_path: Path,
) -> None:
    protocol = AblationProtocol(
        navigation_seeds=(7, 17),
        lab_cases_per_partition=0,
        action_budget=8,
        reset_budget=1,
        max_search_nodes=512,
    )
    selected = (
        AblationId.A1,
        AblationId.A4,
        AblationId.A5,
        AblationId.A8,
        AblationId.A10,
    )
    first = measure_ablations(
        tmp_path / "first",
        protocol=protocol,
        selected_ablations=selected,
        git_commit="ablation-runner-test",
        repository_dirty=False,
    )
    second = measure_ablations(
        tmp_path / "second",
        protocol=protocol,
        selected_ablations=selected,
        git_commit="ablation-runner-test",
        repository_dirty=False,
    )

    assert first["status"] == "PASS"
    assert first["label"] == "synthetic"
    assert first["verified"] is True
    assert first["claim"] == "NO_GENERALIZATION_CLAIM"
    assert first["semantic_digest"] == second["semantic_digest"]
    assert first["case_manifest_hash"] == second["case_manifest_hash"]
    assert first["protocol_manifest_hash"].startswith("sha256:")
    assert first["protocol_manifest_matches_run"] is False
    assert first["protocol"]["action_budget"] == 8
    assert first["protocol"]["reset_budget"] == 1

    variants = first["variants"]
    full_rows = variants["FULL"]["raw_results"]
    full_case_keys = [row["case_key"] for row in full_rows]
    assert variants["FULL"]["aggregate"]["faults"] == 0
    assert variants["FULL"]["aggregate"]["total_checkpoint_bytes"] > 0
    assert variants["A1"]["aggregate"]["total_checkpoint_bytes"] == 0
    for identifier in selected:
        rows = variants[identifier.value]["raw_results"]
        assert [row["case_key"] for row in rows] == full_case_keys
        assert all(row["verified"] is True for row in rows)
        assert len(first["comparisons"][identifier.value]["paired"]) == 2

    assert first["comparisons"]["A8"]["trace_events_delta_ablation_minus_full"] < 0
    assert first["comparisons"]["A1"]["exposure"]["status"] == "PARTIAL_PROXY_ONLY"
    assert first["comparisons"]["A8"]["exposure"]["status"] == "TRACE_ONLY_NOT_POLICY_COUPLED"
    assert first["comparisons"]["A10"]["exposure"]["status"] == "RUNTIME_ONLY"
    assert first["comparisons"]["A10"]["mechanism_status"] == "MECHANISM_NOT_OBSERVED"
    assert [row["action_digest"] for row in variants["A10"]["raw_results"]] == [
        row["action_digest"] for row in full_rows
    ]
