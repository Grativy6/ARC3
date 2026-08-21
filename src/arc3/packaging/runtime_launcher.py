"""Fail-closed launcher for the pinned platform-supplied Agents framework."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import sys
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from importlib import import_module
from pathlib import Path
from types import ModuleType
from typing import Any, cast
from urllib.request import ProxyHandler, Request, build_opener

from arc3.packaging.models import PackagingError
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
_PINNED_FILES = {
    "LICENSE": "d3f580d1aeb46a801279029bd5f06d099a6dcac0cd304dcf61acaed933e8cc40",
    "agents/agent.py": "500a9b9055aa5023a84b2b19bc9a41cb53dff03b3224b8d1ceb00e738709256f",
    "agents/recorder.py": "e3bb22cbe67180ee8cf3a207faaada79d836c8a16e4180310ea1a34616ffef9a",
    "agents/swarm.py": "c1d35066acfccb0b982bc33bb07a732d70da4d938c80ce3cdafd67b1018212cc",
}
_ORCHESTRATION_ID = "arc3.sequential-pinned-swarm.v1"


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

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "dotenv_imported": self.dotenv_imported,
            "framework_commit": self.framework_commit,
            "framework_identity": self.framework_identity,
            "framework_fixture": self.framework_fixture,
            "agent_count": self.agent_count,
            "game_count": self.game_count,
            "gateway_host": self.gateway_host,
            "gateway_port": self.gateway_port,
            "max_concurrency": self.max_concurrency,
            "orchestration": self.orchestration,
            "telemetry_imported": self.telemetry_imported,
            "worker_count": self.worker_count,
        }


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


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


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

    for relative, expected in _PINNED_FILES.items():
        path = framework_root / relative
        if not path.is_file() or _sha256(path) != expected:
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
        raise PackagingError(
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
        "OPERATION_MODE": "online",
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
) -> CompetitionLaunchReceipt:
    """Run only the pinned framework core against the competition-local gateway."""

    framework_root = framework_root.resolve()
    agent_path = agent_path.resolve()
    if gateway_host not in _ALLOWED_GATEWAY_HOSTS:
        raise PackagingError("gateway host must be the Kaggle sidecar name or loopback")
    if gateway_port <= 0 or gateway_port > 65535:
        raise PackagingError("gateway_port must be in 1..65535")
    if not agent_path.is_file():
        raise PackagingError(f"packaged agent wrapper is missing: {agent_path}")
    resolved_working_root = (working_root or Path.cwd()).resolve()
    resolved_working_root.mkdir(parents=True, exist_ok=True)
    framework_commit, framework_identity, framework_fixture = _validate_framework(
        framework_root, allow_test_fixture=allow_test_fixture
    )

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
            games = _discover_games(gateway_host, gateway_port)
            sys.argv = ["arc3-competition-launcher", "--agent", "myagent"]
            swarm = cast(Any, swarm_type)(
                "myagent", _gateway_url(gateway_host, gateway_port, "/"), list(games), tags=[]
            )
            stats = _SequentialThreadStats()

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
            try:
                cast(Any, swarm).main()
            finally:
                swarm_module.__dict__["Thread"] = original_thread

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
                    f"{stats.failures} sequential Swarm worker(s) failed before scorecard closure"
                )
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
