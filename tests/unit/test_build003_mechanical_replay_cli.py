from __future__ import annotations

import ast
import copy
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from scripts import replay_build003_mechanical_recording as replay_cli

import arc3.evaluation.mechanical_replay as mechanical_replay_module
from arc3.evaluation.artifacts import canonical_json_bytes, seal_object, sha256_bytes


def _campaign_audit(
    tmp_path: Path, *, verifier_passed: bool = True
) -> tuple[Path, dict[str, object]]:
    evaluation_root = tmp_path / "evaluation"
    evaluation_root.mkdir(parents=True)
    (evaluation_root / "recording.jsonl").write_bytes(b"recording-placeholder\n")
    audit = seal_object(
        {
            "audit_conclusion": {
                "completion_genuinely_observed": False,
                "final_environment_state": "NOT_FINISHED",
                "integrity_verified": True,
            },
            "campaign": {
                "evaluation_id": "synthetic-campaign",
                "frozen_git_commit": "a" * 40,
                "game_id": "synthetic-recording",
                "holdout_consumed": False,
                "partition": "development",
                "source_semantically_inspected": False,
                "surface": "local-public",
            },
            "completion": {
                "authoritative_completion_state": "NOT_FINISHED",
                "completion_observed": False,
                "levels_completed": 0,
                "metric_final_state": "NOT_FINISHED",
                "non_reset_environment_action_count": 1,
                "official_run_action_count": 1,
                "official_run_state": "NOT_FINISHED",
                "raw_final_state": "NOT_FINISHED",
                "score_completed": False,
                "submission_count": 1,
                "win_levels": 2,
            },
            "hashes_and_seals": {
                "trace_manifest_object_hash": "sha256:" + "b" * 64,
                "trace_manifest_object_hash_verified": False,
            },
            "recording": {
                "byte_length": 22,
                "consequence_count_excluding_initial_observation": 1,
                "event_count_including_initial_reset_observation": 2,
                "final_observation": {
                    "levels_completed": 0,
                    "state": "NOT_FINISHED",
                    "win_levels": 2,
                },
                "initial_action": "RESET",
                "path": "recording.jsonl",
                "sha256": "sha256:" + "c" * 64,
            },
            "schema": replay_cli.LEGACY_CAMPAIGN_AUDIT_SCHEMA,
            "scope": {
                "evaluation_root": str(evaluation_root),
                "holdout_accessed": False,
                "read_only_campaign_audit": True,
                "target_game_source_inspected": False,
            },
            "verification": {
                "authoritative_public_evaluation_verifier": {
                    "errors": [] if verifier_passed else ["synthetic failure"],
                    "evaluation_id": "synthetic-campaign",
                    "verified": verifier_passed,
                }
            },
        },
        hash_field="audit_receipt_hash",
    )
    path = tmp_path / "campaign-audit.json"
    path.write_bytes(canonical_json_bytes(audit))
    return path, audit


