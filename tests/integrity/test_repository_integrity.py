"""Run the competition-integrity gate against the current candidate tree."""

from __future__ import annotations

from pathlib import Path

import pytest

from arc3.integrity import build_integrity_receipt


@pytest.mark.competition
def test_current_repository_has_no_blocking_static_integrity_finding() -> None:
    root = Path(__file__).resolve().parents[2]
    receipt = build_integrity_receipt(root)
    assert receipt.passed, receipt.body["findings"]
    assert receipt.body["assurance_scope"] == {
        "kind": "static-only",
        "runtime_socket_denial": "OUT_OF_SCOPE",
        "scanner_network_mode": "offline-by-construction",
    }
    inputs = receipt.body["inputs"]
    assert isinstance(inputs, dict)
    assert inputs["public_identifier_count"] > 0
    source_hashes = receipt.body["source_hashes"]
    assert isinstance(source_hashes, dict)
    assert "docs/evaluation/public-game-partitions.v0.1.json" in source_hashes
