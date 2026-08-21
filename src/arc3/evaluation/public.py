"""Guarded public evaluation over the frozen ARC3 partition manifest.

This module is development/evaluation infrastructure.  It never exposes game
source to a policy: the only policy inputs are normalized observations and
returned consequences from :class:`~arc3.adapters.arc_agi.ArcAGIAdapter`.
"""

from __future__ import annotations

import hashlib
import importlib
import importlib.metadata
import json
import logging
import math
import os
import platform
import subprocess
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol, cast

from arc3.adapters import (
    EnvironmentDescriptor,
    EnvironmentSession,
    ScoreSummary,
)
from arc3.adapters.arc_agi import (
    ARC_AGI_VERSION,
    ARCENGINE_VERSION,
    DEFAULT_BASE_URL,
    ArcAGIAdapter,
)
from arc3.config import ARC3Config, BudgetConfig
from arc3.errors import AdapterError, EvaluationError
from arc3.trace import (
    BaselineTraceSink,
    EventJournal,
    ReplayEngine,
)
from arc3.types import ActionName, EnvironmentMode, EvaluationSurface, GameId, GameStateName

from .artifacts import (
    canonical_json_bytes,
    load_json,
    seal_object,
    sha256_bytes,
    sha256_file,
    verify_object_hash,
)
from .baselines import EvaluationPolicy, baseline_descriptor

