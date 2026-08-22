"""Stage 15 manifest, exposure-gate, and artifact contract tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import pytest
from scripts.evaluate_public import build_parser

from arc3.adapters import EnvironmentDescriptor
from arc3.competition_runtime import FROZEN_COMPETITION_RUNTIME
from arc3.errors import EvaluationError
from arc3.evaluation.artifacts import (
    atomic_write_bytes,
    atomic_write_json,
    atomic_write_text,
    canonical_json_bytes,
    seal_object,
    sha256_file,
)
from arc3.evaluation.public import (
    PUBLIC_EVALUATION_SCHEMA,
    PUBLIC_RUN_SCHEMA,
    PublicEvaluationConfig,
    PublicExposureLedger,
    PublicPartitionManifest,
    _run_context,
    local_asset_identity,
    validate_frozen_source,
    validate_public_gate,
)
from arc3.evaluation.public_runner import _aggregate, verify_public_evaluation
from arc3.policy import RunContext
from arc3.types import GameId

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "docs" / "evaluation" / "public-game-partitions.v0.1.json"
FROZEN = "a" * 40


def test_frozen_manifest_recomputes_all_assignments_and_exposures() -> None:
    manifest = PublicPartitionManifest.load(MANIFEST)

    assert len(manifest.games("smoke")) == 3
    assert len(manifest.games("development")) == 12
    assert len(manifest.games("public-holdout")) == 10
    assert all(
        entry.exposure == "discovery-metadata-only" for entry in manifest.games("public-holdout")
    )
    assert sum(entry.original_partition is not None for entry in manifest.entries) == 1


def test_stage15_default_declaration_is_full_b0_through_b4() -> None:
    args = build_parser().parse_args([])

    assert args.game_ids is None
    assert args.agents == ("random", "cycle", "novelty", "trace", "full")
    assert args.seeds == (7, 11)
    assert args.max_actions == 80
    assert args.max_resets == 8
    assert args.timeout_seconds == 120.0
    config = PublicEvaluationConfig(
        partition="development",
        agents=("full",),
        seeds=(7,),
        frozen_commit=FROZEN,
    )
    assert config.max_actions == FROZEN_COMPETITION_RUNTIME.max_actions == 80
    assert config.max_resets == FROZEN_COMPETITION_RUNTIME.max_resets == 8
    assert config.timeout_seconds == 120.0
    assert FROZEN_COMPETITION_RUNTIME.per_game_wall_clock_seconds == 240.0


def test_public_evaluation_selector_is_partition_bound_and_holdout_closed() -> None:
    manifest = PublicPartitionManifest.load(MANIFEST)
    development_ids = tuple(entry.game_id for entry in manifest.games("development")[:2])
    args = build_parser().parse_args(
        ["--partition", "development", "--game-ids", ",".join(development_ids)]
    )
    config = PublicEvaluationConfig(
        partition=args.partition,
        game_ids=args.game_ids,
        agents=("full",),
        seeds=(7,),
        frozen_commit=FROZEN,
    )

    assert tuple(entry.game_id for entry in config.selected_games(manifest)) == development_ids
    assert config.declaration()["game_ids"] == list(development_ids)
    with pytest.raises(EvaluationError, match="outside partition"):
        PublicEvaluationConfig(
            partition="development",
            game_ids=(manifest.games("public-holdout")[0].game_id,),
            agents=("full",),
            seeds=(7,),
            frozen_commit=FROZEN,
        ).selected_games(manifest)
    with pytest.raises(ValueError, match="cannot select a subset"):
        PublicEvaluationConfig(
            partition="public-holdout",
            game_ids=(manifest.games("public-holdout")[0].game_id,),
            agents=("full",),
            seeds=(7,),
            frozen_commit=FROZEN,
        )


def test_stage15_context_uses_frozen_controller_bounds_with_surface_wall_override(
    tmp_path: Path,
) -> None:
    context = cast(
        RunContext,
        _run_context(
            {
                "checkpoint_path": str(tmp_path / "checkpoint"),
                "game_id": "opaque-stage15-fixture",
                "git_commit": FROZEN,
                "max_actions": 80,
                "max_resets": 8,
                "run_id": "stage15-runtime-bounds",
                "seed": 7,
                "timeout_seconds": 120.0,
                "trace_path": str(tmp_path / "trace"),
            }
        ),
    )
    budgets = context.config.budgets
    assert budgets.max_actions == FROZEN_COMPETITION_RUNTIME.max_actions
    assert budgets.max_resets == FROZEN_COMPETITION_RUNTIME.max_resets
    assert budgets.decision_seconds == FROZEN_COMPETITION_RUNTIME.decision_seconds
    assert budgets.wall_clock_seconds == 120.0
    assert budgets.memory_megabytes == FROZEN_COMPETITION_RUNTIME.memory_megabytes
    assert budgets.max_search_nodes == FROZEN_COMPETITION_RUNTIME.max_search_nodes


def test_manifest_tamper_and_discovery_drift_are_rejected(tmp_path: Path) -> None:
    raw = json.loads(MANIFEST.read_text(encoding="utf-8"))
    raw["games"][0]["assignment_hash"] = "0" * 64
    tampered = tmp_path / "partitions.json"
    tampered.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(EvaluationError, match="assignment hash mismatch"):
        PublicPartitionManifest.load(tampered)

    manifest = PublicPartitionManifest.load(MANIFEST)
    descriptors = tuple(
        EnvironmentDescriptor(game_id=GameId(entry.game_id)) for entry in manifest.entries[:-1]
    )
    comparison = manifest.compare_discovery(descriptors)
    assert comparison["status"] == "MISMATCH"
    assert comparison["gameplay_observed"] is False
    assert comparison["missing_game_ids"] == [manifest.entries[-1].game_id]


def test_local_asset_identity_hashes_without_parsing_source(tmp_path: Path) -> None:
    manifest = PublicPartitionManifest.load(MANIFEST)
    entry = manifest.games("smoke")[0]
    version = entry.game_id.split("-", 1)[1]
    directory = tmp_path / entry.stable_name / version
    directory.mkdir(parents=True)
    (directory / "metadata.json").write_text(
        json.dumps({"game_id": entry.game_id}), encoding="utf-8"
    )
    (directory / f"{entry.stable_name}.py").write_text("SENTINEL = 1\n", encoding="utf-8")

    identity = local_asset_identity(tmp_path, entry)

    assert identity is not None
    assert identity.game_id == entry.game_id
    assert {name for name, _length, _digest in identity.files} == {
        "metadata.json",
        f"{entry.stable_name}.py",
    }
    assert identity.to_dict()["source_semantically_inspected"] is False


def test_exposure_ledger_detects_tampering(tmp_path: Path) -> None:
    ledger = PublicExposureLedger(tmp_path / "exposure.jsonl")
    first = ledger.append("metadata.discovered", {"game_id": "fixture-v1"})
    second = ledger.append("game.evaluation_started", {"game_id": "fixture-v1"})

    assert second["previous_event_hash"] == first["event_hash"]
    assert len(ledger.events()) == 2

    lines = ledger.path.read_text(encoding="utf-8").splitlines()
    event = json.loads(lines[0])
    event["payload"]["game_id"] = "mutated-v1"
    lines[0] = json.dumps(event, sort_keys=True, separators=(",", ":"))
    ledger.path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    with pytest.raises(EvaluationError, match="hash mismatch"):
        ledger.events()


def _git_stub(*arguments: str) -> str:
    return FROZEN if arguments[0] == "rev-parse" else ""


def test_public_gate_requires_clean_frozen_source(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("arc3.evaluation.public._git_value", _git_stub)
    assert validate_frozen_source(FROZEN) == {
        "git_commit": FROZEN,
        "dirty_worktree": False,
    }

    monkeypatch.setattr(
        "arc3.evaluation.public._git_value",
        lambda *arguments: FROZEN if arguments[0] == "rev-parse" else " M policy.py",
    )
    with pytest.raises(EvaluationError, match="clean frozen worktree"):
        validate_frozen_source(FROZEN)


def test_holdout_gate_is_closed_and_then_one_shot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("arc3.evaluation.public._git_value", _git_stub)
    monkeypatch.setattr("arc3.evaluation.public._repository_root", lambda: tmp_path)
    manifest = PublicPartitionManifest.load(MANIFEST)
    output_root = tmp_path / "artifacts" / "stage15" / "evaluations"
    ledger_path = tmp_path / "artifacts" / "stage15" / "public-exposure.jsonl"
    ledger = PublicExposureLedger(ledger_path)
    closed = PublicEvaluationConfig(
        partition="public-holdout",
        agents=("full",),
        seeds=(7,),
        frozen_commit=FROZEN,
    )
    with pytest.raises(EvaluationError, match="holdout is closed"):
        validate_public_gate(closed, manifest, ledger)

    development = tmp_path / "development-manifest.json"
    declaration = {
        "agents": ["full"],
        "seeds": [7],
        "max_actions": 80,
        "max_resets": 8,
        "timeout_seconds": 120.0,
    }
    atomic_write_json(
        development,
        seal_object(
            {
                "schema": PUBLIC_EVALUATION_SCHEMA,
                "partition": "development",
                "status": "PASS",
                "surface": "local-public",
                "git_commit": FROZEN,
                "public_partition_manifest_hash": manifest.digest,
                "agent_config": declaration,
            },
            hash_field="manifest_hash",
        ),
    )
    monkeypatch.setattr(
        "arc3.evaluation.public_runner.verify_public_evaluation",
        lambda _directory: {"verified": True},
    )
    opened = PublicEvaluationConfig(
        partition="public-holdout",
        agents=("full",),
        seeds=(7,),
        frozen_commit=FROZEN,
        evaluation_id="holdout-fixture-v1",
        output_root=output_root,
        exposure_ledger=ledger_path,
        allow_public_holdout=True,
        sealed_development_manifest=development,
    )
    validate_public_gate(opened, manifest, ledger)
    ledger.append(
        "game.evaluation_started",
        {
            "game_id": manifest.games("public-holdout")[0].game_id,
            "evaluation_id": "holdout-fixture-v1",
        },
    )
    with pytest.raises(EvaluationError, match="already been consumed"):
        validate_public_gate(opened, manifest, ledger)
    validate_public_gate(
        opened,
        manifest,
        ledger,
        resume_evaluation_id="holdout-fixture-v1",
    )


def _minimal_run(specification: dict[str, object], identity_hash: str) -> dict[str, Any]:
    return seal_object(
        {
            "schema": PUBLIC_RUN_SCHEMA,
            "evaluation_id": specification["evaluation_id"],
            "run_id": specification["run_id"],
            "run_spec_hash": specification["run_spec_hash"],
            "game_id": specification["game_id"],
            "baseline_id": "B1",
            "agent": "cycle",
            "seed": 7,
            "surface": specification["surface"],
            "partition": "smoke",
            "status": "success",
            "identity_hash": identity_hash,
            "score": {
                "verified": True,
                "official_run_game_id": specification["game_id"],
                "score": 0.0,
                "levels_completed": 0,
                "completed": False,
            },
            "metrics": {
                "environment_actions": 1,
                "resets": 0,
                "fault_count": 0,
            },
            "trace": {"replay_verified": True},
            "asset_identity_after": None,
            "environment_transport": specification["network_mode"],
            "failure": None,
        },
        hash_field="receipt_hash",
    )


def test_public_artifact_verifier_detects_mutation(tmp_path: Path) -> None:
    evaluation = tmp_path / "evaluation"
    runs = evaluation / "runs"
    runs.mkdir(parents=True)
    identity_hash = "sha256:" + "1" * 64
    specification: dict[str, object] = {
        "evaluation_id": "public-fixture",
        "run_id": "fixture-B1-cycle-seed-7",
        "game_id": "fixture-v1",
        "partition": "smoke",
        "surface": "local-public",
        "network_mode": "offline-evaluation",
        "baseline_id": "B1",
        "agent": "cycle",
        "seed": 7,
        "identity_hash": identity_hash,
    }
    specification["run_spec_hash"] = seal_object(specification, hash_field="run_spec_hash")[
        "run_spec_hash"
    ]
    run = _minimal_run(specification, identity_hash)
    atomic_write_json(runs / f"{specification['run_id']}.json", run)
    atomic_write_bytes(evaluation / "results.jsonl", canonical_json_bytes(run))
    summary = _aggregate([run], partition="smoke")
    summary.update(
        {
            "evaluation_id": "public-fixture",
            "surface": "local-public",
            "partition": "smoke",
        }
    )
    atomic_write_json(evaluation / "summary.json", summary)
    atomic_write_text(evaluation / "report.md", "fixture\n")
    atomic_write_json(evaluation / "reproduce.json", {"argv": []})
    atomic_write_text(evaluation / "reproduce.txt", "fixture\n")
    hashes = {
        path.relative_to(evaluation).as_posix(): sha256_file(path)
        for path in evaluation.rglob("*")
        if path.is_file()
    }
    atomic_write_json(
        evaluation / "manifest.json",
        seal_object(
            {
                "schema": PUBLIC_EVALUATION_SCHEMA,
                "evaluation_id": "public-fixture",
                "status": "PASS",
                "surface": "local-public",
                "partition": "smoke",
                "identity_hash": identity_hash,
                "expected_runs": [specification],
                "required_artifacts": sorted(hashes),
                "artifact_hashes": hashes,
            },
            hash_field="manifest_hash",
        ),
    )

    assert verify_public_evaluation(evaluation)["verified"] is True
    atomic_write_bytes(evaluation / "results.jsonl", b"{}\n")
    verification = verify_public_evaluation(evaluation)
    assert verification["verified"] is False
    assert any("results.jsonl" in error for error in verification["errors"])


def test_zero_progress_never_becomes_an_efficiency_improvement() -> None:
    results: list[dict[str, Any]] = []
    for agent, baseline_id, actions in (("random", "B0", 80), ("full", "B4", 1)):
        results.append(
            {
                "agent": agent,
                "baseline_id": baseline_id,
                "status": "success",
                "score": {"score": 0.0, "levels_completed": 0, "completed": False},
                "metrics": {
                    "environment_actions": actions,
                    "resets": 0,
                    "fault_count": 0,
                },
            }
        )

    summary = _aggregate(results, partition="development")

    assert summary["status"] == "PASS"
    assert summary["claim"] == "MECHANISM_NOT_OBSERVED"
