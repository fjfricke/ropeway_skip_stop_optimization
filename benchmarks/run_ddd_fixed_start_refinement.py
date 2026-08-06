from __future__ import annotations

import argparse
from dataclasses import asdict, replace
from datetime import UTC, datetime
import json
from pathlib import Path
from time import perf_counter

from ropeway_skip_stop_optimization.benchmarking.ddd_progress import (
    DddTerminalProgress,
    format_ddd_iteration_progress,
)
from ropeway_skip_stop_optimization.benchmarking.ddd_scaling import (
    build_initial_ddd_network_problem,
)
from ropeway_skip_stop_optimization.examples.registry import get_example
from ropeway_skip_stop_optimization.optimization.ddd import (
    DddNetworkTimeRefinementSolver,
    EanArtifactToDddMovementProblemAdapter,
)
from ropeway_skip_stop_optimization.optimization.ean import (
    EanFleetMode,
    NetworkEanBuildArtifactBuilder,
    SparseHeadwayPairBuilder,
)


DEFAULT_EXAMPLE_ID = "five_station_circle_cw_half_skip_no_wait_v0"


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Run conflict-driven DDD refinement on a physical fixed-start case."
        )
    )
    parser.add_argument("--example", default=DEFAULT_EXAMPLE_ID)
    parser.add_argument("--max-iterations", type=int, default=100)
    parser.add_argument("--max-new-cuts", type=int, default=10_000)
    parser.add_argument("--max-new-time-splits", type=int, default=10_000)
    parser.add_argument(
        "--progress",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    parser.add_argument("--gurobi-log", action="store_true")
    parser.add_argument(
        "--reuse-network-fragments",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    parser.add_argument(
        "--projected-warm-start",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("benchmarks/output/ddd_fixed_start_refinement"),
    )
    args = parser.parse_args()
    if args.progress and args.gurobi_log:
        parser.error("--progress and --gurobi-log cannot be combined")

    setup_started = perf_counter()
    example = get_example(args.example)
    scenario = example.build_scenario()
    config = example.build_ean_config(scenario)
    builder = example.build_ean_artifact_builder(scenario, config)
    if not isinstance(builder, NetworkEanBuildArtifactBuilder):
        raise ValueError("DDD refinement requires a network EAN builder")
    if builder.fleet_config.mode is not EanFleetMode.FIXED_STARTS:
        raise ValueError("DDD refinement requires fixed cabin starts")
    artifact = replace(
        builder,
        headway_pair_builder=SparseHeadwayPairBuilder(),
    ).build(scenario, config)
    movement = EanArtifactToDddMovementProblemAdapter().build(artifact)
    problem = build_initial_ddd_network_problem(movement)
    setup_seconds = perf_counter() - setup_started

    solver = DddNetworkTimeRefinementSolver(
        max_iterations=args.max_iterations,
        output_flag=args.gurobi_log,
        max_new_cuts_per_iteration=args.max_new_cuts,
        max_new_time_splits_per_iteration=args.max_new_time_splits,
        reuse_network_fragments=args.reuse_network_fragments,
        use_projected_warm_start=args.projected_warm_start,
    )
    solve_started = perf_counter()
    with DddTerminalProgress(
        enabled=args.progress,
        max_iterations=args.max_iterations,
        description=f"DDD K={len(movement.starts)}",
    ) as progress:
        result = solver.solve(problem, progress_callback=progress.update)
    solve_seconds = perf_counter() - solve_started

    payload = {
        "schema_version": 1,
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "example_id": args.example,
        "cabin_count": len(movement.starts),
        "operational_end_seconds": movement.operational_end_seconds,
        "max_iterations": args.max_iterations,
        "max_new_cuts_per_iteration": args.max_new_cuts,
        "max_new_time_splits_per_iteration": args.max_new_time_splits,
        "reuse_network_fragments": args.reuse_network_fragments,
        "projected_warm_start": args.projected_warm_start,
        "setup_seconds": setup_seconds,
        "solve_seconds": solve_seconds,
        "status": result.status.value,
        "global_lower_bound": result.global_lower_bound,
        "global_upper_bound": result.global_upper_bound,
        "absolute_gap": result.absolute_gap,
        "iteration_count": len(result.iterations),
        "conflict_cut_count": len(result.conflict_cuts),
        "final_discretization_fingerprint": (
            result.final_discretization.fingerprint
        ),
        "schedule_count": len(result.schedules),
        "iterations": [asdict(iteration) for iteration in result.iterations],
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    output_path = args.output_dir / f"{args.example}.json"
    output_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    print(
        " ".join(
            (
                f"status={result.status.value}",
                f"rounds={len(result.iterations)}",
                f"LB={result.global_lower_bound}",
                f"UB={result.global_upper_bound}",
                f"cuts={len(result.conflict_cuts)}",
                f"setup={setup_seconds:.2f}s",
                f"solve={solve_seconds:.2f}s",
                f"output={output_path}",
            )
        )
    )
    if result.iterations:
        print(format_ddd_iteration_progress(result.iterations[-1]))


if __name__ == "__main__":
    main()
