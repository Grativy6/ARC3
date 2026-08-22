"""Process-isolated artifact runner for guarded Stage 15 public work."""

from __future__ import annotations

import hashlib
import json
import multiprocessing
import os
import shlex
import subprocess
import sys
import time
import tracemalloc
import uuid
from pathlib import Path
from typing import Any, cast

from arc3.adapters.arc_agi import ARC_AGI_VERSION, ARCENGINE_VERSION, ArcAGIAdapter
from arc3.config import ARC3Config
from arc3.errors import EvaluationError, TraceError
from arc3.trace import BaselineTraceSink, CodeIdentity, EventJournal, SourceIdentity
from arc3.types import EnvironmentMode, EvaluationSurface

from .artifacts import (
    atomic_write_bytes,
    atomic_write_json,
    atomic_write_text,
    canonical_json_bytes,
    load_json,
    seal_object,
    sha256_bytes,
    sha256_file,
    verify_object_hash,
)
from .baselines import baseline_descriptor, make_evaluation_policy
from .models import EvaluationOutcome
from .public import (
    PUBLIC_EVALUATION_SCHEMA,
    PUBLIC_RUN_SCHEMA,
    LocalAssetIdentity,
    PublicEvaluationConfig,
    PublicExposureLedger,
    PublicPartitionManifest,
    _first_party_source_hash,
    _hardware,
    _run_context,
    _run_id,
    _score_payload,
    _trace_receipt,
    _utc_now,
    acquire_local_public_asset,
    inventory_local_assets,
    local_asset_identity,
    run_public_episode,
    validate_frozen_source,
    validate_public_gate,
)

_TERMINAL_STATUSES = frozenset({"PASS", "PARTIAL", "FAILED_INFRASTRUCTURE"})


