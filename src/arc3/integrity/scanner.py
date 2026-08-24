"""Deterministic static checks for ARC3 competition policy and candidate files."""

from __future__ import annotations

import ast
import importlib.util
import io
import json
import os
import re
import stat
import struct
import subprocess
import zipfile
from collections import deque
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath

from arc3.integrity.dependencies import inventory_locked_dependencies
from arc3.integrity.hashes import canonical_json_bytes, sha256_bytes, sha256_file
from arc3.integrity.models import (
    DependencyRecord,
    FindingCategory,
    FindingSeverity,
    IntegrityFinding,
    IntegrityReceipt,
)
from arc3.types import JSONValue

INTEGRITY_SCHEMA = "arc3.integrity.receipt.v0.2"
SCANNER_IDENTITY = "arc3.competition-static-integrity.v0.2"
DEFAULT_MAX_CANDIDATE_BYTES = 32 * 1024 * 1024
DEFAULT_MAX_ARCHIVE_BYTES = 256 * 1024 * 1024
DEFAULT_MAX_ARCHIVE_MEMBER_BYTES = 32 * 1024 * 1024
DEFAULT_MAX_ARCHIVE_MEMBERS = 20_000
DEFAULT_MAX_ARCHIVE_EXPANDED_BYTES = 512 * 1024 * 1024
DEFAULT_MAX_ARCHIVE_CENTRAL_DIRECTORY_BYTES = 64 * 1024 * 1024
DEFAULT_MAX_ARCHIVE_DEPTH = 1
DEFAULT_ENTRY_POINTS: tuple[str, ...] = ("agent/my_agent.py",)
_FIRST_PARTY_PAYLOAD_MEMBER = "arc3-first-party.zip"
_ZIP_END_RECORD = struct.Struct("<4s4H2LH")
_ZIP_END_SIGNATURE = b"PK\x05\x06"
_ZIP_CENTRAL_RECORD = struct.Struct("<4s6H3L5H2L")
_ZIP_CENTRAL_SIGNATURE = b"PK\x01\x02"
_PACKAGE_ONLY_PROTECTED_DIRECTORIES: tuple[str, ...] = (
    "artifacts",
    "docs/evaluation",
)
_PACKAGE_ONLY_PROTECTED_FILES: tuple[str, ...] = (
    "docs/ledger/build-001-run-state.json",
    "docs/ledger/run-state.json",
)

DEFAULT_POLICY_PATHS: tuple[str, ...] = (
    "agent",
    "src/arc3",
)
DEFAULT_NON_POLICY_PATHS: tuple[str, ...] = (
    "src/arc3/adapters",
    "src/arc3/__main__.py",
    "src/arc3/cli.py",
    "src/arc3/doctor.py",
    "src/arc3/evaluation",
    "src/arc3/integrity",
    "src/arc3/lab",
    "src/arc3/packaging/builder.py",
    "src/arc3/packaging/sandbox.py",
)

_FORBIDDEN_MODULES: tuple[str, ...] = (
    "aiohttp",
    "anthropic",
    "arc3.adapters.arc_agi",
    "arc_agi",
    "boto3",
    "botocore",
    "ftplib",
    "google.generativeai",
    "google.genai",
    "google.cloud.aiplatform",
    "grpc",
    "huggingface_hub",
    "http.client",
    "httpx",
    "openai",
    "replicate",
    "requests",
    "smtplib",
    "socket",
    "telnetlib",
    "urllib.request",
    "websockets",
    "webbrowser",
    "xai",
    "xmlrpc.client",
)
_SAFE_IMPORT_MEMBERS: frozenset[tuple[str, str]] = frozenset()
_PATH_SCOPED_SAFE_IMPORT_MEMBERS = {
    "src/arc3/packaging/runtime_launcher.py": frozenset(
        {
            ("urllib.request", "ProxyHandler"),
            ("urllib.request", "Request"),
            ("urllib.request", "build_opener"),
        }
    )
}
_NETWORK_CAPABLE_CALLS = frozenset(
    {
        "asyncio.create_subprocess_exec",
        "asyncio.create_subprocess_shell",
        "asyncio.open_connection",
        "asyncio.start_server",
        "os.popen",
        "os.spawnl",
        "os.spawnle",
        "os.spawnlp",
        "os.spawnlpe",
        "os.spawnv",
        "os.spawnve",
        "os.spawnvp",
        "os.spawnvpe",
        "os.system",
        "subprocess.call",
        "subprocess.check_call",
        "subprocess.check_output",
        "subprocess.Popen",
        "subprocess.run",
    }
)
_GAME_ID_SHAPE = re.compile(r"[a-z0-9]{2,16}-[0-9a-f]{8}", re.ASCII)
_ACTION_LITERAL = re.compile(r"(?:ACTION[1-7]|RESET)", re.IGNORECASE)
_SUSPICIOUS_TARGET_PARTS: tuple[str, ...] = (
    "solution",
    "walkthrough",
    "cheat",
    "game_plan",
    "game_script",
    "scripted_action",
    "known_plan",
    "known_actions",
    "action_sequence",
    "public_plan",
    "level_plan",
)
_SECRET_RULES: tuple[tuple[str, re.Pattern[str], str | None], ...] = (
    (
        "private-key-header",
        re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |PGP )?PRIVATE KEY-----"),
        None,
    ),
    (
        "aws-access-key",
        re.compile(r"\b(?P<secret>AKIA[0-9A-Z]{16})\b", re.ASCII),
        "secret",
    ),
    (
        "github-token",
        re.compile(r"\b(?P<secret>gh[pousr]_[A-Za-z0-9]{30,255})\b", re.ASCII),
        "secret",
    ),
    (
        "kaggle-token",
        re.compile(r"\b(?P<secret>KGAT_[A-Za-z0-9_-]{20,255})\b", re.ASCII),
        "secret",
    ),
    (
        "hosted-model-token",
        re.compile(
            r"\b(?P<secret>sk-(?:(?:proj|ant|svcacct)-)?[A-Za-z0-9_-]{20,})\b",
            re.ASCII,
        ),
        "secret",
    ),
    (
        "google-api-key",
        re.compile(r"\b(?P<secret>AIza[0-9A-Za-z_-]{30,})\b", re.ASCII),
        "secret",
    ),
    (
        "generic-secret-assignment",
        re.compile(
            r"(?i)\b(?:api[_-]?key|access[_-]?token|client[_-]?secret|password)\b"
            r"\s*[:=]\s*[\"']?(?P<secret>[A-Za-z0-9_./+=:-]{20,})[\"']?"
        ),
        "secret",
    ),
    (
        "json-web-token",
        re.compile(
            r"\b(?P<secret>eyJ[A-Za-z0-9_-]{12,}\.[A-Za-z0-9_-]{12,}\."
            r"[A-Za-z0-9_-]{12,})\b",
            re.ASCII,
        ),
        "secret",
    ),
    (
        "kaggle-json-key",
        re.compile(r"(?i)\"key\"\s*:\s*\"(?P<secret>[a-f0-9]{32,})\""),
        "secret",
    ),
)
_PLACEHOLDER_MARKERS = (
    "placeholder",
    "example",
    "changeme",
    "your_",
    "sentinel",
    "not_a_secret",
    "abcdefghijklmnop",
    "<",
    "${",
)


@dataclass(frozen=True, slots=True)
class PublicIdentifierSet:
    """Manifest-derived identifiers and the exact source identity."""

    identifiers: tuple[str, ...]
    manifest_hash: str | None


@dataclass(frozen=True, slots=True)
class ManifestBinding:
    """Expected manifest identity and the declaration that supplied it."""

    expected_sha256: str | None
    declaration: str
    issue: str | None = None


def _relative_path(root: Path, path: Path) -> str:
    repository = Path(os.path.abspath(root))
    candidate = Path(os.path.abspath(path))
    try:
        return candidate.relative_to(repository).as_posix()
    except ValueError as error:
        raise ValueError(f"scan path is outside repository root: {path}") from error


def _is_within(root: Path, path: Path) -> bool:
    try:
        _relative_path(root, path)
    except ValueError:
        return False
    return True


def _line_number(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _finding(
    *,
    root: Path,
    path: Path,
    line: int,
    category: FindingCategory,
    rule_id: str,
    evidence: str,
    message: str,
    severity: FindingSeverity = FindingSeverity.ERROR,
) -> IntegrityFinding:
    return _finding_for_label(
        path_label=_relative_path(root, path),
        line=line,
        category=category,
        rule_id=rule_id,
        evidence=evidence,
        message=message,
        severity=severity,
    )


def _finding_for_label(
    *,
    path_label: str,
    line: int,
    category: FindingCategory,
    rule_id: str,
    evidence: str,
    message: str,
    severity: FindingSeverity = FindingSeverity.ERROR,
) -> IntegrityFinding:
    return IntegrityFinding(
        path=path_label,
        line=line,
        category=category,
        rule_id=rule_id,
        severity=severity,
        evidence_sha256=sha256_bytes(evidence.encode("utf-8")),
        message=message,
    )


def load_public_identifiers(manifest_path: Path) -> PublicIdentifierSet:
    """Load public game IDs and stable names without embedding them in policy code."""

    raw = manifest_path.read_bytes()
    document = json.loads(raw)
    if not isinstance(document, dict):
        raise ValueError("public partition manifest must contain a JSON object")
    games = document.get("games")
    if not isinstance(games, list):
        raise ValueError("public partition manifest must contain a games array")
    identifiers: set[str] = set()
    for item in games:
        if not isinstance(item, dict):
            raise ValueError("public partition game entry must be an object")
        for field in ("game_id", "stable_name"):
            value = item.get(field)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"public partition game entry has invalid {field}")
            identifiers.add(value)
    return PublicIdentifierSet(tuple(sorted(identifiers)), sha256_bytes(raw))


def discover_policy_files(
    root: Path,
    policy_paths: Sequence[str | Path] = DEFAULT_POLICY_PATHS,
    *,
    excluded_paths: Sequence[str | Path] = DEFAULT_NON_POLICY_PATHS,
    candidate_files: Sequence[Path] | None = None,
    candidate_snapshots: Mapping[str, bytes] | None = None,
    entry_points: Sequence[str | Path] = DEFAULT_ENTRY_POINTS,
    max_bytes: int = DEFAULT_MAX_CANDIDATE_BYTES,
) -> tuple[Path, ...]:
    """Discover shipped policy sources/assets plus reachable first-party modules."""

    repository = Path(os.path.abspath(root))
    candidates = (
        discover_candidate_files(repository)
        if candidate_files is None
        else tuple(Path(os.path.abspath(path)) for path in candidate_files)
    )
    roots = tuple(_repository_input_path(repository, raw_path) for raw_path in policy_paths)
    excluded = tuple(_repository_input_path(repository, raw_path) for raw_path in excluded_paths)
    found = {
        path
        for path in candidates
        if any(_path_at_or_below(path, prefix) for prefix in roots)
        and not any(_path_at_or_below(path, prefix) for prefix in excluded)
    }
    found.update(
        discover_reachable_policy_files(
            repository,
            candidate_files=candidates,
            entry_points=entry_points,
            candidate_snapshots=candidate_snapshots,
            max_bytes=max_bytes,
        )
    )
    return tuple(sorted(found, key=lambda item: _relative_path(root, item)))


