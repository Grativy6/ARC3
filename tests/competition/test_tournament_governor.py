"""Focused contract tests for the scorecard-wide bounded governor."""

from __future__ import annotations

import math
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import cast

import pytest

from arc3.competition import (
    GovernorStopReason,
    TournamentGovernor,
    TournamentGovernorConfig,
    TournamentOutcome,
)
from arc3.errors import CompetitionIntegrityError
from arc3.types import ActionName, ActionRequest, Coordinate


class FakeClock:
    def __init__(self, value: float = 0.0) -> None:
        self._value = value
        self._lock = threading.Lock()

    def __call__(self) -> float:
        with self._lock:
            return self._value

    def advance(self, seconds: float) -> None:
        with self._lock:
            self._value += seconds

    def set(self, value: float) -> None:
        with self._lock:
            self._value = value


def _config(
    *,
    environments: int = 3,
    ceiling: float = 40.0,
    reserve: float = 10.0,
    minimum: float = 5.0,
    maximum_game: float = 20.0,
    game_actions: int = 4,
    total_actions: int = 12,
    history_capacity: int = 256,
) -> TournamentGovernorConfig:
    return TournamentGovernorConfig(
        expected_environments=environments,
        total_effective_ceiling_seconds=ceiling,
        reserve_seconds=reserve,
        minimum_fallback_seconds=minimum,
        maximum_game_seconds=maximum_game,
        maximum_actions_per_game=game_actions,
        maximum_total_actions=total_actions,
        history_capacity=history_capacity,
    )


@pytest.mark.competition
@pytest.mark.parametrize(
    "overrides,match",
    [
        ({"environments": 0}, "expected_environments"),
        ({"ceiling": math.inf}, "total_effective_ceiling_seconds"),
        ({"reserve": -1.0}, "reserve_seconds"),
        ({"reserve": 40.0}, "reserve_seconds must be below"),
        ({"minimum": 11.0}, "protect the minimum fallback slice"),
        ({"maximum_game": 4.0}, "maximum_game_seconds"),
        ({"game_actions": 0}, "maximum_actions_per_game"),
        ({"total_actions": 2}, "at least one action per environment"),
        ({"history_capacity": 0}, "history_capacity"),
    ],
)
def test_invalid_governor_configs_fail_closed(
    overrides: dict[str, int | float], match: str
) -> None:
    with pytest.raises(CompetitionIntegrityError, match=match):
        _config(**overrides)  # type: ignore[arg-type]


@pytest.mark.competition
def test_dynamic_allocation_protects_reserve_and_future_games() -> None:
    clock = FakeClock()
    governor = TournamentGovernor(_config(), clock=clock)
    start = governor.start_tournament()

    first = governor.begin_game("game-1")
    assert start.playable_deadline_seconds == 30.0
    assert first.allocated_seconds == 10.0
    assert first.protected_future_seconds == 10.0
    assert first.action_limit == 4

    clock.advance(4.0)
    action = governor.authorize_action(
        "game-1",
        ActionRequest(ActionName.ACTION1),
        (ActionName.ACTION1, ActionName.ACTION2),
        selected_value=2.5,
    )
    assert action.elapsed_cost_seconds == 4.0
    assert action.future_environment_count == 2
    assert action.future_opportunity_cost_seconds == 4.0
    assert action.future_opportunity_cost_per_environment_seconds == 2.0
    assert action.future_opportunity_cost_actions == 1

    first_final = governor.finalize_game("game-1", reason=GovernorStopReason.WIN)
    second = governor.begin_game("game-2")
    assert first_final.reserve_remaining_seconds == 10.0
    assert second.allocated_seconds == 13.0
    assert second.protected_future_seconds == 5.0


