"""Temporal component correspondence with visible uncertainty."""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum

from arc3.perception.components import Component


@dataclass(frozen=True, slots=True)
class CorrespondenceAlternative:
    """One observation-supported identity alternative, never an accepted identity."""

    before_id: str
    after_id: str
    score: float
    displacement: tuple[int, int]
    exact_translated_shape: bool
    same_color: bool
    evidence: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Correspondence:
    """Ranked alternatives for one prior component."""

    before_id: str
    alternatives: tuple[CorrespondenceAlternative, ...]

    @property
    def ambiguous(self) -> bool:
        return len(self.alternatives) > 1

    @property
    def sole_alternative(self) -> CorrespondenceAlternative | None:
        return self.alternatives[0] if len(self.alternatives) == 1 else None


class ComponentChangeKind(StrEnum):
    ADDITION = "addition"
    REMOVAL = "removal"
    RECOLOR = "recolor"
    TRANSLATION = "translation"
    RESIZE = "resize"
    SHAPE_CHANGE = "shape_change"
    STABLE = "stable"


@dataclass(frozen=True, slots=True)
class ComponentChange:
    before_id: str | None
    after_id: str | None
    kinds: tuple[ComponentChangeKind, ...]
    displacement: tuple[int, int] | None
    correspondence_score: float | None


@dataclass(frozen=True, slots=True)
class GlobalShift:
    displacement: tuple[int, int]
    supporting_correspondences: int
    confidence: float


@dataclass(frozen=True, slots=True)
class TrackingResult:
    correspondences: tuple[Correspondence, ...]
    changes: tuple[ComponentChange, ...]
    unmatched_before_ids: tuple[str, ...]
    unmatched_after_ids: tuple[str, ...]

    @property
    def has_ambiguity(self) -> bool:
        return any(correspondence.ambiguous for correspondence in self.correspondences)


def _jaccard(left: Component, right: Component) -> float:
    left_cells = frozenset((point.x, point.y) for point in left.cells)
    right_cells = frozenset((point.x, point.y) for point in right.cells)
    return len(left_cells & right_cells) / len(left_cells | right_cells)


def _normalized_shape_overlap(left: Component, right: Component) -> float:
    left_cells = frozenset(
        (point.x - left.bounds.left, point.y - left.bounds.top) for point in left.cells
    )
    right_cells = frozenset(
        (point.x - right.bounds.left, point.y - right.bounds.top) for point in right.cells
    )
    return len(left_cells & right_cells) / len(left_cells | right_cells)


def _candidate_score(
    before: Component,
    after: Component,
    *,
    frame_extent: tuple[int, int],
) -> CorrespondenceAlternative:
    exact_shape = before.translation_signature == after.translation_signature
    rotation_equivalent = before.rotation_signature == after.rotation_signature
    reflection_equivalent = before.reflection_signature == after.reflection_signature
    if exact_shape:
        shape_score = 1.0
    elif rotation_equivalent:
        shape_score = 0.85
    elif reflection_equivalent:
        shape_score = 0.75
    else:
        shape_score = _normalized_shape_overlap(before, after)
    size_score = min(before.area, after.area) / max(before.area, after.area)
    overlap_score = _jaccard(before, after)
    distance = math.dist(before.centroid, after.centroid)
    diagonal = max(math.hypot(*frame_extent), 1.0)
    proximity_score = max(0.0, 1.0 - distance / diagonal)
    color_score = 1.0 if before.color == after.color else 0.0
    score = (
        0.5 * shape_score
        + 0.2 * size_score
        + 0.15 * overlap_score
        + 0.1 * proximity_score
        + 0.05 * color_score
    )
    dx = round(after.centroid[0] - before.centroid[0])
    dy = round(after.centroid[1] - before.centroid[1])
    evidence: list[str] = []
    if exact_shape:
        evidence.append("translation-normalized shape equality")
    elif rotation_equivalent:
        evidence.append("rotation-canonical shape equality")
    elif reflection_equivalent:
        evidence.append("reflection-canonical shape equality")
    elif shape_score > 0:
        evidence.append("translation-normalized shape overlap")
    if before.area == after.area:
        evidence.append("equal area")
    if overlap_score > 0:
        evidence.append("cell overlap")
    if before.color == after.color:
        evidence.append("equal color")
    return CorrespondenceAlternative(
        before_id=before.component_id,
        after_id=after.component_id,
        score=round(score, 9),
        displacement=(dx, dy),
        exact_translated_shape=exact_shape,
        same_color=before.color == after.color,
        evidence=tuple(evidence),
    )


