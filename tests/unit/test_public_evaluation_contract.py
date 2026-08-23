"""Stage 15 manifest, exposure-gate, and artifact contract tests."""

from __future__ import annotations

import json
import socket
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from scripts.evaluate_public import build_parser

from arc3.adapters import (
    EnvironmentDescriptor,
    GridFrame,
    Observation,
    ScoreRunSummary,
    ScoreSummary,
)
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
from arc3.evaluation.baselines import make_evaluation_policy
from arc3.evaluation.public import (
    PUBLIC_EVALUATION_SCHEMA,
    PUBLIC_RUN_SCHEMA,
    PublicEvaluationConfig,
    PublicExposureLedger,
    PublicGameEntry,
    PublicPartitionManifest,
    _run_context,
    local_asset_identity,
    run_public_episode,
    validate_frozen_source,
    validate_public_gate,
)
from arc3.evaluation.public_runner import (
    _aggregate,
    _asset_identity_check,
    _failure_result,
    _hot_path_profile_valid,
    _legacy_aggregate,
    _OfflineSocketGuard,
    _receipt_valid,
    _render_report,
    _reproduction_argv,
    _worker,
    verify_public_evaluation,
)
from arc3.policy import ControllerPreset, RunContext, preset_features
from arc3.profiling.hot_path import HotPathProfiler
from arc3.trace import BaselineTraceSink, CodeIdentity, EventJournal, SourceIdentity
from arc3.types import (
    ActionName,
    ActionRequest,
    EvaluationSurface,
    GameId,
    GameStateName,
    JSONValue,
)

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "docs" / "evaluation" / "public-game-partitions.v0.1.json"
FROZEN = "a" * 40


def test_pre_action_authority_drift_blocks_the_next_environment_step() -> None:
    """Every step/RESET gets a fresh fail-closed authorization callback."""

    def observation(value: int) -> Observation:
        return Observation(
            game_id=GameId("opaque-per-action-fixture"),
            frames=(GridFrame(((value,),)),),
            state=GameStateName.NOT_FINISHED,
            levels_completed=0,
            win_levels=1,
            available_actions=(ActionName.ACTION1, ActionName.RESET),
        )

    class Session:
        def __init__(self) -> None:
            self._observation = observation(0)
            self.steps = 0

        @property
        def observation(self) -> Observation:
            return self._observation

        def step(
            self,
            action: ActionRequest,
            *,
            reasoning: Mapping[str, JSONValue] | None = None,
        ) -> Observation:
            assert reasoning is not None
            self.steps += 1
            self._observation = observation(self.steps)
            return self._observation

        def close(self) -> None:
            return None

    class Policy:
        manages_trace = False

        def select(self, _current: Observation) -> ActionRequest:
            return ActionRequest(ActionName.ACTION1)

        def accept_consequence(self, _returned: Observation) -> None:
            return None

    session = Session()
    checks = 0

    def authorize() -> None:
        nonlocal checks
        checks += 1
        if checks == 2:
            raise EvaluationError("injected mid-episode authority drift")

    with pytest.raises(EvaluationError, match="mid-episode authority drift"):
        run_public_episode(
            cast(Any, session),
            cast(Any, Policy()),
            max_actions=3,
            max_resets=1,
            pre_action_authorization=authorize,
        )
    assert checks == 2
    assert session.steps == 1


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
    assert args.hot_path_profile is False
    assert args.python_allocation_tracing is True
    assert args.automatic_checkpointing is True
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
    assert config.declaration()["python_allocation_tracing"] is True
    assert config.declaration()["automatic_checkpointing"] is True
    assert FROZEN_COMPETITION_RUNTIME.per_game_wall_clock_seconds == 240.0


