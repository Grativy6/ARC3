"""Regression tests for the frozen Strongwiz one-shot run boundary."""

from __future__ import annotations

import argparse
import json
import sqlite3
import time
from collections.abc import Iterator, Mapping
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, ClassVar, NoReturn, cast

import pytest
from scripts import run_strongwiz_operator as runner

from arc3.adapters import GridFrame, Observation
from arc3.errors import EvaluationError
from arc3.evaluation.strongwiz_operator import (
    OPERATOR_RECEIPT_SCHEMA,
    OPERATOR_RESPONSE_SCHEMA,
    StrongwizOperatorConfig,
    StrongwizOperatorPolicy,
    StrongwizSourceIdentity,
)
from arc3.types import ActionName, GameId, GameStateName, JSONValue

ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOT = ROOT / "playground" / "vendor" / "strongwiz"
SOURCE_ARCHIVE = ROOT / "playground" / "tmp" / "strongwiz-6944642.tar"
NETWORK_TRIPLET: dict[str, str] = {
    "policy_network_mode": "external-hosted-codex-operator",
    "environment_acquisition_network_mode": "official-public-normal",
    "environment_runtime_network_mode": "offline-local",
}


@pytest.fixture
def artifact_root() -> Iterator[Path]:
    """Keep every synthetic ledger and result inside the clean-room checkout."""

    with TemporaryDirectory(
        prefix="pytest-strongwiz-clean-run-",
        dir=ROOT / "playground" / "tmp",
    ) as directory:
        yield Path(directory)


def _canonical_args(command: str = "play") -> argparse.Namespace:
    argv = [command, "--protocol-sha256", runner.FROZEN_PROTOCOL_SHA256]
    if command == "play":
        argv.extend(("--run-id", "synthetic-clean-run", "--frozen-commit", "b" * 40))
    return runner.build_parser().parse_args(argv)


def test_frozen_arguments_accept_only_the_canonical_clean_run() -> None:
    args = _canonical_args()

    runner._validate_frozen_arguments(args)

    assert args.protocol.resolve() == runner.DEFAULT_PROTOCOL.resolve()
    assert args.exposure_ledger.resolve() == runner.DEFAULT_EXPOSURE.resolve()
    assert args.protocol_sha256 == runner.FROZEN_PROTOCOL_SHA256
    assert args.max_actions == runner.FROZEN_MAX_ACTIONS == 4096
    assert args.max_resets == runner.FROZEN_MAX_RESETS == 64


@pytest.mark.parametrize(
    ("attribute", "override"),
    [
        ("protocol", ROOT / "playground" / "tmp" / "alternate-protocol.md"),
        ("protocol_sha256", "0" * 64),
        ("exposure_ledger", ROOT / "playground" / "tmp" / "alternate-exposure.jsonl"),
        ("game_id", "opaque-alternate-target"),
        ("seed", 1),
        ("max_actions", 4095),
        ("max_resets", 63),
    ],
)
def test_frozen_arguments_reject_every_specimen_override(
    attribute: str,
    override: object,
) -> None:
    args = _canonical_args()
    setattr(args, attribute, override)

    with pytest.raises(EvaluationError, match=rf"{attribute.replace('_', '-')} is frozen"):
        runner._validate_frozen_arguments(args)


class _FrozenValidationProbe(RuntimeError):
    pass


