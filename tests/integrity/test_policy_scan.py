"""Negative and clean-fixture tests for production-policy static checks."""

from __future__ import annotations

from pathlib import Path

import pytest

from arc3.integrity import (
    FindingCategory,
    discover_policy_files,
    load_public_identifiers,
    scan_policy_files,
)


def _scan(root: Path, fake_source: str) -> tuple[object, ...]:
    source = root / "policy" / "candidate.py"
    source.write_text(fake_source, encoding="utf-8")
    public = load_public_identifiers(
        root / "docs" / "evaluation" / "public-game-partitions.v0.1.json"
    )
    return scan_policy_files(root=root, files=(source,), public_identifiers=public.identifiers)


@pytest.mark.competition
def test_public_game_identifiers_are_manifest_driven_and_blocked(
    integrity_repo: tuple[Path, str, str],
) -> None:
    root, fake_game_id, fake_stable_name = integrity_repo
    findings = _scan(
        root,
        f"TARGET_GAME = {fake_game_id!r}\nALIAS = {fake_stable_name!r}\n",
    )
    public_findings = [
        finding
        for finding in findings
        if finding.category is FindingCategory.PUBLIC_GAME_IDENTIFIER
    ]
    assert len(public_findings) == 2
    assert all(fake_game_id not in finding.message for finding in findings)


@pytest.mark.competition
@pytest.mark.parametrize("module", ["requests", "openai", "urllib.request"])
def test_forbidden_network_or_hosted_import_is_blocked(
    integrity_repo: tuple[Path, str, str], module: str
) -> None:
    root, _, _ = integrity_repo
    findings = _scan(root, "import " + module + "\n")
    assert FindingCategory.FORBIDDEN_NETWORK_CLIENT in {finding.category for finding in findings}


@pytest.mark.competition
@pytest.mark.parametrize(
    ("module", "member"),
    [("google", "genai"), ("urllib", "request"), ("arc3.adapters", "arc_agi")],
)
def test_forbidden_from_import_is_blocked(
    integrity_repo: tuple[Path, str, str], module: str, member: str
) -> None:
    root, _, _ = integrity_repo
    findings = _scan(root, f"from {module} import {member}\n")
    assert any(finding.rule_id == "forbidden-from-import" for finding in findings)


@pytest.mark.competition
def test_pure_normalization_boundary_import_is_allowed(
    integrity_repo: tuple[Path, str, str],
) -> None:
    root, _, _ = integrity_repo
    findings = _scan(root, "from arc3.adapters.arc_agi import normalize_frame_data\n")
    assert not any(
        finding.category is FindingCategory.FORBIDDEN_NETWORK_CLIENT for finding in findings
    )


@pytest.mark.competition
def test_forbidden_dynamic_import_is_blocked(integrity_repo: tuple[Path, str, str]) -> None:
    root, _, _ = integrity_repo
    module = "anth" + "ropic"
    findings = _scan(
        root, "from importlib import import_module\nCLIENT = import_module(" + repr(module) + ")\n"
    )
    assert any(finding.rule_id == "forbidden-dynamic-import" for finding in findings)


@pytest.mark.competition
@pytest.mark.parametrize(
    "source",
    [
        "import subprocess as sp\nsp.run(['local-helper'])\n",
        "from subprocess import run as launch\nlaunch(['local-helper'])\n",
        "import os\nos.system('local-helper')\n",
        "import asyncio\nasyncio.open_connection('localhost', 1)\n",
    ],
)
def test_alias_aware_network_capable_calls_are_blocked(
    integrity_repo: tuple[Path, str, str], source: str
) -> None:
    root, _, _ = integrity_repo
    findings = _scan(root, source)
    assert any(finding.rule_id == "network-capable-call" for finding in findings)


@pytest.mark.competition
def test_reachable_excluded_first_party_wrapper_is_scanned(
    integrity_repo: tuple[Path, str, str],
) -> None:
    root, _, _ = integrity_repo
    entry = root / "agent" / "my_agent.py"
    package = root / "src" / "arc3" / "__init__.py"
    wrapper = root / "src" / "arc3" / "evaluation" / "wrapper.py"
    wrapper.parent.mkdir(parents=True)
    package.parent.mkdir(parents=True, exist_ok=True)
    entry.write_text("from arc3.evaluation import wrapper\n", encoding="utf-8")
    package.write_text("", encoding="utf-8")
    wrapper.write_text("import requests\n", encoding="utf-8")
    candidates = (entry, package, wrapper)
    policy_files = discover_policy_files(root, candidate_files=candidates)
    assert wrapper in policy_files
    public = load_public_identifiers(
        root / "docs" / "evaluation" / "public-game-partitions.v0.1.json"
    )
    findings = scan_policy_files(
        root=root,
        files=policy_files,
        public_identifiers=public.identifiers,
    )
    assert any(
        finding.path.endswith("evaluation/wrapper.py")
        and finding.category is FindingCategory.FORBIDDEN_NETWORK_CLIENT
        for finding in findings
    )


@pytest.mark.competition
def test_obvious_game_solution_table_is_blocked(integrity_repo: tuple[Path, str, str]) -> None:
    root, _, _ = integrity_repo
    target = "KNOWN_GAME_" + "PLANS"
    source = target + " = {'fixture': ['ACTION1', 'ACTION2']}\n"
    findings = _scan(root, source)
    assert any(finding.rule_id == "scripted-action-table" for finding in findings)


@pytest.mark.competition
def test_shipped_policy_data_asset_is_scanned(integrity_repo: tuple[Path, str, str]) -> None:
    root, fake_game_id, _ = integrity_repo
    asset = root / "agent" / "known_actions.json"
    asset.write_text(
        '{"target": ' + repr(fake_game_id) + ', "actions": ["ACTION1", "ACTION2"]}',
        encoding="utf-8",
    )
    public = load_public_identifiers(
        root / "docs" / "evaluation" / "public-game-partitions.v0.1.json"
    )
    policy_files = discover_policy_files(root)
    assert asset in policy_files
    findings = scan_policy_files(
        root=root,
        files=policy_files,
        public_identifiers=public.identifiers,
    )
    assert any(
        finding.path == "agent/known_actions.json"
        and finding.category is FindingCategory.PUBLIC_GAME_IDENTIFIER
        for finding in findings
    )


@pytest.mark.competition
def test_generic_action_semantics_are_not_treated_as_solution_table(
    integrity_repo: tuple[Path, str, str],
) -> None:
    root, _, _ = integrity_repo
    findings = _scan(
        root,
        """from enum import StrEnum

class Action(StrEnum):
    ACTION1 = "ACTION1"
    ACTION2 = "ACTION2"

DIRECTION_PRIORS = {Action.ACTION1: (0, -1), Action.ACTION2: (0, 1)}
""",
    )
    assert findings == ()


@pytest.mark.competition
def test_unparseable_policy_source_blocks_assurance(integrity_repo: tuple[Path, str, str]) -> None:
    root, _, _ = integrity_repo
    findings = _scan(root, "def broken(:\n")
    assert any(finding.category is FindingCategory.UNPARSEABLE_SOURCE for finding in findings)
