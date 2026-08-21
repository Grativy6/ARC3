"""Fresh-process and hard-timeout surface for the Stage 16 profiler."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "profile_competition.py"


def _head() -> str:
    return subprocess.run(
        ("git", "rev-parse", "HEAD"),
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout.strip()


@pytest.mark.integration
def test_profile_cli_runs_in_fresh_process_and_self_hashes_receipt(tmp_path: Path) -> None:
    output = tmp_path / "stage16-profile.json"
    completed = subprocess.run(
        (
            sys.executable,
            str(SCRIPT),
            "--root",
            str(ROOT),
            "--output",
            str(output),
            "--frozen-commit",
            _head(),
            "--work-root",
            str(tmp_path / "work"),
            "--seed",
            "7",
            "--frame-size",
            "8",
            "--fixture",
            "navigation",
            "--max-actions",
            "4",
            "--restart-every",
            "2",
            "--robustness-seeds",
            "7",
            "--robustness-actions",
            "4",
            "--worker-timeout-seconds",
            "900",
            "--skip-integrity",
            "--skip-regression",
        ),
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=1000,
    )
    assert completed.returncode == 1, completed.stderr
    result = json.loads(output.read_text(encoding="utf-8"))
    claimed = result.pop("receipt_sha256")
    canonical = json.dumps(
        result,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    assert claimed == f"sha256:{hashlib.sha256(canonical).hexdigest()}"
    assert result["launch"]["fresh_process"] is True
    assert result["launch"]["worker_exit_code"] == 1
    assert result["startup"]["phase_at_ready"] == "observed"
    assert result["profile"]["complete_action_chains"] is True
    assert result["first_party_import_identity"]["verified"] is True
    assert Path(result["first_party_import_identity"]["arc3_module"]).is_relative_to(
        ROOT / "src" / "arc3"
    )
    assert result["source_identity"]["verified"] is True
    assert result["competition_runtime_match"] is False
    assert result["status"] in {"PARTIAL", "FAILED_MECHANISM"}
    assert result["status"] != "PASS"
    assert result["verified"] is False
    assert result["worker_timeout"]["coherent"] is True
    assert "OS-level socket denial is not claimed" in result["network_enforcement"]


@pytest.mark.integration
def test_profile_cli_hard_timeout_preserves_failure_receipt(tmp_path: Path) -> None:
    output = tmp_path / "timeout.json"
    completed = subprocess.run(
        (
            sys.executable,
            str(SCRIPT),
            "--root",
            str(ROOT),
            "--output",
            str(output),
            "--frozen-commit",
            _head(),
            "--work-root",
            str(tmp_path / "timeout-work"),
            "--worker-timeout-seconds",
            "0.001",
            "--skip-integrity",
            "--skip-regression",
        ),
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
    )
    assert completed.returncode == 2
    result = json.loads(output.read_text(encoding="utf-8"))
    assert result["status"] == "FAILED_INFRASTRUCTURE"
    assert result["failure"]["kind"] == "worker-timeout"
    assert result["receipt_sha256"].startswith("sha256:")
