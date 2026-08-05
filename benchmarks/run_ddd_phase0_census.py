from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
from pathlib import Path

from ropeway_skip_stop_optimization.benchmarking.ddd_census import (
    DEFAULT_QUANTA_SECONDS,
    build_example_census,
    fixed_start_example_ids,
    render_markdown,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build the read-only movement census for DDD Phase 0."
    )
    parser.add_argument(
        "--examples",
        nargs="+",
        default=None,
        help="Registered fixed-start examples; default: all fixed-start examples.",
    )
    parser.add_argument(
        "--quantum",
        type=float,
        action="append",
        dest="quanta",
        help="Hypothetical full-grid quantum in seconds; may be repeated.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("benchmarks/output/ddd_phase0_census"),
    )
    args = parser.parse_args()

    example_ids = tuple(args.examples) if args.examples else fixed_start_example_ids()
    quanta = tuple(args.quanta) if args.quanta else DEFAULT_QUANTA_SECONDS
    cases = [
        build_example_census(example_id, quanta_seconds=quanta)
        for example_id in example_ids
    ]
    payload = {
        "schema_version": 1,
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "scope": "movement_only_fixed_starts",
        "cases": cases,
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "census.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (args.output_dir / "census.md").write_text(
        render_markdown(payload),
        encoding="utf-8",
    )
    print(render_markdown(payload), end="")


if __name__ == "__main__":
    main()
