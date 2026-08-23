"""Stage 09 parent-supervisor boundary tests without public gameplay."""

from __future__ import annotations

import argparse
import base64
import copy
import hashlib
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, NoReturn, cast

import pytest
import scripts._stage09_development_worker as worker
import scripts._stage09_supervisor_bootstrap as bootstrap
import scripts.measure_development_recovery as harness
from tests.unit.test_development_recovery import _boundaries

from arc3.errors import EvaluationError
from arc3.evaluation.artifacts import (
    canonical_json_bytes,
    load_json,
    seal_object,
    sha256_bytes,
    sha256_file,
    verify_object_hash,
)
from arc3.evaluation.development_recovery import (
    CELL_RECEIPT_SCHEMA,
    PREFLIGHT_SCHEMA,
    WORKER_SPEC_SCHEMA,
    CellStatus,
    DevelopmentCell,
    Variant,
    aggregate,
    build_matrix,
)
from arc3.evaluation.public import PUBLIC_RUN_SCHEMA, PublicExposureLedger
from arc3.evaluation.public_runner import _asset_identity_check
from arc3.integrity import IntegrityReceipt

PACKAGE_ONLY_RECEIPT = Path(
    "C:/a/arc3-b001/artifacts/stage09/policy-integrity-d6d4bac-package-only.json"
)
PACKAGE_ONLY_SOURCE = Path("C:/a/arc3-stage09-build001-d6d4bac")


def _execution_identity() -> dict[str, object]:
    return _boundaries()


def test_integrity_authority_uses_the_integrity_receipt_hash_contract(tmp_path: Path) -> None:
    commit = "a" * 40
    body: dict[str, Any] = {
        "schema": "arc3.integrity.receipt.v0.2",
        "checks": {
            name: {"passed": True}
            for name in (
                "archive_static",
                "policy_static",
                "secret_scan",
                "source_identity",
                "supply_chain",
            )
        },
        "finding_counts": {"blocking": 0, "total": 0, "warnings": 0},
        "git": {"commit": commit, "dirty_worktree": False},
        "inputs": {"manifest_sha256": harness.PUBLIC_PARTITION_MANIFEST_SHA256},
        "passed": True,
    }
    receipt = IntegrityReceipt(body=body)
    path = tmp_path / "integrity.json"
    path.write_bytes(receipt.canonical_bytes())

    projection, predicates = harness._integrity_authority(
        path,
        expected_file_hash=sha256_file(path),
        expected_self_hash=receipt.receipt_sha256,
        expected_commit=commit,
    )

    assert all(predicates.values())
    assert projection["receipt_sha256"] == receipt.receipt_sha256


@pytest.mark.skipif(
    not PACKAGE_ONLY_RECEIPT.is_file() or not PACKAGE_ONLY_SOURCE.is_dir(),
    reason="exact detached d6d4 package authority is not installed",
)
def test_exact_package_only_authority_recomputes_live_reachable_closure() -> None:
    projection, predicates = harness._package_integrity_authority(
        PACKAGE_ONLY_RECEIPT,
        source_root=PACKAGE_ONLY_SOURCE,
        expected_file_hash=harness.BUILD_001_PACKAGE_INTEGRITY_RECEIPT_SHA256,
        expected_self_hash=harness.BUILD_001_PACKAGE_INTEGRITY_SELF_HASH,
        expected_commit=harness.BUILD_001_PACKAGE_INTEGRITY_COMMIT,
    )

    assert all(predicates.values())
    assert projection["status"] == "PASS"
    assert projection["candidate_set_recomputed"] is True
    assert projection["reachable_paths_recomputed"] is True
    assert projection["live_source_hashes_match"] is True
    assert projection["reachable_file_count"] == 86


@pytest.mark.skipif(
    not PACKAGE_ONLY_RECEIPT.is_file() or not PACKAGE_ONLY_SOURCE.is_dir(),
    reason="exact detached d6d4 package authority is not installed",
)
def test_rehashed_package_receipt_cannot_override_live_source_hashes(tmp_path: Path) -> None:
    body = cast(dict[str, Any], load_json(PACKAGE_ONLY_RECEIPT))
    body.pop("receipt_sha256")
    reachable = cast(dict[str, object], body["reachable_policy_source_hashes"])
    first = sorted(reachable)[0]
    reachable[first] = "sha256:" + "f" * 64
    receipt = IntegrityReceipt(body=body)
    path = tmp_path / "tampered-package-only.json"
    path.write_bytes(receipt.canonical_bytes())

    projection, predicates = harness._package_integrity_authority(
        path,
        source_root=PACKAGE_ONLY_SOURCE,
        expected_file_hash=sha256_file(path),
        expected_self_hash=receipt.receipt_sha256,
        expected_commit=harness.BUILD_001_PACKAGE_INTEGRITY_COMMIT,
    )

    assert predicates["canonical_self_hash"] is True
    assert predicates["file_hash"] is True
    assert predicates["self_hash"] is True
    assert predicates["complete_reachable_coverage"] is False
    assert projection["live_source_hashes_match"] is False
    assert projection["status"] == "FAIL"


def _worker_identity_keywords() -> dict[str, object]:
    boundaries = _execution_identity()
    harness_source = cast(dict[str, object], boundaries["harness_source"])
    runtime_environment = cast(dict[str, object], boundaries["runtime_environment"])
    return {
        "harness_source_expected": harness_source["expected"],
        "harness_source_before": harness_source["before"],
        "runtime_environment_expected": runtime_environment["expected"],
        "runtime_environment_before": runtime_environment["before"],
    }


def _cell_identity_keywords() -> dict[str, object]:
    boundaries = _execution_identity()
    harness_source = cast(dict[str, object], boundaries["harness_source"])
    runtime_environment = cast(dict[str, object], boundaries["runtime_environment"])
    prior_authority = cast(dict[str, object], boundaries["prior_authority"])
    environment_cache = cast(dict[str, object], boundaries["environment_cache"])
    return {
        "harness_source_expected": harness_source["expected"],
        "harness_source_before": harness_source["before"],
        "harness_source_after": harness_source["after"],
        "runtime_environment_expected": runtime_environment["expected"],
        "runtime_environment_before": runtime_environment["before"],
        "runtime_environment_after": runtime_environment["after"],
        "prior_authority_before": prior_authority["before"],
        "prior_authority_after": prior_authority["after"],
        "environment_cache_before": environment_cache["before"],
        "environment_cache_after": environment_cache["after"],
    }


def _preflight_execution_identity() -> dict[str, object]:
    boundaries = _execution_identity()
    harness_source = cast(dict[str, object], boundaries["harness_source"])
    runtime_environment = cast(dict[str, object], boundaries["runtime_environment"])
    prior_authority = cast(dict[str, object], boundaries["prior_authority"])
    environment_cache = cast(dict[str, object], boundaries["environment_cache"])
    return {
        "harness_source": {
            "expected": harness_source["expected"],
            "start": harness_source["before"],
        },
        "runtime_environment": {
            "expected": runtime_environment["expected"],
            "start": runtime_environment["before"],
        },
        "prior_authority": prior_authority["before"],
        "environment_cache": {"start": environment_cache["before"]},
        "predeclaration_authority": harness._predeclaration_authority(),
    }


def _attach_fixture_clock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    check: dict[str, object],
) -> dict[str, object]:
    """Attach a deterministic boot-bound clock without querying host firmware state."""

    monkeypatch.setattr(harness, "_boot_identity", lambda: "fixture-boot")
    harness_source = cast(dict[str, object], check["harness_source"])
    expected = cast(dict[str, object], harness_source["expected"])
    return harness._attach_run_clock(
        check,
        work_root=tmp_path / "run-clock",
        harness_binding_hash=expected["binding_hash"],
    )


def _asset(cell: DevelopmentCell) -> dict[str, object]:
    return {
        "aggregate_sha256": cell.game.asset_sha256,
        "directory": "C:/fixture/asset",
        "file_count": 2,
        "files": [],
        "game_id": cell.game.game_id,
        "passed": True,
        "source_semantically_inspected": False,
    }


def _raw_receipt(
    spec: dict[str, Any], cell: DevelopmentCell, *, failure_kind: str | None = None
) -> dict[str, object]:
    public = cast(dict[str, Any], spec["public_worker_spec"])
    declaration = cast(dict[str, object], public["specification"])
    identity = cast(dict[str, object], public["identity"])
    success = failure_kind is None
    memory = {
        "current_rss_bytes": 1024,
        "peak_rss_bytes": 2048,
        "measurement_source": "fixture-kernel-rss",
        "reason": None,
    }
    metrics: dict[str, object] = {
        "environment_actions": 3,
        "resets": 0,
        "fault_count": 0 if success else 1,
        "total_cpu_seconds": 0.25,
        "process_memory_before": memory,
        "process_memory_after": memory,
        "peak_rss_bytes": 2048,
        "network_attempt_count": 0,
        "policy_close_status": "closed" if success else "failed:PolicyError",
        "session_close_status": "closed-by-episode-runner",
        "journal_close_status": "closed-by-policy",
    }
    diagnostics: dict[str, object] = {}
    for field, metric_field in (
        ("python_allocation_tracing", "python_allocation_tracing_enabled"),
        ("automatic_checkpointing", "automatic_checkpointing_enabled"),
    ):
        if field in declaration:
            diagnostics[field] = declaration[field]
            metrics[metric_field] = declaration[field]
    asset = _asset(cell)
    score = {
        "verified": success,
        "official_run_game_id": cell.game.game_id if success else None,
        "official_run_actions": 3 if success else None,
        "official_run_resets": 0 if success else None,
        "score": 0.0 if success else None,
        "levels_completed": 1 if success else 0,
        "completed": success,
    }
    counts = {
        "action.submitted": 3,
        "consequence.received": 3,
        "observation.received": 1,
    }
    trace = {
        "schema": "arc3.evaluation.trace-receipt.v0.1",
        "byte_length": 100,
        "consequence_count": 3,
        "environment_action_count": 3,
        "event_count": 7,
        "event_type_counts": counts,
        "path": public["trace_relative"],
        "replay_verified": True,
        "reset_count": 0,
        "run_id": public["run_id"],
        "submitted_action_count": 3,
        "tail_event_hash": "sha256:" + "a" * 64,
        "trace_manifest_hash": "sha256:" + "b" * 64,
    }
    payload = {
        "schema": PUBLIC_RUN_SCHEMA,
        "evaluation_id": declaration["evaluation_id"],
        "run_id": declaration["run_id"],
        "run_spec_hash": declaration["run_spec_hash"],
        "game_id": declaration["game_id"],
        "baseline_id": declaration["baseline_id"],
        "agent": declaration["agent"],
        "seed": declaration["seed"],
        "surface": declaration["surface"],
        "partition": declaration["partition"],
        **diagnostics,
        "status": "success" if success else "failure",
        "identity_hash": identity["identity_hash"],
        "score": score,
        "metrics": metrics,
        "trace": trace,
        "asset_identity_after": asset,
        "asset_identity_check": _asset_identity_check(declaration, asset),
        "environment_transport": declaration["network_mode"],
        "failure": None if success else {"kind": failure_kind, "message": "bounded failure"},
    }
    return seal_object(payload, hash_field="receipt_hash")


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_json_bytes(value))


