"""Optimize the regular no-wait all-stop phase on a frozen reservoir case."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ropeway_skip_stop_optimization.optimization.ddd.all_stop_phase import (
    AllStopPhaseConfig,
    prepare_all_stop_phase,
    solve_all_stop_phase,
)
from ropeway_skip_stop_optimization.optimization.ddd.cp_sat_certificate import atomic_json
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_cp_sat_certificate import (
    write_reservoir_cp_checkpoint,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_hybrid.domain import load_reference


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--reference-checkpoint", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--dispatch-window-end", type=float, required=True)
    parser.add_argument("--cabins", type=int)
    parser.add_argument("--time-limit", type=float, default=120)
    parser.add_argument("--workers", type=int, default=12)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    domain, reference = load_reference(args.reference_checkpoint)
    cabins = args.cabins or len(reference.trips)
    config = AllStopPhaseConfig(
        cabins=cabins,
        dispatch_window_end_seconds=args.dispatch_window_end,
        objective="unserved",
        time_limit_seconds=args.time_limit,
        workers=args.workers,
        seed=args.seed,
    )
    prepared = prepare_all_stop_phase(domain.problem, config)
    events = []
    result, plan = solve_all_stop_phase(prepared, event_callback=events.append)
    result["events"] = events
    if plan is not None:
        write_reservoir_cp_checkpoint(args.output / "best.json", domain.problem, plan)
    atomic_json(args.output / "result.json", result)
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
