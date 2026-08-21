"""Offline trace verification, frame reconstruction, deltas, and summaries."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from arc3.errors import ARC3ValidationError, ReplayError, TraceIntegrityError
from arc3.types import JSONValue

from .blob import BlobStore
from .canonical import canonical_bytes, normalize_json, require_sha256, sha256_bytes
from .index import DerivedIndex, rebuild_index
from .journal import EventJournal
from .schema import SUMMARY_SCHEMA, TraceEvent, utc_now


@dataclass(frozen=True, slots=True)
class CellChange:
    x: int
    y: int
    before: int
    after: int

    def to_dict(self) -> dict[str, JSONValue]:
        return {"x": self.x, "y": self.y, "before": self.before, "after": self.after}


@dataclass(frozen=True, slots=True)
class FrameDelta:
    """A directly measured cell-level difference, not an object interpretation."""

    before_frame_hash: str
    after_frame_hash: str
    changed_cell_count: int
    changed_bbox: tuple[int, int, int, int] | None
    cell_changes: tuple[CellChange, ...]
    apparent_noop: bool

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "before_frame_hash": self.before_frame_hash,
            "after_frame_hash": self.after_frame_hash,
            "changed_cell_count": self.changed_cell_count,
            "changed_bbox": list(self.changed_bbox) if self.changed_bbox is not None else None,
            "cell_changes": [change.to_dict() for change in self.cell_changes],
            "component_changes": [],
            "metadata_changes": {},
            "apparent_noop": self.apparent_noop,
        }


@dataclass(frozen=True, slots=True)
class ReplayedFrame:
    event_id: str
    episode_id: str
    level_index: int
    step_index: int
    frame_hash: str
    frame: tuple[tuple[int, ...], ...]


@dataclass(frozen=True, slots=True)
class DecisionInputs:
    """Concise recorded policy inputs; never an inferred reasoning transcript."""

    action_event_id: str
    observation_event_id: str | None
    episode_id: str
    level_index: int
    step_index: int
    selected_action: dict[str, JSONValue]
    candidate_utilities: tuple[JSONValue, ...]
    selected_probe_or_plan_id: str | None
    active_hypothesis_ids: tuple[str, ...]
    predicted_outcome_ids: tuple[str, ...]
    active_goal_ids: tuple[str, ...]
    active_world_model_ids: tuple[str, ...]
    rationale_category: str
    rationale_summary: str | None


@dataclass(frozen=True, slots=True)
class SummaryClaim:
    """A bounded derived claim with both supporting and contrary receipts."""

    claim: JSONValue
    supporting_event_ids: tuple[str, ...]
    contradicting_event_ids: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "claim": self.claim,
            "supporting_event_ids": list(self.supporting_event_ids),
            "contradicting_event_ids": list(self.contradicting_event_ids),
        }


@dataclass(frozen=True, slots=True)
class TraceSummary:
    """Replaceable summary whose source range and generator are explicit."""

    source_event_start_id: str
    source_event_end_id: str
    source_chunk_hashes: tuple[str, ...]
    generated_at: str
    generator_git_commit: str
    generator_config_hash: str
    claims: tuple[SummaryClaim, ...]
    unresolved_residuals: tuple[JSONValue, ...]
    retrieval_tags: tuple[str, ...]
    schema: str = SUMMARY_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != SUMMARY_SCHEMA:
            raise ReplayError(f"unsupported summary schema: {self.schema!r}")
        if not self.source_event_start_id or not self.source_event_end_id:
            raise ReplayError("summary must cite a non-empty source event range")
        if not self.source_chunk_hashes:
            raise ReplayError("summary must cite at least one source chunk hash")
        for chunk_hash in self.source_chunk_hashes:
            try:
                require_sha256(chunk_hash, field="source_chunk_hash")
            except ARC3ValidationError as error:
                raise ReplayError(str(error)) from error
        if not self.generator_git_commit:
            raise ReplayError("summary generator git commit must be non-empty")
        try:
            require_sha256(self.generator_config_hash, field="generator_config_hash")
        except ARC3ValidationError as error:
            raise ReplayError(str(error)) from error
        for tag in self.retrieval_tags:
            if not tag:
                raise ReplayError("summary retrieval tags must be non-empty")

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "schema": self.schema,
            "source_event_start_id": self.source_event_start_id,
            "source_event_end_id": self.source_event_end_id,
            "source_chunk_hashes": list(self.source_chunk_hashes),
            "generated_at": self.generated_at,
            "generator": {
                "git_commit": self.generator_git_commit,
                "config_hash": self.generator_config_hash,
            },
            "claims": [claim.to_dict() for claim in self.claims],
            "unresolved_residuals": list(self.unresolved_residuals),
            "retrieval_tags": list(self.retrieval_tags),
        }


def compute_frame_delta(
    before: Sequence[Sequence[int]],
    after: Sequence[Sequence[int]],
) -> FrameDelta:
    """Measure a same-sized frame transition with no object-level inference."""

    before_rows = tuple(tuple(row) for row in before)
    after_rows = tuple(tuple(row) for row in after)
    if not before_rows or not after_rows:
        raise ReplayError("delta frames must not be empty")
    if len(before_rows) != len(after_rows) or any(
        len(before_row) != len(after_row)
        for before_row, after_row in zip(before_rows, after_rows, strict=True)
    ):
        raise ReplayError("delta frames must have identical dimensions")
    if any(len(row) != len(before_rows[0]) for row in before_rows) or any(
        len(row) != len(after_rows[0]) for row in after_rows
    ):
        raise ReplayError("delta frames must be rectangular")
    before_hash = sha256_bytes(canonical_bytes([list(row) for row in before_rows]))
    after_hash = sha256_bytes(canonical_bytes([list(row) for row in after_rows]))
    changes: list[CellChange] = []
    for y, (before_row, after_row) in enumerate(zip(before_rows, after_rows, strict=True)):
        for x, (before_cell, after_cell) in enumerate(zip(before_row, after_row, strict=True)):
            if before_cell != after_cell:
                changes.append(CellChange(x=x, y=y, before=before_cell, after=after_cell))
    if changes:
        xs = [change.x for change in changes]
        ys = [change.y for change in changes]
        bbox: tuple[int, int, int, int] | None = (min(xs), min(ys), max(xs), max(ys))
    else:
        bbox = None
    return FrameDelta(
        before_frame_hash=before_hash,
        after_frame_hash=after_hash,
        changed_cell_count=len(changes),
        changed_bbox=bbox,
        cell_changes=tuple(changes),
        apparent_noop=not changes,
    )


def apply_frame_delta(
    before: Sequence[Sequence[int]], delta: FrameDelta
) -> tuple[tuple[int, ...], ...]:
    """Apply a measured delta while rejecting a mismatched base frame."""

    mutable = [list(row) for row in before]
    observed_before_hash = sha256_bytes(canonical_bytes(mutable))
    if observed_before_hash != delta.before_frame_hash:
        raise ReplayError("delta base frame hash mismatch")
    for change in delta.cell_changes:
        try:
            current = mutable[change.y][change.x]
        except IndexError as error:
            raise ReplayError("delta cell coordinate is outside the base frame") from error
        if current != change.before:
            raise ReplayError("delta cell precondition does not match the base frame")
        mutable[change.y][change.x] = change.after
    observed_after_hash = sha256_bytes(canonical_bytes(mutable))
    if observed_after_hash != delta.after_frame_hash:
        raise ReplayError("delta result frame hash mismatch")
    return tuple(tuple(row) for row in mutable)


class ReplayEngine:
    """Audit and reconstruct a journal entirely offline."""

    def __init__(self, journal: EventJournal, blob_store: BlobStore | None = None) -> None:
        self.journal = journal
        self.blobs = blob_store or journal.blobs

    def verify_integrity(self, *, verify_blobs: bool = True) -> tuple[TraceEvent, ...]:
        events = self.journal.verify_manifest()
        if verify_blobs:
            self.journal.verify_referenced_blobs()
        return events

    def rebuild_index(self) -> DerivedIndex:
        return rebuild_index(self.verify_integrity())

    def replay_frames(self) -> tuple[ReplayedFrame, ...]:
        """Load exact observation frames and verify descriptor identities."""

        replayed: list[ReplayedFrame] = []
        for event in self.verify_integrity():
            if event.event_type != "observation.received":
                continue
            raw_frames = event.payload.get("frames")
            if not isinstance(raw_frames, list):  # validated at envelope creation
                raise ReplayError(f"observation {event.event_id} has no frames array")
            for raw_descriptor in raw_frames:
                if not isinstance(raw_descriptor, dict):
                    raise ReplayError("frame descriptor is not an object")
                blob_hash = raw_descriptor.get("blob_hash")
                frame_hash = raw_descriptor.get("frame_hash")
                width = raw_descriptor.get("width")
                height = raw_descriptor.get("height")
                if not isinstance(blob_hash, str) or not isinstance(frame_hash, str):
                    raise ReplayError("frame descriptor hashes are invalid")
                frame = self.blobs.get_frame(blob_hash)
                observed_hash = sha256_bytes(canonical_bytes([list(row) for row in frame]))
                if observed_hash != frame_hash:
                    raise TraceIntegrityError(
                        f"frame semantic hash mismatch in event {event.event_id}"
                    )
                if width != len(frame[0]) or height != len(frame):
                    raise TraceIntegrityError(
                        f"frame dimensions mismatch in event {event.event_id}"
                    )
                replayed.append(
                    ReplayedFrame(
                        event_id=event.event_id,
                        episode_id=event.episode_id,
                        level_index=event.level_index,
                        step_index=event.step_index,
                        frame_hash=frame_hash,
                        frame=frame,
                    )
                )
        return tuple(replayed)

    def rebuild_deltas(self) -> tuple[FrameDelta, ...]:
        """Recompute deltas between consecutive first frames in each level."""

        latest: dict[tuple[str, int], ReplayedFrame] = {}
        deltas: list[FrameDelta] = []
        for receipt in self.replay_frames():
            key = (receipt.episode_id, receipt.level_index)
            prior = latest.get(key)
            if prior is not None:
                deltas.append(compute_frame_delta(prior.frame, receipt.frame))
            latest[key] = receipt
        return tuple(deltas)

    def decision_inputs(
        self,
        *,
        step_index: int,
        episode_id: str | None = None,
    ) -> tuple[DecisionInputs, ...]:
        """Recover the concise, explicit inputs recorded for action selection."""

        events = self.verify_integrity(verify_blobs=False)
        prior_observation: dict[tuple[str, int], str] = {}
        decisions: list[DecisionInputs] = []
        for event in events:
            level_key = (event.episode_id, event.level_index)
            if event.event_type == "observation.received":
                prior_observation[level_key] = event.event_id
            if event.event_type != "action.selected" or event.step_index != step_index:
                continue
            if episode_id is not None and event.episode_id != episode_id:
                continue
            payload = event.payload
            selected_action = payload.get("selected_action")
            candidate_utilities = payload.get("candidate_utilities")
            active_hypotheses = payload.get("active_hypothesis_ids")
            predictions = payload.get("predicted_outcome_ids")
            if not isinstance(selected_action, dict) or not isinstance(candidate_utilities, list):
                raise ReplayError("validated action.selected payload is unavailable")
            if not isinstance(active_hypotheses, list) or not isinstance(predictions, list):
                raise ReplayError("validated action.selected identifiers are unavailable")
            decisions.append(
                DecisionInputs(
                    action_event_id=event.event_id,
                    observation_event_id=prior_observation.get(level_key),
                    episode_id=event.episode_id,
                    level_index=event.level_index,
                    step_index=event.step_index,
                    selected_action=selected_action,
                    candidate_utilities=tuple(candidate_utilities),
                    selected_probe_or_plan_id=_optional_text(
                        payload.get("selected_probe_or_plan_id"),
                        field_name="selected_probe_or_plan_id",
                    ),
                    active_hypothesis_ids=_string_tuple(
                        active_hypotheses, field_name="active_hypothesis_ids"
                    ),
                    predicted_outcome_ids=_string_tuple(
                        predictions, field_name="predicted_outcome_ids"
                    ),
                    active_goal_ids=_string_tuple(
                        payload.get("active_goal_ids", []), field_name="active_goal_ids"
                    ),
                    active_world_model_ids=_string_tuple(
                        payload.get("active_world_model_ids", []),
                        field_name="active_world_model_ids",
                    ),
                    rationale_category=_required_text(
                        payload.get("rationale_category"), field_name="rationale_category"
                    ),
                    rationale_summary=_optional_text(
                        payload.get("rationale_summary"), field_name="rationale_summary"
                    ),
                )
            )
        return tuple(decisions)

    def render_frame(self, blob_hash: str) -> str:
        """Render a verified frame as compact hexadecimal rows for offline audit."""

        palette = "0123456789ABCDEF"
        frame = self.blobs.get_frame(blob_hash)
        return "\n".join("".join(palette[cell] for cell in row) for row in frame)

    def summarize(
        self,
        *,
        generator_git_commit: str,
        generator_config_hash: str,
        claims: Iterable[SummaryClaim],
        unresolved_residuals: Iterable[object],
        retrieval_tags: Iterable[str],
    ) -> TraceSummary:
        """Build a source-cited summary and validate all cited event IDs."""

        events = self.verify_integrity(verify_blobs=False)
        if not events:
            raise ReplayError("cannot summarize an empty trace")
        chunk_hashes = self.journal.chunk_hashes()
        if not chunk_hashes:
            raise ReplayError("seal at least one source chunk before generating a summary")
        event_ids = {event.event_id for event in events}
        normalized_claims = tuple(claims)
        for claim in normalized_claims:
            if not claim.supporting_event_ids:
                raise ReplayError("every summary claim needs at least one supporting event")
            unknown = (
                set(claim.supporting_event_ids) | set(claim.contradicting_event_ids)
            ) - event_ids
            if unknown:
                raise ReplayError(f"summary claim references unknown events: {sorted(unknown)}")
        normalized_residuals = tuple(normalize_json(item) for item in unresolved_residuals)
        return TraceSummary(
            source_event_start_id=events[0].event_id,
            source_event_end_id=events[-1].event_id,
            source_chunk_hashes=chunk_hashes,
            generated_at=utc_now(),
            generator_git_commit=generator_git_commit,
            generator_config_hash=generator_config_hash,
            claims=normalized_claims,
            unresolved_residuals=normalized_residuals,
            retrieval_tags=tuple(retrieval_tags),
        )


def _string_tuple(value: JSONValue, *, field_name: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ReplayError(f"{field_name} must contain only strings")
    return tuple(item for item in value if isinstance(item, str))


def _optional_text(value: JSONValue, *, field_name: str) -> str | None:
    if value is None:
        return None
    return _required_text(value, field_name=field_name)


def _required_text(value: JSONValue, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise ReplayError(f"{field_name} must be a string")
    return value


def validate_summary(summary: TraceSummary, source_events: Sequence[TraceEvent]) -> None:
    """Validate a summary's declared range and every evidence citation."""

    if not source_events:
        raise ReplayError("summary source event sequence must not be empty")
    if summary.source_event_start_id != source_events[0].event_id:
        raise ReplayError("summary source start does not match the supplied trace")
    if summary.source_event_end_id != source_events[-1].event_id:
        raise ReplayError("summary source end does not match the supplied trace")
    event_ids = {event.event_id for event in source_events}
    for claim in summary.claims:
        if not claim.supporting_event_ids:
            raise ReplayError("summary claim has no supporting events")
        if (set(claim.supporting_event_ids) | set(claim.contradicting_event_ids)) - event_ids:
            raise ReplayError("summary contains an out-of-range evidence reference")