def _materialize_cell_chain(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    failure_kind: str | None = None,
    boundary_drift: str | None = None,
) -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
    cell = build_matrix()[0]
    work_root = tmp_path / "work"
    recordings = tmp_path / "recordings"
    environments = tmp_path / "environments"
    runtime = {"cpu": "fixture", "cpu_count": 1, "executable": str(Path(sys.executable).resolve())}
    monkeypatch.setattr(harness, "_asset_identity", lambda _root, selected: _asset(selected))
    paths = harness._cell_paths(work_root, cell)
    spec = harness._worker_spec(
        cell,
        source_root=tmp_path / "build000",
        environments=environments,
        recordings=recordings,
        cell_root=paths["cell_root"],
        runtime_identity=runtime,
        **_worker_identity_keywords(),
    )
    public_spec = cast(dict[str, object], spec["public_worker_spec"])
    Path(cast(str, public_spec["trace_path"])).mkdir(parents=True, exist_ok=True)
    _write(paths["spec"], spec)
    check_payload = _preflight_execution_identity()
    check_payload["runtime_identity"] = runtime
    check = _attach_fixture_clock(tmp_path, monkeypatch, check_payload)
    cell_segment = harness._cell_segment_payload(
        cell=cell,
        check=check,
        boot_identity="fixture-boot",
        started_perf_counter_ns=0,
    )
    _write(paths["cell_segment"], cell_segment)
    exposure = tmp_path / "exposure.jsonl"
    event = harness._append_exposure(exposure, cell)
    token = "1" * 32
    spawn_intent = harness._spawn_intent_payload(
        cell=cell,
        paths=paths,
        spec=spec,
        launch_token=token,
    )
    _write(paths["spawn_intent"], spawn_intent)
    command = harness._worker_command(
        paths["spec"],
        paths["raw"],
        launch_path=paths["launch"],
        authorization_path=paths["authorization"],
        abort_path=paths["abort"],
        launch_token=token,
    )
    context = {
        "cell_id": cell.cell_id,
        "cell_spec_hash": cell.spec_hash,
        "exposure_event_hash": event["event_hash"],
        "launch_token": token,
        "authorization_path": paths["authorization"].resolve().as_posix(),
        "abort_path": paths["abort"].resolve().as_posix(),
        "raw_path": paths["raw"].resolve().as_posix(),
        "stderr_path": paths["stderr"].resolve().as_posix(),
        "stdout_path": paths["stdout"].resolve().as_posix(),
        "worker_spec_hash": spec["worker_spec_hash"],
        "worker_spec_sha256": sha256_file(paths["spec"]),
    }
    launch = seal_object(
        {
            "schema": harness.LAUNCH_RECEIPT_SCHEMA,
            "cell_id": cell.cell_id,
            "cell_spec_hash": cell.spec_hash,
            "command": list(command),
            "command_sha256": sha256_bytes(canonical_json_bytes(list(command))),
            "cwd": harness.ROOT.resolve().as_posix(),
            "exposure_event_hash": event["event_hash"],
            "launch_token": token,
            "authorization_path": paths["authorization"].resolve().as_posix(),
            "launched_at_unix_ns": 1,
            "parent_pid": 1,
            "pid": 2,
            "process_creation_token": "fixture-process-token",
            "raw_path": paths["raw"].resolve().as_posix(),
            "stderr_path": paths["stderr"].resolve().as_posix(),
            "stdout_path": paths["stdout"].resolve().as_posix(),
            "worker_spec_hash": spec["worker_spec_hash"],
            "worker_spec_sha256": sha256_file(paths["spec"]),
        },
        hash_field="launch_receipt_hash",
    )
    _write(paths["launch"], launch)
    authorization = harness._authorization_payload(launch=launch, command=command, context=context)
    _write(paths["authorization"], authorization)
    raw = _raw_receipt(spec, cell, failure_kind=failure_kind)
    _write(paths["raw"], raw)
    monkeypatch.setattr(harness, "_trace_receipt", lambda *_args, **_kwargs: raw["trace"])
    harness_source = cast(dict[str, object], _execution_identity()["harness_source"])
    runtime_environment = cast(dict[str, object], _execution_identity()["runtime_environment"])
    expected_harness = cast(dict[str, object], harness_source["expected"])
    harness_before = cast(dict[str, object], harness_source["before"])
    expected_runtime = cast(dict[str, object], runtime_environment["expected"])
    runtime_before = cast(dict[str, object], runtime_environment["before"])
    identity_keywords = _cell_identity_keywords()
    if boundary_drift is not None:
        after_key = {
            "harness": "harness_source_after",
            "runtime": "runtime_environment_after",
            "prior": "prior_authority_after",
            "cache": "environment_cache_after",
        }[boundary_drift]
        changed = copy.deepcopy(cast(dict[str, object], identity_keywords[after_key]))
        predicates = cast(dict[str, object], changed["predicates"])
        if boundary_drift == "harness":
            files = cast(dict[str, object], changed["files"])
            files["scripts/measure_development_recovery.py"] = "sha256:" + "f" * 64
            predicates["files"] = False
            changed["passed"] = False
            changed = seal_object(changed, hash_field="observation_hash")
        elif boundary_drift == "runtime":
            actual = cast(dict[str, object], changed["actual"])
            versions = cast(dict[str, object], actual["critical_versions"])
            versions["numpy"] = "0.0.0"
            predicates["critical_versions"] = False
            changed["passed"] = False
            changed = seal_object(changed, hash_field="observation_hash")
        elif boundary_drift == "prior":
            predicates["build_001_package_integrity"] = False
            changed["passed"] = False
            changed = seal_object(changed, hash_field="authority_hash")
        else:
            actual = cast(dict[str, object], changed["actual"])
            actual["entry_count"] = cast(int, actual["entry_count"]) + 1
            predicates["entry_count"] = False
            changed["passed"] = False
            changed = seal_object(changed, hash_field="cache_identity_hash")
        identity_keywords[after_key] = changed
    harness_after = cast(dict[str, object], identity_keywords["harness_source_after"])
    runtime_after = cast(dict[str, object], identity_keywords["runtime_environment_after"])
    stdout = canonical_json_bytes(
        {
            "cell_id": cell.cell_id,
            "harness_binding_hash": expected_harness["binding_hash"],
            "harness_source_before_hash": harness_before["observation_hash"],
            "harness_source_after_hash": harness_after["observation_hash"],
            "raw_receipt_hash": raw["receipt_hash"],
            "runtime_binding_hash": expected_runtime["runtime_binding_hash"],
            "runtime_environment_before_hash": runtime_before["observation_hash"],
            "runtime_environment_after_hash": runtime_after["observation_hash"],
            "status": raw["status"],
        }
    )
    paths["stdout"].parent.mkdir(parents=True, exist_ok=True)
    paths["stdout"].write_bytes(stdout)
    paths["stderr"].write_bytes(b"")
    supervision = seal_object(
        {
            "schema": harness.SUPERVISION_RECEIPT_SCHEMA,
            "authorization_hash": authorization["authorization_hash"],
            "cleanup": {
                "active_processes_after": 0,
                "active_processes_before": 0,
                "assigned_before_resume": True,
                "authority": "windows-job-object-assigned-before-resume",
                "close_attempted": True,
                "close_error": None,
                "close_succeeded": True,
                "error": None,
                "limitation": None,
                "members_after": None,
                "members_before": None,
                "observation_error_before": None,
                "passed": True,
                "termination_attempted": False,
                "termination_error": None,
                "termination_succeeded": None,
                "verification_error": None,
            },
            "command": list(command),
            "containment": {
                "active_processes_after": 0,
                "assigned_before_resume": True,
                "authority": "windows-job-object-assigned-before-resume",
                "error": None,
                "limitation": None,
                "passed": True,
            },
            "launch_receipt_hash": launch["launch_receipt_hash"],
            "launch_error": None,
            "returncode": 0,
            "stderr_bytes": 0,
            "stderr_path": paths["stderr"].resolve().as_posix(),
            "stderr_sha256": sha256_bytes(b""),
            "stdout_bytes": len(stdout),
            "stdout_path": paths["stdout"].resolve().as_posix(),
            "stdout_sha256": sha256_bytes(stdout),
            "timed_out": False,
            "timeout_seconds": 120.0,
            "termination": None,
            "wall_ns": 10,
        },
        hash_field="supervision_receipt_hash",
    )
    _write(paths["supervision"], supervision)
    parent_evidence = harness._parent_evidence(
        cell,
        paths=paths,
        spec=spec,
        exposure_event=event,
        supervision=supervision,
        asset_after=_asset(cell),
        pre_receipt_active_wall_ns=20,
        **identity_keywords,
    )
    _write(paths["parent_evidence"], parent_evidence)
    receipt = harness._cell_receipt(
        cell,
        spec=spec,
        exposure_event=event,
        supervision=supervision,
        raw_path=paths["raw"],
        asset_after=_asset(cell),
        pre_receipt_active_wall_ns=20,
        spec_path=paths["spec"],
        launch_receipt_path=paths["launch"],
        authorization_path=paths["authorization"],
        supervision_receipt_path=paths["supervision"],
        parent_evidence_path=paths["parent_evidence"],
        **identity_keywords,
    )
    _write(paths["receipt"], receipt)
    finalization = harness._cell_finalization(
        cell,
        paths=paths,
        receipt=receipt,
        parent_evidence=parent_evidence,
        cell_segment=cell_segment,
        measured_active_wall_ns=21,
    )
    _write(paths["finalization"], finalization)
    return (
        receipt,
        event,
        {
            "check": check,
            "runtime": runtime,
            "work_root": work_root,
            "exposure": exposure,
            "finalization": finalization,
        },
    )


def test_exposure_ledger_accepts_only_exact_contiguous_matrix_prefix(tmp_path: Path) -> None:
    path = tmp_path / "exposure.jsonl"
    cell = build_matrix()[0]
    PublicExposureLedger(path).append(
        "stage09.development_episode_started",
        {
            "asset_sha256": cell.game.asset_sha256,
            "cell_id": cell.cell_id,
            "cell_spec_hash": cell.spec_hash,
            "game_id": cell.game.game_id,
            "partition": "development",
            "seed": cell.seed,
            "source_commit": cell.variant.source_commit,
            "variant": cell.variant.value,
        },
    )

    assert len(harness._validate_exposures(path)) == 1

    PublicExposureLedger(path).append(
        "stage09.development_episode_started",
        {
            "asset_sha256": cell.game.asset_sha256,
            "cell_id": "skipped-or-replayed-cell",
            "cell_spec_hash": cell.spec_hash,
            "game_id": cell.game.game_id,
            "partition": "development",
            "seed": cell.seed,
            "source_commit": cell.variant.source_commit,
            "variant": cell.variant.value,
        },
    )
    with pytest.raises(EvaluationError):
        harness._validate_exposures(path)


def test_worker_spec_binds_source_asset_and_public_worker_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cell = next(cell for cell in build_matrix() if cell.variant is Variant.BUILD_001_FULL)
    monkeypatch.setattr(harness, "_asset_identity", lambda _root, selected: _asset(selected))

    spec = harness._worker_spec(
        cell,
        source_root=tmp_path / "source",
        environments=tmp_path / "environments",
        recordings=tmp_path / "recordings",
        cell_root=tmp_path / "cell",
        runtime_identity={"cpu": "test", "cpu_count": 1},
        **_worker_identity_keywords(),
    )

    assert spec["schema"] == WORKER_SPEC_SCHEMA
    assert verify_object_hash(spec, hash_field="worker_spec_hash")
    assert spec["source_commit"] == cell.variant.source_commit
    public = spec["public_worker_spec"]
    assert public["specification"]["asset_aggregate_sha256_before"] == cell.game.asset_sha256
    assert public["specification"]["run_spec_hash"].startswith("sha256:")


@pytest.mark.parametrize(
    "stale_state",
    [
        "abort",
        "authorization",
        "cell_root",
        "finalization",
        "launch",
        "orphan",
        "parent_evidence",
        "receipt",
        "recording",
        "stream_directory",
        "supervision",
    ],
)
def test_unexposed_cell_rejects_every_attempt_state(tmp_path: Path, stale_state: str) -> None:
    cell = build_matrix()[0]
    recordings = tmp_path / "recordings"
    paths = harness._cell_paths(tmp_path / "work", cell)
    if stale_state == "recording":
        target = recordings / cell.cell_id
        target.mkdir(parents=True)
    elif stale_state == "stream_directory":
        target = paths["stdout"].parent
        target.mkdir(parents=True)
    elif stale_state == "cell_root":
        target = paths["cell_root"]
        target.mkdir(parents=True)
    else:
        target = paths[stale_state]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"stale")

    with pytest.raises(EvaluationError, match="already has execution evidence"):
        harness._assert_unexposed_cell_clean(
            paths=paths,
            recordings=recordings,
            cell=cell,
        )