def _git_environment() -> dict[str, str]:
    environment = {
        key: value for key, value in os.environ.items() if not key.upper().startswith("GIT_")
    }
    environment["GIT_NO_REPLACE_OBJECTS"] = "1"
    return environment


def _git_result(root: Path, *arguments: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["git", "--no-replace-objects", "-C", str(root.resolve()), *arguments],
        check=False,
        capture_output=True,
        env=_git_environment(),
    )


def _candidate_from_git(root: Path) -> tuple[Path, ...] | None:
    try:
        top_level = _git_result(root, "rev-parse", "--show-toplevel")
        completed = _git_result(
            root,
            "ls-files",
            "-z",
            "--cached",
            "--others",
            "--exclude-standard",
        )
    except OSError:
        return None
    if top_level.returncode != 0 or completed.returncode != 0:
        return None
    try:
        git_root = Path(top_level.stdout.decode("utf-8", errors="strict").strip()).resolve()
    except (OSError, UnicodeDecodeError):
        return None
    if git_root != root.resolve():
        return None
    try:
        names = completed.stdout.decode("utf-8").split("\0")
    except UnicodeDecodeError:
        return None
    return tuple(Path(os.path.abspath(root / name)) for name in names if name)


def discover_candidate_files(
    root: Path,
    *,
    excluded_paths: Sequence[Path] = (),
) -> tuple[Path, ...]:
    """Discover every tracked or unignored candidate path without filtering content."""

    repository = Path(os.path.abspath(root))
    discovered = _candidate_from_git(repository)
    if discovered is None:
        discovered = tuple(
            Path(os.path.abspath(path))
            for path in repository.rglob("*")
            if path.is_file() or path.is_symlink()
        )
    excluded = {Path(os.path.abspath(path)) for path in excluded_paths}
    filtered = {
        path
        for path in discovered
        if path not in excluded
        and ".git" not in PurePosixPath(_relative_path(repository, path)).parts
    }
    return tuple(sorted(filtered, key=lambda item: _relative_path(repository, item)))


def _repository_input_path(root: Path, raw_path: str | Path) -> Path:
    candidate = Path(raw_path)
    if not candidate.is_absolute():
        candidate = root / candidate
    normalized = Path(os.path.abspath(candidate))
    _relative_path(root, normalized)
    return normalized


def _archive_input_path(root: Path, raw_path: str | Path) -> Path:
    """Normalize an explicitly supplied archive without requiring checkout residency."""

    candidate = Path(raw_path)
    if not candidate.is_absolute():
        candidate = root / candidate
    return Path(os.path.abspath(candidate))


def _archive_path_labels(root: Path, archives: Sequence[Path]) -> Mapping[Path, str]:
    """Return portable labels for repository-local and explicitly supplied archives."""

    labels: dict[Path, str] = {}
    for index, archive in enumerate(archives):
        if _is_within(root, archive):
            label = _relative_path(root, archive)
        else:
            safe_name = re.sub(r"[^A-Za-z0-9._-]", "_", archive.name) or "archive.zip"
            label = f"@supplied-archive/{index:04d}/{safe_name}"
        labels[archive] = label
    return labels


def _path_at_or_below(path: Path, prefix: Path) -> bool:
    return path == prefix or prefix in path.parents


def _package_only_protected_candidate(root: Path, path: Path) -> str | None:
    lexical_directories = tuple(
        _repository_input_path(root, relative) for relative in _PACKAGE_ONLY_PROTECTED_DIRECTORIES
    )
    lexical_files = tuple(
        _repository_input_path(root, relative) for relative in _PACKAGE_ONLY_PROTECTED_FILES
    )
    try:
        resolved_path = path.resolve(strict=False)
        resolved_directories = tuple(item.resolve(strict=False) for item in lexical_directories)
        resolved_files = tuple(item.resolve(strict=False) for item in lexical_files)
    except OSError as error:
        raise ValueError(
            "package-only integrity cannot validate a candidate path without reading it"
        ) from error
    if path in lexical_files or resolved_path in resolved_files:
        return _relative_path(root, path)
    if any(_path_at_or_below(path, item) for item in lexical_directories) or any(
        _path_at_or_below(resolved_path, item) for item in resolved_directories
    ):
        return _relative_path(root, path)
    return None


def _module_name_for_path(root: Path, path: Path) -> str | None:
    if path.suffix.lower() != ".py":
        return None
    parts = list(Path(_relative_path(root, path)).parts)
    if parts and parts[0] == "src":
        parts.pop(0)
    if not parts:
        return None
    if parts[-1] == "__init__.py":
        parts.pop()
    else:
        parts[-1] = Path(parts[-1]).stem
    return ".".join(parts) if parts else None


