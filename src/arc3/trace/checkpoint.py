"""Versioned derived-state checkpoints tied to an exact trace tail."""

from __future__ import annotations

import os
import random
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from arc3.errors import ARC3ValidationError, CheckpointError
from arc3.types import JSONValue

from .canonical import (
    canonical_bytes,
    normalize_json,
    parse_json_bytes,
    require_object,
    require_sha256,
    sha256_json,
)
from .schema import CHECKPOINT_SCHEMA, CodeIdentity, SourceIdentity

if TYPE_CHECKING:
    from .journal import EventJournal


@dataclass(frozen=True, slots=True)
class CheckpointEnvelope:
    """A validated snapshot whose authority is bounded by its trace position."""

    run_id: str
    episode_id: str
    trace_tail_event_id: str
    trace_tail_hash: str
    git_commit: str
    config_hash: str
    rng_state: JSONValue
    state: dict[str, JSONValue]
    checkpoint_hash: str
    schema: str = CHECKPOINT_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != CHECKPOINT_SCHEMA:
            raise CheckpointError(f"unsupported checkpoint schema: {self.schema!r}")
        for field_name, value in {
            "run_id": self.run_id,
            "episode_id": self.episode_id,
            "trace_tail_event_id": self.trace_tail_event_id,
            "git_commit": self.git_commit,
        }.items():
            if not value:
                raise CheckpointError(f"{field_name} must be non-empty")
        try:
            require_sha256(self.trace_tail_hash, field="trace_tail_hash")
            require_sha256(self.config_hash, field="config_hash")
            require_sha256(self.checkpoint_hash, field="checkpoint_hash")
        except ARC3ValidationError as error:
            raise CheckpointError(str(error)) from error
        normalized_state = normalize_json(self.state)
        if not isinstance(normalized_state, dict):  # pragma: no cover - static invariant
            raise CheckpointError("checkpoint state must be an object")
        object.__setattr__(self, "state", normalized_state)
        normalized_rng = normalize_json(self.rng_state)
        _decode_rng_state(normalized_rng)
        object.__setattr__(self, "rng_state", normalized_rng)

    def to_dict(self, *, include_hash: bool = True) -> dict[str, JSONValue]:
        result: dict[str, JSONValue] = {
            "schema": self.schema,
            "run_id": self.run_id,
            "episode_id": self.episode_id,
            "trace_tail_event_id": self.trace_tail_event_id,
            "trace_tail_hash": self.trace_tail_hash,
            "git_commit": self.git_commit,
            "config_hash": self.config_hash,
            "rng_state": self.rng_state,
            "state": self.state,
        }
        if include_hash:
            result["checkpoint_hash"] = self.checkpoint_hash
        return result

    def computed_hash(self) -> str:
        return sha256_json(self.to_dict(include_hash=False))

    def verify_hash(self) -> None:
        computed = self.computed_hash()
        if computed != self.checkpoint_hash:
            raise CheckpointError(
                f"checkpoint hash mismatch: stored {self.checkpoint_hash}, computed {computed}"
            )

    @classmethod
    def create(
        cls,
        *,
        run_id: str,
        episode_id: str,
        trace_tail_event_id: str,
        trace_tail_hash: str,
        git_commit: str,
        config_hash: str,
        rng: random.Random,
        state: Mapping[str, object],
    ) -> CheckpointEnvelope:
        normalized_state = normalize_json(state)
        if not isinstance(normalized_state, dict):  # pragma: no cover - Mapping invariant
            raise CheckpointError("checkpoint state must be an object")
        rng_state = normalize_json(rng.getstate())
        raw = cls(
            run_id=run_id,
            episode_id=episode_id,
            trace_tail_event_id=trace_tail_event_id,
            trace_tail_hash=trace_tail_hash,
            git_commit=git_commit,
            config_hash=config_hash,
            rng_state=rng_state,
            state=normalized_state,
            checkpoint_hash="sha256:" + "0" * 64,
        )
        return cls(
            run_id=raw.run_id,
            episode_id=raw.episode_id,
            trace_tail_event_id=raw.trace_tail_event_id,
            trace_tail_hash=raw.trace_tail_hash,
            git_commit=raw.git_commit,
            config_hash=raw.config_hash,
            rng_state=raw.rng_state,
            state=raw.state,
            checkpoint_hash=raw.computed_hash(),
        )

    @classmethod
    def from_dict(cls, raw: Mapping[str, object]) -> CheckpointEnvelope:
        normalized = normalize_json(raw)
        if not isinstance(normalized, dict):  # pragma: no cover - Mapping invariant
            raise CheckpointError("checkpoint must be an object")

        def text(key: str) -> str:
            value = normalized.get(key)
            if not isinstance(value, str) or not value:
                raise CheckpointError(f"checkpoint {key} must be a non-empty string")
            return value

        envelope = cls(
            schema=text("schema"),
            run_id=text("run_id"),
            episode_id=text("episode_id"),
            trace_tail_event_id=text("trace_tail_event_id"),
            trace_tail_hash=text("trace_tail_hash"),
            git_commit=text("git_commit"),
            config_hash=text("config_hash"),
            rng_state=normalized.get("rng_state"),
            state=require_object(normalized.get("state"), field="checkpoint state"),
            checkpoint_hash=text("checkpoint_hash"),
        )
        envelope.verify_hash()
        return envelope


