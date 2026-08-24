"""Deterministic, dependency-free ARC3 runtime configuration."""

from __future__ import annotations

import hashlib
import json
import math
import os
from collections.abc import Mapping
from dataclasses import asdict, dataclass, is_dataclass
from enum import Enum
from pathlib import Path
from typing import cast

from arc3.errors import CompetitionIntegrityError, ConfigurationError
from arc3.types import ConfigHash, EnvironmentMode, ExecutionMode, JSONValue

CONFIG_SCHEMA = "arc3.config.v0.2"


@dataclass(frozen=True, slots=True)
class BudgetConfig:
    """Explicit outer bounds for environment interaction and local search."""

    max_actions: int = 100
    max_resets: int = 8
    decision_seconds: float = 5.0
    wall_clock_seconds: float = 900.0
    memory_megabytes: int = 2048
    max_coordinate_candidates: int = 128
    max_search_nodes: int = 10_000
    max_search_depth: int = 32
    max_trace_bytes: int = 256 * 1024 * 1024

    def __post_init__(self) -> None:
        integer_fields = {
            "max_actions": self.max_actions,
            "max_resets": self.max_resets,
            "memory_megabytes": self.memory_megabytes,
            "max_coordinate_candidates": self.max_coordinate_candidates,
            "max_search_nodes": self.max_search_nodes,
            "max_search_depth": self.max_search_depth,
            "max_trace_bytes": self.max_trace_bytes,
        }
        for name, integer_value in integer_fields.items():
            if isinstance(integer_value, bool) or integer_value <= 0:
                raise ConfigurationError(f"{name} must be a positive integer")
        for name, float_value in {
            "decision_seconds": self.decision_seconds,
            "wall_clock_seconds": self.wall_clock_seconds,
        }.items():
            if isinstance(float_value, bool) or not math.isfinite(float_value) or float_value <= 0:
                raise ConfigurationError(f"{name} must be a finite positive number")


@dataclass(frozen=True, slots=True)
class RuntimePolicyConfig:
    """Execution-cost policy kept separate from persistent research mechanisms."""

    allocator_tracing_enabled: bool = True
    automatic_per_action_checkpoints: bool = True
    sparse_checkpoint_interval_actions: int = 1
    compact_trace_capacity: int = 0

    def __post_init__(self) -> None:
        for name, value in (
            ("allocator_tracing_enabled", self.allocator_tracing_enabled),
            ("automatic_per_action_checkpoints", self.automatic_per_action_checkpoints),
        ):
            if not isinstance(value, bool):
                raise ConfigurationError(f"{name} must be a boolean")
        if (
            isinstance(self.sparse_checkpoint_interval_actions, bool)
            or self.sparse_checkpoint_interval_actions <= 0
        ):
            raise ConfigurationError("sparse_checkpoint_interval_actions must be positive")
        if isinstance(self.compact_trace_capacity, bool) or self.compact_trace_capacity < 0:
            raise ConfigurationError("compact_trace_capacity must be non-negative")

    @classmethod
    def research_unbounded(cls) -> RuntimePolicyConfig:
        """Preserve the historical research defaults exactly."""

        return cls()

    @classmethod
    def competition_bounded(cls) -> RuntimePolicyConfig:
        """Return the frozen low-overhead competition persistence policy."""

        return cls(
            allocator_tracing_enabled=False,
            automatic_per_action_checkpoints=False,
            sparse_checkpoint_interval_actions=16,
            compact_trace_capacity=512,
        )


