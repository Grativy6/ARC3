"""Typed ARC3 error hierarchy.

Callers may catch :class:`ARC3Error` at an adapter boundary while retaining a
specific failure class for evidence and recovery decisions.
"""

from __future__ import annotations


class ARC3Error(Exception):
    """Base class for expected ARC3 failures."""


class ConfigurationError(ARC3Error):
    """Configuration is invalid or internally inconsistent."""


class CompetitionIntegrityError(ConfigurationError):
    """Configuration or code would violate a competition-mode invariant."""


class NetworkDisabledError(CompetitionIntegrityError):
    """A network operation was attempted in an offline execution mode."""


class ARC3ValidationError(ARC3Error):
    """First-party input failed structural validation."""


class DependencyUnavailableError(ARC3Error):
    """An optional or required external dependency is unavailable."""


class AdapterError(ARC3Error):
    """An environment adapter could not normalize an upstream operation."""


class InvalidActionError(AdapterError):
    """An action is not valid in the currently advertised action space."""


class EnvironmentStateError(AdapterError):
    """The environment state does not permit the requested operation."""


class TraceError(ARC3Error):
    """Base class for immutable trace failures."""


class TraceIntegrityError(TraceError):
    """A trace hash, linkage, or immutable identity failed verification."""


class ReplayError(TraceError):
    """A trace could not be replayed faithfully."""


class CheckpointError(ARC3Error):
    """A checkpoint could not be created, validated, or restored."""


class HypothesisError(ARC3Error):
    """A hypothesis transition or lineage operation is invalid."""


class WorldModelError(ARC3Error):
    """An executable world-model operation failed."""


class PlanningError(ARC3Error):
    """A planning operation failed within its declared contract."""


class PolicyError(ARC3Error):
    """The production policy could not produce a valid decision."""


class EvaluationError(ARC3Error):
    """An evaluation artifact or run is invalid."""


# Readable compatibility aliases; the ARC3-prefixed name avoids collisions in
# modules that also use a third-party ``ValidationError``.
ValidationError = ARC3ValidationError
DependencyError = DependencyUnavailableError
