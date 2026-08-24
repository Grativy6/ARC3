from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from arc3.packaging import runtime_launcher as launcher_module
from arc3.packaging.models import PackagingError
from arc3.packaging.runtime_launcher import (
    SAFE_FRAMEWORK_FIXTURE_IDENTITY,
    launch_competition_framework,
)


def _write_lifecycle_fixture(
    tmp_path: Path,
    *,
    behavior: str = "normal",
    worker_failure: bool = False,
    finalizer: str = "success",
) -> tuple[Path, Path, Path, Path]:
    framework = tmp_path / "framework"
    agents = framework / "agents"
    agents.mkdir(parents=True)
    (framework / ".arc3-safe-fixture").write_text(SAFE_FRAMEWORK_FIXTURE_IDENTITY, encoding="utf-8")
    (agents / "agent.py").write_text(
        "class Agent:\n"
        "    def __init__(self, *, game_id, agent_name, **kwargs):\n"
        "        self.game_id = game_id\n"
        "        self.agent_name = agent_name\n"
        "        self.kwargs = kwargs\n"
        "    def main(self):\n"
        "        return None\n\n"
        "class Playback(Agent):\n"
        "    pass\n",
        encoding="utf-8",
    )

    lifecycle_path = tmp_path / "lifecycle.json"
    finalizer_path = tmp_path / "finalizer.json"
    (agents / "swarm.py").write_text(
        "import json\n"
        "from pathlib import Path\n"
        "from threading import Thread\n\n"
        "class _CompetitionMode:\n"
        "    value = 'competition'\n\n"
        "class _Arcade:\n"
        "    operation_mode = _CompetitionMode()\n"
        "    def __init__(self):\n"
        "        self.events = []\n"
        "    def _record(self, event):\n"
        "        self.events.append(event)\n"
        f"        Path({str(lifecycle_path)!r}).write_text(\n"
        "            json.dumps(self.events), encoding='utf-8')\n"
        "    def open_scorecard(self, *args, **kwargs):\n"
        "        self._record(['open_scorecard'])\n"
        "        return 'fixture-scorecard'\n"
        "    def make(self, game_id, *args, **kwargs):\n"
        "        self._record(['make', game_id, kwargs.get('scorecard_id')])\n"
        "        return object()\n"
        "    def get_scorecard(self, *args, **kwargs):\n"
        "        self._record(['get_scorecard'])\n"
        "        return None\n"
        "    def close_scorecard(self, scorecard_id):\n"
        "        self._record(['close_scorecard', scorecard_id])\n"
        "        return None\n\n"
        "class Swarm:\n"
        "    def __init__(self, agent, root_url, games, tags=None):\n"
        "        from agents import AVAILABLE_AGENTS\n"
        "        self.agent_class = AVAILABLE_AGENTS[agent]\n"
        "        if self.agent_class.configuration_calls != 1:\n"
        "            raise RuntimeError('tournament was not configured exactly once')\n"
        "        if self.agent_class.configured_games != tuple(games):\n"
        "            raise RuntimeError('configured inventory differs from Swarm inventory')\n"
        "        self.GAMES = list(games)\n"
        "        self.agent_name = agent\n"
        "        self.tags = list(tags or [])\n"
        "        self.agents = []\n"
        "        self.threads = []\n"
        "        self._arc = _Arcade()\n"
        "    def open_scorecard(self):\n"
        "        return self._arc.open_scorecard(tags=self.tags)\n"
        "    def close_scorecard(self, card_id):\n"
        "        return self._arc.close_scorecard(card_id)\n"
        "    def main(self):\n"
        "        card_id = self.open_scorecard()\n"
        f"        behavior = {behavior!r}\n"
        "        if behavior == 'open_retry':\n"
        "            self.open_scorecard()\n"
        "        if behavior == 'get_during_flight':\n"
        "            self._arc.get_scorecard(card_id)\n"
        "        games = list(self.GAMES)\n"
        "        if behavior == 'make_retry':\n"
        "            games.insert(1, games[0])\n"
        "        elif behavior == 'missing_environment':\n"
        "            games = games[:-1]\n"
        "        elif behavior == 'changed_order':\n"
        "            games.reverse()\n"
        "        for game_id in games:\n"
        "            instance = self.agent_class(\n"
        "                card_id=card_id, game_id=game_id, agent_name=self.agent_name,\n"
        "                ROOT_URL='fixture', record=True,\n"
        "                arc_env=self._arc.make(game_id, scorecard_id=card_id), tags=[]\n"
        "            )\n"
        "            self.agents.append(instance)\n"
        "            self.threads.append(Thread(target=instance.main, daemon=True))\n"
        "        for thread in self.threads:\n"
        "            thread.start()\n"
        "        for thread in self.threads:\n"
        "            thread.join()\n"
        "        self.close_scorecard(card_id)\n"
        "        if behavior == 'close_retry':\n"
        "            self.close_scorecard(card_id)\n",
        encoding="utf-8",
    )

    agent = tmp_path / "my_agent.py"
    agent.write_text(
        "import os\n"
        "import time\n"
        "from pathlib import Path\n"
        "from agents.agent import Agent\n\n"
        "class MyAgent(Agent):\n"
        "    configuration_calls = 0\n"
        "    configured_games = ()\n"
        "    configured_root = ''\n"
        "    configured_notebook_start = None\n"
        "    @classmethod\n"
        "    def configure_tournament(\n"
        "        cls, games, working_root, *, notebook_started_at_seconds=None\n"
        "    ):\n"
        "        cls.configuration_calls += 1\n"
        "        cls.configured_games = tuple(games)\n"
        "        cls.configured_root = str(working_root)\n"
        "        cls.configured_notebook_start = notebook_started_at_seconds\n"
        "    def main(self):\n"
        f"        if {worker_failure!r} and self.game_id.endswith('b'):\n"
        "            raise RuntimeError('fixture worker failure')\n"
        "    @classmethod\n"
        "    def finalize_tournament(cls):\n"
        "        receipt = {\n"
        "            'configuration_calls': cls.configuration_calls,\n"
        "            'effective_ceiling_respected': True,\n"
        "            'expected_environments': len(cls.configured_games),\n"
        "            'finalized_environments': len(cls.configured_games),\n"
        "            'games': [{'game_id': game} for game in cls.configured_games],\n"
        "            'configured_games': list(cls.configured_games),\n"
        "            'maximum_total_actions': max(1, 80 * len(cls.configured_games)),\n"
        "            'operation_mode': os.environ.get('OPERATION_MODE'),\n"
        "            'outcome': 'complete-reserve-preserved',\n"
        "            'reserve_preserved': True,\n"
        "            'notebook_started_at_seconds': cls.configured_notebook_start,\n"
        "            'total_actions_authorized': 0,\n"
        "            'working_root': cls.configured_root,\n"
        "        }\n"
        f"        Path({str(finalizer_path)!r}).write_text(\n"
        "            __import__('json').dumps(receipt), encoding='utf-8')\n"
        f"        mode = {finalizer!r}\n"
        "        if mode == 'failure':\n"
        "            raise RuntimeError('fixture tournament finalization failure')\n"
        "        if mode == 'non_json':\n"
        "            return {'invalid': {1, 2}}\n"
        "        if mode == 'block':\n"
        "            time.sleep(0.25)\n"
        "        if mode == 'ceiling':\n"
        "            receipt['effective_ceiling_respected'] = False\n"
        "            receipt['outcome'] = 'complete-ceiling-exceeded'\n"
        "        if mode == 'reserve':\n"
        "            receipt['reserve_preserved'] = False\n"
        "            receipt['outcome'] = 'complete-reserve-consumed'\n"
        "        return receipt\n",
        encoding="utf-8",
    )
    return framework, agent, lifecycle_path, finalizer_path


