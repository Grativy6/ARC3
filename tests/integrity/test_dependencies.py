"""Offline dependency/license inventory tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from arc3.integrity import build_integrity_receipt, inventory_locked_dependencies
from arc3.licensing import MIT0_LICENSE_SHA256


def _write_owner_approved_license(root: Path) -> None:
    project_root = Path(__file__).resolve().parents[2]
    (root / "LICENSE").write_bytes((project_root / "LICENSE").read_bytes())
    (root / "pyproject.toml").write_text(
        '[project]\nname="arc3"\nlicense="MIT-0"\nlicense-files=["LICENSE"]\n',
        encoding="utf-8",
    )


@pytest.mark.competition
def test_lock_inventory_is_sorted_and_network_independent(tmp_path: Path) -> None:
    lock = tmp_path / "uv.lock"
    lock.write_text(
        """version = 1

[[package]]
name = "zeta-fixture"
version = "2.0.0"
source = { registry = "https://example.invalid/simple" }

[[package]]
name = "arc3"
version = "0.1.0"
source = { editable = "." }

[[package]]
name = "alpha-fixture"
version = "1.0.0"
source = { registry = "https://example.invalid/simple" }
""",
        encoding="utf-8",
    )
    _write_owner_approved_license(tmp_path)
    records = inventory_locked_dependencies(lock, include_installed_metadata=False)
    assert [record.name for record in records] == ["alpha-fixture", "arc3", "zeta-fixture"]
    assert records[1].license_status == "MIT-0"
    assert records[1].license_evidence == (
        "license-expression:MIT-0",
        f"license-sha256:{MIT0_LICENSE_SHA256}",
    )
    assert records[0].license_status == "NOT_QUERIED"


@pytest.mark.competition
def test_provably_inapplicable_platform_dependency_is_not_reported_missing(
    tmp_path: Path,
) -> None:
    lock = tmp_path / "uv.lock"
    lock.write_text(
        """version = 1

[[package]]
name = "arc3"
version = "0.1.0"
source = { editable = "." }
dependencies = [
    { name = "platform-only-fixture", marker = "sys_platform == 'not-a-real-platform'" },
]

[[package]]
name = "platform-only-fixture"
version = "1.0.0"
source = { registry = "https://example.invalid/simple" }
""",
        encoding="utf-8",
    )
    records = inventory_locked_dependencies(lock)
    fixture = next(record for record in records if record.name == "platform-only-fixture")
    assert fixture.installed_version is None
    assert fixture.license_status == "PLATFORM_EXCLUDED"


@pytest.mark.competition
def test_unknown_or_compound_platform_marker_cannot_excuse_missing_metadata(
    tmp_path: Path,
) -> None:
    lock = tmp_path / "uv.lock"
    lock.write_text(
        """version = 1

[[package]]
name = "arc3"
version = "0.1.0"
source = { editable = "." }
dependencies = [
    { name = "compound-fixture", marker = "sys_platform == 'never' or python_version > '0'" },
]

[[package]]
name = "compound-fixture"
version = "1.0.0"
source = { registry = "https://example.invalid/simple" }
""",
        encoding="utf-8",
    )
    records = inventory_locked_dependencies(lock)
    fixture = next(record for record in records if record.name == "compound-fixture")
    assert fixture.license_status == "MISSING_DISTRIBUTION"


@pytest.mark.competition
def test_installed_version_mismatch_is_explicit_supply_failure(
    integrity_repo: tuple[Path, str, str],
) -> None:
    root, _, _ = integrity_repo
    lock = root / "uv.lock"
    lock.write_text(
        lock.read_text(encoding="utf-8")
        .replace('name = "fixture-dependency-not-installed"', 'name = "pytest"')
        .replace('version = "1.2.3"', 'version = "0.0.0"'),
        encoding="utf-8",
    )
    receipt = build_integrity_receipt(root)
    assert not receipt.passed
    summary = receipt.body["license_summary"]
    assert isinstance(summary, dict)
    assert summary["installed_version_mismatch_count"] == 1
    assert any(
        finding["rule_id"] == "installed-version-mismatch"
        for finding in receipt.body["findings"]
        if isinstance(finding, dict)
    )


@pytest.mark.competition
def test_missing_distribution_license_is_explicit_supply_failure(
    integrity_repo: tuple[Path, str, str],
) -> None:
    root, _, _ = integrity_repo
    receipt = build_integrity_receipt(root)
    assert not receipt.passed
    summary = receipt.body["license_summary"]
    assert isinstance(summary, dict)
    assert summary["unknown_or_missing_metadata_count"] == 1
    assert any(
        finding["rule_id"] == "dependency-license-unresolved"
        for finding in receipt.body["findings"]
        if isinstance(finding, dict)
    )