def test_stage03_diagnostic_switches_are_explicit_and_tightly_guarded() -> None:
    args = build_parser().parse_args(
        ["--no-python-allocation-tracing", "--no-automatic-checkpointing"]
    )
    assert args.python_allocation_tracing is False
    assert args.automatic_checkpointing is False

    with pytest.raises(ValueError, match="require hot-path profiling"):
        PublicEvaluationConfig(
            partition="development",
            python_allocation_tracing=False,
            agents=("full",),
            seeds=(7,),
            frozen_commit=FROZEN,
        )
    with pytest.raises(ValueError, match="FULL policy only"):
        PublicEvaluationConfig(
            partition="development",
            hot_path_profile=True,
            automatic_checkpointing=False,
            agents=("cycle", "full"),
            seeds=(7,),
            frozen_commit=FROZEN,
        )
    with pytest.raises(ValueError, match="cannot enable diagnostic interventions"):
        PublicEvaluationConfig(
            partition="public-holdout",
            automatic_checkpointing=False,
            agents=("full",),
            seeds=(7,),
            frozen_commit=FROZEN,
        )

    diagnostic = PublicEvaluationConfig(
        partition="development",
        hot_path_profile=True,
        python_allocation_tracing=False,
        automatic_checkpointing=False,
        agents=("full",),
        seeds=(7,),
        frozen_commit=FROZEN,
    )
    argv = _reproduction_argv(diagnostic)
    assert "--hot-path-profile" in argv
    assert "--no-python-allocation-tracing" in argv
    assert "--no-automatic-checkpointing" in argv
    assert diagnostic.declaration()["python_allocation_tracing"] is False
    assert diagnostic.declaration()["automatic_checkpointing"] is False


def test_automatic_checkpoint_diagnostic_changes_only_full_use_memory(tmp_path: Path) -> None:
    context = cast(
        RunContext,
        _run_context(
            {
                "checkpoint_path": str(tmp_path / "checkpoint"),
                "game_id": "opaque-stage03-fixture",
                "git_commit": FROZEN,
                "max_actions": 80,
                "max_resets": 8,
                "run_id": "stage03-checkpoint-diagnostic",
                "seed": 7,
                "timeout_seconds": 120.0,
                "trace_path": str(tmp_path / "trace"),
            }
        ),
    )
    policy = make_evaluation_policy(
        "full",
        seed=7,
        run_context=context,
        automatic_checkpointing=False,
    )
    expected = replace(preset_features(ControllerPreset.FULL), use_memory=False)

    assert cast(Any, policy)._controller.preset is ControllerPreset.FULL
    assert cast(Any, policy)._controller.features == expected
    assert {
        key: value
        for key, value in cast(Any, policy)._controller.features.to_dict().items()
        if key != "use_memory"
    } == {
        key: value
        for key, value in preset_features(ControllerPreset.FULL).to_dict().items()
        if key != "use_memory"
    }


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
    with pytest.raises(ValueError, match="cannot enable diagnostic profiling"):
        PublicEvaluationConfig(
            partition="public-holdout",
            hot_path_profile=True,
            agents=("full",),
            seeds=(7,),
            frozen_commit=FROZEN,
        )
    with pytest.raises(ValueError, match="requires the FULL policy only"):
        PublicEvaluationConfig(
            partition="development",
            hot_path_profile=True,
            agents=("cycle", "full"),
            seeds=(7,),
            frozen_commit=FROZEN,
        )