def test_worker_command_preserves_lexical_symlinked_venv_launcher(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    interpreter_target = Path(sys.executable).resolve()
    launcher = tmp_path / "venv" / ("python.exe" if os.name == "nt" else "python")
    launcher.parent.mkdir(parents=True)
    try:
        launcher.symlink_to(Path(sys.executable))
    except OSError:
        pytest.skip("host does not permit a test interpreter symlink")
    monkeypatch.setattr(harness.sys, "executable", str(launcher))

    command = harness._worker_command(
        tmp_path / "spec.json",
        tmp_path / "raw.json",
        launch_path=tmp_path / "launch.json",
        authorization_path=tmp_path / "authorization.json",
        abort_path=tmp_path / "abort.json",
        launch_token="1" * 32,
    )

    assert Path(command[0]) == launcher.absolute()
    assert Path(command[0]).resolve() == interpreter_target


def test_parent_and_worker_commands_use_the_same_lexical_launcher(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    launcher = tmp_path / "venv" / ("python.exe" if os.name == "nt" else "python")
    monkeypatch.setattr(harness.sys, "executable", str(launcher))
    spec = tmp_path / "spec.json"
    raw = tmp_path / "raw.json"
    launch = tmp_path / "launch.json"
    authorization = tmp_path / "authorization.json"
    abort = tmp_path / "abort.json"
    token = "1" * 32
    args = argparse.Namespace(
        spec=spec,
        result=raw,
        launch_receipt=launch,
        authorization=authorization,
        abort_receipt=abort,
        launch_token=token,
    )

    parent_command = harness._worker_command(
        spec,
        raw,
        launch_path=launch,
        authorization_path=authorization,
        abort_path=abort,
        launch_token=token,
    )

    assert tuple(worker._expected_command(args)) == parent_command
    assert parent_command[0] == os.path.abspath(str(launcher))
    assert bootstrap._lexical_python_launcher() == parent_command[0]


def test_windows_process_table_ignores_unaddressable_system_idle_process() -> None:
    table = harness._parse_windows_process_table_rows(
        [
            {
                "command_line": "",
                "parent_pid": 0,
                "pid": 0,
                "process_creation_token": "windows-cim:0",
            },
            {
                "command_line": "fixture",
                "parent_pid": 0,
                "pid": 4,
                "process_creation_token": "windows-cim:123",
            },
        ]
    )

    assert set(table) == {4}


def test_windows_handle_close_preserves_pointer_width_and_checks_success() -> None:
    class FakeCloseHandle:
        argtypes: object = None
        restype: object = None
        received: int | None = None

        def __call__(self, handle: object) -> int:
            assert isinstance(handle, harness.ctypes.c_void_p)
            self.received = handle.value
            return 1

    close_handle = FakeCloseHandle()
    high_bit_handle = (1 << 63) | 0x1234

    harness._checked_windows_close_handle(close_handle, high_bit_handle)

    assert close_handle.argtypes == [harness.ctypes.c_void_p]
    assert close_handle.restype is harness.ctypes.c_int
    assert close_handle.received == high_bit_handle


def test_windows_handle_close_rejects_zero_kernel_result() -> None:
    class FailingCloseHandle:
        argtypes: object = None
        restype: object = None

        def __call__(self, handle: object) -> int:
            assert isinstance(handle, harness.ctypes.c_void_p)
            return 0

    close_handle = FailingCloseHandle()

    with pytest.raises(OSError, match="CloseHandle failed"):
        harness._checked_windows_close_handle(close_handle, (1 << 63) | 0x5678)

    assert close_handle.argtypes == [harness.ctypes.c_void_p]
    assert close_handle.restype is harness.ctypes.c_int


@pytest.mark.skipif(os.name != "nt", reason="requires native Windows Job Object cleanup")
def test_windows_job_close_failure_is_nonpromotable_infrastructure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    actual_close = harness._close_windows_handle

    def close_then_report_failure(handle: int) -> None:
        actual_close(handle)
        raise OSError("fixture CloseHandle failure")

    monkeypatch.setattr(harness, "_close_windows_handle", close_then_report_failure)
    supervision = harness._supervise(
        [sys.executable, "-I", "-c", "pass"],
        cwd=tmp_path,
        streams=tmp_path / "streams",
        timeout_seconds=5.0,
    )
    cleanup = cast(dict[str, object], supervision["cleanup"])
    containment = cast(dict[str, object], supervision["containment"])
    assert cleanup["close_attempted"] is True
    assert cleanup["close_succeeded"] is False
    assert cleanup["passed"] is False
    assert containment["passed"] is False
    with pytest.raises(EvaluationError, match="did not verify empty"):
        harness._validate_cleanup_receipt(cleanup, containment)

    cell = build_matrix()[0]
    boundaries = _execution_identity()
    harness_boundary = cast(dict[str, object], boundaries["harness_source"])
    runtime_boundary = cast(dict[str, object], boundaries["runtime_environment"])
    prior_boundary = cast(dict[str, object], boundaries["prior_authority"])
    cache_boundary = cast(dict[str, object], boundaries["environment_cache"])
    receipt = harness._cell_receipt(
        cell,
        spec={"worker_spec_hash": "sha256:" + "1" * 64},
        exposure_event={"event_hash": "sha256:" + "2" * 64},
        supervision=supervision,
        raw_path=tmp_path / "absent-raw.json",
        asset_after=_asset(cell),
        pre_receipt_active_wall_ns=1,
        harness_source_expected=cast(dict[str, object], harness_boundary["expected"]),
        harness_source_before=cast(dict[str, object], harness_boundary["before"]),
        harness_source_after=cast(dict[str, object], harness_boundary["after"]),
        runtime_environment_expected=cast(dict[str, object], runtime_boundary["expected"]),
        runtime_environment_before=cast(dict[str, object], runtime_boundary["before"]),
        runtime_environment_after=cast(dict[str, object], runtime_boundary["after"]),
        prior_authority_before=cast(dict[str, object], prior_boundary["before"]),
        prior_authority_after=cast(dict[str, object], prior_boundary["after"]),
        environment_cache_before=cast(dict[str, object], cache_boundary["before"]),
        environment_cache_after=cast(dict[str, object], cache_boundary["after"]),
    )
    assert receipt["status"] == CellStatus.INFRASTRUCTURE_FAILURE.value
    assert receipt["result"] == {
        "completed": False,
        "environment_actions": 0,
        "levels_completed": 0,
        "score_verified": False,
    }


def test_parent_supervisor_hashes_raw_streams_without_shell(tmp_path: Path) -> None:
    result = harness._supervise(
        [sys.executable, "-I", "-c", "import sys;sys.stdout.write('ok')"],
        cwd=tmp_path,
        streams=tmp_path / "streams",
        timeout_seconds=5.0,
    )

    assert result["launch_error"] is None
    assert result["returncode"] == 0
    assert result["timed_out"] is False
    assert result["stdout_bytes"] == 2
    stdout_path = result["stdout_path"]
    stderr_path = result["stderr_path"]
    assert isinstance(stdout_path, str)
    assert isinstance(stderr_path, str)
    assert Path(stdout_path).read_bytes() == b"ok"
    assert Path(stderr_path).read_bytes() == b""


def test_normal_root_exit_drains_and_verifies_long_lived_descendant(tmp_path: Path) -> None:
    child_code = (
        "import subprocess,sys;"
        "child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)'],"
        "stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,"
        "close_fds=True);print(child.pid,flush=True)"
    )
    result = harness._supervise(
        [sys.executable, "-I", "-c", child_code],
        cwd=tmp_path,
        streams=tmp_path / "streams",
        timeout_seconds=5.0,
    )

    assert result["launch_error"] is None
    assert result["returncode"] == 0
    assert result["timed_out"] is False
    stdout_path = cast(str, result["stdout_path"])
    child_pid = int(Path(stdout_path).read_text(encoding="utf-8").strip())
    cleanup = cast(dict[str, object], result["cleanup"])
    assert cast(int, cleanup["active_processes_before"]) >= 1
    assert cleanup["termination_attempted"] is True
    assert cleanup["termination_succeeded"] is True
    assert cleanup["active_processes_after"] == 0
    assert cleanup["passed"] is True
    containment = cast(dict[str, object], result["containment"])
    assert containment["active_processes_after"] == 0
    assert containment["passed"] is True
    assert harness._process_creation_token(child_pid) is None


def test_timeout_kills_and_verifies_spawned_descendant_tree(tmp_path: Path) -> None:
    child_code = (
        "import subprocess,sys,time;"
        "subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)']);"
        "time.sleep(30)"
    )
    result = harness._supervise(
        [sys.executable, "-I", "-c", child_code],
        cwd=tmp_path,
        streams=tmp_path / "streams",
        timeout_seconds=0.5,
    )

    assert result["timed_out"] is True
    termination = cast(dict[str, object], result["termination"])
    assert termination["passed"] is True
    assert termination["process_tree_verified_empty"] is True
    assert termination["containment_active_processes_after"] == 0
    containment = cast(dict[str, object], result["containment"])
    assert containment["passed"] is True
    assert containment["active_processes_after"] == 0
    if os.name == "nt":
        assert termination["containment_authority"] == ("windows-job-object-assigned-before-resume")
    else:
        assert termination["containment_authority"] == "posix-new-session-process-group"


def test_command_success_alone_cannot_verify_tree_termination() -> None:
    root_pid = 123
    root_token = "fixture-root-token"
    receipt = {
        "command_succeeded": True,
        "containment_active_processes_after": 1,
        "containment_authority": "posix-new-session-process-group",
        "passed": True,
        "process_tree_before": [
            {
                "parent_pid": 1,
                "pid": root_pid,
                "process_creation_token": root_token,
            },
            {
                "parent_pid": root_pid,
                "pid": 124,
                "process_creation_token": "fixture-child-token",
            },
        ],
        "process_tree_enumeration_error": None,
        "process_tree_live_after": [
            {
                "parent_pid": root_pid,
                "pid": 124,
                "process_creation_token": "fixture-child-token",
            }
        ],
        "process_tree_verification_error": None,
        "process_tree_verified_empty": True,
        "root_pid": root_pid,
        "root_process_creation_token": root_token,
    }

    with pytest.raises(EvaluationError, match="did not verify empty"):
        harness._validate_tree_termination_receipt(
            receipt,
            expected_root_pid=root_pid,
            expected_root_token=root_token,
            require_target_match=False,
        )


def test_runtime_identity_avoids_hostname_dependent_platform_helpers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden() -> NoReturn:
        raise AssertionError("hostname-dependent platform helper was called")

    monkeypatch.setattr(harness.platform, "processor", forbidden)
    monkeypatch.setattr(harness.platform, "machine", forbidden)
    monkeypatch.setattr(harness.platform, "platform", forbidden)

    identity = harness._runtime_identity()

    assert identity["platform"] == f"{os.name}:{sys.platform}"


def test_worker_handshake_aborts_before_environment_when_authorization_is_absent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spec = {"cell_id": "fixture-cell", "worker_spec_hash": "sha256:fixture"}
    spec_path = tmp_path / "spec.json"
    _write(spec_path, spec)
    args = argparse.Namespace(
        spec=spec_path,
        result=tmp_path / "raw.json",
        launch_receipt=tmp_path / "launch.json",
        authorization=tmp_path / "authorization.json",
        abort_receipt=tmp_path / "abort.json",
        launch_token="fixture-token",
    )
    ticks = iter((0.0, 11.0))
    monkeypatch.setattr("scripts._stage09_development_worker.time.monotonic", lambda: next(ticks))
    monkeypatch.setattr("scripts._stage09_development_worker.time.sleep", lambda _seconds: None)

    assert worker._await_authorization(args, spec) is False
    abort = worker._load_object(args.abort_receipt)
    assert abort["environment_opened"] is False
    assert abort["worker_abort_hash"] == worker._object_hash(abort, "worker_abort_hash")
    assert not args.result.exists()


@pytest.mark.parametrize("failed_boundary", ["launch", "authorization"])
def test_supervisor_launch_boundary_failure_terminates_waiting_child(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failed_boundary: str,
) -> None:
    paths = {
        "launch": tmp_path / "launch.json",
        "authorization": tmp_path / "authorization.json",
        "supervision": tmp_path / "supervision.json",
    }
    monkeypatch.setattr(harness, "_process_creation_token", lambda _pid: "fixture-token")
    original_create = harness._atomic_create

    def injected(path: Path, content: bytes) -> None:
        if path == paths[failed_boundary]:
            raise PermissionError("injected durable boundary failure")
        original_create(path, content)

    monkeypatch.setattr(harness, "_atomic_create", injected)
    result = harness._supervise(
        [sys.executable, "-I", "-c", "import time;time.sleep(30)"],
        cwd=tmp_path,
        streams=tmp_path / "streams",
        timeout_seconds=20.0,
        launch_receipt_path=paths["launch"],
        authorization_path=paths["authorization"],
        supervision_receipt_path=paths["supervision"],
        launch_context={
            "cell_id": "fixture-cell",
            "cell_spec_hash": "sha256:cell",
            "exposure_event_hash": "sha256:event",
            "launch_token": "fixture-launch-token",
            "authorization_path": paths["authorization"].resolve().as_posix(),
            "abort_path": (tmp_path / "abort.json").resolve().as_posix(),
            "raw_path": (tmp_path / "raw.json").resolve().as_posix(),
            "stderr_path": (tmp_path / "streams/stderr.bin").resolve().as_posix(),
            "stdout_path": (tmp_path / "streams/stdout.bin").resolve().as_posix(),
            "worker_spec_hash": "sha256:spec",
            "worker_spec_sha256": "sha256:spec-file",
        },
    )

    assert result["launch_error"] is not None
    termination = cast(dict[str, object], result["termination"])
    assert termination["attempted"] is True
    assert result["returncode"] is not None
    assert verify_object_hash(result, hash_field="supervision_receipt_hash")


def test_process_identity_query_failure_cannot_authorize_worker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(harness, "_process_creation_token", lambda _pid: None)
    result = harness._supervise(
        [sys.executable, "-I", "-c", "import time;time.sleep(30)"],
        cwd=tmp_path,
        streams=tmp_path / "streams",
        timeout_seconds=20.0,
        launch_receipt_path=tmp_path / "launch.json",
        authorization_path=tmp_path / "authorization.json",
        supervision_receipt_path=tmp_path / "supervision.json",
        launch_context={"launch_token": "fixture"},
    )

    assert "creation identity" in cast(str, result["launch_error"])
    assert result["launch_receipt_hash"] is None
    assert result["authorization_hash"] is None
    assert cast(dict[str, object], result["termination"])["attempted"] is True


@pytest.mark.parametrize(
    ("termination_passed", "expected"),
    [(True, CellStatus.CONTROLLER_WALL_TIMEOUT), (False, CellStatus.INFRASTRUCTURE_FAILURE)],
)
def test_timeout_requires_verified_process_tree_termination(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    termination_passed: bool,
    expected: CellStatus,
) -> None:
    cell = build_matrix()[0]
    monkeypatch.setattr(harness, "_asset_identity", lambda _root, selected: _asset(selected))
    monkeypatch.setattr(
        harness,
        "_timeout_trace_evidence",
        lambda *_args: {
            "trace": {"environment_action_count": 3},
            "timeout_trace_hash": "sha256:trace",
        },
    )
    spec = harness._worker_spec(
        cell,
        source_root=tmp_path / "source",
        environments=tmp_path / "environments",
        recordings=tmp_path / "recordings",
        cell_root=tmp_path / "cell",
        runtime_identity={},
        **_worker_identity_keywords(),
    )
    receipt = harness._cell_receipt(
        cell,
        spec=spec,
        exposure_event={"event_hash": "sha256:exposure"},
        supervision={
            "timed_out": True,
            "termination": {"passed": termination_passed},
            "wall_ns": 120_000_000_000,
        },
        raw_path=tmp_path / "missing.json",
        asset_after=_asset(cell),
        pre_receipt_active_wall_ns=120_000_010_000,
        **_cell_identity_keywords(),
    )

    assert receipt["schema"] == CELL_RECEIPT_SCHEMA
    assert receipt["status"] == expected.value
    result = cast(dict[str, object], receipt["result"])
    assert result["environment_actions"] == 0
    recovered = receipt["recovered_failure_result"]
    if expected is CellStatus.CONTROLLER_WALL_TIMEOUT:
        assert isinstance(recovered, dict)
        assert recovered["environment_actions"] == 3
        assert recovered["claim_status"] == "non-claim"
    else:
        assert isinstance(recovered, dict)
        assert recovered["environment_actions"] == 3
        assert recovered["claim_status"] == "non-claim"
    assert verify_object_hash(receipt, hash_field="cell_receipt_hash")


def test_timeout_with_invalid_raw_trace_is_infrastructure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cell = build_matrix()[0]
    raw_path = tmp_path / "raw.json"
    _write(raw_path, {"present": True})
    monkeypatch.setattr(
        harness,
        "_raw_result",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            EvaluationError("raw trace receipt changed from exact live replay")
        ),
    )
    monkeypatch.setattr(
        harness,
        "_timeout_trace_evidence",
        lambda *_args: {
            "trace": {"environment_action_count": 3},
            "timeout_trace_hash": "sha256:trace",
        },
    )
    spec = harness._worker_spec(
        cell,
        source_root=tmp_path / "source",
        environments=tmp_path / "environments",
        recordings=tmp_path / "recordings",
        cell_root=tmp_path / "cell",
        runtime_identity={},
        **_worker_identity_keywords(),
    )

    receipt = harness._cell_receipt(
        cell,
        spec=spec,
        exposure_event={"event_hash": "sha256:exposure"},
        supervision={
            "timed_out": True,
            "termination": {"passed": True},
            "wall_ns": 120_000_000_000,
        },
        raw_path=raw_path,
        asset_after=_asset(cell),
        pre_receipt_active_wall_ns=120_000_010_000,
        **_cell_identity_keywords(),
    )

    assert receipt["status"] == CellStatus.INFRASTRUCTURE_FAILURE.value
    assert "exact live replay" in cast(str, receipt["failure"])
    assert receipt["recovered_failure_result"] is not None


def test_untyped_policy_failure_is_infrastructure_and_reconstructs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    receipt, event, fixture = _materialize_cell_chain(
        tmp_path, monkeypatch, failure_kind="PolicyError"
    )
    cell = build_matrix()[0]
    reconstructed = harness._reconstruct_cell_receipt(
        work_root=cast(Path, fixture["work_root"]),
        recordings=tmp_path / "recordings",
        environments=tmp_path / "environments",
        build_000_root=tmp_path / "build000",
        build_001_root=tmp_path / "build001",
        runtime_identity=cast(dict[str, object], fixture["runtime"]),
        check=cast(dict[str, object], fixture["check"]),
        cell=cell,
        exposure_event=event,
    )

    assert receipt["status"] == CellStatus.INFRASTRUCTURE_FAILURE.value
    assert reconstructed == receipt
    result = cast(dict[str, object], receipt["result"])
    assert result == {
        "completed": False,
        "environment_actions": 0,
        "levels_completed": 0,
        "score_verified": False,
    }
    recovered = cast(dict[str, object], receipt["recovered_failure_result"])
    assert recovered["source"] == "raw-nondecisive-result"
    assert recovered["claim_status"] == "non-claim"
    failure = receipt["failure"]
    assert isinstance(failure, str)
    assert failure.startswith("raw worker failure")


@pytest.mark.parametrize("boundary", ["harness", "runtime", "prior", "cache"])
def test_persisted_after_boundary_drift_reconstructs_one_terminal_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    boundary: str,
) -> None:
    receipt, event, fixture = _materialize_cell_chain(
        tmp_path,
        monkeypatch,
        boundary_drift=boundary,
    )
    assert receipt["status"] == CellStatus.INFRASTRUCTURE_FAILURE.value
    section_name = {
        "harness": "harness_source",
        "runtime": "runtime_environment",
        "prior": "prior_authority",
        "cache": "environment_cache",
    }[boundary]
    section = cast(dict[str, object], receipt[section_name])
    assert section["after"] != section["before"]
    assert section["stable"] is False
    cell = build_matrix()[0]
    reconstructed = harness._reconstruct_cell_receipt(
        work_root=cast(Path, fixture["work_root"]),
        recordings=tmp_path / "recordings",
        environments=tmp_path / "environments",
        build_000_root=tmp_path / "build000",
        build_001_root=tmp_path / "build001",
        runtime_identity=cast(dict[str, object], fixture["runtime"]),
        check=cast(dict[str, object], fixture["check"]),
        cell=cell,
        exposure_event=event,
    )
    assert reconstructed == receipt
    preflight = seal_object(
        {
            "schema": PREFLIGHT_SCHEMA,
            "status": "READY_NOT_EXECUTED",
            "gameplay_opened": False,
            "runtime_identity": fixture["runtime"],
            "competition_integrity": {},
            "stage09_exposure_event_count": 1,
            **_preflight_execution_identity(),
        },
        hash_field="preflight_hash",
    )
    preflight = _attach_fixture_clock(tmp_path, monkeypatch, preflight)
    ends = {
        "harness_end": cast(dict[str, object], receipt["harness_source"])["after"],
        "runtime_end": cast(dict[str, object], receipt["runtime_environment"])["after"],
        "authority_end": cast(dict[str, object], receipt["prior_authority"])["after"],
        "cache_end": cast(dict[str, object], receipt["environment_cache"])["after"],
    }
    output = tmp_path / "terminal.json"
    terminal = harness._failure_terminal(
        output=output,
        check=preflight,
        receipts=[receipt],
        finalizations=[cast(dict[str, object], fixture["finalization"])],
        exposure=cast(Path, fixture["exposure"]),
        failed_cell=cell,
        failure_kind="terminal-cell-infrastructure-failure",
        exposure_event_hash=event["event_hash"],
        **ends,
    )

    resumed = harness._load_existing_terminal(
        output=output,
        work_root=cast(Path, fixture["work_root"]),
        exposure=cast(Path, fixture["exposure"]),
        check=preflight,
        recordings=tmp_path / "recordings",
        environments=tmp_path / "environments",
        build_000_root=tmp_path / "build000",
        build_001_root=tmp_path / "build001",
    )
    assert resumed == terminal
    assert cast(dict[str, object], resumed["failure"])["kind"] == (
        "terminal-cell-infrastructure-failure"
    )


