"""Focused contract tests for the Strongwiz clean-room operator boundary."""

from __future__ import annotations

import json
import sqlite3
import time
from collections.abc import Callable, Iterator, Mapping
from contextlib import closing
from dataclasses import replace
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
from typing import Any, NoReturn, TextIO, cast

import pytest

from arc3.adapters import GridFrame, Observation
from arc3.errors import DependencyUnavailableError, EvaluationError, InvalidActionError, PolicyError
from arc3.evaluation.public import run_public_episode
from arc3.evaluation.strongwiz_operator import (
    OPERATOR_RECEIPT_SCHEMA,
    OPERATOR_RESPONSE_SCHEMA,
    STRONGWIZ_ARCHIVE_SHA256,
    STRONGWIZ_COMMIT,
    STRONGWIZ_LICENSE_SHA256,
    STRONGWIZ_TREE,
    JsonlOperatorProvider,
    StrongwizOperatorConfig,
    StrongwizOperatorPolicy,
    StrongwizSourceIdentity,
    verify_strongwiz_source,
)
from arc3.trace.canonical import sha256_json
from arc3.types import ActionName, ActionRequest, GameId, GameStateName, JSONValue

ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOT = ROOT / "playground" / "vendor" / "strongwiz"
SOURCE_ARCHIVE = ROOT / "playground" / "tmp" / "strongwiz-6944642.tar"
PROTOCOL_SHA256 = "9a75b29a73d4b0cf4549c2d083838c27cf7a7b90cc532a376a55f6bcb3d8df56"


def _source_identity() -> StrongwizSourceIdentity:
    return StrongwizSourceIdentity(source_root=SOURCE_ROOT, archive_path=SOURCE_ARCHIVE)


@pytest.fixture
def artifact_root() -> Iterator[Path]:
    """Keep generated ledgers inside the declared clean-room checkout."""

    with TemporaryDirectory(
        prefix="pytest-strongwiz-operator-",
        dir=ROOT / "playground" / "tmp",
    ) as directory:
        yield Path(directory)


def _config(artifact_root: Path, *, run_id: str) -> StrongwizOperatorConfig:
    return StrongwizOperatorConfig(
        repository_root=ROOT,
        source=_source_identity(),
        run_id=run_id,
        game_id="opaque-contract-fixture",
        artifact_root=artifact_root,
        protocol_sha256=PROTOCOL_SHA256,
        max_actions=2,
        max_resets=2,
        checkpoint_actions=1,
        checkpoint_resets=1,
    )


def _observation(
    value: int,
    *,
    state: GameStateName = GameStateName.NOT_FINISHED,
    levels_completed: int = 0,
    available_actions: tuple[ActionName, ...] = (
        ActionName.ACTION1,
        ActionName.ACTION6,
        ActionName.RESET,
    ),
) -> Observation:
    return Observation(
        game_id=GameId("opaque-contract-fixture"),
        frames=(GridFrame(((value, 0), (0, 0))),),
        state=state,
        levels_completed=levels_completed,
        win_levels=1,
        available_actions=available_actions,
    )


def _valid_response(
    request: Mapping[str, JSONValue],
    *,
    action: Mapping[str, object] | None = None,
) -> dict[str, object]:
    return {
        "schema": OPERATOR_RESPONSE_SCHEMA,
        "request_sha256": cast(str, request["request_sha256"]),
        "sequence": cast(int, request["sequence"]),
        "action": dict(action or {"name": ActionName.ACTION1.value, "coordinate": None}),
        "distinction": {
            "statement": "Whether one legal synthetic action changes the returned frame",
            "candidate_resolutions": ("frame changes", "frame repeats"),
            "competing_predictions": ("digest differs", "digest remains equal"),
            "decision_effects": ("movement",),
            "decision_that_could_change": "the next generic contract probe",
            "relevance_summary": "The returned frame discriminates the fixture alternatives",
            "smallest_discriminating_test": "one synthetic action and one consequence",
            "reopening_condition": "the returned consequence contradicts the prediction",
        },
        "prediction": {
            "expected_consequences": ("the synthetic frame digest changes",),
            "falsified_by": ("the synthetic frame digest remains unchanged",),
            "alternatives": ("the action has no visible effect",),
            "expected_frame_change": True,
        },
        "hypotheses": (),
        "evidence_refs": (),
        "trace_refs": (),
        "residual_refs": (),
        "concise_rationale": "One bounded synthetic probe distinguishes the stated alternatives",
        "reversible": True,
        "expected_progress_rank": 1,
        "information_gain_rank": 1,
        "risk_rank": 0,
    }