@pytest.mark.competition
def test_launcher_enforces_and_receipts_exact_competition_lifecycle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    framework, agent, lifecycle_path, _ = _write_lifecycle_fixture(tmp_path)
    discovered = ("fixture-c", "fixture-a", "fixture-b")
    monkeypatch.setattr(launcher_module, "_discover_games", lambda host, port: discovered)
    working_root = tmp_path / "working"
    scorecard_open_intents: list[str] = []
    make_intents: list[tuple[str, int]] = []

    receipt = launch_competition_framework(
        framework,
        agent,
        working_root=working_root,
        allow_test_fixture=True,
        before_scorecard_open=lambda: scorecard_open_intents.append("open"),
        before_environment_make=lambda game_id, ordinal: make_intents.append((game_id, ordinal)),
    )

    frozen = tuple(sorted(discovered))
    assert receipt.discovered_environments == frozen
    assert receipt.lifecycle_enforced is True
    assert receipt.open_scorecard_count == 1
    assert receipt.close_scorecard_count == 1
    assert receipt.make_count == len(frozen)
    assert receipt.get_scorecard_during_flight_count == 0
    assert receipt.all_environments_covered is True
    assert receipt.tournament_configured is True
    assert receipt.tournament_finalized is True
    assert scorecard_open_intents == ["open"]
    assert make_intents == [(game_id, ordinal) for ordinal, game_id in enumerate(frozen)]
    assert isinstance(receipt.tournament_receipt, dict)
    assert receipt.tournament_receipt["status"] == "PASS"
    tournament = receipt.tournament_receipt["receipt"]
    assert isinstance(tournament, dict)
    assert tournament["configuration_calls"] == 1
    assert tournament["configured_games"] == list(frozen)
    assert tournament["games"] == [{"game_id": game} for game in frozen]
    assert tournament["operation_mode"] == "competition"
    assert tournament["working_root"] == str(working_root.resolve())
    assert tournament["reserve_preserved"] is True
    assert tournament["effective_ceiling_respected"] is True
    assert json.loads(lifecycle_path.read_text(encoding="utf-8")) == [
        ["open_scorecard"],
        *[["make", game, "fixture-scorecard"] for game in frozen],
        ["close_scorecard", "fixture-scorecard"],
    ]
    assert json.loads(json.dumps(receipt.to_dict(), allow_nan=False)) == receipt.to_dict()


