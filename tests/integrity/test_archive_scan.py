"""Bounded final-archive integrity regressions."""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from arc3.integrity import (
    FindingCategory,
    build_integrity_receipt,
    load_public_identifiers,
    scan_archive_files,
)


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
        and finding.rule_id == "archive-path-traversal"
        for finding in findings
    )


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
