"""Tests for deterministic configuration identity and validation."""

from __future__ import annotations

import hashlib

import pytest

from arc3.config import (
    ARC3Config,
    BudgetConfig,
    canonical_config_json,
    config_from_mapping,
    config_hash,
    default_config,
    derive_seed,
    load_config,
)
from arc3.errors import ConfigurationError
from arc3.types import EnvironmentMode

EXPECTED_DEFAULT_JSON = (
    '{"artifact_root":"artifacts","budgets":{"decision_seconds":5.0,'
    '"max_actions":100,"max_coordinate_candidates":128,"max_resets":8,'
    '"max_search_depth":32,"max_search_nodes":10000,"max_trace_bytes":268435456,'
    '"memory_megabytes":2048,"wall_clock_seconds":900.0},'
    '"execution_mode":"RESEARCH_UNBOUNDED","log_level":"INFO",'
    '"mode":"synthetic","network_enabled":false,"profile":"foundation",'
    '"runtime_policy":{"allocator_tracing_enabled":true,'
    '"automatic_per_action_checkpoints":true,"compact_trace_capacity":0,'
    '"sparse_checkpoint_interval_actions":1},"schema":"arc3.config.v0.2",'
    '"seed":0,"trace_root":"recordings"}'
)


def test_default_configuration_has_stable_canonical_identity() -> None:
    config = default_config()

    assert canonical_config_json(config) == EXPECTED_DEFAULT_JSON
    expected_digest = hashlib.sha256(EXPECTED_DEFAULT_JSON.encode()).hexdigest()
    assert str(config_hash(config)) == f"sha256:{expected_digest}"
    assert config.hash == config_hash(config)


def test_mapping_order_does_not_change_config_hash() -> None:
    left = {"mode": "local", "seed": 9, "nested": {"b": 2, "a": 1}}
    right = {"nested": {"a": 1, "b": 2}, "seed": 9, "mode": "local"}

    assert canonical_config_json(left) == canonical_config_json(right)
    assert config_hash(left) == config_hash(right)


def test_seed_derivation_is_stable_and_namespaced() -> None:
    assert derive_seed(123, "planner") == 14_228_957_291_026_052_264
    assert derive_seed(-1, "planner", ordinal=2) == 2_400_027_736_534_655_516
    assert derive_seed(123, "planner") != derive_seed(123, "perception")
    assert derive_seed(123, "planner") != derive_seed(123, "planner", ordinal=1)


@pytest.mark.parametrize(
    ("root_seed", "component", "ordinal"),
    [(True, "planner", 0), (0, "", 0), (0, "planner", -1), (0, "planner", True)],
)
def test_seed_derivation_rejects_ambiguous_inputs(
    root_seed: int, component: str, ordinal: int
) -> None:
    with pytest.raises(ConfigurationError):
        derive_seed(root_seed, component, ordinal=ordinal)


def test_mode_presets_make_network_policy_explicit() -> None:
    assert ARC3Config.for_mode(EnvironmentMode.SYNTHETIC).network_enabled is False
    assert ARC3Config.for_mode(EnvironmentMode.LOCAL).network_enabled is False
    assert ARC3Config.for_mode(EnvironmentMode.ONLINE).network_enabled is True
    assert ARC3Config.for_mode(EnvironmentMode.COMPETITION).network_enabled is False


def test_environment_loading_uses_only_declared_arc3_overrides() -> None:
    config = load_config(
        environ={
            "ARC3_MODE": "local",
            "ARC3_SEED": "41",
            "ARC3_LOG_LEVEL": "warning",
            "ARC_API_KEY": "must-not-enter-config",
            "KAGGLE_KEY": "must-not-enter-config",
        }
    )

    assert config.mode is EnvironmentMode.LOCAL
    assert config.seed == 41
    assert config.log_level == "WARNING"
    serialized = canonical_config_json(config)
    assert "must-not-enter-config" not in serialized


def test_config_mapping_rejects_unknown_keys_and_invalid_budget() -> None:
    with pytest.raises(ConfigurationError, match="unknown configuration keys"):
        config_from_mapping({"netwrok_enabled": False})
    with pytest.raises(ConfigurationError, match="max_actions"):
        config_from_mapping({"budgets": {"max_actions": 0}})


@pytest.mark.parametrize("value", [0, -1, True])
def test_positive_budget_fields_are_enforced(value: int) -> None:
    with pytest.raises(ConfigurationError, match="max_actions"):
        BudgetConfig(max_actions=value)


def test_non_finite_values_are_never_canonicalized() -> None:
    with pytest.raises(ConfigurationError, match="NaN or infinity"):
        canonical_config_json({"decision_seconds": float("nan")})
