from __future__ import annotations

import argparse
from pathlib import Path
import sys

from ropeway_skip_stop_optimization.benchmarking.ddd_fixed_k_feasibility import (
    DddFixedKFeasibilityLivePublisher,
    DddFixedKFeasibilityProbeResult,
    DddFixedKFeasibilitySweepConfig,
    DddFixedKFeasibilitySweepResult,
    DddFixedKFeasibilityTermination,
    read_ddd_fixed_k_feasibility_sweep,
    run_ddd_fixed_k_feasibility_sweep,
    write_ddd_fixed_k_feasibility_sweep,
)
from ropeway_skip_stop_optimization.benchmarking.optimization_live_store import (
    OptimizationLivePaths,
    OptimizationLiveStore,
)
from ropeway_skip_stop_optimization.optimization.ddd import (
    DddFixedKOperatingMode,
    DddFixedKSeedStatus,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Probe canonical exact-K movement feasibility sequentially with CP-SAT."
        )
    )
    parser.add_argument("--example", required=True)
    parser.add_argument("--k-from", type=int, required=True)
    parser.add_argument("--k-to", type=int, required=True)
    parser.add_argument(
        "--mode",
        choices=tuple(mode.value for mode in DddFixedKOperatingMode),
        default=DddFixedKOperatingMode.SKIP_STOP.value,
    )
    parser.add_argument("--time-limit", type=float, default=600.0)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--continue-on-unknown", action="store_true")
    parser.add_argument("--continue-on-infeasible", action="store_true")
    parser.add_argument("--premature-unknown-retries", type=int, default=1)
    parser.add_argument("--worker-grace", type=float, default=120.0)
    parser.add_argument(
        "--isolate-attempts",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--frontend-live", action="store_true")
    parser.add_argument("--publish-only", action="store_true")
    parser.add_argument("--campaign-id")
    parser.add_argument(
        "--frontend-root",
        type=Path,
        default=Path("frontend/public/generated/optimization"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("benchmarks/output/ddd_fixed_k_feasibility/result.json"),
    )
    args = parser.parse_args()

    config = DddFixedKFeasibilitySweepConfig(
        example_id=args.example,
        minimum_k=args.k_from,
        maximum_k=args.k_to,
        operating_mode=DddFixedKOperatingMode(args.mode),
        time_limit_seconds_per_k=args.time_limit,
        cp_sat_workers=args.workers,
        stop_on_unknown=not args.continue_on_unknown,
        stop_on_infeasible=not args.continue_on_infeasible,
        premature_unknown_retries=args.premature_unknown_retries,
        worker_grace_seconds=args.worker_grace,
        isolate_attempts=args.isolate_attempts,
    )
    config.validate()
    if args.publish_only and not args.frontend_live:
        parser.error("--publish-only requires --frontend-live")
    if args.publish_only and not args.output.exists():
        parser.error(f"cannot publish missing checkpoint: {args.output}")
    if args.output.exists() and not args.resume:
        if not args.publish_only:
            parser.error(f"output already exists: {args.output}; use --resume")
    existing = (
        read_ddd_fixed_k_feasibility_sweep(args.output, config=config)
        if (args.resume or args.publish_only) and args.output.exists()
        else ()
    )

    publisher = None
    if args.frontend_live:
        campaign_id = args.campaign_id or args.output.stem
        live_store = OptimizationLiveStore(
            OptimizationLivePaths(
                canonical_campaign_dir=args.output.parent / f"{campaign_id}_live",
                frontend_root=args.frontend_root,
            )
        )
        publisher = DddFixedKFeasibilityLivePublisher(
            store=live_store,
            campaign_id=campaign_id,
            config=config,
            label=(
                f"{config.example_id}: canonical Fixed-K "
                f"{config.operating_mode.value} feasibility"
            ),
        )
        if args.publish_only:
            published = DddFixedKFeasibilitySweepResult(
                config.fingerprint,
                existing,
            )
            publisher.publish_checkpoint(published)
            print(
                f"published campaign={campaign_id} probes={len(existing)} "
                f"frontend={args.frontend_root / campaign_id / 'snapshot.json'}"
            )
            return
        publisher.import_probes(existing)

    latest = list(existing)

    def progress(probe: DddFixedKFeasibilityProbeResult) -> None:
        latest.append(probe)
        write_ddd_fixed_k_feasibility_sweep(
            DddFixedKFeasibilitySweepResult(config.fingerprint, tuple(latest)),
            args.output,
        )
        print(
            f"K={probe.cabin_count} attempt={probe.attempt_index} "
            f"status={probe.status.value} termination={probe.termination.value} "
            f"kind={probe.seed_kind or '-'} cp={probe.cp_sat_seconds:.1f}s "
            f"total={probe.total_seconds:.1f}s "
            f"native={probe.cp_sat_solver_status_name or '-'} "
            f"conflicts={probe.cp_sat_conflict_count} "
            f"branches={probe.cp_sat_branch_count} "
            f"rss={_memory(probe.peak_rss_bytes)}",
            flush=True,
        )
        if publisher is not None:
            retryable = probe.termination in {
                DddFixedKFeasibilityTermination.PREMATURE_UNKNOWN,
                DddFixedKFeasibilityTermination.WORKER_ERROR,
                DddFixedKFeasibilityTermination.WORKER_TIMEOUT,
            }
            publisher.record_attempt(
                probe,
                final_for_k=not (
                    retryable
                    and probe.attempt_index <= config.premature_unknown_retries
                ),
            )

    result = run_ddd_fixed_k_feasibility_sweep(
        config,
        existing_probes=existing,
        progress_hook=progress,
    )
    write_ddd_fixed_k_feasibility_sweep(result, args.output)
    if publisher is not None:
        publisher.complete(result)
    frontier = result.frontier_probe
    print(
        f"done largest_feasible_k={result.largest_feasible_k} "
        f"frontier_k={None if frontier is None else frontier.cabin_count} "
        f"frontier_status={None if frontier is None else frontier.status.value} "
        f"output={args.output}"
    )
    if (
        frontier is not None
        and frontier.status is DddFixedKSeedStatus.INTERNAL_VALIDATION_ERROR
    ):
        raise RuntimeError(frontier.detail or "CP-SAT feasibility validation failed")


def _memory(value: int | None) -> str:
    if value is None:
        return "-"
    return f"{value / (1024**2):.0f}MiB"


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\ninterrupted; completed attempts remain checkpointed", file=sys.stderr)
        raise SystemExit(130)