def _reset_aware_campaign_audit(tmp_path: Path) -> tuple[Path, dict[str, Any]]:
    evaluation_root = tmp_path / "evaluation"
    evaluation_root.mkdir(parents=True)
    (evaluation_root / "recording.jsonl").write_bytes(b"recording-placeholder\n")
    audit = seal_object(
        {
            "audit_conclusion": {
                "completion_genuinely_observed": False,
                "final_environment_state": "NOT_FINISHED",
                "integrity_verified": True,
            },
            "campaign": {
                "evaluation_id": "synthetic-reset-campaign",
                "frozen_git_commit": "a" * 40,
                "game_id": "synthetic-recording",
                "holdout_consumed": False,
                "partition": "development",
                "source_semantically_inspected": False,
                "surface": "local-public",
            },
            "completion": {
                "authoritative_completion_state": "NOT_FINISHED",
                "completion_observed": False,
                "levels_completed": 1,
                "metric_final_state": "NOT_FINISHED",
                "non_reset_environment_action_count": 2,
                "official_run_action_count": 3,
                "official_run_state": "GAME_OVER",
                "raw_final_state": "NOT_FINISHED",
                "reset_count": 1,
                "score_boundary_consistent": True,
                "score_completed": False,
                "submission_count": 3,
                "win_levels": 2,
            },
            "hashes_and_seals": {
                "trace_manifest_object_hash": "sha256:" + "b" * 64,
                "trace_manifest_object_hash_verified": False,
            },
            "recording": {
                "byte_length": 22,
                "consequence_count_excluding_initial_observation": 3,
                "consequence_state_counts": {"GAME_OVER": 1, "NOT_FINISHED": 2},
                "event_count_including_initial_reset_observation": 4,
                "final_observation": {
                    "levels_completed": 1,
                    "state": "NOT_FINISHED",
                    "win_levels": 2,
                },
                "game_over_events": 1,
                "initial_action": "RESET",
                "path": "recording.jsonl",
                "sha256": "sha256:" + "c" * 64,
                "submitted_action_id_counts": {"ACTION6": 2, "RESET": 1},
                "win_events": 0,
            },
            "schema": replay_cli.CAMPAIGN_AUDIT_SCHEMA,
            "scope": {
                "evaluation_root": str(evaluation_root),
                "holdout_accessed": False,
                "read_only_campaign_audit": True,
                "target_game_source_inspected": False,
            },
            "verification": {
                "authoritative_public_evaluation_verifier": {
                    "errors": [],
                    "evaluation_id": "synthetic-reset-campaign",
                    "verified": True,
                }
            },
        },
        hash_field="audit_receipt_hash",
    )
    path = tmp_path / "campaign-audit-v2.json"
    path.write_bytes(canonical_json_bytes(audit))
    return path, audit


def _reseal_audit(path: Path, audit: dict[str, Any]) -> dict[str, Any]:
    unsigned = copy.deepcopy(audit)
    unsigned.pop("audit_receipt_hash", None)
    sealed = seal_object(unsigned, hash_field="audit_receipt_hash")
    path.write_bytes(canonical_json_bytes(sealed))
    return sealed


def test_campaign_binding_authenticates_and_derives_the_recording_contract(
    tmp_path: Path,
) -> None:
    path, audit = _campaign_audit(tmp_path)

    binding, recording, expected = replay_cli._campaign_binding(
        campaign_audit=path,
        expected_file_sha256=sha256_bytes(path.read_bytes()),
        expected_object_hash=str(audit["audit_receipt_hash"]),
        expected_evaluation_id="synthetic-campaign",
    )

    assert recording == (tmp_path / "evaluation" / "recording.jsonl").resolve()
    assert expected == {
        "byte_length": 22,
        "final_state": "NOT_FINISHED",
        "game_id": "synthetic-recording",
        "levels_completed": 0,
        "recording_sha256": "sha256:" + "c" * 64,
        "row_count": 2,
        "submission_count": 1,
        "win_levels": 2,
    }
    assert binding["authoritative_public_verifier"] is True
    assert binding["audit_schema"] == replay_cli.LEGACY_CAMPAIGN_AUDIT_SCHEMA
    assert binding["trace_manifest_object_hash_verified"] is False


def test_reset_aware_campaign_binding_preserves_raw_and_score_boundary_states(
    tmp_path: Path,
) -> None:
    path, audit = _reset_aware_campaign_audit(tmp_path)

    binding, recording, expected = replay_cli._campaign_binding(
        campaign_audit=path,
        expected_file_sha256=sha256_bytes(path.read_bytes()),
        expected_object_hash=str(audit["audit_receipt_hash"]),
        expected_evaluation_id="synthetic-reset-campaign",
    )

    assert recording == (tmp_path / "evaluation" / "recording.jsonl").resolve()
    assert expected == {
        "byte_length": 22,
        "final_state": "NOT_FINISHED",
        "game_id": "synthetic-recording",
        "levels_completed": 1,
        "recording_sha256": "sha256:" + "c" * 64,
        "row_count": 4,
        "submission_count": 3,
        "win_levels": 2,
    }
    assert binding["audit_schema"] == replay_cli.CAMPAIGN_AUDIT_SCHEMA
    assert binding["official_run_state"] == "GAME_OVER"
    assert binding["replay_final_state"] == "NOT_FINISHED"
    assert binding["non_reset_environment_action_count"] == 2
    assert binding["reset_count"] == 1


