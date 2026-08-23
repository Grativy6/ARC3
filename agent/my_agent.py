"""Thin official ARC-AGI-3 wrapper around :class:`arc3.policy.ARC3Controller`.

This module owns only framework normalization and action translation. All
selection, trace, model, goal, planning, recovery, and checkpoint behavior is
implemented once in ``src/arc3/policy``.
"""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass, replace
from enum import StrEnum
from importlib import import_module
from pathlib import Path
from typing import ClassVar

from arc3.adapters.normalization import normalize_frame_data
from arc3.competition_runtime import FROZEN_COMPETITION_RUNTIME
from arc3.config import ARC3Config, derive_seed
from arc3.errors import ConfigurationError
from arc3.policy import ARC3Controller, ControllerPhase, ControllerPreset, RunContext
from arc3.trace.canonical import sha256_json
from arc3.types import ActionRequest, EnvironmentMode


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

    @property
    def name(self) -> str:
        return self.agent_name


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
    """Instance-local request data paired with the pinned action vocabulary.

    ``arcengine.GameAction`` is an ``Enum`` whose members are process-wide
    singletons. Its ``set_data`` method mutates the member, so returning a
    configured ``ACTION6`` from one Swarm thread can be overwritten by another
    thread before the pinned Agent serializes the request. Keep the payload in
    this immutable per-decision envelope and submit it explicitly instead.
    """

    member: object
    payload_items: tuple[tuple[str, object], ...]

    @property
    def name(self) -> str:
        name = getattr(self.member, "name", None)
        if not isinstance(name, str):
            raise RuntimeError("official action member has no string name")
        return name

    def payload(self) -> dict[str, object]:
        """Return a fresh request payload for the framework boundary."""

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


class MyAgent(_AgentBase):  # type: ignore[misc,valid-type]
    """Official wrapper using the exact production controller implementation."""

    MAX_ACTIONS = FROZEN_COMPETITION_RUNTIME.max_actions

    def __init__(self, *args: object, **kwargs: object) -> None:
        forwarded = dict(kwargs)
        self._root_seed = _parse_root_seed(forwarded.pop("seed", forwarded.pop("root_seed", None)))
        super().__init__(*args, **forwarded)
        self._controller: ARC3Controller | None = None

    @property
    def name(self) -> str:
        base_name = getattr(super(), "name", type(self).__name__.lower())
        return f"{base_name}.arc3-controller-v1"

    def is_done(self, frames: list[object], latest_frame: object) -> bool:
        del frames
        return _enum_name(getattr(latest_frame, "state", "UNKNOWN")) == "WIN"

    def _start_controller(self, observation_game_id: str) -> ARC3Controller:
        # derive_seed is an unsigned 64-bit component seed while ARC3Config's
        # portable contract is signed 64-bit. Preserve determinism inside the
        # accepted non-negative half of that range.
        derived_seed = derive_seed(self._root_seed, "official-wrapper") & ((1 << 63) - 1)
        identity = sha256_json({"seed": derived_seed, "scope": "official-wrapper"}).removeprefix(
            "sha256:"
        )[:16]
        runtime_root = Path(tempfile.mkdtemp(prefix=f"arc3-agent-{identity}-"))
        config = ARC3Config(
            mode=EnvironmentMode.COMPETITION,
            seed=derived_seed,
            network_enabled=False,
            profile="competition",
            trace_root=str(runtime_root / "trace"),
            artifact_root=str(runtime_root / "artifacts"),
            budgets=FROZEN_COMPETITION_RUNTIME.budgets(),
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
                source_version="0.1",
            )
        )
        return controller

    def choose_action(self, frames: list[object], latest_frame: object) -> object:
        """Translate one controller decision to the pinned framework vocabulary."""

        del frames
        # The pinned Agents runner reconstructs FrameData without carrying the
        # environment's action_input.  Pydantic then supplies a RESET default,
        # which is not an acknowledgement of the action just submitted.  This
        # wrapper boundary therefore marks action identity unavailable; direct
        # adapters retain the controller's strict returned-action validation.
        observation = replace(normalize_frame_data(latest_frame), returned_action=None)
        if self._controller is None:
            self._controller = self._start_controller(str(observation.game_id))
            self._controller.observe(observation)
        elif self._controller.phase is ControllerPhase.AWAITING_CONSEQUENCE:
            self._controller.apply_consequence(observation)
        elif self._controller.phase is ControllerPhase.NEW:
            self._controller.observe(observation)
        decision = self._controller.choose_action()
        return _translate_action(decision.action)

    def do_action_request(self, action: object) -> object:
        """Submit immutable per-decision data at the pinned request boundary."""

        if not isinstance(action, _FrameworkActionRequest):
            raise RuntimeError("official wrapper received an unsealed action request")
        environment = getattr(self, "arc_env", None)
        step = getattr(environment, "step", None)
        if not callable(step):
            raise RuntimeError("official wrapper has no callable environment step")
        raw = step(action.member, data=action.payload(), reasoning=None)
        converter = getattr(self, "_convert_raw_frame_data", None)
        if not callable(converter):
            raise RuntimeError("official wrapper has no frame conversion boundary")
        return converter(raw)


__all__ = ["MyAgent"]
