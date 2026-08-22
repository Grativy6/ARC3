from __future__ import annotations

import random
import subprocess
import sys
from pathlib import Path

import pytest

from arc3.memory import (
    ControllerCheckpointManager,
    RestartDirective,
)
from arc3.trace import CodeIdentity, EventJournal, SourceIdentity

CONFIG_HASH = "sha256:" + "4" * 64
STATE_HASH = "sha256:" + "5" * 64
CODE = CodeIdentity("memory-process-death", CONFIG_HASH)
SOURCE = SourceIdentity("synthetic-process-death", "1")


@pytest.mark.integration
def test_process_death_after_action_receipt_resumes_without_resubmission(
    tmp_path: Path,
) -> None:
    trace_root = tmp_path / "trace"
    checkpoint_root = tmp_path / "checkpoint"
    child_code = f"""
import os
import random
from arc3.memory import ControllerCheckpointManager, ControllerPhase, DerivedControllerState, PendingAction, PersistentMemory
from arc3.trace import CodeIdentity, EventJournal, SourceIdentity
from arc3.types import ActionName, ActionRequest

code = CodeIdentity('memory-process-death', '{CONFIG_HASH}')
source = SourceIdentity('synthetic-process-death', '1')
journal = EventJournal({str(trace_root)!r}, run_id='run-death')
journal.append(episode_id='episode-death', game_id='redacted', level_index=0, step_index=0, event_type='run.started', source=source, scope='run', payload={{}}, code_identity=code, event_id='E-RUN')
rng = random.Random(8128)
candidates = (ActionName.ACTION1, ActionName.ACTION2, ActionName.ACTION3, ActionName.ACTION4)
chosen = rng.choice(candidates)
journal.append(episode_id='episode-death', game_id='redacted', level_index=0, step_index=1, event_type='action.selected', source=source, scope='episode', payload={{'decision_id': 'D-1', 'selected_action': {{'name': chosen.value, 'coordinate': None}}, 'candidate_utilities': [], 'selected_probe_or_plan_id': 'PLAN-1', 'active_hypothesis_ids': ['H-1'], 'predicted_outcome_ids': ['P-1'], 'rationale_category': 'follow_plan'}}, code_identity=code, event_id='E-SELECTED')
journal.append(episode_id='episode-death', game_id='redacted', level_index=0, step_index=1, event_type='action.validated', source=source, scope='episode', payload={{'selected_event_id': 'E-SELECTED', 'action': {{'name': chosen.value, 'coordinate': None}}}}, code_identity=code, event_id='E-VALIDATED')
journal.append(episode_id='episode-death', game_id='redacted', level_index=0, step_index=1, event_type='action.submitted', source=source, scope='episode', payload={{'decision_id': 'D-1', 'selected_event_id': 'E-SELECTED', 'validated_event_id': 'E-VALIDATED', 'action': {{'name': chosen.value, 'coordinate': None}}}}, code_identity=code, event_id='E-SUBMITTED')
state = DerivedControllerState(normalized_state_hash='{STATE_HASH}', level_index=0, step_index=1, phase=ControllerPhase.AWAITING_CONSEQUENCE, perception_state={{'tracks': ['T-1']}}, action_semantics={{'ACTION1': 'candidate-up'}}, hypothesis_registry={{'events': ['HE-1']}}, world_model_ensemble={{'active': ['WM-1']}}, goal_registry={{'active': ['G-1']}}, explored_state_graph={{'nodes': ['S-0']}}, planner_state={{'plan_id': 'PLAN-1', 'cursor': 1}}, memory=PersistentMemory(), pending_action=PendingAction(selected_event_id='E-SELECTED', submitted_event_id='E-SUBMITTED', step_index=1, action=ActionRequest(chosen), prediction_ids=('P-1',)), unresolved_residuals=('contact rule unresolved',))
ControllerCheckpointManager({str(checkpoint_root)!r}).write(journal=journal, episode_id='episode-death', code_identity=code, rng=rng, state=state)
os._exit(23)
"""
    process = subprocess.run([sys.executable, "-c", child_code], check=False)
    assert process.returncode == 23

    uninterrupted_rng = random.Random(8128)
    candidates = ("ACTION1", "ACTION2", "ACTION3", "ACTION4")
    expected_pending = uninterrupted_rng.choice(candidates)
    expected_followups = [uninterrupted_rng.choice(candidates) for _ in range(20)]

    journal = EventJournal(trace_root, run_id="run-death")
    restored = ControllerCheckpointManager(checkpoint_root).restore(
        journal=journal,
        episode_id="episode-death",
        code_identity=CODE,
    )
    assert restored.restart_directive is RestartDirective.AWAIT_CONSEQUENCE
    assert restored.state.pending_action is not None
    assert restored.state.pending_action.action.name.value == expected_pending
    assert restored.state.perception_state == {"tracks": ["T-1"]}
    assert restored.state.hypothesis_registry == {"events": ["HE-1"]}
    assert restored.state.world_model_ensemble == {"active": ["WM-1"]}
    assert restored.state.goal_registry == {"active": ["G-1"]}
    assert restored.state.explored_state_graph == {"nodes": ["S-0"]}
    assert restored.state.planner_state == {"cursor": 1, "plan_id": "PLAN-1"}

    consequence = journal.append(
        episode_id="episode-death",
        game_id="redacted",
        level_index=0,
        step_index=1,
        event_type="consequence.received",
        source=SOURCE,
        scope="episode",
        payload={"submitted_event_id": "E-SUBMITTED"},
        code_identity=CODE,
        event_id="E-CONSEQUENCE",
    )
    continued = restored.state.after_consequence(consequence)
    assert continued.restart_directive is RestartDirective.CHOOSE_ACTION
    resumed_followups = [restored.rng.choice(candidates) for _ in range(20)]
    assert resumed_followups == expected_followups
    journal.close()
