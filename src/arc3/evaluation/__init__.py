"""Reproducible evaluation APIs with side-effect-free package import.

The public names remain available lazily.  This is a security boundary for the
sealed holdout gate: importing :mod:`arc3.evaluation.holdout_gate` must not
transitively import any environment adapter or evaluation runner.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any

_EXPORTS = {
    "BASELINES": (".baselines", "BASELINES"),
    "BaselineDescriptor": (".baselines", "BaselineDescriptor"),
    "EvaluationConfig": (".models", "EvaluationConfig"),
    "EvaluationOutcome": (".models", "EvaluationOutcome"),
    "compare_evaluations": (".reports", "compare_evaluations"),
    "evaluate_performance_thresholds": (
        ".thresholds",
        "evaluate_performance_thresholds",
    ),
    "load_performance_thresholds": (".thresholds", "load_performance_thresholds"),
    "load_results": (".reports", "load_results"),
    "render_markdown": (".reports", "render_markdown"),
    "resolve_evaluation": (".artifacts", "resolve_evaluation"),
    "run_evaluation": (".runner", "run_evaluation"),
    "verify_evaluation_artifacts": (".artifacts", "verify_evaluation_artifacts"),
}

__all__ = list(_EXPORTS)


def __getattr__(name: str) -> Any:
    """Load a legacy package export only when a caller actually requests it."""

    try:
        module_name, attribute = _EXPORTS[name]
    except KeyError as error:  # pragma: no cover - normal module protocol
        raise AttributeError(name) from error
    value = getattr(import_module(module_name, __name__), attribute)
    globals()[name] = value
    return value
