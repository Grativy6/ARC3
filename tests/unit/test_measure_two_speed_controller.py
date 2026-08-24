from __future__ import annotations

import copy
import importlib.metadata
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, cast

import pytest
import scripts.measure_two_speed_controller as harness
from scripts.measure_two_speed_controller import (
    DEFAULT_BUILD_000_ROOT,
    DEFAULT_ENVIRONMENTS_DIR,
    DEFAULT_EXPOSURE_LEDGER,
    DEFAULT_OUTPUT,
    DEFAULT_RECORDINGS_ROOT,
    DEFAULT_WORK_ROOT,
    OVERALL_WALL_SECONDS,
    WORKER_RESULT_SCHEMA,
    WORKER_SPEC_SCHEMA,
    WORKER_WALL_SECONDS,
    _append_exposure,
    _artifact_inventory,
    _atomic_create_bytes,
    _atomic_create_json,
    _expected_configuration,
    _interrupted_parent_receipt,
    _make_parent_receipt,
    _official_runtime_preflight,
    _project_worker_result,
    _remaining_worker_timeout,
    _require_official_paths,
    _result_from_receipt,
    _seal_parent_receipt,
    _supervise_worker,
    _validate_stage08_exposures,
    _wall_resource_receipt,
    _worker_environment,
    build_worker_spec,
    measure_two_speed_controller,
)

from arc3.errors import EvaluationError
from arc3.evaluation.two_speed_measurement import (
    BUILD_000_PRODUCTION_COMMIT,
    BUILD_000_PRODUCTION_TREE,
    MEASUREMENT_MATRIX_SHA256,
    MEASUREMENT_PLAN_SHA256,
    PREDECLARATION_SHA256,
    BoundaryStatus,
    CellStatus,
    EvidenceAvailability,
    FailureDomain,
    MeasurementVariant,
    WorkAvailability,
    build_measurement_matrix,
    seal_canonical_object,
)
from arc3.trace.canonical import normalize_json, sha256_json
from arc3.types import JSONValue


def _source(root: Path, *, build_000: bool) -> dict[str, object]:
    return {
        "git_commit": (BUILD_000_PRODUCTION_COMMIT if build_000 else "1" * 40),
        "git_tree": BUILD_000_PRODUCTION_TREE if build_000 else "2" * 40,
        "root": root.resolve().as_posix(),
    }


def _spec(tmp_path: Path, ordinal: int = 0) -> tuple[Any, dict[str, object]]:
    cell = build_measurement_matrix()[ordinal]
    spec = build_worker_spec(
        cell,
        work_root=tmp_path / "work",
        recordings_root=tmp_path / "recordings",
        environments_dir=tmp_path / "environments",
        current_source=_source(tmp_path / "build001", build_000=False),
        build_000_source=_source(tmp_path / "build000", build_000=True),
    )
    return cell, spec


def _work_unavailable() -> dict[str, object]:
    return {
        "availability": WorkAvailability.UNAVAILABLE_AT_FROZEN_SOURCE.value,
        "cache_hits": None,
        "cache_invalidations": None,
        "cache_misses": None,
        "compilation_invocations": None,
        "prediction_invocations": None,
        "retrodicted_transitions": None,
        "search_expanded_nodes": None,
        "simulation_invocations": None,
    }


