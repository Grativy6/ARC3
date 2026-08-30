from __future__ import annotations

import json
import runpy
from pathlib import Path
from typing import Any

import pytest
from arcengine import FrameData, GameState

from arc3.adapters.normalization import normalize_frame_data
from arc3.competition_runtime import FROZEN_COMPETITION_RUNTIME
from arc3.mechanics.visual_causal import (
    VisualActionPurpose,
    VisualCausalPolicy,
    supports_visual_causal_observation,
)

ROOT = Path(__file__).resolve().parents[2]
WRAPPER = runpy.run_path(str(ROOT / "agent" / "my_agent.py"))
MyAgent = WRAPPER["MyAgent"]
BOUNDED_STOP = WRAPPER["_BoundedTournamentStop"]

_ENDPOINT_SHAPE = (
    (0, -2),
    (-1, -1),
    (0, -1),
    (1, -1),
    (-2, 0),
    (-1, 0),
    (0, 0),
    (1, 0),
    (2, 0),
    (-1, 1),
    (0, 1),
    (1, 1),
    (0, 2),
)
_MEDIATOR_OUTER = tuple(
    (dx, dy)
    for dy in range(-2, 3)
    for dx in range(-2, 3)
    if (abs(dx), abs(dy)) != (2, 2) and (dx, dy) != (0, 0)
)
_TARGET_RING = (
    (-1, -2),
    (0, -2),
    (1, -2),
    (-2, -1),
    (2, -1),
    (-2, 0),
    (2, 0),
    (-2, 1),
    (2, 1),
    (-1, 2),
    (0, 2),
    (1, 2),
)


def _paint(
    rows: list[list[int]],
    center: tuple[int, int],
    shape: tuple[tuple[int, int], ...],
    color: int,
) -> None:
    for dx, dy in shape:
        rows[center[1] + dy][center[0] + dx] = color


def _readable_rows() -> list[list[int]]:
    rows = [[5 for _ in range(40)] for _ in range(40)]
    active = (8, 30)
    anchor = (30, 30)
    mediator = (19, 30)
    target = (20, 8)
    _paint(rows, active, _ENDPOINT_SHAPE, 0)
    _paint(rows, anchor, _ENDPOINT_SHAPE, 3)
    _paint(rows, mediator, _MEDIATOR_OUTER, 15)
    rows[mediator[1]][mediator[0]] = 6
    _paint(rows, target, _TARGET_RING, 15)
    return rows


def _flat_rows() -> list[list[int]]:
    return [[5 for _ in range(40)] for _ in range(40)]


def _frame(
    game_id: str,
    rows: list[list[int]],
    *,
    state: GameState = GameState.NOT_FINISHED,
    levels_completed: int = 0,
    available_actions: list[int] | None = None,
) -> FrameData:
    return FrameData(
        game_id=game_id,
        frame=[rows],
        state=state,
        levels_completed=levels_completed,
        win_levels=2,
        available_actions=[6] if available_actions is None else available_actions,
    )


def _win(game_id: str, rows: list[list[int]]) -> FrameData:
    return _frame(
        game_id,
        rows,
        state=GameState.WIN,
        levels_completed=2,
        available_actions=[],
    )


@pytest.mark.competition
def test_visual_production_gate_requires_current_readable_action6_evidence() -> None:
    readable = normalize_frame_data(_frame("readable-fixture", _readable_rows()))
    no_coordinate = normalize_frame_data(
        _frame("no-coordinate-fixture", _readable_rows(), available_actions=[1, 2, 3, 4])
    )
    flat = normalize_frame_data(_frame("flat-coordinate-fixture", _flat_rows()))
    pregame = normalize_frame_data(
        _frame(
            "pregame-fixture",
            _readable_rows(),
            state=GameState.NOT_PLAYED,
            available_actions=[0],
        )
    )

    assert supports_visual_causal_observation(readable) is True
    assert supports_visual_causal_observation(no_coordinate) is False
    assert supports_visual_causal_observation(flat) is False
    assert supports_visual_causal_observation(pregame) is False


