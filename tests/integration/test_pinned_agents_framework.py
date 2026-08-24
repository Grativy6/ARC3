"""Exact pinned Agents framework execution against a loopback-only gateway."""

from __future__ import annotations

import hashlib
import json
import os
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, cast

import pytest

from arc3.packaging import runtime_launcher as launcher_module
from arc3.packaging.runtime_launcher import launch_competition_framework

ROOT = Path(__file__).resolve().parents[2]
PINNED_SOURCE = ROOT / "tests" / "fixtures" / "pinned-agents-4743e7d"
AGENT_PATH = ROOT / "agent" / "my_agent.py"


def _git_blob_sha1(data: bytes) -> str:
    header = f"blob {len(data)}\0".encode("ascii")
    return hashlib.sha1(header + data).hexdigest()


def _materialize_exact_framework(target: Path) -> dict[str, Any]:
    identity = cast(
        dict[str, Any],
        json.loads((PINNED_SOURCE / "SOURCE_IDENTITY.json").read_text(encoding="utf-8")),
    )
    files = cast(dict[str, dict[str, str]], identity["files"])
    for relative, expected in files.items():
        fixture_relative = f"{relative}.source" if relative.startswith("agents/") else relative
        data = (PINNED_SOURCE / fixture_relative).read_bytes()
        if relative == "LICENSE" and hashlib.sha256(data).hexdigest() != expected["sha256"]:
            # apply_patch-backed text fixtures have one final LF; the pinned MIT
            # blob intentionally has none. Remove exactly that staging artifact.
            assert data.endswith(b"\n")
            data = data[:-1]
        assert hashlib.sha256(data).hexdigest() == expected["sha256"]
        assert _git_blob_sha1(data) == expected["git_blob_sha1"]
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)
    return identity


def _assert_pinned_identity(framework: Path, identity: dict[str, Any]) -> None:
    lock = cast(dict[str, Any], json.loads((ROOT / "upstream.lock.json").read_text()))
    refresh = cast(dict[str, Any], lock["build_002_refresh"])
    heads = cast(dict[str, str], refresh["public_repository_heads"])
    agents_repository = next(
        item
        for item in cast(list[dict[str, Any]], lock["repositories"])
        if item["name"] == "arcprize/ARC-AGI-3-Agents"
    )

    assert identity["commit"] == launcher_module.AGENTS_COMMIT
    assert identity["commit"] == heads["arcprize/ARC-AGI-3-Agents"]
    assert identity["tree"] == agents_repository["tree"]
    assert launcher_module._PINNED_LF_FILES == {
        relative: expected["sha256"]
        for relative, expected in cast(dict[str, dict[str, str]], identity["files"]).items()
    }
    assert launcher_module._validate_framework(framework, allow_test_fixture=False) == (
        identity["commit"],
        f"git:{identity['commit']}",
        False,
    )


class _GatewayServer(ThreadingHTTPServer):
    requests: list[tuple[str, str, dict[str, object]]]

    def __init__(self) -> None:
        super().__init__(("127.0.0.1", 0), _GatewayHandler)
        self.requests = []


