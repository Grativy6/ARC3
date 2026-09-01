"""Trace instrumentation for baseline observation/action loops."""

from __future__ import annotations

from dataclasses import dataclass

from arc3.adapters import Observation
from arc3.baseline_runner import BaselineReceiptSink
from arc3.types import ActionName, ActionRequest, JSONValue, RationaleCategory, StateScope

from .journal import EventJournal
from .schema import CodeIdentity, SourceIdentity


def _action_payload(action: ActionRequest) -> dict[str, JSONValue]:
    coordinate: dict[str, JSONValue] | None = None
    if action.coordinate is not None:
        coordinate = {"x": action.coordinate.x, "y": action.coordinate.y}
    return {"name": action.name.value, "coordinate": coordinate}


@dataclass(slots=True)
class BaselineTraceSink(BaselineReceiptSink):
    """Append raw policy receipts without retaining mutable observations.

    Historical callers keep the baseline defaults. Experiment adapters may supply
    truthful concise labels without changing the immutable event vocabulary.
    """

    journal: EventJournal
    episode_id: str
    source: SourceIdentity
    code_identity: CodeIdentity
    rationale_category: RationaleCategory = RationaleCategory.BASELINE
    rationale_summary: str = "bounded deterministic baseline selection"
    alternative_interpretation: str = "unranked deterministic baseline alternative"
    consequence_classification: str = "uninterpreted-baseline"
    model_update_summary: str = "not-applicable-baseline"
    level_index: int = 0
    step_index: int = 0

    def _append(
        self,
        observation: Observation,
        event_type: str,
        payload: dict[str, object],
    ) -> None:
        self.journal.append(
            episode_id=self.episode_id,
            game_id=str(observation.game_id),
            level_index=self.level_index,
            step_index=self.step_index,
            event_type=event_type,
            source=self.source,
            scope=StateScope.EPISODE,
            payload=payload,
            code_identity=self.code_identity,
        )

    def record_observation(self, observation: Observation) -> None:
        frames = [
            self.journal.blobs.put_frame(frame.cells).to_payload() for frame in observation.frames
        ]
        metadata: dict[str, JSONValue] = {
            key: value for key, value in observation.upstream_metadata
        }
        metadata.update(
            {
                "levels_completed": observation.levels_completed,
                "win_levels": observation.win_levels,
                "full_reset": observation.full_reset,
            }
        )
        self._append(
            observation,
            "observation.received",
            {
                "frame_count": len(frames),
                "frames": frames,
                "game_state": observation.state.value,
                "score": None,
                "available_actions": [action.value for action in observation.available_actions],
                "upstream_metadata": metadata,
            },
        )

    def record_candidates(self, observation: Observation) -> None:
        candidates: list[dict[str, JSONValue]] = []
        if observation.state.value in {"NOT_PLAYED", "GAME_OVER"}:
            candidates.append({"action": ActionName.RESET.value, "source": "mandatory_lifecycle"})
        else:
            candidates.extend(
                {"action": action.value, "source": "advertised"}
                for action in observation.available_actions
            )
        self._append(
            observation,
            "action.candidates_generated",
            {
                "candidates": candidates,
                "summary": "advertised actions plus mandatory lifecycle handling",
            },
        )

    def record_selected(self, observation: Observation, action: ActionRequest) -> None:
        self._append(
            observation,
            "action.selected",
            {
                "selected_action": _action_payload(action),
                "candidate_utilities": [
                    {
                        "action": candidate.value,
                        "weight": 0.0,
                        "interpretation": self.alternative_interpretation,
                    }
                    for candidate in observation.available_actions
                ],
                "selected_probe_or_plan_id": None,
                "active_hypothesis_ids": [],
                "predicted_outcome_ids": [],
                "rationale_category": self.rationale_category.value,
                "rationale_summary": self.rationale_summary,
                "alternatives_summary": "all currently advertised actions were eligible",
            },
        )

    def record_submitted(self, observation: Observation, action: ActionRequest) -> None:
        self._append(
            observation,
            "action.submitted",
            {
                "action": _action_payload(action),
                "selected_event_id": self.journal.tail_event_id,
            },
        )

    def record_consequence(
        self,
        before: Observation,
        action: ActionRequest,
        after: Observation,
    ) -> None:
        frame_receipts = [
            self.journal.blobs.put_frame(frame.cells).to_payload() for frame in after.frames
        ]
        self._append(
            after,
            "consequence.received",
            {
                "action": _action_payload(action),
                "before_state": before.state.value,
                "after_state": after.state.value,
                "returned_frames": frame_receipts,
                "levels_completed": after.levels_completed,
                "effect_classification": self.consequence_classification,
                "model_update": self.model_update_summary,
            },
        )
        self.step_index += 1


__all__ = ["BaselineTraceSink"]
