from __future__ import annotations

import argparse
from pathlib import Path

from ropeway_skip_stop_optimization.benchmarking.ddd_fixed_k_arc_flow import (
    DddFixedKArcFlowRunConfig,
)
from ropeway_skip_stop_optimization.benchmarking.ddd_partial_passenger_benders import (
    DddPartialPassengerGateConfig,
    DddPartialPassengerGateRunner,
    DddPartialPassengerGateVariant,
    write_ddd_partial_passenger_gate_result,
)
from ropeway_skip_stop_optimization.optimization.ddd import (
    DddFixedKOperatingMode,
    DddFixedKStartPolicy,
    DddPartialPassengerCutStrategy,
    DddPassengerCorePolicy,
)
from ropeway_skip_stop_optimization.optimization.ean import EanPassengerObjective


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Run the gated partial-Passenger root-cut laboratory on one exact-K "
            "DDD arc-flow instance."
        )
    )
    parser.add_argument("--example", required=True)
    parser.add_argument("--cabins", type=int, required=True)
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
    parser.add_argument(
        "--policies",
        default=DddPassengerCorePolicy.HYBRID.value,
        help="Comma-separated selective core policies.",
    )
    parser.add_argument(
        "--core-fractions",
        default="0.1,0.2,0.4",
        help="Comma-separated core variable/nonzero budget fractions.",
    )
    parser.add_argument("--include-none-control", action="store_true")
    parser.add_argument("--include-all-control", action="store_true")
    parser.add_argument("--time-limit", type=float, default=120.0)
    parser.add_argument("--max-iterations", type=int, default=30)
    parser.add_argument(
        "--cut-strategy",
        choices=tuple(item.value for item in DddPartialPassengerCutStrategy),
        default=DddPartialPassengerCutStrategy.STANDARD.value,
    )
    parser.add_argument("--pareto-time-limit", type=float, default=10.0)
    parser.add_argument("--reference-lp-objective", type=float)
    parser.add_argument("--reference-problem-fingerprint")
    parser.add_argument("--required-bound-fraction", type=float, default=0.9)
    parser.add_argument("--maximum-core-nonzero-fraction", type=float, default=0.4)
    parser.add_argument("--threads", type=int)
    parser.add_argument("--gurobi-output", action="store_true")
    parser.add_argument("--progress", action="store_true")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(
            "benchmarks/output/ddd_partial_passenger_benders/root_gate.json"
        ),
    )
    args = parser.parse_args()

    policies = tuple(
        DddPassengerCorePolicy(item.strip())
        for item in args.policies.split(",")
        if item.strip()
    )
    if any(
        item in {DddPassengerCorePolicy.NONE, DddPassengerCorePolicy.ALL}
        for item in policies
    ):
        parser.error("--policies accepts selective policies only")
    fractions = tuple(
        float(item.strip())
        for item in args.core_fractions.split(",")
        if item.strip()
    )
    variants = []
    if args.include_none_control:
        variants.append(
            DddPartialPassengerGateVariant(
                id="none",
                policy=DddPassengerCorePolicy.NONE,
                core_variable_fraction=0.0,
                core_nonzero_fraction=0.0,
            )
        )
    for policy in policies:
        for fraction in fractions:
            variants.append(
                DddPartialPassengerGateVariant(
                    id=f"{policy.value}_{fraction:g}",
                    policy=policy,
                    core_variable_fraction=fraction,
                    core_nonzero_fraction=fraction,
                )
            )
    if args.include_all_control:
        variants.append(
            DddPartialPassengerGateVariant(
                id="all",
                policy=DddPassengerCorePolicy.ALL,
                core_variable_fraction=1.0,
                core_nonzero_fraction=1.0,
            )
        )

    last_width = 0

    def progress(variant_id, sample) -> None:
        nonlocal last_width
        if not args.progress:
            return
        line = (
            f"{variant_id:<18.18} r={sample.iteration:02d}/{args.max_iterations:02d} "
            f"phase={sample.phase:<12.12} cuts={sample.cut_count:03d} "
            f"LB={sample.certified_lower_bound:12,.1f} "
            f"left={sample.remaining_seconds:6.1f}s"
        )
        padding = " " * max(0, last_width - len(line))
        print(f"\r{line}{padding}", end="", flush=True)
        last_width = len(line)
        if sample.phase == "complete":
            print()
            last_width = 0

    result = DddPartialPassengerGateRunner().run(
        DddPartialPassengerGateConfig(
            run=DddFixedKArcFlowRunConfig(
                example_id=args.example,
                cabin_count=args.cabins,
                operating_mode=DddFixedKOperatingMode(args.mode),
                objective=EanPassengerObjective(args.objective),
                start_policy=DddFixedKStartPolicy(args.start_policy),
                total_time_limit_seconds=max(args.time_limit, 1.0),
                solver_threads=args.threads,
                output_flag=args.gurobi_output,
            ),
            variants=tuple(variants),
            per_variant_time_limit_seconds=args.time_limit,
            max_iterations=args.max_iterations,
            reference_lp_objective=args.reference_lp_objective,
            reference_problem_fingerprint=args.reference_problem_fingerprint,
            required_bound_fraction=args.required_bound_fraction,
            maximum_core_nonzero_fraction=(
                args.maximum_core_nonzero_fraction
            ),
            cut_strategy=DddPartialPassengerCutStrategy(args.cut_strategy),
            pareto_time_limit_seconds=args.pareto_time_limit,
        ),
        progress_hook=progress,
    )
    write_ddd_partial_passenger_gate_result(result, args.output)
    print(
        f"done fingerprint={result.problem_fingerprint[:12]} "
        f"reference_verified={result.reference_verified} "
        f"passed={','.join(result.passed_variant_ids) or '-'} "
        f"time={result.total_seconds:.1f}s output={args.output}"
    )
    for item in result.variants:
        achieved = (
            "-"
            if item.achieved_reference_fraction is None
            else f"{100 * item.achieved_reference_fraction:.1f}%"
        )
        print(
            f"  {item.variant.id:<18} status={item.root.status.value:<36} "
            f"LB={item.root.certified_lower_bound:12,.1f} "
            f"reference={achieved:>7} core_nnz={100 * item.core_nonzero_fraction:5.1f}% "
            f"cuts={item.root.cut_count:3d}"
        )


if __name__ == "__main__":
    main()
