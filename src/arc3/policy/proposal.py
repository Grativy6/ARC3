"""Disabled-by-default local proposal boundary.

Proposal providers may suggest typed, revisable interpretations.  This surface
does not contain :class:`~arc3.types.ActionRequest`, so a plugin cannot submit
or directly select an environment action.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from arc3.types import JSONValue


@dataclass(frozen=True, slots=True)
class ProposalContext:
    """Bounded, non-raw context available to an optional local-only model."""

    frame_hash: str
    measurement_summary: dict[str, JSONValue]
    active_hypothesis_ids: tuple[str, ...]
    active_goal_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class LocalProposal:
    """A revisable candidate interpretation with no action authority."""

    proposal_id: str
    family: str
    statement: dict[str, JSONValue]
    source: str = "local-experimental-model"

    def __post_init__(self) -> None:
        if not self.proposal_id.strip() or not self.family.strip():
            raise ValueError("proposal identity and family must be non-empty")


class LocalProposalProvider(Protocol):
    """Optional offline proposal generator; it never returns actions."""

    def propose(self, context: ProposalContext) -> tuple[LocalProposal, ...]:
        """Return bounded interpretations for ordinary typed validation."""


__all__ = ["LocalProposal", "LocalProposalProvider", "ProposalContext"]
