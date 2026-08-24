"""Competition-rerun rehearsal using a local gateway and safe framework fixture."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import shutil
import subprocess
import sysconfig
import tempfile
import venv
from pathlib import Path
from typing import cast

from arc3.packaging.models import (
    PYTHON_NETWORK_ENFORCEMENT,
    PackagingError,
    SandboxReceipt,
)
from arc3.packaging.notebook import REHEARSAL_AUTHORITY, validate_notebook
from arc3.packaging.runtime_launcher import SAFE_FRAMEWORK_FIXTURE_IDENTITY
from arc3.packaging.submission import write_validation_submission
from arc3.packaging.util import (
    deterministic_zip_bytes,
    sha256_bytes,
    sha256_file,
    write_bytes_atomic,
)
from arc3.types import JSONValue

_FIXTURE_DISTRIBUTION = "arc3-rehearsal-canary"
_FIXTURE_VERSION = "0.0.0"

_PYTHON_SOCKET_GUARD = r"""
def address_host(address):
    raw_host = address[0] if isinstance(address, tuple) and address else address
    if isinstance(raw_host, bytes):
        return raw_host.decode("ascii", errors="replace")
    return str(raw_host)


def guard_address(operation, address, *, record_connection=False):
    if address_host(address) not in allowed_hosts:
        blocked_attempts.append(f"{operation}:{address!r}")
        raise RuntimeError(f"offline sandbox blocked non-loopback {operation}")
    if record_connection:
        gateway_connections.append(repr(address))


def deny_operation(operation, address):
    blocked_attempts.append(f"{operation}:{address!r}")
    raise RuntimeError(f"offline sandbox blocked {operation}")


class GuardedSocket(real_socket):
    def connect(self, address):
        guard_address("connect", address, record_connection=True)
        return super().connect(address)

    def connect_ex(self, address):
        try:
            guard_address("connect_ex", address, record_connection=True)
        except RuntimeError:
            return 1
        return super().connect_ex(address)

    def sendto(self, data, *args):
        if not args:
            raise TypeError("sendto requires a destination address")
        guard_address("sendto", args[-1])
        return super().sendto(data, *args)

    def sendmsg(self, buffers, ancdata=(), flags=0, address=None):
        if address is not None:
            guard_address("sendmsg", address)
        implementation = getattr(super(), "sendmsg", None)
        if implementation is None:
            raise NotImplementedError("sendmsg is unavailable on this platform")
        if address is None:
            return implementation(buffers, ancdata, flags)
        return implementation(buffers, ancdata, flags, address)


def guarded_connection(address, *args, **kwargs):
    guard_address("create_connection", address, record_connection=True)
    return real_create_connection(address, *args, **kwargs)


def guarded_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
    guard_address("getaddrinfo", host)
    return real_getaddrinfo(
        host, port, family, type, proto, flags | socket.AI_NUMERICHOST
    )


def guarded_gethostbyname(host):
    deny_operation("gethostbyname", host)


def guarded_gethostbyname_ex(host):
    deny_operation("gethostbyname_ex", host)


def guarded_gethostbyaddr(host):
    deny_operation("gethostbyaddr", host)


def guarded_getnameinfo(address, flags):
    del flags
    deny_operation("getnameinfo", address)


socket.socket = GuardedSocket
socket.SocketType = GuardedSocket
socket.create_connection = guarded_connection
socket.getaddrinfo = guarded_getaddrinfo
socket.gethostbyname = guarded_gethostbyname
socket.gethostbyname_ex = guarded_gethostbyname_ex
socket.gethostbyaddr = guarded_gethostbyaddr
socket.getnameinfo = guarded_getnameinfo
"""

_RUNNER_TEMPLATE = r"""
from __future__ import annotations

import json
import os
import re
import socket
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

notebook_path = Path(sys.argv[1]).resolve()
working_root = Path(sys.argv[2]).resolve()
input_root = Path(sys.argv[3]).resolve()
requirements_path = Path(sys.argv[4]).resolve()
rehearsal_authority = sys.argv[5]
gateway_connections = []
blocked_attempts = []
real_socket = socket.socket
real_create_connection = socket.create_connection
real_getaddrinfo = socket.getaddrinfo
real_gethostbyname = socket.gethostbyname
real_gethostbyname_ex = socket.gethostbyname_ex
real_gethostbyaddr = socket.gethostbyaddr
real_getnameinfo = socket.getnameinfo
allowed_hosts = {"127.0.0.1", "::1"}
network_enforcement = __ARC3_NETWORK_ENFORCEMENT__


class GatewayHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        gateway_connections.append(self.path)
        if self.path != "/api/games":
            self.send_response(404)
            self.end_headers()
            return
        body = json.dumps([{"game_id": "stage17-fixture-game"}]).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        del format, args


server = ThreadingHTTPServer(("127.0.0.1", 0), GatewayHandler)
server_thread = threading.Thread(target=server.serve_forever, daemon=True)
server_thread.start()
gateway_port = int(server.server_address[1])

__ARC3_PYTHON_SOCKET_GUARD__
os.environ["KAGGLE_IS_COMPETITION_RERUN"] = "1"
os.environ["ARC3_REHEARSAL_FIXTURE"] = "1"
os.environ["ARC3_COMPETITION_INPUT"] = str(input_root)
os.environ["ARC3_REHEARSAL_REQUIREMENTS"] = str(requirements_path)
os.environ["ARC3_GATEWAY_HOST"] = "127.0.0.1"
os.environ["ARC3_GATEWAY_PORT"] = str(gateway_port)
os.environ["ARC3_WORKING_DIR"] = str(working_root)

document = json.loads(notebook_path.read_text(encoding="utf-8"))
namespace = {
    "__name__": "__arc3_notebook_sandbox__",
    "_ARC3_REHEARSAL_AUTHORITY": rehearsal_authority,
}
try:
    for index, cell in enumerate(document["cells"]):
        if cell.get("cell_type") == "code":
            exec(compile(cell["source"], f"<notebook-cell-{index}>", "exec"), namespace)
finally:
    server.shutdown()
    server.server_close()
    server_thread.join(timeout=5)

import arc3
import arc3_rehearsal_canary
from arc3.config import ARC3Config
from arc3.types import EnvironmentMode

config = ARC3Config.for_mode(EnvironmentMode.COMPETITION)
if config.network_enabled:
    raise RuntimeError("packaged competition config enabled networking")
arc3_path = Path(arc3.__file__).resolve()
if not arc3_path.is_relative_to((working_root / "arc3_submission").resolve()):
    raise RuntimeError("sandbox imported ARC3 outside the extracted package payload")
canary_path = Path(arc3_rehearsal_canary.__file__).resolve()
if not canary_path.is_relative_to((working_root / "arc3_dependencies").resolve()):
    raise RuntimeError("no-index canary was not imported from the isolated install target")

agent_path = working_root / "arc3_submission" / "agent" / "my_agent.py"
if not agent_path.is_file():
    raise RuntimeError("packaged wrapper is absent after payload extraction")

output_path = working_root / "submission.parquet"
if not output_path.is_file():
    raise RuntimeError("safe sidecar fixture did not create submission.parquet")
install_receipt = json.loads(
    (working_root / "arc3-install-receipt.json").read_text(encoding="utf-8")
)
launch_receipt = json.loads(
    (working_root / "arc3-launch-receipt.json").read_text(encoding="utf-8")
)
fixture_receipt = json.loads(
    (working_root / "arc3-framework-fixture-receipt.json").read_text(encoding="utf-8")
)
if install_receipt.get("dependency_install_status") != "PASS":
    raise RuntimeError("offline dependency install did not pass")
if not install_receipt.get("no_index") or not install_receipt.get("require_hashes"):
    raise RuntimeError("offline dependency install contract was weakened")
if launch_receipt.get("framework_fixture") is not True:
    raise RuntimeError("safe framework fixture was not identified")
if (
    launch_receipt.get("agent_count") != 1
    or launch_receipt.get("worker_count") != 1
    or launch_receipt.get("max_concurrency") != 1
    or launch_receipt.get("orchestration") != "arc3.sequential-pinned-swarm.v1"
):
    raise RuntimeError("safe framework fixture did not use bounded sequential orchestration")
if fixture_receipt.get("games") != ["stage17-fixture-game"]:
    raise RuntimeError("safe framework fixture did not receive the gateway game inventory")
