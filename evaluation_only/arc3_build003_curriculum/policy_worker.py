"""Deliberately weak observation-only worker used to verify process isolation."""

from __future__ import annotations

import importlib
import importlib.abc
import sys
from importlib.machinery import ModuleSpec
from multiprocessing.connection import Connection
from types import ModuleType

from .broker import (
    _ERROR_SCHEMA,
    _READY_SCHEMA,
    action_to_bytes,
    canonical_bytes,
    observation_from_bytes,
)

_PRIVILEGED_MODULES = ("engine", "generator", "oracle")


class _PrivilegeDenyFinder(importlib.abc.MetaPathFinder):
    """Fail closed if observation-only worker code reaches evaluator mechanics."""

    def __init__(self, package: str) -> None:
        self._denied = tuple(f"{package}.{leaf}" for leaf in _PRIVILEGED_MODULES)

    def find_spec(
        self,
        fullname: str,
        path: object = None,
        target: ModuleType | None = None,
    ) -> ModuleSpec | None:
        del path, target
        if any(fullname == denied or fullname.startswith(f"{denied}.") for denied in self._denied):
            raise ModuleNotFoundError(
                f"policy worker is not authorized to import privileged module {fullname}"
            )
        return None


def worker_main(connection: Connection, variant: str = "BLA_CLEF_FULL") -> None:
    """Receive canonical observations and return canonical actions until closed."""

    prefix = __package__ or "arc3_build003_curriculum"
    sys.meta_path.insert(0, _PrivilegeDenyFinder(prefix))
    blocked_imports: list[str] = []
    for leaf in _PRIVILEGED_MODULES:
        name = f"{prefix}.{leaf}"
        try:
            importlib.import_module(name)
        except ModuleNotFoundError:
            blocked_imports.append(name)
        else:
            raise RuntimeError(f"privileged worker import unexpectedly succeeded: {name}")
    from .variant_policy import ObservationOnlyVariantPolicy

    policy = ObservationOnlyVariantPolicy(variant)
    modules = sorted(name for name in sys.modules if name.startswith(prefix))
    connection.send_bytes(
        canonical_bytes(
            {
                "blocked_imports": blocked_imports,
                "modules": modules,
                "schema": _READY_SCHEMA,
                "variant": variant,
            }
        )
    )
    try:
        while True:
            payload = connection.recv_bytes()
            if payload == canonical_bytes({"command": "close"}):
                return
            try:
                envelope = __import__("json").loads(payload.decode("utf-8"))
            except (UnicodeDecodeError, ValueError):
                envelope = None
            if isinstance(envelope, dict) and envelope.get("command") == "finalize":
                raw_observation = envelope.get("observation")
                if not isinstance(raw_observation, dict):
                    raise ValueError("finalize requires an observation object")
                observation = observation_from_bytes(canonical_bytes(raw_observation))
                connection.send_bytes(canonical_bytes(policy.finalize(observation)))
                continue
            observation = observation_from_bytes(payload)
            connection.send_bytes(action_to_bytes(policy.choose_action(observation)))
    except EOFError:
        return
    except Exception as error:
        message = f"{type(error).__name__}: {error}"
        try:
            connection.send_bytes(canonical_bytes({"message": message, "schema": _ERROR_SCHEMA}))
        except (BrokenPipeError, EOFError, OSError):
            return
    finally:
        connection.close()


__all__ = ["worker_main"]