ResponseMutator = Callable[[dict[str, object]], None]


class _Provider:
    def __init__(
        self,
        *,
        action: Mapping[str, object] | None = None,
        mutate: ResponseMutator | None = None,
    ) -> None:
        self.action = action
        self.mutate = mutate
        self.calls = 0
        self.last_request: Mapping[str, JSONValue] | None = None

    def __call__(self, request: Mapping[str, JSONValue]) -> Mapping[str, object]:
        self.calls += 1
        self.last_request = request
        response = _valid_response(request, action=self.action)
        if self.mutate is not None:
            self.mutate(response)
        return response


class _RecordingSession:
    def __init__(self, before: Observation, after: Observation) -> None:
        self._observation = before
        self._after = after
        self.step_calls = 0
        self.close_calls = 0

    @property
    def observation(self) -> Observation:
        return self._observation

    def step(
        self,
        action: ActionRequest,
        *,
        reasoning: Mapping[str, JSONValue] | None = None,
    ) -> Observation:
        assert reasoning is not None
        assert action.name in self._observation.available_actions
        self.step_calls += 1
        self._observation = self._after
        return self._observation

    def close(self) -> None:
        self.close_calls += 1


def _ledger_projection(path: Path) -> list[tuple[str, dict[str, object]]]:
    with closing(sqlite3.connect(path)) as connection:
        rows = connection.execute(
            """SELECT receipts.kind, objects.canonical_payload
               FROM receipts
               JOIN objects ON objects.payload_hash = receipts.payload_hash
               ORDER BY receipts.sequence"""
        ).fetchall()
    return [
        (str(kind), cast(dict[str, object], json.loads(bytes(payload)))) for kind, payload in rows
    ]


def _abort_after_selection_failure(policy: StrongwizOperatorPolicy) -> None:
    policy.abort(reason="synthetic pre-actuation rejection", environment_effect_unknown=False)
    assert policy.closed


class _BlockingInput:
    def __init__(self) -> None:
        self.release = Event()

    def readline(self, _limit: int = -1) -> str:
        self.release.wait(timeout=5.0)
        return ""


def test_jsonl_provider_deadline_prevents_unbounded_operator_wait() -> None:
    blocked = _BlockingInput()
    provider = JsonlOperatorProvider(
        cast(TextIO, blocked),
        StringIO(),
        deadline_monotonic=time.monotonic() - 1.0,
        poll_seconds=0.001,
    )
    try:
        with pytest.raises(PolicyError, match="wall deadline"):
            provider({"schema": "synthetic-request"})
    finally:
        blocked.release.set()


def test_jsonl_provider_checks_resource_watchdog_while_waiting() -> None:
    blocked = _BlockingInput()

    def reject_wait() -> NoReturn:
        raise EvaluationError("synthetic operator-wait resource ceiling")

    provider = JsonlOperatorProvider(
        cast(TextIO, blocked),
        StringIO(),
        deadline_monotonic=time.monotonic() + 60.0,
        watchdog=reject_wait,
        poll_seconds=0.001,
    )
    try:
        with pytest.raises(EvaluationError, match="operator-wait resource ceiling"):
            provider({"schema": "synthetic-request"})
    finally:
        blocked.release.set()


def test_exact_repository_local_strongwiz_source_identity() -> None:
    identity = _source_identity()

    assert verify_strongwiz_source(identity) == {
        "archive_sha256": STRONGWIZ_ARCHIVE_SHA256,
        "commit": STRONGWIZ_COMMIT,
        "license_sha256": STRONGWIZ_LICENSE_SHA256,
        "tree": STRONGWIZ_TREE,
    }

    with pytest.raises(DependencyUnavailableError, match="source identity changed"):
        verify_strongwiz_source(replace(identity, archive_sha256="0" * 64))