@pytest.mark.parametrize("field", ["levels_completed", "environment_actions", "status"])
def test_rehashed_parent_result_cannot_replace_raw_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, field: str
) -> None:
    receipt, _event, fixture = _materialize_cell_chain(tmp_path, monkeypatch)
    tampered = copy.deepcopy(receipt)
    if field == "status":
        tampered["status"] = CellStatus.MECHANISM_FAILURE.value
    else:
        result = cast(dict[str, object], tampered["result"])
        result[field] = cast(int, result[field]) + 1
    tampered = seal_object(tampered, hash_field="cell_receipt_hash")
    cell = build_matrix()[0]
    paths = harness._cell_paths(cast(Path, fixture["work_root"]), cell)
    _write(paths["receipt"], tampered)
    preflight = seal_object(
        {
            "schema": PREFLIGHT_SCHEMA,
            "status": "READY_NOT_EXECUTED",
            "gameplay_opened": False,
            "runtime_identity": fixture["runtime"],
            "competition_integrity": {},
            "stage09_exposure_event_count": 1,
            **_preflight_execution_identity(),
        },
        hash_field="preflight_hash",
    )
    preflight = _attach_fixture_clock(tmp_path, monkeypatch, preflight)
    output = tmp_path / "terminal.json"
    terminal = harness._failure_terminal(
        output=output,
        check=preflight,
        receipts=[receipt],
        finalizations=[cast(dict[str, object], fixture["finalization"])],
        exposure=cast(Path, fixture["exposure"]),
        failed_cell=build_matrix()[1],
        failure_kind="overall-active-wall-cannot-admit-next-cell",
        exposure_event_hash=None,
    )
    terminal["cell_receipt_hashes"] = [tampered["cell_receipt_hash"]]
    _write(output, seal_object(terminal, hash_field="artifact_core_hash"))

    with pytest.raises(EvaluationError, match=r"changed|does not reconstruct exactly"):
        harness._load_existing_terminal(
            output=output,
            work_root=cast(Path, fixture["work_root"]),
            exposure=cast(Path, fixture["exposure"]),
            check=preflight,
            recordings=tmp_path / "recordings",
            environments=tmp_path / "environments",
            build_000_root=tmp_path / "build000",
            build_001_root=tmp_path / "build001",
        )


def test_rehashed_parent_wall_and_terminal_resource_projection_cannot_promote(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    receipt, _event, fixture = _materialize_cell_chain(tmp_path, monkeypatch)
    tampered = copy.deepcopy(receipt)
    resources = cast(dict[str, object], tampered["resources"])
    resources["pre_receipt_active_wall_ns"] = 10
    tampered = seal_object(tampered, hash_field="cell_receipt_hash")
    cell = build_matrix()[0]
    paths = harness._cell_paths(cast(Path, fixture["work_root"]), cell)
    _write(paths["receipt"], tampered)
    preflight = seal_object(
        {
            "schema": PREFLIGHT_SCHEMA,
            "status": "READY_NOT_EXECUTED",
            "gameplay_opened": False,
            "runtime_identity": fixture["runtime"],
            "competition_integrity": {},
            "stage09_exposure_event_count": 1,
            **_preflight_execution_identity(),
        },
        hash_field="preflight_hash",
    )
    preflight = _attach_fixture_clock(tmp_path, monkeypatch, preflight)
    output = tmp_path / "terminal.json"
    harness._failure_terminal(
        output=output,
        check=preflight,
        receipts=[tampered],
        finalizations=[cast(dict[str, object], fixture["finalization"])],
        exposure=cast(Path, fixture["exposure"]),
        failed_cell=build_matrix()[1],
        failure_kind="overall-active-wall-cannot-admit-next-cell",
        exposure_event_hash=None,
    )

    with pytest.raises(EvaluationError, match="parent cell receipt does not reconstruct exactly"):
        harness._load_existing_terminal(
            output=output,
            work_root=cast(Path, fixture["work_root"]),
            exposure=cast(Path, fixture["exposure"]),
            check=preflight,
            recordings=tmp_path / "recordings",
            environments=tmp_path / "environments",
            build_000_root=tmp_path / "build000",
            build_001_root=tmp_path / "build001",
        )


@pytest.mark.parametrize("artifact", ["raw", "stdout", "spec"])
def test_restart_revalidates_exact_worker_evidence_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, artifact: str
) -> None:
    _receipt, event, fixture = _materialize_cell_chain(tmp_path, monkeypatch)
    cell = build_matrix()[0]
    paths = harness._cell_paths(cast(Path, fixture["work_root"]), cell)
    if artifact == "raw":
        raw = load_json(paths["raw"])
        score = cast(dict[str, object], raw["score"])
        score["levels_completed"] = 2
        _write(paths["raw"], seal_object(raw, hash_field="receipt_hash"))
    elif artifact == "stdout":
        paths["stdout"].write_bytes(paths["stdout"].read_bytes() + b"tamper")
    else:
        spec = load_json(paths["spec"])
        spec["cell_id"] = "changed-cell"
        _write(paths["spec"], seal_object(spec, hash_field="worker_spec_hash"))

    with pytest.raises(EvaluationError):
        harness._reconstruct_cell_receipt(
            work_root=cast(Path, fixture["work_root"]),
            recordings=tmp_path / "recordings",
            environments=tmp_path / "environments",
            build_000_root=tmp_path / "build000",
            build_001_root=tmp_path / "build001",
            runtime_identity=cast(dict[str, object], fixture["runtime"]),
            check=cast(dict[str, object], fixture["check"]),
            cell=cell,
            exposure_event=event,
        )


@pytest.mark.parametrize(
    "tamper",
    ["missing-live-trace", "mutated-trace-receipt", "action-drift", "reset-drift"],
)
def test_raw_result_requires_exact_live_trace_replay(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    tamper: str,
) -> None:
    _receipt_value, _event, fixture = _materialize_cell_chain(tmp_path, monkeypatch)
    cell = build_matrix()[0]
    paths = harness._cell_paths(cast(Path, fixture["work_root"]), cell)
    spec = cast(dict[str, object], load_json(paths["spec"]))
    if tamper == "missing-live-trace":
        public = cast(dict[str, object], spec["public_worker_spec"])
        Path(cast(str, public["trace_path"])).rmdir()
    else:
        raw = cast(dict[str, object], load_json(paths["raw"]))
        if tamper == "mutated-trace-receipt":
            trace = cast(dict[str, object], raw["trace"])
            trace["tail_event_hash"] = "sha256:" + "f" * 64
        elif tamper == "action-drift":
            metrics = cast(dict[str, object], raw["metrics"])
            metrics["environment_actions"] = 4
        else:
            metrics = cast(dict[str, object], raw["metrics"])
            metrics["resets"] = 1
        _write(paths["raw"], seal_object(raw, hash_field="receipt_hash"))

    with pytest.raises(EvaluationError, match=r"trace|receipt validation"):
        harness._raw_result(paths["raw"], cell, spec, asset_after=_asset(cell))


@pytest.mark.parametrize("field", ["environment_action_count", "reset_count"])
def test_timeout_trace_replay_rejects_action_or_reset_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
) -> None:
    _receipt_value, _event, fixture = _materialize_cell_chain(tmp_path, monkeypatch)
    cell = build_matrix()[0]
    paths = harness._cell_paths(cast(Path, fixture["work_root"]), cell)
    spec = cast(dict[str, object], load_json(paths["spec"]))
    raw = cast(dict[str, object], load_json(paths["raw"]))
    trace = copy.deepcopy(cast(dict[str, object], raw["trace"]))
    trace[field] = cast(int, trace[field]) + 1
    monkeypatch.setattr(harness, "_trace_receipt", lambda *_args, **_kwargs: trace)

    assert harness._timeout_trace_evidence(cell, spec) is None


def test_orphan_pid_reuse_is_not_terminated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _receipt, event, fixture = _materialize_cell_chain(tmp_path, monkeypatch)
    cell = build_matrix()[0]
    paths = harness._cell_paths(cast(Path, fixture["work_root"]), cell)
    paths["receipt"].unlink()
    monkeypatch.setattr(harness, "_process_creation_token", lambda _pid: "reused-process-token")

    def forbidden(_pid: int, _token: str) -> NoReturn:
        raise AssertionError("PID-reused process was terminated")

    monkeypatch.setattr(harness, "_terminate_orphan_exact", forbidden)
    orphan = harness._seal_orphan_boundary(
        work_root=cast(Path, fixture["work_root"]),
        recordings=tmp_path / "recordings",
        environments=tmp_path / "environments",
        build_000_root=tmp_path / "build000",
        build_001_root=tmp_path / "build001",
        runtime_identity=cast(dict[str, object], fixture["runtime"]),
        check=cast(dict[str, object], fixture["check"]),
        cell=cell,
        exposure_event=event,
    )

    assert orphan["passed"] is True
    assert orphan["state"] == "pid-reused-original-not-running"
    assert orphan["termination"] is None


def test_invalid_orphan_launch_token_fails_before_process_lookup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _receipt, event, fixture = _materialize_cell_chain(tmp_path, monkeypatch)
    cell = build_matrix()[0]
    paths = harness._cell_paths(cast(Path, fixture["work_root"]), cell)
    paths["receipt"].unlink()
    launch = cast(dict[str, object], load_json(paths["launch"]))
    launch["launch_token"] = ""
    _write(paths["launch"], seal_object(launch, hash_field="launch_receipt_hash"))

    def forbidden(_pid: int) -> NoReturn:
        raise AssertionError("invalid launch token reached process lookup")

    monkeypatch.setattr(harness, "_process_creation_token", forbidden)
    with pytest.raises(EvaluationError, match="launch token is invalid"):
        harness._seal_orphan_boundary(
            work_root=cast(Path, fixture["work_root"]),
            recordings=tmp_path / "recordings",
            environments=tmp_path / "environments",
            build_000_root=tmp_path / "build000",
            build_001_root=tmp_path / "build001",
            runtime_identity=cast(dict[str, object], fixture["runtime"]),
            check=cast(dict[str, object], fixture["check"]),
            cell=cell,
            exposure_event=event,
        )
    assert not paths["orphan"].exists()


def test_exact_live_orphan_blocks_terminal_sealing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _receipt_value, event, fixture = _materialize_cell_chain(tmp_path, monkeypatch)
    cell = build_matrix()[0]
    paths = harness._cell_paths(cast(Path, fixture["work_root"]), cell)
    paths["receipt"].unlink()
    monkeypatch.setattr(
        harness,
        "_process_creation_token",
        lambda _pid: "fixture-process-token",
    )
    monkeypatch.setattr(
        harness,
        "_terminate_orphan_exact",
        lambda _pid, _token: {
            "attempted": True,
            "error": "fixture termination failure",
            "live_process_token_after": "fixture-process-token",
            "live_process_token_before": "fixture-process-token",
            "method": "fixture",
            "passed": False,
            "returncode": 1,
            "target_token_matched": True,
        },
    )

    with pytest.raises(EvaluationError, match="remains live"):
        harness._seal_orphan_boundary(
            work_root=cast(Path, fixture["work_root"]),
            recordings=tmp_path / "recordings",
            environments=tmp_path / "environments",
            build_000_root=tmp_path / "build000",
            build_001_root=tmp_path / "build001",
            runtime_identity=cast(dict[str, object], fixture["runtime"]),
            check=cast(dict[str, object], fixture["check"]),
            cell=cell,
            exposure_event=event,
        )
    assert not paths["orphan"].exists()


