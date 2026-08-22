"""Synthetic repository fixtures for integrity tests."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest


@pytest.fixture
def integrity_repo(tmp_path: Path) -> tuple[Path, str, str]:
    """Create a minimal repository with a fake public manifest and lock."""

    root = tmp_path / "repository"
    policy = root / "policy"
    manifest = root / "docs" / "evaluation" / "public-game-partitions.v0.1.json"
    policy.mkdir(parents=True)
    manifest.parent.mkdir(parents=True)
    fake_stable_name = "fixture" + "42"
    fake_game_id = fake_stable_name + "-" + "dead" + "beef"
    manifest_raw = json.dumps(
        {
            "schema": "fixture.public-partitions.v1",
            "games": [{"game_id": fake_game_id, "stable_name": fake_stable_name}],
        },
        sort_keys=True,
    ).encode("utf-8")
    manifest.write_bytes(manifest_raw)
    manifest_sha256 = "sha256:" + hashlib.sha256(manifest_raw).hexdigest()
    run_state = root / "docs" / "ledger" / "run-state.json"
    run_state.parent.mkdir(parents=True)
    run_state.write_text(
        json.dumps(
            {
                "evidence": {
                    "stage_02": {
                        "public_partition_manifest": (
                            "docs/evaluation/public-game-partitions.v0.1.json"
                        ),
                        "public_partition_manifest_sha256": manifest_sha256,
                    }
                }
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    (root / "uv.lock").write_text(
        """version = 1

[[package]]
name = "arc3"
version = "0.1.0"
source = { editable = "." }

[[package]]
name = "fixture-dependency-not-installed"
version = "1.2.3"
source = { registry = "https://example.invalid/simple" }
""",
        encoding="utf-8",
    )
    (root / "pyproject.toml").write_text(
        '[project]\nname="arc3"\nlicense="MIT-0"\nlicense-files=["LICENSE"]\n',
        encoding="utf-8",
    )
    (root / "upstream.lock.json").write_text("{}\n", encoding="utf-8")
    project_root = Path(__file__).resolve().parents[2]
    (root / "LICENSE").write_bytes((project_root / "LICENSE").read_bytes())
    (root / "THIRD_PARTY_NOTICES.md").write_text("fixture\n", encoding="utf-8")
    entry = root / "agent" / "my_agent.py"
    entry.parent.mkdir()
    entry.write_text("class MyAgent:\n    pass\n", encoding="utf-8")
    return root, fake_game_id, fake_stable_name