@pytest.mark.competition
def test_launcher_anchors_tournament_to_validated_notebook_start(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    framework, agent, _, _ = _write_lifecycle_fixture(tmp_path)
    monkeypatch.setattr(launcher_module, "_discover_games", lambda host, port: ("fixture-a",))
    notebook_start = time.monotonic() - 1.0

    receipt = launch_competition_framework(
        framework,
        agent,
        working_root=tmp_path / "working",
        allow_test_fixture=True,
        notebook_started_at_seconds=notebook_start,
    )

    assert receipt.notebook_started_at_seconds == notebook_start
    tournament_wrapper = receipt.tournament_receipt
    assert isinstance(tournament_wrapper, dict)
    tournament = tournament_wrapper["receipt"]
    assert isinstance(tournament, dict)
    assert tournament["notebook_started_at_seconds"] == notebook_start


@pytest.mark.competition
@pytest.mark.parametrize("invalid_start", [float("nan"), float("inf"), -1.0, True])
def test_launcher_rejects_invalid_notebook_start_before_framework_execution(
    tmp_path: Path, invalid_start: float
) -> None:
    framework, agent, lifecycle_path, _ = _write_lifecycle_fixture(tmp_path)

    with pytest.raises(PackagingError, match="finite monotonic time"):
        launch_competition_framework(
            framework,
            agent,
            working_root=tmp_path / "working",
            allow_test_fixture=True,
            notebook_started_at_seconds=invalid_start,
        )

    assert not lifecycle_path.exists()


@pytest.mark.competition
def test_launcher_rejects_future_notebook_start_before_framework_execution(
    tmp_path: Path,
) -> None:
    framework, agent, lifecycle_path, _ = _write_lifecycle_fixture(tmp_path)

    with pytest.raises(PackagingError, match="cannot be in the future"):
        launch_competition_framework(
            framework,
            agent,
            working_root=tmp_path / "working",
            allow_test_fixture=True,
            notebook_started_at_seconds=time.monotonic() + 60.0,
        )

    assert not lifecycle_path.exists()


@pytest.mark.competition
def test_pre_make_callback_failure_prevents_underlying_make_and_is_receipted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    framework, agent, lifecycle_path, finalizer_path = _write_lifecycle_fixture(tmp_path)
    monkeypatch.setattr(
        launcher_module,
        "_discover_games",
        lambda host, port: ("fixture-a", "fixture-b"),
    )
    intents: list[tuple[str, int]] = []

    def stop_before_make(game_id: str, ordinal: int) -> None:
        intents.append((game_id, ordinal))
        raise RuntimeError("durable intent write failed")

    working = tmp_path / "working"
    with pytest.raises(RuntimeError, match="durable intent write failed"):
        launch_competition_framework(
            framework,
            agent,
            working_root=working,
            allow_test_fixture=True,
            before_environment_make=stop_before_make,
        )

    assert intents == [("fixture-a", 0)]
    assert json.loads(lifecycle_path.read_text(encoding="utf-8")) == [
        ["open_scorecard"],
        ["close_scorecard", "fixture-scorecard"],
    ]
    assert finalizer_path.is_file()
    failures = list(working.glob("arc3-launch-failure-*.json"))
    assert any(
        json.loads(path.read_text(encoding="utf-8"))["stage"] == "framework-run"
        for path in failures
    )


@pytest.mark.competition
def test_pre_open_callback_failure_prevents_upstream_scorecard_interaction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    framework, agent, lifecycle_path, finalizer_path = _write_lifecycle_fixture(tmp_path)
    monkeypatch.setattr(
        launcher_module,
        "_discover_games",
        lambda host, port: ("fixture-a",),
    )
    intents = 0

    def stop_before_open() -> None:
        nonlocal intents
        intents += 1
        raise RuntimeError("durable scorecard intent write failed")

    working = tmp_path / "working"
    with pytest.raises(RuntimeError, match="durable scorecard intent write failed"):
        launch_competition_framework(
            framework,
            agent,
            working_root=working,
            allow_test_fixture=True,
            before_scorecard_open=stop_before_open,
        )

    assert intents == 1
    assert not lifecycle_path.exists()
    assert finalizer_path.is_file()
    failures = list(working.glob("arc3-launch-failure-*.json"))
    assert any(
        json.loads(path.read_text(encoding="utf-8"))["lifecycle"]["open_scorecard_count"] == 0
        for path in failures
    )


@pytest.mark.competition
@pytest.mark.parametrize(
    ("behavior", "message"),
    [
        ("open_retry", "scorecard retry"),
        ("make_retry", "environment retry"),
        ("get_during_flight", "forbids scorecard reads"),
        ("changed_order", "frozen environment order"),
        ("close_retry", "scorecard close retry"),
        ("missing_environment", "exactly one agent per game"),
    ],
)
def test_launcher_fails_closed_on_lifecycle_violation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    behavior: str,
    message: str,
) -> None:
    framework, agent, _, _ = _write_lifecycle_fixture(tmp_path, behavior=behavior)
    monkeypatch.setattr(
        launcher_module,
        "_discover_games",
        lambda host, port: ("fixture-a", "fixture-b", "fixture-c"),
    )

    with pytest.raises(PackagingError, match=message):
        launch_competition_framework(
            framework,
            agent,
            working_root=tmp_path / "working",
            allow_test_fixture=True,
        )