def test_resume_retries_exact_authorized_orphan_token(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _receipt_value, event, fixture = _materialize_cell_chain(tmp_path, monkeypatch)
    cell = build_matrix()[0]
    paths = harness._cell_paths(cast(Path, fixture["work_root"]), cell)
    paths["receipt"].unlink()
    monkeypatch.setattr(harness, "_process_creation_token", lambda _pid: "reused-token")
    original = harness._seal_orphan_boundary(
        work_root=cast(Path, fixture["work_root"]),
        recordings=tmp_path / "recordings",
        environments=tmp_path / "environments",
        build_000_root=tmp_path / "build000",
        build_001_root=tmp_path / "build001",
        runtime_identity=cast(dict[str, object], fixture["runtime"]),
        check=cast(dict[str, object], fixture["check"]),
        cell=cell,
        exposure_event=event,
    )
    assert original["state"] == "pid-reused-original-not-running"
    tokens = iter(("fixture-process-token", None))
    monkeypatch.setattr(harness, "_process_creation_token", lambda _pid: next(tokens))
    calls: list[tuple[int, str]] = []

    def terminate(pid: int, token: str) -> dict[str, object]:
        calls.append((pid, token))
        return {
            "attempted": True,
            "error": None,
            "live_process_token_after": None,
            "live_process_token_before": token,
            "method": "fixture",
            "passed": True,
            "returncode": 0,
            "target_token_matched": True,
        }

    monkeypatch.setattr(harness, "_terminate_orphan_exact", terminate)
    resumed = harness._seal_orphan_boundary(
        work_root=cast(Path, fixture["work_root"]),
        recordings=tmp_path / "recordings",
        environments=tmp_path / "environments",
        build_000_root=tmp_path / "build000",
        build_001_root=tmp_path / "build001",
        runtime_identity=cast(dict[str, object], fixture["runtime"]),
        check=cast(dict[str, object], fixture["check"]),
        cell=cell,
        exposure_event=event,
    )
    assert resumed == original
    assert calls == [(2, "fixture-process-token")]


@pytest.mark.parametrize("tamper", ["noncanonical", "resigned-invalid-state"])
def test_orphan_receipt_tamper_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    tamper: str,
) -> None:
    _receipt_value, event, fixture = _materialize_cell_chain(tmp_path, monkeypatch)
    cell = build_matrix()[0]
    paths = harness._cell_paths(cast(Path, fixture["work_root"]), cell)
    paths["receipt"].unlink()
    monkeypatch.setattr(harness, "_process_creation_token", lambda _pid: "reused-token")
    harness._seal_orphan_boundary(
        work_root=cast(Path, fixture["work_root"]),
        recordings=tmp_path / "recordings",
        environments=tmp_path / "environments",
        build_000_root=tmp_path / "build000",
        build_001_root=tmp_path / "build001",
        runtime_identity=cast(dict[str, object], fixture["runtime"]),
        check=cast(dict[str, object], fixture["check"]),
        cell=cell,
        exposure_event=event,
    )
    if tamper == "noncanonical":
        paths["orphan"].write_bytes(paths["orphan"].read_bytes() + b" ")
    else:
        orphan = cast(dict[str, object], load_json(paths["orphan"]))
        orphan["state"] = "terminated"
        _write(paths["orphan"], seal_object(orphan, hash_field="orphan_receipt_hash"))

    with pytest.raises(EvaluationError):
        harness._seal_orphan_boundary(
            work_root=cast(Path, fixture["work_root"]),
            recordings=tmp_path / "recordings",
            environments=tmp_path / "environments",
            build_000_root=tmp_path / "build000",
            build_001_root=tmp_path / "build001",
            runtime_identity=cast(dict[str, object], fixture["runtime"]),
            check=cast(dict[str, object], fixture["check"]),
            cell=cell,
            exposure_event=event,
        )


def test_resume_validates_pre_environment_worker_abort(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _receipt, event, fixture = _materialize_cell_chain(tmp_path, monkeypatch)
    cell = build_matrix()[0]
    paths = harness._cell_paths(cast(Path, fixture["work_root"]), cell)
    for name in ("receipt", "launch", "authorization", "raw", "stdout", "stderr", "supervision"):
        paths[name].unlink()
    abort = seal_object(
        {
            "schema": harness.WORKER_ABORT_SCHEMA,
            "authorization_path": paths["authorization"].resolve().as_posix(),
            "cell_id": cell.cell_id,
            "environment_opened": False,
            "launch_receipt_path": paths["launch"].resolve().as_posix(),
            "launch_token": cast(
                str,
                cast(dict[str, object], load_json(paths["spawn_intent"]))["launch_token"],
            ),
            "pid": 123,
            "reason": "launch-authorization-unavailable-or-invalid",
        },
        hash_field="worker_abort_hash",
    )
    _write(paths["abort"], abort)
    monkeypatch.setattr(harness, "_spawn_intent_processes", lambda _token: ([], None))

    orphan = harness._seal_orphan_boundary(
        work_root=cast(Path, fixture["work_root"]),
        recordings=tmp_path / "recordings",
        environments=tmp_path / "environments",
        build_000_root=tmp_path / "build000",
        build_001_root=tmp_path / "build001",
        runtime_identity=cast(dict[str, object], fixture["runtime"]),
        check=cast(dict[str, object], fixture["check"]),
        cell=cell,
        exposure_event=event,
    )

    assert orphan["passed"] is True
    assert orphan["state"] == "pre-environment-handshake-aborted"


def test_rehashed_partial_terminal_cannot_be_promoted_to_pass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cell = build_matrix()[0]
    exposure = tmp_path / "exposure.jsonl"
    event = PublicExposureLedger(exposure).append(
        "stage09.development_episode_started",
        {
            "asset_sha256": cell.game.asset_sha256,
            "cell_id": cell.cell_id,
            "cell_spec_hash": cell.spec_hash,
            "game_id": cell.game.game_id,
            "partition": "development",
            "seed": cell.seed,
            "source_commit": cell.variant.source_commit,
            "variant": cell.variant.value,
        },
    )
    runtime = harness._runtime_identity()
    preflight = seal_object(
        {
            "schema": PREFLIGHT_SCHEMA,
            "status": "READY_NOT_EXECUTED",
            "gameplay_opened": False,
            "runtime_identity": runtime,
            "competition_integrity": {},
            "stage09_exposure_event_count": 1,
            **_preflight_execution_identity(),
        },
        hash_field="preflight_hash",
    )
    preflight = _attach_fixture_clock(tmp_path, monkeypatch, preflight)
    output = tmp_path / "terminal.json"
    terminal = harness._failure_terminal(
        output=output,
        check=preflight,
        receipts=[],
        finalizations=[],
        exposure=exposure,
        failed_cell=cell,
        failure_kind="exposed-without-terminal-receipt",
        exposure_event_hash=event["event_hash"],
    )
    tampered = dict(terminal)
    tampered["status"] = "PASS"
    output.write_bytes(canonical_json_bytes(seal_object(tampered, hash_field="artifact_core_hash")))

    with pytest.raises(EvaluationError, match="fail-closed"):
        harness._load_existing_terminal(
            output=output,
            work_root=tmp_path / "work",
            exposure=exposure,
            check=preflight,
        )


@pytest.mark.parametrize(
    "tamper",
    ["failure-identity", "boundary-endpoint", "receipt-hash", "finalization-hash", "bytes"],
)
def test_partial_terminal_identity_and_hash_tamper_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    tamper: str,
) -> None:
    receipt, event, fixture = _materialize_cell_chain(
        tmp_path,
        monkeypatch,
        boundary_drift="runtime",
    )
    preflight = seal_object(
        {
            "schema": PREFLIGHT_SCHEMA,
            "status": "READY_NOT_EXECUTED",
            "gameplay_opened": False,
            "runtime_identity": fixture["runtime"],
            "competition_integrity": {},
            "stage09_exposure_event_count": 1,
            **_preflight_execution_identity(),
        },
        hash_field="preflight_hash",
    )
    preflight = _attach_fixture_clock(tmp_path, monkeypatch, preflight)
    cell = build_matrix()[0]
    output = tmp_path / "terminal.json"
    terminal = harness._failure_terminal(
        output=output,
        check=preflight,
        receipts=[receipt],
        finalizations=[cast(dict[str, object], fixture["finalization"])],
        exposure=cast(Path, fixture["exposure"]),
        failed_cell=cell,
        failure_kind="terminal-cell-infrastructure-failure",
        exposure_event_hash=event["event_hash"],
        harness_end=cast(dict[str, object], receipt["harness_source"])["after"],
        runtime_end=cast(dict[str, object], receipt["runtime_environment"])["after"],
        authority_end=cast(dict[str, object], receipt["prior_authority"])["after"],
        cache_end=cast(dict[str, object], receipt["environment_cache"])["after"],
    )
    if tamper == "bytes":
        output.write_bytes(output.read_bytes() + b" ")
    else:
        changed = copy.deepcopy(terminal)
        if tamper == "failure-identity":
            cast(dict[str, object], changed["failure"])["kind"] = "different-failure"
        elif tamper == "boundary-endpoint":
            execution = cast(dict[str, object], changed["execution_boundaries"])
            runtime = cast(dict[str, object], execution["runtime_environment"])
            runtime["end"] = None
        elif tamper == "receipt-hash":
            changed["cell_receipt_hashes"] = ["sha256:" + "f" * 64]
        else:
            changed["cell_finalization_hashes"] = ["sha256:" + "f" * 64]
        _write(output, seal_object(changed, hash_field="artifact_core_hash"))

    with pytest.raises(EvaluationError):
        harness._load_existing_terminal(
            output=output,
            work_root=cast(Path, fixture["work_root"]),
            exposure=cast(Path, fixture["exposure"]),
            check=preflight,
            recordings=tmp_path / "recordings",
            environments=tmp_path / "environments",
            build_000_root=tmp_path / "build000",
            build_001_root=tmp_path / "build001",
        )


def test_exposed_cell_without_terminal_receipt_is_never_relaunched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    event = {"event_hash": "sha256:already-exposed"}
    identity = _execution_identity()
    harness_boundary = cast(dict[str, object], identity["harness_source"])
    expected_harness = cast(dict[str, object], harness_boundary["expected"])
    monkeypatch.setattr(
        harness,
        "_BOOTSTRAP_AUTHORITY",
        {
            "files": expected_harness["files"],
            "git_commit": expected_harness["git_commit"],
            "git_tree": expected_harness["git_tree"],
            "runtime_binding_hash": harness.EXPECTED_RUNTIME_ENVIRONMENT["runtime_binding_hash"],
            "socket_audit_denial_installed": True,
        },
    )
    monkeypatch.setattr(harness, "_boot_identity", lambda: "fixture-boot")
    monkeypatch.setattr(harness, "_runtime_identity", lambda: {})
    monkeypatch.setattr(harness, "_official_paths", lambda **_kwargs: None)
    preflight_receipt = seal_object(
        {
            "schema": PREFLIGHT_SCHEMA,
            "status": "READY_NOT_EXECUTED",
            "gameplay_opened": False,
            "runtime_identity": {},
            "sources": {},
            "competition_integrity": {},
            "stage09_exposure_event_count": 1,
            **_preflight_execution_identity(),
        },
        hash_field="preflight_hash",
    )
    monkeypatch.setattr(
        harness,
        "preflight",
        lambda **_kwargs: preflight_receipt,
    )
    monkeypatch.setattr(harness, "_validate_exposures", lambda _path: (event,))
    monkeypatch.setattr(
        harness,
        "_seal_orphan_boundary",
        lambda **_kwargs: {"passed": False, "state": "fixture-untracked"},
    )

    def forbidden(*_args: object, **_kwargs: object) -> NoReturn:
        raise AssertionError("an exposed cell was relaunched")

    monkeypatch.setattr(harness, "_supervise", forbidden)

    result = harness.execute(
        harness_source_expected=expected_harness,
        output=tmp_path / "output.json",
        work_root=tmp_path / "work",
        exposure=tmp_path / "exposure.jsonl",
        recordings=tmp_path / "recordings",
        environments=tmp_path / "environments",
        build_000_root=tmp_path / "build000",
        build_001_root=tmp_path / "build001",
        stage08_result=tmp_path / "stage08.json",
        stage08_exposure=tmp_path / "stage08-exposure.jsonl",
    )

    assert result["status"] == "FAILED_INFRASTRUCTURE"
    assert result["execution_complete"] is False
    failure = result["failure"]
    assert isinstance(failure, dict)
    assert failure["kind"] == "exposed-without-terminal-receipt"