def _as_int(value: object, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise EvaluationError(f"{field} must be an integer")
    return value


def _as_float(value: object, *, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise EvaluationError(f"{field} must be numeric")
    return float(value)


def _evaluation_id(config: PublicEvaluationConfig, started_at: str) -> str:
    if config.evaluation_id is not None:
        return config.evaluation_id
    digest = hashlib.sha256(canonical_json_bytes(config.declaration())).hexdigest()[:12]
    compact = "".join(character for character in started_at if character.isalnum())
    return f"public-{compact}-{digest}"


def _identity(
    config: PublicEvaluationConfig,
    manifest: PublicPartitionManifest,
    assets: dict[str, LocalAssetIdentity],
) -> dict[str, object]:
    root = Path(__file__).resolve().parents[3]
    lock = root / "upstream.lock.json"
    selected = config.selected_games(manifest)
    declaration = config.declaration()
    identity: dict[str, object] = {
        "git_commit": config.frozen_commit,
        "dirty_worktree": False,
        "first_party_source_hash": _first_party_source_hash(),
        "upstream_lock_hash": sha256_file(lock) if lock.is_file() else None,
        "public_partition_manifest_hash": manifest.digest,
        "python_version": sys.version.split()[0],
        "platform": sys.platform,
        "hardware": _hardware(),
        "surface": config.surface,
        "agent_config": declaration,
        "config_hash": sha256_bytes(canonical_json_bytes(declaration)),
        "games": [entry.game_id for entry in selected],
        "seeds": list(config.seeds),
        "action_budget": config.max_actions,
        "wall_clock_budget_seconds": config.timeout_seconds,
        "budgets": {
            "maximum_actions": config.max_actions,
            "maximum_resets": config.max_resets,
            "maximum_wall_clock_seconds_per_run": config.timeout_seconds,
        },
        "network_mode": config.network_mode,
        "policy_network_mode": "offline",
        "asset_identities": {game_id: assets[game_id].to_dict() for game_id in sorted(assets)},
        "scorer_source_version": (
            f"arc-agi=={ARC_AGI_VERSION} "
            f"{'ONLINE scorecard' if config.surface == 'online-public' else 'local ScorecardManager'}; "
            f"arcengine=={ARCENGINE_VERSION}"
        ),
    }
    identity["identity_hash"] = sha256_bytes(canonical_json_bytes(identity))
    return identity


def _specifications(
    evaluation_id: str,
    config: PublicEvaluationConfig,
    manifest: PublicPartitionManifest,
    identity: dict[str, object],
) -> list[dict[str, object]]:
    specifications: list[dict[str, object]] = []
    for entry in config.selected_games(manifest):
        for agent in config.agents:
            for seed in config.seeds:
                specification: dict[str, object] = {
                    "evaluation_id": evaluation_id,
                    "run_id": _run_id(entry.game_id, agent, seed),
                    "game_id": entry.game_id,
                    "stable_name": entry.stable_name,
                    "partition": config.partition,
                    "baseline_id": baseline_descriptor(agent).baseline_id,
                    "agent": agent,
                    "seed": seed,
                    "max_actions": config.max_actions,
                    "max_resets": config.max_resets,
                    "timeout_seconds": config.timeout_seconds,
                    "surface": config.surface,
                    "network_mode": config.network_mode,
                    "identity_hash": identity["identity_hash"],
                }
                specification["run_spec_hash"] = sha256_bytes(canonical_json_bytes(specification))
                specifications.append(specification)
    return specifications


def _storage_key(run_id: str) -> str:
    return hashlib.sha256(run_id.encode("utf-8")).hexdigest()[:20]


def _runtime_path(path: Path) -> Path:
    resolved = path.resolve()
    if os.name == "nt":
        value = str(resolved)
        if not value.startswith("\\\\?\\"):
            return Path(f"\\\\?\\{value}")
    return resolved


def _empty_metrics() -> dict[str, object]:
    return {
        "environment_actions": 0,
        "resets": 0,
        "game_over_events": 0,
        "time_to_first_progress_seconds": None,
        "actions_to_first_completed_level": None,
        "repeated_no_op_rate": 0.0,
        "invalid_action_rate": 0.0,
        "coordinate_action_hit_rate": None,
        "unique_state_count": 0,
        "state_revisitation_rate": 0.0,
        "decision_latency_seconds": {"p50": None, "p95": None, "p99": None},
        "total_wall_clock_seconds": 0.0,
        "peak_python_allocation_bytes": None,
        "fault_count": 1,
    }


def _failure_result(
    specification: dict[str, object],
    identity: dict[str, object],
    *,
    started_at: str,
    status: str,
    kind: str,
    message: str,
    metrics: dict[str, object] | None = None,
    trace: dict[str, object] | None = None,
    asset_identity_after: dict[str, object] | None = None,
) -> dict[str, Any]:
    expected_surface = (
        EvaluationSurface.ONLINE_PUBLIC
        if specification.get("surface") == "online-public"
        else EvaluationSurface.LOCAL_PUBLIC
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
            "status": status,
            "started_at": started_at,
            "completed_at": _utc_now(),
            "identity_hash": identity["identity_hash"],
            "score": _score_payload(None, expected_surface=expected_surface),
            "metrics": metrics or _empty_metrics(),
            "trace": trace,
            "asset_identity_after": asset_identity_after,
            "asset_identity_after_reason": (
                "official ONLINE mode evaluates remotely and does not download game source"
                if specification.get("surface") == "online-public"
                else "asset identity is frozen in the evaluation manifest"
            ),
            "environment_transport": specification.get("network_mode"),
            "failure": {"kind": kind, "message": message[:500]},
        },
        hash_field="receipt_hash",
    )


def _salvage_trace(
    trace_path: Path,
    *,
    run_id: str,
    relative_path: str,
    elapsed_seconds: float,
) -> tuple[dict[str, object] | None, dict[str, object]]:
    """Preserve a verifiable partial trace after timeout or worker failure."""

    metrics = _empty_metrics()
    metrics["total_wall_clock_seconds"] = elapsed_seconds
    if not trace_path.is_dir():
        return None, metrics
    try:
        trace = _trace_receipt(trace_path, run_id=run_id, relative_path=relative_path)
    except (OSError, TraceError, ValueError):
        return None, metrics
    metrics["environment_actions"] = _as_int(
        trace["environment_action_count"], field="environment_action_count"
    )
    metrics["resets"] = _as_int(trace["reset_count"], field="reset_count")
    counts_value = trace.get("event_type_counts")
    counts = counts_value if isinstance(counts_value, dict) else {}
    metrics["fault_count"] = max(1, int(counts.get("run.environment_fault", 0)))
    consequences = _as_int(trace["consequence_count"], field="consequence_count")
    metrics["trace_bytes_per_action"] = (
        _as_int(trace["byte_length"], field="byte_length") / consequences if consequences else None
    )
    return trace, metrics


def _holdout_asset_after(
    manifest: PublicPartitionManifest,
    config: PublicEvaluationConfig,
    game_id: str,
) -> dict[str, object] | None:
    if config.partition != "public-holdout":
        return None
    entry = next(
        (item for item in manifest.games(config.partition) if item.game_id == game_id), None
    )
    if entry is None:
        return None
    try:
        identity = local_asset_identity(config.environments_dir, entry)
    except (EvaluationError, OSError):
        return None
    return identity.to_dict() if identity is not None else None


def _worker(spec: dict[str, Any], receipt_path: str) -> None:
    started_at = _utc_now()
    started = time.perf_counter()
    specification = cast(dict[str, object], spec["specification"])
    identity = cast(dict[str, object], spec["identity"])
    run_id = str(specification["run_id"])
    trace_path = Path(str(spec["trace_path"]))
    trace_relative = str(spec["trace_relative"])
    policy = None
    session = None
    journal: EventJournal | None = None
    trace: dict[str, object] | None = None
    metrics = _empty_metrics()
    caught: Exception | None = None
    scorecard = None
    score_payload: dict[str, object] | None = None
    asset_identity_after: dict[str, object] | None = None
    tracemalloc.start()
    try:
        surface = str(specification["surface"])
        online_one_shot = surface == "online-public"
        adapter = ArcAGIAdapter(
            ARC3Config.for_mode(
                EnvironmentMode.ONLINE if online_one_shot else EnvironmentMode.LOCAL,
                seed=_as_int(specification["seed"], field="seed"),
                network_enabled=online_one_shot,
            ),
            environments_dir=str(spec["environments_dir"]),
            recordings_dir=str(spec["recordings_dir"]),
            save_recording=True,
            include_frame_data=True,
            environ={},
        )
        session = adapter.open(
            str(specification["game_id"]),
            seed=_as_int(specification["seed"], field="seed"),
        )
        if str(session.observation.game_id) != str(specification["game_id"]):
            raise EvaluationError(
                "official initial observation game identity does not match the run declaration"
            )
        agent = str(specification["agent"])
        policy = make_evaluation_policy(
            agent,
            seed=_as_int(specification["seed"], field="seed"),
            run_context=cast(Any, _run_context(spec)) if agent == "full" else None,
        )
        sink: BaselineTraceSink | None = None
        if not policy.manages_trace:
            journal = EventJournal(trace_path, run_id=run_id)
            source_surface = str(specification["surface"]).replace("-", "_")
            sink = BaselineTraceSink(
                journal=journal,
                episode_id=f"episode:{run_id}",
                source=SourceIdentity(
                    f"arc_agi_{source_surface}",
                    f"arc-agi=={ARC_AGI_VERSION}",
                    {
                        "baseline_id": str(specification["baseline_id"]),
                        "network_mode": str(specification["network_mode"]),
                    },
                ),
                code_identity=CodeIdentity(
                    str(identity["git_commit"]),
                    str(identity["config_hash"]),
                    {"first_party_source_hash": str(identity["first_party_source_hash"])},
                ),
            )
        scorecard, metrics = run_public_episode(
            session,
            policy,
            max_actions=_as_int(specification["max_actions"], field="max_actions"),
            max_resets=_as_int(specification["max_resets"], field="max_resets"),
            trace_sink=sink,
        )
    except Exception as error:
        caught = error
    finally:
        if policy is not None:
            try:
                policy.close()
            except Exception as error:
                caught = caught or error
        if session is not None and scorecard is None:
            try:
                scorecard = session.close()
            except Exception as error:
                caught = caught or error
        if journal is not None:
            try:
                journal.close()
            except Exception as error:
                caught = caught or error
        try:
            if trace_path.is_dir():
                trace = _trace_receipt(trace_path, run_id=run_id, relative_path=trace_relative)
        except (OSError, TraceError, ValueError) as error:
            caught = caught or error
        _current, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        metrics["peak_python_allocation_bytes"] = peak
        metrics["total_wall_clock_seconds"] = time.perf_counter() - started
        if trace is not None:
            counts_value = trace.get("event_type_counts")
            counts = counts_value if isinstance(counts_value, dict) else {}
            metrics["fault_count"] = int(counts.get("run.environment_fault", 0))
            consequences = int(cast(int, trace["consequence_count"]))
            metrics["trace_bytes_per_action"] = (
                int(cast(int, trace["byte_length"])) / consequences if consequences else None
            )
        if scorecard is not None and caught is None:
            try:
                expected_surface = (
                    EvaluationSurface.ONLINE_PUBLIC
                    if str(specification["surface"]) == "online-public"
                    else EvaluationSurface.LOCAL_PUBLIC
                )
                score_payload = _score_payload(
                    scorecard,
                    expected_game_id=str(specification["game_id"]),
                    expected_surface=expected_surface,
                )
            except EvaluationError as error:
                caught = error
    if caught is not None or scorecard is None or score_payload is None:
        result = _failure_result(
            specification,
            identity,
            started_at=started_at,
            status="failure",
            kind=type(caught).__name__ if caught is not None else "missing_scorecard",
            message=(
                f"{type(caught).__name__}: {caught}"
                if caught is not None
                else "official local session returned no scorecard"
            ),
            metrics=metrics,
            trace=trace,
            asset_identity_after=asset_identity_after,
        )
    else:
        result = seal_object(
            {
                "schema": PUBLIC_RUN_SCHEMA,
                "evaluation_id": specification["evaluation_id"],
                "run_id": run_id,
                "run_spec_hash": specification["run_spec_hash"],
                "game_id": specification["game_id"],
                "baseline_id": specification["baseline_id"],
                "agent": specification["agent"],
                "seed": specification["seed"],
                "surface": specification["surface"],
                "partition": specification["partition"],
                "status": "success",
                "started_at": started_at,
                "completed_at": _utc_now(),
                "identity_hash": identity["identity_hash"],
                "score": score_payload,
                "metrics": metrics,
                "trace": trace,
                "asset_identity_after": asset_identity_after,
                "environment_transport": specification["network_mode"],
                "asset_identity_after_reason": (
                    "official ONLINE mode evaluates remotely and does not download game source"
                    if specification["surface"] == "online-public"
                    else "asset identity is frozen in the evaluation manifest"
                ),
                "failure": None,
            },
            hash_field="receipt_hash",
        )
    atomic_write_json(Path(receipt_path), result)


def _receipt_valid(
    receipt: dict[str, Any], specification: dict[str, object], identity_hash: object
) -> bool:
    unsigned_specification = dict(specification)
    declared_spec_hash = unsigned_specification.pop("run_spec_hash", None)
    if declared_spec_hash != sha256_bytes(canonical_json_bytes(unsigned_specification)):
        return False
    bound_fields = (
        "evaluation_id",
        "run_id",
        "run_spec_hash",
        "game_id",
        "baseline_id",
        "agent",
        "seed",
        "partition",
    )
    if any(receipt.get(field) != specification.get(field) for field in bound_fields):
        return False
    status = receipt.get("status")
    if status not in {"success", "failure", "timeout", "crash", "interrupted"}:
        return False
    score = receipt.get("score")
    metrics = receipt.get("metrics")
    if not isinstance(score, dict) or not isinstance(metrics, dict):
        return False
    if status == "success":
        trace = receipt.get("trace")
        if (
            receipt.get("failure") is not None
            or not isinstance(trace, dict)
            or trace.get("replay_verified") is not True
            or score.get("verified") is not True
            or score.get("official_run_game_id") != specification.get("game_id")
            or receipt.get("environment_transport") != specification.get("network_mode")
        ):
            return False
    elif not isinstance(receipt.get("failure"), dict):
        return False
    return bool(
        receipt.get("schema") == PUBLIC_RUN_SCHEMA
        and verify_object_hash(receipt, hash_field="receipt_hash")
        and receipt.get("identity_hash") == identity_hash
        and receipt.get("surface") == specification.get("surface")
    )


def _preserve(path: Path, failures: Path) -> None:
    if not path.exists():
        return
    failures.mkdir(parents=True, exist_ok=True)
    path.replace(failures / f"{path.stem}.invalid-{uuid.uuid4().hex}{path.suffix}")


def _aggregate(results: list[dict[str, Any]], *, partition: str) -> dict[str, object]:
    policies: dict[str, dict[str, object]] = {}
    failures = 0
    for result in results:
        agent = str(result["agent"])
        row = policies.setdefault(
            agent,
            {
                "baseline_id": result["baseline_id"],
                "runs": 0,
                "successes": 0,
                "failures": 0,
                "score_sum": 0.0,
                "levels_completed": 0,
                "completed_runs": 0,
                "environment_actions": 0,
                "resets": 0,
                "faults": 0,
            },
        )
        row["runs"] = int(cast(int, row["runs"])) + 1
        if result["status"] == "success":
            row["successes"] = int(cast(int, row["successes"])) + 1
        else:
            row["failures"] = int(cast(int, row["failures"])) + 1
            failures += 1
        score = cast(dict[str, object], result["score"])
        metrics = cast(dict[str, object], result["metrics"])
        row["score_sum"] = float(cast(float, row["score_sum"])) + _as_float(
            score["score"], field="score"
        )
        row["levels_completed"] = int(cast(int, row["levels_completed"])) + _as_int(
            score["levels_completed"], field="levels_completed"
        )
        row["completed_runs"] = int(cast(int, row["completed_runs"])) + int(
            bool(score["completed"])
        )
        row["environment_actions"] = int(cast(int, row["environment_actions"])) + _as_int(
            metrics["environment_actions"], field="environment_actions"
        )
        row["resets"] = int(cast(int, row["resets"])) + _as_int(metrics["resets"], field="resets")
        row["faults"] = int(cast(int, row["faults"])) + _as_int(
            metrics.get("fault_count", 0), field="fault_count"
        )
    for row in policies.values():
        runs = int(cast(int, row["runs"]))
        row["mean_score"] = float(cast(float, row.pop("score_sum"))) / runs if runs else 0.0

    claim = "MECHANISM_NOT_OBSERVED"
    full = policies.get("full")
    baselines = [row for agent, row in policies.items() if agent != "full"]
    if failures == 0 and full is not None and baselines:
        full_rank = (
            int(cast(int, full["levels_completed"])),
            float(cast(float, full["mean_score"])),
            -int(cast(int, full["environment_actions"])),
        )
        best_baseline = max(
            (
                int(cast(int, row["levels_completed"])),
                float(cast(float, row["mean_score"])),
                -int(cast(int, row["environment_actions"])),
            )
            for row in baselines
        )
        full_has_positive_progress = (
            int(cast(int, full["levels_completed"])) > 0
            or float(cast(float, full["mean_score"])) > 0.0
        )
        if full_has_positive_progress and full_rank > best_baseline:
            claim = (
                "PUBLIC_HOLDOUT_IMPROVEMENT"
                if partition == "public-holdout"
                else "LOCAL_PUBLIC_IMPROVEMENT"
            )
    status = (
        "PASS"
        if failures == 0
        else "PARTIAL"
        if failures < len(results)
        else "FAILED_INFRASTRUCTURE"
    )
    return {
        "schema": "arc3.public-evaluation.summary.v0.1",
        "status": status,
        "claim": claim,
        "claim_boundary": "NO_GENERALIZATION_CLAIM",
        "result_count": len(results),
        "failure_count": failures,
        "policies": {agent: policies[agent] for agent in sorted(policies)},
    }


def _render_report(
    manifest: dict[str, Any], summary: dict[str, object], results: list[dict[str, Any]]
) -> str:
    lines = [
        "# ARC3 Stage 15 public evaluation",
        "",
        f"- Status: **{summary['status']}**",
        f"- Claim: **{summary['claim']}**",
        "- Claim boundary: **NO_GENERALIZATION_CLAIM**",
        f"- Surface: `{manifest['surface']}`",
        f"- Partition: `{manifest['partition']}`",
        f"- Frozen commit: `{manifest['git_commit']}`",
        f"- Manifest: `{manifest['public_partition_manifest_hash']}`",
        f"- Network during evaluation: `{manifest['network_mode']}`",
        "",
        "| policy | game | seed | status | levels | score | actions | resets | faults |",
        "|---|---|---:|---|---:|---:|---:|---:|---:|",
    ]
    for result in results:
        score = cast(dict[str, object], result["score"])
        metrics = cast(dict[str, object], result["metrics"])
        lines.append(
            "| {agent} | {game} | {seed} | {status} | {levels} | {score} | "
            "{actions} | {resets} | {faults} |".format(
                agent=result["agent"],
                game=result["game_id"],
                seed=result["seed"],
                status=result["status"],
                levels=score["levels_completed"],
                score=score["score"],
                actions=metrics["environment_actions"],
                resets=metrics["resets"],
                faults=metrics.get("fault_count", 0),
            )
        )
    lines.extend(
        [
            "",
            f"This is a measured `{manifest['surface']}` result from the pinned official scorer. ",
            "It is not hidden-game evidence and does not establish general intelligence.",
            "",
        ]
    )
    return "\n".join(lines)


def _shell_command(argv: list[str]) -> str:
    return subprocess.list2cmdline(argv) if os.name == "nt" else shlex.join(argv)


def _reproduction_argv(config: PublicEvaluationConfig) -> list[str]:
    argv = [
        sys.executable,
        "-m",
        "scripts.evaluate_public",
        "--partition",
        config.partition,
        "--agents",
        ",".join(config.agents),
        "--seeds",
        ",".join(str(seed) for seed in config.seeds),
        "--max-actions",
        str(config.max_actions),
        "--max-resets",
        str(config.max_resets),
        "--timeout-seconds",
        str(config.timeout_seconds),
        "--frozen-commit",
        config.frozen_commit,
        "--manifest",
        str(config.manifest_path.resolve()),
        "--environments-dir",
        str(config.environments_dir.resolve()),
        "--recordings-dir",
        str(config.recordings_dir.resolve()),
        "--output-root",
        str(config.output_root.resolve()),
        "--exposure-ledger",
        str(config.exposure_ledger.resolve()),
        "--milestone-id",
        config.milestone_id,
    ]
    if config.game_ids is not None:
        argv.extend(["--game-ids", ",".join(config.game_ids)])
    if config.evaluation_id is not None:
        argv.extend(["--evaluation-id", config.evaluation_id])
    if config.acquire_missing:
        argv.append("--acquire-missing")
    if config.allow_public_holdout:
        argv.append("--allow-public-holdout")
    if config.sealed_development_manifest is not None:
        argv.extend(
            ["--sealed-development-manifest", str(config.sealed_development_manifest.resolve())]
        )
    return argv


def verify_public_evaluation(directory: str | Path) -> dict[str, object]:
    root = Path(directory).resolve()
    errors: list[str] = []
    try:
        manifest = load_json(root / "manifest.json")
    except (OSError, EvaluationError, json.JSONDecodeError) as error:
        return {"verified": False, "errors": [f"manifest unreadable: {type(error).__name__}"]}
    if manifest.get("schema") != PUBLIC_EVALUATION_SCHEMA:
        errors.append("manifest schema mismatch")
    if not verify_object_hash(manifest, hash_field="manifest_hash"):
        errors.append("manifest self-hash mismatch")
    hashes = manifest.get("artifact_hashes")
    if not isinstance(hashes, dict):
        errors.append("manifest artifact_hashes is invalid")
        hashes = {}
    required = manifest.get("required_artifacts")
    if not isinstance(required, list) or any(not isinstance(item, str) for item in required):
        errors.append("manifest required_artifacts is invalid")
        required = []
    elif len(required) != len(set(required)):
        errors.append("manifest required_artifacts contains duplicates")
    for relative in sorted(cast(list[str], required)):
        if relative not in hashes:
            errors.append(f"required artifact is not hash-bound: {relative}")
    for relative, expected in sorted(hashes.items()):
        if not isinstance(relative, str) or not isinstance(expected, str):
            errors.append("manifest artifact hash entry is invalid")
            continue
        candidate = (root / relative).resolve()
        try:
            candidate.relative_to(root)
        except ValueError:
            errors.append(f"artifact path escapes evaluation: {relative}")
            continue
        if not candidate.is_file():
            errors.append(f"artifact is missing: {relative}")
        elif sha256_file(candidate) != expected:
            errors.append(f"artifact hash mismatch: {relative}")
    actual_artifacts = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() and path.relative_to(root).as_posix() != "manifest.json"
    }
    declared_artifacts = {relative for relative in hashes if isinstance(relative, str)}
    for relative in sorted(actual_artifacts - declared_artifacts):
        errors.append(f"artifact is not hash-bound: {relative}")
    for relative in sorted(declared_artifacts - actual_artifacts):
        if f"artifact is missing: {relative}" not in errors:
            errors.append(f"artifact is missing: {relative}")
    expected_runs = manifest.get("expected_runs")
    if not isinstance(expected_runs, list):
        errors.append("manifest expected_runs is invalid")
        expected_runs = []
    results: list[dict[str, Any]] = []
    run_ids: set[str] = set()
    for raw_specification in expected_runs:
        if not isinstance(raw_specification, dict):
            errors.append("run specification is not an object")
            continue
        specification = cast(dict[str, object], raw_specification)
        run_id_value = specification.get("run_id")
        if (
            not isinstance(run_id_value, str)
            or not run_id_value
            or any(
                character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_"
                for character in run_id_value
            )
        ):
            errors.append("run specification has an invalid run ID")
            continue
        if run_id_value in run_ids:
            errors.append(f"run specification is duplicated: {run_id_value}")
            continue
        run_ids.add(run_id_value)
        path = root / "runs" / f"{run_id_value}.json"
        try:
            receipt = load_json(path)
        except (OSError, EvaluationError, json.JSONDecodeError):
            errors.append(f"run receipt unreadable: {specification.get('run_id')}")
            continue
        if not _receipt_valid(receipt, specification, manifest.get("identity_hash")):
            errors.append(f"run receipt identity mismatch: {specification.get('run_id')}")
        results.append(receipt)
    canonical_required = {
        "results.jsonl",
        "summary.json",
        "report.md",
        "reproduce.json",
        "reproduce.txt",
        *(f"runs/{run_id}.json" for run_id in run_ids),
    }
    for relative in sorted(canonical_required - set(cast(list[str], required))):
        errors.append(f"canonical required artifact is undeclared: {relative}")
    results_path = root / "results.jsonl"
    if results_path.is_file():
        expected_bytes = b"".join(
            canonical_json_bytes(result)
            for result in sorted(results, key=lambda item: str(item["run_id"]))
        )
        if results_path.read_bytes() != expected_bytes:
            errors.append("results.jsonl does not exactly match run receipts")
    else:
        errors.append("results.jsonl is missing")
    try:
        summary = load_json(root / "summary.json")
    except (OSError, EvaluationError, json.JSONDecodeError):
        errors.append("summary.json is unreadable")
    else:
        partition = manifest.get("partition")
        if not isinstance(partition, str):
            errors.append("manifest partition is invalid")
        else:
            try:
                expected_summary = _aggregate(results, partition=partition)
            except (EvaluationError, KeyError, TypeError, ValueError):
                errors.append("run receipts cannot be aggregated")
            else:
                expected_summary["evaluation_id"] = manifest.get("evaluation_id")
                expected_summary["surface"] = manifest.get("surface")
                expected_summary["partition"] = partition
                if summary != expected_summary:
                    errors.append("summary.json does not exactly match run receipts")
                if manifest.get("status") != summary.get("status"):
                    errors.append("manifest status does not match summary status")
    return {
        "schema": "arc3.public-evaluation.verification.v0.1",
        "verified": not errors,
        "errors": errors,
        "evaluation_id": manifest.get("evaluation_id"),
        "artifact_count": len(hashes),
        "run_count": len(results),
    }


