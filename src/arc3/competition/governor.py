"""Deterministic global runtime and action governor for bounded tournaments.

The governor owns only competition-wide resource authority.  It does not infer
game rules or choose among valid policy actions.  Callers supply a requested
action and the currently advertised legal action names; the governor either
authorizes that request or returns a deterministic legal fallback.
"""

from __future__ import annotations

import math
import threading
import time
from collections import deque
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Final

from arc3.errors import CompetitionIntegrityError
from arc3.types import ActionName, ActionRequest, Coordinate

MonotonicClock = Callable[[], float]

_FALLBACK_ORDER: Final[tuple[ActionName, ...]] = (
    ActionName.ACTION1,
    ActionName.ACTION2,
    ActionName.ACTION3,
    ActionName.ACTION4,
    ActionName.ACTION5,
    ActionName.ACTION7,
    ActionName.ACTION6,
    ActionName.RESET,
)


class GovernorStopReason(StrEnum):
    """Stable reasons why an active game may or must stop."""

    CONTINUE = "continue"
    WIN = "win"
    AGENT_DONE = "agent-done"
    FAILURE = "failure"
    NO_LEGAL_ACTIONS = "no-legal-actions"
    GAME_ACTION_LIMIT = "game-action-limit"
    TOURNAMENT_ACTION_LIMIT = "tournament-action-limit"
    GAME_TIME_LIMIT = "game-time-limit"
    TOURNAMENT_PLAYABLE_TIME_LIMIT = "tournament-playable-time-limit"


class TournamentOutcome(StrEnum):
    """Measured terminal condition after every configured environment closes."""

    COMPLETE_RESERVE_PRESERVED = "complete-reserve-preserved"
    COMPLETE_RESERVE_CONSUMED = "complete-reserve-consumed"
    COMPLETE_CEILING_EXCEEDED = "complete-ceiling-exceeded"


