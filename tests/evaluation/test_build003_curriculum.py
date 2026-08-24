"""Acceptance tests for the evaluator-only Build 003 curriculum."""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

import pytest
from evaluation_only.arc3_build003_curriculum.broker import (
    PolicyProcess,
    assert_unprivileged_payload,
    observation_from_bytes,
    observation_to_bytes,
)
from evaluation_only.arc3_build003_curriculum.engine import CurriculumSession
from evaluation_only.arc3_build003_curriculum.generator import (
    case_for_seed,
    frozen_seeds,
    generate_curriculum,
)
from evaluation_only.arc3_build003_curriculum.models import CurriculumFamily
from evaluation_only.arc3_build003_curriculum.oracle import (
    force_game_over_then_reset,
    shortest_level_plan,
    validate_curriculum,
)

from arc3.errors import InvalidActionError
from arc3.types import ActionName, ActionRequest, GameStateName

ROOT = Path(__file__).resolve().parents[2]


def test_frozen_manifest_has_exactly_thirty_derived_cases() -> None:
    manifest = json.loads(
        (ROOT / "docs/evaluation/build-003-heldout-seeds.v0.1.json").read_text(encoding="utf-8")
    )
    cases = manifest["cases"]
    assert manifest["seed_count"] == 30
    assert manifest["replacement_permitted"] is False
    assert len(cases) == len({row["seed"] for row in cases}) == 30
    assert tuple(row["seed"] for row in cases) == frozen_seeds()
    assert tuple(row["case_id"] for row in cases) == tuple(
        case_for_seed(seed).case_id for seed in frozen_seeds()
    )


def test_generation_is_deterministic_and_covers_all_ten_families() -> None:
    first = generate_curriculum(frozen_seeds()[0])
    assert first == generate_curriculum(frozen_seeds()[0])
    assert tuple(level.family for level in first.levels) == tuple(CurriculumFamily)
    assert len(first.levels) == 10
    assert first != generate_curriculum(frozen_seeds()[1])


def test_frozen_seeds_vary_layout_palette_counts_and_mechanic_magnitudes() -> None:
    specifications = tuple(generate_curriculum(seed) for seed in frozen_seeds())
    assert len({tuple(level.start for level in spec.levels) for spec in specifications}) > 1
    assert len({tuple(level.palette for level in spec.levels) for spec in specifications}) == 30
    assert (
        len(
            {
                (
                    tuple(level.base_cost for level in spec.levels),
                    spec.levels[2].restoration_amount,
                    spec.levels[6].terrain_extra_cost,
                    len(spec.levels[8].decorations),
                )
                for spec in specifications
            }
        )
        > 1
    )


def test_every_frozen_level_is_oracle_solvable() -> None:
    for seed in frozen_seeds():
        spec = generate_curriculum(seed)
        plans = tuple(shortest_level_plan(level) for level in spec.levels)
        assert len(plans) == 10
        assert all(plan.actions for plan in plans)


def test_replay_stays_not_finished_until_final_authoritative_win() -> None:
    spec = generate_curriculum(frozen_seeds()[0])
    plans = tuple(shortest_level_plan(level) for level in spec.levels)
    session = CurriculumSession(spec)
    states: list[GameStateName] = []
    for plan in plans:
        for action in plan.actions:
            observation = session.step(action)
        states.append(observation.state)
    assert states == [GameStateName.NOT_FINISHED] * 9 + [GameStateName.WIN]
    assert session.observation.levels_completed == session.observation.win_levels == 10
    receipt = validate_curriculum(spec)
    assert receipt.final_state is GameStateName.WIN
    assert receipt.levels_completed == receipt.win_levels == 10


def test_game_over_allows_only_reset_and_reset_restarts_sequence() -> None:
    spec = generate_curriculum(frozen_seeds()[0])
    session = CurriculumSession(spec)
    while session.observation.state is GameStateName.NOT_FINISHED:
        observation = session.step(ActionRequest(ActionName.ACTION5))
    assert observation.state is GameStateName.GAME_OVER
    with pytest.raises(InvalidActionError, match="GAME_OVER permits only RESET"):
        session.step(ActionRequest(ActionName.ACTION1))
    reset = session.step(ActionRequest(ActionName.RESET))
    assert reset.state is GameStateName.NOT_FINISHED
    assert reset.levels_completed == 0
    assert reset.full_reset is True
    assert reset.returned_action == ActionRequest(ActionName.RESET)
    assert force_game_over_then_reset(spec) == (
        GameStateName.GAME_OVER,
        GameStateName.NOT_FINISHED,
    )
    for level in spec.levels:
        for action in shortest_level_plan(level).actions:
            recovered = session.step(action)
    assert recovered.state is GameStateName.WIN
    assert recovered.levels_completed == recovered.win_levels == 10


def test_wire_round_trip_contains_only_public_observation_fields() -> None:
    spec = generate_curriculum(frozen_seeds()[0])
    observation = CurriculumSession(spec).observation
    payload = observation_to_bytes(observation)
    assert observation_from_bytes(payload) == observation
    wire = json.loads(payload)
    assert "seed" not in wire
    assert "family" not in wire
    assert "spec" not in wire
    assert "oracle" not in wire
    assert set(dict(wire["metadata"])) == {"attempt", "step"}
    with pytest.raises(ValueError, match="privileged evaluator field"):
        assert_unprivileged_payload({"nested": [{"seed": spec.case.seed}]})


@pytest.mark.integration
def test_spawned_policy_process_has_no_privileged_modules_or_values() -> None:
    spec = generate_curriculum(frozen_seeds()[0])
    observation = CurriculumSession(spec).observation
    with PolicyProcess(timeout_seconds=10.0) as worker:
        assert worker.process_id is not None
        imported_leaf_names = {name.rsplit(".", 1)[-1] for name in worker.loaded_modules}
        assert imported_leaf_names.isdisjoint({"engine", "generator", "oracle"})
        assert {name.rsplit(".", 1)[-1] for name in worker.blocked_privileged_imports} == {
            "engine",
            "generator",
            "oracle",
        }
        action = worker.request_action(observation)
        assert action.name in observation.available_actions


def test_evaluator_only_package_is_excluded_from_production_wheel() -> None:
    configuration = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    wheel_packages = configuration["tool"]["hatch"]["build"]["targets"]["wheel"]["packages"]
    assert wheel_packages == ["src/arc3"]
    for source in (ROOT / "src").rglob("*.py"):
        if source.name == "build003_results.py":
            continue
        assert "arc3_build003_curriculum" not in source.read_text(encoding="utf-8")
