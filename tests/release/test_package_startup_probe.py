"""Offline subprocess tests for the package-only startup measurement."""

from __future__ import annotations

import hashlib
import io
import json
import stat
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest


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


def _payload(
    *,
    agent_source: bytes | None = None,
    extra_name: str | None = None,
    extra_mode: int | None = None,
    extra_create_system: int = 3,
) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_STORED) as archive:
        for name, content in {
            "agent/my_agent.py": agent_source
            or (
                b"class MyAgent:\n"
                b"    def __init__(self, game_id, agent_name, seed):\n"
                b"        self.name = agent_name\n"
            ),
            "src/arc3/__init__.py": b'__version__ = "fixture"\n',
        }.items():
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            archive.writestr(info, content)
        if extra_name is not None:
            info = zipfile.ZipInfo(extra_name, date_time=(1980, 1, 1, 0, 0, 0))
            info.filename = extra_name
            info.create_system = extra_create_system
            if extra_mode is not None:
                info.external_attr = extra_mode
            archive.writestr(info, b"unsafe-fixture")
    return buffer.getvalue()


def _write_package(package: Path, payload: bytes, expected_commit: str) -> None:
    package.mkdir()
    (package / "arc3-first-party.zip").write_bytes(payload)
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


def _run_probe(package: Path, expected_commit: str) -> subprocess.CompletedProcess[str]:
    repository = Path(__file__).resolve().parents[2]
    return subprocess.run(
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


def test_package_startup_probe_uses_only_extracted_offline_fixture(tmp_path: Path) -> None:
    package = tmp_path / "package"
    expected_commit = "a" * 40
    payload = _payload()
    _write_package(package, payload, expected_commit)
    completed = _run_probe(package, expected_commit)

    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    assert result["status"] == "PASS"
    assert result["network_attempts"] == 0
    assert result["network_attempt_events"] == []
    assert result["network_enforcement"] == "python-audit-hook-socket-events"
    assert result["process_launch_attempts"] == 0
    assert result["process_launch_attempt_events"] == []
    assert result["payload_sha256"] == _sha256(payload)
    assert result["tournament_configured"] is False
    assert result["total_seconds"] >= result["import_seconds"]


def test_package_startup_probe_configures_competition_agent_before_instantiation(
    tmp_path: Path,
) -> None:
    package = tmp_path / "package"
    expected_commit = "c" * 40
    payload = _payload(
        agent_source=(
            b"class MyAgent:\n"
            b"    configured_games = ()\n"
            b"    @classmethod\n"
            b"    def configure_tournament(cls, game_ids, working_root):\n"
            b"        cls.configured_games = tuple(game_ids)\n"
            b"    def __init__(self, game_id, agent_name, seed):\n"
            b"        assert self.configured_games == (game_id,)\n"
            b"        self.name = agent_name\n"
        )
    )
    _write_package(package, payload, expected_commit)

    completed = _run_probe(package, expected_commit)

    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    assert result["status"] == "PASS"
    assert result["tournament_configured"] is True
    assert result["network_attempts"] == 0
    assert result["process_launch_attempts"] == 0


def test_package_startup_probe_denies_udp_sendto(tmp_path: Path) -> None:
    package = tmp_path / "package"
    payload = _payload(
        agent_source=(
            b"import socket\n"
            b"class MyAgent:\n"
            b"    def __init__(self, game_id, agent_name, seed):\n"
            b"        socket.socket(socket.AF_INET, socket.SOCK_DGRAM).sendto(b'x', ('127.0.0.1', 9))\n"
            b"        self.name = agent_name\n"
        )
    )
    expected_commit = "a" * 40
    _write_package(package, payload, expected_commit)
    completed = _run_probe(package, expected_commit)

    assert completed.returncode == 2
    assert "forbids Python socket event" in completed.stderr


def test_package_startup_probe_denies_child_process(tmp_path: Path) -> None:
    package = tmp_path / "package"
    payload = _payload(
        agent_source=(
            b"import subprocess, sys\n"
            b"class MyAgent:\n"
            b"    def __init__(self, game_id, agent_name, seed):\n"
            b"        subprocess.run([sys.executable, '-c', 'print(1)'], check=True)\n"
            b"        self.name = agent_name\n"
        )
    )
    expected_commit = "a" * 40
    _write_package(package, payload, expected_commit)
    completed = _run_probe(package, expected_commit)

    assert completed.returncode == 2
    assert "forbids child process event subprocess.Popen" in completed.stderr


@pytest.mark.parametrize(
    ("member_name", "external_attr", "create_system"),
    (
        ("C:/escape.py", None, 3),
        ("C:escape.py", None, 3),
        ("agent/cache:stream.py", None, 3),
        ("//server/share/escape.py", None, 3),
        (r"agent\shadow.py", None, 3),
        ("src/arc3/../escape.py", None, 3),
        ("agent/./shadow.py", None, 3),
        ("agent/link.py", (stat.S_IFLNK | 0o777) << 16, 3),
        ("agent/reparse.py", 0x400, 0),
    ),
)
def test_package_startup_probe_rejects_cross_platform_unsafe_members(
    tmp_path: Path,
    member_name: str,
    external_attr: int | None,
    create_system: int,
) -> None:
    package = tmp_path / "package"
    expected_commit = "b" * 40
    payload = _payload(
        extra_name=member_name,
        extra_mode=external_attr,
        extra_create_system=create_system,
    )
    _write_package(package, payload, expected_commit)

    completed = _run_probe(package, expected_commit)

    assert completed.returncode == 2
    assert "unsafe or incomplete member set" in completed.stderr
