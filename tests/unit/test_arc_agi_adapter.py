"""Contract tests for the optional official SDK adapter boundary."""

from __future__ import annotations

from enum import Enum
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest

from arc3.adapters.arc_agi import ArcAGIAdapter, _SDKBindings, normalize_frame_data
from arc3.config import ARC3Config
from arc3.errors import AdapterError, ConfigurationError, InvalidActionError, NetworkDisabledError
from arc3.types import (
    ActionName,
    ActionRequest,
    Coordinate,
    EnvironmentMode,
    EvaluationSurface,
    GameStateName,
)


class FakeMode(Enum):
    OFFLINE = "offline"
    ONLINE = "online"
    COMPETITION = "competition"


class FakeAction(Enum):
    RESET = 0
    ACTION1 = 1
    ACTION2 = 2
    ACTION3 = 3
    ACTION4 = 4
    ACTION5 = 5
    ACTION6 = 6
    ACTION7 = 7


def make_frame(
    *,
    state: GameStateName = GameStateName.NOT_FINISHED,
    available: list[int] | None = None,
    returned_action: FakeAction = FakeAction.RESET,
) -> SimpleNamespace:
    return SimpleNamespace(
        game_id="fixture-environment-v1",
        frame=[np.array([[0, 1], [2, 3]], dtype=np.int8)],
        state=state,
        levels_completed=0,
        win_levels=1,
        action_input=SimpleNamespace(id=returned_action, data={}),
        guid="fixture-session",
        full_reset=returned_action is FakeAction.RESET,
        available_actions=[1, 6] if available is None else available,
    )


def make_scorecard() -> SimpleNamespace:
    run = SimpleNamespace(
        score=0.0,
        levels_completed=0,
        actions=1,
        resets=0,
        state=GameStateName.NOT_FINISHED,
        completed=False,
        level_scores=[0.0],
        level_actions=[1],
        level_baseline_actions=[2],
    )
    return SimpleNamespace(
        score=0.0,
        environments=[SimpleNamespace(id="fixture-environment-v1", runs=[run])],
        api_key="SENTINEL_NOT_A_SECRET",
    )


class FakeWrapper:
    def __init__(self) -> None:
        self.scorecard_id = "fixture-scorecard"
        self.observation_space: object | None = make_frame()
        self.reset_calls = 0
        self.step_calls: list[tuple[object, dict[str, object] | None]] = []
        self.next_state = GameStateName.NOT_FINISHED

    def reset(self) -> object:
        self.reset_calls += 1
        self.observation_space = make_frame()
        return self.observation_space

    def step(
        self,
        action: object,
        data: dict[str, object] | None = None,
        reasoning: dict[str, object] | None = None,
    ) -> object:
        del reasoning
        self.step_calls.append((action, data))
        returned = action if isinstance(action, FakeAction) else FakeAction.ACTION1
        response = make_frame(state=self.next_state, returned_action=returned)
        self.observation_space = response
        return response


class FakeArcade:
    def __init__(self, operation_mode: object, wrapper: FakeWrapper) -> None:
        self.operation_mode = operation_mode
        self.wrapper = wrapper
        self.make_calls = 0

    def get_environments(self) -> list[SimpleNamespace]:
        return [
            SimpleNamespace(
                game_id="z-fixture-v1",
                title="Z fixture",
                tags=["test"],
                baseline_actions=[2],
                local_dir=None,
            ),
            SimpleNamespace(
                game_id="a-fixture-v1",
                title="A fixture",
                tags=["test", "local"],
                baseline_actions=[1, 3],
                local_dir="ignored-private-path",
            ),
        ]

    def make(self, game_id: str, **kwargs: object) -> FakeWrapper | None:
        del kwargs
        self.make_calls += 1
        return self.wrapper if game_id != "missing" else None

    def get_scorecard(self, scorecard_id: str | None = None) -> object:
        assert scorecard_id == self.wrapper.scorecard_id
        return make_scorecard()

    def close_scorecard(self, scorecard_id: str | None = None) -> object:
        assert scorecard_id == self.wrapper.scorecard_id
        return make_scorecard()


class FakeFactory:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []
        self.wrapper = FakeWrapper()
        self.arcade: FakeArcade | None = None

    def __call__(self, **kwargs: object) -> FakeArcade:
        self.calls.append(dict(kwargs))
        logger = kwargs["logger"]
        assert hasattr(logger, "info")
        logger.info("Got anonymous API key: SENTINEL_NOT_A_SECRET")
        self.arcade = FakeArcade(kwargs["operation_mode"], self.wrapper)
        return self.arcade


def fake_bindings(factory: Any) -> _SDKBindings:
    return _SDKBindings(
        arcade_factory=factory,
        operation_modes={
            EnvironmentMode.LOCAL: FakeMode.OFFLINE,
            EnvironmentMode.ONLINE: FakeMode.ONLINE,
            EnvironmentMode.COMPETITION: FakeMode.COMPETITION,
        },
        game_actions={ActionName[item.name]: item for item in FakeAction},
    )


def local_adapter(factory: FakeFactory) -> ArcAGIAdapter:
    return ArcAGIAdapter(
        ARC3Config.for_mode(EnvironmentMode.LOCAL, seed=7),
        environments_dir="fixture-environments",
        recordings_dir="fixture-recordings",
        environ={},
        bindings=fake_bindings(factory),
    )


