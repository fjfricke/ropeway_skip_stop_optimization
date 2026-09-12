"""Run the symbolic temporal reservoir DP on a frozen reservoir checkpoint."""

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from ropeway_skip_stop_optimization.optimization.ddd.cp_sat_certificate import (
    atomic_json,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_cp_sat_certificate import (
    validate_reservoir_cp_plan,
    write_reservoir_cp_checkpoint,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_dp import (
    ReservoirDpConfig,
    ReservoirDpOptimizer,
    ReservoirDpSearchMode,
    ReservoirDpVariant,
    prepare_reservoir_dp,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_hybrid.domain import (
    load_reference,
)


def main():
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--reference-checkpoint", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument(
        "--variant", choices=list(ReservoirDpVariant), default="symbolic_visits"
    )
    parser.add_argument(
        "--search-mode", choices=list(ReservoirDpSearchMode), default="primal"
    )
    parser.add_argument("--objective", choices=("unserved",), default="unserved")
    parser.add_argument(
        "--operating-mode", choices=("skip_stop",), default="skip_stop"
    )
    parser.add_argument(
        "--pattern-scope", choices=("whole_trip",), default="whole_trip"
    )
    parser.add_argument("--time-limit", type=float, default=60)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--memory-limit-gib", type=float, default=24)
    parser.add_argument("--initial-beam-width", type=int, default=64)
    parser.add_argument("--max-beam-width", type=int, default=1024)
    parser.add_argument(
        "--keep-all-layers", action=argparse.BooleanOptionalAction, default=False
    )
    parser.add_argument("--build-only", action="store_true")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    domain, reference_plan = load_reference(args.reference_checkpoint)
    reference = validate_reservoir_cp_plan(domain.problem, reference_plan)
    prepared = prepare_reservoir_dp(domain.problem)
    atomic_json(args.output / "prepared.json", prepared.payload)
    atomic_json(args.output / "reference_metrics.json", asdict(reference))
    if args.build_only:
        result = {
            "status": "built",
            "variant": args.variant,
            "model_fingerprint": prepared.fingerprint,
            "reference_metrics": asdict(reference),
        }
    else:
        result, plan = ReservoirDpOptimizer(
            ReservoirDpConfig(
                variant=ReservoirDpVariant(args.variant),
                search_mode=ReservoirDpSearchMode(args.search_mode),
                time_limit_seconds=args.time_limit,
                workers=args.workers,
                memory_limit_gib=args.memory_limit_gib,
                initial_beam_width=args.initial_beam_width,
                max_beam_width=args.max_beam_width,
                keep_all_layers=args.keep_all_layers,
            )
        ).solve(domain.problem)
        if plan is not None:
            write_reservoir_cp_checkpoint(args.output / "best.json", domain.problem, plan)
    atomic_json(args.output / "result.json", result)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