def _raw_success(cell: Any, spec: dict[str, object]) -> dict[str, object]:
    recordings_dir = Path(str(spec["recordings_dir"]))
    recordings_dir.mkdir(parents=True, exist_ok=True)
    (recordings_dir / "fixture.jsonl").write_text("{}\n", encoding="utf-8")
    recordings = _artifact_inventory(recordings_dir)
    recordings["path"] = recordings.pop("root")
    action: dict[str, JSONValue] = {"coordinate": None, "name": "ACTION1"}
    action_identity = sha256_json(action)
    observation = {
        "available_actions": ["ACTION1"],
        "frame_digest": "sha256:" + "a" * 64,
        "full_reset": False,
        "game_id": cell.development.game_id,
        "levels_completed": 0,
        "returned_action": None,
        "state": "NOT_FINISHED",
        "win_levels": 1,
    }
    consequence = {
        **observation,
        "frame_digest": "sha256:" + "b" * 64,
        "levels_completed": 1,
        "returned_action": action,
        "state": "WIN",
    }
    boundary = {
        "acknowledged_by_controller": True,
        "action": action,
        "action_chain_valid": True,
        "action_ordinal": 0,
        "adapter_crossed": True,
        "boundary_status": BoundaryStatus.NORMAL.value,
        "checkpoint_cpu_ns": 3,
        "checkpoint_wall_ns": 3,
        "choose_checkpoint_cpu_ns": 1,
        "choose_checkpoint_wall_ns": 1,
        "choose_cpu_inclusive_ns": 11,
        "choose_cpu_ns": 10,
        "choose_wall_inclusive_ns": 11,
        "choose_wall_ns": 10,
        "consequence": consequence,
        "consequence_cpu_inclusive_ns": 22,
        "consequence_cpu_ns": 20,
        "consequence_event_id": "evt-consequence",
        "consequence_event_hash": "sha256:" + "c" * 64,
        "consequence_frame_hashes": [consequence["frame_digest"]],
        "consequence_observation_event_hash": "sha256:" + "d" * 64,
        "consequence_observation_event_id": "evt-after-observation",
        "consequence_returned": True,
        "consequence_wall_inclusive_ns": 22,
        "consequence_wall_ns": 20,
        "controller_total_cpu_ns": 33,
        "controller_total_wall_ns": 33,
        "decision_id": "decision-1",
        "deep_trigger_receipts": [],
        "environment_action_identity": action_identity,
        "failure_phase": None,
        "is_reset": False,
        "observation_before": observation,
        "observation_event_id": "evt-observation",
        "ordered_triggers": [],
        "reasoning_path": None,
        "reasoning_terminal_receipt": None,
        "selected_event_id": "evt-selected",
        "submission_ordinal": 0,
        "submitted_event_id": "evt-submitted",
        "trace_consequence_event_id": "evt-consequence",
        "trace_consequence_observation_event_id": "evt-after-observation",
        "validated_event_id": "evt-validated",
        "work": _work_unavailable(),
    }
    source_endpoint = {
        "build_001_baseline_ancestor": True,
        "dirty_worktree": False,
        "git_commit": spec["source_commit"],
        "git_tree": spec["source_tree"],
        "source_root": spec["source_root"],
    }
    asset = {
        "aggregate_sha256": cell.development.asset_aggregate_sha256,
        "files": [],
        "game_id": cell.development.game_id,
        "passed": True,
        "source_semantically_inspected": False,
    }
    payload: dict[str, object] = {
        "action_counts": {"acknowledged": 1, "attempted": 1, "returned": 1, "submitted": 1},
        "action_sequence": [action],
        "actions": [boundary],
        "attempted_boundaries": [boundary],
        "asset_after": asset,
        "asset_before": asset,
        "cadence": {
            "action_receipts_complete": True,
            "available": False,
            "deep_completed_count": None,
            "deep_selected_count": None,
            "typed_deep_receipts_complete": None,
        },
        "cell": cell.to_dict(),
        "cell_id": cell.cell_id,
        "checkpoint": {
            "path": (Path(str(spec["checkpoint_root"])) / "fixture.json").as_posix(),
            "restore_valid": True,
        },
        "checkpoint_bytes": 10,
        "completed_at": "2026-08-22T00:00:00Z",
        "configuration": _expected_configuration(cell.variant),
        "controller_fault_count": 0,
        "controller_fault_identities": [],
        "counts": {
            "acknowledged_consequences": 1,
            "adapter_submissions": 1,
            "classified_attempts": 1,
            "decision_attempts": 1,
            "predicates": {},
            "returned_consequences": 1,
            "success_exact_counts": True,
            "unclassified_attempts": 0,
        },
        "development_identity": cell.development.to_dict(),
        "environment_actions": 1,
        "evidence_label": "local-public",
        "failure": None,
        "failure_domain": None,
        "failure_phase": None,
        "final_observation": consequence,
        "memory": {
            "invalid_sample_count": 0,
            "measurement_valid": True,
            "peak_rss_bytes": 100,
            "sample_count": 2,
            "source": "arc3.profiling.runtime.process_memory_sample",
            "sources": ["arc3.profiling.runtime.process_memory_sample"],
        },
        "network_attempt_count": 0,
        "network_guard": {},
        "peak_rss_bytes": 100,
        "primary_timing_scope": "non-reset normally-returned boundaries; resets remain gated evidence",
        "receipt_integrity_valid": True,
        "recordings": recordings,
        "reset_boundaries": [],
        "reset_counts": {"acknowledged": 0, "attempted": 0, "returned": 0, "submitted": 0},
        "resets": 0,
        "resources_valid": True,
        "returned_consequences": [consequence],
        "runtime_environment": {
            "expected": {
                "ALL_PROXY": "",
                "HTTP_PROXY": "",
                "HTTPS_PROXY": "",
                "NO_PROXY": "*",
                "PIP_NO_INDEX": "1",
                "PYTHONHASHSEED": "0",
                "PYTHONNOUSERSITE": "1",
                "UV_OFFLINE": "1",
            },
            "observed": {
                "ALL_PROXY": "",
                "HTTP_PROXY": "",
                "HTTPS_PROXY": "",
                "NO_PROXY": "*",
                "PIP_NO_INDEX": "1",
                "PYTHONHASHSEED": "0",
                "PYTHONNOUSERSITE": "1",
                "UV_OFFLINE": "1",
            },
            "passed": True,
        },
        "runtime_identity": {},
        "schema": WORKER_RESULT_SCHEMA,
        "score": {
            "completed": True,
            "levels_completed": 1,
            "official_run_actions": 1,
            "official_run_levels_completed": 1,
            "official_run_resets": 0,
            "official_run_state": "WIN",
            "score": 1.0,
            "scorer": "fixture",
            "verified": True,
        },
        "source_identity": {
            "end": source_endpoint,
            "exact_identity_stable": True,
            "start": source_endpoint,
        },
        "spec_hash": spec["spec_hash"],
        "status": "success",
        "submitted_action_identities": [action_identity],
        "submitted_boundaries": [boundary],
        "total_cpu_ns": 40,
        "total_wall_ns": 50,
        "trace": {
            "byte_length": 20,
            "path": Path(str(spec["trace_root"])).resolve().as_posix(),
            "replay_verified": True,
        },
        "validation_failures": [],
        "variant": cell.variant.value,
    }
    return dict(
        seal_canonical_object(
            cast(dict[str, JSONValue], normalize_json(payload)),
            hash_field="worker_result_hash",
        )
    )


def _reseal_worker_result(value: dict[str, object]) -> dict[str, object]:
    return dict(
        seal_canonical_object(
            cast(dict[str, JSONValue], normalize_json(value)),
            hash_field="worker_result_hash",
        )
    )


def _supervisor_fixture(
    streams_root: Path,
    *,
    launch_error: str | None = None,
    returncode: int | None = 0,
    timed_out: bool = False,
) -> dict[str, object]:
    termination = (
        {
            "attempted": True,
            "direct_fallback_used": False,
            "error": None,
            "method": "windows-taskkill-tree" if os.name == "nt" else "posix-killpg",
            "returncode": 0 if os.name == "nt" else None,
            "stderr_bytes": 0,
            "stderr_sha256": (
                "sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
            ),
            "stdout_bytes": 0,
            "stdout_sha256": (
                "sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
            ),
        }
        if timed_out
        else None
    )
    return {
        "command": ["python", "fixture-worker.py"],
        "launch_error": launch_error,
        "returncode": returncode,
        "stderr_bytes": 0,
        "stderr_path": (streams_root / "stderr.bin").resolve().as_posix(),
        "stderr_sha256": "sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        "stdout_bytes": 0,
        "stdout_path": (streams_root / "stdout.bin").resolve().as_posix(),
        "stdout_sha256": "sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        "timed_out": timed_out,
        "timeout_seconds": 120.0,
        "termination": termination,
        "wall_ns": 1,
    }