def test_reset_aware_campaign_binding_counts_resets_and_game_overs_independently(
    tmp_path: Path,
) -> None:
    path, audit = _reset_aware_campaign_audit(tmp_path)
    audit["completion"].update(
        {
            "official_run_action_count": 4,
            "reset_count": 2,
            "submission_count": 4,
        }
    )
    audit["recording"].update(
        {
            "consequence_count_excluding_initial_observation": 4,
            "consequence_state_counts": {"GAME_OVER": 1, "NOT_FINISHED": 3},
            "event_count_including_initial_reset_observation": 5,
            "submitted_action_id_counts": {"ACTION6": 2, "RESET": 2},
        }
    )
    audit = _reseal_audit(path, audit)

    binding, _, expected = replay_cli._campaign_binding(
        campaign_audit=path,
        expected_file_sha256=sha256_bytes(path.read_bytes()),
        expected_object_hash=str(audit["audit_receipt_hash"]),
        expected_evaluation_id="synthetic-reset-campaign",
    )

    assert binding["reset_count"] == 2
    assert expected["submission_count"] == 4
    assert expected["row_count"] == 5


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (
            lambda audit: audit["completion"].update({"non_reset_environment_action_count": 3}),
            "reset-aware action-accounting",
        ),
        (
            lambda audit: audit["completion"].update({"official_run_state": "NOT_FINISHED"}),
            "official score-boundary state",
        ),
        (
            lambda audit: audit["completion"].update({"raw_final_state": "GAME_OVER"}),
            "authoritative NOT_FINISHED boundary",
        ),
        (
            lambda audit: audit["recording"].update({"submitted_action_id_counts": {"ACTION6": 3}}),
            "submitted-action counts",
        ),
        (
            lambda audit: audit["recording"].update(
                {"consequence_state_counts": {"NOT_FINISHED": 3}}
            ),
            "consequence-state counts",
        ),
        (
            lambda audit: audit["recording"].update({"win_events": 1}),
            "consequence-state counts",
        ),
        (
            lambda audit: audit["recording"].update(
                {
                    "consequence_state_counts": {"GAME_OVER": 3},
                    "game_over_events": 3,
                }
            ),
            "consequence-state counts",
        ),
    ],
)
def test_reset_aware_campaign_binding_fails_closed_on_count_or_state_mismatch(
    tmp_path: Path,
    mutate: Callable[[dict[str, Any]], None],
    message: str,
) -> None:
    path, audit = _reset_aware_campaign_audit(tmp_path)
    mutate(audit)
    audit = _reseal_audit(path, audit)

    with pytest.raises(ValueError, match=message):
        replay_cli._campaign_binding(
            campaign_audit=path,
            expected_file_sha256=sha256_bytes(path.read_bytes()),
            expected_object_hash=str(audit["audit_receipt_hash"]),
            expected_evaluation_id="synthetic-reset-campaign",
        )


