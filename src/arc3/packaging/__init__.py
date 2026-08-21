"""Deterministic, first-party offline competition packaging.

The package initializer deliberately imports nothing. Competition payloads
include only the narrow runtime launcher; build-time subprocess and Parquet
tools therefore cannot enter the policy's runtime import graph.
"""

__all__: list[str] = []
