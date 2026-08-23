"""Fail-closed identity checks for ARC3's owner-approved first-party license."""

from __future__ import annotations

import hashlib
import tomllib
from pathlib import Path

MIT0_EXPRESSION = "MIT-0"
MIT0_LICENSE_SHA256 = "7f433e520d07d56ad14d92e9da9f580771479c30a2bfccc8024eed308f21bbe8"


def first_party_license_identity_bytes(
    license_bytes: bytes,
    pyproject_bytes: bytes,
) -> tuple[str, tuple[str, ...]]:
    """Return MIT-0 identity from one immutable source snapshot pair."""

    digest = hashlib.sha256(license_bytes).hexdigest()
    evidence = (f"license-expression:{MIT0_EXPRESSION}", f"license-sha256:{digest}")
    if digest != MIT0_LICENSE_SHA256:
        return "LICENSE_HASH_MISMATCH", evidence
    try:
        document = tomllib.loads(pyproject_bytes.decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError):
        return "LICENSE_METADATA_UNREADABLE", evidence
    project = document.get("project")
    if (
        not isinstance(project, dict)
        or project.get("license") != MIT0_EXPRESSION
        or project.get("license-files") != ["LICENSE"]
    ):
        return "LICENSE_METADATA_MISMATCH", evidence
    return MIT0_EXPRESSION, evidence


def first_party_license_identity(repository: Path) -> tuple[str, tuple[str, ...]]:
    """Return a bounded status and evidence for the exact operative MIT-0 grant."""

    license_path = repository / "LICENSE"
    pyproject_path = repository / "pyproject.toml"
    if not license_path.is_file() or license_path.is_symlink():
        return "MISSING_LICENSE", ()
    try:
        return first_party_license_identity_bytes(
            license_path.read_bytes(),
            pyproject_path.read_bytes(),
        )
    except OSError:
        return "LICENSE_METADATA_UNREADABLE", ()


__all__ = [
    "MIT0_EXPRESSION",
    "MIT0_LICENSE_SHA256",
    "first_party_license_identity",
    "first_party_license_identity_bytes",
]