def test_campaign_binding_rejects_hash_and_authoritative_verifier_failures(
    tmp_path: Path,
) -> None:
    path, audit = _campaign_audit(tmp_path)
    file_sha256 = sha256_bytes(path.read_bytes())

    with pytest.raises(ValueError, match="file SHA-256"):
        replay_cli._campaign_binding(
            campaign_audit=path,
            expected_file_sha256="0" * 64,
            expected_object_hash=str(audit["audit_receipt_hash"]),
            expected_evaluation_id="synthetic-campaign",
        )
    with pytest.raises(ValueError, match="object hash"):
        replay_cli._campaign_binding(
            campaign_audit=path,
            expected_file_sha256=file_sha256,
            expected_object_hash="sha256:" + "0" * 64,
            expected_evaluation_id="synthetic-campaign",
        )

    failed_path, failed = _campaign_audit(tmp_path / "failed", verifier_passed=False)
    with pytest.raises(ValueError, match="authoritative public verifier"):
        replay_cli._campaign_binding(
            campaign_audit=failed_path,
            expected_file_sha256=sha256_bytes(failed_path.read_bytes()),
            expected_object_hash=str(failed["audit_receipt_hash"]),
            expected_evaluation_id="synthetic-campaign",
        )


def test_receipt_write_is_exclusive(tmp_path: Path) -> None:
    output = tmp_path / "receipt.json"
    replay_cli._write_exclusive(output, {"status": "PASS_RECORDED_FRAME_REPLAY"})

    assert output.read_bytes() == canonical_json_bytes({"status": "PASS_RECORDED_FRAME_REPLAY"})
    with pytest.raises(RuntimeError, match="already exists"):
        replay_cli._write_exclusive(output, {"status": "different"})


def test_replay_sources_do_not_import_official_execution_surfaces() -> None:
    replay_module_path = mechanical_replay_module.__file__
    assert replay_module_path is not None
    paths = (
        Path(replay_cli.__file__),
        Path(replay_module_path),
    )
    forbidden = {"arc_agi", "arcengine"}

    for path in paths:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        imported = {
            node.module.split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module is not None
        }
        imported.update(
            alias.name.split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        )
        assert imported.isdisjoint(forbidden)


def test_cli_accepts_an_explicit_sealed_trace_contract(tmp_path: Path) -> None:
    trace_root = tmp_path / "trace"
    output = tmp_path / "receipt.json"
    args = replay_cli._parser().parse_args(
        [
            "--sealed-trace-root",
            str(trace_root),
            "--expected-trace-run-id",
            "synthetic-run",
            "--expected-trace-game-id",
            "synthetic-game",
            "--expected-trace-generator-commit",
            "c" * 40,
            "--expected-trace-manifest-hash",
            "1" * 64,
            "--expected-trace-tail-event-hash",
            "2" * 64,
            "--expected-trace-event-count",
            "950",
            "--expected-trace-submission-count",
            "158",
            "--expected-trace-final-state",
            "NOT_FINISHED",
            "--expected-trace-levels-completed",
            "4",
            "--expected-trace-win-levels",
            "6",
            "--expected-commit",
            "a" * 40,
            "--expected-tree",
            "b" * 40,
            "--output",
            str(output),
            "--policy-profile",
            replay_cli.POLICY_PROFILE,
        ]
    )

    assert replay_cli._replay_mode(args) == "sealed-trace"
    assert args.campaign_audit is None
    assert args.sealed_trace_root == trace_root
    assert args.expected_trace_event_count == 950
    assert args.expected_trace_submission_count == 158
    assert args.expected_trace_generator_commit == "c" * 40
    assert replay_cli.TRACE_SCHEMA == "arc3.build003.mechanical-sealed-trace-replay.v0.1"


