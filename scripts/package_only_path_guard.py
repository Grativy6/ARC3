"""Fail-closed filesystem guard for package-only test processes."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

_PROTECTED_DIRECTORIES = ("artifacts", "docs/evaluation")
_PROTECTED_FILES = (
    "docs/ledger/build-001-run-state.json",
    "docs/ledger/run-state.json",
)
_PATH_EVENTS = frozenset(
    {
        "open",
        "os.chdir",
        "os.listdir",
        "os.lstat",
        "os.scandir",
        "os.stat",
    }
)


def _normalized(
    path: Path | str | bytes | os.PathLike[str] | os.PathLike[bytes], *, base: Path
) -> str:
    decoded = os.fsdecode(path)
    absolute = decoded if os.path.isabs(decoded) else os.path.join(str(base), decoded)
    return os.path.normcase(os.path.abspath(absolute))


class PackageOnlyPathGuard:
    """Audit-hook state that denies real repository evidence/public surfaces."""

    def __init__(self, root: Path, attempt_log: Path) -> None:
        self.root = Path(os.path.abspath(root))
        self.attempts: list[dict[str, str]] = []
        self._directories = tuple(
            _normalized(self.root / relative, base=self.root) for relative in _PROTECTED_DIRECTORIES
        )
        self._files = frozenset(
            _normalized(self.root / relative, base=self.root) for relative in _PROTECTED_FILES
        )
        attempt_log.parent.mkdir(parents=True, exist_ok=True)
        self._attempt_log_fd = os.open(
            attempt_log,
            os.O_APPEND | os.O_CREAT | os.O_WRONLY,
            0o600,
        )

    def _denied(self, candidate: str) -> bool:
        if candidate in self._files:
            return True
        return any(
            candidate == directory or candidate.startswith(directory + os.sep)
            for directory in self._directories
        )

    def audit(self, event: str, args: tuple[Any, ...]) -> None:
        if event not in _PATH_EVENTS or not args:
            return
        raw_path = args[0]
        if not isinstance(raw_path, (str, bytes, os.PathLike)):
            return
        candidate = _normalized(raw_path, base=Path.cwd())
        if not self._denied(candidate):
            return
        try:
            relative = Path(candidate).relative_to(self.root).as_posix()
        except ValueError:
            relative = "protected-external-path"
        record = {"event": event, "path": relative}
        self.attempts.append(record)
        os.write(
            self._attempt_log_fd,
            (json.dumps(record, separators=(",", ":"), sort_keys=True) + "\n").encode("utf-8"),
        )
        raise PermissionError(f"package-only test guard denied {event} on {relative}")

    def close(self) -> None:
        os.close(self._attempt_log_fd)


def install(root: Path, attempt_log: Path) -> PackageOnlyPathGuard:
    """Install one irreversible process-local audit hook and return its state."""

    guard = PackageOnlyPathGuard(root, attempt_log)
    sys.addaudithook(guard.audit)
    return guard


def install_from_environment() -> PackageOnlyPathGuard | None:
    """Install the inherited guard in Python children when configured."""

    raw_root = os.environ.get("ARC3_PACKAGE_ONLY_ROOT")
    raw_log = os.environ.get("ARC3_PACKAGE_ONLY_GUARD_LOG")
    if not raw_root or not raw_log:
        return None
    return install(Path(raw_root), Path(raw_log))


__all__ = ["PackageOnlyPathGuard", "install", "install_from_environment"]
