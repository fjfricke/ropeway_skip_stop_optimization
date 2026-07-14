from __future__ import annotations

import argparse
from pathlib import Path

from ropeway_skip_stop_optimization.benchmarking.ean_passenger import (
    DEFAULT_BENCHMARK_OUTPUT_DIR,
    BenchmarkRunConfig,
    run_ean_passenger_benchmark,
)
from ropeway_skip_stop_optimization.benchmarking.plots import PlotBuilder, load_benchmark_result_dicts
from ropeway_skip_stop_optimization.exports.runner import DEFAULT_OUTPUT_ROOT
from ropeway_skip_stop_optimization.optimization.ean import (
    ALL_EAN_SELECTION_NAMES,
    EanOptimizationConfig,
    GurobiSolverPolicyPreset,
)


def main() -> None:
    args = _parse_args()
    output_dir = args.output_dir
    result_dir = args.result_dir or output_dir / "results"
    plot_dir = args.plot_dir or output_dir / "plots"
    checkpoint_dir = args.checkpoint_dir

    result, result_path = run_ean_passenger_benchmark(
        BenchmarkRunConfig(
            example_id=args.example,
            artifact_set_id=args.artifact_set,
            ean_solver_policy=GurobiSolverPolicyPreset(args.ean_solver_policy),
            time_limit_seconds=args.time_limit,
            sample_interval_seconds=args.sample_interval,
            ean_optimization_config=args.ean_optimization_config,
            label=args.label,
            output_dir=output_dir,
            result_dir=result_dir,
            plot_dir=plot_dir,
            checkpoint_dir=checkpoint_dir,
            resume_checkpoint=args.resume_checkpoint,
            resume_latest_checkpoint=args.resume_latest_checkpoint,
            export_frontend_artifacts=args.export_frontend_artifacts,
            frontend_output_root=args.frontend_output_root,
            clean_frontend_output=args.clean_frontend_output,
            progress=args.progress,
        )
    )

    plot_paths = PlotBuilder(load_benchmark_result_dicts((result_path,))).write_all(plot_dir)
    print(f"Wrote benchmark result: {result_path}")
    print(f"Run id: {result.run_id}")
    print(f"Wrote {len(plot_paths)} plot(s) to: {plot_dir}")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run an EAN passenger benchmark and write JSON/SVG outputs.")
    parser.add_argument("--example", default="three_station_v0")
    parser.add_argument("--artifact-set", default="ean_passenger_journey_time")
    parser.add_argument(
        "--ean-solver-policy",
        choices=[preset.value for preset in GurobiSolverPolicyPreset],
        default=GurobiSolverPolicyPreset.QUICK_GOOD_SOLUTION.value,
    )
    parser.add_argument("--time-limit", type=float, default=None)
    parser.add_argument("--sample-interval", type=float, default=5.0)
    parser.add_argument(
        "--ean-optimizations",
        default="all",
        help=(
            "'all' for the current default set, 'none', or comma-separated "
            "optimization and formulation selections; choose at most one "
            "horizon_* and one time_bounds_* value: "
            + ", ".join(ALL_EAN_SELECTION_NAMES)
        ),
    )
    parser.add_argument("--label", default=None)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_BENCHMARK_OUTPUT_DIR)
    parser.add_argument("--result-dir", type=Path, default=None)
    parser.add_argument("--plot-dir", type=Path, default=None)
    parser.add_argument("--checkpoint-dir", type=Path, default=None)
    parser.add_argument("--resume-checkpoint", type=Path, default=None)
    parser.add_argument("--resume-latest-checkpoint", action="store_true")
    parser.add_argument("--export-frontend-artifacts", action="store_true")
    parser.add_argument("--frontend-output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--clean-frontend-output", action="store_true")
    parser.add_argument("--progress", action=argparse.BooleanOptionalAction, default=True)
    args = parser.parse_args()
    if args.sample_interval <= 0:
        parser.error("--sample-interval must be positive")
    if args.resume_checkpoint is not None and args.resume_latest_checkpoint:
        parser.error("Use either --resume-checkpoint or --resume-latest-checkpoint, not both")
    try:
        args.ean_optimization_config = EanOptimizationConfig.from_selection(args.ean_optimizations)
    except ValueError as error:
        parser.error(str(error))
    return args


if __name__ == "__main__":
    main()
