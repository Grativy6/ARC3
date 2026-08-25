"""Exact official ARC-AGI-3 adapter around the persistent ARC3 controller."""

from __future__ import annotations

import json
import math
import os
import signal
import sys
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
from arc3.mechanics.visual_causal import (
    VisualCausalPolicy,
    supports_visual_causal_observation,
)
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


class _ResourceBudgetExceeded(RuntimeError):
    """A measured competition resource crossed its frozen ceiling."""


class _PolicyRoute(StrEnum):
    """One game-local production policy owner selected from visible evidence."""

    CONTROLLER = "controller"
    MECHANICAL = "mechanical"


def _peak_rss_bytes() -> int | None:
    """Return the process high-water RSS on the Linux competition runtime."""

    try:
        resource_module = import_module("resource")
    except ImportError:
        return None
    getter = getattr(resource_module, "getrusage", None)
    self_usage = getattr(resource_module, "RUSAGE_SELF", None)
    if not callable(getter) or not isinstance(self_usage, int):
        return None
    usage = getattr(getter(self_usage), "ru_maxrss", None)
    if not isinstance(usage, int | float):
        return None
    # Linux reports KiB; macOS reports bytes. Kaggle evaluation is Linux, but
    # retaining the distinction keeps local diagnostics meaningful.
    return int(usage if sys.platform == "darwin" else usage * 1024)


