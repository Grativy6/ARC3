"""Frozen row contract and paired summaries for the Build 003 curriculum."""

from __future__ import annotations

import math
import statistics
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from typing import cast

from arc3.mechanics import CHANNEL_ORDER, CompositionMode
from arc3.types import GameStateName

BUILD003_RESULT_SCHEMA = "arc3.build003.curriculum-result.v0.3"
BUILD003_SUMMARY_SCHEMA = "arc3.build003.paired-summary.v0.3"
FROZEN_SEED_COUNT = 30

VARIANTS = (
    "BUILD002_FROZEN",
    "BLA_CLEF_LEVEL_RESET",
    "BLA_ONLY_PERSISTENT",
    "BLA_CLEF_FULL",
)
FAMILIES = (
    "movement-resource-cost",
    "blocking-walls",
    "resource-restoration",
    "reusable-versus-one-shot-restoration",
    "gate-switch-reachability",
    "pushing-other-object",
    "terrain-status-modifier",
    "delayed-hidden-state-response",
    "harmless-animation",
    "held-out-mechanic-composition",
)
RUN_STATUSES = (
    "SUCCESS",
    "ACTION_BUDGET",
    "RESET_BUDGET",
    "WALL_CLOCK_BUDGET",
    "MEMORY_BUDGET",
    "FAILED_INFRASTRUCTURE",
    "POLICY_ERROR",
)


@dataclass(frozen=True, slots=True)
class FrozenCase:
    """Public immutable pairing identity from the preregistered seed manifest."""

    case_id: str
    seed: int

    def __post_init__(self) -> None:
        if not self.case_id:
            raise ValueError("case_id must not be empty")
        if (
            isinstance(self.seed, bool)
            or not isinstance(self.seed, int)
            or not 0 <= self.seed < 2**63
        ):
            raise ValueError("seed must be an unsigned 63-bit integer")


