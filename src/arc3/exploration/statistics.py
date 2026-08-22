"""Conditioned action-effect counts derived only from returned consequences."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from arc3.types import ActionRequest

from .models import EffectClassification, EffectKind, StateFeatures


@dataclass(frozen=True, slots=True)
class EffectEstimate:
    """Highest-weight current estimate and the evidence supporting it."""

    kind: EffectKind | None
    displacement: tuple[int, int] | None
    weight: float
    observations: int
    prior_only: bool


class ActionEffectStatistics:
    """Mutable derived index over immutable before/action/after receipts."""

    def __init__(self) -> None:
        self._counts: defaultdict[
            tuple[str, ActionRequest], defaultdict[tuple[EffectKind, tuple[int, int] | None], float]
        ] = defaultdict(lambda: defaultdict(float))
        self._observations: defaultdict[tuple[str, ActionRequest], int] = defaultdict(int)
        self._undo_successes = 0

    @property
    def supported_restore(self) -> bool:
        """Whether any submitted handle has restored a preserved prior frame."""

        return self._undo_successes > 0

    @property
    def supported_undo(self) -> bool:
        """Compatibility alias for receipt-supported restore evidence."""

        return self.supported_restore

    def observe(
        self,
        state: StateFeatures,
        action: ActionRequest,
        effect: EffectClassification,
    ) -> None:
        key = (state.signature, action)
        for kind in effect.kinds:
            displacement = effect.displacement if kind is EffectKind.MOVEMENT else None
            self._counts[key][(kind, displacement)] += 1.0
        self._observations[key] += 1
        if EffectKind.UNDO in effect.kinds:
            self._undo_successes += 1

    def estimate(self, state: StateFeatures, action: ActionRequest) -> EffectEstimate:
        """Return measured evidence, or an explicit unknown estimate."""

        key = (state.signature, action)
        counts: dict[tuple[EffectKind, tuple[int, int] | None], float] = dict(self._counts[key])
        if not counts:
            return EffectEstimate(None, None, 0.0, 0, True)
        (kind, displacement), weight = max(
            counts.items(), key=lambda item: (item[1], item[0][0].value, repr(item[0][1]))
        )
        observations = self._observations.get(key, 0)
        return EffectEstimate(
            kind=kind,
            displacement=displacement,
            weight=weight,
            observations=observations,
            prior_only=observations == 0,
        )


__all__ = ["ActionEffectStatistics", "EffectEstimate"]
