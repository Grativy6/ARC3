"""Fail-closed launcher for the pinned platform-supplied Agents framework."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import os
import signal
import sys
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass, is_dataclass
from enum import Enum
from importlib import import_module
from pathlib import Path
from types import ModuleType
from typing import Any, cast
from urllib.request import ProxyHandler, Request, build_opener

from arc3.competition_runtime import FROZEN_COMPETITION_RUNTIME
from arc3.packaging.models import ExternalSurfaceUnavailableError, PackagingError
from arc3.types import JSONValue

AGENTS_COMMIT = "4743e7d0aaae0ded0d98a89a7e282e63564cd58b"
SAFE_FRAMEWORK_FIXTURE_IDENTITY = "arc3.stage17.safe-framework.v0.1"
_ALLOWED_GATEWAY_HOSTS = frozenset({"127.0.0.1", "::1", "gateway", "localhost"})
_MANAGED_MODULE_ROOTS = (
    "agents",
    "agentops",
    "arc3_competition_agent",
    "arc_agi",
    "arcengine",
    "dotenv",
)
_PINNED_LF_FILES = {
    # SHA-256 identities of the raw LF bytes stored by the pinned Git commit.
    "LICENSE": "75c4276c506fd93082b38ad39f67ee97aa859574401ef978e701710c7a40af04",
    "agents/agent.py": "49f1a349cd5e2123fceb266aec4a3a758d18ef5520e0212e808f695905d9e073",
    "agents/recorder.py": "0a08d89f4067a760012767c05d4406bd2bf409f426e29a1193106abfcbb696c8",
    "agents/swarm.py": "d9dc48f710f1b90a6552db0921293c7e89c8a925ed00a3faefa07ae19998ad39",
}
_ORCHESTRATION_ID = "arc3.sequential-pinned-swarm.v1"
_PLATFORM_BOUNDARY_TIMEOUT_SECONDS = 120.0
_FAILURE_RECEIPT_MARGIN_SECONDS = 30.0


class _CompetitionBoundaryTimeout(TimeoutError):
    """Private signal raised only by the launcher's real-time timer."""


def _signal_deadline_available() -> bool:
    """Return whether this process can interrupt a blocking call with SIGALRM."""

    return (
        os.name == "posix"
        and threading.current_thread() is threading.main_thread()
        and hasattr(signal, "SIGALRM")
        and hasattr(signal, "ITIMER_REAL")
        and hasattr(signal, "setitimer")
    )


def _call_with_hard_deadline(
    operation: str,
    call: Callable[[], object],
    *,
    hard_deadline_seconds: float,
) -> object:
    """Bound one lifecycle call by a short cap and the global notebook deadline."""

    now = time.monotonic()
    remaining = min(
        _PLATFORM_BOUNDARY_TIMEOUT_SECONDS,
        hard_deadline_seconds - now,
    )
    if remaining <= 0.0:
        raise PackagingError(f"{operation} reached the competition runtime deadline")

    if not _signal_deadline_available():
        result = call()
        if time.monotonic() > min(now + remaining, hard_deadline_seconds):
            raise PackagingError(f"{operation} exceeded its bounded runtime")
        return result

    posix_signal: Any = signal
    sigalrm = posix_signal.SIGALRM
    itimer_real = posix_signal.ITIMER_REAL
    getitimer = cast(Callable[[int], tuple[float, float]], posix_signal.getitimer)
    setitimer = cast(
        Callable[[int, float], tuple[float, float]],
        posix_signal.setitimer,
    )
    previous_handler = signal.getsignal(sigalrm)
    previous_timer = getitimer(itimer_real)
    if previous_timer[0] > 0.0 or previous_timer[1] > 0.0:
        raise PackagingError(f"{operation} found an active conflicting real-time timer")

    def expire(_signum: int, _frame: object) -> None:
        raise _CompetitionBoundaryTimeout(operation)

    signal.signal(sigalrm, expire)
    setitimer(itimer_real, remaining)
    try:
        return call()
    except _CompetitionBoundaryTimeout as error:
        raise PackagingError(f"{operation} exceeded its bounded runtime") from error
    finally:
        setitimer(itimer_real, 0.0)
        signal.signal(sigalrm, previous_handler)


@dataclass(frozen=True, slots=True)
class CompetitionLaunchReceipt:
    """Concise evidence returned after the supplied framework exits."""

    framework_commit: str
    framework_identity: str
    framework_fixture: bool
    gateway_host: str
    gateway_port: int
    game_count: int
    agent_count: int
    worker_count: int
    max_concurrency: int
    orchestration: str
    dotenv_imported: bool
    telemetry_imported: bool
    discovered_environments: tuple[str, ...]
    lifecycle_enforced: bool
    open_scorecard_count: int
    close_scorecard_count: int
    make_count: int
    get_scorecard_during_flight_count: int
    all_environments_covered: bool
    tournament_configured: bool
    tournament_finalized: bool
    tournament_receipt: JSONValue
    notebook_started_at_seconds: float | None
    hard_deadline_seconds: float
    hard_timeout_enforced: bool

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "dotenv_imported": self.dotenv_imported,
            "all_environments_covered": self.all_environments_covered,
            "close_scorecard_count": self.close_scorecard_count,
            "discovered_environments": list(self.discovered_environments),
            "framework_commit": self.framework_commit,
            "framework_identity": self.framework_identity,
            "framework_fixture": self.framework_fixture,
            "agent_count": self.agent_count,
            "game_count": self.game_count,
            "gateway_host": self.gateway_host,
            "gateway_port": self.gateway_port,
            "get_scorecard_during_flight_count": (self.get_scorecard_during_flight_count),
            "hard_deadline_seconds": self.hard_deadline_seconds,
            "hard_timeout_enforced": self.hard_timeout_enforced,
            "lifecycle_enforced": self.lifecycle_enforced,
            "make_count": self.make_count,
            "max_concurrency": self.max_concurrency,
            "notebook_started_at_seconds": self.notebook_started_at_seconds,
            "open_scorecard_count": self.open_scorecard_count,
            "orchestration": self.orchestration,
            "telemetry_imported": self.telemetry_imported,
            "tournament_configured": self.tournament_configured,
            "tournament_finalized": self.tournament_finalized,
            "tournament_receipt": self.tournament_receipt,
            "worker_count": self.worker_count,
        }