@dataclass(frozen=True, slots=True)
class ARC3Config:
    """Configuration whose full canonical form is suitable for run identity."""

    mode: EnvironmentMode = EnvironmentMode.SYNTHETIC
    execution_mode: ExecutionMode = ExecutionMode.RESEARCH_UNBOUNDED
    seed: int = 0
    network_enabled: bool = False
    profile: str = "foundation"
    log_level: str = "INFO"
    artifact_root: str = "artifacts"
    trace_root: str = "recordings"
    budgets: BudgetConfig = BudgetConfig()
    runtime_policy: RuntimePolicyConfig = RuntimePolicyConfig()
    schema: str = CONFIG_SCHEMA

    def __post_init__(self) -> None:
        raw_mode: object = self.mode
        if not isinstance(raw_mode, EnvironmentMode):
            try:
                object.__setattr__(self, "mode", EnvironmentMode(str(raw_mode)))
            except ValueError as error:
                raise ConfigurationError(f"unknown environment mode: {raw_mode!r}") from error
        raw_execution_mode: object = self.execution_mode
        if not isinstance(raw_execution_mode, ExecutionMode):
            try:
                object.__setattr__(self, "execution_mode", ExecutionMode(str(raw_execution_mode)))
            except ValueError as error:
                raise ConfigurationError(
                    f"unknown execution mode: {raw_execution_mode!r}"
                ) from error
        if isinstance(self.seed, bool) or not -(2**63) <= self.seed < 2**63:
            raise ConfigurationError("seed must be a signed 64-bit integer")
        if not isinstance(self.network_enabled, bool):
            raise ConfigurationError("network_enabled must be a boolean")
        if self.schema != CONFIG_SCHEMA:
            raise ConfigurationError(
                f"unsupported config schema {self.schema!r}; expected {CONFIG_SCHEMA!r}"
            )
        if not self.profile.strip():
            raise ConfigurationError("profile must not be empty")
        normalized_level = self.log_level.upper()
        if normalized_level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ConfigurationError(f"unsupported log level: {self.log_level!r}")
        object.__setattr__(self, "log_level", normalized_level)
        if self.mode is EnvironmentMode.COMPETITION and self.network_enabled:
            raise CompetitionIntegrityError(
                "competition mode forbids network access; set network_enabled=false"
            )
        expected_policy = (
            RuntimePolicyConfig.competition_bounded()
            if self.execution_mode is ExecutionMode.COMPETITION_BOUNDED
            else RuntimePolicyConfig.research_unbounded()
        )
        if self.runtime_policy != expected_policy:
            raise ConfigurationError(
                f"{self.execution_mode.value} requires its frozen runtime policy"
            )
        if (
            self.execution_mode is ExecutionMode.COMPETITION_BOUNDED
            and self.mode is not EnvironmentMode.COMPETITION
        ):
            raise CompetitionIntegrityError(
                "COMPETITION_BOUNDED requires the competition environment surface"
            )
        if not self.artifact_root.strip() or not self.trace_root.strip():
            raise ConfigurationError("artifact and trace roots must not be empty")

    @classmethod
    def for_mode(
        cls,
        mode: EnvironmentMode | str,
        *,
        seed: int = 0,
        network_enabled: bool | None = None,
        execution_mode: ExecutionMode | str | None = None,
        profile: str = "foundation",
        log_level: str = "INFO",
        budgets: BudgetConfig | None = None,
    ) -> ARC3Config:
        """Build a mode preset, resolving network behavior explicitly."""

        try:
            parsed_mode = mode if isinstance(mode, EnvironmentMode) else EnvironmentMode(mode)
        except ValueError as error:
            choices = ", ".join(item.value for item in EnvironmentMode)
            raise ConfigurationError(f"unknown mode {mode!r}; expected one of {choices}") from error
        default_network = parsed_mode is EnvironmentMode.ONLINE
        resolved_network = default_network if network_enabled is None else network_enabled
        if execution_mode is None:
            resolved_execution_mode = (
                ExecutionMode.COMPETITION_BOUNDED
                if parsed_mode is EnvironmentMode.COMPETITION
                else ExecutionMode.RESEARCH_UNBOUNDED
            )
        else:
            try:
                resolved_execution_mode = (
                    execution_mode
                    if isinstance(execution_mode, ExecutionMode)
                    else ExecutionMode(execution_mode)
                )
            except ValueError as error:
                choices = ", ".join(item.value for item in ExecutionMode)
                raise ConfigurationError(
                    f"unknown execution mode {execution_mode!r}; expected one of {choices}"
                ) from error
        runtime_policy = (
            RuntimePolicyConfig.competition_bounded()
            if resolved_execution_mode is ExecutionMode.COMPETITION_BOUNDED
            else RuntimePolicyConfig.research_unbounded()
        )
        return cls(
            mode=parsed_mode,
            execution_mode=resolved_execution_mode,
            seed=seed,
            network_enabled=resolved_network,
            profile=profile,
            log_level=log_level,
            budgets=budgets or BudgetConfig(),
            runtime_policy=runtime_policy,
        )

    def to_dict(self) -> dict[str, JSONValue]:
        """Return a JSON-compatible value with enums converted to their values."""

        normalized = _normalize_json(asdict(self))
        if not isinstance(normalized, dict):  # pragma: no cover - dataclass invariant
            raise ConfigurationError("config normalization did not produce an object")
        return normalized

    @property
    def hash(self) -> ConfigHash:
        """Canonical SHA-256 identity, including the ``sha256:`` algorithm tag."""

        return config_hash(self)


