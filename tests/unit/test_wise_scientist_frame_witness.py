from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import pytest
import scripts.audit_wise_frame_positions as position_audit

from arc3.adapters import GridFrame
from arc3.errors import ARC3ValidationError
from arc3.types import JSONValue
from arc3.wise_scientist.frame_witness import (
    PositionChangeKind,
    measure_position_transition,
    measure_position_transition_between_patterns,
    measure_region_color_count,
    require_position_transition,
)
from arc3.wise_scientist.journal import WiseJournal

PATTERN = (
    (12, 12, 12),
    (12, 9, 12),
    (9, 9, 9),
)
AFTER_PATTERN = (
    (12, 12, 12),
    (12, 8, 12),
    (8, 8, 8),
)
ORDINARY = frozenset({(-1, 0), (1, 0), (0, -1), (0, 1)})
HUD_FRAME = GridFrame.from_rows(
    (
        (0, 5, 5, 1, 5),
        (5, 1, 5, 5, 0),
        (5, 5, 0, 5, 5),
    )
)
_EXACT_REPLAY_RULE = (
    "exact normalized observation payload after excluding only "
    "upstream_session_id and upstream_metadata"
)


def _frame(
    center: tuple[int, int],
    *,
    pattern: tuple[tuple[int, ...], ...] = PATTERN,
    resource: int = 1,
) -> GridFrame:
    rows = [[3 for _x in range(9)] for _y in range(9)]
    left = center[0] - 1
    top = center[1] - 1
    for y, row in enumerate(pattern):
        for x, cell in enumerate(row):
            rows[top + y][left + x] = cell
    rows[8][8] = resource
    return GridFrame.from_rows(rows)


def _hash(digit: str) -> str:
    return "sha256:" + (digit * 64)


def _record_observation(
    root: Path,
    journal: WiseJournal,
    *,
    identity: str,
    filename: str,
    frame: GridFrame,
) -> None:
    (root / filename).write_text(
        json.dumps({"frames": [{"cells": [list(row) for row in frame.cells]}]}),
        encoding="utf-8",
    )
    journal.append(
        "observation.recorded",
        {"observation_hash": identity, "observation_path": filename},
    )


def _record_resume(
    journal: WiseJournal,
    *,
    previous: object,
    replayed: object,
    semantic_replay_verified: object = True,
    equivalence_rule: object = _EXACT_REPLAY_RULE,
) -> None:
    journal.append(
        "run.resumed",
        {
            "previous_observation_hash": previous,
            "replayed_observation_hash": replayed,
            "semantic_replay_verified": semantic_replay_verified,
            "observation_equivalence_rule": equivalence_rule,
        },
    )


def _audit(
    root: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    after_pattern: tuple[tuple[int, ...], ...] | None = None,
) -> dict[str, JSONValue]:
    monkeypatch.setattr(position_audit, "ROOT", root.parent)
    return position_audit.audit_positions(
        root,
        pattern=PATTERN,
        ordinary_displacements=ORDINARY,
        first_action=1,
        last_action=1,
        after_pattern=after_pattern,
    )


def test_region_color_count_witness_measures_exact_rectangle() -> None:
    witness = measure_region_color_count(
        HUD_FRAME,
        left=1,
        top=0,
        right_exclusive=4,
        bottom_exclusive=2,
        color=5,
    )

    assert witness.left == 1
    assert witness.top == 0
    assert witness.right_exclusive == 4
    assert witness.bottom_exclusive == 2
    assert witness.color == 5
    assert witness.count == 4
    assert witness.to_dict() == {
        "region": {
            "left": 1,
            "top": 0,
            "right_exclusive": 4,
            "bottom_exclusive": 2,
        },
        "color": 5,
        "count": 4,
    }


def test_region_color_count_witness_preserves_exact_zero() -> None:
    witness = measure_region_color_count(
        HUD_FRAME,
        left=1,
        top=0,
        right_exclusive=4,
        bottom_exclusive=2,
        color=15,
    )

    assert witness.count == 0


@pytest.mark.parametrize(
    ("left", "top", "right_exclusive", "bottom_exclusive"),
    [
        (-1, 0, 1, 1),
        (0, -1, 1, 1),
        (1, 0, 1, 1),
        (0, 1, 1, 1),
        (0, 0, 6, 1),
        (0, 0, 1, 4),
        (True, 0, 2, 1),
    ],
)
def test_region_color_count_witness_rejects_invalid_bounds(
    left: int,
    top: int,
    right_exclusive: int,
    bottom_exclusive: int,
) -> None:
    with pytest.raises(ARC3ValidationError, match="bounds"):
        measure_region_color_count(
            HUD_FRAME,
            left=left,
            top=top,
            right_exclusive=right_exclusive,
            bottom_exclusive=bottom_exclusive,
            color=5,
        )