def test_requested_hot_path_profile_is_structurally_verified() -> None:
    profiler = HotPathProfiler(
        rss_sampler=lambda: {
            "current_rss_bytes": 1,
            "measurement_source": "test",
            "peak_rss_bytes": 2,
            "reason": None,
        }
    )
    profiler.boundary("reset", actions=0)
    metrics: dict[str, object] = {
        "environment_actions": 0,
        "hot_path_profile": profiler.summary(),
    }
    specification: dict[str, object] = {"hot_path_profile": True}

    assert _hot_path_profile_valid(metrics, specification=specification, status="success")
    unavailable: dict[str, object] = {
        "hot_path_profile": {
            "enabled": False,
            "reason": "wall_clock_timeout",
            "schema": "arc3.hot-path-profile-unavailable.v0.1",
        }
    }
    assert _hot_path_profile_valid(
        unavailable,
        specification=specification,
        status="timeout",
    )
    assert not _hot_path_profile_valid(
        unavailable,
        specification=specification,
        status="success",
    )
    assert not _hot_path_profile_valid({}, specification=specification, status="success")


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

    authorization = SimpleNamespace(
        manifest_sha256=manifest.digest,
        opaque_count=len(manifest.games("public-holdout")),
    )
    monkeypatch.setattr(
        "arc3.evaluation.public.validate_holdout_authorization",
        lambda _config: authorization,
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
    metrics: dict[str, object] = {
        "environment_actions": 1,
        "resets": 0,
        "fault_count": 0,
    }
    diagnostics: dict[str, object] = {}
    for field, metric_field in (
        ("python_allocation_tracing", "python_allocation_tracing_enabled"),
        ("automatic_checkpointing", "automatic_checkpointing_enabled"),
    ):
        if field in specification:
            diagnostics[field] = specification[field]
            metrics[metric_field] = specification[field]
    if "asset_aggregate_sha256_before" in specification:
        memory_sample: dict[str, object] = {
            "current_rss_bytes": 1,
            "peak_rss_bytes": 2,
            "measurement_source": "fixture-kernel-rss",
            "reason": None,
        }
        metrics.update(
            {
                "total_cpu_seconds": 0.01,
                "process_memory_before": memory_sample,
                "process_memory_after": memory_sample,
                "peak_rss_bytes": 2,
                "network_attempt_count": (
                    None if specification["surface"] == "online-public" else 0
                ),
                "policy_close_status": "closed",
                "session_close_status": "closed-by-episode-runner",
                "journal_close_status": "closed-by-policy",
            }
        )
    expected_asset_hash = specification.get("asset_aggregate_sha256_before")
    asset_identity_after = (
        {
            "game_id": specification["game_id"],
            "files": [],
            "aggregate_sha256": expected_asset_hash,
            "source_semantically_inspected": False,
        }
        if isinstance(expected_asset_hash, str)
        else None
    )
    return seal_object(
        {
            "schema": PUBLIC_RUN_SCHEMA,
            "evaluation_id": specification["evaluation_id"],
            "run_id": specification["run_id"],
            "run_spec_hash": specification["run_spec_hash"],
            "game_id": specification["game_id"],
            "baseline_id": specification["baseline_id"],
            "agent": specification["agent"],
            "seed": specification["seed"],
            "surface": specification["surface"],
            "partition": specification["partition"],
            **diagnostics,
            "status": "success",
            "identity_hash": identity_hash,
            "score": {
                "verified": True,
                "official_run_game_id": specification["game_id"],
                "score": 0.0,
                "levels_completed": 0,
                "completed": False,
            },
            "metrics": metrics,
            "trace": {"replay_verified": True},
            "asset_identity_after": asset_identity_after,
            **(
                {"asset_identity_check": _asset_identity_check(specification, asset_identity_after)}
                if "asset_aggregate_sha256_before" in specification
                else {}
            ),
            "environment_transport": specification["network_mode"],
            "failure": None,
        },
        hash_field="receipt_hash",
    )


@pytest.mark.parametrize(
    ("field", "metric_field"),
    (
        ("python_allocation_tracing", "python_allocation_tracing_enabled"),
        ("automatic_checkpointing", "automatic_checkpointing_enabled"),
    ),
)
def test_stage03_diagnostic_switches_are_bound_into_receipts(
    field: str,
    metric_field: str,
) -> None:
    identity_hash = "sha256:" + "1" * 64
    specification: dict[str, object] = {
        "evaluation_id": "stage03-diagnostic-fixture",
        "run_id": "fixture-B1-cycle-seed-7",
        "game_id": "fixture-v1",
        "partition": "smoke",
        "surface": "local-public",
        "network_mode": "offline-evaluation",
        "baseline_id": "B1",
        "agent": "cycle",
        "seed": 7,
        "identity_hash": identity_hash,
        "hot_path_profile": False,
        "python_allocation_tracing": True,
        "automatic_checkpointing": True,
    }
    specification["run_spec_hash"] = seal_object(specification, hash_field="run_spec_hash")[
        "run_spec_hash"
    ]
    receipt = _minimal_run(specification, identity_hash)

    assert _receipt_valid(receipt, specification, identity_hash)

    mismatched = dict(receipt)
    mismatched.pop("receipt_hash")
    mismatched[field] = False
    mismatched_metrics = dict(cast(dict[str, object], mismatched["metrics"]))
    mismatched_metrics[metric_field] = False
    mismatched["metrics"] = mismatched_metrics
    resealed = seal_object(mismatched, hash_field="receipt_hash")
    assert not _receipt_valid(resealed, specification, identity_hash)


def test_local_success_receipt_binds_post_run_asset_identity() -> None:
    identity_hash = "sha256:" + "1" * 64
    asset_hash = "sha256:" + "2" * 64
    specification: dict[str, object] = {
        "evaluation_id": "asset-boundary-fixture",
        "run_id": "fixture-B4-full-seed-7",
        "game_id": "fixture-v1",
        "stable_name": "fixture",
        "partition": "development",
        "surface": "local-public",
        "network_mode": "offline-evaluation",
        "baseline_id": "B1",
        "agent": "cycle",
        "seed": 7,
        "identity_hash": identity_hash,
        "hot_path_profile": False,
        "asset_aggregate_sha256_before": asset_hash,
    }
    specification["run_spec_hash"] = seal_object(specification, hash_field="run_spec_hash")[
        "run_spec_hash"
    ]
    receipt = _minimal_run(specification, identity_hash)

    assert _receipt_valid(receipt, specification, identity_hash)

    missing_resource = deepcopy(receipt)
    missing_resource.pop("receipt_hash")
    cast(dict[str, object], missing_resource["metrics"]).pop("total_cpu_seconds")
    assert not _receipt_valid(
        seal_object(missing_resource, hash_field="receipt_hash"),
        specification,
        identity_hash,
    )

    mismatched = dict(receipt)
    mismatched.pop("receipt_hash")
    mismatched["asset_identity_after"] = {
        "game_id": "fixture-v1",
        "files": [],
        "aggregate_sha256": "sha256:" + "3" * 64,
        "source_semantically_inspected": False,
    }
    assert not _receipt_valid(
        seal_object(mismatched, hash_field="receipt_hash"),
        specification,
        identity_hash,
    )

    changed_failure = deepcopy(mismatched)
    changed_failure["status"] = "failure"
    changed_failure["failure"] = {
        "kind": "EvaluationError",
        "message": "local asset identity changed during the run",
    }
    changed_failure["asset_identity_check"] = _asset_identity_check(
        specification,
        cast(dict[str, object], changed_failure["asset_identity_after"]),
    )
    changed_failure = seal_object(changed_failure, hash_field="receipt_hash")
    assert _receipt_valid(changed_failure, specification, identity_hash)
    assert changed_failure["asset_identity_check"]["status"] == "changed"
    assert changed_failure["asset_identity_check"]["integrity_failure"] is True

    wrong_score = deepcopy(changed_failure)
    wrong_score.pop("receipt_hash")
    cast(dict[str, object], wrong_score["score"])["official_run_game_id"] = "wrong-v1"
    assert not _receipt_valid(
        seal_object(wrong_score, hash_field="receipt_hash"),
        specification,
        identity_hash,
    )


def test_asset_boundary_accepts_recorded_uncompared_and_rejects_online_assets() -> None:
    identity_hash = "sha256:" + "1" * 64
    base: dict[str, object] = {
        "evaluation_id": "uncompared-asset-fixture",
        "run_id": "fixture-B1-cycle-seed-7",
        "game_id": "fixture-v1",
        "stable_name": "fixture",
        "partition": "development",
        "surface": "local-public",
        "network_mode": "offline-evaluation",
        "baseline_id": "B1",
        "agent": "cycle",
        "seed": 7,
        "identity_hash": identity_hash,
        "hot_path_profile": False,
        "asset_aggregate_sha256_before": None,
    }
    base["run_spec_hash"] = seal_object(base, hash_field="run_spec_hash")["run_spec_hash"]
    local = _minimal_run(base, identity_hash)
    local.pop("receipt_hash")
    local_asset: dict[str, object] = {
        "game_id": "fixture-v1",
        "files": [],
        "aggregate_sha256": "sha256:" + "7" * 64,
        "source_semantically_inspected": False,
    }
    local["asset_identity_after"] = local_asset
    local["asset_identity_check"] = _asset_identity_check(base, local_asset)
    assert _receipt_valid(
        seal_object(local, hash_field="receipt_hash"),
        base,
        identity_hash,
    )

    missing = deepcopy(local)
    missing["asset_identity_after"] = None
    missing["asset_identity_check"] = _asset_identity_check(base, None)
    assert not _receipt_valid(
        seal_object(missing, hash_field="receipt_hash"),
        base,
        identity_hash,
    )

    online_specification = dict(base)
    online_specification.update(
        {
            "surface": "online-public",
            "network_mode": "official-online-one-shot",
        }
    )
    online_specification["run_spec_hash"] = seal_object(
        online_specification, hash_field="run_spec_hash"
    )["run_spec_hash"]
    online = _minimal_run(online_specification, identity_hash)
    online.pop("receipt_hash")
    online["asset_identity_after"] = local_asset
    online["asset_identity_check"] = _asset_identity_check(online_specification, local_asset)
    assert not _receipt_valid(
        seal_object(online, hash_field="receipt_hash"),
        online_specification,
        identity_hash,
    )


def test_failure_receipt_preserves_a_recovered_official_score() -> None:
    identity_hash = "sha256:" + "1" * 64
    specification: dict[str, object] = {
        "evaluation_id": "terminal-failure-fixture",
        "run_id": "fixture-B4-full-seed-7",
        "run_spec_hash": "sha256:" + "2" * 64,
        "game_id": "fixture-v1",
        "baseline_id": "B4",
        "agent": "full",
        "seed": 7,
        "partition": "development",
        "surface": "local-public",
        "network_mode": "offline-evaluation",
    }
    identity: dict[str, object] = {"identity_hash": identity_hash}
    recovered_score: dict[str, object] = {
        "verified": True,
        "official_run_game_id": "fixture-v1",
        "score": 1.0,
        "levels_completed": 1,
        "completed": True,
    }

    receipt = _failure_result(
        specification,
        identity,
        started_at="2026-08-22T00:00:00Z",
        status="failure",
        kind="PolicyError",
        message="derived processing failed after the returned consequence",
        recovered_score=recovered_score,
    )

    assert receipt["status"] == "failure"
    assert receipt["score"] == recovered_score
    assert receipt["failure"]["kind"] == "PolicyError"


def test_aggregate_separates_recovered_failure_scores_from_success_metrics() -> None:
    results: list[dict[str, Any]] = [
        {
            "agent": "random",
            "baseline_id": "B0",
            "game_id": "fixture-v1",
            "seed": 7,
            "status": "success",
            "score": {
                "verified": True,
                "score": 0.4,
                "levels_completed": 1,
                "completed": True,
            },
            "metrics": {"environment_actions": 4, "resets": 0, "fault_count": 0},
        },
        {
            "agent": "full",
            "baseline_id": "B4",
            "game_id": "fixture-v1",
            "seed": 7,
            "status": "success",
            "score": {
                "verified": True,
                "score": 0.1,
                "levels_completed": 0,
                "completed": False,
            },
            "metrics": {"environment_actions": 1, "resets": 0, "fault_count": 0},
        },
        {
            "agent": "full",
            "baseline_id": "B4",
            "game_id": "fixture-v1",
            "seed": 8,
            "status": "failure",
            "score": {
                "verified": True,
                "score": 8.0,
                "levels_completed": 8,
                "completed": True,
            },
            "metrics": {"environment_actions": 2, "resets": 0, "fault_count": 1},
        },
    ]

    summary = _aggregate(results, partition="development")
    policies = cast(dict[str, dict[str, object]], summary["policies"])
    full = policies["full"]
    successful = cast(dict[str, object], full["successful_score_metrics"])
    recovered = cast(dict[str, object], full["recovered_failure_score_metrics"])

    assert summary["schema"] == "arc3.public-evaluation.summary.v0.2"
    assert summary["status"] == "PARTIAL"
    assert summary["claim"] == "MECHANISM_NOT_OBSERVED"
    assert summary["score_metric_scope"] == "SUCCESSFUL_RUNS_ONLY"
    assert full["levels_completed"] == 0
    assert full["completed_runs"] == 0
    assert full["mean_score"] == pytest.approx(0.1)
    assert successful == {
        "evidence_scope": "terminal-success-receipts",
        "run_count": 1,
        "score_sum": 0.1,
        "mean_score": 0.1,
        "levels_completed": 0,
        "completed_runs": 0,
    }
    assert recovered == {
        "evidence_scope": "verified-scorecards-on-failed-receipts",
        "run_count": 1,
        "score_sum": 8.0,
        "mean_score": 8.0,
        "levels_completed": 8,
        "completed_runs": 1,
    }

    report = _render_report(
        {
            "surface": "local-public",
            "partition": "development",
            "git_commit": "fixture-commit",
            "public_partition_manifest_hash": "sha256:fixture",
            "network_mode": "offline-evaluation",
        },
        summary,
        results,
    )
    assert "Successful-run score and level aggregates exclude every failed receipt" in report
    assert "| full | 2 | 1 | 1 | 0 | 0.100000 | 1 | 8 | 8.000000 | 3 |" in report
    assert "| full | fixture-v1 | 8 | failure | recovered-failure |" in report


def test_unverified_failed_receipt_has_no_score_aggregate() -> None:
    summary = _aggregate(
        [
            {
                "agent": "full",
                "baseline_id": "B4",
                "status": "timeout",
                "score": {
                    "verified": False,
                    "score": 0.0,
                    "levels_completed": 0,
                    "completed": False,
                },
                "metrics": {"environment_actions": 3, "resets": 0, "fault_count": 1},
            }
        ],
        partition="development",
    )
    full = cast(dict[str, dict[str, object]], summary["policies"])["full"]
    successful = cast(dict[str, object], full["successful_score_metrics"])
    recovered = cast(dict[str, object], full["recovered_failure_score_metrics"])

    assert full["mean_score"] is None
    assert successful["run_count"] == 0
    assert recovered["run_count"] == 0
    assert recovered["mean_score"] is None
    assert full["unscored_failure_runs"] == 1


def test_legacy_public_summary_remains_reproducible_for_immutable_evidence() -> None:
    summary = _legacy_aggregate(
        [
            {
                "agent": "full",
                "baseline_id": "B4",
                "status": "timeout",
                "score": {"score": 0.0, "levels_completed": 0, "completed": False},
                "metrics": {"environment_actions": 21, "resets": 0, "fault_count": 1},
            }
        ],
        partition="development",
    )

    assert summary["schema"] == "arc3.public-evaluation.summary.v0.1"
    assert summary["policies"] == {
        "full": {
            "baseline_id": "B4",
            "runs": 1,
            "successes": 0,
            "failures": 1,
            "levels_completed": 0,
            "completed_runs": 0,
            "environment_actions": 21,
            "resets": 0,
            "faults": 1,
            "mean_score": 0.0,
        }
    }


def test_worker_seals_trace_score_resources_asset_and_close_after_policy_fault(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    game_id = "fixture-v1"
    trace_path = tmp_path / "trace"
    checkpoint_path = tmp_path / "checkpoint"
    environments_dir = tmp_path / "environments"
    asset_dir = environments_dir / "fixture" / "v1"
    asset_dir.mkdir(parents=True)
    (asset_dir / "metadata.json").write_text("{}\n", encoding="utf-8")
    asset = local_asset_identity(
        environments_dir,
        PublicGameEntry(
            game_id=game_id,
            stable_name="fixture",
            assignment_hash="fixture-assignment",
            partition="development",
            exposure="fixture-only",
        ),
    )
    assert asset is not None

    def observation(
        value: int,
        *,
        state: GameStateName,
        levels: int,
        returned: ActionRequest | None = None,
    ) -> Observation:
        return Observation(
            game_id=GameId(game_id),
            frames=(GridFrame(((value, 0), (0, 0))),),
            state=state,
            levels_completed=levels,
            win_levels=1,
            available_actions=(ActionName.ACTION1,),
            returned_action=returned,
        )

    class FaultSession:
        def __init__(self) -> None:
            self._observation = observation(
                1,
                state=GameStateName.NOT_FINISHED,
                levels=0,
            )
            self.close_count = 0

        @property
        def observation(self) -> Observation:
            return self._observation

        def step(
            self,
            action: ActionRequest,
            *,
            reasoning: Mapping[str, JSONValue] | None = None,
        ) -> Observation:
            assert reasoning is not None
            self._observation = observation(
                2,
                state=GameStateName.WIN,
                levels=1,
                returned=action,
            )
            return self._observation

        def close(self) -> ScoreSummary:
            self.close_count += 1
            return ScoreSummary(
                surface=EvaluationSurface.LOCAL_PUBLIC,
                verified=True,
                scorer="fault-injection-local-scorecard",
                score=1.0,
                runs=(
                    ScoreRunSummary(
                        game_id=GameId(game_id),
                        score=1.0,
                        levels_completed=1,
                        actions=1,
                        resets=0,
                        state=GameStateName.WIN,
                        completed=True,
                        level_scores=(1.0,),
                        level_actions=(1,),
                        level_baseline_actions=(1,),
                    ),
                ),
            )

    class FaultPolicy:
        manages_trace = True

        def __init__(self) -> None:
            self.journal = EventJournal(trace_path, run_id="fault-run")
            self.sink = BaselineTraceSink(
                journal=self.journal,
                episode_id="episode:fault-run",
                source=SourceIdentity("fault_fixture", "1"),
                code_identity=CodeIdentity(
                    "fixture-commit",
                    "sha256:" + "4" * 64,
                ),
            )
            self.before: Observation | None = None
            self.action: ActionRequest | None = None
            self.closed = False

        def select(self, current: Observation) -> ActionRequest:
            self.before = current
            self.action = ActionRequest(ActionName.ACTION1)
            self.sink.record_observation(current)
            self.sink.record_candidates(current)
            self.sink.record_selected(current, self.action)
            self.sink.record_submitted(current, self.action)
            return self.action

        def accept_consequence(self, returned: Observation) -> None:
            assert self.before is not None
            assert self.action is not None
            self.sink.record_consequence(self.before, self.action, returned)
            self.sink.record_observation(returned)
            self.journal.flush()
            raise RuntimeError("injected post-action policy fault")

        def close(self) -> None:
            self.closed = True
            self.journal.close()

    session = FaultSession()
    policy = FaultPolicy()

    class Adapter:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

        def open(self, selected_game_id: str, *, seed: int) -> FaultSession:
            assert selected_game_id == game_id
            assert seed == 7
            return session

    monkeypatch.setattr("arc3.evaluation.public_runner.ArcAGIAdapter", Adapter)
    monkeypatch.setattr(
        "arc3.evaluation.public_runner.make_evaluation_policy",
        lambda *_args, **_kwargs: policy,
    )

    identity_hash = "sha256:" + "5" * 64
    specification: dict[str, object] = {
        "evaluation_id": "worker-fault-fixture",
        "run_id": "fault-run",
        "game_id": game_id,
        "stable_name": "fixture",
        "baseline_id": "B4",
        "agent": "full",
        "seed": 7,
        "partition": "development",
        "surface": "local-public",
        "network_mode": "offline-evaluation",
        "identity_hash": identity_hash,
        "hot_path_profile": False,
        "python_allocation_tracing": False,
        "automatic_checkpointing": True,
        "max_actions": 8,
        "max_resets": 1,
        "asset_aggregate_sha256_before": asset.aggregate_sha256,
    }
    specification["run_spec_hash"] = seal_object(specification, hash_field="run_spec_hash")[
        "run_spec_hash"
    ]
    identity: dict[str, object] = {
        "git_commit": "fixture-commit",
        "config_hash": "sha256:" + "4" * 64,
        "first_party_source_hash": "sha256:" + "6" * 64,
        "identity_hash": identity_hash,
    }
    receipt_path = tmp_path / "receipt.json"
    _worker(
        {
            "identity": identity,
            "specification": specification,
            "trace_path": str(trace_path),
            "trace_relative": "t/fault-run",
            "checkpoint_path": str(checkpoint_path),
            "environments_dir": str(environments_dir),
            "recordings_dir": str(tmp_path / "recordings"),
            "timeout_seconds": 30.0,
            "max_actions": 8,
            "max_resets": 1,
            "seed": 7,
            "run_id": "fault-run",
            "game_id": game_id,
            "git_commit": "fixture-commit",
        },
        str(receipt_path),
    )
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))

    assert receipt["status"] == "failure"
    assert receipt["failure"]["kind"] == "RuntimeError"
    assert receipt["score"]["verified"] is True
    assert receipt["score"]["official_run_actions"] == 1
    assert receipt["metrics"]["environment_actions"] == 1
    assert receipt["metrics"]["resets"] == 0
    assert receipt["metrics"]["fault_count"] == 1
    assert receipt["metrics"]["total_cpu_seconds"] >= 0.0
    assert receipt["metrics"]["process_memory_before"]["measurement_source"]
    assert receipt["metrics"]["process_memory_after"]["measurement_source"]
    assert receipt["metrics"]["network_attempt_count"] == 0
    assert receipt["metrics"]["policy_close_status"] == "closed"
    assert receipt["metrics"]["session_close_status"] == "closed"
    assert receipt["metrics"]["journal_close_status"] == "closed-by-policy"
    assert receipt["trace"]["submitted_action_count"] == 1
    assert receipt["trace"]["consequence_count"] == 1
    assert receipt["trace"]["tail_event_hash"].startswith("sha256:")
    assert receipt["trace"]["replay_verified"] is True
    assert receipt["asset_identity_after"]["aggregate_sha256"] == asset.aggregate_sha256
    assert policy.closed is True
    assert session.close_count == 1
    assert _receipt_valid(receipt, specification, identity_hash)
    aggregate = _aggregate([receipt], partition="development")
    assert aggregate["status"] == "FAILED_INFRASTRUCTURE"
    assert aggregate["claim"] == "MECHANISM_NOT_OBSERVED"


