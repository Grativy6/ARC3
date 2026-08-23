"""Narrow, credential-safe boundary around the pinned official ARC-AGI SDK."""

from __future__ import annotations

import importlib
import importlib.metadata
import logging
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from types import ModuleType
from typing import Protocol, cast
from urllib.parse import urlparse

import numpy as np

from arc3.adapters import (
    EnvironmentDescriptor,
    EnvironmentSession,
    Observation,
    ScoreRunSummary,
    ScoreSummary,
    validate_action_request,
)
from arc3.adapters.normalization import (
    normalize_frame_data,
    normalize_game_state,
    strict_nonnegative_int,
)
from arc3.config import ARC3Config
from arc3.errors import (
    AdapterError,
    ConfigurationError,
    DependencyUnavailableError,
    EnvironmentStateError,
    NetworkDisabledError,
)
from arc3.types import (
    ActionName,
    ActionRequest,
    EnvironmentMode,
    EvaluationSurface,
    GameId,
    JSONValue,
)

ARC_AGI_VERSION = "0.9.9"
ARCENGINE_VERSION = "0.9.3"
DEFAULT_BASE_URL = "https://three.arcprize.org"


class _EnvironmentInfoLike(Protocol):
    game_id: str
    title: str | None
    tags: list[str] | None
    baseline_actions: list[int] | None
    local_dir: str | None


class _WrapperLike(Protocol):
    scorecard_id: str
    observation_space: object | None

    def reset(self) -> object | None: ...

    def step(
        self,
        action: object,
        data: dict[str, object] | None = None,
        reasoning: dict[str, object] | None = None,
    ) -> object | None: ...


class _ArcadeLike(Protocol):
    operation_mode: object

    def get_environments(self) -> list[_EnvironmentInfoLike]: ...

    def make(
        self,
        game_id: str,
        seed: int = 0,
        scorecard_id: str | None = None,
        save_recording: bool = False,
        include_frame_data: bool = True,
        render_mode: str | None = None,
        renderer: object | None = None,
    ) -> _WrapperLike | None: ...

    def get_scorecard(self, scorecard_id: str | None = None) -> object | None: ...

    def close_scorecard(self, scorecard_id: str | None = None) -> object | None: ...


class _ArcadeFactory(Protocol):
    def __call__(
        self,
        *,
        arc_api_key: str,
        arc_base_url: str,
        operation_mode: object,
        environments_dir: str,
        recordings_dir: str,
        logger: logging.Logger,
    ) -> _ArcadeLike: ...


@dataclass(frozen=True, slots=True)
class _SDKBindings:
    arcade_factory: _ArcadeFactory
    operation_modes: Mapping[EnvironmentMode, object]
    game_actions: Mapping[ActionName, object]


def _attribute(module: ModuleType, name: str) -> object:
    try:
        return getattr(module, name)
    except AttributeError as error:
        raise DependencyUnavailableError(
            f"pinned official SDK is missing required symbol {module.__name__}.{name}"
        ) from error


def _member(value: object, name: str) -> object:
    try:
        return getattr(value, name)
    except AttributeError as error:
        raise DependencyUnavailableError(
            f"pinned official SDK value is missing required member {name}"
        ) from error


