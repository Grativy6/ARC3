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
    BUILD_000_INTEGRITY_FILE_SHA256,
    BUILD_000_INTEGRITY_RECEIPT_SHA256,
    BUILD_001_INTEGRITY_FILE_SHA256,
    BUILD_001_INTEGRITY_RECEIPT_SHA256,
    CELL_RECEIPT_SCHEMA,
    ENVIRONMENT_CACHE_SCHEMA,
    EXPECTED_CELL_COUNT,
    HARNESS_SOURCE_BINDING_SCHEMA,
    HARNESS_SOURCE_OBSERVATION_SCHEMA,
    HARNESS_SOURCE_PATHS,
    HOLDOUT_NONCONSUMPTION_FILE_SHA256,
    OVERALL_ACTIVE_WALL_SECONDS,
    PREDECLARATION_FILE_SHA256,
    PRIOR_AUTHORITY_SCHEMA,
    RUNTIME_ENVIRONMENT_OBSERVATION_SCHEMA,
    RUNTIME_ENVIRONMENT_SCHEMA,
    WORKER_WALL_SECONDS,
    CellStatus,
    DevelopmentCell,
    Variant,
    aggregate,
    build_matrix,
    matrix_hash,
    validate_environment_cache_observation,
    validate_predeclaration_bytes,
    validate_prior_authority_observation,
    validate_runtime_environment_observation,
)

ROOT = Path(__file__).resolve().parents[2]
PREDECLARATION = ROOT / "docs/evidence/001-09-development-recovery-predeclaration.json"


def _boundaries() -> dict[str, object]:
    harness_expected = seal_object(
        {
            "schema": HARNESS_SOURCE_BINDING_SCHEMA,
            "git_commit": "a" * 40,
            "git_tree": "b" * 40,
            "files": {path: "sha256:" + "1" * 64 for path in HARNESS_SOURCE_PATHS},
        },
        hash_field="binding_hash",
    )
    harness_predicates = {
        "clean": True,
        "commit": True,
        "detached": True,
        "files": True,
        "root": True,
        "tree": True,
    }
    harness_observation = seal_object(
        {
            "schema": HARNESS_SOURCE_OBSERVATION_SCHEMA,
            "binding_hash": harness_expected["binding_hash"],
            "branch": "",
            "dirty_worktree": False,
            "files": harness_expected["files"],
            "git_commit": harness_expected["git_commit"],
            "git_tree": harness_expected["git_tree"],
            "passed": True,
            "predicates": harness_predicates,
            "root": "C:/frozen-harness",
        },
        hash_field="observation_hash",
    )
    critical_versions = {
        "annotated-types": "0.8.0",
        "numpy": "2.5.2",
        "pydantic": "2.13.4",
        "pydantic-core": "2.46.4",
        "typing-extensions": "4.16.0",
        "typing-inspection": "0.4.4",
    }
    distributions = {
        name: {"file_count": 1, "source_sha256": "sha256:" + digit * 64, "version": version}
        for name, digit, version in (("arc-agi", "2", "0.9.9"), ("arcengine", "3", "0.9.3"))
    }
    runtime_expected = seal_object(
        {
            "schema": RUNTIME_ENVIRONMENT_SCHEMA,
            "cache_tag": "cpython-312",
            "critical_versions": critical_versions,
            "distributions": distributions,
            "executable": "C:/python.exe",
            "executable_sha256": "sha256:" + "4" * 64,
            "implementation": "CPython",
            "python_version": "3.12.14",
            "scorer": {
                "distribution": "arc-agi",
                "module": "arc_agi/scorecard.py",
                "sha256": "sha256:" + "5" * 64,
                "source_version": "fixture",
            },
            "sdk_import_probe": True,
            "upstream_lock_sha256": "sha256:" + "6" * 64,
            "uv_lock_sha256": "sha256:" + "7" * 64,
        },
        hash_field="runtime_binding_hash",
    )
    runtime_actual = {
        key: value
        for key, value in runtime_expected.items()
        if key not in {"runtime_binding_hash", "schema"}
    }
    runtime_observation = seal_object(
        {
            "schema": RUNTIME_ENVIRONMENT_OBSERVATION_SCHEMA,
            "actual": runtime_actual,
            "binding_hash": runtime_expected["runtime_binding_hash"],
            "passed": True,
            "predicates": {key: True for key in runtime_actual},
        },
        hash_field="observation_hash",
    )
    authority = seal_object(
        {
            "schema": PRIOR_AUTHORITY_SCHEMA,
            "holdout": {
                "file_sha256": HOLDOUT_NONCONSUMPTION_FILE_SHA256,
                "identities_loaded": 0,
                "manifest_loaded_as_metadata": False,
                "path": "C:/authority/holdout.json",
                "status": "SEALED_UNCONSUMED",
            },
            "integrity": {
                name: {
                    "file_sha256": file_sha256,
                    "git_commit": git_commit,
                    "path": f"C:/authority/{name}.json",
                    "receipt_sha256": receipt_sha256,
                }
                for name, file_sha256, git_commit, receipt_sha256 in (
                    (
                        "build_000",
                        BUILD_000_INTEGRITY_FILE_SHA256,
                        "90ecf7267d5bb23d751d6f7ce3e8aa75f2f1a130",
                        BUILD_000_INTEGRITY_RECEIPT_SHA256,
                    ),
                    (
                        "build_001",
                        BUILD_001_INTEGRITY_FILE_SHA256,
                        "2e78c258cfbee8be62462f61ed08ad04c00a8934",
                        BUILD_001_INTEGRITY_RECEIPT_SHA256,
                    ),
                )
            },
            "passed": True,
            "predicates": {
                "build_000_integrity": True,
                "build_001_integrity": True,
                "holdout_file_hash": True,
                "holdout_manifest_hash": True,
                "holdout_nonconsumption": True,
            },
        },
        hash_field="authority_hash",
    )
    cache_values = {
        "aggregate_sha256": "sha256:" + "b" * 64,
        "directory_count": 30,
        "entry_count": 60,
        "recursive_bytes": 100,
        "recursive_file_count": 30,
        "root_file_count": 0,
        "top_level_directory_count": 15,
    }
    cache = seal_object(
        {
            "schema": ENVIRONMENT_CACHE_SCHEMA,
            "actual": dict(cache_values),
            "expected": dict(cache_values),
            "holdout_identities_loaded": 0,
            "passed": True,
            "predicates": {
                **{key: True for key in cache_values},
                "root_present": True,
                "symlinks_absent": True,
            },
            "root": "C:/opaque-cache",
        },
        hash_field="cache_identity_hash",
    )
    return {
        "environment_cache": {"after": cache, "before": cache, "stable": True},
        "harness_source": {
            "after": harness_observation,
            "before": harness_observation,
            "expected": harness_expected,
            "stable": True,
        },
        "prior_authority": {"after": authority, "before": authority, "stable": True},
        "runtime_environment": {
            "after": runtime_observation,
            "before": runtime_observation,
            "expected": runtime_expected,
            "stable": True,
        },
    }


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
        **_boundaries(),
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


