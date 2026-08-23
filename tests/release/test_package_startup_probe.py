"""Offline subprocess tests for the package-only startup measurement."""

from __future__ import annotations

import hashlib
import io
import json
import subprocess
import sys
import zipfile
from pathlib import Path


def _canonical_line(value: object) -> bytes:
    return (
        json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def _sha256(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


def _payload() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_STORED) as archive:
        for name, content in {
            "agent/my_agent.py": (
                b"class MyAgent:\n"
                b"    def __init__(self, game_id, agent_name, seed):\n"
                b"        self.name = agent_name\n"
            ),
            "src/arc3/__init__.py": b'__version__ = "fixture"\n',
        }.items():
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            archive.writestr(info, content)
    return buffer.getvalue()


def test_package_startup_probe_uses_only_extracted_offline_fixture(tmp_path: Path) -> None:
    package = tmp_path / "package"
    package.mkdir()
    payload = _payload()
    (package / "arc3-first-party.zip").write_bytes(payload)
    expected_commit = "a" * 40
    (package / "package-manifest.json").write_bytes(
        _canonical_line({"source": {"git_commit": expected_commit}})
    )
    body = {
        "payload_sha256": _sha256(payload),
        "status": "PACKAGING_PASS",
    }
    receipt = dict(body)
    receipt["receipt_sha256"] = _sha256(_canonical_line(body))
    (package / "build-receipt.json").write_bytes(_canonical_line(receipt))
    repository = Path(__file__).resolve().parents[2]

    completed = subprocess.run(
        (
            sys.executable,
            "-I",
            str(repository / "scripts" / "package_startup_probe.py"),
            "--package-root",
            str(package),
            "--expected-commit",
            expected_commit,
        ),
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    assert result["status"] == "PASS"
    assert result["network_attempts"] == 0
    assert result["payload_sha256"] == _sha256(payload)
    assert result["total_seconds"] >= result["import_seconds"]
