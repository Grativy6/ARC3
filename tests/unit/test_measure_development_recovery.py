"""Stage 09 parent-supervisor boundary tests without public gameplay."""

from __future__ import annotations

import argparse
import copy
import subprocess
import sys
from pathlib import Path
from typing import Any, NoReturn, cast

import pytest
import scripts._stage09_development_worker as worker
import scripts.measure_development_recovery as harness

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
        "score": 0.0 if success else None,
        "levels_completed": 1 if success else 0,
        "completed": success,
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
        "trace": {"replay_verified": True} if success else None,
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
    )
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
    stdout = canonical_json_bytes(
        {"cell_id": cell.cell_id, "raw_receipt_hash": raw["receipt_hash"], "status": raw["status"]}
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
    receipt = harness._cell_receipt(
        cell,
        spec=spec,
        exposure_event=event,
        supervision=supervision,
        raw_path=paths["raw"],
        asset_after=_asset(cell),
        parent_active_wall_ns=20,
        spec_path=paths["spec"],
        launch_receipt_path=paths["launch"],
        authorization_path=paths["authorization"],
        supervision_receipt_path=paths["supervision"],
    )
    _write(paths["receipt"], receipt)
    return receipt, event, {"runtime": runtime, "work_root": work_root, "exposure": exposure}


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
        parent_active_wall_ns=120_000_010_000,
    )

    assert receipt["schema"] == CELL_RECEIPT_SCHEMA
    assert receipt["status"] == expected.value
    result = cast(dict[str, object], receipt["result"])
    assert result["environment_actions"] == (
        3 if expected is CellStatus.CONTROLLER_WALL_TIMEOUT else 0
    )
    assert verify_object_hash(receipt, hash_field="cell_receipt_hash")


def test_validated_policy_failure_is_mechanism_and_reconstructs(
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
        cell=cell,
        exposure_event=event,
    )

    assert receipt["status"] == CellStatus.MECHANISM_FAILURE.value
    assert reconstructed == receipt
    failure = receipt["failure"]
    assert isinstance(failure, str)
    assert failure.startswith("raw controller failure")


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
        },
        hash_field="preflight_hash",
    )
    output = tmp_path / "terminal.json"
    terminal = harness._failure_terminal(
        output=output,
        check=preflight,
        receipts=[receipt],
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
            cell=cell,
            exposure_event=event,
        )


def test_orphan_pid_reuse_is_not_terminated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _receipt, event, fixture = _materialize_cell_chain(tmp_path, monkeypatch)
    cell = build_matrix()[0]
    paths = harness._cell_paths(cast(Path, fixture["work_root"]), cell)
    paths["receipt"].unlink()
    monkeypatch.setattr(harness, "_process_creation_token", lambda _pid: "reused-process-token")

    def forbidden(_pid: int) -> NoReturn:
        raise AssertionError("PID-reused process was terminated")

    monkeypatch.setattr(harness, "_terminate_orphan_pid", forbidden)
    orphan = harness._seal_orphan_boundary(
        work_root=cast(Path, fixture["work_root"]),
        recordings=tmp_path / "recordings",
        environments=tmp_path / "environments",
        build_000_root=tmp_path / "build000",
        build_001_root=tmp_path / "build001",
        runtime_identity=cast(dict[str, object], fixture["runtime"]),
        cell=cell,
        exposure_event=event,
    )

    assert orphan["passed"] is True
    assert orphan["state"] == "pid-reused-original-not-running"
    assert orphan["termination"] is None


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
        cell=cell,
        exposure_event=event,
    )

    assert orphan["passed"] is True
    assert orphan["state"] == "pre-environment-handshake-aborted"


def test_rehashed_partial_terminal_cannot_be_promoted_to_pass(tmp_path: Path) -> None:
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
        },
        hash_field="preflight_hash",
    )
    output = tmp_path / "terminal.json"
    terminal = harness._failure_terminal(
        output=output,
        check=preflight,
        receipts=[],
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


def test_exposed_cell_without_terminal_receipt_is_never_relaunched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    event = {"event_hash": "sha256:already-exposed"}
    monkeypatch.setattr(harness, "_official_paths", lambda **_kwargs: None)
    monkeypatch.setattr(
        harness,
        "preflight",
        lambda **_kwargs: {
            "status": "READY_NOT_EXECUTED",
            "runtime_identity": {},
            "sources": {},
            "competition_integrity": {},
        },
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
                "schema": CELL_RECEIPT_SCHEMA,
                "status": CellStatus.SUCCESS.value,
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
                "resources": {
                    "child_cpu_seconds": 0.1,
                    "child_peak_rss_bytes": 1024,
                    "parent_active_wall_ns": 20,
                    "supervision_wall_ns": 10,
                    "worker_wall_seconds": 120.0,
                },
            },
            hash_field="cell_receipt_hash",
        )
        receipts.append(receipt)
    return receipts


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
    }
    check = seal_object(check_payload, hash_field="preflight_hash")
    embedded_payload = dict(check_payload)
    embedded_payload["stage09_exposure_event_count"] = 0
    embedded = seal_object(embedded_payload, hash_field="preflight_hash")
    receipts = _aggregate_receipts()
    resources = harness._resource_summary(receipts, runtime_start=runtime, execution_complete=True)
    terminal = aggregate(receipts, evidence_integrity=True, competition_integrity=True)
    terminal.update(
        {
            "preflight": embedded,
            "execution_complete": True,
            "expected_cell_count": 96,
            "resources": resources,
            "source_end": {"build_000": source_000, "build_001": source_001},
            "source_stable": True,
            "asset_end": check["assets"],
            "exposure_ledger_sha256": sha256_file(exposure),
            "holdout": dict(harness.SEALED_HOLDOUT),
        }
    )
    output = tmp_path / "terminal.json"
    _write(output, seal_object(terminal, hash_field="artifact_core_hash"))
    monkeypatch.setattr(harness, "_load_receipt_prefix", lambda **_kwargs: receipts)
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
