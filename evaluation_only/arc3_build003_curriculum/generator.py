"""Deterministic generator for the evaluator-held Build 003 curriculum."""

from __future__ import annotations

import hashlib
import random
from collections.abc import Iterable

from arc3.types import ActionName

from .models import (
    CARDINAL_VECTORS,
    DEFAULT_ACTION_VECTORS,
    MOVEMENT_ACTIONS,
    CurriculumCase,
    CurriculumFamily,
    CurriculumSpec,
    LevelSpec,
    Point,
)
from .protocol import (
    PROTOCOL_V0_1,
    PROTOCOL_V0_2,
    ProtocolDefinition,
    ProtocolVersion,
    protocol_definition,
)

PROTOCOL_ID = PROTOCOL_V0_1.protocol_id
BOARD_MIN = 1
BOARD_MAX = 8


def _derived_seed(domain: str, separator: str, index: int) -> int:
    payload = domain.encode("utf-8") + separator.encode("utf-8") + str(index).encode("ascii")
    digest = hashlib.sha256(payload).digest()
    return int.from_bytes(digest[:8], "big") % (2**63)


def derive_seed(
    index: int,
    protocol: ProtocolDefinition | ProtocolVersion | str = ProtocolVersion.V0_1,
) -> int:
    """Derive one frozen signed-63-bit seed without depending on Python hashing."""

    if isinstance(index, bool) or not isinstance(index, int) or index < 0:
        raise ValueError("seed index must be a non-negative integer")
    definition = protocol_definition(protocol)
    return _derived_seed(
        definition.heldout_seed_domain,
        definition.heldout_seed_separator,
        index,
    )


def frozen_seeds(
    protocol: ProtocolDefinition | ProtocolVersion | str = ProtocolVersion.V0_1,
) -> tuple[int, ...]:
    """Return the preregistered thirty-seed evaluation set."""

    definition = protocol_definition(protocol)
    return tuple(derive_seed(index, definition) for index in range(30))


def development_seeds(
    protocol: ProtocolDefinition | ProtocolVersion | str = ProtocolVersion.V0_1,
) -> tuple[int, ...]:
    """Return only the declared non-heldout development seeds."""

    definition = protocol_definition(protocol)
    if definition.development_seed_values:
        return definition.development_seed_values
    if definition.development_seed_domain is None:
        raise ValueError("protocol has no development seed derivation")
    return tuple(
        _derived_seed(
            definition.development_seed_domain,
            definition.development_seed_separator,
            index,
        )
        for index in range(5)
    )


def case_for_seed(
    seed: int,
    protocol: ProtocolDefinition | ProtocolVersion | str = ProtocolVersion.V0_1,
) -> CurriculumCase:
    """Give a seed an opaque, stable case identity."""

    if isinstance(seed, bool) or not isinstance(seed, int) or not 0 <= seed < 2**63:
        raise ValueError("curriculum seed must be an unsigned 63-bit integer")
    definition = protocol_definition(protocol)
    payload = definition.protocol_id.encode("utf-8") + b"\0" + str(seed).encode("ascii")
    digest = hashlib.sha256(payload).hexdigest()
    return CurriculumCase(case_id=f"{definition.case_prefix}{digest[:16]}", seed=seed)


def _transform(point: Point, symmetry: int) -> Point:
    """Apply one D4 symmetry inside the observable 1..8 board."""

    x, y = point
    x -= BOARD_MIN
    y -= BOARD_MIN
    extent = BOARD_MAX - BOARD_MIN
    if symmetry >= 4:
        x = extent - x
    for _ in range(symmetry % 4):
        x, y = extent - y, x
    return x + BOARD_MIN, y + BOARD_MIN


def _points(values: Iterable[Point], symmetry: int) -> frozenset[Point]:
    return frozenset(_transform(point, symmetry) for point in values)