def _terminal_outcome(directory: Path, manifest: dict[str, Any]) -> EvaluationOutcome:
    verification = verify_public_evaluation(directory)
    if not verification["verified"]:
        raise EvaluationError(
            "refusing to reuse a tampered terminal public evaluation: "
            + "; ".join(str(item) for item in cast(list[object], verification["errors"]))
        )
    summary = load_json(directory / "summary.json")
    return EvaluationOutcome(
        str(manifest["evaluation_id"]), directory, str(manifest["status"]), summary
    )


def _validate_terminal_identity(
    previous: dict[str, Any],
    config: PublicEvaluationConfig,
    manifest: PublicPartitionManifest,
) -> None:
    """Refuse to alias a terminal directory to a different declaration."""

    expected = {
        "agent_config": config.declaration(),
        "git_commit": config.frozen_commit,
        "partition": config.partition,
        "public_partition_manifest_hash": manifest.digest,
    }
    for field, value in expected.items():
        if previous.get(field) != value:
            raise EvaluationError(
                f"terminal public evaluation {field} does not match the requested declaration"
            )


def _acquire_missing_assets(
    config: PublicEvaluationConfig,
    manifest: PublicPartitionManifest,
    ledger: PublicExposureLedger,
    directory: Path,
    assets: dict[str, LocalAssetIdentity],
) -> dict[str, LocalAssetIdentity]:
    selected = config.selected_games(manifest)
    missing = [entry for entry in selected if entry.game_id not in assets]
    if not missing:
        return assets
    if not config.acquire_missing:
        raise EvaluationError(
            "official local assets are missing: " + ", ".join(entry.game_id for entry in missing)
        )
    if config.partition == "public-holdout":
        raise EvaluationError("holdout assets cannot be acquired inside the one-shot evaluation")
    acquisitions = directory / "acquisitions"
    acquisitions.mkdir(parents=True, exist_ok=True)
    for entry in missing:
        ledger.append(
            "game.asset_acquisition_started",
            {
                "evaluation_id": directory.name,
                "milestone_id": config.milestone_id,
                "partition": config.partition,
                "game_id": entry.game_id,
                "seed": config.seeds[0],
                "surface": config.surface,
                "gameplay_exposure": True,
            },
        )
        started_at = _utc_now()
        attempt_id = "".join(character for character in started_at if character.isalnum())
        receipt_path = acquisitions / f"{entry.assignment_hash[:16]}-{attempt_id}.json"
        try:
            acquire_local_public_asset(
                entry.game_id,
                seed=config.seeds[0],
                environments_dir=config.environments_dir,
                recordings_dir=config.recordings_dir,
            )
            refreshed = inventory_local_assets(manifest, config.environments_dir)
            identity = refreshed.get(entry.game_id)
            if identity is None:
                raise EvaluationError("acquired game is absent from the official local inventory")
            receipt = seal_object(
                {
                    "schema": "arc3.public-asset-acquisition.v0.1",
                    "status": "PASS",
                    "surface": "local-public",
                    "game_id": entry.game_id,
                    "partition": config.partition,
                    "started_at": started_at,
                    "completed_at": _utc_now(),
                    "network_used_for_acquisition": True,
                    "evaluation_network_mode": "offline",
                    "asset_identity": identity.to_dict(),
                },
                hash_field="receipt_hash",
            )
            atomic_write_json(receipt_path, receipt)
            ledger.append(
                "game.asset_acquired_and_opened",
                {
                    "evaluation_id": directory.name,
                    "milestone_id": config.milestone_id,
                    "partition": config.partition,
                    "game_id": entry.game_id,
                    "surface": "local-public",
                    "asset_sha256": identity.aggregate_sha256,
                    "gameplay_exposure": True,
                },
            )
            assets = refreshed
        except Exception as error:
            failure = seal_object(
                {
                    "schema": "arc3.public-asset-acquisition.v0.1",
                    "status": "BLOCKED_EXTERNAL",
                    "surface": "local-public",
                    "game_id": entry.game_id,
                    "partition": config.partition,
                    "started_at": started_at,
                    "completed_at": _utc_now(),
                    "failure": {
                        "kind": type(error).__name__,
                        "message": str(error)[:500],
                    },
                },
                hash_field="receipt_hash",
            )
            atomic_write_json(receipt_path, failure)
            ledger.append(
                "game.asset_acquisition_failed",
                {
                    "evaluation_id": directory.name,
                    "milestone_id": config.milestone_id,
                    "partition": config.partition,
                    "game_id": entry.game_id,
                    "surface": "local-public",
                    "failure_kind": type(error).__name__,
                    "gameplay_exposure": True,
                },
            )
            raise EvaluationError(
                f"official asset acquisition failed for {entry.game_id}: {type(error).__name__}"
            ) from None
    return assets


