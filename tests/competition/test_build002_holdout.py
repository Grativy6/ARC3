"""Fail-closed tests for the Build 002 one-shot public-run boundary."""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import tempfile
from dataclasses import asdict
from functools import cache
from pathlib import Path
from typing import Any, cast

import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]
import pytest
from scripts import run_build002_holdout as runner
from scripts.run_build002_holdout import RUN_PLAN_SCHEMA, _collector_source

import arc3.evaluation.build002_holdout as build002_holdout
import arc3.evaluation.build002_preflight as build002_preflight
from arc3.competition import GovernorStopReason, TournamentGovernor
from arc3.competition_runtime import FROZEN_COMPETITION_RUNTIME
from arc3.errors import EvaluationError
from arc3.evaluation.artifacts import atomic_write_json, sha256_file
from arc3.evaluation.build002_holdout import (
    BUILD_002_ATTEMPT_ID,
    CANONICAL_STATE_RELATIVE,
    ArtifactBinding,
    FailureClassification,
    GameMeasurement,
    LevelMeasurement,
    OneShotHoldoutSeal,
    ReceiptBinding,
    create_frozen_preflight,
    create_runtime_evidence_manifest,
    create_static_asset_inventory,
    validate_consumed_failure,
    validate_terminal_result,
)
from arc3.evaluation.build002_preflight import GATE_EVIDENCE_ROLES
from arc3.evaluation.public import PublicPartitionManifest
from arc3.packaging.builder import build_kaggle_candidate
from arc3.packaging.notebook import notebook_embedded_inputs

REPOSITORY = Path(__file__).resolve().parents[2]
MANIFEST = REPOSITORY / "docs" / "evaluation" / "public-game-partitions.v0.1.json"

GATE_ROLES = (
    "competition-lifecycle",
    "dependency-and-config-identity",
    "deterministic-startup-and-replay",
    "frozen-source-config-artifacts",
    "notebook-build-and-offline-entry-point",
    "offline-cold-start",
    "official-source-identity",
    "package-and-license-inventory",
    "secret-and-integrity-scan",
    "submission-parquet-structure",
)
ARTIFACT_ROLES = (
    "agent-wrapper",
    "competition-runtime-config",
    "dependency-lock",
    "holdout-asset-inventory",
    "kaggle-notebook",
    "offline-package-candidate",
    "source-preview-contamination-receipt",
    "submission-parquet",
    "third-party-notices",
    "upstream-lock",
)
RESULT_ARTIFACT_ROLES = (
    "competition-launch-receipt",
    "execution-profile",
    "failure-receipts",
    "local-scorecard",
    "runtime-evidence-manifest",
    "submission-parquet",
)


