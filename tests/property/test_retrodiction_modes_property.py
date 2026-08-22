from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from arc3.types import ActionName, ActionRequest
from arc3.world_model import (
    Cell,
    MovementRule,
    PreservedTransition,
    RetrodictionConfig,
    RetrodictionMode,
    RetrodictionRequest,
    RetrodictionRuntime,
    SymbolicEntity,
    SymbolicState,
    make_model_candidate,
    retrodict,
)


def _state(x: int) -> SymbolicState:
    return SymbolicState(256, 3, (SymbolicEntity("piece", "mover", (Cell(x, 1),)),))


def _history(length: int, *, contradiction: int | None) -> tuple[PreservedTransition, ...]:
    return tuple(
        PreservedTransition(
            f"T-{index:03d}",
            _state(index + 32),
            ActionRequest(ActionName.ACTION1),
            _state(index + 32 + (-1 if contradiction == index else 1)),
            (f"E-{index:03d}-before", f"E-{index:03d}-after"),
        )
        for index in range(length)
    )


@settings(max_examples=40, deadline=None)
@given(
    length=st.integers(min_value=2, max_value=40),
    prefix=st.integers(min_value=1, max_value=39),
    contradiction=st.one_of(st.none(), st.integers(min_value=0, max_value=39)),
)
def test_cached_prefix_extension_is_semantically_identical_to_full(
    length: int,
    prefix: int,
    contradiction: int | None,
) -> None:
    prefix = min(prefix, length - 1)
    contradiction = contradiction if contradiction is not None and contradiction < length else None
    history = _history(length, contradiction=contradiction)
    model = make_model_candidate(
        hypothesis_ids=("H",),
        rules=(MovementRule("R", ActionName.ACTION1, 1, 0, entity_id="piece"),),
    )
    runtime = RetrodictionRuntime(RetrodictionConfig(RetrodictionMode.CACHED_INCREMENTAL))
    first_request = RetrodictionRequest(model, history[:prefix], "epoch:0")
    first_plan = runtime.plan(first_request)
    first = runtime.execute(first_plan)
    runtime.commit(first, source_receipt_event_id="E-FIRST")

    full_request = RetrodictionRequest(model, history, "epoch:0")
    incremental = runtime.execute(runtime.plan(full_request))

    assert incremental.artifact == retrodict(model, history)
