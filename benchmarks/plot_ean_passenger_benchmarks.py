from __future__ import annotations

import argparse
from pathlib import Path

from ropeway_skip_stop_optimization.benchmarking.ean_passenger import DEFAULT_BENCHMARK_OUTPUT_DIR
from ropeway_skip_stop_optimization.benchmarking.plots import (
    PLOT_NAMES,
    PlotBuilder,
    collect_result_paths,
    load_benchmark_result_dicts,
)


def main() -> None:
    args = _parse_args()
    result_paths = collect_result_paths(args.input, args.input_dir)
    if not result_paths:
        raise SystemExit(f"No benchmark result JSON files found in {args.input_dir}")
    results = load_benchmark_result_dicts(result_paths)
    if args.label_field != "label":
        results = tuple({**result, "label": result.get(args.label_field) or result.get("label")} for result in results)
    output_paths = PlotBuilder(results).write_all(args.output_dir, file_format=args.format, include=args.include)
    print(f"Read {len(result_paths)} benchmark result(s)")
    print(f"Wrote {len(output_paths)} plot(s) to: {args.output_dir}")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Plot one or more EAN passenger benchmark JSON results.")
    parser.add_argument("--input", type=Path, action="append", default=[])
    parser.add_argument("--input-dir", type=Path, default=DEFAULT_BENCHMARK_OUTPUT_DIR / "results")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_BENCHMARK_OUTPUT_DIR / "plots")
    parser.add_argument("--format", choices=["svg"], default="svg")
    parser.add_argument("--include", default="all", help=f"'all' or comma-separated names: {', '.join(PLOT_NAMES)}")
    parser.add_argument("--label-field", default="label")
    return parser.parse_args()


if __name__ == "__main__":
    main()
