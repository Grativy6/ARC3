from __future__ import annotations

from arc3.adapters import GridFrame, Observation
from arc3.goals import ProgressSignalKind, detect_progress_signals, progress_snapshot
from arc3.types import ActionName, GameId, GameStateName


def observation(
    *,
    state: GameStateName = GameStateName.NOT_FINISHED,
    levels: int = 0,
    metadata: tuple[tuple[str, int | float | bool | str | None], ...] = (),
) -> Observation:
    return Observation(
        game_id=GameId("opaque-test-scope"),
        frames=(GridFrame.from_rows(((0, 1), (0, 0))),),
        state=state,
        levels_completed=levels,
        win_levels=2,
        available_actions=(ActionName.ACTION1,),
        upstream_metadata=metadata,
    )


def test_explicit_score_progress_level_and_win_changes_are_measured() -> None:
    before = progress_snapshot(
        observation(metadata=(("score", 1.0), ("progress", 0.25), ("level_index", 0))),
        step=2,
        source_event_ids=("obs-before",),
    )
    after = progress_snapshot(
        observation(
            state=GameStateName.WIN,
            levels=1,
            metadata=(("score", 3.0), ("progress", 1.0), ("level_index", 1)),
        ),
        step=3,
        source_event_ids=("obs-after",),
    )

    signals = detect_progress_signals(before, after)

    assert {signal.kind for signal in signals} == {
        ProgressSignalKind.SCORE_INCREASE,
        ProgressSignalKind.PROGRESS_INCREASE,
        ProgressSignalKind.LEVEL_COMPLETED,
        ProgressSignalKind.LEVEL_ADVANCE,
        ProgressSignalKind.WIN,
    }
    assert all(
        signal.evidence.source_event_ids == ("obs-after", "obs-before") for signal in signals
    )
    assert all(signal.evidence.summary.startswith("explicit ") for signal in signals)


def test_missing_or_decreasing_numeric_metadata_does_not_claim_progress() -> None:
    before = progress_snapshot(
        observation(metadata=(("score", 4.0), ("progress", 0.8))),
        step=0,
        source_event_ids=("before",),
    )
    after = progress_snapshot(
        observation(metadata=(("score", 3.0),)),
        step=1,
        source_event_ids=("after",),
    )

    assert detect_progress_signals(before, after) == ()


def test_game_over_is_explicit_negative_terminal_evidence() -> None:
    before = progress_snapshot(observation(), step=0, source_event_ids=("before",))
    after = progress_snapshot(
        observation(state=GameStateName.GAME_OVER),
        step=1,
        source_event_ids=("after",),
    )

    signal = detect_progress_signals(before, after)[0]

    assert signal.kind is ProgressSignalKind.GAME_OVER
    assert signal.terminal is True
    assert signal.evidence.direction.value == "contradiction"
