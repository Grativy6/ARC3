from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from arc3.ablations import (
    DEFAULT_PROTOCOL_PATH,
    PROTOCOL_SCHEMA,
    AblationId,
    AblationProtocol,
    ablation_specs,
    features_for_ablation,
    load_protocol_manifest,
)
from arc3.adapters import GridFrame, Observation
from arc3.adapters.synthetic import SYNTHETIC_GAME_ID, SyntheticAdapter
from arc3.config import ARC3Config, BudgetConfig
from arc3.errors import CompetitionIntegrityError, PolicyError
from arc3.policy import ARC3Controller, ControllerPreset, RunContext, preset_features
from arc3.types import ActionName, EnvironmentMode, GameId, GameStateName


def _context(
    tmp_path: Path,
    *,
    label: str,
    max_coordinate_candidates: int = 24,
) -> RunContext:
    return RunContext(
        run_id=f"run-{label}",
        episode_id=f"episode-{label}",
        game_id=SYNTHETIC_GAME_ID,
        trace_root=tmp_path / label / "trace",
        checkpoint_root=tmp_path / label / "checkpoint",
        config=ARC3Config(
            mode=EnvironmentMode.SYNTHETIC,
            seed=37,
            profile=f"ablation-test-{label}",
            budgets=BudgetConfig(
                max_actions=16,
                max_coordinate_candidates=max_coordinate_candidates,
                max_search_nodes=2_048,
            ),
        ),
        git_commit="ablation-test",
    )


def test_a1_through_a10_disable_exactly_one_full_feature() -> None:
    specs = ablation_specs()
    assert tuple(spec.ablation_id for spec in specs) == tuple(AblationId)
    assert len({spec.disabled_feature for spec in specs}) == 10
    full = preset_features(ControllerPreset.FULL)
    original = full.to_dict()

    for spec in specs:
        ablated = features_for_ablation(spec.ablation_id).to_dict()
        differences = {key for key in original if original[key] != ablated[key]}
        assert differences == {spec.disabled_feature}
        assert original[spec.disabled_feature] is True
        assert ablated[spec.disabled_feature] is False

    assert preset_features(ControllerPreset.FULL).to_dict() == original
    assert preset_features(ControllerPreset.COMPETITION) == full


def test_frozen_protocol_manifest_exactly_matches_typed_contract(tmp_path: Path) -> None:
    protocol, ablations, digest = load_protocol_manifest()
    assert protocol == AblationProtocol()
    assert ablations == tuple(AblationId)
    assert digest == "sha256:" + hashlib.sha256(DEFAULT_PROTOCOL_PATH.read_bytes()).hexdigest()
    raw = json.loads(DEFAULT_PROTOCOL_PATH.read_text(encoding="utf-8"))
    assert raw["schema"] == PROTOCOL_SCHEMA
    assert raw["protocol"] == protocol.to_dict()
    assert [item["ablation_id"] for item in raw["ablations"]] == [
        identifier.value for identifier in AblationId
    ]

    raw["protocol"]["action_budget"] = protocol.action_budget + 1
    malformed = tmp_path / "changed-protocol.json"
    malformed.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ValueError, match="does not exactly match"):
        load_protocol_manifest(malformed)


def test_competition_preset_rejects_experimental_feature_override() -> None:
    with pytest.raises(CompetitionIntegrityError, match="experimental feature overrides"):
        ARC3Controller(
            ControllerPreset.COMPETITION,
            features=features_for_ablation(AblationId.A10),
        )


