from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
import scripts.measure_stage10_regression as harness

from arc3.evaluation.artifacts import atomic_write_json
from arc3.evaluation.stage10_regression import (
    Stage10Status,
    SuiteDisposition,
    SuiteSpec,
    SuiteValidation,
    suite_plan_hash,
)
from arc3.types import JSONValue

ROOT = Path(__file__).resolve().parents[2]
COMMIT = "2e78c258cfbee8be62462f61ed08ad04c00a8934"


def _identity() -> dict[str, JSONValue]:
    return {
        "clean_worktree": True,
        "commit": COMMIT,
        "exact_frozen_commit": True,
        "floor_commit": COMMIT,
        "floor_is_ancestor": True,
        "floor_tree": "4145356c116944bbd7c0c412771de9179ba22efe",
        "floor_tree_exact": True,
        "tree": "4145356c116944bbd7c0c412771de9179ba22efe",
        "verified": True,
    }


def test_default_preflight_is_non_playing_and_creates_no_attempt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempt = tmp_path / "attempt"
    output = tmp_path / "result.json"
    monkeypatch.setattr(harness, "_source_identity", lambda *_args: _identity())
    preflight, plan = harness.build_preflight(
        source_root=ROOT,
        python=Path(sys.executable),
        attempt_root=attempt,
        output=output,
        frozen_commit=COMMIT,
    )
    assert preflight["mode"] == "NON_PLAYING_PREFLIGHT"
    assert preflight["status"] == "PASS"
    assert len(plan) == 9
    assert not attempt.exists()
    assert not output.exists()


def test_started_without_completed_is_not_rerun(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempt = tmp_path / "attempt"
    output = tmp_path / "result.json"
    suite = SuiteSpec(
        suite_id="stage13-evaluate",
        command=(sys.executable, "-c", "raise SystemExit(99)"),
        timeout_seconds=1.0,
        allowed_returncodes=(0, 1),
        artifact_path=attempt / "artifact.json",
    )
    plan_hash = suite_plan_hash((suite,))
    attempt.mkdir()
    record = harness._new_ledger_record(
        [],
        suite=suite,
        state="STARTED",
        plan_hash=plan_hash,
    )
    harness._append_record(attempt / "invocations.jsonl", record)
    monkeypatch.setattr(harness, "_source_identity", lambda *_args: _identity())

    def forbidden(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("an interrupted child must never be rerun")

    monkeypatch.setattr(harness, "_run_child", forbidden)
    status = harness._execute(
        preflight={"plan_hash": plan_hash, "status": "PASS"},
        plan=(suite,),
        source_root=ROOT,
        attempt_root=attempt,
        output=output,
        frozen_commit=COMMIT,
    )
    assert status is Stage10Status.FAILED_INFRASTRUCTURE
    result = json.loads(output.read_text(encoding="utf-8"))
    assert result["infrastructure_failure"] == "interrupted-suite-not-rerun:stage13-evaluate"
    assert result["suite_validations"] == []


def test_parent_receipt_revalidation_detects_artifact_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempt = tmp_path / "attempt"
    logs = attempt / "logs"
    logs.mkdir(parents=True)
    artifact = attempt / "artifact.json"
    stdout = logs / "rule-change.stdout"
    stderr = logs / "rule-change.stderr"
    atomic_write_json(artifact, {"value": 1})
    stdout.write_bytes(b"out")
    stderr.write_bytes(b"")
    suite = SuiteSpec(
        suite_id="rule-change",
        command=(sys.executable, "worker.py"),
        timeout_seconds=1.0,
        allowed_returncodes=(0, 1),
        artifact_path=artifact,
    )
    validation = SuiteValidation(
        suite_id="rule-change",
        disposition=SuiteDisposition.FAILED_MECHANISM,
        predicates={"floor": False},
        measurements={"returncode": 1},
    )
    receipt = harness._parent_receipt(
        suite=suite,
        plan_hash="sha256:" + "b" * 64,
        source_identity=_identity(),
        returncode=1,
        timed_out=False,
        launch_error=None,
        wall_ns=1,
        stdout_path=stdout,
        stderr_path=stderr,
        validation=validation,
    )
    receipt_path = attempt / "receipt.json"
    atomic_write_json(receipt_path, receipt)
    monkeypatch.setattr(harness, "_validate_suite", lambda *_args, **_kwargs: validation)
    resumed = harness._resume_receipt(
        receipt_path,
        suite=suite,
        attempt_root=attempt,
        plan_hash="sha256:" + "b" * 64,
        source_identity=_identity(),
    )
    assert resumed == validation
    atomic_write_json(artifact, {"value": 2})
    try:
        harness._resume_receipt(
            receipt_path,
            suite=suite,
            attempt_root=attempt,
            plan_hash="sha256:" + "b" * 64,
            source_identity=_identity(),
        )
    except ValueError as error:
        assert "failed closed validation" in str(error)
    else:  # pragma: no cover
        raise AssertionError("artifact drift was accepted")