@pytest.mark.competition
def test_launcher_rejects_duplicate_discovery_even_when_discovery_is_stubbed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    framework, agent, _, _ = _write_lifecycle_fixture(tmp_path)
    monkeypatch.setattr(
        launcher_module,
        "_discover_games",
        lambda host, port: ("fixture-a", "fixture-a"),
    )

    with pytest.raises(PackagingError, match="inventory is empty or duplicated"):
        launch_competition_framework(
            framework,
            agent,
            working_root=tmp_path / "working",
            allow_test_fixture=True,
        )


@pytest.mark.competition
def test_launcher_requires_tournament_hooks_before_scorecard_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    framework, agent, lifecycle_path, _ = _write_lifecycle_fixture(tmp_path)
    agent.write_text(
        "from agents.agent import Agent\n\nclass MyAgent(Agent):\n    pass\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        launcher_module,
        "_discover_games",
        lambda host, port: ("fixture-a",),
    )
    working = tmp_path / "working"

    with pytest.raises(PackagingError, match="requires configure_tournament"):
        launch_competition_framework(
            framework,
            agent,
            working_root=working,
            allow_test_fixture=True,
        )

    assert not lifecycle_path.exists()
    failures = list(working.glob("arc3-launch-failure-*.json"))
    assert len(failures) == 1
    payload = json.loads(failures[0].read_text(encoding="utf-8"))
    assert payload["stage"] == "tournament-hook-preflight"
    assert payload["tournament_configured"] is False


@pytest.mark.competition
def test_launcher_closes_scorecard_and_finalizes_before_worker_failure_verdict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    framework, agent, lifecycle_path, finalizer_path = _write_lifecycle_fixture(
        tmp_path, worker_failure=True
    )
    monkeypatch.setattr(
        launcher_module,
        "_discover_games",
        lambda host, port: ("fixture-a", "fixture-b", "fixture-c"),
    )

    with pytest.raises(PackagingError, match="scorecard closure completed"):
        launch_competition_framework(
            framework,
            agent,
            working_root=tmp_path / "working",
            allow_test_fixture=True,
        )

    lifecycle = json.loads(lifecycle_path.read_text(encoding="utf-8"))
    assert lifecycle[-1] == ["close_scorecard", "fixture-scorecard"]
    assert sum(event[0] == "close_scorecard" for event in lifecycle) == 1
    assert finalizer_path.is_file()