@pytest.mark.competition
def test_notebook_start_anchor_charges_preconfiguration_runtime() -> None:
    clock = FakeClock(10.0)
    governor = TournamentGovernor(_config(), clock=clock)
    start = governor.start_tournament(started_at_seconds=0.0)

    assert start.started_at_seconds == 0.0
    assert start.playable_deadline_seconds == 30.0
    allocation = governor.begin_game("game-1")
    assert allocation.tournament_playable_seconds_remaining_before == 20.0
    assert allocation.allocated_seconds == pytest.approx(20.0 / 3.0)


@pytest.mark.competition
def test_future_notebook_start_anchor_fails_closed() -> None:
    governor = TournamentGovernor(_config(), clock=FakeClock(10.0))
    with pytest.raises(CompetitionIntegrityError, match="start anchor"):
        governor.start_tournament(started_at_seconds=11.0)


@pytest.mark.competition
def test_legal_action_enforcement_and_coordinate_safe_fallback() -> None:
    clock = FakeClock()
    governor = TournamentGovernor(
        _config(environments=1, minimum=1.0, game_actions=5), clock=clock
    )
    governor.start_tournament()
    governor.begin_game("only")

    fallback = governor.authorize_action(
        "only",
        ActionRequest(ActionName.ACTION5),
        (ActionName.ACTION6,),
        selected_value=-0.25,
    )
    assert fallback.fallback_used is True
    assert fallback.authorized_action == ActionRequest(ActionName.ACTION6, Coordinate(32, 32))

    forced = governor.authorize_action(
        "only",
        ActionRequest(ActionName.ACTION6, Coordinate(1, 1)),
        (ActionName.ACTION5, ActionName.ACTION6),
        selected_value=0.0,
        force_fallback=True,
    )
    assert forced.fallback_used is True
    assert forced.authorized_action == ActionRequest(ActionName.ACTION5)

    action5 = governor.authorize_action(
        "only",
        ActionRequest(ActionName.ACTION5),
        (ActionName.ACTION5, ActionName.ACTION6),
        selected_value=0.0,
    )
    assert action5.authorized_action == ActionRequest(ActionName.ACTION5)
    assert action5.fallback_used is False

    action6 = governor.authorize_action(
        "only",
        ActionRequest(ActionName.ACTION6, Coordinate(7, 61)),
        (ActionName.ACTION5, ActionName.ACTION6),
        selected_value=1.0,
    )
    assert action6.authorized_action.coordinate == Coordinate(7, 61)


@pytest.mark.competition
@pytest.mark.parametrize(
    "legal",
    [
        (),
        (ActionName.ACTION1, ActionName.ACTION1),
        cast(tuple[ActionName, ...], ("ACTION1",)),
    ],
)
def test_malformed_legal_action_surfaces_fail_closed(legal: tuple[ActionName, ...]) -> None:
    governor = TournamentGovernor(_config(environments=1, minimum=1.0), clock=FakeClock())
    governor.start_tournament()
    governor.begin_game("only")
    with pytest.raises(CompetitionIntegrityError, match="legal_actions"):
        governor.authorize_action(
            "only", ActionRequest(ActionName.ACTION1), legal, selected_value=0.0
        )


@pytest.mark.competition
def test_stop_reasons_have_stable_resource_priority() -> None:
    clock = FakeClock()
    governor = TournamentGovernor(
        _config(
            environments=1,
            ceiling=20.0,
            reserve=5.0,
            minimum=1.0,
            maximum_game=5.0,
            game_actions=2,
            total_actions=2,
        ),
        clock=clock,
    )
    governor.start_tournament()
    governor.begin_game("only")
    for _ in range(2):
        governor.authorize_action(
            "only",
            ActionRequest(ActionName.ACTION1),
            (ActionName.ACTION1,),
            selected_value=1.0,
        )
    stop = governor.stop_decision("only")
    assert stop.reason is GovernorStopReason.TOURNAMENT_ACTION_LIMIT
    assert stop.should_stop is True
    with pytest.raises(CompetitionIntegrityError, match="authorization denied"):
        governor.authorize_action(
            "only",
            ActionRequest(ActionName.ACTION1),
            (ActionName.ACTION1,),
            selected_value=1.0,
        )
    governor.finalize_game("only", reason=GovernorStopReason.TOURNAMENT_ACTION_LIMIT)


