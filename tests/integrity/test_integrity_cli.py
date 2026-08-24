"""Collision-safe deterministic receipt-output regressions."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
import scripts.check_competition_integrity as integrity_cli
from scripts.check_competition_integrity import package_only_candidate_files


def _script() -> Path:
    return Path(__file__).resolve().parents[2] / "scripts" / "check_competition_integrity.py"


def _initialize_fixture_git(root: Path) -> str:
    subprocess.run(["git", "init", "--quiet", str(root)], check=True, capture_output=True)
    subprocess.run(
        ("git", "-C", str(root), "config", "core.autocrlf", "false"),
        check=True,
        capture_output=True,
    )
    subprocess.run(
        [
            "git",
            "-C",
            str(root),
            "add",
            "--",
            "agent",
            "docs",
            "LICENSE",
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
    return subprocess.run(
        ("git", "-C", str(root), "rev-parse", "HEAD"),
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def test_exact_git_blob_projection_rejects_oversize_before_content_fetch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    object_id = "0" * 40

    def metadata_only(
        _root: Path,
        *arguments: str,
        input_bytes: bytes | None = None,
    ) -> bytes:
        assert arguments == ("cat-file", "--batch-check")
        assert input_bytes == f"{object_id}\n".encode("ascii")
        return f"{object_id} blob {integrity_cli.DEFAULT_MAX_CANDIDATE_BYTES + 1}\n".encode()

    def refuse_content_fetch(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("oversize Git blob content must not be fetched")

    monkeypatch.setattr(integrity_cli, "_git_bytes", metadata_only)
    monkeypatch.setattr(integrity_cli.subprocess, "Popen", refuse_content_fetch)

    with pytest.raises(ValueError, match="per-file byte limit"):
        integrity_cli._git_blob_bytes(tmp_path, (object_id,))


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


@pytest.mark.competition
def test_package_only_cli_excludes_ledger_and_manifest_semantics(
    integrity_repo: tuple[Path, str, str],
) -> None:
    root, _, _ = integrity_repo
    expected_commit = _initialize_fixture_git(root)
    completed = subprocess.run(
        (
            sys.executable,
            str(_script()),
            "--root",
            str(root),
            "--package-only",
            "--expected-commit",
            expected_commit,
            "--lock-only-metadata",
        ),
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 1
    receipt = json.loads(completed.stdout)
    assert receipt["passed"] is False
    assert receipt["package_only_passed"] is False
    assert receipt["full_competition_integrity_status"] == "NOT_EVALUATED_PUBLIC_IDENTIFIERS"
    assert receipt["inputs"]["manifest"] is None
    assert receipt["inputs"]["run_state"] is None
    assert not any(
        path.startswith("docs/evaluation/") or path.startswith("docs/ledger/")
        for path in receipt["inputs"]["candidate_paths"]
    )


@pytest.mark.competition
def test_package_only_cli_rejects_manifest_argument_before_scanning(
    integrity_repo: tuple[Path, str, str],
) -> None:
    root, _, _ = integrity_repo
    completed = subprocess.run(
        (
            sys.executable,
            str(_script()),
            "--root",
            str(root),
            "--package-only",
            "--manifest",
            "docs/evaluation/public-game-partitions.v0.1.json",
        ),
        check=False,
        capture_output=True,
    )

    assert completed.returncode == 2
    assert b"--package-only forbids" in completed.stderr


@pytest.mark.competition
def test_package_only_candidate_projection_ignores_hostile_git_redirection(
    integrity_repo: tuple[Path, str, str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, _, _ = integrity_repo
    commit = _initialize_fixture_git(root)
    decoy = tmp_path / "decoy"
    subprocess.run(("git", "init", "--quiet", str(decoy)), check=True, capture_output=True)
    monkeypatch.setenv("GIT_DIR", str(decoy / ".git"))
    monkeypatch.setenv("GIT_WORK_TREE", str(decoy))
    monkeypatch.setenv("GIT_INDEX_FILE", str(decoy / "hostile-index"))

    candidates = package_only_candidate_files(root, commit)

    assert root / "agent" / "my_agent.py" in candidates


@pytest.mark.competition
def test_package_only_candidate_projection_rejects_hidden_or_empty_index_evidence(
    integrity_repo: tuple[Path, str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, _, _ = integrity_repo
    commit = _initialize_fixture_git(root)
    subprocess.run(
        ("git", "-C", str(root), "update-index", "--assume-unchanged", "agent/my_agent.py"),
        check=True,
        capture_output=True,
    )
    with pytest.raises(ValueError, match="non-H Git index entry"):
        package_only_candidate_files(root, commit)

    subprocess.run(
        ("git", "-C", str(root), "update-index", "--no-assume-unchanged", "agent/my_agent.py"),
        check=True,
        capture_output=True,
    )
    real_git_bytes = integrity_cli._git_bytes

    def empty_index(repository: Path, *arguments: str, input_bytes: bytes | None = None) -> bytes:
        if arguments == ("ls-files", "-v", "-z"):
            return b""
        return real_git_bytes(repository, *arguments, input_bytes=input_bytes)

    monkeypatch.setattr(integrity_cli, "_git_bytes", empty_index)
    with pytest.raises(ValueError, match="index membership"):
        package_only_candidate_files(root, commit)
