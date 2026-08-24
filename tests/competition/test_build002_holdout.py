"""Fail-closed tests for the Build 002 one-shot public-run boundary."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

import arc3.evaluation.build002_holdout as build002_holdout
from arc3.errors import EvaluationError
from arc3.evaluation.artifacts import atomic_write_json
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
    create_static_asset_inventory,
    validate_consumed_failure,
    validate_terminal_result,
)
from arc3.evaluation.public import PublicPartitionManifest

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
    "submission-parquet",
)


def _git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )


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

    gates: list[ReceiptBinding] = []
    for role in GATE_ROLES:
        path = evidence / f"{role}.json"
        atomic_write_json(path, {"schema": "fixture.gate.v1", "status": "PASS"})
        gates.append(ReceiptBinding(role, path))

    manifest = PublicPartitionManifest.load(manifest_path)
    games = tuple(sorted(entry.game_id for entry in manifest.games("public-holdout")))
    assets: dict[str, Path] = {}
    for game_id in games:
        path = assets_root / f"{game_id}.arc"
        path.write_bytes((game_id + "\n").encode())
        assets[game_id] = path
    inventory_path = payload / "holdout-assets.json"
    atomic_write_json(inventory_path, create_static_asset_inventory(manifest_path, assets))

    artifacts: list[ArtifactBinding] = []
    for role in ARTIFACT_ROLES:
        path = inventory_path if role == "holdout-asset-inventory" else payload / f"{role}.bin"
        if role == "source-preview-contamination-receipt":
            path = payload / f"{role}.json"
            atomic_write_json(
                path,
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
                        "future_public_run_evidence_label": ("local-public-source-preview-exposed"),
                    },
                },
            )
        elif role != "holdout-asset-inventory":
            path.write_bytes((role + "\n").encode())
        artifacts.append(ArtifactBinding(role, path))

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
    preflight = create_frozen_preflight(
        root,
        attempt_id=BUILD_002_ATTEMPT_ID,
        seed=0,
        manifest_path=root / "docs" / "evaluation" / MANIFEST.name,
        gates=gates,
        artifacts=artifacts,
    )
    atomic_write_json(preflight_path, preflight)
    seal = OneShotHoldoutSeal.arm(root, state_root=state, preflight_path=preflight_path)
    return root, state, preflight_path, games, seal


def _launch_receipt(games: tuple[str, ...]) -> dict[str, Any]:
    game_rows = [
        {
            "game_id": game_id,
            "allocated_seconds": 1.0,
            "reserve_remaining_seconds": 6000.0,
        }
        for game_id in games
    ]
    return {
        "all_environments_covered": True,
        "close_scorecard_count": 1,
        "discovered_environments": list(games),
        "game_count": len(games),
        "get_scorecard_during_flight_count": 0,
        "lifecycle_enforced": True,
        "make_count": len(games),
        "open_scorecard_count": 1,
        "tournament_configured": True,
        "tournament_finalized": True,
        "tournament_receipt": {
            "status": "PASS",
            "receipt": {
                "effective_ceiling_respected": True,
                "expected_environments": len(games),
                "finalized_environments": len(games),
                "games": game_rows,
                "reserve_preserved": True,
                "reserve_remaining_seconds": 6000.0,
            },
        },
    }


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
            peak_memory_bytes=1024,
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


def _result_artifacts(root: Path, state: Path) -> tuple[ArtifactBinding, ...]:
    artifact_root = state / "result-artifacts"
    artifact_root.mkdir(parents=True, exist_ok=True)
    rows: list[ArtifactBinding] = []
    for role in RESULT_ARTIFACT_ROLES:
        suffix = ".parquet" if role == "submission-parquet" else ".json"
        path = artifact_root / f"{role}{suffix}"
        path.write_bytes((role + "\n").encode())
        rows.append(ArtifactBinding(role, path))
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


def test_wrong_first_make_does_not_consume_authority(tmp_path: Path) -> None:
    _, state, _, games, seal = _arm(tmp_path)

    with pytest.raises(EvaluationError, match="order or identity changed"):
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


def test_consumption_is_fsynced_before_make_and_prevents_rerun(tmp_path: Path) -> None:
    root, state, preflight_path, games, seal = _arm(tmp_path)
    upstream_called = False

    def simulated_instrumented_make() -> None:
        nonlocal upstream_called
        seal.before_environment_make(games[0], 0)
        marker = json.loads((state / "holdout-consumed.json").read_text(encoding="utf-8"))
        assert marker["status"] == "INTENTIONALLY_CONSUMED"
        assert (state / "exposure.jsonl").is_file()
        upstream_called = True

    simulated_instrumented_make()

    assert upstream_called is True
    with pytest.raises(EvaluationError, match="already consumed"):
        OneShotHoldoutSeal.arm(root, state_root=state, preflight_path=preflight_path)


def test_complete_result_seals_and_independently_validates(tmp_path: Path) -> None:
    root, state, preflight_path, games, seal = _arm(tmp_path)
    for ordinal, game_id in enumerate(games):
        seal.before_environment_make(game_id, ordinal)

    result = seal.seal_terminal_result(
        status="PASS",
        games=_game_rows(games),
        launch_receipt=_launch_receipt(games),
        total_wall_seconds=1.0,
        peak_memory_bytes=2048,
        result_artifacts=_result_artifacts(root, state),
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


def test_consumed_framework_failure_is_sealed_without_retry_or_score(tmp_path: Path) -> None:
    root, state, preflight_path, games, seal = _arm(tmp_path)
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


def test_consumption_marker_without_exposure_append_still_seals(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, state, preflight_path, games, seal = _arm(tmp_path)

    def fail_append(path: Path, payload: dict[str, Any]) -> None:
        del path, payload
        raise OSError("fixture append failure")

    monkeypatch.setattr(build002_holdout, "_append_fsynced", fail_append)
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


def test_terminal_result_tampering_is_rejected(tmp_path: Path) -> None:
    root, state, preflight_path, games, seal = _arm(tmp_path)
    for ordinal, game_id in enumerate(games):
        seal.before_environment_make(game_id, ordinal)
    seal.seal_terminal_result(
        status="PASS",
        games=_game_rows(games),
        launch_receipt=_launch_receipt(games),
        total_wall_seconds=1.0,
        peak_memory_bytes=2048,
        result_artifacts=_result_artifacts(root, state),
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
            peak_memory_bytes=0,
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
        create_frozen_preflight(
            root,
            attempt_id=BUILD_002_ATTEMPT_ID,
            seed=0,
            manifest_path=root / "docs" / "evaluation" / MANIFEST.name,
            gates=gates,
            artifacts=artifacts,
        )
