"""Exact official ARC-AGI-3 adapter around the persistent ARC3 controller."""

from __future__ import annotations

import json
import math
import os
import signal
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, replace
from enum import StrEnum
from importlib import import_module
from pathlib import Path
from typing import ClassVar, cast

from arc3.adapters import Observation, validate_action_request
from arc3.adapters.normalization import normalize_frame_data
from arc3.competition import GovernorStopReason, TournamentGovernor
from arc3.competition_runtime import FROZEN_COMPETITION_RUNTIME
from arc3.config import ARC3Config, derive_seed
from arc3.errors import CompetitionIntegrityError, ConfigurationError
from arc3.policy import ARC3Controller, ControllerPhase, ControllerPreset, RunContext
from arc3.trace.canonical import normalize_json, sha256_json
from arc3.types import (
    ActionName,
    ActionRequest,
    Coordinate,
    EnvironmentMode,
    ExecutionMode,
    GameStateName,
    JSONValue,
)


class _FallbackGameState(StrEnum):
    NOT_PLAYED = "NOT_PLAYED"
    NOT_FINISHED = "NOT_FINISHED"
    WIN = "WIN"
    GAME_OVER = "GAME_OVER"


class _FallbackGameAction(StrEnum):
    RESET = "RESET"
    ACTION1 = "ACTION1"
    ACTION2 = "ACTION2"
    ACTION3 = "ACTION3"
    ACTION4 = "ACTION4"
    ACTION5 = "ACTION5"
    ACTION6 = "ACTION6"
    ACTION7 = "ACTION7"

    def is_complex(self) -> bool:
        return self is _FallbackGameAction.ACTION6

    def set_data(self, data: dict[str, int]) -> None:
        self.action_data = dict(data)


class _FallbackAgent:
    """Import-only stand-in used when the optional framework is unavailable."""

    MAX_ACTIONS: ClassVar[int] = FROZEN_COMPETITION_RUNTIME.max_actions

    def __init__(self, *args: object, **kwargs: object) -> None:
        del args
        self.game_id = str(kwargs.get("game_id", "offline"))
        self.agent_name = str(kwargs.get("agent_name", type(self).__name__.lower()))
        self.action_counter = 0

    @property
    def name(self) -> str:
        return self.agent_name


class _BoundedTournamentStop(RuntimeError):
    """Internal loop signal: a measured governor boundary forbids another action."""


class _ActionDeadlineExpired(TimeoutError):
    """A competition call exceeded its explicit local wall-clock slice."""


def _bounded_call[T](call: Callable[[], T], *, seconds: float, boundary: str) -> T:
    """Interrupt a blocking competition call on the Linux main thread."""

    if not math.isfinite(seconds) or seconds <= 0.0:
        raise _ActionDeadlineExpired(f"{boundary} has no remaining wall-clock budget")
    if os.name != "posix" or threading.current_thread() is not threading.main_thread():
        return call()
    setitimer = getattr(signal, "setitimer", None)
    getitimer = getattr(signal, "getitimer", None)
    alarm_signal = getattr(signal, "SIGALRM", None)
    timer_kind = getattr(signal, "ITIMER_REAL", None)
    if (
        not callable(setitimer)
        or not callable(getitimer)
        or alarm_signal is None
        or timer_kind is None
    ):
        raise RuntimeError("Linux competition runtime has no interruptible wall-clock timer")
    prior_timer = getitimer(timer_kind)
    if prior_timer[0] > 0.0 or prior_timer[1] > 0.0:
        raise RuntimeError("competition call cannot replace an existing process alarm")
    prior_handler = signal.getsignal(alarm_signal)

    def expire(_signum: int, _frame: object) -> None:
        raise _ActionDeadlineExpired(f"{boundary} exceeded {seconds:.6f} seconds")

    signal.signal(alarm_signal, expire)
    setitimer(timer_kind, seconds)
    try:
        return call()
    finally:
        setitimer(timer_kind, 0.0)
        signal.signal(alarm_signal, prior_handler)


