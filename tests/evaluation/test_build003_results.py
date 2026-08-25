"""Frozen-matrix and paired-metric tests for Build 003 evidence."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

from evaluation_only.arc3_build003_curriculum.generator import (
    case_for_seed,
    frozen_seeds,
)
from evaluation_only.arc3_build003_curriculum.models import (
    CurriculumFamily,
    CurriculumVariant,
)

from arc3.evaluation.build003_results import (
    FAMILIES,
    VARIANTS,
    Build003ResultLedger,
    CurriculumResultRow,
    FrozenCase,
)
from arc3.mechanics import CHANNEL_ORDER, CompositionMode
from arc3.types import GameStateName

ROOT = Path(__file__).resolve().parents[2]


def _cases() -> tuple[FrozenCase, ...]:
    return tuple(
        FrozenCase(case_id=case_for_seed(seed).case_id, seed=seed) for seed in frozen_seeds()
    )


def _row(case: FrozenCase, variant: str, family: str) -> CurriculumResultRow:
    level_index = FAMILIES.index(family) + 1
    exploratory = {
        "BUILD002_FROZEN": 5,
        "BLA_CLEF_LEVEL_RESET": 4,
        "BLA_ONLY_PERSISTENT": 3,
        "BLA_CLEF_FULL": 2,
    }[variant]
    redundant = {
        "BUILD002_FROZEN": 3,
        "BLA_CLEF_LEVEL_RESET": 2,
        "BLA_ONLY_PERSISTENT": 2,
        "BLA_CLEF_FULL": 1,
    }[variant]
    return CurriculumResultRow(
        case_id=case.case_id,
        seed=case.seed,
        variant=variant,
        family=family,
        level_index=level_index,
        state=GameStateName.WIN if level_index == len(FAMILIES) else GameStateName.NOT_FINISHED,
        completed=True,
        levels_completed=level_index,
        environment_actions=10 + exploratory,
        resets=0,
        exploratory_actions=exploratory,
        progress_actions=10,
        redundant_probes=redundant,
        actions_to_stable=exploratory,
        movement_prediction_errors=0,
        resource_prediction_errors=0,
        access_prediction_errors=0,
        hazard_prediction_errors=0,
        prediction_errors_by_channel=tuple((channel.value, 0) for channel in CHANNEL_ORDER),
        residuals_observed=1,
        residuals_localized=1,
        residuals_resolved=1,
        base_mechanics_retained=variant == "BLA_CLEF_FULL",
        observed_retained_matches=1 if variant == "BLA_CLEF_FULL" else 0,
        erroneous_global_reopenings=0 if variant == "BLA_CLEF_FULL" else 1,
        passive_confirmations=1,
        transfer_confirmations=1 if variant == "BLA_CLEF_FULL" else 0,
        local_repair_candidates_opened=1,
        local_repairs_confirmed=1,
        local_repair_failures=0,
        base_reopenings=0,
        composition_events=tuple((mode.value, 0) for mode in CompositionMode),
        clef_promotions=0,
        clef_parks=0,
        clef_stops=0,
        other_object_effects_observed=0,
        topology_changes_confirmed=0,
        delayed_candidates_confirmed=0,
        unresolved_ledger_count=0,
        active_ledger_pressure=2,
        wall_time_seconds=0.01,
        peak_memory_bytes=1024,
        replay_digest="sha256:" + "0" * 64,
        replay_deterministic=True,
        receipt_complete=True,
    )


def _complete_ledger() -> Build003ResultLedger:
    cases = _cases()
    ledger = Build003ResultLedger(cases)
    ledger.append_many(
        _row(case, variant, family) for case in cases for variant in VARIANTS for family in FAMILIES
    )
    return ledger


def test_four_variant_matrix_requires_all_1200_rows() -> None:
    assert VARIANTS == tuple(variant.value for variant in CurriculumVariant)
    assert FAMILIES == tuple(family.value for family in CurriculumFamily)
    protocol = json.loads(
        (ROOT / "docs/evaluation/build-003-curriculum-protocol.v0.1.json").read_text(
            encoding="utf-8"
        )
    )
    assert tuple(protocol["variants"]) == VARIANTS
    assert tuple(protocol["families"]) == FAMILIES
    assert protocol["pairing"]["required_rows"] == 1200
    ledger = _complete_ledger()
    assert ledger.expected_row_count == 4 * 30 * 10 == 1200
    assert len(ledger.rows) == 1200
    assert ledger.completeness_errors() == ()
    ledger.require_complete()


def test_missing_rows_are_reported_and_existing_rows_cannot_be_replaced() -> None:
    case = _cases()[0]
    row = _row(case, VARIANTS[0], FAMILIES[0])
    ledger = Build003ResultLedger(_cases())
    ledger.append(row)
    assert ledger.completeness_errors()
    try:
        ledger.append(row)
    except ValueError as error:
        assert "replacement is forbidden" in str(error)
    else:
        raise AssertionError("duplicate result silently replaced frozen evidence")


def test_preregistered_paired_metrics_use_identical_seed_family_pairs() -> None:
    ledger = _complete_ledger()
    h1 = ledger.paired_distribution(
        reference="BLA_CLEF_LEVEL_RESET",
        treatment="BLA_CLEF_FULL",
        metric="exploratory_actions",
        families=FAMILIES[1:],
    )
    assert h1.pairs == 30 * 9
    assert h1.mean_delta == h1.median_delta == -2.0
    assert h1.reference_failures == h1.treatment_failures == 0
    summary = ledger.preregistered_summary()
    json.dumps(summary, sort_keys=True)
    assert summary["row_count"] == 1200
    assert summary["h2_conservative_repair"] == {
        "modifier_rows": 150,
        "base_mechanic_retention_rate": 1.0,
        "base_mechanic_retention_rate_by_family": {
            family: 1.0
            for family in (FAMILIES[2], FAMILIES[3], FAMILIES[6], FAMILIES[7], FAMILIES[9])
        },
        "observed_retained_matches_by_family": {
            family: 30
            for family in (FAMILIES[2], FAMILIES[3], FAMILIES[6], FAMILIES[7], FAMILIES[9])
        },
        "erroneous_global_reopenings": 0,
        "erroneous_global_reopenings_assessed_rows": 150,
        "local_scoped_revisions": 150,
    }
    paired = summary["paired"]
    assert paired["h3_redundant_probes"]["mean_delta"] == -1.0
    assert paired["baseline_full_actions"]["mean_delta"] == -3.0
    assert summary["evidence_quality"] == {
        "replay_determinism_rate": 1.0,
        "receipt_completeness_rate": 1.0,
        "infrastructure_failure_rows": 0,
        "policy_error_rows": 0,
    }
    decisions = summary["decisions"]
    assert decisions["H1"]["status"] == decisions["H2"]["status"] == "PASS"
    assert decisions["H3"]["status"] == "PASS"
    assert decisions["all_hypotheses_passed"] is True
    assert decisions["evidence_quality_passed"] is True
    assert decisions["matrix_passed"] is True


def test_structurally_complete_anti_result_cannot_pass_decision_gates() -> None:
    cases = _cases()
    rows = []
    for case in cases:
        for variant in VARIANTS:
            for family in FAMILIES:
                row = _row(case, variant, family)
                if variant == "BLA_CLEF_FULL":
                    row = replace(
                        row,
                        environment_actions=14,
                        exploratory_actions=4,
                        redundant_probes=2,
                        erroneous_global_reopenings=None,
                    )
                rows.append(row)
    ledger = Build003ResultLedger(cases)
    ledger.append_many(rows)
    assert ledger.completeness_errors() == ()
    decisions = ledger.preregistered_summary()["decisions"]
    assert decisions["H1"]["status"] == "FAIL"
    assert decisions["H2"]["status"] == "NOT_MEASURED"
    assert decisions["all_hypotheses_passed"] is False
    assert decisions["matrix_passed"] is False


def test_one_replay_or_receipt_failure_invalidates_matrix_evidence() -> None:
    cases = _cases()
    rows = [
        _row(case, variant, family) for case in cases for variant in VARIANTS for family in FAMILIES
    ]
    rows[0] = replace(rows[0], replay_deterministic=False)
    rows[1] = replace(rows[1], receipt_complete=False)
    rows[2] = replace(rows[2], run_status="POLICY_ERROR", failure_reason="measured failure")
    ledger = Build003ResultLedger(cases)
    ledger.append_many(rows)
    decisions = ledger.preregistered_summary()["decisions"]
    assert decisions["all_hypotheses_passed"] is True
    assert decisions["evidence_quality_passed"] is False
    assert decisions["matrix_passed"] is False