@pytest.mark.competition
def test_visual_policy_cancellation_retracts_prediction_and_all_pending_fields() -> None:
    observation = normalize_frame_data(_frame("cancel-fixture", _readable_rows()))
    policy = VisualCausalPolicy(max_coordinate_candidates=8)

    policy.select(observation)
    learner = policy.mechanical_learner
    assert learner is not None
    assert len(learner.pending) == 1
    assert policy.snapshot()["pending_action"] is not None

    policy.cancel_unsubmitted_action()

    assert learner.pending == ()
    assert policy.receipts == ()
    assert policy.snapshot()["pending_action"] is None
    assert policy.snapshot()["pending_prediction_id"] is None
    assert policy._pending_before is None
    assert policy._pending_action is None
    assert policy._pending_purpose is VisualActionPurpose.PROBE
    assert policy._pending_prediction == "all factored channels UNKNOWN"
    assert policy._pending_mechanic_refs == ()
    assert policy._pending_plan_signature is None
    assert policy._pending_target_center is None
    assert policy._pending_mediator_color is None
    assert policy._pending_arity is None
    assert policy._pending_completes_local_target is False
    assert policy._pending_completes_hierarchy is False
    assert policy._pending_completes_child_isolation is False
    assert policy._pending_completes_child_recovery is False
    assert policy._pending_expected_child_mediator_center is None
    assert policy._pending_expected_child_mediator_signature is None
    assert policy._pending_expected_child_endpoint_centers == ()
    assert policy._pending_expected_child_endpoint_signature == ()
    assert policy._pending_expected_child_connector_signature is None
    assert policy._pending_expected_active_center is None
    assert policy._pending_expected_child_protected_raster_hash is None
    assert policy._pending_expected_child_raster_signature == ()
    assert policy._pending_expected_occluded_endpoint_centers == ()
    assert policy._pending_expected_occluded_endpoint_cells == ()
    assert policy._pending_expected_visible_endpoint_count is None
    assert policy._pending_expected_visible_mediator_count is None
    assert policy._pending_affine_reacquisition is False
    assert policy._pending_mechanic_prediction is None
    policy.close()

    # The prediction slot and its deterministic sequence are reusable.
    policy.select(observation)
    assert len(learner.pending) == 1
    policy.cancel_unsubmitted_action()
    policy.close()

    # An interrupt can land after learner.predict returns but before the policy
    # assigns its receipt. Cancellation recovers the sole learner-owned slot.
    policy.select(observation)
    policy._pending_mechanic_prediction = None
    assert len(learner.pending) == 1
    policy.cancel_unsubmitted_action()
    assert learner.pending == ()
    assert policy.snapshot()["pending_action"] is None
    policy.close()


@pytest.mark.competition
def test_myagent_routes_readable_levels_through_mechanical_policy_and_snapshots(
    tmp_path: Path,
) -> None:
    game_id = "mechanical-production-fixture"
    runtime_root = tmp_path / "mechanical-runtime"
    MyAgent.configure_tournament((game_id,), runtime_root)
    agent = MyAgent(game_id=game_id, seed=53)

    first_action = agent.choose_action([], _frame(game_id, _readable_rows()))
    assert first_action.name == "ACTION6"
    assert agent._policy_route.value == "mechanical"
    assert agent._controller is None

    second_action = agent.choose_action(
        [],
        _frame(game_id, _readable_rows(), levels_completed=1),
    )
    assert second_action.name == "ACTION6"
    assert agent._mechanical_policy.snapshot()["active_level_index"] == 1
    assert agent._mechanical_policy.snapshot()["receipt_count"] == 1

    assert agent.is_done([], _win(game_id, _readable_rows())) is True
    assert agent._mechanical_policy.snapshot()["receipt_count"] == 2
    assert agent._mechanical_policy_closed is True
    tournament = MyAgent.finalize_tournament()
    assert tournament["games"][0]["reason"] == "win"

    snapshots = tuple((runtime_root / "arc3-runtime-receipts").glob("policy-*.json"))
    assert len(snapshots) == 1
    snapshot = json.loads(snapshots[0].read_text(encoding="utf-8"))
    assert snapshot["schema"] == "arc3.production-policy-route.v0.2"
    assert snapshot["policy_route"] == "mechanical"
    assert snapshot["pending_policy_route"] is None
    assert snapshot["mechanical_policy_closed"] is True
    assert snapshot["mechanical_policy"]["receipt_count"] == 2


