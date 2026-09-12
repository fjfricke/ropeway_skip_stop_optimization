"""Run the gated reservoir arrival-bound pilot on a checked checkpoint."""

import argparse
import json
from pathlib import Path

from ropeway_skip_stop_optimization.benchmarking.ddd_reservoir_hybrid import (
    DddReservoirHybridRunConfig,
    run_ddd_reservoir_hybrid,
)


def main():
    p = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    p.add_argument("--resume-checkpoint", required=True, type=Path)
    p.add_argument("--output-dir", required=True, type=Path)
    p.add_argument(
        "--phase",
        choices=("replay", "bound", "repair", "refine", "hybrid"),
        default="bound",
    )
    p.add_argument(
        "--lifecycle", choices=("single_use", "reusable"), default="single_use"
    )
    p.add_argument(
        "--bound-profile",
        choices=("arrival_only", "movement_capacity", "resource_windows"),
        default="resource_windows",
    )
    p.add_argument("--initial-bound-step-seconds", type=float, default=60)
    p.add_argument("--time-limit", type=float, default=300)
    p.add_argument("--num-workers", type=int, default=12)
    p.add_argument(
        "--max-variables", type=int, default=50000, help="0 disables the size cap"
    )
    p.add_argument(
        "--max-rows", type=int, default=250000, help="0 disables the size cap"
    )
    p.add_argument("--build-only", action="store_true")
    p.add_argument("--lp-method", type=int, choices=(-1, 0, 1, 2), default=-1)
    p.add_argument(
        "--open-deployments",
        type=lambda s: tuple(int(v) for v in s.split(",") if v),
        default=(),
    )
    p.add_argument("--new-slots", type=int, default=0)
    p.add_argument("--no-repair-presolve", action="store_true")
    p.add_argument("--initial-bound-result", type=Path)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--refinement-rounds", type=int, default=5)
    p.add_argument("--trim-empty-tails", action="store_true")
    p.add_argument(
        "--journey-encoding",
        choices=("legacy", "ride_bounds", "time_moments"),
        default="legacy",
    )
    a = p.parse_args()
    c = DddReservoirHybridRunConfig(
        a.resume_checkpoint,
        a.output_dir,
        a.phase,
        a.lifecycle,
        a.bound_profile,
        a.initial_bound_step_seconds,
        a.time_limit,
        a.num_workers,
        None if a.max_variables == 0 else a.max_variables,
        None if a.max_rows == 0 else a.max_rows,
        a.build_only,
        a.journey_encoding,
        a.lp_method,
        a.open_deployments,
        a.new_slots,
        not a.no_repair_presolve,
        a.initial_bound_result,
        a.seed,
        a.refinement_rounds,
        a.trim_empty_tails,
    )
    print(json.dumps(run_ddd_reservoir_hybrid(c), indent=2))


if __name__ == "__main__":
    main()
