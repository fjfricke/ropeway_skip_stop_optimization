"""Opt-in native DIDPPy/CABS backend; legacy solvers remain unchanged."""

import argparse
import json
from pathlib import Path
from time import perf_counter
from ropeway_skip_stop_optimization.benchmarking.ddd_fixed_k_didp import (
    EXAMPLE,
    prepare_large,
    prepare_small,
)
from ropeway_skip_stop_optimization.optimization.ddd.didp.optimizer import (
    DddDidpConfig,
    DddDidpOptimizer,
)
from ropeway_skip_stop_optimization.optimization.ddd.fixed_k import DddFixedKStartPolicy
from ropeway_skip_stop_optimization.optimization.ddd.cp_sat_certificate import (
    atomic_json,
)


def main():
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument("--example", default=EXAMPLE)
    parser.add_argument("--cabins", "--cabin-count", type=int, required=True)
    parser.add_argument("--small-case", action="store_true")
    parser.add_argument(
        "--start-policy",
        choices=["canonical_rope", "balanced_reference"],
        default="balanced_reference",
    )
    parser.add_argument("--demand", type=int, default=3074)
    parser.add_argument("--maximum-wait-seconds", type=float, default=0)
    parser.add_argument("--waiting-step-seconds", type=float, default=1e-6)
    parser.add_argument("--objective", choices=["unserved"], default="unserved")
    parser.add_argument("--time-limit", "--time-limit-seconds", type=float, default=60)
    parser.add_argument("--threads", "--num-workers", type=int, default=1)
    parser.add_argument("--memory-limit-gib", type=float, default=8)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--reference-checkpoint", "--checkpoint-import", type=Path)
    parser.add_argument("--build-only", action="store_true")
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=False)
    started = perf_counter()
    if args.small_case:
        _, problem = prepare_small(
            args.cabins,
            waiting=args.maximum_wait_seconds,
            step=args.waiting_step_seconds,
        )
    else:
        _, problem = prepare_large(
            args.cabins,
            example=args.example,
            waiting=args.maximum_wait_seconds,
            step=args.waiting_step_seconds,
            demand=args.demand,
            start_policy=DddFixedKStartPolicy(args.start_policy),
        )
    input_seconds = perf_counter() - started
    config = DddDidpConfig(
        max(1e-6, args.time_limit - input_seconds),
        args.threads,
        args.memory_limit_gib,
        args.output_dir,
        args.reference_checkpoint,
        args.build_only,
    )
    atomic_json(
        args.output_dir / "config.json",
        {k: str(v) if isinstance(v, Path) else v for k, v in vars(args).items()},
    )

    def report(event):
        with (args.output_dir / "events.jsonl").open("a") as stream:
            stream.write(json.dumps(event) + "\n")
        print(
            json.dumps({k: v for k, v in event.items() if k != "incumbent"}), flush=True
        )

    result = DddDidpOptimizer(config).solve(problem, event_callback=report)
    result.update(
        input_preparation_seconds=input_seconds, total_seconds=perf_counter() - started
    )
    atomic_json(args.output_dir / "result.json", result)
    print(
        json.dumps(
            {
                k: v
                for k, v in result.items()
                if k
                not in (
                    "events",
                    "domain_manifest",
                    "native_incumbent",
                    "best_validated_incumbent",
                )
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
