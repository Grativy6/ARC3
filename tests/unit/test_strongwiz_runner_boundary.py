"""Fail-closed tests for the Strongwiz one-shot runner boundary."""

from __future__ import annotations

import socket
from collections.abc import Mapping
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, cast

import pytest
from scripts.run_strongwiz_operator import (
    ACQUISITION_NETWORK_MODE,
    DEFAULT_TARGET,
    ROOT,
    _inside_repository,
    _OfflineSocketGuard,
    _require_new_acquisition,
    _require_new_measured_run,
    _target_entry,
)

from arc3.adapters import GridFrame, Observation
from arc3.errors import EvaluationError
from arc3.evaluation.public import PublicExposureLedger, run_public_episode
from arc3.types import ActionName, ActionRequest, GameId, GameStateName, JSONValue

PROTOCOL_SHA256 = "9a75b29a73d4b0cf4549c2d083838c27cf7a7b90cc532a376a55f6bcb3d8df56"
SETUP_NETWORK_MODE = "official-NORMAL-anonymous-networked-acquisition"


def _append_setup(ledger: PublicExposureLedger) -> None:
    intent = ledger.append(
        "strongwiz.asset-acquisition.intent",
        {
            "frame_exposed_to_operator": False,
            "game_id": DEFAULT_TARGET,
            "environment_acquisition_network_mode": ACQUISITION_NETWORK_MODE,
            "partition": "development",
            "protocol_sha256": PROTOCOL_SHA256,
            "seed": 0,
            "setup_network_mode": SETUP_NETWORK_MODE,
        },
    )
    ledger.append(
        "strongwiz.asset-acquisition.completed",
        {
            "frame_exposed_to_operator": False,
            "game_id": DEFAULT_TARGET,
            "environment_acquisition_network_mode": ACQUISITION_NETWORK_MODE,
            "intent_event_hash": intent["event_hash"],
            "partition": "development",
            "protocol_sha256": PROTOCOL_SHA256,
            "seed": 0,
            "setup_network_mode": SETUP_NETWORK_MODE,
        },
    )


def test_exact_target_and_repository_path_are_fail_closed() -> None:
    manifest = ROOT / "docs" / "evaluation" / "public-game-partitions.v0.1.json"
    _target_entry(manifest, DEFAULT_TARGET)
    with pytest.raises(EvaluationError, match="only its frozen target"):
        _target_entry(manifest, "different-development-game")
    assert _inside_repository(ROOT / "artifacts" / "fixture", label="fixture").is_absolute()
    with pytest.raises(EvaluationError, match="inside the clean-room checkout"):
        _inside_repository(ROOT.parent / "outside-fixture", label="fixture")


def test_setup_and_measured_run_are_each_one_shot() -> None:
    with TemporaryDirectory(prefix="runner-boundary-", dir=ROOT / "playground" / "tmp") as temp:
        ledger = PublicExposureLedger(Path(temp) / "exposure.jsonl")
        _require_new_acquisition(ledger)
        _append_setup(ledger)
        with pytest.raises(EvaluationError, match="setup exposure is already consumed"):
            _require_new_acquisition(ledger)
        _require_new_measured_run(
            ledger,
            game_id=DEFAULT_TARGET,
            protocol_sha256=PROTOCOL_SHA256,
            seed=0,
        )
        ledger.append(
            "strongwiz.measured-run.intent",
            {
                "game_id": DEFAULT_TARGET,
                "protocol_sha256": PROTOCOL_SHA256,
                "seed": 0,
            },
        )
        with pytest.raises(EvaluationError, match="measured run is already consumed"):
            _require_new_measured_run(
                ledger,
                game_id=DEFAULT_TARGET,
                protocol_sha256=PROTOCOL_SHA256,
                seed=0,
            )


def test_python_socket_guard_counts_denial_and_restores() -> None:
    original = socket.getaddrinfo
    guard = _OfflineSocketGuard()
    guard.install()
    try:
        with pytest.raises(EvaluationError, match="blocked a network attempt"):
            socket.getaddrinfo("example.invalid", 443)
        assert guard.attempt_count == 1
    finally:
        guard.restore()
    assert socket.getaddrinfo is original


def _observation(value: int, state: GameStateName) -> Observation:
    return Observation(
        game_id=GameId("callback-order-fixture"),
        frames=(GridFrame(((value,),)),),
        state=state,
        levels_completed=int(state is GameStateName.WIN),
        win_levels=1,
        available_actions=(ActionName.ACTION1,),
    )


def test_returned_authority_callback_precedes_derived_assessment() -> None:
    calls: list[str] = []
    before = _observation(0, GameStateName.NOT_FINISHED)
    after = _observation(1, GameStateName.WIN)

    class Policy:
        def select(self, observation: Observation) -> ActionRequest:
            assert observation == before
            calls.append("select")
            return ActionRequest(ActionName.ACTION1)

        def accept_consequence(self, observation: Observation) -> None:
            assert observation == after
            calls.append("assess")

    class Session:
        observation = before

        def step(
            self,
            action: ActionRequest,
            *,
            reasoning: Mapping[str, JSONValue] | None = None,
        ) -> Observation:
            assert action == ActionRequest(ActionName.ACTION1)
            assert reasoning is not None
            calls.append("step")
            return after

        def close(self) -> None:
            calls.append("close")

    def authorize() -> None:
        calls.append("authorize")

    def preselect() -> None:
        calls.append("preselect")

    def submission_started() -> None:
        calls.append("submission_started")

    def returned(observation: Observation) -> None:
        assert observation == after
        calls.append("returned")

    class TraceSink:
        def record_observation(self, observation: Observation) -> None:
            calls.append(f"trace_observation:{observation.state.value}")

        def record_candidates(self, _observation: Observation) -> None:
            calls.append("trace_candidates")

        def record_selected(self, _observation: Observation, _action: ActionRequest) -> None:
            calls.append("trace_selected")

        def record_submitted(self, _observation: Observation, _action: ActionRequest) -> None:
            calls.append("trace_submitted")

        def record_consequence(
            self,
            _before: Observation,
            _action: ActionRequest,
            _after: Observation,
        ) -> None:
            calls.append("trace_consequence")

    run_public_episode(
        cast(Any, Session()),
        cast(Any, Policy()),
        max_actions=1,
        max_resets=1,
        trace_sink=cast(Any, TraceSink()),
        pre_action_selection=preselect,
        pre_action_authorization=authorize,
        environment_submission_started=submission_started,
        environment_returned=returned,
    )
    assert calls == [
        "trace_observation:NOT_FINISHED",
        "preselect",
        "trace_candidates",
        "select",
        "trace_selected",
        "authorize",
        "submission_started",
        "trace_submitted",
        "step",
        "returned",
        "trace_consequence",
        "trace_observation:WIN",
        "assess",
        "close",
    ]