@dataclass(slots=True)
class _CompetitionLifecycleStats:
    """Fail-closed interaction counts for one pinned scorecard run."""

    expected_games: tuple[str, ...]
    open_scorecard_count: int = 0
    close_scorecard_count: int = 0
    make_count: int = 0
    get_scorecard_during_flight_count: int = 0
    opened_scorecard_id: str | None = None
    made_games: tuple[str, ...] = ()

    @property
    def scorecard_in_flight(self) -> bool:
        return self.open_scorecard_count == 1 and self.close_scorecard_count == 0

    @property
    def all_environments_covered(self) -> bool:
        return self.made_games == self.expected_games

    def validate_complete(self) -> None:
        if self.open_scorecard_count != 1:
            raise PackagingError("competition lifecycle did not open exactly one scorecard")
        if self.close_scorecard_count != 1:
            raise PackagingError("competition lifecycle did not close exactly one scorecard")
        if self.make_count != len(self.expected_games):
            raise PackagingError("competition lifecycle environment make count mismatch")
        if self.get_scorecard_during_flight_count != 0:
            raise PackagingError("competition lifecycle read the scorecard during flight")
        if not self.all_environments_covered:
            raise PackagingError(
                "competition lifecycle did not cover every environment exactly once"
            )


class _InstrumentedArcade:
    """Narrow proxy enforcing the one-scorecard competition lifecycle."""

    def __init__(
        self,
        arcade: object,
        stats: _CompetitionLifecycleStats,
        *,
        hard_deadline_seconds: float,
        before_scorecard_open: Callable[[], None] | None = None,
        before_environment_make: Callable[[str, int], None] | None = None,
    ) -> None:
        self._arcade = arcade
        self._stats = stats
        self._hard_deadline_seconds = hard_deadline_seconds
        self._before_scorecard_open = before_scorecard_open
        self._before_environment_make = before_environment_make

    def __getattr__(self, name: str) -> Any:
        return getattr(self._arcade, name)

    def open_scorecard(self, *args: Any, **kwargs: Any) -> str:
        if self._stats.open_scorecard_count != 0:
            raise PackagingError("competition lifecycle attempted a scorecard retry")
        method = getattr(self._arcade, "open_scorecard", None)
        if not callable(method):
            raise PackagingError("competition Arcade has no open_scorecard boundary")
        if self._before_scorecard_open is not None:
            self._before_scorecard_open()
        # Count the upstream interaction attempt only after the durable callback
        # succeeds and directly before the official scorecard-open call.
        self._stats.open_scorecard_count = 1
        scorecard_id = _call_with_hard_deadline(
            "competition scorecard open",
            lambda: method(*args, **kwargs),
            hard_deadline_seconds=self._hard_deadline_seconds,
        )
        if not isinstance(scorecard_id, str) or not scorecard_id:
            raise PackagingError("competition Arcade returned an invalid scorecard identity")
        self._stats.opened_scorecard_id = scorecard_id
        return scorecard_id

    def make(self, game_id: str, *args: Any, **kwargs: Any) -> object:
        self._stats.make_count += 1
        if not self._stats.scorecard_in_flight:
            raise PackagingError("competition lifecycle made an environment outside its scorecard")
        if game_id not in self._stats.expected_games:
            raise PackagingError("competition lifecycle attempted an unexpected environment")
        if game_id in self._stats.made_games:
            raise PackagingError("competition lifecycle attempted an environment retry")
        expected_ordinal = len(self._stats.made_games)
        if self._stats.expected_games[expected_ordinal] != game_id:
            raise PackagingError("competition lifecycle changed the frozen environment order")

        scorecard_id = kwargs.get("scorecard_id")
        if len(args) >= 2:
            if "scorecard_id" in kwargs:
                raise PackagingError("competition lifecycle supplied scorecard identity twice")
            scorecard_id = args[1]
        if scorecard_id != self._stats.opened_scorecard_id:
            raise PackagingError("competition environment was not bound to the open scorecard")

        if self._before_environment_make is not None:
            self._before_environment_make(game_id, expected_ordinal)

        # Seal the attempt before calling upstream. A failed make cannot be
        # retried without violating the one-interaction competition boundary.
        self._stats.made_games = (*self._stats.made_games, game_id)
        method = getattr(self._arcade, "make", None)
        if not callable(method):
            raise PackagingError("competition Arcade has no make boundary")
        environment = _call_with_hard_deadline(
            "competition environment make",
            lambda: method(game_id, *args, **kwargs),
            hard_deadline_seconds=self._hard_deadline_seconds,
        )
        if environment is None:
            raise PackagingError("competition Arcade did not return an environment")
        return environment

    def get_scorecard(self, *args: Any, **kwargs: Any) -> object:
        if self._stats.scorecard_in_flight:
            self._stats.get_scorecard_during_flight_count += 1
            raise PackagingError("competition lifecycle forbids scorecard reads during flight")
        method = getattr(self._arcade, "get_scorecard", None)
        if not callable(method):
            raise PackagingError("competition Arcade has no get_scorecard boundary")
        return _call_with_hard_deadline(
            "competition scorecard read",
            lambda: method(*args, **kwargs),
            hard_deadline_seconds=self._hard_deadline_seconds,
        )

    def close_scorecard(self, *args: Any, **kwargs: Any) -> object:
        self._stats.close_scorecard_count += 1
        if self._stats.close_scorecard_count != 1:
            raise PackagingError("competition lifecycle attempted a scorecard close retry")
        if self._stats.open_scorecard_count != 1:
            raise PackagingError("competition lifecycle closed a scorecard before opening it")
        scorecard_id = args[0] if args else kwargs.get("scorecard_id")
        if scorecard_id != self._stats.opened_scorecard_id:
            raise PackagingError("competition lifecycle closed the wrong scorecard")
        method = getattr(self._arcade, "close_scorecard", None)
        if not callable(method):
            raise PackagingError("competition Arcade has no close_scorecard boundary")
        return _call_with_hard_deadline(
            "competition scorecard close",
            lambda: method(*args, **kwargs),
            hard_deadline_seconds=self._hard_deadline_seconds,
        )


