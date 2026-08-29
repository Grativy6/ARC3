"""Focused tests for the reusable Build 003 read-only prelaunch audit."""

from __future__ import annotations

import argparse
import ast
from pathlib import Path
from types import SimpleNamespace

import pytest
from scripts import audit_build003_prelaunch as audit
from scripts import evaluate_public

_COMMIT = "a" * 40
_TREE = "b" * 40
_GAME_ID = "r11l-495a7899"


def _prospective_argv(
    *,
    manifest: Path,
    cache: Path,
    output_root: Path,
    exposure_ledger: Path,
    evaluation_id: str = "build003-r11l-seed7-campaign-test",
) -> tuple[str, ...]:
    run_root = output_root / evaluation_id
    return (
        "--partition",
        "development",
        "--agents",
        "mechanical",
        "--seeds",
        "7",
        "--max-actions",
        "3000",
        "--max-resets",
        "64",
        "--timeout-seconds",
        "21600.0",
        "--frozen-commit",
        _COMMIT,
        "--manifest",
        str(manifest),
        "--environments-dir",
        str(cache),
        "--recordings-dir",
        str(run_root / "official-recordings"),
        "--output-root",
        str(output_root),
        "--exposure-ledger",
        str(exposure_ledger),
        "--milestone-id",
        "build-003-stage10-target-play-test",
        "--game-ids",
        _GAME_ID,
        "--no-python-allocation-tracing",
        "--automatic-checkpointing",
        "--evaluation-id",
        evaluation_id,
    )


def _request(
    tmp_path: Path,
    *,
    exposure_ledger: Path | None = None,
) -> tuple[audit.AuditRequest, Path, Path]:
    neutral = tmp_path / "neutral"
    neutral.mkdir()
    cache = tmp_path / "cache"
    cache.mkdir()
    output_root = tmp_path / "play"
    output_root.mkdir()
    canonical_ledger = output_root / "public-exposure.jsonl"
    ledger = canonical_ledger if exposure_ledger is None else exposure_ledger
    ledger.parent.mkdir(parents=True, exist_ok=True)
    ledger.write_bytes(b"stable-exposure\n")
    manifest = audit.ROOT / "docs/evaluation/public-game-partitions.v0.1.json"
    manifest_hash = audit._sha256_file(manifest)
    evaluation_id = "build003-r11l-seed7-campaign-test"
    run_root = output_root / evaluation_id
    request = audit.AuditRequest(
        source_root=audit.ROOT,
        expected_commit=_COMMIT,
        expected_tree=_TREE,
        expected_manifest_sha256=manifest_hash,
        expected_game_id=_GAME_ID,
        expected_run_root=run_root,
        neutral_cwd=neutral,
        output=tmp_path / "gate" / "prelaunch.json",
        evaluator_argv=_prospective_argv(
            manifest=manifest,
            cache=cache,
            output_root=output_root,
            exposure_ledger=ledger,
            evaluation_id=evaluation_id,
        ),
    )
    return request, neutral, ledger