def test_ungated_ablation_is_explicit_in_model_receipts(tmp_path: Path) -> None:
    session = SyntheticAdapter(seed=37, size=8, max_steps=32).open(SYNTHETIC_GAME_ID)
    controller = ARC3Controller(
        ControllerPreset.FULL,
        features=features_for_ablation(AblationId.A3),
    )
    controller.reset(_context(tmp_path, label="ungated"))
    controller.observe(session.observation)

    assert controller.snapshot.active_world_model_ids
    events = controller.journal.verify_manifest()
    retrodictions = [
        event for event in events if event.event_type == "model.retrodiction_completed"
    ]
    promotions = [event for event in events if event.event_type == "model.rule_promoted"]
    assert retrodictions
    assert {event.payload["status"] for event in retrodictions} == {"ungated_ablation"}
    assert promotions
    assert {event.payload["promotion_basis"] for event in promotions} == {
        "ungated Stage 14 ablation"
    }


def test_object_tracking_ablation_preserves_raw_delta_but_omits_correspondence(
    tmp_path: Path,
) -> None:
    session = SyntheticAdapter(seed=37, size=8, max_steps=32).open(SYNTHETIC_GAME_ID)
    controller = ARC3Controller(
        ControllerPreset.FULL,
        features=features_for_ablation(AblationId.A8),
    )
    controller.reset(_context(tmp_path, label="no-tracking"))
    controller.observe(session.observation)
    decision = controller.choose_action()
    controller.apply_consequence(session.step(decision.action))

    event_types = [event.event_type for event in controller.journal.verify_manifest()]
    assert "observation.received" in event_types
    assert "observation.delta_measured" in event_types
    assert "perception.object_correspondence_proposed" not in event_types


def test_coordinate_salience_ablation_uses_seeded_uniform_candidates(tmp_path: Path) -> None:
    observation = Observation(
        game_id=GameId(SYNTHETIC_GAME_ID),
        frames=(
            GridFrame.from_rows(
                tuple(
                    tuple(1 if (x, y) == (1, 1) else 2 if (x, y) == (6, 6) else 0 for x in range(8))
                    for y in range(8)
                )
            ),
        ),
        state=GameStateName.NOT_FINISHED,
        levels_completed=0,
        win_levels=1,
        available_actions=(ActionName.ACTION6,),
    )
    salient = ARC3Controller(ControllerPreset.FULL)
    salient.reset(_context(tmp_path, label="salient", max_coordinate_candidates=2))
    salient.observe(observation)
    uniform = ARC3Controller(
        ControllerPreset.FULL,
        features=features_for_ablation(AblationId.A6),
    )
    uniform.reset(_context(tmp_path, label="uniform", max_coordinate_candidates=2))
    uniform.observe(observation)
    uniform_repeat = ARC3Controller(
        ControllerPreset.FULL,
        features=features_for_ablation(AblationId.A6),
    )
    uniform_repeat.reset(_context(tmp_path, label="uniform-repeat", max_coordinate_candidates=2))
    uniform_repeat.observe(observation)

    salient_actions = salient._legal_actions(observation, salient._latest_view)
    uniform_actions = uniform._legal_actions(observation, uniform._latest_view)
    repeated_actions = uniform_repeat._legal_actions(observation, uniform_repeat._latest_view)
    assert uniform_actions == repeated_actions
    assert uniform_actions != salient_actions
    assert len(uniform_actions) == len(salient_actions) == 2


def test_checkpoint_restore_rejects_feature_identity_mismatch(tmp_path: Path) -> None:
    features = features_for_ablation(AblationId.A3)
    context = _context(tmp_path, label="feature-identity")
    session = SyntheticAdapter(seed=37, size=8, max_steps=32).open(SYNTHETIC_GAME_ID)
    controller = ARC3Controller(ControllerPreset.FULL, features=features)
    controller.reset(context)
    controller.observe(session.observation)
    controller.checkpoint()
    controller.close()
    checkpoint_path = context.checkpoint_root / "latest.json"

    with pytest.raises(PolicyError, match="feature identity"):
        ARC3Controller.restore(
            context,
            preset=ControllerPreset.FULL,
            checkpoint_path=checkpoint_path,
        )

    restored = ARC3Controller.restore(
        context,
        preset=ControllerPreset.FULL,
        checkpoint_path=checkpoint_path,
        features=features,
    )
    assert restored.features == features