@dataclass(slots=True)
class _SequentialThreadStats:
    """Measured worker scheduling state for the pinned Swarm implementation."""

    active: int = 0
    completed: int = 0
    failures: int = 0
    max_active: int = 0
    started: int = 0


class _SequentialThread:
    """Narrow ``Thread`` substitute that preserves Swarm flow without fan-out."""

    def __init__(
        self,
        stats: _SequentialThreadStats,
        group: object | None = None,
        target: Callable[..., object] | None = None,
        name: str | None = None,
        args: tuple[object, ...] = (),
        kwargs: dict[str, object] | None = None,
        *,
        daemon: bool | None = None,
    ) -> None:
        del group, name, daemon
        self._stats = stats
        self._target = target
        self._args = args
        self._kwargs = dict(kwargs or {})
        self._started = False

    def start(self) -> None:
        if self._started:
            raise RuntimeError("threads can only be started once")
        self._started = True
        self._stats.started += 1
        self._stats.active += 1
        self._stats.max_active = max(self._stats.max_active, self._stats.active)
        try:
            if self._target is not None:
                self._target(*self._args, **self._kwargs)
        except BaseException:
            # ``threading.Thread`` does not re-raise a worker failure in its
            # caller. Preserve that behavior until Swarm closes its scorecard,
            # then fail the launcher from the measured failure count below.
            self._stats.failures += 1
        finally:
            self._stats.active -= 1
            self._stats.completed += 1

    def join(self, timeout: float | None = None) -> None:
        del timeout
        if not self._started:
            raise RuntimeError("cannot join a thread before it is started")


def _matches_pinned_git_text(path: Path, expected_lf_sha256: str) -> bool:
    """Match raw Git bytes or their exact all-CRLF Windows checkout form.

    The repository identity is always the raw LF content stored by Git. A
    Windows checkout may have converted every LF to CRLF; accepting that exact
    reversible transform keeps local rehearsals portable without accepting
    mixed line endings, lone carriage returns, or any content mutation.
    """

    content = path.read_bytes()
    if hashlib.sha256(content).hexdigest() == expected_lf_sha256:
        return True
    canonical_lf = content.replace(b"\r\n", b"\n")
    if b"\r" in canonical_lf:
        return False
    if canonical_lf.replace(b"\n", b"\r\n") != content:
        return False
    return hashlib.sha256(canonical_lf).hexdigest() == expected_lf_sha256


def _validate_framework(framework_root: Path, *, allow_test_fixture: bool) -> tuple[str, str, bool]:
    agents_directory = framework_root / "agents"
    if not agents_directory.is_dir():
        raise PackagingError("competition Agents framework has no agents package")
    fixture_marker = framework_root / ".arc3-safe-fixture"
    if fixture_marker.is_file():
        if (
            not allow_test_fixture
            or fixture_marker.read_text(encoding="utf-8") != SAFE_FRAMEWORK_FIXTURE_IDENTITY
        ):
            raise PackagingError("test framework fixture is not authorized for this rehearsal")
        for relative in ("agents/agent.py", "agents/swarm.py"):
            if not (framework_root / relative).is_file():
                raise PackagingError(f"safe framework fixture is missing {relative}")
        return AGENTS_COMMIT, SAFE_FRAMEWORK_FIXTURE_IDENTITY, True

    for relative, expected in _PINNED_LF_FILES.items():
        path = framework_root / relative
        if not path.is_file() or not _matches_pinned_git_text(path, expected):
            raise PackagingError(
                f"platform Agents framework differs from pinned {AGENTS_COMMIT}: {relative}"
            )
    return AGENTS_COMMIT, f"git:{AGENTS_COMMIT}", False