@pytest.mark.competition
def test_game_time_limit_is_measured_before_finalization() -> None:
    clock = FakeClock()
    governor = TournamentGovernor(
        _config(environments=1, minimum=1.0, maximum_game=5.0), clock=clock
    )
    governor.start_tournament()
    governor.begin_game("only")
    clock.advance(5.0)

    assert governor.stop_decision("only").reason is GovernorStopReason.GAME_TIME_LIMIT
    with pytest.raises(CompetitionIntegrityError, match="does not honor measured"):
        governor.finalize_game("only", reason=GovernorStopReason.GAME_ACTION_LIMIT)
    final = governor.finalize_game("only", reason=GovernorStopReason.GAME_TIME_LIMIT)
    assert final.allocation_overrun_seconds == 0.0


@pytest.mark.competition
def test_nonresource_label_cannot_hide_a_measured_resource_stop() -> None:
    clock = FakeClock()
    governor = TournamentGovernor(
        _config(environments=1, minimum=1.0, maximum_game=5.0), clock=clock
    )
    governor.start_tournament()
    governor.begin_game("only")
    clock.advance(5.0)

    with pytest.raises(CompetitionIntegrityError, match="does not honor measured"):
        governor.finalize_game("only", reason=GovernorStopReason.AGENT_DONE)
    # A winning consequence returned by an action authorized inside the slice
    # remains a measured win; the receipt separately preserves its overrun.
    final = governor.finalize_game("only", reason=GovernorStopReason.WIN)
    assert final.reason is GovernorStopReason.WIN


@pytest.mark.competition
def test_lifecycle_duplicates_mismatches_and_early_tournament_close_fail_closed() -> None:
    governor = TournamentGovernor(_config(environments=2, minimum=1.0), clock=FakeClock())
    with pytest.raises(CompetitionIntegrityError, match="has not started"):
        governor.begin_game("game-1")
    governor.start_tournament()
    with pytest.raises(CompetitionIntegrityError, match="already started"):
        governor.start_tournament()
    with pytest.raises(CompetitionIntegrityError, match="count mismatch"):
        governor.finalize_tournament()

    governor.begin_game("game-1")
    with pytest.raises(CompetitionIntegrityError, match=r"while .* is active"):
        governor.begin_game("game-2")
    with pytest.raises(CompetitionIntegrityError, match="active game mismatch"):
        governor.stop_decision("game-2")
    governor.finalize_game("game-1", reason=GovernorStopReason.AGENT_DONE)
    with pytest.raises(CompetitionIntegrityError, match="no game is active"):
        governor.finalize_game("game-1", reason=GovernorStopReason.AGENT_DONE)
    with pytest.raises(CompetitionIntegrityError, match="already begun"):
        governor.begin_game("game-1")

    governor.begin_game("game-2")
    governor.finalize_game("game-2", reason=GovernorStopReason.FAILURE)
    final = governor.finalize_tournament()
    assert final.finalized_environments == 2
    assert final.outcome is TournamentOutcome.COMPLETE_RESERVE_PRESERVED
    with pytest.raises(CompetitionIntegrityError, match="already finalized"):
        governor.finalize_tournament()


@pytest.mark.competition
def test_final_receipts_preserve_aggregate_value_cost_and_tail() -> None:
    clock = FakeClock()
    governor = TournamentGovernor(_config(environments=1, minimum=1.0), clock=clock)
    governor.start_tournament()
    governor.begin_game("only")
    clock.advance(2.0)
    governor.authorize_action(
        "only",
        ActionRequest(ActionName.ACTION1),
        (ActionName.ACTION1,),
        selected_value=3.25,
    )
    clock.advance(1.5)
    game = governor.finalize_game("only", reason=GovernorStopReason.WIN)
    tournament = governor.finalize_tournament()

    assert game.elapsed_action_cost_total_seconds == 2.0
    assert game.unassigned_tail_elapsed_seconds == 1.5
    assert game.elapsed_seconds == 3.5
    assert game.selected_value_total == 3.25
    assert tournament.selected_value_total == 3.25
    assert tournament.games == (game,)
    assert tournament.reserve_preserved is True
    assert tournament.effective_ceiling_respected is True


