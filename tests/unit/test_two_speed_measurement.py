"""Frozen pure-contract tests for the Build 001 Stage 08 measurement."""

from __future__ import annotations

from dataclasses import replace

import pytest

from arc3.errors import EvaluationError
from arc3.evaluation.two_speed_measurement import (
    EXPECTED_CELL_COUNT,
    MATERIALITY_MAX_MEDIAN_RATIO,
    MAX_DECISION_WALL_NS,
    MAX_PEAK_RSS_BYTES,
    MAX_TRACE_BYTES_PER_RUN,
    MEASUREMENT_MATRIX_SHA256,
    MEASUREMENT_PLAN_SHA256,
    NONREGRESSION_MIN_FRACTION,
    PREDECLARATION_PATH,
    PREDECLARATION_SHA256,
    VARIANT_ORDER,
    ActionMeasurement,
    BoundaryStatus,
    CellResult,
    CellStatus,
    DeepTrigger,
    DeepTriggerMeasurement,
    DeliberationStatus,
    DevelopmentIdentity,
    MeasurementCell,
    MeasurementVariant,
    ReasoningPath,
    ReasoningTerminalKind,
    ReasoningTerminalMeasurement,
    ScoreMeasurement,
    WorkAvailability,
    WorkMeasurement,
    aggregate_score_evidence,
    build_measurement_matrix,
    build_measurement_plan,
    canonical_measurement_hash,
    evaluate_materiality_gates,
    validate_predeclaration_bytes,
    verify_canonical_object_hash,
)


def _work(variant: MeasurementVariant) -> WorkMeasurement:
    if variant is MeasurementVariant.FROZEN_BUILD_000_FULL:
        return WorkMeasurement.unavailable_at_frozen_source()
    return WorkMeasurement.measured(
        prediction_invocations=1,
        compilation_invocations=1,
        retrodicted_transitions=2,
        simulation_invocations=3,
        search_expanded_nodes=4,
        cache_hits=5,
        cache_misses=6,
        cache_invalidations=7,
    )


def _action(
    variant: MeasurementVariant,
    total_wall_ns: int,
    *,
    boundary_status: BoundaryStatus = BoundaryStatus.NORMAL,
    action_ordinal: int = 0,
    environment_action_identity: str = "canonical-action-1",
    reasoning_path: ReasoningPath | None = None,
    deep_triggers: tuple[DeepTriggerMeasurement, ...] = (),
    reasoning_terminal: ReasoningTerminalMeasurement | None = None,
) -> ActionMeasurement:
    if variant is MeasurementVariant.FROZEN_BUILD_000_FULL:
        selected_path = None
        terminal = None
    else:
        selected_path = reasoning_path or (
            ReasoningPath.DEEP
            if variant is MeasurementVariant.BUILD_001_LEGACY_ALWAYS_DEEP
            else ReasoningPath.FAST
        )
        terminal = reasoning_terminal or ReasoningTerminalMeasurement(
            path_selected_event_id=f"reasoning-selected-{action_ordinal}",
            terminal_event_id=f"reasoning-terminal-{action_ordinal}",
            path=selected_path,
            kind=ReasoningTerminalKind.DELIBERATION_COMPLETED,
            status=DeliberationStatus.COMPLETED,
        )
    if boundary_status is not BoundaryStatus.NORMAL:
        return ActionMeasurement(
            action_ordinal=action_ordinal,
            environment_action_identity=environment_action_identity,
            boundary_status=boundary_status,
            choose_wall_ns=None,
            choose_cpu_ns=None,
            consequence_wall_ns=None,
            consequence_cpu_ns=None,
            checkpoint_wall_ns=None,
            checkpoint_cpu_ns=None,
            controller_total_wall_ns=None,
            controller_total_cpu_ns=None,
            work=_work(variant),
            reasoning_path=selected_path,
            deep_triggers=deep_triggers,
            reasoning_terminal=terminal,
        )
    checkpoint_wall_ns = min(1, total_wall_ns)
    measured_without_checkpoint = total_wall_ns - checkpoint_wall_ns
    choose_wall_ns = measured_without_checkpoint // 2
    consequence_wall_ns = measured_without_checkpoint - choose_wall_ns
    choose_cpu_ns = choose_wall_ns * 2
    consequence_cpu_ns = consequence_wall_ns * 2
    checkpoint_cpu_ns = checkpoint_wall_ns * 2
    return ActionMeasurement(
        action_ordinal=action_ordinal,
        environment_action_identity=environment_action_identity,
        boundary_status=boundary_status,
        choose_wall_ns=choose_wall_ns,
        choose_cpu_ns=choose_cpu_ns,
        consequence_wall_ns=consequence_wall_ns,
        consequence_cpu_ns=consequence_cpu_ns,
        checkpoint_wall_ns=checkpoint_wall_ns,
        checkpoint_cpu_ns=checkpoint_cpu_ns,
        controller_total_wall_ns=total_wall_ns,
        controller_total_cpu_ns=choose_cpu_ns + consequence_cpu_ns + checkpoint_cpu_ns,
        work=_work(variant),
        reasoning_path=selected_path,
        deep_triggers=deep_triggers,
        reasoning_terminal=terminal,
    )


