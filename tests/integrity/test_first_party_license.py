"""Owner-approved first-party license identity regressions."""

from __future__ import annotations

from pathlib import Path

import pytest

from arc3.integrity import build_integrity_receipt, inventory_locked_dependencies
from arc3.licensing import MIT0_LICENSE_SHA256, first_party_license_identity


@pytest.mark.competition
def test_root_license_matches_preserved_candidate_and_metadata() -> None:
    root = Path(__file__).resolve().parents[2]
    candidate = (root / "docs/legal/candidates/MIT-0-CANDIDATE.md").read_text(encoding="utf-8")
    operative = (root / "LICENSE").read_text(encoding="utf-8")
    assert operative.strip() == candidate.split("---\n", maxsplit=1)[1].strip()
    assert first_party_license_identity(root) == (
        "MIT-0",
        (
            "license-expression:MIT-0",
            f"license-sha256:{MIT0_LICENSE_SHA256}",
        ),
    )


@pytest.mark.competition
def test_modified_first_party_license_fails_closed(
    integrity_repo: tuple[Path, str, str],
) -> None:
    root, _, _ = integrity_repo
    (root / "LICENSE").write_text("not the owner-approved license\n", encoding="utf-8")
    records = inventory_locked_dependencies(root / "uv.lock", include_installed_metadata=False)
    arc3 = next(record for record in records if record.name == "arc3")
    assert arc3.license_status == "LICENSE_HASH_MISMATCH"
    receipt = build_integrity_receipt(root, include_installed_metadata=False)
    assert not receipt.passed
    assert any(
        finding["rule_id"] == "first-party-license-invalid"
        for finding in receipt.body["findings"]
        if isinstance(finding, dict)
    )
