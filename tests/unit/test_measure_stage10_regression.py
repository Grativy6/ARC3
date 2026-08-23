from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import cast

import pytest
import scripts._stage10_offline_child as child
import scripts.measure_stage10_regression as harness

from arc3.evaluation.artifacts import atomic_write_json, seal_object, sha256_file
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


def _runtime() -> dict[str, object]:
    return {"runtime_identity_sha256": "sha256:" + "c" * 64, "verified": True}


def _bound_runtime(launcher: Path, actual_executable: Path) -> dict[str, object]:
    return seal_object(
        {
            "actual_process_executable_path": str(actual_executable.resolve()),
            "actual_process_executable_sha256": sha256_file(actual_executable),
            "launcher_path": str(Path(os.path.abspath(launcher))),
            "launcher_sha256": sha256_file(launcher),
            "predicates": {"synthetic_binding": True},
            "process_launch_strategy": (
                harness._WINDOWS_PROCESS_LAUNCH_STRATEGY
                if os.name == "nt"
                else harness._POSIX_PROCESS_LAUNCH_STRATEGY
            ),
            "schema": harness._RUNTIME_IDENTITY_SCHEMA,
            "verified": True,
        },
        hash_field="runtime_identity_sha256",
    )


def _supervisor() -> dict[str, object]:
    return {
        "supervisor_import_identity_sha256": "sha256:" + "d" * 64,
        "verified": True,
    }