PUBLIC_MANIFEST_SCHEMA = "arc3.public-game-partitions.v0.1"
PUBLIC_EVALUATION_SCHEMA = "arc3.public-evaluation.manifest.v0.1"
PUBLIC_RUN_SCHEMA = "arc3.public-evaluation.run.v0.1"
PUBLIC_EXPOSURE_SCHEMA = "arc3.public-exposure.event.v0.1"
_PARTITIONS = frozenset({"smoke", "development", "public-holdout"})
_SOURCE_SUFFIXES = frozenset({".json", ".py", ".toml", ".yaml", ".yml"})


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _repository_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _git_value(*arguments: str) -> str | None:
    try:
        completed = subprocess.run(
            ("git", *arguments),
            cwd=_repository_root(),
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    # An empty successful result is meaningful for commands such as
    # ``git status --porcelain``: it proves that the worktree is clean.  Keep
    # that distinct from command failure, which is represented by ``None``.
    return completed.stdout.strip()


@dataclass(frozen=True, slots=True)
class PublicGameEntry:
    """One immutable entry in the Build 000 public partition manifest."""

    game_id: str
    stable_name: str
    assignment_hash: str
    partition: str
    exposure: str
    original_partition: str | None = None


@dataclass(frozen=True, slots=True)
class PublicPartitionManifest:
    """Validated deterministic public partition declaration."""

    path: Path
    salt: str
    entries: tuple[PublicGameEntry, ...]
    digest: str

    @classmethod
    def load(cls, path: str | Path) -> PublicPartitionManifest:
        manifest_path = Path(path).resolve()
        raw = load_json(manifest_path)
        if raw.get("schema") != PUBLIC_MANIFEST_SCHEMA:
            raise EvaluationError("public partition manifest has an unsupported schema")
        assignment = raw.get("assignment")
        games = raw.get("games")
        if not isinstance(assignment, dict) or not isinstance(games, list):
            raise EvaluationError("public partition manifest is missing assignment or games")
        salt = assignment.get("salt")
        if not isinstance(salt, str) or not salt:
            raise EvaluationError("public partition manifest salt is invalid")
        entries: list[PublicGameEntry] = []
        for raw_game in games:
            if not isinstance(raw_game, dict):
                raise EvaluationError("public partition manifest contains a non-object game")
            values = {
                field: raw_game.get(field)
                for field in ("game_id", "stable_name", "assignment_hash", "partition", "exposure")
            }
            if any(not isinstance(value, str) or not value for value in values.values()):
                raise EvaluationError("public partition manifest has an invalid game entry")
            original = raw_game.get("original_partition")
            if original is not None and not isinstance(original, str):
                raise EvaluationError("public partition original_partition must be a string")
            entries.append(
                PublicGameEntry(
                    game_id=cast(str, values["game_id"]),
                    stable_name=cast(str, values["stable_name"]),
                    assignment_hash=cast(str, values["assignment_hash"]),
                    partition=cast(str, values["partition"]),
                    exposure=cast(str, values["exposure"]),
                    original_partition=original,
                )
            )
        manifest = cls(manifest_path, salt, tuple(entries), sha256_file(manifest_path))
        manifest.validate()
        return manifest

    def validate(self) -> None:
        if len(self.entries) != 25:
            raise EvaluationError("Build 000 public manifest must contain exactly 25 games")
        game_ids = [entry.game_id for entry in self.entries]
        stable_names = [entry.stable_name for entry in self.entries]
        if len(set(game_ids)) != len(game_ids) or len(set(stable_names)) != len(stable_names):
            raise EvaluationError("public partition game identities must be unique")
        for entry in self.entries:
            if entry.partition not in _PARTITIONS:
                raise EvaluationError(f"unknown public partition {entry.partition!r}")
            if not entry.game_id.startswith(f"{entry.stable_name}-"):
                raise EvaluationError("public game ID does not match its stable name")
            expected_hash = hashlib.sha256(f"{self.salt}\0{entry.stable_name}".encode()).hexdigest()
            if entry.assignment_hash != expected_hash:
                raise EvaluationError("public partition assignment hash mismatch")

        ranked = sorted(self.entries, key=lambda entry: entry.assignment_hash)
        for rank, entry in enumerate(ranked):
            expected = "smoke" if rank < 3 else "development" if rank < 14 else "public-holdout"
            if entry.partition == expected:
                if entry.original_partition is not None:
                    raise EvaluationError("unchanged partition unexpectedly records an override")
                continue
            if not (
                expected == "public-holdout"
                and entry.partition == "development"
                and entry.original_partition == "public-holdout"
                and entry.exposure != "discovery-metadata-only"
            ):
                raise EvaluationError("public partition contains an undeclared assignment override")
        counts = {
            partition: sum(entry.partition == partition for entry in self.entries)
            for partition in sorted(_PARTITIONS)
        }
        if counts != {"development": 12, "public-holdout": 10, "smoke": 3}:
            raise EvaluationError(f"public partition counts changed: {counts}")

    def games(self, partition: str) -> tuple[PublicGameEntry, ...]:
        if partition not in _PARTITIONS:
            raise EvaluationError(f"unknown public partition {partition!r}")
        return tuple(entry for entry in self.entries if entry.partition == partition)

    def compare_discovery(self, descriptors: Sequence[EnvironmentDescriptor]) -> dict[str, object]:
        """Compare metadata-only official discovery with the frozen identities."""

        discovered = {str(descriptor.game_id): descriptor for descriptor in descriptors}
        expected = {entry.game_id for entry in self.entries}
        missing = sorted(expected - set(discovered))
        extra = sorted(set(discovered) - expected)
        mismatched_names = sorted(
            entry.game_id
            for entry in self.entries
            if entry.game_id in discovered and not entry.game_id.startswith(f"{entry.stable_name}-")
        )
        return {
            "status": "PASS" if not (missing or extra or mismatched_names) else "MISMATCH",
            "manifest_sha256": self.digest,
            "manifest_count": len(self.entries),
            "discovered_count": len(descriptors),
            "missing_game_ids": missing,
            "extra_game_ids": extra,
            "mismatched_stable_names": mismatched_names,
            "metadata": [
                {
                    "game_id": game_id,
                    "title": discovered[game_id].title,
                    "tags": list(discovered[game_id].tags),
                    "baseline_actions": list(discovered[game_id].baseline_actions),
                    "locally_available": discovered[game_id].locally_available,
                }
                for game_id in sorted(discovered)
            ],
            "gameplay_observed": False,
        }


@dataclass(frozen=True, slots=True)
class LocalAssetIdentity:
    """Content identity for one cached official game without semantic inspection."""

    game_id: str
    files: tuple[tuple[str, int, str], ...]
    aggregate_sha256: str

    def to_dict(self) -> dict[str, object]:
        return {
            "game_id": self.game_id,
            "files": [
                {"name": name, "bytes": length, "sha256": digest}
                for name, length, digest in self.files
            ],
            "aggregate_sha256": self.aggregate_sha256,
            "source_semantically_inspected": False,
        }


def local_asset_identity(
    environments_dir: str | Path,
    entry: PublicGameEntry,
) -> LocalAssetIdentity | None:
    """Hash a cached official asset directory without parsing its game source."""

    _base, separator, version = entry.game_id.partition("-")
    if not separator or not version:
        raise EvaluationError(f"versioned public game ID is invalid: {entry.game_id}")
    directory = Path(environments_dir).resolve() / entry.stable_name / version
    metadata = directory / "metadata.json"
    if not metadata.is_file():
        return None
    files = tuple(
        (
            path.relative_to(directory).as_posix(),
            path.stat().st_size,
            sha256_file(path),
        )
        for path in sorted(directory.rglob("*"))
        if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc"
    )
    if not files:
        raise EvaluationError(f"cached public game has no identity files: {entry.game_id}")
    digest = sha256_bytes(canonical_json_bytes(files))
    return LocalAssetIdentity(entry.game_id, files, digest)


def inventory_local_assets(
    manifest: PublicPartitionManifest,
    environments_dir: str | Path,
) -> dict[str, LocalAssetIdentity]:
    """Return only validated manifest entries currently cached for local execution."""

    adapter = ArcAGIAdapter(
        ARC3Config.for_mode(EnvironmentMode.LOCAL, seed=0, network_enabled=False),
        environments_dir=environments_dir,
        recordings_dir=Path(environments_dir).resolve().parent / "inventory-recordings",
        environ={},
    )
    listed = {str(descriptor.game_id) for descriptor in adapter.list_games()}
    expected = {entry.game_id for entry in manifest.entries}
    unknown = listed - expected
    if unknown:
        raise EvaluationError(
            f"local cache contains games outside the frozen manifest: {sorted(unknown)}"
        )
    assets: dict[str, LocalAssetIdentity] = {}
    for entry in manifest.entries:
        identity = local_asset_identity(environments_dir, entry)
        if identity is not None:
            if entry.game_id not in listed:
                raise EvaluationError(
                    f"cached asset is not discoverable by pinned SDK: {entry.game_id}"
                )
            assets[entry.game_id] = identity
    return assets


@dataclass(frozen=True, slots=True)
class PublicEvaluationConfig:
    """Predeclared Stage 15 public comparison."""

    partition: str
    agents: tuple[str, ...]
    seeds: tuple[int, ...]
    frozen_commit: str
    max_actions: int = 80
    max_resets: int = 8
    timeout_seconds: float = 120.0
    manifest_path: Path = Path("docs/evaluation/public-game-partitions.v0.1.json")
    environments_dir: Path = Path("artifacts/stage15/public-environments")
    recordings_dir: Path = Path("artifacts/stage15/official-recordings")
    output_root: Path = Path("artifacts/stage15/evaluations")
    exposure_ledger: Path = Path("artifacts/stage15/public-exposure.jsonl")
    evaluation_id: str | None = None
    acquire_missing: bool = False
    allow_public_holdout: bool = False
    sealed_development_manifest: Path | None = None
    milestone_id: str = "build-000-stage15-v0.1"

    def __post_init__(self) -> None:
        if self.partition not in _PARTITIONS:
            raise ValueError(f"partition must be one of {sorted(_PARTITIONS)}")
        if not self.agents or len(set(self.agents)) != len(self.agents):
            raise ValueError("agents must be non-empty and unique")
        for agent in self.agents:
            baseline_descriptor(agent)
        if not self.seeds or len(set(self.seeds)) != len(self.seeds):
            raise ValueError("seeds must be non-empty and unique")
        if any(
            isinstance(seed, bool) or not isinstance(seed, int) or not -(2**63) <= seed < 2**63
            for seed in self.seeds
        ):
            raise ValueError("seeds must be signed 64-bit integers")
        for name, value in {"max_actions": self.max_actions, "max_resets": self.max_resets}.items():
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"{name} must be a positive integer")
        if (
            isinstance(self.timeout_seconds, bool)
            or not isinstance(self.timeout_seconds, (int, float))
            or not math.isfinite(self.timeout_seconds)
            or self.timeout_seconds <= 0
        ):
            raise ValueError("timeout_seconds must be finite and positive")
        if not self.frozen_commit or any(
            character not in "0123456789abcdef" for character in self.frozen_commit
        ):
            raise ValueError("frozen_commit must be a lowercase hexadecimal commit identity")
        if not self.milestone_id.strip():
            raise ValueError("milestone_id must not be empty")
        if self.evaluation_id is not None and (
            not self.evaluation_id
            or any(
                character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_"
                for character in self.evaluation_id
            )
        ):
            raise ValueError("evaluation_id contains unsupported characters")

    def declaration(self) -> dict[str, object]:
        return {
            "partition": self.partition,
            "agents": list(self.agents),
            "seeds": list(self.seeds),
            "max_actions": self.max_actions,
            "max_resets": self.max_resets,
            "timeout_seconds": self.timeout_seconds,
            "surface": self.surface,
            "network_mode": self.network_mode,
            "frozen_commit": self.frozen_commit,
            "manifest_path": self.manifest_path.resolve().as_posix(),
            "environments_dir": self.environments_dir.resolve().as_posix(),
            "recordings_dir": self.recordings_dir.resolve().as_posix(),
            "output_root": self.output_root.resolve().as_posix(),
            "exposure_ledger": self.exposure_ledger.resolve().as_posix(),
            "evaluation_id": self.evaluation_id,
            "acquire_missing": self.acquire_missing,
            "allow_public_holdout": self.allow_public_holdout,
            "milestone_id": self.milestone_id,
            "sealed_development_manifest": (
                self.sealed_development_manifest.resolve().as_posix()
                if self.sealed_development_manifest is not None
                else None
            ),
        }

    @property
    def surface(self) -> str:
        """Evidence label fixed by the declared partition protocol."""

        return "online-public" if self.partition == "public-holdout" else "local-public"

    @property
    def network_mode(self) -> str:
        """Environment transport; the policy itself remains network-disabled."""

        return (
            "official-online-one-shot"
            if self.partition == "public-holdout"
            else "offline-evaluation"
        )


