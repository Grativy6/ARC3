"""Collision-safe deterministic receipt-output regressions."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest


def _script() -> Path:
    return Path(__file__).resolve().parents[2] / "scripts" / "check_competition_integrity.py"


def _initialize_fixture_git(root: Path) -> None:
    subprocess.run(["git", "init", "--quiet", str(root)], check=True, capture_output=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(root),
            "add",
            "--",
            "agent",
            "docs",
            "uv.lock",
            "pyproject.toml",
            "upstream.lock.json",
            "THIRD_PARTY_NOTICES.md",
        ],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        [
            "git",
            "-C",
            str(root),
            "-c",
            "user.name=ARC3 Integrity Test",
            "-c",
            "user.email=integrity-test@example.invalid",
            "commit",
            "--quiet",
            "-m",
            "test fixture",
            "-m",
            (
                "This commit was initiated by human direction, prepared by AI systems, "
                "and approved by one-time human authorization."
            ),
        ],
        check=True,
        capture_output=True,
    )


@pytest.mark.competition
def test_in_repository_output_is_stably_excluded_and_atomically_replaced(
    integrity_repo: tuple[Path, str, str],
) -> None:
    root, _, _ = integrity_repo
    _initialize_fixture_git(root)
    output = root / "evidence" / "integrity-receipt.json"
    command = [sys.executable, str(_script()), "--root", str(root), "--output", str(output)]
    first = subprocess.run(command, check=False, capture_output=True)
    assert first.returncode == 1, first.stderr.decode("utf-8", errors="replace")
    first_bytes = output.read_bytes()
    second = subprocess.run(command, check=False, capture_output=True)
    assert second.returncode == 1, second.stderr.decode("utf-8", errors="replace")
    assert output.read_bytes() == first_bytes
    assert first.stdout.rstrip(b"\n") == first_bytes
    assert second.stdout.rstrip(b"\n") == first_bytes
    assert not tuple(output.parent.glob(f".{output.name}.*.tmp"))


@pytest.mark.competition
def test_output_collision_refuses_to_overwrite_required_input(
    integrity_repo: tuple[Path, str, str],
) -> None:
    root, _, _ = integrity_repo
    lock = root / "uv.lock"
    before = lock.read_bytes()
    completed = subprocess.run(
        [sys.executable, str(_script()), "--root", str(root), "--output", str(lock)],
        check=False,
        capture_output=True,
    )
    assert completed.returncode == 2
    assert b"collides" in completed.stderr
    assert lock.read_bytes() == before
