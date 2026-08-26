from __future__ import annotations

import argparse
import json
from pathlib import Path
from time import perf_counter

from ropeway_skip_stop_optimization.benchmarking.ddd_fixed_k_arc_flow import (
    DddAnalyticAllStopInfeasible,
    DddFixedKArcFlowRunConfig,
    run_ddd_fixed_k_arc_flow,
    write_ddd_fixed_k_arc_flow_result,
)
from ropeway_skip_stop_optimization.benchmarking.ddd_fixed_k_campaign import (
    DddFixedKCampaignConfig,
    derive_available_fleet_intervals,
    derive_skip_stop_benefit_interval,
)
from ropeway_skip_stop_optimization.benchmarking.optimization_events import (
    OptimizationEventKind,
)
from ropeway_skip_stop_optimization.benchmarking.optimization_live_store import (
    OptimizationLivePaths,
    OptimizationLiveStore,
    reduce_optimization_events,
)
from ropeway_skip_stop_optimization.optimization.ddd import (
    DddFixedKArcFlowProgress,
    DddFixedKOperatingMode,
    DddFixedKProfileConfig,
    DddFixedKStartPolicy,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run a complete-DDD-arc-flow exact-K campaign."
    )
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path("benchmarks/output/ddd_fixed_k_arc_flow_campaigns"),
    )
    parser.add_argument(
        "--frontend-root",
        type=Path,
        default=Path("frontend/public/generated/optimization"),
    )
    parser.add_argument("--frontend-live", action="store_true")
    parser.add_argument("--progress", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--threads", type=int)
    parser.add_argument("--cp-seed-workers", type=int, default=8)
    args = parser.parse_args()

    campaign = DddFixedKCampaignConfig.from_dict(
        json.loads(args.config.read_text(encoding="utf-8"))
    )
    if campaign.start_policy not in (
        DddFixedKStartPolicy.CANONICAL_ROPE,
        DddFixedKStartPolicy.BALANCED_REFERENCE,
    ):
        raise ValueError(
            "complete DDD arc-flow campaigns require canonical_rope or "
            "balanced_reference starts"
        )
    profile = DddFixedKProfileConfig.for_profile(campaign.profile)
    campaign_dir = args.output_root / campaign.campaign_id
    store = OptimizationLiveStore(
        OptimizationLivePaths(
            canonical_campaign_dir=campaign_dir,
            frontend_root=args.frontend_root if args.frontend_live else None,
        )
    )
    existing = store.read_events()
    if existing and not args.resume:
        raise ValueError(f"campaign {campaign.campaign_id!r} exists; use --resume")
    completed_keys: set[tuple[str, int]] = set()
    results: list[dict[str, object]] = []
    if existing:
        snapshot = reduce_optimization_events(existing)
        for trial in snapshot["trials"].values():
            if trial["status"] != "complete":
                continue
            completed_keys.add(
                (str(trial["policy_id"]), int(trial["available_fleet_count"]))
            )
            results.append(dict(trial))
    else:
        store.append_new(
            OptimizationEventKind.CAMPAIGN_STARTED,
            campaign.campaign_id,
            payload={
                "label": campaign.label,
                "objective": campaign.objective.value,
                "example_id": campaign.example_id,
                "profile": campaign.profile.value,
                "start_policy": campaign.start_policy.value,
                "trial_count": len(campaign.k_values) * len(campaign.operating_modes),
                "method": "fixed_k_complete_ddd_arc_flow",
            },
        )
        _publish(store)

    for mode in campaign.operating_modes:
        for cabin_count in campaign.k_values:
            if (mode.value, cabin_count) in completed_keys:
                continue
            trial_dir = campaign_dir / "policies" / mode.value / f"k{cabin_count}"
            store.append_new(
                OptimizationEventKind.TRIAL_STARTED,
                campaign.campaign_id,
                policy_id=mode.value,
                available_fleet_count=cabin_count,
                stage="start_preparation",
                payload={
                    "exact_active_cabin_count": cabin_count,
                    "start_policy": campaign.start_policy.value,
                },
            )
            _publish(store)
            trial_started = perf_counter()
            last_progress_width = 0

            def progress(sample: DddFixedKArcFlowProgress) -> None:
                nonlocal last_progress_width
                store.append_new(
                    OptimizationEventKind.SOLVER_SAMPLE,
                    campaign.campaign_id,
                    policy_id=mode.value,
                    available_fleet_count=cabin_count,
                    stage=sample.phase,
                    global_certified_lower_bound=sample.certified_lower_bound,
                    local_solver_incumbent=sample.solver_incumbent,
                    local_solver_bound=sample.solver_bound,
                    local_solver_gap=sample.solver_gap,
                    elapsed_seconds=perf_counter() - trial_started,
                    payload={
                        "node_count": sample.node_count,
                        "solution_count": sample.solution_count,
                        "movement_variable_count": sample.movement_variable_count,
                        "passenger_variable_count": sample.passenger_variable_count,
                        "movement_constraint_count": sample.movement_constraint_count,
                        "passenger_constraint_count": sample.passenger_constraint_count,
                        "resource_row_count": sample.resource_row_count,
                        "linear_constraint_count": sample.linear_constraint_count,
                        "remaining_budget_seconds": sample.remaining_seconds,
                        "simplex_iteration_count": sample.simplex_iteration_count,
                        "barrier_iteration_count": sample.barrier_iteration_count,
                        "presolved_removed_row_count": (
                            sample.presolved_removed_row_count
                        ),
                        "presolved_removed_column_count": (
                            sample.presolved_removed_column_count
                        ),
                    },
                )
                _publish(store)
                if args.progress:
                    line = _progress_line(mode, cabin_count, sample)
                    padding = " " * max(0, last_progress_width - len(line))
                    print(
                        f"\r{line}{padding}",
                        end="",
                        flush=True,
                    )
                    last_progress_width = len(line)

            try:
                run_result = run_ddd_fixed_k_arc_flow(
                    DddFixedKArcFlowRunConfig(
                        example_id=campaign.example_id,
                        cabin_count=cabin_count,
                        operating_mode=mode,
                        objective=campaign.objective,
                        start_policy=campaign.start_policy,
                        start_layout_time_limit_seconds=(
                            _start_layout_budget_seconds(campaign.profile.value)
                        ),
                        total_time_limit_seconds=profile.total_time_limit_seconds,
                        cp_seed_time_limit_seconds=profile.cp_seed_time_limit_seconds,
                        cp_seed_workers=args.cp_seed_workers,
                        solver_threads=args.threads,
                    ),
                    progress_hook=progress,
                )
            except DddAnalyticAllStopInfeasible as error:
                if args.progress and last_progress_width:
                    print()
                payload = {
                    "status": "movement_infeasible",
                    "certificate_kind": "analytic_all_stop_capacity",
                    "detail": str(error),
                    "example_id": campaign.example_id,
                    "operating_mode": mode.value,
                    "exact_active_cabin_count": cabin_count,
                    "objective": campaign.objective.value,
                    "start_policy": campaign.start_policy.value,
                    "all_stop_maximum_cabin_count": error.maximum_cabin_count,
                    "total_seconds": perf_counter() - trial_started,
                }
                results.append(payload)
                store.append_new(
                    OptimizationEventKind.TRIAL_COMPLETED,
                    campaign.campaign_id,
                    policy_id=mode.value,
                    available_fleet_count=cabin_count,
                    stage="analytic_all_stop_capacity",
                    elapsed_seconds=perf_counter() - trial_started,
                    payload=payload,
                )
                _publish(store)
                print(
                    f"{mode.value} K={cabin_count} "
                    f"status=movement_infeasible analytic K_max_AS="
                    f"{error.maximum_cabin_count}",
                    flush=True,
                )
                continue
            except Exception as error:
                if args.progress and last_progress_width:
                    print()
                store.append_new(
                    OptimizationEventKind.TRIAL_FAILED,
                    campaign.campaign_id,
                    policy_id=mode.value,
                    available_fleet_count=cabin_count,
                    stage="failed",
                    elapsed_seconds=perf_counter() - trial_started,
                    payload={"detail": str(error)},
                )
                _publish(store)
                raise
            if args.progress and last_progress_width:
                print()
            write_ddd_fixed_k_arc_flow_result(run_result, trial_dir / "result.json")
            payload = run_result.to_payload()
            results.append(payload)
            solve = run_result.solve_result
            store.append_new(
                OptimizationEventKind.TRIAL_COMPLETED,
                campaign.campaign_id,
                policy_id=mode.value,
                available_fleet_count=cabin_count,
                trial_fingerprint=solve.problem_fingerprint,
                stage="complete",
                global_certified_lower_bound=solve.certified_lower_bound,
                global_validated_upper_bound=solve.validated_upper_bound,
                global_relative_gap=solve.relative_gap,
                local_solver_incumbent=solve.objective_value,
                local_solver_bound=solve.solver_best_bound,
                local_solver_gap=solve.relative_gap,
                elapsed_seconds=run_result.total_seconds,
                payload=payload,
            )
            _publish(store)
            print(
                f"{mode.value} K={cabin_count} status={solve.status.value} "
                f"LB={solve.certified_lower_bound:.3f} "
                f"UB={solve.validated_upper_bound}",
                flush=True,
            )

    store.append_new(
        OptimizationEventKind.CAMPAIGN_COMPLETED,
        campaign.campaign_id,
        payload={"status": "complete", "comparison": _comparisons(results)},
    )
    _publish(store)


def _comparisons(results: list[dict[str, object]]) -> dict[str, object]:
    by_mode: dict[str, dict[int, tuple[float, float | None]]] = {}
    requested_by_mode: dict[str, set[int]] = {}
    analytic_all_stop_limit: int | None = None
    for result in results:
        mode = str(result["operating_mode"])
        cabin_count = int(result["exact_active_cabin_count"])
        requested_by_mode.setdefault(mode, set()).add(cabin_count)
        if result.get("certificate_kind") == "analytic_all_stop_capacity":
            analytic_all_stop_limit = int(result["all_stop_maximum_cabin_count"])
        if result.get("certified_lower_bound") is None:
            continue
        by_mode.setdefault(mode, {})[cabin_count] = (
            float(result["certified_lower_bound"]),
            None
            if result.get("validated_upper_bound") is None
            else float(result["validated_upper_bound"]),
        )
    available: dict[str, dict[int, tuple[float, float | None]]] = {}
    for mode, values in by_mode.items():
        prefix = derive_available_fleet_intervals(values)
        carried: dict[int, tuple[float, float | None]] = {}
        for requested_k in sorted(requested_by_mode.get(mode, ())):
            eligible = [tested_k for tested_k in prefix if tested_k <= requested_k]
            if eligible:
                carried[requested_k] = prefix[max(eligible)]
        available[mode] = carried
    benefit: dict[int, tuple[float, float]] = {}
    all_stop = by_mode.get(DddFixedKOperatingMode.ALL_STOP.value, {})
    skip_stop = by_mode.get(DddFixedKOperatingMode.SKIP_STOP.value, {})
    for cabin_count in sorted(set(all_stop) & set(skip_stop)):
        as_lower, as_upper = all_stop[cabin_count]
        ss_lower, ss_upper = skip_stop[cabin_count]
        if as_upper is None or ss_upper is None:
            continue
        benefit[cabin_count] = derive_skip_stop_benefit_interval(
            all_stop_lower=as_lower,
            all_stop_upper=as_upper,
            skip_stop_lower=ss_lower,
            skip_stop_upper=ss_upper,
        )
    capacity_advantage = {
        int(result["exact_active_cabin_count"]): {
            "all_stop_status": "movement_infeasible",
            "all_stop_maximum_cabin_count": analytic_all_stop_limit,
            "skip_stop_validated_upper_bound": result.get("validated_upper_bound"),
            "skip_stop_status": result.get("status"),
        }
        for result in results
        if result.get("operating_mode")
        == DddFixedKOperatingMode.SKIP_STOP.value
        and analytic_all_stop_limit is not None
        and int(result["exact_active_cabin_count"]) > analytic_all_stop_limit
        and result.get("validated_upper_bound") is not None
    }
    return {
        "available_fleet": available,
        "skip_stop_benefit": benefit,
        "capacity_advantage": capacity_advantage,
    }


def _progress_line(
    mode: DddFixedKOperatingMode,
    cabin_count: int,
    sample: DddFixedKArcFlowProgress,
) -> str:
    upper = "-" if sample.solver_incumbent is None else f"{sample.solver_incumbent:.1f}"
    return (
        f"{mode.value} K={cabin_count} LB={sample.certified_lower_bound:.1f} "
        f"UB={upper} nodes={sample.node_count:.0f} "
        f"phase={sample.phase:<20.20} left={sample.remaining_seconds:.0f}s"
    )


def _publish(store: OptimizationLiveStore) -> None:
    store.publish(reduce_optimization_events(store.read_events()))


def _start_layout_budget_seconds(profile: str) -> float:
    return {
        "screening": 120.0,
        "regular": 600.0,
        "headline": 1_800.0,
    }[profile]


if __name__ == "__main__":
    main()
