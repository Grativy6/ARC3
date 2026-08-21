"""Evaluator-only oracle, self-tests, recording, and measured baselines."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import fields
from typing import Protocol

from arc3.adapters import Observation
from arc3.policy.baselines import ActionCyclePolicy, RandomValidPolicy
from arc3.types import ActionName, ActionRequest, Coordinate, GameStateName, JSONValue

from ._engine import (
    _EpisodeSpec,
    advance,
    build_catalog,
    false_leading_action,
    goal_description,
    initial_state,
    reset_state,
    solve,
    state_token,
)
from .models import (
    BaselineMeasurement,
    EpisodeGroundTruth,
    EpisodeRecord,
    EvaluatedStep,
    LabCase,
    LabPartition,
    RuleFamily,
    TransitionTruth,
)
from .session import LabSession


class LabPolicy(Protocol):
    """Minimal policy surface accepted by the fast batch runner."""

    def select(self, observation: Observation) -> ActionRequest: ...


class EvaluatorEpisode:
    """Evaluator-owned episode pairing an opaque session with a shadow oracle."""

    __slots__ = ("_spec", "_state", "session", "truth")

    def __init__(self, spec: _EpisodeSpec) -> None:
        plan = solve(spec)
        primary = false_leading_action(spec)
        false_prefix: tuple[ActionRequest, ...] = ()
        contradiction: ActionRequest | None = None
        if spec.family is RuleFamily.FALSE_INITIAL_HYPOTHESIS:
            repeated = ActionRequest(primary)
            false_prefix = (repeated, repeated)
            contradiction = repeated
        self.truth = EpisodeGroundTruth(
            case_id=spec.case.case_id,
            family=spec.family,
            partition=spec.case.partition,
            seed=spec.case.seed,
            goal=goal_description(spec.family),
            transition_rule=spec.family.value,
            action_semantics=tuple(
                (action.value, semantic) for action, semantic in spec.action_map
            ),
            grid_size=spec.size,
            palette=spec.palette,
            player_shape=spec.player_shape,
            target_shape=spec.target_shape,
            start=Coordinate(*spec.start),
            target=Coordinate(*spec.target),
            distractors=tuple(Coordinate(*point) for point in spec.distractors),
            walls=tuple(Coordinate(*point) for point in sorted(spec.walls)),
            oracle_plan=plan,
            false_leading_prefix=false_prefix,
            contradiction_action=contradiction,
            reversible_consequences=spec.reversible,
        )
        self._spec = spec
        self._state = initial_state(spec)
        self.session = LabSession(spec)

    def take(
        self,
        action: ActionRequest,
        *,
        reasoning: Mapping[str, JSONValue] | None = None,
    ) -> EvaluatedStep:
        before = self._state
        if action.name is ActionName.RESET:
            after = reset_state(self._spec, before)
            effects: tuple[str, ...] = ("episode-reset",)
            contradiction = False
        else:
            transition = advance(self._spec, before, action)
            after = transition.state
            effects = transition.effects
            contradiction = transition.contradiction
        observation = self.session.step(action, reasoning=reasoning)
        self._state = after
        if observation.state is not after.terminal:
            raise AssertionError("production session diverged from evaluator shadow state")
        return EvaluatedStep(
            observation=observation,
            truth=TransitionTruth(
                step=after.steps,
                family=self._spec.family,
                action=action,
                before_state=state_token(before),
                after_state=state_token(after),
                effects=effects,
                goal_reached=after.terminal is GameStateName.WIN,
                contradiction_revealed=contradiction,
            ),
        )


class LabEvaluator:
    """Explicit evaluator boundary that alone exposes procedural ground truth."""

    def __init__(
        self,
        *,
        partition: LabPartition = LabPartition.DEVELOPMENT,
        root_seed: int = 0,
        count: int = 15,
    ) -> None:
        self.partition = LabPartition(partition)
        self.root_seed = root_seed
        self._catalog = build_catalog(self.partition, root_seed=root_seed, count=count)
        self._specs = {case.case_id: spec for case, spec in self._catalog}

    def cases(self) -> tuple[LabCase, ...]:
        return tuple(case for case, _spec in self._catalog)

    def open(self, case: LabCase | str) -> EvaluatorEpisode:
        case_id = case.case_id if isinstance(case, LabCase) else case
        try:
            spec = self._specs[case_id]
        except KeyError as error:
            raise ValueError(f"case {case_id!r} is outside this evaluator catalog") from error
        return EvaluatorEpisode(spec)

    def ground_truth(self, case: LabCase | str) -> EpisodeGroundTruth:
        """Return evaluator-only annotations without executing the oracle plan."""

        return self.open(case).truth

    def assert_solvable(self) -> None:
        """Replay every generated oracle plan and require exact completion."""

        for case, _spec in self._catalog:
            episode = self.open(case)
            for action in episode.truth.oracle_plan:
                episode.take(action, reasoning={"category": "evaluator-oracle"})
            if episode.session.observation.state is not GameStateName.WIN:
                raise AssertionError(f"oracle plan did not solve {case.case_id}")

    def assert_no_observation_leakage(self) -> None:
        """Reject goal/rule/oracle fields from the complete production observation graph."""

        forbidden = {
            "family",
            "goal",
            "oracle",
            "partition",
            "rule",
            "solution",
            "target",
            "transition",
        }
        observation_fields = {field.name.lower() for field in fields(Observation)}
        if observation_fields & forbidden:
            raise AssertionError("normalized Observation type contains an evaluator-only field")
        for case, _spec in self._catalog:
            observation = LabSession(self._specs[case.case_id]).observation
            public_text = " ".join(
                (
                    str(observation.game_id),
                    *(key for key, _value in observation.upstream_metadata),
                    *(descriptor.value for descriptor in observation.available_actions),
                )
            ).lower()
            leaked = sorted(token for token in forbidden if token in public_text)
            if leaked:
                raise AssertionError(
                    f"production observation for {case.case_id} leaks {', '.join(leaked)}"
                )


def _run_episode(
    episode: EvaluatorEpisode, policy: LabPolicy, *, max_actions: int
) -> EpisodeRecord:
    actions: list[ActionRequest] = []
    frame_hashes = [str(episode.session.observation.frames[-1].digest)]
    for _ordinal in range(max_actions):
        if episode.session.observation.state is GameStateName.WIN:
            break
        action = policy.select(episode.session.observation)
        step = episode.take(action, reasoning={"category": "measured-baseline"})
        actions.append(action)
        frame_hashes.append(str(step.observation.frames[-1].digest))
    observation = episode.session.observation
    return EpisodeRecord(
        case_id=episode.truth.case_id,
        family=episode.truth.family,
        seed=episode.truth.seed,
        completed=observation.state is GameStateName.WIN,
        final_state=observation.state,
        actions=tuple(actions),
        frame_hashes=tuple(frame_hashes),
    )


def run_batch(
    evaluator: LabEvaluator,
    policy_factory: Callable[[int], LabPolicy],
    *,
    max_actions: int = 64,
) -> tuple[EpisodeRecord, ...]:
    """Execute and record a deterministic in-memory batch without filesystem overhead."""

    if isinstance(max_actions, bool) or max_actions <= 0:
        raise ValueError("max_actions must be a positive integer")
    return tuple(
        _run_episode(evaluator.open(case), policy_factory(case.seed), max_actions=max_actions)
        for case in evaluator.cases()
    )


def _random_policy(seed: int) -> LabPolicy:
    return RandomValidPolicy(seed)


def _cycle_policy(seed: int) -> LabPolicy:
    del seed
    return ActionCyclePolicy()


def measure_baseline(
    *,
    partition: LabPartition,
    root_seed: int,
    episodes: int = 30,
    max_actions: int = 64,
    policy: str = "random",
) -> BaselineMeasurement:
    """Measure a pinned generic baseline on a predeclared synthetic partition."""

    evaluator = LabEvaluator(partition=partition, root_seed=root_seed, count=episodes)
    if policy == "random":
        factory = _random_policy
    elif policy == "cycle":
        factory = _cycle_policy
    else:
        raise ValueError("policy must be 'random' or 'cycle'")
    records = run_batch(evaluator, factory, max_actions=max_actions)
    completed = sum(record.completed for record in records)
    actions = sum(
        action.name is not ActionName.RESET for record in records for action in record.actions
    )
    resets = sum(action.name is ActionName.RESET for record in records for action in record.actions)
    return BaselineMeasurement(
        policy=policy,
        partition=partition,
        root_seed=root_seed,
        episodes=episodes,
        completed=completed,
        environment_actions=actions,
        resets=resets,
        completion_rate=completed / episodes,
        mean_actions=actions / episodes,
        scorer="arc3.lab.completion-rate.v1",
        records=records,
    )


def available_rule_families() -> tuple[RuleFamily, ...]:
    """Return the complete stable family registry for coverage checks."""

    return tuple(RuleFamily)


__all__ = [
    "EvaluatorEpisode",
    "LabEvaluator",
    "LabPolicy",
    "available_rule_families",
    "measure_baseline",
    "run_batch",
]