def _optional_attribute(module_name: str, attribute: str, fallback: object) -> object:
    try:
        module = import_module(module_name)
    except (ImportError, ModuleNotFoundError):
        return fallback
    return getattr(module, attribute, fallback)


_AgentBase = _optional_attribute("agents.agent", "Agent", _FallbackAgent)
GameAction = _optional_attribute("arcengine", "GameAction", _FallbackGameAction)
GameState = _optional_attribute("arcengine", "GameState", _FallbackGameState)


def _enum_name(value: object) -> str:
    name = getattr(value, "name", None)
    if isinstance(name, str):
        return name.upper()
    raw = getattr(value, "value", value)
    return str(raw).upper()


def _enum_member(enum_type: object, name: str) -> object:
    member = getattr(enum_type, name, None)
    if member is None:
        raise RuntimeError(f"official action vocabulary is missing {name}")
    return member


def _parse_root_seed(raw_seed: object) -> int:
    if raw_seed is None:
        raw_seed = os.environ.get("ARC3_SEED", "0")
    try:
        seed = int(str(raw_seed))
    except ValueError as error:
        raise ConfigurationError("ARC3_SEED must be an integer") from error
    if not -(2**63) <= seed < 2**63:
        raise ConfigurationError("ARC3_SEED must be a signed 64-bit integer")
    return seed


@dataclass(frozen=True, slots=True)
class _FrameworkActionRequest:
    """Instance-local payload paired with the pinned action vocabulary."""

    member: object
    payload_items: tuple[tuple[str, object], ...]

    @property
    def name(self) -> str:
        name = getattr(self.member, "name", None)
        if not isinstance(name, str):
            raise RuntimeError("official action member has no string name")
        return name

    def payload(self) -> dict[str, object]:
        return dict(self.payload_items)


def _instance_local_payload(member: object, action: ActionRequest) -> dict[str, object]:
    values: dict[str, object] = {}
    if action.coordinate is not None:
        values.update({"x": action.coordinate.x, "y": action.coordinate.y})
    action_type = getattr(member, "action_type", None)
    if action_type is None:
        return values
    if not callable(action_type):
        raise RuntimeError("official action member has a non-callable action type")
    action_data = action_type(**values)
    dumper = getattr(action_data, "model_dump", None)
    if not callable(dumper):
        raise RuntimeError("official action data cannot be serialized")
    serialized = dumper()
    if not isinstance(serialized, dict) or not all(isinstance(key, str) for key in serialized):
        raise RuntimeError("official action data serialization has the wrong shape")
    return serialized


def _translate_action(action: ActionRequest) -> _FrameworkActionRequest:
    member = _enum_member(GameAction, action.name.value)
    payload = _instance_local_payload(member, action)
    return _FrameworkActionRequest(member, tuple(sorted(payload.items())))


def _normalized_dict(value: object) -> dict[str, JSONValue]:
    normalized = normalize_json(value)
    if not isinstance(normalized, dict):
        raise RuntimeError("runtime receipt did not normalize to an object")
    return normalized


def _safe_action_for(legal: tuple[ActionName, ...]) -> ActionRequest:
    if not legal:
        raise RuntimeError("no legal action is available for bounded fallback")
    name = legal[0]
    return ActionRequest(name, Coordinate(32, 32) if name is ActionName.ACTION6 else None)