def test_valid_one_action_consequence_and_close_persist_exact_receipts(
    artifact_root: Path,
) -> None:
    provider = _Provider()
    policy = StrongwizOperatorPolicy(
        _config(artifact_root, run_id="valid-one-action"),
        provider,
    )
    session = _RecordingSession(
        _observation(0),
        _observation(1, state=GameStateName.WIN, levels_completed=1),
    )

    scorecard, metrics = run_public_episode(
        cast(Any, session),
        policy,
        max_actions=1,
        max_resets=1,
    )
    policy.close()

    assert scorecard is None
    assert metrics["environment_actions"] == 1
    assert provider.calls == 1
    assert session.step_calls == 1
    assert session.close_calls == 1
    assert policy.actions == 1
    assert policy.resets == 0
    assert policy.completion_genuinely_observed
    assert policy.closed
    projection = _ledger_projection(policy.ledger_path)
    assert [kind for kind, _payload in projection] == [
        "runtime.source",
        "operator.request",
        "operator.response",
        "strongwiz.decision",
        "environment.consequence",
        "strongwiz.assessment",
        "run.checkpoint",
        "run.final",
    ]
    assert projection[0][1]["commit"] == STRONGWIZ_COMMIT
    assert projection[0][1]["archive_sha256"] == STRONGWIZ_ARCHIVE_SHA256
    assert projection[4][1]["schema"] == "arc3.returned-consequence.v0.1"
    receipt = cast(
        dict[str, object],
        json.loads((artifact_root / "operator-receipt.json").read_text(encoding="utf-8")),
    )
    receipt_without_hash = {key: value for key, value in receipt.items() if key != "receipt_sha256"}
    assert receipt["schema"] == OPERATOR_RECEIPT_SCHEMA
    assert receipt["strongwiz_commit"] == STRONGWIZ_COMMIT
    assert receipt["receipt_sha256"] == sha256_json(receipt_without_hash)


def _make_stale(response: dict[str, object]) -> None:
    response["request_sha256"] = "0" * 64


def _make_malformed(response: dict[str, object]) -> None:
    del response["prediction"]


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (_make_stale, "stale or bound to another request"),
        (_make_malformed, "failed schema validation"),
    ],
    ids=("stale", "malformed"),
)
def test_stale_and_malformed_responses_fail_before_actuation(
    artifact_root: Path,
    mutate: ResponseMutator,
    message: str,
) -> None:
    provider = _Provider(mutate=mutate)
    policy = StrongwizOperatorPolicy(
        _config(artifact_root, run_id=f"pre-actuation-{message.split()[0]}"),
        provider,
    )
    session = _RecordingSession(_observation(0), _observation(1))

    try:
        with pytest.raises(PolicyError, match=message):
            run_public_episode(
                cast(Any, session),
                policy,
                max_actions=1,
                max_resets=1,
            )
        assert provider.calls == 1
        assert session.step_calls == 0
        assert policy.actions == 0
        assert policy.resets == 0
        assert not policy.has_pending_action
    finally:
        _abort_after_selection_failure(policy)


def _inject_hidden_reasoning(response: dict[str, object]) -> None:
    distinction = cast(dict[str, object], response["distinction"])
    distinction["scratchpad"] = "prohibited private derivation"


def test_hidden_reasoning_is_rejected_before_actuation(artifact_root: Path) -> None:
    provider = _Provider(mutate=_inject_hidden_reasoning)
    policy = StrongwizOperatorPolicy(
        _config(artifact_root, run_id="hidden-reasoning-rejection"),
        provider,
    )
    session = _RecordingSession(_observation(0), _observation(1))

    try:
        with pytest.raises(PolicyError, match="prohibited hidden-reasoning field"):
            run_public_episode(
                cast(Any, session),
                policy,
                max_actions=1,
                max_resets=1,
            )
        assert provider.calls == 1
        assert session.step_calls == 0
        assert not policy.has_pending_action
    finally:
        _abort_after_selection_failure(policy)


@pytest.mark.parametrize(
    ("action", "message"),
    [
        (
            {"name": "NOT_AN_ARC_ACTION", "coordinate": None},
            "unsupported operator action",
        ),
        (
            {"name": ActionName.ACTION6.value, "coordinate": None},
            "ACTION6 alone requires a coordinate",
        ),
        (
            {
                "name": ActionName.ACTION1.value,
                "coordinate": {"x": 0, "y": 0},
            },
            "ACTION6 alone requires a coordinate",
        ),
    ],
    ids=("unknown-action", "action6-missing-coordinate", "coordinate-on-non-action6"),
)
def test_invalid_action_and_action6_shapes_fail_before_actuation(
    artifact_root: Path,
    action: Mapping[str, object],
    message: str,
) -> None:
    provider = _Provider(action=action)
    policy = StrongwizOperatorPolicy(
        _config(artifact_root, run_id=f"invalid-action-{provider.calls}-{message[:8]}"),
        provider,
    )
    session = _RecordingSession(_observation(0), _observation(1))

    try:
        with pytest.raises(PolicyError, match=message):
            run_public_episode(
                cast(Any, session),
                policy,
                max_actions=1,
                max_resets=1,
            )
        assert provider.calls == 1
        assert session.step_calls == 0
        assert not policy.has_pending_action
    finally:
        _abort_after_selection_failure(policy)


