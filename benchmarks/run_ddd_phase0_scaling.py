from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
from pathlib import Path

from ropeway_skip_stop_optimization.benchmarking.ddd_scaling import (
    DEFAULT_SCALING_EXAMPLE_IDS,
    build_ddd_scaling_case,
    evaluate_g9_structural_gate,
    render_scaling_markdown,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Measure delayed-prefix scaling against support and eager EAN references."
    )
    parser.add_argument(
        "--examples",
        nargs="+",
        default=DEFAULT_SCALING_EXAMPLE_IDS,
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("benchmarks/output/ddd_phase0_scaling"),
    )
    args = parser.parse_args()

    cases = [build_ddd_scaling_case(example_id) for example_id in args.examples]
    payload = {
        "schema_version": 1,
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "scope": "movement_only_fixed_starts_no_wait",
        "local_prefix_cabin_count": 2,
        "local_prefix_max_visit_index": 2,
        "cases": cases,
        "gate_g9": evaluate_g9_structural_gate(cases),
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "scaling.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    markdown = render_scaling_markdown(payload)
    (args.output_dir / "scaling.md").write_text(markdown, encoding="utf-8")
    print(markdown, end="")


if __name__ == "__main__":
    main()
