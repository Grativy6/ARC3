"""Unit tests for the procedural laboratory catalog and evaluator boundary."""

from __future__ import annotations

from dataclasses import asdict

from arc3.lab import (
    LabAdapter,
    LabEvaluator,
    LabPartition,
    RuleFamily,
    available_rule_families,
)


def test_lab_registers_all_fifteen_distinct_protocol_families() -> None:
    families = available_rule_families()

    assert len(families) == 15
    assert len(set(families)) == 15
    assert set(families) == set(RuleFamily)


def test_partitions_cover_development_and_wholly_held_out_families() -> None:
    development = LabEvaluator(partition=LabPartition.DEVELOPMENT, root_seed=17, count=12)
    held_out = LabEvaluator(partition=LabPartition.HELD_OUT_FAMILIES, root_seed=17, count=3)
    development_families = {development.ground_truth(case).family for case in development.cases()}
    held_out_families = {held_out.ground_truth(case).family for case in held_out.cases()}

    assert len(development_families) == 12
    assert len(held_out_families) == 3
    assert development_families.isdisjoint(held_out_families)
    assert development_families | held_out_families == set(RuleFamily)


def test_catalog_identity_and_held_out_generation_are_seed_deterministic() -> None:
    first = LabEvaluator(
        partition=LabPartition.HELD_OUT_COMBINATIONS,
        root_seed=991,
        count=18,
    )
    second = LabEvaluator(
        partition=LabPartition.HELD_OUT_COMBINATIONS,
        root_seed=991,
        count=18,
    )

    assert first.cases() == second.cases()
    assert tuple(asdict(first.ground_truth(case)) for case in first.cases()) == tuple(
        asdict(second.ground_truth(case)) for case in second.cases()
    )


def test_seeded_variations_cover_required_generation_axes() -> None:
    evaluator = LabEvaluator(
        partition=LabPartition.HELD_OUT_COMBINATIONS,
        root_seed=551,
        count=36,
    )
    truths = tuple(evaluator.ground_truth(case) for case in evaluator.cases())

    assert len({truth.palette for truth in truths}) > 1
    assert len({truth.player_shape for truth in truths}) > 1
    assert len({truth.target_shape for truth in truths}) > 1
    assert len({truth.start for truth in truths}) > 1
    assert len({truth.action_semantics for truth in truths}) > 1
    assert len({truth.distractors for truth in truths}) > 1
    assert len({truth.walls for truth in truths}) > 1
    assert {truth.reversible_consequences for truth in truths} == {False, True}
    assert {truth.grid_size for truth in truths}.issubset({9, 10})


def test_production_adapter_has_no_ground_truth_surface_or_textual_instructions() -> None:
    adapter = LabAdapter(
        partition=LabPartition.HELD_OUT_FAMILIES,
        root_seed=71,
        count=3,
    )
    session = adapter.open(adapter.cases()[0].case_id)

    assert not hasattr(session, "truth")
    assert not hasattr(session, "ground_truth")
    assert not hasattr(session, "oracle_plan")
    assert not hasattr(session.observation, "goal")
    assert not hasattr(session.observation, "rule")
    assert session.observation.upstream_metadata == (("step", 0), ("attempt", 0))
    assert adapter.list_games()[0].title == "Procedural synthetic episode"


def test_evaluator_leakage_self_test_covers_complete_catalog() -> None:
    evaluator = LabEvaluator(
        partition=LabPartition.DEVELOPMENT,
        root_seed=113,
        count=24,
    )

    evaluator.assert_no_observation_leakage()