def test_game_over_rejects_non_reset_and_accepts_reset(artifact_root: Path) -> None:
    game_over = _observation(
        0,
        state=GameStateName.GAME_OVER,
        available_actions=(ActionName.RESET,),
    )
    non_reset_provider = _Provider()
    rejected = StrongwizOperatorPolicy(
        _config(artifact_root / "rejected", run_id="game-over-non-reset"),
        non_reset_provider,
    )
    try:
        with pytest.raises(InvalidActionError, match="legal action aperture"):
            rejected.select(game_over)
        assert not rejected.has_pending_action
        assert rejected.actions == 0
        assert rejected.resets == 0
    finally:
        _abort_after_selection_failure(rejected)

    reset_provider = _Provider(action={"name": ActionName.RESET.value, "coordinate": None})
    accepted = StrongwizOperatorPolicy(
        _config(artifact_root / "accepted", run_id="game-over-reset"),
        reset_provider,
    )
    reset = accepted.select(game_over)
    assert reset == ActionRequest(ActionName.RESET)
    accepted.accept_consequence(_observation(1))
    accepted.close()
    assert accepted.actions == 0
    assert accepted.resets == 1
    assert accepted.closed


def test_game_over_never_synthesizes_unexposed_reset(artifact_root: Path) -> None:
    game_over_without_reset = _observation(
        0,
        state=GameStateName.GAME_OVER,
        available_actions=(ActionName.ACTION1,),
    )
    provider = _Provider(action={"name": ActionName.RESET.value, "coordinate": None})
    policy = StrongwizOperatorPolicy(
        _config(artifact_root, run_id="game-over-reset-not-exposed"),
        provider,
    )
    try:
        with pytest.raises(InvalidActionError, match="legal action aperture"):
            policy.select(game_over_without_reset)
        assert provider.last_request is not None
        assert provider.last_request["available_actions"] == []
        assert policy.actions == 0
        assert policy.resets == 0
    finally:
        _abort_after_selection_failure(policy)


def test_duplicate_pending_selection_is_rejected(artifact_root: Path) -> None:
    provider = _Provider()
    policy = StrongwizOperatorPolicy(
        _config(artifact_root, run_id="duplicate-pending-selection"),
        provider,
    )
    before = _observation(0)

    first = policy.select(before)
    assert first == ActionRequest(ActionName.ACTION1)
    with pytest.raises(PolicyError, match="one pending action must be assessed"):
        policy.select(before)
    assert provider.calls == 1
    assert policy.has_pending_action

    policy.accept_consequence(_observation(1))
    policy.close()
    assert policy.actions == 1
    assert policy.closed


def test_raw_consequence_receipt_precedes_derived_assessment_fault(
    artifact_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    policy = StrongwizOperatorPolicy(
        _config(artifact_root, run_id="derived-assessment-fault"),
        _Provider(),
    )
    policy.select(_observation(0))

    def fail_derived_assessment(
        _self: StrongwizOperatorPolicy,
        *_args: object,
        **_kwargs: object,
    ) -> NoReturn:
        raise EvaluationError("injected derived assessment fault")

    monkeypatch.setattr(StrongwizOperatorPolicy, "_prediction_checks", fail_derived_assessment)
    with pytest.raises(EvaluationError, match="injected derived assessment fault"):
        policy.accept_consequence(_observation(1))

    projection = _ledger_projection(policy.ledger_path)
    assert projection[-1][0] == "environment.consequence"
    assert projection[-1][1]["schema"] == "arc3.returned-consequence.v0.1"
    assert projection[-1][1]["available_actions"] == ["ACTION1", "ACTION6", "RESET"]
    assert "strongwiz.assessment" not in {kind for kind, _payload in projection}
    assert policy.has_pending_action
    assert policy.actions == 1

    policy.abort(
        reason="derived assessment fault after raw receipt", environment_effect_unknown=False
    )
    assert policy.closed