@dataclass(frozen=True, slots=True)
class RestoredCheckpoint:
    """Validated state plus an RNG positioned exactly at snapshot time."""

    envelope: CheckpointEnvelope
    rng: random.Random

    @property
    def state(self) -> dict[str, JSONValue]:
        return self.envelope.state


def _decode_rng_state(value: JSONValue) -> tuple[int, tuple[int, ...], float | None]:
    if not isinstance(value, list) or len(value) != 3:
        raise CheckpointError("rng_state must be the three-part Python random state")
    version, internal, gauss = value
    if isinstance(version, bool) or not isinstance(version, int):
        raise CheckpointError("rng_state version must be an integer")
    if not isinstance(internal, list) or not internal:
        raise CheckpointError("rng_state internal state must be a non-empty array")
    if any(isinstance(item, bool) or not isinstance(item, int) for item in internal):
        raise CheckpointError("rng_state internal values must be integers")
    if gauss is not None and (isinstance(gauss, bool) or not isinstance(gauss, (int, float))):
        raise CheckpointError("rng_state Gaussian cache must be numeric or null")
    return (
        version,
        tuple(item for item in internal if isinstance(item, int) and not isinstance(item, bool)),
        float(gauss) if gauss is not None else None,
    )


def validate_checkpoint(
    envelope: CheckpointEnvelope,
    *,
    expected_run_id: str,
    expected_episode_id: str,
    expected_trace_tail_event_id: str,
    expected_trace_tail_hash: str,
    expected_git_commit: str,
    expected_config_hash: str,
) -> None:
    """Apply the exact-identity restore policy required by Trace v0.1."""

    envelope.verify_hash()
    expected = {
        "run_id": expected_run_id,
        "episode_id": expected_episode_id,
        "trace_tail_event_id": expected_trace_tail_event_id,
        "trace_tail_hash": expected_trace_tail_hash,
        "git_commit": expected_git_commit,
        "config_hash": expected_config_hash,
    }
    observed = {
        "run_id": envelope.run_id,
        "episode_id": envelope.episode_id,
        "trace_tail_event_id": envelope.trace_tail_event_id,
        "trace_tail_hash": envelope.trace_tail_hash,
        "git_commit": envelope.git_commit,
        "config_hash": envelope.config_hash,
    }
    mismatches = [key for key in expected if expected[key] != observed[key]]
    if mismatches:
        details = ", ".join(
            f"{key}: expected {expected[key]!r}, observed {observed[key]!r}" for key in mismatches
        )
        raise CheckpointError(f"checkpoint identity mismatch ({details})")