def test_cli_accepts_the_complete_sealed_trace_prefix_reopening_contract(
    tmp_path: Path,
) -> None:
    args = replay_cli._parser().parse_args(
        [
            "--sealed-trace-root",
            str(tmp_path / "trace"),
            "--expected-trace-run-id",
            "synthetic-run",
            "--expected-trace-game-id",
            "synthetic-game",
            "--expected-trace-generator-commit",
            "c" * 40,
            "--expected-trace-manifest-hash",
            "1" * 64,
            "--expected-trace-tail-event-hash",
            "2" * 64,
            "--expected-trace-event-count",
            "2198",
            "--expected-trace-submission-count",
            "366",
            "--expected-trace-final-state",
            "NOT_FINISHED",
            "--expected-trace-levels-completed",
            "4",
            "--expected-trace-win-levels",
            "6",
            "--expected-trace-reopening-submission",
            "359",
            "--expected-trace-reopening-consequence-event-id",
            "E-synthetic-reopening",
            "--expected-trace-reopening-consequence-event-hash",
            "3" * 64,
            "--expected-trace-reopening-state",
            "NOT_FINISHED",
            "--expected-trace-reopening-levels-completed",
            "4",
            "--expected-trace-reopening-win-levels",
            "6",
            "--expected-trace-reopening-candidate-plan-prefix",
            "affine-crossed-post-deposit-mediator-access:",
            "--expected-commit",
            "a" * 40,
            "--expected-tree",
            "b" * 40,
            "--output",
            str(tmp_path / "receipt.json"),
            "--policy-profile",
            replay_cli.POLICY_PROFILE,
        ]
    )

    assert replay_cli._replay_mode(args) == "sealed-trace-prefix-reopening"
    assert args.expected_trace_reopening_submission == 359
    assert args.expected_trace_reopening_consequence_event_id == "E-synthetic-reopening"
    assert args.expected_trace_reopening_state == "NOT_FINISHED"
    assert args.expected_trace_reopening_candidate_plan_prefix == (
        "affine-crossed-post-deposit-mediator-access:"
    )
    assert (
        replay_cli.TRACE_REOPENING_SCHEMA
        == "arc3.build003.mechanical-sealed-trace-prefix-reopening.v0.1"
    )


def test_cli_rejects_a_partial_sealed_trace_prefix_reopening_contract(
    tmp_path: Path,
) -> None:
    args = replay_cli._parser().parse_args(
        [
            "--sealed-trace-root",
            str(tmp_path / "trace"),
            "--expected-trace-run-id",
            "synthetic-run",
            "--expected-trace-game-id",
            "synthetic-game",
            "--expected-trace-generator-commit",
            "c" * 40,
            "--expected-trace-manifest-hash",
            "1" * 64,
            "--expected-trace-tail-event-hash",
            "2" * 64,
            "--expected-trace-event-count",
            "14",
            "--expected-trace-submission-count",
            "2",
            "--expected-trace-final-state",
            "NOT_FINISHED",
            "--expected-trace-levels-completed",
            "0",
            "--expected-trace-win-levels",
            "2",
            "--expected-trace-reopening-submission",
            "1",
            "--expected-commit",
            "a" * 40,
            "--expected-tree",
            "b" * 40,
            "--output",
            str(tmp_path / "receipt.json"),
            "--policy-profile",
            replay_cli.POLICY_PROFILE,
        ]
    )

    with pytest.raises(
        ValueError,
        match=(
            r"sealed reopening mode is missing required arguments: "
            r".*--expected-trace-reopening-consequence-event-id"
        ),
    ):
        replay_cli._replay_mode(args)


def test_cli_trace_mode_rejects_missing_or_campaign_only_arguments(tmp_path: Path) -> None:
    common = [
        "--sealed-trace-root",
        str(tmp_path / "trace"),
        "--expected-trace-run-id",
        "synthetic-run",
        "--expected-trace-game-id",
        "synthetic-game",
        "--expected-trace-generator-commit",
        "c" * 40,
        "--expected-trace-manifest-hash",
        "1" * 64,
        "--expected-trace-event-count",
        "8",
        "--expected-trace-submission-count",
        "1",
        "--expected-trace-final-state",
        "NOT_FINISHED",
        "--expected-trace-levels-completed",
        "0",
        "--expected-trace-win-levels",
        "2",
        "--expected-commit",
        "a" * 40,
        "--expected-tree",
        "b" * 40,
        "--output",
        str(tmp_path / "receipt.json"),
        "--policy-profile",
        replay_cli.POLICY_PROFILE,
    ]
    missing_tail = replay_cli._parser().parse_args(common)

    with pytest.raises(ValueError, match="--expected-trace-tail-event-hash"):
        replay_cli._replay_mode(missing_tail)

    mixed = replay_cli._parser().parse_args(
        [
            *common,
            "--expected-trace-tail-event-hash",
            "2" * 64,
            "--expected-evaluation-id",
            "incompatible-campaign-value",
        ]
    )
    with pytest.raises(ValueError, match="incompatible arguments: --expected-evaluation-id"):
        replay_cli._replay_mode(mixed)


