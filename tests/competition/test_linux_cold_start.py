"""Build 002 wheelhouse acquisition and native cold-start boundaries."""

from __future__ import annotations

import io
import json
import subprocess
import zipfile
from pathlib import Path
from typing import Any

import pytest
from scripts import verify_build002_cold_start

from arc3.packaging import cold_start
from arc3.packaging.cold_start import (
    acquire_runtime_wheelhouse,
    load_runtime_wheel_manifest,
    run_linux_cold_start,
)
from arc3.packaging.models import PackagingError
from arc3.packaging.notebook import build_notebook
from arc3.packaging.requirements import build_linux_runtime_requirements
from arc3.packaging.util import canonical_json_bytes, deterministic_zip_bytes, sha256_bytes

REPOSITORY = Path(__file__).resolve().parents[2]


class _Download(io.BytesIO):
    def __init__(self, content: bytes, url: str) -> None:
        super().__init__(content)
        self._url = url
        self.headers = {"Content-Length": str(len(content))}

    def geturl(self) -> str:
        return self._url


@pytest.mark.competition
def test_build002_failed_subprocess_preserves_only_a_bounded_diagnostic_tail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stderr = "discard-me" + ("x" * 5000) + "useful-tail"
    monkeypatch.setattr(
        cold_start.subprocess,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            args=["probe"], returncode=7, stdout="", stderr=stderr
        ),
    )

    with pytest.raises(PackagingError) as caught:
        cold_start._run_checked(
            ["probe"],
            environment={},
            timeout_seconds=1.0,
            label="fixture probe",
        )

    message = str(caught.value)
    assert "fixture probe failed with exit 7" in message
    assert "useful-tail" in message
    assert "discard-me" not in message
    assert "stderr_sha256=sha256:" in message


