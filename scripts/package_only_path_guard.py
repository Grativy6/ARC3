"""Fail-closed filesystem guard for package-only test processes."""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

_PROTECTED_DIRECTORIES = ("artifacts", "docs/evaluation")
_PROTECTED_FILES = (
    "docs/ledger/build-001-run-state.json",
    "docs/ledger/run-state.json",
)
_PATH_EVENT_ARGUMENTS: dict[str, tuple[int, ...]] = {
    "open": (0,),
    "os.chdir": (0,),
    "os.chmod": (0,),
    "os.chown": (0,),
    "os.link": (0, 1),
    "os.listdir": (0,),
    "os.lstat": (0,),
    "os.mkdir": (0,),
    "os.remove": (0,),
    "os.rename": (0, 1),
    "os.rmdir": (0,),
    "os.scandir": (0,),
    "os.stat": (0,),
    "os.symlink": (0, 1),
    "os.truncate": (0,),
    "os.utime": (0,),
    "shutil.copyfile": (0, 1),
    "shutil.copytree": (0, 1),
    "shutil.move": (0, 1),
    "shutil.rmtree": (0,),
}
_PROCESS_EVENTS = frozenset(
    {
        "os.exec",
        "os.fork",
        "os.forkpty",
        "os.posix_spawn",
        "os.posix_spawnp",
        "os.spawn",
        "os.startfile",
        "os.system",
        "subprocess.Popen",
    }
)
_READ_ONLY_OPEN_FLAGS = os.O_APPEND | os.O_CREAT | os.O_EXCL | os.O_RDWR | os.O_TRUNC | os.O_WRONLY
_LINUX_KERNEL_TELEMETRY_PATH = Path("/proc/self/status")


def _canonical(
    path: Path | str | bytes | os.PathLike[str] | os.PathLike[bytes], *, base: Path
) -> str:
    decoded = os.fsdecode(path)
    absolute = decoded if os.path.isabs(decoded) else os.path.join(str(base), decoded)
    return os.path.normcase(os.path.realpath(os.path.abspath(absolute)))