@pytest.mark.parametrize("entrypoint", (runner._acquire, runner._play))
def test_acquire_and_play_validate_freeze_before_any_boundary(
    entrypoint: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    args = _canonical_args("acquire" if entrypoint is runner._acquire else "play")

    def stop_at_freeze(_args: argparse.Namespace) -> NoReturn:
        raise _FrozenValidationProbe

    monkeypatch.setattr(runner, "_validate_frozen_arguments", stop_at_freeze)
    with pytest.raises(_FrozenValidationProbe):
        entrypoint(args)


def _acquisition_events() -> list[dict[str, Any]]:
    intent_hash = "synthetic-acquisition-intent"
    common = {
        "environment_acquisition_network_mode": runner.ACQUISITION_NETWORK_MODE,
        "frame_exposed_to_operator": False,
        "game_id": runner.DEFAULT_TARGET,
        "protocol_sha256": runner.FROZEN_PROTOCOL_SHA256,
        "seed": runner.FROZEN_SEED,
        "setup_network_mode": "official-NORMAL-anonymous-networked-acquisition",
    }
    return [
        {
            "event_hash": intent_hash,
            "event_type": "strongwiz.asset-acquisition.intent",
            "payload": dict(common),
        },
        {
            "event_hash": "synthetic-acquisition-completed",
            "event_type": "strongwiz.asset-acquisition.completed",
            "payload": {**common, "intent_event_hash": intent_hash},
        },
    ]


class _MemoryExposureLedger:
    last_instance: ClassVar[_MemoryExposureLedger | None] = None

    def __init__(self, _path: Path, *, events: list[dict[str, Any]] | None = None) -> None:
        self._events = list(_acquisition_events() if events is None else events)
        type(self).last_instance = self

    def events(self) -> list[dict[str, Any]]:
        return list(self._events)

    def append(self, event_type: str, payload: Mapping[str, object]) -> dict[str, Any]:
        event = {
            "event_hash": f"synthetic-event-{len(self._events):04d}",
            "event_type": event_type,
            "payload": dict(payload),
        }
        self._events.append(event)
        return event


def _last_memory_ledger() -> _MemoryExposureLedger:
    ledger = _MemoryExposureLedger.last_instance
    if ledger is None:
        raise AssertionError("synthetic exposure ledger was not constructed")
    return ledger


def test_one_shot_ledger_rejects_reacquisition_and_second_measured_intent() -> None:
    already_started = _MemoryExposureLedger(
        runner.DEFAULT_EXPOSURE,
        events=[
            {
                "event_hash": "existing-strongwiz-event",
                "event_type": "strongwiz.asset-acquisition.intent",
                "payload": {},
            }
        ],
    )
    with pytest.raises(EvaluationError, match="setup exposure is already consumed"):
        runner._require_new_acquisition(cast(Any, already_started))

    measured_events = _acquisition_events()
    measured_events.append(
        {
            "event_hash": "existing-measured-intent",
            "event_type": "strongwiz.measured-run.intent",
            "payload": {},
        }
    )
    measured = _MemoryExposureLedger(runner.DEFAULT_EXPOSURE, events=measured_events)
    with pytest.raises(EvaluationError, match="measured run is already consumed"):
        runner._require_new_measured_run(
            cast(Any, measured),
            game_id=runner.DEFAULT_TARGET,
            protocol_sha256=runner.FROZEN_PROTOCOL_SHA256,
            seed=runner.FROZEN_SEED,
        )


def test_exposure_reservation_is_exclusive_and_recoverable(artifact_root: Path) -> None:
    exposure = artifact_root / "exposure.jsonl"
    lock = exposure.with_name(f"{exposure.name}.reservation.lock")

    with runner._exclusive_exposure_reservation(exposure):
        assert lock.is_file()
        with pytest.raises(EvaluationError, match="reservation is active"):
            with runner._exclusive_exposure_reservation(exposure):
                raise AssertionError("a second reservation must never enter")
    assert not lock.exists()

    with runner._exclusive_exposure_reservation(exposure):
        assert lock.is_file()
    assert not lock.exists()


def test_resource_guard_enforces_every_frozen_ceiling(
    artifact_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    guard = runner._ResourceGuard(artifact_root, 0.0)
    monkeypatch.setattr(time, "monotonic", lambda: 1.0)
    monkeypatch.setattr(
        runner,
        "_peak_rss_bytes",
        lambda: (runner.MAX_MEMORY_BYTES + 1, "synthetic-peak-rss"),
    )
    monkeypatch.setattr(runner, "_directory_bytes", lambda _path: 0)
    with pytest.raises(EvaluationError, match="memory ceiling at synthetic-memory"):
        guard.enforce(boundary="synthetic-memory")

    monkeypatch.setattr(
        runner,
        "_peak_rss_bytes",
        lambda: (runner.MAX_MEMORY_BYTES, "synthetic-peak-rss"),
    )
    monkeypatch.setattr(
        runner,
        "_directory_bytes",
        lambda _path: runner.MAX_EVIDENCE_BYTES - runner.RESULT_EVIDENCE_RESERVE_BYTES + 1,
    )
    with pytest.raises(EvaluationError, match="evidence-byte ceiling at synthetic-evidence"):
        guard.enforce(boundary="synthetic-evidence")

    monkeypatch.setattr(runner, "_directory_bytes", lambda _path: 0)
    monkeypatch.setattr(
        time,
        "monotonic",
        lambda: float(runner.MAX_WALL_CLOCK_SECONDS),
    )
    with pytest.raises(EvaluationError, match="wall ceiling at synthetic-wall"):
        guard.enforce(boundary="synthetic-wall")


def test_resource_guard_counts_external_evidence_growth_from_its_baseline(
    artifact_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_root = artifact_root / "run"
    run_root.mkdir()
    exposure = artifact_root / "exposure.jsonl"
    exposure.write_bytes(b"prior-acquisition")
    guard = runner._ResourceGuard(
        run_root,
        time.monotonic(),
        external_evidence_files=(exposure,),
    )
    (run_root / "trace.jsonl").write_bytes(b"trace")
    with exposure.open("ab") as handle:
        handle.write(b"-measured")
    monkeypatch.setattr(
        runner,
        "_peak_rss_bytes",
        lambda: (1024, "synthetic-peak-rss"),
    )

    snapshot = guard.snapshot(boundary="synthetic-external-evidence")

    assert snapshot["evidence_run_root_bytes"] == len(b"trace")
    assert snapshot["evidence_external_delta_bytes"] == len(b"-measured")
    assert snapshot["evidence_bytes"] == len(b"trace-measured")


class _AdapterStub:
    open_calls: ClassVar[int] = 0
    recordings_dir: ClassVar[Path | None] = None

    def __init__(self, *_args: object, **kwargs: object) -> None:
        type(self).recordings_dir = Path(cast(str | Path, kwargs["recordings_dir"]))

    def open(self, _game_id: str, *, seed: int) -> object:
        assert seed == runner.FROZEN_SEED
        type(self).open_calls += 1
        return object()


class _PolicyStub:
    actions = 0
    resets = 0
    completion_genuinely_observed = False
    environment_effect_unknown = False

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        pass

    def mark_submission_started(self) -> None:
        return None

    def mark_environment_returned(self, _observation: Observation) -> None:
        return None

    def close(self) -> None:
        return None

    def abort(self, *, reason: str, environment_effect_unknown: bool) -> None:
        del reason, environment_effect_unknown


class _JournalStub:
    def __init__(self, *_args: object, **_kwargs: object) -> None:
        pass

    def verify_manifest(self, *, include_active: bool) -> tuple[object, ...]:
        assert include_active
        return ()

    def close(self) -> None:
        return None


class _TraceSinkStub:
    def __init__(self, *_args: object, **_kwargs: object) -> None:
        pass


class _SocketGuardStub:
    def __init__(self) -> None:
        self.attempt_count = 0

    def install(self) -> None:
        return None

    def restore(self) -> None:
        return None


def _synthetic_episode(
    *_args: object,
    **_kwargs: object,
) -> tuple[None, dict[str, object]]:
    return None, {"environment_actions": 0, "resets": 0}


def _assert_network_triplet(payload: Mapping[str, object]) -> None:
    assert {field: payload.get(field) for field in NETWORK_TRIPLET} == NETWORK_TRIPLET


def test_result_and_measured_receipts_repeat_the_exact_network_triplet(
    artifact_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(runner, "DEFAULT_OUTPUT", artifact_root)
    monkeypatch.setattr(runner, "PublicExposureLedger", _MemoryExposureLedger)
    monkeypatch.setattr(runner, "ArcAGIAdapter", _AdapterStub)
    monkeypatch.setattr(runner, "StrongwizOperatorPolicy", _PolicyStub)
    monkeypatch.setattr(runner, "EventJournal", _JournalStub)
    monkeypatch.setattr(runner, "BaselineTraceSink", _TraceSinkStub)
    monkeypatch.setattr(runner, "_OfflineSocketGuard", _SocketGuardStub)
    monkeypatch.setattr(runner, "run_public_episode", _synthetic_episode)
    monkeypatch.setattr(runner, "_target_entry", lambda *_args: None)
    monkeypatch.setattr(runner, "validate_frozen_source", lambda *_args: None)
    monkeypatch.setattr(runner, "verify_strongwiz_source", lambda *_args: {})
    _AdapterStub.open_calls = 0
    _AdapterStub.recordings_dir = None
    _MemoryExposureLedger.last_instance = None
    args = _canonical_args()

    result = runner._play(args)

    assert result["failure"] is None
    assert _AdapterStub.open_calls == 1
    assert _AdapterStub.recordings_dir == (
        artifact_root / "runs" / args.run_id / "official-recordings"
    )
    _assert_network_triplet(cast(dict[str, object], result))
    written = cast(
        dict[str, object],
        json.loads(
            (artifact_root / "runs" / args.run_id / "result.json").read_text(encoding="utf-8")
        ),
    )
    _assert_network_triplet(written)
    ledger = _last_memory_ledger()
    measured = {
        cast(str, event["event_type"]): cast(dict[str, object], event["payload"])
        for event in ledger.events()
        if str(event["event_type"]).startswith("strongwiz.measured-run.")
    }
    assert set(measured) == {
        "strongwiz.measured-run.intent",
        "strongwiz.measured-run.completed",
    }
    for payload in measured.values():
        _assert_network_triplet(payload)


def _source_identity() -> StrongwizSourceIdentity:
    return StrongwizSourceIdentity(source_root=SOURCE_ROOT, archive_path=SOURCE_ARCHIVE)


def _operator_config(artifact_root: Path, *, run_id: str) -> StrongwizOperatorConfig:
    return StrongwizOperatorConfig(
        repository_root=ROOT,
        source=_source_identity(),
        run_id=run_id,
        game_id="opaque-clean-run-fixture",
        artifact_root=artifact_root,
        protocol_sha256=runner.FROZEN_PROTOCOL_SHA256,
        bridge_commit="b" * 40,
        max_actions=runner.FROZEN_MAX_ACTIONS,
        max_resets=runner.FROZEN_MAX_RESETS,
    )


def _observation(
    value: int,
    *,
    available_actions: tuple[ActionName, ...],
) -> Observation:
    return Observation(
        game_id=GameId("opaque-clean-run-fixture"),
        frames=(GridFrame(((value, 0), (0, 0))),),
        state=GameStateName.NOT_FINISHED,
        levels_completed=0,
        win_levels=1,
        available_actions=available_actions,
    )


def _valid_response(request: Mapping[str, JSONValue]) -> Mapping[str, object]:
    return {
        "schema": OPERATOR_RESPONSE_SCHEMA,
        "request_sha256": cast(str, request["request_sha256"]),
        "sequence": cast(int, request["sequence"]),
        "action": {"name": ActionName.ACTION1.value, "coordinate": None},
        "distinction": {
            "statement": "Whether the synthetic action changes the returned frame",
            "candidate_resolutions": ("frame changes", "frame repeats"),
            "competing_predictions": ("digest differs", "digest remains equal"),
            "decision_effects": ("movement",),
            "decision_that_could_change": "the next synthetic contract probe",
            "relevance_summary": "The returned frame distinguishes the fixture alternatives",
            "smallest_discriminating_test": "one synthetic action and consequence",
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
        "concise_rationale": "One bounded synthetic probe distinguishes the alternatives",
        "reversible": True,
        "expected_progress_rank": 1,
        "information_gain_rank": 1,
        "risk_rank": 0,
    }


def _receipt_projection(path: Path, kind: str) -> tuple[dict[str, object], dict[str, object]]:
    with closing(sqlite3.connect(path)) as connection:
        row = connection.execute(
            """SELECT receipts.envelope_json, objects.canonical_payload
               FROM receipts
               JOIN objects ON objects.payload_hash = receipts.payload_hash
               WHERE receipts.kind = ?
               ORDER BY receipts.sequence DESC
               LIMIT 1""",
            (kind,),
        ).fetchone()
    assert row is not None
    envelope = cast(dict[str, object], json.loads(bytes(row[0])))
    payload = cast(dict[str, object], json.loads(bytes(row[1])))
    return envelope, payload


def _ledger_object(path: Path, object_ref: str) -> dict[str, object]:
    with closing(sqlite3.connect(path)) as connection:
        row = connection.execute(
            "SELECT canonical_payload FROM objects WHERE payload_hash = ?",
            (object_ref,),
        ).fetchone()
    assert row is not None
    return cast(dict[str, object], json.loads(bytes(row[0])))


def _ledger_object_refs(path: Path) -> set[str]:
    with closing(sqlite3.connect(path)) as connection:
        rows = connection.execute("SELECT payload_hash FROM objects").fetchall()
    return {str(row[0]) for row in rows}


def test_post_return_assessment_fault_counts_action_and_preserves_raw_observation(
    artifact_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    policy = StrongwizOperatorPolicy(
        _operator_config(artifact_root, run_id="post-return-assessment-fault"),
        _valid_response,
    )
    before = _observation(
        0,
        available_actions=(ActionName.ACTION1, ActionName.ACTION6, ActionName.RESET),
    )
    after_actions = (ActionName.ACTION2, ActionName.ACTION6, ActionName.RESET)
    after = _observation(1, available_actions=after_actions)
    policy.select(before)
    policy.mark_submission_started()
    policy.mark_environment_returned(after)

    def fail_assessment(
        _self: StrongwizOperatorPolicy,
        *_args: object,
        **_kwargs: object,
    ) -> NoReturn:
        raise EvaluationError("synthetic post-return assessment fault")

    monkeypatch.setattr(StrongwizOperatorPolicy, "_prediction_checks", fail_assessment)
    with pytest.raises(EvaluationError, match="post-return assessment fault"):
        policy.accept_consequence(after)

    assert policy.actions == 1
    assert policy.resets == 0
    assert not policy.environment_effect_unknown
    envelope, payload = _receipt_projection(policy.ledger_path, "environment.consequence")
    assert payload["available_actions"] == [item.value for item in after_actions]
    assert payload["after_frames"] == [str(frame.digest) for frame in after.frames]
    runtime_frames = cast(list[dict[str, object]], payload["runtime_frames"])
    runtime_refs = {cast(str, frame["evidence_ref"]) for frame in runtime_frames}
    assert runtime_refs <= _ledger_object_refs(policy.ledger_path)
    assert cast(list[str], envelope["object_refs"])

    policy.abort(
        reason="synthetic assessment failure after returned consequence",
        environment_effect_unknown=False,
    )
    receipt = cast(
        dict[str, object],
        json.loads((artifact_root / "operator-receipt.json").read_text(encoding="utf-8")),
    )
    assert receipt["actions"] == 1
    assert receipt["resets"] == 0


def test_assessment_refs_resolve_after_observation_and_operator_network_receipt(
    artifact_root: Path,
) -> None:
    policy = StrongwizOperatorPolicy(
        _operator_config(artifact_root, run_id="assessment-after-observation-ref"),
        _valid_response,
    )
    before = _observation(
        0,
        available_actions=(ActionName.ACTION1, ActionName.RESET),
    )
    after = _observation(
        1,
        available_actions=(ActionName.ACTION2, ActionName.RESET),
    )

    policy.select(before)
    policy.accept_consequence(after)
    assessment_envelope, assessment = _receipt_projection(
        policy.ledger_path,
        "strongwiz.assessment",
    )
    outcome_ref = cast(str, assessment["outcome_ref"])
    outcome = _ledger_object(policy.ledger_path, outcome_ref)
    after_ref = cast(str, outcome["observation_after_ref"])
    assert after_ref in cast(list[str], assessment_envelope["object_refs"])
    stored_after = _ledger_object(policy.ledger_path, after_ref)
    assert stored_after["observation_id"] == outcome["observation_after_id"]

    policy.close()
    receipt = cast(
        dict[str, object],
        json.loads((artifact_root / "operator-receipt.json").read_text(encoding="utf-8")),
    )
    assert receipt["schema"] == OPERATOR_RECEIPT_SCHEMA
    _assert_network_triplet(receipt)
    _runtime_envelope, runtime_source = _receipt_projection(policy.ledger_path, "runtime.source")
    _assert_network_triplet(runtime_source)