def _result(
    cell: MeasurementCell,
    total_wall_ns: int,
    *,
    status: CellStatus = CellStatus.SUCCESS,
    boundary_status: BoundaryStatus = BoundaryStatus.NORMAL,
    score: ScoreMeasurement | None = None,
    integrity_valid: bool = True,
    terminal_state: str | None = "NOT_FINISHED",
    controller_faults: int = 0,
    controller_fault_identities: tuple[str, ...] = (),
) -> CellResult:
    return CellResult(
        cell=cell,
        status=status,
        actions=(_action(cell.variant, total_wall_ns, boundary_status=boundary_status),),
        score=score or ScoreMeasurement(True, 0.25, 0, False),
        environment_actions=1,
        resets=0,
        peak_rss_bytes=1_000,
        trace_bytes=2_000,
        checkpoint_bytes=3_000,
        terminal_state=terminal_state,
        controller_faults=controller_faults,
        controller_fault_identities=controller_fault_identities,
        source_identity_valid=integrity_valid,
        failure_kind=None if status is CellStatus.SUCCESS else "fixture-failure",
    )


def _complete_results(
    *,
    candidate_wall_by_repetition: tuple[int, ...] = (75, 75, 75, 75, 75),
) -> list[CellResult]:
    values: list[CellResult] = []
    for cell in build_measurement_matrix():
        if cell.variant is MeasurementVariant.BUILD_001_TWO_SPEED:
            wall_ns = candidate_wall_by_repetition[cell.repetition]
        elif cell.variant is MeasurementVariant.BUILD_001_TWO_SPEED_NO_PREDICTION_CACHE:
            wall_ns = 80
        else:
            wall_ns = 100
        values.append(_result(cell, wall_ns))
    return values


def _replace_result(
    values: list[CellResult],
    variant: MeasurementVariant,
    repetition: int,
    replacement: CellResult,
) -> None:
    index = next(
        index
        for index, result in enumerate(values)
        if result.cell.variant is variant and result.cell.repetition == repetition
    )
    values[index] = replacement


def test_predeclaration_bytes_and_canonical_plan_are_frozen() -> None:
    content = PREDECLARATION_PATH.read_bytes()
    validate_predeclaration_bytes(content)
    with pytest.raises(EvaluationError, match="predeclaration hash changed"):
        validate_predeclaration_bytes(content + b"\n")

    plan = build_measurement_plan()
    assert PREDECLARATION_SHA256 == (
        "sha256:3342b6e2635c0606391c9aea02b2fec0cf4c5642a3d38b95768a1b77b4520878"
    )
    assert plan["predeclaration_sha256"] == PREDECLARATION_SHA256
    assert plan["expected_cell_count"] == 20
    assert plan["evaluation_matrix_hash"] == MEASUREMENT_MATRIX_SHA256
    assert plan["plan_hash"] == MEASUREMENT_PLAN_SHA256
    assert plan["public_holdout_allowed"] is False
    assert verify_canonical_object_hash(plan, hash_field="plan_hash")
    assert canonical_measurement_hash(plan) == canonical_measurement_hash(dict(plan))
    tampered = dict(plan)
    tampered["expected_cell_count"] = 19
    assert not verify_canonical_object_hash(tampered, hash_field="plan_hash")