class CheckpointStore:
    """Write immutable checkpoint files and a replaceable ``latest`` pointer."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.latest_path = self.root / "latest.json"

    def content_addressed_path(self, checkpoint_hash: str) -> Path:
        """Resolve an immutable checkpoint identity without trusting ``latest``."""

        require_sha256(checkpoint_hash, field="checkpoint_hash")
        return self.root / f"checkpoint-{checkpoint_hash.removeprefix('sha256:')}.json"

    @staticmethod
    def _write_atomic(path: Path, content: bytes) -> None:
        temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        try:
            with temporary.open("xb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)

    def write(
        self,
        *,
        run_id: str,
        episode_id: str,
        trace_tail_event_id: str,
        trace_tail_hash: str,
        git_commit: str,
        config_hash: str,
        rng: random.Random,
        state: Mapping[str, object],
    ) -> tuple[Path, CheckpointEnvelope]:
        """Write a content-addressed snapshot and update the local latest copy."""

        envelope = CheckpointEnvelope.create(
            run_id=run_id,
            episode_id=episode_id,
            trace_tail_event_id=trace_tail_event_id,
            trace_tail_hash=trace_tail_hash,
            git_commit=git_commit,
            config_hash=config_hash,
            rng=rng,
            state=state,
        )
        content = canonical_bytes(envelope.to_dict()) + b"\n"
        immutable_path = self.content_addressed_path(envelope.checkpoint_hash)
        if immutable_path.exists():
            if immutable_path.read_bytes() != content:
                raise CheckpointError("content-addressed checkpoint collision")
        else:
            self._write_atomic(immutable_path, content)
        self._write_atomic(self.latest_path, content)
        return immutable_path, envelope

    def load(self, path: str | Path | None = None) -> CheckpointEnvelope:
        """Load and hash-validate a checkpoint without applying compatibility."""

        checkpoint_path = self.latest_path if path is None else Path(path)
        try:
            parsed = require_object(
                parse_json_bytes(checkpoint_path.read_bytes()), field="checkpoint"
            )
            return CheckpointEnvelope.from_dict(parsed)
        except FileNotFoundError as error:
            raise CheckpointError(f"checkpoint file does not exist: {checkpoint_path}") from error
        except ARC3ValidationError as error:
            raise CheckpointError(f"invalid checkpoint JSON: {error}") from error

    def restore(
        self,
        *,
        expected_run_id: str,
        expected_episode_id: str,
        expected_trace_tail_event_id: str,
        expected_trace_tail_hash: str,
        expected_git_commit: str,
        expected_config_hash: str,
        path: str | Path | None = None,
    ) -> RestoredCheckpoint:
        """Validate all identities and restore deterministic RNG state."""

        envelope = self.load(path)
        validate_checkpoint(
            envelope,
            expected_run_id=expected_run_id,
            expected_episode_id=expected_episode_id,
            expected_trace_tail_event_id=expected_trace_tail_event_id,
            expected_trace_tail_hash=expected_trace_tail_hash,
            expected_git_commit=expected_git_commit,
            expected_config_hash=expected_config_hash,
        )
        rng = random.Random()
        rng.setstate(_decode_rng_state(envelope.rng_state))
        return RestoredCheckpoint(envelope=envelope, rng=rng)

    def restore_with_journal_receipt(
        self,
        *,
        journal: EventJournal,
        episode_id: str,
        game_id: str,
        level_index: int,
        step_index: int,
        source: SourceIdentity,
        code_identity: CodeIdentity,
        path: str | Path | None = None,
    ) -> RestoredCheckpoint | None:
        """Restore at the current tail, recording success or rejection immutably.

        A rejected checkpoint file is never changed or deleted.  ``None`` tells
        the caller to initialize fresh derived state from the verified journal.
        """

        tail_event_id = journal.tail_event_id
        tail_hash = journal.tail_hash
        if tail_event_id is None or tail_hash is None:
            raise CheckpointError("cannot restore a checkpoint against an empty journal")
        try:
            restored = self.restore(
                path=path,
                expected_run_id=journal.run_id,
                expected_episode_id=episode_id,
                expected_trace_tail_event_id=tail_event_id,
                expected_trace_tail_hash=tail_hash,
                expected_git_commit=code_identity.git_commit,
                expected_config_hash=code_identity.config_hash,
            )
        except CheckpointError as error:
            reason = (
                "checkpoint_hash_invalid"
                if "hash mismatch" in str(error)
                else "checkpoint_identity_incompatible"
            )
            journal.append(
                episode_id=episode_id,
                game_id=game_id,
                level_index=level_index,
                step_index=step_index,
                event_type="run.checkpoint_rejected",
                source=source,
                scope="run",
                payload={
                    "checkpoint_file": (self.latest_path if path is None else Path(path)).name,
                    "reason_category": reason,
                    "preserved": True,
                },
                code_identity=code_identity,
            )
            return None
        journal.append(
            episode_id=episode_id,
            game_id=game_id,
            level_index=level_index,
            step_index=step_index,
            event_type="run.checkpoint_restored",
            source=source,
            scope="run",
            payload={
                "checkpoint_hash": restored.envelope.checkpoint_hash,
                "restored_trace_tail_event_id": restored.envelope.trace_tail_event_id,
            },
            code_identity=code_identity,
        )
        return restored


# Readable downstream alias.
CheckpointManager = CheckpointStore
