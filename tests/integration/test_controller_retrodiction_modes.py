from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import cast

import pytest

from arc3.ablations import AblationId, features_for_ablation
from arc3.adapters.synthetic import SYNTHETIC_GAME_ID, SyntheticAdapter
from arc3.config import ARC3Config, BudgetConfig
from arc3.errors import CompetitionIntegrityError, PolicyError
from arc3.policy import ARC3Controller, ControllerPhase, ControllerPreset, RunContext
from arc3.profiling import HotPathChangeKind, HotPathPhase, HotPathProfiler
from arc3.types import EnvironmentMode, JSONValue
from arc3.world_model import RetrodictionConfig, RetrodictionMode, RetrodictionReason


def _context(tmp_path: Path, *, label: str) -> RunContext:
    return RunContext(
        run_id=f"stage07-{label}",
        episode_id=f"stage07-{label}-episode",
        game_id=SYNTHETIC_GAME_ID,
        trace_root=tmp_path / label / "trace",
        checkpoint_root=tmp_path / label / "checkpoint",
        config=ARC3Config(
            mode=EnvironmentMode.SYNTHETIC,
            seed=37,
            profile=f"stage07-{label}",
            budgets=BudgetConfig(max_actions=16, max_search_nodes=2_048),
        ),
        git_commit="stage07-controller-integration",
    )


def _drive(
    tmp_path: Path,
    mode: RetrodictionMode,
    *,
    steps: int = 6,
    profiler: HotPathProfiler | None = None,
) -> ARC3Controller:
    label = mode.value.lower()
    session = SyntheticAdapter(seed=37, size=8, max_steps=32).open(SYNTHETIC_GAME_ID)
    controller = ARC3Controller(
        ControllerPreset.FULL,
        retrodiction_config=RetrodictionConfig(mode=mode),
        hot_path_profiler=profiler,
    )
    controller.reset(_context(tmp_path, label=label))
    controller.observe(session.observation)
    for _ in range(steps):
        if controller.phase in {ControllerPhase.COMPLETE, ControllerPhase.GAME_OVER}:
            break
        decision = controller.choose_action()
        controller.apply_consequence(session.step(decision.action))
    if mode in {
        RetrodictionMode.EVENT_TRIGGERED,
        RetrodictionMode.CACHED_INCREMENTAL,
    }:
        assert controller._latest_observation is not None
        controller._update_world_models(controller._latest_observation)
    return controller


def _expected_change_kind(
    reason: RetrodictionReason,
    *,
    generation: int,
) -> HotPathChangeKind:
    if reason in {RetrodictionReason.DISABLED, RetrodictionReason.EXACT_CACHE_HIT}:
        return HotPathChangeKind.UNCHANGED
    if reason is RetrodictionReason.FIRST_USE:
        return HotPathChangeKind.INITIAL
    if reason in {
        RetrodictionReason.PREFIX_EXTENSION,
        RetrodictionReason.EVENT_RECEIPT_REUSE,
    }:
        return HotPathChangeKind.HISTORY_GROWTH
    if reason in {RetrodictionReason.NON_PREFIX, RetrodictionReason.INVALIDATED}:
        return HotPathChangeKind.GLOBAL_CHANGE
    if reason in {RetrodictionReason.FULL, RetrodictionReason.EVENT_FULL_AUDIT}:
        return HotPathChangeKind.INITIAL if generation == 1 else HotPathChangeKind.GLOBAL_CHANGE
    if reason is RetrodictionReason.RECENT_WINDOW:
        return HotPathChangeKind.INITIAL if generation == 1 else HotPathChangeKind.HISTORY_GROWTH
    raise AssertionError(f"unmapped retrodiction reason: {reason.value}")


def test_omitted_config_is_full_and_a3_is_exactly_none() -> None:
    full = ARC3Controller(ControllerPreset.FULL)
    assert full.retrodiction_config == RetrodictionConfig(mode=RetrodictionMode.FULL)

    ungated = ARC3Controller(
        ControllerPreset.FULL,
        features=features_for_ablation(AblationId.A3),
    )
    assert ungated.retrodiction_config == RetrodictionConfig(mode=RetrodictionMode.NONE)

    with pytest.raises(PolicyError, match="NONE retrodiction"):
        ARC3Controller(
            ControllerPreset.FULL,
            retrodiction_config=RetrodictionConfig(mode=RetrodictionMode.NONE),
        )
    with pytest.raises(PolicyError, match="all other modes require the gate"):
        ARC3Controller(
            ControllerPreset.FULL,
            features=features_for_ablation(AblationId.A3),
            retrodiction_config=RetrodictionConfig(mode=RetrodictionMode.FULL),
        )