class PublicExposureLedger:
    """Small append-only, hash-linked ledger of gameplay exposure boundaries."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).resolve()

    def events(self) -> tuple[dict[str, Any], ...]:
        if not self.path.exists():
            return ()
        events: list[dict[str, Any]] = []
        previous: str | None = None
        for line_number, line in enumerate(self.path.read_text(encoding="utf-8").splitlines(), 1):
            if not line:
                continue
            try:
                raw = json.loads(line)
            except json.JSONDecodeError as error:
                raise EvaluationError(f"exposure ledger line {line_number} is invalid") from error
            if not isinstance(raw, dict) or raw.get("schema") != PUBLIC_EXPOSURE_SCHEMA:
                raise EvaluationError(f"exposure ledger line {line_number} has an invalid schema")
            event = cast(dict[str, Any], raw)
            if event.get("sequence") != len(events) or event.get("previous_event_hash") != previous:
                raise EvaluationError("exposure ledger sequence/hash link is invalid")
            if not verify_object_hash(event, hash_field="event_hash"):
                raise EvaluationError("exposure ledger event hash mismatch")
            previous = cast(str, event["event_hash"])
            events.append(event)
        return tuple(events)

    def append(self, event_type: str, payload: Mapping[str, object]) -> dict[str, Any]:
        events = self.events()
        event = seal_object(
            {
                "schema": PUBLIC_EXPOSURE_SCHEMA,
                "sequence": len(events),
                "event_type": event_type,
                "occurred_at": _utc_now(),
                "payload": dict(payload),
                "previous_event_hash": events[-1]["event_hash"] if events else None,
            },
            hash_field="event_hash",
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        encoded = canonical_json_bytes(event)
        with self.path.open("ab") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        return event


def validate_frozen_source(frozen_commit: str) -> dict[str, object]:
    """Fail closed unless HEAD and the complete worktree match a frozen commit."""

    head = _git_value("rev-parse", "HEAD")
    status = _git_value("status", "--porcelain", "--untracked-files=all")
    if head is None or status is None:
        raise EvaluationError("git source identity is unavailable")
    if head != frozen_commit:
        raise EvaluationError(f"HEAD {head} does not match frozen commit {frozen_commit}")
    if status:
        raise EvaluationError("public evaluation requires a clean frozen worktree")
    return {"git_commit": head, "dirty_worktree": False}


def validate_public_gate(
    config: PublicEvaluationConfig,
    manifest: PublicPartitionManifest,
    ledger: PublicExposureLedger,
    *,
    resume_evaluation_id: str | None = None,
) -> None:
    """Enforce source freeze and the one-shot public-holdout boundary."""

    validate_frozen_source(config.frozen_commit)
    selected = manifest.games(config.partition)
    if not selected:
        raise EvaluationError("selected public partition is empty")
    if config.partition != "public-holdout":
        return
    if not config.allow_public_holdout:
        raise EvaluationError(
            "public holdout is closed; explicit milestone authorization is required"
        )
    if config.evaluation_id is None:
        raise EvaluationError("public holdout requires an explicit resumable evaluation ID")
    canonical_output = (_repository_root() / "artifacts" / "stage15" / "evaluations").resolve()
    canonical_ledger = (
        _repository_root() / "artifacts" / "stage15" / "public-exposure.jsonl"
    ).resolve()
    if (
        config.output_root.resolve() != canonical_output
        or config.exposure_ledger.resolve() != canonical_ledger
    ):
        raise EvaluationError(
            "public holdout requires the canonical evaluation root and exposure ledger"
        )
    for prior_path in canonical_output.glob("*/manifest.json"):
        try:
            prior = load_json(prior_path)
        except (OSError, EvaluationError, json.JSONDecodeError) as error:
            raise EvaluationError("prior public evaluation manifest is unreadable") from error
        if not verify_object_hash(prior, hash_field="manifest_hash"):
            raise EvaluationError("prior public evaluation manifest failed its self-hash")
        if prior.get("partition") != "public-holdout":
            continue
        if prior.get("evaluation_id") != config.evaluation_id:
            raise EvaluationError("a different public holdout evaluation already exists")
    if config.acquire_missing:
        raise EvaluationError(
            "public holdout acquisition is inseparable from its one-shot online evaluation"
        )
    development = config.sealed_development_manifest
    if development is None or not development.is_file():
        raise EvaluationError("public holdout requires a sealed development manifest")
    sealed = load_json(development)
    if sealed.get("schema") != PUBLIC_EVALUATION_SCHEMA or not verify_object_hash(
        sealed, hash_field="manifest_hash"
    ):
        raise EvaluationError("sealed development manifest failed its self-hash")
    if sealed.get("partition") != "development" or sealed.get("status") != "PASS":
        raise EvaluationError("sealed development evidence is not a passing development run")
    if (
        sealed.get("git_commit") != config.frozen_commit
        or sealed.get("public_partition_manifest_hash") != manifest.digest
        or sealed.get("surface") != "local-public"
    ):
        raise EvaluationError("sealed development evidence has a different frozen identity")
    from .public_runner import verify_public_evaluation

    verification = verify_public_evaluation(development.parent)
    if verification.get("verified") is not True:
        raise EvaluationError("sealed development artifacts failed verification")
    development_config = sealed.get("agent_config")
    if not isinstance(development_config, dict):
        raise EvaluationError("sealed development evidence has no agent declaration")
    for field in ("agents", "seeds", "max_actions", "max_resets", "timeout_seconds"):
        if development_config.get(field) != config.declaration().get(field):
            raise EvaluationError(
                f"holdout {field} does not match the sealed development declaration"
            )
    holdout_ids = {entry.game_id for entry in selected}
    for event in ledger.events():
        payload = event.get("payload")
        if not isinstance(payload, dict):
            continue
        if (
            payload.get("game_id") not in holdout_ids
            or event.get("event_type") == "metadata.discovered"
        ):
            continue
        if (
            resume_evaluation_id is not None
            and payload.get("evaluation_id") == resume_evaluation_id
        ):
            continue
        raise EvaluationError("public holdout has already been consumed in the exposure ledger")


class _ArcadeLike(Protocol):
    operation_mode: object

    def make(self, game_id: str, **kwargs: object) -> _AcquiredWrapperLike | None: ...

    def close_scorecard(self, scorecard_id: str | None = None) -> object | None: ...


class _AcquiredWrapperLike(Protocol):
    observation_space: object | None
    scorecard_id: str


def _silent_logger() -> logging.Logger:
    logger = logging.getLogger("arc3.stage15.official-acquisition")
    logger.handlers.clear()
    logger.addHandler(logging.NullHandler())
    logger.setLevel(logging.CRITICAL + 1)
    logger.propagate = False
    return logger


def acquire_local_public_asset(
    game_id: str,
    *,
    seed: int,
    environments_dir: str | Path,
    recordings_dir: str | Path,
    base_url: str = DEFAULT_BASE_URL,
) -> None:
    """Use the pinned official NORMAL path to cache and initialize one declared game.

    This operation uses anonymous or already configured official access, opens an
    initial observation, and therefore must be recorded as gameplay exposure.
    It never returns or parses the downloaded source.
    """

    try:
        if importlib.metadata.version("arc-agi") != ARC_AGI_VERSION:
            raise EvaluationError("arc-agi version changed before public acquisition")
        if importlib.metadata.version("arcengine") != ARCENGINE_VERSION:
            raise EvaluationError("arcengine version changed before public acquisition")
        arc_agi = importlib.import_module("arc_agi")
        arcade_type = arc_agi.Arcade
        operation_mode_type = arc_agi.OperationMode
        normal_mode = operation_mode_type.NORMAL
    except (AttributeError, ImportError, importlib.metadata.PackageNotFoundError) as error:
        raise EvaluationError("pinned official acquisition surface is unavailable") from error
    inherited_mode = os.environ.get("OPERATION_MODE", "").strip().lower()
    if inherited_mode and inherited_mode != "normal":
        raise EvaluationError("OPERATION_MODE would override the official acquisition mode")
    try:
        arcade = cast(
            _ArcadeLike,
            arcade_type(
                arc_api_key=os.environ.get("ARC_API_KEY", ""),
                arc_base_url=base_url,
                operation_mode=normal_mode,
                environments_dir=str(Path(environments_dir).resolve()),
                recordings_dir=str(Path(recordings_dir).resolve()),
                logger=_silent_logger(),
            ),
        )
        if str(getattr(arcade.operation_mode, "value", arcade.operation_mode)) != "normal":
            raise EvaluationError("official SDK did not retain NORMAL acquisition mode")
        wrapper = arcade.make(
            game_id,
            seed=seed,
            save_recording=False,
            include_frame_data=True,
        )
        if wrapper is None or wrapper.observation_space is None:
            raise EvaluationError("official SDK did not acquire an initial local observation")
        returned_game_id = getattr(wrapper.observation_space, "game_id", None)
        if returned_game_id != game_id:
            raise EvaluationError("acquired observation game identity mismatch")
        arcade.close_scorecard(wrapper.scorecard_id)
    except EvaluationError:
        raise
    except Exception as error:
        raise AdapterError(
            f"official public acquisition failed ({type(error).__name__}); upstream details suppressed"
        ) from None


def _first_party_source_hash() -> str:
    root = _repository_root()
    candidates: list[Path] = []
    for directory in (root / "src" / "arc3", root / "agent"):
        candidates.extend(
            path
            for path in directory.rglob("*")
            if path.is_file()
            and path.suffix.lower() in _SOURCE_SUFFIXES
            and "__pycache__" not in path.parts
        )
    for relative in ("pyproject.toml", "uv.lock"):
        path = root / relative
        if path.is_file():
            candidates.append(path)
    entries = [
        {"path": path.relative_to(root).as_posix(), "sha256": sha256_file(path)}
        for path in sorted(set(candidates))
    ]
    return sha256_bytes(canonical_json_bytes(entries))


def _hardware() -> dict[str, object]:
    return {
        "cpu": platform.processor() or platform.machine() or None,
        "cpu_count": os.cpu_count(),
        "gpu": None,
        "gpu_reason": "the symbolic local-public harness does not require a GPU",
        "ram_gb": None,
        "ram_reason": "whole-process RSS is measured separately in Stage 16",
    }


def _percentile(values: Sequence[float], quantile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(quantile * len(ordered)) - 1)]


def _score_payload(
    scorecard: ScoreSummary | None,
    *,
    expected_game_id: str | None = None,
    expected_surface: EvaluationSurface = EvaluationSurface.LOCAL_PUBLIC,
) -> dict[str, object]:
    if scorecard is None:
        return {
            "scorer": None,
            "verified": False,
            "score": 0.0,
            "official_rhae": None,
            "official_rhae_reason": (
                f"no official {expected_surface.value} scorecard was returned"
            ),
            "levels_completed": 0,
            "completed": False,
            "official_run_game_id": None,
            "official_run_actions": None,
            "official_run_resets": None,
            "official_run_state": None,
            "level_scores": [],
            "level_actions": [],
            "level_human_baseline_actions": [],
        }
    if scorecard.surface is not expected_surface:
        raise EvaluationError("official scorecard returned an unexpected evaluation surface")
    if not scorecard.verified:
        raise EvaluationError("official local scorecard was not marked verified by the adapter")
    if len(scorecard.runs) != 1:
        raise EvaluationError("official local scorecard must contain exactly one run")
    run = scorecard.runs[0]
    if expected_game_id is not None and str(run.game_id) != expected_game_id:
        raise EvaluationError("official scorecard game identity does not match the run declaration")
    baselines = list(run.level_baseline_actions)
    return {
        "scorer": scorecard.scorer,
        "verified": scorecard.verified,
        "score": scorecard.score,
        "official_rhae": None,
        "official_rhae_reason": (
            f"pinned official {expected_surface.value} scorecard is authoritative for this "
            "public result but does not "
            "identify a standalone raw/capped/weighted RHAE field"
        ),
        "levels_completed": run.levels_completed,
        "completed": run.completed,
        "official_run_game_id": str(run.game_id),
        "official_run_actions": run.actions,
        "official_run_resets": run.resets,
        "official_run_state": run.state.value,
        "level_scores": list(run.level_scores),
        "level_actions": list(run.level_actions),
        "level_human_baseline_actions": baselines,
    }


def _trace_receipt(trace_path: Path, *, run_id: str, relative_path: str) -> dict[str, object]:
    journal = EventJournal(trace_path, run_id=run_id, fsync_on_flush=False)
    try:
        if journal.active_path.is_file() and journal.active_path.stat().st_size:
            journal.seal()
        events = ReplayEngine(journal).verify_integrity(verify_blobs=True)
        counts: dict[str, int] = {}
        environment_actions = 0
        resets = 0
        for event in events:
            counts[event.event_type] = counts.get(event.event_type, 0) + 1
            if event.event_type == "consequence.received":
                action = event.payload.get("action")
                name = action.get("name") if isinstance(action, dict) else None
                if name == ActionName.RESET.value:
                    resets += 1
                else:
                    environment_actions += 1
        receipt: dict[str, object] = {
            "schema": "arc3.evaluation.trace-receipt.v0.1",
            "path": relative_path,
            "run_id": run_id,
            "event_count": len(events),
            "submitted_action_count": counts.get("action.submitted", 0),
            "consequence_count": counts.get("consequence.received", 0),
            "environment_action_count": environment_actions,
            "reset_count": resets,
            "trace_manifest_hash": journal.manifest.manifest_hash,
            "tail_event_hash": events[-1].event_hash if events else None,
            "event_type_counts": counts,
            "replay_verified": True,
        }
    finally:
        journal.close()
    receipt["byte_length"] = sum(
        path.stat().st_size for path in trace_path.rglob("*") if path.is_file()
    )
    return receipt


def _run_id(game_id: str, agent: str, seed: int) -> str:
    safe_seed = str(seed).replace("-", "neg")
    return f"{game_id}-{baseline_descriptor(agent).baseline_id}-{agent}-seed-{safe_seed}"


def _run_context(spec: Mapping[str, object]) -> object:
    from arc3.policy import RunContext

    timeout = float(cast(float | int, spec["timeout_seconds"]))
    budgets = BudgetConfig(
        max_actions=int(cast(int, spec["max_actions"])),
        max_resets=int(cast(int, spec["max_resets"])),
        decision_seconds=max(0.001, min(5.0, timeout)),
        wall_clock_seconds=timeout,
    )
    config = ARC3Config.for_mode(
        EnvironmentMode.LOCAL,
        seed=int(cast(int, spec["seed"])),
        network_enabled=False,
        profile="stage15-local-public",
        budgets=budgets,
    )
    return RunContext(
        run_id=str(spec["run_id"]),
        episode_id=f"episode:{spec['run_id']}",
        game_id=GameId(str(spec["game_id"])),
        trace_root=Path(str(spec["trace_path"])),
        checkpoint_root=Path(str(spec["checkpoint_path"])),
        config=config,
        git_commit=str(spec["git_commit"]),
        source_kind="arc3-stage15-local-public",
        source_version="0.1",
    )


def run_public_episode(
    session: EnvironmentSession,
    policy: EvaluationPolicy,
    *,
    max_actions: int,
    max_resets: int,
    trace_sink: BaselineTraceSink | None = None,
) -> tuple[ScoreSummary | None, dict[str, object]]:
    """Execute one normalized official session with no game-specific behavior."""

    observation = session.observation
    state_visits = [f"{observation.state.value}:{observation.frames[-1].digest}"]
    no_op_keys: set[tuple[str, str]] = set()
    repeated_no_ops = 0
    invalid_actions = 0
    coordinate_actions = 0
    coordinate_hits = 0
    resets = 0
    actions = 0
    game_over_events = 0
    latencies: list[float] = []
    first_progress: float | None = None
    actions_to_first_level: int | None = None
    started = time.perf_counter()
    if trace_sink is not None:
        trace_sink.record_observation(observation)
    while actions < max_actions:
        if observation.state is GameStateName.WIN:
            break
        if trace_sink is not None:
            trace_sink.record_candidates(observation)
        decision_started = time.perf_counter()
        action = policy.select(observation)
        latencies.append(time.perf_counter() - decision_started)
        if trace_sink is not None:
            trace_sink.record_selected(observation, action)
        if action.name is ActionName.RESET and resets >= max_resets:
            break
        before = observation
        if trace_sink is not None:
            trace_sink.record_submitted(before, action)
        try:
            observation = session.step(
                action,
                reasoning={
                    "category": "stage15-local-public",
                    "summary": "generic typed policy selection; no game-specific rule",
                },
            )
        except Exception:
            invalid_actions += 1
            raise
        policy.accept_consequence(observation)
        if trace_sink is not None:
            trace_sink.record_consequence(before, action, observation)
            trace_sink.record_observation(observation)
        if action.name is ActionName.RESET:
            resets += 1
        else:
            actions += 1
        before_hash = str(before.frames[-1].digest)
        after_hash = str(observation.frames[-1].digest)
        changed = (
            before_hash != after_hash or observation.levels_completed > before.levels_completed
        )
        if not changed and action.name is not ActionName.RESET:
            key = (before_hash, repr(action))
            repeated_no_ops += int(key in no_op_keys)
            no_op_keys.add(key)
        if action.name is ActionName.ACTION6:
            coordinate_actions += 1
            coordinate_hits += int(changed)
        game_over_events += int(observation.state is GameStateName.GAME_OVER)
        if observation.levels_completed > before.levels_completed and first_progress is None:
            first_progress = time.perf_counter() - started
            actions_to_first_level = actions
        state_visits.append(f"{observation.state.value}:{after_hash}")
    scorecard = session.close()
    unique_states = len(set(state_visits))
    metrics: dict[str, object] = {
        "environment_actions": actions,
        "resets": resets,
        "game_over_events": game_over_events,
        "time_to_first_progress_seconds": first_progress,
        "actions_to_first_completed_level": actions_to_first_level,
        "repeated_no_op_rate": repeated_no_ops / actions if actions else 0.0,
        "invalid_action_rate": invalid_actions / max(1, actions + invalid_actions),
        "coordinate_action_hit_rate": (
            coordinate_hits / coordinate_actions if coordinate_actions else None
        ),
        "unique_state_count": unique_states,
        "state_revisitation_rate": (len(state_visits) - unique_states) / len(state_visits),
        "decision_latency_seconds": {
            "p50": _percentile(latencies, 0.50),
            "p95": _percentile(latencies, 0.95),
            "p99": _percentile(latencies, 0.99),
        },
        "total_wall_clock_seconds": time.perf_counter() - started,
        "final_state": observation.state.value,
        "final_frame_hash": str(observation.frames[-1].digest),
    }
    return scorecard, metrics
