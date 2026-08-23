"""Measure isolated first-party package import/startup without public-game access."""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import re
import sys
import tempfile
import time
import zipfile
from collections.abc import Sequence
from pathlib import Path
from typing import Any, cast

_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_PROCESS_LAUNCH_EVENTS = frozenset(
    {
        "os.exec",
        "os.posix_spawn",
        "os.posix_spawnp",
        "os.spawn",
        "os.system",
        "subprocess.Popen",
    }
)


def _sha256_bytes(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def _json_object(path: Path) -> dict[str, Any]:
    loaded: object = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError(f"JSON document is not an object: {path.name}")
    return cast(dict[str, Any], loaded)


def _verify_build_receipt(package_root: Path, expected_commit: str) -> tuple[Path, str]:
    receipt_path = package_root / "build-receipt.json"
    receipt = _json_object(receipt_path)
    claimed_receipt = receipt.pop("receipt_sha256", None)
    canonical_body = (
        json.dumps(
            receipt,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")
    if claimed_receipt != _sha256_bytes(canonical_body):
        raise ValueError("package build receipt self-hash is invalid")
    if receipt.get("status") != "PACKAGING_PASS":
        raise ValueError("package build receipt does not claim PACKAGING_PASS")
    payload = package_root / "arc3-first-party.zip"
    payload_sha256 = _sha256_file(payload)
    if receipt.get("payload_sha256") != payload_sha256:
        raise ValueError("package payload hash differs from the build receipt")
    manifest = _json_object(package_root / "package-manifest.json")
    source = manifest.get("source")
    if not isinstance(source, dict) or source.get("git_commit") != expected_commit:
        raise ValueError("package manifest source commit differs from the startup probe")
    return payload, payload_sha256


def _extract_payload(payload: Path, destination: Path) -> None:
    with zipfile.ZipFile(payload) as archive:
        infos = archive.infolist()
        names = [info.filename for info in infos]
        if (
            len(names) != len(set(names))
            or not {"agent/my_agent.py", "src/arc3/__init__.py"} <= set(names)
            or any(
                info.is_dir()
                or info.filename.startswith("/")
                or ".." in Path(info.filename).parts
                or (info.external_attr >> 16) & 0o170000 == 0o120000
                for info in infos
            )
        ):
            raise ValueError("package payload has an unsafe or incomplete member set")
        for info in infos:
            target = destination / info.filename
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.read(info.filename))


def run_probe(package_root: Path, expected_commit: str) -> dict[str, object]:
    """Import and instantiate the package under a scoped Python audit boundary."""

    if _COMMIT.fullmatch(expected_commit) is None:
        raise ValueError("expected commit must be a lowercase full SHA")
    package_root = package_root.resolve()
    payload, payload_sha256 = _verify_build_receipt(package_root, expected_commit)
    started = time.perf_counter()
    network_attempt_events: list[str] = []
    process_launch_events: list[str] = []

    def deny_external_capabilities(event: str, _args: tuple[Any, ...]) -> None:
        if event.startswith("socket."):
            network_attempt_events.append(event)
            raise PermissionError(f"package startup probe forbids Python socket event {event}")
        if event in _PROCESS_LAUNCH_EVENTS or event.startswith("os.exec"):
            process_launch_events.append(event)
            raise PermissionError(f"package startup probe forbids child process event {event}")

    sys.addaudithook(deny_external_capabilities)
    inserted_paths: list[str] = []
    try:
        with tempfile.TemporaryDirectory(prefix="arc3-package-startup-") as temporary:
            extracted = Path(temporary) / "payload"
            _extract_payload(payload, extracted)
            inserted_paths = [str(extracted), str(extracted / "src")]
            for path in inserted_paths:
                sys.path.insert(0, path)
            import_started = time.perf_counter()
            arc3 = importlib.import_module("arc3")
            wrapper = importlib.import_module("agent.my_agent")
            import_seconds = time.perf_counter() - import_started
            arc3_origin = Path(str(getattr(arc3, "__file__", ""))).resolve()
            wrapper_origin = Path(str(getattr(wrapper, "__file__", ""))).resolve()
            if arc3_origin != (extracted / "src" / "arc3" / "__init__.py").resolve():
                raise ValueError("startup probe imported arc3 outside the packaged payload")
            if wrapper_origin != (extracted / "agent" / "my_agent.py").resolve():
                raise ValueError("startup probe imported the wrapper outside the packaged payload")
            agent_type = getattr(wrapper, "MyAgent", None)
            if not isinstance(agent_type, type):
                raise ValueError("packaged wrapper has no MyAgent type")
            instantiate_started = time.perf_counter()
            agent = agent_type(game_id="offline-startup", agent_name="myagent", seed=0)
            instantiate_seconds = time.perf_counter() - instantiate_started
            if not isinstance(getattr(agent, "name", None), str):
                raise ValueError("packaged MyAgent did not initialize a string name")
    finally:
        for path in inserted_paths:
            while path in sys.path:
                sys.path.remove(path)
    if network_attempt_events or process_launch_events:
        raise ValueError("packaged startup crossed the Python capability boundary")
    return {
        "expected_commit": expected_commit,
        "import_seconds": import_seconds,
        "instantiate_seconds": instantiate_seconds,
        "network_attempt_events": network_attempt_events,
        "network_attempts": len(network_attempt_events),
        "network_enforcement": "python-audit-hook-socket-events",
        "payload_sha256": payload_sha256,
        "process_launch_attempt_events": process_launch_events,
        "process_launch_attempts": len(process_launch_events),
        "process_launch_enforcement": "python-audit-hook-process-events",
        "schema": "arc3.package-startup-probe.v0.2",
        "status": "PASS",
        "total_seconds": time.perf_counter() - started,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package-root", type=Path, required=True)
    parser.add_argument("--expected-commit", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    try:
        receipt = run_probe(args.package_root, args.expected_commit)
    except (OSError, ValueError, zipfile.BadZipFile) as error:
        print(f"package startup probe refused: {error}", file=sys.stderr)
        return 2
    print(json.dumps(receipt, allow_nan=False, separators=(",", ":"), sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