class MyAgent(_AgentBase):  # type: ignore[misc,valid-type]
    """Official adapter with one shared scorecard-wide resource governor."""

    MAX_ACTIONS = FROZEN_COMPETITION_RUNTIME.max_actions
    _tournament_lock: ClassVar[threading.RLock] = threading.RLock()
    _governor: ClassVar[TournamentGovernor | None] = None
    _expected_games: ClassVar[tuple[str, ...]] = ()
    _working_root: ClassVar[Path | None] = None
    _failure_receipts: ClassVar[list[dict[str, JSONValue]]] = []
    _final_tournament_receipt: ClassVar[dict[str, JSONValue] | None] = None

    @classmethod
    def configure_tournament(
        cls,
        game_ids: Sequence[str],
        working_root: str | Path,
        *,
        clock: Callable[[], float] | None = None,
        notebook_started_at_seconds: float | None = None,
    ) -> dict[str, JSONValue]:
        """Bind the exact discovered environment set before Swarm construction."""

        frozen_games = tuple(game_ids)
        if (
            not frozen_games
            or any(not isinstance(game_id, str) or not game_id.strip() for game_id in frozen_games)
            or len(set(frozen_games)) != len(frozen_games)
            or frozen_games != tuple(sorted(frozen_games))
        ):
            raise ConfigurationError(
                "tournament games must be unique non-empty IDs in sorted order"
            )
        with cls._tournament_lock:
            if cls._governor is not None and not cls._governor.finalized:
                raise ConfigurationError("an unfinished tournament governor is already configured")
            root = Path(working_root).resolve()
            receipt_root = root / "arc3-runtime-receipts"
            receipt_root.mkdir(parents=True, exist_ok=True)
            governor = TournamentGovernor(
                FROZEN_COMPETITION_RUNTIME.governor_config(len(frozen_games)),
                clock=time.monotonic if clock is None else clock,
            )
            start = governor.start_tournament(started_at_seconds=notebook_started_at_seconds)
            cls._governor = governor
            cls._expected_games = frozen_games
            cls._working_root = root
            cls._failure_receipts = []
            cls._final_tournament_receipt = None
            receipt = _normalized_dict(asdict(start))
            cls._write_receipt("tournament-start.json", receipt)
            return receipt

    @classmethod
    def _require_governor(cls) -> TournamentGovernor:
        governor = cls._governor
        if governor is None:
            raise ConfigurationError("MyAgent tournament governor was not configured")
        return governor

    @classmethod
    def _write_receipt(cls, name: str, payload: dict[str, JSONValue]) -> None:
        root = cls._working_root
        if root is None:
            raise RuntimeError("competition working root is unavailable")
        path = root / "arc3-runtime-receipts" / name
        path.write_text(
            json.dumps(payload, ensure_ascii=False, allow_nan=False, indent=2, sort_keys=True)
            + "\n",
            encoding="utf-8",
            newline="\n",
        )

    @classmethod
    def failure_receipts(cls) -> tuple[dict[str, JSONValue], ...]:
        with cls._tournament_lock:
            return tuple(dict(item) for item in cls._failure_receipts)

    @classmethod
    def finalize_tournament(cls) -> dict[str, JSONValue]:
        """Seal all residual games and the single tournament receipt."""

        with cls._tournament_lock:
            if cls._final_tournament_receipt is not None:
                return dict(cls._final_tournament_receipt)
            governor = cls._require_governor()
            active = governor.active_game_id
            if active is not None:
                stop = governor.stop_decision(active)
                governor.finalize_game(
                    active,
                    reason=stop.reason if stop.should_stop else GovernorStopReason.FAILURE,
                )
            finalized = {item.game_id for item in governor.finalized_game_receipts}
            for game_id in cls._expected_games:
                if game_id in finalized:
                    continue
                governor.begin_game(game_id)
                stop = governor.stop_decision(game_id)
                governor.finalize_game(
                    game_id,
                    reason=stop.reason if stop.should_stop else GovernorStopReason.FAILURE,
                )
            receipt = _normalized_dict(asdict(governor.finalize_tournament()))
            cls._final_tournament_receipt = receipt
            cls._write_receipt("tournament-final.json", receipt)
            return dict(receipt)

    def __init__(self, *args: object, **kwargs: object) -> None:
        forwarded = dict(kwargs)
        self._root_seed = _parse_root_seed(forwarded.pop("seed", forwarded.pop("root_seed", None)))
        super().__init__(*args, **forwarded)
        self.action_counter = 0
        self._controller: ARC3Controller | None = None
        self._controller_failed = False
        self._game_started = False
        self._game_finalized = False
        self._authorized_actions = 0
        with self._tournament_lock:
            self._require_governor()
            if str(self.game_id) not in self._expected_games:
                raise ConfigurationError("agent game is absent from the configured tournament")

    @property
    def name(self) -> str:
        base_name = getattr(super(), "name", type(self).__name__.lower())
        return f"{base_name}.arc3-controller-v2"

    def _ensure_game_started(self) -> None:
        if self._game_started:
            return
        with self._tournament_lock:
            governor = self._require_governor()
            completed = len(governor.finalized_game_receipts)
            if completed >= len(self._expected_games) or self._expected_games[completed] != str(
                self.game_id
            ):
                raise ConfigurationError("sequential tournament game order changed")
            governor.begin_game(str(self.game_id))
            self._game_started = True

    def _record_failure(self, *, boundary: str, classification: str, error: Exception) -> None:
        allowed = {
            "perception",
            "goal inference",
            "rule learning",
            "planning",
            "execution",
            "platform",
            "budget exhaustion",
        }
        if classification not in allowed:
            raise RuntimeError("unknown failure classification")
        with self._tournament_lock:
            receipt: dict[str, JSONValue] = {
                "boundary": boundary,
                "classification": classification,
                "error_type": type(error).__name__,
                "game_id": str(self.game_id),
                "sequence": len(self._failure_receipts) + 1,
            }
            if self._controller is not None:
                compact = self._controller.compact_trace_projection
                receipt["compact_trace_events"] = len(compact)
                receipt["compact_trace_tail_hash"] = (
                    cast(str, compact[-1]["event_hash"]) if compact else None
                )
            self._failure_receipts.append(receipt)
            identity = sha256_json(
                {
                    "boundary": boundary,
                    "game_id": str(self.game_id),
                    "sequence": receipt["sequence"],
                }
            ).removeprefix("sha256:")[:16]
            self._write_receipt(f"failure-{identity}.json", receipt)

    def _finalize_game(self, reason: GovernorStopReason) -> None:
        if self._game_finalized:
            return
        with self._tournament_lock:
            governor = self._require_governor()
            if self._game_started and governor.active_game_id == str(self.game_id):
                measured = governor.stop_decision(str(self.game_id))
                effective_reason = (
                    measured.reason
                    if measured.should_stop and reason is not GovernorStopReason.WIN
                    else reason
                )
                receipt = _normalized_dict(
                    asdict(governor.finalize_game(str(self.game_id), reason=effective_reason))
                )
                identity = sha256_json({"game_id": str(self.game_id)}).removeprefix("sha256:")[:16]
                self._write_receipt(f"game-{identity}.json", receipt)
            self._game_finalized = True
        if self._controller is not None:
            try:
                _bounded_call(
                    self._controller.close,
                    seconds=30.0,
                    boundary="controller-finalize",
                )
            except Exception as error:
                self._record_failure(
                    boundary="controller-finalize",
                    classification="execution",
                    error=error,
                )
                self._controller_failed = True

    def _close_failed_controller(self) -> None:
        if self._controller is None:
            return
        try:
            _bounded_call(
                self._controller.close,
                seconds=30.0,
                boundary="controller-failure-finalize",
            )
        except Exception as error:
            self._record_failure(
                boundary="controller-failure-finalize",
                classification="execution",
                error=error,
            )

    def is_done(self, frames: list[object], latest_frame: object) -> bool:
        del frames
        if self._game_finalized:
            return True
        self._ensure_game_started()
        if _enum_name(getattr(latest_frame, "state", "UNKNOWN")) == "WIN":
            self._finalize_game(GovernorStopReason.WIN)
            return True
        stop = self._require_governor().stop_decision(str(self.game_id))
        if stop.should_stop:
            self._finalize_game(stop.reason)
            return True
        return False

    def _start_controller(self, observation_game_id: str) -> ARC3Controller:
        derived_seed = derive_seed(self._root_seed, "official-wrapper") & ((1 << 63) - 1)
        identity = sha256_json(
            {"game_id": observation_game_id, "seed": derived_seed, "scope": "official-wrapper-v2"}
        ).removeprefix("sha256:")[:16]
        root = self._working_root
        if root is None:
            raise ConfigurationError("competition working root is unavailable")
        runtime_root = root / "arc3-agent-state" / identity
        runtime_root.mkdir(parents=True, exist_ok=True)
        config = ARC3Config(
            mode=EnvironmentMode.COMPETITION,
            execution_mode=ExecutionMode.COMPETITION_BOUNDED,
            seed=derived_seed,
            network_enabled=False,
            profile="competition-bounded-v2",
            trace_root=str(runtime_root / "trace"),
            artifact_root=str(runtime_root / "artifacts"),
            budgets=FROZEN_COMPETITION_RUNTIME.budgets(),
            runtime_policy=FROZEN_COMPETITION_RUNTIME.runtime_policy(),
        )
        controller = ARC3Controller(ControllerPreset.COMPETITION)
        controller.reset(
            RunContext(
                run_id=f"agent-run-{identity}",
                episode_id=f"agent-episode-{identity}",
                game_id=observation_game_id,
                trace_root=runtime_root / "trace",
                checkpoint_root=runtime_root / "checkpoints",
                config=config,
                git_commit=os.environ.get("ARC3_GIT_COMMIT", "packaged-source"),
                source_kind="official-agent-wrapper",
                source_version="0.2",
            )
        )
        return controller

    @staticmethod
    def _legal_actions(observation: Observation) -> tuple[ActionName, ...]:
        if observation.state in {GameStateName.NOT_PLAYED, GameStateName.GAME_OVER}:
            return (ActionName.RESET,)
        if observation.state in {GameStateName.WIN, GameStateName.UNKNOWN}:
            return ()
        return observation.available_actions

    def _controller_request(self, observation: Observation) -> tuple[ActionRequest, float]:
        if self._controller is None:
            self._controller = self._start_controller(str(observation.game_id))
            self._controller.observe(observation)
        elif self._controller.phase is ControllerPhase.AWAITING_CONSEQUENCE:
            self._controller.apply_consequence(observation)
        elif self._controller.phase is ControllerPhase.NEW:
            self._controller.observe(observation)
        decision = self._controller.choose_action()
        selected_value = next(
            (
                candidate.utility
                for candidate in decision.alternatives
                if candidate.action == decision.action
            ),
            0.0,
        )
        return decision.action, selected_value

    def choose_action(self, frames: list[object], latest_frame: object) -> object:
        """Select, govern, and translate one action under the exact interface."""

        del frames
        self._ensure_game_started()
        observation = replace(normalize_frame_data(latest_frame), returned_action=None)
        legal = self._legal_actions(observation)
        if not legal:
            error = RuntimeError("observation exposes no legal action")
            self._record_failure(
                boundary="legal-action-surface", classification="platform", error=error
            )
            self._finalize_game(GovernorStopReason.NO_LEGAL_ACTIONS)
            raise error
        if observation.full_reset and self._authorized_actions > 1:
            error = RuntimeError("competition lifecycle returned an unexpected full game reset")
            self._record_failure(boundary="reset-lifecycle", classification="platform", error=error)
            self._finalize_game(GovernorStopReason.FAILURE)
            raise error

        requested = _safe_action_for(legal)
        selected_value = 0.0
        force_fallback = self._controller_failed
        if not self._controller_failed:
            try:
                requested, selected_value = _bounded_call(
                    lambda: self._controller_request(observation),
                    seconds=FROZEN_COMPETITION_RUNTIME.decision_seconds,
                    boundary="controller-decision",
                )
                validate_action_request(observation, requested)
            except Exception as error:
                self._record_failure(
                    boundary="controller-decision",
                    classification="execution",
                    error=error,
                )
                self._controller_failed = True
                force_fallback = True
                self._close_failed_controller()
        try:
            authorization = self._require_governor().authorize_action(
                str(self.game_id),
                requested,
                legal,
                selected_value=selected_value,
                force_fallback=force_fallback,
            )
        except CompetitionIntegrityError as error:
            stop = self._require_governor().stop_decision(str(self.game_id))
            if not stop.should_stop:
                self._record_failure(
                    boundary="governor-authorization",
                    classification="execution",
                    error=error,
                )
                self._finalize_game(GovernorStopReason.FAILURE)
                raise
            self._record_failure(
                boundary="governor-stop-before-action",
                classification="budget exhaustion",
                error=error,
            )
            self._finalize_game(stop.reason)
            raise _BoundedTournamentStop(stop.reason.value) from None
        if authorization.fallback_used and not force_fallback:
            replacement_error = RuntimeError("governor replaced an illegal controller request")
            self._record_failure(
                boundary="governor-legality",
                classification="execution",
                error=replacement_error,
            )
            self._controller_failed = True
            self._close_failed_controller()
        self._authorized_actions += 1
        try:
            return _translate_action(authorization.authorized_action)
        except Exception as error:
            self._record_failure(
                boundary="action-translation",
                classification="execution",
                error=error,
            )
            self._finalize_game(GovernorStopReason.FAILURE)
            raise

    def main(self) -> None:
        """Run the pinned interface loop without ever exceeding an authorized boundary."""

        self.timer = time.time()
        try:
            while self.action_counter < self.MAX_ACTIONS:
                latest = self.frames[-1]
                if self.is_done(self.frames, latest):
                    break
                converter = getattr(self, "_convert_raw_frame_data", None)
                environment = getattr(self, "arc_env", None)
                if not callable(converter) or environment is None:
                    raise RuntimeError("official wrapper main-loop boundary is unavailable")
                converted = converter(environment.observation_space)
                try:
                    action = self.choose_action(self.frames, converted)
                except _BoundedTournamentStop:
                    break
                try:
                    frame = self.take_action(action)
                except _BoundedTournamentStop:
                    break
                if frame is not None:
                    self.append_frame(frame)
                self.action_counter += 1
        finally:
            self.cleanup()

    def do_action_request(self, action: object) -> object:
        """Submit immutable per-decision data at the pinned request boundary."""

        if not isinstance(action, _FrameworkActionRequest):
            raise RuntimeError("official wrapper received an unsealed action request")
        environment = getattr(self, "arc_env", None)
        step = getattr(environment, "step", None)
        if not callable(step):
            raise RuntimeError("official wrapper has no callable environment step")
        stop = self._require_governor().stop_decision(str(self.game_id))
        if stop.should_stop:
            error = _ActionDeadlineExpired("governor boundary expired before environment step")
            self._record_failure(
                boundary="environment-step-before-boundary",
                classification="budget exhaustion",
                error=error,
            )
            self._finalize_game(stop.reason)
            raise _BoundedTournamentStop(stop.reason.value) from None
        remaining_seconds = min(
            stop.game_seconds_remaining,
            stop.tournament_playable_seconds_remaining,
        )
        try:
            raw = _bounded_call(
                lambda: step(action.member, data=action.payload(), reasoning=None),
                seconds=remaining_seconds,
                boundary="environment-step",
            )
            converter = getattr(self, "_convert_raw_frame_data", None)
            if not callable(converter):
                raise RuntimeError("official wrapper has no frame conversion boundary")
            return converter(raw)
        except _ActionDeadlineExpired as error:
            self._record_failure(
                boundary="environment-step-deadline",
                classification="budget exhaustion",
                error=error,
            )
            measured = self._require_governor().stop_decision(str(self.game_id))
            self._finalize_game(
                measured.reason if measured.should_stop else GovernorStopReason.FAILURE
            )
            raise _BoundedTournamentStop("environment-step-deadline") from None
        except Exception as error:
            self._record_failure(
                boundary="environment-step", classification="platform", error=error
            )
            self._finalize_game(GovernorStopReason.FAILURE)
            raise

    def cleanup(self, scorecard: object | None = None) -> None:
        """Close sparse recovery state and ensure the game has one terminal receipt."""

        if self._game_started and not self._game_finalized:
            stop = self._require_governor().stop_decision(str(self.game_id))
            reason = stop.reason if stop.should_stop else GovernorStopReason.AGENT_DONE
            self._finalize_game(reason)
        parent_cleanup = getattr(super(), "cleanup", None)
        if callable(parent_cleanup):
            parent_cleanup(scorecard)


__all__ = ["MyAgent"]
