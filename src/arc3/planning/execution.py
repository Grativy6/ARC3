"""One-action-at-a-time plan execution with consequence validation."""

from __future__ import annotations

from dataclasses import dataclass

from arc3.errors import PlanningError
from arc3.trace.canonical import sha256_json
from arc3.types import ActionRequest, GameStateName, JSONValue
from arc3.world_model import SymbolicState

from .models import Plan, PlanStep
from .recovery import RecoveryContext, RecoveryDecision, RecoveryPolicy


@dataclass(frozen=True, slots=True)
class ActionEmission:
    """Exactly one action plus the prediction that must be checked next."""

    decision_id: str
    plan_id: str
    step_index: int
    action: ActionRequest
    before_state_id: str
    predicted_state_id: str

    def to_trace_payload(self) -> dict[str, JSONValue]:
        return {
            "schema": "arc3.planning.action-emission.v0.1",
            "decision_id": self.decision_id,
            "plan_id": self.plan_id,
            "step_index": self.step_index,
            "action": self.action.name.value,
            "before_state_id": self.before_state_id,
            "predicted_state_id": self.predicted_state_id,
        }


@dataclass(frozen=True, slots=True)
class ConsequenceDecision:
    """Observed-versus-predicted result and any mandatory recovery."""

    receipt_id: str
    plan_id: str
    step_index: int
    observed_state_id: str
    predicted_state_id: str
    matched: bool
    plan_complete: bool
    recovery: RecoveryDecision | None

    def to_trace_payload(self) -> dict[str, JSONValue]:
        return {
            "schema": "arc3.planning.consequence-decision.v0.1",
            "receipt_id": self.receipt_id,
            "plan_id": self.plan_id,
            "step_index": self.step_index,
            "observed_state_id": self.observed_state_id,
            "predicted_state_id": self.predicted_state_id,
            "matched": self.matched,
            "plan_complete": self.plan_complete,
            "recovery_decision_id": (
                self.recovery.decision_id if self.recovery is not None else None
            ),
        }


class PlanExecutor:
    """Release one planned action, then block until its consequence is supplied."""

    def __init__(self, *, recovery_policy: RecoveryPolicy | None = None) -> None:
        self._recovery = recovery_policy or RecoveryPolicy()
        self._plan: Plan | None = None
        self._cursor = 0
        self._pending: ActionEmission | None = None

    @property
    def plan(self) -> Plan | None:
        return self._plan

    @property
    def cursor(self) -> int:
        return self._cursor

    def load(self, plan: Plan) -> None:
        if self._pending is not None:
            raise PlanningError("cannot replace a plan while an action consequence is pending")
        self._plan = plan
        self._cursor = 0

    def next_action(
        self,
        current_state: SymbolicState,
        *,
        model_id: str,
        goal_id: str,
        goal_revision: str,
        game_state: GameStateName = GameStateName.NOT_FINISHED,
    ) -> ActionEmission | RecoveryDecision | None:
        plan = self._require_plan()
        if self._pending is not None:
            raise PlanningError("a consequence is required before another action")
        if game_state is GameStateName.GAME_OVER:
            return self._invalidate(
                RecoveryContext(
                    cause="game-over",
                    plan_id=plan.plan_id,
                    model_id=model_id,
                    goal_id=goal_id,
                    game_over=True,
                )
            )
        if not plan.is_current(model_id=model_id, goal_id=goal_id, goal_revision=goal_revision):
            same_model = plan.model_id == model_id
            cause = "goal-identity-changed" if same_model else "model-identity-changed"
            return self._invalidate(
                RecoveryContext(
                    cause=cause,
                    plan_id=plan.plan_id,
                    model_id=model_id,
                    goal_id=goal_id,
                    same_model_viable=same_model,
                )
            )
        if self._cursor >= len(plan.steps):
            return None
        step = plan.steps[self._cursor]
        if step.before_state_id != current_state.state_id:
            return self._invalidate(
                RecoveryContext(
                    cause="execution-state-diverged-before-action",
                    plan_id=plan.plan_id,
                    model_id=model_id,
                    goal_id=goal_id,
                    same_model_viable=True,
                )
            )
        content: dict[str, JSONValue] = {
            "plan_id": plan.plan_id,
            "step_index": step.index,
            "before_state_id": current_state.state_id,
            "predicted_state_id": step.predicted_state_id,
            "action": step.action.name.value,
        }
        digest = sha256_json(content).removeprefix("sha256:")[:24]
        emission = ActionEmission(
            decision_id=f"action-decision:{digest}",
            plan_id=plan.plan_id,
            step_index=step.index,
            action=step.action,
            before_state_id=current_state.state_id,
            predicted_state_id=step.predicted_state_id,
        )
        self._pending = emission
        return emission

    def apply_consequence(
        self,
        observed_state: SymbolicState,
        *,
        game_state: GameStateName = GameStateName.NOT_FINISHED,
        undo_supported: bool = False,
        same_model_viable: bool = True,
        models_disagree: bool = False,
        discriminating_probe: ActionRequest | None = None,
    ) -> ConsequenceDecision:
        plan = self._require_plan()
        emission = self._pending
        if emission is None:
            raise PlanningError("cannot apply a consequence without a pending action")
        step = self._step(plan, emission.step_index)
        matched = observed_state.state_id == step.predicted_state_id
        recovery: RecoveryDecision | None = None
        if game_state is GameStateName.GAME_OVER:
            recovery = self._recovery.decide(
                RecoveryContext(
                    cause="game-over-after-action",
                    plan_id=plan.plan_id,
                    model_id=plan.model_id,
                    goal_id=plan.goal_id,
                    failed_action=step.action,
                    game_over=True,
                )
            )
        elif not matched:
            recovery = self._recovery.decide(
                RecoveryContext(
                    cause="predicted-consequence-mismatch",
                    plan_id=plan.plan_id,
                    model_id=plan.model_id,
                    goal_id=plan.goal_id,
                    failed_action=step.action,
                    undo_supported=undo_supported,
                    same_model_viable=same_model_viable,
                    models_disagree=models_disagree,
                    discriminating_probe=discriminating_probe,
                )
            )
        else:
            self._cursor += 1
        content: dict[str, JSONValue] = {
            "action_decision_id": emission.decision_id,
            "observed_state_id": observed_state.state_id,
            "predicted_state_id": step.predicted_state_id,
            "matched": matched,
            "recovery": recovery.decision_id if recovery is not None else None,
        }
        digest = sha256_json(content).removeprefix("sha256:")[:24]
        result = ConsequenceDecision(
            receipt_id=f"consequence:{digest}",
            plan_id=plan.plan_id,
            step_index=step.index,
            observed_state_id=observed_state.state_id,
            predicted_state_id=step.predicted_state_id,
            matched=matched,
            plan_complete=matched and self._cursor == len(plan.steps),
            recovery=recovery,
        )
        self._pending = None
        if recovery is not None:
            self._plan = None
            self._cursor = 0
        return result

    def _invalidate(self, context: RecoveryContext) -> RecoveryDecision:
        decision = self._recovery.decide(context)
        self._plan = None
        self._cursor = 0
        return decision

    def _require_plan(self) -> Plan:
        if self._plan is None:
            raise PlanningError("no plan is loaded")
        return self._plan

    @staticmethod
    def _step(plan: Plan, index: int) -> PlanStep:
        try:
            return plan.steps[index]
        except IndexError as error:
            raise PlanningError("pending action refers to a missing plan step") from error


__all__ = ["ActionEmission", "ConsequenceDecision", "PlanExecutor"]
