"""Transitive POSIX process-event probe used only by boundary regressions."""

from __future__ import annotations

import os


def attempt_clone(operation: str) -> None:
    """Invoke a named POSIX clone primitive and safely reap if denial regresses."""

    result = getattr(os, operation)()
    if operation == "fork":
        process_id = result
        if process_id == 0:
            os._exit(97)
        os.waitpid(process_id, 0)
    else:
        process_id, descriptor = result
        if process_id == 0:
            os._exit(97)
        os.close(descriptor)
        os.waitpid(process_id, 0)
    raise AssertionError(f"package-only guard permitted POSIX clone event os.{operation}")