@dataclass(frozen=True, slots=True)
class CurriculumResultRow:
    """One immutable variant/seed/family result row."""

    case_id: str
    seed: int
    variant: str
    family: str
    level_index: int
    state: GameStateName
    completed: bool
    levels_completed: int
    environment_actions: int
    resets: int
    exploratory_actions: int
    progress_actions: int
    redundant_probes: int
    actions_to_stable: int | None
    movement_prediction_errors: int
    resource_prediction_errors: int
    access_prediction_errors: int
    hazard_prediction_errors: int
    prediction_errors_by_channel: tuple[tuple[str, int], ...]
    residuals_observed: int
    residuals_localized: int
    residuals_resolved: int
    base_mechanics_retained: bool
    observed_retained_matches: int
    erroneous_global_reopenings: int | None
    passive_confirmations: int
    transfer_confirmations: int
    local_repair_candidates_opened: int
    local_repairs_confirmed: int
    local_repair_failures: int
    base_reopenings: int
    composition_events: tuple[tuple[str, int], ...]
    clef_promotions: int
    clef_parks: int
    clef_stops: int
    other_object_effects_observed: int
    topology_changes_confirmed: int
    delayed_candidates_confirmed: int
    unresolved_ledger_count: int
    active_ledger_pressure: int
    wall_time_seconds: float
    peak_memory_bytes: int
    replay_digest: str
    replay_deterministic: bool
    receipt_complete: bool
    run_status: str = "SUCCESS"
    failure_reason: str | None = None
    schema: str = BUILD003_RESULT_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != BUILD003_RESULT_SCHEMA:
            raise ValueError("result row schema mismatch")
        if self.variant not in VARIANTS or self.family not in FAMILIES:
            raise ValueError("result row has an undeclared variant or family")
        if self.run_status not in RUN_STATUSES:
            raise ValueError("result row has an undeclared run status")
        if (self.run_status == "SUCCESS") != (self.failure_reason is None):
            raise ValueError("only successful runs omit a failure reason")
        if self.failure_reason is not None and not self.failure_reason.strip():
            raise ValueError("failure_reason must be non-empty when present")
        if not isinstance(self.state, GameStateName):
            raise ValueError("state must be a normalized GameStateName")
        if not all(
            isinstance(value, bool)
            for value in (
                self.completed,
                self.base_mechanics_retained,
                self.replay_deterministic,
                self.receipt_complete,
            )
        ):
            raise ValueError("result flags must be booleans")
        expected_level = FAMILIES.index(self.family) + 1
        if self.level_index != expected_level:
            raise ValueError("family and level_index disagree")
        digest = self.replay_digest.removeprefix("sha256:")
        if (
            not self.case_id
            or not self.replay_digest.startswith("sha256:")
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
        ):
            raise ValueError("result identity and replay digest must be present")
        integer_fields = {
            "seed": self.seed,
            "levels_completed": self.levels_completed,
            "environment_actions": self.environment_actions,
            "resets": self.resets,
            "exploratory_actions": self.exploratory_actions,
            "progress_actions": self.progress_actions,
            "redundant_probes": self.redundant_probes,
            "movement_prediction_errors": self.movement_prediction_errors,
            "resource_prediction_errors": self.resource_prediction_errors,
            "access_prediction_errors": self.access_prediction_errors,
            "hazard_prediction_errors": self.hazard_prediction_errors,
            "observed_retained_matches": self.observed_retained_matches,
            "residuals_observed": self.residuals_observed,
            "residuals_localized": self.residuals_localized,
            "residuals_resolved": self.residuals_resolved,
            "passive_confirmations": self.passive_confirmations,
            "transfer_confirmations": self.transfer_confirmations,
            "local_repair_candidates_opened": self.local_repair_candidates_opened,
            "local_repairs_confirmed": self.local_repairs_confirmed,
            "local_repair_failures": self.local_repair_failures,
            "base_reopenings": self.base_reopenings,
            "clef_promotions": self.clef_promotions,
            "clef_parks": self.clef_parks,
            "clef_stops": self.clef_stops,
            "other_object_effects_observed": self.other_object_effects_observed,
            "topology_changes_confirmed": self.topology_changes_confirmed,
            "delayed_candidates_confirmed": self.delayed_candidates_confirmed,
            "unresolved_ledger_count": self.unresolved_ledger_count,
            "active_ledger_pressure": self.active_ledger_pressure,
            "peak_memory_bytes": self.peak_memory_bytes,
        }
        if any(
            isinstance(value, bool) or not isinstance(value, int) or value < 0
            for value in integer_fields.values()
        ):
            raise ValueError("result count fields must be non-negative integers")
        if self.erroneous_global_reopenings is not None and (
            isinstance(self.erroneous_global_reopenings, bool)
            or not isinstance(self.erroneous_global_reopenings, int)
            or self.erroneous_global_reopenings < 0
        ):
            raise ValueError("erroneous_global_reopenings must be non-negative or null")
        expected_channels = tuple(channel.value for channel in CHANNEL_ORDER)
        if tuple(name for name, _ in self.prediction_errors_by_channel) != expected_channels:
            raise ValueError("per-channel prediction errors must name all channels in order")
        expected_modes = tuple(mode.value for mode in CompositionMode)
        if tuple(name for name, _ in self.composition_events) != expected_modes:
            raise ValueError("composition events must name all modes in order")
        if any(
            isinstance(count, bool) or not isinstance(count, int) or count < 0
            for _, count in (*self.prediction_errors_by_channel, *self.composition_events)
        ):
            raise ValueError("factorized result counts must be non-negative integers")
        if self.actions_to_stable is not None and (
            isinstance(self.actions_to_stable, bool)
            or not isinstance(self.actions_to_stable, int)
            or self.actions_to_stable < 0
        ):
            raise ValueError("actions_to_stable must be a non-negative integer or null")
        if self.environment_actions != self.exploratory_actions + self.progress_actions:
            raise ValueError("exploratory and progress actions must partition environment actions")
        if self.redundant_probes > self.exploratory_actions:
            raise ValueError("redundant probes cannot exceed exploratory actions")
        if self.actions_to_stable is not None and self.actions_to_stable > self.environment_actions:
            raise ValueError("actions_to_stable cannot exceed environment actions")
        if not self.residuals_resolved <= self.residuals_localized <= self.residuals_observed:
            raise ValueError("residual resolution counts must be nested")
        if (
            isinstance(self.wall_time_seconds, bool)
            or not isinstance(self.wall_time_seconds, (int, float))
            or not math.isfinite(self.wall_time_seconds)
            or self.wall_time_seconds < 0
        ):
            raise ValueError("wall_time_seconds must be finite and non-negative")
        if self.levels_completed > len(FAMILIES):
            raise ValueError("levels_completed exceeds the curriculum")
        if self.completed and self.levels_completed != self.level_index:
            raise ValueError("completed row must end at its declared level")
        expected_success_state = (
            GameStateName.WIN if self.level_index == len(FAMILIES) else GameStateName.NOT_FINISHED
        )
        if self.completed and self.state is not expected_success_state:
            raise ValueError("completed row has the wrong authoritative environment state")
        if self.state is GameStateName.WIN and not self.completed:
            raise ValueError("WIN cannot be recorded as an incomplete level")

    @property
    def key(self) -> tuple[str, int, str, str]:
        return self.case_id, self.seed, self.variant, self.family