def run_public_evaluation(config: PublicEvaluationConfig) -> EvaluationOutcome:
    """Run or validate a frozen, process-isolated official public comparison."""

    manifest = PublicPartitionManifest.load(config.manifest_path)
    ledger = PublicExposureLedger(config.exposure_ledger)
    started_at = _utc_now()
    evaluation_id = _evaluation_id(config, started_at)
    directory = (config.output_root / evaluation_id).resolve()
    manifest_path = directory / "manifest.json"
    previous: dict[str, Any] | None = None
    if manifest_path.is_file():
        previous = load_json(manifest_path)
        if not verify_object_hash(previous, hash_field="manifest_hash"):
            raise EvaluationError("public evaluation manifest self-hash mismatch")
        if previous.get("status") in _TERMINAL_STATUSES:
            validate_frozen_source(config.frozen_commit)
            _validate_terminal_identity(previous, config, manifest)
            return _terminal_outcome(directory, previous)
        if previous.get("status") != "IN_PROGRESS":
            raise EvaluationError("public evaluation manifest is not resumable")
        original = previous.get("started_at")
        if isinstance(original, str):
            started_at = original
    elif directory.exists() and any(directory.iterdir()):
        entries = list(directory.iterdir())
        if any(entry.name != "acquisitions" for entry in entries):
            raise EvaluationError("public evaluation directory has artifacts but no manifest")
    validate_public_gate(
        config,
        manifest,
        ledger,
        resume_evaluation_id=evaluation_id if previous is not None else None,
    )
    directory.mkdir(parents=True, exist_ok=True)
    assets = inventory_local_assets(manifest, config.environments_dir)
    selected_ids = {entry.game_id for entry in config.selected_games(manifest)}
    if config.partition == "public-holdout":
        # Holdout acquisition and evaluation are deliberately inseparable.  A
        # content identity is recorded after each one-shot NORMAL-mode run.
        selected_assets: dict[str, LocalAssetIdentity] = {}
    else:
        assets = _acquire_missing_assets(config, manifest, ledger, directory, assets)
        missing = selected_ids - set(assets)
        if missing:
            raise EvaluationError(
                f"official local asset inventory remains incomplete: {sorted(missing)}"
            )
        selected_assets = {game_id: assets[game_id] for game_id in sorted(selected_ids)}
    identity = _identity(config, manifest, selected_assets)
    specifications = _specifications(evaluation_id, config, manifest, identity)
    if manifest_path.is_file():
        previous = load_json(manifest_path)
        if previous.get("identity_hash") != identity["identity_hash"]:
            raise EvaluationError("cannot resume public evaluation under a changed identity")
        if previous.get("expected_runs") != specifications:
            raise EvaluationError("cannot resume public evaluation under a changed declaration")

    runs = directory / "runs"
    failures = directory / "failures"
    traces = directory / "t"
    checkpoints = directory / "c"
    official_recordings = directory / "official-recordings"
    for path in (runs, failures, traces, checkpoints, official_recordings):
        path.mkdir(parents=True, exist_ok=True)
    required = sorted(
        {
            "results.jsonl",
            "summary.json",
            "report.md",
            "reproduce.json",
            "reproduce.txt",
            *(f"runs/{specification['run_id']}.json" for specification in specifications),
        }
    )
    manifest_object: dict[str, Any] = {
        "schema": PUBLIC_EVALUATION_SCHEMA,
        "evaluation_id": evaluation_id,
        "status": "IN_PROGRESS",
        "surface": config.surface,
        "verified": True,
        "verified_meaning": (
            "pinned official ONLINE scorecard"
            if config.surface == "online-public"
            else "pinned official local ScorecardManager"
        ),
        "partition": config.partition,
        "public_game_derived_memory_or_tuning": config.partition == "development",
        "holdout_consumed": config.partition == "public-holdout",
        "aggregate": True,
        **identity,
        "started_at": started_at,
        "completed_at": None,
        "expected_runs": specifications,
        "required_artifacts": required,
        "artifact_hashes": {},
        "process_isolation": "multiprocessing-spawn",
        "exposure_ledger_path": str(config.exposure_ledger.resolve()),
        "exposure_ledger_sha256_before": (
            sha256_file(config.exposure_ledger) if config.exposure_ledger.is_file() else None
        ),
    }
    atomic_write_json(manifest_path, seal_object(manifest_object, hash_field="manifest_hash"))
    context = multiprocessing.get_context("spawn")
    prior_events = ledger.events()
    prior_starts = {
        str(payload.get("run_id"))
        for event in prior_events
        if event.get("event_type") == "game.evaluation_started"
        and isinstance((payload := event.get("payload")), dict)
        and payload.get("evaluation_id") == evaluation_id
    }
    prior_completions = {
        str(payload.get("run_id"))
        for event in prior_events
        if event.get("event_type") == "game.evaluation_completed"
        and isinstance((payload := event.get("payload")), dict)
        and payload.get("evaluation_id") == evaluation_id
    }
    for specification in specifications:
        run_id = str(specification["run_id"])
        receipt_path = runs / f"{run_id}.json"
        failure_path = failures / f"{run_id}.json"
        if receipt_path.is_file():
            try:
                existing = load_json(receipt_path)
            except (OSError, EvaluationError, json.JSONDecodeError):
                _preserve(receipt_path, failures)
            else:
                if _receipt_valid(existing, specification, identity["identity_hash"]):
                    if run_id not in prior_completions:
                        ledger.append(
                            "game.evaluation_completed",
                            {
                                "evaluation_id": evaluation_id,
                                "run_id": run_id,
                                "milestone_id": config.milestone_id,
                                "partition": config.partition,
                                "game_id": specification["game_id"],
                                "agent": specification["agent"],
                                "seed": specification["seed"],
                                "surface": config.surface,
                                "status": existing["status"],
                                "receipt_hash": existing["receipt_hash"],
                                "recovered_after_interruption": True,
                            },
                        )
                        prior_completions.add(run_id)
                    continue
                _preserve(receipt_path, failures)
        if config.partition == "public-holdout" and run_id in prior_starts:
            moment = _utc_now()
            result = _failure_result(
                specification,
                identity,
                started_at=moment,
                status="interrupted",
                kind="holdout_run_already_opened",
                message="holdout run had an exposure receipt but no valid terminal run receipt",
                asset_identity_after=_holdout_asset_after(
                    manifest, config, str(specification["game_id"])
                ),
            )
            atomic_write_json(receipt_path, result)
            atomic_write_json(failure_path, result)
            ledger.append(
                "game.evaluation_completed",
                {
                    "evaluation_id": evaluation_id,
                    "run_id": run_id,
                    "milestone_id": config.milestone_id,
                    "partition": config.partition,
                    "game_id": specification["game_id"],
                    "agent": specification["agent"],
                    "seed": specification["seed"],
                    "surface": config.surface,
                    "status": result["status"],
                    "receipt_hash": result["receipt_hash"],
                    "recovered_after_interruption": True,
                },
            )
            prior_completions.add(run_id)
            continue
        storage_key = _storage_key(run_id)
        trace_path = traces / storage_key
        checkpoint_path = checkpoints / storage_key
        if trace_path.exists():
            trace_path.replace(failures / f"trace-{storage_key}-{uuid.uuid4().hex}")
        if checkpoint_path.exists():
            checkpoint_path.replace(failures / f"checkpoint-{storage_key}-{uuid.uuid4().hex}")
        ledger.append(
            "game.evaluation_started",
            {
                "evaluation_id": evaluation_id,
                "run_id": run_id,
                "milestone_id": config.milestone_id,
                "partition": config.partition,
                "game_id": specification["game_id"],
                "agent": specification["agent"],
                "seed": specification["seed"],
                "surface": config.surface,
                "gameplay_exposure": True,
            },
        )
        worker_spec = {
            "identity": identity,
            "specification": specification,
            "trace_path": str(_runtime_path(trace_path)),
            "trace_relative": f"t/{storage_key}",
            "checkpoint_path": str(_runtime_path(checkpoint_path)),
            "environments_dir": str(config.environments_dir.resolve()),
            "recordings_dir": str(_runtime_path(official_recordings)),
            "timeout_seconds": config.timeout_seconds,
            "max_actions": config.max_actions,
            "max_resets": config.max_resets,
            "seed": specification["seed"],
            "run_id": run_id,
            "game_id": specification["game_id"],
            "git_commit": config.frozen_commit,
        }
        launched = _utc_now()
        timer = time.perf_counter()
        process = context.Process(target=_worker, args=(worker_spec, str(receipt_path)))
        try:
            process.start()
            process.join(config.timeout_seconds)
            if process.is_alive():
                process.terminate()
                process.join(5)
                if process.is_alive():
                    process.kill()
                    process.join(5)
                trace, metrics = _salvage_trace(
                    trace_path,
                    run_id=run_id,
                    relative_path=f"t/{storage_key}",
                    elapsed_seconds=time.perf_counter() - timer,
                )
                result = _failure_result(
                    specification,
                    identity,
                    started_at=launched,
                    status="timeout",
                    kind="wall_clock_timeout",
                    message=f"worker exceeded {config.timeout_seconds} seconds",
                    metrics=metrics,
                    trace=trace,
                    asset_identity_after=_holdout_asset_after(
                        manifest, config, str(specification["game_id"])
                    ),
                )
                atomic_write_json(receipt_path, result)
            elif process.exitcode != 0 or not receipt_path.is_file():
                trace, metrics = _salvage_trace(
                    trace_path,
                    run_id=run_id,
                    relative_path=f"t/{storage_key}",
                    elapsed_seconds=time.perf_counter() - timer,
                )
                result = _failure_result(
                    specification,
                    identity,
                    started_at=launched,
                    status="crash",
                    kind="abnormal_process_exit",
                    message=f"isolated worker exited with code {process.exitcode}",
                    metrics=metrics,
                    trace=trace,
                    asset_identity_after=_holdout_asset_after(
                        manifest, config, str(specification["game_id"])
                    ),
                )
                atomic_write_json(receipt_path, result)
        except (OSError, RuntimeError) as error:
            metrics = _empty_metrics()
            metrics["total_wall_clock_seconds"] = time.perf_counter() - timer
            result = _failure_result(
                specification,
                identity,
                started_at=launched,
                status="failure",
                kind="process_start_failed",
                message=f"{type(error).__name__}: {error}",
                metrics=metrics,
                asset_identity_after=_holdout_asset_after(
                    manifest, config, str(specification["game_id"])
                ),
            )
            atomic_write_json(receipt_path, result)
        try:
            result = load_json(receipt_path)
        except (OSError, EvaluationError, json.JSONDecodeError):
            trace, metrics = _salvage_trace(
                trace_path,
                run_id=run_id,
                relative_path=f"t/{storage_key}",
                elapsed_seconds=time.perf_counter() - timer,
            )
            result = _failure_result(
                specification,
                identity,
                started_at=launched,
                status="failure",
                kind="invalid_worker_receipt",
                message="worker receipt could not be loaded",
                metrics=metrics,
                trace=trace,
                asset_identity_after=_holdout_asset_after(
                    manifest, config, str(specification["game_id"])
                ),
            )
            atomic_write_json(receipt_path, result)
        if not _receipt_valid(result, specification, identity["identity_hash"]):
            _preserve(receipt_path, failures)
            trace, metrics = _salvage_trace(
                trace_path,
                run_id=run_id,
                relative_path=f"t/{storage_key}",
                elapsed_seconds=time.perf_counter() - timer,
            )
            result = _failure_result(
                specification,
                identity,
                started_at=launched,
                status="failure",
                kind="worker_receipt_identity_mismatch",
                message="worker receipt failed its hash or frozen run identity",
                metrics=metrics,
                trace=trace,
                asset_identity_after=_holdout_asset_after(
                    manifest, config, str(specification["game_id"])
                ),
            )
            atomic_write_json(receipt_path, result)
        if result["status"] != "success":
            atomic_write_json(failure_path, result)
        ledger.append(
            "game.evaluation_completed",
            {
                "evaluation_id": evaluation_id,
                "run_id": run_id,
                "milestone_id": config.milestone_id,
                "partition": config.partition,
                "game_id": specification["game_id"],
                "agent": specification["agent"],
                "seed": specification["seed"],
                "surface": config.surface,
                "status": result["status"],
                "receipt_hash": result["receipt_hash"],
                "asset_sha256_after": (
                    asset.get("aggregate_sha256")
                    if isinstance((asset := result.get("asset_identity_after")), dict)
                    else None
                ),
            },
        )

    results = [
        load_json(runs / f"{specification['run_id']}.json") for specification in specifications
    ]
    results.sort(key=lambda result: str(result["run_id"]))
    atomic_write_bytes(
        directory / "results.jsonl",
        b"".join(canonical_json_bytes(result) for result in results),
    )
    summary = _aggregate(results, partition=config.partition)
    summary["evaluation_id"] = evaluation_id
    summary["surface"] = config.surface
    summary["partition"] = config.partition
    atomic_write_json(directory / "summary.json", summary)
    argv = _reproduction_argv(config)
    atomic_write_json(
        directory / "reproduce.json",
        {
            "schema": "arc3.public-evaluation.reproduction.v0.1",
            "argv": argv,
            "working_directory": str(Path(__file__).resolve().parents[3]),
            "holdout_warning": (
                "The exposure ledger intentionally prevents reopening a consumed holdout."
                if config.partition == "public-holdout"
                else None
            ),
        },
    )
    atomic_write_text(directory / "reproduce.txt", _shell_command(argv) + "\n")
    manifest_object["status"] = summary["status"]
    manifest_object["completed_at"] = _utc_now()
    manifest_object["exposure_ledger_sha256_after"] = sha256_file(config.exposure_ledger)
    if config.partition == "public-holdout":
        final_assets = inventory_local_assets(manifest, config.environments_dir)
        manifest_object["asset_identities_after"] = {
            game_id: final_assets[game_id].to_dict()
            for game_id in sorted(selected_ids & set(final_assets))
        }
    atomic_write_text(directory / "report.md", _render_report(manifest_object, summary, results))
    artifact_paths = [
        path
        for path in directory.rglob("*")
        if path.is_file() and path.relative_to(directory).as_posix() != "manifest.json"
    ]
    manifest_object["artifact_hashes"] = {
        path.relative_to(directory).as_posix(): sha256_file(path) for path in artifact_paths
    }
    atomic_write_json(manifest_path, seal_object(manifest_object, hash_field="manifest_hash"))
    verification = verify_public_evaluation(directory)
    if not verification["verified"]:
        raise EvaluationError(
            "public evaluation artifact verification failed: "
            + "; ".join(str(item) for item in cast(list[object], verification["errors"]))
        )
    return EvaluationOutcome(evaluation_id, directory, str(summary["status"]), summary)


__all__ = ["run_public_evaluation", "verify_public_evaluation"]
