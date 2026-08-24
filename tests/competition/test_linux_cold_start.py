"""Build 002 wheelhouse acquisition and native cold-start boundaries."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path
from typing import Any

import pytest

from arc3.packaging import cold_start
from arc3.packaging.cold_start import (
    acquire_runtime_wheelhouse,
    load_runtime_wheel_manifest,
    run_linux_cold_start,
)
from arc3.packaging.models import PackagingError
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
        source_commit=source_commit,
    )

    assert receipt.status == "BLOCKED_PLATFORM"
    assert receipt.executed is False
    assert receipt.deterministic_repetitions == 0
    assert receipt.stable_projection_sha256 is None
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
    monkeypatch.delitem(cold_start._DISTRIBUTION_IMPORTS, "fixture", raising=False)

    with pytest.raises(PackagingError, match="lack explicit cold-start import targets"):
        run_linux_cold_start(
            manifest,
            requirements,
            wheelhouse,
            payload,
            package_manifest,
            source_commit=source_commit,
        )
