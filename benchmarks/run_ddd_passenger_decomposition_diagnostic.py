from __future__ import annotations

import argparse
from pathlib import Path

from ropeway_skip_stop_optimization.benchmarking.ddd_fixed_k_arc_flow import (
    DddFixedKArcFlowRunConfig,
)
from ropeway_skip_stop_optimization.benchmarking.ddd_passenger_decomposition import (
    DddPassengerDecompositionDiagnosticConfig,
    DddPassengerDecompositionSample,
    run_ddd_passenger_decomposition_diagnostic,
    write_ddd_passenger_decomposition_diagnostic,
)
from ropeway_skip_stop_optimization.optimization.ddd import (
    DddFixedKMovementArcFlowProgress,
    DddFixedKOperatingMode,
    DddFixedKStartPolicy,
)
from ropeway_skip_stop_optimization.optimization.ean import EanPassengerObjective


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Generate complete DDD Movement plans and compare fixed-plan "
            "Passenger LP and IP recourse."
        )
    )
    parser.add_argument("--example", required=True)
    parser.add_argument("--cabins", required=True, type=int)
    parser.add_argument(
        "--mode",
        choices=tuple(item.value for item in DddFixedKOperatingMode),
        default=DddFixedKOperatingMode.SKIP_STOP.value,
    )
    parser.add_argument(
        "--start-policy",
        choices=tuple(item.value for item in DddFixedKStartPolicy),
        default=DddFixedKStartPolicy.BALANCED_REFERENCE.value,
    )
    parser.add_argument(
        "--objective",
        choices=tuple(item.value for item in EanPassengerObjective),
        default=EanPassengerObjective.JOURNEY_TIME.value,
    )
    parser.add_argument("--movement-time-limit", type=float, default=120.0)
    parser.add_argument("--passenger-time-limit", type=float, default=60.0)
    parser.add_argument("--start-layout-time-limit", type=float, default=120.0)
    parser.add_argument("--threads", type=int)
    parser.add_argument("--seeds", default="0,1,2,3,4")
    parser.add_argument("--gurobi-output", action="store_true")
    parser.add_argument(
        "--diversify-movements",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    parser.add_argument("--progress", action="store_true")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(
            "benchmarks/output/ddd_passenger_decomposition/diagnostic.json"
        ),
    )
    args = parser.parse_args()
    seeds = tuple(int(value.strip()) for value in args.seeds.split(",") if value.strip())
    run_config = DddFixedKArcFlowRunConfig(
        example_id=args.example,
        cabin_count=args.cabins,
        operating_mode=DddFixedKOperatingMode(args.mode),
        objective=EanPassengerObjective(args.objective),
        start_policy=DddFixedKStartPolicy(args.start_policy),
        start_layout_time_limit_seconds=args.start_layout_time_limit,
        total_time_limit_seconds=(
            args.movement_time_limit + args.passenger_time_limit * 2
        ),
        solver_threads=args.threads,
        output_flag=args.gurobi_output,
    )
    config = DddPassengerDecompositionDiagnosticConfig(
        run=run_config,
        movement_time_limit_seconds=args.movement_time_limit,
        passenger_time_limit_seconds=args.passenger_time_limit,
        solver_seeds=seeds,
        diversify_movements=args.diversify_movements,
    )
    last_width = 0

    def progress(seed: int, sample: DddFixedKMovementArcFlowProgress) -> None:
        nonlocal last_width
        if not args.progress:
            return
        line = (
            f" seed={seed:03d} phase={sample.phase:<18.18} "
            f"nodes={sample.node_count:9.0f} sol={sample.solution_count:03d} "
            f"x={sample.movement_variable_count:,} "
            f"rows={sample.movement_constraint_count:,}/"
            f"{sample.resource_row_count:,} "
            f"left={sample.remaining_seconds:7.1f}s"
        )
        print(f"\r{line}{' ' * max(0, last_width - len(line))}", end="", flush=True)
        last_width = len(line)

    def completed(sample: DddPassengerDecompositionSample) -> None:
        nonlocal last_width
        if args.progress:
            print()
            last_width = 0
        comparison = sample.passenger
        if comparison is None:
            print(
                f"seed={sample.solver_seed} movement={sample.movement_status} "
                f"duplicate={sample.duplicate_movement}"
            )
            return
        print(
            f"seed={sample.solver_seed} movement={sample.movement_status} "
            f"LP={_number(comparison.lp.objective_value)} "
            f"IP={_number(comparison.integer.objective_value)} "
            f"gap={_percent(comparison.relative_gap)} "
            f"fractional_rides={comparison.lp.fractional_ride_count} "
            f"exact={comparison.gap_is_exact}"
        )

    result = run_ddd_passenger_decomposition_diagnostic(
        config,
        progress_hook=progress,
        sample_hook=completed,
    )
    write_ddd_passenger_decomposition_diagnostic(result, args.output)
    print(
        f"done samples={len(result.samples)} unique={result.unique_movement_count} "
        f"time={result.total_seconds:.1f}s output={args.output}"
    )


def _number(value: float | None) -> str:
    return "-" if value is None else f"{value:,.3f}"


def _percent(value: float | None) -> str:
    return "-" if value is None else f"{100 * value:.4f}%"


if __name__ == "__main__":
    main()
