"""Run the reproducible Stage 04 maximum-frame perception benchmark."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from datetime import UTC, datetime

from arc3.perception.benchmark import benchmark_maximum_frame


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iterations", type=int, default=10)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    started_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    result = asdict(benchmark_maximum_frame(iterations=args.iterations))
    result.update(
        {
            "schema": "arc3.perception.benchmark.v0.1",
            "label": "synthetic",
            "started_at": started_at,
            "completed_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        }
    )
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