def test_exact_twenty_cell_balanced_rotation() -> None:
    cells = build_measurement_matrix()
    assert len(cells) == EXPECTED_CELL_COUNT == 20
    assert len({cell.cell_id for cell in cells}) == 20
    assert [
        [cell.variant for cell in cells if cell.repetition == repetition] for repetition in range(5)
    ] == [
        list(VARIANT_ORDER),
        [*VARIANT_ORDER[1:], VARIANT_ORDER[0]],
        [*VARIANT_ORDER[2:], *VARIANT_ORDER[:2]],
        [VARIANT_ORDER[3], *VARIANT_ORDER[:3]],
        list(VARIANT_ORDER),
    ]
    assert [sum(cell.variant is variant for cell in cells) for variant in VARIANT_ORDER] == [
        5,
        5,
        5,
        5,
    ]
    assert [cell.ordinal for cell in cells] == list(range(20))

    first = cells[0]
    with pytest.raises(EvaluationError, match="balanced rotation"):
        MeasurementCell(
            ordinal=first.ordinal,
            repetition=first.repetition,
            position=first.position,
            variant=MeasurementVariant.BUILD_001_TWO_SPEED,
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("partition", "public-holdout"),
        ("game_id", "not-the-frozen-development-game"),
        ("seed", 8),
        ("max_actions", 9),
        ("max_resets", 9),
        ("worker_wall_seconds", 121.0),
        ("environment_mode", "ONLINE"),
        ("network_enabled", True),
        ("acquire_missing", True),
        ("asset_aggregate_sha256", "sha256:" + "0" * 64),
        ("public_partition_manifest_sha256", "sha256:" + "1" * 64),
    ],
)
def test_development_identity_rejects_every_frozen_field_drift(field: str, value: object) -> None:
    with pytest.raises(EvaluationError, match="exact frozen development identity"):
        replace(DevelopmentIdentity(), **{field: value})


def test_development_identity_mapping_is_exact_and_does_not_accept_asset_paths() -> None:
    payload = DevelopmentIdentity().to_dict()
    assert DevelopmentIdentity.from_mapping(payload).to_dict() == payload
    payload["asset_path"] = "C:/forbidden-enumeration"
    with pytest.raises(EvaluationError, match="fields are not exact"):
        DevelopmentIdentity.from_mapping(payload)


def test_frozen_build_work_is_null_not_zero_and_build001_work_is_required() -> None:
    unavailable = WorkMeasurement.unavailable_at_frozen_source()
    assert unavailable.availability is WorkAvailability.UNAVAILABLE_AT_FROZEN_SOURCE
    assert all(
        value is None for key, value in unavailable.to_dict().items() if key != "availability"
    )
    with pytest.raises(EvaluationError, match="null, never zero"):
        WorkMeasurement(
            availability=WorkAvailability.UNAVAILABLE_AT_FROZEN_SOURCE,
            prediction_invocations=0,
            compilation_invocations=None,
            retrodicted_transitions=None,
            simulation_invocations=None,
            search_expanded_nodes=None,
            cache_hits=None,
            cache_misses=None,
            cache_invalidations=None,
        )

    build000_cell = next(
        cell
        for cell in build_measurement_matrix()
        if cell.variant is MeasurementVariant.FROZEN_BUILD_000_FULL
    )
    bad_build000_action = replace(
        _action(build000_cell.variant, 100), work=WorkMeasurement.measured()
    )
    with pytest.raises(EvaluationError, match="Build 000 integer work"):
        replace(_result(build000_cell, 100), actions=(bad_build000_action,))

    build001_cell = next(
        cell
        for cell in build_measurement_matrix()
        if cell.variant is MeasurementVariant.BUILD_001_TWO_SPEED
    )
    bad_build001_action = replace(
        _action(build001_cell.variant, 75),
        work=WorkMeasurement.unavailable_at_frozen_source(),
    )
    with pytest.raises(EvaluationError, match="Build 001 integer work"):
        replace(_result(build001_cell, 75), actions=(bad_build001_action,))

    build000_action = _action(build000_cell.variant, 100)
    build000_payload = build000_action.to_dict()
    assert build000_payload["reasoning_path"] is None
    assert build000_payload["reasoning_terminal_receipt"] is None
    assert build000_payload["ordered_triggers"] == []