def test_worker_spec_binds_frozen_plan_source_and_cell_layout(tmp_path: Path) -> None:
    cell, spec = _spec(tmp_path)

    assert spec["schema"] == WORKER_SPEC_SCHEMA
    assert spec["cell"] == cell.to_dict()
    assert spec["measurement_matrix_sha256"] == MEASUREMENT_MATRIX_SHA256
    assert spec["measurement_plan_sha256"] == MEASUREMENT_PLAN_SHA256
    assert spec["predeclaration_sha256"] == PREDECLARATION_SHA256
    assert spec["source_commit"] == BUILD_000_PRODUCTION_COMMIT
    assert Path(str(spec["recordings_dir"])).parent.parent == Path(str(spec["recordings_root"]))


def test_worker_environment_is_offline_deterministic_and_drops_secrets() -> None:
    result = _worker_environment(
        {
            "PATH": "fixture-path",
            "OPENAI_API_KEY": "must-not-cross",
            "HTTPS_PROXY": "https://proxy.invalid",
        }
    )

    assert result["PATH"] == "fixture-path"
    assert "OPENAI_API_KEY" not in result
    assert result["HTTPS_PROXY"] == ""
    assert result["NO_PROXY"] == "*"
    assert result["PYTHONHASHSEED"] == "0"
    assert result["UV_OFFLINE"] == "1"


def test_projection_uses_raw_ordinals_and_phase_counts_fail_closed(tmp_path: Path) -> None:
    cell, spec = _spec(tmp_path)
    raw = _raw_success(cell, spec)
    result = _project_worker_result(
        raw,
        cell=cell,
        spec=spec,
        supervisor={"returncode": 0, "timed_out": False},
    )

    assert result.status is CellStatus.SUCCESS
    assert result.action_counts is not None
    assert result.action_counts.attempted == result.action_counts.submitted == 1
    assert result.actions[0].submission_ordinal == 0
    assert result.actions[0].controller_total_wall_ns == 33

    tampered = dict(raw)
    tampered["action_counts"] = {
        "acknowledged": 1,
        "attempted": 2,
        "returned": 1,
        "submitted": 1,
    }
    tampered = dict(
        seal_canonical_object(
            cast(dict[str, JSONValue], normalize_json(tampered)),
            hash_field="worker_result_hash",
        )
    )
    with pytest.raises(EvaluationError, match="action counts"):
        _project_worker_result(
            tampered,
            cell=cell,
            spec=spec,
            supervisor={"returncode": 0, "timed_out": False},
        )


@pytest.mark.parametrize(
    "tamper",
    [
        "returned-consequences",
        "final-observation",
        "rss",
        "configuration",
        "score-levels",
        "recording-identity",
    ],
)
def test_projection_recomputes_full_boundary_resource_and_configuration_binding(
    tmp_path: Path,
    tamper: str,
) -> None:
    cell, spec = _spec(tmp_path / tamper)
    raw = _raw_success(cell, spec)
    changed = copy.deepcopy(raw)
    if tamper == "returned-consequences":
        changed["returned_consequences"] = []
    elif tamper == "final-observation":
        final = cast(dict[str, object], changed["final_observation"])
        final["state"] = "NOT_FINISHED"
    elif tamper == "rss":
        changed["peak_rss_bytes"] = 101
    elif tamper == "configuration":
        configuration = cast(dict[str, object], changed["configuration"])
        configuration["controller_preset"] = "tampered"
    elif tamper == "score-levels":
        score = cast(dict[str, object], changed["score"])
        score["official_run_levels_completed"] = 0
    else:
        recordings = cast(dict[str, object], changed["recordings"])
        recordings["path"] = (tmp_path / "escaped-recordings").resolve().as_posix()

    with pytest.raises(EvaluationError):
        _project_worker_result(
            _reseal_worker_result(changed),
            cell=cell,
            spec=spec,
            supervisor={"returncode": 0, "timed_out": False},
        )


def test_interrupted_raw_result_is_preserved_but_never_accepted(tmp_path: Path) -> None:
    cell, spec = _spec(tmp_path)
    raw_path = Path(str(spec["cell_root"])) / "worker-result.json"
    _atomic_create_json(raw_path, _raw_success(cell, spec))
    streams_root = tmp_path / "streams"
    receipt = _interrupted_parent_receipt(
        cell=cell,
        spec=spec,
        raw_path=raw_path,
        streams_root=streams_root,
    )

    result, errors, retained = _result_from_receipt(
        cell=cell,
        spec=spec,
        receipt=receipt,
        cell_root=raw_path.parent,
        streams_root=streams_root,
        holdout_exposure_count=0,
        exposure_spec_hash=str(spec["spec_hash"]),
    )

    assert result.status is CellStatus.INTERRUPTED
    assert result.failure_kind == "interrupted"
    assert result.failure_domain is FailureDomain.INFRASTRUCTURE
    assert result.evidence_availability is EvidenceAvailability.UNAVAILABLE
    assert result.action_counts is None
    assert result.reset_counts is None
    assert result.trace_bytes is None
    assert result.controller_faults is None
    assert result.network_attempt_count is None
    assert errors == []
    assert retained is not None


def test_missing_exposure_link_forces_infrastructure_projection_failure(tmp_path: Path) -> None:
    cell, spec = _spec(tmp_path)
    raw_path = Path(str(spec["cell_root"])) / "worker-result.json"
    _atomic_create_json(raw_path, _raw_success(cell, spec))
    streams_root = tmp_path / "streams"
    _atomic_create_bytes(streams_root / "stdout.bin", b"")
    _atomic_create_bytes(streams_root / "stderr.bin", b"")
    supervisor = _supervisor_fixture(streams_root)
    receipt = _make_parent_receipt(
        cell=cell,
        spec=spec,
        supervisor=supervisor,
        raw_path=raw_path,
        streams_root=streams_root,
    )

    result, errors, _ = _result_from_receipt(
        cell=cell,
        spec=spec,
        receipt=receipt,
        cell_root=raw_path.parent,
        streams_root=streams_root,
        holdout_exposure_count=0,
        exposure_spec_hash=None,
    )

    assert result.status is CellStatus.CRASH
    assert result.failure_kind == "WorkerResultValidationError"
    assert errors == ["matching development exposure event is missing or changed"]


