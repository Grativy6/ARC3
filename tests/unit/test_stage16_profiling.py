"""Focused contracts for Stage 16 profiling values and transformed fixtures."""

from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path

import pytest

from arc3.competition_runtime import FROZEN_COMPETITION_RUNTIME, load_competition_runtime
from arc3.profiling import (
    ManyComponentStressSession,
    RobustnessVariant,
    RuntimeProfileConfig,
    TransformedSyntheticSession,
    process_memory_sample,
)
from arc3.profiling.regression import validate_stage13_regression_binding
from arc3.types import ActionName, ActionRequest

ROOT = Path(__file__).resolve().parents[2]


def test_runtime_profile_config_maps_every_declared_controller_budget() -> None:
    config = RuntimeProfileConfig(
        seed=25,
        frame_size=32,
        max_actions=64,
        max_resets=5,
        restart_every=8,
        decision_seconds=3.0,
        wall_clock_seconds=120.0,
        memory_megabytes=1024,
        max_trace_bytes=64 * 1024 * 1024,
        max_checkpoint_bytes=32 * 1024 * 1024,
        max_coordinate_candidates=32,
        max_search_nodes=4096,
        max_search_depth=48,
    )
    budgets = config.budgets()
    assert budgets.max_actions == 64
    assert budgets.max_resets == 5
    assert budgets.decision_seconds == 3.0
    assert budgets.wall_clock_seconds == 120.0
    assert budgets.memory_megabytes == 1024
    assert budgets.max_trace_bytes == 64 * 1024 * 1024
    assert budgets.max_coordinate_candidates == 32
    assert budgets.max_search_nodes == 4096
    assert budgets.max_search_depth == 48
    assert config.max_checkpoint_bytes == 32 * 1024 * 1024


def test_frozen_competition_runtime_is_shared_and_self_verified() -> None:
    loaded = load_competition_runtime()
    assert loaded == FROZEN_COMPETITION_RUNTIME
    assert loaded.max_actions == 80
    assert loaded.max_resets == 8
    assert loaded.decision_seconds == 10.0
    assert loaded.per_game_wall_clock_seconds == 240.0
    assert loaded.per_game_wall_clock_seconds * loaded.official_evaluation_games == 26_400
    assert loaded.reserved_non_game_seconds == 6_000
    governor = loaded.governor_config(10)
    assert governor.maximum_resets_per_game == loaded.max_resets == 8
    assert governor.maximum_total_resets == 80
    assert RuntimeProfileConfig().budgets() == loaded.budgets()
    assert RuntimeProfileConfig().restart_every == 0


def test_kaggle_metadata_identity_is_cross_bound_across_runtime_and_source_locks() -> None:
    runtime = json.loads(
        (ROOT / "src" / "arc3" / "competition-runtime.v0.2.json").read_text(encoding="utf-8")
    )
    upstream = json.loads((ROOT / "upstream.lock.json").read_text(encoding="utf-8"))
    evidence = json.loads(
        (ROOT / "docs" / "evidence" / "002-00-official-source-identities.json").read_text(
            encoding="utf-8"
        )
    )
    locked = upstream["build_002_refresh"]["kaggle_competition_metadata"]
    observed = evidence["kaggle_competition_snapshot"]
    raw_evidence = json.loads(
        (
            ROOT
            / "docs"
            / "evidence"
            / "source"
            / "002-kaggle-competition-metadata-response.v0.1.json"
        ).read_text(encoding="utf-8")
    )
    raw_body = base64.b64decode(raw_evidence["body_base64"], validate=True)
    assert runtime["kaggle_metadata_response_sha256"] == locked["response_sha256"]
    assert runtime["kaggle_metadata_response_sha256"] == ("sha256:" + observed["response_sha256"])
    assert runtime["kaggle_metadata_accessed_at"] == locked["accessed_at"]
    assert runtime["kaggle_metadata_accessed_at"] == observed["accessed_at"]
    assert runtime["kaggle_competition_id"] == locked["competition_id"]
    assert runtime["kaggle_competition_id"] == observed["competition_id"]
    assert len(raw_body) == raw_evidence["decoded_size_bytes"] == observed["response_size_bytes"]
    assert "sha256:" + hashlib.sha256(raw_body).hexdigest() == raw_evidence["decoded_sha256"]
    assert raw_evidence["decoded_sha256"] == runtime["kaggle_metadata_response_sha256"]
    assert json.loads(raw_body)["id"] == runtime["kaggle_competition_id"]


def test_pinned_agents_runtime_hashes_use_exact_git_blob_bytes() -> None:
    upstream = json.loads((ROOT / "upstream.lock.json").read_text(encoding="utf-8"))
    fixture = json.loads(
        (ROOT / "tests" / "fixtures" / "pinned-agents-4743e7d" / "SOURCE_IDENTITY.json").read_text(
            encoding="utf-8"
        )
    )
    locked = upstream["build_002_refresh"]["pinned_agents_git_blob_sha256"]
    assert locked == {
        path: "sha256:" + record["sha256"] for path, record in fixture["files"].items()
    }


