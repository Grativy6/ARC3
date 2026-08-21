"""Reproducibility check for the complete Stage 17 candidate."""

from __future__ import annotations

from pathlib import Path

import pytest

from arc3.packaging.builder import build_kaggle_candidate

REPOSITORY = Path(__file__).resolve().parents[2]


@pytest.mark.integration
def test_stage17_package_build_is_byte_deterministic(tmp_path: Path) -> None:
    first = build_kaggle_candidate(REPOSITORY, tmp_path / "first", allow_dirty_preacceptance=True)
    second = build_kaggle_candidate(REPOSITORY, tmp_path / "second", allow_dirty_preacceptance=True)

    assert first.candidate_sha256 == second.candidate_sha256
    assert first.notebook_sha256 == second.notebook_sha256
    assert first.payload_sha256 == second.payload_sha256
    assert first.manifest_sha256 == second.manifest_sha256
    assert first.sbom_sha256 == second.sbom_sha256
    assert first.runtime_requirements_sha256 == second.runtime_requirements_sha256
    assert first.wheel_manifest_sha256 == second.wheel_manifest_sha256
    assert first.candidate_archive.read_bytes() == second.candidate_archive.read_bytes()
    assert first.sandbox_submission.read_bytes() == second.sandbox_submission.read_bytes()