def test_competition_rejects_even_semantically_default_explicit_override() -> None:
    with pytest.raises(CompetitionIntegrityError, match="retrodiction overrides"):
        ARC3Controller(
            ControllerPreset.COMPETITION,
            retrodiction_config=RetrodictionConfig(mode=RetrodictionMode.FULL),
        )


@pytest.mark.integration
@pytest.mark.parametrize(
    "mode",
    (
        RetrodictionMode.FULL,
        RetrodictionMode.RECENT_WINDOW_8,
        RetrodictionMode.EVENT_TRIGGERED,
        RetrodictionMode.CACHED_INCREMENTAL,
    ),
)
def test_controller_receipts_bind_each_retrodiction_mode(
    tmp_path: Path,
    mode: RetrodictionMode,
) -> None:
    controller = _drive(tmp_path, mode)
    events = controller.journal.verify_manifest()
    by_id = {event.event_id: event for event in events}
    run_started = next(event for event in events if event.event_type == "run.started")
    assert run_started.payload["retrodiction_config"] == controller.retrodiction_config.to_dict()
    assert run_started.payload["retrodiction_configuration_hash"] == (
        controller.retrodiction_config.configuration_hash
    )

    completed = [event for event in events if event.event_type == "model.retrodiction_completed"]
    assert completed
    assert {event.payload["mode"] for event in completed} == {mode.value}
    for event in completed:
        started_id = event.payload["retrodiction_started_event_id"]
        started = by_id[started_id]
        assert started.event_type == "model.retrodiction_started"
        assert started.payload["namespace_key"] == event.payload["namespace_key"]
        assert started.payload["cache_key"] == event.payload["cache_key"]
        reused_id = event.payload["retrodiction_reused_event_id"]
        assert bool(reused_id) is event.payload["reused"]
        if isinstance(reused_id, str):
            reused = by_id[reused_id]
            assert reused.event_type == "model.retrodiction_reused"
            assert reused.payload["retrodiction_started_event_id"] == started_id
            assert reused.payload["artifact_id"] == event.payload["artifact_id"]

    promotions = [event for event in events if event.event_type == "model.rule_promoted"]
    assert promotions
    for promotion in promotions:
        source = by_id[promotion.payload["retrodiction_completed_event_id"]]
        assert source.event_type == "model.retrodiction_completed"
        assert promotion.payload["retrodiction_artifact_id"] == source.payload["artifact_id"]
        assert promotion.payload["retrodiction_mode"] == mode.value

    if mode is RetrodictionMode.CACHED_INCREMENTAL:
        assert any(event.payload["reused"] is True for event in completed)
        assert any(event.event_type == "model.retrodiction_reused" for event in events)
    if mode is RetrodictionMode.FULL:
        assert all(event.payload["reused"] is False for event in completed)


@pytest.mark.integration
@pytest.mark.parametrize(
    "mode",
    (
        RetrodictionMode.FULL,
        RetrodictionMode.RECENT_WINDOW_8,
        RetrodictionMode.EVENT_TRIGGERED,
        RetrodictionMode.CACHED_INCREMENTAL,
    ),
)
def test_retrodiction_profiler_uses_only_stable_change_kinds(
    tmp_path: Path,
    mode: RetrodictionMode,
) -> None:
    profiler = HotPathProfiler(
        rss_sampler=lambda: {
            "current_rss_bytes": 4_096,
            "measurement_source": "deterministic-test-sample",
            "peak_rss_bytes": 8_192,
            "reason": None,
        }
    )
    controller = _drive(tmp_path, mode, profiler=profiler)
    completed = [
        event
        for event in controller.journal.verify_manifest()
        if event.event_type == "model.retrodiction_completed"
    ]
    expected: Counter[HotPathChangeKind] = Counter(
        _expected_change_kind(
            RetrodictionReason(cast(str, event.payload["reason"])),
            generation=cast(int, event.payload["generation"]),
        )
        for event in completed
    )

    profile = profiler.summary()
    phases = cast(dict[str, JSONValue], profile["phases"])
    retrodiction = cast(dict[str, JSONValue], phases[HotPathPhase.RETRODICTION.value])
    observed = cast(dict[str, JSONValue], retrodiction["change_kind_counts"])
    assert observed == {kind.value: expected[kind] for kind in HotPathChangeKind}