@dataclass(frozen=True, slots=True)
class TournamentGovernorConfig:
    """Fail-closed limits for one scorecard-wide tournament run.

    ``total_effective_ceiling_seconds`` includes the protected reserve.  Agent
    play is bounded by ``ceiling - reserve``.  The minimum fallback slice and
    one total action are protected for every not-yet-started environment.
    """

    expected_environments: int
    total_effective_ceiling_seconds: float
    reserve_seconds: float
    minimum_fallback_seconds: float
    maximum_game_seconds: float
    maximum_actions_per_game: int
    maximum_total_actions: int
    history_capacity: int = 256
    fallback_coordinate: Coordinate = field(default_factory=lambda: Coordinate(32, 32))

    def __post_init__(self) -> None:
        for name in (
            "expected_environments",
            "maximum_actions_per_game",
            "maximum_total_actions",
            "history_capacity",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise CompetitionIntegrityError(f"{name} must be a positive integer")

        for name in (
            "total_effective_ceiling_seconds",
            "minimum_fallback_seconds",
            "maximum_game_seconds",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise CompetitionIntegrityError(f"{name} must be a finite positive number")
            normalized = float(value)
            if not math.isfinite(normalized) or normalized <= 0.0:
                raise CompetitionIntegrityError(f"{name} must be a finite positive number")
            object.__setattr__(self, name, normalized)

        reserve = self.reserve_seconds
        if isinstance(reserve, bool) or not isinstance(reserve, (int, float)):
            raise CompetitionIntegrityError("reserve_seconds must be a finite non-negative number")
        normalized_reserve = float(reserve)
        if not math.isfinite(normalized_reserve) or normalized_reserve < 0.0:
            raise CompetitionIntegrityError("reserve_seconds must be a finite non-negative number")
        object.__setattr__(self, "reserve_seconds", normalized_reserve)

        if normalized_reserve >= self.total_effective_ceiling_seconds:
            raise CompetitionIntegrityError(
                "reserve_seconds must be below total_effective_ceiling_seconds"
            )
        if self.maximum_game_seconds < self.minimum_fallback_seconds:
            raise CompetitionIntegrityError(
                "maximum_game_seconds must be at least minimum_fallback_seconds"
            )
        if self.playable_seconds < (self.minimum_fallback_seconds * self.expected_environments):
            raise CompetitionIntegrityError(
                "playable tournament time cannot protect the minimum fallback slice "
                "for every environment"
            )
        if self.maximum_total_actions < self.expected_environments:
            raise CompetitionIntegrityError(
                "maximum_total_actions must protect at least one action per environment"
            )
        if not isinstance(self.fallback_coordinate, Coordinate):
            raise CompetitionIntegrityError("fallback_coordinate must be a Coordinate")

    @property
    def playable_seconds(self) -> float:
        """Tournament seconds available before entering the protected reserve."""

        return self.total_effective_ceiling_seconds - self.reserve_seconds


@dataclass(frozen=True, slots=True)
class TournamentStartReceipt:
    sequence: int
    started_at_seconds: float
    playable_deadline_seconds: float
    effective_ceiling_deadline_seconds: float
    expected_environments: int
    maximum_total_actions: int


@dataclass(frozen=True, slots=True)
class GameAllocationReceipt:
    sequence: int
    game_id: str
    game_ordinal: int
    began_at_seconds: float
    deadline_seconds: float
    allocated_seconds: float
    action_limit: int
    environments_remaining_including_current: int
    tournament_playable_seconds_remaining_before: float
    protected_future_seconds: float
    protected_future_actions: int
    minimum_fallback_slice_used: bool


@dataclass(frozen=True, slots=True)
class ActionAccountingReceipt:
    sequence: int
    game_id: str
    action_ordinal: int
    requested_action: ActionRequest
    authorized_action: ActionRequest
    legal_actions: tuple[ActionName, ...]
    fallback_used: bool
    selected_value: float
    authorized_at_seconds: float
    elapsed_cost_seconds: float
    future_environment_count: int
    future_opportunity_cost_seconds: float
    future_opportunity_cost_per_environment_seconds: float
    future_opportunity_cost_actions: int
    game_seconds_remaining: float
    tournament_playable_seconds_remaining: float
    game_actions_remaining: int
    tournament_actions_remaining: int


@dataclass(frozen=True, slots=True)
class StopDecisionReceipt:
    sequence: int
    game_id: str
    observed_at_seconds: float
    reason: GovernorStopReason
    game_seconds_remaining: float
    tournament_playable_seconds_remaining: float
    game_actions_remaining: int
    tournament_actions_remaining: int

    @property
    def should_stop(self) -> bool:
        return self.reason is not GovernorStopReason.CONTINUE


@dataclass(frozen=True, slots=True)
class GameFinalReceipt:
    sequence: int
    game_id: str
    game_ordinal: int
    reason: GovernorStopReason
    began_at_seconds: float
    finalized_at_seconds: float
    allocated_seconds: float
    elapsed_seconds: float
    allocation_overrun_seconds: float
    actions_authorized: int
    fallback_actions: int
    selected_value_total: float
    elapsed_action_cost_total_seconds: float
    unassigned_tail_elapsed_seconds: float
    future_opportunity_cost_total_seconds: float
    future_opportunity_cost_total_actions: int
    reserve_remaining_seconds: float
    tournament_playable_seconds_remaining: float


@dataclass(frozen=True, slots=True)
class TournamentFinalReceipt:
    sequence: int
    outcome: TournamentOutcome
    started_at_seconds: float
    finalized_at_seconds: float
    elapsed_seconds: float
    expected_environments: int
    finalized_environments: int
    total_actions_authorized: int
    maximum_total_actions: int
    reserve_seconds: float
    reserve_remaining_seconds: float
    ceiling_remaining_seconds: float
    reserve_preserved: bool
    effective_ceiling_respected: bool
    selected_value_total: float
    future_opportunity_cost_total_seconds: float
    recent_history_receipts: int
    dropped_history_receipts: int
    games: tuple[GameFinalReceipt, ...]


type GovernorReceipt = (
    TournamentStartReceipt
    | GameAllocationReceipt
    | ActionAccountingReceipt
    | StopDecisionReceipt
    | GameFinalReceipt
    | TournamentFinalReceipt
)


@dataclass(slots=True)
class _ActiveGame:
    allocation: GameAllocationReceipt
    last_action_boundary_seconds: float
    actions_authorized: int = 0
    fallback_actions: int = 0
    selected_value_total: float = 0.0
    elapsed_action_cost_total_seconds: float = 0.0
    future_opportunity_cost_total_seconds: float = 0.0
    future_opportunity_cost_total_actions: int = 0


_RESOURCE_STOP_REASONS: Final[frozenset[GovernorStopReason]] = frozenset(
    {
        GovernorStopReason.GAME_ACTION_LIMIT,
        GovernorStopReason.TOURNAMENT_ACTION_LIMIT,
        GovernorStopReason.GAME_TIME_LIMIT,
        GovernorStopReason.TOURNAMENT_PLAYABLE_TIME_LIMIT,
    }
)


class TournamentGovernor:
    """Thread-safe, scorecard-wide budget authority with deterministic receipts."""

    def __init__(
        self,
        config: TournamentGovernorConfig,
        *,
        clock: MonotonicClock = time.monotonic,
    ) -> None:
        if not isinstance(config, TournamentGovernorConfig):
            raise CompetitionIntegrityError("config must be TournamentGovernorConfig")
        if not callable(clock):
            raise CompetitionIntegrityError("clock must be callable")
        self._config = config
        self._clock = clock
        self._lock = threading.RLock()
        self._history: deque[GovernorReceipt] = deque(maxlen=config.history_capacity)
        self._dropped_history_receipts = 0
        self._sequence = 0
        self._last_clock_value: float | None = None
        self._started_at_seconds: float | None = None
        self._playable_deadline_seconds: float | None = None
        self._effective_ceiling_deadline_seconds: float | None = None
        self._start_receipt: TournamentStartReceipt | None = None
        self._active: _ActiveGame | None = None
        self._begun_game_ids: set[str] = set()
        self._game_receipts: list[GameFinalReceipt] = []
        self._total_actions_authorized = 0
        self._selected_value_total = 0.0
        self._future_opportunity_cost_total_seconds = 0.0
        self._final_receipt: TournamentFinalReceipt | None = None

    @property
    def config(self) -> TournamentGovernorConfig:
        return self._config

    @property
    def started(self) -> bool:
        with self._lock:
            return self._start_receipt is not None

    @property
    def finalized(self) -> bool:
        with self._lock:
            return self._final_receipt is not None

    @property
    def active_game_id(self) -> str | None:
        with self._lock:
            if self._active is None:
                return None
            return self._active.allocation.game_id

    @property
    def total_actions_authorized(self) -> int:
        with self._lock:
            return self._total_actions_authorized

    @property
    def finalized_game_receipts(self) -> tuple[GameFinalReceipt, ...]:
        with self._lock:
            return tuple(self._game_receipts)

    @property
    def receipt_history(self) -> tuple[GovernorReceipt, ...]:
        with self._lock:
            return tuple(self._history)

    @property
    def dropped_history_receipts(self) -> int:
        with self._lock:
            return self._dropped_history_receipts

    def _now(self) -> float:
        try:
            raw = self._clock()
        except Exception as error:
            raise CompetitionIntegrityError("monotonic clock failed") from error
        if isinstance(raw, bool) or not isinstance(raw, (int, float)):
            raise CompetitionIntegrityError("monotonic clock must return a finite number")
        now = float(raw)
        if not math.isfinite(now):
            raise CompetitionIntegrityError("monotonic clock must return a finite number")
        if self._last_clock_value is not None and now < self._last_clock_value:
            raise CompetitionIntegrityError("monotonic clock moved backwards")
        self._last_clock_value = now
        return now

    def _next_sequence(self) -> int:
        self._sequence += 1
        return self._sequence

    def _remember(self, receipt: GovernorReceipt) -> None:
        if len(self._history) == self._config.history_capacity:
            self._dropped_history_receipts += 1
        self._history.append(receipt)

    def _require_started(self) -> tuple[float, float, float]:
        if (
            self._started_at_seconds is None
            or self._playable_deadline_seconds is None
            or self._effective_ceiling_deadline_seconds is None
        ):
            raise CompetitionIntegrityError("tournament has not started")
        return (
            self._started_at_seconds,
            self._playable_deadline_seconds,
            self._effective_ceiling_deadline_seconds,
        )

    def _require_mutable_tournament(self) -> tuple[float, float, float]:
        timing = self._require_started()
        if self._final_receipt is not None:
            raise CompetitionIntegrityError("tournament is already finalized")
        return timing

    @staticmethod
    def _validate_game_id(game_id: str) -> None:
        if not isinstance(game_id, str) or not game_id or game_id.strip() != game_id:
            raise CompetitionIntegrityError("game_id must be a non-empty canonical string")

    def _require_active(self, game_id: str) -> _ActiveGame:
        self._validate_game_id(game_id)
        active = self._active
        if active is None:
            raise CompetitionIntegrityError("no game is active")
        if active.allocation.game_id != game_id:
            raise CompetitionIntegrityError(
                f"active game mismatch: expected {active.allocation.game_id!r}, got {game_id!r}"
            )
        return active

    def _remaining_reserve(self, now: float) -> float:
        started, _, _ = self._require_started()
        reserve_consumed = max(0.0, (now - started) - self._config.playable_seconds)
        return max(0.0, self._config.reserve_seconds - reserve_consumed)

    def _stop_reason_at(self, active: _ActiveGame, now: float) -> GovernorStopReason:
        _, playable_deadline, _ = self._require_started()
        if now >= playable_deadline:
            return GovernorStopReason.TOURNAMENT_PLAYABLE_TIME_LIMIT
        if now >= active.allocation.deadline_seconds:
            return GovernorStopReason.GAME_TIME_LIMIT
        if self._total_actions_authorized >= self._config.maximum_total_actions:
            return GovernorStopReason.TOURNAMENT_ACTION_LIMIT
        if active.actions_authorized >= active.allocation.action_limit:
            return GovernorStopReason.GAME_ACTION_LIMIT
        return GovernorStopReason.CONTINUE

    @staticmethod
    def _normalize_legal_actions(legal_actions: Iterable[ActionName]) -> tuple[ActionName, ...]:
        try:
            supplied = tuple(legal_actions)
        except TypeError as error:
            raise CompetitionIntegrityError("legal_actions must be iterable") from error
        if not supplied:
            raise CompetitionIntegrityError("legal_actions must contain at least one action")
        if any(not isinstance(action, ActionName) for action in supplied):
            raise CompetitionIntegrityError("legal_actions must contain only ActionName values")
        if len(set(supplied)) != len(supplied):
            raise CompetitionIntegrityError("legal_actions must not contain duplicates")
        supplied_set = set(supplied)
        return tuple(action for action in _FALLBACK_ORDER if action in supplied_set)

    def _fallback_action(self, legal_actions: tuple[ActionName, ...]) -> ActionRequest:
        selected = legal_actions[0]
        if selected is ActionName.ACTION6:
            return ActionRequest(selected, self._config.fallback_coordinate)
        return ActionRequest(selected)

    def start_tournament(
        self, *, started_at_seconds: float | None = None
    ) -> TournamentStartReceipt:
        """Start once, optionally anchored to an earlier notebook boundary."""

        with self._lock:
            if self._start_receipt is not None:
                raise CompetitionIntegrityError("tournament was already started")
            if self._final_receipt is not None:
                raise CompetitionIntegrityError("finalized tournament cannot be restarted")
            now = self._now()
            if started_at_seconds is None:
                started = now
            elif (
                isinstance(started_at_seconds, bool)
                or not isinstance(started_at_seconds, (int, float))
                or not math.isfinite(started_at_seconds)
                or float(started_at_seconds) > now
            ):
                raise CompetitionIntegrityError(
                    "tournament start anchor must be finite and no later than the current clock"
                )
            else:
                started = float(started_at_seconds)
            self._started_at_seconds = started
            self._playable_deadline_seconds = started + self._config.playable_seconds
            self._effective_ceiling_deadline_seconds = (
                started + self._config.total_effective_ceiling_seconds
            )
            receipt = TournamentStartReceipt(
                sequence=self._next_sequence(),
                started_at_seconds=started,
                playable_deadline_seconds=self._playable_deadline_seconds,
                effective_ceiling_deadline_seconds=self._effective_ceiling_deadline_seconds,
                expected_environments=self._config.expected_environments,
                maximum_total_actions=self._config.maximum_total_actions,
            )
            self._start_receipt = receipt
            self._remember(receipt)
            return receipt

    def begin_game(self, game_id: str) -> GameAllocationReceipt:
        """Allocate a bounded dynamic slice while protecting all future games."""

        with self._lock:
            self._validate_game_id(game_id)
            _, playable_deadline, _ = self._require_mutable_tournament()
            if self._active is not None:
                raise CompetitionIntegrityError(
                    f"cannot begin {game_id!r} while {self._active.allocation.game_id!r} is active"
                )
            if game_id in self._begun_game_ids:
                raise CompetitionIntegrityError(f"game {game_id!r} was already begun")
            finalized = len(self._game_receipts)
            if finalized >= self._config.expected_environments:
                raise CompetitionIntegrityError("configured environment count is already exhausted")

            now = self._now()
            remaining_environments = self._config.expected_environments - finalized
            remaining_playable = max(0.0, playable_deadline - now)
            future_count = remaining_environments - 1
            protected_future_seconds = self._config.minimum_fallback_seconds * future_count
            fair_share = remaining_playable / remaining_environments
            feasible_current = max(0.0, remaining_playable - protected_future_seconds)
            if remaining_playable >= (
                self._config.minimum_fallback_seconds * remaining_environments
            ):
                allocated_seconds = min(
                    self._config.maximum_game_seconds,
                    max(self._config.minimum_fallback_seconds, fair_share),
                    feasible_current,
                )
            else:
                # A prior call may overrun its slice because environment steps are
                # external and cannot be pre-empted safely.  Still register every
                # remaining environment: a zero/short allocation makes is_done()
                # stop it deterministically instead of preventing its one make.
                allocated_seconds = min(self._config.maximum_game_seconds, fair_share)

            remaining_actions = self._config.maximum_total_actions - self._total_actions_authorized
            protected_future_actions = future_count
            if remaining_actions >= remaining_environments:
                action_limit = min(
                    self._config.maximum_actions_per_game,
                    remaining_actions - protected_future_actions,
                )
            else:
                action_limit = min(
                    self._config.maximum_actions_per_game,
                    max(0, remaining_actions // remaining_environments),
                )

            receipt = GameAllocationReceipt(
                sequence=self._next_sequence(),
                game_id=game_id,
                game_ordinal=finalized + 1,
                began_at_seconds=now,
                deadline_seconds=now + allocated_seconds,
                allocated_seconds=allocated_seconds,
                action_limit=action_limit,
                environments_remaining_including_current=remaining_environments,
                tournament_playable_seconds_remaining_before=remaining_playable,
                protected_future_seconds=protected_future_seconds,
                protected_future_actions=protected_future_actions,
                minimum_fallback_slice_used=(
                    allocated_seconds <= self._config.minimum_fallback_seconds
                ),
            )
            self._active = _ActiveGame(
                allocation=receipt,
                last_action_boundary_seconds=now,
            )
            self._begun_game_ids.add(game_id)
            self._remember(receipt)
            return receipt

    def authorize_action(
        self,
        game_id: str,
        requested_action: ActionRequest,
        legal_actions: Iterable[ActionName],
        *,
        selected_value: float,
        force_fallback: bool = False,
    ) -> ActionAccountingReceipt:
        """Authorize one legal action and account for its shared opportunity cost.

        Elapsed cost is the monotonic interval since the prior authorization
        boundary (or game start for the first action).  The final tail is kept
        separately in :class:`GameFinalReceipt`, so no time is hidden.
        """

        with self._lock:
            self._require_mutable_tournament()
            active = self._require_active(game_id)
            if not isinstance(requested_action, ActionRequest):
                raise CompetitionIntegrityError("requested_action must be ActionRequest")
            if not isinstance(force_fallback, bool):
                raise CompetitionIntegrityError("force_fallback must be a boolean")
            if isinstance(selected_value, bool) or not isinstance(selected_value, (int, float)):
                raise CompetitionIntegrityError("selected_value must be finite")
            normalized_value = float(selected_value)
            if not math.isfinite(normalized_value):
                raise CompetitionIntegrityError("selected_value must be finite")
            legal = self._normalize_legal_actions(legal_actions)
            now = self._now()
            stop_reason = self._stop_reason_at(active, now)
            if stop_reason is not GovernorStopReason.CONTINUE:
                raise CompetitionIntegrityError(
                    f"action authorization denied after {stop_reason.value}"
                )

            fallback_used = force_fallback or requested_action.name not in legal
            authorized = self._fallback_action(legal) if fallback_used else requested_action
            elapsed_cost = now - active.last_action_boundary_seconds
            future_environment_count = (
                self._config.expected_environments - len(self._game_receipts) - 1
            )
            opportunity_seconds = elapsed_cost if future_environment_count > 0 else 0.0
            opportunity_per_environment = (
                opportunity_seconds / future_environment_count
                if future_environment_count > 0
                else 0.0
            )
            opportunity_actions = 1 if future_environment_count > 0 else 0

            active.actions_authorized += 1
            active.fallback_actions += int(fallback_used)
            active.selected_value_total += normalized_value
            active.elapsed_action_cost_total_seconds += elapsed_cost
            active.future_opportunity_cost_total_seconds += opportunity_seconds
            active.future_opportunity_cost_total_actions += opportunity_actions
            active.last_action_boundary_seconds = now
            self._total_actions_authorized += 1
            self._selected_value_total += normalized_value
            self._future_opportunity_cost_total_seconds += opportunity_seconds

            _, playable_deadline, _ = self._require_started()
            receipt = ActionAccountingReceipt(
                sequence=self._next_sequence(),
                game_id=game_id,
                action_ordinal=active.actions_authorized,
                requested_action=requested_action,
                authorized_action=authorized,
                legal_actions=legal,
                fallback_used=fallback_used,
                selected_value=normalized_value,
                authorized_at_seconds=now,
                elapsed_cost_seconds=elapsed_cost,
                future_environment_count=future_environment_count,
                future_opportunity_cost_seconds=opportunity_seconds,
                future_opportunity_cost_per_environment_seconds=(opportunity_per_environment),
                future_opportunity_cost_actions=opportunity_actions,
                game_seconds_remaining=max(0.0, active.allocation.deadline_seconds - now),
                tournament_playable_seconds_remaining=max(0.0, playable_deadline - now),
                game_actions_remaining=active.allocation.action_limit - active.actions_authorized,
                tournament_actions_remaining=(
                    self._config.maximum_total_actions - self._total_actions_authorized
                ),
            )
            self._remember(receipt)
            return receipt

    def stop_decision(self, game_id: str) -> StopDecisionReceipt:
        """Return the deterministic resource stop decision for the active game."""

        with self._lock:
            self._require_mutable_tournament()
            active = self._require_active(game_id)
            now = self._now()
            reason = self._stop_reason_at(active, now)
            _, playable_deadline, _ = self._require_started()
            receipt = StopDecisionReceipt(
                sequence=self._next_sequence(),
                game_id=game_id,
                observed_at_seconds=now,
                reason=reason,
                game_seconds_remaining=max(0.0, active.allocation.deadline_seconds - now),
                tournament_playable_seconds_remaining=max(0.0, playable_deadline - now),
                game_actions_remaining=max(
                    0, active.allocation.action_limit - active.actions_authorized
                ),
                tournament_actions_remaining=max(
                    0, self._config.maximum_total_actions - self._total_actions_authorized
                ),
            )
            self._remember(receipt)
            return receipt

    def finalize_game(
        self,
        game_id: str,
        *,
        reason: GovernorStopReason,
    ) -> GameFinalReceipt:
        """Finalize the active game exactly once with a truthful terminal reason."""

        with self._lock:
            self._require_mutable_tournament()
            active = self._require_active(game_id)
            if not isinstance(reason, GovernorStopReason) or reason is GovernorStopReason.CONTINUE:
                raise CompetitionIntegrityError("final game reason must be a terminal stop reason")
            now = self._now()
            measured_resource_reason = self._stop_reason_at(active, now)
            if measured_resource_reason is not GovernorStopReason.CONTINUE and reason not in {
                measured_resource_reason,
                GovernorStopReason.WIN,
            }:
                raise CompetitionIntegrityError(
                    f"claimed stop reason {reason.value!r} does not honor measured "
                    f"reason {measured_resource_reason.value!r}"
                )
            if reason in _RESOURCE_STOP_REASONS and reason is not measured_resource_reason:
                raise CompetitionIntegrityError(
                    f"claimed stop reason {reason.value!r} does not match measured "
                    f"reason {measured_resource_reason.value!r}"
                )

            started, playable_deadline, _ = self._require_started()
            elapsed = now - active.allocation.began_at_seconds
            tail = now - active.last_action_boundary_seconds
            receipt = GameFinalReceipt(
                sequence=self._next_sequence(),
                game_id=game_id,
                game_ordinal=active.allocation.game_ordinal,
                reason=reason,
                began_at_seconds=active.allocation.began_at_seconds,
                finalized_at_seconds=now,
                allocated_seconds=active.allocation.allocated_seconds,
                elapsed_seconds=elapsed,
                allocation_overrun_seconds=max(0.0, elapsed - active.allocation.allocated_seconds),
                actions_authorized=active.actions_authorized,
                fallback_actions=active.fallback_actions,
                selected_value_total=active.selected_value_total,
                elapsed_action_cost_total_seconds=(active.elapsed_action_cost_total_seconds),
                unassigned_tail_elapsed_seconds=tail,
                future_opportunity_cost_total_seconds=(
                    active.future_opportunity_cost_total_seconds
                ),
                future_opportunity_cost_total_actions=(
                    active.future_opportunity_cost_total_actions
                ),
                reserve_remaining_seconds=self._remaining_reserve(now),
                tournament_playable_seconds_remaining=max(0.0, playable_deadline - now),
            )
            if now < started:
                raise CompetitionIntegrityError("game finalized before tournament start")
            self._game_receipts.append(receipt)
            self._active = None
            self._remember(receipt)
            return receipt

    def finalize_tournament(self) -> TournamentFinalReceipt:
        """Seal the tournament only after every configured game was finalized."""

        with self._lock:
            started, playable_deadline, effective_deadline = self._require_mutable_tournament()
            if self._active is not None:
                raise CompetitionIntegrityError(
                    f"cannot finalize tournament while {self._active.allocation.game_id!r} is active"
                )
            finalized_count = len(self._game_receipts)
            begun_count = len(self._begun_game_ids)
            expected = self._config.expected_environments
            if begun_count != expected or finalized_count != expected:
                raise CompetitionIntegrityError(
                    "tournament environment count mismatch: "
                    f"expected={expected}, begun={begun_count}, finalized={finalized_count}"
                )

            now = self._now()
            elapsed = now - started
            reserve_preserved = now <= playable_deadline
            ceiling_respected = now <= effective_deadline
            if not ceiling_respected:
                outcome = TournamentOutcome.COMPLETE_CEILING_EXCEEDED
            elif not reserve_preserved:
                outcome = TournamentOutcome.COMPLETE_RESERVE_CONSUMED
            else:
                outcome = TournamentOutcome.COMPLETE_RESERVE_PRESERVED
            will_drop = int(len(self._history) == self._config.history_capacity)
            receipt = TournamentFinalReceipt(
                sequence=self._next_sequence(),
                outcome=outcome,
                started_at_seconds=started,
                finalized_at_seconds=now,
                elapsed_seconds=elapsed,
                expected_environments=expected,
                finalized_environments=finalized_count,
                total_actions_authorized=self._total_actions_authorized,
                maximum_total_actions=self._config.maximum_total_actions,
                reserve_seconds=self._config.reserve_seconds,
                reserve_remaining_seconds=self._remaining_reserve(now),
                ceiling_remaining_seconds=max(0.0, effective_deadline - now),
                reserve_preserved=reserve_preserved,
                effective_ceiling_respected=ceiling_respected,
                selected_value_total=self._selected_value_total,
                future_opportunity_cost_total_seconds=(self._future_opportunity_cost_total_seconds),
                recent_history_receipts=min(self._config.history_capacity, len(self._history) + 1),
                dropped_history_receipts=self._dropped_history_receipts + will_drop,
                games=tuple(self._game_receipts),
            )
            self._final_receipt = receipt
            self._remember(receipt)
            return receipt


__all__ = [
    "ActionAccountingReceipt",
    "GameAllocationReceipt",
    "GameFinalReceipt",
    "GovernorReceipt",
    "GovernorStopReason",
    "MonotonicClock",
    "StopDecisionReceipt",
    "TournamentFinalReceipt",
    "TournamentGovernor",
    "TournamentGovernorConfig",
    "TournamentOutcome",
    "TournamentStartReceipt",
]