def _patch_success_dependencies(
    monkeypatch: pytest.MonkeyPatch,
    request: audit.AuditRequest,
    ledger: Path,
) -> None:
    source = audit.SourceIdentity(audit.ROOT, _COMMIT, _TREE)
    target_identity: dict[str, object] = {
        "aggregate_sha256": "sha256:" + "c" * 64,
        "files": [
            {
                "bytes": 12,
                "name": "metadata.json",
                "sha256": "sha256:" + "d" * 64,
            }
        ],
        "game_id": _GAME_ID,
        "source_semantically_inspected": False,
    }
    manifest_bytes = (
        (audit.ROOT / "docs/evaluation/public-game-partitions.v0.1.json").stat().st_size
    )
    snapshot = audit.ManifestCacheSnapshot(
        manifest={
            "bytes": manifest_bytes,
            "entry_count": 25,
            "partition_counts": {"development": 12, "public-holdout": 10, "smoke": 3},
            "path": str(audit.ROOT / "docs/evaluation/public-game-partitions.v0.1.json"),
            "sha256": request.expected_manifest_sha256,
            "target": {
                "assignment_hash": "4a713213684214057d6bb8dffe5c312309a58891c35bcc27e0551ac409b0e149",
                "exposure": "discovery-metadata-only",
                "game_id": _GAME_ID,
                "original_partition": None,
                "partition": "development",
                "stable_name": "r11l",
            },
        },
        cache={
            "cached_entry_count": 15,
            "filesystem_inventory_matches_manifest_entries": True,
            "holdout_cached_count": 0,
            "partition_counts": {"development": 12, "smoke": 3},
            "root": str(Path(request.evaluator_argv[25]).resolve()),
        },
        target_identity=target_identity,
        game_partitions={_GAME_ID: "development"},
    )
    exposure = audit.ExposureSnapshot(
        receipt={
            "bytes": ledger.stat().st_size,
            "canonical_chain_verified": True,
            "event_count": 1,
            "holdout_event_count": 0,
            "partition_counts": {"development": 1},
            "path": str(ledger.resolve()),
            "sha256": audit._sha256_file(ledger),
            "tail_event_hash": "sha256:" + "e" * 64,
        },
        byte_length=ledger.stat().st_size,
        sha256=audit._sha256_file(ledger),
    )
    evaluator = SimpleNamespace(
        build_parser=evaluate_public.build_parser,
        main=lambda *_args, **_kwargs: pytest.fail("evaluator main must remain unreachable"),
    )
    monkeypatch.setattr(audit, "_BYTECODE_DISABLED_AT_STARTUP", True)
    monkeypatch.setattr(audit, "_source_identity", lambda *_args, **_kwargs: source)
    monkeypatch.setattr(audit, "_prepare_exact_imports", lambda _root: None)
    monkeypatch.setattr(
        audit,
        "_import_bindings",
        lambda _root: (
            {
                "imports": {
                    "arc3": str(audit.ROOT / "src/arc3/__init__.py"),
                    "arc3.evaluation.public": str(audit.ROOT / "src/arc3/evaluation/public.py"),
                    "scripts.evaluate_public": str(audit.ROOT / "scripts/evaluate_public.py"),
                },
                "official_package_versions": {"arc-agi": "0.9.9", "arcengine": "0.9.3"},
            },
            evaluator,
        ),
    )
    monkeypatch.setattr(audit, "_manifest_cache_snapshot", lambda **_kwargs: snapshot)
    monkeypatch.setattr(audit, "_exposure_snapshot", lambda *_args, **_kwargs: exposure)
    monkeypatch.setattr(audit, "_target_identity", lambda **_kwargs: target_identity)
    monkeypatch.setattr(audit, "_environment_names_now", lambda: frozenset())


def test_producer_parses_without_evaluation_and_seals_read_only_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request, neutral, ledger = _request(tmp_path)
    _patch_success_dependencies(monkeypatch, request, ledger)
    monkeypatch.chdir(neutral)

    receipt = audit.produce_audit(
        request,
        environment_names=frozenset(),
        observed_at="2026-08-29T00:00:00.000000Z",
    )
    repeated = audit.produce_audit(
        request,
        environment_names=frozenset(),
        observed_at="2026-08-29T00:00:00.000000Z",
    )

    assert receipt["status"] == "PASS"
    assert repeated == receipt
    assert audit._verify_seal(receipt, hash_field="receipt_hash")
    assert receipt["boundaries"] == {
        "acquisition_attempts": 0,
        "credential_values_inspected": False,
        "credential_values_used": False,
        "environment_actions_issued": 0,
        "environment_sessions_constructed": 0,
        "evaluator_called": False,
        "game_source_semantically_inspected": False,
        "holdout_accessed": False,
        "network_requests_issued": 0,
        "official_submission_performed": False,
    }
    prospective = receipt["prospective_run"]
    assert isinstance(prospective, dict)
    assert prospective["run_root_absent_before_and_after"] is True
    assert prospective["credential_or_submission_parser_options"] == []
    assert list(neutral.iterdir()) == []
    assert not request.expected_run_root.exists()


def test_exclusive_output_preserves_first_canonical_receipt(tmp_path: Path) -> None:
    output = tmp_path / "gate" / "receipt.json"
    receipt = audit._seal({"schema": audit.SCHEMA, "status": "PASS"}, hash_field="receipt_hash")

    audit._write_exclusive(output, receipt)

    assert output.read_bytes() == audit._canonical_json_bytes(receipt)
    with pytest.raises(audit.PrelaunchAuditError, match="already exists"):
        audit._write_exclusive(output, {"status": "different"})


