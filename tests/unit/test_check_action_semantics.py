"""Focused tests for the Stage 05 production action-semantics scan."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.check_action_semantics import (
    build_action_semantics_receipt,
    discover_action_semantic_files,
    scan_action_semantics,
)


def _fixture(tmp_path: Path, relative: str, source: str) -> tuple[Path, Path]:
    root = tmp_path / "repo"
    target = root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(source, encoding="utf-8")
    manifest = root / "docs/evaluation/public-game-partitions.v0.1.json"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(
        json.dumps(
            {
                "schema": "fixture",
                "games": [{"game_id": "fixture-deadbeef", "stable_name": "fixture-game"}],
            }
        ),
        encoding="utf-8",
    )
    return target, manifest


def _rules(tmp_path: Path, source: str) -> set[str]:
    target, manifest = _fixture(tmp_path, "src/arc3/policy/candidate.py", source)
    return {
        finding.rule_id
        for finding in scan_action_semantics(target.parents[3], files=(target,), manifest=manifest)
    }


def test_rejects_both_orientations_of_fixed_cardinal_tables(tmp_path: Path) -> None:
    rules = _rules(
        tmp_path,
        """from arc3.types import ActionName
RAW_TO_EFFECT = {ActionName.ACTION1: (0, -1)}
EFFECT_TO_RAW = {(1, 0): ActionName.ACTION4}
""",
    )
    assert "raw-action-to-cardinal-vector" in rules
    assert "cardinal-vector-to-raw-action" in rules


def test_rejects_name_based_direction_undo_and_coordinate_meaning(tmp_path: Path) -> None:
    rules = _rules(
        tmp_path,
        """from arc3.types import ActionName
UP_ACTION = ActionName.ACTION2
if action.name is ActionName.ACTION7 and undo_supported:
    restore_previous()
SELECT_TARGET_ACTION = ActionName.ACTION6
""",
    )
    assert "raw-action-direction-label" in rules
    assert "action7-name-based-undo" in rules
    assert "action6-name-based-interaction" in rules


def test_compound_body_words_do_not_contaminate_wire_arity_checks(tmp_path: Path) -> None:
    rules = _rules(
        tmp_path,
        """from arc3.types import ActionName
if ActionName.ACTION6 in observation.available_actions:
    target = infer_target_from_observation(observation)
""",
    )
    assert "action6-name-based-interaction" not in rules


def test_rejects_game_identity_and_solution_table(tmp_path: Path) -> None:
    rules = _rules(
        tmp_path,
        """KNOWN_GAME_ACTIONS = {'fixture-deadbeef': ['ACTION1', 'ACTION2']}
TARGET = 'other-cafebabe'
""",
    )
    assert "public-game-action-table" in rules
    assert "game-specific-action-table" in rules
    assert "game-identifier-in-production-policy" in rules


def test_allows_wire_arity_lifecycle_and_receipt_learned_bindings(tmp_path: Path) -> None:
    target, manifest = _fixture(
        tmp_path,
        "src/arc3/policy/candidate.py",
        """from arc3.types import ActionName, ActionRequest, Coordinate
def resolve(effect, registry):
    return registry.resolve(effect)
def wire(name):
    coordinate = Coordinate(3, 3) if name is ActionName.ACTION6 else None
    return ActionRequest(name, coordinate)
def lifecycle(state):
    return ActionRequest(ActionName.RESET) if state == 'GAME_OVER' else None
""",
    )
    assert scan_action_semantics(target.parents[3], files=(target,), manifest=manifest) == ()


def test_evaluator_fixture_allowlist_is_narrow_and_receipt_is_sealed(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    production = root / "src/arc3/policy/clean.py"
    evaluator = root / "src/arc3/world_model/benchmark.py"
    production.parent.mkdir(parents=True, exist_ok=True)
    evaluator.parent.mkdir(parents=True, exist_ok=True)
    production.write_text("VALUE = 1\n", encoding="utf-8")
    evaluator.write_text("MAP = {'ACTION1': (0, -1)}\n", encoding="utf-8")
    manifest = root / "docs/evaluation/public-game-partitions.v0.1.json"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text('{"schema":"fixture","games":[]}', encoding="utf-8")

    discovered = discover_action_semantic_files(root)
    assert production in discovered
    assert evaluator not in discovered
    receipt = build_action_semantics_receipt(root, manifest=manifest)
    assert receipt["passed"] is True
    assert receipt["finding_count"] == 0
    assert isinstance(receipt["receipt_hash"], str)


def test_discovery_includes_the_production_mechanics_learner_tree(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    learner = root / "src/arc3/mechanics/learner.py"
    policy = root / "src/arc3/policy/controller.py"
    learner.parent.mkdir(parents=True, exist_ok=True)
    policy.parent.mkdir(parents=True, exist_ok=True)
    learner.write_text("class MechanicalLearner:\n    pass\n", encoding="utf-8")
    policy.write_text("VALUE = 1\n", encoding="utf-8")

    discovered = discover_action_semantic_files(root)

    assert learner in discovered
    assert policy in discovered
