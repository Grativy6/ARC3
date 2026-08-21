"""Traceable recovery selection for stale plans and failed predictions."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from arc3.trace.canonical import sha256_json
from arc3.types import ActionName, ActionRequest, JSONValue


class RecoveryMode(StrEnum):
    """Explicit outcomes at a planning failure boundary."""

    REPLAN_SAME_MODEL = "replan-same-model"
    DISCRIMINATING_PROBE = "discriminating-probe"
    REOPEN_MODEL = "reopen-model"
    SUPPORTED_UNDO = "supported-undo"
    MANDATORY_RESET = "mandatory-reset"
    STOP_NO_RECOVERY = "stop-no-recovery-ablation"


@dataclass(frozen=True, slots=True)
class RecoveryContext:
    """Evidence available to recovery; flags are explicit rather than inferred."""

    cause: str
    plan_id: str
    model_id: str
    goal_id: str
    failed_action: ActionRequest | None = None
    game_over: bool = False
    undo_supported: bool = False
    same_model_viable: bool = True
    models_disagree: bool = False
    discriminating_probe: ActionRequest | None = None


@dataclass(frozen=True, slots=True)
class RecoveryDecision:
    """Concise receipt: a recovery choice is not hidden reasoning or evidence."""

    decision_id: str
    mode: RecoveryMode
    cause: str
    invalidated_plan_id: str
    model_id: str
    goal_id: str
    next_action: ActionRequest | None
    rationale: str

    def to_trace_payload(self) -> dict[str, JSONValue]:
        return {
            "schema": "arc3.planning.recovery-decision.v0.1",
            "decision_id": self.decision_id,
            "mode": self.mode.value,
            "cause": self.cause,
            "invalidated_plan_id": self.invalidated_plan_id,
            "model_id": self.model_id,
            "goal_id": self.goal_id,
            "next_action": (
                {
                    "name": self.next_action.name.value,
                    "coordinate": (
                        [self.next_action.coordinate.x, self.next_action.coordinate.y]
                        if self.next_action.coordinate is not None
                        else None
                    ),
                }
                if self.next_action is not None
                else None
            ),
            "rationale": self.rationale,
        }


class RecoveryPolicy:
    """Deterministic recovery ordering with an explicit no-recovery ablation."""

    def __init__(self, *, enabled: bool = True) -> None:
        self.enabled = enabled

    def decide(self, context: RecoveryContext) -> RecoveryDecision:
        if context.game_over:
            mode = RecoveryMode.MANDATORY_RESET
            action = ActionRequest(ActionName.RESET)
            rationale = "game over permits only reset"
        elif not self.enabled:
            mode = RecoveryMode.STOP_NO_RECOVERY
            action = None
            rationale = "recovery disabled by named ablation; blind continuation refused"
        elif context.undo_supported:
            mode = RecoveryMode.SUPPORTED_UNDO
            action = ActionRequest(ActionName.ACTION7)
            rationale = "failed transition is reversible under observed undo support"
        elif context.models_disagree and context.discriminating_probe is not None:
            mode = RecoveryMode.DISCRIMINATING_PROBE
            action = context.discriminating_probe
            rationale = "active models disagree; take the supplied bounded discriminator"
        elif context.same_model_viable:
            mode = RecoveryMode.REPLAN_SAME_MODEL
            action = None
            rationale = "retain the model provisionally and search again from observed state"
        else:
            mode = RecoveryMode.REOPEN_MODEL
            action = None
            rationale = "prediction failure leaves no viable continuation under this model"
        content: dict[str, JSONValue] = {
            "mode": mode.value,
            "cause": context.cause,
            "plan_id": context.plan_id,
            "model_id": context.model_id,
            "goal_id": context.goal_id,
            "failed_action": (
                context.failed_action.name.value if context.failed_action is not None else None
            ),
            "next_action": action.name.value if action is not None else None,
        }
        digest = sha256_json(content).removeprefix("sha256:")[:24]
        return RecoveryDecision(
            decision_id=f"recovery:{digest}",
            mode=mode,
            cause=context.cause,
            invalidated_plan_id=context.plan_id,
            model_id=context.model_id,
            goal_id=context.goal_id,
            next_action=action,
            rationale=rationale,
        )


__all__ = ["RecoveryContext", "RecoveryDecision", "RecoveryMode", "RecoveryPolicy"]