def test_stage10_git_authority_disables_replacements_and_caller_redirection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GIT_DIR", "redirected.git")
    monkeypatch.setenv("git_index_file", "redirected.index")
    captured: list[dict[str, str]] = []

    def fake_run(*_args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        captured.append(cast(dict[str, str], kwargs["env"]))
        return subprocess.CompletedProcess([], 0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    assert harness._git(ROOT, "status", "--porcelain=v1") == ""
    assert harness._git_success(ROOT, "rev-parse", "HEAD") is True
    assert len(captured) == 2
    for environment in captured:
        assert environment["GIT_NO_REPLACE_OBJECTS"] == "1"
        assert "GIT_DIR" not in environment
        assert "git_index_file" not in environment


def test_stage10_child_environment_disables_replacement_objects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GIT_DIR", "redirected.git")
    monkeypatch.setenv("__PYVENV_LAUNCHER__", "stale-launcher")
    environment = harness._safe_environment(ROOT)

    assert environment["GIT_NO_REPLACE_OBJECTS"] == "1"
    assert "GIT_DIR" not in environment
    assert "__PYVENV_LAUNCHER__" not in environment


def _integrity_inputs(tmp_path: Path) -> Path:
    path = tmp_path / "integrity-authority-inputs.json"
    payload: dict[str, object] = {
        "build_000_source_commit": "1" * 40,
        "build_000_source_root": (tmp_path / "build-000").resolve().as_posix(),
        "build_000_source_tree": "2" * 40,
        "development_identifier_list_sha256": "sha256:" + "3" * 64,
        "development_predeclaration_core_hash": "sha256:" + "4" * 64,
        "development_predeclaration_file_sha256": "sha256:" + "5" * 64,
        "development_predeclaration_path": (tmp_path / "stage09-predecl.json").resolve().as_posix(),
        "holdout_nonconsumption_path": (tmp_path / "holdout.json").resolve().as_posix(),
        "holdout_nonconsumption_sha256": "sha256:" + "6" * 64,
        "schema": "arc3.build-001.stage-10-integrity-authority-inputs.v0.1",
        "stage09_verification_file_sha256": "sha256:" + "7" * 64,
        "stage09_verification_hash": "sha256:" + "8" * 64,
        "stage09_verification_path": (tmp_path / "stage09-verification.json").resolve().as_posix(),
    }
    atomic_write_json(path, seal_object(payload, hash_field="authority_inputs_hash"))
    return path


def test_default_preflight_is_non_playing_and_creates_no_attempt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempt = tmp_path / "attempt"
    output = tmp_path / "result.json"
    monkeypatch.setattr(harness, "_source_identity", lambda *_args: _identity())
    monkeypatch.setattr(harness, "_runtime_identity", lambda *_args: _runtime())
    monkeypatch.setattr(harness, "_require_supervisor_import_origin", lambda *_args: _supervisor())
    integrity_inputs = _integrity_inputs(tmp_path)
    preflight, plan = harness.build_preflight(
        source_root=ROOT,
        python=Path(sys.executable),
        attempt_root=attempt,
        output=output,
        frozen_commit=COMMIT,
        integrity_inputs_path=integrity_inputs,
    )
    assert preflight["mode"] == "NON_PLAYING_PREFLIGHT"
    assert preflight["status"] == "PASS"
    assert len(plan) == 9
    assert not attempt.exists()
    assert not output.exists()


def test_integrity_inputs_reseal_cannot_cross_frozen_preflight(
    tmp_path: Path,
) -> None:
    integrity_inputs = _integrity_inputs(tmp_path)
    expected_hash = harness._integrity_inputs_summary(integrity_inputs)["authority_inputs_hash"]
    value = json.loads(integrity_inputs.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    value["build_000_source_commit"] = "9" * 40
    atomic_write_json(
        integrity_inputs,
        seal_object(value, hash_field="authority_inputs_hash"),
    )
    baseline = SuiteValidation(
        suite_id="competition-integrity",
        disposition=SuiteDisposition.PASS,
        predicates={},
        measurements={},
        errors=(),
    )

    observed = harness._with_integrity_continuity(
        baseline,
        source_root=ROOT,
        integrity_inputs_path=integrity_inputs,
        expected_integrity_inputs_hash=str(expected_hash),
    )

    assert observed.disposition is SuiteDisposition.FAILED_INFRASTRUCTURE
    assert observed.predicates["current_integrity_inputs_exact"] is False
    assert any("changed after frozen preflight" in error for error in observed.errors)


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
    launch = {
        "launch_receipt_hash": "sha256:" + "9" * 64,
        "launch_token": "sha256:" + "a" * 64,
        "pid": 1234,
        "process_creation_token": "synthetic-token",
    }
    authorization = seal_object(
        {
            "containment": {"kind": "synthetic"},
            "schema": "arc3.build-001.stage-10-launch-authorization.v0.1",
        },
        hash_field="authorization_hash",
    )
    record = harness._new_ledger_record(
        [],
        suite=suite,
        state="STARTED",
        plan_hash=plan_hash,
        launch=launch,
        authorization=authorization,
    )
    harness._append_record(attempt / "invocations.jsonl", record)
    assert (attempt / "invocations.jsonl").read_bytes().endswith(b"}\n")
    assert not (attempt / "invocations.jsonl").read_bytes().endswith(b"}\r\n")
    monkeypatch.setattr(harness, "_source_identity", lambda *_args: _identity())
    monkeypatch.setattr(harness, "_runtime_identity", lambda *_args: _runtime())
    monkeypatch.setattr(harness, "_recover_interrupted_suite", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(harness, "_require_supervisor_import_origin", lambda *_args: _supervisor())
    monkeypatch.setattr(harness, "_supervisor_import_identity", lambda *_args: _supervisor())
    integrity_inputs = _integrity_inputs(tmp_path)

    def forbidden(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("an interrupted child must never be rerun")

    monkeypatch.setattr(harness, "_run_child", forbidden)
    status = harness._execute(
        preflight={
            "plan_hash": plan_hash,
            "runtime_identity": _runtime(),
            "source_identity": _identity(),
            "status": "PASS",
            "supervisor_import_identity": _supervisor(),
        },
        plan=(suite,),
        source_root=ROOT,
        attempt_root=attempt,
        output=output,
        frozen_commit=COMMIT,
        integrity_inputs_path=integrity_inputs,
    )
    assert status is Stage10Status.FAILED_INFRASTRUCTURE
    result = json.loads(output.read_text(encoding="utf-8"))
    assert result["infrastructure_failure"] == "interrupted-suite-not-rerun:stage13-evaluate"
    assert result["suite_validations"] == []

    def recovery_forbidden(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("read-only reconstruction must not recover or mutate a process")

    monkeypatch.setattr(harness, "_recover_interrupted_suite", recovery_forbidden)
    with pytest.raises(ValueError, match=r"read-only.*STARTED"):
        harness._resume_terminal_result(
            output,
            preflight={
                "plan_hash": plan_hash,
                "runtime_identity": _runtime(),
                "source_identity": _identity(),
                "status": "PASS",
                "supervisor_import_identity": _supervisor(),
            },
            plan=(suite,),
            source_root=ROOT,
            attempt_root=attempt,
            frozen_commit=COMMIT,
            integrity_inputs_path=integrity_inputs,
            read_only=True,
        )
    monkeypatch.setattr(harness, "_recover_interrupted_suite", lambda *_args, **_kwargs: {})

    result["infrastructure_failure"] = "self-rehashed-edited-reason"
    atomic_write_json(output, seal_object(result, hash_field="artifact_core_hash"))
    with pytest.raises(ValueError, match="differ from reconstructed evidence"):
        harness._execute(
            preflight={
                "plan_hash": plan_hash,
                "runtime_identity": _runtime(),
                "source_identity": _identity(),
                "status": "PASS",
                "supervisor_import_identity": _supervisor(),
            },
            plan=(suite,),
            source_root=ROOT,
            attempt_root=attempt,
            output=output,
            frozen_commit=COMMIT,
            integrity_inputs_path=integrity_inputs,
        )


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
    integrity_inputs = _integrity_inputs(tmp_path)
    launch_path = attempt / "launch.json"
    authorization_path = attempt / "authorization.json"
    cleanup_path = attempt / "cleanup.json"
    atomic_write_json(launch_path, {"synthetic": True})
    authorization = seal_object(
        {
            "containment": {"kind": "synthetic"},
            "schema": "arc3.build-001.stage-10-launch-authorization.v0.1",
        },
        hash_field="authorization_hash",
    )
    atomic_write_json(authorization_path, authorization)
    atomic_write_json(cleanup_path, {"synthetic": True})
    suite = SuiteSpec(
        suite_id="rule-change",
        command=(sys.executable, "worker.py"),
        timeout_seconds=1.0,
        allowed_returncodes=(0, 1),
        artifact_path=artifact,
        launch_path=launch_path,
        authorization_path=authorization_path,
        cleanup_path=cleanup_path,
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
        runtime_identity=_runtime(),
        supervisor_import_identity=_supervisor(),
        returncode=1,
        timed_out=False,
        launch_error=None,
        wall_ns=1,
        stdout_path=stdout,
        stderr_path=stderr,
        validation=validation,
        integrity_inputs_path=integrity_inputs,
    )
    assert receipt["predeclaration_amendment_sha256"] == harness.PREDECLARATION_AMENDMENT_SHA256
    receipt_path = attempt / "receipt.json"
    atomic_write_json(receipt_path, receipt)
    monkeypatch.setattr(harness, "_validate_suite", lambda *_args, **_kwargs: validation)
    monkeypatch.setattr(harness, "_validate_launch_receipt", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(harness, "_authorization_payload", lambda *_args, **_kwargs: authorization)
    monkeypatch.setattr(
        harness,
        "_validate_authorization_receipt",
        lambda *_args, **_kwargs: authorization,
    )
    monkeypatch.setattr(harness, "_validate_cleanup_receipt", lambda *_args, **_kwargs: {})
    resumed = harness._resume_receipt(
        receipt_path,
        suite=suite,
        attempt_root=attempt,
        source_root=ROOT,
        plan_hash="sha256:" + "b" * 64,
        source_identity=_identity(),
        runtime_identity=_runtime(),
        supervisor_import_identity=_supervisor(),
        integrity_inputs_path=integrity_inputs,
    )
    assert resumed == validation
    atomic_write_json(artifact, {"value": 2})
    try:
        harness._resume_receipt(
            receipt_path,
            suite=suite,
            attempt_root=attempt,
            source_root=ROOT,
            plan_hash="sha256:" + "b" * 64,
            source_identity=_identity(),
            runtime_identity=_runtime(),
            supervisor_import_identity=_supervisor(),
            integrity_inputs_path=integrity_inputs,
        )
    except ValueError as error:
        assert "failed closed validation" in str(error)
    else:  # pragma: no cover
        raise AssertionError("artifact drift was accepted")


@pytest.mark.parametrize(
    ("artifact_present", "disposition", "errors", "predicates", "accepted"),
    [
        (
            False,
            SuiteDisposition.FAILED_INFRASTRUCTURE,
            (
                "child-artifact-missing",
                "composite-integrity-invalid:ValueError:package-only suite is structurally invalid",
            ),
            {"composite_integrity_authority": False},
            True,
        ),
        (
            False,
            SuiteDisposition.FAILED_INFRASTRUCTURE,
            ("composite-integrity-invalid:ValueError:package-only suite is structurally invalid",),
            {"composite_integrity_authority": False},
            False,
        ),
        (
            True,
            SuiteDisposition.FAILED_INFRASTRUCTURE,
            ("composite-integrity-invalid:ValueError:composite output is missing",),
            {"composite_integrity_authority": False},
            True,
        ),
        (
            True,
            SuiteDisposition.FAILED_INFRASTRUCTURE,
            (),
            {"composite_integrity_authority": False},
            False,
        ),
        (
            False,
            SuiteDisposition.PASS,
            (
                "child-artifact-missing",
                "composite-integrity-invalid:ValueError:composite output is missing",
            ),
            {"composite_integrity_authority": False},
            False,
        ),
        (
            False,
            SuiteDisposition.FAILED_MECHANISM,
            (
                "child-artifact-missing",
                "composite-integrity-invalid:ValueError:composite output is missing",
            ),
            {"composite_integrity_authority": False},
            False,
        ),
    ],
)
def test_parent_receipt_accepts_missing_outputs_only_as_exact_infrastructure_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    artifact_present: bool,
    disposition: SuiteDisposition,
    errors: tuple[str, ...],
    predicates: dict[str, bool],
    accepted: bool,
) -> None:
    attempt = tmp_path / "attempt"
    logs = attempt / "logs"
    logs.mkdir(parents=True)
    artifact = attempt / "integrity.json"
    composite = attempt / "integrity-composite.json"
    if artifact_present:
        atomic_write_json(artifact, {"status": "FAILED_INFRASTRUCTURE"})
    stdout = logs / "competition-integrity.stdout"
    stderr = logs / "competition-integrity.stderr"
    stdout.write_bytes(b"")
    stderr.write_bytes(b"missing expected argument")
    integrity_inputs = _integrity_inputs(tmp_path)
    launch_path = attempt / "launch.json"
    authorization_path = attempt / "authorization.json"
    cleanup_path = attempt / "cleanup.json"
    atomic_write_json(launch_path, {"synthetic": True})
    authorization = seal_object(
        {
            "containment": {"kind": "synthetic"},
            "schema": "arc3.build-001.stage-10-launch-authorization.v0.1",
        },
        hash_field="authorization_hash",
    )
    atomic_write_json(authorization_path, authorization)
    atomic_write_json(cleanup_path, {"synthetic": True})
    suite = SuiteSpec(
        suite_id="competition-integrity",
        command=(sys.executable, "worker.py"),
        timeout_seconds=1.0,
        allowed_returncodes=(0, 1),
        artifact_path=artifact,
        integrity_composite_path=composite,
        launch_path=launch_path,
        authorization_path=authorization_path,
        cleanup_path=cleanup_path,
    )
    validation = SuiteValidation(
        suite_id="competition-integrity",
        disposition=disposition,
        predicates=predicates,
        measurements={},
        errors=errors,
    )
    receipt = harness._parent_receipt(
        suite=suite,
        plan_hash="sha256:" + "b" * 64,
        source_identity=_identity(),
        runtime_identity=_runtime(),
        supervisor_import_identity=_supervisor(),
        returncode=2,
        timed_out=False,
        launch_error=None,
        wall_ns=1,
        stdout_path=stdout,
        stderr_path=stderr,
        validation=validation,
        integrity_inputs_path=integrity_inputs,
    )
    receipt_path = attempt / "receipt.json"
    atomic_write_json(receipt_path, receipt)
    monkeypatch.setattr(harness, "_validate_suite", lambda *_args, **_kwargs: validation)
    monkeypatch.setattr(harness, "_validate_launch_receipt", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(harness, "_authorization_payload", lambda *_args, **_kwargs: authorization)
    monkeypatch.setattr(
        harness,
        "_validate_authorization_receipt",
        lambda *_args, **_kwargs: authorization,
    )
    monkeypatch.setattr(harness, "_validate_cleanup_receipt", lambda *_args, **_kwargs: {})

    if accepted:
        assert (
            harness._resume_receipt(
                receipt_path,
                suite=suite,
                attempt_root=attempt,
                source_root=ROOT,
                plan_hash="sha256:" + "b" * 64,
                source_identity=_identity(),
                runtime_identity=_runtime(),
                supervisor_import_identity=_supervisor(),
                integrity_inputs_path=integrity_inputs,
            )
            == validation
        )
    else:
        with pytest.raises(ValueError, match="failed closed validation"):
            harness._resume_receipt(
                receipt_path,
                suite=suite,
                attempt_root=attempt,
                source_root=ROOT,
                plan_hash="sha256:" + "b" * 64,
                source_identity=_identity(),
                runtime_identity=_runtime(),
                supervisor_import_identity=_supervisor(),
                integrity_inputs_path=integrity_inputs,
            )


def test_terminal_verifier_uses_the_interpreter_bound_by_the_first_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempt = tmp_path / "attempt"
    output = tmp_path / "result.json"
    recorded_python = tmp_path / "recorded-runtime" / "python.exe"
    integrity_inputs = _integrity_inputs(tmp_path)
    attempt.mkdir()
    atomic_write_json(output, {})
    suite = SuiteSpec(
        suite_id="competition-integrity",
        command=(str(recorded_python),),
        timeout_seconds=1.0,
        allowed_returncodes=(0,),
        artifact_path=None,
    )
    observed: dict[str, object] = {}

    supervisor = _supervisor()

    def replay(**arguments: object) -> tuple[dict[str, object], tuple[SuiteSpec, ...]]:
        observed.update(arguments)
        return {"status": "PASS", "supervisor_import_identity": supervisor}, (suite,)

    monkeypatch.setattr(
        harness,
        "_terminal_bootstrap",
        lambda **_kwargs: (
            {
                "supervisor_import_identity_end": supervisor,
                "supervisor_import_identity_start": supervisor,
            },
            recorded_python,
            integrity_inputs,
        ),
    )
    monkeypatch.setattr(harness, "_replay_frozen_preflight", replay)
    monkeypatch.setattr(harness, "_require_supervisor_import_origin", lambda *_args: _supervisor())
    monkeypatch.setattr(
        harness,
        "_resume_terminal_result",
        lambda *_args, **_kwargs: Stage10Status.PASS,
    )
    assert harness.verify_terminal_evidence(
        source_root=ROOT,
        attempt_root=attempt,
        output=output,
        frozen_commit=COMMIT,
    )
    assert observed["recorded_python"] == recorded_python
    assert observed["integrity_inputs_path"] == integrity_inputs


def test_read_only_terminal_api_preserves_authenticated_infrastructure_status(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempt = tmp_path / "attempt"
    attempt.mkdir()
    output = tmp_path / "result.json"
    atomic_write_json(output, {})
    integrity_inputs = _integrity_inputs(tmp_path)
    supervisor = _supervisor()
    suite = SuiteSpec(
        suite_id="competition-integrity",
        command=(sys.executable,),
        timeout_seconds=1.0,
        allowed_returncodes=(0,),
        artifact_path=None,
    )
    monkeypatch.setattr(harness, "_require_supervisor_import_origin", lambda *_args: supervisor)
    monkeypatch.setattr(
        harness,
        "_terminal_bootstrap",
        lambda **_kwargs: (
            {
                "supervisor_import_identity_end": supervisor,
                "supervisor_import_identity_start": supervisor,
            },
            Path(sys.executable),
            integrity_inputs,
        ),
    )
    monkeypatch.setattr(
        harness,
        "_replay_frozen_preflight",
        lambda **_kwargs: (
            {"status": "PASS", "supervisor_import_identity": supervisor},
            (suite,),
        ),
    )
    monkeypatch.setattr(
        harness,
        "_resume_terminal_result",
        lambda *_args, **_kwargs: Stage10Status.FAILED_INFRASTRUCTURE,
    )

    assert (
        harness.reconstruct_terminal_status(
            verifier_source_root=ROOT,
            execution_source_root=tmp_path / "archived-source",
            attempt_root=attempt,
            output=output,
            frozen_commit=COMMIT,
        )
        is Stage10Status.FAILED_INFRASTRUCTURE
    )
    assert not harness.verify_terminal_evidence(
        source_root=ROOT,
        attempt_root=attempt,
        output=output,
        frozen_commit=COMMIT,
    )


def test_supervisor_loaded_from_tree_a_cannot_validate_tree_b(tmp_path: Path) -> None:
    other_tree = tmp_path / "tree-b"
    output = tmp_path / "terminal.json"
    output.write_bytes(b"not-json")

    with pytest.raises(ValueError, match="import closure"):
        harness._execute(
            preflight={"status": "PASS"},
            plan=(),
            source_root=other_tree,
            attempt_root=tmp_path / "attempt",
            output=output,
            frozen_commit=COMMIT,
            integrity_inputs_path=_integrity_inputs(tmp_path),
        )


def test_stage10_cli_requires_explicit_source_root(tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        harness._parser().parse_args(
            [
                "--attempt-root",
                str(tmp_path / "attempt"),
                "--output",
                str(tmp_path / "result.json"),
            ]
        )


def _run_denial_fixture(
    tmp_path: Path,
    *,
    body: str,
) -> tuple[dict[str, int], subprocess.CompletedProcess[str]]:
    target = tmp_path / "target.py"
    target.write_text(body, encoding="utf-8")
    probe = (
        "import importlib.util,json,pathlib;"
        f"p=pathlib.Path({str(ROOT / 'scripts/_stage10_offline_child.py')!r});"
        "s=importlib.util.spec_from_file_location('stage10_child',p);"
        "m=importlib.util.module_from_spec(s);s.loader.exec_module(m);"
        "a,_=m._install_denial();"
        f"exec(pathlib.Path({str(target)!r}).read_text(encoding='utf-8'));"
        "print(json.dumps(a,sort_keys=True))"
    )
    completed = subprocess.run(
        (sys.executable, "-c", probe),
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    counts = json.loads(completed.stdout) if completed.returncode == 0 else {}
    return counts, completed


def test_offline_child_installs_socket_denial_before_target_import(
    tmp_path: Path,
) -> None:
    counts, completed = _run_denial_fixture(
        tmp_path,
        body="import socket\nassert callable(socket.getaddrinfo)\n",
    )
    assert completed.returncode == 0, completed.stderr
    assert sum(counts.values()) == 0


def test_offline_child_denies_and_records_socket_attempt(
    tmp_path: Path,
) -> None:
    counts, completed = _run_denial_fixture(
        tmp_path,
        body=(
            "import socket\n"
            "sock = socket.socket()\n"
            "probes = [\n"
            "    lambda: socket.create_connection(('203.0.113.1', 9)),\n"
            "    lambda: socket.getaddrinfo('example.invalid', 443),\n"
            "    lambda: sock.connect(('203.0.113.1', 9)),\n"
            "    lambda: sock.connect_ex(('203.0.113.1', 9)),\n"
            "    lambda: sock.send(b'x'),\n"
            "    lambda: sock.sendall(b'x'),\n"
            "    lambda: sock.sendto(b'x', ('203.0.113.1', 9)),\n"
            "]\n"
            "for probe in probes:\n"
            "    try:\n"
            "        probe()\n"
            "    except OSError as error:\n"
            "        assert 'offline guard denied' in str(error)\n"
            "    else:\n"
            "        raise AssertionError('socket attempt was not denied')\n"
            "sock.close()\n"
        ),
    )
    assert completed.returncode == 0, completed.stderr
    attempts = sum(counts.values())
    assert attempts == 7
    guarded = harness._with_network_guard(
        SuiteValidation(
            suite_id="synthetic-guard-test",
            disposition=SuiteDisposition.PASS,
            predicates={"synthetic_ok": True},
            measurements={},
        ),
        structural_errors=(),
        network_attempts=attempts,
    )
    assert guarded.disposition is SuiteDisposition.FAILED_MECHANISM


def test_offline_child_cannot_import_target_without_launch_authorization(
    tmp_path: Path,
) -> None:
    target = tmp_path / "target.py"
    marker = tmp_path / "target-imported"
    target.write_text(
        f"from pathlib import Path\nPath({str(marker)!r}).touch()\n", encoding="utf-8"
    )
    receipt = tmp_path / "network.json"
    launch = tmp_path / "launch.json"
    authorization = tmp_path / "authorization.json"
    abort = tmp_path / "abort.json"
    command = (
        sys.executable,
        str(ROOT / "scripts/_stage10_offline_child.py"),
        "--receipt",
        str(receipt),
        "--suite-id",
        "synthetic-guard-test",
        "--frozen-commit",
        COMMIT,
        "--launch-receipt",
        str(launch),
        "--authorization",
        str(authorization),
        "--abort-receipt",
        str(abort),
        "--launch-token",
        "sha256:" + "a" * 64,
        "--script",
        str(target),
        "--",
    )
    environment = dict(harness._safe_environment(ROOT))
    environment["ARC3_STAGE10_LEXICAL_LAUNCHER"] = sys.executable
    completed = subprocess.run(
        command,
        cwd=ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert completed.returncode == 72, completed.stderr
    assert not marker.exists()
    abort_document = json.loads(abort.read_text(encoding="utf-8"))
    assert abort_document["target_imported"] is False
    assert abort_document["socket_denial_installed"] is True
    assert json.loads(launch.read_text(encoding="utf-8"))["target_imported"] is False


def test_cleanup_never_kills_a_reused_pid(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cleanup_path = tmp_path / "cleanup.json"
    suite = SuiteSpec(
        suite_id="synthetic-cleanup",
        command=(sys.executable,),
        timeout_seconds=1.0,
        allowed_returncodes=(0,),
        artifact_path=None,
        cleanup_path=cleanup_path,
        launch_token="sha256:" + "a" * 64,
    )
    launch = {
        "launch_receipt_hash": None,
        "launch_token": suite.launch_token,
        "pid": 4242,
        "process_creation_token": "original-process",
    }
    monkeypatch.setattr(harness, "_process_creation_token", lambda _pid: "reused-process")
    monkeypatch.setattr(harness, "_posix_group_members", lambda _pid: ())

    def forbidden(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("PID reuse must never trigger a termination command")

    monkeypatch.setattr(subprocess, "run", forbidden)
    receipt = harness._cleanup_process_tree(
        suite=suite,
        launch=launch,
        authorization=None,
        containment={"kind": "synthetic"},
        reason="pid-reuse-test",
        windows_job_handle=None,
        allow_group_without_live_root=False,
    )
    assert receipt["pid_reused_original_not_running"] is True
    assert receipt["termination_attempted"] is False
    assert cleanup_path.is_file()


def test_unavailable_creation_token_is_contained_and_receipted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class SyntheticProcess:
        pid = 4242
        returncode: int | None = None

        def poll(self) -> int | None:
            return self.returncode

        def wait(self, timeout: float | None = None) -> int:
            del timeout
            self.returncode = -9
            return self.returncode

    cleanup_path = tmp_path / "cleanup.json"
    suite = SuiteSpec(
        suite_id="unidentified-preauthorization",
        command=(sys.executable,),
        timeout_seconds=1.0,
        allowed_returncodes=(0,),
        artifact_path=None,
        cleanup_path=cleanup_path,
        launch_token="sha256:" + "a" * 64,
    )
    process = SyntheticProcess()
    monkeypatch.setattr(harness, "_process_creation_token", lambda _pid: None)
    monkeypatch.setattr(harness, "_posix_group_members", lambda _pid: ())
    windows_handle: int | None = None
    if os.name == "nt":
        windows_handle = 123
        monkeypatch.setattr(harness, "_close_windows_handle", lambda _handle: None)
    else:
        monkeypatch.setattr(os, "killpg", lambda _pid, _signal: None)
    launch_error = "ValueError: Stage 10 spawned process creation identity is unavailable"
    reason = f"child-failed-before-authorized-start:unidentified-preauthorization:{launch_error}"
    receipt = harness._cleanup_unidentified_spawn(
        suite=suite,
        process=process,  # type: ignore[arg-type]
        containment={"kind": "synthetic-preauthorization-containment"},
        reason=reason,
        windows_job_handle=windows_handle,
    )

    assert receipt["passed"] is True
    assert receipt["process_creation_token"] is None
    assert receipt["group_members_after"] == []
    stdout = tmp_path / "stdout"
    stderr = tmp_path / "stderr"
    stdout.write_bytes(b"")
    stderr.write_bytes(b"")
    failure = harness._preauthorization_failure(
        suite,
        stdout_path=stdout,
        stderr_path=stderr,
        launch_error=launch_error,
    )
    assert failure["target_import_authorized"] is False


def test_parent_authorization_is_accepted_by_child_contract(tmp_path: Path) -> None:
    launch_path = tmp_path / "launch.json"
    authorization_path = tmp_path / "authorization.json"
    abort_path = tmp_path / "abort.json"
    network_path = tmp_path / "network.json"
    atomic_write_json(launch_path, {"synthetic": True})
    suite = SuiteSpec(
        suite_id="synthetic-authorization",
        command=(sys.executable,),
        timeout_seconds=1.0,
        allowed_returncodes=(0,),
        artifact_path=None,
        launch_path=launch_path,
        authorization_path=authorization_path,
        abort_path=abort_path,
        network_guard_path=network_path,
        launch_token="sha256:" + "a" * 64,
        integrity_inputs_hash="sha256:" + "b" * 64,
    )
    launch = {
        "command_sha256": "sha256:" + "c" * 64,
        "launch_receipt_hash": "sha256:" + "d" * 64,
        "pid": os.getpid(),
        "process_creation_token": "synthetic-token",
    }
    runtime = {
        "observed": {"runtime_surface": {"verified": True}},
        "runtime_identity_sha256": "sha256:" + "e" * 64,
    }
    authorization = harness._authorization_payload(
        suite,
        launch=launch,
        plan_hash="sha256:" + "f" * 64,
        source_root=ROOT,
        source_identity={"commit": COMMIT, "tree": "1" * 40},
        runtime_identity=runtime,
        supervisor_import_identity=_supervisor(),
        containment={"kind": "synthetic"},
    )
    atomic_write_json(authorization_path, authorization)
    args = argparse.Namespace(
        abort_receipt=abort_path,
        authorization=authorization_path,
        frozen_commit=COMMIT,
        launch_receipt=launch_path,
        launch_token=suite.launch_token,
        receipt=network_path,
        suite_id=suite.suite_id,
    )

    assert child._authorization_valid(args, launch=launch) == authorization


def test_parent_child_authority_integrity_hash_contract(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "authority.json"
    inputs_hash = "sha256:" + "1" * 64
    parent_hash = "sha256:" + "2" * 64
    composition = {
        "assurance_limitation": (
            "Package and development scans are static; dynamic-import and native-extension "
            "containment are not proven; Build 001 public identifiers were not fully evaluated."
        ),
        "composite_integrity_core_hash": "sha256:" + "3" * 64,
        "composite_integrity_file_sha256": "sha256:" + "4" * 64,
        "composite_integrity_schema": "arc3.build-001.competition-integrity-composite.v0.1",
        "dynamic_or_native_containment": "NOT_PROVEN_BY_STATIC_IMPORT_REACHABILITY",
        "full_public_integrity_status": "NOT_EVALUATED_BUILD_001_PUBLIC_IDENTIFIERS",
        "integrity_inputs_file_sha256": "sha256:" + "5" * 64,
        "integrity_inputs_hash": inputs_hash,
        "integrity_inputs_schema": "arc3.build-001.stage-10-integrity-authority-inputs.v0.1",
        "semantic_holdout_identifier_scan": "NOT_EVALUATED_SEALED_HOLDOUT_IDENTIFIERS",
        "static_authority_claim": "BOUNDED_STATIC_COMPETITION_INTEGRITY_WITH_OPAQUE_HOLDOUT",
    }
    authority_document = seal_object(
        {
            "authorized_suites": list(child._AUTHORIZED_SUITES),
            "frozen_commit": COMMIT,
            "integrity_composition": composition,
            "integrity_inputs_hash": inputs_hash,
            "integrity_parent_receipt_sha256": parent_hash,
            "plan_hash": "sha256:" + "6" * 64,
            "predeclaration_amendment_sha256": child.PREDECLARATION_AMENDMENT_SHA256,
            "predeclaration_sha256": child.PREDECLARATION_SHA256,
            "profile": {
                "authorized_surface": "synthetic-no-semantic-public-manifest",
                "public_identifier_values_available": 0,
                "public_manifest_paths_available": 0,
                "semantic_public_manifest_access": False,
            },
            "runtime_identity_sha256": "sha256:" + "8" * 64,
            "runtime_surface": {"verified": True},
            "schema": child.AUTHORITY_SCHEMA,
            "source_commit": COMMIT,
            "source_tree": "1" * 40,
            "supervisor_import_identity_sha256": "sha256:" + "9" * 64,
        },
        hash_field="authority_sha256",
    )
    atomic_write_json(path, authority_document)
    monkeypatch.setenv(
        "ARC3_STAGE10_EXPECTED_AUTHORITY_SHA256",
        cast(str, authority_document["authority_sha256"]),
    )
    monkeypatch.setenv("ARC3_STAGE10_EXPECTED_AUTHORITY_FILE_SHA256", sha256_file(path))
    monkeypatch.setenv("ARC3_STAGE10_EXPECTED_PARENT_RECEIPT_SHA256", parent_hash)

    loaded, projection = child._load_authority(
        path,
        suite_id="action-equivariance",
        frozen_commit=COMMIT,
        expected_integrity_inputs_hash=inputs_hash,
    )
    assert loaded == authority_document
    assert isinstance(projection, dict)
    assert projection["integrity_composition"] == composition

    with pytest.raises(ValueError, match="failed closed validation"):
        child._load_authority(
            path,
            suite_id="action-equivariance",
            frozen_commit=COMMIT,
            expected_integrity_inputs_hash="sha256:" + "0" * 64,
        )

    drifted = seal_object(
        {key: value for key, value in authority_document.items() if key != "authority_sha256"}
        | {"predeclaration_amendment_sha256": "sha256:" + "0" * 64},
        hash_field="authority_sha256",
    )
    atomic_write_json(path, drifted)
    monkeypatch.setenv(
        "ARC3_STAGE10_EXPECTED_AUTHORITY_SHA256",
        cast(str, drifted["authority_sha256"]),
    )
    monkeypatch.setenv("ARC3_STAGE10_EXPECTED_AUTHORITY_FILE_SHA256", sha256_file(path))
    with pytest.raises(ValueError, match="failed closed validation"):
        child._load_authority(
            path,
            suite_id="action-equivariance",
            frozen_commit=COMMIT,
            expected_integrity_inputs_hash=inputs_hash,
        )


@pytest.mark.skipif(os.name == "nt", reason="POSIX venv launchers are symlinks")
def test_runtime_identity_preserves_lexical_symlink_launcher(tmp_path: Path) -> None:
    launcher = tmp_path / "venv" / "bin" / "python"
    launcher.parent.mkdir(parents=True)
    launcher.symlink_to(Path(sys.executable).resolve())

    identity = harness._runtime_identity(ROOT, launcher)

    assert identity["launcher_path"] == str(launcher)
    assert identity["launcher_is_symlink"] is True
    assert identity["resolved_executable_path"] == str(Path(sys.executable).resolve())


def test_bound_process_executable_rejects_hash_drift(tmp_path: Path) -> None:
    launcher = tmp_path / "venv" / ("Scripts" if os.name == "nt" else "bin") / "python"
    launcher.parent.mkdir(parents=True)
    launcher.write_bytes(b"synthetic-launcher")
    actual_executable = tmp_path / "runtime" / "python"
    actual_executable.parent.mkdir(parents=True)
    actual_executable.write_bytes(b"synthetic-runtime")
    runtime_identity = _bound_runtime(launcher, actual_executable)

    assert (
        harness._bound_process_executable(
            runtime_identity,
            lexical_launcher=str(launcher),
        )
        == actual_executable.resolve()
    )

    actual_executable.write_bytes(b"changed-runtime")
    with pytest.raises(ValueError, match="process executable changed"):
        harness._bound_process_executable(
            runtime_identity,
            lexical_launcher=str(launcher),
        )

    actual_executable.write_bytes(b"synthetic-runtime")
    launcher.write_bytes(b"changed-launcher")
    with pytest.raises(ValueError, match="process launcher changed"):
        harness._bound_process_executable(
            runtime_identity,
            lexical_launcher=str(launcher),
        )


@pytest.mark.skipif(os.name != "nt", reason="Windows launcher topology regression")
def test_windows_direct_base_spawn_preserves_venv_identity_and_pid() -> None:
    if sys.prefix == sys.base_prefix:
        pytest.skip("test interpreter is not running from a virtual environment")
    launcher = Path(os.path.abspath(sys.executable))
    runtime_identity = harness._runtime_identity(ROOT, launcher)
    assert runtime_identity["verified"] is True
    actual_executable = harness._bound_process_executable(
        runtime_identity,
        lexical_launcher=str(launcher),
    )
    environment = harness._safe_environment(ROOT)
    environment["__PYVENV_LAUNCHER__"] = str(launcher)
    code = (
        "import json,os,sys;"
        "print(json.dumps({'pid':os.getpid(),'executable':os.path.abspath(sys.executable),"
        "'prefix':os.path.abspath(sys.prefix)}))"
    )
    process = subprocess.Popen(
        (str(launcher), "-I", "-c", code),
        executable=str(actual_executable),
        cwd=ROOT,
        env=environment,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    stdout, stderr = process.communicate(timeout=20)

    assert process.returncode == 0, stderr
    observation = json.loads(stdout)
    assert observation == {
        "pid": process.pid,
        "executable": str(launcher),
        "prefix": os.path.abspath(sys.prefix),
    }


@pytest.mark.skipif(os.name != "nt", reason="Windows Popen executable override")
def test_run_child_uses_bound_process_executable_on_windows(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    launcher = tmp_path / "venv" / "Scripts" / "python.exe"
    launcher.parent.mkdir(parents=True)
    launcher.write_bytes(b"synthetic-launcher")
    actual_executable = tmp_path / "runtime" / "python.exe"
    actual_executable.parent.mkdir(parents=True)
    actual_executable.write_bytes(b"synthetic-runtime")
    runtime_identity = _bound_runtime(launcher, actual_executable)
    suite = SuiteSpec(
        suite_id="synthetic-launch",
        command=(str(launcher), "worker.py"),
        timeout_seconds=1.0,
        allowed_returncodes=(0,),
        artifact_path=None,
    )
    captured: dict[str, object] = {}

    def fail_popen(*args: object, **kwargs: object) -> subprocess.Popen[bytes]:
        captured["command"] = args[0]
        captured["kwargs"] = kwargs
        raise OSError("synthetic launch stop")

    monkeypatch.setattr(subprocess, "Popen", fail_popen)
    result = harness._run_child(
        suite,
        source_root=ROOT,
        stdout_path=tmp_path / "stdout.log",
        stderr_path=tmp_path / "stderr.log",
        ledger_path=tmp_path / "invocations.jsonl",
        records=[],
        plan_hash="sha256:" + "a" * 64,
        source_identity=_identity(),
        runtime_identity=runtime_identity,
        supervisor_import_identity=_supervisor(),
    )

    assert result[2] == "OSError: synthetic launch stop"
    assert captured["command"] == suite.command
    kwargs = cast(dict[str, object], captured["kwargs"])
    assert kwargs["executable"] == str(actual_executable.resolve())
    environment = cast(dict[str, str], kwargs["env"])
    assert environment["ARC3_STAGE10_LEXICAL_LAUNCHER"] == str(launcher)
    assert environment["__PYVENV_LAUNCHER__"] == str(launcher)