def _level(
    *,
    family: CurriculumFamily,
    rng: random.Random,
    start: Point,
    goal: Point,
    walls: Iterable[Point] = (),
    base_cost: int = 1,
    resource_start: int = 24,
    resource_cap: int = 31,
    action_vectors: tuple[tuple[ActionName, Point], ...] = DEFAULT_ACTION_VECTORS,
    reusable_restorers: Iterable[Point] = (),
    one_shot_restorers: Iterable[Point] = (),
    restoration_amount: int = 0,
    switch: Point | None = None,
    gate: Point | None = None,
    pushable_start: Point | None = None,
    pushable_goal: Point | None = None,
    terrain: Iterable[Point] = (),
    terrain_extra_cost: int = 0,
    delayed_trigger: Point | None = None,
    delayed_actions: int = 0,
    decorations: Iterable[Point] = (),
    max_steps: int = 96,
) -> LevelSpec:
    symmetry = rng.randrange(8)
    palette = list(range(1, 16))
    rng.shuffle(palette)

    def transform_optional(value: Point | None) -> Point | None:
        return None if value is None else _transform(value, symmetry)

    return LevelSpec(
        family=family,
        size=10,
        start=_transform(start, symmetry),
        goal=_transform(goal, symmetry),
        walls=_points(walls, symmetry),
        base_cost=base_cost,
        resource_start=resource_start,
        resource_cap=resource_cap,
        action_vectors=action_vectors,
        reusable_restorers=_points(reusable_restorers, symmetry),
        one_shot_restorers=_points(one_shot_restorers, symmetry),
        restoration_amount=restoration_amount,
        switch=transform_optional(switch),
        gate=transform_optional(gate),
        pushable_start=transform_optional(pushable_start),
        pushable_goal=transform_optional(pushable_goal),
        terrain=_points(terrain, symmetry),
        terrain_extra_cost=terrain_extra_cost,
        delayed_trigger=transform_optional(delayed_trigger),
        delayed_actions=delayed_actions,
        decorations=_points(decorations, symmetry),
        palette=tuple(palette),
        max_steps=max_steps,
    )