def test_frame_normalization_deep_copies_private_raw_frames() -> None:
    frame = make_frame()
    source = frame.frame[0]
    observation = normalize_frame_data(frame)

    source[0, 0] = 9

    assert observation.frames[0].cells == ((0, 1), (2, 3))
    assert observation.frames[0].width == 2
    assert observation.frames[0].height == 2
    assert observation.available_actions == (ActionName.ACTION1, ActionName.ACTION6)
    assert observation.returned_action == ActionRequest(ActionName.RESET)
    assert "numpy" not in type(observation.frames[0].cells).__module__


def test_normalization_rejects_unknown_upstream_action() -> None:
    with pytest.raises(AdapterError, match="unknown upstream action ID 9"):
        normalize_frame_data(make_frame(available=[9]))


def test_discovery_is_sorted_copied_and_silent(capsys: pytest.CaptureFixture[str]) -> None:
    factory = FakeFactory()
    adapter = local_adapter(factory)

    games = adapter.list_games()

    assert [str(game.game_id) for game in games] == ["a-fixture-v1", "z-fixture-v1"]
    assert games[0].locally_available is True
    assert games[0].baseline_actions == (1, 3)
    assert "ignored-private-path" not in repr(games)
    assert "SENTINEL_NOT_A_SECRET" not in capsys.readouterr().out
    assert factory.calls[0]["arc_api_key"] == ""
    assert factory.calls[0]["operation_mode"] is FakeMode.OFFLINE


def test_make_uses_constructor_observation_without_duplicate_reset() -> None:
    factory = FakeFactory()
    session = local_adapter(factory).open("fixture-environment", seed=11)

    assert factory.wrapper.reset_calls == 0
    assert session.observation.state is GameStateName.NOT_FINISHED


def test_invalid_action_is_rejected_before_backend_call() -> None:
    factory = FakeFactory()
    session = local_adapter(factory).open("fixture-environment")

    with pytest.raises(InvalidActionError):
        session.step(ActionRequest(ActionName.ACTION7))

    assert factory.wrapper.step_calls == []


def test_fractional_coordinate_is_rejected_before_backend_call() -> None:
    factory = FakeFactory()
    session = local_adapter(factory).open("fixture-environment")
    coordinate = Coordinate(1.5, 2)  # type: ignore[arg-type]

    with pytest.raises(InvalidActionError, match="exact integers"):
        session.step(ActionRequest(ActionName.ACTION6, coordinate))

    assert factory.wrapper.step_calls == []


def test_game_over_forces_reset_and_scorecard_drops_credentials() -> None:
    factory = FakeFactory()
    session = local_adapter(factory).open("fixture-environment")
    factory.wrapper.next_state = GameStateName.GAME_OVER

    result = session.step(ActionRequest(ActionName.ACTION1))
    assert result.state is GameStateName.GAME_OVER
    with pytest.raises(InvalidActionError, match="only RESET"):
        session.step(ActionRequest(ActionName.ACTION1))

    reset = session.step(ActionRequest(ActionName.RESET))
    assert reset.state is GameStateName.NOT_FINISHED
    assert factory.wrapper.reset_calls == 1
    scorecard = session.close()
    assert scorecard is not None
    assert scorecard.surface is EvaluationSurface.LOCAL_PUBLIC
    assert scorecard.score == 0.0
    assert "SENTINEL_NOT_A_SECRET" not in repr(scorecard)
    assert session.close() is scorecard


def test_environment_override_is_rejected_before_sdk_construction() -> None:
    factory = FakeFactory()
    with pytest.raises(ConfigurationError, match="OPERATION_MODE conflicts"):
        ArcAGIAdapter(
            ARC3Config.for_mode(EnvironmentMode.LOCAL),
            environ={"OPERATION_MODE": "competition"},
            bindings=fake_bindings(factory),
        )
    assert factory.calls == []


def test_online_requires_network_and_competition_requires_loopback() -> None:
    factory = FakeFactory()
    with pytest.raises(NetworkDisabledError, match="requires network_enabled"):
        ArcAGIAdapter(
            ARC3Config.for_mode(EnvironmentMode.ONLINE, network_enabled=False),
            environ={},
            bindings=fake_bindings(factory),
        )
    with pytest.raises(NetworkDisabledError, match="loopback"):
        ArcAGIAdapter(
            ARC3Config.for_mode(EnvironmentMode.COMPETITION),
            base_url="https://example.invalid",
            result_surface=EvaluationSurface.SEMI_PRIVATE,
            environ={},
            bindings=fake_bindings(factory),
        )


def test_upstream_exception_message_is_redacted() -> None:
    def fail(**kwargs: object) -> FakeArcade:
        del kwargs
        raise RuntimeError("SENTINEL_NOT_A_SECRET")

    adapter = ArcAGIAdapter(
        ARC3Config.for_mode(EnvironmentMode.LOCAL),
        environ={},
        bindings=fake_bindings(fail),
    )
    with pytest.raises(AdapterError) as caught:
        adapter.list_games()
    assert "RuntimeError" in str(caught.value)
    assert "SENTINEL_NOT_A_SECRET" not in str(caught.value)


def test_missing_environment_and_missing_initial_observation_are_errors() -> None:
    factory = FakeFactory()
    adapter = local_adapter(factory)
    with pytest.raises(AdapterError, match="could not create"):
        adapter.open("missing")

    factory.wrapper.observation_space = None
    with pytest.raises(AdapterError, match="without an initial reset observation"):
        adapter.open("fixture-environment")