def _directory_bytes(root: Path) -> int:
    """Measure regular files without following aliases outside runtime state."""

    if not root.exists():
        return 0
    total = 0
    pending = [root]
    while pending:
        current = pending.pop()
        with os.scandir(current) as entries:
            for entry in entries:
                if entry.is_symlink():
                    raise CompetitionIntegrityError(
                        f"competition runtime state contains an alias: {entry.path}"
                    )
                if entry.is_dir(follow_symlinks=False):
                    pending.append(Path(entry.path))
                elif entry.is_file(follow_symlinks=False):
                    total += entry.stat(follow_symlinks=False).st_size
    return total


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
        self._controller_closed = False
        self._mechanical_policy = VisualCausalPolicy(
            max_coordinate_candidates=FROZEN_COMPETITION_RUNTIME.max_coordinate_candidates
        )
        self._mechanical_policy_closed = False
        self._policy_route: _PolicyRoute | None = None
        self._pending_policy_route: _PolicyRoute | None = None
        self._controller_failed = False
        self._game_started = False
        self._game_finalized = False
        self._authorized_actions = 0
        self._runtime_root: Path | None = None
        with self._tournament_lock:
            self._require_governor()
            if str(self.game_id) not in self._expected_games:
                raise ConfigurationError("agent game is absent from the configured tournament")

    @property
    def name(self) -> str:
        base_name = getattr(super(), "name", type(self).__name__.lower())
        return f"{base_name}.arc3-controller-v2"

    def start_recording(self) -> None:
        """Disable the pinned framework's unbounded, nondeterministic frame recorder."""

        # The research controller retains its own compact trace and sparse
        # recovery checkpoints.  The inherited Agents recorder writes every
        # full frame with UUIDs and wall-clock timestamps outside the governor,
        # so it is deliberately absent only at this competition adapter.

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
            mechanical_snapshot = self._mechanical_policy.snapshot()
            receipt["mechanical_receipt_count"] = cast(int, mechanical_snapshot["receipt_count"])
            receipt["pending_policy_route"] = (
                self._pending_policy_route.value if self._pending_policy_route is not None else None
            )
            receipt["policy_route"] = (
                self._policy_route.value if self._policy_route is not None else None
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

    def _write_policy_snapshot(self) -> None:
        """Persist bounded in-memory policy evidence exactly once at close."""

        snapshot = _normalized_dict(
            {
                "authorized_actions": self._authorized_actions,
                "controller_closed": self._controller_closed,
                "controller_failed": self._controller_failed,
                "game_id": str(self.game_id),
                "mechanical_policy": self._mechanical_policy.snapshot(),
                "mechanical_policy_closed": self._mechanical_policy_closed,
                "pending_policy_route": (
                    self._pending_policy_route.value
                    if self._pending_policy_route is not None
                    else None
                ),
                "policy_route": (
                    self._policy_route.value if self._policy_route is not None else None
                ),
                "schema": "arc3.production-policy-route.v0.2",
            }
        )
        identity = sha256_json({"game_id": str(self.game_id)}).removeprefix("sha256:")[:16]
        self._write_receipt(f"policy-{identity}.json", snapshot)

    def _finalize_game(self, reason: GovernorStopReason) -> None:
        if self._game_finalized:
            return
        effective_reason = reason
        close_error = self._close_controller(boundary="controller-finalize")
        if close_error is not None:
            self._record_failure(
                boundary="controller-finalize",
                classification=(
                    "budget exhaustion"
                    if isinstance(close_error, _ActionDeadlineExpired)
                    else "execution"
                ),
                error=close_error,
            )
            self._controller_failed = True
            effective_reason = GovernorStopReason.FAILURE
        post_close_resource_error = (
            self._resource_budget_error(force_storage=True)
            if self._controller is not None
            else None
        )
        if post_close_resource_error is not None:
            self._record_failure(
                boundary="resource-budget-after-final-checkpoint",
                classification="budget exhaustion",
                error=post_close_resource_error,
            )
            self._controller_failed = True
            effective_reason = GovernorStopReason.FAILURE
        self._write_policy_snapshot()
        with self._tournament_lock:
            governor = self._require_governor()
            if self._game_started and governor.active_game_id == str(self.game_id):
                measured = governor.stop_decision(str(self.game_id))
                if measured.should_stop:
                    effective_reason = measured.reason
                receipt = _normalized_dict(
                    asdict(governor.finalize_game(str(self.game_id), reason=effective_reason))
                )
                identity = sha256_json({"game_id": str(self.game_id)}).removeprefix("sha256:")[:16]
                self._write_receipt(f"game-{identity}.json", receipt)
            self._game_finalized = True

    def _close_controller(self, *, boundary: str) -> Exception | None:
        first_error: Exception | None = None
        if not self._mechanical_policy_closed:
            try:
                self._mechanical_policy.close()
            except Exception as error:
                first_error = error
            else:
                self._mechanical_policy_closed = True
        if self._controller is None or self._controller_closed:
            return first_error
        stop = self._require_governor().stop_decision(str(self.game_id))
        seconds = min(
            30.0,
            stop.game_seconds_remaining,
            stop.tournament_playable_seconds_remaining,
        )
        if seconds <= 0.0:
            return first_error or _ActionDeadlineExpired(
                f"{boundary} has no remaining governed wall-clock slice"
            )
        try:
            _bounded_call(
                self._controller.close,
                seconds=seconds,
                boundary=boundary,
            )
        except Exception as error:
            return first_error or error
        self._controller_closed = True
        return first_error

    def _accept_pending_policy_consequence(self, observation: Observation) -> None:
        """Deliver one returned observation to exactly the selecting policy."""

        route = self._pending_policy_route
        if route is None:
            return
        if route is _PolicyRoute.MECHANICAL:
            if self._mechanical_policy_closed:
                raise RuntimeError("closed mechanical policy still owns a pending action")
            self._mechanical_policy.accept_consequence(observation)
        else:
            controller = self._controller
            if controller is None or controller.phase is not ControllerPhase.AWAITING_CONSEQUENCE:
                raise RuntimeError("controller consequence has no pending production action")
            controller.apply_consequence(observation)
        self._pending_policy_route = None

    def _cancel_unsubmitted_policy_request(self) -> Exception | None:
        """Cancel a mechanical selection that never reached environment.step."""

        route = self._pending_policy_route
        if route is None:
            return None
        if route is _PolicyRoute.CONTROLLER:
            return RuntimeError(
                "generic controller request is already durably submitted to its adapter boundary"
            )
        try:
            self._mechanical_policy.cancel_unsubmitted_action()
        except Exception as error:
            return error
        self._pending_policy_route = None
        return None

    def _fail_before_environment(
        self,
        *,
        boundary: str,
        classification: str,
        error: Exception,
        reason: GovernorStopReason,
    ) -> None:
        """Cancel definite non-submission, preserve receipts, and seal the game."""

        cancellation_error = self._cancel_unsubmitted_policy_request()
        if cancellation_error is not None:
            self._record_failure(
                boundary="policy-cancellation",
                classification="execution",
                error=cancellation_error,
            )
        self._record_failure(
            boundary=boundary,
            classification=classification,
            error=error,
        )
        self._finalize_game(reason)

    def _decision_slice_seconds(self) -> float:
        """Return the remaining single-cycle computation slice."""

        stop = self._require_governor().stop_decision(str(self.game_id))
        return min(
            FROZEN_COMPETITION_RUNTIME.decision_seconds,
            stop.game_seconds_remaining,
            stop.tournament_playable_seconds_remaining,
        )

    def is_done(self, frames: list[object], latest_frame: object) -> bool:
        del frames
        if self._game_finalized:
            return True
        self._ensure_game_started()
        resource_error = self._resource_budget_error()
        state_name = _enum_name(getattr(latest_frame, "state", "UNKNOWN"))
        stop = self._require_governor().stop_decision(str(self.game_id))
        terminal_or_stopped = state_name in {"WIN", "GAME_OVER", "UNKNOWN"} or stop.should_stop
        if (
            self._pending_policy_route is not None
            and resource_error is None
            and terminal_or_stopped
        ):
            try:
                observation = replace(normalize_frame_data(latest_frame), returned_action=None)
                _bounded_call(
                    lambda: self._accept_pending_policy_consequence(observation),
                    seconds=self._decision_slice_seconds(),
                    boundary="policy-consequence-terminal",
                )
            except Exception as error:
                self._record_failure(
                    boundary="policy-consequence-terminal",
                    classification=(
                        "budget exhaustion"
                        if isinstance(error, _ActionDeadlineExpired)
                        else "execution"
                    ),
                    error=error,
                )
                self._controller_failed = True
                self._finalize_game(GovernorStopReason.FAILURE)
                return True
        if resource_error is not None:
            self._record_failure(
                boundary="resource-budget",
                classification="budget exhaustion",
                error=resource_error,
            )
            self._finalize_game(GovernorStopReason.FAILURE)
            return True
        if state_name == "WIN":
            self._finalize_game(GovernorStopReason.WIN)
            return True
        if state_name == "GAME_OVER":
            # RESET from GAME_OVER is a whole-game reset in the official
            # lifecycle. Competition mode permits level resets only, so this
            # environment is terminal even though RESET is the sole SDK action.
            self._finalize_game(GovernorStopReason.AGENT_DONE)
            return True
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
        self._runtime_root = runtime_root
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

    def _resource_budget_error(
        self, *, force_storage: bool = False
    ) -> _ResourceBudgetExceeded | None:
        peak_rss = _peak_rss_bytes()
        memory_limit = FROZEN_COMPETITION_RUNTIME.memory_megabytes * 1024 * 1024
        if peak_rss is None and os.name == "posix":
            return _ResourceBudgetExceeded(
                "Linux peak RSS measurement is unavailable at the competition boundary"
            )
        if peak_rss is not None and peak_rss > memory_limit:
            return _ResourceBudgetExceeded(
                f"peak RSS {peak_rss} exceeded frozen memory ceiling {memory_limit}"
            )
        root = self._runtime_root
        if root is None or (not force_storage and self._authorized_actions <= 0):
            return None
        try:
            trace_bytes = _directory_bytes(root / "trace")
            checkpoint_bytes = _directory_bytes(root / "checkpoints")
        except (OSError, CompetitionIntegrityError) as error:
            return _ResourceBudgetExceeded(f"runtime state measurement failed: {error}")
        if trace_bytes > FROZEN_COMPETITION_RUNTIME.max_trace_bytes:
            return _ResourceBudgetExceeded(
                "trace bytes exceeded frozen ceiling: "
                f"{trace_bytes}>{FROZEN_COMPETITION_RUNTIME.max_trace_bytes}"
            )
        if checkpoint_bytes > FROZEN_COMPETITION_RUNTIME.max_checkpoint_bytes:
            return _ResourceBudgetExceeded(
                "checkpoint bytes exceeded frozen ceiling: "
                f"{checkpoint_bytes}>{FROZEN_COMPETITION_RUNTIME.max_checkpoint_bytes}"
            )
        return None

    @staticmethod
    def _legal_actions(observation: Observation) -> tuple[ActionName, ...]:
        if observation.state is GameStateName.NOT_PLAYED:
            return (ActionName.RESET,)
        if observation.state in {
            GameStateName.WIN,
            GameStateName.GAME_OVER,
            GameStateName.UNKNOWN,
        }:
            return ()
        return observation.available_actions

    def _controller_request(self, observation: Observation) -> tuple[ActionRequest, float]:
        # Returned-consequence folding and the next selection share this one
        # bounded call; the frozen 10-second slice explicitly covers both.
        self._accept_pending_policy_consequence(observation)
        if self._policy_route is None and observation.state is GameStateName.NOT_PLAYED:
            self._pending_policy_route = _PolicyRoute.MECHANICAL
            action = self._mechanical_policy.select(observation)
            return action, 0.0
        if self._policy_route is None:
            self._policy_route = (
                _PolicyRoute.MECHANICAL
                if supports_visual_causal_observation(observation)
                else _PolicyRoute.CONTROLLER
            )
        elif (
            self._policy_route is _PolicyRoute.MECHANICAL
            and observation.state is GameStateName.NOT_FINISHED
            and not supports_visual_causal_observation(observation)
        ):
            # Once current visible support disappears, switch exactly once to
            # a controller initialized from this returned observation.  Never
            # alternate two stateful policies across environment actions.
            self._mechanical_policy.close()
            self._mechanical_policy_closed = True
            self._policy_route = _PolicyRoute.CONTROLLER

        if self._policy_route is _PolicyRoute.MECHANICAL:
            self._pending_policy_route = _PolicyRoute.MECHANICAL
            action = self._mechanical_policy.select(observation)
            return action, 0.0

        if self._controller is None:
            self._controller = self._start_controller(str(observation.game_id))
            self._controller.observe(observation)
        elif self._controller.phase is ControllerPhase.NEW:
            self._controller.observe(observation)
        elif self._controller.phase is ControllerPhase.AWAITING_CONSEQUENCE:
            raise RuntimeError("controller pending consequence bypassed production ownership")
        self._pending_policy_route = _PolicyRoute.CONTROLLER
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
        resource_error = self._resource_budget_error()
        if resource_error is not None:
            self._record_failure(
                boundary="resource-budget",
                classification="budget exhaustion",
                error=resource_error,
            )
            self._finalize_game(GovernorStopReason.FAILURE)
            raise _BoundedTournamentStop("resource-budget")
        observation = replace(normalize_frame_data(latest_frame), returned_action=None)
        legal = self._legal_actions(observation)
        if not legal:
            error = RuntimeError("observation exposes no legal action")
            self._record_failure(
                boundary="legal-action-surface", classification="platform", error=error
            )
            self._finalize_game(GovernorStopReason.NO_LEGAL_ACTIONS)
            raise error
        if observation.full_reset and self._authorized_actions > 0:
            error = RuntimeError("competition lifecycle returned an unexpected full game reset")
            self._record_failure(boundary="reset-lifecycle", classification="platform", error=error)
            self._finalize_game(GovernorStopReason.FAILURE)
            raise error

        requested = _safe_action_for(legal)
        selected_value = 0.0
        force_fallback = self._controller_failed
        if not self._controller_failed:
            try:
                cycle_boundary = self._require_governor().stop_decision(str(self.game_id))
                if cycle_boundary.should_stop:
                    self._finalize_game(cycle_boundary.reason)
                    raise _BoundedTournamentStop(cycle_boundary.reason.value)
                cycle_seconds = min(
                    FROZEN_COMPETITION_RUNTIME.decision_seconds,
                    cycle_boundary.game_seconds_remaining,
                    cycle_boundary.tournament_playable_seconds_remaining,
                )
                requested, selected_value = _bounded_call(
                    lambda: self._controller_request(observation),
                    seconds=cycle_seconds,
                    boundary="controller-decision",
                )
                validate_action_request(observation, requested)
            except _BoundedTournamentStop:
                raise
            except Exception as error:
                staged_route = self._pending_policy_route
                cancellation_error = (
                    self._cancel_unsubmitted_policy_request()
                    if staged_route is _PolicyRoute.MECHANICAL
                    else None
                )
                if cancellation_error is not None:
                    self._record_failure(
                        boundary="policy-cancellation",
                        classification="execution",
                        error=cancellation_error,
                    )
                self._record_failure(
                    boundary="controller-decision",
                    classification=(
                        "budget exhaustion"
                        if isinstance(error, _ActionDeadlineExpired)
                        else "execution"
                    ),
                    error=error,
                )
                mechanical_owned = (
                    staged_route is _PolicyRoute.MECHANICAL
                    or self._policy_route is _PolicyRoute.MECHANICAL
                    or (
                        observation.state is GameStateName.NOT_PLAYED and self._policy_route is None
                    )
                )
                # A mechanical failure while support remains, or a generic
                # controller that already emitted its durable submitted-action
                # receipt, cannot honestly own a different fallback action.
                if mechanical_owned or staged_route is _PolicyRoute.CONTROLLER:
                    self._controller_failed = True
                    self._finalize_game(GovernorStopReason.FAILURE)
                    raise _BoundedTournamentStop("policy-decision") from None
                self._controller_failed = True
                force_fallback = True
        try:
            authorization = self._require_governor().authorize_action(
                str(self.game_id),
                requested,
                legal,
                selected_value=selected_value,
                force_fallback=force_fallback,
            )
        except CompetitionIntegrityError as error:
            cancellation_error = self._cancel_unsubmitted_policy_request()
            if cancellation_error is not None:
                self._record_failure(
                    boundary="policy-cancellation",
                    classification="execution",
                    error=cancellation_error,
                )
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
            cancellation_error = self._cancel_unsubmitted_policy_request()
            if cancellation_error is not None:
                self._record_failure(
                    boundary="policy-cancellation",
                    classification="execution",
                    error=cancellation_error,
                )
            replacement_error = RuntimeError("governor replaced an illegal controller request")
            self._record_failure(
                boundary="governor-legality",
                classification="execution",
                error=replacement_error,
            )
            self._controller_failed = True
            self._finalize_game(GovernorStopReason.FAILURE)
            raise _BoundedTournamentStop("governor-legality")
        self._authorized_actions += 1
        try:
            return _translate_action(authorization.authorized_action)
        except Exception as error:
            cancellation_error = self._cancel_unsubmitted_policy_request()
            if cancellation_error is not None:
                self._record_failure(
                    boundary="policy-cancellation",
                    classification="execution",
                    error=cancellation_error,
                )
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
            shape_error = RuntimeError("official wrapper received an unsealed action request")
            self._fail_before_environment(
                boundary="environment-request-shape",
                classification="platform",
                error=shape_error,
                reason=GovernorStopReason.FAILURE,
            )
            raise shape_error
        environment = getattr(self, "arc_env", None)
        step = getattr(environment, "step", None)
        if not callable(step):
            step_error = RuntimeError("official wrapper has no callable environment step")
            self._fail_before_environment(
                boundary="environment-step-unavailable",
                classification="platform",
                error=step_error,
                reason=GovernorStopReason.FAILURE,
            )
            raise step_error
        converter = getattr(self, "_convert_raw_frame_data", None)
        if not callable(converter):
            converter_error = RuntimeError("official wrapper has no frame conversion boundary")
            self._fail_before_environment(
                boundary="environment-converter-unavailable",
                classification="platform",
                error=converter_error,
                reason=GovernorStopReason.FAILURE,
            )
            raise converter_error
        stop = self._require_governor().stop_decision(str(self.game_id))
        if stop.should_stop:
            stop_error = _ActionDeadlineExpired("governor boundary expired before environment step")
            self._fail_before_environment(
                boundary="environment-step-before-boundary",
                classification="budget exhaustion",
                error=stop_error,
                reason=stop.reason,
            )
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
