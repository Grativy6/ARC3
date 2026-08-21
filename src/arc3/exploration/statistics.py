"""Conditioned action-effect counts with explicitly weak directional priors."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from arc3.types import ActionName, ActionRequest

from .models import EffectClassification, EffectKind, StateFeatures

_PRIOR_WEIGHT = 0.25
_DIRECTIONAL_PRIORS: dict[ActionName, tuple[int, int]] = {
    ActionName.ACTION1: (0, -1),
    ActionName.ACTION2: (0, 1),
    ActionName.ACTION3: (-1, 0),
    ActionName.ACTION4: (1, 0),
}


@dataclass(frozen=True, slots=True)
class EffectEstimate:
    """Highest-weight current estimate and the evidence supporting it."""

    kind: EffectKind
    displacement: tuple[int, int] | None
    weight: float
    observations: int
    prior_only: bool


class ActionEffectStatistics:
    """Mutable derived index over immutable before/action/after receipts."""

    def __init__(self, *, directional_prior_weight: float = _PRIOR_WEIGHT) -> None:
        if not 0.0 <= directional_prior_weight < 1.0:
            raise ValueError("directional_prior_weight must be within 0..1")
        self._prior_weight = directional_prior_weight
        self._counts: defaultdict[
            tuple[str, ActionRequest], defaultdict[tuple[EffectKind, tuple[int, int] | None], float]
        ] = defaultdict(lambda: defaultdict(float))
        self._observations: defaultdict[tuple[str, ActionRequest], int] = defaultdict(int)
        self._undo_successes = 0

    @property
    def supported_undo(self) -> bool:
        """Undo is supported only after a receipt restores a known prior frame."""

        return self._undo_successes > 0

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
        """Return evidence when present, otherwise a weak conventional prior."""

        key = (state.signature, action)
        counts: dict[tuple[EffectKind, tuple[int, int] | None], float] = dict(self._counts[key])
        prior = _DIRECTIONAL_PRIORS.get(action.name)
        if prior is not None and action.coordinate is None and self._prior_weight > 0:
            prior_key = (EffectKind.MOVEMENT, prior)
            counts[prior_key] = counts.get(prior_key, 0.0) + self._prior_weight
        if not counts:
            return EffectEstimate(EffectKind.NO_OP, None, 0.0, 0, True)
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
