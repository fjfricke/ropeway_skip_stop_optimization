from __future__ import annotations

import argparse
from pathlib import Path

from ropeway_skip_stop_optimization.benchmarking.ean_bottleneck import (
    DEFAULT_BOTTLENECK_OUTPUT_DIR,
    EanBottleneckDiagnosticConfig,
    EanBottleneckDiagnosticRunner,
)
from ropeway_skip_stop_optimization.benchmarking.plots import (
    EanBottleneckPlotBuilder,
)
from ropeway_skip_stop_optimization.exports.json_codec import to_jsonable
from ropeway_skip_stop_optimization.optimization.ean import (
    ALL_EAN_SELECTION_NAMES,
    EanOptimizationConfig,
    EanPassengerObjective,
    GurobiSolverPolicyPreset,
)


def main() -> None:
    args = _parse_args()
    for example_id in args.examples:
        result, output_path = EanBottleneckDiagnosticRunner(
            EanBottleneckDiagnosticConfig(
                example_id=example_id,
                objective=EanPassengerObjective(args.objective),
                solver_policy=GurobiSolverPolicyPreset(
                    args.ean_solver_policy
                ),
                time_limit_seconds=args.time_limit,
                sample_interval_seconds=args.sample_interval,
                optimization_config=args.ean_optimization_config,
                output_dir=args.output_dir,
                log_to_console=args.progress,
                root_diagnostics=args.root_diagnostics,
            )
        ).run()
        plot_paths = EanBottleneckPlotBuilder(
            to_jsonable(result)
        ).write_all(
            args.output_dir,
            prefix=result.run_id,
        )
        print(f"Wrote bottleneck diagnostic: {output_path}")
        print(f"Wrote {len(plot_paths)} diagnostic plot(s)")
        for case in result.cases:
            if case.metadata is None:
                print(
                    f"  {case.case.value}: unavailable "
                    f"({case.unavailable_reason})"
                )
                continue
            print(
                f"  {case.case.value}: "
                f"status={case.metadata.status} "
                f"runtime={case.metadata.runtime_seconds} "
                f"gap={case.metadata.mip_gap}"
            )
            if case.root_relaxation is not None:
                print(
                    "    root samples="
                    f"{len(case.root_relaxation.samples)}"
                )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run integrated, movement-only, and fixed-movement EAN "
            "bottleneck diagnostics."
        )
    )
    parser.add_argument(
        "--examples",
        nargs="+",
        default=("three_station_v0",),
        help="One or more registered EAN example ids.",
    )
    parser.add_argument(
        "--objective",
        choices=tuple(objective.value for objective in EanPassengerObjective),
        default=EanPassengerObjective.JOURNEY_TIME.value,
    )
    parser.add_argument(
        "--ean-solver-policy",
        choices=tuple(
            preset.value for preset in GurobiSolverPolicyPreset
        ),
        default=GurobiSolverPolicyPreset.QUICK_GOOD_SOLUTION.value,
    )
    parser.add_argument(
        "--time-limit",
        type=float,
        default=300.0,
        help="Solver time limit in seconds for each of the three cases.",
    )
    parser.add_argument("--sample-interval", type=float, default=5.0)
    parser.add_argument(
        "--ean-optimizations",
        default="all",
        help=(
            "'all', 'none', or a comma-separated optimization/formulation "
            "selection: "
            + ", ".join(ALL_EAN_SELECTION_NAMES)
        ),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_BOTTLENECK_OUTPUT_DIR,
    )
    parser.add_argument(
        "--progress",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    parser.add_argument(
        "--root-diagnostics",
        action=argparse.BooleanOptionalAction,
        default=False,
        help=(
            "Record variable-family fractionality at the Gurobi root node."
        ),
    )
    args = parser.parse_args()
    if args.time_limit <= 0:
        parser.error("--time-limit must be positive")
    if args.sample_interval <= 0:
        parser.error("--sample-interval must be positive")
    try:
        args.ean_optimization_config = (
            EanOptimizationConfig.from_selection(
                args.ean_optimizations
            )
        )
    except ValueError as error:
        parser.error(str(error))
    return args


if __name__ == "__main__":
    main()