@lru_cache(maxsize=1)
def _load_sdk_bindings() -> _SDKBindings:
    """Load and verify the exact optional SDK versions only when requested."""

    try:
        arc_agi_version = importlib.metadata.version("arc-agi")
        arcengine_version = importlib.metadata.version("arcengine")
        arc_agi = importlib.import_module("arc_agi")
        arcengine = importlib.import_module("arcengine")
    except (ModuleNotFoundError, importlib.metadata.PackageNotFoundError) as error:
        raise DependencyUnavailableError(
            "official adapter requires the `official` dependency group"
        ) from error

    if arc_agi_version != ARC_AGI_VERSION or arcengine_version != ARCENGINE_VERSION:
        raise DependencyUnavailableError(
            "official SDK version mismatch: "
            f"expected arc-agi {ARC_AGI_VERSION} and arcengine {ARCENGINE_VERSION}"
        )

    operation_mode_type = _attribute(arc_agi, "OperationMode")
    game_action_type = _attribute(arcengine, "GameAction")
    operation_modes = {
        EnvironmentMode.LOCAL: _member(operation_mode_type, "OFFLINE"),
        EnvironmentMode.ONLINE: _member(operation_mode_type, "ONLINE"),
        EnvironmentMode.COMPETITION: _member(operation_mode_type, "COMPETITION"),
    }
    game_actions = {name: _member(game_action_type, name.value) for name in ActionName}

    _silence_upstream_module_logger("arc_agi.scorecard")
    return _SDKBindings(
        arcade_factory=cast(_ArcadeFactory, _attribute(arc_agi, "Arcade")),
        operation_modes=operation_modes,
        game_actions=game_actions,
    )


def _silence_upstream_module_logger(name: str) -> None:
    """Remove SDK-installed stdout handlers from a credential-adjacent boundary."""

    logger = logging.getLogger(name)
    logger.handlers.clear()
    logger.addHandler(logging.NullHandler())
    logger.setLevel(logging.CRITICAL + 1)
    logger.propagate = False


def _silent_upstream_logger() -> logging.Logger:
    logger = logging.getLogger("arc3.upstream.arc_agi.silent")
    logger.handlers.clear()
    logger.addHandler(logging.NullHandler())
    logger.setLevel(logging.CRITICAL + 1)
    logger.propagate = False
    return logger


def _numeric_float(value: object, *, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float, np.integer, np.floating)):
        raise AdapterError(f"upstream {field} must be numeric")
    return float(value)


def _sequence_of_ints(
    value: object, *, field: str, allow_negative: bool = False
) -> tuple[int, ...]:
    if value is None:
        return ()
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise AdapterError(f"upstream {field} must be a sequence")
    normalized: list[int] = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, (int, np.integer)):
            raise AdapterError(f"upstream {field} values must be integers")
        result = int(item)
        if not allow_negative and result < 0:
            raise AdapterError(f"upstream {field} values must be non-negative")
        normalized.append(result)
    return tuple(normalized)


def _sequence_of_floats(value: object, *, field: str) -> tuple[float, ...]:
    if value is None:
        return ()
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise AdapterError(f"upstream {field} must be a sequence")
    return tuple(_numeric_float(item, field=field) for item in value)


def _normalize_scorecard(
    scorecard: object,
    *,
    surface: EvaluationSurface,
    scorer: str,
) -> ScoreSummary:
    try:
        total_score = _numeric_float(_member(scorecard, "score"), field="score")
    except (TypeError, ValueError, AttributeError, DependencyUnavailableError) as error:
        raise AdapterError("upstream scorecard has no numeric score") from error

    raw_groups = getattr(scorecard, "environments", ())
    if isinstance(raw_groups, (str, bytes)) or not isinstance(raw_groups, Sequence):
        raise AdapterError("upstream scorecard environments must be a sequence")
    runs: list[ScoreRunSummary] = []
    for group in raw_groups:
        raw_game_id = getattr(group, "id", None)
        if not isinstance(raw_game_id, str) or not raw_game_id:
            raise AdapterError("upstream score group has no game ID")
        raw_runs = getattr(group, "runs", ())
        if isinstance(raw_runs, (str, bytes)) or not isinstance(raw_runs, Sequence):
            raise AdapterError("upstream score runs must be a sequence")
        for run in raw_runs:
            raw_completed = getattr(run, "completed", False)
            if raw_completed is not None and not isinstance(raw_completed, bool):
                raise AdapterError("upstream completed flag must be boolean")
            completed = raw_completed if raw_completed is not None else False
            raw_resets = getattr(run, "resets", 0)
            runs.append(
                ScoreRunSummary(
                    game_id=GameId(raw_game_id),
                    score=_numeric_float(getattr(run, "score", 0.0), field="run.score"),
                    levels_completed=strict_nonnegative_int(
                        getattr(run, "levels_completed", 0), field="levels_completed"
                    ),
                    actions=strict_nonnegative_int(getattr(run, "actions", 0), field="actions"),
                    resets=strict_nonnegative_int(
                        0 if raw_resets is None else raw_resets, field="resets"
                    ),
                    state=normalize_game_state(getattr(run, "state", None)),
                    completed=completed,
                    level_scores=_sequence_of_floats(
                        getattr(run, "level_scores", None), field="level_scores"
                    ),
                    level_actions=_sequence_of_ints(
                        getattr(run, "level_actions", None), field="level_actions"
                    ),
                    level_baseline_actions=_sequence_of_ints(
                        getattr(run, "level_baseline_actions", None),
                        field="level_baseline_actions",
                        allow_negative=True,
                    ),
                )
            )
    return ScoreSummary(
        surface=surface,
        verified=True,
        scorer=scorer,
        score=total_score,
        runs=tuple(runs),
    )