def _load_agent_module(agent_path: Path) -> ModuleType:
    module_name = "arc3_competition_agent"
    spec = importlib.util.spec_from_file_location(module_name, agent_path)
    if spec is None or spec.loader is None:
        raise PackagingError(f"cannot load packaged agent wrapper: {agent_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(module_name, None)
        raise
    return module


def _trace_passthrough(function: Callable[..., Any]) -> Callable[..., Any]:
    return function


def _tracing_stub() -> ModuleType:
    module = ModuleType("agents.tracing")
    module.__dict__["trace_agent_session"] = _trace_passthrough
    return module


def _dotenv_stub() -> ModuleType:
    module = ModuleType("dotenv")

    def load_dotenv(*args: Any, **kwargs: Any) -> bool:
        del args, kwargs
        return False

    module.__dict__["load_dotenv"] = load_dotenv
    return module


def _matches_module_namespace(name: str, root: str) -> bool:
    return name == root or name.startswith(root + ".")


def _gateway_url(host: str, port: int, path: str) -> str:
    authority = f"[{host}]" if host == "::1" else host
    return f"http://{authority}:{port}{path}"


def _discover_games(host: str, port: int) -> tuple[str, ...]:
    request = Request(
        _gateway_url(host, port, "/api/games"),
        headers={"Accept": "application/json", "X-API-Key": "test-key-123"},
        method="GET",
    )
    try:
        with build_opener(ProxyHandler({})).open(request, timeout=10.0) as response:
            body = response.read(1024 * 1024 + 1)
    except Exception as error:
        raise ExternalSurfaceUnavailableError(
            f"competition-local gateway discovery failed ({type(error).__name__})"
        ) from None
    if len(body) > 1024 * 1024:
        raise PackagingError("competition-local gateway response exceeded one MiB")
    try:
        decoded = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise PackagingError(f"competition-local gateway returned invalid JSON: {error}") from error
    if not isinstance(decoded, list):
        raise PackagingError("competition-local gateway game inventory must be an array")
    games: list[str] = []
    for item in decoded:
        if not isinstance(item, dict):
            raise PackagingError("competition-local gateway game record must be an object")
        game_id = item.get("game_id")
        if not isinstance(game_id, str) or not game_id or len(game_id) > 128:
            raise PackagingError("competition-local gateway returned an invalid game ID")
        games.append(game_id)
    if not games or len(games) != len(set(games)):
        raise PackagingError("competition-local gateway returned no games or duplicate IDs")
    return tuple(games)


def _freeze_environment_order(games: tuple[str, ...]) -> tuple[str, ...]:
    """Revalidate and freeze gateway inventory independently of response order."""

    if not games or len(games) != len(set(games)):
        raise PackagingError("competition environment inventory is empty or duplicated")
    if any(not isinstance(game, str) or not game or len(game) > 128 for game in games):
        raise PackagingError("competition environment inventory contains an invalid identity")
    return tuple(sorted(games))


def _json_default(value: object) -> object:
    if is_dataclass(value) and not isinstance(value, type):
        return asdict(value)
    if isinstance(value, Enum):
        return value.value
    converter = getattr(value, "to_dict", None)
    if callable(converter):
        return converter()
    raise TypeError(f"{type(value).__name__} is not JSON-compatible")


def _normalize_json_receipt(value: object) -> JSONValue:
    """Canonicalize hook output and reject non-finite or oversized receipts."""

    encoded = json.dumps(
        value,
        allow_nan=False,
        default=_json_default,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    if len(encoded) > 1024 * 1024:
        raise ValueError("tournament receipt exceeds one MiB")
    decoded: Any = json.loads(encoded)
    return cast(JSONValue, decoded)


def _validate_tournament_receipt(
    value: JSONValue,
    *,
    expected_games: tuple[str, ...],
) -> None:
    """Validate the bounded governor's terminal receipt before launch success."""

    if not isinstance(value, dict) or value.get("status") != "PASS":
        raise PackagingError("competition tournament finalization did not return PASS")
    receipt = value.get("receipt")
    if not isinstance(receipt, dict):
        raise PackagingError("competition tournament finalization receipt is not an object")
    expected_count = len(expected_games)
    if receipt.get("expected_environments") != expected_count:
        raise PackagingError("competition tournament expected-environment count changed")
    if receipt.get("finalized_environments") != expected_count:
        raise PackagingError("competition tournament did not finalize every environment")
    if receipt.get("effective_ceiling_respected") is not True:
        raise PackagingError("competition tournament exceeded its effective runtime ceiling")
    if receipt.get("reserve_preserved") is not True:
        raise PackagingError("competition tournament consumed its protected runtime reserve")
    if receipt.get("outcome") != "complete-reserve-preserved":
        raise PackagingError("competition tournament terminal outcome is not reserve-preserving")
    games = receipt.get("games")
    if not isinstance(games, list) or len(games) != expected_count:
        raise PackagingError("competition tournament game receipt count mismatch")
    game_ids: list[str] = []
    for game in games:
        if not isinstance(game, dict) or not isinstance(game.get("game_id"), str):
            raise PackagingError("competition tournament contains an invalid game receipt")
        game_ids.append(cast(str, game["game_id"]))
    if tuple(game_ids) != expected_games:
        raise PackagingError("competition tournament game receipt order or identity changed")
    total_actions = receipt.get("total_actions_authorized")
    maximum_actions = receipt.get("maximum_total_actions")
    if (
        isinstance(total_actions, bool)
        or not isinstance(total_actions, int)
        or total_actions < 0
        or isinstance(maximum_actions, bool)
        or not isinstance(maximum_actions, int)
        or maximum_actions <= 0
        or total_actions > maximum_actions
    ):
        raise PackagingError("competition tournament action accounting is invalid")


def _finalize_tournament_hook(
    agent_type: type[object],
    *,
    hard_deadline_seconds: float,
) -> tuple[bool, bool, JSONValue]:
    """Run the optional tournament finalizer and always return a safe receipt."""

    finalizer = getattr(agent_type, "finalize_tournament", None)
    if not callable(finalizer):
        return False, False, None
    try:
        result = _call_with_hard_deadline(
            "competition tournament finalization",
            finalizer,
            hard_deadline_seconds=hard_deadline_seconds,
        )
        if result is None:
            raise ValueError("tournament finalizer returned no receipt")
        normalized = _normalize_json_receipt(result)
    except Exception as error:
        return (
            True,
            False,
            {
                "error_type": type(error).__name__,
                "message_sha256": hashlib.sha256(str(error).encode("utf-8")).hexdigest(),
                "status": "FAIL",
            },
        )
    return True, True, {"receipt": normalized, "status": "PASS"}


def _lifecycle_receipt(stats: _CompetitionLifecycleStats | None) -> dict[str, JSONValue]:
    if stats is None:
        return {
            "all_environments_covered": False,
            "close_scorecard_count": 0,
            "get_scorecard_during_flight_count": 0,
            "lifecycle_enforced": False,
            "make_count": 0,
            "open_scorecard_count": 0,
        }
    return {
        "all_environments_covered": stats.all_environments_covered,
        "close_scorecard_count": stats.close_scorecard_count,
        "get_scorecard_during_flight_count": stats.get_scorecard_during_flight_count,
        "lifecycle_enforced": True,
        "make_count": stats.make_count,
        "open_scorecard_count": stats.open_scorecard_count,
    }


def _write_launch_failure_receipt(
    working_root: Path,
    *,
    stage: str,
    error: BaseException,
    framework_identity: str,
    games: tuple[str, ...],
    lifecycle: _CompetitionLifecycleStats | None,
    tournament_configured: bool,
    tournament_finalized: bool,
    tournament_receipt: JSONValue,
    notebook_started_at_seconds: float | None = None,
    hard_deadline_seconds: float | None = None,
    hard_timeout_enforced: bool = False,
) -> Path:
    """Persist an immutable, credential-free receipt before propagating failure."""

    payload: dict[str, JSONValue] = {
        "discovered_environments": list(games),
        "error_type": type(error).__name__,
        "framework_commit": AGENTS_COMMIT,
        "framework_identity": framework_identity,
        "hard_deadline_seconds": hard_deadline_seconds,
        "hard_timeout_enforced": hard_timeout_enforced,
        "lifecycle": _lifecycle_receipt(lifecycle),
        "message_sha256": hashlib.sha256(str(error).encode("utf-8")).hexdigest(),
        "notebook_started_at_seconds": notebook_started_at_seconds,
        "schema": "arc3.competition-launch-failure.v0.1",
        "stage": stage,
        "status": "FAIL",
        "tournament_configured": tournament_configured,
        "tournament_finalized": tournament_finalized,
        "tournament_receipt": tournament_receipt,
    }
    encoded = (
        json.dumps(payload, allow_nan=False, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    identity = hashlib.sha256(encoded).hexdigest()[:16]
    path = working_root / f"arc3-launch-failure-{identity}.json"
    try:
        with path.open("xb") as stream:
            stream.write(encoded)
    except FileExistsError:
        if path.read_bytes() != encoded:
            raise PackagingError("competition launch failure receipt identity collision") from None
    return path


@contextmanager
def _sanitized_competition_environment(
    *, gateway_host: str, gateway_port: int, working_root: Path
) -> Iterator[None]:
    prior = dict(os.environ)
    preserved_names = {
        "ARC3_GIT_COMMIT",
        "ARC3_SEED",
        "KAGGLE_IS_COMPETITION_RERUN",
        "LANG",
        "LC_ALL",
        "LD_LIBRARY_PATH",
        "PATH",
        "SYSTEMDRIVE",
        "SYSTEMROOT",
        "TEMP",
        "TMP",
        "TMPDIR",
        "WINDIR",
    }
    preserved = {name: prior[name] for name in preserved_names if name in prior}
    runtime = {
        "ARC3_MODE": "competition",
        "ARC3_NETWORK_ENABLED": "false",
        "ARC_API_KEY": "test-key-123",
        "ARC_BASE_URL": _gateway_url(gateway_host, gateway_port, "/"),
        "ENVIRONMENTS_DIR": "",
        "HOME": str(working_root),
        "HOST": gateway_host,
        "MPLBACKEND": "agg",
        "OPERATION_MODE": "competition",
        "PORT": str(gateway_port),
        "PYTHONDONTWRITEBYTECODE": "1",
        "RECORDINGS_DIR": str(working_root / "server_recording"),
        "SCHEME": "http",
        "USERPROFILE": str(working_root),
        "XDG_CACHE_HOME": str(working_root / ".cache"),
        "XDG_CONFIG_HOME": str(working_root / ".config"),
        "XDG_DATA_HOME": str(working_root / ".local" / "share"),
        "ARC3_WORKING_DIR": str(working_root),
        "NO_PROXY": "gateway,localhost,127.0.0.1,::1",
        "no_proxy": "gateway,localhost,127.0.0.1,::1",
    }
    try:
        os.environ.clear()
        os.environ.update(preserved)
        os.environ.update(runtime)
        yield
    finally:
        os.environ.clear()
        os.environ.update(prior)


def launch_competition_framework(
    framework_root: Path,
    agent_path: Path,
    *,
    gateway_host: str = "gateway",
    gateway_port: int = 8001,
    working_root: Path | None = None,
    allow_test_fixture: bool = False,
    before_scorecard_open: Callable[[], None] | None = None,
    before_environment_make: Callable[[str, int], None] | None = None,
    notebook_started_at_seconds: float | None = None,
) -> CompetitionLaunchReceipt:
    """Run only the pinned framework core against the competition-local gateway."""

    launcher_started_at = time.monotonic()
    framework_root = framework_root.resolve()
    agent_path = agent_path.resolve()
    if gateway_host not in _ALLOWED_GATEWAY_HOSTS:
        raise PackagingError("gateway host must be the Kaggle sidecar name or loopback")
    if gateway_port <= 0 or gateway_port > 65535:
        raise PackagingError("gateway_port must be in 1..65535")
    if before_environment_make is not None and not callable(before_environment_make):
        raise PackagingError("before_environment_make must be callable when supplied")
    if before_scorecard_open is not None and not callable(before_scorecard_open):
        raise PackagingError("before_scorecard_open must be callable when supplied")
    normalized_notebook_start: float | None = None
    if notebook_started_at_seconds is not None:
        if (
            isinstance(notebook_started_at_seconds, bool)
            or not isinstance(notebook_started_at_seconds, (int, float))
            or not math.isfinite(notebook_started_at_seconds)
            or notebook_started_at_seconds < 0.0
        ):
            raise PackagingError("notebook_started_at_seconds must be a finite monotonic time")
        normalized_notebook_start = float(notebook_started_at_seconds)
        if normalized_notebook_start > launcher_started_at:
            raise PackagingError("notebook_started_at_seconds cannot be in the future")
    runtime_anchor = (
        normalized_notebook_start if normalized_notebook_start is not None else launcher_started_at
    )
    hard_deadline_seconds = (
        runtime_anchor
        + float(FROZEN_COMPETITION_RUNTIME.official_total_runtime_seconds)
        - _FAILURE_RECEIPT_MARGIN_SECONDS
    )
    if hard_deadline_seconds <= launcher_started_at:
        raise PackagingError("competition runtime deadline was exhausted before launch")
    hard_timeout_enforced = _signal_deadline_available()
    if not agent_path.is_file():
        raise PackagingError(f"packaged agent wrapper is missing: {agent_path}")
    resolved_working_root = (working_root or Path.cwd()).resolve()
    resolved_working_root.mkdir(parents=True, exist_ok=True)
    framework_commit, framework_identity, framework_fixture = _validate_framework(
        framework_root, allow_test_fixture=allow_test_fixture
    )
    if not framework_fixture and not hard_timeout_enforced:
        error = PackagingError(
            "competition launch requires Linux main-thread signal deadline enforcement"
        )
        _write_launch_failure_receipt(
            resolved_working_root,
            stage="runtime-deadline-preflight",
            error=error,
            framework_identity=framework_identity,
            games=(),
            lifecycle=None,
            tournament_configured=False,
            tournament_finalized=False,
            tournament_receipt=None,
            notebook_started_at_seconds=normalized_notebook_start,
            hard_deadline_seconds=hard_deadline_seconds,
            hard_timeout_enforced=False,
        )
        raise error

    agents_directory = framework_root / "agents"
    prior_modules = dict(sys.modules)
    old_argv = sys.argv
    try:
        for name in tuple(sys.modules):
            if any(_matches_module_namespace(name, root) for root in _MANAGED_MODULE_ROOTS):
                del sys.modules[name]
        package = ModuleType("agents")
        package.__package__ = "agents"
        package.__path__ = [str(agents_directory)]
        dotenv_stub = _dotenv_stub()
        sys.modules["agents"] = package
        sys.modules["agents.tracing"] = _tracing_stub()
        sys.modules["dotenv"] = dotenv_stub

        with _sanitized_competition_environment(
            gateway_host=gateway_host,
            gateway_port=gateway_port,
            working_root=resolved_working_root,
        ):
            agent_module = import_module("agents.agent")
            swarm_module = import_module("agents.swarm")
            agent_base = getattr(agent_module, "Agent", None)
            playback = getattr(agent_module, "Playback", None)
            swarm_type = getattr(swarm_module, "Swarm", None)
            if not isinstance(agent_base, type) or not isinstance(swarm_type, type):
                raise PackagingError("competition Agents framework does not expose Agent and Swarm")

            module = _load_agent_module(agent_path)
            my_agent = getattr(module, "MyAgent", None)
            if not isinstance(my_agent, type) or not issubclass(my_agent, agent_base):
                raise PackagingError("agent/my_agent.py must expose MyAgent as an Agent subclass")

            package.__dict__["Agent"] = agent_base
            package.__dict__["Playback"] = playback
            package.__dict__["Swarm"] = swarm_type
            package.__dict__["AVAILABLE_AGENTS"] = {"myagent": my_agent}
            games = _freeze_environment_order(_discover_games(gateway_host, gateway_port))
            configure_tournament = getattr(my_agent, "configure_tournament", None)
            finalize_tournament = getattr(my_agent, "finalize_tournament", None)
            if not callable(configure_tournament) or not callable(finalize_tournament):
                error = PackagingError(
                    "competition agent requires configure_tournament and finalize_tournament hooks"
                )
                _write_launch_failure_receipt(
                    resolved_working_root,
                    stage="tournament-hook-preflight",
                    error=error,
                    framework_identity=framework_identity,
                    games=games,
                    lifecycle=None,
                    tournament_configured=False,
                    tournament_finalized=False,
                    tournament_receipt=None,
                    notebook_started_at_seconds=normalized_notebook_start,
                    hard_deadline_seconds=hard_deadline_seconds,
                    hard_timeout_enforced=hard_timeout_enforced,
                )
                raise error

            tournament_configured = False
            tournament_finalized = False
            tournament_receipt: JSONValue = None
            try:
                if normalized_notebook_start is None:
                    _call_with_hard_deadline(
                        "competition tournament configuration",
                        lambda: configure_tournament(games, resolved_working_root),
                        hard_deadline_seconds=hard_deadline_seconds,
                    )
                else:
                    _call_with_hard_deadline(
                        "competition tournament configuration",
                        lambda: configure_tournament(
                            games,
                            resolved_working_root,
                            notebook_started_at_seconds=normalized_notebook_start,
                        ),
                        hard_deadline_seconds=hard_deadline_seconds,
                    )
                tournament_configured = True
            except Exception as error:
                _, tournament_finalized, tournament_receipt = _finalize_tournament_hook(
                    my_agent,
                    hard_deadline_seconds=hard_deadline_seconds,
                )
                wrapped = PackagingError(
                    f"agent tournament configuration failed ({type(error).__name__})"
                )
                _write_launch_failure_receipt(
                    resolved_working_root,
                    stage="tournament-configuration",
                    error=wrapped,
                    framework_identity=framework_identity,
                    games=games,
                    lifecycle=None,
                    tournament_configured=False,
                    tournament_finalized=tournament_finalized,
                    tournament_receipt=tournament_receipt,
                    notebook_started_at_seconds=normalized_notebook_start,
                    hard_deadline_seconds=hard_deadline_seconds,
                    hard_timeout_enforced=hard_timeout_enforced,
                )
                raise wrapped from error

            sys.argv = ["arc3-competition-launcher", "--agent", "myagent"]
            swarm: Any | None = None
            lifecycle: _CompetitionLifecycleStats | None = None
            instrumented_arcade: _InstrumentedArcade | None = None
            stats = _SequentialThreadStats()
            run_error: BaseException | None = None
            try:
                swarm = cast(Any, swarm_type)(
                    "myagent", _gateway_url(gateway_host, gateway_port, "/"), list(games), tags=[]
                )
                arcade = getattr(swarm, "_arc", None)
                if arcade is None:
                    if not framework_fixture:
                        raise PackagingError("pinned Swarm did not expose its Arcade boundary")
                else:
                    operation_mode = getattr(arcade, "operation_mode", None)
                    operation_mode_value = getattr(operation_mode, "value", operation_mode)
                    if str(operation_mode_value).lower() != "competition":
                        raise PackagingError("competition Arcade did not enter competition mode")
                    lifecycle = _CompetitionLifecycleStats(expected_games=games)
                    instrumented_arcade = _InstrumentedArcade(
                        arcade,
                        lifecycle,
                        hard_deadline_seconds=hard_deadline_seconds,
                        before_scorecard_open=before_scorecard_open,
                        before_environment_make=before_environment_make,
                    )
                    swarm._arc = instrumented_arcade

                def sequential_thread(
                    group: object | None = None,
                    target: Callable[..., object] | None = None,
                    name: str | None = None,
                    args: tuple[object, ...] = (),
                    kwargs: dict[str, object] | None = None,
                    *,
                    daemon: bool | None = None,
                ) -> _SequentialThread:
                    return _SequentialThread(
                        stats,
                        group=group,
                        target=target,
                        name=name,
                        args=args,
                        kwargs=kwargs,
                        daemon=daemon,
                    )

                original_thread = getattr(swarm_module, "Thread", None)
                if original_thread is None:
                    raise PackagingError("pinned Swarm framework does not expose its Thread worker")
                swarm_module.__dict__["Thread"] = sequential_thread
                main_error: BaseException | None = None
                try:
                    swarm.main()
                except BaseException as error:
                    main_error = error
                finally:
                    swarm_module.__dict__["Thread"] = original_thread
                    if (
                        main_error is not None
                        and lifecycle is not None
                        and instrumented_arcade is not None
                        and lifecycle.scorecard_in_flight
                        and lifecycle.close_scorecard_count == 0
                        and lifecycle.opened_scorecard_id is not None
                    ):
                        try:
                            instrumented_arcade.close_scorecard(lifecycle.opened_scorecard_id)
                        except BaseException as closure_error:
                            raise PackagingError(
                                "competition launch failed and emergency scorecard closure failed"
                            ) from closure_error
                if main_error is not None:
                    raise main_error
            except BaseException as error:
                run_error = error
            finally:
                _, tournament_finalized, tournament_receipt = _finalize_tournament_hook(
                    my_agent,
                    hard_deadline_seconds=hard_deadline_seconds,
                )

            if run_error is not None:
                _write_launch_failure_receipt(
                    resolved_working_root,
                    stage="framework-run",
                    error=run_error,
                    framework_identity=framework_identity,
                    games=games,
                    lifecycle=lifecycle,
                    tournament_configured=tournament_configured,
                    tournament_finalized=tournament_finalized,
                    tournament_receipt=tournament_receipt,
                    notebook_started_at_seconds=normalized_notebook_start,
                    hard_deadline_seconds=hard_deadline_seconds,
                    hard_timeout_enforced=hard_timeout_enforced,
                )
            if not tournament_finalized:
                finalization_error = PackagingError(
                    "agent tournament finalization failed after scorecard closure"
                )
                _write_launch_failure_receipt(
                    resolved_working_root,
                    stage="tournament-finalization",
                    error=finalization_error,
                    framework_identity=framework_identity,
                    games=games,
                    lifecycle=lifecycle,
                    tournament_configured=tournament_configured,
                    tournament_finalized=False,
                    tournament_receipt=tournament_receipt,
                    notebook_started_at_seconds=normalized_notebook_start,
                    hard_deadline_seconds=hard_deadline_seconds,
                    hard_timeout_enforced=hard_timeout_enforced,
                )
                raise finalization_error from run_error
            if run_error is not None:
                raise run_error

            try:
                _validate_tournament_receipt(tournament_receipt, expected_games=games)
                if swarm is None:
                    raise PackagingError("pinned Swarm was not constructed")
                agents = getattr(swarm, "agents", None)
                if not isinstance(agents, list) or len(agents) != len(games):
                    raise PackagingError("pinned Swarm did not create exactly one agent per game")
                if len({id(agent) for agent in agents}) != len(agents):
                    raise PackagingError("pinned Swarm reused an agent across multiple games")
                if (
                    stats.started != len(games)
                    or stats.completed != len(games)
                    or stats.active != 0
                    or stats.max_active != 1
                ):
                    raise PackagingError(
                        "sequential Swarm orchestration produced invalid worker counts"
                    )
                if stats.failures:
                    raise PackagingError(
                        f"{stats.failures} sequential Swarm worker(s) failed; "
                        "scorecard closure completed before launcher failure"
                    )
                if lifecycle is not None:
                    lifecycle.validate_complete()
                dotenv_imported = any(
                    _matches_module_namespace(name, "dotenv")
                    and not (name == "dotenv" and sys.modules.get(name) is dotenv_stub)
                    for name in sys.modules
                )
                telemetry_imported = any(
                    _matches_module_namespace(name, "agentops") for name in sys.modules
                )
                if dotenv_imported or telemetry_imported:
                    raise PackagingError("competition launcher imported dotenv or telemetry code")
            except BaseException as error:
                _write_launch_failure_receipt(
                    resolved_working_root,
                    stage="launch-postflight",
                    error=error,
                    framework_identity=framework_identity,
                    games=games,
                    lifecycle=lifecycle,
                    tournament_configured=tournament_configured,
                    tournament_finalized=tournament_finalized,
                    tournament_receipt=tournament_receipt,
                    notebook_started_at_seconds=normalized_notebook_start,
                    hard_deadline_seconds=hard_deadline_seconds,
                    hard_timeout_enforced=hard_timeout_enforced,
                )
                raise

            return CompetitionLaunchReceipt(
                framework_commit=framework_commit,
                framework_identity=framework_identity,
                framework_fixture=framework_fixture,
                gateway_host=gateway_host,
                gateway_port=gateway_port,
                game_count=len(games),
                agent_count=len(agents),
                worker_count=stats.completed,
                max_concurrency=stats.max_active,
                orchestration=_ORCHESTRATION_ID,
                dotenv_imported=False,
                telemetry_imported=False,
                discovered_environments=games,
                lifecycle_enforced=lifecycle is not None,
                open_scorecard_count=(
                    lifecycle.open_scorecard_count if lifecycle is not None else 0
                ),
                close_scorecard_count=(
                    lifecycle.close_scorecard_count if lifecycle is not None else 0
                ),
                make_count=lifecycle.make_count if lifecycle is not None else 0,
                get_scorecard_during_flight_count=(
                    lifecycle.get_scorecard_during_flight_count if lifecycle is not None else 0
                ),
                all_environments_covered=(
                    lifecycle.all_environments_covered if lifecycle is not None else False
                ),
                tournament_configured=tournament_configured,
                tournament_finalized=tournament_finalized,
                tournament_receipt=tournament_receipt,
                notebook_started_at_seconds=normalized_notebook_start,
                hard_deadline_seconds=hard_deadline_seconds,
                hard_timeout_enforced=hard_timeout_enforced,
            )
    finally:
        sys.argv = old_argv
        for name in tuple(sys.modules):
            if any(_matches_module_namespace(name, root) for root in _MANAGED_MODULE_ROOTS):
                del sys.modules[name]
        sys.modules.update(
            {
                name: module
                for name, module in prior_modules.items()
                if any(_matches_module_namespace(name, root) for root in _MANAGED_MODULE_ROOTS)
            }
        )


__all__ = [
    "AGENTS_COMMIT",
    "SAFE_FRAMEWORK_FIXTURE_IDENTITY",
    "CompetitionLaunchReceipt",
    "launch_competition_framework",
]
