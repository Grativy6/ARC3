"""Measure exact synthetic FAST/DEEP continuation and immutable replay gates."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from collections.abc import Sequence
from pathlib import Path
from typing import cast

from arc3.adapters.synthetic import SYNTHETIC_GAME_ID, SyntheticAdapter
from arc3.config import ARC3Config, BudgetConfig
from arc3.errors import PolicyError, TraceError
from arc3.evaluation.artifacts import atomic_write_json, seal_object
from arc3.evaluation.stage10_regression import STAGE10_CHECKPOINT_SCHEMA
from arc3.policy import (
    ARC3Controller,
    CadenceConfig,
    ControllerPhase,
    ControllerPreset,
    RunContext,
)
from arc3.trace import EventJournal, ReplayEngine, TraceEvent, sha256_json
from arc3.types import ActionRequest, EnvironmentMode, JSONValue

ROOT = Path(__file__).resolve().parents[1]
_SEED = 7
_MAX_ACTIONS = 16


def _git(*arguments: str) -> str:
    environment = {
        key: value for key, value in os.environ.items() if not key.upper().startswith("GIT_")
    }
    environment["GIT_NO_REPLACE_OBJECTS"] = "1"
    completed = subprocess.run(
        ("git", *arguments),
        cwd=ROOT,
        check=False,
        capture_output=True,
        env=environment,
        text=True,
        encoding="utf-8",
        timeout=10,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"git {' '.join(arguments)} failed")
    return completed.stdout.strip()


def _source_identity(frozen_commit: str) -> dict[str, JSONValue]:
    commit = _git("rev-parse", "HEAD")
    tree = _git("rev-parse", "HEAD^{tree}")
    dirty = bool(_git("status", "--porcelain=v1", "--untracked-files=all"))
    if commit != frozen_commit or dirty:
        raise RuntimeError("checkpoint worker requires the exact clean frozen source")
    return {
        "dirty_worktree": dirty,
        "git_commit": commit,
        "git_tree": tree,
        "verified": True,
    }


def _context(root: Path, *, label: str, frozen_commit: str) -> RunContext:
    return RunContext(
        run_id=f"stage10-{label}",
        episode_id=f"stage10-{label}-episode",
        game_id=SYNTHETIC_GAME_ID,
        trace_root=root / label / "trace",
        checkpoint_root=root / label / "checkpoint",
        config=ARC3Config(
            mode=EnvironmentMode.SYNTHETIC,
            seed=_SEED,
            profile="build-001-stage10-checkpoint-replay",
            budgets=BudgetConfig(max_actions=_MAX_ACTIONS, max_search_nodes=2_048),
        ),
        git_commit=frozen_commit,
    )


def _action(action: ActionRequest) -> dict[str, JSONValue]:
    coordinate = action.coordinate
    return {
        "coordinate": (None if coordinate is None else {"x": coordinate.x, "y": coordinate.y}),
        "name": action.name.value,
    }


def _selection(events: tuple[TraceEvent, ...]) -> dict[str, JSONValue]:
    event = next(item for item in reversed(events) if item.event_type == "reasoning.path_selected")
    ordered = event.payload.get("ordered_triggers")
    if not isinstance(ordered, list) or not all(isinstance(item, str) for item in ordered):
        raise RuntimeError("reasoning selection has malformed typed triggers")
    path = event.payload.get("path")
    if path not in {"FAST", "DEEP"}:
        raise RuntimeError("reasoning selection has malformed path")
    triggers: list[JSONValue] = [item for item in cast(list[str], ordered)]
    return {"ordered_triggers": triggers, "path": cast(str, path)}


def _decision_projection(
    controller: ARC3Controller,
    decision_action: ActionRequest,
    rationale_category: str,
    rationale_summary: str,
) -> dict[str, JSONValue]:
    return {
        "action": _action(decision_action),
        "rationale_category": rationale_category,
        "rationale_summary": rationale_summary,
        "selection": _selection(controller.journal.verify_manifest()),
    }


def _continuation_case(
    work_root: Path,
    *,
    target_path: str,
    frozen_commit: str,
) -> dict[str, JSONValue]:
    cadence = CadenceConfig(repeated_no_progress_threshold=16)
    label = target_path.lower()
    checkpoint_context = _context(
        work_root,
        label=f"{label}-checkpointed",
        frozen_commit=frozen_commit,
    )
    uninterrupted_context = _context(
        work_root,
        label=f"{label}-uninterrupted",
        frozen_commit=frozen_commit,
    )
    checkpointed_session = SyntheticAdapter(seed=_SEED, size=8, max_steps=32).open(
        SYNTHETIC_GAME_ID
    )
    uninterrupted_session = SyntheticAdapter(seed=_SEED, size=8, max_steps=32).open(
        SYNTHETIC_GAME_ID
    )
    checkpointed = ARC3Controller(ControllerPreset.FULL, cadence_config=cadence)
    uninterrupted = ARC3Controller(ControllerPreset.FULL, cadence_config=cadence)
    checkpointed.reset(checkpoint_context)
    uninterrupted.reset(uninterrupted_context)
    checkpointed.observe(checkpointed_session.observation)
    uninterrupted.observe(uninterrupted_session.observation)

    prefix_actions: list[JSONValue] = []
    for _ordinal in range(_MAX_ACTIONS):
        left = checkpointed._reasoning_selection
        right = uninterrupted._reasoning_selection
        if left is None or right is None or left.path != right.path:
            raise RuntimeError("paired cadence selections diverged before checkpoint")
        if left.path.value == target_path:
            break
        left_decision = checkpointed.choose_action()
        right_decision = uninterrupted.choose_action()
        if (
            left_decision.action != right_decision.action
            or left_decision.rationale_category != right_decision.rationale_category
            or left_decision.rationale_summary != right_decision.rationale_summary
        ):
            raise RuntimeError("paired decisions diverged before checkpoint")
        prefix_actions.append(_action(left_decision.action))
        checkpointed.apply_consequence(checkpointed_session.step(left_decision.action))
        uninterrupted.apply_consequence(uninterrupted_session.step(right_decision.action))
    else:
        raise RuntimeError(f"fixture did not reach a pending {target_path} boundary")

    pending = checkpointed._reasoning_selection
    if pending is None or pending.path.value != target_path:
        raise RuntimeError(f"fixture did not retain a pending {target_path} boundary")
    checkpoint = checkpointed.checkpoint()
    checkpointed.journal.close()
    restored = ARC3Controller.restore(
        checkpoint_context,
        preset=ControllerPreset.FULL,
        checkpoint_path=checkpoint.path,
        cadence_config=cadence,
    )
    restored_decision = restored.choose_action()
    uninterrupted_decision = uninterrupted.choose_action()
    restored_projection = _decision_projection(
        restored,
        restored_decision.action,
        restored_decision.rationale_category.value,
        restored_decision.rationale_summary,
    )
    uninterrupted_projection = _decision_projection(
        uninterrupted,
        uninterrupted_decision.action,
        uninterrupted_decision.rationale_category.value,
        uninterrupted_decision.rationale_summary,
    )
    exact = restored_projection == uninterrupted_projection
    restored.close()
    uninterrupted.close()
    checkpointed_session.close()
    uninterrupted_session.close()
    return {
        "checkpoint_hash": checkpoint.envelope.checkpoint_hash,
        "exact": exact,
        "path": target_path,
        "prefix_actions": prefix_actions,
        "restored": restored_projection,
        "uninterrupted": uninterrupted_projection,
    }


def _run_deterministic_episode(
    work_root: Path,
    *,
    label: str,
    frozen_commit: str,
) -> tuple[dict[str, JSONValue], Path, str]:
    context = _context(work_root, label=label, frozen_commit=frozen_commit)
    session = SyntheticAdapter(seed=_SEED, size=8, max_steps=32).open(SYNTHETIC_GAME_ID)
    controller = ARC3Controller(ControllerPreset.FULL)
    controller.reset(context)
    controller.observe(session.observation)
    actions: list[JSONValue] = []
    for _ordinal in range(_MAX_ACTIONS):
        if controller.phase in {ControllerPhase.COMPLETE, ControllerPhase.GAME_OVER}:
            break
        decision = controller.choose_action()
        actions.append(_action(decision.action))
        controller.apply_consequence(session.step(decision.action))
    score = session.scorecard()
    controller.close()
    session.close()
    journal = EventJournal(context.trace_root, run_id=context.run_id, fsync_on_flush=False)
    try:
        events = ReplayEngine(journal).verify_integrity(verify_blobs=True)
        paths: list[JSONValue] = [
            {
                "ordered_triggers": event.payload.get("ordered_triggers"),
                "path": event.payload.get("path"),
            }
            for event in events
            if event.event_type == "reasoning.path_selected"
        ]
        projection: dict[str, JSONValue] = {
            "actions": actions,
            "fault_count": controller.snapshot.fault_count,
            "final_phase": controller.snapshot.phase.value,
            "levels_completed": sum(run.levels_completed for run in score.runs),
            "paths": paths,
            "score": score.score,
        }
        return projection, context.trace_root, context.run_id
    finally:
        journal.close()


def _trace_receipt(trace_root: Path, *, run_id: str) -> dict[str, JSONValue]:
    journal = EventJournal(trace_root, run_id=run_id, fsync_on_flush=False)
    try:
        replay = ReplayEngine(journal)
        events = replay.verify_integrity(verify_blobs=True)
        frames = replay.replay_frames()
        deltas = replay.rebuild_deltas()
        return {
            "delta_count": len(deltas),
            "event_count": len(events),
            "frame_count": len(frames),
            "manifest_hash": journal.manifest.manifest_hash,
            "verified": True,
        }
    finally:
        journal.close()


def _trace_tamper_rejected(
    trace_root: Path,
    *,
    run_id: str,
    destination: Path,
) -> bool:
    shutil.copytree(trace_root, destination)
    candidate = next(
        (path for path in sorted(destination.rglob("*.jsonl")) if path.stat().st_size),
        None,
    )
    if candidate is None:
        raise RuntimeError("trace tamper fixture contains no event bytes")
    raw = bytearray(candidate.read_bytes())
    index = next((offset for offset, value in enumerate(raw) if value not in b"\r\n \t"), None)
    if index is None:
        raise RuntimeError("trace tamper fixture contains no mutable byte")
    raw[index] = ord("[") if raw[index] != ord("[") else ord("{")
    candidate.write_bytes(bytes(raw))
    try:
        journal = EventJournal(destination, run_id=run_id, fsync_on_flush=False)
        try:
            ReplayEngine(journal).verify_integrity(verify_blobs=True)
        finally:
            journal.close()
    except (OSError, TraceError, ValueError):
        return True
    return False


def _checkpoint_tamper_rejected(work_root: Path, *, frozen_commit: str) -> bool:
    context = _context(work_root, label="checkpoint-tamper", frozen_commit=frozen_commit)
    session = SyntheticAdapter(seed=_SEED, size=8, max_steps=32).open(SYNTHETIC_GAME_ID)
    controller = ARC3Controller(ControllerPreset.FULL)
    controller.reset(context)
    controller.observe(session.observation)
    controller.choose_action()
    checkpoint = controller.checkpoint()
    controller.journal.close()
    raw_value: object = json.loads(checkpoint.path.read_text(encoding="utf-8"))
    if not isinstance(raw_value, dict):
        raise RuntimeError("checkpoint tamper fixture is not an object")
    raw = cast(dict[str, object], raw_value)
    state = raw.get("state")
    if not isinstance(state, dict):
        raise RuntimeError("checkpoint tamper fixture has no state")
    derived = state.get("derived_controller_state")
    if not isinstance(derived, dict):
        raise RuntimeError("checkpoint tamper fixture has no controller state")
    planner = derived.get("planner_state")
    if not isinstance(planner, dict):
        raise RuntimeError("checkpoint tamper fixture has no planner state")
    cadence = planner.get("cadence_state")
    if not isinstance(cadence, dict):
        raise RuntimeError("checkpoint tamper fixture has no cadence state")
    streak = cadence.get("fast_streak")
    if isinstance(streak, bool) or not isinstance(streak, int):
        raise RuntimeError("checkpoint tamper fixture has no integer fast streak")
    cadence["fast_streak"] = streak + 1
    raw["checkpoint_hash"] = sha256_json(
        {key: value for key, value in raw.items() if key != "checkpoint_hash"}
    )
    tampered = work_root / "checkpoint-tamper" / "tampered.json"
    atomic_write_json(tampered, raw)
    try:
        ARC3Controller.restore(
            context,
            preset=ControllerPreset.FULL,
            checkpoint_path=tampered,
        )
    except PolicyError as error:
        session.close()
        return "immutable commitment" in str(error)
    session.close()
    return False


def run_measurement(
    *,
    work_root: Path,
    frozen_commit: str,
    command: Sequence[str],
) -> dict[str, object]:
    if work_root.exists() and any(work_root.iterdir()):
        raise ValueError(f"work root already contains data: {work_root}")
    work_root.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter_ns()
    source = _source_identity(frozen_commit)
    deep = _continuation_case(work_root, target_path="DEEP", frozen_commit=frozen_commit)
    fast = _continuation_case(work_root, target_path="FAST", frozen_commit=frozen_commit)
    first, trace_root, run_id = _run_deterministic_episode(
        work_root,
        label="repeat-a",
        frozen_commit=frozen_commit,
    )
    second, _second_root, _second_run_id = _run_deterministic_episode(
        work_root,
        label="repeat-b",
        frozen_commit=frozen_commit,
    )
    replay = _trace_receipt(trace_root, run_id=run_id)
    trace_tamper = _trace_tamper_rejected(
        trace_root,
        run_id=run_id,
        destination=work_root / "trace-tamper-copy",
    )
    checkpoint_tamper = _checkpoint_tamper_rejected(
        work_root,
        frozen_commit=frozen_commit,
    )
    acceptance = {
        "checkpoint_tamper_rejected": checkpoint_tamper,
        "deep_exact_continuation": deep.get("exact") is True,
        "deterministic_seed_repeatability": first == second,
        "fast_exact_continuation": fast.get("exact") is True,
        "trace_replay": replay.get("verified") is True,
        "trace_tamper_rejected": trace_tamper,
    }
    status = "PASS" if all(acceptance.values()) else "FAILED_MECHANISM"
    report: dict[str, object] = {
        "acceptance": acceptance,
        "claim": "NO_GENERALIZATION_CLAIM",
        "command": list(command),
        "deep_continuation": deep,
        "deterministic_repeat": {"first": first, "second": second},
        "evidence_label": "synthetic",
        "fast_continuation": fast,
        "resource": {"wall_ns": max(0, time.perf_counter_ns() - started)},
        "schema": STAGE10_CHECKPOINT_SCHEMA,
        "source_identity": source,
        "status": status,
        "trace_replay": replay,
    }
    return seal_object(report, hash_field="artifact_core_hash")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--work-root", type=Path, required=True)
    parser.add_argument("--frozen-commit", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    invocation = list(sys.argv[1:] if argv is None else argv)
    args = _parser().parse_args(invocation)
    if len(args.frozen_commit) != 40 or any(
        character not in "0123456789abcdef" for character in args.frozen_commit
    ):
        raise SystemExit("--frozen-commit must be an exact lowercase 40-hex commit")
    try:
        report = run_measurement(
            work_root=args.work_root.resolve(),
            frozen_commit=cast(str, args.frozen_commit),
            command=invocation,
        )
    except (OSError, RuntimeError, ValueError) as error:
        print(
            f"Stage 10 checkpoint worker failed: {type(error).__name__}: {error}", file=sys.stderr
        )
        return 2
    atomic_write_json(args.output.resolve(), report)
    return 0 if report.get("status") == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