class ArcAGISession(EnvironmentSession):
    """One normalized official-SDK session with pre-submit validation."""

    def __init__(
        self,
        *,
        arcade: _ArcadeLike,
        wrapper: _WrapperLike,
        bindings: _SDKBindings,
        initial_observation: Observation,
        surface: EvaluationSurface,
        scorer: str,
    ) -> None:
        self._arcade = arcade
        self._wrapper = wrapper
        self._bindings = bindings
        self._observation = initial_observation
        self._surface = surface
        self._scorer = scorer
        self._closed = False
        self._closed_scorecard: ScoreSummary | None = None

    @property
    def observation(self) -> Observation:
        return self._observation

    def _ensure_open(self) -> None:
        if self._closed:
            raise EnvironmentStateError("environment session is closed")

    def step(
        self,
        action: ActionRequest,
        *,
        reasoning: Mapping[str, JSONValue] | None = None,
    ) -> Observation:
        self._ensure_open()
        validate_action_request(self._observation, action)
        if action.name is ActionName.RESET:
            return self.reset()
        data: dict[str, object] | None = None
        if action.coordinate is not None:
            data = {"x": action.coordinate.x, "y": action.coordinate.y}
        normalized_reasoning = (
            cast(dict[str, object], dict(reasoning)) if reasoning is not None else None
        )
        try:
            response = self._wrapper.step(
                self._bindings.game_actions[action.name],
                data=data,
                reasoning=normalized_reasoning,
            )
        except Exception as error:
            raise AdapterError(
                f"official SDK step failed ({type(error).__name__}); upstream details suppressed"
            ) from None
        if response is None:
            raise AdapterError("official SDK step returned no observation")
        self._observation = normalize_frame_data(response)
        return self._observation

    def reset(self) -> Observation:
        self._ensure_open()
        try:
            response = self._wrapper.reset()
        except Exception as error:
            raise AdapterError(
                f"official SDK reset failed ({type(error).__name__}); upstream details suppressed"
            ) from None
        if response is None:
            raise AdapterError("official SDK reset returned no observation")
        self._observation = normalize_frame_data(response)
        return self._observation

    def scorecard(self) -> ScoreSummary | None:
        if self._closed:
            return self._closed_scorecard
        try:
            card = self._arcade.get_scorecard(self._wrapper.scorecard_id)
        except Exception as error:
            raise AdapterError(
                f"official SDK scorecard failed ({type(error).__name__}); upstream details suppressed"
            ) from None
        if card is None:
            return None
        return _normalize_scorecard(card, surface=self._surface, scorer=self._scorer)

    def close(self) -> ScoreSummary | None:
        if self._closed:
            return self._closed_scorecard
        try:
            card = self._arcade.close_scorecard(self._wrapper.scorecard_id)
        except Exception as error:
            raise AdapterError(
                f"official SDK close failed ({type(error).__name__}); upstream details suppressed"
            ) from None
        self._closed = True
        if card is not None:
            self._closed_scorecard = _normalize_scorecard(
                card, surface=self._surface, scorer=self._scorer
            )
        return self._closed_scorecard