@pytest.mark.competition
def test_build002_timed_out_subprocess_becomes_a_bounded_packaging_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def timed_out(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired(cmd=["probe"], timeout=1.25)

    monkeypatch.setattr(cold_start.subprocess, "run", timed_out)
    with pytest.raises(PackagingError, match=r"fixture probe exceeded the remaining 1\.250s"):
        cold_start._run_checked(
            ["probe"],
            environment={},
            timeout_seconds=1.25,
            label="fixture probe",
        )


@pytest.mark.competition
def test_build002_probe_allows_only_required_loopback_bind_socket_events() -> None:
    source = cold_start._PROBE_SOURCE

    assert 'event == "socket.__new__"' in source
    assert 'event == "socket.bind"' in source
    assert '{"127.0.0.1", "::1"}' in source
    assert "forbids non-loopback socket access" in source
    assert '"permitted_loopback_socket_events"' in source
    assert 'denial_probe.connect(("203.0.113.1", 9))' in source
    assert 'network_denial_self_test = "PASS"' in source
    assert "FROZEN_COMPETITION_RUNTIME.configuration_sha256" in source
    assert "FROZEN_COMPETITION_RUNTIME.config_sha256" not in source

    notebook_runner = cold_start.NOTEBOOK_REHEARSAL_RUNNER_SOURCE
    assert 'runner_mode == "native-linux-exact"' in notebook_runner
    assert 'os.environ["KAGGLE_IS_COMPETITION_RERUN"] = "1"' in notebook_runner
    assert 'working_root / "arc3-runtime-linux-cp312.txt"' in notebook_runner
    assert "executed_code_cells += 1" in notebook_runner
    assert "resource.setrlimit(resource.RLIMIT_AS" in notebook_runner
    assert "resource.setrlimit(resource.RLIMIT_CPU" in notebook_runner
    assert 'raise RuntimeError("native notebook runner found a host-site .pth bridge")' in (
        notebook_runner
    )


@pytest.mark.competition
def test_build002_native_notebook_receipt_requires_exact_entry_and_zero_network() -> None:
    expected_packages = {"arc-agi": "0.9.9"}
    expected_hash = "sha256:" + "1" * 64
    raw: dict[str, Any] = {
        "dependency_install_status": "PASS",
        "exact_generated_code_cells": 4,
        "exact_production_requirements": True,
        "external_site_pth_entries": [],
        "foreign_site_paths": [],
        "framework_fixture": True,
        "framework_identity": "arc3.stage17.safe-framework.v0.1",
        "host_site_pth_bridge_present": False,
        "network_attempts": 0,
        "network_attempt_scope": "non-loopback Python socket attempts",
        "network_enforcement": cold_start.PYTHON_NETWORK_ENFORCEMENT,
        "notebook_entrypoint": "exact-generated-notebook-code-cells",
        "output_sha256": expected_hash,
        "peak_memory_bytes": 1,
        "platform_surface": "safe-loopback-gateway-and-framework-fixture",
        "production_rerun_exercised": True,
        "rehearsal_requirements_sha256": expected_hash,
        "runner_mode": "native-linux-exact",
        "runtime_dependency_surface": "exact-embedded-production-requirements",
        "secret_scan_status": "PASS",
        "status": "PASS",
        "target_import_origins": {"arc-agi": "arc_agi/__init__.py"},
        "target_installed_packages": expected_packages,
    }

    cold_start._validate_native_notebook_result(
        raw,
        expected_packages=expected_packages,
        expected_requirements_sha256=expected_hash,
        expected_output_sha256=expected_hash,
    )

    raw["network_attempts"] = 1
    with pytest.raises(PackagingError, match="incomplete or weakened"):
        cold_start._validate_native_notebook_result(
            raw,
            expected_packages=expected_packages,
            expected_requirements_sha256=expected_hash,
            expected_output_sha256=expected_hash,
        )


@pytest.mark.competition
def test_build002_cli_writes_failure_receipt_before_returning_nonzero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    package = tmp_path / "package"
    package.mkdir()
    (package / "package-manifest.json").write_text(
        json.dumps({"source": {"git_commit": "1" * 40}}), encoding="utf-8"
    )
    monkeypatch.setattr(
        verify_build002_cold_start,
        "run_linux_cold_start",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(PackagingError("linux import failed")),
    )
    receipt = tmp_path / "receipt.json"

    exit_code = verify_build002_cold_start.main(
        [
            "--package-dir",
            str(package),
            "--wheelhouse",
            str(tmp_path / "wheels"),
            "--receipt",
            str(receipt),
        ]
    )

    document = json.loads(receipt.read_text(encoding="utf-8"))
    assert exit_code == 1
    assert document["schema"] == "arc3.build-002-cold-start-command.v0.2"
    assert document["status"] == "FAILED_INFRASTRUCTURE"
    assert document["error_type"] == "PackagingError"
    assert document["error_message_sha256"] == sha256_bytes(b"linux import failed")
    assert document["public_environment_interactions"] == 0
    assert document["kaggle_accessed"] is False


def _fixture_manifest(tmp_path: Path) -> tuple[Path, Path, str, bytes]:
    wheel_bytes = deterministic_zip_bytes({"fixture/__init__.py": b"VALUE = 1\n"})
    filename = "fixture-1.0-py3-none-any.whl"
    url = f"https://files.pythonhosted.org/packages/aa/bb/{filename}"
    requirements = (
        "# Generated from uv.lock; CPython 3.12 Linux x86_64 only.\n"
        "# Installation must also pass --no-index --no-deps --require-hashes.\n"
        f"fixture==1.0 --hash={sha256_bytes(wheel_bytes)}\n"
    ).encode()
    requirements_path = tmp_path / "requirements.txt"
    requirements_path.write_bytes(requirements)
    _, generated, _ = build_linux_runtime_requirements(REPOSITORY / "uv.lock")
    core: dict[str, Any] = {
        "packages": [
            {
                "filename": filename,
                "name": "fixture",
                "sha256": sha256_bytes(wheel_bytes),
                "url": url,
                "version": "1.0",
            }
        ],
        "pip_target": generated["pip_target"],
        "python": "3.12",
        "schema": "arc3.runtime-wheel-manifest.v0.1",
        "target": generated["target"],
        "uv_lock_sha256": "sha256:" + "0" * 64,
    }
    manifest = dict(core)
    manifest["requirements_sha256"] = sha256_bytes(requirements)
    manifest["manifest_core_sha256"] = sha256_bytes(canonical_json_bytes(core))
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_bytes(canonical_json_bytes(manifest))
    return manifest_path, requirements_path, url, wheel_bytes


def _fixture_package_manifest(
    tmp_path: Path,
    *,
    runtime_manifest: Path,
    requirements: Path,
    payload: Path,
    source_commit: str,
) -> Path:
    document = {
        "build_status": "PACKAGING_PASS",
        "payload": {
            "sha256": sha256_bytes(payload.read_bytes()),
            "source_identity": {
                "exact_git_commit_bound": True,
                "git_commit": source_commit,
                "mode": "git-blob-exact",
            },
        },
        "runtime_lock": {
            "requirements_sha256": sha256_bytes(requirements.read_bytes()),
            "target": "CPython 3.12 / Linux x86_64 / manylinux_2_28",
            "wheel_manifest_sha256": sha256_bytes(runtime_manifest.read_bytes()),
        },
        "schema": "arc3.kaggle-package-manifest.v0.1",
        "source": {"git_commit": source_commit, "git_dirty": False},
    }
    path = tmp_path / "package-manifest.json"
    path.write_bytes(canonical_json_bytes(document))
    return path


def _fixture_notebook(
    tmp_path: Path,
    *,
    requirements: Path,
    payload: Path,
    source_commit: str,
) -> Path:
    document = build_notebook(
        payload=payload.read_bytes(),
        payload_sha256=sha256_bytes(payload.read_bytes()),
        runtime_requirements=requirements.read_bytes(),
        requirements_sha256=sha256_bytes(requirements.read_bytes()),
        validation_parquet=b"PAR1fixturePAR1",
        source_commit=source_commit,
    )
    path = tmp_path / "arc3-submission.ipynb"
    path.write_bytes(canonical_json_bytes(document))
    return path


@pytest.mark.competition
def test_build002_manifest_loader_binds_requirements_target_and_urls(tmp_path: Path) -> None:
    manifest, requirements, _url, _wheel = _fixture_manifest(tmp_path)

    selected = load_runtime_wheel_manifest(manifest, requirements)

    assert len(selected) == 1
    assert selected[0].name == "fixture"
    tampered = requirements.read_bytes().replace(b"fixture==1.0", b"fixture==2.0")
    requirements.write_bytes(tampered)
    with pytest.raises(PackagingError, match="does not match its requirements"):
        load_runtime_wheel_manifest(manifest, requirements)


@pytest.mark.competition
def test_build002_wheelhouse_acquisition_uses_only_pinned_url_and_hash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest, requirements, expected_url, wheel_bytes = _fixture_manifest(tmp_path)
    observed: list[tuple[str, float]] = []

    def fake_urlopen(request: Any, *, timeout: float) -> _Download:
        observed.append((request.full_url, timeout))
        return _Download(wheel_bytes, expected_url)

    monkeypatch.setattr(cold_start, "urlopen", fake_urlopen)
    wheelhouse = tmp_path / "wheelhouse"
    receipt = acquire_runtime_wheelhouse(
        manifest,
        requirements,
        wheelhouse,
        timeout_seconds=7.0,
    )

    assert observed == [(expected_url, 7.0)]
    assert receipt.to_dict()["status"] == "PASS"
    assert receipt.package_count == 1
    assert (wheelhouse / "fixture-1.0-py3-none-any.whl").read_bytes() == wheel_bytes
    assert sorted(path.name for path in wheelhouse.iterdir()) == ["fixture-1.0-py3-none-any.whl"]


@pytest.mark.competition
def test_build002_wheelhouse_acquisition_removes_failed_staging(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest, requirements, expected_url, wheel_bytes = _fixture_manifest(tmp_path)

    def fake_urlopen(request: Any, *, timeout: float) -> _Download:
        del request, timeout
        return _Download(wheel_bytes + b"tampered", expected_url)

    monkeypatch.setattr(cold_start, "urlopen", fake_urlopen)
    destination = tmp_path / "wheelhouse"
    with pytest.raises(PackagingError, match="hash mismatch"):
        acquire_runtime_wheelhouse(manifest, requirements, destination)

    assert not destination.exists()
    assert not list(tmp_path.glob(".arc3-wheelhouse-*"))


@pytest.mark.competition
def test_build002_wheelhouse_rejects_redirect_outside_pinned_host(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest, requirements, _url, wheel_bytes = _fixture_manifest(tmp_path)

    def fake_urlopen(request: Any, *, timeout: float) -> _Download:
        del request, timeout
        return _Download(
            wheel_bytes,
            "https://example.invalid/packages/fixture-1.0-py3-none-any.whl",
        )

    monkeypatch.setattr(cold_start, "urlopen", fake_urlopen)
    with pytest.raises(PackagingError, match="outside the pinned PyPI"):
        acquire_runtime_wheelhouse(manifest, requirements, tmp_path / "wheelhouse")


@pytest.mark.competition
def test_build002_non_linux_host_never_claims_linux_cold_start_pass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest, requirements, _url, wheel_bytes = _fixture_manifest(tmp_path)
    wheelhouse = tmp_path / "wheelhouse"
    wheelhouse.mkdir()
    (wheelhouse / "fixture-1.0-py3-none-any.whl").write_bytes(wheel_bytes)
    payload = tmp_path / "payload.zip"
    payload.write_bytes(
        deterministic_zip_bytes(
            {
                "agent/my_agent.py": b"class MyAgent: pass\n",
                "src/arc3/__init__.py": b"\n",
            }
        )
    )
    source_commit = "1" * 40
    package_manifest = _fixture_package_manifest(
        tmp_path,
        runtime_manifest=manifest,
        requirements=requirements,
        payload=payload,
        source_commit=source_commit,
    )
    notebook = _fixture_notebook(
        tmp_path,
        requirements=requirements,
        payload=payload,
        source_commit=source_commit,
    )
    monkeypatch.setattr(
        cold_start,
        "_host_identity",
        lambda: ("Windows", "AMD64", "CPython", "3.12.14", "unknown"),
    )

    monkeypatch.setitem(cold_start._DISTRIBUTION_IMPORTS, "fixture", "fixture")
    receipt = run_linux_cold_start(
        manifest,
        requirements,
        wheelhouse,
        payload,
        package_manifest,
        notebook_path=notebook,
        source_commit=source_commit,
    )

    assert receipt.status == "BLOCKED_PLATFORM"
    assert receipt.executed is False
    assert receipt.deterministic_repetitions == 0
    assert receipt.stable_projection_sha256 is None
    assert receipt.notebook_entry["status"] == "BLOCKED_PLATFORM"
    assert receipt.notebook_entry["executed"] is False
    assert receipt.to_dict()["schema"] == "arc3.linux-cold-start.v0.2"
    assert receipt.to_dict()["pip"] == {
        "isolated": False,
        "no_deps": False,
        "no_index": False,
        "require_hashes": False,
        "version": None,
    }


@pytest.mark.competition
def test_build002_payload_validation_rejects_traversal_before_platform_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest, requirements, _url, wheel_bytes = _fixture_manifest(tmp_path)
    wheelhouse = tmp_path / "wheelhouse"
    wheelhouse.mkdir()
    (wheelhouse / "fixture-1.0-py3-none-any.whl").write_bytes(wheel_bytes)
    payload = tmp_path / "payload.zip"
    with zipfile.ZipFile(payload, "w") as archive:
        archive.writestr("agent/my_agent.py", "class MyAgent: pass\n")
        archive.writestr("src/arc3/__init__.py", "\n")
        archive.writestr("../escape", "bad")
    source_commit = "2" * 40
    package_manifest = _fixture_package_manifest(
        tmp_path,
        runtime_manifest=manifest,
        requirements=requirements,
        payload=payload,
        source_commit=source_commit,
    )
    notebook = _fixture_notebook(
        tmp_path,
        requirements=requirements,
        payload=payload,
        source_commit=source_commit,
    )
    monkeypatch.setattr(
        cold_start,
        "_host_identity",
        lambda: ("Windows", "AMD64", "CPython", "3.12.14", "unknown"),
    )

    monkeypatch.setitem(cold_start._DISTRIBUTION_IMPORTS, "fixture", "fixture")
    with pytest.raises(PackagingError, match="unsafe member"):
        run_linux_cold_start(
            manifest,
            requirements,
            wheelhouse,
            payload,
            package_manifest,
            notebook_path=notebook,
            source_commit=source_commit,
        )


@pytest.mark.competition
def test_build002_cold_start_fails_closed_for_unmapped_runtime_distribution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest, requirements, _url, wheel_bytes = _fixture_manifest(tmp_path)
    wheelhouse = tmp_path / "wheelhouse"
    wheelhouse.mkdir()
    (wheelhouse / "fixture-1.0-py3-none-any.whl").write_bytes(wheel_bytes)
    payload = tmp_path / "payload.zip"
    payload.write_bytes(
        deterministic_zip_bytes(
            {
                "agent/my_agent.py": b"class MyAgent: pass\n",
                "src/arc3/__init__.py": b"\n",
            }
        )
    )
    source_commit = "3" * 40
    package_manifest = _fixture_package_manifest(
        tmp_path,
        runtime_manifest=manifest,
        requirements=requirements,
        payload=payload,
        source_commit=source_commit,
    )
    notebook = _fixture_notebook(
        tmp_path,
        requirements=requirements,
        payload=payload,
        source_commit=source_commit,
    )
    monkeypatch.delitem(cold_start._DISTRIBUTION_IMPORTS, "fixture", raising=False)

    with pytest.raises(PackagingError, match="lack explicit cold-start import targets"):
        run_linux_cold_start(
            manifest,
            requirements,
            wheelhouse,
            payload,
            package_manifest,
            notebook_path=notebook,
            source_commit=source_commit,
        )
