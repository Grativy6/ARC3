"""Redacted secret detection tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from arc3.integrity import FindingCategory, discover_candidate_files, scan_secret_files


@pytest.mark.competition
def test_likely_secret_is_blocking_and_redacted(tmp_path: Path) -> None:
    token = "sk-" + ("q" * 36)
    candidate = tmp_path / "candidate.py"
    candidate.write_text("TOKEN = " + repr(token) + "\n", encoding="utf-8")
    findings = scan_secret_files(root=tmp_path, files=(candidate,))
    assert len(findings) == 1
    finding = findings[0]
    assert finding.category is FindingCategory.LIKELY_SECRET
    assert token not in finding.message
    assert token not in str(finding.to_dict())
    assert finding.evidence_sha256.startswith("sha256:")


@pytest.mark.competition
@pytest.mark.parametrize(
    "placeholder",
    [
        "your_api_key_placeholder_value",
        "SENTINEL_NOT_A_SECRET",
        "sk-proj-" + "abcdefghijklmnop",
    ],
)
def test_placeholder_is_not_reported_as_a_secret(tmp_path: Path, placeholder: str) -> None:
    candidate = tmp_path / ".env.example"
    candidate.write_text(
        "API_KEY=" + repr(placeholder) + "\n",
        encoding="utf-8",
    )
    assert scan_secret_files(root=tmp_path, files=(candidate,)) == ()


@pytest.mark.competition
def test_private_key_in_uncommon_extension_is_discovered_and_blocked(tmp_path: Path) -> None:
    candidate = tmp_path / "credential.pem"
    candidate.write_text(
        "-----BEGIN " + "PRIVATE KEY-----\nnot-real\n",
        encoding="utf-8",
    )
    discovered = discover_candidate_files(tmp_path)
    assert candidate in discovered
    findings = scan_secret_files(root=tmp_path, files=discovered)
    assert any(finding.rule_id == "private-key-header" for finding in findings)


@pytest.mark.competition
def test_binary_bytes_are_scanned_for_ascii_tokens(tmp_path: Path) -> None:
    token = "sk-" + ("z" * 36)
    candidate = tmp_path / "payload.bin"
    candidate.write_bytes(b"\x00\xff" + token.encode("ascii") + b"\x00")
    findings = scan_secret_files(root=tmp_path, files=(candidate,))
    assert any(finding.rule_id == "hosted-model-token" for finding in findings)
    assert token not in str(findings)


@pytest.mark.competition
def test_oversize_candidate_is_a_blocking_unscannable_finding(tmp_path: Path) -> None:
    candidate = tmp_path / "large.dat"
    candidate.write_bytes(b"x" * 9)
    findings = scan_secret_files(root=tmp_path, files=(candidate,), max_bytes=8)
    assert len(findings) == 1
    assert findings[0].category is FindingCategory.UNSCANNABLE_CANDIDATE
    assert findings[0].rule_id == "candidate-size-limit"


@pytest.mark.competition
def test_placeholder_variable_name_does_not_suppress_real_value(tmp_path: Path) -> None:
    token = "sk-" + ("r" * 36)
    candidate = tmp_path / "candidate.py"
    candidate.write_text("EXAMPLE_API_KEY = " + repr(token) + "\n", encoding="utf-8")
    findings = scan_secret_files(root=tmp_path, files=(candidate,))
    assert any(finding.rule_id == "hosted-model-token" for finding in findings)
