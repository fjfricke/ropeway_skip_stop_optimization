from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path
from time import perf_counter

from ropeway_skip_stop_optimization.benchmarking.ddd_fixed_k_arc_flow import (
    DddFixedKArcFlowRunConfig,
    prepare_ddd_fixed_k_arc_flow_run,
)
from ropeway_skip_stop_optimization.optimization.ddd import (
    DddArcFlowProblemPreparer,
    DddArcFlowRelaxationConfig,
    DddArcFlowRelaxationMethod,
    DddArcFlowRelaxationOptimizer,
    DddArcFlowRelaxationProgress,
    DddFixedKOperatingMode,
    DddFixedKStartPolicy,
    DddOuterLoopLpBendersConfig,
    DddOuterLoopLpBendersProgress,
    DddOuterLoopLpBendersSolver,
)
from ropeway_skip_stop_optimization.optimization.ean import EanPassengerObjective


METHODS = ("full_lp", "outer_integer", "outer_root_lp")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compare certified Passenger-bound methods on one exact-K case."
    )
    parser.add_argument("--example", required=True)
    parser.add_argument("--cabins", type=int, required=True)
    parser.add_argument("--method", choices=METHODS, required=True)
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
    parser.add_argument("--time-limit", type=float, default=600.0)
    parser.add_argument("--max-iterations", type=int, default=100)
    parser.add_argument("--threads", type=int)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument(
        "--lp-method",
        choices=tuple(item.value for item in DddArcFlowRelaxationMethod),
        default=DddArcFlowRelaxationMethod.BARRIER_NO_CROSSOVER.value,
    )
    parser.add_argument("--start-layout-time-limit", type=float, default=120.0)
    parser.add_argument("--gurobi-output", action="store_true")
    parser.add_argument("--progress", action="store_true")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("benchmarks/output/ddd_passenger_bounds/result.json"),
    )
    args = parser.parse_args()
    started = perf_counter()
    run_config = DddFixedKArcFlowRunConfig(
        example_id=args.example,
        cabin_count=args.cabins,
        operating_mode=DddFixedKOperatingMode(args.mode),
        objective=EanPassengerObjective(args.objective),
        start_policy=DddFixedKStartPolicy(args.start_policy),
        start_layout_time_limit_seconds=args.start_layout_time_limit,
        total_time_limit_seconds=args.time_limit,
        solver_threads=args.threads,
        seed=args.seed,
        output_flag=args.gurobi_output,
    )
    prepared_run = prepare_ddd_fixed_k_arc_flow_run(run_config)
    prepared = DddArcFlowProblemPreparer().build(prepared_run.problem)
    preparation_seconds = perf_counter() - started

    if args.method == "full_lp":
        result = DddArcFlowRelaxationOptimizer(
            DddArcFlowRelaxationConfig(
                time_limit_seconds=max(
                    0.001,
                    args.time_limit - preparation_seconds,
                ),
                method=DddArcFlowRelaxationMethod(args.lp_method),
                threads=args.threads,
                output_flag=args.gurobi_output,
            )
        ).solve(
            prepared,
            progress_hook=(
                _lp_progress if args.progress else None
            ),
        )
        payload = asdict(result)
        payload["status"] = result.status.value
        payload["method"] = args.method
        payload["lp_method"] = result.method.value
    else:
        result = DddOuterLoopLpBendersSolver(
            DddOuterLoopLpBendersConfig(
                time_limit_seconds=max(
                    0.001,
                    args.time_limit - preparation_seconds,
                ),
                max_iterations=args.max_iterations,
                threads=args.threads,
                seed=args.seed,
                output_flag=args.gurobi_output,
                relax_movement=args.method == "outer_root_lp",
            )
        ).solve(
            prepared,
            seed_trajectories=prepared_run.seed_trajectories,
            progress_hook=(
                _outer_progress if args.progress else None
            ),
        )
        payload = asdict(result)
        payload.pop("best_solution", None)
        payload.pop("cuts", None)
        payload["status"] = result.status.value
        payload["method"] = args.method
    payload.update(
        {
            "example_id": args.example,
            "exact_active_cabin_count": args.cabins,
            "operating_mode": args.mode,
            "start_policy": args.start_policy,
            "objective": args.objective,
            "preparation_seconds": preparation_seconds,
            "wall_clock_total_seconds": perf_counter() - started,
        }
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        f"done method={args.method} status={payload['status']} "
        f"LB={payload.get('certified_lower_bound')} "
        f"UB={payload.get('validated_upper_bound')} "
        f"time={payload['wall_clock_total_seconds']:.1f}s output={args.output}"
    )


def _lp_progress(sample: DddArcFlowRelaxationProgress) -> None:
    primal = "-" if sample.local_primal_objective is None else f"{sample.local_primal_objective:,.1f}"
    dual = "-" if sample.local_dual_objective is None else f"{sample.local_dual_objective:,.1f}"
    iterations = (
        sample.simplex_iterations
        if sample.simplex_iterations is not None
        else sample.barrier_iterations
    )
    print(
        f"LP phase={sample.phase:<12} iter={iterations or 0:9.0f} "
        f"local_primal={primal:>14} local_dual={dual:>14} "
        f"left={sample.remaining_seconds:7.1f}s",
        flush=True,
    )


def _outer_progress(sample: DddOuterLoopLpBendersProgress) -> None:
    upper = (
        "-"
        if sample.validated_upper_bound is None
        else f"{sample.validated_upper_bound:,.1f}"
    )
    print(
        f"BENDERS phase={sample.phase:<12} r={sample.iteration:03d} "
        f"cuts={sample.cut_count:04d} LB={sample.certified_lower_bound:,.1f} "
        f"UB={upper} left={sample.remaining_seconds:7.1f}s",
        flush=True,
    )


if __name__ == "__main__":
    main()
