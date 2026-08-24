"""Focused tests for the executable Build 002 one-shot collector."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest
from scripts import run_build002_holdout as runner

from arc3.errors import EvaluationError
from arc3.packaging.models import ExternalSurfaceUnavailableError, PackagingError

REPOSITORY = Path(__file__).resolve().parents[2]
MANIFEST = REPOSITORY / "docs" / "evaluation" / "public-game-partitions.v0.1.json"


def _scorecard(*, completed: bool = True) -> SimpleNamespace:
    run = SimpleNamespace(
        id="game-a",
        score=25.0 if completed else 0.0,
        levels_completed=1 if completed else 0,
        actions=2,
        resets=1,
        state="WIN" if completed else "NOT_FINISHED",
        completed=completed,
        level_scores=[25.0 if completed else 0.0],
        level_actions=[2],
        level_baseline_actions=[1],
        api_key="SENTINEL_SECRET",
        opaque={"private": "SENTINEL_SECRET"},
    )
    return SimpleNamespace(
        environments=[SimpleNamespace(id="game-a", runs=[run])],
        api_key="SENTINEL_SECRET",
        card_id="private-card",
        source_url="https://private.invalid",
    )


def test_scorecard_collector_is_exact_and_credential_free() -> None:
    payload = runner.collect_scorecard_payload(_scorecard(), ("game-a",))

    assert payload["games"][0]["toolkit_score"] == 0.25
    assert payload["games"][0]["levels"][0]["human_baseline_actions"] == 1
    assert payload["scorer_identity"] == runner.pinned_toolkit_scorer_identity()
    encoded = json.dumps(payload, sort_keys=True)
    assert "SENTINEL_SECRET" not in encoded
    assert "private-card" not in encoded
    assert "source_url" not in encoded


def test_scorecard_collector_fails_closed_on_lifecycle_or_type_drift() -> None:
    scorecard = _scorecard()
    scorecard.environments[0].runs.append(scorecard.environments[0].runs[0])
    with pytest.raises(EvaluationError, match="exactly one"):
        runner.collect_scorecard_payload(scorecard, ("game-a",))

    scorecard = _scorecard()
    scorecard.environments[0].runs[0].completed = "yes"
    with pytest.raises(EvaluationError, match="must be boolean"):
        runner.collect_scorecard_payload(scorecard, ("game-a",))


def test_scorecard_normalizes_exact_pinned_level_and_game_caps() -> None:
    scorecard = _scorecard()
    run = scorecard.environments[0].runs[0]
    run.score = 100.0
    run.actions = 1
    run.level_scores = [115.0]
    run.level_actions = [1]
    run.level_baseline_actions = [2]

    payload = runner.collect_scorecard_payload(scorecard, ("game-a",))

    assert payload["games"][0]["levels"][0]["toolkit_score"] == 1.15
    assert payload["games"][0]["toolkit_score"] == 1.0


@pytest.mark.parametrize(
    ("field", "value"),
    (("score", 100.000001), ("level_scores", [115.000001])),
)
def test_scorecard_rejects_values_above_exact_pinned_caps(field: str, value: object) -> None:
    scorecard = _scorecard()
    setattr(scorecard.environments[0].runs[0], field, value)

    with pytest.raises(EvaluationError, match="finite non-negative range"):
        runner.collect_scorecard_payload(scorecard, ("game-a",))


def test_scorecard_rejects_in_range_score_that_disagrees_with_action_rows() -> None:
    scorecard = _scorecard()
    scorecard.environments[0].runs[0].score = 24.0

    with pytest.raises(EvaluationError, match="game score does not reconcile"):
        runner.collect_scorecard_payload(scorecard, ("game-a",))


def test_pinned_scorer_identity_reconciles_with_upstream_lock() -> None:
    lock = json.loads((REPOSITORY / "upstream.lock.json").read_text(encoding="utf-8"))
    refresh = lock["build_002_refresh"]
    identity = runner.pinned_toolkit_scorer_identity()

    assert identity["commit"] == refresh["public_repository_heads"]["arcprize/ARC-AGI"]
    assert (
        identity["sha256"]
        == refresh["controlling_file_sha256"]["arcprize/ARC-AGI:arc_agi/scorecard.py"]
    )


def test_rss_monitor_uses_kernel_high_water_for_tournament_peak(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from arc3.profiling import runtime

    monkeypatch.setattr(
        runtime,
        "process_memory_sample",
        lambda: {
            "current_rss_bytes": 10,
            "measurement_source": "linux-proc-status-rss-hwm",
            "peak_rss_bytes": 100,
            "reason": None,
        },
    )

    with runner._RssMonitor() as monitor:
        pass

    assert monitor.kernel_peak_rss_bytes == 100
    assert monitor.sampled_current_rss_max_between(0.0, float("inf")) == 10
    assert monitor.measurement_source == "linux-proc-status-rss-hwm"


def test_measurement_reconciles_governor_and_derives_budget_failure() -> None:
    raw = runner.collect_scorecard_payload(_scorecard(completed=False), ("game-a",))
    launch = {
        "tournament_receipt": {
            "receipt": {
                "games": [
                    {
                        "actions_authorized": 2,
                        "allocated_seconds": 3.0,
                        "began_at_seconds": 10.0,
                        "elapsed_seconds": 2.0,
                        "finalized_at_seconds": 12.0,
                        "game_id": "game-a",
                        "reason": "game-time-limit",
                        "reset_limit": 8,
                        "resets_authorized": 1,
                        "reserve_remaining_seconds": 6000.0,
                    }
                ]
            }
        }
    }
    failures: list[dict[str, str]] = []
    monitor = SimpleNamespace(sampled_current_rss_max_between=lambda _begin, _end: 4096)

    measured = runner._measurements(raw, launch, monitor, failures)

    assert measured[0].primary_failure is runner.FailureClassification.BUDGET_EXHAUSTION
    assert failures == [
        {
            "boundary": "derived-from-governor-stop:game-time-limit",
            "classification": "budget exhaustion",
            "game_id": "game-a",
        }
    ]

    launch["tournament_receipt"]["receipt"]["games"][0]["actions_authorized"] = 3
    with pytest.raises(EvaluationError, match="actions disagree"):
        runner._measurements(raw, launch, monitor, [])


def test_collector_wrapper_binds_policy_hash_and_official_methods(tmp_path: Path) -> None:
    policy = tmp_path / "my_agent.py"
    policy.write_text("class MyAgent:\n    pass\n", encoding="utf-8")

    source = runner._collector_source(policy).decode("utf-8")

    assert runner.sha256_file(policy) in source
    assert "def choose_action(" in source
    assert "def is_done(" in source
    assert "persist_collected_scorecard" in source


def test_missing_required_surface_is_blocked_before_consumption(tmp_path: Path) -> None:
    manifest = tmp_path / "docs" / "evaluation" / MANIFEST.name
    manifest.parent.mkdir(parents=True)
    shutil.copyfile(MANIFEST, manifest)
    roles = sorted(runner.ARTIFACT_ROLES)
    gates = sorted(runner.GATE_ROLES)
    plan_path = tmp_path / "run-plan.json"
    plan_path.write_text(
        json.dumps(
            {
                "artifacts": {role: f"artifacts/inputs/{role}" for role in roles},
                "assets": {},
                "framework_root": "missing-framework",
                "gateway_host": "127.0.0.1",
                "gateway_port": 8001,
                "gates": {role: f"artifacts/gates/{role}.json" for role in gates},
                "manifest": str(manifest.relative_to(tmp_path)),
                "production_agent": "missing-agent.py",
                "schema": runner.RUN_PLAN_SCHEMA,
                "seed": 0,
                "submission_output": "artifacts/runtime/submission.parquet",
            }
        ),
        encoding="utf-8",
    )

    outcome = runner.execute(tmp_path, plan_path)

    state = tmp_path / runner.CANONICAL_STATE_RELATIVE
    assert outcome.status == "BLOCKED_EXTERNAL"
    assert outcome.receipt["environment_make_interactions"] == 0
    assert outcome.receipt["rerun_authorized"] is True
    assert not (state / "holdout-consumed.json").exists()
    assert len(list((state / "blockers").glob("*.json"))) == 1


def test_gateway_unavailability_is_external_but_malformed_surface_is_preflight_failure() -> None:
    unavailable = ExternalSurfaceUnavailableError("gateway unavailable")
    malformed = PackagingError("gateway returned invalid JSON")

    assert runner._pre_consumption_status(unavailable, stale_lock=False) == "BLOCKED_EXTERNAL"
    assert runner._pre_consumption_status(malformed, stale_lock=False) == "FAILED_PREFLIGHT"
    assert runner._pre_consumption_status(unavailable, stale_lock=True) == "BLOCKED_RECOVERY"