@dataclass(frozen=True, slots=True)
class PairedDistribution:
    """Deterministic paired spread with a normal-approximation mean CI."""

    pairs: int
    reference_failures: int
    treatment_failures: int
    mean_delta: float
    median_delta: float
    q1_delta: float
    q3_delta: float
    minimum_delta: float
    maximum_delta: float
    mean_ci95_low: float
    mean_ci95_high: float


def _quantile(values: list[float], fraction: float) -> float:
    if not values:
        raise ValueError("cannot summarize an empty paired distribution")
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def _distribution(
    deltas: list[float],
    *,
    reference_failures: int,
    treatment_failures: int,
) -> PairedDistribution:
    if not deltas:
        raise ValueError("paired comparison has no rows")
    mean = statistics.fmean(deltas)
    half_width = 0.0
    if len(deltas) > 1:
        half_width = 1.96 * statistics.stdev(deltas) / math.sqrt(len(deltas))
    return PairedDistribution(
        pairs=len(deltas),
        reference_failures=reference_failures,
        treatment_failures=treatment_failures,
        mean_delta=mean,
        median_delta=statistics.median(deltas),
        q1_delta=_quantile(deltas, 0.25),
        q3_delta=_quantile(deltas, 0.75),
        minimum_delta=min(deltas),
        maximum_delta=max(deltas),
        mean_ci95_low=mean - half_width,
        mean_ci95_high=mean + half_width,
    )


