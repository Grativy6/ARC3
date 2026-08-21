"""Emit the pinned Stage 08 retrodiction comparison as JSON."""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import UTC, datetime

from arc3.world_model.benchmark import measure_retrodiction_comparison


def main() -> int:
    started_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    result = asdict(measure_retrodiction_comparison())
    result.update(
        {
            "schema": "arc3.world-model.comparison.v0.1",
            "started_at": started_at,
            "completed_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        }
    )
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
