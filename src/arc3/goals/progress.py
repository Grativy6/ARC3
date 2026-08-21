"""Exact extraction of score, progress, level, and terminal metadata changes."""

from __future__ import annotations

import hashlib
from collections.abc import Iterable

from arc3.adapters import Observation
from arc3.types import GameStateName, JSONScalar

from .models import (
    EvidenceDirection,
    GoalEvidence,
    ProgressSignal,
    ProgressSignalKind,
    ProgressSnapshot,
)

_SCORE_KEYS = ("score", "points", "reward")
_PROGRESS_KEYS = ("progress", "completion", "completion_rate")
_LEVEL_KEYS = ("level_index", "level")


def _number(value: JSONScalar | None) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _first_number(metadata: dict[str, JSONScalar], keys: Iterable[str]) -> float | None:
    for key in keys:
        value = _number(metadata.get(key))
        if value is not None:
            return value
    return None


def progress_snapshot(
    observation: Observation,
    *,
    step: int,
    source_event_ids: tuple[str, ...],
) -> ProgressSnapshot:
    """Copy only explicit progress-bearing fields from an observation."""

    metadata = dict(observation.upstream_metadata)
    explicit_level = _first_number(metadata, _LEVEL_KEYS)
    level_index = (
        int(explicit_level)
        if explicit_level is not None and explicit_level >= 0 and explicit_level.is_integer()
        else observation.levels_completed
    )
    return ProgressSnapshot(
        step=step,
        level_index=level_index,
        state=observation.state,
        levels_completed=observation.levels_completed,
        win_levels=observation.win_levels,
        score=_first_number(metadata, _SCORE_KEYS),
        progress=_first_number(metadata, _PROGRESS_KEYS),
        source_event_ids=source_event_ids,
    )


def _evidence_id(
    kind: ProgressSignalKind, before: ProgressSnapshot, after: ProgressSnapshot
) -> str:
    material = "\0".join(
        (
            "arc3.goal.progress.v1",
            kind.value,
            *before.source_event_ids,
            *after.source_event_ids,
        )
    ).encode()
    return f"gev:{hashlib.sha256(material).hexdigest()}"


def _signal(
    kind: ProgressSignalKind,
    before: ProgressSnapshot,
    after: ProgressSnapshot,
    *,
    old: float | int | str | None,
    new: float | int | str | None,
    magnitude: float,
    terminal: bool,
    positive: bool = True,
    rank_impact: int = 2,
) -> ProgressSignal:
    sources = tuple(sorted(set(before.source_event_ids + after.source_event_ids)))
    return ProgressSignal(
        kind=kind,
        before=old,
        after=new,
        magnitude=magnitude,
        terminal=terminal,
        evidence=GoalEvidence(
            evidence_id=_evidence_id(kind, before, after),
            direction=(EvidenceDirection.SUPPORT if positive else EvidenceDirection.CONTRADICTION),
            source_event_ids=sources,
            observed_step=after.step,
            level_index=after.level_index,
            summary=f"explicit {kind.value}: {old!s} -> {new!s}",
            rank_impact=rank_impact,
        ),
    )


def detect_progress_signals(
    before: ProgressSnapshot, after: ProgressSnapshot
) -> tuple[ProgressSignal, ...]:
    """Measure explicit progress transitions without inferring a structural cause."""

    if after.step < before.step:
        raise ValueError("progress snapshots must be supplied in step order")
    signals: list[ProgressSignal] = []
    if before.score is not None and after.score is not None and after.score > before.score:
        signals.append(
            _signal(
                ProgressSignalKind.SCORE_INCREASE,
                before,
                after,
                old=before.score,
                new=after.score,
                magnitude=after.score - before.score,
                terminal=False,
            )
        )
    if (
        before.progress is not None
        and after.progress is not None
        and after.progress > before.progress
    ):
        signals.append(
            _signal(
                ProgressSignalKind.PROGRESS_INCREASE,
                before,
                after,
                old=before.progress,
                new=after.progress,
                magnitude=after.progress - before.progress,
                terminal=False,
            )
        )
    if after.levels_completed > before.levels_completed:
        signals.append(
            _signal(
                ProgressSignalKind.LEVEL_COMPLETED,
                before,
                after,
                old=before.levels_completed,
                new=after.levels_completed,
                magnitude=float(after.levels_completed - before.levels_completed),
                terminal=True,
                rank_impact=4,
            )
        )
    if after.level_index > before.level_index:
        signals.append(
            _signal(
                ProgressSignalKind.LEVEL_ADVANCE,
                before,
                after,
                old=before.level_index,
                new=after.level_index,
                magnitude=float(after.level_index - before.level_index),
                terminal=True,
                rank_impact=4,
            )
        )
    if before.state is not GameStateName.WIN and after.state is GameStateName.WIN:
        signals.append(
            _signal(
                ProgressSignalKind.WIN,
                before,
                after,
                old=before.state.value,
                new=after.state.value,
                magnitude=1.0,
                terminal=True,
                rank_impact=5,
            )
        )
    if before.state is not GameStateName.GAME_OVER and after.state is GameStateName.GAME_OVER:
        signals.append(
            _signal(
                ProgressSignalKind.GAME_OVER,
                before,
                after,
                old=before.state.value,
                new=after.state.value,
                magnitude=1.0,
                terminal=True,
                positive=False,
                rank_impact=3,
            )
        )
    return tuple(signals)


def positive_external_progress(signals: tuple[ProgressSignal, ...]) -> bool:
    """Return whether a transition contains explicit positive progress evidence."""

    return any(signal.evidence.direction is EvidenceDirection.SUPPORT for signal in signals)


__all__ = ["detect_progress_signals", "positive_external_progress", "progress_snapshot"]
