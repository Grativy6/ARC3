from __future__ import annotations

import json
import runpy
import subprocess
import sys
from pathlib import Path

import pytest
from arcengine import FrameData, GameAction, GameState

from arc3.adapters.synthetic import SYNTHETIC_GAME_ID, SyntheticAdapter
from arc3.competition_runtime import FROZEN_COMPETITION_RUNTIME
from arc3.config import ARC3Config, BudgetConfig
from arc3.policy import ARC3Controller, ControllerPhase, ControllerPreset, LocalProposal, RunContext
from arc3.types import EnvironmentMode

ROOT = Path(__file__).resolve().parents[2]
MyAgent = runpy.run_path(str(ROOT / "agent" / "my_agent.py"))["MyAgent"]
PRODUCTION_PATHS = (ROOT / "src" / "arc3" / "policy", ROOT / "agent" / "my_agent.py")


@pytest.mark.competition
def test_production_policy_has_no_public_ids_or_forbidden_network_clients() -> None:
    manifest = json.loads(
        (ROOT / "docs" / "evaluation" / "public-game-partitions.v0.1.json").read_text(
            encoding="utf-8"
        )
    )
    known_ids = {item["game_id"].lower() for item in manifest["games"]}
    sources = "\n".join(
        path.read_text(encoding="utf-8").lower()
        for root in PRODUCTION_PATHS
        for path in ([root] if root.is_file() else sorted(root.glob("*.py")))
    )
    assert not any(game_id in sources for game_id in known_ids)
    assert not any(
        token in sources
        for token in (
            "import requests",
            "import httpx",
            "import socket",
            "urllib.request",
            "openai",
            "anthropic",
        )
    )


@pytest.mark.competition
def test_local_proposal_value_has_no_environment_action_authority() -> None:
    assert "action" not in LocalProposal.__dataclass_fields__


@pytest.mark.competition
def test_competition_preset_completes_synthetic_with_network_disabled(tmp_path: Path) -> None:
    session = SyntheticAdapter(seed=7, size=8, max_steps=32).open(SYNTHETIC_GAME_ID)
    config = ARC3Config(
        mode=EnvironmentMode.COMPETITION,
        seed=7,
        network_enabled=False,
        profile="competition",
        budgets=BudgetConfig(max_actions=16),
    )
    controller = ARC3Controller(ControllerPreset.COMPETITION)
    controller.reset(
        RunContext(
            "competition-offline",
            "competition-offline-episode",
            SYNTHETIC_GAME_ID,
            tmp_path / "trace",
            tmp_path / "checkpoint",
            config,
            "competition-offline",
        )
    )
    controller.observe(session.observation)
    for _step in range(16):
        decision = controller.choose_action()
        controller.apply_consequence(session.step(decision.action))
        if controller.phase is ControllerPhase.COMPLETE:
            break
    assert controller.phase is ControllerPhase.COMPLETE


@pytest.mark.competition
def test_pinned_frame_data_default_action_is_stripped_only_by_official_wrapper() -> None:
    agent = MyAgent(game_id="opaque-wrapper-fixture", seed=31)
    first_frame = FrameData(
        game_id="opaque-wrapper-fixture",
        frame=[[[0, 1, 0], [0, 0, 2], [0, 0, 0]]],
        state=GameState.NOT_FINISHED,
        levels_completed=0,
        win_levels=2,
        available_actions=[1, 2, 3, 4],
    )
    assert first_frame.action_input.id is GameAction.RESET

    first_action = agent.choose_action([], first_frame)
    assert first_action is not GameAction.RESET
    second_frame = FrameData(
        game_id="opaque-wrapper-fixture",
        frame=[[[0, 1, 0], [0, 0, 2], [0, 0, 0]]],
        state=GameState.NOT_FINISHED,
        levels_completed=0,
        win_levels=2,
        available_actions=[1, 2, 3, 4],
    )
    second_action = agent.choose_action([first_frame], second_frame)
    assert second_action is not GameAction.RESET
    assert agent._controller is not None
    assert agent._controller.snapshot.actions_used == 1
    assert agent._controller.snapshot.fault_count == 0
    assert agent._controller.context.config.budgets == FROZEN_COMPETITION_RUNTIME.budgets()
    assert MyAgent.MAX_ACTIONS == FROZEN_COMPETITION_RUNTIME.max_actions == 80
    agent._controller.close()


@pytest.mark.competition
def test_fresh_process_full_controller_reset_observe_choose_smoke() -> None:
    source = """
from pathlib import Path
from tempfile import TemporaryDirectory
from arc3.adapters.synthetic import SYNTHETIC_GAME_ID, SyntheticAdapter
from arc3.config import ARC3Config, BudgetConfig
from arc3.policy import ARC3Controller, ControllerPreset, RunContext
from arc3.types import EnvironmentMode
with TemporaryDirectory(prefix='arc3-fresh-controller-') as raw:
    root = Path(raw)
    session = SyntheticAdapter(seed=11, size=8, max_steps=32).open(SYNTHETIC_GAME_ID)
    config = ARC3Config(mode=EnvironmentMode.SYNTHETIC, seed=11, budgets=BudgetConfig(max_actions=2))
    controller = ARC3Controller(ControllerPreset.FULL)
    controller.reset(RunContext('fresh-run', 'fresh-episode', SYNTHETIC_GAME_ID, root / 'trace', root / 'checkpoint', config, 'fresh-process'))
    controller.observe(session.observation)
    decision = controller.choose_action()
    assert decision.action.name.value.startswith('ACTION')
    controller.close()
"""
    completed = subprocess.run(
        (sys.executable, "-c", source),
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert completed.returncode == 0, completed.stderr
