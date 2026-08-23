from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[2]
WORKER_PATH = ROOT / "scripts" / "_stage10_checkpoint_worker.py"


@pytest.fixture(scope="module")
def worker() -> ModuleType:
    module_name = "_arc3_stage10_checkpoint_worker_test"
    specification = importlib.util.spec_from_file_location(module_name, WORKER_PATH)
    assert specification is not None and specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    sys.modules[module_name] = module
    specification.loader.exec_module(module)
    return module


@pytest.mark.integration
def test_checkpoint_worker_git_identity_disables_redirection_and_replacements(
    worker: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GIT_DIR", "redirected.git")
    monkeypatch.setenv("git_work_tree", "redirected-worktree")
    captured: dict[str, str] = {}

    def fake_run(*_args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        captured.update(kwargs["env"])
        return subprocess.CompletedProcess([], 0, stdout="", stderr="")

    monkeypatch.setattr(worker.subprocess, "run", fake_run)

    assert worker._git("rev-parse", "HEAD") == ""
    assert captured["GIT_NO_REPLACE_OBJECTS"] == "1"
    assert "GIT_DIR" not in captured
    assert "git_work_tree" not in captured


@pytest.mark.integration
def test_synthetic_checkpoint_worker_exercises_all_exact_gates(
    tmp_path: Path,
    worker: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    frozen = "f" * 40
    monkeypatch.setattr(
        worker,
        "_source_identity",
        lambda _commit: {
            "dirty_worktree": False,
            "git_commit": frozen,
            "git_tree": "e" * 40,
            "verified": True,
        },
    )
    report = worker.run_measurement(
        work_root=tmp_path / "work",
        frozen_commit=frozen,
        command=("focused-pytest",),
    )
    assert report["status"] == "PASS"
    assert report["acceptance"] == {
        "checkpoint_tamper_rejected": True,
        "deep_exact_continuation": True,
        "deterministic_seed_repeatability": True,
        "fast_exact_continuation": True,
        "trace_replay": True,
        "trace_tamper_rejected": True,
    }
    assert report["deep_continuation"]["path"] == "DEEP"
    assert report["fast_continuation"]["path"] == "FAST"
