"""Supervised native engine entry point; existing CLI defaults are unchanged."""

import argparse
import json
import math
import sys
import time
from pathlib import Path

from ropeway_skip_stop_optimization.benchmarking.native_solvers import (
    prepare_input,
    supervise,
    worker,
)
from ropeway_skip_stop_optimization.optimization.ddd.cp_sat_certificate import (
    atomic_json,
)


def parser():
    p = argparse.ArgumentParser(allow_abbrev=False)
    p.add_argument(
        "--backend", choices=["hexaly", "z3", "tempest", "patty"], required=True
    )
    p.add_argument("--operation", choices=["fixed_k", "reservoir"], required=True)
    p.add_argument(
        "--objective", choices=["journey_time", "unserved"], default="unserved"
    )
    p.add_argument("--example", required=True)
    p.add_argument("--cabins", type=int)
    p.add_argument("--max-cabins", type=int)
    p.add_argument("--mode", choices=["all_stop", "skip_stop"], default="skip_stop")
    p.add_argument(
        "--start-policy",
        choices=["canonical_rope", "balanced_reference"],
        default=None,
    )
    p.add_argument("--entry-state")
    p.add_argument("--demand", type=int)
    p.add_argument("--warmup-seconds", type=float)
    p.add_argument("--service-seconds", type=float)
    p.add_argument("--recovery-seconds", type=float)
    p.add_argument("--maximum-wait-seconds", type=float, default=0)
    p.add_argument("--waiting-step-seconds", type=float, default=1e-6)
    p.add_argument("--dispatch-step-seconds", type=float)
    p.add_argument("--time-limit", type=float, default=60)
    p.add_argument("--num-workers", type=int, default=1)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--memory-gib", type=float, default=8)
    p.add_argument("--output-dir", type=Path, required=True)
    p.add_argument("--resume-checkpoint", type=Path)
    p.add_argument("--build-only", action="store_true")
    p.add_argument("--_worker", action="store_true", help=argparse.SUPPRESS)
    return p


def main():
    p = parser()
    args = p.parse_args()
    if args.backend in ("tempest", "patty"):
        p.error(
            "temporal engines require a passed exact-semantics gate; run probe_temporal_solvers.py first. No full ropeway adapter is certified."
        )
    if args.operation == "fixed_k" and (
        args.cabins is None or args.max_cabins is not None
    ):
        p.error("fixed_k requires --cabins and does not accept --max-cabins")
    if args.operation == "reservoir" and (
        args.max_cabins is None or args.cabins is not None
    ):
        p.error("reservoir requires --max-cabins and does not accept --cabins")
    if args.warmup_seconds is None:
        args.warmup_seconds = 300 if args.operation == "reservoir" else 0
    if args.operation == "fixed_k":
        if any(
            x is not None
            for x in (
                args.entry_state,
                args.service_seconds,
                args.recovery_seconds,
                args.dispatch_step_seconds,
            )
        ):
            p.error(
                "entry/dispatch/service/recovery arguments apply only to reservoir; Fixed-K uses the example horizon and tail"
            )
        args.start_policy = args.start_policy or "balanced_reference"
    else:
        if args.start_policy is not None:
            p.error("reservoir does not accept a fixed start policy")
        args.entry_state = args.entry_state or "A_entry_cw"
        args.service_seconds = (
            1200 if args.service_seconds is None else args.service_seconds
        )
        args.recovery_seconds = (
            300 if args.recovery_seconds is None else args.recovery_seconds
        )
        args.dispatch_step_seconds = (
            1e-6 if args.dispatch_step_seconds is None else args.dispatch_step_seconds
        )
    if any(not math.isfinite(x) or x <= 0 for x in (args.time_limit, args.memory_gib)):
        p.error("finite positive time and memory limits required")
    if args._worker:
        started = time.monotonic()
        try:
            problem, seed = prepare_input(args)
            result = worker(problem, seed, args, started=started)
        except Exception as exc:  # noqa: BLE001 - preserve diagnostics across optional native engine failures
            result = {
                "status": "ERROR",
                "error": f"{type(exc).__name__}: {exc}",
                "proven_optimal": False,
            }
            atomic_json(args.output_dir / "result.json", result)
        print(json.dumps(result, default=str))
        return
    args.output_dir.mkdir(parents=True, exist_ok=False)
    atomic_json(
        args.output_dir / "config.json",
        {k: str(v) if isinstance(v, Path) else v for k, v in vars(args).items()},
    )
    supervise(
        [sys.executable, str(Path(__file__).resolve()), *sys.argv[1:], "--_worker"],
        args.output_dir,
        seconds=args.time_limit,
        memory_bytes=int(args.memory_gib * 1024**3),
    )
    result_file = args.output_dir / "result.json"
    if result_file.exists():
        print(result_file.read_text())
    else:
        print(
            json.dumps(
                {
                    "status": "INTERRUPTED",
                    "proven_optimal": False,
                    "supervisor": str(args.output_dir / "supervisor.json"),
                }
            )
        )


if __name__ == "__main__":
    main()
