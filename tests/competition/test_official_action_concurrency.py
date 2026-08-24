"""Concurrency regression for the pinned Agents request boundary."""

from __future__ import annotations

import runpy
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier, Lock
from typing import cast

import pytest
from arcengine import GameAction

from arc3.types import ActionName, ActionRequest, Coordinate

ROOT = Path(__file__).resolve().parents[2]
WRAPPER = runpy.run_path(str(ROOT / "agent" / "my_agent.py"))
MyAgent = cast(type[object], WRAPPER["MyAgent"])
translate_action = cast(Callable[[ActionRequest], object], WRAPPER["_translate_action"])


class _RecordingEnvironment:
    def __init__(self, barrier: Barrier) -> None:
        self._barrier = barrier
        self._lock = Lock()
        self.requests: list[tuple[object, dict[str, object], object]] = []

    def step(
        self,
        action: object,
        *,
        data: dict[str, object] | None,
        reasoning: object,
    ) -> dict[str, object]:
        self._barrier.wait(timeout=5)
        with self._lock:
            self.requests.append((action, dict(data or {}), reasoning))
        return {"accepted": True}


class _UnexpiredGovernor:
    class _Stop:
        should_stop = False
        game_seconds_remaining = 5.0
        tournament_playable_seconds_remaining = 5.0

    def stop_decision(self, game_id: str) -> _Stop:
        del game_id
        return self._Stop()


def _translated(x: int, y: int) -> object:
    return translate_action(ActionRequest(ActionName.ACTION6, Coordinate(x, y)))


@pytest.mark.competition
def test_two_agents_keep_action6_coordinates_instance_local_under_concurrency(
    tmp_path: Path,
) -> None:
    configure = MyAgent.configure_tournament
    configure(("concurrent-a", "concurrent-b"), tmp_path / "action-runtime")
    before = GameAction.ACTION6.action_data.model_dump()
    first_request = _translated(2, 3)
    second_request = _translated(61, 62)

    # Translation must not mutate the process-wide enum singleton.
    assert GameAction.ACTION6.action_data.model_dump() == before

    barrier = Barrier(2)
    first_environment = _RecordingEnvironment(barrier)
    second_environment = _RecordingEnvironment(barrier)
    first_agent = MyAgent(game_id="concurrent-a", seed=7)
    second_agent = MyAgent(game_id="concurrent-b", seed=11)
    first_agent.arc_env = first_environment
    second_agent.arc_env = second_environment
    first_agent._convert_raw_frame_data = lambda raw: raw
    second_agent._convert_raw_frame_data = lambda raw: raw
    first_agent._require_governor = lambda: _UnexpiredGovernor()
    second_agent._require_governor = lambda: _UnexpiredGovernor()

    with ThreadPoolExecutor(max_workers=2) as executor:
        first_future = executor.submit(first_agent.do_action_request, first_request)
        second_future = executor.submit(second_agent.do_action_request, second_request)
        assert first_future.result(timeout=10) == {"accepted": True}
        assert second_future.result(timeout=10) == {"accepted": True}

    assert first_environment.requests == [
        (GameAction.ACTION6, {"game_id": "", "x": 2, "y": 3}, None)
    ]
    assert second_environment.requests == [
        (GameAction.ACTION6, {"game_id": "", "x": 61, "y": 62}, None)
    ]
    assert GameAction.ACTION6.action_data.model_dump() == before
    finalize = MyAgent.finalize_tournament
    finalize()