def summary_from_mapping(raw: Mapping[str, object]) -> TraceSummary:
    """Parse a persisted summary without giving it raw-event authority."""

    normalized = normalize_json(raw)
    if not isinstance(normalized, dict):  # pragma: no cover - Mapping invariant
        raise ReplayError("summary must be an object")
    if normalized.get("schema") != SUMMARY_SCHEMA:
        raise ReplayError("unsupported summary schema")
    generator = normalized.get("generator")
    if not isinstance(generator, dict):
        raise ReplayError("summary generator must be an object")
    raw_claims = normalized.get("claims")
    if not isinstance(raw_claims, list):
        raise ReplayError("summary claims must be an array")
    claims: list[SummaryClaim] = []
    for raw_claim in raw_claims:
        if not isinstance(raw_claim, dict):
            raise ReplayError("summary claim must be an object")
        claims.append(
            SummaryClaim(
                claim=raw_claim.get("claim"),
                supporting_event_ids=_string_tuple(
                    raw_claim.get("supporting_event_ids", []),
                    field_name="supporting_event_ids",
                ),
                contradicting_event_ids=_string_tuple(
                    raw_claim.get("contradicting_event_ids", []),
                    field_name="contradicting_event_ids",
                ),
            )
        )
    residuals = normalized.get("unresolved_residuals")
    tags = normalized.get("retrieval_tags")
    chunks = normalized.get("source_chunk_hashes")
    if not isinstance(residuals, list):
        raise ReplayError("summary unresolved_residuals must be an array")
    return TraceSummary(
        schema=_required_text(normalized.get("schema"), field_name="schema"),
        source_event_start_id=_required_text(
            normalized.get("source_event_start_id"), field_name="source_event_start_id"
        ),
        source_event_end_id=_required_text(
            normalized.get("source_event_end_id"), field_name="source_event_end_id"
        ),
        source_chunk_hashes=_string_tuple(chunks, field_name="source_chunk_hashes"),
        generated_at=_required_text(normalized.get("generated_at"), field_name="generated_at"),
        generator_git_commit=_required_text(
            generator.get("git_commit"), field_name="generator.git_commit"
        ),
        generator_config_hash=_required_text(
            generator.get("config_hash"), field_name="generator.config_hash"
        ),
        claims=tuple(claims),
        unresolved_residuals=tuple(residuals),
        retrieval_tags=_string_tuple(tags, field_name="retrieval_tags"),
    )