def generate_curriculum(
    seed: int,
    protocol: ProtocolDefinition | ProtocolVersion | str = ProtocolVersion.V0_1,
) -> CurriculumSpec:
    """Generate the hidden progressive ten-level sequence for ``seed``."""

    definition = protocol_definition(protocol)
    case = case_for_seed(seed, definition)
    rng = random.Random(seed)
    sequence_base_cost: int | None = None
    action_vectors = DEFAULT_ACTION_VECTORS
    if definition is PROTOCOL_V0_2:
        sequence_base_cost = rng.randint(1, 2)
        shuffled_vectors = list(CARDINAL_VECTORS)
        rng.shuffle(shuffled_vectors)
        action_vectors = tuple(zip(MOVEMENT_ACTIONS, shuffled_vectors, strict=True))

    def base_cost(*, randomized_in_v01: bool) -> int:
        if sequence_base_cost is not None:
            return sequence_base_cost
        return rng.randint(1, 2) if randomized_in_v01 else 1

    wall_gap = rng.randint(5, 7)
    vertical_wall = {(4, y) for y in range(1, 9) if y != wall_gap}
    gate_wall = {(4, y) for y in range(1, 9) if y != 5}
    push_corridor = {(x, y) for x in range(1, 9) for y in (4, 6)}
    decoration_candidates = ((2, 7), (3, 3), (5, 7), (6, 2), (7, 7))
    harmless_decorations = rng.sample(
        decoration_candidates,
        k=rng.randint(2, len(decoration_candidates)),
    )
    composition_decorations = rng.sample(decoration_candidates, k=rng.randint(1, 3))
    levels = (
        _level(
            family=CurriculumFamily.MOVEMENT_RESOURCE_COST,
            rng=rng,
            start=(1, 1),
            goal=(8, 8),
            base_cost=base_cost(randomized_in_v01=True),
            resource_start=30,
            resource_cap=31,
            action_vectors=action_vectors,
        ),
        _level(
            family=CurriculumFamily.BLOCKING_WALLS,
            rng=rng,
            start=(1, 1),
            goal=(8, 8),
            walls=vertical_wall,
            base_cost=base_cost(randomized_in_v01=True),
            resource_start=30,
            resource_cap=31,
            action_vectors=action_vectors,
        ),
        _level(
            family=CurriculumFamily.RESOURCE_RESTORATION,
            rng=rng,
            start=(1, 1),
            goal=(8, 8),
            base_cost=base_cost(randomized_in_v01=False),
            resource_start=12 if definition is PROTOCOL_V0_2 else 9,
            reusable_restorers={(2, 3)},
            restoration_amount=(
                rng.randint(18, 22) if definition is PROTOCOL_V0_2 else rng.randint(10, 14)
            ),
            action_vectors=action_vectors,
        ),
        _level(
            family=CurriculumFamily.REUSABLE_ONE_SHOT,
            rng=rng,
            start=(1, 1),
            goal=(8, 8),
            base_cost=base_cost(randomized_in_v01=False),
            resource_start=12 if definition is PROTOCOL_V0_2 else 7,
            resource_cap=28,
            reusable_restorers={(4, 4)},
            one_shot_restorers={(1, 4)},
            restoration_amount=(
                rng.randint(16, 20) if definition is PROTOCOL_V0_2 else rng.randint(8, 12)
            ),
            action_vectors=action_vectors,
        ),
        _level(
            family=CurriculumFamily.GATE_SWITCH,
            rng=rng,
            start=(1, 5),
            goal=(8, 5),
            walls=gate_wall,
            switch=(2, 5),
            gate=(4, 5),
            base_cost=base_cost(randomized_in_v01=True),
            resource_start=20 if definition is PROTOCOL_V0_2 else 18,
            action_vectors=action_vectors,
        ),
        _level(
            family=CurriculumFamily.PUSHING,
            rng=rng,
            start=(2, 5),
            goal=(8, 5),
            walls=push_corridor,
            pushable_start=(4, 5),
            pushable_goal=(7, 5),
            base_cost=base_cost(randomized_in_v01=True),
            resource_start=18 if definition is PROTOCOL_V0_2 else 16,
            action_vectors=action_vectors,
        ),
        _level(
            family=CurriculumFamily.TERRAIN_STATUS,
            rng=rng,
            start=(1, 5),
            goal=(8, 5),
            terrain={(3, 5), (4, 5), (5, 5), (6, 5)},
            base_cost=base_cost(randomized_in_v01=True),
            terrain_extra_cost=rng.randint(1, 2),
            resource_start=26,
            action_vectors=action_vectors,
        ),
        _level(
            family=CurriculumFamily.DELAYED_RESPONSE,
            rng=rng,
            start=(1, 5),
            goal=(8, 5),
            walls=gate_wall,
            gate=(4, 5),
            delayed_trigger=(2, 5),
            delayed_actions=2,
            base_cost=base_cost(randomized_in_v01=True),
            resource_start=24 if definition is PROTOCOL_V0_2 else 20,
            action_vectors=action_vectors,
        ),
        _level(
            family=CurriculumFamily.HARMLESS_ANIMATION,
            rng=rng,
            start=(1, 1),
            goal=(8, 8),
            decorations=harmless_decorations,
            base_cost=base_cost(randomized_in_v01=True),
            resource_start=30,
            resource_cap=31,
            action_vectors=action_vectors,
        ),
        _level(
            family=CurriculumFamily.HELD_OUT_COMPOSITION,
            rng=rng,
            start=(1, 5),
            goal=(8, 8),
            walls=gate_wall,
            base_cost=base_cost(randomized_in_v01=False),
            resource_start=31 if definition is PROTOCOL_V0_2 else 26,
            resource_cap=31,
            reusable_restorers={(3, 7)},
            restoration_amount=14 if definition is PROTOCOL_V0_2 else 8,
            gate=(4, 5),
            pushable_start=(6, 5),
            pushable_goal=(8, 5),
            terrain={(5, 5), (5, 6)},
            terrain_extra_cost=rng.randint(1, 2),
            delayed_trigger=(2, 5),
            delayed_actions=2,
            decorations=composition_decorations,
            action_vectors=action_vectors,
        ),
    )
    return CurriculumSpec(case=case, levels=levels, protocol_id=definition.protocol_id)


__all__ = [
    "BOARD_MAX",
    "BOARD_MIN",
    "PROTOCOL_ID",
    "case_for_seed",
    "derive_seed",
    "development_seeds",
    "frozen_seeds",
    "generate_curriculum",
]