class PackageOnlyPathGuard:
    """Audit-hook state that denies real repository evidence/public surfaces."""

    def __init__(
        self,
        root: Path,
        attempt_log: Path,
        *,
        allowed_roots: Sequence[Path] = (),
        protected_paths: Sequence[Path] = (),
    ) -> None:
        self.root = Path(os.path.realpath(os.path.abspath(root)))
        self.attempts: list[dict[str, str]] = []
        self.kernel_telemetry_read_count = 0
        self._active = True
        self._canonicalizing = False
        self._directories = tuple(
            _canonical(self.root / relative, base=self.root) for relative in _PROTECTED_DIRECTORIES
        )
        self._files = frozenset(
            {
                *(
                    _canonical(self.root / relative, base=self.root)
                    for relative in _PROTECTED_FILES
                ),
                _canonical(attempt_log, base=self.root),
                *(_canonical(candidate, base=self.root) for candidate in protected_paths),
            }
        )
        self._allowed_roots = tuple(
            sorted(
                {_canonical(candidate, base=self.root) for candidate in (self.root, *allowed_roots)}
            )
        )
        self._read_only_kernel_telemetry_files = frozenset(
            {_canonical(_LINUX_KERNEL_TELEMETRY_PATH, base=self.root)}
            if sys.platform.startswith("linux")
            else set()
        )
        metadata_roots = (self.root, *allowed_roots)
        self._allow_root_ancestor_metadata_paths = frozenset(
            _canonical(parent, base=self.root)
            for metadata_root in metadata_roots
            for parent in Path(metadata_root).resolve().parents
        )
        attempt_log.parent.mkdir(parents=True, exist_ok=True)
        self._attempt_log_fd = os.open(
            attempt_log,
            os.O_APPEND | os.O_CREAT | os.O_WRONLY,
            0o600,
        )

    def _protected(self, candidate: str) -> bool:
        if candidate in self._files:
            return True
        return any(
            candidate == directory or candidate.startswith(directory + os.sep)
            for directory in self._directories
        )

    def _allowed(self, candidate: str) -> bool:
        return any(
            candidate == root or candidate.startswith(root + os.sep) for root in self._allowed_roots
        )

    def _allowed_kernel_telemetry_read(
        self,
        event: str,
        args: tuple[Any, ...],
        candidate: str,
    ) -> bool:
        """Allow only an exact read-only Linux RSS surface outside allowed roots."""

        if (
            event != "open"
            or len(args) < 3
            or not isinstance(args[0], (str, bytes, os.PathLike))
            or os.fsdecode(args[0]) != "/proc/self/status"
            or args[1] != "r"
            or candidate not in self._read_only_kernel_telemetry_files
        ):
            return False
        if not isinstance(args[2], int):
            return False
        if args[2] & _READ_ONLY_OPEN_FLAGS:
            return False
        self.kernel_telemetry_read_count += 1
        return True

    def _record(self, event: str, path: str) -> None:
        record = {"event": event, "path": path}
        if os.environ.get("ARC3_PACKAGE_ONLY_DIAGNOSTIC_TEST_CONTEXT") == "1":
            current_test = os.environ.get("PYTEST_CURRENT_TEST")
            if current_test:
                record["test"] = current_test.partition(" (")[0]
        self.attempts.append(record)
        os.write(
            self._attempt_log_fd,
            (json.dumps(record, separators=(",", ":"), sort_keys=True) + "\n").encode("utf-8"),
        )

    def audit(self, event: str, args: tuple[Any, ...]) -> None:
        if not self._active or self._canonicalizing:
            return
        if event in _PROCESS_EVENTS or event.startswith("os.exec"):
            self._record(event, "child-process")
            raise PermissionError(f"package-only test guard denied {event}")
        path_arguments = _PATH_EVENT_ARGUMENTS.get(event)
        if path_arguments is None:
            return
        for index in path_arguments:
            if index >= len(args):
                continue
            raw_path = args[index]
            if not isinstance(raw_path, (str, bytes, os.PathLike)):
                continue
            self._canonicalizing = True
            try:
                candidate = _canonical(raw_path, base=Path.cwd())
            finally:
                self._canonicalizing = False
            if self._allowed_kernel_telemetry_read(event, args, candidate):
                continue
            if event == "os.listdir" and candidate in self._allow_root_ancestor_metadata_paths:
                continue
            if self._protected(candidate):
                try:
                    relative = Path(candidate).relative_to(self.root).as_posix()
                except ValueError:
                    relative = "protected-external-path"
            elif not self._allowed(candidate):
                relative = "protected-external-path"
            else:
                continue
            self._record(event, relative)
            raise PermissionError(f"package-only test guard denied {event} on {relative}")

    def close(self) -> None:
        self._active = False
        os.close(self._attempt_log_fd)


def install(
    root: Path,
    attempt_log: Path,
    *,
    allowed_roots: Sequence[Path] = (),
    protected_paths: Sequence[Path] = (),
) -> PackageOnlyPathGuard:
    """Install one irreversible process-local audit hook and return its state."""

    guard = PackageOnlyPathGuard(
        root,
        attempt_log,
        allowed_roots=allowed_roots,
        protected_paths=protected_paths,
    )
    sys.addaudithook(guard.audit)
    return guard


def install_from_environment() -> PackageOnlyPathGuard | None:
    """Install the inherited guard in Python children when configured."""

    raw_root = os.environ.get("ARC3_PACKAGE_ONLY_ROOT")
    raw_log = os.environ.get("ARC3_PACKAGE_ONLY_GUARD_LOG")
    if not raw_root or not raw_log:
        return None
    raw_allowed = os.environ.get("ARC3_PACKAGE_ONLY_ALLOWED_ROOTS", "[]")
    raw_protected = os.environ.get("ARC3_PACKAGE_ONLY_PROTECTED_PATHS", "[]")
    loaded: object = json.loads(raw_allowed)
    protected: object = json.loads(raw_protected)
    if not isinstance(loaded, list) or not all(isinstance(item, str) for item in loaded):
        raise RuntimeError("ARC3_PACKAGE_ONLY_ALLOWED_ROOTS must be a JSON string list")
    if not isinstance(protected, list) or not all(isinstance(item, str) for item in protected):
        raise RuntimeError("ARC3_PACKAGE_ONLY_PROTECTED_PATHS must be a JSON string list")
    return install(
        Path(raw_root),
        Path(raw_log),
        allowed_roots=tuple(Path(item) for item in loaded),
        protected_paths=tuple(Path(item) for item in protected),
    )


__all__ = ["PackageOnlyPathGuard", "install", "install_from_environment"]
