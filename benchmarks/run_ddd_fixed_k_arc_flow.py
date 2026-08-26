from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from time import perf_counter

from ropeway_skip_stop_optimization.benchmarking.ddd_fixed_k_arc_flow import (
    DddAnalyticAllStopInfeasible,
    DddFixedKArcFlowRunConfig,
    run_ddd_fixed_k_arc_flow,
    write_ddd_fixed_k_arc_flow_result,
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
    DddFixedKStartPolicy,
)
from ropeway_skip_stop_optimization.optimization.ean import EanPassengerObjective


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Solve one exact-K fixed-start problem as a complete DDD arc-flow MILP."
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
        choices=(
            DddFixedKStartPolicy.CANONICAL_ROPE.value,
            DddFixedKStartPolicy.BALANCED_REFERENCE.value,
        ),
        default=DddFixedKStartPolicy.CANONICAL_ROPE.value,
    )
    parser.add_argument(
        "--objective",
        choices=tuple(item.value for item in EanPassengerObjective),
        default=EanPassengerObjective.JOURNEY_TIME.value,
    )
    parser.add_argument("--time-limit", type=float, default=600.0)
    parser.add_argument("--cp-seed-time-limit", type=float, default=60.0)
    parser.add_argument("--start-layout-time-limit", type=float, default=120.0)
    parser.add_argument("--cp-seed-workers", type=int, default=8)
    parser.add_argument("--threads", type=int)
    parser.add_argument("--mip-gap", type=float, default=0.0)
    parser.add_argument("--mip-focus", type=int, choices=range(4), default=0)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--gurobi-output", action="store_true")
    parser.add_argument("--root-cg-result", type=Path)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("benchmarks/output/ddd_fixed_k_arc_flow"),
    )
    parser.add_argument("--campaign-id")
    parser.add_argument(
        "--frontend-root",
        type=Path,
        default=Path("frontend/public/generated/optimization"),
    )
    parser.add_argument("--frontend-live", action="store_true")
    parser.add_argument("--progress", action="store_true")
    args = parser.parse_args()

    mode = DddFixedKOperatingMode(args.mode)
    campaign_id = args.campaign_id or (
        f"{args.example}_arc_flow_{mode.value}_k{args.cabins}"
    )
    policy_id = f"arc_flow_{mode.value}"
    output_path = args.output_dir / campaign_id / "result.json"
    store = (
        OptimizationLiveStore(
            OptimizationLivePaths(
                canonical_campaign_dir=args.output_dir / campaign_id,
                frontend_root=args.frontend_root,
            )
        )
        if args.frontend_live
        else None
    )
    if store is not None:
        store.append_new(
            OptimizationEventKind.CAMPAIGN_STARTED,
            campaign_id,
            payload={
                "label": f"{args.example}: complete DDD arc-flow K={args.cabins}",
                "objective": args.objective,
                "example_id": args.example,
                "trial_count": 1,
                "method": "fixed_k_complete_ddd_arc_flow",
            },
        )
        store.append_new(
            OptimizationEventKind.TRIAL_STARTED,
            campaign_id,
            policy_id=policy_id,
            available_fleet_count=args.cabins,
            stage="start_preparation",
            payload={
                "exact_active_cabin_count": args.cabins,
                "start_policy": args.start_policy,
            },
        )
        _publish(store)

    started = perf_counter()
    last_width = 0

    def progress(sample: DddFixedKArcFlowProgress) -> None:
        nonlocal last_width
        bound = _number(sample.certified_lower_bound)
        incumbent = _number(sample.solver_incumbent)
        certified_gap = (
            None
            if sample.solver_incumbent is None
            else max(0.0, sample.solver_incumbent - sample.certified_lower_bound)
            / max(abs(sample.solver_incumbent), 1e-9)
        )
        gap = "      -" if certified_gap is None else f"{100 * certified_gap:7.2f}%"
        line = (
            f" {mode.value[:2].upper()} K={args.cabins:03d} | "
            f"LB={bound} UB={incumbent} gap={gap} | "
            f"phase={sample.phase:<20.20} | "
            f"nodes={sample.node_count:9.0f} sol={sample.solution_count:03d} | "
            f"x={sample.movement_variable_count:,} p={sample.passenger_variable_count:,} "
            f"rows={sample.movement_constraint_count:,}/"
            f"{sample.resource_row_count:,}/"
            f"{sample.passenger_constraint_count:,} | "
            f"left={_clock(sample.remaining_seconds)}"
        )
        if args.progress:
            padding = " " * max(0, last_width - len(line))
            print(f"\r{line}{padding}", end="", flush=True)
            last_width = len(line)
        if store is not None:
            store.append_new(
                OptimizationEventKind.SOLVER_SAMPLE,
                campaign_id,
                policy_id=policy_id,
                available_fleet_count=args.cabins,
                stage=sample.phase,
                global_certified_lower_bound=sample.certified_lower_bound,
                local_solver_incumbent=sample.solver_incumbent,
                local_solver_bound=sample.solver_bound,
                local_solver_gap=sample.solver_gap,
                elapsed_seconds=sample.elapsed_seconds,
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

    try:
        run_result = run_ddd_fixed_k_arc_flow(
            DddFixedKArcFlowRunConfig(
                example_id=args.example,
                cabin_count=args.cabins,
                operating_mode=mode,
                objective=EanPassengerObjective(args.objective),
                start_policy=DddFixedKStartPolicy(args.start_policy),
                start_layout_time_limit_seconds=args.start_layout_time_limit,
                total_time_limit_seconds=args.time_limit,
                cp_seed_time_limit_seconds=args.cp_seed_time_limit,
                cp_seed_workers=args.cp_seed_workers,
                solver_threads=args.threads,
                mip_gap=args.mip_gap,
                mip_focus=args.mip_focus,
                seed=args.seed,
                output_flag=args.gurobi_output,
                root_cg_result_path=args.root_cg_result,
            ),
            progress_hook=progress,
        )
    except DddAnalyticAllStopInfeasible as error:
        if args.progress:
            print()
        payload = {
            "status": "movement_infeasible",
            "certificate_kind": "analytic_all_stop_capacity",
            "detail": str(error),
            "example_id": args.example,
            "operating_mode": mode.value,
            "exact_active_cabin_count": args.cabins,
            "objective": args.objective,
            "start_policy": args.start_policy,
            "all_stop_maximum_cabin_count": error.maximum_cabin_count,
            "total_seconds": perf_counter() - started,
        }
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        if store is not None:
            store.append_new(
                OptimizationEventKind.TRIAL_COMPLETED,
                campaign_id,
                policy_id=policy_id,
                available_fleet_count=args.cabins,
                stage="analytic_all_stop_capacity",
                elapsed_seconds=payload["total_seconds"],
                payload=payload,
            )
            store.append_new(
                OptimizationEventKind.CAMPAIGN_COMPLETED,
                campaign_id,
                payload={"status": "complete"},
            )
            _publish(store)
        print(
            f"status=movement_infeasible certificate=analytic_all_stop_capacity "
            f"K_max_AS={error.maximum_cabin_count} output={output_path}"
        )
        return
    except Exception as error:
        if args.progress:
            print()
        if store is not None:
            store.append_new(
                OptimizationEventKind.TRIAL_FAILED,
                campaign_id,
                policy_id=policy_id,
                available_fleet_count=args.cabins,
                stage="failed",
                elapsed_seconds=perf_counter() - started,
                payload={"detail": str(error)},
            )
            _publish(store)
        raise

    if args.progress:
        print()
    write_ddd_fixed_k_arc_flow_result(run_result, output_path)
    result = run_result.solve_result
    if store is not None:
        store.append_new(
            OptimizationEventKind.TRIAL_COMPLETED,
            campaign_id,
            policy_id=policy_id,
            available_fleet_count=args.cabins,
            trial_fingerprint=result.problem_fingerprint,
            stage="complete",
            global_certified_lower_bound=result.certified_lower_bound,
            global_validated_upper_bound=result.validated_upper_bound,
            global_relative_gap=result.relative_gap,
            local_solver_incumbent=result.objective_value,
            local_solver_bound=result.solver_best_bound,
            local_solver_gap=result.relative_gap,
            elapsed_seconds=run_result.total_seconds,
            payload=run_result.to_payload(),
        )
        store.append_new(
            OptimizationEventKind.CAMPAIGN_COMPLETED,
            campaign_id,
            payload={"status": "complete"},
        )
        _publish(store)
    print(
        f"status={result.status.value} LB={result.certified_lower_bound:.3f} "
        f"UB={_number(result.validated_upper_bound).strip()} "
        f"gap={('-' if result.relative_gap is None else f'{100 * result.relative_gap:.3f}%')} "
        f"time={run_result.total_seconds:.2f}s output={output_path}"
    )


def _number(value: float | None) -> str:
    return "            -" if value is None else f"{value:13,.1f}"


def _clock(seconds: float) -> str:
    value = max(0, int(round(seconds)))
    return f"{value // 60:02d}:{value % 60:02d}"


def _publish(store: OptimizationLiveStore) -> None:
    store.publish(reduce_optimization_events(store.read_events()))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        raise SystemExit(130)
