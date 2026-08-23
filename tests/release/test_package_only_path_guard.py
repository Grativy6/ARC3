"""Subprocess tests for fail-closed package-only protected-path denial."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


def _run_guarded_test(
    *,
    fake_root: Path,
    test_source: str,
    tmp_path: Path,
    extra_environment: dict[str, str] | None = None,
) -> tuple[subprocess.CompletedProcess[str], dict[str, object]]:
    test_file = fake_root / "tests" / "test_boundary_probe.py"
    test_file.parent.mkdir(parents=True, exist_ok=True)
    test_file.write_text(test_source, encoding="utf-8")
    guard_log = tmp_path / "guard" / "attempts.jsonl"
    receipt = tmp_path / "output" / "guard-receipt.json"
    repository = Path(__file__).resolve().parents[2]
    environment = dict(os.environ)
    if extra_environment is not None:
        environment.update(extra_environment)
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
            "--allow-root",
            str(repository),
            "--",
            "-q",
            "--no-cov",
            "--basetemp",
            str(fake_root / ".pytest-temp"),
            str(test_file),
        ),
        cwd=repository,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    return completed, json.loads(receipt.read_text(encoding="utf-8"))


@pytest.mark.skipif(os.name != "nt", reason="Windows framework path isolation")
def test_package_only_pytest_isolates_windows_framework_writable_paths(tmp_path: Path) -> None:
    fake_root = tmp_path / "repository"
    fake_manifest = fake_root / "docs" / "evaluation" / "fixture.json"
    fake_manifest.parent.mkdir(parents=True)
    fake_manifest.write_text("sealed\n", encoding="utf-8")
    hostile = tmp_path / "host-provided-state"
    hostile.mkdir()
    completed, document = _run_guarded_test(
        fake_root=fake_root,
        tmp_path=tmp_path,
        test_source=(
            "from pathlib import Path\n"
            "def test_denied():\n"
            f"    Path({str(fake_manifest)!r}).read_text(encoding='utf-8')\n"
        ),
        extra_environment={
            name: str(hostile)
            for name in ("APPDATA", "HOME", "LOCALAPPDATA", "TEMP", "TMP", "USERPROFILE")
        },
    )

    assert completed.returncode == 3
    assert document["framework_writable_state"] == "isolated-under-allowed-guard-parent"
    assert document["attempts"] == [{"event": "open", "path": "docs/evaluation/fixture.json"}]


def test_package_only_pytest_denies_semantic_manifest_access(tmp_path: Path) -> None:
    fake_root = tmp_path / "repository"
    fake_manifest = fake_root / "docs" / "evaluation" / "fixture.json"
    fake_manifest.parent.mkdir(parents=True)
    fake_manifest.write_text('{"games":["sealed-fixture"]}\n', encoding="utf-8")
    completed, document = _run_guarded_test(
        fake_root=fake_root,
        tmp_path=tmp_path,
        test_source=(
            "from pathlib import Path\n"
            "def test_denied():\n"
            f"    Path({str(fake_manifest)!r}).read_text(encoding='utf-8')\n"
        ),
    )

    assert completed.returncode == 3
    assert document["status"] == "FAILED_BOUNDARY"
    assert document["attempt_count"] >= 1
    assert {
        "event": "open",
        "path": "docs/evaluation/fixture.json",
    } in document["attempts"]


def test_package_only_pytest_denies_isolated_python_child(tmp_path: Path) -> None:
    fake_root = tmp_path / "repository"
    protected = fake_root / "docs" / "evaluation" / "fixture.json"
    protected.parent.mkdir(parents=True)
    protected.write_text("sealed\n", encoding="utf-8")
    completed, document = _run_guarded_test(
        fake_root=fake_root,
        tmp_path=tmp_path,
        test_source=(
            "import subprocess,sys\n"
            "def test_child():\n"
            "    subprocess.run([sys.executable, '-I', '-c', "
            "\"print('unexpected-child')\"], check=True)\n"
        ),
    )

    assert completed.returncode == 3
    assert document["status"] == "FAILED_BOUNDARY"
    assert any(
        attempt == {"event": "subprocess.Popen", "path": "child-process"}
        for attempt in document["attempts"]
    )


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="POSIX clone audit events")
@pytest.mark.parametrize("operation", ("fork", "forkpty"))
def test_package_only_pytest_denies_transitive_posix_clone_events(
    tmp_path: Path,
    operation: str,
) -> None:
    fake_root = tmp_path / "repository"
    completed, document = _run_guarded_test(
        fake_root=fake_root,
        tmp_path=tmp_path,
        test_source=(
            "from process_clone_probe import attempt_clone\n"
            f"OPERATION = {operation!r}\n"
            "def test_clone_event():\n"
            "    attempt_clone(OPERATION)\n"
        ),
    )

    assert completed.returncode == 3
    assert document["status"] == "FAILED_BOUNDARY"
    assert {"event": f"os.{operation}", "path": "child-process"} in document["attempts"]


@pytest.mark.parametrize(
    ("statement", "event", "relative"),
    [
        ("os.remove(PROTECTED)", "os.remove", "docs/evaluation/fixture.json"),
        ("os.rename(PROTECTED, TARGET)", "os.rename", "docs/evaluation/fixture.json"),
        ("os.replace(PROTECTED, TARGET)", "os.rename", "docs/evaluation/fixture.json"),
        ("os.chmod(PROTECTED, 0o600)", "os.chmod", "docs/evaluation/fixture.json"),
        ("os.link(PROTECTED, TARGET)", "os.link", "docs/evaluation/fixture.json"),
        ("os.rmdir(PARENT)", "os.rmdir", "docs/evaluation"),
    ],
)
def test_package_only_pytest_denies_protected_mutations(
    tmp_path: Path,
    statement: str,
    event: str,
    relative: str,
) -> None:
    fake_root = tmp_path / "repository"
    protected = fake_root / "docs" / "evaluation" / "fixture.json"
    protected.parent.mkdir(parents=True)
    protected.write_text("sealed\n", encoding="utf-8")
    target = fake_root / "target.json"
    completed, document = _run_guarded_test(
        fake_root=fake_root,
        tmp_path=tmp_path,
        test_source=(
            "import os\n"
            f"PROTECTED = {str(protected)!r}\n"
            f"PARENT = {str(protected.parent)!r}\n"
            f"TARGET = {str(target)!r}\n"
            "def test_mutation():\n"
            f"    {statement}\n"
        ),
    )

    assert completed.returncode == 3
    assert protected.read_text(encoding="utf-8") == "sealed\n"
    assert {"event": event, "path": relative} in document["attempts"]


def test_package_only_pytest_default_denies_external_paths(tmp_path: Path) -> None:
    fake_root = tmp_path / "repository"
    prefix = Path(sys.prefix).resolve()
    external_parent = prefix.parent if tmp_path.resolve().is_relative_to(prefix) else tmp_path
    external_root = external_parent / f"arc3-guard-external-{tmp_path.name}"
    external = external_root / "fixture.json"
    external.parent.mkdir(parents=True)
    external.write_text("external\n", encoding="utf-8")
    try:
        completed, document = _run_guarded_test(
            fake_root=fake_root,
            tmp_path=tmp_path,
            test_source=(
                "from pathlib import Path\n"
                "def test_external():\n"
                f"    Path({str(external)!r}).read_text(encoding='utf-8')\n"
            ),
        )
    finally:
        external.unlink(missing_ok=True)
        external_root.rmdir()

    assert completed.returncode == 3
    assert {"event": "open", "path": "protected-external-path"} in document["attempts"]


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux /proc boundary")
def test_package_only_pytest_allows_only_exact_read_only_linux_rss_surface(
    tmp_path: Path,
) -> None:
    fake_root = tmp_path / "repository"
    completed, document = _run_guarded_test(
        fake_root=fake_root,
        tmp_path=tmp_path,
        test_source=(
            "from pathlib import Path\n"
            "def test_kernel_rss():\n"
            "    assert 'VmRSS' in Path('/proc/self/status').read_text(encoding='utf-8')\n"
        ),
    )

    assert completed.returncode == 0, completed.stderr
    assert document["status"] == "PASS"
    assert document["attempts"] == []
    assert document["kernel_telemetry_paths"] == ["/proc/self/status"]
    assert document["kernel_telemetry_read_count"] == 1


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux /proc boundary")
@pytest.mark.parametrize(
    "statement",
    (
        "Path('/proc/self/cmdline').read_text(encoding='utf-8')",
        "Path(f'/proc/{os.getpid()}/status').read_text(encoding='utf-8')",
        "Path('/proc/thread-self/status').read_text(encoding='utf-8')",
        "Path('/proc/self/../self/status').read_text(encoding='utf-8')",
        "Path('/proc/self/status').write_text('denied', encoding='utf-8')",
    ),
)
def test_package_only_pytest_denies_linux_proc_siblings_aliases_and_writes(
    tmp_path: Path,
    statement: str,
) -> None:
    fake_root = tmp_path / "repository"
    completed, document = _run_guarded_test(
        fake_root=fake_root,
        tmp_path=tmp_path,
        test_source=(
            "import os\n"
            "from pathlib import Path\n"
            "def test_denied_proc_surface():\n"
            f"    {statement}\n"
        ),
    )

    assert completed.returncode == 3
    assert document["kernel_telemetry_read_count"] == 0
    assert {"event": "open", "path": "protected-external-path"} in document["attempts"]


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux /proc boundary")
def test_package_only_pytest_denies_symlink_alias_to_linux_rss_surface(tmp_path: Path) -> None:
    fake_root = tmp_path / "repository"
    fake_root.mkdir()
    alias = fake_root / "rss-alias"
    alias.symlink_to("/proc/self/status")
    completed, document = _run_guarded_test(
        fake_root=fake_root,
        tmp_path=tmp_path,
        test_source=(
            "from pathlib import Path\n"
            "def test_denied_rss_alias():\n"
            f"    Path({str(alias)!r}).read_text(encoding='utf-8')\n"
        ),
    )

    assert completed.returncode == 3
    assert document["kernel_telemetry_read_count"] == 0
    assert {"event": "open", "path": "protected-external-path"} in document["attempts"]


def test_package_only_pytest_canonicalizes_directory_links(tmp_path: Path) -> None:
    fake_root = tmp_path / "repository"
    protected_root = fake_root / "docs" / "evaluation"
    protected_root.mkdir(parents=True)
    protected = protected_root / "fixture.json"
    protected.write_text("sealed\n", encoding="utf-8")
    link = fake_root / "safe-link"
    if os.name == "nt":
        created = subprocess.run(
            ("cmd.exe", "/d", "/c", "mklink", "/J", str(link), str(protected_root)),
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if created.returncode != 0:
            pytest.skip(f"directory junctions are unavailable on this host: {created.stderr}")
    else:
        link.symlink_to(protected_root, target_is_directory=True)
    try:
        completed, document = _run_guarded_test(
            fake_root=fake_root,
            tmp_path=tmp_path,
            test_source=(
                "from pathlib import Path\n"
                "def test_link():\n"
                f"    Path({str(link / 'fixture.json')!r}).read_text(encoding='utf-8')\n"
            ),
        )
    finally:
        if os.name == "nt":
            link.rmdir()
        else:
            link.unlink()

    assert completed.returncode == 3
    assert {"event": "open", "path": "docs/evaluation/fixture.json"} in document["attempts"]


def test_package_only_pytest_protects_guard_log(tmp_path: Path) -> None:
    fake_root = tmp_path / "repository"
    completed, document = _run_guarded_test(
        fake_root=fake_root,
        tmp_path=tmp_path,
        test_source=(
            "import os\n"
            "from pathlib import Path\n"
            "def test_log():\n"
            "    Path(os.environ['ARC3_PACKAGE_ONLY_GUARD_LOG']).unlink()\n"
        ),
    )

    assert completed.returncode == 3
    assert {"event": "os.remove", "path": "protected-external-path"} in document["attempts"]