def test_cli_preserves_the_campaign_recording_contract(tmp_path: Path) -> None:
    args = replay_cli._parser().parse_args(
        [
            "--campaign-audit",
            str(tmp_path / "campaign-audit.json"),
            "--expected-campaign-audit-file-sha256",
            "1" * 64,
            "--expected-campaign-audit-object-hash",
            "2" * 64,
            "--expected-evaluation-id",
            "synthetic-campaign",
            "--expected-commit",
            "a" * 40,
            "--expected-tree",
            "b" * 40,
            "--output",
            str(tmp_path / "receipt.json"),
            "--policy-profile",
            replay_cli.POLICY_PROFILE,
        ]
    )

    assert replay_cli._replay_mode(args) == "campaign-recording"
    assert args.sealed_trace_root is None


def test_cli_sealed_trace_binding_preserves_validated_game_and_generator_identity() -> None:
    binding = replay_cli._sealed_trace_binding(
        {
            "trace": {
                "event_count": 950,
                "game_id": "synthetic-game",
                "manifest_hash": "sha256:" + ("1" * 64),
                "path": "C:/synthetic-trace",
                "run_id": "synthetic-run",
                "submission_count": 158,
                "tail_event_hash": "sha256:" + ("2" * 64),
            }
        },
        generator_commit="c" * 40,
    )

    assert binding["game_id"] == "synthetic-game"
    assert binding["generator_commit"] == "c" * 40
    assert binding["recording_reconstructed"] is False


def test_cli_sealed_trace_prefix_reopening_binding_names_the_divergence_boundary() -> None:
    binding = replay_cli._sealed_trace_binding(
        {
            "reopening_boundary": {
                "candidate_plan_prefix": "affine-crossed-post-deposit-mediator-access:",
                "candidate_plan_signature": (
                    "affine-crossed-post-deposit-mediator-access:synthetic"
                ),
                "consequence_event_hash": "sha256:" + ("3" * 64),
                "consequence_event_id": "E-synthetic-reopening",
                "submission_count": 359,
            },
            "trace": {
                "event_count": 2198,
                "game_id": "synthetic-game",
                "manifest_hash": "sha256:" + ("1" * 64),
                "path": "C:/synthetic-trace",
                "run_id": "synthetic-run",
                "submission_count": 366,
                "tail_event_hash": "sha256:" + ("2" * 64),
            },
        },
        generator_commit="c" * 40,
        replay_mode="sealed-trace-prefix-reopening",
    )

    assert binding["mode"] == "sealed-trace-prefix-reopening"
    assert binding["submission_count"] == 366
    assert binding["reopening_submission_count"] == 359
    assert binding["reopening_consequence_event_id"] == "E-synthetic-reopening"
    assert binding["reopening_consequence_event_hash"] == "sha256:" + ("3" * 64)
    assert binding["reopening_candidate_plan_prefix"] == (
        "affine-crossed-post-deposit-mediator-access:"
    )
    assert binding["reopening_candidate_plan_signature"] == (
        "affine-crossed-post-deposit-mediator-access:synthetic"
    )