@pytest.mark.parametrize("color", [-1, 16, True])
def test_region_color_count_witness_rejects_invalid_color(color: int) -> None:
    with pytest.raises(ARC3ValidationError, match=r"color must be an integer in 0..15"):
        measure_region_color_count(
            HUD_FRAME,
            left=0,
            top=0,
            right_exclusive=HUD_FRAME.width,
            bottom_exclusive=HUD_FRAME.height,
            color=color,
        )


def test_position_witness_classifies_ordinary_move() -> None:
    transition = measure_position_transition(
        _frame((3, 3)),
        _frame((4, 3), resource=2),
        PATTERN,
        ordinary_displacements=ORDINARY,
    )

    assert transition.before.center == (3, 3)
    assert transition.after.center == (4, 3)
    assert transition.kind is PositionChangeKind.ORDINARY_MOVE


def test_position_witness_accepts_distinct_exact_after_pattern() -> None:
    transition = measure_position_transition_between_patterns(
        _frame((3, 3)),
        _frame((4, 3), pattern=AFTER_PATTERN, resource=2),
        before_pattern=PATTERN,
        after_pattern=AFTER_PATTERN,
        ordinary_displacements=ORDINARY,
    )

    assert transition.before.center == (3, 3)
    assert transition.after.center == (4, 3)
    assert transition.kind is PositionChangeKind.ORDINARY_MOVE


def test_position_witness_classifies_block_despite_hud_change() -> None:
    transition = measure_position_transition(
        _frame((3, 3), resource=1),
        _frame((3, 3), resource=2),
        PATTERN,
        ordinary_displacements=ORDINARY,
    )

    assert transition.displacement == (0, 0)
    assert transition.kind is PositionChangeKind.BLOCKED


def test_position_witness_classifies_respawn_as_discontinuity() -> None:
    transition = measure_position_transition(
        _frame((7, 1)),
        _frame((1, 7), resource=2),
        PATTERN,
        ordinary_displacements=ORDINARY,
    )

    assert transition.displacement == (-6, 6)
    assert transition.kind is PositionChangeKind.DISCONTINUITY


def test_position_witness_rejects_false_corridor_claim() -> None:
    transition = measure_position_transition(
        _frame((3, 3)),
        _frame((3, 3), resource=2),
        PATTERN,
        ordinary_displacements=ORDINARY,
    )

    with pytest.raises(ARC3ValidationError, match="disagrees with exact frames"):
        require_position_transition(
            transition,
            expected_before=(3, 3),
            expected_after=(4, 3),
            expected_kind=PositionChangeKind.ORDINARY_MOVE,
        )


def test_position_witness_rejects_ambiguous_pattern() -> None:
    frame = _frame((3, 3))
    rows = [list(row) for row in frame.cells]
    for y, row in enumerate(PATTERN):
        for x, cell in enumerate(row):
            rows[5 + y][5 + x] = cell

    with pytest.raises(ARC3ValidationError, match="exactly once"):
        measure_position_transition(
            frame,
            GridFrame.from_rows(rows),
            PATTERN,
            ordinary_displacements=ORDINARY,
        )


def test_position_audit_preserves_direct_observation_resolution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "run"
    root.mkdir()
    journal = WiseJournal(root / "events.jsonl")
    _record_observation(
        root,
        journal,
        identity=_hash("1"),
        filename="before.json",
        frame=_frame((3, 3)),
    )
    journal.append(
        "action.selected",
        {
            "action": {"name": "ACTION1"},
            "observation_hash": _hash("1"),
            "predicted_consequence": "the marker moves one cell east",
        },
    )
    _record_observation(
        root,
        journal,
        identity=_hash("3"),
        filename="after.json",
        frame=_frame((4, 3)),
    )
    journal.append("action.consequence", {"after_observation_hash": _hash("3")})

    result = _audit(root, monkeypatch)

    actions = cast(list[dict[str, JSONValue]], result["actions"])
    transition = cast(dict[str, JSONValue], actions[0]["position_transition"])
    before = cast(dict[str, JSONValue], transition["before"])
    after = cast(dict[str, JSONValue], transition["after"])
    assert before["center"] == [3, 3]
    assert after["center"] == [4, 3]
    assert result["schema"] == "arc3.wise-scientist.position-audit.v0.1"
    assert result["pattern"] == [list(row) for row in PATTERN]
    assert "before_pattern" not in result
    assert "after_pattern" not in result