class Build003ResultLedger:
    """Append-only exact matrix; duplicate keys can never replace prior evidence."""

    def __init__(self, cases: Iterable[FrozenCase]) -> None:
        materialized = tuple(cases)
        if len(materialized) != FROZEN_SEED_COUNT:
            raise ValueError(f"Build 003 requires exactly {FROZEN_SEED_COUNT} frozen cases")
        if len({case.seed for case in materialized}) != len(materialized):
            raise ValueError("cases must have unique seeds")
        if len({case.case_id for case in materialized}) != len(materialized):
            raise ValueError("case IDs must be unique")
        self._cases = {case.seed: case for case in materialized}
        self._rows: dict[tuple[str, int, str, str], CurriculumResultRow] = {}

    @property
    def rows(self) -> tuple[CurriculumResultRow, ...]:
        return tuple(self._rows[key] for key in sorted(self._rows))

    @property
    def expected_row_count(self) -> int:
        return len(self._cases) * len(VARIANTS) * len(FAMILIES)

    def append(self, row: CurriculumResultRow) -> None:
        self.append_many((row,))

    def append_many(self, rows: Iterable[CurriculumResultRow]) -> None:
        pending = tuple(rows)
        keys = [row.key for row in pending]
        if len(keys) != len(set(keys)):
            raise ValueError("batch contains duplicate result keys; replacement is forbidden")
        if any(key in self._rows for key in keys):
            raise ValueError("result key already exists; replacement is forbidden")
        for row in pending:
            case = self._cases.get(row.seed)
            if case is None or case.case_id != row.case_id:
                raise ValueError("result row is not in the frozen seed/case manifest")
        self._rows.update(zip(keys, pending, strict=True))

    def completeness_errors(self) -> tuple[str, ...]:
        expected = {
            (case.case_id, case.seed, variant, family)
            for case in self._cases.values()
            for variant in VARIANTS
            for family in FAMILIES
        }
        actual = set(self._rows)
        errors: list[str] = []
        if missing := expected - actual:
            errors.append(f"missing {len(missing)} frozen rows")
        if unexpected := actual - expected:
            errors.append(f"unexpected {len(unexpected)} non-preregistered rows")
        if len(actual) != self.expected_row_count:
            errors.append(
                f"row count {len(actual)} does not equal frozen count {self.expected_row_count}"
            )
        return tuple(errors)

    def require_complete(self) -> None:
        errors = self.completeness_errors()
        if errors:
            raise ValueError("; ".join(errors))

    def paired_distribution(
        self,
        *,
        reference: str,
        treatment: str,
        metric: str,
        families: Iterable[str] = FAMILIES,
    ) -> PairedDistribution:
        if reference not in VARIANTS or treatment not in VARIANTS or reference == treatment:
            raise ValueError("paired variants must be distinct preregistered variants")
        selected = frozenset(families)
        if not selected or not selected <= set(FAMILIES):
            raise ValueError("paired families must be a non-empty curriculum subset")
        indexed = {(row.seed, row.variant, row.family): row for row in self._rows.values()}
        deltas: list[float] = []
        reference_failures = 0
        treatment_failures = 0
        for seed in sorted(self._cases):
            for family in FAMILIES:
                if family not in selected:
                    continue
                try:
                    reference_row = indexed[(seed, reference, family)]
                    treatment_row = indexed[(seed, treatment, family)]
                except KeyError as error:
                    raise ValueError("paired comparison requires complete paired rows") from error
                reference_failures += not reference_row.completed
                treatment_failures += not treatment_row.completed
                deltas.append(_metric(treatment_row, metric) - _metric(reference_row, metric))
        return _distribution(
            deltas,
            reference_failures=reference_failures,
            treatment_failures=treatment_failures,
        )

    def preregistered_summary(self) -> dict[str, object]:
        """Return literal preregistered H1/H2/H3 decisions and paired evidence."""

        self.require_complete()
        later_families = FAMILIES[1:]
        modifier_families = (
            FAMILIES[2],
            FAMILIES[3],
            FAMILIES[6],
            FAMILIES[7],
            FAMILIES[9],
        )
        full_modifier_rows = [
            row
            for row in self._rows.values()
            if row.variant == "BLA_CLEF_FULL" and row.family in modifier_families
        ]
        h2_retention = statistics.fmean(
            float(row.base_mechanics_retained) for row in full_modifier_rows
        )
        assessed_reopenings = [
            row.erroneous_global_reopenings
            for row in full_modifier_rows
            if row.erroneous_global_reopenings is not None
        ]
        h2_global_reopenings = None if not assessed_reopenings else sum(assessed_reopenings)
        h2_local_scoped_revisions = sum(
            row.local_repair_candidates_opened for row in full_modifier_rows
        )
        h2_retention_by_family = {
            family: statistics.fmean(
                float(row.base_mechanics_retained)
                for row in full_modifier_rows
                if row.family == family
            )
            for family in modifier_families
        }
        h2_observed_matches_by_family = {
            family: sum(
                row.observed_retained_matches for row in full_modifier_rows if row.family == family
            )
            for family in modifier_families
        }
        comparisons: Mapping[str, tuple[str, str, str, Iterable[str]]] = {
            "h1_later_exploration": (
                "BLA_CLEF_LEVEL_RESET",
                "BLA_CLEF_FULL",
                "exploratory_actions",
                later_families,
            ),
            "h1_later_completion": (
                "BLA_CLEF_LEVEL_RESET",
                "BLA_CLEF_FULL",
                "completed",
                later_families,
            ),
            "h3_redundant_probes": (
                "BLA_ONLY_PERSISTENT",
                "BLA_CLEF_FULL",
                "redundant_probes",
                FAMILIES,
            ),
            "h3_active_ledger_pressure": (
                "BLA_ONLY_PERSISTENT",
                "BLA_CLEF_FULL",
                "active_ledger_pressure",
                FAMILIES,
            ),
            "h3_environment_actions": (
                "BLA_ONLY_PERSISTENT",
                "BLA_CLEF_FULL",
                "environment_actions",
                FAMILIES,
            ),
            "h3_completion": (
                "BLA_ONLY_PERSISTENT",
                "BLA_CLEF_FULL",
                "completed",
                FAMILIES,
            ),
            "baseline_full_actions": (
                "BUILD002_FROZEN",
                "BLA_CLEF_FULL",
                "environment_actions",
                FAMILIES,
            ),
        }
        paired = {
            name: asdict(
                self.paired_distribution(
                    reference=reference,
                    treatment=treatment,
                    metric=metric,
                    families=families,
                )
            )
            for name, (reference, treatment, metric, families) in comparisons.items()
        }
        indexed = {(row.seed, row.variant, row.family): row for row in self._rows.values()}
        h1_completion_losses_by_family = {
            family: sum(
                indexed[(seed, "BLA_CLEF_FULL", family)].completed
                < indexed[(seed, "BLA_CLEF_LEVEL_RESET", family)].completed
                for seed in sorted(self._cases)
            )
            for family in later_families
        }
        h1_reference_completions = sum(
            indexed[(seed, "BLA_CLEF_LEVEL_RESET", family)].completed
            for seed in sorted(self._cases)
            for family in later_families
        )
        h1_treatment_completions = sum(
            indexed[(seed, "BLA_CLEF_FULL", family)].completed
            for seed in sorted(self._cases)
            for family in later_families
        )
        h3_reference_completions = sum(
            indexed[(seed, "BLA_ONLY_PERSISTENT", family)].completed
            for seed in sorted(self._cases)
            for family in FAMILIES
        )
        h3_treatment_completions = sum(
            indexed[(seed, "BLA_CLEF_FULL", family)].completed
            for seed in sorted(self._cases)
            for family in FAMILIES
        )
        h3_reference_action_median = statistics.median(
            indexed[(seed, "BLA_ONLY_PERSISTENT", family)].environment_actions
            for seed in sorted(self._cases)
            for family in FAMILIES
        )
        h3_treatment_action_median = statistics.median(
            indexed[(seed, "BLA_CLEF_FULL", family)].environment_actions
            for seed in sorted(self._cases)
            for family in FAMILIES
        )
        h3_action_ratio = (
            1.0
            if h3_reference_action_median == h3_treatment_action_median == 0
            else (
                None
                if h3_reference_action_median == 0
                else h3_treatment_action_median / h3_reference_action_median
            )
        )
        replay_rate = statistics.fmean(
            float(row.replay_deterministic) for row in self._rows.values()
        )
        receipt_rate = statistics.fmean(float(row.receipt_complete) for row in self._rows.values())
        infrastructure_failure_rows = sum(
            row.run_status == "FAILED_INFRASTRUCTURE" for row in self._rows.values()
        )
        policy_error_rows = sum(row.run_status == "POLICY_ERROR" for row in self._rows.values())
        h1_exploration_median_delta = cast(
            float,
            cast(dict[str, object], paired["h1_later_exploration"])["median_delta"],
        )
        h3_redundant_probe_median_delta = cast(
            float,
            cast(dict[str, object], paired["h3_redundant_probes"])["median_delta"],
        )
        h3_active_pressure_median_delta = cast(
            float,
            cast(dict[str, object], paired["h3_active_ledger_pressure"])["median_delta"],
        )
        h1_passed = (
            h1_exploration_median_delta < 0
            and max(h1_completion_losses_by_family.values()) <= 1
            and h1_treatment_completions >= h1_reference_completions
        )
        h2_passed = (
            len(assessed_reopenings) == len(full_modifier_rows)
            and all(value == 1.0 for value in h2_retention_by_family.values())
            and all(value > 0 for value in h2_observed_matches_by_family.values())
            and h2_global_reopenings is not None
            and h2_local_scoped_revisions > 0
            and h2_global_reopenings < h2_local_scoped_revisions
        )
        h3_passed = (
            (h3_redundant_probe_median_delta < 0 or h3_active_pressure_median_delta < 0)
            and h3_treatment_completions >= h3_reference_completions
            and h3_action_ratio is not None
            and h3_action_ratio <= 1.05
        )
        evidence_quality_passed = (
            replay_rate == 1.0
            and receipt_rate == 1.0
            and infrastructure_failure_rows == 0
            and policy_error_rows == 0
        )
        hypotheses_passed = h1_passed and h2_passed and h3_passed
        return {
            "schema": BUILD003_SUMMARY_SCHEMA,
            "row_count": len(self._rows),
            "expected_row_count": self.expected_row_count,
            "paired": paired,
            "h2_conservative_repair": {
                "modifier_rows": len(full_modifier_rows),
                "base_mechanic_retention_rate": h2_retention,
                "base_mechanic_retention_rate_by_family": h2_retention_by_family,
                "observed_retained_matches_by_family": h2_observed_matches_by_family,
                "erroneous_global_reopenings": h2_global_reopenings,
                "erroneous_global_reopenings_assessed_rows": len(assessed_reopenings),
                "local_scoped_revisions": h2_local_scoped_revisions,
            },
            "evidence_quality": {
                "replay_determinism_rate": replay_rate,
                "receipt_completeness_rate": receipt_rate,
                "infrastructure_failure_rows": infrastructure_failure_rows,
                "policy_error_rows": policy_error_rows,
            },
            "decisions": {
                "H1": {
                    "status": "PASS" if h1_passed else "FAIL",
                    "passed": h1_passed,
                    "later_exploration_median_delta": h1_exploration_median_delta,
                    "completion_losses_by_family": h1_completion_losses_by_family,
                    "reference_completions": h1_reference_completions,
                    "treatment_completions": h1_treatment_completions,
                },
                "H2": {
                    "status": (
                        "NOT_MEASURED"
                        if len(assessed_reopenings) != len(full_modifier_rows)
                        else ("PASS" if h2_passed else "FAIL")
                    ),
                    "passed": h2_passed,
                    "all_modifier_rows_assessed": len(assessed_reopenings)
                    == len(full_modifier_rows),
                    "all_required_families_retained": all(
                        value == 1.0 for value in h2_retention_by_family.values()
                    ),
                    "all_required_families_have_observed_matches": all(
                        value > 0 for value in h2_observed_matches_by_family.values()
                    ),
                    "erroneous_global_reopenings": h2_global_reopenings,
                    "local_scoped_revisions": h2_local_scoped_revisions,
                },
                "H3": {
                    "status": "PASS" if h3_passed else "FAIL",
                    "passed": h3_passed,
                    "redundant_probe_median_delta": h3_redundant_probe_median_delta,
                    "active_ledger_pressure_median_delta": h3_active_pressure_median_delta,
                    "reference_completions": h3_reference_completions,
                    "treatment_completions": h3_treatment_completions,
                    "reference_action_median": h3_reference_action_median,
                    "treatment_action_median": h3_treatment_action_median,
                    "treatment_to_reference_action_ratio": h3_action_ratio,
                },
                "all_hypotheses_passed": hypotheses_passed,
                "evidence_quality_passed": evidence_quality_passed,
                "matrix_passed": hypotheses_passed and evidence_quality_passed,
            },
        }


def _metric(row: CurriculumResultRow, metric: str) -> float:
    fields = {
        "completed": float(row.completed),
        "environment_actions": float(row.environment_actions),
        "resets": float(row.resets),
        "exploratory_actions": float(row.exploratory_actions),
        "progress_actions": float(row.progress_actions),
        "redundant_probes": float(row.redundant_probes),
        "active_ledger_pressure": float(row.active_ledger_pressure),
        "unresolved_ledger_count": float(row.unresolved_ledger_count),
        "wall_time_seconds": float(row.wall_time_seconds),
        "peak_memory_bytes": float(row.peak_memory_bytes),
    }
    try:
        return fields[metric]
    except KeyError as error:
        raise ValueError(f"unsupported paired metric: {metric}") from error


__all__ = [
    "BUILD003_RESULT_SCHEMA",
    "BUILD003_SUMMARY_SCHEMA",
    "FAMILIES",
    "FROZEN_SEED_COUNT",
    "RUN_STATUSES",
    "VARIANTS",
    "Build003ResultLedger",
    "CurriculumResultRow",
    "FrozenCase",
    "PairedDistribution",
]
