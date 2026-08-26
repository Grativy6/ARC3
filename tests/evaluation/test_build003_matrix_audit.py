"""Fabricated-only tests for the independent Build 003 v0.2 matrix auditor."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from pathlib import Path

import pytest
from scripts import run_build003_curriculum_matrix as matrix_cli

from arc3.evaluation.build003_matrix_audit import (
    AUDIT_SCHEMA,
    BUILD002_COMMIT,
    BUILD002_TREE,
    EXPECTED_BUDGETS,
    _expected_row,
    _validate_level_metric,
    _validate_links,
    audit_build003_matrix,
)
from arc3.evaluation.build003_results import (
    FAMILIES,
    VARIANTS,
    Build003ResultLedger,
    CurriculumResultRow,
    FrozenCase,
)
from arc3.mechanics import CHANNEL_ORDER, CompositionMode
from arc3.types import GameStateName

BUILD003_COMMIT = "1" * 40
BUILD003_TREE = "2" * 40


def _canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _digest(value: object) -> str:
    return "sha256:" + hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _file_digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _cases() -> tuple[FrozenCase, ...]:
    # These identities are intentionally fabricated.  The tests never derive,
    # import, read, or execute the frozen v0.2 held-out case set.
    return tuple(
        FrozenCase(case_id=f"fabricated-{index:02d}", seed=1000 + index) for index in range(30)
    )


def _metric(variant: str) -> dict[str, object]:
    exploratory = 0 if variant == "BLA_CLEF_FULL" else 1
    return {
        "environment_actions": 1,
        "resets": 0,
        "exploratory_actions": exploratory,
        "progress_actions": 1 - exploratory,
        "redundant_probes": 1 if variant == "BLA_ONLY_PERSISTENT" else 0,
        "actions_to_stable": exploratory,
        "movement_prediction_errors": 0,
        "resource_prediction_errors": 0,
        "resource_discrimination_actions": 0,
        "restoration_ambiguities_resolved": 0,
        "access_prediction_errors": 0,
        "hazard_prediction_errors": 0,
        "prediction_errors_by_channel": {channel.value: 0 for channel in CHANNEL_ORDER},
        "residuals_observed": 1,
        "residuals_localized": 1,
        "residuals_resolved": 1,
        "base_mechanics_retained": variant == "BLA_CLEF_FULL",
        "observed_retained_matches": 1 if variant == "BLA_CLEF_FULL" else 0,
        "erroneous_global_reopenings": 0 if variant == "BLA_CLEF_FULL" else 1,
        "passive_confirmations": 1,
        "transfer_confirmations": 1 if variant == "BLA_CLEF_FULL" else 0,
        "local_repair_candidates_opened": 1,
        "local_repairs_confirmed": 1,
        "local_repair_failures": 0,
        "base_reopenings": 0,
        "composition_events": {mode.value: 0 for mode in CompositionMode},
        "clef_promotions": 0,
        "clef_parks": 0,
        "clef_stops": 0,
        "other_object_effects_observed": 0,
        "topology_changes_confirmed": 0,
        "delayed_candidates_confirmed": 0,
        "unresolved_ledger_count": 0,
        "active_ledger_pressure": 2,
        "receipt_count": 1,
        "complete_receipt_count": 1,
        "completed": True,
    }


def _row(case: FrozenCase, variant: str, family: str, replay_digest: str) -> CurriculumResultRow:
    index = FAMILIES.index(family)
    metric = _metric(variant)
    return CurriculumResultRow(
        case_id=case.case_id,
        seed=case.seed,
        variant=variant,
        family=family,
        level_index=index + 1,
        state=GameStateName.WIN if index == len(FAMILIES) - 1 else GameStateName.NOT_FINISHED,
        completed=True,
        levels_completed=index + 1,
        environment_actions=1,
        resets=0,
        exploratory_actions=int(metric["exploratory_actions"]),
        progress_actions=int(metric["progress_actions"]),
        redundant_probes=int(metric["redundant_probes"]),
        actions_to_stable=int(metric["actions_to_stable"]),
        movement_prediction_errors=0,
        resource_prediction_errors=0,
        access_prediction_errors=0,
        hazard_prediction_errors=0,
        prediction_errors_by_channel=tuple((channel.value, 0) for channel in CHANNEL_ORDER),
        residuals_observed=1,
        residuals_localized=1,
        residuals_resolved=1,
        base_mechanics_retained=bool(metric["base_mechanics_retained"]),
        observed_retained_matches=int(metric["observed_retained_matches"]),
        erroneous_global_reopenings=int(metric["erroneous_global_reopenings"]),
        passive_confirmations=1,
        transfer_confirmations=int(metric["transfer_confirmations"]),
        local_repair_candidates_opened=1,
        local_repairs_confirmed=1,
        local_repair_failures=0,
        base_reopenings=0,
        composition_events=tuple((mode.value, 0) for mode in CompositionMode),
        clef_promotions=0,
        clef_parks=0,
        clef_stops=0,
        other_object_effects_observed=0,
        topology_changes_confirmed=0,
        delayed_candidates_confirmed=0,
        unresolved_ledger_count=0,
        active_ledger_pressure=2,
        wall_time_seconds=0.01,
        peak_memory_bytes=1024,
        replay_digest=replay_digest,
        replay_deterministic=True,
        receipt_complete=True,
    )


def _action_link(step: int, level_index: int) -> dict[str, object]:
    return {
        "step": step,
        "level_index": level_index,
        "action": {"name": "ACTION1", "coordinate": None},
        "prediction_id": f"P-{step}",
        "prediction_digest": _digest({"prediction": step}),
        "before_ref": _digest({"observation": step - 1}),
        "after_ref": _digest({"observation": step}),
        "learning_digest": _digest({"learning": step}),
        "causal_receipt_digest": _digest({"receipt": step}),
        "complete": True,
    }


def _sequence(
    case: FrozenCase, variant: str
) -> tuple[dict[str, object], list[CurriculumResultRow]]:
    replay_digest = _digest({"case": case.case_id, "variant": variant})
    metrics = [_metric(variant) for _ in FAMILIES]
    summary: dict[str, object] = {
        "schema": "arc3.build003.worker-summary.v0.1",
        "variant": variant,
        "levels": metrics,
        "receipt_count": len(FAMILIES),
        "receipt_digest": _digest({"receipts": case.case_id, "variant": variant}),
        "final_state": "WIN",
        "levels_completed": len(FAMILIES),
        "win_levels": len(FAMILIES),
    }
    if variant == "BUILD002_FROZEN":
        summary.update(
            {
                "source_commit": BUILD002_COMMIT,
                "source_tree": BUILD002_TREE,
                "source_clean": True,
                "arc3_file": "C:/fabricated-build002/src/arc3/__init__.py",
            }
        )
    else:
        summary["action_links"] = [
            _action_link(level_index + 1, level_index) for level_index in range(len(FAMILIES))
        ]
    receipt: dict[str, object] = {
        "schema": "arc3.build003.sequence-run.v0.2",
        "surface": "synthetic",
        "protocol_version": "v0.2",
        "protocol_id": "arc3.build003.curriculum.v0.2",
        "protocol_path": "docs/evaluation/build-003-curriculum-protocol.v0.2.json",
        "manifest_path": "docs/evaluation/build-003-heldout-seeds.v0.2.json",
        "budgets": EXPECTED_BUDGETS,
        "build002_baseline_identity": {"commit": BUILD002_COMMIT, "tree": BUILD002_TREE},
        "case_id": case.case_id,
        "seed": case.seed,
        "variant": variant,
        "run_status": "SUCCESS",
        "failure_reason": None,
        "final_state": "WIN",
        "levels_completed": len(FAMILIES),
        "win_levels": len(FAMILIES),
        "environment_actions": len(FAMILIES),
        "resets": 0,
        "wall_time_seconds": 0.1,
        "peak_memory_bytes": 1024,
        "replay_digest": replay_digest,
        "replay_deterministic": True,
        "receipt_links_complete": True,
        "sequence_counts_reconciled": True,
        "reported_environment_actions": len(FAMILIES),
        "reported_resets": 0,
        "worker_summary": summary,
        "claim_boundary": "Fabricated synthetic test evidence only.",
    }
    rows = [_row(case, variant, family, replay_digest) for family in FAMILIES]
    return receipt, rows


def _write_canonical(path: Path, value: object) -> None:
    path.write_text(_canonical(value) + "\n", encoding="utf-8", newline="\n")


def _write_jsonl(path: Path, values: list[dict[str, object]]) -> None:
    path.write_text(
        "".join(_canonical(value) + "\n" for value in values),
        encoding="utf-8",
        newline="\n",
    )


def _fixture(tmp_path: Path) -> tuple[Path, Path, Path, tuple[FrozenCase, ...]]:
    repository = tmp_path / "repository"
    matrix = tmp_path / "matrix"
    baseline = tmp_path / "fabricated-build002"
    (repository / "docs/evaluation").mkdir(parents=True)
    (repository / "scripts").mkdir()
    (repository / "src/arc3/evaluation").mkdir(parents=True)
    matrix.mkdir()
    (matrix / "worker-storage").mkdir()
    baseline.mkdir()
    assets = {
        "build-003-curriculum-protocol.v0.2.json": {"fabricated": "protocol"},
        "build-003-heldout-seeds.v0.2.json": {"fabricated": "manifest"},
        "build-003-preregistration-amendment.v0.2.json": {"fabricated": "preregistration"},
    }
    for name, value in assets.items():
        _write_canonical(repository / "docs/evaluation" / name, value)
    (repository / "scripts/run_build003_curriculum_matrix.py").write_text(
        "# fabricated matrix runner\n", encoding="utf-8", newline="\n"
    )
    (repository / "src/arc3/evaluation/build003_results.py").write_text(
        "# fabricated result ledger\n", encoding="utf-8", newline="\n"
    )

    cases = _cases()
    sequences_and_rows = [
        _sequence(case, variant)
        for variant, case in sorted(
            ((variant, case) for variant in VARIANTS for case in cases),
            key=lambda item: (item[0], item[1].seed),
        )
    ]
    sequences = [item[0] for item in sequences_and_rows]
    typed_rows = [row for _, rows in sequences_and_rows for row in rows]
    rows: list[dict[str, object]] = []
    for row in typed_rows:
        value = asdict(row)
        value["state"] = row.state.value
        rows.append(value)
    _write_jsonl(matrix / "rows.jsonl", rows)
    _write_jsonl(matrix / "sequence-receipts.jsonl", sequences)
    (matrix / "REPORT.md").write_text("# Fabricated matrix\n", encoding="utf-8", newline="\n")

    ledger = Build003ResultLedger(cases)
    ledger.append_many(typed_rows)
    summary = ledger.preregistered_summary()
    receipt = {
        "schema": "arc3.build003.curriculum-matrix-receipt.v0.2",
        "surface": "synthetic",
        "status": "PASS",
        "status_reason": "PREREGISTERED_H1_H2_H3_AND_EVIDENCE_QUALITY_PASSED",
        "matrix_structure_status": "COMPLETE_V02",
        "complete_preregistered_matrix": True,
        "protocol_version": "v0.2",
        "protocol_id": "arc3.build003.curriculum.v0.2",
        "protocol_path": str(
            repository / "docs/evaluation/build-003-curriculum-protocol.v0.2.json"
        ),
        "protocol_sha256": _file_digest(
            repository / "docs/evaluation/build-003-curriculum-protocol.v0.2.json"
        ),
        "manifest_path": str(repository / "docs/evaluation/build-003-heldout-seeds.v0.2.json"),
        "manifest_sha256": _file_digest(
            repository / "docs/evaluation/build-003-heldout-seeds.v0.2.json"
        ),
        "preregistration_path": str(
            repository / "docs/evaluation/build-003-preregistration-amendment.v0.2.json"
        ),
        "preregistration_sha256": _file_digest(
            repository / "docs/evaluation/build-003-preregistration-amendment.v0.2.json"
        ),
        "seed_set": "heldout",
        "case_count": 30,
        "variant_count": 4,
        "sequence_count": 120,
        "row_count": 1200,
        "expected_selected_row_count": 1200,
        "expected_full_row_count": 1200,
        "authoritative_win_sequences": 120,
        "run_status_counts": {"SUCCESS": 120},
        "wall_time_seconds": 12.0,
        "rows_path": str(matrix / "rows.jsonl"),
        "rows_sha256": _file_digest(matrix / "rows.jsonl"),
        "sequence_receipts_path": str(matrix / "sequence-receipts.jsonl"),
        "sequence_receipts_sha256": _file_digest(matrix / "sequence-receipts.jsonl"),
        "worker_storage_root": str(matrix / "worker-storage"),
        "budgets": EXPECTED_BUDGETS,
        "build002_baseline_identity": {"commit": BUILD002_COMMIT, "tree": BUILD002_TREE},
        "build003_source_identity": {
            "commit": BUILD003_COMMIT,
            "tree": BUILD003_TREE,
            "clean": True,
        },
        "build003_source_files": {
            "matrix_runner": {
                "path": str(repository / "scripts/run_build003_curriculum_matrix.py"),
                "sha256": _file_digest(repository / "scripts/run_build003_curriculum_matrix.py"),
            },
            "result_ledger": {
                "path": str(repository / "src/arc3/evaluation/build003_results.py"),
                "sha256": _file_digest(repository / "src/arc3/evaluation/build003_results.py"),
            },
        },
        "paired_summary": summary,
        "build002_source_root": str(baseline),
        "claim_boundary": "Fabricated synthetic test evidence only.",
    }
    _write_canonical(matrix / "matrix-receipt.json", receipt)
    return repository, matrix, baseline, cases


def _probe(_: Path) -> tuple[str, str, bool]:
    return BUILD002_COMMIT, BUILD002_TREE, True


def _build003_probe(_: Path) -> tuple[str, str, bool]:
    return BUILD003_COMMIT, BUILD003_TREE, True


def _audit(
    *,
    repository: Path,
    matrix: Path,
    output: Path,
    cases: tuple[FrozenCase, ...],
):
    return audit_build003_matrix(
        matrix_root=matrix,
        output_root=output,
        repository_root=repository,
        expected_cases=cases,
        build002_probe=_probe,
        build003_probe=_build003_probe,
        loaded_result_ledger_path=repository / "src/arc3/evaluation/build003_results.py",
    )


def _refresh_matrix_hash(matrix: Path, field: str, source: str) -> None:
    receipt_path = matrix / "matrix-receipt.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt[field] = _file_digest(matrix / source)
    _write_canonical(receipt_path, receipt)


def test_matrix_runner_records_build003_identity_and_source_hashes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository = tmp_path / "repository"
    result_ledger = repository / "src/arc3/evaluation/build003_results.py"
    result_ledger.parent.mkdir(parents=True)
    result_ledger.write_text("# fabricated result ledger\n", encoding="utf-8")
    answers = {
        ("rev-parse", "HEAD"): BUILD003_COMMIT,
        ("show", "-s", "--format=%T", "HEAD"): BUILD003_TREE,
        ("status", "--porcelain=v1"): "",
    }
    monkeypatch.setattr(matrix_cli, "_git", lambda _root, *args: answers[args])

    identity, source_files = matrix_cli._build003_source_binding(repository)

    assert identity == {"commit": BUILD003_COMMIT, "tree": BUILD003_TREE, "clean": True}
    assert source_files["result_ledger"] == {
        "path": str(result_ledger),
        "sha256": _file_digest(result_ledger),
    }
    assert source_files["matrix_runner"]["path"] == str(Path(matrix_cli.__file__).resolve())
    assert source_files["matrix_runner"]["sha256"] == _file_digest(
        Path(matrix_cli.__file__).resolve()
    )


def test_valid_fabricated_complete_matrix_is_independently_sealed(tmp_path: Path) -> None:
    repository, matrix, _, cases = _fixture(tmp_path)
    before = {
        path.relative_to(matrix): path.read_bytes() for path in matrix.rglob("*") if path.is_file()
    }
    outcome = _audit(
        repository=repository,
        matrix=matrix,
        output=tmp_path / "audit",
        cases=cases,
    )
    after = {
        path.relative_to(matrix): path.read_bytes() for path in matrix.rglob("*") if path.is_file()
    }

    assert outcome.passed, outcome.errors
    assert before == after
    receipt = json.loads(outcome.receipt_path.read_text(encoding="utf-8"))
    assert receipt["schema"] == AUDIT_SCHEMA
    assert receipt["status"] == "PASS"
    assert receipt["source_matrix_unchanged"] is True
    assert all(receipt["checks"].values())
    seal = receipt.pop("seal")
    assert seal["payload_sha256"] == _digest(receipt)


@pytest.mark.parametrize(
    "field",
    ("resource_discrimination_actions", "restoration_ambiguities_resolved"),
)
def test_resource_discrimination_level_counters_are_known_and_nonnegative(field: str) -> None:
    metric = _metric("BLA_CLEF_FULL")
    errors: list[str] = []

    _validate_level_metric(metric, "level", errors)

    assert errors == []

    metric[field] = -1
    _validate_level_metric(metric, "level", errors)

    assert errors == [f"level.{field} is not a non-negative integer"]


def test_final_matrix_incomplete_links_retain_level_evidence_without_row_cascade() -> None:
    # This fabricated topology reproduces the immutable matrix's 72 incomplete
    # sequences without reading or replacing its frozen held-out artifacts.
    played_level_histogram = ((1, 14), (2, 29), (5, 4), (6, 13), (7, 10), (9, 2))
    errors: list[str] = []
    row_mismatches = 0
    sequence_index = 0

    for played_levels, sequence_count in played_level_histogram:
        for _ in range(sequence_count):
            sequence_index += 1
            metrics = [_metric("BLA_CLEF_FULL") for _ in FAMILIES]
            for level_index, metric in enumerate(metrics):
                if level_index < played_levels:
                    metric["completed"] = level_index < played_levels - 1
                    continue
                metric.update(
                    {
                        "environment_actions": 0,
                        "resets": 0,
                        "receipt_count": 0,
                        "complete_receipt_count": 0,
                        "completed": False,
                    }
                )
            summary = {
                "action_links": [
                    _action_link(level_index + 1, level_index)
                    for level_index in range(played_levels)
                ]
            }
            receipt: dict[str, object] = {
                "case_id": f"fabricated-incomplete-{sequence_index:02d}",
                "seed": sequence_index,
                "variant": "BLA_CLEF_FULL",
                "run_status": "ACTION_BUDGET",
                "failure_reason": "fabricated action-budget evidence",
                "final_state": "NOT_FINISHED",
                "levels_completed": played_levels - 1,
                "environment_actions": played_levels,
                "resets": 0,
                "wall_time_seconds": 0.1,
                "peak_memory_bytes": 1024,
                "replay_digest": _digest({"sequence": sequence_index}),
                "receipt_links_complete": False,
                "sequence_counts_reconciled": True,
                "_audit_metrics": metrics,
            }
            runner_level_links = tuple(
                level_index < played_levels for level_index in range(len(FAMILIES))
            )
            recorded_rows = tuple(
                _expected_row(
                    receipt=receipt,
                    metric=metric,
                    index=level_index,
                    link_valid=runner_level_links[level_index],
                )
                for level_index, metric in enumerate(metrics)
            )

            observed_level_links = _validate_links(
                summary,
                "BLA_CLEF_FULL",
                metrics,
                receipt,
                f"sequence_receipts[{sequence_index - 1}]",
                errors,
            )
            reconstructed_rows = tuple(
                _expected_row(
                    receipt=receipt,
                    metric=metric,
                    index=level_index,
                    link_valid=observed_level_links[level_index],
                )
                for level_index, metric in enumerate(metrics)
            )
            row_mismatches += sum(
                recorded != reconstructed
                for recorded, reconstructed in zip(recorded_rows, reconstructed_rows, strict=True)
            )

    count_mismatches = sum("action/receipt counts do not reconcile" in error for error in errors)
    aggregate_incomplete = sum(
        "does not attest complete action/receipt links" in error for error in errors
    )

    assert sequence_index == 72
    assert count_mismatches == 462
    assert aggregate_incomplete == 72
    assert len(errors) == 534
    assert not any("unknown fields" in error for error in errors)
    assert row_mismatches == 0


@pytest.mark.parametrize(
    ("target", "mutate"),
    (
        (
            "rows",
            lambda rows: rows.__setitem__(
                0,
                {**rows[0], "active_ledger_pressure": rows[0]["active_ledger_pressure"] + 1},
            ),
        ),
        (
            "sequences",
            lambda sequences: sequences[1]["worker_summary"]["action_links"][1].__setitem__(
                "before_ref", "sha256:" + "f" * 64
            ),
        ),
        (
            "sequences",
            lambda sequences: sequences[0].__setitem__("replay_deterministic", False),
        ),
    ),
)
def test_adversarial_row_link_and_replay_tampering_fail_closed(
    tmp_path: Path, target: str, mutate: object
) -> None:
    repository, matrix, _, cases = _fixture(tmp_path)
    filename = "rows.jsonl" if target == "rows" else "sequence-receipts.jsonl"
    path = matrix / filename
    values = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    mutate(values)  # type: ignore[operator]
    _write_jsonl(path, values)
    hash_field = "rows_sha256" if target == "rows" else "sequence_receipts_sha256"
    _refresh_matrix_hash(matrix, hash_field, filename)

    outcome = _audit(
        repository=repository,
        matrix=matrix,
        output=tmp_path / "audit",
        cases=cases,
    )

    assert not outcome.passed
    assert outcome.errors


def test_duplicate_sequence_and_paired_summary_rewrite_fail_closed(tmp_path: Path) -> None:
    repository, matrix, _, cases = _fixture(tmp_path)
    sequences_path = matrix / "sequence-receipts.jsonl"
    sequences = [
        json.loads(line) for line in sequences_path.read_text(encoding="utf-8").splitlines()
    ]
    sequences[1]["case_id"] = sequences[0]["case_id"]
    sequences[1]["seed"] = sequences[0]["seed"]
    _write_jsonl(sequences_path, sequences)
    _refresh_matrix_hash(matrix, "sequence_receipts_sha256", "sequence-receipts.jsonl")
    receipt_path = matrix / "matrix-receipt.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["paired_summary"]["decisions"]["matrix_passed"] = False
    receipt["status"] = "FAILED_MECHANISM"
    receipt["status_reason"] = "PREREGISTERED_HYPOTHESIS_OR_EVIDENCE_GATE_FAILED"
    _write_canonical(receipt_path, receipt)

    outcome = _audit(
        repository=repository,
        matrix=matrix,
        output=tmp_path / "audit",
        cases=cases,
    )

    assert not outcome.passed
    assert any("duplicates/replaces" in error for error in outcome.errors)
    assert any("paired summary" in error for error in outcome.errors)


def test_missing_build003_source_identity_is_an_explicit_failure(tmp_path: Path) -> None:
    repository, matrix, _, cases = _fixture(tmp_path)
    receipt_path = matrix / "matrix-receipt.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    del receipt["build003_source_identity"]
    del receipt["build003_source_files"]
    _write_canonical(receipt_path, receipt)

    outcome = _audit(
        repository=repository,
        matrix=matrix,
        output=tmp_path / "audit",
        cases=cases,
    )

    assert not outcome.passed
    assert any("Build 003 commit/tree identity" in error for error in outcome.errors)
    assert any("runner/result-ledger hashes" in error for error in outcome.errors)


def test_nonempty_audit_output_cannot_be_replaced(tmp_path: Path) -> None:
    repository, matrix, _, cases = _fixture(tmp_path)
    output = tmp_path / "audit"
    output.mkdir()
    (output / "prior-receipt.json").write_text("{}\n", encoding="utf-8")

    with pytest.raises(FileExistsError, match="not empty"):
        audit_build003_matrix(
            matrix_root=matrix,
            output_root=output,
            repository_root=repository,
            expected_cases=cases,
            build002_probe=_probe,
        )
