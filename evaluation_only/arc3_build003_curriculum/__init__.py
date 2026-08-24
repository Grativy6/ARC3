"""Evaluator-only Build 003 progressive mechanic curriculum.

This namespace is deliberately outside ``src/arc3`` and the production wheel.
Production policy code must communicate with it only through the canonical
observation/action broker.
"""

from .models import CurriculumFamily, CurriculumVariant

__all__ = ["CurriculumFamily", "CurriculumVariant"]
