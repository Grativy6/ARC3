"""Clean-checkout contracts for packaging, CLI, bootstrap scripts, and CI."""

from __future__ import annotations

import json
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def test_project_metadata_exposes_python312_arc3_cli() -> None:
    metadata = tomllib.loads((REPOSITORY_ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    assert metadata["project"]["requires-python"] == ">=3.12,<3.13"
    assert metadata["project"]["scripts"]["arc3"] == "arc3.cli:main"
    assert metadata["tool"]["mypy"]["strict"] is True
    assert (REPOSITORY_ROOT / ".python-version").read_text(encoding="utf-8").strip() == "3.12.14"


@pytest.mark.integration
@pytest.mark.parametrize(
    ("relative_path", "check_token"),
    [("scripts/bootstrap.ps1", "$Check"), ("scripts/bootstrap.sh", "--check")],
)
def test_clean_checkout_bootstraps_are_location_independent_and_pinned(
    relative_path: str,
    check_token: str,
) -> None:
    script = (REPOSITORY_ROOT / relative_path).read_text(encoding="utf-8")

    assert "0.12.5" in script
    assert "3.12.14" in script
    assert check_token in script
    assert "sync" in script and "--all-extras" in script and "--dev" in script
    assert "ruff check ." in script
    assert "ruff format --check ." in script
    assert "mypy src agent scripts" in script
    assert "pytest -q" in script
    assert "arc3 doctor" in script
    assert "PSScriptRoot" in script or 'dirname -- "$0"' in script


@pytest.mark.integration
def test_ci_exercises_locked_linux_and_windows_smoke_contract() -> None:
    workflow = (REPOSITORY_ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")

    assert "ubuntu-latest" in workflow
    assert "windows-latest" in workflow
    assert "uv sync --locked --all-extras --dev --python 3.12.14" in workflow
    assert "uv run mypy src agent scripts" in workflow
    assert "uv run pytest -q" in workflow
    assert "uv run arc3 doctor" in workflow


@pytest.mark.integration
def test_module_cli_is_available_from_installed_clean_checkout() -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "arc3", "doctor", "--json"],
        cwd=REPOSITORY_ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert completed.returncode == 0, completed.stderr
    report = json.loads(completed.stdout)
    assert report["schema"] == "arc3.doctor.v0.1"
    assert report["passed"] is True


@pytest.mark.integration
def test_bootstrap_inputs_exist_in_repository_skeleton() -> None:
    required = (
        "pyproject.toml",
        "uv.lock",
        ".python-version",
        ".gitignore",
        ".pre-commit-config.yaml",
        "scripts/bootstrap.ps1",
        "scripts/bootstrap.sh",
        "src/arc3/__init__.py",
        "src/arc3/__main__.py",
        "agent/my_agent.py",
    )

    missing = [path for path in required if not (REPOSITORY_ROOT / path).is_file()]
    assert missing == []
