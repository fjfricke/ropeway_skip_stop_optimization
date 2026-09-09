"""Run one arm of the controlled K20 demand pilot, in a fresh process."""

from __future__ import annotations

import argparse
from dataclasses import asdict, replace
from datetime import datetime, timezone
import json
from pathlib import Path
import resource
import subprocess
import sys
from time import perf_counter

from ropeway_skip_stop_optimization.benchmarking.ddd_fixed_k_arc_flow import (
    DddFixedKArcFlowRunConfig,
    prepare_ddd_fixed_k_arc_flow_run,
    run_ddd_fixed_k_arc_flow,
    write_ddd_fixed_k_arc_flow_result,
)
from ropeway_skip_stop_optimization.benchmarking.ddd_ring_demand_case import (
    DddRingDemandCase,
    RingDemandFamily,
    RingDemandTiming,
)
from ropeway_skip_stop_optimization.optimization.ddd.cp_sat_certificate import (
    atomic_json,
    stable_fingerprint,
)
from ropeway_skip_stop_optimization.optimization.ddd.fixed_k import (
    DddFixedKOperatingMode,
    DddFixedKStartPolicy,
)
from ropeway_skip_stop_optimization.optimization.ddd.primal_evaluation import (
    DddEanPassengerPrimalEvaluator,
)
from ropeway_skip_stop_optimization.benchmarking.ddd_scaling import (
    build_initial_ddd_network_problem,
)

EXAMPLE = "five_station_circle_cw_half_skip_no_wait_headway_b_v0"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--family", choices=list(RingDemandFamily), required=True)
    parser.add_argument("--timing", choices=list(RingDemandTiming), required=True)
    parser.add_argument("--mode", choices=["all_stop", "skip_stop"], required=True)
    parser.add_argument("--cabins", type=int, default=20)
    parser.add_argument("--time-limit", type=float, default=120)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=False)
    started = perf_counter()
    config = DddFixedKArcFlowRunConfig(
        EXAMPLE,
        args.cabins,
        DddFixedKOperatingMode.SKIP_STOP,
        start_policy=DddFixedKStartPolicy.BALANCED_REFERENCE,
        total_time_limit_seconds=args.time_limit,
        cp_seed_time_limit_seconds=0,
        seed_passenger_time_limit_seconds=15,
        solver_threads=8,
    )
    # Both arms derive from precisely the same unrestricted artifact/starts.
    prepared = prepare_ddd_fixed_k_arc_flow_run(config)
    case = DddRingDemandCase(
        RingDemandFamily(args.family), RingDemandTiming(args.timing)
    )
    prepared = case.apply(prepared)
    config = replace(config, operating_mode=DddFixedKOperatingMode(args.mode))
    prepared = replace(
        prepared,
        problem=replace(prepared.problem, operating_mode=config.operating_mode),
    )
    comparison_manifest = prepared.problem.certificate_manifest.copy()
    # The only allowed mathematical difference between pair arms is mode and
    # its route restriction. Preserve the common original structural routes.
    comparison_manifest["operating_mode"] = "paired_all_stop_vs_skip_stop"
    comparison_manifest["trajectory_problem"] = asdict(
        prepared.problem.trajectory_problem
    )
    atomic_json(
        args.output_dir / "config.json",
        {
            "case": asdict(case),
            "solver": asdict(config),
            "started_utc": datetime.now(timezone.utc).isoformat(),
            "git_commit": subprocess.check_output(
                ["git", "rev-parse", "HEAD"], text=True
            ).strip(),
            "comparison_fingerprint": stable_fingerprint(comparison_manifest),
            "demand_groups": [
                asdict(g) for g in prepared.problem.passenger_build.demand_groups
            ],
        }
        | {"solver": json.loads(json.dumps(asdict(config), default=str))},
    )
    with (args.output_dir / "events.jsonl").open("w") as events:

        def progress(event):
            events.write(
                json.dumps(
                    {
                        "runner_elapsed_seconds": perf_counter() - started,
                        **asdict(event),
                    },
                    default=str,
                )
                + "\n"
            )
            events.flush()

        result = run_ddd_fixed_k_arc_flow(
            config, prepared_run=prepared, progress_hook=progress
        )
    write_ddd_fixed_k_arc_flow_result(result, args.output_dir / "result.json")
    metrics = {
        "end_to_end_seconds": perf_counter() - started,
        "runner_seconds_excludes_external_preparation": result.total_seconds,
        "peak_rss_mb": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        / (1024**2 if sys.platform == "darwin" else 1024),
        "comparison_fingerprint": stable_fingerprint(comparison_manifest),
    }
    if result.solve_result.solution is not None:
        problem = prepared.problem
        evaluation = DddEanPassengerPrimalEvaluator(
            scenario=prepared.scenario,
            artifact=problem.artifact,
            objective=problem.objective,
            waiting_policy=problem.resolved_trajectory_problem.waiting_policy,
            passenger_candidate_build=problem.passenger_build,
            time_limit_seconds=15,
            mip_gap=0,
            threads=1,
        ).evaluate(
            build_initial_ddd_network_problem(
                problem.resolved_trajectory_problem.structural_movement_problem
            ),
            result.solve_result.solution,
        )
        metrics.update(
            served=evaluation.served_passenger_count,
            unserved=evaluation.unserved_passenger_count,
            post_ip_objective=evaluation.objective_value,
            post_ip_status=evaluation.solver_status,
            post_ip_seconds=evaluation.total_seconds,
        )
    atomic_json(args.output_dir / "metrics.json", metrics)
    print(json.dumps(metrics, indent=2))


if __name__ == "__main__":
    main()