def test_action_measurement_requires_complete_consistent_normal_boundary() -> None:
    action = _action(MeasurementVariant.BUILD_001_TWO_SPEED, 75)
    assert action.controller_total_wall_ns == (
        action.choose_wall_ns + action.consequence_wall_ns + action.checkpoint_wall_ns
    )
    assert action.controller_total_cpu_ns == (
        action.choose_cpu_ns + action.consequence_cpu_ns + action.checkpoint_cpu_ns
    )
    with pytest.raises(EvaluationError, match="complete timing"):
        replace(action, choose_wall_ns=None)
    with pytest.raises(EvaluationError, match="wall total"):
        replace(action, controller_total_wall_ns=76)
    with pytest.raises(EvaluationError, match="CPU total"):
        replace(action, controller_total_cpu_ns=151)


@pytest.mark.parametrize(
    "mismatch",
    ["action_identity", "resets", "terminal_state", "score", "levels", "completed", "faults"],
)
def test_gate_fails_closed_on_exact_paired_behavior_mismatch(mismatch: str) -> None:
    values = _complete_results()
    target = next(
        result
        for result in values
        if result.cell.variant is MeasurementVariant.BUILD_001_TWO_SPEED
        and result.cell.repetition == 0
    )
    replacement = target
    if mismatch == "action_identity":
        replacement = replace(
            target,
            actions=(replace(target.actions[0], environment_action_identity="different-action"),),
        )
    elif mismatch == "resets":
        replacement = replace(target, resets=1)
    elif mismatch == "terminal_state":
        replacement = replace(target, terminal_state="WIN")
    elif mismatch == "score":
        replacement = replace(target, score=ScoreMeasurement(True, 0.5, 0, False))
    elif mismatch == "levels":
        replacement = replace(target, score=ScoreMeasurement(True, 0.25, 1, False))
    elif mismatch == "completed":
        replacement = replace(target, score=ScoreMeasurement(True, 0.25, 0, True))
    else:
        replacement = replace(
            target,
            controller_faults=1,
            controller_fault_identities=("canonical-controller-fault",),
        )
    _replace_result(
        values,
        MeasurementVariant.BUILD_001_TWO_SPEED,
        0,
        replacement,
    )

    gate = evaluate_materiality_gates(values)
    assert gate.behavior_parity_failure_count == 1
    assert not gate.passed


def test_behavior_signature_preserves_exact_environment_action_order() -> None:
    cell = next(
        cell
        for cell in build_measurement_matrix()
        if cell.variant is MeasurementVariant.BUILD_001_TWO_SPEED
    )
    first = _action(cell.variant, 40, action_ordinal=0, environment_action_identity="action-a")
    second = _action(cell.variant, 35, action_ordinal=1, environment_action_identity="action-b")
    forward = replace(
        _result(cell, 75),
        actions=(first, second),
        environment_actions=2,
    )
    reverse = replace(
        forward,
        actions=(
            replace(first, environment_action_identity="action-b"),
            replace(second, environment_action_identity="action-a"),
        ),
    )
    assert forward.behavior_signature != reverse.behavior_signature


def test_gate_compares_controller_fault_identity_at_equal_count() -> None:
    values = [
        replace(
            result,
            controller_faults=1,
            controller_fault_identities=("shared-fault-kind",),
        )
        for result in _complete_results()
    ]
    target = next(
        result
        for result in values
        if result.cell.variant is MeasurementVariant.BUILD_001_TWO_SPEED
        and result.cell.repetition == 0
    )
    _replace_result(
        values,
        MeasurementVariant.BUILD_001_TWO_SPEED,
        0,
        replace(target, controller_fault_identities=("different-fault-kind",)),
    )
    gate = evaluate_materiality_gates(values)
    assert gate.behavior_parity_failure_count == 1
    assert not gate.passed


