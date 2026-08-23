"""Stage 09 parent-supervisor boundary tests without public gameplay."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import NoReturn

import pytest
import scripts.measure_development_recovery as harness

from arc3.errors import EvaluationError
from arc3.evaluation.artifacts import canonical_json_bytes, seal_object, verify_object_hash
from arc3.evaluation.development_recovery import (
    CELL_RECEIPT_SCHEMA,
    PREFLIGHT_SCHEMA,
    WORKER_SPEC_SCHEMA,
    CellStatus,
    DevelopmentCell,
    Variant,
    build_matrix,
)
from arc3.evaluation.public import PublicExposureLedger


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
    assert verify_object_hash(receipt, hash_field="cell_receipt_hash")


def test_raw_worker_failure_is_infrastructure_not_mechanism(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cell = build_matrix()[0]
    raw_path = tmp_path / "raw.json"
    raw_path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(
        harness,
        "_raw_result",
        lambda *_args: {
            "status": "failure",
            "failure": {"kind": "PolicyError", "message": "bounded failure"},
            "receipt_hash": "sha256:raw",
            "score": {"verified": False, "completed": False, "levels_completed": 0},
            "metrics": {
                "environment_actions": 3,
                "total_cpu_seconds": 0.2,
                "peak_rss_bytes": 4096,
            },
        },
    )

    receipt = harness._cell_receipt(
        cell,
        spec={"worker_spec_hash": "sha256:spec"},
        exposure_event={"event_hash": "sha256:exposure"},
        supervision={"timed_out": False, "launch_error": None, "returncode": 0, "wall_ns": 10},
        raw_path=raw_path,
        asset_after=_asset(cell),
        parent_active_wall_ns=20,
    )

    assert receipt["status"] == CellStatus.INFRASTRUCTURE_FAILURE.value
    failure = receipt["failure"]
    assert isinstance(failure, str)
    assert failure.startswith("raw worker failure")


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
