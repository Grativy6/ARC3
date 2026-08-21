"""Unit tests for evaluator-only transition and contradiction annotations."""

from __future__ import annotations

from arc3.lab import EvaluatorEpisode, LabEvaluator, LabPartition, RuleFamily
from arc3.types import GameStateName


def _episode_for_family(evaluator: LabEvaluator, family: RuleFamily) -> EvaluatorEpisode:
    case = next(case for case in evaluator.cases() if evaluator.ground_truth(case).family is family)
    return evaluator.open(case)


def test_false_leading_evidence_is_followed_by_explicit_contradiction() -> None:
    evaluator = LabEvaluator(
        partition=LabPartition.HELD_OUT_FAMILIES,
        root_seed=33,
        count=3,
    )
    episode = _episode_for_family(evaluator, RuleFamily.FALSE_INITIAL_HYPOTHESIS)
    prefix = episode.truth.false_leading_prefix

    assert len(prefix) == 2
    first = episode.take(prefix[0])
    second = episode.take(prefix[1])
    contradiction_action = episode.truth.contradiction_action
    assert contradiction_action is not None
    contradiction = episode.take(contradiction_action)

    assert "translation" in first.truth.effects
    assert "translation" in second.truth.effects
    assert first.truth.contradiction_revealed is False
    assert second.truth.contradiction_revealed is False
    assert contradiction.truth.contradiction_revealed is True
    assert contradiction.truth.before_state != contradiction.truth.after_state


def test_transition_truth_is_separate_from_production_observation() -> None:
    evaluator = LabEvaluator(
        partition=LabPartition.DEVELOPMENT,
        root_seed=47,
        count=12,
    )
    episode = evaluator.open(evaluator.cases()[0])
    action = episode.truth.oracle_plan[0]

    evaluated = episode.take(action)

    assert evaluated.truth.family is episode.truth.family
    assert evaluated.truth.action == action
    assert evaluated.observation.returned_action == action
    assert not hasattr(evaluated.observation, "effects")
    assert not hasattr(evaluated.observation, "family")


def test_oracle_plan_reaches_exact_goal_for_each_family() -> None:
    evaluators = (
        LabEvaluator(partition=LabPartition.DEVELOPMENT, root_seed=5, count=12),
        LabEvaluator(partition=LabPartition.HELD_OUT_FAMILIES, root_seed=5, count=3),
    )
    reached: set[RuleFamily] = set()

    for evaluator in evaluators:
        for case in evaluator.cases():
            episode = evaluator.open(case)
            reached.add(episode.truth.family)
            for action in episode.truth.oracle_plan:
                episode.take(action)
            assert episode.session.observation.state is GameStateName.WIN

    assert reached == set(RuleFamily)