@pytest.mark.parametrize("resource", ["rss", "trace", "decision"])
def test_gate_fails_closed_on_each_frozen_resource_limit(resource: str) -> None:
    values = _complete_results()
    target = next(
        result
        for result in values
        if result.cell.variant is MeasurementVariant.BUILD_001_TWO_SPEED
        and result.cell.repetition == 0
    )
    if resource == "rss":
        replacement = replace(target, peak_rss_bytes=MAX_PEAK_RSS_BYTES + 1)
    elif resource == "trace":
        replacement = replace(target, trace_bytes=MAX_TRACE_BYTES_PER_RUN + 1)
    else:
        action = target.actions[0]
        assert action.consequence_wall_ns is not None
        assert action.checkpoint_wall_ns is not None
        replacement = replace(
            target,
            actions=(
                replace(
                    action,
                    choose_wall_ns=MAX_DECISION_WALL_NS + 1,
                    controller_total_wall_ns=(
                        MAX_DECISION_WALL_NS
                        + 1
                        + action.consequence_wall_ns
                        + action.checkpoint_wall_ns
                    ),
                ),
            ),
        )
    _replace_result(
        values,
        MeasurementVariant.BUILD_001_TWO_SPEED,
        0,
        replacement,
    )

    gate = evaluate_materiality_gates(values)
    assert gate.resource_failure_count == 1
    assert not gate.passed


def test_resource_limits_are_inclusive() -> None:
    target = next(
        result
        for result in _complete_results()
        if result.cell.variant is MeasurementVariant.BUILD_001_TWO_SPEED
    )
    action = target.actions[0]
    assert action.consequence_wall_ns is not None
    assert action.checkpoint_wall_ns is not None
    at_limits = replace(
        target,
        peak_rss_bytes=MAX_PEAK_RSS_BYTES,
        trace_bytes=MAX_TRACE_BYTES_PER_RUN,
        actions=(
            replace(
                action,
                choose_wall_ns=MAX_DECISION_WALL_NS,
                controller_total_wall_ns=(
                    MAX_DECISION_WALL_NS + action.consequence_wall_ns + action.checkpoint_wall_ns
                ),
            ),
        ),
    )
    assert at_limits.resources_valid


def test_two_speed_deep_path_requires_typed_trigger_sources_and_terminal_receipt() -> None:
    values = _complete_results()
    target = next(
        result
        for result in values
        if result.cell.variant is MeasurementVariant.BUILD_001_TWO_SPEED
        and result.cell.repetition == 0
    )
    action = target.actions[0]
    terminal = ReasoningTerminalMeasurement(
        path_selected_event_id="selected-deep",
        terminal_event_id="terminal-deep",
        path=ReasoningPath.DEEP,
        kind=ReasoningTerminalKind.DELIBERATION_COMPLETED,
        status=DeliberationStatus.COMPLETED,
    )
    deep = replace(
        action,
        reasoning_path=ReasoningPath.DEEP,
        deep_triggers=(
            DeepTriggerMeasurement(
                DeepTrigger.REOPENING,
                ("source-event-1",),
            ),
        ),
        reasoning_terminal=terminal,
    )
    _replace_result(
        values,
        MeasurementVariant.BUILD_001_TWO_SPEED,
        0,
        replace(target, actions=(deep,)),
    )
    accepted = evaluate_materiality_gates(values)
    assert accepted.reasoning_receipt_failure_count == 0
    assert accepted.passed

    without_trigger = list(values)
    _replace_result(
        without_trigger,
        MeasurementVariant.BUILD_001_TWO_SPEED,
        0,
        replace(target, actions=(replace(deep, deep_triggers=()),)),
    )
    trigger_gate = evaluate_materiality_gates(without_trigger)
    assert trigger_gate.reasoning_receipt_failure_count == 1
    assert not trigger_gate.passed

    without_terminal = list(values)
    _replace_result(
        without_terminal,
        MeasurementVariant.BUILD_001_TWO_SPEED,
        0,
        replace(target, actions=(replace(deep, reasoning_terminal=None),)),
    )
    terminal_gate = evaluate_materiality_gates(without_terminal)
    assert terminal_gate.reasoning_receipt_failure_count == 1
    assert not terminal_gate.passed