@pytest.mark.parametrize(
    ("field", "invalid"),
    (
        ("max_actions", True),
        ("decision_seconds", "10.0"),
        ("execution_backend", 7),
    ),
)
def test_frozen_competition_runtime_rejects_rehashed_invalid_field_types(
    tmp_path: Path,
    field: str,
    invalid: object,
) -> None:
    source = ROOT / "src" / "arc3" / "competition-runtime.v0.2.json"
    raw = json.loads(source.read_text(encoding="utf-8"))
    raw[field] = invalid
    body = {key: value for key, value in raw.items() if key != "configuration_sha256"}
    canonical = json.dumps(
        body,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    raw["configuration_sha256"] = f"sha256:{hashlib.sha256(canonical).hexdigest()}"
    candidate = tmp_path / "runtime.json"
    candidate.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ValueError):
        load_competition_runtime(candidate)


def test_stage13_regression_binding_verifies_exact_evidence_and_threshold() -> None:
    binding = validate_stage13_regression_binding(ROOT)
    assert binding["verified"] is True
    assert binding["evidence_sha256"] == (
        "sha256:ab354deec3ef4f7a84d285a8e7603dbe357afcf6c6bbff7862fe94979b94780e"
    )
    assert binding["performance_threshold_sha256"] == (
        "sha256:3d3b2638583e58f93ef6fa85420020380809bd7d4618a2485de65a8d0a784f2d"
    )


@pytest.mark.parametrize(
    "overrides",
    (
        {"frame_size": 65},
        {"max_actions": 0},
        {"restart_every": -1},
        {"restart_every": 1.5},
        {"seed": "7"},
        {"decision_seconds": float("inf")},
        {"fixture": "unknown"},
        {"frame_size": 8, "component_count": 17},
    ),
)
def test_runtime_profile_config_rejects_unbounded_values(
    overrides: dict[str, object],
) -> None:
    with pytest.raises(ValueError):
        RuntimeProfileConfig(**overrides)  # type: ignore[arg-type]


def test_action_remap_preserves_controller_visible_returned_action() -> None:
    session = TransformedSyntheticSession(
        seed=7,
        size=8,
        max_steps=32,
        variant=RobustnessVariant.ACTION_REMAP,
    )
    requested = ActionRequest(ActionName.ACTION3)
    before = session.observation.frames[-1]
    returned = session.step(requested)
    assert returned.returned_action == requested
    assert returned.frames[-1].digest != before.digest


def test_palette_translation_and_distractor_are_observation_only_transformations() -> None:
    palette = TransformedSyntheticSession(
        seed=7,
        size=8,
        max_steps=32,
        variant=RobustnessVariant.PALETTE,
    ).observation.frames[-1]
    translated = TransformedSyntheticSession(
        seed=7,
        size=8,
        max_steps=32,
        variant=RobustnessVariant.TRANSLATION,
    ).observation.frames[-1]
    distractor = TransformedSyntheticSession(
        seed=7,
        size=8,
        max_steps=32,
        variant=RobustnessVariant.DISTRACTOR,
    ).observation.frames[-1]
    assert {7, 12}.issubset(palette.palette)
    assert (translated.width, translated.height) == (10, 11)
    assert {3, 4}.issubset(distractor.palette)


def test_process_memory_sample_states_its_kernel_measurement_scope() -> None:
    sample = process_memory_sample()
    assert isinstance(sample["measurement_source"], str)
    assert "peak_rss_bytes" in sample
    assert "current_rss_bytes" in sample


def test_many_component_stress_fixture_forces_declared_action_length() -> None:
    session = ManyComponentStressSession(size=8, component_count=16)
    assert sum(value != 0 for row in session.observation.frames[-1].cells for value in row) == 16
    for index in range(12):
        action = ActionRequest((ActionName.ACTION1, ActionName.ACTION2)[index % 2])
        observation = session.step(action)
        assert observation.state.value == "NOT_FINISHED"
        assert observation.returned_action == action
    score = session.close()
    assert score.total_actions == 12
    assert score.runs[0].completed is False


def test_default_component_stress_fixture_has_a_generic_navigation_lane() -> None:
    session = ManyComponentStressSession(size=32, component_count=64)
    initial = session.observation.frames[-1].cells
    assert sum(value != 0 for row in initial for value in row) == 64
    assert initial[2][2] == 10
    assert initial[2][6] == 11

    for _index in range(3):
        session.step(ActionRequest(ActionName.ACTION4))
    adjacent = session.observation.frames[-1].cells
    assert adjacent[2][5] == 10
    assert adjacent[2][6] == 11

    blocked = session.step(ActionRequest(ActionName.ACTION4)).frames[-1].cells
    assert blocked == adjacent
    assert sum(value != 0 for row in blocked for value in row) == 64
