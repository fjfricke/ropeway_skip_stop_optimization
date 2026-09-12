"""Isolate hint feasibility from search on a frozen repair neighborhood."""

import argparse
import hashlib
import json
from pathlib import Path
from time import perf_counter

from ropeway_skip_stop_optimization.optimization.ddd.cp_sat_certificate import (
    atomic_json,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_hybrid.domain import (
    load_reference,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_hybrid.repair import (
    ReservoirRepairProblem,
    ReservoirRepairOptimizer,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_cp_sat_certificate import (
    write_reservoir_cp_checkpoint,
)


def main():
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--resume-checkpoint", required=True, type=Path)
    parser.add_argument("--neighborhoods", required=True, type=Path)
    parser.add_argument("--case", required=True)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--fixed-hint", action="store_true")
    parser.add_argument("--no-presolve", action="store_true")
    parser.add_argument("--time-limit", type=float, default=28)
    args = parser.parse_args()
    started = perf_counter()
    args.output_dir.mkdir(parents=True, exist_ok=False)
    domain, plan = load_reference(args.resume_checkpoint)
    selected = next(
        c for c in json.loads(args.neighborhoods.read_text()) if c["name"] == args.case
    )
    atomic_json(
        args.output_dir / "config.json",
        {
            **selected,
            "fixed_hint": args.fixed_hint,
            "presolve": not args.no_presolve,
            "workers": 12,
            "resume_checkpoint": str(args.resume_checkpoint),
            "checkpoint_sha256": hashlib.sha256(
                args.resume_checkpoint.read_bytes()
            ).hexdigest(),
            "time_limit": args.time_limit,
            "fingerprint": domain.fingerprint,
        },
    )
    atomic_json(
        args.output_dir / "source_hashes.json",
        {
            str(path): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(Path("src").rglob("*.py"))
        },
    )
    context = ReservoirRepairProblem.prepare(
        domain.problem, plan, selected["open_ids"], selected["new_slots"]
    )
    best, result = ReservoirRepairOptimizer().solve(
        context,
        time_limit=max(0.001, args.time_limit - (perf_counter() - started)),
        workers=12,
        verify_fixed_hint=args.fixed_hint,
        presolve=not args.no_presolve,
        log_path=args.output_dir / "solver.log",
        on_improvement=lambda s: write_reservoir_cp_checkpoint(
            args.output_dir / "incumbent.json", domain.problem, s
        ),
    )
    write_reservoir_cp_checkpoint(args.output_dir / "best.json", domain.problem, best)
    atomic_json(args.output_dir / "result.json", result)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
