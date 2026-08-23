"""Frozen Stage 09 local-public development-recovery protocol.

This is a pure declaration/validation layer.  It never imports an environment
adapter and cannot open a game.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, cast

from arc3.errors import EvaluationError
from arc3.evaluation.artifacts import canonical_json_bytes, sha256_bytes, verify_object_hash

PREDECLARATION_SCHEMA = "arc3.build-001.stage-09-predeclaration.v0.2"
PREFLIGHT_SCHEMA = "arc3.build-001.stage-09-preflight.v0.2"
WORKER_SPEC_SCHEMA = "arc3.build-001.stage-09-worker-spec.v0.2"
CELL_RECEIPT_SCHEMA = "arc3.build-001.stage-09-cell-receipt.v0.2"
AGGREGATE_SCHEMA = "arc3.build-001.stage-09-aggregate.v0.2"
PREDECLARATION_CORE_HASH = "sha256:b32f91fa228a7f1f2c2bbfee23e8fafc3a9affc18f9b0d3cbf9e050b0e498f3c"
PREDECLARATION_FILE_SHA256 = (
    "sha256:dce14e30d47aff7ac99551ad462c9202113dcd44c591dacd410b86363ddad348"
)

FROZEN_BUILD_001_COMMIT = "2e78c258cfbee8be62462f61ed08ad04c00a8934"
FROZEN_BUILD_001_TREE = "4145356c116944bbd7c0c412771de9179ba22efe"
FROZEN_BUILD_001_SOURCE_SHA256 = (
    "sha256:4dc8b7d7802be6b97427e12fe550bd4a6832ef30f6acdc4b509294a5a1add7f1"
)
FROZEN_BUILD_000_COMMIT = "90ecf7267d5bb23d751d6f7ce3e8aa75f2f1a130"
FROZEN_BUILD_000_TREE = "0cf6e00b2fcc399e7a99a62c20e91bb84d485f13"
FROZEN_BUILD_000_SOURCE_SHA256 = (
    "sha256:2112c390ac62432270a98fdcf6067b02c968b4139d3ee17c68bcd1d21842109c"
)
PUBLIC_PARTITION_MANIFEST_SHA256 = (
    "sha256:682d5891c2aface54803d9bd1173c55ed21e89856e13b8a478fb9276ee963f2f"
)
UPSTREAM_LOCK_SHA256 = "sha256:67e1d937e213bbcc25783784d04c4fa349b85dc09b94855256916ca6b96e808a"
STAGE08_RESULT_FILE_SHA256 = (
    "sha256:7c39fa77de24bd1925d9dbd489d583118f96d4b7fe860678607f485506ad39d4"
)
STAGE08_RESULT_CORE_HASH = "sha256:e3e078092318882f2c32887c6a223c0396938abba0ca7b30fdcde0eb5b15383f"
STAGE08_EXPOSURE_SHA256 = "sha256:be73b837805a66ed172b20573aa31c41fe6ba16ced4d471929b6018e22a5d52e"

SEEDS = (7, 11)
MAX_ACTIONS = 80
MAX_RESETS = 8
WORKER_WALL_SECONDS = 120.0
OVERALL_ACTIVE_WALL_SECONDS = 14_400.0
EXPECTED_CELL_COUNT = 96


@dataclass(frozen=True, slots=True)
class DevelopmentGame:
    game_id: str
    stable_name: str
    asset_sha256: str

    @property
    def version(self) -> str:
        prefix, separator, version = self.game_id.partition("-")
        if not separator or prefix != self.stable_name or not version:
            raise EvaluationError("Stage 09 development game identity is malformed")
        return version

    def to_dict(self) -> dict[str, str]:
        return {
            "asset_sha256": self.asset_sha256,
            "game_id": self.game_id,
            "stable_name": self.stable_name,
        }


DEVELOPMENT_GAMES = (
    DevelopmentGame(
        "tr87-cd924810",
        "tr87",
        "sha256:dcdcaf14bf6e61564d6b7e9a7503be57d65733fcdd6e5c2b02da746779274181",
    ),
    DevelopmentGame(
        "r11l-495a7899",
        "r11l",
        "sha256:483e583c88e91c2ae58ad1fa7b274d97813993796ce798551a563e1a9a78a7ff",
    ),
    DevelopmentGame(
        "cd82-fb555c5d",
        "cd82",
        "sha256:844d3717dd2bb158e658010d21363ad00b3597d12ebe0cb97c24e5d923196b90",
    ),
    DevelopmentGame(
        "sk48-d8078629",
        "sk48",
        "sha256:b8cf3491d5506a3fae0210f37a20faa7c864d8407dab18459376c9c13dc5ff41",
    ),
    DevelopmentGame(
        "m0r0-492f87ba",
        "m0r0",
        "sha256:9888ae0fce7285f40089749692ad84583b13bf0206287e1678fbfc2d907673de",
    ),
    DevelopmentGame(
        "ka59-38d34dbb",
        "ka59",
        "sha256:fe337174d175c13ae0d6796325ac55bc16261098df7b55226ad6ae3fbbef8555",
    ),
    DevelopmentGame(
        "tu93-0768757b",
        "tu93",
        "sha256:e0e3e9f475ecd6e6101adc080b91a0a05919c2ba8c64a38aba690c44057c29d3",
    ),
    DevelopmentGame(
        "lf52-271a04aa",
        "lf52",
        "sha256:3f77f216e6b97083d8cbcf50d3439b18f6556dea06e7ae2564dcdfbd8f2d8203",
    ),
    DevelopmentGame(
        "g50t-5849a774",
        "g50t",
        "sha256:60ca84c0a65821982fd5119f22f7997620df397f81205fa80882df71496b53e5",
    ),
    DevelopmentGame(
        "lp85-305b61c3",
        "lp85",
        "sha256:cfec302ab60d79cbfdb618674488fc1f733d7617f841127fe8a906da07e12561",
    ),
    DevelopmentGame(
        "ar25-0c556536",
        "ar25",
        "sha256:e796e615d2e10c93b849f9bf150308fbf84d624725deaf995d7ec2d1c2f86b22",
    ),
    DevelopmentGame(
        "ls20-9607627b",
        "ls20",
        "sha256:2c2f3412429bea00ba1173ff069304f028cfd1ba5935d896c5e10044ebbeda5a",
    ),
)


class Variant(StrEnum):
    BUILD_000_RANDOM = "build_000_random"
    BUILD_000_CYCLE = "build_000_cycle"
    BUILD_000_FULL = "build_000_full"
    BUILD_001_FULL = "build_001_full"

    @property
    def agent(self) -> str:
        return {
            Variant.BUILD_000_RANDOM: "random",
            Variant.BUILD_000_CYCLE: "cycle",
            Variant.BUILD_000_FULL: "full",
            Variant.BUILD_001_FULL: "full",
        }[self]

    @property
    def baseline_id(self) -> str:
        return {
            Variant.BUILD_000_RANDOM: "B0",
            Variant.BUILD_000_CYCLE: "B1",
            Variant.BUILD_000_FULL: "B4",
            Variant.BUILD_001_FULL: "B4",
        }[self]

    @property
    def source_commit(self) -> str:
        return (
            FROZEN_BUILD_001_COMMIT if self is Variant.BUILD_001_FULL else FROZEN_BUILD_000_COMMIT
        )

    @property
    def source_tree(self) -> str:
        return FROZEN_BUILD_001_TREE if self is Variant.BUILD_001_FULL else FROZEN_BUILD_000_TREE

    @property
    def source_sha256(self) -> str:
        return (
            FROZEN_BUILD_001_SOURCE_SHA256
            if self is Variant.BUILD_001_FULL
            else FROZEN_BUILD_000_SOURCE_SHA256
        )


VARIANTS = (
    Variant.BUILD_000_RANDOM,
    Variant.BUILD_000_CYCLE,
    Variant.BUILD_000_FULL,
    Variant.BUILD_001_FULL,
)


class CellStatus(StrEnum):
    SUCCESS = "success"
    MECHANISM_FAILURE = "mechanism_failure"
    CONTROLLER_WALL_TIMEOUT = "controller_wall_timeout"
    INFRASTRUCTURE_FAILURE = "infrastructure_failure"


@dataclass(frozen=True, slots=True)
class DevelopmentCell:
    ordinal: int
    game: DevelopmentGame
    seed: int
    variant: Variant

    @property
    def cell_id(self) -> str:
        return (
            f"s09-{self.ordinal:02d}-{self.game.stable_name}-{self.variant.value}-seed-{self.seed}"
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "agent": self.variant.agent,
            "asset_sha256": self.game.asset_sha256,
            "baseline_id": self.variant.baseline_id,
            "cell_id": self.cell_id,
            "game_id": self.game.game_id,
            "max_actions": MAX_ACTIONS,
            "max_resets": MAX_RESETS,
            "ordinal": self.ordinal,
            "partition": "development",
            "seed": self.seed,
            "source_commit": self.variant.source_commit,
            "source_tree": self.variant.source_tree,
            "surface": "local-public",
            "variant": self.variant.value,
            "worker_wall_seconds": WORKER_WALL_SECONDS,
        }

    @property
    def spec_hash(self) -> str:
        return sha256_bytes(canonical_json_bytes(self.to_dict()))


def build_matrix() -> tuple[DevelopmentCell, ...]:
    cells: list[DevelopmentCell] = []
    for game in DEVELOPMENT_GAMES:
        for seed in SEEDS:
            for variant in VARIANTS:
                cells.append(DevelopmentCell(len(cells), game, seed, variant))
    if len(cells) != EXPECTED_CELL_COUNT:
        raise EvaluationError("Stage 09 matrix size changed")
    return tuple(cells)


def matrix_hash() -> str:
    return sha256_bytes(canonical_json_bytes([cell.to_dict() for cell in build_matrix()]))


def development_partition_hash() -> str:
    return sha256_bytes(canonical_json_bytes([game.to_dict() for game in DEVELOPMENT_GAMES]))


def validate_predeclaration_bytes(
    raw: bytes, *, expected_file_sha256: str | None = None
) -> dict[str, Any]:
    if expected_file_sha256 is not None and sha256_bytes(raw) != expected_file_sha256:
        raise EvaluationError("Stage 09 predeclaration file hash changed")
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise EvaluationError("Stage 09 predeclaration is not valid JSON") from error
    if not isinstance(value, dict):
        raise EvaluationError("Stage 09 predeclaration must be an object")
    document = cast(dict[str, Any], value)
    if document.get("schema") != PREDECLARATION_SCHEMA or not verify_object_hash(
        document, hash_field="predeclaration_core_hash"
    ):
        raise EvaluationError("Stage 09 predeclaration schema/self-hash changed")
    if document.get("predeclaration_core_hash") != PREDECLARATION_CORE_HASH:
        raise EvaluationError("Stage 09 predeclaration frozen core identity changed")
    expected = {
        "build_001_commit": FROZEN_BUILD_001_COMMIT,
        "build_001_tree": FROZEN_BUILD_001_TREE,
        "build_001_first_party_source_sha256": FROZEN_BUILD_001_SOURCE_SHA256,
        "build_000_commit": FROZEN_BUILD_000_COMMIT,
        "build_000_tree": FROZEN_BUILD_000_TREE,
        "build_000_first_party_source_sha256": FROZEN_BUILD_000_SOURCE_SHA256,
        "public_partition_manifest_sha256": PUBLIC_PARTITION_MANIFEST_SHA256,
        "upstream_lock_sha256": UPSTREAM_LOCK_SHA256,
        "stage08_result_file_sha256": STAGE08_RESULT_FILE_SHA256,
        "stage08_result_core_hash": STAGE08_RESULT_CORE_HASH,
        "stage08_exposure_sha256": STAGE08_EXPOSURE_SHA256,
        "stage08_status": "FAILED_INFRASTRUCTURE",
        "development_partition_hash": development_partition_hash(),
        "matrix_hash": matrix_hash(),
        "cell_count": EXPECTED_CELL_COUNT,
        "seeds": list(SEEDS),
        "max_actions": MAX_ACTIONS,
        "max_resets": MAX_RESETS,
        "worker_wall_seconds": WORKER_WALL_SECONDS,
        "overall_active_wall_seconds": OVERALL_ACTIVE_WALL_SECONDS,
    }
    bindings = document.get("bindings")
    if not isinstance(bindings, dict) or bindings != expected:
        raise EvaluationError("Stage 09 predeclaration bindings changed")
    if document.get("development_games") != [game.to_dict() for game in DEVELOPMENT_GAMES]:
        raise EvaluationError("Stage 09 development partition changed")
    expected_matrix = {
        "expansion_order": ["development_games", "seeds", "variants"],
        "variant_order": [variant.value for variant in VARIANTS],
        "variants": [
            {
                "agent": variant.agent,
                "baseline_id": variant.baseline_id,
                "source_commit": variant.source_commit,
                "source_tree": variant.source_tree,
                "variant": variant.value,
            }
            for variant in VARIANTS
        ],
    }
    if document.get("measurement_matrix") != expected_matrix:
        raise EvaluationError("Stage 09 cell matrix changed")
    if document.get("result_state") != "READY_NOT_EXECUTED":
        raise EvaluationError("Stage 09 predeclaration contains a result")
    gate = document.get("decision_gate")
    if not isinstance(gate, dict) or set(gate) != {
        "all_evidence_verifies",
        "build_001_full_beats_b0",
        "distinct_new_completed_games_minimum",
        "full_normal_termination_fraction_minimum",
        "integrity_required",
        "status_mapping",
    }:
        raise EvaluationError("Stage 09 decision gate fields changed")
    if (
        gate.get("distinct_new_completed_games_minimum") != 2
        or gate.get("full_normal_termination_fraction_minimum") != 0.5
        or gate.get("all_evidence_verifies") is not True
        or gate.get("integrity_required") is not True
    ):
        raise EvaluationError("Stage 09 decision thresholds changed")
    return document


def _nonnegative_int(value: object, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise EvaluationError(f"Stage 09 {field} must be a non-negative integer")
    return value


def _finite_nonnegative(value: object, *, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise EvaluationError(f"Stage 09 {field} must be numeric")
    result = float(value)
    if not math.isfinite(result) or result < 0:
        raise EvaluationError(f"Stage 09 {field} must be finite and non-negative")
    return result


@dataclass(frozen=True, slots=True)
class Outcome:
    cell: DevelopmentCell
    status: CellStatus
    score_verified: bool
    levels_completed: int
    completed: bool
    environment_actions: int
    receipt_hash: str

    @classmethod
    def from_receipt(cls, value: Mapping[str, object], cell: DevelopmentCell) -> Outcome:
        receipt = dict(value)
        if receipt.get("schema") != CELL_RECEIPT_SCHEMA or not verify_object_hash(
            receipt, hash_field="cell_receipt_hash"
        ):
            raise EvaluationError("Stage 09 cell receipt hash/schema is invalid")
        expected = {
            "cell_id": cell.cell_id,
            "cell_spec_hash": cell.spec_hash,
            "game_id": cell.game.game_id,
            "seed": cell.seed,
            "variant": cell.variant.value,
            "asset_sha256": cell.game.asset_sha256,
            "source_commit": cell.variant.source_commit,
            "evidence_label": "local-public",
        }
        if any(receipt.get(key) != item for key, item in expected.items()):
            raise EvaluationError("Stage 09 cell receipt identity changed")
        raw_status = receipt.get("status")
        if not isinstance(raw_status, str):
            raise EvaluationError("Stage 09 cell status is invalid")
        status = CellStatus(raw_status)
        result = receipt.get("result")
        if not isinstance(result, dict):
            raise EvaluationError("Stage 09 cell result is missing")
        score_verified = result.get("score_verified")
        completed = result.get("completed")
        if not isinstance(score_verified, bool) or not isinstance(completed, bool):
            raise EvaluationError("Stage 09 score flags are invalid")
        levels = _nonnegative_int(result.get("levels_completed"), field="levels completed")
        actions = _nonnegative_int(result.get("environment_actions"), field="actions")
        if actions > MAX_ACTIONS:
            raise EvaluationError("Stage 09 action count exceeds its frozen budget")
        if status is CellStatus.SUCCESS and not score_verified:
            raise EvaluationError("Stage 09 successful cell lacks a verified score")
        if not score_verified and (levels or completed):
            raise EvaluationError("Stage 09 unverified score claims completion")
        receipt_hash = receipt.get("cell_receipt_hash")
        if not isinstance(receipt_hash, str):
            raise EvaluationError("Stage 09 cell receipt hash is absent")
        resources = receipt.get("resources")
        if not isinstance(resources, dict):
            raise EvaluationError("Stage 09 resource receipt is absent")
        _nonnegative_int(resources.get("supervision_wall_ns"), field="supervision wall")
        _nonnegative_int(resources.get("parent_active_wall_ns"), field="parent active wall")
        cpu = resources.get("child_cpu_seconds")
        rss = resources.get("child_peak_rss_bytes")
        if cpu is not None:
            _finite_nonnegative(cpu, field="child CPU")
        if rss is not None:
            _nonnegative_int(rss, field="child peak RSS")
        return cls(cell, status, score_verified, levels, completed, actions, receipt_hash)


def _summary(outcomes: Sequence[Outcome], variant: Variant) -> dict[str, object]:
    selected = [outcome for outcome in outcomes if outcome.cell.variant is variant]
    if len(selected) != 24:
        raise EvaluationError(f"Stage 09 {variant.value} does not contain 24 cells")
    return {
        "completed_runs": sum(outcome.completed for outcome in selected),
        "controller_wall_timeouts": sum(
            outcome.status is CellStatus.CONTROLLER_WALL_TIMEOUT for outcome in selected
        ),
        "environment_actions": sum(
            MAX_ACTIONS
            if outcome.status is CellStatus.CONTROLLER_WALL_TIMEOUT
            else outcome.environment_actions
            for outcome in selected
        ),
        "infrastructure_failures": sum(
            outcome.status is CellStatus.INFRASTRUCTURE_FAILURE for outcome in selected
        ),
        "levels_completed": sum(outcome.levels_completed for outcome in selected),
        "normal_terminations": sum(outcome.status is CellStatus.SUCCESS for outcome in selected),
        "runs": len(selected),
    }


def aggregate(
    receipts: Sequence[Mapping[str, object]],
    *,
    evidence_integrity: bool,
    competition_integrity: bool,
) -> dict[str, object]:
    """Apply the exact predeclared decision rule to all 96 receipts."""

    matrix = build_matrix()
    if len(receipts) != len(matrix):
        raise EvaluationError("Stage 09 aggregate requires exactly 96 cell receipts")
    outcomes = tuple(
        Outcome.from_receipt(receipt, cell) for receipt, cell in zip(receipts, matrix, strict=True)
    )
    summaries = {variant: _summary(outcomes, variant) for variant in VARIANTS}
    old_full_games = {
        outcome.cell.game.game_id
        for outcome in outcomes
        if outcome.cell.variant is Variant.BUILD_000_FULL and outcome.levels_completed > 0
    }
    new_full_games = {
        outcome.cell.game.game_id
        for outcome in outcomes
        if outcome.cell.variant is Variant.BUILD_001_FULL and outcome.levels_completed > 0
    }
    distinct_new_games = sorted(new_full_games - old_full_games)
    current = summaries[Variant.BUILD_001_FULL]
    random = summaries[Variant.BUILD_000_RANDOM]
    current_levels = cast(int, current["levels_completed"])
    random_levels = cast(int, random["levels_completed"])
    current_actions = cast(int, current["environment_actions"])
    random_actions = cast(int, random["environment_actions"])
    completion_count_win = current_levels > random_levels
    efficiency_win = bool(
        current_levels > 0
        and random_levels > 0
        and current_actions / current_levels < random_actions / random_levels
    )
    infrastructure_failures = sum(
        cast(int, summary["infrastructure_failures"]) for summary in summaries.values()
    )
    gate = {
        "all_evidence_verifies": evidence_integrity,
        "build_001_full_beats_b0": completion_count_win or efficiency_win,
        "competition_integrity": competition_integrity,
        "distinct_new_completed_games": len(distinct_new_games) >= 2,
        "normal_termination_fraction": cast(int, current["normal_terminations"]) / 24 >= 0.5,
    }
    status = (
        "FAILED_INFRASTRUCTURE"
        if infrastructure_failures or not evidence_integrity or not competition_integrity
        else "PASS"
        if all(gate.values())
        else "FAILED_MECHANISM"
    )
    return {
        "schema": AGGREGATE_SCHEMA,
        "status": status,
        "evidence_label": "local-public",
        "claim_boundary": "development recovery only; no public-holdout or hidden-game generalization claim",
        "matrix_hash": matrix_hash(),
        "cell_count": len(outcomes),
        "cell_receipt_hashes": [outcome.receipt_hash for outcome in outcomes],
        "variants": {variant.value: summaries[variant] for variant in VARIANTS},
        "build_001_full": {
            **current,
            "new_completed_game_ids": distinct_new_games,
            "normal_termination_fraction": cast(int, current["normal_terminations"]) / 24,
        },
        "comparison": {
            "b0_completion_count_win": completion_count_win,
            "b0_completion_normalized_action_efficiency_win": efficiency_win,
            "equal_per_run_action_budget": True,
        },
        "gate": gate,
    }


__all__ = [
    "AGGREGATE_SCHEMA",
    "CELL_RECEIPT_SCHEMA",
    "DEVELOPMENT_GAMES",
    "EXPECTED_CELL_COUNT",
    "FROZEN_BUILD_000_COMMIT",
    "FROZEN_BUILD_000_SOURCE_SHA256",
    "FROZEN_BUILD_000_TREE",
    "FROZEN_BUILD_001_COMMIT",
    "FROZEN_BUILD_001_SOURCE_SHA256",
    "FROZEN_BUILD_001_TREE",
    "MAX_ACTIONS",
    "MAX_RESETS",
    "OVERALL_ACTIVE_WALL_SECONDS",
    "PREDECLARATION_CORE_HASH",
    "PREDECLARATION_FILE_SHA256",
    "PREFLIGHT_SCHEMA",
    "PUBLIC_PARTITION_MANIFEST_SHA256",
    "SEEDS",
    "STAGE08_EXPOSURE_SHA256",
    "STAGE08_RESULT_CORE_HASH",
    "STAGE08_RESULT_FILE_SHA256",
    "VARIANTS",
    "WORKER_SPEC_SCHEMA",
    "WORKER_WALL_SECONDS",
    "CellStatus",
    "DevelopmentCell",
    "DevelopmentGame",
    "Outcome",
    "Variant",
    "aggregate",
    "build_matrix",
    "development_partition_hash",
    "matrix_hash",
    "validate_predeclaration_bytes",
]
