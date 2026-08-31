"""Audit Wise Scientist action positions from immutable observation frames."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import cast

from arc3.adapters import GridFrame
from arc3.errors import ARC3ValidationError
from arc3.evaluation.artifacts import atomic_write_json
from arc3.trace.canonical import normalize_json, sha256_json
from arc3.types import JSONValue
from arc3.wise_scientist.frame_witness import measure_position_transition

ROOT = Path(__file__).resolve().parents[1]


def _inside_checkout(path: Path) -> Path:
    resolved = path.resolve()
    if not resolved.is_relative_to(ROOT):
        raise ARC3ValidationError("artifact directory must remain inside the checkout")
    return resolved


def _object(value: object, *, field: str) -> dict[str, JSONValue]:
    normalized = normalize_json(value)
    if not isinstance(normalized, dict):
        raise ARC3ValidationError(f"{field} must be an object")
    return normalized


def _load_json(path: Path) -> dict[str, JSONValue]:
    try:
        return _object(json.loads(path.read_text(encoding="utf-8")), field=str(path))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ARC3ValidationError(f"cannot read {path}: {error}") from error


def _parse_pattern(value: str) -> tuple[tuple[int, ...], ...]:
    try:
        raw: object = json.loads(value)
    except json.JSONDecodeError as error:
        raise ARC3ValidationError(f"invalid --pattern-json: {error}") from error
    if not isinstance(raw, list) or any(not isinstance(row, list) for row in raw):
        raise ARC3ValidationError("--pattern-json must be a two-dimensional array")
    rows: list[tuple[int, ...]] = []
    for raw_row in raw:
        row = cast(list[object], raw_row)
        if any(isinstance(cell, bool) or not isinstance(cell, int) for cell in row):
            raise ARC3ValidationError("--pattern-json cells must be integers")
        rows.append(tuple(cast(int, cell) for cell in row))
    return tuple(rows)


def _parse_displacement(value: str) -> tuple[int, int]:
    try:
        left, right = value.split(",", maxsplit=1)
        return (int(left), int(right))
    except (ValueError, TypeError) as error:
        raise ARC3ValidationError("--ordinary-displacement must be DX,DY") from error


def _frame_from_observation(value: dict[str, JSONValue]) -> GridFrame:
    raw_frames = value.get("frames")
    if not isinstance(raw_frames, list) or not raw_frames:
        raise ARC3ValidationError("stored observation has no frames")
    raw_frame = raw_frames[-1]
    if not isinstance(raw_frame, dict) or not isinstance(raw_frame.get("cells"), list):
        raise ARC3ValidationError("stored final frame is malformed")
    return GridFrame.from_rows(cast(list[list[int]], raw_frame["cells"]))


def audit_positions(
    artifact_dir: Path,
    *,
    pattern: tuple[tuple[int, ...], ...],
    ordinary_displacements: frozenset[tuple[int, int]],
    first_action: int,
    last_action: int,
) -> dict[str, JSONValue]:
    """Return exact transition evidence for a contiguous logical-action range."""

    root = _inside_checkout(artifact_dir)
    events_path = root / "events.jsonl"
    events: list[dict[str, JSONValue]] = []
    try:
        for line in events_path.read_text(encoding="utf-8").splitlines():
            events.append(_object(json.loads(line), field="journal event"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ARC3ValidationError(f"cannot read Wise Scientist journal: {error}") from error

    observation_paths: dict[str, Path] = {}
    for event in events:
        if event.get("event_type") != "observation.recorded":
            continue
        payload = event.get("payload")
        if not isinstance(payload, dict):
            raise ARC3ValidationError("observation event payload is malformed")
        identity = payload.get("observation_hash")
        relative = payload.get("observation_path")
        if not isinstance(identity, str) or not isinstance(relative, str):
            raise ARC3ValidationError("observation event identity/path is malformed")
        path = (root / relative).resolve()
        if not path.is_relative_to(root) or path.parent != root:
            raise ARC3ValidationError("observation event path escapes artifact directory")
        observation_paths[identity] = path

    logical_action = 0
    pending: dict[str, JSONValue] | None = None
    records: list[dict[str, JSONValue]] = []
    awaiting_assessment: dict[str, JSONValue] | None = None
    for event in events:
        event_type = event.get("event_type")
        payload = event.get("payload")
        if not isinstance(payload, dict):
            continue
        if event_type == "action.selected":
            action = payload.get("action")
            if not isinstance(action, dict) or not isinstance(action.get("name"), str):
                raise ARC3ValidationError("selected action payload is malformed")
            if action["name"] == "RESET":
                pending = None
                awaiting_assessment = None
                continue
            logical_action += 1
            pending = {
                "unique_logical_action_count": logical_action,
                "action_name": action["name"],
                "selected_event_hash": event.get("event_hash"),
                "before_observation_hash": payload.get("observation_hash"),
                "predicted_consequence": payload.get("predicted_consequence"),
                "assessment_event_hash": None,
                "assessment": None,
            }
        elif event_type == "action.consequence" and pending is not None:
            pending["after_observation_hash"] = payload.get("after_observation_hash")
            pending["consequence_event_hash"] = event.get("event_hash")
            records.append(pending)
            awaiting_assessment = pending
            pending = None
        elif event_type == "consequence.assessed" and awaiting_assessment is not None:
            awaiting_assessment["assessment_event_hash"] = event.get("event_hash")
            awaiting_assessment["assessment"] = payload.get("assessment")
            awaiting_assessment = None

    selected = [
        record
        for record in records
        if first_action
        <= cast(int, record["unique_logical_action_count"])
        <= last_action
    ]
    if [record["unique_logical_action_count"] for record in selected] != list(
        range(first_action, last_action + 1)
    ):
        raise ARC3ValidationError("requested logical-action range is incomplete")

    results: list[JSONValue] = []
    for record in selected:
        before_hash = record.get("before_observation_hash")
        after_hash = record.get("after_observation_hash")
        if not isinstance(before_hash, str) or not isinstance(after_hash, str):
            raise ARC3ValidationError("action observation hashes are malformed")
        before_path = observation_paths.get(before_hash)
        after_path = observation_paths.get(after_hash)
        if before_path is None or after_path is None:
            raise ARC3ValidationError("action observation artifact is missing")
        before_observation = _load_json(before_path)
        after_observation = _load_json(after_path)
        before_frame = _frame_from_observation(before_observation)
        after_frame = _frame_from_observation(after_observation)
        transition = measure_position_transition(
            before_frame,
            after_frame,
            pattern,
            ordinary_displacements=ordinary_displacements,
        )
        results.append(
            {
                **record,
                "before_final_frame_digest": str(before_frame.digest),
                "after_final_frame_digest": str(after_frame.digest),
                "position_transition": transition.to_dict(),
            }
        )

    core: dict[str, JSONValue] = {
        "schema": "arc3.wise-scientist.position-audit.v0.1",
        "artifact_dir": root.relative_to(ROOT).as_posix(),
        "action_range": [first_action, last_action],
        "ordinary_displacements": [
            list(item) for item in sorted(ordinary_displacements)
        ],
        "pattern": [list(row) for row in pattern],
        "actions": results,
    }
    return {**core, "audit_hash": sha256_json(core)}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-dir", required=True, type=Path)
    parser.add_argument("--pattern-json", required=True)
    parser.add_argument("--ordinary-displacement", action="append", required=True)
    parser.add_argument("--first-action", required=True, type=int)
    parser.add_argument("--last-action", required=True, type=int)
    parser.add_argument("--output", type=Path)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    pattern = _parse_pattern(args.pattern_json)
    displacements = frozenset(
        _parse_displacement(item) for item in args.ordinary_displacement
    )
    result = audit_positions(
        args.artifact_dir,
        pattern=pattern,
        ordinary_displacements=displacements,
        first_action=args.first_action,
        last_action=args.last_action,
    )
    if args.output is not None:
        atomic_write_json(_inside_checkout(args.output), result)
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