def test_cli_main_emits_the_prefix_reopening_schema_and_count_contract(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = tmp_path / "prefix-reopening-receipt.json"
    plan_prefix = "affine-crossed-post-deposit-mediator-access:"
    plan_signature = plan_prefix + "synthetic"
    source_binding = {
        "clean": True,
        "commit": "a" * 40,
        "tree": "b" * 40,
    }

    def source_snapshot(**_kwargs: object) -> tuple[dict[str, object], dict[str, bytes]]:
        return dict(source_binding), {"synthetic": b"source"}

    def replay_trace(_path: Path, **kwargs: object) -> dict[str, object]:
        assert kwargs["expected_reopening_submission_count"] == 359
        assert kwargs["expected_reopening_candidate_plan_prefix"] == plan_prefix
        return {
            "boundaries": {"environment_actions_issued": False},
            "candidate_next_submission": {
                "action": {"coordinate": [53, 28], "name": "ACTION6"},
                "plan_signature": plan_signature,
                "submitted": False,
            },
            "reopening_boundary": {
                "candidate_plan_prefix": plan_prefix,
                "candidate_plan_signature": plan_signature,
                "consequence_event_hash": "sha256:" + ("3" * 64),
                "consequence_event_id": "E-synthetic-reopening",
                "matched_action_and_consequence_through_submission": 359,
                "submission_count": 359,
            },
            "replay_result": {
                "matched_submission_count": 358,
                "status": "PASS_SEALED_TRACE_PREFIX_REOPENING",
            },
            "trace": {
                "event_count": 2198,
                "game_id": "synthetic-game",
                "manifest_hash": "sha256:" + ("1" * 64),
                "path": str(tmp_path / "trace"),
                "run_id": "synthetic-run",
                "submission_count": 366,
                "tail_event_hash": "sha256:" + ("2" * 64),
            },
        }

    monkeypatch.setattr(replay_cli, "_BYTECODE_DISABLED_AT_STARTUP", True)
    monkeypatch.setattr(replay_cli, "_DIRECT_SCRIPT_INVOCATION", True)
    monkeypatch.setattr(replay_cli, "_source_snapshot", source_snapshot)
    monkeypatch.setattr(
        replay_cli,
        "_repository_file_projection",
        lambda: {"synthetic": "sha256:" + ("4" * 64)},
    )
    monkeypatch.setattr(replay_cli, "replay_unfinished_mechanical_trace", replay_trace)

    assert (
        replay_cli.main(
            [
                "--sealed-trace-root",
                str(tmp_path / "trace"),
                "--expected-trace-run-id",
                "synthetic-run",
                "--expected-trace-game-id",
                "synthetic-game",
                "--expected-trace-generator-commit",
                "c" * 40,
                "--expected-trace-manifest-hash",
                "1" * 64,
                "--expected-trace-tail-event-hash",
                "2" * 64,
                "--expected-trace-event-count",
                "2198",
                "--expected-trace-submission-count",
                "366",
                "--expected-trace-final-state",
                "NOT_FINISHED",
                "--expected-trace-levels-completed",
                "4",
                "--expected-trace-win-levels",
                "6",
                "--expected-trace-reopening-submission",
                "359",
                "--expected-trace-reopening-consequence-event-id",
                "E-synthetic-reopening",
                "--expected-trace-reopening-consequence-event-hash",
                "3" * 64,
                "--expected-trace-reopening-state",
                "NOT_FINISHED",
                "--expected-trace-reopening-levels-completed",
                "4",
                "--expected-trace-reopening-win-levels",
                "6",
                "--expected-trace-reopening-candidate-plan-prefix",
                plan_prefix,
                "--expected-commit",
                "a" * 40,
                "--expected-tree",
                "b" * 40,
                "--output",
                str(output),
                "--policy-profile",
                replay_cli.POLICY_PROFILE,
            ]
        )
        == 0
    )
    document = json.loads(output.read_bytes())
    assert document["schema"] == replay_cli.TRACE_REOPENING_SCHEMA
    payload = document["payload"]
    assert payload["receipt_status"] == "PASS_SEALED_TRACE_PREFIX_REOPENING"
    assert payload["replay_evidence_mode"] == "sealed-trace-prefix-reopening"
    assert payload["sealed_trace_binding"]["reopening_candidate_plan_prefix"] == plan_prefix
    assert payload["sealed_trace_binding"]["reopening_candidate_plan_signature"] == plan_signature
