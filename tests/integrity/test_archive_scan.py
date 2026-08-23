"""Bounded final-archive integrity regressions."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest

from arc3.integrity import (
    FindingCategory,
    build_integrity_receipt,
    load_public_identifiers,
    scan_archive_files,
)


def _zip_bytes(
    members: dict[str, bytes | str],
    *,
    modes: dict[str, int] | None = None,
) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as handle:
        for name, content in members.items():
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            if modes is not None and name in modes:
                info.create_system = 3
                info.external_attr = modes[name] << 16
            handle.writestr(info, content)
    return buffer.getvalue()


def _write_candidate(path: Path, payload: bytes) -> None:
    path.write_bytes(_zip_bytes({"arc3-first-party.zip": payload}))


@pytest.mark.competition
def test_supplied_archive_policy_data_is_scanned(
    integrity_repo: tuple[Path, str, str],
) -> None:
    root, fake_game_id, _ = integrity_repo
    archive = root / "candidate.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr(
            "agent/known_actions.json",
            '{"target":"' + fake_game_id + '","actions":["ACTION1","ACTION2"]}',
        )
    public = load_public_identifiers(
        root / "docs" / "evaluation" / "public-game-partitions.v0.1.json"
    )
    findings = scan_archive_files(
        root=root,
        archives=(archive,),
        public_identifiers=public.identifiers,
    )
    assert any(
        finding.path.endswith("candidate.zip!/agent/known_actions.json")
        and finding.category is FindingCategory.PUBLIC_GAME_IDENTIFIER
        for finding in findings
    )
    receipt = build_integrity_receipt(
        root,
        archive_paths=(archive,),
        include_installed_metadata=False,
    )
    checks = receipt.body["checks"]
    assert isinstance(checks, dict)
    assert checks["archive_static"] == {"passed": False}


@pytest.mark.competition
def test_archive_path_traversal_is_blocking(integrity_repo: tuple[Path, str, str]) -> None:
    root, _, _ = integrity_repo
    archive = root / "unsafe.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("../outside.py", "VALUE = 1\n")
    findings = scan_archive_files(root=root, archives=(archive,), public_identifiers=())
    assert any(
        finding.category is FindingCategory.UNSAFE_ARCHIVE
        and finding.rule_id == "archive-central-directory-unsafe"
        for finding in findings
    )


@pytest.mark.competition
def test_explicit_external_archive_is_scanned_with_a_portable_label(
    integrity_repo: tuple[Path, str, str],
    tmp_path: Path,
) -> None:
    root, _, _ = integrity_repo
    archive = tmp_path / "generated-output" / "candidate.zip"
    archive.parent.mkdir()
    _write_candidate(
        archive,
        _zip_bytes({"agent/my_agent.py": "class MyAgent:\n    pass\n"}),
    )

    findings = scan_archive_files(root=root, archives=(archive,), public_identifiers=())
    assert findings == ()
    receipt = build_integrity_receipt(
        root,
        archive_paths=(archive,),
        include_installed_metadata=False,
    )
    inputs = receipt.body["inputs"]
    assert isinstance(inputs, dict)
    assert inputs["archive_paths"] == ["@supplied-archive/0000/candidate.zip"]
    files = receipt.body["source_hashes"]
    assert isinstance(files, dict)
    assert "@supplied-archive/0000/candidate.zip" in files
    assert str(tmp_path).encode("utf-8") not in receipt.canonical_bytes()


@pytest.mark.competition
def test_archived_first_party_network_call_is_blocked(
    integrity_repo: tuple[Path, str, str],
) -> None:
    root, _, _ = integrity_repo
    archive = root / "networked.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr(
            "agent/my_agent.py",
            "import subprocess as sp\nsp.run(['local-helper'])\n",
        )
    findings = scan_archive_files(root=root, archives=(archive,), public_identifiers=())
    assert any(
        finding.category is FindingCategory.FORBIDDEN_NETWORK_CLIENT
        and finding.rule_id == "network-capable-call"
        for finding in findings
    )


@pytest.mark.competition
def test_archived_runtime_launcher_gateway_import_exception_is_exact(
    integrity_repo: tuple[Path, str, str],
) -> None:
    root, _, _ = integrity_repo
    archive = root / "launcher.zip"
    launcher_path = "src/arc3/packaging/runtime_launcher.py"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr(
            launcher_path,
            "from urllib.request import ProxyHandler, Request, build_opener\n",
        )
    allowed = scan_archive_files(root=root, archives=(archive,), public_identifiers=())
    assert not any(
        finding.category is FindingCategory.FORBIDDEN_NETWORK_CLIENT for finding in allowed
    )

    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr(
            launcher_path,
            "from urllib.request import ProxyHandler, Request, build_opener, urlopen\n",
        )
    blocked = scan_archive_files(root=root, archives=(archive,), public_identifiers=())
    assert any(finding.category is FindingCategory.FORBIDDEN_NETWORK_CLIENT for finding in blocked)
