"""Corrected protocol-v0.2 bindings and non-heldout development checks."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from evaluation_only.arc3_build003_curriculum.broker import (
    PolicyProcess,
    observation_to_bytes,
)
from evaluation_only.arc3_build003_curriculum.engine import CurriculumSession
from evaluation_only.arc3_build003_curriculum.generator import (
    case_for_seed,
    development_seeds,
    frozen_seeds,
    generate_curriculum,
)
from evaluation_only.arc3_build003_curriculum.oracle import validate_curriculum
from evaluation_only.arc3_build003_curriculum.protocol import (
    PROTOCOL_V0_1,
    PROTOCOL_V0_2,
)
from evaluation_only.arc3_build003_curriculum.runner import (
    SequenceBudgets,
    budgets_for_protocol,
)
from scripts import run_build003_curriculum_matrix as matrix_cli

from arc3.evaluation.build003_results import (
    Build003ResultLedger,
    CurriculumResultRow,
    FrozenCase,
)
from arc3.types import GameStateName

ROOT = Path(__file__).resolve().parents[2]


def _v02_cases() -> tuple[FrozenCase, ...]:
    return tuple(
        FrozenCase(case_for_seed(seed, PROTOCOL_V0_2).case_id, seed)
        for seed in frozen_seeds(PROTOCOL_V0_2)
    )


def _single_row(case: FrozenCase) -> CurriculumResultRow:
    return CurriculumResultRow(
        case_id=case.case_id,
        seed=case.seed,
        variant="BUILD002_FROZEN",
        family="movement-resource-cost",
        level_index=1,
        state=GameStateName.NOT_FINISHED,
        completed=False,
        levels_completed=0,
        environment_actions=1,
        resets=0,
        exploratory_actions=1,
        progress_actions=0,
        redundant_probes=0,
        actions_to_stable=None,
        movement_prediction_errors=0,
        resource_prediction_errors=0,
        access_prediction_errors=0,
        hazard_prediction_errors=0,
        residuals_observed=0,
        residuals_localized=0,
        residuals_resolved=0,
        base_mechanics_retained=False,
        erroneous_global_reopenings=0,
        unresolved_ledger_count=0,
        active_ledger_pressure=0,
        wall_time_seconds=0.01,
        peak_memory_bytes=1024,
        replay_digest="sha256:" + "0" * 64,
        replay_deterministic=True,
        receipt_complete=True,
    )


def test_v02_manifest_matches_new_domain_exactly_without_replacement() -> None:
    manifest = json.loads((ROOT / PROTOCOL_V0_2.manifest_path).read_text(encoding="utf-8"))
    cases = manifest["cases"]
    assert manifest["protocol_id"] == PROTOCOL_V0_2.protocol_id
    assert manifest["domain_utf8"] == PROTOCOL_V0_2.heldout_seed_domain
    assert manifest["replacement_permitted"] is False
    assert manifest["results_executed_before_freeze"] is False
    assert len(cases) == len({row["seed"] for row in cases}) == 30
    assert tuple(row["seed"] for row in cases) == frozen_seeds(PROTOCOL_V0_2)
    assert tuple(row["case_id"] for row in cases) == tuple(
        case_for_seed(seed, PROTOCOL_V0_2).case_id for seed in frozen_seeds(PROTOCOL_V0_2)
    )
    assert set(frozen_seeds(PROTOCOL_V0_2)).isdisjoint(frozen_seeds(PROTOCOL_V0_1))


def test_v02_reuses_one_mapping_and_cost_per_sequence_and_varies_by_seed() -> None:
    specifications = tuple(
        generate_curriculum(seed, PROTOCOL_V0_2) for seed in development_seeds(PROTOCOL_V0_2)
    )
    mappings = []
    costs = []
    for specification in specifications:
        assert specification.protocol_id == PROTOCOL_V0_2.protocol_id
        assert len({level.base_cost for level in specification.levels}) == 1
        assert len({level.action_vectors for level in specification.levels}) == 1
        assert all(set(level.palette) == set(range(1, 16)) for level in specification.levels)
        costs.append(specification.levels[0].base_cost)
        mappings.append(specification.levels[0].action_vectors)
    assert len(set(costs)) > 1
    assert len(set(mappings)) > 1
    assert len({tuple(level.palette for level in spec.levels) for spec in specifications}) > 1


def test_v02_development_curricula_fit_the_preregistered_oracle_bounds() -> None:
    for seed in development_seeds(PROTOCOL_V0_2):
        receipt = validate_curriculum(generate_curriculum(seed, PROTOCOL_V0_2))
        assert receipt.final_state is GameStateName.WIN
        assert receipt.levels_completed == receipt.win_levels == 10
        assert receipt.environment_actions <= PROTOCOL_V0_2.budgets.max_environment_actions
        assert all(
            len(plan.actions) <= int(PROTOCOL_V0_2.budgets.max_environment_actions_per_level or 0)
            for plan in receipt.plans
        )


@pytest.mark.integration
def test_v02_policy_process_receives_only_public_observation() -> None:
    seed = development_seeds(PROTOCOL_V0_2)[0]
    observation = CurriculumSession(generate_curriculum(seed, PROTOCOL_V0_2)).observation
    wire = json.loads(observation_to_bytes(observation))
    assert set(wire) == {
        "available_actions",
        "frames",
        "full_reset",
        "game_id",
        "levels_completed",
        "metadata",
        "returned_action",
        "schema",
        "state",
        "win_levels",
    }
    assert set(dict(wire["metadata"])) == {"attempt", "step"}
    with PolicyProcess(timeout_seconds=10.0) as worker:
        assert {name.rsplit(".", 1)[-1] for name in worker.blocked_privileged_imports} == {
            "engine",
            "generator",
            "oracle",
        }
        assert {name.rsplit(".", 1)[-1] for name in worker.loaded_modules}.isdisjoint(
            {"engine", "generator", "oracle"}
        )
        assert worker.request_action(observation).name in observation.available_actions


def test_v02_binds_stage01_baseline_and_its_own_budgets() -> None:
    stage01 = json.loads(
        (ROOT / "docs/evidence/003-01-build-002-frozen-baseline.json").read_text(encoding="utf-8")
    )
    assert PROTOCOL_V0_2.baseline.commit == stage01["required_build_002_head"]
    assert PROTOCOL_V0_2.baseline.tree == stage01["source_tree"]
    assert PROTOCOL_V0_2.baseline != PROTOCOL_V0_1.baseline
    assert budgets_for_protocol(PROTOCOL_V0_2) == SequenceBudgets(
        max_environment_actions=192,
        max_environment_actions_per_level=48,
        max_resets=10,
        max_wall_clock_seconds=10.0,
        max_peak_memory_bytes=1_073_741_824,
        policy_cycle_seconds=10.0,
    )


def test_v02_ledger_rejects_row_replacement() -> None:
    ledger = Build003ResultLedger(_v02_cases())
    row = _single_row(_v02_cases()[0])
    ledger.append(row)
    with pytest.raises(ValueError, match="replacement is forbidden"):
        ledger.append(row)


def test_matrix_cli_requires_explicit_protocol_and_seed_set(tmp_path: Path) -> None:
    parser = matrix_cli._parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["--seed-set", "development", "--output-root", str(tmp_path)])
    with pytest.raises(SystemExit):
        parser.parse_args(["--protocol", "v0.2", "--output-root", str(tmp_path)])
    parsed = parser.parse_args(
        [
            "--protocol",
            "v0.2",
            "--seed-set",
            "development",
            "--limit",
            "1",
            "--output-root",
            str(tmp_path),
        ]
    )
    assert parsed.protocol == "v0.2"
    assert parsed.seed_set == "development"


def test_matrix_cli_rejects_nonempty_output_before_running(tmp_path: Path) -> None:
    output_root = tmp_path / "existing"
    output_root.mkdir()
    (output_root / "immutable.jsonl").write_text("existing\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="replacement is forbidden"):
        matrix_cli.main(
            [
                "--protocol",
                "v0.2",
                "--seed-set",
                "development",
                "--limit",
                "1",
                "--variants",
                "BLA_CLEF_FULL",
                "--output-root",
                str(output_root),
            ]
        )