@pytest.mark.competition
def test_pregame_reset_consequence_and_next_selection_share_one_decision_slice(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    game_id = "mechanical-reset-fixture"
    MyAgent.configure_tournament((game_id,), tmp_path / "mechanical-reset-runtime")
    agent = MyAgent(game_id=game_id, seed=57)

    reset = agent.choose_action(
        [],
        _frame(
            game_id,
            _readable_rows(),
            state=GameState.NOT_PLAYED,
            available_actions=[0],
        ),
    )
    assert reset.name == "RESET"
    assert agent._policy_route is None
    assert agent._mechanical_policy.snapshot()["receipt_count"] == 0

    returned = _frame(game_id, _readable_rows())
    assert agent.is_done([], returned) is False
    assert agent._mechanical_policy.snapshot()["receipt_count"] == 0

    calls: list[str] = []

    def measured(call: Any, *, seconds: float, boundary: str) -> Any:
        assert seconds <= FROZEN_COMPETITION_RUNTIME.decision_seconds
        calls.append(boundary)
        return call()

    monkeypatch.setitem(agent.choose_action.__globals__, "_bounded_call", measured)
    first_action = agent.choose_action([], returned)

    assert first_action.name == "ACTION6"
    assert calls == ["controller-decision"]
    assert agent._policy_route.value == "mechanical"
    assert agent._mechanical_policy.snapshot()["receipt_count"] == 1
    assert agent.is_done([], _win(game_id, _readable_rows())) is True
    assert MyAgent.finalize_tournament()["games"][0]["reason"] == "win"


@pytest.mark.competition
def test_mechanical_route_degrades_once_and_never_reenters_after_support_returns(
    tmp_path: Path,
) -> None:
    game_id = "mechanical-degrade-fixture"
    MyAgent.configure_tournament((game_id,), tmp_path / "mechanical-degrade-runtime")
    agent = MyAgent(game_id=game_id, seed=58)

    assert agent.choose_action([], _frame(game_id, _readable_rows())).name == "ACTION6"
    fallback = agent.choose_action(
        [],
        _frame(game_id, _flat_rows(), available_actions=[1, 2, 3, 4]),
    )
    assert fallback.name in {"ACTION1", "ACTION2", "ACTION3", "ACTION4"}
    assert agent._policy_route.value == "controller"
    assert agent._mechanical_policy_closed is True
    assert agent._mechanical_policy.snapshot()["receipt_count"] == 1
    assert agent._controller is not None

    agent.choose_action(
        [],
        _frame(game_id, _readable_rows(), available_actions=[1, 2, 3, 4, 6]),
    )
    assert supports_visual_causal_observation(
        normalize_frame_data(_frame(game_id, _readable_rows(), available_actions=[1, 2, 3, 4, 6]))
    )
    assert agent._policy_route.value == "controller"
    assert agent._mechanical_policy.snapshot()["receipt_count"] == 1

    assert agent.is_done([], _win(game_id, _readable_rows())) is True
    assert MyAgent.finalize_tournament()["games"][0]["reason"] == "win"


@pytest.mark.competition
def test_governor_rejection_cancels_last_unsubmitted_mechanical_prediction(
    tmp_path: Path,
) -> None:
    game_id = "mechanical-reset-limit-fixture"
    MyAgent.configure_tournament((game_id,), tmp_path / "mechanical-reset-limit-runtime")
    agent = MyAgent(game_id=game_id, seed=61)
    pregame = _frame(
        game_id,
        _readable_rows(),
        state=GameState.NOT_PLAYED,
        available_actions=[0],
    )

    for _ in range(FROZEN_COMPETITION_RUNTIME.max_resets):
        assert agent.choose_action([], pregame).name == "RESET"
    with pytest.raises(BOUNDED_STOP, match="game-reset-limit"):
        agent.choose_action([], pregame)

    learner = agent._mechanical_policy.mechanical_learner
    assert learner is not None
    assert learner.pending == ()
    assert agent._pending_policy_route is None
    assert agent._mechanical_policy_closed is True
    assert MyAgent.finalize_tournament()["games"][0]["reason"] == "game-reset-limit"


@pytest.mark.competition
def test_missing_environment_step_cancels_definitely_unsubmitted_mechanical_action(
    tmp_path: Path,
) -> None:
    game_id = "mechanical-no-step-fixture"
    MyAgent.configure_tournament((game_id,), tmp_path / "mechanical-no-step-runtime")
    agent = MyAgent(game_id=game_id, seed=63)
    request = agent.choose_action([], _frame(game_id, _readable_rows()))
    agent.arc_env = object()

    with pytest.raises(RuntimeError, match="no callable environment step"):
        agent.do_action_request(request)

    learner = agent._mechanical_policy.mechanical_learner
    assert learner is not None
    assert learner.pending == ()
    assert agent._pending_policy_route is None
    assert agent._mechanical_policy_closed is True
    assert MyAgent.failure_receipts()[-1]["boundary"] == "environment-step-unavailable"
    assert MyAgent.finalize_tournament()["games"][0]["reason"] == "failure"


@pytest.mark.competition
def test_missing_converter_cancels_before_environment_submission(
    tmp_path: Path,
) -> None:
    game_id = "mechanical-no-converter-fixture"
    MyAgent.configure_tournament((game_id,), tmp_path / "mechanical-no-converter-runtime")
    agent = MyAgent(game_id=game_id, seed=65)
    request = agent.choose_action([], _frame(game_id, _readable_rows()))

    class StepWitness:
        calls = 0

        def step(self, *_args: object, **_kwargs: object) -> object:
            self.calls += 1
            return object()

    witness = StepWitness()
    agent.arc_env = witness
    agent._convert_raw_frame_data = None

    with pytest.raises(RuntimeError, match="no frame conversion boundary"):
        agent.do_action_request(request)

    assert witness.calls == 0
    learner = agent._mechanical_policy.mechanical_learner
    assert learner is not None
    assert learner.pending == ()
    assert agent._pending_policy_route is None
    assert agent._mechanical_policy_closed is True
    assert MyAgent.failure_receipts()[-1]["boundary"] == "environment-converter-unavailable"
    assert MyAgent.finalize_tournament()["games"][0]["reason"] == "failure"


@pytest.mark.competition
def test_failed_close_is_not_reported_as_closed(tmp_path: Path) -> None:
    game_id = "mechanical-close-invariant-fixture"
    runtime_root = tmp_path / "mechanical-close-invariant-runtime"
    MyAgent.configure_tournament((game_id,), runtime_root)
    agent = MyAgent(game_id=game_id, seed=66)

    agent.choose_action([], _frame(game_id, _readable_rows()))
    agent.cleanup()

    assert agent._mechanical_policy_closed is False
    assert agent._pending_policy_route.value == "mechanical"
    snapshot_path = next((runtime_root / "arc3-runtime-receipts").glob("policy-*.json"))
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    assert snapshot["mechanical_policy_closed"] is False
    assert snapshot["mechanical_policy"]["pending_action"] is not None
    assert MyAgent.failure_receipts()[-1]["boundary"] == "controller-finalize"
    assert MyAgent.finalize_tournament()["games"][0]["reason"] == "failure"


@pytest.mark.competition
def test_translation_failure_cancels_mechanical_action_before_environment_submit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    game_id = "mechanical-translation-fixture"
    MyAgent.configure_tournament((game_id,), tmp_path / "mechanical-translation-runtime")
    agent = MyAgent(game_id=game_id, seed=67)

    def fail_translation(_action: object) -> object:
        raise RuntimeError("fixture translation failure")

    monkeypatch.setitem(agent.choose_action.__globals__, "_translate_action", fail_translation)
    with pytest.raises(RuntimeError, match="fixture translation failure"):
        agent.choose_action([], _frame(game_id, _readable_rows()))

    learner = agent._mechanical_policy.mechanical_learner
    assert learner is not None
    assert learner.pending == ()
    assert agent._pending_policy_route is None
    assert agent._mechanical_policy_closed is True
    assert MyAgent.failure_receipts()[-1]["boundary"] == "action-translation"
    assert MyAgent.finalize_tournament()["games"][0]["reason"] == "failure"