def test_exposure_ledger_accepts_only_unique_frozen_development_cells(tmp_path: Path) -> None:
    cell, spec = _spec(tmp_path)
    ledger = tmp_path / "public-exposure.jsonl"
    _append_exposure(ledger, cell=cell, spec_hash=str(spec["spec_hash"]))

    events = _validate_stage08_exposures(ledger)
    assert len(events) == 1
    first_payload = cast(dict[str, object], events[0]["payload"])
    assert first_payload["partition"] == "development"

    _append_exposure(ledger, cell=cell, spec_hash=str(spec["spec_hash"]))
    with pytest.raises(EvaluationError, match="undeclared boundary"):
        _validate_stage08_exposures(ledger)

    out_of_prefix = tmp_path / "out-of-prefix.jsonl"
    later_cell, later_spec = _spec(tmp_path / "later", ordinal=1)
    _append_exposure(
        out_of_prefix,
        cell=later_cell,
        spec_hash=str(later_spec["spec_hash"]),
    )
    with pytest.raises(EvaluationError, match="contiguous prefix"):
        _validate_stage08_exposures(out_of_prefix)


class _TimeoutProcess:
    returncode = -9

    def __init__(self) -> None:
        self.calls = 0
        self.killed = False

    def communicate(self, timeout: float | None = None) -> tuple[bytes, bytes]:
        self.calls += 1
        if self.calls == 1:
            assert timeout is not None
            raise subprocess.TimeoutExpired(
                cmd=["fixture"], timeout=timeout, output=b"prefix", stderr=b"error"
            )
        return b"prefix-tail", b"error-tail"

    def kill(self) -> None:
        self.killed = True


