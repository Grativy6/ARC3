"""Profile the packaged Build 003 mechanical route against exact Build 002.

This harness uses only named synthetic development frames.  It never imports a
game package, opens an environment, reads a public partition, or accesses a
heldout seed.  Each source is measured twice in a fresh process so source
identity, route ownership, deterministic actions, wall time, and peak RSS are
all explicit in one sealed receipt.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import runpy
import subprocess
import sys
import tempfile
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, cast

BUILD002_COMMIT = "5448c53f3b7e08f606cf292e6068f3f9c9db16d4"
BUILD002_TREE = "700718c09c2a1532cea16526b290f57be0120371"
SCHEMA = "arc3.build003.mechanical-production-profile.v0.1"
FIXTURE_ID = "visible-affine-development-v0.1"
GAME_ID = "synthetic-mechanical-profile"
REPETITIONS = 2
EXPECTED_CYCLES = 3
MAX_CYCLE_SECONDS = 10.0
MAX_PEAK_RSS_BYTES = 2_147_483_648

_ENDPOINT_SHAPE = (
    (0, -2),
    (-1, -1),
    (0, -1),
    (1, -1),
    (-2, 0),
    (-1, 0),
    (0, 0),
    (1, 0),
    (2, 0),
    (-1, 1),
    (0, 1),
    (1, 1),
    (0, 2),
)
_MEDIATOR_OUTER = tuple(
    (dx, dy)
    for dy in range(-2, 3)
    for dx in range(-2, 3)
    if (abs(dx), abs(dy)) != (2, 2) and (dx, dy) != (0, 0)
)
_TARGET_RING = (
    (-1, -2),
    (0, -2),
    (1, -2),
    (-2, -1),
    (2, -1),
    (-2, 0),
    (2, 0),
    (-2, 1),
    (2, 1),
    (-1, 2),
    (0, 2),
    (1, 2),
)


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


def _sealed(value: Mapping[str, object]) -> dict[str, object]:
    result = dict(value)
    result["receipt_sha256"] = _sha256_bytes(_canonical_bytes(result))
    return result


def _atomic_write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(_canonical_bytes(value) + b"\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _git_environment() -> dict[str, str]:
    environment = {
        key: value for key, value in os.environ.items() if not key.upper().startswith("GIT_")
    }
    environment["GIT_NO_REPLACE_OBJECTS"] = "1"
    return environment


def _git_text(root: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ("git", "--no-replace-objects", "-C", str(root), *arguments),
        check=False,
        capture_output=True,
        env=_git_environment(),
        text=True,
        encoding="utf-8",
        timeout=30,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"git {' '.join(arguments)} failed with exit {completed.returncode}: "
            f"{completed.stderr.strip()}"
        )
    return completed.stdout.strip()


def _source_identity(root: Path, *, commit: str, tree: str | None = None) -> dict[str, object]:
    resolved = root.resolve()
    if Path(_git_text(resolved, "rev-parse", "--show-toplevel")).resolve() != resolved:
        raise RuntimeError("profile source root is not the exact Git top level")
    actual_commit = _git_text(resolved, "rev-parse", "HEAD")
    actual_tree = _git_text(resolved, "rev-parse", "HEAD^{tree}")
    status = _git_text(resolved, "status", "--porcelain=v1", "--untracked-files=all")
    if actual_commit != commit or (tree is not None and actual_tree != tree) or status:
        raise RuntimeError("profile source is not the named clean frozen commit/tree")
    return {
        "clean": True,
        "commit": actual_commit,
        "root": str(resolved),
        "tree": actual_tree,
    }


def _sanitized_environment(source_root: Path) -> dict[str, str]:
    blocked = ("API_KEY", "TOKEN", "PASSWORD", "SECRET", "KAGGLE")
    environment = {
        key: value
        for key, value in os.environ.items()
        if not any(part in key.upper() for part in blocked)
        and key.upper() not in {"PYTHONHOME", "PYTHONPATH", "VIRTUAL_ENV"}
    }
    environment.update(
        {
            "ARC3_NETWORK_ENABLED": "false",
            "PYTHONHASHSEED": "0",
            "PYTHONNOUSERSITE": "1",
            "PYTHONPATH": os.pathsep.join((str(source_root / "src"), str(source_root))),
        }
    )
    return environment


def _paint(
    rows: list[list[int]],
    center: tuple[int, int],
    shape: Sequence[tuple[int, int]],
    color: int,
) -> None:
    for dx, dy in shape:
        rows[center[1] + dy][center[0] + dx] = color


def _visible_rows(*, phase: int) -> list[list[int]]:
    """Return one generic visible-relation frame from the named dev fixture."""

    rows = [[5 for _ in range(40)] for _ in range(40)]
    active = ((8, 30), (10, 29), (12, 28))[phase]
    anchor = (30, 30)
    mediator = (19, 30)
    target = (20, 8)
    _paint(rows, active, _ENDPOINT_SHAPE, 0)
    _paint(rows, anchor, _ENDPOINT_SHAPE, 3)
    _paint(rows, mediator, _MEDIATOR_OUTER, 15)
    rows[mediator[1]][mediator[0]] = 6
    _paint(rows, target, _TARGET_RING, 15)
    return rows


def _enum_name(value: object) -> str:
    name = getattr(value, "name", None)
    if isinstance(name, str):
        return name.upper()
    raw = getattr(value, "value", value)
    return str(raw).upper()


def _worker_measurement(config_path: Path) -> dict[str, object]:
    config_raw: object = json.loads(config_path.read_text(encoding="utf-8"))
    if not isinstance(config_raw, dict):
        raise ValueError("worker configuration must be an object")
    config = cast(dict[str, Any], config_raw)
    source_root = Path(str(config["source_root"])).resolve()
    source = _source_identity(
        source_root,
        commit=str(config["commit"]),
        tree=str(config["tree"]),
    )

    from arcengine import FrameData, GameState

    import arc3
    from arc3.profiling import process_memory_sample

    imported_arc3 = Path(arc3.__file__).resolve()
    if not imported_arc3.is_relative_to((source_root / "src" / "arc3").resolve()):
        raise RuntimeError("worker imported arc3 outside the named source root")
    wrapper_path = source_root / "agent" / "my_agent.py"
    wrapper = runpy.run_path(str(wrapper_path))
    agent_type = wrapper.get("MyAgent")
    if not isinstance(agent_type, type):
        raise RuntimeError("named source has no MyAgent type")

    runtime_root = Path(str(config["runtime_root"])).resolve()
    runtime_root.mkdir(parents=True, exist_ok=False)
    configure = getattr(agent_type, "configure_tournament", None)
    finalize = getattr(agent_type, "finalize_tournament", None)
    if not callable(configure) or not callable(finalize):
        raise RuntimeError("MyAgent tournament lifecycle is unavailable")
    configure((GAME_ID,), runtime_root)
    agent = agent_type(game_id=GAME_ID, seed=71)

    frames = (
        FrameData(
            game_id=GAME_ID,
            frame=[_visible_rows(phase=0)],
            state=GameState.NOT_FINISHED,
            levels_completed=0,
            win_levels=2,
            available_actions=[6],
        ),
        FrameData(
            game_id=GAME_ID,
            frame=[_visible_rows(phase=1)],
            state=GameState.NOT_FINISHED,
            levels_completed=0,
            win_levels=2,
            available_actions=[6],
        ),
        FrameData(
            game_id=GAME_ID,
            frame=[_visible_rows(phase=2)],
            state=GameState.NOT_FINISHED,
            levels_completed=1,
            win_levels=2,
            available_actions=[6],
        ),
    )
    actions: list[str] = []
    cycle_seconds: list[float] = []
    started = time.perf_counter()
    for frame in frames:
        cycle_started = time.perf_counter()
        selected = agent.choose_action([], frame)
        elapsed = time.perf_counter() - cycle_started
        if not math.isfinite(elapsed) or elapsed < 0.0:
            raise RuntimeError("worker produced an invalid cycle duration")
        cycle_seconds.append(elapsed)
        actions.append(_enum_name(selected))

    terminal = FrameData(
        game_id=GAME_ID,
        frame=[_visible_rows(phase=2)],
        state=GameState.WIN,
        levels_completed=2,
        win_levels=2,
        available_actions=[],
    )
    if agent.is_done([], terminal) is not True:
        raise RuntimeError("synthetic terminal fixture was not recognized")
    tournament = finalize()
    total_seconds = time.perf_counter() - started
    memory = process_memory_sample()
    peak_rss = memory.get("peak_rss_bytes")
    if isinstance(peak_rss, bool) or not isinstance(peak_rss, int) or peak_rss <= 0:
        raise RuntimeError("worker peak RSS is unavailable")

    route = getattr(agent, "_policy_route", None)
    route_name = getattr(route, "value", None)
    mechanical = getattr(agent, "_mechanical_policy", None)
    mechanical_snapshot: Mapping[str, object] | None = None
    if mechanical is not None:
        snapshot = getattr(mechanical, "snapshot", None)
        if callable(snapshot):
            raw_snapshot = snapshot()
            if isinstance(raw_snapshot, Mapping):
                mechanical_snapshot = cast(Mapping[str, object], raw_snapshot)

    source_end = _source_identity(
        source_root,
        commit=str(config["commit"]),
        tree=str(config["tree"]),
    )
    if source_end != source:
        raise RuntimeError("source identity changed during the profile")
    games = tournament.get("games") if isinstance(tournament, Mapping) else None
    return {
        "action_names": actions,
        "cycle_seconds": cycle_seconds,
        "fixture_id": FIXTURE_ID,
        "imported_arc3": str(imported_arc3),
        "mechanical_receipt_count": (
            mechanical_snapshot.get("receipt_count") if mechanical_snapshot is not None else None
        ),
        "peak_rss_bytes": peak_rss,
        "policy_route": route_name,
        "repetition": int(config["repetition"]),
        "role": str(config["role"]),
        "source": source,
        "synthetic_terminal_observed": True,
        "total_seconds": total_seconds,
        "tournament_games": games,
    }


def _run_worker(config_path: Path) -> int:
    try:
        result = _sealed(_worker_measurement(config_path))
    except BaseException as error:
        print(f"mechanical profile worker failed: {type(error).__name__}: {error}", file=sys.stderr)
        return 2
    sys.stdout.buffer.write(_canonical_bytes(result) + b"\n")
    return 0


def _verify_worker_receipt(raw: bytes) -> dict[str, Any]:
    parsed: object = json.loads(raw)
    if not isinstance(parsed, dict):
        raise RuntimeError("worker receipt is not an object")
    receipt = cast(dict[str, Any], parsed)
    claimed = receipt.pop("receipt_sha256", None)
    if claimed != _sha256_bytes(_canonical_bytes(receipt)):
        raise RuntimeError("worker receipt hash does not verify")
    receipt["receipt_sha256"] = claimed
    return receipt


def _spawn_measurement(
    *,
    script: Path,
    source: Mapping[str, object],
    role: str,
    repetition: int,
    work_root: Path,
    timeout_seconds: float,
) -> dict[str, Any]:
    repetition_root = work_root / f"{role}-{repetition}"
    repetition_root.mkdir(parents=True, exist_ok=False)
    config_path = repetition_root / "worker-config.json"
    config = {
        "commit": source["commit"],
        "repetition": repetition,
        "role": role,
        "runtime_root": str(repetition_root / "runtime"),
        "source_root": source["root"],
        "tree": source["tree"],
    }
    _atomic_write(config_path, config)
    completed = subprocess.run(
        (sys.executable, str(script), "--worker-config", str(config_path)),
        cwd=Path(str(source["root"])),
        env=_sanitized_environment(Path(str(source["root"]))),
        check=False,
        capture_output=True,
        timeout=timeout_seconds,
    )
    if completed.returncode != 0:
        message = completed.stderr.decode("utf-8", errors="replace")[:1000]
        raise RuntimeError(
            f"{role} profile worker failed with exit {completed.returncode}: {message}"
        )
    return _verify_worker_receipt(completed.stdout)


def _maximum(values: Sequence[float]) -> float:
    if not values or any(not math.isfinite(value) or value < 0.0 for value in values):
        raise RuntimeError("profile has missing or invalid timing measurements")
    return max(values)


def _required_number(run: Mapping[str, Any], key: str) -> float:
    raw = run.get(key)
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise RuntimeError(f"profile has no numeric {key}")
    value = float(raw)
    if not math.isfinite(value) or value < 0.0:
        raise RuntimeError(f"profile has invalid {key}")
    return value


def _required_integer(run: Mapping[str, Any], key: str) -> int:
    raw = run.get(key)
    if isinstance(raw, bool) or not isinstance(raw, int) or raw <= 0:
        raise RuntimeError(f"profile has no positive integer {key}")
    return raw


def _required_actions(run: Mapping[str, Any]) -> tuple[str, ...]:
    raw = run.get("action_names")
    if not isinstance(raw, list) or any(not isinstance(item, str) for item in raw):
        raise RuntimeError("profile action sequence is missing or malformed")
    return tuple(cast(list[str], raw))


def _required_cycles(run: Mapping[str, Any]) -> tuple[float, ...]:
    raw = run.get("cycle_seconds")
    if not isinstance(raw, list):
        raise RuntimeError("profile cycle measurements are missing")
    values: list[float] = []
    for item in raw:
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            raise RuntimeError("profile cycle measurement is not numeric")
        values.append(float(item))
    return tuple(values)


def _aggregate(runs: Sequence[Mapping[str, Any]], *, role: str) -> dict[str, Any]:
    if len(runs) != REPETITIONS:
        raise RuntimeError(f"{role} profile does not have {REPETITIONS} repetitions")
    action_sequences = [_required_actions(run) for run in runs]
    deterministic = len(set(action_sequences)) == 1
    all_cycles = [value for run in runs for value in _required_cycles(run)]
    peaks = [_required_integer(run, "peak_rss_bytes") for run in runs]
    totals = [_required_number(run, "total_seconds") for run in runs]
    return {
        "action_sequence": list(action_sequences[0]),
        "action_sequence_deterministic": deterministic,
        "cycle_count_per_repetition": len(action_sequences[0]),
        "cycle_seconds_maximum": _maximum(all_cycles),
        "cycle_seconds_mean": sum(all_cycles) / len(all_cycles),
        "peak_rss_bytes_maximum": max(peaks),
        "repetitions": [dict(run) for run in runs],
        "total_seconds_maximum": _maximum(totals),
        "total_seconds_mean": sum(totals) / len(totals),
    }


def _build_comparison(
    build003_runs: Sequence[Mapping[str, Any]],
    build002_runs: Sequence[Mapping[str, Any]],
) -> dict[str, object]:
    build003 = _aggregate(build003_runs, role="build003")
    build002 = _aggregate(build002_runs, role="build002")
    build003_cycle = float(build003["cycle_seconds_maximum"])
    build002_cycle = float(build002["cycle_seconds_maximum"])
    build003_rss = int(build003["peak_rss_bytes_maximum"])
    build002_rss = int(build002["peak_rss_bytes_maximum"])
    route_verified = all(
        run.get("policy_route") == "mechanical"
        and isinstance(run.get("mechanical_receipt_count"), int)
        and int(run["mechanical_receipt_count"]) >= EXPECTED_CYCLES
        for run in build003_runs
    )
    checks = {
        "build002_action_sequence_deterministic": build002["action_sequence_deterministic"] is True,
        "build003_action_sequence_deterministic": build003["action_sequence_deterministic"] is True,
        "build003_cycle_budget": build003_cycle <= MAX_CYCLE_SECONDS,
        "build003_peak_rss_budget": build003_rss <= MAX_PEAK_RSS_BYTES,
        "build003_production_mechanical_route": route_verified,
        "matched_cycle_count": (
            build002["cycle_count_per_repetition"]
            == build003["cycle_count_per_repetition"]
            == EXPECTED_CYCLES
        ),
        "synthetic_terminal_observed": all(
            run.get("synthetic_terminal_observed") is True
            for run in (*build002_runs, *build003_runs)
        ),
    }
    regressions = {
        "cycle_maximum_slower_than_build002": build003_cycle > build002_cycle,
        "peak_rss_higher_than_build002": build003_rss > build002_rss,
        "total_mean_slower_than_build002": (
            float(build003["total_seconds_mean"]) > float(build002["total_seconds_mean"])
        ),
    }
    return {
        "build002": build002,
        "build003": build003,
        "checks": checks,
        "claim": "SYNTHETIC_PERFORMANCE_ONLY_NO_GAMEPLAY_OR_RHAE_CLAIM",
        "fixture": {
            "cycles": EXPECTED_CYCLES,
            "game_id": GAME_ID,
            "id": FIXTURE_ID,
            "public_or_heldout_inputs": False,
        },
        "limits": {
            "max_cycle_seconds": MAX_CYCLE_SECONDS,
            "max_peak_rss_bytes": MAX_PEAK_RSS_BYTES,
        },
        "regressions": regressions,
        "status": "PASS" if all(checks.values()) else "FAILED_MECHANISM",
        "verified": all(checks.values()),
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--frozen-commit", required=False)
    parser.add_argument("--build002-source-root", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--work-root", type=Path)
    parser.add_argument("--worker-timeout-seconds", type=float, default=120.0)
    parser.add_argument("--worker-config", type=Path, help=argparse.SUPPRESS)
    return parser


def _run_parent(args: argparse.Namespace) -> int:
    if not isinstance(args.frozen_commit, str) or len(args.frozen_commit) != 40:
        raise RuntimeError("--frozen-commit must name the full Build 003 commit")
    if args.build002_source_root is None or args.output is None or args.work_root is None:
        raise RuntimeError("--build002-source-root, --output, and --work-root are required")
    if args.worker_timeout_seconds <= 0.0:
        raise RuntimeError("--worker-timeout-seconds must be positive")
    output = args.output.resolve()
    work_root = args.work_root.resolve()
    if output.exists() or work_root.exists():
        raise FileExistsError("profile output and work roots must both be fresh")
    build003_source = _source_identity(args.root.resolve(), commit=args.frozen_commit)
    build002_source = _source_identity(
        args.build002_source_root.resolve(),
        commit=BUILD002_COMMIT,
        tree=BUILD002_TREE,
    )
    work_root.mkdir(parents=True, exist_ok=False)
    script = Path(__file__).resolve()
    build003_runs = [
        _spawn_measurement(
            script=script,
            source=build003_source,
            role="build003",
            repetition=repetition,
            work_root=work_root,
            timeout_seconds=float(args.worker_timeout_seconds),
        )
        for repetition in range(REPETITIONS)
    ]
    build002_runs = [
        _spawn_measurement(
            script=script,
            source=build002_source,
            role="build002",
            repetition=repetition,
            work_root=work_root,
            timeout_seconds=float(args.worker_timeout_seconds),
        )
        for repetition in range(REPETITIONS)
    ]
    comparison = _build_comparison(build003_runs, build002_runs)
    body: dict[str, object] = {
        **comparison,
        "network_enabled": False,
        "official_environment_interactions": 0,
        "public_or_holdout_inputs_read": False,
        "schema": SCHEMA,
        "source_identity": {
            "build002": build002_source,
            "build003": build003_source,
        },
    }
    receipt = _sealed(body)
    _atomic_write(output, receipt)
    sys.stdout.buffer.write(_canonical_bytes(receipt) + b"\n")
    return 0 if receipt["verified"] is True else 1


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(list(argv) if argv is not None else None)
    if args.worker_config is not None:
        return _run_worker(args.worker_config.resolve())
    try:
        return _run_parent(args)
    except (FileExistsError, OSError, RuntimeError, ValueError) as error:
        print(f"mechanical profile refused: {type(error).__name__}: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