def _classify_pair(
    before: Component,
    after: Component,
    candidate: CorrespondenceAlternative,
) -> ComponentChange:
    kinds: list[ComponentChangeKind] = []
    if before.color != after.color:
        kinds.append(ComponentChangeKind.RECOLOR)
    if candidate.displacement != (0, 0):
        kinds.append(ComponentChangeKind.TRANSLATION)
    if before.area != after.area or (
        before.bounds.width,
        before.bounds.height,
    ) != (after.bounds.width, after.bounds.height):
        kinds.append(ComponentChangeKind.RESIZE)
    if before.translation_signature != after.translation_signature:
        kinds.append(ComponentChangeKind.SHAPE_CHANGE)
    if not kinds:
        kinds.append(ComponentChangeKind.STABLE)
    return ComponentChange(
        before_id=before.component_id,
        after_id=after.component_id,
        kinds=tuple(kinds),
        displacement=candidate.displacement,
        correspondence_score=candidate.score,
    )


def track_components(
    before: tuple[Component, ...],
    after: tuple[Component, ...],
    *,
    frame_extent: tuple[int, int],
    minimum_score: float = 0.55,
    ambiguity_tolerance: float = 0.025,
) -> TrackingResult:
    """Propose correspondence alternatives and classify only unambiguous pairs."""

    if frame_extent[0] < 1 or frame_extent[1] < 1:
        raise ValueError("frame_extent dimensions must be positive")
    if not 0 <= minimum_score <= 1 or not 0 <= ambiguity_tolerance <= 1:
        raise ValueError("score thresholds must be within 0..1")
    after_by_id = {component.component_id: component for component in after}
    correspondences: list[Correspondence] = []
    referenced_after: set[str] = set()
    changes: list[ComponentChange] = []
    unmatched_before: list[str] = []
    for source in before:
        ranked = sorted(
            (_candidate_score(source, target, frame_extent=frame_extent) for target in after),
            key=lambda candidate: (-candidate.score, candidate.after_id),
        )
        eligible = [candidate for candidate in ranked if candidate.score >= minimum_score]
        if not eligible:
            unmatched_before.append(source.component_id)
            changes.append(
                ComponentChange(
                    before_id=source.component_id,
                    after_id=None,
                    kinds=(ComponentChangeKind.REMOVAL,),
                    displacement=None,
                    correspondence_score=None,
                )
            )
            continue
        best_score = eligible[0].score
        alternatives = tuple(
            candidate
            for candidate in eligible
            if best_score - candidate.score <= ambiguity_tolerance
        )
        correspondences.append(Correspondence(source.component_id, alternatives))
        referenced_after.update(candidate.after_id for candidate in alternatives)
        if len(alternatives) == 1:
            selected = alternatives[0]
            changes.append(_classify_pair(source, after_by_id[selected.after_id], selected))

    unmatched_after = [
        component.component_id
        for component in after
        if component.component_id not in referenced_after
    ]
    changes.extend(
        ComponentChange(
            before_id=None,
            after_id=component_id,
            kinds=(ComponentChangeKind.ADDITION,),
            displacement=None,
            correspondence_score=None,
        )
        for component_id in unmatched_after
    )
    return TrackingResult(
        correspondences=tuple(correspondences),
        changes=tuple(changes),
        unmatched_before_ids=tuple(unmatched_before),
        unmatched_after_ids=tuple(unmatched_after),
    )


def detect_global_shift(result: TrackingResult) -> GlobalShift | None:
    """Return a shared exact-shape displacement only when correspondence is complete."""

    if result.unmatched_before_ids or result.unmatched_after_ids or not result.correspondences:
        return None
    alternatives = [item.sole_alternative for item in result.correspondences]
    if any(item is None or not item.exact_translated_shape for item in alternatives):
        return None
    certain = [item for item in alternatives if item is not None]
    if len({item.after_id for item in certain}) != len(certain):
        return None
    displacements = {item.displacement for item in certain}
    if len(displacements) != 1:
        return None
    return GlobalShift(
        displacement=next(iter(displacements)),
        supporting_correspondences=len(certain),
        confidence=min(item.score for item in certain),
    )