def test_supervisor_kills_timeout_and_preserves_exact_stream_bytes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    process = _TimeoutProcess()
    monkeypatch.setattr(subprocess, "Popen", lambda *_args, **_kwargs: process)

    def terminate(received: object) -> dict[str, object]:
        assert received is process
        process.kill()
        return {
            "attempted": True,
            "direct_fallback_used": True,
            "error": None,
            "method": "windows-taskkill-tree" if harness.os.name == "nt" else "posix-killpg",
            "returncode": 0 if harness.os.name == "nt" else None,
            "stderr_bytes": 0,
            "stderr_sha256": "sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
            "stdout_bytes": 0,
            "stdout_sha256": "sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        }

    monkeypatch.setattr(harness, "_terminate_process_tree", terminate)

    receipt = _supervise_worker(
        ["fixture"],
        environment={},
        streams_root=tmp_path / "streams",
        timeout_seconds=0.5,
    )

    assert process.killed is True
    assert receipt["timed_out"] is True
    assert cast(dict[str, object], receipt["termination"])["attempted"] is True
    assert (tmp_path / "streams/stdout.bin").read_bytes() == b"prefix-tail"
    assert (tmp_path / "streams/stderr.bin").read_bytes() == b"error-tail"


def test_supervisor_timeout_terminates_the_worker_descendant_tree(tmp_path: Path) -> None:
    pid_path = (tmp_path / "descendant.pid").resolve()
    child_code = "import time; time.sleep(30)"
    parent_code = (
        "import pathlib,subprocess,sys,time;"
        "child=subprocess.Popen([sys.executable,'-c',sys.argv[2]]);"
        "pathlib.Path(sys.argv[1]).write_text(str(child.pid),encoding='utf-8');"
        "time.sleep(30)"
    )

    receipt = _supervise_worker(
        [str(Path(sys.executable).resolve()), "-c", parent_code, str(pid_path), child_code],
        environment=harness._worker_environment(os.environ),
        streams_root=tmp_path / "tree-streams",
        timeout_seconds=1.0,
    )

    assert receipt["timed_out"] is True
    assert pid_path.is_file()
    descendant_pid = int(pid_path.read_text(encoding="utf-8"))

    def descendant_alive() -> bool:
        if os.name != "nt":
            stat_path = Path(f"/proc/{descendant_pid}/stat")
            if stat_path.is_file():
                fields = stat_path.read_text(encoding="utf-8", errors="replace").split()
                if len(fields) > 2 and fields[2] == "Z":
                    return False
        try:
            os.kill(descendant_pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        except OSError as error:
            if os.name == "nt" and error.winerror == 87:
                return False
            raise
        return True

    deadline = time.monotonic() + 5.0
    while descendant_alive() and time.monotonic() < deadline:
        time.sleep(0.05)
    assert descendant_alive() is False


def test_remaining_worker_timeout_enforces_both_frozen_ceilings() -> None:
    assert _remaining_worker_timeout(0) == WORKER_WALL_SECONDS
    elapsed = int((OVERALL_WALL_SECONDS - 5.0) * 1_000_000_000)
    assert _remaining_worker_timeout(elapsed) == pytest.approx(5.0)
    limit_ns = int(OVERALL_WALL_SECONDS * 1_000_000_000)
    assert _remaining_worker_timeout(limit_ns - 1) == pytest.approx(1e-9)


def test_incomplete_wall_accounting_is_explicit_null_and_fail_closed() -> None:
    receipt = _wall_resource_receipt(123, complete=False)

    assert receipt["cumulative_active_wall_ns"] is None
    assert receipt["observed_lower_bound_active_wall_ns"] == 123
    assert receipt["wall_measurement_complete"] is False
    assert receipt["wall_within_limit"] is False


def test_parent_receipt_separates_timeout_from_infrastructure_failures(
    tmp_path: Path,
) -> None:
    cell, spec = _spec(tmp_path)
    raw_path = Path(str(spec["cell_root"])) / "worker-result.json"
    streams_root = tmp_path / "streams"
    _atomic_create_bytes(streams_root / "stdout.bin", b"")
    _atomic_create_bytes(streams_root / "stderr.bin", b"")

    timeout = _make_parent_receipt(
        cell=cell,
        spec=spec,
        supervisor=_supervisor_fixture(streams_root, returncode=-9, timed_out=True),
        raw_path=raw_path,
        streams_root=streams_root,
    )
    launch_error = _make_parent_receipt(
        cell=cell,
        spec=spec,
        supervisor=_supervisor_fixture(
            streams_root,
            launch_error="OSError: fixture",
            returncode=None,
        ),
        raw_path=raw_path,
        streams_root=streams_root,
    )

    assert timeout["classification"] == "timeout"
    assert launch_error["classification"] == "launch-error"


def test_failed_process_tree_termination_is_infrastructure_evidence(
    tmp_path: Path,
) -> None:
    cell, spec = _spec(tmp_path)
    raw_path = Path(str(spec["cell_root"])) / "worker-result.json"
    streams_root = tmp_path / "streams"
    _atomic_create_bytes(streams_root / "stdout.bin", b"")
    _atomic_create_bytes(streams_root / "stderr.bin", b"")
    supervisor = _supervisor_fixture(streams_root, returncode=-9, timed_out=True)
    termination = cast(dict[str, object], supervisor["termination"])
    termination["error"] = "PermissionError: fixture tree-kill denied"
    receipt = _make_parent_receipt(
        cell=cell,
        spec=spec,
        supervisor=supervisor,
        raw_path=raw_path,
        streams_root=streams_root,
    )

    result, errors, _raw = _result_from_receipt(
        cell=cell,
        spec=spec,
        receipt=receipt,
        cell_root=raw_path.parent,
        streams_root=streams_root,
        holdout_exposure_count=0,
        exposure_spec_hash=str(spec["spec_hash"]),
    )

    assert receipt["classification"] == "termination-failure"
    assert result.failure_domain is FailureDomain.INFRASTRUCTURE
    assert result.failure_kind == "termination-failure"
    assert errors == []


def test_parent_recomputes_classification_and_rejects_a_resealed_false_timeout(
    tmp_path: Path,
) -> None:
    cell, spec = _spec(tmp_path)
    raw_path = Path(str(spec["cell_root"])) / "worker-result.json"
    _atomic_create_json(raw_path, _raw_success(cell, spec))
    streams_root = tmp_path / "streams"
    _atomic_create_bytes(streams_root / "stdout.bin", b"")
    _atomic_create_bytes(streams_root / "stderr.bin", b"")
    supervisor = _supervisor_fixture(streams_root)
    receipt = _make_parent_receipt(
        cell=cell,
        spec=spec,
        supervisor=supervisor,
        raw_path=raw_path,
        streams_root=streams_root,
    )
    cast(dict[str, object], receipt["supervisor"])["timed_out"] = True
    receipt["classification"] = "timeout"
    tampered_receipt = _seal_parent_receipt(receipt)

    result, errors, _raw = _result_from_receipt(
        cell=cell,
        spec=spec,
        receipt=tampered_receipt,
        cell_root=raw_path.parent,
        streams_root=streams_root,
        holdout_exposure_count=0,
        exposure_spec_hash=str(spec["spec_hash"]),
    )

    assert result.status is CellStatus.CRASH
    assert result.failure_kind == "WorkerResultValidationError"
    assert any("terminal raw result conflicts" in error for error in errors)


@pytest.mark.parametrize(
    ("failure_phase", "false_domain"),
    [
        ("adapter-step", "MECHANISM"),
        ("worker-bootstrap", "RESOURCE"),
        ("controller-choose", "RESOURCE"),
    ],
)
def test_parent_recomputes_resealed_worker_failure_domain(
    tmp_path: Path,
    failure_phase: str,
    false_domain: str,
) -> None:
    cell, spec = _spec(tmp_path)
    raw = _raw_success(cell, spec)
    raw.update(
        {
            "failure": {
                "kind": "RuntimeError",
                "message": "fixture terminal failure",
                "traceback": "fixture traceback",
            },
            "failure_domain": false_domain,
            "failure_phase": failure_phase,
            "status": "failure",
        }
    )
    raw = _reseal_worker_result(raw)
    raw_path = Path(str(spec["cell_root"])) / "worker-result.json"
    _atomic_create_json(raw_path, raw)
    streams_root = tmp_path / "streams"
    _atomic_create_bytes(streams_root / "stdout.bin", b"")
    _atomic_create_bytes(streams_root / "stderr.bin", b"")
    receipt = _make_parent_receipt(
        cell=cell,
        spec=spec,
        supervisor=_supervisor_fixture(streams_root, returncode=1),
        raw_path=raw_path,
        streams_root=streams_root,
    )

    result, errors, _raw = _result_from_receipt(
        cell=cell,
        spec=spec,
        receipt=receipt,
        cell_root=raw_path.parent,
        streams_root=streams_root,
        holdout_exposure_count=0,
        exposure_spec_hash=str(spec["spec_hash"]),
    )

    assert result.failure_domain is FailureDomain.INFRASTRUCTURE
    assert result.failure_kind == "WorkerResultValidationError"
    assert any("failure domain disagrees" in error for error in errors)


def test_parent_rejects_resealed_unsupervised_nonrecovery_receipt(tmp_path: Path) -> None:
    cell, spec = _spec(tmp_path)
    raw_path = Path(str(spec["cell_root"])) / "worker-result.json"
    _atomic_create_json(raw_path, _raw_success(cell, spec))
    streams_root = tmp_path / "streams"
    receipt = _interrupted_parent_receipt(
        cell=cell,
        spec=spec,
        raw_path=raw_path,
        streams_root=streams_root,
    )
    receipt["classification"] = None
    receipt["recovered_after_orchestrator_interruption"] = False

    result, errors, _raw = _result_from_receipt(
        cell=cell,
        spec=spec,
        receipt=_seal_parent_receipt(receipt),
        cell_root=raw_path.parent,
        streams_root=streams_root,
        holdout_exposure_count=0,
        exposure_spec_hash=str(spec["spec_hash"]),
    )

    assert result.status is CellStatus.CRASH
    assert result.failure_kind == "WorkerResultValidationError"
    assert any("must be an interruption recovery" in error for error in errors)


def test_official_paths_reject_redirected_evidence_and_split_source_authority(
    tmp_path: Path,
) -> None:
    with pytest.raises(EvaluationError, match="exact measured Build 001 source root"):
        _require_official_paths(
            output=DEFAULT_OUTPUT,
            work_root=DEFAULT_WORK_ROOT,
            exposure_ledger=DEFAULT_EXPOSURE_LEDGER,
            recordings_root=DEFAULT_RECORDINGS_ROOT,
            environments_dir=DEFAULT_ENVIRONMENTS_DIR,
            build_000_root=DEFAULT_BUILD_000_ROOT,
            build_001_root=tmp_path / "detached-source",
        )
    with pytest.raises(EvaluationError, match="paths differ"):
        _require_official_paths(
            output=tmp_path / "redirected.json",
            work_root=DEFAULT_WORK_ROOT,
            exposure_ledger=DEFAULT_EXPOSURE_LEDGER,
            recordings_root=DEFAULT_RECORDINGS_ROOT,
            environments_dir=DEFAULT_ENVIRONMENTS_DIR,
            build_000_root=DEFAULT_BUILD_000_ROOT,
            build_001_root=tmp_path / "detached-source",
        )
    with pytest.raises(EvaluationError, match="paths differ"):
        _require_official_paths(
            output=DEFAULT_OUTPUT,
            work_root=DEFAULT_WORK_ROOT,
            exposure_ledger=DEFAULT_EXPOSURE_LEDGER,
            recordings_root=tmp_path / "redirected-recordings",
            environments_dir=DEFAULT_ENVIRONMENTS_DIR,
            build_000_root=DEFAULT_BUILD_000_ROOT,
            build_001_root=tmp_path / "detached-source",
        )


def test_matrix_remains_balanced_twenty_cells() -> None:
    matrix = build_measurement_matrix()
    assert len(matrix) == 20
    assert [cell.variant for cell in matrix[:4]] == list(MeasurementVariant)


def _fake_execution_preflight(tmp_path: Path) -> dict[str, object]:
    current = _source(tmp_path / "build001", build_000=False)
    build_000 = _source(tmp_path / "build000", build_000=True)
    return {
        "build_000_source": build_000,
        "current_source": current,
        "development_asset": {"passed": True},
        "holdout": {"passed": True},
        "status": "READY_NOT_EXECUTED",
    }


def test_official_runtime_preflight_fails_before_exposure_when_packages_are_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def missing(_distribution: str) -> str:
        raise importlib.metadata.PackageNotFoundError

    monkeypatch.setattr(importlib.metadata, "version", missing)
    monkeypatch.setattr(
        harness,
        "_source_import_probe",
        lambda _root, *, label: {"label": label, "passed": True},
    )

    receipt = _official_runtime_preflight()

    assert receipt["passed"] is False
    assert receipt["adapter_bindings_valid"] is False
    assert receipt["observed_packages"] == {"arc-agi": None, "arcengine": None}


def test_official_runtime_preflight_requires_both_exact_source_import_probes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def probe(_root: Path, *, label: str) -> dict[str, object]:
        return {"label": label, "passed": label == "build-001"}

    monkeypatch.setattr(harness, "_source_import_probe", probe)

    receipt = _official_runtime_preflight(
        build_000_root=tmp_path / "build000",
        build_001_root=tmp_path / "build001",
    )

    assert receipt["passed"] is False
    assert "build_000-source-import-probe:failed" in cast(list[str], receipt["failures"])


@pytest.mark.parametrize(
    ("wall_complete", "execution_complete"),
    [(False, False), (True, True)],
)
def test_resume_revalidates_every_surviving_exposure_without_launch_or_artifact_mutation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    wall_complete: bool,
    execution_complete: bool,
) -> None:
    check = _fake_execution_preflight(tmp_path)
    work_root = tmp_path / "work"
    recordings_root = tmp_path / "recordings"
    environments_dir = tmp_path / "environments"
    output = tmp_path / "aggregate.json"
    ledger = tmp_path / "exposure.jsonl"
    matrix = build_measurement_matrix()
    exposed = (matrix[0], matrix[4])
    specs = {
        cell.cell_id: build_worker_spec(
            cell,
            work_root=work_root,
            recordings_root=recordings_root,
            environments_dir=environments_dir,
            current_source=cast(dict[str, object], check["current_source"]),
            build_000_source=cast(dict[str, object], check["build_000_source"]),
        )
        for cell in exposed
    }
    existing = {
        "build_000_source_start": check["build_000_source"],
        "cell_records": [],
        "commands": [["prior-invocation"]],
        "current_source_start": check["current_source"],
        "execution_complete": execution_complete,
        "matrix_hash": MEASUREMENT_MATRIX_SHA256,
        "resources": {
            "cumulative_active_wall_ns": 123 if wall_complete else None,
            "observed_lower_bound_active_wall_ns": 123,
            "wall_measurement_complete": wall_complete,
        },
    }
    captured: dict[str, object] = {}

    monkeypatch.setattr(harness, "preflight", lambda **_kwargs: check)
    monkeypatch.setattr(harness, "_load_existing_aggregate", lambda _path: existing)
    monkeypatch.setattr(
        harness,
        "_existing_exposure_cells",
        lambda _path: {cell_id: cast(str, spec["spec_hash"]) for cell_id, spec in specs.items()},
    )

    def aggregate(**kwargs: object) -> dict[str, object]:
        captured.clear()
        captured.update(kwargs)
        return {"execution_complete": False, "status": "FAILED_INFRASTRUCTURE"}

    monkeypatch.setattr(harness, "_aggregate_payload", aggregate)

    def forbidden_launch(*_args: object, **_kwargs: object) -> dict[str, object]:
        raise AssertionError("resume attempted a forbidden worker launch")

    monkeypatch.setattr(harness, "_supervise_worker", forbidden_launch)

    result = measure_two_speed_controller(
        output=output,
        work_root=work_root,
        exposure_ledger=ledger,
        recordings_root=recordings_root,
        environments_dir=environments_dir,
        build_000_root=tmp_path / "build000",
        build_001_root=tmp_path / "build001",
        command=["current-invocation"],
    )

    assert result["status"] == "FAILED_INFRASTRUCTURE"
    indexed = cast(list[object], captured["results"])
    assert len(indexed) == 2
    assert all(cast(Any, item).status is CellStatus.INTERRUPTED for item in indexed)
    assert captured["command_history"] == [["prior-invocation"], ["current-invocation"]]
    assert not (work_root / "specs").exists()
    assert not (work_root / "parent-receipts").exists()
    assert not recordings_root.exists()


def test_surviving_receipt_without_any_aggregate_loses_wall_authority_and_stops_launches(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    check = _fake_execution_preflight(tmp_path)
    work_root = tmp_path / "work"
    recordings_root = tmp_path / "recordings"
    output = tmp_path / "aggregate.json"
    ledger = tmp_path / "exposure.jsonl"
    cell = build_measurement_matrix()[0]
    spec = build_worker_spec(
        cell,
        work_root=work_root,
        recordings_root=recordings_root,
        environments_dir=tmp_path / "environments",
        current_source=cast(dict[str, object], check["current_source"]),
        build_000_source=cast(dict[str, object], check["build_000_source"]),
    )
    _atomic_create_json(harness._spec_path(work_root, cell), spec)
    _atomic_create_json(harness._parent_receipt_path(work_root, cell), {"fixture": True})
    captured: dict[str, object] = {}

    monkeypatch.setattr(harness, "preflight", lambda **_kwargs: check)
    monkeypatch.setattr(harness, "_load_existing_aggregate", lambda _path: None)
    monkeypatch.setattr(
        harness,
        "_existing_exposure_cells",
        lambda _path: {cell.cell_id: cast(str, spec["spec_hash"])},
    )

    def project(**kwargs: object) -> tuple[object, list[str], None]:
        projected_cell = cast(Any, kwargs["cell"])
        return (
            harness._synthetic_failure_result(
                projected_cell,
                status=CellStatus.TIMEOUT,
                failure_kind="fixture-resource-timeout",
                failure_phase="fixture-timeout",
                failure_domain=FailureDomain.RESOURCE,
            ),
            [],
            None,
        )

    monkeypatch.setattr(harness, "_result_from_receipt", project)

    def aggregate(**kwargs: object) -> dict[str, object]:
        captured.clear()
        captured.update(kwargs)
        return {"execution_complete": False, "status": "FAILED_INFRASTRUCTURE"}

    monkeypatch.setattr(harness, "_aggregate_payload", aggregate)

    def forbidden_launch(*_args: object, **_kwargs: object) -> dict[str, object]:
        raise AssertionError("lost-wall resume attempted a forbidden worker launch")

    monkeypatch.setattr(harness, "_supervise_worker", forbidden_launch)

    result = measure_two_speed_controller(
        output=output,
        work_root=work_root,
        exposure_ledger=ledger,
        recordings_root=recordings_root,
        environments_dir=tmp_path / "environments",
        build_000_root=tmp_path / "build000",
        build_001_root=tmp_path / "build001",
        command=["resume-without-aggregate"],
    )

    assert result["status"] == "FAILED_INFRASTRUCTURE"
    assert captured["wall_measurement_complete"] is False
    assert len(cast(list[object], captured["results"])) == 1


def test_projection_error_stops_later_fresh_launches_even_when_result_is_resource_typed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    check = _fake_execution_preflight(tmp_path)
    work_root = tmp_path / "work"
    output = tmp_path / "aggregate.json"
    ledger = tmp_path / "exposure.jsonl"
    launches = 0
    captured: dict[str, object] = {}
    launch_order: list[str] = []
    persisted_spec_hash: str | None = None

    monkeypatch.setattr(harness, "preflight", lambda **_kwargs: check)
    monkeypatch.setattr(harness, "_load_existing_aggregate", lambda _path: None)
    monkeypatch.setattr(harness, "_existing_exposure_cells", lambda _path: {})
    original_append_exposure = harness._append_exposure

    def append_exposure(
        exposure_ledger: Path,
        *,
        cell: object,
        spec_hash: str,
    ) -> dict[str, object]:
        nonlocal persisted_spec_hash
        receipt = original_append_exposure(
            exposure_ledger,
            cell=cast(Any, cell),
            spec_hash=spec_hash,
        )
        persisted_spec_hash = spec_hash
        launch_order.append("exposure-persisted")
        return receipt

    monkeypatch.setattr(harness, "_append_exposure", append_exposure)

    def launch(
        _command: object,
        *,
        environment: object,
        streams_root: Path,
        timeout_seconds: float,
    ) -> dict[str, object]:
        del environment, timeout_seconds
        nonlocal launches
        assert launch_order == ["exposure-persisted"]
        assert ledger.is_file()
        exposure_bytes = ledger.read_bytes()
        assert persisted_spec_hash is not None
        assert persisted_spec_hash.encode("utf-8") in exposure_bytes
        launch_order.append("worker-supervised")
        launches += 1
        _atomic_create_bytes(streams_root / "stdout.bin", b"")
        _atomic_create_bytes(streams_root / "stderr.bin", b"")
        return {
            "launch_error": None,
            "returncode": 1,
            "stderr_bytes": 0,
            "stderr_path": (streams_root / "stderr.bin").resolve().as_posix(),
            "stderr_sha256": "sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
            "stdout_bytes": 0,
            "stdout_path": (streams_root / "stdout.bin").resolve().as_posix(),
            "stdout_sha256": "sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
            "timed_out": False,
        }

    monkeypatch.setattr(harness, "_supervise_worker", launch)

    def project(**kwargs: object) -> tuple[object, list[str], None]:
        projected_cell = cast(Any, kwargs["cell"])
        return (
            harness._synthetic_failure_result(
                projected_cell,
                status=CellStatus.TIMEOUT,
                failure_kind="fixture-resource-timeout",
                failure_phase="fixture-timeout",
                failure_domain=FailureDomain.RESOURCE,
            ),
            ["fixture projection identity mismatch"],
            None,
        )

    monkeypatch.setattr(harness, "_result_from_receipt", project)

    def aggregate(**kwargs: object) -> dict[str, object]:
        captured.clear()
        captured.update(kwargs)
        return {"execution_complete": False, "status": "FAILED_INFRASTRUCTURE"}

    monkeypatch.setattr(harness, "_aggregate_payload", aggregate)

    measure_two_speed_controller(
        output=output,
        work_root=work_root,
        exposure_ledger=ledger,
        recordings_root=tmp_path / "recordings",
        environments_dir=tmp_path / "environments",
        build_000_root=tmp_path / "build000",
        build_001_root=tmp_path / "build001",
        command=["projection-error"],
    )

    assert launches == 1
    assert launch_order == ["exposure-persisted", "worker-supervised"]
    assert cast(list[dict[str, object]], captured["projection_failures"]) == [
        {
            "cell_id": build_measurement_matrix()[0].cell_id,
            "errors": ["fixture projection identity mismatch"],
        }
    ]


def test_failed_tree_termination_stops_all_later_fresh_launches(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    check = _fake_execution_preflight(tmp_path)
    work_root = tmp_path / "work"
    output = tmp_path / "aggregate.json"
    ledger = tmp_path / "exposure.jsonl"
    launches = 0
    captured: dict[str, object] = {}

    monkeypatch.setattr(harness, "preflight", lambda **_kwargs: check)
    monkeypatch.setattr(harness, "_load_existing_aggregate", lambda _path: None)
    monkeypatch.setattr(harness, "_existing_exposure_cells", lambda _path: {})

    def launch(
        _command: object,
        *,
        environment: object,
        streams_root: Path,
        timeout_seconds: float,
    ) -> dict[str, object]:
        del environment, timeout_seconds
        nonlocal launches
        launches += 1
        _atomic_create_bytes(streams_root / "stdout.bin", b"")
        _atomic_create_bytes(streams_root / "stderr.bin", b"")
        supervisor = _supervisor_fixture(streams_root, returncode=-9, timed_out=True)
        cast(dict[str, object], supervisor["termination"])["error"] = (
            "PermissionError: fixture tree-kill denied"
        )
        return supervisor

    monkeypatch.setattr(harness, "_supervise_worker", launch)

    def aggregate(**kwargs: object) -> dict[str, object]:
        captured.clear()
        captured.update(kwargs)
        return {"execution_complete": False, "status": "FAILED_INFRASTRUCTURE"}

    monkeypatch.setattr(harness, "_aggregate_payload", aggregate)

    measure_two_speed_controller(
        output=output,
        work_root=work_root,
        exposure_ledger=ledger,
        recordings_root=tmp_path / "recordings",
        environments_dir=tmp_path / "environments",
        build_000_root=tmp_path / "build000",
        build_001_root=tmp_path / "build001",
        command=["fresh-invocation"],
    )

    assert launches == 1
    results = cast(list[object], captured["results"])
    assert len(results) == 1
    assert cast(Any, results[0]).failure_domain is FailureDomain.INFRASTRUCTURE
    assert cast(Any, results[0]).failure_kind == "termination-failure"


@pytest.mark.parametrize("failed_integrity", ["asset_stable", "holdout_sealed", "source_stable"])
def test_interim_integrity_failure_stops_all_later_fresh_launches(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    failed_integrity: str,
) -> None:
    check = _fake_execution_preflight(tmp_path)
    work_root = tmp_path / "work"
    output = tmp_path / "aggregate.json"
    ledger = tmp_path / "exposure.jsonl"
    launches = 0

    monkeypatch.setattr(harness, "preflight", lambda **_kwargs: check)
    monkeypatch.setattr(harness, "_load_existing_aggregate", lambda _path: None)
    monkeypatch.setattr(harness, "_existing_exposure_cells", lambda _path: {})

    def launch(
        _command: object,
        *,
        environment: object,
        streams_root: Path,
        timeout_seconds: float,
    ) -> dict[str, object]:
        del environment, timeout_seconds
        nonlocal launches
        launches += 1
        _atomic_create_bytes(streams_root / "stdout.bin", b"")
        _atomic_create_bytes(streams_root / "stderr.bin", b"")
        return _supervisor_fixture(streams_root, returncode=-9, timed_out=True)

    monkeypatch.setattr(harness, "_supervise_worker", launch)

    def project(**kwargs: object) -> tuple[object, list[str], None]:
        projected_cell = cast(Any, kwargs["cell"])
        return (
            harness._synthetic_failure_result(
                projected_cell,
                status=CellStatus.TIMEOUT,
                failure_kind="fixture-resource-timeout",
                failure_phase="fixture-timeout",
                failure_domain=FailureDomain.RESOURCE,
            ),
            [],
            None,
        )

    monkeypatch.setattr(harness, "_result_from_receipt", project)

    def aggregate(**_kwargs: object) -> dict[str, object]:
        integrity = {
            "asset_stable": True,
            "holdout_sealed": True,
            "source_stable": True,
        }
        integrity[failed_integrity] = False
        return {
            "execution_complete": False,
            "source_and_external_integrity": integrity,
            "status": "FAILED_INFRASTRUCTURE",
        }

    monkeypatch.setattr(harness, "_aggregate_payload", aggregate)

    measure_two_speed_controller(
        output=output,
        work_root=work_root,
        exposure_ledger=ledger,
        recordings_root=tmp_path / "recordings",
        environments_dir=tmp_path / "environments",
        build_000_root=tmp_path / "build000",
        build_001_root=tmp_path / "build001",
        command=["integrity-drift"],
    )

    assert launches == 1
