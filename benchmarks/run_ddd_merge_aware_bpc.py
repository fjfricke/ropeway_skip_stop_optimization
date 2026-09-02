from __future__ import annotations

import argparse
from pathlib import Path

from ropeway_skip_stop_optimization.benchmarking.ddd_merge_aware_bpc import (
    DddMergeAwareRootGateConfig,
    DddMergeAwareRootGateRunner,
    DddMergeAwareRootVariant,
)
from ropeway_skip_stop_optimization.optimization.ddd import DddFixedKStartPolicy


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the matched merge-aware trajectory Root-CG gate."
    )
    parser.add_argument("--example", required=True)
    parser.add_argument("--k", type=int, required=True)
    parser.add_argument("--root-time-limit", type=float, default=900.0)
    parser.add_argument("--reference-lp-time-limit", type=float, default=900.0)
    parser.add_argument("--start-layout-time-limit", type=float, default=600.0)
    parser.add_argument("--max-iterations", type=int, default=60)
    parser.add_argument("--merge-corridor-time-limit", type=float, default=30.0)
    parser.add_argument("--merge-corridor-interval", type=int, default=3)
    parser.add_argument(
        "--merge-corridor-window-seconds",
        action="append",
        type=float,
        default=[],
    )
    parser.add_argument(
        "--variant",
        action="append",
        choices=tuple(item.value for item in DddMergeAwareRootVariant),
    )
    parser.add_argument(
        "--start-policy",
        choices=tuple(item.value for item in DddFixedKStartPolicy),
        default=DddFixedKStartPolicy.BALANCED_REFERENCE.value,
    )
    parser.add_argument("--threads", type=int)
    parser.add_argument("--solver-output", action="store_true")
    parser.add_argument("--progress", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("benchmarks/output/ddd_merge_aware_bpc/root_gate.json"),
    )
    args = parser.parse_args()

    variants = (
        tuple(DddMergeAwareRootVariant(item) for item in args.variant)
        if args.variant
        else tuple(DddMergeAwareRootVariant)
    )

    def progress(event: dict[str, object]) -> None:
        if not args.progress:
            return
        lower = event.get("certified_lower_bound")
        rmp = event.get("restricted_lp_value")
        upper = event.get("validated_upper_bound")
        print(
            f"{str(event.get('variant', '-')):31} "
            f"phase={str(event.get('phase', '-')):24} "
            f"r={str(event.get('round', '-')):>3} "
            f"LB={_number(lower)} RMP={_number(rmp)} UB={_number(upper)} "
            f"cols={str(event.get('trajectory_count', '-')):>5} "
            f"batch={event.get('compatible_batch_selected_count', 0)}/"
            f"{event.get('compatible_batch_candidate_count', 0)} "
            f"corridor={event.get('merge_corridor_released_cabin_count', 0)}c/"
            f"{event.get('merge_corridor_released_decision_count', 0)}d/"
            f"{event.get('merge_corridor_candidate_count', 0)}p",
            flush=True,
        )

    result = DddMergeAwareRootGateRunner().run(
        DddMergeAwareRootGateConfig(
            example_id=args.example,
            cabin_count=args.k,
            output_path=args.output,
            variants=variants,
            root_time_limit_seconds=args.root_time_limit,
            reference_lp_time_limit_seconds=args.reference_lp_time_limit,
            start_layout_time_limit_seconds=args.start_layout_time_limit,
            maximum_iterations=args.max_iterations,
            merge_corridor_time_limit_seconds=args.merge_corridor_time_limit,
            merge_corridor_interval=args.merge_corridor_interval,
            merge_corridor_window_widths_seconds=tuple(
                sorted(
                    set(
                        args.merge_corridor_window_seconds
                        or (120.0, 240.0, 480.0)
                    )
                )
            ),
            start_policy=DddFixedKStartPolicy(args.start_policy),
            threads=args.threads,
            solver_output=args.solver_output,
        ),
        progress_hook=progress,
    )
    print(
        f"done fingerprint={result.problem_fingerprint} "
        f"variants={len(result.variants)} output={args.output}",
        flush=True,
    )


def _number(value: object) -> str:
    if value is None:
        return f"{'-':>12}"
    return f"{float(value):12,.1f}"


if __name__ == "__main__":
    main()
