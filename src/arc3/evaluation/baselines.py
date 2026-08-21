"""Pinned Stage 13 baseline policies and their honest availability status."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from arc3.adapters import Observation
from arc3.errors import PolicyError
from arc3.perception.delta import measure_delta
from arc3.policy.baselines import RandomValidPolicy
from arc3.types import ActionName, ActionRequest, Coordinate, GameStateName

if TYPE_CHECKING:
    from arc3.policy import RunContext


class EvaluationPolicy(Protocol):
    """Stateful policy lifecycle used by isolated evaluation workers."""

    manages_trace: bool

    def select(self, observation: Observation) -> ActionRequest: ...

    def accept_consequence(self, observation: Observation) -> None: ...

    def close(self) -> None: ...


class _SelectPolicy(Protocol):
    def select(self, observation: Observation) -> ActionRequest: ...


@dataclass(frozen=True, slots=True)
class BaselineDescriptor:
    """Stable baseline identity, meaning, and current implementation status."""

    baseline_id: str
    agent: str
    title: str
    meaning: str
    status: str
    limitation: str | None = None

    def to_dict(self) -> dict[str, str | None]:
        return {
            "baseline_id": self.baseline_id,
            "agent": self.agent,
            "title": self.title,
            "meaning": self.meaning,
            "status": self.status,
            "limitation": self.limitation,
        }


_ORDER = (
    ActionName.ACTION1,
    ActionName.ACTION2,
    ActionName.ACTION3,
    ActionName.ACTION4,
    ActionName.ACTION5,
    ActionName.ACTION6,
    ActionName.ACTION7,
)
_SWEEP_AXIS = (0, 16, 32, 48, 63)
_SWEEP_COORDINATES = tuple(Coordinate(x, y) for y in _SWEEP_AXIS for x in _SWEEP_AXIS)


def _legal_actions(observation: Observation) -> tuple[ActionRequest, ...]:
    if observation.state in {GameStateName.GAME_OVER, GameStateName.NOT_PLAYED}:
        return (ActionRequest(ActionName.RESET),)
    if observation.state is GameStateName.WIN:
        raise PolicyError("the completed environment permits no further policy action")
    if observation.state is GameStateName.UNKNOWN:
        raise PolicyError("cannot act on an unknown environment state")
    available = set(observation.available_actions)
    actions = tuple(
        ActionRequest(name, Coordinate(32, 32) if name is ActionName.ACTION6 else None)
        for name in _ORDER
        if name in available
    )
    if not actions:
        raise PolicyError("the environment advertises no supported action")
    return actions


class NoveltyOnlyPolicy:
    """B2: favor actions whose observed consequences yielded novel states."""

    def __init__(self) -> None:
        self._previous_hash: str | None = None
        self._previous_action: ActionRequest | None = None
        self._trials: dict[ActionRequest, int] = {}
        self._novel_outcomes: dict[ActionRequest, set[str]] = {}

    def select(self, observation: Observation) -> ActionRequest:
        current_hash = str(observation.frames[-1].digest)
        if self._previous_action is not None and self._previous_hash != current_hash:
            self._novel_outcomes.setdefault(self._previous_action, set()).add(current_hash)
        legal = _legal_actions(observation)
        selected = max(
            legal,
            key=lambda action: (
                len(self._novel_outcomes.get(action, set())),
                -self._trials.get(action, 0),
                action.name.value,
            ),
        )
        self._trials[selected] = self._trials.get(selected, 0) + 1
        self._previous_hash = current_hash
        self._previous_action = selected
        return selected


class DeterministicCyclePolicy:
    """B1 cycle with a deterministic coarse coordinate sweep for ACTION6."""

    def __init__(self) -> None:
        self._action_ordinal = 0
        self._coordinate_ordinal = 0

    def select(self, observation: Observation) -> ActionRequest:
        legal = _legal_actions(observation)
        selected = legal[self._action_ordinal % len(legal)]
        self._action_ordinal += 1
        if selected.name is not ActionName.ACTION6:
            return selected
        coordinate = _SWEEP_COORDINATES[self._coordinate_ordinal % len(_SWEEP_COORDINATES)]
        self._coordinate_ordinal += 1
        return ActionRequest(ActionName.ACTION6, coordinate)


class TraceLocalStatisticsPolicy:
    """B3: retain exact local deltas and avoid repeated observed no-ops."""

    def __init__(self) -> None:
        self._previous: Observation | None = None
        self._previous_action: ActionRequest | None = None
        self._no_op_counts: dict[tuple[str, ActionRequest], int] = {}
        self._ordinal = 0

    def select(self, observation: Observation) -> ActionRequest:
        if self._previous is not None and self._previous_action is not None:
            delta = measure_delta(self._previous.frames[-1], observation.frames[-1])
            key = (str(self._previous.frames[-1].digest), self._previous_action)
            if delta.apparent_noop:
                self._no_op_counts[key] = self._no_op_counts.get(key, 0) + 1
            else:
                self._no_op_counts.pop(key, None)
        legal = _legal_actions(observation)
        state_hash = str(observation.frames[-1].digest)
        ranked = (
            tuple(action for action in legal if self._no_op_counts.get((state_hash, action), 0) < 2)
            or legal
        )
        selected = ranked[self._ordinal % len(ranked)]
        self._ordinal += 1
        self._previous = observation
        self._previous_action = selected
        return selected


class _CrashTestPolicy:
    """Private fault-injection policy used to verify abnormal-exit preservation."""

    def select(self, observation: Observation) -> ActionRequest:
        del observation
        os._exit(86)


class _ManagedBaselinePolicy:
    """Adapt a select-only baseline to the explicit evaluation lifecycle."""

    manages_trace = False

    def __init__(self, policy: _SelectPolicy) -> None:
        self._policy = policy

    def select(self, observation: Observation) -> ActionRequest:
        action = self._policy.select(observation)
        if not isinstance(action, ActionRequest):
            raise PolicyError("evaluation baseline returned a non-ActionRequest value")
        return action

    def accept_consequence(self, observation: Observation) -> None:
        del observation

    def close(self) -> None:
        return


class FullARC3EvaluationPolicy:
    """B4 adapter over the genuine integrated ARC3 controller."""

    manages_trace = True

    def __init__(self, context: RunContext) -> None:
        from arc3.policy import ARC3Controller, ControllerPreset

        self._controller = ARC3Controller(ControllerPreset.FULL)
        self._context = context
        self._started = False

    def select(self, observation: Observation) -> ActionRequest:
        if not self._started:
            self._controller.reset(self._context)
            self._controller.observe(observation)
            self._started = True
        return self._controller.choose_action().action

    def accept_consequence(self, observation: Observation) -> None:
        if not self._started:
            raise PolicyError("full ARC3 policy received a consequence before observation")
        self._controller.apply_consequence(observation)

    def close(self) -> None:
        self._controller.close()


BASELINES: tuple[BaselineDescriptor, ...] = (
    BaselineDescriptor(
        "B0",
        "random",
        "random valid",
        "Uniform seeded choice among advertised non-reset actions with uniform ACTION6 coordinates.",
        "supported",
    ),
    BaselineDescriptor(
        "B1",
        "cycle",
        "deterministic cycle",
        "Fixed action cycle with deterministic ACTION6 coordinate behavior.",
        "supported",
    ),
    BaselineDescriptor(
        "B2",
        "novelty",
        "novelty only",
        "Select by observed state novelty without a goal model or planner.",
        "supported",
    ),
    BaselineDescriptor(
        "B3",
        "trace",
        "trace plus local action statistics",
        "Measure exact frame deltas and suppress repeated state-conditioned no-ops.",
        "supported",
    ),
    BaselineDescriptor(
        "B4",
        "full",
        "full ARC3",
        "Integrated perception, hypotheses, retrodiction, world model, goals, planning, memory, and reopening.",
        "supported",
        None,
    ),
)

_BY_AGENT = {descriptor.agent: descriptor for descriptor in BASELINES}


def baseline_descriptor(agent: str) -> BaselineDescriptor:
    """Resolve a public agent name to its pinned baseline descriptor."""

    if agent == "crash-test":
        return BaselineDescriptor("TEST-CRASH", agent, agent, "fault injection", "supported")
    try:
        return _BY_AGENT[agent.strip().lower()]
    except KeyError as error:
        expected = ", ".join(_BY_AGENT)
        raise ValueError(f"unknown evaluation agent {agent!r}; expected {expected}") from error


def make_evaluation_policy(
    agent: str,
    *,
    seed: int,
    run_context: RunContext | None = None,
) -> EvaluationPolicy:
    """Construct a supported policy without silently substituting another baseline."""

    descriptor = baseline_descriptor(agent)
    if descriptor.status != "supported":
        raise PolicyError(descriptor.limitation or f"{descriptor.baseline_id} is unsupported")
    if descriptor.baseline_id == "B0":
        return _ManagedBaselinePolicy(RandomValidPolicy(seed))
    if descriptor.baseline_id == "B1":
        return _ManagedBaselinePolicy(DeterministicCyclePolicy())
    if descriptor.baseline_id == "B2":
        return _ManagedBaselinePolicy(NoveltyOnlyPolicy())
    if descriptor.baseline_id == "B3":
        return _ManagedBaselinePolicy(TraceLocalStatisticsPolicy())
    if descriptor.baseline_id == "B4":
        if run_context is None:
            raise PolicyError("B4 evaluation requires an explicit offline RunContext")
        return FullARC3EvaluationPolicy(run_context)
    if descriptor.baseline_id == "TEST-CRASH":
        return _ManagedBaselinePolicy(_CrashTestPolicy())
    raise PolicyError(f"no policy factory exists for {descriptor.baseline_id}")


__all__ = [
    "BASELINES",
    "BaselineDescriptor",
    "DeterministicCyclePolicy",
    "EvaluationPolicy",
    "FullARC3EvaluationPolicy",
    "NoveltyOnlyPolicy",
    "TraceLocalStatisticsPolicy",
    "baseline_descriptor",
    "make_evaluation_policy",
]