def test_position_audit_records_distinct_before_and_after_patterns(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "run"
    root.mkdir()
    journal = WiseJournal(root / "events.jsonl")
    _record_observation(
        root,
        journal,
        identity=_hash("1"),
        filename="before.json",
        frame=_frame((3, 3)),
    )
    journal.append(
        "action.selected",
        {
            "action": {"name": "ACTION1"},
            "observation_hash": _hash("1"),
            "predicted_consequence": "the color-changing marker moves one cell east",
        },
    )
    _record_observation(
        root,
        journal,
        identity=_hash("3"),
        filename="after.json",
        frame=_frame((4, 3), pattern=AFTER_PATTERN, resource=2),
    )
    journal.append("action.consequence", {"after_observation_hash": _hash("3")})

    result = _audit(root, monkeypatch, after_pattern=AFTER_PATTERN)

    assert result["schema"] == "arc3.wise-scientist.position-audit.v0.1"
    assert result["pattern"] == [list(row) for row in PATTERN]
    assert result["before_pattern"] == [list(row) for row in PATTERN]
    assert result["after_pattern"] == [list(row) for row in AFTER_PATTERN]
    actions = cast(list[dict[str, JSONValue]], result["actions"])
    transition = cast(dict[str, JSONValue], actions[0]["position_transition"])
    assert transition["kind"] == PositionChangeKind.ORDINARY_MOVE.value


def test_position_audit_cli_after_pattern_defaults_to_before_pattern() -> None:
    parser = position_audit.build_parser()
    args = parser.parse_args(
        [
            "--artifact-dir",
            "artifacts/example",
            "--pattern-json",
            json.dumps(PATTERN),
            "--ordinary-displacement",
            "1,0",
            "--first-action",
            "1",
            "--last-action",
            "1",
        ]
    )

    before_pattern = position_audit._parse_pattern(args.pattern_json)
    after_pattern = (
        before_pattern
        if args.after_pattern_json is None
        else position_audit._parse_pattern(args.after_pattern_json, option="--after-pattern-json")
    )
    assert after_pattern == before_pattern


def test_position_audit_resolves_verified_resume_alias_chain(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "run"
    root.mkdir()
    journal = WiseJournal(root / "events.jsonl")
    _record_observation(
        root,
        journal,
        identity=_hash("1"),
        filename="before.json",
        frame=_frame((3, 3)),
    )
    _record_resume(journal, previous=_hash("1"), replayed=_hash("2"))
    _record_resume(journal, previous=_hash("2"), replayed=_hash("3"))
    journal.append(
        "action.selected",
        {
            "action": {"name": "ACTION1"},
            "observation_hash": _hash("3"),
            "predicted_consequence": "the marker moves one cell east",
        },
    )
    _record_observation(
        root,
        journal,
        identity=_hash("4"),
        filename="after.json",
        frame=_frame((4, 3)),
    )
    journal.append("action.consequence", {"after_observation_hash": _hash("4")})

    result = _audit(root, monkeypatch)

    actions = cast(list[dict[str, JSONValue]], result["actions"])
    assert actions[0]["before_observation_hash"] == _hash("3")
    transition = cast(dict[str, JSONValue], actions[0]["position_transition"])
    before = cast(dict[str, JSONValue], transition["before"])
    assert before["center"] == [3, 3]


@pytest.mark.parametrize(
    ("semantic_replay_verified", "equivalence_rule", "expected"),
    [
        (False, _EXACT_REPLAY_RULE, "requires verified semantic replay"),
        (True, "payload equality except arbitrary fields", "unauthorized equivalence rule"),
    ],
)
def test_position_audit_rejects_unverified_or_inexact_resume_alias(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    semantic_replay_verified: object,
    equivalence_rule: object,
    expected: str,
) -> None:
    root = tmp_path / "run"
    root.mkdir()
    journal = WiseJournal(root / "events.jsonl")
    _record_observation(
        root,
        journal,
        identity=_hash("1"),
        filename="before.json",
        frame=_frame((3, 3)),
    )
    _record_resume(
        journal,
        previous=_hash("1"),
        replayed=_hash("2"),
        semantic_replay_verified=semantic_replay_verified,
        equivalence_rule=equivalence_rule,
    )

    with pytest.raises(ARC3ValidationError, match=expected):
        _audit(root, monkeypatch)


@pytest.mark.parametrize(
    ("previous", "replayed"),
    [
        (None, _hash("2")),
        (_hash("1"), None),
        ("not-a-hash", _hash("2")),
        (_hash("1"), "not-a-hash"),
    ],
)
def test_position_audit_rejects_malformed_resume_alias(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    previous: object,
    replayed: object,
) -> None:
    root = tmp_path / "run"
    root.mkdir()
    journal = WiseJournal(root / "events.jsonl")
    _record_observation(
        root,
        journal,
        identity=_hash("1"),
        filename="before.json",
        frame=_frame((3, 3)),
    )
    _record_resume(journal, previous=previous, replayed=replayed)

    with pytest.raises(ARC3ValidationError, match="alias is malformed"):
        _audit(root, monkeypatch)


def test_position_audit_rejects_conflicting_resume_aliases(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "run"
    root.mkdir()
    journal = WiseJournal(root / "events.jsonl")
    _record_observation(
        root,
        journal,
        identity=_hash("1"),
        filename="first-before.json",
        frame=_frame((3, 3)),
    )
    _record_resume(journal, previous=_hash("1"), replayed=_hash("2"))
    _record_observation(
        root,
        journal,
        identity=_hash("3"),
        filename="conflicting-before.json",
        frame=_frame((5, 3)),
    )
    _record_resume(journal, previous=_hash("3"), replayed=_hash("2"))

    with pytest.raises(ARC3ValidationError, match="conflicts with existing evidence"):
        _audit(root, monkeypatch)
