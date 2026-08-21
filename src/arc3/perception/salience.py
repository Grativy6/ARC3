"""Evidence-bounded candidates for action-correlated component change."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from enum import StrEnum

from arc3.types import ActionName


@dataclass(frozen=True, slots=True)
class ActionEffectEvidence:
    """One measured association; it does not establish identity or causation."""

    action: ActionName
    component_signature: str
    changed: bool
    correspondence_confidence: float

    def __post_init__(self) -> None:
        if not self.component_signature:
            raise ValueError("component_signature must not be empty")
        if not 0 <= self.correspondence_confidence <= 1:
            raise ValueError("correspondence_confidence must be within 0..1")


class ControllabilityStatus(StrEnum):
    """Deliberately lacks an accepted state; downstream hypotheses own promotion."""

    INSUFFICIENT = "insufficient"
    CANDIDATE = "candidate"


@dataclass(frozen=True, slots=True)
class ControllabilityCandidate:
    component_signature: str
    status: ControllabilityStatus
    evidence_count: int
    changed_evidence_count: int
    distinct_actions: tuple[ActionName, ...]
    weighted_change_ratio: float


def infer_controllability_candidates(
    evidence: tuple[ActionEffectEvidence, ...],
    *,
    minimum_evidence: int = 2,
    minimum_weighted_change_ratio: float = 0.5,
) -> tuple[ControllabilityCandidate, ...]:
    """Rank structural candidates while retaining a strict multi-sample threshold."""

    if minimum_evidence < 2:
        raise ValueError("minimum_evidence must be at least two")
    if not 0 <= minimum_weighted_change_ratio <= 1:
        raise ValueError("minimum_weighted_change_ratio must be within 0..1")
    grouped: defaultdict[str, list[ActionEffectEvidence]] = defaultdict(list)
    for item in evidence:
        grouped[item.component_signature].append(item)
    candidates: list[ControllabilityCandidate] = []
    for signature, items in grouped.items():
        denominator = sum(item.correspondence_confidence for item in items)
        numerator = sum(item.correspondence_confidence for item in items if item.changed)
        ratio = numerator / denominator if denominator else 0.0
        changed_count = sum(item.changed for item in items)
        supported = (
            len(items) >= minimum_evidence
            and changed_count >= 2
            and ratio >= minimum_weighted_change_ratio
        )
        candidates.append(
            ControllabilityCandidate(
                component_signature=signature,
                status=(
                    ControllabilityStatus.CANDIDATE
                    if supported
                    else ControllabilityStatus.INSUFFICIENT
                ),
                evidence_count=len(items),
                changed_evidence_count=changed_count,
                distinct_actions=tuple(sorted({item.action for item in items}, key=str)),
                weighted_change_ratio=round(ratio, 9),
            )
        )
    return tuple(
        sorted(
            candidates,
            key=lambda item: (
                item.status is not ControllabilityStatus.CANDIDATE,
                -item.weighted_change_ratio,
                item.component_signature,
            ),
        )
    )