class ArcAGIAdapter:
    """Explicit-mode adapter that keeps all official SDK values at its edge."""

    def __init__(
        self,
        config: ARC3Config,
        *,
        environments_dir: str | Path = "environment_files",
        recordings_dir: str | Path = "recordings",
        base_url: str | None = None,
        api_key: str | None = None,
        save_recording: bool = False,
        include_frame_data: bool = True,
        result_surface: EvaluationSurface | None = None,
        environ: Mapping[str, str] | None = None,
        bindings: _SDKBindings | None = None,
    ) -> None:
        if config.mode is EnvironmentMode.SYNTHETIC:
            raise ConfigurationError("use SyntheticAdapter for synthetic mode")
        if config.mode is EnvironmentMode.ONLINE and not config.network_enabled:
            raise NetworkDisabledError("online SDK mode requires network_enabled=true")

        self._config = config
        self._environments_dir = str(Path(environments_dir).resolve())
        self._recordings_dir = str(Path(recordings_dir).resolve())
        self._explicit_base_url = base_url
        self._explicit_api_key = api_key
        self._save_recording = save_recording
        self._include_frame_data = include_frame_data
        self._environ = environ
        self._bindings_override = bindings
        self._arcade: _ArcadeLike | None = None

        if result_surface is None:
            if config.mode is EnvironmentMode.LOCAL:
                result_surface = EvaluationSurface.LOCAL_PUBLIC
            elif config.mode is EnvironmentMode.ONLINE:
                result_surface = EvaluationSurface.ONLINE_PUBLIC
            else:
                raise ConfigurationError(
                    "competition scorecards require an explicit evidence surface"
                )
        self._result_surface = result_surface
        self._preflight_environment()

    def _environment(self) -> Mapping[str, str]:
        return os.environ if self._environ is None else self._environ

    def _expected_operation_mode(self) -> str:
        return {
            EnvironmentMode.LOCAL: "offline",
            EnvironmentMode.ONLINE: "online",
            EnvironmentMode.COMPETITION: "competition",
        }[self._config.mode]

    def _resolved_base_url(self) -> str:
        if self._explicit_base_url is not None:
            return self._explicit_base_url
        return self._environment().get("ARC_BASE_URL", DEFAULT_BASE_URL)

    def _preflight_environment(self) -> None:
        upstream_mode = self._environment().get("OPERATION_MODE", "").strip().lower()
        expected_mode = self._expected_operation_mode()
        if upstream_mode and upstream_mode != expected_mode:
            raise ConfigurationError(
                "upstream OPERATION_MODE conflicts with first-party mode; "
                f"expected {expected_mode!r}, got {upstream_mode!r}"
            )
        if self._config.mode is EnvironmentMode.COMPETITION:
            parsed = urlparse(self._resolved_base_url())
            if parsed.hostname not in {"127.0.0.1", "::1", "localhost"}:
                raise NetworkDisabledError(
                    "competition adapter permits only an explicit loopback SDK endpoint"
                )

    def _bindings(self) -> _SDKBindings:
        return self._bindings_override or _load_sdk_bindings()

    def _ensure_arcade(self) -> _ArcadeLike:
        if self._arcade is not None:
            return self._arcade
        bindings = self._bindings()
        self._preflight_environment()
        environment = self._environment()
        api_key = (
            self._explicit_api_key
            if self._explicit_api_key is not None
            else environment.get("ARC_API_KEY", "")
        )
        try:
            arcade = bindings.arcade_factory(
                arc_api_key=api_key,
                arc_base_url=self._resolved_base_url(),
                operation_mode=bindings.operation_modes[self._config.mode],
                environments_dir=self._environments_dir,
                recordings_dir=self._recordings_dir,
                logger=_silent_upstream_logger(),
            )
        except Exception as error:
            raise AdapterError(
                f"official SDK initialization failed ({type(error).__name__}); "
                "upstream details suppressed"
            ) from None
        resolved_mode = str(getattr(arcade.operation_mode, "value", arcade.operation_mode))
        if resolved_mode != self._expected_operation_mode():
            raise ConfigurationError(
                f"official SDK resolved unexpected operation mode {resolved_mode!r}"
            )
        self._arcade = arcade
        return arcade

    def list_games(self) -> tuple[EnvironmentDescriptor, ...]:
        arcade = self._ensure_arcade()
        try:
            upstream_environments = arcade.get_environments()
        except Exception as error:
            raise AdapterError(
                f"official SDK discovery failed ({type(error).__name__}); upstream details suppressed"
            ) from None

        descriptors: dict[str, EnvironmentDescriptor] = {}
        for environment in upstream_environments:
            game_id = environment.game_id
            if not isinstance(game_id, str) or not game_id.strip():
                raise AdapterError("official SDK returned an environment without a game ID")
            raw_tags = environment.tags
            if isinstance(raw_tags, (str, bytes)):
                raise AdapterError(f"official SDK returned invalid tags for {game_id}")
            tags = tuple(raw_tags or ())
            if any(not isinstance(tag, str) for tag in tags):
                raise AdapterError(f"official SDK returned invalid tags for {game_id}")
            baseline_actions = _sequence_of_ints(
                environment.baseline_actions, field=f"{game_id}.baseline_actions"
            )
            descriptor = EnvironmentDescriptor(
                game_id=GameId(game_id),
                title=environment.title,
                tags=tags,
                baseline_actions=baseline_actions,
                locally_available=environment.local_dir is not None,
            )
            previous = descriptors.get(game_id)
            if previous is None or (
                descriptor.locally_available and not previous.locally_available
            ):
                descriptors[game_id] = descriptor
        return tuple(descriptors[key] for key in sorted(descriptors))

    def open(self, game_id: str, *, seed: int | None = None) -> ArcAGISession:
        if not game_id.strip():
            raise ConfigurationError("game_id must not be empty")
        selected_seed = self._config.seed if seed is None else seed
        if isinstance(selected_seed, bool) or not -(2**63) <= selected_seed < 2**63:
            raise ConfigurationError("seed must be a signed 64-bit integer")
        arcade = self._ensure_arcade()
        try:
            wrapper = arcade.make(
                game_id,
                seed=selected_seed,
                save_recording=self._save_recording,
                include_frame_data=self._include_frame_data,
            )
        except Exception as error:
            raise AdapterError(
                f"official SDK make failed ({type(error).__name__}); upstream details suppressed"
            ) from None
        if wrapper is None:
            raise AdapterError(f"official SDK could not create environment {game_id!r}")
        if wrapper.observation_space is None:
            raise AdapterError(
                f"official SDK created {game_id!r} without an initial reset observation"
            )
        initial = normalize_frame_data(wrapper.observation_space)
        scorer_kind = (
            "local ScorecardManager"
            if self._config.mode is EnvironmentMode.LOCAL
            else "remote scorecard"
        )
        return ArcAGISession(
            arcade=arcade,
            wrapper=wrapper,
            bindings=self._bindings(),
            initial_observation=initial,
            surface=self._result_surface,
            scorer=f"arc-agi=={ARC_AGI_VERSION} {scorer_kind}",
        )


__all__ = [
    "ARCENGINE_VERSION",
    "ARC_AGI_VERSION",
    "ArcAGIAdapter",
    "ArcAGISession",
    "normalize_frame_data",
]