def default_config(
    mode: EnvironmentMode | str = EnvironmentMode.SYNTHETIC,
    *,
    seed: int = 0,
) -> ARC3Config:
    """Return a deterministic mode preset."""

    return ARC3Config.for_mode(mode, seed=seed)


def _normalize_json(value: object) -> JSONValue:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ConfigurationError("configuration cannot contain NaN or infinity")
        return value
    if isinstance(value, Enum):
        return _normalize_json(value.value)
    if isinstance(value, Path):
        return value.as_posix()
    if is_dataclass(value) and not isinstance(value, type):
        return _normalize_json(asdict(value))
    if isinstance(value, Mapping):
        normalized: dict[str, JSONValue] = {}
        for raw_key, item in value.items():
            if not isinstance(raw_key, str):
                raise ConfigurationError("configuration object keys must be strings")
            normalized[raw_key] = _normalize_json(item)
        return normalized
    if isinstance(value, (list, tuple)):
        return [_normalize_json(item) for item in value]
    raise ConfigurationError(
        f"configuration value of type {type(value).__name__} is not canonicalizable"
    )


def canonical_config_json(config: ARC3Config | Mapping[str, object]) -> str:
    """Serialize configuration using the trace contract's canonical JSON form."""

    value: object = config.to_dict() if isinstance(config, ARC3Config) else config
    normalized = _normalize_json(value)
    if not isinstance(normalized, dict):
        raise ConfigurationError("top-level configuration must be an object")
    return json.dumps(
        normalized,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def config_hash(config: ARC3Config | Mapping[str, object]) -> ConfigHash:
    """Return the canonical configuration's tagged SHA-256 hash."""

    digest = hashlib.sha256(canonical_config_json(config).encode("utf-8")).hexdigest()
    return ConfigHash(f"sha256:{digest}")


def derive_seed(root_seed: int, component: str, *, ordinal: int = 0) -> int:
    """Derive a stable unsigned 64-bit component seed without Python ``hash``."""

    if isinstance(root_seed, bool) or not -(2**63) <= root_seed < 2**63:
        raise ConfigurationError("root_seed must be a signed 64-bit integer")
    if isinstance(ordinal, bool) or ordinal < 0:
        raise ConfigurationError("ordinal must be a non-negative integer")
    if not component:
        raise ConfigurationError("component must not be empty")
    material = f"arc3.seed.v1\0{root_seed}\0{component}\0{ordinal}".encode()
    return int.from_bytes(hashlib.sha256(material).digest()[:8], "big", signed=False)


def _parse_bool(value: object, *, name: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    raise ConfigurationError(f"{name} must be a boolean")


def _parse_int(value: object, *, name: str) -> int:
    if isinstance(value, bool):
        raise ConfigurationError(f"{name} must be an integer")
    try:
        return int(cast(str | int, value))
    except (TypeError, ValueError) as error:
        raise ConfigurationError(f"{name} must be an integer") from error


def config_from_mapping(data: Mapping[str, object]) -> ARC3Config:
    """Validate a plain mapping without silently accepting misspelled keys."""

    allowed = {
        "schema",
        "mode",
        "execution_mode",
        "seed",
        "network_enabled",
        "profile",
        "log_level",
        "artifact_root",
        "trace_root",
        "budgets",
        "runtime_policy",
    }
    unknown = sorted(set(data) - allowed)
    if unknown:
        raise ConfigurationError(f"unknown configuration keys: {', '.join(unknown)}")
    raw_mode = data.get("mode", EnvironmentMode.SYNTHETIC.value)
    try:
        mode = EnvironmentMode(str(raw_mode))
    except ValueError as error:
        raise ConfigurationError(f"unknown environment mode: {raw_mode!r}") from error
    raw_execution_mode = data.get("execution_mode")
    if raw_execution_mode is None:
        execution_mode = (
            ExecutionMode.COMPETITION_BOUNDED
            if mode is EnvironmentMode.COMPETITION
            else ExecutionMode.RESEARCH_UNBOUNDED
        )
    else:
        try:
            execution_mode = ExecutionMode(str(raw_execution_mode))
        except ValueError as error:
            raise ConfigurationError(
                f"unknown execution mode: {raw_execution_mode!r}"
            ) from error

    raw_budgets = data.get("budgets", {})
    if isinstance(raw_budgets, BudgetConfig):
        budgets = raw_budgets
    elif isinstance(raw_budgets, Mapping):
        budget_allowed = set(BudgetConfig.__dataclass_fields__)
        budget_unknown = sorted(set(str(key) for key in raw_budgets) - budget_allowed)
        if budget_unknown:
            raise ConfigurationError(f"unknown budget keys: {', '.join(budget_unknown)}")
        try:
            budgets = BudgetConfig(**dict(raw_budgets))
        except TypeError as error:
            raise ConfigurationError(f"invalid budget configuration: {error}") from error
    else:
        raise ConfigurationError("budgets must be an object")

    raw_runtime_policy = data.get("runtime_policy")
    if raw_runtime_policy is None:
        runtime_policy = (
            RuntimePolicyConfig.competition_bounded()
            if execution_mode is ExecutionMode.COMPETITION_BOUNDED
            else RuntimePolicyConfig.research_unbounded()
        )
    elif isinstance(raw_runtime_policy, RuntimePolicyConfig):
        runtime_policy = raw_runtime_policy
    elif isinstance(raw_runtime_policy, Mapping):
        policy_allowed = set(RuntimePolicyConfig.__dataclass_fields__)
        policy_unknown = sorted(set(str(key) for key in raw_runtime_policy) - policy_allowed)
        if policy_unknown:
            raise ConfigurationError(f"unknown runtime policy keys: {', '.join(policy_unknown)}")
        try:
            runtime_policy = RuntimePolicyConfig(**dict(raw_runtime_policy))
        except TypeError as error:
            raise ConfigurationError(f"invalid runtime policy configuration: {error}") from error
    else:
        raise ConfigurationError("runtime_policy must be an object")

    raw_network = data.get("network_enabled")
    network_enabled = (
        mode is EnvironmentMode.ONLINE
        if raw_network is None
        else _parse_bool(raw_network, name="network_enabled")
    )
    return ARC3Config(
        mode=mode,
        execution_mode=execution_mode,
        seed=_parse_int(data.get("seed", 0), name="seed"),
        network_enabled=network_enabled,
        profile=str(data.get("profile", "foundation")),
        log_level=str(data.get("log_level", "INFO")),
        artifact_root=str(data.get("artifact_root", "artifacts")),
        trace_root=str(data.get("trace_root", "recordings")),
        budgets=budgets,
        runtime_policy=runtime_policy,
        schema=str(data.get("schema", CONFIG_SCHEMA)),
    )


def load_config(
    path: str | Path | None = None,
    *,
    environ: Mapping[str, str] | None = None,
) -> ARC3Config:
    """Load optional JSON and explicit ``ARC3_*`` overrides.

    No credential-bearing environment variables are accepted by this layer.
    """

    data: dict[str, object] = {}
    if path is not None:
        config_path = Path(path)
        try:
            loaded = json.loads(config_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ConfigurationError(f"cannot load configuration {config_path}: {error}") from error
        if not isinstance(loaded, dict):
            raise ConfigurationError("configuration file must contain a JSON object")
        data.update(cast(dict[str, object], loaded))

    source = os.environ if environ is None else environ
    overrides: dict[str, object] = {}
    environment_keys = {
        "ARC3_MODE": "mode",
        "ARC3_EXECUTION_MODE": "execution_mode",
        "ARC3_SEED": "seed",
        "ARC3_NETWORK_ENABLED": "network_enabled",
        "ARC3_PROFILE": "profile",
        "ARC3_LOG_LEVEL": "log_level",
        "ARC3_ARTIFACT_ROOT": "artifact_root",
        "ARC3_TRACE_ROOT": "trace_root",
    }
    for environment_key, config_key in environment_keys.items():
        if environment_key in source:
            overrides[config_key] = source[environment_key]
    data.update(overrides)
    return config_from_mapping(data)


# Short aliases retained for CLI and downstream code readability.
canonical_json = canonical_config_json
hash_config = config_hash
