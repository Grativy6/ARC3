"""Immutable executable identities for Build 003 synthetic protocols."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ProtocolVersion(StrEnum):
    """Explicit CLI selectors for immutable curriculum protocols."""

    V0_1 = "v0.1"
    V0_2 = "v0.2"


@dataclass(frozen=True, slots=True)
class SourceIdentity:
    """Exact commit/tree pair required before importing a frozen baseline."""

    commit: str
    tree: str

    def __post_init__(self) -> None:
        for label, value in (("commit", self.commit), ("tree", self.tree)):
            if len(value) != 40 or any(character not in "0123456789abcdef" for character in value):
                raise ValueError(f"source {label} must be a lowercase 40-character Git object id")


@dataclass(frozen=True, slots=True)
class ProtocolBudgets:
    """Protocol-level bounds copied into each sequence receipt."""

    max_environment_actions: int
    max_environment_actions_per_level: int | None
    max_resets: int
    max_wall_clock_seconds: float
    max_peak_memory_bytes: int
    policy_cycle_seconds: float

    def __post_init__(self) -> None:
        integers = (
            self.max_environment_actions,
            self.max_resets,
            self.max_peak_memory_bytes,
        )
        if any(isinstance(value, bool) or value <= 0 for value in integers):
            raise ValueError("protocol integer budgets must be positive")
        if self.max_environment_actions_per_level is not None and (
            isinstance(self.max_environment_actions_per_level, bool)
            or self.max_environment_actions_per_level <= 0
        ):
            raise ValueError("per-level action budget must be positive when present")
        if self.max_wall_clock_seconds <= 0 or self.policy_cycle_seconds <= 0:
            raise ValueError("protocol time budgets must be positive")


@dataclass(frozen=True, slots=True)
class ProtocolDefinition:
    """Complete evaluator-side binding for one immutable protocol version."""

    version: ProtocolVersion
    protocol_id: str
    protocol_path: str
    manifest_path: str
    preregistration_path: str
    heldout_seed_domain: str
    heldout_seed_separator: str
    development_seed_domain: str | None
    development_seed_separator: str
    development_seed_values: tuple[int, ...]
    case_prefix: str
    baseline: SourceIdentity
    budgets: ProtocolBudgets
    sequence_receipt_schema: str
    matrix_receipt_schema: str
    scorecard_scorer: str

    def __post_init__(self) -> None:
        if not self.protocol_id or not self.case_prefix:
            raise ValueError("protocol identity and case prefix must not be empty")
        if self.heldout_seed_separator not in {"\\0", "\0"}:
            raise ValueError("seed separator must preserve v0.1 text or use one NUL byte")
        if self.development_seed_domain is None and not self.development_seed_values:
            raise ValueError("protocol must define development seeds or a derivation domain")


PROTOCOL_V0_1 = ProtocolDefinition(
    version=ProtocolVersion.V0_1,
    protocol_id="arc3.build003.curriculum.v0.1",
    protocol_path="docs/evaluation/build-003-curriculum-protocol.v0.1.json",
    manifest_path="docs/evaluation/build-003-heldout-seeds.v0.1.json",
    preregistration_path="docs/evaluation/build-003-preregistration.v0.1.json",
    heldout_seed_domain="arc3-build003-heldout-v1",
    heldout_seed_separator="\\0",
    development_seed_domain=None,
    development_seed_separator="\0",
    development_seed_values=(3030, 3031, 3032, 3033, 3034),
    case_prefix="b003c-",
    baseline=SourceIdentity(
        commit="753b0e007222a973a2c8a6d7ce14a395135d3c5f",
        tree="d07e72716a1f918ed04a6892adb1e3f46259e345",
    ),
    budgets=ProtocolBudgets(
        max_environment_actions=1500,
        max_environment_actions_per_level=None,
        max_resets=10,
        max_wall_clock_seconds=120.0,
        max_peak_memory_bytes=1_073_741_824,
        policy_cycle_seconds=10.0,
    ),
    sequence_receipt_schema="arc3.build003.sequence-run.v0.1",
    matrix_receipt_schema="arc3.build003.curriculum-matrix-receipt.v0.1",
    scorecard_scorer="arc3-build003-curriculum-v0.1",
)

PROTOCOL_V0_2 = ProtocolDefinition(
    version=ProtocolVersion.V0_2,
    protocol_id="arc3.build003.curriculum.v0.2",
    protocol_path="docs/evaluation/build-003-curriculum-protocol.v0.2.json",
    manifest_path="docs/evaluation/build-003-heldout-seeds.v0.2.json",
    preregistration_path="docs/evaluation/build-003-preregistration-amendment.v0.2.json",
    heldout_seed_domain="arc3-build003-curriculum-v0.2-heldout",
    heldout_seed_separator="\0",
    development_seed_domain="arc3-build003-curriculum-v0.2-development",
    development_seed_separator="\0",
    development_seed_values=(),
    case_prefix="b003v2-",
    baseline=SourceIdentity(
        commit="5448c53f3b7e08f606cf292e6068f3f9c9db16d4",
        tree="700718c09c2a1532cea16526b290f57be0120371",
    ),
    budgets=ProtocolBudgets(
        max_environment_actions=192,
        max_environment_actions_per_level=48,
        max_resets=10,
        max_wall_clock_seconds=10.0,
        max_peak_memory_bytes=1_073_741_824,
        policy_cycle_seconds=10.0,
    ),
    sequence_receipt_schema="arc3.build003.sequence-run.v0.2",
    matrix_receipt_schema="arc3.build003.curriculum-matrix-receipt.v0.2",
    scorecard_scorer="arc3-build003-curriculum-v0.2",
)

_BY_VERSION = {definition.version: definition for definition in (PROTOCOL_V0_1, PROTOCOL_V0_2)}
_BY_ID = {definition.protocol_id: definition for definition in _BY_VERSION.values()}


def protocol_definition(value: ProtocolDefinition | ProtocolVersion | str) -> ProtocolDefinition:
    """Resolve only an explicit known version or immutable protocol identifier."""

    if isinstance(value, ProtocolDefinition):
        return value
    if isinstance(value, ProtocolVersion):
        return _BY_VERSION[value]
    try:
        return _BY_VERSION[ProtocolVersion(value)]
    except ValueError:
        try:
            return _BY_ID[value]
        except KeyError as error:
            raise ValueError(f"unknown Build 003 curriculum protocol: {value}") from error


__all__ = [
    "PROTOCOL_V0_1",
    "PROTOCOL_V0_2",
    "ProtocolBudgets",
    "ProtocolDefinition",
    "ProtocolVersion",
    "SourceIdentity",
    "protocol_definition",
]