@pytest.mark.competition
@pytest.mark.parametrize("finalizer", ["failure", "non_json"])
def test_launcher_fails_closed_and_persists_tournament_finalization_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, finalizer: str
) -> None:
    framework, agent, _, _ = _write_lifecycle_fixture(tmp_path, finalizer=finalizer)
    monkeypatch.setattr(
        launcher_module,
        "_discover_games",
        lambda host, port: ("fixture-a", "fixture-b"),
    )

    working = tmp_path / "working"
    with pytest.raises(PackagingError, match="tournament finalization failed"):
        launch_competition_framework(
            framework,
            agent,
            working_root=working,
            allow_test_fixture=True,
        )

    failures = list(working.glob("arc3-launch-failure-*.json"))
    assert failures
    payloads = [json.loads(path.read_text(encoding="utf-8")) for path in failures]
    finalization = next(item for item in payloads if item["stage"] == "tournament-finalization")
    assert finalization["tournament_configured"] is True
    assert finalization["tournament_finalized"] is False
    assert finalization["tournament_receipt"]["status"] == "FAIL"


@pytest.mark.competition
def test_launcher_bounds_blocking_finalizer_and_persists_failure_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    framework, agent, _, _ = _write_lifecycle_fixture(tmp_path, finalizer="block")
    monkeypatch.setattr(launcher_module, "_discover_games", lambda host, port: ("fixture-a",))
    monkeypatch.setattr(launcher_module, "_PLATFORM_BOUNDARY_TIMEOUT_SECONDS", 0.02)
    working = tmp_path / "working"

    with pytest.raises(PackagingError, match="tournament finalization failed"):
        launch_competition_framework(
            framework,
            agent,
            working_root=working,
            allow_test_fixture=True,
        )

    payloads = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in working.glob("arc3-launch-failure-*.json")
    ]
    finalization = next(item for item in payloads if item["stage"] == "tournament-finalization")
    assert finalization["hard_deadline_seconds"] > 0.0
    assert finalization["hard_timeout_enforced"] is launcher_module._signal_deadline_available()
    assert finalization["tournament_receipt"]["status"] == "FAIL"


@pytest.mark.competition
def test_hard_deadline_rejects_call_before_invocation() -> None:
    invoked = False

    def should_not_run() -> None:
        nonlocal invoked
        invoked = True

    with pytest.raises(PackagingError, match="runtime deadline"):
        launcher_module._call_with_hard_deadline(
            "fixture operation",
            should_not_run,
            hard_deadline_seconds=time.monotonic() - 1.0,
        )

    assert invoked is False


@pytest.mark.competition
@pytest.mark.skipif(
    not launcher_module._signal_deadline_available(),
    reason="SIGALRM/setitimer interruption requires a POSIX main thread",
)
def test_linux_signal_deadline_interrupts_blocking_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(launcher_module, "_PLATFORM_BOUNDARY_TIMEOUT_SECONDS", 0.02)
    started = time.monotonic()

    with pytest.raises(PackagingError, match="exceeded its bounded runtime"):
        launcher_module._call_with_hard_deadline(
            "fixture blocking operation",
            lambda: time.sleep(1.0),
            hard_deadline_seconds=time.monotonic() + 10.0,
        )

    assert time.monotonic() - started < 0.5


@pytest.mark.competition
@pytest.mark.parametrize("finalizer", ["ceiling", "reserve"])
def test_launcher_rejects_non_reserve_preserving_tournament_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, finalizer: str
) -> None:
    framework, agent, _, _ = _write_lifecycle_fixture(tmp_path, finalizer=finalizer)
    monkeypatch.setattr(
        launcher_module,
        "_discover_games",
        lambda host, port: ("fixture-a", "fixture-b"),
    )
    working = tmp_path / "working"

    with pytest.raises(PackagingError, match=r"runtime ceiling|runtime reserve"):
        launch_competition_framework(
            framework,
            agent,
            working_root=working,
            allow_test_fixture=True,
        )

    failures = list(working.glob("arc3-launch-failure-*.json"))
    assert failures
    assert any(
        json.loads(path.read_text(encoding="utf-8"))["stage"] == "launch-postflight"
        for path in failures
    )