class _GatewayHandler(BaseHTTPRequestHandler):
    server: _GatewayServer

    def log_message(self, _format: str, *args: object) -> None:
        del args

    def _body(self) -> dict[str, object]:
        length = int(self.headers.get("Content-Length", "0"))
        if length == 0:
            return {}
        decoded: object = json.loads(self.rfile.read(length))
        assert isinstance(decoded, dict)
        return cast(dict[str, object], decoded)

    def _send(self, value: object, *, status: int = 200) -> None:
        encoded = json.dumps(value, allow_nan=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    @staticmethod
    def _metadata() -> dict[str, object]:
        return {
            "baseline_actions": [1],
            "class_name": "PinnedLifecycle",
            "game_id": "p1fw-0001",
            "tags": ["exact-pinned-framework-test"],
            "title": "Pinned framework lifecycle fixture",
        }

    @staticmethod
    def _frame(*, action_id: int, state: str) -> dict[str, object]:
        frame = [[0 for _ in range(8)] for _ in range(8)]
        frame[2][2] = 1
        return {
            "action_input": {"data": {}, "id": action_id, "reasoning": None},
            "available_actions": list(range(1, 8)) if state == "NOT_FINISHED" else [],
            "frame": [frame],
            "full_reset": action_id == 0,
            "game_id": "p1fw-0001",
            "guid": "p1fw-guid-0001",
            "levels_completed": 0 if state == "NOT_FINISHED" else 1,
            "state": state,
            "win_levels": 1,
        }

    def do_GET(self) -> None:
        self.server.requests.append(("GET", self.path, {}))
        if self.path == "/api/games":
            self._send([self._metadata()])
            return
        if self.path == "/api/games/p1fw":
            self._send(self._metadata())
            return
        self._send({"error": "not found"}, status=404)

    def do_POST(self) -> None:
        body = self._body()
        self.server.requests.append(("POST", self.path, body))
        if self.path == "/api/scorecard/open":
            self._send({"card_id": "p1fw-scorecard"})
            return
        if self.path == "/api/scorecard/close":
            self._send(
                {
                    "card_id": "p1fw-scorecard",
                    "competition_mode": True,
                    "environments": [],
                    "score": 1.0,
                    "tags_scores": [],
                }
            )
            return
        if self.path == "/api/cmd/RESET":
            self._send(self._frame(action_id=0, state="NOT_FINISHED"))
            return
        if self.path.startswith("/api/cmd/ACTION"):
            action_id = int(self.path.removeprefix("/api/cmd/ACTION"))
            self._send(self._frame(action_id=action_id, state="WIN"))
            return
        self._send({"error": "not found"}, status=404)


@contextmanager
def _loopback_gateway() -> Iterator[_GatewayServer]:
    server = _GatewayServer()
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        yield server
    finally:
        server.shutdown()
        worker.join(timeout=10)
        server.server_close()
        assert not worker.is_alive()


@pytest.mark.competition
def test_pinned_agents_fixture_matches_git_objects_and_launcher_identity(tmp_path: Path) -> None:
    framework = tmp_path / "pinned-agents"
    identity = _materialize_exact_framework(framework)

    _assert_pinned_identity(framework, identity)


@pytest.mark.competition
@pytest.mark.integration
@pytest.mark.skipif(
    os.name != "posix",
    reason="the exact non-fixture launcher requires Linux SIGALRM deadline enforcement",
)
def test_exact_pinned_agents_framework_runs_myagent_lifecycle(tmp_path: Path) -> None:
    framework = tmp_path / "pinned-agents"
    identity = _materialize_exact_framework(framework)
    _assert_pinned_identity(framework, identity)

    working_root = tmp_path / "competition-runtime"
    with _loopback_gateway() as gateway:
        port = int(gateway.server_address[1])
        receipt = launch_competition_framework(
            framework,
            AGENT_PATH,
            gateway_host="127.0.0.1",
            gateway_port=port,
            working_root=working_root,
            allow_test_fixture=False,
        )
        requests = tuple(gateway.requests)

    paths = [path for _, path, _ in requests]
    action_paths = [path for path in paths if path.startswith("/api/cmd/ACTION")]
    assert paths.count("/api/games") == 2
    assert paths.count("/api/games/p1fw") == 1
    assert paths.count("/api/scorecard/open") == 1
    assert paths.count("/api/cmd/RESET") == 1
    assert len(action_paths) == 1
    assert paths.count("/api/scorecard/close") == 1

    assert receipt.framework_commit == identity["commit"]
    assert receipt.framework_identity == f"git:{identity['commit']}"
    assert receipt.framework_fixture is False
    assert receipt.hard_timeout_enforced is True
    assert receipt.discovered_environments == ("p1fw-0001",)
    assert receipt.agent_count == receipt.worker_count == receipt.make_count == 1
    assert receipt.max_concurrency == 1
    assert receipt.open_scorecard_count == receipt.close_scorecard_count == 1
    assert receipt.get_scorecard_during_flight_count == 0
    assert receipt.all_environments_covered is True
    assert receipt.tournament_configured is True
    assert receipt.tournament_finalized is True
    tournament_wrapper = cast(dict[str, Any], receipt.tournament_receipt)
    assert tournament_wrapper["status"] == "PASS"
    tournament = cast(dict[str, Any], tournament_wrapper["receipt"])
    assert tournament["expected_environments"] == 1
    assert tournament["finalized_environments"] == 1
    assert tournament["total_actions_authorized"] == 1
    assert tournament["reserve_preserved"] is True
    assert tournament["effective_ceiling_respected"] is True
    assert not tuple(working_root.rglob("*.recording.jsonl"))
    assert not tuple(working_root.glob("arc3-launch-failure-*.json"))