if fixture_receipt.get("agent_action_cycle_status") != "PASS":
    raise RuntimeError("safe framework fixture did not execute a packaged agent action cycle")
cycle_actions = fixture_receipt.get("agent_cycle_actions")
if (
    not isinstance(cycle_actions, list)
    or len(cycle_actions) != 2
    or cycle_actions[0] != "RESET"
    or cycle_actions[1] not in {f"ACTION{index}" for index in range(1, 8)}
):
    raise RuntimeError("safe framework fixture returned an invalid packaged agent action cycle")
if fixture_receipt.get("agent_consequence_state") != "NOT_FINISHED":
    raise RuntimeError("safe framework fixture did not return a consequence to the agent")

sensitive = ("TOKEN", "SECRET", "PASSWORD", "CREDENTIAL", "AUTH", "API_KEY")
credentials = sorted(
    name
    for name, value in os.environ.items()
    if value and any(fragment in name.upper() for fragment in sensitive)
)
for permitted in ("ARC_API_KEY",):
    if permitted in credentials and os.environ.get(permitted) == "test-key-123":
        credentials.remove(permitted)

forbidden_names = {".env", "kaggle.json", "credentials.json"}
secret_patterns = (
    re.compile(rb"-----BEGIN (?:RSA |EC |DSA |OPENSSH |PGP )?PRIVATE KEY-----"),
    re.compile(rb"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(rb"\bgh[pousr]_[A-Za-z0-9]{30,}\b"),
    re.compile(rb"\bKGAT_[A-Za-z0-9_-]{20,}\b"),
    re.compile(rb"\bsk-(?:(?:proj|ant|svcacct)-)?[A-Za-z0-9_-]{20,}\b"),
)
payload_root = working_root / "arc3_submission"
for path in payload_root.rglob("*"):
    if not path.is_file():
        continue
    if path.name.lower() in forbidden_names:
        raise RuntimeError("credential-bearing filename in extracted payload")
    content = path.read_bytes()
    if any(pattern.search(content) for pattern in secret_patterns):
        raise RuntimeError("high-confidence secret pattern in extracted payload")

print(json.dumps({
    "credentials_present": credentials,
    "agent_action_cycle_status": fixture_receipt["agent_action_cycle_status"],
    "agent_consequence_state": fixture_receipt["agent_consequence_state"],
    "agent_cycle_actions": cycle_actions,
    "dependency_install_status": install_receipt["dependency_install_status"],
    "agent_count": launch_receipt["agent_count"],
    "framework_commit": launch_receipt["framework_commit"],
    "framework_identity": launch_receipt["framework_identity"],
    "framework_fixture": launch_receipt["framework_fixture"],
    "gateway_connections": len(gateway_connections),
    "imported_agent_path": agent_path.relative_to(working_root).as_posix(),
    "imported_arc3_path": arc3_path.relative_to(working_root).as_posix(),
    "installed_wheel_sha256": install_receipt["wheel_sha256"],
    "max_concurrency": launch_receipt["max_concurrency"],
    "network_attempts": len(blocked_attempts),
    "network_enforcement": network_enforcement,
    "orchestration": launch_receipt["orchestration"],
    "production_rerun_exercised": True,
    "rehearsal_requirements_sha256": install_receipt["requirements_sha256"],
    "secret_scan_status": "PASS",
    "status": "PASS" if not blocked_attempts and not credentials else "FAIL",
    "worker_count": launch_receipt["worker_count"],
}, sort_keys=True))
"""

_RUNNER = _RUNNER_TEMPLATE.replace("__ARC3_PYTHON_SOCKET_GUARD__", _PYTHON_SOCKET_GUARD).replace(
    "__ARC3_NETWORK_ENFORCEMENT__", repr(PYTHON_NETWORK_ENFORCEMENT)
)


def _wheel_record(path: str, content: bytes) -> str:
    digest = hashlib.sha256(content).digest()
    encoded = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return f"{path},sha256={encoded},{len(content)}"


def _fixture_wheel() -> tuple[str, bytes, bytes]:
    package_path = "arc3_rehearsal_canary/__init__.py"
    dist_info = "arc3_rehearsal_canary-0.0.0.dist-info"
    members = {
        package_path: b'IDENTITY = "arc3.stage17.no-index-canary.v0.1"\n',
        f"{dist_info}/METADATA": (
            "Metadata-Version: 2.1\n"
            f"Name: {_FIXTURE_DISTRIBUTION}\n"
            f"Version: {_FIXTURE_VERSION}\n"
            "Summary: ARC3 Stage 17 local no-index installer canary\n"
            "\n"
        ).encode(),
        f"{dist_info}/WHEEL": (
            b"Wheel-Version: 1.0\n"
            b"Generator: ARC3 Stage 17 deterministic fixture\n"
            b"Root-Is-Purelib: true\n"
            b"Tag: py3-none-any\n"
            b"\n"
        ),
    }
    record_path = f"{dist_info}/RECORD"
    rows = [_wheel_record(path, content) for path, content in sorted(members.items())]
    rows.append(f"{record_path},,")
    members[record_path] = ("\n".join(rows) + "\n").encode("utf-8")
    wheel_bytes = deterministic_zip_bytes(members)
    filename = "arc3_rehearsal_canary-0.0.0-py3-none-any.whl"
    digest = sha256_bytes(wheel_bytes)
    requirements = (f"{_FIXTURE_DISTRIBUTION}=={_FIXTURE_VERSION} --hash={digest}\n").encode()
    return filename, wheel_bytes, requirements


def _write_framework_fixture(framework_root: Path, submission_bytes: bytes) -> None:
    agents = framework_root / "agents"
    agents.mkdir(parents=True)
    write_bytes_atomic(
        framework_root / ".arc3-safe-fixture",
        SAFE_FRAMEWORK_FIXTURE_IDENTITY.encode("utf-8"),
    )
    write_bytes_atomic(
        agents / "agent.py",
        (
            b"class Agent:\n"
            b"    def __init__(self, *args, **kwargs):\n"
            b"        del args\n"
            b"        self.game_id = kwargs.get('game_id', 'fixture')\n"
            b"        self.agent_name = kwargs.get('agent_name', 'myagent')\n"
            b"    @property\n"
            b"    def name(self):\n"
            b"        return self.agent_name\n"
            b"\n"
            b"class Playback(Agent):\n"
            b"    pass\n"
        ),
    )
    encoded_submission = base64.b64encode(submission_bytes).decode("ascii")
    swarm_source = f'''import base64
import json
import os
from pathlib import Path
from threading import Thread
from types import SimpleNamespace

from arcengine import GameAction, GameState

class Swarm:
    def __init__(self, agent, root_url, games, tags=None):
        from agents import AVAILABLE_AGENTS
        self.agent = agent
        self.root_url = root_url
        self.games = list(games)
        self.tags = list(tags or [])
        self.agent_class = AVAILABLE_AGENTS[agent]
        self.agents = []
        self.threads = []

    def main(self):
        outcomes = {{}}
        def run(instance):
            if not instance.name:
                raise RuntimeError("fixture agent did not initialize")
            first_frame = SimpleNamespace(
                action_input=None,
                available_actions=[GameAction.RESET],
                frame=[[[0, 0], [0, 0]]],
                full_reset=False,
                game_id=instance.game_id,
                guid=f"stage17-fixture-{{instance.game_id}}",
                levels_completed=0,
                state=GameState.NOT_PLAYED,
                win_levels=1,
            )
            first_action = instance.choose_action([], first_frame)
            if getattr(first_action, "name", None) != "RESET":
                raise RuntimeError("packaged agent did not reset a not-played game")
            consequence_frame = SimpleNamespace(
                action_input=SimpleNamespace(id=GameAction.RESET, data={{}}),
                available_actions=[
                    GameAction.ACTION1,
                    GameAction.ACTION2,
                    GameAction.ACTION3,
                    GameAction.ACTION4,
                    GameAction.ACTION5,
                ],
                frame=[[[0, 0], [0, 1]]],
                full_reset=False,
                game_id=instance.game_id,
                guid=f"stage17-fixture-{{instance.game_id}}",
                levels_completed=0,
                state=GameState.NOT_FINISHED,
                win_levels=1,
            )
            second_action = instance.choose_action([first_frame], consequence_frame)
            second_name = getattr(second_action, "name", None)
            if second_name not in {{f"ACTION{{index}}" for index in range(1, 8)}}:
                raise RuntimeError("packaged agent returned an invalid post-consequence action")
            outcomes[instance.game_id] = {{
                "agent_consequence_state": consequence_frame.state.name,
                "agent_cycle_actions": [first_action.name, second_name],
            }}
        for game_id in self.games:
            instance = self.agent_class(game_id=game_id, agent_name=self.agent)
            self.agents.append(instance)
            self.threads.append(Thread(target=run, args=(instance,), daemon=True))
        for thread in self.threads:
            thread.start()
        for thread in self.threads:
            thread.join()
        if set(outcomes) != set(self.games):
            raise RuntimeError("fixture did not execute every discovered game")
        first_outcome = outcomes[self.games[0]]
        working_root = Path(os.environ["ARC3_WORKING_DIR"])
        (working_root / "submission.parquet").write_bytes(
            base64.b64decode("{encoded_submission}")
        )
        receipt = {{
            "agent": self.agent,
            "agent_action_cycle_status": "PASS",
            "agent_consequence_state": first_outcome["agent_consequence_state"],
            "agent_cycle_actions": first_outcome["agent_cycle_actions"],
            "agent_count": len(self.agents),
            "base_url": self.root_url,
            "games": self.games,
            "mode": os.environ.get("ARC3_MODE"),
            "network": os.environ.get("ARC3_NETWORK_ENABLED"),
        }}
        (working_root / "arc3-framework-fixture-receipt.json").write_text(
            json.dumps(receipt, sort_keys=True), encoding="utf-8"
        )
'''
    write_bytes_atomic(agents / "swarm.py", swarm_source.encode("utf-8"))


def _sanitized_environment(working_root: Path) -> dict[str, str]:
    keep = {
        "COMSPEC",
        "LOCALAPPDATA",
        "PATH",
        "PATHEXT",
        "SYSTEMDRIVE",
        "SYSTEMROOT",
        "TEMP",
        "TMP",
        "WINDIR",
    }
    environment = {name: value for name, value in os.environ.items() if name.upper() in keep}
    environment.update(
        {
            "ARC3_MODE": "competition",
            "ARC3_NETWORK_ENABLED": "false",
            "ARC3_SEED": "0",
            "ARC3_WORKING_DIR": str(working_root),
            "NO_PROXY": "*",
            "PYTHONHASHSEED": "0",
            "PYTHONNOUSERSITE": "1",
        }
    )
    return environment


def _load_document(path: Path) -> dict[str, JSONValue]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise PackagingError(f"cannot read generated notebook {path}: {error}") from error
    if not isinstance(raw, dict):
        raise PackagingError("generated notebook must be a JSON object")
    return cast(dict[str, JSONValue], raw)


def _sandbox_python(sandbox_root: Path) -> Path:
    environment_root = sandbox_root / "python"
    venv.EnvBuilder(with_pip=True, clear=True).create(environment_root)
    scripts = "Scripts" if os.name == "nt" else "bin"
    executable = environment_root / scripts / ("python.exe" if os.name == "nt" else "python")
    completed = subprocess.run(
        [str(executable), "-c", "import sysconfig; print(sysconfig.get_paths()['purelib'])"],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise PackagingError("could not locate the rehearsal environment site-packages")
    site_packages = Path(completed.stdout.strip())
    host_site_packages = Path(sysconfig.get_paths()["purelib"]).resolve()
    write_bytes_atomic(
        site_packages / "arc3-stage17-host-runtime.pth",
        (str(host_site_packages) + "\n").encode("utf-8"),
    )
    return executable


def run_offline_sandbox(
    notebook_path: Path,
    output_path: Path,
    *,
    payload_sha256: str,
    requirements_sha256: str,
    timeout_seconds: float = 120.0,
) -> SandboxReceipt:
    """Execute the real rerun branch with no-index install and safe fixtures."""

    document = _load_document(notebook_path)
    validate_notebook(document)
    notebook_sha256 = sha256_file(notebook_path)
    with tempfile.TemporaryDirectory(prefix="arc3-kaggle-sandbox-") as temporary:
        sandbox_root = Path(temporary)
        working_root = sandbox_root / "working"
        input_root = sandbox_root / "input"
        wheel_root = input_root / "arc_agi_3_wheels"
        working_root.mkdir(parents=True)
        wheel_root.mkdir(parents=True)

        with tempfile.TemporaryDirectory(prefix="arc3-fixture-parquet-") as parquet_temporary:
            fixture_submission = Path(parquet_temporary) / "submission.parquet"
            write_validation_submission(fixture_submission)
            submission_bytes = fixture_submission.read_bytes()
        _write_framework_fixture(input_root / "ARC-AGI-3-Agents", submission_bytes)
        wheel_name, wheel_bytes, rehearsal_requirements = _fixture_wheel()
        write_bytes_atomic(wheel_root / wheel_name, wheel_bytes)
        requirements_path = input_root / "rehearsal-requirements.txt"
        write_bytes_atomic(requirements_path, rehearsal_requirements)

        runner_path = sandbox_root / "offline_runner.py"
        write_bytes_atomic(runner_path, _RUNNER.encode("utf-8"))
        executable = _sandbox_python(sandbox_root)
        try:
            completed = subprocess.run(
                [
                    str(executable),
                    str(runner_path),
                    str(notebook_path.resolve()),
                    str(working_root),
                    str(input_root),
                    str(requirements_path),
                    REHEARSAL_AUTHORITY,
                ],
                cwd=sandbox_root,
                env=_sanitized_environment(working_root),
                check=False,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
            )
        except subprocess.TimeoutExpired as error:
            raise PackagingError(f"offline notebook sandbox exceeded {timeout_seconds}s") from error
        if completed.returncode != 0:
            stderr = completed.stderr.strip()[-4000:]
            raise PackagingError(
                f"offline notebook sandbox failed with exit {completed.returncode}: {stderr}"
            )
        output_lines = [line for line in completed.stdout.splitlines() if line.strip()]
        if not output_lines:
            raise PackagingError("offline notebook sandbox emitted no receipt")
        try:
            raw_receipt = json.loads(output_lines[-1])
        except json.JSONDecodeError as error:
            raise PackagingError("offline notebook sandbox receipt was not JSON") from error
        if not isinstance(raw_receipt, dict):
            raise PackagingError("offline notebook sandbox receipt must be an object")
        sandbox_submission = working_root / "submission.parquet"
        if not sandbox_submission.is_file():
            raise PackagingError("offline notebook sandbox did not preserve submission.parquet")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(sandbox_submission, output_path)

    network_attempts = raw_receipt.get("network_attempts")
    network_enforcement = raw_receipt.get("network_enforcement")
    gateway_connections = raw_receipt.get("gateway_connections")
    credentials = raw_receipt.get("credentials_present")
    installed_wheels = raw_receipt.get("installed_wheel_sha256")
    imported_agent = raw_receipt.get("imported_agent_path")
    imported_arc3 = raw_receipt.get("imported_arc3_path")
    rehearsal_requirements_sha256 = raw_receipt.get("rehearsal_requirements_sha256")
    framework_commit = raw_receipt.get("framework_commit")
    framework_identity = raw_receipt.get("framework_identity")
    status = raw_receipt.get("status")
    agent_action_cycle_status = raw_receipt.get("agent_action_cycle_status")
    agent_consequence_state = raw_receipt.get("agent_consequence_state")
    agent_cycle_actions = raw_receipt.get("agent_cycle_actions")
    agent_count = raw_receipt.get("agent_count")
    worker_count = raw_receipt.get("worker_count")
    max_concurrency = raw_receipt.get("max_concurrency")
    orchestration = raw_receipt.get("orchestration")
    if not isinstance(network_attempts, int) or network_attempts < 0:
        raise PackagingError("sandbox receipt has an invalid network-attempt count")
    if network_enforcement != PYTHON_NETWORK_ENFORCEMENT:
        raise PackagingError("sandbox receipt overstates or omits its network enforcement scope")
    if not isinstance(gateway_connections, int) or gateway_connections < 2:
        raise PackagingError("sandbox did not exercise the local gateway path")
    if not isinstance(credentials, list) or not all(isinstance(item, str) for item in credentials):
        raise PackagingError("sandbox receipt has an invalid credential inventory")
    if not isinstance(installed_wheels, list) or not all(
        isinstance(item, str) and item.startswith("sha256:") for item in installed_wheels
    ):
        raise PackagingError("sandbox receipt has an invalid wheel inventory")
    if not isinstance(imported_agent, str) or not imported_agent:
        raise PackagingError("sandbox receipt has no imported agent path")
    if not isinstance(imported_arc3, str) or not imported_arc3:
        raise PackagingError("sandbox receipt has no imported ARC3 path")
    if not isinstance(rehearsal_requirements_sha256, str):
        raise PackagingError("sandbox receipt has no rehearsal requirements identity")
    if not isinstance(framework_commit, str):
        raise PackagingError("sandbox receipt has no framework identity")
    if not isinstance(framework_identity, str):
        raise PackagingError("sandbox receipt has no executed framework identity")
    if (
        not isinstance(agent_count, int)
        or agent_count != 1
        or not isinstance(worker_count, int)
        or worker_count != agent_count
        or max_concurrency != 1
        or orchestration != "arc3.sequential-pinned-swarm.v1"
    ):
        raise PackagingError("sandbox receipt has no bounded sequential orchestration evidence")
    if (
        agent_action_cycle_status != "PASS"
        or agent_consequence_state != "NOT_FINISHED"
        or not isinstance(agent_cycle_actions, list)
        or len(agent_cycle_actions) != 2
        or agent_cycle_actions[0] != "RESET"
        or not isinstance(agent_cycle_actions[1], str)
        or agent_cycle_actions[1] not in {f"ACTION{index}" for index in range(1, 8)}
    ):
        raise PackagingError("sandbox receipt has no valid packaged agent consequence cycle")
    if (
        status != "PASS"
        or network_attempts
        or credentials
        or raw_receipt.get("dependency_install_status") != "PASS"
        or raw_receipt.get("framework_fixture") is not True
        or framework_identity != SAFE_FRAMEWORK_FIXTURE_IDENTITY
        or raw_receipt.get("production_rerun_exercised") is not True
        or raw_receipt.get("secret_scan_status") != "PASS"
    ):
        raise PackagingError("offline sandbox detected a weakened competition rehearsal")
    return SandboxReceipt(
        status="PASS",
        agent_action_cycle_status="PASS",
        agent_consequence_state=agent_consequence_state,
        agent_cycle_actions=(agent_cycle_actions[0], agent_cycle_actions[1]),
        network_attempts=network_attempts,
        network_enforcement=PYTHON_NETWORK_ENFORCEMENT,
        credentials_present=tuple(cast(list[str], credentials)),
        imported_agent_path=imported_agent,
        imported_arc3_path=imported_arc3,
        output_sha256=sha256_file(output_path),
        output_size_bytes=output_path.stat().st_size,
        notebook_sha256=notebook_sha256,
        payload_sha256=payload_sha256,
        requirements_sha256=requirements_sha256,
        rehearsal_requirements_sha256=rehearsal_requirements_sha256,
        installed_wheel_sha256=tuple(cast(list[str], installed_wheels)),
        framework_commit=framework_commit,
        framework_identity=framework_identity,
        framework_fixture=True,
        agent_count=agent_count,
        worker_count=worker_count,
        max_concurrency=1,
        orchestration=orchestration,
        production_rerun_exercised=True,
        dependency_install_status="PASS",
        gateway_connections=gateway_connections,
        secret_scan_status="PASS",
        limitations=(
            "The production KAGGLE_IS_COMPETITION_RERUN branch and no-index pip command ran, "
            "but a deterministic pure-Python canary wheel plus host-installed pinned runtime "
            "dependencies replaced the Linux wheel set on this Windows host.",
            "The launcher ran against a distinct deterministic safe-framework fixture; the "
            "launcher contains core-file hashes measured from the pinned Agents commit, but the "
            "competition-provided framework tree was unavailable and was not executed locally.",
            "A loopback HTTP gateway fixture reproduced discovery and output handoff; Kaggle's "
            "private gateway sidecar and official evaluator were unavailable locally.",
            "Network denial in this rehearsal is limited to guarded Python socket entry points. "
            "OS-level network containment is absent, so native code, direct system calls, and "
            "child-process egress were not proven impossible.",
        ),
    )


__all__ = ["run_offline_sandbox"]
