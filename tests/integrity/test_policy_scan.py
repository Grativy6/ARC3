"""Negative and clean-fixture tests for production-policy static checks."""

from __future__ import annotations

from pathlib import Path

import pytest

from arc3.integrity import (
    FindingCategory,
    discover_candidate_files,
    discover_policy_files,
    discover_reachable_policy_files,
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
def test_game_id_shape_is_blocked_without_semantic_public_identifiers(
    integrity_repo: tuple[Path, str, str],
) -> None:
    root, _, _ = integrity_repo
    source = root / "policy" / "candidate.py"
    source.write_text("TARGET = 'generic42-deadbeef'\n", encoding="utf-8")

    findings = scan_policy_files(root=root, files=(source,), public_identifiers=())

    assert any(finding.rule_id == "game-id-shaped-literal" for finding in findings)


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
def test_runtime_launcher_allows_only_competition_local_gateway_import_members(
    integrity_repo: tuple[Path, str, str],
) -> None:
    root, _, _ = integrity_repo
    launcher = root / "src" / "arc3" / "packaging" / "runtime_launcher.py"
    launcher.parent.mkdir(parents=True)
    launcher.write_text(
        "from urllib.request import ProxyHandler, Request, build_opener\n",
        encoding="utf-8",
    )

    findings = scan_policy_files(root=root, files=(launcher,), public_identifiers=())

    assert not any(
        finding.category is FindingCategory.FORBIDDEN_NETWORK_CLIENT for finding in findings
    )


@pytest.mark.competition
@pytest.mark.parametrize(
    ("relative_path", "source"),
    [
        (
            "src/arc3/packaging/runtime_launcher.py",
            "from urllib.request import ProxyHandler, Request, build_opener, urlopen\n",
        ),
        ("src/arc3/packaging/runtime_launcher.py", "import urllib.request\n"),
        (
            "policy/candidate.py",
            "from urllib.request import ProxyHandler, Request, build_opener\n",
        ),
    ],
)
def test_runtime_launcher_gateway_import_exception_is_exact_and_path_scoped(
    integrity_repo: tuple[Path, str, str], relative_path: str, source: str
) -> None:
    root, _, _ = integrity_repo
    candidate = root / relative_path
    candidate.parent.mkdir(parents=True, exist_ok=True)
    candidate.write_text(source, encoding="utf-8")

    findings = scan_policy_files(root=root, files=(candidate,), public_identifiers=())

    assert any(finding.category is FindingCategory.FORBIDDEN_NETWORK_CLIENT for finding in findings)


@pytest.mark.competition
def test_environment_adapter_normalization_import_is_not_exempt(
    integrity_repo: tuple[Path, str, str],
) -> None:
    root, _, _ = integrity_repo
    findings = _scan(root, "from arc3.adapters.normalization import normalize_frame_data\n")
    assert not any(
        finding.category is FindingCategory.FORBIDDEN_NETWORK_CLIENT for finding in findings
    )


@pytest.mark.competition
def test_environment_adapter_normalization_import_is_no_longer_exempt(
    integrity_repo: tuple[Path, str, str],
) -> None:
    root, _, _ = integrity_repo
    findings = _scan(root, "from arc3.adapters.arc_agi import normalize_frame_data\n")

    assert any(finding.rule_id == "forbidden-from-import" for finding in findings)


@pytest.mark.competition
def test_production_entry_reaches_pure_boundary_not_environment_adapter() -> None:
    root = Path(__file__).resolve().parents[2]
    reachable = discover_reachable_policy_files(
        root,
        candidate_files=discover_candidate_files(root),
    )
    labels = {path.relative_to(root).as_posix() for path in reachable}

    assert "agent/my_agent.py" in labels
    assert "src/arc3/adapters/normalization.py" in labels
    assert "src/arc3/mechanics/visual_causal.py" in labels
    assert "src/arc3/mechanics/learner.py" in labels
    assert "src/arc3/mechanics/ledger.py" in labels
    assert "src/arc3/exploration/causal_events.py" in labels
    assert "src/arc3/adapters/arc_agi.py" not in labels
    findings = scan_policy_files(root=root, files=reachable, public_identifiers=())
    assert not any(
        finding.path == "src/arc3/adapters/arc_agi.py"
        or finding.rule_id == "forbidden-dynamic-import"
        for finding in findings
    )


@pytest.mark.competition
def test_from_import_cannot_hide_malicious_module_top_level_code(
    integrity_repo: tuple[Path, str, str],
) -> None:
    root, _, _ = integrity_repo
    entry = root / "agent" / "my_agent.py"
    package = root / "src" / "arc3" / "__init__.py"
    adapters = root / "src" / "arc3" / "adapters" / "__init__.py"
    boundary = root / "src" / "arc3" / "adapters" / "arc_agi.py"
    boundary.parent.mkdir(parents=True, exist_ok=True)
    entry.write_text("from arc3.adapters.arc_agi import normalize_frame_data\n", encoding="utf-8")
    package.write_text("", encoding="utf-8")
    adapters.write_text("", encoding="utf-8")
    boundary.write_text("import openai\ndef normalize_frame_data(): ...\n", encoding="utf-8")

    candidates = (entry, package, adapters, boundary)
    policy_files = discover_policy_files(root, candidate_files=candidates)

    assert boundary in policy_files
    findings = scan_policy_files(root=root, files=policy_files, public_identifiers=())
    assert any(
        finding.path.endswith("arc3/adapters/arc_agi.py")
        and finding.category is FindingCategory.FORBIDDEN_NETWORK_CLIENT
        for finding in findings
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
def test_reachable_packaging_build_tool_is_scanned_despite_default_exclusion(
    integrity_repo: tuple[Path, str, str],
) -> None:
    root, _, _ = integrity_repo
    entry = root / "agent" / "my_agent.py"
    package = root / "src" / "arc3" / "__init__.py"
    packaging = root / "src" / "arc3" / "packaging" / "__init__.py"
    builder = root / "src" / "arc3" / "packaging" / "builder.py"
    builder.parent.mkdir(parents=True)
    package.parent.mkdir(parents=True, exist_ok=True)
    entry.write_text("from arc3.packaging import builder\n", encoding="utf-8")
    package.write_text("", encoding="utf-8")
    packaging.write_text("", encoding="utf-8")
    builder.write_text("import subprocess\nsubprocess.run(['local-helper'])\n", encoding="utf-8")
    candidates = (entry, package, packaging, builder)
    policy_files = discover_policy_files(root, candidate_files=candidates)
    assert builder in policy_files
    public = load_public_identifiers(
        root / "docs" / "evaluation" / "public-game-partitions.v0.1.json"
    )
    findings = scan_policy_files(
        root=root,
        files=policy_files,
        public_identifiers=public.identifiers,
    )
    assert any(
        finding.path.endswith("packaging/builder.py")
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