def test_exposed_without_launch_or_abort_seals_typed_failure_without_cleanup_claim(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _receipt, event, fixture = _materialize_cell_chain(tmp_path, monkeypatch)
    cell = build_matrix()[0]
    work_root = cast(Path, fixture["work_root"])
    paths = harness._cell_paths(work_root, cell)
    for name in (
        "authorization",
        "finalization",
        "launch",
        "parent_evidence",
        "raw",
        "receipt",
        "stderr",
        "stdout",
        "supervision",
    ):
        paths[name].unlink()
    monkeypatch.setattr(harness, "_spawn_intent_processes", lambda _token: ([], None))

    orphan = harness._seal_orphan_boundary(
        work_root=work_root,
        recordings=tmp_path / "recordings",
        environments=tmp_path / "environments",
        build_000_root=tmp_path / "build000",
        build_001_root=tmp_path / "build001",
        runtime_identity=cast(dict[str, object], fixture["runtime"]),
        check=cast(dict[str, object], fixture["check"]),
        cell=cell,
        exposure_event=event,
    )
    assert orphan["state"] == "unreceipted-launch-not-running"
    assert orphan["cleanup_claimed"] is False
    process_proof = cast(dict[str, object], orphan["process_enumeration"])
    assert process_proof["verified_empty"] is True

    output = tmp_path / "unreceipted-failure.json"
    terminal = harness._failure_terminal(
        output=output,
        check=cast(dict[str, object], fixture["check"]),
        receipts=[],
        finalizations=[],
        exposure=cast(Path, fixture["exposure"]),
        failed_cell=cell,
        failure_kind="exposed-without-terminal-receipt",
        exposure_event_hash=event["event_hash"],
        orphan_process=orphan,
    )
    assert terminal["status"] == "FAILED_INFRASTRUCTURE"
    resources = cast(dict[str, object], terminal["resources"])
    assert resources["open_segment_conservative_charge_ns"] == (harness.CELL_ADMISSION_CHARGE_NS)


def test_unreceipted_live_spawn_without_exact_containment_blocks_terminal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _receipt, event, fixture = _materialize_cell_chain(tmp_path, monkeypatch)
    cell = build_matrix()[0]
    work_root = cast(Path, fixture["work_root"])
    paths = harness._cell_paths(work_root, cell)
    for name in (
        "authorization",
        "finalization",
        "launch",
        "parent_evidence",
        "raw",
        "receipt",
        "stderr",
        "stdout",
        "supervision",
    ):
        paths[name].unlink()
    match = {
        "parent_pid": 1,
        "pid": 123,
        "process_creation_token": "fixture-live-token",
    }
    monkeypatch.setattr(
        harness,
        "_spawn_intent_processes",
        lambda _token: ([match], None),
    )
    monkeypatch.setattr(
        harness,
        "_terminate_orphan_exact",
        lambda _pid, _token: {
            "live_process_token_after": "fixture-live-token",
            "passed": False,
        },
    )

    with pytest.raises(EvaluationError, match="did not terminate"):
        harness._seal_orphan_boundary(
            work_root=work_root,
            recordings=tmp_path / "recordings",
            environments=tmp_path / "environments",
            build_000_root=tmp_path / "build000",
            build_001_root=tmp_path / "build001",
            runtime_identity=cast(dict[str, object], fixture["runtime"]),
            check=cast(dict[str, object], fixture["check"]),
            cell=cell,
            exposure_event=event,
        )
    assert not paths["orphan"].exists()


def test_open_cell_segment_resume_charges_full_cell_and_excludes_reboot_downtime(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    identity = _execution_identity()
    harness_boundary = cast(dict[str, object], identity["harness_source"])
    expected_harness = cast(dict[str, object], harness_boundary["expected"])
    monkeypatch.setattr(
        harness,
        "_BOOTSTRAP_AUTHORITY",
        {
            "files": expected_harness["files"],
            "git_commit": expected_harness["git_commit"],
            "git_tree": expected_harness["git_tree"],
            "runtime_binding_hash": harness.EXPECTED_RUNTIME_ENVIRONMENT["runtime_binding_hash"],
            "socket_audit_denial_installed": True,
        },
    )
    runtime: dict[str, object] = {}
    monkeypatch.setattr(harness, "_runtime_identity", lambda: runtime)
    monkeypatch.setattr(harness, "_official_paths", lambda **_kwargs: None)
    base_preflight = seal_object(
        {
            "schema": PREFLIGHT_SCHEMA,
            "status": "READY_NOT_EXECUTED",
            "gameplay_opened": False,
            "runtime_identity": runtime,
            "sources": {},
            "competition_integrity": {},
            "stage09_exposure_event_count": 0,
            **_preflight_execution_identity(),
        },
        hash_field="preflight_hash",
    )
    work_root = tmp_path / "run-clock"
    check = harness._attach_run_clock(
        base_preflight,
        work_root=work_root,
        harness_binding_hash=expected_harness["binding_hash"],
    )
    cell = build_matrix()[0]
    paths = harness._cell_paths(work_root, cell)
    segment = harness._cell_segment_payload(
        cell=cell,
        check=check,
        boot_identity="old-boot",
        started_perf_counter_ns=1,
    )
    _write(paths["cell_segment"], segment)
    monkeypatch.setattr(harness, "preflight", lambda **_kwargs: base_preflight)
    monkeypatch.setattr(harness, "_validate_exposures", lambda _path: ())
    monkeypatch.setattr(harness, "_boot_identity", lambda: "simulated-new-boot")
    monkeypatch.setattr(harness.time, "perf_counter_ns", lambda: 10**18)

    def forbidden(*_args: object, **_kwargs: object) -> NoReturn:
        raise AssertionError("open cell segment was relaunched")

    monkeypatch.setattr(harness, "_supervise", forbidden)
    output = tmp_path / "open-segment-failure.json"
    kwargs = {
        "harness_source_expected": expected_harness,
        "output": output,
        "work_root": work_root,
        "exposure": tmp_path / "exposure.jsonl",
        "recordings": tmp_path / "recordings",
        "environments": tmp_path / "environments",
        "build_000_root": tmp_path / "build000",
        "build_001_root": tmp_path / "build001",
        "stage08_result": tmp_path / "stage08.json",
        "stage08_exposure": tmp_path / "stage08-exposure.jsonl",
    }
    terminal = harness.execute(**kwargs)
    assert terminal["status"] == "FAILED_INFRASTRUCTURE"
    assert cast(dict[str, object], terminal["failure"])["kind"] == (
        "open-cell-segment-without-finalization"
    )
    resources = cast(dict[str, object], terminal["resources"])
    assert resources["cumulative_active_accounted_wall_ns"] == (harness.CELL_ADMISSION_CHARGE_NS)
    assert resources["open_segment_conservative_charge_ns"] == (harness.CELL_ADMISSION_CHARGE_NS)
    assert harness.execute(**kwargs) == terminal


def test_resume_seals_receipt_without_finalization_and_never_relaunches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    receipt, _event, fixture = _materialize_cell_chain(tmp_path, monkeypatch)
    cell = build_matrix()[0]
    work_root = cast(Path, fixture["work_root"])
    paths = harness._cell_paths(work_root, cell)
    receipt_bytes = paths["receipt"].read_bytes()
    paths["finalization"].unlink()
    identity = _execution_identity()
    harness_boundary = cast(dict[str, object], identity["harness_source"])
    expected_harness = cast(dict[str, object], harness_boundary["expected"])
    monkeypatch.setattr(
        harness,
        "_BOOTSTRAP_AUTHORITY",
        {
            "files": expected_harness["files"],
            "git_commit": expected_harness["git_commit"],
            "git_tree": expected_harness["git_tree"],
            "runtime_binding_hash": harness.EXPECTED_RUNTIME_ENVIRONMENT["runtime_binding_hash"],
            "socket_audit_denial_installed": True,
        },
    )
    runtime = cast(dict[str, object], fixture["runtime"])
    monkeypatch.setattr(harness, "_runtime_identity", lambda: runtime)
    monkeypatch.setattr(harness, "_official_paths", lambda **_kwargs: None)
    preflight_receipt = seal_object(
        {
            "schema": PREFLIGHT_SCHEMA,
            "status": "READY_NOT_EXECUTED",
            "gameplay_opened": False,
            "runtime_identity": runtime,
            "sources": {},
            "competition_integrity": {},
            "stage09_exposure_event_count": 1,
            **_preflight_execution_identity(),
        },
        hash_field="preflight_hash",
    )
    monkeypatch.setattr(harness, "preflight", lambda **_kwargs: preflight_receipt)

    def forbidden(*_args: object, **_kwargs: object) -> NoReturn:
        raise AssertionError("a receipt-bearing cell was relaunched")

    monkeypatch.setattr(harness, "_supervise", forbidden)
    output = tmp_path / "output.json"

    result = harness.execute(
        harness_source_expected=expected_harness,
        output=output,
        work_root=work_root,
        exposure=cast(Path, fixture["exposure"]),
        recordings=tmp_path / "recordings",
        environments=tmp_path / "environments",
        build_000_root=tmp_path / "build000",
        build_001_root=tmp_path / "build001",
        stage08_result=tmp_path / "stage08.json",
        stage08_exposure=tmp_path / "stage08-exposure.jsonl",
    )

    assert result["status"] == "FAILED_INFRASTRUCTURE"
    assert result["execution_complete"] is False
    assert cast(dict[str, object], result["failure"])["kind"] == (
        "durable-cell-receipt-without-finalization"
    )
    assert result["cell_count"] == 1
    assert result["cell_receipt_hashes"] == [receipt["cell_receipt_hash"]]
    assert paths["receipt"].read_bytes() == receipt_bytes
    recovered = harness._load_finalization_prefix(
        work_root=work_root,
        receipts=[receipt],
        check=cast(dict[str, object], fixture["check"]),
    )[0]
    assert recovered["schema"] == harness.RECOVERED_CELL_FINALIZATION_SCHEMA
    assert recovered["recovery_kind"] == "durable-cell-receipt-without-finalization"
    assert recovered["timing_measurement_available"] is False
    assert recovered["measured_active_wall_ns"] is None
    assert recovered["within_admission_charge"] is False
    assert result["cell_finalization_hashes"] == [recovered["finalization_hash"]]
    assert len(harness._validate_exposures(cast(Path, fixture["exposure"]))) == 1
    monkeypatch.setattr(harness, "_boot_identity", lambda: "simulated-new-boot")
    monkeypatch.setattr(harness.time, "perf_counter_ns", lambda: 10**18)
    resumed = harness.execute(
        harness_source_expected=expected_harness,
        output=output,
        work_root=work_root,
        exposure=cast(Path, fixture["exposure"]),
        recordings=tmp_path / "recordings",
        environments=tmp_path / "environments",
        build_000_root=tmp_path / "build000",
        build_001_root=tmp_path / "build001",
        stage08_result=tmp_path / "stage08.json",
        stage08_exposure=tmp_path / "stage08-exposure.jsonl",
    )
    assert resumed == result


def _aggregate_receipts() -> list[dict[str, object]]:
    receipts: list[dict[str, object]] = []
    for cell in build_matrix():
        levels = int(
            cell.variant is Variant.BUILD_001_FULL
            and cell.seed == 7
            and cell.game.stable_name in {"tr87", "r11l"}
        )
        receipt = seal_object(
            {
                **_execution_identity(),
                "schema": CELL_RECEIPT_SCHEMA,
                "status": CellStatus.SUCCESS.value,
                "normal_termination_definition": harness.NORMAL_TERMINATION_DEFINITION,
                "mechanism_provenance": None,
                "evidence_label": "local-public",
                "cell_id": cell.cell_id,
                "cell_spec_hash": cell.spec_hash,
                "game_id": cell.game.game_id,
                "seed": cell.seed,
                "variant": cell.variant.value,
                "asset_sha256": cell.game.asset_sha256,
                "source_commit": cell.variant.source_commit,
                "result": {
                    "completed": levels > 0,
                    "environment_actions": 40 if cell.variant is Variant.BUILD_001_FULL else 80,
                    "levels_completed": levels,
                    "score_verified": True,
                },
                "recovered_failure_result": None,
                "resources": {
                    "child_cpu_seconds": 0.1,
                    "child_peak_rss_bytes": 1024,
                    "pre_receipt_active_wall_ns": 20,
                    "supervision_wall_ns": 10,
                    "worker_wall_seconds": 120.0,
                },
            },
            hash_field="cell_receipt_hash",
        )
        receipts.append(receipt)
    return receipts


def _aggregate_finalizations(
    receipts: list[dict[str, object]],
) -> list[dict[str, object]]:
    return [
        seal_object(
            {
                "schema": harness.CELL_FINALIZATION_SCHEMA,
                "admission_charge_ns": harness.CELL_ADMISSION_CHARGE_NS,
                "budget_accounting": "fixed-full-cell-admission-charge",
                "cell_id": cell.cell_id,
                "cell_spec_hash": cell.spec_hash,
                "cell_receipt_hash": receipt["cell_receipt_hash"],
                "cell_receipt_sha256": f"sha256:{cell.ordinal:064x}",
                "measurement_scope": "cell-preparation-start-through-durable-cell-receipt",
                "measured_active_wall_ns": 21,
                "normal_termination_definition": harness.NORMAL_TERMINATION_DEFINITION,
                "parent_evidence_hash": f"sha256:{cell.ordinal + 1:064x}",
                "parent_evidence_sha256": f"sha256:{cell.ordinal + 2:064x}",
                "within_admission_charge": True,
            },
            hash_field="finalization_hash",
        )
        for cell, receipt in zip(build_matrix(), receipts, strict=True)
    ]


def test_fixed_admission_charge_resists_coordinated_parent_wall_resealing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    receipt, _event, fixture = _materialize_cell_chain(tmp_path, monkeypatch)
    changed_receipt = copy.deepcopy(receipt)
    resources = cast(dict[str, object], changed_receipt["resources"])
    resources["pre_receipt_active_wall_ns"] = 10
    changed_receipt = seal_object(changed_receipt, hash_field="cell_receipt_hash")
    changed_finalization = copy.deepcopy(cast(dict[str, object], fixture["finalization"]))
    changed_finalization["cell_receipt_hash"] = changed_receipt["cell_receipt_hash"]
    changed_finalization["measured_active_wall_ns"] = 11
    changed_finalization = seal_object(changed_finalization, hash_field="finalization_hash")
    monkeypatch.setattr(harness, "_runtime_identity", lambda: fixture["runtime"])

    summary = harness._resource_summary(
        [changed_receipt],
        [changed_finalization],
        runtime_start=cast(dict[str, object], fixture["runtime"]),
        execution_complete=False,
    )

    assert summary["cumulative_admission_charge_ns"] == harness.CELL_ADMISSION_CHARGE_NS
    assert summary["cumulative_measured_active_wall_ns"] == 11
    assert summary["admission_accounting"] == "fixed-full-cell-admission-charge"


def test_terminal_output_overhead_cannot_escape_overall_run_wall(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    expected = cast(
        dict[str, object],
        cast(dict[str, object], _execution_identity()["harness_source"])["expected"],
    )
    monkeypatch.setattr(harness.time, "perf_counter_ns", lambda: 0)
    check_payload = _preflight_execution_identity()
    cast(dict[str, object], check_payload["harness_source"])["expected"] = expected
    check = _attach_fixture_clock(tmp_path, monkeypatch, check_payload)
    limit = int(harness.OVERALL_ACTIVE_WALL_SECONDS * 1_000_000_000)
    ticks = iter((0, 0, harness.TERMINAL_WRITE_RESERVE_NS + 1))
    monkeypatch.setattr(harness.time, "perf_counter_ns", lambda: next(ticks))
    output = tmp_path / "terminal.json"

    with pytest.raises(EvaluationError, match="crossed the overall active-wall boundary"):
        harness._write_terminal(
            output,
            seal_object(
                {
                    "schema": harness.AGGREGATE_SCHEMA,
                    "status": "PASS",
                    "resources": {
                        "cumulative_active_accounted_wall_ns": (
                            limit - harness.TERMINAL_WRITE_RESERVE_NS
                        )
                    },
                },
                hash_field="artifact_core_hash",
            ),
            check=check,
        )

    assert output.is_file()
    finalization = cast(dict[str, object], load_json(harness._terminal_finalization_path(output)))
    assert finalization["within_overall_active_wall"] is False
    assert finalization["active_after_durable_output_ns"] == limit + 1


def test_active_wall_clock_is_stable_across_downtime_and_reboot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    expected = cast(
        dict[str, object],
        cast(dict[str, object], _execution_identity()["harness_source"])["expected"],
    )
    base = {"harness_source": {"expected": expected}}
    monkeypatch.setattr(harness, "_boot_identity", lambda: "first-boot")
    first = harness._attach_run_clock(
        base,
        work_root=tmp_path,
        harness_binding_hash=expected["binding_hash"],
    )
    monkeypatch.setattr(harness, "_boot_identity", lambda: "new-boot")
    monkeypatch.setattr(harness.time, "perf_counter_ns", lambda: 10**18)
    resumed = harness._attach_run_clock(
        base,
        work_root=tmp_path,
        harness_binding_hash=expected["binding_hash"],
    )

    assert resumed == first
    clock = cast(dict[str, object], cast(dict[str, object], resumed["run_clock"])["receipt"])
    assert clock["interruption_downtime_excluded"] is True
    assert clock["reboot_stable"] is True
    assert clock["open_segment_conservative_charge_ns"] == harness.CELL_ADMISSION_CHARGE_NS


def _complete_terminal_fixture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[Path, Path, dict[str, object], list[dict[str, object]]]:
    exposure = tmp_path / "exposure.jsonl"
    for cell in build_matrix():
        harness._append_exposure(exposure, cell)
    source_000 = {
        "branch": "",
        "dirty_worktree": False,
        "first_party_source_sha256": "sha256:source-000",
        "git_commit": "0" * 40,
        "git_tree": "1" * 40,
        "root": "C:/fixture/build000",
        "passed": True,
    }
    source_001 = {
        "branch": "",
        "dirty_worktree": False,
        "first_party_source_sha256": "sha256:source-001",
        "git_commit": "2" * 40,
        "git_tree": "3" * 40,
        "root": "C:/fixture/build001",
        "passed": True,
    }
    runtime = {"cpu": "fixture", "executable": "C:/fixture/python.exe"}
    check_payload = {
        "schema": PREFLIGHT_SCHEMA,
        "status": "READY_NOT_EXECUTED",
        "gameplay_opened": False,
        "runtime_identity": runtime,
        "sources": {"build_000": source_000, "build_001": source_001},
        "assets": {"passed": True, "identities": []},
        "competition_integrity": {"build_000": {"passed": True}},
        "stage09_exposure_event_count": 96,
        **_preflight_execution_identity(),
    }
    check = seal_object(check_payload, hash_field="preflight_hash")
    monkeypatch.setattr(harness, "_runtime_identity", lambda: runtime)
    check = _attach_fixture_clock(tmp_path, monkeypatch, check)
    embedded_payload = dict(check)
    embedded_payload.pop("preflight_hash", None)
    embedded_payload["stage09_exposure_event_count"] = 0
    embedded = seal_object(embedded_payload, hash_field="preflight_hash")
    receipts = _aggregate_receipts()
    finalizations = _aggregate_finalizations(receipts)
    resources = harness._resource_summary(
        receipts,
        finalizations,
        runtime_start=runtime,
        execution_complete=True,
    )
    boundaries = _execution_identity()
    harness_boundary = cast(dict[str, object], boundaries["harness_source"])
    runtime_boundary = cast(dict[str, object], boundaries["runtime_environment"])
    prior_boundary = cast(dict[str, object], boundaries["prior_authority"])
    cache_boundary = cast(dict[str, object], boundaries["environment_cache"])
    execution_boundaries = harness._execution_boundaries(
        embedded,
        harness_end=cast(dict[str, object], harness_boundary["after"]),
        runtime_end=cast(dict[str, object], runtime_boundary["after"]),
        authority_end=cast(dict[str, object], prior_boundary["after"]),
        cache_end=cast(dict[str, object], cache_boundary["after"]),
    )
    terminal = aggregate(receipts, evidence_integrity=True, competition_integrity=True)
    terminal.update(
        {
            "preflight": embedded,
            "execution_complete": True,
            "expected_cell_count": 96,
            "cell_finalization_hashes": [item["finalization_hash"] for item in finalizations],
            "execution_boundaries": execution_boundaries,
            "resources": resources,
            "source_end": {"build_000": source_000, "build_001": source_001},
            "source_stable": True,
            "asset_end": check["assets"],
            "exposure_ledger_sha256": sha256_file(exposure),
            "holdout": dict(harness.SEALED_HOLDOUT),
        }
    )
    output = tmp_path / "terminal.json"
    harness._write_terminal(
        output,
        seal_object(terminal, hash_field="artifact_core_hash"),
        check=embedded,
    )
    monkeypatch.setattr(harness, "_load_receipt_prefix", lambda **_kwargs: receipts)
    monkeypatch.setattr(harness, "_load_finalization_prefix", lambda **_kwargs: finalizations)
    return output, exposure, check, receipts


def test_complete_terminal_verifier_returns_hash_bound_authority(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output, exposure, check, _receipts = _complete_terminal_fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(harness, "preflight", lambda **_kwargs: check)
    monkeypatch.setattr(harness, "_attach_run_clock", lambda *_args, **_kwargs: check)
    terminal = cast(dict[str, object], load_json(output))
    finalization_path = harness._terminal_finalization_path(output)
    finalization = cast(dict[str, object], load_json(finalization_path))

    verified = harness.verify_complete_terminal(
        source_root=harness.ROOT,
        attempt_root=tmp_path / "run-clock",
        output=output,
        exposure=exposure,
        expected_output_sha256=sha256_file(output),
        expected_artifact_core_hash=cast(str, terminal["artifact_core_hash"]),
        expected_terminal_finalization_sha256=sha256_file(finalization_path),
        expected_terminal_finalization_hash=cast(str, finalization["terminal_finalization_hash"]),
    )

    assert verified["schema"] == harness.TERMINAL_VERIFICATION_SCHEMA
    assert verified["passed"] is True
    assert verified["status"] == "PASS"
    assert verified["execution_complete"] is True
    assert verified["evidence_integrity"] is True
    assert verified["competition_integrity"] is True
    assert verify_object_hash(verified, hash_field="verification_hash")
    assert set(verified) == {
        "attempt_root",
        "competition_integrity",
        "evidence_integrity",
        "execution_complete",
        "exposure",
        "gate",
        "output",
        "passed",
        "prior_authority",
        "schema",
        "source_end",
        "source_root",
        "source_stable",
        "status",
        "terminal_finalization",
        "verification_hash",
        "work_authority",
    }
    output_authority = cast(dict[str, object], verified["output"])
    assert output_authority["sha256"] == sha256_file(output)
    assert output_authority["artifact_core_hash"] == terminal["artifact_core_hash"]
    work_authority = cast(dict[str, object], verified["work_authority"])
    assert work_authority["cell_count"] == len(build_matrix())
    assert work_authority["cell_receipt_hashes"] == terminal["cell_receipt_hashes"]
    assert work_authority["cell_finalization_hashes"] == terminal["cell_finalization_hashes"]
    assert set(work_authority) == {
        "cell_count",
        "cell_finalization_hashes",
        "cell_receipt_hashes",
        "matrix_hash",
    }
    authority = cast(dict[str, object], verified["prior_authority"])
    assert set(authority) == {
        "assurance_limitation",
        "build_001_package_only",
        "development_scans",
        "full_public_integrity_status",
        "holdout",
        "predeclaration",
        "prior_authority_hash",
    }
    assert set(cast(dict[str, object], authority["build_001_package_only"])) == {
        "candidate_set_recomputed",
        "file_sha256",
        "git_commit",
        "live_source_hashes_match",
        "package_only_passed",
        "policy_scan_covers_reachable_paths",
        "reachable_paths_recomputed",
        "receipt_sha256",
        "status",
    }
    assert set(cast(dict[str, object], authority["development_scans"])) == {
        "build_000_finding_count",
        "build_000_passed",
        "build_001_finding_count",
        "build_001_passed",
        "development_identity_count",
        "identifier_list_hash",
        "identifier_string_count",
        "identity_values_disclosed",
    }
    assert set(cast(dict[str, object], authority["holdout"])) == {
        "file_sha256",
        "identities_loaded",
        "manifest_loaded_as_metadata",
        "pinned_manifest_sha256",
        "public_holdout_gameplay_events",
        "status",
    }

    with pytest.raises(EvaluationError, match="output file hash changed"):
        harness.verify_complete_terminal(
            source_root=harness.ROOT,
            attempt_root=tmp_path / "run-clock",
            output=output,
            exposure=exposure,
            expected_output_sha256="sha256:" + "f" * 64,
            expected_artifact_core_hash=cast(str, terminal["artifact_core_hash"]),
            expected_terminal_finalization_sha256=sha256_file(finalization_path),
            expected_terminal_finalization_hash=cast(
                str, finalization["terminal_finalization_hash"]
            ),
        )


def test_complete_failed_mechanism_terminal_retains_evidence_authority(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output, exposure, check, _receipts = _complete_terminal_fixture(tmp_path, monkeypatch)
    terminal = cast(dict[str, Any], load_json(output))
    terminal.pop("artifact_core_hash")
    terminal["status"] = "FAILED_MECHANISM"
    gate = cast(dict[str, object], terminal["gate"])
    gate["distinct_new_completed_games"] = False
    terminal = seal_object(terminal, hash_field="artifact_core_hash")
    output.write_bytes(canonical_json_bytes(terminal))
    wall = cast(dict[str, object], terminal["run_active_wall"])
    active = cast(int, wall["active_before_output_ns"])
    finalization = harness._terminal_finalization_payload(
        output=output,
        terminal=terminal,
        check=check,
        active_after_output_ns=active,
        recovery_kind=None,
    )
    finalization_path = harness._terminal_finalization_path(output)
    finalization_path.write_bytes(canonical_json_bytes(finalization))
    monkeypatch.setattr(harness, "preflight", lambda **_kwargs: check)
    monkeypatch.setattr(harness, "_attach_run_clock", lambda *_args, **_kwargs: check)
    monkeypatch.setattr(harness, "_load_existing_terminal", lambda **_kwargs: terminal)

    verified = harness.verify_complete_terminal(
        source_root=harness.ROOT,
        attempt_root=tmp_path / "run-clock",
        output=output,
        exposure=exposure,
        expected_output_sha256=sha256_file(output),
        expected_artifact_core_hash=cast(str, terminal["artifact_core_hash"]),
        expected_terminal_finalization_sha256=sha256_file(finalization_path),
        expected_terminal_finalization_hash=cast(str, finalization["terminal_finalization_hash"]),
    )

    assert verified["passed"] is True
    assert verified["status"] == "FAILED_MECHANISM"
    assert verified["evidence_integrity"] is True
    assert verified["competition_integrity"] is True


def test_crash_after_pass_output_before_finalization_cannot_earn_authority(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output, exposure, check, _receipts = _complete_terminal_fixture(tmp_path, monkeypatch)
    finalization_path = harness._terminal_finalization_path(output)
    finalization_path.unlink()

    with pytest.raises(EvaluationError, match="claimed terminal"):
        harness._load_existing_terminal(
            output=output,
            work_root=tmp_path / "work",
            exposure=exposure,
            check=check,
        )

    recovered = cast(dict[str, object], load_json(finalization_path))
    assert recovered["recovery_kind"] == (
        "terminal-output-durable-finalization-missing-after-interruption"
    )
    assert recovered["timing_measurement_available"] is False
    assert recovered["terminal_authority_passed"] is False
    assert verify_object_hash(recovered, hash_field="terminal_finalization_hash")


def test_complete_terminal_verifier_is_read_only_when_finalization_is_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output, exposure, check, _receipts = _complete_terminal_fixture(tmp_path, monkeypatch)
    terminal = cast(dict[str, object], load_json(output))
    finalization_path = harness._terminal_finalization_path(output)
    finalization = cast(dict[str, object], load_json(finalization_path))
    finalization_sha256 = sha256_file(finalization_path)
    finalization_path.unlink()
    monkeypatch.setattr(harness, "preflight", lambda **_kwargs: check)
    monkeypatch.setattr(harness, "_attach_run_clock", lambda *_args, **_kwargs: check)

    with pytest.raises(EvaluationError, match="finalization receipt is absent"):
        harness.verify_complete_terminal(
            source_root=harness.ROOT,
            attempt_root=tmp_path / "run-clock",
            output=output,
            exposure=exposure,
            expected_output_sha256=sha256_file(output),
            expected_artifact_core_hash=cast(str, terminal["artifact_core_hash"]),
            expected_terminal_finalization_sha256=finalization_sha256,
            expected_terminal_finalization_hash=cast(
                str, finalization["terminal_finalization_hash"]
            ),
        )

    assert not finalization_path.exists()


def test_complete_terminal_verifier_is_read_only_when_run_clock_is_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output, exposure, check, _receipts = _complete_terminal_fixture(tmp_path, monkeypatch)
    terminal = cast(dict[str, object], load_json(output))
    finalization_path = harness._terminal_finalization_path(output)
    finalization = cast(dict[str, object], load_json(finalization_path))
    clock_path = tmp_path / "run-clock" / "run-clock.json"
    clock_path.unlink()
    monkeypatch.setattr(harness, "preflight", lambda **_kwargs: check)

    with pytest.raises(EvaluationError, match="run clock receipt is absent"):
        harness.verify_complete_terminal(
            source_root=harness.ROOT,
            attempt_root=tmp_path / "run-clock",
            output=output,
            exposure=exposure,
            expected_output_sha256=sha256_file(output),
            expected_artifact_core_hash=cast(str, terminal["artifact_core_hash"]),
            expected_terminal_finalization_sha256=sha256_file(finalization_path),
            expected_terminal_finalization_hash=cast(
                str, finalization["terminal_finalization_hash"]
            ),
        )

    assert not clock_path.exists()


@pytest.mark.parametrize("projection", ["source_end", "asset_end", "exposure_hash"])
def test_rehashed_complete_terminal_projection_tamper_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, projection: str
) -> None:
    output, exposure, check, _receipts = _complete_terminal_fixture(tmp_path, monkeypatch)
    terminal = cast(dict[str, object], load_json(output))
    if projection == "source_end":
        source_end = cast(dict[str, object], terminal["source_end"])
        build_000 = cast(dict[str, object], source_end["build_000"])
        build_000["git_commit"] = "f" * 40
    elif projection == "asset_end":
        cast(dict[str, object], terminal["asset_end"])["passed"] = False
    else:
        terminal["exposure_ledger_sha256"] = "sha256:" + "f" * 64
    _write(output, seal_object(terminal, hash_field="artifact_core_hash"))

    with pytest.raises(EvaluationError, match=r"changed|does not reconstruct exactly"):
        harness._load_existing_terminal(
            output=output,
            work_root=tmp_path / "work",
            exposure=exposure,
            check=check,
        )


def test_complete_terminal_rejects_live_exposure_prefix_extension(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output, exposure, check, _receipts = _complete_terminal_fixture(tmp_path, monkeypatch)
    harness._append_exposure(exposure, build_matrix()[0])

    with pytest.raises(EvaluationError, match="exposure count exceeds"):
        harness._load_existing_terminal(
            output=output,
            work_root=tmp_path / "work",
            exposure=exposure,
            check=check,
        )


def test_worker_refuses_rehashed_wrong_source_before_environment_import(tmp_path: Path) -> None:
    spec = {
        "schema": WORKER_SPEC_SCHEMA,
        "cell_id": "cell",
        "cell_spec_hash": "sha256:cell",
        "first_party_source_sha256": "sha256:source",
        "public_worker_spec": {},
        "source_commit": "0" * 40,
        "source_root": tmp_path.as_posix(),
        "source_tree": "0" * 40,
    }
    sealed = seal_object(spec, hash_field="worker_spec_hash")
    spec_path = tmp_path / "spec.json"
    spec_path.write_bytes(canonical_json_bytes(sealed))
    worker = Path(harness.__file__).resolve().with_name("_stage09_development_worker.py")

    result = subprocess.run(
        [
            sys.executable,
            "-I",
            str(worker),
            "--spec",
            str(spec_path),
            "--result",
            str(tmp_path / "result.json"),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=10.0,
    )

    assert result.returncode != 0
    assert not (tmp_path / "result.json").exists()


def test_preflight_source_mismatch_stops_before_runtime_or_environment_import(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    identity = _execution_identity()
    harness_boundary = identity["harness_source"]
    assert isinstance(harness_boundary, dict)
    expected = harness_boundary["expected"]
    observed = copy.deepcopy(harness_boundary["before"])
    assert isinstance(expected, dict)
    assert isinstance(observed, dict)
    predicates = observed["predicates"]
    assert isinstance(predicates, dict)
    predicates["files"] = False
    observed["passed"] = False
    observed = seal_object(observed, hash_field="observation_hash")
    monkeypatch.setattr(harness, "_harness_source_identity", lambda _expected: observed)

    def forbidden(*_args: object, **_kwargs: object) -> NoReturn:
        raise AssertionError("source mismatch crossed the pre-import boundary")

    for name in (
        "_runtime_environment_identity",
        "_prior_authority",
        "_environment_cache_identity",
        "validate_predeclaration_bytes",
        "_source_identity",
        "_all_assets",
        "_validate_exposures",
    ):
        monkeypatch.setattr(harness, name, forbidden)

    result = harness.preflight(
        harness_source_expected=expected,
        output=tmp_path / "result.json",
        work_root=tmp_path / "work",
        exposure=tmp_path / "exposure.jsonl",
        recordings=tmp_path / "recordings",
        environments=tmp_path / "environments",
        build_000_root=tmp_path / "build000",
        build_001_root=tmp_path / "build001",
        stage08_result=tmp_path / "stage08.json",
        stage08_exposure=tmp_path / "stage08-exposure.jsonl",
        prior_integrity_receipt=tmp_path / "integrity-001.json",
        build_000_integrity_receipt=tmp_path / "integrity-000.json",
        enforce_official_paths=False,
    )

    assert result["status"] == "FAILED_INFRASTRUCTURE"
    assert result["gameplay_opened"] is False
    assert result["runtime_environment"] == {
        "expected": harness.EXPECTED_RUNTIME_ENVIRONMENT,
        "start": None,
        "status": "NOT_EVALUATED_HARNESS_SOURCE_FAILED",
    }


def test_record_file_tamper_is_detected_without_record_mutation(tmp_path: Path) -> None:
    package = tmp_path / "fixture_pkg/module.py"
    package.parent.mkdir(parents=True)
    original = b"original-runtime-bytes"
    package.write_bytes(original)
    encoded = base64.urlsafe_b64encode(hashlib.sha256(original).digest()).rstrip(b"=").decode()
    record = tmp_path / "fixture_pkg-1.0.dist-info/RECORD"
    record.parent.mkdir(parents=True)
    record.write_text(
        f"fixture_pkg/module.py,sha256={encoded},{len(original)}\n"
        "fixture_pkg-1.0.dist-info/RECORD,,\n",
        encoding="utf-8",
        newline="",
    )

    class FakeDistribution:
        files = (Path("fixture_pkg/module.py"), Path("fixture_pkg-1.0.dist-info/RECORD"))

        @staticmethod
        def locate_file(item: object) -> Path:
            return tmp_path / str(item)

    before = worker._distribution_record_identity(cast(Any, FakeDistribution()))
    record_hash = before["record_sha256"]
    package.write_bytes(b"tampered-runtime-bytes")
    after = worker._distribution_record_identity(cast(Any, FakeDistribution()))

    assert before["record_verification_passed"] is True
    assert after["record_sha256"] == record_hash
    assert after["record_verification_passed"] is False
    assert after["installed_files_sha256"] != before["installed_files_sha256"]


def test_runtime_inventory_drift_cannot_reach_sdk_import_probe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    expected = copy.deepcopy(harness.EXPECTED_RUNTIME_ENVIRONMENT)
    distributions = cast(dict[str, object], expected["distributions"])
    monkeypatch.setattr(
        worker,
        "_distribution_file_identity",
        lambda name, _prefixes: copy.deepcopy(cast(dict[str, object], distributions[name])),
    )
    inventory = copy.deepcopy(cast(dict[str, object], expected["installed_distribution_inventory"]))
    names = cast(list[dict[str, str]], inventory["names_and_versions"])
    names.append({"name": "unexpected-runtime", "version": "1.0"})
    inventory["distribution_count"] = cast(int, inventory["distribution_count"]) + 1
    monkeypatch.setattr(worker, "_installed_distribution_inventory", lambda: inventory)
    monkeypatch.setattr(
        worker,
        "_python_base_identity",
        lambda: copy.deepcopy(cast(dict[str, object], expected["python_base"])),
    )
    versions = cast(dict[str, str], expected["critical_versions"])
    monkeypatch.setattr(worker.importlib.metadata, "version", lambda name: versions[name])
    real_sha = worker._sha256_file

    def expected_hash(path: Path) -> str:
        resolved = path.resolve()
        if resolved == Path(sys.executable).resolve():
            return cast(str, expected["executable_sha256"])
        if resolved.name == "scorecard.py":
            scorer = cast(dict[str, object], expected["scorer"])
            return cast(str, scorer["sha256"])
        if resolved.name == "upstream.lock.json":
            return cast(str, expected["upstream_lock_sha256"])
        if resolved.name == "uv.lock":
            return cast(str, expected["uv_lock_sha256"])
        return real_sha(path)

    monkeypatch.setattr(worker, "_sha256_file", expected_hash)

    def forbidden(*_args: object, **_kwargs: object) -> NoReturn:
        raise AssertionError("runtime drift reached the SDK import probe")

    monkeypatch.setattr(worker.subprocess, "run", forbidden)
    observation = worker._runtime_observation(tmp_path, expected)

    assert observation["passed"] is False
    actual = cast(dict[str, object], observation["actual"])
    assert actual["sdk_import_probe"] is False
    predicates = cast(dict[str, object], observation["predicates"])
    assert predicates["installed_distribution_inventory"] is False


@pytest.mark.parametrize(
    "drift",
    ["installed-file", "extra-distribution", "python-stdlib", "bootstrap-boundary"],
)
def test_runtime_binding_rejects_rehashed_full_environment_drift(drift: str) -> None:
    boundaries = _execution_identity()
    runtime = cast(dict[str, object], boundaries["runtime_environment"])
    expected = cast(dict[str, object], runtime["expected"])
    changed = copy.deepcopy(cast(dict[str, object], runtime["before"]))
    actual = cast(dict[str, object], changed["actual"])
    if drift == "installed-file":
        distributions = cast(dict[str, object], actual["distributions"])
        numpy = cast(dict[str, object], distributions["numpy"])
        numpy["installed_files_sha256"] = "sha256:" + "f" * 64
    elif drift == "extra-distribution":
        inventory = cast(dict[str, object], actual["installed_distribution_inventory"])
        inventory["distribution_count"] = cast(int, inventory["distribution_count"]) + 1
    elif drift == "python-stdlib":
        python_base = cast(dict[str, object], actual["python_base"])
        stdlib = cast(dict[str, object], python_base["stdlib"])
        stdlib["files_sha256"] = "sha256:" + "f" * 64
    else:
        bootstrap_boundary = cast(dict[str, object], actual["bootstrap_boundary"])
        bootstrap_boundary["supervisor_pre_first_party_runtime_validation"] = False
    changed = seal_object(changed, hash_field="observation_hash")

    with pytest.raises(EvaluationError, match="runtime environment identity changed"):
        harness.validate_runtime_environment_observation(changed, expected=expected)


@pytest.mark.parametrize("drift", ["commit", "dirty", "file"])
def test_stdlib_bootstrap_rejects_source_drift_before_runtime_probe(
    monkeypatch: pytest.MonkeyPatch,
    drift: str,
) -> None:
    commit = "a" * 40
    tree = "b" * 40
    files = {
        relative: bootstrap._sha256_file(bootstrap.ROOT / relative)
        for relative in (
            "scripts/_stage09_supervisor_bootstrap.py",
            "scripts/measure_development_recovery.py",
            "scripts/_stage09_development_worker.py",
            "src/arc3/evaluation/development_recovery.py",
        )
    }
    supplied = dict(files)
    if drift == "file":
        supplied["scripts/measure_development_recovery.py"] = "sha256:" + "f" * 64

    def fake_git(*arguments: str) -> str:
        values = {
            ("rev-parse", "--show-toplevel"): str(bootstrap.ROOT),
            ("rev-parse", "HEAD"): "c" * 40 if drift == "commit" else commit,
            ("rev-parse", "HEAD^{tree}"): tree,
            ("branch", "--show-current"): "",
            ("status", "--porcelain=v1", "--untracked-files=all"): (
                " M source.py" if drift == "dirty" else ""
            ),
        }
        return values[arguments]

    monkeypatch.setattr(bootstrap, "_git", fake_git)

    def forbidden(*_args: object, **_kwargs: object) -> NoReturn:
        raise AssertionError("source drift reached runtime validation")

    monkeypatch.setattr(bootstrap.subprocess, "run", forbidden)
    arguments = [
        "--expected-harness-commit",
        commit,
        "--expected-harness-tree",
        tree,
        "--expected-bootstrap-sha256",
        supplied["scripts/_stage09_supervisor_bootstrap.py"],
        "--expected-supervisor-sha256",
        supplied["scripts/measure_development_recovery.py"],
        "--expected-worker-sha256",
        supplied["scripts/_stage09_development_worker.py"],
        "--expected-protocol-sha256",
        supplied["src/arc3/evaluation/development_recovery.py"],
        "--expected-runtime-binding-file-sha256",
        "sha256:" + "0" * 64,
    ]

    with pytest.raises(RuntimeError, match="source authority changed"):
        bootstrap.main(arguments)


def test_stdlib_bootstrap_rejects_runtime_binding_bytes_before_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commit = "a" * 40
    tree = "b" * 40
    files = {
        relative: bootstrap._sha256_file(bootstrap.ROOT / relative)
        for relative in (
            "scripts/_stage09_supervisor_bootstrap.py",
            "scripts/measure_development_recovery.py",
            "scripts/_stage09_development_worker.py",
            "src/arc3/evaluation/development_recovery.py",
        )
    }

    def fake_git(*arguments: str) -> str:
        values = {
            ("rev-parse", "--show-toplevel"): str(bootstrap.ROOT),
            ("rev-parse", "HEAD"): commit,
            ("rev-parse", "HEAD^{tree}"): tree,
            ("branch", "--show-current"): "",
            ("status", "--porcelain=v1", "--untracked-files=all"): "",
        }
        return values[arguments]

    monkeypatch.setattr(bootstrap, "_git", fake_git)

    def forbidden(*_args: object, **_kwargs: object) -> NoReturn:
        raise AssertionError("runtime binding drift reached the import probe")

    monkeypatch.setattr(bootstrap.subprocess, "run", forbidden)
    arguments = [
        "--expected-harness-commit",
        commit,
        "--expected-harness-tree",
        tree,
        "--expected-bootstrap-sha256",
        files["scripts/_stage09_supervisor_bootstrap.py"],
        "--expected-supervisor-sha256",
        files["scripts/measure_development_recovery.py"],
        "--expected-worker-sha256",
        files["scripts/_stage09_development_worker.py"],
        "--expected-protocol-sha256",
        files["src/arc3/evaluation/development_recovery.py"],
        "--expected-runtime-binding-file-sha256",
        "sha256:" + "0" * 64,
    ]

    with pytest.raises(RuntimeError, match="runtime binding changed"):
        bootstrap.main(arguments)
