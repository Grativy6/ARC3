"""Subprocess tests for fail-closed package-only protected-path denial."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def test_package_only_pytest_denies_semantic_manifest_access(tmp_path: Path) -> None:
    fake_root = tmp_path / "repository"
    fake_manifest = fake_root / "docs" / "evaluation" / "fixture.json"
    fake_manifest.parent.mkdir(parents=True)
    fake_manifest.write_text('{"games":["sealed-fixture"]}\n', encoding="utf-8")
    test_file = tmp_path / "test_denied.py"
    test_file.write_text(
        "from pathlib import Path\n"
        "def test_denied():\n"
        f"    Path({str(fake_manifest)!r}).read_text(encoding='utf-8')\n",
        encoding="utf-8",
    )
    guard_log = tmp_path / "guard" / "attempts.jsonl"
    receipt = tmp_path / "output" / "guard-receipt.json"
    repository = Path(__file__).resolve().parents[2]

    completed = subprocess.run(
        (
            sys.executable,
            "-m",
            "scripts.package_only_pytest",
            "--root",
            str(fake_root),
            "--guard-log",
            str(guard_log),
            "--receipt",
            str(receipt),
            "--",
            "-q",
            "--no-cov",
            "--basetemp",
            str(tmp_path / "pytest-temp"),
            str(test_file),
        ),
        cwd=repository,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert completed.returncode == 3
    document = json.loads(receipt.read_text(encoding="utf-8"))
    assert document["status"] == "FAILED_BOUNDARY"
    assert document["attempt_count"] >= 1
    assert document["attempts"][0] == {
        "event": "open",
        "path": "docs/evaluation/fixture.json",
    }