def test_typed_deep_receipt_rejects_missing_sources_and_terminal_disagreement() -> None:
    with pytest.raises(EvaluationError, match="at least one source"):
        DeepTriggerMeasurement(DeepTrigger.REOPENING, ())
    with pytest.raises(EvaluationError, match="kind and status disagree"):
        ReasoningTerminalMeasurement(
            path_selected_event_id="selected-deep",
            terminal_event_id="terminal-deep",
            path=ReasoningPath.DEEP,
            kind=ReasoningTerminalKind.FALLBACK_USED,
            status=DeliberationStatus.COMPLETED,
        )


def test_materiality_gate_passes_at_frozen_ratio_edge() -> None:
    gate = evaluate_materiality_gates(_complete_results())
    assert MATERIALITY_MAX_MEDIAN_RATIO == 0.75
    assert NONREGRESSION_MIN_FRACTION == 0.70
    assert gate.complete_matrix
    assert gate.terminal_failure_count == 0
    assert gate.censored_action_count == 0
    assert gate.integrity_failure_count == 0
    assert gate.behavior_parity_failure_count == 0
    assert gate.resource_failure_count == 0
    assert gate.reasoning_receipt_failure_count == 0
    assert gate.passed
    assert len(gate.comparisons) == 2
    for comparison in gate.comparisons:
        assert comparison.passed
        assert comparison.paired_action_count == 5
        assert comparison.valid_cell_pairs == 5
        assert comparison.median_paired_wall_ratio == pytest.approx(0.75)
        assert comparison.median_reduction_fraction == pytest.approx(0.25)
        assert comparison.nonregressing_cell_fraction == 1.0


def test_nonregression_is_counted_by_predeclared_cell_not_selected_action_rows() -> None:
    three_nonregressing = evaluate_materiality_gates(
        _complete_results(candidate_wall_by_repetition=(75, 75, 75, 105, 105))
    )
    assert not three_nonregressing.passed
    for comparison in three_nonregressing.comparisons:
        assert comparison.median_paired_wall_ratio == pytest.approx(0.75)
        assert comparison.material_reduction_passed
        assert comparison.nonregressing_cell_count == 3
        assert comparison.nonregressing_cell_fraction == pytest.approx(0.6)
        assert not comparison.nonregression_passed

    four_nonregressing = evaluate_materiality_gates(
        _complete_results(candidate_wall_by_repetition=(75, 75, 75, 75, 105))
    )
    assert four_nonregressing.passed
    for comparison in four_nonregressing.comparisons:
        assert comparison.nonregressing_cell_count == 4
        assert comparison.nonregressing_cell_fraction == pytest.approx(0.8)


def test_censored_failed_missing_and_integrity_rows_never_pass() -> None:
    candidate = MeasurementVariant.BUILD_001_TWO_SPEED

    censored = _complete_results()
    censored_cell = next(
        result.cell
        for result in censored
        if result.cell.variant is candidate and result.cell.repetition == 0
    )
    _replace_result(
        censored,
        candidate,
        0,
        _result(censored_cell, 1, boundary_status=BoundaryStatus.CENSORED),
    )
    censored_gate = evaluate_materiality_gates(censored)
    assert not censored_gate.passed
    assert censored_gate.censored_action_count == 1
    assert all(comparison.censored_action_pairs == 1 for comparison in censored_gate.comparisons)

    failed = _complete_results()
    failed_cell = next(
        result.cell
        for result in failed
        if result.cell.variant is candidate and result.cell.repetition == 0
    )
    _replace_result(
        failed,
        candidate,
        0,
        _result(failed_cell, 1, status=CellStatus.FAILURE),
    )
    failed_gate = evaluate_materiality_gates(failed)
    assert not failed_gate.passed
    assert failed_gate.terminal_failure_count == 1
    assert all(comparison.failed_cell_pairs == 1 for comparison in failed_gate.comparisons)

    missing_gate = evaluate_materiality_gates(_complete_results()[:-1])
    assert not missing_gate.passed
    assert not missing_gate.complete_matrix
    assert missing_gate.missing_cell_count == 1

    invalid = _complete_results()
    invalid_cell = next(
        result.cell
        for result in invalid
        if result.cell.variant is candidate and result.cell.repetition == 0
    )
    _replace_result(
        invalid,
        candidate,
        0,
        _result(invalid_cell, 1, integrity_valid=False),
    )
    invalid_gate = evaluate_materiality_gates(invalid)
    assert not invalid_gate.passed
    assert invalid_gate.integrity_failure_count == 1

    prohibited_contact = _complete_results()
    contact_result = prohibited_contact[0]
    prohibited_contact[0] = replace(contact_result, holdout_exposure_count=1)
    contact_gate = evaluate_materiality_gates(prohibited_contact)
    assert not contact_gate.passed
    assert contact_gate.integrity_failure_count == 1