@pytest.fixture(autouse=True)
def _separate_fixture_receipts_from_production_semantics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep holdout state tests focused on v0.2 binding and one-shot mechanics."""

    monkeypatch.setattr(
        build002_preflight,
        "validate_production_evidence_rows",
        lambda _root, _evidence_rows, _artifact_rows, *, gate_checks=None: None,
    )


def _git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )


def _fixture_evidence_rows(root: Path, evidence: Path) -> dict[str, dict[str, object]]:
    rows: dict[str, dict[str, object]] = {}
    for role in sorted(GATE_EVIDENCE_ROLES):
        path = evidence / ("LICENSE" if role == "first-party-license" else f"{role}.json")
        if role == "first-party-license":
            shutil.copyfile(REPOSITORY / "LICENSE", path)
        else:
            atomic_write_json(
                path,
                {
                    "fixture": True,
                    "schema": f"arc3.test.build-002.{role}.v0.1",
                    "status": "PASS",
                },
            )
        rows[role] = {
            "byte_length": path.stat().st_size,
            "path": path.relative_to(root).as_posix(),
            "sha256": sha256_file(path),
        }
    return rows


def _write_gate_receipts(evidence: Path, artifacts: list[ArtifactBinding]) -> list[ReceiptBinding]:
    root = evidence.parent
    artifact_hashes = {binding.role: sha256_file(binding.path) for binding in artifacts}
    evidence_rows = _fixture_evidence_rows(root, evidence)
    gates: list[ReceiptBinding] = []
    for role in GATE_ROLES:
        path = evidence / f"{role}.json"
        atomic_write_json(
            path,
            {
                "artifact_sha256": {
                    artifact_role: artifact_hashes[artifact_role]
                    for artifact_role in sorted(build002_holdout._GATE_ARTIFACT_ROLES[role])
                },
                "checks": {check: True for check in sorted(build002_holdout._GATE_CHECKS[role])},
                "evidence": evidence_rows,
                "evidence_class": "production",
                "schema": build002_holdout._GATE_SCHEMAS[role],
                "status": "PASS",
            },
        )
        gates.append(ReceiptBinding(role, path))
    return gates


@cache
def _validated_candidate_fixture() -> tuple[bytes, bytes, bytes]:
    parent = REPOSITORY / "artifacts" / "test-tmp"
    parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix="build002-holdout-candidate-", dir=parent))
    try:
        result = build_kaggle_candidate(
            REPOSITORY,
            temporary / "package",
            allow_dirty_preacceptance=True,
        )
        assert result.status in {"PACKAGING_PASS", "PACKAGING_PREACCEPTANCE"}
        notebook = json.loads(result.notebook.read_text(encoding="utf-8"))
        embedded = notebook_embedded_inputs(notebook)
        return (
            result.candidate_archive.read_bytes(),
            result.notebook.read_bytes(),
            embedded.validation_parquet,
        )
    finally:

        def remove_readonly(function: Any, path: str, _error: BaseException) -> None:
            os.chmod(path, stat.S_IWRITE)
            function(path)

        shutil.rmtree(temporary, onexc=remove_readonly)


def _prepared_root(
    tmp_path: Path,
) -> tuple[Path, tuple[str, ...], list[ReceiptBinding], list[ArtifactBinding]]:
    root = tmp_path / "repository"
    evidence = root / "evidence"
    payload = root / "payload"
    assets_root = root / "assets"
    manifest_path = root / "docs" / "evaluation" / MANIFEST.name
    evidence.mkdir(parents=True)
    payload.mkdir(parents=True)
    assets_root.mkdir(parents=True)
    manifest_path.parent.mkdir(parents=True)
    shutil.copyfile(MANIFEST, manifest_path)
    (root / ".gitignore").write_text("artifacts/\n", encoding="utf-8")

    manifest = PublicPartitionManifest.load(manifest_path)
    games = tuple(sorted(entry.game_id for entry in manifest.games("public-holdout")))
    assets: dict[str, Path] = {}
    for game_id in games:
        path = assets_root / f"{game_id}.arc"
        path.write_bytes((game_id + "\n").encode())
        assets[game_id] = path
    inventory_path = payload / "holdout-assets.json"
    atomic_write_json(inventory_path, create_static_asset_inventory(manifest_path, assets))

    production_agent = root / "agent" / "my_agent.py"
    production_agent.parent.mkdir(parents=True)
    shutil.copyfile(REPOSITORY / "agent" / "my_agent.py", production_agent)
    agent_path = payload / "agent-wrapper.py"
    agent_path.write_bytes(_collector_source(production_agent))
    runtime_path = payload / "competition-runtime-config.json"
    shutil.copyfile(REPOSITORY / "src" / "arc3" / "competition-runtime.v0.2.json", runtime_path)
    dependency_path = payload / "uv.lock"
    shutil.copyfile(REPOSITORY / "uv.lock", dependency_path)

    package_path = payload / "offline-package-candidate.zip"
    candidate_bytes, notebook_bytes, submission_bytes = _validated_candidate_fixture()
    package_path.write_bytes(candidate_bytes)
    submission_path = payload / "submission.parquet"
    submission_path.write_bytes(submission_bytes)
    notebook_path = payload / "arc3-submission.ipynb"
    notebook_path.write_bytes(notebook_bytes)

    preview_path = payload / "source-preview-contamination-receipt.json"
    atomic_write_json(
        preview_path,
        {
            "schema": "arc3.build-002.public-source-preview-contamination.v0.1",
            "exposure": {
                "environment_actions": 0,
                "environment_make_interactions": 0,
                "production_policy_changes_derived_from_snippet": False,
            },
            "authority": {
                "build_002_mechanical_consumption_boundary_crossed": False,
            },
            "consequence": {
                "future_public_run_may_be_labeled_pristine_or_unseen": False,
                "future_public_run_evidence_label": "local-public-source-preview-exposed",
            },
        },
    )
    notices_path = payload / "THIRD_PARTY_NOTICES.md"
    shutil.copyfile(REPOSITORY / "THIRD_PARTY_NOTICES.md", notices_path)
    upstream_path = payload / "upstream.lock.json"
    shutil.copyfile(REPOSITORY / "upstream.lock.json", upstream_path)

    artifact_paths = {
        "agent-wrapper": agent_path,
        "competition-runtime-config": runtime_path,
        "dependency-lock": dependency_path,
        "holdout-asset-inventory": inventory_path,
        "kaggle-notebook": notebook_path,
        "offline-package-candidate": package_path,
        "source-preview-contamination-receipt": preview_path,
        "submission-parquet": submission_path,
        "third-party-notices": notices_path,
        "upstream-lock": upstream_path,
    }
    artifacts = [ArtifactBinding(role, artifact_paths[role]) for role in ARTIFACT_ROLES]
    gates = _write_gate_receipts(evidence, artifacts)

    framework_root = root / "framework"
    framework_root.mkdir()
    run_plan_path = root / "run-plan.json"
    atomic_write_json(
        run_plan_path,
        {
            "artifacts": {
                binding.role: binding.path.relative_to(root).as_posix() for binding in artifacts
            },
            "assets": {game_id: str(path.resolve()) for game_id, path in sorted(assets.items())},
            "framework_root": str(framework_root.resolve()),
            "gateway_host": "127.0.0.1",
            "gateway_port": 8001,
            "gates": {binding.role: binding.path.relative_to(root).as_posix() for binding in gates},
            "manifest": manifest_path.relative_to(root).as_posix(),
            "production_agent": production_agent.relative_to(root).as_posix(),
            "schema": RUN_PLAN_SCHEMA,
            "seed": 0,
            "submission_output": str((root / "runtime-output" / "submission.parquet").resolve()),
        },
    )

    _git(root, "init", "-q")
    _git(root, "add", ".")
    _git(
        root,
        "-c",
        "user.name=ARC3 Test",
        "-c",
        "user.email=arc3-test@example.invalid",
        "commit",
        "-q",
        "-m",
        "fixture",
    )
    return root, games, gates, artifacts


def _arm(
    tmp_path: Path,
) -> tuple[Path, Path, Path, tuple[str, ...], OneShotHoldoutSeal]:
    root, games, gates, artifacts = _prepared_root(tmp_path)
    state = root / CANONICAL_STATE_RELATIVE
    preflight_path = state / "preflight.json"
    preflight = _create_fixture_preflight(root, gates, artifacts)
    atomic_write_json(preflight_path, preflight)
    seal = OneShotHoldoutSeal.arm(root, state_root=state, preflight_path=preflight_path)
    return root, state, preflight_path, games, seal


def _create_fixture_preflight(
    root: Path,
    gates: list[ReceiptBinding],
    artifacts: list[ArtifactBinding],
) -> dict[str, Any]:
    """Exercise the freeze except the separately tested production evidence semantics."""

    return create_frozen_preflight(
        root,
        attempt_id=BUILD_002_ATTEMPT_ID,
        seed=0,
        manifest_path=root / "docs" / "evaluation" / MANIFEST.name,
        run_plan_path=root / "run-plan.json",
        gates=gates,
        artifacts=artifacts,
    )


def _launch_receipt(games: tuple[str, ...]) -> dict[str, Any]:
    tournament_start = 100.0
    game_rows = []
    for ordinal, game_id in enumerate(games):
        began = tournament_start + ordinal * 0.1
        finalized = began + 0.1
        game_rows.append(
            {
                "actions_authorized": 2,
                "allocated_seconds": 1.0,
                "allocation_overrun_seconds": 0.0,
                "began_at_seconds": began,
                "elapsed_action_cost_total_seconds": 0.1,
                "elapsed_seconds": finalized - began,
                "fallback_actions": 0,
                "finalized_at_seconds": finalized,
                "future_opportunity_cost_total_actions": (2 if ordinal < len(games) - 1 else 0),
                "future_opportunity_cost_total_seconds": (0.1 if ordinal < len(games) - 1 else 0.0),
                "game_id": game_id,
                "game_ordinal": ordinal + 1,
                "reason": "win",
                "reset_limit": 8,
                "resets_authorized": 1,
                "reserve_remaining_seconds": 6000.0,
                "selected_value_total": 0.5,
                "sequence": 10 + ordinal,
                "tournament_playable_seconds_remaining": max(
                    0.0, 26400.0 - (finalized - tournament_start)
                ),
                "unassigned_tail_elapsed_seconds": 0.0,
            }
        )
    tournament_end = cast(float, game_rows[-1]["finalized_at_seconds"])
    tournament_elapsed = tournament_end - tournament_start
    return {
        "agent_count": len(games),
        "all_environments_covered": True,
        "close_scorecard_count": 1,
        "discovered_environments": list(games),
        "dotenv_imported": False,
        "framework_commit": "4743e7d0aaae0ded0d98a89a7e282e63564cd58b",
        "framework_fixture": False,
        "framework_identity": "git:4743e7d0aaae0ded0d98a89a7e282e63564cd58b",
        "game_count": len(games),
        "gateway_host": "127.0.0.1",
        "gateway_port": 8001,
        "get_scorecard_during_flight_count": 0,
        "hard_deadline_seconds": 32470.0,
        "hard_timeout_enforced": True,
        "lifecycle_enforced": True,
        "make_count": len(games),
        "max_concurrency": 1,
        "notebook_started_at_seconds": 100.0,
        "open_scorecard_count": 1,
        "orchestration": "arc3.sequential-pinned-swarm.v1",
        "telemetry_imported": False,
        "tournament_configured": True,
        "tournament_finalized": True,
        "tournament_receipt": {
            "status": "PASS",
            "receipt": {
                "ceiling_remaining_seconds": 32400.0 - tournament_elapsed,
                "dropped_history_receipts": 0,
                "effective_ceiling_respected": True,
                "elapsed_seconds": tournament_elapsed,
                "expected_environments": len(games),
                "finalized_at_seconds": tournament_end,
                "finalized_environments": len(games),
                "future_opportunity_cost_total_seconds": 0.1 * (len(games) - 1),
                "games": game_rows,
                "maximum_total_actions": 80 * len(games),
                "maximum_resets_per_game": 8,
                "maximum_total_resets": 8 * len(games),
                "outcome": "complete-reserve-preserved",
                "recent_history_receipts": len(games),
                "reserve_preserved": True,
                "reserve_remaining_seconds": 6000.0,
                "reserve_seconds": 6000.0,
                "selected_value_total": 0.5 * len(games),
                "sequence": 1000,
                "started_at_seconds": tournament_start,
                "total_actions_authorized": 2 * len(games),
                "total_resets_authorized": len(games),
            },
        },
        "worker_count": len(games),
    }


def test_launch_validator_accepts_real_one_based_governor_ordinals() -> None:
    games = ("governor-game-a", "governor-game-b")
    now = [100.0]
    governor = TournamentGovernor(
        FROZEN_COMPETITION_RUNTIME.governor_config(len(games)),
        clock=lambda: now[0],
    )
    governor.start_tournament(started_at_seconds=now[0])
    for game_id in games:
        governor.begin_game(game_id)
        now[0] += 0.1
        governor.finalize_game(game_id, reason=GovernorStopReason.AGENT_DONE)
    terminal = json.loads(json.dumps(asdict(governor.finalize_tournament())))
    launch = _launch_receipt(games)
    wrapper = cast(dict[str, Any], launch["tournament_receipt"])
    wrapper["receipt"] = terminal

    validated = build002_holdout._validate_launch_receipt(launch, games)

    rows = validated["games"]
    assert [row["game_ordinal"] for row in rows] == [1, 2]


def _game_rows(games: tuple[str, ...]) -> tuple[GameMeasurement, ...]:
    return tuple(
        GameMeasurement(
            game_id=game_id,
            completed=True,
            levels_completed=1,
            actions=2,
            resets=1,
            toolkit_score=0.25,
            wall_seconds=0.1,
            sampled_current_rss_max_bytes=1024,
            allocated_seconds=1.0,
            reserve_remaining_seconds=6000.0,
            stop_reason="win",
            primary_failure=None,
            levels=(
                LevelMeasurement(
                    level_index=1,
                    completed=True,
                    toolkit_score=0.25,
                    agent_actions=2,
                    human_baseline_actions=1,
                ),
            ),
        )
        for game_id in games
    )


def test_measurement_models_enforce_pinned_level_and_game_caps_and_recompute() -> None:
    level = LevelMeasurement(
        level_index=1,
        completed=True,
        toolkit_score=1.15,
        agent_actions=1,
        human_baseline_actions=2,
    )
    game = GameMeasurement(
        game_id="fixture-capped-game",
        completed=True,
        levels_completed=1,
        actions=1,
        resets=0,
        toolkit_score=1.0,
        wall_seconds=0.1,
        sampled_current_rss_max_bytes=1024,
        allocated_seconds=1.0,
        reserve_remaining_seconds=6000.0,
        stop_reason="win",
        primary_failure=None,
        levels=(level,),
    )

    assert level.to_dict()["pinned_toolkit_recomputed_score"] == 1.15
    assert game.to_dict()["pinned_toolkit_recomputed_score"] == 1.0

    with pytest.raises(ValueError, match="public-toolkit range"):
        LevelMeasurement(
            level_index=1,
            completed=True,
            toolkit_score=1.150001,
            agent_actions=1,
            human_baseline_actions=2,
        )
    with pytest.raises(ValueError, match="public-toolkit cap"):
        GameMeasurement(
            game_id="fixture-over-cap-game",
            completed=True,
            levels_completed=1,
            actions=1,
            resets=0,
            toolkit_score=1.000001,
            wall_seconds=0.1,
            sampled_current_rss_max_bytes=1024,
            allocated_seconds=1.0,
            reserve_remaining_seconds=6000.0,
            stop_reason="win",
            primary_failure=None,
            levels=(level,),
        )


def _result_artifacts(
    root: Path,
    state: Path,
    games: tuple[GameMeasurement, ...],
    launch_receipt: dict[str, Any],
    *,
    total_wall_seconds: float = 1.0,
    peak_memory_bytes: int = 2048,
    peak_memory_source: str = "linux-proc-status-rss-hwm",
) -> tuple[ArtifactBinding, ...]:
    artifact_root = state / "result-artifacts"
    artifact_root.mkdir(parents=True, exist_ok=True)
    launch_path = artifact_root / "competition-launch-receipt.json"
    atomic_write_json(
        launch_path,
        {
            "receipt": launch_receipt,
            "schema": "arc3.build-002.competition-launch-artifact.v0.1",
            "status": "PASS",
        },
    )
    scorecard_path = artifact_root / "local-scorecard.json"
    atomic_write_json(
        scorecard_path,
        {
            "completed_games": sum(game.completed for game in games),
            "completed_levels": sum(game.levels_completed for game in games),
            "games": [
                {
                    "actions": game.actions,
                    "completed": game.completed,
                    "game_id": game.game_id,
                    "levels": [
                        {
                            "agent_actions": level.agent_actions,
                            "completed": level.completed,
                            "human_baseline_actions": level.human_baseline_actions,
                            "level_index": level.level_index,
                            "toolkit_score": float(level.toolkit_score),
                        }
                        for level in game.levels
                    ],
                    "levels_completed": game.levels_completed,
                    "resets": game.resets,
                    "toolkit_score": float(game.toolkit_score),
                }
                for game in games
            ],
            "official": False,
            "schema": "arc3.build-002.local-scorecard.v0.1",
            "status": "PASS",
            "surface": "local-public",
            "total_actions": sum(game.actions for game in games),
            "total_resets": sum(game.resets for game in games),
            "total_score": sum(game.toolkit_score for game in games) / len(games),
        },
    )
    profile_path = artifact_root / "execution-profile.json"
    atomic_write_json(
        profile_path,
        {
            "games": [
                {
                    "game_id": game.game_id,
                    "sampled_current_rss_max_bytes": game.sampled_current_rss_max_bytes,
                    "wall_seconds": float(game.wall_seconds),
                }
                for game in games
            ],
            "peak_memory_bytes": peak_memory_bytes,
            "peak_memory_source": peak_memory_source,
            "per_game_memory_measurement": "sampled-current-rss-window-maximum-50ms",
            "schema": "arc3.build-002.execution-profile.v0.2",
            "status": "PASS",
            "total_wall_seconds": total_wall_seconds,
            "tournament_memory_measurement": "kernel-process-peak-rss-high-water-mark",
        },
    )
    failure_path = artifact_root / "failure-receipts.json"
    atomic_write_json(
        failure_path,
        {
            "games": [
                {
                    "game_id": game.game_id,
                    "primary_failure": (
                        game.primary_failure.value if game.primary_failure is not None else None
                    ),
                    "stop_reason": game.stop_reason,
                }
                for game in games
            ],
            "receipts": [
                {
                    "boundary": "fixture-terminal-analysis",
                    "classification": game.primary_failure.value,
                    "game_id": game.game_id,
                }
                for game in games
                if game.primary_failure is not None
            ],
            "schema": "arc3.build-002.failure-receipts.v0.1",
            "status": "PASS",
        },
    )
    runtime_receipts = state / "runtime" / "arc3-runtime-receipts"
    agent_state = state / "runtime" / "arc3-agent-state" / "fixture-controller"
    runtime_receipts.mkdir(parents=True, exist_ok=True)
    (agent_state / "trace").mkdir(parents=True, exist_ok=True)
    (agent_state / "checkpoints").mkdir(parents=True, exist_ok=True)
    (agent_state / "trace" / "events.jsonl").write_text(
        '{"event":"fixture"}\n', encoding="utf-8", newline="\n"
    )
    atomic_write_json(agent_state / "checkpoints" / "checkpoint-0001.json", {"fixture": True})
    atomic_write_json(
        runtime_receipts / "raw-local-scorecard.json",
        {
            "games": [
                {
                    **{
                        "actions": game.actions,
                        "completed": game.completed,
                        "game_id": game.game_id,
                        "levels": [
                            {
                                "agent_actions": level.agent_actions,
                                "completed": level.completed,
                                "human_baseline_actions": level.human_baseline_actions,
                                "level_index": level.level_index,
                                "toolkit_score": float(level.toolkit_score),
                            }
                            for level in game.levels
                        ],
                        "levels_completed": game.levels_completed,
                        "resets": game.resets,
                        "toolkit_score": float(game.toolkit_score),
                    },
                    "state": "WIN" if game.completed else "NOT_FINISHED",
                }
                for game in games
            ],
            "scorer_identity": build002_holdout.pinned_toolkit_scorer_identity(),
            "schema": build002_holdout.RAW_RUNTIME_SCORECARD_SCHEMA,
            "status": "PASS",
            "surface": "local-public",
        },
    )
    tournament = cast(dict[str, Any], launch_receipt["tournament_receipt"])["receipt"]
    assert isinstance(tournament, dict)
    atomic_write_json(runtime_receipts / "tournament-final.json", tournament)
    atomic_write_json(
        runtime_receipts / "tournament-start.json",
        {
            "effective_ceiling_deadline_seconds": tournament["started_at_seconds"] + 32400.0,
            "expected_environments": tournament["expected_environments"],
            "maximum_resets_per_game": tournament["maximum_resets_per_game"],
            "maximum_total_actions": tournament["maximum_total_actions"],
            "maximum_total_resets": tournament["maximum_total_resets"],
            "playable_deadline_seconds": tournament["started_at_seconds"] + 26400.0,
            "sequence": 1,
            "started_at_seconds": tournament["started_at_seconds"],
        },
    )
    tournament_games = tournament["games"]
    assert isinstance(tournament_games, list)
    for ordinal, game_receipt in enumerate(tournament_games):
        assert isinstance(game_receipt, dict)
        atomic_write_json(runtime_receipts / f"game-{ordinal:02d}.json", game_receipt)
    runtime_manifest_path = artifact_root / "runtime-evidence-manifest.json"
    atomic_write_json(
        runtime_manifest_path,
        create_runtime_evidence_manifest(
            state,
            expected_games=tuple(game.game_id for game in games),
        ),
    )
    submission_path = artifact_root / "submission-parquet.parquet"
    table = pa.table(
        {
            "row_id": pa.array(
                [f"{index}_{game.game_id}" for index, game in enumerate(games)],
                type=pa.string(),
            ),
            "game_id": pa.array([game.game_id for game in games], type=pa.string()),
            "end_of_game": pa.array([True] * len(games), type=pa.bool_()),
            "score": pa.array([game.toolkit_score for game in games], type=pa.float64()),
        }
    )
    pq.write_table(
        table,
        submission_path,
        compression="NONE",
        use_dictionary=False,
        write_statistics=False,
        version="2.6",
    )
    paths = {
        "competition-launch-receipt": launch_path,
        "execution-profile": profile_path,
        "failure-receipts": failure_path,
        "local-scorecard": scorecard_path,
        "runtime-evidence-manifest": runtime_manifest_path,
        "submission-parquet": submission_path,
    }
    rows = [ArtifactBinding(role, paths[role]) for role in RESULT_ARTIFACT_ROLES]
    assert all(path.path.is_relative_to(root) for path in rows)
    return tuple(rows)


def test_static_inventory_requires_exact_ten_game_identity(tmp_path: Path) -> None:
    manifest = PublicPartitionManifest.load(MANIFEST)
    games = tuple(sorted(entry.game_id for entry in manifest.games("public-holdout")))
    assets: dict[str, Path] = {}
    for game_id in games:
        path = tmp_path / game_id
        path.write_bytes(game_id.encode())
        assets[game_id] = path

    receipt = create_static_asset_inventory(MANIFEST, assets)

    assert receipt["status"] == "PASS"
    assert receipt["game_count"] == 10
    assert receipt["environment_make_interactions"] == 0
    with pytest.raises(EvaluationError, match="differs from the exact ten-game holdout"):
        create_static_asset_inventory(MANIFEST, dict(list(assets.items())[:-1]))


def test_make_before_scorecard_open_does_not_consume_authority(tmp_path: Path) -> None:
    _, state, _, games, seal = _arm(tmp_path)

    with pytest.raises(EvaluationError, match="preceded the durable scorecard open intent"):
        seal.before_environment_make("wrong-game", 0)

    assert seal.consumed is False
    assert not (state / "holdout-consumed.json").exists()
    assert games


def test_alternate_state_root_cannot_bypass_one_shot_identity(tmp_path: Path) -> None:
    root, _, preflight_path, _, _ = _arm(tmp_path)

    with pytest.raises(EvaluationError, match="state root is not canonical"):
        OneShotHoldoutSeal.arm(
            root,
            state_root=root / "alternate-state",
            preflight_path=preflight_path,
        )


def test_consumption_is_fsynced_before_scorecard_open_and_prevents_rerun(tmp_path: Path) -> None:
    root, state, preflight_path, games, seal = _arm(tmp_path)
    upstream_called = False

    def simulated_instrumented_make() -> None:
        nonlocal upstream_called
        seal.before_scorecard_open()
        seal.before_environment_make(games[0], 0)
        marker = json.loads((state / "holdout-consumed.json").read_text(encoding="utf-8"))
        assert marker["status"] == "INTENTIONALLY_CONSUMED"
        assert marker["consumption_boundary"] == "scorecard.open_intent"
        assert marker["scorecard_open_intent_count"] == 1
        assert marker["environment_make_interactions"] == 0
        assert (state / "exposure.jsonl").is_file()
        upstream_called = True

    simulated_instrumented_make()

    assert upstream_called is True
    with pytest.raises(EvaluationError, match="already consumed"):
        OneShotHoldoutSeal.arm(root, state_root=state, preflight_path=preflight_path)


def test_process_lock_prevents_concurrent_arm_and_can_release_before_consumption(
    tmp_path: Path,
) -> None:
    root, state, preflight_path, _, first = _arm(tmp_path)

    with pytest.raises(EvaluationError, match=r"active|recovery"):
        OneShotHoldoutSeal.arm(root, state_root=state, preflight_path=preflight_path)

    first.release_unconsumed()
    second = OneShotHoldoutSeal.arm(root, state_root=state, preflight_path=preflight_path)
    assert second.consumed is False
    second.release_unconsumed()
    assert not (state / "run.lock").exists()


def test_execute_after_consumption_reports_closed_authority_without_launch(
    tmp_path: Path,
) -> None:
    root, state, _, _, seal = _arm(tmp_path)
    seal.before_scorecard_open()
    launched = False

    def forbidden_launch(*_args: object, **_kwargs: object) -> Any:
        nonlocal launched
        launched = True
        raise AssertionError("consumed authority reached the launcher")

    outcome = runner.execute(root, root / "run-plan.json", launcher=forbidden_launch)

    assert outcome.status == "BLOCKED_AUTHORITY"
    assert outcome.receipt["rerun_authorized"] is False
    assert outcome.receipt["environment_make_interactions"] == 0
    assert launched is False
    assert (state / "holdout-consumed.json").is_file()


def test_pre_make_launch_failure_releases_lock_and_preserves_authority(tmp_path: Path) -> None:
    root, state, _, _, _ = _arm(tmp_path)
    # Simulate a fresh process after fixture setup without crossing make.
    (state / "run.lock").unlink()

    def unavailable_surface(*_args: object, **_kwargs: object) -> Any:
        raise ConnectionError("fixture gateway unavailable")

    outcome = runner.execute(root, root / "run-plan.json", launcher=unavailable_surface)

    assert outcome.status == "BLOCKED_EXTERNAL"
    assert outcome.receipt["environment_make_interactions"] == 0
    assert outcome.receipt["rerun_authorized"] is True
    assert not (state / "run.lock").exists()
    assert not (state / "holdout-consumed.json").exists()


def test_complete_result_seals_and_independently_validates(tmp_path: Path) -> None:
    root, state, preflight_path, games, seal = _arm(tmp_path)
    seal.before_scorecard_open()
    for ordinal, game_id in enumerate(games):
        seal.before_environment_make(game_id, ordinal)
    measured = _game_rows(games)
    launch = _launch_receipt(games)

    result = seal.seal_terminal_result(
        status="PASS",
        games=measured,
        launch_receipt=launch,
        total_wall_seconds=1.0,
        peak_memory_bytes=2048,
        peak_memory_source="linux-proc-status-rss-hwm",
        result_artifacts=_result_artifacts(root, state, measured, launch),
    )
    verified = validate_terminal_result(
        root,
        state_root=state,
        preflight_path=preflight_path,
    )

    assert result == verified
    assert result["evidence_label"] == "local-public-source-preview-exposed"
    assert result["official_rhae"] is None
    assert result["scores"]["local_toolkit_total"] == 0.25
    assert result["scores"]["documented_formula_rhae"] == 0.25
    assert result["failure_classification_counts"] == {
        classification.value: 0 for classification in FailureClassification
    }


def test_terminal_validation_recomputes_every_runtime_manifest_row(tmp_path: Path) -> None:
    root, state, preflight_path, games, seal = _arm(tmp_path)
    seal.before_scorecard_open()
    for ordinal, game_id in enumerate(games):
        seal.before_environment_make(game_id, ordinal)
    measured = _game_rows(games)
    launch = _launch_receipt(games)
    seal.seal_terminal_result(
        status="PASS",
        games=measured,
        launch_receipt=launch,
        total_wall_seconds=1.0,
        peak_memory_bytes=2048,
        peak_memory_source="linux-proc-status-rss-hwm",
        result_artifacts=_result_artifacts(root, state, measured, launch),
    )

    unmanifested = state / "runtime" / "arc3-agent-state" / "late-file.json"
    atomic_write_json(unmanifested, {"late": True})

    with pytest.raises(EvaluationError, match="runtime evidence manifest does not recompute"):
        validate_terminal_result(root, state_root=state, preflight_path=preflight_path)


def test_runtime_manifest_requires_raw_and_tournament_receipts(tmp_path: Path) -> None:
    root, state, _, games, _ = _arm(tmp_path)
    measured = _game_rows(games)
    launch = _launch_receipt(games)
    _result_artifacts(root, state, measured, launch)
    manifest = create_runtime_evidence_manifest(state, expected_games=games)
    paths = {row["path"] for row in manifest["files"]}
    assert "runtime/arc3-agent-state/fixture-controller/trace/events.jsonl" in paths
    assert "runtime/arc3-agent-state/fixture-controller/checkpoints/checkpoint-0001.json" in paths
    assert "runtime/arc3-runtime-receipts/raw-local-scorecard.json" in paths
    (state / "runtime" / "arc3-runtime-receipts" / "tournament-start.json").unlink()

    with pytest.raises(EvaluationError, match="missing required raw/tournament receipts"):
        create_runtime_evidence_manifest(state, expected_games=games)


@pytest.mark.parametrize(
    "forged_role",
    (
        "competition-launch-receipt",
        "execution-profile",
        "failure-receipts",
        "local-scorecard",
        "runtime-evidence-manifest",
        "submission-parquet",
    ),
)
def test_result_seal_rejects_forged_semantic_artifact(tmp_path: Path, forged_role: str) -> None:
    root, state, _, game_ids, seal = _arm(tmp_path)
    seal.before_scorecard_open()
    for ordinal, game_id in enumerate(game_ids):
        seal.before_environment_make(game_id, ordinal)
    measured = _game_rows(game_ids)
    launch = _launch_receipt(game_ids)
    artifacts = _result_artifacts(root, state, measured, launch)
    path = next(binding.path for binding in artifacts if binding.role == forged_role)
    if forged_role == "submission-parquet":
        table = pq.read_table(path)
        rows = table.to_pylist()
        rows[0]["score"] = 0.5
        pq.write_table(
            pa.Table.from_pylist(rows, schema=table.schema),
            path,
            compression="NONE",
            use_dictionary=False,
            write_statistics=False,
            version="2.6",
        )
    else:
        value = json.loads(path.read_text(encoding="utf-8"))
        if forged_role == "competition-launch-receipt":
            value["receipt"]["make_count"] = 9
        elif forged_role == "execution-profile":
            value["total_wall_seconds"] = 2.0
        elif forged_role == "failure-receipts":
            value["games"][0]["stop_reason"] = "forged"
        elif forged_role == "runtime-evidence-manifest":
            value["files"][0]["byte_length"] += 1
        else:
            value["total_actions"] = 999
        atomic_write_json(path, value)

    with pytest.raises(EvaluationError):
        seal.seal_terminal_result(
            status="PASS",
            games=measured,
            launch_receipt=launch,
            total_wall_seconds=1.0,
            peak_memory_bytes=2048,
            peak_memory_source="linux-proc-status-rss-hwm",
            result_artifacts=artifacts,
        )
    assert not (state / "result.json").exists()


def test_result_requires_exact_governor_action_accounting(tmp_path: Path) -> None:
    root, state, _, game_ids, seal = _arm(tmp_path)
    seal.before_scorecard_open()
    for ordinal, game_id in enumerate(game_ids):
        seal.before_environment_make(game_id, ordinal)
    measured = _game_rows(game_ids)
    launch = _launch_receipt(game_ids)
    del launch["tournament_receipt"]["receipt"]["games"][0]["actions_authorized"]

    with pytest.raises(EvaluationError, match=r"field set|action accounting"):
        seal.seal_terminal_result(
            status="PASS",
            games=measured,
            launch_receipt=launch,
            total_wall_seconds=1.0,
            peak_memory_bytes=2048,
            peak_memory_source="linux-proc-status-rss-hwm",
            result_artifacts=_result_artifacts(root, state, measured, launch),
        )
    assert not (state / "result.json").exists()


def test_terminal_pass_rejects_a_late_failure_receipt(tmp_path: Path) -> None:
    root, state, _, game_ids, seal = _arm(tmp_path)
    seal.before_scorecard_open()
    for ordinal, game_id in enumerate(game_ids):
        seal.before_environment_make(game_id, ordinal)
    measured = _game_rows(game_ids)
    launch = _launch_receipt(game_ids)
    artifacts = _result_artifacts(root, state, measured, launch)
    failures_path = next(
        binding.path for binding in artifacts if binding.role == "failure-receipts"
    )
    failures = json.loads(failures_path.read_text(encoding="utf-8"))
    failures["receipts"].append(
        {
            "boundary": "resource-budget-after-final-checkpoint",
            "classification": "budget exhaustion",
            "game_id": game_ids[0],
        }
    )
    atomic_write_json(failures_path, failures)

    with pytest.raises(EvaluationError, match="terminal status disagrees"):
        seal.seal_terminal_result(
            status="PASS",
            games=measured,
            launch_receipt=launch,
            total_wall_seconds=1.0,
            peak_memory_bytes=2048,
            peak_memory_source="linux-proc-status-rss-hwm",
            result_artifacts=artifacts,
        )
    assert not (state / "result.json").exists()


def test_consumed_framework_failure_is_sealed_without_retry_or_score(tmp_path: Path) -> None:
    root, state, preflight_path, games, seal = _arm(tmp_path)
    seal.before_scorecard_open()
    seal.before_environment_make(games[0], 0)

    failure = seal.seal_consumed_failure(
        classification=FailureClassification.PLATFORM,
        boundary="fixture-framework",
        error=RuntimeError("fixture fault"),
    )
    verified = validate_consumed_failure(
        root,
        state_root=state,
        preflight_path=preflight_path,
    )

    assert verified == failure
    assert failure["make_intent_count"] == 1
    assert failure["missing_games"] == list(games[1:])
    assert failure["official_rhae"] is None
    assert failure["rerun_authorized"] is False


def test_scorecard_open_failure_consumes_authority_without_make_interaction(
    tmp_path: Path,
) -> None:
    root, state, preflight_path, games, seal = _arm(tmp_path)
    seal.before_scorecard_open()

    failure = seal.seal_consumed_failure(
        classification=FailureClassification.PLATFORM,
        boundary="scorecard-open",
        error=RuntimeError("fixture open failure"),
    )
    verified = validate_consumed_failure(
        root,
        state_root=state,
        preflight_path=preflight_path,
    )

    assert verified == failure
    assert failure["make_intent_count"] == 0
    assert failure["missing_games"] == list(games)
    assert failure["consumption"]["environment_make_interactions"] == 0
    assert failure["consumption"]["consumption_boundary"] == "scorecard.open_intent"
    with pytest.raises(EvaluationError, match="already consumed"):
        OneShotHoldoutSeal.arm(root, state_root=state, preflight_path=preflight_path)


def test_consumption_marker_without_exposure_append_still_seals(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, state, preflight_path, games, seal = _arm(tmp_path)

    def fail_append(path: Path, payload: dict[str, Any]) -> None:
        del path, payload
        raise OSError("fixture append failure")

    monkeypatch.setattr(build002_holdout, "_append_fsynced", fail_append)
    seal.before_scorecard_open()
    with pytest.raises(OSError, match="fixture append failure"):
        seal.before_environment_make(games[0], 0)

    assert seal.consumed is True
    assert (state / "holdout-consumed.json").is_file()
    assert not (state / "exposure.jsonl").exists()
    failure = seal.seal_consumed_failure(
        classification=FailureClassification.PLATFORM,
        boundary="exposure-ledger-append",
        error=OSError("fixture append failure"),
    )
    verified = validate_consumed_failure(
        root,
        state_root=state,
        preflight_path=preflight_path,
    )
    assert verified == failure
    assert failure["make_intent_count"] == 0
    assert failure["missing_games"] == list(games)


def test_durable_exposure_append_is_recovered_after_in_memory_update_crash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, state, preflight_path, games, seal = _arm(tmp_path)
    append = build002_holdout._append_fsynced

    def append_then_crash(path: Path, payload: dict[str, Any]) -> None:
        append(path, payload)
        raise OSError("fixture crash after durable append")

    monkeypatch.setattr(build002_holdout, "_append_fsynced", append_then_crash)
    seal.before_scorecard_open()
    with pytest.raises(OSError, match="after durable append"):
        seal.before_environment_make(games[0], 0)

    failure = seal.seal_consumed_failure(
        classification=FailureClassification.PLATFORM,
        boundary="post-exposure-append",
        error=OSError("fixture crash after durable append"),
    )
    verified = validate_consumed_failure(
        root,
        state_root=state,
        preflight_path=preflight_path,
    )
    assert verified == failure
    assert failure["make_intent_count"] == 1
    assert failure["make_intents"] == [games[0]]
    assert failure["missing_games"] == list(games[1:])


def test_terminal_result_tampering_is_rejected(tmp_path: Path) -> None:
    root, state, preflight_path, games, seal = _arm(tmp_path)
    seal.before_scorecard_open()
    for ordinal, game_id in enumerate(games):
        seal.before_environment_make(game_id, ordinal)
    measured = _game_rows(games)
    launch = _launch_receipt(games)
    seal.seal_terminal_result(
        status="PASS",
        games=measured,
        launch_receipt=launch,
        total_wall_seconds=1.0,
        peak_memory_bytes=2048,
        peak_memory_source="linux-proc-status-rss-hwm",
        result_artifacts=_result_artifacts(root, state, measured, launch),
    )
    result_path = state / "result.json"
    result = json.loads(result_path.read_text(encoding="utf-8"))
    result["official_rhae"] = 1.0
    result_path.write_text(json.dumps(result), encoding="utf-8")

    with pytest.raises(EvaluationError, match="terminal result seal is invalid"):
        validate_terminal_result(root, state_root=state, preflight_path=preflight_path)


def test_incomplete_game_requires_exact_failure_taxonomy() -> None:
    with pytest.raises(ValueError, match="primary failure"):
        GameMeasurement(
            game_id="fixture-game",
            completed=False,
            levels_completed=0,
            actions=0,
            resets=0,
            toolkit_score=0.0,
            wall_seconds=0.0,
            sampled_current_rss_max_bytes=0,
            allocated_seconds=0.0,
            reserve_remaining_seconds=6000.0,
            stop_reason="failure",
            primary_failure=None,
            levels=(
                LevelMeasurement(
                    level_index=1,
                    completed=False,
                    toolkit_score=0.0,
                    agent_actions=None,
                    human_baseline_actions=None,
                ),
            ),
        )


def test_preflight_fails_closed_when_required_gate_regresses(tmp_path: Path) -> None:
    root, _, gates, artifacts = _prepared_root(tmp_path)
    gate_path = gates[0].path
    atomic_write_json(gate_path, {"schema": "fixture.gate.v1", "status": "FAIL"})
    _git(root, "add", ".")
    _git(
        root,
        "-c",
        "user.name=ARC3 Test",
        "-c",
        "user.email=arc3-test@example.invalid",
        "commit",
        "-q",
        "-m",
        "regressed gate fixture",
    )

    with pytest.raises(EvaluationError, match="gate is not PASS"):
        _create_fixture_preflight(root, gates, artifacts)


def test_preflight_rejects_forged_pass_schema_without_consumption(tmp_path: Path) -> None:
    root, _, gates, artifacts = _prepared_root(tmp_path)
    atomic_write_json(gates[0].path, {"schema": "fixture.gate.v1", "status": "PASS"})
    _git(root, "add", ".")
    _git(
        root,
        "-c",
        "user.name=ARC3 Test",
        "-c",
        "user.email=arc3-test@example.invalid",
        "commit",
        "-q",
        "-m",
        "forged PASS gate",
    )

    with pytest.raises(EvaluationError, match=r"unexpected fields|schema or status"):
        _create_fixture_preflight(root, gates, artifacts)
    assert not (root / CANONICAL_STATE_RELATIVE / "holdout-consumed.json").exists()


def test_preflight_rejects_false_semantic_check_without_consumption(tmp_path: Path) -> None:
    root, _, gates, artifacts = _prepared_root(tmp_path)
    gate_path = gates[0].path
    gate = json.loads(gate_path.read_text(encoding="utf-8"))
    first_check = next(iter(gate["checks"]))
    gate["checks"][first_check] = False
    atomic_write_json(gate_path, gate)
    _git(root, "add", ".")
    _git(
        root,
        "-c",
        "user.name=ARC3 Test",
        "-c",
        "user.email=arc3-test@example.invalid",
        "commit",
        "-q",
        "-m",
        "false semantic gate",
    )

    with pytest.raises(EvaluationError, match="semantic checks"):
        _create_fixture_preflight(root, gates, artifacts)
    assert not (root / CANONICAL_STATE_RELATIVE / "holdout-consumed.json").exists()


def test_preflight_rejects_hash_bound_but_invalid_artifact_without_consumption(
    tmp_path: Path,
) -> None:
    root, _, gates, artifacts = _prepared_root(tmp_path)
    notebook = next(binding.path for binding in artifacts if binding.role == "kaggle-notebook")
    atomic_write_json(notebook, {"forged": True})
    _write_gate_receipts(gates[0].path.parent, artifacts)
    _git(root, "add", ".")
    _git(
        root,
        "-c",
        "user.name=ARC3 Test",
        "-c",
        "user.email=arc3-test@example.invalid",
        "commit",
        "-q",
        "-m",
        "hash-bound invalid notebook",
    )

    with pytest.raises(EvaluationError, match="notebook contract"):
        _create_fixture_preflight(root, gates, artifacts)
    assert not (root / CANONICAL_STATE_RELATIVE / "holdout-consumed.json").exists()