@pytest.mark.parametrize("drift", ["dependency", "scorer"])
def test_rehashed_passing_runtime_dependency_or_scorer_drift_is_rejected(drift: str) -> None:
    boundaries = _boundaries()
    runtime = boundaries["runtime_environment"]
    assert isinstance(runtime, dict)
    expected = runtime["expected"]
    observation = copy.deepcopy(runtime["before"])
    assert isinstance(expected, dict)
    assert isinstance(observation, dict)
    actual = observation["actual"]
    assert isinstance(actual, dict)
    if drift == "dependency":
        versions = actual["critical_versions"]
        assert isinstance(versions, dict)
        versions["numpy"] = "0.0.0"
    else:
        scorer = actual["scorer"]
        assert isinstance(scorer, dict)
        scorer["sha256"] = "sha256:" + "f" * 64
    tampered = seal_object(observation, hash_field="observation_hash")

    with pytest.raises(EvaluationError, match="runtime environment identity changed"):
        validate_runtime_environment_observation(tampered, expected=expected)


def test_rehashed_passing_prior_integrity_receipt_drift_is_rejected() -> None:
    boundaries = _boundaries()
    prior = copy.deepcopy(boundaries["prior_authority"])
    assert isinstance(prior, dict)
    observation = prior["before"]
    assert isinstance(observation, dict)
    integrity = observation["integrity"]
    assert isinstance(integrity, dict)
    build_001 = integrity["build_001"]
    assert isinstance(build_001, dict)
    build_001["file_sha256"] = "sha256:" + "f" * 64
    tampered = seal_object(observation, hash_field="authority_hash")

    with pytest.raises(EvaluationError, match="prior integrity receipt identity changed"):
        validate_prior_authority_observation(tampered)


def test_rehashed_passing_opaque_cache_inventory_drift_is_rejected() -> None:
    boundaries = _boundaries()
    cache_boundary = copy.deepcopy(boundaries["environment_cache"])
    assert isinstance(cache_boundary, dict)
    observation = cache_boundary["before"]
    assert isinstance(observation, dict)
    actual = observation["actual"]
    assert isinstance(actual, dict)
    actual["entry_count"] = 61
    tampered = seal_object(observation, hash_field="cache_identity_hash")

    with pytest.raises(EvaluationError, match="environment-cache inventory changed"):
        validate_environment_cache_observation(tampered)
