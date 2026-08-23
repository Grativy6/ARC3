"""Pure Stage 09 protocol and decision regressions."""

from __future__ import annotations

import copy
import json
from collections.abc import Mapping
from pathlib import Path

import pytest

from arc3.errors import EvaluationError
from arc3.evaluation.artifacts import canonical_json_bytes, seal_object, sha256_file
from arc3.evaluation.development_recovery import (
    CELL_RECEIPT_SCHEMA,
    EXPECTED_CELL_COUNT,
    OVERALL_ACTIVE_WALL_SECONDS,
    PREDECLARATION_FILE_SHA256,
    WORKER_WALL_SECONDS,
    CellStatus,
    DevelopmentCell,
    Variant,
    aggregate,
    build_matrix,
    matrix_hash,
    validate_predeclaration_bytes,
)

ROOT = Path(__file__).resolve().parents[2]
PREDECLARATION = ROOT / "docs/evidence/001-09-development-recovery-predeclaration.json"


def _receipt(
    cell: DevelopmentCell,
    *,
    status: CellStatus = CellStatus.SUCCESS,
    levels: int = 0,
    completed: bool = False,
    actions: int = 80,
) -> dict[str, object]:
    typed = cell
    payload = {
        "schema": CELL_RECEIPT_SCHEMA,
        "status": status.value,
        "evidence_label": "local-public",
        "cell_id": typed.cell_id,
        "cell_spec_hash": typed.spec_hash,
        "game_id": typed.game.game_id,
        "seed": typed.seed,
        "variant": typed.variant.value,
        "asset_sha256": typed.game.asset_sha256,
        "source_commit": typed.variant.source_commit,
        "result": {
            "completed": completed,
            "environment_actions": actions,
            "levels_completed": levels,
            "score_verified": status is CellStatus.SUCCESS,
        },
        "resources": {
            "child_cpu_seconds": 0.25,
            "child_peak_rss_bytes": 1_000_000,
            "parent_active_wall_ns": 12_000,
            "supervision_wall_ns": 10_000,
        },
    }
    return seal_object(payload, hash_field="cell_receipt_hash")


def _passing_receipts() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for cell in build_matrix():
        levels = 0
        if cell.variant is Variant.BUILD_000_RANDOM and cell.ordinal == 0:
            levels = 1
        if (
            cell.variant is Variant.BUILD_001_FULL
            and cell.game.stable_name in {"tr87", "r11l"}
            and cell.seed == 7
        ):
            levels = 1
        rows.append(
            _receipt(
                cell, levels=levels, actions=40 if cell.variant is Variant.BUILD_001_FULL else 80
            )
        )
    return rows


def _resign(document: Mapping[str, object]) -> bytes:
    return canonical_json_bytes(seal_object(dict(document), hash_field="predeclaration_core_hash"))


def test_predeclaration_freezes_exact_96_cell_matched_matrix() -> None:
    document = validate_predeclaration_bytes(PREDECLARATION.read_bytes())
    matrix = build_matrix()

    assert len(matrix) == EXPECTED_CELL_COUNT == 96
    assert document["bindings"]["matrix_hash"] == matrix_hash()
    assert document["bindings"]["worker_wall_seconds"] == WORKER_WALL_SECONDS == 120.0
    assert (
        document["bindings"]["overall_active_wall_seconds"]
        == OVERALL_ACTIVE_WALL_SECONDS
        == 14_400.0
    )
    assert [cell.variant for cell in matrix[:4]] == list(Variant)
    assert len({cell.spec_hash for cell in matrix}) == 96
    assert sha256_file(PREDECLARATION) == PREDECLARATION_FILE_SHA256


@pytest.mark.parametrize(
    ("section", "field", "replacement"),
    [
        ("bindings", "build_001_commit", "0" * 40),
        ("bindings", "cell_count", 24),
        ("decision_gate", "distinct_new_completed_games_minimum", 1),
    ],
)
def test_predeclaration_rejects_rehashed_semantic_tamper(
    section: str, field: str, replacement: object
) -> None:
    document = json.loads(PREDECLARATION.read_text(encoding="utf-8"))
    document[section][field] = replacement

    with pytest.raises(EvaluationError):
        validate_predeclaration_bytes(_resign(document))


def test_pass_requires_two_new_games_normal_termination_and_b0_win() -> None:
    result = aggregate(_passing_receipts(), evidence_integrity=True, competition_integrity=True)

    assert result["status"] == "PASS"
    assert result["gate"] == {
        "all_evidence_verifies": True,
        "build_001_full_beats_b0": True,
        "competition_integrity": True,
        "distinct_new_completed_games": True,
        "normal_termination_fraction": True,
    }
    current = result["build_001_full"]
    assert isinstance(current, dict)
    assert current["new_completed_game_ids"] == [
        "r11l-495a7899",
        "tr87-cd924810",
    ]


def test_complete_but_underperforming_matrix_is_failed_mechanism() -> None:
    receipts = _passing_receipts()
    for index, cell in enumerate(build_matrix()):
        if cell.variant is Variant.BUILD_001_FULL and cell.game.stable_name == "r11l":
            receipts[index] = _receipt(cell, levels=0, actions=40)

    result = aggregate(receipts, evidence_integrity=True, competition_integrity=True)

    assert result["status"] == "FAILED_MECHANISM"
    gate = result["gate"]
    assert isinstance(gate, dict)
    assert gate["distinct_new_completed_games"] is False


def test_infrastructure_cell_cannot_be_promoted_by_other_successes() -> None:
    receipts = _passing_receipts()
    cell = build_matrix()[-1]
    receipts[-1] = _receipt(
        cell,
        status=CellStatus.INFRASTRUCTURE_FAILURE,
        actions=0,
    )

    result = aggregate(receipts, evidence_integrity=False, competition_integrity=True)

    assert result["status"] == "FAILED_INFRASTRUCTURE"
    variants = result["variants"]
    assert isinstance(variants, dict)
    current = variants["build_001_full"]
    assert isinstance(current, dict)
    assert current["infrastructure_failures"] == 1


def test_competition_integrity_failure_is_infrastructure() -> None:
    result = aggregate(_passing_receipts(), evidence_integrity=True, competition_integrity=False)

    assert result["status"] == "FAILED_INFRASTRUCTURE"
    gate = result["gate"]
    assert isinstance(gate, dict)
    assert gate["competition_integrity"] is False


def test_rehashed_cell_identity_tamper_is_rejected() -> None:
    receipts = _passing_receipts()
    tampered = copy.deepcopy(receipts[0])
    tampered["game_id"] = "undeclared-development-game"
    receipts[0] = seal_object(tampered, hash_field="cell_receipt_hash")

    with pytest.raises(EvaluationError):
        aggregate(receipts, evidence_integrity=True, competition_integrity=True)


def test_wall_timeout_is_valid_mechanism_evidence_charged_full_budget() -> None:
    receipts = _passing_receipts()
    current_cells = [
        (index, cell)
        for index, cell in enumerate(build_matrix())
        if cell.variant is Variant.BUILD_001_FULL
    ]
    for index, cell in current_cells[:12]:
        receipts[index] = _receipt(
            cell,
            status=CellStatus.CONTROLLER_WALL_TIMEOUT,
            actions=80,
        )

    result = aggregate(receipts, evidence_integrity=True, competition_integrity=True)

    assert result["status"] != "FAILED_INFRASTRUCTURE"
    current = result["build_001_full"]
    assert isinstance(current, dict)
    assert current["controller_wall_timeouts"] == 12
    assert current["normal_termination_fraction"] == 0.5
