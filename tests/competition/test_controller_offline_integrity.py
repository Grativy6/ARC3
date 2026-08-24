from __future__ import annotations

import json
import os
import runpy
import subprocess
import sys
import time
from pathlib import Path

import pytest
from arcengine import FrameData, GameAction, GameState

from arc3.adapters.synthetic import SYNTHETIC_GAME_ID, SyntheticAdapter
from arc3.competition_runtime import FROZEN_COMPETITION_RUNTIME
from arc3.config import ARC3Config, BudgetConfig, RuntimePolicyConfig
from arc3.policy import ARC3Controller, ControllerPhase, ControllerPreset, LocalProposal, RunContext
from arc3.types import ActionName, ActionRequest, EnvironmentMode, ExecutionMode

ROOT = Path(__file__).resolve().parents[2]
WRAPPER = runpy.run_path(str(ROOT / "agent" / "my_agent.py"))
MyAgent = WRAPPER["MyAgent"]
BOUNDED_CALL = WRAPPER["_bounded_call"]
PRODUCTION_PATHS = (ROOT / "src" / "arc3" / "policy", ROOT / "agent" / "my_agent.py")


class _FakeClock:
    def __init__(self) -> None:
        self.value = 0.0

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


@pytest.mark.competition
@pytest.mark.skipif(os.name != "posix", reason="SIGALRM is a Linux runtime boundary")
def test_linux_blocking_call_is_interrupted_at_local_deadline() -> None:
    with pytest.raises(TimeoutError, match="test-boundary exceeded"):
        BOUNDED_CALL(lambda: time.sleep(0.1), seconds=0.01, boundary="test-boundary")


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
        execution_mode=ExecutionMode.COMPETITION_BOUNDED,
        seed=7,
        network_enabled=False,
        profile="competition",
        budgets=BudgetConfig(max_actions=16),
        runtime_policy=RuntimePolicyConfig.competition_bounded(),
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
def test_pinned_frame_data_default_action_is_stripped_only_by_official_wrapper(
    tmp_path: Path,
) -> None:
    MyAgent.configure_tournament(("opaque-wrapper-fixture",), tmp_path / "agent-runtime")
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
    agent.cleanup()
    MyAgent.finalize_tournament()


@pytest.mark.competition
def test_competition_wrapper_stops_after_an_unexpected_game_reset(tmp_path: Path) -> None:
    game_id = "full-reset-lifecycle-fixture"
    MyAgent.configure_tournament((game_id,), tmp_path / "full-reset-runtime")
    agent = MyAgent(game_id=game_id, seed=37)

    def frame(*, full_reset: bool = False) -> FrameData:
        return FrameData(
            game_id=game_id,
            frame=[[[0, 1, 0], [0, 0, 2], [0, 0, 0]]],
            state=GameState.NOT_FINISHED,
            levels_completed=0,
            win_levels=2,
            available_actions=[1, 2, 3, 4],
            full_reset=full_reset,
        )

    agent.choose_action([], frame())
    agent.choose_action([], frame())
    with pytest.raises(RuntimeError, match="unexpected full game reset"):
        agent.choose_action([], frame(full_reset=True))

    assert agent.is_done([], frame()) is True
    failures = MyAgent.failure_receipts()
    assert failures[-1]["classification"] == "platform"
    assert failures[-1]["boundary"] == "reset-lifecycle"
    receipt = MyAgent.finalize_tournament()
    assert receipt["finalized_environments"] == 1


@pytest.mark.competition
def test_competition_wrapper_emits_budget_receipt_when_decision_expires(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    game_id = "decision-deadline-fixture"
    clock = _FakeClock()
    MyAgent.configure_tournament((game_id,), tmp_path / "deadline-runtime", clock=clock)
    agent = MyAgent(game_id=game_id, seed=41)
    frame = FrameData(
        game_id=game_id,
        frame=[[[0, 1, 0], [0, 0, 2], [0, 0, 0]]],
        state=GameState.NOT_FINISHED,
        levels_completed=0,
        win_levels=2,
        available_actions=[1, 2, 3, 4],
    )

    def expire_during_decision(_observation: object) -> tuple[ActionRequest, float]:
        clock.advance(FROZEN_COMPETITION_RUNTIME.per_game_wall_clock_seconds)
        return ActionRequest(ActionName.ACTION1), 1.0

    monkeypatch.setattr(agent, "_controller_request", expire_during_decision)
    with pytest.raises(RuntimeError, match="game-time-limit"):
        agent.choose_action([], frame)

    assert agent.is_done([], frame) is True
    failures = MyAgent.failure_receipts()
    assert failures[-1]["boundary"] == "governor-stop-before-action"
    assert failures[-1]["classification"] == "budget exhaustion"
    receipt = MyAgent.finalize_tournament()
    assert receipt["total_actions_authorized"] == 0
    assert receipt["finalized_environments"] == 1


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