@pytest.mark.competition
def test_history_is_bounded_and_reports_dropped_receipts() -> None:
    governor = TournamentGovernor(
        _config(environments=1, minimum=1.0, history_capacity=3), clock=FakeClock()
    )
    governor.start_tournament()
    governor.begin_game("only")
    governor.stop_decision("only")
    governor.stop_decision("only")
    governor.finalize_game("only", reason=GovernorStopReason.AGENT_DONE)
    final = governor.finalize_tournament()

    assert len(governor.receipt_history) == 3
    assert governor.dropped_history_receipts == 3
    assert final.recent_history_receipts == 3
    assert final.dropped_history_receipts == 3
    assert governor.receipt_history[-1] is final


@pytest.mark.competition
def test_authorization_is_thread_safe_at_the_action_limit() -> None:
    governor = TournamentGovernor(
        _config(
            environments=1,
            minimum=1.0,
            game_actions=5,
            total_actions=5,
        ),
        clock=FakeClock(),
    )
    governor.start_tournament()
    governor.begin_game("only")

    def attempt() -> int | None:
        try:
            return governor.authorize_action(
                "only",
                ActionRequest(ActionName.ACTION1),
                (ActionName.ACTION1,),
                selected_value=1.0,
            ).action_ordinal
        except CompetitionIntegrityError:
            return None

    with ThreadPoolExecutor(max_workers=8) as pool:
        ordinals = list(pool.map(lambda _index: attempt(), range(16)))

    assert sorted(value for value in ordinals if value is not None) == [1, 2, 3, 4, 5]
    assert governor.total_actions_authorized == 5
    assert governor.stop_decision("only").reason is GovernorStopReason.TOURNAMENT_ACTION_LIMIT


@pytest.mark.competition
def test_nonfinite_or_backward_clock_fails_closed() -> None:
    clock = FakeClock(10.0)
    governor = TournamentGovernor(_config(environments=1, minimum=1.0), clock=clock)
    governor.start_tournament()
    clock.set(9.0)
    with pytest.raises(CompetitionIntegrityError, match="moved backwards"):
        governor.begin_game("only")

    nonfinite = TournamentGovernor(_config(environments=1, minimum=1.0), clock=lambda: math.nan)
    with pytest.raises(CompetitionIntegrityError, match="finite number"):
        nonfinite.start_tournament()


@pytest.mark.competition
def test_elapsed_tournament_still_registers_and_finalizes_every_environment() -> None:
    clock = FakeClock()
    governor = TournamentGovernor(
        _config(
            environments=3,
            ceiling=20.0,
            reserve=5.0,
            minimum=2.0,
            maximum_game=10.0,
        ),
        clock=clock,
    )
    governor.start_tournament()
    governor.begin_game("game-1")
    clock.advance(15.0)
    assert (
        governor.stop_decision("game-1").reason
        is GovernorStopReason.TOURNAMENT_PLAYABLE_TIME_LIMIT
    )
    governor.finalize_game(
        "game-1", reason=GovernorStopReason.TOURNAMENT_PLAYABLE_TIME_LIMIT
    )

    for game_id in ("game-2", "game-3"):
        allocation = governor.begin_game(game_id)
        assert allocation.allocated_seconds == 0.0
        assert allocation.minimum_fallback_slice_used is True
        stop = governor.stop_decision(game_id)
        assert stop.reason is GovernorStopReason.TOURNAMENT_PLAYABLE_TIME_LIMIT
        governor.finalize_game(game_id, reason=stop.reason)

    receipt = governor.finalize_tournament()
    assert receipt.finalized_environments == 3
    assert [game.game_id for game in receipt.games] == ["game-1", "game-2", "game-3"]
