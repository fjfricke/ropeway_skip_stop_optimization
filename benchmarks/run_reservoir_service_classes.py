"""Run the experimental exact-service-class reservoir line pipeline."""

import argparse
import json
from pathlib import Path
import subprocess
from time import perf_counter

from ropeway_skip_stop_optimization.optimization.ddd.cp_sat_certificate import atomic_json
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_boundary import (
    add_boundary_arguments,
    apply_boundary_arguments,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_cp_sat_certificate import (
    write_reservoir_cp_checkpoint,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_hybrid.domain import (
    load_reference,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_lines import (
    ReservoirLineCatalogProfile,
    ReservoirLineConfig,
    ReservoirLineFormulation,
    ReservoirLineMode,
    ReservoirLineVariant,
    ReservoirPatternMasterConfig,
    ReservoirServiceClassPipelineConfig,
    solve_service_class_pipeline,
)


def _source_identity() -> dict:
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], check=True, capture_output=True, text=True
    ).stdout.strip()
    dirty = bool(
        subprocess.run(
            ["git", "status", "--porcelain"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
    )
    return {"git_head": head, "working_tree_dirty": dirty}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--reference-checkpoint", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--dispatch-window-end", required=True, type=float)
    parser.add_argument("--catalog", choices=list(ReservoirLineCatalogProfile), default="small")
    parser.add_argument("--formulation", choices=list(ReservoirLineFormulation), default="shared_rounds")
    parser.add_argument("--variant", choices=list(ReservoirLineVariant), default="intervals")
    parser.add_argument("--max-cabins", type=int)
    parser.add_argument("--master-time-limit", type=float, default=60)
    parser.add_argument("--timing-time-limit", type=float, default=90)
    parser.add_argument("--waiting-time-limit", type=float, default=20)
    parser.add_argument("--candidates", type=int, default=4)
    parser.add_argument("--maximum-ride-variables", type=int, default=500_000)
    parser.add_argument("--workers", type=int, default=12)
    parser.add_argument("--memory-limit-gib", type=float, default=32)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--build-only", action="store_true")
    parser.add_argument("--log-search-progress", action="store_true")
    add_boundary_arguments(parser)
    args = parser.parse_args()

    started = perf_counter()
    args.output.mkdir(parents=True, exist_ok=False)
    domain, reference_plan = load_reference(args.reference_checkpoint)

    problem = apply_boundary_arguments(domain.problem, args)
    line = ReservoirLineConfig(
        dispatch_window_end_seconds=args.dispatch_window_end,
        variant=ReservoirLineVariant(args.variant),
        formulation=ReservoirLineFormulation(args.formulation),
        mode=ReservoirLineMode.FEASIBILITY,
        catalog_profile=ReservoirLineCatalogProfile(args.catalog),
        maximum_cabins=args.max_cabins,
        workers=args.workers,
        memory_limit_gib=args.memory_limit_gib,
        seed=args.seed,
        log_search_progress=args.log_search_progress,
    )
    config = ReservoirServiceClassPipelineConfig(
        line,
        ReservoirPatternMasterConfig(
            time_limit_seconds=args.master_time_limit,
            threads=args.workers,
            memory_limit_gib=args.memory_limit_gib,
            candidate_limit=args.candidates,
            seed=args.seed,
            output_flag=args.log_search_progress,
            maximum_ride_variables=args.maximum_ride_variables,
        ),
        args.timing_time_limit,
        args.waiting_time_limit,
    )
    progress = args.output / "events.jsonl"

    def event_callback(event):
        with progress.open("a") as stream:
            stream.write(json.dumps(event, sort_keys=True) + "\n")

    result, plan = solve_service_class_pipeline(
        problem,
        config,
        build_only=args.build_only,
        event_callback=event_callback,
        reference_plan=reference_plan,
    )
    result["runner_total_wall_seconds"] = perf_counter() - started
    result["source_identity"] = _source_identity()
    if plan is not None:
        write_reservoir_cp_checkpoint(args.output / "best.json", problem, plan)
    atomic_json(args.output / "result.json", result)
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
