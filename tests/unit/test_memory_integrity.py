from __future__ import annotations

import json
from pathlib import Path


def test_memory_production_code_contains_no_public_environment_identifiers() -> None:
    repository_root = Path(__file__).resolve().parents[2]
    manifest = json.loads(
        (repository_root / "docs/evaluation/public-game-partitions.v0.1.json").read_text(
            encoding="utf-8"
        )
    )
    public_identifiers = {
        value for game in manifest["games"] for value in (game["game_id"], game["stable_name"])
    }
    production_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted((repository_root / "src/arc3/memory").glob("*.py"))
    ).lower()
    leaked = sorted(
        identifier for identifier in public_identifiers if identifier.lower() in production_text
    )
    assert leaked == []


def test_memory_production_api_has_no_task_identifier_solution_lookup() -> None:
    repository_root = Path(__file__).resolve().parents[2]
    production_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted((repository_root / "src/arc3/memory").glob("*.py"))
    )
    forbidden_api_fragments = (
        "get_solution_by_" + "game_id",
        "lookup_solution_by_" + "game_id",
        "solutions_by_" + "game_id",
    )
    assert not any(fragment in production_text for fragment in forbidden_api_fragments)