def _literal_string(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = _literal_string(node.left)
        right = _literal_string(node.right)
        if left is not None and right is not None:
            return left + right
    if isinstance(node, ast.JoinedStr):
        values: list[str] = []
        for value in node.values:
            literal = _literal_string(value)
            if literal is None:
                return None
            values.append(literal)
        return "".join(values)
    return None


def _module_import_targets(
    *,
    tree: ast.AST,
    module_name: str,
    is_package: bool,
    available_modules: frozenset[str],
) -> tuple[str, ...]:
    package = module_name if is_package else module_name.rpartition(".")[0]
    targets: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            targets.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                relative = "." * node.level + (node.module or "")
                try:
                    base = importlib.util.resolve_name(relative, package)
                except (ImportError, ValueError):
                    continue
            else:
                base = node.module or ""
            safe_boundary_import = bool(base) and all(
                (base, alias.name) in _SAFE_IMPORT_MEMBERS for alias in node.names
            )
            if base:
                targets.add(base)
            if base and not safe_boundary_import:
                targets.update(f"{base}.{alias.name}" for alias in node.names)
        elif isinstance(node, ast.Call):
            called = _qualified_name(node.func) or ""
            if called in {"__import__", "import_module", "importlib.import_module"} and node.args:
                literal = _literal_string(node.args[0])
                if literal:
                    targets.add(literal)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            if node.value in available_modules:
                targets.add(node.value)
    expanded: set[str] = set()
    for target in targets:
        parts = target.split(".")
        for end in range(1, len(parts) + 1):
            candidate = ".".join(parts[:end])
            if candidate in available_modules:
                expanded.add(candidate)
    return tuple(sorted(expanded))


def discover_reachable_policy_files(
    root: Path,
    *,
    candidate_files: Sequence[Path],
    entry_points: Sequence[str | Path] = DEFAULT_ENTRY_POINTS,
    candidate_snapshots: Mapping[str, bytes] | None = None,
    max_bytes: int = DEFAULT_MAX_CANDIDATE_BYTES,
) -> tuple[Path, ...]:
    """Resolve static first-party imports reachable from shipped entry points."""

    module_paths: dict[str, Path] = {}
    for path in candidate_files:
        if path.is_symlink() or not path.is_file():
            continue
        module_name = _module_name_for_path(root, path)
        if module_name is not None:
            module_paths[module_name] = path
    available = frozenset(module_paths)
    queued: deque[Path] = deque()
    for raw_entry in entry_points:
        entry = _repository_input_path(root, raw_entry)
        if entry.is_file() and not entry.is_symlink():
            queued.append(entry)
    reached: set[Path] = set()
    while queued:
        path = queued.popleft()
        if path in reached:
            continue
        reached.add(path)
        module_name = _module_name_for_path(root, path)
        if module_name is None:
            continue
        try:
            if candidate_snapshots is None:
                raw, unreadable = _read_scannable_file(
                    root=root,
                    path=path,
                    max_bytes=max_bytes,
                    path_label=_relative_path(root, path),
                )
                if unreadable is not None or raw is None:
                    continue
            else:
                relative = _relative_path(root, path)
                raw = candidate_snapshots.get(relative)
                if raw is None:
                    raise ValueError(
                        f"exact candidate snapshot projection omits reachable path: {relative}"
                    )
                if len(raw) > max_bytes:
                    raise ValueError(
                        f"exact candidate snapshot exceeds reachability limit: {relative}"
                    )
            source = raw.decode("utf-8")
            tree = ast.parse(source, filename=_relative_path(root, path))
        except (OSError, UnicodeDecodeError, SyntaxError):
            continue
        for target in _module_import_targets(
            tree=tree,
            module_name=module_name,
            is_package=path.name == "__init__.py",
            available_modules=available,
        ):
            imported = module_paths[target]
            if imported not in reached:
                queued.append(imported)
    return tuple(sorted(reached, key=lambda item: _relative_path(root, item)))


def _qualified_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _qualified_name(node.value)
        return f"{parent}.{node.attr}" if parent else node.attr
    return None


def _forbidden_module(module: str) -> str | None:
    lowered = module.lower()
    for prefix in _FORBIDDEN_MODULES:
        if lowered == prefix or lowered.startswith(f"{prefix}."):
            return prefix
    return None


def _target_names(node: ast.AST) -> tuple[str, ...]:
    if isinstance(node, ast.Name):
        return (node.id,)
    if isinstance(node, (ast.Tuple, ast.List)):
        return tuple(name for item in node.elts for name in _target_names(item))
    return ()


def _suspicious_target(name: str) -> bool:
    lowered = name.lower()
    return any(part in lowered for part in _SUSPICIOUS_TARGET_PARTS)


def _is_action_atom(node: ast.AST) -> bool:
    if isinstance(node, ast.Constant):
        if isinstance(node.value, str):
            return _ACTION_LITERAL.fullmatch(node.value.upper()) is not None
        return (
            isinstance(node.value, int)
            and not isinstance(node.value, bool)
            and 1 <= node.value <= 7
        )
    if isinstance(node, ast.Attribute):
        return _ACTION_LITERAL.fullmatch(node.attr.upper()) is not None
    if isinstance(node, ast.Call):
        name = _qualified_name(node.func)
        return name is not None and name.rsplit(".", 1)[-1] in {"ActionRequest", "GameAction"}
    return False


def _action_atom_count(node: ast.AST) -> int:
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        return sum(1 for item in node.elts if _is_action_atom(item))
    if isinstance(node, ast.Dict):
        return max((_action_atom_count(item) for item in node.values), default=0)
    return 1 if _is_action_atom(node) else 0


class _PolicyVisitor(ast.NodeVisitor):
    def __init__(
        self,
        *,
        root: Path,
        path: Path,
        source: str,
        path_label: str | None = None,
        policy_path: str | None = None,
    ) -> None:
        self.root = root
        self.path = path
        self.source = source
        self.path_label = path_label or _relative_path(root, path)
        self.policy_path = policy_path or self.path_label
        self.findings: list[IntegrityFinding] = []
        self.aliases: dict[str, str] = {}

    def _safe_import_member(self, module: str, member: str) -> bool:
        imported = (module, member)
        return imported in _SAFE_IMPORT_MEMBERS or imported in (
            _PATH_SCOPED_SAFE_IMPORT_MEMBERS.get(self.policy_path, frozenset())
        )

    def _resolved_name(self, node: ast.AST) -> str | None:
        qualified = _qualified_name(node)
        if qualified is None:
            return None
        first, separator, remainder = qualified.partition(".")
        replacement = self.aliases.get(first)
        if replacement is None:
            return qualified
        return replacement + (separator + remainder if separator else "")

    def _add(
        self,
        node: ast.AST,
        *,
        category: FindingCategory,
        rule_id: str,
        evidence: str,
        message: str,
    ) -> None:
        self.findings.append(
            _finding_for_label(
                path_label=self.path_label,
                line=getattr(node, "lineno", 1),
                category=category,
                rule_id=rule_id,
                evidence=evidence,
                message=message,
            )
        )

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            local_name = alias.asname or alias.name.split(".", 1)[0]
            self.aliases[local_name] = alias.name if alias.asname else local_name
            forbidden = _forbidden_module(alias.name)
            if forbidden:
                self._add(
                    node,
                    category=FindingCategory.FORBIDDEN_NETWORK_CLIENT,
                    rule_id="forbidden-import",
                    evidence=alias.name,
                    message="production policy imports a forbidden network or hosted client",
                )
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        module = node.module or ""
        for alias in node.names:
            if alias.name != "*":
                self.aliases[alias.asname or alias.name] = (
                    f"{module}.{alias.name}" if module else alias.name
                )
        unsafe_aliases = tuple(
            alias for alias in node.names if not self._safe_import_member(module, alias.name)
        )
        candidates = (
            ()
            if not unsafe_aliases
            else (module, *(f"{module}.{alias.name}" for alias in unsafe_aliases))
        )
        forbidden_candidates = sorted(
            candidate for candidate in candidates if _forbidden_module(candidate)
        )
        for forbidden in forbidden_candidates:
            self._add(
                node,
                category=FindingCategory.FORBIDDEN_NETWORK_CLIENT,
                rule_id="forbidden-from-import",
                evidence=forbidden,
                message="production policy imports a forbidden network or hosted client",
            )
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        qualified = self._resolved_name(node.func) or ""
        if qualified in {"import_module", "importlib.import_module", "__import__"} and node.args:
            module_name = _literal_string(node.args[0])
            if module_name is not None and _forbidden_module(module_name):
                self._add(
                    node,
                    category=FindingCategory.FORBIDDEN_NETWORK_CLIENT,
                    rule_id="forbidden-dynamic-import",
                    evidence=module_name,
                    message="production policy dynamically imports a forbidden client",
                )
        if qualified in _NETWORK_CAPABLE_CALLS:
            self._add(
                node,
                category=FindingCategory.FORBIDDEN_NETWORK_CLIENT,
                rule_id="network-capable-call",
                evidence=qualified,
                message="production policy invokes a network-capable process or async API",
            )
        self.generic_visit(node)

    def visit_Assign(self, node: ast.Assign) -> None:
        names = tuple(name for target in node.targets for name in _target_names(target))
        if any(_suspicious_target(name) for name in names) and _action_atom_count(node.value) >= 2:
            self._add(
                node,
                category=FindingCategory.GAME_SPECIFIC_LOGIC,
                rule_id="scripted-action-table",
                evidence=ast.get_source_segment(self.source, node) or "scripted-action-table",
                message="production policy contains an obvious scripted action/solution table",
            )
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        names = _target_names(node.target)
        if (
            node.value is not None
            and any(_suspicious_target(name) for name in names)
            and _action_atom_count(node.value) >= 2
        ):
            self._add(
                node,
                category=FindingCategory.GAME_SPECIFIC_LOGIC,
                rule_id="scripted-action-table",
                evidence=ast.get_source_segment(self.source, node) or "scripted-action-table",
                message="production policy contains an obvious scripted action/solution table",
            )
        self.generic_visit(node)

    def visit_Dict(self, node: ast.Dict) -> None:
        for key, value in zip(node.keys, node.values, strict=True):
            if (
                isinstance(key, ast.Constant)
                and isinstance(key.value, str)
                and _GAME_ID_SHAPE.fullmatch(key.value.lower())
                and _action_atom_count(value) >= 2
            ):
                self._add(
                    node,
                    category=FindingCategory.GAME_SPECIFIC_LOGIC,
                    rule_id="game-keyed-action-table",
                    evidence=key.value,
                    message="production policy contains a game-keyed action sequence",
                )
        self.generic_visit(node)

    def visit_Constant(self, node: ast.Constant) -> None:
        if isinstance(node.value, str) and _GAME_ID_SHAPE.fullmatch(node.value.lower()):
            self._add(
                node,
                category=FindingCategory.GAME_SPECIFIC_LOGIC,
                rule_id="game-id-shaped-literal",
                evidence=node.value,
                message="production policy contains a game-ID-shaped literal",
            )


def _read_scannable_file(
    *,
    root: Path,
    path: Path,
    max_bytes: int,
    read_contents: bool = True,
    path_label: str | None = None,
) -> tuple[bytes | None, IntegrityFinding | None]:
    def unreadable_finding(
        *,
        rule_id: str,
        evidence: str,
        message: str,
    ) -> IntegrityFinding:
        if path_label is not None:
            return _finding_for_label(
                path_label=path_label,
                line=1,
                category=FindingCategory.UNSCANNABLE_CANDIDATE,
                rule_id=rule_id,
                evidence=evidence,
                message=message,
            )
        return _finding(
            root=root,
            path=path,
            line=1,
            category=FindingCategory.UNSCANNABLE_CANDIDATE,
            rule_id=rule_id,
            evidence=evidence,
            message=message,
        )

    def is_alias(metadata: os.stat_result) -> bool:
        reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
        attributes = getattr(metadata, "st_file_attributes", 0)
        return stat.S_ISLNK(metadata.st_mode) or bool(attributes & reparse_flag)

    def same_identity(left: os.stat_result, right: os.stat_result) -> bool:
        return left.st_dev == right.st_dev and left.st_ino != 0 and left.st_ino == right.st_ino

    flags = os.O_RDONLY
    flags |= getattr(os, "O_BINARY", 0)
    flags |= getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        try:
            metadata = path.lstat()
        except OSError:
            metadata = None
        if metadata is not None and is_alias(metadata):
            return None, unreadable_finding(
                rule_id="candidate-symlink",
                evidence="symlink-or-reparse-point",
                message="candidate path is an alias and is not safe to follow",
            )
        return None, unreadable_finding(
            rule_id="candidate-unreadable",
            evidence=type(error).__name__,
            message="candidate path cannot be read for static assurance",
        )
    try:
        try:
            metadata = os.fstat(descriptor)
            path_metadata = path.lstat()
        except OSError as error:
            return None, unreadable_finding(
                rule_id="candidate-unreadable",
                evidence=type(error).__name__,
                message="candidate path identity cannot be verified for static assurance",
            )
        if is_alias(path_metadata):
            return None, unreadable_finding(
                rule_id="candidate-symlink",
                evidence="symlink-or-reparse-point",
                message="candidate path is an alias and is not safe to follow",
            )
        if not stat.S_ISREG(metadata.st_mode) or not stat.S_ISREG(path_metadata.st_mode):
            return None, unreadable_finding(
                rule_id="candidate-not-regular",
                evidence=str(metadata.st_mode),
                message="candidate path is not a regular file",
            )
        if not same_identity(metadata, path_metadata):
            return None, unreadable_finding(
                rule_id="candidate-path-race",
                evidence="descriptor-path-identity-mismatch",
                message="candidate path changed while its scan descriptor was opened",
            )
        if metadata.st_size > max_bytes:
            return None, unreadable_finding(
                rule_id="candidate-size-limit",
                evidence=str(metadata.st_size),
                message="candidate file exceeds the explicit static-scan byte limit",
            )
        if not read_contents:
            return b"", None
        chunks: list[bytes] = []
        remaining = max_bytes + 1
        while remaining > 0:
            chunk = os.read(descriptor, min(1024 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        raw = b"".join(chunks)
        if len(raw) > max_bytes:
            return None, unreadable_finding(
                rule_id="candidate-size-limit",
                evidence=str(len(raw)),
                message="candidate file exceeds the explicit static-scan byte limit",
            )
        try:
            final_metadata = os.fstat(descriptor)
            final_path_metadata = path.lstat()
        except OSError as error:
            return None, unreadable_finding(
                rule_id="candidate-unreadable",
                evidence=type(error).__name__,
                message="candidate path identity cannot be reverified after static scanning",
            )
        if is_alias(final_path_metadata) or not same_identity(final_metadata, final_path_metadata):
            return None, unreadable_finding(
                rule_id="candidate-path-race",
                evidence="post-read-descriptor-path-identity-mismatch",
                message="candidate path changed while its bounded snapshot was read",
            )
        initial_version = (metadata.st_size, metadata.st_mtime_ns, metadata.st_ctime_ns)
        final_version = (
            final_metadata.st_size,
            final_metadata.st_mtime_ns,
            final_metadata.st_ctime_ns,
        )
        if initial_version != final_version:
            return None, unreadable_finding(
                rule_id="candidate-mutated-during-scan",
                evidence="descriptor-metadata-changed",
                message="candidate bytes changed while the bounded snapshot was read",
            )
        return raw, None
    except OSError as error:
        return None, unreadable_finding(
            rule_id="candidate-unreadable",
            evidence=type(error).__name__,
            message="candidate path cannot be read for static assurance",
        )
    finally:
        os.close(descriptor)


def read_bounded_regular_snapshot(
    *,
    root: Path,
    path: Path,
    max_bytes: int = DEFAULT_MAX_CANDIDATE_BYTES,
    path_label: str | None = None,
) -> bytes:
    """Read one immutable regular-file snapshot through the scanner's fd boundary."""

    raw, finding = _read_scannable_file(
        root=root,
        path=path,
        max_bytes=max_bytes,
        read_contents=True,
        path_label=path_label,
    )
    if finding is not None:
        raise ValueError(f"{finding.rule_id}: {finding.message}")
    assert raw is not None
    return raw


def _scan_text_for_public_identifiers(
    *,
    path_label: str,
    text: str,
    identifiers: Sequence[str],
) -> list[IntegrityFinding]:
    findings: list[IntegrityFinding] = []
    for identifier in identifiers:
        pattern = re.compile(
            rf"(?<![A-Za-z0-9-]){re.escape(identifier)}(?![A-Za-z0-9-])",
            re.IGNORECASE,
        )
        for match in pattern.finditer(text):
            findings.append(
                _finding_for_label(
                    path_label=path_label,
                    line=_line_number(text, match.start()),
                    category=FindingCategory.PUBLIC_GAME_IDENTIFIER,
                    rule_id="manifest-public-identifier",
                    evidence=match.group(0),
                    message="production policy contains a manifest-derived public identifier",
                )
            )
    return findings


def _scan_data_for_action_tables(*, path_label: str, text: str) -> list[IntegrityFinding]:
    findings: list[IntegrityFinding] = []
    action_matches = tuple(_ACTION_LITERAL.finditer(text))
    lowered_path = path_label.lower()
    if len(action_matches) >= 2 and any(part in lowered_path for part in _SUSPICIOUS_TARGET_PARTS):
        findings.append(
            _finding_for_label(
                path_label=path_label,
                line=_line_number(text, action_matches[0].start()),
                category=FindingCategory.GAME_SPECIFIC_LOGIC,
                rule_id="scripted-action-data",
                evidence=sha256_bytes(text.encode("utf-8")),
                message="shipped policy data contains an obvious scripted action table",
            )
        )
    for match in _GAME_ID_SHAPE.finditer(text.lower()):
        nearby = text[match.end() : match.end() + 4096]
        if len(tuple(_ACTION_LITERAL.finditer(nearby))) >= 2:
            findings.append(
                _finding_for_label(
                    path_label=path_label,
                    line=_line_number(text, match.start()),
                    category=FindingCategory.GAME_SPECIFIC_LOGIC,
                    rule_id="game-keyed-action-data",
                    evidence=match.group(0),
                    message="shipped policy data contains a game-keyed action sequence",
                )
            )
    return findings


def _scan_text_for_secrets(*, path_label: str, text: str) -> list[IntegrityFinding]:
    findings: list[IntegrityFinding] = []
    for rule_id, pattern, secret_group in _SECRET_RULES:
        for match in pattern.finditer(text):
            matched = match.group(0)
            candidate_secret = match.group(secret_group) if secret_group is not None else matched
            if secret_group is not None and any(
                marker in candidate_secret.lower() for marker in _PLACEHOLDER_MARKERS
            ):
                continue
            findings.append(
                _finding_for_label(
                    path_label=path_label,
                    line=_line_number(text, match.start()),
                    category=FindingCategory.LIKELY_SECRET,
                    rule_id=rule_id,
                    evidence=matched,
                    message="candidate file contains a likely secret; matched text is redacted",
                )
            )
    return findings


def scan_policy_files(
    *,
    root: Path,
    files: Iterable[Path],
    public_identifiers: Iterable[str],
    max_bytes: int = DEFAULT_MAX_CANDIDATE_BYTES,
    file_snapshots: Mapping[str, bytes] | None = None,
) -> tuple[IntegrityFinding, ...]:
    """Scan shipped production policy sources and data for static violations."""

    identifiers = tuple(sorted(set(public_identifiers), key=lambda value: (-len(value), value)))
    findings: list[IntegrityFinding] = []
    for path in files:
        path_label = _relative_path(root, path)
        if file_snapshots is None:
            raw, unreadable = _read_scannable_file(root=root, path=path, max_bytes=max_bytes)
        else:
            raw = file_snapshots.get(path_label)
            unreadable = None
            if raw is None:
                findings.append(
                    _finding_for_label(
                        path_label=path_label,
                        line=1,
                        category=FindingCategory.UNSCANNABLE_CANDIDATE,
                        rule_id="candidate-snapshot-missing",
                        evidence=path_label,
                        message="immutable candidate snapshot projection is incomplete",
                    )
                )
                continue
            if len(raw) > max_bytes:
                findings.append(
                    _finding_for_label(
                        path_label=path_label,
                        line=1,
                        category=FindingCategory.UNSCANNABLE_CANDIDATE,
                        rule_id="candidate-size-limit",
                        evidence=str(len(raw)),
                        message="candidate file exceeds the explicit static-scan byte limit",
                    )
                )
                continue
        if unreadable is not None:
            findings.append(unreadable)
            continue
        assert raw is not None
        try:
            source = raw.decode("utf-8")
        except UnicodeDecodeError:
            source = raw.decode("latin-1")
        findings.extend(
            _scan_text_for_public_identifiers(
                path_label=path_label,
                text=source,
                identifiers=identifiers,
            )
        )
        if path.suffix.lower() != ".py":
            findings.extend(_scan_data_for_action_tables(path_label=path_label, text=source))
            continue
        try:
            tree = ast.parse(source, filename=path_label)
        except (SyntaxError, UnicodeEncodeError) as error:
            findings.append(
                _finding(
                    root=root,
                    path=path,
                    line=getattr(error, "lineno", None) or 1,
                    category=FindingCategory.UNPARSEABLE_SOURCE,
                    rule_id="unparseable-policy-source",
                    evidence=str(error),
                    message="production policy source cannot be parsed for static assurance",
                )
            )
            continue
        visitor = _PolicyVisitor(root=root, path=path, source=source)
        visitor.visit(tree)
        findings.extend(visitor.findings)
    return tuple(sorted(set(findings)))


def scan_secret_files(
    *,
    root: Path,
    files: Iterable[Path],
    max_bytes: int = DEFAULT_MAX_CANDIDATE_BYTES,
    file_snapshots: Mapping[str, bytes] | None = None,
) -> tuple[IntegrityFinding, ...]:
    """Scan every candidate byte stream while redacting matched values."""

    findings: list[IntegrityFinding] = []
    for path in files:
        path_label = _relative_path(root, path)
        if file_snapshots is None:
            raw, unreadable = _read_scannable_file(root=root, path=path, max_bytes=max_bytes)
        else:
            raw = file_snapshots.get(path_label)
            unreadable = None
            if raw is None:
                findings.append(
                    _finding_for_label(
                        path_label=path_label,
                        line=1,
                        category=FindingCategory.UNSCANNABLE_CANDIDATE,
                        rule_id="candidate-snapshot-missing",
                        evidence=path_label,
                        message="immutable candidate snapshot projection is incomplete",
                    )
                )
                continue
            if len(raw) > max_bytes:
                findings.append(
                    _finding_for_label(
                        path_label=path_label,
                        line=1,
                        category=FindingCategory.UNSCANNABLE_CANDIDATE,
                        rule_id="candidate-size-limit",
                        evidence=str(len(raw)),
                        message="candidate file exceeds the explicit static-scan byte limit",
                    )
                )
                continue
        if unreadable is not None:
            findings.append(unreadable)
            continue
        assert raw is not None
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            text = raw.decode("latin-1")
        findings.extend(_scan_text_for_secrets(path_label=path_label, text=text))
    return tuple(sorted(set(findings)))


def _safe_archive_member(name: str) -> bool:
    normalized = name.replace("\\", "/")
    member = PurePosixPath(normalized)
    windows = PureWindowsPath(name)
    raw_parts = normalized.rstrip("/").split("/")
    return bool(name) and not (
        "\x00" in name
        or "\\" in name
        or member.is_absolute()
        or windows.is_absolute()
        or bool(windows.drive)
        or any(part in {"", ".", ".."} or ":" in part for part in raw_parts)
    )


def _archive_policy_member(name: str) -> bool:
    normalized = PurePosixPath(name.replace("\\", "/")).as_posix()
    if any(
        normalized == excluded or normalized.startswith(excluded + "/")
        for excluded in DEFAULT_NON_POLICY_PATHS
    ):
        return False
    parts = PurePosixPath(normalized).parts
    return bool(parts) and (
        parts[0] in {"agent", "arc3"}
        or (len(parts) >= 2 and parts[0] == "src" and parts[1] == "arc3")
    )


@dataclass(slots=True)
class _ArchiveScanBudget:
    """Cumulative expansion and member budget shared by nested archives."""

    archive_bytes: int = 0
    central_directory_bytes: int = 0
    expanded_bytes: int = 0
    members: int = 0


@dataclass(frozen=True, slots=True)
class _ZipPreflight:
    """Bounded metadata decoded without constructing a ZipFile."""

    central_directory_bytes: int
    member_count: int


def _zip_preflight(
    raw: bytes,
    *,
    max_members: int,
    max_central_directory_bytes: int,
) -> _ZipPreflight:
    """Read a single-disk non-ZIP64 EOCD before ZipFile materializes metadata."""

    minimum_size = _ZIP_END_RECORD.size
    offset = raw.rfind(
        _ZIP_END_SIGNATURE,
        max(0, len(raw) - (minimum_size + 65_535)),
    )
    if offset < 0 or offset + minimum_size > len(raw):
        raise ValueError("missing ZIP end-of-central-directory record")
    (
        signature,
        disk_number,
        central_disk,
        disk_entries,
        total_entries,
        central_size,
        central_offset,
        comment_size,
    ) = _ZIP_END_RECORD.unpack_from(raw, offset)
    if signature != _ZIP_END_SIGNATURE or offset + minimum_size + comment_size != len(raw):
        raise ValueError("malformed ZIP end-of-central-directory record")
    if disk_number != 0 or central_disk != 0 or disk_entries != total_entries:
        raise ValueError("multi-disk ZIP archives are unsupported")
    if total_entries == 0xFFFF or central_size == 0xFFFFFFFF or central_offset == 0xFFFFFFFF:
        raise ValueError("ZIP64 metadata is unsupported by the bounded static scanner")
    if total_entries > max_members:
        raise ValueError("ZIP member count exceeds the bounded static-scanner limit")
    if central_size > max_central_directory_bytes:
        raise ValueError("ZIP central directory exceeds the static-scanner byte limit")
    if central_offset + central_size > offset:
        raise ValueError("ZIP central directory exceeds its declared bounds")
    cursor = central_offset
    central_end = central_offset + central_size
    parsed_entries = 0
    while cursor < central_end:
        if cursor + _ZIP_CENTRAL_RECORD.size > central_end:
            raise ValueError("truncated ZIP central-directory record")
        fields = _ZIP_CENTRAL_RECORD.unpack_from(raw, cursor)
        if fields[0] != _ZIP_CENTRAL_SIGNATURE:
            raise ValueError("invalid ZIP central-directory record signature")
        filename_size, extra_size, member_comment_size = fields[10:13]
        name_start = cursor + _ZIP_CENTRAL_RECORD.size
        name_end = name_start + filename_size
        try:
            filename = raw[name_start:name_end].decode(
                "utf-8" if fields[3] & 0x800 else "cp437",
                errors="strict",
            )
        except UnicodeDecodeError as error:
            raise ValueError("ZIP central directory has a non-portable member name") from error
        if not _safe_archive_member(filename):
            raise ValueError("ZIP central directory has an unsafe member path")
        cursor += _ZIP_CENTRAL_RECORD.size + filename_size + extra_size + member_comment_size
        if cursor > central_end:
            raise ValueError("ZIP central-directory variable fields exceed their declared bounds")
        parsed_entries += 1
        if parsed_entries > max_members:
            raise ValueError("ZIP parsed member count exceeds the bounded static-scanner limit")
    if cursor != central_end or parsed_entries != total_entries:
        raise ValueError("ZIP central-directory record count disagrees with its end record")
    return _ZipPreflight(
        central_directory_bytes=int(central_size),
        member_count=int(total_entries),
    )


def _scan_zip_handle(
    *,
    root: Path,
    handle: zipfile.ZipFile,
    path_label: str,
    identifiers: Sequence[str],
    budget: _ArchiveScanBudget,
    depth: int,
    max_depth: int,
    max_archive_bytes: int,
    max_member_bytes: int,
    max_members: int,
    max_expanded_bytes: int,
    max_central_directory_bytes: int,
    declared_member_count: int,
    declared_central_directory_bytes: int,
) -> list[IntegrityFinding]:
    """Scan one ZIP and the exact shipped first-party payload under one budget."""

    findings: list[IntegrityFinding] = []
    members = handle.infolist()
    if len(members) != declared_member_count:
        findings.append(
            _finding_for_label(
                path_label=path_label,
                line=1,
                category=FindingCategory.UNSAFE_ARCHIVE,
                rule_id="archive-central-directory-count-mismatch",
                evidence=f"{declared_member_count}:{len(members)}",
                message="ZIP metadata count changed between bounded preflight and decoding",
            )
        )
        return findings
    names = [member.filename for member in members]
    if len(names) != len(set(names)):
        findings.append(
            _finding_for_label(
                path_label=path_label,
                line=1,
                category=FindingCategory.UNSAFE_ARCHIVE,
                rule_id="archive-duplicate-member",
                evidence=str(len(names) - len(set(names))),
                message="supplied archive contains duplicate member names",
            )
        )
    prospective_members = budget.members + len(members)
    if prospective_members > max_members:
        findings.append(
            _finding_for_label(
                path_label=path_label,
                line=1,
                category=FindingCategory.UNSAFE_ARCHIVE,
                rule_id="archive-member-count-limit",
                evidence=str(prospective_members),
                message="supplied archive tree exceeds the safe member-count limit",
            )
        )
        return findings
    prospective_central = budget.central_directory_bytes + declared_central_directory_bytes
    if prospective_central > max_central_directory_bytes:
        findings.append(
            _finding_for_label(
                path_label=path_label,
                line=1,
                category=FindingCategory.UNSAFE_ARCHIVE,
                rule_id="archive-central-directory-size-limit",
                evidence=str(prospective_central),
                message="supplied archive tree exceeds the central-directory byte limit",
            )
        )
        return findings
    budget.members = prospective_members
    budget.central_directory_bytes = prospective_central

    for member in members:
        member_label = f"{path_label}!/{member.filename}"
        normalized_name = PurePosixPath(member.filename.replace("\\", "/")).as_posix()
        is_nested_payload = normalized_name == _FIRST_PARTY_PAYLOAD_MEMBER
        if not _safe_archive_member(member.filename):
            findings.append(
                _finding_for_label(
                    path_label=member_label,
                    line=1,
                    category=FindingCategory.UNSAFE_ARCHIVE,
                    rule_id="archive-path-traversal",
                    evidence=member.filename,
                    message="supplied archive contains an unsafe member path",
                )
            )
            continue
        if member.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}:
            findings.append(
                _finding_for_label(
                    path_label=member_label,
                    line=1,
                    category=FindingCategory.UNSAFE_ARCHIVE,
                    rule_id="archive-compression-unsupported",
                    evidence=str(member.compress_type),
                    message="archive member uses an unbounded decoder that is not permitted",
                )
            )
            continue
        mode = member.external_attr >> 16
        file_type = stat.S_IFMT(mode)
        windows_reparse = member.create_system == 0 and bool(member.external_attr & 0x400)
        if stat.S_ISLNK(mode) or windows_reparse:
            findings.append(
                _finding_for_label(
                    path_label=member_label,
                    line=1,
                    category=FindingCategory.UNSAFE_ARCHIVE,
                    rule_id="archive-symlink",
                    evidence=str(mode),
                    message="supplied archive contains a symlink member",
                )
            )
            continue
        if file_type not in {0, stat.S_IFREG, stat.S_IFDIR}:
            findings.append(
                _finding_for_label(
                    path_label=member_label,
                    line=1,
                    category=FindingCategory.UNSAFE_ARCHIVE,
                    rule_id="archive-special-member",
                    evidence=str(mode),
                    message="supplied archive contains a non-regular special member",
                )
            )
            continue
        if member.is_dir():
            continue
        if member.file_size > max_member_bytes:
            findings.append(
                _finding_for_label(
                    path_label=member_label,
                    line=1,
                    category=FindingCategory.UNSCANNABLE_CANDIDATE,
                    rule_id="archive-member-size-limit",
                    evidence=str(member.file_size),
                    message="archive member exceeds the safe static-scan byte limit",
                )
            )
            continue
        remaining_archive_bytes = max_archive_bytes - budget.archive_bytes
        if is_nested_payload and member.file_size > remaining_archive_bytes:
            findings.append(
                _finding_for_label(
                    path_label=member_label,
                    line=1,
                    category=FindingCategory.UNSAFE_ARCHIVE,
                    rule_id="archive-total-size-limit",
                    evidence=str(budget.archive_bytes + member.file_size),
                    message="supplied archive tree exceeds the cumulative archive-byte limit",
                )
            )
            continue
        prospective_expanded = budget.expanded_bytes + member.file_size
        if prospective_expanded > max_expanded_bytes:
            findings.append(
                _finding_for_label(
                    path_label=path_label,
                    line=1,
                    category=FindingCategory.UNSAFE_ARCHIVE,
                    rule_id="archive-expanded-size-limit",
                    evidence=str(prospective_expanded),
                    message="supplied archive tree exceeds the safe expanded-byte limit",
                )
            )
            break
        member_read_limit = (
            min(max_member_bytes, remaining_archive_bytes)
            if is_nested_payload
            else max_member_bytes
        )
        with handle.open(member, "r") as member_stream:
            member_raw = member_stream.read(member_read_limit + 1)
        if len(member_raw) > member_read_limit:
            if is_nested_payload:
                findings.append(
                    _finding_for_label(
                        path_label=member_label,
                        line=1,
                        category=FindingCategory.UNSAFE_ARCHIVE,
                        rule_id="archive-total-size-limit",
                        evidence=str(max_archive_bytes + 1),
                        message=("supplied archive tree exceeds the cumulative archive-byte limit"),
                    )
                )
                continue
            findings.append(
                _finding_for_label(
                    path_label=member_label,
                    line=1,
                    category=FindingCategory.UNSCANNABLE_CANDIDATE,
                    rule_id="archive-member-read-limit",
                    evidence=str(len(member_raw)),
                    message="archive member exceeded its declared safe read limit",
                )
            )
            continue
        actual_expanded = budget.expanded_bytes + max(member.file_size, len(member_raw))
        if actual_expanded > max_expanded_bytes:
            findings.append(
                _finding_for_label(
                    path_label=path_label,
                    line=1,
                    category=FindingCategory.UNSAFE_ARCHIVE,
                    rule_id="archive-expanded-size-limit",
                    evidence=str(actual_expanded),
                    message="supplied archive tree exceeds the safe expanded-byte limit",
                )
            )
            break
        budget.expanded_bytes = actual_expanded

        if is_nested_payload:
            if depth >= max_depth:
                findings.append(
                    _finding_for_label(
                        path_label=member_label,
                        line=1,
                        category=FindingCategory.UNSAFE_ARCHIVE,
                        rule_id="archive-nesting-depth-limit",
                        evidence=str(depth + 1),
                        message="first-party payload exceeds the safe archive nesting depth",
                    )
                )
                continue
            nested_stream = io.BytesIO(member_raw)
            if not zipfile.is_zipfile(nested_stream):
                findings.append(
                    _finding_for_label(
                        path_label=member_label,
                        line=1,
                        category=FindingCategory.UNSCANNABLE_CANDIDATE,
                        rule_id="nested-payload-invalid",
                        evidence=_FIRST_PARTY_PAYLOAD_MEMBER,
                        message="first-party payload is not a supported ZIP-compatible artifact",
                    )
                )
                continue
            try:
                nested_preflight = _zip_preflight(
                    member_raw,
                    max_members=max_members,
                    max_central_directory_bytes=max_central_directory_bytes,
                )
            except ValueError as error:
                findings.append(
                    _finding_for_label(
                        path_label=member_label,
                        line=1,
                        category=FindingCategory.UNSAFE_ARCHIVE,
                        rule_id="archive-central-directory-unsafe",
                        evidence=type(error).__name__,
                        message=str(error),
                    )
                )
                continue
            if budget.members + nested_preflight.member_count > max_members:
                findings.append(
                    _finding_for_label(
                        path_label=member_label,
                        line=1,
                        category=FindingCategory.UNSAFE_ARCHIVE,
                        rule_id="archive-member-count-limit",
                        evidence=str(budget.members + nested_preflight.member_count),
                        message="supplied archive tree exceeds the safe member-count limit",
                    )
                )
                continue
            if (
                budget.central_directory_bytes + nested_preflight.central_directory_bytes
                > max_central_directory_bytes
            ):
                findings.append(
                    _finding_for_label(
                        path_label=member_label,
                        line=1,
                        category=FindingCategory.UNSAFE_ARCHIVE,
                        rule_id="archive-central-directory-size-limit",
                        evidence=str(
                            budget.central_directory_bytes
                            + nested_preflight.central_directory_bytes
                        ),
                        message="supplied archive tree exceeds the central-directory byte limit",
                    )
                )
                continue
            prospective_archive_bytes = budget.archive_bytes + len(member_raw)
            if prospective_archive_bytes > max_archive_bytes:
                findings.append(
                    _finding_for_label(
                        path_label=member_label,
                        line=1,
                        category=FindingCategory.UNSAFE_ARCHIVE,
                        rule_id="archive-total-size-limit",
                        evidence=str(prospective_archive_bytes),
                        message="supplied archive tree exceeds the cumulative archive-byte limit",
                    )
                )
                continue
            budget.archive_bytes = prospective_archive_bytes
            with zipfile.ZipFile(io.BytesIO(member_raw)) as nested:
                findings.extend(
                    _scan_zip_handle(
                        root=root,
                        handle=nested,
                        path_label=member_label,
                        identifiers=identifiers,
                        budget=budget,
                        depth=depth + 1,
                        max_depth=max_depth,
                        max_archive_bytes=max_archive_bytes,
                        max_member_bytes=max_member_bytes,
                        max_members=max_members,
                        max_expanded_bytes=max_expanded_bytes,
                        max_central_directory_bytes=max_central_directory_bytes,
                        declared_member_count=nested_preflight.member_count,
                        declared_central_directory_bytes=(nested_preflight.central_directory_bytes),
                    )
                )
            continue

        try:
            text = member_raw.decode("utf-8")
        except UnicodeDecodeError:
            text = member_raw.decode("latin-1")
        findings.extend(
            _scan_text_for_public_identifiers(
                path_label=member_label,
                text=text,
                identifiers=identifiers,
            )
        )
        findings.extend(_scan_text_for_secrets(path_label=member_label, text=text))
        if _archive_policy_member(member.filename):
            if PurePosixPath(member.filename).suffix.lower() == ".py":
                try:
                    tree = ast.parse(text, filename=member_label)
                except (SyntaxError, UnicodeEncodeError) as error:
                    findings.append(
                        _finding_for_label(
                            path_label=member_label,
                            line=getattr(error, "lineno", None) or 1,
                            category=FindingCategory.UNPARSEABLE_SOURCE,
                            rule_id="unparseable-archive-policy-source",
                            evidence=str(error),
                            message="archived production policy source cannot be parsed for static assurance",
                        )
                    )
                else:
                    visitor = _PolicyVisitor(
                        root=root,
                        path=Path(path_label),
                        source=text,
                        path_label=member_label,
                        policy_path=PurePosixPath(member.filename.replace("\\", "/")).as_posix(),
                    )
                    visitor.visit(tree)
                    findings.extend(visitor.findings)
            else:
                findings.extend(_scan_data_for_action_tables(path_label=member_label, text=text))
    return findings


def scan_archive_files(
    *,
    root: Path,
    archives: Iterable[Path],
    public_identifiers: Iterable[str],
    max_archive_bytes: int = DEFAULT_MAX_ARCHIVE_BYTES,
    max_member_bytes: int = DEFAULT_MAX_ARCHIVE_MEMBER_BYTES,
    max_members: int = DEFAULT_MAX_ARCHIVE_MEMBERS,
    max_expanded_bytes: int = DEFAULT_MAX_ARCHIVE_EXPANDED_BYTES,
    max_central_directory_bytes: int = DEFAULT_MAX_ARCHIVE_CENTRAL_DIRECTORY_BYTES,
    max_depth: int = DEFAULT_MAX_ARCHIVE_DEPTH,
    scanned_hashes: dict[str, str] | None = None,
    scanned_snapshots: dict[str, bytes] | None = None,
) -> tuple[IntegrityFinding, ...]:
    """Safely scan supplied competition artifacts and their exact policy payload."""

    identifiers = tuple(sorted(set(public_identifiers), key=lambda value: (-len(value), value)))
    findings: list[IntegrityFinding] = []
    if (
        min(
            max_archive_bytes,
            max_member_bytes,
            max_members,
            max_expanded_bytes,
            max_central_directory_bytes,
            max_depth,
        )
        <= 0
    ):
        raise ValueError("archive scan limits must be positive")
    archive_sequence = tuple(archives)
    archive_labels = _archive_path_labels(root, archive_sequence)
    budget = _ArchiveScanBudget()
    for archive in archive_sequence:
        path_label = archive_labels[archive]
        remaining_archive_bytes = max_archive_bytes - budget.archive_bytes
        raw, unreadable = _read_scannable_file(
            root=root,
            path=archive,
            max_bytes=remaining_archive_bytes,
            read_contents=True,
            path_label=path_label,
        )
        if unreadable is not None:
            if unreadable.rule_id == "candidate-size-limit" and budget.archive_bytes:
                findings.append(
                    _finding_for_label(
                        path_label=path_label,
                        line=1,
                        category=FindingCategory.UNSAFE_ARCHIVE,
                        rule_id="archive-total-size-limit",
                        evidence=str(max_archive_bytes + 1),
                        message=("supplied archive tree exceeds the cumulative archive-byte limit"),
                    )
                )
                continue
            findings.append(unreadable)
            continue
        assert raw is not None
        prospective_archive_bytes = budget.archive_bytes + len(raw)
        if prospective_archive_bytes > max_archive_bytes:
            findings.append(
                _finding_for_label(
                    path_label=path_label,
                    line=1,
                    category=FindingCategory.UNSAFE_ARCHIVE,
                    rule_id="archive-total-size-limit",
                    evidence=str(prospective_archive_bytes),
                    message="supplied archive tree exceeds the cumulative archive-byte limit",
                )
            )
            continue
        budget.archive_bytes = prospective_archive_bytes
        if scanned_hashes is not None:
            scanned_hashes[path_label] = sha256_bytes(raw)
        if scanned_snapshots is not None:
            scanned_snapshots[path_label] = raw
        archive_stream = io.BytesIO(raw)
        if not zipfile.is_zipfile(archive_stream):
            findings.append(
                _finding_for_label(
                    path_label=path_label,
                    line=1,
                    category=FindingCategory.UNSCANNABLE_CANDIDATE,
                    rule_id="unsupported-archive-format",
                    evidence=archive.suffix.lower(),
                    message="supplied archive is not a supported ZIP-compatible artifact",
                )
            )
            continue
        try:
            preflight = _zip_preflight(
                raw,
                max_members=max_members,
                max_central_directory_bytes=max_central_directory_bytes,
            )
        except ValueError as error:
            findings.append(
                _finding_for_label(
                    path_label=path_label,
                    line=1,
                    category=FindingCategory.UNSAFE_ARCHIVE,
                    rule_id="archive-central-directory-unsafe",
                    evidence=type(error).__name__,
                    message=str(error),
                )
            )
            continue
        if budget.members + preflight.member_count > max_members:
            findings.append(
                _finding_for_label(
                    path_label=path_label,
                    line=1,
                    category=FindingCategory.UNSAFE_ARCHIVE,
                    rule_id="archive-member-count-limit",
                    evidence=str(budget.members + preflight.member_count),
                    message="supplied archive tree exceeds the safe member-count limit",
                )
            )
            continue
        if (
            budget.central_directory_bytes + preflight.central_directory_bytes
            > max_central_directory_bytes
        ):
            findings.append(
                _finding_for_label(
                    path_label=path_label,
                    line=1,
                    category=FindingCategory.UNSAFE_ARCHIVE,
                    rule_id="archive-central-directory-size-limit",
                    evidence=str(
                        budget.central_directory_bytes + preflight.central_directory_bytes
                    ),
                    message="supplied archive tree exceeds the central-directory byte limit",
                )
            )
            continue
        try:
            with zipfile.ZipFile(io.BytesIO(raw)) as handle:
                findings.extend(
                    _scan_zip_handle(
                        root=root,
                        handle=handle,
                        path_label=path_label,
                        identifiers=identifiers,
                        budget=budget,
                        depth=0,
                        max_depth=max_depth,
                        max_archive_bytes=max_archive_bytes,
                        max_member_bytes=max_member_bytes,
                        max_members=max_members,
                        max_expanded_bytes=max_expanded_bytes,
                        max_central_directory_bytes=max_central_directory_bytes,
                        declared_member_count=preflight.member_count,
                        declared_central_directory_bytes=preflight.central_directory_bytes,
                    )
                )
        except (
            EOFError,
            NotImplementedError,
            OSError,
            RuntimeError,
            ValueError,
            zipfile.BadZipFile,
        ) as error:
            findings.append(
                _finding_for_label(
                    path_label=path_label,
                    line=1,
                    category=FindingCategory.UNSCANNABLE_CANDIDATE,
                    rule_id="archive-read-failure",
                    evidence=type(error).__name__,
                    message="supplied archive could not be read safely",
                )
            )
    return tuple(sorted(set(findings)))


def _git_identity(
    root: Path,
    *,
    excluded_paths: Sequence[Path] = (),
) -> tuple[str | None, bool | None]:
    status_arguments = [
        "status",
        "--porcelain=v1",
        "--untracked-files=all",
        "--",
        ".",
    ]
    status_arguments.extend(f":(exclude){_relative_path(root, path)}" for path in excluded_paths)
    try:
        top_level = _git_result(root, "rev-parse", "--show-toplevel")
        commit = _git_result(root, "rev-parse", "HEAD")
        status = _git_result(root, *status_arguments)
    except OSError:
        return None, None
    if top_level.returncode != 0 or commit.returncode != 0 or status.returncode != 0:
        return None, None
    try:
        git_root = Path(top_level.stdout.decode("utf-8", errors="strict").strip()).resolve()
        commit_text = commit.stdout.decode("ascii", errors="strict").strip()
    except (OSError, UnicodeDecodeError):
        return None, None
    if git_root != root.resolve():
        return None, None
    return commit_text, bool(status.stdout)


def _normalize_sha256(value: str) -> str:
    raw = value.removeprefix("sha256:").lower()
    if re.fullmatch(r"[0-9a-f]{64}", raw) is None:
        raise ValueError("expected SHA-256 must contain exactly 64 hexadecimal digits")
    return f"sha256:{raw}"


def _declared_manifest_binding(
    *,
    root: Path,
    manifest: Path,
    run_state: Path,
    explicit_expected: str | None,
) -> ManifestBinding:
    if explicit_expected is not None:
        try:
            explicit_digest = _normalize_sha256(explicit_expected)
        except ValueError as error:
            return ManifestBinding(None, "explicit-argument", str(error))
        return ManifestBinding(explicit_digest, "explicit-argument")
    if not run_state.is_file() or run_state.is_symlink():
        return ManifestBinding(None, _relative_path(root, run_state), "run-state unavailable")
    try:
        document = json.loads(run_state.read_bytes())
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        return ManifestBinding(
            None,
            _relative_path(root, run_state),
            f"run-state unreadable:{type(error).__name__}",
        )
    if not isinstance(document, dict):
        return ManifestBinding(None, _relative_path(root, run_state), "run-state is not an object")
    manifest_label = _relative_path(root, manifest)
    declarations: list[str] = []
    evidence = document.get("evidence")
    if isinstance(evidence, dict):
        stage_02 = evidence.get("stage_02")
        if (
            isinstance(stage_02, dict)
            and stage_02.get("public_partition_manifest") == manifest_label
        ):
            value = stage_02.get("public_partition_manifest_sha256")
            if isinstance(value, str):
                declarations.append(value)
    artifacts = document.get("artifacts")
    if isinstance(artifacts, dict):
        artifact = artifacts.get("public_game_partitions_v0_1")
        if isinstance(artifact, dict) and artifact.get("path") == manifest_label:
            value = artifact.get("sha256")
            if isinstance(value, str):
                declarations.append(value)
    holdout = document.get("holdout")
    if isinstance(holdout, dict) and holdout.get("manifest") == manifest_label:
        value = holdout.get("manifest_sha256")
        if isinstance(value, str):
            declarations.append(value)
    try:
        declared_digests = {_normalize_sha256(value) for value in declarations}
    except ValueError as error:
        return ManifestBinding(None, _relative_path(root, run_state), str(error))
    if not declared_digests:
        return ManifestBinding(
            None,
            _relative_path(root, run_state),
            "run-state has no declaration for the selected manifest",
        )
    if len(declared_digests) != 1:
        return ManifestBinding(
            None,
            _relative_path(root, run_state),
            "run-state contains conflicting manifest identities",
        )
    return ManifestBinding(declared_digests.pop(), _relative_path(root, run_state))


def _required_path_findings(
    *,
    root: Path,
    required_paths: Sequence[tuple[str, Path]],
) -> list[IntegrityFinding]:
    findings: list[IntegrityFinding] = []
    for label, path in required_paths:
        try:
            metadata = path.lstat()
        except OSError as error:
            findings.append(
                _finding(
                    root=root,
                    path=path,
                    line=1,
                    category=FindingCategory.SOURCE_IDENTITY,
                    rule_id="required-input-missing",
                    evidence=f"{label}:{type(error).__name__}",
                    message=f"required integrity input is missing: {label}",
                )
            )
            continue
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
            findings.append(
                _finding(
                    root=root,
                    path=path,
                    line=1,
                    category=FindingCategory.SOURCE_IDENTITY,
                    rule_id="required-input-not-regular",
                    evidence=f"{label}:{metadata.st_mode}",
                    message=f"required integrity input is not a regular file: {label}",
                )
            )
        elif metadata.st_size == 0:
            findings.append(
                _finding(
                    root=root,
                    path=path,
                    line=1,
                    category=FindingCategory.SOURCE_IDENTITY,
                    rule_id="required-input-empty",
                    evidence=label,
                    message=f"required integrity input is empty: {label}",
                )
            )
    return findings


def build_integrity_receipt(
    root: Path,
    *,
    manifest_path: Path | None = None,
    policy_paths: Sequence[str | Path] = DEFAULT_POLICY_PATHS,
    excluded_policy_paths: Sequence[str | Path] = DEFAULT_NON_POLICY_PATHS,
    candidate_files: Sequence[Path] | None = None,
    candidate_snapshots: Mapping[str, bytes] | None = None,
    lock_path: Path | None = None,
    run_state_path: Path | None = None,
    expected_manifest_sha256: str | None = None,
    entry_points: Sequence[str | Path] = DEFAULT_ENTRY_POINTS,
    archive_paths: Sequence[Path] = (),
    receipt_output_path: Path | None = None,
    max_candidate_bytes: int = DEFAULT_MAX_CANDIDATE_BYTES,
    include_installed_metadata: bool = True,
    generated_at: str | None = None,
    semantic_public_manifest_access: bool = True,
) -> IntegrityReceipt:
    """Build a deterministic, self-hashed repository integrity receipt.

    ``generated_at`` is caller-supplied and defaults to ``null`` so identical
    inputs on the same local environment produce byte-identical receipts.
    """

    if max_candidate_bytes <= 0:
        raise ValueError("max_candidate_bytes must be positive")
    repository = Path(os.path.abspath(root))
    if not semantic_public_manifest_access and (
        manifest_path is not None
        or run_state_path is not None
        or expected_manifest_sha256 is not None
    ):
        raise ValueError(
            "package-only integrity forbids manifest, run-state, and manifest-identity inputs"
        )
    if not semantic_public_manifest_access and candidate_files is None:
        raise ValueError(
            "package-only integrity requires an explicit protected-surface-free candidate set"
        )
    if not semantic_public_manifest_access:
        assert candidate_files is not None
        for raw_candidate in candidate_files:
            candidate = _repository_input_path(repository, raw_candidate)
            protected = _package_only_protected_candidate(repository, candidate)
            if protected is not None:
                raise ValueError(
                    "package-only integrity forbids protected candidate file: " + protected
                )
    manifest = (
        _repository_input_path(
            repository,
            manifest_path or "docs/evaluation/public-game-partitions.v0.1.json",
        )
        if semantic_public_manifest_access
        else None
    )
    dependency_lock = _repository_input_path(repository, lock_path or "uv.lock")
    run_state = (
        _repository_input_path(
            repository,
            run_state_path or "docs/ledger/run-state.json",
        )
        if semantic_public_manifest_access
        else None
    )
    archives = tuple(dict.fromkeys(_archive_input_path(repository, path) for path in archive_paths))
    archive_labels = _archive_path_labels(repository, archives)
    output_exclusions: tuple[Path, ...] = ()
    output_label: str | None = None
    if receipt_output_path is not None and _is_within(repository, receipt_output_path):
        output = Path(os.path.abspath(receipt_output_path))
        output_exclusions = (output,)
        output_label = _relative_path(repository, output)

    normalized_candidates = (
        discover_candidate_files(repository, excluded_paths=output_exclusions)
        if candidate_files is None
        else tuple(
            sorted(
                {
                    _repository_input_path(repository, path)
                    for path in candidate_files
                    if Path(os.path.abspath(path)) not in output_exclusions
                },
                key=lambda item: _relative_path(repository, item),
            )
        )
    )
    immutable_candidate_snapshots: dict[str, bytes] | None = None
    candidate_snapshot_total_bytes = 0
    if not semantic_public_manifest_access:
        if candidate_snapshots is None:
            supplemental_paths = (
                dependency_lock,
                repository / "LICENSE",
                repository / "pyproject.toml",
                repository / "upstream.lock.json",
                repository / "THIRD_PARTY_NOTICES.md",
                *(_repository_input_path(repository, item) for item in entry_points),
            )
            snapshot_paths = tuple(
                sorted(
                    {
                        *normalized_candidates,
                        *(path for path in supplemental_paths if path.is_file()),
                    },
                    key=lambda item: _relative_path(repository, item),
                )
            )
        else:
            snapshot_paths = normalized_candidates
        snapshot_labels = tuple(_relative_path(repository, path) for path in snapshot_paths)
        if len(snapshot_labels) > DEFAULT_MAX_ARCHIVE_MEMBERS:
            raise ValueError("package-only candidate snapshot exceeds the file-count limit")
        if candidate_snapshots is None:
            immutable_candidate_snapshots = {}
            for path, label in zip(snapshot_paths, snapshot_labels, strict=True):
                raw, unreadable = _read_scannable_file(
                    root=repository,
                    path=path,
                    max_bytes=max_candidate_bytes,
                    path_label=label,
                )
                if unreadable is not None or raw is None:
                    rule = unreadable.rule_id if unreadable is not None else "unknown"
                    raise ValueError(f"package-only candidate snapshot refused: {label}:{rule}")
                prospective_total = candidate_snapshot_total_bytes + len(raw)
                if prospective_total > DEFAULT_MAX_ARCHIVE_BYTES:
                    raise ValueError(
                        "package-only candidate snapshot exceeds the cumulative byte limit"
                    )
                candidate_snapshot_total_bytes = prospective_total
                immutable_candidate_snapshots[label] = raw
        else:
            if len(candidate_snapshots) != len(snapshot_labels):
                raise ValueError("package-only candidate snapshot membership is not exact")
            immutable_candidate_snapshots = {}
            for label in snapshot_labels:
                raw = candidate_snapshots.get(label)
                if not isinstance(raw, bytes):
                    raise ValueError(
                        "package-only candidate snapshot mapping has invalid or missing entries"
                    )
                if len(raw) > max_candidate_bytes:
                    raise ValueError(
                        f"package-only candidate snapshot exceeds the per-file limit: {label}"
                    )
                prospective_total = candidate_snapshot_total_bytes + len(raw)
                if prospective_total > DEFAULT_MAX_ARCHIVE_BYTES:
                    raise ValueError(
                        "package-only candidate snapshot exceeds the cumulative byte limit"
                    )
                candidate_snapshot_total_bytes = prospective_total
                immutable_candidate_snapshots[label] = raw

        def validate_live_candidate_snapshots() -> None:
            assert immutable_candidate_snapshots is not None
            for path, label in zip(snapshot_paths, snapshot_labels, strict=True):
                live, unreadable = _read_scannable_file(
                    root=repository,
                    path=path,
                    max_bytes=max_candidate_bytes,
                    path_label=label,
                )
                if unreadable is not None or live != immutable_candidate_snapshots[label]:
                    rule = unreadable.rule_id if unreadable is not None else "byte-mismatch"
                    raise ValueError(
                        f"live package-only candidate differs from immutable snapshot: "
                        f"{label}:{rule}"
                    )

        validate_live_candidate_snapshots()
    reachable_files = discover_reachable_policy_files(
        repository,
        candidate_files=normalized_candidates,
        entry_points=entry_points,
        candidate_snapshots=immutable_candidate_snapshots,
        max_bytes=max_candidate_bytes,
    )
    policy_files = discover_policy_files(
        repository,
        policy_paths,
        excluded_paths=excluded_policy_paths,
        candidate_files=normalized_candidates,
        candidate_snapshots=immutable_candidate_snapshots,
        entry_points=entry_points,
        max_bytes=max_candidate_bytes,
    )

    common_required_paths = (
        ("dependency-lock", dependency_lock),
        ("first-party-license", repository / "LICENSE"),
        ("pyproject", repository / "pyproject.toml"),
        ("upstream-lock", repository / "upstream.lock.json"),
        ("third-party-notices", repository / "THIRD_PARTY_NOTICES.md"),
        *(
            (f"entry-point:{Path(item).as_posix()}", _repository_input_path(repository, item))
            for item in entry_points
        ),
    )
    required_paths = (
        (
            ("manifest", manifest),
            common_required_paths[0],
            ("run-state", run_state),
            *common_required_paths[1:],
        )
        if manifest is not None and run_state is not None
        else common_required_paths
    )
    if candidate_snapshots is not None:
        assert immutable_candidate_snapshots is not None
        missing_required_snapshots = sorted(
            _relative_path(repository, path)
            for _label, path in required_paths
            if _relative_path(repository, path) not in immutable_candidate_snapshots
        )
        if missing_required_snapshots:
            raise ValueError(
                "package-only candidate snapshots omit required source inputs: "
                + ", ".join(missing_required_snapshots)
            )
    identity_findings = _required_path_findings(root=repository, required_paths=required_paths)

    if semantic_public_manifest_access:
        assert manifest is not None
        assert run_state is not None
        try:
            public = load_public_identifiers(manifest)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
            observed_hash = (
                sha256_file(manifest) if manifest.is_file() and not manifest.is_symlink() else None
            )
            public = PublicIdentifierSet((), observed_hash)
            identity_findings.append(
                _finding(
                    root=repository,
                    path=manifest,
                    line=1,
                    category=FindingCategory.SOURCE_IDENTITY,
                    rule_id="manifest-unusable",
                    evidence=type(error).__name__,
                    message="public partition manifest cannot supply a trusted identifier set",
                )
            )
        binding = _declared_manifest_binding(
            root=repository,
            manifest=manifest,
            run_state=run_state,
            explicit_expected=expected_manifest_sha256,
        )
        if binding.issue is not None or binding.expected_sha256 is None:
            identity_findings.append(
                _finding(
                    root=repository,
                    path=run_state if expected_manifest_sha256 is None else manifest,
                    line=1,
                    category=FindingCategory.SOURCE_IDENTITY,
                    rule_id="manifest-identity-unbound",
                    evidence=binding.issue or "missing expected identity",
                    message="public partition manifest has no valid pinned identity",
                )
            )
        elif public.manifest_hash != binding.expected_sha256:
            identity_findings.append(
                _finding(
                    root=repository,
                    path=manifest,
                    line=1,
                    category=FindingCategory.SOURCE_IDENTITY,
                    rule_id="manifest-identity-mismatch",
                    evidence=f"{binding.expected_sha256}:{public.manifest_hash}",
                    message="public partition manifest does not match its declared identity",
                )
            )
    else:
        public = PublicIdentifierSet((), None)
        binding = ManifestBinding(
            None,
            "disabled-package-only",
            "semantic public-manifest access is prohibited in this profile",
        )

    policy_findings = list(
        scan_policy_files(
            root=repository,
            files=policy_files,
            public_identifiers=public.identifiers,
            max_bytes=max_candidate_bytes,
            file_snapshots=immutable_candidate_snapshots,
        )
    )
    secret_findings = list(
        scan_secret_files(
            root=repository,
            files=(path for path in normalized_candidates if path not in archives),
            max_bytes=max_candidate_bytes,
            file_snapshots=immutable_candidate_snapshots,
        )
    )
    archive_scan_hashes: dict[str, str] = {}
    archive_findings = list(
        scan_archive_files(
            root=repository,
            archives=archives,
            public_identifiers=public.identifiers,
            scanned_hashes=archive_scan_hashes,
        )
    )

    dependencies: tuple[DependencyRecord, ...] = ()
    supply_findings: list[IntegrityFinding] = []
    if dependency_lock.is_file() and not dependency_lock.is_symlink():
        try:
            dependencies = inventory_locked_dependencies(
                dependency_lock,
                include_installed_metadata=include_installed_metadata,
                lock_snapshot=(
                    immutable_candidate_snapshots.get(_relative_path(repository, dependency_lock))
                    if immutable_candidate_snapshots is not None
                    else None
                ),
                first_party_source_snapshots=immutable_candidate_snapshots,
            )
        except (OSError, UnicodeDecodeError, ValueError) as error:
            supply_findings.append(
                _finding(
                    root=repository,
                    path=dependency_lock,
                    line=1,
                    category=FindingCategory.SUPPLY_CHAIN,
                    rule_id="dependency-lock-unusable",
                    evidence=type(error).__name__,
                    message="dependency lock cannot be inventoried",
                )
            )
    third_party = tuple(item for item in dependencies if item.name != "arc3")
    first_party = next((item for item in dependencies if item.name == "arc3"), None)
    unknown_dependencies = tuple(
        item for item in third_party if item.license_status in {"UNKNOWN", "MISSING_DISTRIBUTION"}
    )
    not_queried_dependencies = tuple(
        item for item in third_party if item.license_status == "NOT_QUERIED"
    )
    version_mismatches = tuple(
        item
        for item in third_party
        if item.installed_version is not None and item.installed_version != item.locked_version
    )
    if first_party is not None and first_party.license_status != "MIT-0":
        supply_findings.append(
            _finding(
                root=repository,
                path=repository / "LICENSE",
                line=1,
                category=FindingCategory.SUPPLY_CHAIN,
                rule_id="first-party-license-invalid",
                evidence=first_party.license_status,
                message="ARC3 first-party license does not match the owner-approved MIT-0 identity",
            )
        )
    for item in unknown_dependencies:
        supply_findings.append(
            _finding(
                root=repository,
                path=dependency_lock,
                line=1,
                category=FindingCategory.SUPPLY_CHAIN,
                rule_id="dependency-license-unresolved",
                evidence=f"{item.name}:{item.license_status}",
                message=f"third-party dependency license metadata is unresolved: {item.name}",
            )
        )
    for item in not_queried_dependencies:
        supply_findings.append(
            _finding(
                root=repository,
                path=dependency_lock,
                line=1,
                category=FindingCategory.SUPPLY_CHAIN,
                rule_id="dependency-license-not-evaluated",
                evidence=item.name,
                message=f"third-party dependency license metadata was not evaluated: {item.name}",
                severity=FindingSeverity.WARNING,
            )
        )
    for item in version_mismatches:
        supply_findings.append(
            _finding(
                root=repository,
                path=dependency_lock,
                line=1,
                category=FindingCategory.SUPPLY_CHAIN,
                rule_id="installed-version-mismatch",
                evidence=f"{item.name}:{item.locked_version}:{item.installed_version}",
                message=f"installed dependency does not match the lock: {item.name}",
            )
        )

    identity_paths = {
        *policy_files,
        *normalized_candidates,
        *archives,
        *(path for _, path in required_paths),
    }
    file_hashes: dict[str, JSONValue] = {}
    hash_findings: list[IntegrityFinding] = []

    def identity_label(path: Path) -> str:
        if path in archive_labels:
            return archive_labels[path]
        return _relative_path(repository, path)

    for path in sorted(identity_paths, key=identity_label):
        label = identity_label(path)
        if immutable_candidate_snapshots is not None and label in immutable_candidate_snapshots:
            file_hashes[label] = sha256_bytes(immutable_candidate_snapshots[label])
            continue
        if path in archive_labels and label in archive_scan_hashes:
            file_hashes[label] = archive_scan_hashes[label]
            continue
        try:
            metadata = path.lstat()
            if stat.S_ISREG(metadata.st_mode) and metadata.st_size <= max_candidate_bytes:
                file_hashes[label] = sha256_file(path)
            elif path in archives and stat.S_ISREG(metadata.st_mode):
                file_hashes[label] = sha256_file(path)
        except OSError as error:
            hash_findings.append(
                _finding_for_label(
                    path_label=label,
                    line=1,
                    category=FindingCategory.SOURCE_IDENTITY,
                    rule_id="source-hash-unavailable",
                    evidence=type(error).__name__,
                    message="candidate source identity could not be hashed",
                )
            )

    identity_findings.extend(hash_findings)
    all_findings = tuple(
        sorted(
            set(
                (
                    *policy_findings,
                    *secret_findings,
                    *archive_findings,
                    *identity_findings,
                    *supply_findings,
                )
            )
        )
    )
    blocking_count = sum(item.severity is FindingSeverity.ERROR for item in all_findings)
    warning_count = sum(item.severity is FindingSeverity.WARNING for item in all_findings)
    policy_passed = not any(item.severity is FindingSeverity.ERROR for item in policy_findings)
    secret_passed = not any(item.severity is FindingSeverity.ERROR for item in secret_findings)
    archive_passed = not any(item.severity is FindingSeverity.ERROR for item in archive_findings)
    identity_passed = not any(item.severity is FindingSeverity.ERROR for item in identity_findings)
    required_supply_labels = {
        "dependency-lock",
        "pyproject",
        "upstream-lock",
        "third-party-notices",
    }
    required_supply_failed = any(
        finding.rule_id.startswith("required-input")
        and any(label in finding.message for label in required_supply_labels)
        for finding in identity_findings
    )
    if required_supply_failed or any(
        item.severity is FindingSeverity.ERROR for item in supply_findings
    ):
        supply_status = "FAIL"
    elif not_queried_dependencies:
        supply_status = "NOT_EVALUATED"
    else:
        supply_status = "PASS"
    supply_passed = supply_status == "PASS"
    commit, dirty = _git_identity(repository, excluded_paths=output_exclusions)
    overall_passed = all(
        (policy_passed, secret_passed, archive_passed, identity_passed, supply_passed)
    )
    inputs: dict[str, JSONValue] = {
        "archive_count": len(archives),
        "archive_paths": [archive_labels[path] for path in archives],
        "candidate_file_count": len(normalized_candidates),
        "candidate_paths": [_relative_path(repository, path) for path in normalized_candidates],
        "candidate_mode": (
            "git-index-or-conservative-filesystem-fallback"
            if candidate_files is None
            else "caller-supplied"
        ),
        "dependency_lock": _relative_path(repository, dependency_lock),
        "entry_points": [Path(item).as_posix() for item in entry_points],
        "installed_metadata_mode": (
            "local-enrichment" if include_installed_metadata else "lock-only"
        ),
        "manifest": _relative_path(repository, manifest) if manifest is not None else None,
        "manifest_sha256": public.manifest_hash,
        "manifest_binding": {
            "declaration": binding.declaration,
            "expected_sha256": binding.expected_sha256,
            "issue": binding.issue,
        },
        "max_candidate_bytes": max_candidate_bytes,
        "policy_file_count": len(policy_files),
        "policy_excluded_paths": [Path(item).as_posix() for item in excluded_policy_paths],
        "policy_paths": [Path(item).as_posix() for item in policy_paths],
        "public_identifier_count": len(public.identifiers),
        "reachable_policy_file_count": len(reachable_files),
        "receipt_output_excluded": output_label,
        "run_state": _relative_path(repository, run_state) if run_state is not None else None,
    }
    assurance_scope: dict[str, JSONValue] = {
        "kind": "static-only",
        "runtime_socket_denial": "OUT_OF_SCOPE",
        "scanner_network_mode": "offline-by-construction",
    }
    if not semantic_public_manifest_access:
        assert immutable_candidate_snapshots is not None
        validate_live_candidate_snapshots()
        inputs["public_identifier_mode"] = "disabled-package-only"
        inputs["candidate_snapshot_file_count"] = len(immutable_candidate_snapshots)
        inputs["candidate_snapshot_total_bytes"] = candidate_snapshot_total_bytes
        inputs["candidate_snapshot_sha256"] = sha256_bytes(
            canonical_json_bytes(
                {
                    label: sha256_bytes(raw)
                    for label, raw in sorted(immutable_candidate_snapshots.items())
                }
            )
        )
        inputs["reachable_policy_paths"] = [
            _relative_path(repository, path) for path in reachable_files
        ]
        assurance_scope["public_identifier_scan"] = (
            "NOT_EVALUATED_PACKAGE_ONLY_NO_SEMANTIC_MANIFEST_ACCESS"
        )

    body: dict[str, JSONValue] = {
        "dependency_inventory": [item.to_dict() for item in dependencies],
        "finding_counts": {
            "blocking": blocking_count,
            "total": len(all_findings),
            "warnings": warning_count,
        },
        "findings": [item.to_dict() for item in all_findings],
        "generated_at": generated_at,
        "git": {
            "commit": commit,
            "dirty_worktree": dirty,
        },
        "inputs": inputs,
        "license_summary": {
            "dependency_count": len(dependencies),
            "first_party_license_status": next(
                (item.license_status for item in dependencies if item.name == "arc3"),
                "FIRST_PARTY_NOT_PRESENT",
            ),
            "installed_version_mismatch_count": len(version_mismatches),
            "not_evaluated_count": len(not_queried_dependencies),
            "status": supply_status,
            "unknown_or_missing_metadata_count": len(unknown_dependencies),
        },
        "assurance_scope": assurance_scope,
        "checks": {
            "archive_static": {"passed": archive_passed},
            "policy_static": {"passed": policy_passed},
            "secret_scan": {"passed": secret_passed},
            "source_identity": {"passed": identity_passed},
            "supply_chain": {"passed": supply_passed, "status": supply_status},
        },
        "passed": overall_passed,
        "scanner": SCANNER_IDENTITY,
        "schema": INTEGRITY_SCHEMA,
        "source_hashes": file_hashes,
    }
    if not semantic_public_manifest_access:
        reachable_labels = tuple(_relative_path(repository, path) for path in reachable_files)
        reachable_hashes = {
            label: file_hashes[label] for label in reachable_labels if label in file_hashes
        }
        entry_point_labels = tuple(Path(item).as_posix() for item in entry_points)
        reached_entry_points = tuple(
            label for label in entry_point_labels if label in reachable_labels
        )
        policy_labels = frozenset(_relative_path(repository, path) for path in policy_files)
        continuity_complete = (
            bool(reachable_labels)
            and len(reachable_hashes) == len(reachable_labels)
            and reached_entry_points == entry_point_labels
            and all(label in policy_labels for label in reachable_labels)
        )
        body["full_competition_integrity_status"] = "NOT_EVALUATED_PUBLIC_IDENTIFIERS"
        body["integrity_scope"] = "package-only-no-public-identifiers"
        body["package_only_passed"] = overall_passed and continuity_complete
        body["passed"] = False
        body["production_policy_static_coverage"] = {
            "algorithm": "static-first-party-import-closure-v0.1",
            "entry_points": list(entry_point_labels),
            "entry_points_reached": list(reached_entry_points),
            "limitations": (
                "Static first-party import reachability does not prove runtime dynamic-import "
                "or native-extension containment."
            ),
            "policy_scan_covers_reachable_paths": all(
                label in policy_labels for label in reachable_labels
            ),
            "reachable_file_count": len(reachable_labels),
            "reachable_paths_hashed": len(reachable_hashes) == len(reachable_labels),
            "status": "PASS" if continuity_complete else "FAIL",
        }
        body["reachable_policy_source_hashes"] = reachable_hashes
    return IntegrityReceipt(body=body)


__all__ = [
    "DEFAULT_ENTRY_POINTS",
    "DEFAULT_MAX_CANDIDATE_BYTES",
    "DEFAULT_NON_POLICY_PATHS",
    "DEFAULT_POLICY_PATHS",
    "INTEGRITY_SCHEMA",
    "SCANNER_IDENTITY",
    "PublicIdentifierSet",
    "build_integrity_receipt",
    "discover_candidate_files",
    "discover_policy_files",
    "discover_reachable_policy_files",
    "load_public_identifiers",
    "scan_archive_files",
    "scan_policy_files",
    "scan_secret_files",
]
