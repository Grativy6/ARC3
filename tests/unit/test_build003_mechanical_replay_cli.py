from __future__ import annotations

import ast
import copy
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from scripts import replay_build003_mechanical_recording as replay_cli

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
    paths = (
        Path(replay_cli.__file__),
        Path(replay_cli.replay_module.__file__),
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
