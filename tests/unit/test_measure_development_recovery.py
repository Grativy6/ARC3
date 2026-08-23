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
    exposure = tmp_path / "exposure.jsonl"
    event = harness._append_exposure(exposure, cell)
    token = "fixture-launch-token"
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
            predicates["build_001_integrity"] = False
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
            "command": list(command),
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
        measured_active_wall_ns=21,
    )
    _write(paths["finalization"], finalization)
    return (
        receipt,
        event,
        {
            "check": _preflight_execution_identity(),
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
            "launch_token": "aborted-token",
            "pid": 123,
            "reason": "launch-authorization-unavailable-or-invalid",
        },
        hash_field="worker_abort_hash",
    )
    _write(paths["abort"], abort)

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
    check = _attach_fixture_clock(
        tmp_path,
        monkeypatch,
        {"harness_source": {"expected": expected}},
    )
    limit = int(harness.OVERALL_ACTIVE_WALL_SECONDS * 1_000_000_000)
    ticks = iter((limit - harness.TERMINAL_WRITE_RESERVE_NS, limit + 1))
    monkeypatch.setattr(harness.time, "perf_counter_ns", lambda: next(ticks))
    output = tmp_path / "terminal.json"

    with pytest.raises(EvaluationError, match="crossed the overall active-wall boundary"):
        harness._write_terminal(
            output,
            seal_object(
                {"schema": harness.AGGREGATE_SCHEMA, "status": "PASS"},
                hash_field="artifact_core_hash",
            ),
            check=check,
        )

    assert output.is_file()
    finalization = cast(dict[str, object], load_json(harness._terminal_finalization_path(output)))
    assert finalization["within_overall_active_wall"] is False
    assert finalization["elapsed_after_durable_output_ns"] == limit + 1


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