def test_recovered_failure_score_is_preserved_but_excluded_from_success_metrics_and_gate() -> None:
    values = _complete_results()
    candidate = MeasurementVariant.BUILD_001_TWO_SPEED
    failed_cell = next(
        result.cell
        for result in values
        if result.cell.variant is candidate and result.cell.repetition == 0
    )
    recovered_score = ScoreMeasurement(True, 99.0, 99, True)
    _replace_result(
        values,
        candidate,
        0,
        _result(
            failed_cell,
            1,
            status=CellStatus.FAILURE,
            score=recovered_score,
        ),
    )

    aggregate = aggregate_score_evidence(values, candidate)
    successful = aggregate.successful_score_metrics
    recovered = aggregate.recovered_failure_score_metrics
    assert successful.run_count == 4
    assert successful.score_sum == pytest.approx(1.0)
    assert successful.mean_score == pytest.approx(0.25)
    assert successful.levels_completed == 0
    assert recovered.run_count == 1
    assert recovered.score_sum == pytest.approx(99.0)
    assert recovered.mean_score == pytest.approx(99.0)
    assert recovered.levels_completed == 99
    assert aggregate.to_dict()["score_metric_scope"] == "SUCCESSFUL_RUNS_ONLY"

    gate = evaluate_materiality_gates(values)
    assert not gate.passed
    assert gate.terminal_failure_count == 1
    assert all(comparison.paired_action_count == 4 for comparison in gate.comparisons)
    assert all(comparison.failed_cell_pairs == 1 for comparison in gate.comparisons)


def test_unverified_failed_score_has_no_aggregate_and_result_hash_is_canonical() -> None:
    cell = next(
        cell
        for cell in build_measurement_matrix()
        if cell.variant is MeasurementVariant.BUILD_001_TWO_SPEED
    )
    result = _result(
        cell,
        1,
        status=CellStatus.FAILURE,
        score=ScoreMeasurement.unverified(),
    )
    aggregate = aggregate_score_evidence((result,), cell.variant)
    assert aggregate.successful_score_metrics.run_count == 0
    assert aggregate.recovered_failure_score_metrics.run_count == 0
    assert aggregate.recovered_failure_score_metrics.mean_score is None
    assert aggregate.unscored_failure_runs == 1

    sealed = result.sealed_dict()
    assert sealed["result_hash"] == result.result_hash
    assert verify_canonical_object_hash(sealed, hash_field="result_hash")
    sealed["status"] = CellStatus.SUCCESS.value
    assert not verify_canonical_object_hash(sealed, hash_field="result_hash")


def test_duplicate_or_undeclared_result_identity_is_rejected() -> None:
    result = _complete_results()[0]
    with pytest.raises(EvaluationError, match="must be unique"):
        evaluate_materiality_gates((result, result))

    undeclared = replace(result.cell, development=DevelopmentIdentity())
    object.__setattr__(undeclared, "ordinal", 99)
    object.__setattr__(undeclared, "repetition", 24)
    with pytest.raises(EvaluationError, match="undeclared measurement cell"):
        evaluate_materiality_gates((replace(result, cell=undeclared),))
