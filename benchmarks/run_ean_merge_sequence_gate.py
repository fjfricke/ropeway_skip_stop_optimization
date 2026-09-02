from __future__ import annotations

import argparse
from pathlib import Path

from ropeway_skip_stop_optimization.benchmarking.ean_merge_sequence import (
    EanMergeSequenceGateCase,
    solve_ean_merge_sequence_gate,
    write_ean_merge_sequence_gate_results,
)
from ropeway_skip_stop_optimization.optimization.ean import (
    EanMergeGateFormulation,
    EanMergeGateSolveConfig,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the isolated Merge-Sequence EAN gate")
    parser.add_argument("--stream-size", type=int, default=10)
    parser.add_argument(
        "--release-pattern",
        choices=("uniform", "clustered", "adversarial", "random"),
        default="adversarial",
    )
    parser.add_argument("--service-headway", type=float, default=10.0)
    parser.add_argument("--skip-headway", type=float, default=5.0)
    parser.add_argument("--time-limit", type=float, default=120.0)
    parser.add_argument("--threads", type=int, default=1)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument(
        "--formulations",
        default="pairwise_fifo,lattice,slots,cp_sat",
        help="comma-separated formulation names",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("benchmarks/output/ean_merge_sequence/gate.json"),
    )
    args = parser.parse_args()
    formulations = tuple(
        EanMergeGateFormulation(item.strip())
        for item in args.formulations.split(",")
        if item.strip()
    )
    case = EanMergeSequenceGateCase(
        stream_size=args.stream_size,
        release_pattern=args.release_pattern,
        service_headway_seconds=args.service_headway,
        skip_headway_seconds=args.skip_headway,
        seed=args.seed,
    )
    config = EanMergeGateSolveConfig(
        time_limit_seconds=args.time_limit,
        threads=args.threads,
        seed=args.seed,
    )
    results = solve_ean_merge_sequence_gate(
        case,
        formulations=formulations,
        config=config,
    )
    write_ean_merge_sequence_gate_results(
        args.output,
        case=case,
        config=config,
        results=results,
    )
    for result in results:
        metrics = result.metrics
        print(
            f"{result.formulation.value:14s} status={result.status:8s} "
            f"obj={result.objective} vars={metrics.variable_count} "
            f"bin={metrics.binary_variable_count} rows={metrics.constraint_count} "
            f"build={metrics.build_seconds:.3f}s solve={metrics.solve_seconds:.3f}s "
            f"nodes={metrics.node_count}"
        )
    print(f"output={args.output}")


if __name__ == "__main__":
    main()