def test_local_worker_socket_guard_counts_denial_and_restores_entry_points() -> None:
    original_create_connection = socket.create_connection
    original_connect = socket.socket.connect
    guard = _OfflineSocketGuard(enabled=True)
    probe_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    guard.install()
    try:
        attempts = (
            lambda: socket.create_connection(("203.0.113.1", 9)),
            lambda: socket.getaddrinfo("example.invalid", 443),
            lambda: probe_socket.connect(("203.0.113.1", 9)),
            lambda: probe_socket.connect_ex(("203.0.113.1", 9)),
            lambda: probe_socket.sendto(b"fixture", ("203.0.113.1", 9)),
        )
        for attempt in attempts:
            with pytest.raises(EvaluationError, match="blocked a network attempt"):
                attempt()
        assert guard.attempt_count == 5
    finally:
        guard.restore()
        probe_socket.close()

    assert socket.create_connection is original_create_connection
    assert socket.socket.connect is original_connect


def test_worker_restores_socket_entry_points_after_unexpected_body_unwind(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_create_connection = socket.create_connection
    original_connect = socket.socket.connect

    def raise_unexpected(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("unexpected worker-body unwind")

    monkeypatch.setattr("arc3.evaluation.public_runner._worker_body", raise_unexpected)
    with pytest.raises(RuntimeError, match="unexpected worker-body unwind"):
        _worker(
            {"specification": {"surface": "local-public"}},
            str(tmp_path / "unwritten.json"),
        )

    assert socket.create_connection is original_create_connection
    assert socket.socket.connect is original_connect


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
    errors = cast(list[str], verification["errors"])
    assert any("results.jsonl" in error for error in errors)


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
