from __future__ import annotations

import argparse
from dataclasses import asdict, replace
from datetime import UTC, datetime
import json
from pathlib import Path
from time import perf_counter

from ropeway_skip_stop_optimization.benchmarking.ddd_progress import (
    DddTerminalProgress,
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
        description="Run nested fixed-start DDD probes for several cabin counts."
    )
    parser.add_argument("--example", default=DEFAULT_EXAMPLE_ID)
    parser.add_argument("--k-values", default="5,10,15,19")
    parser.add_argument("--max-iterations", type=int, default=100)
    parser.add_argument("--cp-sat-time-limit", type=float, default=5.0)
    parser.add_argument("--cp-sat-workers", type=int, default=8)
    parser.add_argument(
        "--progress",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("benchmarks/output/ddd_fixed_start_k_sweep"),
    )
    args = parser.parse_args()
    k_values = tuple(
        sorted({_positive_int(value) for value in args.k_values.split(",")})
    )

    example = get_example(args.example)
    scenario = example.build_scenario()
    config = example.build_ean_config(scenario)
    builder = example.build_ean_artifact_builder(scenario, config)
    if not isinstance(builder, NetworkEanBuildArtifactBuilder):
        raise ValueError("DDD K sweep requires a network EAN builder")
    if builder.fleet_config.mode is not EanFleetMode.FIXED_STARTS:
        raise ValueError("DDD K sweep requires fixed starts")
    artifact = replace(
        builder,
        headway_pair_builder=SparseHeadwayPairBuilder(),
    ).build(scenario, config)
    base_movement = EanArtifactToDddMovementProblemAdapter().build(artifact)
    ordered_starts = tuple(sorted(base_movement.starts, key=lambda item: item.cabin_id))
    if k_values[-1] > len(ordered_starts):
        raise ValueError(
            f"requested K={k_values[-1]} exceeds {len(ordered_starts)} fixed starts"
        )

    rows = []
    sweep_started = perf_counter()
    for cabin_count in k_values:
        movement = replace(base_movement, starts=ordered_starts[:cabin_count])
        problem = build_initial_ddd_network_problem(movement)
        solver = DddNetworkTimeRefinementSolver(
            max_iterations=args.max_iterations,
            max_new_time_splits_per_iteration=10_000,
            cp_sat_time_limit_seconds=args.cp_sat_time_limit,
            cp_sat_num_workers=args.cp_sat_workers,
        )
        started = perf_counter()
        with DddTerminalProgress(
            enabled=args.progress,
            max_iterations=args.max_iterations,
            description=f"DDD K={cabin_count}",
        ) as progress:
            result = solver.solve(problem, progress_callback=progress.update)
        elapsed_seconds = perf_counter() - started
        final_iteration = result.iterations[-1] if result.iterations else None
        row = {
            "cabin_count": cabin_count,
            "status": result.status.value,
            "global_lower_bound": result.global_lower_bound,
            "global_upper_bound": result.global_upper_bound,
            "absolute_gap": result.absolute_gap,
            "iteration_count": len(result.iterations),
            "elapsed_seconds": elapsed_seconds,
            "schedule_count": len(result.schedules),
            "conflict_cut_count": len(result.conflict_cuts),
            "final_iteration": asdict(final_iteration) if final_iteration else None,
        }
        rows.append(row)
        print(
            f"K={cabin_count} status={result.status.value} "
            f"LB={result.global_lower_bound} UB={result.global_upper_bound} "
            f"rounds={len(result.iterations)} time={elapsed_seconds:.2f}s"
        )

    payload = {
        "schema_version": 1,
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "example_id": args.example,
        "nested_fixed_start_order": [start.cabin_id for start in ordered_starts],
        "k_values": k_values,
        "cp_sat_time_limit_seconds": args.cp_sat_time_limit,
        "cp_sat_num_workers": args.cp_sat_workers,
        "total_elapsed_seconds": perf_counter() - sweep_started,
        "results": rows,
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    output_path = args.output_dir / f"{args.example}.json"
    output_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"output={output_path}")


def _positive_int(value: str) -> int:
    result = int(value.strip())
    if result <= 0:
        raise ValueError("DDD K values must be positive")
    return result


if __name__ == "__main__":
    main()