@pytest.mark.parametrize(
    ("name", "classification"),
    [
        ("SESSION_COOKIE", "credential"),
        ("GIT_CEILING_DIRECTORIES", "source_control"),
        ("ARC_BASE_URL", "upstream"),
        ("ARC3_NETWORK_ENABLED", "upstream"),
    ],
)
def test_environment_name_gate_fails_closed_without_accepting_values(
    name: str,
    classification: str,
) -> None:
    with pytest.raises(audit.PrelaunchAuditError) as captured:
        audit._require_sanitized_environment(frozenset({name}))

    assert name in str(captured.value)
    assert classification in str(captured.value)
    assert "must-never-be-read" not in str(captured.value)


def test_alternate_development_exposure_ledger_is_rejected(
    tmp_path: Path,
) -> None:
    alternate = tmp_path / "alternate" / "development-only.jsonl"
    request, _neutral, _ledger = _request(tmp_path, exposure_ledger=alternate)
    evaluator = SimpleNamespace(build_parser=evaluate_public.build_parser)

    with pytest.raises(audit.PrelaunchAuditError, match="canonical output-root ledger"):
        audit._parse_prospective_run(evaluator, request)


def test_stability_gate_rejects_manifest_byte_change(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.json"
    manifest.write_bytes(b"before\n")
    expected = audit._sha256_file(manifest)
    expected_length = manifest.stat().st_size
    manifest.write_bytes(b"after\n")

    with pytest.raises(audit.PrelaunchAuditError, match="manifest changed"):
        audit._require_stable_file(
            manifest,
            expected_length=expected_length,
            expected_sha256=expected,
            label="manifest",
        )


def _exposure_event(*, partition: str, game_id: str) -> dict[str, object]:
    return audit._seal(
        {
            "event_type": "game.evaluation_started",
            "occurred_at": "2026-08-29T00:00:00.000000Z",
            "payload": {
                "game_id": game_id,
                "partition": partition,
            },
            "previous_event_hash": None,
            "schema": "arc3.public-exposure.event.v0.1",
            "sequence": 0,
        },
        hash_field="event_hash",
    )


def test_exposure_gate_reuses_canonical_chain_and_rejects_holdout(
    tmp_path: Path,
) -> None:
    ledger = tmp_path / "public-exposure.jsonl"
    event = _exposure_event(partition="development", game_id=_GAME_ID)
    ledger.write_bytes(audit._canonical_json_bytes(event))

    snapshot = audit._exposure_snapshot(
        ledger,
        game_partitions={_GAME_ID: "development"},
    )

    assert snapshot.receipt["canonical_chain_verified"] is True
    holdout_id = "sealed-deadbeef"
    holdout = _exposure_event(partition="public-holdout", game_id=holdout_id)
    ledger.write_bytes(audit._canonical_json_bytes(holdout))
    with pytest.raises(audit.PrelaunchAuditError, match="non-development"):
        audit._exposure_snapshot(
            ledger,
            game_partitions={holdout_id: "public-holdout"},
        )


def test_parser_option_gate_rejects_new_submission_surface(tmp_path: Path) -> None:
    request, _neutral, _ledger = _request(tmp_path)

    def unsafe_parser() -> argparse.ArgumentParser:
        parser = evaluate_public.build_parser()
        parser.add_argument("--submission-token")
        return parser

    evaluator = SimpleNamespace(build_parser=unsafe_parser)
    with pytest.raises(audit.PrelaunchAuditError, match="credential/submission options"):
        audit._parse_prospective_run(evaluator, request)


def test_arc3_configuration_error_is_normalized_after_exact_import(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from arc3.errors import ConfigurationError
    from arc3.evaluation import public as public_module

    request, _neutral, _ledger = _request(tmp_path)

    def reject_config(**_kwargs: object) -> object:
        raise ConfigurationError("synthetic configuration boundary")

    monkeypatch.setattr(public_module, "PublicEvaluationConfig", reject_config)
    evaluator = SimpleNamespace(build_parser=evaluate_public.build_parser)

    with pytest.raises(
        audit.PrelaunchAuditError,
        match=r"declaration failed closed \(ConfigurationError\)",
    ):
        audit._parse_prospective_run(evaluator, request)


def test_producer_has_no_evaluator_acquisition_or_action_call_surface() -> None:
    tree = ast.parse(Path(audit.__file__).read_text(encoding="utf-8"))
    called_names = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    called_attributes = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }

    assert called_names.isdisjoint({"acquire_local_public_asset", "run_public_evaluation"})
    assert called_attributes.isdisjoint({"main", "make", "reset", "step"})
