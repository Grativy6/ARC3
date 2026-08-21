"""Tests for bounded, local-only repository diagnostics."""

from __future__ import annotations

import json
import socket
import urllib.request

import pytest

import arc3.doctor as doctor
from arc3.cli import main as cli_main
from arc3.config import default_config
from arc3.types import EnvironmentMode


def _fail_network(*args: object, **kwargs: object) -> None:
    del args, kwargs
    raise AssertionError("doctor attempted a network operation")


def test_doctor_runs_without_network_or_optional_dependencies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(socket, "create_connection", _fail_network)
    monkeypatch.setattr(urllib.request, "urlopen", _fail_network)
    monkeypatch.setattr(doctor.importlib.util, "find_spec", lambda module: None)

    report = doctor.run_doctor(default_config(EnvironmentMode.COMPETITION, seed=17))

    assert report.passed
    assert report.mode is EnvironmentMode.COMPETITION
    assert report.config_hash.startswith("sha256:")
    assert all(not check.required for check in report.checks if check.name.startswith("optional-"))
    network_check = next(check for check in report.checks if check.name == "network-policy")
    assert network_check.passed
    assert network_check.details == {"network_enabled": False}


def test_doctor_report_never_reads_or_emits_environment_secrets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sentinel = "doctor-must-not-leak-this"
    monkeypatch.setenv("ARC_API_KEY", sentinel)
    monkeypatch.setenv("KAGGLE_KEY", sentinel)

    serialized = json.dumps(doctor.run_doctor().to_dict(), sort_keys=True)

    assert sentinel not in serialized
    assert "ARC_API_KEY" not in serialized
    assert "KAGGLE_KEY" not in serialized


def test_cli_doctor_json_contract(capsys: pytest.CaptureFixture[str]) -> None:
    status = cli_main(["doctor", "--mode", "competition", "--seed", "23", "--json"])

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert status == 0
    assert captured.err == ""
    assert payload["schema"] == "arc3.doctor.v0.1"
    assert payload["passed"] is True
    assert payload["mode"] == "competition"
    assert len(payload["config_hash"]) == 71


def test_cli_reserves_future_commands_without_false_success(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert cli_main(["replay"]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "reserved for Stage 03" in captured.err
